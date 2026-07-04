"""Shift task tracking — records what task an employee performed during each shift."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from backend.payroll_identity import eastern_now_naive
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column

DEFAULT_TASKS = (
    "Rinse WF - Weigh",
    "Rinse WF - Sort",
    "Rinse WF - Wash",
    "Rinse WF - Fold",
    "Rinse HD - Wash",
    "Rinse HD - Fold",
    "DHS",
    "Drop Off",
)

# Legacy alias
DEFAULT_JOB_NAMES = DEFAULT_TASKS

CHECKOUT_TYPES = (
    "manual",
    "force_scheduled",
    "force_admin",
    "auto_max_hours",
    "auto_midnight",
)

_SESSION_COLS = (
    ("scheduled_end_at", "DATETIME NULL"),
    ("force_checkout_at", "DATETIME NULL"),
    ("force_checkout_waived", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("force_checked_out_at", "DATETIME NULL"),
    ("checkout_type", "VARCHAR(32) NULL"),
    ("continuation_allowed", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("continued_after_force_at", "DATETIME NULL"),
    ("current_job_name_id", "INT NULL"),
)


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")[:19])
    except Exception:
        return None


def _combine_date_time(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)


def _add_column_if_missing(cursor, table: str, column: str, ddl: str) -> None:
    if not table_exists(cursor, table):
        return
    if table_has_column(cursor, table, column):
        return
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except Exception as exc:
        if getattr(exc, "args", (None,))[0] != 1060:
            raise
    invalidate_schema_cache()


def ensure_shift_job_tracking_schema(cursor) -> None:
    if not table_exists(cursor, "ta_job_names"):
        cursor.execute(
            """
            CREATE TABLE ta_job_names (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              name VARCHAR(128) NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_tjn_org_name (organization_id, name),
              INDEX idx_tjn_org_active (organization_id, active, sort_order)
            ) ENGINE=InnoDB
            """
        )
    if not table_exists(cursor, "shift_job_segments"):
        cursor.execute(
            """
            CREATE TABLE shift_job_segments (
              id INT AUTO_INCREMENT PRIMARY KEY,
              shift_session_id INT NOT NULL,
              job_name_id INT NOT NULL,
              started_at DATETIME NOT NULL,
              ended_at DATETIME NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_sjs_session (shift_session_id, started_at),
              CONSTRAINT fk_sjs_session FOREIGN KEY (shift_session_id)
                REFERENCES shift_sessions(id) ON DELETE CASCADE,
              CONSTRAINT fk_sjs_job FOREIGN KEY (job_name_id) REFERENCES ta_job_names(id)
            ) ENGINE=InnoDB
            """
        )
    for col, ddl in _SESSION_COLS:
        _add_column_if_missing(cursor, "shift_sessions", col, ddl)
    _add_column_if_missing(
        cursor, "payroll_profiles", "force_checkout_waiver", "TINYINT(1) NOT NULL DEFAULT 0"
    )
    invalidate_schema_cache()


def seed_default_job_names(cursor, organization_id: int) -> None:
    ensure_shift_job_tracking_schema(cursor)
    cursor.execute(
        "SELECT COUNT(*) FROM ta_job_names WHERE organization_id=%s",
        (int(organization_id),),
    )
    row = cursor.fetchone()
    count = int(row[0] if not isinstance(row, dict) else list(row.values())[0])
    if count > 0:
        return
    for idx, name in enumerate(DEFAULT_TASKS):
        cursor.execute(
            """
            INSERT INTO ta_job_names (organization_id, name, sort_order, active)
            VALUES (%s, %s, %s, 1)
            """,
            (int(organization_id), name, idx),
        )


def list_job_names(
    cursor,
    organization_id: int,
    *,
    include_inactive: bool = False,
    include_usage: bool = False,
) -> list[dict]:
    ensure_shift_job_tracking_schema(cursor)
    q = """
        SELECT id, organization_id, name, sort_order, active, created_at, updated_at
        FROM ta_job_names
        WHERE organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if not include_inactive:
        q += " AND active=1"
    q += " ORDER BY sort_order ASC, name ASC"
    cursor.execute(q, params)
    rows = [json_safe(r) for r in cursor.fetchall()]
    if include_usage:
        for row in rows:
            count = task_usage_count(cursor, int(row["id"]))
            row["usage_count"] = count
            row["can_delete"] = count == 0
    return rows


