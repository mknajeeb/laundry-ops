"""Supervisor manual completion and audited correction for Task Dashboard."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any, Mapping, Optional, Sequence

from backend.cleaning_task_activity import (
    COMPLETED_STATUSES,
    STATUS_IN_PROGRESS,
    TABLE,
    CleaningTaskError,
    _day_responsibilities,
    _employee_names,
    _finalize_completion,
    _record_event,
    _role_catalog,
    ensure_cleaning_task_activity_tables,
    get_activity,
    serialize_activity,
)
from backend.cleaning_task_group_execution import (
    ensure_group_activity_schema,
    is_activity_group_code,
    start_group_activity,
)
from backend.cleaning_task_shared_execution import ensure_shared_activity_schema
from backend.ta_helpers import table_exists, table_has_column, invalidate_schema_cache

SOURCE_PIN = "pin"
SOURCE_MANUAL = "manual"
SOURCE_CORRECTED = "corrected"

REVISIONS_TABLE = "cleaning_task_completion_revisions"

_MANUAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("completion_source", "VARCHAR(32) NOT NULL DEFAULT 'pin'"),
    ("recorded_by_user_id", "INT NULL"),
    ("manual_reason", "VARCHAR(500) NULL"),
    ("manual_remarks", "VARCHAR(1000) NULL"),
    ("times_manual", "TINYINT(1) NOT NULL DEFAULT 0"),
)


def ensure_manual_completion_schema(cursor) -> None:
    ensure_cleaning_task_activity_tables(cursor)
    for col, ddl in _MANUAL_COLUMNS:
        if not table_has_column(cursor, TABLE, col):
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
    if not table_exists(cursor, REVISIONS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {REVISIONS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              activity_id BIGINT NOT NULL,
              revised_by_user_id INT NOT NULL,
              reason VARCHAR(500) NOT NULL,
              remarks VARCHAR(1000) NULL,
              before_json TEXT NOT NULL,
              after_json TEXT NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_ctcr_activity (organization_id, activity_id),
              INDEX idx_ctcr_org_created (organization_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    invalidate_schema_cache()


def completion_source_label(source: Any) -> str:
    raw = str(source or SOURCE_PIN).strip().lower()
    return {
        SOURCE_PIN: "Completed via PIN",
        SOURCE_MANUAL: "Recorded by Supervisor",
        SOURCE_CORRECTED: "Corrected by Management",
    }.get(raw, "Completed via PIN")


def _parse_et_datetime(raw: Any, *, field: str) -> datetime | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:19] if fmt != "%Y-%m-%d" else text[:10], fmt)
            if fmt == "%Y-%m-%d":
                # Date-only is not enough for completion time.
                if field.endswith("time") or "completed" in field or "ended" in field:
                    raise CleaningTaskError(f"{field} requires a time (America/New_York).", status=400)
            return dt.replace(microsecond=0)
        except ValueError:
            continue
    raise CleaningTaskError(f"Invalid {field}. Use America/New_York date and time.", status=400)


def _parse_et_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CleaningTaskError("Invalid business date.", status=400) from exc


def _combine_date_time(*, day: Any, clock: Any, field: str) -> datetime | None:
    """Accept either ISO datetime or separate date + HH:MM."""
    if clock in (None, "") and day in (None, ""):
        return None
    if clock not in (None, "") and ("-" in str(clock) or "T" in str(clock)):
        return _parse_et_datetime(clock, field=field)
    d = _parse_et_date(day)
    if d is None:
        raise CleaningTaskError(f"{field} date is required.", status=400)
    clock_text = str(clock or "00:00").strip()
    try:
        hh, mm = [int(x) for x in clock_text[:5].split(":")[:2]]
    except (TypeError, ValueError) as exc:
        raise CleaningTaskError(f"Invalid {field} time.", status=400) from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise CleaningTaskError(f"Invalid {field} time.", status=400)
    return datetime.combine(d, time(hour=hh, minute=mm))


def _snapshot(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return serialize_activity(row)


def _apply_manual_fields(
    cursor,
    *,
    oid: int,
    activity_id: int,
    recorded_by: int,
    source: str,
    reason: str,
    remarks: str | None,
    times_manual: bool,
) -> None:
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET completion_source=%s,
            recorded_by_user_id=%s,
            manual_reason=%s,
            manual_remarks=%s,
            times_manual=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            source,
            int(recorded_by),
            (reason or "")[:500],
            (remarks or None),
            1 if times_manual else 0,
            int(activity_id),
            int(oid),
        ),
    )


def _existing_completed(cursor, oid: int, responsibility_id: int) -> Mapping[str, Any] | None:
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id=%s AND responsibility_id=%s
          AND status IN ('pending_approval','approved','completed','rejected')
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(oid), int(responsibility_id)),
    )
    return cursor.fetchone()


def record_manual_completion(
    conn,
    cursor,
    *,
    organization_id: int,
    supervisor_user_id: int,
    responsibility_id: int,
    employee_user_id: int,
    completed_at: datetime,
    started_at: datetime | None = None,
    reason: str,
    remarks: str | None = None,
    group_item_codes: Sequence[str] | None = None,
    shared_item_completions: Sequence[Mapping[str, Any]] | None = None,
    business_date: date | None = None,
) -> dict[str, Any]:
    """Record that work was done outside the PIN app (audited, not auto-verified)."""
    ensure_manual_completion_schema(cursor)
    ensure_group_activity_schema(cursor)
    ensure_shared_activity_schema(cursor)
    oid = int(organization_id)
    supervisor = int(supervisor_user_id)
    employee = int(employee_user_id)
    reason_clean = str(reason or "").strip()
    if len(reason_clean) < 3:
        raise CleaningTaskError("A reason for manual entry is required.", status=400)
    if employee == supervisor:
        # Allowed to record for self, but cannot later self-verify (approve_activity already blocks).
        pass

    day = business_date or completed_at.date()
    responsibilities = _day_responsibilities(cursor, oid, business_date=day, user_id=employee)
    target = next((r for r in responsibilities if int(r.get("id") or 0) == int(responsibility_id)), None)
    if not target:
        raise CleaningTaskError("Assignment not found for that employee on the selected date.", status=404)
    if int(target.get("user_id") or 0) != employee:
        raise CleaningTaskError("Employee does not match this assignment.", status=400)

    existing = _existing_completed(cursor, oid, int(responsibility_id))
    if existing and str(existing.get("status")) in COMPLETED_STATUSES - {STATUS_PENDING_APPROVAL}:
        # Rejected can be re-recorded; approved/completed need correction workflow.
        if str(existing.get("status")) in {"approved", "completed", "pending_approval"}:
            raise CleaningTaskError(
                "This assignment already has a completion record. Use Correct Completion Record.",
                status=409,
                payload={"activity_id": int(existing["id"]), "status": existing.get("status")},
            )

    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id=%s AND responsibility_id=%s AND status=%s
        ORDER BY id DESC LIMIT 1
        """,
        (oid, int(responsibility_id), STATUS_IN_PROGRESS),
    )
    open_row = cursor.fetchone()

    role = str(target.get("role") or "")
    is_group = is_activity_group_code(role)
    start_dt = started_at
    end_dt = completed_at
    if start_dt and start_dt > end_dt:
        raise CleaningTaskError("Start time cannot be after completion time.", status=400)

    times_manual = True
    duration = None
    if start_dt is not None:
        duration = max(0, int((end_dt - start_dt).total_seconds()))
    else:
        # Unknown start: do not fabricate duration; stamp started_at = completed_at.
        start_dt = end_dt
        duration = None

    if open_row:
        activity_id = int(open_row["id"])
        cursor.execute(
            f"UPDATE {TABLE} SET started_at=%s, business_date=%s WHERE id=%s AND organization_id=%s",
            (start_dt, day, activity_id, oid),
        )
        row = get_activity(cursor, oid, activity_id) or open_row
    else:
        from backend.cleaning_task_activity import start_task

        if is_group:
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
        activity_id = int(started["id"])
        cursor.execute(
            f"UPDATE {TABLE} SET started_at=%s, business_date=%s WHERE id=%s AND organization_id=%s",
            (start_dt, day, activity_id, oid),
        )
        row = get_activity(cursor, oid, activity_id)

    execution_mode = str(target.get("execution_mode") or "individual").strip().lower()
    is_shared = execution_mode == "shared" or row and row.get("shared_session_id") is not None

    attributed_items: list[dict[str, Any]] = []
    if is_shared and (shared_item_completions or group_item_codes):
        attributed_items = _apply_shared_item_attributions(
            conn,
            cursor,
            organization_id=oid,
            supervisor_user_id=supervisor,
            primary_user_id=employee,
            primary_activity_id=activity_id,
            primary_responsibility_id=int(responsibility_id),
            business_date=day,
            completed_at=end_dt,
            shared_item_completions=shared_item_completions or [],
            fallback_item_codes=list(group_item_codes or []),
        )
    elif is_group and group_item_codes:
        from backend.cleaning_task_group_execution import checkoff_group_item

        for code in group_item_codes:
            try:
                checkoff_group_item(
                    conn,
                    cursor,
                    organization_id=oid,
                    user_id=employee,
                    activity_id=activity_id,
                    task_code=str(code),
                )
            except CleaningTaskError as exc:
                if exc.status != 409:
                    raise
            attributed_items.append(
                {"task_code": str(code), "completed_by_user_id": employee}
            )

    out = _finalize_completion(
        cursor,
        oid=oid,
        uid=employee,
        activity_id=activity_id,
        row=row or {},
        at=end_dt,
        duration=duration,
        completion_input={"remarks": remarks, "values": {}, "manual": True},
        interrupt_role=False,
    )
    _apply_manual_fields(
        cursor,
        oid=oid,
        activity_id=activity_id,
        recorded_by=supervisor,
        source=SOURCE_MANUAL,
        reason=reason_clean,
        remarks=remarks,
        times_manual=times_manual,
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=activity_id,
        event_type="manual_completed",
        actor_user_id=supervisor,
        payload={
            "employee_user_id": employee,
            "completed_at": end_dt.isoformat(sep=" "),
            "started_at": start_dt.isoformat(sep=" ") if start_dt else None,
            "reason": reason_clean,
            "remarks": remarks,
            "duration_seconds": duration,
            "times_manual": times_manual,
            "group_item_codes": list(group_item_codes or []),
            "shared_item_completions": attributed_items,
            "execution_mode": "shared" if is_shared else ("group" if is_group else "individual"),
        },
    )
    updated = get_activity(cursor, oid, activity_id)
    catalog = _role_catalog(cursor, oid)
    ser = serialize_activity(updated or {}, catalog=catalog)
    name_ids = {employee, supervisor} | {
        int(i["completed_by_user_id"])
        for i in attributed_items
        if i.get("completed_by_user_id") is not None
    }
    names = _employee_names(cursor, oid, sorted(name_ids))
    ser["employee_name"] = names.get(employee)
    ser["recorded_by_name"] = names.get(supervisor)
    ser["completion_source_label"] = completion_source_label(SOURCE_MANUAL)
    ser["shared_item_completions"] = [
        {**i, "completed_by_name": names.get(int(i["completed_by_user_id"]))}
        for i in attributed_items
    ]
    return ser


