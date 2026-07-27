"""Rinse WF — Folder dual productivity averages for the Folding Performance dashboard.

Applies only to Category ``RINSE_WF`` + Role ``FOLDER`` job-tracking segments.
Does not alter Operator / HD / DHS / Drop Off productivity denominators.

Credited pounds are Evidence PRE only — never POST / authoritative POST / canonical fallback.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import (
    eastern_now,
    eastern_today,
    naive_et_day_start,
)
from backend.rinse_folding_settings import get_rinse_folding_benchmarks

CATEGORY_CODE_RINSE_WF = "RINSE_WF"
ROLE_CODE_FOLDER = "FOLDER"

# Evidence PRE only — never POST / output / authoritative / display fallbacks.
_PRE_CREDIT_KEYS = (
    "credited_weight_lbs",
    "credited_lbs",  # PRE alias used by some credit payloads
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


def _hours(seconds: float) -> float:
    return round(max(0.0, seconds) / 3600.0, 4)


def _rate(numerator: float, hours: float | None) -> float | None:
    if hours is None or hours <= 0:
        return None
    return round(float(numerator) / float(hours), 4)


def _productivity_pct(lbs_per_hour: float | None, target: float) -> float | None:
    if lbs_per_hour is None or target is None or float(target) <= 0:
        return None
    return round((float(lbs_per_hour) / float(target)) * 100.0, 1)


def _bag_completion_ts(bag: Mapping[str, Any]) -> datetime | None:
    return _parse_dt(
        bag.get("credit_timestamp")
        or bag.get("completion_time")
        or bag.get("completion_timestamp")
    )


def _bag_credited_lbs_pre(bag: Mapping[str, Any]) -> float:
    """Evidence PRE credited pounds only. POST corrections must not affect this."""
    source = str(bag.get("credited_weight_source") or bag.get("credit_weight_source") or "").upper()
    if source and source not in ("EVIDENCE_PRE", "PRE", ""):
        # Explicit non-PRE source → do not credit pounds into Folder rates.
        if "POST" in source or source in ("AUTHORITATIVE_POST", "CANONICAL", "OUTPUT"):
            return 0.0

    for key in _PRE_CREDIT_KEYS:
        raw = bag.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val >= 0:
            return val
    return 0.0


def _is_wf_bag(bag: Mapping[str, Any]) -> bool:
    return str(bag.get("service_type") or bag.get("service_bucket") or "").upper() == "WF"


def _is_rinse_wf_folder_segment(seg: Mapping[str, Any]) -> bool:
    cat = str(seg.get("category_code") or "").strip().upper()
    role = str(seg.get("role_code") or "").strip().upper()
    if cat == CATEGORY_CODE_RINSE_WF and role == ROLE_CODE_FOLDER:
        return True
    label = str(seg.get("display_label") or "").strip().casefold()
    if label == "rinse wf — folder" or label == "rinse wf - folder":
        return True
    cat_name = str(seg.get("category_name") or seg.get("category_name_snapshot") or "").strip().casefold()
    role_name = str(seg.get("role_name") or seg.get("role_name_snapshot") or "").strip().casefold()
    return cat_name == "rinse wf" and role_name == "folder"


def resolve_effective_role_end(
    *,
    role_start: datetime,
    role_end: datetime | None,
    selected_date_et: date,
    now_et: datetime | None = None,
    session_clock_out: datetime | None = None,
    next_segment_start: datetime | None = None,
) -> dict[str, Any]:
    """Resolve effective Folder role end without silently extending to midnight.

    Priority:
    1. explicit role segment end
    2. attendance session / checkout end
    3. next role segment start (any category/role), when after role start
    4. current ET time only for an open segment on the current ET day

    Historical unresolved open → role_end_missing, provisional, no midnight cap.
    """
    today = eastern_today()
    now = now_et or eastern_now().replace(tzinfo=None)

    closed_end = role_end if role_end is not None and role_end >= role_start else None
    if closed_end is not None:
        return {
            "effective_end": closed_end,
            "role_status": "closed",
            "role_end_missing": False,
            "rates_provisional": False,
            "include_in_authoritative_aggregate": True,
            "end_source": "segment_end",
        }

    if session_clock_out is not None and session_clock_out >= role_start:
        return {
            "effective_end": session_clock_out,
            "role_status": "closed",
            "role_end_missing": False,
            "rates_provisional": False,
            "include_in_authoritative_aggregate": True,
            "end_source": "session_checkout",
        }

    if next_segment_start is not None and next_segment_start > role_start:
        return {
            "effective_end": next_segment_start,
            "role_status": "closed",
            "role_end_missing": False,
            "rates_provisional": False,
            "include_in_authoritative_aggregate": True,
            "end_source": "next_segment_start",
        }

    if selected_date_et == today:
        live = max(role_start, now)
        return {
            "effective_end": live,
            "role_status": "open",
            "role_end_missing": False,
            "rates_provisional": False,
            "include_in_authoritative_aggregate": True,
            "end_source": "current_et_now",
        }

    # Historical / future with no defensible end — do NOT use midnight.
    return {
        "effective_end": None,
        "role_status": "unresolved",
        "role_end_missing": True,
        "rates_provisional": True,
        "include_in_authoritative_aggregate": False,
        "end_source": None,
    }


def bags_in_segment_window(
    bags: Sequence[Mapping[str, Any]],
    *,
    role_start: datetime,
    effective_end: datetime | None,
    claimed_bag_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Eligible WF bags in [start, end]. Each bag id claimed at most once across segments."""
    claimed = claimed_bag_ids if claimed_bag_ids is not None else set()
    out: list[dict[str, Any]] = []
    if effective_end is None:
        return out
    for bag in bags or []:
        if not isinstance(bag, Mapping):
            continue
        if not _is_wf_bag(bag):
            continue
        bid = str(bag.get("bag_id") or "").strip().upper()
        if bid and bid in claimed:
            continue
        ts = _bag_completion_ts(bag)
        if ts is None:
            continue
        if ts < role_start or ts > effective_end:
            continue
        out.append(dict(bag))
        if bid:
            claimed.add(bid)
    return out


