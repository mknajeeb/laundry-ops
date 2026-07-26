"""Payroll role-session context for Employee Productivity (additive only).

Layers session assignment, idle time, and bag elapsed timing on top of existing
completed-bag attribution. Does NOT modify PRE pounds, ownership, rankings, or
Bags/Hour / Lbs/Hour / Productive Hours calculations.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import eastern_now, eastern_today
from backend.rinse_folding_folder_role_productivity import (
    load_day_job_segments_by_user,
    load_shift_sessions_by_id,
    resolve_effective_role_end,
)
from backend.ta_helpers import table_exists

ASSIGNMENT_AUTO = "auto"
ASSIGNMENT_MANUAL = "manual"
ASSIGNMENT_NEEDS_REVIEW = "needs_review"
ASSIGNMENT_UNASSIGNED = "unassigned"

DEFAULT_ROLE_FILTER_KEY = "RINSE_WF:FOLDER"

_CATEGORY_SHORT = {
    "RINSE_WF": "WF",
    "RINSE_HD": "HD",
    "DHS": "DHS",
    "DROP_OFF": "DO",
    "DROPOFF": "DO",
}


def ensure_bag_session_assignments_table(cursor) -> None:
    if table_exists(cursor, "rinse_employee_bag_session_assignments"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_employee_bag_session_assignments (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          selected_date_et DATE NOT NULL,
          employee_name VARCHAR(255) NULL,
          session_id VARCHAR(64) NULL,
          segment_id INT NULL,
          assignment_source VARCHAR(32) NOT NULL DEFAULT 'manual',
          assigned_by_user_id INT NULL,
          note VARCHAR(255) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_bag_session_assign_org_bag_date (organization_id, bag_id, selected_date_et),
          KEY idx_bag_session_assign_org_date (organization_id, selected_date_et),
          KEY idx_bag_session_assign_segment (organization_id, segment_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat(sep=" ", timespec="seconds")


def _minutes(seconds: float | None) -> float | None:
    if seconds is None:
        return None
    return round(max(0.0, float(seconds)) / 60.0, 2)


def _fmt_duration_minutes(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    total = int(round(max(0.0, float(minutes))))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def role_filter_key(category_code: Any, role_code: Any) -> str:
    cat = str(category_code or "").strip().upper() or "UNKNOWN"
    role = str(role_code or "").strip().upper() or "UNKNOWN"
    return f"{cat}:{role}"


def category_short(category_code: Any) -> str:
    cat = str(category_code or "").strip().upper()
    if cat in _CATEGORY_SHORT:
        return _CATEGORY_SHORT[cat]
    if cat.startswith("RINSE_"):
        return cat.replace("RINSE_", "")[:4] or "SEG"
    return (cat[:4] or "SEG").upper()


def build_stable_session_id(segment: Mapping[str, Any]) -> str:
    """Deterministic session id from role segment — never an array index."""
    seg_id = segment.get("id")
    short = category_short(segment.get("category_code"))
    if seg_id is not None:
        try:
            return f"{short}-{int(seg_id)}"
        except (TypeError, ValueError):
            pass
    start = _parse_dt(segment.get("started_at")) or datetime.min
    user = segment.get("user_id") or 0
    role = str(segment.get("role_code") or "ROLE").upper()
    return f"{short}-{user}-{role}-{start.strftime('%Y%m%d%H%M%S')}"


def assign_session_display_codes(sessions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Human labels like WF-01 / HD-02 (display only; session_id stays stable).

    Always sets session_code — never leave the UI to fall back to session_id.
    """
    counters: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for sess in sessions or []:
        s = dict(sess)
        short = category_short(s.get("category_code")) or "SESSION"
        counters[short] = counters.get(short, 0) + 1
        existing = str(s.get("session_code") or "").strip()
        # Keep a pre-set readable code; otherwise assign deterministic WF-01 style.
        if existing and not _looks_like_internal_session_id(existing, s.get("session_id")):
            code = existing
        else:
            code = f"{short}-{counters[short]:02d}"
        s["session_code"] = code
        start_label = _fmt_clock(s.get("_start_dt") or _parse_dt(s.get("start_time")))
        if s.get("end_display") in ("Open", "Unresolved"):
            end_label = s["end_display"]
        else:
            end_label = _fmt_clock(s.get("_end_dt") or _parse_dt(s.get("end_time")))
        time_range = f"{start_label or '—'}–{end_label or '—'}"
        s["time_range_label"] = time_range
        s["option_label"] = f"{code}\n{time_range}"
        out.append(s)
    return out


