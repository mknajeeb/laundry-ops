"""Daily Revenue & Cost — long-term financial module for LaundryOps."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.daily_revenue_cost_constants import (
    BILLING_FLAT,
    BILLING_HYBRID,
    BILLING_PER_LB,
    DEFAULT_COMMERCIAL_ACCOUNTS,
    DEFAULT_WF_TIERS,
    ENTRY_STATUS_APPROVED,
    ENTRY_STATUS_LOCKED,
    ENTRY_STATUS_OPEN,
    ENTRY_STATUS_REJECTED,
    ENTRY_STATUS_SUBMITTED,
    FIXED_COST_KEYS,
    LK_COST_ADJUSTMENTS,
    LK_COST_ELECTRICITY,
    LK_COST_GAS,
    LK_COST_INSURANCE,
    LK_COST_MAINTENANCE,
    LK_COST_PROPERTY_TAX,
    LK_COST_RENT,
    LK_COST_SUPPLIES,
    LK_COST_WATER,
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_PAYROLL_TAX,
    LK_PAYROLL_TOTAL,
    LK_RINSE_HD_AMOUNT,
    LK_RINSE_HD_ORDERS,
    LK_RINSE_WF_AMOUNT,
    LK_RINSE_WF_POUNDS,
    LK_RINSE_WI_AMOUNT,
    LK_RINSE_WI_ORDERS,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    SOURCE_MANUAL,
    VARIABLE_COST_KEYS,
    commercial_amount_key,
    commercial_pounds_key,
)
from backend.daily_revenue_cost_payroll import (
    fetch_payroll_total_suggestion,
    resolve_payroll_line_for_save,
    should_apply_payroll_suggestion,
    suggestion_to_line_row,
)
from backend.daily_revenue_cost_workload import (
    fetch_workload_wf_pounds_suggestion,
    resolve_workload_wf_line_for_save,
    should_apply_workload_wf_suggestion,
    suggestion_to_line_row as workload_suggestion_to_line_row,
)
from backend.daily_revenue_cost_schema import (
    SQL_SCHEMA_PATH,
    V1_MIGRATION_ERROR,
    _coerce_date,
    assert_entry_editable,
    assert_no_overlapping_schedules,
    assert_v2_safe_bootstrap,
    close_schedule_before,
    detect_v1_schema,
    json_dump,
    resolve_single_active_schedule,
    transition_entry_status,
    upsert_entry_line,
    WORKFLOW_TRANSITIONS,
)
from backend.ta_helpers import table_exists

from backend.wf_mtd_pricing import (
    MONEY_Q,
    allocate_wf_day_revenue_from_mtd,
    cumulative_wf_revenue as shared_cumulative_wf_revenue,
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


def _money(val: Any) -> float:
    return float(_d(val).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def _pct(val: Any) -> float | None:
    if val is None:
        return None
    return float(_d(val))


def _json_dump(obj: Any) -> str | None:
    return json_dump(obj)


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── Schema ───────────────────────────────────────────────────────────────────


def ensure_daily_revenue_cost_tables(cursor) -> None:
    """Create v2 tables if missing. See backend/sql/daily_revenue_cost_v2.sql."""
    assert_v2_safe_bootstrap(cursor)
    if table_exists(cursor, "dr_daily_entry_lines"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_commercial_accounts (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          name VARCHAR(128) NOT NULL,
          external_ref VARCHAR(128) NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          sort_order INT NOT NULL DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_dr_ca_org_name (organization_id, name)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_commercial_pricing_schedules (
          id INT AUTO_INCREMENT PRIMARY KEY,
          commercial_account_id INT NOT NULL,
          effective_from DATE NOT NULL,
          effective_to DATE NULL,
          billing_model VARCHAR(16) NOT NULL DEFAULT 'per_lb',
          rate_per_pound DECIMAL(10, 4) NULL,
          flat_amount DECIMAL(12, 2) NULL,
          logistics_charge DECIMAL(12, 2) NOT NULL DEFAULT 0,
          additional_charge DECIMAL(12, 2) NOT NULL DEFAULT 0,
          notes VARCHAR(255) NULL,
          created_by INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_dr_cps_account_dates (commercial_account_id, effective_from, effective_to)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_rinse_wf_pricing_schedules (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          effective_from DATE NOT NULL,
          effective_to DATE NULL,
          name VARCHAR(128) NULL,
          created_by INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_dr_wfps_org_dates (organization_id, effective_from, effective_to)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_rinse_wf_tier_lines (
          id INT AUTO_INCREMENT PRIMARY KEY,
          schedule_id INT NOT NULL,
          tier_number INT NOT NULL,
          max_lbs INT NULL,
          rate_per_lb DECIMAL(10, 4) NOT NULL DEFAULT 0,
          UNIQUE KEY uq_dr_wftl_sched_tier (schedule_id, tier_number)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_cost_schedules (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          effective_from DATE NOT NULL,
          effective_to DATE NULL,
          payroll_tax_pct DECIMAL(8, 4) NULL,
          payroll_tax_daily_fixed DECIMAL(12, 2) NULL,
          rent_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          insurance_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          property_tax_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          electricity_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          water_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          gas_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          supplies_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          maintenance_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          adjustments_daily DECIMAL(12, 2) NOT NULL DEFAULT 0,
          created_by INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_dr_cs_org_dates (organization_id, effective_from, effective_to)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_daily_entries (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          entry_date DATE NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'open',
          created_by INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          modified_by INT NULL,
          modified_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          locked_by INT NULL,
          locked_at DATETIME NULL,
          submitted_by INT NULL,
          submitted_at DATETIME NULL,
          reviewed_by INT NULL,
          reviewed_at DATETIME NULL,
          review_notes TEXT NULL,
          UNIQUE KEY uq_dr_entry_org_date (organization_id, entry_date)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_daily_entry_lines (
          id INT AUTO_INCREMENT PRIMARY KEY,
          daily_entry_id INT NOT NULL,
          line_key VARCHAR(64) NOT NULL,
          line_category VARCHAR(16) NOT NULL,
          amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
          quantity DECIMAL(12, 2) NULL,
          commercial_account_id INT NULL,
          source_system VARCHAR(32) NOT NULL DEFAULT 'manual',
          source_ref VARCHAR(128) NULL,
          source_captured_at DATETIME NULL,
          source_payload JSON NULL,
          is_manual_override TINYINT(1) NOT NULL DEFAULT 0,
          override_reason VARCHAR(255) NULL,
          overridden_by INT NULL,
          overridden_at DATETIME NULL,
          pricing_schedule_id INT NULL,
          rate_snapshot_json JSON NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_dr_del_entry_key (daily_entry_id, line_key)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_entry_audit_events (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          daily_entry_id INT NULL,
          event_type VARCHAR(32) NOT NULL,
          line_key VARCHAR(64) NULL,
          field_name VARCHAR(64) NULL,
          old_value TEXT NULL,
          new_value TEXT NULL,
          source_system VARCHAR(32) NULL,
          actor_user_id INT NULL,
          notes TEXT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_dr_eae_entry (daily_entry_id, created_at)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_integration_sync_runs (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          entry_date DATE NOT NULL,
          source_system VARCHAR(32) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'pending',
          records_imported INT NOT NULL DEFAULT 0,
          error_message TEXT NULL,
          payload_json JSON NULL,
          started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          completed_at TIMESTAMP NULL,
          INDEX idx_dr_isr_org_date (organization_id, entry_date, source_system)
        ) ENGINE=InnoDB
        """
    )


# ── Effective-date resolution ────────────────────────────────────────────────


def _schedule_active_sql(date_col: str = "%s") -> str:
    return f"(effective_from <= {date_col} AND (effective_to IS NULL OR effective_to >= {date_col}))"


def get_cost_schedule_for_date(cursor, org_id: int, as_of: date) -> dict | None:
    ensure_daily_revenue_cost_tables(cursor)
    row = resolve_single_active_schedule(
        cursor,
        table="dr_cost_schedules",
        scope_column="organization_id",
        scope_id=org_id,
        as_of=as_of,
    )
    return _cost_schedule_to_dict(row) if row else None


def _cost_schedule_to_dict(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "effective_from": row["effective_from"].isoformat() if hasattr(row["effective_from"], "isoformat") else str(row["effective_from"]),
        "effective_to": row["effective_to"].isoformat() if row.get("effective_to") and hasattr(row["effective_to"], "isoformat") else (str(row["effective_to"]) if row.get("effective_to") else None),
        "payroll_tax_pct": _pct(row.get("payroll_tax_pct")),
        "payroll_tax_daily_fixed": _money(row["payroll_tax_daily_fixed"]) if row.get("payroll_tax_daily_fixed") is not None else None,
        "fixed_costs": {
            "rent_daily": _money(row.get("rent_daily")),
            "insurance_daily": _money(row.get("insurance_daily")),
            "property_tax_daily": _money(row.get("property_tax_daily")),
        },
        "variable_costs": {
            "electricity_daily": _money(row.get("electricity_daily")),
            "water_daily": _money(row.get("water_daily")),
            "gas_daily": _money(row.get("gas_daily")),
            "supplies_daily": _money(row.get("supplies_daily")),
            "maintenance_daily": _money(row.get("maintenance_daily")),
            "adjustments_daily": _money(row.get("adjustments_daily")),
        },
        # Flat compat for existing UI
        "electricity_daily": _money(row.get("electricity_daily")),
        "water_daily": _money(row.get("water_daily")),
        "gas_daily": _money(row.get("gas_daily")),
        "supplies_daily": _money(row.get("supplies_daily")),
        "insurance_daily": _money(row.get("insurance_daily")),
        "maintenance_daily": _money(row.get("maintenance_daily")),
        "rent_daily": _money(row.get("rent_daily")),
        "property_tax_daily": _money(row.get("property_tax_daily")),
        "adjustments_daily": _money(row.get("adjustments_daily")),
    }


