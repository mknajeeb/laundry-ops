"""Presentation-layer scoping for employee productivity (completed production credit only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_employee_completed_bags import PRODUCTIVITY_END_CLOCK_OUT, PRODUCTIVITY_END_LAST_COMPLETION
from backend.rinse_employee_workload_productivity import (
    UNASSIGNED_EMPLOYEE,
    build_completed_attribution_audit,
    build_workload_productivity_reconciliation,
    filter_workload_rows,
    normalize_rush_filter,
)


def _service_type(bag: Mapping[str, Any]) -> str:
    return str(bag.get("service_type") or bag.get("service_bucket") or "").upper()


def _matches_rush(bag: Mapping[str, Any], rush_filter: str) -> bool:
    rush = normalize_rush_filter(rush_filter)
    if rush == "all":
        return True
    bucket = str(bag.get("rush_bucket") or "").upper()
    if rush == "rush":
        return bucket == "RUSH"
    if rush == "non_rush":
        return bucket == "NON_RUSH"
    return True


def _scoped_bags(
    bags: Sequence[Mapping[str, Any]],
    *,
    include_hd: bool,
    rush_filter: str = "all",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bag in bags or []:
        if not isinstance(bag, dict):
            continue
        if not include_hd and _service_type(bag) != "WF":
            continue
        if not _matches_rush(bag, rush_filter):
            continue
        out.append(dict(bag))
    return out


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
    total_lbs_completed: float,
) -> tuple[float | None, float | None, float | None, datetime | None, datetime | None]:
    completed_times = [
        _parse_ts(b.get("completion_time") or b.get("completion_timestamp") or b.get("credit_timestamp"))
        for b in scoped_completed
    ]
    completed_times = [t for t in completed_times if t is not None]
    first_completed = min(completed_times) if completed_times else None
    last_completed = max(completed_times) if completed_times else None

    clock_in = _parse_ts(emp.get("clock_in_time"))
    productive_start = _parse_ts(emp.get("productive_start_time")) or clock_in
    end_source = str(emp.get("productivity_end_source") or PRODUCTIVITY_END_LAST_COMPLETION)
    if end_source == PRODUCTIVITY_END_CLOCK_OUT:
        productive_end_completed = _parse_ts(emp.get("productive_end_time"))
    else:
        productive_end_completed = last_completed

    productive_hours = emp.get("productive_hours")
    completed_bags_per_hour = emp.get("completed_bags_per_hour") or emp.get("bags_per_hour")
    completed_lbs_per_hour = emp.get("completed_lbs_per_hour") or emp.get("lbs_per_hour")

    if clock_in is None:
        return None, None, None, productive_start, productive_end_completed

    if (
        emp.get("roster_role") in ("operator", "folder")
        and emp.get("folding_duration_seconds") is not None
        and len(scoped_completed) == int(emp.get("completed_bags") or 0)
    ):
        productive_sec = max(0, int(emp.get("folding_duration_seconds") or 0))
        productive_hours = round(productive_sec / 3600.0, 4)
    elif productive_start is not None and productive_end_completed is not None:
        productive_sec = max(0, int((productive_end_completed - productive_start).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
    elif last_completed is not None and clock_in is not None:
        productive_sec = max(0, int((last_completed - clock_in).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
    else:
        productive_hours = None

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
        productive_end_completed,
    )


def _recalc_employee_metrics(emp: Mapping[str, Any], scoped_bags: list[dict[str, Any]]) -> dict[str, Any]:
    bags_sorted = sorted(
        scoped_bags,
        key=lambda b: str(
            b.get("completion_time") or b.get("completion_timestamp") or b.get("credit_timestamp") or ""
        ),
    )
    comp_times = [
        _parse_ts(b.get("completion_time") or b.get("completion_timestamp") or b.get("credit_timestamp"))
        for b in bags_sorted
    ]
    comp_times = [t for t in comp_times if t is not None]
    first_comp = min(comp_times) if comp_times else None
    last_comp = max(comp_times) if comp_times else None

    missing_weight_count = sum(1 for b in bags_sorted if b.get("weight_missing"))
    total_lbs = round(
        sum(float(b["completed_lbs"]) for b in bags_sorted if b.get("completed_lbs") is not None),
        2,
    )

    (
        productive_hours,
        completed_bags_per_hour,
        completed_lbs_per_hour,
        productive_start,
        productive_end,
    ) = _resolve_productive_hours(
        emp,
        scoped_completed=bags_sorted,
        total_lbs_completed=total_lbs,
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
            "first_completed_time": first_comp.isoformat() if first_comp else None,
            "last_completed_time": last_comp.isoformat() if last_comp else None,
            "first_completed_time_et": _ts_et(first_comp),
            "last_completed_time_et": _ts_et(last_comp),
            "productive_start_time": (
                productive_start.isoformat() if productive_start is not None else emp.get("productive_start_time")
            ),
            "productive_end_time": (
                productive_end.isoformat() if productive_end is not None else emp.get("productive_end_time")
            ),
            "productive_hours": productive_hours,
            "worked_hours": productive_hours,
            "completed_bags_per_hour": completed_bags_per_hour,
            "completed_lbs_per_hour": completed_lbs_per_hour,
            "bags_per_hour": completed_bags_per_hour,
            "lbs_per_hour": completed_lbs_per_hour,
            "processed_bags_per_hour": completed_bags_per_hour,
            "processed_lbs_per_hour": completed_lbs_per_hour,
            "credited_bags_count": len(bags_sorted),
            "total_credited_lbs": total_lbs,
            "processed_bags_count": len(bags_sorted),
            "processed_bags": bags_sorted,
            "total_processed_lbs": total_lbs,
            "workload_bags": bags_sorted,
            "pending_completion_count": 0,
            "pending_completion_bags": [],
            "show_processed_completed_split": False,
            "folding_blocks": emp.get("folding_blocks") or [],
            "folding_duration_seconds": emp.get("folding_duration_seconds"),
            "productivity_note": emp.get("productivity_note"),
            "wf_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "WF"),
            "hd_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "HD"),
        }
    )
    return out


def _build_executive_summary(employees: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active_completed = [e for e in employees if int(e.get("completed_bags") or 0) > 0]
    total_completed = sum(int(e.get("completed_bags") or 0) for e in employees)
    total_completed_lbs = round(sum(float(e.get("total_completed_lbs") or 0) for e in employees), 2)
    unassigned_count = sum(
        int(e.get("completed_bags") or 0)
        for e in employees
        if str(e.get("employee") or "").startswith("Unassigned")
    )

    completed_rates = [
        float(e["completed_bags_per_hour"])
        for e in active_completed
        if e.get("completed_bags_per_hour") is not None
        and not isinstance(e.get("completed_bags_per_hour"), str)
    ]
    completed_lbs_rates = [
        float(e["completed_lbs_per_hour"])
        for e in active_completed
        if e.get("completed_lbs_per_hour") is not None
        and not isinstance(e.get("completed_lbs_per_hour"), str)
    ]
    total_productive_hours = round(
        sum(float(e.get("productive_hours") or e.get("worked_hours") or 0) for e in active_completed),
        4,
    )
    missing_weight_total = sum(int(e.get("missing_weight_count") or 0) for e in employees)

    def _avg(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    global_lbs_per_hour: float | None = None
    if total_productive_hours > 0 and total_completed_lbs > 0:
        global_lbs_per_hour = round(total_completed_lbs / total_productive_hours, 2)

    missing_weight_warning: str | None = None
    if missing_weight_total > 0 and total_completed > 0:
        missing_weight_warning = (
            f"{missing_weight_total} of {total_completed} completed bags missing weight; "
            "lbs/hr may be understated."
        )

    return {
        "total_employees_active": len(active_completed),
        "total_bags_completed": total_completed,
        "total_pounds_completed": total_completed_lbs,
        "total_unassigned_bags": unassigned_count,
        "average_completed_bags_per_hour": _avg(completed_rates),
        "average_completed_pounds_per_hour": global_lbs_per_hour or _avg(completed_lbs_rates),
        "total_productive_hours": total_productive_hours if total_productive_hours > 0 else None,
        "missing_weight_count": missing_weight_total,
        "missing_weight_warning": missing_weight_warning,
        # Backward-compatible aliases
        "total_bags_credited": total_completed,
        "total_credited_lbs": total_completed_lbs,
        "total_pending_completion": 0,
        "average_bags_per_hour": _avg(completed_rates),
        "average_pounds_per_hour": global_lbs_per_hour or _avg(completed_lbs_rates),
        "total_bags_processed": total_completed,
        "total_pounds_processed": total_completed_lbs,
        "average_processed_bags_per_hour": _avg(completed_rates),
        "average_processed_pounds_per_hour": _avg(completed_lbs_rates),
    }


def _scoped_reconciliation(
    section: Mapping[str, Any],
    *,
    include_hd: bool,
    rush_filter: str,
    scoped_credited_bags: Sequence[Mapping[str, Any]],
    workload_rows: Sequence[Mapping[str, Any]] | None = None,
    selected_date_et: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    recon = dict(section.get("reconciliation") or {})
    banner = dict(section.get("reconciliation_banner") or {})
    workload_based = bool(section.get("workload_based_productivity"))
    scoped_bag_count = len(scoped_credited_bags)

    if workload_based and workload_rows is not None and selected_date_et:
        from datetime import date as date_cls

        scoped_recon = build_workload_productivity_reconciliation(
            workload_rows=workload_rows,
            credited_bags=scoped_credited_bags,
            duplicate_bag_ids=recon.get("duplicate_bag_ids") or [],
            selected_date_et=date_cls.fromisoformat(str(selected_date_et)),
            rush_filter=rush_filter,
            include_hd=include_hd,
        )
        scoped_banner = {
            **banner,
            "employee_completed_bags_credited": scoped_recon.get("employee_attributed_bag_count"),
            "workload_completed_today": scoped_recon.get("workload_completed_today"),
            "difference": scoped_recon.get("difference"),
            "status": scoped_recon.get("status"),
            "status_label": scoped_recon.get("status_label"),
            "unassigned_count": scoped_recon.get("unassigned_count"),
        }
        scoped_recon["productivity_scope_wf_only"] = not include_hd
        scoped_recon["productivity_rush_filter"] = normalize_rush_filter(rush_filter)
        return scoped_recon, scoped_banner

    if include_hd:
        workload = int(recon.get("workload_completed_today") or banner.get("workload_completed_today") or 0)
    else:
        workload = int(recon.get("workload_wf_completed") or recon.get("wf_count") or scoped_bag_count)
    credited = scoped_bag_count
    difference = workload - credited
    recon_ok = (
        credited == workload
        and recon.get("no_duplicate_bags", True)
        and not recon.get("duplicate_bag_ids")
        and not recon.get("missing_from_employee_productivity")
        and not recon.get("missing_from_employee_dashboard")
    )
    status = "reconciled" if recon_ok else "mismatch"
    status_label = "Reconciled ✓" if recon_ok else "Mismatch ✗"
    scoped_recon = {
        **recon,
        "workload_completed_today": workload,
        "employee_attributed_bag_count": credited,
        "employee_completed_bags_credited": credited,
        "credited_total": credited,
        "difference": difference,
        "status": status,
        "status_label": status_label,
        "ok": recon_ok,
        "bags_match_workload_completed": credited == workload,
        "productivity_scope_wf_only": not include_hd,
        "productivity_rush_filter": normalize_rush_filter(rush_filter),
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
    rush_filter: str = "all",
    workload_rows: Sequence[Mapping[str, Any]] | None = None,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    registry_meta_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Filter employee_completed_bags_today for dashboard display (completed credit only)."""
    rush = normalize_rush_filter(rush_filter)
    if not isinstance(section, dict):
        return {
            "employees": [],
            "executive_summary": _build_executive_summary([]),
            "productivity_scope": "wf_only" if not include_hd else "wf_plus_hd",
            "productivity_scope_label": "WF Only" if not include_hd else "WF + HD",
            "include_hd_in_employee_productivity": include_hd,
            "productivity_rush_filter": rush,
            "completed_attribution_audit": [],
        }

    scoped_employees: list[dict[str, Any]] = []
    scoped_credited_bags: list[dict[str, Any]] = []
    for emp in section.get("employees") or []:
        if not isinstance(emp, dict):
            continue
        completed = _scoped_bags(emp.get("bags") or [], include_hd=include_hd, rush_filter=rush)
        scoped_credited_bags.extend(completed)
        scoped_employees.append(_recalc_employee_metrics(emp, completed))

    scoped_employees.sort(
        key=lambda e: (
            -(e.get("completed_bags") or 0),
            str(e.get("employee") or "").lower(),
        )
    )

    scoped_recon, scoped_banner = _scoped_reconciliation(
        section,
        include_hd=include_hd,
        rush_filter=rush,
        scoped_credited_bags=scoped_credited_bags,
        workload_rows=workload_rows,
        selected_date_et=section.get("selected_date_et"),
    )

    completed_attribution_audit = [
        row
        for row in (section.get("completed_attribution_audit") or section.get("attribution_audit") or [])
        if isinstance(row, dict)
        and (include_hd or str(row.get("workflow") or row.get("service_type") or "").upper() == "WF")
        and _matches_rush(row, rush)
    ]
    if workload_rows is not None and events_by_bag is not None and section.get("selected_date_et"):
        from datetime import date as date_cls

        completed_attribution_audit = build_completed_attribution_audit(
            workload_rows,
            events_by_bag=events_by_bag,
            selected_date_et=date_cls.fromisoformat(str(section.get("selected_date_et"))),
            registry_meta=registry_meta_by_bag,
            rush_filter=rush,
            include_hd=include_hd,
        )

    out = dict(section)
    out["employees"] = scoped_employees
    out["reconciliation"] = scoped_recon
    out["reconciliation_banner"] = scoped_banner
    out["executive_summary"] = _build_executive_summary(scoped_employees)
    out["productivity_scope"] = "wf_plus_hd" if include_hd else "wf_only"
    out["productivity_scope_label"] = "WF + HD" if include_hd else "WF Only"
    out["include_hd_in_employee_productivity"] = include_hd
    out["productivity_rush_filter"] = rush
    out["completed_attribution_audit"] = completed_attribution_audit
    out["attribution_audit"] = completed_attribution_audit
    out["processed_attribution_audit"] = completed_attribution_audit
    return out
