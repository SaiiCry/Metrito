"""
Modelos de datos para el Sistema de Metro y Transporte (SMyT).
Separa estrictamente los datos topológicos, geométricos, de infraestructura y operativos
de la capa de visualización.
"""

from django.db import models


class CityOutline(models.Model):
    """
    Define polígonos y elementos geográficos editables de la ciudad ficticia (Asura / SMyT):
    mancha urbana, meseta central, distritos, ríos y cuerpos de agua.
    """
    ZONE_TYPES = [
        ('urban_core', 'Núcleo Urbano Denso'),
        ('metropolitan', 'Área Metropolitana / Periferia'),
        ('industrial', 'Polígono Industrial'),
        ('water', 'Cuerpo de Agua / Río / Canal'),
        ('park', 'Reserva Ecológica / Parque'),
        ('airport', 'Zona Aeroportuaria'),
    ]
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    zone_type = models.CharField(max_length=30, choices=ZONE_TYPES, default='urban_core')
    color = models.CharField(max_length=25, default='#1e293b')
    opacity = models.FloatField(default=0.18)
    # Lista JSON de vértices [[x, y], ...] en coordenadas del lienzo (0..13020, 0..4700)
    polygon_points = models.JSONField(default=list)
    elevation_m = models.FloatField(default=2240.0, help_text="Elevación promedio sobre el nivel del mar (m)")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.zone_type})"


class TransitLine(models.Model):
    """
    Representa una línea de la red SMyT.
    Distingue explícitamente entre:
    - 'metro': Metro (Líneas convencionales 1-22 y Alimentadoras A-G)
    - 'bus_articulado': Red de autobuses articulados / Metropolitano (Sistemas 1-5)
    """
    NETWORK_TYPES = [
        ('metro', 'Metro (Subterráneo / Superficial / Elevado)'),
        ('bus_articulado', 'Red de Autobuses Articulados (Metropolitano)'),
    ]
    SUBTYPES = [
        ('convencional', 'Línea Convencional (1–22)'),
        ('alimentadora', 'Línea Alimentadora (A–G)'),
        ('bus_articulado', 'Sistema Auxiliar de Autobuses Articulados (1–5)'),
    ]
    STATUS_CHOICES = [
        ('operational', 'En Operación Normal'),
        ('partial', 'Operación Parcial / Tramo Clausurado o en Obra'),
        ('construction', 'En Construcción'),
        ('expansion_pending', 'Operativa con Ampliación Pendiente'),
        ('suspended', 'Servicio Suspendido'),
    ]

    code = models.CharField(max_length=20, unique=True, help_text="Identificador de línea: 1..22, A..G, S1..S5")
    name = models.CharField(max_length=120, help_text="Nombre oficial, ej. Línea 1 o Sistema 1 BRT")
    route_title = models.CharField(max_length=200, help_text="Terminales, ej. Siervo de la Nación – Sofia")
    direction_axis = models.CharField(max_length=150, blank=True, help_text="Dirección general y eje vial")
    network_type = models.CharField(max_length=25, choices=NETWORK_TYPES, default='metro')
    line_subtype = models.CharField(max_length=25, choices=SUBTYPES, default='convencional')
    color = models.CharField(max_length=20, default='#0052ff', help_text="Color hexadecimal coincidente con metro2.png")
    text_color = models.CharField(max_length=20, default='#ffffff')

    length_km = models.FloatField(default=20.0, help_text="Longitud comercial en km")
    total_track_km = models.FloatField(default=24.0, help_text="Longitud total incluyendo talleres y maniobras")
    declared_stations_count = models.IntegerField(default=20)
    operational_stations_count = models.IntegerField(default=20)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='operational')
    status_note = models.TextField(blank=True, help_text="Notas de estado operativo (ampliaciones, cierres, ramales)")

    # Parámetros operativos y de horarios
    frequency_seconds = models.IntegerField(default=180, help_text="Frecuencia estándar de paso en segundos")
    premium_frequency_seconds = models.IntegerField(
        null=True, blank=True,
        help_text="Frecuencia del servicio expreso/premium (ej. 300s en Línea A)"
    )
    max_speed_kmh = models.FloatField(default=50.0, help_text="Velocidad máxima comercial (km/h)")
    premium_speed_kmh = models.FloatField(null=True, blank=True, help_text="Velocidad máxima servicio premium (km/h)")
    first_train_time = models.CharField(max_length=10, default='05:00')
    last_train_time = models.CharField(max_length=10, default='23:59')
    rolling_stock = models.CharField(
        max_length=180,
        default='Alstom Metrópolis (NA-2002 / NA-2016)',
        help_text="Material rodante o flota de autobuses biarticulados"
    )
    traction_type = models.CharField(
        max_length=120,
        default='Neumática · 750 VCC (barra guía / tercer riel)',
        help_text="Tipo de rodadura y electrificación"
    )
    annual_ridership_millions = models.FloatField(default=300.0, help_text="Afluencia anual en millones de pasajeros")
    current_occupancy_pct = models.IntegerField(default=62, help_text="Ocupación actual promedio (%)")

    # Criterios geométricos y constructivos del PDF
    min_curve_radius_m = models.FloatField(default=250.0, help_text="Radio mínimo de curva horizontal (m)")
    superelevation_mm = models.FloatField(
        default=115.0,
        help_text="Sobreelevación aplicada en curvas con R < 1800 m (mm)"
    )
    min_tangent_between_curves_m = models.FloatField(
        default=17.0,
        help_text="Tangente mínima entre dos curvas consecutivas (>= 17.000 m)"
    )
    min_curve_length_m = models.FloatField(
        default=16.0,
        help_text="Longitud mínima de curva circular (>= 16.00 m)"
    )
    depots_info = models.TextField(blank=True, help_text="Talleres, cocheras y patios de maniobras")
    is_circular = models.BooleanField(default=False, help_text="True para circuitos cerrados como Línea A")
    display_order = models.IntegerField(default=0)
    is_user_created = models.BooleanField(
        default=False,
        help_text="Indica si la línea fue creada por el usuario en el editor visual"
    )
    is_custom_modified = models.BooleanField(
        default=False,
        help_text="Indica si la línea fue editada por el usuario"
    )

    # Polilínea editable completa de la vía [[x, y], ...] o lista de ramas
    custom_geometry = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.name}: {self.route_title}"