def get_cost_settings(cursor, org_id: int, *, as_of: date | None = None) -> dict:
    from backend.business_time import business_today

    as_of = as_of or business_today()
    sched = get_cost_schedule_for_date(cursor, org_id, as_of)
    if sched:
        return sched
    return {
        "payroll_tax_pct": None,
        "payroll_tax_daily_fixed": None,
        "fixed_costs": {"rent_daily": 0, "insurance_daily": 0, "property_tax_daily": 0},
        "variable_costs": {
            "electricity_daily": 0, "water_daily": 0, "gas_daily": 0,
            "supplies_daily": 0, "maintenance_daily": 0, "adjustments_daily": 0,
        },
        "electricity_daily": 0, "water_daily": 0, "gas_daily": 0,
        "supplies_daily": 0, "insurance_daily": 0, "maintenance_daily": 0,
        "rent_daily": 0, "property_tax_daily": 0, "adjustments_daily": 0,
    }


def save_cost_settings(cursor, org_id: int, payload: dict, *, user_id: int | None = None, effective_from: date | None = None) -> dict:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    eff = effective_from or business_today()
    pct = payload.get("payroll_tax_pct")
    fixed = payload.get("payroll_tax_daily_fixed")

    cursor.execute(
        f"""
        SELECT id FROM dr_cost_schedules
        WHERE organization_id = %s AND {_schedule_active_sql()}
        ORDER BY effective_from DESC LIMIT 1
        """,
        (org_id, eff, eff),
    )
    current = cursor.fetchone()
    if current:
        cursor.execute(
            "SELECT effective_from FROM dr_cost_schedules WHERE id = %s",
            (current["id"],),
        )
        prev = cursor.fetchone()
        prev_from = _coerce_date(prev["effective_from"]) if prev else None
        if prev and prev_from == eff:
            cursor.execute(
                """
                UPDATE dr_cost_schedules SET
                  payroll_tax_pct = %s, payroll_tax_daily_fixed = %s,
                  rent_daily = %s, insurance_daily = %s, property_tax_daily = %s,
                  electricity_daily = %s, water_daily = %s, gas_daily = %s,
                  supplies_daily = %s, maintenance_daily = %s, adjustments_daily = %s
                WHERE id = %s
                """,
                (
                    pct if pct is not None else None,
                    fixed if fixed is not None else None,
                    _money(payload.get("rent_daily")),
                    _money(payload.get("insurance_daily")),
                    _money(payload.get("property_tax_daily")),
                    _money(payload.get("electricity_daily")),
                    _money(payload.get("water_daily")),
                    _money(payload.get("gas_daily")),
                    _money(payload.get("supplies_daily")),
                    _money(payload.get("maintenance_daily")),
                    _money(payload.get("adjustments_daily")),
                    current["id"],
                ),
            )
            _log_schedule_audit(cursor, None, "cost_schedule_changed", user_id=user_id, notes=f"updated id={current['id']}")
            return get_cost_settings(cursor, org_id, as_of=eff)
        if prev and prev_from and prev_from < eff:
            close_schedule_before(
                cursor,
                table="dr_cost_schedules",
                id_column="id",
                schedule_id=int(current["id"]),
                new_effective_from=eff,
            )

    assert_no_overlapping_schedules(
        cursor,
        table="dr_cost_schedules",
        scope_column="organization_id",
        scope_id=org_id,
        effective_from=eff,
    )

    cursor.execute(
        """
        INSERT INTO dr_cost_schedules (
          organization_id, effective_from, payroll_tax_pct, payroll_tax_daily_fixed,
          rent_daily, insurance_daily, property_tax_daily,
          electricity_daily, water_daily, gas_daily, supplies_daily, maintenance_daily, adjustments_daily,
          created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            org_id, eff,
            pct if pct is not None else None,
            fixed if fixed is not None else None,
            _money(payload.get("rent_daily")),
            _money(payload.get("insurance_daily")),
            _money(payload.get("property_tax_daily")),
            _money(payload.get("electricity_daily")),
            _money(payload.get("water_daily")),
            _money(payload.get("gas_daily")),
            _money(payload.get("supplies_daily")),
            _money(payload.get("maintenance_daily")),
            _money(payload.get("adjustments_daily")),
            user_id,
        ),
    )
    new_id = cursor.lastrowid
    _log_schedule_audit(cursor, None, "cost_schedule_changed", user_id=user_id, notes=f"created id={new_id} effective_from={eff}")
    return get_cost_settings(cursor, org_id, as_of=eff)


def get_commercial_pricing_for_date(cursor, account_id: int, as_of: date) -> dict | None:
    row = resolve_single_active_schedule(
        cursor,
        table="dr_commercial_pricing_schedules",
        scope_column="commercial_account_id",
        scope_id=account_id,
        as_of=as_of,
    )
    if not row:
        return None
    return _pricing_schedule_to_dict(row)


def _pricing_schedule_to_dict(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "commercial_account_id": int(row["commercial_account_id"]),
        "effective_from": row["effective_from"].isoformat() if hasattr(row["effective_from"], "isoformat") else str(row["effective_from"]),
        "effective_to": row["effective_to"].isoformat() if row.get("effective_to") and hasattr(row["effective_to"], "isoformat") else None,
        "billing_model": row.get("billing_model") or BILLING_PER_LB,
        "rate_per_pound": _money(row.get("rate_per_pound")) if row.get("rate_per_pound") is not None else None,
        "flat_amount": _money(row.get("flat_amount")) if row.get("flat_amount") is not None else None,
        "logistics_charge": _money(row.get("logistics_charge")),
        "additional_charge": _money(row.get("additional_charge")),
    }


def commercial_line_revenue_from_pricing(pounds: Any, pricing: dict) -> float:
    model = pricing.get("billing_model") or BILLING_PER_LB
    lbs = _d(pounds)
    logistics = _d(pricing.get("logistics_charge"))
    additional = _d(pricing.get("additional_charge"))
    if model == BILLING_FLAT:
        rev = _d(pricing.get("flat_amount")) + logistics + additional
    elif model == BILLING_HYBRID:
        rate = _d(pricing.get("rate_per_pound"))
        flat = _d(pricing.get("flat_amount"))
        rev = max(lbs * rate, flat) + logistics + additional
    else:
        rev = lbs * _d(pricing.get("rate_per_pound")) + logistics + additional
    return _money(rev)


def commercial_line_revenue(pounds: Any, rate: Any, logistics: Any, additional: Any) -> float:
    return commercial_line_revenue_from_pricing(
        pounds,
        {"billing_model": BILLING_PER_LB, "rate_per_pound": rate, "logistics_charge": logistics, "additional_charge": additional},
    )


def get_wf_schedule_for_date(cursor, org_id: int, as_of: date) -> tuple[int | None, list[dict]]:
    row = resolve_single_active_schedule(
        cursor,
        table="dr_rinse_wf_pricing_schedules",
        scope_column="organization_id",
        scope_id=org_id,
        as_of=as_of,
    )
    if not row:
        return None, []
    schedule_id = int(row["id"])
    cursor.execute(
        "SELECT * FROM dr_rinse_wf_tier_lines WHERE schedule_id = %s ORDER BY tier_number",
        (schedule_id,),
    )
    tiers = []
    for row in cursor.fetchall() or []:
        tiers.append({
            "id": int(row["id"]),
            "tier_number": int(row.get("tier_number") or 0),
            "max_lbs": int(row["max_lbs"]) if row.get("max_lbs") is not None else None,
            "rate_per_lb": _money(row.get("rate_per_lb")),
        })
    return schedule_id, tiers


def get_rinse_wf_tiers(cursor, org_id: int, *, as_of: date | None = None) -> list[dict]:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    _seed_wf_pricing(cursor, org_id)
    as_of = as_of or business_today()
    _, tiers = get_wf_schedule_for_date(cursor, org_id, as_of)
    return tiers


# ── WF tier revenue math (shared with Daily Operations via wf_mtd_pricing) ─


def cumulative_wf_revenue(total_lbs: Any, tiers: list[dict]) -> Decimal:
    """Compatibility wrapper — single implementation lives in wf_mtd_pricing."""
    return shared_cumulative_wf_revenue(total_lbs, tiers)


def _mtd_wf_pounds(cursor, org_id: int, entry_date: date, *, exclude_entry_id: int | None = None) -> Decimal:
    month_start = entry_date.replace(day=1)
    params: list[Any] = [org_id, month_start, entry_date, LK_RINSE_WF_POUNDS]
    exclude_sql = ""
    if exclude_entry_id:
        exclude_sql = " AND e.id != %s"
        params.append(exclude_entry_id)
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(l.quantity), 0) AS mtd
        FROM dr_daily_entry_lines l
        JOIN dr_daily_entries e ON e.id = l.daily_entry_id
        WHERE e.organization_id = %s
          AND e.entry_date >= %s AND e.entry_date < %s
          AND l.line_key = %s
          {exclude_sql}
        """,
        tuple(params),
    )
    return _d((cursor.fetchone() or {}).get("mtd"))


