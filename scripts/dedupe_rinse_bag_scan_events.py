#!/usr/bin/env python3
"""
Remove duplicate rinse_bag_scan_events rows (same org, bag, dedupe_key).

Keeps the row with the smallest id per duplicate group.
Does not modify rinse_bag_registry.

Usage:
  .venv/bin/python scripts/dedupe_rinse_bag_scan_events.py
  .venv/bin/python scripts/dedupe_rinse_bag_scan_events.py --org 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.db import get_db
from backend.rinse_bag_registry import (
    backfill_scan_event_dedupe_keys,
    delete_duplicate_scan_events,
    ensure_rinse_bag_scan_events_dedupe_schema,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedupe rinse_bag_scan_events")
    parser.add_argument("--org", type=int, default=None, help="Organization id (default: all)")
    args = parser.parse_args()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_rinse_bag_scan_events_dedupe_schema(cursor)
        backfilled = backfill_scan_event_dedupe_keys(cursor, args.org)
        deleted = delete_duplicate_scan_events(cursor, args.org)
        conn.commit()
        print(
            f"Done. backfilled_dedupe_keys={backfilled} deleted_duplicate_rows={deleted}"
            + (f" org={args.org}" if args.org else " (all orgs)")
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
