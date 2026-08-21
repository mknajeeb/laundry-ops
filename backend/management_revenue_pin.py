"""PIN Revenue/Cash V3 — slim bootstrap and tab-scoped payloads.

Daily / DHS / Missing / Cash / Stats must not share one heavy bootstrap.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.business_time import business_today
from backend.daily_revenue_cost import _load_entry_lines, ensure_daily_revenue_cost_tables
from backend.management_revenue import (
    _cash_revenue_from_lines,
    _load_drc_lines_for_date,
    _money,
    _payout_row,
    ensure_management_revenue_tables,
)
from backend.management_revenue_accounts import build_account_revenue_day
from backend.management_revenue_obligations import (
    MISSING_WORK_START,
    build_daily_completeness,
    build_dhs_board,
    build_missing_work_summary_only,
)


def build_pin_bootstrap(cursor, org_id: int, processing_date: date) -> dict[str, Any]:
    """Lightweight shell for PIN unlock — Daily-ready, no Missing/Stats/DHS history."""
    ensure_management_revenue_tables(cursor)
    lines = _load_drc_lines_for_date(cursor, org_id, processing_date)
    # Account block only for non_rinse + rinse summaries (skip heavy DHS account calc if possible)
    account_block = build_account_revenue_day(cursor, org_id, processing_date, lines)
    daily = build_daily_completeness(cursor, org_id, processing_date)
    badges = build_missing_work_summary_only(cursor, org_id, as_of=processing_date)
    cash = _cash_revenue_from_lines(lines)
    cursor.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS paid
        FROM mgmt_cash_payouts
        WHERE organization_id = %s AND payout_date_et = %s
        """,
        (org_id, processing_date),
    )
    paid_row = cursor.fetchone() or {}
    paid = _money(paid_row.get("paid") if isinstance(paid_row, dict) else (paid_row[0] if paid_row else 0))
    return {
        "date_et": processing_date.isoformat(),
        "daily_completeness": daily,
        "non_rinse": account_block.get("non_rinse"),
        "rinse": {
            "wf": (account_block.get("rinse") or {}).get("wf"),
            "hd": (account_block.get("rinse") or {}).get("hd"),
        },
        "badges": {
            "missing_total": badges.get("missing_total", 0),
            "daily_missing": badges.get("daily_missing", 0),
            "dhs_pending": badges.get("dhs_pending", 0),
            "overdue": badges.get("overdue", 0),
        },
        "cash_today": {
            "cash_received": cash["total_cash_revenue"],
            "cash_paid_out": paid,
            "net_cash": _money(Decimal(str(cash["total_cash_revenue"])) - Decimal(str(paid))),
        },
    }


def build_daily_tab(cursor, org_id: int, processing_date: date) -> dict[str, Any]:
    """Daily tab only — SS / Drop Off / WF / HD for one Processing Date."""
    ensure_management_revenue_tables(cursor)
    lines = _load_drc_lines_for_date(cursor, org_id, processing_date)
    account_block = build_account_revenue_day(cursor, org_id, processing_date, lines)
    daily = build_daily_completeness(cursor, org_id, processing_date)
    return {
        "date_et": processing_date.isoformat(),
        "daily_completeness": daily,
        "non_rinse": account_block.get("non_rinse"),
        "rinse": {
            "wf": (account_block.get("rinse") or {}).get("wf"),
            "hd": (account_block.get("rinse") or {}).get("hd"),
        },
    }


def build_cash_tab(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Cash Paid Out history + today summary. Independent of Daily obligations."""
    ensure_management_revenue_tables(cursor)
    as_of = as_of or business_today()
    start = start or (as_of - timedelta(days=30))
    end = end or as_of
    if start < MISSING_WORK_START:
        # History can still show older payouts — cash is not Missing Work.
        pass
    cursor.execute(
        """
        SELECT id, payout_date_et, purpose, amount, note,
               entered_by_name_snapshot, created_at, updated_at
        FROM mgmt_cash_payouts
        WHERE organization_id = %s
          AND payout_date_et >= %s AND payout_date_et <= %s
        ORDER BY payout_date_et DESC, id DESC
        """,
        (org_id, start, end),
    )
    payouts = [_payout_row(dict(r)) for r in (cursor.fetchall() or [])]

    lines = _load_drc_lines_for_date(cursor, org_id, as_of)
    cash = _cash_revenue_from_lines(lines)
    today_paid = _money(
        sum(
            Decimal(str(p.get("amount") or 0))
            for p in payouts
            if str(p.get("payout_date_et") or "")[:10] == as_of.isoformat()
        )
    )
    return {
        "as_of": as_of.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": {
            "cash_received": cash["total_cash_revenue"],
            "cash_paid_out": today_paid,
            "net_cash": _money(Decimal(str(cash["total_cash_revenue"])) - Decimal(str(today_paid))),
        },
        "payouts": payouts,
    }


def build_dhs_tab(cursor, org_id: int, as_of: date | None = None) -> dict[str, Any]:
    return build_dhs_board(cursor, org_id, as_of=as_of or business_today())
