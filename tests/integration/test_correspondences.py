"""
Pruebas de Integración para el Módulo de Correspondencias y Transbordos.
Verifica:
- POST /api/correspondences/create/
- Reglas de correspondencia entre distintas líneas.
- Rechazo estricto de transferencias intra-línea y auto-correspondencia.
- Preservación de nombres limpios sin sufijos de selectores.
- Reciprocidad en terminal_lines (con xfail documentado según especificación).
"""

import json
import pytest
from network.models import Station, TransitLine, LineStation


@pytest.mark.integration
class TestCorrespondencesEndpoint:
    """Verifica la creación y validación de correspondencias de transbordo."""

    def test_create_correspondence_between_two_stations_different_lines(self, api_client, minimal_network):
        """
        Escenario 2: Conectar dos estaciones existentes de líneas distintas como nodo de transferencia.
        - st_alfa (Línea 1) y st_gamma (Línea 2)
        - Ambas quedan con is_transfer=True
        - LineStation.correspondences_text se sincroniza a '1/2'
        """
        st_alfa = minimal_network["st_alfa"]
        st_gamma = minimal_network["st_gamma"]

        payload = {
            "station_id": st_alfa.id,
            "station_id_2": st_gamma.id,
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["is_transfer"] is True
        assert data["combined_lines"] == ["1", "2"]

        st_alfa.refresh_from_db()
        st_gamma.refresh_from_db()
        assert st_alfa.is_transfer is True
        assert st_gamma.is_transfer is True

        # Verificar correspondences_text en los segmentos
        for st in [st_alfa, st_gamma]:
            for ls in LineStation.objects.filter(station=st):
                assert ls.correspondences_text == "1/2"

    def test_create_correspondence_assigning_station_to_new_line(self, api_client, minimal_network):
        """
        Escenario 1: Asignar una estación existente a una nueva línea destino.
        - st_alfa (pertenece a Línea 1) se conecta a Línea 2.
        - Se crea LineStation en Línea 2.
        - st_alfa.is_transfer = True.
        - correspondences_text = '1/2'.
        """
        st_alfa = minimal_network["st_alfa"]
        line_2 = minimal_network["line_2"]

        payload = {
            "station_id": st_alfa.id,
            "target_line_code": line_2.code,
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["is_transfer"] is True
        assert data["served_lines"] == ["1", "2"]

        st_alfa.refresh_from_db()
        assert st_alfa.is_transfer is True
        assert LineStation.objects.filter(line=line_2, station=st_alfa).exists()

    def test_reject_intra_line_correspondence_same_station_target_line(self, api_client, minimal_network):
        """Rechaza intentar crear correspondencia de una estación con la línea a la que YA pertenece."""
        st_alfa = minimal_network["st_alfa"]  # Ya pertenece a Línea 1

        payload = {
            "station_id": st_alfa.id,
            "target_line_code": "1",
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "No se puede crear correspondencia entre la misma línea" in resp.json()["error"]

    def test_reject_intra_line_correspondence_two_stations_same_sole_line(self, api_client, minimal_network):
        """Rechaza intentar crear correspondencia entre dos estaciones que pertenecen únicamente a la misma línea."""
        st_alfa = minimal_network["st_alfa"]  # Línea 1
        st_beta = minimal_network["st_beta"]    # Línea 1

        payload = {
            "station_id": st_alfa.id,
            "station_id_2": st_beta.id,
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "No se puede crear correspondencia entre la misma línea" in resp.json()["error"]

    def test_reject_correspondence_station_with_itself(self, api_client, minimal_network):
        """Rechaza intentar crear correspondencia de una estación consigo misma."""
        st_alfa = minimal_network["st_alfa"]

        payload = {
            "station_id": st_alfa.id,
            "station_id_2": st_alfa.id,
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "No se puede crear correspondencia de una estación consigo misma" in resp.json()["error"]

    def test_reject_correspondence_insufficient_or_non_existent_entities(self, api_client, minimal_network):
        """Verifica rechazo con 400 cuando faltan datos o las entidades no existen."""
        # Estación inexistente con target_line
        resp1 = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": 999999, "target_line_code": "1"}),
            content_type="application/json",
        )
        assert resp1.status_code == 400
        assert "La estación no existe" in resp1.json()["error"]

        # Línea inexistente
        resp2 = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": minimal_network["st_alfa"].id, "target_line_code": "LINEA_FANTASMA"}),
            content_type="application/json",
        )
        assert resp2.status_code == 400
        assert "no existe" in resp2.json()["error"]

        # Parámetros insuficientes
        resp3 = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"description": "sin estaciones ni lineas"}),
            content_type="application/json",
        )
        assert resp3.status_code == 400
        assert "Parámetros insuficientes" in resp3.json()["error"]

    def test_correspondence_preserves_clean_station_names_without_modal_artifacts(self, api_client, minimal_network):
        """
        Requisito UI / Integridad: La creación libre de correspondencias basada en IDs
        no debe alterar el nombre de las estaciones con sufijos espurios tipo ' (1)'.
        """
        st_alfa = minimal_network["st_alfa"]
        st_gamma = minimal_network["st_gamma"]
        assert st_alfa.name == "Alfa"
        assert st_gamma.name == "Gamma"

        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "station_id_2": st_gamma.id}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        st_alfa.refresh_from_db()
        st_gamma.refresh_from_db()
        assert st_alfa.name == "Alfa"
        assert st_gamma.name == "Gamma"
        assert "(" not in st_alfa.name
        assert "(" not in st_gamma.name

    def test_correspondence_reciprocity_in_terminal_lines(self, api_client, minimal_network):
        """
        Regla de negocio: 'Las correspondencias deben ser recíprocas en terminal_lines'.
        Si la estación Alfa es terminal de la Línea 1 (terminal_lines=['1']) y la estación Gamma
        es terminal de la Línea 2 (terminal_lines=['2']), al vincularlas en correspondencia
        ambas deben reflejar de forma recíproca las líneas terminales correspondientes.
        """
        st_alfa = minimal_network["st_alfa"]
        st_gamma = minimal_network["st_gamma"]
        st_alfa.terminal_lines = ["1"]
        st_alfa.is_terminal = True
        st_alfa.save(update_fields=["terminal_lines", "is_terminal"])

        st_gamma.terminal_lines = ["2"]
        st_gamma.is_terminal = True
        st_gamma.save(update_fields=["terminal_lines", "is_terminal"])

        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "station_id_2": st_gamma.id}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        st_alfa.refresh_from_db()
        st_gamma.refresh_from_db()

        # Comportamiento esperado por la regla de negocio:
        assert set(st_alfa.terminal_lines) == {"1", "2"}
        assert set(st_gamma.terminal_lines) == {"1", "2"}

    def test_correspondence_root_url_and_line_alias(self, api_client, minimal_network):
        """Verifica que /api/correspondences/ acepte prefijos como 'Línea 2' y funcione vía endpoint raíz."""
        st_beta = minimal_network["st_beta"]
        payload = {
            "station_id": st_beta.id,
            "target_line_code": "Línea 2",
        }
        resp = api_client.post(
            "/api/correspondences/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        st_beta.refresh_from_db()
        assert st_beta.is_transfer is True

    def test_remove_correspondence_disconnects_line_and_resets_transfer(self, api_client, minimal_network):
        """Verifica que action='remove' desconecte la estación de la línea y actualice is_transfer adecuadamente."""
        st_alfa = minimal_network["st_alfa"]
        line_2 = minimal_network["line_2"]

        # 1. Agregar a Línea 2
        resp_add = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "target_line_code": line_2.code}),
            content_type="application/json",
        )
        assert resp_add.status_code == 200
        st_alfa.refresh_from_db()
        assert st_alfa.is_transfer is True

        # 2. Desconectar de Línea 2 con action='remove'
        resp_rm = api_client.post(
            "/api/correspondences/",
            data=json.dumps({
                "action": "remove",
                "station_id": st_alfa.id,
                "target_line_code": line_2.code,
            }),
            content_type="application/json",
        )
        assert resp_rm.status_code == 200
        data_rm = resp_rm.json()
        assert data_rm["ok"] is True
        assert data_rm["removed"] is True

        st_alfa.refresh_from_db()
        # Solo pertenece a Línea 1 nuevamente, por lo que no es de transferencia
        assert st_alfa.is_transfer is False
        assert not LineStation.objects.filter(line=line_2, station=st_alfa).exists()

    def test_create_multiple_correspondences_at_once_success(self, api_client, minimal_network, line_factory):
        """
        Permite vincular más de una correspondencia simultáneamente mediante target_line_codes.
        Verifica que se creen los LineStation en cada línea, se marque is_transfer y se sincronice correspondences_text.
        """
        st_alfa = minimal_network["st_alfa"]  # Ya en Línea 1
        l3 = line_factory(code="3", name="Línea 3", color="#10B981")
        l4 = line_factory(code="4", name="Línea 4", color="#F59E0B")
        l5 = line_factory(code="5", name="Línea 5", color="#8B5CF6")

        payload = {
            "station_id": st_alfa.id,
            "target_line_codes": ["3", "4", "5"],
        }
        resp = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["is_transfer"] is True
        assert set(data["added_lines"]) == {"3", "4", "5"}
        assert set(data["served_lines"]) == {"1", "3", "4", "5"}
        assert data["total_lines_count"] == 4

        st_alfa.refresh_from_db()
        assert st_alfa.is_transfer is True
        for code in ["1", "3", "4", "5"]:
            assert LineStation.objects.filter(station=st_alfa, line__code=code).exists()

    def test_enforce_maximum_10_correspondences_per_station(self, api_client, minimal_network, line_factory):
        """
        Regla de negocio: Una estación puede tener un máximo de 10 correspondencias/líneas.
        - Se permite conectar hasta 10 líneas.
        - Intentar agregar una 11va línea es rechazado con status 400 y mensaje descriptivo.
        """
        st_alfa = minimal_network["st_alfa"]  # Ya en Línea 1 (1 línea)
        line_2 = minimal_network["line_2"]    # Línea 2 ya existe (código '2')

        # Crear 8 líneas adicionales para llegar a 10 (Línea 2 + L3..L10)
        line_codes = [line_2.code]
        for i in range(3, 11):
            code = str(i)
            line_factory(code=code, name=f"Línea {code}")
            line_codes.append(code)

        # Conectar las 9 líneas adicionales en batch -> Total 10 líneas
        resp_batch = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "target_line_codes": line_codes}),
            content_type="application/json",
        )
        assert resp_batch.status_code == 200
        data_batch = resp_batch.json()
        assert data_batch["total_lines_count"] == 10
        assert len(data_batch["served_lines"]) == 10

        # Crear la 11va línea (L11)
        line_factory(code="11", name="Línea 11")

        # Intentar conectar la 11va línea debe ser rechazado
        resp_overflow = api_client.post(
            "/api/correspondences/create/",
            data=json.dumps({"station_id": st_alfa.id, "target_line_code": "11"}),
            content_type="application/json",
        )
        assert resp_overflow.status_code == 400
        err_msg = resp_overflow.json()["error"]
        assert "Límite alcanzado" in err_msg or "máximo permitido de 10 correspondencias" in err_msg
        assert not LineStation.objects.filter(station=st_alfa, line__code="11").exists()
