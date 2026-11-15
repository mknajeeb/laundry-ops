"""Assemble the supervisor day from existing folding data plus Track 2 views.

Does not call auto-approval and does not change the folder benchmark.
"""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any, Mapping, Sequence

from backend.supervisor_portal.adjustments import reported_employee_day, reported_session
from backend.supervisor_portal.reconciliation import classify_completed_bags
from backend.supervisor_portal.roles import ROLE_CATALOG, role_public
from backend.supervisor_portal.scoring import preview_score

MIN_COMPARISON_HOURS = 0.25
MIN_COMPARISON_EMPLOYEES = 3


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def membership_from_day(day: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sessions: list[dict[str, Any]] = []
    for employee in day.get("employees") or []:
        if not isinstance(employee, Mapping):
            continue
        for session in employee.get("sessions") or []:
            if not isinstance(session, Mapping):
                continue
            publication = session.get("publication") if isinstance(session.get("publication"), Mapping) else {}
            status = str(session.get("publication_status") or publication.get("status") or "UNAPPROVED").upper()
            for order in session.get("orders") or []:
                if not isinstance(order, Mapping):
                    continue
                sessions.append(
                    {
                        **dict(order),
                        "session_id": session.get("session_id"),
                        "publication_status": status,
                        "approval_source": publication.get("approval_source") or session.get("approval_source"),
                        "is_rate_override": bool(
                            publication.get("is_rate_override") or session.get("is_rate_override")
                        ),
                        "role_status": session.get("role_status"),
                        "employee": employee.get("employee"),
                        "pounds": order.get("pre_lbs") or order.get("credited_weight_lbs"),
                    }
                )
    outside = [dict(row) for row in (day.get("outside_folder_session_orders") or []) if isinstance(row, Mapping)]
    unmapped = [dict(row) for row in (day.get("needs_attribution_orders") or []) if isinstance(row, Mapping)]
    return {"session_membership": sessions, "outside": outside, "unmapped": unmapped}


def team_comparison(employees: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Team speed is total eligible pounds / total eligible hours. Median is separate."""
    included = []
    for employee in employees or []:
        if employee.get("excluded"):
            continue
        hours = _num(employee.get("reported_hours"))
        pounds = _num(employee.get("reported_lbs"))
        rate = _num(employee.get("reported_rate"))
        if hours is None or pounds is None:
            continue
        included.append({"hours": hours, "pounds": pounds, "rate": rate, "eligible": hours + 1e-9 >= MIN_COMPARISON_HOURS and pounds > 0 and rate is not None})
    total_hours = round(sum(row["hours"] for row in included), 4)
    total_pounds = round(sum(row["pounds"] for row in included), 4)
    average = round(total_pounds / total_hours, 4) if total_hours > 0 else None
    rates = [row["rate"] for row in included if row["eligible"] and row["rate"] is not None]
    reliable = len(rates) >= MIN_COMPARISON_EMPLOYEES
    return {
        "eligible_pounds": total_pounds,
        "eligible_hours": total_hours,
        "average_lbs_per_hour": average,
        "median_lbs_per_hour": round(float(median(rates)), 4) if rates else None,
        "employees_in_median": len(rates),
        "comparison_reliable": reliable,
        "minimum_hours": MIN_COMPARISON_HOURS,
        "minimum_employees": MIN_COMPARISON_EMPLOYEES,
    }


def _achievement(actual: float | None, target: float | None) -> float | None:
    if actual is None or target is None or target <= 0:
        return None
    return round((actual / target) * 100.0, 1)


def assemble_supervisor_day(
    *,
    selected_date: date,
    completed: Sequence[Mapping[str, Any]],
    day: Mapping[str, Any],
    adjustments: Sequence[Mapping[str, Any]] | None = None,
    auto_approval_threshold: float | None = None,
    scoring_target: float | None = None,
    auto_approve_enabled: bool = False,
    quality_points_by_employee: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    placed = membership_from_day(day)
    reconciliation = classify_completed_bags(completed, **placed)
    threshold = float(auto_approval_threshold) if auto_approval_threshold is not None else None
    achievement_target = float(scoring_target) if scoring_target is not None else threshold
    target_source = "scoring_target" if scoring_target is not None else "auto_approval_benchmark"
    adj = list(adjustments or [])
    employees_out = []
    approved_hours = 0.0
    approved_pounds = 0.0
    pending_sessions = 0
    for employee in day.get("employees") or []:
        if not isinstance(employee, Mapping):
            continue
        session_reports = []
        sessions_public = []
        for session in employee.get("sessions") or []:
            if not isinstance(session, Mapping):
                continue
            report = reported_session(session, adj)
            session_reports.append(report)
            status = str(session.get("publication_status") or "UNAPPROVED").upper()
            if status == "APPROVED" and not report["excluded"]:
                if report.get("eligible_hours"):
                    approved_hours += float(report["eligible_hours"])
                if report.get("reported_lbs"):
                    approved_pounds += float(report["reported_lbs"])
            elif status != "EXCLUDED" and not report["excluded"]:
                pending_sessions += 1
            publication = session.get("publication") if isinstance(session.get("publication"), Mapping) else {}
            sessions_public.append(
                {
                    "session_id": session.get("session_id"),
                    "session_code": session.get("session_code"),
                    "start_time": session.get("start_time"),
                    "end_time": session.get("end_time"),
                    "role_status": session.get("role_status"),
                    "publication_status": status,
                    "approval_source": publication.get("approval_source"),
                    "is_rate_override": bool(publication.get("is_rate_override")),
                    "orders_completed": session.get("orders_completed"),
                    "original_role": "FOLDER",
                    **{key: report[key] for key in (
                        "original_hours",
                        "original_lbs",
                        "original_rate",
                        "eligible_hours",
                        "reported_lbs",
                        "reported_rate",
                        "reported_basis",
                        "excluded",
                        "reallocated_role_key",
                        "destination_output_lbs",
                    )},
                    "adjustments": report["adjustments"],
                }
            )
        day_report = reported_employee_day(employee, session_reports, adj)
        rate = day_report.get("reported_rate")
        achievement = _achievement(rate, achievement_target)
        excluded = bool(sessions_public) and all(row.get("excluded") or row.get("publication_status") == "EXCLUDED" for row in sessions_public)
        uid = employee.get("user_id")
        points = None
        if quality_points_by_employee:
            if uid is not None and f"u:{uid}" in quality_points_by_employee:
                points = quality_points_by_employee[f"u:{uid}"]
            elif employee.get("employee"):
                points = quality_points_by_employee.get(f"n:{str(employee.get('employee')).casefold()}")
        score = preview_score(
            actual=rate,
            target=achievement_target,
            measurable=True,
            quality_points=points,
            volume=day_report.get("reported_lbs"),
            training_ratio=None,
        )
        employees_out.append(
            {
                "employee": employee.get("employee"),
                "user_id": uid,
                "bags": employee.get("orders_completed"),
                "pounds": day_report.get("reported_lbs"),
                "recorded_hours": employee.get("session_hours") or employee.get("performance_hours"),
                "eligible_hours": day_report.get("reported_hours"),
                "calculated_rate": day_report.get("original_rate"),
                "reported_rate": rate,
                "rate_basis": day_report.get("precedence"),
                "target": achievement_target,
                "target_source": target_source,
                "achievement_percent": achievement,
                "below_target": bool(achievement is not None and achievement < 100 and not excluded),
                "excluded": excluded,
                "session_count": len(sessions_public),
                "sessions": sessions_public,
                "score": score,
            }
        )
    team = team_comparison(
        [
            {
                "reported_hours": row["eligible_hours"],
                "reported_lbs": row["pounds"],
                "reported_rate": row["reported_rate"],
                "excluded": row["excluded"],
            }
            for row in employees_out
        ]
    )
    approved_speed = round(approved_pounds / approved_hours, 4) if approved_hours > 0 else None
    below = [row["employee"] for row in employees_out if row["below_target"]]
    categories = reconciliation["categories"]
    return {
        "date_et": selected_date.isoformat(),
        "timezone": "America/New_York",
        "auto_approve": {
            "enabled": bool(auto_approve_enabled),
            "threshold_lbs_per_hour": threshold,
            "independent_of_scoring_target": True,
            "setting_key": "rinse_folding_lbs_per_hour_target",
        },
        "scoring_target_lbs_per_hour": scoring_target,
        "achievement_target_lbs_per_hour": achievement_target,
        "achievement_target_source": target_source,
        "reconciliation": reconciliation,
        "approved_productivity": {
            "approved_bags": categories.get("approved", 0),
            "pending_bags": categories.get("pending", 0),
            "excluded_bags": categories.get("excluded", 0),
            "approved_hours": round(approved_hours, 4),
            "approved_pounds": round(approved_pounds, 4),
            "approved_lbs_per_hour": approved_speed,
            "target_lbs_per_hour": threshold,
        },
        "volume": {
            "completed_bags": reconciliation["total_completed"],
            "approved_bags": categories.get("approved", 0),
            "approved_pounds": round(approved_pounds, 4),
            "accounted_bags": reconciliation["total_accounted"],
        },
        "employees": employees_out,
        "below_target": below,
        "pending_session_count": pending_sessions,
        "team": team,
        "roles": [dict(row) for row in ROLE_CATALOG],
        "folding_role": role_public("FOLDER"),
    }
