"""Tenant processing time assumptions (system_settings, seconds per bag)."""

from __future__ import annotations

import json
from typing import Any

from backend.ta_helpers import table_exists

DEFAULT_FACILITY_ENTRY_RACKS = ("VeeWash Dirty", "Rinse Zipvan")


def parse_facility_entry_racks(raw: Any) -> list[str]:
    if isinstance(raw, list):
        out = [str(r).strip() for r in raw if str(r).strip()]
        return out or list(DEFAULT_FACILITY_ENTRY_RACKS)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                out = [str(r).strip() for r in parsed if str(r).strip()]
                return out or list(DEFAULT_FACILITY_ENTRY_RACKS)
        except json.JSONDecodeError:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            return parts or list(DEFAULT_FACILITY_ENTRY_RACKS)
    return list(DEFAULT_FACILITY_ENTRY_RACKS)

KEY_WEIGH = "processing_weigh_seconds_per_bag"
KEY_SORT = "processing_sort_seconds_per_bag"
KEY_WASH = "processing_wash_seconds_per_bag"
KEY_DRY = "processing_dry_seconds_per_bag"
KEY_REJECT_NO_START = "reject_no_start_cleaning_minutes"
KEY_WASHING_MINUTES = "washing_minutes"
KEY_DRYING_MINUTES = "drying_minutes"
KEY_REJECT_AFTER_CREATE_ISSUE = "reject_after_create_issue_minutes"
KEY_WEIGHT_DIFFERENCE_THRESHOLD = "weight_difference_threshold_lbs"
KEY_FACILITY_ENTRY_RACKS = "facility_entry_racks"
KEY_RFV_RUSH_CUTOFF = "rfv_rush_cutoff_time_et"

DEFAULT_WEIGH = 30
DEFAULT_SORT = 180
DEFAULT_WASH = 120
DEFAULT_DRY = 120
DEFAULT_REJECT_NO_START = 30
DEFAULT_WASHING_MINUTES = 30
DEFAULT_DRYING_MINUTES = 45
DEFAULT_REJECT_AFTER_CREATE_ISSUE = 45
DEFAULT_WEIGHT_DIFFERENCE_THRESHOLD_LBS = 5.0
DEFAULT_RFV_RUSH_CUTOFF = "07:00"


def parse_rfv_rush_cutoff_time_et(raw: Any) -> tuple[str, Any] | None:
    """Parse HH:MM (or HH:MM:SS) ET cutoff. Returns (normalized HH:MM label, time) or None."""
    from datetime import datetime, time

    text = str(raw or "").strip()
    if not text:
        return None
    for fmt, n in (("%H:%M:%S", 8), ("%H:%M", 5)):
        try:
            parsed = datetime.strptime(text[:n], fmt)
            t = parsed.time()
            return t.strftime("%H:%M"), t
        except ValueError:
            continue
    return None


def resolve_rfv_rush_cutoff_setting(cursor, organization_id: int) -> dict[str, Any]:
    """Runtime RFV rush cutoff — settings value with safe default fallback."""
    from datetime import datetime

    org = int(organization_id)
    default_t = parse_rfv_rush_cutoff_time_et(DEFAULT_RFV_RUSH_CUTOFF)
    default_time = default_t[1] if default_t else datetime.strptime("07:00", "%H:%M").time()
    raw = _get_setting(cursor, org, KEY_RFV_RUSH_CUTOFF)
    if raw is None or not str(raw).strip():
        return {
            "rfv_rush_cutoff_time_et": DEFAULT_RFV_RUSH_CUTOFF,
            "rfv_rush_cutoff_source": "default",
            "cutoff_time": default_time,
            "stored_raw": None,
        }
    parsed = parse_rfv_rush_cutoff_time_et(raw)
    if parsed:
        return {
            "rfv_rush_cutoff_time_et": parsed[0],
            "rfv_rush_cutoff_source": "settings",
            "cutoff_time": parsed[1],
            "stored_raw": str(raw).strip(),
        }
    return {
        "rfv_rush_cutoff_time_et": DEFAULT_RFV_RUSH_CUTOFF,
        "rfv_rush_cutoff_source": "default",
        "cutoff_time": default_time,
        "stored_raw": str(raw).strip(),
        "rfv_rush_cutoff_invalid_stored": True,
    }


