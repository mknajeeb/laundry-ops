"""Supervisor reporting adjustments.

Original session measurements are never overwritten. Eligible time, role
reallocation, and manual rates change the reported view only.

Auto-approval does not read this module. A manual rate stored here is also
sent to the existing approval override, which keeps ``calculated_*`` intact.

Precedence for the employee-day reported rate:
1. Active employee-day manual rate. Session rates stay visible and are not compounded.
2. Otherwise each session uses its manual rate, else pounds / eligible hours,
   else the calculated rate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

ELIGIBLE_KINDS = frozenset({"eligible_interval", "eligible_duration", "eligible_percent"})
SESSION_KINDS = ELIGIBLE_KINDS | frozenset(
    {"role_reallocation", "exclude", "session_manual_rate"}
)
DAY_KINDS = frozenset({"day_manual_rate"})
ALL_KINDS = SESSION_KINDS | DAY_KINDS


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _active(rows: Sequence[Mapping[str, Any]], kind: str | None = None) -> list[Mapping[str, Any]]:
    out = []
    for row in rows or []:
        if row.get("reversed_at"):
            continue
        if kind is not None and str(row.get("kind") or "") != kind:
            continue
        out.append(row)
    return out


def validate_adjustment(body: Mapping[str, Any], session: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a normalized adjustment or raise ValueError."""
    kind = str(body.get("kind") or "").strip()
    if kind not in ALL_KINDS:
        raise ValueError("Unknown adjustment kind")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise ValueError("A reason is required")
    original_hours = _num((session or {}).get("performance_hours"))
    if original_hours is None:
        original_hours = _num((session or {}).get("session_hours"))
    original_lbs = _num((session or {}).get("total_pre_lbs"))
    if original_lbs is None:
        original_lbs = _num(body.get("original_lbs"))
    payload = {
        "kind": kind,
        "reason": reason[:255],
        "notes": (str(body.get("notes")).strip()[:2000] if body.get("notes") else None),
        "session_id": str(body.get("session_id") or "").strip() or None,
        "employee_user_id": body.get("employee_user_id"),
        "employee_name": str(body.get("employee_name") or "").strip() or None,
        "original_hours": original_hours,
        "original_rate": _num((session or {}).get("lbs_per_hour")),
        "original_lbs": original_lbs,
        "original_start": (session or {}).get("start_time"),
        "original_end": (session or {}).get("end_time"),
        "eligible_start": body.get("eligible_start") or None,
        "eligible_end": body.get("eligible_end") or None,
        "eligible_hours": _num(body.get("eligible_hours")),
        "eligible_percent": _num(body.get("eligible_percent")),
        "reallocated_role_key": (str(body.get("reallocated_role_key") or "").strip().upper() or None),
        "reallocated_hours": _num(body.get("reallocated_hours")),
        "manual_rate": _num(body.get("manual_rate")),
    }
    if kind in SESSION_KINDS and not payload["session_id"]:
        raise ValueError("Session is required")
    if kind == "day_manual_rate" and not payload["employee_name"] and not payload["employee_user_id"]:
        raise ValueError("Employee is required")
    if kind in ELIGIBLE_KINDS:
        _validate_eligible(kind, payload, original_hours)
    if kind == "role_reallocation":
        hours = payload["reallocated_hours"]
        if hours is None or hours < 0:
            raise ValueError("Reallocated hours are required")
        if original_hours is not None and hours - original_hours > 1e-9:
            raise ValueError("Reallocated hours cannot exceed the recorded session")
        if not payload["reallocated_role_key"] or payload["reallocated_role_key"] == "UNKNOWN":
            payload["reallocated_role_key"] = None
    if kind in {"session_manual_rate", "day_manual_rate"}:
        if payload["manual_rate"] is None or payload["manual_rate"] < 0:
            raise ValueError("Approved rate is required")
    if payload["original_lbs"] is not None and _num(body.get("corrected_lbs")) not in (None, payload["original_lbs"]):
        raise ValueError("Adjustments cannot change pounds")
    return payload


def _validate_eligible(kind: str, payload: dict[str, Any], original_hours: float | None) -> None:
    supplied = [
        name
        for name, present in (
            ("eligible_interval", payload["eligible_start"] and payload["eligible_end"]),
            ("eligible_duration", payload["eligible_hours"] is not None),
            ("eligible_percent", payload["eligible_percent"] is not None),
        )
        if present and (kind == "eligible_interval" or name == kind or present)
    ]
    # Reject mixed modes even if the client sent extras on the chosen kind.
    modes = 0
    if payload["eligible_start"] or payload["eligible_end"]:
        modes += 1
    if payload["eligible_hours"] is not None:
        modes += 1
    if payload["eligible_percent"] is not None:
        modes += 1
    if modes > 1:
        raise ValueError("Use one eligible-time method: interval, duration, or percent")
    if kind == "eligible_interval" and not (payload["eligible_start"] and payload["eligible_end"]):
        raise ValueError("Eligible start and end are required")
    if kind == "eligible_duration":
        hours = payload["eligible_hours"]
        if hours is None or hours < 0:
            raise ValueError("Eligible hours are required")
        if original_hours is not None and hours - original_hours > 1e-6:
            raise ValueError("Eligible hours cannot exceed the recorded session")
    if kind == "eligible_percent":
        pct = payload["eligible_percent"]
        if pct is None or pct < 0 or pct > 100:
            raise ValueError("Eligible percent must be between 0 and 100")
        if original_hours is not None:
            payload["eligible_hours"] = round(original_hours * pct / 100.0, 4)
    if supplied and kind not in ELIGIBLE_KINDS:
        raise ValueError("Eligible time kind is required")


