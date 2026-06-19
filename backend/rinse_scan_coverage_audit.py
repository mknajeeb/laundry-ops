"""
Read-only scan chronology coverage audit for a single ET day.

Processed bag definition (union — matches ops floor reality):
1. Any bag with at least one rinse_bag_scan_events row on the selected ET day.
2. Any bag on active orders_staging (or rinse_bag_registry supplement) with date_clean
   on that day — scheduled production even when scans have not arrived yet.
3. Any bag with a post-anchor process/completion scan on that day (weight-entry,
   add-photos, processed-by-vendor, sent-to-vendor) — explicit completion signals.

Stage status reuses existing weighing/sorting/washing/drying chronology builders only;
no synthetic events or new duration logic.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start, rinse_wall_calendar_date
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_processed_by_vendor_purpose,
    is_sent_to_vendor_purpose,
    is_weight_entry_purpose,
)
from backend.rinse_simple_shift_performance import _load_bag_metadata
from backend.ta_helpers import table_exists, table_has_column

STAGE_WEIGHING = "weighing"
STAGE_SORTING = "sorting"
STAGE_WASHING = "washing"
STAGE_DRYING = "drying"

ALL_COVERAGE_STAGES = (STAGE_WEIGHING, STAGE_SORTING, STAGE_WASHING, STAGE_DRYING)

STATUS_FOUND = "found"
STATUS_INFERRED = "inferred"
STATUS_MISSING = "missing"
STATUS_EXCEPTION = "exception"

_ACCEPTABLE_COVERAGE = frozenset({STATUS_FOUND, STATUS_INFERRED})

_PROCESS_COMPLETION_PURPOSE_CHECKS = (
    is_weight_entry_purpose,
    is_add_photos_purpose,
    is_processed_by_vendor_purpose,
    is_sent_to_vendor_purpose,
)


def _normalize_bag_id(raw: str | None) -> str:
    return str(raw or "").strip().upper()


def _session_on_selected_day(
    *,
    selected_date_et: date,
    start_et: datetime | None = None,
    end_et: datetime | None = None,
    timestamp_et: datetime | None = None,
) -> bool:
    for ts in (start_et, end_et, timestamp_et):
        if ts is not None and rinse_wall_calendar_date(ts) == selected_date_et:
            return True
    if start_et and end_et and start_et <= naive_et_day_end_inclusive(selected_date_et):
        if end_et >= naive_et_day_start(selected_date_et):
            return True
    return False


def _status_from_confidence(confidence: str | None) -> str:
    cf = str(confidence or "").strip().lower()
    if cf == STATUS_INFERRED:
        return STATUS_INFERRED
    if cf == STATUS_FOUND or cf == "exact":
        return STATUS_FOUND
    return STATUS_FOUND


def _best_stage_status(existing: str | None, candidate: str) -> str:
    if existing is None:
        return candidate
    priority = {
        STATUS_FOUND: 3,
        STATUS_INFERRED: 2,
        STATUS_EXCEPTION: 1,
        STATUS_MISSING: 0,
    }
    return candidate if priority.get(candidate, 0) > priority.get(existing, 0) else existing


def map_stage_sessions_for_bag(
    bag_id: str,
    *,
    weighing_sessions: Sequence[Mapping[str, Any]] | None = None,
    sorting_sessions: Sequence[Mapping[str, Any]] | None = None,
    washing_sessions: Sequence[Mapping[str, Any]] | None = None,
    drying_sessions: Sequence[Mapping[str, Any]] | None = None,
    selected_date_et: date,
) -> dict[str, Any]:
    """Derive per-stage status and session refs from chronology builder rows."""
    bid = _normalize_bag_id(bag_id)
    statuses: dict[str, str] = {stage: STATUS_MISSING for stage in ALL_COVERAGE_STAGES}
    details: dict[str, Any] = {stage: None for stage in ALL_COVERAGE_STAGES}
    activity_times: list[datetime] = []

    for row in weighing_sessions or []:
        if _normalize_bag_id(row.get("bag_id")) != bid:
            continue
        if not _session_on_selected_day(
            selected_date_et=selected_date_et,
            start_et=row.get("start_et") or row.get("weigh_start_et"),
            end_et=row.get("end_et") or row.get("weigh_end_et"),
        ):
            continue
        st = _status_from_confidence(row.get("confidence"))
        statuses[STAGE_WEIGHING] = _best_stage_status(statuses[STAGE_WEIGHING], st)
        details[STAGE_WEIGHING] = row
        for key in ("end_et", "weigh_end_et", "start_et", "weigh_start_et"):
            ts = row.get(key)
            if isinstance(ts, datetime):
                activity_times.append(ts)

    for row in sorting_sessions or []:
        if _normalize_bag_id(row.get("bag_id")) != bid:
            continue
        if not _session_on_selected_day(
            selected_date_et=selected_date_et,
            start_et=row.get("start_et") or row.get("sort_start_et"),
            end_et=row.get("end_et") or row.get("sort_end_et"),
        ):
            continue
        st = _status_from_confidence(row.get("confidence"))
        statuses[STAGE_SORTING] = _best_stage_status(statuses[STAGE_SORTING], st)
        details[STAGE_SORTING] = row
        for key in ("end_et", "sort_end_et", "start_et", "sort_start_et"):
            ts = row.get(key)
            if isinstance(ts, datetime):
                activity_times.append(ts)

    for row in washing_sessions or []:
        if _normalize_bag_id(row.get("bag_id")) != bid:
            continue
        ts = row.get("timestamp_et")
        if not _session_on_selected_day(selected_date_et=selected_date_et, timestamp_et=ts):
            continue
        st = _status_from_confidence(row.get("confidence"))
        statuses[STAGE_WASHING] = _best_stage_status(statuses[STAGE_WASHING], st)
        details[STAGE_WASHING] = row
        if isinstance(ts, datetime):
            activity_times.append(ts)

    for row in drying_sessions or []:
        if _normalize_bag_id(row.get("bag_id")) != bid:
            continue
        ts = row.get("timestamp_et")
        if not _session_on_selected_day(selected_date_et=selected_date_et, timestamp_et=ts):
            continue
        st = _status_from_confidence(row.get("confidence"))
        statuses[STAGE_DRYING] = _best_stage_status(statuses[STAGE_DRYING], st)
        details[STAGE_DRYING] = row
        if isinstance(ts, datetime):
            activity_times.append(ts)

    return {
        "statuses": statuses,
        "details": details,
        "activity_times": activity_times,
    }


def _stage_present(statuses: Mapping[str, str], stage: str) -> bool:
    return statuses.get(stage) in _ACCEPTABLE_COVERAGE


def _stage_missing(statuses: Mapping[str, str], stage: str) -> bool:
    return statuses.get(stage) == STATUS_MISSING


def apply_coverage_exception_rules(statuses: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Mark downstream stages Exception when earlier required coverage is missing."""
    updated = dict(statuses)
    notes: list[str] = []

    if _stage_present(updated, STAGE_SORTING) and _stage_missing(updated, STAGE_WEIGHING):
        updated[STAGE_SORTING] = STATUS_EXCEPTION
        notes.append("Sorting without weighing chronology")

    if _stage_present(updated, STAGE_WASHING) and _stage_missing(updated, STAGE_SORTING):
        updated[STAGE_WASHING] = STATUS_EXCEPTION
        notes.append("Washing without sorting chronology")

    if _stage_present(updated, STAGE_WASHING) and _stage_missing(updated, STAGE_WEIGHING):
        if "Washing without weighing chronology" not in notes:
            notes.append("Washing without weighing chronology")
        if updated[STAGE_WASHING] != STATUS_EXCEPTION:
            updated[STAGE_WASHING] = STATUS_EXCEPTION

    if _stage_present(updated, STAGE_DRYING) and _stage_missing(updated, STAGE_WASHING):
        updated[STAGE_DRYING] = STATUS_EXCEPTION
        notes.append("Drying without washing chronology")

    if _stage_present(updated, STAGE_DRYING) and _stage_missing(updated, STAGE_SORTING):
        if "Drying without sorting chronology" not in notes:
            notes.append("Drying without sorting chronology")
        if updated[STAGE_DRYING] != STATUS_EXCEPTION:
            updated[STAGE_DRYING] = STATUS_EXCEPTION

    missing_count = sum(1 for stage in ALL_COVERAGE_STAGES if updated.get(stage) == STATUS_MISSING)
    if missing_count >= 2:
        notes.append(f"{missing_count} stages missing chronology coverage")

    return updated, notes


