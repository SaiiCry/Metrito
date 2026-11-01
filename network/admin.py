from django.contrib import admin
from .models import CityOutline, TransitLine, Station, LineStation, OperationalAlert


@admin.register(CityOutline)
class CityOutlineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "zone_type", "elevation_m", "color")


@admin.register(TransitLine)
class TransitLineAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "route_title",
        "network_type",
        "line_subtype",
        "length_km",
        "declared_stations_count",
        "operational_stations_count",
        "frequency_seconds",
        "status",
    )
    list_filter = ("network_type", "line_subtype", "status")
    search_fields = ("code", "name", "route_title")


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "infrastructure_type",
        "operational_status",
        "depth_meters",
        "platform_type",
        "is_transfer",
        "is_premium_stop",
    )
    list_filter = ("infrastructure_type", "operational_status", "platform_type", "is_transfer", "is_premium_stop")
    search_fields = ("name", "code")


@admin.register(LineStation)
class LineStationAdmin(admin.ModelAdmin):
    list_display = (
        "line",
        "sequence",
        "branch",
        "station",
        "segment_infrastructure",
        "segment_status",
        "chainage_km",
        "curve_radius_m",
    )
    list_filter = ("line", "segment_infrastructure", "segment_status", "branch")


@admin.register(OperationalAlert)
class OperationalAlertAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "category", "line", "station", "is_active", "created_at")
    list_filter = ("severity", "category", "is_active")
