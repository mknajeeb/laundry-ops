"""Fencing + sequential immediate chain tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.rinse_scrape_chain import classify_running_row
from backend.rinse_scrape_lease import FencedWriterError, assert_lease_writable
from backend.rinse_scrape_runs import compute_next_run_at, scheduled_post_run_cooldown


def test_next_run_is_immediate_after_finish():
    finished = datetime(2026, 8, 19, 16, 18, 0)
    nxt = compute_next_run_at(finished, cooldown_minutes=0)
    assert nxt == finished


def test_scheduled_gate_never_blocks_on_wait():
    cursor = MagicMock()
    finished = datetime(2026, 8, 19, 12, 0, 0)
    cursor.fetchone.return_value = {"finished_at": finished}
    now = finished + timedelta(seconds=1)
    gate = scheduled_post_run_cooldown(cursor, 3, now=now, run_type="scheduled")
    assert gate["ok_to_run"] is True
    assert gate["sequential_immediate"] is True
    assert gate["remaining_seconds"] == 0


def test_assert_lease_writable_rejects_fenced_generation():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"generation": 102, "owner_run_id": 50}
    try:
        assert_lease_writable(cursor, 3, 101)
        raised = False
    except FencedWriterError:
        raised = True
    assert raised is True


def test_classify_stalled_when_progress_old():
    started = datetime(2026, 8, 19, 12, 0, 0)
    row = {
        "started_at": started,
        "result_json": {
            "progress": {
                "last_progress_at": "2026-08-19T12:00:10Z",
                "last_heartbeat_at": "2026-08-19T12:00:10Z",
            }
        },
    }
    now = started + timedelta(minutes=12)
    assert classify_running_row(row, now=now) == "stalled"


def test_classify_healthy_when_progress_recent():
    started = datetime(2026, 8, 19, 12, 0, 0)
    now = started + timedelta(minutes=10)
    row = {
        "started_at": started,
        "result_json": {
            "progress": {
                "last_progress_at": now.isoformat() + "Z",
                "last_heartbeat_at": now.isoformat() + "Z",
            }
        },
    }
    assert classify_running_row(row, now=now) == "healthy"


def test_zombie_recovery_skips_without_execution_name(monkeypatch):
    from backend import rinse_scrape_chain as chain

    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 10, "status": "success"}
    monkeypatch.setattr(chain, "mysql_lock_is_held", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(chain, "current_execution_name", lambda: None)
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table", lambda *_a, **_k: None
    )
    actions = chain.recover_zombie_aca_executions(cursor, 3)
    assert actions == [{"skipped": "no_execution_name"}]


def test_classify_over_ceiling():
    started = datetime(2026, 8, 19, 12, 0, 0)
    now = started + timedelta(seconds=4300)
    row = {
        "started_at": started,
        "result_json": {"progress": {"last_progress_at": now.isoformat() + "Z"}},
    }
    assert classify_running_row(row, now=now) == "over_ceiling"
