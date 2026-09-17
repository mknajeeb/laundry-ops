"""Recovery watchdog: expected idle vs missed ACTIVE tick."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from backend.rinse_scrape_schedule import (
    ScrapeScheduleConfig,
    default_schedule_config,
    missed_active_tick,
)

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh, mm, ss=0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


def test_missed_tick_expected_idle_within_grace():
    cfg = default_schedule_config()
    # 07:00:30 — tick at 07:00, within 120s grace
    d = missed_active_tick(_et(2026, 9, 17, 7, 0, 30), cfg, last_completed_tick_key=None)
    assert d.mode == "ACTIVE"
    assert d.scrape_due is False
    assert d.reason == "within_miss_grace"
    assert d.recovery_start_permitted is True


def test_missed_tick_due_after_grace():
    cfg = default_schedule_config()
    d = missed_active_tick(_et(2026, 9, 17, 7, 3, 0), cfg, last_completed_tick_key=None)
    assert d.scrape_due is True
    assert d.reason == "missed_active_tick"
    assert d.tick_key == "2026-09-17 07:00"


def test_missed_tick_quiet_is_expected_idle():
    cfg = default_schedule_config()
    d = missed_active_tick(_et(2026, 9, 17, 23, 0, 0), cfg, last_completed_tick_key=None)
    assert d.mode == "QUIET"
    assert d.scrape_due is False
    assert d.quiet_suppresses_automatic_start is True
    assert d.recovery_start_permitted is False


def test_ensure_recovery_once_quiet_blocks(monkeypatch):
    from backend import rinse_scrape_chain as chain

    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config",
        lambda *_a, **_k: default_schedule_config(),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.get_last_completed_tick_key",
        lambda *_a, **_k: None,
    )
    starts: list[int] = []
    monkeypatch.setattr(
        "backend.rinse_aca_job_trigger.start_rinse_scrape_aca_job",
        lambda *_a, **_k: starts.append(1) or MagicMock(ok=True, execution_name="x", error_message=None),
    )
    cursor = MagicMock()
    out = chain.ensure_recovery_once(cursor, 3, now_et=_et(2026, 9, 17, 23, 30))
    assert out["restarted"] is False
    assert out["reason"] == "quiet_expected_idle"
    assert starts == []


def test_ensure_recovery_once_starts_on_missed_tick(monkeypatch):
    from backend import rinse_scrape_chain as chain
    from backend.rinse_aca_job_trigger import AcaJobStartResult

    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config",
        lambda *_a, **_k: default_schedule_config(),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.get_last_completed_tick_key",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(chain, "_running_aca_executions", lambda: [])
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.mysql_lock_is_held",
        lambda *_a, **_k: (False, None),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.is_owned_execution_live",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.read_lease_liveness",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(chain, "read_lease", lambda *_a, **_k: {})
    monkeypatch.setattr(chain, "record_successor_attempt", lambda *_a, **_k: None)

    cursor = MagicMock()
    cursor.fetchone.return_value = {"got": 1}

    starts: list[int] = []

    def _start(org, **kw):
        starts.append(org)
        return AcaJobStartResult(ok=True, execution_name="recov-1")

    monkeypatch.setattr(
        "backend.rinse_aca_job_trigger.start_rinse_scrape_aca_job",
        _start,
    )
    # 07:05 — past 07:00 tick grace
    out = chain.ensure_recovery_once(cursor, 3, now_et=_et(2026, 9, 17, 7, 5))
    assert out["restarted"] is True
    assert out["reason"] == "recovery_started"
    assert starts == [3]


def test_ensure_recovery_once_idle_between_ticks_no_start(monkeypatch):
    from backend import rinse_scrape_chain as chain

    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config",
        lambda *_a, **_k: default_schedule_config(),
    )
    # Prior tick completed; within grace of current slot start
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.get_last_completed_tick_key",
        lambda *_a, **_k: "2026-09-17 07:00",
    )
    starts: list[int] = []
    monkeypatch.setattr(
        "backend.rinse_aca_job_trigger.start_rinse_scrape_aca_job",
        lambda *_a, **_k: starts.append(1) or MagicMock(ok=True),
    )
    cursor = MagicMock()
    # 07:01 with last tick 07:00 completed → tick_already_completed for 07:00 slot
    out = chain.ensure_recovery_once(cursor, 3, now_et=_et(2026, 9, 17, 7, 1))
    assert out["restarted"] is False
    assert out["reason"] == "tick_already_completed"
    assert starts == []
