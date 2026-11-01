import json
import xml.etree.ElementTree as ET
from django.test import TestCase, Client
from network.models import TransitLine, Station, LineStation
from network.seed import seed_database


class SMyTNetworkTestCase(TestCase):
    def setUp(self):
        seed_database(force_reset=True)
        self.client = Client()

    def test_master_plan_topology_counts_and_coherence(self):
        """Verifica que Django consuma directamente cartografia/red_metro.json con las 828 estaciones únicas."""
        self.assertEqual(TransitLine.objects.count(), 34)
        self.assertEqual(Station.objects.count(), 828)

        metro_lines = TransitLine.objects.filter(network_type="metro")
        brt_lines = TransitLine.objects.filter(network_type="bus_articulado")
        self.assertEqual(metro_lines.count(), 29)
        self.assertEqual(brt_lines.count(), 5)

        total_metro_declared = sum(l.declared_stations_count for l in metro_lines)
        self.assertEqual(total_metro_declared, 828)

        # Verificar Santa Mónica (registro único compartido por las líneas 1, 4, 7, 15 y 18)
        sm = Station.objects.get(code="estacion-santa-monica")
        sm_lines = sorted(
            LineStation.objects.filter(station=sm).values_list("line__code", flat=True)
        )
        self.assertEqual(sm_lines, ["1", "15", "18", "4", "7"])

        # Verificar Línea A (132,8 km, 124 estaciones, frecuencias 150s y 300s)
        line_a = TransitLine.objects.get(code="A")
        self.assertAlmostEqual(line_a.length_km, 132.8, places=1)
        self.assertEqual(line_a.declared_stations_count, 124)
        self.assertEqual(line_a.frequency_seconds, 150)
        self.assertEqual(line_a.premium_frequency_seconds, 300)

        # Verificar Línea C (21 estaciones en operación y 13 cerradas permanentemente)
        line_c = TransitLine.objects.get(code="C")
        self.assertEqual(line_c.declared_stations_count, 34)
        self.assertEqual(line_c.operational_stations_count, 21)
        closed_c = LineStation.objects.filter(line=line_c, segment_status="closed_permanent").count()
        self.assertEqual(closed_c, 13)

    def test_index_api_and_cartografia_endpoints(self):
        """Verifica vista principal, API operativa y endpoints directos de cartografía SVG/JSON/Logo."""
        resp_index = self.client.get("/")
        self.assertEqual(resp_index.status_code, 200)

        resp_api = self.client.get("/api/network/")
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertEqual(data["kpis"]["total_lines"], 34)
        self.assertEqual(data["kpis"]["metro_stations_total"], 828)

        # Verificar endpoints directos de los artefactos cartográficos
        resp_c_json = self.client.get("/api/cartografia/json/")
        self.assertEqual(resp_c_json.status_code, 200)
        c_json = resp_c_json.json()
        self.assertEqual(c_json["metadatos"]["total_estaciones"], 828)
        self.assertEqual(c_json["metadatos"]["total_lineas_convencionales"], 22)

        resp_c_svg = self.client.get("/api/cartografia/svg/")
        self.assertEqual(resp_c_svg.status_code, 200)
        root_svg = ET.fromstring(resp_c_svg.content)
        self.assertTrue(root_svg.tag.endswith("svg"))

        resp_logo = self.client.get("/api/cartografia/logo/")
        self.assertEqual(resp_logo.status_code, 200)
        root_logo = ET.fromstring(resp_logo.content)
        self.assertTrue(root_logo.tag.endswith("svg"))

        # Probar simulación de alerta y edición de estación
        resp_sim = self.client.post("/api/alerts/simulate/")
        self.assertEqual(resp_sim.status_code, 200)
        self.assertTrue(resp_sim.json()["ok"])

        santa_monica = Station.objects.get(code="estacion-santa-monica")
        resp_st = self.client.post(
            f"/api/stations/{santa_monica.id}/update/",
            data=json.dumps({
                "x": 2124.0,
                "y": 1862.0,
                "icon_tags": ["centro_modal", "zona_cultural", "escuela"],
                "terminal_lines": ["1", "18"],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_st.status_code, 200)
        santa_monica.refresh_from_db()
        self.assertEqual(santa_monica.x, 2124.0)
        self.assertEqual(santa_monica.icon_tags, ["centro_modal", "zona_cultural", "escuela"])
        self.assertEqual(santa_monica.terminal_lines, ["1", "18"])
        self.assertTrue(santa_monica.is_terminal)

        # Probar edición interactiva de trazos (waypoints de un tramo LineStation)
        sample_ls = LineStation.objects.filter(line__code="1").order_by("sequence").first()
        resp_wp = self.client.post(
            f"/api/line-segments/{sample_ls.id}/waypoints/",
            data=json.dumps({"waypoints": [[1850.5, 1790.0], [1910.0, 1815.5]]}),
            content_type="application/json",
        )
        self.assertEqual(resp_wp.status_code, 200)
        sample_ls.refresh_from_db()
        self.assertEqual(sample_ls.waypoints, [[1850.5, 1790.0], [1910.0, 1815.5]])

        # Mover la estación NO debe borrar los trazos/waypoints personalizados del usuario
        self.client.post(
            f"/api/stations/{sample_ls.station_id}/update/",
            data=json.dumps({"x": sample_ls.station.x + 5.0, "y": sample_ls.station.y + 5.0}),
            content_type="application/json",
        )
        sample_ls.refresh_from_db()
        self.assertEqual(sample_ls.waypoints, [[1850.5, 1790.0], [1910.0, 1815.5]])

        # Probar edición de trayecto de paradas de una línea
        line_g = TransitLine.objects.get(code="G")
        g_stops = list(LineStation.objects.filter(line=line_g).order_by("sequence"))
        reversed_payload = [{"station_id": ls.station_id, "id": ls.id} for ls in reversed(g_stops)]
        resp_route = self.client.post(
            "/api/lines/G/route/",
            data=json.dumps({"stops": reversed_payload}),
            content_type="application/json",
        )
        self.assertEqual(resp_route.status_code, 200)
        new_first = LineStation.objects.filter(line=line_g).order_by("sequence").first()
        self.assertEqual(new_first.station_id, g_stops[-1].station_id)

    def test_visual_editor_station_creation_and_orphan_support(self):
        """1. Agregar estaciones: crea estaciones en el mapa, valida nombre y soporta estaciones huérfanas."""
        # Validación de nombre obligatorio
        resp_fail = self.client.post(
            "/api/stations/create/",
            data=json.dumps({"name": "", "x": 2100.0, "y": 1850.0}),
            content_type="application/json",
        )
        self.assertEqual(resp_fail.status_code, 400)
        self.assertIn("error", resp_fail.json())

        # Creación exitosa de estación huérfana (sin líneas asignadas)
        resp_ok = self.client.post(
            "/api/stations/create/",
            data=json.dumps({
                "name": "Estación Ficticia Parque Oriente",
                "x": 3200.0,
                "y": 1500.0,
                "infrastructure_type": "elevado",
                "operational_status": "operational",
                "lines": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_ok.status_code, 200)
        st_data = resp_ok.json()["station"]
        st_obj = Station.objects.get(id=st_data["id"])
        self.assertEqual(st_obj.name, "Estación Ficticia Parque Oriente")
        self.assertTrue(st_obj.is_user_created)
        self.assertEqual(st_obj.infrastructure_type, "elevado")

        # Verificar que /api/network/ incluya la estación huérfana sin errores
        resp_net = self.client.get("/api/network/")
        self.assertEqual(resp_net.status_code, 200)
        net_data = resp_net.json()
        orphan_found = next((s for s in net_data["stations"] if s["id"] == st_obj.id), None)
        self.assertIsNotNone(orphan_found)
        self.assertEqual(orphan_found["lines"], [])
        self.assertTrue(orphan_found["is_user_created"])

    def test_visual_editor_line_creation_and_planning_support(self):
        """4. Agregar líneas nuevas: crea línea con código único, color y soporta líneas sin estaciones iniciales."""
        # Creación de nueva línea en planificación (0 estaciones)
        resp_create = self.client.post(
            "/api/lines/create/",
            data=json.dumps({
                "code": "23",
                "name": "Línea 23 Expresa",
                "color": "#E11D48",
                "network_type": "metro",
                "line_subtype": "convencional",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_create.status_code, 200)
        line_obj = TransitLine.objects.get(code="23")
        self.assertEqual(line_obj.name, "Línea 23 Expresa")
        self.assertEqual(line_obj.color, "#E11D48")
        self.assertTrue(line_obj.is_user_created)
        self.assertEqual(line_obj.declared_stations_count, 0)

        # Validación de duplicidad de código
        resp_dup = self.client.post(
            "/api/lines/create/",
            data=json.dumps({
                "code": "23",
                "name": "Otra Línea 23 Duplicada",
                "color": "#10B981",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_dup.status_code, 400)
        self.assertIn("error", resp_dup.json())

        # Verificar que /api/network/ devuelva la nueva línea sin fallar
        resp_net = self.client.get("/api/network/")
        self.assertEqual(resp_net.status_code, 200)
        line_found = next((l for l in resp_net.json()["lines"] if l["code"] == "23"), None)
        self.assertIsNotNone(line_found)
        self.assertEqual(line_found["declared_stations_count"], 0)
        self.assertTrue(line_found["is_user_created"])

    def test_visual_editor_segment_creation_and_duplicate_prevention(self):
        """4. Agregar tramos: conecta estaciones contiguas y rechaza tramos directos duplicados."""
        line_1 = TransitLine.objects.get(code="1")
        stops = list(LineStation.objects.filter(line=line_1).order_by("sequence"))
        st_first = stops[0].station
        st_second = stops[1].station

        # Intentar crear un tramo directo duplicado entre dos estaciones que ya están conectadas directamente
        resp_dup_seg = self.client.post(
            "/api/line-segments/create/",
            data=json.dumps({
                "line_code": "1",
                "from_station_id": st_first.id,
                "to_station_id": st_second.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_dup_seg.status_code, 400)
        self.assertIn("Ya existe un tramo directo", resp_dup_seg.json()["error"])

        # Crear una nueva estación y conectarla a st_second en Línea 1
        st_new = Station.objects.create(
            code="estacion-test-ext",
            name="Estación Extensión Línea 1",
            x=2250.0,
            y=1900.0,
            is_user_created=True,
        )
        resp_new_seg = self.client.post(
            "/api/line-segments/create/",
            data=json.dumps({
                "line_code": "1",
                "from_station_id": st_second.id,
                "to_station_id": st_new.id,
                "waypoints": [[2200.0, 1880.0]],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_new_seg.status_code, 200)
        self.assertTrue(LineStation.objects.filter(line=line_1, station=st_new).exists())

    def test_visual_editor_correspondence_and_intra_line_rejection(self):
        """2. Agregar correspondencias: conecta estaciones a otras líneas y rechaza transferencias intra-línea."""
        line_1 = TransitLine.objects.get(code="1")
        line_2 = TransitLine.objects.get(code="2")
        st_line1 = LineStation.objects.filter(line=line_1).first().station

        # Rechazo de transferencia intra-línea (la estación ya pertenece a Línea 1)
        resp_intra = self.client.post(
            "/api/correspondences/create/",
            data=json.dumps({
                "station_id": st_line1.id,
                "target_line_code": "1",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_intra.status_code, 400)
        self.assertIn("No se puede crear correspondencia entre la misma línea", resp_intra.json()["error"])

        # Conectar exitosamente a Línea 2 como correspondencia
        resp_corr = self.client.post(
            "/api/correspondences/create/",
            data=json.dumps({
                "station_id": st_line1.id,
                "target_line_code": "2",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_corr.status_code, 200)
        st_line1.refresh_from_db()
        self.assertTrue(st_line1.is_transfer)
        self.assertTrue(LineStation.objects.filter(line=line_2, station=st_line1).exists())

    def test_minimum_two_stops_enforcement(self):
        """3. Modificar tramos: bloquear eliminación de paradas si la línea quedaría con menos de 2 estaciones."""
        line_b = TransitLine.objects.get(code="B")
        stops = list(LineStation.objects.filter(line=line_b).order_by("sequence"))

        # Intentar dejar solo 1 estación en la línea
        resp_underflow = self.client.post(
            "/api/lines/B/route/",
            data=json.dumps({"stops": [{"station_id": stops[0].station_id, "id": stops[0].id}]}),
            content_type="application/json",
        )
        self.assertEqual(resp_underflow.status_code, 400)
        self.assertIn("al menos 2 estaciones", resp_underflow.json()["error"])

    def test_persistence_across_server_restarts_and_seed_calls(self):
        """5. Persistencia de cambios: garantiza que las estaciones y líneas de usuario sobrevivan a reinicios."""
        # 1. Crear estación y línea de usuario
        st_user = Station.objects.create(
            code="estacion-persist-test",
            name="Estación Persistente Test",
            x=3100.0,
            y=1700.0,
            is_user_created=True,
        )
        line_user = TransitLine.objects.create(
            code="24",
            name="Línea 24 Persistente",
            color="#3B82F6",
            is_user_created=True,
        )

        # 2. Guardar explícitamente la capa de edición
        resp_save = self.client.post("/api/editor/save/")
        self.assertEqual(resp_save.status_code, 200)

        # 3. Simular llamada a seed_database(force_reset=False) como ocurre al reiniciar o recargar el servidor
        seed_res = seed_database(force_reset=False)
        self.assertFalse(seed_res["seeded"])  # No debe sobreescribir la base de datos

        # 4. Verificar que sigan existiendo intactas
        self.assertTrue(Station.objects.filter(code="estacion-persist-test").exists())
        self.assertTrue(TransitLine.objects.filter(code="24").exists())
