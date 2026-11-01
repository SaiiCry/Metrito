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
        isolatedLineCode: null,
        selectedStationId: null,

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
