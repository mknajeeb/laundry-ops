"""Team Status — manager Mobile Ops attendance/role roster (Today / Week / Upcoming).

View-only. Reuses shift_sessions, shift_breaks, shift_job_segments, planned weekly
schedule, and payroll OT threshold rules. Worked time = gross − breaks (live open
break included). Does not write attendance or schedule rows.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from backend.business_time import business_today
from backend.mobile_ops_labels import (
    employee_assignment_label_from_segment,
    employee_role_label,
    employee_work_type_label,
)
from backend.payroll_identity import eastern_now_naive, payroll_week_bounds
from backend.payroll_overtime import DEFAULT_OT_THRESHOLD, split_hours_for_overtime
from backend.shift_job_tracking import list_session_segments
from backend.ta_helpers import table_exists, table_has_column

# Within this many hours of the OT threshold → "Near 40h" (matches payroll warn band).
NEAR_OT_REMAINING_HOURS = Decimal("5")

# Planned weekly schedule role → friendly (role_label, work_type_label).
_PLANNED_ROLE_DISPLAY: dict[str, tuple[str, Optional[str]]] = {
    "sort": ("Sort", "Rinse Wash & Fold"),
    "wash": ("Wash-Dry", "Rinse Wash & Fold"),
    "fold": ("Fold", "Rinse Wash & Fold"),
    "weigher": ("Weigher", "Rinse Wash & Fold"),
    "pt_sorter": ("Sort", "Rinse Wash & Fold"),
    "pt_washer": ("Wash-Dry", "Rinse Wash & Fold"),
    "pt_folder": ("Fold", "Rinse Wash & Fold"),
    "hd_operator": ("Operator", "Rinse Hang Dry"),
    "hd_folder": ("Folder", "Rinse Hang Dry"),
    "attendant": ("Attendant", None),
    "non_rinse_folder": ("Folder", "Non-Rinse"),
}


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


def _session_name_join(conn) -> tuple[str, str]:
    """Return (joins, name_parts_select) for shift_sessions → users name."""
    name_parts = "'' AS name_parts"
    joins = "INNER JOIN users u ON u.id = s.user_id"
    from backend.payroll_identity import payroll_profiles_active

    c = conn.cursor(dictionary=True)
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
    return joins, name_parts


def _load_day_sessions(conn, organization_id: int, day: date) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_sessions"):
        return []
    joins, name_parts = _session_name_join(conn)
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
        (int(organization_id), day.isoformat()),
    )
    return list(c.fetchall() or [])


def _load_range_sessions(conn, organization_id: int, start: date, end: date) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_sessions"):
        return []
    joins, name_parts = _session_name_join(conn)
    c.execute(
        f"""
        SELECT s.*,
               u.display_name, u.username,
               {name_parts}
        FROM shift_sessions s
        {joins}
        WHERE s.organization_id = %s
          AND DATE(s.clock_in_at) BETWEEN %s AND %s
        ORDER BY s.clock_in_at ASC, s.id ASC
        """,
        (int(organization_id), start.isoformat(), end.isoformat()),
    )
    return list(c.fetchall() or [])


def _org_ot_threshold_hours(conn, organization_id: int) -> Decimal:
    c = conn.cursor(dictionary=True)
    try:
        if table_exists(c, "payroll_schedule_org_settings"):
            c.execute(
                "SELECT overtime_threshold_hours FROM payroll_schedule_org_settings WHERE organization_id=%s",
                (int(organization_id),),
            )
            row = c.fetchone() or {}
            if row.get("overtime_threshold_hours") is not None:
                return Decimal(str(row["overtime_threshold_hours"]))
    except Exception:
        pass
    return DEFAULT_OT_THRESHOLD


def _hours_to_seconds(hours: Decimal | float | int) -> int:
    try:
        return max(0, int((Decimal(str(hours)) * Decimal("3600")).to_integral_value()))
    except Exception:
        return 0


def _ot_flag(worked_seconds: int, threshold_hours: Decimal) -> Optional[str]:
    thr_sec = _hours_to_seconds(threshold_hours)
    if thr_sec <= 0:
        return None
    if worked_seconds > thr_sec:
        return "ot"
    remaining = thr_sec - worked_seconds
    near_band = _hours_to_seconds(NEAR_OT_REMAINING_HOURS)
    if remaining <= near_band:
        return "near_40"
    return None


def _week_hours_context(
    worked_seconds: int,
    *,
    week_start: date,
    week_end: date,
    threshold_hours: Decimal,
) -> dict[str, Any]:
    hours = Decimal(str(worked_seconds)) / Decimal("3600")
    regular, ot = split_hours_for_overtime(hours, threshold=threshold_hours, enabled=True)
    thr_sec = _hours_to_seconds(threshold_hours)
    seconds_to = max(0, thr_sec - int(worked_seconds))
    flag = _ot_flag(int(worked_seconds), threshold_hours)
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "worked_seconds": int(worked_seconds),
        "ot_threshold_hours": float(threshold_hours),
        "regular_seconds": _hours_to_seconds(regular),
        "ot_seconds": _hours_to_seconds(ot),
        "seconds_to_threshold": seconds_to,
        "flag": flag,
    }


def _aggregate_user_week_seconds(
    sessions: list[dict],
    breaks_by: dict[int, list[dict]],
    *,
    now: datetime,
) -> dict[int, dict[str, Any]]:
    """user_id → {display_name, worked_seconds, by_day: {ymd: seconds}, break_seconds}."""
    by_user: dict[int, dict[str, Any]] = {}
    for sess in sessions:
        uid = int(sess["user_id"])
        sid = int(sess["id"])
        brs = breaks_by.get(sid, [])
        worked, _, _ = _session_worked_seconds(sess, brs, now=now)
        break_sec, _, _ = _break_seconds_for_session(brs, now=now)
        clock_in = _parse_dt(sess.get("clock_in_at"))
        day_key = clock_in.date().isoformat() if clock_in else None
        emp = by_user.get(uid)
        if not emp:
            emp = {
                "user_id": uid,
                "display_name": _display_name(sess),
                "worked_seconds": 0,
                "break_seconds": 0,
                "by_day": {},
            }
            by_user[uid] = emp
        emp["worked_seconds"] += worked
        emp["break_seconds"] += break_sec
        if day_key:
            emp["by_day"][day_key] = int(emp["by_day"].get(day_key) or 0) + worked
    return by_user


def _planned_dow(d: date) -> int:
    """Sunday=0 … Saturday=6 for planned_weekly_schedule."""
    return (d.weekday() + 1) % 7


def _planned_assignment_payload(roles: list[str]) -> dict[str, Any]:
    if not roles:
        return {
            "roles": [],
            "role_label": "",
            "work_type_label": "",
            "assignment_label": "",
            "role_labels": [],
        }
    labels: list[str] = []
    work_types: list[str] = []
    for code in roles:
        role_lbl, wt = _PLANNED_ROLE_DISPLAY.get(code, (code.replace("_", " ").title(), None))
        if role_lbl and role_lbl not in labels:
            labels.append(role_lbl)
        if wt and wt not in work_types:
            work_types.append(wt)
    role_label = " · ".join(labels)
    work_type_label = work_types[0] if len(work_types) == 1 else " · ".join(work_types)
    if role_label and work_type_label:
        assignment = f"{role_label} | {work_type_label}"
    else:
        assignment = role_label or work_type_label
    return {
        "roles": list(roles),
        "role_label": role_label,
        "work_type_label": work_type_label,
        "assignment_label": assignment,
        "role_labels": labels,
    }


def _format_time_hhmm(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%H:%M")
        except Exception:
            pass
    s = str(val).strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s


def _schedulable_user_ids(conn, organization_id: int) -> set[int] | None:
    """Workers whose Mapping affiliation is not ``none``. ``None`` = lookup failed."""
    from backend.planned_weekly_schedule import schedulable_worker_user_ids

    try:
        return schedulable_worker_user_ids(conn, int(organization_id))
    except Exception:
        return None


def _filter_planned_entries_for_schedulable(
    entries: list[dict],
    schedulable_uids: set[int] | None,
) -> list[dict]:
    if schedulable_uids is None:
        return list(entries or [])
    return [e for e in entries if int(e.get("user_id") or 0) in schedulable_uids]


def _load_planned_day_entries(conn, organization_id: int, day: date) -> list[dict]:
    """Read-only planned schedule entries for one calendar day (no carry-forward writes)."""
    from backend.planned_weekly_schedule import list_week_entries, normalize_week_start

    c = conn.cursor(dictionary=True)
    week_start = normalize_week_start(day)
    if not week_start:
        return []
    try:
        entries = list_week_entries(c, int(organization_id), week_start=week_start, conn=conn)
    except Exception:
        return []
    dow = _planned_dow(day)
    day_entries = [e for e in entries if int(e.get("day_of_week") or -1) == dow]
    return _filter_planned_entries_for_schedulable(
        day_entries,
        _schedulable_user_ids(conn, organization_id),
    )


def _saturday_template_entries_for_upcoming_sunday(
    conn,
    organization_id: int,
    *,
    today: date,
    day: date,
    primary_entries: list[dict],
) -> list[dict]:
    """When tomorrow is Sunday and still unplanned, preview today's Saturday shifts."""
    if primary_entries:
        return primary_entries
    if day != today + timedelta(days=1):
        return primary_entries
    if day.weekday() != 6 or today.weekday() != 5:
        return primary_entries
    return _load_planned_day_entries(conn, organization_id, today)


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
    return _inject_timeline_gaps(events, clock_in=clock_in, clock_out=clock_out, now=now)


