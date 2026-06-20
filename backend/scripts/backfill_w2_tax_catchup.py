"""
Backfill estimated taxes for W2-2026-002 through W2-2026-006 catch-up payroll.

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
    report: dict = {"prior_balances": prior_balances, "lines": []}

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
    running_balance: dict[int, float] = dict(prior_balances)

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

        current_liability = round(
            sum(float(v or 0) for v in (patch.get("employee_deductions") or {}).values()),
            2,
        )
        if is_catchup:
            withheld_target = round(current_liability + prior, 2)
            withheld = round(min(gross, withheld_target), 2)
            patch.setdefault("settlement", {})
            patch["settlement"].update(
                {
                    "prior_unpaid_taxes": prior,
                    "amount_withheld": withheld,
                    "amount_paid": round(max(0.0, gross - withheld), 2),
                    "paid_full_gross_without_withholding": False,
                }
            )
            patch.setdefault("tax_summary", {})
            patch["tax_summary"]["prior_tax_balance"] = prior
            patch = reconcile_tax_summary(patch)
        else:
            patch.setdefault("settlement", {})
            patch["settlement"].update(
                {
                    "prior_unpaid_taxes": 0.0,
                    "amount_withheld": 0.0,
                    "amount_paid": gross,
                    "paid_full_gross_without_withholding": True,
                }
            )
            patch.setdefault("payment", {})
            patch["payment"]["method"] = "cash"
            patch["payment"]["cash_amount"] = gross
            patch = reconcile_tax_summary(patch)

        existing = parse_line_payout_details(row)
        merged = dict(existing)
        for section in ("employee_deductions", "employer_taxes", "payment", "settlement", "tax_summary"):
            if section in patch:
                merged[section] = {**(merged.get(section) or {}), **patch[section]}
        merged = reconcile_tax_summary(merged)

        entry = {
            "batch_name": batch_name,
            "line_id": row["line_id"],
            "worker": worker,
            "gross": gross,
            "prior_balance": prior if is_catchup else 0,
            "amount_withheld": merged["settlement"]["amount_withheld"],
            "amount_paid": merged["settlement"]["amount_paid"],
            "tax_balance_owed": merged["settlement"]["tax_balance_owed"],
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

    if apply:
        conn.commit()
        report["applied"] = True
    else:
        report["applied"] = False

    conn.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill W2 tax catch-up estimates")
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    args = parser.parse_args(argv)
    apply = bool(args.apply)
    report = backfill(args.org_id, apply=apply)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
