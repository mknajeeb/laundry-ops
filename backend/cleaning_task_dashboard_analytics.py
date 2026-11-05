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
    _prime_activities_for_range,
    _role_catalog,
    _task_meta_for_role,
    assignment_is_completed,
    assignment_is_verified,
    assignment_needs_correction,
    ensure_cleaning_task_activity_tables,
    serialize_activity,
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
        VERIFICATION_NOT_REQUIRED,
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
        if verification == VERIFICATION_NOT_REQUIRED:
            return "completed"
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
                "completed": 0,
            }
        chart = row.get("chart") if isinstance(row.get("chart"), Mapping) else {}
        for name in grouped[key]:
            grouped[key][name] += int(chart.get(name) or 0)
    return [{"label": key, **grouped[key]} for key in order]


MAX_TASK_DASHBOARD_SPAN_DAYS = 366


class TaskDashboardRangeError(ValueError):
    """The requested business-date range cannot be reported as asked."""


def resolve_task_dashboard_range(start: date, end: date) -> tuple[date, date]:
    """Inclusive America/New_York business dates. Never shortens the range."""
    if end < start:
        start, end = end, start
    span = (end - start).days + 1
    if span > MAX_TASK_DASHBOARD_SPAN_DAYS:
        raise TaskDashboardRangeError(
            f"Date range is {span} days. Choose {MAX_TASK_DASHBOARD_SPAN_DAYS} days or fewer."
        )
    return start, end


def page_rows(rows: list[Any], offset: int | None, limit: int | None) -> list[Any]:
    """Return a page. A missing or non-positive limit returns every row."""
    if limit is None or int(limit) <= 0:
        return list(rows)
    start_at = max(0, int(offset or 0))
    return list(rows[start_at : start_at + int(limit)])


def history_verification_label(item: Mapping[str, Any]) -> str:
    """Verification is separate from whether the work itself is complete."""
    if item.get("is_voided"):
        return "Voided"
    if item.get("verification_required") is False:
        return "Not required"
    status = str(item.get("status") or "")
    if status == "approved":
        return "Verified"
    if status == "pending_approval":
        return "Pending verification"
    if status == "rejected":
        return "Needs correction"
    if status == "completed":
        return "Completed, verification not required"
    return "Not verified"


def participation_rollup(shared_rows: list[Mapping[str, Any]]) -> dict[str, int]:
    """Employee timers once each. Shared assignments are not counted again."""
    from backend.cleaning_task_activity import (
        PARTICIPATION_FINISHED,
        PARTICIPATION_IN_PROGRESS,
        participation_status_from_display,
    )

    assigned = started = finished = seconds = 0
    for row in shared_rows or []:
        for contrib in row.get("contributions") or []:
            if not isinstance(contrib, Mapping):
                continue
            assigned += 1
            part = str(contrib.get("participation_status") or "")
            if part not in {"not_started", "in_progress", "finished"}:
                part = participation_status_from_display(contrib.get("status"))
            if part in {PARTICIPATION_IN_PROGRESS, PARTICIPATION_FINISHED}:
                started += 1
            if part == PARTICIPATION_FINISHED:
                finished += 1
            act = contrib.get("activity") if isinstance(contrib.get("activity"), Mapping) else {}
            kind = str(act.get("timestamp_kind") or act.get("activity_kind") or "")
            if kind in {"checklist_checkoff", "group_item"}:
                continue
            raw = act.get("duration_seconds")
            if raw is not None and raw != "":
                seconds += max(0, int(raw))
    return {
        "employees_assigned": assigned,
        "employees_started": started,
        "employees_finished": finished,
        "total_time_seconds": seconds,
    }


_REPORT_STATUS_LABELS = {
    "not_started": "Not Started",
    "in_progress": "In Progress",
    "finished": "Finished",
    "completed": "Completed",
    "pending_verification": "Waiting for Verification",
    "verified": "Verified",
    "overdue": "Overdue",
    "needs_correction": "Needs Correction",
}


def _remember_filter_options(
    shared: list[Mapping[str, Any]],
    activities: dict[str, str],
    employees: dict[int, str],
) -> None:
    for row in shared:
        role = str(row.get("role") or "")
        if role and role not in activities:
            activities[role] = str(row.get("role_label") or role)
        for source in list(row.get("contributions") or []) + list(row.get("members") or []):
            if not isinstance(source, Mapping):
                continue
            raw = source.get("employee_id") or source.get("user_id")
            if not raw:
                continue
            eid = int(raw)
            employees.setdefault(eid, str(source.get("employee_name") or f"User #{eid}"))


