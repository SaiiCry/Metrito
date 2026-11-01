"""
Pruebas de Integración para Creación y Actualización de Estaciones.
Cubre el ciclo de vida del recurso Estación, validaciones de ingeniería,
estaciones huérfanas, asignación multilínea e integridad de nombres.
"""

import json
import pytest
from network.models import Station, TransitLine, LineStation
from network.views import ALLOWED_ICON_TAGS


@pytest.mark.integration
class TestStationCreationEndpoint:
    """Verifica el endpoint POST /api/stations/create/."""

    def test_create_station_valid_payload_success(self, api_client, db):
        """Verifica la creación exitosa de una estación con cálculo automático de coordenadas geográficas."""
        payload = {
            "name": "Estación Juárez Central",
            "x": 2500.0,
            "y": 1800.0,
            "infrastructure_type": "elevado",
            "operational_status": "operational",
            "depth_meters": 12.5,
            "platform_type": "lateral",
            "platform_count": 2,
            "has_psd": True,
            "icon_tags": ["aeropuerto", "centro_modal"],
        }
        resp = api_client.post(
            "/api/stations/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        st_data = data["station"]
        assert st_data["name"] == "Estación Juárez Central"
        assert st_data["x"] == 2500.0
        assert st_data["y"] == 1800.0
        assert st_data["lat"] is not None
        assert st_data["lng"] is not None
        assert st_data["is_user_created"] is True
        assert st_data["icon_tags"] == ["aeropuerto", "centro_modal"]

        # Verificar persistencia en base de datos
        station = Station.objects.get(id=st_data["id"])
        assert station.name == "Estación Juárez Central"
        assert station.is_user_created is True
        assert station.depth_meters == 12.5

    def test_create_station_name_is_mandatory(self, api_client, db):
        """Verifica que el nombre de la estación sea obligatorio y rechace cadenas vacías, espacios o campo ausente."""
        for empty_payload in [{"name": "", "x": 2000.0, "y": 1500.0},
                              {"name": "   ", "x": 2000.0, "y": 1500.0},
                              {"x": 2000.0, "y": 1500.0}]:
            resp = api_client.post(
                "/api/stations/create/",
                data=json.dumps(empty_payload),
                content_type="application/json",
            )
            assert resp.status_code == 400
            assert "error" in resp.json()
            assert "El nombre de la estación es obligatorio" in resp.json()["error"]

        assert Station.objects.count() == 0

    def test_create_orphan_station_without_lines(self, api_client, seeded_network):
        """Verifica que el editor permita crear estaciones huérfanas (lines: []) útiles para planificación."""
        payload = {
            "name": "Estación Huérfana Futurista",
            "x": 3500.0,
            "y": 2500.0,
            "lines": [],
        }
        resp = api_client.post(
            "/api/stations/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        st_id = resp.json()["station"]["id"]

        # Verificar que /api/network/ la devuelva con arreglo de líneas vacío
        resp_net = api_client.get("/api/network/")
        assert resp_net.status_code == 200
        net_data = resp_net.json()
        st_net = next((s for s in net_data["stations"] if s["id"] == st_id), None)
        assert st_net is not None
        assert st_net["lines"] == []
        assert st_net["is_transfer"] is False

    def test_create_station_assigned_to_single_line(self, api_client, minimal_network):
        """Verifica que crear una estación asignada a una línea cree su LineStation al final de la secuencia."""
        line_1 = minimal_network["line_1"]
        initial_count = LineStation.objects.filter(line=line_1).count()

        payload = {
            "name": "Estación Extremo Línea 1",
            "lines": ["1"],
        }
        resp = api_client.post(
            "/api/stations/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        st_id = resp.json()["station"]["id"]

        # Verificar LineStation creado
        ls = LineStation.objects.get(line=line_1, station_id=st_id)
        assert ls.sequence == initial_count
        assert ls.branch == "main"

        line_1.refresh_from_db()
        assert line_1.declared_stations_count == initial_count + 1

    def test_create_station_assigned_to_multiple_lines_marks_transfer(self, api_client, minimal_network):
        """Verifica que asignar una estación a 2 o más líneas durante su creación marque is_transfer=True."""
        line_1 = minimal_network["line_1"]
        line_2 = minimal_network["line_2"]

        payload = {
            "name": "Estación Intermodal Cruce",
            "lines": ["1", "2"],
        }
        resp = api_client.post(
            "/api/stations/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        st_data = resp.json()["station"]
        assert st_data["is_transfer"] is True
        assert sorted(st_data["lines"]) == ["1", "2"]

        station = Station.objects.get(id=st_data["id"])
        assert station.is_transfer is True
        assert LineStation.objects.filter(station=station).count() == 2

    def test_create_station_duplicate_code_handled_without_crashing(self, api_client, station_factory):
        """Si se proporciona un código ya existente, el backend debe evitar colisión asignando sufijo único."""
        existing = station_factory(code="st-existente", name="Existente")

        payload = {
            "code": "st-existente",
            "name": "Segunda Estación con Código Repetido",
        }
        resp = api_client.post(
            "/api/stations/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        new_code = resp.json()["station"]["code"]
        assert new_code != "st-existente"
        assert new_code.startswith("st-existente-")
        assert Station.objects.filter(code=new_code).exists()


@pytest.mark.integration
class TestStationUpdateEndpoint:
    """Verifica el endpoint POST /api/stations/<station_id>/update/."""

    def test_update_station_coordinates_recomputes_latlng(self, api_client, station_factory):
        """Verifica que actualizar (x, y) actualice latitud y longitud geográficas."""
        station = station_factory(x=1000.0, y=1000.0)
        old_lat, old_lng = station.lat, station.lng

        resp = api_client.post(
            f"/api/stations/{station.id}/update/",
            data=json.dumps({"x": 2500.0, "y": 3000.0}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        station.refresh_from_db()
        assert station.x == 2500.0
        assert station.y == 3000.0
        assert station.lat != old_lat
        assert station.lng != old_lng
        assert station.is_custom_modified is True

    def test_update_station_preserves_custom_waypoints_of_segments(self, api_client, minimal_network):
        """
        Regla crítica: Mover una estación NO debe resetear ni borrar los waypoints
        personalizados trazados por el usuario en los tramos adyacentes.
        """
        ls = minimal_network["ls_1_0"]
        ls.waypoints = [[1100.0, 1050.0], [1200.0, 1080.0]]
        ls.save(update_fields=["waypoints"])

        st = minimal_network["st_alfa"]
        resp = api_client.post(
            f"/api/stations/{st.id}/update/",
            data=json.dumps({"x": st.x + 20.0, "y": st.y + 15.0}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        ls.refresh_from_db()
        assert ls.waypoints == [[1100.0, 1050.0], [1200.0, 1080.0]]

    def test_update_station_icon_tags_validation(self, api_client, station_factory):
        """Valida que icon_tags solo acepte etiquetas permitidas y descarte las no reconocidas."""
        station = station_factory()
        payload = {
            "icon_tags": [
                "aeropuerto",
                "parque",
                "etiqueta_invalida_inventada",
                "zona_cultural",
                "aeropuerto",  # duplicado
            ]
        }
        resp = api_client.post(
            f"/api/stations/{station.id}/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        station.refresh_from_db()
        assert set(station.icon_tags) == {"aeropuerto", "parque", "zona_cultural"}
        assert "etiqueta_invalida_inventada" not in station.icon_tags

    def test_update_station_terminal_lines_validation(self, api_client, minimal_network):
        """Valida que terminal_lines solo admita códigos de línea que existan realmente."""
        st = minimal_network["st_alfa"]
        payload = {
            "terminal_lines": ["1", "999_NO_EXISTE", "2"],
        }
        resp = api_client.post(
            f"/api/stations/{st.id}/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        st.refresh_from_db()
        assert set(st.terminal_lines) == {"1", "2"}
        assert "999_NO_EXISTE" not in st.terminal_lines
        assert st.is_terminal is True

    def test_update_station_syncs_infrastructure_to_line_stations(self, api_client, minimal_network):
        """Verifica que cambiar infraestructura o estado en la estación sincronice sus registros LineStation."""
        st = minimal_network["st_alfa"]
        ls = minimal_network["ls_1_0"]
        assert ls.segment_infrastructure == "subterraneo"

        resp = api_client.post(
            f"/api/stations/{st.id}/update/",
            data=json.dumps({
                "infrastructure_type": "elevado",
                "operational_status": "construction",
                "depth_meters": 14.0,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        ls.refresh_from_db()
        assert ls.segment_infrastructure == "elevado"
        assert ls.segment_status == "construction"
        assert ls.depth_meters == 14.0

    def test_station_retains_clean_name_without_corrupted_selector_suffixes(self, api_client, station_factory):
        """
        Requisito de interfaz limpia: Las estaciones deben conservar su nombre exacto
        sin sufijos como ' (1)' o ' (8/9/19/S5)' provenientes del selector erróneo.
        """
        station = station_factory(name="Felipe Escamilla")
        resp = api_client.post(
            f"/api/stations/{station.id}/update/",
            data=json.dumps({
                "name": "Felipe Escamilla",
                "icon_tags": ["terminal"],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        station.refresh_from_db()
        assert station.name == "Felipe Escamilla"
        assert "(" not in station.name
        assert ")" not in station.name
