"""Day, week, and month folding totals.

Approved productivity is approved pounds divided by approved hours.
Pending pounds and hours stay in their own totals.
Daily rates are never averaged.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.supervisor_portal.service import MEASUREMENT_NOTE, team_comparison


def period_bounds(selected: date, period: str) -> tuple[date, date]:
    key = str(period or "day").strip().lower()
    if key == "week":
        start = selected - timedelta(days=selected.weekday())
        return start, start + timedelta(days=6)
    if key == "month":
        start = selected.replace(day=1)
        if start.month == 12:
            next_month = date(start.year + 1, 1, 1)
        else:
            next_month = date(start.year, start.month + 1, 1)
        return start, next_month - timedelta(days=1)
    return selected, selected


def iter_dates(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rate(pounds: float, hours: float) -> float | None:
    if hours <= 0:
        return None
    return round(pounds / hours, 4)


def _achievement(rate: float | None, target: float | None) -> float | None:
    if rate is None or target is None or target <= 0:
        return None
    return round((rate / target) * 100.0, 1)


def _employee_key(row: Mapping[str, Any]) -> str:
    if row.get("user_id") is not None:
        return f"u:{row.get('user_id')}"
    return f"n:{str(row.get('employee') or '').casefold()}"


def aggregate_period(days: Sequence[Mapping[str, Any]], *, quality: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Combine already-built Eastern days. Failed days stay listed and are not invented."""
    usable = [day for day in days if isinstance(day, Mapping) and not day.get("error")]
    errors = [dict(day) for day in days if isinstance(day, Mapping) and day.get("error")]
    people: dict[str, dict[str, Any]] = {}
    categories = {
        "approved": 0,
        "pending": 0,
        "excluded": 0,
        "outside_session": 0,
        "nonqualifying": 0,
        "unmapped": 0,
        "unresolved": 0,
    }
    completed = 0
    accounted = 0
    unaccounted = 0
    approved_hours = 0.0
    approved_pounds = 0.0
    pending_hours = 0.0
    pending_pounds = 0.0
    trend = []
    target = None
    target_source = None
    for day in usable:
        recon = day.get("reconciliation") or {}
        counts = recon.get("categories") or {}
        for key in categories:
            categories[key] += int(counts.get(key) or 0)
        completed += int(recon.get("total_completed") or 0)
        accounted += int(recon.get("total_accounted") or 0)
        unaccounted += int(recon.get("unaccounted") or 0)
        approved = day.get("approved_productivity") or {}
        approved_hours += _num(approved.get("approved_hours"))
        approved_pounds += _num(approved.get("approved_pounds"))
        pending_hours += _num(approved.get("pending_hours"))
        pending_pounds += _num(approved.get("pending_pounds"))
        if target is None and day.get("achievement_target_lbs_per_hour") is not None:
            target = float(day["achievement_target_lbs_per_hour"])
            target_source = day.get("achievement_target_source")
        day_pounds = 0.0
        day_hours = 0.0
        day_pending_pounds = 0.0
        day_pending_hours = 0.0
        for employee in day.get("employees") or []:
            if not isinstance(employee, Mapping) or employee.get("excluded"):
                continue
            key = _employee_key(employee)
            slot = people.setdefault(
                key,
                {
                    "employee": employee.get("employee"),
                    "user_id": employee.get("user_id"),
                    "bags": 0,
                    "pounds": 0.0,
                    "eligible_hours": 0.0,
                    "pending_bags": 0,
                    "pending_pounds": 0.0,
                    "pending_hours": 0.0,
                    "days": 0,
                    "trend": [],
                    "measurement_basis": "approved_sessions",
                },
            )
            pounds = _num(employee.get("pounds"))
            hours = _num(employee.get("eligible_hours"))
            pending_bags = int(employee.get("pending_bags") or 0)
            employee_pending_pounds = _num(employee.get("pending_pounds"))
            employee_pending_hours = _num(employee.get("pending_hours"))
            slot["bags"] += int(employee.get("bags") or 0)
            slot["pounds"] = round(slot["pounds"] + pounds, 4)
            slot["eligible_hours"] = round(slot["eligible_hours"] + hours, 4)
            slot["pending_bags"] += pending_bags
            slot["pending_pounds"] = round(slot["pending_pounds"] + employee_pending_pounds, 4)
            slot["pending_hours"] = round(slot["pending_hours"] + employee_pending_hours, 4)
            slot["days"] += 1
            day_rate = _rate(pounds, hours)
            slot["trend"].append(
                {
                    "date": day.get("date_et"),
                    "pounds": round(pounds, 4),
                    "hours": round(hours, 4),
                    "rate": day_rate,
                    "pending_pounds": round(employee_pending_pounds, 4),
                    "pending_hours": round(employee_pending_hours, 4),
                    "basis": "approved",
                }
            )
            day_pounds += pounds
            day_hours += hours
            day_pending_pounds += employee_pending_pounds
            day_pending_hours += employee_pending_hours
        trend.append(
            {
                "date": day.get("date_et"),
                "pounds": round(day_pounds, 4),
                "hours": round(day_hours, 4),
                "rate": _rate(day_pounds, day_hours),
                "pending_pounds": round(day_pending_pounds, 4),
                "pending_hours": round(day_pending_hours, 4),
                "basis": "approved",
            }
        )
    points = (quality or {}).get("employee_points") or {}
    employees = []
    for slot in people.values():
        rate = _rate(slot["pounds"], slot["eligible_hours"])
        ident = f"u:{slot['user_id']}" if slot.get("user_id") is not None else f"n:{str(slot.get('employee') or '').casefold()}"
        employees.append(
            {
                **slot,
                "reported_rate": rate,
                "calculated_rate": rate,
                "bags_per_hour": _rate(slot["bags"], slot["eligible_hours"]),
                "pending_lbs_per_hour": _rate(slot["pending_pounds"], slot["pending_hours"]),
                "pending_bags_per_hour": _rate(slot["pending_bags"], slot["pending_hours"]),
                "target": target,
                "target_source": target_source,
                "achievement_percent": _achievement(rate, target),
                "quality_points": points.get(ident, 0),
                "below_target": bool(_achievement(rate, target) is not None and _achievement(rate, target) < 100),
                "excluded": False,
                "sessions": [],
                "score": {"overall": None, "activated": False, "status": "inactive", "reason": "Scoring formula is not authorized"},
            }
        )
    employees.sort(key=lambda row: (-(row.get("reported_rate") or 0), str(row.get("employee") or "")))
    team = team_comparison(
        [
            {
                "reported_hours": row["eligible_hours"],
                "reported_lbs": row["pounds"],
                "reported_rate": row["reported_rate"],
                "excluded": False,
            }
            for row in employees
        ]
    )
    return {
        "employees": employees,
        "team": team,
        "trend": trend,
        "reconciliation": {
            "total_completed": completed,
            "total_accounted": accounted,
            "unaccounted": unaccounted,
            "categories": categories,
            "invariant_holds": completed == accounted and unaccounted == 0,
            "bags": [],
            "scope": "category_totals_across_reporting_days",
            "cross_day_bag_ids_stay_separate": True,
        },
        "measurement_note": MEASUREMENT_NOTE,
        "approved_productivity": {
            "approved_hours": round(approved_hours, 4),
            "approved_pounds": round(approved_pounds, 4),
            "approved_lbs_per_hour": _rate(approved_pounds, approved_hours),
            "approved_bags": categories["approved"],
            "approved_bags_per_hour": _rate(categories["approved"], approved_hours),
            "pending_hours": round(pending_hours, 4),
            "pending_pounds": round(pending_pounds, 4),
            "pending_lbs_per_hour": _rate(pending_pounds, pending_hours),
            "pending_bags": categories["pending"],
            "pending_bags_per_hour": _rate(categories["pending"], pending_hours),
            "target_lbs_per_hour": target,
            "pending_is_excluded_from_approved_rate": True,
        },
        "volume": {
            "completed_bags": completed,
            "approved_bags": categories["approved"],
            "approved_pounds": round(approved_pounds, 4),
            "accounted_bags": accounted,
        },
        "achievement_target_lbs_per_hour": target,
        "achievement_target_source": target_source,
        "quality": quality or {},
        "day_errors": errors,
        "days_included": len(usable),
    }
