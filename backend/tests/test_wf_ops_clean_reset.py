"""Safety tests for the WF-only operational clean reset.

Rinse HD must survive every predicate here. The reset is WF-scoped by design:
reusing the org-wide targets in ``rinse_ops_baseline_reset`` would destroy HD.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from backend.wf_ops_clean_reset import (
    ACTION_CLEAR,
    ACTION_REGISTRY_RESET,
    ACTION_RETAIN_EPOCH,
    ALLOWED_ORGANIZATION_IDS,
    APPLY_BLOCKED,
    PRESERVED_TABLES,
    REGISTRY_RESET_COLUMNS,
    REGISTRY_RETAINED_COLUMNS,
    TARGETS,
    TargetSpec,
    WF_SERVICE_PREDICATE,
    _iter_rows,
    _require_allowed_org,
    archive_target,
    build_dry_run_report,
    clear_target,
    clear_targets,
    format_dry_run_report,
    inventory_wf_clean_reset,
    registry_reset,
    registry_target,
    restore_from_archive,
    retained_targets,
    run_wf_clean_reset,
    validate_target,
)

ORG = 3

_SCHEMA = """
CREATE TABLE system_settings (
  organization_id INTEGER, skey TEXT, svalue TEXT
);
CREATE TABLE rinse_wf_service_cycles (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT,
  cycle_anchor_at TEXT, status TEXT, estimated_delivery_date TEXT
);
CREATE TABLE rinse_order_instances (
  order_instance_id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT,
  service_type TEXT, cycle_anchor_at TEXT, source_cycle_id INTEGER,
  completed_at TEXT
);
CREATE TABLE rinse_shift_monitor_day_bags (
  id INTEGER PRIMARY KEY, organization_id INTEGER, shift_date_et TEXT,
  bag_id TEXT, service_type TEXT
);
CREATE TABLE orders_staging (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT, service_type TEXT
);
CREATE TABLE rinse_folding_performance (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT
);
CREATE TABLE rinse_bag_registry (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT,
  completion_status TEXT, completed_at TEXT, completion_reason TEXT,
  first_clean_scan_at TEXT, first_clean_scan_event_id INTEGER,
  trigger_scan_at TEXT, trigger_scan_event_id INTEGER, trigger_kind TEXT,
  name_clean TEXT, weight_num REAL, service_type TEXT, date_clean TEXT,
  last_upload_batch_id INTEGER, last_staging_order_id INTEGER, created_at TEXT
);
CREATE TABLE rinse_bag_scan_events (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT,
  scanned_at_parsed TEXT
);
CREATE TABLE hd_day_bag_production (
  id INTEGER PRIMARY KEY, organization_id INTEGER, bag_id TEXT, items INTEGER
);
"""

_SEED = [
    # WF lifecycle for org 3
    ("INSERT INTO rinse_wf_service_cycles VALUES (?,?,?,?,?,?)",
     (1, ORG, "WFBAG1", "2026-09-10 08:00:00", "ACTIVE", "2026-09-12")),
    ("INSERT INTO rinse_wf_service_cycles VALUES (?,?,?,?,?,?)",
     (2, ORG, "WFBAG2", "2026-09-11 08:00:00", "COMPLETED", "2026-09-13")),
    ("INSERT INTO rinse_order_instances VALUES (?,?,?,?,?,?,?)",
     (10, ORG, "WFBAG1", "WF", "2026-09-10 08:00:00", 1, None)),
    ("INSERT INTO rinse_order_instances VALUES (?,?,?,?,?,?,?)",
     (11, ORG, "WFBAG2", None, "2026-09-11 08:00:00", 2, "2026-09-13 10:00:00")),
    # HD order instance for the same org — must survive
    ("INSERT INTO rinse_order_instances VALUES (?,?,?,?,?,?,?)",
     (12, ORG, "HDBAG1", "HD", "2026-09-11 09:00:00", None, None)),
    ("INSERT INTO rinse_shift_monitor_day_bags VALUES (?,?,?,?,?)",
     (20, ORG, "2026-09-10", "WFBAG1", "WF")),
    ("INSERT INTO rinse_shift_monitor_day_bags VALUES (?,?,?,?,?)",
     (21, ORG, "2026-09-10", "HDBAG1", "HD")),
    ("INSERT INTO orders_staging VALUES (?,?,?,?)", (30, ORG, "WFBAG1", "WF")),
    ("INSERT INTO orders_staging VALUES (?,?,?,?)", (31, ORG, "HDBAG1", "HD")),
    ("INSERT INTO rinse_folding_performance VALUES (?,?,?)", (40, ORG, "WFBAG1")),
    ("INSERT INTO rinse_folding_performance VALUES (?,?,?)", (41, ORG, "HDBAG1")),
    # Registry: one WF completed, one HD completed (reused id risk), one HD clean
    ("INSERT INTO rinse_bag_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (50, ORG, "WFBAG1", "COMPLETED", "2026-09-10 20:00:00", "CLEAN_SCAN",
      "2026-09-10 19:00:00", 900, "2026-09-10 19:30:00", 901, "clean",
      "Alice", 22.5, "WF", "2026-09-10", 77, 88, "2026-09-01 00:00:00")),
    ("INSERT INTO rinse_bag_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (51, ORG, "HDBAG1", "COMPLETED", "2026-09-11 20:00:00", "CLEAN_SCAN",
      "2026-09-11 19:00:00", 902, "2026-09-11 19:30:00", 903, "clean",
      "Bob", 0.0, "HD", "2026-09-11", 78, 89, "2026-09-01 00:00:00")),
    ("INSERT INTO rinse_bag_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (52, ORG, "HDBAG2", "INCOMPLETE", None, None, None, None, None, None, None,
      "Cara", 0.0, "HD", "2026-09-11", 79, 90, "2026-09-01 00:00:00")),
    ("INSERT INTO rinse_bag_scan_events VALUES (?,?,?,?)",
     (60, ORG, "WFBAG1", "2026-09-10 07:00:00")),
    ("INSERT INTO hd_day_bag_production VALUES (?,?,?,?)", (70, ORG, "HDBAG1", 12)),
]


class _SqliteCursor:
    """MySQL-flavoured cursor facade over sqlite for reset fixture tests."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cur = conn.cursor()

    def execute(self, sql, params=None):
        self._cur.execute(sql.replace("%s", "?"), tuple(params or ()))

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    @property
    def rowcount(self) -> int:
        return int(self._cur.rowcount or 0)

    def close(self) -> None:
        self._cur.close()


