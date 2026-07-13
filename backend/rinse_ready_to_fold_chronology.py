"""
Read-only Ready to Fold chronology for Scan Chronology.

Ready-to-fold time = drying scan time + configurable drying duration (default 40 min).
Builds a 24-hour report in 15-minute intervals for the selected ET day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_folding import rack_contains_folding
from backend.rinse_bag_stage_bounds import (
    event_ts,
    gaming_events_from_records,
    sort_key_ev,
    ts_valid,
)
from backend.rinse_drying_chronology import extract_drying_rows_from_events
from backend.rinse_folding_et import (
    eastern_now,
    eastern_today,
    naive_et_day_end_inclusive,
    naive_et_day_start,
)
from backend.rinse_scan_purpose import is_sent_to_vendor_purpose
from backend.rinse_simple_shift_performance import _load_bag_metadata
from backend.ta_helpers import table_exists

DEFAULT_DRYING_DURATION_MINUTES = 40
INTERVAL_MINUTES = 15
INTERVALS_PER_DAY = 24 * 60 // INTERVAL_MINUTES  # 96

STATUS_WAITING = "waiting_to_fold"
STATUS_FOLDING_STARTED = "folding_started"
STATUS_NOT_YET_READY = "not_yet_ready"

VALID_STATUS_FILTERS = frozenset({"all", STATUS_WAITING, STATUS_FOLDING_STARTED, STATUS_NOT_YET_READY})
VALID_VIEW_MODES = frozenset({"newly_ready", "cumulative", "both"})


def clamp_drying_duration_minutes(value: Any) -> int:
    """Bound duration to [0, 1440]. Invalid input falls back to the default (40)."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DRYING_DURATION_MINUTES
    return max(0, min(minutes, 24 * 60))


