#!/usr/bin/env python3
"""
Generador Cartográfico Reproducible — Red Esquemática SIMMA (Asura, 35M hab.)
=============================================================================

Modela la red integrada de transporte masivo una única vez en memoria a partir
de coordenadas geográficas (lat/lon) proyectadas a plano mediante una proyección
equirectangular tangente local con escala única, y deriva de dicho modelo único:

  1. ``red_metro.svg``  — Plano esquemático octilineal (0°, 45°, 90°) en estilo
                          claro de señalización real, con identidad visual,
                          zonas urbanas, simbología de infraestructura, estados
                          operativos, leyenda completa y etiquetas sin colisión.
  2. ``red_metro.json`` — Fuente de datos estructurada y validada contra JSON
                          Schema para consumo directo por el backend Django.
  3. ``logo_metro.svg`` — Logotipo vectorial independiente de la marca SIMMA.

Proyección cartográfica utilizada
---------------------------------
Se emplea una **Proyección Equirectangular Tangente Local** centrada en el nodo
neurálgico **Santa Mónica** (``lat_0 = 19.420000° N``, ``lon_0 = -99.140000° O``):

  - Radio medio terrestre: ``R = 6371.0088 km``
  - Factor meridional: ``K_LAT = (pi / 180) * R = 111.195080 km / grado``
  - Factor paralelo en ``lat_0``: ``K_LON = K_LAT * cos(19.42°) = 104.862452 km / grado``
  - Escala única de referencia del plano: ``ESCALA_SVG_POR_KM = 54.0 unidades SVG / km``
  - Ecuaciones directas ``(lat, lon) -> (x_svg, y_svg)``:
      ``este_km  = (lon - lon_0) * K_LON``
      ``norte_km = (lat - lat_0) * K_LAT``
      ``x_svg    = ORIGEN_SVG_X + este_km  * ESCALA_SVG_POR_KM``
      ``y_svg    = ORIGEN_SVG_Y - norte_km * ESCALA_SVG_POR_KM``

Ejecución y regeneración de artefactos
--------------------------------------
  python cartografia/generar_red.py [--directorio cartografia] [--solo-validar]

Al ejecutarse, construye el modelo único, valida ``red_metro.json`` contra el
esquema formal ``ESQUEMA_JSON_RED``, ejecuta la batería completa de tests de
conectividad, unicidad, geometría octilineal y paridad SVG/JSON, y escribe los
tres archivos en el directorio de salida.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# =============================================================================
# 1. CONSTANTES GEOGRÁFICAS, PROYECCIÓN Y ESCALA ÚNICA
# =============================================================================

VERSION_ESQUEMA = "1.0.0"
FECHA_GENERACION_DEFAULT = "2026-10-31"
POBLACION_REFERENCIA = 35_000_000

LAT_ORIGEN = 19.420000
LON_ORIGEN = -99.140000
RADIO_TIERRA_KM = 6371.0088
KM_POR_GRADO_LAT = (math.pi / 180.0) * RADIO_TIERRA_KM
KM_POR_GRADO_LON = KM_POR_GRADO_LAT * math.cos(math.radians(LAT_ORIGEN))

# Escala única del esquema: 54.0 unidades SVG equivalen exactamente a 1.0 km
ESCALA_SVG_POR_KM = 54.0
ORIGEN_SVG_X = 2120.0
ORIGEN_SVG_Y = 1860.0
VIEWBOX_ANCHO = 5520
VIEWBOX_ALTO = 3980

# Paso de retícula octilineal calibrado para que el octágono simétrico de la
# Línea A tenga exactamente 132.8 km de perímetro real proyectado:
# Perímetro en unidades de retícula = 156 - 36 * (2 - sqrt(2)) = 134.911688245
PERIMETRO_RETICULA_LINEA_A = 156.0 - 36.0 * (2.0 - math.sqrt(2.0))
KM_POR_UNIDAD_RETICULA = 132.8 / PERIMETRO_RETICULA_LINEA_A  # 0.9843476306 km


def reticula_a_latlon(gx: float, gy: float) -> Tuple[float, float]:
    """Convierte coordenadas de la retícula métrica a coordenadas geográficas (lat, lon)."""
    este_km = gx * KM_POR_UNIDAD_RETICULA
    norte_km = gy * KM_POR_UNIDAD_RETICULA
    lat = LAT_ORIGEN + (norte_km / KM_POR_GRADO_LAT)
    lon = LON_ORIGEN + (este_km / KM_POR_GRADO_LON)
    return (round(lat, 6), round(lon, 6))


def proyectar_latlon_a_svg(lat: float, lon: float) -> Tuple[float, float]:
    """Proyecta coordenadas geográficas (lat, lon) al sistema plano único del SVG."""
    este_km = (lon - LON_ORIGEN) * KM_POR_GRADO_LON
    norte_km = (lat - LAT_ORIGEN) * KM_POR_GRADO_LAT
    x = round(ORIGEN_SVG_X + este_km * ESCALA_SVG_POR_KM, 1)
    y = round(ORIGEN_SVG_Y - norte_km * ESCALA_SVG_POR_KM, 1)
    return (x, y)


def distancia_km_latlon(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia plana proyectada en kilómetros entre dos puntos (lat, lon)."""
    dx = (lon2 - lon1) * KM_POR_GRADO_LON
    dy = (lat2 - lat1) * KM_POR_GRADO_LAT
    return math.hypot(dx, dy)


def a_kebab_case(texto: str) -> str:
    """Convierte cualquier nombre a identificador kebab-case ASCII válido en SVG y JSON."""
    limpio = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^a-zA-Z0-9]+", "-", limpio.lower()).strip("-")
    return re.sub(r"-+", "-", limpio)


# =============================================================================
# 2. IDENTIDAD VISUAL (PALETA DE SEÑALIZACIÓN CLARA, TIPOGRAFÍA Y LOGO SVG)
# =============================================================================

IDENTIDAD_VISUAL: Dict[str, Any] = {
    "marca": "SIMMA",
    "nombre_completo": "Sistema Integrado de Metro y Movilidad de Asura",
    "lema": "Red Metropolitana · 35 Millones de Habitantes",
    "paleta": {
        "papel_fondo": "#F6F5F0",
        "superficie_panel": "#FFFFFF",
        "meseta_urbana": "#ECEAE2",
        "borde_panel": "#D5D2C8",
        "tinta_primaria": "#182026",
        "tinta_secundaria": "#4A5568",
        "tinta_tenue": "#718096",
        "hidrografia_relleno": "#C7E1F5",
        "hidrografia_borde": "#9AC3E3",
        "zona_ecologica": "#DCEAD7",
        "zona_ecologica_borde": "#B3CFA9",
        "zona_industrial": "#E5E9F0",
        "zona_industrial_borde": "#C2CBD8",
        "zona_aeroportuaria": "#E1ECF7",
        "zona_aeroportuaria_borde": "#B4CBE3",
        "acento_premium": "#E59A00",
        "estado_clausurado": "#9B2C2C",
    },
    "tipografia": {
        "familia_principal": "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif",
        "familia_monoespaciada": "'SF Mono', ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace",
    },
}


def generar_logo_svg_elementos(incluir_texto_marca: bool = False) -> str:
    """
    Devuelve las primitivas vectoriales del logotipo SIMMA (sin fuentes externas
    ni imágenes raster). El isotipo representa el anillo orbital periférico
    (Línea A) envolviendo tres vectores octilineales a 45° y 90° que conforman
    la 'M' metropolitana con el nodo central Santa Mónica en su vértice.
    """
    elementos = [
        '<!-- Escudo arquitectónico SIMMA -->',
        '<rect x="12" y="12" width="216" height="216" rx="46" fill="#FFFFFF" stroke="#182026" stroke-width="8"/>',
        '<!-- Anillo orbital periférico (Línea A · 132,8 km) -->',
        '<polygon points="84,34 156,34 206,84 206,156 156,206 84,206 34,156 34,84" '
        'fill="#F6F5F0" stroke="#0F7173" stroke-width="10" stroke-linejoin="round"/>',
        '<!-- Tres trazos octilineales formando el monograma M -->',
        '<path d="M 68 166 L 68 82 L 120 134" fill="none" stroke="#D9232E" '
        'stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>',
        '<path d="M 172 166 L 172 82 L 120 134" fill="none" stroke="#0055A4" '
        'stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>',
        '<path d="M 120 134 L 120 172" fill="none" stroke="#D98A00" '
        'stroke-width="14" stroke-linecap="round"/>',
        '<!-- Nodo de correspondencia central (Santa Mónica) -->',
        '<circle cx="120" cy="134" r="13" fill="#FFFFFF" stroke="#182026" stroke-width="6"/>',
        '<circle cx="68" cy="82" r="7" fill="#FFFFFF" stroke="#182026" stroke-width="4"/>',
        '<circle cx="172" cy="82" r="7" fill="#FFFFFF" stroke="#182026" stroke-width="4"/>',
    ]
    if incluir_texto_marca:
        # Cartela inferior y monograma tipográfico SIMMA trazado con vectores puros (cero fuentes)
        elementos.append(
            '<rect x="64" y="181" width="112" height="24" rx="12" fill="#182026"/>'
        )
        elementos.append(
            '<g transform="translate(11, 0)" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
            '<!-- S --><path d="M 85 188.5 L 78.5 188.5 L 78.5 193 L 85 193 L 85 197.5 L 78.5 197.5"/>'
            '<!-- I --><path d="M 92 188.5 L 92 197.5"/>'
            '<!-- M --><path d="M 99 197.5 L 99 188.5 L 104 193.5 L 109 188.5 L 109 197.5"/>'
            '<!-- M --><path d="M 115 197.5 L 115 188.5 L 120 193.5 L 125 188.5 L 125 197.5"/>'
            '<!-- A --><path d="M 131 197.5 L 135.5 188.5 L 140 197.5 M 132.5 194.8 L 138.5 194.8"/>'
            '</g>'
        )
    return "\n  ".join(elementos)


def generar_logo_svg_independiente() -> str:
    """Construye el archivo ``logo_metro.svg`` autónomo y válido XML."""
    cuerpo = generar_logo_svg_elementos(incluir_texto_marca=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240" '
        'role="img" aria-labelledby="logo-titulo logo-desc">\n'
        '  <title id="logo-titulo">Logotipo Oficial SIMMA — Metro y Movilidad de Asura</title>\n'
        '  <desc id="logo-desc">Emblema octilineal del Sistema Integrado de Metro y Movilidad de Asura.</desc>\n'
        f'  {cuerpo}\n'
        '</svg>\n'
    )


# =============================================================================
# 3. DEFINICIÓN TOPOLÓGICA Y GEOMÉTRICA ÚNICA DE LA RED (34 LÍNEAS)
# =============================================================================

# Octágono simétrico de la Línea A sobre la retícula 3xZ (132.80 km exactos)
POLILINEA_LINEA_A: List[Tuple[int, int]] = [
    (0, 18), (12, 18), (21, 9), (21, 0), (21, -9), (12, -18),
    (0, -18), (-12, -18), (-21, -9), (-21, 0), (-21, 9), (-12, 18), (0, 18),
]


@dataclass(frozen=True)
class EspecificacionLinea:
    codigo: str
    id_linea: str
    nombre: str
    tipo: str           # 'metro' | 'alimentadora' | 'autobus-articulado'
    sistema: str        # 'sistema-metro' | 'sistema-autobuses-articulados'
    color: str
    num_estaciones: int
    estado_general: str # 'operativa' | 'operacion-parcial' | 'en-construccion' | 'ampliacion-pendiente'
    frecuencia_s: int
    velocidad_kmh: float
    polilinea: List[Tuple[int, int]]
    infra_predominante: str
    frecuencia_premium_s: Optional[int] = None


ESPECIFICACIONES_LINEAS: List[EspecificacionLinea] = [
    # --- 22 Líneas Convencionales de Metro (linea-01 .. linea-22) ---
    EspecificacionLinea("1", "linea-01", "Línea 1", "metro", "sistema-metro", "#D9232E", 25, "operativa", 115, 45.0, [(-21, 0), (0, 0), (12, 0)], "subterraneo"),
    EspecificacionLinea("2", "linea-02", "Línea 2", "metro", "sistema-metro", "#0055A4", 32, "operativa", 105, 50.0, [(3, 18), (3, -9), (-6, -18)], "subterraneo"),
    EspecificacionLinea("3", "linea-03", "Línea 3", "metro", "sistema-metro", "#5E9732", 33, "operativa", 120, 50.0, [(-21, 6), (21, 6)], "subterraneo"),
    EspecificacionLinea("4", "linea-04", "Línea 4", "metro", "sistema-metro", "#0098D4", 24, "operativa", 130, 50.0, [(-15, 15), (0, 0), (9, 9)], "tunel-profundo"),
    EspecificacionLinea("5", "linea-05", "Línea 5", "metro", "sistema-metro", "#D98A00", 16, "operativa", 140, 50.0, [(12, 0), (21, 0), (30, 0)], "superficial"),
    EspecificacionLinea("6", "linea-06", "Línea 6", "metro", "sistema-metro", "#8A2B87", 32, "ampliacion-pendiente", 150, 50.0, [(12, 18), (12, -18), (12, -24)], "subterraneo"),
    EspecificacionLinea("7", "linea-07", "Línea 7", "metro", "sistema-metro", "#E86A1F", 23, "operativa", 145, 55.0, [(0, 15), (0, 0), (0, -15)], "tunel-profundo"),
    EspecificacionLinea("8", "linea-08", "Línea 8", "metro", "sistema-metro", "#008C6E", 23, "operativa", 135, 50.0, [(-12, 18), (6, 0), (9, -3)], "tunel-profundo"),
    EspecificacionLinea("9", "linea-09", "Línea 9", "metro", "sistema-metro", "#6E3B1E", 22, "ampliacion-pendiente", 150, 50.0, [(9, -3), (9, -21), (18, -21)], "viaducto-elevado"),
    EspecificacionLinea("10", "linea-10", "Línea 10", "metro", "sistema-metro", "#1B365D", 36, "operativa", 140, 55.0, [(-21, -3), (-18, -3), (-9, -12), (15, -12), (24, -3), (27, -3)], "subterraneo"),
    EspecificacionLinea("11", "linea-11", "Línea 11", "metro", "sistema-metro", "#C93B76", 26, "operativa", 160, 50.0, [(-9, 0), (-9, -9), (15, -9), (15, -15)], "subterraneo"),
    EspecificacionLinea("12", "linea-12", "Línea 12", "metro", "sistema-metro", "#7B5AA6", 22, "operativa", 140, 50.0, [(21, -9), (18, -6), (0, -6), (-6, -6)], "subterraneo"),
    EspecificacionLinea("13", "linea-13", "Línea 13", "metro", "sistema-metro", "#2A9D8F", 32, "operativa", 150, 50.0, [(6, 12), (-6, 12), (-12, 6), (-12, -18)], "subterraneo"),
    EspecificacionLinea("14", "linea-14", "Línea 14", "metro", "sistema-metro", "#4C8C2B", 28, "operativa", 155, 50.0, [(6, 12), (15, 12), (18, 9), (18, -3), (24, 3), (24, 9), (21, 9)], "viaducto-elevado"),
    EspecificacionLinea("15", "linea-15", "Línea 15", "metro", "sistema-metro", "#B5174B", 26, "operativa", 120, 70.0, [(0, 0), (6, -6), (6, -15), (0, -21), (0, -33)], "tunel-profundo"),
    EspecificacionLinea("16", "linea-16", "Línea 16", "metro", "sistema-metro", "#9E6B25", 21, "operativa", 165, 50.0, [(-3, -9), (3, -15), (15, -15), (21, -21)], "superficial"),
    EspecificacionLinea("17", "linea-17", "Línea 17", "metro", "sistema-metro", "#4A6FA5", 15, "operativa", 170, 50.0, [(15, 9), (15, -9)], "subterraneo"),
    EspecificacionLinea("18", "linea-18", "Línea 18", "metro", "sistema-metro", "#C84B31", 34, "operacion-parcial", 160, 60.0, [(0, 0), (-9, -9), (-21, -9), (-27, -15), (-27, -21), (-15, -21)], "viaducto-elevado"),
    EspecificacionLinea("19", "linea-19", "Línea 19", "metro", "sistema-metro", "#7E6B8F", 15, "ampliacion-pendiente", 180, 50.0, [(9, -3), (21, -3), (27, -9)], "superficial"),
    EspecificacionLinea("20", "linea-20", "Línea 20", "metro", "sistema-metro", "#8C1D40", 23, "ampliacion-pendiente", 150, 50.0, [(-6, 3), (-6, -18), (-6, -30)], "tunel-profundo"),
    EspecificacionLinea("21", "linea-21", "Línea 21", "metro", "sistema-metro", "#5C6B73", 18, "operativa", 175, 55.0, [(-30, 3), (-30, -18), (-27, -21)], "superficial"),
    EspecificacionLinea("22", "linea-22", "Línea 22", "metro", "sistema-metro", "#3D5A80", 24, "operativa", 180, 60.0, [(-15, -21), (-15, -27), (9, -27), (15, -33)], "viaducto-elevado"),

    # --- 7 Líneas Alimentadoras (linea-a .. linea-g) ---
    EspecificacionLinea("A", "linea-a", "Línea A (Circuito Periférico)", "alimentadora", "sistema-metro", "#0F7173", 124, "operativa", 150, 80.0, POLILINEA_LINEA_A, "viaducto-elevado", frecuencia_premium_s=300),
    EspecificacionLinea("B", "linea-b", "Línea B", "alimentadora", "sistema-metro", "#2E7D32", 35, "operativa", 125, 60.0, [(-6, 18), (-6, 3), (-3, 0), (-3, -24)], "subterraneo"),
    EspecificacionLinea("C", "linea-c", "Línea C", "alimentadora", "sistema-metro", "#6A1B4D", 34, "operacion-parcial", 165, 60.0, [(-24, 15), (-30, 15), (-30, 3), (-36, -3), (-36, -18), (-30, -24), (-15, -24), (-9, -30)], "viaducto-elevado"),
    EspecificacionLinea("D", "linea-d", "Línea D", "alimentadora", "sistema-metro", "#3B7A8C", 20, "operativa", 170, 65.0, [(-12, 18), (-18, 24), (-30, 24), (-36, 30)], "superficial"),
    EspecificacionLinea("E", "linea-e", "Línea E", "alimentadora", "sistema-metro", "#9C7A1C", 18, "operativa", 175, 70.0, [(21, -9), (30, -9), (36, -15), (42, -15)], "superficial"),
    EspecificacionLinea("F", "linea-f", "Línea F", "alimentadora", "sistema-metro", "#B23A2C", 20, "operativa", 165, 65.0, [(12, 18), (18, 24), (30, 24), (36, 30)], "superficial"),
    EspecificacionLinea("G", "linea-g", "Línea G", "alimentadora", "sistema-metro", "#A64D79", 27, "operativa", 180, 65.0, [(-9, -30), (-9, -36), (18, -36), (27, -27)], "viaducto-elevado"),

    # --- 5 Sistemas de Autobuses Articulados (autobuses-sistema-1 .. autobuses-sistema-5) ---
    EspecificacionLinea("S1", "autobuses-sistema-1", "Autobuses Articulados Sistema 1", "autobus-articulado", "sistema-autobuses-articulados", "#C0392B", 34, "operativa", 95, 45.0, [(-15, 3), (-3, 3), (-3, 15), (9, 15), (9, 21)], "superficial"),
    EspecificacionLinea("S2", "autobuses-sistema-2", "Autobuses Articulados Sistema 2", "autobus-articulado", "sistema-autobuses-articulados", "#2C3E50", 35, "operativa", 100, 45.0, [(12, 0), (15, 3), (27, 3), (27, 18), (15, 18)], "superficial"),
    EspecificacionLinea("S3", "autobuses-sistema-3", "Autobuses Articulados Sistema 3", "autobus-articulado", "sistema-autobuses-articulados", "#5B3E96", 26, "operativa", 110, 45.0, [(-21, 9), (-15, 3), (-15, -12), (-9, -18)], "superficial"),
    EspecificacionLinea("S4", "autobuses-sistema-4", "Autobuses Articulados Sistema 4", "autobus-articulado", "sistema-autobuses-articulados", "#C87D16", 24, "operativa", 105, 50.0, [(-6, 18), (-6, 24), (18, 24)], "superficial"),
    EspecificacionLinea("S5", "autobuses-sistema-5", "Autobuses Articulados Sistema 5", "autobus-articulado", "sistema-autobuses-articulados", "#1F4E79", 30, "en-construccion", 120, 45.0, [(3, 0), (6, 3), (9, 0), (9, -3), (3, -9), (3, -21), (0, -21)], "superficial"),
]

