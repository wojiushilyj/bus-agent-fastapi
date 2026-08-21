from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import database, repository
from app.engine import generate_actions, metrics_for, snapshot


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = Path(__file__).resolve().parents[1] / "data" / "test_repository.db"
        self.artifacts = [
            Path(str(self.database_path) + suffix) for suffix in ("", "-wal", "-shm")
        ]
        for artifact in self.artifacts:
            artifact.unlink(missing_ok=True)
        self.environment = patch.dict(os.environ, {"BUS_AGENT_DB_PATH": str(self.database_path)})
        self.environment.start()
        database.init_db()

    def tearDown(self) -> None:
        self.environment.stop()
        for artifact in self.artifacts:
            artifact.unlink(missing_ok=True)

    def create_record(self, simulation_id: str = "a" * 32) -> dict:
        current_snapshot = snapshot(11, "peak")
        current_snapshot["generated_at"] = "2026-08-21T03:00:00.000+00:00"
        actions = generate_actions("peak")
        return repository.create_simulation(
            simulation_id=simulation_id,
            scenario="peak",
            hour=11,
            spot_id="xs",
            current_snapshot=current_snapshot,
            actions=actions,
            metrics=metrics_for("peak", len(actions)),
            created_at="2026-08-21T03:00:00.000+00:00",
        )

    def test_create_list_and_filter(self) -> None:
        detail = self.create_record()
        self.assertEqual(detail["status"], "planned")
        self.assertEqual(len(detail["actions"]), 4)

        result = repository.list_simulations(
            limit=8, offset=0, scenario="peak", status="planned"
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["action_count"], 4)

        empty = repository.list_simulations(
            limit=8, offset=0, scenario="normal", status=None
        )
        self.assertEqual(empty["total"], 0)

    def test_transitions_are_idempotent(self) -> None:
        self.create_record()
        first_dispatch = repository.dispatch_simulation("a" * 32, "2026-08-21T03:01:00Z")
        second_dispatch = repository.dispatch_simulation("a" * 32, "2026-08-21T03:02:00Z")
        self.assertEqual(first_dispatch["status"], "dispatched")
        self.assertEqual(second_dispatch["status"], "dispatched")
        self.assertEqual(len([event for event in second_dispatch["events"] if event["stage"] == 4]), 2)

        first_evaluation = repository.evaluate_simulation("a" * 32, "2026-08-21T03:03:00Z")
        second_evaluation = repository.evaluate_simulation("a" * 32, "2026-08-21T03:04:00Z")
        self.assertEqual(first_evaluation["status"], "evaluated")
        self.assertEqual(second_evaluation["status"], "evaluated")
        self.assertEqual(len([event for event in second_evaluation["events"] if event["stage"] == 5]), 1)

    def test_evaluate_before_dispatch_is_rejected(self) -> None:
        self.create_record()
        with self.assertRaisesRegex(repository.InvalidTransitionError, "先下发"):
            repository.evaluate_simulation("a" * 32, "2026-08-21T03:03:00Z")

    def test_concurrent_dispatch_writes_one_stage_only(self) -> None:
        self.create_record()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(
                    lambda index: repository.dispatch_simulation(
                        "a" * 32, f"2026-08-21T03:0{index}:00Z"
                    ),
                    range(1, 5),
                )
            )
        self.assertTrue(all(result["status"] == "dispatched" for result in results))
        detail = repository.get_simulation("a" * 32)
        self.assertEqual(len([event for event in detail["events"] if event["stage"] == 4]), 2)

    def test_export_requires_existing_simulation(self) -> None:
        self.assertFalse(repository.log_export("f" * 32, "print", "2026-08-21T03:05:00Z"))
        self.create_record()
        self.assertTrue(repository.log_export("a" * 32, "pdf", "2026-08-21T03:05:00Z"))
        self.assertEqual(repository.get_simulation("a" * 32)["export_count"], 1)
