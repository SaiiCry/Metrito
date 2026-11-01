"""
Pruebas de Regresión para Bugs y Rendimiento del Backend en el Editor de Trazado.
Utiliza los nuevos fixtures de conftest.py para reproducir y verificar las correcciones
en los endpoints de actualización de líneas, trayectos con ramales, creación de tramos,
estaciones y persistencia de capas de edición.
"""

import json
import pytest
from network.models import Station, TransitLine, LineStation, UserNetworkEditLayer


@pytest.mark.integration
class TestEditorBackendRegression:
    """Verifica la resolución de bugs del backend del editor utilizando los nuevos fixtures."""

    def test_update_line_marks_custom_modified_and_exports_user_layer(self, api_client, editor_network):
        """
        Regresión Bug 1:
        Al actualizar propiedades operativas o estéticas de una línea mediante
        POST /api/lines/<line_code>/update/, la línea debe marcarse con is_custom_modified=True
        y sincronizarse en UserNetworkEditLayer (SQLite) mediante export_user_network_layer().
        """
        metro_line = editor_network["line_metro"]
        assert metro_line.is_custom_modified is False

        payload = {
            "name": "Línea 1 Metro Modificada por PCCO",
            "frequency_seconds": 120,
            "color": "#2563EB",
            "max_speed_kmh": 75.0,
        }
        resp = api_client.post(
            f"/api/lines/{metro_line.code}/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        metro_line.refresh_from_db()
        assert metro_line.name == "Línea 1 Metro Modificada por PCCO"
        assert metro_line.frequency_seconds == 120
        assert metro_line.color == "#2563EB"
        assert metro_line.is_custom_modified is True

        # Verificar persistencia en UserNetworkEditLayer
        layer = UserNetworkEditLayer.objects.filter(is_active=True).first()
        assert layer is not None
        layer_lines = layer.data.get("modified_lines", [])
        assert any(l["code"] == metro_line.code for l in layer_lines)

    def test_update_line_route_multi_branch_contiguous_sequences(self, api_client, editor_network):
        """
        Regresión Bug 2:
        Al actualizar el trayecto de una línea que contiene múltiples ramas (main y ramal_1),
        las secuencias deben asignarse de forma contigua comenzando en 0 dentro de CADA rama,
        respetando unique_together = [('line', 'branch', 'sequence')] sin saltos ni duplicados.
        """
        metro_line = editor_network["line_metro"]
        st_start = editor_network["stations"]["metro_start"]
        st_transfer = editor_network["stations"]["transfer"]
        st_end = editor_network["stations"]["metro_end"]
        st_branch = editor_network["stations"]["branch_term"]

        # Payload con paradas en rama 'main' y rama 'ramal_1'
        payload = {
            "stops": [
                {"station_id": st_start.id, "branch": "main"},
                {"station_id": st_transfer.id, "branch": "main"},
                {"station_id": st_end.id, "branch": "main"},
                {"station_id": st_transfer.id, "branch": "ramal_1"},
                {"station_id": st_branch.id, "branch": "ramal_1"},
            ],
            "terminal_station_ids": [st_start.id, st_end.id, st_branch.id],
        }

        resp = api_client.post(
            f"/api/lines/{metro_line.code}/route/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verificar secuencias en rama main: 0, 1, 2
        main_stops = list(
            LineStation.objects.filter(line=metro_line, branch="main").order_by("sequence")
        )
        assert [ls.sequence for ls in main_stops] == [0, 1, 2]

        # Verificar secuencias en rama ramal_1: 0, 1 (comienza en 0 sin saltos)
        branch_stops = list(
            LineStation.objects.filter(line=metro_line, branch="ramal_1").order_by("sequence")
        )
        assert [ls.sequence for ls in branch_stops] == [0, 1]

        # Verificar asignación de terminales
        st_start.refresh_from_db()
        st_end.refresh_from_db()
        st_branch.refresh_from_db()
        assert metro_line.code in st_start.terminal_lines
        assert metro_line.code in st_end.terminal_lines
        assert metro_line.code in st_branch.terminal_lines

    def test_api_network_data_preserves_custom_editor_network_without_reseed(self, api_client, editor_network):
        """
        Regresión Bug 3:
        Llamar a GET /api/network/ con una red personalizada en base de datos NO debe
        sobreescribir ni resetear los datos existentes cuando no existe Santa Mónica.
        """
        metro_line = editor_network["line_metro"]
        brt_line = editor_network["line_brt"]

        resp = api_client.get("/api/network/")
        assert resp.status_code == 200
        data = resp.json()

        # Debe devolver las líneas de editor_network
        retrieved_codes = [ln["code"] for ln in data["lines"]]
        assert metro_line.code in retrieved_codes
        assert brt_line.code in retrieved_codes

        # Verificar que la estación de transbordo conserva sus líneas servidas
        st_trans_id = editor_network["transfer_station"].id
        st_net = next(s for s in data["stations"] if s["id"] == st_trans_id)
        assert {metro_line.code, brt_line.code}.issubset(set(st_net["lines"]))
        assert st_net["is_transfer"] is True

    def test_create_segment_in_alternate_branch_shifts_sequences_within_branch_only(
        self, api_client, editor_network, station_factory
    ):
        """
        Regresión Bug 4:
        Al crear un nuevo tramo en un ramal alternativo ('ramal_1'), el desplazamiento
        de secuencias (_shift_sequences_forward) debe operar exclusivamente dentro de esa rama
        y no desplazar ni corromper las secuencias de la rama 'main'.
        """
        metro_line = editor_network["line_metro"]
        st_branch = editor_network["stations"]["branch_term"]

        main_seqs_before = list(
            LineStation.objects.filter(line=metro_line, branch="main")
            .order_by("sequence")
            .values_list("sequence", flat=True)
        )

        # Estación adicional en el ramal
        st_branch_prolongacion = station_factory(
            code="st-ramal-prolongacion",
            name="Prolongación Ramal",
            x=2200.0, y=1600.0,
        )

        payload = {
            "line_code": metro_line.code,
            "from_station_id": st_branch.id,
            "to_station_id": st_branch_prolongacion.id,
        }
        resp = api_client.post(
            "/api/line-segments/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Secuencias en 'main' deben permanecer estrictamente intactas
        main_seqs = list(
            LineStation.objects.filter(line=metro_line, branch="main")
            .order_by("sequence")
            .values_list("sequence", flat=True)
        )
        assert main_seqs == main_seqs_before

        # El nuevo segmento debe ubicarse en 'ramal_1' en secuencia consecutiva (2)
        ls_new = LineStation.objects.get(line=metro_line, station=st_branch_prolongacion)
        assert ls_new.branch == "ramal_1"
        assert ls_new.sequence == 2

    def test_update_station_preserves_transfer_flag_and_filters_invalid_terminals(
        self, api_client, editor_network
    ):
        """
        Regresión Bug 5:
        POST /api/stations/<id>/update/ debe permitir actualizar is_transfer y descartar
        códigos de línea inexistentes en terminal_lines.
        """
        st = editor_network["stations"]["metro_start"]
        metro_line = editor_network["line_metro"]

        payload = {
            "is_transfer": True,
            "terminal_lines": [metro_line.code, "CODIGO_FANTASMA_INEXISTENTE"],
            "icon_tags": ["aeropuerto", "tag_falso"],
        }
        resp = api_client.post(
            f"/api/stations/{st.id}/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        st.refresh_from_db()
        assert st.is_transfer is True
        assert st.terminal_lines == [metro_line.code]
        assert "CODIGO_FANTASMA_INEXISTENTE" not in st.terminal_lines
        assert st.icon_tags == ["aeropuerto"]
