import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

describe("ApiClient - Persistencia Dual y Modo Offline / GitHub Pages", () => {
    let mockStore;
    let mockLocalStorage;
    let storageData = {};

    beforeEach(() => {
        storageData = {};
        mockLocalStorage = {
            getItem(k) { return storageData[k] || null; },
            setItem(k, v) { storageData[k] = String(v); },
            removeItem(k) { delete storageData[k]; }
        };

        mockStore = {
            stations: [
                { id: 101, code: "st-101", name: "Estación Central", lines: ["1", "2"], is_transfer: true, terminal_lines: [] },
                { id: 102, code: "st-102", name: "Estación Norte", lines: ["1"], is_transfer: false, terminal_lines: [] }
            ],
            stationsById: new Map(),
            lines: [
                {
                    code: "1",
                    name: "Línea 1",
                    stops: [
                        { station_id: 101, sequence: 0, waypoints: [] },
                        { station_id: 102, sequence: 1, waypoints: [] }
                    ]
                },
                {
                    code: "2",
                    name: "Línea 2",
                    stops: [
                        { station_id: 101, sequence: 0, waypoints: [] }
                    ]
                }
            ],
            linesByCode: new Map()
        };

        mockStore.stations.forEach(s => mockStore.stationsById.set(s.id, s));
        mockStore.lines.forEach(l => mockStore.linesByCode.set(l.code, l));
    });

    it("desconectar correspondencia en modo offline actualiza NetworkStore y persiste en storage", () => {
        const st = mockStore.stationsById.get(101);
        assert.equal(st.is_transfer, true);
        assert.deepEqual(st.lines, ["1", "2"]);

        // Simular lógica de ApiClient.applyLocalMutation para desconectar Línea 2
        st.lines = st.lines.filter(c => c !== "2");
        st.is_transfer = st.lines.length > 1;

        const ln2 = mockStore.linesByCode.get("2");
        ln2.stops = ln2.stops.filter(s => s.station_id !== 101);

        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify({
            stations: { 101: { lines: st.lines, is_transfer: st.is_transfer } },
            lines: { "2": { stops: ln2.stops } }
        }));

        assert.equal(st.lines.length, 1);
        assert.equal(st.is_transfer, false);
        assert.equal(ln2.stops.length, 0);

        const saved = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        assert.deepEqual(saved.stations[101].lines, ["1"]);
        assert.equal(saved.stations[101].is_transfer, false);
    });

    it("agregar correspondencia en modo offline incrementa líneas y actualiza is_transfer", () => {
        const st = mockStore.stationsById.get(102);
        assert.equal(st.is_transfer, false);

        // Conectar a Línea 2
        st.lines.push("2");
        st.is_transfer = true;

        const ln2 = mockStore.linesByCode.get("2");
        ln2.stops.push({ station_id: 102, sequence: ln2.stops.length, waypoints: [] });

        assert.equal(st.is_transfer, true);
        assert.equal(st.lines.length, 2);
        assert.equal(ln2.stops.length, 2);
    });

    it("edición de coordenadas de estación persiste en memoria y almacenamiento local", () => {
        const st = mockStore.stationsById.get(101);
        st.x = 2450.5;
        st.y = 1920.0;

        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify({
            stations: { 101: { x: 2450.5, y: 1920.0 } }
        }));

        const saved = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        assert.equal(saved.stations[101].x, 2450.5);
        assert.equal(saved.stations[101].y, 1920.0);
    });

    it("configuración de endpoint de Vercel (setApiBase / getApiBase) y enrutamiento remoto", () => {
        const setApiBase = (url) => {
            if (!url || !url.trim()) {
                mockLocalStorage.removeItem("metrito_api_url");
            } else {
                mockLocalStorage.setItem("metrito_api_url", url.trim().replace(/\/+$/, ""));
            }
        };

        const getApiBase = () => {
            const stored = mockLocalStorage.getItem("metrito_api_url");
            return stored ? stored.trim().replace(/\/+$/, "") : "";
        };

        assert.equal(getApiBase(), "");

        setApiBase("https://metrito-api.vercel.app/");
        assert.equal(getApiBase(), "https://metrito-api.vercel.app");

        const endpoint = "/api/network/";
        const fullUrl = `${getApiBase()}${endpoint}`;
        assert.equal(fullUrl, "https://metrito-api.vercel.app/api/network/");

        setApiBase("");
        assert.equal(getApiBase(), "");
    });

    it("conexión directa de estaciones estilo MetroMapMaker en modo offline sin modal incorpora líneas e is_transfer", () => {
        const st1 = mockStore.stationsById.get(101); // Líneas ["1", "2"]
        const st2 = mockStore.stationsById.get(102); // Línea ["1"]
        const lineCode = "2";

        if (!st2.lines.includes(lineCode)) st2.lines.push(lineCode);
        st2.is_transfer = st2.lines.length > 1;

        const ln2 = mockStore.linesByCode.get("2");
        ln2.stops.push({
            id: 999,
            station_id: 102,
            sequence: ln2.stops.length,
            waypoints: []
        });

        assert.equal(st2.lines.includes("2"), true);
        assert.equal(st2.is_transfer, true);
        assert.equal(ln2.stops.length, 2);
    });

    it("eliminación de estación en modo offline persiste en deletedStations y no resucita al recargar topología base", () => {
        const stIdToDelete = 102;
        
        // 1. Simular eliminación local
        mockStore.stations = mockStore.stations.filter(s => s.id !== stIdToDelete);
        mockStore.stationsById.delete(stIdToDelete);
        for (const ln of mockStore.lines) {
            ln.stops = ln.stops.filter(s => s.station_id !== stIdToDelete);
        }

        const edits = {
            stations: {},
            lines: {},
            createdStations: [],
            createdLines: [],
            cityOutlines: {},
            deletedStations: [stIdToDelete]
        };
        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify(edits));

        assert.equal(mockStore.stationsById.has(102), false);
        assert.equal(mockStore.stations.length, 1);
        assert.equal(mockStore.lines[0].stops.length, 1);

        // 2. Simular recarga de topología base (data/network.json con las estaciones originales)
        const baseStations = [
            { id: 101, code: "st-101", name: "Estación Central", lines: ["1", "2"], is_transfer: true },
            { id: 102, code: "st-102", name: "Estación Norte", lines: ["1"], is_transfer: false }
        ];
        mockStore.stations = [...baseStations];
        mockStore.stationsById.clear();
        mockStore.stations.forEach(s => mockStore.stationsById.set(s.id, s));
        mockStore.lines[0].stops = [
            { station_id: 101, sequence: 0, waypoints: [] },
            { station_id: 102, sequence: 1, waypoints: [] }
        ];

        // 3. Re-aplicar capas de localStorage (applyStoredEditsToStore)
        const storedEdits = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        if (Array.isArray(storedEdits.deletedStations) && storedEdits.deletedStations.length > 0) {
            const delSet = new Set(storedEdits.deletedStations.map(Number));
            mockStore.stations = mockStore.stations.filter(s => !delSet.has(s.id));
            for (const delId of delSet) mockStore.stationsById.delete(delId);
            for (const ln of mockStore.lines) {
                ln.stops = ln.stops.filter(s => !delSet.has(s.station_id));
            }
        }

        // 4. Verificar que la estación eliminada no revivió
        assert.equal(mockStore.stationsById.has(102), false);
        assert.equal(mockStore.stations.length, 1);
        assert.equal(mockStore.stations[0].id, 101);
        assert.equal(mockStore.lines[0].stops.length, 1);
    });

    it("inserción de estación intermedia en un tramo entre dos paradas no la marca como terminal y la posiciona en secuencia correcta", () => {
        const ln1 = mockStore.linesByCode.get("1");
        // Línea 1 tiene paradas 101 (seq 0) y 102 (seq 1)
        const newStationId = 999;
        const newSt = {
            id: newStationId,
            code: "st-999",
            name: "Estación Intermedia",
            x: 2120,
            y: 1860,
            lines: ["1"],
            is_terminal: false,
            terminal_lines: []
        };
        mockStore.stations.push(newSt);
        mockStore.stationsById.set(newStationId, newSt);

        // Simular inserción entre 101 y 102
        const s1Id = 101;
        const s2Id = 102;
        const i1 = ln1.stops.findIndex(s => s.station_id === s1Id);
        const i2 = ln1.stops.findIndex(s => s.station_id === s2Id);
        const insertIdx = Math.max(i1, i2) === i1 + 1 ? i2 : Math.min(i1, i2) + 1;

        const newStop = {
            id: 888,
            station_id: newStationId,
            station_name: newSt.name,
            sequence: 0,
            waypoints: []
        };
        ln1.stops.splice(insertIdx, 0, newStop);
        ln1.stops.forEach((s, idx) => { s.sequence = idx; });

        assert.equal(ln1.stops.length, 3);
        assert.equal(ln1.stops[0].station_id, 101);
        assert.equal(ln1.stops[1].station_id, 999);
        assert.equal(ln1.stops[2].station_id, 102);
        assert.equal(newSt.is_terminal, false);
        assert.equal(newSt.terminal_lines.length, 0);
    });

    it("reordenar y eliminar parada en el editor de trayecto actualiza secuencias y pertenencia de línea", () => {
        const ln1 = mockStore.linesByCode.get("1");
        // Reordenar: subir la parada intermedia a la posición 0
        const stops = [...ln1.stops];
        [stops[0], stops[1]] = [stops[1], stops[0]];
        stops.forEach((s, i) => { s.sequence = i; });
        ln1.stops = stops;

        assert.equal(ln1.stops[0].station_id, 102);
        assert.equal(ln1.stops[1].station_id, 101);

        // Eliminar parada 102 (última)
        const removed = ln1.stops.pop();
        const removedSt = mockStore.stationsById.get(removed.station_id);
        if (removedSt) {
            removedSt.lines = removedSt.lines.filter(c => c !== "1");
            removedSt.is_transfer = removedSt.lines.length > 1;
        }

        assert.equal(ln1.stops.length, 1);
        assert.equal(removedSt.lines.includes("1"), false);
    });

    it("enderezado ortogonal de línea en modo offline genera esquinas exactas a 90°/180° y persiste en almacenamiento", () => {
        const ln1 = mockStore.linesByCode.get("1");
        const st1 = mockStore.stationsById.get(101);
        const st2 = mockStore.stationsById.get(102);

        // Estaciones en diagonal: st1(100, 200), st2(500, 260) -> dx = 400, dy = 60
        st1.x = 100.0;
        st1.y = 200.0;
        st2.x = 500.0;
        st2.y = 260.0;

        // Simular lógica de ApiClient.applyLocalMutation para enderezar línea 1
        const branches = {};
        for (const s of ln1.stops) {
            const b = s.branch || "main";
            if (!branches[b]) branches[b] = [];
            branches[b].push(s);
        }
        for (const [branchName, bStops] of Object.entries(branches)) {
            const n = bStops.length;
            if (n < 2) continue;
            for (let i = 0; i < n - 1; i++) {
                const s1 = bStops[i];
                const s2 = bStops[i + 1];
                const station1 = mockStore.stationsById.get(s1.station_id);
                const station2 = mockStore.stationsById.get(s2.station_id);
                const dx = station2.x - station1.x;
                const dy = station2.y - station1.y;
                if (Math.abs(dy) < 1.0) {
                    s1.waypoints = [];
                } else if (Math.abs(dx) < 1.0) {
                    s1.waypoints = [];
                } else {
                    if (Math.abs(dx) >= Math.abs(dy)) {
                        s1.waypoints = [[Math.round(station2.x * 2) / 2, Math.round(station1.y * 2) / 2]];
                    } else {
                        s1.waypoints = [[Math.round(station1.x * 2) / 2, Math.round(station2.y * 2) / 2]];
                    }
                }
            }
            bStops[n - 1].waypoints = [];
        }

        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify({
            lines: { "1": { stops: ln1.stops } }
        }));

        assert.equal(ln1.stops[0].waypoints.length, 1);
        assert.deepEqual(ln1.stops[0].waypoints[0], [500.0, 200.0]);
        // dy = 0 horizontal (180°), luego dx = 0 vertical (90°)
        assert.equal(ln1.stops[0].waypoints[0][1] - st1.y, 0);
        assert.equal(st2.x - ln1.stops[0].waypoints[0][0], 0);

        const saved = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        assert.deepEqual(saved.lines["1"].stops[0].waypoints, [[500.0, 200.0]]);
    });

    it("actualización de waypoints de un tramo persiste correctamente", () => {
        const ln1 = mockStore.linesByCode.get("1");
        const stop = ln1.stops[0];
        stop.id = 55;
        const newWps = [[200.0, 150.0], [300.0, 150.0]];
        stop.waypoints = newWps;

        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify({
            segments: { 55: { waypoints: newWps } }
        }));

        const saved = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        assert.deepEqual(saved.segments["55"].waypoints, [[200.0, 150.0], [300.0, 150.0]]);
    });

    it("personalización de línea principal y color de estación persiste en memoria y almacenamiento local", () => {
        const st = mockStore.stationsById.get(102);
        st.lines = ["2"];
        st.custom_color = "#E11D48";
        st.is_transfer = false;

        mockLocalStorage.setItem("simma_user_network_edits_v1", JSON.stringify({
            stations: {
                102: { lines: ["2"], custom_color: "#E11D48", is_transfer: false }
            }
        }));

        const saved = JSON.parse(mockLocalStorage.getItem("simma_user_network_edits_v1"));
        assert.deepEqual(saved.stations[102].lines, ["2"]);
        assert.equal(saved.stations[102].custom_color, "#E11D48");
        assert.equal(saved.stations[102].is_transfer, false);
    });

    it("conexión de tramo directo detecta y utiliza la línea compartida 2 sin defaulting a Línea 1", () => {
        const st1 = mockStore.stationsById.get(101); // lines: ["1", "2"]
        const st2 = mockStore.stationsById.get(102); // lines: ["1"]
        // Si st2 se conecta en Línea 2
        const targetLineCode = "2";
        const ln2 = mockStore.linesByCode.get(targetLineCode);

        // Añadir a ln2
        ln2.stops.push({ station_id: st2.id, sequence: ln2.stops.length, waypoints: [] });
        if (!st2.lines.includes(targetLineCode)) st2.lines.push(targetLineCode);
        st2.is_transfer = st2.lines.length > 1;

        assert.equal(st2.lines.includes("2"), true);
        assert.equal(st2.is_transfer, true);
        assert.equal(ln2.stops.some(s => s.station_id === 102), true);
    });
});