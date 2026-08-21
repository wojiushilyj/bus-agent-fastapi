from __future__ import annotations

import unittest
from pathlib import Path


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "app" / "templates" / "index.html").read_text(encoding="utf-8")
        cls.javascript = (root / "app" / "static" / "api-client.js").read_text(encoding="utf-8")

    def test_leaflet_has_integrity_and_schematic_fallback(self) -> None:
        self.assertIn("leaflet@1.9.4", self.html)
        self.assertIn("integrity=", self.html)
        self.assertIn('id="geoMap"', self.html)
        self.assertIn('id="map"', self.html)
        self.assertIn("force-schematic", self.javascript)

    def test_operational_status_and_history_are_present(self) -> None:
        self.assertIn('id="serviceText"', self.html)
        self.assertIn('id="dataTime"', self.html)
        self.assertIn('id="historyPanel"', self.html)
        self.assertIn('/api/simulations?limit=8', self.javascript)

    def test_frontend_has_timeout_and_stale_workflow_guards(self) -> None:
        self.assertIn("controller.abort()", self.javascript)
        self.assertIn("workflowSerial", self.javascript)
        self.assertIn("clearWorkflowTimers", self.javascript)
        self.assertIn('id="historyDetail"', self.html)
        self.assertIn("showHistoryDetail", self.javascript)

    def test_accessibility_and_reduced_motion_are_present(self) -> None:
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('aria-label="推演时刻"', self.html)
        self.assertIn("prefers-reduced-motion", self.html)


if __name__ == "__main__":
    unittest.main()
