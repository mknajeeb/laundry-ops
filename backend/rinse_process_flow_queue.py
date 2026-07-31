"""
Read-only Process Flow inter-stage queue calculator.

Uses actual canonical Sort / Wash / Dry times and folding completion
(folding_end_at from evaluate_folding_performance_for_bag via rinse_folding_performance).

Does not introduce Sort/Wash duration assumptions.
Ready-to-Fold arrival = dry + drying_minutes (default 40; not org settings 45).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import ts_valid
from backend.rinse_folding_et import eastern_now, eastern_today, naive_et_day_end_inclusive
from backend.rinse_folding_settings import (
    DEFAULT_LBS_PER_HOUR,
    get_rinse_folding_benchmarks,
)
from backend.rinse_process_flow_chronology import (
    DEFAULT_DRY_ASSUMPTION_MINUTES,
    ProcessFlowValidationError,
    clamp_dry_assumption_minutes,
    parse_checkpoint_datetime,
    validate_checkpoint_times,
)
from backend.ta_helpers import table_exists, table_has_column

# Folding completion = persisted output of evaluate_folding_performance_for_bag
# (FOLDING rack → CLEAN rack → folding_end_at). Do not invent a competing resolver.
FOLDING_COMPLETION_SOURCE = "rinse_folding_performance.folding_end_at"
FOLDING_COMPLETION_RESOLVER = "evaluate_folding_performance_for_bag"

SEQ_FOLDED_BEFORE_READY = "Folded Before Ready to Fold"

STATUS_DEFICIT = "deficit"
STATUS_BALANCED = "balanced"
STATUS_CAPACITY = "capacity_available"

NEGLIGIBLE_STARVED_SECONDS = 30  # "negligible" for Balanced vs capacity labeling


def _bag_key(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _as_naive(ts: Any) -> datetime | None:
    if not ts_valid(ts):
        return None
    assert isinstance(ts, datetime)
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def parse_interval_start(value: Any, *, selected_date_et: date) -> datetime:
    """Calculator Start Time — required for Slot 1 interval start (not midnight)."""
    if value is None or (isinstance(value, str) and not str(value).strip()):
        raise ProcessFlowValidationError(
            "Start Time is required. Slot 1 interval starts at the calculator Start Time."
        )
    return parse_checkpoint_datetime(value, selected_date_et=selected_date_et)


def effective_departure(
    arrival: datetime | None,
    departure: datetime | None,
) -> tuple[datetime | None, bool]:
    """
    Return (effective_departure, is_out_of_sequence_departure).

    A departure before its valid arrival must not reduce the queue.
    """
    arr = _as_naive(arrival)
    dep = _as_naive(departure)
    if dep is None:
        return None, False
    if arr is None:
        # Departure without arrival — excluded from normal queue reduction.
        return None, True
    if dep < arr:
        return None, True
    return dep, False


def waiting_at_checkpoint(
    bags: Sequence[Mapping[str, Any]],
    checkpoint: datetime,
    *,
    arrival_key: str,
    departure_key: str,
) -> list[dict[str, Any]]:
    """Point-in-time queue: arrival <= cp AND (no valid dep OR dep > cp)."""
    cp = _as_naive(checkpoint)
    assert cp is not None
    waiting: list[dict[str, Any]] = []
    for bag in bags:
        arr = _as_naive(bag.get(arrival_key))
        if arr is None or arr > cp:
            continue
        dep_eff, _oos = effective_departure(arr, bag.get(departure_key))
        if dep_eff is not None and dep_eff <= cp:
            continue
        waiting.append(dict(bag))
    return waiting


def newly_available_in_interval(
    bags: Sequence[Mapping[str, Any]],
    *,
    interval_start: datetime,
    interval_end: datetime,
    arrival_key: str,
) -> list[dict[str, Any]]:
    """Arrivals with interval_start < arrival <= interval_end."""
    start = _as_naive(interval_start)
    end = _as_naive(interval_end)
    assert start is not None and end is not None
    out = []
    for bag in bags:
        arr = _as_naive(bag.get(arrival_key))
        if arr is None:
            continue
        if start < arr <= end:
            out.append(dict(bag))
    return out


def processed_in_interval(
    bags: Sequence[Mapping[str, Any]],
    *,
    interval_start: datetime,
    interval_end: datetime,
    arrival_key: str,
    departure_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Valid departures in (start, end] that had a prior valid arrival.

    Returns (processed, excluded_out_of_sequence).
    """
    start = _as_naive(interval_start)
    end = _as_naive(interval_end)
    assert start is not None and end is not None
    processed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for bag in bags:
        arr = _as_naive(bag.get(arrival_key))
        raw_dep = _as_naive(bag.get(departure_key))
        if raw_dep is None:
            continue
        if not (start < raw_dep <= end):
            continue
        dep_eff, oos = effective_departure(arr, raw_dep)
        if oos or dep_eff is None:
            excluded.append({**dict(bag), "exclusion_reason": "out_of_sequence_departure"})
            continue
        if arr is None or arr > dep_eff:
            excluded.append({**dict(bag), "exclusion_reason": "departure_without_valid_arrival"})
            continue
        processed.append(dict(bag))
    return processed, excluded


