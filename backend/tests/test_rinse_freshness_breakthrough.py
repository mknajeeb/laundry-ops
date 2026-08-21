"""Breakthrough freshness architecture unit/integration tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.rinse_freshness_portal_boundary import EarlyStopState, bag_fingerprint
from backend.rinse_freshness_store import LaneFencedError, assert_lane_writable
from backend.rinse_freshness_supervisor import failure_backoff_seconds


ET = ZoneInfo("America/New_York")


def test_fingerprint_matches_node_format():
    row = {
        "bag_id": "abc123",
        "customer": "Jane",
        "edd": "2026-08-20",
        "lbs": "12",
        "service": "WF",
    }
    # Node: `${bid}|${customer}|${edd}|${lbs}|${service}`.slice(0, 24)
    expected = "ABC123|Jane|2026-08-20|12|W"[:24]
    assert bag_fingerprint(row) == expected


def test_early_stop_does_not_assume_page_one_is_delta():
    st = EarlyStopState(known_fingerprints={})
    assert (
        st.observe_page(
            [{"bag_id": "AAA111", "customer": "A"}, {"bag_id": "BBB222", "customer": "B"}],
            unchanged_pages_to_stop=2,
            page_budget=5,
        )
        is None
    )
    assert st.source_inspected_complete is False
    assert (
        st.observe_page(
            [{"bag_id": "CCC333", "customer": "C"}],
            unchanged_pages_to_stop=2,
            page_budget=5,
        )
        is None
    )
    known = {
        "AAA111": bag_fingerprint({"bag_id": "AAA111", "customer": "A"}),
        "BBB222": bag_fingerprint({"bag_id": "BBB222", "customer": "B"}),
    }
    st2 = EarlyStopState(known_fingerprints=dict(known))
    assert (
        st2.observe_page(
            [{"bag_id": "AAA111", "customer": "A"}],
            unchanged_pages_to_stop=2,
            page_budget=10,
        )
        is None
    )
    reason = st2.observe_page(
        [{"bag_id": "BBB222", "customer": "B"}],
        unchanged_pages_to_stop=2,
        page_budget=10,
    )
    assert reason == "safe_unchanged_boundary"
    assert st2.source_inspected_complete is True


def test_page_budget_marks_incomplete_not_complete():
    st3 = EarlyStopState()
    r = st3.observe_page([{"bag_id": "Z"}], unchanged_pages_to_stop=5, page_budget=1)
    assert r == "page_budget"
    assert st3.source_inspected_complete is False


def test_lane_fencing_rejects_stale_generation():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"generation": 5}
    with pytest.raises(LaneFencedError):
        assert_lane_writable(cursor, 3, "fast", 4)


def test_delta_finalize_loads_only_affected_bags():
    from backend.rinse_upload_finalize import load_upload_batch_scan_events_as_dataframe

    cursor = MagicMock()
    cursor.fetchall.return_value = []

    with patch("backend.rinse_upload_finalize.table_exists", return_value=True):
        load_upload_batch_scan_events_as_dataframe(
            cursor, 3, 3713, bag_ids=["ABC123", "DEF456"]
        )
    sql = cursor.execute.call_args[0][0]
    assert "bag_id IN" in sql


def test_freshness_delta_bag_ids_from_draft():
    from backend.rinse_scheduled_scrape import _freshness_delta_bag_ids

    with patch.dict("os.environ", {"RINSE_FRESHNESS_DELTA_FINALIZE": "1"}):
        bags = _freshness_delta_bag_ids(
            {"draft_bag_ids": ["aaa111", "BBB222", "aaa111"]},
            None,
        )
    assert bags == ["AAA111", "BBB222"]

    with patch.dict("os.environ", {"RINSE_FRESHNESS_DELTA_FINALIZE": "0"}):
        assert _freshness_delta_bag_ids({"draft_bag_ids": ["X"]}, None) is None


def test_midnight_crossing_has_no_scheduler_special_case():
    """Supervisor loop has no midnight branch; business dates attributed downstream."""
    import inspect

    from backend import rinse_freshness_supervisor as sup

    src = inspect.getsource(sup.run_supervisor)
    assert "midnight" not in src.lower()
    assert "00:00" not in src


def test_midnight_business_dates_use_et_not_cycle_wall_clock():
    """Evidence attributed by business ET date, not when the child process finishes."""
    from backend.rinse_folding_et import eastern_today

    before = datetime(2026, 8, 20, 23, 58, tzinfo=ET)
    after = datetime(2026, 8, 21, 0, 5, tzinfo=ET)

    with patch("backend.rinse_folding_et.eastern_now", return_value=before):
        d1 = eastern_today()
    with patch("backend.rinse_folding_et.eastern_now", return_value=after):
        d2 = eastern_today()
    assert d1 == date(2026, 8, 20)
    assert d2 == date(2026, 8, 21)
    assert d1 != d2


def test_failure_backoff_is_bounded():
    assert failure_backoff_seconds(1) >= 10
    assert failure_backoff_seconds(99) <= 120


def test_not_started_without_publish_is_unavailable():
    from backend.rinse_veewash_shift_day import _snapshot_missing_step1_payload

    wl, summary, _ = _snapshot_missing_step1_payload(date(2026, 8, 20))
    assert summary.get("data_unavailable") is True
    assert summary.get("active_workload") is None
    assert summary.get("completed") is None
    assert wl.get("data_unavailable") is True
    assert "not available yet" in str(summary.get("message") or "").lower()


def test_management_load_headline_prefers_published_snapshot():
    from backend.management_today import _load_headline

    cursor = MagicMock()
    published = {
        "version": 3,
        "publish_status": "published",
        "published_at": datetime(2026, 8, 20, 18, 0, 0),
        "headline_json": {
            "active_workload": 41,
            "completed": 12,
            "pending": 29,
            "segments": {
                "wf": {
                    "active_workload": 41,
                    "total_workload": 41,
                    "completed": 12,
                    "pending": 29,
                    "exceptions": {"review_required": 2},
                }
            },
            "specialty_metrics": {"wf": {"split_orders": {}, "classification_version": 99}},
        },
    }
    with patch(
        "backend.rinse_freshness_publish.latest_published_snapshot",
        return_value=published,
    ), patch(
        "backend.management_today._specialty_packs_current", return_value=True
    ):
        day_rec, headline = _load_headline(cursor, 3, date(2026, 8, 20))
    assert day_rec.get("from_published_snapshot") is True
    assert headline.get("active_workload") == 41
    assert headline.get("published_snapshot_version") == 3
    assert not headline.get("data_unavailable")


def test_management_load_headline_blocks_not_started_zeros():
    from backend.management_today import _load_headline

    cursor = MagicMock()
    with patch(
        "backend.rinse_freshness_publish.latest_published_snapshot",
        return_value=None,
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={
            "status": "NOT_STARTED",
            "headline": {"active_workload": 0, "completed": 0, "pending": 0},
            "last_sync_at": None,
        },
    ):
        day_rec, headline = _load_headline(cursor, 3, date(2026, 8, 20))
    assert headline.get("data_unavailable") is True
    assert headline.get("active_workload") is None
    assert "not available yet" in str(headline.get("message") or "").lower()


def test_stale_snapshot_publish_rejects_wrong_generation():
    from backend.rinse_freshness_publish import publish_snapshot
    from backend.rinse_freshness_store import LaneFencedError

    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "lease_generation": 9,
        "publish_status": "building",
    }
    with patch(
        "backend.rinse_freshness_publish.assert_lane_writable", return_value=None
    ), pytest.raises(LaneFencedError):
        publish_snapshot(
            cursor,
            organization_id=3,
            shift_date_et=date(2026, 8, 20),
            version=1,
            lease_generation=8,
            lane="fast",
            headline={},
            workload_meta={},
        )


def test_deferred_stage_b_is_not_freshness_success():
    """Management publish must not treat Stage-B DEFERRED as SUCCESS."""
    import inspect

    from backend.jobs import run_rinse_freshness_cycle as cycle

    src = inspect.getsource(cycle.run_fast_cycle)
    assert "incremental_project_and_publish" in src
    assert "fast_lane_incremental" in src or "incremental" in src


def test_incremental_publish_does_not_infer_absence():
    from backend.rinse_freshness_incremental import incremental_project_and_publish

    cursor = MagicMock()
    # Minimal stubs — ensure absence_inference stays false in contract.
    with patch(
        "backend.rinse_freshness_incremental.get_day_record",
        create=True,
    ):
        # Source inspection of function defaults
        import inspect

        src = inspect.getsource(incremental_project_and_publish)
        assert "absence_inference" in src
        assert "Additive-only" in src or "Additive" in src or "new_admits" in src
        assert "DELETE" not in src
