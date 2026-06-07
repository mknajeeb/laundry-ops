"""Payroll planning maintenance extras (JSON in system_settings) + org rule fields."""

from __future__ import annotations

import json
from typing import Any

from backend.ta_helpers import json_safe, table_exists, table_has_column

KEY_SCHEDULING_EXTRAS = "payroll_scheduling_rules_extras_v1"
KEY_FORECAST_ASSUMPTIONS = "payroll_forecast_assumptions_v1"
KEY_BAG_VOLUME_FORECAST = "payroll_bag_volume_forecast_v1"
KEY_MACHINE_CAPACITY = "payroll_machine_capacity_v1"

DEFAULT_SCHEDULING_EXTRAS = {
    "late_grace_minutes": 10,
    "missing_grace_minutes": 15,
    "default_break_paid": False,
    "max_scheduled_days_per_week": 6,
    "balanced_hours_min": 24,
    "balanced_hours_max": 36,
}

DEFAULT_FORECAST_ASSUMPTIONS = {
    "average_rinse_bag_weight_lbs": None,
    "folding_bags_per_hour": None,
    "folding_pounds_per_hour": None,
    "weighing_minutes_per_bag": None,
    "sorting_minutes_per_bag": None,
    "washing_handling_minutes_per_bag": None,
    "drying_handling_minutes_per_bag": None,
    "target_labor_cost_percent": None,
    "notes": "Deprecated — use bag_volume_forecast.role_speed_parameters.",
}

def _default_bag_volume_forecast():
    from backend.payroll_bag_volume_forecast import DEFAULT_BAG_VOLUME_FORECAST

    return dict(DEFAULT_BAG_VOLUME_FORECAST)

DEFAULT_MACHINE_CAPACITY = {
    "washers": [],
    "dryers": [],
    "notes": "Phase 2 — machine capacity planning not active yet.",
}


def _cursor(conn):
    return conn.cursor(dictionary=True)


def _get_json_setting(conn, organization_id: int, key: str, default: dict) -> dict:
    c = _cursor(conn)
    if not table_exists(c, "system_settings"):
        return dict(default)
    c.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = c.fetchone()
    if not row or not row.get("svalue"):
        return dict(default)
    try:
        parsed = json.loads(row["svalue"])
        if isinstance(parsed, dict):
            out = dict(default)
            out.update(parsed)
            return out
    except Exception:
        pass
    return dict(default)


def _set_json_setting(conn, organization_id: int, key: str, data: dict) -> None:
    cur = conn.cursor()
    if not table_exists(cur, "system_settings"):
        return
    cur.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, json.dumps(data)),
    )


def ensure_planning_optional_columns(cursor) -> None:
    """Optional notes / role_group on planning lookup tables."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    alters = [
        ("payroll_shifts", "notes", "TEXT NULL"),
        ("payroll_roles", "role_group", "VARCHAR(64) NULL"),
        ("payroll_work_streams", "notes", "TEXT NULL"),
    ]
    for table, col, ddl in alters:
        if table_exists(c, table) and not table_has_column(c, table, col):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def get_planning_maintenance_extras(conn, organization_id: int) -> dict[str, Any]:
    from backend.payroll_bag_volume_forecast import merge_legacy_forecast_assumptions, validate_bag_volume_forecast

    ensure_planning_optional_columns(conn.cursor())
    legacy_forecast = _get_json_setting(conn, organization_id, KEY_FORECAST_ASSUMPTIONS, DEFAULT_FORECAST_ASSUMPTIONS)
    bag_raw = _get_json_setting(conn, organization_id, KEY_BAG_VOLUME_FORECAST, _default_bag_volume_forecast())
    bag_volume = merge_legacy_forecast_assumptions(bag_raw, legacy_forecast)
    validation_errors = validate_bag_volume_forecast(bag_volume)
    return json_safe(
        {
            "scheduling_rules": _get_json_setting(conn, organization_id, KEY_SCHEDULING_EXTRAS, DEFAULT_SCHEDULING_EXTRAS),
            "forecast_assumptions": legacy_forecast,
            "bag_volume_forecast": bag_volume,
            "bag_volume_forecast_validation_errors": validation_errors,
            "machine_capacity": _get_json_setting(conn, organization_id, KEY_MACHINE_CAPACITY, DEFAULT_MACHINE_CAPACITY),
        }
    )


def save_planning_maintenance_extras(conn, organization_id: int, body: dict) -> dict[str, Any]:
    from backend.payroll_bag_volume_forecast import validate_bag_volume_forecast

    oid = int(organization_id)
    if "scheduling_rules" in body:
        _set_json_setting(conn, oid, KEY_SCHEDULING_EXTRAS, body["scheduling_rules"])
    if "forecast_assumptions" in body:
        _set_json_setting(conn, oid, KEY_FORECAST_ASSUMPTIONS, body["forecast_assumptions"])
    if "bag_volume_forecast" in body:
        errors = validate_bag_volume_forecast(body["bag_volume_forecast"])
        if errors:
            raise ValueError("; ".join(errors))
        _set_json_setting(conn, oid, KEY_BAG_VOLUME_FORECAST, body["bag_volume_forecast"])
    if "machine_capacity" in body:
        _set_json_setting(conn, oid, KEY_MACHINE_CAPACITY, body["machine_capacity"])
    return get_planning_maintenance_extras(conn, oid)
