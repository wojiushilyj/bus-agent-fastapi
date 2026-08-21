"""推演记录的数据访问层。

HTTP 层不直接拼接 SQL；状态迁移在同一个 IMMEDIATE 事务内完成，以保证重复
点击或并发请求不会重复写入执行事件。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from . import database
from .engine import AGENT_EVENTS


class DataCorruptionError(RuntimeError):
    """数据库记录存在无法解析的持久化数据。"""


class InvalidTransitionError(RuntimeError):
    """推演状态不允许执行目标操作。"""


def _insert_events(
    connection: sqlite3.Connection,
    simulation_id: str,
    stages: Iterable[int],
    occurred_at: str,
) -> None:
    rows: list[tuple[Any, ...]] = []
    for stage in stages:
        events = AGENT_EVENTS.get(stage)
        if events is None:
            raise ValueError(f"未知智能体阶段：{stage}")
        rows.extend(
            (
                simulation_id,
                stage,
                event["agent"],
                event["tool"],
                event["message"],
                occurred_at,
            )
            for event in events
        )
    connection.executemany(
        """
        INSERT INTO agent_events
            (simulation_id, stage, agent_name, tool_name, message, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _decode_json(value: str, field_name: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DataCorruptionError(f"推演记录字段 {field_name} 无法解析") from exc


def _detail(connection: sqlite3.Connection, simulation_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM simulations WHERE id = ?", (simulation_id,)
    ).fetchone()
    if row is None:
        return None

    item = dict(row)
    item["metrics"] = _decode_json(item.pop("metrics_json"), "metrics_json")
    item["snapshot"] = _decode_json(item.pop("snapshot_json"), "snapshot_json")
    item["actions"] = [
        dict(action)
        for action in connection.execute(
            """
            SELECT id, sequence_no, action_type AS type, title, detail, effect,
                   line_id, basis, status, dispatched_at
            FROM dispatch_actions
            WHERE simulation_id = ?
            ORDER BY sequence_no
            """,
            (simulation_id,),
        ).fetchall()
    ]
    item["events"] = [
        dict(event)
        for event in connection.execute(
            """
            SELECT id, stage, agent_name, tool_name, message, event_status, occurred_at
            FROM agent_events
            WHERE simulation_id = ?
            ORDER BY stage, id
            """,
            (simulation_id,),
        ).fetchall()
    ]
    item["export_count"] = connection.execute(
        "SELECT COUNT(*) FROM export_logs WHERE simulation_id = ?", (simulation_id,)
    ).fetchone()[0]
    return item


def get_simulation(simulation_id: str) -> dict[str, Any] | None:
    with database.connect() as connection:
        return _detail(connection, simulation_id)


def create_simulation(
    *,
    simulation_id: str,
    scenario: str,
    hour: int,
    spot_id: str,
    current_snapshot: dict[str, Any],
    actions: list[dict[str, Any]],
    metrics: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    worst = current_snapshot["worst_line"]
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO simulations
                (id, scenario, hour, spot_id, status, alert_count, worst_line,
                 before_load, after_load, metrics_json, snapshot_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                simulation_id,
                scenario,
                hour,
                spot_id,
                current_snapshot["alert_count"],
                worst["name"],
                worst["before"],
                worst["after"],
                json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                json.dumps(current_snapshot, ensure_ascii=False, separators=(",", ":")),
                created_at,
                created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO dispatch_actions
                (simulation_id, sequence_no, action_type, title, detail, effect,
                 line_id, basis, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned')
            """,
            [
                (
                    simulation_id,
                    sequence_no,
                    action["type"],
                    action["title"],
                    action["detail"],
                    action["effect"],
                    action["line_id"],
                    action["basis"],
                )
                for sequence_no, action in enumerate(actions, start=1)
            ],
        )
        _insert_events(connection, simulation_id, (1, 2, 3), created_at)
        detail = _detail(connection, simulation_id)
    if detail is None:  # pragma: no cover - INSERT 成功后仅防御性保留。
        raise DataCorruptionError("新建推演记录后无法读取")
    return detail


def list_simulations(
    *,
    limit: int,
    offset: int,
    scenario: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    clauses: list[str] = []
    parameters: list[Any] = []
    if scenario is not None:
        clauses.append("scenario = ?")
        parameters.append(scenario)
    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    with database.connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM simulations{where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT id, scenario, hour, spot_id, status, alert_count, worst_line,
                   before_load, after_load, created_at, updated_at, dispatched_at, evaluated_at,
                   (SELECT COUNT(*) FROM dispatch_actions AS action
                    WHERE action.simulation_id = simulations.id) AS action_count
            FROM simulations
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def dispatch_simulation(simulation_id: str, dispatched_at: str) -> dict[str, Any] | None:
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM simulations WHERE id = ?", (simulation_id,)
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "planned":
            connection.execute(
                """
                UPDATE simulations
                SET status = 'dispatched', dispatched_at = ?, updated_at = ?
                WHERE id = ? AND status = 'planned'
                """,
                (dispatched_at, dispatched_at, simulation_id),
            )
            connection.execute(
                """
                UPDATE dispatch_actions
                SET status = 'dispatched', dispatched_at = ?
                WHERE simulation_id = ? AND status = 'planned'
                """,
                (dispatched_at, simulation_id),
            )
            _insert_events(connection, simulation_id, (4,), dispatched_at)
        return _detail(connection, simulation_id)


def evaluate_simulation(simulation_id: str, evaluated_at: str) -> dict[str, Any] | None:
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM simulations WHERE id = ?", (simulation_id,)
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "planned":
            raise InvalidTransitionError("请先下发调度指令")
        if row["status"] == "dispatched":
            connection.execute(
                """
                UPDATE simulations
                SET status = 'evaluated', evaluated_at = ?, updated_at = ?
                WHERE id = ? AND status = 'dispatched'
                """,
                (evaluated_at, evaluated_at, simulation_id),
            )
            connection.execute(
                """
                UPDATE dispatch_actions
                SET status = 'completed'
                WHERE simulation_id = ? AND status = 'dispatched'
                """,
                (simulation_id,),
            )
            _insert_events(connection, simulation_id, (5,), evaluated_at)
        return _detail(connection, simulation_id)


def log_export(simulation_id: str, export_format: str, exported_at: str) -> bool:
    with database.transaction() as connection:
        exists = connection.execute(
            "SELECT 1 FROM simulations WHERE id = ?", (simulation_id,)
        ).fetchone()
        if exists is None:
            return False
        connection.execute(
            "INSERT INTO export_logs (simulation_id, format, exported_at) VALUES (?, ?, ?)",
            (simulation_id, export_format, exported_at),
        )
    return True
