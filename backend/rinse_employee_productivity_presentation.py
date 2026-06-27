"""Presentation-layer scoping for employee productivity (Phase 1 attribution unchanged)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_employee_completed_bags import (
    PRODUCTIVITY_END_CLOCK_OUT,
    PRODUCTIVITY_END_LAST_COMPLETION,
    WF_POST_PROCESSING_WEIGHT_SIGNAL,
)


def _service_type(bag: Mapping[str, Any]) -> str:
    return str(bag.get("service_type") or bag.get("service_bucket") or "").upper()


def _scoped_bags(bags: Sequence[Mapping[str, Any]], *, include_hd: bool) -> list[dict[str, Any]]:
    if include_hd:
        return [dict(b) for b in (bags or []) if isinstance(b, dict)]
    return [dict(b) for b in (bags or []) if isinstance(b, dict) and _service_type(b) == "WF"]


def _scoped_processed_bags(bags: Sequence[Mapping[str, Any]], *, include_hd: bool) -> list[dict[str, Any]]:
    if include_hd:
        return [dict(b) for b in (bags or []) if isinstance(b, dict)]
    return [dict(b) for b in (bags or []) if isinstance(b, dict) and _service_type(b) == "WF"]


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _productivity_rates(
    *,
    count: int,
    total_lbs: float,
    productive_hours: float | None,
) -> tuple[float | None, float | None]:
    if productive_hours is None or productive_hours <= 0:
        return None, None
    bags_rate = round(count / productive_hours, 4)
    lbs_rate = round(total_lbs / productive_hours, 4) if total_lbs else None
    return bags_rate, lbs_rate


def _resolve_productive_hours(
    emp: Mapping[str, Any],
    *,
    scoped_completed: list[dict[str, Any]],
    scoped_processed: list[dict[str, Any]],
    total_lbs_completed: float,
) -> tuple[float | None, float | None, float | None, datetime | None, datetime | None]:
    """Return productive_hours, completed_bags_per_hour, completed_lbs_per_hour, productive_start, productive_end."""
    completed_times = [
        _parse_ts(b.get("completion_time") or b.get("completion_timestamp")) for b in scoped_completed
    ]
    completed_times = [t for t in completed_times if t is not None]
    processed_times = [_parse_ts(b.get("processed_time") or b.get("processed_timestamp")) for b in scoped_processed]
    processed_times = [t for t in processed_times if t is not None]

    first_completed = min(completed_times) if completed_times else None
    last_completed = max(completed_times) if completed_times else None
    last_processed = max(processed_times) if processed_times else None

    clock_in = _parse_ts(emp.get("clock_in_time"))
    productive_start = _parse_ts(emp.get("productive_start_time")) or clock_in
    end_source = str(emp.get("productivity_end_source") or PRODUCTIVITY_END_LAST_COMPLETION)
    if end_source == PRODUCTIVITY_END_CLOCK_OUT:
        productive_end_completed = _parse_ts(emp.get("productive_end_time"))
    else:
        productive_end_completed = last_completed
    productive_end_processed = last_processed or productive_end_completed

    productive_hours = emp.get("productive_hours")
    completed_bags_per_hour = emp.get("bags_per_hour")
    completed_lbs_per_hour = emp.get("lbs_per_hour")

    if clock_in is None:
        return None, None, None, productive_start, productive_end_processed

    if (
        emp.get("roster_role") in ("operator", "folder")
        and emp.get("folding_duration_seconds") is not None
        and len(scoped_completed) == int(emp.get("completed_bags") or 0)
        and len(scoped_processed) == int(emp.get("processed_bags_count") or 0)
    ):
        productive_sec = max(0, int(emp.get("folding_duration_seconds") or 0))
        productive_hours = round(productive_sec / 3600.0, 4)
    elif productive_start is not None and productive_end_processed is not None:
        productive_sec = max(0, int((productive_end_processed - productive_start).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
    elif last_processed is not None and clock_in is not None:
        productive_sec = max(0, int((last_processed - clock_in).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
    elif last_completed is not None and clock_in is not None:
        productive_sec = max(0, int((last_completed - clock_in).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
    else:
        productive_hours = None

    if productive_end_completed is None:
        productive_end_completed = productive_end_processed

    completed_bags_per_hour, completed_lbs_per_hour = _productivity_rates(
        count=len(scoped_completed),
        total_lbs=total_lbs_completed,
        productive_hours=productive_hours,
    )
    return (
        productive_hours,
        completed_bags_per_hour,
        completed_lbs_per_hour,
        productive_start,
        productive_end_processed if last_processed else productive_end_completed,
    )


def _recalc_employee_metrics(
    emp: Mapping[str, Any],
    scoped_bags: list[dict[str, Any]],
    *,
    scoped_processed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    processed_sorted = sorted(
        scoped_processed if scoped_processed is not None else list(emp.get("processed_bags") or []),
        key=lambda b: str(b.get("processed_time") or b.get("processed_timestamp") or ""),
    )
    bags_sorted = sorted(scoped_bags, key=lambda b: str(b.get("completion_time") or b.get("completion_timestamp") or ""))
    comp_times = [_parse_ts(b.get("completion_time") or b.get("completion_timestamp")) for b in bags_sorted]
    comp_times = [t for t in comp_times if t is not None]
    first_comp = min(comp_times) if comp_times else None
    last_comp = max(comp_times) if comp_times else None

    missing_weight_count = sum(1 for b in bags_sorted if b.get("weight_missing"))
    total_lbs = round(
        sum(float(b["completed_lbs"]) for b in bags_sorted if b.get("completed_lbs") is not None),
        2,
    )

    total_processed_lbs = round(
        sum(float(b["processed_lbs"]) for b in processed_sorted if b.get("processed_lbs") is not None),
        2,
    )
    completed_ids = {str(b.get("bag_id") or "").upper() for b in bags_sorted if b.get("bag_id")}
    processed_ids = {str(b.get("bag_id") or "").upper() for b in processed_sorted if b.get("bag_id")}
    for bag in processed_sorted:
        bid = str(bag.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if (
            _service_type(bag) == "WF"
            and str(bag.get("processed_signal") or "") == WF_POST_PROCESSING_WEIGHT_SIGNAL
        ):
            completed_ids.add(bid)
    pending_ids = sorted(processed_ids - completed_ids)
    pending_bags = [b for b in processed_sorted if str(b.get("bag_id") or "").upper() in pending_ids]

    processed_times = [_parse_ts(b.get("processed_time") or b.get("processed_timestamp")) for b in processed_sorted]
    processed_times = [t for t in processed_times if t is not None]
    first_processed = min(processed_times) if processed_times else None
    last_processed = max(processed_times) if processed_times else None

    productivity_note = emp.get("productivity_note")
    (
        productive_hours,
        completed_bags_per_hour,
        completed_lbs_per_hour,
        productive_start,
        productive_end,
    ) = _resolve_productive_hours(
        emp,
        scoped_completed=bags_sorted,
        scoped_processed=processed_sorted,
        total_lbs_completed=total_lbs,
    )

    processed_bags_per_hour, processed_lbs_per_hour = _productivity_rates(
        count=len(processed_sorted),
        total_lbs=total_processed_lbs,
        productive_hours=productive_hours,
    )

    from backend.rinse_scan_time import format_rinse_wall_et_display

    def _ts_et(raw: datetime | None) -> str | None:
        if raw is None:
            return None
        return format_rinse_wall_et_display(raw)

    out = dict(emp)
    out.update(
        {
            "bags": bags_sorted,
            "completed_bags": len(bags_sorted),
            "total_completed_lbs": total_lbs,
            "missing_weight_count": missing_weight_count,
            "first_completion_time": first_comp.isoformat() if first_comp else None,
            "last_completion_time": last_comp.isoformat() if last_comp else None,
            "first_completion_time_et": _ts_et(first_comp),
            "last_completion_time_et": _ts_et(last_comp),
            "processed_bags": processed_sorted,
            "processed_bags_count": len(processed_sorted),
            "total_processed_lbs": total_processed_lbs,
            "pending_completion_count": len(pending_ids),
            "pending_completion_bags": pending_bags,
            "first_processed_time": first_processed.isoformat() if first_processed else None,
            "last_processed_time": last_processed.isoformat() if last_processed else None,
            "first_processed_time_et": _ts_et(first_processed),
            "last_processed_time_et": _ts_et(last_processed),
            "productive_start_time": (
                productive_start.isoformat() if productive_start is not None else emp.get("productive_start_time")
            ),
            "productive_end_time": (
                productive_end.isoformat() if productive_end is not None else emp.get("productive_end_time")
            ),
            "productive_hours": productive_hours,
            "worked_hours": productive_hours,
            "processed_bags_per_hour": processed_bags_per_hour,
            "processed_lbs_per_hour": processed_lbs_per_hour,
            "completed_bags_per_hour": completed_bags_per_hour,
            "completed_lbs_per_hour": completed_lbs_per_hour,
            "bags_per_hour": processed_bags_per_hour,
            "lbs_per_hour": processed_lbs_per_hour,
            "folding_blocks": emp.get("folding_blocks") or [],
            "folding_duration_seconds": emp.get("folding_duration_seconds"),
            "productivity_note": productivity_note,
            "wf_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "WF"),
            "hd_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "HD"),
            "wf_processed_in_scope": sum(1 for b in processed_sorted if _service_type(b) == "WF"),
            "hd_processed_in_scope": sum(1 for b in processed_sorted if _service_type(b) == "HD"),
        }
    )
    return out


def _build_executive_summary(employees: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active_processed = [e for e in employees if int(e.get("processed_bags_count") or 0) > 0]
    active_completed = [e for e in employees if int(e.get("completed_bags") or 0) > 0]
    total_processed = sum(int(e.get("processed_bags_count") or 0) for e in employees)
    total_completed = sum(int(e.get("completed_bags") or 0) for e in employees)
    total_processed_lbs = round(sum(float(e.get("total_processed_lbs") or 0) for e in employees), 2)
    total_completed_lbs = round(sum(float(e.get("total_completed_lbs") or 0) for e in employees), 2)
    total_pending = sum(int(e.get("pending_completion_count") or 0) for e in employees)

    processed_rates = [
        float(e["processed_bags_per_hour"])
        for e in active_processed
        if e.get("processed_bags_per_hour") is not None
        and not isinstance(e.get("processed_bags_per_hour"), str)
    ]
    completed_rates = [
        float(e["completed_bags_per_hour"])
        for e in active_completed
        if e.get("completed_bags_per_hour") is not None
        and not isinstance(e.get("completed_bags_per_hour"), str)
    ]
    processed_lbs_rates = [
        float(e["processed_lbs_per_hour"])
        for e in active_processed
        if e.get("processed_lbs_per_hour") is not None
        and not isinstance(e.get("processed_lbs_per_hour"), str)
    ]
    completed_lbs_rates = [
        float(e["completed_lbs_per_hour"])
        for e in active_completed
        if e.get("completed_lbs_per_hour") is not None
        and not isinstance(e.get("completed_lbs_per_hour"), str)
    ]

    def _avg(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    return {
        "total_employees_active": len(active_processed) or len(active_completed),
        "total_bags_processed": total_processed,
        "total_bags_completed": total_completed,
        "total_pending_completion": total_pending,
        "total_pounds_processed": total_processed_lbs,
        "total_pounds_completed": total_completed_lbs,
        "average_processed_bags_per_hour": _avg(processed_rates),
        "average_completed_bags_per_hour": _avg(completed_rates),
        "average_processed_pounds_per_hour": _avg(processed_lbs_rates),
        "average_completed_pounds_per_hour": _avg(completed_lbs_rates),
        "average_bags_per_hour": _avg(processed_rates),
        "average_pounds_per_hour": _avg(processed_lbs_rates),
    }


def _scoped_reconciliation(
    section: Mapping[str, Any],
    *,
    include_hd: bool,
    scoped_bag_count: int,
) -> dict[str, Any]:
    recon = dict(section.get("reconciliation") or {})
    banner = dict(section.get("reconciliation_banner") or {})
    wf_count = int(recon.get("wf_count") or 0)
    hd_count = int(recon.get("hd_count") or 0)

    if include_hd:
        workload = int(recon.get("workload_completed_today") or banner.get("workload_completed_today") or 0)
        credited = scoped_bag_count
    else:
        workload = wf_count
        credited = scoped_bag_count

    difference = workload - credited
    recon_ok = (
        credited == workload
        and (include_hd or hd_count == 0 or credited == wf_count)
        and recon.get("no_duplicate_bags", True)
        and not recon.get("duplicate_bag_ids")
        and not recon.get("missing_from_employee_dashboard")
    )
    if not include_hd:
        recon_ok = credited == workload and recon.get("no_duplicate_bags", True)

    status = "reconciled" if recon_ok else "mismatch"
    status_label = "Reconciled ✓" if recon_ok else "Mismatch ✗"
    scoped_recon = {
        **recon,
        "workload_completed_today": workload,
        "employee_attributed_bag_count": credited,
        "employee_completed_bags_credited": credited,
        "difference": difference,
        "status": status,
        "status_label": status_label,
        "ok": recon_ok,
        "bags_match_workload_completed": credited == workload,
        "productivity_scope_wf_only": not include_hd,
    }
    scoped_banner = {
        **banner,
        "employee_completed_bags_credited": credited,
        "workload_completed_today": workload,
        "difference": difference,
        "status": status,
        "status_label": status_label,
    }
    return scoped_recon, scoped_banner


def apply_employee_productivity_scope(
    section: Mapping[str, Any] | None,
    *,
    include_hd: bool,
) -> dict[str, Any]:
    """Filter Phase 1 employee_completed_bags_today for dashboard display only."""
    if not isinstance(section, dict):
        return {
            "employees": [],
            "executive_summary": _build_executive_summary([]),
            "productivity_scope": "wf_only" if not include_hd else "wf_plus_hd",
            "productivity_scope_label": "WF Only" if not include_hd else "WF + HD",
            "include_hd_in_employee_productivity": include_hd,
        }

    scoped_employees: list[dict[str, Any]] = []
    scoped_bag_count = 0
    scoped_processed_count = 0
    for emp in section.get("employees") or []:
        if not isinstance(emp, dict):
            continue
        bags = _scoped_bags(emp.get("bags") or [], include_hd=include_hd)
        processed = _scoped_processed_bags(emp.get("processed_bags") or [], include_hd=include_hd)
        scoped_bag_count += len(bags)
        scoped_processed_count += len(processed)
        recalced = _recalc_employee_metrics(emp, bags, scoped_processed=processed)
        scoped_employees.append(recalced)

    scoped_employees.sort(
        key=lambda e: (
            -(e.get("processed_bags_count") or e.get("completed_bags") or 0),
            str(e.get("employee") or "").lower(),
        )
    )

    scoped_recon, scoped_banner = _scoped_reconciliation(
        section,
        include_hd=include_hd,
        scoped_bag_count=scoped_bag_count,
    )

    processed_summary = dict(section.get("processed_summary") or {})
    if not include_hd:
        processed_summary = {
            **processed_summary,
            "total_processed_bags": scoped_processed_count,
            "wf_processed_count": scoped_processed_count,
            "hd_processed_count": 0,
        }

    out = dict(section)
    out["employees"] = scoped_employees
    out["reconciliation"] = scoped_recon
    out["reconciliation_banner"] = scoped_banner
    out["executive_summary"] = _build_executive_summary(scoped_employees)
    out["processed_summary"] = processed_summary
    out["productivity_scope"] = "wf_plus_hd" if include_hd else "wf_only"
    out["productivity_scope_label"] = "WF + HD" if include_hd else "WF Only"
    out["include_hd_in_employee_productivity"] = include_hd
    if not include_hd:
        out["attribution_audit"] = [
            row
            for row in (section.get("attribution_audit") or [])
            if isinstance(row, dict) and str(row.get("service_type") or "").upper() == "WF"
        ]
        out["processed_attribution_audit"] = [
            row
            for row in (section.get("processed_attribution_audit") or [])
            if isinstance(row, dict) and str(row.get("service_type") or "").upper() == "WF"
        ]
    return out
