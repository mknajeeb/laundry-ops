#!/usr/bin/env python3
"""
Apply portal departure verification on a confirmed batch (prod backfill).

Bags missing from the batch portal export are verified — completed bags are
marked COMPLETED; bags without completion evidence enter needs-verification;
only explicit cancellations are REJECTED.

Usage:
  python3 -m backend.scripts.apply_portal_scrape_rejected_rule --org 3 --dry-run
  python3 -m backend.scripts.apply_portal_scrape_rejected_rule --org 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_accepted_portal_rows(cursor, org: int, batch_id: int) -> list[dict]:
    from backend.ta_helpers import table_has_column

    tid = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
    cursor.execute(
        f"""
        SELECT date_clean, name_clean, weight_num, service_type, rush_type{tid}
        FROM upload_batch_rows
        WHERE upload_batch_id = %s AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (int(batch_id),),
    )
    return list(cursor.fetchall() or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply portal scrape rejected rule")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--batch-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_portal_absence_completion import reject_bags_missing_from_latest_portal

    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
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
                print(json.dumps({"error": "No CONFIRMED batch", "org": org}))
                return 1
            batch_id = int(row["batch_id"])
        else:
            cur.execute(
                "SELECT batch_id, state FROM upload_batches WHERE organization_id=%s AND batch_id=%s",
                (org, int(batch_id)),
            )
            row = cur.fetchone()
            if not row or str(row.get("state") or "").upper() != "CONFIRMED":
                print(json.dumps({"error": "Batch not confirmed", "batch_id": batch_id}))
                return 1

        accepted = _load_accepted_portal_rows(cur, org, int(batch_id))
        if args.dry_run:
            from backend.rinse_portal_absence_completion import (
                build_current_upload_bag_ids,
                fetch_incomplete_bag_candidates_for_org,
                upload_batch_is_full_snapshot_portal,
            )

            is_full = upload_batch_is_full_snapshot_portal(cur, org, int(batch_id), accepted)
            current = build_current_upload_bag_ids(accepted)
            candidates = fetch_incomplete_bag_candidates_for_org(cur, org)
            missing = sorted(b for b in candidates if b not in current)
            print(
                json.dumps(
                    {
                        "organization_id": org,
                        "batch_id": int(batch_id),
                        "full_snapshot": is_full,
                        "portal_bags": len(current),
                        "would_reject": missing,
                        "would_reject_count": len(missing),
                        "dry_run": True,
                    },
                    indent=2,
                )
            )
            return 0

        payload = reject_bags_missing_from_latest_portal(
            cur, org, int(batch_id), accepted
        )
        conn.commit()
        print(json.dumps({"organization_id": org, "batch_id": int(batch_id), **payload}, indent=2, default=str))
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
