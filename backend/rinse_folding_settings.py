"""Tenant folding performance benchmarks (system_settings)."""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists

KEY_BAGS_PER_HOUR = "rinse_folding_bags_per_hour_target"
KEY_LBS_PER_HOUR = "rinse_folding_lbs_per_hour_target"
KEY_MINUTES_PER_BAG = "rinse_folding_minutes_per_bag_target"
KEY_ISSUE_FREE_PERCENT = "rinse_folding_issue_free_percent_target"
KEY_WEEK_START_DAY = "rinse_folding_week_start_day"

DEFAULT_BAGS_PER_HOUR = 2.5
DEFAULT_LBS_PER_HOUR = 40.0
DEFAULT_MINUTES_PER_BAG = 24.0
DEFAULT_ISSUE_FREE_PERCENT = 98.0
DEFAULT_WEEK_START_DAY = "MONDAY"

VALID_WEEK_START_DAYS = frozenset(
    {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
)


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


def _float_setting(raw: Any, default: float) -> float:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _week_start_day_setting(raw: Any) -> str:
    val = str(raw or DEFAULT_WEEK_START_DAY).strip().upper()
    if val not in VALID_WEEK_START_DAYS:
        return DEFAULT_WEEK_START_DAY
    return val


def get_rinse_folding_benchmarks(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    bags = _float_setting(_get_setting(cursor, org, KEY_BAGS_PER_HOUR), DEFAULT_BAGS_PER_HOUR)
    lbs = _float_setting(_get_setting(cursor, org, KEY_LBS_PER_HOUR), DEFAULT_LBS_PER_HOUR)
    minutes = _float_setting(
        _get_setting(cursor, org, KEY_MINUTES_PER_BAG),
        DEFAULT_MINUTES_PER_BAG if bags <= 0 else round(60.0 / bags, 2),
    )
    return {
        "bags_per_hour_target": bags,
        "lbs_per_hour_target": lbs,
        "minutes_per_bag_target": minutes,
        "issue_free_percent_target": _float_setting(
            _get_setting(cursor, org, KEY_ISSUE_FREE_PERCENT), DEFAULT_ISSUE_FREE_PERCENT
        ),
        "week_start_day": _week_start_day_setting(_get_setting(cursor, org, KEY_WEEK_START_DAY)),
    }


def put_rinse_folding_benchmarks(
    cursor,
    organization_id: int,
    *,
    bags_per_hour: float | None = None,
    lbs_per_hour: float | None = None,
    minutes_per_bag: float | None = None,
    issue_free_percent: float | None = None,
    week_start_day: str | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    if bags_per_hour is not None:
        _set_setting(cursor, org, KEY_BAGS_PER_HOUR, str(bags_per_hour))
        if minutes_per_bag is None and bags_per_hour > 0:
            _set_setting(cursor, org, KEY_MINUTES_PER_BAG, str(round(60.0 / bags_per_hour, 2)))
    if lbs_per_hour is not None:
        _set_setting(cursor, org, KEY_LBS_PER_HOUR, str(lbs_per_hour))
    if minutes_per_bag is not None:
        _set_setting(cursor, org, KEY_MINUTES_PER_BAG, str(minutes_per_bag))
    if issue_free_percent is not None:
        _set_setting(cursor, org, KEY_ISSUE_FREE_PERCENT, str(issue_free_percent))
    if week_start_day is not None:
        _set_setting(cursor, org, KEY_WEEK_START_DAY, _week_start_day_setting(week_start_day))
    return get_rinse_folding_benchmarks(cursor, org)
