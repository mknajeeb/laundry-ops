"""Gated no-op scraper path: Quiet exits without production DB."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def test_quiet_once_skips_db_entirely(monkeypatch):
    from backend.jobs import run_scheduled_rinse_scrape as job
    from backend.rinse_scrape_schedule import default_schedule_config

    db_calls: list[int] = []

    monkeypatch.setattr(
        "backend.release_revision.load_release_revision_stamps",
        lambda: {"runtime_revision": "test"},
    )
    monkeypatch.setattr(
        "backend.rinse_scheduled_scrape.parse_scheduled_org_ids",
        lambda: [3],
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config",
        lambda *_a, **_k: default_schedule_config(),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.current_mode",
        lambda **_k: "QUIET",
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.quiet_suppresses_automatic_start",
        lambda **_k: True,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.evaluate_schedule",
        lambda *a, **k: __import__(
            "backend.rinse_scrape_schedule", fromlist=["ScheduleDecision"]
        ).ScheduleDecision(
            mode="QUIET",
            now_et=datetime(2026, 9, 17, 23, 0, tzinfo=ET),
            scrape_due=False,
            reason="quiet_expected_idle",
            quiet_suppresses_automatic_start=True,
            recovery_start_permitted=False,
            config=default_schedule_config(),
        ),
    )

    def _boom():
        db_calls.append(1)
        raise AssertionError("get_db must not be called on Quiet gated no-op")

    monkeypatch.setattr("backend.db.get_db", _boom)
    assert job.main(["--once"]) == 0
    assert db_calls == []


def test_active_once_still_opens_db(monkeypatch):
    from backend.jobs import run_scheduled_rinse_scrape as job
    from backend.rinse_scrape_schedule import default_schedule_config, ScheduleDecision

    db_calls: list[int] = []

    class FakeCursor:
        def close(self):
            return None

    class FakeConn:
        def cursor(self, **_k):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        "backend.release_revision.load_release_revision_stamps",
        lambda: {"runtime_revision": "test"},
    )
    monkeypatch.setattr(
        "backend.rinse_scheduled_scrape.parse_scheduled_org_ids",
        lambda: [3],
    )
    # Pre-gate (conn=None): ACTIVE → needs DB
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.load_schedule_config",
        lambda *_a, **_k: default_schedule_config(),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.current_mode",
        lambda **_k: "ACTIVE",
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_schedule.quiet_suppresses_automatic_start",
        lambda **_k: False,
    )

    def _get_db():
        db_calls.append(1)
        return FakeConn()

    monkeypatch.setattr("backend.db.get_db", _get_db)
    monkeypatch.setattr(
        "backend.jobs.run_scheduled_rinse_scrape._schedule_gate_allows_run",
        lambda conn, args: (
            (True, {"reason": "needs_db_for_active_tick"})
            if conn is None
            else (
                False,
                {
                    "reason": "tick_already_completed",
                    "mode": "ACTIVE",
                    "tick_key": "2026-09-17 07:00",
                },
            )
        ),
    )
    assert job.main(["--once"]) == 0
    assert db_calls == [1]