def _inject_timeline_gaps(
    events: list[dict],
    *,
    clock_in: Optional[datetime],
    clock_out: Optional[datetime],
    now: datetime,
) -> list[dict]:
    """Insert explicit data-gap rows for intervals covered by neither role nor break."""
    if not clock_in:
        return events
    end_bound = clock_out or now
    covered: list[tuple[datetime, datetime]] = []
    for ev in events:
        if ev.get("type") not in ("role", "break"):
            continue
        start = _parse_dt(ev.get("started_at"))
        end = _parse_dt(ev.get("ended_at")) or (now if ev.get("open") else None)
        if start and end and end > start:
            covered.append((start, end))
    covered.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for s, e in covered:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    gaps: list[dict] = []
    cursor = clock_in
    for s, e in merged:
        if s > cursor and int((s - cursor).total_seconds()) >= 60:
            gaps.append(
                {
                    "type": "gap",
                    "started_at": _iso(cursor),
                    "ended_at": _iso(s),
                    "duration_seconds": int((s - cursor).total_seconds()),
                    "label": "Data gap",
                }
            )
        cursor = max(cursor, e)
    if end_bound > cursor and int((end_bound - cursor).total_seconds()) >= 60:
        gaps.append(
            {
                "type": "gap",
                "started_at": _iso(cursor),
                "ended_at": _iso(end_bound) if clock_out else None,
                "open": clock_out is None,
                "duration_seconds": int((end_bound - cursor).total_seconds()),
                "label": "Data gap",
            }
        )

    if not gaps:
        return events
    out = list(events) + gaps
    out.sort(
        key=lambda e: (
            _parse_dt(e.get("at") or e.get("started_at")) or datetime.min,
            e.get("type") or "",
        )
    )
    return out


