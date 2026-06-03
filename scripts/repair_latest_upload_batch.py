#!/usr/bin/env python3
"""
Repair the latest Washpro (or any tenant) upload batch after Clean-rack completion fix.

Usage:
  python scripts/repair_latest_upload_batch.py --tenant washpro --latest --dry-run
  python scripts/repair_latest_upload_batch.py --org 1 --latest
  python scripts/repair_latest_upload_batch.py --org 1 --batch-id 115 --dry-run

Only touches the specified organization and one batch (latest or --batch-id).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

from backend.db import get_db  # noqa: E402
import json  # noqa: E402
from backend.repair_latest_upload_batch import (  # noqa: E402
    repair_latest_upload_batch,
    repair_summary_json,
    resolve_organization_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair latest upload batch (completion, row status, staging, folding)"
    )
    parser.add_argument("--org", type=int, default=None, help="organization_id")
    parser.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="organizations.slug or display_name (e.g. washpro)",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Use latest upload_batches row for the org (default when no --batch-id)",
    )
    parser.add_argument("--batch-id", type=int, default=None, help="Specific upload_batches id")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    parser.add_argument(
        "--force-scan-merge",
        action="store_true",
        help="Re-merge upload_batch_scan_events even if persistent events exist",
    )
    parser.add_argument(
        "--reclassify-manual-rows",
        action="store_true",
        help="Reclassify upload_batch_rows using manual checkout eligibility rules",
    )
    args = parser.parse_args()

    if not args.org and not args.tenant:
        parser.error("Provide --org or --tenant")
    if args.batch_id is None and not args.latest:
        args.latest = True

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        org_id, org_meta = resolve_organization_id(
            cursor, organization_id=args.org, tenant=args.tenant
        )
        print(
            f"Organization: id={org_id} slug={org_meta.get('slug')!r} "
            f"name={org_meta.get('display_name')!r}"
        )

        if args.reclassify_manual_rows:
            from backend.manual_checkout_eligibility import reclassify_manual_batch_upload_rows

            batch_id = args.batch_id
            if batch_id is None:
                from backend.repair_latest_upload_batch import find_latest_upload_batch, _upload_batches_pk

                batch = find_latest_upload_batch(cursor, org_id)
                if not batch:
                    raise ValueError(f"No upload_batches rows for organization_id={org_id}")
                batch_id = int(batch[_upload_batches_pk(cursor)])
            summary = reclassify_manual_batch_upload_rows(
                cursor, org_id, int(batch_id), dry_run=args.dry_run
            )
            summary["organization_id"] = org_id
            summary["organization"] = org_meta
            summary["batch_id"] = batch_id
            print(json.dumps(summary, indent=2, default=str))
        elif args.staging_only:
            from backend.checkout_batch_scope import reapply_manual_batch_staging

            batch_id = args.batch_id
            if batch_id is None:
                from backend.repair_latest_upload_batch import find_latest_upload_batch

                batch = find_latest_upload_batch(cursor, org_id)
                if not batch:
                    raise ValueError(f"No upload_batches rows for organization_id={org_id}")
                from backend.repair_latest_upload_batch import _upload_batches_pk

                batch_id = int(batch[_upload_batches_pk(cursor)])
            summary = reapply_manual_batch_staging(
                cursor, org_id, int(batch_id), dry_run=args.dry_run
            )
            summary["organization_id"] = org_id
            summary["organization"] = org_meta
            summary["batch_id"] = batch_id
            print(json.dumps(summary, indent=2, default=str))
        else:
            summary = repair_latest_upload_batch(
                cursor,
                organization_id=org_id,
                tenant=None,
                upload_batch_id=args.batch_id,
                dry_run=args.dry_run,
                force_scan_merge=args.force_scan_merge,
            )
            print(repair_summary_json(summary))

        if args.dry_run:
            print("\n[dry-run] No database changes committed.")
            return 0

        conn.commit()
        print("\nRepair committed successfully.")
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
