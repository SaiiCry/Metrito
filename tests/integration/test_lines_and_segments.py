"""
Pruebas de Integración para Líneas, Tramos, Waypoints y Regla de Parada Mínima.
Verifica endpoints:
- POST /api/lines/create/
- POST /api/lines/<line_code>/update/
- POST /api/lines/<line_code>/route/
- POST /api/line-segments/create/
- POST /api/line-segments/<ls_id>/waypoints/
"""

import json
import pytest
from network.models import TransitLine, Station, LineStation


@pytest.mark.integration
class TestLineCreationEndpoint:
    """Verifica la creación y validación de líneas de transporte."""

    def test_create_line_valid_payload_success(self, api_client, db):
        """Crea una nueva línea en planificación (0 estaciones iniciales) con color y tipo válidos."""
        payload = {
            "code": "23",
            "name": "Línea 23 Expresa",
            "route_title": "Norte – Sur",
            "color": "#E11D48",
            "network_type": "metro",
            "line_subtype": "convencional",
            "frequency_seconds": 150,
            "max_speed_kmh": 70.0,
        }
        resp = api_client.post(
            "/api/lines/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        l_data = data["line"]
        assert l_data["code"] == "23"
        assert l_data["name"] == "Línea 23 Expresa"
        assert l_data["color"] == "#E11D48"
        assert l_data["is_user_created"] is True
        assert l_data["declared_stations_count"] == 0

        line_obj = TransitLine.objects.get(code="23")
        assert line_obj.is_user_created is True
        assert line_obj.frequency_seconds == 150

    def test_create_line_duplicate_code_rejected(self, api_client, minimal_network):
        """Verifica que no se permita registrar una línea con código duplicado (case-insensitive)."""
        payload = {
            "code": "1",  # Ya existe en minimal_network
            "name": "Otra Línea 1",
            "color": "#10B981",
        }
        resp = api_client.post(
            "/api/lines/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "ya existe en la red" in resp.json()["error"]

    def test_create_line_code_and_name_required(self, api_client, db):
        """Verifica que el código y el nombre de la línea sean estrictamente obligatorios."""
        # Falta código
        resp1 = api_client.post(
            "/api/lines/create/",
            data=json.dumps({"name": "Línea Sin Código", "color": "#10B981"}),
            content_type="application/json",
        )
        assert resp1.status_code == 400
        assert "código de línea es obligatorio" in resp1.json()["error"]

        # Falta nombre
        resp2 = api_client.post(
            "/api/lines/create/",
            data=json.dumps({"code": "L99", "name": "", "color": "#10B981"}),
            content_type="application/json",
        )
        assert resp2.status_code == 400
        assert "nombre de la línea es obligatorio" in resp2.json()["error"]

    def test_create_line_with_initial_stations(self, api_client, station_factory):
        """Verifica la creación de una línea asociándole estaciones existentes en el mismo payload."""
        st1 = station_factory(name="Terminal Poniente", x=1000.0, y=1000.0)
        st2 = station_factory(name="Terminal Oriente", x=2000.0, y=1000.0)

        payload = {
            "code": "EXPRESS",
            "name": "Línea Expresa Aeropuerto",
            "color": "#8B5CF6",
            "stations": [st1.id, st2.id],
        }
        resp = api_client.post(
            "/api/lines/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        line_obj = TransitLine.objects.get(code="EXPRESS")
        assert line_obj.declared_stations_count == 2
        assert LineStation.objects.filter(line=line_obj).count() == 2


@pytest.mark.integration
class TestLineRouteAndMinimumStopsRule:
    """Verifica la actualización de rutas, waypoints y la regla de negocio de parada mínima."""

    def test_update_line_route_reorders_stations_and_title(self, api_client, minimal_network):
        """Verifica que invertir el orden de paradas actualice secuencias y título de ruta."""
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]
        st_beta = minimal_network["st_beta"]

        payload = {
            "stops": [
                {"station_id": st_beta.id},
                {"station_id": st_alfa.id},
            ]
        }
        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        line.refresh_from_db()
        assert line.route_title == "Beta – Alfa"

        new_first = LineStation.objects.filter(line=line, sequence=0).first()
        assert new_first.station_id == st_beta.id

    def test_minimum_two_stops_rule_rejects_underflow(self, api_client, minimal_network):
        """
        Regla de negocio: Una línea debe conservar al menos 2 estaciones.
        Intentar reducir la línea a 1 o 0 paradas debe devolver 400 y NO modificar la línea.
        """
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]
        original_count = LineStation.objects.filter(line=line).count()
        original_stops = list(LineStation.objects.filter(line=line).values_list("station_id", flat=True))

        # Intento con 1 parada
        resp1 = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"stops": [{"station_id": st_alfa.id}]}),
            content_type="application/json",
        )
        assert resp1.status_code == 400
        assert "al menos 2 estaciones" in resp1.json()["error"]

        # Intento con 0 paradas
        resp2 = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"stops": []}),
            content_type="application/json",
        )
        assert resp2.status_code == 400
        assert "al menos 2 estaciones" in resp2.json()["error"]

        # Verificar que la base de datos NO se modificó
        current_stops = list(LineStation.objects.filter(line=line).values_list("station_id", flat=True))
        assert current_stops == original_stops
        assert LineStation.objects.filter(line=line).count() == original_count

    def test_route_update_rejects_non_existent_stations(self, api_client, minimal_network):
        """Verifica que el payload sea rechazado sin modificar la base si alguna estación no existe."""
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]

        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"stops": [{"station_id": st_alfa.id}, {"station_id": 999999}]}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Una o más estaciones del trayecto no existen" in resp.json()["error"]
        assert LineStation.objects.filter(line=line).count() == 2

    def test_clear_all_waypoints_endpoint(self, api_client, minimal_network):
        """Verifica que clear_all_waypoints: True vacíe los waypoints de todos los tramos de la línea."""
        line = minimal_network["line_1"]
        ls_0 = minimal_network["ls_1_0"]
        ls_0.waypoints = [[100, 200], [150, 250]]
        ls_0.save(update_fields=["waypoints"])

        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"clear_all_waypoints": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["cleared_waypoints"] is True
        ls_0.refresh_from_db()
        assert ls_0.waypoints == []

    def test_straighten_orthogonal_tracks_90_and_180_degrees(self, api_client, line_factory, station_factory):
        """
        Verifica que el enderezado de trazos oriente derecho a 180° (horizontal) o 90° (vertical)
        según el eje dominante entre estaciones consecutivas.
        """
        line = line_factory(code="S99", name="Línea de Prueba Ortogonal")
        st1 = station_factory(name="St Horiz 1", x=100.0, y=200.0)
        st2 = station_factory(name="St Horiz 2", x=500.0, y=260.0)  # dx=400, dy=60 -> horizontal (180°)
        st3 = station_factory(name="St Vert 3", x=550.0, y=800.0)   # dx=50, dy=540 -> vertical (90°)

        ls1 = LineStation.objects.create(line=line, station=st1, sequence=0, branch="main", waypoints=[[250, 400]])
        ls2 = LineStation.objects.create(line=line, station=st2, sequence=1, branch="main", waypoints=[[520, 500]])
        ls3 = LineStation.objects.create(line=line, station=st3, sequence=2, branch="main", waypoints=[])

        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"clear_all_waypoints": True, "straighten_orthogonal": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["straightened"] is True

        ls1.refresh_from_db()
        ls2.refresh_from_db()

        # ls1 (st1 -> st2): orientación horizontal -> codo [st2.x, st1.y] = [500.0, 200.0]
        assert ls1.waypoints == [[500.0, 200.0]]

        # ls2 (st2 -> st3): orientación vertical -> codo [st2.x, st3.y] = [500.0, 800.0]
        assert ls2.waypoints == [[500.0, 800.0]]

    def test_remove_station_from_line_keeps_station_in_database(self, api_client, station_factory, minimal_network):
        """
        Al eliminar una estación de una línea mediante route update:
        - Su LineStation se elimina.
        - La estación física persiste en el modelo Station.
        - Las demás paradas se re-secuencian correctamente.
        """
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]
        st_beta = minimal_network["st_beta"]
        st_extra = station_factory(name="Parada Extra Intermedia", x=1250.0, y=1000.0)

        # Crear inicialmente con 3 paradas: Alfa -> Extra -> Beta
        LineStation.objects.create(line=line, station=st_extra, sequence=2, branch="main")

        # Actualizar ruta eliminando st_extra (dejando Alfa y Beta)
        payload = {
            "stops": [
                {"station_id": st_alfa.id},
                {"station_id": st_beta.id},
            ]
        }
        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # st_extra ya no está en la línea, pero sigue existiendo en Station
        assert not LineStation.objects.filter(line=line, station=st_extra).exists()
        assert Station.objects.filter(id=st_extra.id).exists()
        assert LineStation.objects.filter(line=line).count() == 2


