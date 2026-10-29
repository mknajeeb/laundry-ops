"""PIN Tasks execution on top of weekly schedule assignments.

Assignments stay in ``planned_weekly_schedule_responsibilities``. This module
tracks per-employee start/complete timers, optional verification, inputs, and
dashboard metrics without changing payroll clock-in/out.

Table names retain the ``cleaning_task_*`` prefix for backward compatibility.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional, Sequence

from backend.business_time import business_now, business_today
from backend.payroll_identity import eastern_now_naive
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import (
    assignment_key,
    ensure_responsibilities_table,
    list_week_responsibilities,
)
from backend.planned_weekly_schedule_task_timing import TIMING_LABELS, timing_display
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column
from backend.task_catalog import (
    COMPLETION_INPUT,
    COMPLETION_SIMPLE,
    VERIFY_EMPLOYEE,
    VERIFY_NONE,
    VERIFY_ROLE,
    VERIFY_SUPERVISOR,
    VERIFY_TIMING_NEXT_DAY,
    get_task_definition,
    list_categories,
    list_task_definitions,
    seed_builtin_categories,
    validate_completion_input,
    TaskCatalogError,
)
from backend.weekly_schedule_roles import catalog_index, is_task_role, list_role_catalog

TABLE = "cleaning_task_activities"
EVENTS = "cleaning_task_activity_events"


def _role_catalog(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    return catalog_index(list_role_catalog(cursor, int(organization_id)))


def _role_label(code: Any, catalog: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    key = str(code or "").strip()
    if not key:
        return ""
    info = (catalog or {}).get(key) or {}
    return str(info.get("name") or key).strip() or key


def _minutes(value: Any) -> int | None:
    text = str(value or "")[:5]
    if len(text) < 4 or ":" not in text:
        return None
    try:
        hour, minute = int(text[:2]), int(text[3:5])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute

STATUS_IN_PROGRESS = "in_progress"
STATUS_PENDING_APPROVAL = "pending_approval"  # pending verification
STATUS_APPROVED = "approved"  # verified
STATUS_COMPLETED = "completed"  # done, no verification required
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = frozenset({STATUS_IN_PROGRESS})
COMPLETED_STATUSES = frozenset(
    {STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_REJECTED, STATUS_COMPLETED}
)
TERMINAL_OK_STATUSES = frozenset({STATUS_APPROVED, STATUS_COMPLETED})
OPEN_OR_PENDING = frozenset({STATUS_IN_PROGRESS, STATUS_PENDING_APPROVAL})

DISPLAY_PENDING = "pending"
DISPLAY_IN_PROGRESS = "in_progress"
DISPLAY_PENDING_APPROVAL = "pending_approval"  # UI: Pending Verification
DISPLAY_APPROVED = "approved"  # UI: Verified
DISPLAY_COMPLETED = "completed"
DISPLAY_REJECTED = "rejected"
DISPLAY_OVERDUE = "overdue"

_ACTIVITY_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("category_code", "VARCHAR(40) NULL"),
    ("completion_type", "VARCHAR(32) NULL"),
    ("timer_enabled", "TINYINT(1) NULL"),
    ("verification_required", "TINYINT(1) NULL"),
    ("verification_method", "VARCHAR(32) NULL"),
    ("verification_timing", "VARCHAR(32) NULL"),
    ("completion_input_json", "TEXT NULL"),
    ("checklist_id", "INT NULL"),
    ("parent_activity_id", "BIGINT NULL"),
    ("activity_kind", "VARCHAR(20) NULL"),
    ("completion_source", "VARCHAR(32) NOT NULL DEFAULT 'pin'"),
    ("recorded_by_user_id", "INT NULL"),
    ("manual_reason", "VARCHAR(500) NULL"),
    ("manual_remarks", "VARCHAR(1000) NULL"),
    ("times_manual", "TINYINT(1) NOT NULL DEFAULT 0"),
)


class CleaningTaskError(Exception):
    def __init__(self, message: str, *, status: int = 400, payload: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


def ensure_cleaning_task_activity_tables(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          responsibility_id INT NOT NULL,
          assignment_group_id VARCHAR(36) NULL,
          user_id INT NOT NULL,
          shift_session_id INT NULL,
          business_date DATE NOT NULL,
          role VARCHAR(64) NOT NULL,
          timing_mode VARCHAR(20) NOT NULL DEFAULT 'anytime',
          planned_start_time TIME NULL,
          status VARCHAR(32) NOT NULL,
          started_at DATETIME NOT NULL,
          ended_at DATETIME NULL,
          duration_seconds INT NULL,
          paused_category_id INT NULL,
          paused_role_id INT NULL,
          approved_by_user_id INT NULL,
          approved_at DATETIME NULL,
          rejection_reason VARCHAR(500) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_cta_org_date (organization_id, business_date),
          INDEX idx_cta_org_user_date (organization_id, user_id, business_date),
          INDEX idx_cta_org_status (organization_id, status),
          INDEX idx_cta_resp (responsibility_id),
          INDEX idx_cta_open_user (organization_id, user_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EVENTS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          activity_id BIGINT NOT NULL,
          event_type VARCHAR(40) NOT NULL,
          actor_user_id INT NULL,
          payload_json TEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_ctae_activity (activity_id),
          INDEX idx_ctae_org (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    for col, ddl in _ACTIVITY_EXTRA_COLUMNS:
        if not table_has_column(cursor, TABLE, col):
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
    invalidate_schema_cache()


def _dow_for_date(day: date) -> int:
    return (day.weekday() + 1) % 7


def _serialize_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    text = str(value)
    return text[:19] if text else None


def _serialize_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%H:%M")
        except Exception:
            pass
    return text[:5] if text else None


def _record_event(
    cursor,
    *,
    organization_id: int,
    activity_id: int,
    event_type: str,
    actor_user_id: int | None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    cursor.execute(
        f"""
        INSERT INTO {EVENTS}
          (organization_id, activity_id, event_type, actor_user_id, payload_json)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            int(activity_id),
            str(event_type),
            int(actor_user_id) if actor_user_id is not None else None,
            json.dumps(payload or {}, default=str) if payload else None,
        ),
    )


def _display_status(status: str) -> str:
    """Map storage status to operator-facing status labels used in PIN/UI."""
    return {
        STATUS_PENDING_APPROVAL: "pending_verification",
        STATUS_APPROVED: "verified",
        STATUS_COMPLETED: DISPLAY_COMPLETED,
        STATUS_REJECTED: DISPLAY_REJECTED,
        STATUS_IN_PROGRESS: DISPLAY_IN_PROGRESS,
    }.get(str(status or ""), str(status or ""))


def friendly_status_label(status: str | None, *, overdue: bool = False) -> str:
    """Management-facing status wording (never expose raw codes in UI)."""
    if overdue or str(status or "") == DISPLAY_OVERDUE:
        return "Overdue"
    key = _display_status(str(status or ""))
    return {
        "pending": "Not Started",
        "not_started": "Not Started",
        DISPLAY_IN_PROGRESS: "In Progress",
        "pending_verification": "Waiting for Verification",
        DISPLAY_PENDING_APPROVAL: "Waiting for Verification",
        "verified": "Verified",
        DISPLAY_APPROVED: "Verified",
        DISPLAY_COMPLETED: "Completed",
        DISPLAY_REJECTED: "Needs Correction",
        DISPLAY_OVERDUE: "Overdue",
    }.get(key, "Not Started")


