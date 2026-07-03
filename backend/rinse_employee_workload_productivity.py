"""Workload-based employee productivity — completed production credit only.

Each unique completed workload bag is credited to at most one employee (or Unassigned).
Pending workload and non-completion signals (e.g. add-photos) do not create productivity credit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_at_vendor_module import AV_NON_RUSH, AV_RUSH
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    _attribution_reason,
    _completed_lbs,
    _completion_on_selected_et_day,
    _event_user_name,
    _resolve_anchor_ts,
    resolve_completion_attribution,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive

UNASSIGNED_EMPLOYEE = "Unassigned / No Attribution"


def _normalize_workload_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("at_vendor_status") or "").strip().lower()
    return "completed" if status == "completed" else "pending"


def _service_type(row: Mapping[str, Any]) -> str:
    return str(row.get("service_type") or row.get("service_bucket") or "").upper()


def _rush_bucket(row: Mapping[str, Any]) -> str:
    return str(row.get("rush_bucket") or "").upper()


def _rush_label(row: Mapping[str, Any]) -> str | None:
    label = row.get("rush_label")
    if label:
        return str(label)
    bucket = _rush_bucket(row)
    if bucket == AV_RUSH:
        return "Rush"
    if bucket == AV_NON_RUSH:
        return "Non-Rush"
    return None


def normalize_rush_filter(rush_filter: str | None) -> str:
    raw = str(rush_filter or "all").strip().lower()
    if raw in ("rush", "non_rush", "all"):
        return raw
    return "all"


def filter_workload_rows(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    rush_filter: str = "all",
    include_hd: bool = True,
    completed_only: bool = False,
) -> list[dict[str, Any]]:
    """Filter workload rows for productivity scope without changing attribution."""
    rush = normalize_rush_filter(rush_filter)
    out: list[dict[str, Any]] = []
    for row in workload_rows:
        if not isinstance(row, dict):
            continue
        if completed_only and _normalize_workload_status(row) != "completed":
            continue
        svc = _service_type(row)
        if not include_hd and svc != "WF":
            continue
        bucket = _rush_bucket(row)
        if rush == "rush" and bucket != AV_RUSH:
            continue
        if rush == "non_rush" and bucket != AV_NON_RUSH:
            continue
        out.append(dict(row))
    return out


def resolve_workload_bag_credit(
    row: Mapping[str, Any],
    *,
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    as_of_end: datetime,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one completed workload bag credit record (unique bag, one owner)."""
    bid = str(row.get("bag_id") or "").strip().upper()
    svc = _service_type(row)
    workload_status = _normalize_workload_status(row)
    meta = (registry_meta or {}).get(bid) or {}
    anchor = _resolve_anchor_ts(events, selected_date_et)

    employee = UNKNOWN_EMPLOYEE
    credit_ts: datetime | None = None
    credit_event_type: str | None = None
    credit_reason = "No completion attribution signal — Unassigned"
    excluded_reason: str | None = None
    included_in_employee_productivity = False

    if workload_status == "pending":
        excluded_reason = "Pending workload — excluded from employee productivity"
    else:
        attr_employee, attr_ts, attr_signal = resolve_completion_attribution(
            service_type=svc,
            events=events,
            anchor_ts=anchor,
            as_of_end=as_of_end,
        )
        if attr_employee != UNKNOWN_EMPLOYEE and attr_ts is not None:
            if svc == "WF" and not _completion_on_selected_et_day(attr_ts, selected_date_et):
                excluded_reason = "WF completion not on selected ET day — excluded from productivity"
            else:
                employee = attr_employee
                credit_ts = attr_ts
                credit_event_type = attr_signal
                credit_reason = _attribution_reason(svc, attr_signal)
                included_in_employee_productivity = True
        elif workload_status == "completed":
            excluded_reason = None
            credit_reason = "No completion/finalization signal — Unassigned"
            included_in_employee_productivity = True

    if employee == UNKNOWN_EMPLOYEE:
        display_employee = UNASSIGNED_EMPLOYEE
    else:
        display_employee = employee

    lbs = _completed_lbs(
        row,
        meta,
        events=events,
        service_type=svc,
        anchor_ts=anchor,
        as_of_end=as_of_end,
    )
    from backend.rinse_at_vendor_module import _format_et_display

    completion_ts_raw = row.get("completion_time")
    completion_ts: datetime | None = None
    if isinstance(completion_ts_raw, datetime):
        completion_ts = completion_ts_raw
    elif completion_ts_raw:
        try:
            completion_ts = datetime.fromisoformat(str(completion_ts_raw))
        except ValueError:
            completion_ts = None

    credit_time_et = _format_et_display(credit_ts) if credit_ts is not None else None
    completion_time_et = row.get("completion_time_et") or (
        _format_et_display(completion_ts) if completion_ts is not None else None
    )

    return {
        "bag_id": bid,
        "workflow": svc,
        "workload_status": workload_status,
        "service_type": svc if svc in ("WF", "HD") else row.get("service_type"),
        "service_bucket": row.get("service_bucket") or svc,
        "customer_name": row.get("customer_name") or meta.get("name_clean"),
        "at_vendor_status": row.get("at_vendor_status"),
        "rush_bucket": row.get("rush_bucket"),
        "rush_label": _rush_label(row),
        "credited_employee": display_employee,
        "employee_credited": display_employee,
        "completed_by_employee": display_employee,
        "processed_by_employee": display_employee,
        "credit_reason": credit_reason,
        "attribution_reason": credit_reason,
        "credit_event_type": credit_event_type,
        "credit_signal": credit_event_type,
        "credit_timestamp": credit_ts.isoformat() if credit_ts else None,
        "processed_time": credit_ts.isoformat() if credit_ts else None,
        "processed_timestamp": credit_ts.isoformat() if credit_ts else None,
        "processed_time_et": credit_time_et,
        "processed_signal": credit_event_type,
        "completion_time": completion_ts.isoformat() if completion_ts else row.get("completion_time"),
        "completion_timestamp": completion_ts.isoformat() if completion_ts else row.get("completion_time"),
        "completion_time_et": completion_time_et,
        "completion_signal": row.get("completion_signal") if workload_status == "completed" else None,
        "credited_lbs": lbs,
        "processed_lbs": lbs,
        "completed_lbs": lbs if workload_status == "completed" else None,
        "weight_missing": lbs is None,
        "included_in_employee_productivity": included_in_employee_productivity,
        "excluded_reason": excluded_reason,
    }