def is_fully_covered(statuses: Mapping[str, str]) -> bool:
    return all(statuses.get(stage) in _ACCEPTABLE_COVERAGE for stage in ALL_COVERAGE_STAGES)


def has_coverage_exception(statuses: Mapping[str, str], exception_notes: Sequence[str]) -> bool:
    if exception_notes:
        return True
    return any(statuses.get(stage) == STATUS_EXCEPTION for stage in ALL_COVERAGE_STAGES)


def build_coverage_audit_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    fully_covered = sum(1 for r in rows if r.get("fully_covered"))
    missing_weighing = sum(
        1 for r in rows if (r.get("weighing_status") or r.get("statuses", {}).get(STAGE_WEIGHING)) == STATUS_MISSING
    )
    missing_sorting = sum(
        1 for r in rows if (r.get("sorting_status") or r.get("statuses", {}).get(STAGE_SORTING)) == STATUS_MISSING
    )
    missing_washing = sum(
        1 for r in rows if (r.get("washing_status") or r.get("statuses", {}).get(STAGE_WASHING)) == STATUS_MISSING
    )
    missing_drying = sum(
        1 for r in rows if (r.get("drying_status") or r.get("statuses", {}).get(STAGE_DRYING)) == STATUS_MISSING
    )
    exception_bags = sum(1 for r in rows if r.get("has_exception"))
    return {
        "total_processed_bags": total,
        "fully_covered_bags": fully_covered,
        "missing_weighing": missing_weighing,
        "missing_sorting": missing_sorting,
        "missing_washing": missing_washing,
        "missing_drying": missing_drying,
        "exception_bags": exception_bags,
    }


