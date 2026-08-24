#!/usr/bin/env python3
"""Bounded reconciliation: backfill day-bag completion attribution from scan evidence."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date-et", required=True, help="YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true", help="Write updates (default dry-run)")
    args = parser.parse_args()

    selected = date.fromisoformat(args.date_et)
    from backend.db import get_db
    from backend.management_wf_folder_performance import build_day_folder_performance
    from backend.rinse_day_bag_completion_projection import (
        reconcile_day_bag_completion_projection,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        before = build_day_folder_performance(
            cur, args.org, selected_date_et=selected, attach_customers=False
        )
        before_unmapped = int(before.get("unmapped_count") or 0)
        before_orders = sum(
            int(e.get("orders_completed") or 0) for e in (before.get("employees") or [])
        )

        if args.apply:
            out = reconcile_day_bag_completion_projection(
                cur, args.org, selected, bag_ids=None
            )
            conn.commit()
        else:
            out = {
                "ok": True,
                "dry_run": True,
                "message": "Pass --apply to write reconciliation",
            }

        after_unmapped = before_unmapped
        after_orders = before_orders
        if args.apply:
            after = build_day_folder_performance(
                cur, args.org, selected_date_et=selected, attach_customers=False
            )
            after_unmapped = int(after.get("unmapped_count") or 0)
            after_orders = sum(
                int(e.get("orders_completed") or 0) for e in (after.get("employees") or [])
            )

        report = {
            **out,
            "performance_before": {
                "unmapped_count": before_unmapped,
                "mapped_orders": before_orders,
            },
            "performance_after": {
                "unmapped_count": after_unmapped,
                "mapped_orders": after_orders,
            },
        }
        print(json.dumps(report, indent=2, default=str))
        return 0
    except Exception as exc:
        conn.rollback()
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