def get_job_name(cursor, organization_id: int, job_name_id: int) -> Optional[dict]:
    ensure_shift_job_tracking_schema(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, name, sort_order, active
        FROM ta_job_names
        WHERE id=%s AND organization_id=%s
        """,
        (int(job_name_id), int(organization_id)),
    )
    row = cursor.fetchone()
    return json_safe(row) if row else None


def create_job_name(cursor, organization_id: int, name: str, *, active: bool = True) -> dict:
    ensure_shift_job_tracking_schema(cursor)
    name = (name or "").strip()
    if not name:
        raise ValueError("Task name is required")
    cursor.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM ta_job_names WHERE organization_id=%s",
        (int(organization_id),),
    )
    row = cursor.fetchone()
    sort_order = int(row[0] if not isinstance(row, dict) else list(row.values())[0])
    cursor.execute(
        """
        INSERT INTO ta_job_names (organization_id, name, sort_order, active)
        VALUES (%s, %s, %s, %s)
        """,
        (int(organization_id), name, sort_order, 1 if active else 0),
    )
    jid = cursor.lastrowid
    return get_job_name(cursor, organization_id, jid) or {"id": jid, "name": name}


def update_job_name(
    cursor,
    organization_id: int,
    job_name_id: int,
    *,
    name: Optional[str] = None,
    active: Optional[bool] = None,
) -> dict:
    ensure_shift_job_tracking_schema(cursor)
    existing = get_job_name(cursor, organization_id, job_name_id)
    if not existing:
        raise ValueError("Task not found")
    fields = []
    vals: list[Any] = []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Job name is required")
        fields.append("name=%s")
        vals.append(name)
    if active is not None:
        fields.append("active=%s")
        vals.append(1 if active else 0)
    if not fields:
        return existing
    vals.extend([int(job_name_id), int(organization_id)])
    cursor.execute(
        f"UPDATE ta_job_names SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
        vals,
    )
    return get_job_name(cursor, organization_id, job_name_id) or existing


def reorder_job_names(cursor, organization_id: int, ordered_ids: list[int]) -> list[dict]:
    ensure_shift_job_tracking_schema(cursor)
    for idx, jid in enumerate(ordered_ids):
        cursor.execute(
            """
            UPDATE ta_job_names SET sort_order=%s
            WHERE id=%s AND organization_id=%s
            """,
            (idx, int(jid), int(organization_id)),
        )
    return list_job_names(cursor, organization_id, include_inactive=True)


def task_usage_count(cursor, task_id: int) -> int:
    if not table_exists(cursor, "shift_job_segments"):
        return 0
    cursor.execute(
        "SELECT COUNT(*) FROM shift_job_segments WHERE job_name_id=%s",
        (int(task_id),),
    )
    row = cursor.fetchone()
    return int(row[0] if not isinstance(row, dict) else list(row.values())[0])


def delete_job_name(cursor, organization_id: int, task_id: int) -> None:
    ensure_shift_job_tracking_schema(cursor)
    existing = get_job_name(cursor, organization_id, task_id)
    if not existing:
        raise ValueError("Task not found")
    if task_usage_count(cursor, task_id) > 0:
        raise ValueError("Task has been used on a shift and cannot be deleted. Deactivate it instead.")
    cursor.execute(
        "DELETE FROM ta_job_names WHERE id=%s AND organization_id=%s",
        (int(task_id), int(organization_id)),
    )


def user_force_checkout_waiver(conn, user_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    if not table_has_column(c, "payroll_profiles", "force_checkout_waiver"):
        return False
    c.execute(
        "SELECT force_checkout_waiver FROM payroll_profiles WHERE user_id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone()
    return bool(row and int(row.get("force_checkout_waiver") or 0))


def set_user_force_checkout_waiver(conn, user_id: int, waived: bool) -> bool:
    c = conn.cursor()
    ensure_shift_job_tracking_schema(c)
    c.execute(
        "UPDATE payroll_profiles SET force_checkout_waiver=%s WHERE user_id=%s",
        (1 if waived else 0, int(user_id)),
    )
    return bool(c.rowcount)


def resolve_scheduled_end_at(conn, organization_id: int, user_id: int, clock_in_at: datetime) -> Optional[datetime]:
    """Best-effort scheduled end from payroll_schedule_entries for clock-in date."""
    if not table_exists(conn.cursor(), "payroll_schedule_entries"):
        return None
    c = conn.cursor(dictionary=True)
    work_date = clock_in_at.date()
    clock_t = clock_in_at.time().replace(microsecond=0)
    c.execute(
        """
        SELECT pse.end_time, pse.start_time, pse.work_date
        FROM payroll_schedule_entries pse
        JOIN payroll_worker_profiles pwp ON pwp.id = pse.worker_profile_id
        WHERE pwp.user_id=%s AND pse.organization_id=%s
          AND pse.work_date=%s
          AND pse.status NOT IN ('cancelled', 'canceled')
        ORDER BY pse.start_time ASC
        """,
        (int(user_id), int(organization_id), work_date),
    )
    rows = c.fetchall()
    if not rows:
        return None

    def _as_time(val):
        if isinstance(val, time):
            return val.replace(microsecond=0)
        if isinstance(val, timedelta):
            sec = int(val.total_seconds()) % 86400
            return (datetime.min + timedelta(seconds=sec)).time()
        s = str(val)
        if len(s) >= 5:
            parts = s.split(":")
            return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        return None

    best_end: Optional[time] = None
    for row in rows:
        st = _as_time(row.get("start_time"))
        et = _as_time(row.get("end_time"))
        if et is None:
            continue
        if st is not None and st <= clock_t <= et:
            best_end = et
            break
        if best_end is None:
            best_end = et
        elif et > best_end:
            best_end = et
    if best_end is None:
        return None
    return _combine_date_time(work_date, best_end)


def effective_force_checkout_at(sess: dict, employee_waiver: bool) -> Optional[datetime]:
    if employee_waiver:
        return None
    if bool(int(sess.get("force_checkout_waived") or 0)):
        return None
    fc = _parse_dt(sess.get("force_checkout_at"))
    if fc:
        return fc
    return _parse_dt(sess.get("scheduled_end_at"))


def init_session_job_tracking(
    conn,
    session_id: int,
    organization_id: int,
    user_id: int,
    clock_in_at: datetime,
    job_name_id: Optional[int] = None,
) -> None:
    c = conn.cursor()
    ensure_shift_job_tracking_schema(c)
    seed_default_job_names(c, organization_id)

    scheduled_end = resolve_scheduled_end_at(conn, organization_id, user_id, clock_in_at)
    force_checkout = scheduled_end
    c.execute(
        """
        UPDATE shift_sessions
        SET scheduled_end_at=%s, force_checkout_at=%s
        WHERE id=%s
        """,
        (scheduled_end, force_checkout, int(session_id)),
    )
    if job_name_id:
        start_job_segment(conn, int(session_id), int(organization_id), int(job_name_id), clock_in_at)


def get_open_job_segment(conn, session_id: int) -> Optional[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return None
    c.execute(
        """
        SELECT s.*, j.name AS job_name
        FROM shift_job_segments s
        JOIN ta_job_names j ON j.id = s.job_name_id
        WHERE s.shift_session_id=%s AND s.ended_at IS NULL
        ORDER BY s.id DESC LIMIT 1
        """,
        (int(session_id),),
    )
    row = c.fetchone()
    return json_safe(row) if row else None


def close_open_job_segment(conn, session_id: int, ended_at: Optional[datetime] = None) -> None:
    c = conn.cursor()
    if not table_exists(c, "shift_job_segments"):
        return
    ended = ended_at or eastern_now_naive()
    c.execute(
        """
        UPDATE shift_job_segments SET ended_at=%s
        WHERE shift_session_id=%s AND ended_at IS NULL
        """,
        (ended, int(session_id)),
    )
    c.execute(
        "UPDATE shift_sessions SET current_job_name_id=NULL WHERE id=%s",
        (int(session_id),),
    )


def start_job_segment(
    conn,
    session_id: int,
    organization_id: int,
    job_name_id: int,
    started_at: Optional[datetime] = None,
) -> dict:
    c = conn.cursor(dictionary=True)
    ensure_shift_job_tracking_schema(c)
    job = get_job_name(c, organization_id, job_name_id)
    if not job or not int(job.get("active") or 0):
        raise ValueError("Invalid or inactive task")
    started = started_at or eastern_now_naive()
    close_open_job_segment(conn, session_id, started)
    ins = conn.cursor()
    ins.execute(
        """
        INSERT INTO shift_job_segments (shift_session_id, job_name_id, started_at)
        VALUES (%s, %s, %s)
        """,
        (int(session_id), int(job_name_id), started),
    )
    seg_id = ins.lastrowid
    ins.execute(
        "UPDATE shift_sessions SET current_job_name_id=%s WHERE id=%s",
        (int(job_name_id), int(session_id)),
    )
    c.execute(
        """
        SELECT s.*, j.name AS job_name
        FROM shift_job_segments s
        JOIN ta_job_names j ON j.id = s.job_name_id
        WHERE s.id=%s
        """,
        (seg_id,),
    )
    row = c.fetchone()
    return json_safe(row) if row else {"id": seg_id, "job_name_id": job_name_id}


def switch_job_role(conn, session_id: int, organization_id: int, job_name_id: int) -> dict:
    return start_job_segment(conn, session_id, organization_id, job_name_id)


def list_session_segments(conn, session_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return []
    c.execute(
        """
        SELECT s.*, j.name AS job_name
        FROM shift_job_segments s
        JOIN ta_job_names j ON j.id = s.job_name_id
        WHERE s.shift_session_id=%s
        ORDER BY s.started_at ASC, s.id ASC
        """,
        (int(session_id),),
    )
    rows = c.fetchall()
    out = []
    now = eastern_now_naive()
    for row in rows:
        r = json_safe(row)
        start = _parse_dt(r.get("started_at"))
        end = _parse_dt(r.get("ended_at"))
        if start:
            end_eff = end or now
            r["duration_seconds"] = max(0, int((end_eff - start).total_seconds()))
        else:
            r["duration_seconds"] = 0
        out.append(r)
    return out


def _sum_break_seconds(conn, shift_id: int) -> int:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_breaks"):
        return 0
    c.execute(
        "SELECT break_start_at, break_end_at FROM shift_breaks WHERE shift_session_id=%s",
        (int(shift_id),),
    )
    total = 0
    for row in c.fetchall():
        start = _parse_dt(row.get("break_start_at"))
        end = _parse_dt(row.get("break_end_at"))
        if start and end:
            total += int((end - start).total_seconds())
    return total


def _compute_net_seconds(conn, sess: dict, clock_out_at: datetime) -> tuple[int, int]:
    br = _sum_break_seconds(conn, int(sess["id"]))
    clock_in = _parse_dt(sess.get("clock_in_at"))
    if not clock_in:
        return br, 0
    elapsed = int((clock_out_at - clock_in).total_seconds())
    return br, max(0, elapsed - br)


def perform_force_checkout(
    conn,
    sess: dict,
    user_id: int,
    checkout_type: str = "force_scheduled",
    *,
    clock_out_at: Optional[datetime] = None,
    message: Optional[str] = None,
) -> dict:
    if str(sess.get("status")) != "active":
        raise ValueError("Session is not active")
    sid = int(sess["id"])
    now = clock_out_at or eastern_now_naive()
    br, net = _compute_net_seconds(conn, sess, now)
    close_open_job_segment(conn, sid, now)

    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, status='auto_closed', total_break_seconds=%s,
            net_work_seconds=%s, force_checked_out_at=%s, checkout_type=%s,
            continuation_allowed=0
        WHERE id=%s
        """,
        (now, br, net, now, checkout_type, sid),
    )
    msg = message or f"Force check-out ({checkout_type}) at scheduled end."
    c.execute(
        """
        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message, severity)
        VALUES (%s,%s,'scheduled_force_checkout',%s,'warning')
        """,
        (sid, int(user_id), msg),
    )
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
    return json_safe(c2.fetchone() or {})