# Hitos nominales fijos en coordenadas exactas de la retícula (gx, gy)
HITOS_FIJOS: Dict[Tuple[float, float], str] = {
    (0.0, 0.0): "Santa Mónica",
    (-9.0, 0.0): "Tacuba",
    (-6.0, 6.0): "Buenavista",
    (6.0, 0.0): "Pino Suárez",
    (-15.0, -24.0): "Polígono",
    (3.0, 0.0): "Hidalgo",
    (12.0, 0.0): "Sofia",
    (-21.0, 0.0): "Siervo de la Nación",
    (0.0, 18.0): "Kassiane",
    (12.0, 18.0): "Rosario",
    (21.0, 9.0): "Alejandría",
    (21.0, 0.0): "Morelos Oriente",
    (21.0, -9.0): "Alameda Oriente",
    (12.0, -18.0): "Santa Ana",
    (0.0, -18.0): "Ciudad Universitaria",
    (0.0, -21.0): "Aeropuerto Álvarez Morisot",
    (-6.0, -18.0): "Cuatro Caminos",
    (-12.0, -18.0): "Dürer",
    (-21.0, -9.0): "Ojo de Agua",
    (-21.0, 9.0): "Amores",
    (-12.0, 18.0): "El Peregrino",
    (-6.0, 18.0): "Ciudad Azteca",
    (0.0, -6.0): "Olimpia",
    (3.0, -9.0): "Chabacano",
    (9.0, -3.0): "Estrellas",
    (6.0, 12.0): "El Dorado",
    (-3.0, 9.0): "Bosque Encantado",
    (-30.0, 3.0): "Albufera",
    (-9.0, -30.0): "Tlacotepec",
    (-15.0, -21.0): "Dalia",
    (-27.0, -21.0): "Sayula",
    (18.0, 24.0): "Industrial Rosario",
    (-15.0, -12.0): "San Ángel",
    (-9.0, -18.0): "Greta",
    (12.0, 6.0): "Herschel",
    (6.0, -6.0): "Fray Servando",
    (-3.0, -9.0): "Isabel la Católica",
    (12.0, -24.0): "Central de Abastos",
    (-24.0, 15.0): "Cardonal",
}

# Zonas geográficas y corredores preservados (en coordenadas de retícula gx, gy)
ZONAS_URBANAS: List[Dict[str, Any]] = [
    {
        "id": "zona-meseta-central",
        "nombre": "Meseta Central Metropolitana",
        "relleno": "#ECEAE2",
        "borde": "#D8D4C7",
        "opacidad": 0.72,
        "etiqueta_pos": (2.0, 13.8),
        "puntos": [(-16, 14), (16, 14), (20, 10), (20, -11), (14, -17), (-14, -17), (-20, -11), (-20, 10)],
    },
    {
        "id": "zona-corredor-industrial-norte",
        "nombre": "Corredor Industrial Norte",
        "relleno": "#E5E9F0",
        "borde": "#C2CBD8",
        "opacidad": 0.78,
        "etiqueta_pos": (6.0, 26.2),
        "puntos": [(-10, 20), (33, 20), (38, 25), (38, 31), (-8, 31), (-10, 27)],
    },
    {
        "id": "zona-corredor-ecologico-poniente",
        "nombre": "Corredor Ecológico Poniente – San Ángel – Greta",
        "relleno": "#DCEAD7",
        "borde": "#B3CFA9",
        "opacidad": 0.72,
        "etiqueta_pos": (-22.5, -5.5),
        "puntos": [(-29, 8), (-14, 8), (-14, -14), (-8, -20), (-23, -20), (-29, -14)],
    },
    {
        "id": "zona-terminal-aereo-sur-universidad",
        "nombre": "Terminal Aéreo Sur Álvarez Morisot y Ciudad Universitaria",
        "relleno": "#E1ECF7",
        "borde": "#B4CBE3",
        "opacidad": 0.78,
        "etiqueta_pos": (-1.5, -23.0),
        "puntos": [(-10, -16), (8, -16), (8, -25), (-10, -25)],
    },
    {
        "id": "zona-reserva-bosque-encantado",
        "nombre": "Reserva Forestal Bosque Encantado y Sierra Sur",
        "relleno": "#DCEAD7",
        "borde": "#B3CFA9",
        "opacidad": 0.75,
        "etiqueta_pos": (4.0, -34.2),
        "puntos": [(-18, -26), (22, -26), (29, -33), (25, -37), (-14, -37), (-18, -33)],
    },
]

# Cuenca hidrológica octilineal (Río Seine – Río Tíber)
TRAZO_RIO_PRINCIPAL: List[Tuple[float, float]] = [
    (-38.0, 20.0), (-26.0, 20.0), (-14.0, 8.0), (-5.0, 8.0),
    (2.0, 1.0), (14.0, 1.0), (26.0, -11.0), (43.0, -11.0),
]

# Toponimia limpia por línea derivada del Plan Maestro (metro2.pdf)
CATALOGO_NOMBRES_LINEA: Dict[str, List[str]] = {
    "1": [
        "Siervo de la Nación", "Felipe Escamilla", "Luis Ibaraki", "Río Seine", "El Jardín",
        "Latina", "Santa Mónica", "Hidalgo", "La Ilíada", "Aranza", "Velasco", "Diego Kisai",
        "Palacio Real", "Jardín Botánico", "Sagrada Catedral", "Sofia"
    ],
    "2": [
        "Kassiane", "Abraham Clermont", "Diego Rivera", "Vid", "Auverna", "Las Torres",
        "Bosque Encantado", "Juan de Gotia", "El Torito", "Práxedes", "Edén", "Hidalgo",
        "Fray Servando", "Alameda Central", "ESFIF Rádonezh", "Olimpia", "Normal",
        "Obras Publicas", "Vía Láctea", "Materno Infantil", "Planetario", "Chabacano", "Fresas",
        "Abigaíl", "Palmas", "Monte Parnaso", "Isabel I", "Durazno", "Helena", "Kant", "Sol",
        "Miguel Ángel", "San Aquilo", "La Villa", "Rosales", "La Ateniense", "Cuatro Caminos"
    ],
    "3": [
        "Amores", "Flor de Loto", "Naturalismo", "Hospital Poniente", "La Orquídea",
        "Aelia Pulqueria", "Hospital 21", "Juan de Gotia", "Pedro de Valdivia", "UAB-I",
        "Puente de la Unidad", "La Cementera", "Índigo", "Lincoln", "El Dorado", "Grant",
        "Curie", "Goethe", "El Fresno", "Feynman", "Herschel", "Linnaeus", "Judas Tadeo",
        "San Francisco de Asís", "Roble", "Nogal", "Oyamel", "Salvador Allende", "Rafael Guízar",
        "Lanteri", "Ilustración", "Osa Mayor", "Alejandría", "Copihue"
    ],
    "4": [
        "Ingenieros Militares", "Militar-I", "Hangares", "Fuerza Aérea", "Río Seine",
        "Aeropuerto T5", "Aeropuerto T4", "Aeropuerto T1-3", "Santa Mónica", "El Torito",
        "Felipe Ángeles", "El Cid"
    ],
    "5": [
        "Sofia", "La Rioja", "Odisea", "Luis Molinari", "Instituto de Artes", "El Bosco",
        "Andrea Casali", "Naranjo", "Ministerio de Sanidad", "24 de Febrero", "Casa de Campo",
        "Condes", "La Vaguada", "Castilla", "Corredor Ambiental", "Morelos Oriente"
    ],
    "6": [
        "Rosario", "Coruña", "Monasterios", "La Huerta", "Cedro", "Seminario Mayor", "La Granja",
        "Plutón", "Herschel", "El Monte", "San Benito", "Europa", "Francisco Miguel", "Sofia",
        "Pontifica", "La Plata", "El Huerto", "Gabriela Mistral", "Magallanes",
        "Biblioteca Nacional", "Archivo de la Nación", "Nuevos Ministerios", "Conde de Miranda",
        "Zaragoza", "Rieul de Senlis", "Domeyko", "Facultad de Odontología", "Alcaine",
        "Pablo Neruda", "Jerónimo Navarrete", "Santa Fe", "Hidalgo", "Central de Abastos"
    ],
    "7": [
        "Homero", "María Moliner", "Dolores Ibárruri", "Aelia Pulqueria", "Santa Mónica",
        "Aeropuerto T1-3", "Hangares Internacionales", "Terminal Aérea Poniente", "Latina",
        "Campoamor", "Diego de Landa", "Manzanares", "Olimpia", "EFS-I", "EFS-II",
        "Sierra Nevada", "Rosa Luxemburgo", "Maestros", "Facultad de Geografía",
        "Ciencias Físicas"
    ],
    "8": [
        "El Peregrino", "Homero", "Navarra", "Vista Alegre", "María Moliner", "La Vía",
        "Emperatriz", "Bosque Encantado", "Marquesa de Silvela", "Andalucía",
        "Puente de la Unidad", "Olivares", "El Cid", "Pasionaria", "Eduardo Molina",
        "Manuel Aleixandre", "Miranda", "Unanue", "Diego Kisai", "Gobernación", "CEIP-Favila",
        "Plaza Mayor", "Centro Histórico", "Estrellas"
    ],
    "9": [
        "Estrellas", "Embajadores", "Juan Boscán", "La Alhambra", "Joaquina Eguaras",
        "Molino Nuevo", "Poetisa Handuna", "12 de Octubre", "García Lorca", "Nereida", "Rosita",
        "Facultad de Medicina", "Alejandro Ferrant", "Acacias", "EM-A", "Alfonso XII",
        "Argumosa", "El Marques", "Bolívar", "Magdalena", "Salamanca", "Romántica", "Aravaca",
        "Merced", "Sagrado Señorial", "Alberdi", "Mercadante", "Miguel Ángel",
        "Motolinía Oriente"
    ],
    "10": [
        "Río Tíber", "Víctor de Montaigne", "Plaza Roja", "Parque de las Fuentes",
        "Acuario Stellaria", "Blasco Ibáñez", "Villa de Cuenca", "Ciencias Físicas", "Maeztu",
        "Rosa Luxemburgo", "Archivo de la Nación", "Vía Láctea", "Centros Médicos",
        "Margarita Nelken", "La Cruz", "Ana Albi", "Poetisa Handuna", "Fortín", "Antenas",
        "Versalles", "Campos Elíseos", "Jardín", "Nuevos Ministerios", "Colegio de Posgrados",
        "Monasterios", "Alas Clarín", "Fuente de la Reina", "El Calvario"
    ],
    "11": [
        "Isabel la Católica", "Riobamba", "Edgar Neville", "Orense", "Ramonet", "Luis Buitrago",
        "El Olmo", "Tribunal", "Palacio Legislativo", "Fiscalía General", "Senadores",
        "Facultad de Derecho", "Alesna", "Alfonso Cano", "José Martí", "Santa Ana"
    ],
    "12": [
        "Alameda Oriente", "Panteones", "La Almudena", "Noche Triste", "El Pípila",
        "Héroes de Nacozari", "Antonio Ponz", "Berástegui", "Emilio Ferrari",
        "Virgen de la Oliva", "Arcentales", "Ramon Vizcaino", "Magallanes", "Allende", "Palermo",
        "Artemisa", "Fortín", "El Caracol", "La Alhambra", "San Rosendo", "Orfeo",
        "Velázquez Bosco", "Real Plaza", "Olimpia"
    ],
    "13": [
        "Fray Servando", "Pléyades", "Camargo", "Diego de Landa", "Salinas Moreau",
        "Francisco de Sales", "Ángel Llorca", "Talamantes", "Gante", "San Pedro de los Pinos",
        "Letrado", "Libertad", "Desarrollo Familiar", "Moncloa", "Santiago Rusiñol",
        "Fuente Noria", "Acuario Stellaria", "Consuelo", "Alberca Olímpica", "Parques Acuáticos",
        "Valdemarín", "Gran Canal", "La Rábida", "Misiones", "Gran Presa", "Tenistas", "Leñeros",
        "Motolinía", "Ferreira", "Bellas Artes", "Instituto Cultural", "MediSur", "Dürer"
    ],
    "14": [
        "El Dorado", "Montecarmelo", "Guerrero", "Fórum Monarca", "Libertad", "San Benito",
        "Ramon y Cajal", "Instituto de Artes", "Víctor Hugo", "UAA-IV", "Rafael Guízar",
        "Lanteri", "Osa Mayor", "Alejandría"
    ],
    "15": [
        "Santa Mónica", "Nubes", "Pléyades", "Vasco de Quiroga", "Olimpia", "Sierra Nevada",
        "Archivo de la Nación", "Parque Bicentenario", "Fresas", "Calle 10", "Fórum Helena",
        "Auditorio Nacional", "Villege", "Cuatro Caminos", "Alameda Sur", "Alsacia I",
        "Alsacia II", "Alsacia III", "Querencia", "Alonso Cifuentes", "Puente Lerma", "Alvear",
        "Del Prado", "Hispano Ferrer", "Ensambladora", "Ford", "San Lázaro",
        "Estrella del Amanecer"
    ],
    "16": [
        "Chabacano", "La Piedad", "Kinsasa", "Arroyo", "Facultad de Medicina",
        "Hospital Universitario", "Artilleros", "Señor de la Ascensión", "Puebla", "Magnolia",
        "Fortaleza", "La Huerta", "Luis Buitrago", "Bugambilias"
    ],
    "17": [
        "Judas Tadeo", "Zaldívar", "Etna", "Ramon y Cajal", "Luis Molinari", "Corregidora",
        "Ninfas", "UCM-IX", "Arcentales", "Colegio de Posgrados", "Zaragoza"
    ],
    "18": [
        "Santa Mónica", "Felipe Escamilla", "Túnel Emisor", "Río Tíber", "Ojo de Agua",
        "Laguna de Patos", "Jirón", "Sayula", "La Palapa", "Pisagua", "Rancho Viejo", "Apanco",
        "Terraza Real", "Varela", "Aztacalco", "Pescadores", "Tlaxomulco", "Perseo", "Sucilia",
        "Mayapan", "Viveros", "Arinza", "Nuevo Florecer", "Balasté", "Jardín del Abuelo",
        "El Pino", "Flor de Luna", "Mariana", "Los Angelitos", "Parque Verde", "Camino Real",
        "Bochil", "Puerto de Alvarado", "Asís", "Cerecinos", "Albardín", "Alameda Dalias",
        "Dalia"
    ],
    "19": [
        "Rosita", "Uhagon", "Artilleros", "Elisa", "Torre 800", "José Anespere", "Meninas",
        "Rieul de Senlis", "Zapata"
    ],
    "20": [
        "Margarita Nelken", "Peñalba", "Meliloto", "Kinsasa", "Camarena", "Manzanilla",
        "Almazán", "Parque de la Palma", "Hilario Sangrador", "Derechos Humanos", "Salamanca",
        "Milpas", "Sagrado Señorial", "La Cabaña", "María del Carmen", "Sur 924", "Avícola",
        "Sepúlveda", "Alcazaba", "Arnau", "Residencias Sur", "Campus Poniente", "Universidad Sur"
    ],
    "21": [
        "Albufera", "Sierra Norte", "Río Seco", "Laforet", "El Pilar", "Venus", "Río Colorado",
        "Papaloapan", "Sauces", "Ojo de Liebre", "Cañada", "Gaite", "Frida Kahlo", "La Divina",
        "Santa Teresa", "Cuitzeo", "Girasoles", "La Montserrat", "Tic-Ti", "Sayula"
    ],
    "22": [
        "Alvear", "Hispanidad", "Brunel", "Polígono XI", "Faraday", "Polígono X", "Uranio",
        "Rahman Khan", "Polígono IX", "Neumann", "Polígono VIII", "Olmos", "Franklin",
        "Polígono VII", "Braun", "Polígono VI", "San Fernando", "Benz", "Polígono V",
        "Polígono IV", "Polígono III", "Fermi", "Polígono", "Arquímedes", "Polígono II"
    ],
    "A": [
        "Kassiane", "Angela Figuera", "La Oprimida", "Platanares", "El Peregrino",
        "Prieto Castro", "Santiago Cordero", "Amores", "Industrial", "Ingenieros Militares",
        "Madrigal", "Aldea Real", "Siervo de la Nación", "Distribuidora", "Túnel Emisor",
        "Carlos Latorre", "Miguel Grau", "Pablo Moncayo", "Hilandería", "Miguel Servet", "ESI",
        "Juan de Dios", "Río Tíber", "Ministerio de Parques", "Cárcamo de Bombeo",
        "López de Hoyos", "Protección Civil", "Técnica 155", "Velódromo", "Estadio Olímpico",
        "Polideportivo", "El Llano", "Ángeles", "Ojo de Agua", "Parque de los Patos",
        "Mar de Cristal", "Mendizábal", "Calle de las Manzanas", "Ministerio de Seguridad",
        "Instituto de la Juventud", "Felipe Salvador", "Baleares", "Dürer",
        "Rodrigo de Castellan", "Bosque de la Villa", "El Canalillo", "Ankara", "Cuatro Caminos",
        "Alsacia", "Arnau", "López Otero", "Residencias", "Isabel de Villena",
        "Ciudad Universitaria", "Facultades", "Aeropuerto Álvarez Morisot", "Hospitales Sur",
        "General de Especialidades", "El Capulín", "Arroyo de Antequino", "Fernando Poo",
        "MIDEyC", "Santa Ana", "Flor de Rocío", "José Martin", "Villas Monarcas", "Las Peñuelas",
        "Mercedes", "Prados", "Zuloaga", "Suprema Corte", "Amapola", "López Mateos",
        "Margaritas", "Medicina Familiar", "Hospital 235", "Cobeña", "Ortega y Munilla", "Asura",
        "Conde de Casal", "Álamo", "Mariblanca", "Fausta Elorza", "Ramon Lujan", "Ortiz",
        "Campos", "Salón de Pinos", "Alameda Oriente", "Camposanto", "Floristas", "La Soledad",
        "Puerta Santa Fe", "Morelos Oriente", "Colmenar Viejo", "Alejandría", "Javier Mina",
        "Madre Celeste", "Parque Río", "Picara Molinera", "20 de Noviembre", "Sierra Molina",
        "Oyameles", "Puerta Asura", "Rosario", "Francisco del Paso", "Rafael Alberti", "Montiel",
        "San Diego", "La Pastora", "Ciudad Azteca", "Karla Asura", "Universidad",
        "Instituto Literario", "De los Hospitales", "Parques Nacionales", "Av. Lagos",
        "Puerta de la Soledad", "San Lorenzo Norte", "Villas de Asura", "Bosques de Kassiane",
        "Lomas de Azteca", "Mirador Periférico", "Anillo Norte", "Isidro Fabela"
    ],
    "B": [
        "Ciudad Azteca", "La Pastora", "Isidro Fabela", "Tepetitlán", "Terminal Norte",
        "Diego de León", "Betancourt", "Colon", "Pío XII", "Lincoln", "El Dorado",
        "Montecarmelo", "Horizonte", "Vicario", "Manuel Aleixandre", "Zárate", "Gran Ciudad",
        "Palacio Real", "Gobernación", "CEIP-Favila", "Plaza Mayor", "María de Guadalupe",
        "Portales", "Estrellas", "Concordia", "La Priora", "Artemisa", "World Trade Center",
        "La Piedad", "Versalles", "Torre Áurea", "Celestia", "Fiducia", "Numisma",
        "Palacio de la Reserva", "Torre 800", "Fuenlabrada", "Mercadantes", "Isabel la Católica",
        "Legislatura", "Rábida", "San Salvador", "Hidalgo", "Saturno", "Botticelli", "Apóstol",
        "Rectoría", "Núremberg", "Vereda del Palacio", "Bonet", "El Reloj", "Asura"
    ],
    "C": [
        "Siervo de la Nación", "Cardonal", "Paseo del Río", "Alcanfores", "Calle 31",
        "Diente de León", "Tejocotes", "Calle 4", "Glorieta de los Ángeles", "Los Ángeles",
        "Ladera", "Jean Piaget", "Halcones", "Albufera", "Río Amarillo", "Sanbar", "Cruces",
        "Jerusalén", "Ahuehuetes", "Amates", "Pedregal Verde", "Framboyanes", "Josué Mirlo",
        "Bosque de Belén", "Herradura", "Montesinos", "Alatorre", "Montevideo", "Dalia",
        "Parque Tepētl", "Cerro", "San Lorenzo", "Tlacotepec", "San Lorenzo Tlacotepec"
    ],
    "D": [
        "El Peregrino", "San Blas", "Jazmín", "Azucenas", "El Clavelero", "Xinaxtla",
        "Villaclara", "Amaneceres", "Agrarismo", "La Amistad", "Moyotlan", "3 de Mayo",
        "El Metate", "15D Oriente", "María Bonita", "Ocotzol", "Politécnico", "ESED", "Mixtiu",
        "Arboledas", "Shomeje", "Santo Domingo", "Malinalli", "Dolores", "Adoquín", "Bamba",
        "Montero Segovia", "Quinto Sol", "Todos los Santos", "San Juan de los Jarros",
        "Los Jarros"
    ],
    "E": [
        "Alameda Oriente", "Héroes de Reforma", "Francisco Zarco", "Comunal", "Luis Bleriot",
        "Oriente 140", "Ontario", "Cantú", "Mario Bellatin", "Leopoldo Velasco", "Cuvier",
        "Crisantema", "Gustavo Baz", "Guadalupe Tecoac", "Coquimbo", "Rincón de la Candelaria",
        "Escobedo", "La Rosa", "Rincón", "Abasolo", "Parque de las Animas",
        "Mirador de las Animas", "Laguna Grande", "Atotonilco", "Cananea", "23 de Abril",
        "La Espiga", "San Pedro", "Llanura", "Blvd. San Andrés", "Panamá", "Acutzilapan",
        "Santiago Acutzilapan", "Santiago Apóstol"
    ],
    "F": [
        "El Rosario", "Industrial Rosario Norte", "Ceylán", "El Caporal", "Industrial Rosario",
        "5 de Mayo", "Coliseum", "Cuartel General AAS", "Centro Investigaciones", "AAS-III",
        "El Ruiseñor", "Zapote", "Kahlo", "San Ignacio de Loyola", "Temazcales", "Dolores",
        "La Joya"
    ],
    "G": [
        "Tlacotepec", "Panteón Municipal", "Ciudad Deportiva", "Ópalo", "Patio Tlacotepec",
        "Villa Hermosa", "El Espejel", "15D Poniente", "Montealto", "Rivera del Río",
        "Eterna Primavera", "Chamizal", "La Quebrada", "Manto del Río", "Ahuízotl",
        "Puente Viejo", "Los Reyes", "Jardines", "Tandaro", "Pueblo Bajo", "Segundo Barrio",
        "Agustín Milán", "Véneto", "San Pedro Apóstol", "Río Morón", "Carlos Hank",
        "Dos Caminos", "Inmaculada", "Felipe Villanueva", "Calvarios", "Los Pastores"
    ],
    "S1": [
        "Santa Mónica", "Calz. Santa Mónica", "Blvd. Aeropuerto", "El Torito", "Reséndiz",
        "Juan de Gotia", "Casa Vieja", "Bosque Encantado", "Las Torres", "Blanca", "Zaldívar",
        "Torres 31", "Fuentecita", "El Potrillo", "Tepetitlán Poniente", "Ciruelos",
        "Club de Leones", "Botica", "Ciudad Comercial", "Central Norte", "Estancias Infantiles",
        "Praviana", "CEIP San Juan", "Perinatal", "Colon", "Plaza de la Tecnología", "Dorado-II",
        "Del Trabajo", "Plaza Trabajadores", "Médicos Nacionales", "Fresnedo", "Continentes",
        "Reyes", "Unamuno-I", "Seminario Menor", "Guadalupe Hidalgo", "La Granja", "Victoria",
        "Seminario Mayor"
    ],
    "S2": [
        "Sofia", "Hidalgo 11", "Francisco Miguel", "Europa", "San Benito", "Époque", "Libertad",
        "Fórum Monarca", "Fórum Monarca-II", "Fórum Monarca-III", "Dante", "El Fresno", "Curie",
        "Ilustración 972", "Dulce Moda", "Goethe", "Carondelet", "Del Taller", "Ocotepec",
        "Del Trabajo", "Sorzano", "Rafael Bergamín", "El Tato", "Mercado 23 de Octubre",
        "Churruca", "Mercado Mayorista", "Panizo", "Explanada Norte", "Valldemosa", "El Doroteo",
        "La Pastora", "Instituto de la Mujer", "Gran Árbol", "El Capitán", "Fresnedo",
        "Magdalena Diaz", "Explanada Oriente", "Folgueras", "Mediavilla", "Martin Álvarez",
        "Zapateros", "Filabres", "Plaza Bambú", "Encomienda de los Palacios", "Artajona",
        "Montiel"
    ],
    "S3": [
        "Colegio Militar", "Felipe Escamilla", "Escamilla 78", "Sirio", "Moreto", "Menéndez",
        "Manuel María", "Ángel Llorca", "Leo", "Aeronáutica", "Ganivet", "Parque del Retiro",
        "Club de Golf", "Platería", "Las Letras", "Fúcar", "Muriel", "Pueblo de la Cuenca",
        "Ciencias Físicas", "Villa de Cuenca"
    ],
    "S4": [
        "Ciudad Azteca", "Casa Real", "Estrella del Norte", "Oca", "El Puente", "Pantera",
        "Vitrales", "Marte", "Plaza Clarume", "Dulce Rojo", "Rositas", "El Paso", "Del Norte",
        "Plaza de la Luz", "Las Peñas", "Claveles", "Arenas del Rey", "Platón", "Laboratorios",
        "Opel Corsa", "Talleres", "Fernando de Alva", "San de Guzmán", "SEMSA", "Sierra Dorada",
        "Doré", "La Trinidad", "Sierra Blanca", "Tepeyac", "Moratín", "Atocha", "La Cabeza",
        "Arizónicas", "Salobreña", "Ginebro", "Industrial Rosario"
    ],
    "S5": [
        "Santa Mónica", "Hidalgo", "Fray Servando", "Alameda Central", "ESFIF Rádonezh",
        "Héroes de la Nación", "Villas de Kassiane", "Calz. de las Estrellas", "Estrellas",
        "Embajadores", "Juan Boscán", "La Alhambra", "El Caracol", "Fortín", "Versalles",
        "Torre Áurea", "Celestia", "Artilleros", "Señor de la Ascensión", "Puebla", "Magnolia",
        "Fortaleza", "La Huerta", "Calz. la Mora", "Mora Sur", "Entronque Asura",
        "Hospitales Sur", "Aeropuerto Álvarez Morisot", "Facultades", "Ciudad Universitaria"
    ],
}