def wf_revenue_for_day(
    cursor, org_id: int, entry_date: date, day_pounds: Any,
    tiers: list[dict] | None = None, *, exclude_entry_id: int | None = None,
) -> tuple[float, dict]:
    if tiers is None:
        _, tiers = get_wf_schedule_for_date(cursor, org_id, entry_date)
    mtd_before = _mtd_wf_pounds(cursor, org_id, entry_date, exclude_entry_id=exclude_entry_id)
    allocated = allocate_wf_day_revenue_from_mtd(mtd_before, day_pounds, tiers)
    return float(allocated["weight_revenue_today"]), {
        "mtd_pounds_before": allocated["mtd_pounds_before"],
        "mtd_pounds_after": allocated["mtd_pounds_after"],
        "day_pounds": allocated["day_pounds"],
        "applied_tiers": allocated["applied_tiers"],
        "tier1_pounds_today": allocated["tier1_pounds_today"],
        "tier2_pounds_today": allocated["tier2_pounds_today"],
        "tier1_revenue_today": allocated["tier1_revenue_today"],
        "tier2_revenue_today": allocated["tier2_revenue_today"],
        "weight_revenue_today": allocated["weight_revenue_today"],
    }


def calc_payroll_tax(payroll: Any, settings: dict) -> float:
    payroll_d = _d(payroll)
    fixed = settings.get("payroll_tax_daily_fixed")
    pct = settings.get("payroll_tax_pct")
    if fixed is not None and _d(fixed) > 0:
        return _money(fixed)
    if pct is not None and _d(pct) > 0:
        return _money(payroll_d * _d(pct) / Decimal("100"))
    return 0.0


# ── Commercial accounts ──────────────────────────────────────────────────────


def _seed_commercial_accounts(cursor, org_id: int, user_id: int | None = None) -> None:
    cursor.execute("SELECT COUNT(*) AS c FROM dr_commercial_accounts WHERE organization_id = %s", (org_id,))
    if int((cursor.fetchone() or {}).get("c") or 0) > 0:
        return
    from backend.business_time import business_today
    eff = business_today()
    for i, name in enumerate(DEFAULT_COMMERCIAL_ACCOUNTS):
        cursor.execute(
            "INSERT INTO dr_commercial_accounts (organization_id, name, active, sort_order) VALUES (%s, %s, 1, %s)",
            (org_id, name, i),
        )
        acct_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO dr_commercial_pricing_schedules
              (commercial_account_id, effective_from, billing_model, rate_per_pound, logistics_charge, additional_charge, created_by)
            VALUES (%s, %s, 'per_lb', 0, 0, 0, %s)
            """,
            (acct_id, eff, user_id),
        )


def _commercial_account_to_dict(row: dict, pricing: dict | None = None) -> dict:
    out = {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "external_ref": row.get("external_ref"),
        "active": bool(row.get("active")),
        "sort_order": int(row.get("sort_order") or 0),
    }
    if pricing:
        out.update({
            "billing_model": pricing.get("billing_model"),
            "rate_per_pound": pricing.get("rate_per_pound", 0),
            "flat_amount": pricing.get("flat_amount"),
            "default_logistics_charge": pricing.get("logistics_charge", 0),
            "default_additional_charge": pricing.get("additional_charge", 0),
            "pricing_effective_from": pricing.get("effective_from"),
        })
    else:
        out.update({
            "billing_model": BILLING_PER_LB,
            "rate_per_pound": 0,
            "flat_amount": None,
            "default_logistics_charge": 0,
            "default_additional_charge": 0,
        })
    return out


def list_commercial_accounts(cursor, org_id: int, *, active_only: bool = False, as_of: date | None = None) -> list[dict]:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    _seed_commercial_accounts(cursor, org_id)
    as_of = as_of or business_today()
    sql = "SELECT * FROM dr_commercial_accounts WHERE organization_id = %s"
    params: list[Any] = [org_id]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY sort_order, name"
    cursor.execute(sql, tuple(params))
    out = []
    for row in cursor.fetchall() or []:
        pricing = get_commercial_pricing_for_date(cursor, int(row["id"]), as_of)
        out.append(_commercial_account_to_dict(row, pricing))
    return out


def create_commercial_account(cursor, org_id: int, payload: dict, *, user_id: int | None = None) -> dict:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    cursor.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM dr_commercial_accounts WHERE organization_id = %s",
        (org_id,),
    )
    sort_order = int((cursor.fetchone() or {}).get("n") or 0)
    eff = payload.get("effective_from")
    if eff and hasattr(eff, "isoformat"):
        eff_date = eff
    elif isinstance(eff, str) and eff:
        from backend.business_time import business_today
        try:
            eff_date = date.fromisoformat(eff)
        except ValueError:
            eff_date = business_today()
    else:
        eff_date = business_today()

    cursor.execute(
        "INSERT INTO dr_commercial_accounts (organization_id, name, external_ref, active, sort_order) VALUES (%s, %s, %s, %s, %s)",
        (org_id, name, payload.get("external_ref"), 1 if payload.get("active", True) else 0, sort_order),
    )
    acct_id = int(cursor.lastrowid)
    cursor.execute(
        """
        INSERT INTO dr_commercial_pricing_schedules
          (commercial_account_id, effective_from, billing_model, rate_per_pound, flat_amount,
           logistics_charge, additional_charge, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            acct_id, eff_date,
            payload.get("billing_model") or BILLING_PER_LB,
            _money(payload.get("rate_per_pound")) if payload.get("rate_per_pound") is not None else None,
            _money(payload.get("flat_amount")) if payload.get("flat_amount") is not None else None,
            _money(payload.get("default_logistics_charge")),
            _money(payload.get("default_additional_charge")),
            user_id,
        ),
    )
    cursor.execute("SELECT * FROM dr_commercial_accounts WHERE id = %s", (acct_id,))
    acct_row = cursor.fetchone()
    pricing = get_commercial_pricing_for_date(cursor, acct_id, eff_date)
    return _commercial_account_to_dict(acct_row, pricing)


