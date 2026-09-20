"""Payroll Time Records — break visibility and editing.

Payable hours stay:

    net = max(0, clock_out - clock_in - sum(completed breaks))

Role segments are not the payable source of truth. Segment edits that overlap a
completed break require an explicit resolution. Open breaks are never deducted
until closed or removed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.ta_helpers import json_safe, table_exists


class BreakConflictError(ValueError):
    """Segment times overlap a completed break; manager must choose a resolution."""

    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = payload


class OpenBreakApprovalError(ValueError):
    """Completed session still has an open break — block payroll approval."""

    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload or {}


def _parse_dt(value: Any) -> Optional[datetime]:
    from backend.payroll_operations import _parse_clock_dt

    if value is None or (isinstance(value, str) and not str(value).strip()):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return _parse_clock_dt(value)


def _as_naive(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return _parse_dt(value)


def _overlap_seconds(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds())


def load_session_breaks(conn, session_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_breaks"):
        return []
    c.execute(
        """
        SELECT id, shift_session_id, break_start_at, break_end_at
        FROM shift_breaks
        WHERE shift_session_id=%s
        ORDER BY break_start_at ASC, id ASC
        """,
        (int(session_id),),
    )
    return list(c.fetchall() or [])


def break_row_status(row: dict) -> str:
    if row.get("break_start_at") and row.get("break_end_at"):
        return "completed"
    if row.get("break_start_at") and not row.get("break_end_at"):
        return "open"
    return "invalid"


def completed_break_seconds(breaks: list[dict]) -> int:
    total = 0
    for row in breaks or []:
        start = _as_naive(row.get("break_start_at"))
        end = _as_naive(row.get("break_end_at"))
        if not start or not end or end <= start:
            continue
        total += int((end - start).total_seconds())
    return total


def serialize_break(row: dict) -> dict:
    start = _as_naive(row.get("break_start_at"))
    end = _as_naive(row.get("break_end_at"))
    status = break_row_status(row)
    duration = None
    if start and end and end > start:
        duration = int((end - start).total_seconds())
    return json_safe(
        {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "break_start_at": start,
            "break_end_at": end,
            "duration_seconds": duration,
            "status": status,
            "deducted": status == "completed",
        }
    )


def segment_break_conflicts(
    segments: list[dict], breaks: list[dict], *, tolerance_sec: int = 1
) -> list[dict]:
    conflicts = []
    for seg in segments or []:
        s_start = _as_naive(seg.get("started_at"))
        s_end = _as_naive(seg.get("ended_at"))
        if not s_start or not s_end:
            continue
        for br in breaks or []:
            if break_row_status(br) != "completed":
                continue
            b_start = _as_naive(br.get("break_start_at"))
            b_end = _as_naive(br.get("break_end_at"))
            if not b_start or not b_end:
                continue
            overlap = _overlap_seconds(s_start, s_end, b_start, b_end)
            if overlap > tolerance_sec:
                conflicts.append(
                    {
                        "segment_id": int(seg["id"]) if seg.get("id") is not None else None,
                        "break_id": int(br["id"]),
                        "overlap_seconds": overlap,
                        "segment_started_at": s_start,
                        "segment_ended_at": s_end,
                        "break_start_at": b_start,
                        "break_end_at": b_end,
                        "segment_change_source": seg.get("change_source"),
                    }
                )
    return conflicts


def find_break_resume_sync_candidate(
    segment: dict, breaks: list[dict], *, previous_start: Any, tolerance_sec: int = 2
) -> Optional[dict]:
    """If this is a break_resume whose prior start matched a break end, that break can sync."""
    if str(segment.get("change_source") or "") != "break_resume":
        return None
    prev = _as_naive(previous_start)
    if not prev:
        return None
    for br in breaks or []:
        if break_row_status(br) != "completed":
            continue
        b_end = _as_naive(br.get("break_end_at"))
        if not b_end:
            continue
        if abs(int((b_end - prev).total_seconds())) <= tolerance_sec:
            return br
    return None


def attach_breaks_to_time_records(conn, items: list[dict]) -> None:
    if not items:
        return
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_breaks"):
        for it in items:
            it["breaks"] = []
            it["has_open_break"] = False
            it["segment_break_conflicts"] = []
            it["elapsed_seconds"] = None
            it["payable_composition"] = None
        return

    ids = [int(it["id"]) for it in items]
    ph = ",".join(["%s"] * len(ids))
    c.execute(
        f"""
        SELECT id, shift_session_id, break_start_at, break_end_at
        FROM shift_breaks
        WHERE shift_session_id IN ({ph})
        ORDER BY shift_session_id ASC, break_start_at ASC, id ASC
        """,
        tuple(ids),
    )
    by_session: dict[int, list] = {}
    for row in c.fetchall() or []:
        by_session.setdefault(int(row["shift_session_id"]), []).append(row)

    for it in items:
        sid = int(it["id"])
        raw_breaks = by_session.get(sid, [])
        breaks = [serialize_break(b) for b in raw_breaks]
        it["breaks"] = breaks
        it["has_open_break"] = any(b.get("status") == "open" for b in breaks)
        segs = it.get("role_segments") or []
        it["segment_break_conflicts"] = segment_break_conflicts(segs, raw_breaks)
        ci = _as_naive(it.get("clock_in_at"))
        co = _as_naive(it.get("clock_out_at"))
        elapsed = int((co - ci).total_seconds()) if ci and co and co > ci else None
        break_sec = int(it.get("break_seconds") or completed_break_seconds(raw_breaks))
        it["elapsed_seconds"] = elapsed
        if elapsed is not None and (break_sec > 0 or it["has_open_break"] or it["segment_break_conflicts"]):
            it["payable_composition"] = {
                "payable_seconds": max(0, elapsed - break_sec),
                "elapsed_seconds": elapsed,
                "break_seconds": break_sec,
                "payable_hours": round(max(0, elapsed - break_sec) / 3600.0, 2),
                "elapsed_hours": round(elapsed / 3600.0, 2),
                "break_hours": round(break_sec / 3600.0, 2),
            }
        else:
            it["payable_composition"] = None


def session_has_open_break(conn, session_id: int) -> bool:
    for row in load_session_breaks(conn, session_id):
        if break_row_status(row) == "open":
            return True
    return False


def assert_no_open_break_for_approval(conn, session_id: int) -> None:
    opens = [b for b in load_session_breaks(conn, session_id) if break_row_status(b) == "open"]
    if not opens:
        return
    raise OpenBreakApprovalError(
        "Resolve the open break before approving this time record for payroll",
        {
            "error": "open_break_blocks_approval",
            "session_id": int(session_id),
            "open_breaks": [serialize_break(b) for b in opens],
            "message": (
                "This completed shift still has an open break. "
                "Open breaks are not deducted from payable hours until you close or remove them."
            ),
        },
    )


def recompute_session_work_seconds(
    conn,
    session_id: int,
    *,
    clear_approval_if_hours_change: bool = True,
) -> dict:
    """Rewrite total_break_seconds and net_work_seconds from the break ledger + clocks."""
    from backend.payroll_operations import ensure_payroll_hours_approved_column
    from backend.ta_helpers import table_has_column

    sid = int(session_id)
    c = conn.cursor(dictionary=True)
    ensure_payroll_hours_approved_column(c)
    c.execute(
        """
        SELECT id, clock_in_at, clock_out_at, status, net_work_seconds,
               total_break_seconds, payroll_hours_approved
        FROM shift_sessions
        WHERE id=%s
        """,
        (sid,),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Time record not found")

    breaks = load_session_breaks(conn, sid)
    br = completed_break_seconds(breaks)
    ci = _as_naive(row.get("clock_in_at"))
    co = _as_naive(row.get("clock_out_at"))
    prior_net = row.get("net_work_seconds")
    prior_approved = bool(row.get("payroll_hours_approved"))

    sets = ["total_break_seconds=%s"]
    params: list[Any] = [br]
    net = None
    if co is None or ci is None:
        sets.append("net_work_seconds=NULL")
    else:
        elapsed = int((co - ci).total_seconds())
        net = max(0, elapsed - br)
        sets.append("net_work_seconds=%s")
        params.append(net)
        if str(row.get("status") or "") in ("active",):
            pass
        elif co is not None:
            sets.append("status=%s")
            params.append("completed")

    hours_changed = prior_net is None or net is None or int(prior_net) != int(net or -1)
    approval_cleared = False
    if clear_approval_if_hours_change and prior_approved and hours_changed:
        sets.append("payroll_hours_approved=0")
        approval_cleared = True
    if table_has_column(c, "shift_sessions", "manual_override"):
        sets.append("manual_override=1")

    params.append(sid)
    upd = conn.cursor()
    upd.execute(
        f"UPDATE shift_sessions SET {', '.join(sets)} WHERE id=%s",
        tuple(params),
    )
    return {
        "id": sid,
        "total_break_seconds": br,
        "net_work_seconds": net,
        "approved_hours": round(net / 3600.0, 2) if net is not None else None,
        "hours_changed": hours_changed,
        "approval_cleared": approval_cleared,
        "has_open_break": any(break_row_status(b) == "open" for b in breaks),
    }


def _load_session_clocks(conn, organization_id: int, session_id: int) -> dict:
    from backend.payroll_operations import _session_in_org

    if not _session_in_org(conn, organization_id, session_id):
        raise ValueError("Time record not found")
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, user_id, clock_in_at, clock_out_at, status,
               net_work_seconds, total_break_seconds, payroll_hours_approved
        FROM shift_sessions
        WHERE id=%s
        """,
        (int(session_id),),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Time record not found")
    return row


