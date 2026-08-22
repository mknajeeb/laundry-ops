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
    period: str | None = None,
) -> dict[str, Any]:
    """Cash ledger summary + payouts for a period. Independent of Daily obligations."""
    from backend.management_revenue import build_cash_activity, _period_bounds

    ensure_management_revenue_tables(cursor)
    as_of = as_of or business_today()
    period = (period or "month").strip().lower()
    if start and end:
        pass
    else:
        start, end = _period_bounds(period, as_of, start, end)

    activity = build_cash_activity(cursor, org_id, period if period != "custom" else "custom", as_of, start, end)
    return {
        "as_of": as_of.isoformat(),
        "period": period,
        "start": activity.get("start_date"),
        "end": activity.get("end_date"),
        "summary": {
            "cash_received": activity.get("total_cash_revenue"),
            "cash_paid_out": activity.get("cash_paid_out"),
            "net_cash": activity.get("net_cash_movement"),
        },
        # Legacy today key for older clients
        "today": {
            "cash_received": activity.get("total_cash_revenue"),
            "cash_paid_out": activity.get("cash_paid_out"),
            "net_cash": activity.get("net_cash_movement"),
        },
        "payouts": (activity.get("cash_out") or {}).get("payouts") or activity.get("payouts") or [],
    }


def build_stream_tab(
    cursor,
    org_id: int,
    *,
    stream: str,
    as_of: date | None = None,
    period: str = "month",
) -> dict[str, Any]:
    """Lightweight Self Service / Drop Off / WF / HD period summary + recent days + today entry."""
    from backend.management_revenue import _load_drc_lines_for_date, _money, _period_bounds
    from backend.management_revenue_accounts import build_account_revenue_day
    from backend.management_revenue_obligations import build_daily_completeness

    ensure_management_revenue_tables(cursor)
    as_of = as_of or business_today()
    stream = (stream or "").strip().lower()
    if stream not in ("self_service", "drop_off", "rinse_wf", "rinse_hd"):
        raise ValueError("Invalid stream")
    start, end = _period_bounds(period, as_of, None, None)

    days_complete = 0
    revenue_total = Decimal("0")
    cash_total = Decimal("0")
    card_total = Decimal("0")
    volume_total = Decimal("0")
    recent: list[dict[str, Any]] = []

    day = start
    while day <= end and day <= as_of:
        lines = _load_drc_lines_for_date(cursor, org_id, day)
        block = build_account_revenue_day(cursor, org_id, day, lines)
        if stream in ("self_service", "drop_off"):
            row = (block.get("non_rinse") or {}).get(stream) or {}
            cash = Decimal(str(row.get("cash") if row.get("cash") is not None else 0))
            card = Decimal(str(row.get("card") if row.get("card") is not None else 0))
            rev = Decimal(str(row.get("total") if row.get("total") is not None else (cash + card)))
            entered = row.get("cash") is not None or row.get("card") is not None or row.get("total") is not None
            if entered:
                days_complete += 1
                cash_total += cash
                card_total += card
                revenue_total += rev
                recent.append({
                    "date_et": day.isoformat(),
                    "cash": _money(cash),
                    "card": _money(card),
                    "total": _money(rev),
                    "status": "entered",
                })
        else:
            key = "wf" if stream == "rinse_wf" else "hd"
            row = (block.get("rinse") or {}).get(key) or {}
            rev = row.get("revenue")
            vol = row.get("volume_lbs") or row.get("lbs")
            entered = rev is not None or vol is not None
            if entered:
                days_complete += 1
                if rev is not None:
                    revenue_total += Decimal(str(rev))
                if vol is not None:
                    volume_total += Decimal(str(vol))
                recent.append({
                    "date_et": day.isoformat(),
                    "volume_lbs": float(vol) if vol is not None else None,
                    "revenue": _money(rev) if rev is not None else None,
                    "status": "entered",
                })
        day += timedelta(days=1)

    recent = list(reversed(recent[-14:]))  # newest first, capped

    today_lines = _load_drc_lines_for_date(cursor, org_id, as_of)
    today_block = build_account_revenue_day(cursor, org_id, as_of, today_lines)
    daily = build_daily_completeness(cursor, org_id, as_of)

    entry = None
    if stream in ("self_service", "drop_off"):
        entry = (today_block.get("non_rinse") or {}).get(stream)
    elif stream == "rinse_wf":
        entry = (today_block.get("rinse") or {}).get("wf")
    else:
        entry = (today_block.get("rinse") or {}).get("hd")

    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    period_label = f"{months[start.month - 1]} {start.year}" if period == "month" else f"{start.isoformat()} → {end.isoformat()}"

    summary = {
        "period": period,
        "period_label": period_label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "revenue": _money(revenue_total),
        "days_complete": days_complete,
    }
    if stream in ("self_service", "drop_off"):
        summary["cash"] = _money(cash_total)
        summary["card"] = _money(card_total)
    else:
        summary["volume_lbs"] = float(volume_total)

    return {
        "stream": stream,
        "as_of": as_of.isoformat(),
        "summary": summary,
        "entry": entry,
        "recent": recent,
        "daily_completeness": daily,
        "non_rinse": today_block.get("non_rinse"),
        "rinse": {
            "wf": (today_block.get("rinse") or {}).get("wf"),
            "hd": (today_block.get("rinse") or {}).get("hd"),
        },
    }


def build_dhs_tab(cursor, org_id: int, as_of: date | None = None) -> dict[str, Any]:
    return build_dhs_board(cursor, org_id, as_of=as_of or business_today())
