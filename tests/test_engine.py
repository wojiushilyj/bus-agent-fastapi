from __future__ import annotations

import unittest

from app.engine import forecast, generate_actions, snapshot


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


if __name__ == "__main__":
    unittest.main()
