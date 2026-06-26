"""Employee completed bags today — productivity attribution for At Vendor workload.

PHASE 1 FROZEN — bug fixes only. Phase 2 UI reads this module as single source of truth.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_assembly_printed_ct_purpose,
    is_complete_cleaning_purpose,
    is_fold_block_split_purpose,
    is_operator_upstream_processing_purpose,
    is_sent_to_vendor_purpose,
    is_weight_entry_purpose,
    is_wf_folding_pipeline_purpose,
    normalize_scan_purpose,
)
from backend.rinse_wf_weight_events import (
    _latest_wf_processing_after_anchor,
    _post_processing_weight_events,
    distinct_wf_weight_events,
    parse_weight_lbs_from_scan_event,
)

UNKNOWN_EMPLOYEE = "Unknown user"
PRODUCTIVITY_END_LAST_COMPLETION = "last_completion"
PRODUCTIVITY_END_CLOCK_OUT = "clock_out"
PRODUCTIVITY_START_CLOCK_IN = "clock_in"
PRODUCTIVITY_START_OPERATOR_PROCESSING = "operator_processing"
PRODUCTIVITY_START_INFERRED_FOLD = "inferred_fold_start"
FOLD_BLOCK_START_CLOCK_IN = "clock_in"
FOLD_BLOCK_START_PRIOR_SCAN = "prior_work_scan"
FOLD_BLOCK_END_LAST_COMPLETION = "last_completion"
FOLD_BLOCK_END_CLOCK_OUT = "clock_out"
# When summed micro-block durations fall below this fraction of the continuous span,
# use the continuous folding start → end window for productive hours (single block only).
FOLDING_CONTINUOUS_SPAN_MIN_FRACTION = 0.5
# Split folding blocks when completions are separated by a long gap with no WF pipeline work.
FOLDING_INACTIVE_GAP_SECONDS = 60 * 60


def _normalize_employee(raw: Any) -> str:
    text = str(raw or "").strip()
    return text or UNKNOWN_EMPLOYEE


def _event_user_name(ev: Mapping[str, Any]) -> str:
    return _normalize_employee(ev.get("user_name") or ev.get("user"))


def _is_hd_completion_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return (
        is_complete_cleaning_purpose(raw)
        or is_assembly_printed_ct_purpose(raw)
        or "garments-reviewed" in p
    )


def _hd_completion_event(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> dict[str, Any] | None:
    from backend.rinse_at_vendor_module import _hd_completion_signal
    from backend.rinse_bag_activity_rules import unique_occurrence_times

    signal, comp_ts = _hd_completion_signal(
        timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
    )
    if comp_ts is None:
        return None

    anchored = [ev for ev in timeline if event_ts(ev) and anchor_ts <= event_ts(ev) <= as_of_end]
    if signal == "second add-photos":
        add_photos = unique_occurrence_times(anchored, is_add_photos_purpose)
        if len(add_photos) >= 2:
            return dict(add_photos[1][0])
    for ev in anchored:
        if event_ts(ev) == comp_ts and _is_hd_completion_purpose(ev.get("purpose")):
            return dict(ev)
        if event_ts(ev) == comp_ts and is_add_photos_purpose(ev.get("purpose")) and signal == "second add-photos":
            return dict(ev)
    for ev in anchored:
        if event_ts(ev) == comp_ts:
            return dict(ev)
    return None


def _wf_completion_weight_event(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> tuple[dict[str, Any] | None, datetime | None]:
    latest_proc, _ = _latest_wf_processing_after_anchor(
        timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
    )
    if latest_proc is None:
        return None, None
    weights = distinct_wf_weight_events(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
    post = _post_processing_weight_events(weights, latest_proc)
    if not post:
        return None, None
    last = post[-1]
    return dict(last.event), last.timestamp


def _attribution_reason(service_type: str, signal: str | None) -> str:
    svc = str(service_type or "").upper()
    if svc == "WF":
        return "WF: user on post-clean weight-entry scan (post_processing_weight)"
    if svc == "HD":
        sig = signal or "hd-completion"
        return f"HD: user on completion signal scan ({sig})"
    return "Unknown service type — no attribution rule"


def resolve_completion_attribution(
    *,
    service_type: str,
    events: Sequence[Mapping[str, Any]],
    anchor_ts: datetime | None,
    as_of_end: datetime,
) -> tuple[str, datetime | None, str | None]:
    """Return (employee, completion_ts, completion_signal)."""
    if anchor_ts is None or not ts_valid(anchor_ts):
        return UNKNOWN_EMPLOYEE, None, None
    timeline = gaming_events_from_records(events)
    svc = str(service_type or "").upper()
    if svc == "WF":
        ev, comp_ts = _wf_completion_weight_event(
            timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
        )
        if ev is None or comp_ts is None:
            return UNKNOWN_EMPLOYEE, None, None
        return _event_user_name(ev), comp_ts, "post_processing_weight"
    if svc == "HD":
        ev = _hd_completion_event(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
        if ev is None:
            return UNKNOWN_EMPLOYEE, None, None
        comp_ts = event_ts(ev)
        if not ts_valid(comp_ts):
            return UNKNOWN_EMPLOYEE, None, None
        sig = normalize_scan_purpose(ev.get("purpose")) or "hd-completion"
        if is_add_photos_purpose(ev.get("purpose")):
            sig = "second add-photos"
        return _event_user_name(ev), comp_ts, sig
    return UNKNOWN_EMPLOYEE, None, None


def _resolve_anchor_ts(events: Sequence[Mapping[str, Any]], selected_date_et: date) -> datetime | None:
    from backend.rinse_at_vendor_module import _resolve_selected_day_anchor_ts

    return _resolve_selected_day_anchor_ts(events, selected_date_et)


def _build_roster_role_lookup(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, str]:
    from backend.daily_shift_roster import build_roster_role_lookup, list_roster_entries

    entries = list_roster_entries(cursor, int(organization_id), roster_date=selected_date_et)
    return build_roster_role_lookup(entries)


def _actual_clock_out_from_sessions(sessions: Sequence[Mapping[str, Any]]) -> datetime | None:
    outs = [
        sh.get("clock_out_at")
        for sh in sessions
        if isinstance(sh, Mapping) and isinstance(sh.get("clock_out_at"), datetime)
    ]
    return max(outs) if outs else None


def _load_upstream_processing_scan_times_bulk(
    cursor,
    organization_id: int,
    rinse_user_names: Sequence[str],
    selected_date_et: date,
) -> dict[str, list[datetime]]:
    from backend.ta_helpers import table_exists

    names = sorted({str(n).strip() for n in rinse_user_names if str(n).strip()})
    if not names or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}

    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(selected_date_et, selected_date_et)
    end_exclusive = naive_et_day_end_exclusive(selected_date_et)
    out: dict[str, list[datetime]] = {n.casefold(): [] for n in names}
    chunk = 100
    for i in range(0, len(names), chunk):
        part = names[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT user_name, purpose, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed < %s
              AND user_name IN ({placeholders})
            """,
            (org, start_dt, end_exclusive, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            if not is_operator_upstream_processing_purpose(row.get("purpose")):
                continue
            ts = row.get("scanned_at_parsed")
            if not isinstance(ts, datetime):
                continue
            uname = str(row.get("user_name") or "").strip().casefold()
            if uname in out:
                out[uname].append(ts)
    return out


def _last_scan_before(timestamps: Sequence[datetime], before: datetime) -> datetime | None:
    candidates = [ts for ts in timestamps if ts < before]
    return max(candidates) if candidates else None


def _has_wf_pipeline_between(
    start: datetime,
    end: datetime,
    wf_pipeline: Sequence[datetime],
) -> bool:
    return any(start < ts < end for ts in wf_pipeline if ts_valid(ts))


def _has_wf_pipeline_in_inactive_gap_core(
    prev_completion: datetime,
    next_completion: datetime,
    wf_pipeline: Sequence[datetime],
) -> bool:
    """True when WF pipeline work occurred in the middle of a long inter-completion gap."""
    if next_completion <= prev_completion:
        return False
    gap = next_completion - prev_completion
    margin = min(timedelta(minutes=45), gap / 2)
    core_start = prev_completion + margin
    core_end = next_completion - margin
    if core_end <= core_start:
        return False
    return _has_wf_pipeline_between(core_start, core_end, wf_pipeline)


def _scan_event_timestamp(ev: Mapping[str, Any]) -> datetime | None:
    ts = ev.get("scanned_at_parsed")
    if isinstance(ts, datetime):
        return ts
    return event_ts(ev)


def _scan_within_shift_window(
    ts: datetime,
    *,
    clock_in: datetime | None,
    clock_out: datetime | None,
) -> bool:
    if clock_in is not None and ts < clock_in:
        return False
    if clock_out is not None and ts > clock_out:
        return False
    return True


def _completion_keys_for_bags(
    bags: Sequence[Mapping[str, Any]],
) -> set[tuple[datetime, str]]:
    keys: set[tuple[datetime, str]] = set()
    for bag in bags:
        raw_ts = bag.get("completion_time")
        if not raw_ts:
            continue
        try:
            ts = datetime.fromisoformat(str(raw_ts))
        except ValueError:
            continue
        if not ts_valid(ts):
            continue
        bid = str(bag.get("bag_id") or "").strip().upper()
        if bid:
            keys.add((ts, bid))
    return keys


def _anchor_ts_by_bag(
    bags: Sequence[Mapping[str, Any]],
) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for bag in bags:
        bid = str(bag.get("bag_id") or "").strip().upper()
        raw = bag.get("lifecycle_anchor_ts")
        if not bid or not raw:
            continue
        try:
            anchor = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if ts_valid(anchor):
            out[bid] = anchor
    return out


def _load_employee_day_scan_events_bulk(
    cursor,
    organization_id: int,
    rinse_user_names: Sequence[str],
    selected_date_et: date,
) -> dict[str, list[dict[str, Any]]]:
    from backend.ta_helpers import table_exists

    names = sorted({str(n).strip() for n in rinse_user_names if str(n).strip()})
    if not names or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}

    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(selected_date_et, selected_date_et)
    end_exclusive = naive_et_day_end_exclusive(selected_date_et)
    out: dict[str, list[dict[str, Any]]] = {n.casefold(): [] for n in names}
    chunk = 100
    for i in range(0, len(names), chunk):
        part = names[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, user_name, purpose, rack, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed < %s
              AND user_name IN ({placeholders})
            """,
            (org, start_dt, end_exclusive, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            ts = row.get("scanned_at_parsed")
            if not isinstance(ts, datetime):
                continue
            uname = str(row.get("user_name") or "").strip().casefold()
            if uname in out:
                out[uname].append(dict(row))
    return out


def _dedupe_scan_events(
    scans: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, datetime, str, str]] = set()
    out: list[dict[str, Any]] = []
    for ev in scans:
        if not isinstance(ev, Mapping):
            continue
        ts = _scan_event_timestamp(ev)
        if ts is None:
            continue
        bid = str(ev.get("bag_id") or "").strip().upper()
        dedupe_key = (
            bid,
            ts,
            str(ev.get("purpose") or ""),
            str(ev.get("rack") or ""),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(dict(ev))
    return out


def _employee_day_scans_from_events_by_bag(
    employee: str,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
) -> list[dict[str, Any]]:
    start_dt, _end_incl = period_datetime_bounds_et(selected_date_et, selected_date_et)
    end_exclusive = naive_et_day_end_exclusive(selected_date_et)
    emp_key = employee.casefold()
    out: list[dict[str, Any]] = []
    for bid, evs in events_by_bag.items():
        bag_id = str(bid or "").strip().upper()
        for ev in evs or []:
            if not isinstance(ev, Mapping):
                continue
            if _event_user_name(ev).casefold() != emp_key:
                continue
            ts = _scan_event_timestamp(ev)
            if ts is None or ts < start_dt or ts >= end_exclusive:
                continue
            out.append({**dict(ev), "bag_id": bag_id})
    return out


def _collect_employee_non_folding_scans(
    employee: str,
    *,
    day_scans: Sequence[Mapping[str, Any]],
    completion_keys: set[tuple[datetime, str]],
    anchor_by_bag: Mapping[str, datetime],
    clock_in: datetime | None,
    clock_out: datetime | None,
) -> list[datetime]:
    emp_key = employee.casefold()
    timestamps: list[datetime] = []
    seen: set[tuple[datetime, str]] = set()
    for ev in day_scans:
        if _event_user_name(ev).casefold() != emp_key:
            continue
        ts = _scan_event_timestamp(ev)
        if ts is None or not ts_valid(ts):
            continue
        if not _scan_within_shift_window(ts, clock_in=clock_in, clock_out=clock_out):
            continue
        bid = str(ev.get("bag_id") or "").strip().upper()
        purpose = ev.get("purpose")
        rack = ev.get("rack")
        if (ts, bid) in completion_keys:
            continue
        if not is_fold_block_split_purpose(purpose, rack=rack):
            continue
        anchor = anchor_by_bag.get(bid)
        if bid and anchor is not None and ts < anchor:
            continue
        dedupe = (ts, bid)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        timestamps.append(ts)
    return sorted(timestamps)


def _collect_employee_wf_pipeline_scans(
    employee: str,
    *,
    day_scans: Sequence[Mapping[str, Any]],
    completion_keys: set[tuple[datetime, str]],
    anchor_by_bag: Mapping[str, datetime],
    clock_in: datetime | None,
    clock_out: datetime | None,
) -> list[datetime]:
    """WF pipeline activity timestamps used to infer folding block start."""
    emp_key = employee.casefold()
    timestamps: list[datetime] = []
    seen: set[tuple[datetime, str]] = set()
    for ev in day_scans:
        if _event_user_name(ev).casefold() != emp_key:
            continue
        ts = _scan_event_timestamp(ev)
        if ts is None or not ts_valid(ts):
            continue
        if not _scan_within_shift_window(ts, clock_in=clock_in, clock_out=clock_out):
            continue
        bid = str(ev.get("bag_id") or "").strip().upper()
        purpose = ev.get("purpose")
        if (ts, bid) in completion_keys:
            continue
        if not is_wf_folding_pipeline_purpose(purpose):
            continue
        anchor = anchor_by_bag.get(bid)
        if bid and anchor is not None and ts < anchor:
            continue
        dedupe = (ts, bid)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        timestamps.append(ts)
    return sorted(timestamps)


def _compute_folding_blocks(
    *,
    roster_role: str | None,
    clock_in: datetime | None,
    clock_out: datetime | None,
    non_folding_scans: Sequence[datetime],
    fold_completions: Sequence[datetime],
    wf_pipeline_scans: Sequence[datetime] | None = None,
) -> list[dict[str, Any]]:
    if roster_role not in ("operator", "folder"):
        return []
    if clock_in is None or not ts_valid(clock_in):
        return []

    completions = sorted({ts for ts in fold_completions if ts_valid(ts)})
    if not completions:
        return []

    non_fold = sorted({ts for ts in non_folding_scans if ts_valid(ts)})
    wf_pipeline = sorted({ts for ts in (wf_pipeline_scans or []) if ts_valid(ts)})

    groups: list[list[datetime]] = []
    current: list[datetime] = [completions[0]]
    for comp in completions[1:]:
        prev = current[-1]
        inactive_gap = (
            (comp - prev).total_seconds() > FOLDING_INACTIVE_GAP_SECONDS
            and not _has_wf_pipeline_in_inactive_gap_core(prev, comp, wf_pipeline)
        )
        if inactive_gap or any(prev < nf < comp for nf in non_fold):
            groups.append(current)
            current = [comp]
        else:
            current.append(comp)
    groups.append(current)

    blocks: list[dict[str, Any]] = []
    for idx, group in enumerate(groups):
        first_comp = min(group)
        last_comp = max(group)
        prior = _last_scan_before(non_fold, first_comp)
        wf_prior = _last_scan_before(wf_pipeline, first_comp)
        if prior is not None and prior >= clock_in:
            block_start = prior
            start_source = FOLD_BLOCK_START_PRIOR_SCAN
        elif wf_prior is not None and wf_prior >= clock_in:
            block_start = wf_prior
            start_source = FOLD_BLOCK_START_PRIOR_SCAN
        else:
            block_start = clock_in
            start_source = FOLD_BLOCK_START_CLOCK_IN

        block_end = last_comp
        end_source = FOLD_BLOCK_END_LAST_COMPLETION

        blocks.append(
            {
                "start_time": block_start.isoformat(),
                "end_time": block_end.isoformat(),
                "start_source": start_source,
                "end_source": end_source,
                "duration_seconds": max(0, int((block_end - block_start).total_seconds())),
                "completion_count": len(group),
            }
        )
    return blocks


def _folding_productivity_from_blocks(
    blocks: Sequence[Mapping[str, Any]],
) -> tuple[datetime | None, datetime | None, str, str, int]:
    if not blocks:
        return None, None, PRODUCTIVITY_START_CLOCK_IN, PRODUCTIVITY_END_LAST_COMPLETION, 0
    try:
        first_start = datetime.fromisoformat(str(blocks[0]["start_time"]))
        last_end = datetime.fromisoformat(str(blocks[-1]["end_time"]))
    except (ValueError, KeyError, TypeError):
        return None, None, PRODUCTIVITY_START_CLOCK_IN, PRODUCTIVITY_END_LAST_COMPLETION, 0
    total_sec = sum(int(b.get("duration_seconds") or 0) for b in blocks)
    if len(blocks) == 1:
        continuous_sec = max(0, int((last_end - first_start).total_seconds()))
        if (
            continuous_sec > 0
            and total_sec < int(continuous_sec * FOLDING_CONTINUOUS_SPAN_MIN_FRACTION)
        ):
            total_sec = continuous_sec
    start_source = str(blocks[0].get("start_source") or PRODUCTIVITY_START_INFERRED_FOLD)
    end_source = str(blocks[-1].get("end_source") or PRODUCTIVITY_END_LAST_COMPLETION)
    if start_source == FOLD_BLOCK_START_CLOCK_IN:
        start_source = PRODUCTIVITY_START_CLOCK_IN
    elif start_source == FOLD_BLOCK_START_PRIOR_SCAN:
        start_source = PRODUCTIVITY_START_INFERRED_FOLD
    if end_source == FOLD_BLOCK_END_CLOCK_OUT:
        end_source = PRODUCTIVITY_END_CLOCK_OUT
    elif end_source == FOLD_BLOCK_END_LAST_COMPLETION:
        end_source = PRODUCTIVITY_END_LAST_COMPLETION
    return first_start, last_end, start_source, end_source, total_sec


def _compute_productive_window(
    *,
    roster_role: str | None,
    clock_in: datetime | None,
    first_comp: datetime | None,
    last_comp: datetime | None,
    actual_clock_out: datetime | None,
    upstream_scans: Sequence[datetime],
    folding_blocks: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[datetime | None, datetime | None, str, str, int | None]:
    if roster_role in ("operator", "folder") and folding_blocks:
        return _folding_productivity_from_blocks(folding_blocks)

    productive_start = clock_in
    start_source = PRODUCTIVITY_START_CLOCK_IN
    if roster_role == "operator" and first_comp is not None:
        last_proc = _last_scan_before(upstream_scans, first_comp)
        if last_proc is not None:
            productive_start = last_proc
            start_source = PRODUCTIVITY_START_OPERATOR_PROCESSING

    productive_end = last_comp
    end_source = PRODUCTIVITY_END_LAST_COMPLETION
    if roster_role == "folder" and actual_clock_out is not None:
        productive_end = actual_clock_out
        end_source = PRODUCTIVITY_END_CLOCK_OUT

    total_sec: int | None = None
    if productive_start is not None and productive_end is not None:
        total_sec = max(0, int((productive_end - productive_start).total_seconds()))
    return productive_start, productive_end, start_source, end_source, total_sec


def _completed_lbs(row: Mapping[str, Any], meta: Mapping[str, Any] | None) -> float | None:
    for source in (row, meta or {}):
        for key in ("post_clean_weight", "weight_num", "registry_weight_num", "weight_lbs"):
            raw = source.get(key)
            if raw is None:
                continue
            try:
                val = float(raw)
                if val > 0:
                    return round(val, 4)
            except (TypeError, ValueError):
                continue
    return None


def build_employee_completed_bags_today(
    cursor,
    organization_id: int,
    *,
    completed_rows: Sequence[Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
    registry_meta_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from backend.rinse_simple_shift_performance import (
        _employee_shift_window,
        _load_rinse_user_maps,
    )
    from backend.rinse_processing_productivity import _load_shift_sessions_bulk

    org = int(organization_id)
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    user_maps = _load_rinse_user_maps(cursor, org)
    registry_meta = registry_meta_by_bag or {}

    attributed_bags: list[dict[str, Any]] = []
    seen_bags: set[str] = set()
    duplicate_bags: list[str] = []

    for row in completed_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("at_vendor_status") or "") != "Completed":
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if bid in seen_bags:
            duplicate_bags.append(bid)
            continue
        seen_bags.add(bid)

        events = events_by_bag.get(bid) or []
        anchor = _resolve_anchor_ts(events, selected_date_et)
        svc = str(row.get("service_type") or row.get("service_bucket") or "").upper()
        employee, attr_comp_ts, attr_signal = resolve_completion_attribution(
            service_type=svc,
            events=events,
            anchor_ts=anchor,
            as_of_end=as_of_end,
        )
        comp_ts = attr_comp_ts
        if comp_ts is None:
            raw = row.get("completion_time")
            if isinstance(raw, datetime):
                comp_ts = raw
            elif raw:
                try:
                    comp_ts = datetime.fromisoformat(str(raw))
                except ValueError:
                    comp_ts = None

        meta = registry_meta.get(bid) or {}
        lbs = _completed_lbs(row, meta)
        attr_reason = _attribution_reason(svc, attr_signal or row.get("completion_signal"))
        if employee == UNKNOWN_EMPLOYEE:
            if attr_comp_ts is None:
                attr_reason = "No completion attribution scan found — grouped under Unknown user"
            else:
                attr_reason = f"{attr_reason}; user_name missing on attribution scan"
        comp_time_et = None
        if comp_ts is not None:
            from backend.rinse_at_vendor_module import _format_et_display

            comp_time_et = _format_et_display(comp_ts)
        bag_record = {
            **dict(row),
            "bag_id": bid,
            "customer_name": row.get("customer_name") or meta.get("name_clean"),
            "completed_by_employee": employee,
            "employee_credited": employee,
            "attribution_reason": attr_reason,
            "completion_time": comp_ts.isoformat() if comp_ts else row.get("completion_time"),
            "completion_timestamp": comp_ts.isoformat() if comp_ts else row.get("completion_time"),
            "completion_time_et": comp_time_et or row.get("completion_time_et"),
            "completion_signal": attr_signal or row.get("completion_signal"),
            "completed_lbs": lbs,
            "weight": lbs,
            "weight_missing": lbs is None,
            "service_type": svc if svc in ("WF", "HD") else row.get("service_type"),
            "service_bucket": row.get("service_bucket") or svc,
            "lifecycle_anchor_ts": anchor.isoformat() if anchor else None,
            "attribution_matches_workload_time": (
                comp_ts is not None
                and row.get("completion_time") is not None
                and str(comp_ts.isoformat())[:19]
                == str(row.get("completion_time"))[:19]
            ),
        }
        attributed_bags.append(bag_record)

    attributed_bags.sort(
        key=lambda b: (
            str(b.get("completed_by_employee") or "").lower(),
            b.get("completion_time") or "",
        )
    )

    by_employee: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bag in attributed_bags:
        by_employee[str(bag.get("completed_by_employee") or UNKNOWN_EMPLOYEE)].append(bag)

    user_ids = sorted(
        {
            int(mapping["user_id"])
            for bags in by_employee.values()
            for bag in bags
            for mapping in [user_maps.get(str(bag.get("completed_by_employee") or "").casefold())]
            if mapping and mapping.get("user_id")
        }
    )
    sessions_by_user = (
        _load_shift_sessions_bulk(cursor, org, user_ids, selected_date_et, selected_date_et)
        if user_ids
        else {}
    )
    window_cache: dict[int, tuple[datetime | None, datetime | None, str | None]] = {}
    roster_roles = _build_roster_role_lookup(cursor, org, selected_date_et)
    credited_employees = [
        emp for emp in by_employee.keys() if emp != UNKNOWN_EMPLOYEE
    ]
    upstream_scans_by_employee = _load_upstream_processing_scan_times_bulk(
        cursor,
        org,
        credited_employees,
        selected_date_et,
    )
    day_scans_by_employee = _load_employee_day_scan_events_bulk(
        cursor,
        org,
        credited_employees,
        selected_date_et,
    )
    for employee_name in credited_employees:
        key = employee_name.casefold()
        day_scans_by_employee[key] = _dedupe_scan_events(
            list(day_scans_by_employee.get(key) or [])
            + _employee_day_scans_from_events_by_bag(
                employee_name, events_by_bag, selected_date_et
            )
        )

    employees: list[dict[str, Any]] = []
    for employee, bags in sorted(by_employee.items(), key=lambda x: x[0].lower()):
        bags_sorted = sorted(bags, key=lambda b: str(b.get("completion_time") or ""))
        comp_times = [
            datetime.fromisoformat(str(b["completion_time"]))
            for b in bags_sorted
            if b.get("completion_time")
        ]
        first_comp = min(comp_times) if comp_times else None
        last_comp = max(comp_times) if comp_times else None

        mapping = user_maps.get(employee.casefold()) if employee != UNKNOWN_EMPLOYEE else None
        user_id = int(mapping["user_id"]) if mapping and mapping.get("user_id") else None
        clock_in: datetime | None = None
        clock_out: datetime | None = None
        clock_diagnostic: str | None = None
        user_sessions: list[dict[str, Any]] = []
        if user_id is not None:
            user_sessions = sessions_by_user.get(user_id) or []
            clock_in, clock_out, clock_diagnostic = _employee_shift_window(
                cursor,
                org,
                user_id=user_id,
                period_start=selected_date_et,
                period_end=selected_date_et,
                sessions_by_user=sessions_by_user,
                last_sync_loaded=True,
                window_cache=window_cache,
            )
        elif employee == UNKNOWN_EMPLOYEE:
            clock_diagnostic = "Clock-in missing"

        roster_role = None
        if employee != UNKNOWN_EMPLOYEE:
            from backend.daily_shift_roster import resolve_roster_role_for_rinse_user

            roster_role = resolve_roster_role_for_rinse_user(
                employee, roster_roles, user_maps
            )
        actual_clock_out = _actual_clock_out_from_sessions(user_sessions)
        shift_clock_out = actual_clock_out or clock_out
        upstream_scans = upstream_scans_by_employee.get(employee.casefold()) or []
        employee_day_scans = day_scans_by_employee.get(employee.casefold()) or []
        completion_keys = _completion_keys_for_bags(bags_sorted)
        anchor_by_bag = _anchor_ts_by_bag(bags_sorted)

        non_folding_scans = _collect_employee_non_folding_scans(
            employee,
            day_scans=employee_day_scans,
            completion_keys=completion_keys,
            anchor_by_bag=anchor_by_bag,
            clock_in=clock_in,
            clock_out=shift_clock_out,
        )
        wf_pipeline_scans = _collect_employee_wf_pipeline_scans(
            employee,
            day_scans=employee_day_scans,
            completion_keys=completion_keys,
            anchor_by_bag=anchor_by_bag,
            clock_in=clock_in,
            clock_out=shift_clock_out,
        )
        folding_blocks = _compute_folding_blocks(
            roster_role=roster_role,
            clock_in=clock_in,
            clock_out=shift_clock_out,
            non_folding_scans=non_folding_scans,
            fold_completions=comp_times,
            wf_pipeline_scans=wf_pipeline_scans,
        )

        productive_start, productive_end, start_source, end_source, productive_sec = (
            _compute_productive_window(
                roster_role=roster_role,
                clock_in=clock_in,
                first_comp=first_comp,
                last_comp=last_comp,
                actual_clock_out=actual_clock_out,
                upstream_scans=upstream_scans,
                folding_blocks=folding_blocks,
            )
        )
        folding_duration_seconds = productive_sec or 0

        missing_weight_count = sum(1 for b in bags_sorted if b.get("weight_missing"))
        total_lbs = round(
            sum(float(b["completed_lbs"]) for b in bags_sorted if b.get("completed_lbs") is not None),
            2,
        )
        worked_hours: float | None = None
        wall_clock_hours: float | None = None
        productive_hours: float | None = None
        bags_per_hour: float | None = None
        lbs_per_hour: float | None = None
        productivity_note: str | None = None

        if clock_in is None:
            productivity_note = "Missing clock-in data"
        elif productive_sec is not None and productive_sec > 0:
            productive_hours = round(productive_sec / 3600.0, 4)
            worked_hours = productive_hours
            if clock_out is not None and clock_out >= clock_in:
                wall_sec = max(0, int((clock_out - clock_in).total_seconds()))
                wall_clock_hours = round(wall_sec / 3600.0, 4)
            else:
                wall_clock_hours = productive_hours
            if productive_hours > 0:
                bags_per_hour = round(len(bags_sorted) / productive_hours, 4)
                if total_lbs:
                    lbs_per_hour = round(total_lbs / productive_hours, 4)

        employees.append(
            {
                "employee": employee,
                "roster_role": roster_role,
                "clock_in_time": clock_in.isoformat() if clock_in else None,
                "clock_out_time": actual_clock_out.isoformat() if actual_clock_out else None,
                "clock_in_time_et": None,
                "productive_start_time": productive_start.isoformat() if productive_start else None,
                "productive_end_time": productive_end.isoformat() if productive_end else None,
                "productivity_start_source": start_source,
                "productivity_end_source": end_source,
                "folding_blocks": folding_blocks,
                "folding_duration_seconds": folding_duration_seconds,
                "last_completion_time": last_comp.isoformat() if last_comp else None,
                "first_completion_time": first_comp.isoformat() if first_comp else None,
                "worked_hours": worked_hours,
                "productive_hours": productive_hours,
                "wall_clock_hours": wall_clock_hours,
                "completed_bags": len(bags_sorted),
                "total_completed_lbs": total_lbs,
                "bags_per_hour": bags_per_hour,
                "lbs_per_hour": lbs_per_hour,
                "missing_weight_count": missing_weight_count,
                "productivity_note": productivity_note or clock_diagnostic,
                "bags": bags_sorted,
            }
        )

    from backend.rinse_at_vendor_module import _format_et_display

    def _ts_et(raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return _format_et_display(datetime.fromisoformat(str(raw)))
        except ValueError:
            return None

    for emp in employees:
        emp["clock_in_time_et"] = _ts_et(emp.get("clock_in_time"))
        emp["clock_out_time_et"] = _ts_et(emp.get("clock_out_time"))
        emp["productive_start_time_et"] = _ts_et(emp.get("productive_start_time"))
        emp["productive_end_time_et"] = _ts_et(emp.get("productive_end_time"))
        emp["last_completion_time_et"] = _ts_et(emp.get("last_completion_time"))
        emp["first_completion_time_et"] = _ts_et(emp.get("first_completion_time"))

    employees.sort(
        key=lambda e: (
            -(e.get("completed_bags") or 0),
            str(e.get("employee") or "").lower(),
        )
    )

    wf_count = sum(1 for b in attributed_bags if str(b.get("service_type") or "").upper() == "WF")
    hd_count = sum(1 for b in attributed_bags if str(b.get("service_type") or "").upper() == "HD")
    total_bags = len(attributed_bags)
    workload_completed = len(completed_rows)

    workload_bag_ids = sorted(
        str(r.get("bag_id") or "").strip().upper()
        for r in completed_rows
        if isinstance(r, dict) and r.get("bag_id")
    )
    attributed_ids = sorted({str(b.get("bag_id") or "").upper() for b in attributed_bags})
    workload_set = set(workload_bag_ids)
    attributed_set = set(attributed_ids)
    missing_from_employee = sorted(workload_set - attributed_set)
    extra_in_employee = sorted(attributed_set - workload_set)
    recon_ok = (
        total_bags == workload_completed
        and wf_count + hd_count == total_bags
        and not duplicate_bags
        and not missing_from_employee
        and not extra_in_employee
    )

    attribution_audit = [
        {
            "bag_id": b.get("bag_id"),
            "customer": b.get("customer_name"),
            "service_type": b.get("service_type"),
            "completion_signal": b.get("completion_signal"),
            "completion_timestamp": b.get("completion_timestamp") or b.get("completion_time"),
            "employee_credited": b.get("employee_credited"),
            "attribution_reason": b.get("attribution_reason"),
        }
        for b in sorted(attributed_bags, key=lambda x: str(x.get("completion_time") or ""))
    ]

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "employees": employees,
        "attribution_audit": attribution_audit,
        "reconciliation_banner": {
            "employee_completed_bags_credited": total_bags,
            "workload_completed_today": workload_completed,
            "difference": workload_completed - total_bags,
            "status": "reconciled" if recon_ok else "mismatch",
            "status_label": "Reconciled ✓" if recon_ok else "Mismatch ✗",
        },
        "reconciliation": {
            "workload_completed_today": workload_completed,
            "employee_attributed_bag_count": total_bags,
            "employee_completed_bags_credited": total_bags,
            "difference": workload_completed - total_bags,
            "status": "reconciled" if recon_ok else "mismatch",
            "status_label": "Reconciled ✓" if recon_ok else "Mismatch ✗",
            "wf_count": wf_count,
            "hd_count": hd_count,
            "wf_plus_hd": wf_count + hd_count,
            "duplicate_bag_ids": duplicate_bags,
            "missing_from_employee_dashboard": missing_from_employee,
            "extra_in_employee_dashboard": extra_in_employee,
            "bags_match_workload_completed": total_bags == workload_completed,
            "wf_hd_match_total": wf_count + hd_count == total_bags,
            "no_duplicate_bags": not duplicate_bags,
            "ok": recon_ok,
        },
    }


def build_employee_productivity_dashboard_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only Phase 2 payload — uses frozen Phase 1 employee_completed_bags_today."""
    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_employee_productivity_presentation import apply_employee_productivity_scope
    from backend.rinse_employee_productivity_settings import (
        include_hd_in_employee_productivity,
        productivity_scope_label,
    )

    org = int(organization_id)
    av = build_at_vendor_module(
        cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
    )
    emp = av.get("employee_completed_bags_today") or {}
    include_hd = include_hd_in_employee_productivity(cursor, org)
    scoped_emp = apply_employee_productivity_scope(emp, include_hd=include_hd)
    from backend.daily_shift_labor_summary import build_labor_summary
    from backend.daily_shift_roster import list_roster_entries
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps

    roster_entries = list_roster_entries(cursor, org, roster_date=selected_date_et)
    user_maps = _load_rinse_user_maps(cursor, org)
    labor_summary = build_labor_summary(
        roster_entries,
        productivity_section=scoped_emp,
        user_maps=user_maps,
    )
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "employee_completed_bags_today": scoped_emp,
        "completed_today_kpi": av.get("completed") or av.get("completed_today_count"),
        "include_hd_in_employee_productivity": include_hd,
        "productivity_scope_label": productivity_scope_label(include_hd),
        "labor_summary": labor_summary,
    }