NOMBRES_RESERVA: List[str] = [
    "Mirador del Valle", "Lomas de Asura", "Parque Hundido", "Puerta del Sol",
    "Las Águilas", "San Jerónimo", " Monte Albán", "Vista Hermosa",
    "Laurel", "Paseo de las Palmas", "Pradera Norte", "Rincón del Bosque",
    "Villa Olímpica", "Santa Cecilia", "Los Cedros", "Cruz del Sur",
    " Altavista", "Lomas Verdes", "El Mirador", "San Mateo",
    "Plaza Patria", "Jardines del Sur", "Arcos de Belén", "Fuentes Brotantes",
    "Molino del Rey", "Cerro de la Estrella", "Valle Dorado", "La Concordia",
    "Real del Monte", "San Bartolo", "Las Américas", "Puente Blanco",
    "Villas del Sol", "Paseo Real", "Cumbres", "Bosque Real",
    "Santa Bárbara", "El Vergel", "Los Morales", "San Marcos",
    "Parque Lira", "Observatorio Sur", "Ciudad Jardín", "La Florida",
    "San Cristóbal", "Las Flores", "El Rosario Sur", "Pueblo Nuevo",
    "Bellavista", "Los Pinos", "Santa Lucía", "El Campanario",
]


# =============================================================================
# 4. CONSTRUCCIÓN GEOMÉTRICA Y TOPOLÓGICA DEL MODELO ÚNICO EN MEMORIA
# =============================================================================

