"""
Pruebas de Validación de los Nuevos Fixtures del Editor de Trazado.
Verifica que las entidades generadas por conftest.py cumplan estrictamente
con models.py y todas las reglas de negocio (ejecutables con pytest -k integridad):
1. Unicidad de Station.code y TransitLine.code.
2. Restricción unique_together = [('line', 'branch', 'sequence')] sin huecos ni duplicados.
3. Coherencia de is_transfer con las líneas asignadas y reciprocidad en terminal_lines.
4. Validez estricta de icon_tags (solo aeropuerto, parque, terminal, centro_modal, zona_cultural, escuela).
5. Modalidades metro y bus_articulado con display_order sin colisiones.
6. Coexistencia pacífica con seeded_network (828 estaciones y 34 líneas).
"""

import pytest
from network.models import Station, TransitLine, LineStation
from tests.conftest import ALLOWED_ICON_TAGS


@pytest.mark.unit
class TestEditorFixturesIntegridad:
    """Suite de validación de integridad de datos y modelos del editor de trazado."""

    def test_integridad_codigos_unicos(self, editor_network):
        """Verifica que todos los códigos de estación y línea generados sean estrictamente únicos."""
        line_codes = list(TransitLine.objects.values_list("code", flat=True))
        station_codes = list(Station.objects.values_list("code", flat=True))

        assert len(line_codes) == len(set(line_codes)), "Existen códigos duplicados en TransitLine"
        assert len(station_codes) == len(set(station_codes)), "Existen códigos duplicados en Station"

        assert editor_network["line_metro"].code != editor_network["line_brt"].code

    def test_integridad_unique_together_secuencias(self, editor_network):
        """
        Verifica que dentro de cada combinación (línea, rama) los LineStation
        cumplan unique_together, comiencen en secuencia 0 y sean estrictamente consecutivos.
        """
        by_line_and_branch = editor_network["by_line_and_branch"]

        for line_code, branches in by_line_and_branch.items():
            for branch_name, stops in branches.items():
                assert len(stops) >= 2, f"La rama {branch_name} de {line_code} debe tener al menos 2 paradas"
                sequences = [ls.sequence for ls in stops]

                # Sin duplicados
                assert len(sequences) == len(set(sequences)), f"Secuencias duplicadas en {line_code} / {branch_name}"

                # Ordenados comenzando en 0
                expected_sequences = list(range(len(stops)))
                assert sequences == expected_sequences, (
                    f"Secuencias no consecutivas en {line_code} / {branch_name}: {sequences} != {expected_sequences}"
                )

                # Verificar en base de datos la restricción unique_together
                db_stops = list(
                    LineStation.objects.filter(line__code=line_code, branch=branch_name).order_by("sequence")
                )
                assert [ls.sequence for ls in db_stops] == expected_sequences

    def test_integridad_coherencia_is_transfer_y_correspondencias(self, editor_network):
        """
        Verifica la coherencia de is_transfer con las líneas asignadas y
        la reciprocidad de correspondencias combinadas:
        - Metro con Metro
        - Metro con Autobús Articulado (BRT)
        - Estaciones con tres o más líneas (Metro 1 + Metro 2 + BRT)
        """
        existing_line_codes = set(TransitLine.objects.values_list("code", flat=True))

        for st in editor_network["all_stations"]:
            connected_lines = set(
                LineStation.objects.filter(station=st).values_list("line__code", flat=True)
            )
            if len(connected_lines) > 1:
                assert st.is_transfer is True, f"Estación {st.name} sirve a {connected_lines} pero tiene is_transfer=False"
                for code in connected_lines:
                    assert code in st.terminal_lines, (
                        f"Estación {st.name} sirve a {code} pero no aparece en sus terminal_lines"
                    )
            elif len(connected_lines) == 1 and not st.is_terminal:
                # Estación normal no transbordo
                assert st.is_transfer is False

        # Verificar correspondencias específicas requeridas
        st_mm = editor_network["transfer_metro_metro"]
        st_mbrt = editor_network["transfer_metro_brt"]
        st_triple = editor_network["transfer_triple"]

        assert st_mm.is_transfer is True
        assert editor_network["line_metro"].code in st_mm.terminal_lines
        if editor_network.get("line_metro_2"):
            assert editor_network["line_metro_2"].code in st_mm.terminal_lines

        assert st_mbrt.is_transfer is True
        assert editor_network["line_metro"].code in st_mbrt.terminal_lines
        assert editor_network["line_brt"].code in st_mbrt.terminal_lines

        assert st_triple.is_transfer is True
        assert len(st_triple.terminal_lines) >= 3

        # Validez de todos los códigos en terminal_lines
        for code in st_triple.terminal_lines:
            assert code in existing_line_codes

    def test_integridad_icon_tags_permitidos(self, editor_network):
        """
        Verifica que todas las estaciones creadas por el fixture tengan únicamente
        icon_tags reconocidos y permitidos por models.py.
        """
        allowed_tags_set = set(ALLOWED_ICON_TAGS)
        found_tags = set()

        for st in editor_network["all_stations"]:
            assert isinstance(st.icon_tags, list)
            for tag in st.icon_tags:
                assert tag in allowed_tags_set, f"Etiqueta '{tag}' no es válida según models.py"
                found_tags.add(tag)

        # Variedad de tags poblados
        assert len(found_tags) >= 4, "El fixture debe poblar diversos icon_tags válidos"

    def test_integridad_modalidades_y_display_order(self, editor_network):
        """
        Verifica tipos de red, subtipos correspondientes (bus_articulado debe usar
        subtipo bus_articulado) y que display_order no tenga colisiones.
        """
        metro = editor_network["line_metro"]
        brt = editor_network["line_brt"]

        assert metro.network_type == "metro"
        assert metro.line_subtype == "convencional"

        assert brt.network_type == "bus_articulado"
        assert brt.line_subtype == "bus_articulado"

        # display_order único sin colisiones
        orders = [l.display_order for l in editor_network["all_lines"]]
        assert len(orders) == len(set(orders)), f"Colisión en display_order: {orders}"

        # Metro tiene rama principal y ramal adicional
        metro_branches = list(
            LineStation.objects.filter(line=metro).values_list("branch", flat=True).distinct()
        )
        assert "main" in metro_branches
        assert "ramal_1" in metro_branches

    def test_integridad_station_variants(self, station_variants):
        """
        Verifica el fixture station_variants que provee directamente las 4 variantes de estación:
        - normal
        - con icon_tags
        - terminal
        - correspondencia (metro-metro, metro-brt, triple)
        """
        assert station_variants["normal"].is_transfer is False
        assert station_variants["normal"].is_terminal is False

        assert len(station_variants["with_icons"].icon_tags) >= 2
        for t in station_variants["with_icons"].icon_tags:
            assert t in ALLOWED_ICON_TAGS

        assert station_variants["terminal"].is_terminal is True
        assert len(station_variants["terminal"].terminal_lines) >= 1

        assert station_variants["transfer_metro_metro"].is_transfer is True
        assert station_variants["transfer_metro_brt"].is_transfer is True
        assert station_variants["transfer_triple"].is_transfer is True
        assert len(station_variants["transfer_triple"].terminal_lines) == 3

    def test_integridad_coexistencia_con_seeded_network(self, seeded_network, editor_network):
        """
        Prueba crítica de coexistencia con la red real:
        seeded_network carga 828 estaciones y 34 líneas del catálogo maestro.
        editor_network debe construirse en la misma prueba sin colisiones de códigos únicos.
        """
        total_lines = TransitLine.objects.count()
        total_stations = Station.objects.count()

        # 34 líneas maestras + 3 líneas del fixture editor_network
        assert total_lines == 34 + len(editor_network["all_lines"])
        # 828 estaciones maestras + estaciones del fixture
        assert total_stations > 828

        # Verificar unicidad absoluta en toda la base de datos
        all_line_codes = list(TransitLine.objects.values_list("code", flat=True))
        all_station_codes = list(Station.objects.values_list("code", flat=True))
        assert len(all_line_codes) == len(set(all_line_codes))
        assert len(all_station_codes) == len(set(all_station_codes))
