"""
Pruebas de Rendimiento, Consultas N+1 y Snap de Trayectoria de Línea para el Editor SMyT.
Ejecutables selectivamente:
- Rendimiento / Carga de red realista: pytest -k rendimiento
- Snap octilineal de trayectoria: pytest -k snap
"""

import json
import math
import time
import pytest
from network.models import LineStation, Station, TransitLine


@pytest.mark.integration
class TestEditorRendimiento:
    """Pruebas de latencia y conteo de consultas ORM para el editor de red."""

    def test_network_editor_load_queries_no_n_plus_one_rendimiento(
        self, api_client, seeded_network, django_assert_num_queries
    ):
        """
        Criterio de rendimiento en red de tamaño realista (34 líneas y 828 estaciones):
        - Solo lectura de estado.
        - Verificación de ausencia de consultas N+1 mediante django_assert_num_queries.
        - Tiempo máximo por endpoint con umbral fijo de 1.5 segundos.
        """
        start_time = time.perf_counter()
        with django_assert_num_queries(12):
            response = api_client.get("/api/network/")
        elapsed_seconds = time.perf_counter() - start_time

        assert response.status_code == 200
        data = response.json()
        assert len(data["lines"]) == 34
        assert len(data["stations"]) == 828

        # Umbral estricto de tiempo de respuesta para fluidez (< 1.5s en base de datos real)
        assert elapsed_seconds < 1.5, f"GET /api/network/ tardó {elapsed_seconds:.3f}s (máx 1.5s)"

    def test_editor_mixer_throughput_and_latencies_rendimiento(
        self, api_client, seeded_network
    ):
        """
        Reproduce el mezclador de estaciones/líneas de la página del editor:
        - Carga de topología general.
        - Inspección de estado de la capa de edición de usuario.
        - Actualización de parámetros de línea sin bloqueos.
        Verifica que cada endpoint responda dentro del umbral de fluidez.
        """
        # 1. Estado del editor
        t0 = time.perf_counter()
        resp_status = api_client.get("/api/editor/status/")
        t_status = time.perf_counter() - t0
        assert resp_status.status_code == 200
        assert t_status < 0.3, f"GET /api/editor/status/ excedió umbral: {t_status:.3f}s"

        # 2. Actualización de parámetros de una línea (Línea 1)
        line = TransitLine.objects.get(code="1")
        payload = {
            "name": line.name,
            "color": line.color,
            "max_speed_kmh": 70.0,
            "frequency_seconds": 150,
            "current_occupancy_pct": 80,
        }
        t1 = time.perf_counter()
        resp_line = api_client.post(
            f"/api/lines/{line.code}/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        t_line = time.perf_counter() - t1
        assert resp_line.status_code == 200
        assert t_line < 0.5, f"POST /api/lines/{line.code}/update/ excedió umbral: {t_line:.3f}s"


@pytest.mark.integration
class TestEditorSnap:
    """Pruebas de alineación angular exacta y snap de trayectorias en múltiplos de 45°."""

    def test_segment_waypoints_snap_to_octilinear_angle(self, api_client, editor_network):
        """
        Verifica que al editar la trayectoria de un tramo con snap=True,
        cada segmento y vértice intermedio quede alineado a un múltiplo exacto de 45°
        (octilineal) dentro de una tolerancia angular estricta (< 0.1°).
        """
        # Obtener el primer tramo de Metro 1
        line = editor_network["line_metro"]
        ls = LineStation.objects.filter(line=line, branch="main", sequence=0).first()
        assert ls is not None

        # Posición inicial de la estación ancla: (1000.0, 1000.0)
        anchor_x = float(ls.station.x)
        anchor_y = float(ls.station.y)

        # Enviar waypoints con ángulos arbitrarios fuera de múltiplos de 45°:
        # P1: dx=200, dy=50 -> ~14° (debe hacer snap a 0°)
        # P2: dx=150, dy=130 -> ~40.9° respecto a P1 (debe hacer snap a 45°)
        raw_waypoints = [
            [anchor_x + 200.0, anchor_y + 50.0],
            [anchor_x + 350.0, anchor_y + 180.0],
        ]

        resp = api_client.post(
            f"/api/line-segments/{ls.id}/waypoints/",
            data=json.dumps({"waypoints": raw_waypoints, "snap": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        saved_wps = data["waypoints"]
        assert len(saved_wps) == 2

        # Verificar matemáticamente que cada segmento vectorizado tenga ángulo múltiplo de 45°
        current_anchor = [anchor_x, anchor_y]
        tolerance_deg = 0.1  # Tolerancia máxima permitida en grados

        for wp in saved_wps:
            dx = wp[0] - current_anchor[0]
            dy = wp[1] - current_anchor[1]
            dist = math.hypot(dx, dy)
            assert dist > 1.0, "La distancia del segmento debe ser perceptible"

            angle_deg = math.degrees(math.atan2(dy, dx))
            # Normalizar a [0, 360)
            norm_angle = angle_deg % 360.0

            # Distancia angular al múltiplo de 45° más cercano
            diff_from_45_multiple = abs((norm_angle + 22.5) % 45.0 - 22.5)
            assert diff_from_45_multiple < tolerance_deg, (
                f"El vértice {wp} no quedó alineado a múltiplo de 45°. "
                f"Ángulo obtenido: {angle_deg:.3f}°, diferencia: {diff_from_45_multiple:.3f}°"
            )

            current_anchor = wp

    def test_line_route_waypoints_snap_angle_tolerance(self, api_client, editor_network):
        """
        Verifica el snap octilineal aplicado a través del endpoint de actualización de ruta
        (api_update_line_route) con múltiplos de 45° preservados en base de datos.
        """
        line = editor_network["line_metro"]
        stops = list(LineStation.objects.filter(line=line, branch="main").order_by("sequence"))
        assert len(stops) >= 2

        st0 = stops[0].station
        # Definir waypoints arbitrarios en la primera parada
        raw_wps = [
            [st0.x + 100.0, st0.y + 12.0],  # ~6.8° -> snap a 0°
            [st0.x + 200.0, st0.y + 115.0], # ~45° respecto a P1
        ]

        stops_payload = [
            {
                "station_id": s.station_id,
                "branch": s.branch,
                "sequence": s.sequence,
                "waypoints": raw_wps if idx == 0 else [],
                "snap": True,
            }
            for idx, s in enumerate(stops)
        ]

        resp = api_client.post(
            f"/api/lines/{line.code}/route/",
            data=json.dumps({"stops": stops_payload, "snap": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Verificar en la base de datos
        reloaded_ls0 = LineStation.objects.filter(line=line, branch="main", sequence=0).first()
        assert len(reloaded_ls0.waypoints) == 2

        anchor = [st0.x, st0.y]
        for wp in reloaded_ls0.waypoints:
            dx = wp[0] - anchor[0]
            dy = wp[1] - anchor[1]
            angle_deg = math.degrees(math.atan2(dy, dx))
            diff = abs((angle_deg % 360.0 + 22.5) % 45.0 - 22.5)
            assert diff < 0.1, f"Ángulo {angle_deg}° no está alineado a múltiplo de 45°"
            anchor = wp
