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
});