class _SqliteConn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, **_kwargs):
        return _SqliteCursor(self._conn)

    def commit(self) -> None:
        self._conn.commit()


@pytest.fixture()
def db(monkeypatch):
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.executescript(_SCHEMA)
    for sql, params in _SEED:
        raw.execute(sql, params)
    raw.commit()

    def fake_table_exists(_cursor, table: str) -> bool:
        row = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    def fake_table_has_column(_cursor, table: str, col: str) -> bool:
        if not fake_table_exists(None, table):
            return False
        cols = {r["name"] for r in raw.execute(f"PRAGMA table_info(`{table}`)")}
        return col in cols

    monkeypatch.setattr(
        "backend.wf_ops_clean_reset.table_exists", fake_table_exists
    )
    monkeypatch.setattr(
        "backend.wf_ops_clean_reset.table_has_column", fake_table_has_column
    )
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.table_exists", fake_table_exists
    )
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.table_has_column", fake_table_has_column
    )
    from backend.wf_ops_reset_epoch import invalidate_wf_reset_epoch_cache

    invalidate_wf_reset_epoch_cache()
    yield raw
    raw.close()


def _cursor(raw) -> _SqliteCursor:
    return _SqliteCursor(raw)


def _ids(raw, table: str, col: str = "id") -> set:
    return {r[0] for r in raw.execute(f"SELECT {col} FROM {table}")}


# --- static configuration guards -------------------------------------------------


def test_only_org_3_allowed():
    assert ALLOWED_ORGANIZATION_IDS == frozenset({3})
    assert _require_allowed_org(3) == 3
    for bad in (1, 4, 99):
        with pytest.raises(ValueError):
            _require_allowed_org(bad)


def test_apply_is_hard_blocked():
    assert APPLY_BLOCKED is True


