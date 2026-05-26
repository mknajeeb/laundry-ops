#!/usr/bin/env python3
"""
Apply tenant folding exception rules to stored rinse_folding_performance rows.

Reads rules from system_settings, re-evaluates from scan events, upserts performance
only (no registry/staging/upload/scan timestamp writes).

Usage:
  python3 scripts/apply_folding_exception_rules.py --org 3
  python3 scripts/apply_folding_exception_rules.py --org 3 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import get_db  # noqa: E402
from backend.rinse_bag_completion import COMPLETION_COMPLETED  # noqa: E402
from backend.rinse_bag_registry import ensure_rinse_bag_registry_table, list_registry_rows  # noqa: E402
from backend.rinse_folding_exception_rules import get_folding_exception_rules  # noqa: E402
from backend.rinse_folding_registry import (  # noqa: E402
    ensure_rinse_folding_tables,
    recompute_folding_performance_for_bags,
    summarize_recompute_results,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply folding exception rules (recompute rinse_folding_performance only)"
    )
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print rules and bag count only; no writes",
    )
    args = parser.parse_args()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        org = int(args.org)
        ensure_rinse_bag_registry_table(cursor)
        ensure_rinse_folding_tables(cursor)
        rules = get_folding_exception_rules(cursor, org)
        rows = list_registry_rows(
            cursor, org, status=COMPLETION_COMPLETED, limit=10000, offset=0
        )
        bag_ids = [str(r["bag_id"]) for r in rows if r.get("bag_id")]

        print(f"Org {org} — exception rules:")
        print(f"  min_duration_minutes={rules.get('min_duration_minutes')}")
        print(f"  max_duration_minutes={rules.get('max_duration_minutes')}")
        print(f"  multiple_clean_scans_as_exception={rules.get('multiple_clean_scans_as_exception')}")
        print(f"Completed bags to recompute: {len(bag_ids)}")

        if args.dry_run:
            print("Dry-run — no rows updated.")
            return 0

        payload = recompute_folding_performance_for_bags(
            cursor, org, bag_ids, source_recompute_kind="exception_rules_apply"
        )
        conn.commit()
        summary = payload.get("summary") or summarize_recompute_results(
            payload.get("bags") or []
        )
        print(
            f"Applied: processed={summary.get('processed', payload.get('bags_processed', 0))} "
            f"calculated={summary.get('calculated', 0)} "
            f"exceptions={summary.get('exceptions', 0)} "
            f"skipped={payload.get('bags_skipped', 0)}"
        )
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
