"""Unit tests for rinse scrape schedule / mode (America/New_York, DST-aware)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from backend.rinse_folding_et import ET
from backend.rinse_scrape_schedule import (
    ScrapeScheduleConfig,
    current_mode,
    current_or_due_tick,
    default_schedule_config,
    evaluate_schedule,
    iter_active_ticks_for_day,
    load_schedule_config,
    missed_active_tick,
    next_scheduled_tick,
    quiet_suppresses_automatic_start,
    recovery_start_permitted,
    tick_key,
    validate_schedule_config_payload,
)


def _et(y, m, d, hh, mm, ss=0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


def test_default_config_values():
    cfg = default_schedule_config()
    assert cfg.timezone == "America/New_York"
    assert cfg.active_start == time(6, 45)
    assert cfg.active_end == time(22, 0)
    assert cfg.active_interval_minutes == 15
    assert cfg.quiet_scrape_times == ()


def test_validate_rejects_quiet_inside_active():
    cfg, errs = validate_schedule_config_payload(
        {
            "active_start": "06:45",
            "active_end": "22:00",
            "active_interval_minutes": 15,
            "quiet_scrape_times": ["12:00"],
        }
    )
    assert cfg is None
    assert any("inside the ACTIVE window" in e for e in errs)


def test_validate_rejects_duplicate_quiet():
    cfg, errs = validate_schedule_config_payload(
        {
            "active_start": "06:45",
            "active_end": "22:00",
            "active_interval_minutes": 10,
            "quiet_scrape_times": ["00:00", "00:00"],
        }
    )
    assert cfg is None
    assert any("duplicate" in e for e in errs)


def test_validate_accepts_interval_10():
    cfg, errs = validate_schedule_config_payload(
        {
            "active_start": "06:45",
            "active_end": "22:00",
            "active_interval_minutes": 10,
            "quiet_scrape_times": ["00:00"],
        }
    )
    assert errs == []
    assert cfg is not None
    assert cfg.active_interval_minutes == 10
    assert cfg.quiet_scrape_times == (time(0, 0),)


def test_mode_boundaries():
    cfg = default_schedule_config()
    assert current_mode(_et(2026, 9, 17, 6, 44, 59), cfg) == "QUIET"
    assert current_mode(_et(2026, 9, 17, 6, 45, 0), cfg) == "ACTIVE"
    assert current_mode(_et(2026, 9, 17, 12, 0, 0), cfg) == "ACTIVE"
    assert current_mode(_et(2026, 9, 17, 21, 59, 59), cfg) == "ACTIVE"
    assert current_mode(_et(2026, 9, 17, 22, 0, 0), cfg) == "ACTIVE"
    assert current_mode(_et(2026, 9, 17, 22, 0, 59), cfg) == "ACTIVE"
    assert current_mode(_et(2026, 9, 17, 22, 1, 0), cfg) == "QUIET"
    assert current_mode(_et(2026, 9, 17, 23, 59, 59), cfg) == "QUIET"
    assert current_mode(_et(2026, 9, 18, 0, 0, 0), cfg) == "QUIET"


def test_active_ticks_include_opening_and_closing():
    cfg = default_schedule_config()
    ticks = iter_active_ticks_for_day(date(2026, 9, 17), cfg)
    assert ticks[0] == _et(2026, 9, 17, 6, 45)
    assert ticks[-1] == _et(2026, 9, 17, 22, 0)
    # 15-minute grid from 06:45
    assert _et(2026, 9, 17, 7, 0) in ticks
    assert _et(2026, 9, 17, 7, 15) in ticks


def test_evaluate_opening_tick_due():
    cfg = default_schedule_config()
    decision = evaluate_schedule(_et(2026, 9, 17, 6, 45, 5), cfg)
    assert decision.mode == "ACTIVE"
    assert decision.scrape_due is True
    assert decision.tick_key == "2026-09-17 06:45"
    assert decision.quiet_suppresses_automatic_start is False
    assert decision.recovery_start_permitted is True


def test_evaluate_tick_already_completed():
    cfg = default_schedule_config()
    decision = evaluate_schedule(
        _et(2026, 9, 17, 6, 50, 0),
        cfg,
        last_completed_tick_key="2026-09-17 06:45",
    )
    assert decision.scrape_due is False
    assert decision.reason == "tick_already_completed"


def test_evaluate_between_ticks_not_due():
    """At 06:44 still Quiet/no opening tick; at 07:05 still in 07:00 slot."""
    cfg = default_schedule_config()
    early = evaluate_schedule(_et(2026, 9, 17, 6, 44, 0), cfg)
    assert early.mode == "QUIET"
    assert early.scrape_due is False
    assert quiet_suppresses_automatic_start(_et(2026, 9, 17, 6, 44, 0), cfg) is True

    mid = evaluate_schedule(_et(2026, 9, 17, 7, 5, 0), cfg)
    assert mid.mode == "ACTIVE"
    assert mid.scrape_due is True
    assert mid.tick_key == "2026-09-17 07:00"


def test_closing_tick_does_not_span_quiet_night():
    cfg = default_schedule_config()
    at_close = evaluate_schedule(_et(2026, 9, 17, 22, 0, 30), cfg)
    assert at_close.mode == "ACTIVE"
    assert at_close.scrape_due is True
    assert at_close.tick_key == "2026-09-17 22:00"

    late = evaluate_schedule(_et(2026, 9, 17, 22, 20, 0), cfg)
    assert late.mode == "QUIET"
    assert late.scrape_due is False
    assert late.quiet_suppresses_automatic_start is True
    assert late.recovery_start_permitted is False
    assert recovery_start_permitted(_et(2026, 9, 17, 23, 0), cfg) is False


def test_quiet_expected_idle_for_missed_recovery():
    cfg = default_schedule_config()
    decision = missed_active_tick(_et(2026, 9, 17, 23, 30), cfg)
    assert decision.mode == "QUIET"
    assert decision.scrape_due is False
    assert decision.reason == "quiet_expected_idle"


def test_missed_active_tick_after_grace():
    cfg = default_schedule_config()
    # 07:00 tick, now 07:03 (>120s grace) and not completed
    decision = missed_active_tick(
        _et(2026, 9, 17, 7, 3, 0),
        cfg,
        last_completed_tick_key=None,
        miss_grace_seconds=120,
    )
    assert decision.scrape_due is True
    assert decision.reason == "missed_active_tick"
    assert decision.tick_key == "2026-09-17 07:00"


def test_missed_active_within_grace():
    cfg = default_schedule_config()
    decision = missed_active_tick(
        _et(2026, 9, 17, 7, 0, 30),
        cfg,
        miss_grace_seconds=120,
    )
    assert decision.scrape_due is False
    assert decision.reason == "within_miss_grace"


def test_next_tick_after_closing():
    cfg = default_schedule_config()
    nxt = next_scheduled_tick(_et(2026, 9, 17, 22, 1), cfg)
    assert nxt == _et(2026, 9, 18, 6, 45)


def test_dst_spring_forward_active_ticks_deterministic():
    # 2026-03-08 spring forward in US (2:00 → 3:00). Active window unaffected.
    cfg = default_schedule_config()
    ticks = iter_active_ticks_for_day(date(2026, 3, 8), cfg)
    assert ticks[0] == _et(2026, 3, 8, 6, 45)
    assert ticks[-1] == _et(2026, 3, 8, 22, 0)
    keys = [tick_key(t) for t in ticks]
    assert len(keys) == len(set(keys))


def test_dst_fall_back_quiet_time_uses_first_occurrence():
    # 2026-11-01 fall back. Quiet 01:30 would be ambiguous; fold=0 first occurrence.
    cfg = ScrapeScheduleConfig(
        active_start=time(6, 45),
        active_end=time(22, 0),
        active_interval_minutes=15,
        quiet_scrape_times=(time(1, 30),),
    )
    from backend.rinse_scrape_schedule import iter_quiet_ticks_for_day

    ticks = iter_quiet_ticks_for_day(date(2026, 11, 1), cfg)
    assert len(ticks) == 1
    assert ticks[0].fold == 0
    assert tick_key(ticks[0]) == "2026-11-01 01:30"


def test_dst_fall_back_does_not_duplicate_active_workers_via_tick_keys():
    cfg = default_schedule_config()
    ticks = iter_active_ticks_for_day(date(2026, 11, 1), cfg)
    assert len([tick_key(t) for t in ticks]) == len({tick_key(t) for t in ticks})


def test_load_schedule_config_defaults_without_cursor():
    cfg = load_schedule_config(None)
    assert cfg.active_interval_minutes == 15
    assert cfg.used_safe_fallback is False


def test_env_interval_override(monkeypatch):
    monkeypatch.setenv("RINSE_SCRAPE_ACTIVE_INTERVAL_MIN", "10")
    cfg = load_schedule_config(None)
    assert cfg.active_interval_minutes == 10


def test_current_or_due_tick_none_in_deep_quiet():
    cfg = default_schedule_config()
    assert current_or_due_tick(_et(2026, 9, 17, 3, 0), cfg) is None