def update_commercial_account(cursor, org_id: int, account_id: int, payload: dict, *, user_id: int | None = None) -> dict:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute("SELECT * FROM dr_commercial_accounts WHERE id = %s AND organization_id = %s", (account_id, org_id))
    row = cursor.fetchone()
    if not row:
        raise LookupError("Commercial account not found")

    name = (payload.get("name") or row.get("name") or "").strip()
    cursor.execute(
        "UPDATE dr_commercial_accounts SET name = %s, external_ref = %s, active = %s WHERE id = %s",
        (name, payload.get("external_ref", row.get("external_ref")), 1 if payload.get("active", row.get("active")) else 0, account_id),
    )

    # New pricing schedule if rates changed (never overwrite history)
    rate_fields = ("rate_per_pound", "flat_amount", "default_logistics_charge", "default_additional_charge", "billing_model")
    if any(k in payload for k in rate_fields):
        eff_raw = payload.get("effective_from")
        eff_date = date.fromisoformat(eff_raw) if isinstance(eff_raw, str) and eff_raw else business_today()
        current = get_commercial_pricing_for_date(cursor, account_id, eff_date)
        if current and (_coerce_date(current.get("effective_from")) or date.min) < eff_date:
            close_schedule_before(
                cursor,
                table="dr_commercial_pricing_schedules",
                id_column="id",
                schedule_id=int(current["id"]),
                new_effective_from=eff_date,
            )
        elif current and _coerce_date(current.get("effective_from")) == eff_date:
            cursor.execute(
                """
                UPDATE dr_commercial_pricing_schedules SET
                  billing_model = %s, rate_per_pound = %s, flat_amount = %s,
                  logistics_charge = %s, additional_charge = %s
                WHERE id = %s
                """,
                (
                    payload.get("billing_model") or current.get("billing_model") or BILLING_PER_LB,
                    _money(payload.get("rate_per_pound", current.get("rate_per_pound"))),
                    _money(payload.get("flat_amount", current.get("flat_amount"))) if payload.get("flat_amount") is not None or current.get("flat_amount") else None,
                    _money(payload.get("default_logistics_charge", current.get("logistics_charge"))),
                    _money(payload.get("default_additional_charge", current.get("additional_charge"))),
                    current["id"],
                ),
            )
            _log_schedule_audit(cursor, None, "pricing_schedule_changed", user_id=user_id, notes=f"commercial account={account_id} updated id={current['id']}")
            cursor.execute("SELECT * FROM dr_commercial_accounts WHERE id = %s", (account_id,))
            acct_row = cursor.fetchone()
            pricing = get_commercial_pricing_for_date(cursor, account_id, business_today())
            return _commercial_account_to_dict(acct_row, pricing)

        assert_no_overlapping_schedules(
            cursor,
            table="dr_commercial_pricing_schedules",
            scope_column="commercial_account_id",
            scope_id=account_id,
            effective_from=eff_date,
        )
        cursor.execute(
            """
            INSERT INTO dr_commercial_pricing_schedules
              (commercial_account_id, effective_from, billing_model, rate_per_pound, flat_amount,
               logistics_charge, additional_charge, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                account_id, eff_date,
                payload.get("billing_model") or (current or {}).get("billing_model") or BILLING_PER_LB,
                _money(payload.get("rate_per_pound", (current or {}).get("rate_per_pound"))),
                _money(payload.get("flat_amount", (current or {}).get("flat_amount"))) if payload.get("flat_amount") is not None or (current or {}).get("flat_amount") else None,
                _money(payload.get("default_logistics_charge", (current or {}).get("logistics_charge"))),
                _money(payload.get("default_additional_charge", (current or {}).get("additional_charge"))),
                user_id,
            ),
        )
        _log_schedule_audit(cursor, None, "pricing_schedule_changed", user_id=user_id, notes=f"commercial account={account_id} new schedule effective_from={eff_date}")

    cursor.execute("SELECT * FROM dr_commercial_accounts WHERE id = %s", (account_id,))
    acct_row = cursor.fetchone()
    pricing = get_commercial_pricing_for_date(cursor, account_id, business_today())
    return _commercial_account_to_dict(acct_row, pricing)


# ── WF pricing schedules ───────────────────────────────────────────────────


def ensure_veewash_aug1_2026_wf_schedule(cursor, org_id: int, user_id: int | None = None) -> dict[str, Any]:
    """
    Ensure the approved Aug 1, 2026 WF tier schedule exists for org 3.

    Does not rewrite historical schedules. Safe to call repeatedly.
    """
    from backend.wf_mtd_pricing import (
        VEEWASH_WF_SCHEDULE_EFFECTIVE_FROM,
        VEEWASH_WF_SCHEDULE_NAME,
    )

    ensure_daily_revenue_cost_tables(cursor)
    org = int(org_id)
    eff = VEEWASH_WF_SCHEDULE_EFFECTIVE_FROM
    cursor.execute(
        """
        SELECT id FROM dr_rinse_wf_pricing_schedules
        WHERE organization_id = %s AND effective_from = %s
        LIMIT 1
        """,
        (org, eff),
    )
    existing = cursor.fetchone()
    if existing:
        return {"created": False, "schedule_id": int(existing["id"]), "effective_from": eff.isoformat()}

    # Close any open-ended schedule that would overlap Aug 1+.
    cursor.execute(
        """
        SELECT id, effective_from, effective_to
        FROM dr_rinse_wf_pricing_schedules
        WHERE organization_id = %s
          AND effective_from < %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC
        """,
        (org, eff, eff),
    )
    for row in cursor.fetchall() or []:
        close_schedule_before(
            cursor,
            table="dr_rinse_wf_pricing_schedules",
            id_column="id",
            schedule_id=int(row["id"]),
            new_effective_from=eff,
        )

    assert_no_overlapping_schedules(
        cursor,
        table="dr_rinse_wf_pricing_schedules",
        scope_column="organization_id",
        scope_id=org,
        effective_from=eff,
    )
    cursor.execute(
        """
        INSERT INTO dr_rinse_wf_pricing_schedules
          (organization_id, effective_from, name, created_by)
        VALUES (%s, %s, %s, %s)
        """,
        (org, eff, VEEWASH_WF_SCHEDULE_NAME, user_id),
    )
    sched_id = int(cursor.lastrowid)
    for tier in DEFAULT_WF_TIERS:
        cursor.execute(
            """
            INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb)
            VALUES (%s, %s, %s, %s)
            """,
            (sched_id, tier["tier_number"], tier["max_lbs"], tier["rate_per_lb"]),
        )
    _log_schedule_audit(
        cursor,
        None,
        "pricing_schedule_changed",
        user_id=user_id,
        notes=f"seeded {VEEWASH_WF_SCHEDULE_NAME} id={sched_id}",
    )
    return {"created": True, "schedule_id": sched_id, "effective_from": eff.isoformat()}


def _seed_wf_pricing(cursor, org_id: int, user_id: int | None = None) -> None:
    cursor.execute("SELECT COUNT(*) AS c FROM dr_rinse_wf_pricing_schedules WHERE organization_id = %s", (org_id,))
    if int((cursor.fetchone() or {}).get("c") or 0) > 0:
        # Org 3 always ensures the approved Aug 1 schedule exists alongside any history.
        if int(org_id) == 3:
            ensure_veewash_aug1_2026_wf_schedule(cursor, org_id, user_id=user_id)
        return
    from backend.wf_mtd_pricing import VEEWASH_WF_SCHEDULE_EFFECTIVE_FROM, VEEWASH_WF_SCHEDULE_NAME

    # Org 3: seed the approved Aug 1 plan (not today), so Jul 23–31 remain without this rate.
    if int(org_id) == 3:
        ensure_veewash_aug1_2026_wf_schedule(cursor, org_id, user_id=user_id)
        return

    from backend.business_time import business_today

    eff = business_today()
    cursor.execute(
        "INSERT INTO dr_rinse_wf_pricing_schedules (organization_id, effective_from, name, created_by) VALUES (%s, %s, 'Default', %s)",
        (org_id, eff, user_id),
    )
    sched_id = cursor.lastrowid
    for tier in DEFAULT_WF_TIERS:
        cursor.execute(
            "INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb) VALUES (%s, %s, %s, %s)",
            (sched_id, tier["tier_number"], tier["max_lbs"], tier["rate_per_lb"]),
        )


def save_rinse_wf_tiers(cursor, org_id: int, tiers: list[dict], *, user_id: int | None = None, effective_from: date | None = None) -> list[dict]:
    from backend.business_time import business_today

    ensure_daily_revenue_cost_tables(cursor)
    if not isinstance(tiers, list) or not tiers:
        raise ValueError("tiers must be a non-empty list")
    eff = effective_from or business_today()

    cursor.execute(
        f"""
        SELECT id FROM dr_rinse_wf_pricing_schedules
        WHERE organization_id = %s AND {_schedule_active_sql()}
        ORDER BY effective_from DESC LIMIT 1
        """,
        (org_id, eff, eff),
    )
    current = cursor.fetchone()
    if current:
        cursor.execute("SELECT effective_from FROM dr_rinse_wf_pricing_schedules WHERE id = %s", (current["id"],))
        prev = cursor.fetchone()
        prev_from = _coerce_date(prev["effective_from"]) if prev else None
        if prev and prev_from == eff:
            cursor.execute("DELETE FROM dr_rinse_wf_tier_lines WHERE schedule_id = %s", (current["id"],))
            for tier in sorted(tiers, key=lambda t: int(t.get("tier_number") or 0)):
                max_lbs = tier.get("max_lbs")
                cursor.execute(
                    "INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb) VALUES (%s, %s, %s, %s)",
                    (current["id"], int(tier.get("tier_number") or 0), int(max_lbs) if max_lbs is not None else None, _money(tier.get("rate_per_lb"))),
                )
            _log_schedule_audit(cursor, None, "pricing_schedule_changed", user_id=user_id, notes=f"wf tiers updated id={current['id']}")
            return get_rinse_wf_tiers(cursor, org_id, as_of=eff)
        close_schedule_before(
            cursor,
            table="dr_rinse_wf_pricing_schedules",
            id_column="id",
            schedule_id=int(current["id"]),
            new_effective_from=eff,
        )

    assert_no_overlapping_schedules(
        cursor,
        table="dr_rinse_wf_pricing_schedules",
        scope_column="organization_id",
        scope_id=org_id,
        effective_from=eff,
    )

    cursor.execute(
        "INSERT INTO dr_rinse_wf_pricing_schedules (organization_id, effective_from, created_by) VALUES (%s, %s, %s)",
        (org_id, eff, user_id),
    )
    sched_id = int(cursor.lastrowid)
    for tier in sorted(tiers, key=lambda t: int(t.get("tier_number") or 0)):
        max_lbs = tier.get("max_lbs")
        cursor.execute(
            "INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb) VALUES (%s, %s, %s, %s)",
            (sched_id, int(tier.get("tier_number") or 0), int(max_lbs) if max_lbs is not None else None, _money(tier.get("rate_per_lb"))),
        )
    _log_schedule_audit(cursor, None, "pricing_schedule_changed", user_id=user_id, notes=f"wf tiers created schedule_id={sched_id} effective_from={eff}")
    return get_rinse_wf_tiers(cursor, org_id, as_of=eff)


# ── Line items + audit ───────────────────────────────────────────────────────


def _load_entry_lines(cursor, entry_id: int) -> dict[str, dict]:
    cursor.execute("SELECT * FROM dr_daily_entry_lines WHERE daily_entry_id = %s", (entry_id,))
    return {row["line_key"]: row for row in (cursor.fetchall() or [])}


def _line_amount(lines: dict[str, dict], key: str) -> float:
    row = lines.get(key)
    return _money(row.get("amount")) if row else 0.0


def _line_qty(lines: dict[str, dict], key: str) -> float:
    row = lines.get(key)
    return _money(row.get("quantity")) if row and row.get("quantity") is not None else 0.0


def _parse_json_field(val: Any) -> Any:
    if val is None or isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (TypeError, ValueError):
            return val
    return val


def _line_source_meta(row: dict | None, *, line_key: str, audit_history: list[dict] | None = None) -> dict:
    row = row or {}
    source = str(row.get("source_system") or SOURCE_MANUAL)
    return {
        "line_key": line_key,
        "source_system": source,
        "source_ref": row.get("source_ref"),
        "source_captured_at": str(row.get("source_captured_at") or "") or None,
        "source_payload": _parse_json_field(row.get("source_payload")),
        "is_manual_override": bool(row.get("is_manual_override")),
        "override_reason": row.get("override_reason"),
        "overridden_at": str(row.get("overridden_at") or "") or None,
        "overridden_by": row.get("overridden_by"),
        "history": audit_history or [],
    }


def _load_line_audit_events(cursor, entry_id: int) -> dict[str, list[dict]]:
    cursor.execute(
        """
        SELECT event_type, line_key, old_value, new_value, source_system, actor_user_id, notes, created_at
        FROM dr_entry_audit_events
        WHERE daily_entry_id = %s AND line_key IS NOT NULL
        ORDER BY created_at DESC
        """,
        (entry_id,),
    )
    grouped: dict[str, list[dict]] = {}
    for row in cursor.fetchall() or []:
        lk = str(row.get("line_key") or "")
        if not lk:
            continue
        grouped.setdefault(lk, []).append({
            "event_type": row.get("event_type"),
            "old_value": row.get("old_value"),
            "new_value": row.get("new_value"),
            "source_system": row.get("source_system"),
            "actor_user_id": row.get("actor_user_id"),
            "notes": row.get("notes"),
            "created_at": str(row.get("created_at") or ""),
        })
    return grouped


def _field_sources_from_lines(lines: dict[str, dict], accounts: list[dict], audit_by_line: dict[str, list[dict]] | None = None) -> dict:
    audit_by_line = audit_by_line or {}

    def _meta(key: str) -> dict:
        return _line_source_meta(lines.get(key), line_key=key, audit_history=audit_by_line.get(key, []))

    out = {
        LK_SELF_SERVICE_CASH: _meta(LK_SELF_SERVICE_CASH),
        LK_SELF_SERVICE_CARD: _meta(LK_SELF_SERVICE_CARD),
        LK_DROP_OFF_CASH: _meta(LK_DROP_OFF_CASH),
        LK_DROP_OFF_CARD: _meta(LK_DROP_OFF_CARD),
        LK_RINSE_WF_POUNDS: _meta(LK_RINSE_WF_POUNDS),
        LK_RINSE_HD_ORDERS: _meta(LK_RINSE_HD_ORDERS),
        LK_RINSE_HD_AMOUNT: _meta(LK_RINSE_HD_AMOUNT),
        LK_RINSE_WI_ORDERS: _meta(LK_RINSE_WI_ORDERS),
        LK_RINSE_WI_AMOUNT: _meta(LK_RINSE_WI_AMOUNT),
        LK_PAYROLL_TOTAL: _meta(LK_PAYROLL_TOTAL),
    }
    for acct in accounts:
        aid = int(acct["id"])
        pk, ak = commercial_pounds_key(aid), commercial_amount_key(aid)
        out[pk] = _line_source_meta(
            lines.get(pk) or lines.get(ak),
            line_key=pk,
            audit_history=(audit_by_line.get(pk) or []) + (audit_by_line.get(ak) or []),
        )
    return out


def _resolve_line_source(existing_lines: dict[str, dict], line_key: str, *, is_override: bool) -> str:
    existing = existing_lines.get(line_key) or {}
    if existing.get("source_system"):
        return str(existing["source_system"])
    return SOURCE_MANUAL


def _resolve_line_source_ref(existing_lines: dict[str, dict], line_key: str) -> str | None:
    existing = existing_lines.get(line_key) or {}
    return existing.get("source_ref")


def _upsert_line(
    cursor, entry_id: int, line_key: str, line_category: str,
    amount: float, quantity: float | None = None,
    *, commercial_account_id: int | None = None,
    source_system: str = SOURCE_MANUAL, source_ref: str | None = None,
    source_payload: dict | None = None, source_captured_at: str | None = None,
    is_override: bool = False, override_reason: str | None = None,
    user_id: int | None = None,
    pricing_schedule_id: int | None = None, rate_snapshot: dict | None = None,
    existing_lines: dict[str, dict] | None = None,
) -> None:
    existing = (existing_lines or {}).get(line_key)

    def _on_change(*, line_key: str, old_value: str, new_value: str, is_override: bool) -> None:
        _log_audit(
            cursor, entry_id, "override" if is_override else "updated",
            line_key=line_key, old_value=old_value, new_value=new_value,
            actor_user_id=user_id, source_system=source_system,
        )

    upsert_entry_line(
        cursor,
        daily_entry_id=entry_id,
        line_key=line_key,
        line_category=line_category,
        amount=amount,
        quantity=quantity,
        commercial_account_id=commercial_account_id,
        source_system=source_system,
        source_ref=source_ref,
        source_payload=_parse_json_field(source_payload) if isinstance(source_payload, str) else source_payload,
        source_captured_at=source_captured_at,
        is_override=is_override,
        override_reason=override_reason,
        user_id=user_id,
        pricing_schedule_id=pricing_schedule_id,
        rate_snapshot=rate_snapshot,
        existing_line=existing,
        on_change=_on_change if existing else None,
    )


def _log_schedule_audit(cursor, entry_id: int | None, event_type: str, *, user_id: int | None = None, notes: str | None = None) -> None:
    cursor.execute(
        """
        INSERT INTO dr_entry_audit_events (daily_entry_id, event_type, notes, actor_user_id)
        VALUES (%s, %s, %s, %s)
        """,
        (entry_id, event_type, notes, user_id),
    )


def _log_audit(cursor, entry_id: int, event_type: str, *, line_key: str | None = None,
               field_name: str | None = None, old_value: str | None = None, new_value: str | None = None,
               source_system: str | None = None, actor_user_id: int | None = None, notes: str | None = None) -> None:
    cursor.execute(
        """
        INSERT INTO dr_entry_audit_events
          (daily_entry_id, event_type, line_key, field_name, old_value, new_value, source_system, actor_user_id, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (entry_id, event_type, line_key, field_name, old_value, new_value, source_system, actor_user_id, notes),
    )


