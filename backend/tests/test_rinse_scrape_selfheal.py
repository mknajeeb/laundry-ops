"""Fencing + sequential immediate chain tests."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any
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


def test_scrape_stage_heartbeat_uses_supervisor_subprocess(monkeypatch):
    from backend.rinse_scrape_runs import scrape_stage_heartbeat

    calls: list[tuple[int, int, str]] = []

    def fake_supervisor(org, gen, **kwargs):
        calls.append((int(org), int(gen), str(kwargs.get("stage") or "")))

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.touch_supervisor_heartbeat",
        fake_supervisor,
    )
    spawned: list[str] = []

    class FakeProc:
        def __init__(self, *args, **kwargs):
            spawned.append("spawn")

        def start(self):
            spawned.append("start")

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

        def terminate(self):
            pass

        def kill(self):
            pass

    class FakeCtx:
        def Event(self):
            import threading

            return threading.Event()

        def Process(self, *args, **kwargs):
            return FakeProc()

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.multiprocessing.get_context",
        lambda _name: FakeCtx(),
    )

    with scrape_stage_heartbeat(99, 3, stage="finalizing", lease_generation=7):
        pass

    assert calls == [(3, 7, "finalizing")]
    assert spawned == ["spawn", "start"]


def test_supervisor_subprocess_ticks_multiple_times(monkeypatch):
    import threading

    from backend.rinse_scrape_liveness import _supervisor_heartbeat_subprocess_main

    calls: list[int] = []
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.touch_supervisor_heartbeat",
        lambda *_a, **_k: calls.append(1) or True,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._parent_process_alive",
        lambda _pid: True,
    )

    stop = threading.Event()
    worker = threading.Thread(
        target=_supervisor_heartbeat_subprocess_main,
        args=(3, 7, "portal_scrape", os.getpid(), stop, 0.05),
        daemon=True,
    )
    worker.start()
    time.sleep(0.2)
    stop.set()
    worker.join(timeout=3)
    assert len(calls) >= 3


def test_supervisor_subprocess_continues_when_worker_frozen(monkeypatch):
    """Worker stuck (no worker_progress_at bumps) but supervisor subprocess keeps ticking."""
    import threading

    from backend.rinse_scrape_liveness import _supervisor_heartbeat_subprocess_main

    supervisor_calls: list[int] = []
    worker_calls: list[int] = []

    def fake_touch(org, gen, **kwargs):
        if kwargs.get("worker_progress"):
            worker_calls.append(1)
        else:
            supervisor_calls.append(1)
        return True

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.touch_supervisor_heartbeat",
        fake_touch,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._parent_process_alive",
        lambda _pid: True,
    )

    stop = threading.Event()
    # Simulate initial worker progress tick from parent context.
    fake_touch(3, 7, stage="portal_scrape", worker_progress=True)
    worker = threading.Thread(
        target=_supervisor_heartbeat_subprocess_main,
        args=(3, 7, "portal_scrape", os.getpid(), stop, 0.05),
        daemon=True,
    )
    worker.start()
    time.sleep(0.25)
    stop.set()
    worker.join(timeout=3)

    assert len(worker_calls) == 1
    assert len(supervisor_calls) >= 3


def test_supervisor_subprocess_stops_on_parent_death(monkeypatch):
    from backend.rinse_scrape_liveness import _supervisor_heartbeat_subprocess_main
    import multiprocessing

    ticks: list[int] = []
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.touch_supervisor_heartbeat",
        lambda *_a, **_k: ticks.append(1) or True,
    )

    ctx = multiprocessing.get_context("spawn")
    stop = ctx.Event()
    proc = ctx.Process(
        target=_supervisor_heartbeat_subprocess_main,
        args=(3, 7, "portal_scrape", 999_999_999, stop, 0.05),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=3)
    assert not proc.is_alive()
    assert ticks == []


def test_parent_process_alive_detects_dead_pid():
    from backend.rinse_scrape_liveness import _parent_process_alive

    assert _parent_process_alive(999_999_999) is False
    assert _parent_process_alive(os.getpid()) is True


def test_touch_supervisor_heartbeat_rejects_stale_generation(monkeypatch):
    from backend.rinse_scrape_liveness import touch_supervisor_heartbeat

    class FakeCursor:
        rowcount = 0

        def execute(self, *_a, **_k):
            return None

        def close(self):
            return None

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._direct_mysql_connection",
        lambda: FakeConn(),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._ensure_liveness_columns_on_connection",
        lambda *_a, **_k: None,
    )
    assert touch_supervisor_heartbeat(3, 99, stage="portal_scrape") is False


def test_take_lease_resets_liveness_fields():
    from backend.rinse_scrape_lease import take_lease

    cursor = MagicMock()
    cursor.fetchone.return_value = {"generation": 42}
    gen = take_lease(cursor, 3, run_id=100)
    assert gen == 42
    insert_call = next(
        c
        for c in cursor.execute.call_args_list
        if "ON DUPLICATE KEY UPDATE" in c[0][0]
    )
    sql = insert_call[0][0]
    assert "supervisor_heartbeat_at" in sql
    assert "worker_progress_at" in sql
    params = insert_call[0][1]
    heartbeats = params[4:8]
    assert len(set(heartbeats)) == 1


def test_new_owner_cannot_inherit_previous_owner_fresh_heartbeat(monkeypatch):
    from backend.rinse_scrape_lease import take_lease

    stored: dict[str, Any] = {
        "generation": 5,
        "supervisor_heartbeat_at": datetime(2026, 8, 23, 12, 0, 0),
    }

    def fake_execute(sql, params=None):
        if "ON DUPLICATE KEY UPDATE" in sql and params:
            stored["generation"] = int(stored.get("generation") or 0) + 1
            stored["supervisor_heartbeat_at"] = params[5]
            stored["worker_progress_at"] = params[7]

    cursor = MagicMock()
    cursor.execute.side_effect = fake_execute
    cursor.fetchone.side_effect = lambda: {"generation": stored["generation"]}

    old_sup = stored["supervisor_heartbeat_at"]
    take_lease(cursor, 3, run_id=200)
    assert stored["supervisor_heartbeat_at"] != old_sup
    assert stored["worker_progress_at"] == stored["supervisor_heartbeat_at"]


def test_touch_scrape_run_progress_commits_lease_before_result_json(monkeypatch):
    from backend.rinse_scrape_runs import touch_scrape_run_progress

    commits: list[str] = []
    conn = MagicMock()
    conn.commit.side_effect = lambda: commits.append("commit")

    cursor = MagicMock()
    cursor.connection = conn
    cursor.fetchone.return_value = {
        "status": "running",
        "result_json": "{}",
        "lease_generation": 5,
    }

    monkeypatch.setattr(
        "backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.ensure_lease_liveness_columns", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_lease.touch_lease_heartbeat", lambda *_a, **_k: True
    )

    touch_scrape_run_progress(
        cursor, 99, 3, stage="portal_scrape", lease_generation=5
    )

    assert commits == ["commit"]
    assert cursor.execute.call_count >= 3


def test_run_bash_script_supervisor_tick_in_poll_loop(monkeypatch, tmp_path):
    from backend.rinse_scheduled_scrape import _TeeLog, _run_bash_script

    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/bash\nsleep 5\n")
    script.chmod(0o755)

    ticks: list[int] = []

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.scrape_supervisor_heartbeat_interval_sec",
        lambda: 0.05,
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.scrape_run_heartbeat_interval_sec",
        lambda: 3600,
    )

    log = _TeeLog(tmp_path / "log.txt")
    rc = _run_bash_script(
        script,
        {},
        log,
        supervisor_tick_fn=lambda: ticks.append(1),
    )
    assert rc == 0
    assert len(ticks) >= 2


def test_orphan_reclaim_blocked_when_supervisor_fresh(monkeypatch):
    from backend.rinse_scrape_liveness import orphan_reclaim_allowed

    now = datetime(2026, 8, 23, 18, 0, 0)
    lease = {
        "supervisor_heartbeat_at": now - timedelta(seconds=30),
        "owner_execution_name": "exec-a",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.mysql_lock_is_held",
        lambda *_a, **_k: (False, None),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._aca_execution_running",
        lambda _n: False,
    )
    allowed, reason, _ = orphan_reclaim_allowed(cursor, 3, lease, now=now)
    assert allowed is False
    assert reason == "skip_fresh_supervisor"


def test_orphan_reclaim_blocked_when_aca_running(monkeypatch):
    from backend.rinse_scrape_liveness import orphan_reclaim_allowed

    now = datetime(2026, 8, 23, 18, 0, 0)
    lease = {
        "supervisor_heartbeat_at": now - timedelta(seconds=3600),
        "owner_execution_name": "exec-a",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.mysql_lock_is_held",
        lambda *_a, **_k: (False, None),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._aca_execution_running",
        lambda _n: True,
    )
    allowed, reason, _ = orphan_reclaim_allowed(cursor, 3, lease, now=now)
    assert allowed is False
    assert reason == "skip_live_aca_execution"


def test_orphan_reclaim_blocked_when_lock_held(monkeypatch):
    from backend.rinse_scrape_liveness import orphan_reclaim_allowed

    now = datetime(2026, 8, 23, 18, 0, 0)
    lease = {
        "supervisor_heartbeat_at": now - timedelta(seconds=3600),
        "owner_execution_name": "exec-a",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.mysql_lock_is_held",
        lambda *_a, **_k: (True, 1),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._aca_execution_running",
        lambda _n: False,
    )
    allowed, reason, _ = orphan_reclaim_allowed(cursor, 3, lease, now=now)
    assert allowed is False
    assert reason == "skip_live_mysql_lock"


def test_orphan_reclaim_allowed_when_all_dead_signals(monkeypatch):
    from backend.rinse_scrape_liveness import orphan_reclaim_allowed

    now = datetime(2026, 8, 23, 18, 0, 0)
    lease = {
        "supervisor_heartbeat_at": now - timedelta(seconds=3600),
        "owner_execution_name": "exec-a",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.mysql_lock_is_held",
        lambda *_a, **_k: (False, None),
    )
    monkeypatch.setattr(
        "backend.rinse_scrape_liveness._aca_execution_running",
        lambda _n: False,
    )
    allowed, reason, _ = orphan_reclaim_allowed(cursor, 3, lease, now=now)
    assert allowed is True
    assert reason is None


def test_recover_stalled_uses_shared_orphan_policy(monkeypatch):
    from backend import rinse_scrape_chain as chain

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.reclaim_orphan_owner",
        lambda cursor, org: {"action": "skip_live_aca_execution"},
    )
    assert chain.recover_stalled_running_rows(MagicMock(), 3) == []

    monkeypatch.setattr(
        "backend.rinse_scrape_liveness.reclaim_orphan_owner",
        lambda cursor, org: {
            "action": "reclaimed",
            "run_id": 99,
            "reason": "FAILED_ORPHAN_RECLAIM stall>1200s",
        },
    )
    monkeypatch.setattr(chain, "current_execution_name", lambda: "self-exec")
    monkeypatch.setattr(
        "backend.rinse_aca_job_trigger.stop_foreign_running_executions",
        lambda **kwargs: [],
    )
    actions = chain.recover_stalled_running_rows(MagicMock(), 3)
    assert actions == [
        {
            "run_id": 99,
            "action": "FAILED_ORPHAN_RECLAIM",
            "reason": "FAILED_ORPHAN_RECLAIM stall>1200s",
        }
    ]
