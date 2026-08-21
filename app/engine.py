"""客流预测、拥堵识别与弹性调度规则引擎。

当前版本以可解释规则和确定性时序模型实现原型中的业务链路。后续接入真实
GPS、刷卡、景区预约等数据时，只需要替换本模块的数据输入，API 和前端无需改版。
"""

from __future__ import annotations

import math
from typing import Any


SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {"name": "平日", "congestion_factor": 0.7, "predicted_total": 235_000},
    "peak": {"name": "旅游高峰日", "congestion_factor": 1.0, "predicted_total": 386_000},
    "event": {"name": "大型活动日", "congestion_factor": 1.25, "predicted_total": 462_000},
    "burst": {"name": "突发大客流", "congestion_factor": 1.15, "predicted_total": 418_000},
}

SPOTS: list[dict[str, Any]] = [
    {"id": "xs", "name": "象山景区", "x": 205, "y": 100, "group": "gl"},
    {"id": "ljs", "name": "两江四湖·夜游", "x": 300, "y": 135, "group": "gl"},
    {"id": "ljj", "name": "漓江/磨盘山码头", "x": 375, "y": 78, "group": "gl"},
    {"id": "ldy", "name": "芦笛岩", "x": 120, "y": 72, "group": "gl"},
    {"id": "qx", "name": "七星景区", "x": 405, "y": 165, "group": "gl"},
    {"id": "wj", "name": "靖江王城·东西巷", "x": 260, "y": 190, "group": "gl"},
    {"id": "xj", "name": "阳朔西街", "x": 330, "y": 375, "group": "ys"},
    {"id": "ylh", "name": "遇龙河", "x": 240, "y": 408, "group": "ys"},
    {"id": "sj", "name": "十里画廊", "x": 430, "y": 388, "group": "ys"},
    {"id": "xp", "name": "兴坪古镇", "x": 485, "y": 428, "group": "ys"},
]

LINES: list[dict[str, Any]] = [
    {"id": "L1", "name": "旅游专线1", "color": "#1e6fff", "spot_ids": ["xs", "ljs"]},
    {"id": "L2", "name": "阳朔环线", "color": "#00b386", "spot_ids": ["xj"]},
    {"id": "L3", "name": "跨区直通车", "color": "#ff7a45", "spot_ids": ["ljj"]},
    {"id": "L4", "name": "接驳摆渡", "color": "#7c4dff", "spot_ids": ["xj"]},
]

CONGESTION_PROFILES: list[dict[str, Any]] = [
    {"spot_id": "xs", "line_id": "L1", "peaks": [(11, 1.0), (15, 0.92)], "note": "双峰站台滞留"},
    {"spot_id": "xj", "line_id": "L2", "peaks": [(21, 1.0)], "note": "夜场返程"},
    {"spot_id": "ljj", "line_id": "L3", "peaks": [(9, 1.0), (10, 0.9)], "note": "去程集中"},
    {"spot_id": "ljs", "line_id": "L1", "peaks": [(20, 1.0)], "note": "夜游散场"},
]

FORECAST_PEAKS: dict[str, list[tuple[int, int]]] = {
    "xs": [(11, 40), (15, 38)],
    "ljs": [(20, 55)],
    "ljj": [(9, 52), (10, 46)],
    "ldy": [(10, 30), (11, 28)],
    "qx": [(14, 25), (15, 24)],
    "wj": [(16, 28), (20, 22)],
    "xj": [(21, 60)],
    "ylh": [(10, 35), (14, 38)],
    "sj": [(13, 30), (15, 32)],
    "xp": [(11, 28), (15, 26)],
}

PEAK_LABELS = {
    "xs": "11:00 / 15:00",
    "ljs": "20:00",
    "ljj": "09:00",
    "ldy": "10:00",
    "qx": "14:00",
    "wj": "16:00",
    "xj": "21:00",
    "ylh": "14:00",
    "sj": "14:00",
    "xp": "15:00",
}

