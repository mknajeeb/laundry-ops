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


def _session_status(session: Mapping[str, Any]) -> str:
    publication = session.get("publication") if isinstance(session.get("publication"), Mapping) else {}
    return str(session.get("publication_status") or publication.get("status") or "UNAPPROVED").upper()


def _session_bags(session: Mapping[str, Any]) -> int:
    raw = session.get("orders_completed")
    if raw is not None and raw != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    return sum(1 for row in (session.get("orders") or []) if isinstance(row, Mapping))


def _sum_measured(reports: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    pounds = round(sum(float(row.get("reported_lbs") or 0) for row in reports), 4)
    hours = round(
        sum(float(row.get("eligible_hours") or 0) for row in reports if row.get("eligible_hours")),
        4,
    )
    return pounds, hours


def _per_hour(numerator: float, hours: float) -> float | None:
    if hours <= 0:
        return None
    return round(numerator / hours, 4)


MEASUREMENT_NOTE = (
    "Approved bags, pounds, hours, and speed include only approved folding sessions. "
    "Pending work is shown separately and is not part of the approved speed. "
    "Excluded, outside-session, unmapped, and missing-scan bags stay in their own counts."
)


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
    approved_session_bags = 0
    pending_hours = 0.0
    pending_pounds = 0.0
    pending_session_bags = 0
    pending_sessions = 0
    for employee in day.get("employees") or []:
        if not isinstance(employee, Mapping):
            continue
        approved_reports = []
        pending_reports = []
        sessions_public = []
        employee_approved_bags = 0
        employee_pending_bags = 0
        for session in employee.get("sessions") or []:
            if not isinstance(session, Mapping):
                continue
            report = reported_session(session, adj)
            status = _session_status(session)
            bags = _session_bags(session)
            if status == "APPROVED" and not report["excluded"]:
                approved_reports.append(report)
                employee_approved_bags += bags
                if report.get("eligible_hours"):
                    approved_hours += float(report["eligible_hours"])
                if report.get("reported_lbs"):
                    approved_pounds += float(report["reported_lbs"])
            elif status != "EXCLUDED" and not report["excluded"]:
                pending_reports.append(report)
                employee_pending_bags += bags
                pending_sessions += 1
                if report.get("eligible_hours"):
                    pending_hours += float(report["eligible_hours"])
                if report.get("reported_lbs"):
                    pending_pounds += float(report["reported_lbs"])
            publication = session.get("publication") if isinstance(session.get("publication"), Mapping) else {}
            sessions_public.append(
                {
                    "session_id": session.get("session_id"),
                    "session_code": session.get("session_code"),
                    "start_time": session.get("start_time"),
                    "end_time": session.get("end_time"),
                    "role_status": session.get("role_status"),
                    "publication_status": status,
                    "counts_toward_approved": status == "APPROVED" and not report["excluded"],
                    "approval_source": publication.get("approval_source"),
                    "is_rate_override": bool(publication.get("is_rate_override")),
                    "orders_completed": bags,
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
        # A day-level manual rate applies to approved folding only. Pending-only
        # employees keep a blank approved rate instead of inheriting that override.
        rate_adjustments = adj if approved_reports else [
            row for row in adj if str(row.get("kind")) != "day_manual_rate"
        ]
        day_report = reported_employee_day(employee, approved_reports, rate_adjustments)
        approved_session_bags += employee_approved_bags
        pending_session_bags += employee_pending_bags
        pending_measured_lbs, pending_measured_hours = _sum_measured(pending_reports)
        rate = day_report.get("reported_rate")
        approved_measured_hours = float(day_report.get("reported_hours") or 0)
        approved_measured_lbs = float(day_report.get("reported_lbs") or 0)
        measured_rate = _per_hour(approved_measured_lbs, approved_measured_hours)
        achievement = _achievement(rate, achievement_target)
        excluded = bool(sessions_public) and all(
            row.get("excluded") or row.get("publication_status") == "EXCLUDED" for row in sessions_public
        )
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
            measurable=approved_measured_hours > 0,
            quality_points=points,
            volume=approved_measured_lbs,
            training_ratio=None,
        )
        employees_out.append(
            {
                "employee": employee.get("employee"),
                "user_id": uid,
                "bags": employee_approved_bags,
                "pounds": day_report.get("reported_lbs"),
                "recorded_hours": approved_measured_hours if approved_measured_hours else None,
                "eligible_hours": day_report.get("reported_hours"),
                "bags_per_hour": _per_hour(employee_approved_bags, approved_measured_hours),
                "calculated_rate": measured_rate,
                "reported_rate": rate,
                "rate_basis": day_report.get("precedence") if approved_reports else "no_approved_time",
                "measurement_basis": "approved_sessions",
                "pending_bags": employee_pending_bags,
                "pending_pounds": pending_measured_lbs,
                "pending_hours": pending_measured_hours,
                "pending_lbs_per_hour": _per_hour(pending_measured_lbs, pending_measured_hours),
                "pending_bags_per_hour": _per_hour(employee_pending_bags, pending_measured_hours),
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
    approved_hours = round(approved_hours, 4)
    approved_pounds = round(approved_pounds, 4)
    pending_hours = round(pending_hours, 4)
    pending_pounds = round(pending_pounds, 4)
    approved_speed = _per_hour(approved_pounds, approved_hours)
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
        "measurement_note": MEASUREMENT_NOTE,
        "approved_productivity": {
            "approved_bags": categories.get("approved", 0),
            "approved_session_bags": approved_session_bags,
            "pending_bags": categories.get("pending", 0),
            "pending_session_bags": pending_session_bags,
            "excluded_bags": categories.get("excluded", 0),
            "approved_hours": approved_hours,
            "approved_pounds": approved_pounds,
            "approved_lbs_per_hour": approved_speed,
            "approved_bags_per_hour": _per_hour(approved_session_bags, approved_hours),
            "pending_hours": pending_hours,
            "pending_pounds": pending_pounds,
            "pending_lbs_per_hour": _per_hour(pending_pounds, pending_hours),
            "pending_bags_per_hour": _per_hour(pending_session_bags, pending_hours),
            "target_lbs_per_hour": threshold,
            "pending_is_excluded_from_approved_rate": True,
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
