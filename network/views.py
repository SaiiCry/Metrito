"""
Controladores y API REST para el Sistema de Metro y Transporte (SMyT).
Expone toda la topología, geometría, infraestructura y estado operativo en JSON,
y permite editar en tiempo real líneas, estaciones, horarios, frecuencias,
trazados cartográficos, polígonos de la ciudad y alertas del PCCO.
"""

import json
import math
import random
import uuid
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

ALLOWED_ICON_TAGS = {
    "aeropuerto",
    "parque",
    "terminal",
    "centro_modal",
    "zona_cultural",
    "escuela",
}

from .models import CityOutline, TransitLine, Station, LineStation, OperationalAlert, UserNetworkEditLayer
from .ridership import calculate_line_ridership, get_network_ridership_summary
from .seed import (
    ESCALA_SVG_POR_KM,
    KM_POR_GRADO_LAT,
    KM_POR_GRADO_LON,
    LAT_ORIGEN,
    LON_ORIGEN,
    ORIGEN_SVG_X,
    ORIGEN_SVG_Y,
    RUTA_LOGO_SVG,
    RUTA_RED_SVG,
    apply_user_network_layer,
    cargar_fuente_cartografica,
    export_user_network_layer,
    get_cached_transfer_corridors,
    set_cached_transfer_corridors,
    seed_database,
    xy_to_latlng,
)


def index_view(request):
    """Renderiza la aplicación principal del Centro de Control y Mapa Interactivo SMyT."""
    seed_database(force_reset=False)
    return render(request, "network/index.html")


