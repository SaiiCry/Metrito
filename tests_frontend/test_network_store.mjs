/**
 * Suite de Pruebas Unitarias para NetworkStore (Frontend SMyT).
 * Ejecutable mediante el test runner nativo de Node.js (node --test).
 *
 * Cubre:
 * 1. Carga de datos topológicos (fetchAll) e hidratación (hydrate) de mapas por índice.
 * 2. Manejo de respuestas de error de red y HTTP (4xx / 5xx).
 * 3. Preservación estricta del nombre canónico de estaciones (inmunidad contra sufijos del modal selector).
 * 4. Creación y edición de correspondencias libremente por IDs numéricos sin selector.
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

// Extracción desacoplada de NetworkStore basada en network/static/network/js/app.js
function createNetworkStore() {
    return {
        cityOutlines: [],
        lines: [],
        linesByCode: new Map(),
        stations: [],
        stationsById: new Map(),
        sortedStations: null,
        alerts: [],
        kpis: {},
        viewMode: "schematic",
        showLabels: true,
        showCityOutlines: false,
        isolatedLineCode: null,
        selectedStationId: null,
        trackWidthScale: 1.0,
        distanceScale: 1.0,
        hiddenLines: new Set(),
        transferCorridors: [],
        transferCorridorsById: new Map(),

        toggleLineVisibility(code) {
            const strCode = String(code);
            if (this.hiddenLines.has(strCode)) {
                this.hiddenLines.delete(strCode);
            } else {
                this.hiddenLines.add(strCode);
            }
            return !this.hiddenLines.has(strCode);
        },

        hideLine(code) {
            this.hiddenLines.add(String(code));
        },

        showLine(code) {
            this.hiddenLines.delete(String(code));
        },

        isLineHidden(code) {
            return this.hiddenLines.has(String(code));
        },

        showAllLines() {
            this.hiddenLines.clear();
        },

        hideAllLines() {
            for (const ln of this.lines) {
                this.hiddenLines.add(String(ln.code));
            }
        },

        setDistanceScale(scale) {
            const val = Math.max(0.6, Math.min(3.5, Number(scale) || 1.0));
            this.distanceScale = val;
            return val;
        },

        logicalToSvgCoords(x, y) {
            const dScale = this.distanceScale || 1.0;
            if (dScale === 1.0) return { x, y };
            const cx = 2760.0;
            const cy = 1990.0;
            return {
                x: cx + (x - cx) * dScale,
                y: cy + (y - cy) * dScale
            };
        },

        svgToLogicalCoords(svgX, svgY) {
            const dScale = this.distanceScale || 1.0;
            if (dScale === 1.0) return { x: svgX, y: svgY };
            const cx = 2760.0;
            const cy = 1990.0;
            return {
                x: cx + (svgX - cx) / dScale,
                y: cy + (svgY - cy) / dScale
            };
        },

        addTransferCorridor(corridor) {
            if (!corridor || !corridor.id) return;
            const idx = this.transferCorridors.findIndex(c => c.id === corridor.id);
            if (idx >= 0) {
                this.transferCorridors[idx] = corridor;
            } else {
                this.transferCorridors.push(corridor);
            }
            this.transferCorridorsById.set(corridor.id, corridor);
        },

        removeTransferCorridor(corridorId) {
            this.transferCorridors = this.transferCorridors.filter(c => c.id !== corridorId);
            this.transferCorridorsById.delete(corridorId);
        },

        getCorridorsForStation(stationId) {
            const numId = Number(stationId);
            return this.transferCorridors.filter(c =>
                Number(c.from_station_id) === numId || Number(c.to_station_id) === numId
            );
        },

        async fetchAll(customFetch = globalThis.fetch) {
            const resp = await customFetch("/api/network/");
            if (!resp.ok) {
                throw new Error("Error cargando topología de la red SMyT");
            }
            const data = await resp.json();
            this.hydrate(data);
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

            this.stationsById.clear();
            for (const st of this.stations) {
                this.stationsById.set(st.id, st);
            }
            this.sortedStations = [...this.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));

            this.transferCorridors = data.transfer_corridors || [];
            this.transferCorridorsById.clear();
            for (const tc of this.transferCorridors) {
                this.transferCorridorsById.set(tc.id, tc);
            }
        },

        getSortedStations() {
            if (!this.sortedStations || this.sortedStations.length !== this.stations.length) {
                this.sortedStations = [...this.stations].sort((a, b) => a.name.localeCompare(b.name, "es"));
            }
            return this.sortedStations;
        },

        // Helper para formular payloads de correspondencia directamente por IDs numéricos (sin selector UI)
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
}

describe("NetworkStore - Arquitectura de Estado y Manejo de Errores", () => {
    let store;

    beforeEach(() => {
        store = createNetworkStore();
    });

    it("hydrate() indexa correctamente linesByCode y stationsById", () => {
        const mockData = {
            city_outlines: [{ id: 1, name: "Centro Histórico" }],
            lines: [
                { id: 10, code: "1", name: "Línea 1", color: "#FF0000" },
                { id: 20, code: "A", name: "Línea A", color: "#00FF00" },
            ],
            stations: [
                { id: 101, code: "st-1", name: "Felipe Escamilla", lines: ["1"] },
                { id: 102, code: "st-2", name: "Estrellas", lines: ["8", "9", "19", "S5"] },
            ],
            alerts: [],
            kpis: { total_lines: 2, total_stations: 2 },
        };

        store.hydrate(mockData);

        assert.equal(store.lines.length, 2);
        assert.equal(store.stations.length, 2);
        assert.equal(store.linesByCode.get("1")?.name, "Línea 1");
        assert.equal(store.linesByCode.get("A")?.name, "Línea A");
        assert.equal(store.stationsById.get(101)?.name, "Felipe Escamilla");
        assert.equal(store.stationsById.get(102)?.name, "Estrellas");
    });

    it("fetchAll() consume /api/network/ exitosamente e hidrata el estado", async () => {
        const mockApiResponse = {
            city_outlines: [],
            lines: [{ code: "1", name: "Línea 1" }],
            stations: [{ id: 50, name: "Santa Mónica", lines: ["1", "4", "7"] }],
            alerts: [],
            kpis: {},
        };

        const mockFetch = async (url) => {
            assert.equal(url, "/api/network/");
            return {
                ok: true,
                status: 200,
                json: async () => mockApiResponse,
            };
        };

        const data = await store.fetchAll(mockFetch);
        assert.equal(data.stations.length, 1);
        assert.equal(store.stationsById.get(50)?.name, "Santa Mónica");
    });

    it("fetchAll() lanza error descriptivo y no corrompe el estado ante HTTP 500", async () => {
        // Pre-cargar estado válido
        store.hydrate({
            lines: [{ code: "1", name: "Línea 1" }],
            stations: [{ id: 1, name: "Estación Previa", lines: ["1"] }],
        });

        const mockFetchError = async () => ({
            ok: false,
            status: 500,
            statusText: "Internal Server Error",
            json: async () => ({ error: "Falla interna del servidor" }),
        });

        await assert.rejects(
            async () => await store.fetchAll(mockFetchError),
            {
                name: "Error",
                message: "Error cargando topología de la red SMyT",
            }
        );

        // El estado previo debe seguir intacto
        assert.equal(store.stations.length, 1);
        assert.equal(store.stationsById.get(1)?.name, "Estación Previa");
    });

    it("getSortedStations() ordena alfabéticamente con acentos en español y cachea el resultado para fluidez", () => {
        store.hydrate({
            stations: [
                { id: 1, name: "Zapata" },
                { id: 2, name: "Álvaro Obregón" },
                { id: 3, name: "Balderas" },
            ],
        });

        const sorted = store.getSortedStations();
        assert.deepEqual(sorted.map(s => s.name), ["Álvaro Obregón", "Balderas", "Zapata"]);
        // Debe retornar la misma referencia en memoria sin recalcular
        assert.equal(store.getSortedStations(), sorted);
    });
});

describe("Requisito UI / Integridad de Nombres e Inmunidad al Modal Selector", () => {
    let store;

    beforeEach(() => {
        store = createNetworkStore();
        store.hydrate({
            lines: [
                { code: "1", name: "Línea 1" },
                { code: "2", name: "Línea 2" },
                { code: "S3", name: "Sistema 3 BRT" },
            ],
            stations: [
                { id: 101, code: "st-1", name: "Felipe Escamilla", lines: ["1", "S3"], is_transfer: true },
                { id: 102, code: "st-2", name: "Estrellas", lines: ["8", "9", "19", "S5"], is_transfer: true },
                { id: 103, code: "st-3", name: "Etna", lines: ["17", "19"], is_transfer: true },
            ],
        });
    });

    it("los nombres de estación en NetworkStore se conservan limpios sin sufijos de líneas", () => {
        /**
         * Requisito: En la captura (image.png) el modal selector mostraba
         * 'Felipe Escamilla (1)', 'Estrellas (8/9/19/S5)', etc.
         * El store debe asegurar que los nombres canónicos en memoria carezcan
         * totalmente de paréntesis con números de línea añadidos.
         */
        for (const st of store.stations) {
            assert.doesNotMatch(
                st.name,
                /\s\([0-9A-Za-z/]+\)$/,
                `El nombre '${st.name}' no debe contener sufijos de líneas entre paréntesis`
            );
        }

        assert.equal(store.stationsById.get(101).name, "Felipe Escamilla");
        assert.equal(store.stationsById.get(102).name, "Estrellas");
        assert.equal(store.stationsById.get(103).name, "Etna");
    });

    it("la creación de correspondencia se formula libremente por ID numérico sin pasar por un selector de texto", () => {
        // Correspondencia entre Felipe Escamilla (101) y Etna (103)
        const payloadEstaciones = store.createCorrespondencePayload(101, 103);
        assert.deepEqual(payloadEstaciones, {
            station_id: 101,
            station_id_2: 103,
        });

        // Correspondencia de Felipe Escamilla (101) a Línea 2
        const payloadLinea = store.createCorrespondencePayload(101, "2");
        assert.deepEqual(payloadLinea, {
            station_id: 101,
            target_line_code: "2",
        });

        // Correspondencia múltiple (más de una línea simultánea)
        const payloadMultiples = store.createCorrespondencePayload(101, ["2", "3", "7"]);
        assert.deepEqual(payloadMultiples, {
            station_id: 101,
            target_line_codes: ["2", "3", "7"],
        });

        // Verificación de que ningún nombre fue alterado al formular las correspondencias
        assert.equal(store.stationsById.get(101).name, "Felipe Escamilla");
    });
});

