from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database


class DatabaseTests(unittest.TestCase):
    def test_schema_and_indexes_are_created(self) -> None:
        test_db = Path(__file__).resolve().parents[1] / "data" / "test_schema.db"
        artifacts = [Path(str(test_db) + suffix) for suffix in ("", "-wal", "-shm")]
        for artifact in artifacts:
            artifact.unlink(missing_ok=True)
        try:
            with patch.dict(os.environ, {"BUS_AGENT_DB_PATH": str(test_db)}):
                database.init_db()
                with database.connect() as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_schema WHERE type = 'table'"
                        ).fetchall()
                    }
                    indexes = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_schema WHERE type = 'index'"
                        ).fetchall()
                    }
                    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                    query_plan = " ".join(
                        row[3]
                        for row in connection.execute(
                            """
                            EXPLAIN QUERY PLAN
                            SELECT id FROM simulations
                            WHERE scenario = ?
                            ORDER BY created_at DESC
                            LIMIT 8
                            """,
                            ("peak",),
                        ).fetchall()
                    )

            self.assertTrue(
                {"simulations", "dispatch_actions", "agent_events", "export_logs"} <= tables
            )
            self.assertIn("idx_simulations_created_at", indexes)
            self.assertIn("idx_simulations_scenario_created_at", indexes)
            self.assertIn("idx_simulations_status_created_at", indexes)
            self.assertIn("idx_export_logs_simulation", indexes)
            self.assertNotIn("idx_dispatch_actions_simulation", indexes)
            self.assertEqual(schema_version, 2)
            self.assertIn("idx_simulations_scenario_created_at", query_plan)
        finally:
            for artifact in artifacts:
                artifact.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
