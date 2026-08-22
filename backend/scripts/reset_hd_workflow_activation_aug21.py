#!/usr/bin/env python3
"""Production HD workflow activation reset (2026-08-21 ET).

Soft-quarantines pre-activation hd_day_bag_production rows (no DELETE),
then seeds Aug 21 HD day_bags membership into durable pending/washed/awaiting rows.

Usage (from repo root, with MYSQL_* in .env):
  python -m backend.scripts.reset_hd_workflow_activation_aug21 --org 3 --apply
  python -m backend.scripts.reset_hd_workflow_activation_aug21 --org 3 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from backend.db import get_db
from backend.management_rinse_hd import (
    HD_WORKFLOW_ACTIVATION_DATE,
    build_rinse_hd_day,
    run_hd_activation_reset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument(
        "--opening-date",
        default=HD_WORKFLOW_ACTIVATION_DATE.isoformat(),
        help="Opening ET date (default activation day)",
    )
    parser.add_argument("--apply", action="store_true", help="Commit quarantine+seed")
    parser.add_argument("--dry-run", action="store_true", help="Rollback after compute")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        print("Pass --apply or --dry-run", file=sys.stderr)
        return 2

    from datetime import date

    opening = date.fromisoformat(args.opening_date)
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        result = run_hd_activation_reset(
            cursor,
            args.org,
            opening_date_et=opening,
            actor_user_id=None,
        )
        day = build_rinse_hd_day(cursor, args.org, opening, status="all")
        out = {
            "activation_date_et": HD_WORKFLOW_ACTIVATION_DATE.isoformat(),
            "reset": result,
            "verify_day": {
                "date_et": day.get("date_et"),
                "summary": day.get("summary"),
                "counts": day.get("counts"),
                "order_count": len(day.get("orders") or []),
                "durable_admission": (day.get("_meta") or {}).get("durable_admission"),
            },
        }
        print(json.dumps(out, default=str, indent=2))
        if args.apply and result.get("ok"):
            conn.commit()
            print("COMMITTED", file=sys.stderr)
        else:
            conn.rollback()
            print("ROLLED BACK (dry-run or not ok)", file=sys.stderr)
            return 0 if args.dry_run else 1
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
