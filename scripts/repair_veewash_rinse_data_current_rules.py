#!/usr/bin/env python3
"""
VeeWash (org 3) production data repair for current Rinse rules.

Dry-run (default):
  python scripts/repair_veewash_rinse_data_current_rules.py --org 3 --from-batch 120 --to-batch latest --dry-run

Apply (after reviewing dry-run JSON):
  python scripts/repair_veewash_rinse_data_current_rules.py --org 3 --from-batch 120 --to-batch latest --apply

Idempotent and tenant-scoped. Does not touch other organizations unless --org is set explicitly.
"""

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

from backend.db import get_db  # noqa: E402
from backend.repair_veewash_rinse_current_rules import (  # noqa: E402
    DEFAULT_ORG_ID,
    apply_repair_plan,
    build_repair_plan,
    plan_to_json,
)
from backend.repair_latest_upload_batch import resolve_organization_id  # noqa: E402


def _print_human_summary(plan: dict) -> None:
    c = plan.get("counters") or {}
    print(f"\n=== VeeWash Rinse repair plan (org {plan.get('organization_id')}) ===")
    print(f"Batches: {plan.get('from_batch')} .. {plan.get('to_batch')} ({len(plan.get('batch_ids') or [])} batches)")
    print("\n--- Counts (would change on --apply) ---")
    for key, val in sorted(c.items()):
        print(f"  {key}: {val}")
    print("\n--- Summary by issue type ---")
    for k, v in (plan.get("summary_by_issue_type") or {}).items():
        print(f"  {k}: {v}")
    print("\n--- Summary by batch ---")
    for row in plan.get("summary_by_batch") or []:
        print(
            f"  batch {row.get('batch_id')} state={row.get('state')} "
            f"ok→updated={row.get('ok_to_updated')} wrong_reject={row.get('wrong_reject')} "
            f"wrong_accept={row.get('wrong_accept')} scrape_linked={row.get('scrape_linked')}"
        )
    bags = plan.get("bag_ids_to_change") or []
    print(f"\n--- Bag IDs to change ({len(bags)}) ---")
    if bags:
        print("  " + ", ".join(bags[:40]) + (" ..." if len(bags) > 40 else ""))
    manual = plan.get("manual_review_bags") or []
    if manual:
        print(f"\n--- Manual review bags ({len(manual)}) ---")
        print("  " + ", ".join(manual[:30]))
    folding = plan.get("folding_change_detail") or []
    if folding:
        print(f"\n--- Folding alignment ({len(folding)} bags) ---")
        for row in folding:
            bid = row.get("bag_id") or "?"
            if row.get("action") == "create":
                print(f"  {bid}: (none) → {row.get('to_status')}/{row.get('to_code') or '—'}")
            else:
                print(
                    f"  {bid}: {row.get('from_status')}/{row.get('from_code') or '—'} "
                    f"→ {row.get('to_status')}/{row.get('to_code') or '—'}"
                )
    print(f"\nProduction safe to apply (no manual-review blockers): {plan.get('production_safe_to_apply')}")
    for note in plan.get("notes") or []:
        print(f"  • {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=DEFAULT_ORG_ID, help="organization_id (default 3)")
    parser.add_argument("--from-batch", type=int, default=120, dest="from_batch")
    parser.add_argument(
        "--to-batch",
        default="latest",
        help="batch id or 'latest' (default latest)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only; no writes (default if --apply omitted)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply repairs (commits transaction)")
    parser.add_argument(
        "--folding-only",
        action="store_true",
        help="With --apply: recompute folding only for bags in folding_change_detail",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON plan")
    parser.add_argument(
        "--allow-absence-reversal",
        action="store_true",
        help="Reserved: portal absence reversals still require manual review",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    if args.dry_run:
        dry_run = True

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        org_id, org_meta = resolve_organization_id(cursor, organization_id=args.org)
        if org_id != args.org and not args.json:
            print(f"Resolved org {org_id} (requested {args.org})", file=sys.stderr)
        if not args.json:
            print(
                f"Tenant: id={org_id} slug={org_meta.get('slug')!r} "
                f"name={org_meta.get('display_name')!r}"
            )

        to_batch: str | int = args.to_batch
        if str(to_batch).strip().lower() != "latest":
            try:
                to_batch = int(to_batch)
            except ValueError:
                parser.error("--to-batch must be an integer or 'latest'")

        plan = build_repair_plan(
            cursor,
            organization_id=org_id,
            from_batch=args.from_batch,
            to_batch=to_batch,
        )

        if args.json:
            print(plan_to_json(plan))
        else:
            _print_human_summary(plan)
        if dry_run and not args.json:
            print("\n[dry-run] No database changes. Re-run with --apply after approval.")

        if not dry_run:
            if not plan.get("production_safe_to_apply"):
                print(
                    "\nWARNING: manual-review items present. Proceeding because --apply was set.",
                    file=sys.stderr,
                )
            applied = apply_repair_plan(
                cursor,
                plan,
                allow_absence_reversal=args.allow_absence_reversal,
                folding_only=args.folding_only,
            )
            conn.commit()
            print("\n=== Applied ===")
            print(plan_to_json(applied))

        return 0
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
