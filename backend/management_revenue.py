"""Management Hub — Revenue & Cash compartment.

Reuses DRC line storage for non-rinse cash/card and DHS commercial entry.
HD revenue is read-only from hd_day_bag_production (canonical writable HD source).
Cash payouts are stored separately (not negative revenue).

Legacy DRC lines revenue.rinse_hd.* may still exist historically / on DRC Daily Entry.
Do not write HD revenue from Management into those lines — retire that path later by
making DRC HD fields read-only from production (no destructive migration).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.business_time import business_today
from backend.daily_revenue_cost import (
    _line_amount,
    _load_entry_lines,
    _log_audit,
    _money,
    _upsert_line,
    ensure_daily_revenue_cost_tables,
)
from backend.daily_revenue_cost_constants import (
    ENTRY_STATUS_OPEN,
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    SOURCE_MANUAL,
)
from backend.daily_revenue_cost_schema import assert_entry_editable
from backend.ta_helpers import table_exists
from backend.management_revenue_accounts import (
    build_account_revenue_day,
    build_revenue_dashboard,
    save_dhs_account_revenue,
)

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
    from backend.management_revenue_accounts import _period_bounds_extended

    return _period_bounds_extended(period, ref_date, start, end)


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


def _load_entry_header(cursor, org_id: int, entry_date: date) -> dict | None:
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT id, status FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def build_revenue_day(cursor, org_id: int, entry_date: date) -> dict[str, Any]:
    """Single-day revenue view for Management Revenue entry.

    Does not call DRC get_daily_entry (payroll + at-vendor workload rebuild).
    """
    ensure_management_revenue_tables(cursor)
    header = _load_entry_header(cursor, org_id, entry_date)
    lines = _load_drc_lines_for_date(cursor, org_id, entry_date)
    account_block = build_account_revenue_day(cursor, org_id, entry_date, lines)

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

    cash = _cash_revenue_from_lines(lines)
    payout_rows = [_payout_row(p) for p in payouts]
    from backend.management_revenue_obligations import build_daily_completeness, build_missing_work

    daily_completeness = build_daily_completeness(cursor, org_id, entry_date)
    missing = build_missing_work(cursor, org_id, as_of=entry_date, filter_kind="all")
    dhs_due = missing["summary"]["dhs_pending"]
    dhs_complete = max(
        0,
        len([a for a in (account_block.get("dhs") or {}).get("accounts") or [] if a.get("entered")]),
    )
    return {
        "date_et": entry_date.isoformat(),
        "entry_id": header.get("id") if header else None,
        "entry_status": (header or {}).get("status") or "open",
        **account_block,
        "cash_payouts": payout_rows,
        "cash_activity": {
            "self_service_cash": cash["self_service_cash"],
            "drop_off_cash": cash["drop_off_cash"],
            "total_cash_revenue": cash["total_cash_revenue"],
            "cash_paid_out": paid_out,
            "net_cash_movement": _money(
                Decimal(str(cash["total_cash_revenue"])) - Decimal(str(paid_out))
            ),
            "payout_count": len(payout_rows),
        },
        "daily_completeness": daily_completeness,
        "missing_work_summary": missing["summary"],
        "section_status": {
            "sections": [
                {
                    "id": s["key"],
                    "entered": s["status"] == "entered",
                    "status": s["status"],
                    "required": True,
                    "label": s["label"],
                }
                for s in daily_completeness["sections"]
            ],
            "complete": daily_completeness["complete"],
            "required": daily_completeness["required"],
            "label": daily_completeness["label"],
        },
        "dhs_completeness": {
            "due": dhs_due,
            "complete": dhs_complete,
            "pending": dhs_due,
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
    """Write Self Service / Drop Off cash+card only.

    Does not run DRC save_daily_entry (payroll, at-vendor workload, costs, commercial).
    Null/blank field values mean not entered — lines are skipped (left untouched) when
    omitted; explicit null clears to no-write of that key only when provided as null
    with intent to clear — we treat null as skip/keep existing to avoid accidental wipe.
    Explicit 0 is stored as 0.
    """
    ensure_management_revenue_tables(cursor)
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    header = cursor.fetchone()
    assert_entry_editable(header, payload)

    if header:
        entry_id = int(header["id"])
        existing_lines = _load_entry_lines(cursor, entry_id)
        cursor.execute(
            "UPDATE dr_daily_entries SET modified_by = %s WHERE id = %s",
            (user_id, entry_id),
        )
        was_existing = True
    else:
        cursor.execute(
            """
            INSERT INTO dr_daily_entries
              (organization_id, entry_date, status, created_by, modified_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (org_id, entry_date, ENTRY_STATUS_OPEN, user_id, user_id),
        )
        entry_id = int(cursor.lastrowid)
        existing_lines = {}
        _log_audit(cursor, entry_id, "created", actor_user_id=user_id)
        was_existing = False

    for line_key, payload_key in (
        (LK_SELF_SERVICE_CASH, "self_service_cash"),
        (LK_SELF_SERVICE_CARD, "self_service_card"),
        (LK_DROP_OFF_CASH, "drop_off_cash"),
        (LK_DROP_OFF_CARD, "drop_off_card"),
    ):
        if payload_key not in payload:
            continue
        raw = payload.get(payload_key)
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            # Explicit clear: leave line absent / do not upsert zero
            continue
        amount = _money(raw)
        _upsert_line(
            cursor,
            entry_id,
            line_key,
            "revenue",
            amount,
            None,
            source_system=SOURCE_MANUAL,
            user_id=user_id,
            existing_lines=existing_lines,
        )

    if was_existing:
        _log_audit(cursor, entry_id, "updated", actor_user_id=user_id)
    return build_revenue_day(cursor, org_id, entry_date)


