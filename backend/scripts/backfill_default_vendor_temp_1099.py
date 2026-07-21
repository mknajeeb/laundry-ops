"""Seed the default staffing vendor and assign it to all temp / 1099 workers.

Safe + idempotent. Only sets payroll_profiles.default_vendor_id where it is NULL —
never overrides an explicit assignment. Touches no wages, taxes, or amounts.

Usage:
    python -m backend.scripts.backfill_default_vendor_temp_1099 --org 3 [--apply]

Without --apply this is a dry run.
"""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

load_dotenv(".env")

from backend.db import get_db
from backend.payroll_vendors import ensure_default_vendor, ensure_payroll_vendor_tables


def worker_ids_for_temp_1099(conn, organization_id: int) -> list[int]:
    """Distinct users who appear on temp / 1099 payout batch lines."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT DISTINCT pbl.user_id
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pb.worker_category IN ('temp', 'contractor_1099')
          AND pbl.user_id IS NOT NULL
        """,
        (int(organization_id),),
    )
    return [int(r["user_id"]) for r in c.fetchall() or []]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_db()
    ensure_payroll_vendor_tables(conn.cursor())
    vendor = ensure_default_vendor(conn, args.org)
    print(f"Default vendor: {vendor}")

    user_ids = worker_ids_for_temp_1099(conn, args.org)
    print(f"Temp/1099 workers found: {len(user_ids)}")

    c = conn.cursor(dictionary=True)
    to_set = []
    for uid in user_ids:
        c.execute(
            "SELECT user_id, default_vendor_id FROM payroll_profiles WHERE user_id=%s",
            (uid,),
        )
        row = c.fetchone()
        if not row:
            print(f"  user {uid}: no payroll_profiles row — skipped")
            continue
        if row.get("default_vendor_id") is None:
            to_set.append(uid)

    print(f"Would set default_vendor_id={vendor['id']} for {len(to_set)} workers: {to_set}")

    if args.apply and to_set:
        upd = conn.cursor()
        upd.executemany(
            "UPDATE payroll_profiles SET default_vendor_id=%s WHERE user_id=%s AND default_vendor_id IS NULL",
            [(int(vendor["id"]), uid) for uid in to_set],
        )
        conn.commit()
        print(f"APPLIED: {upd.rowcount} workers updated.")
    elif not args.apply:
        print("DRY RUN — re-run with --apply to persist.")

    out = {
        "org": args.org,
        "vendor": vendor,
        "temp_1099_workers": user_ids,
        "assigned": to_set if args.apply else [],
        "applied": bool(args.apply),
    }
    print(json.dumps(out, default=str))
    conn.close()


if __name__ == "__main__":
    main()