def _looks_like_internal_session_id(label: Any, session_id: Any) -> bool:
    """True when a label is the raw internal session_id (must not be shown)."""
    lab = str(label or "").strip()
    sid = str(session_id or "").strip()
    if not lab:
        return True
    return bool(sid and lab == sid)


def public_session_display_fields(session: Mapping[str, Any]) -> dict[str, Any]:
    """Fields safe for UI labels — never includes session_id as a visible label."""
    code = str(session.get("session_code") or "").strip()
    if not code or _looks_like_internal_session_id(code, session.get("session_id")):
        short = category_short(session.get("category_code")) or "SESSION"
        code = f"{short}-01"
    return {
        "session_code": code,
        "option_label": session.get("option_label") or code,
        "time_range_label": session.get("time_range_label"),
    }


def _fmt_clock(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    hour = dt.hour % 12 or 12
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour}:{dt.minute:02d} {ampm}"


def resolve_customer_name(*candidates: Any) -> str | None:
    """Return first usable customer name, or None if none found (caller may fall back)."""
    for raw in candidates:
        name = str(raw or "").strip()
        if name and name not in ("—", "-", "–", "N/A", "n/a", "null", "None", "Unknown Customer"):
            return name
    return None


def customer_name_or_unknown(*candidates: Any) -> str:
    return resolve_customer_name(*candidates) or "Unknown Customer"


def _bag_completion_ts(bag: Mapping[str, Any]) -> datetime | None:
    return _parse_dt(
        bag.get("credit_timestamp")
        or bag.get("completion_time")
        or bag.get("completion_timestamp")
        or bag.get("processed_time")
        or bag.get("processed_timestamp")
    )


def _next_segment_start(
    segments: Sequence[Mapping[str, Any]],
    index: int,
) -> datetime | None:
    if index < 0 or index + 1 >= len(segments):
        return None
    return _parse_dt(segments[index + 1].get("started_at"))


