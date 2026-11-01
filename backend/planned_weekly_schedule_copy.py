"""Copy one planned shift onto other employees and weekdays in the same week.

The copy is scheduled data only: shift times, breaks, role segments, task
participation, activity-group membership, and checklist responsibility for the
destination date. Each destination row is its own assignment. Attendance,
completed check-offs, activity timers, verification, and payroll are not read
for copying and are not written.

Shifts are stored per schedule week (``week_start`` + ``day_of_week``), not as
a recurring weekday template on the row. Later weeks change only when this week
is the org's active template source, and that sync is the same hook every other
schedule write already uses.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import (
    DAY_LABELS,
    delete_entry,
    get_entry,
    list_week_entries,
    normalize_day_of_week,
)
from backend.planned_weekly_schedule_responsibilities import (
    EXECUTION_INDIVIDUAL,
    TABLE as RESP_TABLE,
    _insert_member,
    delete_responsibility,
    list_week_responsibilities,
)
from backend.planned_weekly_schedule_task_timing import TIMING_ANYTIME, evaluate_task_timing

CONFLICT_SKIP = "skip"
CONFLICT_REPLACE = "replace"
CONFLICT_MODES = frozenset({CONFLICT_SKIP, CONFLICT_REPLACE})

RESOLUTION_SKIP = "skip"
RESOLUTION_CHECKLIST = "copy_schedule_only"
RESOLUTION_WITHOUT_CHECKLIST = "copy_without_checklist"
RESOLUTIONS = frozenset({RESOLUTION_SKIP, RESOLUTION_CHECKLIST, RESOLUTION_WITHOUT_CHECKLIST})

_COMPLETED_SESSION = frozenset({"completed", "approved", "verified"})


def format_copy_message(*, created: int, replaced: int, skipped: int) -> str:
    copied = int(created) + int(replaced)
    shift_word = "shift" if copied == 1 else "shifts"
    parts = [f"{copied} {shift_word} copied"]
    if replaced:
        parts[0] += f" ({replaced} replaced)"
    if skipped:
        parts.append(f"{skipped} skipped")
    return ", ".join(parts) + "."


def _resolution_map(resolutions: Sequence[Mapping[str, Any]] | None) -> dict[tuple[int, int], str]:
    out: dict[tuple[int, int], str] = {}
    for item in resolutions or []:
        if not isinstance(item, Mapping):
            continue
        try:
            key = (int(item.get("user_id")), int(item.get("day_of_week")))
        except (TypeError, ValueError):
            continue
        action = str(item.get("action") or "").strip()
        if action in RESOLUTIONS:
            out[key] = action
    return out


def _parse_targets(
    *,
    user_ids: Sequence[Any],
    days_of_week: Sequence[Any],
) -> tuple[list[int], list[int], str | None]:
    users: list[int] = []
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            return [], [], "user_ids must be employee ids"
        if uid > 0 and uid not in users:
            users.append(uid)
    days: list[int] = []
    for raw in days_of_week or []:
        dow = normalize_day_of_week(raw)
        if dow is None:
            return [], [], "days must be 0-6 (Sun-Sat)"
        if dow not in days:
            days.append(dow)
    if not users:
        return [], [], "Choose at least one employee."
    if not days:
        return [], [], "Choose at least one day."
    return users, days, None


def _role_label(catalog: Mapping[str, Mapping[str, Any]], code: str) -> str:
    info = catalog.get(code) or {}
    return str(info.get("name") or code)


def _source_tasks(responsibilities: Sequence[Mapping[str, Any]], *, user_id: int, day: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in responsibilities
        if int(row.get("user_id") or 0) == int(user_id) and int(row.get("day_of_week") or 0) == int(day)
    ]


def _entries_for(
    entries: Sequence[Mapping[str, Any]],
    *,
    user_id: int,
    day: int,
    week_start: date,
) -> list[dict[str, Any]]:
    week = str(week_start)
    return [
        dict(row)
        for row in entries
        if int(row.get("user_id") or 0) == int(user_id)
        and int(row.get("day_of_week") or 0) == int(day)
        and str(row.get("week_start") or "")[:10] == week
    ]


def _shift_payload(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "start_time": source.get("start_time"),
        "end_time": source.get("end_time"),
        "break_slots": list(source.get("break_slots") or []),
        "unscheduled_break_minutes": int(source.get("unscheduled_break_minutes") or 0),
    }


def _checklist_for_role_date(cursor, organization_id: int, role: str, business_date: date) -> dict[str, Any]:
    """Resolved checklist for one activity on one date. Sessions are read, never written."""
    from backend.task_activity_groups import get_activity_group
    from backend.task_activity_item_responsibility import (
        load_overrides_for_items,
        load_session_items_for_role_date,
        resolve_responsibility,
    )

    try:
        group = get_activity_group(cursor, int(organization_id), role_code=role)
    except Exception:
        return {"error": "Activity group could not be read", "items": [], "open_session": False}
    if not group:
        return {"error": "Activity group definition was not found", "items": [], "open_session": False}
    members = list(group.get("items") or [])
    try:
        overrides = load_overrides_for_items(
            cursor,
            int(organization_id),
            [int(item.get("id") or 0) for item in members],
            business_date,
        )
        sessions = load_session_items_for_role_date(cursor, int(organization_id), role, business_date)
    except Exception:
        return {"error": "Checklist responsibility could not be read", "items": [], "open_session": False}
    session_by_code = {str(row.get("task_code") or ""): row for row in sessions}
    open_session = any(str(row.get("status") or "") not in _COMPLETED_SESSION for row in sessions)
    items = []
    for member in members:
        item_id = int(member.get("id") or 0)
        payload = resolve_responsibility(member, overrides.get(item_id))
        code = str(member.get("task_code") or "")
        items.append(
            {
                "group_item_id": item_id,
                "task_code": code,
                "task_name": member.get("task_name") or member.get("name") or code,
                "responsibility_mode": payload.get("responsibility_mode"),
                "responsibility_user_ids": list(payload.get("responsibility_user_ids") or []),
                "responsibility_label": payload.get("responsibility_label"),
                "date_override": item_id in overrides,
                "open_session_item": code in session_by_code
                and str((session_by_code.get(code) or {}).get("status") or "") not in _COMPLETED_SESSION,
            }
        )
    return {"error": None, "items": items, "open_session": open_session}


def plan_checklist_transfer(
    *,
    source_user_id: int,
    dest_user_id: int,
    same_date: bool,
    source_items: Sequence[Mapping[str, Any]],
    dest_items: Sequence[Mapping[str, Any]],
    dest_roster: Sequence[int],
) -> dict[str, Any]:
    """Date overrides that name the destination where the source is specifically responsible.

    Master activity items are not changed. A different day gets its own override and does not
    rewrite the source date. Existing destination names stay when those employees are still on
    the activity. An override that already names someone off the roster is a conflict.
    """
    roster = {int(uid) for uid in dest_roster}
    dest_by_id = {int(item.get("group_item_id") or 0): item for item in dest_items or []}
    overrides: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for item in source_items or []:
        mode = str(item.get("responsibility_mode") or "team")
        named = [int(uid) for uid in (item.get("responsibility_user_ids") or [])]
        if mode != "named" or int(source_user_id) not in named:
            continue
        dest_item = dest_by_id.get(int(item.get("group_item_id") or 0)) or {}
        if same_date:
            current = list(named)
        elif dest_item.get("date_override"):
            current = [int(uid) for uid in (dest_item.get("responsibility_user_ids") or [])]
        else:
            current = []
        off_roster = [uid for uid in current if uid not in roster and uid != int(dest_user_id)]
        label = item.get("task_name") or item.get("task_code")
        if off_roster:
            issues.append(
                {
                    "code": "checklist_ineligible",
                    "task_code": item.get("task_code"),
                    "task_name": label,
                    "message": (
                        f"Checklist item {label} already names an employee who is not on this day's activity. "
                        "Copying responsibility would change that list."
                    ),
                    "choices": [RESOLUTION_SKIP, RESOLUTION_WITHOUT_CHECKLIST],
                }
            )
            continue
        kept: list[int] = []
        for uid in current:
            if uid not in kept:
                kept.append(uid)
        if same_date and int(source_user_id) not in kept:
            kept.insert(0, int(source_user_id))
        if int(dest_user_id) not in kept:
            kept.append(int(dest_user_id))
        overrides.append(
            {
                "group_item_id": int(item.get("group_item_id") or 0),
                "task_code": item.get("task_code"),
                "task_name": label,
                "responsibility_mode": "named",
                "user_ids": kept,
            }
        )
    return {"overrides": overrides, "issues": issues}


def _persist_checklist_overrides(
    cursor,
    organization_id: int,
    *,
    business_date: date,
    overrides: Sequence[Mapping[str, Any]],
) -> None:
    """Write the destination date only. Does not touch master items or session snapshots."""
    if not overrides:
        return
    from backend.task_activity_item_responsibility import ensure_item_responsibility_schema

    ensure_item_responsibility_schema(cursor)
    for item in overrides:
        cursor.execute(
            """
            INSERT INTO task_activity_item_date_overrides
              (organization_id, group_item_id, business_date, responsibility_mode, user_ids_json)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              responsibility_mode=VALUES(responsibility_mode),
              user_ids_json=VALUES(user_ids_json)
            """,
            (
                int(organization_id),
                int(item.get("group_item_id") or 0),
                business_date,
                "named",
                json.dumps([int(uid) for uid in (item.get("user_ids") or [])]),
            ),
        )


def _task_summary(task: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    role = str(task.get("role") or "")
    return {
        "role": role,
        "label": _role_label(catalog, role),
        "remarks": task.get("remarks"),
        "timing_mode": task.get("timing_mode") or TIMING_ANYTIME,
        "start_time": task.get("start_time"),
        "timing_label": task.get("timing_label") or "",
        "execution_mode": task.get("execution_mode") or EXECUTION_INDIVIDUAL,
        "shared": str(task.get("execution_mode") or "") == "shared" and len(task.get("user_ids") or []) >= 2,
        "activity_group": role.startswith("agroup_"),
        "checklist_items": list(task.get("checklist_items") or []),
    }


def _source_summary(source: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]], catalog, names) -> dict[str, Any]:
    uid = int(source.get("user_id") or 0)
    day = int(source.get("day_of_week") or 0)
    return {
        "entry_id": int(source.get("id") or 0),
        "user_id": uid,
        "employee_name": names.get(uid) or f"User #{uid}",
        "day_of_week": day,
        "day_label": DAY_LABELS[day],
        "week_start": str(source.get("week_start") or "")[:10],
        "start_time": source.get("start_time"),
        "end_time": source.get("end_time"),
        "break_minutes": int(source.get("break_minutes") or 0),
        "break_slots": list(source.get("break_slots") or []),
        "unscheduled_break_minutes": int(source.get("unscheduled_break_minutes") or 0),
        "assignments": list(source.get("assignments") or []),
        "employer_affiliation": source.get("employer_affiliation"),
        "tasks": [_task_summary(task, catalog) for task in tasks],
    }


def _issue(code: str, message: str, choices: Sequence[str]) -> dict[str, Any]:
    return {"code": code, "message": message, "choices": list(choices)}


def _merge_choices(issues: Sequence[Mapping[str, Any]]) -> list[str]:
    sets = [set(issue.get("choices") or []) for issue in issues if issue.get("choices")]
    if not sets:
        return [RESOLUTION_SKIP]
    allowed = set.intersection(*sets) if sets else {RESOLUTION_SKIP}
    if RESOLUTION_SKIP not in allowed:
        allowed.add(RESOLUTION_SKIP)
    order = [RESOLUTION_SKIP, RESOLUTION_WITHOUT_CHECKLIST, RESOLUTION_CHECKLIST]
    return [choice for choice in order if choice in allowed]


def preview_copy_shift(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    *,
    user_ids: Sequence[Any],
    days_of_week: Sequence[Any],
    conflict_mode: str = CONFLICT_SKIP,
    resolutions: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    mode = str(conflict_mode or CONFLICT_SKIP).strip().lower()
    if mode not in CONFLICT_MODES:
        return None, "conflict_mode must be skip or replace"
    users, days, err = _parse_targets(user_ids=user_ids, days_of_week=days_of_week)
    if err:
        return None, err
    source = get_entry(cursor, organization_id, int(entry_id), conn=conn)
    if not source:
        return None, "schedule entry not found"
    week_start = date.fromisoformat(str(source["week_start"])[:10])
    from backend.planned_weekly_schedule import _load_role_catalog_index
    from backend.planned_weekly_schedule_responsibilities import _worker_names
    from backend.task_activity_item_responsibility import business_date_for_week
    from backend.weekly_schedule_roles import role_assignment_error

    catalog = _load_role_catalog_index(cursor, organization_id)
    responsibilities = list_week_responsibilities(cursor, organization_id, week_start=week_start)
    entries = list_week_entries(cursor, organization_id, week_start=week_start, conn=conn)
    source_day = int(source["day_of_week"])
    source_user = int(source["user_id"])
    tasks = _source_tasks(responsibilities, user_id=source_user, day=source_day)
    try:
        from backend.task_activity_item_responsibility import attach_checklist_responsibilities

        tasks = attach_checklist_responsibilities(cursor, organization_id, tasks)
    except Exception:
        pass
    everyone = users + [source_user]
    names = _worker_names(conn, organization_id, everyone)
    chosen = _resolution_map(resolutions)
    from backend.planned_weekly_schedule import _assert_worker_in_org, _assert_worker_schedulable

    targets: list[dict[str, Any]] = []
    for uid in users:
        worker_err = _assert_worker_in_org(conn, organization_id, uid)
        sched_err = None if worker_err else _assert_worker_schedulable(conn, organization_id, uid)
        for day in days:
            existing_shifts = [
                row
                for row in _entries_for(entries, user_id=uid, day=day, week_start=week_start)
                if int(row.get("id") or 0) != int(source.get("id") or 0)
            ]
            existing_tasks = _source_tasks(responsibilities, user_id=uid, day=day)
            colliding = [
                row
                for row in existing_tasks
                if str(row.get("role") or "") in {str(task.get("role") or "") for task in tasks}
            ]
            issues: list[dict[str, Any]] = []
            notes: list[str] = []
            checklist_overrides: list[dict[str, Any]] = []
            if uid == source_user and day == source_day:
                targets.append(
                    _target_row(
                        uid,
                        day,
                        names,
                        action="skip",
                        reason="Source shift",
                        existing_shift_count=len(existing_shifts) + 1,
                        issues=[],
                        notes=[],
                        checklist_overrides=[],
                    )
                )
                continue
            if worker_err or sched_err:
                issues.append(
                    _issue(
                        "worker",
                        worker_err or sched_err or "Employee cannot be scheduled",
                        [RESOLUTION_SKIP],
                    )
                )
            for task in tasks:
                role = str(task.get("role") or "")
                label = _role_label(catalog, role)
                task_err = role_assignment_error(role, catalog, timed=False, already_assigned=False)
                if task_err:
                    issues.append(_issue("inactive_task", task_err, [RESOLUTION_SKIP]))
                timing_errors, timing_warnings = evaluate_task_timing(
                    timing_mode=str(task.get("timing_mode") or TIMING_ANYTIME),
                    start_time=task.get("start_time"),
                    members=[{"name": names.get(uid) or f"User #{uid}", "shifts": [_shift_payload(source)]}],
                )
                for warning in timing_warnings:
                    notes.append(warning)
                for timing_err in timing_errors:
                    issues.append(_issue("timing", f"{label}: {timing_err}", [RESOLUTION_SKIP]))
                if task.get("execution_mode") == "shared" and len(task.get("user_ids") or []) >= 2:
                    notes.append(
                        f"{label} is copied as {names.get(uid) or 'the employee'}'s own assignment. "
                        "The original team is unchanged."
                    )
                if role.startswith("agroup_"):
                    source_date = business_date_for_week(week_start, source_day)
                    dest_date = business_date_for_week(week_start, day)
                    source_loaded = _checklist_for_role_date(cursor, organization_id, role, source_date)
                    dest_loaded = (
                        source_loaded
                        if dest_date == source_date
                        else _checklist_for_role_date(cursor, organization_id, role, dest_date)
                    )
                    if source_loaded.get("error") or dest_loaded.get("error"):
                        detail = source_loaded.get("error") or dest_loaded.get("error")
                        issues.append(
                            _issue(
                                "checklist_unreadable",
                                f"{label}: {detail}. Checklist responsibility was not copied.",
                                [RESOLUTION_SKIP, RESOLUTION_WITHOUT_CHECKLIST],
                            )
                        )
                    else:
                        roster = [
                            int(row.get("user_id") or 0)
                            for row in responsibilities
                            if int(row.get("day_of_week") or 0) == day
                            and str(row.get("role") or "") == role
                            and int(row.get("user_id") or 0) != uid
                        ]
                        roster.append(uid)
                        planned = plan_checklist_transfer(
                            source_user_id=source_user,
                            dest_user_id=uid,
                            same_date=dest_date == source_date,
                            source_items=source_loaded.get("items") or [],
                            dest_items=dest_loaded.get("items") or [],
                            dest_roster=roster,
                        )
                        checklist_overrides.extend(planned["overrides"])
                        issues.extend(planned["issues"])
                        if dest_loaded.get("open_session") and planned["overrides"]:
                            issues.append(
                                _issue(
                                    "open_checklist",
                                    f"{label} has an open checklist on this date. "
                                    "The scheduled names can be updated. Completed check-offs and the open session record stay as they are.",
                                    [RESOLUTION_SKIP, RESOLUTION_CHECKLIST],
                                )
                            )
            action, reason = _classify(
                mode=mode,
                existing_shifts=existing_shifts,
                colliding=colliding,
                catalog=catalog,
                issues=issues,
                resolution=chosen.get((uid, day)),
            )
            if action == "needs_resolution" and not reason:
                reason = issues[0]["message"] if issues else "Resolve this assignment before copying."
            targets.append(
                _target_row(
                    uid,
                    day,
                    names,
                    action=action,
                    reason=reason,
                    existing_shift_count=len(existing_shifts),
                    issues=issues,
                    notes=list(dict.fromkeys(notes)),
                    checklist_overrides=checklist_overrides,
                    choices=_merge_choices(issues) if issues else [],
                )
            )
    counts = {
        "create": sum(1 for row in targets if row["action"] == "create"),
        "replace": sum(1 for row in targets if row["action"] == "replace"),
        "skip": sum(1 for row in targets if row["action"] == "skip"),
        "needs_resolution": sum(1 for row in targets if row["action"] == "needs_resolution"),
    }
    return {
        "conflict_mode": mode,
        "source": _source_summary(source, tasks, catalog, names),
        "counts": counts,
        "targets": targets,
        "message": format_copy_message(
            created=counts["create"],
            replaced=counts["replace"],
            skipped=counts["skip"],
        ),
    }, None


def _classify(
    *,
    mode: str,
    existing_shifts: Sequence[Mapping[str, Any]],
    colliding: Sequence[Mapping[str, Any]],
    catalog,
    issues: Sequence[Mapping[str, Any]],
    resolution: str | None,
) -> tuple[str, str]:
    remaining = list(issues)
    allowed = set(_merge_choices(issues)) if issues else set()
    if issues and resolution == RESOLUTION_SKIP:
        return "skip", issues[0]["message"]
    if resolution and resolution in allowed:
        if resolution == RESOLUTION_WITHOUT_CHECKLIST:
            remaining = [
                issue
                for issue in remaining
                if issue.get("code") not in {"checklist_unreadable", "checklist_ineligible"}
            ]
        elif resolution == RESOLUTION_CHECKLIST:
            remaining = [issue for issue in remaining if issue.get("code") != "open_checklist"]
    if remaining:
        return "needs_resolution", str(remaining[0].get("message") or "Resolve this assignment before copying.")
    conflict = bool(existing_shifts or colliding)
    if not conflict:
        return "create", ""
    labels = []
    if existing_shifts:
        labels.append(
            f"{len(existing_shifts)} existing shift{'s' if len(existing_shifts) != 1 else ''}"
        )
    for row in colliding:
        labels.append(_role_label(catalog, str(row.get("role") or "")))
    detail = ", ".join(labels)
    if mode == CONFLICT_REPLACE:
        return "replace", f"Replaces {detail}"
    return "skip", f"Skipped: {detail}"


def _target_row(
    uid: int,
    day: int,
    names: Mapping[int, str],
    *,
    action: str,
    reason: str,
    existing_shift_count: int,
    issues: Sequence[Mapping[str, Any]],
    notes: Sequence[str],
    checklist_overrides: Sequence[Mapping[str, Any]],
    choices: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "user_id": uid,
        "day_of_week": day,
        "employee_name": names.get(uid) or f"User #{uid}",
        "day_label": DAY_LABELS[day],
        "action": action,
        "reason": reason,
        "existing_shift_count": existing_shift_count,
        "issues": [dict(issue) for issue in issues],
        "choices": list(choices or []),
        "notes": list(notes),
        "checklist_overrides": [dict(item) for item in checklist_overrides],
    }


def _copy_entry_data(source: Mapping[str, Any], *, user_id: int, day: int) -> dict[str, Any]:
    data: dict[str, Any] = {
        "user_id": int(user_id),
        "day_of_week": int(day),
        "assignments": list(source.get("assignments") or []),
        "start_time": source.get("start_time"),
        "end_time": source.get("end_time"),
        "break_minutes": source.get("break_minutes") or 0,
        "break_slots": list(source.get("break_slots") or []),
        "unscheduled_break_minutes": int(source.get("unscheduled_break_minutes") or 0),
    }
    if source.get("employer_affiliation"):
        data["employer_affiliation"] = source.get("employer_affiliation")
    return data


def apply_copy_shift(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    *,
    user_ids: Sequence[Any],
    days_of_week: Sequence[Any],
    conflict_mode: str = CONFLICT_SKIP,
    confirm_replace: bool = False,
    resolutions: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    preview, err = preview_copy_shift(
        conn,
        cursor,
        organization_id,
        entry_id,
        user_ids=user_ids,
        days_of_week=days_of_week,
        conflict_mode=conflict_mode,
        resolutions=resolutions,
    )
    if err or preview is None:
        return None, err or "Could not preview this copy"
    if preview["counts"]["needs_resolution"]:
        return None, "Resolve flagged assignments before copying."
    if preview["counts"]["replace"] and not confirm_replace:
        return None, "Confirm replacement before replacing existing shifts."
    source = get_entry(cursor, organization_id, int(entry_id), conn=conn)
    if not source:
        return None, "schedule entry not found"
    week_start = date.fromisoformat(str(source["week_start"])[:10])
    source_user = int(source["user_id"])
    source_day = int(source["day_of_week"])
    from backend.planned_weekly_schedule import create_entry
    from backend.task_activity_item_responsibility import business_date_for_week

    responsibilities = list_week_responsibilities(cursor, organization_id, week_start=week_start)
    tasks = _source_tasks(responsibilities, user_id=source_user, day=source_day)
    entries = list_week_entries(cursor, organization_id, week_start=week_start, conn=conn)
    created_ids: list[int] = []
    replaced = 0
    skipped_targets: list[dict[str, Any]] = []
    checklist_written: list[dict[str, Any]] = []
    for target in preview["targets"]:
        action = target["action"]
        uid = int(target["user_id"])
        day = int(target["day_of_week"])
        if action == "skip":
            skipped_targets.append(
                {
                    "user_id": uid,
                    "day_of_week": day,
                    "employee_name": target["employee_name"],
                    "day_label": target["day_label"],
                    "reason": target["reason"] or "Skipped",
                }
            )
            continue
        if action != "create" and action != "replace":
            return None, "Resolve flagged assignments before copying."
        if action == "replace":
            replaced += 1
            for row in _entries_for(entries, user_id=uid, day=day, week_start=week_start):
                if int(row.get("id") or 0) != int(source.get("id") or 0):
                    delete_entry(cursor, organization_id, int(row["id"]))
            source_roles = {str(task.get("role") or "") for task in tasks}
            for row in _source_tasks(responsibilities, user_id=uid, day=day):
                if str(row.get("role") or "") in source_roles:
                    delete_responsibility(cursor, organization_id, int(row["id"]))
        entry, create_err = create_entry(
            conn,
            cursor,
            organization_id,
            week_start=week_start,
            data=_copy_entry_data(source, user_id=uid, day=day),
            preserve_assignments=list(source.get("assignments") or []),
        )
        if create_err or not entry:
            return None, create_err or "Could not copy the shift"
        created_ids.append(int(entry["id"]))
        chosen = _resolution_map(resolutions).get((uid, day))
        write_checklist = chosen != RESOLUTION_WITHOUT_CHECKLIST
        for task in tasks:
            new_id = _insert_member(
                cursor,
                organization_id,
                week_start=week_start,
                user_id=uid,
                day_of_week=day,
                role=str(task.get("role") or ""),
                remarks=task.get("remarks"),
                assignment_group_id=uuid.uuid4().hex,
                timing_mode=str(task.get("timing_mode") or TIMING_ANYTIME),
                start_time=task.get("start_time"),
                execution_mode=EXECUTION_INDIVIDUAL,
            )
            cursor.execute(
                f"""
                UPDATE {RESP_TABLE}
                SET display_order=%s
                WHERE organization_id=%s AND id=%s AND user_id=%s AND day_of_week=%s
                """,
                (
                    int(task.get("display_order") or 0),
                    int(organization_id),
                    int(new_id),
                    uid,
                    day,
                ),
            )
        if write_checklist and target.get("checklist_overrides"):
            business_date = business_date_for_week(week_start, day)
            _persist_checklist_overrides(
                cursor,
                organization_id,
                business_date=business_date,
                overrides=target["checklist_overrides"],
            )
            for item in target["checklist_overrides"]:
                checklist_written.append({**item, "business_date": business_date.isoformat(), "user_id": uid, "day_of_week": day})
        # Refresh local snapshots so a later target in this batch sees the new rows.
        responsibilities = list_week_responsibilities(cursor, organization_id, week_start=week_start)
        entries = list_week_entries(cursor, organization_id, week_start=week_start, conn=conn)
    created = len(created_ids)
    skipped = len(skipped_targets)
    return {
        "created": created - replaced,
        "replaced": replaced,
        "skipped": skipped,
        "entry_ids": created_ids,
        "skipped_targets": skipped_targets,
        "checklist_overrides": checklist_written,
        "message": format_copy_message(created=created - replaced, replaced=replaced, skipped=skipped),
        "week_start": week_start.isoformat(),
    }, None
