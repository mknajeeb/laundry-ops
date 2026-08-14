"""Morning snapshot reliability — Today must exist after a valid import.

P0 invariant: a new ET business date plus a successful authoritative import
must leave one OPEN day row + day_bags + headline. Optional/targeted phases
must not block that persist. Incomplete gates must not replace a good snapshot.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_scrape_runs import acquire_scrape_lock
from backend.rinse_step1_evidence_gate import GATE_COMPLETE, GATE_INCOMPLETE
from backend.rinse_step1_scrape_refresh import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    ensure_today_snapshot_if_missing,
    refresh_step1_after_scrape,
)
from backend.rinse_veewash_shift_day import (
    STATUS_OPEN,
    _persist_snapshot_then_attach_specialty,
    reproject_day_bag_completions_from_chronology,
)
from backend.tests.test_step1_post_scrape_refresh import _patch_refresh_deps
from backend.tests.test_rinse_scheduled_targeted_refresh import _run_scheduled_with_mocks

TODAY = date(2026, 8, 14)
HEADLINE = {
    "completed": 80,
    "pending": 20,
    "active_workload": 100,
    "total_workload": 100,
    "exceptions": {"review_required": 0},
}


def _open_day(*, bags=12):
    return {
        "status": STATUS_OPEN,
        "headline": dict(HEADLINE),
        "last_sync_at": datetime(2026, 8, 14, 6, 0, 0),
        "workload_meta": {},
    }


def test_morning_invariant_successful_import_creates_open_snapshot():
    """New ET date + complete import → OPEN day + bags + headline before success."""
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day_after = _open_day()
    patches = _patch_refresh_deps(
        day=TODAY,
        day_record=None,
        backfill_return={
            "ok": True,
            "persisted": True,
            "day": day_after,
            "bag_count": 100,
            "summary_totals": {
                "completed": 80,
                "pending": 20,
                "review_required": 0,
            },
        },
    )
    with patches[0], patches[1], patches[2], patches[3] as backfill, patches[4], patches[
        5
    ], patches[6], patches[7], patches[8], patches[9]:
        out = refresh_step1_after_scrape(
            conn,
            cursor,
            organization_id=3,
            log=log,
            scrape_run_id=3952,
            import_batch_id=3493,
            operations_date_et=TODAY,
        )
    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["step1_refresh_status"] == STATUS_SUCCESS
    assert out["day_status"] == STATUS_OPEN
    assert out["day_bags_rebuilt"] == 100
    assert day_after["headline"]["completed"] == 80
    backfill.assert_called_once()
    assert backfill.call_args.args[:3] == (cursor, 3, TODAY)


def test_targeted_hang_after_import_still_creates_snapshot():
    """Post-lock targeted hang cannot undo Stage-B persist from the import."""
    result, _refresh, mock_finish, mock_release, mock_stage_b, order, *_rest = (
        _run_scheduled_with_mocks(
            refresh_side_effect=TimeoutError("targeted hung past bound"),
        )
    )
    assert result.status == "success"
    assert (result.detail or {}).get("step1_day_refresh", {}).get("ok") is True
    mock_finish.assert_called_once()
    mock_release.assert_called_once()
    assert order.index("stage_b_main") < order.index("finish")
    assert order.index("stage_b_main") < order.index("targeted")
    assert mock_stage_b.call_count >= 1


def test_later_scrape_failure_retains_prior_snapshot():
    """A failed later Stage-B must not wipe a good Today snapshot."""
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    prior = _open_day()
    patches = _patch_refresh_deps(
        day=TODAY,
        day_record=prior,
        backfill_side_effect=RuntimeError("later scrape persist failed"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
        6
    ], patches[7], patches[8], patches[9]:
        out = refresh_step1_after_scrape(
            conn,
            cursor,
            organization_id=3,
            log=log,
            scrape_run_id=3971,
            import_batch_id=3498,
            operations_date_et=TODAY,
        )
    assert out["ok"] is False
    assert out["step1_refresh_status"] == STATUS_FAILED
    sql = " ".join(str(c) for c in cursor.execute.call_args_list).upper()
    assert "DELETE FROM RINSE_SHIFT_MONITOR_DAYS" not in sql
    assert "DELETE FROM RINSE_SHIFT_MONITOR_DAY_BAGS" not in sql


def test_incomplete_evidence_gate_does_not_replace_good_snapshot():
    conn = MagicMock()
    cursor = MagicMock()
    prior = _open_day()
    with patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.step1_snapshot_present",
        return_value=True,
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": True,
            "allow_persist": False,
            "gate_status": GATE_INCOMPLETE,
            "gate_reason": "import_batch_incomplete",
            "import_batch_id": 3500,
        },
    ), patch(
        "backend.rinse_step1_scrape_refresh.refresh_step1_after_scrape",
    ) as refresh:
        out = ensure_today_snapshot_if_missing(
            conn,
            cursor,
            3,
            scrape_run_id=3976,
            import_batch_id=3500,
        )
    assert out.get("skipped") is True
    assert out.get("reason") == "snapshot_present"
    assert out.get("persisted") is not True
    refresh.assert_not_called()
    assert prior["headline"]["completed"] == 80


def test_incomplete_gate_does_not_create_snapshot_on_new_day():
    conn = MagicMock()
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.step1_snapshot_present",
        return_value=False,
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": True,
            "allow_persist": False,
            "gate_status": GATE_INCOMPLETE,
            "gate_reason": "import_batch_incomplete",
            "import_batch_id": 3500,
        },
    ), patch(
        "backend.rinse_step1_scrape_refresh.refresh_step1_after_scrape",
    ) as refresh:
        out = ensure_today_snapshot_if_missing(
            conn,
            cursor,
            3,
            scrape_run_id=3976,
            import_batch_id=3500,
        )
    assert out["deferred"] is True
    assert out["persisted"] is False
    refresh.assert_not_called()


def test_new_day_no_prior_snapshot_complete_import_creates_it():
    conn = MagicMock()
    cursor = MagicMock()
    created = {
        "ok": True,
        "persisted": True,
        "step1_refresh_status": STATUS_SUCCESS,
        "day_status": STATUS_OPEN,
        "day_bags_rebuilt": 100,
    }
    with patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.step1_snapshot_present",
        return_value=False,
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": False,
            "allow_persist": True,
            "gate_status": GATE_COMPLETE,
            "import_batch_id": 3493,
            "scrape_run_id": 3952,
        },
    ), patch(
        "backend.rinse_step1_scrape_refresh.refresh_step1_after_scrape",
        return_value=created,
    ) as refresh:
        out = ensure_today_snapshot_if_missing(
            conn, cursor, 3, scrape_run_id=3952, import_batch_id=3493
        )
    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["day_status"] == STATUS_OPEN
    assert out["day_bags_rebuilt"] == 100
    refresh.assert_called_once()
    assert refresh.call_args.kwargs["operations_date_et"] == TODAY
    assert refresh.call_args.kwargs["import_batch_id"] == 3493


def test_presence_day_missing_today_creates_snapshot():
    created = {
        "ok": True,
        "persisted": True,
        "day": _open_day(),
        "bag_count": 100,
        "reason": "day_missing_created_today",
    }
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=None
    ), patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
        return_value=created,
    ) as backfill:
        out = reproject_day_bag_completions_from_chronology(MagicMock(), 3, TODAY)
    backfill.assert_called_once()
    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["day"]["status"] == STATUS_OPEN


def test_presence_day_missing_historical_still_skips():
    historical = date(2026, 8, 13)
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=None
    ), patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
    ) as backfill:
        out = reproject_day_bag_completions_from_chronology(
            MagicMock(), 3, historical
        )
    backfill.assert_not_called()
    assert out["skipped"] is True
    assert out["reason"] == "day_missing"
    assert out["persisted"] is False


def test_specialty_failure_after_persist_leaves_open_snapshot():
    cursor = MagicMock()
    persisted = _open_day()
    wl = {"membership": {"ok": True, "total_count": 100}}
    summary = dict(HEADLINE)
    with patch(
        "backend.rinse_hd_day_presentation.finalize_hd_step1_summary",
        side_effect=lambda s, **k: s,
    ), patch(
        "backend.rinse_veewash_shift_day.derive_shift_day_status",
        return_value=STATUS_OPEN,
    ), patch(
        "backend.rinse_veewash_shift_day.persist_day_snapshot",
        return_value=persisted,
    ) as persist, patch(
        "backend.rinse_veewash_shift_day._commit",
    ), patch(
        "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary",
        side_effect=RuntimeError("specialty hung"),
    ):
        day, _summary, specialty_ok = _persist_snapshot_then_attach_specialty(
            cursor,
            3,
            TODAY,
            wl=wl,
            summary=summary,
            day=None,
            chronology_complete=True,
        )
    assert specialty_ok is False
    assert persist.call_count == 1
    assert day["status"] == STATUS_OPEN
    assert day["headline"]["completed"] == 80


def test_freshness_defer_on_new_day_still_creates_first_snapshot():
    """Complete import + missing Today: freshness defer must not skip create."""
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day_after = _open_day()
    patches = list(
        _patch_refresh_deps(
            day=TODAY,
            day_record=None,
            backfill_return={
                "ok": True,
                "persisted": True,
                "day": day_after,
                "bag_count": 100,
                "summary_totals": {"completed": 80, "pending": 20},
            },
        )
    )
    # Replace allow-gate with freshness defer (non-blocking durable).
    patches[9] = patch(
        "backend.rinse_scan_chronology_gate.evaluate_step1_rebuild_gate",
        return_value={
            "allow_persist": False,
            "ok": False,
            "deferred": True,
            "rebuild_deferred": True,
            "reason": "scan_chronology_stale",
            "status": "scan_chronology_stale",
            "data_freshness": {"status": "stale"},
            "last_consistent_snapshot": {},
            "durable_evidence_gate": {
                "blocking": False,
                "gate_status": GATE_COMPLETE,
                "allow_persist": True,
            },
        },
    )
    with patches[0], patches[1], patches[2], patches[3] as backfill, patches[4], patches[
        5
    ], patches[6], patches[7], patches[8], patches[9], patch(
        "backend.rinse_veewash_shift_day.step1_snapshot_present",
        return_value=False,
    ):
        out = refresh_step1_after_scrape(
            conn,
            cursor,
            organization_id=3,
            log=log,
            scrape_run_id=3952,
            import_batch_id=3493,
            operations_date_et=TODAY,
        )
    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["step1_refresh_status"] == STATUS_SUCCESS
    backfill.assert_called_once()


def test_watchdog_stale_timeout_heals_missing_today_snapshot():
    cursor = MagicMock()
    conn = MagicMock()
    cursor.connection = conn
    cursor.fetchall.side_effect = [
        [
            {
                "id": 3952,
                "started_at": datetime(2026, 8, 14, 5, 30, 0),
                "result_json": "{}",
            }
        ],
    ]
    cursor.fetchone.side_effect = [
        None,  # no remaining running rows
        {"got": 1},
    ]
    with patch(
        "backend.rinse_scrape_runs.ensure_rinse_scrape_runs_table"
    ), patch(
        "backend.rinse_scrape_runs._stale_minutes", return_value=120
    ), patch(
        "backend.rinse_scrape_runs._infer_failed_step_from_presence_runs",
        return_value="unknown",
    ), patch(
        "backend.rinse_step1_scrape_refresh.ensure_today_snapshot_if_missing",
        return_value={"ok": True, "persisted": True},
    ) as heal:
        acquired, reason = acquire_scrape_lock(cursor, 3)
    assert acquired is True
    assert reason == ""
    heal.assert_called_once()
    assert heal.call_args.kwargs.get("scrape_run_id") == 3952 or heal.call_args.args[
        2
    ] == 3


def test_ensure_skips_when_snapshot_already_present():
    conn = MagicMock()
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.today_et", return_value=TODAY
    ), patch(
        "backend.rinse_veewash_shift_day.step1_snapshot_present",
        return_value=True,
    ), patch(
        "backend.rinse_step1_scrape_refresh.refresh_step1_after_scrape",
    ) as refresh:
        out = ensure_today_snapshot_if_missing(conn, cursor, 3)
    assert out["skipped"] is True
    assert out["reason"] == "snapshot_present"
    refresh.assert_not_called()


def test_cycle_not_successful_until_snapshot_persisted():
    from backend.rinse_scheduled_scrape import (
        ScheduledScrapeResult,
        _mark_step1_refresh_failed_on_result,
    )

    result = ScheduledScrapeResult(organization_id=3, status="success")
    result.detail = {}
    _mark_step1_refresh_failed_on_result(
        result,
        {
            "ok": False,
            "persisted": False,
            "step1_refresh_status": STATUS_FAILED,
            "error": "today_snapshot_missing",
        },
    )
    assert result.status == "needs_attention"
    assert result.detail["step1_refresh_failed"] is True


def test_first_complete_import_creates_today_without_watchdog():
    """Morning Today comes from in-cycle Stage-B, not the missing-snapshot watchdog."""
    result, _refresh, _finish, _release, mock_stage_b, order, _c, _fin, mock_watchdog = (
        _run_scheduled_with_mocks()
    )
    assert result.status == "success"
    assert order.index("confirm") < order.index("stage_b_main")
    mock_stage_b.assert_called()
    mock_watchdog.assert_not_called()
    assert (result.detail or {}).get("step1_day_refresh", {}).get("ok") is True
