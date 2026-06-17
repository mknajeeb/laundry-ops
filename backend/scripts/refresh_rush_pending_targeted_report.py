#!/usr/bin/env python3
"""Live targeted refresh report for Rush Pending bags (direct ?q=BAGID)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ORG = 3
OUT = REPO / "data" / "rush_pending_targeted_refresh_report.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rush Pending targeted refresh report (org 3)")
    p.add_argument("--date-et", help="Workload date YYYY-MM-DD (default: today ET)")
    p.add_argument("--dry-run", action="store_true", help="Classify only; do not import scans")
    return p.parse_args()


def main() -> int:
    from backend.db import get_db
    from backend.rinse_at_vendor_module import AV_RUSH, AV_STATUS_COMPLETED, AV_STATUS_PENDING, build_at_vendor_module
    from backend.rinse_off_portal_scan_refresh import (
        bag_in_portal_crawl_batch,
        get_latest_successful_crawl_batch_id,
        refresh_pending_workload_scans_via_direct_lookup,
        resolve_pending_not_in_latest_crawl_bag_ids,
    )
    from backend.rinse_scheduled_scrape import _today_et
    from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline

    args = _parse_args()
    selected = date.fromisoformat(args.date_et) if args.date_et else _today_et()
    conn = get_db()
    c = conn.cursor(dictionary=True)
    try:
        baseline = build_baseline_context(c, ORG, get_shift_monitor_baseline(c, ORG))
        av_before = build_at_vendor_module(c, ORG, selected_date_et=selected, baseline_ctx=baseline)
        rush_pending = [
            r for r in av_before["rows"]
            if r.get("rush_bucket") == AV_RUSH and r.get("at_vendor_status") == AV_STATUS_PENDING
        ]
        rows_before = {str(r["bag_id"]).upper(): r for r in rush_pending}
        batch_id = get_latest_successful_crawl_batch_id(c, ORG)
        targets, _, on_portal_map = resolve_pending_not_in_latest_crawl_bag_ids(
            c, ORG, selected_date_et=selected, baseline_ctx=baseline, rush_only=True, crawl_batch_id=batch_id
        )

        refresh = refresh_pending_workload_scans_via_direct_lookup(
            c,
            ORG,
            upload_batch_id=batch_id,
            selected_date_et=selected,
            baseline_ctx=baseline,
            bag_ids=targets,
            dry_run=bool(args.dry_run),
            rush_only=True,
        )
        if not args.dry_run:
            conn.commit()

        av_after = build_at_vendor_module(c, ORG, selected_date_et=selected, baseline_ctx=baseline)
        rows_after = {str(r["bag_id"]).upper(): r for r in av_after["rows"]}

        bag_table = []
        refresh_by_bag = {str(b["bag_id"]).upper(): b for b in refresh.get("bags") or []}
        for bid in targets:
            row = rows_before.get(bid) or {}
            rb = refresh_by_bag.get(bid) or {}
            after = rows_after.get(bid) or {}
            status_after = after.get("at_vendor_status") or rb.get("status_after")
            missing = int(rb.get("missing_scans_imported") or rb.get("missing_row_count") or 0)
            would_complete = bool(rb.get("would_complete"))
            if status_after == AV_STATUS_COMPLETED:
                disposition = "resolved_stale"
            elif missing > 0 and would_complete:
                disposition = "stale_would_complete"
            elif missing > 0:
                disposition = "stale_partial"
            else:
                disposition = "truly_pending"
            bag_table.append(
                {
                    "bag_id": bid,
                    "on_current_portal_crawl": bool(on_portal_map.get(bid)),
                    "in_latest_portal_crawl_batch": bool(
                        batch_id and bag_in_portal_crawl_batch(c, ORG, batch_id, bid)
                    ),
                    "direct_lookup_success": rb.get("direct_lookup_success", rb.get("lookup_ok")),
                    "missing_scans_imported": missing,
                    "status_before": rb.get("status_before") or row.get("at_vendor_status"),
                    "status_after": status_after,
                    "pending_why_before": row.get("pending_why_label") or rb.get("pending_why_before"),
                    "pending_why_after": after.get("pending_why_label") if status_after == AV_STATUS_PENDING else None,
                    "reason_still_pending": (
                        after.get("pending_why_label")
                        if status_after == AV_STATUS_PENDING
                        else None
                    ),
                    "would_complete_after_import": would_complete,
                    "disposition": disposition,
                    "lookup_error": rb.get("error"),
                }
            )

        report = {
            "selected_date_et": str(selected),
            "crawl_batch_id": batch_id,
            "rush_pending_count": len(rush_pending),
            "not_in_latest_crawl_rush_count": len(targets),
            "dry_run": bool(args.dry_run),
            "targeted_refresh": {
                "events_inserted": refresh.get("events_inserted"),
                "lookup_failed": refresh.get("lookup_failed"),
                "lookup_failed_bag_ids": refresh.get("lookup_failed_bag_ids"),
            },
            "bags": bag_table,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str))
        print(f"\nReport: {OUT}")
        return 0
    finally:
        c.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
