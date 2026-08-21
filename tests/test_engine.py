from __future__ import annotations

import unittest

from app.engine import LINES, SPOTS, forecast, generate_actions, metrics_for, snapshot


class EngineTests(unittest.TestCase):
    def test_peak_snapshot_has_alerts_and_reduces_load(self) -> None:
        result = snapshot(11, "peak")
        self.assertGreaterEqual(result["alert_count"], 1)
        self.assertGreater(result["worst_line"]["before"], result["worst_line"]["after"])

    def test_forecast_has_24_values(self) -> None:
        result = forecast("xs", "event")
        self.assertEqual(len(result["values"]), 24)
        self.assertEqual(set(result["curves"]), {"normal", "peak", "event", "burst"})

    def test_rules_generate_explainable_actions(self) -> None:
        actions = generate_actions("peak")
        self.assertEqual(len(actions), 4)
        self.assertTrue(all(action["basis"] for action in actions))

    def test_map_configuration_has_real_coordinates_and_routes(self) -> None:
        self.assertTrue(all(-90 <= spot["latitude"] <= 90 for spot in SPOTS))
        self.assertTrue(all(-180 <= spot["longitude"] <= 180 for spot in SPOTS))
        self.assertTrue(all(len(line["route"]) >= 2 for line in LINES))

    def test_invalid_engine_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知场景"):
            snapshot(9, "unknown")
        with self.assertRaisesRegex(ValueError, "hour"):
            snapshot(24, "peak")
        with self.assertRaisesRegex(ValueError, "未知景区"):
            forecast("missing", "peak")

    def test_metrics_match_configured_spots(self) -> None:
        metrics = metrics_for("peak", 4)
        self.assertEqual(metrics["covered_spots"], len(SPOTS))
        with self.assertRaisesRegex(ValueError, "不能为负数"):
            metrics_for("peak", -1)


if __name__ == "__main__":
    unittest.main()
