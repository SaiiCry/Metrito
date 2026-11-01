"""
Pruebas de Integración para Validación de Errores HTTP y Métodos Permitidos.
Cubre sistemáticamente:
- 400 Bad Request por payloads malformados (JSONDecodeError) y campos requeridos.
- 404 Not Found por identificadores o códigos no existentes en la base de datos.
- 405 Method Not Allowed por invocación de endpoints con verbos HTTP no autorizados.
"""

import json
import pytest
from network.models import Station, TransitLine, LineStation, CityOutline


@pytest.mark.integration
class TestMalformedPayloads:
    """Verifica que todos los endpoints POST manejen JSON malformado con status 400."""

    @pytest.mark.parametrize(
        "endpoint_pattern,needs_id",
        [
            ("/api/stations/create/", None),
            ("/api/stations/{id}/update/", "station"),
            ("/api/lines/create/", None),
            ("/api/lines/{code}/update/", "line"),
            ("/api/lines/{code}/route/", "line"),
            ("/api/line-segments/create/", None),
            ("/api/line-segments/{id}/waypoints/", "segment"),
            ("/api/correspondences/create/", None),
            ("/api/city-outlines/{id}/update/", "outline"),
        ],
    )
    def test_malformed_json_returns_400(self, api_client, minimal_network, endpoint_pattern, needs_id):
        """Verifica que enviar un cuerpo que no sea JSON válido devuelva 400 con {'error': 'JSON inválido'}."""
        url = endpoint_pattern
        if needs_id == "station":
            url = url.format(id=minimal_network["st_alfa"].id)
        elif needs_id == "line":
            url = url.format(code=minimal_network["line_1"].code)
        elif needs_id == "segment":
            url = url.format(id=minimal_network["ls_1_0"].id)
        elif needs_id == "outline":
            outline = CityOutline.objects.create(code="out-test", name="Zona Test")
            url = url.format(id=outline.id)

        # Enviar bytes que no son JSON
        resp = api_client.post(
            url,
            data="{payload roto y sin cerrar: 123",
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json().get("error") == "JSON inválido"


@pytest.mark.integration
class TestNonExistentEntitiesReturn404:
    """Verifica que los endpoints que consultan por clave primaria devuelvan 404 ante IDs inexistentes."""

    def test_update_non_existent_station_returns_404(self, api_client, db):
        """POST /api/stations/999999/update/ debe retornar 404."""
        resp = api_client.post(
            "/api/stations/999999/update/",
            data=json.dumps({"name": "Nuevo Nombre"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_update_non_existent_line_returns_404(self, api_client, db):
        """POST /api/lines/LINEA_INEXISTENTE/update/ debe retornar 404."""
        resp = api_client.post(
            "/api/lines/LINEA_INEXISTENTE/update/",
            data=json.dumps({"name": "Nuevo Nombre"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_update_route_of_non_existent_line_returns_404(self, api_client, db):
        """POST /api/lines/LINEA_INEXISTENTE/route/ debe retornar 404."""
        resp = api_client.post(
            "/api/lines/LINEA_INEXISTENTE/route/",
            data=json.dumps({"stops": []}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_update_waypoints_of_non_existent_segment_returns_404(self, api_client, db):
        """POST /api/line-segments/999999/waypoints/ debe retornar 404."""
        resp = api_client.post(
            "/api/line-segments/999999/waypoints/",
            data=json.dumps({"waypoints": []}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_update_non_existent_city_outline_returns_404(self, api_client, db):
        """POST /api/city-outlines/999999/update/ debe retornar 404."""
        resp = api_client.post(
            "/api/city-outlines/999999/update/",
            data=json.dumps({"name": "Nuevo Polígono"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_toggle_non_existent_alert_returns_404(self, api_client, db):
        """POST /api/alerts/999999/toggle/ debe retornar 404."""
        resp = api_client.post("/api/alerts/999999/toggle/")
        assert resp.status_code == 404


@pytest.mark.integration
class TestDisallowedHttpMethodsReturn405:
    """Verifica que enviar un método HTTP no permitido devuelva 405 Method Not Allowed."""

    @pytest.mark.parametrize(
        "post_only_url",
        [
            "/api/stations/create/",
            "/api/lines/create/",
            "/api/line-segments/create/",
            "/api/correspondences/create/",
            "/api/editor/save/",
            "/api/editor/discard/",
            "/api/network/reset/",
            "/api/alerts/create/",
            "/api/alerts/simulate/",
        ],
    )
    def test_get_on_post_only_endpoints_returns_405(self, api_client, db, post_only_url):
        """Llamar con GET a un endpoint que exige POST debe devolver 405."""
        resp = api_client.get(post_only_url)
        assert resp.status_code == 405

    @pytest.mark.parametrize(
        "get_only_url",
        [
            "/api/network/",
            "/api/editor/status/",
            "/api/cartografia/json/",
            "/api/cartografia/svg/",
            "/api/cartografia/logo/",
        ],
    )
    def test_post_on_get_only_endpoints_returns_405(self, api_client, db, get_only_url):
        """Llamar con POST a un endpoint que exige GET debe devolver 405."""
        resp = api_client.post(get_only_url)
        assert resp.status_code == 405