# ── Integration stubs (auto-populate later) ────────────────────────────────


def fetch_integration_suggestions(cursor, org_id: int, entry_date: date) -> dict:
    suggestions: dict[str, dict] = {}
    payroll = fetch_payroll_total_suggestion(cursor, org_id, entry_date)
    if payroll:
        suggestions[LK_PAYROLL_TOTAL] = payroll
    workload_wf = fetch_workload_wf_pounds_suggestion(cursor, org_id, entry_date)
    if workload_wf:
        suggestions[LK_RINSE_WF_POUNDS] = workload_wf
    return {
        "available_sources": ["workload", "productivity", "payroll", "pos", "stripe", "cleancloud"],
        "suggestions": suggestions,
        "note": "Payroll and workload adapters active; other sources pending.",
    }


def _integration_suggestions_for_entry(cursor, org_id: int, entry_date: date, lines: dict[str, dict]) -> dict:
    payload = fetch_integration_suggestions(cursor, org_id, entry_date)
    payroll = payload.get("suggestions", {}).get(LK_PAYROLL_TOTAL)
    if payroll and not should_apply_payroll_suggestion(lines.get(LK_PAYROLL_TOTAL)):
        payload = {**payload, "payroll_blocked_by_override": True}
    workload_wf = payload.get("suggestions", {}).get(LK_RINSE_WF_POUNDS)
    if workload_wf and not should_apply_workload_wf_suggestion(lines.get(LK_RINSE_WF_POUNDS)):
        payload = {**payload, "workload_wf_pounds_blocked_by_override": True}
    return payload


def _apply_payroll_suggestion_to_lines(lines: dict[str, dict], suggestion: dict | None) -> dict[str, dict]:
    if not suggestion or not should_apply_payroll_suggestion(lines.get(LK_PAYROLL_TOTAL)):
        return lines
    merged = dict(lines)
    merged[LK_PAYROLL_TOTAL] = suggestion_to_line_row(suggestion)
    return merged


def _apply_workload_suggestion_to_lines(lines: dict[str, dict], suggestion: dict | None) -> dict[str, dict]:
    if not suggestion or not should_apply_workload_wf_suggestion(lines.get(LK_RINSE_WF_POUNDS)):
        return lines
    merged = dict(lines)
    merged[LK_RINSE_WF_POUNDS] = workload_suggestion_to_line_row(suggestion)
    return merged


def _refresh_wf_revenue_display_lines(
    cursor,
    org_id: int,
    entry_date: date,
    lines: dict[str, dict],
    tiers: list[dict],
    *,
    exclude_entry_id: int | None = None,
) -> tuple[dict[str, dict], dict]:
    pounds = _line_qty(lines, LK_RINSE_WF_POUNDS)
    if pounds <= 0:
        return lines, {}
    wf_rev, wf_meta = wf_revenue_for_day(
        cursor, org_id, entry_date, pounds, tiers, exclude_entry_id=exclude_entry_id,
    )
    merged = dict(lines)
    amount_row = dict(merged.get(LK_RINSE_WF_AMOUNT) or {})
    amount_row["amount"] = wf_rev
    amount_row["quantity"] = pounds
    merged[LK_RINSE_WF_AMOUNT] = amount_row
    return merged, wf_meta


# ── Summary + API shape ────────────────────────────────────────────────────


