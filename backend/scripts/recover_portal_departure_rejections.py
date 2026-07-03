#!/usr/bin/env python3
"""
Recover bags wrongly rejected as MISSING_FROM_LATEST_PORTAL_SCRAPE.

Restores rejection, recovers scans from upload batch history, optionally runs
targeted portal scrape for missing final scans, then marks COMPLETED when evidence exists.

Usage:
  python3 -m backend.scripts.recover_portal_departure_rejections --org 3 --date 2026-07-02 --dry-run
  python3 -m backend.scripts.recover_portal_departure_rejections --org 3 --date 2026-07-02 --apply
  python3 -m backend.scripts.recover_portal_departure_rejections --org 3 --apply --portal-refresh
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _latest_confirmed_batch_id(cursor, org: int) -> int | None:
    cursor.execute(
        """
        SELECT batch_id FROM upload_batches
        WHERE organization_id = %s AND state = 'CONFIRMED'
        ORDER BY batch_id DESC LIMIT 1
        """,
        (int(org),),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return int(row["batch_id"] if isinstance(row, dict) else row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover portal departure rejections")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", type=str, default=None, help="Audit filter YYYY-MM-DD (registry updated_at)")
    parser.add_argument("--bag-id", action="append", default=[], dest="bag_ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--portal-refresh",
        action="store_true",
        help="Run targeted portal scrape for bags still missing completion evidence",
    )
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_bag_registry import recompute_completion_for_bags
    from backend.rinse_portal_departure_completion import (
        detect_portal_departure_completion_evidence,
        list_portal_scrape_rejected_bag_ids,
        recover_missing_scans_from_upload_batch_history,
        restore_portal_scrape_rejected_bag,
        verify_and_resolve_portal_departure_bag,
    )

    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    report: dict = {
        "organization_id": org,
        "dry_run": args.dry_run,
        "bags": [],
        "summary": {},
    }

    try:
        targets = [b.upper() for b in args.bag_ids if b]
        if not targets:
            targets = list_portal_scrape_rejected_bag_ids(cur, org)
            if args.date:
                filter_date = date.fromisoformat(args.date)
                cur.execute(
                    """
                    SELECT bag_id FROM rinse_bag_registry
                    WHERE organization_id = %s
                      AND UPPER(COALESCE(completion_status, '')) = 'REJECTED'
                      AND completion_reason = 'MISSING_FROM_LATEST_PORTAL_SCRAPE'
                      AND DATE(updated_at) = %s
                    ORDER BY bag_id
                    """,
                    (org, filter_date.isoformat()),
                )
                targets = [
                    str(r["bag_id"]).upper()
                    for r in (cur.fetchall() or [])
                    if r.get("bag_id")
                ]

        batch_id = _latest_confirmed_batch_id(cur, org) or 0
        selected_date = date.fromisoformat(args.date) if args.date else date.today()

        for bid in targets:
            entry: dict = {"bag_id": bid, "steps": []}
            if args.dry_run:
                cur.execute(
                    """
                    SELECT completion_status, completion_reason, name_clean, rush_type
                    FROM rinse_bag_registry
                    WHERE organization_id = %s AND bag_id = %s
                    """,
                    (org, bid),
                )
                reg = cur.fetchone() or {}
                entry["registry_before"] = reg
                from backend.rinse_bag_registry import fetch_persistent_scan_events_for_bag

                events = fetch_persistent_scan_events_for_bag(cur, org, bid)
                evidence = detect_portal_departure_completion_evidence(
                    events, service_type=str(reg.get("service_type") or "")
                )
                entry["completion_evidence"] = evidence
                entry["scan_event_count"] = len(events)
                entry["would_restore"] = str(reg.get("completion_reason") or "") == "MISSING_FROM_LATEST_PORTAL_SCRAPE"
                entry["would_action"] = "completed" if evidence else "needs_verification_or_portal_refresh"
                report["bags"].append(entry)
                continue

            restored = restore_portal_scrape_rejected_bag(cur, org, bid)
            entry["steps"].append({"restore_rejection": restored})

            recovery = recover_missing_scans_from_upload_batch_history(
                cur, org, bid, up_to_batch_id=batch_id or None
            )
            entry["steps"].append({"scan_recovery": recovery})

            if args.portal_refresh:
                from backend.rinse_off_portal_scan_refresh import refresh_off_portal_pending_scans

                refresh = refresh_off_portal_pending_scans(
                    cur,
                    org,
                    upload_batch_id=batch_id or None,
                    selected_date_et=selected_date,
                    bag_ids=[bid],
                    dry_run=False,
                )
                entry["steps"].append({"portal_refresh": refresh})

            outcome = verify_and_resolve_portal_departure_bag(
                cur,
                org,
                bid,
                upload_batch_id=int(batch_id or 0),
                recover_scans=False,
            )
            entry["outcome"] = outcome

            recompute = recompute_completion_for_bags(cur, org, [bid])
            entry["recompute"] = recompute

            cur.execute(
                """
                SELECT completion_status, completion_reason, completed_at, trigger_kind
                FROM rinse_bag_registry WHERE organization_id = %s AND bag_id = %s
                """,
                (org, bid),
            )
            entry["registry_after"] = cur.fetchone() or {}
            report["bags"].append(entry)

        if not args.dry_run:
            conn.commit()

        completed = sum(1 for b in report["bags"] if (b.get("outcome") or {}).get("action") == "completed")
        needs_ver = sum(
            1 for b in report["bags"] if (b.get("outcome") or {}).get("action") == "needs_verification"
        )
        rejected = sum(1 for b in report["bags"] if (b.get("outcome") or {}).get("action") == "rejected")
        report["summary"] = {
            "target_count": len(targets),
            "completed": completed,
            "needs_verification": needs_ver,
            "rejected": rejected,
            "batch_id": batch_id,
        }
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