def replay_peak_and_starved(
    bags: Sequence[Mapping[str, Any]],
    *,
    interval_start: datetime,
    interval_end: datetime,
    waiting_at_start_count: int,
    arrival_key: str,
    departure_key: str,
) -> dict[str, Any]:
    """
    Chronologically replay arrivals/departures inside the interval.

    Peak Waiting = max queue size during replay (never below zero).
    Work-Starved Minutes = sum of continuous periods where queue == 0.
    """
    start = _as_naive(interval_start)
    end = _as_naive(interval_end)
    assert start is not None and end is not None
    if end <= start:
        return {
            "peak_waiting": max(0, int(waiting_at_start_count)),
            "work_starved_seconds": 0,
            "work_starved_minutes": 0,
            "excluded_departures": 0,
        }

    events: list[tuple[datetime, int, str, str]] = []
    # sort key: time, then departures before arrivals at same instant (clear before fill)
    excluded_deps = 0
    for bag in bags:
        bid = _bag_key(bag.get("bag_id"))
        arr = _as_naive(bag.get(arrival_key))
        if arr is not None and start < arr <= end:
            events.append((arr, 1, "arrival", bid))
        raw_dep = _as_naive(bag.get(departure_key))
        if raw_dep is not None and start < raw_dep <= end:
            dep_eff, oos = effective_departure(arr, raw_dep)
            if oos or dep_eff is None:
                excluded_deps += 1
                continue
            events.append((dep_eff, 0, "departure", bid))

    # Departures (ord=0) before arrivals (ord=1) at the same timestamp.
    events.sort(key=lambda e: (e[0], e[1], e[3]))

    queue = max(0, int(waiting_at_start_count))
    peak = queue
    starved_seconds = 0.0
    zero_since: datetime | None = start if queue == 0 else None

    def _close_starved(until: datetime) -> None:
        nonlocal starved_seconds, zero_since
        if zero_since is not None and until > zero_since:
            starved_seconds += (until - zero_since).total_seconds()
        zero_since = None

    for ts, _ord, kind, _bid in events:
        if kind == "departure":
            if queue > 0:
                queue -= 1
            queue = max(0, queue)
            if queue == 0 and zero_since is None:
                zero_since = ts
        else:
            # Arrival ends a starved stretch (if any), then increases queue.
            if zero_since is not None:
                _close_starved(ts)
            queue += 1
            peak = max(peak, queue)

    if zero_since is not None:
        _close_starved(end)

    starved_minutes = int(round(starved_seconds / 60.0))
    return {
        "peak_waiting": peak,
        "work_starved_seconds": int(round(starved_seconds)),
        "work_starved_minutes": starved_minutes,
        "excluded_departures": excluded_deps,
    }


