"""
Pruebas Unitarias para el Algoritmo de Orientación de Nombres de Estación (SMyT).
Verifica:
1. Trazados horizontales puros o dominantes (|dx| >= 2*|dy|): texto arriba/abajo.
2. Trazados verticales puros o dominantes (|dy| >= 2*|dx|): texto derecha/izquierda.
3. Trazados diagonales (múltiplos de 45°): texto orientado a ±45°.
4. Nodos aislados sin vecinos.
Ejecutable con: pytest -k label_orientation
"""

import pytest
from network.label_orientation import calculate_station_label_orientation


@pytest.mark.unit
class TestLabelOrientation:
    """Suite de validación de posicionamiento y orientación de rótulos de estación."""

    def test_horizontal_track_label_top_and_bottom_label_orientation(self):
        """Verifica que un tramo horizontal ubique la etiqueta centrada horizontalmente arriba o abajo."""
        st = [1000.0, 1000.0]
        prev_st = [800.0, 1000.0]
        next_st = [1200.0, 1000.0]

        res_top = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st)
        assert res_top["orientation"] == "horizontal"
        assert res_top["placement"] == "top"
        assert res_top["offset_x"] == 0.0
        assert res_top["offset_y"] == -14.0
        assert res_top["text_anchor"] == "middle"
        assert res_top["angle_deg"] == 0.0

        res_bottom = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st, preferred_side="bottom")
        assert res_bottom["placement"] == "bottom"
        assert res_bottom["offset_y"] == 18.0

    def test_vertical_track_label_right_and_left_label_orientation(self):
        """Verifica que un tramo vertical ubique la etiqueta alineada a la derecha o izquierda."""
        st = [1000.0, 1000.0]
        prev_st = [1000.0, 800.0]
        next_st = [1000.0, 1200.0]

        res_right = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st)
        assert res_right["orientation"] == "vertical"
        assert res_right["placement"] == "right"
        assert res_right["offset_x"] == 16.0
        assert res_right["offset_y"] == 4.0
        assert res_right["text_anchor"] == "start"
        assert res_right["angle_deg"] == 0.0

        res_left = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st, preferred_side="left")
        assert res_left["placement"] == "left"
        assert res_left["offset_x"] == -16.0
        assert res_left["text_anchor"] == "end"

    def test_diagonal_southeast_track_label_orientation(self):
        """Verifica tramo diagonal a 45° con pendiente positiva en pantalla (dx > 0, dy > 0)."""
        st = [1000.0, 1000.0]
        prev_st = [850.0, 850.0]
        next_st = [1150.0, 1150.0]

        res = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st)
        assert res["orientation"] == "diagonal_se"
        assert res["placement"] == "diagonal_top_right"
        assert res["offset_x"] == 14.0
        assert res["offset_y"] == -10.0
        assert res["text_anchor"] == "start"
        assert res["angle_deg"] == -45.0

    def test_diagonal_northeast_track_label_orientation(self):
        """Verifica tramo diagonal a 45° con pendiente negativa en pantalla (dx > 0, dy < 0)."""
        st = [1000.0, 1000.0]
        prev_st = [850.0, 1150.0]
        next_st = [1150.0, 850.0]

        res = calculate_station_label_orientation(st, prev_coords=prev_st, next_coords=next_st)
        assert res["orientation"] == "diagonal_ne"
        assert res["placement"] == "diagonal_bottom_right"
        assert res["offset_x"] == 14.0
        assert res["offset_y"] == 14.0
        assert res["text_anchor"] == "start"
        assert res["angle_deg"] == 45.0

    def test_isolated_node_label_orientation(self):
        """Verifica que un nodo aislado sin paradas previas ni posteriores tome el valor por defecto."""
        st = [2000.0, 2000.0]
        res = calculate_station_label_orientation(st)
        assert res["orientation"] == "isolated"
        assert res["placement"] == "top"
        assert res["offset_y"] == -14.0
        assert res["angle_deg"] == 0.0