@require_http_methods(["GET"])
def api_network_data(request):
    """
    Devuelve la estructura completa de la red separada de la lógica de visualización:
    - Polígonos geográficos editables de la ciudad ficticia (city_outlines)
    - Catálogo de las 34 líneas con frecuencias, velocidades, estados y criterios geométricos (lines)
    - Nodos de estación con ingeniería civil, arquitectura y coordenadas esquemáticas/geográficas (stations)
    - Secuencia topológica de tramos por línea y ramal (line_stations)
    - Alertas activas e historial reciente del Centro de Control Operativo (alerts)
    - Indicadores clave de desempeño de la red (kpis)
    """
    seed_database(force_reset=False)

    outlines = [
        {
            "id": o.id,
            "code": o.code,
            "name": o.name,
            "zone_type": o.zone_type,
            "zone_type_label": o.get_zone_type_display(),
            "color": o.color,
            "opacity": o.opacity,
            "elevation_m": o.elevation_m,
            "polygon_points": o.polygon_points,
        }
        for o in CityOutline.objects.all()
    ]

    lines_qs = TransitLine.objects.prefetch_related("line_stations__station", "alerts").all()
    ridership_summary = get_network_ridership_summary(lines_qs)
    stations_qs = Station.objects.all()

    # Mapear qué líneas sirven a cada estación física
    station_served_lines = {}
    for ls in LineStation.objects.select_related("line").all():
        sid = ls.station_id
        if sid not in station_served_lines:
            station_served_lines[sid] = []
        code = ls.line.code
        if code not in station_served_lines[sid]:
            station_served_lines[sid].append(code)

    stations_dict = {}
    for s in stations_qs:
        stations_dict[s.id] = {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "x": s.x,
            "y": s.y,
            "lat": s.lat,
            "lng": s.lng,
            "infrastructure_type": s.infrastructure_type,
            "infrastructure_label": s.get_infrastructure_type_display(),
            "operational_status": s.operational_status,
            "status_label": s.get_operational_status_display(),
            "depth_meters": s.depth_meters,
            "platform_type": s.platform_type,
            "platform_label": s.get_platform_type_display(),
            "platform_count": s.platform_count,
            "has_psd": s.has_psd,
            "ventilation_system": s.ventilation_system,
            "emergency_exits": s.emergency_exits,
            "drainage_and_accessibility": s.Drainage_and_accessibility,
            "is_transfer": s.is_transfer,
            "is_terminal": s.is_terminal,
            "has_depot": s.has_depot,
            "depot_details": s.depot_details,
            "is_premium_stop": s.is_premium_stop,
            "icon_tags": [t for t in (s.icon_tags or []) if t in ALLOWED_ICON_TAGS],
            "terminal_lines": s.terminal_lines if isinstance(s.terminal_lines, list) else [],
            "lines": station_served_lines.get(s.id, []),
            "custom_color": s.custom_color or "",
            "is_user_created": s.is_user_created,
            "is_custom_modified": s.is_custom_modified,
        }

    lines_list = []
    metro_stations_sum = 0
    brt_stations_sum = 0
    total_metro_km = 0.0
    total_brt_km = 0.0

    for line in lines_qs:
        active_alerts = [a for a in line.alerts.all() if a.is_active]
        speed_factor = min([a.speed_factor for a in active_alerts], default=1.0)
        extra_delay = sum([a.delay_seconds for a in active_alerts])

        ls_items = []
        for ls in line.line_stations.all():
            st_info = stations_dict.get(ls.station_id)
            ls_items.append(
                {
                    "id": ls.id,
                    "sequence": ls.sequence,
                    "branch": ls.branch,
                    "station_id": ls.station_id,
                    "station_name": st_info["name"] if st_info else "",
                    "x": st_info["x"] if st_info else 6000.0,
                    "y": st_info["y"] if st_info else 2000.0,
                    "lat": st_info["lat"] if st_info else 19.4326,
                    "lng": st_info["lng"] if st_info else -99.1332,
                    "is_premium_stop": st_info["is_premium_stop"] if st_info else False,
                    "segment_infrastructure": ls.segment_infrastructure,
                    "segment_status": ls.segment_status,
                    "depth_meters": ls.depth_meters,
                    "chainage_km": ls.chainage_km,
                    "curve_radius_m": ls.curve_radius_m,
                    "superelevation_deg": ls.superelevation_deg,
                    "tangent_length_m": ls.tangent_length_m,
                    "correspondences_text": ls.correspondences_text,
                    "notes": ls.notes,
                    "waypoints": ls.waypoints,
                }
            )

        if line.network_type == "metro":
            metro_stations_sum += line.declared_stations_count
            total_metro_km += line.length_km
        else:
            brt_stations_sum += line.declared_stations_count
            total_brt_km += line.length_km

        lines_list.append(
            {
                "id": line.id,
                "code": line.code,
                "name": line.name,
                "route_title": line.route_title,
                "direction_axis": line.direction_axis,
                "network_type": line.network_type,
                "network_type_label": line.get_network_type_display(),
                "line_subtype": line.line_subtype,
                "line_subtype_label": line.get_line_subtype_display(),
                "color": line.color,
                "text_color": line.text_color,
                "length_km": line.length_km,
                "total_track_km": line.total_track_km,
                "declared_stations_count": line.declared_stations_count,
                "operational_stations_count": line.operational_stations_count,
                "status": line.status,
                "status_label": line.get_status_display(),
                "status_note": line.status_note,
                "frequency_seconds": line.frequency_seconds,
                "premium_frequency_seconds": line.premium_frequency_seconds,
                "max_speed_kmh": line.max_speed_kmh,
                "premium_speed_kmh": line.premium_speed_kmh,
                "first_train_time": line.first_train_time,
                "last_train_time": line.last_train_time,
                "rolling_stock": line.rolling_stock,
                "traction_type": line.traction_type,
                "annual_ridership_millions": line.annual_ridership_millions,
                "projected_annual_ridership_35m": ridership_summary["by_line"].get(line.code, {}).get("projected_annual_ridership_millions"),
                "real_vs_projected_ratio_35m": ridership_summary["by_line"].get(line.code, {}).get("real_vs_projected_ratio"),
                "daily_passengers_weekday_35m": ridership_summary["by_line"].get(line.code, {}).get("daily_passengers_weekday"),
                "passengers_per_km_annual": ridership_summary["by_line"].get(line.code, {}).get("passengers_per_km_millions"),
                "current_occupancy_pct": line.current_occupancy_pct,
                "min_curve_radius_m": line.min_curve_radius_m,
                "superelevation_mm": line.superelevation_mm,
                "min_tangent_between_curves_m": line.min_tangent_between_curves_m,
                "min_curve_length_m": line.min_curve_length_m,
                "depots_info": line.depots_info,
                "is_circular": line.is_circular,
                "custom_geometry": line.custom_geometry,
                "is_user_created": line.is_user_created,
                "is_custom_modified": line.is_custom_modified,
                "effective_speed_factor": speed_factor,
                "extra_delay_seconds": extra_delay,
                "active_alerts_count": len(active_alerts),
                "stops": ls_items,
            }
        )

    alerts_list = [
        {
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "severity": a.severity,
            "severity_label": a.get_severity_display(),
            "category": a.category,
            "category_label": a.get_category_display(),
            "line_id": a.line_id,
            "line_code": a.line.code if a.line else None,
            "line_color": a.line.color if a.line else "#64748b",
            "station_id": a.station_id,
            "station_name": a.station.name if a.station else None,
            "speed_factor": a.speed_factor,
            "delay_seconds": a.delay_seconds,
            "is_active": a.is_active,
            "created_at": a.created_at.strftime("%H:%M:%S") if a.created_at else "05:00:00",
        }
        for a in OperationalAlert.objects.select_related("line", "station").all()[:40]
    ]

    transfer_corridors_list = get_cached_transfer_corridors()

    return JsonResponse(
        {
            "city_outlines": outlines,
            "lines": lines_list,
            "stations": list(stations_dict.values()),
            "alerts": alerts_list,
            "transfer_corridors": transfer_corridors_list,
            "kpis": {
                "total_lines": len(lines_list),
                "metro_lines_count": sum(1 for l in lines_list if l["network_type"] == "metro"),
                "brt_lines_count": sum(1 for l in lines_list if l["network_type"] == "bus_articulado"),
                "metro_stations_total": metro_stations_sum,
                "brt_stations_total": brt_stations_sum,
                "unique_physical_nodes": len(stations_dict),
                "metro_length_km": round(total_metro_km, 2),
                "brt_length_km": round(total_brt_km, 2),
                "active_alerts": sum(1 for a in alerts_list if a["is_active"]),
                "annual_ridership_total_millions": ridership_summary["total_annual_ridership_real_millions"],
                "projected_annual_demand_35m_millions": ridership_summary["total_annual_demand_projected_millions"],
                "metro_annual_ridership_millions": ridership_summary["metro_annual_millions"],
                "brt_annual_ridership_millions": ridership_summary["brt_annual_millions"],
                "annual_trips_per_capita_35m": ridership_summary["annual_trips_per_capita"],
            },
            "ridership_analytics_35m": ridership_summary,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_update_line(request, line_code):
    """Actualiza los datos operativos, estéticos o geométricos de una línea y los persiste en SQLite."""
    line = get_object_or_404(TransitLine, code=line_code)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    editable_str = [
        "name", "route_title", "direction_axis", "network_type", "line_subtype",
        "color", "text_color", "status", "status_note", "first_train_time",
        "last_train_time", "rolling_stock", "traction_type", "depots_info"
    ]
    editable_float = [
        "length_km", "total_track_km", "max_speed_kmh", "premium_speed_kmh",
        "annual_ridership_millions", "min_curve_radius_m", "superelevation_mm",
        "min_tangent_between_curves_m", "min_curve_length_m"
    ]
    editable_int = [
        "declared_stations_count", "operational_stations_count",
        "frequency_seconds", "premium_frequency_seconds", "current_occupancy_pct"
    ]

    for field in editable_str:
        if field in payload and payload[field] is not None:
            setattr(line, field, str(payload[field]))

    for field in editable_float:
        if field in payload:
            val = payload[field]
            setattr(line, field, float(val) if val not in (None, "") else None)

    for field in editable_int:
        if field in payload:
            val = payload[field]
            setattr(line, field, int(val) if val not in (None, "") else None)

    if "custom_geometry" in payload and isinstance(payload["custom_geometry"], dict):
        line.custom_geometry = payload["custom_geometry"]

    line.is_custom_modified = True
    line.save()
    export_user_network_layer()
    return JsonResponse({"ok": True, "line_code": line.code})


@csrf_exempt
@require_http_methods(["POST"])
def api_update_station(request, station_id):
    """
    Actualiza nombre, posición cartográfica (x, y / lat, lng), tipo de infraestructura,
    estado operativo y arquitectura de una estación. Si cambia el tipo de infraestructura
    o estado en una línea específica, también sincroniza los registros LineStation.
    """
    station = get_object_or_404(Station, id=station_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    if "name" in payload and payload["name"]:
        station.name = str(payload["name"]).strip()

    coords_changed = False
    if "x" in payload and payload["x"] is not None:
        station.x = round(float(payload["x"]), 1)
        coords_changed = True
    if "y" in payload and payload["y"] is not None:
        station.y = round(float(payload["y"]), 1)
        coords_changed = True

    if "lat" in payload and "lng" in payload and not coords_changed:
        station.lat = round(float(payload["lat"]), 6)
        station.lng = round(float(payload["lng"]), 6)
        # Actualizar también (x, y) con la Proyección Equirectangular Tangente Local (54 u. SVG/km)
        station.x = round(ORIGEN_SVG_X + (station.lng - LON_ORIGEN) * KM_POR_GRADO_LON * ESCALA_SVG_POR_KM, 1)
        station.y = round(ORIGEN_SVG_Y - (station.lat - LAT_ORIGEN) * KM_POR_GRADO_LAT * ESCALA_SVG_POR_KM, 1)
        coords_changed = True
    elif coords_changed:
        station.lat, station.lng = xy_to_latlng(station.x, station.y)

    if "infrastructure_type" in payload and payload["infrastructure_type"]:
        station.infrastructure_type = str(payload["infrastructure_type"])
    if "operational_status" in payload and payload["operational_status"]:
        station.operational_status = str(payload["operational_status"])
    if "depth_meters" in payload and payload["depth_meters"] is not None:
        station.depth_meters = float(payload["depth_meters"])
    if "platform_type" in payload and payload["platform_type"]:
        station.platform_type = str(payload["platform_type"])
    if "platform_count" in payload and payload["platform_count"] is not None:
        station.platform_count = int(payload["platform_count"])
    if "has_psd" in payload:
        station.has_psd = bool(payload["has_psd"])
    if "is_premium_stop" in payload:
        station.is_premium_stop = bool(payload["is_premium_stop"])
    if "ventilation_system" in payload and payload["ventilation_system"]:
        station.ventilation_system = str(payload["ventilation_system"])
    if "emergency_exits" in payload and payload["emergency_exits"] is not None:
        station.emergency_exits = int(payload["emergency_exits"])
    if "drainage_and_accessibility" in payload and payload["drainage_and_accessibility"]:
        station.Drainage_and_accessibility = str(payload["drainage_and_accessibility"])
    if "icon_tags" in payload and isinstance(payload["icon_tags"], list):
        clean_tags = []
        for raw_tag in payload["icon_tags"]:
            t_str = str(raw_tag).strip()
            if t_str in ALLOWED_ICON_TAGS and t_str not in clean_tags:
                clean_tags.append(t_str)
        station.icon_tags = clean_tags

    if "terminal_lines" in payload and isinstance(payload["terminal_lines"], list):
        valid_codes = set(TransitLine.objects.values_list("code", flat=True))
        clean_terminals = []
        for raw_code in payload["terminal_lines"]:
            c_str = str(raw_code).strip()
            if c_str in valid_codes and c_str not in clean_terminals:
                clean_terminals.append(c_str)
        station.terminal_lines = clean_terminals
        station.is_terminal = len(clean_terminals) > 0
    elif "is_terminal" in payload:
        station.is_terminal = bool(payload["is_terminal"])

    if "is_transfer" in payload:
        station.is_transfer = bool(payload["is_transfer"])

    if "custom_color" in payload:
        station.custom_color = str(payload["custom_color"]).strip()

    if "primary_line" in payload:
        target_line = str(payload.get("primary_line") or "").strip()
        if target_line:
            target_line_obj = TransitLine.objects.filter(code=target_line).first()
            if target_line_obj:
                ls_exists = LineStation.objects.filter(station=station, line=target_line_obj).exists()
                if not ls_exists:
                    max_seq = LineStation.objects.filter(line=target_line_obj).count()
                    LineStation.objects.create(
                        line=target_line_obj,
                        station=station,
                        sequence=max_seq + 1,
                        branch="main",
                        segment_infrastructure=station.infrastructure_type,
                        segment_status=station.operational_status,
                        depth_meters=station.depth_meters,
                    )
        elif target_line == "":
            LineStation.objects.filter(station=station).delete()
            station.is_transfer = False
            station.is_terminal = False
            station.terminal_lines = []

    station.is_custom_modified = True
    station.save()

    # Sincronizar los segmentos de LineStation asociados en una única consulta SQL optimizada (sin N+1)
    sync_fields = {}
    if "infrastructure_type" in payload:
        sync_fields["segment_infrastructure"] = station.infrastructure_type
    if "operational_status" in payload:
        sync_fields["segment_status"] = station.operational_status
    if "depth_meters" in payload:
        sync_fields["depth_meters"] = station.depth_meters
    if sync_fields:
        LineStation.objects.filter(station=station).update(**sync_fields)

    export_user_network_layer()

    return JsonResponse(
        {
            "ok": True,
            "station": {
                "id": station.id,
                "name": station.name,
                "x": station.x,
                "y": station.y,
                "lat": station.lat,
                "lng": station.lng,
                "icon_tags": station.icon_tags,
                "terminal_lines": station.terminal_lines,
                "is_terminal": station.is_terminal,
                "custom_color": station.custom_color,
            },
        }
    )


def snap_point_to_octilinear(anchor, target, step_deg=45.0):
    """
    Alinea el punto target respecto al ancla al múltiplo angular exacto de step_deg (45° por defecto).
    Mantiene la distancia euclidiana y proyecta exactamente sobre el rayo angular octilineal:
    0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°.
    Garantiza dy == 0 en horizontales, dx == 0 en verticales y |dx| == |dy| en diagonales de 45°,
    eliminando cualquier desviación de punto flotante o redondeo trigonométrico.
    """
    ax = float(anchor[0])
    ay = float(anchor[1])
    tx = float(target[0])
    ty = float(target[1])
    dx = tx - ax
    dy = ty - ay
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        return [round(tx, 1), round(ty, 1)]

    # Si step_deg es 45.0 (octilineal estándar de diagramas esquemáticos de metro)
    if abs(step_deg - 45.0) < 1e-3:
        deg = math.degrees(math.atan2(dy, dx)) % 360.0
        oct_idx = int(round(deg / 45.0)) % 8
        d_diag = round(dist * 0.7071067811865476, 1)
        d_ortho = round(dist, 1)

        if oct_idx == 0:  # 0° Este (Horizontal derecha)
            return [round(ax + d_ortho, 1), round(ay, 1)]
        elif oct_idx == 1:  # 45° Sur-Este (Diagonal abajo-derecha)
            return [round(ax + d_diag, 1), round(ay + d_diag, 1)]
        elif oct_idx == 2:  # 90° Sur (Vertical abajo)
            return [round(ax, 1), round(ay + d_ortho, 1)]
        elif oct_idx == 3:  # 135° Sur-Oeste (Diagonal abajo-izquierda)
            return [round(ax - d_diag, 1), round(ay + d_diag, 1)]
        elif oct_idx == 4:  # 180° Oeste (Horizontal izquierda)
            return [round(ax - d_ortho, 1), round(ay, 1)]
        elif oct_idx == 5:  # 225° Norte-Oeste (Diagonal arriba-izquierda)
            return [round(ax - d_diag, 1), round(ay - d_diag, 1)]
        elif oct_idx == 6:  # 270° Norte (Vertical arriba)
            return [round(ax, 1), round(ay - d_ortho, 1)]
        elif oct_idx == 7:  # 315° Norte-Este (Diagonal arriba-derecha)
            return [round(ax + d_diag, 1), round(ay - d_diag, 1)]

    raw_angle = math.atan2(dy, dx)
    step_rad = math.radians(step_deg)
    snapped_angle = round(raw_angle / step_rad) * step_rad
    return [
        round(ax + dist * math.cos(snapped_angle), 1),
        round(ay + dist * math.sin(snapped_angle), 1),
    ]


@csrf_exempt
@require_http_methods(["POST"])
def api_update_segment_waypoints(request, ls_id):
    """
    Actualiza los vértices intermedios (waypoints) del trazo geométrico de un tramo LineStation,
    permitiendo moldear libremente curvas, codos y trayectorias de cualquier línea en el mapa.
    Si payload incluye 'snap': True (o snap_angle), aplica snap octilineal a múltiplos exactos de 45°.
    """
    ls = get_object_or_404(LineStation.objects.select_related("station", "line"), id=ls_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    raw_wps = payload.get("waypoints", [])
    if not isinstance(raw_wps, list):
        return JsonResponse({"error": "waypoints debe ser una lista de pares [x, y]"}, status=400)

    snap_enabled = bool(payload.get("snap", False))
    snap_step = float(payload.get("snap_angle", 45.0))

    clean_wps = []
    anchor = [float(ls.station.x), float(ls.station.y)]
    for pt in raw_wps:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            target = [float(pt[0]), float(pt[1])]
            if snap_enabled:
                snapped = snap_point_to_octilinear(anchor, target, step_deg=snap_step)
                clean_wps.append([round(snapped[0], 1), round(snapped[1], 1)])
                anchor = snapped
            else:
                clean_wps.append([round(target[0], 1), round(target[1], 1)])
                anchor = target

    ls.waypoints = clean_wps
    ls.save(update_fields=["waypoints"])
    ls.line.is_custom_modified = True
    ls.line.save(update_fields=["is_custom_modified"])
    export_user_network_layer()
    return JsonResponse({"ok": True, "id": ls.id, "waypoints": ls.waypoints})


@csrf_exempt
@require_http_methods(["POST"])
def api_update_line_route(request, line_code):
    """
    Actualiza el trayecto topológico (orden de paradas, inserción o eliminación de estaciones
    en la línea) o endereza todos los trazos (clear_all_waypoints) de una línea.
    """
    line = get_object_or_404(TransitLine, code=line_code)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    if payload.get("clear_all_waypoints") or payload.get("straighten_tracks"):
        straighten_orthogonal = payload.get("straighten_orthogonal", True)
        if straighten_orthogonal:
            # Enderezar derecho a 90° o 180° dependiendo de si la orientación entre estaciones es vertical u horizontal
            branches = {}
            for ls in LineStation.objects.filter(line=line).select_related("station").order_by("sequence"):
                branches.setdefault(ls.branch, []).append(ls)

            with transaction.atomic():
                for branch_name, stops in branches.items():
                    n = len(stops)
                    if n < 2:
                        continue
                    limit = n if (line.is_circular and branch_name == "main") else (n - 1)
                    for i in range(limit):
                        ls1 = stops[i]
                        ls2 = stops[(i + 1) % n]
                        st1 = ls1.station
                        st2 = ls2.station
                        dx = float(st2.x) - float(st1.x)
                        dy = float(st2.y) - float(st1.y)

                        if abs(dx) >= abs(dy):
                            # Orientación horizontal (180° / 0°):
                            if abs(dy) < 0.5:
                                ls1.waypoints = []
                            else:
                                # Trazo horizontal (180°) de (x1, y1) a (x2, y1), luego vertical (90°) a (x2, y2)
                                ls1.waypoints = [[round(float(st2.x), 1), round(float(st1.y), 1)]]
                        else:
                            # Orientación vertical (90° / 270°):
                            if abs(dx) < 0.5:
                                ls1.waypoints = []
                            else:
                                # Trazo vertical (90°) de (x1, y1) a (x1, y2), luego horizontal (180°) a (x2, y2)
                                ls1.waypoints = [[round(float(st1.x), 1), round(float(st2.y), 1)]]
                        ls1.save(update_fields=["waypoints"])

                    if not (line.is_circular and branch_name == "main") and n > 0:
                        stops[-1].waypoints = []
                        stops[-1].save(update_fields=["waypoints"])

                line.is_custom_modified = True
                line.save(update_fields=["is_custom_modified"])
                export_user_network_layer()

            return JsonResponse({
                "ok": True,
                "line_code": line.code,
                "cleared_waypoints": True,
                "straightened": True,
                "orthogonal": True
            })
        else:
            LineStation.objects.filter(line=line).update(waypoints=[])
            line.is_custom_modified = True
            line.save(update_fields=["is_custom_modified"])
            export_user_network_layer()
            return JsonResponse({"ok": True, "line_code": line.code, "cleared_waypoints": True})

    raw_stops = payload.get("stops")
    if not isinstance(raw_stops, list) or len(raw_stops) < 2:
        return JsonResponse({"error": "Una línea debe conservar al menos 2 estaciones."}, status=400)

    existing_by_id = {ls.id: ls for ls in LineStation.objects.filter(line=line)}
    existing_by_station = {}
    for ls in existing_by_id.values():
        existing_by_station.setdefault(ls.station_id, ls)

    station_ids = [int(item["station_id"]) for item in raw_stops if "station_id" in item]
    stations_map = {s.id: s for s in Station.objects.filter(id__in=station_ids)}
    if len(station_ids) < 2 or any(sid not in stations_map for sid in station_ids):
        return JsonResponse({"error": "Una o más estaciones del trayecto no existen."}, status=400)

    with transaction.atomic():
        LineStation.objects.filter(line=line).delete()
        new_rows = []
        cum_km = 0.0
        prev_st = None
        branch_counters = {}
        for item in raw_stops:
            sid = int(item["station_id"])
            st_obj = stations_map[sid]
            ref_ls = None
            if item.get("id") and int(item["id"]) in existing_by_id:
                ref_ls = existing_by_id[int(item["id"])]
            elif sid in existing_by_station:
                ref_ls = existing_by_station[sid]

            branch_val = str(item.get("branch") or (ref_ls.branch if ref_ls else "main"))
            if item.get("sequence") is not None:
                seq_val = int(item["sequence"])
            else:
                seq_val = branch_counters.get(branch_val, 0)
                branch_counters[branch_val] = seq_val + 1

            if prev_st is not None:
                dist_svg = ((st_obj.x - prev_st.x) ** 2 + (st_obj.y - prev_st.y) ** 2) ** 0.5
                cum_km += round(dist_svg / ESCALA_SVG_POR_KM, 3)
            prev_st = st_obj

            raw_wps = item.get("waypoints", ref_ls.waypoints if ref_ls else [])
            snap_enabled = bool(item.get("snap", payload.get("snap", False)))
            snap_step = float(item.get("snap_angle", payload.get("snap_angle", 45.0)))
            clean_wps = []
            anchor = [float(st_obj.x), float(st_obj.y)]
            for p in (raw_wps if isinstance(raw_wps, list) else []):
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    target = [float(p[0]), float(p[1])]
                    if snap_enabled:
                        snapped = snap_point_to_octilinear(anchor, target, step_deg=snap_step)
                        clean_wps.append([round(snapped[0], 1), round(snapped[1], 1)])
                        anchor = snapped
                    else:
                        clean_wps.append([round(target[0], 1), round(target[1], 1)])
                        anchor = target

            new_rows.append(
                LineStation(
                    line=line,
                    station=st_obj,
                    sequence=seq_val,
                    branch=branch_val,
                    segment_infrastructure=str(
                        item.get("segment_infrastructure")
                        or (ref_ls.segment_infrastructure if ref_ls else st_obj.infrastructure_type)
                    ),
                    segment_status=str(
                        item.get("segment_status")
                        or (ref_ls.segment_status if ref_ls else st_obj.operational_status)
                    ),
                    depth_meters=float(
                        item.get("depth_meters")
                        if item.get("depth_meters") is not None
                        else (ref_ls.depth_meters if ref_ls else st_obj.depth_meters)
                    ),
                    chainage_km=round(cum_km, 3),
                    curve_radius_m=float(ref_ls.curve_radius_m if ref_ls else line.min_curve_radius_m),
                    superelevation_deg=float(ref_ls.superelevation_deg if ref_ls else 0.0),
                    tangent_length_m=float(ref_ls.tangent_length_m if ref_ls else 180.0),
                    correspondences_text=ref_ls.correspondences_text if ref_ls else "",
                    notes=ref_ls.notes if ref_ls else "",
                    waypoints=clean_wps,
                )
            )
        LineStation.objects.bulk_create(new_rows)

        line.declared_stations_count = len(new_rows)
        line.operational_stations_count = sum(1 for r in new_rows if r.segment_status == "operational")
        first_name = stations_map[int(raw_stops[0]["station_id"])].name
        last_name = stations_map[int(raw_stops[-1]["station_id"])].name
        if not line.is_circular:
            line.route_title = f"{first_name} – {last_name}"
        line.is_custom_modified = True
        line.save(update_fields=["declared_stations_count", "operational_stations_count", "route_title", "is_custom_modified"])

        # Actualizar estaciones terminales optimizadamente (filtrando candidatos en lugar de las 828 estaciones)
        if "terminal_station_ids" in payload and isinstance(payload["terminal_station_ids"], list):
            desired_term_ids = {int(x) for x in payload["terminal_station_ids"]}
        else:
            desired_term_ids = (
                {int(raw_stops[0]["station_id"])}
                if line.is_circular
                else {int(raw_stops[0]["station_id"]), int(raw_stops[-1]["station_id"])}
            )

        candidate_terminals = list(Station.objects.filter(
            models.Q(id__in=desired_term_ids) | models.Q(is_terminal=True)
        ))
        modified_terminals = []
        for st_candidate in candidate_terminals:
            cur_list = list(st_candidate.terminal_lines or [])
            has_code = line.code in cur_list
            should_have = st_candidate.id in desired_term_ids
            if should_have and not has_code:
                cur_list.append(line.code)
                st_candidate.terminal_lines = cur_list
                st_candidate.is_terminal = True
                modified_terminals.append(st_candidate)
            elif not should_have and has_code:
                cur_list = [c for c in cur_list if c != line.code]
                st_candidate.terminal_lines = cur_list
                st_candidate.is_terminal = len(cur_list) > 0
                modified_terminals.append(st_candidate)
        if modified_terminals:
            Station.objects.bulk_update(modified_terminals, ["terminal_lines", "is_terminal"])

    export_user_network_layer()

    return JsonResponse(
        {
            "ok": True,
            "line_code": line.code,
            "stops_count": len(new_rows),
            "route_title": line.route_title,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_update_city_outline(request, outline_id):
    """Permite editar la forma de la ciudad (polígonos, nombre, elevación, color y vértices)."""
    outline = get_object_or_404(CityOutline, id=outline_id)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    if "name" in payload and payload["name"]:
        outline.name = str(payload["name"])
    if "color" in payload and payload["color"]:
        outline.color = str(payload["color"])
    if "opacity" in payload and payload["opacity"] is not None:
        outline.opacity = float(payload["opacity"])
    if "elevation_m" in payload and payload["elevation_m"] is not None:
        outline.elevation_m = float(payload["elevation_m"])
    if "polygon_points" in payload and isinstance(payload["polygon_points"], list):
        outline.polygon_points = payload["polygon_points"]

    outline.save()
    return JsonResponse({"ok": True, "outline_id": outline.id})


@csrf_exempt
@require_http_methods(["POST"])
def api_create_alert(request):
    """Crea una alerta manual en el Centro de Control Operativo (PCCO) y ajusta la línea."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    line = None
    if payload.get("line_code"):
        line = TransitLine.objects.filter(code=payload["line_code"]).first()
    station = None
    if payload.get("station_id"):
        station = Station.objects.filter(id=payload["station_id"]).first()

    alert = OperationalAlert.objects.create(
        title=payload.get("title", "Incidencia operativa reportada por PCCO"),
        description=payload.get("description", "Monitoreo en curso por brigadas de mando centralizado."),
        severity=payload.get("severity", "warning"),
        category=payload.get("category", "signaling"),
        line=line,
        station=station,
        speed_factor=float(payload.get("speed_factor", 0.75)),
        delay_seconds=int(payload.get("delay_seconds", 45)),
        is_active=True,
    )
    return JsonResponse({"ok": True, "alert_id": alert.id})


@csrf_exempt
@require_http_methods(["POST"])
def api_simulate_alert(request):
    """
    Genera y activa un incidente operativo realista del Plan Maestro SMyT
    para demostrar la respuesta en tiempo real del Centro de Control Operativo.
    """
    scenarios = [
        {
            "line_code": "1",
            "station_name": "Santa Mónica",
            "severity": "warning",
            "category": "crowding",
            "title": "Línea 1 (Nodo Santa Mónica): Despacho de 3 trenes en vacío por saturación de triple andén",
            "description": "Afluencia superior al 92% en la correspondencia 1/4/7/15/18. Se reduce intervalo a 75 s y se regulan accesos en torniquetes.",
            "speed_factor": 0.82,
            "delay_seconds": 30,
        },
        {
            "line_code": "7",
            "station_name": "Fórum Monarca",
            "severity": "warning",
            "category": "signaling",
            "title": "Línea 7 (Túnel Profundo -50 m): Reconfiguración de cantonamiento CBTC en Fórum Monarca",
            "description": "Conmutación automática a canal redundante de pilotaje en el tramo subterráneo profundo. Velocidad comercial limitada a 38 km/h.",
            "speed_factor": 0.68,
            "delay_seconds": 55,
        },
        {
            "line_code": "A",
            "station_name": "Aeropuerto Álvarez Morisset (Terminal 1-2)",
            "severity": "info",
            "category": "rolling_stock",
            "title": "Línea A (Circuito Periférico): Prioridad de vía para convoyes Expresos Premium en sector Sur",
            "description": "Sincronización de enclavamientos en los 6 andenes de Terminal Aérea Álvarez Morisset para garantizar frecuencia de 300 s.",
            "speed_factor": 0.95,
            "delay_seconds": 15,
        },
        {
            "line_code": "14",
            "station_name": "La Miel",
            "severity": "critical",
            "category": "power",
            "title": "Línea 14: Disparo momentáneo de disyuntor en Subestación Rectificadora 750 VCC (Tramo Elevado)",
            "description": "Restablecimiento por telecontrol desde PCCO en curso. Trenes circulan a marcha de seguridad sobre el viaducto elevado.",
            "speed_factor": 0.45,
            "delay_seconds": 110,
        },
        {
            "line_code": "8",
            "station_name": "Túnel Emisor",
            "severity": "warning",
            "category": "weather",
            "title": "Línea 8: Arranque de bombas N+2 en cárcamo de gran profundidad (-75 m) en Túnel Emisor",
            "description": "Caudal pluvial extraordinario en lumbreras del sector norte. Operación segura con supervisión de humedad en vía.",
            "speed_factor": 0.75,
            "delay_seconds": 40,
        },
        {
            "line_code": "S2",
            "station_name": "Río Tíber",
            "severity": "warning",
            "category": "signaling",
            "title": "Sistema 2 (Autobuses Articulados): Onda verde prioritaria activada en bifurcación 2A/2B Río Tíber",
            "description": "Ajuste de fase semafórica en carril confinado BRT para absorber demanda procedente de Línea 9.",
            "speed_factor": 0.80,
            "delay_seconds": 25,
        },
    ]

    chosen = random.choice(scenarios)
    line = TransitLine.objects.filter(code=chosen["line_code"]).first()
    station = Station.objects.filter(name__icontains=chosen["station_name"]).first()

    if line and chosen["category"] == "crowding":
        line.current_occupancy_pct = min(98, line.current_occupancy_pct + 12)
        line.save(update_fields=["current_occupancy_pct"])

    alert = OperationalAlert.objects.create(
        title=chosen["title"],
        description=chosen["description"],
        severity=chosen["severity"],
        category=chosen["category"],
        line=line,
        station=station,
        speed_factor=chosen["speed_factor"],
        delay_seconds=chosen["delay_seconds"],
        is_active=True,
    )
    return JsonResponse({"ok": True, "alert_id": alert.id, "title": alert.title})


@csrf_exempt
@require_http_methods(["POST"])
def api_toggle_alert(request, alert_id):
    """Alterna el estado activa/resuelta de una alerta en el PCCO."""
    alert = get_object_or_404(OperationalAlert, id=alert_id)
    alert.is_active = not alert.is_active
    if not alert.is_active:
        alert.severity = "resolved"
        alert.resolved_at = timezone.now()
    else:
        if alert.severity == "resolved":
            alert.severity = "warning"
        alert.resolved_at = None
    alert.save()
    return JsonResponse({"ok": True, "id": alert.id, "is_active": alert.is_active})


@csrf_exempt
@require_http_methods(["POST"])
def api_reset_network(request):
    """Restaura la cartografía y datos al estado maestro original de cartografia/red_metro.json."""
    result = seed_database(force_reset=True)
    return JsonResponse({"ok": True, "result": result})


@require_http_methods(["GET"])
def api_cartografia_json(request):
    """Sirve directamente el artefacto maestro validado cartografia/red_metro.json."""
    return JsonResponse(cargar_fuente_cartografica(), json_dumps_params={"ensure_ascii": False})


@require_http_methods(["GET"])
def api_cartografia_svg(request):
    """Sirve directamente el plano esquemático oficial cartografia/red_metro.svg."""
    return HttpResponse(RUTA_RED_SVG.read_text(encoding="utf-8"), content_type="image/svg+xml; charset=utf-8")


@require_http_methods(["GET"])
def api_cartografia_logo(request):
    """Sirve directamente el logotipo vectorial independiente cartografia/logo_metro.svg."""
    return HttpResponse(RUTA_LOGO_SVG.read_text(encoding="utf-8"), content_type="image/svg+xml; charset=utf-8")


# =============================================================================
# ENDPOINTS DEL EDITOR VISUAL DE RED (CREACIÓN, CONEXIÓN, TRANSFERENCIA Y PERSISTENCIA)
# =============================================================================

@csrf_exempt
@require_http_methods(["POST"])
def api_create_station(request):
    """
    1. AGREGAR ESTACIONES:
    Crea una nueva estación en el mapa esquemático:
    - Valida nombre obligatorio (status 400 si vacío).
    - Asigna o deduce coordenadas esquemáticas (x, y) y geográficas (lat, lng).
    - Parámetros de ingeniería civil y estado operativo.
    - Soporta estaciones huérfanas (sin línea asignada, lines=[]).
    - Asignación opcional a una o más líneas con actualización de secuencia.
    - Marca is_user_created=True.
    - Auto-persiste en la capa de edición de usuario.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    name = str(payload.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "El nombre de la estación es obligatorio."}, status=400)

    x = float(payload.get("x", 2120.0))
    y = float(payload.get("y", 1860.0))
    lat = float(payload.get("lat")) if payload.get("lat") is not None else None
    lng = float(payload.get("lng")) if payload.get("lng") is not None else None
    if lat is None or lng is None:
        lat, lng = xy_to_latlng(x, y)

    code = str(payload.get("code", "")).strip()
    if not code:
        code = f"estacion-u-{uuid.uuid4().hex[:8]}"
    elif Station.objects.filter(code=code).exists():
        code = f"{code}-{uuid.uuid4().hex[:4]}"

    infra = str(payload.get("infrastructure_type", "subterraneo")).strip()
    if infra not in dict(Station.INFRASTRUCTURE_CHOICES):
        infra = "subterraneo"

    status = str(payload.get("operational_status", "operational")).strip()
    if status not in dict(Station.STATUS_CHOICES):
        status = "operational"

    platform = str(payload.get("platform_type", "central")).strip()
    if platform not in dict(Station.PLATFORM_CHOICES):
        platform = "central"

    depth_m = float(payload.get("depth_meters", -10.0))
    platform_count = int(payload.get("platform_count", 2))
    has_psd = bool(payload.get("has_psd", True))
    icon_tags = [t for t in payload.get("icon_tags", []) if t in ALLOWED_ICON_TAGS]
    terminal_lines = [c for c in payload.get("terminal_lines", []) if TransitLine.objects.filter(code=c).exists()]

    station = Station.objects.create(
        code=code,
        name=name,
        x=round(x, 1),
        y=round(y, 1),
        lat=round(lat, 6),
        lng=round(lng, 6),
        infrastructure_type=infra,
        operational_status=status,
        depth_meters=depth_m,
        platform_type=platform,
        platform_count=platform_count,
        has_psd=has_psd,
        is_transfer=len(terminal_lines) > 1,
        is_terminal=len(terminal_lines) > 0,
        icon_tags=icon_tags,
        terminal_lines=terminal_lines,
        is_user_created=True,
        is_custom_modified=False,
    )

    # Asignación opcional a una o varias líneas (soporta 'lines', 'initial_line' o 'line_code')
    assigned_lines = []
    lines_input = payload.get("lines")
    if lines_input is None:
        init_l = payload.get("initial_line") or payload.get("line_code")
        lines_input = [init_l] if init_l else []
    if isinstance(lines_input, list):
        for line_code in lines_input:
            if not line_code:
                continue
            line_obj = TransitLine.objects.filter(code=str(line_code).strip().upper()).first()
            if not line_obj:
                line_obj = TransitLine.objects.filter(name__iexact=str(line_code).strip()).first()
            if line_obj:
                s1_id = payload.get("s1_id")
                s2_id = payload.get("s2_id")
                seq = None

                if s1_id and s2_id:
                    ls1 = LineStation.objects.filter(line=line_obj, station_id=s1_id).first()
                    ls2 = LineStation.objects.filter(line=line_obj, station_id=s2_id).first()
                    if ls1 and ls2:
                        min_seq = min(ls1.sequence, ls2.sequence)
                        seq = min_seq + 1
                        LineStation.objects.filter(line=line_obj, sequence__gte=seq).update(sequence=models.F("sequence") + 1)
                        ls1.waypoints = []
                        ls1.save(update_fields=["waypoints"])
                if seq is None:
                    # Detectar si (x, y) cae entre dos estaciones de esta línea
                    stops_in_order = list(LineStation.objects.filter(line=line_obj).select_related("station").order_by("sequence"))
                    for i in range(len(stops_in_order) - 1):
                        st_a = stops_in_order[i].station
                        st_b = stops_in_order[i + 1].station
                        dx = float(st_b.x) - float(st_a.x)
                        dy = float(st_b.y) - float(st_a.y)
                        len_sq = dx * dx + dy * dy
                        if len_sq == 0:
                            continue
                        t = ((x - float(st_a.x)) * dx + (y - float(st_a.y)) * dy) / len_sq
                        if -0.05 <= t <= 1.05:
                            t_clamped = max(0.0, min(1.0, t))
                            proj_x = float(st_a.x) + t_clamped * dx
                            proj_y = float(st_a.y) + t_clamped * dy
                            dist = ((x - proj_x) ** 2 + (y - proj_y) ** 2) ** 0.5
                            if dist <= 75.0:
                                ls1 = stops_in_order[i]
                                seq = ls1.sequence + 1
                                LineStation.objects.filter(line=line_obj, sequence__gte=seq).update(sequence=models.F("sequence") + 1)
                                ls1.waypoints = []
                                ls1.save(update_fields=["waypoints"])
                                break

                if seq is None:
                    last_seq = LineStation.objects.filter(line=line_obj, branch="main").order_by("-sequence").values_list("sequence", flat=True).first()
                    seq = (last_seq + 1) if last_seq is not None else 0

                # Una estación intermedia insertada nunca es terminal
                if station.is_terminal and not terminal_lines:
                    station.is_terminal = False
                    station.terminal_lines = []
                    station.save(update_fields=["is_terminal", "terminal_lines"])

                LineStation.objects.create(
                    line=line_obj,
                    station=station,
                    sequence=seq,
                    branch="main",
                    segment_infrastructure=station.infrastructure_type,
                    segment_status=station.operational_status,
                    depth_meters=station.depth_meters,
                    chainage_km=0.0,
                    waypoints=[],
                    correspondences_text="",
                )
                assigned_lines.append(line_obj.code)
                line_obj.declared_stations_count = LineStation.objects.filter(line=line_obj).count()
                line_obj.operational_stations_count = LineStation.objects.filter(line=line_obj, segment_status="operational").count()
                line_obj.is_custom_modified = True
                line_obj.save(update_fields=["declared_stations_count", "operational_stations_count", "is_custom_modified"])

    if assigned_lines:
        corr_text = "/".join(sorted(assigned_lines))
        LineStation.objects.filter(station=station).update(correspondences_text=corr_text)

    if len(assigned_lines) > 1:
        station.is_transfer = True
        station.save(update_fields=["is_transfer"])

    # Auto-persistencia en la capa de usuario
    export_user_network_layer()

    return JsonResponse({
        "ok": True,
        "station": {
            "id": station.id,
            "code": station.code,
            "name": station.name,
            "x": station.x,
            "y": station.y,
            "lat": station.lat,
            "lng": station.lng,
            "infrastructure_type": station.infrastructure_type,
            "operational_status": station.operational_status,
            "is_transfer": station.is_transfer,
            "is_terminal": station.is_terminal,
            "icon_tags": station.icon_tags,
            "terminal_lines": station.terminal_lines,
            "lines": assigned_lines,
            "is_user_created": True,
        }
    })


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_delete_station(request, station_id):
    """
    Elimina una estación de la red y desvincula de forma limpia sus tramos LineStation,
    re-secuenciando las líneas afectadas y persistiendo en la capa de usuario.
    """
    station = get_object_or_404(Station, id=station_id)
    station_name = station.name
    station_code = station.code
    st_id_val = station.id

    with transaction.atomic():
        affected_line_ids = list(LineStation.objects.filter(station=station).values_list("line_id", flat=True).distinct())
        LineStation.objects.filter(station=station).delete()

        for lid in affected_line_ids:
            line_obj = TransitLine.objects.filter(id=lid).first()
            if line_obj:
                main_ls = LineStation.objects.filter(line=line_obj, branch="main").order_by("sequence")
                for new_seq, row in enumerate(main_ls):
                    if row.sequence != new_seq:
                        row.sequence = new_seq
                        row.save(update_fields=["sequence"])
                line_obj.declared_stations_count = LineStation.objects.filter(line=line_obj).count()
                line_obj.operational_stations_count = LineStation.objects.filter(line=line_obj, segment_status="operational").count()
                line_obj.is_custom_modified = True
                line_obj.save(update_fields=["declared_stations_count", "operational_stations_count", "is_custom_modified"])

        station.delete()

    export_user_network_layer(deleted_station_code=station_code, deleted_station_id=st_id_val)
    return JsonResponse({
        "ok": True,
        "deleted": True,
        "deleted_id": station_id,
        "station_name": station_name
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_create_line(request):
    """
    4. AGREGAR LÍNEAS NUEVAS:
    Crea una nueva línea de metro o autobuses articulados:
    - Valida código obligatorio y único (status 400 si ya existe).
    - Valida nombre (status 400 si vacío) y color hexadecimal.
    - Soporta líneas en planificación sin paradas iniciales (0 estaciones).
    - Marca is_user_created=True.
    - Auto-persiste en la capa de edición de usuario.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    code = str(payload.get("code", "")).strip().upper()
    if not code:
        return JsonResponse({"error": "El código de línea es obligatorio."}, status=400)

    if TransitLine.objects.filter(code__iexact=code).exists():
        return JsonResponse({"error": f"El código de línea '{code}' ya existe en la red."}, status=400)

    name = str(payload.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "El nombre de la línea es obligatorio."}, status=400)

    color = str(payload.get("color", "#0052FF")).strip()
    if not color.startswith("#"):
        color = f"#{color}"

    net_type = str(payload.get("network_type", "metro")).strip()
    if net_type not in dict(TransitLine.NETWORK_TYPES):
        net_type = "metro"

    subtype = str(payload.get("line_subtype", "convencional")).strip()
    if subtype not in dict(TransitLine.SUBTYPES):
        subtype = "convencional" if net_type == "metro" else "bus_articulado"

    freq = int(payload.get("frequency_seconds", 180))
    speed = float(payload.get("max_speed_kmh", 50.0))
    length = float(payload.get("length_km", 0.0))

    line = TransitLine.objects.create(
        code=code,
        name=name,
        route_title=str(payload.get("route_title", f"{name} (En Planificación)")),
        direction_axis=str(payload.get("direction_axis", "Eje Urbano Metropolitano")),
        network_type=net_type,
        line_subtype=subtype,
        color=color,
        text_color=str(payload.get("text_color", "#FFFFFF")),
        length_km=length,
        total_track_km=round(length * 1.15, 2),
        declared_stations_count=0,
        operational_stations_count=0,
        status=str(payload.get("status", "operational")),
        frequency_seconds=freq,
        max_speed_kmh=speed,
        is_user_created=True,
        is_custom_modified=False,
    )

    # Si se especificaron estaciones iniciales en la creación
    initial_stations = payload.get("stations", [])
    if isinstance(initial_stations, list) and initial_stations:
        cum_km = 0.0
        prev_st = None
        for seq_idx, st_ref in enumerate(initial_stations):
            st_obj = None
            if isinstance(st_ref, int) or (isinstance(st_ref, str) and st_ref.isdigit()):
                st_obj = Station.objects.filter(id=int(st_ref)).first()
            elif isinstance(st_ref, str):
                st_obj = Station.objects.filter(code=st_ref).first()

            if st_obj:
                if prev_st:
                    dist_svg = ((st_obj.x - prev_st.x) ** 2 + (st_obj.y - prev_st.y) ** 2) ** 0.5
                    cum_km += round(dist_svg / ESCALA_SVG_POR_KM, 3)
                prev_st = st_obj

                LineStation.objects.create(
                    line=line,
                    station=st_obj,
                    sequence=seq_idx,
                    branch="main",
                    segment_infrastructure=st_obj.infrastructure_type,
                    segment_status=st_obj.operational_status,
                    depth_meters=st_obj.depth_meters,
                    chainage_km=round(cum_km, 3),
                    waypoints=[],
                    correspondences_text="",
                )
        line.declared_stations_count = LineStation.objects.filter(line=line).count()
        line.operational_stations_count = LineStation.objects.filter(line=line, segment_status="operational").count()
        line.save(update_fields=["declared_stations_count", "operational_stations_count", "length_km"])

    export_user_network_layer()

    return JsonResponse({
        "ok": True,
        "line": {
            "id": line.id,
            "code": line.code,
            "name": line.name,
            "route_title": line.route_title,
            "network_type": line.network_type,
            "line_subtype": line.line_subtype,
            "color": line.color,
            "text_color": line.text_color,
            "declared_stations_count": line.declared_stations_count,
            "is_user_created": True,
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_create_line_segment(request):
    """
    4. AGREGAR TRAMOS:
    Crea o enlaza un nuevo tramo directo entre dos estaciones en una línea dada:
    - Valida que la línea y ambas estaciones existan.
    - Valida from_station_id != to_station_id.
    - Control de duplicados: si ya existe una conexión directa contigua en esa línea,
      rechaza con status 400: "Ya existe un tramo directo entre estas estaciones en la línea".
    - Inserta la conexión con secuencia adecuada.
    - Auto-persiste en la capa de edición de usuario.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    line_code = str(payload.get("line_code", "")).strip()
    line = TransitLine.objects.filter(code=line_code).first()
    if not line:
        return JsonResponse({"error": f"La línea '{line_code}' no existe."}, status=400)

    s1_id = payload.get("from_station_id")
    s2_id = payload.get("to_station_id")
    if not s1_id or not s2_id:
        return JsonResponse({"error": "Se requieren 'from_station_id' y 'to_station_id'."}, status=400)

    try:
        s1_id = int(s1_id)
        s2_id = int(s2_id)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Los IDs de estación deben ser numéricos."}, status=400)

    if s1_id == s2_id:
        return JsonResponse({"error": "No se puede conectar una estación consigo misma."}, status=400)

    st1 = Station.objects.filter(id=s1_id).first()
    st2 = Station.objects.filter(id=s2_id).first()
    if not st1 or not st2:
        return JsonResponse({"error": "Una o ambas estaciones no existen en la red."}, status=400)

    # Validar restricción entre líneas: impedir conectar estaciones pertenecientes a otras líneas si no forman parte de esta línea
    st1_lines = set(LineStation.objects.filter(station=st1).values_list("line_id", flat=True))
    st2_lines = set(LineStation.objects.filter(station=st2).values_list("line_id", flat=True))

    auto_correspondence = payload.get("auto_correspondence", False)
    if not auto_correspondence:
        if st1_lines and line.id not in st1_lines:
            return JsonResponse({
                "error": f"La estación '{st1.name}' pertenece a otra línea y no a la Línea {line.code}. Para conectarla, incorpórala primero como correspondencia."
            }, status=400)

        if st2_lines and line.id not in st2_lines:
            return JsonResponse({
                "error": f"La estación '{st2.name}' pertenece a otra línea y no a la Línea {line.code}. Para conectarla, incorpórala primero como correspondencia."
            }, status=400)
    else:
        # En modo trazado directo interactivo estilo MetroMapMaker, incorporar automáticamente a la línea como correspondencia
        if st1_lines and line.id not in st1_lines:
            st1.is_transfer = True
            st1.save(update_fields=["is_transfer"])
        if st2_lines and line.id not in st2_lines:
            st2.is_transfer = True
            st2.save(update_fields=["is_transfer"])

    # Validar duplicados en la línea: verificar si ya existe un tramo directo contiguo entre st1 y st2 en la misma rama
    branches_stops = {}
    for ls_item in LineStation.objects.filter(line=line).order_by("sequence"):
        branches_stops.setdefault(ls_item.branch, []).append(ls_item)
    for b_stops in branches_stops.values():
        for idx in range(len(b_stops) - 1):
            pair = {b_stops[idx].station_id, b_stops[idx + 1].station_id}
            if {s1_id, s2_id} == pair:
                return JsonResponse({
                    "error": f"Ya existe un tramo directo entre las estaciones '{st1.name}' y '{st2.name}' en la Línea {line.code}."
                }, status=400)

    st1_ls = LineStation.objects.filter(line=line, station=st1).first()
    st2_ls = LineStation.objects.filter(line=line, station=st2).first()
    target_branch = st1_ls.branch if st1_ls else (st2_ls.branch if st2_ls else "main")

    # Calcular waypoints ortogonales automáticos (90° o 180°) si no se especificaron
    provided_wps = payload.get("waypoints")
    if provided_wps is not None and isinstance(provided_wps, list) and len(provided_wps) > 0:
        segment_wps = provided_wps
    else:
        dx = float(st2.x) - float(st1.x)
        dy = float(st2.y) - float(st1.y)
        if abs(dx) >= abs(dy):
            segment_wps = [] if abs(dy) < 0.5 else [[round(float(st2.x), 1), round(float(st1.y), 1)]]
        else:
            segment_wps = [] if abs(dx) < 0.5 else [[round(float(st1.x), 1), round(float(st2.y), 1)]]

    with transaction.atomic():
        def _shift_sequences_forward(target_seq, branch):
            for row in LineStation.objects.filter(line=line, branch=branch, sequence__gte=target_seq).order_by("-sequence"):
                row.sequence += 1
                row.save(update_fields=["sequence"])

        if not st1_ls and not st2_ls:
            last_seq = LineStation.objects.filter(line=line, branch=target_branch).order_by("-sequence").values_list("sequence", flat=True).first()
            seq = (last_seq + 1) if last_seq is not None else 0
            LineStation.objects.create(
                line=line, station=st1, sequence=seq, branch=target_branch,
                segment_infrastructure=st1.infrastructure_type, segment_status=st1.operational_status,
                depth_meters=st1.depth_meters, waypoints=[]
            )
            LineStation.objects.create(
                line=line, station=st2, sequence=seq + 1, branch=target_branch,
                segment_infrastructure=st2.infrastructure_type, segment_status=st2.operational_status,
                depth_meters=st2.depth_meters, waypoints=segment_wps
            )
        elif st1_ls and not st2_ls:
            last_seq = LineStation.objects.filter(line=line, branch=st1_ls.branch).order_by("-sequence").values_list("sequence", flat=True).first()
            if st1_ls.sequence == 0 and last_seq is not None and last_seq > 0:
                next_ls = LineStation.objects.filter(line=line, branch=st1_ls.branch, sequence=1).select_related("station").first()
                if next_ls:
                    d_before = math.hypot(float(st2.x) - float(st1.x), float(st2.y) - float(st1.y))
                    d_after = math.hypot(float(st2.x) - float(next_ls.station.x), float(st2.y) - float(next_ls.station.y))
                    insert_seq = 0 if d_before < d_after else 1
                else:
                    insert_seq = 1
            elif last_seq is not None and st1_ls.sequence == last_seq:
                insert_seq = last_seq + 1
            else:
                prev_ls = LineStation.objects.filter(line=line, branch=st1_ls.branch, sequence=st1_ls.sequence - 1).select_related("station").first()
                next_ls = LineStation.objects.filter(line=line, branch=st1_ls.branch, sequence=st1_ls.sequence + 1).select_related("station").first()
                detour_before = (
                    math.hypot(float(st2.x) - float(prev_ls.station.x), float(st2.y) - float(prev_ls.station.y)) +
                    math.hypot(float(st1.x) - float(st2.x), float(st1.y) - float(st2.y)) -
                    math.hypot(float(prev_ls.station.x) - float(st1.x), float(prev_ls.station.y) - float(st1.y))
                ) if prev_ls else 1e9
                detour_after = (
                    math.hypot(float(st2.x) - float(next_ls.station.x), float(st2.y) - float(next_ls.station.y)) +
                    math.hypot(float(st1.x) - float(st2.x), float(st1.y) - float(st2.y)) -
                    math.hypot(float(next_ls.station.x) - float(st1.x), float(next_ls.station.y) - float(st1.y))
                ) if next_ls else 1e9
                insert_seq = st1_ls.sequence if detour_before < detour_after else (st1_ls.sequence + 1)

            _shift_sequences_forward(insert_seq, st1_ls.branch)
            LineStation.objects.create(
                line=line, station=st2, sequence=insert_seq, branch=st1_ls.branch,
                segment_infrastructure=st2.infrastructure_type, segment_status=st2.operational_status,
                depth_meters=st2.depth_meters, waypoints=segment_wps
            )
        elif not st1_ls and st2_ls:
            last_seq = LineStation.objects.filter(line=line, branch=st2_ls.branch).order_by("-sequence").values_list("sequence", flat=True).first()
            if st2_ls.sequence == 0 and last_seq is not None and last_seq > 0:
                next_ls = LineStation.objects.filter(line=line, branch=st2_ls.branch, sequence=1).select_related("station").first()
                if next_ls:
                    d_before = math.hypot(float(st1.x) - float(st2.x), float(st1.y) - float(st2.y))
                    d_after = math.hypot(float(st1.x) - float(next_ls.station.x), float(st1.y) - float(next_ls.station.y))
                    insert_seq = 0 if d_before < d_after else 1
                else:
                    insert_seq = 1
            elif last_seq is not None and st2_ls.sequence == last_seq:
                insert_seq = last_seq + 1
            else:
                prev_ls = LineStation.objects.filter(line=line, branch=st2_ls.branch, sequence=st2_ls.sequence - 1).select_related("station").first()
                next_ls = LineStation.objects.filter(line=line, branch=st2_ls.branch, sequence=st2_ls.sequence + 1).select_related("station").first()
                detour_before = (
                    math.hypot(float(st1.x) - float(prev_ls.station.x), float(st1.y) - float(prev_ls.station.y)) +
                    math.hypot(float(st2.x) - float(st1.x), float(st2.y) - float(st1.y)) -
                    math.hypot(float(prev_ls.station.x) - float(st2.x), float(prev_ls.station.y) - float(st2.y))
                ) if prev_ls else 1e9
                detour_after = (
                    math.hypot(float(st1.x) - float(next_ls.station.x), float(st1.y) - float(next_ls.station.y)) +
                    math.hypot(float(st2.x) - float(st1.x), float(st2.y) - float(st1.y)) -
                    math.hypot(float(next_ls.station.x) - float(st2.x), float(next_ls.station.y) - float(st2.y))
                ) if next_ls else 1e9
                insert_seq = st2_ls.sequence if detour_before < detour_after else (st2_ls.sequence + 1)

            _shift_sequences_forward(insert_seq, st2_ls.branch)
            LineStation.objects.create(
                line=line, station=st1, sequence=insert_seq, branch=st2_ls.branch,
                segment_infrastructure=st1.infrastructure_type, segment_status=st1.operational_status,
                depth_meters=st1.depth_meters, waypoints=segment_wps
            )
        else:
            insert_seq = st1_ls.sequence + 1
            _shift_sequences_forward(insert_seq, st1_ls.branch)
            LineStation.objects.create(
                line=line, station=st2, sequence=insert_seq, branch=st1_ls.branch,
                segment_infrastructure=st2.infrastructure_type, segment_status=st2.operational_status,
                depth_meters=st2.depth_meters, waypoints=segment_wps
            )

        line.declared_stations_count = LineStation.objects.filter(line=line).count()
        line.operational_stations_count = LineStation.objects.filter(line=line, segment_status="operational").count()
        first_ls = LineStation.objects.filter(line=line, branch="main").order_by("sequence").first()
        last_ls = LineStation.objects.filter(line=line, branch="main").order_by("-sequence").first()
        if first_ls and last_ls and not line.is_circular:
            line.route_title = f"{first_ls.station.name} – {last_ls.station.name}"
        line.is_custom_modified = True
        line.save(update_fields=["declared_stations_count", "operational_stations_count", "route_title", "is_custom_modified"])

        # Sincronizar correspondencias y estado de transbordo en ambas estaciones
        for st in (st1, st2):
            served_lines = list(LineStation.objects.filter(station=st).values_list("line__code", flat=True).distinct())
            st.is_transfer = len(served_lines) > 1
            st.save(update_fields=["is_transfer"])
            corr_str = "/".join(sorted(served_lines))
            LineStation.objects.filter(station=st).update(correspondences_text=corr_str)

    export_user_network_layer()

    return JsonResponse({
        "ok": True,
        "line_code": line.code,
        "from_station": st1.name,
        "to_station": st2.name,
        "total_stops": line.declared_stations_count,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_create_correspondence(request):
    """
    2. AGREGAR CORRESPONDENCIAS:
    Conecta estaciones de distintas líneas como transbordos (nodo de transferencia):
    - Escenario 1: Conectar estación a una nueva línea (station_id, target_line_code).
    - Escenario 2: Enlazar dos estaciones como nodo de transferencia (station_id, station_id_2).
    - Validación intra-línea: si la estación ya pertenece a la línea destino,
      rechaza con status 400: "No se puede crear correspondencia entre la misma línea".
    - Marca is_transfer=True en las estaciones involucradas.
    - Sincroniza correspondences_text en LineStation.
    - Auto-persiste en la capa de edición de usuario.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    def find_station(val):
        if val is None or val == "":
            return None
        st_match = None
        try:
            st_match = Station.objects.filter(id=int(val)).first()
        except (ValueError, TypeError):
            pass
        if not st_match:
            st_match = Station.objects.filter(code=str(val).strip()).first()
        if not st_match:
            st_match = Station.objects.filter(name__iexact=str(val).strip()).first()
        if not st_match and " (" in str(val):
            clean_name = str(val).split(" (")[0].strip()
            st_match = Station.objects.filter(name__iexact=clean_name).first()
        return st_match

    def find_line(val):
        if not val:
            return None
        v_str = str(val).strip()
        ln_match = TransitLine.objects.filter(code=v_str.upper()).first()
        if not ln_match:
            try:
                ln_match = TransitLine.objects.filter(id=int(v_str)).first()
            except (ValueError, TypeError):
                pass
        if not ln_match:
            for prefix in ["Línea ", "Linea ", "Line ", "L"]:
                if v_str.lower().startswith(prefix.lower()):
                    candidate = v_str[len(prefix):].strip().upper()
                    ln_match = TransitLine.objects.filter(code=candidate).first()
                    if ln_match:
                        break
        if not ln_match:
            ln_match = TransitLine.objects.filter(name__iexact=v_str).first()
        return ln_match

    raw_s1 = payload.get("station_id") or payload.get("station_id_1") or payload.get("station1")
    raw_s2 = payload.get("station_id_2") or payload.get("station2")
    raw_line = payload.get("target_line_code") or payload.get("line_code") or payload.get("target_line")
    action = payload.get("action", "").lower().strip()

    if action in ["remove", "delete"]:
        st = find_station(raw_s1)
        if not st:
            return JsonResponse({"error": "La estación no existe."}, status=400)
        target_line = find_line(raw_line)
        if not target_line:
            return JsonResponse({"error": f"La línea '{raw_line}' no existe."}, status=400)

        ls_qs = LineStation.objects.filter(line=target_line, station=st)
        if not ls_qs.exists():
            return JsonResponse({"error": f"La estación '{st.name}' no pertenece a la Línea {target_line.code}."}, status=400)

        try:
            with transaction.atomic():
                ls_qs.delete()
                # Renumerar de forma consistente las secuencias de todas las ramas de la línea
                branches = set(LineStation.objects.filter(line=target_line).values_list("branch", flat=True))
                for b_name in branches:
                    branch_stops = list(LineStation.objects.filter(line=target_line, branch=b_name).order_by("sequence"))
                    for new_seq, ls_item in enumerate(branch_stops):
                        if ls_item.sequence != new_seq:
                            ls_item.sequence = new_seq
                            ls_item.save(update_fields=["sequence"])

                target_line.declared_stations_count = LineStation.objects.filter(line=target_line).count()
                target_line.operational_stations_count = LineStation.objects.filter(line=target_line, segment_status="operational").count()
                first_ls = LineStation.objects.filter(line=target_line, branch="main").order_by("sequence").first()
                last_ls = LineStation.objects.filter(line=target_line, branch="main").order_by("-sequence").first()
                if first_ls and last_ls and not target_line.is_circular:
                    target_line.route_title = f"{first_ls.station.name} – {last_ls.station.name}"
                target_line.is_custom_modified = True
                target_line.save(update_fields=["declared_stations_count", "operational_stations_count", "route_title", "is_custom_modified"])

                served_count = LineStation.objects.filter(station=st).count()
                if served_count <= 1:
                    st.is_transfer = False
                cur_terms = list(st.terminal_lines or [])
                if target_line.code in cur_terms:
                    st.terminal_lines = [c for c in cur_terms if c != target_line.code]
                    st.is_terminal = len(st.terminal_lines) > 0
                st.is_custom_modified = True
                st.save(update_fields=["is_transfer", "is_terminal", "terminal_lines", "is_custom_modified"])

                served_codes = list(LineStation.objects.filter(station=st).values_list("line__code", flat=True).distinct())
                corr_text = "/".join(sorted(served_codes))
                LineStation.objects.filter(station=st).update(correspondences_text=corr_text)

            export_user_network_layer()
            return JsonResponse({
                "ok": True,
                "removed": True,
                "station_id": st.id,
                "station_name": st.name,
                "line_code": target_line.code,
                "served_lines": sorted(served_codes),
            })
        except Exception as exc:
            return JsonResponse({"error": f"Error al desconectar correspondencia: {str(exc)}"}, status=500)

    MAX_CORRESPONDENCES_PER_STATION = 10

    raw_lines_input = (
        payload.get("target_line_codes")
        or payload.get("target_lines")
        or payload.get("lines")
        or payload.get("target_line_code")
        or payload.get("line_code")
        or payload.get("target_line")
    )

    if raw_s1 and raw_lines_input:
        st = find_station(raw_s1)
        if not st:
            return JsonResponse({"error": "La estación no existe."}, status=400)

        if isinstance(raw_lines_input, list):
            lines_list = raw_lines_input
        elif isinstance(raw_lines_input, str) and "," in raw_lines_input:
            lines_list = [c.strip() for c in raw_lines_input.split(",") if c.strip()]
        else:
            lines_list = [raw_lines_input]

        seen_codes = set()
        clean_lines = []
        for x in lines_list:
            if x is not None:
                val = str(x).strip()
                if val and val not in seen_codes:
                    seen_codes.add(val)
                    clean_lines.append(val)

        if not clean_lines:
            return JsonResponse({"error": "Debes especificar al menos una línea válida para la correspondencia."}, status=400)

        current_line_ids = set(LineStation.objects.filter(station=st).values_list("line_id", flat=True))
        current_count = len(current_line_ids)

        if current_count >= MAX_CORRESPONDENCES_PER_STATION:
            return JsonResponse({
                "error": f"Límite alcanzado: La estación '{st.name}' ya cuenta con el máximo permitido de {MAX_CORRESPONDENCES_PER_STATION} correspondencias/líneas operativas."
            }, status=400)

        valid_target_lines = []
        already_operating_codes = []
        for l_item in clean_lines:
            target_line = find_line(l_item)
            if not target_line:
                return JsonResponse({"error": f"La línea '{l_item}' no existe."}, status=400)
            if target_line.id in current_line_ids or target_line in valid_target_lines:
                already_operating_codes.append(target_line.code)
            else:
                valid_target_lines.append(target_line)

        if not valid_target_lines:
            if len(already_operating_codes) == 1:
                return JsonResponse({
                    "error": f"No se puede crear correspondencia entre la misma línea: '{st.name}' ya forma parte de la Línea {already_operating_codes[0]}."
                }, status=400)
            else:
                return JsonResponse({
                    "error": f"No se puede crear correspondencia: '{st.name}' ya forma parte de las líneas seleccionadas ({', '.join(already_operating_codes)})."
                }, status=400)

        if current_count + len(valid_target_lines) > MAX_CORRESPONDENCES_PER_STATION:
            disponibles = MAX_CORRESPONDENCES_PER_STATION - current_count
            return JsonResponse({
                "error": f"Límite excedido: una estación puede tener como máximo {MAX_CORRESPONDENCES_PER_STATION} correspondencias. '{st.name}' cuenta con {current_count} líneas activas y solo puede agregar hasta {disponibles} más (intentando agregar {len(valid_target_lines)})."
            }, status=400)

        with transaction.atomic():
            for target_line in valid_target_lines:
                last_seq = LineStation.objects.filter(line=target_line, branch="main").order_by("-sequence").values_list("sequence", flat=True).first()
                seq = (last_seq + 1) if last_seq is not None else 0

                LineStation.objects.create(
                    line=target_line,
                    station=st,
                    sequence=seq,
                    branch="main",
                    segment_infrastructure=st.infrastructure_type,
                    segment_status=st.operational_status,
                    depth_meters=st.depth_meters,
                    chainage_km=0.0,
                    waypoints=[],
                    correspondences_text="",
                )

                target_line.declared_stations_count = LineStation.objects.filter(line=target_line).count()
                target_line.operational_stations_count = LineStation.objects.filter(line=target_line, segment_status="operational").count()
                target_line.is_custom_modified = True
                target_line.save(update_fields=["declared_stations_count", "operational_stations_count", "is_custom_modified"])

            st.is_transfer = True
            st.is_custom_modified = True
            st.save(update_fields=["is_transfer", "is_custom_modified"])

            served_codes = list(LineStation.objects.filter(station=st).values_list("line__code", flat=True).distinct())
            corr_text = "/".join(sorted(served_codes))
            LineStation.objects.filter(station=st).update(correspondences_text=corr_text)

        export_user_network_layer()
        return JsonResponse({
            "ok": True,
            "station_id": st.id,
            "station_name": st.name,
            "is_transfer": True,
            "line_code": valid_target_lines[0].code if len(valid_target_lines) == 1 else None,
            "added_lines": [l.code for l in valid_target_lines],
            "served_lines": sorted(served_codes),
            "total_lines_count": len(served_codes),
        })

    elif raw_s1 and raw_s2:
        st1 = find_station(raw_s1)
        st2 = find_station(raw_s2)
        if not st1 or not st2:
            return JsonResponse({"error": "Una o ambas estaciones no existen."}, status=400)

        if st1.id == st2.id:
            return JsonResponse({"error": "No se puede crear correspondencia de una estación consigo misma."}, status=400)

        lines_st1 = set(LineStation.objects.filter(station=st1).values_list("line__code", flat=True))
        lines_st2 = set(LineStation.objects.filter(station=st2).values_list("line__code", flat=True))

        if lines_st1 and lines_st1 == lines_st2 and len(lines_st1) == 1:
            return JsonResponse({
                "error": "No se puede crear correspondencia entre la misma línea: ambas estaciones pertenecen únicamente a la misma línea."
            }, status=400)

        all_lines = sorted(list(lines_st1.union(lines_st2)))
        if len(all_lines) > MAX_CORRESPONDENCES_PER_STATION:
            return JsonResponse({
                "error": f"Límite excedido: La unión de correspondencias generaría {len(all_lines)} líneas (el máximo permitido por estación es {MAX_CORRESPONDENCES_PER_STATION})."
            }, status=400)

        with transaction.atomic():
            st1.is_transfer = True
            st2.is_transfer = True
            st1.is_custom_modified = True
            st2.is_custom_modified = True

            # Reciprocidad en terminal_lines entre estaciones vinculadas por correspondencia
            valid_line_codes = set(TransitLine.objects.values_list("code", flat=True))
            combined_terminals = sorted([c for c in set(st1.terminal_lines or []).union(set(st2.terminal_lines or [])) if c in valid_line_codes])
            if combined_terminals:
                st1.terminal_lines = combined_terminals
                st2.terminal_lines = combined_terminals
                st1.is_terminal = True
                st2.is_terminal = True

            st1.save(update_fields=["is_transfer", "is_custom_modified", "terminal_lines", "is_terminal"])
            st2.save(update_fields=["is_transfer", "is_custom_modified", "terminal_lines", "is_terminal"])

            all_lines = sorted(list(lines_st1.union(lines_st2)))
            corr_text = "/".join(all_lines)
            LineStation.objects.filter(station__in=[st1, st2]).update(correspondences_text=corr_text)

        corridor_data = None
        dist_px = math.hypot(st1.x - st2.x, st1.y - st2.y)
        if dist_px >= 10.0:
            dist_m = max(30.0, round(dist_px * 18.5, 1))
            walk_min = max(1, round(dist_m / 75.0))
            corr_id = f"corridor-{min(st1.id, st2.id)}-{max(st1.id, st2.id)}"
            corridor_data = {
                "id": corr_id,
                "station1_id": st1.id,
                "station2_id": st2.id,
                "station1_name": st1.name,
                "station2_name": st2.name,
                "distance_m": dist_m,
                "walking_minutes": walk_min,
                "waypoints": [],
            }
            ex_corrs = [c for c in get_cached_transfer_corridors() if c.get("id") != corr_id]
            ex_corrs.append(corridor_data)
            set_cached_transfer_corridors(ex_corrs)

        export_user_network_layer()

        return JsonResponse({
            "ok": True,
            "station_1": st1.name,
            "station_2": st2.name,
            "is_transfer": True,
            "combined_lines": all_lines,
            "corridor": corridor_data,
        })

    return JsonResponse({"error": "Parámetros insuficientes para crear correspondencia."}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def api_save_user_edits(request):
    """
    5. PERSISTENCIA DE CAMBIOS:
    Persiste de forma explícita el estado actual de la red editada en
    UserNetworkEditLayer (SQLite) y en cartografia/user_network_edits.json.
    """
    result = export_user_network_layer()
    return JsonResponse({"ok": True, "result": result})


@csrf_exempt
@require_http_methods(["POST"])
def api_discard_user_edits(request):
    """
    Restaura la cartografía al Plan Maestro original de cartografia/red_metro.json.
    """
    result = seed_database(force_reset=True)
    return JsonResponse({"ok": True, "result": result})


@require_http_methods(["GET"])
def api_editor_status(request):
    """
    Devuelve métricas e información del estado de la capa de usuario.
    """
    layer = UserNetworkEditLayer.objects.filter(is_active=True).first()
    return JsonResponse({
        "has_user_layer": layer is not None,
        "user_stations_count": Station.objects.filter(is_user_created=True).count(),
        "user_lines_count": TransitLine.objects.filter(is_user_created=True).count(),
        "modified_stations_count": Station.objects.filter(is_custom_modified=True).count(),
        "modified_lines_count": TransitLine.objects.filter(is_custom_modified=True).count(),
        "last_updated": layer.updated_at.strftime("%Y-%m-%d %H:%M:%S") if layer and layer.updated_at else None,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_create_transfer_corridor(request):
    """
    Crea un pasillo de correspondencia peatonal entre dos estaciones distantes.
    Enlaza transbordo, calcula distancia métrica y persiste en UserNetworkEditLayer.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    st1_id = payload.get("station_id") or payload.get("station_id_1") or payload.get("station1_id")
    st2_id = payload.get("station_id_2") or payload.get("station2_id")
    waypoints = payload.get("waypoints", [])

    if not st1_id or not st2_id:
        return JsonResponse({"error": "Se requieren ambas estaciones (station_id y station_id_2)"}, status=400)

    st1 = Station.objects.filter(id=int(st1_id)).first()
    st2 = Station.objects.filter(id=int(st2_id)).first()
    if not st1 or not st2:
        return JsonResponse({"error": "Una o ambas estaciones no existen."}, status=400)

    if st1.id == st2.id:
        return JsonResponse({"error": "No se puede tender un pasillo consigo misma."}, status=400)

    # Asegurar correspondencia entre ambas
    st1.is_transfer = True
    st2.is_transfer = True
    st1.is_custom_modified = True
    st2.is_custom_modified = True
    st1.save(update_fields=["is_transfer", "is_custom_modified"])
    st2.save(update_fields=["is_transfer", "is_custom_modified"])

    lines_st1 = set(LineStation.objects.filter(station=st1).values_list("line__code", flat=True))
    lines_st2 = set(LineStation.objects.filter(station=st2).values_list("line__code", flat=True))
    all_lines = sorted(list(lines_st1.union(lines_st2)))
    corr_text = "/".join(all_lines)
    LineStation.objects.filter(station__in=[st1, st2]).update(correspondences_text=corr_text)

    dist_px = math.hypot(st1.x - st2.x, st1.y - st2.y)
    dist_m = max(30.0, round(dist_px * 18.5, 1))
    walk_min = max(1, round(dist_m / 75.0))
    corr_id = f"corridor-{min(st1.id, st2.id)}-{max(st1.id, st2.id)}"

    corridor_data = {
        "id": corr_id,
        "station1_id": st1.id,
        "station2_id": st2.id,
        "station1_name": st1.name,
        "station2_name": st2.name,
        "distance_m": dist_m,
        "walking_minutes": walk_min,
        "waypoints": waypoints,
    }

    ex_corrs = [c for c in get_cached_transfer_corridors() if c.get("id") != corr_id]
    ex_corrs.append(corridor_data)
    set_cached_transfer_corridors(ex_corrs)

    export_user_network_layer()
    return JsonResponse({
        "ok": True,
        "corridor": corridor_data,
        "combined_lines": all_lines,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_delete_transfer_corridor(request):
    """
    Elimina un pasillo de correspondencia peatonal.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    corr_id = payload.get("corridor_id") or payload.get("id")
    st1_id = payload.get("station_id") or payload.get("station_id_1")
    st2_id = payload.get("station_id_2")

    ex_corrs = get_cached_transfer_corridors()
    if corr_id:
        ex_corrs = [c for c in ex_corrs if c.get("id") != corr_id]
    elif st1_id and st2_id:
        sid1, sid2 = int(st1_id), int(st2_id)
        target_id = f"corridor-{min(sid1, sid2)}-{max(sid1, sid2)}"
        ex_corrs = [c for c in ex_corrs if c.get("id") != target_id]
    set_cached_transfer_corridors(ex_corrs)

    export_user_network_layer()
    return JsonResponse({"ok": True, "deleted": True})