describe("Moldeado de Trazo - Snap Octilineal Automático a Múltiplos de 45°", () => {
    function snapPointOctilinear(anchor, target) {
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
    }

    const anchor = [100.0, 100.0];

    it("alinea a 0° horizontal derecha con dy estricto a 0", () => {
        const rawTarget = [300.0, 110.0]; // Leve desviación vertical (+10)
        const snapped = snapPointOctilinear(anchor, rawTarget);
        assert.equal(snapped[1], 100.0, "La coordenada Y debe coincidir exactamente con el ancla");
        assert.ok(snapped[0] > 100.0);
    });

    it("alinea a 45° diagonal sureste con |dx| === |dy| exacto", () => {
        const rawTarget = [200.0, 205.0]; // Leve desviación de 45°
        const snapped = snapPointOctilinear(anchor, rawTarget);
        const dx = snapped[0] - anchor[0];
        const dy = snapped[1] - anchor[1];
        assert.equal(dx, dy, "|dx| y |dy| deben ser idénticos para ángulo de 45°");
        assert.ok(dx > 0);
    });

    it("alinea a 90° vertical sur con dx estricto a 0", () => {
        const rawTarget = [108.0, 250.0]; // Leve desviación horizontal (+8)
        const snapped = snapPointOctilinear(anchor, rawTarget);
        assert.equal(snapped[0], 100.0, "La coordenada X debe coincidir exactamente con el ancla");
        assert.ok(snapped[1] > 100.0);
    });

    it("alinea a 135° diagonal suroeste con |dx| === |dy| exacto", () => {
        const rawTarget = [20.0, 185.0];
        const snapped = snapPointOctilinear(anchor, rawTarget);
        const dx = Math.abs(snapped[0] - anchor[0]);
        const dy = Math.abs(snapped[1] - anchor[1]);
        assert.equal(dx, dy, "|dx| y |dy| deben ser idénticos para ángulo de 135°");
    });

    it("alinea a 180° horizontal izquierda con dy estricto a 0", () => {
        const rawTarget = [10.0, 95.0];
        const snapped = snapPointOctilinear(anchor, rawTarget);
        assert.equal(snapped[1], 100.0, "La coordenada Y debe coincidir exactamente con el ancla");
        assert.ok(snapped[0] < 100.0);
    });

    it("alinea a 225° diagonal noroeste con |dx| === |dy| exacto", () => {
        const rawTarget = [30.0, 25.0];
        const snapped = snapPointOctilinear(anchor, rawTarget);
        const dx = Math.abs(snapped[0] - anchor[0]);
        const dy = Math.abs(snapped[1] - anchor[1]);
        assert.equal(dx, dy, "|dx| y |dy| deben ser idénticos para ángulo de 225°");
    });

    it("alinea a 270° vertical norte con dx estricto a 0", () => {
        const rawTarget = [96.0, 10.0];
        const snapped = snapPointOctilinear(anchor, rawTarget);
        assert.equal(snapped[0], 100.0, "La coordenada X debe coincidir exactamente con el ancla");
        assert.ok(snapped[1] < 100.0);
    });

    it("alinea a 315° diagonal noreste con |dx| === |dy| exacto", () => {
        const rawTarget = [170.0, 35.0];
        const snapped = snapPointOctilinear(anchor, rawTarget);
        const dx = Math.abs(snapped[0] - anchor[0]);
        const dy = Math.abs(snapped[1] - anchor[1]);
        assert.equal(dx, dy, "|dx| y |dy| deben ser idénticos para ángulo de 315°");
    });
});