def _canonical_role_bucket(label: str) -> Optional[str]:
    key = (label or "").strip().lower()
    if key in ("wash-dry", "wash dry", "operator"):
        return "Wash-Dry"
    if key in ("sort", "sorting", "sorter"):
        return "Sort"
    if key in ("fold", "folder", "folding"):
        return "Fold"
    if label:
        return label
    return None


def _build_role_coverage(
    working_now: list[dict],
    all_cards: list[dict],
) -> dict[str, Any]:
    """Active headcounts + unique worked-today role participation."""
    active_order = ("Wash-Dry", "Sort", "Fold")
    active_counts = {k: 0 for k in active_order}
    break_count = 0
    for emp in working_now:
        if emp.get("on_break") or emp.get("status") == "on_break":
            break_count += 1
            continue
        label = emp.get("role_label") or ""
        if not label and emp.get("assignment"):
            label = (emp["assignment"] or {}).get("role_label") or ""
        bucket = _canonical_role_bucket(label)
        if bucket in active_counts:
            active_counts[bucket] += 1
        elif bucket:
            active_counts[bucket] = active_counts.get(bucket, 0) + 1

    active_roles = [{"label": k, "count": active_counts[k]} for k in active_order]
    for k, v in active_counts.items():
        if k not in active_order and v > 0:
            active_roles.append({"label": k, "count": v})
    active_roles.append({"label": "Break", "count": break_count})

    participation: dict[str, set[int]] = {k: set() for k in active_order}
    role_seconds: dict[str, int] = {k: 0 for k in active_order}
    for emp in all_cards:
        uid = int(emp.get("user_id") or 0)
        for row in emp.get("role_summary") or []:
            if row.get("kind") != "role":
                continue
            bucket = _canonical_role_bucket(str(row.get("label") or ""))
            if not bucket:
                continue
            if bucket not in participation:
                participation[bucket] = set()
                role_seconds[bucket] = 0
            if uid:
                participation[bucket].add(uid)
            role_seconds[bucket] = int(role_seconds.get(bucket) or 0) + int(
                row.get("duration_seconds") or 0
            )

    worked_today_roles = []
    for k in list(active_order) + [x for x in participation if x not in active_order]:
        users = participation.get(k) or set()
        if not users and not role_seconds.get(k):
            continue
        worked_today_roles.append(
            {
                "label": k,
                "unique_employees": len(users),
                "duration_seconds": int(role_seconds.get(k) or 0),
            }
        )

    return {
        "active_roles": active_roles,
        "worked_today_roles": worked_today_roles,
        "worked_today_roles_note": (
            "People who worked each role today; employees may appear in more than one role."
        ),
    }


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
    oid = int(organization_id)

    week_start, week_end = payroll_week_bounds(conn, day, oid)
    threshold = _org_ot_threshold_hours(conn, oid)

    sessions = _load_day_sessions(conn, oid, day)
    session_ids = [int(s["id"]) for s in sessions]
    breaks_by = _fetch_breaks(conn, session_ids)

    week_sessions = _load_range_sessions(conn, oid, week_start, week_end)
    week_breaks = _fetch_breaks(conn, [int(s["id"]) for s in week_sessions])
    week_by_user = _aggregate_user_week_seconds(week_sessions, week_breaks, now=now)

    planned_day = _load_planned_day_entries(conn, oid, day)
    planned_by_user: dict[int, list[dict]] = {}
    for entry in planned_day:
        uid = int(entry.get("user_id") or 0)
        if uid:
            planned_by_user.setdefault(uid, []).append(entry)

    # user_id → aggregated employee card
    by_user: dict[int, dict] = {}

    for sess in sessions:
        uid = int(sess["user_id"])
        sid = int(sess["id"])
        brs = breaks_by.get(sid, [])
        worked, on_break, open_break_start = _session_worked_seconds(sess, brs, now=now)
        break_sec, _, _ = _break_seconds_for_session(brs, now=now)
        segments = list_session_segments(conn, sid)
        status = str(sess.get("status") or "").strip().lower()
        active = is_today and status == "active" and not _parse_dt(sess.get("clock_out_at"))
        clock_in = _parse_dt(sess.get("clock_in_at"))
        clock_out = _parse_dt(sess.get("clock_out_at"))
        open_break_sec = 0
        if active and on_break and open_break_start:
            open_break_sec = max(0, int((now - open_break_start).total_seconds()))

        emp = by_user.get(uid)
        if not emp:
            emp = {
                "user_id": uid,
                "display_name": _display_name(sess),
                "active": False,
                "on_break": False,
                "worked_seconds": 0,
                "break_seconds": 0,
                "open_break_seconds": 0,
                "clock_in_at": None,
                "clock_out_at": None,
                "assignment": _assignment_payload(None),
                "sessions": [],
                "role_summary": [],
                "timeline": [],
            }
            by_user[uid] = emp

        emp["worked_seconds"] += worked
        emp["break_seconds"] += break_sec
        emp["active"] = emp["active"] or active
        emp["on_break"] = emp["on_break"] or (active and on_break)
        if active and on_break:
            emp["open_break_seconds"] = max(int(emp.get("open_break_seconds") or 0), open_break_sec)
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
        elif not emp["active"] and not (emp.get("assignment") or {}).get("assignment_label"):
            # Prefer last completed role assignment for Worked Today cards
            if assign.get("assignment_label"):
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
                "break_seconds": break_sec,
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
        elif not emp["active"] and not (emp.get("assignment") or {}).get("assignment_label"):
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
        week_ctx = _week_hours_context(
            int((week_by_user.get(emp["user_id"]) or {}).get("worked_seconds") or 0),
            week_start=week_start,
            week_end=week_end,
            threshold_hours=threshold,
        )
        role_chips = [
            r.get("label")
            for r in (emp.get("role_summary") or [])
            if r.get("kind") == "role" and r.get("label")
        ]
        scheduled = planned_by_user.get(emp["user_id"]) or []
        scheduled_seconds = 0
        scheduled_rows = []
        for pe in scheduled:
            hrs = float(pe.get("hours") or 0)
            scheduled_seconds += _hours_to_seconds(hrs)
            ap = _planned_assignment_payload(list(pe.get("roles") or []))
            scheduled_rows.append(
                {
                    "start_time": pe.get("start_time"),
                    "end_time": pe.get("end_time"),
                    "hours": hrs,
                    "assignment_label": ap.get("assignment_label") or "",
                    "roles": ap.get("roles") or [],
                }
            )
        card = {
            "user_id": emp["user_id"],
            "display_name": emp["display_name"],
            "worked_seconds": int(emp["worked_seconds"]),
            "break_seconds": int(emp["break_seconds"]),
            "open_break_seconds": int(emp.get("open_break_seconds") or 0),
            "clock_in_at": emp["clock_in_at"],
            "clock_out_at": emp["clock_out_at"],
            "assignment": assign,
            "assignment_label": assign.get("assignment_label") or "",
            "role_label": assign.get("role_label") or "",
            "work_type_label": assign.get("work_type_label") or "",
            "role_code": assign.get("role_code"),
            "category_code": assign.get("category_code"),
            "on_break": bool(emp["on_break"]),
            "status": (
                "on_break"
                if emp["active"] and emp["on_break"]
                else "working"
                if emp["active"]
                else "completed"
            ),
            "role_summary": emp["role_summary"],
            "role_chips": role_chips,
            "timeline": emp["timeline"],
            "sessions": emp["sessions"],
            "week": week_ctx,
            "scheduled_seconds": scheduled_seconds,
            "scheduled": scheduled_rows,
        }
        if is_today and emp["active"]:
            working_now.append(card)
        else:
            worked_list.append(card)

    working_now.sort(key=lambda e: (_parse_dt(e.get("clock_in_at")) or datetime.max, e["display_name"]))
    worked_list.sort(key=lambda e: (_parse_dt(e.get("clock_in_at")) or datetime.max, e["display_name"]))

    total_hrs_seconds = sum(int(e["worked_seconds"]) for e in by_user.values())
    unique_worked = len(by_user)
    break_count = sum(1 for e in working_now if e.get("on_break") or e.get("status") == "on_break")
    all_cards = (working_now if is_today else []) + worked_list
    coverage = _build_role_coverage(working_now if is_today else [], all_cards)

    return {
        "ok": True,
        "date_et": day.isoformat(),
        "is_today": is_today,
        "business_today_et": today.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "ot_threshold_hours": float(threshold),
        "summary": {
            "working_count": len(working_now) if is_today else 0,
            "break_count": break_count if is_today else 0,
            "worked_count": unique_worked,
            "total_worked_seconds": total_hrs_seconds,
            "active_roles": coverage["active_roles"] if is_today else [],
            "worked_today_roles": coverage["worked_today_roles"],
            "worked_today_roles_note": coverage["worked_today_roles_note"],
        },
        "working_now": working_now if is_today else [],
        "worked": worked_list,
    }


