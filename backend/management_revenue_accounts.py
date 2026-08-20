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
    _load_entry_lines,
    _money,
    ensure_daily_revenue_cost_tables,
    wf_revenue_for_day,
)
from backend.daily_revenue_cost_constants import (
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_RINSE_WF_POUNDS,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    commercial_amount_key,
    commercial_pounds_key,
)
from backend.daily_revenue_cost_schema import upsert_entry_line
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

REVENUE_GROUP_RINSE_WF = "rinse_wf"
REVENUE_GROUP_RINSE_HD = "rinse_hd"
REVENUE_GROUP_NON_RINSE = "non_rinse"
REVENUE_GROUP_DHS = "dhs"

# Display rollup groups (UI hierarchy — not the same as per-account revenue_group codes).
DISPLAY_GROUP_RINSE = "rinse"
DISPLAY_GROUP_NON_RINSE = "non_rinse"
DISPLAY_GROUP_DHS = "dhs"

ACCOUNT_EXTRA_COLUMNS = (
    ("allow_override", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("use_pickup_date", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("use_processing_date", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("use_delivery_date", "TINYINT(1) NOT NULL DEFAULT 0"),
)

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


def _ensure_account_extra_columns(cursor) -> None:
    altered = False
    for col, ddl in ACCOUNT_EXTRA_COLUMNS:
        if table_has_column(cursor, "mgmt_revenue_accounts", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE mgmt_revenue_accounts ADD COLUMN {col} {ddl}")
            altered = True
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
            altered = True
    if altered:
        invalidate_schema_cache()


def ensure_mgmt_revenue_account_tables(cursor) -> None:
    if table_exists(cursor, "mgmt_revenue_accounts"):
        _ensure_account_extra_columns(cursor)
    else:
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
              allow_override TINYINT(1) NOT NULL DEFAULT 1,
              use_pickup_date TINYINT(1) NOT NULL DEFAULT 0,
              use_processing_date TINYINT(1) NOT NULL DEFAULT 1,
              use_delivery_date TINYINT(1) NOT NULL DEFAULT 0,
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
    if not table_exists(cursor, "mgmt_revenue_pricing_schedules"):
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


def _line_amount_or_none(lines: dict[str, dict], key: str) -> float | None:
    """None = not entered; 0.0 = intentionally entered zero."""
    row = lines.get(key)
    if not row:
        return None
    if row.get("amount") is None:
        return None
    return _money(row.get("amount"))


def _line_qty_or_none(lines: dict[str, dict], key: str) -> float | None:
    row = lines.get(key)
    if not row:
        return None
    if row.get("quantity") is None:
        return None
    return _money(row.get("quantity"))


def _parse_snapshot_dates(row: dict | None) -> dict[str, str | None]:
    raw = (row or {}).get("rate_snapshot_json") or (row or {}).get("rate_snapshot")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "pickup_date": raw.get("pickup_date"),
        "processing_date": raw.get("processing_date"),
        "delivery_date": raw.get("delivery_date"),
        "use_revenue_override": bool(raw.get("use_revenue_override")),
    }


def _account_row_to_dict(row: dict, pricing: dict | None = None) -> dict[str, Any]:
    sd = row.get("start_date")
    ed = row.get("end_date")
    from backend.management_revenue_obligations import default_cadence_for_account

    base = {
        "id": int(row["id"]),
        "parent_id": int(row["parent_id"]) if row.get("parent_id") else None,
        "account_code": row.get("account_code"),
        "name": row.get("name") or "",
        "revenue_group": row.get("revenue_group") or "",
        "service_type": row.get("service_type"),
        "revenue_mode": row.get("revenue_mode") or REVENUE_MODE_CALCULATED,
        "active": bool(row.get("active")),
        "allow_override": bool(row.get("allow_override", 1)),
        "use_pickup_date": bool(row.get("use_pickup_date", 0)),
        "use_processing_date": bool(row.get("use_processing_date", 1)),
        "use_delivery_date": bool(row.get("use_delivery_date", 0)),
        "entry_cadence": row.get("entry_cadence"),
        "start_date": sd.isoformat() if hasattr(sd, "isoformat") else sd,
        "end_date": ed.isoformat() if hasattr(ed, "isoformat") else ed,
        "dr_commercial_account_id": int(row["dr_commercial_account_id"]) if row.get("dr_commercial_account_id") else None,
        "notes": row.get("notes"),
        "sort_order": int(row.get("sort_order") or 0),
        "pricing": pricing,
    }
    base["entry_cadence"] = default_cadence_for_account(base)
    return base


def list_accounts(cursor, org_id: int, *, as_of: date | None = None, active_only: bool = False) -> list[dict]:
    ensure_mgmt_revenue_account_tables(cursor)
    from backend.management_revenue_obligations import (
        ensure_account_obligation_columns,
        get_schedule_for_account,
        seed_default_cadences_and_schedules,
    )

    ensure_account_obligation_columns(cursor)
    seed_mgmt_revenue_accounts(cursor, org_id)
    seed_default_cadences_and_schedules(cursor, org_id)
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
        item = _account_row_to_dict(acct, pricing)
        item["schedule"] = get_schedule_for_account(cursor, int(acct["id"]), as_of)
        out.append(item)
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
    allow_override: bool = True,
    use_pickup_date: bool = False,
    use_processing_date: bool = True,
    use_delivery_date: bool = False,
) -> int:
    eff = business_today()
    cursor.execute(
        """
        INSERT INTO mgmt_revenue_accounts
          (organization_id, parent_id, account_code, name, revenue_group, service_type,
           revenue_mode, active, allow_override, use_pickup_date, use_processing_date,
           use_delivery_date, start_date, dr_commercial_account_id, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            org_id,
            parent_id,
            account_code,
            name,
            revenue_group,
            service_type,
            revenue_mode,
            1 if allow_override else 0,
            1 if use_pickup_date else 0,
            1 if use_processing_date else 0,
            1 if use_delivery_date else 0,
            eff,
            dr_commercial_account_id,
            sort_order,
        ),
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
    """Hierarchical revenue block for one business day.

    Missing DRC lines return null (not entered). Present zero amounts stay 0.
    """
    # Active accounts for new entry; also keep inactive accounts that already have
    # DRC commercial lines for this day so historical drill-downs stay intact.
    all_accounts = list_accounts(cursor, org_id, as_of=entry_date, active_only=False)
    accounts = []
    for a in all_accounts:
        if a.get("active", True):
            accounts.append(a)
            continue
        cid = a.get("dr_commercial_account_id")
        if not cid:
            continue
        if commercial_pounds_key(cid) in lines or commercial_amount_key(cid) in lines:
            accounts.append(a)
    by_code = {a.get("account_code"): a for a in accounts if a.get("account_code")}
    by_id = {a["id"]: a for a in accounts}

    ss_cash = _line_amount_or_none(lines, LK_SELF_SERVICE_CASH)
    ss_card = _line_amount_or_none(lines, LK_SELF_SERVICE_CARD)
    do_cash = _line_amount_or_none(lines, LK_DROP_OFF_CASH)
    do_card = _line_amount_or_none(lines, LK_DROP_OFF_CARD)
    ss_total = None if ss_cash is None and ss_card is None else _money(_d(ss_cash or 0) + _d(ss_card or 0))
    do_total = None if do_cash is None and do_card is None else _money(_d(do_cash or 0) + _d(do_card or 0))
    non_rinse_total = None if ss_total is None and do_total is None else _money(_d(ss_total or 0) + _d(do_total or 0))

    wf_acct = by_code.get("rinse_wf") or {}
    wf_pricing = wf_acct.get("pricing")
    wf_tiers = _wf_tiers_from_pricing(wf_pricing)
    wf_pounds = _line_qty_or_none(lines, LK_RINSE_WF_POUNDS)
    wf_enabled = bool(wf_tiers)
    wf_revenue = None
    wf_meta: dict[str, Any] = {}
    if wf_enabled and wf_pounds:
        wf_revenue, wf_meta = wf_revenue_for_day(
            cursor, org_id, entry_date, wf_pounds, wf_tiers,
        )
    elif wf_enabled and wf_pounds == 0:
        wf_revenue = 0.0

    hd_totals = compute_hd_day_revenue_totals(cursor, org_id, entry_date)
    hd_revenue_raw = hd_totals.get("complete_hd_revenue")
    if hd_revenue_raw is None:
        hd_revenue_raw = hd_totals.get("total_hd_revenue")
    hd_orders = int(hd_totals.get("complete") or 0)
    # HD from production: treat no production as null display (not entered in revenue form)
    hd_revenue = _money(hd_revenue_raw) if (hd_orders or hd_revenue_raw) else None

    dhs_parent = by_code.get("dhs")
    dhs_parent_id = dhs_parent.get("id") if dhs_parent else None

    def _dhs_descendants(parent_id: int | None) -> list[dict]:
        """All active DHS accounts under parent (any depth)."""
        children = [a for a in accounts if a.get("revenue_group") == REVENUE_GROUP_DHS and a.get("parent_id") == parent_id]
        out = []
        for child in sorted(children, key=lambda x: (x.get("sort_order") or 0, x.get("name") or "")):
            out.append(child)
            out.extend(_dhs_descendants(child["id"]))
        return out

    # Leaf commercial accounts: those with dr_commercial_account_id under DHS tree
    dhs_tree = _dhs_descendants(dhs_parent_id) if dhs_parent_id else [
        a for a in accounts if a.get("revenue_group") == REVENUE_GROUP_DHS and a.get("parent_id")
    ]

    dhs_rows = []
    dhs_total_d = Decimal("0")
    dhs_any = False
    for acct in dhs_tree:
        cid = acct.get("dr_commercial_account_id")
        if not cid:
            continue
        pk = commercial_pounds_key(cid)
        ak = commercial_amount_key(cid)
        volume = _line_qty_or_none(lines, pk)
        stored = _line_amount_or_none(lines, ak)
        snap = _parse_snapshot_dates(lines.get(ak))
        mode = acct.get("revenue_mode") or REVENUE_MODE_CALCULATED
        use_override = snap.get("use_revenue_override") and acct.get("allow_override", True)

        if mode == REVENUE_MODE_ABSOLUTE:
            revenue = stored
        elif use_override and stored is not None:
            revenue = stored
        elif volume is None and stored is None:
            revenue = None
        else:
            revenue = _calc_account_revenue(
                revenue_mode=mode,
                volume=volume or 0,
                pricing=acct.get("pricing"),
                stored_amount=stored,
            )

        if revenue is not None:
            dhs_total_d += _d(revenue)
            dhs_any = True
        elif volume is not None or stored is not None:
            dhs_any = True

        parent = by_id.get(acct.get("parent_id")) if acct.get("parent_id") else None
        dhs_rows.append({
            "account_id": acct["id"],
            "parent_id": acct.get("parent_id"),
            "parent_name": parent.get("name") if parent else None,
            "dr_commercial_account_id": cid,
            "name": acct["name"],
            "revenue_mode": mode,
            "allow_override": bool(acct.get("allow_override", True)),
            "use_pickup_date": bool(acct.get("use_pickup_date")),
            "use_processing_date": bool(acct.get("use_processing_date", True)),
            "use_delivery_date": bool(acct.get("use_delivery_date")),
            "volume": volume,
            "revenue": revenue,
            "entered": volume is not None or stored is not None,
            "use_revenue_override": bool(use_override),
            "pickup_date": snap.get("pickup_date"),
            "processing_date": snap.get("processing_date"),
            "delivery_date": snap.get("delivery_date"),
            "pricing": acct.get("pricing"),
            "sort_order": acct.get("sort_order") or 0,
        })

    dhs_total = _money(dhs_total_d) if dhs_any else None
    rinse_total = None
    if wf_revenue is not None or hd_revenue is not None:
        rinse_total = _money(_d(wf_revenue or 0) + _d(hd_revenue or 0))

    total_revenue = None
    if rinse_total is not None or non_rinse_total is not None or dhs_total is not None:
        total_revenue = _money(_d(rinse_total or 0) + _d(non_rinse_total or 0) + _d(dhs_total or 0))

    def _money_label(v):
        if v is None:
            return "—"
        return f"${v:,.0f}"

    groups = [
        {
            "id": DISPLAY_GROUP_RINSE,
            "label": "RINSE",
            "total": rinse_total,
            "summary": f"WF {_money_label(wf_revenue)} · HD {_money_label(hd_revenue)}",
            "accounts": [
                {"code": "rinse_wf", "name": "Rinse WF", "total": wf_revenue, "read_only": False, "detail": "wf"},
                {"code": "rinse_hd", "name": "Rinse HD", "total": hd_revenue, "read_only": True, "detail": "hd"},
            ],
        },
        {
            "id": DISPLAY_GROUP_NON_RINSE,
            "label": "NON-RINSE",
            "total": non_rinse_total,
            "summary": f"Self Service {_money_label(ss_total)} · Drop Off {_money_label(do_total)}",
            "accounts": [
                {"code": "self_service", "name": "Self Service", "total": ss_total, "detail": "self_service"},
                {"code": "drop_off", "name": "Drop Off", "total": do_total, "detail": "drop_off"},
            ],
        },
        {
            "id": DISPLAY_GROUP_DHS,
            "label": "DHS",
            "total": dhs_total,
            "summary": (
                f"{sum(1 for r in dhs_rows if r.get('entered'))}/{len(dhs_rows)} accounts entered"
                if dhs_rows
                else "No accounts"
            ),
            "accounts": dhs_rows,
        },
    ]

    dhs_lbs = None
    if any(r.get("volume") is not None for r in dhs_rows):
        dhs_lbs = _money(sum(_d(r.get("volume") or 0) for r in dhs_rows))

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
            "total": dhs_total,
            "volume_lbs": dhs_lbs,
            "active_count": len(dhs_rows),
            "entered_count": sum(1 for r in dhs_rows if r.get("entered")),
        },
        "groups": groups,
        "accounts": accounts,
        "total_revenue": total_revenue,
    }


def build_revenue_dashboard(
    cursor,
    org_id: int,
    period: str,
    ref_date: date,
    start: date | None = None,
    end: date | None = None,
    *,
    compare: bool = True,
) -> dict[str, Any]:
    from backend.management_revenue import _load_drc_lines_for_date, build_cash_activity

    start_date, end_date = _period_bounds_extended(period, ref_date, start, end)
    day_count = max((end_date - start_date).days + 1, 1)

    totals = {
        "wf": Decimal("0"),
        "hd": Decimal("0"),
        "self_service": Decimal("0"),
        "self_service_cash": Decimal("0"),
        "self_service_card": Decimal("0"),
        "drop_off": Decimal("0"),
        "drop_off_cash": Decimal("0"),
        "drop_off_card": Decimal("0"),
        "dhs_total": Decimal("0"),
    }
    dhs_by_name: dict[str, Decimal] = {}
    trend: list[dict[str, Any]] = []
    day = start_date
    while day <= end_date:
        lines = _load_drc_lines_for_date(cursor, org_id, day)
        block = build_account_revenue_day(cursor, org_id, day, lines)
        wf = _d(block["rinse"]["wf"].get("revenue") or 0)
        hd = _d(block["rinse"]["hd"].get("revenue") or 0)
        ss = block["non_rinse_revenue"]["self_service"]
        do = block["non_rinse_revenue"]["drop_off"]
        ss_t = _d(ss.get("total") or 0)
        do_t = _d(do.get("total") or 0)
        dhs_t = _d(block["dhs"].get("total") or 0)
        day_total = wf + hd + ss_t + do_t + dhs_t
        totals["wf"] += wf
        totals["hd"] += hd
        totals["self_service"] += ss_t
        totals["self_service_cash"] += _d(ss.get("cash") or 0)
        totals["self_service_card"] += _d(ss.get("card") or 0)
        totals["drop_off"] += do_t
        totals["drop_off_cash"] += _d(do.get("cash") or 0)
        totals["drop_off_card"] += _d(do.get("card") or 0)
        totals["dhs_total"] += dhs_t
        for row in block["dhs"]["accounts"]:
            name = row.get("name") or "?"
            dhs_by_name[name] = dhs_by_name.get(name, Decimal("0")) + _d(row.get("revenue") or 0)
        trend.append({
            "date_et": day.isoformat(),
            "total": _money(day_total),
            "rinse": _money(wf + hd),
            "non_rinse": _money(ss_t + do_t),
            "dhs": _money(dhs_t),
        })
        day += timedelta(days=1)

    cash_act = build_cash_activity(cursor, org_id, period, ref_date, start_date, end_date)
    total = totals["wf"] + totals["hd"] + totals["self_service"] + totals["drop_off"] + totals["dhs_total"]
    cash_rev = totals["self_service_cash"] + totals["drop_off_cash"]
    card_rev = totals["self_service_card"] + totals["drop_off_card"]
    rinse_total = totals["wf"] + totals["hd"]
    non_rinse_total = totals["self_service"] + totals["drop_off"]

    top_accounts = sorted(
        [{"name": k, "revenue": _money(v)} for k, v in dhs_by_name.items()],
        key=lambda x: x["revenue"],
        reverse=True,
    )
    # Include non-rinse named accounts in top list
    named = [
        {"name": "Self Service", "revenue": _money(totals["self_service"])},
        {"name": "Drop Off", "revenue": _money(totals["drop_off"])},
        {"name": "Rinse WF", "revenue": _money(totals["wf"])},
        {"name": "Rinse HD", "revenue": _money(totals["hd"])},
        *top_accounts,
    ]
    named.sort(key=lambda x: x["revenue"], reverse=True)

    previous = None
    if compare:
        span = day_count
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        previous = build_revenue_dashboard(
            cursor, org_id, "custom", ref_date, prev_start, prev_end, compare=False,
        )

    payload = {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "day_count": day_count,
        "total_revenue": _money(total),
        "revenue_per_day": _money(total / day_count) if day_count else _money(total),
        "rinse": {
            "wf": _money(totals["wf"]),
            "hd": _money(totals["hd"]),
            "total": _money(rinse_total),
        },
        "non_rinse": {
            "self_service": _money(totals["self_service"]),
            "drop_off": _money(totals["drop_off"]),
            "total": _money(non_rinse_total),
        },
        "dhs": {
            "total": _money(totals["dhs_total"]),
            "accounts": {k: _money(v) for k, v in sorted(dhs_by_name.items())},
            "account_list": top_accounts,
        },
        "cash_revenue": _money(cash_rev),
        "card_revenue": _money(card_rev),
        "cash_paid_out": cash_act.get("cash_paid_out"),
        "net_cash_movement": cash_act.get("net_cash_movement"),
        "cash_vs_card": {
            "cash": _money(cash_rev),
            "card": _money(card_rev),
        },
        "by_group": [
            {"id": "rinse", "label": "Rinse", "revenue": _money(rinse_total)},
            {"id": "non_rinse", "label": "Non-Rinse", "revenue": _money(non_rinse_total)},
            {"id": "dhs", "label": "DHS", "revenue": _money(totals["dhs_total"])},
        ],
        "top_accounts": named[:10],
        "trend": trend,
        "payouts": cash_act.get("payouts") or [],
    }
    from backend.management_revenue_obligations import build_daily_completeness, build_dhs_obligations

    day_complete = build_daily_completeness(cursor, org_id, end_date)
    dhs_obs = build_dhs_obligations(cursor, org_id, as_of=end_date)
    dhs_due_total = len(dhs_obs)
    dhs_complete = len([r for r in dhs_obs if r.get("resolved")])
    dhs_pending = len([r for r in dhs_obs if not r.get("resolved")])
    payload["completeness"] = {
        "processing_date_et": end_date.isoformat(),
        "daily_entries": f"{day_complete.get('label')} complete",
        "daily": day_complete,
        "dhs_due": dhs_due_total,
        "dhs_complete": dhs_complete,
        "dhs_pending": dhs_pending,
        "dhs_label": f"DHS due {dhs_due_total} · Complete {dhs_complete} · Pending {dhs_pending}",
        "attribution": "processing_date",
    }
    if previous is not None:
        payload["compare"] = {
            "start_date": previous["start_date"],
            "end_date": previous["end_date"],
            "total_revenue": previous["total_revenue"],
            "delta_total": _money(_d(total) - _d(previous["total_revenue"])),
            "rinse": previous["rinse"]["total"],
            "non_rinse": previous["non_rinse"]["total"],
            "dhs": previous["dhs"]["total"],
        }
    return payload


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
    allow_override = 1 if payload.get("allow_override", True) else 0
    use_pickup_date = 1 if payload.get("use_pickup_date") else 0
    use_processing_date = 1 if payload.get("use_processing_date", True) else 0
    use_delivery_date = 1 if payload.get("use_delivery_date") else 0
    entry_cadence = (payload.get("entry_cadence") or "").strip().lower() or None
    if entry_cadence and entry_cadence not in ("daily", "scheduled", "optional"):
        raise ValueError("Invalid entry_cadence")

    from backend.management_revenue_obligations import ensure_account_obligation_columns, save_account_schedule

    ensure_account_obligation_columns(cursor)

    if acct_id:
        cursor.execute(
            """
            UPDATE mgmt_revenue_accounts
            SET name = %s, revenue_group = %s, service_type = %s, revenue_mode = %s,
                parent_id = %s, active = %s, notes = %s,
                allow_override = %s, use_pickup_date = %s, use_processing_date = %s,
                use_delivery_date = %s, entry_cadence = COALESCE(%s, entry_cadence)
            WHERE id = %s AND organization_id = %s
            """,
            (
                name, revenue_group, service_type, revenue_mode, parent_id, active, notes,
                allow_override, use_pickup_date, use_processing_date, use_delivery_date,
                entry_cadence, acct_id, org_id,
            ),
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
            allow_override=bool(allow_override),
            use_pickup_date=bool(use_pickup_date),
            use_processing_date=bool(use_processing_date),
            use_delivery_date=bool(use_delivery_date),
        )
        if notes:
            cursor.execute("UPDATE mgmt_revenue_accounts SET notes = %s WHERE id = %s", (notes, acct_id))
        if entry_cadence:
            cursor.execute(
                "UPDATE mgmt_revenue_accounts SET entry_cadence = %s WHERE id = %s",
                (entry_cadence, acct_id),
            )

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

    if "pickup_weekdays" in payload or "delivery_weekdays" in payload:
        sched_from = payload.get("schedule_effective_from") or business_today().isoformat()
        save_account_schedule(
            cursor,
            int(acct_id),
            effective_from=date.fromisoformat(str(sched_from)[:10]),
            pickup_weekdays=payload.get("pickup_weekdays"),
            delivery_weekdays=payload.get("delivery_weekdays"),
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
    out = _account_row_to_dict(dict(row), pricing)
    from backend.management_revenue_obligations import get_schedule_for_account

    out["schedule"] = get_schedule_for_account(cursor, int(acct_id), business_today())
    return out


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


def _optional_money(val: Any) -> float | None:
    """Parse money; None/blank → None (not entered). Explicit 0 stays 0."""
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    return _money(val)


def save_dhs_account_revenue(
    cursor,
    org_id: int,
    entry_date: date,
    accounts_payload: list[dict],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Persist DHS sub-account volume/revenue into DRC commercial lines.

    Null volume/revenue means not entered for that field. Only payload accounts
    are touched — never rebuilds the full DRC day.
    """
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
        volume = _optional_money(item.get("volume")) if "volume" in item else None
        entered_revenue = _optional_money(item.get("revenue")) if "revenue" in item else None
        use_override = bool(item.get("use_revenue_override")) and bool(acct.get("allow_override", True))
        pricing = acct.get("pricing")

        # Dates are dimensions only. Do not invent values the user never confirmed.
        # UI may visibly prefill Processing Date with entry_date; client must send it.
        pickup = item.get("pickup_date") or None
        processing = item.get("processing_date") or None
        delivery = item.get("delivery_date") or None
        if isinstance(pickup, str) and not pickup.strip():
            pickup = None
        if isinstance(processing, str) and not processing.strip():
            processing = None
        if isinstance(delivery, str) and not delivery.strip():
            delivery = None

        if mode == REVENUE_MODE_ABSOLUTE or use_override:
            revenue = entered_revenue
            is_override = True
        elif volume is None and entered_revenue is None:
            # Nothing to write for this account in this payload
            continue
        else:
            revenue = _calc_account_revenue(
                revenue_mode=mode,
                volume=volume or 0,
                pricing=pricing,
                stored_amount=entered_revenue,
            )
            is_override = entered_revenue is not None and use_override

        if revenue is None and volume is None:
            continue

        pk, ak = commercial_pounds_key(cid), commercial_amount_key(cid)
        snapshot = {
            "pricing": pricing,
            "revenue_mode": mode,
            "calculated_amount": revenue,
            "quantity": volume,
            "pickup_date": str(pickup)[:10] if pickup else None,
            "processing_date": str(processing)[:10] if processing else None,
            "delivery_date": str(delivery)[:10] if delivery else None,
            "scheduled_pickup_date": str(item.get("scheduled_pickup_date") or pickup or "")[:10] or None,
            "scheduled_delivery_date": str(item.get("scheduled_delivery_date") or delivery or "")[:10] or None,
            "date_override": bool(item.get("date_override")),
            "use_revenue_override": use_override,
            "date_basis": [
                k for k, enabled in (
                    ("pickup", acct.get("use_pickup_date")),
                    ("processing", acct.get("use_processing_date", True)),
                    ("delivery", acct.get("use_delivery_date")),
                ) if enabled
            ],
        }
        qty = volume if volume is not None else 0
        amt = revenue if revenue is not None else 0
        for lk, line_amt, line_qty in [(pk, 0, qty), (ak, amt, qty)]:
            upsert_entry_line(
                cursor,
                daily_entry_id=entry_id,
                line_key=lk,
                line_category="revenue",
                amount=line_amt if lk == ak else 0,
                quantity=line_qty if volume is not None else (existing_lines.get(lk) or {}).get("quantity"),
                commercial_account_id=cid,
                source_system="manual",
                is_override=is_override if lk == ak else False,
                user_id=user_id,
                rate_snapshot=snapshot if lk == ak else {**snapshot, "line": "pounds"},
                existing_line=existing_lines.get(lk),
            )

    return build_revenue_day(cursor, org_id, entry_date)
