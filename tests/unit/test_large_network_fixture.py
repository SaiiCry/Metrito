"""
Pruebas Unitarias del Fixture de Red de Gran Tamaño (large_network_factory / large_network).
Valida:
1. Validación estricta de parámetros con errores explícitos (ValueError).
2. Generación rápida de cientos de estaciones y LineStation (< 1.0s).
3. Cumplimiento de la restricción unique_together = [('line', 'branch', 'sequence')].
4. Reciprocidad de correspondencias y terminal_lines coherentes.
5. Icon tags permitidos exclusivamente según models.py.
6. Soporte de múltiples ramales por línea (branches_per_line >= 1).
"""

import time
import pytest
from network.models import Station, TransitLine, LineStation
from tests.conftest import ALLOWED_ICON_TAGS


@pytest.mark.unit
class TestLargeNetworkFixture:
    """Suite de validación de la fábrica parametrizable de red grande."""

    def test_large_network_parameter_validation_raises_value_error(self, large_network_factory):
        """Verifica que parámetros inválidos lancen ValueError descriptivo."""
        # metro_lines < 1
        with pytest.raises(ValueError, match="metro_lines debe ser un entero >= 1"):
            large_network_factory(metro_lines=0)

        # brt_lines < 0
        with pytest.raises(ValueError, match="brt_lines debe ser un entero >= 0"):
            large_network_factory(brt_lines=-1)

        # stations_per_line < 2
        with pytest.raises(ValueError, match="stations_per_line debe ser un entero >= 2"):
            large_network_factory(stations_per_line=1)

        # branches_per_line < 1
        with pytest.raises(ValueError, match="branches_per_line debe ser un entero >= 1"):
            large_network_factory(branches_per_line=0)

        # transfer_ratio fuera de rango [0.0, 0.8]
        with pytest.raises(ValueError, match="transfer_ratio debe ser un float entre 0.0 y 0.8"):
            large_network_factory(transfer_ratio=0.95)

    def test_large_network_generation_speed_and_hundreds_of_stations(self, large_network_factory):
        """
        Verifica que el fixture genere cientos de estaciones y paradas
        en menos de 1.0 segundo (alta velocidad mediante bulk_create).
        """
        t0 = time.perf_counter()
        # 8 líneas de metro + 4 de BRT, 25 estaciones por línea = ~300 LineStation
        bundle = large_network_factory(
            metro_lines=8,
            brt_lines=4,
            stations_per_line=25,
            branches_per_line=2,
            transfer_ratio=0.20,
            prefix="perf",
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"La generación tardó demasiado: {elapsed:.3f}s (máximo 1.0s)"
        assert bundle["total_lines_count"] == 12
        assert bundle["total_stations_count"] >= 200, f"Debe cubrir cientos de estaciones (obtenido: {bundle['total_stations_count']})"
        assert bundle["total_line_stations_count"] >= 300, f"Debe generar cientos de LineStation (obtenido: {bundle['total_line_stations_count']})"

    def test_large_network_unique_together_sequences(self, large_network):
        """
        Verifica que todos los LineStation de la red grande respeten
        unique_together = [('line', 'branch', 'sequence')] sin huecos ni duplicados.
        """
        by_line_and_branch = large_network["by_line_and_branch"]

        for line_code, branches in by_line_and_branch.items():
            for branch_name, stops in branches.items():
                assert len(stops) >= 2
                seqs = [ls.sequence for ls in stops]
                assert len(seqs) == len(set(seqs)), f"Secuencias duplicadas en {line_code} rama {branch_name}"
                expected = list(range(len(stops)))
                assert seqs == expected, f"Secuencias no consecutivas en {line_code} rama {branch_name}"

    def test_large_network_transfer_stations_reciprocity(self, large_network):
        """
        Verifica que las estaciones de correspondencia tengan is_transfer=True
        y terminal_lines recíprocas con las líneas que las sirven.
        """
        transfer_stations = large_network["transfer_stations"]
        assert len(transfer_stations) >= 2

        for st in transfer_stations:
            assert st.is_transfer is True
            served_lines = set(LineStation.objects.filter(station=st).values_list("line__code", flat=True))
            assert len(served_lines) >= 2, f"La estación de transferencia {st.name} debe pertenecer a >= 2 líneas"
            for code in served_lines:
                assert code in st.terminal_lines, f"Línea {code} no aparece en terminal_lines de {st.name}"

    def test_large_network_icon_tags_validity(self, large_network):
        """Verifica que todos los icon_tags pertenezcan al conjunto permitido de models.py."""
        allowed_set = set(ALLOWED_ICON_TAGS)
        for st in large_network["all_stations"]:
            for tag in st.icon_tags:
                assert tag in allowed_set, f"Tag no permitido: {tag}"