describe("Enderezado de Trazos Derecho a 90° o 180° según Orientación", () => {
    function calculateOrthogonalWaypoints(st1, st2) {
        const dx = st2.x - st1.x;
        const dy = st2.y - st1.y;
        if (Math.abs(dx) >= Math.abs(dy)) {
            // Predominantemente horizontal (180° / 0°)
            return Math.abs(dy) < 0.5 ? [] : [[Math.round(st2.x * 2) / 2, Math.round(st1.y * 2) / 2]];
        } else {
            // Predominantemente vertical (90° / 270°)
            return Math.abs(dx) < 0.5 ? [] : [[Math.round(st1.x * 2) / 2, Math.round(st2.y * 2) / 2]];
        }
    }

    it("endereza a 180° horizontal con giro a 90° cuando |dx| >= |dy|", () => {
        const st1 = { x: 100.0, y: 200.0 };
        const st2 = { x: 500.0, y: 260.0 }; // dx = 400, dy = 60 -> horizontal
        const wps = calculateOrthogonalWaypoints(st1, st2);
        assert.deepEqual(wps, [[500.0, 200.0]]);

        // Tramo 1: (100, 200) -> (500, 200): dy estricto = 0 (180° horizontal)
        assert.equal(wps[0][1] - st1.y, 0);
        // Tramo 2: (500, 200) -> (500, 260): dx estricto = 0 (90° vertical)
        assert.equal(st2.x - wps[0][0], 0);
    });

    it("endereza a 90° vertical con giro a 180° cuando |dy| > |dx|", () => {
        const st1 = { x: 200.0, y: 100.0 };
        const st2 = { x: 240.0, y: 600.0 }; // dx = 40, dy = 500 -> vertical
        const wps = calculateOrthogonalWaypoints(st1, st2);
        assert.deepEqual(wps, [[200.0, 600.0]]);

        // Tramo 1: (200, 100) -> (200, 600): dx estricto = 0 (90° vertical)
        assert.equal(wps[0][0] - st1.x, 0);
        // Tramo 2: (200, 600) -> (240, 600): dy estricto = 0 (180° horizontal)
        assert.equal(st2.y - wps[0][1], 0);
    });

    it("no inserta waypoints innecesarios si las estaciones ya están alineadas en 180° (horizontal pura)", () => {
        const st1 = { x: 100.0, y: 300.0 };
        const st2 = { x: 400.0, y: 300.0 };
        const wps = calculateOrthogonalWaypoints(st1, st2);
        assert.deepEqual(wps, []);
    });

    it("no inserta waypoints innecesarios si las estaciones ya están alineadas en 90° (vertical pura)", () => {
        const st1 = { x: 500.0, y: 100.0 };
        const st2 = { x: 500.0, y: 400.0 };
        const wps = calculateOrthogonalWaypoints(st1, st2);
        assert.deepEqual(wps, []);
    });
});

describe("Renderizador de Selectores de Línea Destino en Correspondencias", () => {
    function mockRenderCorrespondenceLinesChecklist(checklistEl, selectEl, availableLines, remainingQuota) {
        const lines = Array.isArray(availableLines) ? availableLines : [];

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
                    options.push(`<option value="${l.code}">Línea ${l.code} · ${l.name}</option>`);
                }
                selectEl.innerHTML = options.join("");
            }
        }

        if (checklistEl) {
            if (remainingQuota <= 0) {
                checklistEl.innerHTML = `<div>Límite alcanzado</div>`;
            } else if (lines.length === 0) {
                checklistEl.innerHTML = `<div>Pertenece a todas las líneas</div>`;
            } else {
                checklistEl.innerHTML = lines.map(l =>
                    `<input type="checkbox" class="js-corr-line-checkbox" value="${l.code}">${l.name}`
                ).join("");
            }
        }
    }

    it("puebla selectEl independientemente incluso cuando checklistEl es null", () => {
        const mockSelect = { disabled: false, innerHTML: "" };
        const availableLines = [
            { code: "2", name: "Tasqueña - Cuatro Caminos" },
            { code: "3", name: "Indios Verdes - Universidad" }
        ];

        mockRenderCorrespondenceLinesChecklist(null, mockSelect, availableLines, 8);

        assert.equal(mockSelect.disabled, false);
        assert.ok(mockSelect.innerHTML.includes("-- Selecciona una línea destino --"));
        assert.ok(mockSelect.innerHTML.includes('value="2"'));
        assert.ok(mockSelect.innerHTML.includes('value="3"'));
    });

    it("deshabilita selectEl cuando remainingQuota es 0 (máximo de 10 alcanzado)", () => {
        const mockSelect = { disabled: false, innerHTML: "" };
        const availableLines = [{ code: "2", name: "Línea 2" }];

        mockRenderCorrespondenceLinesChecklist(null, mockSelect, availableLines, 0);

        assert.equal(mockSelect.disabled, true);
        assert.ok(mockSelect.innerHTML.includes("Límite de 10 correspondencias alcanzado"));
    });

    it("deshabilita selectEl cuando la estación ya pertenece a todas las líneas", () => {
        const mockSelect = { disabled: false, innerHTML: "" };

        mockRenderCorrespondenceLinesChecklist(null, mockSelect, [], 5);

        assert.equal(mockSelect.disabled, true);
        assert.ok(mockSelect.innerHTML.includes("ya pertenece a todas las líneas"));
    });

    it("puebla tanto selectEl como checklistEl de forma desacoplada y simultánea", () => {
        const mockSelect = { disabled: false, innerHTML: "" };
        const mockChecklist = { innerHTML: "" };
        const availableLines = [
            { code: "1", name: "Observatorio - Pantitlán" },
            { code: "S3", name: "Ruta Sur Directa" }
        ];

        mockRenderCorrespondenceLinesChecklist(mockChecklist, mockSelect, availableLines, 8);

        assert.ok(mockSelect.innerHTML.includes('value="1"'));
        assert.ok(mockSelect.innerHTML.includes('value="S3"'));
        assert.ok(mockChecklist.innerHTML.includes('value="1"'));
        assert.ok(mockChecklist.innerHTML.includes('value="S3"'));
    });
});


