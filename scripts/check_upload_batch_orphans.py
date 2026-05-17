#!/usr/bin/env python3
"""
Report (and optionally fix) orphan upload_batch_rows / upload_batch_scan_events.

Orphans: child.upload_batch_id with no matching upload_batches parent.

Usage:
  python scripts/check_upload_batch_orphans.py
  python scripts/check_upload_batch_orphans.py --organization-id 3
  python scripts/check_upload_batch_orphans.py --fix
  python scripts/check_upload_batch_orphans.py --fix --add-fk-cascade
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import get_db  # noqa: E402
from backend.upload_batch_cleanup import (  # noqa: E402
    count_orphan_upload_batch_children,
    delete_orphan_upload_batch_children,
    ensure_upload_batch_child_fk_cascade,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect/fix orphan upload batch child rows (all tenants)"
    )
    parser.add_argument(
        "--organization-id",
        type=int,
        default=None,
        help="Limit scan-event orphan report/fix to one organization_id",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Delete orphan child rows only (never deletes upload_batches)",
    )
    parser.add_argument(
        "--add-fk-cascade",
        action="store_true",
        help="With --fix: also add ON DELETE CASCADE FKs after orphan cleanup",
    )
    args = parser.parse_args()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        before = count_orphan_upload_batch_children(
            cursor, organization_id=args.organization_id
        )
        print(json.dumps({"orphans_before": before}, indent=2))

        if not args.fix:
            total = (
                before["upload_batch_rows"]["total"]
                + before["upload_batch_scan_events"]["total"]
            )
            return 1 if total > 0 else 0

        deleted = delete_orphan_upload_batch_children(
            cursor, organization_id=args.organization_id
        )
        fk_result = None
        if args.add_fk_cascade:
            fk_result = ensure_upload_batch_child_fk_cascade(
                cursor, cleanup_orphans=False
            )

        conn.commit()
        after = count_orphan_upload_batch_children(
            cursor, organization_id=args.organization_id
        )
        out = {
            "orphans_deleted": deleted,
            "orphans_after": after,
        }
        if fk_result is not None:
            out["fk_migration"] = fk_result
        print(json.dumps(out, indent=2))
        total_after = (
            after["upload_batch_rows"]["total"]
            + after["upload_batch_scan_events"]["total"]
        )
        return 1 if total_after > 0 else 0
    except Exception as exc:
        conn.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
