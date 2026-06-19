"""Org-scoped washer/dryer rack capacity settings (system_settings JSON)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.ta_helpers import table_exists

KEY_MACHINE_RACK_CONFIG = "machine_rack_config"

DEFAULT_WASHER_CAPACITIES: dict[str, float] = {
    "W24-30-VW": 30.0,
    "W29-40-VW": 40.0,
    "W28-20-VW": 20.0,
}

DEFAULT_DRYER_CAPACITIES: dict[str, float] = {
    "D4-50-VW": 50.0,
    "D8-35-VW": 35.0,
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


def _parse_positive_float(raw: Any, default: float) -> float:
    if raw is None:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if val <= 0:
        return default
    return val


def _normalize_capacity_map(
    raw: Any,
    defaults: Mapping[str, float],
) -> dict[str, float]:
    out = dict(defaults)
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        code = str(key or "").strip()
        if not code:
            continue
        out[code] = _parse_positive_float(val, out.get(code, defaults.get(code, 1.0)))
    return out


def get_machine_rack_config(cursor, organization_id: int) -> dict[str, dict[str, float]]:
    raw = _get_setting(cursor, int(organization_id), KEY_MACHINE_RACK_CONFIG)
    washers = dict(DEFAULT_WASHER_CAPACITIES)
    dryers = dict(DEFAULT_DRYER_CAPACITIES)
    if not raw:
        return {"washers": washers, "dryers": dryers}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"washers": washers, "dryers": dryers}
    if not isinstance(parsed, dict):
        return {"washers": washers, "dryers": dryers}
    washers = _normalize_capacity_map(parsed.get("washers"), DEFAULT_WASHER_CAPACITIES)
    dryers = _normalize_capacity_map(parsed.get("dryers"), DEFAULT_DRYER_CAPACITIES)
    return {"washers": washers, "dryers": dryers}


def save_machine_rack_config(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    current = get_machine_rack_config(cursor, organization_id)
    washers_in = data.get("washers")
    dryers_in = data.get("dryers")
    if isinstance(washers_in, dict):
        merged = dict(current["washers"])
        for key, val in washers_in.items():
            code = str(key or "").strip()
            if code:
                merged[code] = _parse_positive_float(val, merged.get(code, 1.0))
        current["washers"] = merged
    if isinstance(dryers_in, dict):
        merged = dict(current["dryers"])
        for key, val in dryers_in.items():
            code = str(key or "").strip()
            if code:
                merged[code] = _parse_positive_float(val, merged.get(code, 1.0))
        current["dryers"] = merged
    _set_setting(
        cursor,
        int(organization_id),
        KEY_MACHINE_RACK_CONFIG,
        json.dumps(current),
    )
    return current
