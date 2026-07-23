#!/usr/bin/env python3
"""
Backfill portal weight enrichment onto rinse_bag_scan_events weight-entry rows.

Recovers missing pre-clean (earlier) weight-entry weights from historical
portal observations without ever attaching the current/final portal value to
an earlier weight-entry event. See backend/rinse_scan_weight_enrichment.py.

Usage:
    python -m backend.scripts.backfill_scan_weight_enrichment --org 3 --dry-run
    python -m backend.scripts.backfill_scan_weight_enrichment --org 3 --apply
    python -m backend.scripts.backfill_scan_weight_enrichment --org 3 --bag 42EN4J3VRB --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_ORG = 3
DOCUMENTED_BAG = "42EN4J3VRB"


def _bag_ids_with_weight_entries(
    cursor, organization_id: int, *, bag_id: str | None, on_date: date | None
) -> list[str]:
    from backend.rinse_bag_completion import normalize_bag_id

    if bag_id:
        nb = normalize_bag_id(bag_id)
        return [nb] if nb else []

    org = int(organization_id)
    args: list[Any] = [org]
    date_clause = ""
    if on_date is not None:
        date_clause = " AND DATE(scanned_at_parsed) = %s"
        args.append(on_date)
    cursor.execute(
        f"""
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND LOWER(REPLACE(TRIM(purpose), ' ', '-')) = 'weight-entry'
          {date_clause}
        ORDER BY bag_id
        """,
        tuple(args),
    )
    out: list[str] = []
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id") if isinstance(row, dict) else row[0])
        if bid:
            out.append(bid)
    return sorted(set(out))


def _snapshot_bag_events(cursor, organization_id: int, bag_id: str) -> list[dict[str, Any]]:
    from backend.rinse_scan_purpose import is_weight_entry_purpose
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

    cursor.execute(
        """
        SELECT id, scanned_at_parsed, purpose, weight_lbs
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        """,
        (int(organization_id), bag_id),
    )
    out = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or not is_weight_entry_purpose(row.get("purpose")):
            continue
        out.append(
            {
                "id": row.get("id"),
                "scanned_at_parsed": row.get("scanned_at_parsed"),
                "weight_lbs": normalize_scan_weight_lbs(row.get("weight_lbs")),
            }
        )
    return out


def run(
    conn,
    *,
    organization_id: int,
    bag_id: str | None,
    on_date: date | None,
    dry_run: bool,
) -> dict[str, Any]:
    from backend.rinse_scan_weight_enrichment import classify_and_backfill_bag

    cursor = conn.cursor(dictionary=True)
    bag_ids = _bag_ids_with_weight_entries(
        cursor, organization_id, bag_id=bag_id, on_date=on_date
    )

    documented_before = None
    if DOCUMENTED_BAG in bag_ids or bag_id == DOCUMENTED_BAG:
        documented_before = _snapshot_bag_events(cursor, organization_id, DOCUMENTED_BAG)

    outcome_counts: Counter[str] = Counter()
    per_bag: list[dict[str, Any]] = []
    for bid in bag_ids:
        result = classify_and_backfill_bag(cursor, organization_id, bid, dry_run=dry_run)
        for ev in result.get("events") or []:
            outcome_counts[str(ev.get("outcome"))] += 1
        per_bag.append(result)

    if not dry_run:
        conn.commit()

    documented_after = None
    if documented_before is not None:
        documented_after = _snapshot_bag_events(cursor, organization_id, DOCUMENTED_BAG)

    return {
        "organization_id": organization_id,
        "dry_run": dry_run,
        "bag_id_filter": bag_id,
        "date_filter": on_date.isoformat() if on_date else None,
        "bags_scanned": len(bag_ids),
        "outcome_counts": dict(outcome_counts),
        "manager_correction_required_bags": sum(
            1 for r in per_bag if r.get("manager_correction_required_count")
        ),
        "documented_bag": DOCUMENTED_BAG,
        "documented_bag_before": documented_before,
        "documented_bag_after": documented_after,
        "results": per_bag,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=DEFAULT_ORG)
    parser.add_argument("--bag", default=None, help="Restrict to a single bag id")
    parser.add_argument("--date", default=None, help="Restrict to weight-entry scans on this ET date (YYYY-MM-DD)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Classify only, no writes (default)")
    mode.add_argument("--apply", action="store_true", help="Perform writes")
    parser.add_argument(
        "--out",
        default=str(REPO / "data/backfill_scan_weight_enrichment_report.json"),
    )
    args = parser.parse_args()
    dry_run = not args.apply

    on_date = date.fromisoformat(args.date) if args.date else None

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    from backend.db import get_db

    conn = get_db()
    conn.autocommit = False
    try:
        report = run(
            conn,
            organization_id=args.org,
            bag_id=args.bag,
            on_date=on_date,
            dry_run=dry_run,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"organization_id={report['organization_id']} dry_run={report['dry_run']}")
    print(f"bags_scanned={report['bags_scanned']}")
    print("outcome_counts:")
    for outcome, count in sorted(report["outcome_counts"].items()):
        print(f"  {outcome}: {count}")
    print(f"manager_correction_required_bags={report['manager_correction_required_bags']}")
    print(f"\n{DOCUMENTED_BAG} before: {json.dumps(report['documented_bag_before'], default=str)}")
    print(f"{DOCUMENTED_BAG} after:  {json.dumps(report['documented_bag_after'], default=str)}")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
