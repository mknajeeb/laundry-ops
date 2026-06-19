"""Org-scoped supply usage dosage settings (system_settings JSON)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.ta_helpers import table_exists

KEY_SUPPLY_USAGE_DOSAGES = "supply_usage_dosages"

DEFAULT_DOSAGES: dict[str, float] = {
    "Tide": 2.0,
    "Downy": 1.0,
    "OxiClean": 1.0,
    "All Free & Clear": 2.0,
}

SUPPLY_DOSAGE_KEYS = tuple(DEFAULT_DOSAGES.keys())


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


def get_supply_usage_dosages(cursor, organization_id: int) -> dict[str, float]:
    raw = _get_setting(cursor, int(organization_id), KEY_SUPPLY_USAGE_DOSAGES)
    out = dict(DEFAULT_DOSAGES)
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, dict):
        return out
    for key in DEFAULT_DOSAGES:
        if key in parsed:
            out[key] = _parse_positive_float(parsed[key], DEFAULT_DOSAGES[key])
    return out


def save_supply_usage_dosages(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, float]:
    current = get_supply_usage_dosages(cursor, organization_id)
    for key in DEFAULT_DOSAGES:
        if key in data:
            current[key] = _parse_positive_float(data[key], current[key])
    _set_setting(
        cursor,
        int(organization_id),
        KEY_SUPPLY_USAGE_DOSAGES,
        json.dumps(current),
    )
    return current