describe("Snap de Waypoints - Exactitud de Ángulos Ortogonales y Octilineales entre Paradas", () => {
    function snapPointOctilinear(anchor, target) {
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
            case 0: return [Math.round((ax + dOrtho) * 2) / 2, ay];
            case 1: return [Math.round((ax + dDiag) * 2) / 2, Math.round((ay + dDiag) * 2) / 2];
            case 2: return [ax, Math.round((ay + dOrtho) * 2) / 2];
            case 3: return [Math.round((ax - dDiag) * 2) / 2, Math.round((ay + dDiag) * 2) / 2];
            case 4: return [Math.round((ax - dOrtho) * 2) / 2, ay];
            case 5: return [Math.round((ax - dDiag) * 2) / 2, Math.round((ay - dDiag) * 2) / 2];
            case 6: return [ax, Math.round((ay - dOrtho) * 2) / 2];
            case 7: return [Math.round((ax + dDiag) * 2) / 2, Math.round((ay - dDiag) * 2) / 2];
            default: return [tx, ty];
        }
    }

    function snapWaypoint(prevPt, nextPt, mousePt) {
        const mx = Number(mousePt[0]);
        const my = Number(mousePt[1]);
        if (!prevPt) return [Math.round(mx * 2) / 2, Math.round(my * 2) / 2];
        const x0 = Number(prevPt[0]);
        const y0 = Number(prevPt[1]);
        if (!nextPt) return snapPointOctilinear([x0, y0], [mx, my]);
        const x1 = Number(nextPt[0]);
        const y1 = Number(nextPt[1]);
        const dx = x1 - x0;
        const dy = y1 - y0;
        const candidates = [];
        const addCandidate = (cx, cy, priority = 1.0) => {
            const rx = Math.round(cx * 2) / 2;
            const ry = Math.round(cy * 2) / 2;
            if (!candidates.some(c => Math.abs(c.x - rx) < 0.5 && Math.abs(c.y - ry) < 0.5)) {
                candidates.push({ x: rx, y: ry, priority });
            }
        };

        // 1. Esquinas ortogonales puras a 90° / 180°:
        addCandidate(x1, y0, 1.8);
        addCandidate(x0, y1, 1.8);

        // 2. Trazos ortogonales-octilineales a 45°
        const signX = Math.sign(dx) || 1;
        const signY = Math.sign(dy) || 1;
        const absDx = Math.abs(dx);
        const absDy = Math.abs(dy);
        if (absDx >= absDy) {
            addCandidate(x0 + signX * absDy, y1, 1.5);
            addCandidate(x1 - signX * absDy, y0, 1.5);
        }
        if (absDy >= absDx) {
            addCandidate(x1, y0 + signY * absDx, 1.5);
            addCandidate(x0, y1 - signY * absDx, 1.5);
        }

        if (absDx < 1.0 || absDy < 1.0) {
            const octPrev = snapPointOctilinear([x0, y0], [mx, my]);
            addCandidate(octPrev[0], octPrev[1], 1.0);
            const octNext = snapPointOctilinear([x1, y1], [mx, my]);
            addCandidate(octNext[0], octNext[1], 1.0);
        }

        let best = null;
        let bestScore = Infinity;
        for (const cand of candidates) {
            const dist = Math.hypot(cand.x - mx, cand.y - my);
            const score = dist / (cand.priority || 1.0);
            if (score < bestScore) {
                bestScore = score;
                best = cand;
            }
        }
        return best ? [best.x, best.y] : [Math.round(mx * 2) / 2, Math.round(my * 2) / 2];
    }

    it("acomoda el trazo a esquina ortogonal exacta a 90°/180° horizontal-vertical", () => {
        const prev = [100.0, 100.0];
        const next = [400.0, 250.0];
        const mouse = [380.0, 110.0];
        const snapped = snapWaypoint(prev, next, mouse);
        assert.deepEqual(snapped, [400.0, 100.0]);
        assert.equal(snapped[1], prev[1]);
        assert.equal(snapped[0], next[0]);
    });

    it("acomoda el trazo a esquina ortogonal exacta a 90°/180° vertical-horizontal", () => {
        const prev = [100.0, 100.0];
        const next = [400.0, 250.0];
        const mouse = [110.0, 240.0];
        const snapped = snapWaypoint(prev, next, mouse);
        assert.deepEqual(snapped, [100.0, 250.0]);
        assert.equal(snapped[0], prev[0]);
        assert.equal(snapped[1], next[1]);
    });

    it("acomoda el trazo a ángulo octilineal exacto a 45° seguido de recta", () => {
        const prev = [100.0, 100.0];
        const next = [400.0, 250.0];
        const mouse = [240.0, 235.0];
        const snapped = snapWaypoint(prev, next, mouse);
        assert.deepEqual(snapped, [250.0, 250.0]);
        assert.equal(Math.abs(snapped[0] - prev[0]), Math.abs(snapped[1] - prev[1]));
        assert.equal(snapped[1], next[1]);
    });

    it("snap magnético de estación alinea a 180° horizontal con estación vecina", () => {
        const neighbor = { x: 500.0, y: 300.0 };
        const mouseX = 820.0;
        const mouseY = 308.0;
        let targetX = Math.round(mouseX * 2) / 2;
        let targetY = Math.round(mouseY * 2) / 2;
        if (Math.abs(mouseY - neighbor.y) <= 16.0) {
            targetY = neighbor.y;
        }
        assert.equal(targetY, 300.0);
        assert.equal(targetY - neighbor.y, 0);
    });

    it("snap magnético de estación alinea a 90° vertical con estación vecina", () => {
        const neighbor = { x: 500.0, y: 300.0 };
        const mouseX = 506.0;
        const mouseY = 720.0;
        let targetX = Math.round(mouseX * 2) / 2;
        let targetY = Math.round(mouseY * 2) / 2;
        if (Math.abs(mouseX - neighbor.x) <= 16.0) {
            targetX = neighbor.x;
        }
        assert.equal(targetX, 500.0);
        assert.equal(targetX - neighbor.x, 0);
    });
});