def credit_workload_bags(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Credit each unique completed workload bag once. Returns (records, duplicate_bag_ids)."""
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    credited: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []

    for row in workload_rows:
        if not isinstance(row, dict):
            continue
        if _normalize_workload_status(row) != "completed":
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if bid in seen:
            duplicates.append(bid)
            continue
        seen.add(bid)
        events = events_by_bag.get(bid) or []
        record = resolve_workload_bag_credit(
            row,
            events=events,
            selected_date_et=selected_date_et,
            as_of_end=as_of_end,
            registry_meta=registry_meta,
        )
        if record.get("excluded_reason") and "WF completion not on selected ET day" in str(
            record.get("excluded_reason")
        ):
            continue
        credited.append(record)
    return credited, duplicates


def build_completed_attribution_audit(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_date_et: date,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
    rush_filter: str = "all",
    include_hd: bool = True,
) -> list[dict[str, Any]]:
    """Explain every completed workload bag's productivity attribution in scope."""
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    scoped_rows = filter_workload_rows(
        workload_rows,
        rush_filter=rush_filter,
        include_hd=include_hd,
        completed_only=True,
    )
    audit: list[dict[str, Any]] = []
    for row in scoped_rows:
        bid = str(row.get("bag_id") or "").strip().upper()
        events = events_by_bag.get(bid) or []
        record = resolve_workload_bag_credit(
            row,
            events=events,
            selected_date_et=selected_date_et,
            as_of_end=as_of_end,
            registry_meta=registry_meta,
        )
        audit.append(
            {
                "bag_id": record.get("bag_id"),
                "workflow": record.get("workflow"),
                "service_type": record.get("service_type"),
                "rush_bucket": record.get("rush_bucket"),
                "rush_label": record.get("rush_label"),
                "workload_status": record.get("workload_status"),
                "completed_status": record.get("at_vendor_status"),
                "completion_time": record.get("completion_time"),
                "completion_timestamp": record.get("completion_timestamp"),
                "completion_time_et": record.get("completion_time_et"),
                "completion_signal": record.get("completion_signal"),
                "credited_employee": record.get("credited_employee"),
                "credit_reason": record.get("credit_reason"),
                "credit_signal": record.get("credit_signal") or record.get("credit_event_type"),
                "credit_event_type": record.get("credit_event_type"),
                "credit_timestamp": record.get("credit_timestamp"),
                "included_in_employee_productivity": bool(record.get("included_in_employee_productivity")),
                "excluded_reason": record.get("excluded_reason"),
            }
        )
    audit.sort(key=lambda x: str(x.get("credit_timestamp") or x.get("completion_timestamp") or x.get("bag_id") or ""))
    return audit


def _count_completed_scope(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    rush_filter: str = "all",
    include_hd: bool = True,
) -> dict[str, int]:
    scoped = filter_workload_rows(
        workload_rows,
        rush_filter=rush_filter,
        include_hd=include_hd,
        completed_only=True,
    )
    wf = sum(1 for r in scoped if _service_type(r) == "WF")
    hd = sum(1 for r in scoped if _service_type(r) == "HD")
    rush = sum(1 for r in scoped if _rush_bucket(r) == AV_RUSH)
    non_rush = sum(1 for r in scoped if _rush_bucket(r) == AV_NON_RUSH)
    wf_rush = sum(1 for r in scoped if _service_type(r) == "WF" and _rush_bucket(r) == AV_RUSH)
    wf_non_rush = sum(1 for r in scoped if _service_type(r) == "WF" and _rush_bucket(r) == AV_NON_RUSH)
    hd_rush = sum(1 for r in scoped if _service_type(r) == "HD" and _rush_bucket(r) == AV_RUSH)
    hd_non_rush = sum(1 for r in scoped if _service_type(r) == "HD" and _rush_bucket(r) == AV_NON_RUSH)
    return {
        "workload_completed_today": len(scoped),
        "workload_wf_completed": wf,
        "workload_hd_completed": hd,
        "workload_rush_completed": rush,
        "workload_non_rush_completed": non_rush,
        "workload_wf_rush_completed": wf_rush,
        "workload_wf_non_rush_completed": wf_non_rush,
        "workload_hd_rush_completed": hd_rush,
        "workload_hd_non_rush_completed": hd_non_rush,
    }


def build_workload_productivity_reconciliation(
    *,
    workload_rows: Sequence[Mapping[str, Any]],
    credited_bags: Sequence[Mapping[str, Any]],
    duplicate_bag_ids: Sequence[str],
    selected_date_et: date,
    rush_filter: str = "all",
    include_hd: bool = True,
) -> dict[str, Any]:
    """Reconcile credited completed workload bags to Today's Workload completed totals."""
    scope_counts = _count_completed_scope(
        workload_rows,
        rush_filter=rush_filter,
        include_hd=include_hd,
    )
    scoped_completed_ids = {
        str(r.get("bag_id") or "").strip().upper()
        for r in filter_workload_rows(
            workload_rows,
            rush_filter=rush_filter,
            include_hd=include_hd,
            completed_only=True,
        )
        if r.get("bag_id")
    }
    scoped_credited = [
        b
        for b in credited_bags
        if str(b.get("bag_id") or "").strip().upper() in scoped_completed_ids
    ]
    credited_ids = sorted(
        {str(b.get("bag_id") or "").strip().upper() for b in scoped_credited if b.get("bag_id")}
    )
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

    credited_wf = sum(1 for b in scoped_credited if _service_type(b) == "WF")
    credited_hd = sum(1 for b in scoped_credited if _service_type(b) == "HD")
    unassigned = [
        b for b in scoped_credited if str(b.get("credited_employee") or "") == UNASSIGNED_EMPLOYEE
    ]
    unassigned_ids = sorted(str(b.get("bag_id") or "").upper() for b in unassigned if b.get("bag_id"))

    employee_credits: dict[str, set[str]] = {}
    duplicate_credit_count = 0
    for bag in scoped_credited:
        bid = str(bag.get("bag_id") or "").upper()
        emp = str(bag.get("credited_employee") or UNASSIGNED_EMPLOYEE)
        if not bid:
            continue
        bucket = employee_credits.setdefault(emp, set())
        if bid in bucket:
            duplicate_credit_count += 1
        bucket.add(bid)

    missing_from_productivity = sorted(scoped_completed_ids - credited_set)
    extra_in_productivity = sorted(credited_set - scoped_completed_ids)

    workload_completed = scope_counts["workload_completed_today"]
    credited_total = len(credited_ids)
    unassigned_count = len(unassigned_ids)
    employee_attributed = credited_total - unassigned_count

    recon_ok = (
        workload_completed == credited_total
        and not duplicate_bag_ids
        and not missing_from_productivity
        and not extra_in_productivity
        and duplicate_credit_count == 0
        and scope_counts["workload_wf_completed"] == credited_wf
        and (include_hd or credited_hd == 0)
        and (not include_hd or scope_counts["workload_hd_completed"] == credited_hd)
    )

    audit = [
        {
            "bag_id": b.get("bag_id"),
            "workflow": b.get("workflow"),
            "rush_bucket": b.get("rush_bucket"),
            "rush_label": b.get("rush_label"),
            "workload_status": b.get("workload_status"),
            "completed_status": b.get("at_vendor_status"),
            "completion_time": b.get("completion_time"),
            "completion_timestamp": b.get("completion_timestamp"),
            "completion_time_et": b.get("completion_time_et"),
            "completion_signal": b.get("completion_signal"),
            "credited_employee": b.get("credited_employee"),
            "credit_reason": b.get("credit_reason"),
            "credit_signal": b.get("credit_signal") or b.get("credit_event_type"),
            "credit_event_type": b.get("credit_event_type"),
            "credit_timestamp": b.get("credit_timestamp"),
            "included_in_employee_productivity": bool(b.get("included_in_employee_productivity")),
            "excluded_reason": b.get("excluded_reason"),
        }
        for b in sorted(
            scoped_credited,
            key=lambda x: str(x.get("credit_timestamp") or x.get("completion_timestamp") or x.get("bag_id") or ""),
        )
    ]

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "rush_filter": normalize_rush_filter(rush_filter),
        "workload_total": len(workload_rows),
        "workload_wf_total": wf_total,
        "workload_hd_total": hd_total,
        "workload_wf_pending": wf_pending,
        "workload_hd_pending": hd_pending,
        "workload_wf_completed": scope_counts["workload_wf_completed"] if rush_filter != "all" or not include_hd else wf_completed,
        "workload_hd_completed": scope_counts["workload_hd_completed"] if rush_filter != "all" or not include_hd else hd_completed,
        "workload_completed_today": workload_completed,
        "workload_rush_completed": scope_counts["workload_rush_completed"],
        "workload_non_rush_completed": scope_counts["workload_non_rush_completed"],
        "workload_wf_rush_completed": scope_counts["workload_wf_rush_completed"],
        "workload_wf_non_rush_completed": scope_counts["workload_wf_non_rush_completed"],
        "workload_hd_rush_completed": scope_counts["workload_hd_rush_completed"],
        "workload_hd_non_rush_completed": scope_counts["workload_hd_non_rush_completed"],
        "credited_total": credited_total,
        "credited_wf_count": credited_wf,
        "credited_hd_count": credited_hd,
        "credited_completed": credited_total,
        "credited_pending": 0,
        "unassigned_count": unassigned_count,
        "unassigned_bag_ids": unassigned_ids,
        "duplicate_credit_count": duplicate_credit_count,
        "scan_derived_excluded_bag_ids": extra_in_productivity,
        "bags_outside_workload_excluded": extra_in_productivity,
        "employee_credited_unique_bags": employee_attributed,
        "workload_bag_ids": sorted(scoped_completed_ids),
        "credited_bag_ids": credited_ids,
        "missing_from_employee_productivity": missing_from_productivity,
        "extra_in_employee_productivity": extra_in_productivity,
        "duplicate_bag_ids": list(duplicate_bag_ids),
        "wf_count": credited_wf,
        "hd_count": credited_hd,
        "wf_plus_hd": credited_wf + credited_hd,
        "employee_completed_bags_credited": employee_attributed,
        "employee_attributed_bag_count": employee_attributed,
        "difference": workload_completed - credited_total,
        "bags_match_workload_total": workload_completed == credited_total,
        "bags_match_workload_completed": workload_completed == credited_total,
        "credited_plus_unassigned_equals_workload": credited_total == workload_completed,
        "no_duplicate_bags": not duplicate_bag_ids and duplicate_credit_count == 0,
        "ok": recon_ok,
        "status": "reconciled" if recon_ok else "mismatch",
        "status_label": "Reconciled ✓" if recon_ok else "Mismatch ✗",
        "workload_attribution_audit": audit,
        "attribution_audit": audit,
    }