def _entry_summary_from_lines(lines: dict[str, dict]) -> dict:
    self_service = _money(_d(_line_amount(lines, LK_SELF_SERVICE_CASH)) + _d(_line_amount(lines, LK_SELF_SERVICE_CARD)))
    drop_off = _money(_d(_line_amount(lines, LK_DROP_OFF_CASH)) + _d(_line_amount(lines, LK_DROP_OFF_CARD)))
    rinse_wf = _line_amount(lines, LK_RINSE_WF_AMOUNT)
    rinse_hd = _line_amount(lines, LK_RINSE_HD_AMOUNT)
    rinse_wi = _line_amount(lines, LK_RINSE_WI_AMOUNT)
    commercial = _money(sum(
        _d(r.get("amount")) for k, r in lines.items()
        if k.startswith("revenue.commercial.") and k.endswith(".amount")
    ))
    total_revenue = _money(_d(self_service) + _d(drop_off) + _d(rinse_wf) + _d(rinse_hd) + _d(rinse_wi) + _d(commercial))
    payroll = _line_amount(lines, LK_PAYROLL_TOTAL)
    payroll_tax = _line_amount(lines, LK_PAYROLL_TAX)
    labor_cost = _money(_d(payroll) + _d(payroll_tax))
    fixed_cost = _money(sum(_d(_line_amount(lines, k)) for k in FIXED_COST_KEYS))
    variable_cost = _money(sum(_d(_line_amount(lines, k)) for k in VARIABLE_COST_KEYS))
    operating_cost = _money(_d(fixed_cost) + _d(variable_cost))
    total_cost = _money(_d(labor_cost) + _d(operating_cost))
    profit = _money(_d(total_revenue) - _d(total_cost))
    margin_pct = _money((_d(profit) / _d(total_revenue) * Decimal("100")) if _d(total_revenue) > 0 else Decimal("0"))
    return {
        "self_service_revenue": self_service,
        "drop_off_revenue": drop_off,
        "rinse_wf_revenue": rinse_wf,
        "rinse_hd_revenue": rinse_hd,
        "rinse_wi_revenue": rinse_wi,
        "commercial_revenue": commercial,
        "total_revenue": total_revenue,
        "payroll_total": payroll,
        "payroll_tax_amount": payroll_tax,
        "labor_cost": labor_cost,
        "fixed_cost": fixed_cost,
        "variable_cost": variable_cost,
        "operating_cost": operating_cost,
        "total_cost": total_cost,
        "estimated_profit": profit,
        "profit_margin_pct": margin_pct,
    }


def _lines_to_entry_shape(
    lines: dict[str, dict],
    header: dict | None,
    commercial_accounts: list[dict],
    wf_meta: dict | None = None,
    *,
    audit_by_line: dict[str, list[dict]] | None = None,
) -> dict:
    commercial_lines = []
    for acct in commercial_accounts:
        aid = acct["id"]
        pk = commercial_pounds_key(aid)
        ak = commercial_amount_key(aid)
        lr = lines.get(pk)
        ar = lines.get(ak)
        src_row = lr or ar or {}
        commercial_lines.append({
            "commercial_account_id": aid,
            "account_name": acct["name"],
            "pounds": _line_qty(lines, pk) if lr else 0,
            "rate_per_pound": acct.get("rate_per_pound", 0),
            "logistics_charge": acct.get("default_logistics_charge", 0),
            "additional_charge": acct.get("default_additional_charge", 0),
            "revenue": _line_amount(lines, ak) if ar else 0,
            "source_system": src_row.get("source_system", SOURCE_MANUAL),
            "is_manual_override": bool(src_row.get("is_manual_override")),
            "line_key": pk,
        })

    summary = _entry_summary_from_lines(lines)
    op = {
        "electricity": _line_amount(lines, LK_COST_ELECTRICITY),
        "water": _line_amount(lines, LK_COST_WATER),
        "gas": _line_amount(lines, LK_COST_GAS),
        "supplies": _line_amount(lines, LK_COST_SUPPLIES),
        "insurance": _line_amount(lines, LK_COST_INSURANCE),
        "maintenance": _line_amount(lines, LK_COST_MAINTENANCE),
        "rent": _line_amount(lines, LK_COST_RENT),
        "property_tax": _line_amount(lines, LK_COST_PROPERTY_TAX),
        "adjustments": _line_amount(lines, LK_COST_ADJUSTMENTS),
    }

    meta = {}
    if header:
        meta = {
            "status": header.get("status") or ENTRY_STATUS_OPEN,
            "created_by": header.get("created_by"),
            "created_at": str(header.get("created_at") or ""),
            "modified_by": header.get("modified_by"),
            "modified_at": str(header.get("modified_at") or "") if header.get("modified_at") else None,
            "locked_by": header.get("locked_by"),
            "locked_at": str(header.get("locked_at") or "") if header.get("locked_at") else None,
        }

    return {
        "id": int(header["id"]) if header else None,
        "entry_date": header["entry_date"].isoformat() if header and hasattr(header.get("entry_date"), "isoformat") else None,
        "exists": bool(header),
        "self_service_cash": _line_amount(lines, LK_SELF_SERVICE_CASH),
        "self_service_card": _line_amount(lines, LK_SELF_SERVICE_CARD),
        "drop_off_cash": _line_amount(lines, LK_DROP_OFF_CASH),
        "drop_off_card": _line_amount(lines, LK_DROP_OFF_CARD),
        "rinse_wf_pounds": _line_qty(lines, LK_RINSE_WF_POUNDS),
        "rinse_wf_revenue": _line_amount(lines, LK_RINSE_WF_AMOUNT),
        "rinse_wf_meta": wf_meta or {},
        "rinse_hd_orders": int(_line_qty(lines, LK_RINSE_HD_ORDERS)),
        "rinse_hd_revenue": _line_amount(lines, LK_RINSE_HD_AMOUNT),
        "rinse_wi_orders": int(_line_qty(lines, LK_RINSE_WI_ORDERS)),
        "rinse_wi_revenue": _line_amount(lines, LK_RINSE_WI_AMOUNT),
        "payroll_total": _line_amount(lines, LK_PAYROLL_TOTAL),
        "payroll_tax_amount": _line_amount(lines, LK_PAYROLL_TAX),
        "operating_costs": op,
        "commercial_lines": commercial_lines,
        "line_sources": _field_sources_from_lines(lines, commercial_accounts, audit_by_line),
        "summary": summary,
        **meta,
    }


def get_daily_entry(cursor, org_id: int, entry_date: date) -> dict:
    ensure_daily_revenue_cost_tables(cursor)
    cost_settings = get_cost_settings(cursor, org_id, as_of=entry_date)
    accounts = list_commercial_accounts(cursor, org_id, active_only=True, as_of=entry_date)
    tiers = get_rinse_wf_tiers(cursor, org_id, as_of=entry_date)

    cursor.execute("SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s", (org_id, entry_date))
    header = cursor.fetchone()
    lines: dict[str, dict] = _load_entry_lines(cursor, int(header["id"])) if header else {}
    audit_by_line = _load_line_audit_events(cursor, int(header["id"])) if header else {}
    payroll_suggestion = fetch_payroll_total_suggestion(cursor, org_id, entry_date)
    workload_suggestion = fetch_workload_wf_pounds_suggestion(cursor, org_id, entry_date)

    if not header:
        draft_lines = {}
        for acct in accounts:
            draft_lines[commercial_pounds_key(acct["id"])] = {"amount": 0, "quantity": 0}
            draft_lines[commercial_amount_key(acct["id"])] = {"amount": 0}
        draft_lines = _apply_payroll_suggestion_to_lines(draft_lines, payroll_suggestion)
        draft_lines = _apply_workload_suggestion_to_lines(draft_lines, workload_suggestion)
        draft_lines, wf_meta = _refresh_wf_revenue_display_lines(
            cursor, org_id, entry_date, draft_lines, tiers,
        )
        entry_shape = _lines_to_entry_shape(draft_lines, None, accounts, wf_meta, audit_by_line={})
        entry_shape["summary"] = _entry_summary_from_lines(draft_lines)
        return {
            "entry": entry_shape,
            "cost_settings": cost_settings,
            "commercial_accounts": accounts,
            "rinse_wf_tiers": tiers,
            "integration_suggestions": _integration_suggestions_for_entry(cursor, org_id, entry_date, draft_lines),
        }

    if header:
        display_lines = _apply_payroll_suggestion_to_lines(lines, payroll_suggestion)
        display_lines = _apply_workload_suggestion_to_lines(display_lines, workload_suggestion)
        exclude_id = int(header["id"])
        if should_apply_workload_wf_suggestion(lines.get(LK_RINSE_WF_POUNDS)) and workload_suggestion:
            display_lines, wf_meta = _refresh_wf_revenue_display_lines(
                cursor, org_id, entry_date, display_lines, tiers, exclude_entry_id=exclude_id,
            )
        else:
            wf_meta = {}
        # Frozen lines only — never recalculate historical revenue from current maintenance.
        entry_shape = _lines_to_entry_shape(display_lines, header, accounts, wf_meta=wf_meta, audit_by_line=audit_by_line)
        return {
            "entry": entry_shape,
            "cost_settings": cost_settings,
            "commercial_accounts": accounts,
            "rinse_wf_tiers": tiers,
            "integration_suggestions": _integration_suggestions_for_entry(cursor, org_id, entry_date, lines),
        }