def serialize_activity(row: Mapping[str, Any], *, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    mode = str(row.get("timing_mode") or "anytime")
    start = _serialize_time(row.get("planned_start_time"))
    status = str(row.get("status") or "")
    input_raw = row.get("completion_input_json")
    try:
        completion_input = json.loads(input_raw) if input_raw else None
    except (TypeError, ValueError, json.JSONDecodeError):
        completion_input = None
    return {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "responsibility_id": int(row.get("responsibility_id") or 0),
        "assignment_group_id": (str(row.get("assignment_group_id") or "").strip() or None),
        "user_id": int(row.get("user_id") or 0),
        "shift_session_id": int(row["shift_session_id"]) if row.get("shift_session_id") is not None else None,
        "business_date": str(row.get("business_date") or "")[:10],
        "role": str(row.get("role") or ""),
        "role_label": _role_label(row.get("role"), catalog),
        "category_code": (str(row.get("category_code") or "").strip() or None),
        "timing_mode": mode,
        "timing_label": timing_display(mode, start) or TIMING_LABELS.get(mode, ""),
        "planned_start_time": start,
        "status": status,
        "display_status": _display_status(status),
        "status_label": friendly_status_label(status),
        "started_at": _serialize_dt(row.get("started_at")),
        "ended_at": _serialize_dt(row.get("ended_at")),
        "duration_seconds": (
            None
            if (
                row.get("times_manual") in (1, True)
                and row.get("duration_seconds") is None
            )
            else (int(row["duration_seconds"]) if row.get("duration_seconds") is not None else None)
        ),
        "completion_source": str(row.get("completion_source") or "pin"),
        "completion_source_label": {
            "pin": "Completed via PIN",
            "manual": "Recorded by Supervisor",
            "corrected": "Corrected by Supervisor",
        }.get(str(row.get("completion_source") or "pin").lower(), "Completed via PIN"),
        "recorded_by_user_id": int(row["recorded_by_user_id"])
        if row.get("recorded_by_user_id") is not None
        else None,
        "manual_reason": (str(row.get("manual_reason") or "").strip() or None),
        "manual_remarks": (str(row.get("manual_remarks") or "").strip() or None),
        "times_manual": bool(row.get("times_manual")),
        "is_manual_completion": str(row.get("completion_source") or "pin").lower()
        in {"manual", "corrected"},
        "paused_category_id": int(row["paused_category_id"]) if row.get("paused_category_id") is not None else None,
        "paused_role_id": int(row["paused_role_id"]) if row.get("paused_role_id") is not None else None,
        "approved_by_user_id": int(row["approved_by_user_id"])
        if row.get("approved_by_user_id") is not None
        else None,
        "verified_by_user_id": int(row["approved_by_user_id"])
        if row.get("approved_by_user_id") is not None
        else None,
        "approved_at": _serialize_dt(row.get("approved_at")),
        "verified_at": _serialize_dt(row.get("approved_at")),
        "rejection_reason": (str(row.get("rejection_reason") or "").strip() or None),
        "completion_type": (str(row.get("completion_type") or "").strip() or None),
        "timer_enabled": None if row.get("timer_enabled") is None else bool(row.get("timer_enabled")),
        "verification_required": None
        if row.get("verification_required") is None
        else bool(row.get("verification_required")),
        "verification_method": (str(row.get("verification_method") or "").strip() or None),
        "verification_timing": (str(row.get("verification_timing") or "").strip() or None),
        "completion_input": completion_input,
        "checklist_id": int(row["checklist_id"]) if row.get("checklist_id") is not None else None,
        "parent_activity_id": int(row["parent_activity_id"])
        if row.get("parent_activity_id") is not None
        else None,
        "activity_kind": (str(row.get("activity_kind") or "").strip() or None),
        "shared_session_id": int(row["shared_session_id"])
        if row.get("shared_session_id") is not None
        else None,
        "is_activity_group": str(row.get("activity_kind") or "") == "group"
        or str(row.get("role") or "").startswith("agroup_"),
        "execution_mode": "shared" if row.get("shared_session_id") is not None else "individual",
    }


def get_open_activity(cursor, organization_id: int, user_id: int) -> dict[str, Any] | None:
    ensure_cleaning_task_activity_tables(cursor)
    cursor.execute(
        f"""
        SELECT *
        FROM {TABLE}
        WHERE organization_id = %s AND user_id = %s AND status = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(organization_id), int(user_id), STATUS_IN_PROGRESS),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def get_activity(cursor, organization_id: int, activity_id: int) -> dict[str, Any] | None:
    ensure_cleaning_task_activity_tables(cursor)
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(activity_id)),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def _day_responsibilities(
    cursor,
    organization_id: int,
    *,
    business_date: date,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_responsibilities_table(cursor)
    week = normalize_week_start(business_date)
    if not week:
        return []
    dow = _dow_for_date(business_date)
    catalog = _role_catalog(cursor, int(organization_id))
    items = []
    for item in list_week_responsibilities(cursor, int(organization_id), week_start=week):
        if int(item.get("day_of_week") or -1) != dow:
            continue
        if not is_task_role(item.get("role") or "", catalog):
            continue
        if user_id is not None and int(item.get("user_id") or 0) != int(user_id):
            continue
        items.append(item)
    return items


def _activities_for_day(
    cursor,
    organization_id: int,
    business_date: date,
    *,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_cleaning_task_activity_tables(cursor)
    params: list[Any] = [int(organization_id), business_date]
    sql = f"""
        SELECT * FROM {TABLE}
        WHERE organization_id = %s AND business_date = %s
    """
    if user_id is not None:
        sql += " AND user_id = %s"
        params.append(int(user_id))
    sql += " ORDER BY id ASC"
    cursor.execute(sql, tuple(params))
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _employee_names(cursor, organization_id: int, user_ids: Sequence[int]) -> dict[int, str]:
    ids = sorted({int(u) for u in user_ids if u})
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, display_name, username
        FROM users
        WHERE organization_id = %s AND id IN ({placeholders})
        """,
        (int(organization_id), *ids),
    )
    out: dict[int, str] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        uid = int(row["id"])
        out[uid] = (str(row.get("display_name") or "").strip() or str(row.get("username") or uid))
    return out


def _latest_activity_by_resp(activities: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """Prefer in-progress, else newest non-cancelled row per responsibility.

    Child group-item rows (parent_activity_id set) are ignored so assignment
    status tracks the parent group / standalone activity only.
    """
    best: dict[int, dict[str, Any]] = {}
    for row in activities:
        if str(row.get("status") or "") == STATUS_CANCELLED:
            continue
        if row.get("parent_activity_id") is not None or str(row.get("activity_kind") or "") == "group_item":
            continue
        rid = int(row.get("responsibility_id") or 0)
        prev = best.get(rid)
        if prev is None:
            best[rid] = dict(row)
            continue
        if str(row.get("status")) == STATUS_IN_PROGRESS:
            best[rid] = dict(row)
            continue
        if str(prev.get("status")) == STATUS_IN_PROGRESS:
            continue
        if int(row.get("id") or 0) > int(prev.get("id") or 0):
            best[rid] = dict(row)
    return best


def _coerce_business_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def _is_overdue(
    *,
    timing_mode: str,
    planned_start_time: Any,
    now: datetime,
    business_date: date | None = None,
    shift_start: Any = None,
    shift_end: Any = None,
    break_start: Any = None,
    break_end: Any = None,
) -> bool:
    """Overdue vs America/New_York business calendar.

    - Future business dates are never overdue (clock time alone must not mark them).
    - Past incomplete assignments are overdue once the business day has ended.
    - Anytime tasks are not overdue on the current business day.
    - Timed / relative modes on the current day use ET wall-clock vs anchors.
    Callers must only invoke this for incomplete (not pending-verification) work.
    """
    mode = str(timing_mode or "anytime")
    today = business_today()
    day = _coerce_business_date(business_date)
    if day is not None:
        if day > today:
            return False
        if day < today:
            return True
    # Current ET business day (or unknown date → treat as current).
    if mode == "anytime":
        return False
    now_m = int(getattr(now, "hour", 0) or 0) * 60 + int(getattr(now, "minute", 0) or 0)
    if mode == "specific_time":
        point = _minutes(planned_start_time)
        return point is not None and now_m > point + 15
    if mode == "upon_entry":
        point = _minutes(shift_start)
        return point is not None and now_m > point + 30
    if mode == "before_break":
        point = _minutes(break_start)
        return point is not None and now_m > point
    if mode == "after_break":
        point = _minutes(break_end)
        return point is not None and now_m > point + 30
    if mode == "before_exit":
        point = _minutes(shift_end)
        return point is not None and now_m > point
    return False


def _day_shifts_for_user(cursor, organization_id: int, user_id: int, business_date: date) -> list[dict]:
    week = normalize_week_start(business_date)
    if not week:
        return []
    dow = _dow_for_date(business_date)
    if not table_exists(cursor, "planned_weekly_schedule_entries"):
        return []
    cursor.execute(
        """
        SELECT start_time, end_time, break_slots, break_minutes
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start = %s AND user_id = %s AND day_of_week = %s
        ORDER BY start_time ASC, id ASC
        """,
        (int(organization_id), week, int(user_id), dow),
    )
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _shift_break_anchors(shifts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from backend.planned_weekly_schedule import parse_break_slots_storage

    if not shifts:
        return {}
    first = shifts[0]
    last = shifts[-1]
    break_start = break_end = None
    for shift in shifts:
        slots = parse_break_slots_storage(shift.get("break_slots"))
        for slot in slots or []:
            if isinstance(slot, dict):
                bs = slot.get("start") or slot.get("start_time")
                be = slot.get("end") or slot.get("end_time")
                if bs and break_start is None:
                    break_start = bs
                if be:
                    break_end = be
    return {
        "shift_start": _serialize_time(first.get("start_time")),
        "shift_end": _serialize_time(last.get("end_time")),
        "break_start": _serialize_time(break_start),
        "break_end": _serialize_time(break_end),
    }


def _task_meta_for_role(cursor, organization_id: int, role_code: str) -> dict[str, Any]:
    defn = get_task_definition(cursor, int(organization_id), str(role_code or ""))
    if defn:
        return defn
    return {
        "code": role_code,
        "name": role_code,
        "category_code": "intra_day",
        "category_name": "Intra-Day",
        "completion_type": COMPLETION_SIMPLE,
        "timer_enabled": True,
        "verification_required": True,
        "verification_method": VERIFY_SUPERVISOR,
        "verification_timing": "same_shift",
        "verifier_config": {},
        "input_schema": [],
        "checklist_id": None,
    }


def list_employee_day_tasks(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    business_date: date | None = None,
) -> dict[str, Any]:
    """Tasks assigned to one employee for the business day, with activity status."""
    day = business_date or business_today()
    try:
        seed_builtin_categories(cursor, int(organization_id))
    except Exception:
        pass
    catalog = _role_catalog(cursor, int(organization_id))
    categories = list_categories(cursor, int(organization_id), include_inactive=False)
    assignments = _day_responsibilities(cursor, organization_id, business_date=day, user_id=user_id)
    activities = _activities_for_day(cursor, organization_id, day, user_id=user_id)
    by_resp = _latest_activity_by_resp(activities)
    open_row = get_open_activity(cursor, organization_id, user_id)
    all_member_ids = {int(user_id)}
    for item in assignments:
        for mid in item.get("user_ids") or []:
            all_member_ids.add(int(mid))
    names = _employee_names(cursor, organization_id, sorted(all_member_ids))
    shared_by_resp: dict[int, dict[str, Any]] = {}
    if any(
        str(item.get("execution_mode") or "") == "shared" and len(item.get("user_ids") or []) >= 2
        for item in assignments
    ):
        shared_by_resp = _latest_activity_by_resp(
            _activities_for_day(cursor, organization_id, day)
        )
    shifts = _day_shifts_for_user(cursor, organization_id, user_id, day)
    anchors = _shift_break_anchors(shifts)
    now = business_now()
    if getattr(now, "tzinfo", None) is not None:
        now = now.replace(tzinfo=None)

    pending: list[dict] = []
    in_progress: list[dict] = []
    completed: list[dict] = []
    by_category: dict[str, list[dict]] = {c["code"]: [] for c in categories}

    from backend.task_activity_groups import get_activity_group, is_activity_group_code

    for item in assignments:
        rid = int(item["id"])
        act = by_resp.get(rid)
        # Skip child verification rows when matching by responsibility — use latest parent/standalone.
        if act and act.get("parent_activity_id") is not None:
            act = None
            for candidate in activities:
                if int(candidate.get("responsibility_id") or 0) != rid:
                    continue
                if candidate.get("parent_activity_id") is not None:
                    continue
                act = candidate
        role_code = str(item.get("role") or "")
        is_group = is_activity_group_code(role_code)
        group_cfg = get_activity_group(cursor, int(organization_id), role_code=role_code) if is_group else None
        meta = _task_meta_for_role(cursor, organization_id, role_code)
        if is_group and group_cfg:
            cat_code = group_cfg.get("category_code") or meta.get("category_code") or "intra_day"
            cat_name = next(
                (c["name"] for c in categories if c["code"] == cat_code),
                meta.get("category_name") or cat_code,
            )
            meta = {
                **meta,
                "name": group_cfg.get("name") or meta.get("name"),
                "category_code": cat_code,
                "category_name": cat_name,
                "timer_enabled": True,
                "completion_type": COMPLETION_SIMPLE,
                "verification_required": False,
                "verification_method": VERIFY_NONE,
                "input_schema": [],
            }
        member_ids = [int(x) for x in (item.get("user_ids") or [item["user_id"]])]
        member_names = [names.get(mid, f"User #{mid}") for mid in member_ids]
        member_names_sorted = sorted(member_names, key=lambda s: s.lower())
        base = {
            "responsibility_id": rid,
            "assignment_key": assignment_key(item),
            "assignment_group_id": item.get("assignment_group_id"),
            "role": item.get("role"),
            "role_label": meta.get("name") or _role_label(item.get("role"), catalog),
            "category_code": meta.get("category_code"),
            "category_name": meta.get("category_name"),
            "completion_type": meta.get("completion_type") or COMPLETION_SIMPLE,
            "timer_enabled": bool(meta.get("timer_enabled", True)),
            "verification_required": bool(meta.get("verification_required", True)),
            "verification_method": meta.get("verification_method"),
            "input_schema": meta.get("input_schema") or [],
            "timing_mode": item.get("timing_mode") or "anytime",
            "timing_label": item.get("timing_label")
            or timing_display(item.get("timing_mode"), item.get("start_time")),
            "planned_start_time": item.get("start_time"),
            "remarks": item.get("remarks"),
            "user_ids": member_ids,
            "assigned_employees": member_names_sorted,
            "shared": len(member_ids) > 1,
            "execution_mode": str(item.get("execution_mode") or "individual"),
            "partners": _shared_partner_rows(item, int(user_id), names, shared_by_resp),
            "is_activity_group": is_group,
            "activity_kind": "group" if is_group else "standalone",
            "group_items": (group_cfg or {}).get("items") if is_group else None,
            "group_item_count": int((group_cfg or {}).get("item_count") or 0) if is_group else None,
        }
        if act and str(act.get("status")) == STATUS_IN_PROGRESS:
            row = {**base, "status": DISPLAY_IN_PROGRESS, "activity": serialize_activity(act, catalog=catalog)}
            in_progress.append(row)
        elif act and str(act.get("status")) in COMPLETED_STATUSES:
            st = str(act.get("status"))
            display = {
                STATUS_PENDING_APPROVAL: "pending_verification",
                STATUS_APPROVED: "verified",
                STATUS_COMPLETED: DISPLAY_COMPLETED,
                STATUS_REJECTED: DISPLAY_REJECTED,
            }.get(st, st)
            row = {**base, "status": display, "activity": serialize_activity(act, catalog=catalog)}
            completed.append(row)
        else:
            overdue = _is_overdue(
                timing_mode=str(item.get("timing_mode") or "anytime"),
                planned_start_time=item.get("start_time"),
                now=now,
                business_date=day,
                **anchors,
            )
            status = DISPLAY_OVERDUE if overdue else DISPLAY_PENDING
            row = {**base, "status": status, "activity": None}
            pending.append(row)
        cat = str(base.get("category_code") or "intra_day")
        by_category.setdefault(cat, []).append(row)

    open_ser = None
    if open_row:
        open_ser = serialize_activity(open_row, catalog=catalog)
        open_meta = _task_meta_for_role(cursor, organization_id, str(open_row.get("role") or ""))
        open_ser["input_schema"] = open_meta.get("input_schema") or []
        open_ser["completion_type"] = open_meta.get("completion_type") or COMPLETION_SIMPLE
        try:
            from backend.cleaning_task_group_execution import enrich_open_group_activity
            from backend.task_activity_groups import is_activity_group_code

            if open_ser.get("is_activity_group") or is_activity_group_code(open_row.get("role")):
                open_ser = enrich_open_group_activity(cursor, int(organization_id), open_ser)
            open_ser["partners"] = partners_for_activity(cursor, int(organization_id), open_row)
        except Exception:
            pass
    return {
        "business_date": str(day),
        "user_id": int(user_id),
        "open_activity": open_ser,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "tasks": pending + in_progress + completed,
        "categories": categories,
        "tasks_by_category": [
            {
                "category_code": c["code"],
                "category_name": c["name"],
                "tasks": by_category.get(c["code"]) or [],
            }
            for c in categories
            if by_category.get(c["code"])
        ],
    }


def start_task(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    responsibility_id: int,
    shift_session_id: int | None,
    business_date: date | None = None,
) -> dict[str, Any]:
    """Start a cleaning task. Closes open production role; blocks if on break or already on a task.

    Optional ``business_date`` supports supervisor historical backfill (manual completion).
    """
    from backend.shift_job_tracking import close_open_job_segment, get_open_job_segment
    from backend.ta_routes import get_open_break

    ensure_cleaning_task_activity_tables(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    today = business_today()
    day = business_date or today
    catalog = _role_catalog(cursor, oid)
    historical = day != today
    # Historical supervisor backfill must never attach to a live shift or pause
    # production-role job segments.
    if historical:
        shift_session_id = None

    # Live PIN starts must not stack; historical supervisor backfill may proceed.
    if not historical and get_open_activity(cursor, oid, uid):
        raise CleaningTaskError("Finish your current task first.", status=400)

    if shift_session_id and get_open_break(conn, int(shift_session_id)):
        raise CleaningTaskError("Finish your break before starting a task.", status=400)

    assignments = _day_responsibilities(cursor, oid, business_date=day, user_id=uid)
    target = next((a for a in assignments if int(a["id"]) == int(responsibility_id)), None)
    if not target:
        raise CleaningTaskError(
            "That task is not assigned to you today."
            if not historical
            else "That task is not assigned on the selected date.",
            status=404,
        )

    from backend.task_activity_groups import is_activity_group_code

    if is_activity_group_code(target.get("role")):
        raise CleaningTaskError(
            "Use Start Group for activity groups.",
            status=400,
        )
    meta = _task_meta_for_role(cursor, oid, str(target.get("role") or ""))
    if not bool(meta.get("timer_enabled", True)):
        raise CleaningTaskError(
            "This task is untimed. Mark it complete instead of starting a timer.",
            status=400,
        )

    activities = _activities_for_day(cursor, oid, day, user_id=uid)
    latest = _latest_activity_by_resp(activities).get(int(responsibility_id))
    if latest and str(latest.get("status")) in {
        STATUS_IN_PROGRESS,
        STATUS_PENDING_APPROVAL,
        STATUS_APPROVED,
        STATUS_COMPLETED,
    }:
        raise CleaningTaskError("This task is already in progress or completed.", status=400)
    # Rejected rows stay in history; a new activity may be started for redo.

    at = eastern_now_naive()
    paused_cat = paused_role = None
    if shift_session_id:
        open_seg = get_open_job_segment(conn, int(shift_session_id))
        if open_seg:
            paused_cat = open_seg.get("category_id")
            paused_role = open_seg.get("role_id")
            close_open_job_segment(conn, int(shift_session_id), at, close_source="cleaning_task_start")

    verify_required = bool(meta.get("verification_required", True))
    verify_method = str(meta.get("verification_method") or VERIFY_SUPERVISOR)
    if not verify_required:
        verify_method = VERIFY_NONE
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (
          organization_id, responsibility_id, assignment_group_id, user_id,
          shift_session_id, business_date, role, timing_mode, planned_start_time,
          status, started_at, paused_category_id, paused_role_id,
          category_code, completion_type, timer_enabled, verification_required,
          verification_method, verification_timing, checklist_id,
          parent_activity_id, activity_kind
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            oid,
            int(target["id"]),
            target.get("assignment_group_id"),
            uid,
            int(shift_session_id) if shift_session_id else None,
            day,
            target.get("role"),
            target.get("timing_mode") or "anytime",
            target.get("start_time"),
            STATUS_IN_PROGRESS,
            at,
            int(paused_cat) if paused_cat is not None else None,
            int(paused_role) if paused_role is not None else None,
            meta.get("category_code"),
            meta.get("completion_type") or COMPLETION_SIMPLE,
            1,
            1 if verify_required else 0,
            verify_method,
            meta.get("verification_timing") or "same_shift",
            meta.get("checklist_id"),
            None,
            "standalone",
        ),
    )
    aid = int(cursor.lastrowid)
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=aid,
        event_type="started",
        actor_user_id=uid,
        payload={"responsibility_id": int(target["id"]), "paused_role": bool(paused_role)},
    )
    row = get_activity(cursor, oid, aid)
    out = serialize_activity(row or {}, catalog=catalog)
    out["input_schema"] = meta.get("input_schema") or []
    out["completion_type"] = meta.get("completion_type") or COMPLETION_SIMPLE
    out["role_label"] = meta.get("name") or out.get("role_label")
    return out


def _resolve_post_complete_status(row: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    verify_required = row.get("verification_required")
    if verify_required is None and meta is not None:
        verify_required = meta.get("verification_required", True)
    method = str(row.get("verification_method") or (meta or {}).get("verification_method") or VERIFY_SUPERVISOR)
    if verify_required in (0, False) or method == VERIFY_NONE:
        return STATUS_COMPLETED
    return STATUS_PENDING_APPROVAL


def _finalize_completion(
    cursor,
    *,
    oid: int,
    uid: int,
    activity_id: int,
    row: Mapping[str, Any],
    at: datetime,
    duration: int | None,
    completion_input: Mapping[str, Any] | None,
    interrupt_role: bool,
    force_status: str | None = None,
    force_verify: bool | None = None,
) -> dict[str, Any]:
    catalog = _role_catalog(cursor, oid)
    meta = _task_meta_for_role(cursor, oid, str(row.get("role") or ""))
    final_status = force_status or _resolve_post_complete_status(row, meta)
    if force_verify is False and final_status == STATUS_PENDING_APPROVAL:
        final_status = STATUS_COMPLETED
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET status = %s, ended_at = %s, duration_seconds = %s, completion_input_json = %s
        WHERE id = %s AND organization_id = %s
        """,
        (
            final_status,
            at,
            duration,
            json.dumps(completion_input, default=str) if completion_input else None,
            int(activity_id),
            oid,
        ),
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="completed",
        actor_user_id=uid,
        payload={
            "duration_seconds": duration,
            "final_status": final_status,
            "completion_input": completion_input,
        },
    )
    updated = get_activity(cursor, oid, int(activity_id))
    out = serialize_activity(updated or {}, catalog=catalog)
    if interrupt_role:
        out["next_options"] = [
            {"id": "resume_work", "label": "Resume Work"},
            {"id": "change_role", "label": "Change Role"},
            {"id": "take_break", "label": "Take Break"},
        ]
    else:
        out["next_options"] = []
    out["paused_category_id"] = (
        int(row["paused_category_id"]) if row.get("paused_category_id") is not None else None
    )
    out["paused_role_id"] = int(row["paused_role_id"]) if row.get("paused_role_id") is not None else None
    out["verification_required"] = final_status == STATUS_PENDING_APPROVAL
    return out


def complete_task(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
    completion_input: Any = None,
) -> dict[str, Any]:
    ensure_cleaning_task_activity_tables(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row or int(row.get("user_id") or 0) != uid:
        raise CleaningTaskError("Active task not found.", status=404)
    if str(row.get("status")) != STATUS_IN_PROGRESS:
        raise CleaningTaskError("That task is not in progress.", status=400)

    meta = _task_meta_for_role(cursor, oid, str(row.get("role") or ""))
    try:
        validated = validate_completion_input(meta, completion_input)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc

    at = eastern_now_naive()
    started = row.get("started_at")
    if isinstance(started, str):
        try:
            started = datetime.fromisoformat(started[:19])
        except ValueError:
            started = at
    duration = max(0, int((at - started).total_seconds())) if isinstance(started, datetime) else 0
    return _finalize_completion(
        cursor,
        oid=oid,
        uid=uid,
        activity_id=int(activity_id),
        row=row,
        at=at,
        duration=duration,
        completion_input=validated,
        interrupt_role=True,
    )


def complete_untimed_task(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    responsibility_id: int,
    shift_session_id: int | None,
    completion_input: Any = None,
) -> dict[str, Any]:
    """Mark an untimed task complete without pausing the production role."""
    ensure_cleaning_task_activity_tables(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    day = business_today()
    if get_open_activity(cursor, oid, uid):
        raise CleaningTaskError("Finish your current timed task first.", status=400)
    assignments = _day_responsibilities(cursor, oid, business_date=day, user_id=uid)
    target = next((a for a in assignments if int(a["id"]) == int(responsibility_id)), None)
    if not target:
        raise CleaningTaskError("That task is not assigned to you today.", status=404)
    meta = _task_meta_for_role(cursor, oid, str(target.get("role") or ""))
    if bool(meta.get("timer_enabled", True)):
        raise CleaningTaskError("This task requires a timer. Start the task first.", status=400)
    activities = _activities_for_day(cursor, oid, day, user_id=uid)
    latest = _latest_activity_by_resp(activities).get(int(responsibility_id))
    if latest and str(latest.get("status")) in {
        STATUS_IN_PROGRESS,
        STATUS_PENDING_APPROVAL,
        STATUS_APPROVED,
        STATUS_COMPLETED,
    }:
        raise CleaningTaskError("This task is already completed.", status=400)
    try:
        validated = validate_completion_input(meta, completion_input)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc

    at = eastern_now_naive()
    verify_required = bool(meta.get("verification_required", True))
    verify_method = str(meta.get("verification_method") or VERIFY_SUPERVISOR)
    if not verify_required:
        verify_method = VERIFY_NONE
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (
          organization_id, responsibility_id, assignment_group_id, user_id,
          shift_session_id, business_date, role, timing_mode, planned_start_time,
          status, started_at, ended_at, duration_seconds,
          category_code, completion_type, timer_enabled, verification_required,
          verification_method, verification_timing, checklist_id, completion_input_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            oid,
            int(target["id"]),
            target.get("assignment_group_id"),
            uid,
            int(shift_session_id) if shift_session_id else None,
            day,
            target.get("role"),
            target.get("timing_mode") or "anytime",
            target.get("start_time"),
            STATUS_IN_PROGRESS,
            at,
            at,
            0,
            meta.get("category_code"),
            meta.get("completion_type") or COMPLETION_SIMPLE,
            0,
            1 if verify_required else 0,
            verify_method,
            meta.get("verification_timing") or "same_shift",
            meta.get("checklist_id"),
            json.dumps(validated, default=str),
        ),
    )
    aid = int(cursor.lastrowid)
    row = get_activity(cursor, oid, aid) or {}
    return _finalize_completion(
        cursor,
        oid=oid,
        uid=uid,
        activity_id=aid,
        row=row,
        at=at,
        duration=0,
        completion_input=validated,
        interrupt_role=False,
    )


def record_post_complete_choice(
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
    choice: str,
) -> dict[str, Any]:
    """Audit the post-complete choice. Actual resume/break/role use existing PIN flows."""
    choice_clean = str(choice or "").strip().lower()
    if choice_clean not in {"resume_work", "change_role", "take_break"}:
        raise CleaningTaskError("Choose Resume Work, Change Role, or Take Break.", status=400)
    row = get_activity(cursor, organization_id, int(activity_id))
    if not row or int(row.get("user_id") or 0) != int(user_id):
        raise CleaningTaskError("Task not found.", status=404)
    if str(row.get("status")) not in COMPLETED_STATUSES and str(row.get("status")) != STATUS_COMPLETED:
        raise CleaningTaskError("Complete the task before choosing what to do next.", status=400)
    _record_event(
        cursor,
        organization_id=int(organization_id),
        activity_id=int(activity_id),
        event_type=f"next_{choice_clean}",
        actor_user_id=int(user_id),
        payload={"choice": choice_clean},
    )
    return {
        "ok": True,
        "choice": choice_clean,
        "paused_category_id": int(row["paused_category_id"])
        if row.get("paused_category_id") is not None
        else None,
        "paused_role_id": int(row["paused_role_id"]) if row.get("paused_role_id") is not None else None,
    }


def approve_activity(
    cursor,
    *,
    organization_id: int,
    activity_id: int,
    supervisor_user_id: int,
) -> dict[str, Any]:
    catalog = _role_catalog(cursor, int(organization_id))
    row = get_activity(cursor, organization_id, int(activity_id))
    if not row:
        raise CleaningTaskError("Task activity not found.", status=404)
    if str(row.get("status")) != STATUS_PENDING_APPROVAL:
        raise CleaningTaskError("Only completed tasks awaiting verification can be verified.", status=400)
    if int(row.get("user_id") or 0) == int(supervisor_user_id):
        raise CleaningTaskError(
            "You cannot verify your own completed task. Ask another authorized person.",
            status=403,
        )
    at = eastern_now_naive()
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET status = %s, approved_by_user_id = %s, approved_at = %s, rejection_reason = NULL
        WHERE id = %s AND organization_id = %s
        """,
        (STATUS_APPROVED, int(supervisor_user_id), at, int(activity_id), int(organization_id)),
    )
    _record_event(
        cursor,
        organization_id=int(organization_id),
        activity_id=int(activity_id),
        event_type="approved",
        actor_user_id=int(supervisor_user_id),
    )
    return serialize_activity(get_activity(cursor, organization_id, int(activity_id)) or {}, catalog=catalog)


def reject_activity(
    cursor,
    *,
    organization_id: int,
    activity_id: int,
    supervisor_user_id: int,
    reason: str,
) -> dict[str, Any]:
    catalog = _role_catalog(cursor, int(organization_id))
    reason_clean = (reason or "").strip()
    if len(reason_clean) < 3:
        raise CleaningTaskError("A rejection reason is required.", status=400)
    if len(reason_clean) > 500:
        raise CleaningTaskError("Rejection reason is too long.", status=400)
    row = get_activity(cursor, organization_id, int(activity_id))
    if not row:
        raise CleaningTaskError("Task activity not found.", status=404)
    if str(row.get("status")) != STATUS_PENDING_APPROVAL:
        raise CleaningTaskError("Only completed tasks awaiting verification can be rejected.", status=400)
    if int(row.get("user_id") or 0) == int(supervisor_user_id):
        raise CleaningTaskError(
            "You cannot reject your own completed task. Ask another authorized person.",
            status=403,
        )
    at = eastern_now_naive()
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET status = %s, approved_by_user_id = %s, approved_at = %s, rejection_reason = %s
        WHERE id = %s AND organization_id = %s
        """,
        (
            STATUS_REJECTED,
            int(supervisor_user_id),
            at,
            reason_clean,
            int(activity_id),
            int(organization_id),
        ),
    )
    _record_event(
        cursor,
        organization_id=int(organization_id),
        activity_id=int(activity_id),
        event_type="rejected",
        actor_user_id=int(supervisor_user_id),
        payload={"reason": reason_clean},
    )
    return serialize_activity(get_activity(cursor, organization_id, int(activity_id)) or {}, catalog=catalog)


def _contribution_entry(
    item: Mapping[str, Any],
    act: Mapping[str, Any] | None,
    *,
    catalog: Mapping[str, Mapping[str, Any]],
    names: Mapping[int, str],
    status: str,
) -> dict[str, Any]:
    return {
        "responsibility_id": int(item["id"]),
        "assignment_key": assignment_key(item),
        "assignment_group_id": item.get("assignment_group_id"),
        "shared": len(item.get("user_ids") or []) > 1,
        "role": item.get("role"),
        "role_label": _role_label(item.get("role"), catalog),
        "timing_label": item.get("timing_label")
        or timing_display(item.get("timing_mode"), item.get("start_time")),
        "employee_id": int(item["user_id"]),
        "employee_name": names.get(int(item["user_id"]), f"User #{item['user_id']}"),
        "assigned_employees": [
            names.get(int(x), f"User #{x}") for x in (item.get("user_ids") or [item["user_id"]])
        ],
        "status": status,
        "status_label": friendly_status_label(status, overdue=status == DISPLAY_OVERDUE),
        "activity": serialize_activity(act, catalog=catalog) if act else None,
        "can_record_manual": status in {DISPLAY_PENDING, DISPLAY_OVERDUE, DISPLAY_REJECTED}
        or (act is None),
        "can_correct": bool(act) and str((act or {}).get("status") or "") in COMPLETED_STATUSES,
    }


def list_supervisor_queue(
    cursor,
    organization_id: int,
    *,
    business_date: date | None = None,
    status: str | None = None,
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """
    Per-employee contribution queue for supervisor approval.

    Shared assignments appear once per member. Approval is always per employee
    contribution (not once for the whole group).
    """
    day = business_date or business_today()
    catalog = _role_catalog(cursor, int(organization_id))
    assignments = _day_responsibilities(cursor, organization_id, business_date=day)
    activities = _activities_for_day(cursor, organization_id, day)
    by_resp = _latest_activity_by_resp(activities)
    name_ids = {int(a["user_id"]) for a in assignments}
    name_ids |= {int(r["user_id"]) for r in activities}
    name_ids |= {
        int(r["approved_by_user_id"])
        for r in activities
        if r.get("approved_by_user_id") is not None
    }
    names = _employee_names(cursor, organization_id, sorted(name_ids))
    now = business_now()
    if getattr(now, "tzinfo", None) is not None:
        now = now.replace(tzinfo=None)

    buckets = {
        "pending_approval": [],
        "approved": [],
        "rejected": [],
        "not_started": [],
        "overdue": [],
        "in_progress": [],
        "completed_without_verification": [],
    }

    for item in assignments:
        if user_id is not None and int(item["user_id"]) != int(user_id):
            continue
        if role and str(item.get("role")) != str(role):
            continue
        rid = int(item["id"])
        act = by_resp.get(rid)
        if act and str(act.get("status")) == STATUS_IN_PROGRESS:
            buckets["in_progress"].append(
                _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_IN_PROGRESS)
            )
        elif act and str(act.get("status")) == STATUS_PENDING_APPROVAL:
            buckets["pending_approval"].append(
                _contribution_entry(
                    item, act, catalog=catalog, names=names, status=DISPLAY_PENDING_APPROVAL
                )
            )
        elif act and str(act.get("status")) == STATUS_APPROVED:
            buckets["approved"].append(
                _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_APPROVED)
            )
        elif act and str(act.get("status")) == STATUS_COMPLETED:
            # The parent timer closes as completed. Required group items still carry
            # verification, so a finished group can still be waiting or need correction.
            child_verification = verification_status_from_subjects(
                [
                    child
                    for child in activities
                    if child.get("parent_activity_id") is not None
                    and int(child.get("parent_activity_id") or 0) == int(act.get("id") or 0)
                ]
            )
            if child_verification in {VERIFICATION_WAITING, VERIFICATION_PARTIAL}:
                buckets["pending_approval"].append(
                    _contribution_entry(
                        item, act, catalog=catalog, names=names, status=DISPLAY_PENDING_APPROVAL
                    )
                )
            elif child_verification == VERIFICATION_NEEDS_CORRECTION:
                buckets["rejected"].append(
                    _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_REJECTED)
                )
            else:
                # Finished with no verification step. Keep it out of the verified bucket
                # so one completion cannot be counted again as an approval.
                buckets["completed_without_verification"].append(
                    _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_COMPLETED)
                )
        elif act and str(act.get("status")) == STATUS_REJECTED:
            buckets["rejected"].append(
                _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_REJECTED)
            )
        else:
            shifts = _day_shifts_for_user(cursor, organization_id, int(item["user_id"]), day)
            anchors = _shift_break_anchors(shifts)
            overdue = _is_overdue(
                timing_mode=str(item.get("timing_mode") or "anytime"),
                planned_start_time=item.get("start_time"),
                now=now,
                business_date=day,
                **anchors,
            )
            if overdue:
                buckets["overdue"].append(
                    _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_OVERDUE)
                )
            else:
                buckets["not_started"].append(
                    _contribution_entry(item, act, catalog=catalog, names=names, status=DISPLAY_PENDING)
                )

    if status:
        key = str(status).strip().lower()
        alias = {
            "pending": "not_started",
            "not_started": "not_started",
            "pending_approval": "pending_approval",
            "approved": "approved",
            "rejected": "rejected",
            "overdue": "overdue",
            "in_progress": "in_progress",
            "started": "in_progress",
        }.get(key)
        if alias:
            buckets = {k: (v if k == alias else []) for k, v in buckets.items()}

    # Shift-end: incomplete / overdue / still waiting on supervisor approval.
    shift_end = {
        "incomplete": buckets["not_started"] + buckets["in_progress"] + buckets["rejected"],
        "overdue": buckets["overdue"],
        "pending_approval": buckets["pending_approval"],
        "blocking_close": (
            buckets["not_started"]
            + buckets["in_progress"]
            + buckets["overdue"]
            + buckets["pending_approval"]
            + buckets["rejected"]
        ),
    }

    return {
        "business_date": str(day),
        "approval_policy": "per_employee_contribution",
        "approval_policy_label": (
            "Verify each employee's contribution separately when verification is required. "
            "Shared tasks stay one assignment, with individual timers and verifications."
        ),
        "shift_end": shift_end,
        **buckets,
    }


def _group_shared_assignments(
    assignments: Sequence[Mapping[str, Any]],
    by_resp: Mapping[int, Mapping[str, Any]],
    *,
    catalog: Mapping[str, Mapping[str, Any]],
    names: Mapping[int, str],
    now: datetime,
    cursor,
    organization_id: int,
    business_date: date,
    user_id: int | None = None,
    role: str | None = None,
    activities: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One dashboard row per shared/solo assignment, with member contributions nested."""
    activities_all = list(activities or [])
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in assignments:
        if user_id is not None and int(item["user_id"]) != int(user_id):
            continue
        if role and str(item.get("role")) != str(role):
            continue
        key = assignment_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(dict(item))

    out: list[dict[str, Any]] = []
    for key in order:
        members = groups[key]
        sample = members[0]
        contributions = []
        member_statuses = []
        for member in members:
            rid = int(member["id"])
            act = by_resp.get(rid)
            if act and str(act.get("status")) == STATUS_IN_PROGRESS:
                st = DISPLAY_IN_PROGRESS
            elif act and str(act.get("status")) == STATUS_PENDING_APPROVAL:
                st = DISPLAY_PENDING_APPROVAL
            elif act and str(act.get("status")) == STATUS_APPROVED:
                st = DISPLAY_APPROVED
            elif act and str(act.get("status")) == STATUS_COMPLETED:
                st = DISPLAY_COMPLETED
            elif act and str(act.get("status")) == STATUS_REJECTED:
                st = DISPLAY_REJECTED
            else:
                shifts = _day_shifts_for_user(cursor, organization_id, int(member["user_id"]), business_date)
                anchors = _shift_break_anchors(shifts)
                overdue = _is_overdue(
                    timing_mode=str(member.get("timing_mode") or "anytime"),
                    planned_start_time=member.get("start_time"),
                    now=now,
                    business_date=business_date,
                    **anchors,
                )
                st = DISPLAY_OVERDUE if overdue else DISPLAY_PENDING
            member_statuses.append(st)
            entry = _contribution_entry(member, act, catalog=catalog, names=names, status=st)
            # Activity-group drill-down: nest item-level child activities under the parent.
            if act and (
                str(act.get("activity_kind") or "") == "group"
                or str(member.get("role") or "").startswith("agroup_")
            ):
                children = [
                    serialize_activity(a, catalog=catalog)
                    for a in activities_all
                    if a.get("parent_activity_id") is not None
                    and int(a.get("parent_activity_id") or 0) == int(act.get("id") or 0)
                    and int(a.get("user_id") or 0) == int(member.get("user_id") or 0)
                ]
                entry["group_items"] = children
                entry["is_activity_group"] = True
                entry["execution_mode"] = (
                    "shared" if act.get("shared_session_id") is not None else "individual"
                )
                if act.get("duration_seconds") is not None:
                    entry["group_duration_seconds"] = int(act.get("duration_seconds") or 0)
                # Shared checklist once per assignment (who completed each item).
                if act.get("shared_session_id") is not None:
                    try:
                        from backend.cleaning_task_shared_execution import (
                            list_shared_session_items,
                            serialize_shared_item,
                        )

                        shared_items = list_shared_session_items(
                            cursor, int(organization_id), int(act["shared_session_id"])
                        )
                        name_ids = {
                            int(it["completed_by_user_id"])
                            for it in shared_items
                            if it.get("completed_by_user_id") is not None
                        }
                        item_names = _employee_names(cursor, int(organization_id), sorted(name_ids))
                        entry["shared_checklist_items"] = [
                            serialize_shared_item(
                                it,
                                catalog=catalog,
                                meta=_task_meta_for_role(
                                    cursor, int(organization_id), str(it.get("task_code") or "")
                                ),
                                names=item_names,
                            )
                            for it in shared_items
                        ]
                        entry["shared_session_id"] = int(act["shared_session_id"])
                    except Exception:
                        pass
            subjects = verification_subjects_for_contribution(entry)
            entry["verification_status"] = verification_status_from_subjects(subjects)
            entry["verification_label"] = _VERIFICATION_LABELS[entry["verification_status"]]
            entry["completion_status"] = completion_status_from_members([st])
            entry["completion_label"] = _COMPLETION_LABELS[entry["completion_status"]]
            contributions.append(entry)
            # Only attach shared checklist once on the assignment row (after loop).

        # Assignment-level rollup for display (worst outstanding state first).
        if DISPLAY_OVERDUE in member_statuses:
            rollup = DISPLAY_OVERDUE
        elif DISPLAY_IN_PROGRESS in member_statuses:
            rollup = DISPLAY_IN_PROGRESS
        elif DISPLAY_PENDING_APPROVAL in member_statuses:
            rollup = DISPLAY_PENDING_APPROVAL
        elif DISPLAY_REJECTED in member_statuses:
            rollup = DISPLAY_REJECTED
        elif all(s == DISPLAY_APPROVED for s in member_statuses):
            rollup = DISPLAY_APPROVED
        elif all(s in (DISPLAY_APPROVED, DISPLAY_COMPLETED) for s in member_statuses):
            rollup = (
                DISPLAY_APPROVED
                if all(s == DISPLAY_APPROVED for s in member_statuses)
                else DISPLAY_COMPLETED
            )
        elif any(s == DISPLAY_APPROVED for s in member_statuses) or any(
            s == DISPLAY_PENDING_APPROVAL for s in member_statuses
        ):
            rollup = DISPLAY_PENDING_APPROVAL if DISPLAY_PENDING_APPROVAL in member_statuses else "partial"
        elif any(s == DISPLAY_COMPLETED for s in member_statuses):
            rollup = "partial" if any(s == DISPLAY_PENDING for s in member_statuses) else DISPLAY_COMPLETED
        else:
            rollup = DISPLAY_PENDING

        completion_status = completion_status_from_members(member_statuses)
        verification_status = verification_status_from_subjects(
            [
                subject
                for contrib in contributions
                for subject in verification_subjects_for_contribution(contrib)
            ]
        )
        execution_mode = str(sample.get("execution_mode") or "individual")
        shared_checklist = None
        shared_session_id = None
        for contrib in contributions:
            if contrib.get("shared_checklist_items"):
                shared_checklist = contrib.get("shared_checklist_items")
                shared_session_id = contrib.get("shared_session_id")
                break
        out.append(
            {
                "assignment_key": key,
                "assignment_group_id": sample.get("assignment_group_id"),
                "shared": len(members) > 1,
                "execution_mode": execution_mode,
                "role": sample.get("role"),
                "role_label": _role_label(sample.get("role"), catalog),
                "timing_label": sample.get("timing_label")
                or timing_display(sample.get("timing_mode"), sample.get("start_time")),
                "assigned_employees": sorted(
                    {
                        names.get(int(m["user_id"]), f"User #{m['user_id']}")
                        for m in members
                    },
                    key=lambda s: s.lower(),
                ),
                "status": rollup,
                "status_label": friendly_status_label(rollup, overdue=rollup == DISPLAY_OVERDUE),
                "completion_status": completion_status,
                "completion_label": _COMPLETION_LABELS[completion_status],
                "verification_status": verification_status,
                "verification_label": _VERIFICATION_LABELS[verification_status],
                "category_code": (
                    _task_meta_for_role(cursor, int(organization_id), str(sample.get("role") or "")).get(
                        "category_code"
                    )
                    or "intra_day"
                ),
                "contributions": contributions,
                "shared_session_id": shared_session_id,
                "shared_checklist_items": shared_checklist,
                "has_manual_completion": any(
                    (c.get("activity") or {}).get("is_manual_completion") for c in contributions
                ),
                "activity_group_items": _activity_group_item_templates(
                    cursor, int(organization_id), str(sample.get("role") or "")
                ),
                "members": [
                    {
                        "employee_id": int(m["user_id"]),
                        "employee_name": names.get(int(m["user_id"]), f"User #{m['user_id']}"),
                        "responsibility_id": int(m["id"]),
                    }
                    for m in members
                ],
            }
        )
    return out


def _activity_group_item_templates(cursor, organization_id: int, role: str) -> list[dict[str, Any]]:
    """Catalog items for an activity-group role (for manual shared attribution UI)."""
    try:
        from backend.task_activity_groups import get_activity_group, is_activity_group_code

        if not is_activity_group_code(role):
            return []
        group = get_activity_group(cursor, int(organization_id), role_code=str(role))
        if not group:
            return []
        return [
            {
                "task_code": str(it.get("task_code") or ""),
                "task_name": str(it.get("task_name") or it.get("name") or it.get("task_code") or ""),
                "required": bool(it.get("required", True)),
                "display_order": int(it.get("display_order") or 0),
            }
            for it in (group.get("items") or [])
            if it.get("task_code")
        ]
    except Exception:
        return []


_SUCCESS_DISPLAY = frozenset({DISPLAY_COMPLETED, DISPLAY_APPROVED, DISPLAY_PENDING_APPROVAL})
_STARTED_DISPLAY = _SUCCESS_DISPLAY | frozenset({DISPLAY_IN_PROGRESS, DISPLAY_REJECTED})


def partner_participation_state(status: Any) -> str:
    """Assigned partner vs someone whose own timer is running vs finished."""
    st = str(status or "")
    if st == STATUS_IN_PROGRESS:
        return "working"
    if st in COMPLETED_STATUSES:
        return "finished"
    return "assigned"


def _shared_partner_rows(
    item: Mapping[str, Any],
    viewer_user_id: int,
    names: Mapping[int, str],
    by_resp: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Other employees on a Shared Execution assignment, including those who have not started."""
    if str(item.get("execution_mode") or "") != "shared":
        return []
    if len(item.get("user_ids") or []) < 2:
        return []
    labels = {
        "working": "Working now",
        "assigned": "Not started",
        "finished": "Finished",
    }
    out: list[dict[str, Any]] = []
    for member in item.get("members") or []:
        mid = int(member.get("user_id") or 0)
        if not mid or mid == int(viewer_user_id):
            continue
        act = by_resp.get(int(member.get("id") or 0))
        state = partner_participation_state(None if not act else act.get("status"))
        out.append(
            {
                "user_id": mid,
                "name": names.get(mid, f"User #{mid}"),
                "state": state,
                "state_label": labels[state],
            }
        )
    out.sort(key=lambda row: str(row["name"]).lower())
    return out


def partners_for_activity(cursor, organization_id: int, activity: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Partners for one open shared activity. Individual and standalone tasks get none."""
    day = _coerce_business_date(activity.get("business_date"))
    if day is None:
        return []
    group = str(activity.get("assignment_group_id") or "").strip()
    role = str(activity.get("role") or "")
    if not group:
        return []
    rows = _day_responsibilities(cursor, int(organization_id), business_date=day)
    members = [
        row
        for row in rows
        if str(row.get("assignment_group_id") or "").strip() == group
        and str(row.get("role") or "") == role
    ]
    if len(members) < 2 or str(members[0].get("execution_mode") or "") != "shared":
        return []
    names = _employee_names(cursor, int(organization_id), [int(row["user_id"]) for row in members])
    by_resp = _latest_activity_by_resp(_activities_for_day(cursor, int(organization_id), day))
    sample = dict(members[0])
    sample["members"] = members
    sample["user_ids"] = [int(row["user_id"]) for row in members]
    sample["execution_mode"] = "shared"
    return _shared_partner_rows(sample, int(activity.get("user_id") or 0), names, by_resp)


COMPLETION_NOT_STARTED = "not_started"
COMPLETION_IN_PROGRESS = "in_progress"
COMPLETION_COMPLETED = "completed"
VERIFICATION_NOT_REQUIRED = "not_required"
VERIFICATION_WAITING = "waiting"
VERIFICATION_PARTIAL = "partial"
VERIFICATION_VERIFIED = "verified"
VERIFICATION_NEEDS_CORRECTION = "needs_correction"

_COMPLETION_LABELS = {
    COMPLETION_NOT_STARTED: "Not Started",
    COMPLETION_IN_PROGRESS: "In Progress",
    COMPLETION_COMPLETED: "Completed",
}
_VERIFICATION_LABELS = {
    VERIFICATION_NOT_REQUIRED: "Not Required",
    VERIFICATION_WAITING: "Waiting for Verification",
    VERIFICATION_PARTIAL: "Partially Verified",
    VERIFICATION_VERIFIED: "Verified",
    VERIFICATION_NEEDS_CORRECTION: "Needs Correction",
}
_FINISHED_WORK_DISPLAY = frozenset(
    {DISPLAY_COMPLETED, DISPLAY_APPROVED, DISPLAY_PENDING_APPROVAL, DISPLAY_REJECTED}
)


def _subject_requires_verification(item: Mapping[str, Any] | None) -> bool:
    if not item:
        return False
    required = item.get("verification_required")
    method = str(item.get("verification_method") or "").strip().lower()
    if required in (0, False, "0") or method == "none":
        return False
    if required in (1, True, "1"):
        return True
    return method in {"supervisor", "employee", "role"}


def _subject_verification_state(item: Mapping[str, Any]) -> str:
    status = str(item.get("display_status") or item.get("status") or "").strip().lower()
    if status in {STATUS_PENDING_APPROVAL, DISPLAY_PENDING_APPROVAL, "pending_verification"}:
        return VERIFICATION_WAITING
    if status in {STATUS_APPROVED, DISPLAY_APPROVED, "verified"}:
        return VERIFICATION_VERIFIED
    if status in {STATUS_REJECTED, DISPLAY_REJECTED}:
        return VERIFICATION_NEEDS_CORRECTION
    return "other"


def verification_status_from_subjects(subjects: Sequence[Mapping[str, Any]]) -> str:
    """Roll verification up from the items that actually require it.

    Activity-group parents are stored as completed with verification not required.
    The required task items carry the verification state.
    """
    required = [item for item in subjects or [] if _subject_requires_verification(item)]
    if not required:
        return VERIFICATION_NOT_REQUIRED
    states = [_subject_verification_state(item) for item in required]
    if any(state == VERIFICATION_NEEDS_CORRECTION for state in states):
        return VERIFICATION_NEEDS_CORRECTION
    verified = sum(state == VERIFICATION_VERIFIED for state in states)
    if verified == len(states):
        return VERIFICATION_VERIFIED
    if verified:
        return VERIFICATION_PARTIAL
    return VERIFICATION_WAITING


def verification_subjects_for_contribution(contrib: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = [item for item in (contrib.get("group_items") or []) if isinstance(item, Mapping)]
    if items:
        return items
    activity = contrib.get("activity") or {}
    if activity:
        return [activity]
    return []


def completion_status_from_members(statuses: Sequence[str]) -> str:
    values = [str(status or "") for status in statuses]
    if values and all(status in _FINISHED_WORK_DISPLAY for status in values):
        return COMPLETION_COMPLETED
    if any(status in _STARTED_DISPLAY or status in _FINISHED_WORK_DISPLAY for status in values):
        return COMPLETION_IN_PROGRESS
    return COMPLETION_NOT_STARTED


def assignment_completion_status(row: Mapping[str, Any]) -> str:
    return completion_status_from_members(
        [str(contrib.get("status") or "") for contrib in (row.get("contributions") or [])]
    )


def assignment_verification_status(row: Mapping[str, Any]) -> str:
    subjects: list[Mapping[str, Any]] = []
    for contrib in row.get("contributions") or []:
        subjects.extend(verification_subjects_for_contribution(contrib))
    return verification_status_from_subjects(subjects)


def assignment_is_started(row: Mapping[str, Any]) -> bool:
    return any(str(c.get("status") or "") in _STARTED_DISPLAY for c in (row.get("contributions") or []))


def assignment_is_completed(row: Mapping[str, Any]) -> bool:
    """One required assignment is complete when every member has finished the work.

    Shared Execution is still one assignment: two finished timers do not make two completions.
    A partner who has not finished keeps the assignment incomplete. A finished submission
    that needs correction is still complete; it is not verified.
    """
    recorded = str(row.get("completion_status") or "")
    if recorded:
        return recorded == COMPLETION_COMPLETED
    contribs = list(row.get("contributions") or [])
    if not contribs:
        return False
    return all(str(c.get("status") or "") in _SUCCESS_DISPLAY for c in contribs)


def _contribution_verification_satisfied(contrib: Mapping[str, Any]) -> bool:
    status = str(contrib.get("status") or "")
    if status not in _SUCCESS_DISPLAY:
        return False
    rolled = verification_status_from_subjects(verification_subjects_for_contribution(contrib))
    return rolled in {VERIFICATION_NOT_REQUIRED, VERIFICATION_VERIFIED}


def assignment_is_verified(row: Mapping[str, Any]) -> bool:
    if not assignment_is_completed(row):
        return False
    contribs = list(row.get("contributions") or [])
    return bool(contribs) and all(_contribution_verification_satisfied(c) for c in contribs)


def assignment_needs_correction(row: Mapping[str, Any]) -> bool:
    if str(row.get("verification_status") or "") == VERIFICATION_NEEDS_CORRECTION:
        return True
    return any(
        str(c.get("status") or "") == DISPLAY_REJECTED for c in (row.get("contributions") or [])
    ) and not assignment_is_completed(row)


def dashboard_summary(
    cursor,
    organization_id: int,
    *,
    business_date: date | None = None,
    user_id: int | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    ensure_cleaning_task_activity_tables(cursor)
    try:
        from backend.cleaning_task_manual_completion import ensure_manual_completion_schema

        ensure_manual_completion_schema(cursor)
    except Exception:
        pass
    day = business_date or business_today()
    queue = list_supervisor_queue(
        cursor,
        organization_id,
        business_date=day,
        status=None,
        user_id=user_id,
        role=role,
    )
    catalog = _role_catalog(cursor, int(organization_id))
    assignments = _day_responsibilities(cursor, organization_id, business_date=day)
    activities = _activities_for_day(cursor, organization_id, day, user_id=user_id)
    if role:
        activities = [a for a in activities if str(a.get("role")) == str(role)]
    by_resp = _latest_activity_by_resp(activities)
    name_ids = {int(a["user_id"]) for a in assignments}
    name_ids |= {int(r["user_id"]) for r in activities}
    name_ids |= {
        int(r["approved_by_user_id"])
        for r in activities
        if r.get("approved_by_user_id") is not None
    }
    names = _employee_names(cursor, organization_id, sorted(name_ids))
    now = business_now()
    if getattr(now, "tzinfo", None) is not None:
        now = now.replace(tzinfo=None)

    shared_assignments = _group_shared_assignments(
        assignments,
        by_resp,
        catalog=catalog,
        names=names,
        now=now,
        cursor=cursor,
        organization_id=int(organization_id),
        business_date=day,
        user_id=user_id,
        role=role,
        activities=activities,
    )

    # Headline counts are distinct required assignments. A shared group is one assignment
    # no matter how many employees or activity rows it has. Contribution rows stay on the
    # drill-down (queue, durations, activity log) and are not added into these totals.
    assigned_unique = len(shared_assignments)
    overdue_unique = sum(1 for row in shared_assignments if row["status"] == DISPLAY_OVERDUE)
    started = sum(1 for row in shared_assignments if assignment_is_started(row))
    completed = sum(1 for row in shared_assignments if assignment_is_completed(row))
    verified = sum(1 for row in shared_assignments if assignment_is_verified(row))
    pending_verification = sum(
        1
        for row in shared_assignments
        if str(row.get("verification_status") or "") in {VERIFICATION_WAITING, VERIFICATION_PARTIAL}
    )
    rejected_assignments = sum(1 for row in shared_assignments if assignment_needs_correction(row))
    completion_rate = round((completed / assigned_unique) * 100, 1) if assigned_unique else None
    verification_rate = round((verified / assigned_unique) * 100, 1) if assigned_unique else None
    # Count group timer once (parent only); ignore group_item children (duration NULL / excluded).
    time_spent = sum(
        int(a.get("duration_seconds") or 0)
        for a in activities
        if a.get("duration_seconds") is not None
        and a.get("parent_activity_id") is None
        and str(a.get("activity_kind") or "") != "group_item"
    )
    try:
        cats = list_categories(cursor, int(organization_id), include_inactive=False)
    except Exception:
        cats = []
    by_cat: dict[str, dict[str, int]] = {
        c["code"]: {
            "assigned": 0,
            "started": 0,
            "completed": 0,
            "pending_verification": 0,
            "verified": 0,
            "rejected": 0,
            "overdue": 0,
        }
        for c in cats
    }
    for row in shared_assignments:
        meta = _task_meta_for_role(cursor, int(organization_id), str(row.get("role") or ""))
        code = str(meta.get("category_code") or "intra_day")
        bucket = by_cat.setdefault(
            code,
            {
                "assigned": 0,
                "started": 0,
                "completed": 0,
                "pending_verification": 0,
                "verified": 0,
                "rejected": 0,
                "overdue": 0,
            },
        )
        bucket["assigned"] += 1
        if assignment_is_started(row):
            bucket["started"] += 1
        if assignment_is_completed(row):
            bucket["completed"] += 1
        if assignment_is_verified(row):
            bucket["verified"] += 1
        if str(row.get("verification_status") or "") in {VERIFICATION_WAITING, VERIFICATION_PARTIAL}:
            bucket["pending_verification"] += 1
        if assignment_needs_correction(row):
            bucket["rejected"] += 1
        if row.get("status") == DISPLAY_OVERDUE:
            bucket["overdue"] += 1
    metrics = {
        "total_assigned": assigned_unique,
        "started": started,
        "completed": completed,
        "approved": len(queue["approved"]),
        "verified": verified,
        "pending_approval": len(queue["pending_approval"]),
        "pending_verification": pending_verification,
        "overdue": overdue_unique,
        "rejected": rejected_assignments,
        "in_progress": len(queue["in_progress"]),
        "not_started": len(queue["not_started"]),
        "completed_no_verification": len(queue.get("completed_without_verification") or []),
        "completion_rate": completion_rate,
        "verification_rate": verification_rate,
        "time_spent_seconds": time_spent,
        # Per-employee drill-down. This may exceed Assigned when a task is shared.
        "contributions_assigned": sum(len(row.get("contributions") or []) for row in shared_assignments),
    }
    category_breakdown = []
    for c in cats:
        bucket = dict(by_cat.get(c["code"]) or {})
        assigned_n = int(bucket.get("assigned") or 0)
        completed_n = int(bucket.get("completed") or 0)
        bucket["completion_rate"] = round((completed_n / assigned_n) * 100, 1) if assigned_n else None
        category_breakdown.append(
            {
                "category_code": c["code"],
                "category_name": c["name"],
                **bucket,
            }
        )

    log = []
    for row in sorted(activities, key=lambda r: int(r.get("id") or 0), reverse=True):
        if status and str(row.get("status")) != str(status):
            continue
        item = serialize_activity(row, catalog=catalog)
        item["employee_name"] = names.get(item["user_id"], f"User #{item['user_id']}")
        item["supervisor_name"] = (
            names.get(item["approved_by_user_id"]) if item.get("approved_by_user_id") else None
        )
        item["verified"] = item["status"] == STATUS_APPROVED
        group_id = item.get("assignment_group_id")
        item["assignment_key"] = (
            f"g:{item.get('business_date')}:{group_id}" if group_id else f"solo:{item['responsibility_id']}"
        )
        log.append(item)

    durations = [
        {
            "employee_id": item["user_id"],
            "employee_name": item["employee_name"],
            "role": item["role"],
            "role_label": item["role_label"],
            "duration_seconds": item.get("duration_seconds"),
            "status": item["status"],
            "verified": item["verified"],
            "activity_id": item["id"],
            "completion_input": item.get("completion_input"),
            "category_code": item.get("category_code"),
        }
        for item in log
        if item.get("duration_seconds") is not None
    ]

    checklist_reports: list[dict[str, Any]] = []
    try:
        from backend.task_checklist import build_checklist_day_status, list_checklists

        for cl in list_checklists(cursor, int(organization_id), include_inactive=False):
            if not cl.get("active"):
                continue
            checklist_reports.append(
                build_checklist_day_status(cursor, int(organization_id), cl, day)
            )
    except Exception:
        checklist_reports = []

    return {
        "business_date": str(day),
        "approval_policy": queue.get("approval_policy"),
        "approval_policy_label": queue.get("approval_policy_label"),
        "metrics": metrics,
        "category_breakdown": category_breakdown,
        "shared_assignments": shared_assignments,
        "durations": durations,
        "activity_log": log,
        "queue": queue,
        "shift_end": queue.get("shift_end"),
        "checklists": checklist_reports,
    }


def user_can_verify_activity(
    cursor,
    *,
    organization_id: int,
    activity: Mapping[str, Any],
    verifier_user_id: int,
    verifier_roles: Sequence[str] | None = None,
    has_supervisor_review: bool = False,
) -> bool:
    """Backend authorization for verifying a completed contribution."""
    if int(activity.get("user_id") or 0) == int(verifier_user_id):
        return False
    if str(activity.get("status")) != STATUS_PENDING_APPROVAL:
        return False
    method = str(activity.get("verification_method") or VERIFY_SUPERVISOR)
    meta = _task_meta_for_role(cursor, int(organization_id), str(activity.get("role") or ""))
    if activity.get("verification_required") in (0, False) or method == VERIFY_NONE:
        return False
    config = meta.get("verifier_config") or {}
    if method == VERIFY_SUPERVISOR:
        return bool(has_supervisor_review)
    if method == VERIFY_EMPLOYEE:
        allowed = {int(x) for x in (config.get("user_ids") or config.get("employee_ids") or []) if x}
        if allowed:
            return int(verifier_user_id) in allowed
        # No explicit list: any other employee with Tasks access may verify.
        return True
    if method == VERIFY_ROLE:
        needed = {str(x).upper() for x in (config.get("roles") or config.get("role_codes") or []) if x}
        have = {str(x).upper() for x in (verifier_roles or []) if x}
        return bool(needed & have) or bool(has_supervisor_review)
    return bool(has_supervisor_review)


def list_tasks_to_verify(
    cursor,
    organization_id: int,
    verifier_user_id: int,
    *,
    as_of: date | None = None,
    verifier_roles: Sequence[str] | None = None,
    has_supervisor_review: bool = False,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Pending verification items this employee is authorized to verify (incl. prior days)."""
    ensure_cleaning_task_activity_tables(cursor)
    try:
        seed_builtin_categories(cursor, int(organization_id))
    except Exception:
        pass
    day = as_of or business_today()
    catalog = _role_catalog(cursor, int(organization_id))
    start = day - timedelta(days=max(0, int(lookback_days)))
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id = %s
          AND status = %s
          AND business_date >= %s
          AND business_date <= %s
        ORDER BY business_date ASC, id ASC
        """,
        (int(organization_id), STATUS_PENDING_APPROVAL, start, day),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    name_ids = {int(r["user_id"]) for r in rows}
    names = _employee_names(cursor, organization_id, sorted(name_ids))
    pending = []
    for row in rows:
        if not user_can_verify_activity(
            cursor,
            organization_id=int(organization_id),
            activity=row,
            verifier_user_id=int(verifier_user_id),
            verifier_roles=verifier_roles,
            has_supervisor_review=has_supervisor_review,
        ):
            continue
        timing = str(row.get("verification_timing") or "same_shift")
        biz = row.get("business_date")
        if isinstance(biz, date):
            biz_day = biz
        else:
            try:
                biz_day = date.fromisoformat(str(biz)[:10])
            except ValueError:
                biz_day = day
        if timing == VERIFY_TIMING_NEXT_DAY and biz_day >= day:
            # Next-day items stay on the original date until the following business day.
            continue
        ser = serialize_activity(row, catalog=catalog)
        ser["employee_name"] = names.get(int(row["user_id"]), f"User #{row['user_id']}")
        ser["original_business_date"] = ser["business_date"]
        meta = _task_meta_for_role(cursor, int(organization_id), str(row.get("role") or ""))
        ser["category_code"] = ser.get("category_code") or meta.get("category_code")
        ser["category_name"] = meta.get("category_name")
        pending.append(ser)
    return {
        "as_of": str(day),
        "verifier_user_id": int(verifier_user_id),
        "pending_verification": pending,
        "count": len(pending),
    }


def attendance_cleaning_snapshot(cursor, organization_id: int, user_id: int) -> dict[str, Any]:
    """Fields merged into PIN hub attendance for active cleaning task."""
    catalog = _role_catalog(cursor, int(organization_id))
    open_row = get_open_activity(cursor, organization_id, user_id)
    if not open_row:
        return {
            "on_cleaning_task": False,
            "cleaning_task_started_at": None,
            "cleaning_task_label": None,
            "cleaning_activity_id": None,
        }
    ser = serialize_activity(open_row, catalog=catalog)
    return {
        "on_cleaning_task": True,
        "cleaning_task_started_at": ser.get("started_at"),
        "cleaning_task_label": ser.get("role_label") or ser.get("role"),
        "cleaning_activity_id": ser.get("id"),
    }


_RINSE_TASK_DURATION_KEYS = (
    "duration_seconds",
    "group_duration_seconds",
    "time_spent_seconds",
)


def _strip_task_duration_fields(row: Any) -> Any:
    """Remove labor/duration fields from nested dashboard structures (Rinse viewers)."""
    if isinstance(row, list):
        return [_strip_task_duration_fields(item) for item in row]
    if not isinstance(row, Mapping):
        return row
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in _RINSE_TASK_DURATION_KEYS:
            continue
        out[key] = _strip_task_duration_fields(value)
    return out


def apply_rinse_task_dashboard_scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """API-level filter: keep compliance/verification; strip durations and labor hours."""
    out = dict(payload)
    metrics = dict(out.get("metrics") or {})
    metrics.pop("time_spent_seconds", None)
    out["metrics"] = metrics
    out["durations"] = []
    out["shared_assignments"] = _strip_task_duration_fields(out.get("shared_assignments") or [])
    out["activity_log"] = _strip_task_duration_fields(out.get("activity_log") or [])
    queue = out.get("queue")
    if isinstance(queue, Mapping):
        out["queue"] = _strip_task_duration_fields(queue)
    shift_end = out.get("shift_end")
    if isinstance(shift_end, Mapping):
        out["shift_end"] = _strip_task_duration_fields(shift_end)
    if "checklists" in out:
        out["checklists"] = _strip_task_duration_fields(out.get("checklists") or [])
    out["hide_labor_metrics"] = True
    out["labor_fields_hidden"] = True
    return out
