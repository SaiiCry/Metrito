"""
Configuración global de fixtures para pytest y pytest-django.
Garantiza aislamiento de base de datos, fixtures modulares y ejecución determinista.
"""

import pytest
from django.test import Client
from network.models import TransitLine, Station, LineStation, CityOutline, OperationalAlert, UserNetworkEditLayer
from network.seed import seed_database


@pytest.fixture
def api_client():
    """Cliente HTTP de pruebas de Django aislado."""
    return Client()


@pytest.fixture
def station_factory(db):
    """Fábrica de estaciones con valores por defecto válidos y códigos únicos."""
    created_count = 0

    def _create_station(**kwargs):
        nonlocal created_count
        created_count += 1
        defaults = {
            "code": f"test-st-{created_count}",
            "name": f"Estación Prueba {created_count}",
            "x": 2000.0 + (created_count * 10.0),
            "y": 1500.0 + (created_count * 10.0),
            "lat": 19.4326,
            "lng": -99.1332,
            "infrastructure_type": "subterraneo",
            "operational_status": "operational",
            "platform_type": "lateral",
            "platform_count": 2,
            "has_psd": True,
            "is_transfer": False,
            "is_terminal": False,
            "icon_tags": [],
            "terminal_lines": [],
            "is_user_created": False,
            "is_custom_modified": False,
        }
        defaults.update(kwargs)
        return Station.objects.create(**defaults)

    return _create_station


@pytest.fixture
def line_factory(db):
    """Fábrica de líneas de tránsito con valores por defecto válidos y display_order sin colisiones."""
    created_count = 0

    def _create_line(**kwargs):
        nonlocal created_count
        created_count += 1
        net_type = kwargs.get("network_type", "metro")
        sub_type = kwargs.get(
            "line_subtype",
            "bus_articulado" if net_type == "bus_articulado" else "convencional"
        )
        color = kwargs.get(
            "color",
            "#16A34A" if net_type == "bus_articulado" else "#1E40AF"
        )
        defaults = {
            "code": f"TL{created_count}",
            "name": f"Línea de Prueba {created_count}",
            "route_title": f"Terminal A – Terminal B",
            "network_type": net_type,
            "line_subtype": sub_type,
            "color": color,
            "text_color": "#FFFFFF",
            "display_order": TransitLine.objects.count() + 1,
            "length_km": 15.0,
            "declared_stations_count": 2,
            "operational_stations_count": 2,
            "status": "operational",
            "frequency_seconds": 180,
            "max_speed_kmh": 60.0,
            "is_user_created": False,
            "is_custom_modified": False,
        }
        defaults.update(kwargs)
        return TransitLine.objects.create(**defaults)

    return _create_line


@pytest.fixture
def brt_line_factory(line_factory):
    """Fábrica especializada en líneas de autobús articulado BRT con subtipo bus_articulado."""
    def _create_brt(**kwargs):
        count = TransitLine.objects.filter(network_type="bus_articulado").count() + 1
        defaults = {
            "code": f"S{count}",
            "name": f"Sistema {count} BRT",
            "network_type": "bus_articulado",
            "line_subtype": "bus_articulado",
            "color": "#16A34A",
            "text_color": "#FFFFFF",
            "route_title": f"Terminal BRT Norte – Terminal BRT Sur",
        }
        defaults.update(kwargs)
        return line_factory(**defaults)

    return _create_brt


