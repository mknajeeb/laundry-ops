"""Supervisor record management: edit times/business date, soft-void, audit trail.

Does not physically delete activities. Does not change payroll or attendance tables.
Verification approvals are preserved unless an authorized manager edits the row
(and even then prior values are stored in cleaning_task_completion_revisions).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Optional

from backend.cleaning_task_activity import (
    TABLE,
    CleaningTaskError,
    _record_event,
    ensure_cleaning_task_activity_tables,
    get_activity,
    serialize_activity,
)
from backend.cleaning_task_manual_completion import (
    REVISIONS_TABLE,
    SOURCE_CORRECTED,
    SOURCE_MANUAL,
    SOURCE_PIN,
    _parse_et_date,
    _parse_et_datetime,
    ensure_manual_completion_schema,
)
from backend.ta_helpers import remember_column, table_exists, table_has_column

CHANGE_CORRECTION = "correction"
CHANGE_BUSINESS_DATE = "business_date"
CHANGE_VOID = "void"
CHANGE_CREATE = "manual_create"

_VOID_COLUMNS: tuple[tuple[str, str], ...] = (
    ("voided_at", "DATETIME NULL"),
    ("voided_by_user_id", "INT NULL"),
    ("void_reason", "VARCHAR(500) NULL"),
    ("superseded_by_activity_id", "BIGINT NULL"),
)


def ensure_record_management_schema(cursor) -> None:
    ensure_cleaning_task_activity_tables(cursor)
    ensure_manual_completion_schema(cursor)
    if not table_has_column(cursor, TABLE, "participation_sessions_json"):
        cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN participation_sessions_json TEXT NULL")
        remember_column(TABLE, "participation_sessions_json")
    for col, ddl in _VOID_COLUMNS:
        if not table_has_column(cursor, TABLE, col):
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
            remember_column(TABLE, col)
    if table_exists(cursor, REVISIONS_TABLE) and not table_has_column(
        cursor, REVISIONS_TABLE, "change_type"
    ):
        cursor.execute(
            f"""
            ALTER TABLE {REVISIONS_TABLE}
              ADD COLUMN change_type VARCHAR(32) NOT NULL DEFAULT 'correction'
              AFTER revised_by_user_id
            """
        )
        remember_column(REVISIONS_TABLE, "change_type")


def activity_is_voided(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False
    return row.get("voided_at") not in (None, "")


def activity_has_manual_touch(row: Mapping[str, Any] | None) -> bool:
    """True when the live row was created or altered outside the normal PIN path."""
    if not row:
        return False
    source = str(row.get("completion_source") or SOURCE_PIN).strip().lower()
    if source in {SOURCE_MANUAL, SOURCE_CORRECTED}:
        return True
    if row.get("times_manual") in (1, True, "1"):
        return True
    if row.get("recorded_by_user_id") not in (None, "", 0, "0"):
        # recorded_by alone can appear on PIN rows in some paths; only treat as
        # manual when source is not pin OR times_manual / voided.
        if source != SOURCE_PIN:
            return True
    return False


def activity_is_rinse_eligible(row: Mapping[str, Any] | None) -> bool:
    """PIN-original, non-voided, non-superseded activities only."""
    if not row:
        return False
    if activity_is_voided(row):
        return False
    if row.get("superseded_by_activity_id") not in (None, "", 0, "0"):
        return False
    source = str(row.get("completion_source") or SOURCE_PIN).strip().lower()
    if source != SOURCE_PIN:
        return False
    if row.get("times_manual") in (1, True, "1"):
        return False
    return True


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "user_id",
        "role",
        "business_date",
        "status",
        "started_at",
        "ended_at",
        "duration_seconds",
        "completion_source",
        "times_manual",
        "recorded_by_user_id",
        "manual_reason",
        "voided_at",
        "voided_by_user_id",
        "void_reason",
        "verification_required",
        "verification_method",
        "approved_by_user_id",
        "approved_at",
        "assignment_group_id",
        "activity_kind",
        "parent_activity_id",
        "participation_sessions_json",
    )
    out: dict[str, Any] = {}
    for key in keys:
        val = row.get(key)
        if isinstance(val, datetime):
            out[key] = val.replace(microsecond=0).isoformat(sep=" ")
        elif isinstance(val, date):
            # date.isoformat() does not accept sep; business_date is a date.
            out[key] = val.isoformat()
        else:
            out[key] = val
    return out


def _insert_revision(
    cursor,
    *,
    organization_id: int,
    activity_id: int,
    revised_by_user_id: int,
    change_type: str,
    reason: str,
    remarks: str | None,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    has_change_type = table_has_column(cursor, REVISIONS_TABLE, "change_type")
    if has_change_type:
        cursor.execute(
            f"""
            INSERT INTO {REVISIONS_TABLE}
              (organization_id, activity_id, revised_by_user_id, change_type, reason, remarks, before_json, after_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                int(activity_id),
                int(revised_by_user_id),
                str(change_type),
                str(reason)[:500],
                (str(remarks)[:1000] if remarks else None),
                json.dumps(before, default=str),
                json.dumps(after, default=str),
            ),
        )
    else:
        cursor.execute(
            f"""
            INSERT INTO {REVISIONS_TABLE}
              (organization_id, activity_id, revised_by_user_id, reason, remarks, before_json, after_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                int(activity_id),
                int(revised_by_user_id),
                str(reason)[:500],
                (str(remarks)[:1000] if remarks else None),
                json.dumps(before, default=str),
                json.dumps(after, default=str),
            ),
        )


def _recalc_duration(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if not started_at or not ended_at:
        return None
    return max(0, int((ended_at - started_at).total_seconds()))


def update_activity_record(
    conn,
    cursor,
    *,
    organization_id: int,
    editor_user_id: int,
    activity_id: int,
    reason: str,
    remarks: str | None = None,
    started_at: Any = None,
    ended_at: Any = None,
    business_date: Any = None,
) -> dict[str, Any]:
    """Edit start/end and/or business date with full audit.

    Verification preservation rule:
    - approved_by_user_id / approved_at / status are **preserved** (never silently cleared).
    - Row is marked completion_source=corrected + times_manual for Rinse exclusion.
    - Before/after snapshots land in cleaning_task_completion_revisions.
    - Does not write payroll or attendance tables.
    """
    ensure_record_management_schema(cursor)
    reason_text = str(reason or "").strip()
    if len(reason_text) < 3:
        raise CleaningTaskError("A reason is required for record changes.", status=400)

    oid = int(organization_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row:
        raise CleaningTaskError("Activity not found.", status=404)
    if activity_is_voided(row):
        raise CleaningTaskError("Cannot edit a voided activity.", status=409)

    before = _snapshot(row)
    new_started = row.get("started_at")
    new_ended = row.get("ended_at")
    new_bday = row.get("business_date")
    change_type = CHANGE_CORRECTION

    if started_at not in (None, ""):
        new_started = _parse_et_datetime(started_at, field="started_at")
    if ended_at not in (None, ""):
        new_ended = _parse_et_datetime(ended_at, field="ended_at")
    if business_date not in (None, ""):
        new_bday = _parse_et_date(business_date)
        change_type = CHANGE_BUSINESS_DATE if started_at in (None, "") and ended_at in (None, "") else CHANGE_CORRECTION

    if new_started and new_ended and new_ended < new_started:
        raise CleaningTaskError("End time must be on or after start time.", status=400)

    duration = _recalc_duration(
        new_started if isinstance(new_started, datetime) else None,
        new_ended if isinstance(new_ended, datetime) else None,
    )
    # group_item timestamps are check-offs; keep duration null
    if str(row.get("activity_kind") or "") == "group_item":
        duration = None

    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET started_at=%s, ended_at=%s, duration_seconds=%s, business_date=%s,
            completion_source=%s, times_manual=1, recorded_by_user_id=%s,
            manual_reason=%s, manual_remarks=%s, updated_at=UTC_TIMESTAMP()
        WHERE id=%s AND organization_id=%s
        """,
        (
            new_started,
            new_ended,
            duration,
            new_bday,
            SOURCE_CORRECTED,
            int(editor_user_id),
            reason_text[:500],
            (str(remarks)[:1000] if remarks else None),
            int(activity_id),
            oid,
        ),
    )
    after_row = get_activity(cursor, oid, int(activity_id)) or {}
    after = _snapshot(after_row)
    _insert_revision(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        revised_by_user_id=int(editor_user_id),
        change_type=change_type,
        reason=reason_text,
        remarks=remarks,
        before=before,
        after=after,
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="record_corrected",
        actor_user_id=int(editor_user_id),
        payload={"change_type": change_type, "reason": reason_text, "before": before, "after": after},
    )
    conn.commit()
    return serialize_activity(after_row)


