"""
Payroll accrual: W-2 sick leave (NYC/NY) and 1099/temp health credit.

Internal tracking only — verify with accountant/payroll provider.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from backend.payroll_tax_settings import fetch_payroll_tax_settings
from backend.ta_helpers import json_safe, table_exists, table_has_column

ACCRUAL_DISCLAIMER = (
    "Estimated/internal payroll tracking — verify with accountant/payroll provider."
)
HEALTH_CREDIT_DISCLAIMER = (
    "Health / attendance credit is an internal discretionary payment tracking field. "
    "It does not classify the worker as a W-2 employee and should be verified with "
    "accountant/legal advisor."
)
SICK_LEAVE_TYPES = ("SICK_LEAVE",)
HEALTH_CREDIT_TYPES = ("HEALTH_CREDIT",)
LINE_TYPES = ("REGULAR", "SICK_PAY", "HEALTH_CREDIT")


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def _q2(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _q4(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _cursor(conn_or_cursor, dictionary: bool = True):
    """Accept either a mysql connection or an existing cursor."""
    if hasattr(conn_or_cursor, "fetchone"):
        return conn_or_cursor
    return conn_or_cursor.cursor(dictionary=dictionary)


def _connection(conn_or_cursor):
    """Return the connection object for APIs that need conn.cursor()."""
    if hasattr(conn_or_cursor, "fetchone"):
        return getattr(conn_or_cursor, "connection", None) or conn_or_cursor
    return conn_or_cursor


def ensure_payroll_accrual_ledger(conn_or_cursor) -> None:
    c = _cursor(conn_or_cursor)
    if table_exists(c, "payroll_accrual_ledger"):
        return
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_accrual_ledger (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            user_id INT NOT NULL,
            worker_type VARCHAR(32) NOT NULL,
            accrual_type VARCHAR(32) NOT NULL,
            payroll_batch_id INT NULL,
            payout_batch_line_id INT NULL,
            attendance_record_id BIGINT NULL,
            period_start DATE NULL,
            period_end DATE NULL,
            hours_worked_basis DECIMAL(10,2) NULL,
            amount_or_hours_accrued DECIMAL(10,4) NULL,
            amount_or_hours_used DECIMAL(10,4) NULL,
            balance_after DECIMAL(10,4) NULL,
            manual_adjustment TINYINT(1) NOT NULL DEFAULT 0,
            reversed TINYINT(1) NOT NULL DEFAULT 0,
            reversal_of_id BIGINT NULL,
            admin_note TEXT NULL,
            created_by INT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_pal_org_user_type (organization_id, user_id, accrual_type),
            INDEX idx_pal_batch (payroll_batch_id),
            INDEX idx_pal_line (payout_batch_line_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_payout_line_accrual_columns(conn_or_cursor) -> None:
    c = _cursor(conn_or_cursor)
    if not table_exists(c, "payout_batch_lines"):
        return
    extras = [
        ("ot_hours", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("ot_rate", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("sick_hours_accrued", "DECIMAL(10,4) NOT NULL DEFAULT 0"),
        ("sick_hours_used", "DECIMAL(10,4) NOT NULL DEFAULT 0"),
        ("sick_pay_amount", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("health_credit_amount", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("bonus_tip_amount", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("reimbursement_amount", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("line_type", "VARCHAR(32) NOT NULL DEFAULT 'REGULAR'"),
        ("ny_pfl_deduction", "DECIMAL(10,2) NULL"),
        ("ny_dbl_deduction", "DECIMAL(10,2) NULL"),
    ]
    for col, typedef in extras:
        if not table_has_column(c, "payout_batch_lines", col):
            c.execute(
                f"ALTER TABLE payout_batch_lines ADD COLUMN {col} {typedef}"
            )


def sick_leave_annual_cap(settings: dict[str, Any]) -> Decimal:
    cap = _d(settings.get("sick_leave_annual_cap_hours") or 40)
    large_cap = _d(settings.get("sick_leave_annual_cap_hours_large_employer") or 56)
    threshold = int(settings.get("sick_leave_large_employer_threshold") or 100)
    emp_count = int(settings.get("_employee_count_override") or settings.get("w2_employee_count") or 0)
    if emp_count >= threshold:
        return large_cap
    return cap


def calculate_sick_hours_accrued(
    eligible_hours: Decimal,
    *,
    ytd_accrued: Decimal,
    annual_cap: Decimal,
) -> Decimal:
    """1 hour per 30 hours worked; respect annual cap."""
    if eligible_hours <= 0:
        return Decimal("0")
    earned = eligible_hours / Decimal("30")
    room = max(Decimal("0"), annual_cap - ytd_accrued)
    return min(earned, room)


def calculate_health_credit_amount(
    settings: dict[str, Any],
    *,
    worker_category: str,
    eligible_hours: Decimal,
    has_approved_hours: bool,
    manual_amount: Optional[Decimal] = None,
) -> Decimal:
    cat = str(worker_category or "")
    if cat == "contractor_1099" and not settings.get("health_credit_enabled_for_1099", True):
        return Decimal("0")
    if cat == "temp" and not settings.get("health_credit_enabled_for_temp", True):
        return Decimal("0")
    method = str(settings.get("health_credit_accrual_method") or "manual_only").lower()
    if method == "manual_only":
        return max(Decimal("0"), _d(manual_amount))
    amount = Decimal("0")
    if method == "per_hour":
        rate = _d(settings.get("health_credit_rate_per_hour") or 0)
        amount = eligible_hours * rate
    elif method == "flat_per_period":
        if has_approved_hours and eligible_hours > 0:
            amount = _d(settings.get("health_credit_flat_amount_per_period") or 0)
    cap_period = settings.get("health_credit_cap_per_period")
    if cap_period is not None:
        amount = min(amount, _d(cap_period))
    return max(Decimal("0"), amount)


def get_ledger_ytd_totals(
    conn_or_cursor,
    organization_id: int,
    user_id: int,
    accrual_type: str,
    year: int,
) -> dict[str, Decimal]:
    c = _cursor(conn_or_cursor)
    ensure_payroll_accrual_ledger(c)
    c.execute(
        """
        SELECT
          COALESCE(SUM(amount_or_hours_accrued), 0) AS accrued,
          COALESCE(SUM(amount_or_hours_used), 0) AS used
        FROM payroll_accrual_ledger
        WHERE organization_id=%s AND user_id=%s AND accrual_type=%s
          AND reversed=0 AND YEAR(COALESCE(period_end, created_at))=%s
        """,
        (int(organization_id), int(user_id), accrual_type, int(year)),
    )
    row = c.fetchone() or {}
    return {
        "accrued": _d(row.get("accrued")),
        "used": _d(row.get("used")),
    }


def get_sick_leave_balance(
    conn_or_cursor, organization_id: int, user_id: int, *, year: Optional[int] = None
) -> dict[str, Any]:
    year = int(year or date.today().year)
    c = _cursor(conn_or_cursor)
    ensure_payroll_accrual_ledger(c)
    c.execute(
        """
        SELECT balance_after FROM payroll_accrual_ledger
        WHERE organization_id=%s AND user_id=%s AND accrual_type='SICK_LEAVE' AND reversed=0
        ORDER BY id DESC LIMIT 1
        """,
        (int(organization_id), int(user_id)),
    )
    row = c.fetchone() or {}
    balance = _d(row.get("balance_after"))
    ytd = get_ledger_ytd_totals(c, organization_id, user_id, "SICK_LEAVE", year)
    settings = fetch_payroll_tax_settings(_connection(conn_or_cursor), organization_id)
    return json_safe(
        {
            "balance_hours": _q2(balance),
            "ytd_accrued_hours": _q2(ytd["accrued"]),
            "ytd_used_hours": _q2(ytd["used"]),
            "annual_cap_hours": _q2(sick_leave_annual_cap(settings)),
            "accrual_rate_label": "1 hour per 30 hours worked",
            "policy_label": "NYC/NY Paid Sick Leave",
            "disclaimer": ACCRUAL_DISCLAIMER,
            "carryover_enabled": bool(settings.get("sick_leave_carryover_enabled", True)),
        }
    )


def insert_ledger_entry(
    conn_or_cursor,
    *,
    organization_id: int,
    user_id: int,
    worker_type: str,
    accrual_type: str,
    payroll_batch_id: Optional[int] = None,
    payout_batch_line_id: Optional[int] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    hours_worked_basis: Optional[float] = None,
    amount_or_hours_accrued: Optional[float] = None,
    amount_or_hours_used: Optional[float] = None,
    balance_after: Optional[float] = None,
    manual_adjustment: bool = False,
    admin_note: Optional[str] = None,
    created_by: Optional[int] = None,
) -> int:
    c = _cursor(conn_or_cursor)
    ensure_payroll_accrual_ledger(c)
    c.execute(
        """
        INSERT INTO payroll_accrual_ledger (
          organization_id, user_id, worker_type, accrual_type,
          payroll_batch_id, payout_batch_line_id, period_start, period_end,
          hours_worked_basis, amount_or_hours_accrued, amount_or_hours_used,
          balance_after, manual_adjustment, admin_note, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(user_id),
            worker_type,
            accrual_type,
            payroll_batch_id,
            payout_batch_line_id,
            period_start,
            period_end,
            hours_worked_basis,
            amount_or_hours_accrued,
            amount_or_hours_used,
            balance_after,
            1 if manual_adjustment else 0,
            admin_note,
            created_by,
        ),
    )
    return int(c.lastrowid)


