"""Weekly quality assignments.

Investigation stays outside the app. A supervisor records a confirmed incident
and the employees responsible. One incident key counts once in the weekly
incident total no matter how many employees are assigned.

Weights are versioned. Publishing a new version does not rewrite incidents
that already stored ``weight_version_id``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

# Starting catalog. Management can add, rename, and retire codes.
STARTER_ISSUE_TYPES = (
    {"code": "missing_item", "label": "Missing item"},
    {"code": "found_item", "label": "Found item"},
    {"code": "damage", "label": "Damage"},
    {"code": "sorting_error", "label": "Sorting error"},
    {"code": "scan_error", "label": "Scan/process error"},
    {"code": "incorrect_handling", "label": "Incorrect handling"},
    {"code": "other", "label": "Other"},
)

# Illustrative only. Not a published production weight table.
ILLUSTRATIVE_WEIGHTS = {
    "found_item": 1,
    "scan_error": 1,
    "sorting_error": 2,
    "missing_item": 3,
    "incorrect_handling": 4,
    "damage": 4,
    "other": 1,
}

ILLUSTRATIVE_SEVERITY = {"minor": 1, "standard": 1, "major": 1.5}


def week_start(day: date) -> date:
    """Monday of the America/New_York business date. ``day`` is already an ET date."""
    return day - timedelta(days=day.weekday())


def normalize_incident(body: Mapping[str, Any], *, week: date) -> dict[str, Any]:
    issue_type = str(body.get("issue_type") or body.get("issue_type_code") or "").strip().lower()
    if not issue_type:
        raise ValueError("Issue type is required")
    try:
        quantity = int(body.get("quantity") if body.get("quantity") is not None else 1)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a whole number") from None
    if quantity < 1:
        raise ValueError("Quantity must be at least 1")
    employees = body.get("employees") or []
    if isinstance(employees, Mapping):
        employees = [employees]
    cleaned = []
    seen = set()
    for employee in employees:
        if not isinstance(employee, Mapping):
            continue
        uid = employee.get("user_id") or employee.get("employee_user_id")
        name = str(employee.get("employee_name") or employee.get("name") or "").strip()
        if uid is None:
            raise ValueError("Each assigned employee needs an account id")
        key = f"u:{uid}"
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "user_id": int(uid) if uid is not None else None,
                "employee_name": name or None,
                "role_key": str(employee.get("role_key") or body.get("role_key") or "GENERAL").strip().upper()
                or "GENERAL",
            }
        )
    if not cleaned:
        raise ValueError("Select at least one employee")
    incident_key = str(body.get("incident_key") or body.get("reference") or "").strip()
    if not incident_key:
        raise ValueError("An incident reference or incident key is required")
    return {
        "week_start": week_start(week).isoformat(),
        "issue_type": issue_type,
        "severity": (str(body.get("severity")).strip().lower() if body.get("severity") else None),
        "quantity": quantity,
        "incident_key": incident_key[:160],
        "reference": (str(body.get("reference")).strip()[:500] if body.get("reference") else None),
        "notes": (str(body.get("notes")).strip()[:2000] if body.get("notes") else None),
        "role_key": str(body.get("role_key") or "GENERAL").strip().upper() or "GENERAL",
        "employees": cleaned,
    }


def points_for(
    quantity: int,
    issue_type: str,
    severity: str | None,
    version: Mapping[str, Any] | None,
) -> float | None:
    if not version:
        return None
    weights = version.get("weights") or {}
    if issue_type not in weights:
        return None
    weight = float(weights[issue_type])
    modifiers = version.get("severity") or {}
    modifier = float(modifiers.get(severity, 1)) if severity else 1.0
    return round(quantity * weight * modifier, 4)


def incident_totals(incidents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count each non-voided incident key once. Employee rows do not add incidents."""
    seen: dict[str, Mapping[str, Any]] = {}
    by_type: dict[str, int] = defaultdict(int)
    employee_points: dict[str, float] = defaultdict(float)
    for row in incidents or []:
        if row.get("voided_at"):
            continue
        key = str(row.get("incident_key") or row.get("id") or "")
        if not key:
            continue
        if key not in seen:
            seen[key] = row
            by_type[str(row.get("issue_type") or "other")] += 1
        for employee in _employees_of(row):
            points = row.get("employee_points")
            if points is None:
                continue
            ident = _employee_key(employee)
            if not ident:
                continue
            employee_points[ident] = round(employee_points.get(ident, 0) + float(points), 4)
    return {
        "incident_count": len(seen),
        "by_type": [{"issue_type": key, "incidents": value} for key, value in sorted(by_type.items())],
        "employee_points": dict(employee_points),
    }


def _employees_of(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    employees = row.get("employees") or []
    if employees:
        return [employee for employee in employees if isinstance(employee, Mapping)]
    if row.get("employee_name") or row.get("user_id") is not None:
        return [{"employee_name": row.get("employee_name"), "user_id": row.get("user_id")}]
    return []


def _employee_key(employee: Mapping[str, Any]) -> str | None:
    uid = employee.get("user_id")
    if uid is not None:
        return f"u:{uid}"
    name = str(employee.get("employee_name") or employee.get("name") or "").strip()
    if not name:
        return None
    return f"n:{name.casefold()}"
