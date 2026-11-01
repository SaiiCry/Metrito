"""
Pruebas de Integración para Persistencia en Localhost, Capa de Edición y Reset de Red.
Verifica:
- POST /api/editor/save/
- GET /api/editor/status/
- POST /api/editor/discard/
- POST /api/network/reset/
- Supervivencia a reinicios simulados del servidor (seed_database con force_reset=False)
- Protección de datos maestros frente a ediciones del usuario
"""

import json
import pytest
from django.urls import reverse
from network.models import Station, TransitLine, UserNetworkEditLayer
from network.seed import seed_database


@pytest.mark.integration
class TestPersistenceAndEditorLayer:
    """Verifica la persistencia y consulta de estado de la capa de usuario."""

    def test_save_user_edits_persists_layer_in_database(self, api_client, db, station_factory, line_factory):
        """Verifica que /api/editor/save/ serialice y guarde las ediciones en UserNetworkEditLayer."""
        st_user = station_factory(code="st-persist-1", name="Estación Creada Usuario", is_user_created=True)
        ln_user = line_factory(code="L99", name="Línea Creada Usuario", is_user_created=True)
        st_mod = station_factory(code="st-mod-1", name="Estación Modificada", is_custom_modified=True)

        resp = api_client.post("/api/editor/save/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["result"]["created_stations_count"] >= 1
        assert data["result"]["created_lines_count"] >= 1

        layer = UserNetworkEditLayer.objects.filter(is_active=True).first()
        assert layer is not None
        layer_data = layer.data
        assert any(s["code"] == "st-persist-1" for s in layer_data.get("created_stations", []))
        assert any(l["code"] == "L99" for l in layer_data.get("created_lines", []))
        assert any(s["code"] == "st-mod-1" for s in layer_data.get("modified_stations", []))

    def test_editor_status_endpoint_returns_accurate_metrics(self, api_client, db, station_factory):
        """Verifica que /api/editor/status/ devuelva el conteo exacto de elementos de usuario."""
        station_factory(code="st-usr-1", is_user_created=True)
        station_factory(code="st-usr-2", is_user_created=True)
        station_factory(code="st-mod-1", is_custom_modified=True)

        resp = api_client.get("/api/editor/status/")
        assert resp.status_code == 200
        status_data = resp.json()
        assert status_data["user_stations_count"] == 2
        assert status_data["modified_stations_count"] == 1

    def test_user_edits_survive_simulated_server_restart(self, api_client, seeded_network, station_factory, line_factory):
        """
        Regla de negocio: Los cambios deben sobrevivir a reinicios del servidor local.
        Al reiniciar o recargar la app (invocando seed_database con force_reset=False),
        la base de datos existente debe protegerse y NO sobreescribir las entidades del usuario.
        """
        # 1. Crear estación y línea de usuario sobre el catálogo maestro poblado
        st_user = station_factory(code="estacion-persistente-local", name="Estación Persistente Local", is_user_created=True)
        ln_user = line_factory(code="L-PER", name="Línea Persistente Local", is_user_created=True)

        # 2. Guardar capa de edición
        resp_save = api_client.post("/api/editor/save/")
        assert resp_save.status_code == 200

        # 3. Simular reinicio de servidor local (ejecuta seed_database(force_reset=False))
        seed_result = seed_database(force_reset=False)
        assert seed_result["seeded"] is False  # No debe sobreescribir datos

        # 4. Verificar supervivencia intacta
        assert Station.objects.filter(code="estacion-persistente-local").exists()
        assert TransitLine.objects.filter(code="L-PER").exists()

    def test_network_reset_restores_master_plan(self, api_client, seeded_network, station_factory):
        """
        Verifica que POST /api/network/reset/ restaure los datos base del Plan Maestro:
        - 34 líneas
        - 828 estaciones
        """
        # Crear estación ficticia
        station_factory(code="estacion-a-borrar", name="Estación Borrable", is_user_created=True)
        assert Station.objects.filter(code="estacion-a-borrar").exists()

        resp_reset = api_client.post("/api/network/reset/")
        assert resp_reset.status_code == 200
        assert resp_reset.json()["ok"] is True

        # La base contiene únicamente las 828 estaciones del catálogo maestro
        assert Station.objects.count() == 828
        assert TransitLine.objects.count() == 34
        assert not Station.objects.filter(code="estacion-a-borrar").exists()

    def test_network_reset_preserves_user_network_edit_layer_table(self, api_client, seeded_network, station_factory):
        """
        Regla de negocio: El reset devuelve solo los datos base y no borra la capa de edición
        salvo que el reset lo indique explícitamente. UserNetworkEditLayer debe preservarse.
        """
        st_user = station_factory(code="st-layer-check", is_user_created=True)
        api_client.post("/api/editor/save/")
        assert UserNetworkEditLayer.objects.filter(is_active=True).exists()

        # Ejecutar reset de red
        resp_reset = api_client.post("/api/network/reset/")
        assert resp_reset.status_code == 200

        # La capa persiste en la tabla independiente UserNetworkEditLayer
        assert UserNetworkEditLayer.objects.filter(is_active=True).exists()

    def test_reverse_api_save_user_edits_resolves_correctly(self):
        """Verifica que el nombre de ruta 'api_save_user_edits' resuelva al endpoint configurado en urls.py."""
        url = reverse("api_save_user_edits")
        assert url == "/api/editor/save/"

    def test_user_edits_save_alias_url_accessibility(self, api_client, db):
        """
        Verifica que las rutas alias /api/user-edits/save/, /api/user-edits/discard/ y /api/editor-status/
        estén debidamente mapeadas en urls.py y respondan con 200.
        """
        resp_save = api_client.post("/api/user-edits/save/")
        assert resp_save.status_code == 200

        resp_status = api_client.get("/api/editor-status/")
        assert resp_status.status_code == 200

        resp_discard = api_client.post("/api/user-edits/discard/")
        assert resp_discard.status_code == 200
