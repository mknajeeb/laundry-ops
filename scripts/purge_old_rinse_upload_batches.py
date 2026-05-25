#!/usr/bin/env python3
"""
Purge heavy Rinse upload batch child rows (Option C retention).

Keeps upload_batches headers and rinse_scrape_runs summary rows.
Deletes upload_batch_rows and upload_batch_scan_events when safe.

Usage:
  python scripts/purge_old_rinse_upload_batches.py --org 3 --older-than-days 3 --dry-run
  python scripts/purge_old_rinse_upload_batches.py --org 3 --older-than-days 3 --apply
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
from backend.rinse_upload_batch_retention import (  # noqa: E402
    apply_heavy_row_purge,
    default_retention_days,
    plan_heavy_row_purge,
)


def _print_plan(plan: dict) -> None:
    print("=== Rinse upload batch retention (Option C) ===")
    print(f"Organization ID: {plan.get('organization_id')}")
    print(f"Retention days: {plan.get('retention_days')}")
    print(f"Today (America/New_York): {plan.get('today_et')}")
    print(f"Cutoff batch_date (purge on/before): {plan.get('cutoff_batch_date')}")
    print(f"Latest successful sync batch ID (protected): {plan.get('latest_success_batch_id')}")
    print()

    totals = plan.get("totals") or {}
    print("--- Totals to purge ---")
    print(f"  Batches: {totals.get('batches', 0)}")
    print(f"  upload_batch_rows: {totals.get('upload_batch_rows', 0)}")
    print(f"  upload_batch_scan_events: {totals.get('upload_batch_scan_events', 0)}")
    print()

    print("--- Batches to purge ---")
    batches = plan.get("batches_to_purge") or []
    if not batches:
        print("  (none)")
    for b in batches:
        print(
            f"  #{b.get('batch_id')} date={b.get('batch_date')} state={b.get('state')} "
            f"rows={b.get('upload_batch_rows')} scan_events={b.get('upload_batch_scan_events')}"
        )
    print()

    print("--- Skipped batches ---")
    skipped = plan.get("skipped_batches") or []
    if not skipped:
        print("  (none)")
    for b in skipped[:25]:
        reasons = "; ".join(b.get("skip_reasons") or []) or "—"
        print(
            f"  #{b.get('batch_id')} date={b.get('batch_date')} state={b.get('state')} — {reasons}"
        )
    if len(skipped) > 25:
        print(f"  ... +{len(skipped) - 25} more")
    print()

    scrape = plan.get("scrape_runs") or {}
    print("--- Scrape run rows (retain summary) ---")
    retain = scrape.get("retain") or []
    if not retain:
        print("  (none linked to purge set)")
    for r in retain:
        print(
            f"  run #{r.get('run_id')} batch={r.get('imported_batch_id')} "
            f"status={r.get('status')} started={r.get('started_at')}"
        )
    trim = scrape.get("trim_heavy_fields") or []
    if trim:
        print("--- Scrape runs: trim heavy result_json on apply ---")
        for r in trim:
            print(f"  run #{r.get('run_id')} batch={r.get('imported_batch_id')}")
    print()

    print("--- Tables touched on apply ---")
    for t in plan.get("tables_touched_on_apply") or []:
        print(f"  {t}")
    print()

    print("--- Tables never touched ---")
    for t in plan.get("tables_never_touched") or []:
        print(f"  {t}")
    print()

    warnings = plan.get("warnings") or []
    if warnings:
        print("--- Warnings ---")
        for w in warnings:
            print(f"  ! {w}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purge heavy Rinse upload batch rows (Option C — keep headers)"
    )
    parser.add_argument("--org", type=int, required=True, help="organization_id")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help=f"Retention window (default env RINSE_UPLOAD_BATCH_RETENTION_DAYS or {default_retention_days()})",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Plan only; no deletes")
    mode.add_argument("--apply", action="store_true", help="Execute purge")
    args = parser.parse_args()

    retention = args.older_than_days if args.older_than_days is not None else default_retention_days()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        plan = plan_heavy_row_purge(
            cursor, args.org, older_than_days=retention
        )
        plan["dry_run"] = args.dry_run
        _print_plan(plan)

        if args.dry_run:
            print("DRY RUN — no changes made.")
            print(json.dumps(plan, indent=2, default=str))
            return 0

        if not plan.get("batches_to_purge"):
            print("APPLY — nothing eligible; no changes made.")
            return 0

        applied = apply_heavy_row_purge(cursor, args.org, plan)
        conn.commit()
        print("APPLY — completed:")
        print(json.dumps(applied, indent=2, default=str))
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