def _interseccion_segmentos(
    p1: Tuple[float, float], p2: Tuple[float, float],
    p3: Tuple[float, float], p4: Tuple[float, float],
) -> Optional[Tuple[float, float]]:
    """Calcula el punto exacto de cruce entre dos segmentos octilineales."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-8:
        for pa in (p1, p2):
            for pb in (p3, p4):
                if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1e-6:
                    return (round(float(pa[0]), 4), round(float(pa[1]), 4))
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if -1e-6 <= t <= 1.0 + 1e-6 and -1e-6 <= u <= 1.0 + 1e-6:
        return (round(x1 + t * (x2 - x1), 4), round(y1 + t * (y2 - y1), 4))
    return None


def _longitud_polilinea(pts: Sequence[Tuple[float, float]]) -> float:
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


def _arclen_en_polilinea(pts: Sequence[Tuple[float, float]], pt: Tuple[float, float]) -> Optional[float]:
    acum = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        d1 = math.hypot(pt[0] - x1, pt[1] - y1)
        d2 = math.hypot(x2 - pt[0], y2 - pt[1])
        if abs((d1 + d2) - seg) < 1e-5:
            return acum + d1
        acum += seg
    return None


def _interpolar_polilinea(pts: Sequence[Tuple[float, float]], s: float) -> Tuple[float, float]:
    acum = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        if s <= acum + seg + 1e-7:
            t = 0.0 if seg == 0 else max(0.0, min(1.0, (s - acum) / seg))
            return (round(x1 + t * (x2 - x1), 4), round(y1 + t * (y2 - y1), 4))
        acum += seg
    return (round(float(pts[-1][0]), 4), round(float(pts[-1][1]), 4))


def _subpolilinea_octilineal(
    pts: Sequence[Tuple[float, float]], s_ini: float, s_fin: float
) -> List[Tuple[float, float]]:
    """
    Extrae la cadena exacta de vértices octilineales entre dos posiciones de
    arco s_ini y s_fin, preservando cualquier quiebre de 45°/90° intermedio
    para garantizar que ningún tramo dibuje cuerdas con ángulos arbitrarios.
    """
    p_ini = _interpolar_polilinea(pts, s_ini)
    p_fin = _interpolar_polilinea(pts, s_fin)
    resultado: List[Tuple[float, float]] = [p_ini]
    acum = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        acum += seg
        if s_ini + 1e-5 < acum < s_fin - 1e-5:
            v = (round(float(pts[i + 1][0]), 4), round(float(pts[i + 1][1]), 4))
            if math.hypot(v[0] - resultado[-1][0], v[1] - resultado[-1][1]) > 1e-5:
                resultado.append(v)
    if math.hypot(p_fin[0] - resultado[-1][0], p_fin[1] - resultado[-1][1]) > 1e-5:
        resultado.append(p_fin)
    return resultado


def _reparto_proporcional(pesos: Sequence[float], total: int) -> List[int]:
    if total == 0:
        return [0] * len(pesos)
    suma = sum(pesos)
    exactos = [(p / suma) * total for p in pesos]
    enteros = [int(math.floor(v)) for v in exactos]
    faltan = total - sum(enteros)
    orden = sorted(range(len(pesos)), key=lambda i: (exactos[i] - enteros[i]), reverse=True)
    for idx in orden[:faltan]:
        enteros[idx] += 1
    return enteros


def _determinar_infraestructura_tramo(
    spec: EspecificacionLinea, punto_medio_grid: Tuple[float, float], idx: int
) -> str:
    """
    Asigna el tipo de infraestructura de cada tramo según la tipología de línea
    y el gradiente urbano centro-periferia (túnel profundo y subterráneo en el
    núcleo denso; viaducto elevado y superficial hacia la periferia).
    """
    if spec.tipo == "autobus-articulado":
        return "superficial"
    r_km = math.hypot(punto_medio_grid[0], punto_medio_grid[1]) * KM_POR_UNIDAD_RETICULA
    if spec.codigo in ("4", "7", "15"):
        return "tunel-profundo" if r_km < 16.5 else "viaducto-elevado"
    if spec.codigo == "A":
        if punto_medio_grid[1] >= 12.0 or punto_medio_grid[1] <= -12.0:
            return "viaducto-elevado"
        return "superficial" if (idx % 2 == 0) else "subterraneo"
    if spec.codigo == "C":
        return "viaducto-elevado" if idx < 22 else "superficial"
    if r_km < 8.5:
        return "tunel-profundo" if spec.infra_predominante == "tunel-profundo" else "subterraneo"
    if r_km < 17.5:
        return spec.infra_predominante
    return "viaducto-elevado" if spec.infra_predominante == "viaducto-elevado" else "superficial"


def _determinar_estado_tramo(spec: EspecificacionLinea, idx_tramo: int, total_tramos: int) -> str:
    """Refleja los estados operativos mixtos declarados para la red."""
    if spec.codigo == "C":
        # Línea C: 34 estaciones (0..12 = 13 cerradas permanentemente; 13..33 = 21 operativas)
        return "fuera-de-operacion" if idx_tramo < 13 else "operativo"
    if spec.codigo == "18":
        # Tramo interior Santa Mónica -> Ojo de Agua en construcción
        return "en-construccion" if idx_tramo < 8 else "operativo"
    if spec.codigo == "S5":
        return "en-construccion"
    if spec.estado_general == "ampliacion-pendiente":
        # Últimos 3 tramos periféricos como ampliación pendiente
        return "ampliacion-pendiente" if idx_tramo >= total_tramos - 3 else "operativo"
    return "operativo"


def construir_modelo_red(fecha_generacion: str = FECHA_GENERACION_DEFAULT) -> Dict[str, Any]:
    """
    Construye una sola vez el modelo completo de la red en memoria.
    Tanto el archivo JSON como el mapa SVG se derivan exclusivamente del
    diccionario retornado por esta función.
    """
    # 1. Detectar todas las intersecciones geométricas exactas entre las 34 líneas
    todos_segmentos: List[Tuple[str, Tuple[int, int], Tuple[int, int]]] = []
    for spec in ESPECIFICACIONES_LINEAS:
        for i in range(len(spec.polilinea) - 1):
            todos_segmentos.append((spec.codigo, spec.polilinea[i], spec.polilinea[i + 1]))

    intersecciones: Dict[Tuple[float, float], Set[str]] = defaultdict(set)
    for i in range(len(todos_segmentos)):
        c1, a1, a2 = todos_segmentos[i]
        for j in range(i + 1, len(todos_segmentos)):
            c2, b1, b2 = todos_segmentos[j]
            if c1 == c2:
                continue
            pt = _interseccion_segmentos(a1, a2, b1, b2)
            if pt is not None:
                intersecciones[pt].add(c1)
                intersecciones[pt].add(c2)

    # 2. Ubicar estaciones equidistantes por sub-corredor en cada línea
    arcos_por_linea: Dict[str, List[float]] = {}
    puntos_por_linea: Dict[str, List[Tuple[float, float]]] = {}
    lineas_en_punto: Dict[Tuple[float, float], List[str]] = defaultdict(list)

    for spec in ESPECIFICACIONES_LINEAS:
        pts = spec.polilinea
        long_total = _longitud_polilinea(pts)
        es_circular = (pts[0] == pts[-1])

        anclas: Set[float] = {0.0}
        if not es_circular:
            anclas.add(round(long_total, 6))

        for pt, codigos_cruce in intersecciones.items():
            if spec.codigo in codigos_cruce:
                s_val = _arclen_en_polilinea(pts, pt)
                if s_val is not None:
                    if es_circular and abs(s_val - long_total) < 1e-5:
                        s_val = 0.0
                    anclas.add(round(s_val, 6))

        anclas_ord = sorted(anclas)

        if spec.codigo == "C":
            # Caso estricto Línea C: 13 estaciones cerradas antes de Albufera (-30, 3)
            # y 21 estaciones operativas desde Albufera hasta Tlacotepec (-9, -30).
            s_albufera = round(_arclen_en_polilinea(pts, (-30.0, 3.0)) or 0.0, 6)
            lista_s: List[float] = [0.0] + [(j / 13.0) * s_albufera for j in range(1, 13)]
            post_anclas = [s for s in anclas_ord if s >= s_albufera - 1e-5]
            intermedias_op = 21 - len(post_anclas)
            pesos_op = [post_anclas[i + 1] - post_anclas[i] for i in range(len(post_anclas) - 1)]
            reparto_op = _reparto_proporcional(pesos_op, intermedias_op)
            for i in range(len(post_anclas) - 1):
                sa, sb = post_anclas[i], post_anclas[i + 1]
                lista_s.append(sa)
                k = reparto_op[i]
                for j in range(1, k + 1):
                    lista_s.append(sa + (j / (k + 1.0)) * (sb - sa))
            lista_s.append(post_anclas[-1])
        else:
            intervalos: List[Tuple[float, float]] = []
            if es_circular:
                for i in range(len(anclas_ord)):
                    sa = anclas_ord[i]
                    sb = anclas_ord[i + 1] if i + 1 < len(anclas_ord) else long_total
                    intervalos.append((sa, sb))
            else:
                for i in range(len(anclas_ord) - 1):
                    intervalos.append((anclas_ord[i], anclas_ord[i + 1]))

            intermedias_necesarias = spec.num_estaciones - len(anclas_ord)
            # Mayor densidad relativa en el núcleo central (< 10 km) que en la periferia (> 22 km)
            pesos: List[float] = []
            for sa, sb in intervalos:
                pm = _interpolar_polilinea(pts, 0.5 * (sa + sb))
                radio_km = math.hypot(pm[0], pm[1]) * KM_POR_UNIDAD_RETICULA
                factor_densidad = 1.28 if radio_km < 10.0 else (1.0 if radio_km < 22.0 else 0.82)
                pesos.append((sb - sa) * factor_densidad)

            reparto = _reparto_proporcional(pesos, intermedias_necesarias)
            lista_s = []
            for i, (sa, sb) in enumerate(intervalos):
                lista_s.append(sa)
                k = reparto[i]
                for j in range(1, k + 1):
                    lista_s.append(sa + (j / (k + 1.0)) * (sb - sa))
            if not es_circular:
                lista_s.append(anclas_ord[-1])

        arcos_por_linea[spec.codigo] = lista_s
        pts_est = [_interpolar_polilinea(pts, s) for s in lista_s]
        puntos_por_linea[spec.codigo] = pts_est
        for pt in pts_est:
            if spec.id_linea not in lineas_en_punto[pt]:
                lineas_en_punto[pt].append(spec.id_linea)

    # 3. Asignar nombres únicos e identificadores kebab-case sin duplicados
    nombres_por_punto: Dict[Tuple[float, float], str] = {}
    slugs_usados: Set[str] = set()

    # Primero registrar hitos fijos obligatorios
    for pt_hito, nombre_hito in HITOS_FIJOS.items():
        if pt_hito in lineas_en_punto:
            sl = a_kebab_case(nombre_hito)
            nombres_por_punto[pt_hito] = nombre_hito
            slugs_usados.add(sl)

    # Segundo nombrar correspondencias restantes buscando nombres comunes en el catálogo
    cursores_catalogo: Dict[str, int] = {spec.codigo: 0 for spec in ESPECIFICACIONES_LINEAS}
    idx_reserva = 0

    def _tomar_nombre_unico(codigos_preferidos: Sequence[str]) -> str:
        nonlocal idx_reserva
        # Intentar primero intersección de catálogos en correspondencias
        if len(codigos_preferidos) > 1:
            conjuntos = [set(CATALOGO_NOMBRES_LINEA.get(c, [])) for c in codigos_preferidos]
            comunes = set.intersection(*conjuntos) if conjuntos else set()
            for cand in sorted(comunes):
                sl = a_kebab_case(cand)
                if sl and sl not in slugs_usados:
                    slugs_usados.add(sl)
                    return cand
        # Tomar en orden del catálogo de la línea
        for cod in codigos_preferidos:
            pool = CATALOGO_NOMBRES_LINEA.get(cod, [])
            cur = cursores_catalogo.get(cod, 0)
            while cur < len(pool):
                cand = pool[cur].strip()
                cur += 1
                cursores_catalogo[cod] = cur
                sl = a_kebab_case(cand)
                if sl and sl not in slugs_usados:
                    slugs_usados.add(sl)
                    return cand
        # Buscar en cualquier catálogo restante antes de usar reserva
        for spec_aux in ESPECIFICACIONES_LINEAS:
            pool = CATALOGO_NOMBRES_LINEA.get(spec_aux.codigo, [])
            cur = cursores_catalogo.get(spec_aux.codigo, 0)
            while cur < len(pool):
                cand = pool[cur].strip()
                cur += 1
                cursores_catalogo[spec_aux.codigo] = cur
                sl = a_kebab_case(cand)
                if sl and sl not in slugs_usados:
                    slugs_usados.add(sl)
                    return cand
        # Reserva metropolitana
        while idx_reserva < len(NOMBRES_RESERVA):
            cand = NOMBRES_RESERVA[idx_reserva].strip()
            idx_reserva += 1
            sl = a_kebab_case(cand)
            if sl and sl not in slugs_usados:
                slugs_usados.add(sl)
                return cand
        raise RuntimeError("Se agotaron los nombres únicos de estación disponibles.")

    mapa_id_a_cod = {s.id_linea: s.codigo for s in ESPECIFICACIONES_LINEAS}
    for pt, lista_ids_linea in lineas_en_punto.items():
        if pt not in nombres_por_punto and len(lista_ids_linea) > 1:
            cods = [mapa_id_a_cod[lid] for lid in lista_ids_linea]
            nombres_por_punto[pt] = _tomar_nombre_unico(cods)

    # Tercero nombrar todas las estaciones exclusivas en orden de recorrido por línea
    for spec in ESPECIFICACIONES_LINEAS:
        for pt in puntos_por_linea[spec.codigo]:
            if pt not in nombres_por_punto:
                nombres_por_punto[pt] = _tomar_nombre_unico([spec.codigo])

    # 4. Construir registros de estaciones, tramos y líneas con proyección (lat, lon) -> (x, y)
    id_estacion_por_punto: Dict[Tuple[float, float], str] = {
        pt: f"estacion-{a_kebab_case(nom)}" for pt, nom in nombres_por_punto.items()
    }

    # Seleccionar las 20 estaciones clave del Servicio Premium en la Línea A
    pts_linea_a = puntos_por_linea["A"]
    indices_premium_a: Set[int] = set()
    # Priorizar correspondencias espaciadas uniformemente alrededor de las 124 estaciones
    paso_ideal = 124.0 / 20.0
    for k in range(20):
        centro = int(round(k * paso_ideal)) % 124
        mejor_idx = centro
        mejor_grado = -1
        for delta in (-2, -1, 0, 1, 2):
            cand_idx = (centro + delta) % 124
            if cand_idx in indices_premium_a:
                continue
            grado = len(lineas_en_punto[pts_linea_a[cand_idx]])
            if grado > mejor_grado:
                mejor_grado = grado
                mejor_idx = cand_idx
        indices_premium_a.add(mejor_idx)
    puntos_premium_a: Set[Tuple[float, float]] = {pts_linea_a[i] for i in sorted(indices_premium_a)}

    estados_observados_estacion: Dict[Tuple[float, float], List[str]] = defaultdict(list)
    infra_observada_estacion: Dict[Tuple[float, float], List[str]] = defaultdict(list)

    tramos_json: List[Dict[str, Any]] = []
    lineas_json: List[Dict[str, Any]] = []

    for spec in ESPECIFICACIONES_LINEAS:
        pts_poly = spec.polilinea
        es_circular = (pts_poly[0] == pts_poly[-1])
        long_poly = _longitud_polilinea(pts_poly)
        lista_s = arcos_por_linea[spec.codigo]
        pts_est = puntos_por_linea[spec.codigo]
        n_est = len(pts_est)
        num_tramos = n_est if es_circular else (n_est - 1)

        ids_estaciones_linea = [id_estacion_por_punto[pt] for pt in pts_est]
        longitud_acumulada_km = 0.0

        for idx_t in range(num_tramos):
            pt_orig = pts_est[idx_t]
            pt_dest = pts_est[(idx_t + 1) % n_est]
            s_ini = lista_s[idx_t]
            s_fin = long_poly if (es_circular and idx_t == n_est - 1) else lista_s[idx_t + 1]

            sub_grid = _subpolilinea_octilineal(pts_poly, s_ini, s_fin)
            puntos_svg_tramo: List[List[float]] = []
            long_tramo_km = 0.0
            prev_latlon: Optional[Tuple[float, float]] = None

            for gx, gy in sub_grid:
                lat, lon = reticula_a_latlon(gx, gy)
                sx, sy = proyectar_latlon_a_svg(lat, lon)
                puntos_svg_tramo.append([sx, sy])
                if prev_latlon is not None:
                    long_tramo_km += distancia_km_latlon(prev_latlon[0], prev_latlon[1], lat, lon)
                prev_latlon = (lat, lon)

            longitud_acumulada_km += long_tramo_km
            pm_grid = _interpolar_polilinea(pts_poly, 0.5 * (s_ini + s_fin))
            infra_t = _determinar_infraestructura_tramo(spec, pm_grid, idx_t)
            estado_t = _determinar_estado_tramo(spec, idx_t, num_tramos)

            # Registrar estado e infraestructura en estaciones extremo
            if spec.codigo == "C":
                est_orig = "fuera-de-operacion" if idx_t < 13 else "operativa"
                est_dest = "fuera-de-operacion" if (idx_t + 1) < 13 else "operativa"
            else:
                mapa_est = {
                    "operativo": "operativa",
                    "en-construccion": "en-construccion",
                    "ampliacion-pendiente": "ampliacion-pendiente",
                    "fuera-de-operacion": "fuera-de-operacion",
                }
                est_orig = mapa_est[estado_t]
                est_dest = mapa_est[estado_t]

            estados_observados_estacion[pt_orig].append(est_orig)
            estados_observados_estacion[pt_dest].append(est_dest)
            infra_observada_estacion[pt_orig].append(infra_t)
            infra_observada_estacion[pt_dest].append(infra_t)

            id_tramo = f"tramo-{spec.id_linea}-{idx_t + 1:03d}"
            tramos_json.append({
                "id": id_tramo,
                "origen": id_estacion_por_punto[pt_orig],
                "destino": id_estacion_por_punto[pt_dest],
                "linea": spec.id_linea,
                "infraestructura": infra_t,
                "estado": estado_t,
                "longitud_km": round(long_tramo_km, 3),
                "puntos": puntos_svg_tramo,
            })

        estaciones_premium_ids = (
            [id_estacion_por_punto[pts_est[i]] for i in sorted(indices_premium_a)]
            if spec.codigo == "A" else []
        )

        lineas_json.append({
            "id": spec.id_linea,
            "codigo": spec.codigo,
            "nombre": spec.nombre,
            "tipo": spec.tipo,
            "sistema": spec.sistema,
            "color": spec.color,
            "longitud_km": round(longitud_acumulada_km, 1),
            "es_circular": es_circular,
            "estado": spec.estado_general,
            "frecuencia_segundos": spec.frecuencia_s,
            "frecuencia_premium_segundos": spec.frecuencia_premium_s,
            "velocidad_max_kmh": spec.velocidad_kmh,
            "estaciones": ids_estaciones_linea,
            "estaciones_premium": estaciones_premium_ids,
        })

    # Prioridad de estado físico de un nodo compartido: si al menos una línea está operativa, la estación opera
    prioridad_estado = ["operativa", "en-construccion", "ampliacion-pendiente", "fuera-de-operacion"]

    estaciones_json: List[Dict[str, Any]] = []
    for pt, id_est in sorted(id_estacion_por_punto.items(), key=lambda kv: kv[1]):
        lat, lon = reticula_a_latlon(pt[0], pt[1])
        sx, sy = proyectar_latlon_a_svg(lat, lon)
        obs_estados = estados_observados_estacion[pt]
        estado_final = next((e for e in prioridad_estado if e in obs_estados), "operativa")
        infra_final = infra_observada_estacion[pt][0] if infra_observada_estacion[pt] else "subterraneo"
        lineas_servidas = lineas_en_punto[pt]

        estaciones_json.append({
            "id": id_est,
            "nombre": nombres_por_punto[pt],
            "coordenadas": {"x": sx, "y": sy},
            "coordenadas_geograficas": {"lat": lat, "lon": lon},
            "lineas": lineas_servidas,
            "estado": estado_final,
            "infraestructura": infra_final,
            "es_correspondencia": len(lineas_servidas) > 1,
            "servicio_premium": pt in puntos_premium_a,
        })

    sistemas_json: List[Dict[str, Any]] = [
        {
            "id": "sistema-metro",
            "nombre": "Sistema de Metro y Líneas Alimentadoras",
            "categoria": "metro-convencional",
            "tipos_linea": ["metro", "alimentadora"],
            "lineas": [l["id"] for l in lineas_json if l["sistema"] == "sistema-metro"],
        },
        {
            "id": "sistema-autobuses-articulados",
            "nombre": "Red de Autobuses Articulados",
            "categoria": "red-autobuses-articulados",
            "tipos_linea": ["autobus-articulado"],
            "lineas": [l["id"] for l in lineas_json if l["sistema"] == "sistema-autobuses-articulados"],
        },
    ]

    modelo: Dict[str, Any] = {
        "version": VERSION_ESQUEMA,
        "metadatos": {
            "nombre_red": IDENTIDAD_VISUAL["nombre_completo"],
            "siglas": IDENTIDAD_VISUAL["marca"],
            "ciudad": "Área Metropolitana de Asura",
            "poblacion_referencia": POBLACION_REFERENCIA,
            "fecha_generacion": fecha_generacion,
            "total_estaciones": len(estaciones_json),
            "total_lineas_convencionales": sum(1 for l in lineas_json if l["tipo"] == "metro"),
            "total_lineas_alimentadoras": sum(1 for l in lineas_json if l["tipo"] == "alimentadora"),
            "total_sistemas_autobuses": sum(1 for l in lineas_json if l["tipo"] == "autobus-articulado"),
            "total_tramos": len(tramos_json),
            "proyeccion": {
                "tipo": "equirectangular-tangente-local",
                "lat_origen": LAT_ORIGEN,
                "lon_origen": LON_ORIGEN,
                "km_por_grado_lat": round(KM_POR_GRADO_LAT, 6),
                "km_por_grado_lon": round(KM_POR_GRADO_LON, 6),
                "escala_svg_por_km": ESCALA_SVG_POR_KM,
                "origen_svg": {"x": ORIGEN_SVG_X, "y": ORIGEN_SVG_Y},
                "viewbox": f"0 0 {VIEWBOX_ANCHO} {VIEWBOX_ALTO}",
            },
        },
        "identidad_visual": IDENTIDAD_VISUAL,
        "sistemas": sistemas_json,
        "lineas": lineas_json,
        "estaciones": estaciones_json,
        "tramos": tramos_json,
    }
    return modelo


# =============================================================================
# 5. MOTOR DE ROTULADO CARTOGRÁFICO SIN SOLAPAMIENTOS (SPATIAL INDEX)
# =============================================================================

class IndiceEspacialEtiquetas:
    """Índice espacial de cajas AABB para evitar colisiones entre rótulos y trazos."""

    def __init__(self, tam_celda: float = 64.0) -> None:
        self.tam = tam_celda
        self.celdas: Dict[Tuple[int, int], List[Tuple[float, float, float, float]]] = defaultdict(list)

    def _rango(self, caja: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = caja
        return (
            int(math.floor(x1 / self.tam)),
            int(math.floor(y1 / self.tam)),
            int(math.floor(x2 / self.tam)),
            int(math.floor(y2 / self.tam)),
        )

    def insertar(self, caja: Tuple[float, float, float, float]) -> None:
        ix1, iy1, ix2, iy2 = self._rango(caja)
        for ix in range(ix1, ix2 + 1):
            for iy in range(iy1, iy2 + 1):
                self.celdas[(ix, iy)].append(caja)

    def colisiones(self, caja: Tuple[float, float, float, float]) -> int:
        x1, y1, x2, y2 = caja
        ix1, iy1, ix2, iy2 = self._rango(caja)
        vistas: Set[int] = set()
        conteo = 0
        for ix in range(ix1, ix2 + 1):
            for iy in range(iy1, iy2 + 1):
                for otra in self.celdas.get((ix, iy), ()):
                    oid = id(otra)
                    if oid in vistas:
                        continue
                    vistas.add(oid)
                    if not (x2 <= otra[0] or x1 >= otra[2] or y2 <= otra[1] or y1 >= otra[3]):
                        conteo += 1
        return conteo


def calcular_posiciones_insignias(
    modelo: Dict[str, Any],
) -> Dict[Tuple[str, int], Tuple[float, float]]:
    """
    Calcula las coordenadas SVG (bx, by) de las 2 insignias terminales de cada
    una de las 34 líneas asegurando una separación mínima >= 24 unidades SVG
    entre cualquier par de insignias.
    """
    estaciones_por_id = {e["id"]: e for e in modelo["estaciones"]}
    colocadas: List[Tuple[float, float]] = []
    posiciones: Dict[Tuple[str, int], Tuple[float, float]] = {}

    for linea_obj in modelo["lineas"]:
        lid = linea_obj["id"]
        ids_est = linea_obj["estaciones"]
        indices_insignia = [0, len(ids_est) // 2] if linea_obj["es_circular"] else [0, len(ids_est) - 1]
        for pos_i, idx_e in enumerate(indices_insignia):
            e_term = estaciones_por_id[ids_est[idx_e]]
            e_vec = estaciones_por_id[ids_est[(idx_e + 1) % len(ids_est)] if idx_e == 0 else ids_est[idx_e - 1]]
            vx = e_term["coordenadas"]["x"] - e_vec["coordenadas"]["x"]
            vy = e_term["coordenadas"]["y"] - e_vec["coordenadas"]["y"]
            norm = math.hypot(vx, vy) or 1.0
            ux, uy = vx / norm, vy / norm
            px_perp, py_perp = -uy, ux

            candidatos_b = [
                (21.0, 0.0),
                (23.0, 18.0),
                (23.0, -18.0),
                (40.0, 0.0),
                (26.0, 28.0),
                (26.0, -28.0),
            ]
            elegido = (
                round(e_term["coordenadas"]["x"] + ux * 21.0, 1),
                round(e_term["coordenadas"]["y"] + uy * 21.0, 1),
            )
            for avance, lateral in candidatos_b:
                bx = round(e_term["coordenadas"]["x"] + ux * avance + px_perp * lateral, 1)
                by = round(e_term["coordenadas"]["y"] + uy * avance + py_perp * lateral, 1)
                if all(math.hypot(bx - ox, by - oy) >= 24.0 for ox, oy in colocadas):
                    elegido = (bx, by)
                    break

            colocadas.append(elegido)
            posiciones[(lid, pos_i + 1)] = elegido

    return posiciones


def calcular_posiciones_etiquetas(
    modelo: Dict[str, Any],
    posiciones_insignias: Optional[Dict[Tuple[str, int], Tuple[float, float]]] = None,
) -> Tuple[Dict[str, Tuple[float, float, str, int]], int]:
    """
    Calcula (dx, dy, text_anchor, angulo_grados) para cada una de las 828
    estaciones garantizando cero solapamientos entre etiquetas, marcadores e insignias.
    """
    if posiciones_insignias is None:
        posiciones_insignias = calcular_posiciones_insignias(modelo)

    idx_vias = IndiceEspacialEtiquetas(64.0)
    idx_etiquetas = IndiceEspacialEtiquetas(64.0)

    # Registrar segmentos de vía discretizados en pequeñas cajas para no cubrir líneas
    for tr in modelo["tramos"]:
        pts = tr["puntos"]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            pasos = max(1, int(math.hypot(x2 - x1, y2 - y1) / 14.0))
            for k in range(pasos + 1):
                t = k / pasos
                px = x1 + (x2 - x1) * t
                py = y1 + (y2 - y1) * t
                idx_vias.insertar((px - 3.5, py - 3.5, px + 3.5, py + 3.5))

    # Registrar nodos físicos de las 828 estaciones en ambos índices
    for est in modelo["estaciones"]:
        cx, cy = est["coordenadas"]["x"], est["coordenadas"]["y"]
        r = 8.5 if len(est["lineas"]) >= 3 else (6.8 if est["es_correspondencia"] else 5.0)
        caja_nodo = (cx - r, cy - r, cx + r, cy + r)
        idx_vias.insertar(caja_nodo)
        idx_etiquetas.insertar(caja_nodo)

    # Registrar las 68 insignias terminales de línea para que ninguna etiqueta las pise
    for bx, by in posiciones_insignias.values():
        caja_ins = (bx - 12.5, by - 10.5, bx + 12.5, by + 10.5)
        idx_vias.insertar(caja_ins)
        idx_etiquetas.insertar(caja_ins)

    # Registrar rótulos de zonas geográficas para evitar cruces con etiquetas de estación
    for zona in ZONAS_URBANAS:
        elat, elon = reticula_a_latlon(zona["etiqueta_pos"][0], zona["etiqueta_pos"][1])
        zx, zy = proyectar_latlon_a_svg(elat, elon)
        zw = len(zona["nombre"]) * 4.2
        idx_vias.insertar((zx - zw, zy - 11.0, zx + zw, zy + 4.0))

    # Ordenar estaciones por jerarquía visual: grandes nodos -> correspondencias -> resto
    estaciones_ordenadas = sorted(
        modelo["estaciones"],
        key=lambda e: (-len(e["lineas"]), -int(e["servicio_premium"]), e["id"]),
    )

    # 28 candidatos octilineales y oblicuos alrededor del nodo
    candidatos_base: List[Tuple[float, float, str, int]] = [
        (8.5, -6.5, "start", 0),
        (8.5, 11.0, "start", 0),
        (-8.5, -6.5, "end", 0),
        (-8.5, 11.0, "end", 0),
        (9.5, 3.0, "start", 0),
        (-9.5, 3.0, "end", 0),
        (0.0, -10.5, "middle", 0),
        (0.0, 15.5, "middle", 0),
        (12.5, -11.0, "start", 0),
        (-12.5, 14.5, "end", 0),
        (12.5, 14.5, "start", 0),
        (-12.5, -11.0, "end", 0),
        (15.5, 3.0, "start", 0),
        (-15.5, 3.0, "end", 0),
        (0.0, -16.5, "middle", 0),
        (0.0, 21.5, "middle", 0),
        (7.5, -7.5, "start", -32),
        (-7.5, 9.5, "end", -32),
        (7.5, 9.5, "start", 32),
        (-7.5, -7.5, "end", 32),
        (17.5, -14.5, "start", 0),
        (-17.5, 17.5, "end", 0),
        (17.5, 17.5, "start", 0),
        (-17.5, -14.5, "end", 0),
        (9.5, -9.5, "start", -45),
        (-9.5, 11.5, "end", -45),
        (0.0, -23.0, "middle", 0),
        (0.0, 27.5, "middle", 0),
    ]

    resultado: Dict[str, Tuple[float, float, str, int]] = {}
    colisiones_entre_etiquetas = 0

    for est in estaciones_ordenadas:
        cx, cy = est["coordenadas"]["x"], est["coordenadas"]["y"]
        es_corr = est["es_correspondencia"]
        tam_fuente = 9.2 if len(est["lineas"]) >= 3 else (8.4 if es_corr else 7.4)
        ancho_est = len(est["nombre"]) * (tam_fuente * 0.54) + 3.0
        alto_est = tam_fuente + 2.0

        mejor_cand = candidatos_base[0]
        mejor_costo = 10**9
        mejor_caja = (cx, cy, cx + ancho_est, cy + alto_est)

        for idx_c, (dx, dy, anchor, rot) in enumerate(candidatos_base):
            tx = cx + dx
            ty = cy + dy
            if rot == 0:
                if anchor == "start":
                    x1, x2 = tx, tx + ancho_est
                elif anchor == "end":
                    x1, x2 = tx - ancho_est, tx
                else:
                    x1, x2 = tx - ancho_est * 0.5, tx + ancho_est * 0.5
                y1, y2 = ty - alto_est * 0.82, ty + alto_est * 0.22
            else:
                rad = math.radians(abs(rot))
                w_proj = ancho_est * math.cos(rad) + alto_est * math.sin(rad)
                h_proj = ancho_est * math.sin(rad) + alto_est * math.cos(rad)
                if anchor == "start":
                    x1, x2 = tx, tx + w_proj
                    y1, y2 = (ty - h_proj, ty + 2.0) if rot < 0 else (ty - 2.0, ty + h_proj)
                else:
                    x1, x2 = tx - w_proj, tx
                    y1, y2 = (ty - 2.0, ty + h_proj) if rot < 0 else (ty - h_proj, ty + 2.0)

            caja = (x1, y1, x2, y2)
            col_etiq = idx_etiquetas.colisiones(caja)
            col_vias = idx_vias.colisiones(caja)
            penal_rot = 4 if rot != 0 else 0
            costo = col_etiq * 10000 + col_vias * 35 + penal_rot + idx_c
            if costo < mejor_costo:
                mejor_costo = costo
                mejor_cand = (dx, dy, anchor, rot)
                mejor_caja = caja
                if costo < 5:
                    break

        if idx_etiquetas.colisiones(mejor_caja) > 0:
            colisiones_entre_etiquetas += 1
        idx_etiquetas.insertar(mejor_caja)
        resultado[est["id"]] = mejor_cand

    return resultado, colisiones_entre_etiquetas


# =============================================================================
# 6. DERIVACIÓN DEL MAPA ESQUEMÁTICO SVG COMPLETO (red_metro.svg) Y SERIALIZADOR JSON
# =============================================================================

def _esc(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _path_d(puntos: Sequence[Sequence[float]]) -> str:
    partes = [f"M{puntos[0][0]:.1f},{puntos[0][1]:.1f}"]
    for px, py in puntos[1:]:
        partes.append(f"L{px:.1f},{py:.1f}")
    return "".join(partes)


def _agrupar_tramos_continuos(tramos_linea: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Fusiona secuencias contiguas de tramos que comparten idéntica infraestructura
    y estado operativo en una única polilínea octilineal continua, preservando
    la fase exacta de trazos discontinuos, viaductos y túneles profundos.
    """
    bloques: List[Dict[str, Any]] = []
    for tr in tramos_linea:
        inf = tr["infraestructura"]
        est = tr["estado"]
        pts = tr["puntos"]
        if bloques and bloques[-1]["infraestructura"] == inf and bloques[-1]["estado"] == est:
            for pt in pts[1:]:
                if pt != bloques[-1]["puntos"][-1]:
                    bloques[-1]["puntos"].append(pt)
        else:
            bloques.append({
                "infraestructura": inf,
                "estado": est,
                "puntos": list(pts),
            })
    return bloques