def _row_matches_filters(
    row: Mapping[str, Any],
    *,
    employee_id: int | None,
    activity: str | None,
    status_filter: str | None,
) -> bool:
    if activity:
        needle = str(activity).strip().lower()
        role = str(row.get("role") or "").lower()
        label = str(row.get("role_label") or "").lower()
        if needle not in {role, label}:
            return False
    if employee_id:
        wanted = int(employee_id)
        ids = set()
        for source in list(row.get("contributions") or []) + list(row.get("members") or []):
            if not isinstance(source, Mapping):
                continue
            raw = source.get("employee_id") or source.get("user_id")
            if raw:
                ids.add(int(raw))
        if wanted not in ids:
            return False
    if status_filter:
        wanted_status = str(status_filter).strip().lower()
        actual = {
            chart_status(row),
            str(row.get("overall_status") or "").lower(),
            str(row.get("status") or "").lower(),
        }
        if wanted_status not in actual:
            return False
    return True


def _personal_checklist_counts(row: Mapping[str, Any], employee_id: int) -> tuple[int, int]:
    """This employee's required check-offs. A partner's check does not count."""
    done_states = {"completed", "approved", "verified", "pending_approval", "pending_verification"}
    items = [
        item
        for item in (row.get("shared_checklist_items") or [])
        if isinstance(item, Mapping) and item.get("required", True)
    ]
    if not items:
        templates = [
            item
            for item in (row.get("activity_group_items") or [])
            if isinstance(item, Mapping) and item.get("required", True) and item.get("task_code")
        ]
        return 0, len(templates)
    done = 0
    for item in items:
        checks = [check for check in (item.get("employee_checks") or []) if isinstance(check, Mapping)]
        mine = [check for check in checks if int(check.get("user_id") or 0) == int(employee_id)]
        if mine:
            if str(mine[0].get("status") or "").lower() in done_states:
                done += 1
        elif not checks:
            completed_by = int(item.get("completed_by_user_id") or 0)
            if completed_by == int(employee_id) and str(item.get("status") or "").lower() in done_states:
                done += 1
    return done, len(items)


