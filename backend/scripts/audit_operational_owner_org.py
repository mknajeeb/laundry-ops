#!/usr/bin/env python3
"""Phase 1: canonical operational owner audit for an organization (read-only report)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_ORG = 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit org operational rows vs canonical bag owner")
    parser.add_argument("--org", type=int, default=DEFAULT_ORG, help="Organization id (default: 3 VeeWash)")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Also upsert rinse_bag_operational_owner from evidence (no deletes)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON report path (default: data/operational_owner_audit_org{N}.json)",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.rinse_bag_operational_owner import (
        audit_org_operational_isolation,
        backfill_canonical_owners_from_audit,
        ensure_operational_owner_table,
    )

    org = int(args.org)
    out_path = Path(args.output or REPO / "data" / f"operational_owner_audit_org{org}.json")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    ensure_operational_owner_table(cursor)

    report: dict = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "phase": "1_audit",
        "organization_id": org,
    }
    report["audit"] = audit_org_operational_isolation(cursor, org)

    if args.backfill:
        backfill = backfill_canonical_owners_from_audit(cursor, org, dry_run=False)
        conn.commit()
        report["backfill"] = backfill
    else:
        report["backfill"] = backfill_canonical_owners_from_audit(cursor, org, dry_run=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    audit = report["audit"]
    print(f"Org {org} bags in operational tables: {audit['bag_ids_in_org_tables']}")
    print(f"Canonical owner matches org: {audit['canonical_owner_matches_org']}")
    print(f"Canonical owner mismatch (other org): {audit['canonical_owner_mismatch_count']}")
    print(f"No canonical evidence: {audit['no_canonical_evidence_count']}")
    print(f"Aggregate row counts (mismatched): {audit['aggregate_row_counts_for_mismatched']}")
    print(f"Report written: {out_path}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
