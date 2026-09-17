"""Tests for lifecycle-safe scan retention (no production MySQL)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_scan_retention import (
    APPLY_BLOCKED,
    MIN_CANONICAL_RETENTION_DAYS,
    MIN_UPLOAD_RETENTION_DAYS,
    RetentionConfig,
    _clamp_days,
    _select_canonical_candidate_ids,
    apply_scan_retention,
    cutoff_datetime_et,
    load_protected_bag_ids,
    plan_scan_retention,
    resolve_retention_config,
    steady_state_projection,
)


def _sqlite():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE rinse_wf_service_cycles (
          id INTEGER PRIMARY KEY, organization_id INT, bag_id TEXT, status TEXT
        );
        CREATE TABLE rinse_order_instances (
          order_instance_id INTEGER PRIMARY KEY, organization_id INT, bag_id TEXT,
          service_type TEXT, completed_at TEXT
        );
        CREATE TABLE hd_day_bag_production (
          id INTEGER PRIMARY KEY, organization_id INT, bag_id TEXT
        );
        CREATE TABLE rinse_bag_scan_events (
          id INTEGER PRIMARY KEY, organization_id INT, bag_id TEXT,
          scanned_at_parsed TEXT, scan_index INT
        );
        CREATE TABLE system_settings (
          organization_id INT, skey TEXT, svalue TEXT,
          PRIMARY KEY (organization_id, skey)
        );
        """
    )
    return conn


class _DictCursor:
    """Thin sqlite adapter mimicking mysql dictionary cursor."""

    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()
        self.rowcount = 0
        self.connection = conn

    def execute(self, sql, params=()):
        sql2 = sql
        # sqlite uses ? ; convert %s
        if "%s" in sql2:
            sql2 = sql2.replace("%s", "?")
        # strip EXPLAIN for sqlite
        if sql2.strip().upper().startswith("EXPLAIN"):
            self._rows = []
            return
        self._cur.execute(sql2, params)
        self.rowcount = self._cur.rowcount

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    def close(self):
        self._cur.close()


def test_clamp_respects_floors():
    n, note = _clamp_days(3, MIN_UPLOAD_RETENTION_DAYS, label="upload")
    assert n == MIN_UPLOAD_RETENTION_DAYS
    assert note
    n2, note2 = _clamp_days(45, MIN_UPLOAD_RETENTION_DAYS, label="upload")
    assert n2 == 45 and note2 is None


def test_steady_state_projection_from_measured_rate():
    p = steady_state_projection(daily_rows=389_047, avg_bytes=388.0, retention_days=30)
    assert p["estimated_rows"] == 11_671_410
    assert p["estimated_gb"] > 4.0


def test_protected_bags_include_active_open_oi_and_hd():
    conn = _sqlite()
    cur = _DictCursor(conn)
    cur.execute(
        "INSERT INTO rinse_wf_service_cycles VALUES (1,3,'BAG_A','ACTIVE')"
    )
    cur.execute(
        "INSERT INTO rinse_wf_service_cycles VALUES (2,3,'BAG_B','COMPLETED')"
    )
    cur.execute(
        "INSERT INTO rinse_order_instances VALUES (1,3,'BAG_C','WF',NULL)"
    )
    cur.execute(
        "INSERT INTO rinse_order_instances VALUES (2,3,'BAG_D','WF','2026-09-01')"
    )
    cur.execute("INSERT INTO hd_day_bag_production VALUES (1,3,'BAG_HD')")
    with patch("backend.rinse_scan_retention.table_exists", return_value=True), patch(
        "backend.rinse_scan_retention.table_has_column", return_value=True
    ):
        bags = load_protected_bag_ids(cur, 3)
    assert bags == {"BAG_A", "BAG_C", "BAG_HD"}


def test_canonical_select_skips_protected_and_respects_cutoff_and_epoch():
    conn = _sqlite()
    cur = _DictCursor(conn)
    # id, org, bag, scanned_at, scan_index
    rows = [
        (1, 3, "OLD", "2026-01-01 10:00:00", 1),
        (2, 3, "ACTIVE_BAG", "2026-01-01 10:00:00", 1),  # protected
        (3, 3, "RECENT", "2026-09-10 10:00:00", 1),  # after cutoff
        (4, 3, "POST_EPOCH", "2026-09-01 12:00:00", 1),  # after epoch
        (5, 3, "ELIGIBLE", "2026-06-01 10:00:00", 1),
    ]
    for r in rows:
        cur.execute("INSERT INTO rinse_bag_scan_events VALUES (?,?,?,?,?)", r)

    cutoff = datetime(2026, 8, 1, 0, 0, 0)
    epoch = datetime(2026, 9, 1, 0, 0, 0)
    with patch("backend.rinse_scan_retention.table_exists", return_value=True):
        ids = _select_canonical_candidate_ids(
            cur,
            3,
            cutoff=cutoff,
            after_id=0,
            batch_size=50,
            protected={"ACTIVE_BAG"},
            epoch_wall=epoch,
        )
    # OLD (before cutoff and epoch), ELIGIBLE (before cutoff and epoch)
    # POST_EPOCH skipped (at/after epoch), ACTIVE protected, RECENT after cutoff
    assert set(ids) == {1, 5}