def maybe_force_checkout_scheduled_end(
    conn,
    sess: dict,
    user_id: int,
    organization_id: int,
) -> Optional[dict]:
    """Force check-out when effective deadline reached. Called from session polling."""
    if not sess or str(sess.get("status")) != "active":
        return None
    ensure_shift_job_tracking_schema(conn.cursor())
    employee_waiver = user_force_checkout_waiver(conn, user_id)
    deadline = effective_force_checkout_at(sess, employee_waiver)
    if not deadline:
        return None
    now = eastern_now_naive()
    if now < deadline:
        return None
    return perform_force_checkout(
        conn,
        sess,
        user_id,
        checkout_type="force_scheduled",
        clock_out_at=deadline,
        message=f"Scheduled shift end at {deadline.strftime('%I:%M %p')} — automatic check-out.",
    )


def enrich_session_job_tracking(conn, sess: dict, user_id: int) -> dict:
    """Task timing payload for active/completed shift sessions."""
    if not sess:
        return {}
    sid = int(sess["id"])
    employee_waiver = user_force_checkout_waiver(conn, user_id)
    deadline = effective_force_checkout_at(sess, employee_waiver)
    open_seg = get_open_job_segment(conn, sid)
    segments = list_session_segments(conn, sid)
    task_segments = [
        {
            **s,
            "task_id": s.get("job_name_id"),
            "task_name": s.get("job_name"),
        }
        for s in segments
    ]
    force_checked = bool(_parse_dt(sess.get("force_checked_out_at")))
    can_continue = bool(int(sess.get("continuation_allowed") or 0))
    current_task_id = None
    current_task_name = None
    if open_seg:
        current_task_id = open_seg.get("job_name_id")
        current_task_name = open_seg.get("job_name")
    elif sess.get("current_job_name_id"):
        c = conn.cursor(dictionary=True)
        c.execute("SELECT name FROM ta_job_names WHERE id=%s", (int(sess["current_job_name_id"]),))
        jn = c.fetchone()
        current_task_id = sess.get("current_job_name_id")
        current_task_name = jn.get("name") if jn else None
    out = {
        "scheduled_end_at": sess.get("scheduled_end_at"),
        "force_checkout_at": sess.get("force_checkout_at"),
        "effective_force_checkout_at": deadline.isoformat() if deadline else None,
        "force_checkout_waived": bool(int(sess.get("force_checkout_waived") or 0)),
        "employee_force_checkout_waiver": employee_waiver,
        "force_checked_out_at": sess.get("force_checked_out_at"),
        "checkout_type": sess.get("checkout_type"),
        "continuation_allowed": can_continue,
        "continued_after_force_at": sess.get("continued_after_force_at"),
        "current_task_id": current_task_id,
        "current_task_name": current_task_name,
        "current_task_segment": open_seg,
        "task_segments": task_segments,
        "force_checkout_blocked": deadline is not None and eastern_now_naive() >= deadline,
        "was_force_checked_out": force_checked,
        "can_continue_after_force": force_checked and can_continue and str(sess.get("status")) != "active",
        # Legacy aliases
        "current_job_name_id": current_task_id,
        "current_job_name": current_task_name,
        "current_job_segment": open_seg,
        "job_segments": segments,
    }
    return json_safe(out)


