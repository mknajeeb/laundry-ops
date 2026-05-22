#!/usr/bin/env python3
"""
Recompute rinse_bag_registry completion from persistent rinse_bag_scan_events.

Usage:
  python scripts/recompute_bag_completion.py --org <organization_id> --bag BAGID
  python scripts/recompute_bag_completion.py --org <organization_id> --all-incomplete
  python scripts/recompute_bag_completion.py --org <organization_id> --all-completed
  python scripts/recompute_bag_completion.py --org <organization_id> --bags BAG1,BAG2
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
from backend.rinse_bag_completion import normalize_bag_id  # noqa: E402
from backend.rinse_bag_registry import (  # noqa: E402
    apply_completion_to_registry,
    ensure_rinse_bag_registry_table,
    list_registry_rows,
)
from backend.rinse_bag_upload import recompute_bag_completion_with_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute bag completion from persisted scans")
    parser.add_argument("--org", type=int, required=True, help="organization_id")
    parser.add_argument("--bag", type=str, help="single bag_id")
    parser.add_argument(
        "--all-incomplete",
        action="store_true",
        help="recompute every INCOMPLETE bag for org",
    )
    parser.add_argument(
        "--all-completed",
        action="store_true",
        help="recompute every COMPLETED bag for org (fixes stale OR-era false completes)",
    )
    parser.add_argument(
        "--bags",
        type=str,
        help="comma-separated bag_ids",
    )
    parser.add_argument(
        "--stale-legacy-reasons",
        action="store_true",
        help="recompute bags still carrying pre-Clean-rack completion reasons",
    )
    parser.add_argument(
        "--upload-batch-id",
        type=int,
        help="recompute every bag_id on this upload batch (portal + scan-events)",
    )
    args = parser.parse_args()

    if (
        not args.bag
        and not args.all_incomplete
        and not args.all_completed
        and not args.bags
        and not args.stale_legacy_reasons
        and args.upload_batch_id is None
    ):
        parser.error(
            "Provide --bag, --bags, --all-incomplete, --all-completed, "
            "--stale-legacy-reasons, or --upload-batch-id"
        )

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
        elif args.bags:
            bag_ids = []
            for raw in str(args.bags).split(","):
                bid = normalize_bag_id(raw.strip())
                if bid:
                    bag_ids.append(bid)
        elif args.upload_batch_id is not None:
            from backend.repair_latest_upload_batch import _collect_bag_ids_from_batch

            bag_ids = sorted(
                _collect_bag_ids_from_batch(cursor, args.org, int(args.upload_batch_id))
            )
        elif args.stale_legacy_reasons:
            cursor.execute(
                """
                SELECT bag_id FROM rinse_bag_registry
                WHERE organization_id = %s
                  AND (
                    completion_reason IN (
                      'CLEAN_WITHOUT_QUALIFYING_LATER_SCAN',
                      'POST_CLEAN_RACK_AND_USER',
                      'POST_CLEAN_RACK_OR_USER',
                      'WORKFLOW_THEN_CLEAN'
                    )
                    OR (
                      completion_status = 'COMPLETED'
                      AND completion_reason NOT IN ('CLEAN_RACK_SCANNED', 'MISSING_FROM_LATEST_PORTAL_UPLOAD')
                    )
                  )
                """,
                (int(args.org),),
            )
            bag_ids = [str(r["bag_id"]) for r in cursor.fetchall() or [] if r.get("bag_id")]
        elif args.all_completed:
            rows = list_registry_rows(
                cursor, args.org, status="COMPLETED", limit=5000, offset=0
            )
            bag_ids = [str(r["bag_id"]) for r in rows if r.get("bag_id")]
        else:
            rows = list_registry_rows(
                cursor, args.org, status="INCOMPLETE", limit=5000, offset=0
            )
            bag_ids = [str(r["bag_id"]) for r in rows if r.get("bag_id")]

        for bid in bag_ids:
            payload = recompute_bag_completion_with_audit(cursor, args.org, bid)
            after = payload.get("after") or {}
            line = (
                f"{bid}: {payload.get('before', {}).get('completion_status')} -> "
                f"{after.get('completion_status')} ({after.get('completion_reason')})"
            )
            if after.get("folding_performance_deleted"):
                line += " [folding performance row removed]"
            print(line)
        conn.commit()
        print(f"Recomputed {len(bag_ids)} bag(s) for org {args.org}")
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
