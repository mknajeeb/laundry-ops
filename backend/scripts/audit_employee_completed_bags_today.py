#!/usr/bin/env python3
"""Pre-deploy reconciliation audit for Employee Completed Bags Today."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG = 3


def _today_et() -> date:
    from backend.rinse_scheduled_scrape import _today_et

    return _today_et()


def main() -> None:
    from backend.db import get_db
    from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED, build_at_vendor_module
    from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline

    selected = _today_et()
    if len(sys.argv) > 1:
        selected = date.fromisoformat(sys.argv[1])

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    baseline_ctx = build_baseline_context(cursor, ORG, get_shift_monitor_baseline(cursor, ORG))
    av = build_at_vendor_module(cursor, ORG, selected_date_et=selected, baseline_ctx=baseline_ctx)
    emp_section = av.get("employee_completed_bags_today") or {}
    recon = emp_section.get("reconciliation") or {}
    banner = emp_section.get("reconciliation_banner") or {}
    workload_completed = av.get("completed") or av.get("completed_today_count")

    productivity_rows = []
    for e in emp_section.get("employees") or []:
        productivity_rows.append(
            {
                "employee": e.get("employee"),
                "clock_in_time": e.get("clock_in_time"),
                "clock_in_time_et": e.get("clock_in_time_et"),
                "last_completion_time": e.get("last_completion_time"),
                "last_completion_time_et": e.get("last_completion_time_et"),
                "productive_hours": e.get("productive_hours"),
                "wall_clock_hours": e.get("wall_clock_hours"),
                "elapsed_hours": e.get("worked_hours"),
                "completed_bags": e.get("completed_bags"),
                "completed_pounds": e.get("total_completed_lbs"),
                "bags_per_hour": e.get("bags_per_hour"),
                "lbs_per_hour": e.get("lbs_per_hour"),
                "productivity_note": e.get("productivity_note"),
                "missing_weight_count": e.get("missing_weight_count"),
            }
        )

    drilldown_checks = []
    for e in emp_section.get("employees") or []:
        bags = e.get("bags") or []
        sorted_ts = [b.get("completion_timestamp") or b.get("completion_time") for b in bags]
        asc_ok = sorted_ts == sorted(sorted_ts, key=lambda x: str(x or ""))
        for b in bags:
            drilldown_checks.append(
                {
                    "employee": e.get("employee"),
                    "bag_id": b.get("bag_id"),
                    "completion_timestamp": b.get("completion_timestamp"),
                    "completion_time_et": b.get("completion_time_et"),
                    "employee_credited": b.get("employee_credited"),
                    "drilldown_sorted_asc": asc_ok,
                    "attribution_reason": b.get("attribution_reason"),
                }
            )

    report = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "organization_id": ORG,
        "selected_date_et": selected.isoformat(),
        "deployment_gate": {
            "pass": bool(recon.get("ok")),
            "status": banner.get("status_label") or recon.get("status_label"),
            "do_not_deploy_until_reconciled": not bool(recon.get("ok")),
        },
        "workload_reconciliation": {
            "workload_based_productivity": bool(emp_section.get("workload_based_productivity")),
            "workload_total": recon.get("workload_total") or av.get("total") or av.get("days_load_total"),
            "workload_wf_total": recon.get("workload_wf_total") or av.get("wf_total"),
            "workload_hd_total": recon.get("workload_hd_total") or av.get("hd_total"),
            "credited_total": recon.get("credited_total") or recon.get("employee_attributed_bag_count"),
            "unassigned_count": recon.get("unassigned_count") or 0,
            "credited_plus_unassigned_equals_workload": (
                int(recon.get("credited_total") or recon.get("employee_attributed_bag_count") or 0)
                == int(recon.get("workload_total") or av.get("total") or av.get("days_load_total") or 0)
            ),
            "wf_reconciles": int(recon.get("credited_wf_count") or recon.get("wf_count") or 0)
            == int(recon.get("workload_wf_total") or av.get("wf_total") or 0),
            "hd_reconciles": int(recon.get("credited_hd_count") or recon.get("hd_count") or 0)
            == int(recon.get("workload_hd_total") or av.get("hd_total") or 0),
            "duplicate_credit_count": recon.get("duplicate_credit_count") or 0,
            "scan_derived_excluded": recon.get("scan_derived_excluded_bag_ids") or [],
        },
        "reconciliation_summary": {
            "workload_completed_today": workload_completed,
            "employee_completed_bags_credited": recon.get("employee_attributed_bag_count"),
            "difference": recon.get("difference"),
            "status": recon.get("status"),
            "status_label": recon.get("status_label"),
            "missing_from_employee_dashboard": recon.get("missing_from_employee_dashboard")
            or recon.get("missing_from_employee_productivity")
            or [],
            "extra_in_employee_dashboard": recon.get("extra_in_employee_dashboard")
            or recon.get("extra_in_employee_productivity")
            or [],
            "duplicate_bag_ids": recon.get("duplicate_bag_ids") or [],
        },
        "attribution_audit": emp_section.get("attribution_audit") or [],
        "productivity_validation": productivity_rows,
        "employee_totals": [
            {
                "employee": e.get("employee"),
                "completed_bags": e.get("completed_bags"),
                "total_completed_lbs": e.get("total_completed_lbs"),
            }
            for e in emp_section.get("employees") or []
        ],
        "drilldown_sort_checks": drilldown_checks,
        "wf_hd_split": {
            "wf": recon.get("wf_count"),
            "hd": recon.get("hd_count"),
            "total": recon.get("employee_attributed_bag_count"),
        },
    }

    out_path = REPO_ROOT / "data" / "employee_completed_bags_reconciliation_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps(report["deployment_gate"], indent=2))
    print(json.dumps(report["reconciliation_summary"], indent=2))
    print(f"\nFull report: {out_path}")
    print(f"Attribution rows: {len(report['attribution_audit'])}")
    sys.exit(0 if report["deployment_gate"]["pass"] else 1)


if __name__ == "__main__":
    main()
