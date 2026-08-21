"""运行配置解析与边界校验。

所有配置都来自环境变量。这里集中完成默认值、相对路径解析和格式校验，
避免各模块分别读取环境变量而产生不一致行为。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_TILE_ATTRIBUTION = "© OpenStreetMap contributors"


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    transit_route_data_path: Path
    map_tile_url: str
    map_tile_attribution: str
    map_max_zoom: int
    max_request_bytes: int


def _database_path(value: str | None) -> Path:
    if not value:
        return PROJECT_ROOT / "data" / "bus_agent.db"
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _project_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _tile_url(value: str | None) -> str:
    url = (value or DEFAULT_TILE_URL).strip()
    if not all(token in url for token in ("{z}", "{x}", "{y}")):
        raise ValueError("MAP_TILE_URL 必须包含 {z}、{x}、{y} 占位符")
    if url.startswith("/"):
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MAP_TILE_URL 必须是 http(s) 地址或站内绝对路径")
    return url


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def load_settings() -> Settings:
    """读取并校验当前环境配置，不缓存以便测试可临时切换数据库。"""

    attribution = os.getenv("MAP_TILE_ATTRIBUTION", DEFAULT_TILE_ATTRIBUTION).strip()
    if not attribution:
        raise ValueError("MAP_TILE_ATTRIBUTION 不能为空")
    if len(attribution) > 300:
        raise ValueError("MAP_TILE_ATTRIBUTION 不能超过 300 个字符")

    return Settings(
        database_path=_database_path(os.getenv("BUS_AGENT_DB_PATH")),
        transit_route_data_path=_project_path(
            os.getenv("TRANSIT_ROUTE_DATA_PATH"),
            PROJECT_ROOT / "app" / "data" / "guilin_bus_routes.json",
        ),
        map_tile_url=_tile_url(os.getenv("MAP_TILE_URL")),
        map_tile_attribution=attribution,
        map_max_zoom=_bounded_int("MAP_MAX_ZOOM", 19, 8, 22),
        max_request_bytes=_bounded_int("MAX_REQUEST_BYTES", 65_536, 1_024, 1_048_576),
    )
