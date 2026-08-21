"""公交文旅潮汐客流预测与弹性调度智能体 HTTP 服务。"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import database, repository
from .engine import LINES, SCENARIOS, SPOT_BY_ID, SPOTS, forecast, generate_actions, metrics_for, snapshot
from .schemas import ExportCreate, ScenarioName, SimulationCreate, SimulationStatus
from .settings import load_settings


APP_DIR = FilePath(__file__).resolve().parent
APP_VERSION = "1.1.0"
logger = logging.getLogger("bus_agent")

SimulationId = Annotated[
    str,
    Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$", description="推演记录 ID"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_settings()  # 启动时尽早暴露无效配置。
    database.init_db()
    yield


app = FastAPI(
    title="公交文旅智能体 API",
    description="潮汐客流预测、弹性调度、指令下发和闭环评估服务",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1_000)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.middleware("http")
async def request_guard_and_headers(request: Request, call_next):
    """限制明显异常请求，并为所有响应附加基础安全头和请求 ID。"""

    settings = load_settings()
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id
        if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_request_id)
        else uuid4().hex
    )

    def finalize(response):
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            body_size = int(content_length)
        except ValueError:
            return finalize(JSONResponse(status_code=400, content={"detail": "Content-Length 无效"}))
        if body_size < 0:
            return finalize(JSONResponse(status_code=400, content={"detail": "Content-Length 无效"}))
        if body_size > settings.max_request_bytes:
            return finalize(JSONResponse(status_code=413, content={"detail": "请求体过大"}))

    response = await call_next(request)
    return finalize(response)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "location": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数校验失败", "errors": errors},
    )


@app.exception_handler(repository.DataCorruptionError)
async def corrupt_data_handler(_: Request, exc: repository.DataCorruptionError) -> JSONResponse:
    logger.error("数据库记录损坏", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"detail": "推演记录数据异常，请联系管理员"})


@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(_: Request, exc: sqlite3.Error) -> JSONResponse:
    logger.error("SQLite 操作失败", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=503, content={"detail": "数据服务暂不可用，请稍后重试"})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("未处理的服务异常", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"detail": "服务内部异常，请稍后重试"})


def _require_simulation(simulation_id: str) -> dict:
    detail = repository.get_simulation(simulation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="推演记录不存在")
    return detail


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(APP_DIR / "templates" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health() -> dict:
    with database.connect() as connection:
        connection.execute("SELECT 1").fetchone()
    return {
        "status": "ok",
        "database": "sqlite",
        "service": "bus-tourism-agent",
        "version": APP_VERSION,
        "checked_at": utc_now(),
    }


@app.get("/api/config")
def config() -> dict:
    settings = load_settings()
    return {
        "api_version": APP_VERSION,
        "scenarios": SCENARIOS,
        "spots": SPOTS,
        "lines": LINES,
        "map": {
            "bounds": [[24.70, 110.20], [25.36, 110.57]],
            "tile_url": settings.map_tile_url,
            # Leaflet 会把 attribution 当作 HTML；环境变量必须先转义。
            "tile_attribution": html.escape(settings.map_tile_attribution),
            "max_zoom": settings.map_max_zoom,
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
def get_forecast(
    spot_id: str = Query(default="xs", min_length=2, max_length=16),
    scenario: ScenarioName = "peak",
) -> dict:
    if spot_id not in SPOT_BY_ID:
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
    return repository.create_simulation(
        simulation_id=simulation_id,
        scenario=payload.scenario,
        hour=payload.hour,
        spot_id=payload.spot_id,
        current_snapshot=current_snapshot,
        actions=actions,
        metrics=metrics,
        created_at=created_at,
    )


@app.get("/api/simulations")
def list_simulations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    scenario: ScenarioName | None = None,
    status: SimulationStatus | None = None,
) -> dict:
    return repository.list_simulations(
        limit=limit,
        offset=offset,
        scenario=scenario,
        status=status,
    )


@app.get("/api/simulations/{simulation_id}")
def get_simulation(simulation_id: SimulationId) -> dict:
    return _require_simulation(simulation_id)


@app.post("/api/simulations/{simulation_id}/dispatch")
def dispatch_simulation(simulation_id: SimulationId) -> dict:
    detail = repository.dispatch_simulation(simulation_id, utc_now())
    if detail is None:
        raise HTTPException(status_code=404, detail="推演记录不存在")
    return detail


@app.post("/api/simulations/{simulation_id}/evaluate")
def evaluate_simulation(simulation_id: SimulationId) -> dict:
    try:
        detail = repository.evaluate_simulation(simulation_id, utc_now())
    except repository.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="推演记录不存在")
    return detail


@app.post("/api/simulations/{simulation_id}/exports", status_code=201)
def log_export(simulation_id: SimulationId, payload: ExportCreate | None = None) -> dict:
    export_format = payload.format if payload else "print"
    exported_at = utc_now()
    if not repository.log_export(simulation_id, export_format, exported_at):
        raise HTTPException(status_code=404, detail="推演记录不存在")
    return {"simulation_id": simulation_id, "format": export_format, "exported_at": exported_at}
