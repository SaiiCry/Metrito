"""
Pruebas Unitarias para el Módulo de Métricas de Flujo Anual de Usuarios (SMyT).
Verifica cálculos de afluencia anual real vs. proyectada para 35 millones de habitantes:
1. Proyección demográfica por línea basada en jerarquía (metro vs. BRT).
2. Cálculo de pasajeros en día laboral y hora punta.
3. Reparto modal del sistema (Metro ~78%, BRT ~22%).
4. Resumen y ranking de líneas más demandadas.
5. Escalabilidad con población variable.
"""

import pytest
from network.ridership import (
    calculate_line_ridership,
    get_network_ridership_summary,
    METROPOLITAN_POPULATION,
    TOTAL_SYSTEM_ANNUAL_DEMAND_MILLIONS,
)


@pytest.mark.unit
class TestRidershipMetrics:
    """Suite de validación analítica de la demanda anual del sistema."""

    def test_calculate_line_ridership_metro_line(self):
        """Verifica el cálculo para una línea troncal de metro convencional."""
        line_data = {
            "code": "1",
            "name": "Línea 1 Metro",
            "network_type": "metro",
            "line_subtype": "convencional",
            "length_km": 18.5,
            "operational_stations_count": 20,
            "frequency_seconds": 120,
            "annual_ridership_millions": 280.0,
            "is_circular": False,
        }
        metrics = calculate_line_ridership(line_data, metro_population=35_000_000)

        assert metrics["line_code"] == "1"
        assert metrics["network_type"] == "metro"
        assert metrics["real_annual_ridership_millions"] == 280.0
        assert metrics["projected_annual_ridership_millions"] > 50.0
        assert 0.5 <= metrics["real_vs_projected_ratio"] <= 3.0
        assert metrics["daily_passengers_weekday"] > 500_000
        assert metrics["peak_hour_passengers"] > 50_000
        assert metrics["passengers_per_km_millions"] > 10.0

    def test_calculate_line_ridership_brt_line(self):
        """Verifica que el modelo aplique menor ponderación modal al autobús articulado BRT."""
        brt_data = {
            "code": "S1",
            "name": "Sistema 1 BRT",
            "network_type": "bus_articulado",
            "line_subtype": "bus_articulado",
            "length_km": 14.0,
            "operational_stations_count": 16,
            "frequency_seconds": 240,
            "annual_ridership_millions": 65.0,
        }
        metro_data = {
            "code": "2",
            "name": "Línea 2 Metro",
            "network_type": "metro",
            "line_subtype": "convencional",
            "length_km": 14.0,
            "operational_stations_count": 16,
            "frequency_seconds": 240,
            "annual_ridership_millions": 150.0,
        }

        m_brt = calculate_line_ridership(brt_data, metro_population=35_000_000)
        m_metro = calculate_line_ridership(metro_data, metro_population=35_000_000)

        # A igualdad de longitud y estaciones, el metro debe tener mayor capacidad proyectada
        assert m_metro["projected_annual_ridership_millions"] > m_brt["projected_annual_ridership_millions"]

    def test_network_ridership_summary(self, large_network):
        """Verifica la generación del balance global de red con large_network."""
        summary = get_network_ridership_summary(
            large_network["all_lines"],
            metro_population=35_000_000,
        )

        assert summary["metropolitan_population"] == 35_000_000
        assert summary["total_annual_demand_projected_millions"] == TOTAL_SYSTEM_ANNUAL_DEMAND_MILLIONS
        assert summary["total_annual_ridership_real_millions"] > 0
        assert summary["metro_annual_millions"] > 0
        assert summary["brt_annual_millions"] > 0
        assert len(summary["top_5_lines_by_ridership"]) <= 5
        assert summary["lines_count"] == large_network["total_lines_count"]

    def test_population_scaling(self):
        """Verifica que la proyección escale linealmente con la población."""
        line_data = {
            "code": "1",
            "name": "Línea 1",
            "network_type": "metro",
            "line_subtype": "convencional",
            "length_km": 20.0,
            "operational_stations_count": 22,
            "frequency_seconds": 150,
            "annual_ridership_millions": 200.0,
        }
        m_35m = calculate_line_ridership(line_data, metro_population=35_000_000)
        m_70m = calculate_line_ridership(line_data, metro_population=70_000_000)

        assert round(m_70m["projected_annual_ridership_millions"] / m_35m["projected_annual_ridership_millions"], 1) == 2.0
