#!/usr/bin/env python3
"""Recover Shift Monitor data when portal ACA gate blocks but scan events stalled.

Runs targeted pending scan refresh for today's ET workload using direct bag lookup.
Safe to run multiple times; does not create portal upload batches.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG = 3


def _today_et() -> date:
    from backend.rinse_scheduled_scrape import _today_et

    return _today_et()


def main() -> None:
    selected = _today_et()
    if len(sys.argv) > 1:
        selected = date.fromisoformat(sys.argv[1])

    from backend.db import get_db
    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_off_portal_scan_refresh import (
        get_latest_successful_crawl_batch_id,
        refresh_pending_workload_scans_via_direct_lookup,
    )
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    baseline_ctx = build_baseline_context(
        cursor, ORG, get_shift_monitor_baseline(cursor, ORG)
    )
    before = build_at_vendor_module(
        cursor, ORG, selected_date_et=selected, baseline_ctx=baseline_ctx
    )
    before_completed = before.get("completed") or before.get("completed_today_count") or 0

    crawl_batch_id = get_latest_successful_crawl_batch_id(cursor, ORG)
    print(f"Recovering org {ORG} for {selected.isoformat()} (crawl batch {crawl_batch_id})")
    print(f"Before: completed_today={before_completed} pending={before.get('pending')}")

    detail = refresh_pending_workload_scans_via_direct_lookup(
        cursor,
        ORG,
        upload_batch_id=crawl_batch_id,
        selected_date_et=selected,
        baseline_ctx=baseline_ctx,
        dry_run=False,
        rush_only=False,
        log_fn=lambda msg: print(msg),
    )
    conn.commit()

    after = build_at_vendor_module(
        cursor, ORG, selected_date_et=selected, baseline_ctx=baseline_ctx
    )
    after_completed = after.get("completed") or after.get("completed_today_count") or 0
    emp_count = len((after.get("employee_completed_bags_today") or {}).get("employees") or [])

    print("\nTargeted refresh result:")
    for key in (
        "bag_ids_requested",
        "bags_processed",
        "events_inserted",
        "lookup_failed",
    ):
        print(f"  {key}: {detail.get(key)}")

    print(f"\nAfter: completed_today={after_completed} pending={after.get('pending')}")
    print(f"Employee productivity rows: {emp_count}")


if __name__ == "__main__":
    main()
