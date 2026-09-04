"""Canonical WF Folder Performance calculation layer (Management → Performance).

Reuses Employee Productivity / Folder dual-rate primitives:
- Evidence PRE only for lbs credit
- RINSE_WF + FOLDER shift_job_segments as session population
- Completion timestamp from day-bag productivity projection

Does NOT use Folding→Clean gaming board rates.
Does NOT manufacture Folder sessions for unmapped bags.

WF PRE pounds: same canonical current-cycle authority as Management Rinse WF
(``load_bag_weight_map`` + ``authoritative_evidence_pre_lbs``). Stale day-bag
``pre_weight_lbs`` / ``productivity_weight_lbs`` must not drive rates.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.management_wf_folder_attribution import (
    apply_override_to_bag,
    load_active_attribution_overrides,
)
from backend.management_wf_folder_fold_attribution import (
    EXCEPTION_NEEDS_ATTRIBUTION,
    EXCEPTION_OUTSIDE_FOLDER_SESSION,
    enrich_folder_performance_bags_with_oi_fold_attribution,
    is_provable_folder_employee,
)
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_employee_productivity_sessions import (
    ASSIGNMENT_NEEDS_REVIEW,
    ASSIGNMENT_UNASSIGNED,
    DEFAULT_ROLE_FILTER_KEY,
    assign_bag_to_session,
    assign_session_display_codes,
    build_payroll_session,
    customer_name_or_unknown,
    resolve_customer_names_for_bags,
)
from backend.rinse_folding_et import eastern_now
from backend.rinse_folding_folder_role_productivity import (
    CATEGORY_CODE_RINSE_WF,
    ROLE_CODE_FOLDER,
    _bag_credited_lbs_pre,
    _hours,
    _rate,
    load_day_job_segments_by_user,
    load_shift_sessions_by_id,
)
from backend.rinse_step1_productivity_fast import load_completed_productivity_day_bags

# UI presets (engine also supports full comparison set).
COMPARE_TODAY = "today"
COMPARE_SAME_WEEKDAY_LAST_WEEK = "same_weekday_last_week"
COMPARE_7D = "7d"
COMPARE_30D = "30d"
COMPARE_LAST_N = "last_n"
COMPARE_WEEK = "week"
COMPARE_PREV_WEEK = "prev_week"
COMPARE_MONTH = "month"
COMPARE_PREV_MONTH = "prev_month"
COMPARE_PREV_DAY = "prev_day"
COMPARE_CUSTOM = "custom"

DEFAULT_LAST_N_SESSIONS = 10

CREDITED_WEIGHT_BASIS_CANONICAL_PRE = "CANONICAL_CURRENT_CYCLE_PRE"


def apply_canonical_pre_to_folder_performance_bags(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bags: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay shared canonical PRE onto Folder Performance bag rows.

    Source of truth matches Management Rinse WF PRE:
    manager correction > latest portal wf_lbs_num > approved fallback
    via ``load_bag_weight_map`` / ``authoritative_evidence_pre_lbs``.

    Settled bulk-only credit stays 0 (no standard WF-lb credit).
    Does not rewrite persisted day-bag columns — read-path only.
    """
    from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs
    from backend.rinse_settled_bulk_only_weight import (
        PROD_EXCLUSION_SETTLED_BULK_ONLY,
        row_is_settled_bulk_only_for_productivity,
    )
    from backend.rinse_veewash_review import load_bag_weight_map

    out = [dict(b) for b in bags]
    ids = [normalize_bag_id(b.get("bag_id")) for b in out if normalize_bag_id(b.get("bag_id"))]
    if not ids:
        return out
    weight_map = load_bag_weight_map(
        cursor,
        int(organization_id),
        ids,
        selected_date_et=selected_date_et,
    )
    for bag in out:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        if row_is_settled_bulk_only_for_productivity(bag):
            bag["credited_weight_lbs"] = 0.0
            bag["credited_lbs"] = 0.0
            bag["credited_weight_source"] = PROD_EXCLUSION_SETTLED_BULK_ONLY
            bag["credited_weight_basis"] = CREDITED_WEIGHT_BASIS_CANONICAL_PRE
            continue
        pre = authoritative_evidence_pre_lbs(weight_map.get(bid) or {})
        if pre is None:
            bag["credited_weight_lbs"] = None
            bag["credited_lbs"] = None
            bag["missing_production_credit_weight"] = True
            bag["credited_weight_basis"] = CREDITED_WEIGHT_BASIS_CANONICAL_PRE
            continue
        pre_f = float(pre)
        bag["credited_weight_lbs"] = pre_f
        bag["credited_lbs"] = pre_f
        bag["pre_weight_lbs"] = pre_f
        bag["evidence_pre_weight_lbs"] = pre_f
        bag["credited_weight_source"] = "EVIDENCE_PRE"
        bag["pre_weight_source"] = "canonical_current_cycle_resolver"
        bag["missing_production_credit_weight"] = False
        bag["credited_weight_basis"] = CREDITED_WEIGHT_BASIS_CANONICAL_PRE
        # Drop stale projected POST-era productivity_weight so PRE keys win.
        bag.pop("productivity_weight_lbs", None)
    return out


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


def _fmt_clock(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    hour = dt.hour % 12 or 12
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour}:{dt.minute:02d} {ampm}"


def _fmt_duration_seconds(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(max(0.0, float(seconds))))
    hours, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h 00m"
    if mins and secs:
        return f"{mins}m {secs}s"
    if mins:
        return f"{mins}m"
    return f"{secs}s"


def _fmt_duration_hours(hours: float | None) -> str | None:
    if hours is None:
        return None
    return _fmt_duration_seconds(float(hours) * 3600.0)


def _pct_delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return round(((float(current) - float(baseline)) / float(baseline)) * 100.0, 1)