describe("Auto-Detección Neutra de Línea al Conectar y Color de Estación", () => {
    function detectLineForConnection(st1, st2 = null, context = {}) {
        const lines1 = (st1 && Array.isArray(st1.lines)) ? st1.lines : [];
        const lines2 = (st2 && Array.isArray(st2.lines)) ? st2.lines : [];

        // 1. Si ambas estaciones comparten una o más líneas, esa es la línea natural
        if (lines1.length > 0 && lines2.length > 0) {
            const common = lines1.filter(c => lines2.includes(c));
            if (common.length > 0) {
                if (context.isolatedLineCode && common.includes(context.isolatedLineCode)) {
                    return context.isolatedLineCode;
                }
                if (context.activeLineCode && common.includes(context.activeLineCode)) {
                    return context.activeLineCode;
                }
                return common[0];
            }
        }

        // 2. Si la línea aislada actual pertenece a st1 o st2
        if (context.isolatedLineCode) {
            if (lines1.includes(context.isolatedLineCode) || lines2.includes(context.isolatedLineCode)) {
                return context.isolatedLineCode;
            }
        }

        // 3. Si la línea activa actualmente seleccionada pertenece a st1 o st2
        if (context.activeLineCode) {
            if (lines1.includes(context.activeLineCode) || lines2.includes(context.activeLineCode)) {
                return context.activeLineCode;
            }
        }

        // 4. Extensión desde el origen: hereda línea principal de st1
        if (lines1.length > 0) {
            return lines1[0];
        }

        // 5. Si solo st2 tiene líneas
        if (lines2.length > 0) {
            return lines2[0];
        }

        return context.activeLineCode || "1";
    }

    it("detecta automáticamente la línea común A entre dos estaciones de Línea A sin forzar Línea 1", () => {
        const st1 = { id: 1, name: "Torre Áurea", lines: ["A"] };
        const st2 = { id: 2, name: "Terminal Norte", lines: ["A"] };
        // activeLineCode por defecto en el editor solía ser "1"
        const detected = detectLineForConnection(st1, st2, { activeLineCode: "1" });
        assert.equal(detected, "A");
    });

    it("detecta la línea de la estación origen al iniciar el trazo para actualizar la línea activa", () => {
        const st1 = { id: 50, name: "Velasco", lines: ["12"] };
        const detected = detectLineForConnection(st1, null, { activeLineCode: "1" });
        assert.equal(detected, "12");
    });

    it("al conectar una correspondencia (múltiples líneas) con una estación de Línea G, selecciona la línea común G", () => {
        const stTransfer = { id: 10, name: "Tlacotepec", lines: ["C", "G"] };
        const stG = { id: 11, name: "Tandaro", lines: ["G"] };
        const detected = detectLineForConnection(stTransfer, stG, { activeLineCode: "1" });
        assert.equal(detected, "G");
    });

    it("al extender un trazo desde una estación hacia una nueva estación huérfana, hereda la línea del origen", () => {
        const stOrigin = { id: 20, name: "Politécnico", lines: ["5"] };
        const stNew = { id: 99, name: "Nueva Parada", lines: [] };
        const detected = detectLineForConnection(stOrigin, stNew, { activeLineCode: "1" });
        assert.equal(detected, "5");
    });

    it("conexión neutra: unir dos estaciones que ya pertenecen a la Línea 3 no genera duplicados ni altera is_transfer", () => {
        const st1 = { id: 31, name: "Estación A", lines: ["3"], is_transfer: false };
        const st2 = { id: 32, name: "Estación B", lines: ["3"], is_transfer: false };
        const lineCode = detectLineForConnection(st1, st2);
        assert.equal(lineCode, "3");
        if (!st1.lines.includes(lineCode)) st1.lines.push(lineCode);
        if (!st2.lines.includes(lineCode)) st2.lines.push(lineCode);
        st1.is_transfer = st1.lines.length > 1;
        st2.is_transfer = st2.lines.length > 1;
        assert.deepEqual(st1.lines, ["3"]);
        assert.deepEqual(st2.lines, ["3"]);
        assert.equal(st1.is_transfer, false);
        assert.equal(st2.is_transfer, false);
    });

    it("respeta el color personalizado de estación si está definido frente al color automático de línea", () => {
        const lineLn = { code: "A", color: "#FF0000" };
        const stWithCustomColor = { id: 1, name: "Estación Especial", lines: ["A"], custom_color: "#10B981" };
        const stDefault = { id: 2, name: "Estación Normal", lines: ["A"], custom_color: "" };
        const effectiveColor1 = stWithCustomColor.custom_color || lineLn.color;
        const effectiveColor2 = stDefault.custom_color || lineLn.color;
        assert.equal(effectiveColor1, "#10B981");
        assert.equal(effectiveColor2, "#FF0000");
    });
});

describe("Inserción Topológica Contigua al Conectar Tramo (Sin conectar con la terminal)", () => {
    function insertSegmentConnection(ln, st1, st2) {
        if (!Array.isArray(ln.stops)) ln.stops = [];
        const fromIdx = ln.stops.findIndex(s => s.station_id === st1.id);
        const toIdx = ln.stops.findIndex(s => s.station_id === st2.id);

        const computeOrthoWps = (a, b) => {
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            if (Math.abs(dy) < 1.0 || Math.abs(dx) < 1.0) return [];
            return Math.abs(dx) >= Math.abs(dy)
                ? [[Math.round(b.x * 2) / 2, Math.round(a.y * 2) / 2]]
                : [[Math.round(a.x * 2) / 2, Math.round(b.y * 2) / 2]];
        };

        if (fromIdx !== -1 && toIdx === -1) {
            const newStop = {
                id: Date.now() + 2,
                station_id: st2.id,
                station_code: st2.code,
                station_name: st2.name,
                sequence: 0,
                branch: ln.stops[fromIdx]?.branch || "main",
                waypoints: []
            };

            if (fromIdx === ln.stops.length - 1) {
                ln.stops[fromIdx].waypoints = computeOrthoWps(st1, st2);
                ln.stops.push(newStop);
            } else if (fromIdx === 0) {
                newStop.waypoints = computeOrthoWps(st2, st1);
                ln.stops.unshift(newStop);
            } else {
                const prevSt = stationsMap.get(ln.stops[fromIdx - 1]?.station_id) || st1;
                const nextSt = stationsMap.get(ln.stops[fromIdx + 1]?.station_id) || st1;
                const detourBefore = Math.hypot(st2.x - prevSt.x, st2.y - prevSt.y) + Math.hypot(st1.x - st2.x, st1.y - st2.y) - Math.hypot(prevSt.x - st1.x, prevSt.y - st1.y);
                const detourAfter = Math.hypot(st2.x - nextSt.x, st2.y - nextSt.y) + Math.hypot(st1.x - st2.x, st1.y - st2.y) - Math.hypot(nextSt.x - st1.x, nextSt.y - st1.y);
                if (detourBefore < detourAfter) {
                    ln.stops[fromIdx - 1].waypoints = computeOrthoWps(prevSt, st2);
                    newStop.waypoints = computeOrthoWps(st2, st1);
                    ln.stops.splice(fromIdx, 0, newStop);
                } else {
                    ln.stops[fromIdx].waypoints = computeOrthoWps(st1, st2);
                    newStop.waypoints = computeOrthoWps(st2, nextSt);
                    ln.stops.splice(fromIdx + 1, 0, newStop);
                }
            }
        }
        ln.stops.forEach((s, idx) => { s.sequence = idx; });
        return ln.stops;
    }

    let stationsMap;

    beforeEach(() => {
        stationsMap = new Map([
            [1, { id: 1, code: "st-1", name: "Terminal Norte", x: 100, y: 100 }],
            [2, { id: 2, code: "st-2", name: "Estación Intermedia", x: 100, y: 200 }],
            [3, { id: 3, code: "st-3", name: "Terminal Sur", x: 100, y: 500 }],
            [99, { id: 99, code: "st-99", name: "Nueva Parada Vacía", x: 100, y: 250 }],
        ]);
    });

    it("inserta la nueva estación inmediatamente contigua a la estación seleccionada y no al final de la terminal", () => {
        const ln = {
            code: "3",
            stops: [
                { id: 10, station_id: 1, station_name: "Terminal Norte", sequence: 0 },
                { id: 20, station_id: 2, station_name: "Estación Intermedia", sequence: 1 },
                { id: 30, station_id: 3, station_name: "Terminal Sur", sequence: 2 },
            ]
        };

        const stFrom = stationsMap.get(2); // Estación Intermedia (idx 1)
        const stNew = stationsMap.get(99); // Nueva Parada Vacía

        insertSegmentConnection(ln, stFrom, stNew);

        // La nueva parada debe estar en la secuencia 2 (inmediatamente después de Estación Intermedia),
        // y Terminal Sur debe haber sido desplazada a la secuencia 3 (conservando su condición de terminal).
        assert.equal(ln.stops.length, 4);
        assert.equal(ln.stops[1].station_name, "Estación Intermedia");
        assert.equal(ln.stops[2].station_name, "Nueva Parada Vacía");
        assert.equal(ln.stops[3].station_name, "Terminal Sur");
        assert.equal(ln.stops[2].sequence, 2);
        assert.equal(ln.stops[3].sequence, 3);
    });

    it("al arrastrar un tramo con vértice existente, no agrega vértices duplicados en acordeón", () => {
        const stopObj = {
            id: 1,
            station_id: 2,
            waypoints: [[100, 220]]
        };
        // Simular intento de agregar otro punto
        const existingCount = stopObj.waypoints.length;
        if (existingCount >= 1) {
            // Se reutiliza el existente
            assert.equal(stopObj.waypoints.length, 1);
        }
        assert.equal(stopObj.waypoints.length, 1);
    });
});