def _validate_completed_break_window(
    *,
    start: datetime,
    end: datetime,
    clock_in: Optional[datetime],
    clock_out: Optional[datetime],
    other_breaks: list[dict],
    ignore_break_id: Optional[int] = None,
) -> None:
    if end <= start:
        raise ValueError("Break end must be after break start")
    if clock_in and start < clock_in:
        raise ValueError("Break cannot start before check-in")
    if clock_out and end > clock_out:
        raise ValueError("Break cannot end after check-out")
    if clock_in and end < clock_in:
        raise ValueError("Break cannot end before check-in")
    if clock_out and start > clock_out:
        raise ValueError("Break cannot start after check-out")
    for other in other_breaks:
        if ignore_break_id is not None and int(other["id"]) == int(ignore_break_id):
            continue
        if break_row_status(other) != "completed":
            continue
        o_start = _as_naive(other.get("break_start_at"))
        o_end = _as_naive(other.get("break_end_at"))
        if not o_start or not o_end:
            continue
        if _overlap_seconds(start, end, o_start, o_end) > 0:
            raise ValueError("Break overlaps another completed break on this shift")


def _session_response_after_break_change(conn, organization_id: int, session_id: int, recomputed: dict) -> dict:
    from backend.payroll_operations import _session_summary_for_segment_response

    row = _load_session_clocks(conn, organization_id, session_id)
    row["net_work_seconds"] = recomputed.get("net_work_seconds")
    row["total_break_seconds"] = recomputed.get("total_break_seconds")
    breaks = [serialize_break(b) for b in load_session_breaks(conn, session_id)]
    summary = _session_summary_for_segment_response(row)
    summary["total_break_seconds"] = recomputed.get("total_break_seconds")
    summary["approval_cleared"] = recomputed.get("approval_cleared")
    summary["has_open_break"] = recomputed.get("has_open_break")
    summary["breaks"] = breaks
    return json_safe(summary)