def _ensure_member_shared_activity(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    responsibility_id: int,
    business_date: date,
    started_at: datetime,
) -> dict[str, Any]:
    """Start (or reuse) a shared group participation for a collaborator."""
    oid = int(organization_id)
    uid = int(user_id)
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id=%s AND responsibility_id=%s
          AND status IN ('in_progress','pending_approval','completed','approved','rejected')
        ORDER BY id DESC LIMIT 1
        """,
        (oid, int(responsibility_id)),
    )
    existing = cursor.fetchone()
    if existing and str(existing.get("status")) == STATUS_IN_PROGRESS:
        return existing
    if existing and str(existing.get("status")) in COMPLETED_STATUSES:
        return existing
    started = start_group_activity(
        conn,
        cursor,
        organization_id=oid,
        user_id=uid,
        responsibility_id=int(responsibility_id),
        shift_session_id=None,
        business_date=business_date,
    )
    aid = int(started["id"])
    cursor.execute(
        f"UPDATE {TABLE} SET started_at=%s, business_date=%s WHERE id=%s AND organization_id=%s",
        (started_at, business_date, aid, oid),
    )
    return get_activity(cursor, oid, aid) or started


def _apply_shared_item_attributions(
    conn,
    cursor,
    *,
    organization_id: int,
    supervisor_user_id: int,
    primary_user_id: int,
    primary_activity_id: int,
    primary_responsibility_id: int,
    business_date: date,
    completed_at: datetime,
    shared_item_completions: Sequence[Mapping[str, Any]],
    fallback_item_codes: Sequence[str],
) -> list[dict[str, Any]]:
    """Attribute each shared checklist item to the employee who actually did it."""
    from backend.cleaning_task_group_execution import checkoff_group_item

    oid = int(organization_id)
    primary = get_activity(cursor, oid, int(primary_activity_id))
    if not primary:
        raise CleaningTaskError("Shared activity not found.", status=404)

    # Normalize payload: explicit attributions, else fall back to primary employee.
    attributions: list[dict[str, Any]] = []
    if shared_item_completions:
        for raw in shared_item_completions:
            code = str(raw.get("task_code") or "").strip()
            if not code:
                continue
            by_uid = raw.get("completed_by_user_id")
            if by_uid in (None, ""):
                raise CleaningTaskError(
                    f"Select which employee completed {code}.",
                    status=400,
                )
            attributions.append(
                {"task_code": code, "completed_by_user_id": int(by_uid)}
            )
    else:
        for code in fallback_item_codes:
            code = str(code or "").strip()
            if code:
                attributions.append(
                    {"task_code": code, "completed_by_user_id": int(primary_user_id)}
                )
    if not attributions:
        return []

    # Map collaborators on this shared assignment.
    group_id = str(primary.get("assignment_group_id") or "").strip()
    day_rows = _day_responsibilities(cursor, oid, business_date=business_date)
    members = [
        r
        for r in day_rows
        if str(r.get("assignment_group_id") or "").strip() == group_id
        and str(r.get("role") or "") == str(primary.get("role") or "")
    ]
    by_user_resp = {int(m["user_id"]): int(m["id"]) for m in members}
    allowed_users = set(by_user_resp.keys())
    if int(primary_user_id) not in allowed_users:
        allowed_users.add(int(primary_user_id))
        by_user_resp[int(primary_user_id)] = int(primary_responsibility_id)

    activity_by_user: dict[int, dict[str, Any]] = {
        int(primary_user_id): primary
    }

    applied: list[dict[str, Any]] = []
    for item in attributions:
        code = item["task_code"]
        by_uid = int(item["completed_by_user_id"])
        if by_uid not in allowed_users:
            raise CleaningTaskError(
                f"Employee {by_uid} is not assigned to this shared activity.",
                status=400,
            )
        if by_uid not in activity_by_user:
            resp_id = by_user_resp[by_uid]
            activity_by_user[by_uid] = _ensure_member_shared_activity(
                conn,
                cursor,
                organization_id=oid,
                user_id=by_uid,
                responsibility_id=resp_id,
                business_date=business_date,
                started_at=completed_at,
            )
        member_act = activity_by_user[by_uid]
        if str(member_act.get("status")) != STATUS_IN_PROGRESS:
            # Re-open is not supported; still allow attribution if already in progress path failed.
            raise CleaningTaskError(
                f"Cannot attribute {code} to a finished participation without correction.",
                status=409,
            )
        try:
            checkoff_group_item(
                conn,
                cursor,
                organization_id=oid,
                user_id=by_uid,
                activity_id=int(member_act["id"]),
                task_code=code,
            )
        except CleaningTaskError as exc:
            if exc.status != 409:
                raise
        # Stamp historical completion time + audit (checkoff uses "now").
        session_id = member_act.get("shared_session_id") or primary.get("shared_session_id")
        if session_id is not None:
            cursor.execute(
                """
                UPDATE cleaning_task_shared_session_items
                SET completed_at=%s, completed_by_user_id=%s
                WHERE organization_id=%s AND shared_session_id=%s AND task_code=%s
                """,
                (completed_at, by_uid, oid, int(session_id), code),
            )
        _record_event(
            cursor,
            organization_id=oid,
            activity_id=int(member_act["id"]),
            event_type="manual_shared_item_attributed",
            actor_user_id=int(supervisor_user_id),
            payload={
                "task_code": code,
                "completed_by_user_id": by_uid,
                "completed_at": completed_at.isoformat(sep=" "),
                "shared_session_id": int(session_id) if session_id is not None else None,
            },
        )
        applied.append({"task_code": code, "completed_by_user_id": by_uid})

    # Finish other collaborators we started solely for attribution (independent timers).
    for uid, act in activity_by_user.items():
        if int(uid) == int(primary_user_id):
            continue
        if str(act.get("status")) != STATUS_IN_PROGRESS:
            continue
        try:
            from backend.cleaning_task_group_execution import complete_group_activity

            complete_group_activity(
                conn,
                cursor,
                organization_id=oid,
                user_id=int(uid),
                activity_id=int(act["id"]),
            )
            _apply_manual_fields(
                cursor,
                oid=oid,
                activity_id=int(act["id"]),
                recorded_by=int(supervisor_user_id),
                source=SOURCE_MANUAL,
                reason="Shared item attribution (supervisor manual entry)",
                remarks=None,
                times_manual=True,
            )
            _record_event(
                cursor,
                organization_id=oid,
                activity_id=int(act["id"]),
                event_type="manual_shared_participation_closed",
                actor_user_id=int(supervisor_user_id),
                payload={"employee_user_id": int(uid)},
            )
        except CleaningTaskError:
            # If group complete blocked (e.g. individual-mode remaining items), leave open.
            pass
    return applied


def correct_completion_record(
    cursor,
    *,
    organization_id: int,
    supervisor_user_id: int,
    activity_id: int,
    reason: str,
    remarks: str | None = None,
    completed_at: datetime | None = None,
    started_at: datetime | None = None,
    employee_user_id: int | None = None,
) -> dict[str, Any]:
    """Audited revision of an existing completion (does not silently overwrite history)."""
    ensure_manual_completion_schema(cursor)
    oid = int(organization_id)
    supervisor = int(supervisor_user_id)
    reason_clean = str(reason or "").strip()
    if len(reason_clean) < 3:
        raise CleaningTaskError("A correction reason is required.", status=400)
    row = get_activity(cursor, oid, int(activity_id))
    if not row:
        raise CleaningTaskError("Activity not found.", status=404)
    if str(row.get("status")) not in COMPLETED_STATUSES | {STATUS_IN_PROGRESS}:
        raise CleaningTaskError("Only started or completed records can be corrected.", status=400)

    before = _snapshot(row)
    end_dt = completed_at
    start_dt = started_at
    if end_dt is None and start_dt is None and employee_user_id is None:
        raise CleaningTaskError("Provide at least one corrected field.", status=400)
    if end_dt is None:
        end_dt = row.get("ended_at")
        if isinstance(end_dt, str):
            end_dt = _parse_et_datetime(end_dt, field="completed_at")
    if start_dt is None:
        start_dt = row.get("started_at")
        if isinstance(start_dt, str):
            start_dt = _parse_et_datetime(start_dt, field="started_at")
    if isinstance(start_dt, datetime) and isinstance(end_dt, datetime) and start_dt > end_dt:
        raise CleaningTaskError("Start time cannot be after completion time.", status=400)

    duration = None
    times_manual = True
    if isinstance(start_dt, datetime) and isinstance(end_dt, datetime):
        duration = max(0, int((end_dt - start_dt).total_seconds()))

    new_user = int(employee_user_id) if employee_user_id is not None else int(row["user_id"])
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET user_id=%s,
            started_at=%s,
            ended_at=%s,
            duration_seconds=%s,
            completion_source=%s,
            recorded_by_user_id=%s,
            manual_reason=%s,
            manual_remarks=%s,
            times_manual=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            new_user,
            start_dt,
            end_dt,
            duration,
            SOURCE_CORRECTED,
            supervisor,
            reason_clean[:500],
            remarks,
            1 if times_manual else 0,
            int(activity_id),
            oid,
        ),
    )
    after_row = get_activity(cursor, oid, int(activity_id))
    after = _snapshot(after_row)
    cursor.execute(
        f"""
        INSERT INTO {REVISIONS_TABLE}
          (organization_id, activity_id, revised_by_user_id, reason, remarks, before_json, after_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            oid,
            int(activity_id),
            supervisor,
            reason_clean[:500],
            remarks,
            json.dumps(before, default=str),
            json.dumps(after, default=str),
        ),
    )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="completion_corrected",
        actor_user_id=supervisor,
        payload={"reason": reason_clean, "remarks": remarks, "before": before, "after": after},
    )
    catalog = _role_catalog(cursor, oid)
    ser = serialize_activity(after_row or {}, catalog=catalog)
    names = _employee_names(cursor, oid, [new_user, supervisor])
    ser["employee_name"] = names.get(new_user)
    ser["recorded_by_name"] = names.get(supervisor)
    ser["completion_source_label"] = completion_source_label(SOURCE_CORRECTED)
    return ser


