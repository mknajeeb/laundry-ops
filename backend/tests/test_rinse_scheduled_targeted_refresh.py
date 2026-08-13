"""Scheduled targeted refresh runs post-lock after main cycle is terminal."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pandas as pd

from backend.tests.portal_csv_gate_fixtures import write_gate_passing_portal_csv


def _run_scheduled_with_mocks(
    *,
    refresh_side_effect=None,
    refresh_return=None,
    finish_side_effect=None,
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
            },
        ),
        patch(
            "backend.upload_batch_confirm.confirm_upload_batch_core",
            return_value={"ok": True},
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
    ) as mock_release:
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

    return result, mock_refresh, mock_finish, mock_release, mock_stage_b, call_order


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

    result, _refresh, mock_finish, mock_release, _stage_b, order = _run_scheduled_with_mocks(
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


def test_targeted_zero_events_skips_reproject():
    result, _refresh, _finish, _release, mock_stage_b, order = _run_scheduled_with_mocks(
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
    result, _refresh, _finish, _release, mock_stage_b, order = _run_scheduled_with_mocks(
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
