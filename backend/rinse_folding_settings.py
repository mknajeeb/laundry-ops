"""Tenant folding performance benchmarks (system_settings)."""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists

KEY_BAGS_PER_HOUR = "rinse_folding_bags_per_hour_target"
KEY_LBS_PER_HOUR = "rinse_folding_lbs_per_hour_target"
DEFAULT_BAGS_PER_HOUR = 2.5
DEFAULT_LBS_PER_HOUR = 40.0


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


def get_rinse_folding_benchmarks(cursor, organization_id: int) -> dict[str, float]:
    org = int(organization_id)
    return {
        "bags_per_hour_target": _float_setting(
            _get_setting(cursor, org, KEY_BAGS_PER_HOUR), DEFAULT_BAGS_PER_HOUR
        ),
        "lbs_per_hour_target": _float_setting(
            _get_setting(cursor, org, KEY_LBS_PER_HOUR), DEFAULT_LBS_PER_HOUR
        ),
    }


def put_rinse_folding_benchmarks(
    cursor, organization_id: int, *, bags_per_hour: float | None, lbs_per_hour: float | None
) -> dict[str, float]:
    org = int(organization_id)
    if bags_per_hour is not None:
        _set_setting(cursor, org, KEY_BAGS_PER_HOUR, str(bags_per_hour))
    if lbs_per_hour is not None:
        _set_setting(cursor, org, KEY_LBS_PER_HOUR, str(lbs_per_hour))
    return get_rinse_folding_benchmarks(cursor, org)
