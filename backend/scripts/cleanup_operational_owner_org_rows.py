#!/usr/bin/env python3
"""
Phase 4: report (and optional execute) cleanup of org rows for bags not canonically owned by that org.

Requires backup before --execute. Does not touch workload/completion rules.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_ORG = 3

CLEANUP_TABLES = [
    ("rinse_bag_scan_events", "bag_id", "organization_id"),
    ("upload_batch_scan_events", "bag_id", "organization_id"),
    ("rinse_bag_registry", "bag_id", "organization_id"),
    ("orders_staging", "ticket_id", "organization_id"),
    ("rinse_cleaner_ticket_presence", "bag_id", "organization_id"),
    ("rinse_cleaner_ticket_presence_run_rows", "bag_id", "organization_id"),
    ("rinse_folding_performance", "bag_id", "organization_id"),
]


def _export_bag_rows(cursor, org: int, bag_id: str) -> dict[str, list[dict[str, Any]]]:
    from backend.ta_helpers import table_exists, table_has_column

    out: dict[str, list[dict[str, Any]]] = {}
    bid = bag_id.upper().strip()
    for table, id_col, org_col in CLEANUP_TABLES:
        if not table_exists(cursor, table):
            continue
        if table == "orders_staging" and not table_has_column(cursor, table, "ticket_id"):
            continue
        if not table_has_column(cursor, table, org_col):
            continue
        cursor.execute(
            f"SELECT * FROM {table} WHERE {org_col} = %s AND UPPER(TRIM({id_col})) = %s",
            (org, bid),
        )
        rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
        if rows:
            out[table] = rows
    return out


def build_cleanup_plan(cursor, organization_id: int) -> dict[str, Any]:
    from backend.rinse_bag_operational_owner import (
        audit_org_operational_isolation,
        ensure_operational_owner_table,
    )

    ensure_operational_owner_table(cursor)
    audit = audit_org_operational_isolation(cursor, organization_id)
    org = int(organization_id)

    to_clean: list[dict[str, Any]] = []
    for entry in audit.get("mismatched_bags") or []:
        owner_org = entry.get("canonical_owner_organization_id")
        if owner_org is None:
            continue
        if int(owner_org) == org:
            continue
        bid = str(entry.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        row_counts = entry.get("org_row_counts") or {}
        to_clean.append(
            {
                "bag_id": bid,
                "canonical_owner_organization_id": int(owner_org),
                "owner_rinse_vendor": entry.get("owner_rinse_vendor"),
                "assignment_source": entry.get("assignment_source"),
                "assigned_at": entry.get("assigned_at"),
                "rows_to_delete_by_table": row_counts,
                "total_rows": sum(int(v) for v in row_counts.values()),
            }
        )

    return {
        "organization_id": org,
        "phase": "4_cleanup_plan",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "bags_to_clean": to_clean,
        "bag_count": len(to_clean),
        "aggregate_rows_to_delete": audit.get("aggregate_row_counts_for_mismatched") or {},
        "affected_tables": [t[0] for t in CLEANUP_TABLES],
        "rollback_plan": {
            "step_1": "Restore from backup archive written before --execute (see backup_path in report).",
            "step_2": "Re-run audit_operational_owner_org.py --org N to verify zero mismatches.",
            "step_3": "If partial restore needed, use per-bag snapshots in backup JSON (tables.* rows).",
            "note": "rinse_bag_operational_owner rows are NOT deleted by this script.",
        },
    }


def execute_cleanup(cursor, organization_id: int, bag_ids: list[str], backup: dict[str, Any]) -> dict[str, int]:
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    deleted: dict[str, int] = {}

    for bid in bag_ids:
        backup["bags"][bid] = _export_bag_rows(cursor, org, bid)

    for table, id_col, org_col in CLEANUP_TABLES:
        if not table_exists(cursor, table):
            continue
        if table == "orders_staging" and not table_has_column(cursor, table, "ticket_id"):
            continue
        if not table_has_column(cursor, table, org_col):
            continue
        ph = ",".join(["%s"] * len(bag_ids))
        cursor.execute(
            f"DELETE FROM {table} WHERE {org_col} = %s AND UPPER(TRIM({id_col})) IN ({ph})",
            (org, *bag_ids),
        )
        deleted[table] = cursor.rowcount or 0

    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 operational owner cleanup plan / execute")
    parser.add_argument("--org", type=int, default=DEFAULT_ORG)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete mismatched org rows after writing backup archive",
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        default=None,
        help="Directory for pre-delete JSON backup (required with --execute)",
    )
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    from backend.db import get_db

    org = int(args.org)
    out_path = Path(args.output or REPO / "data" / f"operational_owner_cleanup_org{org}.json")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    plan = build_cleanup_plan(cursor, org)

    if args.execute:
        if not args.backup_dir:
            print("ERROR: --backup-dir is required with --execute")
            sys.exit(1)
        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"operational_owner_cleanup_org{org}_{stamp}.json"
        backup: dict[str, Any] = {
            "organization_id": org,
            "created_at_utc": datetime.utcnow().isoformat() + "Z",
            "bags": {},
        }
        bag_ids = [b["bag_id"] for b in plan.get("bags_to_clean") or []]
        deleted = execute_cleanup(cursor, org, bag_ids, backup)
        backup_path.write_text(json.dumps(backup, indent=2, default=str), encoding="utf-8")
        conn.commit()
        plan["executed"] = True
        plan["backup_path"] = str(backup_path)
        plan["deleted_row_counts"] = deleted
    else:
        plan["executed"] = False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")

    print(f"Bags to clean: {plan['bag_count']}")
    print(f"Aggregate rows to delete: {plan['aggregate_rows_to_delete']}")
    print(f"Plan written: {out_path}")
    if plan.get("executed"):
        print(f"Backup: {plan.get('backup_path')}")
        print(f"Deleted: {plan.get('deleted_row_counts')}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