class Station(models.Model):
    """
    Representa una estación o nodo físico en el mapa.
    Las estaciones de correspondencia comparten un mismo nodo visual o coordenadas conectadas,
    mientras que el conteo total de estaciones por línea suma las 828 estaciones del Plan Maestro.
    """
    INFRASTRUCTURE_CHOICES = [
        ('subterraneo', 'Subterráneo (Trinchera / Cajón Cortar y Cubrir)'),
        ('tunel_profundo', 'Túnel Profundo (Tuneladora + Lumbreras)'),
        ('superficial', 'Superficial (Nivel de Calle / Camellón Central)'),
        ('elevado', 'Viaducto Elevado (Estructura Prefabricada)'),
    ]
    STATUS_CHOICES = [
        ('operational', 'En Operación'),
        ('construction', 'En Construcción'),
        ('closed_permanent', 'Cerrada Permanentemente (Conflicto Territorial)'),
        ('expansion_planned', 'Ampliación Pendiente / Futura Correspondencia'),
    ]
    PLATFORM_CHOICES = [
        ('lateral', 'Andenes Laterales (2 vías)'),
        ('central', 'Andén Central (Isla)'),
        ('triple', 'Triple Andén (Alta Afluencia / Terminal)'),
        ('seis_andenes', 'Seis Andenes (2 Ordinario + 2 Premium + 2 Reserva - Línea A)'),
        ('brt_central', 'Plataforma Alta Central confinada (Autobús Articulado)'),
    ]

    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=140, db_index=True)

    # Coordenadas en el sistema esquemático de metro2.png (0..13020, 0..4700)
    x = models.FloatField(default=6000.0)
    y = models.FloatField(default=2000.0)

    # Coordenadas geográficas deducidas de forma coherente (Lon/Lat) para vista MapLibre/Leaflet Geo
    lat = models.FloatField(default=19.4326)
    lng = models.FloatField(default=-99.1332)

    infrastructure_type = models.CharField(
        max_length=25, choices=INFRASTRUCTURE_CHOICES, default='subterraneo'
    )
    operational_status = models.CharField(
        max_length=25, choices=STATUS_CHOICES, default='operational'
    )

    # Ingeniería y arquitectura plausible según el PDF
    depth_meters = models.FloatField(
        default=-10.0,
        help_text="Profundidad (-) o altura sobre nivel de calzada (+) en metros"
    )
    platform_type = models.CharField(max_length=25, choices=PLATFORM_CHOICES, default='lateral')
    platform_count = models.IntegerField(default=2)
    has_psd = models.BooleanField(
        default=True,
        help_text="Puertas Automáticas de Andén (PSD / APG)"
    )
    ventilation_system = models.CharField(
        max_length=140,
        default='Inyección/extracción mecánica con pozos de alivio y control climático HVAC'
    )
    emergency_exits = models.IntegerField(default=4)
    Drainage_and_accessibility = models.CharField(
        max_length=200,
        default='Cárcamo de bombeo pluvial redundante, ascensores, escaleras mecánicas y guías podotáctiles'
    )
    is_transfer = models.BooleanField(default=False)
    is_terminal = models.BooleanField(default=False)
    has_depot = models.BooleanField(default=False)
    depot_details = models.CharField(max_length=220, blank=True)
    is_premium_stop = models.BooleanField(
        default=False,
        help_text="Parada del Servicio Expreso/Premium (20 estaciones clave de Línea A)"
    )
    icon_tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Etiquetas con iconos a un costado de la estación: aeropuerto, parque, terminal, centro_modal, zona_cultural, escuela"
    )
    terminal_lines = models.JSONField(
        default=list,
        blank=True,
        help_text="Códigos de línea para los que esta estación muestra el icono con el número de línea terminal a su lado"
    )
    is_user_created = models.BooleanField(
        default=False,
        help_text="Indica si la estación fue creada por el usuario en el editor visual"
    )
    is_custom_modified = models.BooleanField(
        default=False,
        help_text="Indica si sus propiedades fueron modificadas por el usuario"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class LineStation(models.Model):
    """
    Asocia cada línea con sus estaciones en orden secuencial, definiendo el tipo de tramo
    (subterráneo, superficial, viaducto elevado, túnel profundo), estado operativo del segmento,
    cadenamiento al milímetro y parámetros geométricos de curva/tangente entre estaciones.
    Las 34 líneas suman exactamente las 828 estaciones de la ficha técnica.
    """
    line = models.ForeignKey(TransitLine, on_delete=models.CASCADE, related_name='line_stations')
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='station_lines')
    sequence = models.IntegerField(help_text="Orden de la estación en la línea (0..N)")
    branch = models.CharField(
        max_length=40, default='main',
        help_text="Tramo o ramal: 'main', 'ramal_1', 'ramal_2', etc."
    )

    segment_infrastructure = models.CharField(
        max_length=25,
        choices=Station.INFRASTRUCTURE_CHOICES,
        default='subterraneo',
        help_text="Tipo de construcción del tramo hacia la siguiente estación"
    )
    segment_status = models.CharField(
        max_length=25,
        choices=Station.STATUS_CHOICES,
        default='operational'
    )
    depth_meters = models.FloatField(default=-10.0)
    chainage_km = models.FloatField(default=0.0, help_text="Cadenamiento acumulado en km (precisión al mm)")
    curve_radius_m = models.FloatField(
        default=1800.0,
        help_text="Radio de curva horizontal en el tramo (si <1800m aplica sobreelevación)"
    )
    superelevation_deg = models.FloatField(
        default=0.0,
        help_text="Peralte / sobreelevación en el tramo"
    )
    tangent_length_m = models.FloatField(
        default=450.0,
        help_text="Longitud de tangente horizontal (mínimo 17.000 m entre curvas; estaciones en tangente)"
    )
    correspondences_text = models.CharField(max_length=80, blank=True)
    notes = models.CharField(max_length=180, blank=True)
    # Puntos intermedios del trazo entre esta estación y la siguiente [[x, y], ...]
    waypoints = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['line', 'branch', 'sequence']
        unique_together = [('line', 'branch', 'sequence')]

    def __str__(self):
        return f"{self.line.code} [{self.sequence}] {self.station.name}"


