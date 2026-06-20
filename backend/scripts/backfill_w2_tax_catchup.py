"""
Backfill estimated taxes for W2-2026-002 through W2-2026-006 catch-up payroll.

Prior tax balances are stored for display only. Catch-up withholding defaults to $0;
managers must enter catch-up amounts manually in Payment & Details.

Usage (from repo root):
  python -m backend.scripts.backfill_w2_tax_catchup --org-id 3 --dry-run
  python -m backend.scripts.backfill_w2_tax_catchup --org-id 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.payroll_payout_details import (
    apply_settlement_math,
    build_estimated_payout_details_patch,
    ensure_payout_details_columns,
    infer_pay_frequency_from_batch,
    parse_line_payout_details,
    reconcile_tax_summary,
)

CATCHUP_BATCH_NAMES = (
    "W2-2026-002",
    "W2-2026-003",
    "W2-2026-004",
    "W2-2026-005",
)
CATCHUP_BATCH_NAME = "W2-2026-006"


def _prior_balance_by_user(conn, org_id: int, batch_names: tuple[str, ...]) -> dict[int, float]:
    c = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(batch_names))
    c.execute(
        f"""
        SELECT pbl.user_id, pbl.payout_details_json, pbl.gross_amount, pbl.total_amount
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pb.batch_name IN ({placeholders})
        """,
        (int(org_id), *batch_names),
    )
    balances: dict[int, float] = {}
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        details = parse_line_payout_details(row)
        tax_summary = details.get("tax_summary") or {}
        owed = float(tax_summary.get("tax_balance_owed") or 0)
        if owed <= 0:
            owed = float(details.get("settlement", {}).get("tax_balance_owed") or 0)
        balances[uid] = round(balances.get(uid, 0) + owed, 2)
    return balances


def backfill(org_id: int, *, apply: bool = False) -> dict:
    from backend.db import get_db

    conn = get_db()
    ensure_payout_details_columns(conn.cursor())

    prior_balances = _prior_balance_by_user(conn, org_id, CATCHUP_BATCH_NAMES)
    report: dict = {"prior_balances_from_db": prior_balances, "lines": []}

    c = conn.cursor(dictionary=True)
    all_names = list(CATCHUP_BATCH_NAMES) + [CATCHUP_BATCH_NAME]
    placeholders = ",".join(["%s"] * len(all_names))
    c.execute(
        f"""
        SELECT pb.id AS batch_id, pb.batch_name, pb.pay_period_start, pb.pay_period_end,
               pbl.id AS line_id, pbl.user_id,
               pbl.worker_name_snapshot, pbl.gross_amount, pbl.total_amount,
               pbl.payout_details_json
        FROM payout_batches pb
        JOIN payout_batch_lines pbl ON pbl.batch_id = pb.id
        WHERE pb.organization_id = %s AND pb.batch_name IN ({placeholders})
        ORDER BY pb.batch_name, pbl.id
        """,
        (int(org_id), *all_names),
    )
    rows = c.fetchall() or []
    updater = conn.cursor()
    running_balance: dict[int, float] = {}

    for row in rows:
        batch_name = str(row["batch_name"])
        gross = float(row.get("gross_amount") or row.get("total_amount") or 0)
        worker = str(row.get("worker_name_snapshot") or "")
        uid = int(row["user_id"])
        is_catchup = batch_name == CATCHUP_BATCH_NAME
        prior = running_balance.get(uid, 0.0) if is_catchup else 0.0
        batch_row = {
            "pay_period_start": row.get("pay_period_start"),
            "pay_period_end": row.get("pay_period_end"),
        }
        pay_freq = infer_pay_frequency_from_batch(batch_row)
        try:
            patch = build_estimated_payout_details_patch(
                conn,
                org_id,
                uid,
                gross,
                worker_name=worker,
                pay_period_start=row.get("pay_period_start"),
                pay_frequency=pay_freq,
            )
        except ValueError as exc:
            report.setdefault("errors", []).append(
                {
                    "batch_name": batch_name,
                    "line_id": row["line_id"],
                    "worker": worker,
                    "error": str(exc),
                }
            )
            continue

        patch.setdefault("settlement", {})
        patch.setdefault("payment", {})
        pay_default = str(batch_row.get("pay_period_end") or batch_row.get("pay_period_start") or "").strip()
        if pay_default and not str(patch["payment"].get("date") or "").strip():
            patch["payment"]["date"] = pay_default
        if is_catchup:
            patch["settlement"].update(
                {
                    "prior_unpaid_taxes": prior,
                    "catch_up_withholding": 0.0,
                    "paid_full_gross_without_withholding": False,
                }
            )
            patch["tax_summary"]["prior_tax_balance"] = prior
            merged = apply_settlement_math(patch, gross)
        else:
            patch["settlement"].update(
                {
                    "prior_unpaid_taxes": 0.0,
                    "catch_up_withholding": 0.0,
                    "paid_full_gross_without_withholding": True,
                }
            )
            patch["payment"]["method"] = "cash"
            patch["payment"]["cash_amount"] = gross
            merged = apply_settlement_math(patch, gross)

        existing = parse_line_payout_details(row)
        before_ded = dict((existing.get("employee_deductions") or {}))
        before_withheld = float((existing.get("settlement") or {}).get("amount_withheld") or 0)
        before_paid = float((existing.get("settlement") or {}).get("amount_paid") or 0)

        for section in ("employee_deductions", "employer_taxes", "payment", "settlement", "tax_summary"):
            if section in merged:
                existing[section] = {**(existing.get(section) or {}), **merged[section]}
        merged = reconcile_tax_summary(existing)
        merged = apply_settlement_math(merged, gross)

        after_ded = dict((merged.get("employee_deductions") or {}))
        entry = {
            "batch_name": batch_name,
            "line_id": row["line_id"],
            "worker": worker,
            "gross": gross,
            "prior_balance": prior if is_catchup else 0,
            "catch_up_withholding": merged["settlement"]["catch_up_withholding"],
            "amount_withheld": merged["settlement"]["amount_withheld"],
            "amount_paid": merged["settlement"]["amount_paid"],
            "tax_balance_owed": merged["settlement"]["tax_balance_owed"],
        }
        if is_catchup:
            entry["before"] = {
                "fit": float(before_ded.get("fit") or 0),
                "ss": float(before_ded.get("ss") or 0),
                "medicare": float(before_ded.get("medicare") or 0),
                "state": float(before_ded.get("state") or 0),
                "local": float(before_ded.get("local") or 0),
                "amount_withheld": before_withheld,
                "amount_paid": before_paid,
            }
            entry["after"] = {
                "fit": float(after_ded.get("fit") or 0),
                "ss": float(after_ded.get("ss") or 0),
                "medicare": float(after_ded.get("medicare") or 0),
                "state": float(after_ded.get("state") or 0),
                "local": float(after_ded.get("local") or 0),
                "amount_withheld": float(merged["settlement"]["amount_withheld"] or 0),
                "amount_paid": float(merged["settlement"]["amount_paid"] or 0),
            }
        report["lines"].append(entry)

        if not is_catchup:
            owed = float(merged["settlement"]["tax_balance_owed"] or 0)
            running_balance[uid] = round(running_balance.get(uid, 0) + owed, 2)

        if apply:
            updater.execute(
                """
                UPDATE payout_batch_lines SET payout_details_json=%s
                WHERE id=%s
                """,
                (json.dumps(merged), int(row["line_id"])),
            )
            if not is_catchup and float(merged["settlement"]["amount_paid"]) >= gross and gross > 0:
                updater.execute(
                    """
                    UPDATE payout_batch_lines
                    SET payment_status='paid', line_status='paid'
                    WHERE id=%s
                    """,
                    (int(row["line_id"]),),
                )

    if apply:
        conn.commit()
        report["applied"] = True
    else:
        report["applied"] = False

    conn.close()
    return report


def _print_before_after_table(report: dict) -> None:
    rows = [
        ln
        for ln in report.get("lines") or []
        if ln.get("batch_name") == CATCHUP_BATCH_NAME and ln.get("before")
    ]
    if not rows:
        return
    header = (
        f"{'Worker':<28} {'Gross':>8} {'FIT':>7} {'State':>7} {'Local':>7} "
        f"{'SS':>7} {'Med':>7} {'Withheld':>9} {'Paid':>9}"
    )
    print("\nW2-2026-006 withholding — BEFORE (current DB)")
    print(header)
    print("-" * len(header))
    for ln in rows:
        b = ln["before"]
        print(
            f"{ln['worker']:<28} {ln['gross']:>8.2f} {b['fit']:>7.2f} {b['state']:>7.2f} "
            f"{b['local']:>7.2f} {b['ss']:>7.2f} {b['medicare']:>7.2f} "
            f"{b['amount_withheld']:>9.2f} {b['amount_paid']:>9.2f}"
        )
    print("\nW2-2026-006 withholding — AFTER (recalculated, catch-up $0)")
    print(header)
    print("-" * len(header))
    for ln in rows:
        a = ln["after"]
        print(
            f"{ln['worker']:<28} {ln['gross']:>8.2f} {a['fit']:>7.2f} {a['state']:>7.2f} "
            f"{a['local']:>7.2f} {a['ss']:>7.2f} {a['medicare']:>7.2f} "
            f"{a['amount_withheld']:>9.2f} {a['amount_paid']:>9.2f}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill W2 tax catch-up estimates")
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    args = parser.parse_args(argv)
    apply = bool(args.apply)
    report = backfill(args.org_id, apply=apply)
    _print_before_after_table(report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