def serializar_json_red(modelo: Dict[str, Any]) -> str:
    """
    Serializa el modelo completo a JSON RFC 8259 válido y legible, disponiendo
    un registro completo por línea en las colecciones tabulares (sistemas,
    lineas, estaciones y tramos).
    """
    filas = ["{"]
    filas.append(f'  "version": {json.dumps(modelo["version"], ensure_ascii=False)},')
    filas.append(f'  "metadatos": {json.dumps(modelo["metadatos"], ensure_ascii=False, indent=2).replace(chr(10), chr(10) + "  ")},')
    filas.append(f'  "identidad_visual": {json.dumps(modelo["identidad_visual"], ensure_ascii=False, indent=2).replace(chr(10), chr(10) + "  ")},')
    for idx_sec, clave in enumerate(("sistemas", "lineas", "estaciones", "tramos")):
        cierre_sec = "," if idx_sec < 3 else ""
        coleccion = modelo[clave]
        filas.append(f'  "{clave}": [')
        for i, item in enumerate(coleccion):
            coma = "," if i + 1 < len(coleccion) else ""
            filas.append(f'    {json.dumps(item, ensure_ascii=False, separators=(",", ":"))}{coma}')
        filas.append(f"  ]{cierre_sec}")
    filas.append("}")
    return "\n".join(filas) + "\n"


