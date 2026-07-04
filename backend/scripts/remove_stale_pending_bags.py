#!/usr/bin/env python3
"""
Remove stale Rush WF pending bags that are off-portal and terminal.

Usage:
  python3 -m backend.scripts.remove_stale_pending_bags --org 3 --dry-run
  python3 -m backend.scripts.remove_stale_pending_bags --org 3 --apply
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

DEFAULT_ACTIONS: dict[str, dict] = {
    "69PBB0ZXIV": {
        "action": "completed",
        "completed_at": "2026-06-21 20:46:00",
        "note": "Delivered Jun 21; stale baseline carry",
    },
    "3621ZT1RLO": {
        "action": "noop",
        "note": "Registry already COMPLETED; excluded by off-portal terminal filter",
    },
    "79MJG49XPS": {
        "action": "rejected",
        "force": True,
        "note": "Off-portal reject per operator review",
    },
    "9KI3GEO04V": {
        "action": "completed",
        "completed_at": "2026-06-22 22:18:00",
        "note": "Delivered Jun 22; repeat-trip sent-to-vendor stale carry",
    },
    "5I16QGWDZ5": {
        "action": "rejected",
        "force": True,
        "note": "Operator reject — same-time weight dupes, never completed",
    },
}


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
    parser = argparse.ArgumentParser(description="Remove stale pending at-vendor bags")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.rinse_bag_registry import (
        deactivate_at_vendor_presence_for_bags,
        get_registry_row,
        mark_registry_completed_portal_absence,
        mark_registry_rejected_portal_absence,
    )

    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    results: list[dict] = []
    try:
        batch_id = _latest_confirmed_batch_id(cur, org)
        if batch_id is None:
            print(json.dumps({"error": "No confirmed batch", "org": org}))
            return 1

        for bag_id, spec in DEFAULT_ACTIONS.items():
            before = get_registry_row(cur, org, bag_id)
            entry = {
                "bag_id": bag_id,
                "action": spec["action"],
                "note": spec.get("note"),
                "before_status": (before or {}).get("completion_status"),
                "applied": False,
            }
            if args.dry_run:
                entry["dry_run"] = True
                results.append(entry)
                continue

            action = spec["action"]
            if action == "completed":
                when = datetime.fromisoformat(str(spec["completed_at"]))
                entry["applied"] = mark_registry_completed_portal_absence(
                    cur,
                    org,
                    bag_id,
                    upload_batch_id=batch_id,
                    completed_at=when,
                )
            elif action == "rejected":
                entry["applied"] = mark_registry_rejected_portal_absence(
                    cur,
                    org,
                    bag_id,
                    upload_batch_id=batch_id,
                    force=bool(spec.get("force")),
                )
            elif action == "noop":
                entry["applied"] = True
            else:
                entry["error"] = f"Unknown action {action!r}"

            after = get_registry_row(cur, org, bag_id)
            entry["after_status"] = (after or {}).get("completion_status")
            results.append(entry)

        if args.apply:
            bag_ids = [bid for bid in DEFAULT_ACTIONS if DEFAULT_ACTIONS[bid]["action"] != "noop"]
            deactivated = deactivate_at_vendor_presence_for_bags(cur, org, bag_ids)
            conn.commit()
            print(
                json.dumps(
                    {
                        "organization_id": org,
                        "batch_id": batch_id,
                        "presence_deactivated": deactivated,
                        "results": results,
                    },
                    indent=2,
                    default=str,
                )
            )
        else:
            print(json.dumps({"organization_id": org, "batch_id": batch_id, "results": results}, indent=2))
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
