# SMyT · Sistema de Metro y Transporte (Plan Maestro 2025-2030)

Aplicación web de visualización geoespacial, cartografía editable y Puesto Central de Control Operativo (PCCO) en tiempo real para la red integrada de transporte urbano **SMyT**, construida con **Python / Django** en el backend y **HTML5, CSS3 y JavaScript (SVG + Leaflet + Motion One)** en el frontend.

## Características Principales

1. **Topología Completa y Fiel a `metro2.pdf` y `metro2.png`**:
   - **29 Líneas de Metro** (22 Líneas Convencionales `1` a `22` + 7 Líneas Alimentadoras `A` a `G`), que suman exactamente las **828 estaciones** declaradas en la ficha técnica maestra.
   - **5 Sistemas Auxiliares de la Red de Autobuses Articulados / Metropolitano** (`S1` a `S5`), con **171 paradas confinadas** (unificados en la misma categoría de red de autobuses articulados, sin duplicar categorías).
   - **Estados Operativos Reales**:
     - **Línea C**: 21 estaciones en operación comercial (`Albufera` a `Tlacotepec`) y 13 estaciones cerradas permanentemente (`Siervo de la Nación` a `Halcones`) por conflicto territorial, representadas con achurado de clausura e inversión de marcha en `Tlacotepec`.
     - **Línea A (Circuito Periférico de 132,8 km y 124 estaciones)**: configuración de 6 andenes por estación, con **Servicio Ordinario** en las 124 paradas (frecuencia 150 s, 80 km/h) y **Servicio Expreso Premium** en las 20 estaciones clave (frecuencia 300 s, 100 km/h).
     - **Tramos en construcción y ampliaciones pendientes**: Ramal `Santa Mónica - Ojo de Agua` (Línea 18), `Sistema 5` (`5A-5B-5C`), y futuras correspondencias en Líneas 6, 9, 17, 19 y 20.
2. **Representación de Ingeniería Civil y Criterios Geométricos**:
   - Simbología diferenciada y **Plano Técnico de Corte Transversal (SVG dinámico)** para estaciones y tramos en **Subterráneo** (cajón cortar y cubrir), **Túnel Profundo** (escudo TBM y lumbreras hasta `-75 m`), **Superficial** (`0 m`) y **Viaducto Elevado** (`+7,5 m` a `+9,5 m`).
   - Especificaciones de puertas automáticas de andén (`PSD / APG`), ventilación HVAC, cárcamos de bombeo pluvial, salidas de emergencia y criterios geométricos (`sobreelevación` en curvas con `R < 1.800 m`, `tangente mínima de 17,000 m` entre curvas y `longitud mínima de curva de 16,00 m`).
3. **Simulación en Tiempo Real (60 fps) y Centro de Control (PCCO)**:
   - Movimiento continuo de trenes y autobuses biarticulados con inversión de sentido en terminales, tiempos de ascenso/descenso en andén y seguimiento en tiempo real.
   - Simulación de incidentes operativos en 1 clic que modifican dinámicamente las velocidades y frecuencias de la línea afectada.
   - **Edición completa en vivo**: modificación de estaciones, líneas, colores, horarios, frecuencias, estados, coordenadas (arrastrando estaciones en el mapa) y polígonos geográficos de la ciudad, persistida en SQLite.

---

## Ejecución Rápida

El proyecto ya incluye el entorno virtual `.venv` configurado y la base de datos `db.sqlite3` migrada y poblada con las 34 líneas y todas sus estaciones, lista para ejecutarse de inmediato:

```powershell
# 1. Activar el entorno virtual (o usar directamente .\.venv\Scripts\python.exe)
.\.venv\Scripts\Activate.ps1

# 2. (Opcional) Instalar dependencias si se crea un entorno nuevo
pip install -r requirements.txt

# 3. Aplicar migraciones de base de datos
.\.venv\Scripts\python.exe manage.py migrate

# 4. (Opcional) Inicializar o restaurar la topología maestra de metro2.pdf y metro2.png
.\.venv\Scripts\python.exe manage.py seed_network --reset

# 5. Arrancar el servidor de desarrollo
.\.venv\Scripts\python.exe manage.py runserver 8000
```

Una vez iniciado el servidor, abre en el navegador:
- **Aplicación Principal y PCCO**: http://127.0.0.1:8000/
- **API JSON de la Red**: http://127.0.0.1:8000/api/network/
- **Panel de Administración Django**: http://127.0.0.1:8000/admin/

---