# Backward-compatible alias used by older tests/callers.
def bags_in_segment(
    bags: Sequence[Mapping[str, Any]],
    *,
    role_start: datetime,
    effective_end: datetime,
) -> list[dict[str, Any]]:
    return bags_in_segment_window(
        bags, role_start=role_start, effective_end=effective_end, claimed_bag_ids=None
    )


def compute_folder_segment_dual_productivity(
    *,
    role_start: datetime,
    role_end: datetime | None,
    bags: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    folding_target_lbs_per_hour: float,
    now_et: datetime | None = None,
    segment_id: Any = None,
    session_clock_out: datetime | None = None,
    next_segment_start: datetime | None = None,
    claimed_bag_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Dual averages for one Rinse WF — Folder role segment."""
    end_info = resolve_effective_role_end(
        role_start=role_start,
        role_end=role_end,
        selected_date_et=selected_date_et,
        now_et=now_et,
        session_clock_out=session_clock_out,
        next_segment_start=next_segment_start,
    )
    effective_end = end_info["effective_end"]
    role_end_missing = bool(end_info["role_end_missing"])
    provisional = bool(end_info["rates_provisional"])
    include_agg = bool(end_info["include_in_authoritative_aggregate"])
    role_status = str(end_info["role_status"])

    if effective_end is None or role_end_missing:
        role_hours = None
        eligible: list[dict[str, Any]] = []
        # Still claim nothing; bags may belong to a later resolved segment.
        bag_count = 0
        credited_lbs = 0.0
        first_ts = None
        last_ts = None
        active_hours = 0.0
        active_bags_hr = None
        active_lbs_hr = None
        active_pct = None
        idle_hours = None
        active_completion_end = None
        role_bags_hr = None
        role_lbs_hr = None
        role_pct = None
    else:
        role_hours = _hours((effective_end - role_start).total_seconds())
        eligible = bags_in_segment_window(
            bags,
            role_start=role_start,
            effective_end=effective_end,
            claimed_bag_ids=claimed_bag_ids,
        )
        eligible.sort(key=lambda b: _bag_completion_ts(b) or datetime.min)
        bag_count = len(eligible)
        credited_lbs = round(sum(_bag_credited_lbs_pre(b) for b in eligible), 2)
        first_ts = _bag_completion_ts(eligible[0]) if eligible else None
        last_ts = _bag_completion_ts(eligible[-1]) if eligible else None

        if bag_count == 0 or last_ts is None:
            # No qualifying bag: last-bag elapsed/idle/rates are null — do not
            # classify the entire role segment as idle without separate approval.
            active_hours = None
            active_bags_hr = None
            active_lbs_hr = None
            active_pct = None
            idle_hours = None
            active_completion_end = None
        else:
            active_sec = max(0.0, (last_ts - role_start).total_seconds())
            active_hours = _hours(active_sec)
            if active_hours <= 0:
                active_bags_hr = None
                active_lbs_hr = None
                active_pct = None
            else:
                active_bags_hr = _rate(bag_count, active_hours)
                active_lbs_hr = _rate(credited_lbs, active_hours)
                active_pct = _productivity_pct(active_lbs_hr, folding_target_lbs_per_hour)
            idle_hours = round(float(role_hours) - float(active_hours), 4)
            if idle_hours < 0:
                idle_hours = 0.0
            active_completion_end = last_ts

        role_bags_hr = _rate(bag_count, role_hours) if role_hours and role_hours > 0 else None
        role_lbs_hr = _rate(credited_lbs, role_hours) if role_hours and role_hours > 0 else None
        role_pct = _productivity_pct(role_lbs_hr, folding_target_lbs_per_hour)

    return {
        "segment_id": segment_id,
        "segment_start": role_start.isoformat(),
        "segment_end": role_end.isoformat() if role_end is not None else None,
        "segment_end_or_open": (
            "Unresolved"
            if role_end_missing
            else (role_end.isoformat() if role_end is not None else "Open")
        ),
        "effective_role_end": effective_end.isoformat() if effective_end else None,
        "end_source": end_info.get("end_source"),
        "role_status": role_status,
        "role_end_missing": role_end_missing,
        "rates_provisional": provisional,
        "include_in_authoritative_aggregate": include_agg,
        "completed_bags": bag_count,
        "credited_lbs": credited_lbs,
        "credited_weight_basis": "EVIDENCE_PRE",
        "active_completion_end": active_completion_end.isoformat() if active_completion_end else None,
        "role_hours": role_hours,
        "active_completion_hours": (
            None if role_end_missing else active_hours
        ),
        "idle_time_hours": idle_hours,
        "role_bags_per_hour": role_bags_hr,
        "role_lbs_per_hour": role_lbs_hr,
        "role_productivity_pct": role_pct,
        "active_bags_per_hour": active_bags_hr,
        "active_lbs_per_hour": active_lbs_hr,
        "active_productivity_pct": active_pct,
        "first_completed": first_ts.isoformat() if first_ts else None,
        "last_completed": last_ts.isoformat() if last_ts else None,
        "eligible_bag_ids": [str(b.get("bag_id") or "").upper() for b in eligible if b.get("bag_id")],
    }


def aggregate_folder_dual_productivity(
    segment_results: Sequence[Mapping[str, Any]],
    *,
    folding_target_lbs_per_hour: float,
) -> dict[str, Any] | None:
    """Aggregate Folder segments using summed numerators/denominators.

    Segments with ``include_in_authoritative_aggregate=False`` (historical unresolved
    open) are excluded from authoritative hours and rate denominators.
    """
    segs = [dict(s) for s in segment_results or [] if isinstance(s, Mapping)]
    if not segs:
        return None

    authoritative = [s for s in segs if s.get("include_in_authoritative_aggregate", True)]
    provisional_any = any(bool(s.get("rates_provisional") or s.get("role_end_missing")) for s in segs)
    missing_any = any(bool(s.get("role_end_missing")) for s in segs)

    total_role_hours = round(
        sum(float(s.get("role_hours") or 0) for s in authoritative if s.get("role_hours") is not None),
        4,
    )
    active_vals = [
        float(s["active_completion_hours"])
        for s in authoritative
        if s.get("active_completion_hours") is not None
    ]
    total_active_hours = round(sum(active_vals), 4) if active_vals else 0.0
    idle_vals = [
        float(s["idle_time_hours"])
        for s in authoritative
        if s.get("idle_time_hours") is not None
    ]
    total_idle = round(sum(idle_vals), 4) if idle_vals else None
    total_bags = sum(int(s.get("completed_bags") or 0) for s in authoritative)
    total_lbs = round(sum(float(s.get("credited_lbs") or 0) for s in authoritative), 2)

    role_bags_hr = _rate(total_bags, total_role_hours) if total_role_hours > 0 else None
    role_lbs_hr = _rate(total_lbs, total_role_hours) if total_role_hours > 0 else None
    role_pct = _productivity_pct(role_lbs_hr, folding_target_lbs_per_hour)

    if total_bags <= 0 or total_active_hours <= 0:
        active_bags_hr = None
        active_lbs_hr = None
        active_pct = None
    else:
        active_bags_hr = _rate(total_bags, total_active_hours)
        active_lbs_hr = _rate(total_lbs, total_active_hours)
        active_pct = _productivity_pct(active_lbs_hr, folding_target_lbs_per_hour)

    starts = [_parse_dt(s.get("segment_start")) for s in segs]
    starts = [t for t in starts if t is not None]
    ends = [
        _parse_dt(s.get("effective_role_end") or s.get("segment_end"))
        for s in segs
        if not s.get("role_end_missing")
    ]
    ends = [t for t in ends if t is not None]
    any_open = any(str(s.get("role_status") or "") == "open" for s in segs)
    any_unresolved = any(str(s.get("role_status") or "") == "unresolved" for s in segs)

    firsts = [_parse_dt(s.get("first_completed")) for s in authoritative]
    firsts = [t for t in firsts if t is not None]
    lasts = [_parse_dt(s.get("last_completed")) for s in authoritative]
    lasts = [t for t in lasts if t is not None]

    if any_unresolved and not any_open:
        role_status = "unresolved"
        end_display = "Unresolved"
        folder_role_end = None
    elif any_open:
        role_status = "open"
        end_display = "Open"
        folder_role_end = None
    else:
        role_status = "closed"
        folder_role_end = max(ends).isoformat() if ends else None
        end_display = folder_role_end

    return {
        "folder_role_dual_productivity": True,
        "folding_lbs_per_hour_target": float(folding_target_lbs_per_hour),
        "credited_weight_basis": "EVIDENCE_PRE",
        "role_hours": total_role_hours if authoritative else None,
        "active_completion_hours": total_active_hours,
        "idle_time_hours": total_idle,
        "completed_bags": total_bags,
        "credited_lbs": total_lbs,
        "role_bags_per_hour": role_bags_hr,
        "role_lbs_per_hour": role_lbs_hr,
        "role_productivity_pct": role_pct,
        "active_bags_per_hour": active_bags_hr,
        "active_lbs_per_hour": active_lbs_hr,
        "active_productivity_pct": active_pct,
        "folder_role_start": min(starts).isoformat() if starts else None,
        "folder_role_end": folder_role_end,
        "folder_role_end_display": end_display,
        "first_completed": min(firsts).isoformat() if firsts else None,
        "last_completed": max(lasts).isoformat() if lasts else None,
        "role_status": role_status,
        "role_end_missing": missing_any,
        "rates_provisional": provisional_any,
        "folder_role_segments": segs,
        "segment_count": len(segs),
        "authoritative_segment_count": len(authoritative),
    }


def _session_clock_out_for_segment(
    seg: Mapping[str, Any],
    sessions_by_id: Mapping[int, Mapping[str, Any]] | None,
) -> datetime | None:
    if not sessions_by_id:
        return None
    sid = seg.get("shift_session_id")
    if sid is None:
        return None
    try:
        session = sessions_by_id.get(int(sid))
    except (TypeError, ValueError):
        return None
    if not session:
        return None
    return _parse_dt(session.get("clock_out_at") or session.get("clock_out_time"))


def compute_employee_folder_dual_productivity(
    *,
    segments: Sequence[Mapping[str, Any]],
    bags: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    folding_target_lbs_per_hour: float,
    now_et: datetime | None = None,
    all_day_segments: Sequence[Mapping[str, Any]] | None = None,
    sessions_by_id: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Compute dual productivity across all Rinse WF — Folder segments for one employee.

    ``all_day_segments`` (any category/role) supplies next-segment-start bounds.
    Each bag is attributed to at most one Folder segment.
    """
    folder_segs = [s for s in segments or [] if _is_rinse_wf_folder_segment(s)]
    if not folder_segs:
        return None

    timeline = list(all_day_segments) if all_day_segments is not None else list(segments or [])
    timeline_sorted = sorted(
        [s for s in timeline if _parse_dt(s.get("started_at") or s.get("segment_start"))],
        key=lambda s: (
            _parse_dt(s.get("started_at") or s.get("segment_start")) or datetime.min,
            int(s.get("id") or s.get("segment_id") or 0),
        ),
    )

    folder_sorted = sorted(
        folder_segs,
        key=lambda s: (
            _parse_dt(s.get("started_at") or s.get("segment_start")) or datetime.min,
            int(s.get("id") or s.get("segment_id") or 0),
        ),
    )

    claimed: set[str] = set()
    results: list[dict[str, Any]] = []
    for seg in folder_sorted:
        start = _parse_dt(seg.get("started_at") or seg.get("segment_start") or seg.get("start"))
        if start is None:
            continue
        end = _parse_dt(seg.get("ended_at") or seg.get("segment_end") or seg.get("end"))
        seg_id = seg.get("id") or seg.get("segment_id")

        next_start: datetime | None = None
        for other in timeline_sorted:
            other_id = other.get("id") or other.get("segment_id")
            if seg_id is not None and other_id is not None and other_id == seg_id:
                continue
            other_start = _parse_dt(other.get("started_at") or other.get("segment_start"))
            if other_start is not None and other_start > start:
                next_start = other_start
                break

        results.append(
            compute_folder_segment_dual_productivity(
                role_start=start,
                role_end=end,
                bags=bags,
                selected_date_et=selected_date_et,
                folding_target_lbs_per_hour=folding_target_lbs_per_hour,
                now_et=now_et,
                segment_id=seg_id,
                session_clock_out=_session_clock_out_for_segment(seg, sessions_by_id),
                next_segment_start=next_start,
                claimed_bag_ids=claimed,
            )
        )
    return aggregate_folder_dual_productivity(
        results, folding_target_lbs_per_hour=folding_target_lbs_per_hour
    )


def load_shift_sessions_by_id(
    cursor,
    organization_id: int,
    session_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    from backend.ta_helpers import table_exists

    ids = sorted({int(i) for i in session_ids if i})
    if not ids or not table_exists(cursor, "shift_sessions"):
        return {}
    org = int(organization_id)
    out: dict[int, dict[str, Any]] = {}
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, user_id, clock_in_at, clock_out_at, status
        FROM shift_sessions
        WHERE organization_id = %s AND id IN ({ph})
        """,
        (org, *ids),
    )
    for row in cursor.fetchall() or []:
        if isinstance(row, dict) and row.get("id") is not None:
            out[int(row["id"])] = dict(row)
    return out


def load_day_job_segments_by_user(
    cursor,
    organization_id: int,
    user_ids: Sequence[int],
    *,
    selected_date_et: date,
    folder_only: bool = False,
) -> dict[int, list[dict[str, Any]]]:
    """Load shift_job_segments overlapping the selected ET day (optionally Folder-only)."""
    from backend.ta_helpers import table_exists

    ids = sorted({int(u) for u in user_ids if u})
    out: dict[int, list[dict[str, Any]]] = {uid: [] for uid in ids}
    if not ids or not table_exists(cursor, "shift_job_segments"):
        return out
    if not table_exists(cursor, "shift_sessions"):
        return out

    day_start = naive_et_day_start(selected_date_et)
    day_end_excl = day_start + timedelta(days=1)
    org = int(organization_id)
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        folder_filter = ""
        args: list[Any] = [org, *part, day_end_excl, day_start]
        if folder_only:
            folder_filter = (
                " AND UPPER(COALESCE(sjs.category_code, '')) = %s"
                " AND UPPER(COALESCE(sjs.role_code, '')) = %s"
            )
            args.extend([CATEGORY_CODE_RINSE_WF, ROLE_CODE_FOLDER])
        cursor.execute(
            f"""
            SELECT sjs.id, sjs.shift_session_id, sjs.user_id,
                   sjs.category_id, sjs.role_id, sjs.category_role_id,
                   sjs.category_code, sjs.role_code,
                   sjs.category_name_snapshot, sjs.role_name_snapshot,
                   sjs.started_at, sjs.ended_at
            FROM shift_job_segments sjs
            JOIN shift_sessions ss ON ss.id = sjs.shift_session_id
            WHERE ss.organization_id = %s
              AND sjs.user_id IN ({placeholders})
              AND sjs.started_at < %s
              AND (sjs.ended_at IS NULL OR sjs.ended_at >= %s)
              {folder_filter}
            ORDER BY sjs.user_id ASC, sjs.started_at ASC, sjs.id ASC
            """,
            tuple(args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            uid = int(row["user_id"])
            if uid not in out:
                continue
            r = dict(row)
            cat = r.get("category_name_snapshot")
            role = r.get("role_name_snapshot")
            if cat and role:
                r["display_label"] = f"{cat} — {role}"
            out[uid].append(r)
    return out


def load_rinse_wf_folder_segments_by_user(
    cursor,
    organization_id: int,
    user_ids: Sequence[int],
    *,
    selected_date_et: date,
) -> dict[int, list[dict[str, Any]]]:
    return load_day_job_segments_by_user(
        cursor,
        organization_id,
        user_ids,
        selected_date_et=selected_date_et,
        folder_only=True,
    )


def _resolve_user_id_for_employee(
    employee_name: str,
    user_maps: Mapping[str, Mapping[str, Any]] | None,
) -> int | None:
    if not employee_name or not user_maps:
        return None
    mapping = user_maps.get(str(employee_name).casefold())
    if not mapping or mapping.get("user_id") is None:
        return None
    try:
        return int(mapping["user_id"])
    except (TypeError, ValueError):
        return None


def apply_folder_dual_productivity_to_section(
    cursor,
    organization_id: int,
    section: Mapping[str, Any] | None,
    *,
    selected_date_et: date,
    user_maps: Mapping[str, Mapping[str, Any]] | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Enrich Folding Performance employees that have Rinse WF — Folder segments.

    Employees without Folder segments (Operator, HD, etc.) are left byte-for-byte
    unchanged aside from shallow dict copies of the section list structure.
    """
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps

    base = dict(section or {})
    employees_in = list(base.get("employees") or [])
    employees: list[Any] = []
    for e in employees_in:
        employees.append(dict(e) if isinstance(e, Mapping) else e)
    if not employees:
        base["employees"] = employees
        return base

    org = int(organization_id)
    maps = user_maps or _load_rinse_user_maps(cursor, org)
    benchmarks = get_rinse_folding_benchmarks(cursor, org)
    target = float(benchmarks.get("lbs_per_hour_target") or 40.0)

    user_ids: list[int] = []
    emp_user: dict[int, list[int]] = {}
    for idx, emp in enumerate(employees):
        if not isinstance(emp, dict):
            continue
        uid = _resolve_user_id_for_employee(str(emp.get("employee") or ""), maps)
        if uid is None:
            continue
        user_ids.append(uid)
        emp_user.setdefault(uid, []).append(idx)

    all_segs_by_user = load_day_job_segments_by_user(
        cursor, org, user_ids, selected_date_et=selected_date_et, folder_only=False
    )
    session_ids: list[int] = []
    for segs in all_segs_by_user.values():
        for seg in segs:
            if seg.get("shift_session_id") is not None:
                try:
                    session_ids.append(int(seg["shift_session_id"]))
                except (TypeError, ValueError):
                    pass
    sessions_by_id = load_shift_sessions_by_id(cursor, org, session_ids)

    for uid, indexes in emp_user.items():
        all_segs = all_segs_by_user.get(uid) or []
        folder_segs = [s for s in all_segs if _is_rinse_wf_folder_segment(s)]
        if not folder_segs:
            continue
        for idx in indexes:
            emp = employees[idx]
            if not isinstance(emp, dict):
                continue
            # Snapshot pre-enrichment employee for non-Folder isolation audits.
            bags = emp.get("bags") or emp.get("workload_bags") or []
            dual = compute_employee_folder_dual_productivity(
                segments=folder_segs,
                bags=bags,
                selected_date_et=selected_date_et,
                folding_target_lbs_per_hour=target,
                now_et=now_et,
                all_day_segments=all_segs,
                sessions_by_id=sessions_by_id,
            )
            if not dual:
                continue
            emp["folder_role_dual_productivity"] = True
            emp["folding_lbs_per_hour_target"] = dual["folding_lbs_per_hour_target"]
            emp["credited_weight_basis"] = "EVIDENCE_PRE"
            emp["role_hours"] = dual["role_hours"]
            emp["active_completion_hours"] = dual["active_completion_hours"]
            emp["idle_time_hours"] = dual["idle_time_hours"]
            emp["role_bags_per_hour"] = dual["role_bags_per_hour"]
            emp["role_lbs_per_hour"] = dual["role_lbs_per_hour"]
            emp["role_productivity_pct"] = dual["role_productivity_pct"]
            emp["active_bags_per_hour"] = dual["active_bags_per_hour"]
            emp["active_lbs_per_hour"] = dual["active_lbs_per_hour"]
            emp["active_productivity_pct"] = dual["active_productivity_pct"]
            emp["folder_role_start"] = dual["folder_role_start"]
            emp["folder_role_end"] = dual["folder_role_end"]
            emp["folder_role_end_display"] = dual["folder_role_end_display"]
            emp["folder_first_completed"] = dual["first_completed"]
            emp["folder_last_completed"] = dual["last_completed"]
            emp["role_status"] = dual["role_status"]
            emp["role_end_missing"] = dual.get("role_end_missing", False)
            emp["rates_provisional"] = dual.get("rates_provisional", False)
            emp["folder_credited_lbs"] = dual["credited_lbs"]
            emp["folder_completed_bags"] = dual["completed_bags"]
            emp["folder_role_segments"] = dual["folder_role_segments"]
            emp["folder_segment_count"] = dual["segment_count"]
            # Preserve legacy fields; dual values are authoritative for Folder rows.
            emp["legacy_productive_hours"] = emp.get("productive_hours")
            if dual.get("role_hours") is not None and not dual.get("rates_provisional"):
                emp["productive_hours"] = dual["role_hours"]
                emp["worked_hours"] = dual["role_hours"]
            emp["legacy_completed_bags_per_hour"] = emp.get("completed_bags_per_hour") or emp.get(
                "bags_per_hour"
            )
            emp["legacy_completed_lbs_per_hour"] = emp.get("completed_lbs_per_hour") or emp.get(
                "lbs_per_hour"
            )
            employees[idx] = emp

    base["employees"] = employees
    base["folder_dual_productivity_enabled"] = True
    base["folding_lbs_per_hour_target"] = target
    return base
