#!/usr/bin/env python3
"""Audit employee completed WF bag weights vs source data for a selected ET day."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

POST_PROCESSING_WEIGHT = "post_processing_weight"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit employee completed WF bag weights")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", required=True, help="ET date YYYY-MM-DD")
    parser.add_argument("--employee", default=None, help="Optional employee name substring filter")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")

    selected = date.fromisoformat(args.date)
    org = int(args.org)

    from backend.db import get_db
    from backend.rinse_employee_completed_bags import build_employee_productivity_dashboard_payload
    from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline
    from backend.rinse_workload_bag_weight import (
        POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL,
        load_portal_upload_weights_for_bags,
        load_registry_weight_context_for_bags,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    payload = build_employee_productivity_dashboard_payload(
        cur, org, selected_date_et=selected, baseline_ctx=baseline
    )
    section = payload.get("employee_completed_bags_today") or {}
    employees = section.get("employees") or []

    bag_rows: list[dict] = []
    for emp in employees:
        name = str(emp.get("employee") or "")
        if args.employee and args.employee.lower() not in name.lower():
            continue
        for bag in emp.get("bags") or []:
            if str(bag.get("service_type") or bag.get("service_bucket") or "").upper() != "WF":
                continue
            bag_rows.append({**bag, "_employee": name})

    bag_ids = sorted({str(b.get("bag_id") or "").upper() for b in bag_rows if b.get("bag_id")})
    portal = load_portal_upload_weights_for_bags(cur, org, bag_ids, selected_date_et=selected)
    registry = load_registry_weight_context_for_bags(cur, org, bag_ids)

    violations: list[dict] = []
    for bag in bag_rows:
        bid = str(bag.get("bag_id") or "").upper()
        signal = str(bag.get("completion_signal") or bag.get("processed_signal") or "")
        weight_lbs = bag.get("weight_lbs")
        if weight_lbs is None:
            weight_lbs = bag.get("completed_lbs")
        if signal == POST_PROCESSING_WEIGHT and weight_lbs is None:
            violations.append(
                {
                    "bag_id": bid,
                    "employee": bag.get("_employee"),
                    "issue": "post_processing_weight_with_null_weight",
                    "signal": signal,
                }
            )

    total_lbs = round(
        sum(float(b.get("weight_lbs") or b.get("completed_lbs") or 0) for b in bag_rows if (b.get("weight_lbs") or b.get("completed_lbs")) is not None),
        2,
    )
    missing = [b for b in bag_rows if (b.get("weight_lbs") or b.get("completed_lbs")) is None]
    employee_rates: list[dict] = []
    for emp in employees:
        if args.employee and args.employee.lower() not in str(emp.get("employee") or "").lower():
            continue
        hrs = float(emp.get("productive_hours") or emp.get("worked_hours") or 0)
        emp_lbs = float(emp.get("total_completed_lbs") or 0)
        reported = emp.get("completed_lbs_per_hour") or emp.get("lbs_per_hour")
        expected = round(emp_lbs / hrs, 4) if hrs > 0 else None
        employee_rates.append(
            {
                "employee": emp.get("employee"),
                "total_completed_lbs": emp_lbs,
                "productive_hours": hrs,
                "reported_lbs_per_hour": reported,
                "expected_lbs_per_hour": expected,
                "matches": expected is None or reported is None or abs(float(reported) - expected) < 0.02,
            }
        )

    report = {
        "org": org,
        "date": selected.isoformat(),
        "employee_filter": args.employee,
        "wf_completed_bags_in_productivity": len(bag_rows),
        "bags_with_weight": len(bag_rows) - len(missing),
        "bags_missing_weight": len(missing),
        "total_display_lbs": total_lbs,
        "signal_violations": violations,
        "employee_lbs_per_hour_checks": employee_rates,
        "sample_missing": [
            {
                "bag_id": b.get("bag_id"),
                "employee": b.get("_employee"),
                "signal": b.get("completion_signal"),
                "weight_debug_reason": b.get("weight_debug_reason"),
                "portal_weight": portal.get(str(b.get("bag_id") or "").upper()),
                "registry_weight": (registry.get(str(b.get("bag_id") or "").upper()) or {}).get("weight_num"),
            }
            for b in missing[:20]
        ],
        "sample_rows": [
            {
                "bag_id": b.get("bag_id"),
                "employee": b.get("_employee"),
                "weight_lbs": b.get("weight_lbs") or b.get("completed_lbs"),
                "weight_source": b.get("weight_source"),
                "weight_status": b.get("weight_status"),
                "signal": b.get("completion_signal"),
            }
            for b in bag_rows[:25]
        ],
        "ok": not violations and all(r.get("matches", True) for r in employee_rates),
    }
    out_path = args.out or f"data/audit_employee_completed_wf_weights_{selected.isoformat()}_org{org}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
