"""Workload-based employee productivity — Today's Workload is the source of truth.

Each unique workload bag is credited to at most one employee (or Unassigned).
Productivity counts unique workload bags, not raw scan events.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    _attribution_reason,
    _completed_lbs,
    _completion_on_selected_et_day,
    _event_user_name,
    _is_hd_completion_purpose,
    _resolve_anchor_ts,
    resolve_completion_attribution,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_complete_cleaning_purpose,
    is_operator_upstream_processing_purpose,
    is_weight_entry_purpose,
    is_wf_folding_pipeline_purpose,
    normalize_scan_purpose,
)

UNASSIGNED_EMPLOYEE = "Unassigned / No Attribution"


def _normalize_workload_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("at_vendor_status") or "").strip().lower()
    return "completed" if status == "completed" else "pending"


def _service_type(row: Mapping[str, Any]) -> str:
    return str(row.get("service_type") or row.get("service_bucket") or "").upper()


def _resolve_pending_wf_ownership(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    day_start: datetime,
    day_end: datetime,
) -> tuple[str, datetime | None, str | None]:
    candidates: list[tuple[datetime, Mapping[str, Any]]] = []
    for ev in timeline:
        ts = event_ts(ev)
        if not ts_valid(ts) or ts < anchor_ts or ts < day_start or ts > day_end:
            continue
        purpose = ev.get("purpose")
        if (
            is_wf_folding_pipeline_purpose(purpose)
            or is_operator_upstream_processing_purpose(purpose)
            or is_complete_cleaning_purpose(purpose)
            or is_weight_entry_purpose(purpose)
            or is_add_photos_purpose(purpose)
        ):
            candidates.append((ts, ev))
    if not candidates:
        return UNKNOWN_EMPLOYEE, None, None
    ts, ev = max(candidates, key=lambda item: item[0])
    signal = normalize_scan_purpose(ev.get("purpose")) or "wf-production"
    return _event_user_name(ev), ts, signal


def _resolve_pending_hd_ownership(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    day_start: datetime,
    day_end: datetime,
) -> tuple[str, datetime | None, str | None]:
    candidates: list[tuple[datetime, Mapping[str, Any]]] = []
    for ev in timeline:
        ts = event_ts(ev)
        if not ts_valid(ts) or ts < anchor_ts or ts < day_start or ts > day_end:
            continue
        if _is_hd_completion_purpose(ev.get("purpose")) or is_add_photos_purpose(ev.get("purpose")):
            candidates.append((ts, ev))
    if not candidates:
        return UNKNOWN_EMPLOYEE, None, None
    ts, ev = max(candidates, key=lambda item: item[0])
    signal = normalize_scan_purpose(ev.get("purpose")) or "hd-production"
    return _event_user_name(ev), ts, signal


def resolve_workload_bag_credit(
    row: Mapping[str, Any],
    *,
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    as_of_end: datetime,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one workload bag credit record (unique bag, one owner)."""
    bid = str(row.get("bag_id") or "").strip().upper()
    svc = _service_type(row)
    workload_status = _normalize_workload_status(row)
    meta = (registry_meta or {}).get(bid) or {}
    anchor = _resolve_anchor_ts(events, selected_date_et)
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    timeline = gaming_events_from_records(events)

    employee = UNKNOWN_EMPLOYEE
    credit_ts: datetime | None = None
    credit_event_type: str | None = None
    credit_reason = "No ownership signal found — Unassigned"

    attr_employee, attr_ts, attr_signal = resolve_completion_attribution(
        service_type=svc,
        events=events,
        anchor_ts=anchor,
        as_of_end=as_of_end,
    )
    if attr_employee != UNKNOWN_EMPLOYEE and attr_ts is not None and _completion_on_selected_et_day(
        attr_ts, selected_date_et
    ):
        employee = attr_employee
        credit_ts = attr_ts
        credit_event_type = attr_signal
        credit_reason = _attribution_reason(svc, attr_signal)
    elif workload_status == "pending" and anchor is not None:
        if svc == "WF":
            employee, credit_ts, credit_event_type = _resolve_pending_wf_ownership(
                timeline, anchor_ts=anchor, day_start=day_start, day_end=day_end
            )
        elif svc == "HD":
            employee, credit_ts, credit_event_type = _resolve_pending_hd_ownership(
                timeline, anchor_ts=anchor, day_start=day_start, day_end=day_end
            )
        if employee != UNKNOWN_EMPLOYEE and credit_ts is not None:
            credit_reason = f"{svc}: latest production ownership on selected day ({credit_event_type})"
    elif workload_status == "completed" and attr_employee != UNKNOWN_EMPLOYEE:
        # Completed in workload but completion ET not on selected day — still credit from attribution scan.
        employee = attr_employee
        credit_ts = attr_ts
        credit_event_type = attr_signal
        credit_reason = _attribution_reason(svc, attr_signal)

    if employee == UNKNOWN_EMPLOYEE:
        display_employee = UNASSIGNED_EMPLOYEE
    else:
        display_employee = employee

    lbs = _completed_lbs(row, meta)
    from backend.rinse_at_vendor_module import _format_et_display

    credit_time_et = _format_et_display(credit_ts) if credit_ts is not None else None

    return {
        "bag_id": bid,
        "workflow": svc,
        "workload_status": workload_status,
        "service_type": svc if svc in ("WF", "HD") else row.get("service_type"),
        "service_bucket": row.get("service_bucket") or svc,
        "customer_name": row.get("customer_name") or meta.get("name_clean"),
        "at_vendor_status": row.get("at_vendor_status"),
        "credited_employee": display_employee,
        "employee_credited": display_employee,
        "completed_by_employee": display_employee,
        "processed_by_employee": display_employee,
        "credit_reason": credit_reason,
        "attribution_reason": credit_reason,
        "credit_event_type": credit_event_type,
        "credit_timestamp": credit_ts.isoformat() if credit_ts else None,
        "processed_time": credit_ts.isoformat() if credit_ts else None,
        "processed_timestamp": credit_ts.isoformat() if credit_ts else None,
        "processed_time_et": credit_time_et,
        "processed_signal": credit_event_type,
        "completion_time": row.get("completion_time") if workload_status == "completed" else None,
        "completion_timestamp": row.get("completion_time") if workload_status == "completed" else None,
        "completion_time_et": row.get("completion_time_et") if workload_status == "completed" else None,
        "completion_signal": row.get("completion_signal") if workload_status == "completed" else None,
        "credited_lbs": lbs,
        "processed_lbs": lbs,
        "completed_lbs": lbs if workload_status == "completed" else None,
        "weight_missing": lbs is None,
        "included_in_employee_productivity": True,
        "rush_bucket": row.get("rush_bucket"),
    }


