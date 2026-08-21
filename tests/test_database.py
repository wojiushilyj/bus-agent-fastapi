from __future__ import annotations

import os
import unittest
from pathlib import Path

from app import database


class DatabaseTests(unittest.TestCase):
    def test_schema_and_indexes_are_created(self) -> None:
        test_db = Path(__file__).resolve().parents[1] / "data" / "test_bus_agent.db"
        artifacts = [Path(str(test_db) + suffix) for suffix in ("", "-wal", "-shm")]
        for artifact in artifacts:
            artifact.unlink(missing_ok=True)
        previous = os.environ.get("BUS_AGENT_DB_PATH")
        os.environ["BUS_AGENT_DB_PATH"] = str(test_db)
        try:
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
            self.assertTrue({"simulations", "dispatch_actions", "agent_events", "export_logs"} <= tables)
            self.assertIn("idx_simulations_created_at", indexes)
            self.assertIn("idx_dispatch_actions_simulation", indexes)
        finally:
            if previous is None:
                os.environ.pop("BUS_AGENT_DB_PATH", None)
            else:
                os.environ["BUS_AGENT_DB_PATH"] = previous
            for artifact in artifacts:
                artifact.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