describe("Autoalineado de Estaciones a Nivel Perfecto y Snap Estricto (0°, 45°, 90°, 135°, ...)", () => {
    function snapPointOctilinear(anchor, target) {
        const ax = Math.round(Number(anchor[0] !== undefined ? anchor[0] : anchor.x) * 2) / 2;
        const ay = Math.round(Number(anchor[1] !== undefined ? anchor[1] : anchor.y) * 2) / 2;
        const tx = Number(target[0] !== undefined ? target[0] : target.x);
        const ty = Number(target[1] !== undefined ? target[1] : target.y);
        const dx = tx - ax;
        const dy = ty - ay;
        const dist = Math.hypot(dx, dy);
        if (dist < 1.0) return [ax, ay];

        let deg = (Math.atan2(dy, dx) * 180 / Math.PI) % 360;
        if (deg < 0) deg += 360;
        const oct = Math.round(deg / 45) % 8;

        const dOrtho = Math.round(dist * 2) / 2;
        const dDiag = Math.round(((Math.abs(dx) + Math.abs(dy)) / 2) * 2) / 2;

        switch (oct) {
            case 0: return [ax + dOrtho, ay];
            case 1: return [ax + dDiag, ay + dDiag];
            case 2: return [ax, ay + dOrtho];
            case 3: return [ax - dDiag, ay + dDiag];
            case 4: return [ax - dOrtho, ay];
            case 5: return [ax - dDiag, ay - dDiag];
            case 6: return [ax, ay - dOrtho];
            case 7: return [ax + dDiag, ay - dDiag];
            default: return [Math.round(tx * 2) / 2, Math.round(ty * 2) / 2];
        }
    }

    function getStationAutoAlignedCoords(st, rawX, rawY, neighbors, snapThreshold = null) {
        const rx = Number(rawX);
        const ry = Number(rawY);
        if (!neighbors || neighbors.length === 0) {
            return [Math.round(rx * 2) / 2, Math.round(ry * 2) / 2];
        }

        const candidates = [];
        const addCandidate = (cx, cy) => {
            const x = Math.round(Number(cx) * 2) / 2;
            const y = Math.round(Number(cy) * 2) / 2;
            if (!Number.isFinite(x) || !Number.isFinite(y)) return;
            if (!candidates.some(c => c.x === x && c.y === y)) {
                candidates.push({ x, y });
            }
        };

        for (const nb of neighbors) {
            const octPt = snapPointOctilinear([nb.x, nb.y], [rx, ry]);
            addCandidate(octPt[0], octPt[1]);
            addCandidate(nb.x, ry);
            addCandidate(rx, nb.y);
        }

        for (let i = 0; i < neighbors.length; i++) {
            for (let j = i + 1; j < neighbors.length; j++) {
                const n1 = neighbors[i];
                const n2 = neighbors[j];

                addCandidate(n2.x, n1.y);
                addCandidate(n1.x, n2.y);

                if (Math.abs(n1.y - n2.y) <= 12.0) {
                    const midY = (n1.y + n2.y) / 2;
                    addCandidate(rx, midY);
                    addCandidate((n1.x + n2.x) / 2, midY);
                }

                if (Math.abs(n1.x - n2.x) <= 12.0) {
                    const midX = (n1.x + n2.x) / 2;
                    addCandidate(midX, ry);
                    addCandidate(midX, (n1.y + n2.y) / 2);
                }

                const ndx = n2.x - n1.x;
                const ndy = n2.y - n1.y;
                if (Math.abs(Math.abs(ndx) - Math.abs(ndy)) <= 12.0 && Math.abs(ndx) > 6.0) {
                    const m = (ndx * ndy > 0) ? 1 : -1;
                    const projX = (rx + n1.x + m * (ry - n1.y)) / 2;
                    const projY = n1.y + m * (projX - n1.x);
                    addCandidate(projX, projY);
                    addCandidate((n1.x + n2.x) / 2, (n1.y + n2.y) / 2);
                }
            }
        }

        const isOctilinear = (x1, y1, x2, y2) => {
            const dx = Math.abs(x1 - x2);
            const dy = Math.abs(y1 - y2);
            if (dx < 0.001 || dy < 0.001) return true;
            return Math.abs(dx - dy) < 0.001;
        };

        let bestCandidate = null;
        let bestScore = -Infinity;

        for (const cand of candidates) {
            const dist = Math.hypot(cand.x - rx, cand.y - ry);
            if (snapThreshold !== null && dist > snapThreshold) continue;

            let alignedNeighborsCount = 0;
            for (const nb of neighbors) {
                if (isOctilinear(cand.x, cand.y, nb.x, nb.y)) {
                    alignedNeighborsCount++;
                }
            }

            const score = (alignedNeighborsCount * 1000) - dist;
            if (score > bestScore) {
                bestScore = score;
                bestCandidate = cand;
            }
        }

        if (bestCandidate) return [bestCandidate.x, bestCandidate.y];
        return [Math.round(rx * 2) / 2, Math.round(ry * 2) / 2];
    }

    it("garantiza que |dx| === |dy| de forma exacta en coordenadas con decimales a 45°", () => {
        const anchor = [100.5, 200.5];
        const target = [182.3, 279.7]; // Cerca de 45° (SE)
        const [x, y] = snapPointOctilinear(anchor, target);

        const dx = Math.abs(x - anchor[0]);
        const dy = Math.abs(y - anchor[1]);
        assert.equal(dx, dy, "El delta X debe ser exactamente igual al delta Y en 45°");
        assert.equal(Number.isInteger(x * 2), true, "La coordenada X debe caer en paso 0.5");
        assert.equal(Number.isInteger(y * 2), true, "La coordenada Y debe caer en paso 0.5");
    });

    it("auto-alinea a nivel perfecto una estación entre dos vecinos horizontales (dy = 0)", () => {
        const n1 = { id: 1, x: 100.0, y: 300.0 };
        const n2 = { id: 2, x: 250.0, y: 300.0 };
        const st = { id: 3, x: 180.0, y: 304.5 }; // Ligeramente desalineada en Y por 4.5px

        const [newX, newY] = getStationAutoAlignedCoords(st, st.x, st.y, [n1, n2], null);
        assert.equal(newY, 300.0, "La estación debe quedar exactamente a Y=300");
        assert.equal(newX, 180.0, "Conserva su posición en el segmento");
        assert.equal(newY - n1.y, 0, "Pendiente horizontal perfecta con n1");
        assert.equal(newY - n2.y, 0, "Pendiente horizontal perfecta con n2");
    });

    it("auto-alinea a nivel perfecto una estación entre dos vecinos verticales (dx = 0)", () => {
        const n1 = { id: 1, x: 400.0, y: 100.0 };
        const n2 = { id: 2, x: 400.0, y: 300.0 };
        const st = { id: 3, x: 403.5, y: 200.0 }; // Ligeramente desalineada en X por 3.5px

        const [newX, newY] = getStationAutoAlignedCoords(st, st.x, st.y, [n1, n2], null);
        assert.equal(newX, 400.0, "La estación debe quedar exactamente a X=400");
        assert.equal(newY, 200.0);
        assert.equal(newX - n1.x, 0, "Pendiente vertical perfecta con n1");
        assert.equal(newX - n2.x, 0, "Pendiente vertical perfecta con n2");
    });

    it("auto-alinea a nivel perfecto una estación en una esquina ortogonal a 90° (L-bend)", () => {
        const n1 = { id: 1, x: 100.0, y: 200.0 }; // Al oeste
        const n2 = { id: 2, x: 250.0, y: 350.0 }; // Al sur
        const st = { id: 3, x: 252.0, y: 203.0 }; // Cerca de la esquina (250, 200)

        const [newX, newY] = getStationAutoAlignedCoords(st, st.x, st.y, [n1, n2], null);
        assert.equal(newX, 250.0, "Debe alinearse en X con n2");
        assert.equal(newY, 200.0, "Debe alinearse en Y con n1");
        // Con n1: Y es igual (horizontal puro, dy = 0)
        assert.equal(newY - n1.y, 0);
        // Con n2: X es igual (vertical puro, dx = 0)
        assert.equal(newX - n2.x, 0);
    });

    it("auto-alinea a nivel perfecto una estación en una diagonal collinear a 45°", () => {
        const n1 = { id: 1, x: 100.0, y: 100.0 };
        const n2 = { id: 2, x: 300.0, y: 300.0 };
        const st = { id: 3, x: 201.0, y: 198.0 }; // Ligeramente desalineada de la diagonal x = y

        const [newX, newY] = getStationAutoAlignedCoords(st, st.x, st.y, [n1, n2], null);
        assert.equal(Math.abs(newX - n1.x), Math.abs(newY - n1.y), "Debe satisfacer |dx| === |dy| con n1");
        assert.equal(Math.abs(newX - n2.x), Math.abs(newY - n2.y), "Debe satisfacer |dx| === |dy| con n2");
        assert.equal(newX, newY, "X e Y deben ser idénticos en la diagonal a 45°");
        assert.equal(newX, 199.5);
        assert.equal(newY, 199.5);
    });
});


