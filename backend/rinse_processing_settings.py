"""Tenant processing time assumptions (system_settings, seconds per bag)."""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists

KEY_WEIGH = "processing_weigh_seconds_per_bag"
KEY_SORT = "processing_sort_seconds_per_bag"
KEY_WASH = "processing_wash_seconds_per_bag"
KEY_DRY = "processing_dry_seconds_per_bag"

DEFAULT_WEIGH = 30
DEFAULT_SORT = 180
DEFAULT_WASH = 120
DEFAULT_DRY = 120


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


def _int_setting(raw: Any, default: int) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return default


def get_processing_settings(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    weigh = _int_setting(_get_setting(cursor, org, KEY_WEIGH), DEFAULT_WEIGH)
    sort = _int_setting(_get_setting(cursor, org, KEY_SORT), DEFAULT_SORT)
    wash = _int_setting(_get_setting(cursor, org, KEY_WASH), DEFAULT_WASH)
    dry = _int_setting(_get_setting(cursor, org, KEY_DRY), DEFAULT_DRY)
    total = weigh + sort + wash + dry
    return {
        "processing_weigh_seconds_per_bag": weigh,
        "processing_sort_seconds_per_bag": sort,
        "processing_wash_seconds_per_bag": wash,
        "processing_dry_seconds_per_bag": dry,
        "total_seconds_per_bag": total,
        "total_minutes_per_bag": round(total / 60.0, 2),
    }


def put_processing_settings(cursor, organization_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    org = int(organization_id)
    data = payload or {}
    for key, field in (
        (KEY_WEIGH, "processing_weigh_seconds_per_bag"),
        (KEY_SORT, "processing_sort_seconds_per_bag"),
        (KEY_WASH, "processing_wash_seconds_per_bag"),
        (KEY_DRY, "processing_dry_seconds_per_bag"),
    ):
        if field in data and data[field] is not None:
            _set_setting(cursor, org, key, str(_int_setting(data[field], 0)))
    return get_processing_settings(cursor, org)