@pytest.mark.integration
class TestLineSegmentsAndWaypointsEndpoints:
    """Verifica la creación de tramos (segmentos) directos y la edición de sus waypoints."""

    def test_create_line_segment_connects_new_station_successfully(self, api_client, minimal_network, station_factory):
        """Conecta una nueva estación al final de la línea mediante api_create_line_segment."""
        line = minimal_network["line_1"]
        st_beta = minimal_network["st_beta"]
        st_nueva = station_factory(name="Estación Prolongación", x=2000.0, y=1000.0)

        payload = {
            "line_code": line.code,
            "from_station_id": st_beta.id,
            "to_station_id": st_nueva.id,
            "waypoints": [[1750.0, 1000.0]],
        }
        resp = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_stops"] == 3

        ls_new = LineStation.objects.get(line=line, station=st_nueva)
        assert ls_new.sequence == 2
        assert ls_new.waypoints == [[1750.0, 1000.0]]

    def test_create_line_segment_duplicate_contiguous_rejected(self, api_client, minimal_network):
        """Rechaza la creación de un tramo directo contiguo si ya existe entre esas dos estaciones."""
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]
        st_beta = minimal_network["st_beta"]

        payload = {
            "line_code": line.code,
            "from_station_id": st_alfa.id,
            "to_station_id": st_beta.id,
        }
        resp = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Ya existe un tramo directo" in resp.json()["error"]

    def test_create_line_segment_self_connection_rejected(self, api_client, minimal_network):
        """Rechaza conectar una estación consigo misma."""
        line = minimal_network["line_1"]
        st_alfa = minimal_network["st_alfa"]

        payload = {
            "line_code": line.code,
            "from_station_id": st_alfa.id,
            "to_station_id": st_alfa.id,
        }
        resp = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "No se puede conectar una estación consigo misma" in resp.json()["error"]

    def test_create_line_segment_validates_entities_existence_and_numeric_ids(self, api_client, minimal_network):
        """Valida que la línea y estaciones existan y que los IDs sean números enteros válidos."""
        # Línea inexistente
        resp1 = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps({"line_code": "NO_EXISTE", "from_station_id": 1, "to_station_id": 2}),
            content_type="application/json",
        )
        assert resp1.status_code == 400
        assert "no existe" in resp1.json()["error"]

        # Estación inexistente
        resp2 = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps({"line_code": "1", "from_station_id": 99999, "to_station_id": minimal_network["st_alfa"].id}),
            content_type="application/json",
        )
        assert resp2.status_code == 400
        assert "no existen en la red" in resp2.json()["error"]

        # IDs no numéricos
        resp3 = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps({"line_code": "1", "from_station_id": "abc", "to_station_id": "xyz"}),
            content_type="application/json",
        )
        assert resp3.status_code == 400
        assert "deben ser numéricos" in resp3.json()["error"]

    def test_update_segment_waypoints_success_and_validation(self, api_client, minimal_network):
        """Verifica la actualización de waypoints y el rechazo de formatos no válidos."""
        ls = minimal_network["ls_1_0"]

        # Éxito con lista válida de pares [x, y]
        resp_ok = api_client.post(
            f"/api/line-segments/{ls.id}/waypoints/",
            data=json.dumps({"waypoints": [[1100.0, 1050.5], [1200.0, 1080.0]]}),
            content_type="application/json",
        )
        assert resp_ok.status_code == 200
        ls.refresh_from_db()
        assert ls.waypoints == [[1100.0, 1050.5], [1200.0, 1080.0]]
        assert ls.line.is_custom_modified is True

        # Rechazo cuando waypoints no es una lista
        resp_bad = api_client.post(
            f"/api/line-segments/{ls.id}/waypoints/",
            data=json.dumps({"waypoints": "coordenadas_en_cadena"}),
            content_type="application/json",
        )
        assert resp_bad.status_code == 400
        assert "debe ser una lista de pares [x, y]" in resp_bad.json()["error"]

    def test_delete_station_endpoint(self, api_client, minimal_network, station_factory):
        """Elimina una estación existente y verifica la limpieza de LineStation y consistencia."""
        st_del = station_factory(name="Estación Para Borrar", x=3000.0, y=3000.0)
        line = minimal_network["line_1"]
        LineStation.objects.create(line=line, station=st_del, sequence=5, branch="main")

        resp = api_client.post(f"/api/stations/{st_del.id}/delete/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deleted"] is True
        assert not Station.objects.filter(id=st_del.id).exists()
        assert not LineStation.objects.filter(station_id=st_del.id).exists()

    def test_remove_correspondence_endpoint(self, api_client, minimal_network):
        """Quita una correspondencia de una estación y actualiza is_transfer."""
        st_alfa = minimal_network["st_alfa"]
        line_2 = minimal_network["line_2"]

        # Alfa inicialmente solo está en Línea 1
        # Añadir a Línea 2
        resp_add = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "target_line_code": line_2.code}),
            content_type="application/json",
        )
        assert resp_add.status_code == 200
        st_alfa.refresh_from_db()
        assert st_alfa.is_transfer is True

        # Ahora quitar de Línea 2
        resp_rem = api_client.post(
            "/api/correspondences/remove/",
            data=json.dumps({"action": "remove", "station_id": st_alfa.id, "target_line_code": line_2.code}),
            content_type="application/json",
        )
        assert resp_rem.status_code == 200
        data_rem = resp_rem.json()
        assert data_rem["ok"] is True
        assert data_rem["removed"] is True

        st_alfa.refresh_from_db()
        assert st_alfa.is_transfer is False

    def test_remove_correspondence_multi_branch_and_terminal_cleanup(self, api_client, line_factory, station_factory):
        """
        Prueba de regresión: Desconectar una correspondencia en una estación con múltiples líneas,
        ramas y condición terminal, garantizando:
        - Renumeración sin huecos ni colisiones unique_together en todas las ramas.
        - Limpieza recíproca en terminal_lines y recalculo de is_terminal.
        - Mantenimiento coherente de is_transfer cuando aún quedan >= 2 líneas.
        """
        line_1 = line_factory(code="L1X", name="Línea 1 Expresa", color="#EF4444")
        line_2 = line_factory(code="L2X", name="Línea 2 Expresa", color="#3B82F6")
        line_3 = line_factory(code="L3X", name="Línea 3 Expresa", color="#22C55E")

        st_hub = station_factory(name="Mega Nodo Intermodal", x=1500.0, y=1500.0)
        st_hub.terminal_lines = [line_2.code, line_3.code]
        st_hub.is_terminal = True
        st_hub.is_transfer = True
        st_hub.save()

        st_aux1 = station_factory(name="Parada Intermedia L2 A", x=1600.0, y=1500.0)
        st_aux2 = station_factory(name="Parada Intermedia L2 B", x=1700.0, y=1500.0)
        st_branch = station_factory(name="Ramal Norte L2", x=1500.0, y=1800.0)

        # Asociar st_hub a Line 1, Line 2 y Line 3
        LineStation.objects.create(line=line_1, station=st_hub, sequence=0, branch="main")
        LineStation.objects.create(line=line_3, station=st_hub, sequence=0, branch="main")

        # En Line 2: st_hub es sequence 0, luego aux1 (1), aux2 (2); y un ramal 'north' con st_branch (0)
        LineStation.objects.create(line=line_2, station=st_hub, sequence=0, branch="main")
        LineStation.objects.create(line=line_2, station=st_aux1, sequence=1, branch="main")
        LineStation.objects.create(line=line_2, station=st_aux2, sequence=2, branch="main")
        LineStation.objects.create(line=line_2, station=st_branch, sequence=0, branch="north")

        # 1. Desconectar st_hub de Line 2
        resp = api_client.post(
            "/api/correspondences/",
            data=json.dumps({"action": "remove", "station_id": st_hub.id, "target_line_code": line_2.code}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["removed"] is True

        # Verificar que st_hub ya no está en Line 2
        assert not LineStation.objects.filter(line=line_2, station=st_hub).exists()

        # Verificar renumeración de main en Line 2: aux1 debe ser sequence 0 y aux2 sequence 1
        ls_aux1 = LineStation.objects.get(line=line_2, station=st_aux1)
        ls_aux2 = LineStation.objects.get(line=line_2, station=st_aux2)
        assert ls_aux1.sequence == 0
        assert ls_aux2.sequence == 1

        # El ramal north debe permanecer intacto con sequence 0
        ls_branch = LineStation.objects.get(line=line_2, station=st_branch)
        assert ls_branch.sequence == 0
        assert ls_branch.branch == "north"

        # Verificar terminal_lines: line_2.code debe haber sido eliminado, pero line_3.code permanece
        st_hub.refresh_from_db()
        assert line_2.code not in st_hub.terminal_lines
        assert line_3.code in st_hub.terminal_lines
        assert st_hub.is_terminal is True

        # Como st_hub todavía pertenece a Line 1 y Line 3 (2 líneas en total), is_transfer debe seguir en True
        assert st_hub.is_transfer is True

        # 2. Desconectar st_hub de Line 3
        resp2 = api_client.post(
            "/api/correspondences/",
            data=json.dumps({"action": "remove", "station_id": st_hub.id, "target_line_code": line_3.code}),
            content_type="application/json",
        )
        assert resp2.status_code == 200

        st_hub.refresh_from_db()
        # Ahora solo pertenece a Line 1 (1 línea): is_transfer pasa a False
        assert st_hub.is_transfer is False
        assert line_3.code not in st_hub.terminal_lines
        assert st_hub.terminal_lines == []
        assert st_hub.is_terminal is False

    def test_create_segment_between_independent_stations_orthogonal(self, api_client, minimal_network, station_factory):
        """Conecta dos estaciones independientes calculando trazo ortogonal automático (90° o 180°)."""
        line = minimal_network["line_2"]
        st_indep_1 = station_factory(name="Independiente Norte", x=2100.0, y=1000.0)
        st_indep_2 = station_factory(name="Independiente Sur", x=2600.0, y=1400.0)

        payload = {
            "line_code": line.code,
            "from_station_id": st_indep_1.id,
            "to_station_id": st_indep_2.id,
        }
        resp = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # |dx| = 500 >= |dy| = 400 -> orientación horizontal (180°), corner en [st2.x, st1.y] = [2600.0, 1000.0]
        ls_start = LineStation.objects.get(line=line, station=st_indep_2)
        # segment_wps was calculated as [[2600.0, 1000.0]]
        assert len(ls_start.waypoints) == 1
        assert ls_start.waypoints[0] == [2600.0, 1000.0]