def build_employee_report(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """One shared Activity counts once in the overall total, and once per assigned employee."""
    people: dict[int, dict[str, Any]] = {}
    seen: set[str] = set()
    for row in rows or []:
        key = str(row.get("assignment_key") or id(row))
        seen.add(key)
        contributions = [c for c in (row.get("contributions") or []) if isinstance(c, Mapping)]
        if not contributions:
            continue
        for contrib in contributions:
            eid = int(contrib.get("employee_id") or contrib.get("user_id") or 0)
            if not eid:
                continue
            part = str(contrib.get("participation_status") or "not_started")
            if row.get("verification_eligible") is False:
                own_verification = str(row.get("verification_status") or "not_required")
                verification_label = str(row.get("verification_label") or "")
            else:
                own_verification = str(contrib.get("verification_status") or row.get("verification_status") or "")
                verification_label = str(contrib.get("verification_label") or row.get("verification_label") or "")
            checklist_done, checklist_required = _personal_checklist_counts(row, eid)
            person = people.setdefault(
                eid,
                {
                    "employee_id": eid,
                    "employee_name": str(contrib.get("employee_name") or f"User #{eid}"),
                    "assigned": 0,
                    "completed": 0,
                    "in_progress": 0,
                    "not_started": 0,
                    "verified": 0,
                    "activities": [],
                },
            )
            person["assigned"] += 1
            if part == "finished":
                person["completed"] += 1
            elif part == "in_progress":
                person["in_progress"] += 1
            else:
                person["not_started"] += 1
            if part == "finished" and own_verification == "verified":
                person["verified"] += 1
            act = contrib.get("activity") if isinstance(contrib.get("activity"), Mapping) else {}
            person["activities"].append(
                {
                    "assignment_key": key,
                    "activity": str(row.get("role_label") or row.get("role") or ""),
                    "business_date": str(row.get("business_date") or ""),
                    "status": part,
                    "status_label": _REPORT_STATUS_LABELS.get(part, part.replace("_", " ").title()),
                    "verification_status": own_verification,
                    "verification_label": verification_label,
                    "participation_status": part,
                    "started_at": act.get("started_at"),
                    "ended_at": act.get("ended_at"),
                    "duration_seconds": act.get("duration_seconds"),
                    "checklist_done": checklist_done,
                    "checklist_required": checklist_required,
                    "checklist_completed_by_employee": checklist_done,
                }
            )
    employees = sorted(people.values(), key=lambda person: person["employee_name"].lower())
    return {"unique_activities": len(seen), "employees": employees}


def build_activity_frequency(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Activity first, then dates. A shared Activity is one occurrence per day."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        role = str(row.get("role") or "")
        label = str(row.get("role_label") or role or "Activity")
        bucket = groups.setdefault(
            role or label,
            {"role": role, "activity": label, "assigned": 0, "completed": 0, "dates": []},
        )
        bucket["assigned"] += 1
        status = chart_status(row)
        if assignment_is_completed(row) or status in {"verified", "pending_verification"}:
            bucket["completed"] += 1
        employees = [str(name) for name in (row.get("assigned_employees") or []) if name]
        bucket["dates"].append(
            {
                "business_date": str(row.get("business_date") or ""),
                "status": status,
                "status_label": _REPORT_STATUS_LABELS.get(status, str(row.get("status_label") or status)),
                "employees": employees,
            }
        )
    out = []
    for bucket in groups.values():
        assigned = int(bucket["assigned"])
        completed = int(bucket["completed"])
        bucket["completion_rate"] = round((completed / assigned) * 100, 1) if assigned else None
        bucket["dates"].sort(key=lambda item: str(item.get("business_date") or ""), reverse=True)
        out.append(bucket)
    out.sort(key=lambda bucket: str(bucket.get("activity") or "").lower())
    return out


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
    assignment_offset: int = 0,
    assignment_limit: int | None = None,
    history_offset: int = 0,
    history_limit: int | None = None,
    employee_id: int | None = None,
    activity: str | None = None,
    status_filter: str | None = None,
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
        start, end = resolve_task_dashboard_range(start_date, end_date)
    else:
        start, end = _month_bounds(y, m)
    oid = int(organization_id)
    catalog = _role_catalog(cursor, oid)
    cat_filter = (str(category_code or "").strip() or None)
    activity_filter = (str(activity or "").strip() or None)
    try:
        employee_filter = int(employee_id) if employee_id not in (None, "") else None
    except (TypeError, ValueError):
        employee_filter = None
    status_value = (str(status_filter or "").strip().lower() or None)
    _prime_activities_for_range(cursor, oid, start, end)
    want_history = (not rinse_eligible_only) and (history_limit is None or int(history_limit) > 0)
    option_activities: dict[str, str] = {}
    option_employees: dict[int, str] = {}

    days: list[dict[str, Any]] = []
    collected: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    category_cache: dict[str, str] = {}
    participation = {
        "employees_assigned": 0,
        "employees_started": 0,
        "employees_finished": 0,
        "total_time_seconds": 0,
    }
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
        _remember_filter_options(shared, option_activities, option_employees)
        if employee_filter or activity_filter or status_value:
            shared = [
                row
                for row in shared
                if _row_matches_filters(
                    row,
                    employee_id=employee_filter,
                    activity=activity_filter,
                    status_filter=status_value,
                )
            ]

        roll = participation_rollup(shared)
        for key, value in roll.items():
            participation[key] += int(value)
        if want_history:
            for row in activities:
                role = str(row.get("role") or "")
                if role not in category_cache:
                    meta = _task_meta_for_role(cursor, oid, role)
                    category_cache[role] = str((meta or {}).get("category_code") or "intra_day")
                if cat_filter and category_cache[role] != cat_filter:
                    continue
                item = serialize_activity(row, catalog=catalog)
                item["employee_name"] = names.get(int(item["user_id"]), f"User #{item['user_id']}")
                item["category_code"] = item.get("category_code") or category_cache[role]
                item["verification_label"] = history_verification_label(item)
                if employee_filter and int(item.get("user_id") or 0) != employee_filter:
                    continue
                if activity_filter:
                    role_name = str(item.get("role") or "").lower()
                    role_label = str(item.get("role_label") or "").lower()
                    if activity_filter.lower() not in {role_name, role_label}:
                        continue
                history.append(item)

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
            "completed": 0,
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

    history.sort(
        key=lambda item: (str(item.get("business_date") or ""), int(item.get("id") or 0)),
        reverse=True,
    )
    if rinse_eligible_only:
        history = []
        participation["total_time_seconds"] = 0
    assignment_rows = collected if include_assignments else []
    return {
        "year": y,
        "month": m,
        "month_start": str(start),
        "month_end": str(end),
        "range_start": str(start),
        "range_end": str(end),
        "span_days": (end - start).days + 1,
        "truncated": False,
        "category_code": cat_filter,
        "categories": [{"code": c["code"], "name": c["name"]} for c in categories],
        "assignment_total": len(collected),
        "assignments": page_rows(assignment_rows, assignment_offset, assignment_limit)
        if include_assignments
        else [],
        "history_total": len(history),
        "history": page_rows(history, history_offset, history_limit),
        "participation": participation,
        "days": days,
        "buckets": stack_chart_buckets(days, group_by),
        "group_by": str(group_by or "daily"),
        "totals": {**totals, "completion_rate": overall_rate},
        "employee_report": build_employee_report(collected),
        "activity_frequency": build_activity_frequency(collected),
        "filter_options": {
            "activities": [
                {"role": role, "label": label}
                for role, label in sorted(option_activities.items(), key=lambda item: item[1].lower())
            ],
            "employees": [
                {"employee_id": eid, "employee_name": name}
                for eid, name in sorted(option_employees.items(), key=lambda item: item[1].lower())
            ],
        },
    }
