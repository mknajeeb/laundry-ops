"""SQLite-backed integration tests for Daily Revenue & Cost v2."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from unittest.mock import patch

import pytest

from backend.daily_revenue_cost import (
    change_entry_workflow,
    get_daily_entry,
    save_cost_settings,
    save_daily_entry,
    save_rinse_wf_tiers,
    update_commercial_account,
)
from backend.daily_revenue_cost_constants import ENTRY_STATUS_LOCKED, ENTRY_STATUS_OPEN
from backend.daily_revenue_cost import wf_revenue_for_day
from backend.daily_revenue_cost_schema import (
    V1_MIGRATION_ERROR,
    assert_no_overlapping_schedules,
    detect_v1_schema,
    resolve_single_active_schedule,
    schedules_overlap,
)


class SqliteDictCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        if params is None:
            self.conn.execute(sql)
        else:
            self.conn.execute(sql, params)
        return self

    @property
    def lastrowid(self):
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def fetchone(self):
        row = self.conn.execute("SELECT * FROM (__last__)").fetchone() if False else None
        cur = self.conn.execute("SELECT * FROM sqlite_temp_master LIMIT 0")  # noop anchor
        # fetch from last executed select — sqlite3 stores in cursor
        c2 = self.conn.cursor()
        c2.execute("SELECT 1")
        return None

    def fetchall(self):
        return []


def _adapt_sql(sql: str) -> str:
    return (
        sql.replace("%s", "?")
        .replace("AUTO_INCREMENT", "AUTOINCREMENT")
        .replace("INT AUTOINCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        .replace("BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        .replace("BIGINT AUTOINCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        .replace("TINYINT(1)", "INTEGER")
        .replace("DECIMAL(12, 2)", "REAL")
        .replace("DECIMAL(10, 4)", "REAL")
        .replace("DECIMAL(8, 4)", "REAL")
        .replace("JSON", "TEXT")
        .replace("DATETIME", "TEXT")
        .replace("ENGINE=InnoDB", "")
        .replace("ON UPDATE CURRENT_TIMESTAMP", "")
    )


class DictConnection:
    """Minimal sqlite connection wrapper with dictionary rows."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    def cursor(self, dictionary=True):
        cur = DictConnectionCursor(self._conn)
        cur._dict_connection = self
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class DictConnectionCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_result = []

    def execute(self, sql, params=None):
        sql = _adapt_sql(sql)
        if params is None:
            cur = self._conn.execute(sql)
        else:
            cur = self._conn.execute(sql, tuple(params))
        if cur.description:
            cols = [d[0] for d in cur.description]
            self._last_result = [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            self._last_result = []
        return self

    @property
    def lastrowid(self):
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def fetchone(self):
        if not self._last_result:
            return None
        return self._last_result.pop(0)

    def fetchall(self):
        rows = self._last_result
        self._last_result = []
        return rows

    def close(self):
        pass


def _create_v2_tables(cursor):
    stmts = [
        """CREATE TABLE dr_commercial_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL, name TEXT NOT NULL,
            external_ref TEXT, active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT)""",
        """CREATE TABLE dr_commercial_pricing_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, commercial_account_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL, effective_to TEXT,
            billing_model TEXT DEFAULT 'per_lb', rate_per_pound REAL, flat_amount REAL,
            logistics_charge REAL DEFAULT 0, additional_charge REAL DEFAULT 0,
            notes TEXT, created_by INTEGER, created_at TEXT)""",
        """CREATE TABLE dr_rinse_wf_pricing_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL, effective_to TEXT, name TEXT,
            created_by INTEGER, created_at TEXT)""",
        """CREATE TABLE dr_rinse_wf_tier_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER NOT NULL,
            tier_number INTEGER NOT NULL, max_lbs INTEGER, rate_per_lb REAL DEFAULT 0)""",
        """CREATE TABLE dr_cost_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL, effective_to TEXT,
            payroll_tax_pct REAL, payroll_tax_daily_fixed REAL,
            rent_daily REAL DEFAULT 0, insurance_daily REAL DEFAULT 0, property_tax_daily REAL DEFAULT 0,
            electricity_daily REAL DEFAULT 0, water_daily REAL DEFAULT 0, gas_daily REAL DEFAULT 0,
            supplies_daily REAL DEFAULT 0, maintenance_daily REAL DEFAULT 0, adjustments_daily REAL DEFAULT 0,
            created_by INTEGER, created_at TEXT)""",
        """CREATE TABLE dr_daily_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL, entry_date TEXT NOT NULL,
            status TEXT DEFAULT 'open', created_by INTEGER, created_at TEXT,
            modified_by INTEGER, modified_at TEXT, locked_by INTEGER, locked_at TEXT,
            submitted_by INTEGER, submitted_at TEXT, reviewed_by INTEGER, reviewed_at TEXT, review_notes TEXT)""",
        """CREATE TABLE dr_daily_entry_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, daily_entry_id INTEGER NOT NULL,
            line_key TEXT NOT NULL, line_category TEXT NOT NULL, amount REAL DEFAULT 0, quantity REAL,
            commercial_account_id INTEGER, source_system TEXT DEFAULT 'manual', source_ref TEXT,
            source_captured_at TEXT, source_payload TEXT, is_manual_override INTEGER DEFAULT 0,
            override_reason TEXT, overridden_by INTEGER, overridden_at TEXT,
            pricing_schedule_id INTEGER, rate_snapshot_json TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(daily_entry_id, line_key))""",
        """CREATE TABLE dr_entry_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, daily_entry_id INTEGER,
            event_type TEXT NOT NULL, line_key TEXT, field_name TEXT,
            old_value TEXT, new_value TEXT, source_system TEXT,
            actor_user_id INTEGER, notes TEXT, created_at TEXT)""",
        """CREATE TABLE dr_integration_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL, source_system TEXT NOT NULL, status TEXT DEFAULT 'pending',
            records_imported INTEGER DEFAULT 0, error_message TEXT, payload_json TEXT,
            started_at TEXT, completed_at TEXT)""",
    ]
    for s in stmts:
        cursor.execute(s)


@pytest.fixture
def drc_db():
    conn = DictConnection()
    cursor = conn.cursor()
    _create_v2_tables(cursor)
    with patch("backend.daily_revenue_cost.table_exists", return_value=True), patch(
        "backend.daily_revenue_cost.assert_v2_safe_bootstrap"
    ), patch("backend.daily_revenue_cost.ensure_daily_revenue_cost_tables"), patch(
        "backend.daily_revenue_cost._seed_commercial_accounts"
    ), patch(
        "backend.daily_revenue_cost._seed_wf_pricing"
    ):
        # seed minimal org data
        cursor.execute(
            "INSERT INTO dr_commercial_accounts (organization_id, name, active, sort_order) VALUES (1, 'DHS - Clarkson', 1, 0)"
        )
        acct_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO dr_commercial_pricing_schedules
               (commercial_account_id, effective_from, billing_model, rate_per_pound, logistics_charge, additional_charge)
               VALUES (?, '2026-01-01', 'per_lb', 1.0, 10, 5)""",
            (acct_id,),
        )
        cursor.execute(
            "INSERT INTO dr_rinse_wf_pricing_schedules (organization_id, effective_from, name) VALUES (1, '2026-01-01', 'Default')"
        )
        sched_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb) VALUES (?, 1, 5000, 1.0)",
            (sched_id,),
        )
        cursor.execute(
            "INSERT INTO dr_rinse_wf_tier_lines (schedule_id, tier_number, max_lbs, rate_per_lb) VALUES (?, 2, NULL, 0.95)",
            (sched_id,),
        )
        cursor.execute(
            """INSERT INTO dr_cost_schedules
               (organization_id, effective_from, payroll_tax_pct, rent_daily, electricity_daily)
               VALUES (1, '2026-01-01', 10, 100, 50)"""
        )
        conn.commit()
        yield conn, cursor


def test_schedules_overlap_logic():
    assert schedules_overlap(date(2026, 1, 1), None, date(2026, 6, 1), None)
    assert not schedules_overlap(date(2026, 1, 1), date(2026, 3, 31), date(2026, 4, 1), None)


def test_detect_v1_schema_flags_legacy():
    conn = DictConnection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE dr_cost_settings (organization_id INTEGER PRIMARY KEY)")
    with patch("backend.daily_revenue_cost_schema.table_exists", side_effect=lambda c, t: t == "dr_cost_settings"):
        with patch("backend.daily_revenue_cost_schema.table_has_column", return_value=False):
            assert detect_v1_schema(cursor) is True


def test_v1_migration_error_message():
    assert "v1 schema detected" in V1_MIGRATION_ERROR.lower()


def test_locked_entry_rejects_save(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 1)
    save_daily_entry(cursor, 1, entry_date, {"self_service_cash": 100, "payroll_total": 0, "rinse_wf_pounds": 0}, user_id=1)
    change_entry_workflow(cursor, 1, entry_date, "lock", user_id=1)
    with pytest.raises(ValueError, match="cannot be edited"):
        save_daily_entry(cursor, 1, entry_date, {"self_service_cash": 200, "payroll_total": 0, "rinse_wf_pounds": 0}, user_id=1)


def test_audit_created_on_update(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 2)
    save_daily_entry(cursor, 1, entry_date, {"self_service_cash": 50, "payroll_total": 0, "rinse_wf_pounds": 0}, user_id=1)
    save_daily_entry(cursor, 1, entry_date, {"self_service_cash": 75, "payroll_total": 0, "rinse_wf_pounds": 0}, user_id=1)
    cursor.execute("SELECT event_type FROM dr_entry_audit_events")
    events = [r["event_type"] for r in cursor.fetchall()]
    assert "created" in events
    assert "updated" in events


def test_historical_pricing_frozen_after_maintenance_change(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 3)
    save_daily_entry(
        cursor, 1, entry_date,
        {
            "commercial_lines": [{"commercial_account_id": 1, "pounds": 100}],
            "payroll_total": 0,
            "rinse_wf_pounds": 0,
        },
        user_id=1,
    )
    before = get_daily_entry(cursor, 1, entry_date)
    rev_before = before["entry"]["commercial_lines"][0]["revenue"]
    assert rev_before == 115.0  # 100*1 + 10 + 5

    update_commercial_account(cursor, 1, 1, {"rate_per_pound": 5.0, "effective_from": "2026-08-01"}, user_id=1)
    after = get_daily_entry(cursor, 1, entry_date)
    rev_after = after["entry"]["commercial_lines"][0]["revenue"]
    assert rev_after == rev_before


def test_wf_line_stores_pricing_snapshot(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 4)
    save_daily_entry(cursor, 1, entry_date, {"rinse_wf_pounds": 100, "payroll_total": 0}, user_id=1)
    cursor.execute(
        "SELECT pricing_schedule_id, rate_snapshot_json, amount, quantity FROM dr_daily_entry_lines WHERE line_key = 'revenue.rinse_wf.amount'"
    )
    row = cursor.fetchone()
    assert row["pricing_schedule_id"] is not None
    snap = json.loads(row["rate_snapshot_json"])
    assert snap["calculated_amount"] == row["amount"]
    assert snap["quantity"] == row["quantity"]


def test_cost_schedule_effective_resolution(drc_db):
    conn, cursor = drc_db
    save_cost_settings(cursor, 1, {"rent_daily": 200, "electricity_daily": 80, "payroll_tax_pct": 8}, user_id=1, effective_from=date(2026, 8, 1))
    entry_date = date(2026, 8, 2)
    save_daily_entry(cursor, 1, entry_date, {"payroll_total": 1000, "rinse_wf_pounds": 0}, user_id=1)
    cursor.execute("SELECT amount FROM dr_daily_entry_lines WHERE line_key = 'cost.fixed.rent'")
    assert cursor.fetchone()["amount"] == 200.0


def test_overlapping_commercial_schedule_rejected(drc_db):
    conn, cursor = drc_db
    cursor.execute(
        """INSERT INTO dr_commercial_pricing_schedules
           (commercial_account_id, effective_from, effective_to, billing_model, rate_per_pound)
           VALUES (1, '2026-05-01', '2026-12-31', 'per_lb', 2.0)"""
    )
    with pytest.raises(ValueError, match="Overlapping"):
        assert_no_overlapping_schedules(
            cursor,
            table="dr_commercial_pricing_schedules",
            scope_column="commercial_account_id",
            scope_id=1,
            effective_from=date(2026, 7, 1),
            effective_to=None,
        )


def test_mtd_wf_pounds_uses_entry_date(drc_db):
    """MTD accumulation uses entry_date within the month, not calendar today."""
    conn, cursor = drc_db
    save_daily_entry(cursor, 1, date(2026, 7, 1), {"rinse_wf_pounds": 4800, "payroll_total": 0}, user_id=1)
    day_rev, meta = wf_revenue_for_day(cursor, 1, date(2026, 7, 5), 400)
    assert meta["mtd_pounds_before"] == 4800.0
    assert meta["mtd_pounds_after"] == 5200.0
    assert day_rev == 390.0  # tier threshold crossing incremental


def test_close_schedule_sets_effective_to(drc_db):
    conn, cursor = drc_db
    update_commercial_account(
        cursor, 1, 1,
        {"rate_per_pound": 2.0, "effective_from": "2026-08-01"},
        user_id=1,
    )
    cursor.execute(
        "SELECT effective_to FROM dr_commercial_pricing_schedules WHERE effective_from = '2026-01-01'"
    )
    assert cursor.fetchone()["effective_to"] == "2026-07-31"


def test_overlapping_wf_schedule_rejected(drc_db):
    conn, cursor = drc_db
    cursor.execute(
        """INSERT INTO dr_rinse_wf_pricing_schedules
           (organization_id, effective_from, effective_to, name)
           VALUES (1, '2026-05-01', '2026-12-31', 'Overlap')"""
    )
    with pytest.raises(ValueError, match="Overlapping"):
        assert_no_overlapping_schedules(
            cursor,
            table="dr_rinse_wf_pricing_schedules",
            scope_column="organization_id",
            scope_id=1,
            effective_from=date(2026, 7, 1),
            effective_to=None,
        )


def test_ambiguous_active_schedule_raises(drc_db):
    conn, cursor = drc_db
    cursor.execute(
        """INSERT INTO dr_commercial_pricing_schedules
           (commercial_account_id, effective_from, effective_to, billing_model, rate_per_pound)
           VALUES (1, '2026-07-01', NULL, 'per_lb', 3.0)"""
    )
    with pytest.raises(ValueError, match="Ambiguous pricing"):
        resolve_single_active_schedule(
            cursor,
            table="dr_commercial_pricing_schedules",
            scope_column="commercial_account_id",
            scope_id=1,
            as_of=date(2026, 7, 10),
        )


def test_same_day_commercial_account_update(drc_db):
    """Same-day rate edit must fetch account row before pricing lookup (MySQL unread-result guard)."""
    conn, cursor = drc_db
    from backend.business_time import business_today

    eff = business_today().isoformat()
    cursor.execute(
        "UPDATE dr_commercial_pricing_schedules SET effective_from = ? WHERE commercial_account_id = 1",
        (eff,),
    )
    conn.commit()
    out = update_commercial_account(
        cursor, 1, 1,
        {"rate_per_pound": 0.80, "default_logistics_charge": 0, "default_additional_charge": 0},
        user_id=1,
    )
    assert out["rate_per_pound"] == 0.80


def test_override_preserves_import_source(drc_db):
    conn, cursor = drc_db
    from backend.daily_revenue_cost_constants import LK_PAYROLL_TOTAL, SOURCE_PAYROLL

    entry_date = date(2026, 7, 11)
    save_daily_entry(cursor, 1, entry_date, {"payroll_total": 500, "rinse_wf_pounds": 0}, user_id=1)
    cursor.execute("SELECT id FROM dr_daily_entries WHERE entry_date = '2026-07-11'")
    entry_id = cursor.fetchone()["id"]
    cursor.execute(
        "UPDATE dr_daily_entry_lines SET source_system = ?, source_ref = 'run-99' WHERE daily_entry_id = ? AND line_key = ?",
        (SOURCE_PAYROLL, entry_id, LK_PAYROLL_TOTAL),
    )
    conn.commit()
    save_daily_entry(
        cursor, 1, entry_date,
        {
            "payroll_total": 642.15,
            "rinse_wf_pounds": 0,
            "overrides": {LK_PAYROLL_TOTAL: {"is_manual_override": True, "reason": "Bonus adjustment"}},
        },
        user_id=1,
    )
    cursor.execute(
        "SELECT source_system, is_manual_override, override_reason FROM dr_daily_entry_lines WHERE daily_entry_id = ? AND line_key = ?",
        (entry_id, LK_PAYROLL_TOTAL),
    )
    row = cursor.fetchone()
    assert row["source_system"] == SOURCE_PAYROLL
    assert int(row["is_manual_override"]) == 1
    assert row["override_reason"] == "Bonus adjustment"


def test_line_sources_returned_on_get_entry(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 10)
    save_daily_entry(cursor, 1, entry_date, {"payroll_total": 500, "rinse_wf_pounds": 0}, user_id=1)
    cursor.execute("SELECT id FROM dr_daily_entries WHERE entry_date = '2026-07-10'")
    entry_id = cursor.fetchone()["id"]
    cursor.execute(
        """UPDATE dr_daily_entry_lines SET source_system = 'payroll', source_ref = 'run-42',
           source_captured_at = '2026-07-10 08:00:00' WHERE daily_entry_id = ? AND line_key = 'payroll.total'""",
        (entry_id,),
    )
    conn.commit()
    out = get_daily_entry(cursor, 1, entry_date)
    src = out["entry"]["line_sources"]["payroll.total"]
    assert src["source_system"] == "payroll"
    assert src["source_ref"] == "run-42"


PAYROLL_SUGGESTION = {
    "line_key": "payroll.total",
    "source_system": "payroll",
    "amount": 642.15,
    "source_ref": "payroll-day:2026-07-12:sessions=1,2",
    "source_captured_at": "2026-07-12 08:00:00",
    "source_payload": {
        "entry_date": "2026-07-12",
        "record_count": 2,
        "total_gross": 642.15,
        "calculation": "sum(approved_hours * hourly_rate)",
        "records": [{"shift_session_id": 1, "gross": 300}, {"shift_session_id": 2, "gross": 342.15}],
    },
}


def test_payroll_suggestion_populates_draft_entry(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 12)
    with patch("backend.daily_revenue_cost.fetch_payroll_total_suggestion", return_value=PAYROLL_SUGGESTION):
        out = get_daily_entry(cursor, 1, entry_date)
    assert out["integration_suggestions"]["suggestions"]["payroll.total"]["amount"] == 642.15
    assert out["entry"]["payroll_total"] == 642.15
    src = out["entry"]["line_sources"]["payroll.total"]
    assert src["source_system"] == "payroll"
    assert src["source_ref"].startswith("payroll-day:2026-07-12")


def test_no_payroll_suggestion_when_no_data(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 13)
    with patch("backend.daily_revenue_cost.fetch_payroll_total_suggestion", return_value=None):
        out = get_daily_entry(cursor, 1, entry_date)
    assert out["integration_suggestions"]["suggestions"] == {}
    assert out["entry"]["payroll_total"] == 0


def test_manual_override_preserves_value_with_suggestion_available(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 14)
    save_daily_entry(cursor, 1, entry_date, {"payroll_total": 500, "rinse_wf_pounds": 0}, user_id=1)
    cursor.execute("SELECT id FROM dr_daily_entries WHERE entry_date = '2026-07-14'")
    entry_id = cursor.fetchone()["id"]
    cursor.execute(
        """UPDATE dr_daily_entry_lines SET source_system = 'payroll', is_manual_override = 1,
           override_reason = 'Manager adjustment' WHERE daily_entry_id = ? AND line_key = 'payroll.total'""",
        (entry_id,),
    )
    conn.commit()
    with patch("backend.daily_revenue_cost.fetch_payroll_total_suggestion", return_value=PAYROLL_SUGGESTION):
        out = get_daily_entry(cursor, 1, entry_date)
    assert out["entry"]["payroll_total"] == 500.0
    assert out["integration_suggestions"]["payroll_blocked_by_override"] is True
    assert out["integration_suggestions"]["suggestions"]["payroll.total"]["amount"] == 642.15


def test_save_applies_payroll_source_metadata(drc_db):
    conn, cursor = drc_db
    entry_date = date(2026, 7, 15)
    with patch("backend.daily_revenue_cost.fetch_payroll_total_suggestion", return_value=PAYROLL_SUGGESTION):
        save_daily_entry(
            cursor, 1, entry_date,
            {"payroll_total": 642.15, "rinse_wf_pounds": 0},
            user_id=1,
        )
        out = get_daily_entry(cursor, 1, entry_date)
    src = out["entry"]["line_sources"]["payroll.total"]
    assert src["source_system"] == "payroll"
    assert src["source_ref"].startswith("payroll-day:")
    assert src["source_payload"]["total_gross"] == 642.15


def test_dashboard_totals_separate_fixed_variable(drc_db):
    conn, cursor = drc_db
    from backend.daily_revenue_cost import build_dashboard

    save_daily_entry(
        cursor, 1, date(2026, 7, 5),
        {
            "self_service_cash": 1000,
            "payroll_total": 500,
            "rinse_wf_pounds": 0,
            "commercial_lines": [{"commercial_account_id": 1, "pounds": 0, "logistics_charge": 0, "additional_charge": 0}],
        },
        user_id=1,
    )
    dash = build_dashboard(cursor, 1, "daily", date(2026, 7, 5), None, None)
    assert dash["total_revenue"] == 1000.0
    assert dash["payroll_cost"] == 500.0
    assert dash["payroll_tax"] == 50.0
    assert dash["fixed_costs"] == 100.0
    assert dash["variable_costs"] == 50.0
    assert dash["total_cost"] == 700.0
    assert dash["estimated_profit"] == 300.0
    assert dash["profit_margin_pct"] == 30.0