def test_clear_targets_never_include_hd_or_shared_history():
    cleared = {s.table for s in clear_targets()}
    forbidden = {
        "hd_day_bag_production",
        "hd_day_bag_production_audits",
        "upload_batch_scan_events",
        "rinse_bag_scan_events",
        "upload_batches",
        "upload_batch_rows",
        "upload_conflicts",
        "rinse_shift_monitor_days",
        "rinse_shift_monitor_close_audit",
        "rinse_scrape_runs",
        "rinse_import_jobs",
        "employees",
        "users",
        "payroll_cycles",
        "checkout_log",
        "orders_final",
        "system_settings",
        "rinse_bag_registry",
        "rinse_employee_bag_session_assignments",
    }
    assert cleared.isdisjoint(forbidden)


def test_preserved_tables_are_never_targets_of_mutation():
    mutated = {
        s.table for s in TARGETS if s.action in (ACTION_CLEAR, ACTION_REGISTRY_RESET)
    }
    assert mutated.isdisjoint(set(PRESERVED_TABLES))


def test_service_scoped_tables_use_wf_predicate():
    wf_scoped = {
        "rinse_order_instances",
        "rinse_shift_monitor_day_bags",
        "rinse_cleaner_ticket_presence",
        "rinse_cleaner_ticket_presence_run_rows",
        "orders_staging",
    }
    for spec in clear_targets():
        if spec.table in wf_scoped:
            assert spec.predicate == WF_SERVICE_PREDICATE, spec.table


def test_registry_is_update_not_delete():
    spec = registry_target()
    assert spec.table == "rinse_bag_registry"
    assert spec.action == ACTION_REGISTRY_RESET
    assert spec.table not in {s.table for s in clear_targets()}
    assert "bag_id" in REGISTRY_RETAINED_COLUMNS
    assert "service_type" in REGISTRY_RETAINED_COLUMNS
    assert set(REGISTRY_RESET_COLUMNS).isdisjoint(set(REGISTRY_RETAINED_COLUMNS))


def test_strategy_d_tables_are_retained():
    retained = {s.table for s in retained_targets()}
    assert {"upload_batch_scan_events", "rinse_bag_scan_events"} <= retained
    assert {"upload_batches", "upload_batch_rows", "upload_conflicts"} <= retained


def test_session_assignments_left_retained_with_epoch_note():
    spec = next(
        s for s in TARGETS if s.table == "rinse_employee_bag_session_assignments"
    )
    assert spec.action == ACTION_RETAIN_EPOCH
    assert "service_type" in spec.notes


def test_delete_order_puts_order_instances_before_cycles():
    tables = [s.table for s in clear_targets()]
    assert tables.index("rinse_order_instances") < tables.index(
        "rinse_wf_service_cycles"
    )


def test_validate_stops_when_service_type_column_missing(monkeypatch):
    monkeypatch.setattr(
        "backend.wf_ops_clean_reset.table_exists", lambda _c, _t: True
    )
    monkeypatch.setattr(
        "backend.wf_ops_clean_reset.table_has_column",
        lambda _c, _t, col: col != "service_type",
    )
    spec = TargetSpec(
        "rinse_order_instances",
        ACTION_CLEAR,
        WF_SERVICE_PREDICATE,
        requires_columns=("organization_id", "service_type"),
    )
    reason = validate_target(None, spec)
    assert reason and "service_type" in reason


# --- inventory / dry-run ---------------------------------------------------------


def test_inventory_counts_wf_only_and_proves_hd_untouched(db):
    inv = inventory_wf_clean_reset(_cursor(db), ORG)
    assert inv["safe"] is True
    assert inv["stop_reasons"] == []
    assert inv["scope_protection"]["hd_rows_in_clear_scope"] == 0
    assert inv["scope_protection"]["ok"] is True

    by_table = {t["table"]: t for t in inv["targets"]}
    # WFBAG1 (WF) + WFBAG2 (NULL service_type defaults to WF); HDBAG1 excluded.
    assert by_table["rinse_order_instances"]["rows_to_clear"] == 2
    assert by_table["rinse_order_instances"]["non_wf_rows_protected"] == 1
    assert by_table["rinse_shift_monitor_day_bags"]["rows_to_clear"] == 1
    assert by_table["orders_staging"]["rows_to_clear"] == 1
    assert by_table["rinse_wf_service_cycles"]["rows_to_clear"] == 2
    # Folding is registry-scoped: the HD-now bag's row is retained, not cleared.
    assert by_table["rinse_folding_performance"]["rows_to_clear"] == 1
    assert by_table["rinse_folding_performance"]["hd_now_bags_retained"] == 1
    # Registry updates WF bags only; HD completion survives.
    assert by_table["rinse_bag_registry"]["rows_to_update"] == 1
    assert by_table["rinse_bag_registry"]["rows_to_clear"] == 0
    assert by_table["rinse_bag_registry"]["non_wf_rows_reset"] == 0
    assert by_table["rinse_bag_registry"]["hd_rows_in_scope"] is None
    assert inv["scope_protection"]["non_wf_registry_rows_reset"]["rinse_bag_registry"] == 0
    # Strategy D
    assert by_table["rinse_bag_scan_events"]["rows_retained"] == 1
    assert by_table["rinse_bag_scan_events"]["rows_to_clear"] == 0
    assert inv["preserved_counts"]["hd_day_bag_production"] == 1