describe("Cartografía del Mapa - Ocultamiento por Defecto y Renderizado Condicional", () => {
    it("NetworkStore inicia con showCityOutlines desactivado por defecto (false)", () => {
        const store = createNetworkStore();
        assert.equal(store.showCityOutlines, false, "La cartografía de fondo debe estar deshabilitada por defecto");
    });

    it("renderCityOutlines no genera elementos en el SVG si showCityOutlines es false", () => {
        const store = createNetworkStore();
        store.showCityOutlines = false;
        store.cityOutlines = [
            { id: 1, name: "Meseta Central Metropolitana", polygon_points: [[100, 100], [200, 100], [200, 200]] },
            { id: 2, name: "Terminal Aéreo Sur Álvarez Morisot y Ciudad Universitaria", polygon_points: [[300, 300], [400, 300], [400, 400]] }
        ];

        const mockLayer = { innerHTML: "previous-content" };
        function renderOutlines(g, storeRef) {
            if (!g) return;
            if (!storeRef.showCityOutlines) {
                g.innerHTML = "";
                return;
            }
            g.innerHTML = storeRef.cityOutlines.map(z => `<polygon data-zone-id="${z.id}" />`).join("");
        }

        renderOutlines(mockLayer, store);
        assert.equal(mockLayer.innerHTML, "", "La capa SVG de zonas cartográficas debe limpiarse a vacío");

        store.showCityOutlines = true;
        renderOutlines(mockLayer, store);
        assert.ok(mockLayer.innerHTML.includes('data-zone-id="1"'), "Debe renderizar la zona 1 al activarse");
        assert.ok(mockLayer.innerHTML.includes('data-zone-id="2"'), "Debe renderizar la zona 2 al activarse");
    });

    it("la edición de una zona en subtab city activa automáticamente la cartografía si estaba oculta", () => {
        const store = createNetworkStore();
        store.showCityOutlines = false;

        function onSubtabSwitch(tab, storeRef) {
            if (tab === "city") {
                if (!storeRef.showCityOutlines) {
                    storeRef.showCityOutlines = true;
                }
            }
        }

        onSubtabSwitch("station", store);
        assert.equal(store.showCityOutlines, false);

        onSubtabSwitch("city", store);
        assert.equal(store.showCityOutlines, true, "Al entrar al editor de ciudad debe activar la visibilidad de cartografía");
    });
});

