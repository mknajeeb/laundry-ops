"""Monthly Task Performance analytics for Management Task Dashboard."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Mapping

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    DISPLAY_OVERDUE,
    VERIFICATION_PARTIAL,
    VERIFICATION_WAITING,
    _activities_for_day,
    _day_responsibilities,
    _employee_names,
    _group_shared_assignments,
    _latest_activity_by_resp,
    _role_catalog,
    _task_meta_for_role,
    assignment_is_completed,
    assignment_is_verified,
    assignment_needs_correction,
    ensure_cleaning_task_activity_tables,
)
from backend.task_catalog import list_categories


def chart_status(row: Mapping[str, Any]) -> str:
    """One status per assignment so a stacked chart does not count the same activity twice."""
    from backend.cleaning_task_activity import (
        COMPLETION_IN_PROGRESS,
        COMPLETION_NOT_STARTED,
        VERIFICATION_PARTIAL,
        VERIFICATION_WAITING,
        assignment_is_completed,
        assignment_is_started,
        assignment_is_verified,
        assignment_needs_correction,
    )

    if assignment_needs_correction(row):
        return "needs_correction"
    if str(row.get("status") or "") == DISPLAY_OVERDUE and not assignment_is_completed(row):
        return "overdue"
    if assignment_is_verified(row):
        return "verified"
    verification = str(row.get("verification_status") or "")
    overall = str(row.get("overall_status") or "")
    if verification in {VERIFICATION_WAITING, VERIFICATION_PARTIAL} or overall == "pending_verification":
        return "pending_verification"
    if assignment_is_completed(row):
        return "pending_verification"
    if assignment_is_started(row) or str(row.get("completion_status") or "") == COMPLETION_IN_PROGRESS:
        return "in_progress"
    if str(row.get("overall_status") or "") == COMPLETION_NOT_STARTED:
        return "not_started"
    return "not_started"


def bucket_label(day: date, group_by: str) -> str:
    """Sunday-start weeks in America/New_York calendar dates. DST does not move the date."""
    mode = str(group_by or "daily").strip().lower()
    if mode == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    if mode == "weekly":
        start = day - timedelta(days=(day.weekday() + 1) % 7)
        return str(start)
    return str(day)


def stack_chart_buckets(days: list[Mapping[str, Any]], group_by: str = "daily") -> list[dict[str, Any]]:
    order: list[str] = []
    grouped: dict[str, dict[str, int]] = {}
    for row in days or []:
        raw = str(row.get("business_date") or "")[:10]
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            continue
        key = bucket_label(parsed, group_by)
        if key not in grouped:
            order.append(key)
            grouped[key] = {
                "not_started": 0,
                "in_progress": 0,
                "pending_verification": 0,
                "verified": 0,
                "overdue": 0,
                "needs_correction": 0,
            }
        chart = row.get("chart") if isinstance(row.get("chart"), Mapping) else {}
        for name in grouped[key]:
            grouped[key][name] += int(chart.get(name) or 0)
    return [{"label": key, **grouped[key]} for key in order]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def monthly_task_performance(
    cursor,
    organization_id: int,
    *,
    year: int | None = None,
    month: int | None = None,
    category_code: str | None = None,
    rinse_eligible_only: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str = "daily",
    include_assignments: bool = False,
) -> dict[str, Any]:
    """Daily assigned / completed / overdue / verified for a calendar month (ET business dates).

    Shared assignments count once per day. Verified, pending verification, completed,
    and needs-correction use the same assignment helpers as the day dashboard: one
    group is one assignment, and it is verified only when every required item is verified.

    When ``rinse_eligible_only`` is True, only PIN-original non-voided activities are
    used for status rollups (manual/corrected/voided excluded from Rinse reports).
    """
    ensure_cleaning_task_activity_tables(cursor)
    today = business_today()
    y = int(year or today.year)
    m = int(month or today.month)
    if start_date is not None and end_date is not None:
        start, end = start_date, end_date
        if end < start:
            start, end = end, start
        if (end - start).days > 62:
            end = start + timedelta(days=62)
    else:
        start, end = _month_bounds(y, m)
    oid = int(organization_id)
    catalog = _role_catalog(cursor, oid)
    cat_filter = (str(category_code or "").strip() or None)

    days: list[dict[str, Any]] = []
    collected: list[dict[str, Any]] = []
    totals = {
        "assigned": 0,
        "completed": 0,
        "pending": 0,
        "overdue": 0,
        "verified": 0,
        "pending_verification": 0,
        "rejected": 0,
    }
    cur = start
    while cur <= end:
        assignments = _day_responsibilities(cursor, oid, business_date=cur)
        activities = _activities_for_day(cursor, oid, cur)
        if rinse_eligible_only:
            from backend.cleaning_task_record_management import activity_is_rinse_eligible

            activities = [row for row in activities if activity_is_rinse_eligible(row)]
        by_resp = _latest_activity_by_resp(activities)
        name_ids = {int(a["user_id"]) for a in assignments} | {int(r["user_id"]) for r in activities}
        names = _employee_names(cursor, oid, sorted(name_ids))
        from backend.business_time import business_now

        now = business_now()
        if getattr(now, "tzinfo", None) is not None:
            now = now.replace(tzinfo=None)
        # For historical days, evaluate overdue relative to end of that day.
        if cur < today:
            now = __import__("datetime").datetime.combine(cur, __import__("datetime").time(23, 59, 59))
        shared = _group_shared_assignments(
            assignments,
            by_resp,
            catalog=catalog,
            names=names,
            now=now,
            cursor=cursor,
            organization_id=oid,
            business_date=cur,
            activities=activities,
        )
        if cat_filter:
            filtered = []
            for row in shared:
                meta = _task_meta_for_role(cursor, oid, str(row.get("role") or ""))
                if str(meta.get("category_code") or "intra_day") == cat_filter:
                    filtered.append(row)
            shared = filtered

        assigned = len(shared)
        completed = 0
        pending = 0
        overdue = 0
        verified = 0
        pending_verification = 0
        rejected = 0
        exclusive = {
            "not_started": 0,
            "in_progress": 0,
            "pending_verification": 0,
            "verified": 0,
            "overdue": 0,
            "needs_correction": 0,
        }
        # Same assignment rules as the day dashboard. A group is one assignment and is
        # verified only when every required item is verified, not when the parent timer closes.
        for row in shared:
            exclusive[chart_status(row)] += 1
            if include_assignments:
                stamped = dict(row)
                stamped["business_date"] = str(cur)
                collected.append(stamped)
            if assignment_is_completed(row):
                completed += 1
            else:
                pending += 1
            if row.get("status") == DISPLAY_OVERDUE:
                overdue += 1
            if assignment_is_verified(row):
                verified += 1
            if str(row.get("verification_status") or "") in {VERIFICATION_WAITING, VERIFICATION_PARTIAL}:
                pending_verification += 1
            if assignment_needs_correction(row):
                rejected += 1

        day_row = {
            "business_date": str(cur),
            "day": cur.day,
            "assigned": assigned,
            "completed": completed,
            "pending": pending,
            "overdue": overdue,
            "verified": verified,
            "pending_verification": pending_verification,
            "rejected": rejected,
            "chart": exclusive,
            "completion_rate": round((completed / assigned) * 100, 1) if assigned else None,
        }
        days.append(day_row)
        for k in totals:
            totals[k] += int(day_row.get(k) or 0)
        cur += timedelta(days=1)

    overall_rate = (
        round((totals["completed"] / totals["assigned"]) * 100, 1) if totals["assigned"] else None
    )
    try:
        categories = list_categories(cursor, oid, include_inactive=False)
    except Exception:
        categories = []

    return {
        "year": y,
        "month": m,
        "month_start": str(start),
        "month_end": str(end),
        "category_code": cat_filter,
        "categories": [{"code": c["code"], "name": c["name"]} for c in categories],
        "assignments": collected if include_assignments else [],
        "days": days,
        "buckets": stack_chart_buckets(days, group_by),
        "group_by": str(group_by or "daily"),
        "totals": {**totals, "completion_rate": overall_rate},
    }
