"""Output-format checks for Q4's lightweight, reproducible figures."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image
from shapely.geometry import LineString, Polygon

from scripts.question4_visuals import save_bar_chart, save_line_chart, save_map, save_multi_panel


class TestQuestion4Visuals(unittest.TestCase):
    def test_line_chart_is_a_readable_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.png"
            save_line_chart(
                path,
                title="test front position",
                x_label="time s",
                y_label="distance m",
                series=[("case", [0, 1, 2], [0, 3, 5], "#2563eb")],
            )
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 500)
                self.assertGreater(image.height, 300)

    def test_multi_panel_exports_actual_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "panels.png"
            save_multi_panel(
                path,
                [
                    {"title": "depth", "x_label": "distance", "y_label": "m", "series": [("state", [0, 1], [0, 2], "#0ea5e9")]},
                    {"title": "velocity", "x_label": "distance", "y_label": "m/s", "series": [("state", [0, 1], [0, 4], "#dc2626")]},
                ],
            )
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 900)
                self.assertGreater(image.height, 300)

    def test_map_accepts_named_simulation_geometries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            route = LineString([(0, 0), (100, 100)])
            save_map(
                path,
                extent_geometries=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])],
                route_geometries=[route],
                simulated_geometries={"case": route},
                points={"source": (0, 0)},
                title="map test",
            )
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")

    def test_bar_chart_preserves_scenario_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.png"
            save_bar_chart(path, title="sensitivity", categories=["ref", "low", "high"], values=[5, 3, 7], y_label="km")
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 1000)


if __name__ == "__main__":
    unittest.main()