SPOT_BY_ID = {item["id"]: item for item in SPOTS}
LINE_BY_ID = {item["id"]: item for item in LINES}
PROFILE_BY_SPOT = {item["spot_id"]: item for item in CONGESTION_PROFILES}


def _shape(peaks: list[tuple[int, int]], base: int = 4) -> list[int]:
    values = [float(base)] * 24
    for peak_hour, weight in peaks:
        for hour in range(24):
            distance = hour - peak_hour
            values[hour] += weight * math.exp(-(distance * distance) / 6)
    return [round(value) for value in values]


BASE_FORECASTS = {spot_id: _shape(peaks) for spot_id, peaks in FORECAST_PEAKS.items()}


def scenario_curve(base: list[int], scenario: str) -> list[int]:
    if scenario == "normal":
        return list(base)
    if scenario == "peak":
        return [round(value * 1.9) for value in base]
    if scenario == "event":
        return [round(value * (2.4 if value > 10 else 1.2) + (20 if value > 40 else 0)) for value in base]
    return [round(value * 1.2 + 150 * math.exp(-((hour - 21) ** 2) / 3)) for hour, value in enumerate(base)]


def forecast(spot_id: str, scenario: str) -> dict[str, Any]:
    base = BASE_FORECASTS[spot_id]
    selected = scenario_curve(base, scenario)
    return {
        "spot": SPOT_BY_ID[spot_id],
        "scenario": scenario,
        "scenario_name": SCENARIOS[scenario]["name"],
        "peak_label": PEAK_LABELS[spot_id],
        "peak_value": max(selected),
        "values": selected,
        "curves": {key: scenario_curve(base, key) for key in SCENARIOS},
    }


def congestion_intensity(profile: dict[str, Any], hour: int, scenario: str) -> float:
    gaussian = max(
        weight * math.exp(-((hour - peak_hour) ** 2) / 5)
        for peak_hour, weight in profile["peaks"]
    )
    multiplier = float(SCENARIOS[scenario]["congestion_factor"])
    if scenario == "burst":
        multiplier *= 1.45 if 19 <= hour <= 23 else 0.55
    return min(1.0, gaussian * multiplier)


