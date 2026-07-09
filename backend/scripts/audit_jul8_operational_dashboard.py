#!/usr/bin/env python3
"""Re-audit Jul 8 under operational dashboard policy (Total = Pending + Completed; NV separate)."""

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
    from backend.rinse_at_vendor_module import build_at_vendor_module, validate_days_load_invariant
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    av = build_at_vendor_module(cur, org, selected_date_et=selected, baseline_ctx=baseline)

    exc = av.get("operational_exceptions") or {}
    audit = av.get("audit_ledger") or {}
    ledger = audit.get("workload_ledger") or av.get("workload_ledger") or {}
    breakout = audit.get("workload_breakout") or {}

    total = int(av.get("total") or 0)
    pending = int(av.get("pending") or 0)
    completed = int(av.get("completed") or 0)
    nv_count = int(exc.get("needs_verification_count") or len(exc.get("needs_verification_rows") or []))
    row_ids = {str(r.get("bag_id")).upper() for r in (av.get("rows") or []) if r.get("bag_id")}
    nv_ids = {str(r.get("bag_id")).upper() for r in (exc.get("needs_verification_rows") or []) if r.get("bag_id")}

    try:
        validate_days_load_invariant(av)
        invariant_ok = True
        invariant_error = None
    except AssertionError as e:
        invariant_ok = False
        invariant_error = str(e)

    report = {
        "org": org,
        "et_date": selected.isoformat(),
        "operational_dashboard": {
            "total": total,
            "pending": pending,
            "completed": completed,
            "total_equals_pending_plus_completed": total == pending + completed,
            "row_count": len(av.get("rows") or []),
            "rows_match_total": len(av.get("rows") or []) == total,
        },
        "operational_exceptions": {
            "needs_verification_count": nv_count,
            "needs_verification_bag_ids_sample": sorted(nv_ids)[:10],
        },
        "audit_ledger": {
            "ledger_total": breakout.get("ledger_total") or ledger.get("ledger_total"),
            "active_today_total": ledger.get("active_today_total"),
            "historical_backlog_total": ledger.get("historical_backlog_total"),
            "excluded_total": ledger.get("excluded_total"),
        },
        "proofs": {
            "invariant_ok": invariant_ok,
            "invariant_error": invariant_error,
            "nv_not_in_operational_rows": len(row_ids & nv_ids) == 0,
            "ledger_separate_from_operational": (
                int(breakout.get("ledger_total") or ledger.get("ledger_total") or 0) >= total
            ),
        },
        "employee_productivity": {
            "workload_completed_today": (
                (av.get("employee_completed_bags_today") or {})
                .get("reconciliation", {})
                .get("workload_completed_today")
            ),
            "operational_completed": completed,
        },
    }

    out_path = args.out or REPO / f"data/audit_jul8_operational_dashboard_{selected.isoformat()}_org{org}.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["proofs"]["invariant_ok"] and report["proofs"]["nv_not_in_operational_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
