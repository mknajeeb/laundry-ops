"""
Read-only Process Flow chronology for Scan Chronology.

Composes existing Sorting / Washing / Drying current-cycle selectors into one
row per bag. Does not redefine canonical scan selection.

Process Flow bag table: Ready-to-Fold time is calculated as dry + assumption
(default 40; NOT rinse_processing_settings.drying_minutes=45).

Process Flow queue calculator (see rinse_process_flow_queue):
- No Sort/Wash duration assumptions — uses actual canonical times
- Folding completion from evaluate_folding_performance_for_bag → folding_end_at
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, ts_valid
from backend.rinse_drying_chronology import extract_drying_rows_from_events
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_ready_to_fold_chronology import (
    DEFAULT_DRYING_DURATION_MINUTES,
    drying_scan_on_selected_date,
    select_current_cycle_drying_rows,
    select_current_lifecycle_drying_row,
)
from backend.rinse_sorting_chronology import (
    extract_sorting_sessions_for_bag,
    select_current_cycle_sorting_sessions,
    select_current_lifecycle_sorting_session,
)
from backend.rinse_washing_chronology import (
    extract_washing_rows_from_events,
    select_current_cycle_washing_rows,
    select_current_lifecycle_washing_row,
)
from backend.ta_helpers import table_exists

# Re-export selector names so callers/tests can assert composition reuse.
__all__ = [
    "build_process_flow_chronology_payload",
    "build_process_flow_calculator_payload",
    "compose_process_flow_bag_row",
    "derive_current_stage",
    "derive_sequence_status",
    "assign_ready_times_to_slots",
    "DEFAULT_SORT_ASSUMPTION_MINUTES",
    "DEFAULT_WASH_ASSUMPTION_MINUTES",
    "DEFAULT_DRY_ASSUMPTION_MINUTES",
    "MAX_CHECKPOINT_SLOTS",
    "select_current_lifecycle_sorting_session",
    "select_current_cycle_sorting_sessions",
    "select_current_lifecycle_washing_row",
    "select_current_cycle_washing_rows",
    "select_current_lifecycle_drying_row",
    "select_current_cycle_drying_rows",
]

DEFAULT_SORT_ASSUMPTION_MINUTES = 0
DEFAULT_WASH_ASSUMPTION_MINUTES = 0
DEFAULT_DRY_ASSUMPTION_MINUTES = DEFAULT_DRYING_DURATION_MINUTES  # 40
MAX_CHECKPOINT_SLOTS = 48

CURRENT_AWAITING_SORT = "Awaiting Sort"
CURRENT_SORTED = "Sorted / Ready for Washing"
CURRENT_WASHED = "Washed / Ready for Drying"
CURRENT_DRYING = "Drying"
CURRENT_READY_TO_FOLD = "Ready to Fold"
CURRENT_SEQUENCE_EXCEPTION = "Sequence Exception"

SEQ_VALID = "Valid"
SEQ_MISSING_SORT = "Missing Sort"
SEQ_MISSING_WASH = "Missing Wash"
SEQ_MISSING_DRY = "Missing Dry"
SEQ_WASH_BEFORE_SORT = "Wash Before Sort"
SEQ_DRY_BEFORE_WASH = "Dry Before Wash"
SEQ_DRY_BEFORE_SORT = "Dry Before Sort"
SEQ_CONFLICTING = "Conflicting Evidence"


class ProcessFlowValidationError(ValueError):
    """Invalid Process Flow calculator inputs."""


def _bag_key(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _require_int(value: Any, *, field: str) -> int:
    """Reject non-integers (including decimal floats/strings); no silent truncation."""
    if isinstance(value, bool):
        raise ProcessFlowValidationError(f"{field} must be an integer.")
    if isinstance(value, float):
        if not value.is_integer():
            raise ProcessFlowValidationError(f"{field} must be an integer.")
        return int(value)
    if isinstance(value, int):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise ProcessFlowValidationError(f"{field} is required.")
    if "." in raw or "e" in raw.lower():
        raise ProcessFlowValidationError(f"{field} must be an integer.")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ProcessFlowValidationError(f"{field} must be an integer.") from exc


def clamp_sort_assumption_minutes(value: Any) -> int:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return DEFAULT_SORT_ASSUMPTION_MINUTES
    minutes = _require_int(value, field="Sort Assumption (Minutes)")
    if minutes < 0 or minutes > 1440:
        raise ProcessFlowValidationError(
            "Sort Assumption (Minutes) must be between 0 and 1440."
        )
    return minutes


def clamp_wash_assumption_minutes(value: Any) -> int:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return DEFAULT_WASH_ASSUMPTION_MINUTES
    minutes = _require_int(value, field="Wash Assumption (Minutes)")
    if minutes < 0 or minutes > 1440:
        raise ProcessFlowValidationError(
            "Wash Assumption (Minutes) must be between 0 and 1440."
        )
    return minutes


def clamp_dry_assumption_minutes(value: Any) -> int:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return DEFAULT_DRY_ASSUMPTION_MINUTES
    minutes = _require_int(value, field="Dry Assumption (Minutes)")
    if minutes < 1 or minutes > 1440:
        raise ProcessFlowValidationError(
            "Dry Assumption (Minutes) must be between 1 and 1440."
        )
    return minutes


def _format_checkpoint_clock(ts: datetime) -> str:
    return ts.strftime("%I:%M %p").lstrip("0")


def parse_checkpoint_datetime(value: Any, *, selected_date_et: date) -> datetime:
    if isinstance(value, datetime):
        if not ts_valid(value):
            raise ProcessFlowValidationError("Invalid checkpoint datetime.")
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    raw = str(value or "").strip()
    if not raw:
        raise ProcessFlowValidationError("Checkpoint time is required.")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            clock = datetime.strptime(raw, fmt).time()
            return datetime.combine(selected_date_et, clock)
        except ValueError:
            continue
    raise ProcessFlowValidationError(
        f"Unrecognized checkpoint time: {raw!r}. Use HH:MM or ISO datetime."
    )


def validate_checkpoint_times(
    checkpoints: Sequence[Any],
    *,
    selected_date_et: date,
) -> list[datetime]:
    if not checkpoints:
        raise ProcessFlowValidationError("At least one checkpoint time is required.")
    if len(checkpoints) > MAX_CHECKPOINT_SLOTS:
        raise ProcessFlowValidationError(
            f"Number of time slots cannot exceed {MAX_CHECKPOINT_SLOTS}."
        )
    parsed = [
        parse_checkpoint_datetime(value, selected_date_et=selected_date_et)
        for value in checkpoints
    ]
    for idx in range(1, len(parsed)):
        if parsed[idx] <= parsed[idx - 1]:
            raise ProcessFlowValidationError(
                f"Slot {idx + 1} must be later than Slot {idx}. "
                "Checkpoint times must be in chronological order."
            )
    return parsed


def _on_selected_day(ts: datetime | None, selected_date_et: date) -> bool:
    if not ts_valid(ts):
        return False
    day_start = naive_et_day_start(selected_date_et)
    return day_start <= ts < day_start + timedelta(days=1)


def _session_touches_selected_day(session: Mapping[str, Any], selected_date_et: date) -> bool:
    start = session.get("sort_start_et")
    end = session.get("sort_end_et") or start
    if _on_selected_day(start, selected_date_et) or _on_selected_day(end, selected_date_et):
        return True
    if not (ts_valid(start) and ts_valid(end)):
        return False
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    return start <= day_end and end >= day_start


def derive_sequence_status(
    *,
    sort_ts: datetime | None,
    wash_ts: datetime | None,
    dry_ts: datetime | None,
) -> dict[str, Any]:
    codes: list[str] = []
    if sort_ts is None:
        codes.append(SEQ_MISSING_SORT)
    if wash_ts is None:
        codes.append(SEQ_MISSING_WASH)
    if dry_ts is None:
        codes.append(SEQ_MISSING_DRY)

    if sort_ts is not None and wash_ts is not None and wash_ts < sort_ts:
        codes.append(SEQ_WASH_BEFORE_SORT)
    if wash_ts is not None and dry_ts is not None and dry_ts < wash_ts:
        codes.append(SEQ_DRY_BEFORE_WASH)
    if sort_ts is not None and dry_ts is not None and dry_ts < sort_ts:
        codes.append(SEQ_DRY_BEFORE_SORT)

    order_codes = {
        SEQ_WASH_BEFORE_SORT,
        SEQ_DRY_BEFORE_WASH,
        SEQ_DRY_BEFORE_SORT,
    }
    if len(order_codes.intersection(codes)) >= 2:
        if SEQ_CONFLICTING not in codes:
            codes.append(SEQ_CONFLICTING)

    if not codes:
        return {
            "sequence_status": SEQ_VALID,
            "sequence_codes": [SEQ_VALID],
            "has_sequence_exception": False,
        }

    # Prefer a readable primary label: first missing, else first order issue.
    primary = codes[0]
    label = primary if len(codes) == 1 else "; ".join(codes)
    return {
        "sequence_status": label,
        "sequence_codes": codes,
        "has_sequence_exception": True,
    }


def derive_current_stage(
    *,
    sort_ts: datetime | None,
    wash_ts: datetime | None,
    dry_ts: datetime | None,
    ready_et: datetime | None,
    now_et: datetime | None,
    has_sequence_exception: bool,
) -> str:
    if has_sequence_exception and (sort_ts is None or wash_ts is None or dry_ts is None):
        # Keep exception visible when missing stages mix with later evidence,
        # but still prefer Ready to Fold when dry+ready already elapsed.
        pass
    if has_sequence_exception and not (
        dry_ts is not None and ready_et is not None and now_et is not None and now_et >= ready_et
    ):
        # If we have order conflicts with all three present, flag exception.
        if sort_ts and wash_ts and dry_ts and (
            wash_ts < sort_ts or dry_ts < wash_ts or dry_ts < sort_ts
        ):
            return CURRENT_SEQUENCE_EXCEPTION

    if dry_ts is not None and ready_et is not None:
        if now_et is not None and now_et >= ready_et:
            return CURRENT_READY_TO_FOLD
        return CURRENT_DRYING
    if wash_ts is not None:
        return CURRENT_WASHED
    if sort_ts is not None:
        return CURRENT_SORTED
    return CURRENT_AWAITING_SORT


def _rack_near_time(
    events: Sequence[Mapping[str, Any]],
    at: datetime | None,
) -> str | None:
    if not ts_valid(at):
        return None
    best = None
    best_delta = None
    for ev in events:
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        rack = str(ev.get("rack") or "").strip()
        if not rack:
            continue
        delta = abs((ts - at).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = rack
    return best


def _confidence_rank(value: Any) -> int:
    v = str(value or "").strip().lower()
    if v == "exact":
        return 2
    if v == "inferred":
        return 1
    return 0


def _combined_confidence(*values: Any) -> str | None:
    present = [str(v).strip() for v in values if v]
    if not present:
        return None
    return min(present, key=_confidence_rank)


def compose_process_flow_bag_row(
    *,
    bag_id: str,
    sort_session: Mapping[str, Any] | None,
    wash_row: Mapping[str, Any] | None,
    dry_row: Mapping[str, Any] | None,
    bag_events: Sequence[Mapping[str, Any]] | None = None,
    dry_assumption_minutes: int = DEFAULT_DRY_ASSUMPTION_MINUTES,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Compose one Process Flow row from already-selected canonical stage evidence."""
    bid = _bag_key(bag_id)
    sort_ts = sort_session.get("sort_start_et") if sort_session else None
    wash_ts = wash_row.get("timestamp_et") if wash_row else None
    dry_ts = dry_row.get("timestamp_et") if dry_row else None
    ready_et = None
    if ts_valid(dry_ts):
        ready_et = dry_ts + timedelta(minutes=int(dry_assumption_minutes))

    seq = derive_sequence_status(sort_ts=sort_ts, wash_ts=wash_ts, dry_ts=dry_ts)
    current = derive_current_stage(
        sort_ts=sort_ts,
        wash_ts=wash_ts,
        dry_ts=dry_ts,
        ready_et=ready_et,
        now_et=now_et,
        has_sequence_exception=bool(seq["has_sequence_exception"]),
    )
    # Prefer Sequence Exception label when order conflicts exist with all stages.
    if seq["has_sequence_exception"] and any(
        c in seq["sequence_codes"]
        for c in (SEQ_WASH_BEFORE_SORT, SEQ_DRY_BEFORE_WASH, SEQ_DRY_BEFORE_SORT, SEQ_CONFLICTING)
    ):
        if sort_ts and wash_ts and dry_ts:
            current = CURRENT_SEQUENCE_EXCEPTION

    sort_rack = None
    if sort_session:
        sort_rack = sort_session.get("sort_rack") or sort_session.get("machine_rack")
        if not sort_rack and bag_events:
            sort_rack = _rack_near_time(
                bag_events, sort_session.get("sort_end_et") or sort_ts
            )

    return {
        "bag_id": bid,
        "sort_employee": (sort_session or {}).get("employee"),
        "sort_scan_et": sort_ts,
        "sort_machine_rack": sort_rack,
        "wash_employee": (wash_row or {}).get("employee"),
        "wash_scan_et": wash_ts,
        "washer": (wash_row or {}).get("washer_rack"),
        "dry_employee": (dry_row or {}).get("employee"),
        "dry_scan_et": dry_ts,
        "dryer": (dry_row or {}).get("dryer_rack"),
        "ready_to_fold_et": ready_et,
        "ready_to_fold_is_calculated": ready_et is not None,
        "dry_assumption_minutes": int(dry_assumption_minutes) if ready_et is not None else None,
        "current_stage": current,
        "sequence_status": seq["sequence_status"],
        "sequence_codes": seq["sequence_codes"],
        "has_sequence_exception": seq["has_sequence_exception"],
        "confidence": _combined_confidence(
            (sort_session or {}).get("confidence"),
            (wash_row or {}).get("confidence"),
            (dry_row or {}).get("confidence"),
        ),
        "sort_confidence": (sort_session or {}).get("confidence"),
        "wash_confidence": (wash_row or {}).get("confidence"),
        "dry_confidence": (dry_row or {}).get("confidence"),
        "canonical_sort": dict(sort_session) if sort_session else None,
        "canonical_wash": dict(wash_row) if wash_row else None,
        "canonical_dry": dict(dry_row) if dry_row else None,
    }


