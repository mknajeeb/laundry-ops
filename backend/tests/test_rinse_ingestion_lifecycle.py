"""P0 scheduled ingestion lifecycle: lock ownership, terminalization, lag."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.rinse_scrape_runs import (
    DEAD_EXECUTION_MESSAGE,
    MYSQL_LOCK_HELD_REASON,
    acquire_scrape_lock,
    ensure_scrape_run_terminal,
    is_scrape_cycle_running,
    mysql_lock_is_held,
)
from backend.rinse_scheduled_scrape import (
    _fmt_et_wall,
    _source_to_db_lag_seconds,
)
from backend.tests.test_rinse_scheduled_targeted_refresh import _run_scheduled_with_mocks


def _lock_cursor(*, got: int, leftover: list[dict] | None = None):
    cursor = MagicMock()
    conn = MagicMock()
    cursor.connection = conn
    cursor.fetchone.side_effect = [{"got": got}]
    cursor.fetchall.side_effect = [leftover or []]
    return cursor


def test_free_lock_with_no_running_row_acquires_cleanly():
    cursor = _lock_cursor(got=1, leftover=[])
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"):
        acquired, reason = acquire_scrape_lock(cursor, 3)
    assert acquired is True
    assert reason == ""
    joined = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list if c.args)
    assert "GET_LOCK" in joined
    assert "status = 'failed'" not in joined
    cursor = _lock_cursor(got=0, leftover=[{"id": 9, "started_at": datetime.utcnow()}])
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"):
        acquired, reason = acquire_scrape_lock(cursor, 3)
    assert acquired is False
    assert reason == MYSQL_LOCK_HELD_REASON
    updates = [
        str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args and "UPDATE rinse_scrape_runs" in str(c.args[0])
    ]
    assert updates == []


def test_stale_running_row_does_not_block_when_lock_is_free():
    young = datetime.utcnow() - timedelta(minutes=8)
    leftover = {
        "id": 77,
        "started_at": young,
        "result_json": "{}",
    }
    cursor = _lock_cursor(got=1, leftover=[leftover])
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"), patch(
        "backend.rinse_scrape_runs._stale_minutes", return_value=120
    ), patch(
        "backend.rinse_step1_evidence_gate.terminalize_import_running_gates_for_scrape_runs",
        return_value=1,
    ) as gates, patch(
        "backend.rinse_step1_scrape_refresh.ensure_today_snapshot_if_missing",
        return_value={"ok": True},
    ):
        acquired, reason = acquire_scrape_lock(cursor, 3)
    assert acquired is True
    assert reason == ""
    sql = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list if c.args)
    assert "status = 'failed'" in sql
    assert any(
        DEAD_EXECUTION_MESSAGE in str(c.args)
        or (c.kwargs and DEAD_EXECUTION_MESSAGE in str(c.kwargs))
        or any(DEAD_EXECUTION_MESSAGE in str(a) for a in c.args)
        for c in cursor.execute.call_args_list
    )
    gates.assert_called_once()
    assert gates.call_args.kwargs["scrape_run_ids"] == [77]


def test_timeout_row_still_failed_timeout_when_lock_free():
    old = datetime.utcnow() - timedelta(hours=3)
    leftover = {"id": 12, "started_at": old, "result_json": "{}"}
    cursor = _lock_cursor(got=1, leftover=[leftover])
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"), patch(
        "backend.rinse_scrape_runs._stale_minutes", return_value=120
    ), patch(
        "backend.rinse_scrape_runs._infer_failed_step_from_presence_runs",
        return_value="rfv_presence_scrape",
    ), patch(
        "backend.rinse_step1_evidence_gate.terminalize_import_running_gates_for_scrape_runs",
        return_value=0,
    ), patch(
        "backend.rinse_step1_scrape_refresh.ensure_today_snapshot_if_missing",
        return_value={"ok": True},
    ):
        acquired, reason = acquire_scrape_lock(cursor, 3)
    assert acquired is True
    assert reason == ""
    joined = " ".join(str(c.args) for c in cursor.execute.call_args_list)
    assert "timed out after 120 minutes" in joined
    assert "FAILED_TIMEOUT" in joined or "timed out" in joined


def test_is_scrape_cycle_running_uses_lock_not_db_row():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"used": None}
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"):
        running, hint = is_scrape_cycle_running(cursor, 3)
    assert running is False
    assert hint is None

    cursor.fetchone.return_value = {"used": 4242}
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"):
        running, hint = is_scrape_cycle_running(cursor, 3)
    assert running is True
    assert "4242" in (hint or "")


def test_mysql_lock_is_held_false_when_free():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"used": None}
    held, _ = mysql_lock_is_held(cursor, 3)
    assert held is False


def test_ensure_scrape_run_terminal_only_updates_running():
    cursor = MagicMock()
    cursor.rowcount = 1
    with patch("backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"):
        changed = ensure_scrape_run_terminal(
            cursor,
            88,
            3,
            status="failed",
            error_message="cycle ended without finish_scrape_run",
        )
    assert changed is True
    sql = cursor.execute.call_args.args[0]
    assert "AND status = 'running'" in sql
    assert "failed" in cursor.execute.call_args.args[1]


def test_optional_finalize_failure_leaves_main_terminal_and_lock_released():
    result, _refresh, mock_finish, mock_release, *_rest = _run_scheduled_with_mocks(
        finalize_side_effect=RuntimeError("optional finalize exploded"),
    )
    assert result.status == "success"
    mock_finish.assert_called_once()
    assert mock_finish.call_args.kwargs.get("status") == "success"
    mock_release.assert_called_once()
    post = (result.detail or {}).get("rinse_finalize_post_lock") or {}
    assert post.get("post_lock") is True
    assert "optional finalize exploded" in str(post.get("error") or "")


def test_confirm_run_finalize_false_then_stage_b_then_finish():
    result, _refresh, mock_finish, mock_release, mock_stage_b, order, mock_confirm, *_ = (
        _run_scheduled_with_mocks()
    )
    assert result.status == "success"
    assert mock_confirm.call_args.kwargs.get("run_finalize") is False
    assert order.index("confirm") < order.index("stage_b_main")
    assert order.index("stage_b_main") < order.index("finish")
    assert order.index("finish") < order.index("release")
    mock_release.assert_called_once()
    mock_finish.assert_called_once()
    assert mock_stage_b.call_count >= 1


def test_source_to_db_lag_converts_utc_import_against_et_scan():
    # 16:10 UTC = 12:10 ET (EDT). Source scan 12:08 ET → lag 120s.
    source = datetime(2026, 8, 15, 12, 8, 0)
    imported = datetime(2026, 8, 15, 16, 10, 0)
    assert _source_to_db_lag_seconds(imported, source) == 120
    assert _fmt_et_wall(source) == "2026-08-15 12:08:00 ET"


def test_dead_scrape_clears_import_running_gate():
    from backend.rinse_step1_evidence_gate import (
        GATE_IMPORT_RUNNING,
        terminalize_import_running_gates_for_scrape_runs,
    )

    cursor = MagicMock()
    cursor.fetchall.return_value = [{"import_batch_id": 501, "scrape_run_id": 77}]
    with patch(
        "backend.rinse_step1_evidence_gate.table_exists", return_value=True
    ), patch(
        "backend.rinse_step1_evidence_gate.record_scan_import_terminal_failure",
        return_value={"gate_status": "incomplete"},
    ) as rec:
        n = terminalize_import_running_gates_for_scrape_runs(
            cursor,
            organization_id=3,
            scrape_run_ids=[77],
            error=DEAD_EXECUTION_MESSAGE,
        )
    assert n == 1
    rec.assert_called_once()
    assert rec.call_args.kwargs["import_batch_id"] == 501
    sql = cursor.execute.call_args.args[0]
    assert GATE_IMPORT_RUNNING in cursor.execute.call_args.args[1]


def test_finish_exception_still_terminalizes_via_ensure():
    """finish_scrape_run throw must not leave status=running after unlock."""

    def _boom(*_a, **_k):
        raise RuntimeError("finish blew up")

    with patch(
        "backend.rinse_scheduled_scrape.ensure_scrape_run_terminal",
        return_value=True,
    ) as ensure:
        result, _refresh, mock_finish, mock_release, *_rest = _run_scheduled_with_mocks(
            finish_side_effect=_boom,
        )
    mock_release.assert_called_once()
    ensure.assert_called_once()
    assert result.status in ("success", "failed", "needs_attention")