def reverse_ledger_entries_for_line(
    conn_or_cursor,
    organization_id: int,
    line_id: int,
    *,
    created_by: Optional[int] = None,
) -> int:
    c = _cursor(conn_or_cursor)
    ensure_payroll_accrual_ledger(c)
    c.execute(
        """
        SELECT * FROM payroll_accrual_ledger
        WHERE organization_id=%s AND payout_batch_line_id=%s AND reversed=0
        """,
        (int(organization_id), int(line_id)),
    )
    rows = list(c.fetchall() or [])
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        bal = _d(row.get("balance_after"))
        acc = _d(row.get("amount_or_hours_accrued"))
        used = _d(row.get("amount_or_hours_used"))
        reversal_balance = bal - acc + used
        insert_ledger_entry(
            c,
            organization_id=organization_id,
            user_id=int(row["user_id"]),
            worker_type=str(row["worker_type"]),
            accrual_type=str(row["accrual_type"]),
            payroll_batch_id=row.get("payroll_batch_id"),
            payout_batch_line_id=int(line_id),
            amount_or_hours_accrued=_q4(-acc) if acc else None,
            amount_or_hours_used=_q4(-used) if used else None,
            balance_after=_q4(reversal_balance),
            admin_note=f"Reversal of ledger #{row.get('id')} (line recalculated)",
            created_by=created_by,
        )
        c.execute(
            "UPDATE payroll_accrual_ledger SET reversed=1 WHERE id=%s",
            (int(row["id"]),),
        )
        count += 1
    return count