def floor_to_interval(ts: datetime) -> datetime:
    """Floor timestamp to the start of its 15-minute interval (half-open buckets)."""
    minute = (ts.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES
    return ts.replace(minute=minute, second=0, microsecond=0)


def build_day_interval_starts(selected_date_et: date) -> list[datetime]:
    day_start = naive_et_day_start(selected_date_et)
    return [day_start + timedelta(minutes=INTERVAL_MINUTES * i) for i in range(INTERVALS_PER_DAY)]


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _bag_key(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _normalize_service_type(raw: Any) -> str | None:
    val = str(raw or "").strip().upper()
    if not val:
        return None
    if val in ("WF", "WASH & FOLD", "WASH_AND_FOLD", "WASHANDFOLD"):
        return "WF"
    if val in ("HD", "HANG DRY", "HANG_DRY", "HANGDRY"):
        return "HD"
    return val


def lifecycle_anchor_as_of(
    timeline: Sequence[Mapping[str, Any]],
    *,
    as_of_end: datetime,
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    """Latest sent-to-vendor at or before as_of_end — current lifecycle for that day."""
    candidates: list[Mapping[str, Any]] = []
    for ev in timeline:
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts) and ts <= as_of_end:
            candidates.append(ev)
    if not candidates:
        return None, None
    ev = max(candidates, key=sort_key_ev)
    return event_ts(ev), ev


def find_folding_start_after(
    events: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
) -> datetime | None:
    """Earliest FOLDING-rack (or folding purpose) scan strictly after a drying scan."""
    best: datetime | None = None
    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= after_ts:
            continue
        purpose = str(ev.get("purpose") or "").strip().lower()
        if rack_contains_folding(ev.get("rack")) or purpose == "folding":
            if best is None or ts < best:
                best = ts
    return best


def select_current_lifecycle_drying_row(
    drying_rows: Sequence[Mapping[str, Any]],
    bag_events: Sequence[Mapping[str, Any]],
    *,
    as_of_end: datetime,
) -> dict[str, Any] | None:
    """
    Pick the current-lifecycle drying scan for one bag.

    Rules:
    - Prefer drying scans on/after the latest sent-to-vendor at or before as_of_end
    - Among eligible scans, take the most recent (handles redry within the lifecycle)
    - Duplicate ingest rows are already collapsed by extract_drying_rows_from_events
    - If no sent-to-vendor anchor exists, fall back to most recent drying <= as_of_end
    """
    eligible = [
        dict(row)
        for row in drying_rows
        if ts_valid(row.get("timestamp_et")) and row["timestamp_et"] <= as_of_end
    ]
    if not eligible:
        return None

    timeline = gaming_events_from_records(bag_events)
    anchor_ts, _ = lifecycle_anchor_as_of(timeline, as_of_end=as_of_end)
    if anchor_ts is not None:
        anchored = [row for row in eligible if row["timestamp_et"] >= anchor_ts]
        if anchored:
            eligible = anchored
        # If every drying scan predates the anchor, this lifecycle has no dry yet.
        elif any(
            is_sent_to_vendor_purpose(ev.get("purpose"))
            and ts_valid(event_ts(ev))
            and event_ts(ev) <= as_of_end
            for ev in timeline
        ):
            return None

    chosen = max(
        eligible,
        key=lambda r: (
            r.get("timestamp_et") or datetime.min,
            int(r.get("scan_event_id") or 0),
        ),
    )
    chosen["bag_id"] = _bag_key(chosen.get("bag_id"))
    return chosen


def select_current_cycle_drying_rows(
    drying_rows: Sequence[Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    as_of_end: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    One drying row per bag for the current lifecycle.

    When events_by_bag/as_of_end are provided, respects sent-to-vendor lifecycle
    anchors (repeat trips / re-intake). Otherwise falls back to latest drying.
    """
    by_bag_rows: dict[str, list[dict[str, Any]]] = {}
    for row in drying_rows:
        bid = _bag_key(row.get("bag_id"))
        ts = row.get("timestamp_et")
        if not bid or not ts_valid(ts):
            continue
        by_bag_rows.setdefault(bid, []).append(dict(row))

    selected: list[dict[str, Any]] = []
    for bid, rows in by_bag_rows.items():
        if events_by_bag is not None and as_of_end is not None:
            chosen = select_current_lifecycle_drying_row(
                rows,
                events_by_bag.get(bid) or [],
                as_of_end=as_of_end,
            )
            if chosen:
                selected.append(chosen)
            continue

        # Legacy fallback — latest drying only.
        chosen = max(rows, key=lambda r: r.get("timestamp_et") or datetime.min)
        chosen["bag_id"] = bid
        selected.append(chosen)

    return sorted(
        selected,
        key=lambda r: (
            r.get("timestamp_et") is None,
            r.get("timestamp_et") or datetime.min,
            str(r.get("bag_id") or ""),
        ),
    )


def resolve_bag_status(
    *,
    ready_et: datetime,
    folding_start_et: datetime | None,
    as_of: datetime,
) -> str:
    if folding_start_et is not None and folding_start_et <= as_of:
        return STATUS_FOLDING_STARTED
    if ready_et > as_of:
        return STATUS_NOT_YET_READY
    return STATUS_WAITING


def build_ready_to_fold_bag_records(
    *,
    drying_rows: Sequence[Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    metadata_by_bag: Mapping[str, Mapping[str, Any]],
    selected_date_et: date,
    drying_duration_minutes: int,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Build bag-level ready-to-fold records for the selected ET day.

    Includes:
    - Bags whose ready time falls on the selected date
    - Overnight carryover: ready before day start, still waiting at day start
      (or folding later on the selected day)
    """
    duration = clamp_drying_duration_minutes(drying_duration_minutes)
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    as_of_ts = as_of if as_of is not None else day_end

    records: list[dict[str, Any]] = []
    selected_drying = select_current_cycle_drying_rows(
        drying_rows,
        events_by_bag,
        as_of_end=as_of_ts,
    )
    for dry in selected_drying:
        bid = _bag_key(dry.get("bag_id"))
        dry_ts = dry.get("timestamp_et")
        if not bid or not ts_valid(dry_ts):
            continue
        ready_et = dry_ts + timedelta(minutes=duration)
        bag_events = events_by_bag.get(bid) or []
        folding_start_et = find_folding_start_after(bag_events, after_ts=dry_ts)

        ready_on_selected_day = day_start <= ready_et <= day_end
        carryover_waiting = ready_et < day_start and (
            folding_start_et is None or folding_start_et >= day_start
        )
        if not ready_on_selected_day and not carryover_waiting:
            continue

        meta = metadata_by_bag.get(bid) or {}
        service_type = _normalize_service_type(meta.get("service_type"))
        weight = meta.get("weight_num")
        if weight is None:
            weight = meta.get("weight_lbs")

        status = resolve_bag_status(
            ready_et=ready_et,
            folding_start_et=folding_start_et,
            as_of=as_of_ts,
        )

        records.append(
            {
                "bag_id": bid,
                "drying_scan_et": dry_ts,
                "ready_to_fold_et": ready_et,
                "drying_duration_minutes": duration,
                "dryer_rack": dry.get("dryer_rack"),
                "employee": dry.get("employee"),
                "weight": weight,
                "service_type": service_type,
                "order_type": service_type,
                "folding_start_et": folding_start_et,
                "status": status,
                "confidence": dry.get("confidence"),
                "scan_event_id": dry.get("scan_event_id"),
                "is_carryover": ready_et < day_start,
            }
        )

    records.sort(
        key=lambda r: (
            r.get("ready_to_fold_et") is None,
            r.get("ready_to_fold_et") or datetime.min,
            str(r.get("bag_id") or ""),
        ),
    )
    for idx, row in enumerate(records):
        row["index"] = idx + 1
    return records


def _bag_available_at_interval_end(
    bag: Mapping[str, Any],
    *,
    interval_end: datetime,
) -> bool:
    ready_et = bag.get("ready_to_fold_et")
    if not ts_valid(ready_et) or ready_et >= interval_end:
        return False
    fold_ts = bag.get("folding_start_et")
    if fold_ts is not None and ts_valid(fold_ts) and fold_ts < interval_end:
        return False
    return True


def build_ready_to_fold_intervals(
    bags: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    interval_starts = build_day_interval_starts(selected_date_et)
    day_end_exclusive = naive_et_day_start(selected_date_et) + timedelta(days=1)

    intervals: list[dict[str, Any]] = []
    for start in interval_starts:
        end = start + timedelta(minutes=INTERVAL_MINUTES)
        if end > day_end_exclusive:
            end = day_end_exclusive

        newly = [
            b
            for b in bags
            if ts_valid(b.get("ready_to_fold_et"))
            and start <= b["ready_to_fold_et"] < end
        ]
        available = [b for b in bags if _bag_available_at_interval_end(b, interval_end=end)]

        intervals.append(
            {
                "interval_start_et": start,
                "interval_end_et": end,
                "label": start.strftime("%I:%M %p").lstrip("0"),
                "newly_ready_count": len(newly),
                "available_count": len(available),
                "newly_ready_bags": newly,
                "available_bags": available,
            }
        )
    return intervals


def build_ready_to_fold_summary(
    bags: Sequence[Mapping[str, Any]],
    intervals: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> dict[str, Any]:
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    dried = [b for b in bags if ts_valid(b.get("drying_scan_et"))]
    ready_on_day = [
        b
        for b in bags
        if ts_valid(b.get("ready_to_fold_et")) and day_start <= b["ready_to_fold_et"] <= day_end
    ]
    waiting = [b for b in bags if b.get("status") == STATUS_WAITING]
    ready_times = [b["ready_to_fold_et"] for b in ready_on_day if ts_valid(b.get("ready_to_fold_et"))]

    peak_interval = None
    peak_available = 0
    for interval in intervals:
        count = int(interval.get("available_count") or 0)
        if peak_interval is None or count > peak_available:
            peak_available = count
            peak_interval = interval

    return {
        "total_bags_dried": len(dried),
        "total_bags_ready_to_fold": len(ready_on_day),
        "currently_waiting_to_fold": len(waiting),
        "first_bag_ready_et": min(ready_times) if ready_times else None,
        "peak_ready_interval_label": (peak_interval or {}).get("label"),
        "peak_ready_interval_start_et": (peak_interval or {}).get("interval_start_et"),
        "max_bags_waiting": peak_available,
        "drying_duration_minutes": (
            bags[0].get("drying_duration_minutes") if bags else DEFAULT_DRYING_DURATION_MINUTES
        ),
    }


def filter_ready_to_fold_bags(
    bags: Sequence[Mapping[str, Any]],
    *,
    bag_id_filter: str | None = None,
    machine_filter: str | None = None,
    order_type_filter: str | None = None,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    rows = [dict(b) for b in bags]

    if bag_id_filter:
        bid = _bag_key(bag_id_filter)
        rows = [r for r in rows if _bag_key(r.get("bag_id")) == bid]

    if machine_filter:
        mf = str(machine_filter).strip()
        rows = [r for r in rows if str(r.get("dryer_rack") or "").strip() == mf]

    if order_type_filter:
        ot = _normalize_service_type(order_type_filter)
        if ot and ot.lower() != "all":
            rows = [r for r in rows if _normalize_service_type(r.get("service_type")) == ot]

    sf = str(status_filter or "all").strip().lower()
    if sf in VALID_STATUS_FILTERS and sf != "all":
        rows = [r for r in rows if r.get("status") == sf]

    for idx, row in enumerate(rows):
        row["index"] = idx + 1
    return rows


def _load_scan_events_window(
    cursor,
    organization_id: int,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
               last_location, last_scan, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        ORDER BY scanned_at_parsed, scan_index, id
        """,
        (int(organization_id), window_start, window_end),
    )
    return [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def _load_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Full bag timelines for lifecycle anchoring on repeat-trip / re-intake bags."""
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    org = int(organization_id)
    out: list[dict[str, Any]] = []
    ids = sorted({_bag_key(b) for b in bag_ids if _bag_key(b)})
    chunk = 100
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
                   last_location, last_scan, raw_json
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part),
        )
        out.extend(dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict))
    return out


def build_ready_to_fold_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    drying_duration_minutes: int | None = None,
    bag_id_filter: str | None = None,
    machine_filter: str | None = None,
    order_type_filter: str | None = None,
    status_filter: str | None = None,
    view_mode: str | None = None,
    as_of: datetime | None = None,
    # Accepted for API symmetry with other stages; unused for bag-status report.
    employee_filter: str | None = None,
    confidence_filter: str | None = None,
) -> dict[str, Any]:
    del employee_filter, confidence_filter  # unused

    duration = clamp_drying_duration_minutes(
        drying_duration_minutes
        if drying_duration_minutes is not None
        else DEFAULT_DRYING_DURATION_MINUTES
    )
    mode = str(view_mode or "both").strip().lower()
    if mode not in VALID_VIEW_MODES:
        mode = "both"

    # Prior calendar day through selected day end — overnight drying + same-day folding.
    window_start = naive_et_day_start(selected_date_et - timedelta(days=1))
    window_end = naive_et_day_end_inclusive(selected_date_et)
    if as_of is not None:
        as_of_ts = as_of
    elif selected_date_et == eastern_today():
        # Naive ET wall clock for status comparisons against scanned_at_parsed.
        now = eastern_now()
        as_of_ts = now.replace(tzinfo=None)
        if as_of_ts > window_end:
            as_of_ts = window_end
    else:
        as_of_ts = window_end

    window_events = _load_scan_events_window(cursor, organization_id, window_start, window_end)
    window_drying_rows = extract_drying_rows_from_events(window_events)

    candidate_ids = sorted(
        {
            _bag_key(r.get("bag_id"))
            for r in window_drying_rows
            if _bag_key(r.get("bag_id"))
        }
    )
    if bag_id_filter:
        needle = _bag_key(bag_id_filter)
        candidate_ids = [bid for bid in candidate_ids if bid == needle]

    # Full timelines so sent-to-vendor anchors outside the 2-day window still apply.
    full_events = _load_scan_events_for_bags(cursor, organization_id, candidate_ids)
    events_by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in full_events:
        bid = _bag_key(ev.get("bag_id"))
        if bid:
            events_by_bag.setdefault(bid, []).append(ev)

    # Drying rows from full timelines (not just the lookback window) so redry / prior-day
    # drying in the current lifecycle are available for selection.
    drying_rows = extract_drying_rows_from_events(full_events)

    metadata = _load_bag_metadata(cursor, organization_id, candidate_ids)

    bags = build_ready_to_fold_bag_records(
        drying_rows=drying_rows,
        events_by_bag=events_by_bag,
        metadata_by_bag=metadata,
        selected_date_et=selected_date_et,
        drying_duration_minutes=duration,
        as_of=as_of_ts,
    )

    machines = sorted(
        {str(b.get("dryer_rack") or "").strip() for b in bags if b.get("dryer_rack")},
        key=lambda name: name.casefold(),
    )
    order_types = sorted(
        {str(b.get("service_type") or "").strip() for b in bags if b.get("service_type")},
        key=lambda name: name.casefold(),
    )

    filtered = filter_ready_to_fold_bags(
        bags,
        bag_id_filter=bag_id_filter,
        machine_filter=machine_filter,
        order_type_filter=order_type_filter,
        status_filter=status_filter,
    )
    intervals = build_ready_to_fold_intervals(filtered, selected_date_et=selected_date_et)
    summary = build_ready_to_fold_summary(
        filtered, intervals, selected_date_et=selected_date_et
    )
    summary["drying_duration_minutes"] = duration

    # Compact interval payload for the table; bag lists kept for expand-in-place UI.
    interval_rows = []
    for interval in intervals:
        newly = interval["newly_ready_bags"]
        available = interval["available_bags"]
        if mode == "newly_ready":
            detail_bags = newly
        elif mode == "cumulative":
            detail_bags = available
        else:
            # Prefer newly ready bag identities first, then remaining available.
            seen = {b["bag_id"] for b in newly}
            detail_bags = list(newly) + [b for b in available if b["bag_id"] not in seen]

        interval_rows.append(
            {
                "interval_start_et": interval["interval_start_et"],
                "interval_end_et": interval["interval_end_et"],
                "label": interval["label"],
                "newly_ready_count": interval["newly_ready_count"],
                "available_count": interval["available_count"],
                "bags": detail_bags,
            }
        )

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "ready_to_fold",
        "drying_duration_minutes": duration,
        "view_mode": mode,
        "summary": summary,
        "intervals": interval_rows,
        "sessions": filtered,
        "bags": filtered,
        "machines": machines,
        "order_types": order_types,
        "status_options": sorted(VALID_STATUS_FILTERS - {"all"}),
        "employees": [],
        "event_purposes": None,
        "grouping_rules": (
            "Ready to Fold = drying scan time + drying duration minutes (0–1440). "
            "One bag per current lifecycle drying cycle: latest dryer-rack drying scan "
            "on/after the latest sent-to-vendor at or before the selected day. "
            "Redry within the same lifecycle replaces the earlier dry (no double count). "
            "Prior-day drying is included when ready-to-fold falls on the selected ET day "
            "or the bag is still waiting at day start. "
            "Folding start = first FOLDING rack/purpose scan after the drying scan. "
            "Intervals are half-open 15-minute buckets [start, start+15) from 12:00 AM "
            "through 11:45 PM ET."
        ),
    }
