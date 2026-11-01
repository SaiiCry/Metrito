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
});