def reverse_ledger_entries_for_batch(
    conn_or_cursor,
    organization_id: int,
    batch_id: int,
    *,
    created_by: Optional[int] = None,
) -> int:
    """Reverse accrual entries for a batch (audit trail preserved)."""
    c = _cursor(conn_or_cursor)
    ensure_payroll_accrual_ledger(c)
    c.execute(
        """
        SELECT * FROM payroll_accrual_ledger
        WHERE organization_id=%s AND payroll_batch_id=%s AND reversed=0
        """,
        (int(organization_id), int(batch_id)),
    )
    rows = list(c.fetchall() or [])
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        bal = _d(row.get("balance_after"))
        acc = _d(row.get("amount_or_hours_accrued"))
        used = _d(row.get("amount_or_hours_used"))
        reversal_balance = bal - acc + used
        insert_ledger_entry(
            c,
            organization_id=organization_id,
            user_id=int(row["user_id"]),
            worker_type=str(row["worker_type"]),
            accrual_type=str(row["accrual_type"]),
            payroll_batch_id=batch_id,
            payout_batch_line_id=row.get("payout_batch_line_id"),
            period_start=str(row.get("period_start") or "")[:10] or None,
            period_end=str(row.get("period_end") or "")[:10] or None,
            amount_or_hours_accrued=_q4(-acc) if acc else None,
            amount_or_hours_used=_q4(-used) if used else None,
            balance_after=_q4(reversal_balance),
            manual_adjustment=False,
            admin_note=f"Reversal of ledger #{row.get('id')} (batch deleted/reversed)",
            created_by=created_by,
        )
        c.execute(
            "UPDATE payroll_accrual_ledger SET reversed=1 WHERE id=%s",
            (int(row["id"]),),
        )
        count += 1
    return count


