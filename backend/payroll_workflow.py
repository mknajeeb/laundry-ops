"""Payroll batch workflow: rates, due amounts, payment status, W-4 tax prep (engine pending)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from backend.contractor_management import (
    _contractor_json_from_hr,
    _latest_hourly_rate,
    _latest_payment_method_label,
    build_contractor_prefill,
    compute_payment_summary_amounts,
)
from backend.hr_compliance import ensure_hr_extended_profiles_table
from backend.payroll_identity import fetch_payroll_profile_row, payroll_profiles_active
from backend.payroll_operations import (
    BATCH_STATUSES,
    CATEGORY_LABELS,
    WORKER_CATEGORIES,
    _money,
    get_payout_batch,
    list_time_records,
    worker_category_for_user,
)
from backend.payroll_tax_messages import (
    ACCOUNTANT_BATCH_READY_MESSAGE,
    ESTIMATE_DISCLAIMER,
    ESTIMATED_WITHHOLDING_NOTICE,
    MANUAL_DEDUCTIONS_NOTICE,
    MANUAL_TAX_DEDUCTIONS_ONLY,
    PAYROLL_ESTIMATE_PURPOSE,
    SEND_TO_ACCOUNTANT_W2_CONFIRM,
)
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column

PAYMENT_STATUSES = ("pending", "approved_unpaid", "paid")
TAX_CALC_STATUSES = ("not_applicable", "pending", "calculated")

BATCH_ACTIONS = (
    "approve_hours",
    "hours_reviewed",
    "send_to_accountant",
    "revert_to_draft",
    "process_batch",
    "mark_paid",
    "mark_line_paid",
    "mark_line_unpaid",
    "refresh_rates",
    "recalculate_taxes",
)

REVERT_TO_DRAFT_STATUSES = frozenset({"hours_reviewed", "sent_to_accountant", "accountant_reviewed"})

ACCOUNTANT_VISIBLE_STATUSES = frozenset(
    {
        "sent_to_accountant",
        "accountant_reviewed",
        "approved_for_payment",
        "paid",
        "closed",
    }
)

ACCOUNTANT_PROCESSED_STATUSES = frozenset(
    {
        "accountant_reviewed",
        "approved_for_payment",
        "paid",
        "closed",
    }
)

ACCOUNTANT_PAID_STATUSES = frozenset({"paid", "closed"})


def accountant_batch_processing_status(batch: dict) -> Optional[str]:
    """Accountant W-2 panel: Pending → Payment initiated → Paid."""
    st = str(batch.get("status") or "")
    confirmed = bool(batch.get("accountant_payment_confirmed_at"))
    if st == "sent_to_accountant":
        return "PENDING"
    if st == "approved_for_payment":
        return "PAYMENT_INITIATED" if confirmed else "PENDING"
    if st == "accountant_reviewed":
        return "PAYMENT_INITIATED"
    if st in ACCOUNTANT_PAID_STATUSES:
        return "PAID"
    return None


def can_process_batch_as_accountant(batch: dict) -> bool:
    return str(batch.get("status") or "") == "sent_to_accountant"


def ensure_payout_batch_line_extensions(cursor) -> None:
    from backend.payroll_operations import ensure_payout_batches_tables
    from backend.payroll_accrual import ensure_payout_line_accrual_columns

    ensure_payout_batches_tables(cursor)
    ensure_payout_line_accrual_columns(cursor)
    extras = [
        ("payment_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
        ("tax_calc_status", "VARCHAR(32) NULL"),
        ("tax_calc_notes", "TEXT NULL"),
        ("additional_medicare_withholding", "DECIMAL(10,2) NULL"),
        ("total_employee_taxes", "DECIMAL(10,2) NULL"),
        ("employer_social_security", "DECIMAL(10,2) NULL"),
        ("employer_medicare", "DECIMAL(10,2) NULL"),
        ("futa_estimate", "DECIMAL(10,2) NULL"),
        ("ny_suta_estimate", "DECIMAL(10,2) NULL"),
        ("employer_other_tax_estimate", "DECIMAL(10,2) NULL"),
        ("workers_comp_estimate", "DECIMAL(10,2) NULL"),
        ("total_employer_taxes", "DECIMAL(10,2) NULL"),
        ("total_employer_cost", "DECIMAL(10,2) NULL"),
    ]
    for col, typedef in extras:
        if not table_has_column(cursor, "payout_batch_lines", col):
            try:
                cursor.execute(
                    f"ALTER TABLE payout_batch_lines ADD COLUMN {col} {typedef}"
                )
            except Exception as exc:
                if getattr(exc, "args", (None,))[0] != 1060:
                    raise
            invalidate_schema_cache()


def _payroll_schedule_profile_rate(
    conn, user_id: int, organization_id: int
) -> Optional[float]:
    """Hourly rate from Payroll Scheduling worker profile (operational source of truth)."""
    chk = conn.cursor()
    if not table_exists(chk, "payroll_worker_profiles"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT default_hourly_rate
        FROM payroll_worker_profiles
        WHERE organization_id=%s AND user_id=%s AND active=1
        LIMIT 1
        """,
        (int(organization_id), int(user_id)),
    )
    row = c.fetchone()
    if not row or row.get("default_hourly_rate") is None:
        return None
    val = float(row["default_hourly_rate"])
    return val if val > 0 else None