def save_daily_entry(cursor, org_id: int, entry_date: date, payload: dict, *, user_id: int | None = None) -> dict:
    ensure_daily_revenue_cost_tables(cursor)
    cost_settings = get_cost_settings(cursor, org_id, as_of=entry_date)
    wf_schedule_id, tiers = get_wf_schedule_for_date(cursor, org_id, entry_date)
    accounts = list_commercial_accounts(cursor, org_id, active_only=True, as_of=entry_date)

    cursor.execute("SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s", (org_id, entry_date))
    header = cursor.fetchone()
    assert_entry_editable(header, payload)
    if header and str(header.get("status")) == ENTRY_STATUS_REJECTED and payload.get("reopen"):
        transition_entry_status(
            cursor, org_id, entry_date, "reopen", user_id=user_id, log_audit=_log_audit,
        )
        cursor.execute("SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s", (org_id, entry_date))
        header = cursor.fetchone()

    was_existing = bool(header)
    overrides = payload.get("overrides") or {}
    payroll_suggestion = fetch_payroll_total_suggestion(cursor, org_id, entry_date)
    workload_suggestion = fetch_workload_wf_pounds_suggestion(cursor, org_id, entry_date)

    if header:
        entry_id = int(header["id"])
        existing_lines = _load_entry_lines(cursor, entry_id)
        cursor.execute("UPDATE dr_daily_entries SET modified_by = %s WHERE id = %s", (user_id, entry_id))
    else:
        cursor.execute(
            "INSERT INTO dr_daily_entries (organization_id, entry_date, status, created_by, modified_by) VALUES (%s, %s, %s, %s, %s)",
            (org_id, entry_date, ENTRY_STATUS_OPEN, user_id, user_id),
        )
        entry_id = int(cursor.lastrowid)
        existing_lines = {}
        _log_audit(cursor, entry_id, "created", actor_user_id=user_id)

    wf_write = resolve_workload_wf_line_for_save(
        payload_quantity=_money(payload.get("rinse_wf_pounds")),
        overrides=overrides,
        existing_line=(existing_lines or {}).get(LK_RINSE_WF_POUNDS),
        suggestion=workload_suggestion,
    )
    wf_pounds = _money(wf_write["quantity"])
    wf_rev, wf_meta = wf_revenue_for_day(
        cursor, org_id, entry_date, wf_pounds, tiers,
        exclude_entry_id=int(header["id"]) if header else None,
    )
    payroll_total = _money(payload.get("payroll_total"))

    wf_snapshot = {
        "schedule_id": wf_schedule_id,
        "tiers": tiers,
        "mtd_meta": wf_meta,
        "calculated_amount": wf_rev,
        "quantity": wf_pounds,
    }
    cost_snapshot = {**cost_settings, "calculated_at": entry_date.isoformat()}

    def _is_override(key: str) -> bool:
        return bool(overrides.get(key, {}).get("is_manual_override"))

    def _override_reason(key: str) -> str | None:
        return overrides.get(key, {}).get("reason")

    payroll_write = resolve_payroll_line_for_save(
        payload_amount=payroll_total,
        overrides=overrides,
        existing_line=(existing_lines or {}).get(LK_PAYROLL_TOTAL),
        suggestion=payroll_suggestion,
    )
    payroll_total = _money(payroll_write["amount"])
    payroll_tax = calc_payroll_tax(payroll_total, cost_settings)

    revenue_fields = [
        (LK_SELF_SERVICE_CASH, "revenue", _money(payload.get("self_service_cash")), None),
        (LK_SELF_SERVICE_CARD, "revenue", _money(payload.get("self_service_card")), None),
        (LK_DROP_OFF_CASH, "revenue", _money(payload.get("drop_off_cash")), None),
        (LK_DROP_OFF_CARD, "revenue", _money(payload.get("drop_off_card")), None),
        (LK_RINSE_HD_ORDERS, "revenue", 0, int(payload.get("rinse_hd_orders") or 0)),
        (LK_RINSE_HD_AMOUNT, "revenue", _money(payload.get("rinse_hd_revenue")), None),
        (LK_RINSE_WI_ORDERS, "revenue", 0, int(payload.get("rinse_wi_orders") or 0)),
        (LK_RINSE_WI_AMOUNT, "revenue", _money(payload.get("rinse_wi_revenue")), None),
    ]

    for line_key, cat, amt, qty in revenue_fields:
        _upsert_line(
            cursor, entry_id, line_key, cat, amt, qty,
            source_system=_resolve_line_source(existing_lines, line_key, is_override=_is_override(line_key)),
            source_ref=_resolve_line_source_ref(existing_lines, line_key),
            is_override=_is_override(line_key), override_reason=_override_reason(line_key),
            user_id=user_id,
            existing_lines=existing_lines,
        )

    _upsert_line(
        cursor, entry_id, LK_RINSE_WF_POUNDS, "revenue", 0, wf_pounds,
        source_system=wf_write["source_system"],
        source_ref=wf_write.get("source_ref"),
        source_payload=wf_write.get("source_payload"),
        source_captured_at=wf_write.get("source_captured_at"),
        is_override=bool(wf_write.get("is_override")),
        override_reason=wf_write.get("override_reason"),
        user_id=user_id,
        pricing_schedule_id=wf_schedule_id,
        rate_snapshot=wf_snapshot,
        existing_lines=existing_lines,
    )
    _upsert_line(
        cursor, entry_id, LK_RINSE_WF_AMOUNT, "revenue", wf_rev, wf_pounds,
        source_system=SOURCE_MANUAL,
        user_id=user_id,
        pricing_schedule_id=wf_schedule_id,
        rate_snapshot=wf_snapshot,
        existing_lines=existing_lines,
    )

    _upsert_line(
        cursor, entry_id, LK_PAYROLL_TOTAL, "payroll", payroll_total, None,
        source_system=payroll_write["source_system"],
        source_ref=payroll_write.get("source_ref"),
        source_payload=payroll_write.get("source_payload"),
        source_captured_at=payroll_write.get("source_captured_at"),
        is_override=bool(payroll_write.get("is_override")),
        override_reason=payroll_write.get("override_reason"),
        user_id=user_id,
        existing_lines=existing_lines,
    )
    _upsert_line(
        cursor, entry_id, LK_PAYROLL_TAX, "payroll", payroll_tax, None,
        source_system=SOURCE_MANUAL,
        existing_lines=existing_lines,
    )

    cost_lines = [
        (LK_COST_RENT, "cost_fixed", cost_settings.get("rent_daily", 0)),
        (LK_COST_INSURANCE, "cost_fixed", cost_settings.get("insurance_daily", 0)),
        (LK_COST_PROPERTY_TAX, "cost_fixed", cost_settings.get("property_tax_daily", 0)),
        (LK_COST_ELECTRICITY, "cost_variable", cost_settings.get("electricity_daily", 0)),
        (LK_COST_WATER, "cost_variable", cost_settings.get("water_daily", 0)),
        (LK_COST_GAS, "cost_variable", cost_settings.get("gas_daily", 0)),
        (LK_COST_SUPPLIES, "cost_variable", cost_settings.get("supplies_daily", 0)),
        (LK_COST_MAINTENANCE, "cost_variable", cost_settings.get("maintenance_daily", 0)),
        (LK_COST_ADJUSTMENTS, "cost_variable", cost_settings.get("adjustments_daily", 0)),
    ]
    cost_sched_id = cost_settings.get("id")
    for line_key, cat, amt in cost_lines:
        _upsert_line(
            cursor, entry_id, line_key, cat, _money(amt), None,
            source_system=SOURCE_MANUAL,
            pricing_schedule_id=cost_sched_id,
            rate_snapshot=cost_snapshot,
            existing_lines=existing_lines,
        )

    commercial_payload = {int(l.get("commercial_account_id") or 0): l for l in (payload.get("commercial_lines") or [])}
    for acct in accounts:
        aid = acct["id"]
        line_data = commercial_payload.get(aid, {})
        pricing = get_commercial_pricing_for_date(cursor, aid, entry_date) or {
            "billing_model": BILLING_PER_LB, "rate_per_pound": acct.get("rate_per_pound", 0),
            "logistics_charge": acct.get("default_logistics_charge", 0),
            "additional_charge": acct.get("default_additional_charge", 0),
        }
        pounds = _money(line_data.get("pounds"))
        if line_data.get("rate_per_pound") is not None:
            pricing = {**pricing, "rate_per_pound": _money(line_data.get("rate_per_pound"))}
        if line_data.get("logistics_charge") is not None:
            pricing = {**pricing, "logistics_charge": _money(line_data.get("logistics_charge"))}
        if line_data.get("additional_charge") is not None:
            pricing = {**pricing, "additional_charge": _money(line_data.get("additional_charge"))}
        rev = commercial_line_revenue_from_pricing(pounds, pricing)
        comm_snapshot = {**pricing, "calculated_amount": rev, "quantity": pounds}
        pk, ak = commercial_pounds_key(aid), commercial_amount_key(aid)
        for lk, amt, qty in [(pk, 0, pounds), (ak, rev, pounds)]:
            _upsert_line(
                cursor, entry_id, lk, "revenue", amt if lk == ak else 0, qty,
                commercial_account_id=aid,
                source_system=_resolve_line_source(existing_lines, lk, is_override=_is_override(lk)),
                source_ref=_resolve_line_source_ref(existing_lines, lk),
                pricing_schedule_id=pricing.get("id"),
                rate_snapshot=comm_snapshot if lk == ak else {**comm_snapshot, "line": "pounds"},
                is_override=_is_override(lk), override_reason=_override_reason(lk),
                user_id=user_id, existing_lines=existing_lines,
            )

    if was_existing:
        _log_audit(cursor, entry_id, "updated", actor_user_id=user_id)

    cursor.execute("SELECT * FROM dr_daily_entries WHERE id = %s", (entry_id,))
    header = cursor.fetchone()
    lines = _load_entry_lines(cursor, entry_id)
    entry_shape = _lines_to_entry_shape(lines, header, accounts, wf_meta, audit_by_line=_load_line_audit_events(cursor, entry_id))
    summary = _entry_summary_from_lines(lines)
    return {"entry": entry_shape, "summary": summary}