def reconcile_waiting_end(
    *,
    waiting_at_start: int,
    newly_available: int,
    processed: int,
    waiting_at_end: int,
) -> dict[str, Any]:
    """Arithmetic check; report delta instead of forcing match."""
    expected = waiting_at_start + newly_available - processed
    delta = waiting_at_end - expected
    return {
        "expected_waiting_at_end": expected,
        "actual_waiting_at_end": waiting_at_end,
        "reconciliation_delta": delta,
        "reconciles": delta == 0,
    }


def classify_excess_deficit(
    *,
    stage_id: str,
    waiting_at_end: int,
    work_starved_minutes: int,
) -> dict[str, Any]:
    """Downstream-stage perspective status labels."""
    labels = {
        "washing_queue": {
            "deficit": lambda x: f"Wash deficit — {x} bags waiting",
            "capacity": "Wash capacity available",
        },
        "drying_queue": {
            "deficit": lambda x: f"Drying deficit — {x} bags waiting",
            "capacity": "Drying capacity available",
        },
        "folding_queue": {
            "deficit": lambda x: f"Folding deficit — {x} bags waiting",
            "capacity": "Folder capacity available",
        },
    }
    lab = labels[stage_id]
    if waiting_at_end > 0:
        return {
            "status": STATUS_DEFICIT,
            "label": lab["deficit"](waiting_at_end),
            "waiting_at_end": waiting_at_end,
        }
    if work_starved_minutes * 60 > NEGLIGIBLE_STARVED_SECONDS:
        return {
            "status": STATUS_CAPACITY,
            "label": lab["capacity"],
            "waiting_at_end": 0,
        }
    return {
        "status": STATUS_BALANCED,
        "label": "Balanced",
        "waiting_at_end": 0,
    }