def _employee_matches(row: Mapping[str, Any], employee_filter: str) -> bool:
    needle = str(employee_filter or "").strip().lower()
    if not needle:
        return True
    employee = str(row.get("employee") or "").strip().lower()
    return employee == needle


def bag_matches_employee_filter(
    *,
    bag_id: str,
    employee_filter: str | None,
    weighing_sessions: Sequence[Mapping[str, Any]] | None = None,
    sorting_sessions: Sequence[Mapping[str, Any]] | None = None,
    washing_sessions: Sequence[Mapping[str, Any]] | None = None,
    drying_sessions: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    if not employee_filter:
        return True
    bid = _normalize_bag_id(bag_id)
    for rows in (weighing_sessions, sorting_sessions, washing_sessions, drying_sessions):
        for row in rows or []:
            if _normalize_bag_id(row.get("bag_id")) != bid:
                continue
            if _employee_matches(row, employee_filter):
                return True
    return False


def build_coverage_audit_row(
    bag_id: str,
    *,
    selected_date_et: date,
    inclusion_sources: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    processed_completed_et: datetime | None = None,
    weighing_sessions: Sequence[Mapping[str, Any]] | None = None,
    sorting_sessions: Sequence[Mapping[str, Any]] | None = None,
    washing_sessions: Sequence[Mapping[str, Any]] | None = None,
    drying_sessions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    mapped = map_stage_sessions_for_bag(
        bag_id,
        weighing_sessions=weighing_sessions,
        sorting_sessions=sorting_sessions,
        washing_sessions=washing_sessions,
        drying_sessions=drying_sessions,
        selected_date_et=selected_date_et,
    )
    statuses, exception_notes = apply_coverage_exception_rules(mapped["statuses"])
    activity_times = list(mapped.get("activity_times") or [])
    if processed_completed_et is not None:
        activity_times.append(processed_completed_et)
    completed_et = max(activity_times) if activity_times else processed_completed_et

    meta = dict(metadata or {})
    order_id = meta.get("last_staging_order_id") or meta.get("order_id") or meta.get("staging_order_id")
    customer = meta.get("name_clean") or meta.get("customer_name")
    service_type = meta.get("service_type")

    fully = is_fully_covered(statuses)
    has_exc = has_coverage_exception(statuses, exception_notes)

    return {
        "bag_id": _normalize_bag_id(bag_id),
        "order_id": order_id,
        "customer": customer,
        "service_type": service_type,
        "processed_completed_et": completed_et,
        "weighing_status": statuses[STAGE_WEIGHING],
        "sorting_status": statuses[STAGE_SORTING],
        "washing_status": statuses[STAGE_WASHING],
        "drying_status": statuses[STAGE_DRYING],
        "statuses": statuses,
        "exception_notes": exception_notes,
        "has_exception": has_exc,
        "fully_covered": fully,
        "inclusion_sources": sorted(set(inclusion_sources or [])),
        "stage_details": mapped["details"],
    }


def _load_bag_ids_with_scan_activity_on_day(
    cursor,
    organization_id: int,
    day_start: datetime,
    day_end: datetime,
) -> set[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    cursor.execute(
        """
        SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
        """,
        (int(organization_id), day_start, day_end),
    )
    return {
        str(row.get("bag_id") or "").strip().upper()
        for row in cursor.fetchall() or []
        if isinstance(row, dict) and row.get("bag_id")
    }


def _load_bag_ids_with_process_completion_scans_on_day(
    cursor,
    organization_id: int,
    day_start: datetime,
    day_end: datetime,
) -> set[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    cursor.execute(
        """
        SELECT bag_id, purpose, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
        """,
        (int(organization_id), day_start, day_end),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        purpose = row.get("purpose")
        if not any(check(purpose) for check in _PROCESS_COMPLETION_PURPOSE_CHECKS):
            continue
        bid = _normalize_bag_id(row.get("bag_id"))
        if bid:
            out.add(bid)
    return out


def _load_bag_ids_due_on_day(cursor, organization_id: int, selected_date_et: date) -> set[str]:
    from backend.rinse_current_facility_snapshot import load_due_today_rows

    rows = load_due_today_rows(cursor, int(organization_id), selected_date_et)
    return {_normalize_bag_id(bid) for bid in rows.keys() if bid}


def load_processed_bag_ids_for_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> tuple[list[str], dict[str, list[str]]]:
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    sources_by_bag: dict[str, set[str]] = {}

    def _add(bag_ids: set[str], source: str) -> None:
        for bid in bag_ids:
            if not bid:
                continue
            sources_by_bag.setdefault(bid, set()).add(source)

    scan_ids = _load_bag_ids_with_scan_activity_on_day(cursor, organization_id, day_start, day_end)
    _add(scan_ids, "scan_activity")

    due_ids = _load_bag_ids_due_on_day(cursor, organization_id, selected_date_et)
    _add(due_ids, "date_clean")

    completion_ids = _load_bag_ids_with_process_completion_scans_on_day(
        cursor, organization_id, day_start, day_end
    )
    _add(completion_ids, "process_completion_scan")

    bag_ids = sorted(sources_by_bag.keys())
    inclusion = {bid: sorted(sources_by_bag[bid]) for bid in bag_ids}
    return bag_ids, inclusion


def _load_completion_timestamps_on_day(
    cursor,
    organization_id: int,
    bag_ids: list[str],
    day_start: datetime,
    day_end: datetime,
) -> dict[str, datetime]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    out: dict[str, datetime] = {}
    chunk = 100
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed <= %s
            """,
            (int(organization_id), *part, day_start, day_end),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            if not any(check(row.get("purpose")) for check in _PROCESS_COMPLETION_PURPOSE_CHECKS):
                continue
            ts = row.get("scanned_at_parsed")
            if not isinstance(ts, datetime):
                continue
            bid = _normalize_bag_id(row.get("bag_id"))
            if bid and (bid not in out or ts > out[bid]):
                out[bid] = ts
    return out


def _load_registry_order_ids(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, int | None]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_registry"):
        return {}
    if not table_has_column(cursor, "rinse_bag_registry", "last_staging_order_id"):
        return {}
    out: dict[str, int | None] = {}
    chunk = 100
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT UPPER(TRIM(bag_id)) AS bag_id, last_staging_order_id
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (int(organization_id), *part),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("bag_id"):
                out[str(row["bag_id"]).strip().upper()] = row.get("last_staging_order_id")
    return out


def build_scan_coverage_audit_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
) -> dict[str, Any]:
    from backend.rinse_scan_chronology import build_scan_chronology_payload

    bag_ids, inclusion_by_bag = load_processed_bag_ids_for_day(
        cursor, organization_id, selected_date_et
    )

    if bag_id_filter:
        bid = _normalize_bag_id(bag_id_filter)
        if bid:
            bag_ids = [bid]
            inclusion_by_bag.setdefault(bid, ["bag_filter"])

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    weighing_payload = build_scan_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        stage="weighing",
    )
    sorting_payload = build_scan_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        stage="sorting",
    )
    washing_payload = build_scan_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        stage="washing",
    )
    drying_payload = build_scan_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        stage="drying",
    )

    weighing_sessions = weighing_payload.get("sessions") or []
    sorting_sessions = sorting_payload.get("sessions") or []
    washing_sessions = washing_payload.get("sessions") or []
    drying_sessions = drying_payload.get("sessions") or []

    metadata_by_bag = _load_bag_metadata(cursor, organization_id, bag_ids)
    completion_ts = _load_completion_timestamps_on_day(
        cursor, organization_id, bag_ids, day_start, day_end
    )
    registry_order_ids = _load_registry_order_ids(cursor, organization_id, bag_ids)

    rows: list[dict[str, Any]] = []
    for bid in bag_ids:
        if employee_filter and not bag_matches_employee_filter(
            bag_id=bid,
            employee_filter=employee_filter,
            weighing_sessions=weighing_sessions,
            sorting_sessions=sorting_sessions,
            washing_sessions=washing_sessions,
            drying_sessions=drying_sessions,
        ):
            continue

        meta = metadata_by_bag.get(bid, {"bag_id": bid})
        if registry_order_ids.get(bid):
            meta = {**meta, "last_staging_order_id": registry_order_ids[bid]}

        row = build_coverage_audit_row(
            bid,
            selected_date_et=selected_date_et,
            inclusion_sources=inclusion_by_bag.get(bid),
            metadata=meta,
            processed_completed_et=completion_ts.get(bid),
            weighing_sessions=weighing_sessions,
            sorting_sessions=sorting_sessions,
            washing_sessions=washing_sessions,
            drying_sessions=drying_sessions,
        )
        rows.append(row)

    rows.sort(
        key=lambda r: (
            r.get("processed_completed_et") is None,
            r.get("processed_completed_et") or datetime.min,
            str(r.get("bag_id") or ""),
        )
    )

    employees = sorted(
        {
            str(s.get("employee") or "").strip()
            for sessions in (weighing_sessions, sorting_sessions, washing_sessions, drying_sessions)
            for s in sessions
            if s.get("employee")
        },
        key=lambda name: name.casefold(),
    )

    summary = build_coverage_audit_summary(rows)

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "coverage_audit",
        "summary": summary,
        "rows": rows,
        "employees": employees,
        "sessions": rows,
        "machines": [],
        "event_purposes": None,
        "grouping_rules": (
            "Processed bags = union of ET-day scan activity, active orders_staging/registry "
            "rows with date_clean on the day, and bags with weight-entry/add-photos/"
            "processed-by-vendor/sent-to-vendor scans that day. Stage status comes from "
            "existing weighing/sorting/washing/drying chronology builders: Found (exact), "
            "Inferred, Missing (no chronology row), Exception (sequence anomaly such as "
            "washing without sorting)."
        ),
    }