def test_inventory_stops_when_predicate_would_catch_hd(db, monkeypatch):
    # Simulate a broken predicate that forgets the service filter.
    broken = TargetSpec(
        "rinse_order_instances",
        ACTION_CLEAR,
        "organization_id = %s",
        requires_columns=("organization_id", "service_type"),
    )
    monkeypatch.setattr("backend.wf_ops_clean_reset.TARGETS", (broken,))
    inv = inventory_wf_clean_reset(_cursor(db), ORG)
    assert inv["safe"] is False
    assert any("non-WF rows" in r for r in inv["stop_reasons"])
    assert inv["scope_protection"]["hd_rows_in_clear_scope"] == 1


def test_dry_run_report_has_all_required_sections(db, tmp_path):
    report = build_dry_run_report(_cursor(db), ORG, archive_root=tmp_path)
    for key in (
        "current_state",
        "scope_protection",
        "archive_plan",
        "samples",
        "resurrection_residual",
        "registry_reset",
        "epoch",
    ):
        assert key in report, key
    assert report["dry_run"] is True
    assert report["applied"] is False
    assert report["apply_blocked"] is True
    assert report["epoch"]["current_value"] is None
    assert report["epoch"]["maintenance_on"] is False

    display_ids = [s["order_display_id"] for s in report["samples"]["order_instances"]]
    assert "WFBAG1-OI-09122026" in display_ids
    assert all("HDBAG1" not in str(d) for d in display_ids)

    residual = {r["table"] for r in report["resurrection_residual"]}
    assert "rinse_bag_scan_events" in residual
    assert "upload_batch_scan_events" in residual

    text = format_dry_run_report(report)
    assert "SCOPE PROTECTION" in text
    assert "RESURRECTION RESIDUAL" in text
    assert "WFBAG1-OI-09122026" in text


def test_run_wf_clean_reset_dry_run_mutates_nothing(db, tmp_path):
    before = _ids(db, "rinse_order_instances", "order_instance_id")
    report = run_wf_clean_reset(
        _SqliteConn(db), ORG, dry_run=True, archive_root=tmp_path
    )
    assert report["applied"] is False
    assert _ids(db, "rinse_order_instances", "order_instance_id") == before
    assert not list(Path(tmp_path).glob("**/*.jsonl.gz"))


def test_apply_refused_while_blocked(db, tmp_path, monkeypatch):
    monkeypatch.setenv("WF_CLEAN_RESET_APPLY_UNLOCK", "1")
    report = run_wf_clean_reset(
        _SqliteConn(db), ORG, dry_run=False, archive_root=tmp_path
    )
    assert report["applied"] is False
    assert "APPLY_BLOCKED" in report["error"]
    assert _ids(db, "rinse_order_instances", "order_instance_id") == {10, 11, 12}