@pytest.fixture
def minimal_network(db, line_factory, station_factory):
    """
    Crea una red mínima ultrarrápida sin necesidad de poblar las 828 estaciones del catálogo:
    - Línea 1 (código '1'): Estación Alfa (seq 0) -> Estación Beta (seq 1)
    - Línea 2 (código '2'): Estación Gamma (seq 0) -> Estación Delta (seq 1)
    """
    line_1 = line_factory(code="1", name="Línea 1", route_title="Alfa – Beta")
    line_2 = line_factory(code="2", name="Línea 2", route_title="Gamma – Delta")

    st_alfa = station_factory(code="st-alfa", name="Alfa", x=1000.0, y=1000.0, terminal_lines=["1"], is_terminal=True)
    st_beta = station_factory(code="st-beta", name="Beta", x=1500.0, y=1000.0, terminal_lines=["1"], is_terminal=True)

    st_gamma = station_factory(code="st-gamma", name="Gamma", x=1000.0, y=1500.0, terminal_lines=["2"], is_terminal=True)
    st_delta = station_factory(code="st-delta", name="Delta", x=1500.0, y=1500.0, terminal_lines=["2"], is_terminal=True)

    ls_1_0 = LineStation.objects.create(
        line=line_1, station=st_alfa, sequence=0, branch="main",
        segment_infrastructure="subterraneo", segment_status="operational"
    )
    ls_1_1 = LineStation.objects.create(
        line=line_1, station=st_beta, sequence=1, branch="main",
        segment_infrastructure="subterraneo", segment_status="operational"
    )

    ls_2_0 = LineStation.objects.create(
        line=line_2, station=st_gamma, sequence=0, branch="main",
        segment_infrastructure="subterraneo", segment_status="operational"
    )
    ls_2_1 = LineStation.objects.create(
        line=line_2, station=st_delta, sequence=1, branch="main",
        segment_infrastructure="subterraneo", segment_status="operational"
    )

    return {
        "line_1": line_1,
        "line_2": line_2,
        "st_alfa": st_alfa,
        "st_beta": st_beta,
        "st_gamma": st_gamma,
        "st_delta": st_delta,
        "ls_1_0": ls_1_0,
        "ls_1_1": ls_1_1,
        "ls_2_0": ls_2_0,
        "ls_2_1": ls_2_1,
    }


@pytest.fixture
def seeded_network(db):
    """
    Puebla el catálogo maestro completo de 828 estaciones y 34 líneas desde cartografia/red_metro.json.
    Usar solo para pruebas que verifiquen coherencia global o nodos específicos del plan maestro.
    """
    res = seed_database(force_reset=True)
    return res


ALLOWED_ICON_TAGS = [
    "aeropuerto",
    "parque",
    "terminal",
    "centro_modal",
    "zona_cultural",
    "escuela",
]


class NetworkEntityBundle(dict):
    """
    Contenedor de red de prueba con compatibilidad dual (diccionario y atributos)
    y métodos de acceso ergonómico para líneas, estaciones y relaciones organizadas
    por rama y secuencia.
    """
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'NetworkEntityBundle' no contiene el atributo o clave '{name}'")

    @property
    def lines_by_code(self):
        return {l.code: l for l in self.get("all_lines", [])}

    @property
    def stations_by_code(self):
        return {s.code: s for s in self.get("all_stations", [])}

    @property
    def metro_line(self):
        return self.get("line_metro")

    @property
    def metro_line_2(self):
        return self.get("line_metro_2")

    @property
    def brt_line(self):
        return self.get("line_brt")

    def get_stops(self, line_code, branch="main"):
        """Retorna los LineStation de una línea y rama ordenados por secuencia."""
        return list(
            LineStation.objects.filter(line__code=line_code, branch=branch).order_by("sequence")
        )

    def get_station(self, code_or_name):
        """Retorna una estación por su código o nombre."""
        return Station.objects.filter(code=code_or_name).first() or Station.objects.filter(name=code_or_name).first()