def admin_waive_session_force_checkout(conn, session_id: int, waived: bool) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    old = bool(int(sess.get("force_checkout_waived") or 0))
    uc = conn.cursor()
    uc.execute(
        "UPDATE shift_sessions SET force_checkout_waived=%s WHERE id=%s",
        (1 if waived else 0, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    new_sess = c.fetchone()
    return {
        "session": json_safe(new_sess),
        "old": {"force_checkout_waived": old},
        "new": {"force_checkout_waived": waived},
    }


def admin_override_force_checkout_time(conn, session_id: int, force_checkout_at: datetime) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    old = _parse_dt(sess.get("force_checkout_at"))
    uc = conn.cursor()
    uc.execute(
        "UPDATE shift_sessions SET force_checkout_at=%s, manual_override=1 WHERE id=%s",
        (force_checkout_at, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    return {
        "session": json_safe(c.fetchone()),
        "old": {"force_checkout_at": old.isoformat() if old else None},
        "new": {"force_checkout_at": force_checkout_at.isoformat()},
    }


def admin_allow_continuation(conn, session_id: int) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    if not _parse_dt(sess.get("force_checked_out_at")):
        raise ValueError("Session was not force checked out")
    now = eastern_now_naive()
    uc = conn.cursor()
    uc.execute(
        """
        UPDATE shift_sessions
        SET status='active', clock_out_at=NULL, net_work_seconds=NULL,
            continuation_allowed=1, continued_after_force_at=%s,
            checkout_type=NULL
        WHERE id=%s
        """,
        (now, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    return {"session": json_safe(c.fetchone())}


def get_last_check_in_task_id(conn, user_id: int) -> Optional[int]:
    """First task segment from the employee's most recent shift (their last check-in task)."""
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return None
    c.execute(
        """
        SELECT sjs.job_name_id
        FROM shift_sessions ss
        JOIN shift_job_segments sjs ON sjs.shift_session_id = ss.id
        WHERE ss.user_id=%s
        ORDER BY ss.clock_in_at DESC, sjs.started_at ASC, sjs.id ASC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone()
    if not row or row.get("job_name_id") is None:
        return None
    return int(row["job_name_id"])


def build_shift_timeline(rec: dict, segments: list[dict]) -> list[dict]:
    """Chronological check-in, task segments, and check-out for one shift."""
    timeline: list[dict] = []
    clock_in = _parse_dt(rec.get("clock_in_at"))
    clock_out = _parse_dt(rec.get("clock_out_at"))
    force_checked = bool(_parse_dt(rec.get("force_checked_out_at")))

    if clock_in:
        timeline.append(
            {
                "type": "check_in",
                "at": clock_in.isoformat(),
                "label": "Check In",
            }
        )

    for seg in segments:
        timeline.append(
            {
                "type": "task",
                "task_id": seg.get("job_name_id"),
                "task_name": seg.get("job_name"),
                "started_at": seg.get("started_at"),
                "ended_at": seg.get("ended_at"),
            }
        )

    if clock_out:
        if force_checked or rec.get("checkout_type") == "force_scheduled":
            timeline.append(
                {
                    "type": "force_check_out",
                    "at": clock_out.isoformat(),
                    "label": "Force Checked Out",
                }
            )
        else:
            timeline.append(
                {
                    "type": "check_out",
                    "at": clock_out.isoformat(),
                    "label": "Checked Out",
                }
            )

    return timeline


def on_manual_clock_out(conn, session_id: int) -> None:
    close_open_job_segment(conn, int(session_id))
    c = conn.cursor()
    if table_has_column(c, "shift_sessions", "checkout_type"):
        c.execute(
            """
            UPDATE shift_sessions SET checkout_type='manual'
            WHERE id=%s AND (checkout_type IS NULL OR checkout_type='')
            """,
            (int(session_id),),
        )


def job_tracking_report(
    conn,
    organization_id: int,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user_id: Optional[int] = None,
    shift_session_id: Optional[int] = None,
    job_name_id: Optional[int] = None,
    task_id: Optional[int] = None,
) -> list[dict]:
    """Simple task time report for performance dashboard prep."""
    filter_task_id = task_id or job_name_id
    ensure_shift_job_tracking_schema(conn.cursor())
    c = conn.cursor(dictionary=True)
    q = """
        SELECT s.*, pp.first_name, pp.last_name, pp.email
        FROM shift_sessions s
        JOIN payroll_profiles pp ON pp.user_id = s.user_id
        WHERE s.organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if shift_session_id:
        q += " AND s.id=%s"
        params.append(int(shift_session_id))
    if user_id:
        q += " AND s.user_id=%s"
        params.append(int(user_id))
    if from_date:
        q += " AND DATE(s.clock_in_at) >= %s"
        params.append(from_date)
    if to_date:
        q += " AND DATE(s.clock_in_at) <= %s"
        params.append(to_date)
    q += " ORDER BY s.clock_in_at DESC, s.id DESC LIMIT 500"
    c.execute(q, params)
    rows = c.fetchall()
    out = []
    for row in rows:
        rec = json_safe(row)
        sid = int(rec["id"])
        segments = list_session_segments(conn, sid)
        if filter_task_id:
            segments = [s for s in segments if int(s.get("job_name_id") or 0) == int(filter_task_id)]
            if not segments:
                continue
        summary = _role_time_summary(segments)
        task_breakdown = [
            {
                "task_id": t["job_name_id"],
                "task_name": t["job_name"],
                "duration_seconds": t["total_seconds"],
            }
            for t in summary
        ]
        clock_in = _parse_dt(rec.get("clock_in_at"))
        clock_out = _parse_dt(rec.get("clock_out_at"))
        total_seconds = int(rec.get("net_work_seconds") or 0)
        if not total_seconds and clock_in and clock_out:
            total_seconds = max(0, int((clock_out - clock_in).total_seconds()))
        rec["shift_date"] = str(clock_in.date()) if clock_in else str(rec.get("clock_in_at") or "")[:10]
        rec["total_shift_seconds"] = total_seconds
        rec["task_breakdown"] = task_breakdown
        rec["shift_timeline"] = build_shift_timeline(rec, segments)
        rec["was_force_checked_out"] = bool(_parse_dt(rec.get("force_checked_out_at")))
        out.append(rec)
    return out


def _role_time_summary(segments: list[dict]) -> list[dict]:
    totals: dict[int, dict] = {}
    for seg in segments:
        jid = int(seg.get("job_name_id") or 0)
        if jid not in totals:
            totals[jid] = {
                "job_name_id": jid,
                "job_name": seg.get("job_name"),
                "total_seconds": 0,
            }
        totals[jid]["total_seconds"] += int(seg.get("duration_seconds") or 0)
    return sorted(totals.values(), key=lambda x: x.get("job_name") or "")
