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
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

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
    for col, ddl in _VOID_COLUMNS:
        if not table_has_column(cursor, TABLE, col):
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
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
    invalidate_schema_cache()


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
    )
    out: dict[str, Any] = {}
    for key in keys:
        val = row.get(key)
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat(sep=" ")
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
