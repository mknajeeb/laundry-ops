"""Management Hub — Revenue & Cash compartment.

Reuses DRC line storage for non-rinse cash/card entry. HD revenue is read-only
from hd_day_bag_production. Cash payouts are stored separately (not negative revenue).
"""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.business_time import business_today
from backend.daily_operations_hd import compute_hd_day_revenue_totals
from backend.daily_revenue_cost import (
    _line_amount,
    _load_entry_lines,
    _money,
    ensure_daily_revenue_cost_tables,
    get_daily_entry,
    save_daily_entry,
)
from backend.daily_revenue_cost_constants import (
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
)
from backend.ta_helpers import table_exists

def ensure_management_revenue_tables(cursor) -> None:
    if table_exists(cursor, "mgmt_cash_payouts"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mgmt_cash_payouts (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          payout_date_et DATE NOT NULL,
          purpose VARCHAR(255) NOT NULL,
          amount DECIMAL(12,2) NOT NULL,
          note VARCHAR(512) NULL,
          entered_by_user_id INT NULL,
          entered_by_name_snapshot VARCHAR(255) NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_mgmt_cash_payout_org_date (organization_id, payout_date_et)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mgmt_cash_payout_audits (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          payout_id BIGINT NOT NULL,
          organization_id INT NOT NULL,
          action VARCHAR(32) NOT NULL,
          actor_user_id INT NULL,
          actor_name_snapshot VARCHAR(255) NULL,
          before_json JSON NULL,
          after_json JSON NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_mgmt_cash_payout_audit_payout (payout_id),
          INDEX idx_mgmt_cash_payout_audit_org (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _period_bounds(
    period: str,
    ref_date: date,
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date]:
    p = (period or "today").strip().lower()
    if p == "custom" and start and end:
        return start, end
    if p == "week":
        week_start = ref_date - timedelta(days=ref_date.weekday())
        return week_start, week_start + timedelta(days=6)
    if p == "month":
        last_day = monthrange(ref_date.year, ref_date.month)[1]
        return ref_date.replace(day=1), ref_date.replace(day=last_day)
    return ref_date, ref_date


def _cash_revenue_from_lines(lines: dict[str, dict]) -> dict[str, float]:
    ss_cash = _money(_line_amount(lines, LK_SELF_SERVICE_CASH))
    ss_card = _money(_line_amount(lines, LK_SELF_SERVICE_CARD))
    do_cash = _money(_line_amount(lines, LK_DROP_OFF_CASH))
    do_card = _money(_line_amount(lines, LK_DROP_OFF_CARD))
    return {
        "self_service_cash": ss_cash,
        "self_service_card": ss_card,
        "drop_off_cash": do_cash,
        "drop_off_card": do_card,
        "self_service_total": _money(Decimal(str(ss_cash)) + Decimal(str(ss_card))),
        "drop_off_total": _money(Decimal(str(do_cash)) + Decimal(str(do_card))),
        "total_cash_revenue": _money(
            Decimal(str(ss_cash)) + Decimal(str(do_cash))
        ),
    }


def _load_drc_lines_for_date(cursor, org_id: int, entry_date: date) -> dict[str, dict]:
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT id FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    row = cursor.fetchone()
    if not row:
        return {}
    entry_id = int(row["id"] if isinstance(row, dict) else row[0])
    return _load_entry_lines(cursor, entry_id)


def build_revenue_day(cursor, org_id: int, entry_date: date) -> dict[str, Any]:
    """Single-day revenue view for Management Revenue entry."""
    ensure_management_revenue_tables(cursor)
    drc = get_daily_entry(cursor, org_id, entry_date)
    entry = drc.get("entry") or {}
    lines = _load_drc_lines_for_date(cursor, org_id, entry_date)
    cash = _cash_revenue_from_lines(lines)

    hd_totals = compute_hd_day_revenue_totals(cursor, org_id, entry_date)
    hd_revenue = _money(hd_totals.get("complete_hd_revenue") or hd_totals.get("total_hd_revenue") or 0)
    hd_orders = int(hd_totals.get("complete") or 0)

    non_rinse_total = _money(
        Decimal(str(cash["self_service_total"]))
        + Decimal(str(cash["drop_off_total"]))
    )

    cursor.execute(
        """
        SELECT id, payout_date_et, purpose, amount, note,
               entered_by_name_snapshot, created_at, updated_at
        FROM mgmt_cash_payouts
        WHERE organization_id = %s AND payout_date_et = %s
        ORDER BY id
        """,
        (org_id, entry_date),
    )
    payouts = [dict(r) for r in (cursor.fetchall() or [])]
    paid_out = _money(sum(Decimal(str(p.get("amount") or 0)) for p in payouts))

    return {
        "date_et": entry_date.isoformat(),
        "entry_id": entry.get("id"),
        "entry_status": entry.get("status") or "open",
        "rinse": {
            "wf": {
                "placeholder": True,
                "revenue": None,
                "note": "WF revenue calculation will be supplied later.",
            },
            "hd": {
                "source": "hd_day_bag_production",
                "orders": hd_orders,
                "revenue": hd_revenue,
                "read_only": True,
            },
        },
        "non_rinse": {
            "self_service": {
                "cash": cash["self_service_cash"],
                "card": cash["self_service_card"],
                "total": cash["self_service_total"],
            },
            "drop_off": {
                "cash": cash["drop_off_cash"],
                "card": cash["drop_off_card"],
                "total": cash["drop_off_total"],
            },
            "total": non_rinse_total,
        },
        "cash_payouts": payouts,
        "cash_activity": {
            "self_service_cash": cash["self_service_cash"],
            "drop_off_cash": cash["drop_off_cash"],
            "total_cash_revenue": cash["total_cash_revenue"],
            "cash_paid_out": paid_out,
            "net_cash_movement": _money(
                Decimal(str(cash["total_cash_revenue"])) - Decimal(str(paid_out))
            ),
        },
    }


def save_non_rinse_revenue(
    cursor,
    org_id: int,
    entry_date: date,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Write Self Service / Drop Off cash+card via existing DRC storage."""
    existing = get_daily_entry(cursor, org_id, entry_date)
    entry = existing.get("entry") or {}
    save_payload = {
        "self_service_cash": payload.get("self_service_cash", entry.get("self_service_cash") or 0),
        "self_service_card": payload.get("self_service_card", entry.get("self_service_card") or 0),
        "drop_off_cash": payload.get("drop_off_cash", entry.get("drop_off_cash") or 0),
        "drop_off_card": payload.get("drop_off_card", entry.get("drop_off_card") or 0),
        "rinse_wf_pounds": entry.get("rinse_wf_pounds") or 0,
        "rinse_hd_orders": entry.get("rinse_hd_orders") or 0,
        "rinse_hd_revenue": entry.get("rinse_hd_revenue") or 0,
        "rinse_wi_orders": entry.get("rinse_wi_orders") or 0,
        "rinse_wi_revenue": entry.get("rinse_wi_revenue") or 0,
        "payroll_total": entry.get("payroll_total") or 0,
        "commercial_lines": entry.get("commercial_lines") or [],
    }
    save_daily_entry(cursor, org_id, entry_date, save_payload, user_id=user_id)
    return build_revenue_day(cursor, org_id, entry_date)


def _payout_row(row: dict) -> dict[str, Any]:
    ed = row.get("payout_date_et")
    return {
        "id": int(row["id"]),
        "date_et": ed.isoformat() if hasattr(ed, "isoformat") else str(ed),
        "purpose": row.get("purpose") or "",
        "amount": _money(row.get("amount")),
        "note": row.get("note"),
        "entered_by": row.get("entered_by_name_snapshot"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _log_payout_audit(
    cursor,
    *,
    payout_id: int,
    org_id: int,
    action: str,
    actor_user_id: int | None,
    actor_name: str | None,
    before: dict | None,
    after: dict | None,
) -> None:
    cursor.execute(
        """
        INSERT INTO mgmt_cash_payout_audits
          (payout_id, organization_id, action, actor_user_id, actor_name_snapshot, before_json, after_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            payout_id,
            org_id,
            action,
            actor_user_id,
            actor_name,
            json.dumps(before) if before else None,
            json.dumps(after) if after else None,
        ),
    )


def create_cash_payout(
    cursor,
    org_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    ensure_management_revenue_tables(cursor)
    payout_date = payload.get("date_et") or business_today()
    if isinstance(payout_date, str):
        payout_date = date.fromisoformat(payout_date[:10])
    purpose = str(payload.get("purpose") or "").strip()
    if not purpose:
        raise ValueError("Purpose is required")
    amount = _money(payload.get("amount"))
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    note = str(payload.get("note") or "").strip() or None
    cursor.execute(
        """
        INSERT INTO mgmt_cash_payouts
          (organization_id, payout_date_et, purpose, amount, note, entered_by_user_id, entered_by_name_snapshot)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (org_id, payout_date, purpose, amount, note, user_id, actor_name),
    )
    payout_id = int(cursor.lastrowid)
    after = {
        "date_et": payout_date.isoformat(),
        "purpose": purpose,
        "amount": amount,
        "note": note,
    }
    _log_payout_audit(
        cursor,
        payout_id=payout_id,
        org_id=org_id,
        action="created",
        actor_user_id=user_id,
        actor_name=actor_name,
        before=None,
        after=after,
    )
    cursor.execute("SELECT * FROM mgmt_cash_payouts WHERE id = %s", (payout_id,))
    return _payout_row(dict(cursor.fetchone()))


def update_cash_payout(
    cursor,
    org_id: int,
    payout_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    ensure_management_revenue_tables(cursor)
    cursor.execute(
        "SELECT * FROM mgmt_cash_payouts WHERE id = %s AND organization_id = %s",
        (payout_id, org_id),
    )
    row = cursor.fetchone()
    if not row:
        raise LookupError("Cash payout not found")
    before_row = dict(row)
    before = _payout_row(before_row)

    payout_date = payload.get("date_et") or before_row.get("payout_date_et")
    if isinstance(payout_date, str):
        payout_date = date.fromisoformat(payout_date[:10])
    purpose = str(payload.get("purpose") if "purpose" in payload else before_row.get("purpose") or "").strip()
    if not purpose:
        raise ValueError("Purpose is required")
    amount = _money(payload.get("amount") if "amount" in payload else before_row.get("amount"))
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    note_raw = payload.get("note") if "note" in payload else before_row.get("note")
    note = str(note_raw or "").strip() or None

    cursor.execute(
        """
        UPDATE mgmt_cash_payouts
        SET payout_date_et = %s, purpose = %s, amount = %s, note = %s
        WHERE id = %s AND organization_id = %s
        """,
        (payout_date, purpose, amount, note, payout_id, org_id),
    )
    after = {
        "date_et": payout_date.isoformat() if hasattr(payout_date, "isoformat") else str(payout_date),
        "purpose": purpose,
        "amount": amount,
        "note": note,
    }
    _log_payout_audit(
        cursor,
        payout_id=payout_id,
        org_id=org_id,
        action="updated",
        actor_user_id=user_id,
        actor_name=actor_name,
        before=before,
        after=after,
    )
    cursor.execute("SELECT * FROM mgmt_cash_payouts WHERE id = %s", (payout_id,))
    return _payout_row(dict(cursor.fetchone()))


def delete_cash_payout(
    cursor,
    org_id: int,
    payout_id: int,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    ensure_management_revenue_tables(cursor)
    cursor.execute(
        "SELECT * FROM mgmt_cash_payouts WHERE id = %s AND organization_id = %s",
        (payout_id, org_id),
    )
    row = cursor.fetchone()
    if not row:
        raise LookupError("Cash payout not found")
    before = _payout_row(dict(row))
    cursor.execute(
        "DELETE FROM mgmt_cash_payouts WHERE id = %s AND organization_id = %s",
        (payout_id, org_id),
    )
    _log_payout_audit(
        cursor,
        payout_id=payout_id,
        org_id=org_id,
        action="deleted",
        actor_user_id=user_id,
        actor_name=actor_name,
        before=before,
        after=None,
    )


def list_cash_payout_audits(cursor, org_id: int, payout_id: int) -> list[dict]:
    ensure_management_revenue_tables(cursor)
    cursor.execute(
        """
        SELECT id, action, actor_name_snapshot, before_json, after_json, created_at
        FROM mgmt_cash_payout_audits
        WHERE organization_id = %s AND payout_id = %s
        ORDER BY id
        """,
        (org_id, payout_id),
    )
    out = []
    for row in cursor.fetchall() or []:
        r = dict(row)
        out.append(
            {
                "id": int(r["id"]),
                "action": r.get("action"),
                "actor": r.get("actor_name_snapshot"),
                "before": json.loads(r["before_json"]) if r.get("before_json") else None,
                "after": json.loads(r["after_json"]) if r.get("after_json") else None,
                "created_at": r.get("created_at"),
            }
        )
    return out


def build_cash_activity(
    cursor,
    org_id: int,
    period: str,
    ref_date: date,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    ensure_management_revenue_tables(cursor)
    start_date, end_date = _period_bounds(period, ref_date, start, end)

    totals = {
        "self_service_cash": Decimal("0"),
        "drop_off_cash": Decimal("0"),
        "total_cash_revenue": Decimal("0"),
        "cash_paid_out": Decimal("0"),
    }
    daily = []
    day = start_date
    while day <= end_date:
        lines = _load_drc_lines_for_date(cursor, org_id, day)
        cash = _cash_revenue_from_lines(lines)
        cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS paid
            FROM mgmt_cash_payouts
            WHERE organization_id = %s AND payout_date_et = %s
            """,
            (org_id, day),
        )
        paid_row = cursor.fetchone()
        paid = Decimal(str((paid_row or {}).get("paid") or 0))
        ss = Decimal(str(cash["self_service_cash"]))
        do = Decimal(str(cash["drop_off_cash"]))
        rev = Decimal(str(cash["total_cash_revenue"]))
        totals["self_service_cash"] += ss
        totals["drop_off_cash"] += do
        totals["total_cash_revenue"] += rev
        totals["cash_paid_out"] += paid
        daily.append(
            {
                "date_et": day.isoformat(),
                "self_service_cash": _money(ss),
                "drop_off_cash": _money(do),
                "total_cash_revenue": _money(rev),
                "cash_paid_out": _money(paid),
                "net_cash_movement": _money(rev - paid),
            }
        )
        day += timedelta(days=1)

    net = totals["total_cash_revenue"] - totals["cash_paid_out"]
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "self_service_cash": _money(totals["self_service_cash"]),
        "drop_off_cash": _money(totals["drop_off_cash"]),
        "total_cash_revenue": _money(totals["total_cash_revenue"]),
        "cash_paid_out": _money(totals["cash_paid_out"]),
        "net_cash_movement": _money(net),
        "daily": daily,
    }
