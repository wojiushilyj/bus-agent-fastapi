from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app import transit
from scripts.update_transit_routes import build_snapshot


class TransitDataTests(unittest.TestCase):
    def test_bundled_snapshot_has_complete_guilin_routes(self) -> None:
        payload = transit.load_routes()
        self.assertEqual(payload["route_count"], 5)
        self.assertEqual({route["ref"] for route in payload["routes"]}, {"1", "10", "16", "23", "24"})
        for route in payload["routes"]:
            self.assertGreaterEqual(len(route["animation_path"]), 8)
            self.assertTrue(route["paths"])
            for latitude, longitude in route["animation_path"]:
                self.assertGreaterEqual(latitude, 24.9)
                self.assertLessEqual(latitude, 25.45)
                self.assertGreaterEqual(longitude, 110.15)
                self.assertLessEqual(longitude, 110.55)

    def test_list_filter_and_missing_route(self) -> None:
        filtered = transit.list_routes({"1", "23"})
        self.assertEqual(filtered["count"], 2)
        self.assertEqual(filtered["total"], 5)
        self.assertFalse(filtered["is_realtime_gps"])
        self.assertIsNone(transit.get_route("osm-999999999"))

    def test_invalid_coordinate_is_rejected(self) -> None:
        payload = transit.load_routes()
        invalid = json.loads(json.dumps(payload, ensure_ascii=False))
        invalid["routes"][0]["animation_path"][0] = [95, 110.2]
        path = Path(__file__).resolve().parents[1] / "data" / "test_invalid_transit.json"
        try:
            path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            with patch("app.transit.load_settings") as settings:
                settings.return_value.transit_route_data_path = path
                transit._load_cached.cache_clear()
                with self.assertRaises(transit.TransitDataError):
                    transit.load_routes()
        finally:
            transit._load_cached.cache_clear()
            path.unlink(missing_ok=True)


class TransitSnapshotBuilderTests(unittest.TestCase):
    def test_incomplete_relation_is_skipped(self) -> None:
        complete_geometry = [
            {
                "lat": 25.20 + index * 0.001,
                "lon": 110.20 + index * 0.001 + (0.0003 if index % 2 else -0.0003),
            }
            for index in range(9)
        ]
        payload = {
            "osm3s": {"timestamp_osm_base": "2026-08-21T00:00:00Z"},
            "elements": [
                {
                    "type": "relation",
                    "id": 1,
                    "tags": {"route": "bus", "ref": "1", "from": "甲", "to": "乙"},
                    "members": [{"type": "way", "ref": 10, "geometry": complete_geometry}],
                },
                {
                    "type": "relation",
                    "id": 2,
                    "tags": {"route": "bus", "ref": "2", "from": "丙", "to": "丁"},
                    "members": [
                        {
                            "type": "way",
                            "ref": 20,
                            "geometry": [
                                {"lat": 25.20, "lon": 110.20},
                                {"lat": 25.21, "lon": 110.21},
                            ],
                        }
                    ],
                },
            ],
        }
        result = build_snapshot(payload)
        self.assertEqual(result["route_count"], 1)
        self.assertEqual(result["routes"][0]["id"], "osm-1")


if __name__ == "__main__":
    unittest.main()
