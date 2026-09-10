#!/usr/bin/env python3
"""Repair org-3 HD reset admissions that used stale active presence.

Quarantines HD production rows that are NOT in the intended hang_dry
ship_to_vendor window capture. Preserves scans/OI/WF. Does not change
fresh_start_at or scraper sources.

Usage:
  PYTHONPATH=. python3 -m backend.scripts.repair_hd_stale_ship_window_admission \\
    --org 3 --ship-start 2026-09-09 --ship-end 2026-09-10 --dry-run

  PYTHONPATH=. python3 -m backend.scripts.repair_hd_stale_ship_window_admission \\
    --org 3 --ship-start 2026-09-09 --ship-end 2026-09-10 --apply \\
    --allow-captured-untrusted
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from backend.db import get_db
from backend.hd_ship_window_admission import (
    quarantine_hd_stale_reset_admissions,
    resolve_hd_ship_window_membership,
)
from backend.management_rinse_hd import (
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    build_rinse_hd_day,
)


EXPECTED_KEEP = {
    "7J0K1VM6WS",
    "2K7DSB13EK",
    "6KOTR69NWC",
    "DMOJ4730A9",
    "BLXFDA5KUV",
    "28WV1QS4F9",
}
EXPECTED_STALE = {
    "26LVAPM0EV",
    "3YGAWCWIO0",
    "AG482D8DDG",
    "CR3TLGH1PH",
    "DUBMZIT70D",
    "389CSDTX3L",
    "41M8L9YJEC",
    "6QISDZ90DV",
    "7AF1BTBFO1",
    "D3O1A980RG",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--ship-start", required=True)
    parser.add_argument("--ship-end", required=True)
    parser.add_argument("--view-date", default="", help="ET day for post-check (default ship-end)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-captured-untrusted",
        action="store_true",
        help="Use latest matching hang_dry run_rows even if run is anomalous (explicit repair only)",
    )
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        print("Pass --apply or --dry-run", file=sys.stderr)
        return 2

    ship_start = date.fromisoformat(args.ship_start)
    ship_end = date.fromisoformat(args.ship_end)
    view_day = date.fromisoformat(args.view_date) if args.view_date else ship_end

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        membership = resolve_hd_ship_window_membership(
            cur,
            args.org,
            ship_start=ship_start,
            ship_end=ship_end,
            require_trustworthy=not args.allow_captured_untrusted,
            union_recent_captures=bool(args.allow_captured_untrusted),
        )
        if not membership.get("ok") and args.allow_captured_untrusted:
            membership = resolve_hd_ship_window_membership(
                cur,
                args.org,
                ship_start=ship_start,
                ship_end=ship_end,
                require_trustworthy=False,
                union_recent_captures=True,
            )

        if not membership.get("ok"):
            print(json.dumps({"ok": False, "membership": membership}, default=str, indent=2))
            return 1

        valid = {str(b).upper() for b in (membership.get("bag_ids") or [])}
        cur.execute(
            """
            SELECT bag_id, operations_date_et, workflow_status, admitted_at, washed_at, folded_at
            FROM hd_day_bag_production
            WHERE organization_id = %s
              AND COALESCE(workflow_status, '') NOT IN (%s, 'excluded')
            ORDER BY bag_id
            """,
            (args.org, WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED),
        )
        open_rows = cur.fetchall() or []
        open_ids = {str(r["bag_id"]).upper() for r in open_rows}
        stale_open = sorted(open_ids - valid)
        keep_open = sorted(open_ids & valid)

        # Safety: never quarantine a bag that has current-window evidence
        for bid in stale_open:
            if bid in valid:
                raise RuntimeError(f"refusing to quarantine current-window bag {bid}")

        before = build_rinse_hd_day(cur, args.org, view_day, status="all")
        conn.rollback()

        plan = {
            "ok": True,
            "membership": membership,
            "open_before": sorted(open_ids),
            "keep": keep_open,
            "quarantine_candidates": stale_open,
            "expected_keep_match": keep_open == sorted(EXPECTED_KEEP & open_ids) or set(keep_open) == EXPECTED_KEEP,
            "expected_stale_subset": set(stale_open) <= EXPECTED_STALE or set(stale_open) == EXPECTED_STALE,
            "before_summary": before.get("summary"),
        }

        if args.dry_run or not args.apply:
            print(json.dumps({**plan, "dry_run": True}, default=str, indent=2))
            return 0

        q = quarantine_hd_stale_reset_admissions(
            cur,
            args.org,
            stale_open,
            reason="stale_ship_window_reset_admission",
        )
        conn.commit()

        after = build_rinse_hd_day(cur, args.org, view_day, status="all")
        conn.rollback()
        after_ids = sorted(
            str(o.get("bag_id")).upper()
            for o in (after.get("orders") or [])
            if o.get("bag_id")
        )
        print(
            json.dumps(
                {
                    **plan,
                    "applied": True,
                    "quarantine": q,
                    "after_ids": after_ids,
                    "after_summary": after.get("summary"),
                    "counts": {
                        "total": len(after_ids),
                        "pending_wash": (after.get("summary") or {}).get("pending_wash"),
                        "awaiting_fold": (after.get("summary") or {}).get("awaiting_fold"),
                        "awaiting_entry": (after.get("summary") or {}).get("awaiting_entry"),
                        "complete": (after.get("summary") or {}).get("complete"),
                    },
                },
                default=str,
                indent=2,
            )
        )
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