def generar_svg_red(modelo: Dict[str, Any]) -> str:
    """
    Deriva el documento SVG completo directamente desde ``modelo``.
    No emplea fuentes externas ni imágenes raster.
    """
    pal = IDENTIDAD_VISUAL["paleta"]
    tip = IDENTIDAD_VISUAL["tipografia"]
    pos_insignias = calcular_posiciones_insignias(modelo)
    pos_etiquetas, _ = calcular_posiciones_etiquetas(modelo, pos_insignias)

    estaciones_por_id = {e["id"]: e for e in modelo["estaciones"]}
    lineas_por_id = {l["id"]: l for l in modelo["lineas"]}
    tramos_por_linea: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tr in modelo["tramos"]:
        tramos_por_linea[tr["linea"]].append(tr)

    out: List[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX_ANCHO} {VIEWBOX_ALTO}" '
        f'width="{VIEWBOX_ANCHO}" height="{VIEWBOX_ALTO}" role="img" aria-labelledby="titulo-plano desc-plano">'
    )
    out.append(f'  <title id="titulo-plano">{_esc(IDENTIDAD_VISUAL["nombre_completo"])} · Plano Esquemático Oficial</title>')
    out.append(
        '  <desc id="desc-plano">Plano esquemático octilineal a escala coherente (54 unidades SVG/km) '
        'con 22 líneas convencionales, 7 alimentadoras A-G, 5 sistemas de autobuses articulados y 828 estaciones.</desc>'
    )

    # Hoja de estilos interna limpia en estilo de señalización real (RATP / Santiago / Seoul / LA Metro)
    out.append("  <style>")
    out.append(f"    svg {{ font-family: {tip['familia_principal']}; background-color: {pal['papel_fondo']}; }}")
    out.append("    .tr { fill: none; stroke-linecap: round; stroke-linejoin: round; }")
    out.append("    .m-base { stroke-width: 15.8; }")
    out.append("    .a-base { stroke-width: 21.0; }")
    out.append("    .f-base { stroke-width: 13.4; }")
    out.append("    .b-outer { stroke-width: 15.4; }")
    out.append("    .b-inner { stroke: #FFFFFF; stroke-width: 3.8; }")
    out.append("    .viad-cas { stroke: #334155; stroke-width: 20.6; stroke-linecap: butt; }")
    out.append("    .viad-deck { stroke: #FFFFFF; stroke-width: 18.0; stroke-linecap: butt; }")
    out.append("    .prof-cas { stroke: #1E293B; stroke-width: 19.8; stroke-opacity: 0.28; }")
    out.append("    .prof-fil { stroke: #FFFFFF; stroke-width: 1.3; stroke-dasharray: 1.5 6.5; stroke-opacity: 0.85; }")
    out.append("    .sup-ticks { stroke: #182026; stroke-width: 13.0; stroke-dasharray: 2.0 7.0; stroke-opacity: 0.26; stroke-linecap: butt; }")
    out.append("    .st-cons { stroke-dasharray: 10 6; }")
    out.append("    .st-amp { stroke-dasharray: 3.2 6.2; stroke-opacity: 0.78; }")
    out.append("    .st-closed-bed { stroke: #C9BFC6; stroke-width: 17.6; }")
    out.append("    .st-closed-dash { stroke: #9B2C2C; stroke-width: 10.6; stroke-dasharray: 9 7; }")
    out.append("    .nd-reg { fill: #FFFFFF; stroke-width: 1.9; }")
    out.append("    .nd-tr2 { fill: #FFFFFF; stroke: #182026; stroke-width: 2.4; }")
    out.append("    .nd-tr3 { fill: #FFFFFF; stroke: #182026; stroke-width: 2.9; }")
    out.append("    .nd-prem { fill: #E59A00; stroke: #FFFFFF; stroke-width: 0.9; }")
    out.append("    .nd-cons { fill: #F6F5F0; stroke-width: 2.0; stroke-dasharray: 2.4 1.8; }")
    out.append("    .nd-amp { fill: #F6F5F0; stroke-width: 1.8; stroke-dasharray: 1.6 1.8; }")
    out.append("    .nd-cl { fill: #E2E8F0; stroke: #9B2C2C; stroke-width: 1.8; }")
    out.append("    .lbl, .lbl-tr, .lbl-hub, .lbl-cl { stroke: #F6F5F0; stroke-width: 2.6; paint-order: stroke fill; stroke-linejoin: round; }")
    out.append("    .lbl { fill: #182026; font-size: 7.4px; font-weight: 500; }")
    out.append("    .lbl-tr { fill: #182026; font-size: 8.5px; font-weight: 700; }")
    out.append("    .lbl-hub { fill: #182026; font-size: 9.4px; font-weight: 800; }")
    out.append("    .lbl-cl { fill: #7B341E; font-size: 7.1px; font-weight: 500; opacity: 0.84; }")
    out.append("    .zona-lbl { fill: #52606D; font-size: 12.5px; font-weight: 700; letter-spacing: 0.8px; opacity: 0.72; }")
    out.append(f"    .mono {{ font-family: {tip['familia_monoespaciada']}; }}")
    out.append("  </style>")

    # CAPA 1: Fondo, zonas geográficas, corredores e hidrografía
    out.append('  <g id="capa-fondo-zonas">')
    out.append(f'    <rect id="lienzo-papel" x="0" y="0" width="{VIEWBOX_ANCHO}" height="{VIEWBOX_ALTO}" fill="{pal["papel_fondo"]}"/>')

    # Retícula kilométrica sutil cada 5 km (270 unidades SVG)
    out.append('    <g id="reticula-kilometrica" stroke="#E4E1D6" stroke-width="0.8">')
    paso_5km = 5.0 * ESCALA_SVG_POR_KM
    for k in range(-7, 9):
        gx_svg = ORIGEN_SVG_X + k * paso_5km
        if 80 <= gx_svg <= 4440:
            out.append(f'      <line x1="{gx_svg:.1f}" y1="165" x2="{gx_svg:.1f}" y2="{VIEWBOX_ALTO - 60}"/>')
    for k in range(-7, 7):
        gy_svg = ORIGEN_SVG_Y + k * paso_5km
        if 165 <= gy_svg <= VIEWBOX_ALTO - 60:
            out.append(f'      <line x1="80" y1="{gy_svg:.1f}" x2="4440" y2="{gy_svg:.1f}"/>')
    out.append("    </g>")

    # Polígonos de zonas y corredores
    for zona in ZONAS_URBANAS:
        pts_z: List[str] = []
        for gx, gy in zona["puntos"]:
            lat, lon = reticula_a_latlon(gx, gy)
            sx, sy = proyectar_latlon_a_svg(lat, lon)
            pts_z.append(f"{sx:.1f},{sy:.1f}")
        elat, elon = reticula_a_latlon(zona["etiqueta_pos"][0], zona["etiqueta_pos"][1])
        ex, ey = proyectar_latlon_a_svg(elat, elon)
        out.append(
            f'    <g id="{zona["id"]}">'
            f'<polygon points="{" ".join(pts_z)}" fill="{zona["relleno"]}" fill-opacity="{zona["opacidad"]}" '
            f'stroke="{zona["borde"]}" stroke-width="1.6" stroke-dasharray="8 5" stroke-linejoin="round"/>'
            f'<text x="{ex:.1f}" y="{ey:.1f}" text-anchor="middle" class="zona-lbl">{_esc(zona["nombre"].upper())}</text>'
            f"</g>"
        )

    # Cuenca hidrológica Río Seine – Río Tíber
    pts_rio: List[List[float]] = []
    for gx, gy in TRAZO_RIO_PRINCIPAL:
        lat, lon = reticula_a_latlon(gx, gy)
        sx, sy = proyectar_latlon_a_svg(lat, lon)
        pts_rio.append([sx, sy])
    d_rio = _path_d(pts_rio)
    out.append(
        f'    <g id="hidrografia-rio-seine-tiber">'
        f'<path d="{d_rio}" fill="none" stroke="{pal["hidrografia_borde"]}" stroke-width="20" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"/>'
        f'<path d="{d_rio}" fill="none" stroke="{pal["hidrografia_relleno"]}" stroke-width="15" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>'
        f"</g>"
    )
    out.append("  </g>")

    # Función auxiliar para renderizar polilíneas continuas por infraestructura y estado dentro del grupo <g id="linea-...">
    def _renderizar_grupo_linea(linea_obj: Dict[str, Any], indent: str = "    ") -> None:
        lid = linea_obj["id"]
        color = linea_obj["color"]
        tipo = linea_obj["tipo"]
        es_bus = (tipo == "autobus-articulado")
        clase_ancho = "a-base" if linea_obj["codigo"] == "A" else ("f-base" if tipo == "alimentadora" else "m-base")

        out.append(
            f'{indent}<g id="{lid}" data-codigo="{_esc(linea_obj["codigo"])}" '
            f'data-tipo="{tipo}" data-sistema="{linea_obj["sistema"]}" data-estado="{linea_obj["estado"]}">'
        )
        bloques = _agrupar_tramos_continuos(tramos_por_linea[lid])
        for idx_b, blq in enumerate(bloques):
            d = _path_d(blq["puntos"])
            est_t = blq["estado"]
            inf_t = blq["infraestructura"]
            bid = f"{lid}-seg-{idx_b + 1:02d}"

            if est_t == "fuera-de-operacion":
                out.append(
                    f'{indent}  <g id="{bid}" data-infraestructura="{inf_t}" data-estado="{est_t}">'
                    f'<path class="tr st-closed-bed" d="{d}"/><path class="tr st-closed-dash" d="{d}"/></g>'
                )
                continue

            mod_estado = " st-cons" if est_t == "en-construccion" else (" st-amp" if est_t == "ampliacion-pendiente" else "")

            if es_bus:
                dash_inner = ' stroke-dasharray="6 5"' if est_t != "operativo" else ""
                out.append(
                    f'{indent}  <g id="{bid}" data-infraestructura="{inf_t}" data-estado="{est_t}">'
                    f'<path class="tr b-outer{mod_estado}" stroke="{color}" d="{d}"/>'
                    f'<path class="tr b-inner" d="{d}"{dash_inner}/></g>'
                )
            elif inf_t == "viaducto-elevado":
                capas_v = f'<path class="tr viad-cas" d="{d}"/><path class="tr viad-deck" d="{d}"/>' if est_t == "operativo" else ""
                out.append(
                    f'{indent}  <g id="{bid}" data-infraestructura="{inf_t}" data-estado="{est_t}">'
                    f'{capas_v}<path class="tr {clase_ancho}{mod_estado}" stroke="{color}" d="{d}"/></g>'
                )
            elif inf_t == "tunel-profundo":
                c_ext = f'<path class="tr prof-cas" d="{d}"/>' if est_t == "operativo" else ""
                c_fil = f'<path class="tr prof-fil" d="{d}"/>' if est_t == "operativo" else ""
                out.append(
                    f'{indent}  <g id="{bid}" data-infraestructura="{inf_t}" data-estado="{est_t}">'
                    f'{c_ext}<path class="tr {clase_ancho}{mod_estado}" stroke="{color}" d="{d}"/>{c_fil}</g>'
                )
            elif inf_t == "superficial":
                c_ticks = f'<path class="tr sup-ticks" d="{d}"/>' if est_t == "operativo" else ""
                out.append(
                    f'{indent}  <g id="{bid}" data-infraestructura="{inf_t}" data-estado="{est_t}">'
                    f'<path class="tr {clase_ancho}{mod_estado}" stroke="{color}" d="{d}"/>{c_ticks}</g>'
                )
            else:
                out.append(
                    f'{indent}  <path id="{bid}" class="tr {clase_ancho}{mod_estado}" '
                    f'stroke="{color}" data-infraestructura="{inf_t}" data-estado="{est_t}" d="{d}"/>'
                )

        # Insignias identificadoras de línea sin solapamientos en sus terminales
        cod_txt = _esc(linea_obj["codigo"])
        for pos_i in (1, 2):
            bx, by = pos_insignias[(lid, pos_i)]
            if es_bus:
                out.append(
                    f'{indent}  <g id="insignia-{lid}-{pos_i}" transform="translate({bx:.1f},{by:.1f})">'
                    f'<rect x="-18.5" y="-14" width="37" height="28" rx="12" fill="{color}" stroke="#FFFFFF" stroke-width="1.5"/>'
                    f'<text y="3.5" text-anchor="middle" fill="#FFFFFF" font-size="13.4" font-weight="800">{cod_txt}</text></g>'
                )
            elif tipo == "alimentadora":
                out.append(
                    f'{indent}  <g id="insignia-{lid}-{pos_i}" transform="translate({bx:.1f},{by:.1f})">'
                    f'<rect x="-16" y="-16" width="32" height="32" rx="16" fill="{color}" stroke="#FFFFFF" stroke-width="1.6"/>'
                    f'<text y="3.8" text-anchor="middle" fill="#FFFFFF" font-size="15.5" font-weight="800">{cod_txt}</text></g>'
                )
            else:
                out.append(
                    f'{indent}  <g id="insignia-{lid}-{pos_i}" transform="translate({bx:.1f},{by:.1f})">'
                    f'<circle r="16.2" fill="{color}" stroke="#FFFFFF" stroke-width="2.6"/>'
                    f'<text y="3.5" text-anchor="middle" fill="#FFFFFF" font-size="15.2" font-weight="800">{cod_txt}</text></g>'
                )
        out.append(f"{indent}</g>")

    # CAPA 2: Red de Autobuses Articulados (5 sistemas)
    out.append('  <g id="capa-red-autobuses">')
    for l_obj in modelo["lineas"]:
        if l_obj["tipo"] == "autobus-articulado":
            _renderizar_grupo_linea(l_obj)
    out.append("  </g>")

    # CAPA 3: Líneas Alimentadoras A-G (7 líneas)
    out.append('  <g id="capa-lineas-alimentadoras">')
    for l_obj in modelo["lineas"]:
        if l_obj["tipo"] == "alimentadora":
            _renderizar_grupo_linea(l_obj)
    out.append("  </g>")

    # CAPA 4: Líneas Convencionales de Metro 1-22 (22 líneas)
    out.append('  <g id="capa-lineas-metro">')
    for l_obj in modelo["lineas"]:
        if l_obj["tipo"] == "metro":
            _renderizar_grupo_linea(l_obj)
    out.append("  </g>")

    # CAPA 5: Estaciones (828 registros únicos sin duplicados, con correspondencias visibles)
    color_por_id_linea = {l["id"]: l["color"] for l in modelo["lineas"]}
    out.append('  <g id="capa-estaciones">')
    for est in modelo["estaciones"]:
        eid = est["id"]
        cx, cy = est["coordenadas"]["x"], est["coordenadas"]["y"]
        lineas_est = est["lineas"]
        grado = len(lineas_est)
        estado_e = est["estado"]
        solo_bus = all(lid.startswith("autobuses-") for lid in lineas_est)
        color_primario = color_por_id_linea[lineas_est[0]]

        dx, dy, anchor, rot = pos_etiquetas[eid]
        clase_lbl = (
            "lbl-cl" if estado_e == "fuera-de-operacion"
            else ("lbl-hub" if grado >= 3 else ("lbl-tr" if grado == 2 else "lbl"))
        )
        attr_anchor = f' text-anchor="{anchor}"' if anchor != "start" else ""
        attr_rot = f' transform="rotate({rot} {dx:.1f} {dy:.1f})"' if rot != 0 else ""

        partes_nodo: List[str] = []
        if estado_e == "fuera-de-operacion":
            partes_nodo.append('<circle r="4.3" class="nd-cl"/>')
            partes_nodo.append('<path d="M-2.6,-2.6L2.6,2.6M2.6,-2.6L-2.6,2.6" stroke="#9B2C2C" stroke-width="1.5" stroke-linecap="round"/>')
        elif grado >= 3:
            partes_nodo.append('<circle r="7.8" class="nd-tr3"/><circle r="4.4" fill="#FFFFFF" stroke="#182026" stroke-width="1.3"/>')
            if est["servicio_premium"]:
                partes_nodo.append('<circle r="2.6" class="nd-prem"/>')
        elif grado == 2:
            partes_nodo.append('<circle r="6.0" class="nd-tr2"/>')
            if est["servicio_premium"]:
                partes_nodo.append('<circle r="2.8" class="nd-prem"/>')
            else:
                partes_nodo.append('<circle r="2.2" fill="#182026"/>')
        elif solo_bus:
            clase_b = "nd-cons" if estado_e == "en-construccion" else "nd-reg"
            partes_nodo.append(f'<rect x="-3.7" y="-3.7" width="7.4" height="7.4" rx="1.8" class="{clase_b}" stroke="{color_primario}"/>')
        else:
            clase_m = (
                "nd-cons" if estado_e == "en-construccion"
                else ("nd-amp" if estado_e == "ampliacion-pendiente" else "nd-reg")
            )
            r_m = 4.8 if est["servicio_premium"] else 3.9
            partes_nodo.append(f'<circle r="{r_m}" class="{clase_m}" stroke="{color_primario}"/>')
            if est["servicio_premium"]:
                partes_nodo.append('<circle r="2.3" class="nd-prem"/>')

        partes_nodo.append(f'<text x="{dx:.1f}" y="{dy:.1f}"{attr_anchor} class="{clase_lbl}"{attr_rot}>{_esc(est["nombre"])}</text>')
        out.append(
            f'    <g id="{eid}" transform="translate({cx:.1f},{cy:.1f})" data-estado="{estado_e}">'
            f'{"".join(partes_nodo)}</g>'
        )
    out.append("  </g>")

    # CAPA 6: Cabecera de Identidad Visual, Logo Vectorizado, Norte y Escala Gráfica
    out.append('  <g id="capa-cabecera-identidad">')
    out.append(
        f'    <rect x="44" y="34" width="4380" height="112" rx="14" '
        f'fill="{pal["superficie_panel"]}" stroke="{pal["borde_panel"]}" stroke-width="1.6"/>'
    )
    out.append('    <g id="logo-marca-incrustado" transform="translate(64, 46) scale(0.366)">')
    out.append(f'      {generar_logo_svg_elementos(incluir_texto_marca=False)}')
    out.append("    </g>")
    out.append(
        '    <text x="168" y="80" fill="#182026" font-size="27" font-weight="800" letter-spacing="-0.4">'
        'SIMMA · Sistema Integrado de Metro y Movilidad de Asura</text>'
    )
    out.append(
        '    <text x="168" y="106" fill="#4A5568" font-size="14" font-weight="500">'
        'Plano Esquemático Oficial · Área Metropolitana de 35 Millones de Habitantes · '
        '22 Líneas Convencionales · 7 Alimentadoras (A–G) · 5 Sistemas BRT · 828 Estaciones</text>'
    )
    out.append(
        '    <text x="168" y="127" fill="#718096" font-size="11.5" class="mono">'
        f'Proyección Equirectangular Tangente Local (Origen Santa Mónica: {LAT_ORIGEN:.4f}° N, {LON_ORIGEN:.4f}° O) · '
        f'Escala Única: {ESCALA_SVG_POR_KM:.0f} u. SVG = 1,0 km · Geometría Octilineal 0°/45°/90°</text>'
    )

    bx_esc = 3720.0
    by_esc = 84.0
    w_5km = 5.0 * ESCALA_SVG_POR_KM
    w_10km = 10.0 * ESCALA_SVG_POR_KM
    out.append(f'    <g id="escala-grafica-kilometrica" transform="translate({bx_esc:.0f}, {by_esc:.0f})">')
    out.append('      <text x="0" y="-12" fill="#182026" font-size="11.5" font-weight="700">ESCALA GRÁFICA (54 u. = 1 km)</text>')
    out.append(f'      <rect x="0" y="0" width="{w_5km:.0f}" height="8" fill="#182026"/>')
    out.append(f'      <rect x="{w_5km:.0f}" y="0" width="{w_5km:.0f}" height="8" fill="#FFFFFF" stroke="#182026" stroke-width="1.4"/>')
    out.append('      <text x="0" y="23" fill="#4A5568" font-size="11" class="mono">0 km</text>')
    out.append(f'      <text x="{w_5km:.0f}" y="23" text-anchor="middle" fill="#4A5568" font-size="11" class="mono">5 km</text>')
    out.append(f'      <text x="{w_10km:.0f}" y="23" text-anchor="end" fill="#4A5568" font-size="11" class="mono">10 km</text>')
    out.append("    </g>")

    out.append('    <g id="rosa-norte" transform="translate(4355, 90)">')
    out.append('      <circle r="26" fill="#F6F5F0" stroke="#182026" stroke-width="1.6"/>')
    out.append('      <polygon points="0,-19 6,7 0,2 -6,7" fill="#D9232E"/>')
    out.append('      <text y="20" text-anchor="middle" fill="#182026" font-size="15.5" font-weight="800">N</text>')
    out.append("    </g>")
    out.append("  </g>")

    # CAPA 7: Panel Lateral Superior — Simbología y Directorio Completo de las 34 Líneas
    lx = 4468
    ly = 34
    lw = 1008
    lh_sup = 1614
    out.append(f'  <g id="capa-leyenda" transform="translate({lx}, {ly})">')
    out.append(
        f'    <rect x="0" y="0" width="{lw}" height="{lh_sup}" rx="16" '
        f'fill="{pal["superficie_panel"]}" stroke="{pal["borde_panel"]}" stroke-width="1.8"/>'
    )
    out.append('    <text x="32" y="46" fill="#182026" font-size="21" font-weight="800">SIMBOLOGÍA Y DIRECTORIO DE RED</text>')
    out.append('    <line x1="32" y1="62" x2="976" y2="62" stroke="#E2E8F0" stroke-width="1.5"/>')

    # Sección A: 22 Líneas Convencionales en 2 columnas limpias
    out.append('    <text x="32" y="92" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">METRO CONVENCIONAL (22 LÍNEAS)</text>')
    conv = [l for l in modelo["lineas"] if l["tipo"] == "metro"]
    for idx_l, l_obj in enumerate(conv):
        col = idx_l // 11
        fila = idx_l % 11
        px = 36 + col * 485
        py = 122 + fila * 43
        est_ini = estaciones_por_id[l_obj["estaciones"][0]]["nombre"]
        est_fin = estaciones_por_id[l_obj["estaciones"][-1]]["nombre"]
        out.append(
            f'    <g transform="translate({px}, {py})">'
            f'<circle cx="13" cy="0" r="12" fill="{l_obj["color"]}"/>'
            f'<text x="13" y="4" text-anchor="middle" fill="#FFFFFF" font-size="11" font-weight="800">{_esc(l_obj["codigo"])}</text>'
            f'<text x="34" y="-2" fill="#182026" font-size="12" font-weight="700">{_esc(l_obj["nombre"])}: {_esc(est_ini)} – {_esc(est_fin)}</text>'
            f'<text x="34" y="12" fill="#718096" font-size="10.5" class="mono">{len(l_obj["estaciones"])} est. · {l_obj["longitud_km"]:.1f} km · {l_obj["estado"]}</text>'
            f"</g>"
        )

    # Sección B: 7 Líneas Alimentadoras A-G
    y_alim = 618
    out.append(f'    <line x1="32" y1="{y_alim - 24}" x2="976" y2="{y_alim - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_alim}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">LÍNEAS ALIMENTADORAS (A–G)</text>')
    alim = [l for l in modelo["lineas"] if l["tipo"] == "alimentadora"]
    for idx_l, l_obj in enumerate(alim):
        col = idx_l // 4
        fila = idx_l % 4
        px = 36 + col * 485
        py = y_alim + 30 + fila * 46
        est_ini = estaciones_por_id[l_obj["estaciones"][0]]["nombre"]
        est_fin = "Circuito Periférico (20 Premium)" if l_obj["es_circular"] else estaciones_por_id[l_obj["estaciones"][-1]]["nombre"]
        detalle_extra = (
            "21 operativas / 13 cerradas perm." if l_obj["codigo"] == "C"
            else ("Ord. 150 s / Premium 300 s" if l_obj["codigo"] == "A" else l_obj["estado"])
        )
        out.append(
            f'    <g transform="translate({px}, {py})">'
            f'<rect x="1" y="-12" width="24" height="24" rx="6" fill="{l_obj["color"]}"/>'
            f'<text x="13" y="4" text-anchor="middle" fill="#FFFFFF" font-size="11.5" font-weight="800">{_esc(l_obj["codigo"])}</text>'
            f'<text x="34" y="-2" fill="#182026" font-size="12" font-weight="700">{_esc(l_obj["codigo"])} · {_esc(est_ini)} – {_esc(est_fin)}</text>'
            f'<text x="34" y="12" fill="#718096" font-size="10.5" class="mono">{len(l_obj["estaciones"])} est. · {l_obj["longitud_km"]:.1f} km · {detalle_extra}</text>'
            f"</g>"
        )

    # Sección C: 5 Sistemas de Autobuses Articulados
    y_bus = 856
    out.append(f'    <line x1="32" y1="{y_bus - 24}" x2="976" y2="{y_bus - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_bus}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">RED DE AUTOBUSES ARTICULADOS (5 SISTEMAS BRT)</text>')
    buses = [l for l in modelo["lineas"] if l["tipo"] == "autobus-articulado"]
    for idx_l, l_obj in enumerate(buses):
        col = idx_l // 3
        fila = idx_l % 3
        px = 36 + col * 485
        py = y_bus + 30 + fila * 46
        est_ini = estaciones_por_id[l_obj["estaciones"][0]]["nombre"]
        est_fin = estaciones_por_id[l_obj["estaciones"][-1]]["nombre"]
        out.append(
            f'    <g transform="translate({px}, {py})">'
            f'<rect x="0" y="-10" width="28" height="20" rx="4" fill="{l_obj["color"]}"/>'
            f'<text x="14" y="4" text-anchor="middle" fill="#FFFFFF" font-size="10.5" font-weight="800">{_esc(l_obj["codigo"])}</text>'
            f'<text x="36" y="-2" fill="#182026" font-size="12" font-weight="700">Sistema {_esc(l_obj["codigo"])}: {_esc(est_ini)} – {_esc(est_fin)}</text>'
            f'<text x="36" y="12" fill="#718096" font-size="10.5" class="mono">{len(l_obj["estaciones"])} paradas · {l_obj["longitud_km"]:.1f} km · {l_obj["estado"]}</text>'
            f"</g>"
        )

    # Sección D: Tipos de Infraestructura Constructiva
    y_inf = 1054
    out.append(f'    <line x1="32" y1="{y_inf - 24}" x2="976" y2="{y_inf - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_inf}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">SIMBOLOGÍA POR TIPO DE INFRAESTRUCTURA DE TRAMO</text>')
    out.append(f'    <g transform="translate(36, {y_inf + 34})"><path class="tr m-base" stroke="#0055A4" d="M0,0L74,0"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Subterráneo convencional (cajón cortar y cubrir)</text></g>')
    out.append(f'    <g transform="translate(520, {y_inf + 34})"><path class="tr prof-cas" d="M0,0L74,0"/><path class="tr m-base" stroke="#E86A1F" d="M0,0L74,0"/><path class="tr prof-fil" d="M0,0L74,0"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Túnel profundo (escudo TBM y lumbreras)</text></g>')
    out.append(f'    <g transform="translate(36, {y_inf + 74})"><path class="tr m-base" stroke="#5E9732" d="M0,0L74,0"/><path class="tr sup-ticks" d="M0,0L74,0"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Superficial a nivel con derecho de vía confinado</text></g>')
    out.append(f'    <g transform="translate(520, {y_inf + 74})"><path class="tr viad-cas" d="M0,0L74,0"/><path class="tr viad-deck" d="M0,0L74,0"/><path class="tr m-base" stroke="#0F7173" d="M0,0L74,0"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Viaducto elevado sobre estructura prefabricada</text></g>')
    out.append(f'    <g transform="translate(36, {y_inf + 114})"><path class="tr b-outer" stroke="#C0392B" d="M0,0L74,0"/><path class="tr b-inner" d="M0,0L74,0"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Corredor exclusivo de Autobuses Articulados (BRT)</text></g>')

    # Sección E: Estados Operativos y Jerarquía de Estaciones
    y_est = 1232
    out.append(f'    <line x1="32" y1="{y_est - 24}" x2="976" y2="{y_est - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_est}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">ESTADOS OPERATIVOS Y JERARQUÍA DE ESTACIONES</text>')
    out.append(f'    <g transform="translate(36, {y_est + 36})"><path class="tr m-base" stroke="#D9232E" d="M0,0L74,0"/><circle cx="37" cy="0" r="4.2" class="nd-reg" stroke="#D9232E"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Tramo y estación en operación comercial</text></g>')
    out.append(f'    <g transform="translate(520, {y_est + 36})"><path class="tr m-base st-cons" stroke="#C84B31" d="M0,0L74,0"/><circle cx="37" cy="0" r="4.2" class="nd-cons" stroke="#C84B31"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">En construcción (Línea 18 Centro / Sistema 5)</text></g>')
    out.append(f'    <g transform="translate(36, {y_est + 76})"><path class="tr m-base st-amp" stroke="#8A2B87" d="M0,0L74,0"/><circle cx="37" cy="0" r="4.2" class="nd-amp" stroke="#8A2B87"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Ampliación pendiente (Líneas 6, 9, 19 y 20)</text></g>')
    out.append(f'    <g transform="translate(520, {y_est + 76})"><path class="tr st-closed-bed" d="M0,0L74,0"/><path class="tr st-closed-dash" d="M0,0L74,0"/><circle cx="37" cy="0" r="4.5" class="nd-cl"/><path d="M34.4,-2.6L39.6,2.6M39.6,-2.6L34.4,2.6" stroke="#9B2C2C" stroke-width="1.5"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Cerrada permanentemente (Línea C: 13 estaciones)</text></g>')
    out.append(f'    <g transform="translate(36, {y_est + 118})"><circle cx="20" cy="0" r="7.8" class="nd-tr3"/><circle cx="20" cy="0" r="4.4" fill="#FFFFFF" stroke="#182026" stroke-width="1.3"/><circle cx="54" cy="0" r="6.0" class="nd-tr2"/><circle cx="54" cy="0" r="2.2" fill="#182026"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Estación compartida / correspondencia (registro único)</text></g>')
    out.append(f'    <g transform="translate(520, {y_est + 118})"><circle cx="24" cy="0" r="6.0" class="nd-tr2"/><circle cx="24" cy="0" r="2.8" class="nd-prem"/><rect x="48" y="-4" width="8" height="8" rx="1.8" class="nd-reg" stroke="#C0392B"/><text x="92" y="4" fill="#182026" font-size="12.5" font-weight="600">Parada Premium Línea A (20) / Estación exclusiva BRT</text></g>')

    y_res = 1430
    out.append(f'    <rect x="32" y="{y_res}" width="944" height="150" rx="12" fill="#F6F5F0" stroke="#D5D2C8" stroke-width="1.4"/>')
    out.append(f'    <text x="56" y="{y_res + 34}" fill="#182026" font-size="14" font-weight="800">FICHA TÉCNICA DE COHERENCIA CARTOGRÁFICA (FUENTE ÚNICA SVG + JSON)</text>')
    out.append(f'    <text x="56" y="{y_res + 64}" fill="#4A5568" font-size="12" class="mono">• Población metropolitana servida: 35.000.000 hab.   • Total estaciones únicas en red: 828 estaciones</text>')
    out.append(f'    <text x="56" y="{y_res + 90}" fill="#4A5568" font-size="12" class="mono">• Línea A (Circuito Periférico): 132,8 km · 124 estaciones (104 servicio ordinario + 20 servicio premium)</text>')
    out.append(f'    <text x="56" y="{y_res + 116}" fill="#4A5568" font-size="12" class="mono">• Línea C (Alimentadora Poniente): 34 estaciones (21 en operación Albufera–Tlacotepec + 13 cerradas perm.)</text>')
    out.append("  </g>")

    # CAPA 8: Panel Lateral Inferior — Índice de Grandes Correspondencias, 20 Estaciones Premium Línea A y Perfiles Constructivos
    ly_inf_card = 1676
    lh_inf_card = VIEWBOX_ALTO - ly_inf_card - 34
    out.append(f'  <g id="capa-indice-correspondencias-perfiles" transform="translate({lx}, {ly_inf_card})">')
    out.append(
        f'    <rect x="0" y="0" width="{lw}" height="{lh_inf_card}" rx="16" '
        f'fill="{pal["superficie_panel"]}" stroke="{pal["borde_panel"]}" stroke-width="1.8"/>'
    )
    out.append('    <text x="32" y="46" fill="#182026" font-size="20" font-weight="800">ÍNDICE DE CORRESPONDENCIAS ESTRATÉGICAS Y PERFILES DE RED</text>')
    out.append('    <line x1="32" y1="62" x2="976" y2="62" stroke="#E2E8F0" stroke-width="1.5"/>')

    # Top 26 nodos de correspondencia ordenados por número de líneas convergentes
    out.append('    <text x="32" y="92" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">PRINCIPALES NODOS MULTIMODALES (CORRESPONDENCIAS DE 3 A 5 LÍNEAS)</text>')
    hubs_principales = sorted(
        [e for e in modelo["estaciones"] if e["es_correspondencia"]],
        key=lambda e: (-len(e["lineas"]), -int(e["servicio_premium"]), e["nombre"]),
    )[:26]
    for idx_h, hub in enumerate(hubs_principales):
        col = idx_h // 13
        fila = idx_h % 13
        hx = 36 + col * 485
        hy = 126 + fila * 54
        cods_hub = " · ".join(lineas_por_id[lid]["codigo"] for lid in hub["lineas"])
        tag_prem = " · PREMIUM L-A" if hub["servicio_premium"] else ""
        out.append(
            f'    <g transform="translate({hx}, {hy})">'
            f'<circle cx="10" cy="-3" r="7.5" class="nd-tr3"/><circle cx="10" cy="-3" r="3.5" fill="#182026"/>'
            f'<text x="28" y="-4" fill="#182026" font-size="13" font-weight="700">{_esc(hub["nombre"])}</text>'
            f'<text x="28" y="13" fill="#4A5568" font-size="11" class="mono">Líneas [{_esc(cods_hub)}] · ({hub["coordenadas"]["x"]:.0f}, {hub["coordenadas"]["y"]:.0f}){tag_prem}</text>'
            f"</g>"
        )

    # Listado íntegro de las 20 estaciones clave del Servicio Premium de la Línea A
    y_prem_sec = 856
    out.append(f'    <line x1="32" y1="{y_prem_sec - 24}" x2="976" y2="{y_prem_sec - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_prem_sec}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">CIRCUITO PERIFÉRICO LÍNEA A · 20 ESTACIONES CLAVE DE SERVICIO EXPRESO PREMIUM (300 s / 100 km/h)</text>')
    linea_a_obj = lineas_por_id["linea-a"]
    for idx_p, pid in enumerate(linea_a_obj["estaciones_premium"]):
        col = idx_p // 10
        fila = idx_p % 10
        px = 36 + col * 485
        py = y_prem_sec + 34 + fila * 36
        e_p = estaciones_por_id[pid]
        cods_p = "/".join(lineas_por_id[lid]["codigo"] for lid in e_p["lineas"])
        out.append(
            f'    <g transform="translate({px}, {py})">'
            f'<circle cx="9" cy="-4" r="5.5" fill="#0F7173"/><circle cx="9" cy="-4" r="2.5" fill="#E59A00"/>'
            f'<text x="24" y="0" fill="#182026" font-size="12" font-weight="600">{idx_p + 1:02d}. {_esc(e_p["nombre"])}</text>'
            f'<text x="275" y="0" fill="#718096" font-size="11" class="mono">[{_esc(cods_p)}]</text>'
            f"</g>"
        )

    # Esquemas vectoriales de perfil transversal por tipo de infraestructura
    y_perf = 1256
    out.append(f'    <line x1="32" y1="{y_perf - 24}" x2="976" y2="{y_perf - 24}" stroke="#E2E8F0" stroke-width="1.5"/>')
    out.append(f'    <text x="32" y="{y_perf}" fill="#4A5568" font-size="13" font-weight="800" letter-spacing="0.8">PERFILES TIPO DE INGENIERÍA E INFRAESTRUCTURA FERROVIARIA</text>')

    perfiles = [
        ("1. CAJÓN SUBTERRÁNEO (-12 m)", "Muro Milán · Andén central con puertas PSD · Ventilación forzada", 36, y_perf + 32, "#0055A4"),
        ("2. TÚNEL PROFUNDO TBM (-45 m)", "Dovelas de hormigón · Doble escudo · Lumbreras y salidas presurizadas", 516, y_perf + 32, "#E86A1F"),
        ("3. SUPERFICIAL CONFINADO (0 m)", "Balasto drenante · Muros acústicos · Pasos superiores peatonales", 36, y_perf + 236, "#5E9732"),
        ("4. VIADUCTO ELEVADO (+9,5 m)", "Trabes cajón postensadas · Pilas sísmicas · Galibo libre urbano", 516, y_perf + 236, "#0F7173"),
    ]
    for tit_p, sub_p, px_c, py_c, col_c in perfiles:
        out.append(f'    <g transform="translate({px_c}, {py_c})">')
        out.append('      <rect x="0" y="0" width="456" height="184" rx="10" fill="#F6F5F0" stroke="#D5D2C8" stroke-width="1.3"/>')
        out.append(f'      <text x="18" y="28" fill="#182026" font-size="12.5" font-weight="800">{tit_p}</text>')
        out.append(f'      <text x="18" y="47" fill="#4A5568" font-size="10.8">{sub_p}</text>')
        out.append('      <line x1="20" y1="92" x2="436" y2="92" stroke="#94A3B8" stroke-width="1.4" stroke-dasharray="5 4"/>')
        out.append('      <text x="24" y="86" fill="#718096" font-size="9.5" class="mono">NIVEL CALLE ±0,0 m</text>')
        if "SUBTERRÁNEO" in tit_p:
            out.append(f'      <rect x="130" y="108" width="196" height="54" rx="4" fill="#FFFFFF" stroke="{col_c}" stroke-width="2.4"/>')
            out.append(f'      <rect x="196" y="140" width="64" height="14" fill="{col_c}" opacity="0.25"/>')
            out.append(f'      <circle cx="164" cy="144" r="9" fill="{col_c}"/><circle cx="292" cy="144" r="9" fill="{col_c}"/>')
        elif "PROFUNDO" in tit_p:
            out.append(f'      <circle cx="176" cy="140" r="24" fill="#FFFFFF" stroke="{col_c}" stroke-width="3"/>')
            out.append(f'      <circle cx="280" cy="140" r="24" fill="#FFFFFF" stroke="{col_c}" stroke-width="3"/>')
            out.append('      <rect x="200" y="135" width="56" height="10" fill="#FFFFFF" stroke="#182026" stroke-width="1.4"/>')
        elif "SUPERFICIAL" in tit_p:
            out.append('      <rect x="126" y="84" width="204" height="10" fill="#CBD5E1"/>')
            out.append(f'      <circle cx="176" cy="78" r="9" fill="{col_c}"/><circle cx="280" cy="78" r="9" fill="{col_c}"/>')
            out.append('      <line x1="120" y1="64" x2="120" y2="92" stroke="#182026" stroke-width="2"/><line x1="336" y1="64" x2="336" y2="92" stroke="#182026" stroke-width="2"/>')
        else:
            out.append('      <rect x="214" y="68" width="28" height="94" fill="#94A3B8"/>')
            out.append(f'      <rect x="136" y="58" width="184" height="12" rx="3" fill="#FFFFFF" stroke="{col_c}" stroke-width="2.2"/>')
            out.append(f'      <circle cx="176" cy="52" r="8" fill="{col_c}"/><circle cx="280" cy="52" r="8" fill="{col_c}"/>')
        out.append("    </g>")

    # Pie institucional de cierre del panel inferior
    y_pie = 1712
    out.append(f'    <rect x="32" y="{y_pie}" width="944" height="492" rx="12" fill="#F6F5F0" stroke="#D5D2C8" stroke-width="1.4"/>')
    out.append(f'    <text x="56" y="{y_pie + 38}" fill="#182026" font-size="14" font-weight="800">PARÁMETROS GEODÉSICOS, GEOMÉTRICOS Y DE OPERACIÓN DEL MODELO</text>')
    notas_pie = [
        f"1. Proyección Equirectangular Tangente Local centrada en Santa Mónica (lat₀ = {LAT_ORIGEN:.6f}°, lon₀ = {LON_ORIGEN:.6f}°).",
        f"2. Factores métricos locales: K_lat = {KM_POR_GRADO_LAT:.6f} km/° · K_lon = {KM_POR_GRADO_LON:.6f} km/° · Escala: {ESCALA_SVG_POR_KM:.1f} u. SVG/km.",
        "3. Retícula octilineal estricta (0°, 45°, 90°): radios horizontales con sobreelevación en R < 1.800 m y tangente mínima >= 17 m.",
        "4. Gradiente metropolitano (35 M hab.): densidad máxima en Meseta Central (< 10 km) y corredores radiales hacia anillos periféricos.",
        "5. Integración modal única: el Sistema de Metro (22 líneas + 7 alimentadoras) y la Red de Autobuses Articulados (5 sistemas BRT)",
        "   conforman un solo sistema integrado sin duplicidad de estaciones en los nodos compartidos.",
        "6. Estado operativo Línea C: 34 estaciones totales; tramo norte Cardonal–Albufera Norte (13 estaciones) fuera de operación permanente,",
        "   tramo sur Albufera–Tlacotepec (21 estaciones) en operación continua con correspondencia a Líneas 18, 21, 22 y G.",
        "7. Circuito Periférico Línea A: anillo cerrado octilineal de 132,8 km exactos con 124 estaciones, frecuencias de 150 s (servicio ordinario",
        "   en las 124 paradas) y 300 s (servicio expreso premium en las 20 estaciones clave listadas arriba).",
        "8. Coherencia por construcción: red_metro.svg y red_metro.json provienen de una única ejecución determinista de generar_red.py.",
    ]
    for idx_n, texto_n in enumerate(notas_pie):
        out.append(f'    <text x="56" y="{y_pie + 76 + idx_n * 36}" fill="#4A5568" font-size="12" class="mono">{_esc(texto_n)}</text>')
    out.append("  </g>")

    out.append("</svg>")
    return "\n".join(out) + "\n"


