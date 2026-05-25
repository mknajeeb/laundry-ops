#!/usr/bin/env python3
"""Dry-run folding exception rule changes for an org (no DB writes)."""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run folding exception rules recompute")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--from-batch", type=int, default=None)
    parser.add_argument("--to-batch", type=int, default=None)
    args = parser.parse_args()

    from backend.db import get_db
    from backend.rinse_bag_completion import COMPLETION_COMPLETED
    from backend.rinse_bag_folding import STATUS_CALCULATED, STATUS_EXCEPTION, WARNING_MULTIPLE_CLEAN_SCANS
    from backend.rinse_bag_registry import fetch_persistent_scan_events_for_bag, get_registry_row
    from backend.rinse_folding_exception_rules import get_folding_exception_rules_typed
    from backend.rinse_bag_folding import evaluate_folding_performance_for_bag
    from backend.rinse_folding_registry import get_folding_performance_row, ensure_rinse_folding_tables

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        org = int(args.org)
        ensure_rinse_folding_tables(cursor)
        rules = get_folding_exception_rules_typed(cursor, org)

        sql = """
            SELECT bag_id FROM rinse_bag_registry
            WHERE organization_id = %s AND completion_status = %s
        """
        sql_args: list = [org, COMPLETION_COMPLETED]
        if args.from_batch is not None:
            sql += " AND last_upload_batch_id >= %s"
            sql_args.append(int(args.from_batch))
        if args.to_batch is not None:
            sql += " AND last_upload_batch_id <= %s"
            sql_args.append(int(args.to_batch))
        cursor.execute(sql, tuple(sql_args))
        bags = [r["bag_id"] for r in cursor.fetchall() or [] if r.get("bag_id")]

        to_exception = []
        stay_warning = []
        unchanged = []
        other = []

        for bid in bags:
            reg = get_registry_row(cursor, org, bid)
            if not reg:
                continue
            existing = get_folding_performance_row(cursor, org, bid)
            events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
            new = evaluate_folding_performance_for_bag(events, registry_row=reg, rules=rules)
            old_st = (existing or {}).get("status")
            old_code = (existing or {}).get("exception_code")
            new_st = new.status
            new_code = new.exception_code
            if (old_st, old_code) == (new_st, new_code):
                unchanged.append(bid)
            elif old_st == STATUS_CALCULATED and new_st == STATUS_EXCEPTION:
                to_exception.append({"bag_id": bid, "old_code": old_code, "new_code": new_code})
            elif new_code == WARNING_MULTIPLE_CLEAN_SCANS and new_st == STATUS_CALCULATED:
                stay_warning.append({"bag_id": bid, "code": new_code})
            else:
                other.append(
                    {
                        "bag_id": bid,
                        "before": f"{old_st}/{old_code}",
                        "after": f"{new_st}/{new_code}",
                    }
                )

        print(f"Org {org} — bags scanned: {len(bags)}")
        print(f"Rules: min={rules.min_duration_minutes}m max={rules.max_duration_minutes}m")
        print(f"  CALCULATED → EXCEPTION: {len(to_exception)}")
        for row in to_exception[:25]:
            print(f"    {row['bag_id']}: {row['old_code']} -> {row['new_code']}")
        if len(to_exception) > 25:
            print(f"    ... +{len(to_exception) - 25} more")
        print(f"  Warning-only (MULTIPLE_CLEAN_SCANS etc.): {len(stay_warning)}")
        print(f"  Unchanged: {len(unchanged)}")
        print(f"  Other changes: {len(other)}")
        for row in other[:15]:
            print(f"    {row['bag_id']}: {row['before']} -> {row['after']}")
        print("Dry-run only — no rows updated.")
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