def void_activity_record(
    conn,
    cursor,
    *,
    organization_id: int,
    editor_user_id: int,
    activity_id: int,
    reason: str,
    remarks: str | None = None,
) -> dict[str, Any]:
    """Soft-void: hide from operational reporting; keep row + audit forever."""
    ensure_record_management_schema(cursor)
    reason_text = str(reason or "").strip()
    if len(reason_text) < 3:
        raise CleaningTaskError("A reason is required to remove an activity from reporting.", status=400)

    oid = int(organization_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row:
        raise CleaningTaskError("Activity not found.", status=404)
    if activity_is_voided(row):
        raise CleaningTaskError("Activity is already voided.", status=409)

    before = _snapshot(row)
    now = datetime.utcnow().replace(microsecond=0)
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET voided_at=%s, voided_by_user_id=%s, void_reason=%s, updated_at=UTC_TIMESTAMP()
        WHERE id=%s AND organization_id=%s
        """,
        (now, int(editor_user_id), reason_text[:500], int(activity_id), oid),
    )
    # Soft-void children so group items leave operational views too.
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET voided_at=%s, voided_by_user_id=%s, void_reason=%s, updated_at=UTC_TIMESTAMP()
        WHERE organization_id=%s AND parent_activity_id=%s AND voided_at IS NULL
        """,
        (now, int(editor_user_id), reason_text[:500], oid, int(activity_id)),
    )
    after_row = get_activity(cursor, oid, int(activity_id)) or {}
    after = _snapshot(after_row)
    _insert_revision(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        revised_by_user_id=int(editor_user_id),
        change_type=CHANGE_VOID,
        reason=reason_text,
        remarks=remarks,
        before=before,
        after=after,
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="record_voided",
        actor_user_id=int(editor_user_id),
        payload={"reason": reason_text, "before": before, "after": after},
    )
    conn.commit()
    return serialize_activity(after_row)