def test_apply_blocked_even_when_enabled(monkeypatch):
    monkeypatch.setenv("RINSE_SCAN_RETENTION_APPLY_UNLOCK", "1")
    conn = _sqlite()
    cur = _DictCursor(conn)
    cfg = RetentionConfig(organization_id=3, enabled=True)
    with patch(
        "backend.rinse_scan_retention.plan_scan_retention",
        return_value={"organization_id": 3},
    ), patch(
        "backend.rinse_scan_retention.load_protected_bag_ids", return_value=set()
    ):
        out = apply_scan_retention(cur, 3, config=cfg, dry_run=False)
    assert out["applied"] is False
    assert out["stopped_reason"] == "APPLY_BLOCKED"
    assert APPLY_BLOCKED is True


def test_resolve_config_disabled_by_default():
    cur = MagicMock()
    with patch("backend.rinse_scan_retention.table_exists", return_value=False):
        cfg = resolve_retention_config(cur, 3)
    assert cfg.enabled is False
    assert cfg.upload_retention_days == 30
    assert cfg.canonical_retention_days == 90
    assert cfg.upload_retention_days >= MIN_UPLOAD_RETENTION_DAYS
    assert cfg.canonical_retention_days >= MIN_CANONICAL_RETENTION_DAYS


def test_plan_includes_steady_state_and_hd_safety(monkeypatch):
    cur = MagicMock()
    cfg = RetentionConfig(organization_id=3, enabled=False)

    monkeypatch.setattr(
        "backend.rinse_scan_retention.load_protected_bag_ids",
        lambda *a, **k: {"BAG_HD"},
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention._epoch_wall", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention.load_retention_cursor",
        lambda *a, **k: __import__(
            "backend.rinse_scan_retention", fromlist=["RetentionCursor"]
        ).RetentionCursor(),
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention.table_exists",
        lambda c, t: t == "rinse_bag_scan_events",
    )

    def fake_execute(sql, params=()):
        pass

    results = [
        {"n": 100, "mn": datetime(2026, 8, 1), "mx": datetime(2026, 9, 17)},
        {"n": 10},
    ]

    def fetchone():
        return results.pop(0) if results else {}

    cur.execute.side_effect = fake_execute
    cur.fetchone.side_effect = fetchone
    cur.fetchall.return_value = []

    monkeypatch.setattr(
        "backend.rinse_scan_retention._plan_upload_retention_fast",
        lambda *a, **k: {
            "batches": 2,
            "upload_batch_scan_events": 1000,
            "upload_batch_rows": 50,
            "sample_batches": [],
            "notes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention._select_canonical_candidate_ids",
        lambda *a, **k: [1, 2],
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention.explain_canonical_selection", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "backend.rinse_scan_retention.explain_upload_batch_selection",
        lambda *a, **k: [],
    )

    plan = plan_scan_retention(cur, 3, config=cfg, include_explain=False)
    assert plan["enabled"] is False
    assert plan["hd_safety"]["hd_production_bags_protected"] is True
    assert plan["steady_state"]["upload"]["d30"]["estimated_rows"] > 0
    assert plan["current_state"]["upload_eligible_scan_events"] == 1000


def test_idempotent_resume_advances_cursor_only_forward():
    """Second select after advancing after_id must not re-pick earlier ids."""
    conn = _sqlite()
    cur = _DictCursor(conn)
    for i, day in enumerate([1, 2, 3, 4, 5], start=1):
        cur.execute(
            "INSERT INTO rinse_bag_scan_events VALUES (?,?,?,?,?)",
            (i, 3, "X", f"2026-01-0{day} 10:00:00", 1),
        )
    cutoff = datetime(2026, 8, 1)
    with patch("backend.rinse_scan_retention.table_exists", return_value=True):
        first = _select_canonical_candidate_ids(
            cur, 3, cutoff=cutoff, after_id=0, batch_size=2, protected=set(), epoch_wall=None
        )
        assert first == [1, 2]
        second = _select_canonical_candidate_ids(
            cur,
            3,
            cutoff=cutoff,
            after_id=max(first),
            batch_size=2,
            protected=set(),
            epoch_wall=None,
        )
        assert second == [3, 4]
        third = _select_canonical_candidate_ids(
            cur,
            3,
            cutoff=cutoff,
            after_id=max(second),
            batch_size=2,
            protected=set(),
            epoch_wall=None,
        )
        assert third == [5]


def test_cutoff_datetime_et_is_day_boundary():
    c = cutoff_datetime_et(30, today=date(2026, 9, 17))
    assert c == datetime(2026, 8, 18, 0, 0, 0)


def test_floors_prevent_sub_minimum_canonical():
    n, _ = _clamp_days(1, MIN_CANONICAL_RETENTION_DAYS, label="canonical")
    assert n == MIN_CANONICAL_RETENTION_DAYS
