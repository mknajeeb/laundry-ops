"""Management Revenue — account registry, effective-dated pricing, and hierarchy."""

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
    _line_qty,
    _load_entry_lines,
    _money,
    ensure_daily_revenue_cost_tables,
    get_daily_entry,
    save_daily_entry,
    wf_revenue_for_day,
)
from backend.daily_revenue_cost_constants import (
    BILLING_FLAT,
    BILLING_PER_LB,
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_RINSE_WF_POUNDS,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    commercial_amount_key,
    commercial_pounds_key,
)
from backend.daily_revenue_cost_schema import upsert_entry_line
from backend.ta_helpers import table_exists

REVENUE_GROUP_RINSE_WF = "rinse_wf"
REVENUE_GROUP_RINSE_HD = "rinse_hd"
REVENUE_GROUP_NON_RINSE = "non_rinse"
REVENUE_GROUP_DHS = "dhs"

REVENUE_MODE_CALCULATED = "calculated"
REVENUE_MODE_ABSOLUTE = "absolute"

PRICING_FLAT_LB = "flat_lb"
PRICING_TIERED_LB = "tiered_lb"
PRICING_FLAT_AMOUNT = "flat_amount"
PRICING_PER_ORDER = "per_order"

DHS_SUB_ACCOUNTS = ("Auburn", "Clarkson", "Bellevue", "Skillman", "Bedford")

SEED_ACCOUNTS = (
    {"account_code": "dhs", "name": "DHS", "revenue_group": REVENUE_GROUP_DHS, "is_parent": True},
    {"account_code": "rinse_wf", "name": "Rinse WF", "revenue_group": REVENUE_GROUP_RINSE_WF, "revenue_mode": REVENUE_MODE_CALCULATED},
    {"account_code": "rinse_hd", "name": "Rinse HD", "revenue_group": REVENUE_GROUP_RINSE_HD, "revenue_mode": REVENUE_MODE_CALCULATED},
    {"account_code": "self_service", "name": "Self Service", "revenue_group": REVENUE_GROUP_NON_RINSE, "revenue_mode": REVENUE_MODE_ABSOLUTE, "service_type": "self_service"},
    {"account_code": "drop_off", "name": "Drop Off", "revenue_group": REVENUE_GROUP_NON_RINSE, "revenue_mode": REVENUE_MODE_ABSOLUTE, "service_type": "drop_off"},
)


