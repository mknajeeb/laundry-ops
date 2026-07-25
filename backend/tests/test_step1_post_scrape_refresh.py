"""Post-scrape Step-1 day snapshot refresh keeps Completed/Pending queues current.

Pipeline freshness only — does not change WF/HD classification or productivity.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_scheduled_scrape import (
    ScheduledScrapeResult,
    _combined_cycle_needs_step1_refresh,
    _mark_step1_refresh_failed_on_result,
    _refresh_open_step1_day_after_scrape,
    _step1_refresh_succeeded,
)
from backend.rinse_veewash_shift_day import STATUS_CLOSED, STATUS_OPEN


def test_post_scrape_refreshes_open_step1_day():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day = date(2026, 7, 25)
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=day), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_OPEN, "workload_meta": {}},
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
        return_value={
            "ok": True,
            "day": {"status": STATUS_OPEN, "last_sync_at": datetime(2026, 7, 25, 21, 10, 0)},
            "bag_count": 78,
            "summary_totals": {"completed": 70, "pending": 3},
        },
    ) as backfill, patch(
        "backend.rinse_scheduled_scrape._persist_step1_refresh_diagnostics"
    ) as stamp:
        out = _refresh_open_step1_day_after_scrape(
            conn,
            cursor,
            org_id=3,
            log=log,
            scrape_batch_id=2941,
            scrape_run_id=3017,
        )
    assert out["ok"] is True
    assert out["status"] == "ok"
    assert out["shift_date_et"] == "2026-07-25"
    assert out["scrape_batch_id"] == 2941
    assert out["scrape_run_id"] == 3017
    assert out["day_bags_rebuilt"] == 78
    assert out["started_at"]
    assert out["finished_at"]
    backfill.assert_called_once_with(cursor, 3, day, force=True)
    stamp.assert_called_once()
    conn.commit.assert_called()
    assert "ERROR" not in "".join(str(c) for c in log.write.call_args_list)


def test_post_scrape_skips_closed_step1_day():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day = date(2026, 7, 24)
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=day), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_CLOSED, "workload_meta": {}},
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live"
    ) as backfill, patch(
        "backend.rinse_scheduled_scrape._persist_step1_refresh_diagnostics"
    ):
        out = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log, scrape_batch_id=1
        )
    assert out["skipped"] is True
    assert out["reason"] == "day_closed"
    assert out["ok"] is True
    assert out["status"] == "skipped"
    backfill.assert_not_called()


def test_post_scrape_refresh_failure_is_explicit():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=date(2026, 7, 25)), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=RuntimeError("db down"),
    ):
        out = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log, scrape_batch_id=99
        )
    assert out["ok"] is False
    assert out["status"] == "failed"
    assert "db down" in out["error"]
    assert out["scrape_batch_id"] == 99
    assert any("ERROR: Step-1 post-scrape refresh FAILED" in str(c) for c in log.write.call_args_list)


def test_mark_refresh_failed_promotes_success_to_needs_attention():
    result = ScheduledScrapeResult(organization_id=3, status="success")
    result.detail = {}
    _mark_step1_refresh_failed_on_result(
        result, {"ok": False, "status": "failed", "error": "boom"}
    )
    assert result.status == "needs_attention"
    assert result.detail["step1_refresh_failed"] is True
    assert "Step-1 refresh failed" in (result.error_message or "")


def test_mark_refresh_failed_noop_when_ok():
    result = ScheduledScrapeResult(organization_id=3, status="success")
    result.detail = {"step1_day_refresh": {"ok": True, "status": "ok"}}
    _mark_step1_refresh_failed_on_result(result, {"ok": True, "status": "ok"})
    assert result.status == "success"
    assert not result.detail.get("step1_refresh_failed")


def test_combined_cycle_retries_when_prior_refresh_failed():
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"confirm": {}, "targeted_pending_scan_refresh": {}},
        )
        is True
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"step1_day_refresh": {"ok": False, "status": "failed"}},
        )
        is True
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"step1_day_refresh": {"ok": True, "status": "ok"}},
        )
        is False
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"step1_day_refresh": {"skipped": True, "ok": True}},
        )
        is False
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=True, status="success", detail={}
        )
        is False
    )


def test_step1_refresh_succeeded_helpers():
    assert _step1_refresh_succeeded({}) is False
    assert _step1_refresh_succeeded({"step1_day_refresh": {"ok": False}}) is False
    assert _step1_refresh_succeeded({"step1_day_refresh": {"ok": True}}) is True
    assert _step1_refresh_succeeded({"step1_day_refresh": {"skipped": True}}) is True


def test_combined_cycle_guarantee_calls_refresh_when_import_omits_it():
    """Successful combined sync must invoke production backfill when import skipped it."""
    from pathlib import Path
    import tempfile
    import os
    from backend.rinse_scheduled_scrape import run_rinse_combined_sync_for_org
    from backend.rinse_presence_scrape import PresenceScrapeResult

    run_dir = Path(tempfile.mkdtemp())
    paths = MagicMock()
    paths.run_dir = run_dir
    paths.portal_csv = run_dir / "portal.csv"
    paths.scan_tickets_csv = run_dir / "t.csv"
    paths.scan_events_csv = run_dir / "e.csv"
    paths.log_path = run_dir / "log"
    paths.portal_csv.write_text("h\n1\n")
    paths.log_path.write_text("")

    import_result = ScheduledScrapeResult(
        organization_id=3,
        status="success",
        at_vendor_status="success",
        batch_id=2941,
        detail={"confirm": {"status": "batch_confirmed"}, "draft": {}},
    )

    with patch.dict(os.environ, {"RFV_SCRAPE_ENABLED": "false"}), patch(
        "backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash"
    ), patch(
        "backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash")
    ), patch(
        "backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")
    ), patch(
        "backend.rinse_scheduled_scrape.insert_scrape_run", return_value=3017
    ), patch(
        "backend.rinse_scheduled_scrape.finish_scrape_run"
    ), patch(
        "backend.rinse_scheduled_scrape.release_scrape_lock"
    ), patch(
        "backend.rinse_scheduled_scrape.build_run_paths", return_value=paths
    ), patch(
        "backend.rinse_presence_scrape.run_presence_scrape_for_org",
        return_value=PresenceScrapeResult(
            organization_id=3,
            portal_status="at_vendor",
            status="success",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            stats={"rows_found": 11},
        ),
    ), patch(
        "backend.rinse_scheduled_scrape.run_scheduled_scrape_for_org",
        return_value=import_result,
    ), patch(
        "backend.rinse_scheduled_scrape._refresh_open_step1_day_after_scrape",
        return_value={
            "ok": True,
            "status": "ok",
            "shift_date_et": "2026-07-25",
            "scrape_batch_id": 2941,
            "day_bags_rebuilt": 78,
            "started_at": "2026-07-25 21:05:30",
            "finished_at": "2026-07-25 21:06:00",
        },
    ) as refresh:
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        result = run_rinse_combined_sync_for_org(conn, 3, run_type="scheduled")

    refresh.assert_called_once()
    kwargs = refresh.call_args.kwargs
    assert kwargs.get("scrape_batch_id") == 2941
    assert result.detail["step1_day_refresh"]["ok"] is True
    assert result.detail.get("step1_day_refresh_via") == "combined_cycle_guarantee"
    assert result.status == "success"
    assert not result.detail.get("step1_refresh_failed")


def test_summary_exposes_step1_refresh_timestamp():
    from backend.rinse_veewash_shift_day import summary_from_day_record

    day = {
        "status": STATUS_OPEN,
        "opened_at": datetime(2026, 7, 25, 15, 0, 0),
        "last_sync_at": datetime(2026, 7, 25, 21, 6, 0),
        "workload_meta": {
            "step1_refresh": {
                "status": "ok",
                "finished_at": "2026-07-25 21:06:00",
                "scrape_batch_id": 2941,
                "day_bags_rebuilt": 78,
            }
        },
        "headline": {
            "active_workload": 78,
            "completed": 70,
            "pending": 3,
            "segments": {"wf": {"bag_ids": {"pending": [], "completed": []}}},
        },
        "review_required_count": 0,
    }
    summary = summary_from_day_record(day)
    assert summary is not None
    sd = summary["shift_day"]
    assert sd["step1_refreshed_at"] == "2026-07-25 21:06:00"
    assert sd["step1_refresh_status"] == "ok"
    assert sd["step1_refresh_scrape_batch_id"] == 2941
    assert sd["step1_refresh_day_bags_rebuilt"] == 78
    assert sd["last_sync_at"] == datetime(2026, 7, 25, 21, 6, 0)


def test_repeated_refresh_is_idempotent_calls_same_backfill():
    """Repeated scrapes re-enter the same production backfill path (idempotent)."""
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day = date(2026, 7, 25)
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=day), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_OPEN, "workload_meta": {}},
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
        return_value={"ok": True, "day": {"status": STATUS_OPEN}, "bag_count": 78},
    ) as backfill, patch(
        "backend.rinse_scheduled_scrape._persist_step1_refresh_diagnostics"
    ):
        a = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log, scrape_batch_id=1
        )
        b = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log, scrape_batch_id=2
        )
    assert a["ok"] and b["ok"]
    assert backfill.call_count == 2
    assert backfill.call_args_list[0].args == (cursor, 3, day)
    assert backfill.call_args_list[0].kwargs == {"force": True}