@pytest.fixture
def station_variants(db, station_factory, line_factory, brt_line_factory):
    """
    Colección de estaciones cubriendo todas las variantes exigidas por models.py:
    1. normal: Estación regular sin transbordo ni terminal.
    2. with_icons: Estación con icon_tags válidos permitidos (parque, escuela).
    3. terminal: Estación terminal (is_terminal=True, terminal_lines válidas).
    4. transfer_metro_metro: Transbordo Metro con Metro con terminal_lines recíprocas.
    5. transfer_metro_brt: Transbordo Metro con BRT con terminal_lines recíprocas.
    6. transfer_triple: Transbordo triple (Metro 1, Metro 2 y BRT).
    """
    l1 = line_factory(code="V1", name="Línea V1 Metro", network_type="metro", line_subtype="convencional")
    l2 = line_factory(code="V2", name="Línea V2 Metro", network_type="metro", line_subtype="convencional")
    brt = brt_line_factory(code="SV1", name="Sistema V1 BRT")

    st_normal = station_factory(
        code="st-var-normal",
        name="Estación Normal",
        infrastructure_type="subterraneo",
        operational_status="operational",
        is_transfer=False,
        is_terminal=False,
        icon_tags=[],
        terminal_lines=[],
    )

    st_icons = station_factory(
        code="st-var-icons",
        name="Estación Con Iconos",
        infrastructure_type="subterraneo",
        operational_status="operational",
        is_transfer=False,
        is_terminal=False,
        icon_tags=["parque", "escuela", "zona_cultural"],
        terminal_lines=[],
    )

    st_terminal = station_factory(
        code="st-var-terminal",
        name="Estación Terminal",
        infrastructure_type="superficial",
        operational_status="operational",
        is_transfer=False,
        is_terminal=True,
        icon_tags=["terminal"],
        terminal_lines=[l1.code],
    )

    st_transfer_mm = station_factory(
        code="st-var-transfer-mm",
        name="Correspondencia Metro-Metro",
        infrastructure_type="subterraneo",
        operational_status="operational",
        is_transfer=True,
        is_terminal=False,
        icon_tags=["centro_modal"],
        terminal_lines=[l1.code, l2.code],
    )

    st_transfer_mbrt = station_factory(
        code="st-var-transfer-mbrt",
        name="Correspondencia Metro-BRT",
        infrastructure_type="subterraneo",
        operational_status="operational",
        is_transfer=True,
        is_terminal=False,
        icon_tags=["centro_modal"],
        terminal_lines=[l1.code, brt.code],
    )

    st_transfer_triple = station_factory(
        code="st-var-transfer-triple",
        name="Correspondencia Triple Hub",
        infrastructure_type="subterraneo",
        operational_status="operational",
        is_transfer=True,
        is_terminal=True,
        icon_tags=["centro_modal", "aeropuerto", "terminal"],
        terminal_lines=[l1.code, l2.code, brt.code],
    )

    # Conectar LineStation para reflejar pertenencia real
    LineStation.objects.create(line=l1, station=st_normal, sequence=0, branch="main")
    LineStation.objects.create(line=l1, station=st_icons, sequence=1, branch="main")
    LineStation.objects.create(line=l1, station=st_terminal, sequence=2, branch="main")
    LineStation.objects.create(line=l1, station=st_transfer_mm, sequence=3, branch="main")
    LineStation.objects.create(line=l1, station=st_transfer_mbrt, sequence=4, branch="main")
    LineStation.objects.create(line=l1, station=st_transfer_triple, sequence=5, branch="main")

    LineStation.objects.create(line=l2, station=st_transfer_mm, sequence=0, branch="main")
    LineStation.objects.create(line=l2, station=st_transfer_triple, sequence=1, branch="main")

    LineStation.objects.create(line=brt, station=st_transfer_mbrt, sequence=0, branch="main")
    LineStation.objects.create(line=brt, station=st_transfer_triple, sequence=1, branch="main")

    return {
        "lines": {"metro_1": l1, "metro_2": l2, "brt": brt},
        "normal": st_normal,
        "with_icons": st_icons,
        "terminal": st_terminal,
        "transfer_metro_metro": st_transfer_mm,
        "transfer_metro_brt": st_transfer_mbrt,
        "transfer_triple": st_transfer_triple,
    }