def folder_capacity_recommendation(
    *,
    available_bags: int,
    available_pounds: float | None,
    pounds_complete: bool,
    interval_hours: float,
    lbs_per_hour_target: float,
) -> dict[str, Any]:
    """
    Staffing capacity for Folding Queue only.

    Target unit is pounds/hour (rinse_folding_lbs_per_hour_target).
    Uses available PRE pounds when reliable — never guessed bags↔pounds conversion.
    """
    target = float(lbs_per_hour_target or DEFAULT_LBS_PER_HOUR)
    if interval_hours <= 0:
        return {
            "target_unit": "pounds_per_hour",
            "lbs_per_hour_target": target,
            "available_bags": available_bags,
            "available_pounds": available_pounds,
            "pounds_complete": pounds_complete,
            "one_folder_interval_capacity_lbs": 0.0,
            "capacity_ratio": None,
            "full_additional_folders": 0,
            "recommendation": "No additional folder",
            "recommendation_code": "none",
            "note": "Interval length is zero or incomplete.",
        }

    one_cap = target * interval_hours
    if not pounds_complete or available_pounds is None:
        return {
            "target_unit": "pounds_per_hour",
            "lbs_per_hour_target": target,
            "available_bags": available_bags,
            "available_pounds": available_pounds,
            "pounds_complete": False,
            "one_folder_interval_capacity_lbs": round(one_cap, 2),
            "capacity_ratio": None,
            "full_additional_folders": None,
            "recommendation": "Insufficient PRE pounds for capacity recommendation",
            "recommendation_code": "insufficient_pounds",
            "note": (
                "Folding target is pounds/hour. Available pounds incomplete — "
                "no bag-count conversion applied."
            ),
        }

    ratio = (available_pounds / one_cap) if one_cap > 0 else 0.0
    full = int(available_pounds // one_cap) if one_cap > 0 else 0  # floor
    if full <= 0:
        if ratio > 0:
            code, rec = "partial", "Partial additional capacity"
        else:
            code, rec = "none", "No additional folder"
    elif full == 1:
        code, rec = "add_1", "Add 1 folder"
    elif full == 2:
        code, rec = "add_2", "Add 2 folders"
    else:
        code, rec = "add_3_plus", f"Add {full} folders"

    return {
        "target_unit": "pounds_per_hour",
        "lbs_per_hour_target": target,
        "available_bags": available_bags,
        "available_pounds": round(float(available_pounds), 2),
        "pounds_complete": True,
        "one_folder_interval_capacity_lbs": round(one_cap, 2),
        "capacity_ratio": round(ratio, 3),
        "full_additional_folders": full,
        "recommendation": rec,
        "recommendation_code": code,
        "note": None,
    }


def _minutes_waiting(available_since: datetime | None, checkpoint: datetime) -> int | None:
    arr = _as_naive(available_since)
    cp = _as_naive(checkpoint)
    if arr is None or cp is None or cp < arr:
        return None
    return int((cp - arr).total_seconds() // 60)


def _detail_available(bag: Mapping[str, Any], *, arrival_key: str, departure_key: str) -> dict[str, Any]:
    return {
        "bag_id": bag.get("bag_id"),
        "arrival_time_et": bag.get(arrival_key),
        "arrival_employee": bag.get("arrival_employee"),
        "arrival_machine": bag.get("arrival_machine"),
        "departure_time_et": bag.get(departure_key),
        "sequence_status": bag.get("sequence_status"),
        "sequence_codes": bag.get("sequence_codes") or [],
    }


def _detail_processed(
    bag: Mapping[str, Any],
    *,
    arrival_key: str,
    departure_key: str,
) -> dict[str, Any]:
    arr = _as_naive(bag.get(arrival_key))
    dep = _as_naive(bag.get(departure_key))
    wait = None
    if arr is not None and dep is not None and dep >= arr:
        wait = int((dep - arr).total_seconds() // 60)
    return {
        "bag_id": bag.get("bag_id"),
        "arrival_time_et": bag.get(arrival_key),
        "processing_time_et": bag.get(departure_key),
        "processing_employee": bag.get("departure_employee"),
        "processing_machine": bag.get("departure_machine"),
        "queue_wait_minutes": wait,
        "sequence_status": bag.get("sequence_status"),
        "sequence_codes": bag.get("sequence_codes") or [],
    }


def _detail_waiting(
    bag: Mapping[str, Any],
    *,
    checkpoint: datetime,
    arrival_key: str,
    departure_key: str,
) -> dict[str, Any]:
    return {
        "bag_id": bag.get("bag_id"),
        "available_since_et": bag.get(arrival_key),
        "minutes_waiting": _minutes_waiting(bag.get(arrival_key), checkpoint),
        "upstream_employee": bag.get("arrival_employee"),
        "upstream_machine": bag.get("arrival_machine"),
        "later_processing_time_et": bag.get(departure_key),
        "sequence_status": bag.get("sequence_status"),
        "sequence_codes": bag.get("sequence_codes") or [],
        "pre_weight_lbs": bag.get("pre_weight_lbs"),
    }


def build_queue_slot(
    bags: Sequence[Mapping[str, Any]],
    *,
    slot_index: int,
    interval_start: datetime,
    interval_end: datetime,
    analysis_end: datetime,
    arrival_key: str,
    departure_key: str,
    stage_id: str,
    labels: Mapping[str, str],
    incomplete: bool,
) -> dict[str, Any]:
    """Build one checkpoint slot for a queue section."""
    start = _as_naive(interval_start)
    end = _as_naive(min(interval_end, analysis_end))
    assert start is not None and end is not None

    waiting_start = waiting_at_checkpoint(
        bags, start, arrival_key=arrival_key, departure_key=departure_key
    )
    waiting_end = waiting_at_checkpoint(
        bags, end, arrival_key=arrival_key, departure_key=departure_key
    )
    newly = newly_available_in_interval(
        bags, interval_start=start, interval_end=end, arrival_key=arrival_key
    )
    processed, excluded = processed_in_interval(
        bags,
        interval_start=start,
        interval_end=end,
        arrival_key=arrival_key,
        departure_key=departure_key,
    )
    replay = replay_peak_and_starved(
        bags,
        interval_start=start,
        interval_end=end,
        waiting_at_start_count=len(waiting_start),
        arrival_key=arrival_key,
        departure_key=departure_key,
    )
    recon = reconcile_waiting_end(
        waiting_at_start=len(waiting_start),
        newly_available=len(newly),
        processed=len(processed),
        waiting_at_end=len(waiting_end),
    )
    # Exclusions can explain reconciliation deltas (oos departures counted in excluded).
    status = classify_excess_deficit(
        stage_id=stage_id,
        waiting_at_end=len(waiting_end),
        work_starved_minutes=replay["work_starved_minutes"],
    )

    interval_hours = max(0.0, (end - start).total_seconds() / 3600.0)

    detail_available = [
        _detail_available(b, arrival_key=arrival_key, departure_key=departure_key) for b in newly
    ]
    detail_processed = [
        _detail_processed(b, arrival_key=arrival_key, departure_key=departure_key)
        for b in processed
    ]
    detail_waiting = [
        _detail_waiting(
            b, checkpoint=end, arrival_key=arrival_key, departure_key=departure_key
        )
        for b in waiting_end
    ]

    assert len(detail_available) == len(newly)
    assert len(detail_processed) == len(processed)
    assert len(detail_waiting) == len(waiting_end)

    slot: dict[str, Any] = {
        "slot_index": slot_index,
        "checkpoint_et": _as_naive(interval_end),
        "interval_start_et": start,
        "interval_end_et": end,
        "interval_label": (
            f"{start.strftime('%I:%M %p').lstrip('0')} – "
            f"{end.strftime('%I:%M %p').lstrip('0')}"
        ),
        "incomplete_interval": incomplete or end < _as_naive(interval_end),
        "newly_available_count": len(newly),
        "processed_count": len(processed),
        "waiting_at_start": len(waiting_start),
        "waiting_at_end": len(waiting_end),
        "peak_waiting": replay["peak_waiting"],
        "excess_deficit_status": status["status"],
        "excess_deficit_label": status["label"],
        "work_starved_minutes": replay["work_starved_minutes"],
        "work_starved_seconds": replay["work_starved_seconds"],
        "excluded_sequence_count": len(excluded) + int(replay["excluded_departures"]),
        "excluded_bags": excluded,
        "reconciliation": recon,
        "interval_hours": round(interval_hours, 4),
        "labels": dict(labels),
        "bags_available": detail_available,
        "bags_processed": detail_processed,
        "bags_waiting": detail_waiting,
    }

    # Guard: never display negative queues
    for k in ("newly_available_count", "processed_count", "waiting_at_start", "waiting_at_end", "peak_waiting"):
        slot[k] = max(0, int(slot[k]))

    return slot


def load_folding_completions(
    cursor, organization_id: int, bag_ids: Sequence[str]
) -> dict[str, datetime]:
    """Read-only folding_end_at from rinse_folding_performance (canonical completion)."""
    out: dict[str, datetime] = {}
    ids = [_bag_key(b) for b in bag_ids if _bag_key(b)]
    if not ids or not table_exists(cursor, "rinse_folding_performance"):
        return out
    # chunk IN lists
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            SELECT bag_id, folding_end_at
            FROM rinse_folding_performance
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND folding_end_at IS NOT NULL
            """,
            (int(organization_id), *chunk),
        )
        for row in cursor.fetchall() or []:
            bid = _bag_key(row.get("bag_id") if isinstance(row, dict) else row[0])
            end = row.get("folding_end_at") if isinstance(row, dict) else row[1]
            end_n = _as_naive(end)
            if bid and end_n is not None:
                out[bid] = end_n
    return out


def load_bag_pre_pounds(
    cursor, organization_id: int, selected_date_et: date, bag_ids: Sequence[str]
) -> dict[str, float]:
    """
    Evidence PRE pounds from shift-monitor day bags when present.

    Missing pounds are omitted (no guessed conversion).
    """
    out: dict[str, float] = {}
    ids = [_bag_key(b) for b in bag_ids if _bag_key(b)]
    if not ids:
        return out
    table = "rinse_shift_monitor_day_bags"
    if not table_exists(cursor, table):
        return out
    if not table_has_column(cursor, table, "pre_weight_lbs"):
        return out
    if not table_has_column(cursor, table, "shift_date_et"):
        return out
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            SELECT bag_id, pre_weight_lbs
            FROM {table}
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND bag_id IN ({placeholders})
              AND pre_weight_lbs IS NOT NULL
            """,
            (int(organization_id), selected_date_et, *chunk),
        )
        for row in cursor.fetchall() or []:
            bid = _bag_key(row.get("bag_id") if isinstance(row, dict) else row[0])
            raw = row.get("pre_weight_lbs") if isinstance(row, dict) else row[1]
            try:
                lbs = float(raw)
            except (TypeError, ValueError):
                continue
            if bid and lbs > 0:
                out[bid] = lbs
    return out


def compose_queue_bags_from_process_flow_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    dry_minutes: int,
    fold_completions: Mapping[str, datetime],
    pre_pounds: Mapping[str, float],
) -> list[dict[str, Any]]:
    """Map Process Flow chronology rows into queue bag records (actual evidence)."""
    bags: list[dict[str, Any]] = []
    for row in rows:
        bid = _bag_key(row.get("bag_id"))
        if not bid:
            continue
        sort_ts = _as_naive(row.get("sort_scan_et"))
        wash_ts = _as_naive(row.get("wash_scan_et"))
        dry_ts = _as_naive(row.get("dry_scan_et"))
        ready_ts = None
        if dry_ts is not None:
            ready_ts = dry_ts + timedelta(minutes=int(dry_minutes))
        fold_ts = _as_naive(fold_completions.get(bid))
        codes = list(row.get("sequence_codes") or [])
        # Folded before ready exception
        if fold_ts is not None and ready_ts is not None and fold_ts < ready_ts:
            if SEQ_FOLDED_BEFORE_READY not in codes:
                codes = codes + [SEQ_FOLDED_BEFORE_READY]
        seq_status = "; ".join(codes) if codes else (row.get("sequence_status") or "Valid")
        bags.append(
            {
                "bag_id": bid,
                "sort_ts": sort_ts,
                "wash_ts": wash_ts,
                "dry_ts": dry_ts,
                "ready_to_fold_ts": ready_ts,
                "fold_completion_ts": fold_ts,
                "sequence_status": seq_status,
                "sequence_codes": codes,
                "pre_weight_lbs": pre_pounds.get(bid),
                # Washing queue fields
                "wash_arrival": sort_ts,
                "wash_departure": wash_ts,
                "wash_arrival_employee": row.get("sort_employee"),
                "wash_arrival_machine": row.get("sort_machine_rack"),
                "wash_departure_employee": row.get("wash_employee"),
                "wash_departure_machine": row.get("washer"),
                # Drying queue
                "dry_arrival": wash_ts,
                "dry_departure": dry_ts,
                "dry_arrival_employee": row.get("wash_employee"),
                "dry_arrival_machine": row.get("washer"),
                "dry_departure_employee": row.get("dry_employee"),
                "dry_departure_machine": row.get("dryer"),
                # Folding queue
                "fold_arrival": ready_ts,
                "fold_departure": fold_ts,
                "fold_arrival_employee": row.get("dry_employee"),
                "fold_arrival_machine": row.get("dryer"),
                "fold_departure_employee": None,
                "fold_departure_machine": None,
            }
        )
    return bags


def _stage_bag_view(bag: Mapping[str, Any], *, stage: str) -> dict[str, Any]:
    """Project stage-specific arrival/departure employee fields onto generic keys."""
    b = dict(bag)
    if stage == "washing":
        b["arrival_employee"] = bag.get("wash_arrival_employee")
        b["arrival_machine"] = bag.get("wash_arrival_machine")
        b["departure_employee"] = bag.get("wash_departure_employee")
        b["departure_machine"] = bag.get("wash_departure_machine")
    elif stage == "drying":
        b["arrival_employee"] = bag.get("dry_arrival_employee")
        b["arrival_machine"] = bag.get("dry_arrival_machine")
        b["departure_employee"] = bag.get("dry_departure_employee")
        b["departure_machine"] = bag.get("dry_departure_machine")
    else:
        b["arrival_employee"] = bag.get("fold_arrival_employee")
        b["arrival_machine"] = bag.get("fold_arrival_machine")
        b["departure_employee"] = bag.get("fold_departure_employee")
        b["departure_machine"] = bag.get("fold_departure_machine")
    return b


def build_process_flow_queue_calculator_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    checkpoints: Sequence[Any],
    start_time: Any,
    dry_assumption_minutes: int | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """
    Read-only three-queue calculator: Washing / Drying / Folding.

    No Sort/Wash duration assumptions. Dry minutes only for Ready-to-Fold = dry + N.
    """
    from backend.rinse_process_flow_chronology import build_process_flow_chronology_payload

    dry_mins = clamp_dry_assumption_minutes(dry_assumption_minutes)
    parsed_cps = validate_checkpoint_times(checkpoints, selected_date_et=selected_date_et)
    interval_start_0 = parse_interval_start(start_time, selected_date_et=selected_date_et)
    if interval_start_0 >= parsed_cps[0]:
        raise ProcessFlowValidationError(
            "Start Time must be earlier than Slot 1 checkpoint."
        )

    now = _as_naive(now_et) or eastern_now().replace(tzinfo=None)
    today = eastern_today()
    is_today = selected_date_et == today
    day_end = naive_et_day_end_inclusive(selected_date_et)
    analysis_cap = min(now, day_end) if is_today else day_end

    base = build_process_flow_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        dry_assumption_minutes=dry_mins,
    )
    sessions = list(base.get("sessions") or [])
    bag_ids = [_bag_key(r.get("bag_id")) for r in sessions]
    fold_completions = load_folding_completions(cursor, organization_id, bag_ids)
    pre_pounds = load_bag_pre_pounds(cursor, organization_id, selected_date_et, bag_ids)
    queue_bags = compose_queue_bags_from_process_flow_rows(
        sessions,
        dry_minutes=dry_mins,
        fold_completions=fold_completions,
        pre_pounds=pre_pounds,
    )

    benchmarks = get_rinse_folding_benchmarks(cursor, organization_id)
    lbs_target = float(benchmarks.get("lbs_per_hour_target") or DEFAULT_LBS_PER_HOUR)

    stage_defs = [
        {
            "id": "washing_queue",
            "label": "Washing Queue",
            "subtitle": "Sorted → Washed",
            "arrival_key": "wash_arrival",
            "departure_key": "wash_departure",
            "stage": "washing",
            "labels": {
                "newly_available": "Newly Sorted",
                "processed": "Washed",
                "waiting": "Waiting for Wash",
            },
        },
        {
            "id": "drying_queue",
            "label": "Drying Queue",
            "subtitle": "Washed → Dried",
            "arrival_key": "dry_arrival",
            "departure_key": "dry_departure",
            "stage": "drying",
            "labels": {
                "newly_available": "Newly Washed",
                "processed": "Dried",
                "waiting": "Waiting for Dry",
            },
        },
        {
            "id": "folding_queue",
            "label": "Folding Queue",
            "subtitle": "Ready to Fold → Folded",
            "arrival_key": "fold_arrival",
            "departure_key": "fold_departure",
            "stage": "folding",
            "labels": {
                "newly_available": "Newly Ready to Fold",
                "processed": "Folded",
                "waiting": "Waiting for Fold",
                "capacity": "Additional Folder Capacity",
            },
        },
    ]

    sections = []
    for spec in stage_defs:
        projected = [_stage_bag_view(b, stage=spec["stage"]) for b in queue_bags]
        slots = []
        for idx, cp in enumerate(parsed_cps):
            start = interval_start_0 if idx == 0 else parsed_cps[idx - 1]
            future_today = is_today and start >= analysis_cap
            incomplete = is_today and cp > analysis_cap
            if future_today:
                slots.append(
                    {
                        "slot_index": idx + 1,
                        "checkpoint_et": cp,
                        "interval_start_et": start,
                        "interval_end_et": cp,
                        "interval_label": "Future — not calculated",
                        "incomplete_interval": True,
                        "future_interval": True,
                        "newly_available_count": 0,
                        "processed_count": 0,
                        "waiting_at_start": 0,
                        "waiting_at_end": 0,
                        "peak_waiting": 0,
                        "excess_deficit_status": None,
                        "excess_deficit_label": "Incomplete — future checkpoint",
                        "work_starved_minutes": 0,
                        "excluded_sequence_count": 0,
                        "bags_available": [],
                        "bags_processed": [],
                        "bags_waiting": [],
                        "labels": spec["labels"],
                    }
                )
                continue

            slot = build_queue_slot(
                projected,
                slot_index=idx + 1,
                interval_start=start,
                interval_end=cp,
                analysis_end=analysis_cap,
                arrival_key=spec["arrival_key"],
                departure_key=spec["departure_key"],
                stage_id=spec["id"],
                labels=spec["labels"],
                incomplete=incomplete,
            )

            if spec["id"] == "folding_queue":
                waiting_bags = slot["bags_waiting"]
                avail_bags = len(waiting_bags)
                lbs_vals = []
                missing = 0
                for wb in waiting_bags:
                    raw = wb.get("pre_weight_lbs")
                    if raw is None:
                        missing += 1
                        continue
                    try:
                        lbs_vals.append(float(raw))
                    except (TypeError, ValueError):
                        missing += 1
                pounds_complete = missing == 0 and avail_bags > 0
                if avail_bags == 0:
                    pounds_complete = True
                    total_lbs: float | None = 0.0
                elif missing:
                    total_lbs = sum(lbs_vals) if lbs_vals else None
                    pounds_complete = False
                else:
                    total_lbs = sum(lbs_vals)
                slot["folder_capacity"] = folder_capacity_recommendation(
                    available_bags=avail_bags,
                    available_pounds=total_lbs,
                    pounds_complete=pounds_complete,
                    interval_hours=float(slot["interval_hours"]),
                    lbs_per_hour_target=lbs_target,
                )

            slots.append(slot)

        sections.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "subtitle": spec["subtitle"],
                "labels": spec["labels"],
                "slots": slots,
            }
        )

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "process_flow_queue_calculator",
        "read_only": True,
        "mutates_scan_records": False,
        "dry_assumption_minutes": dry_mins,
        "dry_assumption_label": (
            "Scan Chronology Ready-to-Fold assumption (default 40; "
            "not rinse_processing_settings.drying_minutes=45)"
        ),
        "sort_assumption_minutes": None,
        "wash_assumption_minutes": None,
        "start_time_et": interval_start_0,
        "checkpoints_et": parsed_cps,
        "is_today": is_today,
        "analysis_as_of_et": analysis_cap if is_today else day_end,
        "folding_completion_resolver": FOLDING_COMPLETION_RESOLVER,
        "folding_completion_source": FOLDING_COMPLETION_SOURCE,
        "folding_target_unit": "pounds_per_hour",
        "folding_lbs_per_hour_target": lbs_target,
        "folder_role_idle_metric": None,
        "folder_role_idle_note": (
            "Folder Role Minutes Without Available Work deferred — "
            "role-session loaders are reusable, but queue∩role intersection "
            "is a later additive enhancement."
        ),
        "sections": sections,
        "work_starved_definition": (
            "Work-Starved Minutes = continuous periods where the stage queue "
            "size is zero. Queue-availability only — not employee idle proof."
        ),
    }