def credit_workload_bags(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Credit each unique workload bag once. Returns (records, duplicate_bag_ids)."""
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    credited: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []

    for row in workload_rows:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if bid in seen:
            duplicates.append(bid)
            continue
        seen.add(bid)
        events = events_by_bag.get(bid) or []
        credited.append(
            resolve_workload_bag_credit(
                row,
                events=events,
                selected_date_et=selected_date_et,
                as_of_end=as_of_end,
                registry_meta=registry_meta,
            )
        )
    return credited, duplicates


def build_workload_productivity_reconciliation(
    *,
    workload_rows: Sequence[Mapping[str, Any]],
    credited_bags: Sequence[Mapping[str, Any]],
    duplicate_bag_ids: Sequence[str],
    selected_date_et: date,
) -> dict[str, Any]:
    """Reconcile credited workload bags back to Today's Workload totals."""
    workload_ids = sorted(
        {
            str(r.get("bag_id") or "").strip().upper()
            for r in workload_rows
            if isinstance(r, dict) and r.get("bag_id")
        }
    )
    credited_ids = sorted(
        {str(b.get("bag_id") or "").strip().upper() for b in credited_bags if b.get("bag_id")}
    )
    workload_set = set(workload_ids)
    credited_set = set(credited_ids)

    wf_total = sum(1 for r in workload_rows if isinstance(r, dict) and _service_type(r) == "WF")
    hd_total = sum(1 for r in workload_rows if isinstance(r, dict) and _service_type(r) == "HD")
    wf_pending = sum(
        1
        for r in workload_rows
        if isinstance(r, dict)
        and _service_type(r) == "WF"
        and _normalize_workload_status(r) == "pending"
    )
    hd_pending = sum(
        1
        for r in workload_rows
        if isinstance(r, dict)
        and _service_type(r) == "HD"
        and _normalize_workload_status(r) == "pending"
    )
    wf_completed = wf_total - wf_pending
    hd_completed = hd_total - hd_pending

    credited_wf = sum(1 for b in credited_bags if _service_type(b) == "WF")
    credited_hd = sum(1 for b in credited_bags if _service_type(b) == "HD")
    unassigned = [
        b for b in credited_bags if str(b.get("credited_employee") or "") == UNASSIGNED_EMPLOYEE
    ]
    unassigned_ids = sorted(str(b.get("bag_id") or "").upper() for b in unassigned if b.get("bag_id"))

    credited_completed = sum(
        1 for b in credited_bags if str(b.get("workload_status") or "") == "completed"
    )
    credited_pending = sum(
        1 for b in credited_bags if str(b.get("workload_status") or "") == "pending"
    )

    employee_credits: dict[str, set[str]] = {}
    duplicate_credit_count = 0
    for bag in credited_bags:
        bid = str(bag.get("bag_id") or "").upper()
        emp = str(bag.get("credited_employee") or UNASSIGNED_EMPLOYEE)
        if not bid:
            continue
        bucket = employee_credits.setdefault(emp, set())
        if bid in bucket:
            duplicate_credit_count += 1
        bucket.add(bid)

    missing_from_productivity = sorted(workload_set - credited_set)
    extra_in_productivity = sorted(credited_set - workload_set)
    scan_derived_excluded = extra_in_productivity

    workload_total = len(workload_ids)
    credited_total = len(credited_ids)
    unassigned_count = len(unassigned_ids)

    recon_ok = (
        workload_total == credited_total
        and not duplicate_bag_ids
        and not missing_from_productivity
        and not extra_in_productivity
        and duplicate_credit_count == 0
        and credited_completed + credited_pending == credited_total
        and wf_total == credited_wf
        and hd_total == credited_hd
    )

    audit = [
        {
            "bag_id": b.get("bag_id"),
            "workflow": b.get("workflow"),
            "workload_status": b.get("workload_status"),
            "credited_employee": b.get("credited_employee"),
            "credit_reason": b.get("credit_reason"),
            "credit_event_type": b.get("credit_event_type"),
            "credit_timestamp": b.get("credit_timestamp"),
            "included_in_employee_productivity": bool(b.get("included_in_employee_productivity")),
        }
        for b in sorted(credited_bags, key=lambda x: str(x.get("credit_timestamp") or x.get("bag_id") or ""))
    ]

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "workload_total": workload_total,
        "workload_wf_total": wf_total,
        "workload_hd_total": hd_total,
        "workload_wf_pending": wf_pending,
        "workload_hd_pending": hd_pending,
        "workload_wf_completed": wf_completed,
        "workload_hd_completed": hd_completed,
        "workload_completed_today": wf_completed + hd_completed,
        "credited_total": credited_total,
        "credited_wf_count": credited_wf,
        "credited_hd_count": credited_hd,
        "credited_completed": credited_completed,
        "credited_pending": credited_pending,
        "unassigned_count": unassigned_count,
        "unassigned_bag_ids": unassigned_ids,
        "duplicate_credit_count": duplicate_credit_count,
        "scan_derived_excluded_bag_ids": scan_derived_excluded,
        "bags_outside_workload_excluded": scan_derived_excluded,
        "employee_credited_unique_bags": credited_total - unassigned_count,
        "workload_bag_ids": workload_ids,
        "credited_bag_ids": credited_ids,
        "missing_from_employee_productivity": missing_from_productivity,
        "extra_in_employee_productivity": extra_in_productivity,
        "duplicate_bag_ids": list(duplicate_bag_ids),
        "wf_count": credited_wf,
        "hd_count": credited_hd,
        "wf_plus_hd": credited_wf + credited_hd,
        "employee_completed_bags_credited": credited_total - unassigned_count,
        "employee_attributed_bag_count": credited_total - unassigned_count,
        "difference": workload_total - credited_total,
        "bags_match_workload_total": workload_total == credited_total,
        "credited_plus_unassigned_equals_workload": credited_total == workload_total,
        "no_duplicate_bags": not duplicate_bag_ids and duplicate_credit_count == 0,
        "ok": recon_ok,
        "status": "reconciled" if recon_ok else "mismatch",
        "status_label": "Reconciled ✓" if recon_ok else "Mismatch ✗",
        "workload_attribution_audit": audit,
        "attribution_audit": audit,
    }