def _hours_between(start: Any, end: Any) -> float | None:
    def _parse(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        text = str(value or "").strip().replace("Z", "")
        if not text:
            return None
        try:
            return datetime.fromisoformat(text[:19])
        except ValueError:
            return None

    left = _parse(start)
    right = _parse(end)
    if left is None or right is None or right < left:
        return None
    return round((right - left).total_seconds() / 3600.0, 4)


def _eligible_hours(session: Mapping[str, Any], adjustments: Sequence[Mapping[str, Any]]) -> tuple[float | None, str | None]:
    original = _num(session.get("performance_hours"))
    if original is None:
        original = _num(session.get("session_hours"))
    eligible = _active(adjustments)
    chosen = [row for row in eligible if str(row.get("kind")) in ELIGIBLE_KINDS]
    realloc = [row for row in eligible if str(row.get("kind")) == "role_reallocation"]
    hours = original
    method = None
    if chosen:
        row = chosen[-1]
        kind = str(row.get("kind"))
        method = kind
        if kind == "eligible_percent" and _num(row.get("eligible_percent")) is not None and original is not None:
            hours = round(original * float(row["eligible_percent"]) / 100.0, 4)
        elif _num(row.get("eligible_hours")) is not None:
            hours = float(row["eligible_hours"])
        elif kind == "eligible_interval":
            span = _hours_between(row.get("eligible_start"), row.get("eligible_end"))
            if span is not None:
                if original is not None and span - original > 1e-6:
                    span = original
                hours = span
    if realloc and hours is not None:
        moved = sum(float(row.get("reallocated_hours") or 0) for row in realloc)
        hours = round(max(0.0, hours - moved), 4)
        method = method or "role_reallocation"
    return hours, method


def reported_session(session: Mapping[str, Any], adjustments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reported view. Pounds always stay on the original measurement."""
    sid = str(session.get("session_id") or "")
    mine = [
        row
        for row in adjustments or []
        if not row.get("reversed_at") and str(row.get("session_id") or "") == sid
    ]
    original_hours = _num(session.get("performance_hours"))
    if original_hours is None:
        original_hours = _num(session.get("session_hours"))
    original_lbs = _num(session.get("total_pre_lbs"))
    original_rate = _num(session.get("lbs_per_hour"))
    excluded = any(str(row.get("kind")) == "exclude" for row in mine)
    pub = str(session.get("publication_status") or "").upper()
    if pub == "EXCLUDED":
        excluded = True
    eligible, method = _eligible_hours(session, mine)
    manual = [row for row in mine if str(row.get("kind")) == "session_manual_rate"]
    manual_rate = _num(manual[-1].get("manual_rate")) if manual else None
    if excluded:
        reported_rate = None
        basis = "excluded"
    elif manual_rate is not None:
        reported_rate = round(manual_rate, 4)
        basis = "session_manual_rate"
    elif eligible is not None and eligible > 0 and original_lbs is not None:
        reported_rate = round(original_lbs / eligible, 4)
        basis = method or "eligible_hours"
    elif eligible == 0:
        reported_rate = None
        basis = "no_eligible_time"
    else:
        reported_rate = original_rate
        basis = "calculated"
    realloc = [row for row in mine if str(row.get("kind")) == "role_reallocation"]
    destination = realloc[-1].get("reallocated_role_key") if realloc else None
    return {
        "session_id": sid,
        "original_start": session.get("start_time"),
        "original_end": session.get("end_time"),
        "original_hours": original_hours,
        "original_lbs": original_lbs,
        "original_rate": original_rate,
        "eligible_hours": eligible,
        "reported_lbs": original_lbs,
        "reported_rate": reported_rate,
        "reported_basis": basis,
        "excluded": excluded,
        "reallocated_role_key": destination,
        "reallocated_output_lbs": 0,
        "destination_output_lbs": 0,
        "adjustments": [dict(row) for row in mine],
    }


def reported_employee_day(
    employee: Mapping[str, Any],
    session_reports: Sequence[Mapping[str, Any]],
    adjustments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    name = str(employee.get("employee") or "")
    uid = employee.get("user_id")
    day_rows = []
    for row in _active(adjustments, "day_manual_rate"):
        same_user = uid is not None and row.get("employee_user_id") is not None and int(row.get("employee_user_id")) == int(uid)
        same_name = name and str(row.get("employee_name") or "").casefold() == name.casefold()
        if same_user or same_name:
            day_rows.append(row)
    included = [row for row in session_reports if not row.get("excluded")]
    pounds = round(sum(float(row.get("reported_lbs") or 0) for row in included), 4)
    hours = round(sum(float(row.get("eligible_hours") or 0) for row in included if row.get("eligible_hours")), 4)
    if day_rows:
        rate = round(float(day_rows[-1]["manual_rate"]), 4)
        return {
            "employee": name,
            "reported_rate": rate,
            "reported_lbs": pounds,
            "reported_hours": hours,
            "precedence": "employee_day_manual_rate",
            "session_rates_compounded": False,
            "original_rate": _num(employee.get("lbs_per_hour")),
        }
    if hours > 0:
        rate = round(pounds / hours, 4)
        basis = "sum_pounds_over_eligible_hours"
    else:
        rate = None
        basis = "no_eligible_time"
    return {
        "employee": name,
        "reported_rate": rate,
        "reported_lbs": pounds,
        "reported_hours": hours,
        "precedence": basis,
        "session_rates_compounded": False,
        "original_rate": _num(employee.get("lbs_per_hour")),
    }
