"""SQLite 连接、表结构与通用查询辅助。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "bus_agent.db"


def database_path() -> Path:
    configured = os.getenv("BUS_AGENT_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with connect() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL CHECK (scenario IN ('normal', 'peak', 'event', 'burst')),
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    spot_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'dispatched', 'evaluated')),
    alert_count INTEGER NOT NULL DEFAULT 0,
    worst_line TEXT NOT NULL,
    before_load REAL NOT NULL,
    after_load REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dispatched_at TEXT,
    evaluated_at TEXT
);

CREATE TABLE IF NOT EXISTS dispatch_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    effect TEXT NOT NULL,
    line_id TEXT,
    basis TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'dispatched', 'completed')),
    dispatched_at TEXT,
    UNIQUE (simulation_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    stage INTEGER NOT NULL CHECK (stage BETWEEN 1 AND 5),
    agent_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    message TEXT NOT NULL,
    event_status TEXT NOT NULL DEFAULT 'success',
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    format TEXT NOT NULL DEFAULT 'print',
    exported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_simulations_created_at
ON simulations(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_actions_simulation
ON dispatch_actions(simulation_id, sequence_no);

CREATE INDEX IF NOT EXISTS idx_agent_events_simulation
ON agent_events(simulation_id, stage, id);
"""


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA optimize")