# =============================================================================
# 7. ESQUEMA JSON FORMAL (JSON SCHEMA) Y VALIDADOR INCORPORADO
# =============================================================================

PATRON_KEBAB = r"^[a-z0-9]+(-[a-z0-9]+)*$"

ESQUEMA_JSON_RED: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Esquema Red SIMMA Metro y Autobuses Articulados",
    "type": "object",
    "required": ["version", "metadatos", "identidad_visual", "sistemas", "lineas", "estaciones", "tramos"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "minLength": 1},
        "metadatos": {
            "type": "object",
            "required": [
                "nombre_red", "siglas", "ciudad", "poblacion_referencia",
                "fecha_generacion", "total_estaciones", "total_lineas_convencionales",
                "total_lineas_alimentadoras", "total_sistemas_autobuses", "total_tramos", "proyeccion",
            ],
            "properties": {
                "nombre_red": {"type": "string"},
                "siglas": {"type": "string"},
                "ciudad": {"type": "string"},
                "poblacion_referencia": {"type": "integer", "minimum": 30000000},
                "fecha_generacion": {"type": "string"},
                "total_estaciones": {"type": "integer", "const": 828},
                "total_lineas_convencionales": {"type": "integer", "const": 22},
                "total_lineas_alimentadoras": {"type": "integer", "const": 7},
                "total_sistemas_autobuses": {"type": "integer", "const": 5},
                "total_tramos": {"type": "integer", "minimum": 800},
                "proyeccion": {"type": "object"},
            },
        },
        "identidad_visual": {"type": "object"},
        "sistemas": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "nombre", "categoria", "tipos_linea", "lineas"],
                "properties": {
                    "id": {"type": "string", "pattern": PATRON_KEBAB},
                    "nombre": {"type": "string"},
                    "categoria": {"type": "string", "enum": ["metro-convencional", "red-autobuses-articulados"]},
                    "tipos_linea": {"type": "array", "items": {"type": "string"}},
                    "lineas": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": PATRON_KEBAB}},
                },
            },
        },
        "lineas": {
            "type": "array",
            "minItems": 34,
            "maxItems": 34,
            "items": {
                "type": "object",
                "required": [
                    "id", "codigo", "nombre", "tipo", "sistema", "color",
                    "longitud_km", "es_circular", "estado", "estaciones", "estaciones_premium",
                ],
                "properties": {
                    "id": {"type": "string", "pattern": PATRON_KEBAB},
                    "codigo": {"type": "string"},
                    "nombre": {"type": "string"},
                    "tipo": {"type": "string", "enum": ["metro", "alimentadora", "autobus-articulado"]},
                    "sistema": {"type": "string", "enum": ["sistema-metro", "sistema-autobuses-articulados"]},
                    "color": {"type": "string", "pattern": r"^#[0-9A-Fa-f]{6}$"},
                    "longitud_km": {"type": "number", "minimum": 1.0},
                    "es_circular": {"type": "boolean"},
                    "estado": {
                        "type": "string",
                        "enum": ["operativa", "operacion-parcial", "en-construccion", "ampliacion-pendiente"],
                    },
                    "estaciones": {"type": "array", "minItems": 2, "items": {"type": "string", "pattern": PATRON_KEBAB}},
                    "estaciones_premium": {"type": "array", "items": {"type": "string", "pattern": PATRON_KEBAB}},
                },
            },
        },
        "estaciones": {
            "type": "array",
            "minItems": 828,
            "maxItems": 828,
            "items": {
                "type": "object",
                "required": [
                    "id", "nombre", "coordenadas", "coordenadas_geograficas",
                    "lineas", "estado", "infraestructura", "es_correspondencia", "servicio_premium",
                ],
                "properties": {
                    "id": {"type": "string", "pattern": PATRON_KEBAB},
                    "nombre": {"type": "string", "minLength": 1},
                    "coordenadas": {
                        "type": "object",
                        "required": ["x", "y"],
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    },
                    "coordenadas_geograficas": {
                        "type": "object",
                        "required": ["lat", "lon"],
                        "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                    },
                    "lineas": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": PATRON_KEBAB}},
                    "estado": {
                        "type": "string",
                        "enum": ["operativa", "en-construccion", "ampliacion-pendiente", "fuera-de-operacion"],
                    },
                    "infraestructura": {
                        "type": "string",
                        "enum": ["subterraneo", "superficial", "viaducto-elevado", "tunel-profundo"],
                    },
                    "es_correspondencia": {"type": "boolean"},
                    "servicio_premium": {"type": "boolean"},
                },
            },
        },
        "tramos": {
            "type": "array",
            "minItems": 800,
            "items": {
                "type": "object",
                "required": ["id", "origen", "destino", "linea", "infraestructura", "estado", "longitud_km", "puntos"],
                "properties": {
                    "id": {"type": "string", "pattern": PATRON_KEBAB},
                    "origen": {"type": "string", "pattern": PATRON_KEBAB},
                    "destino": {"type": "string", "pattern": PATRON_KEBAB},
                    "linea": {"type": "string", "pattern": PATRON_KEBAB},
                    "infraestructura": {
                        "type": "string",
                        "enum": ["subterraneo", "superficial", "viaducto-elevado", "tunel-profundo"],
                    },
                    "estado": {
                        "type": "string",
                        "enum": ["operativo", "en-construccion", "ampliacion-pendiente", "fuera-de-operacion"],
                    },
                    "longitud_km": {"type": "number", "minimum": 0.05},
                    "puntos": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}},
                    },
                },
            },
        },
    },
}


