"""SQLite 连接、表结构与通用查询辅助。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .settings import load_settings


def database_path() -> Path:
    return load_settings().database_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = NORMAL")
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

CREATE INDEX IF NOT EXISTS idx_simulations_scenario_created_at
ON simulations(scenario, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_simulations_status_created_at
ON simulations(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_events_simulation
ON agent_events(simulation_id, stage, id);

CREATE INDEX IF NOT EXISTS idx_export_logs_simulation
ON export_logs(simulation_id, exported_at DESC);
"""


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        # UNIQUE(simulation_id, sequence_no) 已提供同等索引，移除旧版冗余索引。
        connection.execute("DROP INDEX IF EXISTS idx_dispatch_actions_simulation")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA user_version = 2")
        connection.execute("PRAGMA optimize")
