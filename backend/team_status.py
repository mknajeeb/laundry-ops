"""Team Status — manager Mobile Ops attendance/role roster for a business date.

View-only. Reuses shift_sessions, shift_breaks, and shift_job_segments.
Does not invent payroll hours; worked time = gross − breaks (live open break included).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from backend.business_time import business_today
from backend.mobile_ops_labels import (
    employee_assignment_label_from_segment,
    employee_role_label,
    employee_work_type_label,
)
from backend.payroll_identity import eastern_now_naive
from backend.shift_job_tracking import list_session_segments
from backend.ta_helpers import table_exists, table_has_column


def _parse_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if getattr(val, "tzinfo", None) else val
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t.replace(tzinfo=None) if t.tzinfo else t
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:26], fmt)
        except Exception:
            continue
    return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(sep=" ") if dt else None


def _display_name(row: dict) -> str:
    parts = (row.get("name_parts") or "").strip()
    if parts:
        return parts
    return (row.get("display_name") or row.get("username") or "Employee").strip() or "Employee"


def _break_seconds_for_session(
    breaks: list[dict],
    *,
    now: datetime,
    clip_start: Optional[datetime] = None,
    clip_end: Optional[datetime] = None,
) -> tuple[int, bool, Optional[datetime]]:
    """Return (completed+open break seconds, on_break, open_break_started_at)."""
    total = 0
    on_break = False
    open_start = None
    for br in breaks:
        start = _parse_dt(br.get("break_start_at"))
        end = _parse_dt(br.get("break_end_at"))
        if not start:
            continue
        end_eff = end or now
        if clip_start and end_eff <= clip_start:
            continue
        if clip_end and start >= clip_end:
            continue
        s = start
        e = end_eff
        if clip_start and s < clip_start:
            s = clip_start
        if clip_end and e > clip_end:
            e = clip_end
        if e > s:
            total += int((e - s).total_seconds())
        if end is None:
            on_break = True
            open_start = start
    return total, on_break, open_start


def _session_worked_seconds(
    session: dict,
    breaks: list[dict],
    *,
    now: datetime,
) -> tuple[int, bool, Optional[datetime]]:
    """Worked seconds for a session (gross − breaks). Prefer stored net when completed."""
    clock_in = _parse_dt(session.get("clock_in_at"))
    clock_out = _parse_dt(session.get("clock_out_at"))
    status = str(session.get("status") or "").strip().lower()
    active = status == "active" and clock_out is None
    break_sec, on_break, open_start = _break_seconds_for_session(breaks, now=now)

    if not active:
        stored = session.get("net_work_seconds")
        if stored is not None:
            try:
                return max(0, int(stored)), False, None
            except (TypeError, ValueError):
                pass
        if not clock_in:
            return 0, False, None
        end = clock_out or now
        gross = max(0, int((end - clock_in).total_seconds()))
        return max(0, gross - break_sec), False, None

    if not clock_in:
        return 0, on_break, open_start
    gross = max(0, int((now - clock_in).total_seconds()))
    return max(0, gross - break_sec), on_break, open_start


def _fetch_breaks(conn, session_ids: list[int]) -> dict[int, list[dict]]:
    if not session_ids:
        return {}
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_breaks"):
        return {}
    ph = ",".join(["%s"] * len(session_ids))
    c.execute(
        f"""
        SELECT *
        FROM shift_breaks
        WHERE shift_session_id IN ({ph})
        ORDER BY break_start_at ASC, id ASC
        """,
        tuple(int(x) for x in session_ids),
    )
    out: dict[int, list[dict]] = {}
    for row in c.fetchall() or []:
        sid = int(row["shift_session_id"])
        out.setdefault(sid, []).append(row)
    return out


def _load_day_sessions(conn, organization_id: int, day: date) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_sessions"):
        return []
    day_s = day.isoformat()
    name_parts = "'' AS name_parts"
    joins = "INNER JOIN users u ON u.id = s.user_id"
    from backend.payroll_identity import payroll_profiles_active

    if payroll_profiles_active(conn):
        joins += " LEFT JOIN payroll_profiles pp ON pp.user_id = s.user_id"
        name_parts = (
            "TRIM(CONCAT(COALESCE(pp.first_name,''), ' ', COALESCE(pp.last_name,''))) AS name_parts"
        )
    elif table_exists(c, "ta_users") and table_has_column(c, "ta_users", "washpro_user_id"):
        joins += " LEFT JOIN ta_users t ON t.washpro_user_id = u.id"
        name_parts = (
            "TRIM(CONCAT(COALESCE(t.first_name,''), ' ', COALESCE(t.last_name,''))) AS name_parts"
        )

    c.execute(
        f"""
        SELECT s.*,
               u.display_name, u.username,
               {name_parts}
        FROM shift_sessions s
        {joins}
        WHERE s.organization_id = %s
          AND DATE(s.clock_in_at) = %s
        ORDER BY s.clock_in_at ASC, s.id ASC
        """,
        (int(organization_id), day_s),
    )
    return list(c.fetchall() or [])


def _role_summary_from_segments(segments: list[dict], breaks: list[dict], *, now: datetime) -> list[dict]:
    role_totals: dict[str, int] = {}
    for seg in segments:
        label = employee_role_label(
            seg.get("role_name_snapshot") or seg.get("role_name"),
            role_code=seg.get("role_code"),
        ) or "Role"
        role_totals[label] = role_totals.get(label, 0) + int(seg.get("duration_seconds") or 0)
    break_sec, _, _ = _break_seconds_for_session(breaks, now=now)
    out = [
        {"kind": "role", "label": label, "duration_seconds": secs}
        for label, secs in sorted(role_totals.items(), key=lambda x: (-x[1], x[0]))
        if secs > 0
    ]
    if break_sec > 0:
        out.append({"kind": "break", "label": "Break", "duration_seconds": break_sec})
    return out


def _build_timeline(
    session: dict,
    segments: list[dict],
    breaks: list[dict],
    *,
    now: datetime,
) -> list[dict]:
    events: list[dict] = []
    clock_in = _parse_dt(session.get("clock_in_at"))
    clock_out = _parse_dt(session.get("clock_out_at"))
    if clock_in:
        events.append(
            {
                "type": "clock_in",
                "at": _iso(clock_in),
                "sort_at": clock_in,
            }
        )

    for seg in segments:
        start = _parse_dt(seg.get("started_at"))
        end = _parse_dt(seg.get("ended_at"))
        if not start:
            continue
        end_eff = end or now
        events.append(
            {
                "type": "role",
                "started_at": _iso(start),
                "ended_at": _iso(end) if end else None,
                "open": end is None,
                "duration_seconds": max(0, int((end_eff - start).total_seconds())),
                **_assignment_payload(seg),
                "sort_at": start,
            }
        )

    for br in breaks:
        start = _parse_dt(br.get("break_start_at"))
        end = _parse_dt(br.get("break_end_at"))
        if not start:
            continue
        end_eff = end or now
        events.append(
            {
                "type": "break",
                "started_at": _iso(start),
                "ended_at": _iso(end) if end else None,
                "open": end is None,
                "duration_seconds": max(0, int((end_eff - start).total_seconds())),
                "sort_at": start,
            }
        )

    if clock_out:
        events.append(
            {
                "type": "clock_out",
                "at": _iso(clock_out),
                "sort_at": clock_out,
            }
        )

    events.sort(key=lambda e: (e.get("sort_at") or datetime.min, e.get("type") or ""))
    for e in events:
        e.pop("sort_at", None)
    return events


def _assignment_payload(seg: dict | None) -> dict:
    seg = seg if isinstance(seg, dict) else {}
    role_code = seg.get("role_code")
    role_name = seg.get("role_name_snapshot") or seg.get("role_name")
    category_code = seg.get("category_code")
    category_name = seg.get("category_name_snapshot") or seg.get("category_name")
    return {
        "role_code": role_code,
        "role_name": role_name,
        "category_code": category_code,
        "category_name": category_name,
        "role_label": employee_role_label(role_name, role_code=role_code),
        "work_type_label": employee_work_type_label(category_name, category_code=category_code),
        "assignment_label": employee_assignment_label_from_segment(seg),
    }


def _current_assignment_payload(segments: list[dict]) -> dict:
    if not segments:
        return _assignment_payload(None)
    open_segs = [s for s in segments if not s.get("ended_at")]
    seg = open_segs[-1] if open_segs else segments[-1]
    return _assignment_payload(seg)


def build_team_status(
    conn,
    organization_id: int,
    *,
    date_et: Optional[date] = None,
) -> dict[str, Any]:
    """Authoritative Team Status payload for one ET business date."""
    day = date_et or business_today()
    if not isinstance(day, date):
        raise ValueError("Invalid date_et")
    today = business_today()
    is_today = day == today
    now = eastern_now_naive()

    sessions = _load_day_sessions(conn, int(organization_id), day)
    session_ids = [int(s["id"]) for s in sessions]
    breaks_by = _fetch_breaks(conn, session_ids)

    # user_id → aggregated employee card
    by_user: dict[int, dict] = {}

    for sess in sessions:
        uid = int(sess["user_id"])
        sid = int(sess["id"])
        brs = breaks_by.get(sid, [])
        worked, on_break, _ = _session_worked_seconds(sess, brs, now=now)
        segments = list_session_segments(conn, sid)
        status = str(sess.get("status") or "").strip().lower()
        active = is_today and status == "active" and not _parse_dt(sess.get("clock_out_at"))
        clock_in = _parse_dt(sess.get("clock_in_at"))
        clock_out = _parse_dt(sess.get("clock_out_at"))

        emp = by_user.get(uid)
        if not emp:
            emp = {
                "user_id": uid,
                "display_name": _display_name(sess),
                "active": False,
                "on_break": False,
                "worked_seconds": 0,
                "clock_in_at": None,
                "clock_out_at": None,
                "assignment": _assignment_payload(None),
                "sessions": [],
                "role_summary": [],
                "timeline": [],
            }
            by_user[uid] = emp

        emp["worked_seconds"] += worked
        emp["active"] = emp["active"] or active
        emp["on_break"] = emp["on_break"] or (active and on_break)
        if clock_in and (emp["clock_in_at"] is None or clock_in < _parse_dt(emp["clock_in_at"])):
            emp["clock_in_at"] = _iso(clock_in)
        if clock_out:
            prev_out = _parse_dt(emp["clock_out_at"])
            if prev_out is None or clock_out > prev_out:
                emp["clock_out_at"] = _iso(clock_out)
        elif active:
            emp["clock_out_at"] = None

        assign = _current_assignment_payload(segments)
        if active and assign.get("assignment_label"):
            emp["assignment"] = assign

        timeline = _build_timeline(sess, segments, brs, now=now)
        emp["timeline"].extend(timeline)
        emp["sessions"].append(
            {
                "shift_session_id": sid,
                "clock_in_at": _iso(clock_in),
                "clock_out_at": _iso(clock_out),
                "status": status,
                "worked_seconds": worked,
                "on_break": active and on_break,
                "assignment": assign,
                "role_summary": _role_summary_from_segments(segments, brs, now=now),
                "timeline": timeline,
            }
        )

    # Merge role summaries across sessions; sort timeline
    for emp in by_user.values():
        emp["timeline"].sort(
            key=lambda e: (
                _parse_dt(e.get("at") or e.get("started_at")) or datetime.min,
                e.get("type") or "",
            )
        )
        merged: dict[str, dict] = {}
        for sess in emp["sessions"]:
            for row in sess.get("role_summary") or []:
                key = f"{row.get('kind')}:{row.get('label')}"
                if key not in merged:
                    merged[key] = dict(row)
                else:
                    merged[key]["duration_seconds"] = int(merged[key]["duration_seconds"] or 0) + int(
                        row.get("duration_seconds") or 0
                    )
        emp["role_summary"] = sorted(
            merged.values(),
            key=lambda r: (0 if r.get("kind") == "role" else 1, -(r.get("duration_seconds") or 0)),
        )
        if emp["active"] and not (emp.get("assignment") or {}).get("assignment_label"):
            for ev in reversed(emp["timeline"]):
                if ev.get("type") == "role" and ev.get("assignment_label"):
                    emp["assignment"] = {
                        "role_code": ev.get("role_code"),
                        "role_name": ev.get("role_name"),
                        "category_code": ev.get("category_code"),
                        "category_name": ev.get("category_name"),
                        "role_label": ev.get("role_label"),
                        "work_type_label": ev.get("work_type_label"),
                        "assignment_label": ev.get("assignment_label"),
                    }
                    break

    working_now: list[dict] = []
    worked_list: list[dict] = []
    for emp in by_user.values():
        assign = emp.get("assignment") or _assignment_payload(None)
        card = {
            "user_id": emp["user_id"],
            "display_name": emp["display_name"],
            "worked_seconds": int(emp["worked_seconds"]),
            "clock_in_at": emp["clock_in_at"],
            "clock_out_at": emp["clock_out_at"],
            "assignment": assign,
            "assignment_label": assign.get("assignment_label") or "",
            "role_code": assign.get("role_code"),
            "category_code": assign.get("category_code"),
            "on_break": bool(emp["on_break"]),
            "status": (
                "on_break"
                if emp["active"] and emp["on_break"]
                else "working"
                if emp["active"]
                else "clocked_out"
            ),
            "role_summary": emp["role_summary"],
            "timeline": emp["timeline"],
            "sessions": emp["sessions"],
        }
        if is_today and emp["active"]:
            working_now.append(card)
        else:
            worked_list.append(card)

    working_now.sort(key=lambda e: (_parse_dt(e.get("clock_in_at")) or datetime.max, e["display_name"]))
    worked_list.sort(key=lambda e: (_parse_dt(e.get("clock_in_at")) or datetime.max, e["display_name"]))

    total_hrs_seconds = sum(int(e["worked_seconds"]) for e in by_user.values())
    unique_worked = len(by_user)

    return {
        "ok": True,
        "date_et": day.isoformat(),
        "is_today": is_today,
        "business_today_et": today.isoformat(),
        "summary": {
            "working_count": len(working_now) if is_today else 0,
            "worked_count": unique_worked,
            "total_worked_seconds": total_hrs_seconds,
        },
        "working_now": working_now if is_today else [],
        "worked": worked_list,
    }
