#!/usr/bin/env python3
"""Explain Active Today headline vs drilldown gap for Jul 8.

Classifies every active-tier ledger bag into operational visibility buckets so
supervisors can see why headline != on-screen row count.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
    from backend.rinse_at_vendor_module import (
        MOD_AT_VENDOR_COMPLETED,
        MOD_AT_VENDOR_PENDING,
        build_at_vendor_module,
    )
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )
    from backend.rinse_workload_ledger import (
        ACTIVE_MEMBERSHIP_TIERS,
        is_active_membership_tier,
        load_workload_ledger,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    av = build_at_vendor_module(cur, org, selected_date_et=selected, baseline_ctx=baseline)

    ledger = load_workload_ledger(cur, org, selected)
    row_by_bag = {
        str(r.get("bag_id") or "").strip().upper(): r
        for r in (av.get("rows") or [])
        if r.get("bag_id")
    }
    active_ids = {
        bid
        for bid, rec in ledger.items()
        if is_active_membership_tier(str(rec.get("membership_tier") or ""))
    }

    buckets: Counter = Counter()
    details: list[dict] = []

    for bid in sorted(active_ids):
        rec = ledger[bid]
        row = row_by_bag.get(bid)
        status = str(rec.get("current_status") or "")
        tier = str(rec.get("membership_tier") or "")
        on_drilldown = bid in row_by_bag
        on_portal = row.get("currently_on_vendor_home") is True if row else None
        if row is None:
            snap = rec.get("row_snapshot") or {}
            on_portal = snap.get("currently_on_vendor_home")

        if on_drilldown:
            if MOD_AT_VENDOR_COMPLETED in (row.get("module_tags") or []):
                cat = "on_drilldown_completed"
            elif MOD_AT_VENDOR_PENDING in (row.get("module_tags") or []):
                cat = "on_drilldown_pending"
            else:
                cat = "on_drilldown_other"
        elif status == "completed":
            if row is None and rec.get("row_snapshot"):
                cat = "ledger_only_completed_left_portal"
            else:
                cat = "ledger_only_completed"
        elif status == "needs_verification":
            cat = "ledger_only_needs_verification_off_portal"
        elif status == "pending":
            cat = "ledger_only_pending_off_portal"
        elif status == "sent_to_rinse":
            cat = "ledger_only_sent_to_rinse"
        else:
            cat = f"ledger_only_other_{status}"

        buckets[cat] += 1
        details.append(
            {
                "bag_id": bid,
                "category": cat,
                "membership_tier": tier,
                "ledger_status": status,
                "on_drilldown": on_drilldown,
                "on_portal": on_portal,
            }
        )

    headline = int(av.get("active_today_total") or av.get("total") or 0)
    drilldown = len(row_by_bag)
    gap = headline - drilldown

    report = {
        "org": org,
        "et_date": selected.isoformat(),
        "headline_active_today": headline,
        "drilldown_rows": drilldown,
        "gap": gap,
        "gap_accounted_for": sum(buckets[k] for k in buckets if k.startswith("ledger_only_")),
        "bucket_totals": dict(sorted(buckets.items())),
        "gap_summary": {
            "on_drilldown": sum(v for k, v in buckets.items() if k.startswith("on_drilldown_")),
            "ledger_only_completed_left_portal": buckets.get("ledger_only_completed_left_portal", 0),
            "ledger_only_needs_verification_off_portal": buckets.get(
                "ledger_only_needs_verification_off_portal", 0
            ),
            "ledger_only_pending_off_portal": buckets.get("ledger_only_pending_off_portal", 0),
            "ledger_only_other": sum(
                v for k, v in buckets.items() if k.startswith("ledger_only_") and k
                not in (
                    "ledger_only_completed_left_portal",
                    "ledger_only_needs_verification_off_portal",
                    "ledger_only_pending_off_portal",
                )
            ),
        },
        "active_tier_breakout": av.get("workload_breakout", {}).get("active_today"),
        "sample_ledger_only_completed": [
            d for d in details if d["category"] == "ledger_only_completed_left_portal"
        ][:10],
        "sample_ledger_only_nv": [
            d for d in details if d["category"] == "ledger_only_needs_verification_off_portal"
        ][:10],
    }
    out_path = args.out or f"data/audit_jul8_active_drilldown_gap_org{org}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps({**report, "details": details}, indent=2), encoding="utf-8")
    printable = {k: v for k, v in report.items() if k not in ("sample_ledger_only_completed", "sample_ledger_only_nv")}
    print(json.dumps(printable, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
