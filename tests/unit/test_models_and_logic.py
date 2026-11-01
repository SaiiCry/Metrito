"""
Pruebas Unitarias de Modelos, Restricciones de Integridad y Lógica de Negocio Pura.
No dependen de llamadas HTTP y verifican las reglas fundamentales a nivel de ORM.
"""

import pytest
from django.db import IntegrityError
from network.models import Station, TransitLine, LineStation, CityOutline, OperationalAlert, UserNetworkEditLayer
from network.seed import xy_to_latlng, ORIGEN_SVG_X, ORIGEN_SVG_Y, LAT_ORIGEN, LON_ORIGEN


@pytest.mark.unit
class TestStationModel:
    """Verifica el comportamiento unitario del modelo Station."""

    def test_station_creation_with_defaults(self, db):
        """Verifica que una estación se cree con todos los campos por defecto especificados en el modelo."""
        station = Station.objects.create(code="st-default", name="Estación Defecto")
        assert station.code == "st-default"
        assert station.name == "Estación Defecto"
        assert station.x == 6000.0
        assert station.y == 2000.0
        assert station.lat == 19.4326
        assert station.lng == -99.1332
        assert station.infrastructure_type == "subterraneo"
        assert station.operational_status == "operational"
        assert station.platform_type == "lateral"
        assert station.platform_count == 2
        assert station.has_psd is True
        assert station.is_transfer is False
        assert station.is_terminal is False
        assert station.icon_tags == []
        assert station.terminal_lines == []
        assert station.is_user_created is False
        assert station.is_custom_modified is False
        assert str(station) == "Estación Defecto"

    def test_station_code_uniqueness_enforced(self, db):
        """Verifica que el ORM/base de datos imponga unicidad estricta en Station.code."""
        Station.objects.create(code="unique-code-1", name="Estación 1")
        with pytest.raises(IntegrityError):
            Station.objects.create(code="unique-code-1", name="Estación 2 Duplicada")

    def test_station_string_representation(self, db):
        """Verifica que __str__ devuelva el nombre exacto de la estación."""
        station = Station.objects.create(code="st-str", name="Pino Suárez Central")
        assert str(station) == "Pino Suárez Central"


@pytest.mark.unit
class TestTransitLineModel:
    """Verifica el comportamiento unitario del modelo TransitLine."""

    def test_transit_line_creation_and_defaults(self, db):
        """Verifica que una línea se cree con los valores por defecto y tipos adecuados."""
        line = TransitLine.objects.create(
            code="L100",
            name="Línea 100 Centenario",
            route_title="Norte – Sur",
        )
        assert line.code == "L100"
        assert line.network_type == "metro"
        assert line.line_subtype == "convencional"
        assert line.color == "#0052ff"
        assert line.declared_stations_count == 20
        assert line.operational_stations_count == 20
        assert line.status == "operational"
        assert line.frequency_seconds == 180
        assert line.custom_geometry == {}
        assert line.is_user_created is False
        assert line.is_custom_modified is False
        assert str(line) == "Línea 100 Centenario: Norte – Sur"

    def test_transit_line_code_uniqueness_enforced(self, db):
        """Verifica que el código de línea sea estrictamente único."""
        TransitLine.objects.create(code="DUP", name="Línea Original", route_title="A – B")
        with pytest.raises(IntegrityError):
            TransitLine.objects.create(code="DUP", name="Línea Duplicada", route_title="C – D")


@pytest.mark.unit
class TestLineStationModel:
    """Verifica el comportamiento unitario y las restricciones relacionales de LineStation."""

    def test_line_station_unique_together_constraint(self, db, line_factory, station_factory):
        """
        Verifica la restricción unique_together = [('line', 'branch', 'sequence')].
        No se permite duplicar la misma secuencia en la misma rama de una línea.
        """
        line = line_factory(code="L-TEST")
        st1 = station_factory(code="st-ls-1")
        st2 = station_factory(code="st-ls-2")

        LineStation.objects.create(line=line, station=st1, sequence=0, branch="main")

        with pytest.raises(IntegrityError):
            LineStation.objects.create(line=line, station=st2, sequence=0, branch="main")

    def test_line_station_cascade_deletion(self, db, line_factory, station_factory):
        """Verifica que al eliminar una línea o estación se elimine el registro LineStation asociado."""
        line = line_factory(code="L-CASCADE")
        st = station_factory(code="st-cascade")
        ls = LineStation.objects.create(line=line, station=st, sequence=0, branch="main")

        assert LineStation.objects.filter(id=ls.id).exists()

        line.delete()
        assert not LineStation.objects.filter(id=ls.id).exists()
        assert Station.objects.filter(id=st.id).exists()

    def test_line_station_string_representation(self, db, line_factory, station_factory):
        """Verifica el formato del string representation: '{line.code} [{sequence}] {station.name}'."""
        line = line_factory(code="1")
        st = station_factory(code="st-str-check", name="Balderas")
        ls = LineStation.objects.create(line=line, station=st, sequence=5, branch="main")

        assert str(ls) == "1 [5] Balderas"


@pytest.mark.unit
class TestCityOutlineAndUserLayerModels:
    """Verifica modelos auxiliares de polígonos urbanos y capa persistente de usuario."""

    def test_city_outline_creation_and_defaults(self, db):
        """Verifica creación de polígono urbano y unicidad de código."""
        outline = CityOutline.objects.create(
            code="zona-centro",
            name="Centro Histórico",
            zone_type="urban_core",
            polygon_points=[[100, 200], [300, 400]],
        )
        assert outline.elevation_m == 2240.0
        assert str(outline) == "Centro Histórico (urban_core)"

        with pytest.raises(IntegrityError):
            CityOutline.objects.create(code="zona-centro", name="Zona duplicada")

    def test_user_network_edit_layer_model(self, db):
        """Verifica almacenamiento de deltas serializados en UserNetworkEditLayer."""
        layer = UserNetworkEditLayer.objects.create(
            name="layer_test",
            data={"created_stations": ["st1"], "version": 1},
            is_active=True,
        )
        assert layer.version == 1
        assert layer.is_active is True
        assert layer.data["created_stations"] == ["st1"]
        assert "layer_test v1" in str(layer)

    def test_operational_alert_model(self, db, line_factory):
        """Verifica creación y string format de alertas operativas."""
        line = line_factory(code="L-ALERT")
        alert = OperationalAlert.objects.create(
            title="Falla de señalización",
            description="Demoras de 5 minutos",
            severity="warning",
            line=line,
        )
        assert alert.is_active is True
        assert alert.speed_factor == 1.0
        assert str(alert) == "[WARNING] Falla de señalización"


@pytest.mark.unit
class TestGeographicConversionLogic:
    """Verifica la función pura xy_to_latlng."""

    def test_origin_mapping(self):
        """El punto origen SVG debe mapear exactamente a las coordenadas geográficas de origen."""
        lat, lng = xy_to_latlng(ORIGEN_SVG_X, ORIGEN_SVG_Y)
        assert round(lat, 4) == round(LAT_ORIGEN, 4)
        assert round(lng, 4) == round(LON_ORIGEN, 4)

    def test_positive_displacement(self):
        """Desplazamientos positivos en X deben incrementar la longitud; positivos en Y deben decrementar la latitud."""
        lat_base, lng_base = xy_to_latlng(ORIGEN_SVG_X, ORIGEN_SVG_Y)
        lat_offset, lng_offset = xy_to_latlng(ORIGEN_SVG_X + 540.0, ORIGEN_SVG_Y + 540.0)

        assert lng_offset > lng_base
        assert lat_offset < lat_base
