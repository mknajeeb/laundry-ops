"""
Bag Volume Labor Forecast — data model + validation (Phase 1: settings only).

Calculations are NOT wired to the scheduling screen yet. Stores role-based planning
speeds and method preference for future comparison with actual performance metrics.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from backend.ta_helpers import json_safe

FORECAST_METHODS = frozenset({"planning", "actual", "compare"})
UNIT_TYPES = frozenset(
    {
        "bags_per_hour",
        "pounds_per_hour",
        "minutes_per_bag",
        "minutes_per_order",
    }
)

DEFAULT_BAG_VOLUME_FORECAST: dict[str, Any] = {
    "schema_version": 1,
    "calculations_enabled": False,
    "default_method": "compare",
    "global_defaults": {
        "average_bag_weight_lbs": 20.0,
        "target_completion": "same_day",
        "default_bag_count": 100,
        "notes": "Phase 2 — bag volume labor forecast not on scheduling screen yet.",
    },
    "role_speed_parameters": [],
    "performance_link": {
        "use_rinse_folding_productivity": True,
        "lookback_days": 30,
        "fallback_to_planning_when_no_data": True,
    },
}

# Legacy flat keys (pre-v1 forecast tab) — migrated into global_defaults on read
LEGACY_FLAT_KEYS = (
    "average_rinse_bag_weight_lbs",
    "folding_bags_per_hour",
    "folding_pounds_per_hour",
    "weighing_minutes_per_bag",
    "sorting_minutes_per_bag",
    "washing_handling_minutes_per_bag",
    "drying_handling_minutes_per_bag",
    "target_labor_cost_percent",
)


def _d(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def normalize_role_speed_parameter(row: dict) -> dict[str, Any]:
    unit = str(row.get("unit_type") or "bags_per_hour").strip()
    if unit not in UNIT_TYPES:
        unit = "bags_per_hour"
    return json_safe(
        {
            "id": row.get("id"),
            "role_id": int(row["role_id"]) if row.get("role_id") is not None else None,
            "work_stream_id": int(row["work_stream_id"]) if row.get("work_stream_id") else None,
            "role_name": row.get("role_name"),
            "work_stream_name": row.get("work_stream_name"),
            "unit_type": unit,
            "planning_speed": _d(row.get("planning_speed")),
            "active": bool(row.get("active", True)),
            "notes": (row.get("notes") or "").strip() or None,
        }
    )


def validate_bag_volume_forecast(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Forecast settings must be an object"]
    method = str(data.get("default_method") or "compare")
    if method not in FORECAST_METHODS:
        errors.append(f"default_method must be one of: {', '.join(sorted(FORECAST_METHODS))}")
    params = data.get("role_speed_parameters") or []
    if not isinstance(params, list):
        errors.append("role_speed_parameters must be a list")
        return errors
    seen: set[tuple] = set()
    for i, row in enumerate(params):
        if not isinstance(row, dict):
            errors.append(f"role_speed_parameters[{i}] must be an object")
            continue
        if not row.get("role_id"):
            errors.append(f"Row {i + 1}: role is required")
            continue
        unit = str(row.get("unit_type") or "")
        if unit not in UNIT_TYPES:
            errors.append(f"Row {i + 1}: invalid unit_type '{unit}'")
        speed = row.get("planning_speed")
        if speed is None or _d(speed) <= 0:
            errors.append(f"Row {i + 1}: planning_speed must be > 0")
        key = (int(row["role_id"]), int(row.get("work_stream_id") or 0), unit)
        if key in seen:
            errors.append(f"Duplicate parameter for role/stream/unit at row {i + 1}")
        seen.add(key)
    return errors


def merge_legacy_forecast_assumptions(
    bag_forecast: dict, legacy_flat: Optional[dict]
) -> dict[str, Any]:
    """Merge old flat forecast_assumptions into bag_volume_forecast on read."""
    out = dict(DEFAULT_BAG_VOLUME_FORECAST)
    if isinstance(bag_forecast, dict) and bag_forecast:
        out.update({k: v for k, v in bag_forecast.items() if k != "role_speed_parameters"})
        if bag_forecast.get("global_defaults"):
            gd = dict(out.get("global_defaults") or {})
            gd.update(bag_forecast["global_defaults"])
            out["global_defaults"] = gd
        if isinstance(bag_forecast.get("role_speed_parameters"), list):
            out["role_speed_parameters"] = [
                normalize_role_speed_parameter(r) for r in bag_forecast["role_speed_parameters"]
            ]
        if bag_forecast.get("performance_link"):
            pl = dict(out.get("performance_link") or {})
            pl.update(bag_forecast["performance_link"])
            out["performance_link"] = pl

    if legacy_flat:
        gd = dict(out.get("global_defaults") or {})
        if legacy_flat.get("average_rinse_bag_weight_lbs") is not None:
            gd["average_bag_weight_lbs"] = _d(legacy_flat["average_rinse_bag_weight_lbs"])
        if legacy_flat.get("notes"):
            gd.setdefault("notes", str(legacy_flat["notes"]))
        out["global_defaults"] = gd
        if not out["role_speed_parameters"] and legacy_flat.get("folding_bags_per_hour"):
            out["role_speed_parameters"] = []

    return json_safe(out)


def seed_example_parameters(role_id: int, stream_id: int, role_name: str, stream_name: str, speed: float) -> dict:
    return normalize_role_speed_parameter(
        {
            "role_id": role_id,
            "work_stream_id": stream_id,
            "role_name": role_name,
            "work_stream_name": stream_name,
            "unit_type": "bags_per_hour",
            "planning_speed": speed,
            "active": True,
        }
    )


def compute_bag_volume_forecast_placeholder(
    *,
    settings: dict,
    bag_count: int,
    method: str = "compare",
) -> dict[str, Any]:
    """
    Phase 2 entry point — returns structure only; no labor math until enabled.
    """
    if not settings.get("calculations_enabled"):
        return json_safe(
            {
                "status": "disabled",
                "message": "Bag volume labor forecast is not enabled on the scheduling screen yet. Configure role speeds in Settings → Forecast.",
                "method_requested": method,
                "bag_count": int(bag_count),
            }
        )
    return json_safe(
        {
            "status": "not_implemented",
            "message": "Calculations flag is on but engine not implemented yet.",
            "method_requested": method,
        }
    )


def compare_forecast_to_roster_placeholder(
    *,
    required_roles: list[dict],
    scheduled_summary: dict,
) -> dict[str, Any]:
    """Future: required vs scheduled people/hours/gaps per role-stream."""
    return json_safe(
        {
            "status": "placeholder",
            "required": required_roles,
            "scheduled": scheduled_summary,
            "gaps": [],
            "suggested_actions": [],
        }
    )