def update_session_break(
    conn,
    organization_id: int,
    session_id: int,
    break_id: int,
    *,
    break_start_at: Any = None,
    break_end_at: Any = None,
    end_provided: bool = False,
) -> dict:
    session = _load_session_clocks(conn, organization_id, session_id)
    breaks = load_session_breaks(conn, session_id)
    target = next((b for b in breaks if int(b["id"]) == int(break_id)), None)
    if not target:
        raise ValueError("Break not found")

    new_start = _parse_dt(break_start_at) if break_start_at is not None else _as_naive(target.get("break_start_at"))
    if end_provided:
        if break_end_at is None or (isinstance(break_end_at, str) and not str(break_end_at).strip()):
            raise ValueError("Closing or editing a break requires an end time; use delete to remove it")
        new_end = _parse_dt(break_end_at)
    else:
        new_end = _as_naive(target.get("break_end_at"))
    if not new_start:
        raise ValueError("Break start is required")
    if not new_end:
        raise ValueError("Break end is required for a completed break edit")

    _validate_completed_break_window(
        start=new_start,
        end=new_end,
        clock_in=_as_naive(session.get("clock_in_at")),
        clock_out=_as_naive(session.get("clock_out_at")),
        other_breaks=breaks,
        ignore_break_id=int(break_id),
    )
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_breaks
        SET break_start_at=%s, break_end_at=%s
        WHERE id=%s AND shift_session_id=%s
        """,
        (new_start, new_end, int(break_id), int(session_id)),
    )
    recomputed = recompute_session_work_seconds(conn, session_id)
    return {
        "break": serialize_break(
            {
                "id": int(break_id),
                "break_start_at": new_start,
                "break_end_at": new_end,
            }
        ),
        "session": _session_response_after_break_change(
            conn, organization_id, session_id, recomputed
        ),
    }


def create_session_break(
    conn,
    organization_id: int,
    session_id: int,
    *,
    break_start_at: Any,
    break_end_at: Any,
) -> dict:
    session = _load_session_clocks(conn, organization_id, session_id)
    if not session.get("clock_out_at"):
        raise ValueError("Add a completed break only on a clocked-out attendance day")
    start = _parse_dt(break_start_at)
    end = _parse_dt(break_end_at)
    if not start or not end:
        raise ValueError("Break start and end are required")
    breaks = load_session_breaks(conn, session_id)
    _validate_completed_break_window(
        start=start,
        end=end,
        clock_in=_as_naive(session.get("clock_in_at")),
        clock_out=_as_naive(session.get("clock_out_at")),
        other_breaks=breaks,
    )
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO shift_breaks (shift_session_id, break_start_at, break_end_at)
        VALUES (%s, %s, %s)
        """,
        (int(session_id), start, end),
    )
    break_id = int(c.lastrowid)
    recomputed = recompute_session_work_seconds(conn, session_id)
    return {
        "break": serialize_break(
            {"id": break_id, "break_start_at": start, "break_end_at": end}
        ),
        "session": _session_response_after_break_change(
            conn, organization_id, session_id, recomputed
        ),
    }