def parse_manual_payload(data: Mapping[str, Any], *, require_completed_at: bool = True) -> dict[str, Any]:
    """Normalize API body for manual completion / correction."""
    completed_at = data.get("completed_at")
    if completed_at in (None, ""):
        completed_at = _combine_date_time(
            day=data.get("completion_date") or data.get("completed_date"),
            clock=data.get("completion_time") or data.get("completed_time"),
            field="completed_at",
        )
    elif not isinstance(completed_at, datetime):
        completed_at = _parse_et_datetime(completed_at, field="completed_at")
    if require_completed_at and completed_at is None:
        raise CleaningTaskError("Completion date and time are required.", status=400)
    started_at = data.get("started_at")
    if started_at in (None, ""):
        started_at = _combine_date_time(
            day=data.get("start_date") or data.get("started_date"),
            clock=data.get("start_time") or data.get("started_time"),
            field="started_at",
        )
    elif not isinstance(started_at, datetime):
        started_at = _parse_et_datetime(started_at, field="started_at")
    return {
        "completed_at": completed_at,
        "started_at": started_at,
        "reason": str(data.get("reason") or "").strip(),
        "remarks": (str(data.get("remarks") or "").strip() or None),
        "employee_user_id": int(data["employee_user_id"])
        if data.get("employee_user_id") not in (None, "")
        else None,
        "responsibility_id": int(data["responsibility_id"])
        if data.get("responsibility_id") not in (None, "")
        else None,
        "activity_id": int(data["activity_id"]) if data.get("activity_id") not in (None, "") else None,
        "group_item_codes": [
            str(x).strip()
            for x in (data.get("group_item_codes") or data.get("completed_item_codes") or [])
            if str(x).strip()
        ],
        "shared_item_completions": list(data.get("shared_item_completions") or []),
        "business_date": _parse_et_date(data.get("business_date")),
    }