def get_rfv_rush_cutoff_time_et(cursor, organization_id: int):
    """Return cutoff as datetime.time (fallback 07:00 ET)."""
    return resolve_rfv_rush_cutoff_setting(cursor, organization_id)["cutoff_time"]


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


def _float_setting(raw: Any, default: float) -> float:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def get_processing_settings(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    weigh = _int_setting(_get_setting(cursor, org, KEY_WEIGH), DEFAULT_WEIGH)
    sort = _int_setting(_get_setting(cursor, org, KEY_SORT), DEFAULT_SORT)
    wash = _int_setting(_get_setting(cursor, org, KEY_WASH), DEFAULT_WASH)
    dry = _int_setting(_get_setting(cursor, org, KEY_DRY), DEFAULT_DRY)
    reject_no_start = _int_setting(
        _get_setting(cursor, org, KEY_REJECT_NO_START), DEFAULT_REJECT_NO_START
    )
    washing_minutes = _int_setting(
        _get_setting(cursor, org, KEY_WASHING_MINUTES), DEFAULT_WASHING_MINUTES
    )
    drying_minutes = _int_setting(
        _get_setting(cursor, org, KEY_DRYING_MINUTES), DEFAULT_DRYING_MINUTES
    )
    reject_after_issue = _int_setting(
        _get_setting(cursor, org, KEY_REJECT_AFTER_CREATE_ISSUE),
        DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    )
    weight_diff = _float_setting(
        _get_setting(cursor, org, KEY_WEIGHT_DIFFERENCE_THRESHOLD),
        DEFAULT_WEIGHT_DIFFERENCE_THRESHOLD_LBS,
    )
    facility_entry_racks = parse_facility_entry_racks(
        _get_setting(cursor, org, KEY_FACILITY_ENTRY_RACKS)
    )
    rfv_cutoff = resolve_rfv_rush_cutoff_setting(cursor, org)
    total = weigh + sort + wash + dry
    return {
        "processing_weigh_seconds_per_bag": weigh,
        "processing_sort_seconds_per_bag": sort,
        "processing_wash_seconds_per_bag": wash,
        "processing_dry_seconds_per_bag": dry,
        "reject_no_start_cleaning_minutes": reject_no_start,
        "washing_minutes": washing_minutes,
        "drying_minutes": drying_minutes,
        "reject_after_create_issue_minutes": reject_after_issue,
        "weight_difference_threshold_lbs": weight_diff,
        "facility_entry_racks": facility_entry_racks,
        "rfv_rush_cutoff_time_et": rfv_cutoff["rfv_rush_cutoff_time_et"],
        "rfv_rush_cutoff_source": rfv_cutoff["rfv_rush_cutoff_source"],
        "rfv_rush_cutoff_invalid_stored": bool(rfv_cutoff.get("rfv_rush_cutoff_invalid_stored")),
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
        (KEY_REJECT_NO_START, "reject_no_start_cleaning_minutes"),
        (KEY_WASHING_MINUTES, "washing_minutes"),
        (KEY_DRYING_MINUTES, "drying_minutes"),
        (KEY_REJECT_AFTER_CREATE_ISSUE, "reject_after_create_issue_minutes"),
        (KEY_WEIGHT_DIFFERENCE_THRESHOLD, "weight_difference_threshold_lbs"),
    ):
        if field in data and data[field] is not None:
            if field == "weight_difference_threshold_lbs":
                _set_setting(cursor, org, key, str(_float_setting(data[field], 0)))
            else:
                _set_setting(cursor, org, key, str(_int_setting(data[field], 0)))
    if "facility_entry_racks" in data and data["facility_entry_racks"] is not None:
        import json

        racks = parse_facility_entry_racks(data["facility_entry_racks"])
        _set_setting(cursor, org, KEY_FACILITY_ENTRY_RACKS, json.dumps(racks))
    if "rfv_rush_cutoff_time_et" in data and data["rfv_rush_cutoff_time_et"] is not None:
        parsed = parse_rfv_rush_cutoff_time_et(data["rfv_rush_cutoff_time_et"])
        if not parsed:
            raise ValueError(
                "Invalid Ready for Vendor Rush Cutoff Time — use HH:MM in America/New_York (e.g. 07:00)."
            )
        _set_setting(cursor, org, KEY_RFV_RUSH_CUTOFF, parsed[0])
    return get_processing_settings(cursor, org)
