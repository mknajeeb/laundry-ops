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
    lifecycle_anchor_as_of,
    ts_valid,
)
from backend.rinse_drying_chronology import extract_drying_rows_from_events
from backend.rinse_folding_et import (
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


def drying_scan_on_selected_date(dry_ts: datetime, selected_date_et: date) -> bool:
    """selected_date_start <= DryingScan < selected_date_end (ET day)."""
    day_start = naive_et_day_start(selected_date_et)
    day_end_exclusive = day_start + timedelta(days=1)
    return bool(ts_valid(dry_ts) and day_start <= dry_ts < day_end_exclusive)


def ready_time_for_interval_bucket(
    ready_et: datetime,
    selected_date_et: date,
) -> datetime | None:
    """
    Map ReadyTime onto the selected drying day's 96 intervals.

    ReadyTimes at/after the next midnight still belong to the drying day and are
    counted in the final 11:45 PM bucket.
    """
    if not ts_valid(ready_et):
        return None
    day_start = naive_et_day_start(selected_date_et)
    day_end_exclusive = day_start + timedelta(days=1)
    if ready_et < day_start:
        return None
    if ready_et >= day_end_exclusive:
        return day_end_exclusive - timedelta(microseconds=1)
    return ready_et


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
    Selected-day drying output only.

    Include a bag iff its lifecycle-anchored drying scan falls on the selected
    ET date. ReadyTime may spill past midnight; folding is ignored entirely.
    """
    del as_of  # status / folding as-of no longer used
    duration = clamp_drying_duration_minutes(drying_duration_minutes)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    records: list[dict[str, Any]] = []
    selected_drying = select_current_cycle_drying_rows(
        drying_rows,
        events_by_bag,
        as_of_end=day_end,
    )
    for dry in selected_drying:
        bid = _bag_key(dry.get("bag_id"))
        dry_ts = dry.get("timestamp_et")
        if not bid or not drying_scan_on_selected_date(dry_ts, selected_date_et):
            continue
        ready_et = dry_ts + timedelta(minutes=duration)

        meta = metadata_by_bag.get(bid) or {}
        service_type = _normalize_service_type(meta.get("service_type"))
        weight = meta.get("weight_num")
        if weight is None:
            weight = meta.get("weight_lbs")

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
                "confidence": dry.get("confidence"),
                "scan_event_id": dry.get("scan_event_id"),
                "ready_spills_next_day": ready_et.date() > selected_date_et,
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


def build_ready_to_fold_intervals(
    bags: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    """
    Capacity intervals for selected-day drying output.

    - New Bags Ready: half-open [start, end) on ReadyTime (overflow → 11:45 PM)
    - Cumulative Bags Ready: starts at 0; Cumulative(i)=Cumulative(i-1)+New(i)
    Folding and prior-day carry-in are not used.
    """
    interval_starts = build_day_interval_starts(selected_date_et)
    day_end_exclusive = naive_et_day_start(selected_date_et) + timedelta(days=1)

    cumulative_bags: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()

    intervals: list[dict[str, Any]] = []
    for start in interval_starts:
        end = start + timedelta(minutes=INTERVAL_MINUTES)
        if end > day_end_exclusive:
            end = day_end_exclusive

        newly = []
        for b in bags:
            bucket_ts = ready_time_for_interval_bucket(
                b.get("ready_to_fold_et"),
                selected_date_et,
            )
            if bucket_ts is not None and start <= bucket_ts < end:
                newly.append(b)

        for b in newly:
            bid = _bag_key(b.get("bag_id"))
            if bid and bid not in seen_ids:
                cumulative_bags.append(b)
                seen_ids.add(bid)

        cumulative_count = len(cumulative_bags)
        intervals.append(
            {
                "interval_start_et": start,
                "interval_end_et": end,
                "label": start.strftime("%I:%M %p").lstrip("0"),
                "newly_ready_count": len(newly),
                "cumulative_ready_count": cumulative_count,
                "available_count": cumulative_count,
                "newly_ready_bags": newly,
                "cumulative_ready_bags": list(cumulative_bags),
                "available_bags": list(cumulative_bags),
            }
        )
    return intervals


def build_ready_to_fold_summary(
    bags: Sequence[Mapping[str, Any]],
    intervals: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> dict[str, Any]:
    del selected_date_et  # population already scoped to selected-day drying
    dried = [b for b in bags if ts_valid(b.get("drying_scan_et"))]
    with_ready = [b for b in bags if ts_valid(b.get("ready_to_fold_et"))]
    ready_times = [b["ready_to_fold_et"] for b in with_ready]

    peak_newly_interval = None
    peak_newly = 0
    peak_cum_interval = None
    peak_cum = 0
    for interval in intervals:
        newly = int(interval.get("newly_ready_count") or 0)
        cum = int(
            interval.get("cumulative_ready_count")
            if interval.get("cumulative_ready_count") is not None
            else interval.get("available_count")
            or 0
        )
        if peak_newly_interval is None or newly > peak_newly:
            peak_newly = newly
            peak_newly_interval = interval
        if peak_cum_interval is None or cum > peak_cum:
            peak_cum = cum
            peak_cum_interval = interval

    peak_newly_label = (peak_newly_interval or {}).get("label")
    peak_cum_label = (peak_cum_interval or {}).get("label")
    return {
        "total_bags_dried": len(dried),
        "total_bags_ready": len(with_ready),
        "total_bags_ready_to_fold": len(with_ready),
        "total_bags_ready_today": len(with_ready),
        "first_bag_ready_et": min(ready_times) if ready_times else None,
        "peak_15min_ready_count": peak_newly,
        "peak_15min_ready_label": peak_newly_label,
        "peak_15min_ready_start_et": (peak_newly_interval or {}).get("interval_start_et"),
        "peak_cumulative_ready_count": peak_cum,
        "peak_cumulative_ready_label": peak_cum_label,
        "peak_cumulative_ready_start_et": (peak_cum_interval or {}).get("interval_start_et"),
        # Legacy aliases
        "peak_ready_interval_label": peak_newly_label,
        "peak_ready_interval_start_et": (peak_newly_interval or {}).get("interval_start_et"),
        "peak_waiting_label": peak_cum_label,
        "peak_waiting_count": peak_cum,
        "max_bags_waiting": peak_cum,
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

    # Status / folding filters are intentionally ignored — drying-only report.
    del status_filter

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

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    day_end_exclusive = day_start + timedelta(days=1)
    # Look back one day only to discover candidate bag ids that dried on selected day
    # when scans sit near midnight; lifecycle uses full bag timelines below.
    window_start = day_start - timedelta(days=1)
    window_end = day_end
    del as_of  # folding / as-of status removed

    window_events = _load_scan_events_window(cursor, organization_id, window_start, window_end)
    window_drying_rows = extract_drying_rows_from_events(window_events)

    # Candidate bags = those with a drying extract on the selected ET date only.
    candidate_ids = sorted(
        {
            _bag_key(r.get("bag_id"))
            for r in window_drying_rows
            if drying_scan_on_selected_date(r.get("timestamp_et"), selected_date_et)
            and _bag_key(r.get("bag_id"))
        }
    )
    if bag_id_filter:
        needle = _bag_key(bag_id_filter)
        candidate_ids = [bid for bid in candidate_ids if bid == needle]

    # Full timelines so sent-to-vendor anchors outside the window still apply.
    full_events = _load_scan_events_for_bags(cursor, organization_id, candidate_ids)
    events_by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in full_events:
        bid = _bag_key(ev.get("bag_id"))
        if bid:
            events_by_bag.setdefault(bid, []).append(ev)

    drying_rows = extract_drying_rows_from_events(full_events)
    metadata = _load_bag_metadata(cursor, organization_id, candidate_ids)

    bags = build_ready_to_fold_bag_records(
        drying_rows=drying_rows,
        events_by_bag=events_by_bag,
        metadata_by_bag=metadata,
        selected_date_et=selected_date_et,
        drying_duration_minutes=duration,
        as_of=day_end,
    )
    # Defensive: never include prior-day drying even if selection misfires.
    bags = [
        b
        for b in bags
        if drying_scan_on_selected_date(b.get("drying_scan_et"), selected_date_et)
    ]
    del day_end_exclusive

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
        cumulative = interval["cumulative_ready_bags"]
        if mode == "newly_ready":
            detail_bags = newly
        elif mode == "cumulative":
            detail_bags = cumulative
        else:
            seen = {b["bag_id"] for b in newly}
            detail_bags = list(newly) + [b for b in cumulative if b["bag_id"] not in seen]

        # Strip any folding fields from detail payloads.
        detail_bags = [
            {
                "bag_id": b.get("bag_id"),
                "drying_scan_et": b.get("drying_scan_et"),
                "ready_to_fold_et": b.get("ready_to_fold_et"),
                "drying_duration_minutes": b.get("drying_duration_minutes"),
                "dryer_rack": b.get("dryer_rack"),
                "weight": b.get("weight"),
                "order_type": b.get("order_type") or b.get("service_type"),
                "service_type": b.get("service_type"),
                "ready_spills_next_day": b.get("ready_spills_next_day"),
            }
            for b in detail_bags
        ]

        interval_rows.append(
            {
                "interval_start_et": interval["interval_start_et"],
                "interval_end_et": interval["interval_end_et"],
                "label": interval["label"],
                "newly_ready_count": interval["newly_ready_count"],
                "cumulative_ready_count": interval["cumulative_ready_count"],
                "available_count": interval["available_count"],
                "bags": detail_bags,
            }
        )

    sessions = [
        {
            "bag_id": b.get("bag_id"),
            "drying_scan_et": b.get("drying_scan_et"),
            "ready_to_fold_et": b.get("ready_to_fold_et"),
            "drying_duration_minutes": b.get("drying_duration_minutes"),
            "dryer_rack": b.get("dryer_rack"),
            "weight": b.get("weight"),
            "order_type": b.get("order_type") or b.get("service_type"),
            "service_type": b.get("service_type"),
            "ready_spills_next_day": b.get("ready_spills_next_day"),
            "index": b.get("index"),
        }
        for b in filtered
    ]

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "ready_to_fold",
        "drying_duration_minutes": duration,
        "view_mode": mode,
        "summary": summary,
        "intervals": interval_rows,
        "sessions": sessions,
        "bags": sessions,
        "machines": machines,
        "order_types": order_types,
        "status_options": [],
        "employees": [],
        "event_purposes": None,
        "grouping_rules": (
            "Ready to Fold is selected-day drying output only: "
            "selected_date_start <= DryingScan < selected_date_end. "
            "ReadyTime = DryingScan + drying duration (may spill past midnight). "
            "Lifecycle-anchored drying (latest dry on/after latest sent-to-vendor). "
            "No prior-day carry-in. No folding scans. "
            "New Bags Ready = half-open [interval_start, interval_end); "
            "post-midnight ReadyTimes count in the 11:45 PM bucket. "
            "Cumulative Bags Ready starts at 0 and equals the running sum of New."
        ),
    }
