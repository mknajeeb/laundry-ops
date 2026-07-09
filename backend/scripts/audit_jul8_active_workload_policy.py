#!/usr/bin/env python3
"""Re-audit Jul 8 workload under Active Today policy (headline vs full ledger)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", default="2026-07-08")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")

    selected = date.fromisoformat(args.date)
    org = int(args.org)

    from backend.db import get_db
    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    av = build_at_vendor_module(cur, org, selected_date_et=selected, baseline_ctx=baseline)
    ledger = av.get("workload_ledger") or {}
    breakout = av.get("workload_breakout") or {}

    report = {
        "org": org,
        "et_date": selected.isoformat(),
        "headline": {
            "active_today_total": ledger.get("active_today_total"),
            "dashboard_total": av.get("total"),
            "pending": av.get("pending"),
            "completed": av.get("completed"),
        },
        "active_today_breakout": {
            "new_today": ledger.get("new_today"),
            "carryover_yesterday": ledger.get("carryover_yesterday"),
            "resends_today": ledger.get("resends_today"),
            "active_today_total": ledger.get("active_today_total"),
            "active_today_reconciles": ledger.get("active_today_reconciles"),
        },
        "historical_backlog": {
            "total": ledger.get("historical_backlog_total"),
            "needs_verification": ledger.get("historical_backlog_needs_verification"),
        },
        "excluded_cleanup": {
            "completed_before_day": ledger.get("excluded_completed_before_day"),
            "completed_before_day_bag_ids": ledger.get("excluded_completed_before_day_bag_ids"),
            "rejected": ledger.get("excluded_rejected"),
            "total": ledger.get("excluded_total"),
        },
        "ledger_total": ledger.get("ledger_total"),
        "ledger_total_reconciles": ledger.get("ledger_total_reconciles"),
        "proofs": {
            "active_equals_components": ledger.get("active_today_reconciles"),
            "ledger_equals_segments": ledger.get("ledger_total_reconciles"),
            "headline_not_inflated_by_backlog": (
                int(ledger.get("active_today_total") or 0)
                < int(ledger.get("ledger_total") or 0)
            ),
        },
        "portal_snapshot": av.get("current_live_vendor_home_total"),
        "drilldown_rows": len(av.get("rows") or []),
    }
    out_path = args.out or f"data/audit_jul8_active_workload_policy_org{org}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