class OperationalAlert(models.Model):
    """
    Alertas e incidencias del Centro de Control Operativo (PCCO - SMyT).
    Permite crear, simular, resolver y auditar incidentes en tiempo real.
    """
    SEVERITY_CHOICES = [
        ('critical', 'Crítica: Interrupción / Seguridad'),
        ('warning', 'Preventiva: Regulación de Marcha / Retraso'),
        ('info', 'Informativa: Mantenimiento / Evento Programado'),
        ('resolved', 'Resuelta: Operación Normalizada'),
    ]
    CATEGORY_CHOICES = [
        ('signaling', 'Señalización CBTC / Pilotaje Automático'),
        ('power', 'Subestación Rectificadora 750 VCC'),
        ('rolling_stock', 'Material Rodante / Puertas de Andén (PSD)'),
        ('weather', 'Drenaje Pluvial / Lluvia Extrema en Tramo Superficial'),
        ('civil', 'Cierre Permanente / Conflicto Territorial / Obra Civil'),
        ('crowding', 'Saturación de Andén / Despacho de Trenes en Vacío'),
    ]

    title = models.CharField(max_length=180)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='signaling')
    line = models.ForeignKey(
        TransitLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts'
    )
    station = models.ForeignKey(
        Station, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts'
    )
    speed_factor = models.FloatField(
        default=1.0,
        help_text="Factor multiplicador de velocidad en la línea afectada (ej. 0.5 para marcha reducida, 0.0 detenido)"
    )
    delay_seconds = models.IntegerField(default=0, help_text="Retraso estimado añadido en segundos")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-is_active', '-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"


class UserNetworkEditLayer(models.Model):
    """
    Capa de persistencia independiente para los datos y modificaciones del usuario.
    Almacena el estado serializado de las estaciones creadas, líneas añadidas,
    tramos modificados y correspondencias de transbordo, asegurando que sobrevivan
    a reinicios del servidor, recargas del navegador y actualizaciones de código.
    """
    version = models.IntegerField(default=1)
    name = models.CharField(max_length=100, default="default_user_layer")
    description = models.TextField(blank=True, default="Capa de edición de usuario local")
    data = models.JSONField(
        default=dict,
        help_text="Deltas y estado completo de ediciones del usuario: created_stations, created_lines, route_overrides, etc."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} v{self.version} ({self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else 'new'})"
