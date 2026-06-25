#!/usr/bin/env python3
"""Resolve stale portal attention rows and confirm the latest DRAFT upload batch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=1, help="Organization id (default: 1 Washpro)")
    args = parser.parse_args()
    org = int(args.org)

    from backend.db import get_db
    from backend.manual_checkout_eligibility import resolve_stale_portal_attention_rows_before_confirm
    from backend.upload_batch_confirm import UploadBatchConfirmError, confirm_upload_batch_core

    conn = get_db()
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT batch_id, state, uploaded_at, orders_loaded
        FROM upload_batches
        WHERE organization_id = %s AND state = 'DRAFT'
        ORDER BY batch_id DESC
        LIMIT 1
        """,
        (org,),
    )
    batch = c.fetchone()
    if not batch:
        print(json.dumps({"error": "No DRAFT batch found", "org": org}))
        return 1

    batch_id = int(batch["batch_id"])
    resolved = resolve_stale_portal_attention_rows_before_confirm(c, org, batch_id)
    try:
        payload = confirm_upload_batch_core(c, org, batch_id, force_confirm=False)
    except UploadBatchConfirmError as exc:
        conn.rollback()
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "batch_id": batch_id,
                    "resolved": resolved,
                    "payload": exc.payload,
                },
                indent=2,
                default=str,
            )
        )
        return 1

    conn.commit()
    c.execute(
        "SELECT COUNT(*) AS cnt FROM rinse_bag_scan_events WHERE source_upload_batch_id = %s",
        (batch_id,),
    )
    live_scans = int((c.fetchone() or {}).get("cnt") or 0)
    print(
        json.dumps(
            {
                "batch_id": batch_id,
                "resolved": resolved,
                "confirm": payload,
                "live_scans_imported": live_scans,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
