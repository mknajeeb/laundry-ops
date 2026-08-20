"""Shared attendance break start/end — closes open role segments at break start.

Authoritative break boundaries come from shift_breaks rows + Take Break / Resume.
Role segments must not overlap break intervals going forward.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.payroll_identity import eastern_now_naive


class BreakOpError(Exception):
    def __init__(self, message: str, *, status: int = 400, payload: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


def start_break_on_session(
    conn,
    session_id: int,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Start a break on an active shift.

    Closes any open shift_job_segment at the same timestamp, then inserts an
    open shift_breaks row. The main shift_sessions row stays active.
    """
    from backend.shift_job_tracking import close_open_job_segment
    from backend.ta_routes import get_open_break

    sid = int(session_id)
    if get_open_break(conn, sid):
        raise BreakOpError("Break already in progress", status=400)

    at = now or eastern_now_naive()
    # End current role so break does not accumulate into role time.
    close_open_job_segment(conn, sid, at, close_source="break_start")

    c = conn.cursor()
    c.execute(
        """
        INSERT INTO shift_breaks (shift_session_id, break_start_at)
        VALUES (%s, %s)
        """,
        (sid, at),
    )
    bid = int(c.lastrowid)
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM shift_breaks WHERE id=%s", (bid,))
    row = c2.fetchone()
    if not row:
        raise BreakOpError("Failed to start break", status=500)
    return row


def end_break_on_session(
    conn,
    session_id: int,
    organization_id: int,
    user_id: int,
    *,
    category_id: Any = None,
    role_id: Any = None,
    now: Optional[datetime] = None,
    require_role_when_tracking: bool = True,
) -> tuple[dict[str, Any], Optional[dict]]:
    """
    End the open break. When category/role tracking is on and
    ``require_role_when_tracking``, category_id + role_id are required and a
    new role segment starts at resume time.

    Returns (break_row, segment_or_none).
    """
    from backend.category_role_tracking_settings import is_category_role_tracking_enabled
    from backend.shift_job_tracking import (
        list_active_selection_tree,
        seed_default_categories_and_roles,
        start_category_role_segment,
    )
    from backend.ta_routes import get_open_break

    sid = int(session_id)
    ob = get_open_break(conn, sid)
    if not ob:
        raise BreakOpError("No active break", status=400)

    oid = int(organization_id)
    tracking_on = is_category_role_tracking_enabled(conn, oid)
    has_assignment = category_id is not None and role_id is not None and str(category_id) and str(
        role_id
    )

    if tracking_on and require_role_when_tracking and not has_assignment:
        c = conn.cursor(dictionary=True)
        seed_default_categories_and_roles(c, oid)
        tree = list_active_selection_tree(c, oid)
        raise BreakOpError(
            "Select a category and role to resume work",
            status=400,
            payload={"needs_category_role": True, "selection_tree": tree},
        )

    at = now or eastern_now_naive()
    c2 = conn.cursor()
    c2.execute(
        "UPDATE shift_breaks SET break_end_at=%s WHERE id=%s",
        (at, int(ob["id"])),
    )

    segment = None
    if tracking_on and has_assignment:
        segment = start_category_role_segment(
            conn,
            sid,
            oid,
            int(user_id),
            int(category_id),
            int(role_id),
            started_at=at,
            change_source="break_resume",
        )

    c3 = conn.cursor(dictionary=True)
    c3.execute("SELECT * FROM shift_breaks WHERE id=%s", (int(ob["id"]),))
    row = c3.fetchone()
    return row or {}, segment


def close_open_break_at(
    conn,
    session_id: int,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Close an open break without starting a new role (e.g. clock-out)."""
    from backend.ta_routes import get_open_break

    ob = get_open_break(conn, int(session_id))
    if not ob:
        return False
    at = now or eastern_now_naive()
    c = conn.cursor()
    c.execute(
        "UPDATE shift_breaks SET break_end_at=%s WHERE id=%s",
        (at, int(ob["id"])),
    )
    return True
