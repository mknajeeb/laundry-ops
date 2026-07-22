"""Apply approved OT catch-up correction for 13 org-3 temp/1099 lines.

Preserves settlement.amount_paid, records unpaid OT as outstanding_balance,
archives prior receipt HTML (read pass), recalculates gross from shared OT helpers.

Usage:
  python -m backend.scripts.apply_ot_catchup_org3_13 --dry-run
  python -m backend.scripts.apply_ot_catchup_org3_13 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(".env")

from backend.db import get_db
from backend.payroll_operations import get_payout_batch
from backend.payroll_overtime import (
    compute_wage_with_overtime,
    resolve_overtime_rate,
    split_hours_for_overtime,
)
from backend.payroll_payout_details import (
    _audit_append,
    generate_vendor_receipt_html,
    parse_line_payout_details,
)

ORG_ID = 3
LINE_IDS = (217, 213, 272, 288, 341, 342, 194, 198, 203, 273, 355, 364, 365)
ACTOR_ID = 0
PROPOSAL_ID = "ot_catchup_org3_2026-07-21"


def _money(val) -> float:
    try:
        return round(float(val or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_line(row: dict, details: dict) -> dict:
    settlement = details.get("settlement") or {}
    payment = details.get("payment") or {}
    return {
        "approved_hours": _money(row.get("approved_hours")),
        "ot_hours": _money(row.get("ot_hours")),
        "rate": _money(row.get("rate")),
        "ot_rate": _money(row.get("ot_rate")) if row.get("ot_rate") is not None else None,
        "gross_amount": _money(row.get("gross_amount")),
        "total_amount": _money(row.get("total_amount")),
        "amount_paid": _money(settlement.get("amount_paid")),
        "outstanding_balance": _money(settlement.get("outstanding_balance")),
        "paid_full_gross_without_withholding": bool(
            settlement.get("paid_full_gross_without_withholding")
        ),
        "preserve_amount_paid": bool(settlement.get("preserve_amount_paid")),
        "payment_date": payment.get("date"),
        "payment_method": payment.get("method"),
    }


def _fetch_rows(conn) -> list[dict]:
    c = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(LINE_IDS))
    c.execute(
        f"""
        SELECT
          pbl.id AS line_id,
          pbl.batch_id,
          pbl.user_id,
          pbl.worker_name_snapshot,
          pbl.approved_hours,
          pbl.ot_hours,
          pbl.rate,
          pbl.ot_rate,
          pbl.gross_amount,
          pbl.total_amount,
          pbl.payout_details_json,
          pbl.adjustments,
          pbl.bonus_tip_amount,
          pbl.reimbursement_amount,
          pbl.health_credit_amount,
          pbl.sick_pay_amount,
          pb.batch_name,
          pb.worker_category,
          pb.status AS batch_status,
          pb.official_pay_date,
          pb.payout_details_finalized_at,
          pb.payout_details_audit_json
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pbl.id IN ({placeholders})
        ORDER BY pb.batch_name, pbl.id
        """,
        (ORG_ID, *LINE_IDS),
    )
    rows = c.fetchall() or []
    if len(rows) != len(LINE_IDS):
        found = {int(r["line_id"]) for r in rows}
        missing = [i for i in LINE_IDS if i not in found]
        raise RuntimeError(f"Expected {len(LINE_IDS)} lines; missing {missing}")
    return rows


def _archive_prior_receipts(conn, rows: list[dict]) -> dict[int, dict]:
    """Read-only pass: capture prior receipt HTML before any writes."""
    out: dict[int, dict] = {}
    for row in rows:
        line_id = int(row["line_id"])
        batch_id = int(row["batch_id"])
        finalized = bool(row.get("payout_details_finalized_at"))
        try:
            html = generate_vendor_receipt_html(
                conn, ORG_ID, batch_id, line_id, preview=not finalized
            )
            out[line_id] = {"html": html, "error": None}
            print(f"  archived receipt line {line_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            out[line_id] = {"html": None, "error": str(exc)}
            print(f"  archive failed line {line_id}: {exc}", flush=True)
    return out


def apply_correction(conn, *, apply: bool) -> dict:
    rows = _fetch_rows(conn)
    archives: dict[int, dict] = {}
    if apply:
        print("Archiving prior receipts (read-only)...", flush=True)
        archives = _archive_prior_receipts(conn, rows)

    report: dict = {
        "proposal_id": PROPOSAL_ID,
        "organization_id": ORG_ID,
        "apply": bool(apply),
        "at": datetime.now(timezone.utc).isoformat(),
        "lines": [],
        "audit_events_written": 0,
        "receipts_archived": 0,
        "receipts_regenerated": 0,
        "totals": {},
    }
    batch_events: dict[int, list] = {}
    updater = conn.cursor()

    for row in rows:
        line_id = int(row["line_id"])
        batch_id = int(row["batch_id"])
        details = parse_line_payout_details(row, worker_category=row.get("worker_category"))
        before = _snapshot_line(row, details)
        payment_date_before = (details.get("payment") or {}).get("date")
        official_before = str(row.get("official_pay_date") or "")[:10]

        arch = archives.get(line_id) or {}
        archived_html = arch.get("html")
        archive_error = arch.get("error")

        reg_h = _money(row.get("approved_hours"))
        ot_h = _money(row.get("ot_hours"))
        total_hours = reg_h + ot_h
        if ot_h <= 0 and reg_h > 40:
            total_hours = reg_h
        prop_reg, prop_ot = split_hours_for_overtime(total_hours)
        rate = _money(row.get("rate"))
        prop_ot_rate = float(resolve_overtime_rate(rate, multiplier=1.5))
        other = (
            _money(row.get("adjustments"))
            + _money(row.get("bonus_tip_amount"))
            + _money(row.get("reimbursement_amount"))
            + _money(row.get("health_credit_amount"))
            + _money(row.get("sick_pay_amount"))
        )
        prop_gross = _money(
            float(compute_wage_with_overtime(prop_reg, prop_ot, rate, prop_ot_rate)) + other
        )
        amount_paid = _money(before["amount_paid"] or before["gross_amount"])
        unpaid = _money(prop_gross - amount_paid)

        new_details = dict(details)
        settlement = dict(new_details.get("settlement") or {})
        settlement["amount_paid"] = amount_paid
        settlement["amount_withheld"] = 0.0
        settlement["outstanding_balance"] = unpaid
        settlement["paid_full_gross_without_withholding"] = False
        settlement["preserve_amount_paid"] = True
        new_details["settlement"] = settlement

        history = list(new_details.get("receipt_history") or [])
        hist_entry = {
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "reason": "ot_catchup_correction_pre",
            "proposal_id": PROPOSAL_ID,
            "line_snapshot": before,
        }
        if archived_html:
            hist_entry["html"] = archived_html
            report["receipts_archived"] += 1
        if archive_error:
            hist_entry["error"] = archive_error
            hist_entry["reason"] = "ot_catchup_correction_pre_archive_partial"
        history.append(hist_entry)
        new_details["receipt_history"] = history
        new_details["ot_catchup"] = {
            "proposal_id": PROPOSAL_ID,
            "ot_multiplier": 1.5,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "unpaid_ot_balance": unpaid,
        }

        after_fields = {
            "approved_hours": _money(prop_reg),
            "ot_hours": _money(prop_ot),
            "rate": rate,
            "ot_rate": _money(prop_ot_rate),
            "ot_multiplier": 1.5,
            "regular_earnings": _money(float(prop_reg) * rate),
            "full_ot_earnings": _money(float(prop_ot) * prop_ot_rate),
            "gross_amount": prop_gross,
            "total_amount": prop_gross,
            "amount_paid": amount_paid,
            "outstanding_balance": unpaid,
            "paid_full_gross_without_withholding": False,
            "preserve_amount_paid": True,
            "payment_date": payment_date_before,
            "official_pay_date": official_before,
        }

        entry = {
            "line_id": line_id,
            "batch_id": batch_id,
            "batch_name": row.get("batch_name"),
            "worker": " ".join(str(row.get("worker_name_snapshot") or "").split()),
            "before": before,
            "after": after_fields,
            "official_pay_date_unchanged": official_before,
            "payment_date_unchanged": payment_date_before,
            "archive_error": archive_error,
        }
        report["lines"].append(entry)

        if not apply:
            continue

        updater.execute(
            """
            UPDATE payout_batch_lines
            SET approved_hours=%s,
                ot_hours=%s,
                ot_rate=%s,
                gross_amount=%s,
                total_amount=%s,
                payout_details_json=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (
                float(prop_reg),
                float(prop_ot),
                float(prop_ot_rate),
                prop_gross,
                prop_gross,
                json.dumps(new_details),
                line_id,
                batch_id,
                ORG_ID,
            ),
        )
        print(f"  updated line {line_id}", flush=True)

        batch = get_payout_batch(conn, ORG_ID, batch_id) or {
            "payout_details_audit_json": row.get("payout_details_audit_json")
        }
        if batch_id in batch_events:
            batch = dict(batch)
            batch["payout_details_audit_json"] = json.dumps({"events": batch_events[batch_id]})
        events = _audit_append(
            batch,
            "ot_catchup_correction",
            ACTOR_ID,
            f"line {line_id}: OT split + unpaid balance ${unpaid:.2f}",
            old_value=before,
            new_value=after_fields,
            reason=PROPOSAL_ID,
        )
        batch_events[batch_id] = events
        report["audit_events_written"] += 1

    if apply:
        for batch_id, events in batch_events.items():
            updater.execute(
                """
                UPDATE payout_batches
                SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
                WHERE id=%s AND organization_id=%s
                """,
                (json.dumps({"events": events}), batch_id, ORG_ID),
            )
        conn.commit()
        print("Committed line + audit updates.", flush=True)

        print("Verifying regenerated receipts...", flush=True)
        for entry in report["lines"]:
            try:
                c2 = conn.cursor(dictionary=True)
                c2.execute(
                    "SELECT payout_details_finalized_at FROM payout_batches WHERE id=%s",
                    (entry["batch_id"],),
                )
                brow = c2.fetchone() or {}
                finalized = bool(brow.get("payout_details_finalized_at"))
                html = generate_vendor_receipt_html(
                    conn,
                    ORG_ID,
                    int(entry["batch_id"]),
                    int(entry["line_id"]),
                    preview=not finalized,
                )
                entry["receipt_regenerated"] = True
                entry["receipt_has_outstanding"] = "Outstanding OT balance" in html
                entry["receipt_has_ot_hours"] = "Overtime hours" in html
                entry["receipt_has_amount_previously_paid"] = "Amount previously paid" in html
                report["receipts_regenerated"] += 1
                print(f"  regen ok line {entry['line_id']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                entry["receipt_regenerated"] = False
                entry["receipt_error"] = str(exc)
                print(f"  regen fail line {entry['line_id']}: {exc}", flush=True)

    gross_total = _money(sum(e["after"]["gross_amount"] for e in report["lines"]))
    paid_total = _money(sum(e["after"]["amount_paid"] for e in report["lines"]))
    outstanding_total = _money(sum(e["after"]["outstanding_balance"] for e in report["lines"]))
    report["totals"] = {
        "corrected_gross": gross_total,
        "amount_paid": paid_total,
        "outstanding_ot_balance": outstanding_total,
        "expected_gross": 11316.58,
        "expected_paid": 10491.04,
        "expected_outstanding": 825.54,
        "gross_ok": abs(gross_total - 11316.58) < 0.02,
        "paid_ok": abs(paid_total - 10491.04) < 0.02,
        "outstanding_ok": abs(outstanding_total - 825.54) < 0.02,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-receipt-archive",
        action="store_true",
        help="Skip HTML archive (still stores field snapshot + audit)",
    )
    args = parser.parse_args()
    apply = bool(args.apply) and not bool(args.dry_run)

    conn = get_db()
    try:
        # Monkey-patch archive skip via env of empty archives when requested
        if args.skip_receipt_archive:
            global _archive_prior_receipts  # noqa: PLW0603

            def _archive_prior_receipts(conn, rows):  # type: ignore[misc]
                print("Skipping HTML receipt archive (--skip-receipt-archive)", flush=True)
                return {
                    int(r["line_id"]): {"html": None, "error": "skipped_by_flag"} for r in rows
                }

        report = apply_correction(conn, apply=apply)
    finally:
        conn.close()

    out_path = Path("data") / (
        "ot_catchup_org3_13_apply.json" if apply else "ot_catchup_org3_13_dry_run.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Do not dump megabytes of HTML into the summary file.
    slim = json.loads(json.dumps(report, default=str))
    out_path.write_text(json.dumps(slim, indent=2))
    print(json.dumps(slim["totals"], indent=2))
    print(
        f"lines={len(slim['lines'])} apply={apply} "
        f"archived={slim['receipts_archived']} regen={slim['receipts_regenerated']} "
        f"audits={slim['audit_events_written']} wrote={out_path}"
    )
    if not apply:
        print("DRY RUN — re-run with --apply to persist.", file=sys.stderr)
    if apply and not (
        slim["totals"]["gross_ok"]
        and slim["totals"]["paid_ok"]
        and slim["totals"]["outstanding_ok"]
    ):
        sys.exit(2)


if __name__ == "__main__":
    main()