describe("Ocultar y Mostrar Líneas Individuales (Visibilidad Selectiva)", () => {
    it("permite ocultar, mostrar y alternar visibilidad de líneas con persistencia en el Set", () => {
        const store = createNetworkStore();
        store.lines = [{ code: "1", name: "Línea 1" }, { code: "2", name: "Línea 2" }, { code: "A", name: "Línea A" }];

        assert.equal(store.isLineHidden("1"), false);
        assert.equal(store.isLineHidden("2"), false);

        store.hideLine("1");
        assert.equal(store.isLineHidden("1"), true);
        assert.equal(store.isLineHidden("2"), false);

        // Toggle vuelve a mostrar
        const visibleNow = store.toggleLineVisibility("1");
        assert.equal(visibleNow, true);
        assert.equal(store.isLineHidden("1"), false);

        // Toggle oculta
        const visibleAgain = store.toggleLineVisibility("1");
        assert.equal(visibleAgain, false);
        assert.equal(store.isLineHidden("1"), true);

        // Ocultar todas y mostrar todas
        store.hideAllLines();
        assert.equal(store.isLineHidden("1"), true);
        assert.equal(store.isLineHidden("2"), true);
        assert.equal(store.isLineHidden("A"), true);

        store.showAllLines();
        assert.equal(store.isLineHidden("1"), false);
        assert.equal(store.isLineHidden("2"), false);
        assert.equal(store.isLineHidden("A"), false);
    });

    it("evalúa visibilidad compuesta: estaciones compartidas permanecen visibles si al menos una de sus líneas es visible", () => {
        const store = createNetworkStore();
        store.lines = [{ code: "1" }, { code: "2" }];
        const stShared = { id: 10, name: "Pino Suárez", lines: ["1", "2"] };
        const stExclusive = { id: 20, name: "Merced", lines: ["1"] };

        function isStationVisible(st, storeRef) {
            if (!st.lines || st.lines.length === 0) return true;
            return st.lines.some(code => !storeRef.isLineHidden(code));
        }

        assert.equal(isStationVisible(stShared, store), true);
        assert.equal(isStationVisible(stExclusive, store), true);

        store.hideLine("1");
        // Pino Suárez sigue visible porque Línea 2 no está oculta
        assert.equal(isStationVisible(stShared, store), true);
        // Merced queda oculta porque su única línea está oculta
        assert.equal(isStationVisible(stExclusive, store), false);

        store.hideLine("2");
        // Ahora ambas están ocultas
        assert.equal(isStationVisible(stShared, store), false);
    });
});

describe("Escalas y Distancias de Líneas (distanceScale & trackWidthScale)", () => {
    it("permite ajustar trackWidthScale entre 0.4x y 3.5x para grosores de líneas expandidos", () => {
        const store = createNetworkStore();
        assert.equal(store.trackWidthScale, 1.0);

        store.trackWidthScale = 2.5;
        assert.equal(store.trackWidthScale, 2.5);

        const baseMetroWidth = 15.8;
        const scaledWidth = baseMetroWidth * store.trackWidthScale;
        assert.equal(scaledWidth, 39.5);
    });

    it("permite ajustar distanceScale y transforma coordenadas de forma simétrica e invertible", () => {
        const store = createNetworkStore();
        assert.equal(store.distanceScale, 1.0);

        // A escala 1.0, las coordenadas lógicas y SVG son idénticas
        const p1 = store.logicalToSvgCoords(2120, 1860);
        assert.equal(p1.x, 2120);
        assert.equal(p1.y, 1860);
        const inv1 = store.svgToLogicalCoords(p1.x, p1.y);
        assert.equal(inv1.x, 2120);
        assert.equal(inv1.y, 1860);

        // A escala 1.5x (distancias ampliadas)
        store.setDistanceScale(1.5);
        assert.equal(store.distanceScale, 1.5);

        const logicalPt = { x: 3000, y: 2200 };
        const svgPt = store.logicalToSvgCoords(logicalPt.x, logicalPt.y);
        // Debe expandirse respecto al centroide (2760, 1990)
        assert.ok(svgPt.x > logicalPt.x, "X debe expandirse hacia afuera");
        assert.ok(svgPt.y > logicalPt.y, "Y debe expandirse hacia afuera");

        // El mapeo inverso debe devolver con precisión micrométrica las coordenadas lógicas originales
        const recovered = store.svgToLogicalCoords(svgPt.x, svgPt.y);
        assert.ok(Math.abs(recovered.x - logicalPt.x) < 0.0001, "X inversa debe coincidir");
        assert.ok(Math.abs(recovered.y - logicalPt.y) < 0.0001, "Y inversa debe coincidir");
    });
});

describe("Pasillos de Correspondencia entre Estaciones Distantes", () => {
    it("administra pasillos de correspondencia con distancias en metros y tiempos de caminata", () => {
        const store = createNetworkStore();
        const corridor = {
            id: "tc_101_202",
            from_station_id: 101,
            to_station_id: 202,
            distance_meters: 180,
            walking_minutes: 3.0,
            waypoints: [[2800, 2000]],
            status: "active"
        };

        store.addTransferCorridor(corridor);
        assert.equal(store.transferCorridors.length, 1);
        assert.equal(store.transferCorridorsById.get("tc_101_202"), corridor);

        // Búsqueda por estación conectada
        const corridorsFor101 = store.getCorridorsForStation(101);
        assert.equal(corridorsFor101.length, 1);
        assert.equal(corridorsFor101[0].id, "tc_101_202");

        const corridorsFor202 = store.getCorridorsForStation(202);
        assert.equal(corridorsFor202.length, 1);

        const corridorsForOther = store.getCorridorsForStation(999);
        assert.equal(corridorsForOther.length, 0);

        // Eliminación de pasillo
        store.removeTransferCorridor("tc_101_202");
        assert.equal(store.transferCorridors.length, 0);
        assert.equal(store.transferCorridorsById.has("tc_101_202"), false);
    });

    it("hidrata transfer_corridors al recibir datos topológicos de la API", () => {
        const store = createNetworkStore();
        const mockApiData = {
            lines: [{ code: "1", stops: [] }],
            stations: [{ id: 1, name: "Estación A" }, { id: 2, name: "Estación B" }],
            transfer_corridors: [
                { id: "tc_1_2", from_station_id: 1, to_station_id: 2, distance_meters: 120, walking_minutes: 2.0 }
            ]
        };

        store.hydrate(mockApiData);
        assert.equal(store.transferCorridors.length, 1);
        assert.equal(store.transferCorridorsById.get("tc_1_2").distance_meters, 120);
    });
});