def change_entry_workflow(
    cursor,
    org_id: int,
    entry_date: date,
    action: str,
    *,
    user_id: int | None = None,
    notes: str | None = None,
) -> dict:
    ensure_daily_revenue_cost_tables(cursor)
    row = transition_entry_status(
        cursor, org_id, entry_date, action, user_id=user_id, notes=notes, log_audit=_log_audit,
    )
    return {
        "id": int(row["id"]),
        "entry_date": row["entry_date"].isoformat() if hasattr(row["entry_date"], "isoformat") else str(row["entry_date"]),
        "status": row.get("status"),
        "locked_by": row.get("locked_by"),
        "locked_at": str(row.get("locked_at") or "") if row.get("locked_at") else None,
        "submitted_by": row.get("submitted_by"),
        "submitted_at": str(row.get("submitted_at") or "") if row.get("submitted_at") else None,
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": str(row.get("reviewed_at") or "") if row.get("reviewed_at") else None,
    }


def record_integration_import(
    cursor,
    org_id: int,
    entry_date: date,
    source_system: str,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    """Stub for future POS/Stripe/payroll imports — logs sync run + audit."""
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        """
        INSERT INTO dr_integration_sync_runs
          (organization_id, entry_date, source_system, status, records_imported, payload_json, completed_at)
        VALUES (%s, %s, %s, 'completed', 0, %s, %s)
        """,
        (org_id, entry_date, source_system, _json_dump(payload), datetime.utcnow()),
    )
    cursor.execute(
        "SELECT id FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    hdr = cursor.fetchone()
    if hdr:
        _log_audit(
            cursor, int(hdr["id"]), "import",
            source_system=source_system, actor_user_id=user_id,
            notes="Integration import stub — adapters not yet wired",
        )
    else:
        _log_schedule_audit(
            cursor, None, "import",
            user_id=user_id,
            notes=f"integration stub {source_system} for {entry_date} (no entry yet)",
        )
    return {"ok": True, "source_system": source_system, "entry_date": entry_date.isoformat()}


def preview_entry_calculations(cursor, org_id: int, entry_date: date, payload: dict, *, exclude_entry_id: int | None = None) -> dict:
    cost_settings = get_cost_settings(cursor, org_id, as_of=entry_date)
    tiers = get_rinse_wf_tiers(cursor, org_id, as_of=entry_date)
    wf_pounds = payload.get("rinse_wf_pounds", 0)
    wf_rev, wf_meta = wf_revenue_for_day(cursor, org_id, entry_date, wf_pounds, tiers, exclude_entry_id=exclude_entry_id)
    payroll = _money(payload.get("payroll_total"))
    payroll_tax = calc_payroll_tax(payroll, cost_settings)

    commercial_lines = []
    for line in payload.get("commercial_lines") or []:
        rev = commercial_line_revenue(line.get("pounds"), line.get("rate_per_pound"), line.get("logistics_charge"), line.get("additional_charge"))
        commercial_lines.append({**line, "revenue": rev})

    draft = {
        LK_SELF_SERVICE_CASH: {"amount": _money(payload.get("self_service_cash"))},
        LK_SELF_SERVICE_CARD: {"amount": _money(payload.get("self_service_card"))},
        LK_DROP_OFF_CASH: {"amount": _money(payload.get("drop_off_cash"))},
        LK_DROP_OFF_CARD: {"amount": _money(payload.get("drop_off_card"))},
        LK_RINSE_WF_AMOUNT: {"amount": wf_rev},
        LK_RINSE_HD_AMOUNT: {"amount": _money(payload.get("rinse_hd_revenue"))},
        LK_RINSE_WI_AMOUNT: {"amount": _money(payload.get("rinse_wi_revenue"))},
        LK_PAYROLL_TOTAL: {"amount": payroll},
        LK_PAYROLL_TAX: {"amount": payroll_tax},
        LK_COST_RENT: {"amount": cost_settings.get("rent_daily", 0)},
        LK_COST_INSURANCE: {"amount": cost_settings.get("insurance_daily", 0)},
        LK_COST_PROPERTY_TAX: {"amount": cost_settings.get("property_tax_daily", 0)},
        LK_COST_ELECTRICITY: {"amount": cost_settings.get("electricity_daily", 0)},
        LK_COST_WATER: {"amount": cost_settings.get("water_daily", 0)},
        LK_COST_GAS: {"amount": cost_settings.get("gas_daily", 0)},
        LK_COST_SUPPLIES: {"amount": cost_settings.get("supplies_daily", 0)},
        LK_COST_MAINTENANCE: {"amount": cost_settings.get("maintenance_daily", 0)},
        LK_COST_ADJUSTMENTS: {"amount": cost_settings.get("adjustments_daily", 0)},
    }
    for line in commercial_lines:
        aid = int(line.get("commercial_account_id") or 0)
        if aid:
            draft[commercial_amount_key(aid)] = {"amount": line.get("revenue", 0)}

    summary = _entry_summary_from_lines(draft)
    return {"summary": summary, "rinse_wf_revenue": wf_rev, "rinse_wf_meta": wf_meta, "payroll_tax_amount": payroll_tax}


# ── Dashboard ──────────────────────────────────────────────────────────────


def _period_bounds(period: str, ref_date: date, start: date | None, end: date | None) -> tuple[date, date]:
    p = (period or "daily").strip().lower()
    if p == "custom":
        if not start or not end:
            raise ValueError("start_date and end_date required for custom period")
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        return start, end
    if p == "weekly":
        week_start = ref_date - timedelta(days=ref_date.weekday())
        return week_start, week_start + timedelta(days=6)
    if p == "monthly":
        last_day = monthrange(ref_date.year, ref_date.month)[1]
        return ref_date.replace(day=1), ref_date.replace(day=last_day)
    return ref_date, ref_date


def build_dashboard(cursor, org_id: int, period: str, ref_date: date, start: date | None, end: date | None) -> dict:
    ensure_daily_revenue_cost_tables(cursor)
    start_date, end_date = _period_bounds(period, ref_date, start, end)
    cursor.execute(
        """
        SELECT e.id, e.entry_date, e.status
        FROM dr_daily_entries e
        WHERE e.organization_id = %s AND e.entry_date >= %s AND e.entry_date <= %s
        ORDER BY e.entry_date
        """,
        (org_id, start_date, end_date),
    )
    headers = cursor.fetchall() or []

    totals = {k: Decimal("0") for k in (
        "self_service", "drop_off", "rinse_wf", "rinse_hd", "rinse_wi", "commercial",
        "total_revenue", "payroll", "payroll_tax", "fixed_cost", "variable_cost", "operating", "total_cost", "profit",
    )}
    trend = []

    for hdr in headers:
        lines = _load_entry_lines(cursor, int(hdr["id"]))
        summary = _entry_summary_from_lines(lines)
        totals["self_service"] += _d(summary["self_service_revenue"])
        totals["drop_off"] += _d(summary["drop_off_revenue"])
        totals["rinse_wf"] += _d(summary["rinse_wf_revenue"])
        totals["rinse_hd"] += _d(summary["rinse_hd_revenue"])
        totals["rinse_wi"] += _d(summary["rinse_wi_revenue"])
        totals["commercial"] += _d(summary["commercial_revenue"])
        totals["total_revenue"] += _d(summary["total_revenue"])
        totals["payroll"] += _d(summary["payroll_total"])
        totals["payroll_tax"] += _d(summary["payroll_tax_amount"])
        totals["fixed_cost"] += _d(summary["fixed_cost"])
        totals["variable_cost"] += _d(summary["variable_cost"])
        totals["operating"] += _d(summary["operating_cost"])
        totals["total_cost"] += _d(summary["total_cost"])
        totals["profit"] += _d(summary["estimated_profit"])
        ed = hdr.get("entry_date")
        trend.append({
            "date": ed.isoformat() if hasattr(ed, "isoformat") else str(ed),
            "revenue": summary["total_revenue"],
            "cost": summary["total_cost"],
            "profit": summary["estimated_profit"],
            "status": hdr.get("status"),
        })

    total_rev = totals["total_revenue"]
    margin = (_d(totals["profit"]) / total_rev * Decimal("100")) if total_rev > 0 else Decimal("0")

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "revenue_by_category": {
            "self_service": _money(totals["self_service"]),
            "drop_off": _money(totals["drop_off"]),
            "rinse_wf": _money(totals["rinse_wf"]),
            "rinse_hd": _money(totals["rinse_hd"]),
            "rinse_wi": _money(totals["rinse_wi"]),
            "commercial": _money(totals["commercial"]),
        },
        "total_revenue": _money(totals["total_revenue"]),
        "payroll_cost": _money(totals["payroll"]),
        "payroll_tax": _money(totals["payroll_tax"]),
        "fixed_costs": _money(totals["fixed_cost"]),
        "variable_costs": _money(totals["variable_cost"]),
        "operating_costs": _money(totals["operating"]),
        "total_cost": _money(totals["total_cost"]),
        "estimated_profit": _money(totals["profit"]),
        "profit_margin_pct": _money(margin),
        "trend": trend,
    }
