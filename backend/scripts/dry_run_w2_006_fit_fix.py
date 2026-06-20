"""
Dry-run W2-2026-006 withholding after FIT calculation fixes (no DB writes).

Usage:
  python3 -m backend.scripts.dry_run_w2_006_fit_fix --org-id 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BATCH_NAME = "W2-2026-006"


def dry_run(org_id: int) -> dict:
    from backend.db import get_db
    from backend.payroll_payout_details import (
        apply_settlement_math,
        build_estimated_payout_details_patch,
        infer_pay_frequency_from_batch,
        parse_line_payout_details,
        reconcile_tax_summary,
    )

    conn = get_db()
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pb.id AS batch_id, pb.pay_period_start, pb.pay_period_end,
               pbl.id AS line_id, pbl.user_id, pbl.worker_name_snapshot,
               pbl.gross_amount, pbl.total_amount, pbl.payout_details_json
        FROM payout_batches pb
        JOIN payout_batch_lines pbl ON pbl.batch_id = pb.id
        WHERE pb.organization_id = %s AND pb.batch_name = %s
        ORDER BY pbl.worker_name_snapshot
        """,
        (int(org_id), BATCH_NAME),
    )
    rows = c.fetchall() or []
    if not rows:
        conn.close()
        raise ValueError(f"Batch {BATCH_NAME} not found for org {org_id}")

    batch = {
        "pay_period_start": str(rows[0].get("pay_period_start") or ""),
        "pay_period_end": str(rows[0].get("pay_period_end") or ""),
    }
    pay_freq = infer_pay_frequency_from_batch(batch)
    report_lines: list[dict] = []

    for row in rows:
        gross = float(row.get("gross_amount") or row.get("total_amount") or 0)
        worker = str(row.get("worker_name_snapshot") or "")
        before = parse_line_payout_details(row)
        before_ded = before.get("employee_deductions") or {}
        before_settlement = before.get("settlement") or {}

        patch = build_estimated_payout_details_patch(
            conn,
            org_id,
            int(row["user_id"]),
            gross,
            worker_name=worker,
            pay_period_start=batch.get("pay_period_start"),
            pay_frequency=pay_freq,
        )
        patch.setdefault("settlement", {})
        patch["settlement"]["catch_up_withholding"] = 0.0
        patch["settlement"]["paid_full_gross_without_withholding"] = False
        existing = dict(before)
        for section in ("employee_deductions", "employer_taxes", "tax_summary"):
            if section in patch:
                existing[section] = {**(existing.get(section) or {}), **patch[section]}
        merged = reconcile_tax_summary(apply_settlement_math(existing, gross))
        after_ded = merged.get("employee_deductions") or {}
        after_settlement = merged.get("settlement") or {}

        fit_b = float(before_ded.get("fit") or 0)
        fit_a = float(after_ded.get("fit") or 0)
        ss_a = float(after_ded.get("ss") or 0)
        med_a = float(after_ded.get("medicare") or 0)
        state_a = float(after_ded.get("state") or 0)
        local_a = float(after_ded.get("local") or 0)
        wh_a = round(fit_a + ss_a + med_a + state_a + local_a, 2)

        report_lines.append(
            {
                "worker": worker,
                "gross": gross,
                "pay_frequency_used": pay_freq,
                "before": {
                    "fit": fit_b,
                    "state": float(before_ded.get("state") or 0),
                    "local": float(before_ded.get("local") or 0),
                    "ss": float(before_ded.get("ss") or 0),
                    "medicare": float(before_ded.get("medicare") or 0),
                    "total_withholding": round(
                        fit_b
                        + float(before_ded.get("ss") or 0)
                        + float(before_ded.get("medicare") or 0)
                        + float(before_ded.get("state") or 0)
                        + float(before_ded.get("local") or 0),
                        2,
                    ),
                    "net_paid": float(before_settlement.get("amount_paid") or 0),
                    "catch_up": float(before_settlement.get("catch_up_withholding") or 0),
                },
                "after": {
                    "fit": fit_a,
                    "state": state_a,
                    "local": local_a,
                    "ss": ss_a,
                    "medicare": med_a,
                    "total_withholding": wh_a,
                    "net_paid": float(after_settlement.get("amount_paid") or 0),
                    "catch_up": float(after_settlement.get("catch_up_withholding") or 0),
                },
            }
        )

    conn.close()
    return {
        "batch_name": BATCH_NAME,
        "org_id": org_id,
        "pay_frequency_inferred": pay_freq,
        "applied": False,
        "lines": report_lines,
    }


def print_table(report: dict) -> None:
    batch = report.get("batch_name")
    print(
        f"\n{batch} withholding dry-run (org {report['org_id']}) "
        f"— pay frequency: {report['pay_frequency_inferred']}"
    )
    hdr = (
        f"{'Employee':<28} {'Gross':>8} {'FIT bef':>8} {'FIT aft':>8} "
        f"{'State':>7} {'Local':>7} {'SS':>7} {'Med':>7} "
        f"{'Tot WH':>8} {'Net paid':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for ln in report.get("lines") or []:
        b, a = ln["before"], ln["after"]
        print(
            f"{ln['worker']:<28} {ln['gross']:>8.2f} {b['fit']:>8.2f} {a['fit']:>8.2f} "
            f"{a['state']:>7.2f} {a['local']:>7.2f} {a['ss']:>7.2f} {a['medicare']:>7.2f} "
            f"{a['total_withholding']:>8.2f} {a['net_paid']:>9.2f}"
        )
    print("\nCatch-up withholding: $0 for all rows (display-only prior balance unchanged).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run W2-2026-006 FIT fix")
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument(
        "--out",
        type=str,
        default=str(REPO_ROOT / "data/w2_006_fit_fix_dry_run.json"),
    )
    args = parser.parse_args(argv)
    report = dry_run(args.org_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_table(report)
    print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
