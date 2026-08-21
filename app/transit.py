"""桂林真实公交线路快照的加载、校验与查询。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import load_settings


class TransitDataError(RuntimeError):
    """公交线路快照缺失或结构无效。"""


def _coordinate(point: Any, route_id: str) -> list[float]:
    if not isinstance(point, list) or len(point) != 2:
        raise TransitDataError(f"线路 {route_id} 存在无效坐标")
    latitude, longitude = point
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        raise TransitDataError(f"线路 {route_id} 坐标必须是数值")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise TransitDataError(f"线路 {route_id} 坐标超出范围")
    return [float(latitude), float(longitude)]


def _route(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TransitDataError("公交线路必须是对象")
    route_id = value.get("id")
    if not isinstance(route_id, str) or not route_id.startswith("osm-"):
        raise TransitDataError("公交线路 ID 无效")
    required_text = ("ref", "name", "from", "to", "operator", "color")
    for field in required_text:
        if not isinstance(value.get(field), str):
            raise TransitDataError(f"线路 {route_id} 字段 {field} 无效")

    raw_paths = value.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise TransitDataError(f"线路 {route_id} 缺少道路几何")
    paths: list[list[list[float]]] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, list) or len(raw_path) < 2:
            continue
        paths.append([_coordinate(point, route_id) for point in raw_path])
    if not paths:
        raise TransitDataError(f"线路 {route_id} 没有可绘制路径")

    animation_path = value.get("animation_path")
    if not isinstance(animation_path, list) or len(animation_path) < 2:
        animation_path = max(paths, key=len)
    else:
        animation_path = [_coordinate(point, route_id) for point in animation_path]

    result = dict(value)
    result["paths"] = paths
    result["animation_path"] = animation_path
    result["stops"] = value.get("stops") if isinstance(value.get("stops"), list) else []
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TransitDataError(f"公交线路快照不存在：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise TransitDataError("公交线路快照无法读取") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("routes"), list):
        raise TransitDataError("公交线路快照结构无效")
    routes = [_route(route) for route in payload["routes"]]
    if not routes:
        raise TransitDataError("公交线路快照为空")
    result = dict(payload)
    result["routes"] = routes
    result["route_count"] = len(routes)
    return result


@lru_cache(maxsize=4)
def _load_cached(path_text: str) -> dict[str, Any]:
    return _load(Path(path_text))


def load_routes() -> dict[str, Any]:
    path = load_settings().transit_route_data_path
    return _load_cached(str(path))


def list_routes(refs: set[str] | None = None) -> dict[str, Any]:
    payload = load_routes()
    routes = payload["routes"]
    if refs:
        routes = [route for route in routes if route["ref"] in refs]
    return {
        "source": payload.get("source"),
        "source_url": payload.get("source_url"),
        "license": payload.get("license"),
        "attribution": payload.get("attribution"),
        "osm_base_timestamp": payload.get("osm_base_timestamp"),
        "generated_at": payload.get("generated_at"),
        "bbox": payload.get("bbox"),
        "is_realtime_gps": False,
        "trajectory_mode": "simulated_on_real_route_geometry",
        "count": len(routes),
        "total": len(payload["routes"]),
        "items": routes,
    }


def get_route(route_id: str) -> dict[str, Any] | None:
    return next((route for route in load_routes()["routes"] if route["id"] == route_id), None)
