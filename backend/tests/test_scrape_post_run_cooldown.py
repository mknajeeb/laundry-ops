"""Sequential scrape chain: finish → next immediately; lock still prevents overlap."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.rinse_scrape_runs import (
    compute_next_run_at,
    scheduled_post_run_cooldown,
)


def test_next_run_at_is_finished_immediately():
    finished = datetime(2026, 8, 18, 16, 18, 0)
    nxt = compute_next_run_at(finished, cooldown_minutes=0)
    assert nxt == datetime(2026, 8, 18, 16, 18, 0)


def test_scheduled_cooldown_no_longer_blocks():
    cursor = MagicMock()
    finished = datetime(2026, 8, 18, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(minutes=10)
    gate = scheduled_post_run_cooldown(
        cursor, 3, now=now, run_type="scheduled"
    )
    assert gate["ok_to_run"] is True


def test_manual_still_allowed():
    cursor = MagicMock()
    finished = datetime(2026, 8, 18, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(minutes=1)
    gate = scheduled_post_run_cooldown(cursor, 3, now=now, run_type="manual")
    assert gate["ok_to_run"] is True
    assert gate["bypassed"] is True
