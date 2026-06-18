"""Labor metrics from daily shift roster — additive to employee productivity dashboard."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _norm_name(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def _productivity_by_name(employees: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for emp in employees or []:
        if not isinstance(emp, dict):
            continue
        key = _norm_name(emp.get("employee"))
        if key:
            out[key] = emp
    return out


def _safe_div(numerator: float | int | None, denominator: float | int | None) -> float | None:
    num = float(numerator or 0)
    den = float(denominator or 0)
    if den <= 0:
        return None
    return round(num / den, 4)


def _role_metrics(
    entries: Sequence[Mapping[str, Any]],
    *,
    productivity_by_name: Mapping[str, Mapping[str, Any]],
    role: str,
    include_bags: bool,
) -> dict[str, Any]:
    role_entries = [e for e in entries if str(e.get("role") or "").lower() == role]
    total_hours = round(sum(float(e.get("hours") or 0) for e in role_entries), 4)
    labor_cost = round(sum(float(e.get("cost") or 0) for e in role_entries), 2)

    bags = 0
    pounds = 0.0
    for entry in role_entries:
        prod = productivity_by_name.get(_norm_name(entry.get("employee_name")))
        if not prod:
            continue
        bags += int(prod.get("completed_bags") or 0)
        pounds += float(prod.get("total_completed_lbs") or 0)
    pounds = round(pounds, 2)

    metrics: dict[str, Any] = {
        "employees": len(role_entries),
        "total_hours": total_hours,
        "labor_cost": labor_cost,
    }
    if include_bags:
        metrics.update(
            {
                "bags_completed": bags,
                "pounds_completed": pounds,
                "bags_per_hour": _safe_div(bags, total_hours),
                "pounds_per_hour": _safe_div(pounds, total_hours),
            }
        )
    else:
        metrics["pounds_processed"] = pounds
    return metrics


def build_labor_summary(
    roster_entries: Sequence[Mapping[str, Any]] | None,
    *,
    productivity_section: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entries = [
        dict(e)
        for e in (roster_entries or [])
        if isinstance(e, dict) and not e.get("excluded")
    ]
    if not entries:
        return {
            "available": False,
            "message": "No labor roster recorded for this date.",
            "kpis": {
                "total_labor_hours": None,
                "folder_hours": None,
                "operator_hours": None,
                "total_labor_cost": None,
                "cost_per_bag": None,
                "cost_per_pound": None,
            },
            "role_breakdown": {
                "folders": None,
                "operators": None,
            },
            "employee_details": [],
        }

    productivity_employees = (productivity_section or {}).get("employees") or []
    executive = (productivity_section or {}).get("executive_summary") or {}
    productivity_by_name = _productivity_by_name(productivity_employees)

    total_hours = round(sum(float(e.get("hours") or 0) for e in entries), 4)
    folder_hours = round(
        sum(float(e.get("hours") or 0) for e in entries if str(e.get("role")) == "folder"),
        4,
    )
    operator_hours = round(
        sum(float(e.get("hours") or 0) for e in entries if str(e.get("role")) == "operator"),
        4,
    )
    total_cost = round(sum(float(e.get("cost") or 0) for e in entries), 2)

    total_bags = int(executive.get("total_bags_completed") or 0)
    total_pounds = float(executive.get("total_pounds_completed") or 0)

    folders = _role_metrics(entries, productivity_by_name=productivity_by_name, role="folder", include_bags=True)
    operators = _role_metrics(entries, productivity_by_name=productivity_by_name, role="operator", include_bags=False)

    employee_details = [
        {
            "employee": e.get("employee_name"),
            "role": e.get("role"),
            "hours": e.get("hours"),
            "rate": e.get("rate"),
            "cost": e.get("cost"),
        }
        for e in sorted(
            entries,
            key=lambda row: (str(row.get("role") or ""), str(row.get("employee_name") or "").lower()),
        )
    ]

    return {
        "available": True,
        "message": None,
        "kpis": {
            "total_labor_hours": total_hours,
            "folder_hours": folder_hours,
            "operator_hours": operator_hours,
            "total_labor_cost": total_cost,
            "cost_per_bag": _safe_div(total_cost, total_bags),
            "cost_per_pound": _safe_div(total_cost, total_pounds),
        },
        "role_breakdown": {
            "folders": folders,
            "operators": operators,
        },
        "employee_details": employee_details,
    }