def list_activity_revisions(cursor, organization_id: int, activity_id: int) -> list[dict[str, Any]]:
    ensure_record_management_schema(cursor)
    if not table_exists(cursor, REVISIONS_TABLE):
        return []
    cursor.execute(
        f"""
        SELECT id, organization_id, activity_id, revised_by_user_id,
               COALESCE(change_type, 'correction') AS change_type,
               reason, remarks, before_json, after_json, created_at
        FROM {REVISIONS_TABLE}
        WHERE organization_id=%s AND activity_id=%s
        ORDER BY id ASC
        """,
        (int(organization_id), int(activity_id)),
    )
    rows = cursor.fetchall() or []
    out = []
    for row in rows:
        item = dict(row)
        for key in ("before_json", "after_json"):
            raw = item.get(key)
            try:
                item[key.replace("_json", "")] = json.loads(raw) if raw else {}
            except Exception:
                item[key.replace("_json", "")] = {}
        out.append(item)
    return out


def plan_participation_sessions(status: str, sessions: list[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Validate one employee's work sessions. A gap between sessions is a break.

    Times are America/New_York wall times. This does not touch checklist rows.
    """
    chosen = str(status or "").strip().lower()
    if chosen not in {"not_started", "in_progress", "finished"}:
        raise CleaningTaskError("Participation status must be Not Started, In Progress, or Finished.", status=400)
    raw_sessions = list(sessions or [])
    if chosen == "not_started":
        if raw_sessions:
            raise CleaningTaskError("Not Started cannot include work sessions.", status=400)
        return {
            "participation_status": chosen,
            "sessions": [],
            "started_at": None,
            "ended_at": None,
            "duration_seconds": None,
        }
    if not raw_sessions:
        raise CleaningTaskError("Add at least one work session.", status=400)
    parsed: list[dict[str, datetime | None]] = []
    for index, item in enumerate(raw_sessions):
        if not isinstance(item, Mapping):
            raise CleaningTaskError("Each work session needs a start time.", status=400)
        start = item.get("started_at")
        end = item.get("ended_at")
        if not isinstance(start, datetime):
            raise CleaningTaskError("Each work session needs a start time.", status=400)
        if end is not None and not isinstance(end, datetime):
            raise CleaningTaskError("Finish time is not a valid America/New_York time.", status=400)
        parsed.append({"started_at": start.replace(microsecond=0), "ended_at": end.replace(microsecond=0) if isinstance(end, datetime) else None})
    parsed.sort(key=lambda item: item["started_at"] or datetime.min)
    for index, item in enumerate(parsed):
        start = item["started_at"]
        end = item["ended_at"]
        last = index == len(parsed) - 1
        if chosen == "in_progress" and last:
            if end is not None:
                raise CleaningTaskError("In Progress must end with an open session.", status=400)
        elif end is None:
            raise CleaningTaskError("Only the last session of in-progress work can omit a finish time.", status=400)
        elif end < start:
            raise CleaningTaskError("Finish time cannot be before start time.", status=400)
        if index:
            previous_end = parsed[index - 1]["ended_at"]
            if previous_end is not None and start < previous_end:
                raise CleaningTaskError("Work sessions cannot overlap. Leave a gap for a break.", status=400)
    duration = 0
    counted = False
    for item in parsed:
        if item["ended_at"] is not None and item["started_at"] is not None:
            duration += max(0, int((item["ended_at"] - item["started_at"]).total_seconds()))
            counted = True
    stored = [
        {
            "started_at": item["started_at"].strftime("%Y-%m-%d %H:%M:%S") if item["started_at"] else None,
            "ended_at": item["ended_at"].strftime("%Y-%m-%d %H:%M:%S") if item["ended_at"] else None,
        }
        for item in parsed
    ]
    return {
        "participation_status": chosen,
        "sessions": stored,
        "started_at": parsed[0]["started_at"],
        "ended_at": parsed[-1]["ended_at"],
        "duration_seconds": duration if counted else None,
    }


def _latest_participation_activity(cursor, organization_id: int, responsibility_id: int, user_id: int):
    void_sql = " AND voided_at IS NULL" if table_has_column(cursor, TABLE, "voided_at") else ""
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id=%s AND responsibility_id=%s AND user_id=%s
          AND parent_activity_id IS NULL
          {void_sql}
        ORDER BY id DESC LIMIT 1
        """,
        (int(organization_id), int(responsibility_id), int(user_id)),
    )
    return cursor.fetchone()


def correct_employee_participation(
    conn,
    cursor,
    *,
    organization_id: int,
    supervisor_user_id: int,
    responsibility_id: int,
    employee_user_id: int,
    business_date: Any,
    participation_status: str,
    sessions: list[Mapping[str, Any]] | None,
    reason: str,
    activity_id: int | None = None,
) -> dict[str, Any]:
    """Correct one employee's timer. Does not check off checklist items or open verification."""
    reason_text = str(reason or "").strip()
    if len(reason_text) < 3:
        raise CleaningTaskError("A correction reason is required.", status=400)
    ensure_record_management_schema(cursor)
    from backend.cleaning_task_manual_completion import _parse_et_datetime

    parsed_sessions = []
    for item in sessions or []:
        if not isinstance(item, Mapping):
            raise CleaningTaskError("Each work session needs a start time.", status=400)
        parsed_sessions.append(
            {
                "started_at": _parse_et_datetime(item.get("started_at"), field="started_at"),
                "ended_at": _parse_et_datetime(item.get("ended_at"), field="ended_at")
                if item.get("ended_at") not in (None, "")
                else None,
            }
        )
    plan = plan_participation_sessions(participation_status, parsed_sessions)
    day = _parse_et_date(business_date)
    if day is None:
        raise CleaningTaskError("A business date is required.", status=400)
    oid = int(organization_id)
    employee = int(employee_user_id)
    from backend.cleaning_task_activity import (
        STATUS_APPROVED,
        STATUS_COMPLETED,
        STATUS_IN_PROGRESS,
        STATUS_PENDING_APPROVAL,
        _day_responsibilities,
    )

    assignments = _day_responsibilities(cursor, oid, business_date=day, user_id=employee)
    target = next((row for row in assignments if int(row.get("id") or 0) == int(responsibility_id)), None)
    if not target or int(target.get("user_id") or 0) != employee:
        raise CleaningTaskError("Assignment not found for that employee on the selected date.", status=404)

    row = None
    if activity_id:
        row = get_activity(cursor, oid, int(activity_id))
        if not row or int(row.get("user_id") or 0) != employee or int(row.get("responsibility_id") or 0) != int(responsibility_id):
            raise CleaningTaskError("That participation record does not belong to this employee.", status=404)
        if activity_is_voided(row):
            raise CleaningTaskError("Cannot edit a voided activity.", status=409)
    else:
        row = _latest_participation_activity(cursor, oid, int(responsibility_id), employee)

    chosen = plan["participation_status"]
    if chosen == "not_started":
        if not row:
            return {"ok": True, "participation_status": "not_started", "activity": None}
        if str(row.get("status") or "") == STATUS_APPROVED:
            raise CleaningTaskError(
                "Approved participation cannot be reset to Not Started. Correct the times instead.",
                status=409,
            )
        before = _snapshot(row)
        now = datetime.utcnow().replace(microsecond=0)
        cursor.execute(
            f"""
            UPDATE {TABLE}
            SET voided_at=%s, voided_by_user_id=%s, void_reason=%s,
                completion_source=%s, times_manual=1, recorded_by_user_id=%s,
                manual_reason=%s, updated_at=UTC_TIMESTAMP()
            WHERE id=%s AND organization_id=%s
            """,
            (
                now,
                int(supervisor_user_id),
                reason_text[:500],
                SOURCE_CORRECTED,
                int(supervisor_user_id),
                reason_text[:500],
                int(row["id"]),
                oid,
            ),
        )
        after_row = get_activity(cursor, oid, int(row["id"])) or {}
        after = _snapshot(after_row)
        _insert_revision(
            cursor,
            organization_id=oid,
            activity_id=int(row["id"]),
            revised_by_user_id=int(supervisor_user_id),
            change_type=CHANGE_VOID,
            reason=reason_text,
            remarks=None,
            before=before,
            after=after,
        )
        _record_event(
            cursor,
            organization_id=oid,
            activity_id=int(row["id"]),
            event_type="participation_corrected",
            actor_user_id=int(supervisor_user_id),
            payload={"reason": reason_text, "before": before, "after": after},
        )
        conn.commit()
        return {"ok": True, "participation_status": "not_started", "activity": serialize_activity(after_row)}

    if row and str(row.get("status") or "") == STATUS_APPROVED and chosen != "finished":
        raise CleaningTaskError("Approved participation can only have its times corrected.", status=409)
    if row and str(row.get("status") or "") == "rejected":
        row = None

    if row is None:
        from backend.cleaning_task_group_execution import start_group_activity
        from backend.cleaning_task_activity import start_task
        from backend.task_activity_groups import is_activity_group_code

        if is_activity_group_code(str(target.get("role") or "")):
            started = start_group_activity(
                conn,
                cursor,
                organization_id=oid,
                user_id=employee,
                responsibility_id=int(responsibility_id),
                shift_session_id=None,
                business_date=day,
            )
        else:
            started = start_task(
                conn,
                cursor,
                organization_id=oid,
                user_id=employee,
                responsibility_id=int(responsibility_id),
                shift_session_id=None,
                business_date=day,
            )
        row = get_activity(cursor, oid, int(started["id"]))
        if not row:
            raise CleaningTaskError("Participation record could not be created.", status=500)

    before = _snapshot(row)
    current_status = str(row.get("status") or "")
    if current_status == STATUS_APPROVED:
        next_status = current_status
    elif chosen == "in_progress":
        next_status = STATUS_IN_PROGRESS
    elif current_status == STATUS_PENDING_APPROVAL:
        next_status = current_status
    else:
        next_status = STATUS_COMPLETED
    sessions_json = json.dumps(plan["sessions"])
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET started_at=%s, ended_at=%s, duration_seconds=%s, status=%s, business_date=%s,
            completion_source=%s, times_manual=1, recorded_by_user_id=%s, manual_reason=%s,
            participation_sessions_json=%s, updated_at=UTC_TIMESTAMP()
        WHERE id=%s AND organization_id=%s
        """,
        (
            plan["started_at"],
            plan["ended_at"],
            plan["duration_seconds"],
            next_status,
            day,
            SOURCE_CORRECTED,
            int(supervisor_user_id),
            reason_text[:500],
            sessions_json,
            int(row["id"]),
            oid,
        ),
    )
    after_row = get_activity(cursor, oid, int(row["id"])) or {}
    after = _snapshot(after_row)
    _insert_revision(
        cursor,
        organization_id=oid,
        activity_id=int(row["id"]),
        revised_by_user_id=int(supervisor_user_id),
        change_type=CHANGE_CORRECTION,
        reason=reason_text,
        remarks=None,
        before=before,
        after=after,
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(row["id"]),
        event_type="participation_corrected",
        actor_user_id=int(supervisor_user_id),
        payload={"reason": reason_text, "before": before, "after": after, "sessions": plan["sessions"]},
    )
    conn.commit()
    return {"ok": True, "participation_status": chosen, "activity": serialize_activity(after_row)}
