#!/usr/bin/env python3
"""Apply near-complete WF post-processing weight backfill for specific bags or today's pending."""

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", type=str, default=None, help="ET day YYYY-MM-DD (default today ET)")
    parser.add_argument("--bag-id", action="append", default=[], dest="bag_ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional JSON report path",
    )
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    from backend.db import get_db
    from backend.rinse_near_complete_wf_backfill import backfill_near_complete_wf_after_refresh
    from backend.rinse_scheduled_scrape import _today_et
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    selected = date.fromisoformat(args.date) if args.date else _today_et()
    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    report = backfill_near_complete_wf_after_refresh(
        conn,
        cur,
        org,
        selected_date_et=selected,
        baseline_ctx=baseline,
        bag_ids=args.bag_ids or None,
        dry_run=bool(args.dry_run),
    )
    report["organization_id"] = org
    report["selected_date_et"] = selected.isoformat()

    out_path = Path(
        args.out
        or (
            REPO
            / "data"
            / f"near_complete_wf_backfill_{selected.isoformat()}_org{org}"
            f"{'_dry_run' if args.dry_run else '_apply'}.json"
        )
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("dry_run", "bags_considered", "eligible", "applied")}, indent=2))
    for bag in report.get("bags") or []:
        if bag.get("eligible") or bag.get("applied") or bag.get("error"):
            print(
                bag.get("bag_id"),
                "eligible="+str(bag.get("eligible")),
                "applied="+str(bag.get("applied")),
                "status="+str(((bag.get("after") or {}).get("at_vendor_status"))),
                "credit="+str(bag.get("credited_employee")),
                "lbs="+str(bag.get("registry_weight_lbs")),
                bag.get("skip_reason") or "",
            )
    print(f"\nReport: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
