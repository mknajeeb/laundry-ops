"""WF reset epoch + ops maintenance gate.

Scan history survives a WF clean reset physically. These tests prove the epoch
fence is what stops it from resurrecting lifecycle state, and that maintenance
stops the scheduler and the recovery watchdog from mutating anything.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pytest

from backend.wf_ops_reset_epoch import (
    BASELINE_RESET_AUTH_ENV,
    WF_OPS_MAINTENANCE_KEY,
    WF_RESET_EPOCH_KEY,
    WF_TRUSTED_BASELINE_KEY,
    WfOpsMaintenanceActive,
    assert_wf_ops_mutation_allowed,
    baseline_auth_token_valid,
    epoch_scan_wall,
    evidence_on_or_after_epoch,
    get_wf_ops_maintenance,
    get_wf_reset_epoch_at,
    get_wf_trusted_baseline,
    invalidate_wf_reset_epoch_cache,
    set_wf_ops_maintenance,
    set_wf_reset_epoch_at,
    set_wf_trusted_baseline,
    wf_ops_mutation_gate,
)

ORG = 3
# 2026-09-15 12:00:00 UTC == 2026-09-15 08:00:00 America/New_York (EDT)
EPOCH_UTC = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
EPOCH_ET_WALL = datetime(2026, 9, 15, 8, 0, 0)


class _SettingsCursor:
    """Minimal org-scoped system_settings store."""

    def __init__(self, store: dict | None = None) -> None:
        self.store: dict[tuple[int, str], str] = dict(store or {})
        self._last: list[dict] = []
        self.sql_log: list[str] = []

    def execute(self, sql, params=None):
        norm = " ".join(str(sql).split()).lower()
        params = tuple(params or ())
        self.sql_log.append(norm)
        if "select svalue from system_settings" in norm:
            val = self.store.get((int(params[0]), params[1]))
            self._last = [{"svalue": val}] if val is not None else []
            return
        if "insert into system_settings" in norm:
            self.store[(int(params[0]), params[1])] = params[2]
            self._last = []
            return
        self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)

    def close(self):
        return None


@pytest.fixture(autouse=True)
def _settings_tables(monkeypatch):
    monkeypatch.setattr("backend.wf_ops_reset_epoch.table_exists", lambda *_: True)
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.table_has_column", lambda *_: True
    )
    invalidate_wf_reset_epoch_cache()
    yield
    invalidate_wf_reset_epoch_cache()


# --- epoch storage and conversion -------------------------------------------------


def test_epoch_roundtrips_as_iso_utc():
    cur = _SettingsCursor()
    written = set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)
    assert written == EPOCH_UTC
    assert cur.store[(ORG, WF_RESET_EPOCH_KEY)].endswith("+00:00")
    assert get_wf_reset_epoch_at(cur, ORG, use_cache=False) == EPOCH_UTC


def test_epoch_absent_when_no_reset_has_run():
    assert get_wf_reset_epoch_at(_SettingsCursor(), ORG, use_cache=False) is None


def test_epoch_scan_wall_is_eastern_not_utc():
    """cycle_anchor_at / scanned_at_parsed are ET wall — never the raw UTC instant."""
    assert epoch_scan_wall(EPOCH_UTC) == EPOCH_ET_WALL
    assert epoch_scan_wall(None) is None


def test_evidence_before_epoch_is_rejected_for_scan_wall_values():
    before = datetime(2026, 9, 15, 7, 59, 59)  # ET wall
    after = datetime(2026, 9, 15, 8, 0, 1)
    assert evidence_on_or_after_epoch(before, EPOCH_UTC) is False
    assert evidence_on_or_after_epoch(after, EPOCH_UTC) is True
    assert evidence_on_or_after_epoch(EPOCH_ET_WALL, EPOCH_UTC) is True


def test_evidence_system_naive_values_are_utc():
    """Scrape/DB clocks are UTC. The same wall number must not decide both ways."""
    ambiguous = datetime(2026, 9, 15, 9, 0, 0)
    assert evidence_on_or_after_epoch(ambiguous, EPOCH_UTC, kind="scan") is True
    assert evidence_on_or_after_epoch(ambiguous, EPOCH_UTC, kind="system") is False


def test_evidence_without_epoch_is_always_allowed():
    assert evidence_on_or_after_epoch(datetime(2020, 1, 1), None) is True


def test_undated_evidence_fails_closed():
    assert evidence_on_or_after_epoch(None, EPOCH_UTC) is False


# --- maintenance + baseline auth --------------------------------------------------


def test_maintenance_flag_roundtrip():
    cur = _SettingsCursor()
    assert get_wf_ops_maintenance(cur, ORG) is False
    set_wf_ops_maintenance(cur, ORG, True)
    assert cur.store[(ORG, WF_OPS_MAINTENANCE_KEY)] == "1"
    assert get_wf_ops_maintenance(cur, ORG) is True
    set_wf_ops_maintenance(cur, ORG, False)
    assert get_wf_ops_maintenance(cur, ORG) is False


def test_trusted_baseline_metadata_roundtrip():
    cur = _SettingsCursor()
    assert get_wf_trusted_baseline(cur, ORG) is None
    set_wf_trusted_baseline(cur, ORG, {"run_id": 42, "bags": 310})
    body = get_wf_trusted_baseline(cur, ORG)
    assert body["run_id"] == 42
    assert "recorded_at_utc" in body
    assert cur.store[(ORG, WF_TRUSTED_BASELINE_KEY)]


def test_baseline_token_fails_closed_without_env(monkeypatch):
    monkeypatch.delenv(BASELINE_RESET_AUTH_ENV, raising=False)
    assert baseline_auth_token_valid("anything") is False
    assert baseline_auth_token_valid(None) is False


def test_baseline_token_requires_exact_match(monkeypatch):
    monkeypatch.setenv(BASELINE_RESET_AUTH_ENV, "s3cret-token")
    assert baseline_auth_token_valid("s3cret-token") is True
    assert baseline_auth_token_valid("wrong") is False
    assert baseline_auth_token_valid("") is False


def test_mutation_blocked_while_maintenance_on(monkeypatch):
    monkeypatch.delenv(BASELINE_RESET_AUTH_ENV, raising=False)
    cur = _SettingsCursor()
    set_wf_ops_maintenance(cur, ORG, True)
    allowed, detail = wf_ops_mutation_gate(cur, ORG)
    assert allowed is False
    assert detail["reason"] == "wf_ops_maintenance_active"
    with pytest.raises(WfOpsMaintenanceActive):
        assert_wf_ops_mutation_allowed(cur, ORG)


def test_baseline_auth_allows_mutation_while_maintenance_on(monkeypatch):
    monkeypatch.setenv(BASELINE_RESET_AUTH_ENV, "s3cret-token")
    cur = _SettingsCursor()
    set_wf_ops_maintenance(cur, ORG, True)
    allowed, detail = wf_ops_mutation_gate(
        cur, ORG, allow_baseline_token="s3cret-token"
    )
    assert allowed is True
    assert detail["reason"] == "baseline_auth_accepted"
    assert_wf_ops_mutation_allowed(cur, ORG, allow_baseline_token="s3cret-token")


def test_mutation_allowed_when_maintenance_off():
    cur = _SettingsCursor()
    allowed, detail = wf_ops_mutation_gate(cur, ORG)
    assert allowed is True
    assert detail["reason"] == "maintenance_off"


# --- scheduler + watchdog guards ---------------------------------------------------


def _scrape_args(**overrides) -> argparse.Namespace:
    base = {
        "dry_run": False,
        "organization_ids": [ORG],
        "baseline_auth": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class _FakeConn:
    def __init__(self, cursor) -> None:
        self._cursor = cursor
        self.committed = 0

    def cursor(self, **_kwargs):
        return self._cursor

    def commit(self):
        self.committed += 1

    def close(self):
        return None


def test_scheduled_scrape_refuses_while_maintenance_on(monkeypatch):
    monkeypatch.delenv(BASELINE_RESET_AUTH_ENV, raising=False)
    from backend.jobs import run_scheduled_rinse_scrape as job

    cur = _SettingsCursor()
    set_wf_ops_maintenance(cur, ORG, True)
    allowed, detail = job._wf_maintenance_gate_allows_run(
        _FakeConn(cur), _scrape_args()
    )
    assert allowed is False
    assert detail["reason"] == "wf_ops_maintenance_active"


def test_scheduled_scrape_allows_authorized_baseline_run(monkeypatch):
    monkeypatch.setenv(BASELINE_RESET_AUTH_ENV, "s3cret-token")
    from backend.jobs import run_scheduled_rinse_scrape as job

    cur = _SettingsCursor()
    set_wf_ops_maintenance(cur, ORG, True)
    allowed, _ = job._wf_maintenance_gate_allows_run(
        _FakeConn(cur), _scrape_args(baseline_auth="s3cret-token")
    )
    assert allowed is True


def test_scheduled_scrape_unaffected_when_maintenance_off():
    from backend.jobs import run_scheduled_rinse_scrape as job

    allowed, detail = job._wf_maintenance_gate_allows_run(
        _FakeConn(_SettingsCursor()), _scrape_args()
    )
    assert allowed is True
    assert detail["reason"] == "maintenance_off"


def test_watchdog_skips_reclaim_and_recovery_while_maintenance_on(monkeypatch):
    monkeypatch.delenv(BASELINE_RESET_AUTH_ENV, raising=False)
    from backend.jobs import run_rinse_freshness_watchdog as job

    cur = _SettingsCursor()
    set_wf_ops_maintenance(cur, ORG, True)
    calls: list[str] = []

    class _Cfg:
        def to_public_dict(self):
            return {}

    monkeypatch.setattr("backend.db.get_db", lambda: _FakeConn(cur))
    monkeypatch.setattr(
        "backend.rinse_scheduled_scrape.parse_scheduled_org_ids", lambda: [ORG]
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config", lambda *_a, **_k: _Cfg()
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.current_mode", lambda **_k: "ACTIVE"
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.quiet_suppresses_automatic_start",
        lambda **_k: False,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.quiet_reclaim_due",
        lambda *_a, **_k: calls.append("quiet_reclaim_due") or (True, {}),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.mark_quiet_reclaim",
        lambda *_a, **_k: calls.append("mark_quiet_reclaim"),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.reclaim_orphan_owner",
        lambda *_a, **_k: calls.append("reclaim") or {"action": "none"},
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_chain.ensure_recovery_once",
        lambda *_a, **_k: calls.append("recovery") or {"started": True},
    )

    assert job.main([]) == 0
    assert calls == []


def test_watchdog_runs_recovery_when_maintenance_off(monkeypatch):
    from backend.jobs import run_rinse_freshness_watchdog as job

    cur = _SettingsCursor()
    calls: list[str] = []

    class _Cfg:
        def to_public_dict(self):
            return {}

    monkeypatch.setattr("backend.db.get_db", lambda: _FakeConn(cur))
    monkeypatch.setattr(
        "backend.rinse_scheduled_scrape.parse_scheduled_org_ids", lambda: [ORG]
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config", lambda *_a, **_k: _Cfg()
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.current_mode", lambda **_k: "ACTIVE"
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.quiet_suppresses_automatic_start",
        lambda **_k: False,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.reclaim_orphan_owner",
        lambda *_a, **_k: calls.append("reclaim") or {"action": "none"},
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_chain.ensure_recovery_once",
        lambda *_a, **_k: calls.append("recovery") or {"started": True},
    )

    assert job.main([]) == 0
    assert calls == ["reclaim", "recovery"]


# --- pre-epoch scan evidence cannot rebuild lifecycle ------------------------------


class _TimelineCursor(_SettingsCursor):
    """system_settings + rinse_bag_scan_events, with MySQL-style predicates."""

    def __init__(self, events: list[dict], store: dict | None = None) -> None:
        super().__init__(store)
        self.events = events

    def execute(self, sql, params=None):
        norm = " ".join(str(sql).split()).lower()
        if "from rinse_bag_scan_events" in norm:
            params = tuple(params or ())
            rows = [e for e in self.events if e["bag_id"] == params[1]]
            if len(params) > 2:
                rows = [e for e in rows if e["scanned_at_parsed"] >= params[2]]
            self._last = rows
            self.sql_log.append(norm)
            return
        super().execute(sql, params)


def _scan(ts: datetime, purpose: str = "sent-to-vendor") -> dict:
    return {
        "bag_id": "WFBAG1",
        "rack": "VeeWash Dirty",
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": "Driver",
        "scan_index": 1,
        "id": int(ts.timestamp()),
    }


def test_pre_epoch_scans_are_filtered_out_of_the_timeline(monkeypatch):
    from backend import rinse_wf_service_cycle as cycles

    monkeypatch.setattr(cycles, "table_exists", lambda *_: True)
    cur = _TimelineCursor(
        [_scan(datetime(2026, 9, 14, 10, 0)), _scan(datetime(2026, 9, 16, 10, 0))]
    )
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    timeline = cycles._load_timeline(cur, ORG, "WFBAG1")
    assert [e["scanned_at_parsed"] for e in timeline] == [
        datetime(2026, 9, 16, 10, 0)
    ]


def test_only_pre_epoch_scans_yield_no_cycle_anchor(monkeypatch):
    from backend import rinse_wf_service_cycle as cycles

    monkeypatch.setattr(cycles, "table_exists", lambda *_: True)
    cur = _TimelineCursor(
        [_scan(datetime(2026, 9, 1, 10, 0)), _scan(datetime(2026, 9, 14, 10, 0))]
    )
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    timeline = cycles._load_timeline(cur, ORG, "WFBAG1")
    assert timeline == []
    assert cycles._valid_cycle_anchors(timeline) == []


def test_timeline_unfiltered_when_no_epoch_exists(monkeypatch):
    from backend import rinse_wf_service_cycle as cycles

    monkeypatch.setattr(cycles, "table_exists", lambda *_: True)
    cur = _TimelineCursor([_scan(datetime(2026, 9, 1, 10, 0))])
    assert len(cycles._load_timeline(cur, ORG, "WFBAG1")) == 1


def test_epoch_sql_predicate_and_filter_rows():
    from backend.wf_ops_reset_epoch import (
        epoch_sql_predicate,
        filter_scan_event_rows,
        require_offline_recovery_authorization,
    )

    cur = _SettingsCursor()
    clause, params = epoch_sql_predicate(cur, ORG)
    assert clause == "" and params == ()

    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)
    invalidate_wf_reset_epoch_cache(ORG)
    clause, params = epoch_sql_predicate(cur, ORG)
    assert "scanned_at_parsed" in clause and params == (EPOCH_ET_WALL,)

    rows = [
        {"id": 1, "scanned_at_parsed": datetime(2026, 9, 14, 10, 0, 0)},
        {"id": 2, "scanned_at_parsed": datetime(2026, 9, 15, 9, 0, 0)},
    ]
    kept = filter_scan_event_rows(cur, ORG, rows)
    assert [r["id"] for r in kept] == [2]

    require_offline_recovery_authorization(apply=False)
    with pytest.raises(RuntimeError):
        require_offline_recovery_authorization(apply=True)
