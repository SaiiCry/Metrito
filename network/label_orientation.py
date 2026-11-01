"""
Módulo de Cálculo de Orientación y Posicionamiento de Etiquetas de Estación (SMyT).
Determina deterministamente la posición, desplazamiento (dx, dy), anclaje y ángulo
de los nombres de estaciones en el plano esquemático según la trayectoria del tramo:
- Tramos Horizontales: etiqueta arriba (top, dy = -14) o abajo (bottom, dy = +18).
- Tramos Verticales: etiqueta a la derecha (right, dx = +16) o a la izquierda (left, dx = -16).
- Tramos Diagonales (múltiplos de 45°): etiqueta en diagonal (dx = ±12, dy = ∓10, ángulo = ±45°).
"""

import math
from typing import Dict, Any, Optional, Tuple, Union


PointType = Union[Tuple[float, float], list]


def calculate_station_label_orientation(
    station_coords: PointType,
    prev_coords: Optional[PointType] = None,
    next_coords: Optional[PointType] = None,
    preferred_side: str = "auto",
) -> Dict[str, Any]:
    """
    Calcula la orientación y posición óptima del rótulo textual de una estación.

    Parámetros:
    - station_coords: Par [x, y] de la estación.
    - prev_coords: Par [x, y] de la estación o waypoint anterior (opcional).
    - next_coords: Par [x, y] de la estación o waypoint siguiente (opcional).
    - preferred_side: 'auto' | 'top' | 'bottom' | 'left' | 'right'.

    Retorna un diccionario con:
    - orientation: 'horizontal' | 'vertical' | 'diagonal_se' | 'diagonal_ne' | 'isolated'
    - placement: 'top' | 'bottom' | 'right' | 'left' | 'diagonal_top_right' | 'diagonal_bottom_right'
    - offset_x: float en unidades SVG
    - offset_y: float en unidades SVG
    - text_anchor: 'middle' | 'start' | 'end'
    - angle_deg: float de rotación del texto (0.0 o ±45.0)
    """
    sx = float(station_coords[0])
    sy = float(station_coords[1])

    # Si no hay vecinos, es un nodo aislado: colocar arriba por defecto
    if prev_coords is None and next_coords is None:
        return {
            "orientation": "isolated",
            "placement": "top",
            "offset_x": 0.0,
            "offset_y": -14.0,
            "text_anchor": "middle",
            "angle_deg": 0.0,
            "dx_vector": 0.0,
            "dy_vector": 0.0,
        }

    # Vector tangente direccional del tramo
    if prev_coords is not None and next_coords is not None:
        dx = float(next_coords[0]) - float(prev_coords[0])
        dy = float(next_coords[1]) - float(prev_coords[1])
    elif next_coords is not None:
        dx = float(next_coords[0]) - sx
        dy = float(next_coords[1]) - sy
    else:
        dx = sx - float(prev_coords[0])
        dy = sy - float(prev_coords[1])

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    # 1. Tramo marcadamente Horizontal (|dx| >= 2.0 * |dy|)
    if abs_dx >= 2.0 * abs_dy:
        placement = "bottom" if preferred_side == "bottom" else "top"
        offset_y = 18.0 if placement == "bottom" else -14.0
        return {
            "orientation": "horizontal",
            "placement": placement,
            "offset_x": 0.0,
            "offset_y": offset_y,
            "text_anchor": "middle",
            "angle_deg": 0.0,
            "dx_vector": round(dx, 1),
            "dy_vector": round(dy, 1),
        }

    # 2. Tramo marcadamente Vertical (|dy| >= 2.0 * |dx|)
    if abs_dy >= 2.0 * abs_dx:
        placement = "left" if preferred_side == "left" else "right"
        offset_x = -16.0 if placement == "left" else 16.0
        text_anchor = "end" if placement == "left" else "start"
        return {
            "orientation": "vertical",
            "placement": placement,
            "offset_x": offset_x,
            "offset_y": 4.0,
            "text_anchor": text_anchor,
            "angle_deg": 0.0,
            "dx_vector": round(dx, 1),
            "dy_vector": round(dy, 1),
        }

    # 3. Tramo Diagonal (proporción mixta 45°, 135°, 225°, 315°)
    # Si dx y dy tienen el mismo signo -> Pendiente positiva en pantalla (hacia abajo a la derecha, 45° SE)
    if (dx * dy) > 0:
        return {
            "orientation": "diagonal_se",
            "placement": "diagonal_top_right",
            "offset_x": 14.0,
            "offset_y": -10.0,
            "text_anchor": "start",
            "angle_deg": -45.0,
            "dx_vector": round(dx, 1),
            "dy_vector": round(dy, 1),
        }
    else:
        # Pendiente negativa en pantalla (hacia arriba a la derecha, 45° NE)
        return {
            "orientation": "diagonal_ne",
            "placement": "diagonal_bottom_right",
            "offset_x": 14.0,
            "offset_y": 14.0,
            "text_anchor": "start",
            "angle_deg": 45.0,
            "dx_vector": round(dx, 1),
            "dy_vector": round(dy, 1),
        }
