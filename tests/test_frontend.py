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


if __name__ == "__main__":
    unittest.main()