def process_w2_line_accruals(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    batch_id: int,
    line_id: int,
    regular_hours: Decimal,
    ot_hours: Decimal,
    sick_hours_used: Decimal,
    hourly_rate: Decimal,
    period_start: Optional[str],
    period_end: Optional[str],
    allow_sick_over_balance: bool = False,
    sick_override_note: Optional[str] = None,
    created_by: Optional[int] = None,
    ot_hourly_rate: Optional[Decimal] = None,
) -> dict[str, Any]:
    """Accrue sick leave and compute sick pay for one W-2 batch line."""
    from backend.payroll_overtime import compute_wage_with_overtime

    settings = fetch_payroll_tax_settings(cursor, organization_id)
    year = int(str(period_end or date.today())[:4])
    ytd = get_ledger_ytd_totals(cursor, organization_id, user_id, "SICK_LEAVE", year)
    cap = sick_leave_annual_cap(settings)

    # Eligible: regular + OT; sick pay hours do not accrue additional sick leave
    eligible = regular_hours + ot_hours
    sick_accrued = calculate_sick_hours_accrued(
        eligible, ytd_accrued=ytd["accrued"], annual_cap=cap
    )

    bal_info = get_sick_leave_balance(cursor, organization_id, user_id, year=year)
    balance = _d(bal_info["balance_hours"])

    if sick_hours_used > 0 and sick_hours_used > balance and not allow_sick_over_balance:
        raise ValueError(
            f"Sick hours used ({_q2(sick_hours_used)}) exceeds available balance ({_q2(balance)})"
        )
    if sick_hours_used > balance and allow_sick_over_balance and not (sick_override_note or "").strip():
        raise ValueError("Admin note required when overriding sick balance limit")

    sick_pay = sick_hours_used * hourly_rate if hourly_rate > 0 else Decimal("0")
    new_balance = balance + sick_accrued - sick_hours_used

    if sick_accrued > 0:
        insert_ledger_entry(
            cursor,
            organization_id=organization_id,
            user_id=user_id,
            worker_type="w2",
            accrual_type="SICK_LEAVE",
            payroll_batch_id=batch_id,
            payout_batch_line_id=line_id,
            period_start=period_start,
            period_end=period_end,
            hours_worked_basis=_q2(eligible),
            amount_or_hours_accrued=_q4(sick_accrued),
            balance_after=_q4(new_balance),
            admin_note=sick_override_note,
            created_by=created_by,
        )
    if sick_hours_used > 0:
        insert_ledger_entry(
            cursor,
            organization_id=organization_id,
            user_id=user_id,
            worker_type="w2",
            accrual_type="SICK_LEAVE",
            payroll_batch_id=batch_id,
            payout_batch_line_id=line_id,
            period_start=period_start,
            period_end=period_end,
            amount_or_hours_used=_q4(sick_hours_used),
            balance_after=_q4(new_balance),
            manual_adjustment=allow_sick_over_balance,
            admin_note=sick_override_note or "Sick pay usage",
            created_by=created_by,
        )

    # OT hours are paid at OT rate (default 1.5×), not regular rate.
    gross = compute_wage_with_overtime(
        regular_hours,
        ot_hours,
        hourly_rate,
        ot_hourly_rate,
        sick_pay=sick_pay,
    )
    return {
        "sick_hours_accrued": _q4(sick_accrued),
        "sick_hours_used": _q4(sick_hours_used),
        "sick_pay_amount": _q2(sick_pay),
        "sick_balance_after": _q2(new_balance),
        "gross_wages": _q2(gross),
        "eligible_hours": _q2(eligible),
    }


def process_contractor_line_health_credit(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    worker_category: str,
    batch_id: int,
    line_id: int,
    eligible_hours: Decimal,
    manual_health_credit: Optional[Decimal] = None,
    manual_note: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    created_by: Optional[int] = None,
) -> dict[str, Any]:
    settings = fetch_payroll_tax_settings(cursor, organization_id)
    amount = calculate_health_credit_amount(
        settings,
        worker_category=worker_category,
        eligible_hours=eligible_hours,
        has_approved_hours=eligible_hours > 0,
        manual_amount=manual_health_credit,
    )
    if amount > 0:
        insert_ledger_entry(
            cursor,
            organization_id=organization_id,
            user_id=user_id,
            worker_type=worker_category,
            accrual_type="HEALTH_CREDIT",
            payroll_batch_id=batch_id,
            payout_batch_line_id=line_id,
            period_start=period_start,
            period_end=period_end,
            hours_worked_basis=_q2(eligible_hours),
            amount_or_hours_accrued=_q2(amount),
            balance_after=_q2(amount),
            manual_adjustment=manual_health_credit is not None,
            admin_note=manual_note,
            created_by=created_by,
        )
    return {
        "health_credit_amount": _q2(amount),
        "disclaimer": HEALTH_CREDIT_DISCLAIMER,
    }


def manual_sick_adjustment(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    hours_delta: Decimal,
    admin_note: str,
    created_by: Optional[int] = None,
) -> dict[str, Any]:
    if not (admin_note or "").strip():
        raise ValueError("Admin note required for manual sick leave adjustment")
    bal_info = get_sick_leave_balance(cursor, organization_id, user_id)
    balance = _d(bal_info["balance_hours"])
    new_balance = balance + hours_delta
    accrued = hours_delta if hours_delta > 0 else None
    used = -hours_delta if hours_delta < 0 else None
    insert_ledger_entry(
        cursor,
        organization_id=organization_id,
        user_id=user_id,
        worker_type="w2",
        accrual_type="SICK_LEAVE",
        amount_or_hours_accrued=_q4(accrued) if accrued else None,
        amount_or_hours_used=_q4(used) if used else None,
        balance_after=_q4(new_balance),
        manual_adjustment=True,
        admin_note=admin_note,
        created_by=created_by,
    )
    return get_sick_leave_balance(cursor, organization_id, user_id)
