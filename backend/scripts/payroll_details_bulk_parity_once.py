#!/usr/bin/env python3
"""One-shot parity + timing for payout batch details bulk enrich.

Compares enrich_batch_payout_details(bulk=True) vs bulk=False on the same
core batch rows. Does not write. Does not touch ACA/scraper.

Usage:
  python3 backend/scripts/payroll_details_bulk_parity_once.py [--org 3] [--limit 3]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

env_path = Path("/Users/kamisb./laundry_app/.env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


LINE_KEYS = (
    "id",
    "user_id",
    "employee_id",
    "approved_hours",
    "rate",
    "ot_hours",
    "ot_rate",
    "gross_amount",
    "gross_wages",
    "total_amount",
    "federal_withholding",
    "state_withholding",
    "city_withholding",
    "social_security_withholding",
    "medicare_withholding",
    "additional_medicare_withholding",
    "total_employee_taxes",
    "net_pay",
    "net_paid",
    "tax_withheld",
    "payment_status",
    "payment_recorded",
    "payout_details_finalized",
)


def _line_fp(ln: dict) -> dict:
    doc = ln.get("document") or {}
    out = {k: ln.get(k) for k in LINE_KEYS}
    out["document"] = {
        "paystub_available": doc.get("paystub_available"),
        "vendor_receipt_available": doc.get("vendor_receipt_available"),
        "vendor_receipt_preview_available": doc.get("vendor_receipt_preview_available"),
        "effective_type": doc.get("effective_type"),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", type=int, default=int(os.environ.get("ORG_ID") or 3))
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--batch-id", type=int, default=0)
    args = ap.parse_args()

    from backend.db import get_db
    from backend.payroll_operations import _fetch_payout_batch_core
    from backend.payroll_payout_details import enrich_batch_payout_details

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if args.batch_id:
            batch_ids = [int(args.batch_id)]
        else:
            c.execute(
                """
                SELECT id FROM payout_batches
                WHERE organization_id=%s
                  AND status IN (
                    'sent_to_accountant','accountant_reviewed',
                    'approved_for_payment','paid','closed'
                  )
                ORDER BY pay_period_end DESC, id DESC
                LIMIT %s
                """,
                (args.org, args.limit),
            )
            batch_ids = [int(r["id"]) for r in c.fetchall() or []]

        report = {"org": args.org, "batches": []}
        all_ok = True
        for bid in batch_ids:
            core = _fetch_payout_batch_core(conn, args.org, bid)
            if not core:
                continue
            t0 = time.perf_counter()
            legacy = enrich_batch_payout_details(
                conn, args.org, copy.deepcopy(core), bulk=False
            )
            t_legacy = time.perf_counter() - t0
            t1 = time.perf_counter()
            modern = enrich_batch_payout_details(
                conn, args.org, copy.deepcopy(core), bulk=True
            )
            t_modern = time.perf_counter() - t1

            leg_lines = {_line_fp(ln)["id"]: _line_fp(ln) for ln in legacy.get("lines") or []}
            mod_lines = {_line_fp(ln)["id"]: _line_fp(ln) for ln in modern.get("lines") or []}
            mismatches = []
            for lid, a in leg_lines.items():
                b = mod_lines.get(lid)
                if b != a:
                    mismatches.append({"line_id": lid, "legacy": a, "modern": b})
            extra = sorted(set(mod_lines) - set(leg_lines))
            missing = sorted(set(leg_lines) - set(mod_lines))
            ok = not mismatches and not extra and not missing
            all_ok = all_ok and ok
            report["batches"].append(
                {
                    "batch_id": bid,
                    "line_count": len(leg_lines),
                    "parity_ok": ok,
                    "legacy_s": round(t_legacy, 3),
                    "modern_s": round(t_modern, 3),
                    "mismatch_count": len(mismatches),
                    "extra_line_ids": extra,
                    "missing_line_ids": missing,
                    "mismatches": mismatches[:3],
                }
            )
            print(
                f"batch={bid} lines={len(leg_lines)} parity={'OK' if ok else 'FAIL'} "
                f"legacy={t_legacy:.2f}s modern={t_modern:.2f}s"
            )

        report["all_parity_ok"] = all_ok
        out = ROOT / "backups" / "payroll_details_bulk_parity_once.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"wrote {out}")
        return 0 if all_ok else 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
