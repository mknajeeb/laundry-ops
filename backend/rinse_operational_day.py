"""Day-scoped operational events for weighing, sorting, and wash/dry.

One bounded read of RINSE_WF role segments and one bounded read of
``rinse_bag_scan_events`` for the requested Eastern day. Ordinary day views
do not load ``raw_json`` or a bag's full history.

Attribution requires both:

* the scan ``user_name`` maps to the employee, and
* the scan timestamp falls inside that employee's applicable role segment.

A neighboring scan never assigns the employee.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, ts_valid
from backend.rinse_folding_et import (
    eastern_now,
    naive_et_day_end_exclusive,
    naive_et_day_start,
)
from backend.rinse_machine_rack import (
    canonical_rack_for_event,
    is_dryer_rack_code,
    is_washer_rack_code,
)
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_drying_purpose,
    is_sent_to_vendor_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
)
from backend.rinse_sorting_session import is_wash_handoff_add_photos_scan

ROLE_SORT = "SORT"
ROLE_OPERATOR = "OPERATOR"
_CATEGORY = "RINSE_WF"


def _naive(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raw = raw.replace(tzinfo=None)
        return raw.replace(microsecond=0)
    return None


def _bag(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _naive_now(now: datetime | None) -> datetime:
    if now is None:
        now = eastern_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now.replace(microsecond=0)


def _weight_value(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def build_employee_name_index(
    user_map: Mapping[str, Mapping[str, Any]] | None,
    segments: Sequence[Mapping[str, Any]] | None,
) -> dict[str, tuple[int, str]]:
    """Map a portal/display name to exactly one employee. Ambiguous names drop out."""
    index: dict[str, tuple[int, str]] = {}
    ambiguous: set[str] = set()

    def add(name: Any, user_id: int, display: str) -> None:
        key = str(name or "").strip().casefold()
        if not key or user_id <= 0:
            return
        existing = index.get(key)
        if existing and existing[0] != user_id:
            ambiguous.add(key)
            return
        index[key] = (user_id, display or str(name).strip())

    for row in (user_map or {}).values():
        if not isinstance(row, Mapping):
            continue
        try:
            uid = int(row.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        display = str(row.get("display_name") or row.get("rinse_user_name") or "").strip()
        add(row.get("rinse_user_name"), uid, display)
        add(display, uid, display)
    for seg in segments or []:
        try:
            uid = int(seg.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        display = str(seg.get("display_name") or "").strip()
        add(display, uid, display)
    for key in ambiguous:
        index.pop(key, None)
    return index


def _resolve_employee(
    scan_name: Any,
    name_index: Mapping[str, tuple[int, str]],
) -> tuple[int, str] | None:
    key = str(scan_name or "").strip().casefold()
    if not key:
        return None
    hit = name_index.get(key)
    return hit if hit else None


def _covers(seg: Mapping[str, Any], ts: datetime, now: datetime) -> bool:
    start = _naive(seg.get("started_at"))
    if start is None or ts < start:
        return False
    end = _naive(seg.get("ended_at")) if seg.get("ended_at") is not None else now
    if end is None:
        return False
    return ts <= end


def _covering_segment(
    segments: Sequence[Mapping[str, Any]],
    user_id: int,
    ts: datetime,
    now: datetime,
    *,
    role: str | None,
) -> Mapping[str, Any] | None:
    hits = []
    for seg in segments:
        try:
            uid = int(seg.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid != user_id:
            continue
        if str(seg.get("category_code") or _CATEGORY).strip().upper() not in ("", _CATEGORY):
            if str(seg.get("category_code") or "").strip().upper() != _CATEGORY:
                continue
        code = str(seg.get("role_code") or "").strip().upper()
        if role and code != role:
            continue
        if _covers(seg, ts, now):
            hits.append(seg)
    if not hits:
        return None
    return max(hits, key=lambda s: _naive(s.get("started_at")) or datetime.min)


def _merged_hours(intervals: list[tuple[datetime, datetime]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    seconds = sum((end - start).total_seconds() for start, end in merged)
    return seconds / 3600.0


def role_hours(
    segments: Sequence[Mapping[str, Any]],
    user_id: int,
    role: str,
    selected_date_et: date,
    now: datetime,
) -> float:
    """Hours of one role on the selected day.

    A closed segment ends at its actual end. An open segment ends at the
    current time. Hours are the overlap with the selected Eastern day.
    """
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_exclusive(selected_date_et)
    clip_end = min(day_end, now)
    intervals: list[tuple[datetime, datetime]] = []
    for seg in segments:
        try:
            uid = int(seg.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid != user_id:
            continue
        if str(seg.get("role_code") or "").strip().upper() != role:
            continue
        start = _naive(seg.get("started_at"))
        if start is None:
            continue
        end = _naive(seg.get("ended_at")) if seg.get("ended_at") is not None else now
        if end is None:
            continue
        overlap_start = max(start, day_start)
        overlap_end = min(end, clip_end)
        if overlap_end > overlap_start:
            intervals.append((overlap_start, overlap_end))
    return _merged_hours(intervals)


def _group_events(events: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    by_bag: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for ev in events:
        bid = _bag(ev.get("bag_id"))
        if bid and ts_valid(event_ts(ev)):
            by_bag[bid].append(ev)
    return by_bag


def _stv_times(
    bag_events: Sequence[Mapping[str, Any]],
    prior_stv: datetime | None,
) -> list[datetime]:
    times = []
    if prior_stv is not None:
        wall = _naive(prior_stv)
        if wall is not None:
            times.append(wall)
    for ev in bag_events:
        if is_sent_to_vendor_purpose(ev.get("purpose")):
            ts = _naive(event_ts(ev))
            if ts is not None:
                times.append(ts)
    return times


def _anchor_before(stv_times: Sequence[datetime], ts: datetime) -> datetime | None:
    earlier = [t for t in stv_times if t <= ts]
    return max(earlier) if earlier else None


def _already_marked_before_day(
    prior: datetime | None,
    anchor: datetime | None,
    day_start: datetime,
) -> bool:
    wall = _naive(prior)
    if wall is None or anchor is None:
        return False
    return anchor < wall < day_start


def build_operational_views(
    *,
    events: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    prior_stv: Mapping[str, datetime] | None = None,
    prior_weight: Mapping[str, datetime] | None = None,
    prior_add_photos: Mapping[str, datetime] | None = None,
    name_index: Mapping[str, tuple[int, str]] | None = None,
    selected_date_et: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure day aggregation. ``events`` are the selected day's scans only."""
    now_wall = _naive_now(now)
    day_start = naive_et_day_start(selected_date_et)
    index = dict(name_index or {})
    by_bag = _group_events(events)
    prior_stv = prior_stv or {}
    prior_weight = prior_weight or {}
    prior_add_photos = prior_add_photos or {}

    weighing: list[dict[str, Any]] = []
    sorting: list[dict[str, Any]] = []
    washes: list[dict[str, Any]] = []
    dries: list[dict[str, Any]] = []
    wash_seen: set[tuple[str, datetime, str]] = set()
    dry_seen: set[tuple[str, datetime, str]] = set()

    for bid, bag_events in by_bag.items():
        ordered = sorted(bag_events, key=lambda ev: event_ts(ev) or datetime.min)
        anchors = _stv_times(ordered, prior_stv.get(bid))

        weight_rows = [
            ev for ev in ordered if is_weight_entry_purpose(ev.get("purpose"))
        ]
        first_weight_by_anchor: dict[datetime, Mapping[str, Any]] = {}
        for ev in weight_rows:
            ts = _naive(event_ts(ev))
            if ts is None or ts < day_start:
                continue
            anchor = _anchor_before(anchors, ts)
            if anchor is None or ts <= anchor:
                continue
            current = first_weight_by_anchor.get(anchor)
            if current is None or ts < (_naive(event_ts(current)) or ts):
                first_weight_by_anchor[anchor] = ev
        for anchor, ev in first_weight_by_anchor.items():
            if _already_marked_before_day(prior_weight.get(bid), anchor, day_start):
                continue
            who = _resolve_employee(ev.get("user_name"), index)
            ts = _naive(event_ts(ev))
            if who is None or ts is None:
                continue
            seg = _covering_segment(segments, who[0], ts, now_wall, role=None)
            if seg is None:
                continue
            weighing.append(
                {
                    "bag_id": bid,
                    "employee": who[1],
                    "user_id": who[0],
                    "time_et": ts,
                    "start_et": ts,
                    "end_et": ts,
                    "weight_lbs": _weight_value(ev.get("weight_lbs")),
                    "work_slot_role": str(seg.get("role_code") or "").strip().upper() or None,
                    "confidence": "exact",
                    "source": "weight-entry",
                    "event_purpose": "weight-entry",
                }
            )

        add_rows = [ev for ev in ordered if is_add_photos_purpose(ev.get("purpose"))]
        first_sort_by_anchor: dict[datetime, Mapping[str, Any]] = {}
        for ev in add_rows:
            ts = _naive(event_ts(ev))
            if ts is None or ts < day_start:
                continue
            if is_wash_handoff_add_photos_scan(ordered, ev, event_ts(ev) or ts):
                continue
            anchor = _anchor_before(anchors, ts)
            if anchor is None or ts <= anchor:
                continue
            wash_after = [
                _naive(event_ts(other))
                for other in ordered
                if is_start_cleaning_purpose(other.get("purpose"))
                and _naive(event_ts(other)) is not None
                and (_naive(event_ts(other)) or ts) > anchor
            ]
            first_wash = min((t for t in wash_after if t is not None), default=None)
            if first_wash is not None and ts > first_wash:
                continue
            current = first_sort_by_anchor.get(anchor)
            if current is None or ts < (_naive(event_ts(current)) or ts):
                first_sort_by_anchor[anchor] = ev
        for anchor, ev in first_sort_by_anchor.items():
            if _already_marked_before_day(prior_add_photos.get(bid), anchor, day_start):
                continue
            who = _resolve_employee(ev.get("user_name"), index)
            ts = _naive(event_ts(ev))
            if who is None or ts is None:
                continue
            seg = _covering_segment(segments, who[0], ts, now_wall, role=ROLE_SORT)
            if seg is None:
                continue
            sorting.append(
                {
                    "bag_id": bid,
                    "employee": who[1],
                    "user_id": who[0],
                    "sort_time_et": ts,
                    "time_et": ts,
                    "start_et": ts,
                    "end_et": ts,
                    "confidence": "exact",
                    "source": "add-photos",
                    "event_purpose": "add-photos",
                    "work_slot_role": ROLE_SORT,
                }
            )

        for ev in ordered:
            ts = _naive(event_ts(ev))
            if ts is None or ts < day_start:
                continue
            purpose = ev.get("purpose")
            if is_start_cleaning_purpose(purpose):
                rack = canonical_rack_for_event(ev, is_rack_code=is_washer_rack_code)
                if not rack:
                    continue
                key = (bid, ts, rack.upper())
                if key in wash_seen:
                    continue
                wash_seen.add(key)
                who = _resolve_employee(ev.get("user_name"), index)
                if who is None:
                    continue
                if _covering_segment(segments, who[0], ts, now_wall, role=ROLE_OPERATOR) is None:
                    continue
                washes.append(
                    {
                        "bag_id": bid,
                        "employee": who[1],
                        "user_id": who[0],
                        "timestamp_et": ts,
                        "washer_rack": rack,
                        "confidence": "exact",
                        "event_purpose": "start-cleaning",
                    }
                )
            elif is_drying_purpose(purpose):
                rack = canonical_rack_for_event(ev, is_rack_code=is_dryer_rack_code)
                if not rack:
                    continue
                key = (bid, ts, rack.upper())
                if key in dry_seen:
                    continue
                dry_seen.add(key)
                who = _resolve_employee(ev.get("user_name"), index)
                if who is None:
                    continue
                if _covering_segment(segments, who[0], ts, now_wall, role=ROLE_OPERATOR) is None:
                    continue
                dries.append(
                    {
                        "bag_id": bid,
                        "employee": who[1],
                        "user_id": who[0],
                        "timestamp_et": ts,
                        "dryer_rack": rack,
                        "confidence": "exact",
                        "event_purpose": "drying",
                    }
                )

    weighing.sort(key=lambda r: (r["time_et"], r["bag_id"]))
    sorting.sort(key=lambda r: (r["sort_time_et"], r["bag_id"]))
    washes.sort(key=lambda r: (r["timestamp_et"], r["bag_id"], r["washer_rack"]))
    dries.sort(key=lambda r: (r["timestamp_et"], r["bag_id"], r["dryer_rack"]))
    for idx, row in enumerate(weighing, start=1):
        row["index"] = idx
    for idx, row in enumerate(sorting, start=1):
        row["index"] = idx

    coupled = _couple_wash_dry(washes, dries)
    performance = _performance(
        segments, weighing, sorting, washes, dries, selected_date_et, now_wall
    )
    return {
        "date_et": selected_date_et.isoformat(),
        "weighing": weighing,
        "sorting": sorting,
        "washer_loads": washes,
        "dryer_loads": dries,
        "wash_dry": coupled,
        "performance": performance,
        "raw_json_loaded": False,
    }