@pytest.fixture
def editor_network_factory(db, line_factory, brt_line_factory, station_factory):
    """
    Fábrica componible y parametrizable para construir redes de prueba completas
    para el editor de trazado. Reutiliza station_factory y line_factory.

    Cubre y combina:
    - Líneas de metro (convencional) y autobús articulado (bus_articulado con subtipo bus_articulado).
    - LineStation ordenados por sequence (0..N) sin duplicados ni huecos por línea y rama.
    - Líneas con rama 'main' y ramas adicionales ('ramal_1').
    - Correspondencias combinadas:
      * Metro con Metro (terminal_lines recíprocas).
      * Metro con Autobús Articulado (terminal_lines recíprocas).
      * Triple correspondencia (Metro 1 + Metro 2 + BRT con terminal_lines recíprocas).
    - Tramos con waypoints vacíos y con coordenadas válidas [[x, y], ...].
    - Estaciones terminales con is_terminal=True y terminal_lines coherentes.
    - Estaciones con icon_tags válidos poblados (aeropuerto, parque, terminal, centro_modal, zona_cultural, escuela).
    - Coexistencia segura con seeded_network evitando colisiones de códigos únicos.
    """
    factory_counter = 0

    def _resolve_code(preferred: str, existing_qs, prefix="fx"):
        if not existing_qs.filter(code=preferred).exists():
            return preferred
        candidate = f"{prefix}_{preferred}"
        c = 1
        while existing_qs.filter(code=candidate).exists():
            candidate = f"{prefix}_{preferred}_{c}"
            c += 1
        return candidate

    def _build_network(
        metro_code="1",
        metro_name="Línea 1 Metro",
        metro_subtype="convencional",
        metro_code_2="2",
        metro_name_2="Línea 2 Metro",
        brt_code="S1",
        brt_name="Sistema 1 BRT",
        has_branch=True,
        branch_name="ramal_1",
        include_metro_2=True,
        prefix="fx",
        **custom_kwargs
    ):
        nonlocal factory_counter
        factory_counter += 1
        net_id = factory_counter

        # Resolver códigos únicos que no colisionen si seeded_network ya existe
        m_code = _resolve_code(metro_code, TransitLine.objects, prefix=f"{prefix}m{net_id}")
        m2_code = _resolve_code(metro_code_2, TransitLine.objects, prefix=f"{prefix}m2_{net_id}")
        b_code = _resolve_code(brt_code, TransitLine.objects, prefix=f"{prefix}b{net_id}")

        # 1. Crear Líneas (Metro 1, Metro 2 opcional, y Autobús Articulado)
        line_metro = line_factory(
            code=m_code,
            name=metro_name,
            route_title="Terminal Norte – Terminal Sur",
            network_type="metro",
            line_subtype=metro_subtype,
            color="#0052FF",
            text_color="#FFFFFF",
            length_km=18.5,
            frequency_seconds=180,
            max_speed_kmh=65.0,
        )

        line_metro_2 = None
        if include_metro_2:
            line_metro_2 = line_factory(
                code=m2_code,
                name=metro_name_2,
                route_title="Transbordo Poniente – Oriente Metro 2",
                network_type="metro",
                line_subtype="convencional",
                color="#F59E0B",
                text_color="#FFFFFF",
                length_km=12.0,
                frequency_seconds=200,
                max_speed_kmh=60.0,
            )

        line_brt = brt_line_factory(
            code=b_code,
            name=brt_name,
            route_title="BRT Poniente – BRT Oriente",
            network_type="bus_articulado",
            line_subtype="bus_articulado",
            color="#16A34A",
            text_color="#FFFFFF",
            length_km=14.0,
            frequency_seconds=210,
            max_speed_kmh=45.0,
        )

        # 2. Crear Estaciones con icon_tags válidos y terminales válidas
        st_pfx = f"{prefix}-net{net_id}"

        # Estación terminal de Metro Norte (inicio de main)
        st_m_start = station_factory(
            code=f"{st_pfx}-m-norte",
            name=f"Terminal Norte {net_id}",
            x=1000.0, y=1000.0,
            is_terminal=True,
            terminal_lines=[m_code],
            icon_tags=["terminal", "centro_modal"],
            infrastructure_type="subterraneo",
        )

        # Estación intermedia normal con icon_tags válidos y tramo con waypoints geométricos
        st_m_normal = station_factory(
            code=f"{st_pfx}-m-normal",
            name=f"Parque Cultural {net_id}",
            x=1250.0, y=1000.0,
            is_transfer=False,
            is_terminal=False,
            terminal_lines=[],
            icon_tags=["parque", "zona_cultural"],
            infrastructure_type="subterraneo",
        )

        # Correspondencia Metro con Metro (Línea Metro 1 y Línea Metro 2)
        st_transfer_mm = station_factory(
            code=f"{st_pfx}-transfer-mm",
            name=f"Correspondencia Metro-Metro {net_id}",
            x=1400.0, y=1000.0,
            is_transfer=True,
            is_terminal=False,
            terminal_lines=[m_code, m2_code] if include_metro_2 else [m_code],
            icon_tags=["centro_modal"],
            infrastructure_type="subterraneo",
        )

        # Correspondencia Triple: Metro 1 + Metro 2 + BRT
        triple_lines = [m_code, m2_code, b_code] if include_metro_2 else [m_code, b_code]
        st_transfer_triple = station_factory(
            code=f"{st_pfx}-transbordo-triple",
            name=f"Centro Intermodal Triple {net_id}",
            x=1600.0, y=1000.0,
            is_transfer=True,
            is_terminal=True,
            terminal_lines=triple_lines,
            icon_tags=["centro_modal", "aeropuerto", "terminal"],
            infrastructure_type="subterraneo",
        )

        # Correspondencia Metro con BRT
        st_transfer_mbrt = station_factory(
            code=f"{st_pfx}-transfer-mbrt",
            name=f"Correspondencia Metro-BRT {net_id}",
            x=1800.0, y=1000.0,
            is_transfer=True,
            is_terminal=False,
            terminal_lines=[m_code, b_code],
            icon_tags=["escuela"],
            infrastructure_type="subterraneo",
        )

        # Estación terminal de Metro Sur (fin de main)
        st_m_end = station_factory(
            code=f"{st_pfx}-m-sur",
            name=f"Terminal Sur {net_id}",
            x=2100.0, y=1000.0,
            is_terminal=True,
            terminal_lines=[m_code],
            icon_tags=["terminal"],
            infrastructure_type="subterraneo",
        )

        # Estación terminal de ramal adicional para Metro 1 (aeropuerto / escuela)
        st_branch_term = None
        if has_branch:
            st_branch_term = station_factory(
                code=f"{st_pfx}-m-ramal",
                name=f"Ramal Campus Aeropuerto {net_id}",
                x=1900.0, y=1400.0,
                is_terminal=True,
                terminal_lines=[m_code],
                icon_tags=["aeropuerto", "terminal"],
                infrastructure_type="elevado",
            )

        # Terminales de Metro 2 y BRT
        st_m2_end = None
        if include_metro_2:
            st_m2_end = station_factory(
                code=f"{st_pfx}-m2-oriente",
                name=f"Terminal Oriente M2 {net_id}",
                x=1600.0, y=1600.0,
                is_terminal=True,
                terminal_lines=[m2_code],
                icon_tags=["terminal"],
                infrastructure_type="superficial",
            )

        st_b_start = station_factory(
            code=f"{st_pfx}-b-poniente",
            name=f"BRT Poniente {net_id}",
            x=1600.0, y=400.0,
            is_terminal=True,
            terminal_lines=[b_code],
            icon_tags=["terminal"],
            infrastructure_type="superficial",
        )

        st_b_end = station_factory(
            code=f"{st_pfx}-b-oriente",
            name=f"BRT Oriente {net_id}",
            x=1800.0, y=1600.0,
            is_terminal=True,
            terminal_lines=[b_code],
            icon_tags=["terminal"],
            infrastructure_type="superficial",
        )

        # 3. Crear LineStation ordenados por sequence (0..N) dentro de cada rama
        # Metro 1 - Rama main:
        # seq 0: st_m_start (waypoints [])
        # seq 1: st_m_normal (waypoints poblados [[1100.0, 1000.0], [1200.0, 1000.0]])
        # seq 2: st_transfer_mm
        # seq 3: st_transfer_triple
        # seq 4: st_transfer_mbrt
        # seq 5: st_m_end
        ls_m_0 = LineStation.objects.create(
            line=line_metro, station=st_m_start, sequence=0, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=0.0, correspondences_text="", waypoints=[],
        )
        ls_m_1 = LineStation.objects.create(
            line=line_metro, station=st_m_normal, sequence=1, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=2.5, correspondences_text="",
            waypoints=[[1100.0, 1000.0], [1200.0, 1000.0]],
        )
        ls_m_2 = LineStation.objects.create(
            line=line_metro, station=st_transfer_mm, sequence=2, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=4.0, correspondences_text=f"{m_code}/{m2_code}" if include_metro_2 else "",
            waypoints=[],
        )
        ls_m_3 = LineStation.objects.create(
            line=line_metro, station=st_transfer_triple, sequence=3, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=6.0, correspondences_text="/".join(triple_lines),
            waypoints=[],
        )
        ls_m_4 = LineStation.objects.create(
            line=line_metro, station=st_transfer_mbrt, sequence=4, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=8.0, correspondences_text=f"{m_code}/{b_code}",
            waypoints=[],
        )
        ls_m_5 = LineStation.objects.create(
            line=line_metro, station=st_m_end, sequence=5, branch="main",
            segment_infrastructure="subterraneo", segment_status="operational",
            chainage_km=11.0, correspondences_text="", waypoints=[],
        )

        metro_main_stops = [ls_m_0, ls_m_1, ls_m_2, ls_m_3, ls_m_4, ls_m_5]
        metro_branch_stops = []

        if has_branch and st_branch_term:
            # Metro 1 - Rama ramal_1: st_transfer_triple (seq 0) -> st_branch_term (seq 1)
            ls_mr_0 = LineStation.objects.create(
                line=line_metro, station=st_transfer_triple, sequence=0, branch=branch_name,
                segment_infrastructure="subterraneo", segment_status="operational",
                chainage_km=0.0, correspondences_text="/".join(triple_lines), waypoints=[],
            )
            ls_mr_1 = LineStation.objects.create(
                line=line_metro, station=st_branch_term, sequence=1, branch=branch_name,
                segment_infrastructure="elevado", segment_status="operational",
                chainage_km=3.5, correspondences_text="", waypoints=[],
            )
            metro_branch_stops = [ls_mr_0, ls_mr_1]

        # Metro 2 - Rama main: st_transfer_mm (seq 0) -> st_transfer_triple (seq 1) -> st_m2_end (seq 2)
        metro_2_stops = []
        if include_metro_2 and line_metro_2 and st_m2_end:
            ls_m2_0 = LineStation.objects.create(
                line=line_metro_2, station=st_transfer_mm, sequence=0, branch="main",
                segment_infrastructure="subterraneo", segment_status="operational",
                chainage_km=0.0, correspondences_text=f"{m_code}/{m2_code}", waypoints=[],
            )
            ls_m2_1 = LineStation.objects.create(
                line=line_metro_2, station=st_transfer_triple, sequence=1, branch="main",
                segment_infrastructure="subterraneo", segment_status="operational",
                chainage_km=2.0, correspondences_text="/".join(triple_lines), waypoints=[],
            )
            ls_m2_2 = LineStation.objects.create(
                line=line_metro_2, station=st_m2_end, sequence=2, branch="main",
                segment_infrastructure="superficial", segment_status="operational",
                chainage_km=5.5, correspondences_text="", waypoints=[],
            )
            metro_2_stops = [ls_m2_0, ls_m2_1, ls_m2_2]
            line_metro_2.declared_stations_count = len(metro_2_stops)
            line_metro_2.operational_stations_count = len(metro_2_stops)
            line_metro_2.save(update_fields=["declared_stations_count", "operational_stations_count"])

        # BRT - Rama main: st_b_start (seq 0) -> st_transfer_triple (seq 1) -> st_transfer_mbrt (seq 2) -> st_b_end (seq 3)
        ls_b_0 = LineStation.objects.create(
            line=line_brt, station=st_b_start, sequence=0, branch="main",
            segment_infrastructure="superficial", segment_status="operational",
            chainage_km=0.0, correspondences_text="", waypoints=[],
        )
        ls_b_1 = LineStation.objects.create(
            line=line_brt, station=st_transfer_triple, sequence=1, branch="main",
            segment_infrastructure="superficial", segment_status="operational",
            chainage_km=3.0, correspondences_text="/".join(triple_lines), waypoints=[],
        )
        ls_b_2 = LineStation.objects.create(
            line=line_brt, station=st_transfer_mbrt, sequence=2, branch="main",
            segment_infrastructure="superficial", segment_status="operational",
            chainage_km=5.0, correspondences_text=f"{m_code}/{b_code}", waypoints=[],
        )
        ls_b_3 = LineStation.objects.create(
            line=line_brt, station=st_b_end, sequence=3, branch="main",
            segment_infrastructure="superficial", segment_status="operational",
            chainage_km=8.5, correspondences_text="", waypoints=[],
        )
        brt_main_stops = [ls_b_0, ls_b_1, ls_b_2, ls_b_3]

        # Sincronizar recuentos declarados y operativos
        total_m1 = len(metro_main_stops) + len(metro_branch_stops)
        line_metro.declared_stations_count = total_m1
        line_metro.operational_stations_count = total_m1
        line_metro.save(update_fields=["declared_stations_count", "operational_stations_count"])

        line_brt.declared_stations_count = len(brt_main_stops)
        line_brt.operational_stations_count = len(brt_main_stops)
        line_brt.save(update_fields=["declared_stations_count", "operational_stations_count"])

        # Mapeo por clave tuple (line_code, branch, sequence)
        all_stops = metro_main_stops + metro_branch_stops + metro_2_stops + brt_main_stops
        line_stations_map = {}
        for ls in all_stops:
            line_stations_map[(ls.line.code, ls.branch, ls.sequence)] = ls

        all_lines = [line_metro, line_brt]
        if line_metro_2:
            all_lines.append(line_metro_2)

        stations_dict = {
            "metro_start": st_m_start,
            "normal": st_m_normal,
            "transfer_metro_metro": st_transfer_mm,
            "transfer_triple": st_transfer_triple,
            "transfer_metro_brt": st_transfer_mbrt,
            "transfer": st_transfer_triple,
            "metro_end": st_m_end,
            "brt_start": st_b_start,
            "brt_end": st_b_end,
        }
        if st_branch_term:
            stations_dict["branch_term"] = st_branch_term
        if st_m2_end:
            stations_dict["m2_end"] = st_m2_end

        all_stations = list(stations_dict.values())

        by_line_and_branch = {
            line_metro.code: {
                "main": metro_main_stops,
            },
            line_brt.code: {
                "main": brt_main_stops,
            },
        }
        if metro_branch_stops:
            by_line_and_branch[line_metro.code][branch_name] = metro_branch_stops
        if metro_2_stops and line_metro_2:
            by_line_and_branch[line_metro_2.code] = {"main": metro_2_stops}

        return NetworkEntityBundle({
            "line_metro": line_metro,
            "line_metro_2": line_metro_2,
            "line_brt": line_brt,
            "lines": {
                "metro": line_metro,
                "metro_2": line_metro_2,
                "brt": line_brt,
            },
            "all_lines": all_lines,
            "all_stations": all_stations,
            "stations": stations_dict,
            "line_stations": line_stations_map,
            "all_line_stations": all_stops,
            "by_line_and_branch": by_line_and_branch,
            "metro_main_stops": metro_main_stops,
            "metro_branch_stops": metro_branch_stops,
            "metro_2_stops": metro_2_stops,
            "brt_main_stops": brt_main_stops,
            "transfer_station": st_transfer_triple,
            "transfer_metro_metro": st_transfer_mm,
            "transfer_metro_brt": st_transfer_mbrt,
            "transfer_triple": st_transfer_triple,
        })

    return _build_network


