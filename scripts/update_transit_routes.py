"""从 OpenStreetMap Overpass 更新桂林重点公交线路几何快照。

默认写入 ``app/data/guilin_bus_routes.json``。运行时可使用 ``--stdout`` 仅输出
JSON，便于 CI、审查或其他构建流程接管文件写入。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "app" / "data" / "guilin_bus_routes.json"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GUILIN_BBOX = (24.90, 110.15, 25.45, 110.55)
DEFAULT_REFS = ("1", "10", "14", "16", "19", "21", "23", "24")
DEFAULT_RELATION_IDS = (
    3476169, 3475041, 3476223, 3476480, 3476481, 3476227, 3479257, 3476443,
)
COLORS = {
    "1": "#1677ff",
    "9": "#ff7a45",
    "10": "#13c2c2",
    "14": "#52c41a",
    "16": "#722ed1",
    "19": "#eb2f96",
    "21": "#fa8c16",
    "11": "#52c41a",
    "18": "#722ed1",
    "23": "#eb2f96",
    "100": "#faad14",
    "旅游观光1号线": "#f5222d",
}


def discovery_query() -> str:
    south, west, north, east = GUILIN_BBOX
    return (
        "[out:json][timeout:60];"
        f'relation["route"="bus"]({south},{west},{north},{east});'
        "out tags;"
    )


def geometry_query(relation_ids: Iterable[int]) -> str:
    identifiers = ",".join(str(identifier) for identifier in relation_ids)
    return (
        "[out:json][timeout:60];"
        f"relation(id:{identifiers})->.routes;"
        ".routes out body geom;"
    )


def _post_overpass(url: str, query: str) -> dict[str, Any]:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "GuilinBusAgentPrototype/1.2 (route snapshot updater)",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                raise
            time.sleep(3 + attempt * 5)
    raise RuntimeError("Overpass 请求重试次数耗尽")


def fetch_overpass(url: str, refs: Iterable[str]) -> dict[str, Any]:
    selected_refs = set(refs)
    if selected_refs == set(DEFAULT_REFS):
        relation_ids = list(DEFAULT_RELATION_IDS)
    else:
        discovery = _post_overpass(url, discovery_query())
        relation_ids = [
            element["id"]
            for element in discovery.get("elements", [])
            if element.get("type") == "relation"
            and element.get("tags", {}).get("ref") in selected_refs
        ]
    if not relation_ids:
        raise RuntimeError("Overpass 未发现所选桂林公交线路")
    elements: dict[tuple[str, int], dict[str, Any]] = {}
    osm3s: dict[str, Any] = {}
    skipped_relation_ids: list[int] = []
    for start in range(0, len(relation_ids)):
        if start:
            time.sleep(1)
        relation_id = relation_ids[start]
        try:
            batch = _post_overpass(url, geometry_query([relation_id]))
        except HTTPError:
            skipped_relation_ids.append(relation_id)
            continue
        osm3s = batch.get("osm3s", osm3s)
        for element in batch.get("elements", []):
            elements[(element["type"], element["id"])] = element
    return {
        "version": 0.6,
        "generator": "Overpass API",
        "osm3s": osm3s,
        "elements": list(elements.values()),
        "skipped_relation_ids": skipped_relation_ids,
    }


def _distance(a: list[float], b: list[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(point: list[float], start: list[float], end: list[float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return _distance(point, start)
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    ratio = max(0.0, min(1.0, ratio))
    projection = [start[0] + ratio * dx, start[1] + ratio * dy]
    return _distance(point, projection)


def simplify(points: list[list[float]], tolerance: float = 0.00008) -> list[list[float]]:
    """Douglas-Peucker 简化，约保留 8—10 米以上的线路转折。"""

    if len(points) <= 2:
        return points
    start, end = points[0], points[-1]
    index = 0
    maximum = 0.0
    for candidate_index in range(1, len(points) - 1):
        distance = _point_segment_distance(points[candidate_index], start, end)
        if distance > maximum:
            index = candidate_index
            maximum = distance
    if maximum <= tolerance:
        return [start, end]
    left = simplify(points[: index + 1], tolerance)
    right = simplify(points[index:], tolerance)
    return left[:-1] + right


def _member_points(member: dict[str, Any]) -> list[list[float]]:
    geometry = member.get("geometry") or []
    return [
        [round(float(point["lat"]), 6), round(float(point["lon"]), 6)]
        for point in geometry
        if "lat" in point and "lon" in point
    ]


def merge_paths(
    source_paths: list[list[list[float]]],
    tolerance: float = 0.0015,
) -> list[list[list[float]]]:
    """合并端点相邻但在 OSM 关系成员中顺序分散的道路片段。"""

    paths = [path[:] for path in source_paths]
    merged: list[list[list[float]]] = []
    while paths:
        current = paths.pop(0)
        while paths:
            candidates: list[tuple[float, int, str]] = []
            for index, candidate in enumerate(paths):
                candidates.extend(
                    (
                        (_distance(current[-1], candidate[0]), index, "tail-head"),
                        (_distance(current[-1], candidate[-1]), index, "tail-tail"),
                        (_distance(current[0], candidate[-1]), index, "head-tail"),
                        (_distance(current[0], candidate[0]), index, "head-head"),
                    )
                )
            distance, index, mode = min(candidates, key=lambda item: item[0])
            if distance > tolerance:
                break
            candidate = paths.pop(index)
            if mode == "tail-tail":
                candidate.reverse()
                mode = "tail-head"
            elif mode == "head-head":
                candidate.reverse()
                mode = "head-tail"
            if mode == "tail-head":
                current.extend(candidate[1:] if distance < 0.00001 else candidate)
            else:
                current = candidate[:-1] + current if distance < 0.00001 else candidate + current
        merged.append(current)
    return merged


def stitch_paths(members: list[dict[str, Any]]) -> list[list[list[float]]]:
    """按关系成员顺序连接道路片段，并把明显断开的支线保留为独立路径。"""

    paths: list[list[list[float]]] = []
    current: list[list[float]] = []
    for member in members:
        if member.get("type") != "way":
            continue
        segment = _member_points(member)
        if len(segment) < 2:
            continue
        if not current:
            current = segment
            continue
        distance_to_start = _distance(current[-1], segment[0])
        distance_to_end = _distance(current[-1], segment[-1])
        if min(distance_to_start, distance_to_end) <= 0.003:
            if distance_to_end < distance_to_start:
                segment.reverse()
            if _distance(current[-1], segment[0]) < 0.00001:
                current.extend(segment[1:])
            else:
                current.extend(segment)
        else:
            if len(current) >= 2:
                paths.append(simplify(current))
            current = segment
    if len(current) >= 2:
        paths.append(simplify(current))
    return [simplify(path) for path in merge_paths(paths)]


def build_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = {
        element["id"]: element
        for element in payload.get("elements", [])
        if element.get("type") == "node"
    }
    relations = [
        element
        for element in payload.get("elements", [])
        if element.get("type") == "relation" and element.get("tags", {}).get("route") == "bus"
    ]
    routes: list[dict[str, Any]] = []
    for relation in relations:
        tags = relation.get("tags", {})
        paths = stitch_paths(relation.get("members", []))
        if not paths or max(len(path) for path in paths) < 8:
            continue
        stops: list[dict[str, Any]] = []
        seen_stop_ids: set[int] = set()
        for member in relation.get("members", []):
            if member.get("type") != "node" or member.get("ref") in seen_stop_ids:
                continue
            node = nodes.get(member.get("ref"))
            if not node or "lat" not in node or "lon" not in node:
                continue
            role = member.get("role", "")
            node_tags = node.get("tags", {})
            if not (role.startswith(("stop", "platform")) or node_tags.get("highway") == "bus_stop"):
                continue
            seen_stop_ids.add(node["id"])
            stops.append(
                {
                    "osm_id": node["id"],
                    "name": node_tags.get("name") or "未命名站点",
                    "latitude": round(float(node["lat"]), 6),
                    "longitude": round(float(node["lon"]), 6),
                }
            )
        animation_path = max(paths, key=len)
        ref = tags.get("ref") or "未编号"
        routes.append(
            {
                "id": f"osm-{relation['id']}",
                "osm_relation_id": relation["id"],
                "ref": ref,
                "name": tags.get("name") or f"桂林公交 {ref}",
                "from": tags.get("from") or "",
                "to": tags.get("to") or "",
                "operator": tags.get("operator") or "桂林公交",
                "direction": tags.get("direction") or "",
                "color": tags.get("colour") or COLORS.get(ref, "#1677ff"),
                "paths": paths,
                "animation_path": animation_path,
                "stops": stops,
            }
        )
    routes.sort(key=lambda route: (route["ref"], route["from"], route["to"]))
    if not routes:
        raise RuntimeError("Overpass 未返回可用的桂林公交线路")
    osm3s = payload.get("osm3s", {})
    return {
        "type": "guilin_bus_routes",
        "source": "OpenStreetMap route relations via Overpass API",
        "source_url": "https://www.openstreetmap.org",
        "license": "Open Database License (ODbL)",
        "attribution": "© OpenStreetMap contributors",
        "osm_base_timestamp": osm3s.get("timestamp_osm_base"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": list(GUILIN_BBOX),
        "skipped_relation_ids": payload.get("skipped_relation_ids", []),
        "route_count": len(routes),
        "routes": routes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true", help="输出 JSON，不写文件")
    parser.add_argument("--refs", nargs="+", default=list(DEFAULT_REFS))
    parser.add_argument(
        "--overpass-url",
        default=os.getenv("OSM_OVERPASS_URL", DEFAULT_OVERPASS_URL),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        snapshot = build_snapshot(fetch_overpass(args.overpass_url, args.refs))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"更新公交线路失败：{exc}", file=sys.stderr)
        return 1
    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if args.stdout:
        sys.stdout.write(content)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"已写入 {args.output}，共 {snapshot['route_count']} 个方向关系")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