def build_process_flow_timeline(
    *,
    bag_id: str,
    bag_events: Sequence[Mapping[str, Any]],
    sort_session: Mapping[str, Any] | None,
    wash_row: Mapping[str, Any] | None,
    dry_row: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Read-only chronological evidence list with canonical markers."""
    bid = _bag_key(bag_id)
    canon_sort_start = (sort_session or {}).get("sort_start_et")
    canon_wash_id = (wash_row or {}).get("scan_event_id")
    canon_dry_id = (dry_row or {}).get("scan_event_id")

    rows: list[dict[str, Any]] = []
    for ev in bag_events:
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        purpose = str(ev.get("purpose") or "").strip()
        stage = "Other"
        canonical = False
        exclusion = None
        pl = purpose.lower()
        if "sort" in pl or pl in ("add-photos", "weight-entry", "cleaning"):
            stage = "Sort-related"
        if pl in ("start-cleaning", "washer-settings"):
            stage = "Wash"
        if "dry" in pl:
            stage = "Dry"
        if "sent-to-vendor" in pl or pl == "sent to vendor":
            stage = "Lifecycle"
        ev_id = ev.get("id")
        if canon_wash_id is not None and ev_id == canon_wash_id:
            stage = "Wash"
            canonical = True
        if canon_dry_id is not None and ev_id == canon_dry_id:
            stage = "Dry"
            canonical = True
        if (
            canon_sort_start is not None
            and ts_valid(canon_sort_start)
            and abs((ts - canon_sort_start).total_seconds()) < 1
            and stage.startswith("Sort")
        ):
            canonical = True
            stage = "Sort"

        rows.append(
            {
                "bag_id": bid,
                "stage": stage,
                "event_time_et": ts,
                "employee": (
                    str(ev.get("user_name") or ev.get("user") or "").strip() or None
                ),
                "machine_rack": str(ev.get("rack") or "").strip() or None,
                "raw_event": purpose or None,
                "confidence": None,
                "source": "rinse_bag_scan_events",
                "canonical": canonical,
                "exclusion_reason": exclusion,
                "scan_event_id": ev_id,
            }
        )

    # Ensure canonical stage rows appear even if event matching failed.
    def _ensure(stage: str, ts: datetime | None, employee: Any, rack: Any, conf: Any, sid: Any):
        if not ts_valid(ts):
            return
        if any(r.get("canonical") and r.get("stage") == stage for r in rows):
            return
        rows.append(
            {
                "bag_id": bid,
                "stage": stage,
                "event_time_et": ts,
                "employee": employee,
                "machine_rack": rack,
                "raw_event": f"canonical_{stage.lower()}",
                "confidence": conf,
                "source": "canonical_selector",
                "canonical": True,
                "exclusion_reason": None,
                "scan_event_id": sid,
            }
        )

    if sort_session:
        _ensure(
            "Sort",
            sort_session.get("sort_start_et"),
            sort_session.get("employee"),
            sort_session.get("sort_rack"),
            sort_session.get("confidence"),
            None,
        )
    if wash_row:
        _ensure(
            "Wash",
            wash_row.get("timestamp_et"),
            wash_row.get("employee"),
            wash_row.get("washer_rack"),
            wash_row.get("confidence"),
            wash_row.get("scan_event_id"),
        )
    if dry_row:
        _ensure(
            "Dry",
            dry_row.get("timestamp_et"),
            dry_row.get("employee"),
            dry_row.get("dryer_rack"),
            dry_row.get("confidence"),
            dry_row.get("scan_event_id"),
        )

    rows.sort(
        key=lambda r: (
            r.get("event_time_et") is None,
            r.get("event_time_et") or datetime.min,
            int(r.get("scan_event_id") or 0),
        )
    )
    return rows


def assign_ready_times_to_slots(
    bags: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[datetime],
    *,
    ready_key: str,
) -> list[dict[str, Any]]:
    """Assign each bag to exactly one checkpoint slot by ready_key timestamp."""
    if not checkpoints:
        raise ProcessFlowValidationError("At least one checkpoint time is required.")

    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    ordered = sorted(
        bags,
        key=lambda b: (
            b.get(ready_key) is None,
            b.get(ready_key) or datetime.min,
            str(b.get("bag_id") or ""),
        ),
    )
    for bag in ordered:
        bid = _bag_key(bag.get("bag_id"))
        ready = bag.get(ready_key)
        if not bid or not ts_valid(ready) or bid in seen:
            continue
        seen.add(bid)
        unique.append(bag)

    slots: list[dict[str, Any]] = []
    cumulative = 0
    for idx, checkpoint in enumerate(checkpoints):
        prev = checkpoints[idx - 1] if idx > 0 else None
        newly: list[dict[str, Any]] = []
        for bag in unique:
            ready = bag[ready_key]
            if prev is None:
                if ready <= checkpoint:
                    newly.append(dict(bag))
            elif prev < ready <= checkpoint:
                newly.append(dict(bag))
        cumulative += len(newly)
        if prev is None:
            interval_label = f"Start of ET day–{_format_checkpoint_clock(checkpoint)}"
        else:
            interval_label = (
                f"After {_format_checkpoint_clock(prev)}–"
                f"{_format_checkpoint_clock(checkpoint)}"
            )
        slots.append(
            {
                "slot": idx + 1,
                "checkpoint_et": checkpoint,
                "checkpoint_label": _format_checkpoint_clock(checkpoint),
                "interval_label": interval_label,
                "newly_ready_count": len(newly),
                "cumulative_ready_count": cumulative,
                "bags": newly,
            }
        )
    return slots


def build_process_flow_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unique = {_bag_key(r.get("bag_id")) for r in rows if _bag_key(r.get("bag_id"))}
    sorted_ids = {
        _bag_key(r.get("bag_id")) for r in rows if ts_valid(r.get("sort_scan_et"))
    }
    washed_ids = {
        _bag_key(r.get("bag_id")) for r in rows if ts_valid(r.get("wash_scan_et"))
    }
    dried_ids = {
        _bag_key(r.get("bag_id")) for r in rows if ts_valid(r.get("dry_scan_et"))
    }
    ready_ids = {
        _bag_key(r.get("bag_id")) for r in rows if ts_valid(r.get("ready_to_fold_et"))
    }
    missing_sort = {
        _bag_key(r.get("bag_id"))
        for r in rows
        if SEQ_MISSING_SORT in (r.get("sequence_codes") or [])
    }
    missing_wash = {
        _bag_key(r.get("bag_id"))
        for r in rows
        if SEQ_MISSING_WASH in (r.get("sequence_codes") or [])
    }
    missing_dry = {
        _bag_key(r.get("bag_id"))
        for r in rows
        if SEQ_MISSING_DRY in (r.get("sequence_codes") or [])
    }
    exceptions = {
        _bag_key(r.get("bag_id"))
        for r in rows
        if r.get("has_sequence_exception")
    }
    return {
        "unique_bags": len(unique),
        "sorted": len(sorted_ids),
        "washed": len(washed_ids),
        "dried": len(dried_ids),
        "ready_to_fold": len(ready_ids),
        "missing_sort": len(missing_sort),
        "missing_wash": len(missing_wash),
        "missing_dry": len(missing_dry),
        "sequence_exceptions": len(exceptions),
        "dry_assumption_minutes_default": DEFAULT_DRY_ASSUMPTION_MINUTES,
        "sort_assumption_minutes_default": DEFAULT_SORT_ASSUMPTION_MINUTES,
        "wash_assumption_minutes_default": DEFAULT_WASH_ASSUMPTION_MINUTES,
        "dry_assumption_note": (
            "Scan Chronology Ready-to-Fold assumption (40). "
            "Does not use rinse_processing_settings.drying_minutes (45)."
        ),
        "sort_wash_assumption_note": "No configured assumption — editable 0 minutes.",
    }


def filter_process_flow_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bag_id_filter: str | None = None,
    current_stage_filter: str | None = None,
    sequence_status_filter: str | None = None,
    sort_employee_filter: str | None = None,
    wash_employee_filter: str | None = None,
    dry_employee_filter: str | None = None,
    confidence_filter: str | None = None,
) -> list[dict[str, Any]]:
    out = [dict(r) for r in rows]
    if bag_id_filter:
        needle = _bag_key(bag_id_filter)
        out = [r for r in out if _bag_key(r.get("bag_id")) == needle]
    if current_stage_filter:
        cs = str(current_stage_filter).strip().lower()
        out = [r for r in out if str(r.get("current_stage") or "").strip().lower() == cs]
    if sequence_status_filter:
        ss = str(sequence_status_filter).strip().lower()
        out = [
            r
            for r in out
            if ss in str(r.get("sequence_status") or "").strip().lower()
            or any(ss == str(c).strip().lower() for c in (r.get("sequence_codes") or []))
        ]
    if sort_employee_filter:
        se = str(sort_employee_filter).strip().casefold()
        out = [r for r in out if str(r.get("sort_employee") or "").strip().casefold() == se]
    if wash_employee_filter:
        we = str(wash_employee_filter).strip().casefold()
        out = [r for r in out if str(r.get("wash_employee") or "").strip().casefold() == we]
    if dry_employee_filter:
        de = str(dry_employee_filter).strip().casefold()
        out = [r for r in out if str(r.get("dry_employee") or "").strip().casefold() == de]
    if confidence_filter:
        cf = str(confidence_filter).strip().lower()
        out = [r for r in out if str(r.get("confidence") or "").strip().lower() == cf]
    for idx, row in enumerate(out):
        row["index"] = idx + 1
    return out


def _load_scan_events_window(cursor, organization_id: int, window_start, window_end):
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


def _load_scan_events_for_bags(cursor, organization_id: int, bag_ids: Sequence[str]):
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


def compose_process_flow_rows_for_bags(
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
    dry_assumption_minutes: int = DEFAULT_DRY_ASSUMPTION_MINUTES,
    now_et: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Pure composition helper: given full bag timelines, build one Process Flow row
    per bag that has selected-day current-lifecycle evidence.
    """
    day_end = naive_et_day_end_inclusive(selected_date_et)
    as_of = now_et or day_end

    # Build stage extracts across all bags, then apply shared selectors.
    all_sort_sessions: list[dict[str, Any]] = []
    all_wash_rows: list[dict[str, Any]] = []
    all_dry_rows: list[dict[str, Any]] = []
    for bid, events in events_by_bag.items():
        all_sort_sessions.extend(
            extract_sorting_sessions_for_bag(bid, events, selected_date_et=selected_date_et)
        )
        all_wash_rows.extend(extract_washing_rows_from_events(events))
        all_dry_rows.extend(extract_drying_rows_from_events(events))

    selected_sorts = {
        _bag_key(s.get("bag_id")): s
        for s in select_current_cycle_sorting_sessions(
            all_sort_sessions, events_by_bag, as_of_end=day_end
        )
    }
    selected_washes = {
        _bag_key(s.get("bag_id")): s
        for s in select_current_cycle_washing_rows(
            all_wash_rows, events_by_bag, as_of_end=day_end
        )
    }
    selected_drys = {
        _bag_key(s.get("bag_id")): s
        for s in select_current_cycle_drying_rows(
            all_dry_rows, events_by_bag, as_of_end=day_end
        )
    }

    # Selected-day membership: at least one canonical stage event on/touching day.
    candidate_ids = set()
    for bid, sess in selected_sorts.items():
        if _session_touches_selected_day(sess, selected_date_et):
            candidate_ids.add(bid)
    for bid, row in selected_washes.items():
        if _on_selected_day(row.get("timestamp_et"), selected_date_et):
            candidate_ids.add(bid)
    for bid, row in selected_drys.items():
        if drying_scan_on_selected_date(row.get("timestamp_et"), selected_date_et):
            candidate_ids.add(bid)

    rows: list[dict[str, Any]] = []
    for bid in sorted(candidate_ids):
        sort_sess = selected_sorts.get(bid)
        wash = selected_washes.get(bid)
        dry = selected_drys.get(bid)
        # Keep later-stage evidence even when earlier stages missing.
        composed = compose_process_flow_bag_row(
            bag_id=bid,
            sort_session=sort_sess,
            wash_row=wash,
            dry_row=dry,
            bag_events=events_by_bag.get(bid) or [],
            dry_assumption_minutes=dry_assumption_minutes,
            now_et=as_of,
        )
        composed["timeline"] = build_process_flow_timeline(
            bag_id=bid,
            bag_events=events_by_bag.get(bid) or [],
            sort_session=sort_sess,
            wash_row=wash,
            dry_row=dry,
        )
        rows.append(composed)

    rows.sort(key=lambda r: (str(r.get("bag_id") or ""),))
    for idx, row in enumerate(rows):
        row["index"] = idx + 1
    return rows


def build_process_flow_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    bag_id_filter: str | None = None,
    current_stage_filter: str | None = None,
    sequence_status_filter: str | None = None,
    sort_employee_filter: str | None = None,
    wash_employee_filter: str | None = None,
    dry_employee_filter: str | None = None,
    confidence_filter: str | None = None,
    dry_assumption_minutes: int | None = None,
    # Symmetry with other stages; unused for Process Flow composition filters.
    employee_filter: str | None = None,
    machine_filter: str | None = None,
    activity_type_filter: str | None = None,
    drying_duration_minutes: int | None = None,
    order_type_filter: str | None = None,
    status_filter: str | None = None,
    view_mode: str | None = None,
) -> dict[str, Any]:
    del (
        employee_filter,
        machine_filter,
        activity_type_filter,
        order_type_filter,
        status_filter,
        view_mode,
    )

    dry_minutes = clamp_dry_assumption_minutes(
        dry_assumption_minutes
        if dry_assumption_minutes is not None
        else drying_duration_minutes
    )

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    window_start = day_start - timedelta(days=1)
    window_events = _load_scan_events_window(
        cursor, organization_id, window_start, day_end
    )

    # Candidate discovery from day-window extracts (sort/wash/dry activity).
    wash_window = extract_washing_rows_from_events(window_events)
    dry_window = extract_drying_rows_from_events(window_events)
    candidate_ids = {
        _bag_key(r.get("bag_id"))
        for r in wash_window
        if _on_selected_day(r.get("timestamp_et"), selected_date_et)
        and _bag_key(r.get("bag_id"))
    }
    candidate_ids |= {
        _bag_key(r.get("bag_id"))
        for r in dry_window
        if drying_scan_on_selected_date(r.get("timestamp_et"), selected_date_et)
        and _bag_key(r.get("bag_id"))
    }
    # Sorting activity on day — purposes from window events.
    from backend.rinse_scan_purpose import (
        is_add_photos_purpose,
        is_lifecycle_sorting_progress_marker_purpose,
        is_weight_entry_purpose,
    )

    for ev in window_events:
        purpose = ev.get("purpose")
        if (
            is_add_photos_purpose(purpose)
            or is_weight_entry_purpose(purpose)
            or is_lifecycle_sorting_progress_marker_purpose(purpose)
        ) and _on_selected_day(event_ts(ev), selected_date_et):
            bid = _bag_key(ev.get("bag_id"))
            if bid:
                candidate_ids.add(bid)

    if bag_id_filter:
        needle = _bag_key(bag_id_filter)
        candidate_ids = {bid for bid in candidate_ids if bid == needle}

    full_events = _load_scan_events_for_bags(
        cursor, organization_id, sorted(candidate_ids)
    )
    events_by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in full_events:
        bid = _bag_key(ev.get("bag_id"))
        if bid:
            events_by_bag.setdefault(bid, []).append(ev)

    rows = compose_process_flow_rows_for_bags(
        events_by_bag=events_by_bag,
        selected_date_et=selected_date_et,
        dry_assumption_minutes=dry_minutes,
        now_et=day_end,
    )
    filtered = filter_process_flow_rows(
        rows,
        bag_id_filter=bag_id_filter,
        current_stage_filter=current_stage_filter,
        sequence_status_filter=sequence_status_filter,
        sort_employee_filter=sort_employee_filter,
        wash_employee_filter=wash_employee_filter,
        dry_employee_filter=dry_employee_filter,
        confidence_filter=confidence_filter,
    )
    summary = build_process_flow_summary(filtered)

    # Lightweight sessions for table (timeline available on demand in payload).
    sessions = []
    for r in filtered:
        sessions.append(
            {
                "index": r.get("index"),
                "bag_id": r.get("bag_id"),
                "sort_employee": r.get("sort_employee"),
                "sort_scan_et": r.get("sort_scan_et"),
                "sort_machine_rack": r.get("sort_machine_rack"),
                "wash_employee": r.get("wash_employee"),
                "wash_scan_et": r.get("wash_scan_et"),
                "washer": r.get("washer"),
                "dry_employee": r.get("dry_employee"),
                "dry_scan_et": r.get("dry_scan_et"),
                "dryer": r.get("dryer"),
                "ready_to_fold_et": r.get("ready_to_fold_et"),
                "ready_to_fold_is_calculated": r.get("ready_to_fold_is_calculated"),
                "current_stage": r.get("current_stage"),
                "sequence_status": r.get("sequence_status"),
                "sequence_codes": r.get("sequence_codes"),
                "has_sequence_exception": r.get("has_sequence_exception"),
                "confidence": r.get("confidence"),
                "timeline": r.get("timeline") or [],
            }
        )

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "process_flow",
        "read_only": True,
        "mutates_scan_records": False,
        "dry_assumption_minutes": dry_minutes,
        "sort_assumption_minutes_default": DEFAULT_SORT_ASSUMPTION_MINUTES,
        "wash_assumption_minutes_default": DEFAULT_WASH_ASSUMPTION_MINUTES,
        "summary": summary,
        "sessions": sessions,
        "bags": sessions,
        "employees": sorted(
            {
                e
                for r in sessions
                for e in (
                    r.get("sort_employee"),
                    r.get("wash_employee"),
                    r.get("dry_employee"),
                )
                if e
            },
            key=lambda n: n.casefold(),
        ),
        "current_stage_options": sorted(
            {str(r.get("current_stage")) for r in sessions if r.get("current_stage")}
        ),
        "sequence_status_options": [
            SEQ_VALID,
            SEQ_MISSING_SORT,
            SEQ_MISSING_WASH,
            SEQ_MISSING_DRY,
            SEQ_WASH_BEFORE_SORT,
            SEQ_DRY_BEFORE_WASH,
            SEQ_DRY_BEFORE_SORT,
            SEQ_CONFLICTING,
        ],
        "grouping_rules": (
            "Process Flow composes select_current_cycle_sorting_sessions, "
            "select_current_cycle_washing_rows, and select_current_cycle_drying_rows "
            "with shared lifecycle_anchor_as_of. One row per Bag ID. "
            "Ready-to-Fold time is calculated (dry + assumption). Read-only."
        ),
    }


def build_process_flow_calculator_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    checkpoints: Sequence[Any],
    start_time: Any = None,
    sort_assumption_minutes: int | None = None,
    wash_assumption_minutes: int | None = None,
    dry_assumption_minutes: int | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """
    Read-only Process Flow queue calculator (Washing / Drying / Folding queues).

    Sort/Wash duration assumptions are not used. Optional sort/wash kwargs are
    ignored for compatibility with older clients.
    """
    del sort_assumption_minutes, wash_assumption_minutes  # removed from calculator
    from backend.rinse_process_flow_queue import build_process_flow_queue_calculator_payload

    return build_process_flow_queue_calculator_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        checkpoints=checkpoints,
        start_time=start_time,
        dry_assumption_minutes=dry_assumption_minutes,
        now_et=now_et,
    )
