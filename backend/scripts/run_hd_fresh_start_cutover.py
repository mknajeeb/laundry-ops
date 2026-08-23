#!/usr/bin/env python3
"""Production HD fresh-start cutover script.

Captures before counts + retained Pending Wash IDs, runs fresh start, verifies after state.

Usage:
  python -m backend.scripts.run_hd_fresh_start_cutover --org 3 --dry-run
  python -m backend.scripts.run_hd_fresh_start_cutover --org 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys

from backend.business_time import business_today
from backend.db import get_db
from backend.hd_workflow_extensions import _workflow_status_counts, run_hd_fresh_start
from backend.management_rinse_hd import build_rinse_hd_day


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date-et", default="", help="ET day for pending-wash snapshot (default today)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        print("Pass --apply or --dry-run", file=sys.stderr)
        return 2

    from datetime import date

    day = date.fromisoformat(args.date_et) if args.date_et else business_today()
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        before_counts = _workflow_status_counts(cursor, args.org)
        pending_before = build_rinse_hd_day(cursor, args.org, day, status="pending_wash")
        retained_preview = [o.get("bag_id") for o in (pending_before.get("orders") or [])]

        if args.apply:
            result = run_hd_fresh_start(cursor, args.org, selected_date_et=day)
            conn.commit()
        else:
            result = {
                "ok": True,
                "dry_run": True,
                "would_retain_pending_wash_ids": retained_preview,
                "before": before_counts,
            }
            conn.rollback()

        after = build_rinse_hd_day(cursor, args.org, day, status="all")
        out = {
            "fresh_start_at": result.get("fresh_start_at"),
            "before": before_counts,
            "retained_pending_wash_ids": result.get("retained_pending_wash_ids", retained_preview),
            "after": result.get("after") or {
                "pending_wash": after.get("summary", {}).get("pending_wash"),
                "awaiting_fold": after.get("summary", {}).get("awaiting_fold"),
                "awaiting_entry": after.get("summary", {}).get("awaiting_entry"),
                "complete": after.get("summary", {}).get("complete"),
                "excluded": after.get("summary", {}).get("excluded"),
            },
            "reset": result,
        }
        print(json.dumps(out, default=str, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
