"""Force temp / 1099 settlement checkbox defaults on all payout lines.

Sets:
  settlement.paid_full_gross_without_withholding = True
  show_tax_payment_section = False

Includes finalized / paid batches. Recomputes settlement math so amount_paid
and amount_withheld stay consistent with paid-full-gross.

Usage (from repo root):
  python -m backend.scripts.backfill_vendor_receipt_settlement_defaults --org 3
  python -m backend.scripts.backfill_vendor_receipt_settlement_defaults --org 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(".env")

from backend.db import get_db
from backend.payroll_payout_details import backfill_vendor_receipt_settlement_defaults


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--batch-id",
        type=int,
        action="append",
        dest="batch_ids",
        help="Optional batch id filter (repeatable)",
    )
    args = parser.parse_args()

    conn = get_db()
    try:
        report = backfill_vendor_receipt_settlement_defaults(
            conn,
            args.org,
            apply=bool(args.apply),
            batch_ids=args.batch_ids,
        )
    finally:
        conn.close()

    summary = {
        "organization_id": report["organization_id"],
        "apply": report["apply"],
        "scanned": report["scanned"],
        "changed": report["changed"],
        "unchanged": report["unchanged"],
    }
    print(json.dumps(summary, indent=2))
    if not args.apply:
        print("DRY RUN — re-run with --apply to persist.", file=sys.stderr)
    changed_lines = [ln for ln in report["lines"] if ln.get("changed")]
    if changed_lines:
        print(json.dumps({"sample_changed": changed_lines[:20]}, indent=2, default=str))


if __name__ == "__main__":
    main()
