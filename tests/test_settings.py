from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.settings import PROJECT_ROOT, load_settings


class SettingsTests(unittest.TestCase):
    def test_relative_database_path_is_resolved_from_project_root(self) -> None:
        with patch.dict(os.environ, {"BUS_AGENT_DB_PATH": "data/custom.db"}):
            settings = load_settings()
        self.assertEqual(settings.database_path, (PROJECT_ROOT / "data" / "custom.db").resolve())

    def test_invalid_tile_url_is_rejected(self) -> None:
        with patch.dict(os.environ, {"MAP_TILE_URL": "javascript:alert(1)"}):
            with self.assertRaisesRegex(ValueError, "占位符"):
                load_settings()

    def test_runtime_limits_are_bounded(self) -> None:
        with patch.dict(os.environ, {"MAX_REQUEST_BYTES": "0"}):
            with self.assertRaisesRegex(ValueError, "必须在"):
                load_settings()
