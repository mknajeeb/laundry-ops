"""Presentation-layer scoping for employee productivity (Phase 1 attribution unchanged)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def _service_type(bag: Mapping[str, Any]) -> str:
    return str(bag.get("service_type") or bag.get("service_bucket") or "").upper()


def _scoped_bags(bags: Sequence[Mapping[str, Any]], *, include_hd: bool) -> list[dict[str, Any]]:
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


def _recalc_employee_metrics(emp: Mapping[str, Any], scoped_bags: list[dict[str, Any]]) -> dict[str, Any]:
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

    clock_in = _parse_ts(emp.get("clock_in_time"))
    productive_hours = emp.get("productive_hours")
    bags_per_hour = emp.get("bags_per_hour")
    lbs_per_hour = emp.get("lbs_per_hour")
    productivity_note = emp.get("productivity_note")

    if clock_in is None:
        productive_hours = None
        bags_per_hour = None
        lbs_per_hour = None
    elif last_comp is not None:
        productive_sec = max(0, int((last_comp - clock_in).total_seconds()))
        productive_hours = round(productive_sec / 3600.0, 4)
        if productive_hours > 0:
            bags_per_hour = round(len(bags_sorted) / productive_hours, 4)
            lbs_per_hour = round(total_lbs / productive_hours, 4) if total_lbs else None
        else:
            bags_per_hour = None
            lbs_per_hour = None
    else:
        productive_hours = None
        bags_per_hour = None
        lbs_per_hour = None

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
            "productive_hours": productive_hours,
            "worked_hours": productive_hours,
            "bags_per_hour": bags_per_hour,
            "lbs_per_hour": lbs_per_hour,
            "productivity_note": productivity_note,
            "wf_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "WF"),
            "hd_bags_in_scope": sum(1 for b in bags_sorted if _service_type(b) == "HD"),
        }
    )
    return out


def _build_executive_summary(employees: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active = [e for e in employees if int(e.get("completed_bags") or 0) > 0]
    total_bags = sum(int(e.get("completed_bags") or 0) for e in employees)
    total_lbs = round(sum(float(e.get("total_completed_lbs") or 0) for e in employees), 2)

    bags_rates = [
        float(e["bags_per_hour"])
        for e in active
        if e.get("bags_per_hour") is not None and not isinstance(e.get("bags_per_hour"), str)
    ]
    lbs_rates = [
        float(e["lbs_per_hour"])
        for e in active
        if e.get("lbs_per_hour") is not None and not isinstance(e.get("lbs_per_hour"), str)
    ]

    def _avg(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    return {
        "total_employees_active": len(active),
        "total_bags_completed": total_bags,
        "total_pounds_completed": total_lbs,
        "average_bags_per_hour": _avg(bags_rates),
        "average_pounds_per_hour": _avg(lbs_rates),
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
        and not recon.get("extra_in_employee_dashboard")
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
    for emp in section.get("employees") or []:
        if not isinstance(emp, dict):
            continue
        bags = _scoped_bags(emp.get("bags") or [], include_hd=include_hd)
        scoped_bag_count += len(bags)
        scoped_employees.append(_recalc_employee_metrics(emp, bags))

    scoped_employees.sort(
        key=lambda e: (
            -(e.get("completed_bags") or 0),
            str(e.get("employee") or "").lower(),
        )
    )

    scoped_recon, scoped_banner = _scoped_reconciliation(
        section,
        include_hd=include_hd,
        scoped_bag_count=scoped_bag_count,
    )

    out = dict(section)
    out["employees"] = scoped_employees
    out["reconciliation"] = scoped_recon
    out["reconciliation_banner"] = scoped_banner
    out["executive_summary"] = _build_executive_summary(scoped_employees)
    out["productivity_scope"] = "wf_plus_hd" if include_hd else "wf_only"
    out["productivity_scope_label"] = "WF + HD" if include_hd else "WF Only"
    out["include_hd_in_employee_productivity"] = include_hd
    if not include_hd:
        out["attribution_audit"] = [
            row
            for row in (section.get("attribution_audit") or [])
            if isinstance(row, dict) and str(row.get("service_type") or "").upper() == "WF"
        ]
    return out