## Editor Visual de Red y Arquitectura de Persistencia

El sistema cuenta con un **Editor Visual de Red** integrado directamente sobre el plano esquemático interactivo (SVG), con persistencia garantizada en base de datos (`UserNetworkEditLayer`) y archivo desacoplado local (`cartografia/user_network_edits.json`).

### 1. Capacidades del Editor Visual

1. **Agregar Estaciones (`POST /api/stations/create/`)**:
   - Creación visual haciendo clic directamente sobre el lienzo cartográfico (modo `＋ Estación`) o mediante formulario modal.
   - Parámetros completos de ingeniería civil (subterráneo, túnel profundo, superficial, elevado), estado operativo y andenes.
   - **Soporte para Estaciones Huérfanas**: Si una estación se crea sin líneas asociadas, el motor la renderiza con trazo discontinuo neutral (`.svg-station-node.orphan`), totalmente seleccionable, arrastrable y lista para ser conectada a cualquier línea posterior.
2. **Agregar Correspondencias (`POST /api/correspondences/create/`)**:
   - Enlace de estaciones existentes con nuevas líneas o unificación de nodos de transbordo.
   - Sincronización automática de `is_transfer=True` y actualización del indicador de correspondencias (`correspondences_text`).
   - **Validación de Transferencias Intra-línea**: Bloquea con código HTTP `400 Bad Request` cualquier intento de conectar una estación consigo misma o con una línea que ya la opera (`"No se puede crear correspondencia entre la misma línea"`).
3. **Modificar Trazos de Línea y Waypoints (`POST /api/line-segments/<id>/waypoints/`)**:
   - Edición de trazados arrastrando vértices y waypoints directamente sobre la línea en el lienzo.
   - Inserción interactiva de nuevos codos y curvas haciendo clic sobre cualquier tramo en Modo Edición.
   - Pila completa de **Deshacer (`Ctrl+Z`)** y **Rehacer (`Ctrl+Y`)** para cualquier movimiento o edición.
   - **Regla de 2 Estaciones Mínimas**: Intentar reducir el trayecto de una línea a menos de 2 estaciones es bloqueado con HTTP `400 Bad Request` (`"Una línea debe conservar al menos 2 estaciones."`).
4. **Agregar Nuevas Líneas y Tramos (`POST /api/lines/create/`, `POST /api/line-segments/create/`)**:
   - Creación de líneas completas con código único (validación estricta de unicidad), nombre oficial, color hexadecimal y tipología (`metro` o `bus_articulado`).
   - **Soporte para Líneas en Planificación**: Líneas con 0 estaciones se visualizan adecuadamente en el directorio (`0 est. · En planificación`) y el motor de simulación cinemática las omite sin provocar excepciones.
   - **Prevención de Tramos Duplicados**: Si se intenta crear un tramo directo entre dos estaciones que ya están directamente conectadas en esa línea, la API rechaza la solicitud con HTTP `400 Bad Request` (`"Ya existe un tramo directo entre estas estaciones en la línea"`).
5. **Persistencia Desacoplada de Ediciones**:
   - Los datos base del proyecto provienen de `cartografia/red_metro.json` (solo lectura).
   - Todas las creaciones y modificaciones de usuario se persisten en la tabla `UserNetworkEditLayer` (SQLite) y se exportan automáticamente a `cartografia/user_network_edits.json`.
   - **Protección contra Pérdida de Datos en Reinicios**: La función `seed_database(force_reset=False)` detecta la existencia de líneas y omite cualquier sobreescritura, garantizando que recargas del navegador, reinicios del proceso `runserver` o actualizaciones del código base conserven intactas las estaciones y líneas de usuario.

---

## Ejecución de Pruebas Automatizadas

El proyecto incluye una suite integral de pruebas unitarias y de integración que valida todos los requisitos y casos de esquina:

```powershell
.\.venv\Scripts\python.exe manage.py test network
```

La suite cubre:
- Coherencia topológica maestra (34 líneas, 828 estaciones únicas, Santa Mónica, Línea A, Línea C).
- Endpoints JSON, SVG y Logo oficial.
- Creación de estaciones y soporte de estaciones huérfanas.
- Creación de líneas, unicidad de código y soporte de líneas en planificación.
- Prevención de tramos duplicados en líneas.
- Relevamiento de correspondencias y rechazo de transferencias intra-línea.
- Conservación obligatoria de al menos 2 estaciones por trayecto.
- Persistencia de datos de usuario tras llamadas a `seed_database(force_reset=False)`.