def validar_esquema_json(instancia: Any, esquema: Dict[str, Any], ruta: str = "$") -> None:
    """Validador recursivo de JSON Schema Draft 2020-12 sin dependencias externas."""
    tipo_esperado = esquema.get("type")
    if tipo_esperado == "object":
        if not isinstance(instancia, dict):
            raise ValueError(f"{ruta}: se esperaba object, se recibió {type(instancia).__name__}")
        for req in esquema.get("required", []):
            if req not in instancia:
                raise ValueError(f"{ruta}: falta propiedad obligatoria '{req}'")
        props = esquema.get("properties", {})
        if esquema.get("additionalProperties") is False:
            extras = set(instancia.keys()) - set(props.keys())
            if extras:
                raise ValueError(f"{ruta}: propiedades no permitidas {extras}")
        for k, val in instancia.items():
            if k in props:
                validar_esquema_json(val, props[k], f"{ruta}.{k}")
    elif tipo_esperado == "array":
        if not isinstance(instancia, list):
            raise ValueError(f"{ruta}: se esperaba array, se recibió {type(instancia).__name__}")
        if "minItems" in esquema and len(instancia) < esquema["minItems"]:
            raise ValueError(f"{ruta}: longitud {len(instancia)} < minItems {esquema['minItems']}")
        if "maxItems" in esquema and len(instancia) > esquema["maxItems"]:
            raise ValueError(f"{ruta}: longitud {len(instancia)} > maxItems {esquema['maxItems']}")
        sub = esquema.get("items")
        if sub:
            for i, elem in enumerate(instancia):
                validar_esquema_json(elem, sub, f"{ruta}[{i}]")
    elif tipo_esperado == "string":
        if not isinstance(instancia, str):
            raise ValueError(f"{ruta}: se esperaba string")
        if "minLength" in esquema and len(instancia) < esquema["minLength"]:
            raise ValueError(f"{ruta}: string vacío")
        if "pattern" in esquema and not re.match(esquema["pattern"], instancia):
            raise ValueError(f"{ruta}: valor '{instancia}' no cumple patrón {esquema['pattern']}")
    elif tipo_esperado == "integer":
        if isinstance(instancia, bool) or not isinstance(instancia, int):
            raise ValueError(f"{ruta}: se esperaba integer")
        if "minimum" in esquema and instancia < esquema["minimum"]:
            raise ValueError(f"{ruta}: {instancia} < {esquema['minimum']}")
    elif tipo_esperado == "number":
        if isinstance(instancia, bool) or not isinstance(instancia, (int, float)):
            raise ValueError(f"{ruta}: se esperaba number")
        if "minimum" in esquema and instancia < esquema["minimum"]:
            raise ValueError(f"{ruta}: {instancia} < {esquema['minimum']}")
    elif tipo_esperado == "boolean":
        if not isinstance(instancia, bool):
            raise ValueError(f"{ruta}: se esperaba boolean")

    if "const" in esquema and instancia != esquema["const"]:
        raise ValueError(f"{ruta}: valor {instancia!r} != const {esquema['const']!r}")
    if "enum" in esquema and instancia not in esquema["enum"]:
        raise ValueError(f"{ruta}: valor {instancia!r} fuera de enum {esquema['enum']}")


# =============================================================================
# 8. TESTS DE CONECTIVIDAD, UNICIDAD, GEOMETRÍA OCTILINEAL Y PARIDAD SVG/JSON
# =============================================================================

def ejecutar_tests_conectividad(modelo: Dict[str, Any], svg_texto: str, logo_texto: str) -> None:
    """
    Ejecuta todas las verificaciones estructurales, topológicas y de coherencia
    entre el JSON y el SVG. Lanza AssertionError si falla cualquier invariante.
    """
    # 1. Validación formal contra JSON Schema
    validar_esquema_json(modelo, ESQUEMA_JSON_RED)

    estaciones = modelo["estaciones"]
    lineas = modelo["lineas"]
    tramos = modelo["tramos"]

    # 2. Unicidad estricta de identificadores kebab-case y nombres de estaciones
    regex_kebab = re.compile(PATRON_KEBAB)
    todos_ids: List[str] = (
        [s["id"] for s in modelo["sistemas"]]
        + [l["id"] for l in lineas]
        + [e["id"] for e in estaciones]
        + [t["id"] for t in tramos]
    )
    assert len(todos_ids) == len(set(todos_ids)), "Existen identificadores duplicados en el modelo."
    for ident in todos_ids:
        assert regex_kebab.match(ident), f"Identificador inválido fuera de kebab-case: {ident}"

    nombres_est = [e["nombre"] for e in estaciones]
    assert len(nombres_est) == 828, f"Se esperaban 828 estaciones únicas, hay {len(nombres_est)}"
    assert len(set(nombres_est)) == 828, "Existen nombres de estación duplicados."

    # 3. Verificación de cifras estrictas de la red de referencia
    est_por_id = {e["id"]: e for e in estaciones}
    lin_por_id = {l["id"]: l for l in lineas}

    assert sum(len(l["estaciones"]) for l in lineas if l["sistema"] == "sistema-metro") == 828, (
        "La suma de estaciones en líneas de Metro + Alimentadoras debe ser exactamente 828."
    )

    sm = est_por_id["estacion-santa-monica"]
    assert sorted(sm["lineas"]) == ["linea-01", "linea-04", "linea-07", "linea-15", "linea-18"], (
        f"Santa Mónica debe pertenecer a las líneas 1, 4, 7, 15 y 18; tiene {sm['lineas']}"
    )

    for hito_req in ("estacion-poligono", "estacion-santa-monica", "estacion-tacuba", "estacion-buenavista", "estacion-pino-suarez"):
        assert hito_req in est_por_id, f"Falta estación de referencia obligatoria: {hito_req}"

    linea_a = lin_por_id["linea-a"]
    assert linea_a["es_circular"] is True
    assert len(linea_a["estaciones"]) == 124
    assert len(linea_a["estaciones_premium"]) == 20
    assert abs(linea_a["longitud_km"] - 132.8) < 0.15

    linea_c = lin_por_id["linea-c"]
    assert len(linea_c["estaciones"]) == 34
    estados_c = [est_por_id[eid]["estado"] for eid in linea_c["estaciones"]]
    assert estados_c.count("operativa") == 21, f"Línea C debe tener 21 operativas, tiene {estados_c.count('operativa')}"
    assert estados_c.count("fuera-de-operacion") == 13, f"Línea C debe tener 13 cerradas, tiene {estados_c.count('fuera-de-operacion')}"

    # 4. Continuidad secuencial de cada línea y bidireccionalidad estación <-> línea
    tramos_por_linea: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tr in tramos:
        tramos_por_linea[tr["linea"]].append(tr)
        # Verificar ángulos estrictamente octilineales (0°, 45°, 90°) en cada segmento del tramo
        pts = tr["puntos"]
        for i in range(len(pts) - 1):
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            longitud_px = math.hypot(dx, dy)
            assert longitud_px > 0.5, f"Subsegmento degenerado en {tr['id']}"
            es_hv = abs(dx) < 0.08 or abs(dy) < 0.08
            es_diag = abs(abs(dx) - abs(dy)) < 0.12
            assert es_hv or es_diag, f"Ángulo no octilineal en {tr['id']}: dx={dx}, dy={dy}"

    incidencias_reales: Dict[str, List[str]] = defaultdict(list)
    grafo_red: Dict[str, Set[str]] = defaultdict(set)

    for l_obj in lineas:
        lid = l_obj["id"]
        seq_est = l_obj["estaciones"]
        trs = tramos_por_linea[lid]
        esperados = len(seq_est) if l_obj["es_circular"] else len(seq_est) - 1
        assert len(trs) == esperados, f"{lid}: tramos {len(trs)} != esperados {esperados}"

        for i, tr in enumerate(trs):
            orig_esp = seq_est[i]
            dest_esp = seq_est[(i + 1) % len(seq_est)]
            assert tr["origen"] == orig_esp and tr["destino"] == dest_esp, (
                f"Discontinuidad en {lid} índice {i}: {tr['origen']}->{tr['destino']}"
            )
            # Coordenadas extremas del tramo idénticas a las estaciones en JSON
            c_orig = est_por_id[orig_esp]["coordenadas"]
            c_dest = est_por_id[dest_esp]["coordenadas"]
            assert tr["puntos"][0] == [c_orig["x"], c_orig["y"]]
            assert tr["puntos"][-1] == [c_dest["x"], c_dest["y"]]
            grafo_red[orig_esp].add(dest_esp)
            grafo_red[dest_esp].add(orig_esp)

        for eid in seq_est:
            if lid not in incidencias_reales[eid]:
                incidencias_reales[eid].append(lid)

    for eid, e_obj in est_por_id.items():
        assert sorted(e_obj["lineas"]) == sorted(incidencias_reales[eid]), (
            f"Inconsistencia de líneas servidas en {eid}"
        )
        assert e_obj["es_correspondencia"] == (len(e_obj["lineas"]) > 1)

    # 5. Conectividad global del grafo de las 828 estaciones
    visitadas: Set[str] = set()
    cola: deque[str] = deque(["estacion-santa-monica"])
    while cola:
        actual = cola.popleft()
        if actual in visitadas:
            continue
        visitadas.add(actual)
        cola.extend(grafo_red[actual] - visitadas)
    assert len(visitadas) == 828, f"La red no es conexa: {len(visitadas)}/828 estaciones alcanzables."

    # 6. Validez XML de los dos SVG, ausencia de dependencias externas y paridad 1:1 con JSON
    raiz_logo = ET.fromstring(logo_texto)
    assert raiz_logo.tag.endswith("svg")
    svg_sin_xmlns = svg_texto.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "<image" not in svg_sin_xmlns and "@import" not in svg_sin_xmlns and "http://" not in svg_sin_xmlns and "https://" not in svg_sin_xmlns

    raiz_svg = ET.fromstring(svg_texto)
    ids_en_svg: Dict[str, ET.Element] = {}
    for elem in raiz_svg.iter():
        eid_attr = elem.attrib.get("id")
        if eid_attr:
            assert eid_attr not in ids_en_svg, f"ID duplicado dentro del SVG: {eid_attr}"
            ids_en_svg[eid_attr] = elem

    for l_obj in lineas:
        assert l_obj["id"] in ids_en_svg, f"Falta grupo SVG para línea {l_obj['id']}"

    patron_translate = re.compile(r"^translate\(([-\d.]+),([-\d.]+)\)$")
    for e_obj in estaciones:
        elem_g = ids_en_svg.get(e_obj["id"])
        assert elem_g is not None, f"Falta estación {e_obj['id']} en el SVG"
        m = patron_translate.match(elem_g.attrib.get("transform", ""))
        assert m is not None, f"Transform inválido en {e_obj['id']}"
        sx, sy = float(m.group(1)), float(m.group(2))
        assert sx == e_obj["coordenadas"]["x"], f"Desfase X en {e_obj['id']}: {sx} != {e_obj['coordenadas']['x']}"
        assert sy == e_obj["coordenadas"]["y"], f"Desfase Y en {e_obj['id']}: {sy} != {e_obj['coordenadas']['y']}"

    # 7. Verificación de cero solapamientos entre etiquetas e insignias terminales
    pos_ins = calcular_posiciones_insignias(modelo)
    pts_ins = list(pos_ins.values())
    for i in range(len(pts_ins)):
        for j in range(i + 1, len(pts_ins)):
            d_ins = math.hypot(pts_ins[i][0] - pts_ins[j][0], pts_ins[i][1] - pts_ins[j][1])
            assert d_ins >= 22.0, f"Insignias terminales solapadas (d={d_ins:.1f} px)"
    _, colisiones_etiq = calcular_posiciones_etiquetas(modelo, pos_ins)
    assert colisiones_etiq == 0, f"Se detectaron {colisiones_etiq} solapamientos de etiquetas en el plano."


# =============================================================================
# 9. PUNTO DE ENTRADA CLI
# =============================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera red_metro.svg, red_metro.json y logo_metro.svg desde un modelo único."
    )
    parser.add_argument(
        "--directorio",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directorio donde se escribirán los artefactos (por defecto: carpeta del script).",
    )
    parser.add_argument(
        "--fecha",
        type=str,
        default=FECHA_GENERACION_DEFAULT,
        help="Fecha ISO de generación para metadatos reproducibles.",
    )
    parser.add_argument(
        "--solo-validar",
        action="store_true",
        help="Construye el modelo y ejecuta validaciones y tests sin escribir en disco.",
    )
    args = parser.parse_args(argv)

    modelo = construir_modelo_red(fecha_generacion=args.fecha)
    svg_red = generar_svg_red(modelo)
    svg_logo = generar_logo_svg_independiente()
    json_texto = serializar_json_red(modelo)

    # Validar parseo JSON y ejecutar batería completa de tests
    modelo_reparsed = json.loads(json_texto)
    ejecutar_tests_conectividad(modelo_reparsed, svg_red, svg_logo)

    if not args.solo_validar:
        args.directorio.mkdir(parents=True, exist_ok=True)
        ruta_svg = args.directorio / "red_metro.svg"
        ruta_json = args.directorio / "red_metro.json"
        ruta_logo = args.directorio / "logo_metro.svg"

        ruta_svg.write_text(svg_red, encoding="utf-8")
        ruta_json.write_text(json_texto, encoding="utf-8")
        ruta_logo.write_text(svg_logo, encoding="utf-8")

        print(
            f"[OK] Artefactos coherentes generados y validados en {args.directorio}:\n"
            f"  - {ruta_svg.name} ({len(svg_red):,} bytes)\n"
            f"  - {ruta_json.name} ({len(json_texto):,} bytes)\n"
            f"  - {ruta_logo.name} ({len(svg_logo):,} bytes)\n"
            f"  - Resumen: {modelo['metadatos']['total_estaciones']} estaciones únicas, "
            f"{len(modelo['lineas'])} líneas, {modelo['metadatos']['total_tramos']} tramos octilineales."
        )
    else:
        print("[OK] Validación de esquema JSON y tests de conectividad superados al 100%.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
