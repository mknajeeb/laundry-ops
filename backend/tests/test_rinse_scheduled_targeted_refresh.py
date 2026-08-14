"""Scheduled targeted refresh runs post-lock after main cycle is terminal."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.tests.portal_csv_gate_fixtures import write_gate_passing_portal_csv


def _run_scheduled_with_mocks(
    *,
    refresh_side_effect=None,
    refresh_return=None,
    finish_side_effect=None,
    finalize_side_effect=None,
):
    import tempfile

    from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

    run_dir = Path(tempfile.mkdtemp())
    paths = ScrapePaths(
        run_dir=run_dir,
        portal_csv=run_dir / "portal.csv",
        scan_tickets_csv=run_dir / "t.csv",
        scan_events_csv=run_dir / "e.csv",
        log_path=run_dir / "log",
    )
    write_gate_passing_portal_csv(paths.portal_csv)
    paths.scan_events_csv.write_text("h\n1\n")

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"c": 1}
    conn.cursor.return_value = cursor

    tenant = MagicMock()
    tenant.is_dir.return_value = True

    refresh_payload = refresh_return or {
        "dry_run": False,
        "bag_ids_requested": ["BAG1"],
        "bags_processed": 1,
        "events_inserted": 2,
        "lookup_failed": 0,
        "bags": [],
    }

    patches = [
        patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
        patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
        patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=1),
        patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
        patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0),
        patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
        patch("backend.rinse_scheduled_scrape._count_accepted_rows", return_value=1),
        patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0),
        patch(
            "backend.rinse_portal_csv.portal_csv_to_orders_df",
            return_value=pd.DataFrame([{"ticket_id": "ABC"}]),
        ),
        patch(
            "backend.rinse_scan_events_upload.parse_scan_events_csv",
            return_value=(MagicMock(), []),
        ),
        patch(
            "backend.rinse_combined_upload.commit_rinse_combined_upload",
            return_value={
                "batch_id": 99,
                "rows_inserted": 1,
                "portal_absence_allowed": True,
                "persistent_scan_merge": {"events_inserted": 4, "bags_merged": 1},
            },
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_enabled",
            return_value=True,
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_dry_run",
            return_value=False,
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_rush_only",
            return_value=False,
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.build_baseline_context",
            return_value={},
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline",
            return_value={},
        ),
        patch("backend.rinse_scheduled_scrape.merge_scrape_run_result_json"),
        patch(
            "backend.rinse_upload_finalize.fetch_accepted_portal_rows_for_finalize",
            return_value=[],
        ),
    ]

    refresh_kw = {}
    if refresh_side_effect is not None:
        refresh_kw["side_effect"] = refresh_side_effect
    else:
        refresh_kw["return_value"] = refresh_payload

    finish_kw = {}
    if finish_side_effect is not None:
        finish_kw["side_effect"] = finish_side_effect

    call_order: list[str] = []

    def _finish(*_a, **kwargs):
        call_order.append("finish")
        call_order.append(f"finish_status:{kwargs.get('status')}")
        if finish_side_effect is not None:
            return finish_side_effect(*_a, **kwargs)
        return None

    def _release(*_a, **_k):
        call_order.append("release")

    def _refresh(*_a, **_k):
        call_order.append("targeted")
        if refresh_side_effect is not None:
            if isinstance(refresh_side_effect, BaseException):
                raise refresh_side_effect
            if callable(refresh_side_effect):
                return refresh_side_effect(*_a, **_k)
            raise refresh_side_effect
        return refresh_payload

    def _stage_b(*_a, **_k):
        call_order.append("stage_b_main")
        return {"ok": True, "shift_date_et": "2026-07-25"}

    def _post_reproject(*_a, **_k):
        # Second Stage-B only via post-lock helper when events inserted.
        call_order.append("stage_b_post")
        return {"ok": True, "shift_date_et": "2026-07-25", "post_lock": True}

    def _confirm(*_a, **kwargs):
        call_order.append("confirm")
        assert kwargs.get("run_finalize") is False
        return {
            "status": "batch_confirmed",
            "rinse_finalize": {
                "deferred": True,
                "reason": "post_lock_after_authoritative_cycle",
            },
        }

    def _finalize(*_a, **_k):
        call_order.append("finalize")
        if finalize_side_effect is not None:
            if isinstance(finalize_side_effect, BaseException):
                raise finalize_side_effect
            if callable(finalize_side_effect):
                return finalize_side_effect(*_a, **_k)
            raise finalize_side_effect
        return {"persistent_merge": {"events_inserted": 0, "bags_merged": 0}}

    with patch(
        "backend.rinse_off_portal_scan_refresh.refresh_pending_workload_scans_via_direct_lookup",
        side_effect=_refresh,
    ) as mock_refresh, patch(
        "backend.rinse_scheduled_scrape._refresh_open_step1_day_after_scrape",
        side_effect=_stage_b,
    ) as mock_stage_b, patch(
        "backend.rinse_scheduled_scrape.finish_scrape_run",
        side_effect=_finish,
    ) as mock_finish, patch(
        "backend.rinse_scheduled_scrape.release_scrape_lock",
        side_effect=_release,
    ) as mock_release, patch(
        "backend.upload_batch_confirm.confirm_upload_batch_core",
        side_effect=_confirm,
    ) as mock_confirm, patch(
        "backend.rinse_upload_finalize.finalize_rinse_after_batch_confirm",
        side_effect=_finalize,
    ) as mock_finalize, patch(
        "backend.rinse_step1_scrape_refresh.ensure_today_snapshot_if_missing",
    ) as mock_watchdog:
        for p in patches:
            p.start()
        try:
            # Re-bind post-lock reproject: first Stage-B is main; subsequent are post.
            stage_b_calls = {"n": 0}

            def _stage_b_split(*_a, **_k):
                stage_b_calls["n"] += 1
                if stage_b_calls["n"] == 1:
                    return _stage_b()
                return _post_reproject()

            mock_stage_b.side_effect = _stage_b_split
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")
        finally:
            for p in reversed(patches):
                p.stop()

    return (
        result,
        mock_refresh,
        mock_finish,
        mock_release,
        mock_stage_b,
        call_order,
        mock_confirm,
        mock_finalize,
        mock_watchdog,
    )


def test_scheduled_run_invokes_targeted_refresh_when_enabled():
    result, mock_refresh, *_rest = _run_scheduled_with_mocks()
    mock_refresh.assert_called_once()
    assert mock_refresh.call_args.kwargs.get("dry_run") is False
    detail = (result.detail or {}).get("targeted_pending_scan_refresh") or {}
    assert detail.get("targeted_refresh_ran") is True
    assert detail.get("post_lock") is True
    assert detail.get("targeted_bags_considered") == 1
    assert detail.get("missing_scans_imported") == 2


def test_scheduled_refresh_failure_does_not_fail_main_sync():
    result, *_rest = _run_scheduled_with_mocks(
        refresh_side_effect=RuntimeError("portal timeout"),
    )
    assert result.status in ("success", "needs_attention")
    detail = (result.detail or {}).get("targeted_pending_scan_refresh") or {}
    assert detail.get("targeted_refresh_ran") is False
    assert "portal timeout" in str(detail.get("error") or "")


def test_main_cycle_terminal_and_unlocked_before_targeted_hang():
    """Targeted hang must not leave main scrape running or hold the lock."""

    def _hang(*_a, **_k):
        raise TimeoutError("targeted hung past bound")

    result, _refresh, mock_finish, mock_release, _stage_b, order, *_rest = _run_scheduled_with_mocks(
        refresh_side_effect=_hang,
    )
    assert result.status == "success"
    mock_finish.assert_called_once()
    assert mock_finish.call_args.kwargs.get("status") == "success"
    mock_release.assert_called_once()
    # finish + release happen before targeted attempt
    assert order.index("finish") < order.index("targeted")
    assert order.index("release") < order.index("targeted")
    assert order.index("stage_b_main") < order.index("finish")
    assert order.index("release") < order.index("finalize")
    assert order.index("finalize") < order.index("targeted")


def test_targeted_zero_events_skips_reproject():
    result, _refresh, _finish, _release, mock_stage_b, order, *_rest = _run_scheduled_with_mocks(
        refresh_return={
            "dry_run": False,
            "bag_ids_requested": ["BAG1"],
            "bags_processed": 1,
            "events_inserted": 0,
            "lookup_failed": 0,
            "bags": [],
        },
    )
    assert result.status == "success"
    assert order.count("stage_b_main") == 1
    assert "stage_b_post" not in order
    skipped = (result.detail or {}).get("targeted_post_lock_step1_refresh") or {}
    assert skipped.get("skipped") is True
    assert skipped.get("reason") == "no_targeted_events"
    # Main Stage-B once; no second reproject call
    assert mock_stage_b.call_count == 1


def test_targeted_with_events_runs_separate_post_lock_reproject():
    result, _refresh, _finish, _release, mock_stage_b, order, *_rest = _run_scheduled_with_mocks(
        refresh_return={
            "dry_run": False,
            "bag_ids_requested": ["BAG1"],
            "bags_processed": 1,
            "events_inserted": 3,
            "lookup_failed": 0,
            "bags": [],
        },
    )
    assert result.status == "success"
    assert "stage_b_post" in order
    assert order.index("targeted") < order.index("stage_b_post")
    assert mock_stage_b.call_count == 2
    post = (result.detail or {}).get("targeted_post_lock_step1_refresh") or {}
    assert post.get("ok") is True


def test_main_import_failure_stays_failed_even_if_targeted_ok():
    import tempfile

    from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

    run_dir = Path(tempfile.mkdtemp())
    paths = ScrapePaths(
        run_dir=run_dir,
        portal_csv=run_dir / "portal.csv",
        scan_tickets_csv=run_dir / "t.csv",
        scan_events_csv=run_dir / "e.csv",
        log_path=run_dir / "log",
    )
    write_gate_passing_portal_csv(paths.portal_csv)
    paths.scan_events_csv.write_text("h\n1\n")

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"batch_id": 55, "c": 1}
    conn.cursor.return_value = cursor
    tenant = MagicMock()
    tenant.is_dir.return_value = True

    refresh_summary = {
        "targeted_refresh_ran": True,
        "targeted_bags_considered": 1,
        "targeted_bags_refreshed": 1,
        "missing_scans_imported": 3,
        "bags_completed_after_refresh": 1,
        "lookup_failures": 0,
    }

    order: list[str] = []

    def _finish(*_a, **kwargs):
        order.append(f"finish:{kwargs.get('status')}")

    def _release(*_a, **_k):
        order.append("release")

    def _targeted(*_a, **_k):
        order.append("targeted")
        return refresh_summary

    with patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant), patch(
        "backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")
    ), patch(
        "backend.rinse_scheduled_scrape.insert_scrape_run", return_value=1
    ), patch(
        "backend.rinse_scheduled_scrape.build_run_paths", return_value=paths
    ), patch(
        "backend.rinse_scheduled_scrape._run_bash_script", return_value=1
    ), patch(
        "backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}
    ), patch(
        "backend.rinse_scheduled_scrape._run_targeted_pending_scan_refresh",
        side_effect=_targeted,
    ), patch(
        "backend.rinse_scheduled_scrape._refresh_open_step1_day_after_scrape",
        return_value={"ok": True, "shift_date_et": "2026-07-25"},
    ), patch(
        "backend.rinse_scheduled_scrape.finish_scrape_run",
        side_effect=_finish,
    ), patch(
        "backend.rinse_scheduled_scrape.release_scrape_lock",
        side_effect=_release,
    ), patch(
        "backend.rinse_scheduled_scrape.merge_scrape_run_result_json",
    ):
        result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")

    assert result.status == "failed"
    assert order[0].startswith("finish:failed")
    assert order.index("release") < order.index("targeted")
    detail = (result.detail or {}).get("targeted_pending_scan_refresh") or {}
    assert detail.get("targeted_refresh_ran") is True
    assert detail.get("post_lock") is True
    assert (result.detail or {}).get("targeted_refresh_after_scrape_failure") is True


def test_targeted_failure_allows_next_lock_acquire():
    """After a successful main finish, a targeted failure must not leave status=running."""
    result, _refresh, mock_finish, mock_release, *_rest = _run_scheduled_with_mocks(
        refresh_side_effect=RuntimeError("lookup failed"),
    )
    assert result.status == "success"
    mock_finish.assert_called_once()
    assert mock_finish.call_args.kwargs["status"] == "success"
    mock_release.assert_called_once()


def test_helpers_gate_reproject_on_events():
    from backend.rinse_scheduled_scrape import (
        _targeted_refresh_inserted_events,
        _targeted_refresh_needs_reproject,
    )

    assert _targeted_refresh_inserted_events({"events_inserted": 0}) == 0
    assert _targeted_refresh_needs_reproject({"events_inserted": 0}) is False
    assert _targeted_refresh_needs_reproject({"missing_scans_imported": 2}) is True
    assert _targeted_refresh_needs_reproject(
        {"events_inserted": 0, "near_complete_wf_weight_backfill": {"applied": 1}}
    ) is True


def test_authoritative_confirm_runs_stage_b_before_targeted():
    result, _refresh, _finish, _release, mock_stage_b, order, mock_confirm, *_rest = (
        _run_scheduled_with_mocks()
    )
    assert result.status == "success"
    mock_confirm.assert_called_once()
    assert mock_confirm.call_args.kwargs.get("run_finalize") is False
    assert order.index("confirm") < order.index("stage_b_main")
    assert order.index("stage_b_main") < order.index("targeted")
    assert order.index("stage_b_main") < order.index("finalize")
    assert (result.detail or {}).get("rinse_finalize_deferred") is True
    assert mock_stage_b.call_count >= 1


def test_finalize_hang_leaves_today_current_and_main_terminal():
    result, _refresh, mock_finish, mock_release, mock_stage_b, order, *_rest = (
        _run_scheduled_with_mocks(
            finalize_side_effect=TimeoutError("finalize hung past bound"),
        )
    )
    assert result.status == "success"
    mock_finish.assert_called_once()
    assert mock_finish.call_args.kwargs.get("status") == "success"
    mock_release.assert_called_once()
    assert order.index("stage_b_main") < order.index("finish")
    assert order.index("release") < order.index("finalize")
    assert (result.detail or {}).get("step1_day_refresh", {}).get("ok") is True
    assert mock_stage_b.call_count >= 1
    post = (result.detail or {}).get("rinse_finalize_post_lock") or {}
    assert post.get("post_lock") is True
    assert "finalize hung" in str(post.get("error") or "")


def test_authoritative_import_creates_today_without_watchdog():
    result, _refresh, _finish, _release, mock_stage_b, order, _confirm, _fin, mock_watchdog = (
        _run_scheduled_with_mocks()
    )
    assert result.status == "success"
    assert "stage_b_main" in order
    mock_stage_b.assert_called()
    mock_watchdog.assert_not_called()
    assert (result.detail or {}).get("step1_day_refresh", {}).get("ok") is True


def test_combined_cycle_stage_b_unlock_before_targeted():
    """Combined wrapper: Stage-B + terminal main + unlock, then post-lock finalize/targeted."""
    from datetime import datetime
    import os
    import tempfile

    from backend.rinse_presence_scrape import PresenceScrapeResult
    from backend.rinse_scheduled_scrape import ScrapePaths, run_rinse_combined_sync_for_org

    run_dir = Path(tempfile.mkdtemp())
    paths = ScrapePaths(
        run_dir=run_dir,
        portal_csv=run_dir / "portal.csv",
        scan_tickets_csv=run_dir / "t.csv",
        scan_events_csv=run_dir / "e.csv",
        log_path=run_dir / "log",
    )
    write_gate_passing_portal_csv(paths.portal_csv)
    paths.scan_events_csv.write_text("h\n1\n")

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"c": 1}
    conn.cursor.return_value = cursor
    tenant = MagicMock()
    tenant.is_dir.return_value = True
    order: list[str] = []

    def _presence(*_a, **_k):
        order.append("presence")
        return PresenceScrapeResult(
            organization_id=3,
            portal_status="at_vendor",
            status="success",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            stats={"rows_found": 1, "active_rows": 1, "run_id": 50},
        )

    def _confirm(*_a, **kwargs):
        order.append("confirm")
        assert kwargs.get("run_finalize") is False
        return {
            "status": "batch_confirmed",
            "rinse_finalize": {"deferred": True},
        }

    def _stage_b(*_a, **_k):
        order.append("stage_b_main")
        return {"ok": True, "shift_date_et": "2026-08-14", "persisted": True}

    def _finish(*_a, **kwargs):
        order.append("finish")
        order.append(f"finish_status:{kwargs.get('status')}")

    def _release(*_a, **_k):
        order.append("release")

    def _finalize(*_a, **_k):
        order.append("finalize")
        return {"persistent_merge": {"events_inserted": 0}}

    def _targeted(*_a, **_k):
        order.append("targeted")
        return {
            "dry_run": False,
            "bag_ids_requested": [],
            "bags_processed": 0,
            "events_inserted": 0,
            "lookup_failed": 0,
            "bags": [],
        }

    patches = [
        patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
        patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
        patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=7),
        patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
        patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0),
        patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
        patch("backend.rinse_scheduled_scrape._count_accepted_rows", return_value=1),
        patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0),
        patch(
            "backend.rinse_scheduled_scrape._org_slug_name",
            return_value=("veewash", "VeeWash"),
        ),
        patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash"),
        patch(
            "backend.rinse_presence_scrape.run_presence_scrape_for_org",
            side_effect=_presence,
        ),
        patch(
            "backend.rinse_portal_csv.portal_csv_to_orders_df",
            return_value=pd.DataFrame([{"ticket_id": "ABC"}]),
        ),
        patch(
            "backend.rinse_scan_events_upload.parse_scan_events_csv",
            return_value=(MagicMock(), []),
        ),
        patch(
            "backend.rinse_combined_upload.commit_rinse_combined_upload",
            return_value={
                "batch_id": 99,
                "rows_inserted": 1,
                "portal_absence_allowed": True,
                "persistent_scan_merge": {"events_inserted": 4},
            },
        ),
        patch(
            "backend.upload_batch_confirm.confirm_upload_batch_core",
            side_effect=_confirm,
        ),
        patch(
            "backend.rinse_scheduled_scrape._refresh_open_step1_day_after_scrape",
            side_effect=_stage_b,
        ),
        patch("backend.rinse_scheduled_scrape.finish_scrape_run", side_effect=_finish),
        patch("backend.rinse_scheduled_scrape.release_scrape_lock", side_effect=_release),
        patch(
            "backend.rinse_upload_finalize.finalize_rinse_after_batch_confirm",
            side_effect=_finalize,
        ),
        patch(
            "backend.rinse_upload_finalize.fetch_accepted_portal_rows_for_finalize",
            return_value=[],
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_enabled",
            return_value=True,
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_dry_run",
            return_value=False,
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.off_portal_refresh_rush_only",
            return_value=False,
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.build_baseline_context",
            return_value={},
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline",
            return_value={},
        ),
        patch(
            "backend.rinse_off_portal_scan_refresh.refresh_pending_workload_scans_via_direct_lookup",
            side_effect=_targeted,
        ),
        patch("backend.rinse_scheduled_scrape.merge_scrape_run_result_json"),
    ]
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RFV_SCRAPE_ENABLED", None)
        for p in patches:
            p.start()
        try:
            result = run_rinse_combined_sync_for_org(conn, 3, run_type="scheduled")
        finally:
            for p in reversed(patches):
                p.stop()

    assert result.status == "success"
    assert order.index("confirm") < order.index("stage_b_main")
    assert order.index("stage_b_main") < order.index("finish")
    assert order.index("finish") < order.index("release")
    assert order.index("release") < order.index("finalize")
    assert order.index("finalize") < order.index("targeted")
    assert "stage_b_post" not in order
    assert (result.detail or {}).get("rinse_finalize_deferred") is True