def ensure_mgmt_revenue_account_tables(cursor) -> None:
    if table_exists(cursor, "mgmt_revenue_accounts"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mgmt_revenue_accounts (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          parent_id BIGINT NULL,
          account_code VARCHAR(64) NULL,
          name VARCHAR(255) NOT NULL,
          revenue_group VARCHAR(32) NOT NULL,
          service_type VARCHAR(64) NULL,
          revenue_mode VARCHAR(32) NOT NULL DEFAULT 'calculated',
          active TINYINT(1) NOT NULL DEFAULT 1,
          start_date DATE NULL,
          end_date DATE NULL,
          dr_commercial_account_id INT NULL,
          notes TEXT NULL,
          sort_order INT NOT NULL DEFAULT 0,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_mgmt_rev_acct_org_code (organization_id, account_code),
          INDEX idx_mgmt_rev_acct_org_group (organization_id, revenue_group),
          INDEX idx_mgmt_rev_acct_parent (parent_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mgmt_revenue_pricing_schedules (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          account_id BIGINT NOT NULL,
          effective_from DATE NOT NULL,
          effective_to DATE NULL,
          pricing_method VARCHAR(32) NOT NULL,
          pricing_unit VARCHAR(32) NOT NULL DEFAULT 'lbs',
          rate_per_unit DECIMAL(12,4) NULL,
          tiers_json JSON NULL,
          created_by INT NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_mgmt_rev_price_acct (account_id, effective_from),
          INDEX idx_mgmt_rev_price_active (account_id, effective_from, effective_to)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _d(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _pricing_row_to_dict(row: dict) -> dict[str, Any]:
    tiers_raw = row.get("tiers_json")
    tiers = json.loads(tiers_raw) if isinstance(tiers_raw, str) else (tiers_raw or [])
    return {
        "id": int(row["id"]),
        "account_id": int(row["account_id"]),
        "effective_from": row["effective_from"].isoformat() if hasattr(row["effective_from"], "isoformat") else str(row["effective_from"]),
        "effective_to": row["effective_to"].isoformat() if row.get("effective_to") and hasattr(row["effective_to"], "isoformat") else None,
        "pricing_method": row.get("pricing_method") or PRICING_FLAT_LB,
        "pricing_unit": row.get("pricing_unit") or "lbs",
        "rate_per_unit": float(row["rate_per_unit"]) if row.get("rate_per_unit") is not None else None,
        "tiers": tiers or [],
    }


def get_pricing_for_account(cursor, account_id: int, as_of: date | None = None) -> dict | None:
    as_of = as_of or business_today()
    cursor.execute(
        """
        SELECT * FROM mgmt_revenue_pricing_schedules
        WHERE account_id = %s
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (account_id, as_of, as_of),
    )
    row = cursor.fetchone()
    return _pricing_row_to_dict(dict(row)) if row else None


def _account_row_to_dict(row: dict, pricing: dict | None = None) -> dict[str, Any]:
    sd = row.get("start_date")
    ed = row.get("end_date")
    return {
        "id": int(row["id"]),
        "parent_id": int(row["parent_id"]) if row.get("parent_id") else None,
        "account_code": row.get("account_code"),
        "name": row.get("name") or "",
        "revenue_group": row.get("revenue_group") or "",
        "service_type": row.get("service_type"),
        "revenue_mode": row.get("revenue_mode") or REVENUE_MODE_CALCULATED,
        "active": bool(row.get("active")),
        "start_date": sd.isoformat() if hasattr(sd, "isoformat") else sd,
        "end_date": ed.isoformat() if hasattr(ed, "isoformat") else ed,
        "dr_commercial_account_id": int(row["dr_commercial_account_id"]) if row.get("dr_commercial_account_id") else None,
        "notes": row.get("notes"),
        "sort_order": int(row.get("sort_order") or 0),
        "pricing": pricing,
    }


def list_accounts(cursor, org_id: int, *, as_of: date | None = None, active_only: bool = False) -> list[dict]:
    ensure_mgmt_revenue_account_tables(cursor)
    seed_mgmt_revenue_accounts(cursor, org_id)
    as_of = as_of or business_today()
    sql = "SELECT * FROM mgmt_revenue_accounts WHERE organization_id = %s"
    params: list[Any] = [org_id]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY sort_order, name"
    cursor.execute(sql, tuple(params))
    out = []
    for row in cursor.fetchall() or []:
        acct = dict(row)
        pricing = get_pricing_for_account(cursor, int(acct["id"]), as_of)
        out.append(_account_row_to_dict(acct, pricing))
    return out


def _ensure_dr_commercial_account(cursor, org_id: int, name: str) -> int:
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT id FROM dr_commercial_accounts WHERE organization_id = %s AND name = %s",
        (org_id, name),
    )
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])
    cursor.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM dr_commercial_accounts WHERE organization_id = %s",
        (org_id,),
    )
    sort_order = int((cursor.fetchone() or {}).get("n") or 0)
    cursor.execute(
        "INSERT INTO dr_commercial_accounts (organization_id, name, active, sort_order) VALUES (%s, %s, 1, %s)",
        (org_id, name, sort_order),
    )
    return int(cursor.lastrowid)


def _insert_account(
    cursor,
    org_id: int,
    *,
    account_code: str | None,
    name: str,
    revenue_group: str,
    parent_id: int | None = None,
    revenue_mode: str = REVENUE_MODE_CALCULATED,
    service_type: str | None = None,
    dr_commercial_account_id: int | None = None,
    sort_order: int = 0,
) -> int:
    eff = business_today()
    cursor.execute(
        """
        INSERT INTO mgmt_revenue_accounts
          (organization_id, parent_id, account_code, name, revenue_group, service_type,
           revenue_mode, active, start_date, dr_commercial_account_id, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s)
        """,
        (org_id, parent_id, account_code, name, revenue_group, service_type, revenue_mode, eff, dr_commercial_account_id, sort_order),
    )
    return int(cursor.lastrowid)


def _insert_pricing(
    cursor,
    account_id: int,
    *,
    effective_from: date,
    pricing_method: str,
    pricing_unit: str = "lbs",
    rate_per_unit: float | None = None,
    tiers: list[dict] | None = None,
    user_id: int | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO mgmt_revenue_pricing_schedules
          (account_id, effective_from, pricing_method, pricing_unit, rate_per_unit, tiers_json, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            account_id,
            effective_from,
            pricing_method,
            pricing_unit,
            rate_per_unit,
            json.dumps(tiers) if tiers else None,
            user_id,
        ),
    )


def seed_mgmt_revenue_accounts(cursor, org_id: int, *, user_id: int | None = None) -> None:
    ensure_mgmt_revenue_account_tables(cursor)
    cursor.execute("SELECT COUNT(*) AS c FROM mgmt_revenue_accounts WHERE organization_id = %s", (org_id,))
    if int((cursor.fetchone() or {}).get("c") or 0) > 0:
        return

    eff = business_today()
    parent_ids: dict[str, int] = {}

    for spec in SEED_ACCOUNTS:
        acct_id = _insert_account(
            cursor,
            org_id,
            account_code=spec["account_code"],
            name=spec["name"],
            revenue_group=spec["revenue_group"],
            revenue_mode=spec.get("revenue_mode", REVENUE_MODE_CALCULATED),
            service_type=spec.get("service_type"),
            sort_order=len(parent_ids),
        )
        parent_ids[spec["account_code"]] = acct_id

        if spec["account_code"] == "rinse_wf":
            _insert_pricing(
                cursor,
                acct_id,
                effective_from=eff,
                pricing_method=PRICING_TIERED_LB,
                pricing_unit="lbs",
                tiers=[
                    {"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.0},
                    {"tier_number": 2, "max_lbs": None, "rate_per_lb": 0.95},
                ],
                user_id=user_id,
            )
        elif spec["account_code"] == "rinse_hd":
            _insert_pricing(
                cursor,
                acct_id,
                effective_from=eff,
                pricing_method=PRICING_PER_ORDER,
                pricing_unit="orders",
                user_id=user_id,
            )

    dhs_parent_id = parent_ids["dhs"]
    for i, sub_name in enumerate(DHS_SUB_ACCOUNTS):
        dr_name = f"DHS - {sub_name}"
        dr_id = _ensure_dr_commercial_account(cursor, org_id, dr_name)
        sub_id = _insert_account(
            cursor,
            org_id,
            account_code=f"dhs_{sub_name.lower()}",
            name=sub_name,
            revenue_group=REVENUE_GROUP_DHS,
            parent_id=dhs_parent_id,
            revenue_mode=REVENUE_MODE_CALCULATED,
            dr_commercial_account_id=dr_id,
            sort_order=i,
        )
        _insert_pricing(
            cursor,
            sub_id,
            effective_from=eff,
            pricing_method=PRICING_FLAT_LB,
            pricing_unit="lbs",
            rate_per_unit=0.95,
            user_id=user_id,
        )


def _wf_tiers_from_pricing(pricing: dict | None) -> list[dict]:
    if not pricing or pricing.get("pricing_method") != PRICING_TIERED_LB:
        return []
    tiers = pricing.get("tiers") or []
    return [
        {
            "tier_number": int(t.get("tier_number") or i + 1),
            "max_lbs": t.get("max_lbs"),
            "rate_per_lb": float(t.get("rate_per_lb") or 0),
        }
        for i, t in enumerate(tiers)
    ]


def _calc_account_revenue(
    *,
    revenue_mode: str,
    volume: float,
    pricing: dict | None,
    stored_amount: float | None = None,
) -> float:
    if revenue_mode == REVENUE_MODE_ABSOLUTE:
        return _money(stored_amount or 0)
    if not pricing:
        return _money(stored_amount or 0)
    method = pricing.get("pricing_method") or PRICING_FLAT_LB
    if method == PRICING_FLAT_LB:
        rate = float(pricing.get("rate_per_unit") or 0)
        return _money(_d(volume) * _d(rate))
    if method == PRICING_FLAT_AMOUNT:
        return _money(pricing.get("rate_per_unit") or stored_amount or 0)
    return _money(stored_amount or 0)


def _period_bounds_extended(
    period: str,
    ref_date: date,
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date]:
    p = (period or "today").strip().lower()
    if p == "custom" and start and end:
        return start, end
    if p == "yesterday":
        d = ref_date - timedelta(days=1)
        return d, d
    if p == "week":
        week_start = ref_date - timedelta(days=ref_date.weekday())
        return week_start, week_start + timedelta(days=6)
    if p == "previous_week":
        week_start = ref_date - timedelta(days=ref_date.weekday() + 7)
        return week_start, week_start + timedelta(days=6)
    if p == "month":
        last_day = monthrange(ref_date.year, ref_date.month)[1]
        return ref_date.replace(day=1), ref_date.replace(day=last_day)
    if p == "previous_month":
        first_this = ref_date.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return ref_date, ref_date


def build_account_revenue_day(
    cursor,
    org_id: int,
    entry_date: date,
    lines: dict[str, dict],
) -> dict[str, Any]:
    """Hierarchical revenue block for one business day."""
    accounts = list_accounts(cursor, org_id, as_of=entry_date, active_only=True)
    by_code = {a.get("account_code"): a for a in accounts if a.get("account_code")}

    ss_cash = _money(_line_amount(lines, LK_SELF_SERVICE_CASH))
    ss_card = _money(_line_amount(lines, LK_SELF_SERVICE_CARD))
    do_cash = _money(_line_amount(lines, LK_DROP_OFF_CASH))
    do_card = _money(_line_amount(lines, LK_DROP_OFF_CARD))
    ss_total = _money(_d(ss_cash) + _d(ss_card))
    do_total = _money(_d(do_cash) + _d(do_card))

    wf_acct = by_code.get("rinse_wf") or {}
    wf_pricing = wf_acct.get("pricing")
    wf_tiers = _wf_tiers_from_pricing(wf_pricing)
    wf_pounds = _money(_line_qty(lines, LK_RINSE_WF_POUNDS))
    wf_enabled = bool(wf_tiers)
    wf_revenue = None
    wf_meta: dict[str, Any] = {}
    if wf_enabled and wf_pounds:
        wf_revenue, wf_meta = wf_revenue_for_day(
            cursor, org_id, entry_date, wf_pounds, wf_tiers,
        )
    elif wf_enabled:
        wf_revenue = 0.0

    hd_totals = compute_hd_day_revenue_totals(cursor, org_id, entry_date)
    hd_revenue = _money(hd_totals.get("complete_hd_revenue") or hd_totals.get("total_hd_revenue") or 0)
    hd_orders = int(hd_totals.get("complete") or 0)

    dhs_rows = []
    dhs_total = Decimal("0")
    dhs_parent = by_code.get("dhs")
    for acct in accounts:
        if acct.get("revenue_group") != REVENUE_GROUP_DHS or not acct.get("parent_id"):
            continue
        if dhs_parent and acct.get("parent_id") != dhs_parent.get("id"):
            continue
        cid = acct.get("dr_commercial_account_id")
        if not cid:
            continue
        pk = commercial_pounds_key(cid)
        ak = commercial_amount_key(cid)
        volume = _money(_line_qty(lines, pk))
        stored = _line_amount(lines, ak)
        revenue = _calc_account_revenue(
            revenue_mode=acct.get("revenue_mode") or REVENUE_MODE_CALCULATED,
            volume=volume,
            pricing=acct.get("pricing"),
            stored_amount=stored,
        )
        if acct.get("revenue_mode") == REVENUE_MODE_ABSOLUTE and stored is not None:
            revenue = _money(stored)
        dhs_total += _d(revenue)
        dhs_rows.append({
            "account_id": acct["id"],
            "dr_commercial_account_id": cid,
            "name": acct["name"],
            "revenue_mode": acct.get("revenue_mode"),
            "volume": volume,
            "revenue": _money(revenue),
            "pricing": acct.get("pricing"),
        })

    non_rinse_total = _money(_d(ss_total) + _d(do_total))
    rinse_total = _money(_d(wf_revenue or 0) + _d(hd_revenue))

    return {
        "rinse": {
            "wf": {
                "enabled": wf_enabled,
                "revenue": wf_revenue,
                "volume_lbs": wf_pounds,
                "pricing": wf_pricing,
                "meta": wf_meta,
                "placeholder": not wf_enabled,
            },
            "hd": {
                "source": "hd_day_bag_production",
                "orders": hd_orders,
                "revenue": hd_revenue,
                "read_only": True,
            },
            "total": rinse_total,
        },
        "non_rinse_revenue": {
            "self_service": {"cash": ss_cash, "card": ss_card, "total": ss_total},
            "drop_off": {"cash": do_cash, "card": do_card, "total": do_total},
            "total": non_rinse_total,
        },
        "non_rinse": {
            "self_service": {"cash": ss_cash, "card": ss_card, "total": ss_total},
            "drop_off": {"cash": do_cash, "card": do_card, "total": do_total},
            "total": non_rinse_total,
        },
        "dhs": {
            "accounts": dhs_rows,
            "total": _money(dhs_total),
        },
        "accounts": accounts,
        "total_revenue": _money(_d(rinse_total) + _d(non_rinse_total) + _d(dhs_total)),
    }


def build_revenue_dashboard(
    cursor,
    org_id: int,
    period: str,
    ref_date: date,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    from backend.management_revenue import _load_drc_lines_for_date

    start_date, end_date = _period_bounds_extended(period, ref_date, start, end)
    totals = {
        "wf": Decimal("0"),
        "hd": Decimal("0"),
        "self_service": Decimal("0"),
        "drop_off": Decimal("0"),
        "dhs_total": Decimal("0"),
    }
    dhs_by_name: dict[str, Decimal] = {}
    day = start_date
    while day <= end_date:
        lines = _load_drc_lines_for_date(cursor, org_id, day)
        block = build_account_revenue_day(cursor, org_id, day, lines)
        totals["wf"] += _d(block["rinse"]["wf"].get("revenue") or 0)
        totals["hd"] += _d(block["rinse"]["hd"].get("revenue") or 0)
        totals["self_service"] += _d(block["non_rinse_revenue"]["self_service"]["total"])
        totals["drop_off"] += _d(block["non_rinse_revenue"]["drop_off"]["total"])
        totals["dhs_total"] += _d(block["dhs"]["total"])
        for row in block["dhs"]["accounts"]:
            name = row.get("name") or "?"
            dhs_by_name[name] = dhs_by_name.get(name, Decimal("0")) + _d(row.get("revenue") or 0)
        day += timedelta(days=1)

    total = totals["wf"] + totals["hd"] + totals["self_service"] + totals["drop_off"] + totals["dhs_total"]
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_revenue": _money(total),
        "rinse": {
            "wf": _money(totals["wf"]),
            "hd": _money(totals["hd"]),
            "total": _money(totals["wf"] + totals["hd"]),
        },
        "non_rinse": {
            "self_service": _money(totals["self_service"]),
            "drop_off": _money(totals["drop_off"]),
            "total": _money(totals["self_service"] + totals["drop_off"]),
        },
        "dhs": {
            "total": _money(totals["dhs_total"]),
            "accounts": {k: _money(v) for k, v in sorted(dhs_by_name.items())},
        },
    }


def save_account(
    cursor,
    org_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    ensure_mgmt_revenue_account_tables(cursor)
    seed_mgmt_revenue_accounts(cursor, org_id, user_id=user_id)

    acct_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Account name is required")

    revenue_group = (payload.get("revenue_group") or REVENUE_GROUP_DHS).strip()
    revenue_mode = (payload.get("revenue_mode") or REVENUE_MODE_CALCULATED).strip()
    parent_id = payload.get("parent_id")
    service_type = payload.get("service_type")
    notes = payload.get("notes")
    active = 1 if payload.get("active", True) else 0

    if acct_id:
        cursor.execute(
            """
            UPDATE mgmt_revenue_accounts
            SET name = %s, revenue_group = %s, service_type = %s, revenue_mode = %s,
                parent_id = %s, active = %s, notes = %s
            WHERE id = %s AND organization_id = %s
            """,
            (name, revenue_group, service_type, revenue_mode, parent_id, active, notes, acct_id, org_id),
        )
    else:
        if revenue_group == REVENUE_GROUP_DHS and parent_id:
            dr_id = _ensure_dr_commercial_account(cursor, org_id, f"DHS - {name}")
        else:
            dr_id = None
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM mgmt_revenue_accounts WHERE organization_id = %s",
            (org_id,),
        )
        sort_order = int((cursor.fetchone() or {}).get("n") or 0)
        acct_id = _insert_account(
            cursor,
            org_id,
            account_code=None,
            name=name,
            revenue_group=revenue_group,
            parent_id=parent_id,
            revenue_mode=revenue_mode,
            service_type=service_type,
            dr_commercial_account_id=dr_id,
            sort_order=sort_order,
        )
        if notes:
            cursor.execute("UPDATE mgmt_revenue_accounts SET notes = %s WHERE id = %s", (notes, acct_id))

    pricing_payload = payload.get("pricing") or {}
    if pricing_payload:
        eff_raw = pricing_payload.get("effective_from") or business_today().isoformat()
        eff = date.fromisoformat(str(eff_raw)[:10])
        method = pricing_payload.get("pricing_method") or PRICING_FLAT_LB
        unit = pricing_payload.get("pricing_unit") or "lbs"
        rate = pricing_payload.get("rate_per_unit")
        tiers = pricing_payload.get("tiers")

        cursor.execute(
            """
            UPDATE mgmt_revenue_pricing_schedules
            SET effective_to = %s
            WHERE account_id = %s AND effective_to IS NULL AND effective_from < %s
            """,
            (eff - timedelta(days=1), acct_id, eff),
        )
        _insert_pricing(
            cursor,
            int(acct_id),
            effective_from=eff,
            pricing_method=method,
            pricing_unit=unit,
            rate_per_unit=float(rate) if rate is not None else None,
            tiers=tiers,
            user_id=user_id,
        )

    cursor.execute(
        "SELECT * FROM mgmt_revenue_accounts WHERE id = %s AND organization_id = %s",
        (acct_id, org_id),
    )
    row = cursor.fetchone()
    if not row:
        raise LookupError("Account not found")
    pricing = get_pricing_for_account(cursor, int(acct_id))
    return _account_row_to_dict(dict(row), pricing)


def _ensure_entry_id(cursor, org_id: int, entry_date: date, user_id: int | None = None) -> int:
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT id FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])
    cursor.execute(
        "INSERT INTO dr_daily_entries (organization_id, entry_date, status, created_by, modified_by) VALUES (%s, %s, 'open', %s, %s)",
        (org_id, entry_date, user_id, user_id),
    )
    return int(cursor.lastrowid)


def save_dhs_account_revenue(
    cursor,
    org_id: int,
    entry_date: date,
    accounts_payload: list[dict],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Persist DHS sub-account volume/revenue into DRC commercial lines."""
    from backend.management_revenue import build_revenue_day

    mgmt_by_id = {a["id"]: a for a in list_accounts(cursor, org_id, as_of=entry_date)}
    entry_id = _ensure_entry_id(cursor, org_id, entry_date, user_id)
    existing_lines = _load_entry_lines(cursor, entry_id)

    for item in accounts_payload or []:
        acct_id = int(item.get("account_id") or 0)
        acct = mgmt_by_id.get(acct_id)
        if not acct or acct.get("revenue_group") != REVENUE_GROUP_DHS:
            continue
        cid = int(item.get("dr_commercial_account_id") or acct.get("dr_commercial_account_id") or 0)
        if not cid:
            continue

        mode = (item.get("revenue_mode") or acct.get("revenue_mode") or REVENUE_MODE_CALCULATED).strip()
        volume = _money(item.get("volume") or 0)
        entered_revenue = item.get("revenue")
        pricing = acct.get("pricing")

        if mode == REVENUE_MODE_ABSOLUTE:
            revenue = _money(entered_revenue or 0)
            is_override = True
        else:
            revenue = _calc_account_revenue(
                revenue_mode=mode,
                volume=volume,
                pricing=pricing,
                stored_amount=entered_revenue,
            )
            is_override = entered_revenue is not None

        pk, ak = commercial_pounds_key(cid), commercial_amount_key(cid)
        snapshot = {"pricing": pricing, "revenue_mode": mode, "calculated_amount": revenue, "quantity": volume}
        for lk, amt, qty in [(pk, 0, volume), (ak, revenue, volume)]:
            upsert_entry_line(
                cursor,
                daily_entry_id=entry_id,
                line_key=lk,
                line_category="revenue",
                amount=amt if lk == ak else 0,
                quantity=qty,
                commercial_account_id=cid,
                source_system="manual",
                is_override=is_override if lk == ak else False,
                user_id=user_id,
                rate_snapshot=snapshot if lk == ak else {**snapshot, "line": "pounds"},
                existing_line=existing_lines.get(lk),
            )

    return build_revenue_day(cursor, org_id, entry_date)