def delete_session_break(
    conn, organization_id: int, session_id: int, break_id: int
) -> dict:
    _load_session_clocks(conn, organization_id, session_id)
    breaks = load_session_breaks(conn, session_id)
    if not any(int(b["id"]) == int(break_id) for b in breaks):
        raise ValueError("Break not found")
    c = conn.cursor()
    c.execute(
        "DELETE FROM shift_breaks WHERE id=%s AND shift_session_id=%s",
        (int(break_id), int(session_id)),
    )
    recomputed = recompute_session_work_seconds(conn, session_id)
    return {
        "deleted_break_id": int(break_id),
        "session": _session_response_after_break_change(
            conn, organization_id, session_id, recomputed
        ),
    }


def close_open_session_break(
    conn,
    organization_id: int,
    session_id: int,
    break_id: int,
    *,
    break_end_at: Any,
) -> dict:
    """Explicitly close an open break. Manager must supply the end time — no guessing."""
    session = _load_session_clocks(conn, organization_id, session_id)
    breaks = load_session_breaks(conn, session_id)
    target = next((b for b in breaks if int(b["id"]) == int(break_id)), None)
    if not target:
        raise ValueError("Break not found")
    if break_row_status(target) != "open":
        raise ValueError("Break is not open")
    end = _parse_dt(break_end_at)
    if not end:
        raise ValueError("Break end time is required to close an open break")
    start = _as_naive(target.get("break_start_at"))
    if not start:
        raise ValueError("Open break is missing a start time")
    _validate_completed_break_window(
        start=start,
        end=end,
        clock_in=_as_naive(session.get("clock_in_at")),
        clock_out=_as_naive(session.get("clock_out_at")),
        other_breaks=breaks,
        ignore_break_id=int(break_id),
    )
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_breaks SET break_end_at=%s
        WHERE id=%s AND shift_session_id=%s AND break_end_at IS NULL
        """,
        (end, int(break_id), int(session_id)),
    )
    recomputed = recompute_session_work_seconds(conn, session_id)
    return {
        "break": serialize_break(
            {"id": int(break_id), "break_start_at": start, "break_end_at": end}
        ),
        "session": _session_response_after_break_change(
            conn, organization_id, session_id, recomputed
        ),
    }


def apply_break_conflict_resolution(
    conn,
    session_id: int,
    *,
    resolution: str,
    break_id: int,
    segment_started_at: Any,
) -> None:
    """Apply an explicit manager choice before saving an overlapping segment."""
    key = str(resolution or "").strip()
    breaks = load_session_breaks(conn, session_id)
    target = next((b for b in breaks if int(b["id"]) == int(break_id)), None)
    if not target:
        raise ValueError("Conflicting break not found")
    if key == "delete_break":
        c = conn.cursor()
        c.execute(
            "DELETE FROM shift_breaks WHERE id=%s AND shift_session_id=%s",
            (int(break_id), int(session_id)),
        )
        return
    if key in ("sync_break_end", "trim_break_to_segment_start", "shorten_break"):
        new_end = _as_naive(segment_started_at)
        if not new_end:
            raise ValueError("Segment start is required to sync the break end")
        start = _as_naive(target.get("break_start_at"))
        if not start:
            raise ValueError("Break is missing a start time")
        if new_end <= start:
            # Resume moved to/before break start → delete the break instead of an invalid window.
            c = conn.cursor()
            c.execute(
                "DELETE FROM shift_breaks WHERE id=%s AND shift_session_id=%s",
                (int(break_id), int(session_id)),
            )
            return
        c = conn.cursor()
        c.execute(
            """
            UPDATE shift_breaks SET break_end_at=%s
            WHERE id=%s AND shift_session_id=%s
            """,
            (new_end, int(break_id), int(session_id)),
        )
        return
    if key in ("", "abort", "keep_break"):
        raise ValueError("Break conflict was not resolved")
    raise ValueError(f"Unknown break conflict resolution: {resolution}")


def raise_segment_break_conflict(
    *,
    conflicts: list[dict],
    sync_candidate: Optional[dict],
    proposed_start: Any,
    proposed_end: Any,
) -> None:
    sync_id = int(sync_candidate["id"]) if sync_candidate else None
    payload = {
        "error": "segment_break_conflict",
        "message": (
            "This role segment overlaps an unpaid break. "
            "Payable hours still subtract that break until you resolve the conflict."
        ),
        "conflicts": [
            {
                **c,
                "break_start_at": c.get("break_start_at"),
                "break_end_at": c.get("break_end_at"),
                "segment_started_at": c.get("segment_started_at"),
                "segment_ended_at": c.get("segment_ended_at"),
            }
            for c in conflicts
        ],
        "proposed_started_at": _as_naive(proposed_start),
        "proposed_ended_at": _as_naive(proposed_end),
        "break_resume_sync_available": bool(sync_candidate),
        "break_id_to_sync": sync_id,
        "resolutions": [
            {
                "key": "keep_break",
                "label": "Keep break — cancel segment change",
            },
            {
                "key": "sync_break_end" if sync_candidate else "trim_break_to_segment_start",
                "label": (
                    "Move break end to the new resume/segment start"
                    if sync_candidate
                    else "Shorten break so it ends at the segment start"
                ),
                "break_id": sync_id or (conflicts[0]["break_id"] if conflicts else None),
            },
            {
                "key": "delete_break",
                "label": "Delete the overlapping break (no unpaid break)",
                "break_id": sync_id or (conflicts[0]["break_id"] if conflicts else None),
            },
        ],
    }
    raise BreakConflictError(payload["message"], payload)