def build_payroll_session(
    segment: Mapping[str, Any],
    *,
    selected_date_et: date,
    now_et: datetime | None = None,
    session_row: Mapping[str, Any] | None = None,
    next_segment_start: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one shift_job_segment into a payroll session payload."""
    start = _parse_dt(segment.get("started_at"))
    if start is None:
        return None
    raw_end = _parse_dt(segment.get("ended_at"))
    clock_out = None
    if session_row:
        clock_out = _parse_dt(session_row.get("clock_out_at"))
    end_info = resolve_effective_role_end(
        role_start=start,
        role_end=raw_end,
        selected_date_et=selected_date_et,
        now_et=now_et,
        session_clock_out=clock_out,
        next_segment_start=next_segment_start,
    )
    effective_end = end_info.get("effective_end")
    duration_minutes = None
    if effective_end is not None:
        duration_minutes = _minutes((effective_end - start).total_seconds())
    cat_code = str(segment.get("category_code") or "").strip().upper()
    role_code = str(segment.get("role_code") or "").strip().upper()
    cat_name = (
        segment.get("category_name_snapshot")
        or segment.get("category_name")
        or cat_code
        or "Unknown"
    )
    role_name = (
        segment.get("role_name_snapshot")
        or segment.get("role_name")
        or role_code
        or "Unknown"
    )
    session_id = build_stable_session_id(segment)
    seg_db_id = None
    try:
        if segment.get("id") is not None:
            seg_db_id = int(segment["id"])
    except (TypeError, ValueError):
        seg_db_id = None
    return {
        "session_id": session_id,
        "segment_id": seg_db_id,
        "shift_session_id": segment.get("shift_session_id"),
        "category_code": cat_code or None,
        "role_code": role_code or None,
        "category": cat_name,
        "role": role_name,
        "display_label": f"{cat_name} — {role_name}",
        "role_filter_key": role_filter_key(cat_code, role_code),
        "start_time": _iso(start),
        "end_time": _iso(effective_end) if effective_end is not None else None,
        "end_display": (
            "Open"
            if end_info.get("role_status") == "open"
            else ("Unresolved" if end_info.get("role_end_missing") else _iso(effective_end))
        ),
        "duration_minutes": duration_minutes,
        "duration_label": _fmt_duration_minutes(duration_minutes),
        "role_status": end_info.get("role_status"),
        "role_end_missing": bool(end_info.get("role_end_missing")),
        "end_source": end_info.get("end_source"),
        "_start_dt": start,
        "_end_dt": effective_end,
    }


def sessions_matching_completion(
    sessions: Sequence[Mapping[str, Any]],
    completion_ts: datetime,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for sess in sessions or []:
        start = sess.get("_start_dt") or _parse_dt(sess.get("start_time"))
        end = sess.get("_end_dt") or _parse_dt(sess.get("end_time"))
        if start is None or end is None:
            continue
        if start <= completion_ts <= end:
            matches.append(dict(sess))
    return matches


def assign_bag_to_session(
    bag: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
    *,
    manual_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assign one completed bag to a payroll session (or mark Unassigned / Needs Review)."""
    if manual_override is not None:
        sid_raw = manual_override.get("session_id")
        sid = str(sid_raw).strip() if sid_raw else None
        if sid in ("", "null", "None", "unassigned", "UNASSIGNED"):
            sid = None
        if not sid:
            return {
                "session_id": None,
                "session_assignment": ASSIGNMENT_MANUAL,
                "session_assignment_label": "Unassigned",
                "needs_review": False,
            }
        chosen = next((s for s in sessions if str(s.get("session_id")) == sid), None)
        # Never surface internal session_id in user-facing labels.
        label = (
            (chosen or {}).get("session_code")
            or (chosen or {}).get("option_label")
            or "SESSION"
        )
        return {
            "session_id": sid,
            "session_code": (chosen or {}).get("session_code"),
            "session_assignment": ASSIGNMENT_MANUAL,
            "session_assignment_label": label,
            "needs_review": False,
        }

    ts = _bag_completion_ts(bag)
    if ts is None:
        return {
            "session_id": None,
            "session_code": None,
            "session_assignment": ASSIGNMENT_UNASSIGNED,
            "session_assignment_label": "Unassigned",
            "needs_review": False,
        }

    matches = sessions_matching_completion(sessions, ts)
    if len(matches) == 1:
        sid = matches[0].get("session_id")
        return {
            "session_id": sid,
            "session_code": matches[0].get("session_code"),
            "session_assignment": ASSIGNMENT_AUTO,
            "session_assignment_label": matches[0].get("session_code") or "SESSION",
            "needs_review": False,
        }
    if len(matches) > 1:
        return {
            "session_id": None,
            "session_code": None,
            "session_assignment": ASSIGNMENT_NEEDS_REVIEW,
            "session_assignment_label": "Needs Review",
            "needs_review": True,
            "candidate_session_ids": [m.get("session_id") for m in matches],
        }
    return {
        "session_id": None,
        "session_code": None,
        "session_assignment": ASSIGNMENT_UNASSIGNED,
        "session_assignment_label": "Unassigned",
        "needs_review": False,
    }


def compute_bag_elapsed_timing(
    bags: Sequence[Mapping[str, Any]],
    sessions_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Elapsed time between completions within each session (not folding start)."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []
    for bag in bags or []:
        if not isinstance(bag, Mapping):
            continue
        b = dict(bag)
        sid = b.get("session_id")
        if not sid or b.get("session_assignment") in (
            ASSIGNMENT_UNASSIGNED,
            ASSIGNMENT_NEEDS_REVIEW,
        ):
            # Needs Review / Unassigned: still show bag end = completion, no session start chain
            ts = _bag_completion_ts(b)
            b["bag_start"] = None
            b["bag_end"] = _iso(ts)
            b["elapsed_time_seconds"] = None
            b["elapsed_time_minutes"] = None
            b["elapsed_time_label"] = None
            unassigned.append(b)
            continue
        by_session.setdefault(str(sid), []).append(b)

    out: list[dict[str, Any]] = []
    for sid, group in by_session.items():
        group.sort(key=lambda x: _bag_completion_ts(x) or datetime.min)
        sess = sessions_by_id.get(str(sid)) or {}
        session_start = sess.get("_start_dt") or _parse_dt(sess.get("start_time"))
        prev_end: datetime | None = None
        for idx, bag in enumerate(group):
            end = _bag_completion_ts(bag)
            if idx == 0:
                start = session_start
            else:
                start = prev_end
            elapsed_sec = None
            if start is not None and end is not None and end >= start:
                elapsed_sec = (end - start).total_seconds()
            bag["bag_start"] = _iso(start)
            bag["bag_end"] = _iso(end)
            bag["elapsed_time_seconds"] = (
                int(round(elapsed_sec)) if elapsed_sec is not None else None
            )
            bag["elapsed_time_minutes"] = _minutes(elapsed_sec)
            bag["elapsed_time_label"] = _fmt_duration_minutes(
                _minutes(elapsed_sec) if elapsed_sec is not None else None
            )
            prev_end = end
            out.append(bag)
    out.extend(unassigned)
    out.sort(key=lambda b: _bag_completion_ts(b) or datetime.min)
    return out


def compute_session_idle(
    session: Mapping[str, Any],
    bags_in_session: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Idle = session end − last completed bag (never negative)."""
    sess = dict(session)
    end = sess.get("_end_dt") or _parse_dt(sess.get("end_time"))
    start = sess.get("_start_dt") or _parse_dt(sess.get("start_time"))
    now = now_et or eastern_now().replace(tzinfo=None)
    if end is None and sess.get("role_status") == "open" and selected_date_et == eastern_today():
        end = now
    last_bag_ts = None
    for bag in bags_in_session or []:
        ts = _bag_completion_ts(bag)
        if ts is None:
            continue
        if last_bag_ts is None or ts > last_bag_ts:
            last_bag_ts = ts

    idle_minutes = None
    timing_conflict = False
    if end is not None:
        if last_bag_ts is not None:
            # Visible idle stays clamped at zero; flag when completion is after end.
            if last_bag_ts > end:
                timing_conflict = True
            idle_minutes = _minutes((end - last_bag_ts).total_seconds())
        elif start is not None:
            idle_minutes = _minutes((end - start).total_seconds())
        else:
            idle_minutes = 0.0

    sess["idle_minutes"] = idle_minutes
    sess["idle_label"] = _fmt_duration_minutes(idle_minutes)
    sess["last_bag_completion"] = _iso(last_bag_ts)
    sess["timing_conflict"] = bool(timing_conflict)
    # Strip internal datetime helpers from API payloads later
    return sess


def build_session_summary(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    total_sessions = len(sessions or [])
    total_session_minutes = 0.0
    total_idle_minutes = 0.0
    has_duration = False
    has_idle = False
    first_start = None
    last_end = None
    for sess in sessions or []:
        dur = sess.get("duration_minutes")
        if dur is not None:
            total_session_minutes += float(dur)
            has_duration = True
        idle = sess.get("idle_minutes")
        if idle is not None:
            total_idle_minutes += float(idle)
            has_idle = True
        st = _parse_dt(sess.get("start_time")) or sess.get("_start_dt")
        en = _parse_dt(sess.get("end_time")) or sess.get("_end_dt")
        if st is not None and (first_start is None or st < first_start):
            first_start = st
        if en is not None and (last_end is None or en > last_end):
            last_end = en

    idle_pct = None
    if has_duration and total_session_minutes > 0 and has_idle:
        idle_pct = round((total_idle_minutes / total_session_minutes) * 100.0, 1)

    return {
        "total_sessions": total_sessions,
        "total_session_minutes": round(total_session_minutes, 2) if has_duration else None,
        "total_idle_minutes": round(total_idle_minutes, 2) if has_idle else None,
        "idle_pct": idle_pct,
        "first_session": _iso(first_start),
        "last_session": _iso(last_end),
        "total_session_label": _fmt_duration_minutes(
            total_session_minutes if has_duration else None
        ),
        "total_idle_label": _fmt_duration_minutes(total_idle_minutes if has_idle else None),
    }


def _public_session(sess: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in dict(sess).items() if not str(k).startswith("_")}
    return out


def load_manual_bag_session_assignments(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    ensure_bag_session_assignments_table(cursor)
    if not table_exists(cursor, "rinse_employee_bag_session_assignments"):
        return {}
    org = int(organization_id)
    where = ["organization_id = %s", "selected_date_et = %s"]
    params: list[Any] = [org, selected_date_et]
    ids = [str(b).strip().upper() for b in (bag_ids or []) if b]
    if ids:
        ph = ",".join(["%s"] * len(ids))
        where.append(f"bag_id IN ({ph})")
        params.extend(ids)
    cursor.execute(
        f"""
        SELECT bag_id, session_id, segment_id, assignment_source, employee_name
        FROM rinse_employee_bag_session_assignments
        WHERE {' AND '.join(where)}
        """,
        tuple(params),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if bid:
            out[bid] = dict(row)
    return out


def upsert_manual_bag_session_assignment(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    session_id: str | None,
    segment_id: int | None = None,
    employee_name: str | None = None,
    assigned_by_user_id: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    ensure_bag_session_assignments_table(cursor)
    bid = str(bag_id or "").strip().upper()
    if not bid:
        raise ValueError("bag_id required")
    org = int(organization_id)
    sid = str(session_id).strip() if session_id else None
    if sid in ("", "null", "None", "unassigned", "UNASSIGNED"):
        sid = None
    cursor.execute(
        """
        INSERT INTO rinse_employee_bag_session_assignments (
          organization_id, bag_id, selected_date_et, employee_name,
          session_id, segment_id, assignment_source, assigned_by_user_id, note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          employee_name = VALUES(employee_name),
          session_id = VALUES(session_id),
          segment_id = VALUES(segment_id),
          assignment_source = VALUES(assignment_source),
          assigned_by_user_id = VALUES(assigned_by_user_id),
          note = VALUES(note),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            org,
            bid,
            selected_date_et,
            (str(employee_name).strip() if employee_name else None),
            sid,
            segment_id,
            ASSIGNMENT_MANUAL,
            assigned_by_user_id,
            note,
        ),
    )
    return {
        "bag_id": bid,
        "selected_date_et": selected_date_et.isoformat(),
        "session_id": sid,
        "segment_id": segment_id,
        "assignment_source": ASSIGNMENT_MANUAL,
    }


def enrich_employee_with_sessions(
    emp: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    sessions_by_id: Mapping[int, Mapping[str, Any]] | None = None,
    manual_assignments: Mapping[str, Mapping[str, Any]] | None = None,
    now_et: datetime | None = None,
    role_filter_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Add sessions / bag session fields without mutating productivity metrics."""
    out = dict(emp)
    segs = sorted(
        [s for s in (segments or []) if isinstance(s, Mapping)],
        key=lambda s: (_parse_dt(s.get("started_at")) or datetime.min, int(s.get("id") or 0)),
    )
    built: list[dict[str, Any]] = []
    for idx, seg in enumerate(segs):
        sid = None
        try:
            if seg.get("shift_session_id") is not None:
                sid = int(seg["shift_session_id"])
        except (TypeError, ValueError):
            sid = None
        session_row = (sessions_by_id or {}).get(sid) if sid is not None else None
        payload = build_payroll_session(
            seg,
            selected_date_et=selected_date_et,
            now_et=now_et,
            session_row=session_row,
            next_segment_start=_next_segment_start(segs, idx),
        )
        if payload:
            built.append(payload)

    filter_keys = None
    if role_filter_keys:
        filter_keys = {str(k).strip().upper() for k in role_filter_keys if k}
    visible = (
        [s for s in built if str(s.get("role_filter_key") or "").upper() in filter_keys]
        if filter_keys
        else list(built)
    )
    visible = assign_session_display_codes(visible)

    bags_in = list(out.get("bags") or out.get("workload_bags") or [])
    enriched_bags: list[dict[str, Any]] = []
    manuals = manual_assignments or {}
    for bag in bags_in:
        if not isinstance(bag, Mapping):
            continue
        b = dict(bag)
        bid = str(b.get("bag_id") or "").strip().upper()
        # Prefer already-resolved name; never invent Unknown here (batch resolver does).
        resolved = resolve_customer_name(
            b.get("customer_name"),
            b.get("name_clean"),
            b.get("portal_customer_name"),
            b.get("account_name"),
            b.get("customer"),
        )
        if resolved:
            b["customer_name"] = resolved
        assign = assign_bag_to_session(
            b,
            visible,
            manual_override=manuals.get(bid),
        )
        b.update(assign)
        enriched_bags.append(b)

    sessions_index = {str(s["session_id"]): s for s in visible if s.get("session_id")}
    timed_bags = compute_bag_elapsed_timing(enriched_bags, sessions_index)

    bags_by_session: dict[str, list[dict[str, Any]]] = {}
    for bag in timed_bags:
        sid = bag.get("session_id")
        if sid and bag.get("session_assignment") not in (
            ASSIGNMENT_UNASSIGNED,
            ASSIGNMENT_NEEDS_REVIEW,
        ):
            bags_by_session.setdefault(str(sid), []).append(bag)

    finalized_sessions: list[dict[str, Any]] = []
    for sess in visible:
        sid = str(sess.get("session_id") or "")
        sess_bags = bags_by_session.get(sid) or []
        with_idle = compute_session_idle(
            sess,
            sess_bags,
            selected_date_et=selected_date_et,
            now_et=now_et,
        )
        credited = 0.0
        for bag in sess_bags:
            for key in ("credited_weight_lbs", "credited_lbs", "completed_lbs", "weight_lbs"):
                raw = bag.get(key)
                if raw is None:
                    continue
                try:
                    credited += float(raw)
                    break
                except (TypeError, ValueError):
                    continue
        with_idle["completed_bags"] = len(sess_bags)
        with_idle["credited_lbs"] = round(credited, 2)
        # Guarantee readable code before public payload (never leave UI to use session_id).
        display = public_session_display_fields(with_idle)
        with_idle["session_code"] = display["session_code"]
        with_idle["option_label"] = display["option_label"]
        finalized_sessions.append(_public_session(with_idle))

    # Attach readable session_code onto bags after codes assigned.
    code_by_id = {str(s["session_id"]): s.get("session_code") for s in finalized_sessions}
    for bag in timed_bags:
        sid = bag.get("session_id")
        code = code_by_id.get(str(sid)) if sid else None
        if code:
            bag["session_code"] = code
        # Visible label must never be the internal session_id.
        if bag.get("session_assignment") in (ASSIGNMENT_AUTO, ASSIGNMENT_MANUAL) and code:
            bag["session_assignment_label"] = code
        elif bag.get("session_assignment_label") and sid:
            if str(bag.get("session_assignment_label")) == str(sid):
                bag["session_assignment_label"] = code or "SESSION-01"

    summary_extra = build_session_summary(finalized_sessions)
    existing_summary = dict(out.get("summary") or {})
    # Only the four additive summary fields managers asked for.
    existing_summary["total_sessions"] = summary_extra["total_sessions"]
    existing_summary["total_session_minutes"] = summary_extra["total_session_minutes"]
    existing_summary["total_idle_minutes"] = summary_extra["total_idle_minutes"]
    existing_summary["idle_pct"] = summary_extra["idle_pct"]
    out["summary"] = existing_summary
    # Additive root keys — never overwrite dual-productivity idle_time_hours / rates.
    out["total_sessions"] = summary_extra["total_sessions"]
    out["total_session_minutes"] = summary_extra["total_session_minutes"]
    out["total_idle_minutes"] = summary_extra["total_idle_minutes"]
    out["session_idle_pct"] = summary_extra["idle_pct"]
    out["total_session_label"] = summary_extra["total_session_label"]
    out["total_idle_label"] = summary_extra["total_idle_label"]
    out["sessions"] = finalized_sessions
    out["bags"] = [
        {k: v for k, v in b.items() if not str(k).startswith("_")} for b in timed_bags
    ]
    if "workload_bags" in out:
        out["workload_bags"] = out["bags"]
    out["role_filter_keys_present"] = sorted(
        {str(s.get("role_filter_key")) for s in built if s.get("role_filter_key")}
    )
    out["session_context_enabled"] = True
    return out


def collect_available_role_filters(
    sessions_by_employee: Mapping[Any, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for sessions in (sessions_by_employee or {}).values():
        for sess in sessions or []:
            key = str(sess.get("role_filter_key") or "")
            if not key or key in seen:
                continue
            seen[key] = {
                "key": key,
                "category": sess.get("category"),
                "role": sess.get("role"),
                "label": sess.get("display_label") or key,
                "category_code": sess.get("category_code"),
                "role_code": sess.get("role_code"),
            }
    rows = list(seen.values())
    rows.sort(
        key=lambda r: (
            0 if r.get("key") == DEFAULT_ROLE_FILTER_KEY else 1,
            str(r.get("label") or ""),
        )
    )
    return rows


def apply_productivity_session_context_to_section(
    cursor,
    organization_id: int,
    section: Mapping[str, Any] | None,
    *,
    selected_date_et: date,
    user_maps: Mapping[str, Mapping[str, Any]] | None = None,
    now_et: datetime | None = None,
    role_filter_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Enrich productivity section with payroll sessions (additive only)."""
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps

    base = dict(section or {})
    employees_in = list(base.get("employees") or [])
    employees: list[Any] = [
        dict(e) if isinstance(e, Mapping) else e for e in employees_in
    ]
    if not employees:
        base["employees"] = employees
        base["available_role_filters"] = [
            {
                "key": DEFAULT_ROLE_FILTER_KEY,
                "label": "Rinse WF — Folder",
                "category": "Rinse WF",
                "role": "Folder",
                "category_code": "RINSE_WF",
                "role_code": "FOLDER",
            }
        ]
        base["default_role_filter_keys"] = [DEFAULT_ROLE_FILTER_KEY]
        return base

    org = int(organization_id)
    maps = user_maps or _load_rinse_user_maps(cursor, org)
    user_ids: list[int] = []
    emp_user: dict[int, list[int]] = {}
    for idx, emp in enumerate(employees):
        if not isinstance(emp, dict):
            continue
        name = str(emp.get("employee") or "")
        mapping = maps.get(name.casefold()) if name else None
        if not mapping or mapping.get("user_id") is None:
            # Still enrich bags for customer_name / unassigned sessions.
            employees[idx] = enrich_employee_with_sessions(
                emp,
                [],
                selected_date_et=selected_date_et,
                now_et=now_et,
                role_filter_keys=role_filter_keys,
            )
            continue
        try:
            uid = int(mapping["user_id"])
        except (TypeError, ValueError):
            continue
        user_ids.append(uid)
        emp_user.setdefault(uid, []).append(idx)

    all_segs = load_day_job_segments_by_user(
        cursor, org, user_ids, selected_date_et=selected_date_et, folder_only=False
    )
    session_ids: list[int] = []
    for segs in all_segs.values():
        for seg in segs:
            if seg.get("shift_session_id") is not None:
                try:
                    session_ids.append(int(seg["shift_session_id"]))
                except (TypeError, ValueError):
                    pass
    shift_sessions = load_shift_sessions_by_id(cursor, org, session_ids)

    all_bag_ids: list[str] = []
    for emp in employees:
        if not isinstance(emp, dict):
            continue
        for bag in emp.get("bags") or []:
            bid = str((bag or {}).get("bag_id") or "").strip().upper()
            if bid:
                all_bag_ids.append(bid)
    manuals = load_manual_bag_session_assignments(
        cursor, org, selected_date_et=selected_date_et, bag_ids=all_bag_ids
    )

    filters_seen: dict[str, dict[str, Any]] = {}
    for uid, indexes in emp_user.items():
        segs = all_segs.get(uid) or []
        for idx in indexes:
            emp = employees[idx]
            if not isinstance(emp, dict):
                continue
            enriched = enrich_employee_with_sessions(
                emp,
                segs,
                selected_date_et=selected_date_et,
                sessions_by_id=shift_sessions,
                manual_assignments=manuals,
                now_et=now_et,
                role_filter_keys=role_filter_keys,
            )
            for sess in enriched.get("sessions") or []:
                key = str(sess.get("role_filter_key") or "")
                if key and key not in filters_seen:
                    filters_seen[key] = {
                        "key": key,
                        "category": sess.get("category"),
                        "role": sess.get("role"),
                        "label": sess.get("display_label") or key,
                        "category_code": sess.get("category_code"),
                        "role_code": sess.get("role_code"),
                    }
            # Also collect from all built roles (including filtered-out) via segments
            for seg in segs:
                key = role_filter_key(seg.get("category_code"), seg.get("role_code"))
                if key in filters_seen:
                    continue
                cat = seg.get("category_name_snapshot") or seg.get("category_code") or ""
                role = seg.get("role_name_snapshot") or seg.get("role_code") or ""
                filters_seen[key] = {
                    "key": key,
                    "category": cat,
                    "role": role,
                    "label": f"{cat} — {role}" if cat and role else key,
                    "category_code": str(seg.get("category_code") or "").upper() or None,
                    "role_code": str(seg.get("role_code") or "").upper() or None,
                }
            employees[idx] = enriched

    role_filters = list(filters_seen.values())
    role_filters.sort(
        key=lambda r: (
            0 if r.get("key") == DEFAULT_ROLE_FILTER_KEY else 1,
            str(r.get("label") or ""),
        )
    )
    if not any(r.get("key") == DEFAULT_ROLE_FILTER_KEY for r in role_filters):
        role_filters.insert(
            0,
            {
                "key": DEFAULT_ROLE_FILTER_KEY,
                "label": "Rinse WF — Folder",
                "category": "Rinse WF",
                "role": "Folder",
                "category_code": "RINSE_WF",
                "role_code": "FOLDER",
            },
        )

    base["employees"] = employees
    base["available_role_filters"] = role_filters
    base["default_role_filter_keys"] = [DEFAULT_ROLE_FILTER_KEY]
    base["session_context_enabled"] = True
    return base


def _customer_from_snapshot(raw_snap: Any) -> str | None:
    snap = raw_snap
    if isinstance(raw_snap, str) and raw_snap.strip():
        try:
            snap = json.loads(raw_snap)
        except (TypeError, ValueError):
            return None
    if not isinstance(snap, Mapping):
        return None
    return resolve_customer_name(
        snap.get("customer_name"),
        snap.get("name_clean"),
        snap.get("portal_customer_name"),
        snap.get("account_name"),
        snap.get("customer"),
        snap.get("Name_Clean"),
        snap.get("name"),
    )


def resolve_customer_names_for_bags(
    cursor,
    organization_id: int,
    bags: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date | None = None,
) -> list[dict[str, Any]]:
    """Batch-resolve customer names from the bag's authoritative sources.

    Priority (one batch per source — never N+1):
      1. Already on the bag payload
      2. Day-bag snapshot (same source that generated Step-1 bags)
      3. Portal cleaner ticket presence
      4. Bag registry name_clean
      5. Unknown Customer (last resort only)
    """
    out = [dict(b) for b in bags if isinstance(b, Mapping)]

    def _needs_lookup(name: Any) -> bool:
        return resolve_customer_name(name) is None

    missing = [
        str(b.get("bag_id") or "").strip().upper()
        for b in out
        if b.get("bag_id") and _needs_lookup(b.get("customer_name"))
    ]
    names: dict[str, str] = {}
    org = int(organization_id)

    if missing and table_exists(cursor, "rinse_shift_monitor_day_bags"):
        ph = ",".join(["%s"] * len(missing))
        args: list[Any] = [org, *missing]
        date_clause = ""
        if selected_date_et is not None:
            date_clause = " AND shift_date_et = %s"
            args.append(selected_date_et)
        cursor.execute(
            f"""
            SELECT bag_id, bag_snapshot_json
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND bag_id IN ({ph}){date_clause}
            """,
            tuple(args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            nm = _customer_from_snapshot(row.get("bag_snapshot_json"))
            if bid and nm:
                names[bid] = nm

    still = [b for b in missing if b not in names]
    if still and table_exists(cursor, "rinse_cleaner_ticket_presence"):
        ph = ",".join(["%s"] * len(still))
        cursor.execute(
            f"""
            SELECT bag_id, customer_name
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *still),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            nm = resolve_customer_name(row.get("customer_name"))
            if bid and nm:
                names[bid] = nm

    still = [b for b in missing if b not in names]
    if still and table_exists(cursor, "rinse_bag_registry"):
        ph = ",".join(["%s"] * len(still))
        cursor.execute(
            f"""
            SELECT bag_id, name_clean
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *still),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            nm = resolve_customer_name(row.get("name_clean"))
            if bid and nm:
                names[bid] = nm

    for b in out:
        bid = str(b.get("bag_id") or "").strip().upper()
        b["customer_name"] = customer_name_or_unknown(
            b.get("customer_name"),
            names.get(bid),
            b.get("name_clean"),
            b.get("portal_customer_name"),
            b.get("account_name"),
            b.get("customer"),
        )
    return out