def _couple_wash_dry(
    washes: Sequence[Mapping[str, Any]],
    dries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_bag: dict[str, dict[str, list]] = defaultdict(lambda: {"w": [], "d": []})
    for row in washes:
        by_bag[str(row["bag_id"])]["w"].append(row)
    for row in dries:
        by_bag[str(row["bag_id"])]["d"].append(row)
    out: list[dict[str, Any]] = []
    for bid in sorted(by_bag):
        ws = by_bag[bid]["w"]
        ds = by_bag[bid]["d"]
        for i in range(max(len(ws), len(ds))):
            wash = ws[i] if i < len(ws) else None
            dry = ds[i] if i < len(ds) else None
            wash_emp = wash.get("employee") if wash else None
            dry_emp = dry.get("employee") if dry else None
            out.append(
                {
                    "wash_dry_row": True,
                    "bag_id": bid,
                    "employee": wash_emp or dry_emp,
                    "washer_employee": wash_emp,
                    "dryer_employee": dry_emp,
                    "washer": wash.get("washer_rack") if wash else None,
                    "washer_rack": wash.get("washer_rack") if wash else None,
                    "wash_time_et": wash.get("timestamp_et") if wash else None,
                    "dryer": dry.get("dryer_rack") if dry else None,
                    "dryer_rack": dry.get("dryer_rack") if dry else None,
                    "dry_time_et": dry.get("timestamp_et") if dry else None,
                    "timestamp_et": (
                        (wash.get("timestamp_et") if wash else None)
                        or (dry.get("timestamp_et") if dry else None)
                    ),
                    "confidence": "exact",
                    "event_purpose": "wash-dry",
                }
            )
    for idx, row in enumerate(out, start=1):
        row["index"] = idx
    return out


def _performance(
    segments: Sequence[Mapping[str, Any]],
    weighing: Sequence[Mapping[str, Any]],
    sorting: Sequence[Mapping[str, Any]],
    washes: Sequence[Mapping[str, Any]],
    dries: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    now: datetime,
) -> list[dict[str, Any]]:
    people: dict[int, str] = {}
    for seg in segments:
        try:
            uid = int(seg.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid <= 0:
            continue
        people.setdefault(uid, str(seg.get("display_name") or "").strip() or f"user {uid}")
    for row in (*weighing, *sorting, *washes, *dries):
        uid = int(row.get("user_id") or 0)
        if uid:
            people.setdefault(uid, str(row.get("employee") or ""))

    weigh_bags: dict[int, set[str]] = defaultdict(set)
    sort_bags: dict[int, set[str]] = defaultdict(set)
    wash_n: dict[int, int] = defaultdict(int)
    dry_n: dict[int, int] = defaultdict(int)
    handled: dict[int, set[str]] = defaultdict(set)
    for row in weighing:
        weigh_bags[int(row["user_id"])].add(row["bag_id"])
    for row in sorting:
        sort_bags[int(row["user_id"])].add(row["bag_id"])
    for row in washes:
        wash_n[int(row["user_id"])] += 1
        handled[int(row["user_id"])].add(row["bag_id"])
    for row in dries:
        dry_n[int(row["user_id"])] += 1
        handled[int(row["user_id"])].add(row["bag_id"])

    rows = []
    for uid, name in people.items():
        sort_h = role_hours(segments, uid, ROLE_SORT, selected_date_et, now)
        op_h = role_hours(segments, uid, ROLE_OPERATOR, selected_date_et, now)
        n_sort = len(sort_bags[uid])
        if n_sort == 0 and sort_h == 0 and op_h == 0 and not weigh_bags[uid] and not handled[uid]:
            continue
        rows.append(
            {
                "user_id": uid,
                "employee": name,
                "weighing_bags": len(weigh_bags[uid]),
                "sorting_bags": n_sort,
                "sort_hours": round(sort_h, 4),
                "sorting_bags_per_hour": round(n_sort / sort_h, 2) if sort_h > 0 else None,
                "operator_hours": round(op_h, 4),
                "washer_loads": wash_n[uid],
                "dryer_loads": dry_n[uid],
                "unique_bags_handled": len(handled[uid]),
            }
        )
    rows.sort(key=lambda r: str(r["employee"]).casefold())
    return rows


def _apply_filters(
    rows: list[dict[str, Any]],
    *,
    employee_filter: str | None,
    bag_id_filter: str | None,
    machine_filter: str | None = None,
    machine_keys: Sequence[str] = (),
) -> list[dict[str, Any]]:
    out = rows
    if employee_filter:
        needle = str(employee_filter).strip().casefold()
        out = [
            r
            for r in out
            if needle
            and (
                str(r.get("employee") or "").strip().casefold() == needle
                or str(r.get("washer_employee") or "").strip().casefold() == needle
                or str(r.get("dryer_employee") or "").strip().casefold() == needle
            )
        ]
    if bag_id_filter:
        needle = _bag(bag_id_filter)
        out = [r for r in out if _bag(r.get("bag_id")) == needle]
    if machine_filter:
        needle = str(machine_filter).strip().casefold()
        keys = machine_keys or ("washer_rack", "dryer_rack", "machine")
        out = [
            r
            for r in out
            if any(str(r.get(k) or "").strip().casefold() == needle for k in keys)
        ]
    return out


def _employees(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(name).strip()
            for row in rows
            for name in (
                row.get("employee"),
                row.get("washer_employee"),
                row.get("dryer_employee"),
            )
            if str(name or "").strip()
        },
        key=lambda name: name.casefold(),
    )


def _performance_for_employee_filter(
    performance: Sequence[Mapping[str, Any]] | None,
    employee_filter: str | None,
) -> list[Mapping[str, Any]]:
    """Employee-scoped performance rows, or the full day list when unfiltered."""
    rows = list(performance or [])
    if not employee_filter:
        return rows
    needle = str(employee_filter).strip().casefold()
    if not needle:
        return rows
    return [
        p
        for p in rows
        if str(p.get("employee") or "").strip().casefold() == needle
    ]


def _sort_hours_for_summary(
    performance: Sequence[Mapping[str, Any]] | None,
    employee_filter: str | None,
) -> float:
    """Authoritative SORT hours matching the active employee filter.

    No filter → sum of applicable employee SORT role hours for the day.
    Employee filter → that employee's SORT role hours only.
    """
    return sum(
        float(p.get("sort_hours") or 0)
        for p in _performance_for_employee_filter(performance, employee_filter)
    )


def chronology_payload_from_views(
    views: Mapping[str, Any],
    stage: str,
    *,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
) -> dict[str, Any]:
    if confidence_filter and str(confidence_filter).strip().lower() == "inferred":
        rows: list[dict[str, Any]] = []
    elif stage == "weighing":
        rows = _apply_filters(
            list(views.get("weighing") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
        )
    elif stage == "sorting":
        rows = _apply_filters(
            list(views.get("sorting") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
        )
    elif stage in ("washing", "drying"):
        rows = _apply_filters(
            list(views.get("wash_dry") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
        )
    elif stage == "washer_utilization":
        loads = _apply_filters(
            list(views.get("washer_loads") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
            machine_keys=("washer_rack",),
        )
        rows = [
            {
                "index": i,
                "timestamp_et": row.get("timestamp_et"),
                "machine": row.get("washer_rack"),
                "employee": row.get("employee"),
                "bag_id": row.get("bag_id"),
            }
            for i, row in enumerate(loads, start=1)
        ]
    else:
        loads = _apply_filters(
            list(views.get("dryer_loads") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
            machine_keys=("dryer_rack",),
        )
        rows = [
            {
                "index": i,
                "timestamp_et": row.get("timestamp_et"),
                "machine": row.get("dryer_rack"),
                "employee": row.get("employee"),
                "bag_id": row.get("bag_id"),
            }
            for i, row in enumerate(loads, start=1)
        ]

    payload_washer_loads = list(views.get("washer_loads") or [])
    payload_dryer_loads = list(views.get("dryer_loads") or [])

    for i, row in enumerate(rows, start=1):
        row["index"] = i

    times = [
        t
        for row in rows
        for t in (
            row.get("time_et"),
            row.get("sort_time_et"),
            row.get("wash_time_et"),
            row.get("dry_time_et"),
            row.get("timestamp_et"),
        )
        if isinstance(t, datetime)
    ]
    if stage == "weighing":
        summary = {
            "total_bags": len({r["bag_id"] for r in rows}),
            "total_sessions": len(rows),
            "first_time_et": min(times) if times else None,
            "last_time_et": max(times) if times else None,
        }
        rules = (
            "One row per bag: the first weight-entry after the current sent-to-vendor "
            "anchor, counted only when that scan's employee is inside a RINSE_WF role "
            "segment. No duration, gap, or session."
        )
    elif stage == "sorting":
        # Bags come from filtered sorting rows; SORT hours must use the same
        # employee scope (never org-wide hours under an employee filter).
        sort_hours = _sort_hours_for_summary(
            views.get("performance") or [], employee_filter
        )
        bags = len({r["bag_id"] for r in rows})
        summary = {
            "total_bags": bags,
            "total_sessions": bags,
            "sort_hours": round(sort_hours, 4),
            "sorting_bags_per_hour": round(bags / sort_hours, 2) if sort_hours > 0 else None,
            "first_time_et": min(times) if times else None,
            "last_time_et": max(times) if times else None,
        }
        rules = (
            "One row per bag: qualifying sorting add-photos inside the employee's SORT "
            "segment. Wash-handoff add-photos are excluded. Open SORT hours end at the "
            "current time; closed segments end at the segment end. No start-to-end session. "
            "Summary SORT hours and bags/hr use the same employee scope as the rows."
        )
    elif stage in ("washing", "drying"):
        # Load KPIs must match the employee/bag/machine filter used for rows.
        payload_washer_loads = _apply_filters(
            list(views.get("washer_loads") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
            machine_keys=("washer_rack",),
        )
        payload_dryer_loads = _apply_filters(
            list(views.get("dryer_loads") or []),
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
            machine_keys=("dryer_rack",),
        )
        wash_n = len(payload_washer_loads)
        dry_n = len(payload_dryer_loads)
        bags = len(
            {r["bag_id"] for r in payload_washer_loads}
            | {r["bag_id"] for r in payload_dryer_loads}
        )
        summary = {
            "washer_loads": wash_n,
            "dryer_loads": dry_n,
            "unique_bags_handled": bags,
            "total_washer_loads": wash_n,
            "total_drying_scans": dry_n,
            "first_time_et": min(times) if times else None,
            "last_time_et": max(times) if times else None,
        }
        rules = (
            "Washer loads are start-cleaning on a washer rack. Dryer loads are drying on "
            "a dryer rack. Both count only inside OPERATOR time. Dedupe is bag + timestamp "
            "+ rack, so two machines in the same minute stay two loads. Summary load and "
            "unique-bag counts use the same employee filter as the displayed rows."
        )
    else:
        machines = sorted({str(r.get("machine") or "") for r in rows if r.get("machine")})
        summary = {
            "total_loads": len(rows),
            "unique_machines_used": len(machines),
            "most_used_machine": (
                Counter(str(r.get("machine") or "") for r in rows if r.get("machine")).most_common(1)[0][0]
                if rows
                else None
            ),
            "first_load_et": min(times) if times else None,
            "last_load_et": max(times) if times else None,
        }
        rules = "Machine utilization is the same OPERATOR wash/dry loads, not a second calculator."
        return {
            "date_et": views.get("date_et"),
            "stage": stage,
            "summary": summary,
            "sessions": rows,
            "employees": _employees(rows),
            "machines": machines,
            "event_purposes": None,
            "grouping_rules": rules,
            # Facility-wide per-employee breakdown; not narrowed by the row filter.
            "operational_performance": views.get("performance") or [],
            "raw_json_loaded": False,
        }

    return {
        "date_et": views.get("date_et"),
        "stage": stage,
        "summary": summary,
        "sessions": rows,
        "employees": _employees(rows),
        "machines": sorted(
            {
                str(r.get("washer_rack") or r.get("dryer_rack") or "")
                for r in rows
                if r.get("washer_rack") or r.get("dryer_rack")
            }
        ),
        "event_purposes": None,
        "grouping_rules": rules,
        # Facility-wide per-employee breakdown; not narrowed by the row filter.
        "operational_performance": views.get("performance") or [],
        "washer_loads": payload_washer_loads,
        "dryer_loads": payload_dryer_loads,
        "raw_json_loaded": False,
    }


def _chunked(ids: Sequence[str], size: int = 200):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


def _fetch_dicts(cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def load_operational_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bounded day read. No raw_json. No per-bag history."""
    from backend.rinse_simple_shift_performance import _load_rinse_user_maps
    from backend.ta_helpers import table_exists, table_has_column

    now_wall = _naive_now(now)
    empty = build_operational_views(
        events=[],
        segments=[],
        selected_date_et=selected_date_et,
        now=now_wall,
    )
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return empty

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_exclusive(selected_date_et)
    cols = ["bag_id", "id", "rack", "user_name", "purpose", "scanned_at_parsed", "scan_index"]
    if table_has_column(cursor, "rinse_bag_scan_events", "weight_lbs"):
        cols.append("weight_lbs")
    if table_has_column(cursor, "rinse_bag_scan_events", "last_location"):
        cols.append("last_location")
    if table_has_column(cursor, "rinse_bag_scan_events", "last_scan"):
        cols.append("last_scan")
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
        ORDER BY scanned_at_parsed, scan_index, id
        """,
        (int(organization_id), day_start, day_end),
    )
    events = _fetch_dicts(cursor)

    segments = _load_role_segments(cursor, organization_id, day_start, day_end)
    user_map = _load_rinse_user_maps(cursor, int(organization_id))
    name_index = build_employee_name_index(user_map, segments)

    candidates = sorted(
        {
            _bag(ev.get("bag_id"))
            for ev in events
            if is_weight_entry_purpose(ev.get("purpose")) or is_add_photos_purpose(ev.get("purpose"))
        }
    )
    prior_stv, prior_weight, prior_add = _load_prior_markers(
        cursor, int(organization_id), candidates, day_start, day_end
    )
    return build_operational_views(
        events=events,
        segments=segments,
        prior_stv=prior_stv,
        prior_weight=prior_weight,
        prior_add_photos=prior_add,
        name_index=name_index,
        selected_date_et=selected_date_et,
        now=now_wall,
    )


def _load_role_segments(cursor, organization_id: int, day_start: datetime, day_end: datetime):
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "shift_job_segments") or not table_exists(cursor, "shift_sessions"):
        return []
    if table_exists(cursor, "users") and table_has_column(cursor, "users", "display_name"):
        display_expr = "u.display_name"
        join_users = "LEFT JOIN users u ON u.id = sjs.user_id"
    else:
        display_expr = "NULL"
        join_users = ""
    cursor.execute(
        f"""
        SELECT sjs.user_id, sjs.role_code, sjs.category_code, sjs.started_at, sjs.ended_at,
               {display_expr} AS display_name
        FROM shift_job_segments sjs
        JOIN shift_sessions ss ON ss.id = sjs.shift_session_id
        {join_users}
        WHERE ss.organization_id = %s
          AND UPPER(COALESCE(sjs.category_code, '')) = 'RINSE_WF'
          AND sjs.started_at < %s
          AND (sjs.ended_at IS NULL OR sjs.ended_at > %s)
        """,
        (int(organization_id), day_end, day_start),
    )
    out = []
    for row in _fetch_dicts(cursor):
        try:
            uid = int(row.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid <= 0:
            continue
        row["user_id"] = uid
        row["role_code"] = str(row.get("role_code") or "").strip().upper()
        row["category_code"] = _CATEGORY
        row["display_name"] = str(row.get("display_name") or "").strip()
        out.append(row)
    return out


def _load_prior_markers(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    day_start: datetime,
    day_end: datetime,
) -> tuple[dict[str, datetime], dict[str, datetime], dict[str, datetime]]:
    stv: dict[str, datetime] = {}
    weight: dict[str, datetime] = {}
    photos: dict[str, datetime] = {}
    if not bag_ids:
        return stv, weight, photos
    for part in _chunked(list(bag_ids)):
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, MAX(scanned_at_parsed) AS stv_at
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed < %s
              AND LOWER(COALESCE(purpose, '')) LIKE 'sent-to-vendor%%'
            GROUP BY bag_id
            """,
            (organization_id, *part, day_end),
        )
        for row in _fetch_dicts(cursor):
            bid = _bag(row.get("bag_id"))
            ts = _naive(row.get("stv_at"))
            if bid and ts is not None:
                stv[bid] = ts
        cursor.execute(
            f"""
            SELECT bag_id,
                   MAX(CASE WHEN LOWER(COALESCE(purpose, '')) = 'weight-entry'
                            THEN scanned_at_parsed END) AS last_weight,
                   MAX(CASE WHEN LOWER(COALESCE(purpose, '')) = 'add-photos'
                            THEN scanned_at_parsed END) AS last_photos
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed < %s
              AND LOWER(COALESCE(purpose, '')) IN ('weight-entry', 'add-photos')
            GROUP BY bag_id
            """,
            (organization_id, *part, day_start),
        )
        for row in _fetch_dicts(cursor):
            bid = _bag(row.get("bag_id"))
            if not bid:
                continue
            w = _naive(row.get("last_weight"))
            p = _naive(row.get("last_photos"))
            if w is not None:
                weight[bid] = w
            if p is not None:
                photos[bid] = p
    return stv, weight, photos


def build_operational_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    stage: str,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
    views: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if views is None:
        views = load_operational_day(
            cursor, organization_id, selected_date_et, now=now
        )
    return chronology_payload_from_views(
        views,
        stage,
        employee_filter=employee_filter,
        bag_id_filter=bag_id_filter,
        confidence_filter=confidence_filter,
        machine_filter=machine_filter,
    )
