"""
Módulo de Análisis y Métricas de Flujo Anual de Usuarios (SMyT).
Calcula la demanda real registrada vs. la proyección demográfica aproximada
para una megalópolis con una población de 35 millones de habitantes.

Modelo de Demanda Metropolitano:
- Población del área metropolitana: 35,000,000 habitantes.
- Tasa de generación de viajes masivos: 130 viajes/persona/año.
- Demanda total del sistema estructurante: ~4,550 millones de viajes/año.
- Reparto modal:
  * Red de Metro (22 convencionales + 7 alimentadoras): ~78% de cuota.
  * Red de Autobuses Articulados (BRT Sistemas 1-5): ~22% de cuota.
"""

from typing import Dict, Any, List, Optional


METROPOLITAN_POPULATION = 35_000_000
ANNUAL_TRIPS_PER_CAPITA = 130.0
TOTAL_SYSTEM_ANNUAL_DEMAND_MILLIONS = (METROPOLITAN_POPULATION * ANNUAL_TRIPS_PER_CAPITA) / 1_000_000.0  # 4,550 M


def _get_val(obj, attr: str, default=None):
    """Extrae un valor de forma agnóstica de una instancia Django o un diccionario."""
    if hasattr(obj, attr):
        val = getattr(obj, attr)
        return val if val is not None else default
    elif isinstance(obj, dict):
        return obj.get(attr, default)
    return default


def calculate_line_ridership(line, metro_population: int = METROPOLITAN_POPULATION) -> Dict[str, Any]:
    """
    Calcula las métricas de afluencia anual para una línea específica, comparando
    el dato real registrado con la proyección basada en una población de 35 millones.

    Parámetros:
    - line: Instancia del modelo TransitLine o diccionario equivalente.
    - metro_population: Población metropolitana base (por defecto 35,000,000).

    Retorna un diccionario estructurado con métricas anuales, diarias y por kilómetro.
    """
    total_system_demand_m = (metro_population * ANNUAL_TRIPS_PER_CAPITA) / 1_000_000.0

    code = str(_get_val(line, "code", "L"))
    name = str(_get_val(line, "name", "Línea"))
    net_type = str(_get_val(line, "network_type", "metro"))
    subtype = str(_get_val(line, "line_subtype", "convencional"))
    length_km = float(_get_val(line, "length_km", 18.0) or 18.0)
    st_count = int(_get_val(line, "operational_stations_count", 20) or 20)
    freq_sec = int(_get_val(line, "frequency_seconds", 180) or 180)
    real_annual_m = float(_get_val(line, "annual_ridership_millions", 150.0) or 150.0)

    # 1. Factor de atracción base según jerarquía del modo
    if net_type == "metro":
        base_weight = 1.0 if subtype == "convencional" else 0.58
    else:
        base_weight = 0.42  # BRT alta capacidad

    # 2. Sensibilidad a longitud y número de estaciones
    length_factor = max(0.5, (length_km / 18.0) ** 0.65)
    station_factor = max(0.5, (st_count / 20.0) ** 0.70)

    # 3. Sensibilidad a frecuencia (menor intervalo = mayor capacidad atractiva)
    freq_factor = max(0.6, (180.0 / max(60, freq_sec)) ** 0.35)

    # 4. Bonificación especial por servicio premium (ej. Línea A)
    is_circular = bool(_get_val(line, "is_circular", False))
    circular_bonus = 1.15 if is_circular else 1.0

    raw_weight = base_weight * length_factor * station_factor * freq_factor * circular_bonus

    # Estimación de cuota sobre el sistema de 34 líneas
    line_share = (raw_weight / 34.0) * (0.78 if net_type == "metro" else 0.22) * (34.0 / (29.0 * 0.78 + 5.0 * 0.42))
    projected_annual_m = round(total_system_demand_m * line_share, 2)

    # Ratio real vs proyectado
    ratio = round(real_annual_m / max(1.0, projected_annual_m), 3)

    # Pasajeros promedio en día laboral (asumiendo ~300 días equivalentes anuales)
    daily_passengers = int(round((real_annual_m * 1_000_000.0) / 300.0))
    projected_daily = int(round((projected_annual_m * 1_000_000.0) / 300.0))

    # Hora punta (típicamente 11.5% de la demanda diaria en redes densas)
    peak_hour_passengers = int(round(daily_passengers * 0.115))

    # Densidad de carga (millones de pasajeros por km de línea)
    density_pax_per_km = round(real_annual_m / max(1.0, length_km), 2)

    return {
        "line_code": code,
        "line_name": name,
        "network_type": net_type,
        "line_subtype": subtype,
        "length_km": round(length_km, 2),
        "stations_count": st_count,
        "real_annual_ridership_millions": real_annual_m,
        "projected_annual_ridership_millions": projected_annual_m,
        "real_vs_projected_ratio": ratio,
        "daily_passengers_weekday": daily_passengers,
        "projected_daily_passengers": projected_daily,
        "peak_hour_passengers": peak_hour_passengers,
        "passengers_per_km_millions": density_pax_per_km,
        "modal_share_pct": round((real_annual_m / total_system_demand_m) * 100.0, 2),
    }


def get_network_ridership_summary(
    lines_iterable=None,
    metro_population: int = METROPOLITAN_POPULATION,
) -> Dict[str, Any]:
    """
    Genera el balance integral de afluencia para toda la red de metro y autobuses
    articulados, contrastando la demanda total real con la capacidad demográfica proyectada.
    """
    if lines_iterable is None:
        from .models import TransitLine
        lines_iterable = list(TransitLine.objects.all())
    else:
        lines_iterable = list(lines_iterable)

    line_metrics = [calculate_line_ridership(l, metro_population) for l in lines_iterable]

    total_real_m = round(sum(m["real_annual_ridership_millions"] for m in line_metrics), 2)
    total_projected_m = round(sum(m["projected_annual_ridership_millions"] for m in line_metrics), 2)

    metro_real_m = round(sum(m["real_annual_ridership_millions"] for m in line_metrics if m["network_type"] == "metro"), 2)
    brt_real_m = round(sum(m["real_annual_ridership_millions"] for m in line_metrics if m["network_type"] == "bus_articulado"), 2)

    total_daily_passengers = sum(m["daily_passengers_weekday"] for m in line_metrics)

    top_demanded = sorted(line_metrics, key=lambda x: x["real_annual_ridership_millions"], reverse=True)[:5]

    return {
        "metropolitan_population": metro_population,
        "total_annual_demand_projected_millions": TOTAL_SYSTEM_ANNUAL_DEMAND_MILLIONS,
        "total_annual_ridership_real_millions": total_real_m,
        "total_annual_ridership_projected_lines_millions": total_projected_m,
        "metro_annual_millions": metro_real_m,
        "brt_annual_millions": brt_real_m,
        "metro_share_pct": round((metro_real_m / max(1.0, total_real_m)) * 100.0, 1) if total_real_m > 0 else 78.0,
        "brt_share_pct": round((brt_real_m / max(1.0, total_real_m)) * 100.0, 1) if total_real_m > 0 else 22.0,
        "system_daily_weekday_passengers": total_daily_passengers,
        "annual_trips_per_capita": round((total_real_m * 1_000_000.0) / metro_population, 1),
        "lines_count": len(line_metrics),
        "top_5_lines_by_ridership": [
            {
                "code": item["line_code"],
                "name": item["line_name"],
                "annual_millions": item["real_annual_ridership_millions"],
                "daily_weekday": item["daily_passengers_weekday"],
            }
            for item in top_demanded
        ],
        "by_line": {m["line_code"]: m for m in line_metrics},
    }
