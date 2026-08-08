"""Organization-scoped Shift Capacity Planner parameter persistence.

Storage: system_settings JSON key shift_capacity_planner_params_v1
(same org settings path as weekly-schedule display / processing settings).
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from backend.ta_helpers import table_exists

KEY_PLANNER_PARAMS = "shift_capacity_planner_params_v1"

# Fields persisted for management planner Plan + Process strips.
# Staffing intervals and temporary simulation output are not included.
PERSISTED_KEYS = (
    "bag_count",
    "start_time",
    "target_time",
    "planning_block_size_min",
    "washer_count",
    "dryer_count",
    "weigh_sec_per_bag",
    "sort_min_per_bag",
    "load_washer_min",
    "wash_cycle_min",
    "load_dryer_min",
    "dry_cycle_min",
    "fold_min_per_bag",
)

DEFAULT_PLANNER_PARAMS: dict[str, Any] = {
    "bag_count": 50,
    "start_time": "9:00 AM",
    "target_time": "3:00 PM",
    "planning_block_size_min": 60,
    "washer_count": 4,
    "dryer_count": 4,
    "weigh_sec_per_bag": 45,
    "sort_min_per_bag": 5,
    "load_washer_min": 3,
    "wash_cycle_min": 30,
    "load_dryer_min": 3,
    "dry_cycle_min": 45,
    "fold_min_per_bag": 6,
}


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def _strict_clock_seconds(raw: Any) -> int | None:
    """Parse clock text; return None if invalid (no silent default)."""
    if raw is None:
        return None
    text = str(raw).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$", text, re.I)
    if not m:
        return None
    h = int(m.group(1))
    minute = int(m.group(2))
    sec = int(m.group(3) or 0)
    ampm = m.group(4).upper() if m.group(4) else None
    if minute > 59 or sec > 59:
        return None
    if ampm:
        if h < 1 or h > 12:
            return None
        if ampm == "AM":
            h = 0 if h == 12 else h
        else:
            h = 12 if h == 12 else h + 12
    elif h > 23:
        return None
    return h * 3600 + minute * 60 + sec


def _positive_int(raw: Any, name: str, *, minimum: int = 1) -> int:
    try:
        n = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number") from exc
    if n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


def _non_negative_number(raw: Any, name: str) -> float:
    try:
        n = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if n < 0:
        raise ValueError(f"{name} must be >= 0")
    return n


def validate_planner_params(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize persisted planner params. Raises ValueError on failure."""
    src = dict(DEFAULT_PLANNER_PARAMS)
    if isinstance(data, Mapping):
        for key in PERSISTED_KEYS:
            if key in data and data[key] is not None and data[key] != "":
                src[key] = data[key]

    bag_count = _positive_int(src["bag_count"], "bag_count", minimum=1)
    start_raw = str(src["start_time"]).strip()
    target_raw = str(src["target_time"]).strip()
    start_sec = _strict_clock_seconds(start_raw)
    target_sec = _strict_clock_seconds(target_raw)
    if start_sec is None:
        raise ValueError("start_time is invalid")
    if target_sec is None:
        raise ValueError("target_time is invalid")
    if target_sec <= start_sec:
        raise ValueError("target_time must be after start_time")

    block = _positive_int(src["planning_block_size_min"], "planning_block_size_min", minimum=1)
    if block not in (30, 45, 60):
        raise ValueError("planning_block_size_min must be 30, 45, or 60")

    washer_count = _positive_int(src["washer_count"], "washer_count", minimum=1)
    dryer_count = _positive_int(src["dryer_count"], "dryer_count", minimum=1)

    weigh_sec = _non_negative_number(src["weigh_sec_per_bag"], "weigh_sec_per_bag")
    if weigh_sec <= 0:
        raise ValueError("weigh_sec_per_bag must be > 0")
    sort_min = _non_negative_number(src["sort_min_per_bag"], "sort_min_per_bag")
    load_washer = _non_negative_number(src["load_washer_min"], "load_washer_min")
    wash_cycle = _non_negative_number(src["wash_cycle_min"], "wash_cycle_min")
    if wash_cycle <= 0:
        raise ValueError("wash_cycle_min must be > 0")
    load_dryer = _non_negative_number(src["load_dryer_min"], "load_dryer_min")
    dry_cycle = _non_negative_number(src["dry_cycle_min"], "dry_cycle_min")
    if dry_cycle <= 0:
        raise ValueError("dry_cycle_min must be > 0")
    fold_min = _non_negative_number(src["fold_min_per_bag"], "fold_min_per_bag")

    return {
        "bag_count": bag_count,
        "start_time": start_raw,
        "target_time": target_raw,
        "planning_block_size_min": block,
        "washer_count": washer_count,
        "dryer_count": dryer_count,
        "weigh_sec_per_bag": weigh_sec if weigh_sec != int(weigh_sec) else int(weigh_sec),
        "sort_min_per_bag": sort_min if sort_min != int(sort_min) else int(sort_min),
        "load_washer_min": load_washer if load_washer != int(load_washer) else int(load_washer),
        "wash_cycle_min": wash_cycle if wash_cycle != int(wash_cycle) else int(wash_cycle),
        "load_dryer_min": load_dryer if load_dryer != int(load_dryer) else int(load_dryer),
        "dry_cycle_min": dry_cycle if dry_cycle != int(dry_cycle) else int(dry_cycle),
        "fold_min_per_bag": fold_min if fold_min != int(fold_min) else int(fold_min),
    }


def get_shift_capacity_planner_settings(cursor, organization_id: int) -> dict[str, Any]:
    raw = _get_setting(cursor, int(organization_id), KEY_PLANNER_PARAMS)
    if not raw:
        return dict(DEFAULT_PLANNER_PARAMS)
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return dict(DEFAULT_PLANNER_PARAMS)
    if not isinstance(parsed, dict):
        return dict(DEFAULT_PLANNER_PARAMS)
    try:
        return validate_planner_params(parsed)
    except ValueError:
        # Corrupt/partial row → safe defaults (do not write back here).
        return dict(DEFAULT_PLANNER_PARAMS)


def save_shift_capacity_planner_settings(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate then persist. On validation failure, raises without writing."""
    normalized = validate_planner_params(data or {})
    _set_setting(
        cursor,
        int(organization_id),
        KEY_PLANNER_PARAMS,
        json.dumps(normalized),
    )
    return normalized
