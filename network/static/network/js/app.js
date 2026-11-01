/**
 * SMyT · Sistema de Metro y Transporte — Arquitectura Frontend y Motor de Tiempo Real
 *
 * Estructura modular:
 * 1. NetworkStore: Estado centralizado de datos (estaciones, líneas, horarios, polígonos, alertas)
 *    estrictamente desacoplado de la capa de visualización.
 * 2. TrainSimulationEngine: Simulación física cinemática a 60 fps de trenes de Metro y
 *    autobuses articulados, incluyendo inversión en terminales, circuito cerrado en Línea A
 *    (Ordinario 150 s en 124 estaciones + Premium 300 s en 20 estaciones clave) y respeto
 *    de tramos clausurados (Línea C: 21 operativas / 13 cerradas permanentemente).
 * 3. SchematicMapEngine: Renderizador vectorial SVG interactivo (13020 x 4700) con zoom/pan,
 *    simbología de ingeniería civil y edición cartográfica arrastrando nodos y polígonos.
 * 4. GeoMapEngine: Vista geográfica alternativa sobre Leaflet con coordenadas (lat, lng).
 * 5. BlueprintRenderer: Generador de corte transversal arquitectónico/ingenieril en SVG.
 */

(function () {
    "use strict";

    // =========================================================================
    // 1. ESTADO DE DATOS DE LA RED (Separado de la lógica de visualización)
    // =========================================================================
    const NetworkStore = {
        cityOutlines: [],
        lines: [],
        linesByCode: new Map(),
        stations: [],
        stationsById: new Map(),
        sortedStations: [],
        alerts: [],
        kpis: {},

        // Filtros y estado de interfaz
        viewMode: "schematic",       // 'schematic' | 'geo'
        colorMode: "line",           // 'line' | 'infra'
        networkFilter: "all",        // 'all' | 'metro' | 'bus_articulado'
        infraFilter: "all",          // 'all' | 'subterraneo' | 'tunel_profundo' | 'superficial' | 'elevado' | 'closed_permanent' | 'construction'
        isolatedLineCode: null,      // Código de línea aislada o null
        showLabels: true,
        editMode: false,
        trackWidthScale: 1.0,
        draftRouteStops: [],
        activeLineCode: "1",
        selectedStationId: null,
        selectedTrainId: null,
        simSpeedMultiplier: 1,
        operationalTimeSec: 6 * 3600 + 30 * 60, // 06:30:00 AM

        async fetchAll(customFetch = globalThis.fetch) {
            let resp;
            const apiBase = (typeof ApiClient !== "undefined" && typeof ApiClient.getApiBase === "function") ? ApiClient.getApiBase() : "";
            const isStaticDefault = (typeof window !== "undefined" && (window.location.hostname.includes("github.io") || window.location.protocol === "file:")) && !apiBase;

            if (!isStaticDefault) {
                try {
                    const url = apiBase ? `${apiBase}/api/network/` : "/api/network/";
                    resp = await customFetch(url);
                    if (!resp || !resp.ok) {
                        throw new Error("Fallback to static data");
                    }
                    if (typeof ApiClient !== "undefined" && typeof ApiClient.updateConnectionStatusBadge === "function") {
                        ApiClient.updateConnectionStatusBadge(true);
                    }
                } catch (err) {
                    resp = await customFetch("data/network.json");
                    if (typeof ApiClient !== "undefined" && typeof ApiClient.updateConnectionStatusBadge === "function") {
                        ApiClient.updateConnectionStatusBadge(false);
                    }
                }
            } else {
                resp = await customFetch("data/network.json");
                if (typeof ApiClient !== "undefined" && typeof ApiClient.updateConnectionStatusBadge === "function") {
                    ApiClient.updateConnectionStatusBadge(false);
                }
            }
            if (!resp || !resp.ok) throw new Error("Error cargando topología de la red SMyT");
            const data = await resp.json();
            this.hydrate(data);

            // Re-aplicar capas de edición guardadas por el usuario en localStorage
            if (typeof ApiClient !== "undefined" && typeof ApiClient.applyStoredEditsToStore === "function") {
                ApiClient.applyStoredEditsToStore();
            }
            return data;
        },

        hydrate(data) {
            this.cityOutlines = data.city_outlines || [];
            this.lines = data.lines || [];
            this.stations = data.stations || [];
            this.alerts = data.alerts || [];
            this.kpis = data.kpis || {};

            this.linesByCode.clear();
            for (const ln of this.lines) {
                this.linesByCode.set(ln.code, ln);
            }
            if (this.lines.length > 0 && (!this.activeLineCode || !this.linesByCode.has(this.activeLineCode))) {
                this.activeLineCode = this.lines[0].code;
            }

            this.stationsById.clear();
            for (const st of this.stations) {
                this.stationsById.set(st.id, st);
            }

            this.sortedStations = [...this.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));
        },

        getSortedStations() {
            if (!this.sortedStations || this.sortedStations.length !== this.stations.length) {
                this.sortedStations = [...this.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));
            }
            return this.sortedStations;
        },

        createCorrespondencePayload(stationId, targetLineOrStation2) {
            if (Array.isArray(targetLineOrStation2)) {
                return {
                    station_id: stationId,
                    target_line_codes: targetLineOrStation2.map(c => String(c).trim().toUpperCase()),
                };
            }
            if (typeof targetLineOrStation2 === "string") {
                return {
                    station_id: stationId,
                    target_line_code: targetLineOrStation2.trim().toUpperCase(),
                };
            }
            return {
                station_id: stationId,
                station_id_2: targetLineOrStation2,
            };
        }
    };

    // =========================================================================
    // 1B. CLIENTE DE API CON PERSISTENCIA DUAL (ONLINE / BACKEND + OFFLINE / GITHUB PAGES)
    // =========================================================================
    const ApiClient = {
        STORAGE_KEY: "simma_user_network_edits_v1",
        isServerAvailable: null,

        getApiBase() {
            if (typeof window === "undefined") return "";
            try {
                const stored = localStorage.getItem("metrito_api_url");
                if (stored && stored.trim()) {
                    return stored.trim().replace(/\/+$/, "");
                }
                if (window.METRITO_API_URL && window.METRITO_API_URL.trim()) {
                    return window.METRITO_API_URL.trim().replace(/\/+$/, "");
                }
            } catch (e) {}
            if (typeof window !== "undefined" && window.location.hostname.includes("vercel.app")) {
                return "";
            }
            return "";
        },

        setApiBase(url) {
            try {
                if (!url || !url.trim()) {
                    localStorage.removeItem("metrito_api_url");
                } else {
                    localStorage.setItem("metrito_api_url", url.trim().replace(/\/+$/, ""));
                }
            } catch (e) {}
            this.updateConnectionStatusBadge();
        },

        initBadgeClickHandler() {
            if (typeof document === "undefined") return;
            const badge = document.getElementById("storageSyncBadge");
            if (!badge || badge._hasClickHandler) return;
            badge._hasClickHandler = true;
            badge.style.cursor = "pointer";
            badge.addEventListener("click", () => {
                const current = this.getApiBase();
                const input = prompt(
                    "Conectar con Base de Datos en Vercel:\n\nIngresa la URL de tu backend en Vercel (ejemplo: https://tu-proyecto.vercel.app)\no deja el campo vacío para operar en Modo Autónomo / GitHub Pages (almacenamiento local):",
                    current || ""
                );
                if (input !== null) {
                    this.setApiBase(input);
                    if (input.trim()) {
                        showToast("URL de Vercel configurada. Comprobando conexión...");
                        NetworkStore.fetchAll().then(() => {
                            showToast("✓ Conectado a Vercel y base de datos");
                        }).catch(() => {
                            showToast("No se pudo conectar a la API de Vercel. Operando en modo local.");
                        });
                    } else {
                        showToast("Modo autónomo activado (GitHub Pages + almacenamiento local).");
                        NetworkStore.fetchAll();
                    }
                }
            });
        },

        getStoredEdits() {
            try {
                const raw = localStorage.getItem(this.STORAGE_KEY);
                return raw ? JSON.parse(raw) : { stations: {}, lines: {}, createdStations: [], createdLines: [], cityOutlines: {} };
            } catch (e) {
                return { stations: {}, lines: {}, createdStations: [], createdLines: [], cityOutlines: {} };
            }
        },

        saveStoredEdits(edits) {
            try {
                localStorage.setItem(this.STORAGE_KEY, JSON.stringify(edits));
                this.updateConnectionStatusBadge();
            } catch (e) {
                console.warn("No se pudo guardar en localStorage:", e);
            }
        },

        clearStoredEdits() {
            try {
                localStorage.removeItem(this.STORAGE_KEY);
                this.updateConnectionStatusBadge();
            } catch (e) {}
        },

        updateConnectionStatusBadge(isOnline) {
            if (typeof isOnline === "boolean") {
                this.isServerAvailable = isOnline;
            }
            const badge = document.getElementById("storageSyncBadge");
            if (!badge) return;
            badge.style.cursor = "pointer";
            const edits = this.getStoredEdits();
            const editCount = (edits.createdStations?.length || 0) +
                (edits.createdLines?.length || 0) +
                Object.keys(edits.stations || {}).length +
                Object.keys(edits.lines || {}).length;

            const apiBase = this.getApiBase();
            if (this.isServerAvailable) {
                const target = apiBase ? "Vercel API" : "Servidor";
                badge.className = "storage-sync-pill online";
                badge.innerHTML = `<span class="sync-dot online"></span> Conectado a ${target} (${editCount} cambios)`;
                badge.title = `Sincronización activa con la base de datos (${apiBase || "mismo origen"}). Clic para cambiar URL de Vercel.`;
            } else if (apiBase) {
                badge.className = "storage-sync-pill local";
                badge.innerHTML = `<span class="sync-dot local"></span> Vercel desconectado (${editCount} cambios locales)`;
                badge.title = `No se pudo conectar a ${apiBase}. Clic para reconfigurar URL de Vercel.`;
            } else {
                badge.className = "storage-sync-pill local";
                badge.innerHTML = `<span class="sync-dot local"></span> GitHub Pages / Autónomo (${editCount} cambios guardados)`;
                badge.title = "Guardado local activo en el navegador. Haz clic para conectar con tu base de datos en Vercel.";
            }
        },

        applyStoredEditsToStore() {
            const edits = this.getStoredEdits();
            if (!edits) return false;
            let applied = false;

            // 1. Estaciones creadas por el usuario
            if (Array.isArray(edits.createdStations)) {
                for (const s of edits.createdStations) {
                    if (!NetworkStore.stationsById.has(s.id)) {
                        NetworkStore.stations.push(s);
                        NetworkStore.stationsById.set(s.id, s);
                        applied = true;
                    }
                }
            }

            // 2. Líneas creadas por el usuario
            if (Array.isArray(edits.createdLines)) {
                for (const l of edits.createdLines) {
                    if (!NetworkStore.linesByCode.has(l.code)) {
                        NetworkStore.lines.push(l);
                        NetworkStore.linesByCode.set(l.code, l);
                        applied = true;
                    }
                }
            }

            // 3. Modificaciones en estaciones existentes
            if (edits.stations && typeof edits.stations === "object") {
                for (const [stIdStr, patch] of Object.entries(edits.stations)) {
                    const stId = Number(stIdStr);
                    const st = NetworkStore.stationsById.get(stId);
                    if (st) {
                        Object.assign(st, patch);
                        applied = true;
                    }
                }
            }

            // 4. Modificaciones en líneas y trayectos
            if (edits.lines && typeof edits.lines === "object") {
                for (const [lineCode, patch] of Object.entries(edits.lines)) {
                    const ln = NetworkStore.linesByCode.get(lineCode);
                    if (ln) {
                        Object.assign(ln, patch);
                        applied = true;
                    }
                }
            }

            // 5. Polígonos urbanos
            if (edits.cityOutlines && typeof edits.cityOutlines === "object") {
                for (const [idStr, patch] of Object.entries(edits.cityOutlines)) {
                    const id = Number(idStr);
                    const outline = (NetworkStore.cityOutlines || []).find(o => o.id === id);
                    if (outline) {
                        Object.assign(outline, patch);
                        applied = true;
                    }
                }
            }

            if (applied) {
                NetworkStore.sortedStations = [...NetworkStore.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));
            }
            this.updateConnectionStatusBadge();
            return applied;
        },

        async post(endpoint, payload) {
            const apiBase = this.getApiBase();
            const isStaticHost = (typeof window !== "undefined" && (window.location.hostname.includes("github.io") || window.location.protocol === "file:")) && !apiBase;

            if (!isStaticHost && this.isServerAvailable !== false) {
                try {
                    const fullUrl = apiBase ? `${apiBase}${endpoint}` : endpoint;
                    const resp = await fetch(fullUrl, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload || {})
                    });

                    // Si responde 405 Method Not Allowed o 404 (hosting estático):
                    if (resp.status === 405 || resp.status === 404) {
                        console.info(`Endpoint ${endpoint} no soportado (${resp.status}). Activando persistencia local.`);
                        this.isServerAvailable = false;
                        const localRes = this.applyLocalMutation(endpoint, payload, true);
                        this.updateConnectionStatusBadge(false);
                        return localRes;
                    }

                    const data = await resp.json().catch(() => ({}));
                    if (resp.ok && (data.ok !== false)) {
                        this.isServerAvailable = true;
                        this.applyLocalMutation(endpoint, payload, true);
                        this.updateConnectionStatusBadge(true);
                        return { ok: true, server: true, data };
                    }

                    if (resp.status === 400) {
                        return { ok: false, error: data.error || "Datos inválidos", status: 400 };
                    }

                    return { ok: false, error: data.error || `Error ${resp.status} del servidor`, status: resp.status };
                } catch (netErr) {
                    console.warn(`Servidor no accesible para ${endpoint}. Activando persistencia local:`, netErr);
                    this.isServerAvailable = false;
                    const localRes = this.applyLocalMutation(endpoint, payload, true);
                    this.updateConnectionStatusBadge(false);
                    return localRes;
                }
            }

            // Modo offline / GitHub Pages autónomo
            const localRes = this.applyLocalMutation(endpoint, payload, true);
            this.updateConnectionStatusBadge(false);
            return localRes;
        },

        applyLocalMutation(endpoint, payload, updateStorage = true) {
            const edits = this.getStoredEdits();

            // A) Desconectar correspondencia
            if (endpoint.includes("/correspondences") && (payload?.action === "remove" || payload?.action === "delete")) {
                const stId = Number(payload.station_id);
                const lineCode = String(payload.target_line_code || "").trim();
                const st = NetworkStore.stationsById.get(stId);
                const ln = NetworkStore.linesByCode.get(lineCode);

                if (!st) return { ok: false, error: "Estación no encontrada" };

                st.lines = (st.lines || []).filter(c => String(c).trim().toUpperCase() !== lineCode.toUpperCase());
                st.is_transfer = st.lines.length > 1;
                if (Array.isArray(st.terminal_lines)) {
                    st.terminal_lines = st.terminal_lines.filter(c => String(c).trim().toUpperCase() !== lineCode.toUpperCase());
                    st.is_terminal = st.terminal_lines.length > 0;
                }
                st.is_custom_modified = true;

                if (ln && Array.isArray(ln.stops)) {
                    ln.stops = ln.stops.filter(s => s.station_id !== stId && s.station_code !== st.code);
                    ln.stops.forEach((s, idx) => { s.sequence = idx; });
                    ln.declared_stations_count = ln.stops.length;
                    ln.is_custom_modified = true;

                    if (updateStorage) {
                        edits.lines[lineCode] = { stops: ln.stops, declared_stations_count: ln.declared_stations_count, is_custom_modified: true };
                    }
                }

                if (updateStorage) {
                    edits.stations[stId] = {
                        lines: st.lines,
                        is_transfer: st.is_transfer,
                        terminal_lines: st.terminal_lines,
                        is_terminal: st.is_terminal,
                        is_custom_modified: true
                    };
                    this.saveStoredEdits(edits);
                }

                return {
                    ok: true,
                    server: false,
                    removed: true,
                    station_id: stId,
                    station_name: st.name,
                    line_code: lineCode,
                    served_lines: st.lines
                };
            }

            // B) Agregar correspondencia(s)
            if (endpoint.includes("/correspondences")) {
                const st1Id = Number(payload.station_id || payload.station1 || payload.station_id_1);
                const st2Id = Number(payload.station_id_2 || payload.station2);
                const st1 = NetworkStore.stationsById.get(st1Id);

                if (st1 && st2Id) {
                    const st2 = NetworkStore.stationsById.get(st2Id);
                    if (st2) {
                        const combinedLines = Array.from(new Set([...(st1.lines || []), ...(st2.lines || [])]));
                        st1.lines = combinedLines;
                        st2.lines = combinedLines;
                        st1.is_transfer = combinedLines.length > 1;
                        st2.is_transfer = combinedLines.length > 1;
                        st1.is_custom_modified = true;
                        st2.is_custom_modified = true;

                        if (updateStorage) {
                            edits.stations[st1Id] = { lines: st1.lines, is_transfer: st1.is_transfer, is_custom_modified: true };
                            edits.stations[st2Id] = { lines: st2.lines, is_transfer: st2.is_transfer, is_custom_modified: true };
                            this.saveStoredEdits(edits);
                        }

                        return {
                            ok: true,
                            server: false,
                            station_1: st1.name,
                            station_2: st2.name,
                            is_transfer: true,
                            combined_lines: combinedLines
                        };
                    }
                }

                if (st1) {
                    const rawLines = payload.target_line_codes || payload.target_line_code || payload.line_code || payload.lines;
                    const linesToAdd = Array.isArray(rawLines) ? rawLines : [rawLines].filter(Boolean);
                    const currentSet = new Set((st1.lines || []).map(c => String(c).trim().toUpperCase()));
                    const added = [];

                    for (const lc of linesToAdd) {
                        const codeStr = String(lc).trim().toUpperCase();
                        if (!currentSet.has(codeStr)) {
                            currentSet.add(codeStr);
                            added.push(codeStr);
                        }
                    }

                    if (added.length === 0) {
                        return { ok: false, error: "La estación ya pertenece a la(s) línea(s) seleccionada(s)." };
                    }

                    st1.lines = Array.from(currentSet);
                    st1.is_transfer = st1.lines.length > 1;
                    st1.is_custom_modified = true;

                    for (const code of added) {
                        const ln = NetworkStore.linesByCode.get(code);
                        if (ln) {
                            if (!Array.isArray(ln.stops)) ln.stops = [];
                            const hasStop = ln.stops.some(s => s.station_id === st1.id || s.station_code === st1.code);
                            if (!hasStop) {
                                ln.stops.push({
                                    id: Date.now() + Math.floor(Math.random() * 1000),
                                    station_id: st1.id,
                                    station_code: st1.code,
                                    station_name: st1.name,
                                    sequence: ln.stops.length,
                                    branch: "main",
                                    waypoints: []
                                });
                                ln.declared_stations_count = ln.stops.length;
                                ln.is_custom_modified = true;
                                if (updateStorage) {
                                    edits.lines[code] = { stops: ln.stops, declared_stations_count: ln.declared_stations_count, is_custom_modified: true };
                                }
                            }
                        }
                    }

                    if (updateStorage) {
                        edits.stations[st1Id] = { lines: st1.lines, is_transfer: st1.is_transfer, is_custom_modified: true };
                        this.saveStoredEdits(edits);
                    }

                    return {
                        ok: true,
                        server: false,
                        station_id: st1.id,
                        station_name: st1.name,
                        is_transfer: true,
                        added_lines: added,
                        served_lines: st1.lines,
                        total_lines_count: st1.lines.length
                    };
                }
            }

            // C) Actualizar estación
            if (endpoint.includes("/stations/") && endpoint.includes("/update/")) {
                const match = endpoint.match(/\/stations\/(\d+)\/update\//);
                const stId = match ? Number(match[1]) : Number(payload?.id);
                const st = NetworkStore.stationsById.get(stId);
                if (st) {
                    Object.assign(st, payload);
                    st.is_custom_modified = true;
                    if (updateStorage) {
                        if (!edits.stations[stId]) edits.stations[stId] = {};
                        Object.assign(edits.stations[stId], payload, { is_custom_modified: true });
                        this.saveStoredEdits(edits);
                    }
                    return { ok: true, server: false, station: st };
                }
            }

            // D) Crear estación
            if (endpoint.includes("/stations/create/")) {
                const newId = Date.now();
                const newSt = {
                    id: newId,
                    code: payload.code || `estacion-custom-${newId}`,
                    name: payload.name || "Nueva Estación",
                    x: Number(payload.x) || 2120.0,
                    y: Number(payload.y) || 1860.0,
                    lat: Number(payload.lat) || 19.42,
                    lng: Number(payload.lng) || -99.15,
                    infrastructure_type: payload.infrastructure_type || "subterraneo",
                    operational_status: payload.operational_status || "operational",
                    depth_meters: Number(payload.depth_meters) || -12.0,
                    platform_type: payload.platform_type || "central",
                    platform_count: Number(payload.platform_count) || 2,
                    has_psd: Boolean(payload.has_psd),
                    is_transfer: false,
                    is_terminal: false,
                    is_premium_stop: false,
                    icon_tags: Array.isArray(payload.icon_tags) ? payload.icon_tags : [],
                    terminal_lines: [],
                    lines: payload.line_code ? [payload.line_code] : [],
                    is_user_created: true,
                    is_custom_modified: true
                };

                NetworkStore.stations.push(newSt);
                NetworkStore.stationsById.set(newSt.id, newSt);
                NetworkStore.sortedStations = [...NetworkStore.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));

                if (payload.line_code) {
                    const ln = NetworkStore.linesByCode.get(payload.line_code);
                    if (ln) {
                        if (!Array.isArray(ln.stops)) ln.stops = [];
                        ln.stops.push({
                            id: Date.now() + 1,
                            station_id: newSt.id,
                            station_code: newSt.code,
                            station_name: newSt.name,
                            sequence: ln.stops.length,
                            branch: "main",
                            waypoints: []
                        });
                        ln.declared_stations_count = ln.stops.length;
                        ln.is_custom_modified = true;
                        if (updateStorage) {
                            edits.lines[payload.line_code] = { stops: ln.stops, declared_stations_count: ln.declared_stations_count, is_custom_modified: true };
                        }
                    }
                }

                if (updateStorage) {
                    edits.createdStations.push(newSt);
                    this.saveStoredEdits(edits);
                }

                return { ok: true, server: false, station: newSt };
            }

            // E) Eliminar estación
            if (endpoint.includes("/stations/") && endpoint.includes("/delete/")) {
                const match = endpoint.match(/\/stations\/(\d+)\/delete\//);
                const stId = match ? Number(match[1]) : 0;
                NetworkStore.stations = NetworkStore.stations.filter(s => s.id !== stId);
                NetworkStore.stationsById.delete(stId);
                NetworkStore.sortedStations = [...NetworkStore.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));

                for (const ln of NetworkStore.lines) {
                    if (Array.isArray(ln.stops)) {
                        ln.stops = ln.stops.filter(s => s.station_id !== stId);
                        ln.stops.forEach((s, idx) => { s.sequence = idx; });
                    }
                }

                if (updateStorage) {
                    edits.createdStations = edits.createdStations.filter(s => s.id !== stId);
                    delete edits.stations[stId];
                    this.saveStoredEdits(edits);
                }

                return { ok: true, server: false, removed: true };
            }

            // F) Actualizar trayecto de línea
            if (endpoint.includes("/lines/") && endpoint.includes("/route/")) {
                const match = endpoint.match(/\/lines\/([^\/]+)\/route\//);
                const lineCode = match ? decodeURIComponent(match[1]) : payload?.line_code;
                const ln = NetworkStore.linesByCode.get(lineCode);
                if (ln) {
                    if (payload?.clear_all_waypoints && Array.isArray(ln.stops)) {
                        ln.stops.forEach(s => { s.waypoints = []; });
                    }
                    if (payload?.stops) {
                        ln.stops = payload.stops;
                    }
                    ln.is_custom_modified = true;
                    if (updateStorage) {
                        edits.lines[lineCode] = { stops: ln.stops, is_custom_modified: true };
                        this.saveStoredEdits(edits);
                    }
                    return { ok: true, server: false, line_code: lineCode };
                }
            }

            // G) Actualizar waypoints de tramo
            if (endpoint.includes("/line-segments/") && endpoint.includes("/waypoints/")) {
                const match = endpoint.match(/\/line-segments\/(\d+)\/waypoints\//);
                const lsId = match ? Number(match[1]) : 0;
                for (const ln of NetworkStore.lines) {
                    if (Array.isArray(ln.stops)) {
                        const stop = ln.stops.find(s => s.id === lsId);
                        if (stop) {
                            stop.waypoints = payload.waypoints || [];
                            ln.is_custom_modified = true;
                            if (updateStorage) {
                                edits.lines[ln.code] = { stops: ln.stops, is_custom_modified: true };
                                this.saveStoredEdits(edits);
                            }
                            return { ok: true, server: false, id: lsId, waypoints: stop.waypoints };
                        }
                    }
                }
                return { ok: true, server: false };
            }

            // H) Crear nueva línea
            if (endpoint.includes("/lines/create/")) {
                const newLine = {
                    id: Date.now(),
                    code: payload.code,
                    name: payload.name,
                    color: payload.color || "#0052ff",
                    text_color: "#ffffff",
                    network_type: payload.network_type || "metro",
                    line_subtype: payload.line_subtype || "convencional",
                    status: "operational",
                    frequency_seconds: 180,
                    stops: [],
                    is_user_created: true,
                    is_custom_modified: true
                };
                NetworkStore.lines.push(newLine);
                NetworkStore.linesByCode.set(newLine.code, newLine);

                if (updateStorage) {
                    edits.createdLines.push(newLine);
                    this.saveStoredEdits(edits);
                }
                return { ok: true, server: false, line: newLine };
            }

            // I) Conectar tramo entre estaciones
            if (endpoint.includes("/line-segments/create/")) {
                const lineCode = payload.line_code;
                const fromId = Number(payload.from_station_id);
                const toId = Number(payload.to_station_id);
                const ln = NetworkStore.linesByCode.get(lineCode);
                const st1 = NetworkStore.stationsById.get(fromId);
                const st2 = NetworkStore.stationsById.get(toId);

                if (ln && st1 && st2) {
                    if (!Array.isArray(ln.stops)) ln.stops = [];
                    const hasFrom = ln.stops.some(s => s.station_id === fromId);
                    const hasTo = ln.stops.some(s => s.station_id === toId);

                    if (!hasFrom) {
                        ln.stops.push({
                            id: Date.now() + 1,
                            station_id: fromId,
                            station_code: st1.code,
                            station_name: st1.name,
                            sequence: ln.stops.length,
                            branch: "main",
                            waypoints: []
                        });
                    }
                    if (!hasTo) {
                        ln.stops.push({
                            id: Date.now() + 2,
                            station_id: toId,
                            station_code: st2.code,
                            station_name: st2.name,
                            sequence: ln.stops.length,
                            branch: "main",
                            waypoints: []
                        });
                    }
                    ln.declared_stations_count = ln.stops.length;
                    ln.is_custom_modified = true;

                    if (!st1.lines.includes(lineCode)) st1.lines.push(lineCode);
                    if (!st2.lines.includes(lineCode)) st2.lines.push(lineCode);
                    st1.is_transfer = st1.lines.length > 1;
                    st2.is_transfer = st2.lines.length > 1;

                    if (updateStorage) {
                        edits.lines[lineCode] = { stops: ln.stops, is_custom_modified: true };
                        edits.stations[fromId] = { lines: st1.lines, is_transfer: st1.is_transfer };
                        edits.stations[toId] = { lines: st2.lines, is_transfer: st2.is_transfer };
                        this.saveStoredEdits(edits);
                    }
                    return { ok: true, server: false, line_code: lineCode };
                }
            }

            // J) Actualizar propiedades de línea
            if (endpoint.includes("/lines/") && endpoint.includes("/update/")) {
                const match = endpoint.match(/\/lines\/([^\/]+)\/update\//);
                const lineCode = match ? decodeURIComponent(match[1]) : payload?.code;
                const ln = NetworkStore.linesByCode.get(lineCode);
                if (ln) {
                    Object.assign(ln, payload);
                    ln.is_custom_modified = true;
                    if (updateStorage) {
                        if (!edits.lines[lineCode]) edits.lines[lineCode] = {};
                        Object.assign(edits.lines[lineCode], payload, { is_custom_modified: true });
                        this.saveStoredEdits(edits);
                    }
                    return { ok: true, server: false, line_code: lineCode };
                }
            }

            // K) Actualizar polígono urbano
            if (endpoint.includes("/city-outlines/") && endpoint.includes("/update/")) {
                const match = endpoint.match(/\/city-outlines\/(\d+)\/update\//);
                const outId = match ? Number(match[1]) : 0;
                const outline = (NetworkStore.cityOutlines || []).find(o => o.id === outId);
                if (outline) {
                    if (payload.polygon_points) outline.polygon_points = payload.polygon_points;
                    if (updateStorage) {
                        edits.cityOutlines[outId] = { polygon_points: outline.polygon_points };
                        this.saveStoredEdits(edits);
                    }
                    return { ok: true, server: false, id: outId };
                }
            }

            // L) Guardar capa
            if (endpoint.includes("/editor/save/") || endpoint.includes("/user-edits/save/")) {
                this.saveStoredEdits(edits);
                return {
                    ok: true,
                    server: false,
                    result: {
                        created_stations_count: (edits.createdStations || []).length,
                        created_lines_count: (edits.createdLines || []).length,
                        modified_stations_count: Object.keys(edits.stations || {}).length,
                        route_overrides_count: Object.keys(edits.lines || {}).length
                    }
                };
            }

            // M) Descartar cambios
            if (endpoint.includes("/editor/discard/") || endpoint.includes("/user-edits/discard/") || endpoint.includes("/network/reset/")) {
                this.clearStoredEdits();
                return { ok: true, server: false, discarded: true };
            }

            return { ok: true, server: false };
        },

        exportEditsAsJson() {
            const edits = this.getStoredEdits();
            const payload = {
                version: 1,
                exported_at: new Date().toISOString(),
                description: "Capa de modificaciones de usuario - Metrito SMyT",
                data: edits
            };
            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `metrito_red_usuario_${new Date().toISOString().slice(0, 10)}.json`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
            showToast("✓ Archivo de respaldo JSON descargado");
        },

        async importEditsFromFile(file) {
            try {
                const text = await file.text();
                const parsed = JSON.parse(text);
                const edits = parsed.data || parsed;
                if (!edits || typeof edits !== "object") {
                    throw new Error("Estructura JSON inválida");
                }
                this.saveStoredEdits(edits);
                this.applyStoredEditsToStore();
                await refreshNetworkDataAndRender(true);
                showToast("✓ Capa de usuario importada exitosamente");
            } catch (err) {
                console.error("Error al importar JSON:", err);
                showToast("El archivo seleccionado no tiene un formato válido");
            }
        }
    };


    // =========================================================================
    // 1B. GESTOR DE HISTORIAL Y ACCIONES (DESHACER / REHACER - Ctrl+Z / Ctrl+Y)
    // =========================================================================
    const HistoryManager = {
        undoStack: [],
        redoStack: [],
        maxStack: 40,

        push(action) {
            this.undoStack.push(action);
            if (this.undoStack.length > this.maxStack) {
                this.undoStack.shift();
            }
            this.redoStack = [];
            this.updateButtons();
        },

        canUndo() {
            return this.undoStack.length > 0;
        },

        canRedo() {
            return this.redoStack.length > 0;
        },

        updateButtons() {
            const btnUndo = document.getElementById("btnEditorUndo");
            const btnRedo = document.getElementById("btnEditorRedo");
            if (btnUndo) btnUndo.disabled = !this.canUndo();
            if (btnRedo) btnRedo.disabled = !this.canRedo();
        },

        async undo() {
            if (!this.canUndo()) return;
            const action = this.undoStack.pop();
            try {
                if (action.type === "move_station") {
                    const st = NetworkStore.stationsById.get(action.stationId);
                    if (st) {
                        await ApiClient.post(`/api/stations/${action.stationId}/update/`, { x: action.oldX, y: action.oldY });
                        st.x = action.oldX;
                        st.y = action.oldY;
                    }
                } else if (action.type === "waypoints") {
                    await ApiClient.post(`/api/line-segments/${action.lsId}/waypoints/`, { waypoints: action.oldWaypoints });
                } else if (action.type === "route") {
                    await ApiClient.post(`/api/lines/${action.lineCode}/route/`, { stops: action.oldStops });
                }
                this.redoStack.push(action);
                await refreshNetworkDataAndRender();
                showToast(`Acción deshecha: ${action.description || action.type}`);
            } catch (err) {
                console.error("Error en Deshacer:", err);
                showToast("Error al deshacer acción");
            } finally {
                this.updateButtons();
            }
        },

        async redo() {
            if (!this.canRedo()) return;
            const action = this.redoStack.pop();
            try {
                if (action.type === "move_station") {
                    const st = NetworkStore.stationsById.get(action.stationId);
                    if (st) {
                        await ApiClient.post(`/api/stations/${action.stationId}/update/`, { x: action.newX, y: action.newY });
                        st.x = action.newX;
                        st.y = action.newY;
                    }
                } else if (action.type === "waypoints") {
                    await ApiClient.post(`/api/line-segments/${action.lsId}/waypoints/`, { waypoints: action.newWaypoints });
                } else if (action.type === "route") {
                    await ApiClient.post(`/api/lines/${action.lineCode}/route/`, { stops: action.newStops });
                }
                this.undoStack.push(action);
                await refreshNetworkDataAndRender();
                showToast(`Acción rehecha: ${action.description || action.type}`);
            } catch (err) {
                console.error("Error en Rehacer:", err);
                showToast("Error al rehacer acción");
            } finally {
                this.updateButtons();
            }
        }
    };

    function renderCorrespondenceLinesChecklist(checklistEl, selectEl, availableLines, remainingQuota) {
        const lines = Array.isArray(availableLines) ? availableLines : [];

        // 1. POBLAR SELECT DESPLEGABLE (Selector individual clásico y directo)
        if (selectEl) {
            if (remainingQuota <= 0) {
                selectEl.disabled = true;
                selectEl.innerHTML = '<option value="">(Límite de 10 correspondencias alcanzado)</option>';
            } else if (lines.length === 0) {
                selectEl.disabled = true;
                selectEl.innerHTML = '<option value="">(La estación ya pertenece a todas las líneas)</option>';
            } else {
                selectEl.disabled = false;
                const options = ['<option value="">-- Selecciona una línea destino --</option>'];
                for (const l of lines) {
                    options.push(`<option value="${escapeHtml(l.code)}">Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`);
                }
                selectEl.innerHTML = options.join("");
            }

            // Sincronización bidireccional: al elegir en el select, sincronizar casilla si existe checklist
            if (!selectEl.dataset.boundCorrSync) {
                selectEl.dataset.boundCorrSync = "true";
                selectEl.addEventListener("change", (e) => {
                    const val = e.target.value;
                    const hostChecklist = selectEl.id === "corrTargetLineSelect"
                        ? document.getElementById("corrTargetLinesChecklist")
                        : document.getElementById("modalCorrLinesChecklist");
                    if (hostChecklist) {
                        const cbs = hostChecklist.querySelectorAll(".js-corr-line-checkbox");
                        cbs.forEach(cb => {
                            cb.checked = Boolean(val && cb.value === val);
                        });
                    }
                });
            }
        }

        // 2. POBLAR CHECKLIST DE SELECCIÓN MÚLTIPLE (Opcional, hasta remainingQuota líneas)
        if (checklistEl) {
            if (remainingQuota <= 0) {
                checklistEl.innerHTML = `<div style="font-size:11.5px; color:#b91c1c; font-weight:600; padding:6px; background:#fef2f2; border-radius:4px;">⚠️ Límite alcanzado: Esta estación ya tiene el máximo permitido de 10 correspondencias. Desconecta alguna línea si deseas asociar otra.</div>`;
            } else if (lines.length === 0) {
                checklistEl.innerHTML = `<div style="font-size:11.5px; color:#64748b; font-style:italic; padding:6px;">La estación ya pertenece a todas las líneas del sistema.</div>`;
            } else {
                checklistEl.innerHTML = lines.map(l => {
                    const bg = l.color || "#0052ff";
                    const fg = typeof getBadgeTextColor === "function" ? getBadgeTextColor(bg, "#FFFFFF") : "#FFFFFF";
                    return `
                        <label class="corr-line-checkbox-item" style="display:flex; align-items:center; gap:8px; padding:4px 6px; border-radius:4px; cursor:pointer; font-size:12px; user-select:none;">
                            <input type="checkbox" class="js-corr-line-checkbox" value="${escapeHtml(l.code)}" style="cursor:pointer; accent-color:var(--primary, #0052ff);">
                            <span style="background:${bg}; color:${fg}; font-weight:700; font-size:10px; padding:1px 6px; border-radius:3px; min-width:22px; text-align:center;">
                                ${escapeHtml(l.code)}
                            </span>
                            <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#1e293b; font-weight:500;">
                                ${escapeHtml(l.name)}
                            </span>
                        </label>
                    `;
                }).join("");

                const checkboxes = checklistEl.querySelectorAll(".js-corr-line-checkbox");
                checkboxes.forEach(cb => {
                    cb.addEventListener("change", (e) => {
                        const checked = Array.from(checkboxes).filter(c => c.checked);
                        if (checked.length > remainingQuota) {
                            e.target.checked = false;
                            showToast(`Máximo 10 correspondencias por estación (solo puedes seleccionar hasta ${remainingQuota} en esta estación).`);
                            return;
                        }
                        if (selectEl) {
                            if (checked.length === 1) {
                                selectEl.value = checked[0].value;
                            } else {
                                selectEl.value = "";
                            }
                        }
                    });
                });
            }
        }
    }

    // =========================================================================
    // 1C. CONTROLADOR DE HERRAMIENTAS ACTIVAS DEL EDITOR VISUAL
    // =========================================================================
    const VisualEditorTools = {
        activeTool: null, // 'add_station' | 'connect_segment' | 'add_correspondence'
        segmentSourceStationId: null,
        correspondenceSourceStationId: null,
        pendingLineCaller: null, // 'station' | 'segment' | null

        getActiveLineCode() {
            return NetworkStore.activeLineCode ||
                document.getElementById("edActiveLineSelect")?.value ||
                document.getElementById("editLineSelect")?.value ||
                (NetworkStore.lines[0] ? NetworkStore.lines[0].code : "1");
        },

        setActiveLine(code) {
            if (!code) return;
            NetworkStore.activeLineCode = String(code);
            const sel = document.getElementById("edActiveLineSelect");
            if (sel && sel.value !== code) sel.value = code;
            const dot = document.getElementById("activeLineBadgeDot");
            const ln = NetworkStore.linesByCode.get(String(code));
            if (dot && ln) dot.style.background = ln.color || "#0055A4";
            if (NetworkStore.editMode) {
                SchematicMapEngine.renderEditHandles();
            }
        },

        initActiveLinePicker() {
            const sel = document.getElementById("edActiveLineSelect");
            if (!sel) return;
            sel.innerHTML = NetworkStore.lines.map(l =>
                `<option value="${escapeHtml(l.code)}" ${this.getActiveLineCode() === l.code ? "selected" : ""}>Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`
            ).join("");
            const activeCode = this.getActiveLineCode();
            sel.value = activeCode;
            const dot = document.getElementById("activeLineBadgeDot");
            const curLn = NetworkStore.linesByCode.get(activeCode);
            if (dot && curLn) dot.style.background = curLn.color || "#0055A4";

            if (!sel._hasLinePickerSync) {
                sel._hasLinePickerSync = true;
                sel.addEventListener("change", (e) => {
                    this.setActiveLine(e.target.value);
                    showToast(`Línea activa para trazar: Línea ${e.target.value}`);
                });
            }
        },

        setTool(tool) {
            if (this.activeTool === tool) {
                this.cancel();
                return;
            }
            this.activeTool = tool;
            this.segmentSourceStationId = null;
            this.correspondenceSourceStationId = null;

            document.body.classList.remove("tool-active-add_station", "tool-active-connect_segment", "tool-active-add_correspondence");
            document.querySelectorAll(".ed-tool-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".svg-station-node.connect-source, .svg-station-node.corr-source-pulse, .svg-station-node.connect-target-hover").forEach(el => {
                el.classList.remove("connect-source", "corr-source-pulse", "connect-target-hover");
            });

            const statusBox = document.getElementById("edToolActiveStatus");
            const statusText = document.getElementById("edToolActiveText");

            if (tool === "add_station") {
                document.body.classList.add("tool-active-add_station");
                document.getElementById("btnToolAddStation")?.classList.add("active");
                if (statusBox && statusText) {
                    statusText.textContent = "Haz clic en cualquier punto del mapa para colocar la nueva estación";
                    statusBox.classList.remove("hidden");
                }
            } else if (tool === "connect_segment") {
                document.body.classList.add("tool-active-connect_segment");
                document.getElementById("btnToolAddSegment")?.classList.add("active");
                const lineCode = this.getActiveLineCode();
                const ln = NetworkStore.linesByCode.get(lineCode);
                const lineName = ln ? `Línea ${ln.code}` : "Línea activa";
                if (statusBox && statusText) {
                    statusText.textContent = `Modo Trazado (${lineName}): Clic en una estación o lienzo para iniciar el trazo.`;
                    statusBox.classList.remove("hidden");
                }
                showToast(`Modo Trazado activo para ${lineName}. Haz clic en estaciones o el mapa para unir.`);
            } else if (tool === "add_correspondence") {
                document.body.classList.add("tool-active-add_correspondence");
                document.getElementById("btnToolAddCorrespondence")?.classList.add("active");
                if (statusBox && statusText) {
                    statusText.textContent = "Haz clic en la 1ra estación para conectar correspondencia directamente en el plano";
                    statusBox.classList.remove("hidden");
                }
            }
        },

        cancel() {
            this.activeTool = null;
            this.segmentSourceStationId = null;
            this.correspondenceSourceStationId = null;
            document.body.classList.remove("tool-active-add_station", "tool-active-connect_segment", "tool-active-add_correspondence");
            document.querySelectorAll(".ed-tool-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".svg-station-node.connect-source, .svg-station-node.corr-source-pulse, .svg-station-node.connect-target-hover").forEach(el => {
                el.classList.remove("connect-source", "corr-source-pulse", "connect-target-hover");
            });
            document.getElementById("edToolActiveStatus")?.classList.add("hidden");
            SchematicMapEngine.renderRubberBand(null);
        },

        openNewStationModal(x = null, y = null, initialLine = null) {
            const modal = document.getElementById("modalNewStation");
            if (!modal) return;
            const inputX = document.getElementById("newStationX");
            const inputY = document.getElementById("newStationY");
            const inputName = document.getElementById("newStationName");
            const selectLine = document.getElementById("newStationInitialLine");

            let posX = x;
            let posY = y;
            if (posX == null || posY == null || isNaN(posX) || isNaN(posY)) {
                if (SchematicMapEngine.viewBox) {
                    posX = Math.round((SchematicMapEngine.viewBox.x + SchematicMapEngine.viewBox.w / 2) * 2) / 2;
                    posY = Math.round((SchematicMapEngine.viewBox.y + SchematicMapEngine.viewBox.h / 2) * 2) / 2;
                } else {
                    posX = 2120.0;
                    posY = 1860.0;
                }
            }

            if (inputX) inputX.value = (Math.round(Number(posX) * 2) / 2).toFixed(1);
            if (inputY) inputY.value = (Math.round(Number(posY) * 2) / 2).toFixed(1);
            if (inputName) {
                inputName.value = `Estación ${NetworkStore.stations.length + 1}`;
                setTimeout(() => {
                    inputName.focus();
                    inputName.select();
                }, 50);
            }

            if (selectLine) {
                const curEditLine = document.getElementById("editLineSelect")?.value;
                const chosenLine = initialLine || NetworkStore.isolatedLineCode || curEditLine || "";
                selectLine.innerHTML = '<option value="">(Ninguna: estación independiente / huérfana)</option>' +
                    NetworkStore.lines.map(l =>
                        `<option value="${escapeHtml(l.code)}" ${chosenLine === l.code ? "selected" : ""}>Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`
                    ).join("");
                if (chosenLine) {
                    selectLine.value = chosenLine;
                }
            }

            modal.classList.remove("hidden");
        },

        openNewLineModal() {
            const modal = document.getElementById("modalNewLine");
            if (!modal) return;
            const inputCode = document.getElementById("newLineCode");
            const inputName = document.getElementById("newLineName");
            if (inputCode) inputCode.value = "";
            if (inputName) inputName.value = "";
            modal.classList.remove("hidden");
            setTimeout(() => inputCode?.focus(), 50);
        },

        openNewSegmentModal(fromId = null, toId = null) {
            const modal = document.getElementById("modalNewSegment");
            if (!modal) return;
            const selLine = document.getElementById("newSegmentLineSelect");
            const selFrom = document.getElementById("newSegmentFromSelect");
            const selTo = document.getElementById("newSegmentToSelect");

            // Si fromId viene de una estación con línea, sincronizar línea por defecto
            let defaultLineCode = NetworkStore.isolatedLineCode || document.getElementById("editLineSelect")?.value;
            if (fromId) {
                const stFrom = NetworkStore.stationsById.get(Number(fromId));
                if (stFrom && Array.isArray(stFrom.lines) && stFrom.lines.length > 0) {
                    defaultLineCode = stFrom.lines[0];
                }
            }

            if (selLine) {
                selLine.innerHTML = NetworkStore.lines.map(l =>
                    `<option value="${escapeHtml(l.code)}" ${defaultLineCode === l.code ? "selected" : ""}>Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`
                ).join("");
            }

            const updateStationSelects = () => {
                const activeLineCode = selLine ? selLine.value : defaultLineCode;
                const sortedStations = NetworkStore.getSortedStations();

                const buildOptions = (currentVal) => {
                    return sortedStations.map(s => {
                        const hasLine = Array.isArray(s.lines) && s.lines.length > 0;
                        const belongsToLine = !activeLineCode || (hasLine && s.lines.includes(activeLineCode));
                        const isIndependent = !hasLine;
                        const isForbidden = !belongsToLine && !isIndependent;
                        const lineLabel = hasLine ? `(Líneas: ${s.lines.join("/")})` : "(Independiente)";
                        const disAttr = isForbidden ? "disabled" : "";
                        const note = isForbidden ? " [Otra línea]" : "";
                        const selAttr = String(s.id) === String(currentVal) ? "selected" : "";
                        return `<option value="${s.id}" ${disAttr} ${selAttr}>${escapeHtml(s.name)} ${escapeHtml(lineLabel)}${note}</option>`;
                    }).join("");
                };

                if (selFrom && selTo) {
                    const curFrom = selFrom.value || String(fromId || "");
                    const curTo = selTo.value || String(toId || "");
                    selFrom.innerHTML = buildOptions(curFrom);
                    selTo.innerHTML = buildOptions(curTo);
                }
            };

            updateStationSelects();

            if (selLine && !selLine.dataset.hasSegmentSync) {
                selLine.dataset.hasSegmentSync = "1";
                selLine.addEventListener("change", () => updateStationSelects());
            }

            if (fromId && selFrom) selFrom.value = String(fromId);
            if (toId && selTo) selTo.value = String(toId);
            else if (fromId && selTo) {
                const sortedStations = NetworkStore.getSortedStations();
                const activeLineCode = selLine ? selLine.value : defaultLineCode;
                const candidate = sortedStations.find(s =>
                    s.id !== Number(fromId) &&
                    (!activeLineCode || !s.lines || s.lines.length === 0 || s.lines.includes(activeLineCode))
                );
                if (candidate) selTo.value = String(candidate.id);
            }

            modal.classList.remove("hidden");
        },

        openCorrespondenceModal(stationId = null) {
            const modal = document.getElementById("modalNewCorrespondence");
            if (!modal) return;
            const inputStation = document.getElementById("modalCorrStationSelect");
            const linesText = document.getElementById("modalCorrStationLinesText");
            const capacityBadge = document.getElementById("modalCorrCapacityBadge");
            const checklist = document.getElementById("modalCorrLinesChecklist");
            const selLine = document.getElementById("modalCorrLineSelect");
            const submitBtn = document.getElementById("btnSubmitModalCorr");

            const sorted = NetworkStore.getSortedStations();
            if (inputStation) {
                inputStation.innerHTML = sorted.map(s =>
                    `<option value="${s.id}">${escapeHtml(s.name)}</option>`
                ).join("");
                const chosenId = stationId || NetworkStore.selectedStationId || (sorted[0] ? sorted[0].id : null);
                if (chosenId) {
                    inputStation.value = String(chosenId);
                }
            }

            const updateModalLines = () => {
                const curId = inputStation ? Number(inputStation.value) : Number(stationId);
                const curSt = NetworkStore.stationsById.get(curId);
                const served = curSt && Array.isArray(curSt.lines) ? new Set(curSt.lines) : new Set();
                const currentCount = served.size;
                const remainingQuota = Math.max(0, 10 - currentCount);

                if (linesText && curSt) {
                    linesText.textContent = `Líneas actuales: ${curSt.lines.join(", ") || "Ninguna"}`;
                }
                if (capacityBadge) {
                    capacityBadge.textContent = `${currentCount}/10 líneas`;
                    capacityBadge.style.background = currentCount >= 10 ? "#fee2e2" : "#e2e8f0";
                    capacityBadge.style.color = currentCount >= 10 ? "#b91c1c" : "#334155";
                }
                if (submitBtn) {
                    submitBtn.disabled = remainingQuota <= 0;
                }

                const available = NetworkStore.lines.filter(l => !served.has(l.code));
                renderCorrespondenceLinesChecklist(checklist, selLine, available, remainingQuota);
            };

            updateModalLines();
            if (inputStation && !inputStation.dataset.boundChange) {
                inputStation.dataset.boundChange = "true";
                inputStation.addEventListener("change", updateModalLines);
            }

            const btnAll = document.getElementById("btnSelectAllModalLines");
            if (btnAll && !btnAll.dataset.bound) {
                btnAll.dataset.bound = "true";
                btnAll.addEventListener("click", () => {
                    const curId = inputStation ? Number(inputStation.value) : Number(stationId);
                    const curSt = NetworkStore.stationsById.get(curId);
                    const count = curSt && Array.isArray(curSt.lines) ? curSt.lines.length : 0;
                    const quota = Math.max(0, 10 - count);
                    const cbs = checklist ? Array.from(checklist.querySelectorAll(".js-corr-line-checkbox")) : [];
                    let checkedSoFar = 0;
                    cbs.forEach(cb => {
                        if (checkedSoFar < quota) {
                            cb.checked = true;
                            checkedSoFar++;
                        } else {
                            cb.checked = false;
                        }
                    });
                    if (selLine) {
                        const checked = cbs.filter(c => c.checked);
                        if (checked.length === 1) {
                            selLine.value = checked[0].value;
                        } else {
                            selLine.value = "";
                        }
                    }
                });
            }

            const btnClear = document.getElementById("btnClearModalLines");
            if (btnClear && !btnClear.dataset.bound) {
                btnClear.dataset.bound = "true";
                btnClear.addEventListener("click", () => {
                    const cbs = checklist ? checklist.querySelectorAll(".js-corr-line-checkbox") : [];
                    cbs.forEach(cb => { cb.checked = false; });
                    if (selLine) {
                        selLine.value = "";
                    }
                });
            }

            modal.classList.remove("hidden");
        },

        handleStationClickForSegment(stId) {
            const st = NetworkStore.stationsById.get(stId);
            if (!st) return;

            if (this.segmentSourceStationId === null) {
                this.segmentSourceStationId = stId;
                document.querySelectorAll(".svg-station-node.connect-source").forEach(el => el.classList.remove("connect-source"));
                const nodeEl = document.querySelector(`.svg-station-node[data-station-id="${stId}"]`);
                if (nodeEl) nodeEl.classList.add("connect-source");
                const lineCode = this.getActiveLineCode();
                const statusText = document.getElementById("edToolActiveText");
                if (statusText) {
                    statusText.textContent = `Origen: ${st.name} (Línea ${lineCode}). Clic en la siguiente estación o lienzo para unir. (Esc: terminar)`;
                }
                showToast(`Origen fijado en ${st.name}. Clic en el siguiente punto para unir en Línea ${lineCode}.`);
            } else {
                const fromId = this.segmentSourceStationId;
                const toId = stId;
                if (fromId === toId) {
                    showToast("Haz clic en otra estación o en el mapa para trazar.");
                    return;
                }
                this.connectStationsDirectly(fromId, toId);
            }
        },

        async connectStationsDirectly(fromId, toId) {
            const lineCode = this.getActiveLineCode();
            const st1 = NetworkStore.stationsById.get(fromId);
            const st2 = NetworkStore.stationsById.get(toId);
            if (!st1 || !st2) return;

            try {
                const res = await ApiClient.post("/api/line-segments/create/", {
                    line_code: lineCode,
                    from_station_id: fromId,
                    to_station_id: toId,
                    auto_correspondence: true
                });

                if (!res.ok) {
                    showToast(res.error || "No se pudo conectar el tramo");
                    return;
                }

                if (!st1.lines.includes(lineCode)) st1.lines.push(lineCode);
                if (!st2.lines.includes(lineCode)) st2.lines.push(lineCode);
                st1.is_transfer = st1.lines.length > 1;
                st2.is_transfer = st2.lines.length > 1;

                await refreshNetworkDataAndRender();

                HistoryManager.push({
                    type: "segment_create",
                    lineCode,
                    fromId,
                    toId,
                    description: `Unir ${st1.name} ↔ ${st2.name} en Línea ${lineCode}`
                });

                showToast(`✓ Conectado: ${st1.name} ↔ ${st2.name} en Línea ${lineCode}`);

                // Continuidad fluida estilo MetroMapMaker: toId se convierte en el nuevo origen para encadenar trazos
                this.segmentSourceStationId = toId;
                document.querySelectorAll(".svg-station-node.connect-source").forEach(el => el.classList.remove("connect-source"));
                const nextNodeEl = document.querySelector(`.svg-station-node[data-station-id="${toId}"]`);
                if (nextNodeEl) nextNodeEl.classList.add("connect-source");

                const statusText = document.getElementById("edToolActiveText");
                if (statusText) {
                    statusText.textContent = `Extremo actual: ${st2.name} (Línea ${lineCode}). Continúa haciendo clic para extender el trazo.`;
                }
                SchematicMapEngine.renderRubberBand(null);
            } catch (err) {
                console.error("Error al conectar tramo directo:", err);
                showToast("Error al conectar estaciones");
            }
        },

        async createAndConnectNewStation(x, y) {
            const lineCode = this.getActiveLineCode();
            try {
                const newName = `Estación ${NetworkStore.stations.length + 1}`;
                const res = await ApiClient.post("/api/stations/create/", {
                    name: newName,
                    x: Math.round(x * 2) / 2,
                    y: Math.round(y * 2) / 2,
                    initial_line: lineCode,
                    infrastructure_type: "subterraneo",
                    operational_status: "operational",
                    platforms_count: 2
                });

                if (!res.ok) {
                    showToast(res.error || "Error creando estación");
                    return;
                }

                const newStId = res.created_id || (res.station ? res.station.id : null);
                await refreshNetworkDataAndRender();

                if (this.segmentSourceStationId !== null && newStId) {
                    await this.connectStationsDirectly(this.segmentSourceStationId, newStId);
                } else if (newStId) {
                    this.segmentSourceStationId = newStId;
                    const nodeEl = document.querySelector(`.svg-station-node[data-station-id="${newStId}"]`);
                    if (nodeEl) nodeEl.classList.add("connect-source");
                    showToast(`Estación ${newName} creada. Haz clic en el siguiente punto para unir.`);
                }
            } catch (err) {
                console.error("Error creando estación al trazar:", err);
                showToast("Error al trazar nuevo punto");
            }
        },

        handleStationClickForCorrespondence(stId) {
            const st = NetworkStore.stationsById.get(stId);
            if (!st) return;

            if (this.correspondenceSourceStationId === null) {
                this.correspondenceSourceStationId = stId;
                const nodeEl = document.querySelector(`.svg-station-node[data-station-id="${stId}"]`);
                if (nodeEl) nodeEl.classList.add("corr-source-pulse");
                const statusText = document.getElementById("edToolActiveText");
                if (statusText) {
                    statusText.textContent = `Estación 1: ${st.name}. Ahora haz clic en la 2da estación para unirlas directamente como correspondencia.`;
                }
                showToast(`Paso 1: ${st.name} seleccionada. Haz clic en la 2da estación.`);
                ControlCenterUI.selectStation(stId);
            } else {
                const st1Id = this.correspondenceSourceStationId;
                const st2Id = stId;
                if (st1Id === st2Id) {
                    showToast("Selecciona una estación destino diferente");
                    return;
                }
                const st1 = NetworkStore.stationsById.get(st1Id);
                const st2 = NetworkStore.stationsById.get(st2Id);
                this.cancel();
                this.establishManualCorrespondence(st1Id, st2Id, st1 ? st1.name : "", st2 ? st2.name : "");
            }
        },

        async establishManualCorrespondence(st1Id, st2Id, st1Name = "", st2Name = "") {
            try {
                const res = await ApiClient.post("/api/correspondences/", { station_id: st1Id, station_id_2: st2Id });
                if (!res.ok) {
                    showToast(res.error || "No se pudo conectar correspondencia");
                    return;
                }
                await refreshNetworkDataAndRender(true);
                HistoryManager.push({
                    type: "correspondence",
                    stationId: st1Id,
                    stationId2: st2Id,
                    description: `Transbordo manual entre ${st1Name} y ${st2Name}`
                });
                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ Transbordo conectado entre ${st1Name} y ${st2Name}${msgMode}`);
            } catch (err) {
                console.error("Error al establecer correspondencia manual:", err);
                showToast("Error al conectar correspondencia");
            }
        }
    };

    // =========================================================================
    // Menú Contextual Rápido (Click Derecho) en el Plano Esquemático
    // =========================================================================
    const ContextMenuManager = {
        el: null,

        init() {
            this.el = document.getElementById("metroContextMenu");
            const viewport = document.getElementById("schematicViewport");
            if (!viewport || !this.el) return;

            viewport.addEventListener("contextmenu", (e) => this.handleContextMenu(e));

            // Cerrar menú al hacer clic fuera o presionar Escape
            window.addEventListener("click", (e) => {
                if (this.el && !this.el.contains(e.target)) {
                    this.hide();
                }
            });
            window.addEventListener("contextmenu", (e) => {
                if (this.el && !this.el.contains(e.target) && !viewport.contains(e.target)) {
                    this.hide();
                }
            });
            window.addEventListener("keydown", (e) => {
                if (e.key === "Escape") this.hide();
            });
        },

        hide() {
            if (this.el) {
                this.el.classList.add("hidden");
                this.el.innerHTML = "";
            }
        },

        show(x, y, itemsHtml) {
            if (!this.el) return;
            this.el.innerHTML = itemsHtml;
            this.el.classList.remove("hidden");

            const menuWidth = 245;
            const menuHeight = this.el.offsetHeight || 220;
            const maxX = window.innerWidth - menuWidth - 12;
            const maxY = window.innerHeight - menuHeight - 12;
            const left = Math.min(x, maxX);
            const top = Math.min(y, maxY);

            this.el.style.left = `${Math.max(10, left)}px`;
            this.el.style.top = `${Math.max(10, top)}px`;
        },

        handleContextMenu(e) {
            if (e.target.closest(".svg-waypoint-handle")) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            // 1. Detectar si el clic derecho fue sobre una estación
            const stationNode = e.target.closest(".svg-station-node, .svg-station-label, .svg-terminal-badge");
            const stationId = stationNode ? Number(stationNode.dataset.stationId) : null;
            const st = stationId ? NetworkStore.stationsById.get(stationId) : null;

            if (st) {
                this.renderStationMenu(e.clientX, e.clientY, st);
                return;
            }

            // 2. Detectar si el clic derecho fue sobre un tramo de línea
            const trackHit = e.target.closest(".svg-track-hit");
            if (trackHit) {
                const lineCode = trackHit.dataset.lineCode;
                const s1Id = Number(trackHit.dataset.s1Id);
                const s2Id = Number(trackHit.dataset.s2Id);
                const svgPt = SchematicMapEngine.clientToSvgCoords(e.clientX, e.clientY);
                this.renderTrackMenu(e.clientX, e.clientY, lineCode, s1Id, s2Id, svgPt.x, svgPt.y);
                return;
            }

            // 3. Clic derecho en el lienzo vacío del plano
            const svgPt = SchematicMapEngine.clientToSvgCoords(e.clientX, e.clientY);
            this.renderCanvasMenu(e.clientX, e.clientY, svgPt.x, svgPt.y);
        },

        renderStationMenu(clientX, clientY, st) {
            const lines = Array.isArray(st.lines) ? st.lines : [];
            let linesHtml = "";
            if (lines.length > 0) {
                linesHtml = `
                    <div class="ctx-divider"></div>
                    <div style="padding:4px 12px 2px; font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase;">Quitar de Línea:</div>
                ` + lines.map(c => {
                    const ln = NetworkStore.linesByCode.get(c);
                    const bg = ln ? ln.color : "#475569";
                    return `
                        <button type="button" class="ctx-item js-ctx-remove-line" data-station-id="${st.id}" data-line-code="${escapeHtml(c)}">
                            <span class="ctx-line-badge" style="background:${bg};">${escapeHtml(c)}</span>
                            <span>✕ Quitar de Línea ${escapeHtml(c)}</span>
                        </button>
                    `;
                }).join("");
            } else {
                linesHtml = `
                    <div class="ctx-divider"></div>
                    <div style="padding:4px 12px; font-size:11px; color:#64748b; font-style:italic;">Estación independiente (huérfana)</div>
                `;
            }

            const html = `
                <div class="context-menu-header">Estación: ${escapeHtml(st.name)}</div>
                <button type="button" class="ctx-item js-ctx-create-station-near" data-station-id="${st.id}">
                    <span>＋</span> <span>Crear Estación (Create Station)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-connect-segment" data-station-id="${st.id}">
                    <span>⚡</span> <span>Conectar Trazo a otra Estación</span>
                </button>
                <button type="button" class="ctx-item js-ctx-add-corr" data-station-id="${st.id}">
                    <span>⇄</span> <span>Añadir a Línea (Transbordo)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-edit-inspector" data-station-id="${st.id}">
                    <span>✎</span> <span>Editar Estación en Inspector</span>
                </button>
                ${linesHtml}
                <div class="ctx-divider"></div>
                <button type="button" class="ctx-item danger js-ctx-delete-station" data-station-id="${st.id}">
                    <span>🗑</span> <span>Eliminar Estación</span>
                </button>
            `;

            this.show(clientX, clientY, html);
            this.bindStationMenuEvents(st);
        },

        bindStationMenuEvents(st) {
            this.el.querySelector(".js-ctx-create-station-near")?.addEventListener("click", () => {
                this.hide();
                const defaultLine = Array.isArray(st.lines) && st.lines.length > 0 ? st.lines[0] : null;
                VisualEditorTools.openNewStationModal(st.x + 40, st.y + 40, defaultLine);
            });

            this.el.querySelector(".js-ctx-connect-segment")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewSegmentModal(st.id);
            });

            this.el.querySelector(".js-ctx-add-corr")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openCorrespondenceModal(st.id);
            });

            this.el.querySelector(".js-ctx-edit-inspector")?.addEventListener("click", () => {
                this.hide();
                ControlCenterUI.selectStation(st.id);
                ControlCenterUI.switchRightTab("editor");
                document.querySelector('.ed-subtab[data-edtab="station"]')?.click();
                ControlCenterUI.loadStationIntoEditor(st.id);
            });

            this.el.querySelectorAll(".js-ctx-remove-line").forEach(btn => {
                btn.addEventListener("click", async () => {
                    this.hide();
                    const lineCode = btn.dataset.lineCode;
                    await ControlCenterUI.disconnectStationFromLine(st.id, lineCode);
                });
            });

            this.el.querySelector(".js-ctx-delete-station")?.addEventListener("click", async () => {
                this.hide();
                await ControlCenterUI.deleteStation(st.id, st.name);
            });
        },

        renderTrackMenu(clientX, clientY, lineCode, s1Id, s2Id, svgX = null, svgY = null) {
            const st1 = NetworkStore.stationsById.get(s1Id);
            const st2 = NetworkStore.stationsById.get(s2Id);
            const s1Name = st1 ? st1.name : "Estación 1";
            const s2Name = st2 ? st2.name : "Estación 2";
            const posX = svgX != null ? Math.round(Number(svgX) * 2) / 2 : 2120;
            const posY = svgY != null ? Math.round(Number(svgY) * 2) / 2 : 1860;

            const html = `
                <div class="context-menu-header">Tramo: Línea ${escapeHtml(lineCode)}</div>
                <div style="padding:3px 12px 6px; font-size:11px; color:#475569;">${escapeHtml(s1Name)} ↔ ${escapeHtml(s2Name)}</div>
                <div class="ctx-divider"></div>
                <button type="button" class="ctx-item js-ctx-create-station-track" data-line-code="${escapeHtml(lineCode)}">
                    <span>＋</span> <span>Crear Estación en esta Línea (Create Station)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-new-segment-here" data-s1="${s1Id}">
                    <span>⚡</span> <span>Conectar Tramo desde ${escapeHtml(s1Name)}</span>
                </button>
                <button type="button" class="ctx-item js-ctx-straighten-line" data-line-code="${escapeHtml(lineCode)}">
                    <span>⎯</span> <span>Enderezar Trazos Línea (90° / 180°)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-isolate-line" data-line-code="${escapeHtml(lineCode)}">
                    <span>🔍</span> <span>Aislar esta Línea</span>
                </button>
            `;

            this.show(clientX, clientY, html);
            this.el.querySelector(".js-ctx-create-station-track")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewStationModal(posX, posY, lineCode);
            });
            this.el.querySelector(".js-ctx-straighten-line")?.addEventListener("click", async () => {
                this.hide();
                await ControlCenterUI.straightenLineTracks(lineCode);
            });
            this.el.querySelector(".js-ctx-isolate-line")?.addEventListener("click", () => {
                this.hide();
                NetworkStore.isolatedLineCode = (NetworkStore.isolatedLineCode === lineCode) ? null : lineCode;
                ControlCenterUI.renderLinesDirectory();
                SchematicMapEngine.renderTracksAndStations();
            });
            this.el.querySelector(".js-ctx-new-segment-here")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewSegmentModal(s1Id);
            });
        },

        renderCanvasMenu(clientX, clientY, svgX, svgY) {
            const posX = Math.round(Number(svgX) * 2) / 2;
            const posY = Math.round(Number(svgY) * 2) / 2;

            const html = `
                <div class="context-menu-header">Mapa (${posX.toFixed(1)}, ${posY.toFixed(1)})</div>
                <button type="button" class="ctx-item js-ctx-add-station">
                    <span>＋</span> <span>Crear Estación Aquí (Create Station)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-create-line">
                    <span>＋</span> <span>Crear Línea Nueva</span>
                </button>
                <button type="button" class="ctx-item js-ctx-connect-segment-empty">
                    <span>⚡</span> <span>Conectar Tramo entre Estaciones</span>
                </button>
                <button type="button" class="ctx-item js-ctx-corr-empty">
                    <span>⇄</span> <span>Crear Correspondencia Manual</span>
                </button>
                <div class="ctx-divider"></div>
                <button type="button" class="ctx-item js-ctx-straighten">
                    <span>⎯</span> <span>Enderezar Trazos (90° / 180°)</span>
                </button>
                <button type="button" class="ctx-item js-ctx-center-view">
                    <span>↺</span> <span>Centrar Vista</span>
                </button>
            `;

            this.show(clientX, clientY, html);
            this.bindCanvasMenuEvents(posX, posY);
        },

        bindCanvasMenuEvents(posX, posY) {
            this.el.querySelector(".js-ctx-add-station")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewStationModal(posX, posY);
            });

            this.el.querySelector(".js-ctx-create-line")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewLineModal();
            });

            this.el.querySelector(".js-ctx-connect-segment-empty")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openNewSegmentModal();
            });

            this.el.querySelector(".js-ctx-corr-empty")?.addEventListener("click", () => {
                this.hide();
                VisualEditorTools.openCorrespondenceModal();
            });

            this.el.querySelector(".js-ctx-straighten")?.addEventListener("click", async () => {
                this.hide();
                const curLine = NetworkStore.isolatedLineCode || document.getElementById("editLineSelect")?.value;
                if (!curLine) {
                    showToast("Selecciona o aísla una línea para enderezar sus trazos a 90° o 180°");
                    return;
                }
                await ControlCenterUI.straightenLineTracks(curLine);
            });

            this.el.querySelector(".js-ctx-center-view")?.addEventListener("click", () => {
                this.hide();
                SchematicMapEngine.resetView();
            });
        }
    };

    // Colores técnicos para el modo "Ingeniería de Tramo"
    const INFRA_COLORS = {
        subterraneo: "#3b82f6",
        tunel_profundo: "#8b5cf6",
        superficial: "#22c55e",
        elevado: "#f59e0b"
    };

    const INFRA_NAMES = {
        subterraneo: "Subterráneo (Cajón Cortar y Cubrir)",
        tunel_profundo: "Túnel Profundo (Escudo TBM + Lumbreras)",
        superficial: "Superficial (Derecho de Vía Confinado)",
        elevado: "Viaducto Elevado (Estructura Prefabricada)"
    };

    const STATUS_NAMES = {
        operational: "En Operación Comercial",
        construction: "En Construcción",
        closed_permanent: "Cerrada Permanentemente (Conflicto Territorial)",
        expansion_planned: "Ampliación Pendiente / Futura Correspondencia"
    };

    // Catálogo oficial de los 6 Tags con Iconos de Equipamiento Urbano a un costado de la estación
    const STATION_ICON_TAGS = [
        {
            id: "aeropuerto",
            label: "Aeropuerto",
            bg: "#0284C7",
            svgPath: '<path d="M8 2.1l1.1 3.7 4.4 2v1.5l-4.4-.9v3.2l1.6 1.1v1.2L8 13.1l-2.7.8v-1.2l1.6-1.1V8.4l-4.4.9V7.8l4.4-2L8 2.1z" fill="#FFFFFF"/>'
        },
        {
            id: "parque",
            label: "Parque",
            bg: "#15803D",
            svgPath: '<path d="M8 2.2c2.1 0 3.7 1.6 3.7 3.5 0 .6-.2 1.2-.5 1.7.8.5 1.3 1.3 1.3 2.3 0 1.5-1.3 2.7-3 2.7h-.7v2.2H7.2v-2.2h-.7c-1.7 0-3-1.2-3-2.7 0-1 .5-1.8 1.3-2.3-.3-.5-.5-1.1-.5-1.7 0-1.9 1.6-3.5 3.7-3.5z" fill="#FFFFFF"/>'
        },
        {
            id: "terminal",
            label: "Terminal",
            bg: "#1E293B",
            svgPath: '<path d="M4.2 2.5h7.6c1 0 1.7.8 1.7 1.8v6.5c0 .9-.7 1.6-1.5 1.7l1.3 1.8h-1.7l-1.2-1.7H5.6l-1.2 1.7H2.7L4 12.5c-.8-.1-1.5-.8-1.5-1.7V4.3c0-1 .7-1.8 1.7-1.8zm.4 2.1v3.2h6.8V4.6H4.6zm1 6.2a.9.9 0 1 0 0-1.8.9.9 0 0 0 0 1.8zm4.8 0a.9.9 0 1 0 0-1.8.9.9 0 0 0 0 1.8z" fill="#FFFFFF"/>'
        },
        {
            id: "centro_modal",
            label: "Centro Modal",
            bg: "#6D28D9",
            svgPath: '<path d="M8 2.2l2.6 2.5H8.8v2.5h2.5V5.4L13.8 8l-2.5 2.6V8.8H8.8v2.5h1.8L8 13.8l-2.6-2.5h1.8V8.8H4.7v1.8L2.2 8l2.5-2.6v1.8h2.5V4.7H5.4L8 2.2z" fill="#FFFFFF"/>'
        },
        {
            id: "zona_cultural",
            label: "Zona Cultural",
            bg: "#B45309",
            svgPath: '<path d="M8 2.2l5.6 2.8v1.2H2.4V5L8 2.2zm-4.2 5h1.5v4.4H3.8V7.2zm3.4 0h1.6v4.4H7.2V7.2zm3.5 0h1.5v4.4h-1.5V7.2zM2.4 12.4h11.2v1.4H2.4v-1.4z" fill="#FFFFFF"/>'
        },
        {
            id: "escuela",
            label: "Escuela",
            bg: "#BE123C",
            svgPath: '<path d="M8 2.6l6 2.9-6 2.9-4.7-2.3v3.5H2.1V5.5L8 2.6zm-3.3 5.1L8 9.3l3.3-1.6v2.7c0 1.3-1.5 2.4-3.3 2.4s-3.3-1.1-3.3-2.4V7.7z" fill="#FFFFFF"/>'
        }
    ];

    const STATION_ICON_TAGS_MAP = new Map(STATION_ICON_TAGS.map(t => [t.id, t]));

    function renderInlineTagShieldSvg(tagDef, px = 16) {
        return `<svg width="${px}" height="${px}" viewBox="0 0 16 16" aria-hidden="true" style="display:block;flex-shrink:0;"><rect x="0" y="0" width="16" height="16" rx="3.6" fill="${tagDef.bg}"/>${tagDef.svgPath}</svg>`;
    }

    function getBadgeTextColor(hexColor, fallback = "#FFFFFF") {
        if (!hexColor || typeof hexColor !== "string" || !hexColor.startsWith("#") || hexColor.length < 7) {
            return fallback;
        }
        const r = parseInt(hexColor.slice(1, 3), 16) / 255;
        const g = parseInt(hexColor.slice(3, 5), 16) / 255;
        const b = parseInt(hexColor.slice(5, 7), 16) / 255;
        const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        return lum > 0.66 ? "#182026" : "#FFFFFF";
    }

    // =========================================================================
    // 2. MOTOR DE SIMULACIÓN DE TRENES Y AUTOBUSES EN TIEMPO REAL (60 FPS)
    // =========================================================================
    const TrainSimulationEngine = {
        trains: [],
        trainsById: new Map(),
        svgTrainElements: new Map(),
        geoTrainMarkers: new Map(),
        lastFrameTime: performance.now(),
        eventCounter: 0,

        buildFleet() {
            this.trains = [];
            this.trainsById.clear();

            for (const line of NetworkStore.lines) {
                if (line.status === "suspended") continue;

                // Agrupar paradas por rama (branch) y filtrar únicamente las operativas
                // (o permitir unidades de prueba en S5 si está en pruebas)
                const branches = new Map();
                for (const stop of line.stops) {
                    const bKey = stop.branch || "main";
                    if (!branches.has(bKey)) branches.set(bKey, []);
                    branches.get(bKey).push(stop);
                }

                for (const [branchName, rawStops] of branches.entries()) {
                    // Filtrar paradas activas para circulación comercial
                    let activeStops = rawStops.filter(s => s.segment_status === "operational");
                    // En Sistema 5 (en pruebas estáticas/dinámicas) permitimos 2 unidades de prueba a baja velocidad
                    const isTestCorridor = (line.code === "S5" && activeStops.length === 0);
                    if (isTestCorridor) {
                        activeStops = rawStops;
                    }

                    if (activeStops.length < 2) continue;

                    // Número de convoyes simultáneos proporcional a la longitud y frecuencia (150s, 180s, 300s)
                    const freq = Math.max(60, line.frequency_seconds || 180);
                    let numUnits = Math.max(2, Math.min(18, Math.round((activeStops.length * 42) / freq)));
                    if (line.code === "A") numUnits = 16; // Flota densa para el circuito de 124 estaciones
                    if (isTestCorridor) numUnits = 2;

                    for (let i = 0; i < numUnits; i++) {
                        const dir = (i % 2 === 0) ? 1 : -1;
                        const startIdx = Math.floor((i / numUnits) * (activeStops.length - 1));
                        const startProgress = ((i * 0.37) % 0.85);
                        const unitPrefix = line.network_type === "bus_articulado" ? "BRT" : "M";
                        const trainId = `${unitPrefix}-${line.code}-${branchName === "main" ? "" : branchName + "-"}${101 + i}`;

                        const trainObj = {
                            id: trainId,
                            lineCode: line.code,
                            lineName: line.name,
                            networkType: line.network_type,
                            branch: branchName,
                            serviceType: isTestCorridor ? "Prueba en Obra" : "Ordinario",
                            isPremium: false,
                            color: line.color,
                            textColor: line.text_color,
                            routeStops: activeStops,
                            currentStopIndex: startIdx,
                            segmentProgress: startProgress,
                            direction: dir, // +1 hacia final de lista, -1 hacia inicio
                            isCircular: Boolean(line.is_circular && branchName === "main"),
                            dwellRemainingSec: 0,
                            status: "En tránsito",
                            occupancyPct: Math.min(98, Math.max(18, line.current_occupancy_pct + ((i * 11) % 24) - 12)),
                            x: activeStops[startIdx].x,
                            y: activeStops[startIdx].y,
                            lat: activeStops[startIdx].lat,
                            lng: activeStops[startIdx].lng,
                            angleDeg: 0,
                            currentSpeedKmh: line.max_speed_kmh
                        };
                        this.updateTrainPositionGeometry(trainObj);
                        this.trains.push(trainObj);
                        this.trainsById.set(trainObj.id, trainObj);
                    }

                    // Para la Línea A (Circuito Periférico 132,8 km):
                    // Agregar la flota del Servicio Expreso Premium (frecuencia 300 s, 100 km/h, 20 estaciones clave)
                    if (line.code === "A" && branchName === "main") {
                        const premiumStops = activeStops.filter(s => s.is_premium_stop);
                        if (premiumStops.length >= 10) {
                            const numPremium = 8;
                            for (let p = 0; p < numPremium; p++) {
                                const dir = (p % 2 === 0) ? 1 : -1;
                                const startIdx = Math.floor((p / numPremium) * premiumStops.length) % premiumStops.length;
                                const trainId = `EXP-A-${201 + p}`;
                                const premTrain = {
                                    id: trainId,
                                    lineCode: "A",
                                    lineName: "Línea A (Servicio Premium)",
                                    networkType: "metro",
                                    branch: "premium_loop",
                                    serviceType: "Premium (20 paradas · 300s)",
                                    isPremium: true,
                                    color: line.color,
                                    textColor: "#ffffff",
                                    routeStops: activeStops, // Recorre el trazado completo pero solo se detiene en is_premium_stop
                                    currentStopIndex: Math.floor((p / numPremium) * (activeStops.length - 1)),
                                    segmentProgress: (p * 0.29) % 0.9,
                                    direction: dir,
                                    isCircular: true,
                                    dwellRemainingSec: 0,
                                    status: "Servicio Expreso Premium",
                                    occupancyPct: 54 + (p * 5) % 25,
                                    x: activeStops[0].x,
                                    y: activeStops[0].y,
                                    lat: activeStops[0].lat,
                                    lng: activeStops[0].lng,
                                    angleDeg: 0,
                                    currentSpeedKmh: line.premium_speed_kmh || 100.0
                                };
                                this.updateTrainPositionGeometry(premTrain);
                                this.trains.push(premTrain);
                                this.trainsById.set(premTrain.id, premTrain);
                            }
                        }
                    }
                }
            }

            const kpiEl = document.getElementById("kpiActiveTrains");
            if (kpiEl) kpiEl.textContent = String(this.trains.length);
        },

        getNextStopIndex(train) {
            const n = train.routeStops.length;
            if (train.isCircular) {
                return (train.currentStopIndex + train.direction + n) % n;
            }
            const next = train.currentStopIndex + train.direction;
            if (next >= n) return n - 2;
            if (next < 0) return 1;
            return next;
        },

        updateTrainPositionGeometry(train) {
            const stops = train.routeStops;
            if (!stops || stops.length < 2) return;
            const s1 = stops[train.currentStopIndex];
            const nextIdx = this.getNextStopIndex(train);
            const s2 = stops[nextIdx];

            // Obtener coordenadas actualizadas desde NetworkStore.stationsById por si el usuario arrastró la estación
            const st1 = NetworkStore.stationsById.get(s1.station_id) || s1;
            const st2 = NetworkStore.stationsById.get(s2.station_id) || s2;

            // Interpolar siguiendo los codos octilineales (0°/45°/90°) del tramo
            let pts;
            if (train.direction === 1) {
                const wps = Array.isArray(s1.waypoints) ? s1.waypoints : [];
                pts = [[st1.x, st1.y], ...wps, [st2.x, st2.y]];
            } else {
                const wps = Array.isArray(s2.waypoints) ? [...s2.waypoints].reverse() : [];
                pts = [[st1.x, st1.y], ...wps, [st2.x, st2.y]];
            }

            let totalLen = 0;
            const segLens = [];
            for (let k = 0; k < pts.length - 1; k++) {
                const d = Math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]);
                segLens.push(d);
                totalLen += d;
            }

            const t = Math.max(0, Math.min(1, train.segmentProgress));
            let targetDist = totalLen * t;
            let px = st1.x, py = st1.y, ang = 0;
            for (let k = 0; k < segLens.length; k++) {
                const len = segLens[k];
                if (targetDist <= len || k === segLens.length - 1) {
                    const localT = len > 0.001 ? Math.min(1, targetDist / len) : 0;
                    px = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * localT;
                    py = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * localT;
                    ang = Math.atan2(pts[k + 1][1] - pts[k][1], pts[k + 1][0] - pts[k][0]) * (180 / Math.PI);
                    break;
                }
                targetDist -= len;
            }

            train.x = px;
            train.y = py;
            train.lat = 19.420000 + ((1860.0 - py) / 54.0) / 111.195080;
            train.lng = -99.140000 + ((px - 2120.0) / 54.0) / 104.868820;
            train.angleDeg = ang;
        },

        step(now) {
            const rawDt = Math.min(0.1, (now - this.lastFrameTime) / 1000.0);
            this.lastFrameTime = now;

            const speedMult = NetworkStore.simSpeedMultiplier;
            if (speedMult > 0) {
                const simDt = rawDt * speedMult;
                NetworkStore.operationalTimeSec = (NetworkStore.operationalTimeSec + simDt) % 86400;
                updateClockUI();

                for (const train of this.trains) {
                    const line = NetworkStore.linesByCode.get(train.lineCode);
                    if (!line || line.status === "suspended") continue;

                    const baseSpeed = train.isPremium
                        ? (line.premium_speed_kmh || 100.0)
                        : (line.max_speed_kmh || 50.0);
                    const alertFactor = line.effective_speed_factor || 1.0;

                    if (train.dwellRemainingSec > 0) {
                        train.dwellRemainingSec -= simDt;
                        train.currentSpeedKmh = 0;
                        if (train.dwellRemainingSec <= 0) {
                            train.dwellRemainingSec = 0;
                            train.status = alertFactor < 0.85 ? "Marcha regulada PCCO" : (train.isPremium ? "Expreso en vía" : "En tránsito");
                        }
                        continue;
                    }

                    // Velocidad de avance en el segmento (normalizada para que sea fluida y verosímil)
                    const segmentRate = (baseSpeed / 1600.0) * alertFactor;
                    train.currentSpeedKmh = Math.round(baseSpeed * alertFactor);
                    train.segmentProgress += segmentRate * simDt;

                    if (train.segmentProgress >= 1.0) {
                        train.segmentProgress = 0.0;
                        const n = train.routeStops.length;

                        if (train.isCircular) {
                            train.currentStopIndex = (train.currentStopIndex + train.direction + n) % n;
                        } else {
                            train.currentStopIndex += train.direction;
                            // Si llega a una estación terminal, invierte el sentido de marcha y regresa
                            if (train.currentStopIndex >= n - 1) {
                                train.currentStopIndex = n - 1;
                                train.direction = -1;
                                this.emitLiveEvent(train, "Inversión de marcha en terminal");
                            } else if (train.currentStopIndex <= 0) {
                                train.currentStopIndex = 0;
                                train.direction = 1;
                                this.emitLiveEvent(train, "Salida despachada desde terminal");
                            }
                        }

                        const arrivedStop = train.routeStops[train.currentStopIndex];
                        // Los trenes Expresos Premium de Línea A solo hacen parada en las 20 estaciones clave
                        if (train.isPremium && !arrivedStop.is_premium_stop) {
                            train.dwellRemainingSec = 0;
                            train.status = "Paso directo sin parada (Premium)";
                        } else {
                            train.dwellRemainingSec = train.isPremium ? 4.5 : 3.2;
                            train.status = "Ascenso/descenso en andén (PSD abiertas)";
                        }
                    }

                    this.updateTrainPositionGeometry(train);
                }
            }

            // Actualizar posiciones DOM/SVG y marcadores Leaflet sin recrear nodos
            SchematicMapEngine.syncTrainsDOM();
            if (NetworkStore.viewMode === "geo") {
                GeoMapEngine.syncTrainsGeo();
            }

            // Actualizar panel inspector si hay un tren o estación seleccionados
            if (NetworkStore.selectedTrainId && Math.floor(now / 350) !== Math.floor((now - 16) / 350)) {
                ControlCenterUI.renderTrainInspector(NetworkStore.selectedTrainId);
            }
            if (NetworkStore.selectedStationId && Math.floor(now / 800) !== Math.floor((now - 16) / 800)) {
                ControlCenterUI.updateStationArrivalsLive(NetworkStore.selectedStationId);
            }

            requestAnimationFrame((t) => this.step(t));
        },

        emitLiveEvent(train, actionText) {
            this.eventCounter++;
            if (this.eventCounter % 7 !== 0) return; // Dosificar el ticker para lectura cómoda
            const stop = train.routeStops[train.currentStopIndex];
            if (!stop) return;
            ControlCenterUI.appendTickerEvent(
                train.lineCode,
                train.color,
                `${train.id}: ${actionText} ${stop.station_name}`
            );
        }
    };

    // =========================================================================
    // 3. MOTOR DE MAPA ESQUEMÁTICO VECTORIAL SVG (5520 x 3980 · 54 u. SVG / km)
    // =========================================================================
    const SchematicMapEngine = {
        svg: null,
        viewport: null,
        // Vista inicial centrada en la metrópoli con el anillo de Línea A y el núcleo denso
        viewBox: { x: 80, y: 150, w: 4380, h: 3760 },
        isPanning: false,
        panStart: { x: 0, y: 0, vx: 0, vy: 0 },
        panBoundingRect: null,
        dragTarget: null, // { type: 'station'|'polygon', id, vertexIdx }
        dragRafId: null,

        init() {
            this.svg = document.getElementById("metroSchematicSvg");
            this.viewport = document.getElementById("schematicViewport");
            this.applyViewBox();
            this.renderGrid();
            this.bindInteractionEvents();
        },

        applyViewBox() {
            if (!this.svg) return;
            const { x, y, w, h } = this.viewBox;
            this.svg.setAttribute("viewBox", `${x.toFixed(1)} ${y.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`);
        },

        scheduleDragRender() {
            if (this.dragRafId) return;
            const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (cb) => setTimeout(cb, 16);
            this.dragRafId = raf(() => {
                this.dragRafId = null;
                if (!this.dragTarget) return;
                if (this.dragTarget.type === "polygon") {
                    this.renderCityOutlines();
                    this.renderEditHandles();
                } else {
                    this.renderTracksAndStations();
                    if (this.dragTarget.type === "waypoint") {
                        this.renderEditHandles();
                    }
                }
            });
        },

        cancelDragRender() {
            if (this.dragRafId) {
                if (typeof cancelAnimationFrame === "function") {
                    cancelAnimationFrame(this.dragRafId);
                } else {
                    clearTimeout(this.dragRafId);
                }
                this.dragRafId = null;
            }
        },

        updateStationSelectionUI(prevId, newId) {
            const stationsLayer = document.getElementById("svgLayerStations");
            if (!stationsLayer) {
                this.renderTracksAndStations();
                return;
            }

            const updateNode = (id, isSelected) => {
                if (!id) return;
                const el = stationsLayer.querySelector(`.svg-station-node[data-station-id="${id}"]`);
                if (!el) return;
                const st = NetworkStore.stationsById.get(id);
                if (!st) return;

                const isClosed = st.operational_status === "closed_permanent";
                const isConst = st.operational_status === "construction";
                const isOrphan = !st.lines || st.lines.length === 0;
                const onlyBrt = !isOrphan && st.lines.every(c => c.startsWith("S"));
                const primaryLine = (!isOrphan && st.lines.length === 1) ? NetworkStore.linesByCode.get(st.lines[0]) : null;

                const radius = isSelected ? 15.0 : (st.is_transfer ? 10.6 : (st.is_premium_stop ? 9.0 : 7.4));
                const stroke = isSelected
                    ? "#0055A4"
                    : (isClosed ? "#9B2C2C" : (isConst ? "#0098D4" : (isOrphan ? "#94a3b8" : (primaryLine ? primaryLine.color : "#182026"))));
                const strokeW = isSelected ? 4.2 : (st.is_transfer ? 3.2 : 2.5);

                if (onlyBrt && el.tagName.toLowerCase() === "rect") {
                    const half = radius * 0.92;
                    el.setAttribute("x", (st.x - half).toFixed(1));
                    el.setAttribute("y", (st.y - half).toFixed(1));
                    el.setAttribute("width", (half * 2).toFixed(1));
                    el.setAttribute("height", (half * 2).toFixed(1));
                } else if (el.tagName.toLowerCase() === "circle") {
                    el.setAttribute("r", radius.toString());
                }
                el.setAttribute("stroke", stroke);
                el.setAttribute("stroke-width", strokeW.toString());
            };

            if (prevId && prevId !== newId) {
                updateNode(prevId, false);
            }
            if (newId) {
                updateNode(newId, true);
            }
        },

        zoomBy(factor, clientX, clientY) {
            const rect = this.svg.getBoundingClientRect();
            const relX = clientX !== undefined ? (clientX - rect.left) / rect.width : 0.5;
            const relY = clientY !== undefined ? (clientY - rect.top) / rect.height : 0.5;

            const newW = Math.max(250, Math.min(5520, this.viewBox.w * factor));
            const newH = Math.max(180, Math.min(3980, this.viewBox.h * factor));

            this.viewBox.x += (this.viewBox.w - newW) * relX;
            this.viewBox.y += (this.viewBox.h - newH) * relY;
            this.viewBox.w = newW;
            this.viewBox.h = newH;
            this.applyViewBox();
        },

        flyToBox(x, y, w, h) {
            const start = { ...this.viewBox };
            const startTime = performance.now();
            const duration = 380;
            const animateStep = (now) => {
                const t = Math.min(1, (now - startTime) / duration);
                const ease = 1 - Math.pow(1 - t, 3);
                this.viewBox.x = start.x + (x - start.x) * ease;
                this.viewBox.y = start.y + (y - start.y) * ease;
                this.viewBox.w = start.w + (w - start.w) * ease;
                this.viewBox.h = start.h + (h - start.h) * ease;
                this.applyViewBox();
                if (t < 1) requestAnimationFrame(animateStep);
            };
            requestAnimationFrame(animateStep);
        },

        clientToSvgCoords(clientX, clientY) {
            const rect = this.svg.getBoundingClientRect();
            const rx = (clientX - rect.left) / rect.width;
            const ry = (clientY - rect.top) / rect.height;
            return {
                x: this.viewBox.x + rx * this.viewBox.w,
                y: this.viewBox.y + ry * this.viewBox.h
            };
        },

        renderGrid() {
            const g = document.getElementById("svgLayerGrid");
            if (!g) return;
            let html = "";
            for (let x = 0; x <= 4500; x += 270) {
                html += `<line x1="${x}" y1="0" x2="${x}" y2="3980" stroke="var(--grid-stroke)" stroke-width="1" />`;
            }
            for (let y = 0; y <= 3980; y += 270) {
                html += `<line x1="0" y1="${y}" x2="4500" y2="${y}" stroke="var(--grid-stroke)" stroke-width="1" />`;
            }
            g.innerHTML = html;
        },

        isLineVisible(line) {
            if (NetworkStore.isolatedLineCode && line.code !== NetworkStore.isolatedLineCode) {
                return false;
            }
            if (NetworkStore.networkFilter !== "all" && line.network_type !== NetworkStore.networkFilter) {
                return false;
            }
            return true;
        },

        isSegmentMatchingInfraFilter(stop) {
            const f = NetworkStore.infraFilter;
            if (f === "all") return true;
            if (f === "closed_permanent" || f === "construction") {
                return stop.segment_status === f;
            }
            return stop.segment_infrastructure === f;
        },

        renderAll() {
            this.renderCityOutlines();
            this.renderTracksAndStations();
            this.buildTrainNodes();
            this.renderEditHandles();
        },

        renderCityOutlines() {
            const g = document.getElementById("svgLayerCityOutlines");
            if (!g) return;
            let html = "";
            for (const zone of NetworkStore.cityOutlines) {
                if (!zone.polygon_points || zone.polygon_points.length < 3) continue;
                const pts = zone.polygon_points.map(p => `${p[0]},${p[1]}`).join(" ");
                const cx = zone.polygon_points.reduce((acc, p) => acc + p[0], 0) / zone.polygon_points.length;
                const cy = zone.polygon_points.reduce((acc, p) => acc + p[1], 0) / zone.polygon_points.length;
                const isWater = zone.zone_type === "water";
                const waterClass = isWater ? " city-zone-water" : "";
                const polyFill = isWater ? "#DCEEFA" : zone.color;
                const polyOpacity = isWater ? 0.95 : zone.opacity;
                const polyStroke = isWater ? "#BAE6FD" : "#94A3B8";
                const polyStrokeWidth = isWater ? 2.4 : 1.8;
                const polyDash = isWater ? "none" : (zone.zone_type === 'metropolitan' ? '12 8' : '8 6');
                html += `
                    <g class="city-zone-group${waterClass}" data-zone-id="${zone.id}">
                        <polygon points="${pts}"
                            fill="${polyFill}"
                            fill-opacity="${polyOpacity}"
                            stroke="${polyStroke}"
                            stroke-width="${polyStrokeWidth}"
                            stroke-opacity="${isWater ? 1.0 : 0.45}"
                            stroke-dasharray="${polyDash}" />
                        <text x="${cx.toFixed(0)}" y="${cy.toFixed(0)}"
                            fill="${isWater ? '#0284C7' : '#475569'}" fill-opacity="0.75"
                            font-size="16" font-weight="700" letter-spacing="0.08em" text-anchor="middle"
                            pointer-events="none">${escapeHtml(zone.name)}</text>
                    </g>
                `;
            }
            g.innerHTML = html;
        },

        computeTerminalBadgeVector(st, line) {
            // Determina el vector unitario exterior hacia donde colocar el icono numérico de terminal (estilo Seoul Metro)
            const branches = new Map();
            for (const sp of line.stops) {
                const bKey = sp.branch || "main";
                if (!branches.has(bKey)) branches.set(bKey, []);
                branches.get(bKey).push(sp);
            }

            for (const [bName, stops] of branches.entries()) {
                const n = stops.length;
                if (n < 2) continue;
                const idx = stops.findIndex(s => s.station_id === st.id);
                if (idx === -1) continue;

                const isCircularMain = Boolean(line.is_circular && bName === "main");
                if (!isCircularMain && idx === 0) {
                    const s0 = stops[0];
                    const s1 = stops[1];
                    const stNext = NetworkStore.stationsById.get(s1.station_id) || s1;
                    const wps = Array.isArray(s0.waypoints) ? s0.waypoints : [];
                    const refPt = wps.length > 0 ? wps[0] : [stNext.x, stNext.y];
                    const dx = st.x - refPt[0];
                    const dy = st.y - refPt[1];
                    const len = Math.hypot(dx, dy) || 1;
                    return { ux: dx / len, uy: dy / len, isEndpoint: true };
                }

                if (!isCircularMain && idx === n - 1) {
                    const prevStop = stops[n - 2];
                    const stPrev = NetworkStore.stationsById.get(prevStop.station_id) || prevStop;
                    const wps = Array.isArray(prevStop.waypoints) ? prevStop.waypoints : [];
                    const refPt = wps.length > 0 ? wps[wps.length - 1] : [stPrev.x, stPrev.y];
                    const dx = st.x - refPt[0];
                    const dy = st.y - refPt[1];
                    const len = Math.hypot(dx, dy) || 1;
                    return { ux: dx / len, uy: dy / len, isEndpoint: true };
                }

                // Estación intermedia o en anillo circular: colocar perpendicularmente hacia el exterior del trazo
                const prevIdx = (idx - 1 + n) % n;
                const nextIdx = (idx + 1) % n;
                const stPrev = NetworkStore.stationsById.get(stops[prevIdx].station_id) || stops[prevIdx];
                const stNext = NetworkStore.stationsById.get(stops[nextIdx].station_id) || stops[nextIdx];
                const tx = stNext.x - stPrev.x;
                const ty = stNext.y - stPrev.y;
                const tLen = Math.hypot(tx, ty) || 1;
                const n1 = [-ty / tLen, tx / tLen];
                const n2 = [ty / tLen, -tx / tLen];
                const outX = st.x - 2120.0;
                const outY = st.y - 1860.0;
                const dot1 = n1[0] * outX + n1[1] * outY;
                const dot2 = n2[0] * outX + n2[1] * outY;
                const chosen = dot1 >= dot2 ? n1 : n2;
                return { ux: chosen[0], uy: chosen[1], isEndpoint: false };
            }

            // Si el usuario asignó manualmente una línea que no pasa por esta estación: colocar a la izquierda
            return { ux: -1, uy: 0, isEndpoint: false };
        },

        computeStationLabelPosition(st, radius, hasTopTerminalBadge = false) {
            if (hasTopTerminalBadge) {
                return { x: st.x, y: st.y + radius + 15.0, anchor: "middle" };
            }

            let avgDx = 0;
            let avgDy = 0;
            let count = 0;

            for (const line of NetworkStore.lines) {
                const stops = line.stops || [];
                for (let i = 0; i < stops.length; i++) {
                    if (stops[i].station_id === st.id) {
                        if (i > 0) {
                            const pSt = NetworkStore.stationsById.get(stops[i - 1].station_id);
                            if (pSt) {
                                avgDx += Math.abs(st.x - pSt.x);
                                avgDy += Math.abs(st.y - pSt.y);
                                count++;
                            }
                        }
                        if (i < stops.length - 1) {
                            const nSt = NetworkStore.stationsById.get(stops[i + 1].station_id);
                            if (nSt) {
                                avgDx += Math.abs(nSt.x - st.x);
                                avgDy += Math.abs(nSt.y - st.y);
                                count++;
                            }
                        }
                    }
                }
            }

            if (count === 0 || (avgDx === 0 && avgDy === 0)) {
                return { x: st.x, y: st.y - (radius + 6.0), anchor: "middle" };
            }

            const ratio = avgDy > 0 ? (avgDx / avgDy) : 999;
            if (ratio > 1.8) {
                // Trazado predominantemente horizontal -> Etiqueta ARRIBA
                return { x: st.x, y: st.y - (radius + 6.0), anchor: "middle" };
            } else if (ratio < 0.55) {
                // Trazado predominantemente vertical -> Etiqueta a la DERECHA
                return { x: st.x + radius + 8.0, y: st.y + 4.0, anchor: "start" };
            } else {
                // Trazado diagonal -> Etiqueta en DIAGONAL arriba-derecha
                return { x: st.x + radius + 6.0, y: st.y - (radius + 4.0), anchor: "start" };
            }
        },

        renderTracksAndStations() {
            const tracksLayer = document.getElementById("svgLayerTracks");
            const trackHitsLayer = document.getElementById("svgLayerTrackHits");
            const stationsLayer = document.getElementById("svgLayerStations");
            const terminalBadgesLayer = document.getElementById("svgLayerTerminalBadges");
            const tagsLayer = document.getElementById("svgLayerStationTags");
            const labelsLayer = document.getElementById("svgLayerLabels");
            if (!tracksLayer || !stationsLayer || !labelsLayer) return;

            let tracksHtml = "";
            let trackHitsHtml = "";
            const visibleStationIds = new Set();
            const widthScale = NetworkStore.trackWidthScale || 1.0;

            // 1. Renderizar trazados por línea y segmento con proporción exacta estilo Seoul Metro Map
            for (const line of NetworkStore.lines) {
                const visible = this.isLineVisible(line);
                const lineOpacity = visible ? 1.0 : 0.08;

                // Agrupar paradas por rama (branch) para dibujar trazos limpios
                const branches = new Map();
                for (const stop of line.stops) {
                    const bKey = stop.branch || "main";
                    if (!branches.has(bKey)) branches.set(bKey, []);
                    branches.get(bKey).push(stop);
                }

                for (const [branchName, stops] of branches.entries()) {
                    const n = stops.length;
                    if (n < 2) continue;
                    const limit = (line.is_circular && branchName === "main") ? n : n - 1;

                    for (let i = 0; i < limit; i++) {
                        const s1 = stops[i];
                        const s2 = stops[(i + 1) % n];
                        const st1 = NetworkStore.stationsById.get(s1.station_id) || s1;
                        const st2 = NetworkStore.stationsById.get(s2.station_id) || s2;

                        const matchesInfra = this.isSegmentMatchingInfraFilter(s1);
                        const segOpacity = matchesInfra ? lineOpacity : 0.07;
                        if (visible && matchesInfra) {
                            visibleStationIds.add(s1.station_id);
                            visibleStationIds.add(s2.station_id);
                        }

                        const strokeColor = NetworkStore.colorMode === "infra"
                            ? (INFRA_COLORS[s1.segment_infrastructure] || line.color)
                            : line.color;

                        const isBrt = line.network_type === "bus_articulado";
                        const isFeeder = line.line_subtype === "alimentadora" && line.code !== "A";
                        const isClosed = s1.segment_status === "closed_permanent" || s2.segment_status === "closed_permanent";
                        const isConst = s1.segment_status === "construction";
                        const baseWidth = (
                            line.code === "A" ? 21.0 : (isBrt ? 13.8 : (isFeeder ? 13.4 : 15.8))
                        ) * widthScale;
                        const wps = Array.isArray(s1.waypoints) ? s1.waypoints : [];
                        const polyPts = [[st1.x, st1.y], ...wps, [st2.x, st2.y]].map(p => `${p[0]},${p[1]}`).join(" ");

                        if (NetworkStore.editMode && visible && matchesInfra) {
                            trackHitsHtml += `
                                <polyline class="svg-track-hit"
                                    data-line-code="${escapeHtml(line.code)}"
                                    data-ls-id="${s1.id}"
                                    data-s1-id="${s1.station_id}"
                                    data-s2-id="${s2.station_id}"
                                    points="${polyPts}" fill="none"
                                    stroke="transparent" stroke-width="${(Math.max(26, baseWidth + 12)).toFixed(1)}"
                                    stroke-linecap="round" stroke-linejoin="round" />
                            `;
                        }

                        // Simbología de ingeniería constructiva y tipología de red
                        if (isClosed) {
                            tracksHtml += `
                                <polyline points="${polyPts}" fill="none"
                                    stroke="#F5D0D0" stroke-width="${(baseWidth + 4.4).toFixed(1)}" stroke-opacity="${segOpacity * 0.9}"
                                    stroke-linecap="round" stroke-linejoin="round" />
                                <polyline points="${polyPts}" fill="none"
                                    stroke="#9B2C2C" stroke-width="${(baseWidth * 0.66).toFixed(1)}" stroke-opacity="${segOpacity * 0.85}"
                                    stroke-dasharray="11 8" stroke-linecap="round" stroke-linejoin="round" />
                            `;
                        } else if (isConst) {
                            tracksHtml += `
                                <polyline points="${polyPts}" fill="none"
                                    stroke="${strokeColor}" stroke-width="${baseWidth.toFixed(1)}" stroke-opacity="${segOpacity * 0.88}"
                                    stroke-dasharray="16 10" stroke-linecap="round" stroke-linejoin="round" />
                            `;
                        } else if (isBrt) {
                            tracksHtml += `
                                <polyline points="${polyPts}" fill="none"
                                    stroke="${strokeColor}" stroke-width="${(baseWidth + 1.8).toFixed(1)}" stroke-opacity="${segOpacity}"
                                    stroke-linecap="round" stroke-linejoin="round" />
                                <polyline points="${polyPts}" fill="none"
                                    stroke="#FFFFFF" stroke-width="${(3.8 * widthScale).toFixed(1)}" stroke-opacity="${segOpacity * 0.95}"
                                    stroke-dasharray="9 6" stroke-linecap="round" stroke-linejoin="round" />
                            `;
                        } else {
                            if (s1.segment_infrastructure === "elevado") {
                                tracksHtml += `
                                    <polyline points="${polyPts}" fill="none"
                                        stroke="#182026" stroke-width="${(baseWidth + 4.8).toFixed(1)}" stroke-opacity="${segOpacity * 0.36}"
                                        stroke-linecap="butt" stroke-linejoin="round" />
                                    <polyline points="${polyPts}" fill="none"
                                        stroke="#FFFFFF" stroke-width="${(baseWidth + 2.2).toFixed(1)}" stroke-opacity="${segOpacity * 0.94}"
                                        stroke-linecap="butt" stroke-linejoin="round" />
                                `;
                            } else if (s1.segment_infrastructure === "tunel_profundo") {
                                tracksHtml += `
                                    <polyline points="${polyPts}" fill="none"
                                        stroke="#182026" stroke-width="${(baseWidth + 4.0).toFixed(1)}" stroke-opacity="${segOpacity * 0.38}"
                                        stroke-dasharray="7 5" stroke-linejoin="round" />
                                `;
                            }

                            tracksHtml += `
                                <polyline points="${polyPts}" fill="none"
                                    stroke="${strokeColor}" stroke-width="${baseWidth.toFixed(1)}" stroke-opacity="${segOpacity}"
                                    stroke-linecap="round" stroke-linejoin="round" />
                            `;

                            if (s1.segment_infrastructure === "superficial") {
                                tracksHtml += `
                                    <polyline points="${polyPts}" fill="none"
                                        stroke="#FFFFFF" stroke-width="${(3.0 * widthScale).toFixed(1)}" stroke-opacity="${segOpacity * 0.80}"
                                        stroke-dasharray="3.5 7.5" stroke-linejoin="round" />
                                `;
                            }
                        }
                    }
                }
            }
            tracksLayer.innerHTML = tracksHtml;
            if (trackHitsLayer) trackHitsLayer.innerHTML = trackHitsHtml;

            // 2. Renderizar las estaciones, los iconos numéricos de terminal al lado, sus tags y etiquetas
            let stationsHtml = "";
            let terminalBadgesHtml = "";
            let tagsHtml = "";
            let labelsHtml = "";
            const placedTerminalCenters = [];

            for (const st of NetworkStore.stations) {
                const isVis = visibleStationIds.has(st.id);
                const stOpacity = isVis ? 1.0 : 0.12;
                const isSelected = st.id === NetworkStore.selectedStationId;
                const isClosed = st.operational_status === "closed_permanent";
                const isConst = st.operational_status === "construction";
                const isOrphan = !st.lines || st.lines.length === 0;
                const onlyBrt = !isOrphan && st.lines.every(c => c.startsWith("S"));
                const primaryLine = (!isOrphan && st.lines.length === 1) ? NetworkStore.linesByCode.get(st.lines[0]) : null;

                const isTransfer = st.is_transfer || (Array.isArray(st.lines) && st.lines.length > 1);
                const radius = isSelected ? 13.5 : (isTransfer ? 10.4 : (st.is_premium_stop ? 8.2 : 5.8));
                const fill = isClosed ? "#FDE8E8" : (isOrphan ? "var(--bg-surface)" : (st.is_premium_stop ? "#F59E0B" : "#FFFFFF"));
                const stroke = isSelected
                    ? "#0055A4"
                    : (isClosed ? "#9B2C2C" : (isConst ? "#0098D4" : (isOrphan ? "#94a3b8" : (primaryLine ? primaryLine.color : "#182026"))));
                const strokeW = isSelected ? 3.8 : (isTransfer ? 2.6 : 2.2);
                const orphanClass = isOrphan ? " orphan" : "";
                const dashAttr = isOrphan ? ' stroke-dasharray="4.5 3"' : '';
                const orphanHint = isOrphan ? " · Estación huérfana (sin línea asignada)" : "";

                if (isTransfer) {
                    // Estilo Nodo de Correspondencia / Transbordo Seoul Metro Map (Doble Anillo concéntrico característico)
                    const outerR = isSelected ? 14.5 : 10.4;
                    const innerR = isSelected ? 8.2 : 5.6;
                    const outerStroke = isSelected ? "#0055A4" : "#1E293B";
                    const innerStroke = isSelected ? "#0055A4" : (primaryLine ? primaryLine.color : "#1E293B");
                    stationsHtml += `
                        <g class="svg-station-node transfer-node${orphanClass}" data-station-id="${st.id}" opacity="${stOpacity}">
                            <circle cx="${st.x}" cy="${st.y}" r="${outerR}"
                                fill="#FFFFFF" stroke="${outerStroke}" stroke-width="${strokeW}"${dashAttr} />
                            <circle cx="${st.x}" cy="${st.y}" r="${innerR}"
                                fill="${fill}" stroke="${innerStroke}" stroke-width="1.8" />
                            <title>${escapeHtml(st.name)} · Nodo de Correspondencia (${st.lines.join(", ")})${orphanHint}</title>
                        </g>
                    `;
                } else if (onlyBrt) {
                    const half = radius * 0.95;
                    stationsHtml += `
                        <rect class="svg-station-node${orphanClass}" data-station-id="${st.id}"
                            x="${(st.x - half).toFixed(1)}" y="${(st.y - half).toFixed(1)}"
                            width="${(half * 2).toFixed(1)}" height="${(half * 2).toFixed(1)}" rx="2.5"
                            fill="${fill}" stroke="${stroke}" stroke-width="${strokeW}"${dashAttr}
                            opacity="${stOpacity}">
                            <title>${escapeHtml(st.name)}${orphanHint}</title>
                        </rect>
                    `;
                } else {
                    stationsHtml += `
                        <circle class="svg-station-node${orphanClass}" data-station-id="${st.id}"
                            cx="${st.x}" cy="${st.y}" r="${radius}"
                            fill="${fill}" stroke="${stroke}" stroke-width="${strokeW}"${dashAttr}
                            opacity="${stOpacity}">
                            <title>${escapeHtml(st.name)}${orphanHint}</title>
                        </circle>
                    `;
                }

                if (isClosed && isVis) {
                    stationsHtml += `
                        <path d="M ${st.x - 4.8} ${st.y - 4.8} L ${st.x + 4.8} ${st.y + 4.8} M ${st.x + 4.8} ${st.y - 4.8} L ${st.x - 4.8} ${st.y + 4.8}"
                            stroke="#9B2C2C" stroke-width="2.2" pointer-events="none" />
                    `;
                }

                // 2A. Iconos con el número/código de línea al lado de cada terminal (estilo Seoul Metro Map)
                let rightBadgeMaxX = 0;
                let hasTopTerminalBadge = false;
                const termCodes = Array.isArray(st.terminal_lines) ? st.terminal_lines : [];
                if (termCodes.length > 0) {
                    for (const tCode of termCodes) {
                        const tLine = NetworkStore.linesByCode.get(tCode);
                        if (!tLine) continue;
                        const tLineVis = this.isLineVisible(tLine);
                        const badgeOp = tLineVis ? 1.0 : 0.08;
                        const { ux, uy, isEndpoint } = this.computeTerminalBadgeVector(st, tLine);
                        const isBrtBadge = tLine.network_type === "bus_articulado";
                        const rBadge = isBrtBadge ? 17.5 : 16.2;
                        const dist = radius + rBadge + 7.5;

                        let bx = st.x + ux * dist;
                        let by = st.y + uy * dist;

                        // Evitar colisión si dos líneas tienen terminal en la misma estación o muy cerca
                        const perpX = -uy;
                        const perpY = ux;
                        const candidateOffsets = [0, 34, -34, 68, -68];
                        for (const off of candidateOffsets) {
                            const cx = st.x + ux * dist + perpX * off;
                            const cy = st.y + uy * dist + perpY * off;
                            const collides = placedTerminalCenters.some(
                                p => Math.hypot(p[0] - cx, p[1] - cy) < 32.5
                            );
                            if (!collides) {
                                bx = cx;
                                by = cy;
                                break;
                            }
                        }
                        placedTerminalCenters.push([bx, by]);

                        if (bx > st.x + 10 && Math.abs(by - st.y) < 20) {
                            rightBadgeMaxX = Math.max(rightBadgeMaxX, bx + rBadge);
                        }
                        if (by < st.y - 12 && Math.abs(bx - st.x) < 22) {
                            hasTopTerminalBadge = true;
                        }

                        const fgText = getBadgeTextColor(tLine.color, tLine.text_color || "#FFFFFF");
                        const stubStartX = (st.x + ux * (radius + 0.5)).toFixed(1);
                        const stubStartY = (st.y + uy * (radius + 0.5)).toFixed(1);
                        const stubHtml = isEndpoint ? `
                            <line x1="${stubStartX}" y1="${stubStartY}" x2="${bx.toFixed(1)}" y2="${by.toFixed(1)}"
                                  stroke="${tLine.color}" stroke-width="${(Math.min(13, 11.5 * widthScale)).toFixed(1)}"
                                  stroke-linecap="round" opacity="${badgeOp}" pointer-events="none" />
                        ` : "";

                        if (isBrtBadge) {
                            terminalBadgesHtml += `
                                ${stubHtml}
                                <g class="svg-terminal-badge" data-station-id="${st.id}" data-line-code="${escapeHtml(tLine.code)}"
                                   transform="translate(${bx.toFixed(1)}, ${by.toFixed(1)})" opacity="${badgeOp}">
                                    <title>Terminal ${escapeHtml(tLine.name)}: ${escapeHtml(st.name)} (Clic para editar)</title>
                                    <rect x="-18.5" y="-14" width="37" height="28" rx="12"
                                          fill="${tLine.color}" stroke="#FFFFFF" stroke-width="2.6" />
                                    <text x="0" y="0" dy="0.35em" text-anchor="middle"
                                          fill="${fgText}" font-size="13.4" font-weight="800">${escapeHtml(tLine.code)}</text>
                                </g>
                            `;
                        } else {
                            const fSize = tLine.code.length >= 2 ? "14.2" : "16.4";
                            terminalBadgesHtml += `
                                ${stubHtml}
                                <g class="svg-terminal-badge" data-station-id="${st.id}" data-line-code="${escapeHtml(tLine.code)}"
                                   transform="translate(${bx.toFixed(1)}, ${by.toFixed(1)})" opacity="${badgeOp}">
                                    <title>Terminal ${escapeHtml(tLine.name)}: ${escapeHtml(st.name)} (Clic para editar)</title>
                                    <circle cx="0" cy="0" r="16.2"
                                            fill="${tLine.color}" stroke="#FFFFFF" stroke-width="2.7" />
                                    <text x="0" y="0" dy="0.35em" text-anchor="middle"
                                          fill="${fgText}" font-size="${fSize}" font-weight="800">${escapeHtml(tLine.code)}</text>
                                </g>
                            `;
                        }
                    }
                }

                // 2B. Renderizar tags con iconos vectoriales a un costado de la estación (desplazados si hay insignia terminal a la derecha)
                if (Array.isArray(st.icon_tags) && st.icon_tags.length > 0) {
                    const validTags = st.icon_tags.map(tid => STATION_ICON_TAGS_MAP.get(tid)).filter(Boolean);
                    if (validTags.length > 0) {
                        const baseTx = Math.max(st.x + radius + 5.2, rightBadgeMaxX > 0 ? rightBadgeMaxX + 5.5 : 0);
                        const baseTy = st.y - 8.0;
                        validTags.forEach((tagDef, tIdx) => {
                            const tx = (baseTx + tIdx * 18.0).toFixed(1);
                            const ty = baseTy.toFixed(1);
                            tagsHtml += `
                                <g class="svg-station-tag" data-station-id="${st.id}"
                                   transform="translate(${tx}, ${ty})" opacity="${stOpacity}">
                                    <title>${escapeHtml(st.name)} · ${escapeHtml(tagDef.label)}</title>
                                    <rect x="0" y="0" width="16" height="16" rx="3.8"
                                          fill="${tagDef.bg}" stroke="#FFFFFF" stroke-width="1.35" />
                                    ${tagDef.svgPath}
                                </g>
                            `;
                        });
                    }
                }

                if (NetworkStore.showLabels && isVis) {
                    const hasTags = Array.isArray(st.icon_tags) && st.icon_tags.length > 0;
                    const hasTerm = termCodes.length > 0;
                    const showLabel = st.is_transfer || st.is_terminal || hasTerm || st.is_premium_stop || isClosed || hasTags || Boolean(NetworkStore.isolatedLineCode);
                    if (showLabel) {
                        const fontSize = (st.is_transfer || hasTerm) ? 11.8 : 10.0;
                        const pos = this.computeStationLabelPosition(st, radius, hasTopTerminalBadge);
                        labelsHtml += `
                            <text x="${pos.x.toFixed(1)}" y="${pos.y.toFixed(1)}"
                                font-size="${fontSize}" font-weight="${(st.is_transfer || hasTerm) ? 700 : 600}"
                                fill="var(--text-primary)" stroke="var(--bg-canvas)" stroke-width="3.6"
                                paint-order="stroke" text-anchor="${pos.anchor}" pointer-events="none">${escapeHtml(st.name)}</text>
                        `;
                    }
                }
            }

            stationsLayer.innerHTML = stationsHtml;
            if (terminalBadgesLayer) terminalBadgesLayer.innerHTML = terminalBadgesHtml;
            if (tagsLayer) tagsLayer.innerHTML = tagsHtml;
            labelsLayer.innerHTML = labelsHtml;
        },

        buildTrainNodes() {
            const layer = document.getElementById("svgLayerTrains");
            if (!layer) return;
            layer.innerHTML = "";
            TrainSimulationEngine.svgTrainElements.clear();

            const ns = "http://www.w3.org/2000/svg";
            for (const train of TrainSimulationEngine.trains) {
                const g = document.createElementNS(ns, "g");
                g.setAttribute("class", "svg-train-group");
                g.setAttribute("data-train-id", train.id);

                // Cuerpo del tren o autobús biarticulado escalado a los trazos estilo Seoul Metro
                const rect = document.createElementNS(ns, "rect");
                const isBrt = train.networkType === "bus_articulado";
                const w = train.isPremium ? 25 : (isBrt ? 20.5 : 22.5);
                const h = train.isPremium ? 13.4 : 11.6;
                rect.setAttribute("x", String(-w / 2));
                rect.setAttribute("y", String(-h / 2));
                rect.setAttribute("width", String(w));
                rect.setAttribute("height", String(h));
                rect.setAttribute("rx", isBrt ? "2.8" : "4.8");
                rect.setAttribute("fill", train.color);
                rect.setAttribute("stroke", train.isPremium ? "#F59E0B" : "#182026");
                rect.setAttribute("stroke-width", train.isPremium ? "2.4" : "1.8");

                // Faro frontal direccional
                const nose = document.createElementNS(ns, "circle");
                nose.setAttribute("cx", String(w / 2 - 3.6));
                nose.setAttribute("cy", "0");
                nose.setAttribute("r", "2.1");
                nose.setAttribute("fill", "#FFFFFF");

                g.appendChild(rect);
                g.appendChild(nose);
                layer.appendChild(g);
                TrainSimulationEngine.svgTrainElements.set(train.id, g);
            }
            this.syncTrainsDOM();
        },

        syncTrainsDOM() {
            for (const train of TrainSimulationEngine.trains) {
                const g = TrainSimulationEngine.svgTrainElements.get(train.id);
                if (!g) continue;

                const line = NetworkStore.linesByCode.get(train.lineCode);
                const visible = line && this.isLineVisible(line);
                if (!visible) {
                    g.setAttribute("display", "none");
                    continue;
                }
                g.removeAttribute("display");
                const scale = (train.id === NetworkStore.selectedTrainId) ? 1.45 : 1.0;
                g.setAttribute(
                    "transform",
                    `translate(${train.x.toFixed(1)}, ${train.y.toFixed(1)}) rotate(${train.angleDeg.toFixed(1)}) scale(${scale})`
                );
            }
        },

        findStopByLsId(lineCode, lsId) {
            const ln = NetworkStore.linesByCode.get(lineCode);
            if (!ln) return null;
            return ln.stops.find(s => s.id === Number(lsId)) || null;
        },

        findClosestSegmentInsertIndex(pts, px, py) {
            let bestIdx = 0;
            let bestDist = Infinity;
            for (let i = 0; i < pts.length - 1; i++) {
                const [x1, y1] = pts[i];
                const [x2, y2] = pts[i + 1];
                const dx = x2 - x1;
                const dy = y2 - y1;
                const lenSq = dx * dx + dy * dy;
                let t = lenSq > 0.001 ? ((px - x1) * dx + (py - y1) * dy) / lenSq : 0;
                t = Math.max(0, Math.min(1, t));
                const projX = x1 + t * dx;
                const projY = y1 + t * dy;
                const dist = Math.hypot(px - projX, py - projY);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestIdx = i;
                }
            }
            return bestIdx;
        },

        snapPointOctilinear(anchor, target) {
            const ax = Number(anchor[0]);
            const ay = Number(anchor[1]);
            const tx = Number(target[0]);
            const ty = Number(target[1]);
            const dx = tx - ax;
            const dy = ty - ay;
            const dist = Math.hypot(dx, dy);
            if (dist < 1.0) return [Math.round(tx * 2) / 2, Math.round(ty * 2) / 2];

            let deg = (Math.atan2(dy, dx) * 180 / Math.PI) % 360;
            if (deg < 0) deg += 360;
            const oct = Math.round(deg / 45) % 8;

            const dDiag = Math.round((dist * 0.7071067811865476) * 2) / 2;
            const dOrtho = Math.round(dist * 2) / 2;

            switch (oct) {
                case 0: // 0° Este (Horizontal derecha)
                    return [Math.round((ax + dOrtho) * 2) / 2, ay];
                case 1: // 45° Sur-Este (Diagonal abajo-derecha)
                    return [Math.round((ax + dDiag) * 2) / 2, Math.round((ay + dDiag) * 2) / 2];
                case 2: // 90° Sur (Vertical abajo)
                    return [ax, Math.round((ay + dOrtho) * 2) / 2];
                case 3: // 135° Sur-Oeste (Diagonal abajo-izquierda)
                    return [Math.round((ax - dDiag) * 2) / 2, Math.round((ay + dDiag) * 2) / 2];
                case 4: // 180° Oeste (Horizontal izquierda)
                    return [Math.round((ax - dOrtho) * 2) / 2, ay];
                case 5: // 225° Norte-Oeste (Diagonal arriba-izquierda)
                    return [Math.round((ax - dDiag) * 2) / 2, Math.round((ay - dDiag) * 2) / 2];
                case 6: // 270° Norte (Vertical arriba)
                    return [ax, Math.round((ay - dOrtho) * 2) / 2];
                case 7: // 315° Norte-Este (Diagonal arriba-derecha)
                    return [Math.round((ax + dDiag) * 2) / 2, Math.round((ay - dDiag) * 2) / 2];
                default:
                    return [tx, ty];
            }
        },

        async persistSegmentWaypoints(stopObj, lineCode) {
            if (!stopObj || !stopObj.id) return;
            try {
                const res = await ApiClient.post(`/api/line-segments/${stopObj.id}/waypoints/`, {
                    waypoints: stopObj.waypoints || [],
                    snap: true
                });
                const resp = res;
                if (resp.ok) {
                    const data = await resp.json();
                    if (data && Array.isArray(data.waypoints)) {
                        stopObj.waypoints = data.waypoints;
                        this.renderTracksAndStations();
                        this.renderEditHandles();
                    }
                }
            } catch (err) {
                console.error("Error al persistir waypoints:", err);
            }
            for (const tr of TrainSimulationEngine.trains) {
                if (!lineCode || tr.lineCode === lineCode) {
                    TrainSimulationEngine.updateTrainPositionGeometry(tr);
                }
            }
            if (NetworkStore.viewMode === "geo") {
                GeoMapEngine.renderGeoNetwork();
            }
        },

        async deleteWaypoint(lineCode, lsId, wpIdx) {
            const stopObj = this.findStopByLsId(lineCode, lsId);
            if (!stopObj || !Array.isArray(stopObj.waypoints)) return;
            const oldWaypoints = JSON.parse(JSON.stringify(stopObj.waypoints));
            stopObj.waypoints.splice(wpIdx, 1);
            HistoryManager.push({
                type: "waypoints",
                lsId: lsId,
                lineCode: lineCode,
                oldWaypoints: oldWaypoints,
                newWaypoints: JSON.parse(JSON.stringify(stopObj.waypoints)),
                description: `Eliminar vértice de Línea ${lineCode}`
            });
            this.renderTracksAndStations();
            this.renderEditHandles();
            await this.persistSegmentWaypoints(stopObj, lineCode);
            showToast(`Vértice eliminado del trazo de Línea ${lineCode}`);
        },

        renderEditHandles() {
            const g = document.getElementById("svgLayerEditHandles");
            if (!g) return;
            if (!NetworkStore.editMode) {
                g.innerHTML = "";
                return;
            }
            let html = "";
            // 1. Vértices cuadrados de polígonos urbanos
            for (const zone of NetworkStore.cityOutlines) {
                if (!zone.polygon_points) continue;
                zone.polygon_points.forEach((pt, idx) => {
                    html += `
                        <rect class="svg-city-handle"
                            data-zone-id="${zone.id}" data-vertex-idx="${idx}"
                            x="${pt[0] - 8}" y="${pt[1] - 8}" width="16" height="16" rx="3"
                            fill="#0055A4" stroke="#FFFFFF" stroke-width="2.2" />
                    `;
                });
            }

            // 2. Vértices de los trazos (waypoints): Visibles en Modo Edición para manipular a conveniencia
            const activeLineCode = VisualEditorTools.getActiveLineCode();
            for (const line of NetworkStore.lines) {
                if (!this.isLineVisible(line)) continue;
                const isActiveLine = line.code === activeLineCode;
                for (const stop of (line.stops || [])) {
                    if (!this.isSegmentMatchingInfraFilter(stop)) continue;
                    const wps = Array.isArray(stop.waypoints) ? stop.waypoints : [];
                    wps.forEach((pt, wpIdx) => {
                        const r = isActiveLine ? 8.0 : 6.4;
                        const strokeW = isActiveLine ? 2.8 : 2.0;
                        html += `
                            <circle class="svg-waypoint-handle"
                                data-line-code="${escapeHtml(line.code)}"
                                data-ls-id="${stop.id}"
                                data-wp-idx="${wpIdx}"
                                cx="${pt[0]}" cy="${pt[1]}" r="${r}"
                                fill="${line.color}" stroke="#FFFFFF" stroke-width="${strokeW}">
                                <title>Vértice Línea ${escapeHtml(line.name)} (Arrastra para moldear a 45°/90° · Clic derecho o doble clic para eliminar)</title>
                            </circle>
                        `;
                    });
                }
            }
            g.innerHTML = html;
        },

        renderRubberBand(mouseSvgPt = null) {
            const g = document.getElementById("svgLayerRubberBand");
            if (!g) return;

            if (VisualEditorTools.activeTool !== "connect_segment" || !VisualEditorTools.segmentSourceStationId || !mouseSvgPt) {
                g.innerHTML = "";
                document.querySelectorAll(".svg-station-node.connect-target-hover").forEach(el => el.classList.remove("connect-target-hover"));
                return;
            }

            const st1 = NetworkStore.stationsById.get(VisualEditorTools.segmentSourceStationId);
            if (!st1) {
                g.innerHTML = "";
                return;
            }

            // Detectar si está sobre una estación destino existente (snap a estación)
            let snapTarget = null;
            let hoveredStId = null;
            let closestDist = 28.0;

            for (const st of NetworkStore.stations) {
                if (st.id === st1.id) continue;
                const dist = Math.hypot(st.x - mouseSvgPt.x, st.y - mouseSvgPt.y);
                if (dist < closestDist) {
                    closestDist = dist;
                    snapTarget = [st.x, st.y];
                    hoveredStId = st.id;
                }
            }

            document.querySelectorAll(".svg-station-node.connect-target-hover").forEach(el => el.classList.remove("connect-target-hover"));
            if (hoveredStId) {
                const hoveredEl = document.querySelector(`.svg-station-node[data-station-id="${hoveredStId}"]`);
                if (hoveredEl) hoveredEl.classList.add("connect-target-hover");
            }

            if (!snapTarget) {
                // Snap octilineal a 45°/90° respecto a st1
                snapTarget = this.snapPointOctilinear([st1.x, st1.y], [mouseSvgPt.x, mouseSvgPt.y]);
            }

            const lineCode = VisualEditorTools.getActiveLineCode();
            const ln = NetworkStore.linesByCode.get(lineCode);
            const strokeColor = ln ? ln.color : "#0055A4";

            g.innerHTML = `
                <line x1="${st1.x}" y1="${st1.y}" x2="${snapTarget[0]}" y2="${snapTarget[1]}"
                    stroke="${strokeColor}" stroke-width="8" opacity="0.25" stroke-linecap="round" />
                <line class="svg-rubber-band-line"
                    x1="${st1.x}" y1="${st1.y}" x2="${snapTarget[0]}" y2="${snapTarget[1]}"
                    stroke="${strokeColor}" stroke-width="4.5" stroke-dasharray="8,5" stroke-linecap="round" />
                <circle class="svg-rubber-band-point"
                    cx="${snapTarget[0]}" cy="${snapTarget[1]}" r="6.5"
                    fill="${strokeColor}" stroke="#FFFFFF" stroke-width="2.5" />
            `;
        },

        bindInteractionEvents() {
            // Zoom con rueda del ratón centrado en el puntero
            this.viewport.addEventListener("wheel", (e) => {
                e.preventDefault();
                const factor = e.deltaY > 0 ? 1.14 : 0.87;
                this.zoomBy(factor, e.clientX, e.clientY);
            }, { passive: false });

            // Clic derecho o doble clic sobre un vértice del trazo para eliminarlo
            this.viewport.addEventListener("contextmenu", (e) => {
                if (VisualEditorTools.activeTool === "connect_segment") {
                    e.preventDefault();
                    VisualEditorTools.cancel();
                    showToast("Trazado finalizado");
                    return;
                }
                if (!NetworkStore.editMode) return;
                const wpEl = e.target.closest(".svg-waypoint-handle");
                if (wpEl) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.deleteWaypoint(
                        wpEl.dataset.lineCode,
                        Number(wpEl.dataset.lsId),
                        Number(wpEl.dataset.wpIdx)
                    );
                }
            });

            this.viewport.addEventListener("dblclick", (e) => {
                if (!NetworkStore.editMode) return;
                const wpEl = e.target.closest(".svg-waypoint-handle");
                if (wpEl) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.deleteWaypoint(
                        wpEl.dataset.lineCode,
                        Number(wpEl.dataset.lsId),
                        Number(wpEl.dataset.wpIdx)
                    );
                }
            });

            // Inicio de arrastre (Pan o Edición Cartográfica de trazo/estación/polígono)
            this.viewport.addEventListener("pointerdown", (e) => {
                const wpEl = e.target.closest(".svg-waypoint-handle");
                const stEl = e.target.closest(".svg-station-node");
                const termBadgeEl = e.target.closest(".svg-terminal-badge");
                const tagEl = e.target.closest(".svg-station-tag");
                const handleEl = e.target.closest(".svg-city-handle");
                const trackHitEl = e.target.closest(".svg-track-hit");
                const trainEl = e.target.closest(".svg-train-group");

                // Herramientas activas del editor visual
                if (VisualEditorTools.activeTool === "add_station" && e.button === 0) {
                    e.stopPropagation();
                    const svgPt = this.clientToSvgCoords(e.clientX, e.clientY);
                    VisualEditorTools.openNewStationModal(svgPt.x, svgPt.y);
                    return;
                }

                if (VisualEditorTools.activeTool === "connect_segment" && e.button === 0) {
                    e.stopPropagation();
                    if (stEl) {
                        const stId = Number(stEl.dataset.stationId);
                        VisualEditorTools.handleStationClickForSegment(stId);
                        return;
                    }
                    // Clic en lienzo vacío en modo trazado: crea y conecta nuevo punto estilo MetroMapMaker
                    const svgPt = this.clientToSvgCoords(e.clientX, e.clientY);
                    if (VisualEditorTools.segmentSourceStationId !== null) {
                        const st1 = NetworkStore.stationsById.get(VisualEditorTools.segmentSourceStationId);
                        const snapped = st1 ? this.snapPointOctilinear([st1.x, st1.y], [svgPt.x, svgPt.y]) : [svgPt.x, svgPt.y];
                        VisualEditorTools.createAndConnectNewStation(snapped[0], snapped[1]);
                    } else {
                        VisualEditorTools.createAndConnectNewStation(svgPt.x, svgPt.y);
                    }
                    return;
                }

                if (VisualEditorTools.activeTool === "add_correspondence" && stEl && e.button === 0) {
                    e.stopPropagation();
                    const stId = Number(stEl.dataset.stationId);
                    VisualEditorTools.handleStationClickForCorrespondence(stId);
                    return;
                }

                if (NetworkStore.editMode && wpEl) {
                    e.stopPropagation();
                    const lineCode = wpEl.dataset.lineCode;
                    const lsId = Number(wpEl.dataset.lsId);
                    const wpIdx = Number(wpEl.dataset.wpIdx);
                    if (e.button === 2 || e.altKey) {
                        this.deleteWaypoint(lineCode, lsId, wpIdx);
                        return;
                    }
                    const stopObj = this.findStopByLsId(lineCode, lsId);
                    if (stopObj) {
                        const oldWaypoints = JSON.parse(JSON.stringify(stopObj.waypoints || []));
                        this.dragTarget = {
                            type: "waypoint",
                            lineCode,
                            lsId,
                            stopObj,
                            wpIdx,
                            oldWaypoints,
                            moved: false
                        };
                        this.viewport.setPointerCapture(e.pointerId);
                    }
                    return;
                }

                if (NetworkStore.editMode && stEl && e.button === 0) {
                    e.stopPropagation();
                    const stId = Number(stEl.dataset.stationId);
                    const st = NetworkStore.stationsById.get(stId);
                    this.dragTarget = {
                        type: "station",
                        id: stId,
                        startX: st ? st.x : 0,
                        startY: st ? st.y : 0,
                        moved: false
                    };
                    this.viewport.setPointerCapture(e.pointerId);
                    return;
                }

                if (NetworkStore.editMode && handleEl && e.button === 0) {
                    e.stopPropagation();
                    this.dragTarget = {
                        type: "polygon",
                        id: Number(handleEl.dataset.zoneId),
                        vertexIdx: Number(handleEl.dataset.vertexIdx)
                    };
                    this.viewport.setPointerCapture(e.pointerId);
                    return;
                }

                // Clic y arrastre sobre cualquier tramo de línea para crear y moldear un nuevo vértice
                if (NetworkStore.editMode && trackHitEl && e.button === 0) {
                    e.stopPropagation();
                    const lineCode = trackHitEl.dataset.lineCode;
                    const lsId = Number(trackHitEl.dataset.lsId);
                    const s1Id = Number(trackHitEl.dataset.s1Id);
                    const s2Id = Number(trackHitEl.dataset.s2Id);
                    const stopObj = this.findStopByLsId(lineCode, lsId);
                    if (stopObj) {
                        const svgPt = this.clientToSvgCoords(e.clientX, e.clientY);
                        const st1 = NetworkStore.stationsById.get(s1Id) || stopObj;
                        const st2 = NetworkStore.stationsById.get(s2Id) || stopObj;
                        if (!Array.isArray(stopObj.waypoints)) stopObj.waypoints = [];
                        const oldWaypoints = JSON.parse(JSON.stringify(stopObj.waypoints));
                        const pts = [[st1.x, st1.y], ...stopObj.waypoints, [st2.x, st2.y]];
                        const insertIdx = this.findClosestSegmentInsertIndex(pts, svgPt.x, svgPt.y);
                        const anchor = pts[insertIdx];
                        const snappedPt = this.snapPointOctilinear(anchor, [svgPt.x, svgPt.y]);
                        stopObj.waypoints.splice(insertIdx, 0, snappedPt);
                        this.renderTracksAndStations();
                        this.renderEditHandles();
                        this.dragTarget = {
                            type: "waypoint",
                            lineCode,
                            lsId,
                            stopObj,
                            wpIdx: insertIdx,
                            s1Id,
                            oldWaypoints,
                            moved: true
                        };
                        this.viewport.setPointerCapture(e.pointerId);
                    }
                    return;
                }

                if (termBadgeEl) {
                    const stId = Number(termBadgeEl.dataset.stationId);
                    ControlCenterUI.selectStation(stId);
                    return;
                }

                if (tagEl) {
                    const stId = Number(tagEl.dataset.stationId);
                    ControlCenterUI.selectStation(stId);
                    return;
                }

                if (trainEl) {
                    const tId = trainEl.dataset.trainId;
                    ControlCenterUI.selectTrain(tId);
                    return;
                }

                if (stEl) {
                    const stId = Number(stEl.dataset.stationId);
                    ControlCenterUI.selectStation(stId);
                    return;
                }

                this.isPanning = true;
                this.viewport.classList.add("dragging");
                this.panBoundingRect = this.svg.getBoundingClientRect();
                this.panStart = {
                    x: e.clientX,
                    y: e.clientY,
                    vx: this.viewBox.x,
                    vy: this.viewBox.y
                };
                this.viewport.setPointerCapture(e.pointerId);
            });

            this.viewport.addEventListener("pointermove", (e) => {
                const svgPt = this.clientToSvgCoords(e.clientX, e.clientY);
                const lat = (19.420000 + ((1860.0 - svgPt.y) / 54.0) / 111.195080).toFixed(4);
                const lng = (-99.140000 + ((svgPt.x - 2120.0) / 54.0) / 104.868820).toFixed(4);
                const statusEl = document.getElementById("cursorCoordsDisplay");
                if (statusEl) {
                    statusEl.textContent = `Lienzo: X ${Math.round(svgPt.x)} · Y ${Math.round(svgPt.y)} (54 u/km) | Geo: ${lat}° N, ${lng}° O`;
                }

                if (VisualEditorTools.activeTool === "connect_segment" && VisualEditorTools.segmentSourceStationId !== null) {
                    this.renderRubberBand(svgPt);
                }

                if (this.dragTarget) {
                    if (this.dragTarget.type === "station") {
                        const st = NetworkStore.stationsById.get(this.dragTarget.id);
                        if (st) {
                            st.x = Math.round(svgPt.x * 2) / 2;
                            st.y = Math.round(svgPt.y * 2) / 2;
                            st.lat = Number(lat);
                            st.lng = Number(lng);
                            this.dragTarget.moved = true;
                            this.scheduleDragRender();
                        }
                    } else if (this.dragTarget.type === "waypoint") {
                        const { stopObj, wpIdx } = this.dragTarget;
                        if (stopObj && Array.isArray(stopObj.waypoints) && stopObj.waypoints[wpIdx]) {
                            const st1 = NetworkStore.stationsById.get(stopObj.station_id) || stopObj;
                            const anchor = wpIdx > 0 ? stopObj.waypoints[wpIdx - 1] : [st1.x, st1.y];
                            // El snap octilineal a múltiplos exactos de 45° es 100% automático en cada arrastre
                            const nextPt = this.snapPointOctilinear(anchor, [svgPt.x, svgPt.y]);
                            stopObj.waypoints[wpIdx] = nextPt;
                            this.dragTarget.moved = true;
                            this.scheduleDragRender();
                        }
                    } else if (this.dragTarget.type === "polygon") {
                        const zone = NetworkStore.cityOutlines.find(z => z.id === this.dragTarget.id);
                        if (zone && zone.polygon_points[this.dragTarget.vertexIdx]) {
                            zone.polygon_points[this.dragTarget.vertexIdx] = [
                                Math.round(svgPt.x),
                                Math.round(svgPt.y)
                            ];
                            this.scheduleDragRender();
                        }
                    }
                    return;
                }

                if (!this.isPanning) return;
                const rect = this.panBoundingRect || this.svg.getBoundingClientRect();
                const dx = (e.clientX - this.panStart.x) * (this.viewBox.w / rect.width);
                const dy = (e.clientY - this.panStart.y) * (this.viewBox.h / rect.height);
                this.viewBox.x = this.panStart.vx - dx;
                this.viewBox.y = this.panStart.vy - dy;
                this.applyViewBox();
            });

            const finishPointer = async () => {
                this.cancelDragRender();
                this.panBoundingRect = null;
                if (this.dragTarget) {
                    const target = this.dragTarget;
                    this.dragTarget = null;
                    if (target.type === "station") {
                        const st = NetworkStore.stationsById.get(target.id);
                        if (st) {
                            if (target.moved) {
                                this.renderTracksAndStations();
                                await ApiClient.post(`/api/stations/${st.id}/update/`, { x: st.x, y: st.y });
                                HistoryManager.push({
                                    type: "move_station",
                                    stationId: st.id,
                                    oldX: target.startX,
                                    oldY: target.startY,
                                    newX: st.x,
                                    newY: st.y,
                                    description: `Mover estación "${st.name}"`
                                });
                                showToast(`Coordenadas de ${st.name} actualizadas (${st.x}, ${st.y})`);
                            }
                            ControlCenterUI.selectStation(st.id);
                        }
                    } else if (target.type === "waypoint") {
                        this.renderTracksAndStations();
                        this.renderEditHandles();
                        if (target.moved) {
                            HistoryManager.push({
                                type: "waypoints",
                                lsId: target.lsId,
                                lineCode: target.lineCode,
                                oldWaypoints: target.oldWaypoints || [],
                                newWaypoints: JSON.parse(JSON.stringify(target.stopObj.waypoints || [])),
                                description: `Moldear trazo de Línea ${target.lineCode}`
                            });
                        }
                        await this.persistSegmentWaypoints(target.stopObj, target.lineCode);
                        showToast(`Trazo de Línea ${target.lineCode} moldeado y guardado`);
                    } else if (target.type === "polygon") {
                        const zone = NetworkStore.cityOutlines.find(z => z.id === target.id);
                        if (zone) {
                            this.renderCityOutlines();
                            this.renderEditHandles();
                            await ApiClient.post(`/api/city-outlines/${zone.id}/update/`, { polygon_points: zone.polygon_points });
                            showToast(`Polígono urbano "${zone.name}" actualizado`);
                        }
                    }
                }
                this.isPanning = false;
                this.viewport.classList.remove("dragging");
            };

            this.viewport.addEventListener("pointerup", finishPointer);
            this.viewport.addEventListener("pointercancel", finishPointer);
        }
    };

    // =========================================================================
    // 4. MOTOR DE VISTA GEOGRÁFICA ALTERNATIVA (Leaflet)
    // =========================================================================
    const GeoMapEngine = {
        map: null,
        layerGroup: null,
        trainLayerGroup: null,

        init() {
            if (this.map || typeof L === "undefined") return;
            this.map = L.map("leafletGeoMap", {
                center: [19.4200, -99.1400],
                zoom: 11,
                zoomControl: false
            });

            // Capa base cartográfica clara estilo señalización real
            L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
                attribution: "&copy; OpenStreetMap &copy; CARTO · SIMMA Geoespacial (54 u/km)",
                subdomains: "abcd",
                maxZoom: 19
            }).addTo(this.map);

            this.layerGroup = L.layerGroup().addTo(this.map);
            this.trainLayerGroup = L.layerGroup().addTo(this.map);
        },

        renderGeoNetwork() {
            this.init();
            if (!this.map) return;
            this.layerGroup.clearLayers();
            this.trainLayerGroup.clearLayers();
            TrainSimulationEngine.geoTrainMarkers.clear();

            // 1. Polígonos geográficos de la ciudad ficticia (Proyección Equirectangular Tangente Local 54 u/km)
            for (const zone of NetworkStore.cityOutlines) {
                const latlngs = zone.polygon_points.map(pt => [
                    19.420000 + ((1860.0 - pt[1]) / 54.0) / 111.195080,
                    -99.140000 + ((pt[0] - 2120.0) / 54.0) / 104.868820
                ]);
                L.polygon(latlngs, {
                    color: "#64748B",
                    weight: 1.5,
                    fillColor: zone.color,
                    fillOpacity: 0.45
                }).bindTooltip(`${zone.name} (${zone.elevation_m} m s.n.m.)`).addTo(this.layerGroup);
            }

            // 2. Líneas y estaciones en coordenadas (lat, lng)
            for (const line of NetworkStore.lines) {
                if (!SchematicMapEngine.isLineVisible(line)) continue;
                const branches = new Map();
                for (const stop of line.stops) {
                    const bKey = stop.branch || "main";
                    if (!branches.has(bKey)) branches.set(bKey, []);
                    branches.get(bKey).push(stop);
                }
                for (const [bName, stops] of branches.entries()) {
                    const pts = [];
                    const n = stops.length;
                    const limit = (line.is_circular && bName === "main") ? n : n - 1;
                    for (let i = 0; i < limit; i++) {
                        const s1 = stops[i];
                        const st1 = NetworkStore.stationsById.get(s1.station_id) || s1;
                        pts.push([st1.lat, st1.lng]);
                        const wps = Array.isArray(s1.waypoints) ? s1.waypoints : [];
                        for (const wp of wps) {
                            pts.push([
                                19.420000 + ((1860.0 - wp[1]) / 54.0) / 111.195080,
                                -99.140000 + ((wp[0] - 2120.0) / 54.0) / 104.868820
                            ]);
                        }
                    }
                    if (!(line.is_circular && bName === "main") && n > 0) {
                        const lastS = stops[n - 1];
                        const lastSt = NetworkStore.stationsById.get(lastS.station_id) || lastS;
                        pts.push([lastSt.lat, lastSt.lng]);
                    } else if (line.is_circular && bName === "main" && pts.length > 2) {
                        const firstS = stops[0];
                        const firstSt = NetworkStore.stationsById.get(firstS.station_id) || firstS;
                        pts.push([firstSt.lat, firstSt.lng]);
                    }
                    const gScale = NetworkStore.trackWidthScale || 1.0;
                    const gBase = line.code === "A" ? 9.5 : (line.line_subtype === "alimentadora" ? 6.2 : 7.4);
                    L.polyline(pts, {
                        color: line.color,
                        weight: gBase * gScale,
                        opacity: 0.94,
                        dashArray: line.network_type === "bus_articulado" ? "7, 6" : null
                    }).addTo(this.layerGroup);
                }
            }

            for (const st of NetworkStore.stations) {
                const marker = L.circleMarker([st.lat, st.lng], {
                    radius: st.is_transfer ? 6.2 : 4.2,
                    fillColor: st.is_premium_stop ? "#facc15" : "#ffffff",
                    color: "#0f172a",
                    weight: 2.2,
                    fillOpacity: 1
                }).bindTooltip(`${st.name} (${st.lines.join("/")})`);
                marker.on("click", () => ControlCenterUI.selectStation(st.id));
                marker.addTo(this.layerGroup);

                if (Array.isArray(st.terminal_lines) && st.terminal_lines.length > 0) {
                    st.terminal_lines.forEach((tCode, idx) => {
                        const tLine = NetworkStore.linesByCode.get(tCode);
                        if (!tLine || !SchematicMapEngine.isLineVisible(tLine)) return;
                        const fg = getBadgeTextColor(tLine.color, "#FFFFFF");
                        const wPx = tCode.length >= 2 ? 22 : 19;
                        const icon = L.divIcon({
                            className: "",
                            html: `<div class="geo-terminal-icon" style="width:${wPx}px;height:19px;background:${tLine.color};color:${fg};">${escapeHtml(tCode)}</div>`,
                            iconSize: [wPx, 19],
                            iconAnchor: [-7 - idx * (wPx + 2), 9]
                        });
                        const tm = L.marker([st.lat, st.lng], { icon }).bindTooltip(`Terminal ${tLine.name}: ${st.name}`);
                        tm.on("click", () => ControlCenterUI.selectStation(st.id));
                        tm.addTo(this.layerGroup);
                    });
                }
            }

            // 3. Marcadores de trenes en movimiento
            for (const train of TrainSimulationEngine.trains) {
                const m = L.circleMarker([train.lat, train.lng], {
                    radius: train.isPremium ? 6.5 : 5,
                    fillColor: train.color,
                    color: train.isPremium ? "#facc15" : "#ffffff",
                    weight: 2,
                    fillOpacity: 1
                }).bindTooltip(`${train.id} · ${train.lineName}`);
                m.on("click", () => ControlCenterUI.selectTrain(train.id));
                m.addTo(this.trainLayerGroup);
                TrainSimulationEngine.geoTrainMarkers.set(train.id, m);
            }

            setTimeout(() => this.map.invalidateSize(), 60);
        },

        syncTrainsGeo() {
            if (!this.map) return;
            for (const train of TrainSimulationEngine.trains) {
                const m = TrainSimulationEngine.geoTrainMarkers.get(train.id);
                if (m) {
                    m.setLatLng([train.lat, train.lng]);
                }
            }
        }
    };

    // =========================================================================
    // 5. PLANO TÉCNICO DE INGENIERÍA Y ARQUITECTURA (Corte Transversal SVG)
    // =========================================================================
    const BlueprintRenderer = {
        renderCrossSectionSvg(station) {
            const infra = station.infrastructure_type;
            const depth = station.depth_meters;
            const psdText = station.has_psd ? "PSD / APG Activas" : "Andén Abierto";
            const platCount = station.platform_count || 2;

            //Genera un plano técnico CAD/azulado distinto para Subterráneo, Túnel Profundo, Superficial y Viaducto Elevado
            if (infra === "tunel_profundo") {
                return `
                <svg viewBox="0 0 360 155" width="100%" height="155" aria-label="Plano de ingeniería túnel profundo">
                    <rect width="360" height="155" fill="#071120" rx="4"/>
                    <!-- Nivel de calle -->
                    <line x1="10" y1="22" x2="350" y2="22" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="4 3"/>
                    <text x="16" y="16" fill="#7dd3fc" font-size="9" font-family="monospace">NIVEL CALZADA (0,00 m) · LUMBRERA DE VENTILACIÓN</text>
                    <!-- Lumbreras verticales y escaleras de gran profundidad -->
                    <rect x="75" y="22" width="22" height="72" fill="none" stroke="#38bdf8" stroke-width="1.2"/>
                    <rect x="263" y="22" width="22" height="72" fill="none" stroke="#38bdf8" stroke-width="1.2"/>
                    <line x1="86" y1="22" x2="86" y2="94" stroke="#38bdf8" stroke-dasharray="2 3"/>
                    <line x1="274" y1="22" x2="274" y2="94" stroke="#38bdf8" stroke-dasharray="2 3"/>
                    <!-- Bóveda circular TBM de gran profundidad -->
                    <circle cx="180" cy="105" r="42" fill="#0c1e38" stroke="#8b5cf6" stroke-width="3"/>
                    <circle cx="180" cy="105" r="38" fill="none" stroke="#38bdf8" stroke-width="1" stroke-dasharray="5 3"/>
                    <!-- Andenes y vías dentro del escudo -->
                    <rect x="146" y="108" width="68" height="7" fill="#38bdf8" fill-opacity="0.35" stroke="#7dd3fc"/>
                    <rect x="150" y="96" width="22" height="12" fill="none" stroke="#facc15" stroke-width="1.4"/>
                    <rect x="188" y="96" width="22" height="12" fill="none" stroke="#facc15" stroke-width="1.4"/>
                    <!-- Cárcamo de bombeo N+2 bajo clave inferior -->
                    <rect x="168" y="132" width="24" height="10" fill="#0284c7" fill-opacity="0.4" stroke="#38bdf8"/>
                    <text x="180" y="80" fill="#e0f2fe" font-size="9" font-family="monospace" text-anchor="middle">COTA DE VÍA: ${depth} m · ${platCount} ANDENES (${psdText})</text>
                </svg>`;
            }

            if (infra === "elevado") {
                return `
                <svg viewBox="0 0 360 155" width="100%" height="155" aria-label="Plano de ingeniería viaducto elevado">
                    <rect width="360" height="155" fill="#071120" rx="4"/>
                    <!-- Cubierta aerodinámica del viaducto -->
                    <path d="M 55 34 Q 180 12 305 34" fill="none" stroke="#f59e0b" stroke-width="2.2"/>
                    <!-- Trabe cajón prefabricada -->
                    <polygon points="65,64 295,64 270,84 90,84" fill="#0c1e38" stroke="#f59e0b" stroke-width="2"/>
                    <!-- Vías y puertas PSD sobre el viaducto -->
                    <rect x="85" y="54" width="48" height="10" fill="#38bdf8" fill-opacity="0.3" stroke="#7dd3fc"/>
                    <rect x="227" y="54" width="48" height="10" fill="#38bdf8" fill-opacity="0.3" stroke="#7dd3fc"/>
                    <rect x="142" y="46" width="32" height="18" fill="none" stroke="#facc15" stroke-width="1.5"/>
                    <rect x="186" y="46" width="32" height="18" fill="none" stroke="#facc15" stroke-width="1.5"/>
                    <!-- Columna central sismorresistente y zapata -->
                    <rect x="162" y="84" width="36" height="50" fill="#0c1e38" stroke="#38bdf8" stroke-width="1.8"/>
                    <line x1="15" y1="134" x2="345" y2="134" stroke="#38bdf8" stroke-width="1.5"/>
                    <text x="180" y="147" fill="#7dd3fc" font-size="9" font-family="monospace" text-anchor="middle">GÁLIBO VIAL +${Math.abs(depth || 8.5)} m · DISIPADORES SÍSMICOS · ${psdText}</text>
                </svg>`;
            }

            if (infra === "superficial") {
                return `
                <svg viewBox="0 0 360 155" width="100%" height="155" aria-label="Plano de ingeniería tramo superficial">
                    <rect width="360" height="155" fill="#071120" rx="4"/>
                    <!-- Pasarela peatonal elevada de acceso universal -->
                    <rect x="70" y="24" width="220" height="12" fill="#0c1e38" stroke="#38bdf8" stroke-width="1.4"/>
                    <line x1="95" y1="36" x2="95" y2="105" stroke="#38bdf8" stroke-width="1.4"/>
                    <line x1="265" y1="36" x2="265" y2="105" stroke="#38bdf8" stroke-width="1.4"/>
                    <!-- Superficie de rodamiento a nivel 0.00 m -->
                    <line x1="15" y1="105" x2="345" y2="105" stroke="#22c55e" stroke-width="2"/>
                    <!-- Muros de confinamiento y plataformas -->
                    <rect x="75" y="92" width="44" height="13" fill="#22c55e" fill-opacity="0.3" stroke="#7dd3fc"/>
                    <rect x="241" y="92" width="44" height="13" fill="#22c55e" fill-opacity="0.3" stroke="#7dd3fc"/>
                    <rect x="132" y="82" width="40" height="23" fill="none" stroke="#facc15" stroke-width="1.5"/>
                    <rect x="188" y="82" width="40" height="23" fill="none" stroke="#facc15" stroke-width="1.5"/>
                    <text x="180" y="132" fill="#7dd3fc" font-size="9" font-family="monospace" text-anchor="middle">NIVEL DE CALZADA (0,00 m) · COLECTOR PLUVIAL LATERAL · ${platCount} ANDENES</text>
                </svg>`;
            }

            // Por defecto: Subterráneo (Cajón Cortar y Cubrir / Trinchera, incluyendo 6 andenes en Línea A)
            const isSixPlatforms = station.platform_type === "seis_andenes" || platCount === 6;
            return `
            <svg viewBox="0 0 360 155" width="100%" height="155" aria-label="Plano de ingeniería cajón subterráneo">
                <rect width="360" height="155" fill="#071120" rx="4"/>
                <line x1="12" y1="22" x2="348" y2="22" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="5 3"/>
                <text x="18" y="15" fill="#7dd3fc" font-size="9" font-family="monospace">NIVEL CALLE (0,00 m) · VESTÍBULO Y ACCESOS PMR</text>
                <!-- Cajón estructural cortar y cubrir -->
                <rect x="34" y="42" width="292" height="92" fill="#0c1e38" stroke="#38bdf8" stroke-width="2.2"/>
                <!-- Nivel Mezzanine -->
                <line x1="34" y1="72" x2="326" y2="72" stroke="#38bdf8" stroke-width="1" stroke-dasharray="4 3"/>
                ${isSixPlatforms ? `
                    <!-- 6 Andenes Línea A (2 Ordinario + 2 Premium + 2 Reserva) -->
                    <rect x="44" y="108" width="32" height="12" fill="#facc15" fill-opacity="0.35" stroke="#facc15"/>
                    <rect x="92" y="108" width="32" height="12" fill="#38bdf8" fill-opacity="0.35" stroke="#7dd3fc"/>
                    <rect x="140" y="108" width="32" height="12" fill="#facc15" fill-opacity="0.35" stroke="#facc15"/>
                    <rect x="188" y="108" width="32" height="12" fill="#38bdf8" fill-opacity="0.35" stroke="#7dd3fc"/>
                    <rect x="236" y="108" width="32" height="12" fill="#64748b" fill-opacity="0.35" stroke="#94a3b8"/>
                    <rect x="282" y="108" width="32" height="12" fill="#64748b" fill-opacity="0.35" stroke="#94a3b8"/>
                    <text x="180" y="96" fill="#facc15" font-size="8.5" font-family="monospace" text-anchor="middle">6 ANDENES LÍNEA A: 2 ORDINARIO (150s) + 2 PREMIUM (300s) + 2 RESERVA</text>
                ` : `
                    <rect x="52" y="106" width="66" height="14" fill="#38bdf8" fill-opacity="0.35" stroke="#7dd3fc"/>
                    <rect x="242" y="106" width="66" height="14" fill="#38bdf8" fill-opacity="0.35" stroke="#7dd3fc"/>
                    <rect x="130" y="92" width="44" height="26" fill="none" stroke="#facc15" stroke-width="1.6"/>
                    <rect x="186" y="92" width="44" height="26" fill="none" stroke="#facc15" stroke-width="1.6"/>
                `}
                <text x="180" y="147" fill="#7dd3fc" font-size="9" font-family="monospace" text-anchor="middle">CAJÓN SUBTERRÁNEO (${depth} m) · ${psdText} · HVAC + CÁRCAMO</text>
            </svg>`;
        }
    };

    // =========================================================================
    // 6. INTERFAZ DEL CENTRO DE CONTROL OPERATIVO (PCCO), INSPECTOR Y EDITOR
    // =========================================================================
    const ControlCenterUI = {
        init() {
            this.renderLegendTags();
            this.renderLinesDirectory();
            this.renderAlertsPanel();
            this.renderMetricsTab();
            this.populateEditorSelects();
            this.bindUIEvents();
            this.seedInitialTicker();
            ContextMenuManager.init();
        },

        renderLegendTags() {
            const row = document.getElementById("legendIconTagsRow");
            if (!row) return;
            row.innerHTML = `<span class="legend-subtitle" style="margin:0;">Tags Estación:</span>` +
                STATION_ICON_TAGS.map(t => `
                    <span class="legend-tag-pill">
                        ${renderInlineTagShieldSvg(t, 14)}
                        <span>${escapeHtml(t.label)}</span>
                    </span>
                `).join("");
        },

        renderTagSelectorButtons(activeTags, actionClass) {
            const set = new Set(Array.isArray(activeTags) ? activeTags : []);
            return STATION_ICON_TAGS.map(t => {
                const isOn = set.has(t.id);
                return `
                    <button type="button" class="tag-chip-btn ${isOn ? 'active' : ''} ${actionClass}"
                            data-tag-id="${t.id}" aria-pressed="${isOn}">
                        <span class="tag-chip-icon">${renderInlineTagShieldSvg(t, 18)}</span>
                        <span>${escapeHtml(t.label)}</span>
                    </button>
                `;
            }).join("");
        },

        renderTerminalLinesControlHtml(st, chipActionClass, addBtnClass, selectClass) {
            const activeSet = new Set(Array.isArray(st.terminal_lines) ? st.terminal_lines : []);
            const candidateCodes = [];
            for (const c of (st.lines || [])) {
                if (!candidateCodes.includes(c)) candidateCodes.push(c);
            }
            for (const c of activeSet) {
                if (!candidateCodes.includes(c)) candidateCodes.push(c);
            }

            const chipsHtml = candidateCodes.map(code => {
                const ln = NetworkStore.linesByCode.get(code);
                const bg = ln ? ln.color : "#475569";
                const fg = getBadgeTextColor(bg, "#FFFFFF");
                const isOn = activeSet.has(code);
                return `
                    <button type="button" class="terminal-line-chip ${isOn ? 'active' : ''} ${chipActionClass}"
                            data-line-code="${escapeHtml(code)}" aria-pressed="${isOn}"
                            title="${isOn ? 'Quitar como terminal de Línea ' + escapeHtml(code) : 'Marcar como terminal de Línea ' + escapeHtml(code)}">
                        <span class="terminal-num-dot" style="background:${bg}; color:${fg};">${escapeHtml(code)}</span>
                        <span>${isOn ? 'Terminal ✓' : 'Marcar Terminal'}</span>
                    </button>
                `;
            }).join("");

            const allLinesOpts = `<option value="">+ Asignar terminal de otra línea (1-22, A-G, S1-S5)...</option>` +
                NetworkStore.lines.map(l => {
                    const mark = activeSet.has(l.code) ? " [Activa]" : "";
                    return `<option value="${escapeHtml(l.code)}">${escapeHtml(l.name)}${mark}</option>`;
                }).join("");

            return `
                <div class="terminal-lines-editor" data-station-id="${st.id}">
                    <div class="terminal-badges-active-row">
                        ${chipsHtml || '<span style="font-size:11px;color:var(--text-muted);">Sin líneas asignadas como terminal.</span>'}
                    </div>
                    <div class="terminal-assign-other-row">
                        <select class="form-control ${selectClass}">${allLinesOpts}</select>
                        <button type="button" class="btn-secondary btn-xs ${addBtnClass}">Asignar</button>
                    </div>
                </div>
            `;
        },

        switchRightTab(tabName) {
            document.querySelectorAll(".rtab-btn").forEach(btn => {
                const active = btn.dataset.rtab === tabName;
                btn.classList.toggle("active", active);
                btn.setAttribute("aria-selected", String(active));
            });
            const mapPanels = {
                pcco: "panelPcco",
                inspector: "panelInspector",
                metrics: "panelMetrics",
                editor: "panelEditor"
            };
            Object.entries(mapPanels).forEach(([k, id]) => {
                const el = document.getElementById(id);
                if (el) el.classList.toggle("hidden", k !== tabName);
            });
        },

        renderLinesDirectory() {
            const container = document.getElementById("linesDirectoryList");
            if (!container) return;

            const filtered = NetworkStore.lines.filter(ln => {
                if (NetworkStore.networkFilter !== "all" && ln.network_type !== NetworkStore.networkFilter) {
                    return false;
                }
                return true;
            });

            const countLbl = document.getElementById("linesCountLabel");
            if (countLbl) countLbl.textContent = `DIRECTORIO DE LÍNEAS (${filtered.length})`;

            let html = "";
            for (const ln of filtered) {
                const isSelected = NetworkStore.isolatedLineCode === ln.code;
                const isDimmed = NetworkStore.isolatedLineCode && !isSelected;
                const isBrt = ln.network_type === "bus_articulado";
                const freqText = ln.premium_frequency_seconds
                    ? `Ord ${ln.frequency_seconds}s · Prem ${ln.premium_frequency_seconds}s`
                    : `Cada ${ln.frequency_seconds}s`;

                html += `
                    <div class="line-card ${isSelected ? 'selected' : ''} ${isDimmed ? 'dimmed' : ''}"
                         data-line-code="${ln.code}" role="listitem" tabindex="0">
                        <span class="line-badge ${isBrt ? 'brt-badge' : ''}"
                              style="background-color:${ln.color}; color:${ln.text_color};">
                            ${escapeHtml(ln.code)}
                        </span>
                        <div class="line-card-body">
                            <div class="line-card-top">
                                <span class="line-card-title">${escapeHtml(ln.route_title)}</span>
                                <span class="status-dot ${ln.status}" title="${escapeHtml(ln.status_label)}"></span>
                            </div>
                            <div class="line-card-meta tabular">
                                <span>${ln.operational_stations_count}/${ln.declared_stations_count} est.</span>
                                <span>·</span>
                                <span>${ln.length_km} km</span>
                                <span>·</span>
                                <span>${freqText}</span>
                            </div>
                        </div>
                    </div>
                `;
            }
            container.innerHTML = html;
        },

        renderAlertsPanel() {
            const listEl = document.getElementById("pccoAlertsList");
            if (!listEl) return;

            const activeCount = NetworkStore.alerts.filter(a => a.is_active).length;
            const kpiAlerts = document.getElementById("kpiActiveAlerts");
            if (kpiAlerts) kpiAlerts.textContent = String(activeCount);

            const healthTitle = document.getElementById("networkHealthTitle");
            const healthBadge = document.getElementById("networkHealthBadge");
            if (healthTitle && healthBadge) {
                if (activeCount > 5) {
                    healthTitle.textContent = "Regulación Activa Multi-Línea";
                    healthBadge.textContent = "94,2% DISP.";
                    healthBadge.className = "health-badge caution";
                } else {
                    healthTitle.textContent = "Operación Nominal Controlada";
                    healthBadge.textContent = "98,4% DISP.";
                    healthBadge.className = "health-badge nominal";
                }
            }

            let html = "";
            for (const a of NetworkStore.alerts) {
                const badgeHtml = a.line_code
                    ? `<span class="line-badge-sm" style="background:${a.line_color}; color:#fff;">${escapeHtml(a.line_code)}</span>`
                    : "";
                html += `
                    <article class="alert-card severity-${a.severity}">
                        <div class="alert-card-head">
                            <div style="display:flex; align-items:center; gap:6px;">
                                ${badgeHtml}
                                <h4 class="alert-card-title">${escapeHtml(a.title)}</h4>
                            </div>
                            <button type="button" class="btn-secondary btn-xs js-toggle-alert" data-alert-id="${a.id}">
                                ${a.is_active ? "Resolver" : "Reactivar"}
                            </button>
                        </div>
                        <p class="alert-card-desc">${escapeHtml(a.description)}</p>
                        <div class="alert-card-foot tabular">
                            <span>${escapeHtml(a.category_label)} · Vel: ${Math.round(a.speed_factor * 100)}%</span>
                            <span>${a.created_at}</span>
                        </div>
                    </article>
                `;
            }
            listEl.innerHTML = html;
        },

        renderMetricsTab() {
            const container = document.getElementById("lineMetricsContainer");
            if (!container) return;

            // Calcular ocupación media
            const avgOcc = Math.round(
                NetworkStore.lines.reduce((acc, l) => acc + l.current_occupancy_pct, 0) / Math.max(1, NetworkStore.lines.length)
            );
            const occEl = document.getElementById("kpiAvgOccupancy");
            if (occEl) occEl.textContent = `${avgOcc}%`;

            let html = "";
            for (const ln of NetworkStore.lines) {
                const occColor = ln.current_occupancy_pct > 85
                    ? "var(--status-crit)"
                    : (ln.current_occupancy_pct > 70 ? "var(--status-warn)" : "var(--status-ok)");
                html += `
                    <div class="metric-line-row">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div style="display:flex; align-items:center; gap:7px;">
                                <span class="line-badge-sm" style="background:${ln.color}; color:${ln.text_color};">${escapeHtml(ln.code)}</span>
                                <strong>${escapeHtml(ln.name)}</strong>
                            </div>
                            <button type="button" class="text-link-btn js-jump-edit-line" data-line-code="${ln.code}">Editar</button>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--text-secondary);" class="tabular">
                            <span>Ocupación: <strong>${ln.current_occupancy_pct}%</strong> (${ln.annual_ridership_millions}M/año)</span>
                            <span>Frec: ${ln.frequency_seconds}s · Vel: ${ln.max_speed_kmh} km/h</span>
                        </div>
                        <div class="occupancy-bar-track">
                            <div class="occupancy-bar-fill" style="width:${ln.current_occupancy_pct}%; background:${occColor};"></div>
                        </div>
                        <div style="font-size:10.5px; color:var(--text-muted);" class="tabular">
                            Criterio Geométrico: R mín ${ln.min_curve_radius_m} m · Sobreelevación ${ln.superelevation_mm} mm · Tangente mín ${ln.min_tangent_between_curves_m} m
                        </div>
                    </div>
                `;
            }
            container.innerHTML = html;
        },

        selectStation(stationId) {
            const st = NetworkStore.stationsById.get(stationId);
            if (!st) return;

            const prevSelectedId = NetworkStore.selectedStationId;
            NetworkStore.selectedStationId = stationId;
            NetworkStore.selectedTrainId = null;
            if (SchematicMapEngine.updateStationSelectionUI) {
                SchematicMapEngine.updateStationSelectionUI(prevSelectedId, stationId);
            } else {
                SchematicMapEngine.renderTracksAndStations();
            }
            this.updateCorrespondenceSelectedStation(st);

            // Sincronizar selección en formularios de edición si el panel editor está abierto
            const corrStationSel = document.getElementById("corrStationSelect");
            if (corrStationSel && corrStationSel.value !== String(stationId)) {
                corrStationSel.value = String(stationId);
                this.updateTargetLinesForStation(stationId);
            }
            const edStationSel = document.getElementById("editStationSelect");
            if (edStationSel && edStationSel.value !== String(stationId)) {
                edStationSel.value = String(stationId);
                this.loadStationIntoEditor(stationId);
            }

            // Sincronizar la línea asociada a la estación en todos los apartados del editor
            const stationLines = Array.isArray(st.lines) ? st.lines : [];
            if (stationLines.length > 0) {
                const targetLineCode = (NetworkStore.isolatedLineCode && stationLines.includes(NetworkStore.isolatedLineCode))
                    ? NetworkStore.isolatedLineCode
                    : stationLines[0];

                const edLineSel = document.getElementById("editLineSelect");
                if (edLineSel && edLineSel.value !== String(targetLineCode)) {
                    edLineSel.value = String(targetLineCode);
                    this.loadLineIntoEditor(targetLineCode);
                }
                const newSegLineSel = document.getElementById("newSegmentLineSelect");
                if (newSegLineSel && newSegLineSel.value !== String(targetLineCode)) {
                    newSegLineSel.value = String(targetLineCode);
                }
                const modalCorrLineSel = document.getElementById("modalCorrLineSelect");
                if (modalCorrLineSel) {
                    modalCorrLineSel.value = String(targetLineCode);
                }
            }

            const panelEditor = document.getElementById("panelEditor");
            const isEditorActive = panelEditor && !panelEditor.classList.contains("hidden");
            if (!isEditorActive) {
                this.switchRightTab("inspector");
            }

            document.getElementById("inspectorEmptyState")?.classList.add("hidden");
            document.getElementById("trainInspectorContent")?.classList.add("hidden");
            const contentEl = document.getElementById("stationInspectorContent");
            if (!contentEl) return;
            contentEl.classList.remove("hidden");

            const servedCodes = Array.isArray(st.lines) ? st.lines : [];
            const badgesHtml = servedCodes.map(code => {
                const ln = NetworkStore.linesByCode.get(code);
                const bg = ln ? ln.color : "#475569";
                const fg = ln ? ln.text_color : "#ffffff";
                return `<button type="button" class="line-badge-sm js-isolate-line" data-line-code="${escapeHtml(code)}" style="background:${bg}; color:${fg}; cursor:pointer;">${escapeHtml(code)}</button>`;
            }).join("");

            const linesListHtml = servedCodes.length > 0
                ? servedCodes.map(code => {
                    const ln = NetworkStore.linesByCode.get(code);
                    const bg = ln ? ln.color : "#475569";
                    const fg = ln ? ln.text_color : "#ffffff";
                    return `
                        <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 8px; background:var(--bg-subtle); border:1px solid var(--border-hairline); border-radius:4px; margin-bottom:4px;">
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span class="line-badge-sm" style="background:${bg}; color:${fg};">${escapeHtml(code)}</span>
                                <span style="font-size:11px; font-weight:600;">${escapeHtml(ln ? ln.name : `Línea ${code}`)}</span>
                            </div>
                            <button type="button" class="btn-secondary btn-xs js-disconnect-line-btn" data-station-id="${st.id}" data-line-code="${escapeHtml(code)}" style="color:#ef4444; padding:2px 7px; font-size:11px;" title="Quitar correspondencia de esta línea">
                                ✕ Quitar
                            </button>
                        </div>
                    `;
                }).join("")
                : `<p class="form-hint" style="margin:4px 0 8px;">Estación independiente (huérfana) sin líneas asignadas.</p>`;

            const blueprintSvg = BlueprintRenderer.renderCrossSectionSvg(st);
            const tagButtonsHtml = this.renderTagSelectorButtons(st.icon_tags, "js-inspector-toggle-tag");
            const terminalControlHtml = this.renderTerminalLinesControlHtml(
                st,
                "js-inspector-toggle-terminal",
                "js-inspector-add-terminal",
                "js-inspector-terminal-select"
            );

            contentEl.innerHTML = `
                <div class="inspector-card">
                    <div class="inspector-header">
                        <div>
                            <span class="section-eyebrow">ESTACIÓN · CÓDIGO ${escapeHtml(st.code)}</span>
                            <h3 class="inspector-title">${escapeHtml(st.name)}</h3>
                            <div class="served-lines-row">${badgesHtml}</div>
                        </div>
                        <div style="display:flex; flex-direction:column; gap:6px; align-items:flex-end;">
                            <button type="button" class="btn-secondary btn-xs js-open-station-editor" data-station-id="${st.id}">
                                Editar Estación
                            </button>
                            ${servedCodes.length >= 10 ? `
                                <span style="font-size:10px; font-weight:700; color:#b91c1c; background:#fee2e2; padding:3px 6px; border-radius:4px;">
                                    Máx. 10 correspondencias
                                </span>
                            ` : `
                                <button type="button" class="btn-secondary btn-xs js-quick-add-corr" data-station-id="${st.id}" style="color:var(--accent-blue); font-weight:600;">
                                    ⇄ Añadir a Línea (${servedCodes.length}/10)
                                </button>
                            `}
                            <button type="button" class="btn-secondary btn-xs js-delete-station-btn" data-station-id="${st.id}" style="color:#ef4444; font-weight:600;">
                                🗑 Eliminar
                            </button>
                        </div>
                    </div>

                    <div>
                        <span class="section-eyebrow">LÍNEAS ASIGNADAS Y CORRESPONDENCIAS (${servedCodes.length}/10)</span>
                        ${linesListHtml}
                    </div>

                    <div>
                        <span class="section-eyebrow">TERMINAL DE LÍNEA (ICONO CON NÚMERO AL LADO)</span>
                        ${terminalControlHtml}
                    </div>

                    <div>
                        <span class="section-eyebrow">TAGS CON ICONOS A UN COSTADO DE LA ESTACIÓN</span>
                        <div class="tag-toggle-grid" data-station-id="${st.id}">
                            ${tagButtonsHtml}
                        </div>
                    </div>

                    <div>
                        <span class="section-eyebrow">PRÓXIMOS TRENES Y TIEMPOS ESTIMADOS</span>
                        <div class="arrivals-board tabular" id="liveStationArrivalsBoard" style="margin-top:5px;">
                            <!-- Calculado en tiempo real -->
                        </div>
                    </div>

                    <div class="blueprint-box">
                        <div class="blueprint-title-row">
                            <span>PLANO DE INGENIERÍA Y ARQUITECTURA</span>
                            <span>COTA: ${st.depth_meters} m</span>
                        </div>
                        ${blueprintSvg}
                    </div>

                    <div class="spec-grid">
                        <div class="spec-item">
                            <span>Tipo de Tramo</span>
                            <strong>${escapeHtml(INFRA_NAMES[st.infrastructure_type] || st.infrastructure_label)}</strong>
                        </div>
                        <div class="spec-item">
                            <span>Estado Operativo</span>
                            <strong>${escapeHtml(STATUS_NAMES[st.operational_status] || st.status_label)}</strong>
                        </div>
                        <div class="spec-item">
                            <span>Andenes y Puertas</span>
                            <strong>${escapeHtml(st.platform_label)} · ${st.has_psd ? "Con PSD/APG" : "Sin PSD"}</strong>
                        </div>
                        <div class="spec-item">
                            <span>Salidas Emergencia</span>
                            <strong>${st.emergency_exits} salidas presurizadas</strong>
                        </div>
                    </div>

                    <div class="spec-item">
                        <span>Ventilación y Control Climático</span>
                        <strong>${escapeHtml(st.ventilation_system)}</strong>
                    </div>
                    <div class="spec-item">
                        <span>Drenaje Pluvial y Accesibilidad Universal</span>
                        <strong>${escapeHtml(st.drainage_and_accessibility)}</strong>
                    </div>
                </div>
            `;

            this.updateStationArrivalsLive(stationId);
            animateInspectorCard(contentEl);
        },

        updateStationArrivalsLive(stationId) {
            const board = document.getElementById("liveStationArrivalsBoard");
            const st = NetworkStore.stationsById.get(stationId);
            if (!board || !st) return;

            if (st.operational_status === "closed_permanent") {
                board.innerHTML = `<div style="color:#f87171; padding:4px 0;">Estación clausurada permanentemente por conflicto territorial (sin servicio comercial).</div>`;
                return;
            }
            if (st.operational_status === "construction") {
                board.innerHTML = `<div style="color:#38bdf8; padding:4px 0;">Estación en obra civil y equipamiento electromecánico.</div>`;
                return;
            }

            // Buscar los trenes más cercanos en las líneas que sirven esta estación
            const upcoming = [];
            const servedUpcoming = Array.isArray(st.lines) ? st.lines : [];
            for (const lineCode of servedUpcoming) {
                const ln = NetworkStore.linesByCode.get(lineCode);
                if (!ln) continue;

                const lineTrains = TrainSimulationEngine.trains.filter(t => t.lineCode === lineCode);
                const firstStopName = ln.stops[0]?.station_name || "Terminal A";
                const lastStopName = ln.stops[ln.stops.length - 1]?.station_name || "Terminal B";

                // Calcular ETA realista basado en distancia euclidiana y frecuencia de línea
                for (const tr of lineTrains) {
                    if (tr.isPremium && !st.is_premium_stop) continue; // Los Premium no paran en estaciones ordinarias
                    const distPx = Math.hypot(tr.x - st.x, tr.y - st.y);
                    const etaSec = Math.max(8, Math.round((distPx / Math.max(25, tr.currentSpeedKmh || 45)) * 18));
                    const dest = tr.direction === 1 ? lastStopName : firstStopName;
                    upcoming.push({
                        lineCode: ln.code,
                        color: ln.color,
                        textColor: ln.text_color,
                        trainId: tr.id,
                        dest: ln.is_circular ? (tr.direction === 1 ? "Circuito Horario" : "Circuito Antihorario") : `Dir. ${dest}`,
                        isPremium: tr.isPremium,
                        etaSec
                    });
                }
            }

            upcoming.sort((a, b) => a.etaSec - b.etaSec);
            const topArrivals = upcoming.slice(0, 5);

            if (topArrivals.length === 0) {
                board.innerHTML = `<div>Programando despacho desde terminal...</div>`;
                return;
            }

            board.innerHTML = topArrivals.map(arr => {
                const mins = Math.floor(arr.etaSec / 60);
                const secs = arr.etaSec % 60;
                const timeStr = mins > 0 ? `${mins} min ${secs} s` : `${secs} s (En aproximación)`;
                return `
                    <div class="arrival-row">
                        <div class="arrival-dest">
                            <span class="line-badge-sm" style="background:${arr.color}; color:${arr.textColor};">${escapeHtml(arr.lineCode)}</span>
                            <span>${escapeHtml(arr.dest)}</span>
                            <span class="service-tag ${arr.isPremium ? 'premium' : 'ordinario'}">${arr.isPremium ? 'PREMIUM' : 'ORD'}</span>
                        </div>
                        <span class="arrival-eta">${timeStr}</span>
                    </div>
                `;
            }).join("");
        },

        selectTrain(trainId) {
            const tr = TrainSimulationEngine.trainsById.get(trainId);
            if (!tr) return;

            const prevStationId = NetworkStore.selectedStationId;
            NetworkStore.selectedTrainId = trainId;
            NetworkStore.selectedStationId = null;
            if (prevStationId && SchematicMapEngine.updateStationSelectionUI) {
                SchematicMapEngine.updateStationSelectionUI(prevStationId, null);
            }
            this.switchRightTab("inspector");

            document.getElementById("inspectorEmptyState")?.classList.add("hidden");
            document.getElementById("stationInspectorContent")?.classList.add("hidden");
            const contentEl = document.getElementById("trainInspectorContent");
            if (contentEl) {
                contentEl.classList.remove("hidden");
                this.renderTrainInspector(trainId);
                animateInspectorCard(contentEl);
            }
        },

        renderTrainInspector(trainId) {
            const tr = TrainSimulationEngine.trainsById.get(trainId);
            const contentEl = document.getElementById("trainInspectorContent");
            if (!tr || !contentEl) return;

            const ln = NetworkStore.linesByCode.get(tr.lineCode);
            const currStop = tr.routeStops[tr.currentStopIndex];
            const nextIdx = TrainSimulationEngine.getNextStopIndex(tr);
            const nextStop = tr.routeStops[nextIdx];
            const terminalStop = tr.direction === 1
                ? tr.routeStops[tr.routeStops.length - 1]
                : tr.routeStops[0];

            const etaNextSec = Math.max(2, Math.round((1 - tr.segmentProgress) * 28));
            const chainageKm = currStop && nextStop
                ? (currStop.chainage_km + (nextStop.chainage_km - currStop.chainage_km) * tr.segmentProgress).toFixed(3)
                : "0.000";

            contentEl.innerHTML = `
                <div class="inspector-card">
                    <div class="inspector-header">
                        <div>
                            <span class="section-eyebrow">${tr.networkType === 'bus_articulado' ? 'AUTOBÚS BIARTICULADO EN TIEMPO REAL' : 'CONVOY DE METRO EN TIEMPO REAL'}</span>
                            <h3 class="inspector-title">Unidad ${escapeHtml(tr.id)}</h3>
                            <div style="display:flex; align-items:center; gap:6px; margin-top:4px;">
                                <span class="line-badge-sm" style="background:${tr.color}; color:${tr.textColor};">${escapeHtml(tr.lineCode)}</span>
                                <strong>${escapeHtml(tr.lineName)}</strong>
                            </div>
                        </div>
                        <button type="button" class="btn-secondary btn-xs" id="btnCenterOnTrain" data-train-id="${escapeHtml(tr.id)}">
                            Centrar Mapa
                        </button>
                    </div>

                    <div class="spec-grid tabular">
                        <div class="spec-item">
                            <span>Dirección / Sentido</span>
                            <strong>${tr.isCircular ? (tr.direction === 1 ? 'Circuito Horario' : 'Circuito Antihorario') : 'Hacia ' + escapeHtml(terminalStop?.station_name || '')}</strong>
                        </div>
                        <div class="spec-item">
                            <span>Servicio y Frecuencia</span>
                            <strong>${escapeHtml(tr.serviceType)} (${ln?.frequency_seconds || 180} s)</strong>
                        </div>
                        <div class="spec-item">
                            <span>Próxima Parada</span>
                            <strong>${escapeHtml(nextStop?.station_name || '')} (en ${etaNextSec} s)</strong>
                        </div>
                        <div class="spec-item">
                            <span>Velocidad y Cadenamiento</span>
                            <strong>${tr.currentSpeedKmh} km/h · PK ${chainageKm} km</strong>
                        </div>
                        <div class="spec-item">
                            <span>Estado de Marcha</span>
                            <strong>${escapeHtml(tr.status)}</strong>
                        </div>
                        <div class="spec-item">
                            <span>Ocupación a Bordo</span>
                            <strong>${tr.occupancyPct}% (${escapeHtml(ln?.rolling_stock || '')})</strong>
                        </div>
                    </div>

                    <div class="spec-item tabular">
                        <span>Geometría del Tramo Actual</span>
                        <strong>Radio R = ${currStop?.curve_radius_m || 1800} m · Sobreelevación = ${currStop?.superelevation_deg || 0}° · Tangente = ${currStop?.tangent_length_m || 450} m</strong>
                    </div>
                </div>
            `;

            document.getElementById("btnCenterOnTrain")?.addEventListener("click", () => {
                SchematicMapEngine.flyToBox(tr.x - 900, tr.y - 500, 1800, 1000);
            });
        },

        populateEditorSelects() {
            const lineSel = document.getElementById("editLineSelect");
            const alertLineSel = document.getElementById("newAlertLine");
            if (lineSel && alertLineSel) {
                const opts = NetworkStore.lines.map(
                    l => `<option value="${escapeHtml(l.code)}">${escapeHtml(l.name)}: ${escapeHtml(l.route_title)}</option>`
                ).join("");
                lineSel.innerHTML = opts;
                alertLineSel.innerHTML = opts;
                this.loadLineIntoEditor(NetworkStore.lines[0]?.code);
            }

            const stSel = document.getElementById("editStationSelect");
            const addRouteStSel = document.getElementById("addRouteStationSelect");
            const stOptionsHtml = NetworkStore.getSortedStations()
                .map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
                .join("");
            if (addRouteStSel) {
                addRouteStSel.innerHTML = stOptionsHtml;
            }
            if (stSel) {
                stSel.innerHTML = stOptionsHtml;
                if (NetworkStore.stations[0]) {
                    this.loadStationIntoEditor(NetworkStore.stations[0].id);
                }
            }

            if (lineSel && NetworkStore.lines[0]) {
                this.loadLineIntoEditor(NetworkStore.lines[0].code);
            }

            const citySel = document.getElementById("editCitySelect");
            if (citySel) {
                citySel.innerHTML = NetworkStore.cityOutlines.map(
                    c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`
                ).join("");
                if (NetworkStore.cityOutlines[0]) {
                    this.loadCityIntoEditor(NetworkStore.cityOutlines[0].id);
                }
            }
        },

        loadLineIntoEditor(lineCode) {
            const ln = NetworkStore.linesByCode.get(lineCode);
            if (!ln) return;
            const sel = document.getElementById("editLineSelect");
            if (sel) sel.value = ln.code;
            const newSegLineSel = document.getElementById("newSegmentLineSelect");
            if (newSegLineSel && newSegLineSel.value !== String(ln.code)) {
                newSegLineSel.value = String(ln.code);
            }
            const modalCorrLineSel = document.getElementById("modalCorrLineSelect");
            if (modalCorrLineSel) {
                modalCorrLineSel.value = String(ln.code);
            }
            document.getElementById("editLineName").value = ln.name;
            document.getElementById("editLineColor").value = ln.color;
            document.getElementById("editLineColorPicker").value = ln.color;
            document.getElementById("editLineRoute").value = ln.route_title;
            document.getElementById("editLineNetworkType").value = ln.network_type;
            document.getElementById("editLineStatus").value = ln.status;
            document.getElementById("editLineFreq").value = ln.frequency_seconds;
            document.getElementById("editLinePremFreq").value = ln.premium_frequency_seconds || "";
            document.getElementById("editLineSpeed").value = ln.max_speed_kmh;
            document.getElementById("editLineFirstTrain").value = ln.first_train_time;
            document.getElementById("editLineLastTrain").value = ln.last_train_time;
            document.getElementById("editLineOccupancy").value = ln.current_occupancy_pct;
            document.getElementById("editLineLength").value = ln.length_km;
            document.getElementById("editLineRadius").value = ln.min_curve_radius_m;
            document.getElementById("editLineNote").value = ln.status_note || "";

            NetworkStore.draftRouteStops = ln.stops.map(s => {
                const stObj = NetworkStore.stationsById.get(s.station_id);
                const isTerm = Array.isArray(stObj?.terminal_lines) && stObj.terminal_lines.includes(ln.code);
                return {
                    id: s.id,
                    station_id: s.station_id,
                    station_name: s.station_name,
                    branch: s.branch || "main",
                    segment_infrastructure: s.segment_infrastructure,
                    segment_status: s.segment_status,
                    depth_meters: s.depth_meters,
                    waypoints: Array.isArray(s.waypoints) ? s.waypoints.map(p => [...p]) : [],
                    is_terminal_for_line: isTerm
                };
            });
            this.renderLineRouteEditor();
        },

        renderLineRouteEditor() {
            const listEl = document.getElementById("lineRouteStopsList");
            const badgeEl = document.getElementById("routeStopsCountBadge");
            const lineCode = document.getElementById("editLineSelect")?.value || "";
            const ln = NetworkStore.linesByCode.get(lineCode);
            const stops = NetworkStore.draftRouteStops || [];
            if (badgeEl) badgeEl.textContent = `${stops.length} paradas`;
            if (!listEl) return;

            listEl.innerHTML = stops.map((s, idx) => {
                const st = NetworkStore.stationsById.get(s.station_id);
                const name = st ? st.name : (s.station_name || `Estación #${s.station_id}`);
                const branchTag = s.branch && s.branch !== "main" ? ` [${escapeHtml(s.branch)}]` : "";
                const termStyle = s.is_terminal_for_line && ln
                    ? `style="background:${ln.color};color:${getBadgeTextColor(ln.color)};border-color:${ln.color};"`
                    : "";
                return `
                    <div class="route-stop-row" data-stop-idx="${idx}">
                        <span class="tabular" style="color:var(--text-muted); width:22px;">${idx + 1}.</span>
                        <span class="route-stop-name" title="${escapeHtml(name)}">${escapeHtml(name)}${branchTag}</span>
                        <div class="route-stop-actions">
                            <button type="button" class="route-mini-btn term-btn ${s.is_terminal_for_line ? 'active' : ''} js-route-toggle-terminal"
                                    data-idx="${idx}" ${termStyle}
                                    title="Marcar / quitar esta estación como Terminal de ${escapeHtml(ln?.name || 'la línea')} (muestra icono ${escapeHtml(lineCode)})">${escapeHtml(lineCode || "T")}</button>
                            <button type="button" class="route-mini-btn js-route-straighten-seg" data-idx="${idx}" title="Enderezar tramo siguiente a 90° o 180°" ${idx === stops.length - 1 ? "disabled" : ""}>⚡</button>
                            <button type="button" class="route-mini-btn js-route-move-up" data-idx="${idx}" title="Subir parada" ${idx === 0 ? "disabled" : ""}>▲</button>
                            <button type="button" class="route-mini-btn js-route-move-down" data-idx="${idx}" title="Bajar parada" ${idx === stops.length - 1 ? "disabled" : ""}>▼</button>
                            <button type="button" class="route-mini-btn danger js-route-remove" data-idx="${idx}" title="Quitar parada del trayecto">✕</button>
                        </div>
                    </div>
                `;
            }).join("");
        },

        loadStationIntoEditor(stationId) {
            const st = NetworkStore.stationsById.get(Number(stationId));
            if (!st) return;
            const sel = document.getElementById("editStationSelect");
            if (sel) sel.value = String(st.id);
            document.getElementById("editStationName").value = st.name;
            document.getElementById("editStationInfra").value = st.infrastructure_type;
            document.getElementById("editStationStatus").value = st.operational_status;
            document.getElementById("editStationX").value = st.x;
            document.getElementById("editStationY").value = st.y;
            document.getElementById("editStationDepth").value = st.depth_meters;
            document.getElementById("editStationPlatform").value = st.platform_type;
            document.getElementById("editStationExits").value = st.emergency_exits;
            document.getElementById("editStationPsd").checked = Boolean(st.has_psd);
            document.getElementById("editStationPremium").checked = Boolean(st.is_premium_stop);
            const termBox = document.getElementById("editStationTerminalsGroup");
            if (termBox) {
                termBox.innerHTML = this.renderTerminalLinesControlHtml(
                    st,
                    "js-editor-toggle-terminal",
                    "js-editor-add-terminal",
                    "js-editor-terminal-select"
                );
            }
            const tagsBox = document.getElementById("editStationTagsGroup");
            if (tagsBox) {
                tagsBox.innerHTML = this.renderTagSelectorButtons(st.icon_tags, "js-editor-toggle-tag");
            }
        },

        loadCityIntoEditor(outlineId) {
            const zone = NetworkStore.cityOutlines.find(z => z.id === Number(outlineId));
            if (!zone) return;
            const sel = document.getElementById("editCitySelect");
            if (sel) sel.value = String(zone.id);
            document.getElementById("editCityName").value = zone.name;
            document.getElementById("editCityColor").value = zone.color;
            document.getElementById("editCityOpacity").value = zone.opacity;
            document.getElementById("editCityElevation").value = zone.elevation_m;
        },

        isDisconnectingCorr: false,

        async disconnectStationFromLine(stationId, lineCode) {
            if (this.isDisconnectingCorr) return;
            const stId = Number(stationId);
            const st = NetworkStore.stationsById.get(stId);
            const stName = st ? st.name : `Estación ${stId}`;
            if (!confirm(`¿Desconectar la estación "${stName}" de la Línea ${lineCode}?`)) {
                return;
            }

            this.isDisconnectingCorr = true;
            try {
                const res = await ApiClient.post("/api/correspondences/", {
                    action: "remove",
                    station_id: stId,
                    target_line_code: lineCode
                });

                if (!res.ok) {
                    showToast(res.error || `No se pudo desconectar de la Línea ${lineCode}`);
                    return;
                }

                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ "${stName}" desconectada de la Línea ${lineCode}${msgMode}`);
                try {
                    await refreshNetworkDataAndRender(true);
                    if (NetworkStore.selectedStationId === stId) {
                        this.selectStation(stId);
                    }
                    this.populateCorrespondenceSubtab();
                } catch (uiErr) {
                    console.error("Error al actualizar UI tras desconectar correspondencia:", uiErr);
                }
            } finally {
                this.isDisconnectingCorr = false;
            }
        },

        async deleteStation(stationId, stationName = "") {
            const stId = Number(stationId);
            const st = NetworkStore.stationsById.get(stId);
            const name = stationName || (st ? st.name : `Estación ${stId}`);
            if (!confirm(`¿Eliminar definitivamente la estación "${name}"?
Se desvinculará de todas las líneas y tramos conectados.`)) {
                return;
            }
            try {
                const res = await ApiClient.post(`/api/stations/${stId}/delete/`, {});
                if (!res.ok) {
                    showToast(res.error || "No se pudo eliminar la estación");
                    return;
                }
                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ Estación "${name}" eliminada${msgMode}`);
                if (NetworkStore.selectedStationId === stId) {
                    NetworkStore.selectedStationId = null;
                    document.getElementById("stationInspectorContent")?.classList.add("hidden");
                    document.getElementById("inspectorEmptyState")?.classList.remove("hidden");
                }
                await refreshNetworkDataAndRender(true);
            } catch (err) {
                console.error("Error al eliminar estación:", err);
                showToast("Error al eliminar la estación");
            }
        },

        async straightenLineTracks(lineCode) {
            try {
                const res = await ApiClient.post(`/api/lines/${lineCode}/route/`, {
                    clear_all_waypoints: true,
                    straighten_tracks: true,
                    straighten_orthogonal: true
                });
                if (!res.ok) {
                    showToast(res.error || "No se pudo enderezar los trazos");
                    return;
                }
                showToast(`✓ Trazos de Línea ${lineCode} enderezados a 90° / 180°`);
                await refreshNetworkDataAndRender(true);
            } catch (err) {
                showToast("Error de conexión al enderezar trazos");
            }
        },

        seedInitialTicker() {
            const initialMsgs = [
                ["A", "#00606c", "Circuito Periférico (132,8 km): Sincronizados 16 trenes Ordinarios (150 s) y 8 Expresos Premium (300 s)"],
                ["C", "#ffe712", "Enclavamiento Tlacotepec: Inversión de marcha activa por clausura del tramo Siervo de la Nación - Halcones"],
                ["1", "#fc0203", "Nodo Santa Mónica (1/4/7/15/18): Puertas de andén PSD operando al 100% en triple andén"],
                ["S1", "#ff2301", "Red de Autobuses Articulados: Onda verde prioritaria activa en bifurcación Múzquiz R1/R2"]
            ];
            for (const [code, color, text] of initialMsgs) {
                this.appendTickerEvent(code, color, text);
            }
        },

        appendTickerEvent(lineCode, color, message) {
            const feed = document.getElementById("liveEventTicker");
            if (!feed) return;
            const timeStr = formatSecondsToHHMMSS(NetworkStore.operationalTimeSec);
            const row = document.createElement("div");
            row.className = "event-row";
            row.innerHTML = `
                <span class="event-time">${timeStr}</span>
                <span class="line-badge-sm" style="background:${color}; color:#fff;">${escapeHtml(lineCode)}</span>
                <span>${escapeHtml(message)}</span>
            `;
            feed.prepend(row);
            while (feed.children.length > 25) {
                feed.removeChild(feed.lastChild);
            }
        },

        bindUIEvents() {
            // Pestañas del panel derecho
            document.querySelectorAll(".rtab-btn").forEach(btn => {
                btn.addEventListener("click", () => this.switchRightTab(btn.dataset.rtab));
            });

            // Sub-pestañas del editor de datos
            document.querySelectorAll(".ed-subtab").forEach(btn => {
                btn.addEventListener("click", () => {
                    document.querySelectorAll(".ed-subtab").forEach(b => b.classList.remove("active"));
                    btn.classList.add("active");
                    const tab = btn.dataset.edtab;
                    document.getElementById("formEditLine")?.classList.toggle("hidden", tab !== "line");
                    document.getElementById("formEditStation")?.classList.toggle("hidden", tab !== "station");
                    document.getElementById("formEditCorrespondence")?.classList.toggle("hidden", tab !== "correspondence");
                    document.getElementById("sectionEditCorrespondence")?.classList.toggle("hidden", tab !== "correspondence");
                    document.getElementById("formEditCity")?.classList.toggle("hidden", tab !== "city");
                    if (tab === "correspondence") {
                        this.populateCorrespondenceSubtab();
                    }
                });
            });

            // Alternar Vista Esquemática SVG vs Vista Geográfica Leaflet
            document.getElementById("btnViewSchematic")?.addEventListener("click", () => {
                NetworkStore.viewMode = "schematic";
                document.getElementById("btnViewSchematic").classList.add("active");
                document.getElementById("btnViewGeo").classList.remove("active");
                document.getElementById("schematicViewport").classList.remove("hidden");
                document.getElementById("geoViewport").classList.add("hidden");
            });

            document.getElementById("btnViewGeo")?.addEventListener("click", () => {
                NetworkStore.viewMode = "geo";
                document.getElementById("btnViewGeo").classList.add("active");
                document.getElementById("btnViewSchematic").classList.remove("active");
                document.getElementById("schematicViewport").classList.add("hidden");
                document.getElementById("geoViewport").classList.remove("hidden");
                GeoMapEngine.renderGeoNetwork();
            });

            // Modo de color: Color oficial de línea vs Ingeniería de Tramo
            document.getElementById("btnColorByLine")?.addEventListener("click", () => {
                NetworkStore.colorMode = "line";
                document.getElementById("btnColorByLine").classList.add("active");
                document.getElementById("btnColorByInfra").classList.remove("active");
                SchematicMapEngine.renderTracksAndStations();
            });

            document.getElementById("btnColorByInfra")?.addEventListener("click", () => {
                NetworkStore.colorMode = "infra";
                document.getElementById("btnColorByInfra").classList.add("active");
                document.getElementById("btnColorByLine").classList.remove("active");
                SchematicMapEngine.renderTracksAndStations();
            });

            // Modo Edición Cartográfica interactiva (arrastrar trazos, estaciones y polígonos)
            const btnEdit = document.getElementById("btnToggleEditMode");
            btnEdit?.addEventListener("click", () => {
                NetworkStore.editMode = !NetworkStore.editMode;
                btnEdit.setAttribute("aria-pressed", String(NetworkStore.editMode));
                document.getElementById("editModeBanner")?.classList.toggle("hidden", !NetworkStore.editMode);
                document.getElementById("visualEditorToolbar")?.classList.toggle("hidden", !NetworkStore.editMode);
                if (!NetworkStore.editMode) {
                    VisualEditorTools.cancel();
                }
                SchematicMapEngine.renderTracksAndStations();
                SchematicMapEngine.renderEditHandles();
            });

            // Control deslizante en vivo para el grosor de los trazos de las líneas
            document.getElementById("trackWidthRange")?.addEventListener("input", (e) => {
                NetworkStore.trackWidthScale = parseFloat(e.target.value) || 1.0;
                SchematicMapEngine.renderTracksAndStations();
                if (NetworkStore.viewMode === "geo") {
                    GeoMapEngine.renderGeoNetwork();
                }
            });

            // Superposición 1:1 del mapa original metro2.png
            const btnPng = document.getElementById("btnTogglePngOverlay");
            btnPng?.addEventListener("click", () => {
                const refLayer = document.getElementById("svgLayerReferenceImage");
                const ctrlBox = document.getElementById("pngOverlayControls");
                const isHidden = refLayer.classList.toggle("hidden");
                ctrlBox?.classList.toggle("hidden", isHidden);
                btnPng.setAttribute("aria-pressed", String(!isHidden));
            });

            document.getElementById("pngOpacityRange")?.addEventListener("input", (e) => {
                const val = e.target.value;
                document.getElementById("svgLayerReferenceImage")?.setAttribute("opacity", val);
                const lbl = document.getElementById("pngOpacityVal");
                if (lbl) lbl.textContent = `${Math.round(val * 100)}%`;
            });

            // Botones de navegación rápida en el mapa
            document.getElementById("btnZoomIn")?.addEventListener("click", () => SchematicMapEngine.zoomBy(0.75));
            document.getElementById("btnZoomOut")?.addEventListener("click", () => SchematicMapEngine.zoomBy(1.33));
            document.getElementById("btnZoomCore")?.addEventListener("click", () => {
                SchematicMapEngine.flyToBox(950, 880, 2340, 1960);
            });
            document.getElementById("btnZoomFull")?.addEventListener("click", () => {
                SchematicMapEngine.flyToBox(80, 150, 4380, 3760);
            });
            document.getElementById("btnZoomLineC")?.addEventListener("click", () => {
                NetworkStore.isolatedLineCode = "C";
                document.getElementById("btnIsolateClear")?.removeAttribute("hidden");
                this.renderLinesDirectory();
                SchematicMapEngine.renderTracksAndStations();
                SchematicMapEngine.flyToBox(120, 920, 1850, 2700);
                showToast("Mostrando Línea C: 21 estaciones operativas (Albufera-Tlacotepec) y 13 cerradas permanentemente");
            });

            const btnLabels = document.getElementById("btnToggleLabels");
            btnLabels?.addEventListener("click", () => {
                NetworkStore.showLabels = !NetworkStore.showLabels;
                btnLabels.setAttribute("aria-pressed", String(NetworkStore.showLabels));
                SchematicMapEngine.renderTracksAndStations();
            });

            document.getElementById("btnEditCityZones")?.addEventListener("click", () => {
                this.switchRightTab("editor");
                document.querySelector('.ed-subtab[data-edtab="city"]')?.click();
            });

            // Minimizar / expandir leyenda
            document.getElementById("btnToggleLegend")?.addEventListener("click", (e) => {
                const body = document.getElementById("legendBody");
                const isHidden = body.classList.toggle("hidden");
                e.currentTarget.textContent = isHidden ? "+" : "−";
            });

            // Velocidad de simulación
            document.querySelectorAll(".speed-chip").forEach(btn => {
                btn.addEventListener("click", () => {
                    document.querySelectorAll(".speed-chip").forEach(b => b.classList.remove("active"));
                    btn.classList.add("active");
                    NetworkStore.simSpeedMultiplier = Number(btn.dataset.speed);
                });
            });

            // Tema visual Oscuro / Claro
            document.getElementById("btnThemeToggle")?.addEventListener("click", () => {
                const html = document.documentElement;
                const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
                html.setAttribute("data-theme", next);
            });

            // Filtro por Tipología de Red (Todos / Metro / Red de Autobuses Articulados)
            document.querySelectorAll(".typo-pill").forEach(btn => {
                btn.addEventListener("click", () => {
                    document.querySelectorAll(".typo-pill").forEach(b => b.classList.remove("active"));
                    btn.classList.add("active");
                    NetworkStore.networkFilter = btn.dataset.netfilter;
                    this.renderLinesDirectory();
                    SchematicMapEngine.renderTracksAndStations();
                    if (NetworkStore.viewMode === "geo") GeoMapEngine.renderGeoNetwork();
                });
            });

            // Filtro por Tipo de Infraestructura o Estado
            document.querySelectorAll("#infraFilterChips .filter-chip").forEach(chip => {
                chip.addEventListener("click", () => {
                    document.querySelectorAll("#infraFilterChips .filter-chip").forEach(c => c.classList.remove("active"));
                    chip.classList.add("active");
                    NetworkStore.infraFilter = chip.dataset.infra;
                    SchematicMapEngine.renderTracksAndStations();
                });
            });

            // Clic en tarjeta de línea en el directorio izquierdo
            document.getElementById("linesDirectoryList")?.addEventListener("click", (e) => {
                const card = e.target.closest(".line-card");
                if (!card) return;
                const code = card.dataset.lineCode;
                if (NetworkStore.isolatedLineCode === code) {
                    NetworkStore.isolatedLineCode = null;
                    document.getElementById("btnIsolateClear")?.setAttribute("hidden", "true");
                } else {
                    NetworkStore.isolatedLineCode = code;
                    document.getElementById("btnIsolateClear")?.removeAttribute("hidden");
                }
                this.renderLinesDirectory();
                SchematicMapEngine.renderTracksAndStations();
                if (NetworkStore.viewMode === "geo") GeoMapEngine.renderGeoNetwork();
            });

            const clearIsolation = () => {
                NetworkStore.isolatedLineCode = null;
                NetworkStore.networkFilter = "all";
                NetworkStore.infraFilter = "all";
                document.getElementById("btnIsolateClear")?.setAttribute("hidden", "true");
                document.querySelectorAll(".typo-pill").forEach(b => b.classList.toggle("active", b.dataset.netfilter === "all"));
                document.querySelectorAll("#infraFilterChips .filter-chip").forEach(c => c.classList.toggle("active", c.dataset.infra === "all"));
                this.renderLinesDirectory();
                SchematicMapEngine.renderTracksAndStations();
            };

            document.getElementById("btnIsolateClear")?.addEventListener("click", clearIsolation);
            document.getElementById("btnShowAllLines")?.addEventListener("click", clearIsolation);

            // Buscador global de estaciones y líneas (con atajo de teclado /)
            const searchInput = document.getElementById("globalSearchInput");
            const dropdown = document.getElementById("searchResultsDropdown");

            searchInput?.addEventListener("input", () => {
                const q = searchInput.value.trim().toLowerCase();
                if (!q) {
                    dropdown.classList.add("hidden");
                    return;
                }
                const matchedLines = NetworkStore.lines.filter(
                    l => l.code.toLowerCase().includes(q) || l.name.toLowerCase().includes(q) || l.route_title.toLowerCase().includes(q)
                ).slice(0, 4);
                const matchedStations = NetworkStore.stations.filter(
                    s => s.name.toLowerCase().includes(q)
                ).slice(0, 10);

                let html = "";
                for (const l of matchedLines) {
                    html += `
                        <div class="search-result-item" data-type="line" data-code="${escapeHtml(l.code)}">
                            <div>
                                <span class="line-badge-sm" style="background:${l.color}; color:${l.text_color};">${escapeHtml(l.code)}</span>
                                <strong style="margin-left:6px;">${escapeHtml(l.route_title)}</strong>
                            </div>
                            <span style="font-size:10.5px; color:var(--text-muted);">${l.declared_stations_count} est.</span>
                        </div>
                    `;
                }
                for (const s of matchedStations) {
                    html += `
                        <div class="search-result-item" data-type="station" data-id="${s.id}">
                            <strong>${escapeHtml(s.name)}</strong>
                            <span style="font-size:10.5px; color:var(--text-secondary);">Líneas: ${escapeHtml(s.lines.join("/"))}</span>
                        </div>
                    `;
                }
                dropdown.innerHTML = html || `<div class="search-result-item">Sin coincidencias para "${escapeHtml(q)}"</div>`;
                dropdown.classList.remove("hidden");
            });

            dropdown?.addEventListener("click", (e) => {
                const item = e.target.closest(".search-result-item");
                if (!item) return;
                dropdown.classList.add("hidden");
                searchInput.value = "";
                if (item.dataset.type === "station") {
                    const stId = Number(item.dataset.id);
                    const st = NetworkStore.stationsById.get(stId);
                    if (st) {
                        SchematicMapEngine.flyToBox(st.x - 850, st.y - 500, 1700, 1000);
                        this.selectStation(stId);
                    }
                } else if (item.dataset.type === "line") {
                    NetworkStore.isolatedLineCode = item.dataset.code;
                    document.getElementById("btnIsolateClear")?.removeAttribute("hidden");
                    this.renderLinesDirectory();
                    SchematicMapEngine.renderTracksAndStations();
                }
            });

            // Botones rápidos del estado vacío del inspector
            document.querySelectorAll(".js-quick-station").forEach(btn => {
                btn.addEventListener("click", () => {
                    const name = btn.dataset.stname.toLowerCase();
                    const st = NetworkStore.stations.find(s => s.name.toLowerCase().includes(name));
                    if (st) {
                        SchematicMapEngine.flyToBox(st.x - 850, st.y - 500, 1700, 1000);
                        this.selectStation(st.id);
                    }
                });
            });

            // Delegación en el panel derecho (aislar línea o saltar al editor desde el inspector/métricas)
            document.getElementById("sidebarRight")?.addEventListener("click", async (e) => {
                const isoBtn = e.target.closest(".js-isolate-line");
                if (isoBtn) {
                    NetworkStore.isolatedLineCode = isoBtn.dataset.lineCode;
                    document.getElementById("btnIsolateClear")?.removeAttribute("hidden");
                    this.renderLinesDirectory();
                    SchematicMapEngine.renderTracksAndStations();
                    return;
                }

                const openStEdit = e.target.closest(".js-open-station-editor");
                if (openStEdit) {
                    const stId = Number(openStEdit.dataset.stationId);
                    this.switchRightTab("editor");
                    document.querySelector('.ed-subtab[data-edtab="station"]')?.click();
                    this.loadStationIntoEditor(stId);
                    return;
                }

                const quickAddCorr = e.target.closest(".js-quick-add-corr");
                if (quickAddCorr) {
                    const stId = Number(quickAddCorr.dataset.stationId);
                    VisualEditorTools.openCorrespondenceModal(stId);
                    return;
                }

                const disconnectBtn = e.target.closest(".js-disconnect-line-btn");
                if (disconnectBtn) {
                    const stId = Number(disconnectBtn.dataset.stationId);
                    const lineCode = disconnectBtn.dataset.lineCode;
                    if (stId && lineCode) {
                        this.disconnectStationFromLine(stId, lineCode);
                    }
                    return;
                }

                const deleteStBtn = e.target.closest(".js-delete-station-btn");
                if (deleteStBtn) {
                    const stId = Number(deleteStBtn.dataset.stationId);
                    if (stId) {
                        this.deleteStation(stId);
                    }
                    return;
                }

                const jumpLineEdit = e.target.closest(".js-jump-edit-line");
                if (jumpLineEdit) {
                    this.switchRightTab("editor");
                    document.querySelector('.ed-subtab[data-edtab="line"]')?.click();
                    this.loadLineIntoEditor(jumpLineEdit.dataset.lineCode);
                    return;
                }

                const toggleAlertBtn = e.target.closest(".js-toggle-alert");
                if (toggleAlertBtn) {
                    const alertId = toggleAlertBtn.dataset.alertId;
                    await ApiClient.post(`/api/alerts/${alertId}/toggle/`, {});
                    await refreshNetworkDataAndRender();
                    showToast("Estado de alerta actualizado en PCCO");
                    return;
                }

                // Alternar con 1 clic cualquiera de los 6 tags con icono directamente en el Inspector de Estación
                const inspTagBtn = e.target.closest(".js-inspector-toggle-tag");
                if (inspTagBtn) {
                    const tagId = inspTagBtn.dataset.tagId;
                    const stId = Number(inspTagBtn.closest(".tag-toggle-grid")?.dataset.stationId || NetworkStore.selectedStationId);
                    const st = NetworkStore.stationsById.get(stId);
                    if (st && tagId) {
                        const current = Array.isArray(st.icon_tags) ? [...st.icon_tags] : [];
                        const idx = current.indexOf(tagId);
                        if (idx >= 0) current.splice(idx, 1);
                        else current.push(tagId);
                        st.icon_tags = current;
                        inspTagBtn.classList.toggle("active", idx < 0);
                        inspTagBtn.setAttribute("aria-pressed", String(idx < 0));
                        SchematicMapEngine.renderTracksAndStations();
                        if (Number(document.getElementById("editStationSelect")?.value) === st.id) {
                            this.loadStationIntoEditor(st.id);
                        }
                        await ApiClient.post(`/api/stations/${st.id}/update/`, { icon_tags: st.icon_tags });
                        const tagDef = STATION_ICON_TAGS_MAP.get(tagId);
                        showToast(`${idx < 0 ? "Agregado" : "Quitado"} tag "${tagDef?.label || tagId}" en ${st.name}`);
                    }
                    return;
                }

                // Alternar botones de tags dentro del formulario Editor de Estación
                const edTagBtn = e.target.closest(".js-editor-toggle-tag");
                if (edTagBtn) {
                    const isNowActive = !edTagBtn.classList.contains("active");
                    edTagBtn.classList.toggle("active", isNowActive);
                    edTagBtn.setAttribute("aria-pressed", String(isNowActive));
                    return;
                }

                // Alternar con 1 clic si esta estación es Terminal de una línea directamente desde el Inspector
                const inspTermBtn = e.target.closest(".js-inspector-toggle-terminal");
                if (inspTermBtn) {
                    const code = inspTermBtn.dataset.lineCode;
                    const stId = Number(inspTermBtn.closest(".terminal-lines-editor")?.dataset.stationId || NetworkStore.selectedStationId);
                    const st = NetworkStore.stationsById.get(stId);
                    if (st && code) {
                        const list = Array.isArray(st.terminal_lines) ? [...st.terminal_lines] : [];
                        const i = list.indexOf(code);
                        if (i >= 0) list.splice(i, 1);
                        else list.push(code);
                        st.terminal_lines = list;
                        st.is_terminal = list.length > 0;
                        await ApiClient.post(`/api/stations/${st.id}/update/`, { terminal_lines: st.terminal_lines });
                        SchematicMapEngine.renderTracksAndStations();
                        if (NetworkStore.viewMode === "geo") GeoMapEngine.renderGeoNetwork();
                        this.selectStation(st.id);
                        if (Number(document.getElementById("editStationSelect")?.value) === st.id) {
                            this.loadStationIntoEditor(st.id);
                        }
                        if (document.getElementById("editLineSelect")?.value === code) {
                            this.loadLineIntoEditor(code);
                        }
                        showToast(`${i < 0 ? "Asignada" : "Quitada"} terminal de Línea ${code} en ${st.name}`);
                    }
                    return;
                }

                // Asignar cualquier otra línea como terminal en esta estación desde el desplegable del Inspector
                const inspAddTermBtn = e.target.closest(".js-inspector-add-terminal");
                if (inspAddTermBtn) {
                    const box = inspAddTermBtn.closest(".terminal-lines-editor");
                    const sel = box?.querySelector(".js-inspector-terminal-select");
                    const code = sel?.value;
                    const stId = Number(box?.dataset.stationId || NetworkStore.selectedStationId);
                    const st = NetworkStore.stationsById.get(stId);
                    if (st && code) {
                        const list = Array.isArray(st.terminal_lines) ? [...st.terminal_lines] : [];
                        if (!list.includes(code)) list.push(code);
                        st.terminal_lines = list;
                        st.is_terminal = true;
                        await ApiClient.post(`/api/stations/${st.id}/update/`, { terminal_lines: st.terminal_lines });
                        SchematicMapEngine.renderTracksAndStations();
                        if (NetworkStore.viewMode === "geo") GeoMapEngine.renderGeoNetwork();
                        this.selectStation(st.id);
                        if (Number(document.getElementById("editStationSelect")?.value) === st.id) {
                            this.loadStationIntoEditor(st.id);
                        }
                        if (document.getElementById("editLineSelect")?.value === code) {
                            this.loadLineIntoEditor(code);
                        }
                        showToast(`${st.name} asignada como terminal de Línea ${code}`);
                    }
                    return;
                }

                // Controles de terminal dentro de Editor de Datos -> Editar Estación
                const edTermBtn = e.target.closest(".js-editor-toggle-terminal");
                if (edTermBtn) {
                    const isNowOn = !edTermBtn.classList.contains("active");
                    edTermBtn.classList.toggle("active", isNowOn);
                    edTermBtn.setAttribute("aria-pressed", String(isNowOn));
                    const labelSpan = edTermBtn.querySelector("span:last-child");
                    if (labelSpan) labelSpan.textContent = isNowOn ? "Terminal ✓" : "Marcar Terminal";
                    return;
                }

                const edAddTermBtn = e.target.closest(".js-editor-add-terminal");
                if (edAddTermBtn) {
                    const box = edAddTermBtn.closest(".terminal-lines-editor");
                    const sel = box?.querySelector(".js-editor-terminal-select");
                    const code = sel?.value;
                    if (box && code) {
                        let existingChip = box.querySelector(`.js-editor-toggle-terminal[data-line-code="${CSS.escape(code)}"]`);
                        if (existingChip) {
                            existingChip.classList.add("active");
                            existingChip.setAttribute("aria-pressed", "true");
                            const lbl = existingChip.querySelector("span:last-child");
                            if (lbl) lbl.textContent = "Terminal ✓";
                        } else {
                            const ln = NetworkStore.linesByCode.get(code);
                            const bg = ln ? ln.color : "#475569";
                            const fg = getBadgeTextColor(bg, "#FFFFFF");
                            const row = box.querySelector(".terminal-badges-active-row");
                            if (row) {
                                const emptyHint = row.querySelector("span:only-child");
                                if (emptyHint && !emptyHint.classList.contains("terminal-num-dot")) emptyHint.remove();
                                const btn = document.createElement("button");
                                btn.type = "button";
                                btn.className = "terminal-line-chip active js-editor-toggle-terminal";
                                btn.dataset.lineCode = code;
                                btn.setAttribute("aria-pressed", "true");
                                btn.innerHTML = `<span class="terminal-num-dot" style="background:${bg}; color:${fg};">${escapeHtml(code)}</span><span>Terminal ✓</span>`;
                                row.appendChild(btn);
                            }
                        }
                        sel.value = "";
                    }
                    return;
                }
            });

            // Simular Incidente Realista con 1 clic
            document.getElementById("btnSimulateIncident")?.addEventListener("click", async () => {
                const res = await ApiClient.post("/api/alerts/simulate/", {});
                await refreshNetworkDataAndRender();
                showToast(`Incidente simulado: ${res.data?.title || "Alerta emitida"}`);
            });

            // Modal Nueva Alerta
            const modalAlert = document.getElementById("modalNewAlert");
            document.getElementById("btnOpenNewAlertModal")?.addEventListener("click", () => {
                modalAlert?.classList.remove("hidden");
            });
            document.getElementById("btnCloseAlertModal")?.addEventListener("click", () => {
                modalAlert?.classList.add("hidden");
            });
            document.getElementById("btnCancelAlertModal")?.addEventListener("click", () => {
                modalAlert?.classList.add("hidden");
            });

            document.getElementById("formCreateAlert")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const payload = {
                    title: document.getElementById("newAlertTitle").value,
                    line_code: document.getElementById("newAlertLine").value,
                    severity: document.getElementById("newAlertSeverity").value,
                    category: document.getElementById("newAlertCategory").value,
                    speed_factor: parseFloat(document.getElementById("newAlertSpeedFactor").value),
                    description: document.getElementById("newAlertDesc").value
                };
                await ApiClient.post("/api/alerts/create/", payload);
                modalAlert?.classList.add("hidden");
                await refreshNetworkDataAndRender();
                showToast("Nueva alerta emitida por el Puesto Central de Control");
            });

            // Selectores del Editor de Datos
            document.getElementById("editLineSelect")?.addEventListener("change", (e) => {
                this.loadLineIntoEditor(e.target.value);
            });
            document.getElementById("editLineColorPicker")?.addEventListener("input", (e) => {
                document.getElementById("editLineColor").value = e.target.value;
            });
            document.getElementById("editStationSelect")?.addEventListener("change", (e) => {
                this.loadStationIntoEditor(e.target.value);
            });
            document.getElementById("editCitySelect")?.addEventListener("change", (e) => {
                this.loadCityIntoEditor(e.target.value);
            });

            // Guardar edición de Línea
            document.getElementById("formEditLine")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const code = document.getElementById("editLineSelect").value;
                const payload = {
                    name: document.getElementById("editLineName").value,
                    color: document.getElementById("editLineColor").value,
                    route_title: document.getElementById("editLineRoute").value,
                    network_type: document.getElementById("editLineNetworkType").value,
                    status: document.getElementById("editLineStatus").value,
                    frequency_seconds: parseInt(document.getElementById("editLineFreq").value, 10),
                    premium_frequency_seconds: document.getElementById("editLinePremFreq").value || null,
                    max_speed_kmh: parseFloat(document.getElementById("editLineSpeed").value),
                    first_train_time: document.getElementById("editLineFirstTrain").value,
                    last_train_time: document.getElementById("editLineLastTrain").value,
                    current_occupancy_pct: parseInt(document.getElementById("editLineOccupancy").value, 10),
                    length_km: parseFloat(document.getElementById("editLineLength").value),
                    min_curve_radius_m: parseFloat(document.getElementById("editLineRadius").value),
                    status_note: document.getElementById("editLineNote").value
                };
                const res = await ApiClient.post(`/api/lines/${encodeURIComponent(code)}/update/`, payload);
                if (!res.ok) {
                    showToast(res.error || `Error al actualizar la Línea ${code}`);
                    return;
                }
                await refreshNetworkDataAndRender(true);
                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ Línea ${code} actualizada y sincronizada en el mapa${msgMode}`);
            });

            // Controles de Trayecto y Moldeado de Trazos de la Línea
            document.getElementById("btnIsolateAndEditTrack")?.addEventListener("click", () => {
                const code = document.getElementById("editLineSelect")?.value;
                const ln = NetworkStore.linesByCode.get(code);
                if (!ln) return;
                NetworkStore.isolatedLineCode = code;
                NetworkStore.editMode = true;
                document.getElementById("btnIsolateClear")?.removeAttribute("hidden");
                document.getElementById("btnToggleEditMode")?.setAttribute("aria-pressed", "true");
                document.getElementById("editModeBanner")?.classList.remove("hidden");
                this.renderLinesDirectory();
                SchematicMapEngine.renderTracksAndStations();
                SchematicMapEngine.renderEditHandles();

                if (ln.stops.length > 0) {
                    const xs = ln.stops.map(s => (NetworkStore.stationsById.get(s.station_id) || s).x);
                    const ys = ln.stops.map(s => (NetworkStore.stationsById.get(s.station_id) || s).y);
                    const minX = Math.min(...xs) - 180;
                    const minY = Math.min(...ys) - 180;
                    const boxW = Math.max(600, Math.max(...xs) - minX + 180);
                    const boxH = Math.max(450, Math.max(...ys) - minY + 180);
                    SchematicMapEngine.flyToBox(minX, minY, boxW, boxH);
                }
                showToast(`Moldeado activo en ${ln.name}: haz clic y arrastra sobre su trazo en el mapa`);
            });

            document.getElementById("btnClearLineWaypoints")?.addEventListener("click", async () => {
                const code = document.getElementById("editLineSelect")?.value;
                if (!code) return;
                try {
                    const res = await ApiClient.post(`/api/lines/${encodeURIComponent(code)}/route/`, {
                        clear_all_waypoints: true,
                        straighten_orthogonal: true
                    });
                    if (res.ok) {
                        await refreshNetworkDataAndRender(false);
                        this.loadLineIntoEditor(code);
                        const msgMode = res.server ? "" : " (guardado localmente)";
                        showToast(`✓ Trazos de Línea ${code} enderezados derecho (90° / 180°)${msgMode}`);
                    } else {
                        showToast(res.error || "No se pudieron enderezar los trazos");
                    }
                } catch (err) {
                    showToast("Error al enderezar trazos");
                }
            });

            document.getElementById("btnAddStationToRoute")?.addEventListener("click", () => {
                const stId = Number(document.getElementById("addRouteStationSelect")?.value);
                const st = NetworkStore.stationsById.get(stId);
                if (!st) return;
                NetworkStore.draftRouteStops.push({
                    id: null,
                    station_id: st.id,
                    station_name: st.name,
                    branch: "main",
                    segment_infrastructure: st.infrastructure_type,
                    segment_status: st.operational_status,
                    depth_meters: st.depth_meters,
                    waypoints: [],
                    is_terminal_for_line: false
                });
                this.renderLineRouteEditor();
            });

            document.getElementById("lineRouteStopsList")?.addEventListener("click", async (e) => {
                const termBtn = e.target.closest(".js-route-toggle-terminal");
                const strBtn = e.target.closest(".js-route-straighten-seg");
                const upBtn = e.target.closest(".js-route-move-up");
                const downBtn = e.target.closest(".js-route-move-down");
                const rmBtn = e.target.closest(".js-route-remove");
                const stops = NetworkStore.draftRouteStops;
                if (termBtn) {
                    const idx = Number(termBtn.dataset.idx);
                    const stopItem = stops[idx];
                    const code = document.getElementById("editLineSelect")?.value;
                    if (!stopItem || !code) return;
                    stopItem.is_terminal_for_line = !stopItem.is_terminal_for_line;
                    const st = NetworkStore.stationsById.get(stopItem.station_id);
                    if (st) {
                        const list = Array.isArray(st.terminal_lines) ? [...st.terminal_lines] : [];
                        const pos = list.indexOf(code);
                        if (stopItem.is_terminal_for_line && pos === -1) list.push(code);
                        if (!stopItem.is_terminal_for_line && pos >= 0) list.splice(pos, 1);
                        st.terminal_lines = list;
                        st.is_terminal = list.length > 0;
                        await ApiClient.post(`/api/stations/${st.id}/update/`, { terminal_lines: st.terminal_lines });
                        SchematicMapEngine.renderTracksAndStations();
                        if (NetworkStore.viewMode === "geo") GeoMapEngine.renderGeoNetwork();
                        showToast(`${stopItem.is_terminal_for_line ? "Marcada" : "Quitada"} ${st.name} como terminal de Línea ${code}`);
                    }
                    this.renderLineRouteEditor();
                } else if (strBtn) {
                    const idx = Number(strBtn.dataset.idx);
                    if (idx < stops.length - 1) {
                        const s1 = stops[idx];
                        const s2 = stops[idx + 1];
                        const st1 = NetworkStore.stationsById.get(s1.station_id);
                        const st2 = NetworkStore.stationsById.get(s2.station_id);
                        if (st1 && st2) {
                            const dx = st2.x - st1.x;
                            const dy = st2.y - st1.y;
                            if (Math.abs(dx) >= Math.abs(dy)) {
                                s1.waypoints = Math.abs(dy) < 0.5 ? [] : [[Math.round(st2.x * 2) / 2, Math.round(st1.y * 2) / 2]];
                            } else {
                                s1.waypoints = Math.abs(dx) < 0.5 ? [] : [[Math.round(st1.x * 2) / 2, Math.round(st2.y * 2) / 2]];
                            }
                            this.renderLineRouteEditor();
                            SchematicMapEngine.renderTracksAndStations();
                            showToast(`✓ Tramo hacia ${st2.name} enderezado derecho a ${Math.abs(dx) >= Math.abs(dy) ? "180° (horizontal)" : "90° (vertical)"}`);
                        }
                    }
                } else if (upBtn) {
                    const idx = Number(upBtn.dataset.idx);
                    if (idx > 0) {
                        [stops[idx - 1], stops[idx]] = [stops[idx], stops[idx - 1]];
                        stops[idx - 1].waypoints = [];
                        stops[idx].waypoints = [];
                        this.renderLineRouteEditor();
                    }
                } else if (downBtn) {
                    const idx = Number(downBtn.dataset.idx);
                    if (idx < stops.length - 1) {
                        [stops[idx + 1], stops[idx]] = [stops[idx], stops[idx + 1]];
                        stops[idx + 1].waypoints = [];
                        stops[idx].waypoints = [];
                        this.renderLineRouteEditor();
                    }
                } else if (rmBtn) {
                    if (stops.length <= 2) {
                        showToast("Una línea debe conservar al menos 2 estaciones en su trayecto.");
                        return;
                    }
                    const idx = Number(rmBtn.dataset.idx);
                    if (idx > 0 && stops[idx - 1]) stops[idx - 1].waypoints = [];
                    stops.splice(idx, 1);
                    this.renderLineRouteEditor();
                }
            });

            document.getElementById("btnSaveLineRoute")?.addEventListener("click", async () => {
                const code = document.getElementById("editLineSelect")?.value;
                if (!code || NetworkStore.draftRouteStops.length < 2) return;
                const terminalIds = NetworkStore.draftRouteStops
                    .filter(s => s.is_terminal_for_line)
                    .map(s => s.station_id);
                const res = await ApiClient.post(`/api/lines/${encodeURIComponent(code)}/route/`, {
                    stops: NetworkStore.draftRouteStops,
                    terminal_station_ids: terminalIds,
                    snap: true
                });
                if (res.ok) {
                    await refreshNetworkDataAndRender(true);
                    this.loadLineIntoEditor(code);
                    const msgMode = res.server ? "" : " (guardado localmente)";
                    showToast(`✓ Trayecto y terminales de Línea ${code} guardados (${NetworkStore.draftRouteStops.length} paradas)${msgMode}`);
                } else {
                    showToast(res.error || "No se pudo guardar el trayecto. Verifica las estaciones.");
                }
            });

            // Guardar edición de Estación
            document.getElementById("formEditStation")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const stId = document.getElementById("editStationSelect").value;
                const selectedTags = Array.from(
                    document.querySelectorAll("#editStationTagsGroup .tag-chip-btn.active")
                ).map(btn => btn.dataset.tagId).filter(Boolean);
                const selectedTerminals = Array.from(
                    document.querySelectorAll("#editStationTerminalsGroup .terminal-line-chip.active")
                ).map(btn => btn.dataset.lineCode).filter(Boolean);
                const payload = {
                    name: document.getElementById("editStationName").value,
                    infrastructure_type: document.getElementById("editStationInfra").value,
                    operational_status: document.getElementById("editStationStatus").value,
                    x: parseFloat(document.getElementById("editStationX").value),
                    y: parseFloat(document.getElementById("editStationY").value),
                    depth_meters: parseFloat(document.getElementById("editStationDepth").value),
                    platform_type: document.getElementById("editStationPlatform").value,
                    emergency_exits: parseInt(document.getElementById("editStationExits").value, 10),
                    has_psd: document.getElementById("editStationPsd").checked,
                    is_premium_stop: document.getElementById("editStationPremium").checked,
                    icon_tags: selectedTags,
                    terminal_lines: selectedTerminals
                };
                const res = await ApiClient.post(`/api/stations/${stId}/update/`, payload);
                if (!res.ok) {
                    showToast(res.error || "Error al actualizar la estación");
                    return;
                }
                await refreshNetworkDataAndRender(false);
                this.selectStation(Number(stId));
                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ Estación, terminales y tags actualizados en la cartografía${msgMode}`);
            });

            // Guardar edición de Polígono de la Ciudad
            document.getElementById("formEditCity")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const outlineId = document.getElementById("editCitySelect").value;
                const payload = {
                    name: document.getElementById("editCityName").value,
                    color: document.getElementById("editCityColor").value,
                    opacity: parseFloat(document.getElementById("editCityOpacity").value),
                    elevation_m: parseFloat(document.getElementById("editCityElevation").value)
                };
                const res = await ApiClient.post(`/api/city-outlines/${outlineId}/update/`, payload);
                await refreshNetworkDataAndRender(false);
                const msgMode = res.server ? "" : " (guardado localmente)";
                showToast(`✓ Polígono geográfico de la ciudad actualizado${msgMode}`);
            });

            // Botón Restaurar Plan Maestro original
            document.getElementById("btnResetMasterPlan")?.addEventListener("click", async () => {
                await ApiClient.post("/api/network/reset/", {});
                await refreshNetworkDataAndRender(true);
                showToast("Cartografía y datos restaurados al Plan Maestro SMyT original");
            });

            // =================================================================
            // EVENTOS DEL EDITOR VISUAL DE RED (HERRAMIENTAS, MODALES Y FORMS)
            // =================================================================
            document.getElementById("btnToolAddStation")?.addEventListener("click", () => {
                VisualEditorTools.setTool("add_station");
            });
            document.getElementById("btnToolAddLine")?.addEventListener("click", () => {
                VisualEditorTools.openNewLineModal();
            });
            document.getElementById("btnToolAddSegment")?.addEventListener("click", () => {
                VisualEditorTools.setTool("connect_segment");
            });
            document.getElementById("btnToolAddCorrespondence")?.addEventListener("click", () => {
                VisualEditorTools.setTool("add_correspondence");
            });
            document.getElementById("btnCancelActiveTool")?.addEventListener("click", () => {
                VisualEditorTools.cancel();
            });

            // Botón Enderezar Línea Activa a 45°/90° (Snap Octilineal estilo MetroMapMaker)
            document.getElementById("btnStraightenActiveLine")?.addEventListener("click", async () => {
                const lineCode = VisualEditorTools.getActiveLineCode();
                await this.straightenLineTracks(lineCode);
                showToast(`✓ Trazos de Línea ${lineCode} enderezados y alineados a 45°/90°`);
            });

            // Deshacer y Rehacer
            document.getElementById("btnEditorUndo")?.addEventListener("click", () => {
                HistoryManager.undo();
            });
            document.getElementById("btnEditorRedo")?.addEventListener("click", () => {
                HistoryManager.redo();
            });

            // Guardar y Descartar Capa de Usuario
            document.getElementById("btnSaveUserLayer")?.addEventListener("click", async () => {
                try {
                    const res = await ApiClient.post("/api/editor/save/", {});
                    if (res.ok) {
                        const resData = res.data || res;
                        const msgMode = res.server ? "en servidor y local" : "en almacenamiento local";
                        showToast(`💾 Capa de red guardada con éxito (${msgMode})`);
                    } else {
                        showToast(res.error || "Error al guardar capa de usuario");
                    }
                } catch (err) {
                    showToast("Error al guardar capa");
                }
            });

            document.getElementById("btnDiscardUserLayer")?.addEventListener("click", async () => {
                if (confirm("¿Deseas descartar todas las modificaciones y volver al Plan Maestro original?")) {
                    try {
                        ApiClient.clearStoredEdits();
                        await ApiClient.post("/api/editor/discard/", {});
                        HistoryManager.undoStack = [];
                        HistoryManager.redoStack = [];
                        HistoryManager.updateButtons();
                        await refreshNetworkDataAndRender(true);
                        showToast("↺ Red restaurada al Plan Maestro original");
                    } catch (err) {
                        showToast("Error al descartar modificaciones");
                    }
                }
            });

            // Exportar e Importar Respaldo JSON de usuario
            document.getElementById("btnExportUserLayerJson")?.addEventListener("click", () => {
                ApiClient.exportEditsAsJson();
            });
            document.getElementById("btnImportUserLayerJson")?.addEventListener("click", () => {
                document.getElementById("inputImportUserLayerJson")?.click();
            });
            document.getElementById("inputImportUserLayerJson")?.addEventListener("change", async (e) => {
                const file = e.target.files?.[0];
                if (file) {
                    await ApiClient.importEditsFromFile(file);
                    e.target.value = "";
                }
            });

            // Cerrar Modales
            const closeAllEditorModals = () => {
                document.getElementById("modalNewStation")?.classList.add("hidden");
                document.getElementById("modalNewLine")?.classList.add("hidden");
                document.getElementById("modalNewSegment")?.classList.add("hidden");
                document.getElementById("modalNewCorrespondence")?.classList.add("hidden");
                ContextMenuManager.hide();
                VisualEditorTools.pendingLineCaller = null;
                VisualEditorTools.cancel();
            };

            document.getElementById("btnCloseNewStationModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCancelNewStationModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCloseNewLineModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCancelNewLineModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCloseNewSegmentModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCancelNewSegmentModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCloseNewCorrModal")?.addEventListener("click", closeAllEditorModals);
            document.getElementById("btnCancelNewCorrModal")?.addEventListener("click", closeAllEditorModals);

            // Botones de acción directa: Crear Nueva Estación
            document.getElementById("btnQuickAddStation")?.addEventListener("click", () => {
                VisualEditorTools.openNewStationModal();
            });
            document.getElementById("btnOpenNewStationFromEditor")?.addEventListener("click", () => {
                VisualEditorTools.openNewStationModal();
            });
            document.getElementById("btnToolAddStation")?.addEventListener("click", () => {
                VisualEditorTools.setTool("station");
            });

            document.getElementById("btnCreateLineFromStationModal")?.addEventListener("click", () => {
                VisualEditorTools.pendingLineCaller = "station";
                VisualEditorTools.openNewLineModal();
            });

            document.getElementById("btnCreateLineFromSegmentModal")?.addEventListener("click", () => {
                VisualEditorTools.pendingLineCaller = "segment";
                VisualEditorTools.openNewLineModal();
            });

            // Sincronizar selector de color en Modal Nueva Línea
            document.getElementById("newLineColorPicker")?.addEventListener("input", (e) => {
                const textInput = document.getElementById("newLineColor");
                if (textInput) textInput.value = e.target.value.toUpperCase();
            });

            // 1. Envío Formulario Modal: Crear Estación (100% funcional y reactivo)
            document.getElementById("formCreateStationModal")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const name = document.getElementById("newStationName").value.trim();
                if (!name) {
                    showToast("El nombre de la estación es obligatorio");
                    return;
                }
                const xVal = parseFloat(document.getElementById("newStationX").value);
                const yVal = parseFloat(document.getElementById("newStationY").value);
                const x = isNaN(xVal) ? 2120.0 : xVal;
                const y = isNaN(yVal) ? 1860.0 : yVal;
                const infra = document.getElementById("newStationInfra").value;
                const status = document.getElementById("newStationStatus").value;
                const initLine = document.getElementById("newStationInitialLine").value;

                const payload = {
                    name,
                    x,
                    y,
                    infrastructure_type: infra || "subterraneo",
                    operational_status: status || "operational",
                    lines: initLine ? [initLine] : []
                };

                try {
                    const res = await ApiClient.post("/api/stations/create/", payload);
                    if (!res.ok) {
                        showToast(res.error || "Error al crear la estación");
                        return;
                    }
                    const resData = res.data || res;
                    closeAllEditorModals();
                    await refreshNetworkDataAndRender(true);
                    const stObj = resData.station || payload;
                    if (stObj.id) this.selectStation(stObj.id);
                    if (stObj.x && stObj.y) {
                        SchematicMapEngine.flyToBox(stObj.x - 300, stObj.y - 200, 600, 400);
                    }
                    HistoryManager.push({
                        type: "station_create",
                        stationId: stObj.id,
                        description: `Crear estación "${name}"`
                    });
                    const msgMode = res.server ? "" : " (guardado localmente)";
                    showToast(`✓ Estación "${name}" creada exitosamente${msgMode}`);
                } catch (err) {
                    showToast("Error al crear estación");
                }
            });

            // 2. Envío Formulario Modal: Crear Línea
            document.getElementById("formCreateLineModal")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const code = document.getElementById("newLineCode").value.trim().toUpperCase();
                const name = document.getElementById("newLineName").value.trim();
                const color = document.getElementById("newLineColor").value.trim();
                const netType = document.getElementById("newLineNetType").value;
                const subType = document.getElementById("newLineSubType").value;

                if (!code || !name) {
                    showToast("Código y nombre de línea son obligatorios");
                    return;
                }

                try {
                    const res = await ApiClient.post("/api/lines/create/", {
                            code,
                            name,
                            color,
                            network_type: netType,
                            line_subtype: subType
                        });
                    if (!res.ok) {
                        showToast(res.error || "Error al crear la línea");
                        return;
                    }
                    await refreshNetworkDataAndRender();
                    NetworkStore.isolatedLineCode = code;
                    this.renderLinesDirectory();
                    this.populateEditorSelects();

                    HistoryManager.push({
                        type: "line_create",
                        lineCode: code,
                        description: `Crear Línea ${code}`
                    });
                    const msgMode = res.server ? "" : " (guardado localmente)";
                    showToast(`✓ Línea ${code} creada exitosamente${msgMode}`);

                    if (VisualEditorTools.pendingLineCaller === "station") {
                        VisualEditorTools.pendingLineCaller = null;
                        document.getElementById("modalNewLine")?.classList.add("hidden");
                        const selLine = document.getElementById("newStationInitialLine");
                        if (selLine) {
                            selLine.innerHTML = '<option value="">(Ninguna: estación independiente / huérfana)</option>' +
                                NetworkStore.lines.map(l =>
                                    `<option value="${escapeHtml(l.code)}" ${code === l.code ? "selected" : ""}>Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`
                                ).join("");
                            selLine.value = code;
                        }
                    } else if (VisualEditorTools.pendingLineCaller === "segment") {
                        VisualEditorTools.pendingLineCaller = null;
                        document.getElementById("modalNewLine")?.classList.add("hidden");
                        const selLine = document.getElementById("newSegmentLineSelect");
                        if (selLine) {
                            selLine.innerHTML = NetworkStore.lines.map(l =>
                                `<option value="${escapeHtml(l.code)}" ${code === l.code ? "selected" : ""}>Línea ${escapeHtml(l.code)} · ${escapeHtml(l.name)}</option>`
                            ).join("");
                            selLine.value = code;
                        }
                    } else {
                        closeAllEditorModals();
                    }
                } catch (err) {
                    showToast("Error de conexión al crear línea");
                }
            });

            // 3. Envío Formulario Modal: Conectar Tramo
            document.getElementById("formCreateSegmentModal")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const lineCode = document.getElementById("newSegmentLineSelect").value;
                const fromId = parseInt(document.getElementById("newSegmentFromSelect").value);
                const toId = parseInt(document.getElementById("newSegmentToSelect").value);

                if (fromId === toId) {
                    showToast("Selecciona dos estaciones distintas para conectar el tramo");
                    return;
                }

                try {
                    const res = await ApiClient.post("/api/line-segments/create/", {
                            line_code: lineCode,
                            from_station_id: fromId,
                            to_station_id: toId
                        });
                    if (!res.ok) {
                        showToast(res.error || "Error al conectar el tramo");
                        return;
                    }
                    closeAllEditorModals();
                    await refreshNetworkDataAndRender();
                    HistoryManager.push({
                        type: "segment_create",
                        lineCode,
                        fromId,
                        toId,
                        description: `Conectar tramo en Línea ${lineCode}`
                    });
                    const msgMode = res.server ? "" : " (guardado localmente)";
                    showToast(`✓ Tramo conectado en Línea ${lineCode}${msgMode}`);
                } catch (err) {
                    showToast("Error al conectar tramo");
                }
            });

            // 4. Envío Formulario Modal: Agregar Correspondencia
            const submitCorrAction = async (stId, lineCodes) => {
                try {
                    const payload = NetworkStore.createCorrespondencePayload
                        ? NetworkStore.createCorrespondencePayload(stId, lineCodes)
                        : (Array.isArray(lineCodes)
                            ? { station_id: stId, target_line_codes: lineCodes }
                            : { station_id: stId, target_line_code: lineCodes });
                    const res = await ApiClient.post("/api/correspondences/create/", payload);
                    if (!res.ok) {
                        showToast(res.error || "Error al establecer correspondencia");
                        return;
                    }
                    const resData = res.data || res;
                    closeAllEditorModals();
                    await refreshNetworkDataAndRender();
                    this.selectStation(stId);
                    this.populateCorrespondenceSubtab();
                    const addedNames = resData.added_lines && resData.added_lines.length > 0
                        ? resData.added_lines.join(", ")
                        : (Array.isArray(lineCodes) ? lineCodes.join(", ") : lineCodes);
                    const totalCount = resData.total_lines_count || (resData.served_lines ? resData.served_lines.length : "?");
                    HistoryManager.push({
                        type: "correspondence_create",
                        stationId: stId,
                        lineCodes: Array.isArray(lineCodes) ? lineCodes : [lineCodes],
                        description: `Correspondencia Línea(s) ${addedNames} en ${resData.station_name || "estación"}`
                    });
                    const msgMode = res.server ? "" : " (guardado localmente)";
                    showToast(`✓ Correspondencia establecida con Línea(s) ${addedNames} en ${resData.station_name || "estación"} (${totalCount}/10 líneas)${msgMode}`);
                } catch (err) {
                    showToast("Error al crear correspondencia");
                }
            };

            document.getElementById("formCreateCorrModal")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const stVal = document.getElementById("modalCorrStationSelect")?.value;
                const stId = parseInt(stVal);
                if (!stId) {
                    showToast("Selecciona una estación existente");
                    return;
                }
                const checkedCbs = Array.from(document.querySelectorAll("#modalCorrLinesChecklist .js-corr-line-checkbox:checked"));
                let lineCodes = checkedCbs.map(cb => cb.value);
                if (lineCodes.length === 0) {
                    const sel = document.getElementById("modalCorrLineSelect");
                    if (sel && sel.value) {
                        lineCodes = Array.from(sel.selectedOptions).map(o => o.value).filter(Boolean);
                    }
                }
                if (lineCodes.length === 0) {
                    showToast("Selecciona al menos una línea destino para la correspondencia.");
                    return;
                }
                await submitCorrAction(stId, lineCodes);
            });

            document.getElementById("formEditCorrespondence")?.addEventListener("submit", async (e) => {
                e.preventDefault();
                const stVal = document.getElementById("corrStationSelect")?.value;
                const stId = parseInt(stVal);
                if (!stId) {
                    showToast("Elige una estación existente para la correspondencia");
                    return;
                }
                const checkedCbs = Array.from(document.querySelectorAll("#corrTargetLinesChecklist .js-corr-line-checkbox:checked"));
                let lineCodes = checkedCbs.map(cb => cb.value);
                if (lineCodes.length === 0) {
                    const sel = document.getElementById("corrTargetLineSelect");
                    if (sel && sel.value) {
                        lineCodes = Array.from(sel.selectedOptions).map(o => o.value).filter(Boolean);
                    }
                }
                if (lineCodes.length === 0) {
                    showToast("Selecciona al menos una línea destino para la correspondencia.");
                    return;
                }
                await submitCorrAction(stId, lineCodes);
            });

            document.getElementById("corrStationsList")?.addEventListener("click", async (e) => {
                const rmBtn = e.target.closest(".js-remove-corr-btn");
                if (rmBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const stId = Number(rmBtn.dataset.stationId);
                    const lineCode = rmBtn.dataset.lineCode;
                    if (!stId || !lineCode) return;
                    await this.disconnectStationFromLine(stId, lineCode);
                    return;
                }
                const stLink = e.target.closest(".js-select-corr-st");
                if (stLink) {
                    e.preventDefault();
                    e.stopPropagation();
                    const stId = Number(stLink.dataset.stationId);
                    if (stId) {
                        this.selectStation(stId);
                    }
                }
            });

            // Accesibilidad por teclado:
            // '/' enfoca el buscador
            // 'Escape' cierra modales y herramientas activas
            // 'Ctrl+Z' / 'Cmd+Z' Deshacer
            // 'Ctrl+Y' / 'Cmd+Y' / 'Ctrl+Shift+Z' Rehacer
            window.addEventListener("keydown", (e) => {
                if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
                    e.preventDefault();
                    searchInput?.focus();
                } else if (e.key === "Escape") {
                    modalAlert?.classList.add("hidden");
                    dropdown?.classList.add("hidden");
                    closeAllEditorModals();
                } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
                    if (!["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
                        e.preventDefault();
                        HistoryManager.undo();
                    }
                } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
                    if (!["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
                        e.preventDefault();
                        HistoryManager.redo();
                    }
                }
            });
        },

        updateTargetLinesForStation(stId) {
            const selLine = document.getElementById("corrTargetLineSelect");
            const checklist = document.getElementById("corrTargetLinesChecklist");
            const capacityBadge = document.getElementById("corrCapacityBadge");
            const currentLinesText = document.getElementById("corrStationCurrentLinesText");
            const submitBtn = document.getElementById("btnSubmitAddCorrespondence");

            const st = NetworkStore.stationsById.get(Number(stId));
            const served = st && Array.isArray(st.lines) ? new Set(st.lines) : new Set();
            const currentCount = served.size;
            const remainingQuota = Math.max(0, 10 - currentCount);

            if (currentLinesText && st) {
                currentLinesText.textContent = `Líneas actuales: ${st.lines.join(", ") || "Ninguna"}`;
            }
            if (capacityBadge) {
                capacityBadge.textContent = `${currentCount}/10 líneas`;
                capacityBadge.style.background = currentCount >= 10 ? "#fee2e2" : "#e2e8f0";
                capacityBadge.style.color = currentCount >= 10 ? "#b91c1c" : "#334155";
            }
            if (submitBtn) {
                submitBtn.disabled = remainingQuota <= 0;
            }

            const availableLines = NetworkStore.lines.filter(l => !served.has(l.code));
            renderCorrespondenceLinesChecklist(checklist, selLine, availableLines, remainingQuota);

            // Botones rápidas Todas / Limpiar en sidebar
            const btnAll = document.getElementById("btnSelectAllSidebarLines");
            if (btnAll && !btnAll.dataset.bound) {
                btnAll.dataset.bound = "true";
                btnAll.addEventListener("click", () => {
                    const cbs = checklist ? Array.from(checklist.querySelectorAll(".js-corr-line-checkbox")) : [];
                    let checkedSoFar = 0;
                    cbs.forEach(cb => {
                        if (checkedSoFar < remainingQuota) {
                            cb.checked = true;
                            checkedSoFar++;
                        } else {
                            cb.checked = false;
                        }
                    });
                    if (selLine) {
                        const checked = cbs.filter(c => c.checked);
                        if (checked.length === 1) {
                            selLine.value = checked[0].value;
                        } else {
                            selLine.value = "";
                        }
                    }
                });
            }

            const btnClear = document.getElementById("btnClearSidebarLines");
            if (btnClear && !btnClear.dataset.bound) {
                btnClear.dataset.bound = "true";
                btnClear.addEventListener("click", () => {
                    const cbs = checklist ? checklist.querySelectorAll(".js-corr-line-checkbox") : [];
                    cbs.forEach(cb => { cb.checked = false; });
                    if (selLine) {
                        selLine.value = "";
                    }
                });
            }
        },

        updateCorrespondenceSelectedStation(st) {
            const corrStationSel = document.getElementById("corrStationSelect");
            const modalCorrSel = document.getElementById("modalCorrStationSelect");
            if (st) {
                if (corrStationSel && corrStationSel.value !== String(st.id)) {
                    corrStationSel.value = String(st.id);
                }
                if (modalCorrSel && modalCorrSel.value !== String(st.id)) {
                    modalCorrSel.value = String(st.id);
                }
                this.updateTargetLinesForStation(st.id);
            }
        },

        populateCorrespondenceSubtab() {
            const selStation = document.getElementById("corrStationSelect");
            const listContainer = document.getElementById("corrStationsList");

            const sorted = NetworkStore.getSortedStations();
            if (selStation) {
                selStation.innerHTML = sorted.map(s => {
                    const lList = Array.isArray(s.lines) && s.lines.length > 0 ? ` (Líneas: ${s.lines.join("/")})` : "";
                    return `<option value="${s.id}">${escapeHtml(s.name)}${escapeHtml(lList)}</option>`;
                }).join("");

                const initialId = NetworkStore.selectedStationId || (sorted.length > 0 ? sorted[0].id : null);
                if (initialId) {
                    selStation.value = String(initialId);
                    this.updateTargetLinesForStation(initialId);
                }

                if (!selStation.dataset.boundChange) {
                    selStation.dataset.boundChange = "true";
                    const handleStationChange = (e) => {
                        const stId = Number(e.target.value);
                        if (stId) {
                            NetworkStore.selectedStationId = stId;
                            if (SchematicMapEngine.updateStationSelectionUI) {
                                SchematicMapEngine.updateStationSelectionUI(null, stId);
                            }
                            this.updateTargetLinesForStation(stId);
                        }
                    };
                    selStation.addEventListener("change", handleStationChange);
                    selStation.addEventListener("input", handleStationChange);
                }
            }

            if (listContainer) {
                const transferStations = NetworkStore.stations.filter(s => s.is_transfer || s.lines.length > 1);
                listContainer.innerHTML = transferStations.map(s => `
                    <div class="corr-station-chip" data-station-id="${s.id}">
                        <div class="station-name-link js-select-corr-st" style="cursor:pointer; font-weight:600;" data-station-id="${s.id}">
                            ${escapeHtml(s.name)}
                        </div>
                        <div class="corr-lines-badges">
                            ${s.lines.map(c => {
                                const ln = NetworkStore.linesByCode.get(c);
                                const bg = ln ? ln.color : "#475569";
                                const fg = getBadgeTextColor(bg, "#FFFFFF");
                                return `
                                    <span class="corr-line-badge" style="background:${bg}; color:${fg}; display:inline-flex; align-items:center; gap:4px; padding:2px 6px; border-radius:4px; margin-right:4px;">
                                        ${escapeHtml(c)}
                                        <button type="button" class="js-remove-corr-btn" data-station-id="${s.id}" data-line-code="${escapeHtml(c)}" title="Desconectar Línea ${escapeHtml(c)}" style="background:none; border:none; color:inherit; cursor:pointer; font-weight:bold; font-size:11px; padding:0; line-height:1; opacity:0.85;">×</button>
                                    </span>
                                `;
                            }).join("")}
                        </div>
                    </div>
                `).join("") || '<p style="font-size:11px; color:var(--text-muted); padding:4px;">No hay correspondencias registradas</p>';
            }
        }
    };

    // =========================================================================
    // UTILIDADES Y ARRANQUE PRINCIPAL
    // =========================================================================
    async function refreshNetworkDataAndRender(rebuildFleet = false) {
        await NetworkStore.fetchAll();
        if (rebuildFleet) {
            TrainSimulationEngine.buildFleet();
        }
        SchematicMapEngine.renderAll();
        if (NetworkStore.viewMode === "geo") {
            GeoMapEngine.renderGeoNetwork();
        }
        ControlCenterUI.renderLinesDirectory();
        ControlCenterUI.renderAlertsPanel();
        ControlCenterUI.renderMetricsTab();
        if (typeof ControlCenterUI.populateEditorSelects === "function") {
            ControlCenterUI.populateEditorSelects();
        }
    }

    function animateInspectorCard(el) {
        if (window.Motion && typeof window.Motion.animate === "function") {
            window.Motion.animate(
                el,
                { opacity: [0.3, 1], transform: ["translateY(6px)", "translateY(0px)"] },
                { duration: 0.22, easing: [0.165, 0.84, 0.44, 1] }
            );
        }
    }

    function updateClockUI() {
        const el = document.getElementById("operationalClock");
        if (el) {
            el.textContent = formatSecondsToHHMMSS(NetworkStore.operationalTimeSec);
        }
    }

    function formatSecondsToHHMMSS(totalSec) {
        const s = Math.floor(totalSec) % 86400;
        const hh = String(Math.floor(s / 3600)).padStart(2, "0");
        const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
        const ss = String(s % 60).padStart(2, "0");
        return `${hh}:${mm}:${ss}`;
    }

    function showToast(msg) {
        const container = document.getElementById("toastContainer");
        if (!container) return;
        const item = document.createElement("div");
        item.className = "toast-msg";
        item.textContent = msg;
        container.appendChild(item);
        if (window.Motion && typeof window.Motion.animate === "function") {
            window.Motion.animate(
                item,
                { opacity: [0, 1], transform: ["translateY(10px)", "translateY(0px)"] },
                { duration: 0.2 }
            );
        }
        setTimeout(() => item.remove(), 3600);
    }

    function escapeHtml(str) {
        return String(str ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    async function bootstrap() {
        try {
            await NetworkStore.fetchAll();
            TrainSimulationEngine.buildFleet();
            SchematicMapEngine.init();
            SchematicMapEngine.renderAll();
            ControlCenterUI.init();
            ApiClient.initBadgeClickHandler();
            VisualEditorTools.initActiveLinePicker();
            requestAnimationFrame((t) => TrainSimulationEngine.step(t));
        } catch (err) {
            console.error("Error inicializando SMyT:", err);
            showToast("Error cargando datos de la red. Reintenta recargar la página.");
        }
    }

    document.addEventListener("DOMContentLoaded", bootstrap);
})();