def _line_loads(hour: int, scenario: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for line in LINES:
        max_intensity = 0.0
        for spot_id in line["spot_ids"]:
            profile = PROFILE_BY_SPOT.get(spot_id)
            if profile:
                max_intensity = max(max_intensity, congestion_intensity(profile, hour, scenario))
        before = min(1.0, 0.45 + max_intensity * 0.5)
        after = max(0.45, before - 0.20)
        result[line["id"]] = {"before": round(before, 4), "after": round(after, 4)}
    return result


def snapshot(hour: int, scenario: str) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    for profile in CONGESTION_PROFILES:
        intensity = congestion_intensity(profile, hour, scenario)
        if intensity < 0.3:
            continue
        spot = SPOT_BY_ID[profile["spot_id"]]
        line = LINE_BY_ID[profile["line_id"]]
        alerts.append(
            {
                "spot_id": spot["id"],
                "spot_name": spot["name"],
                "line_id": line["id"],
                "line_name": line["name"],
                "severity": "重度" if intensity > 0.6 else "中度",
                "intensity": round(intensity, 4),
                "note": profile["note"],
            }
        )
    alerts.sort(key=lambda item: item["intensity"], reverse=True)
    line_loads = _line_loads(hour, scenario)
    worst_line_id = max(line_loads, key=lambda line_id: line_loads[line_id]["before"])
    worst = line_loads[worst_line_id]
    return {
        "hour": hour,
        "scenario": scenario,
        "scenario_name": SCENARIOS[scenario]["name"],
        "predicted_total": SCENARIOS[scenario]["predicted_total"],
        "alerts": alerts,
        "alert_count": len(alerts),
        "line_loads": line_loads,
        "worst_line": {
            "id": worst_line_id,
            "name": LINE_BY_ID[worst_line_id]["name"],
            "before": worst["before"],
            "after": worst["after"],
            "delta": round(worst["before"] - worst["after"], 4),
        },
    }


def _daily_peak_load(line_id: str, scenario: str) -> tuple[int, float]:
    hour, load = max(
        ((hour, _line_loads(hour, scenario)[line_id]["before"]) for hour in range(24)),
        key=lambda item: item[1],
    )
    return hour, load


def generate_actions(scenario: str) -> list[dict[str, Any]]:
    peaks = {line_id: _daily_peak_load(line_id, scenario) for line_id in LINE_BY_ID}
    templates = [
        {
            "type": "区间车",
            "title": "象山—日月双塔 增开区间车",
            "detail": "发车间隔 12→6min，覆盖高饱和段",
            "effect": "+4200 人/时",
            "line_id": "L1",
            "basis_prefix": "象山站站台滞留 920 人（≥800 阈值）",
        },
        {
            "type": "接驳车",
            "title": "西街—遇龙河 接驳摆渡",
            "detail": "截流夜游返程客流，缓解主线",
            "effect": "分流 2600 人/时",
            "line_id": "L4",
            "basis_prefix": "阳朔西街夜场客流 2150 人/时，站台滞留 880 人（≥800）",
        },
        {
            "type": "快线",
            "title": "桂林↔阳朔 跨区快线",
            "detail": "按去程/回程潮汐双向加开",
            "effect": "跨区 +38%",
            "line_id": "L3",
            "basis_prefix": "跨区客流呈去程/回程潮汐特征",
        },
    ]
    actions: list[dict[str, Any]] = []
    for template in templates:
        line_id = template["line_id"]
        peak_hour, peak_load = peaks[line_id]
        if peak_load < 0.78:
            continue
        line_name = LINE_BY_ID[line_id]["name"]
        action = {key: value for key, value in template.items() if key != "basis_prefix"}
        action["basis"] = (
            f'{template["basis_prefix"]}，{line_name} {peak_hour:02d}:00 预测满载率 '
            f'<b>{round(peak_load * 100)}%</b>（≥78%）→ 触发{template["type"]}策略'
        )
        actions.append(action)
    max_peak = max(load for _, load in peaks.values())
    if max_peak >= 0.75:
        actions.append(
            {
                "type": "车辆预置",
                "title": "热点场站 车辆预置+充电",
                "detail": "新能源提前就位，避免高峰脱班",
                "effect": "就绪 100%",
                "line_id": None,
                "basis": "全日峰值满载率达到 "
                f"<b>{round(max_peak * 100)}%</b>，预测运力缺口 <b>12 标台</b> → 提前预置 + 充电",
            }
        )
    return actions


def metrics_for(scenario: str, action_count: int) -> dict[str, Any]:
    return {
        "predicted_passengers": SCENARIOS[scenario]["predicted_total"],
        "capacity_increase_percent": 42,
        "load_reduction_percent": 18,
        "average_wait_reduction_minutes": 6.5,
        "covered_spots": 11,
        "action_count": action_count,
    }


AGENT_EVENTS: dict[int, list[dict[str, str]]] = {
    1: [
        {"agent": "感知智能体", "tool": "多源数据API", "message": "汇聚景区预约、天气、GPS 与刷卡聚合数据"},
    ],
    2: [
        {"agent": "预测智能体", "tool": "潮汐预测引擎", "message": "完成分时、分线、分站客流预测与拥堵识别"},
    ],
    3: [
        {"agent": "决策智能体", "tool": "排班系统API", "message": "读取当前排班与可用运力"},
        {"agent": "决策智能体", "tool": "运力调度引擎", "message": "生成弹性调度方案"},
        {"agent": "决策智能体", "tool": "仿真回测API", "message": "完成方案下发前效果评估"},
    ],
    4: [
        {"agent": "执行智能体", "tool": "车载终端API", "message": "调度指令已下发至车载终端"},
        {"agent": "执行智能体", "tool": "调度中心大屏API", "message": "大屏运行状态已同步"},
    ],
    5: [
        {"agent": "评估智能体", "tool": "效果评估API", "message": "完成执行效果回测并形成闭环指标"},
    ],
}
