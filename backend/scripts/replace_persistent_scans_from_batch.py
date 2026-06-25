#!/usr/bin/env python3
"""
Replace persistent rinse_bag_scan_events from a confirmed upload batch export.

Each bag in the batch gets its full portal timeline re-imported (old cycle scans
deleted first). Recomputes registry completion and folding performance.

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.replace_persistent_scans_from_batch --org 3 --dry-run
  python3 -m backend.scripts.replace_persistent_scans_from_batch --org 3 --apply
  python3 -m backend.scripts.replace_persistent_scans_from_batch --org 3 --batch-id 1441 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace persistent scans from batch export")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--batch-id", type=int, default=None, help="Confirmed batch (default: latest)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_bag_registry import merge_scan_events_from_upload, recompute_completion_for_bags
    from backend.rinse_folding_registry import recompute_folding_after_upload
    from backend.rinse_upload_finalize import load_upload_batch_scan_events_as_dataframe
    from backend.ta_helpers import table_exists

    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        if not table_exists(cur, "upload_batch_scan_events"):
            print(json.dumps({"error": "upload_batch_scan_events missing"}))
            return 1

        batch_id = args.batch_id
        if batch_id is None:
            cur.execute(
                """
                SELECT batch_id, state, uploaded_at
                FROM upload_batches
                WHERE organization_id = %s AND state = 'CONFIRMED'
                ORDER BY batch_id DESC
                LIMIT 1
                """,
                (org,),
            )
            row = cur.fetchone()
            if not row:
                print(json.dumps({"error": "No CONFIRMED batch found", "org": org}))
                return 1
            batch_id = int(row["batch_id"])
        else:
            cur.execute(
                """
                SELECT batch_id, state, uploaded_at
                FROM upload_batches
                WHERE organization_id = %s AND batch_id = %s
                """,
                (org, int(batch_id)),
            )
            row = cur.fetchone()
            if not row:
                print(json.dumps({"error": "Batch not found", "batch_id": batch_id}))
                return 1
            if str(row.get("state") or "").upper() != "CONFIRMED":
                print(
                    json.dumps(
                        {
                            "error": "Batch is not CONFIRMED",
                            "batch_id": batch_id,
                            "state": row.get("state"),
                        }
                    )
                )
                return 1

        events_df = load_upload_batch_scan_events_as_dataframe(cur, org, int(batch_id))
        cur.execute(
            """
            SELECT COUNT(*) AS cnt, COUNT(DISTINCT bag_id) AS bags
            FROM upload_batch_scan_events
            WHERE organization_id = %s AND upload_batch_id = %s
            """,
            (org, int(batch_id)),
        )
        staging = cur.fetchone() or {}
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
            """,
            (org,),
        )
        persistent_before = int((cur.fetchone() or {}).get("cnt") or 0)

        report: dict = {
            "organization_id": org,
            "batch_id": int(batch_id),
            "uploaded_at": str(row.get("uploaded_at") or ""),
            "staging_rows": int(staging.get("cnt") or 0),
            "staging_bags": int(staging.get("bags") or 0),
            "persistent_rows_before": persistent_before,
            "dry_run": args.dry_run,
        }

        if events_df.empty:
            report["error"] = "No staging scan events for batch"
            print(json.dumps(report, indent=2, default=str))
            return 1

        if args.dry_run:
            report["would_replace_bags"] = int(events_df["Bag ID"].nunique())
            print(json.dumps(report, indent=2, default=str))
            return 0

        merge_payload = merge_scan_events_from_upload(
            cur,
            org,
            int(batch_id),
            events_df,
            source_filename=f"replace_batch_{batch_id}",
            replace_existing=True,
            credential_sourced=True,
        )
        bag_ids = list(merge_payload.get("bag_ids") or [])
        completion_payload = recompute_completion_for_bags(cur, org, bag_ids) if bag_ids else {}
        folding_payload = recompute_folding_after_upload(cur, org, bag_ids) if bag_ids else {}

        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
            """,
            (org,),
        )
        persistent_after = int((cur.fetchone() or {}).get("cnt") or 0)

        conn.commit()
        report.update(
            {
                "merge": merge_payload,
                "completion": {
                    "bags_recomputed": completion_payload.get("bags_recomputed"),
                    "bags_completed": completion_payload.get("bags_completed"),
                },
                "folding": {
                    "bags_recomputed": (folding_payload or {}).get("bags_recomputed"),
                    "exceptions": (folding_payload or {}).get("exceptions"),
                },
                "persistent_rows_after": persistent_after,
            }
        )
        print(json.dumps(report, indent=2, default=str))
        return 0
    except Exception as exc:
        conn.rollback()
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