def build_team_status_week(
    conn,
    organization_id: int,
    *,
    date_et: Optional[date] = None,
) -> dict[str, Any]:
    """Payroll-week labor control: OT / Near 40h / everyone else."""
    day = date_et or business_today()
    if not isinstance(day, date):
        raise ValueError("Invalid date_et")
    oid = int(organization_id)
    now = eastern_now_naive()
    week_start, week_end = payroll_week_bounds(conn, day, oid)
    threshold = _org_ot_threshold_hours(conn, oid)

    sessions = _load_range_sessions(conn, oid, week_start, week_end)
    breaks_by = _fetch_breaks(conn, [int(s["id"]) for s in sessions])
    by_user = _aggregate_user_week_seconds(sessions, breaks_by, now=now)

    # Role-hour breakdown per user across week (from segments)
    role_by_user: dict[int, dict[str, int]] = {}
    for sess in sessions:
        uid = int(sess["user_id"])
        sid = int(sess["id"])
        segments = list_session_segments(conn, sid)
        for seg in segments:
            label = employee_role_label(
                seg.get("role_name_snapshot") or seg.get("role_name"),
                role_code=seg.get("role_code"),
            ) or "Role"
            start = _parse_dt(seg.get("started_at"))
            end = _parse_dt(seg.get("ended_at"))
            if start:
                end_eff = end or now
                secs = max(0, int((end_eff - start).total_seconds()))
            else:
                secs = int(seg.get("duration_seconds") or 0)
            bucket = role_by_user.setdefault(uid, {})
            bucket[label] = int(bucket.get(label) or 0) + secs

    # Scheduled hours for the payroll week from planned schedule (Sunday weeks may
    # span two planned weeks — load both Sunday anchors that cover the range).
    from backend.planned_weekly_schedule import list_week_entries, normalize_week_start

    scheduled_by_user: dict[int, float] = {}
    scheduled_by_user_day: dict[int, dict[str, float]] = {}
    c = conn.cursor(dictionary=True)
    sunday_anchors: set[date] = set()
    cursor_day = week_start
    while cursor_day <= week_end:
        ws = normalize_week_start(cursor_day)
        if ws:
            sunday_anchors.add(ws)
        cursor_day += timedelta(days=1)
    for ws in sorted(sunday_anchors):
        try:
            entries = list_week_entries(c, oid, week_start=ws, conn=conn)
        except Exception:
            entries = []
        schedulable_uids = _schedulable_user_ids(conn, oid)
        for entry in _filter_planned_entries_for_schedulable(entries, schedulable_uids):
            entry_date = ws + timedelta(days=int(entry.get("day_of_week") or 0))
            if entry_date < week_start or entry_date > week_end:
                continue
            uid = int(entry.get("user_id") or 0)
            if not uid:
                continue
            hrs = float(entry.get("hours") or 0)
            scheduled_by_user[uid] = float(scheduled_by_user.get(uid) or 0) + hrs
            day_map = scheduled_by_user_day.setdefault(uid, {})
            ymd = entry_date.isoformat()
            day_map[ymd] = float(day_map.get(ymd) or 0) + hrs

    employees: list[dict] = []
    total_seconds = 0
    near_count = 0
    ot_count = 0
    for uid, emp in by_user.items():
        worked = int(emp["worked_seconds"])
        total_seconds += worked
        ctx = _week_hours_context(
            worked,
            week_start=week_start,
            week_end=week_end,
            threshold_hours=threshold,
        )
        flag = ctx.get("flag")
        if flag == "ot":
            ot_count += 1
        elif flag == "near_40":
            near_count += 1
        days = []
        day_cursor = week_start
        while day_cursor <= week_end:
            ymd = day_cursor.isoformat()
            days.append(
                {
                    "date_et": ymd,
                    "worked_seconds": int((emp.get("by_day") or {}).get(ymd) or 0),
                    "scheduled_hours": float((scheduled_by_user_day.get(uid) or {}).get(ymd) or 0),
                }
            )
            day_cursor += timedelta(days=1)
        role_hours = [
            {"label": label, "duration_seconds": secs}
            for label, secs in sorted(
                (role_by_user.get(uid) or {}).items(),
                key=lambda x: (-x[1], x[0]),
            )
            if secs > 0
        ]
        employees.append(
            {
                "user_id": uid,
                "display_name": emp["display_name"],
                "worked_seconds": worked,
                "break_seconds": int(emp.get("break_seconds") or 0),
                "regular_seconds": ctx["regular_seconds"],
                "ot_seconds": ctx["ot_seconds"],
                "seconds_to_threshold": ctx["seconds_to_threshold"],
                "flag": flag,
                "scheduled_hours": float(scheduled_by_user.get(uid) or 0),
                "days": days,
                "role_hours": role_hours,
            }
        )

    def _sort_key(row: dict) -> tuple:
        flag = row.get("flag")
        rank = 0 if flag == "ot" else 1 if flag == "near_40" else 2
        return (rank, -(row.get("worked_seconds") or 0), row.get("display_name") or "")

    employees.sort(key=_sort_key)

    return {
        "ok": True,
        "date_et": day.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "ot_threshold_hours": float(threshold),
        "summary": {
            "total_worked_seconds": total_seconds,
            "near_count": near_count,
            "ot_count": ot_count,
            "employee_count": len(employees),
        },
        "employees": employees,
    }