def resolve_comparison_window(
    *,
    anchor_date_et: date,
    compare: str,
    last_n: int = DEFAULT_LAST_N_SESSIONS,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> dict[str, Any]:
    """Reusable comparison engine window resolver."""
    key = str(compare or COMPARE_TODAY).strip().lower()
    n = max(1, int(last_n or DEFAULT_LAST_N_SESSIONS))

    if key == COMPARE_TODAY:
        return {
            "compare": COMPARE_TODAY,
            "label": "Today",
            "mode": "dates",
            "dates": [anchor_date_et],
            "date_start_et": anchor_date_et,
            "date_end_et": anchor_date_et,
        }
    if key == COMPARE_PREV_DAY:
        d = anchor_date_et - timedelta(days=1)
        return {
            "compare": COMPARE_PREV_DAY,
            "label": "Previous Day",
            "mode": "dates",
            "dates": [d],
            "date_start_et": d,
            "date_end_et": d,
        }
    if key == COMPARE_SAME_WEEKDAY_LAST_WEEK:
        d = anchor_date_et - timedelta(days=7)
        return {
            "compare": COMPARE_SAME_WEEKDAY_LAST_WEEK,
            "label": "Same Day Last Week",
            "mode": "dates",
            "dates": [d],
            "date_start_et": d,
            "date_end_et": d,
            "baseline_of": anchor_date_et.isoformat(),
        }
    if key == COMPARE_7D:
        start = anchor_date_et - timedelta(days=6)
        dates = [start + timedelta(days=i) for i in range(7)]
        return {
            "compare": COMPARE_7D,
            "label": "7 Days",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": anchor_date_et,
        }
    if key == COMPARE_30D:
        start = anchor_date_et - timedelta(days=29)
        dates = [start + timedelta(days=i) for i in range(30)]
        return {
            "compare": COMPARE_30D,
            "label": "30 Days",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": anchor_date_et,
        }
    if key == COMPARE_WEEK:
        start = anchor_date_et - timedelta(days=anchor_date_et.weekday())
        dates = [start + timedelta(days=i) for i in range(7)]
        return {
            "compare": COMPARE_WEEK,
            "label": "This Week",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": start + timedelta(days=6),
        }
    if key == COMPARE_PREV_WEEK:
        this_start = anchor_date_et - timedelta(days=anchor_date_et.weekday())
        start = this_start - timedelta(days=7)
        dates = [start + timedelta(days=i) for i in range(7)]
        return {
            "compare": COMPARE_PREV_WEEK,
            "label": "Previous Week",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": start + timedelta(days=6),
        }
    if key == COMPARE_MONTH:
        start = anchor_date_et.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        end = min(end, anchor_date_et)
        dates = []
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += timedelta(days=1)
        return {
            "compare": COMPARE_MONTH,
            "label": "This Month",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": end,
        }
    if key == COMPARE_PREV_MONTH:
        first_this = anchor_date_et.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        dates = []
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += timedelta(days=1)
        return {
            "compare": COMPARE_PREV_MONTH,
            "label": "Previous Month",
            "mode": "dates",
            "dates": dates,
            "date_start_et": start,
            "date_end_et": end,
        }
    if key == COMPARE_LAST_N:
        # Look back enough calendar days to collect N Folder sessions.
        lookback_days = max(14, n * 3)
        start = anchor_date_et - timedelta(days=lookback_days - 1)
        dates = [start + timedelta(days=i) for i in range(lookback_days)]
        return {
            "compare": COMPARE_LAST_N,
            "label": f"Last {n} Sessions",
            "mode": "last_n_sessions",
            "last_n": n,
            "dates": dates,
            "date_start_et": start,
            "date_end_et": anchor_date_et,
        }
    if key == COMPARE_CUSTOM:
        if custom_start is None or custom_end is None:
            raise ValueError("custom_start and custom_end required for custom compare")
        if custom_end < custom_start:
            custom_start, custom_end = custom_end, custom_start
        dates = []
        cur = custom_start
        while cur <= custom_end:
            dates.append(cur)
            cur += timedelta(days=1)
        return {
            "compare": COMPARE_CUSTOM,
            "label": "Custom",
            "mode": "dates",
            "dates": dates,
            "date_start_et": custom_start,
            "date_end_et": custom_end,
        }
    # Default: today
    return resolve_comparison_window(
        anchor_date_et=anchor_date_et, compare=COMPARE_TODAY, last_n=n
    )


def weighted_aggregate_rates(
    *,
    total_orders: int,
    total_pre_lbs: float,
    total_session_hours: float | None,
) -> dict[str, Any]:
    """Canonical aggregate rates — never average individual percentages."""
    hours = float(total_session_hours) if total_session_hours is not None else None
    bags_hr = _rate(total_orders, hours) if hours and hours > 0 else None
    lbs_hr = _rate(total_pre_lbs, hours) if hours and hours > 0 else None
    hours_out = round(hours, 4) if hours is not None else None
    return {
        "orders_completed": int(total_orders),
        "total_pre_lbs": round(float(total_pre_lbs), 2),
        # session_hours / total_hours: Σ credited Folder performance hours
        # (not wall-clock earliest-start → latest-end).
        "session_hours": hours_out,
        "total_hours": hours_out,
        "bags_per_hour": bags_hr,
        "lbs_per_hour": lbs_hr,
        "credited_weight_basis": "EVIDENCE_PRE",
        "aggregate_method": "weighted_totals",
    }


def compute_order_completion_timing(
    orders: Sequence[Mapping[str, Any]],
    *,
    session_start: datetime,
) -> list[dict[str, Any]]:
    """Diagnostic per-order timing from completion chronology (not Folder gaming).

    First order: completion − session start
    Subsequent: completion − previous completion
    End-of-session idle is NOT added to the final bag.
    """
    sorted_orders = sorted(
        [dict(o) for o in orders if isinstance(o, Mapping)],
        key=lambda o: (_parse_dt(o.get("completion_time") or o.get("completion_timestamp")) or datetime.min,
                       str(o.get("bag_id") or "")),
    )
    out: list[dict[str, Any]] = []
    prev_ts: datetime | None = None
    for idx, order in enumerate(sorted_orders):
        ts = _parse_dt(order.get("completion_time") or order.get("completion_timestamp"))
        time_taken_sec = None
        timing_basis = None
        if ts is not None:
            if idx == 0 or prev_ts is None:
                time_taken_sec = max(0.0, (ts - session_start).total_seconds())
                timing_basis = "session_start"
            else:
                time_taken_sec = max(0.0, (ts - prev_ts).total_seconds())
                timing_basis = "prior_completion"
            prev_ts = ts
        row = dict(order)
        row["completion_time_et"] = _iso(ts)
        row["time_taken_seconds"] = (
            int(round(time_taken_sec)) if time_taken_sec is not None else None
        )
        row["time_taken_label"] = _fmt_duration_seconds(time_taken_sec)
        row["timing_basis"] = timing_basis
        row["order_sequence"] = idx + 1
        out.append(row)
    return out


def _is_folder_segment(seg: Mapping[str, Any]) -> bool:
    cat = str(seg.get("category_code") or "").strip().upper()
    role = str(seg.get("role_code") or "").strip().upper()
    return cat == CATEGORY_CODE_RINSE_WF and role == ROLE_CODE_FOLDER


def _segment_is_open(seg: Mapping[str, Any]) -> bool:
    return _parse_dt(seg.get("ended_at")) is None


def _employee_picker_label(rinse_name: str, mapping: Mapping[str, Any] | None) -> str:
    """Show WashPro display name when it differs from the Rinse scan name."""
    rinse = str(rinse_name or "").strip()
    if not isinstance(mapping, Mapping):
        return rinse
    display = str(mapping.get("display_name") or mapping.get("user_name") or "").strip()
    if display and display.casefold() != rinse.casefold():
        return f"{display} · {rinse}"
    return rinse or display


def _build_sessions_from_segments(
    segments: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    sessions_by_id: Mapping[int, Mapping[str, Any]],
    now_et: datetime | None,
    folder_only: bool = True,
    open_only: bool = False,
    manual_destination_only: bool = False,
) -> list[dict[str, Any]]:
    segs = sorted(
        [s for s in segments if isinstance(s, Mapping)],
        key=lambda s: (_parse_dt(s.get("started_at")) or datetime.min, int(s.get("id") or 0)),
    )
    built: list[dict[str, Any]] = []
    for idx, seg in enumerate(segs):
        if folder_only and not _is_folder_segment(seg):
            continue
        if open_only and not _segment_is_open(seg):
            continue
        sid = None
        try:
            if seg.get("shift_session_id") is not None:
                sid = int(seg["shift_session_id"])
        except (TypeError, ValueError):
            sid = None
        session_row = sessions_by_id.get(sid) if sid is not None else None
        next_start = None
        if idx + 1 < len(segs):
            next_start = _parse_dt(segs[idx + 1].get("started_at"))
        payload = build_payroll_session(
            seg,
            selected_date_et=selected_date_et,
            now_et=now_et,
            session_row=session_row,
            next_segment_start=next_start,
        )
        if payload:
            if manual_destination_only:
                payload["manual_destination_only"] = True
            built.append(payload)
    coded = assign_session_display_codes(built)
    if not manual_destination_only:
        return coded
    out: list[dict[str, Any]] = []
    for payload in coded:
        role = str(payload.get("role") or payload.get("role_code") or "Role").strip()
        tr = str(payload.get("time_range_label") or "").strip()
        if role and tr and not tr.lower().startswith(role.casefold()):
            payload["time_range_label"] = f"{role} · {tr}"
            code = payload.get("session_code") or "SESSION"
            payload["option_label"] = f"{code}\n{payload['time_range_label']}"
        out.append(payload)
    return out


def _build_folder_sessions_for_user(
    segments: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    sessions_by_id: Mapping[int, Mapping[str, Any]],
    now_et: datetime | None,
) -> list[dict[str, Any]]:
    return _build_sessions_from_segments(
        segments,
        selected_date_et=selected_date_et,
        sessions_by_id=sessions_by_id,
        now_et=now_et,
        folder_only=True,
    )


def _public_destination_sessions(sessions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in sessions or []:
        out.append(
            {
                "session_id": s.get("session_id"),
                "session_code": s.get("session_code"),
                "segment_id": s.get("segment_id"),
                "time_range_label": s.get("time_range_label")
                or (
                    f"{_fmt_clock(s.get('_start_dt')) or '—'} – "
                    f"{'Open' if str(s.get('role_status') or '').lower() == 'open' else (_fmt_clock(s.get('_end_dt')) or '—')}"
                ),
                "start_time": s.get("start_time"),
                "end_time": s.get("end_time"),
                "role_status": s.get("role_status"),
                "role_code": s.get("role_code"),
                "manual_destination_only": bool(s.get("manual_destination_only")),
            }
        )
    return out


def _order_completion_ts(order: Mapping[str, Any]) -> datetime | None:
    return _parse_dt(
        order.get("completion_time_et")
        or order.get("completion_time")
        or order.get("completion_timestamp")
    )


def _latest_credited_completion_ts(orders: Sequence[Mapping[str, Any]]) -> datetime | None:
    times = [_order_completion_ts(o) for o in orders or []]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def resolve_folder_performance_window(
    sess: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Role session window vs performance rate denominator.

    OPEN: performance_end = latest credited completion (never now).
    CLOSED: performance_end = actual Folder role/session end.
    OPEN with zero completions: no performance denominator.
    """
    start = sess.get("_start_dt") or _parse_dt(sess.get("start_time"))
    role_end = sess.get("_end_dt") or _parse_dt(sess.get("end_time"))
    role_status = str(sess.get("role_status") or "").strip().lower()
    is_open = role_status == "open"
    latest = _latest_credited_completion_ts(orders)

    role_session_hours = None
    if start is not None and role_end is not None and role_end >= start:
        role_session_hours = _hours((role_end - start).total_seconds())

    performance_end = None
    performance_hours = None
    performance_basis = None

    if is_open:
        if latest is not None and start is not None and latest >= start:
            performance_end = latest
            performance_hours = _hours((latest - start).total_seconds())
            performance_basis = "last_completion"
        else:
            performance_basis = "open_no_completions"
    elif role_status == "closed":
        if start is not None and role_end is not None and role_end >= start:
            performance_end = role_end
            performance_hours = role_session_hours
            performance_basis = "session_end"

    return {
        "role_session_start": start,
        "role_session_end": role_end,
        "latest_completion": latest,
        "performance_end": performance_end,
        "role_session_hours": role_session_hours,
        "performance_hours": performance_hours,
        "performance_basis": performance_basis,
        "role_status": role_status,
    }


def _session_timing_labels(
    sess: Mapping[str, Any],
    perf: Mapping[str, Any],
) -> dict[str, str | None]:
    """Human labels separating role session window from performance denominator."""
    start = perf.get("role_session_start")
    role_end = perf.get("role_session_end")
    latest = perf.get("latest_completion")
    role_status = str(perf.get("role_status") or "")
    role_hours = perf.get("role_session_hours")
    perf_hours = perf.get("performance_hours")

    if role_status == "open":
        time_range_label = f"{_fmt_clock(start) or '—'} – Open"
        performance_through_label = (
            f"Performance through last completion: {_fmt_clock(latest)}"
            if latest is not None
            else None
        )
        duration_label = _fmt_duration_hours(perf_hours) if perf_hours else None
        return {
            "time_range_label": time_range_label,
            "performance_through_label": performance_through_label,
            "duration_label": duration_label,
        }

    end_clock = _fmt_clock(role_end) if role_end is not None else "—"
    duration_label = _fmt_duration_hours(role_hours) if role_hours else None
    time_range_label = f"{_fmt_clock(start) or '—'} – {end_clock}"
    if duration_label:
        time_range_label = f"{time_range_label} · {duration_label}"
    return {
        "time_range_label": time_range_label,
        "performance_through_label": None,
        "duration_label": duration_label,
    }


def _public_session_card(sess: Mapping[str, Any], orders: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    perf = resolve_folder_performance_window(sess, orders)
    start = perf.get("role_session_start")
    order_count = len(orders)
    pre_lbs = round(sum(_bag_credited_lbs_pre(o) for o in orders), 2)
    perf_hours = perf.get("performance_hours")
    rates = weighted_aggregate_rates(
        total_orders=order_count,
        total_pre_lbs=pre_lbs,
        total_session_hours=perf_hours,
    )
    labels = _session_timing_labels(sess, perf)
    return {
        "session_id": sess.get("session_id"),
        "session_code": sess.get("session_code"),
        "segment_id": sess.get("segment_id"),
        "employee": sess.get("employee"),
        "start_time": _iso(start),
        "end_time": _iso(perf.get("role_session_end")),
        "end_display": sess.get("end_display"),
        "time_range_label": labels["time_range_label"],
        "performance_through_label": labels["performance_through_label"],
        "duration_label": labels["duration_label"],
        "role_session_hours": perf.get("role_session_hours"),
        "performance_hours": perf_hours,
        "performance_end": _iso(perf.get("performance_end")),
        "latest_completion": _iso(perf.get("latest_completion")),
        "performance_basis": perf.get("performance_basis"),
        "session_hours": perf_hours,
        "role_status": sess.get("role_status"),
        "include_in_authoritative_aggregate": sess.get("role_status") != "unresolved",
        "orders_completed": order_count,
        "total_pre_lbs": pre_lbs,
        "bags_per_hour": rates["bags_per_hour"],
        "lbs_per_hour": rates["lbs_per_hour"],
        "credited_weight_basis": "EVIDENCE_PRE",
        "selected_date_et": sess.get("selected_date_et"),
    }


def _public_order_row(order: Mapping[str, Any]) -> dict[str, Any]:
    pre = _bag_credited_lbs_pre(order)
    return {
        "bag_id": order.get("bag_id"),
        "customer_name": customer_name_or_unknown(
            order.get("customer_name"),
            order.get("name_clean"),
            order.get("portal_customer_name"),
            order.get("account_name"),
            order.get("customer"),
        ),
        "pre_lbs": pre,
        "completion_time_et": order.get("completion_time_et")
        or order.get("completion_time")
        or order.get("completion_timestamp"),
        "time_taken_seconds": order.get("time_taken_seconds"),
        "time_taken_label": order.get("time_taken_label"),
        "timing_basis": order.get("timing_basis"),
        "order_sequence": order.get("order_sequence"),
        "credited_employee": order.get("effective_employee")
        or order.get("credited_employee")
        or order.get("employee"),
        "original_scanner": order.get("original_scanner")
        or order.get("original_employee_name"),
        "reassignment_indicator": bool(order.get("reassignment_indicator")),
        "attribution_overridden": bool(order.get("attribution_overridden")),
        "session_id": order.get("session_id"),
        "session_code": order.get("session_code"),
        "session_assignment": order.get("session_assignment"),
        "selected_date_et": order.get("selected_date_et"),
        "unmapped_reason": order.get("unmapped_reason"),
        "exception_class": order.get("exception_class"),
        "order_instance_id": order.get("order_instance_id"),
        "fold_complete_at": order.get("fold_complete_at"),
        "folder_employee_source": order.get("folder_employee_source"),
    }


def _assign_bag_into_folder_sessions(
    bag: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assign bag to Folder session; honor explicit override session when present.

    Auto-assignment uses Folder sessions only. Manual overrides may target a
    signed-in non-Folder session marked ``manual_destination_only``.
    """
    b = dict(bag)
    override_sid = b.get("override_session_id")
    auto_sessions = [s for s in sessions if not s.get("manual_destination_only")]
    if override_sid:
        assign = assign_bag_to_session(
            b,
            sessions,
            manual_override={
                "session_id": override_sid,
                "segment_id": b.get("override_segment_id"),
            },
        )
        # If override session is not among this employee's eligible sessions, unmapped.
        if assign.get("session_id") and not any(
            str(s.get("session_id")) == str(assign.get("session_id")) for s in sessions
        ):
            assign = {
                "session_id": None,
                "session_code": None,
                "session_assignment": ASSIGNMENT_UNASSIGNED,
                "session_assignment_label": "Unassigned",
                "needs_review": False,
                "unmapped_reason": "OVERRIDE_SESSION_NOT_FOLDER",
            }
        b.update(assign)
        return b

    assign = assign_bag_to_session(b, auto_sessions, manual_override=None)
    b.update(assign)
    if assign.get("session_assignment") in (ASSIGNMENT_UNASSIGNED, ASSIGNMENT_NEEDS_REVIEW):
        b["unmapped_reason"] = (
            "NEEDS_REVIEW"
            if assign.get("session_assignment") == ASSIGNMENT_NEEDS_REVIEW
            else "OUTSIDE_FOLDER_SESSION"
        )
    return b


def build_day_folder_performance(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    now_et: datetime | None = None,
    attach_customers: bool = False,
) -> dict[str, Any]:
    """Build Folder Performance for one ET day (canonical unit)."""
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps

    org = int(organization_id)
    now = now_et or eastern_now().replace(tzinfo=None)
    bags = load_completed_productivity_day_bags(
        cursor,
        org,
        selected_date_et=selected_date_et,
        include_hd=False,
        rush_filter="all",
    )
    # WF only
    bags = [
        dict(b)
        for b in bags
        if str(b.get("service_type") or b.get("service_bucket") or "").upper() == "WF"
    ]
    bags = apply_canonical_pre_to_folder_performance_bags(
        cursor, org, selected_date_et, bags
    )
    # OI-window fold gate + missing-employee fill (no resolve_current_cycle).
    bags = enrich_folder_performance_bags_with_oi_fold_attribution(
        cursor, org, selected_date_et, bags
    )
    for b in bags:
        b["selected_date_et"] = selected_date_et.isoformat()
        b["original_scanner"] = b.get("credited_employee") or b.get("employee")
        b["original_employee_name"] = b.get("original_scanner")

    overrides = load_active_attribution_overrides(
        cursor,
        org,
        selected_date_et=selected_date_et,
        bag_ids=[str(b.get("bag_id") or "") for b in bags],
    )
    attributed: list[dict[str, Any]] = []
    for bag in bags:
        bid = str(bag.get("bag_id") or "").strip().upper()
        attributed.append(apply_override_to_bag(bag, overrides.get(bid)))

    if attach_customers and attributed:
        attributed = resolve_customer_names_for_bags(
            cursor, org, attributed, selected_date_et=selected_date_et
        )

    user_maps = _load_rinse_user_maps(cursor, org)
    # Collect user ids for every effective employee that appears.
    emp_names = sorted(
        {
            str(b.get("effective_employee") or b.get("credited_employee") or "").strip()
            for b in attributed
            if is_provable_folder_employee(
                b.get("effective_employee") or b.get("credited_employee") or ""
            )
        }
    )
    # Also include employees who have Folder sessions even with zero bags.
    for name, mapping in (user_maps or {}).items():
        if mapping and mapping.get("user_id") is not None:
            # name keys are casefolded rinse names; keep map for lookup only
            pass

    name_to_uid: dict[str, int] = {}
    for emp in emp_names:
        mapping = (user_maps or {}).get(emp.casefold())
        if mapping and mapping.get("user_id") is not None:
            try:
                name_to_uid[emp] = int(mapping["user_id"])
            except (TypeError, ValueError):
                continue

    # Also load Folder segments for all mapped users (so empty sessions appear).
    all_mapped_uids: list[int] = []
    uid_to_display: dict[int, str] = {}
    for rinse_name, mapping in (user_maps or {}).items():
        if not isinstance(mapping, dict) or mapping.get("user_id") is None:
            continue
        try:
            uid = int(mapping["user_id"])
        except (TypeError, ValueError):
            continue
        all_mapped_uids.append(uid)
        # Prefer a bag's casing when available; else Rinse scan name (attribution key).
        display = next((n for n in emp_names if n.casefold() == rinse_name), None)
        uid_to_display[uid] = display or str(
            mapping.get("rinse_user_name") or mapping.get("display_name") or rinse_name
        )

    user_ids = sorted(set(all_mapped_uids) | set(name_to_uid.values()))
    segs_by_user = load_day_job_segments_by_user(
        cursor, org, user_ids, selected_date_et=selected_date_et, folder_only=False
    )
    session_ids: list[int] = []
    for segs in segs_by_user.values():
        for seg in segs:
            if seg.get("shift_session_id") is not None:
                try:
                    session_ids.append(int(seg["shift_session_id"]))
                except (TypeError, ValueError):
                    pass
    sessions_by_id = load_shift_sessions_by_id(cursor, org, session_ids)

    sessions_by_employee: dict[str, list[dict[str, Any]]] = {}
    for uid, segs in segs_by_user.items():
        display = uid_to_display.get(uid)
        if not display:
            # Find any emp name mapped to this uid
            display = next((n for n, u in name_to_uid.items() if u == uid), None)
        if not display:
            continue
        built = _build_folder_sessions_for_user(
            segs,
            selected_date_et=selected_date_et,
            sessions_by_id=sessions_by_id,
            now_et=now,
        )
        for s in built:
            s["employee"] = display
            s["selected_date_et"] = selected_date_et.isoformat()
            s["user_id"] = uid
        if built:
            sessions_by_employee[display] = built

    # Ensure employees with bags but no Folder sessions still appear for unmapped routing.
    for emp in emp_names:
        sessions_by_employee.setdefault(emp, sessions_by_employee.get(emp) or [])

    # Inject signed-in (non-Folder) sessions when an active override targets them, so
    # Move into a mapped signed-in Operator/etc. session can leave Unmapped.
    override_targets: dict[str, set[str]] = defaultdict(set)
    for bag in attributed:
        emp = str(bag.get("effective_employee") or "").strip()
        sid = bag.get("override_session_id")
        if emp and sid:
            override_targets[emp].add(str(sid))
    for emp, needed_sids in override_targets.items():
        existing = sessions_by_employee.setdefault(emp, [])
        have = {str(s.get("session_id")) for s in existing}
        missing = needed_sids - have
        if not missing:
            continue
        mapping = (user_maps or {}).get(emp.casefold())
        uid = None
        if mapping and mapping.get("user_id") is not None:
            try:
                uid = int(mapping["user_id"])
            except (TypeError, ValueError):
                uid = None
        if uid is None:
            uid = name_to_uid.get(emp)
        if uid is None:
            continue
        signed_in = _build_sessions_from_segments(
            segs_by_user.get(uid) or [],
            selected_date_et=selected_date_et,
            sessions_by_id=sessions_by_id,
            now_et=now,
            folder_only=False,
            open_only=False,
            manual_destination_only=True,
        )
        for s in signed_in:
            if str(s.get("session_id")) not in missing:
                continue
            if str(s.get("session_id")) in have:
                continue
            s["employee"] = emp
            s["selected_date_et"] = selected_date_et.isoformat()
            s["user_id"] = uid
            existing.append(s)
            have.add(str(s.get("session_id")))

    mapped_orders_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    needs_attribution: list[dict[str, Any]] = []
    outside_folder_session: list[dict[str, Any]] = []
    employee_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for bag in attributed:
        emp = str(bag.get("effective_employee") or bag.get("credited_employee") or "").strip()
        has_emp = is_provable_folder_employee(emp)
        sessions = sessions_by_employee.get(emp) or [] if has_emp else []
        assigned = _assign_bag_into_folder_sessions(bag, sessions)
        sid = assigned.get("session_id")
        if (
            has_emp
            and sid
            and assigned.get("session_assignment")
            not in (
                ASSIGNMENT_UNASSIGNED,
                ASSIGNMENT_NEEDS_REVIEW,
            )
        ):
            # Attach session code
            match = next((s for s in sessions if str(s.get("session_id")) == str(sid)), None)
            if match:
                assigned["session_code"] = match.get("session_code")
            mapped_orders_by_session[str(sid)].append(assigned)
            employee_orders[emp].append(assigned)
        elif has_emp:
            reason = assigned.get("unmapped_reason") or "OUTSIDE_FOLDER_SESSION"
            if not sessions:
                reason = "OUTSIDE_FOLDER_SESSION"
            assigned["unmapped_reason"] = reason
            assigned["exception_class"] = EXCEPTION_OUTSIDE_FOLDER_SESSION
            assigned["session_id"] = None
            outside_folder_session.append(assigned)
        else:
            assigned["unmapped_reason"] = "NEEDS_ATTRIBUTION"
            assigned["exception_class"] = EXCEPTION_NEEDS_ATTRIBUTION
            assigned["session_id"] = None
            assigned["credited_employee"] = None
            assigned["effective_employee"] = None
            needs_attribution.append(assigned)

    unmapped = needs_attribution + outside_folder_session

    # Build session cards + employee cards
    session_cards: list[dict[str, Any]] = []
    employees_out: list[dict[str, Any]] = []

    for emp, sessions in sorted(sessions_by_employee.items(), key=lambda x: x[0].casefold()):
        emp_sessions: list[dict[str, Any]] = []
        emp_orders = 0
        emp_lbs = 0.0
        perf_hours_total = 0.0
        has_perf_hours = False
        for sess in sessions:
            sid = str(sess.get("session_id") or "")
            raw_orders = mapped_orders_by_session.get(sid) or []
            start = sess.get("_start_dt") or _parse_dt(sess.get("start_time"))
            timed = (
                compute_order_completion_timing(raw_orders, session_start=start)
                if start is not None
                else list(raw_orders)
            )
            card = _public_session_card(sess, timed)
            card["employee"] = emp
            card["orders"] = [_public_order_row(o) for o in timed]
            emp_sessions.append(card)
            session_cards.append(card)
            emp_orders += int(card["orders_completed"])
            emp_lbs += float(card["total_pre_lbs"] or 0)
            if card.get("performance_hours") is not None and card.get(
                "include_in_authoritative_aggregate", True
            ):
                perf_hours_total += float(card["performance_hours"])
                has_perf_hours = True

        # Employees with Folder sessions OR mapped orders
        if not emp_sessions and emp not in employee_orders:
            continue

        rates = weighted_aggregate_rates(
            total_orders=emp_orders,
            total_pre_lbs=emp_lbs,
            total_session_hours=perf_hours_total if has_perf_hours else None,
        )
        # Time range across sessions
        starts = [_parse_dt(s.get("start_time")) for s in emp_sessions]
        starts = [t for t in starts if t]
        ends = [_parse_dt(s.get("end_time")) for s in emp_sessions]
        ends = [t for t in ends if t]
        any_open = any(s.get("role_status") == "open" for s in emp_sessions)
        employees_out.append(
            {
                "employee": emp,
                "orders_completed": emp_orders,
                "total_pre_lbs": round(emp_lbs, 2),
                "bags_per_hour": rates["bags_per_hour"],
                "lbs_per_hour": rates["lbs_per_hour"],
                "performance_hours": round(perf_hours_total, 4) if has_perf_hours else None,
                "session_hours": round(perf_hours_total, 4) if has_perf_hours else None,
                "session_count": len(emp_sessions),
                "time_range_label": (
                    f"{_fmt_clock(min(starts)) if starts else '—'} – "
                    f"{'Open' if any_open else (_fmt_clock(max(ends)) if ends else '—')}"
                ),
                "duration_label": _fmt_duration_hours(
                    perf_hours_total if has_perf_hours else None
                ),
                "sessions": emp_sessions,
                "credited_weight_basis": "EVIDENCE_PRE",
            }
        )

    # Sort employees by lbs/hr desc then orders
    employees_out.sort(
        key=lambda e: (
            -(e.get("lbs_per_hour") or 0),
            -(e.get("orders_completed") or 0),
            str(e.get("employee") or "").casefold(),
        )
    )

    total_orders = sum(int(e.get("orders_completed") or 0) for e in employees_out)
    total_lbs = round(sum(float(e.get("total_pre_lbs") or 0) for e in employees_out), 2)
    total_hours = round(
        sum(
            float(e.get("performance_hours") or e.get("session_hours") or 0)
            for e in employees_out
            if (e.get("performance_hours") is not None or e.get("session_hours") is not None)
        ),
        4,
    )
    totals = weighted_aggregate_rates(
        total_orders=total_orders,
        total_pre_lbs=total_lbs,
        total_session_hours=total_hours if total_hours > 0 else None,
    )

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "role_filter_key": DEFAULT_ROLE_FILTER_KEY,
        "credited_weight_basis": "EVIDENCE_PRE",
        "employees": employees_out,
        "sessions": session_cards,
        "needs_attribution_orders": [_public_order_row(o) for o in needs_attribution],
        "needs_attribution_count": len(needs_attribution),
        "outside_folder_session_orders": [
            _public_order_row(o) for o in outside_folder_session
        ],
        "outside_folder_session_count": len(outside_folder_session),
        # Backward-compatible union (Needs Attribution first).
        "unmapped_orders": [_public_order_row(o) for o in unmapped],
        "unmapped_count": len(unmapped),
        "summary": {
            **totals,
            "employee_count": len(employees_out),
            "session_count": len(session_cards),
            "needs_attribution_count": len(needs_attribution),
            "outside_folder_session_count": len(outside_folder_session),
            "unmapped_count": len(unmapped),
        },
        # Internal full bags for reassignment proof / destination helpers
        "_attributed_bags": attributed,
        "_unmapped_raw": unmapped,
        "_needs_attribution_raw": needs_attribution,
        "_outside_folder_session_raw": outside_folder_session,
        "_sessions_by_employee": sessions_by_employee,
    }


def _split_exception_orders(
    orders: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    needs: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    for u in orders or []:
        if not isinstance(u, Mapping):
            continue
        row = dict(u)
        cls = str(row.get("exception_class") or "").strip().lower()
        reason = str(row.get("unmapped_reason") or "").strip().upper()
        if cls == EXCEPTION_OUTSIDE_FOLDER_SESSION or reason == "OUTSIDE_FOLDER_SESSION":
            row["exception_class"] = EXCEPTION_OUTSIDE_FOLDER_SESSION
            outside.append(row)
        else:
            row["exception_class"] = EXCEPTION_NEEDS_ATTRIBUTION
            needs.append(row)
    return needs, outside


def merge_day_payloads(day_payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Weighted merge across days using Σ orders / Σ hours."""
    employees_acc: dict[str, dict[str, Any]] = {}
    all_sessions: list[dict[str, Any]] = []
    needs_attribution: list[dict[str, Any]] = []
    outside_folder_session: list[dict[str, Any]] = []

    for day in day_payloads:
        if not isinstance(day, Mapping):
            continue
        for emp in day.get("employees") or []:
            if not isinstance(emp, Mapping):
                continue
            name = str(emp.get("employee") or "").strip()
            if not name:
                continue
            slot = employees_acc.setdefault(
                name,
                {
                    "employee": name,
                    "orders_completed": 0,
                    "total_pre_lbs": 0.0,
                    "performance_hours": 0.0,
                    "session_hours": 0.0,
                    "session_count": 0,
                    "sessions": [],
                    "credited_weight_basis": "EVIDENCE_PRE",
                },
            )
            slot["orders_completed"] += int(emp.get("orders_completed") or 0)
            slot["total_pre_lbs"] = round(
                float(slot["total_pre_lbs"]) + float(emp.get("total_pre_lbs") or 0), 2
            )
            perf_h = emp.get("performance_hours")
            if perf_h is None:
                perf_h = emp.get("session_hours")
            if perf_h is not None:
                slot["performance_hours"] = round(
                    float(slot["performance_hours"]) + float(perf_h), 4
                )
                slot["session_hours"] = slot["performance_hours"]
            slot["session_count"] += int(emp.get("session_count") or 0)
            for sess in emp.get("sessions") or []:
                if isinstance(sess, Mapping):
                    slot["sessions"].append(dict(sess))
                    all_sessions.append(dict(sess))
        day_needs = day.get("needs_attribution_orders")
        day_outside = day.get("outside_folder_session_orders")
        if day_needs is None and day_outside is None:
            day_needs, day_outside = _split_exception_orders(day.get("unmapped_orders") or [])
        for u in day_needs or []:
            if isinstance(u, Mapping):
                needs_attribution.append(dict(u))
        for u in day_outside or []:
            if isinstance(u, Mapping):
                outside_folder_session.append(dict(u))

    employees_out: list[dict[str, Any]] = []
    for emp in employees_acc.values():
        rates = weighted_aggregate_rates(
            total_orders=int(emp["orders_completed"]),
            total_pre_lbs=float(emp["total_pre_lbs"]),
            total_session_hours=float(emp["performance_hours"]) if emp["performance_hours"] else None,
        )
        emp["bags_per_hour"] = rates["bags_per_hour"]
        emp["lbs_per_hour"] = rates["lbs_per_hour"]
        emp["duration_label"] = _fmt_duration_hours(emp.get("performance_hours"))
        emp["session_hours"] = emp.get("performance_hours")
        # Compact card: drop nested order arrays in multi-day merge to keep payload small
        compact_sessions = []
        for s in emp.get("sessions") or []:
            cs = {k: v for k, v in s.items() if k != "orders"}
            compact_sessions.append(cs)
        emp["sessions"] = compact_sessions
        employees_out.append(emp)

    employees_out.sort(
        key=lambda e: (
            -(e.get("lbs_per_hour") or 0),
            -(e.get("orders_completed") or 0),
            str(e.get("employee") or "").casefold(),
        )
    )

    total_orders = sum(int(e.get("orders_completed") or 0) for e in employees_out)
    total_lbs = round(sum(float(e.get("total_pre_lbs") or 0) for e in employees_out), 2)
    total_hours = round(
        sum(float(e.get("performance_hours") or e.get("session_hours") or 0) for e in employees_out),
        4,
    )
    totals = weighted_aggregate_rates(
        total_orders=total_orders,
        total_pre_lbs=total_lbs,
        total_session_hours=total_hours if total_hours > 0 else None,
    )
    unmapped = needs_attribution + outside_folder_session
    return {
        "employees": employees_out,
        "sessions": [{k: v for k, v in s.items() if k != "orders"} for s in all_sessions],
        "needs_attribution_orders": needs_attribution,
        "needs_attribution_count": len(needs_attribution),
        "outside_folder_session_orders": outside_folder_session,
        "outside_folder_session_count": len(outside_folder_session),
        "unmapped_orders": unmapped,
        "unmapped_count": len(unmapped),
        "summary": {
            **totals,
            "employee_count": len(employees_out),
            "session_count": len(all_sessions),
            "needs_attribution_count": len(needs_attribution),
            "outside_folder_session_count": len(outside_folder_session),
            "unmapped_count": len(unmapped),
        },
    }


def _limit_last_n_sessions(merged: Mapping[str, Any], last_n: int) -> dict[str, Any]:
    n = max(1, int(last_n))
    sessions = list(merged.get("sessions") or [])
    sessions.sort(
        key=lambda s: (
            str(s.get("selected_date_et") or ""),
            str(s.get("start_time") or ""),
        ),
        reverse=True,
    )
    keep = sessions[:n]
    keep_ids = {str(s.get("session_id")) for s in keep if s.get("session_id")}
    employees_out = []
    for emp in merged.get("employees") or []:
        if not isinstance(emp, Mapping):
            continue
        sess = [
            s
            for s in (emp.get("sessions") or [])
            if str(s.get("session_id")) in keep_ids
        ]
        if not sess:
            continue
        orders = sum(int(s.get("orders_completed") or 0) for s in sess)
        lbs = round(sum(float(s.get("total_pre_lbs") or 0) for s in sess), 2)
        hours = round(
            sum(
                float(s.get("performance_hours") or s.get("session_hours") or 0)
                for s in sess
                if (s.get("performance_hours") is not None or s.get("session_hours") is not None)
            ),
            4,
        )
        rates = weighted_aggregate_rates(
            total_orders=orders, total_pre_lbs=lbs, total_session_hours=hours or None
        )
        employees_out.append(
            {
                **dict(emp),
                "sessions": sess,
                "orders_completed": orders,
                "total_pre_lbs": lbs,
                "performance_hours": hours or None,
                "session_hours": hours or None,
                "session_count": len(sess),
                "bags_per_hour": rates["bags_per_hour"],
                "lbs_per_hour": rates["lbs_per_hour"],
                "duration_label": _fmt_duration_hours(hours or None),
            }
        )
    employees_out.sort(
        key=lambda e: (
            -(e.get("lbs_per_hour") or 0),
            -(e.get("orders_completed") or 0),
            str(e.get("employee") or "").casefold(),
        )
    )
    total_orders = sum(int(e.get("orders_completed") or 0) for e in employees_out)
    total_lbs = round(sum(float(e.get("total_pre_lbs") or 0) for e in employees_out), 2)
    total_hours = round(
        sum(float(e.get("session_hours") or 0) for e in employees_out if e.get("session_hours")),
        4,
    )
    totals = weighted_aggregate_rates(
        total_orders=total_orders,
        total_pre_lbs=total_lbs,
        total_session_hours=total_hours or None,
    )
    # Exception queues only for days represented in kept sessions
    keep_dates = {str(s.get("selected_date_et")) for s in keep}
    needs = [
        u
        for u in (merged.get("needs_attribution_orders") or [])
        if str(u.get("selected_date_et") or "") in keep_dates
    ]
    outside = [
        u
        for u in (merged.get("outside_folder_session_orders") or [])
        if str(u.get("selected_date_et") or "") in keep_dates
    ]
    if not needs and not outside and merged.get("unmapped_orders"):
        needs, outside = _split_exception_orders(
            [
                u
                for u in (merged.get("unmapped_orders") or [])
                if str(u.get("selected_date_et") or "") in keep_dates
            ]
        )
    unmapped = needs + outside
    return {
        "employees": employees_out,
        "sessions": keep,
        "needs_attribution_orders": needs,
        "needs_attribution_count": len(needs),
        "outside_folder_session_orders": outside,
        "outside_folder_session_count": len(outside),
        "unmapped_orders": unmapped,
        "unmapped_count": len(unmapped),
        "summary": {
            **totals,
            "employee_count": len(employees_out),
            "session_count": len(keep),
            "needs_attribution_count": len(needs),
            "outside_folder_session_count": len(outside),
            "unmapped_count": len(unmapped),
        },
    }


def build_folder_performance_dashboard(
    cursor,
    organization_id: int,
    *,
    date_et: date | None = None,
    compare: str = COMPARE_TODAY,
    last_n: int = DEFAULT_LAST_N_SESSIONS,
    custom_start: date | None = None,
    custom_end: date | None = None,
    include_baseline_delta: bool = True,
) -> dict[str, Any]:
    """Primary Management Performance payload."""
    anchor = date_et or business_today()
    window = resolve_comparison_window(
        anchor_date_et=anchor,
        compare=compare,
        last_n=last_n,
        custom_start=custom_start,
        custom_end=custom_end,
    )
    day_payloads = []
    for d in window["dates"]:
        day_payloads.append(
            build_day_folder_performance(
                cursor,
                organization_id,
                selected_date_et=d,
                attach_customers=False,
            )
        )

    if window["mode"] == "last_n_sessions":
        merged = merge_day_payloads(day_payloads)
        primary = _limit_last_n_sessions(merged, int(window.get("last_n") or last_n))
    elif len(day_payloads) == 1:
        primary = {
            k: v
            for k, v in day_payloads[0].items()
            if not str(k).startswith("_")
        }
        # Strip nested orders from list payload (lazy-load on session tap)
        slim_employees = []
        for emp in primary.get("employees") or []:
            e = dict(emp)
            slim_sessions = []
            for s in e.get("sessions") or []:
                slim_sessions.append({k: v for k, v in s.items() if k != "orders"})
            e["sessions"] = slim_sessions
            slim_employees.append(e)
        primary["employees"] = slim_employees
        primary["sessions"] = [
            {k: v for k, v in s.items() if k != "orders"} for s in (primary.get("sessions") or [])
        ]
    else:
        primary = merge_day_payloads(day_payloads)

    deltas = None
    baseline_window = None
    if include_baseline_delta and window["compare"] == COMPARE_TODAY:
        # Compact delta vs same weekday last week
        baseline_window = resolve_comparison_window(
            anchor_date_et=anchor,
            compare=COMPARE_SAME_WEEKDAY_LAST_WEEK,
        )
        base_day = build_day_folder_performance(
            cursor,
            organization_id,
            selected_date_et=baseline_window["dates"][0],
            attach_customers=False,
        )
        base_summary = base_day.get("summary") or {}
        cur_summary = primary.get("summary") or {}
        deltas = {
            "baseline_compare": COMPARE_SAME_WEEKDAY_LAST_WEEK,
            "baseline_date_et": baseline_window["dates"][0].isoformat(),
            "bags_per_hour_delta_pct": _pct_delta(
                cur_summary.get("bags_per_hour"), base_summary.get("bags_per_hour")
            ),
            "lbs_per_hour_delta_pct": _pct_delta(
                cur_summary.get("lbs_per_hour"), base_summary.get("lbs_per_hour")
            ),
        }

    return {
        "compartment": "performance",
        "surface": "wf_folder",
        "anchor_date_et": anchor.isoformat(),
        "compare": window,
        "summary": primary.get("summary"),
        "employees": primary.get("employees") or [],
        "sessions": primary.get("sessions") or [],
        "unmapped_count": int(primary.get("unmapped_count") or 0),
        "unmapped_orders": primary.get("unmapped_orders") or [],
        "needs_attribution_count": int(primary.get("needs_attribution_count") or 0),
        "needs_attribution_orders": primary.get("needs_attribution_orders") or [],
        "outside_folder_session_count": int(
            primary.get("outside_folder_session_count") or 0
        ),
        "outside_folder_session_orders": primary.get("outside_folder_session_orders")
        or [],
        "deltas": deltas,
        "credited_weight_basis": "EVIDENCE_PRE",
        "formulas": {
            "total_hours": "Σ credited Folder performance hours (session durations)",
            "bags_per_hour": "Σ mapped orders / Σ performance hours",
            "lbs_per_hour": "Σ PRE lb / Σ performance hours",
            "open_performance_end": "latest credited completion (never now)",
            "closed_performance_end": "actual Folder role/session end",
            "order_time_first": "first_completion − session_start",
            "order_time_next": "completion − previous_completion",
            "weight_basis": "EVIDENCE_PRE",
            "needs_attribution": "qualifying fold with no provable folder employee",
            "outside_folder_session": (
                "credited fold outside a valid RINSE_WF/FOLDER session"
            ),
            "folder_membership": (
                "OI-window garments-reviewed required; non-fold lifecycle "
                "completion excluded"
            ),
        },
        "ui_presets": [
            {"key": COMPARE_TODAY, "label": "Today"},
            {"key": COMPARE_SAME_WEEKDAY_LAST_WEEK, "label": "Same Day Last Week"},
            {"key": COMPARE_7D, "label": "7 Days"},
            {"key": COMPARE_30D, "label": "30 Days"},
            {"key": COMPARE_LAST_N, "label": "Last N"},
        ],
    }


def get_session_orders(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    session_id: str,
) -> dict[str, Any]:
    """Lazy session order drill-down (no full scan chronology)."""
    day = build_day_folder_performance(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        attach_customers=True,
    )
    sid = str(session_id or "").strip()
    for sess in day.get("sessions") or []:
        if str(sess.get("session_id")) == sid:
            return {
                "selected_date_et": selected_date_et.isoformat(),
                "session": {k: v for k, v in sess.items() if k != "orders"},
                "orders": sess.get("orders") or [],
            }
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "session": None,
        "orders": [],
        "error": "session_not_found",
    }


def list_move_destinations(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Move picker destinations for the selected ET day only.

    Includes mapped users who have job segments overlapping ``selected_date_et``:
    - Prefer RINSE_WF / FOLDER sessions when present
    - Otherwise offer that day's signed-in role segment(s) (e.g. Operator)

    Never lists mapped users with no activity on the selected day.
    """
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps

    org = int(organization_id)
    now = now_et or eastern_now().replace(tzinfo=None)
    user_maps = _load_rinse_user_maps(cursor, org)

    uid_to_meta: dict[int, dict[str, Any]] = {}
    for rinse_key, mapping in (user_maps or {}).items():
        if not isinstance(mapping, dict) or mapping.get("user_id") is None:
            continue
        try:
            uid = int(mapping["user_id"])
        except (TypeError, ValueError):
            continue
        rinse_name = str(mapping.get("rinse_user_name") or rinse_key).strip()
        if not rinse_name:
            continue
        # Prefer the canonical rinse name; keep first seen mapping.
        uid_to_meta.setdefault(
            uid,
            {
                "rinse_name": rinse_name,
                "mapping": mapping,
                "employee_label": _employee_picker_label(rinse_name, mapping),
            },
        )

    user_ids = sorted(uid_to_meta.keys())
    # Day-scoped: only segments overlapping selected_date_et.
    segs_by_user = load_day_job_segments_by_user(
        cursor, org, user_ids, selected_date_et=selected_date_et, folder_only=False
    )
    session_ids: list[int] = []
    for segs in segs_by_user.values():
        for seg in segs:
            if seg.get("shift_session_id") is not None:
                try:
                    session_ids.append(int(seg["shift_session_id"]))
                except (TypeError, ValueError):
                    pass
    sessions_by_id = load_shift_sessions_by_id(cursor, org, session_ids)

    destinations: list[dict[str, Any]] = []
    for uid in user_ids:
        meta = uid_to_meta[uid]
        segs = segs_by_user.get(uid) or []
        if not segs:
            # No activity on selected day → exclude (even if mapped).
            continue
        folder = _build_folder_sessions_for_user(
            segs,
            selected_date_et=selected_date_et,
            sessions_by_id=sessions_by_id,
            now_et=now,
        )
        if folder:
            sessions = folder
        else:
            # Same-day non-Folder role segments (Operator, etc.).
            sessions = _build_sessions_from_segments(
                segs,
                selected_date_et=selected_date_et,
                sessions_by_id=sessions_by_id,
                now_et=now,
                folder_only=False,
                open_only=False,
                manual_destination_only=True,
            )
        if not sessions:
            continue
        destinations.append(
            {
                "employee": meta["rinse_name"],
                "employee_label": meta["employee_label"],
                "display_name": str(
                    (meta["mapping"] or {}).get("display_name") or ""
                ).strip()
                or None,
                "sessions": _public_destination_sessions(sessions),
            }
        )

    destinations.sort(
        key=lambda d: str(d.get("employee_label") or d.get("employee") or "").casefold()
    )
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "destinations": destinations,
    }


def find_bag_attribution_context(
    day_payload: Mapping[str, Any],
    bag_id: str,
) -> dict[str, Any] | None:
    bid = str(bag_id or "").strip().upper()
    for bag in day_payload.get("_attributed_bags") or []:
        if str(bag.get("bag_id") or "").strip().upper() == bid:
            return dict(bag)
    for bag in day_payload.get("_unmapped_raw") or []:
        if str(bag.get("bag_id") or "").strip().upper() == bid:
            return dict(bag)
    for sess in day_payload.get("sessions") or []:
        for order in sess.get("orders") or []:
            if str(order.get("bag_id") or "").strip().upper() == bid:
                return dict(order)
    for order in day_payload.get("unmapped_orders") or []:
        if str(order.get("bag_id") or "").strip().upper() == bid:
            return dict(order)
    return None
