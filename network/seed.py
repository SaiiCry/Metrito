"""
Servicio de inicialización y poblado topológico/geoespacial del backend Django
directamente a partir del artefacto maestro validado ``cartografia/red_metro.json``
(generado junto con ``cartografia/red_metro.svg`` por ``cartografia/generar_red.py``).
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from django.conf import settings
from django.db import transaction

from .models import CityOutline, LineStation, OperationalAlert, Station, TransitLine, UserNetworkEditLayer


RUTA_CARTOGRAFIA_DIR = Path(settings.BASE_DIR) / "cartografia"
RUTA_RED_JSON = RUTA_CARTOGRAFIA_DIR / "red_metro.json"
RUTA_RED_SVG = RUTA_CARTOGRAFIA_DIR / "red_metro.svg"
RUTA_LOGO_SVG = RUTA_CARTOGRAFIA_DIR / "logo_metro.svg"
RUTA_USER_EDITS_JSON = RUTA_CARTOGRAFIA_DIR / "user_network_edits.json"

# Parámetros de la Proyección Equirectangular Tangente Local (coherentes con red_metro.json)
LAT_ORIGEN = 19.420000
LON_ORIGEN = -99.140000
RADIO_TIERRA_KM = 6371.0088
KM_POR_GRADO_LAT = (math.pi / 180.0) * RADIO_TIERRA_KM
KM_POR_GRADO_LON = KM_POR_GRADO_LAT * math.cos(math.radians(LAT_ORIGEN))
ESCALA_SVG_POR_KM = 54.0
ORIGEN_SVG_X = 2120.0
ORIGEN_SVG_Y = 1860.0


def xy_to_latlng(x: float, y: float) -> Tuple[float, float]:
    """
    Proyección inversa exacta desde coordenadas SVG (x, y) a coordenadas
    geográficas (lat, lng) según la Proyección Equirectangular Tangente Local.
    """
    este_km = (float(x) - ORIGEN_SVG_X) / ESCALA_SVG_POR_KM
    norte_km = (ORIGEN_SVG_Y - float(y)) / ESCALA_SVG_POR_KM
    lat = LAT_ORIGEN + (norte_km / KM_POR_GRADO_LAT)
    lng = LON_ORIGEN + (este_km / KM_POR_GRADO_LON)
    return round(lat, 6), round(lng, 6)


def cargar_fuente_cartografica() -> Dict[str, Any]:
    """Lee y retorna el diccionario validado de ``cartografia/red_metro.json``."""
    return json.loads(RUTA_RED_JSON.read_text(encoding="utf-8"))


DEFAULT_CITY_OUTLINES = [
    {
        "code": "zona-meseta-central",
        "name": "Meseta Central Metropolitana",
        "zone_type": "urban_core",
        "color": "#ECEAE2",
        "opacity": 0.72,
        "elevation_m": 2248.0,
        "polygon_points": [
            [1269.5, 1115.8], [2970.5, 1115.8], [3183.1, 1328.5], [3183.1, 2444.8],
            [2864.2, 2763.7], [1375.8, 2763.7], [1056.9, 2444.8], [1056.9, 1328.5],
        ],
    },
    {
        "code": "zona-corredor-industrial-norte",
        "name": "Corredor Industrial Norte",
        "zone_type": "industrial",
        "color": "#E5E9F0",
        "opacity": 0.78,
        "elevation_m": 2225.0,
        "polygon_points": [
            [1588.5, 796.9], [3874.1, 796.9], [4139.9, 531.1],
            [4139.9, 212.2], [1694.8, 212.2], [1588.5, 424.8],
        ],
    },
    {
        "code": "zona-corredor-ecologico-poniente",
        "name": "Corredor Ecológico Poniente – San Ángel – Greta",
        "zone_type": "park",
        "color": "#DCEAD7",
        "opacity": 0.72,
        "elevation_m": 2255.0,
        "polygon_points": [
            [578.5, 1434.8], [1375.8, 1434.8], [1375.8, 2604.2],
            [1694.8, 2923.2], [897.4, 2923.2], [578.5, 2604.2],
        ],
    },
    {
        "code": "zona-terminal-aereo-sur-universidad",
        "name": "Terminal Aéreo Sur Álvarez Morisot y Ciudad Universitaria",
        "zone_type": "airport",
        "color": "#E1ECF7",
        "opacity": 0.78,
        "elevation_m": 2242.0,
        "polygon_points": [
            [1588.5, 2710.6], [2545.2, 2710.6], [2545.2, 3189.0], [1588.5, 3189.0],
        ],
    },
    {
        "code": "zona-reserva-bosque-encantado",
        "name": "Reserva Forestal Bosque Encantado y Sierra Sur",
        "zone_type": "park",
        "color": "#DCEAD7",
        "opacity": 0.75,
        "elevation_m": 2285.0,
        "polygon_points": [
            [1163.2, 3242.1], [3289.4, 3242.1], [3661.5, 3614.2],
            [3448.9, 3826.8], [1375.8, 3826.8], [1163.2, 3614.2],
        ],
    },
]

MAPA_INFRA_DJANGO = {
    "subterraneo": "subterraneo",
    "tunel-profundo": "tunel_profundo",
    "superficial": "superficial",
    "viaducto-elevado": "elevado",
}

MAPA_ESTADO_ESTACION_DJANGO = {
    "operativa": "operational",
    "en-construccion": "construction",
    "ampliacion-pendiente": "expansion_planned",
    "fuera-de-operacion": "closed_permanent",
}

MAPA_ESTADO_TRAMO_DJANGO = {
    "operativo": "operational",
    "en-construccion": "construction",
    "ampliacion-pendiente": "expansion_planned",
    "fuera-de-operacion": "closed_permanent",
}

MAPA_ESTADO_LINEA_DJANGO = {
    "operativa": "operational",
    "operacion-parcial": "partial",
    "en-construccion": "construction",
    "ampliacion-pendiente": "expansion_pending",
}

COTAS_PROFUNDIDAD = {
    "subterraneo": -12.0,
    "tunel_profundo": -42.0,
    "superficial": 0.0,
    "elevado": 9.5,
}


def _perfil_ingenieria_estacion(
    infra_django: str, es_correspondencia: bool, es_terminal: bool, es_premium: bool, es_bus: bool
) -> Dict[str, Any]:
    if es_premium:
        platform_type, platform_count = "seis_andenes", 6
    elif es_bus:
        platform_type, platform_count = "brt_central", 2
    elif es_terminal and es_correspondencia:
        platform_type, platform_count = "triple", 3
    else:
        platform_type = "lateral" if infra_django in ("superficial", "elevado") else "central"
        platform_count = 2

    if infra_django == "tunel_profundo":
        vent = "Lumbreras verticales TBM (-28 m a -65 m) con extractores axiales reversibles y exclusas cortafuego"
        dren = "Cárcamo de bombeo redundante N+2, elevadores de alta velocidad y escaleras electromecánicas"
        salidas, psd = (6 if es_correspondencia else 4), True
    elif infra_django == "subterraneo":
        vent = "Inyección y extracción mecánica en cajón cortar y cubrir con pozos de alivio y control HVAC"
        dren = "Cárcamo pluvial automatizado, ascensores hidráulicos, guías podotáctiles y accesibilidad universal"
        salidas, psd = (6 if es_correspondencia else 4), True
    elif infra_django == "elevado":
        vent = "Ventilación natural cruzada en viaducto prefabricado con cubiertas aerodinámicas y topes sísmicos"
        dren = "Bajadas pluviales en pilas de hormigón postensado, pasarelas con elevadores y escaleras mecánicas"
        salidas, psd = (4 if es_correspondencia else 2), True
    else:
        vent = "Ventilación natural a nivel de calzada con arbolado de amortiguamiento y cubierta fotovoltaica"
        dren = "Drenaje longitudinal por gravedad con colectores pluviales perimetrales y rampas PMR al 6%"
        salidas, psd = (4 if es_correspondencia else 2), (not es_bus)

    return {
        "platform_type": platform_type,
        "platform_count": platform_count,
        "has_psd": psd,
        "ventilation_system": vent,
        "emergency_exits": salidas,
        "Drainage_and_accessibility": dren,
    }


@transaction.atomic
def _deducir_icon_tags_iniciales(
    nombre: str, num_lineas: int, es_term: bool, es_prem: bool
) -> List[str]:
    """
    Asigna etiquetas iconográficas iniciales coherentes entre las 6 categorías oficiales:
    aeropuerto, parque, terminal, centro_modal, zona_cultural, escuela.
    """
    n = nombre.lower()
    tags: List[str] = []
    if any(k in n for k in ("aeropuerto", "terminal aérea", "terminal aerea", "morisot")):
        tags.append("aeropuerto")
    if any(k in n for k in ("bosque", "parque", "viveros", "jardín", "jardin", "reserva", "ecológico", "ecologico", "alameda", "flor de loto")):
        tags.append("parque")
    if any(k in n for k in ("terminal norte", "central de abastos", "cuatro caminos", "observatorio", "pantitlán", "tlacotepec", "puerto de alvarado", "ciudad azteca")):
        tags.append("terminal")
    if num_lineas >= 3 or (num_lineas >= 2 and es_prem):
        tags.append("centro_modal")
    if any(k in n for k in ("catedral", "bellas artes", "museo", "cultura", "teatro", "fórum", "forum", "plaza mayor", "centro histórico", "poetisa", "cervantes")):
        tags.append("zona_cultural")
    if any(k in n for k in ("universidad", "politécnico", "politecnico", "facultad", "rectoría", "rectoria", "técnica", "tecnica", "uaa-", "uab-", "ucm-", "unamuno", "colegio", "seminario")):
        tags.append("escuela")
    return tags


def seed_database(force_reset: bool = False) -> Dict[str, Any]:
    """
    Sincroniza la base de datos relacional Django directamente desde ``cartografia/red_metro.json``.
    Si no se fuerza un reinicio (force_reset=False) y la base ya contiene datos, conserva
    estrictamente todas las creaciones y ediciones del usuario sin borrarlas.
    """
    if (
        not force_reset
        and (TransitLine.objects.exists() or Station.objects.exists())
    ):
        return {
            "seeded": False,
            "lines": TransitLine.objects.count(),
            "stations": Station.objects.count(),
            "line_stations": LineStation.objects.count(),
        }

    OperationalAlert.objects.all().delete()
    LineStation.objects.all().delete()
    Station.objects.all().delete()
    TransitLine.objects.all().delete()
    CityOutline.objects.all().delete()

    datos = cargar_fuente_cartografica()

    # 1. Poblar zonas urbanas y corredores geográficos
    for outline_data in DEFAULT_CITY_OUTLINES:
        CityOutline.objects.create(**outline_data)

    estaciones_json_por_id = {e["id"]: e for e in datos["estaciones"]}
    lineas_json_por_id = {l["id"]: l for l in datos["lineas"]}

    # Identificar terminales y qué código(s) de línea terminan/inician en cada estación
    terminales_por_estacion: Dict[str, List[str]] = defaultdict(list)
    grados_por_linea: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for tr in datos["tramos"]:
        lid_tr = tr["linea"]
        grados_por_linea[lid_tr][tr["origen"]] += 1
        grados_por_linea[lid_tr][tr["destino"]] += 1

    for l_obj in datos["lineas"]:
        lid = l_obj["id"]
        code = l_obj["codigo"]
        ests_l = l_obj["estaciones"]
        if not ests_l:
            continue
        if l_obj["es_circular"]:
            # Primera estación declarada del circuito (terminal origen de Línea A)
            if code not in terminales_por_estacion[ests_l[0]]:
                terminales_por_estacion[ests_l[0]].append(code)
        else:
            deg_map = grados_por_linea.get(lid, {})
            endpoints = [eid for eid in ests_l if deg_map.get(eid, 0) == 1]
            if not endpoints:
                endpoints = [ests_l[0], ests_l[-1]]
            for eid_term in endpoints:
                if code not in terminales_por_estacion[eid_term]:
                    terminales_por_estacion[eid_term].append(code)

    terminales_ids = set(terminales_por_estacion.keys())

    # 2. Crear exactamente las 828 estaciones únicas (sin duplicados en estaciones compartidas)
    station_objs: Dict[str, Station] = {}
    lista_stations_bulk: List[Station] = []

    for e_data in datos["estaciones"]:
        eid = e_data["id"]
        infra_dj = MAPA_INFRA_DJANGO[e_data["infraestructura"]]
        estado_dj = MAPA_ESTADO_ESTACION_DJANGO[e_data["estado"]]
        es_corr = bool(e_data["es_correspondencia"])
        es_term = eid in terminales_ids
        es_prem = bool(e_data["servicio_premium"])
        solo_bus = all(lid.startswith("autobuses-") for lid in e_data["lineas"])
        prof_m = COTAS_PROFUNDIDAD[infra_dj]
        eng = _perfil_ingenieria_estacion(infra_dj, es_corr, es_term, es_prem, solo_bus)

        lista_stations_bulk.append(
            Station(
                code=eid,
                name=e_data["nombre"],
                x=float(e_data["coordenadas"]["x"]),
                y=float(e_data["coordenadas"]["y"]),
                lat=float(e_data["coordenadas_geograficas"]["lat"]),
                lng=float(e_data["coordenadas_geograficas"]["lon"]),
                infrastructure_type=infra_dj,
                operational_status=estado_dj,
                depth_meters=prof_m,
                platform_type=eng["platform_type"],
                platform_count=eng["platform_count"],
                has_psd=eng["has_psd"],
                ventilation_system=eng["ventilation_system"],
                emergency_exits=eng["emergency_exits"],
                Drainage_and_accessibility=eng["Drainage_and_accessibility"],
                is_transfer=es_corr,
                is_terminal=es_term,
                has_depot=es_term,
                depot_details="Patio de maniobras y cochera terminal" if es_term else "",
                is_premium_stop=es_prem,
                icon_tags=_deducir_icon_tags_iniciales(
                    e_data["nombre"], len(e_data["lineas"]), es_term, es_prem
                ),
                terminal_lines=terminales_por_estacion.get(eid, []),
            )
        )

    Station.objects.bulk_create(lista_stations_bulk)
    for st in Station.objects.all():
        station_objs[st.code] = st

    # Indexar tramos por línea
    tramos_por_linea: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tr in datos["tramos"]:
        tramos_por_linea[tr["linea"]].append(tr)

    # 3. Crear las 34 líneas y sus secuencias LineStation
    line_objs: Dict[str, TransitLine] = {}
    lista_linestations_bulk: List[LineStation] = []

    for order_idx, l_data in enumerate(datos["lineas"]):
        lid = l_data["id"]
        code = l_data["codigo"]
        tipo_json = l_data["tipo"]
        es_bus = (tipo_json == "autobus-articulado")
        network_type = "bus_articulado" if es_bus else "metro"
        line_subtype = "autobus" if es_bus else ("alimentadora" if tipo_json == "alimentadora" else "convencional")

        ids_est = l_data["estaciones"]
        est_ini_nom = estaciones_json_por_id[ids_est[0]]["nombre"]
        est_fin_nom = "Circuito Periférico" if l_data["es_circular"] else estaciones_json_por_id[ids_est[-1]]["nombre"]
        trs = tramos_por_linea[lid]

        if code == "C":
            op_count = 21
        else:
            op_count = sum(
                1 for eid in ids_est
                if estaciones_json_por_id[eid]["estado"] == "operativa"
            )

        min_radius = 180.0 if es_bus else (350.0 if code == "A" else 250.0)
        line_obj = TransitLine.objects.create(
            code=code,
            name=l_data["nombre"],
            route_title=f"{est_ini_nom} – {est_fin_nom}",
            direction_axis=f"Identificador SVG/JSON: {lid}",
            network_type=network_type,
            line_subtype=line_subtype,
            color=l_data["color"],
            text_color="#ffffff",
            length_km=float(l_data["longitud_km"]),
            total_track_km=round(float(l_data["longitud_km"]) * 1.12, 2),
            declared_stations_count=len(ids_est),
            operational_stations_count=op_count,
            status=MAPA_ESTADO_LINEA_DJANGO[l_data["estado"]],
            status_note=(
                "Circuito Periférico de 132,8 km y 124 estaciones (Ordinario 150 s / Premium 300 s en 20 estaciones clave)."
                if code == "A"
                else (
                    "34 estaciones totales: 21 operativas (Albufera – Tlacotepec) y 13 cerradas permanentemente."
                    if code == "C"
                    else f"Trazado octilineal sincronizado con cartografia/red_metro.svg ({lid})."
                )
            ),
            frequency_seconds=int(l_data["frecuencia_segundos"]),
            premium_frequency_seconds=l_data.get("frecuencia_premium_segundos"),
            max_speed_kmh=float(l_data["velocidad_max_kmh"]),
            premium_speed_kmh=100.0 if code == "A" else None,
            rolling_stock="Volvo 7300 Biarticulado BRT" if es_bus else "Alstom Metrópolis SIMMA",
            traction_type="Carril Confinado Autobús Articulado" if es_bus else "Neumática / Férrea · 750 VCC",
            annual_ridership_millions=1530.0 if code == "A" else (110.0 if es_bus else 320.0),
            current_occupancy_pct=88 if code == "A" else 68,
            min_curve_radius_m=min_radius,
            superelevation_mm=125.0,
            min_tangent_between_curves_m=17.0,
            min_curve_length_m=16.0,
            depots_info=f"Talleres y cocheras terminales {est_ini_nom}",
            is_circular=bool(l_data["es_circular"]),
            display_order=order_idx,
            custom_geometry={
                "svg_id": lid,
                "polylines": [t["puntos"] for t in trs],
            },
        )
        line_objs[code] = line_obj

        acum_km = 0.0
        set_premium = set(l_data.get("estaciones_premium", []))
        for seq_idx, eid in enumerate(ids_est):
            st_obj = station_objs[eid]
            e_json = estaciones_json_por_id[eid]
            tr_ref = trs[seq_idx] if seq_idx < len(trs) else trs[-1]

            if code == "C":
                seg_status = "closed_permanent" if seq_idx < 13 else "operational"
            else:
                seg_status = MAPA_ESTADO_TRAMO_DJANGO[tr_ref["estado"]]

            seg_infra = MAPA_INFRA_DJANGO[tr_ref["infraestructura"]]
            cods_corr = "/".join(
                lineas_json_por_id[otro_lid]["codigo"]
                for otro_lid in e_json["lineas"]
            ) if len(e_json["lineas"]) > 1 else ""

            curve_r = 450.0 if (seq_idx % 3 != 0) else 1950.0
            super_deg = round(1800.0 / curve_r * 1.15, 2) if curve_r < 1800.0 else 0.0
            tangent_m = round(max(17.0, float(tr_ref["longitud_km"]) * 680.0), 3)

            lista_linestations_bulk.append(
                LineStation(
                    line=line_obj,
                    station=st_obj,
                    sequence=seq_idx,
                    branch="main",
                    segment_infrastructure=seg_infra,
                    segment_status=seg_status,
                    depth_meters=COTAS_PROFUNDIDAD[seg_infra],
                    chainage_km=round(acum_km, 4),
                    curve_radius_m=curve_r,
                    superelevation_deg=super_deg,
                    tangent_length_m=tangent_m,
                    correspondences_text=cods_corr,
                    notes="Parada Servicio Expreso Premium (300 s)" if eid in set_premium else "",
                    waypoints=tr_ref["puntos"][1:-1] if seq_idx < len(trs) and len(tr_ref.get("puntos", [])) > 2 else [],
                )
            )
            if seq_idx < len(trs):
                acum_km += float(trs[seq_idx]["longitud_km"])

    LineStation.objects.bulk_create(lista_linestations_bulk)

    # 4. Alertas operativas iniciales coherentes con red_metro.json
    OperationalAlert.objects.bulk_create(
        [
            OperationalAlert(
                title="Línea C: Clausura permanente del sector norte Cardonal – Albufera Norte (13 estaciones)",
                description=(
                    "Las 13 primeras estaciones de la Línea C permanecen fuera de operación de forma definitiva. "
                    "El servicio opera con normalidad en las 21 estaciones del tramo Albufera – Tlacotepec."
                ),
                severity="critical",
                category="civil",
                line=line_objs.get("C"),
                station=station_objs.get("estacion-tlacotepec"),
                speed_factor=1.0,
                delay_seconds=0,
                is_active=True,
            ),
            OperationalAlert(
                title="Línea A (Circuito Periférico 132,8 km): Operación sincronizada Ordinario (150 s) y Premium (300 s)",
                description=(
                    "Circulación continua en las 124 estaciones del anillo periférico y servicio expreso "
                    "en las 20 estaciones clave de transferencia."
                ),
                severity="info",
                category="signaling",
                line=line_objs.get("A"),
                station=station_objs.get("estacion-ciudad-azteca"),
                speed_factor=1.0,
                delay_seconds=0,
                is_active=True,
            ),
            OperationalAlert(
                title="Línea 18 y Autobuses Sistema 5: Obras activas en tramos centrales en construcción",
                description=(
                    "Avance programado de obra civil en la conexión central hacia Santa Mónica y en el corredor "
                    "de autobuses articulados Sistema 5."
                ),
                severity="warning",
                category="civil",
                line=line_objs.get("18"),
                station=station_objs.get("estacion-santa-monica"),
                speed_factor=0.85,
                delay_seconds=20,
                is_active=True,
            ),
        ]
    )

    return {
        "seeded": True,
        "lines": TransitLine.objects.count(),
        "stations": Station.objects.count(),
        "line_stations": LineStation.objects.count(),
    }


_cached_transfer_corridors: Optional[List[Dict[str, Any]]] = None


def get_cached_transfer_corridors() -> List[Dict[str, Any]]:
    global _cached_transfer_corridors
    if _cached_transfer_corridors is None:
        _cached_transfer_corridors = []
        if RUTA_USER_EDITS_JSON.exists():
            try:
                edits = json.loads(RUTA_USER_EDITS_JSON.read_text(encoding="utf-8"))
                if isinstance(edits, dict):
                    _cached_transfer_corridors = list(edits.get("transfer_corridors", []))
            except Exception:
                pass
    return list(_cached_transfer_corridors)


def set_cached_transfer_corridors(corridors: List[Dict[str, Any]]) -> None:
    global _cached_transfer_corridors
    _cached_transfer_corridors = list(corridors)


def export_user_network_layer(deleted_station_code: str = None, deleted_station_id: int = None) -> Dict[str, Any]:
    """
    Serializa todas las adiciones y modificaciones realizadas por el usuario:
    - Estaciones creadas (is_user_created=True) y modificadas (is_custom_modified=True)
    - Líneas creadas (is_user_created=True) y modificadas (is_custom_modified=True)
    - Trayectos de línea con waypoints personalizados o paradas añadidas
    Persiste la capa en la tabla UserNetworkEditLayer y en cartografia/user_network_edits.json.
    """
    created_stations = []
    for s in Station.objects.filter(is_user_created=True):
        created_stations.append({
            "code": s.code,
            "name": s.name,
            "x": s.x,
            "y": s.y,
            "lat": s.lat,
            "lng": s.lng,
            "infrastructure_type": s.infrastructure_type,
            "operational_status": s.operational_status,
            "depth_meters": s.depth_meters,
            "platform_type": s.platform_type,
            "platform_count": s.platform_count,
            "has_psd": s.has_psd,
            "is_transfer": s.is_transfer,
            "is_terminal": s.is_terminal,
            "is_premium_stop": s.is_premium_stop,
            "icon_tags": s.icon_tags,
            "terminal_lines": s.terminal_lines,
            "custom_color": s.custom_color or "",
            "is_user_created": True,
            "is_custom_modified": s.is_custom_modified,
        })

    modified_stations = []
    for s in Station.objects.filter(is_custom_modified=True, is_user_created=False):
        modified_stations.append({
            "code": s.code,
            "name": s.name,
            "x": s.x,
            "y": s.y,
            "lat": s.lat,
            "lng": s.lng,
            "infrastructure_type": s.infrastructure_type,
            "operational_status": s.operational_status,
            "depth_meters": s.depth_meters,
            "platform_type": s.platform_type,
            "platform_count": s.platform_count,
            "has_psd": s.has_psd,
            "is_transfer": s.is_transfer,
            "is_terminal": s.is_terminal,
            "is_premium_stop": s.is_premium_stop,
            "icon_tags": s.icon_tags,
            "terminal_lines": s.terminal_lines,
            "custom_color": s.custom_color or "",
        })

    created_lines = []
    for l in TransitLine.objects.filter(is_user_created=True):
        created_lines.append({
            "code": l.code,
            "name": l.name,
            "route_title": l.route_title,
            "direction_axis": l.direction_axis,
            "network_type": l.network_type,
            "line_subtype": l.line_subtype,
            "color": l.color,
            "text_color": l.text_color,
            "length_km": l.length_km,
            "total_track_km": l.total_track_km,
            "declared_stations_count": l.declared_stations_count,
            "operational_stations_count": l.operational_stations_count,
            "status": l.status,
            "frequency_seconds": l.frequency_seconds,
            "max_speed_kmh": l.max_speed_kmh,
            "custom_geometry": l.custom_geometry,
            "is_user_created": True,
            "is_custom_modified": l.is_custom_modified,
        })

    modified_lines = []
    for l in TransitLine.objects.filter(is_custom_modified=True, is_user_created=False):
        modified_lines.append({
            "code": l.code,
            "name": l.name,
            "route_title": l.route_title,
            "color": l.color,
            "text_color": l.text_color,
            "length_km": l.length_km,
            "frequency_seconds": l.frequency_seconds,
            "custom_geometry": l.custom_geometry,
        })

    # Líneas con trayectos o waypoints modificados
    route_overrides = {}
    for line in TransitLine.objects.prefetch_related("line_stations__station").all():
        line_stops = sorted(line.line_stations.all(), key=lambda ls: ls.sequence)
        has_custom = (
            line.is_user_created
            or line.is_custom_modified
            or any(len(ls.waypoints or []) > 0 or ls.station.is_user_created for ls in line_stops)
        )
        if has_custom:
            route_overrides[line.code] = [
                {
                    "sequence": ls.sequence,
                    "branch": ls.branch,
                    "station_code": ls.station.code,
                    "segment_infrastructure": ls.segment_infrastructure,
                    "segment_status": ls.segment_status,
                    "depth_meters": ls.depth_meters,
                    "chainage_km": ls.chainage_km,
                    "waypoints": ls.waypoints or [],
                    "correspondences_text": ls.correspondences_text,
                }
                for ls in line_stops
            ]

    global _cached_deleted_stations
    if "_cached_deleted_stations" not in globals():
        _cached_deleted_stations = set()
    if deleted_station_code:
        _cached_deleted_stations.add(str(deleted_station_code))
    if deleted_station_id:
        _cached_deleted_stations.add(str(deleted_station_id))
    existing_deleted = list(_cached_deleted_stations)

    transfer_corridors = get_cached_transfer_corridors()

    layer_payload = {
        "version": 1,
        "created_stations": created_stations,
        "modified_stations": modified_stations,
        "created_lines": created_lines,
        "modified_lines": modified_lines,
        "route_overrides": route_overrides,
        "deleted_stations": existing_deleted,
        "transfer_corridors": transfer_corridors,
    }

    # Guardar en SQLite (modelo UserNetworkEditLayer)
    layer_obj, _ = UserNetworkEditLayer.objects.update_or_create(
        name="default_user_layer",
        defaults={
            "data": layer_payload,
            "is_active": True,
        }
    )

    # Guardar en archivo local JSON separado
    try:
        RUTA_USER_EDITS_JSON.write_text(
            json.dumps(layer_payload, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        pass

    return {
        "ok": True,
        "layer_id": layer_obj.id,
        "created_stations_count": len(created_stations),
        "created_lines_count": len(created_lines),
        "modified_stations_count": len(modified_stations),
        "route_overrides_count": len(route_overrides),
    }


def apply_user_network_layer(layer_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Aplica la capa de ediciones guardada sobre la red actual.
    Si layer_data es None, intenta cargarla de SQLite o de cartografia/user_network_edits.json.
    """
    if layer_data is None:
        layer_rec = UserNetworkEditLayer.objects.filter(is_active=True).first()
        if layer_rec and layer_rec.data:
            layer_data = layer_rec.data
        elif RUTA_USER_EDITS_JSON.exists():
            try:
                layer_data = json.loads(RUTA_USER_EDITS_JSON.read_text(encoding="utf-8"))
            except Exception:
                layer_data = None

    if not layer_data:
        return {"applied": False, "reason": "No hay capa de edición disponible"}

    if "transfer_corridors" in layer_data:
        set_cached_transfer_corridors(layer_data.get("transfer_corridors", []))

    applied_stations = 0
    applied_lines = 0

    with transaction.atomic():
        # 0. Eliminar estaciones borradas por el usuario
        for code_or_id in layer_data.get("deleted_stations", []):
            Station.objects.filter(code=str(code_or_id)).delete()
            if str(code_or_id).isdigit():
                Station.objects.filter(id=int(code_or_id)).delete()

        # 1. Crear estaciones de usuario
        for s_data in layer_data.get("created_stations", []):
            st, _ = Station.objects.update_or_create(
                code=s_data["code"],
                defaults={
                    "name": s_data.get("name", "Estación Personalizada"),
                    "x": float(s_data.get("x", 6000.0)),
                    "y": float(s_data.get("y", 2000.0)),
                    "lat": float(s_data.get("lat", 19.4326)),
                    "lng": float(s_data.get("lng", -99.1332)),
                    "infrastructure_type": s_data.get("infrastructure_type", "subterraneo"),
                    "operational_status": s_data.get("operational_status", "operational"),
                    "depth_meters": float(s_data.get("depth_meters", -10.0)),
                    "platform_type": s_data.get("platform_type", "central"),
                    "platform_count": int(s_data.get("platform_count", 2)),
                    "has_psd": bool(s_data.get("has_psd", True)),
                    "is_transfer": bool(s_data.get("is_transfer", False)),
                    "is_terminal": bool(s_data.get("is_terminal", False)),
                    "is_premium_stop": bool(s_data.get("is_premium_stop", False)),
                    "icon_tags": s_data.get("icon_tags", []),
                    "terminal_lines": s_data.get("terminal_lines", []),
                    "custom_color": s_data.get("custom_color", ""),
                    "is_user_created": True,
                    "is_custom_modified": bool(s_data.get("is_custom_modified", False)),
                }
            )
            applied_stations += 1

        # 2. Aplicar modificaciones en estaciones existentes
        for s_data in layer_data.get("modified_stations", []):
            st = Station.objects.filter(code=s_data["code"]).first()
            if st:
                for k in ["name", "x", "y", "lat", "lng", "infrastructure_type", "operational_status",
                          "depth_meters", "platform_type", "platform_count", "has_psd", "is_transfer",
                          "is_terminal", "is_premium_stop", "icon_tags", "terminal_lines", "custom_color"]:
                    if k in s_data:
                        setattr(st, k, s_data[k])
                st.is_custom_modified = True
                st.save()

        # 3. Crear líneas de usuario
        for l_data in layer_data.get("created_lines", []):
            ln, _ = TransitLine.objects.update_or_create(
                code=l_data["code"],
                defaults={
                    "name": l_data.get("name", f"Línea {l_data['code']}"),
                    "route_title": l_data.get("route_title", ""),
                    "direction_axis": l_data.get("direction_axis", ""),
                    "network_type": l_data.get("network_type", "metro"),
                    "line_subtype": l_data.get("line_subtype", "convencional"),
                    "color": l_data.get("color", "#0052ff"),
                    "text_color": l_data.get("text_color", "#ffffff"),
                    "length_km": float(l_data.get("length_km", 10.0)),
                    "total_track_km": float(l_data.get("total_track_km", 12.0)),
                    "declared_stations_count": int(l_data.get("declared_stations_count", 0)),
                    "operational_stations_count": int(l_data.get("operational_stations_count", 0)),
                    "status": l_data.get("status", "operational"),
                    "frequency_seconds": int(l_data.get("frequency_seconds", 180)),
                    "max_speed_kmh": float(l_data.get("max_speed_kmh", 50.0)),
                    "custom_geometry": l_data.get("custom_geometry", {}),
                    "is_user_created": True,
                    "is_custom_modified": bool(l_data.get("is_custom_modified", False)),
                }
            )
            applied_lines += 1

        # 4. Modificar líneas existentes
        for l_data in layer_data.get("modified_lines", []):
            ln = TransitLine.objects.filter(code=l_data["code"]).first()
            if ln:
                for k in ["name", "route_title", "color", "text_color", "length_km", "frequency_seconds", "custom_geometry"]:
                    if k in l_data:
                        setattr(ln, k, l_data[k])
                ln.is_custom_modified = True
                ln.save()

        # 5. Restaurar trayectos de línea y waypoints
        for l_code, stops in layer_data.get("route_overrides", {}).items():
            ln = TransitLine.objects.filter(code=l_code).first()
            if not ln or not isinstance(stops, list) or len(stops) < 2:
                continue
            LineStation.objects.filter(line=ln).delete()
            new_ls_list = []
            for s_item in stops:
                st = Station.objects.filter(code=s_item.get("station_code")).first()
                if not st:
                    continue
                new_ls_list.append(
                    LineStation(
                        line=ln,
                        station=st,
                        sequence=int(s_item.get("sequence", 0)),
                        branch=str(s_item.get("branch", "main")),
                        segment_infrastructure=str(s_item.get("segment_infrastructure", st.infrastructure_type)),
                        segment_status=str(s_item.get("segment_status", st.operational_status)),
                        depth_meters=float(s_item.get("depth_meters", st.depth_meters)),
                        chainage_km=float(s_item.get("chainage_km", 0.0)),
                        waypoints=s_item.get("waypoints", []),
                        correspondences_text=str(s_item.get("correspondences_text", "")),
                    )
                )
            if new_ls_list:
                LineStation.objects.bulk_create(new_ls_list)

    return {
        "applied": True,
        "stations_applied": applied_stations,
        "lines_applied": applied_lines,
    }