def test_apply_requires_unlock_env_and_maintenance(db, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.wf_ops_clean_reset.APPLY_BLOCKED", False)
    monkeypatch.delenv("WF_CLEAN_RESET_APPLY_UNLOCK", raising=False)
    report = run_wf_clean_reset(
        _SqliteConn(db), ORG, dry_run=False, archive_root=tmp_path
    )
    assert report["applied"] is False
    assert "WF_CLEAN_RESET_APPLY_UNLOCK" in report["error"]

    monkeypatch.setenv("WF_CLEAN_RESET_APPLY_UNLOCK", "1")
    report = run_wf_clean_reset(
        _SqliteConn(db), ORG, dry_run=False, archive_root=tmp_path
    )
    assert report["applied"] is False
    assert "wf_ops_maintenance" in report["error"]
    assert _ids(db, "rinse_order_instances", "order_instance_id") == {10, 11, 12}


# --- archive / clear / registry / restore ----------------------------------------


def test_clear_targets_delete_wf_rows_and_leave_hd(db):
    cur = _cursor(db)
    for spec in clear_targets():
        if spec.table in {
            "rinse_order_instances",
            "rinse_shift_monitor_day_bags",
            "orders_staging",
            "rinse_folding_performance",
            "rinse_wf_service_cycles",
        }:
            clear_target(cur, spec, ORG)
    db.commit()

    assert _ids(db, "rinse_order_instances", "order_instance_id") == {12}
    assert _ids(db, "rinse_shift_monitor_day_bags") == {21}
    assert _ids(db, "orders_staging") == {31}
    assert _ids(db, "rinse_folding_performance") == {41}
    assert _ids(db, "rinse_wf_service_cycles") == set()
    # Strategy D + HD production untouched.
    assert _ids(db, "rinse_bag_scan_events") == {60}
    assert _ids(db, "hd_day_bag_production") == {70}


def test_registry_reset_updates_completion_and_keeps_identity(db):
    cur = _cursor(db)
    updated = registry_reset(cur, ORG)
    db.commit()
    assert updated == 1  # WF only

    rows = {
        r["bag_id"]: dict(r)
        for r in db.execute("SELECT * FROM rinse_bag_registry")
    }
    assert set(rows) == {"WFBAG1", "HDBAG1", "HDBAG2"}  # no row deleted
    wf = rows["WFBAG1"]
    assert wf["completion_status"] == "INCOMPLETE"
    for col in REGISTRY_RESET_COLUMNS:
        if col == "completion_status":
            continue
        assert wf[col] is None, col
    # Identity / config retained.
    assert wf["name_clean"] == "Alice"
    assert wf["weight_num"] == 22.5
    assert wf["service_type"] == "WF"
    assert wf["last_upload_batch_id"] == 77
    assert wf["created_at"] == "2026-09-01 00:00:00"
    # HD registry completion must survive (do not wipe Hang Dry state).
    assert rows["HDBAG1"]["completion_status"] == "COMPLETED"
    assert rows["HDBAG1"]["service_type"] == "HD"
    assert rows["HDBAG2"]["completion_status"] == "INCOMPLETE"


def test_archive_clear_restore_roundtrip(db, tmp_path):
    cur = _cursor(db)
    spec = next(s for s in clear_targets() if s.table == "rinse_order_instances")
    dest = tmp_path / "tables" / "rinse_order_instances.jsonl.gz"

    archived = archive_target(cur, spec, ORG, dest)
    assert archived == 2
    assert dest.is_file()

    cleared = clear_target(cur, spec, ORG)
    db.commit()
    assert cleared == 2
    assert _ids(db, "rinse_order_instances", "order_instance_id") == {12}

    restored = restore_from_archive(_cursor(db), tmp_path)
    db.commit()
    assert restored == {"rinse_order_instances": 2}
    assert _ids(db, "rinse_order_instances", "order_instance_id") == {10, 11, 12}


def test_archive_never_writes_hd_rows(db, tmp_path):
    cur = _cursor(db)
    spec = next(s for s in clear_targets() if s.table == "orders_staging")
    dest = tmp_path / "tables" / "orders_staging.jsonl.gz"
    archive_target(cur, spec, ORG, dest)
    assert dest.read_bytes()
    with gzip.open(dest, "rt", encoding="utf-8") as fh:
        restored_rows = [json.loads(line) for line in fh if line.strip()]
    assert [r["bag_id"] for r in restored_rows] == ["WFBAG1"]


def test_iter_rows_pages_past_the_first_chunk(db):
    for n in range(13, 33):
        db.execute(
            "INSERT INTO rinse_order_instances VALUES (?,?,?,?,?,?,?)",
            (n, ORG, f"WFBAG{n}", "WF", "2026-09-12 08:00:00", None, None),
        )
    db.commit()
    spec = next(s for s in clear_targets() if s.table == "rinse_order_instances")
    rows = list(_iter_rows(_cursor(db), spec, ORG, chunk=5))
    assert len(rows) == 22
    assert all(str(r.get("service_type") or "WF").upper() == "WF" for r in rows)
