"""公交文旅潮汐客流预测与弹性调度智能体 HTTP 服务。"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database
from .engine import (
    AGENT_EVENTS,
    LINES,
    SCENARIOS,
    SPOTS,
    forecast,
    generate_actions,
    metrics_for,
    snapshot,
)
from .schemas import ScenarioName, SimulationCreate


APP_DIR = Path(__file__).resolve().parent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    yield


app = FastAPI(
    title="公交文旅智能体 API",
    description="潮汐客流预测、弹性调度、指令下发和闭环评估服务",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def _insert_events(connection, simulation_id: str, stages: list[int], occurred_at: str) -> None:
    for stage in stages:
        for event in AGENT_EVENTS[stage]:
            connection.execute(
                """
                INSERT INTO agent_events
                    (simulation_id, stage, agent_name, tool_name, message, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    stage,
                    event["agent"],
                    event["tool"],
                    event["message"],
                    occurred_at,
                ),
            )


def _row_to_simulation(row) -> dict:
    item = dict(row)
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["snapshot"] = json.loads(item.pop("snapshot_json"))
    return item


def _simulation_detail(simulation_id: str) -> dict:
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM simulations WHERE id = ?", (simulation_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="推演记录不存在")
        actions = [
            dict(item)
            for item in connection.execute(
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
        events = [
            dict(item)
            for item in connection.execute(
                """
                SELECT id, stage, agent_name, tool_name, message, event_status, occurred_at
                FROM agent_events
                WHERE simulation_id = ?
                ORDER BY stage, id
                """,
                (simulation_id,),
            ).fetchall()
        ]
        export_count = connection.execute(
            "SELECT COUNT(*) FROM export_logs WHERE simulation_id = ?", (simulation_id,)
        ).fetchone()[0]
    result = _row_to_simulation(row)
    result["actions"] = actions
    result["events"] = events
    result["export_count"] = export_count
    return result


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(APP_DIR / "templates" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health() -> dict:
    with database.connect() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "sqlite", "service": "bus-tourism-agent"}


@app.get("/api/config")
def config() -> dict:
    return {
        "scenarios": SCENARIOS,
        "spots": SPOTS,
        "lines": LINES,
        "map": {
            "bounds": [[24.70, 110.20], [25.36, 110.57]],
            "tile_url": os.getenv("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
            "tile_attribution": os.getenv(
                "MAP_TILE_ATTRIBUTION",
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            ),
            "max_zoom": 19,
        },
    }


@app.get("/api/snapshot")
def get_snapshot(
    hour: int = Query(default=9, ge=0, le=23),
    scenario: ScenarioName = "peak",
) -> dict:
    result = snapshot(hour, scenario)
    result["generated_at"] = utc_now()
    return result


@app.get("/api/forecast")
def get_forecast(spot_id: str = "xs", scenario: ScenarioName = "peak") -> dict:
    if spot_id not in {spot["id"] for spot in SPOTS}:
        raise HTTPException(status_code=404, detail="景区/站点不存在")
    return forecast(spot_id, scenario)


@app.post("/api/simulations", status_code=201)
def create_simulation(payload: SimulationCreate) -> dict:
    simulation_id = uuid4().hex
    created_at = utc_now()
    current_snapshot = snapshot(payload.hour, payload.scenario)
    current_snapshot["generated_at"] = created_at
    actions = generate_actions(payload.scenario)
    metrics = metrics_for(payload.scenario, len(actions))
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
                payload.scenario,
                payload.hour,
                payload.spot_id,
                current_snapshot["alert_count"],
                worst["name"],
                worst["before"],
                worst["after"],
                json.dumps(metrics, ensure_ascii=False),
                json.dumps(current_snapshot, ensure_ascii=False),
                created_at,
                created_at,
            ),
        )
        for sequence_no, action in enumerate(actions, start=1):
            connection.execute(
                """
                INSERT INTO dispatch_actions
                    (simulation_id, sequence_no, action_type, title, detail, effect,
                     line_id, basis, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned')
                """,
                (
                    simulation_id,
                    sequence_no,
                    action["type"],
                    action["title"],
                    action["detail"],
                    action["effect"],
                    action["line_id"],
                    action["basis"],
                ),
            )
        _insert_events(connection, simulation_id, [1, 2, 3], created_at)
    return _simulation_detail(simulation_id)


@app.get("/api/simulations")
def list_simulations(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    with database.connect() as connection:
        total = connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        rows = connection.execute(
            """
            SELECT id, scenario, hour, spot_id, status, alert_count, worst_line,
                   before_load, after_load, created_at, updated_at, dispatched_at, evaluated_at,
                   (SELECT COUNT(*) FROM dispatch_actions AS action
                    WHERE action.simulation_id = simulations.id) AS action_count
            FROM simulations
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows), "total": total}


@app.get("/api/simulations/{simulation_id}")
def get_simulation(simulation_id: str) -> dict:
    return _simulation_detail(simulation_id)


@app.post("/api/simulations/{simulation_id}/dispatch")
def dispatch_simulation(simulation_id: str) -> dict:
    detail = _simulation_detail(simulation_id)
    if detail["status"] in {"dispatched", "evaluated"}:
        return detail
    dispatched_at = utc_now()
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE simulations
            SET status = 'dispatched', dispatched_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (dispatched_at, dispatched_at, simulation_id),
        )
        connection.execute(
            """
            UPDATE dispatch_actions
            SET status = 'dispatched', dispatched_at = ?
            WHERE simulation_id = ?
            """,
            (dispatched_at, simulation_id),
        )
        _insert_events(connection, simulation_id, [4], dispatched_at)
    return _simulation_detail(simulation_id)


@app.post("/api/simulations/{simulation_id}/evaluate")
def evaluate_simulation(simulation_id: str) -> dict:
    detail = _simulation_detail(simulation_id)
    if detail["status"] == "planned":
        raise HTTPException(status_code=409, detail="请先下发调度指令")
    if detail["status"] == "evaluated":
        return detail
    evaluated_at = utc_now()
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE simulations
            SET status = 'evaluated', evaluated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (evaluated_at, evaluated_at, simulation_id),
        )
        connection.execute(
            "UPDATE dispatch_actions SET status = 'completed' WHERE simulation_id = ?",
            (simulation_id,),
        )
        _insert_events(connection, simulation_id, [5], evaluated_at)
    return _simulation_detail(simulation_id)


@app.post("/api/simulations/{simulation_id}/exports", status_code=201)
def log_export(simulation_id: str) -> dict:
    _simulation_detail(simulation_id)
    exported_at = utc_now()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO export_logs (simulation_id, format, exported_at) VALUES (?, 'print', ?)",
            (simulation_id, exported_at),
        )
    return {"simulation_id": simulation_id, "format": "print", "exported_at": exported_at}
