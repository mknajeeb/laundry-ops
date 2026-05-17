#!/usr/bin/env python3
"""
Recompute rinse_folding_performance from persisted scan-events (fixes work_date, etc.).

Usage:
  python3 scripts/recompute_folding_performance.py --org 3 --bag 5Y4HKEMEF1
  python3 scripts/recompute_folding_performance.py --org 3 --start 2026-05-11 --end 2026-05-17
  python3 scripts/recompute_folding_performance.py --org 3 --all-completed
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import get_db  # noqa: E402
from backend.rinse_bag_completion import normalize_bag_id  # noqa: E402
from backend.rinse_folding_registry import (  # noqa: E402
    fetch_completed_bag_ids_for_date_range,
    recompute_folding_performance_for_bags,
)
from backend.rinse_bag_registry import (  # noqa: E402
    ensure_rinse_bag_registry_table,
    list_registry_rows,
)
from backend.rinse_bag_completion import COMPLETION_COMPLETED  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute folding performance rows")
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument("--bag", type=str, help="single bag_id")
    parser.add_argument("--start", type=str, help="YYYY-MM-DD range start")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD range end")
    parser.add_argument(
        "--date-field",
        type=str,
        default="completed_at",
        choices=("date_clean", "completed_at", "work_date"),
        help="how to select bags for --start/--end (default completed_at)",
    )
    parser.add_argument(
        "--all-completed",
        action="store_true",
        help="recompute every COMPLETED bag in org",
    )
    args = parser.parse_args()

    if not args.bag and not args.all_completed and not (args.start and args.end):
        parser.error("Provide --bag, --all-completed, or --start and --end")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_rinse_bag_registry_table(cursor)
        bag_ids: list[str] = []
        if args.bag:
            bid = normalize_bag_id(args.bag)
            if not bid:
                print("Invalid bag id", file=sys.stderr)
                return 1
            bag_ids = [bid]
        elif args.start and args.end:
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end)
            bag_ids = fetch_completed_bag_ids_for_date_range(
                cursor, args.org, start, end, date_field=args.date_field
            )
        else:
            rows = list_registry_rows(
                cursor, args.org, status=COMPLETION_COMPLETED, limit=10000, offset=0
            )
            bag_ids = [str(r["bag_id"]) for r in rows if r.get("bag_id")]

        payload = recompute_folding_performance_for_bags(
            cursor, args.org, bag_ids, source_recompute_kind="cli_repair"
        )
        conn.commit()
        summary = payload.get("summary") or {}
        print(
            f"Recomputed {payload.get('bags_requested', 0)} bag(s) for org {args.org}: "
            f"processed={summary.get('processed', 0)} "
            f"calculated={summary.get('calculated', 0)} "
            f"exceptions={summary.get('exceptions', 0)}"
        )
        return 0
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
