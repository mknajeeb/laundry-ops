"""Completion-driven scrape cadence: finish → wait → next; no overlap."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.rinse_scrape_runs import (
    compute_next_run_at,
    scheduled_post_run_cooldown,
)


def test_next_run_at_is_finished_plus_cooldown():
    finished = datetime(2026, 8, 18, 16, 18, 0)
    nxt = compute_next_run_at(finished, cooldown_minutes=30)
    assert nxt == datetime(2026, 8, 18, 16, 48, 0)


def test_scheduled_cooldown_blocks_until_finished_plus_30m():
    cursor = MagicMock()
    finished = datetime(2026, 8, 18, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(minutes=10)
    gate = scheduled_post_run_cooldown(
        cursor, 3, now=now, run_type="scheduled"
    )
    assert gate["ok_to_run"] is False
    assert gate["next_run_at"] == finished + timedelta(minutes=30)
    assert gate["remaining_seconds"] == 20 * 60


def test_scheduled_cooldown_allows_after_30m():
    cursor = MagicMock()
    finished = datetime(2026, 8, 18, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(minutes=30, seconds=1)
    gate = scheduled_post_run_cooldown(
        cursor, 3, now=now, run_type="scheduled"
    )
    assert gate["ok_to_run"] is True


def test_manual_bypasses_cooldown():
    cursor = MagicMock()
    finished = datetime(2026, 8, 18, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(minutes=1)
    gate = scheduled_post_run_cooldown(cursor, 3, now=now, run_type="manual")
    assert gate["ok_to_run"] is True
    assert gate["bypassed"] is True


def test_long_run_does_not_allow_second_start_inside_30m_of_finish():
    """Simulate scrape lasting >30m: next start still finish+30m, not clock+30m."""
    started = datetime(2026, 8, 18, 12, 0, 0)
    finished = started + timedelta(minutes=45)  # 12:45
    # Fixed cron would have fired at 12:30 during the run — lock would skip.
    # After finish, a 13:00 fixed tick is only 15m later — cooldown must block.
    cursor = MagicMock()
    cursor.fetchone.return_value = {"finished_at": finished}
    gate = scheduled_post_run_cooldown(
        cursor,
        3,
        now=datetime(2026, 8, 18, 13, 0, 0),
        run_type="scheduled",
    )
    assert gate["ok_to_run"] is False
    assert gate["next_run_at"] == datetime(2026, 8, 18, 13, 15, 0)
    later = scheduled_post_run_cooldown(
        cursor,
        3,
        now=datetime(2026, 8, 18, 13, 15, 0),
        run_type="scheduled",
    )
    assert later["ok_to_run"] is True