def build_team_status_upcoming(
    conn,
    organization_id: int,
    *,
    date_et: Optional[date] = None,
) -> dict[str, Any]:
    """Upcoming staffing from planned weekly schedule (default: tomorrow)."""
    today = business_today()
    day = date_et or (today + timedelta(days=1))
    if not isinstance(day, date):
        raise ValueError("Invalid date_et")
    oid = int(organization_id)

    from backend.planned_weekly_schedule import _load_workers, _workers_index

    entries = _load_planned_day_entries(conn, oid, day)
    entries = _saturday_template_entries_for_upcoming_sunday(
        conn,
        oid,
        today=today,
        day=day,
        primary_entries=entries,
    )
    workers = _load_workers(conn, oid)
    workers_by = _workers_index(workers)

    # Date chip window: tomorrow through +6 days
    chips: list[dict] = []
    for i in range(0, 7):
        d = today + timedelta(days=1 + i)
        chips.append(
            {
                "date_et": d.isoformat(),
                "label": f"{d.strftime('%a')} {d.day}",
                "is_tomorrow": d == today + timedelta(days=1),
                "selected": d == day,
            }
        )

    rows: list[dict] = []
    staff_ids: set[int] = set()
    total_scheduled_hours = 0.0
    for entry in entries:
        uid = int(entry.get("user_id") or 0)
        if not uid:
            continue
        worker = workers_by.get(uid) or {}
        name = (
            worker.get("display_name")
            or worker.get("worker_name")
            or f"User {uid}"
        )
        ap = _planned_assignment_payload(list(entry.get("roles") or []))
        hrs = float(entry.get("hours") or 0)
        total_scheduled_hours += hrs
        staff_ids.add(uid)
        start_s = _format_time_hhmm(entry.get("start_time"))
        end_s = _format_time_hhmm(entry.get("end_time"))
        rows.append(
            {
                "user_id": uid,
                "display_name": name,
                "start_time": start_s,
                "end_time": end_s,
                "hours": hrs,
                "assignment_label": ap.get("assignment_label") or "",
                "role_label": ap.get("role_label") or "",
                "work_type_label": ap.get("work_type_label") or "",
                "roles": ap.get("roles") or [],
            }
        )

    rows.sort(key=lambda r: (r.get("start_time") or "99:99", r.get("display_name") or ""))

    # Group by start time
    groups: list[dict] = []
    by_start: dict[str, list] = {}
    order: list[str] = []
    for row in rows:
        key = row.get("start_time") or ""
        if key not in by_start:
            by_start[key] = []
            order.append(key)
        by_start[key].append(row)
    for key in order:
        groups.append({"start_time": key, "entries": by_start[key]})

    is_tomorrow = day == today + timedelta(days=1)
    month_day = f"{day.strftime('%b')} {day.day}"
    return {
        "ok": True,
        "date_et": day.isoformat(),
        "business_today_et": today.isoformat(),
        "is_tomorrow": is_tomorrow,
        "day_label": "Tomorrow" if is_tomorrow else f"{day.strftime('%a')} · {month_day}",
        "chips": chips,
        "summary": {
            "staff_count": len(staff_ids),
            "scheduled_hours": round(total_scheduled_hours, 2),
            "entry_count": len(rows),
        },
        "groups": groups,
        "entries": rows,
    }
