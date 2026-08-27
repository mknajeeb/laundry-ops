#!/usr/bin/env python3
"""Recover Missing From Portal via scan evidence, then single terminal reproject."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORG = 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-08-26", help="ET shift date YYYY-MM-DD")
    parser.add_argument("--org", type=int, default=ORG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = date.fromisoformat(args.date)

    from backend.db import get_db
    from backend.management_rinse_wf_review import (
        CATEGORY_MISSING_PORTAL,
        compute_canonical_wf_review_membership,
    )
    from backend.rinse_wf_missing_portal_scan_recovery import (
        recover_missing_portal_bags_from_scan_evidence,
    )
    from backend.rinse_wf_service_cycle_compat import terminal_project_canonical_wf_day_snapshot

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        membership_before = compute_canonical_wf_review_membership(
            cur, args.org, target
        )
        missing_before = list(membership_before.get(CATEGORY_MISSING_PORTAL) or [])

        recovery = recover_missing_portal_bags_from_scan_evidence(
            cur, args.org, target, dry_run=args.dry_run
        )

        projection = None
        if not args.dry_run:
            projection = terminal_project_canonical_wf_day_snapshot(
                cur, args.org, target, force=True
            )
            conn.commit()

        membership_after = compute_canonical_wf_review_membership(
            cur, args.org, target
        )
        missing_after = list(membership_after.get(CATEGORY_MISSING_PORTAL) or [])

        report = {
            "target": target.isoformat(),
            "organization_id": args.org,
            "dry_run": args.dry_run,
            "missing_before_count": len(missing_before),
            "missing_before_ids": sorted(missing_before),
            "auto_recovered_count": recovery.get("auto_recovered_count"),
            "auto_recovered_ids": recovery.get("auto_recovered"),
            "manual_required_count": recovery.get("manual_required_count"),
            "manual_required_ids": recovery.get("manual_required"),
            "missing_after_count": len(missing_after),
            "missing_after_ids": sorted(missing_after),
            "recovery": recovery,
            "projection": projection,
        }
        print(json.dumps(report, indent=2, default=str))
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