def _employee_profile_pay_rate(conn, user_id: int) -> Optional[float]:
    chk = conn.cursor()
    if not table_exists(chk, "employee_profiles") or not table_has_column(chk, "users", "employee_id"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute("SELECT employee_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
    row = c.fetchone()
    emp_id = row.get("employee_id") if row else None
    if not emp_id:
        return None
    c.execute(
        "SELECT pay_rate FROM employee_profiles WHERE employee_id=%s LIMIT 1",
        (int(emp_id),),
    )
    ep = c.fetchone()
    if not ep or ep.get("pay_rate") is None:
        return None
    val = float(ep["pay_rate"])
    return val if val > 0 else None


def resolve_worker_hourly_rate(
    conn, user_id: int, organization_id: int
) -> dict[str, Any]:
    """Resolve hourly rate from scheduling and worker profile records (never hardcoded)."""
    cat = worker_category_for_user(conn, user_id)
    rate: Optional[float] = None
    source = "missing"
    sched = _payroll_schedule_profile_rate(conn, user_id, organization_id)
    if sched and sched > 0:
        rate = sched
        source = "payroll_schedule"
    cj, _ = _contractor_json_from_hr(conn, user_id)
    if rate is None:
        cj_rate = cj.get("rate_per_hour") or cj.get("hourly_rate")
        if cj_rate is not None:
            try:
                val = float(cj_rate)
                if val > 0:
                    rate = val
                    source = "contractor_profile"
            except (TypeError, ValueError):
                pass
    if rate is None:
        ur = _latest_hourly_rate(conn, user_id)
        if ur and ur > 0:
            rate = ur
            source = "user_rates"
    if rate is None and cat == "w2":
        ep = _employee_profile_pay_rate(conn, user_id)
        if ep and ep > 0:
            rate = ep
            source = "employee_profile"
    if rate is None:
        try:
            pre = build_contractor_prefill(conn, user_id, organization_id)
            val = float(pre.get("rate_per_hour") or 0)
            if val > 0:
                rate = val
                source = "payroll_prefill"
        except Exception:
            pass
    payment_method = ""
    try:
        pre = build_contractor_prefill(conn, user_id, organization_id)
        payment_method = str(pre.get("payment_method") or "").strip()
    except Exception:
        payment_method = _latest_payment_method_label(conn, user_id) or ""
    return {
        "user_id": int(user_id),
        "worker_category": cat,
        "worker_category_label": CATEGORY_LABELS.get(cat, cat),
        "hourly_rate": rate,
        "rate_source": source,
        "rate_missing": rate is None or rate <= 0,
        "payment_method": payment_method,
    }


def fetch_w4_compliance_summary(conn, user_id: int, organization_id: int) -> dict[str, Any]:
    """Read W-4 / payroll tax profile for batch display and validation."""
    from backend.w2_payroll_tax_engine import ESTIMATE_DISCLAIMER, fetch_employee_tax_profile

    profile = fetch_employee_tax_profile(conn, user_id, organization_id)
    return {
        "w4_on_file": profile.get("w4_complete"),
        "filing_status": profile.get("filing_status"),
        "pay_frequency": profile.get("pay_frequency"),
        "work_state": profile.get("work_state"),
        "work_city": profile.get("work_city"),
        "exempt_from_withholding": profile.get("exempt_federal"),
        "extra_withholding": float(profile.get("extra_withholding") or 0),
        "missing_fields": profile.get("missing_fields") or [],
        "tax_calc_status": "estimated" if profile.get("w4_complete") else "profile_incomplete",
        "tax_calc_note": (
            ESTIMATE_DISCLAIMER
            if profile.get("w4_complete")
            else f"Missing: {', '.join(profile.get('missing_fields') or ['W-4/payroll fields'])}"
        ),
    }


def persist_w2_line_taxes(
    conn,
    organization_id: int,
    line_id: int,
    user_id: int,
    gross_pay: float,
    *,
    pay_period_start: Optional[str] = None,
) -> None:
    if MANUAL_TAX_DEDUCTIONS_ONLY:
        return
    from backend.w2_payroll_tax_engine import calculate_w2_line_taxes

    ensure_payout_batch_line_extensions(conn.cursor())
    calc = calculate_w2_line_taxes(
        conn,
        organization_id,
        user_id,
        gross_pay=gross_pay,
        pay_period_start=pay_period_start,
    )
    c = conn.cursor()
    if calc.get("tax_calc_status") == "profile_incomplete":
        c.execute(
            """
            UPDATE payout_batch_lines SET
              gross_wages=%s, gross_amount=%s,
              federal_withholding=NULL, state_withholding=NULL, city_withholding=NULL,
              social_security_withholding=NULL, medicare_withholding=NULL,
              additional_medicare_withholding=NULL, total_employee_taxes=NULL,
              net_pay=NULL,
              employer_social_security=NULL, employer_medicare=NULL, futa_estimate=NULL,
              ny_suta_estimate=NULL, employer_other_tax_estimate=NULL, workers_comp_estimate=NULL,
              total_employer_taxes=NULL, total_employer_cost=NULL,
              tax_calc_status=%s, tax_calc_notes=%s,
              total_amount=%s
            WHERE id=%s AND organization_id=%s
            """,
            (
                gross_pay,
                gross_pay,
                calc.get("tax_calc_status"),
                calc.get("tax_calc_notes"),
                gross_pay,
                int(line_id),
                int(organization_id),
            ),
        )
        return
    c.execute(
        """
        UPDATE payout_batch_lines SET
          gross_wages=%s, gross_amount=%s,
          federal_withholding=%s, state_withholding=%s, city_withholding=%s,
          social_security_withholding=%s, medicare_withholding=%s,
          additional_medicare_withholding=%s, total_employee_taxes=%s, net_pay=%s,
          ny_pfl_deduction=%s, ny_dbl_deduction=%s,
          employer_social_security=%s, employer_medicare=%s, futa_estimate=%s,
          ny_suta_estimate=%s, employer_other_tax_estimate=%s, workers_comp_estimate=%s,
          total_employer_taxes=%s, total_employer_cost=%s,
          tax_calc_status=%s, tax_calc_notes=%s,
          total_amount=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            calc.get("gross_pay"),
            calc.get("gross_pay"),
            calc.get("federal_withholding_estimate"),
            calc.get("ny_state_withholding_estimate"),
            calc.get("nyc_withholding_estimate"),
            calc.get("social_security_employee"),
            calc.get("medicare_employee"),
            calc.get("additional_medicare_employee"),
            calc.get("total_employee_taxes"),
            calc.get("net_pay"),
            calc.get("ny_pfl_deduction"),
            calc.get("ny_dbl_deduction"),
            calc.get("employer_social_security"),
            calc.get("employer_medicare"),
            calc.get("futa_estimate"),
            calc.get("ny_suta_estimate"),
            calc.get("employer_other_tax_estimate"),
            calc.get("workers_comp_estimate"),
            calc.get("total_employer_taxes"),
            calc.get("total_employer_cost"),
            calc.get("tax_calc_status"),
            calc.get("tax_calc_notes"),
            calc.get("gross_pay"),
            int(line_id),
            int(organization_id),
        ),
    )


def recalculate_w2_batch_taxes(conn, organization_id: int, batch_id: int) -> None:
    if MANUAL_TAX_DEDUCTIONS_ONLY:
        return
    from backend.payroll_operations import _recompute_batch_totals

    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT worker_category, pay_period_start FROM payout_batches WHERE id=%s AND organization_id=%s",
        (int(batch_id), int(organization_id)),
    )
    batch = c.fetchone()
    if not batch or str(batch.get("worker_category")) != "w2":
        return
    c.execute(
        "SELECT id, user_id, gross_amount, approved_hours, rate FROM payout_batch_lines WHERE batch_id=%s",
        (int(batch_id),),
    )
    for ln in c.fetchall() or []:
        uid = ln.get("user_id")
        if not uid:
            continue
        hours = float(ln.get("approved_hours") or 0)
        rate = float(ln.get("rate") or 0)
        gross = float(ln.get("gross_amount") or hours * rate)
        persist_w2_line_taxes(
            conn,
            organization_id,
            int(ln["id"]),
            int(uid),
            gross,
            pay_period_start=str(batch.get("pay_period_start") or ""),
        )
    _recompute_batch_totals(conn, batch_id)
    conn.commit()


def prepare_w2_line_tax_fields(conn, user_id: int, gross: float, organization_id: int = 0) -> dict[str, Any]:
    """Legacy hook — actual amounts filled by persist_w2_line_taxes."""
    from backend.w2_payroll_tax_engine import fetch_employee_tax_profile

    profile = fetch_employee_tax_profile(conn, user_id, organization_id or 1)
    return {
        "gross_wages": gross,
        "tax_calc_status": "estimated" if profile.get("w4_complete") else "profile_incomplete",
    }


def _line_payment_status_label(st: str) -> str:
    if st == "paid":
        return "Paid"
    if st == "unpaid":
        return "UNPAID"
    if st == "approved_unpaid":
        return "Approved — unpaid"
    return "Pending payment"


def _batch_payment_status(lines: list[dict]) -> str:
    if not lines:
        return "pending"
    from backend.payroll_worker_categories import is_payment_recorded_paid, is_payment_recorded_unpaid

    paid = sum(1 for ln in lines if is_payment_recorded_paid(ln, ln.get("payout_details")))
    unpaid = sum(1 for ln in lines if is_payment_recorded_unpaid(ln, ln.get("payout_details")))
    if paid == len(lines):
        return "paid"
    if unpaid == len(lines):
        return "unpaid"
    if paid > 0:
        return "partially_paid"
    if any(str(ln.get("payment_status") or "") == "approved_unpaid" for ln in lines):
        return "approved_unpaid"
    return "pending"


def _sum_withholding(lines: list[dict], field: str) -> float:
    total = Decimal("0")
    for ln in lines:
        val = ln.get(field)
        if val is not None:
            total += _money(val)
    return float(total)


def _sum_estimated_tax_field(lines: list[dict], field: str) -> Optional[float]:
    """Sum tax fields only for W-2 lines with completed estimates (never fake zeros)."""
    total = Decimal("0")
    found = False
    for ln in lines:
        if str(ln.get("tax_calc_status") or "") != "estimated":
            continue
        val = ln.get(field)
        if val is None:
            continue
        found = True
        total += _money(val)
    return float(total) if found else None


_W2_TAX_AMOUNT_FIELDS = (
    "federal_withholding",
    "state_withholding",
    "city_withholding",
    "social_security_withholding",
    "medicare_withholding",
    "additional_medicare_withholding",
    "total_employee_taxes",
    "employer_social_security",
    "employer_medicare",
    "futa_estimate",
    "ny_suta_estimate",
    "employer_other_tax_estimate",
    "workers_comp_estimate",
    "total_employer_taxes",
    "total_employer_cost",
)


def _mask_incomplete_w2_line_taxes(row: dict) -> None:
    """Ensure API responses never expose $0 placeholders for incomplete profiles."""
    if str(row.get("tax_calc_status") or "") != "profile_incomplete":
        return
    for field in _W2_TAX_AMOUNT_FIELDS:
        row[field] = None
    row["net_pay"] = None
    row["employee_taxes_total"] = None


def build_payroll_readiness(
    batch: dict,
    cat: str,
    missing_rates: list[dict],
    missing_w4: list[dict],
    lines: list[dict],
) -> list[dict]:
    """Visible checklist for batch workflow — hours, rates, and export readiness."""
    has_lines = bool(lines)
    st = str(batch.get("status") or "draft")
    is_w2 = cat == "w2"
    hours_reviewed_ok = st in (
        "hours_reviewed",
        "sent_to_accountant",
        "accountant_reviewed",
        "approved_for_payment",
        "paid",
        "closed",
    )
    rate_ok = has_lines and not missing_rates

    if MANUAL_TAX_DEDUCTIONS_ONLY:
        export_ok = has_lines and rate_ok and hours_reviewed_ok
        if not has_lines:
            export_detail = "Add worker lines first"
        elif not rate_ok:
            export_detail = "Resolve missing hourly rates"
        elif not hours_reviewed_ok:
            export_detail = "Mark hours reviewed before export"
        else:
            export_detail = "Ready for accountant review"
        return [
            {
                "key": "worker_type",
                "label": "Worker type confirmed",
                "ok": bool(cat),
                "applicable": True,
                "detail": CATEGORY_LABELS.get(cat, cat or "Unset"),
            },
            {
                "key": "rate_present",
                "label": "Rate present",
                "ok": rate_ok,
                "applicable": True,
                "detail": "All lines have hourly rate" if rate_ok else f"{len(missing_rates)} missing rate(s)",
            },
            {
                "key": "hours_reviewed",
                "label": "Hours reviewed",
                "ok": hours_reviewed_ok,
                "applicable": True,
                "detail": f"Status: {st.replace('_', ' ')}",
            },
            {
                "key": "accountant_export",
                "label": "Accountant export ready",
                "ok": export_ok,
                "applicable": True,
                "detail": export_detail,
            },
            {
                "key": "paid_tracking",
                "label": "Paid/unpaid tracking available",
                "ok": True,
                "applicable": True,
                "detail": "Mark paid/unpaid after send to accountant",
            },
        ]

    w4_ok = (not missing_w4 and has_lines) if is_w2 else True
    if is_w2:
        w4_detail = (
            "All W-2 profiles complete"
            if w4_ok
            else f"{len(missing_w4)} worker(s) missing W-4/payroll tax fields"
        )
    else:
        w4_detail = "Not applicable — gross payout tracking only"

    tax_ok = True
    if is_w2 and has_lines:
        pending = [
            ln
            for ln in lines
            if str(ln.get("tax_calc_status") or "") != "estimated"
        ]
        tax_ok = not pending
        tax_detail = (
            "Estimated withholding calculated for all lines"
            if tax_ok
            else f"{len(pending)} line(s) missing tax estimate"
        )
    else:
        tax_detail = "Not applicable — tax engine does not run for Temp/1099"

    export_ok = (
        has_lines
        and rate_ok
        and hours_reviewed_ok
        and (w4_ok if is_w2 else True)
        and (tax_ok if is_w2 else True)
    )
    if not has_lines:
        export_detail = "Add worker lines first"
    elif not rate_ok:
        export_detail = "Resolve missing hourly rates"
    elif not hours_reviewed_ok:
        export_detail = "Mark hours reviewed before export"
    elif is_w2 and not w4_ok:
        export_detail = "Complete W-4/payroll tax profiles"
    elif is_w2 and not tax_ok:
        export_detail = "Recalculate W-2 tax estimates"
    else:
        export_detail = "Ready for accountant CSV export"

    return [
        {
            "key": "worker_type",
            "label": "Worker type confirmed",
            "ok": bool(cat),
            "applicable": True,
            "detail": CATEGORY_LABELS.get(cat, cat or "Unset"),
        },
        {
            "key": "rate_present",
            "label": "Rate present",
            "ok": rate_ok,
            "applicable": True,
            "detail": "All lines have hourly rate" if rate_ok else f"{len(missing_rates)} missing rate(s)",
        },
        {
            "key": "hours_reviewed",
            "label": "Hours reviewed",
            "ok": hours_reviewed_ok,
            "applicable": True,
            "detail": f"Status: {st.replace('_', ' ')}",
        },
        {
            "key": "w4_profile",
            "label": "W-4/profile complete (W-2 only)",
            "ok": w4_ok if is_w2 else True,
            "applicable": is_w2,
            "detail": w4_detail,
        },
        {
            "key": "tax_estimate",
            "label": "Tax estimate calculated (W-2 only)",
            "ok": tax_ok if is_w2 else True,
            "applicable": is_w2,
            "detail": tax_detail,
        },
        {
            "key": "accountant_export",
            "label": "Accountant export ready",
            "ok": export_ok,
            "applicable": True,
            "detail": export_detail,
        },
        {
            "key": "paid_tracking",
            "label": "Paid/unpaid tracking available",
            "ok": True,
            "applicable": True,
            "detail": (
                "Mark paid after paystubs are finalized"
                if is_w2
                else "Mark paid after payment details are finalized"
            ),
        },
    ]


def aggregate_settled_employee_tax_and_net(
    lines: list[dict],
) -> tuple[Optional[float], Optional[float]]:
    """Sum employee withholding and net from enriched settlement fields.

    Uses line ``tax_withheld`` / ``net_paid`` set by ``enrich_line_settlement_fields``
    after payout details are finalized. Does **not** use employer taxes.

    Returns ``(None, None)`` when no line has settled fields yet (e.g. not finalized).
    """
    withheld_sum = 0.0
    net_sum = 0.0
    n_withheld = 0
    n_net = 0
    for ln in lines or []:
        if ln.get("tax_withheld") is not None and str(ln.get("tax_withheld")).strip() != "":
            withheld_sum += float(_money(ln.get("tax_withheld")))
            n_withheld += 1
        if ln.get("net_paid") is not None and str(ln.get("net_paid")).strip() != "":
            net_sum += float(_money(ln.get("net_paid")))
            n_net += 1
        elif ln.get("tax_withheld") is not None and str(ln.get("tax_withheld")).strip() != "":
            gross = float(_money(ln.get("gross_amount") or ln.get("total_amount") or 0))
            net_sum += round(gross - float(_money(ln.get("tax_withheld"))), 2)
            n_net += 1
    if n_withheld == 0 and n_net == 0:
        return None, None
    taxes = round(withheld_sum, 2) if n_withheld else 0.0
    net = round(net_sum, 2) if n_net else None
    return taxes, net


def apply_manual_tax_batch_summary_totals(
    batch: dict,
    *,
    gross_total: Optional[float] = None,
) -> dict:
    """Update ``batch['summary']`` tax withheld / net from settled employee lines.

    For W-2 under manual taxes: aggregate line withholding + net.
    For Temp/1099/tryout: keep net = gross and tax withheld unset (—).
    No-op when payout details are not yet finalized (no settled line fields).
    """
    summary = dict(batch.get("summary") or {})
    cat = str(batch.get("worker_category") or summary.get("worker_category") or "")
    lines = batch.get("lines") or []
    gross = float(
        _money(
            gross_total
            if gross_total is not None
            else summary.get("gross_total")
            or batch.get("total_payout_amount")
            or 0
        )
    )
    summary["gross_total"] = gross
    if not MANUAL_TAX_DEDUCTIONS_ONLY:
        batch["summary"] = summary
        return batch
    if cat != "w2":
        # Preserve intended Temp/1099 presentation: Tax — / Net = Gross.
        if summary.get("net_pay_total") is None:
            summary["net_pay_total"] = gross
        batch["summary"] = summary
        return batch
    settled_taxes, settled_net = aggregate_settled_employee_tax_and_net(lines)
    if settled_taxes is None and settled_net is None:
        batch["summary"] = summary
        return batch
    taxes = float(settled_taxes if settled_taxes is not None else 0.0)
    if settled_net is not None:
        net = float(settled_net)
    else:
        net = round(gross - taxes, 2)
    # Prefer line nets; if cents drift from gross - tax, keep line net authoritative.
    expected = round(gross - taxes, 2)
    if abs(expected - net) > 0.02 and settled_net is None:
        net = expected
    summary["taxes_withheld_total"] = taxes
    summary["net_pay_total"] = net
    batch["summary"] = summary
    return batch


def enrich_payout_batch(conn, organization_id: int, batch: dict) -> dict:
    """Attach workflow summary, warnings, and enriched line metadata."""
    if not batch:
        return batch
    ensure_payout_batch_line_extensions(conn.cursor())
    cat = str(batch.get("worker_category") or "")
    lines = batch.get("lines") or []
    missing_rates: list[dict] = []
    missing_w4: list[dict] = []
    enriched_lines = []
    gross_total = Decimal("0")
    paid_total = Decimal("0")
    unpaid_total = Decimal("0")
    for ln in lines:
        row = dict(ln)
        uid = row.get("user_id")
        if uid:
            from backend.payroll_payout_details import _user_display_meta

            meta = _user_display_meta(conn, int(uid))
            row["employee_id"] = meta["employee_id"]
            rate_info = resolve_worker_hourly_rate(conn, int(uid), organization_id)
            row["worker_category_label"] = rate_info["worker_category_label"]
            row["payment_method"] = row.get("payment_method") or rate_info.get("payment_method")
            if float(row.get("rate") or 0) <= 0 and not rate_info["rate_missing"]:
                row["suggested_rate"] = rate_info["hourly_rate"]
            if float(row.get("rate") or 0) <= 0:
                missing_rates.append(
                    {
                        "user_id": uid,
                        "worker_name": row.get("worker_name_snapshot"),
                        "suggested_rate": rate_info.get("hourly_rate"),
                        "rate_source": rate_info.get("rate_source"),
                    }
                )
            if cat == "w2":
                if not MANUAL_TAX_DEDUCTIONS_ONLY:
                    from backend.w2_payroll_tax_engine import fetch_employee_tax_profile

                    profile = fetch_employee_tax_profile(conn, int(uid), organization_id)
                    row["w4_summary"] = fetch_w4_compliance_summary(conn, int(uid), organization_id)
                    row["tax_disclaimer"] = ESTIMATE_DISCLAIMER
                    row["tax_calculation_status"] = row.get("tax_calc_status")
                    row["tax_notes"] = row.get("tax_calc_notes")
                    row["profile_incomplete_fields"] = profile.get("missing_fields") or []
                    row["estimated_withholding_notice"] = (
                        ESTIMATED_WITHHOLDING_NOTICE
                        if str(row.get("tax_calc_status") or "") == "estimated"
                        else ""
                    )
                    if not profile.get("w4_complete"):
                        missing_w4.append(
                            {
                                "user_id": uid,
                                "worker_name": row.get("worker_name_snapshot"),
                                "missing_fields": profile.get("missing_fields") or [],
                            }
                        )
                    _mask_incomplete_w2_line_taxes(row)
                from backend.payroll_accrual import get_sick_leave_balance

                sb = get_sick_leave_balance(conn, organization_id, int(uid))
                row["sick_balance_hours"] = sb.get("balance_hours")
                row["sick_hours_accrued_ytd"] = sb.get("ytd_accrued_hours")
                row["sick_hours_used_ytd"] = sb.get("ytd_used_hours")
        ps = str(row.get("payment_status") or "pending")
        from backend.payroll_payout_details import parse_line_payout_details
        from backend.payroll_worker_categories import (
            is_payment_recorded_paid,
            is_payment_recorded_unpaid,
            line_payment_recorded,
        )

        details_for_status = row.get("payout_details") or parse_line_payout_details(row)
        recorded = line_payment_recorded(row, details_for_status, batch)
        row["payment_recorded"] = recorded
        row["payment_status_label"] = _line_payment_status_label(
            recorded if recorded in ("paid", "unpaid") else ps
        )
        amt = _money(row.get("total_amount") or 0)
        gross_total += _money(row.get("gross_amount") or row.get("total_amount") or 0)
        if is_payment_recorded_paid(row, details_for_status, batch):
            paid_total += amt
        elif is_payment_recorded_unpaid(row, details_for_status, batch):
            unpaid_total += amt
        else:
            unpaid_total += amt
        from backend.payroll_payout_details import enrich_line_settlement_fields

        row = enrich_line_settlement_fields(row, batch)
        if cat == "w2" and not MANUAL_TAX_DEDUCTIONS_ONLY:
            if str(row.get("tax_calc_status") or "") == "estimated":
                emp_tax = _sum_estimated_tax_field([row], "total_employee_taxes")
                if emp_tax is None:
                    emp_tax = (
                        _sum_withholding([row], "federal_withholding")
                        + _sum_withholding([row], "state_withholding")
                        + _sum_withholding([row], "city_withholding")
                        + _sum_withholding([row], "social_security_withholding")
                        + _sum_withholding([row], "medicare_withholding")
                        + _sum_withholding([row], "additional_medicare_withholding")
                    )
                row["employee_taxes_total"] = emp_tax
                row["net_pay_display"] = float(row["net_pay"]) if row.get("net_pay") is not None else None
                row["net_pay_note"] = ESTIMATE_DISCLAIMER
            elif row.get("tax_calc_status") == "profile_incomplete":
                row["employee_taxes_total"] = None
                row["net_pay_display"] = None
                row["net_pay_note"] = row.get("tax_calc_notes") or "Complete W-4/payroll tax profile"
            else:
                row["employee_taxes_total"] = None
                row["net_pay_display"] = None
                row["net_pay_note"] = row.get("tax_calc_notes") or "Tax calculation pending"
        enriched_lines.append(json_safe(row))
    batch = dict(batch)
    batch["lines"] = enriched_lines
    batch["payment_status"] = _batch_payment_status(enriched_lines)
    net_total = (
        0
        if MANUAL_TAX_DEDUCTIONS_ONLY
        else sum(
            float(ln.get("net_pay"))
            for ln in enriched_lines
            if str(ln.get("tax_calc_status") or "") == "estimated" and ln.get("net_pay") is not None
        )
    )
    taxes_withheld_total = None if MANUAL_TAX_DEDUCTIONS_ONLY else _sum_estimated_tax_field(enriched_lines, "total_employee_taxes")
    if taxes_withheld_total is None and not MANUAL_TAX_DEDUCTIONS_ONLY:
        component_sum = (
            (_sum_estimated_tax_field(enriched_lines, "federal_withholding") or 0)
            + (_sum_estimated_tax_field(enriched_lines, "state_withholding") or 0)
            + (_sum_estimated_tax_field(enriched_lines, "city_withholding") or 0)
            + (_sum_estimated_tax_field(enriched_lines, "social_security_withholding") or 0)
            + (_sum_estimated_tax_field(enriched_lines, "medicare_withholding") or 0)
            + (_sum_estimated_tax_field(enriched_lines, "additional_medicare_withholding") or 0)
        )
        taxes_withheld_total = component_sum if component_sum > 0 else None
    employer_tax_total = None if MANUAL_TAX_DEDUCTIONS_ONLY else _sum_estimated_tax_field(enriched_lines, "total_employer_taxes")
    employer_cost_total = None if MANUAL_TAX_DEDUCTIONS_ONLY else _sum_estimated_tax_field(enriched_lines, "total_employer_cost")
    if MANUAL_TAX_DEDUCTIONS_ONLY:
        # Default: Temp/1099 net = gross; W-2 tax/net filled from settled lines below.
        net_pay_total = float(gross_total) if cat != "w2" else None
        taxes_withheld_total = None
    else:
        net_pay_total = (
            float(net_total)
            if cat == "w2" and net_total > 0
            else (float(gross_total) if cat != "w2" else None)
        )
    batch["summary"] = json_safe(
        {
            "worker_category": cat,
            "worker_category_label": CATEGORY_LABELS.get(cat, cat),
            "gross_total": float(gross_total),
            "taxes_withheld_total": taxes_withheld_total,
            "net_pay_total": net_pay_total,
            "net_pay_note": None if MANUAL_TAX_DEDUCTIONS_ONLY else (ESTIMATE_DISCLAIMER if cat == "w2" else None),
            "employer_taxes_total": employer_tax_total,
            "employer_cost_total": employer_cost_total,
            "payout_total": float(_money(batch.get("total_payout_amount") or 0)),
            "paid_amount": float(paid_total),
            "unpaid_amount": float(unpaid_total),
            "missing_rate_count": len(missing_rates),
            "missing_w4_count": 0 if MANUAL_TAX_DEDUCTIONS_ONLY else len(missing_w4),
        }
    )
    if MANUAL_TAX_DEDUCTIONS_ONLY:
        apply_manual_tax_batch_summary_totals(batch, gross_total=float(gross_total))
    warnings: list[str] = []
    if missing_rates:
        warnings.append(
            f"{len(missing_rates)} worker(s) have no hourly rate — set rate in Scheduling, "
            "Attendance Setup, employee profile, or contractor profile before approving the batch."
        )
    if not MANUAL_TAX_DEDUCTIONS_ONLY:
        if cat == "w2" and missing_w4:
            for m in missing_w4[:3]:
                fields = ", ".join(m.get("missing_fields") or ["W-4/payroll tax profile"])
                warnings.append(
                    f"W-2 {m.get('worker_name') or 'worker'} missing: {fields}"
                )
            if len(missing_w4) > 3:
                warnings.append(f"+{len(missing_w4) - 3} more W-2 worker(s) with incomplete tax profile.")
        if cat == "w2":
            warnings.append(ESTIMATE_DISCLAIMER)
            warnings.append(PAYROLL_ESTIMATE_PURPOSE)
        elif cat in ("temp", "contractor_1099", "tryout"):
            warnings.append("Temp/1099/Try Out batches track gross payout only — tax engine does not run.")
    batch["warnings"] = warnings
    batch["missing_rates"] = missing_rates
    batch["missing_w4"] = [] if MANUAL_TAX_DEDUCTIONS_ONLY else missing_w4
    batch["available_actions"] = _available_batch_actions(batch)
    batch["readiness"] = build_payroll_readiness(batch, cat, missing_rates, missing_w4, enriched_lines)
    batch["estimated_withholding_notice"] = None if MANUAL_TAX_DEDUCTIONS_ONLY else (ESTIMATED_WITHHOLDING_NOTICE if cat == "w2" else None)
    batch["payroll_estimate_purpose_notice"] = (
        MANUAL_DEDUCTIONS_NOTICE
        if MANUAL_TAX_DEDUCTIONS_ONLY and cat == "w2"
        else (
            PAYROLL_ESTIMATE_PURPOSE
            if cat == "w2"
            else "Gross payout tracking only — not a payroll tax filing engine."
        )
    )
    batch["manual_tax_deductions_only"] = MANUAL_TAX_DEDUCTIONS_ONLY
    batch["send_to_accountant_confirm_message"] = (
        SEND_TO_ACCOUNTANT_W2_CONFIRM if cat == "w2" else None
    )
    st = str(batch.get("status") or "")
    batch["accountant_ready_message"] = (
        ACCOUNTANT_BATCH_READY_MESSAGE
        if cat == "w2" and st in (
            "sent_to_accountant",
            "accountant_reviewed",
            "approved_for_payment",
            "paid",
            "closed",
        )
        else None
    )
    batch["accountant_processing_status"] = accountant_batch_processing_status(batch)
    batch["can_process_as_accountant"] = can_process_batch_as_accountant(batch)
    from backend.payroll_status_display import enrich_batch_payroll_display

    return enrich_batch_payroll_display(json_safe(batch))


def _available_batch_actions(batch: dict) -> list[str]:
    from backend.payroll_status_display import compute_display_status

    ds = compute_display_status(batch)
    cat = str(batch.get("worker_category") or "w2")
    st = str(batch.get("status") or "")
    actions: list[str] = []
    if ds == "draft":
        actions.append("approve_hours")
    elif ds == "ready_for_payroll":
        if cat == "w2" and st == "hours_reviewed":
            actions.append("send_to_accountant")
    elif ds == "ready_to_pay":
        actions.append("mark_paid")
        actions.append("mark_line_paid")
        actions.append("mark_line_unpaid")
    return actions


def validate_batch_for_workflow(batch: dict, action: str) -> None:
    missing = batch.get("missing_rates") or []
    if action in ("hours_reviewed", "send_to_accountant") and missing:
        names = ", ".join(m.get("worker_name") or "?" for m in missing[:5])
        extra = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        raise ValueError(f"Cannot proceed — missing hourly rate for: {names}{extra}")
    if action == "send_to_accountant" and str(batch.get("worker_category")) == "w2":
        if not MANUAL_TAX_DEDUCTIONS_ONLY:
            missing_w4 = batch.get("missing_w4") or []
            if missing_w4:
                parts = []
                for m in missing_w4[:3]:
                    fields = ", ".join(m.get("missing_fields") or ["tax profile"])
                    parts.append(f"{m.get('worker_name') or '?'} ({fields})")
                raise ValueError(
                    "Cannot send W-2 batch — incomplete tax profile for: " + "; ".join(parts)
                )
            incomplete_lines = [
                ln
                for ln in (batch.get("lines") or [])
                if str(ln.get("tax_calc_status") or "") == "profile_incomplete"
            ]
            if incomplete_lines:
                raise ValueError(
                    "Cannot send W-2 batch — tax estimates incomplete. Complete employee W-4/payroll profiles."
                )
    lines = batch.get("lines") or []
    if action in ("hours_reviewed", "send_to_accountant") and not lines:
        raise ValueError("Batch has no worker lines.")


def backfill_batch_line_rates(conn, organization_id: int, batch: dict) -> bool:
    """Persist scheduling/profile rates onto batch lines that still have rate=0."""
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        return False
    from backend.payroll_operations import update_payout_batch_line

    batch_id = int(batch["id"])
    updated = False
    for ln in batch.get("lines") or []:
        uid = ln.get("user_id")
        if not uid or float(ln.get("rate") or 0) > 0:
            continue
        rate = resolve_rate_for_batch_line(conn, organization_id, int(uid))
        if rate <= 0:
            continue
        update_payout_batch_line(
            conn,
            organization_id,
            batch_id,
            int(ln["id"]),
            {
                "approved_hours": ln.get("approved_hours"),
                "rate": rate,
                "adjustments": ln.get("adjustments") or 0,
                "line_status": ln.get("line_status") or "approved",
            },
        )
        updated = True
    if updated:
        conn.commit()
        recalculate_w2_batch_taxes(conn, organization_id, batch_id)
    return updated


def refresh_batch_line_rates(conn, organization_id: int, batch_id: int) -> dict:
    """Re-apply hourly rates from worker profiles onto batch lines."""
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        raise ValueError("Only draft or hours-reviewed batches can refresh rates")
    from backend.payroll_operations import update_payout_batch_line

    for ln in batch.get("lines") or []:
        uid = ln.get("user_id")
        if not uid:
            continue
        rate = resolve_rate_for_batch_line(conn, organization_id, int(uid))
        if rate <= 0:
            continue
        if float(ln.get("rate") or 0) <= 0 or float(ln.get("rate") or 0) != rate:
            update_payout_batch_line(
                conn,
                organization_id,
                batch_id,
                int(ln["id"]),
                {
                    "approved_hours": ln.get("approved_hours"),
                    "rate": rate,
                    "adjustments": ln.get("adjustments") or 0,
                    "line_status": ln.get("line_status") or "approved",
                },
            )
    recalculate_w2_batch_taxes(conn, organization_id, batch_id)
    out = get_payout_batch(conn, organization_id, batch_id) or {}
    return enrich_payout_batch(conn, organization_id, out)


def apply_batch_workflow_action(
    conn,
    organization_id: int,
    batch_id: int,
    action: str,
    *,
    actor_id: Optional[int] = None,
    line_id: Optional[int] = None,
    payment_date: Optional[str] = None,
    payment_reference: Optional[str] = None,
) -> dict:
    if action not in BATCH_ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    batch = enrich_payout_batch(conn, organization_id, batch)
    ensure_payout_batch_line_extensions(conn.cursor())
    c = conn.cursor()
    pd = payment_date or str(date.today())
    if action == "approve_hours":
        validate_batch_for_workflow(batch, "hours_reviewed")
        c.execute(
            """
            UPDATE payout_batches SET status='hours_reviewed', approved_by=COALESCE(approved_by, %s),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status='pending'
            """,
            (int(batch_id), int(organization_id)),
        )
        conn.commit()
        batch = get_payout_batch(conn, organization_id, batch_id)
        if not batch:
            raise ValueError("Batch not found")
        batch = enrich_payout_batch(conn, organization_id, batch)
        validate_batch_for_workflow(batch, "hours_reviewed")
        c.execute(
            """
            UPDATE payout_batches SET status='hours_reviewed', approved_by=COALESCE(approved_by, %s),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status='pending'
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "hours_reviewed":
        validate_batch_for_workflow(batch, action)
        c.execute(
            """
            UPDATE payout_batches SET status='hours_reviewed', approved_by=COALESCE(approved_by, %s),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status='pending'
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "send_to_accountant":
        if str(batch.get("worker_category")) != "w2":
            raise ValueError("Only W-2 batches use accountant review")
        if str(batch.get("status") or "") != "hours_reviewed":
            raise ValueError("Approve hours before sending to accountant")
        validate_batch_for_workflow(batch, action)
        c.execute(
            """
            UPDATE payout_batches SET status='sent_to_accountant',
            sent_to_accountant_at=COALESCE(sent_to_accountant_at, NOW()),
            approved_by=COALESCE(approved_by, %s), updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status IN ('pending', 'approved_unpaid')
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "revert_to_draft":
        st = str(batch.get("status") or "")
        if st not in REVERT_TO_DRAFT_STATUSES:
            raise ValueError(
                "Only draft-eligible batches can be reverted (hours reviewed or awaiting accountant)"
            )
        if batch.get("payout_details_finalized_at"):
            raise ValueError("Cannot revert — payroll details are already finalized")
        c.execute(
            """
            UPDATE payout_batches
            SET status='draft',
                sent_to_accountant_at=NULL,
                approved_by=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines
            SET payment_status='pending', line_status='draft'
            WHERE batch_id=%s AND organization_id=%s AND payment_status != 'paid'
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "process_batch":
        from backend.payroll_payout_details import can_process_accountant_batch

        if not actor_id or not can_process_accountant_batch(conn, int(actor_id)):
            raise ValueError("Only accountant role can process batches")
        if str(batch.get("status") or "") != "sent_to_accountant":
            raise ValueError("Batch must be available for accountant review before processing")
        c.execute(
            """
            UPDATE payout_batches SET status='approved_for_payment',
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "mark_paid":
        c.execute(
            """
            UPDATE payout_batches SET status='paid', paid_at=COALESCE(paid_at, NOW()),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='paid', payment_date=COALESCE(payment_date, %s),
            line_status='approved'
            WHERE batch_id=%s AND organization_id=%s
              AND payment_status NOT IN ('paid', 'unpaid')
            """,
            (pd, int(batch_id), int(organization_id)),
        )
    elif action == "mark_line_paid":
        if not line_id:
            raise ValueError("line_id required")
        from backend.payroll_payout_details import set_line_payment_recorded

        set_line_payment_recorded(
            conn,
            organization_id,
            batch_id,
            int(line_id),
            recorded="paid",
            actor_id=actor_id,
            payment_date=pd,
            payment_reference=payment_reference,
        )
        conn.commit()
        out = get_payout_batch(conn, organization_id, batch_id) or {}
        return enrich_payout_batch(conn, organization_id, out)
    elif action == "mark_line_unpaid":
        if not line_id:
            raise ValueError("line_id required")
        from backend.payroll_payout_details import set_line_payment_recorded

        set_line_payment_recorded(
            conn,
            organization_id,
            batch_id,
            int(line_id),
            recorded="unpaid",
            actor_id=actor_id,
        )
        conn.commit()
        out = get_payout_batch(conn, organization_id, batch_id) or {}
        return enrich_payout_batch(conn, organization_id, out)
    elif action == "refresh_rates":
        conn.commit()
        return refresh_batch_line_rates(conn, organization_id, batch_id)
    elif action == "recalculate_taxes":
        if MANUAL_TAX_DEDUCTIONS_ONLY:
            raise ValueError(
                "Automated tax calculation is disabled. Enter deductions in Payout Details."
            )
        if str(batch.get("worker_category")) != "w2":
            raise ValueError(
                "Tax recalculation applies to W-2 batches only. Temp/1099/Try Out remain gross payout tracking."
            )
        recalculate_w2_batch_taxes(conn, organization_id, batch_id)
        out = get_payout_batch(conn, organization_id, batch_id) or {}
        return enrich_payout_batch(conn, organization_id, out)
    conn.commit()
    out = get_payout_batch(conn, organization_id, batch_id) or {}
    return enrich_payout_batch(conn, organization_id, out)


def payroll_due_summary(
    conn,
    organization_id: int,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict:
    """Approved unpaid hours/value by worker category before batch creation."""
    if not payroll_profiles_active(conn):
        return {"categories": {}, "grand_total": 0, "grand_hours": 0, "workers": []}
    records = list_time_records(
        conn,
        organization_id,
        from_date=from_date,
        to_date=to_date,
        status_filter="approved",
        limit=5000,
    )
    by_cat: dict[str, dict] = {
        cat: {"hours": 0.0, "gross": 0.0, "workers": 0, "missing_rates": 0}
        for cat in WORKER_CATEGORIES
    }
    worker_map: dict[tuple[str, int], dict] = {}
    for rec in records:
        uid = int(rec["user_id"])
        cat = worker_category_for_user(conn, uid)
        hours = float(rec.get("approved_hours") or 0)
        rate_info = resolve_worker_hourly_rate(conn, uid, organization_id)
        rate = float(rate_info.get("hourly_rate") or 0)
        gross = round(hours * rate, 2)
        by_cat[cat]["hours"] += hours
        by_cat[cat]["gross"] += gross
        if rate_info.get("rate_missing"):
            by_cat[cat]["missing_rates"] += 1
        key = (cat, uid)
        if key not in worker_map:
            worker_map[key] = {
                "user_id": uid,
                "worker_name": rec.get("worker_name"),
                "worker_category": cat,
                "worker_category_label": CATEGORY_LABELS.get(cat, cat),
                "approved_hours": 0.0,
                "hourly_rate": rate if rate > 0 else None,
                "rate_missing": rate_info.get("rate_missing"),
                "rate_source": rate_info.get("rate_source"),
                "gross_due": 0.0,
                "payment_method": rate_info.get("payment_method"),
            }
        worker_map[key]["approved_hours"] += hours
        worker_map[key]["gross_due"] += gross
    for cat in by_cat:
        by_cat[cat]["workers"] = sum(
            1 for (c, _uid) in worker_map if c == cat
        )
        by_cat[cat]["hours"] = round(by_cat[cat]["hours"], 2)
        by_cat[cat]["gross"] = round(by_cat[cat]["gross"], 2)
    workers = sorted(worker_map.values(), key=lambda w: (w["worker_category"], w["worker_name"] or ""))
    grand_total = round(sum(by_cat[c]["gross"] for c in WORKER_CATEGORIES), 2)
    grand_hours = round(sum(by_cat[c]["hours"] for c in WORKER_CATEGORIES), 2)
    return json_safe(
        {
            "from_date": from_date,
            "to_date": to_date,
            "categories": {
                cat: {**by_cat[cat], "label": CATEGORY_LABELS.get(cat, cat)} for cat in WORKER_CATEGORIES
            },
            "grand_total": grand_total,
            "grand_hours": grand_hours,
            "workers": workers,
        }
    )


def worker_payment_overview(
    conn, organization_id: int, *, year: Optional[int] = None
) -> list[dict]:
    """Per-worker payout summary for payment history screen."""
    from backend.payroll_operations import accountant_ytd_summary

    year = int(year or date.today().year)
    ytd = accountant_ytd_summary(conn, organization_id, year=year)
    ensure_payout_batch_line_extensions(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pbl.user_id, pb.worker_category,
               SUM(CASE WHEN pbl.payment_status != 'paid' THEN pbl.total_amount ELSE 0 END) AS open_unpaid,
               MAX(CASE WHEN pbl.payment_status = 'paid' THEN pbl.payment_date END) AS last_paid
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.user_id IS NOT NULL
          AND pb.status NOT IN ('closed')
        GROUP BY pbl.user_id, pb.worker_category
        """,
        (int(organization_id),),
    )
    open_by_user = {
        (int(r["user_id"]), str(r["worker_category"])): r for r in c.fetchall() or []
    }
    out = []
    for row in ytd:
        uid = int(row["user_id"])
        cat = str(row["worker_category"])
        rate_info = resolve_worker_hourly_rate(conn, uid, organization_id)
        open_row = open_by_user.get((uid, cat)) or {}
        out.append(
            json_safe(
                {
                    **row,
                    "hourly_rate": rate_info.get("hourly_rate"),
                    "rate_missing": rate_info.get("rate_missing"),
                    "rate_source": rate_info.get("rate_source"),
                    "payment_method": rate_info.get("payment_method"),
                    "open_unpaid_amount": float(open_row.get("open_unpaid") or 0),
                    "last_payment_date": row.get("last_payment_date")
                    or (
                        str(open_row["last_paid"])[:10]
                        if open_row.get("last_paid")
                        else None
                    ),
                }
            )
        )
    return out


def resolve_rate_for_batch_line(
    conn, organization_id: int, user_id: int
) -> float:
    info = resolve_worker_hourly_rate(conn, user_id, organization_id)
    return float(info.get("hourly_rate") or 0)


def apply_w2_fields_on_line_insert(
    conn, user_id: int, worker_category: str, gross: float, organization_id: int = 0
) -> dict[str, Any]:
    if worker_category != "w2":
        return {"tax_calc_status": "not_applicable"}
    return prepare_w2_line_tax_fields(conn, user_id, gross, organization_id)
