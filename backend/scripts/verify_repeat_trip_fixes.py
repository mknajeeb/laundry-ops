#!/usr/bin/env python3
"""Post-deploy verification for repeat-trip sorting + workload fixes."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG = 3
SELECTED = date(2026, 6, 25)
WORKLOAD_BAGS = ["73NBRCJBHJ", "86CK96LI6E", "DJMFG1YEH7"]
SORT_BAG = "DJMFG1YEH7"
EXPECTED = {
    "73NBRCJBHJ": {"employee": "Yessenia", "time": "15:37", "lbs": 10.5},
    "86CK96LI6E": {"employee": "Yessenia", "time": "14:49", "lbs": 6.5},
    "DJMFG1YEH7": {"employee": "Evelin", "time": "13:31", "lbs": 16.9},
}


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_shift_analysis import _load_scan_events_for_bags
    from backend.rinse_sorting_chronology import extract_sorting_sessions_for_bag

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    report: dict = {"org": ORG, "selected_date_et": SELECTED.isoformat(), "ok": True, "checks": []}

    try:
        av = build_at_vendor_module(cur, ORG, selected_date_et=SELECTED)
        completed = {
            str(r.get("bag_id") or "").upper(): r
            for r in (av.get("rows") or [])
            if r.get("at_vendor_status") == "Completed"
        }
        still_ids = {
            str(r.get("bag_id") or "").upper()
            for r in (av.get("completed_before_day_start_still_present_rows") or [])
        }
        emp_bags: dict[str, dict] = {}
        for emp in (av.get("employee_completed_bags_today") or {}).get("employees") or []:
            for bag in emp.get("bags") or []:
                bid = str(bag.get("bag_id") or "").upper()
                if bid:
                    emp_bags[bid] = bag

        for bid in WORKLOAD_BAGS:
            exp = EXPECTED[bid]
            row = completed.get(bid)
            bag = emp_bags.get(bid)
            check = {
                "bag_id": bid,
                "in_completed_today": row is not None,
                "not_still_present": bid not in still_ids,
                "employee": (bag or {}).get("employee_credited") or (bag or {}).get("completed_by_employee"),
                "lbs": (bag or {}).get("completed_lbs") or (bag or {}).get("weight"),
                "completion_time_et": (row or {}).get("completion_time_et"),
            }
            if not check["in_completed_today"]:
                report["ok"] = False
            if not check["not_still_present"]:
                report["ok"] = False
            if exp["employee"].lower() not in str(check["employee"] or "").lower():
                report["ok"] = False
            if float(check["lbs"] or 0) != exp["lbs"]:
                report["ok"] = False
            if exp["time"] not in str(check["completion_time_et"] or ""):
                report["ok"] = False
            report["checks"].append(check)

        events = (_load_scan_events_for_bags(cur, ORG, [SORT_BAG]).get(SORT_BAG) or [])
        sessions = extract_sorting_sessions_for_bag(
            SORT_BAG, events, selected_date_et=SELECTED
        )
        francis = [s for s in sessions if "Francis" in str(s.get("employee") or "")]
        maria = [s for s in sessions if "Maria" in str(s.get("employee") or "")]
        sort_check = {
            "bag_id": SORT_BAG,
            "session_count": len(sessions),
            "francis_sessions": len(francis),
            "maria_session": maria[0] if maria else None,
            "max_duration_hours": max((s.get("duration_seconds") or 0) for s in sessions)
            / 3600
            if sessions
            else 0,
        }
        if sort_check["francis_sessions"]:
            report["ok"] = False
        if sort_check["session_count"] != 1:
            report["ok"] = False
        if sort_check["max_duration_hours"] > 1:
            report["ok"] = False
        if maria:
            dur = maria[0].get("duration_seconds") or 0
            if dur > 600:
                report["ok"] = False
        report["sorting"] = sort_check
        report["completed_today_count"] = av.get("completed_today_count")
        report["reconciliation_ok"] = (av.get("reconciliation") or {}).get("ok")

        print(json.dumps(report, indent=2, default=str))
        return 0 if report["ok"] else 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
