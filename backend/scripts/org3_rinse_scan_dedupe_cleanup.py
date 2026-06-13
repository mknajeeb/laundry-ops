#!/usr/bin/env python3
"""
Back up and dedupe org-3 rinse_bag_scan_events canonical rows.

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.org3_rinse_scan_dedupe_cleanup --dry-run
  python3 -m backend.scripts.org3_rinse_scan_dedupe_cleanup --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG_ID = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Org-3 rinse scan event dedupe cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Report only; no deletes")
    parser.add_argument("--apply", action="store_true", help="Apply dedupe after backup")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_bag_registry import (
        backfill_scan_event_dedupe_keys,
        delete_duplicate_scan_events,
        ensure_rinse_bag_scan_events_dedupe_schema,
    )
    from backend.ta_helpers import table_exists

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        if not table_exists(cur, "rinse_bag_scan_events"):
            print("rinse_bag_scan_events table missing")
            return 1

        cur.execute("SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=%s", (ORG_ID,))
        total_before = int((cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM (
              SELECT organization_id, bag_id, dedupe_key
              FROM rinse_bag_scan_events
              WHERE organization_id=%s AND dedupe_key IS NOT NULL AND dedupe_key != ''
              GROUP BY organization_id, bag_id, dedupe_key
            ) t
            """,
            (ORG_ID,),
        )
        canonical_before = int((cur.fetchone() or {}).get("c") or 0)

        cur.execute("SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=1")
        org1_before = int((cur.fetchone() or {}).get("c") or 0)

        report = {
            "organization_id": ORG_ID,
            "total_rows_before": total_before,
            "canonical_unique_before": canonical_before,
            "duplicate_rows_before": max(0, total_before - canonical_before),
            "org1_rows_before": org1_before,
            "dry_run": args.dry_run,
        }
        print(json.dumps(report, indent=2))

        if args.dry_run:
            return 0

        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_dir = REPO_ROOT / "data" / "rinse-backups" / f"org3_scan_dedupe_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cur.execute("SELECT * FROM rinse_bag_scan_events WHERE organization_id=%s", (ORG_ID,))
        rows = cur.fetchall() or []
        (out_dir / "rinse_bag_scan_events_org3.json").write_text(
            json.dumps(rows, default=str, indent=2)
        )
        print(f"backup written to {out_dir}")

        backfill_scan_event_dedupe_keys(cur, ORG_ID)
        ensure_rinse_bag_scan_events_dedupe_schema(cur)
        removed = delete_duplicate_scan_events(cur, ORG_ID)
        conn.commit()

        cur.execute("SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=%s", (ORG_ID,))
        total_after = int((cur.fetchone() or {}).get("c") or 0)
        cur.execute("SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=1")
        org1_after = int((cur.fetchone() or {}).get("c") or 0)

        after = {
            **report,
            "duplicates_removed": removed,
            "total_rows_after": total_after,
            "rows_retained": total_after,
            "org1_rows_after": org1_after,
            "org1_unchanged": org1_before == org1_after,
        }
        print(json.dumps(after, indent=2))
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