def _payout_row(row: dict) -> dict[str, Any]:
    ed = row.get("payout_date_et")
    created = row.get("created_at")
    updated = row.get("updated_at")
    date_et = ed.isoformat() if hasattr(ed, "isoformat") else str(ed)
    return {
        "id": int(row["id"]),
        "date_et": date_et,
        "payout_business_date": date_et,
        "purpose": row.get("purpose") or "",
        "amount": _money(row.get("amount")),
        "note": row.get("note"),
        "entered_by": row.get("entered_by_name_snapshot"),
        "entered_by_user_id": row.get("entered_by_user_id"),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
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
    raw_date = payload.get("payout_business_date") or payload.get("date_et") or payload.get("payout_date_et")
    if not raw_date:
        raise ValueError("Payout Date is required")
    if isinstance(raw_date, str):
        payout_date = date.fromisoformat(raw_date[:10])
    else:
        payout_date = raw_date
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
        "payout_business_date": payout_date.isoformat(),
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

    payout_date = payload.get("payout_business_date") or payload.get("date_et") or before_row.get("payout_date_et")
    if isinstance(payout_date, str):
        payout_date = date.fromisoformat(payout_date[:10])
    if not payout_date:
        raise ValueError("Payout Date is required")
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
    cursor.execute(
        """
        SELECT id, payout_date_et, purpose, amount, note,
               entered_by_name_snapshot, entered_by_user_id, created_at, updated_at
        FROM mgmt_cash_payouts
        WHERE organization_id = %s AND payout_date_et BETWEEN %s AND %s
        ORDER BY payout_date_et DESC, id DESC
        """,
        (org_id, start_date, end_date),
    )
    payouts = [_payout_row(dict(r)) for r in (cursor.fetchall() or [])]
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "self_service_cash": _money(totals["self_service_cash"]),
        "drop_off_cash": _money(totals["drop_off_cash"]),
        "total_cash_revenue": _money(totals["total_cash_revenue"]),
        "cash_in": {
            "self_service": _money(totals["self_service_cash"]),
            "drop_off": _money(totals["drop_off_cash"]),
            "total": _money(totals["total_cash_revenue"]),
        },
        "cash_out": {
            "payouts": payouts,
            "total": _money(totals["cash_paid_out"]),
        },
        "cash_paid_out": _money(totals["cash_paid_out"]),
        "net_cash_movement": _money(net),
        "payouts": payouts,
        "daily": daily,
    }