@pytest.fixture
def editor_network(editor_network_factory):
    """
    Red multimodal preconstruida que combina todas las restricciones de models.py
    y escenarios para pruebas unitarias e integración del editor de trazado.
    """
    return editor_network_factory()


@pytest.fixture
def metro_line_with_branches(editor_network_factory):
    """Fixture especializado en una línea de metro con rama principal y ramal adicional."""
    bundle = editor_network_factory(has_branch=True, branch_name="ramal_1")
    return {
        "line": bundle["line_metro"],
        "main_stops": bundle["metro_main_stops"],
        "branch_stops": bundle["metro_branch_stops"],
        "stations": bundle["stations"],
        "bundle": bundle,
    }


@pytest.fixture
def brt_line_fixture(editor_network_factory):
    """Fixture especializado en una línea de autobús articulado BRT."""
    bundle = editor_network_factory(has_branch=False)
    return {
        "line": bundle["line_brt"],
        "stops": bundle["brt_main_stops"],
        "stations": bundle["stations"],
        "bundle": bundle,
    }


@pytest.fixture
def transfer_network(editor_network_factory):
    """Fixture especializado en estaciones de correspondencia con terminal_lines recíprocas."""
    bundle = editor_network_factory()
    return {
        "transfer_station": bundle["transfer_station"],
        "transfer_metro_metro": bundle["transfer_metro_metro"],
        "transfer_metro_brt": bundle["transfer_metro_brt"],
        "transfer_triple": bundle["transfer_triple"],
        "line_metro": bundle["line_metro"],
        "line_metro_2": bundle["line_metro_2"],
        "line_brt": bundle["line_brt"],
        "bundle": bundle,
    }
