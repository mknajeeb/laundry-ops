#!/usr/bin/env python3
"""Pre-apply safety checks for Option C upload batch purge."""

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

from backend.db import get_db
from backend.rinse_upload_batch_retention import (
    evaluate_batch_for_heavy_row_purge,
    get_latest_successful_imported_batch_id,
    plan_heavy_row_purge,
    retention_cutoff_batch_date,
    today_et,
)
from backend.ta_helpers import table_exists


def _fetch_batch(cursor, org_id: int, batch_id: int) -> dict | None:
    cursor.execute(
        """
        SELECT batch_id, batch_date, state, raw_rows_purged_at, purged_summary_json,
               organization_id
        FROM upload_batches
        WHERE organization_id = %s AND batch_id = %s
        LIMIT 1
        """,
        (int(org_id), int(batch_id)),
    )
    return cursor.fetchone()


def _attention_count(cursor, batch_id: int) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM upload_batch_rows
        WHERE upload_batch_id = %s AND row_status = 'NEEDS_ATTENTION'
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone()
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def _sample_bag_from_batch(cursor, batch_id: int) -> str | None:
    cursor.execute(
        """
        SELECT ticket_id FROM upload_batch_rows
        WHERE upload_batch_id = %s AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        LIMIT 1
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return str(row.get("ticket_id") if isinstance(row, dict) else row[0]).strip().upper()


def _persistent_scan_count(cursor, org_id: int, bag_id: str) -> int:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return 0
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
        """,
        (int(org_id), bag_id),
    )
    row = cursor.fetchone()
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def _registry_row(cursor, org_id: int, bag_id: str) -> dict | None:
    cursor.execute(
        """
        SELECT bag_id, completion_status, name_clean
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(org_id), bag_id),
    )
    return cursor.fetchone()


def _folding_row(cursor, org_id: int, bag_id: str) -> bool:
    if not table_exists(cursor, "rinse_folding_performance"):
        return False
    cursor.execute(
        """
        SELECT 1 FROM rinse_folding_performance
        WHERE organization_id = %s AND bag_id = %s LIMIT 1
        """,
        (int(org_id), bag_id),
    )
    return cursor.fetchone() is not None


def _staging_count(cursor, org_id: int, bag_id: str) -> int:
    if not table_exists(cursor, "orders_staging"):
        return 0
    sql = "SELECT COUNT(*) AS c FROM orders_staging WHERE ticket_id = %s"
    args: list = [bag_id]
    if table_exists(cursor, "orders_staging") and hasattr(
        __import__("backend.ta_helpers", fromlist=["table_has_column"]).table_has_column,
        "__call__",
    ):
        from backend.ta_helpers import table_has_column

        if table_has_column(cursor, "orders_staging", "organization_id"):
            sql += " AND organization_id = %s"
            args.append(int(org_id))
    cursor.execute(sql, tuple(args))
    row = cursor.fetchone()
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument("--batch-ids", type=int, nargs="+", required=True)
    parser.add_argument("--older-than-days", type=int, default=3)
    args = parser.parse_args()

    org = int(args.org)
    today = today_et()
    cutoff = retention_cutoff_batch_date(today, args.older_than_days)
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        latest_id = get_latest_successful_imported_batch_id(cursor, org)
        plan = plan_heavy_row_purge(cursor, org, older_than_days=args.older_than_days)
        plan_ids = {int(b["batch_id"]) for b in plan.get("batches_to_purge") or []}

        all_ok = True
        for bid in args.batch_ids:
            print(f"\n=== Batch #{bid} ===")
            batch = _fetch_batch(cursor, org, bid)
            if not batch:
                print("  FAIL: batch not found for org")
                all_ok = False
                continue

            verdict = evaluate_batch_for_heavy_row_purge(
                batch,
                organization_id=org,
                today=today,
                cutoff=cutoff,
                latest_success_batch_id=latest_id,
            )
            attn = _attention_count(cursor, bid)
            in_plan = bid in plan_ids

            checks = [
                (
                    "1. CONFIRMED or CLOSED",
                    str(batch.get("state") or "").upper() in ("CONFIRMED", "CLOSED"),
                    f"state={batch.get('state')}",
                ),
                (
                    "2. no NEEDS_ATTENTION",
                    attn == 0,
                    f"attention_rows={attn}",
                ),
                (
                    "3. not today",
                    _parse_bd(batch.get("batch_date")) < today if batch.get("batch_date") else False,
                    f"batch_date={batch.get('batch_date')} today={today}",
                ),
                (
                    "4. outside 3-day window",
                    _parse_bd(batch.get("batch_date")) <= cutoff if batch.get("batch_date") else False,
                    f"cutoff={cutoff}",
                ),
                (
                    "5. not latest success sync",
                    latest_id is None or int(bid) != int(latest_id),
                    f"latest_success={latest_id}",
                ),
                (
                    "6. retention plan eligible",
                    verdict["eligible"] and in_plan,
                    f"eligible={verdict['eligible']} in_plan={in_plan} reasons={verdict.get('skip_reasons')}",
                ),
            ]

            sample_bag = _sample_bag_from_batch(cursor, bid)
            if sample_bag:
                pscan = _persistent_scan_count(cursor, org, sample_bag)
                reg = _registry_row(cursor, org, sample_bag)
                fold = _folding_row(cursor, org, sample_bag)
                stag = _staging_count(cursor, org, sample_bag)
                checks.extend(
                    [
                        (
                            "7. persistent scan events (sample bag)",
                            pscan > 0,
                            f"bag={sample_bag} rinse_bag_scan_events={pscan}",
                        ),
                        (
                            "8a. registry remains",
                            reg is not None,
                            f"bag={sample_bag} registry={reg.get('completion_status') if reg else None}",
                        ),
                        (
                            "8b. staging remains (sample)",
                            stag > 0 or reg is not None,
                            f"orders_staging rows={stag}",
                        ),
                        (
                            "8c. folding row if any (unchanged by purge)",
                            True,
                            f"has_folding={fold}",
                        ),
                    ]
                )
            else:
                checks.append(
                    (
                        "7–8. sample bag",
                        True,
                        "no portal rows left to sample (batch may be empty)",
                    )
                )

            for label, ok, detail in checks:
                mark = "PASS" if ok else "FAIL"
                print(f"  [{mark}] {label} — {detail}")
                if not ok:
                    all_ok = False

        print(f"\n=== Plan alignment (org {org}) ===")
        print(f"Today ET: {today}  Cutoff: {cutoff}  Latest success batch: {latest_id}")
        print(f"Plan purge set: {sorted(plan_ids)}")
        print(f"Requested: {args.batch_ids}")
        if set(args.batch_ids) != plan_ids:
            print("  WARN: requested IDs differ from current plan purge set")
        print(f"\nOverall: {'SAFE TO APPLY' if all_ok and set(args.batch_ids) <= plan_ids else 'NOT SAFE'}")
        return 0 if all_ok else 1
    finally:
        cursor.close()
        conn.close()


def _parse_bd(val):
    from datetime import date, datetime

    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    return date.fromisoformat(str(val)[:10])


if __name__ == "__main__":
    raise SystemExit(main())
