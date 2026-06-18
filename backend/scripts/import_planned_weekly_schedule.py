#!/usr/bin/env python3
"""Import planned weekly schedule rows for an organization (production-safe with --dry-run).

Examples:
  python -m backend.scripts.import_planned_weekly_schedule --org 3 --week 2026-06-14 --dry-run
  python -m backend.scripts.import_planned_weekly_schedule --org 3 --week 2026-06-14 --apply
  python -m backend.scripts.import_planned_weekly_schedule --org 3 --week 2026-06-14 --apply --replace
  python -m backend.scripts.import_planned_weekly_schedule --org 3 --week 2026-06-14 --json path/to/rows.json --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.planned_weekly_schedule_import import (  # noqa: E402
    VEEWASH_WEEK_2026_06_14,
    import_planned_weekly_schedule,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import planned weekly schedule entries")
    parser.add_argument("--org", type=int, default=3, help="Organization id (default: 3 VeeWash)")
    parser.add_argument("--week", required=True, help="Week anchor date YYYY-MM-DD (snaps to Sunday)")
    parser.add_argument("--json", dest="json_path", help="JSON file with employee rows (default: built-in VeeWash Jun 14)")
    parser.add_argument("--dry-run", action="store_true", help="Validate and match names without writing")
    parser.add_argument("--apply", action="store_true", help="Insert rows into the database")
    parser.add_argument("--replace", action="store_true", help="Delete existing week rows before import (requires --apply)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply", file=sys.stderr)
        return 2
    if args.replace and not args.apply:
        print("--replace requires --apply", file=sys.stderr)
        return 2

    if args.json_path:
        rows = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("rows") or []
    else:
        rows = VEEWASH_WEEK_2026_06_14

    from backend.db import get_db

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        result = import_planned_weekly_schedule(
            conn,
            cursor,
            args.org,
            week_start=args.week,
            rows=rows,
            replace_existing=bool(args.replace and args.apply),
            dry_run=bool(args.dry_run and not args.apply),
        )
        if args.apply and not args.dry_run:
            conn.commit()
        print(json.dumps(result, indent=2, default=str))
        if result.get("name_failures"):
            return 1
        if result.get("parse_errors"):
            return 1
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
