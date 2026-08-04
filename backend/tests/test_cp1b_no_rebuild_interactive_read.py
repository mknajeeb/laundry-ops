"""Checkpoint 1B — interactive Shift Monitor reads must not live-rebuild Step-1."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

D_AUG1 = date(2026, 8, 1)
D_AUG2 = date(2026, 8, 2)


def _persisted_summary(*, active=90, completed=72, pending=9, review=9):
    return {
        "selected_date_et": D_AUG1.isoformat(),
        "active_workload": active,
        "total_workload": active,
        "completed": completed,
        "pending": pending,
        "new_today": 80,
        "carryover": 10,
        "exceptions": {"review_required": review, "total": review},
        "segments": {
            "all": {
                "active_workload": active,
                "total_workload": active,
                "completed": completed,
                "pending": pending,
                "new_today": 80,
                "carryover": 10,
                "exceptions": {"review_required": review, "total": review},
                "bag_ids": {
                    "completed": ["C1"],
                    "pending": ["P1"],
                    "review_required": ["R1"],
                    "new_today": [],
                    "carryover": [],
                },
            },
            "wf": {
                "active_workload": active,
                "completed": completed,
                "pending": pending,
                "exceptions": {"review_required": review, "total": review},
                "bag_ids": {"review_required": ["R1"]},
            },
            "hd": {
                "active_workload": 0,
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": 0, "total": 0},
                "bag_ids": {"review_required": []},
            },
        },
        "shift_day": {"status": "OPEN", "read_only": False, "review_required_count": review},
    }


def test_persisted_snapshot_persist_live_false_returns_snapshot_no_rebuild():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    day = {
        "status": "OPEN",
        "headline": _persisted_summary(),
        "shift_date_et": D_AUG1,
        "review_required_count": 9,
    }
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D_AUG1),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=_persisted_summary(),
        ),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 8, 3)),
        patch("backend.rinse_veewash_shift_day._build_step1_workload_for_date") as rebuild,
        patch("backend.rinse_veewash_shift_day._ensure_specialty_metrics", side_effect=lambda *a, **k: a[-1]),
    ):
        wl, summary, meta = build_or_load_step1_for_date(
            cursor, 3, D_AUG1, persist_live=False, include_bag_rows=False
        )
    rebuild.assert_not_called()
    assert wl.get("from_snapshot") is True
    assert summary["active_workload"] == 90
    assert summary.get("data_unavailable") is not True
    assert meta["status"] == "OPEN"


def test_missing_snapshot_persist_live_false_returns_unavailable_no_rebuild():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D_AUG1),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=None),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 8, 3)),
        patch("backend.rinse_veewash_shift_day._build_step1_workload_for_date") as rebuild,
        patch(
            "backend.rinse_shift_day_close_archive.ensure_prior_et_day_archived_on_rollover",
            return_value={"ok": False},
        ),
    ):
        wl, summary, meta = build_or_load_step1_for_date(
            cursor, 3, D_AUG2, persist_live=False, include_bag_rows=False
        )
    rebuild.assert_not_called()
    assert summary["snapshot_available"] is False
    assert summary["snapshot_status"] == "missing"
    assert summary["data_unavailable"] is True
    assert summary["unavailable_reason"] == "step1_snapshot_missing"
    assert summary["active_workload"] is None
    assert summary["completed"] is None
    assert wl["data_unavailable"] is True
    assert meta["unavailable_reason"] == "step1_snapshot_missing"
    # Must not fabricate zero counts from live computation.
    assert summary["segments"]["all"]["completed"] is None


def test_missing_snapshot_persist_live_true_still_builds():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    fake_wl = {
        "selected_date_et": D_AUG2.isoformat(),
        "rows": [{"bag_id": "A"}],
        "membership": {"total_count": 1},
    }
    fake_summary = _persisted_summary(active=1, completed=0, pending=1, review=0)
    fake_summary["selected_date_et"] = D_AUG2.isoformat()

    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D_AUG1),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=None),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 8, 3)),
        patch(
            "backend.rinse_veewash_shift_day._build_step1_workload_for_date",
            return_value=fake_wl,
        ) as rebuild,
        patch(
            "backend.rinse_veewash_shift_day.build_step1_headline_summary",
            return_value=fake_summary,
        ),
        patch(
            "backend.rinse_hd_day_presentation.finalize_hd_step1_summary",
            side_effect=lambda summary, **k: summary,
        ),
        patch(
            "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary",
            side_effect=lambda *a, **k: a[-1],
        ),
        patch(
            "backend.rinse_veewash_shift_day.derive_shift_day_status",
            return_value="OPEN",
        ),
        patch(
            "backend.rinse_veewash_shift_day.persist_day_snapshot",
            return_value={"status": "OPEN", "headline": fake_summary},
        ) as persist,
        patch("backend.rinse_veewash_shift_day._commit"),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=fake_summary,
        ),
        patch(
            "backend.rinse_shift_day_close_archive.ensure_prior_et_day_archived_on_rollover",
            return_value={"ok": False},
        ),
    ):
        wl, summary, meta = build_or_load_step1_for_date(
            cursor, 3, D_AUG2, persist_live=True, include_bag_rows=False
        )
    rebuild.assert_called_once()
    persist.assert_called_once()
    assert summary["active_workload"] == 1
    assert summary.get("data_unavailable") is not True


def test_lightweight_summary_missing_snapshot_does_not_escalate_to_persist_live():
    from backend.rinse_simple_shift_performance import _try_build_step1_lightweight_summary

    cursor = MagicMock()
    missing_wl = {
        "selected_date_et": D_AUG2.isoformat(),
        "rows": [],
        "data_unavailable": True,
        "snapshot_available": False,
        "unavailable_reason": "step1_snapshot_missing",
    }
    missing_summary = {
        "selected_date_et": D_AUG2.isoformat(),
        "active_workload": None,
        "completed": None,
        "pending": None,
        "exceptions": {"review_required": None, "total": None},
        "segments": {"all": {"active_workload": None, "completed": None}},
        "data_unavailable": True,
        "snapshot_available": False,
        "snapshot_status": "missing",
        "unavailable_reason": "step1_snapshot_missing",
        "message": "Shift Monitor snapshot is not available yet. Counts will appear after a successful scan refresh.",
        "shift_day": {
            "status": None,
            "read_only": True,
            "data_unavailable": True,
            "unavailable_reason": "step1_snapshot_missing",
        },
    }
    day_meta = {
        "status": None,
        "data_unavailable": True,
        "unavailable_reason": "step1_snapshot_missing",
    }

    calls = []

    def fake_build(cursor, org, day, *, persist_live=True, include_bag_rows=True):
        calls.append({"persist_live": persist_live, "include_bag_rows": include_bag_rows})
        assert persist_live is False
        return missing_wl, missing_summary, day_meta

    with (
        patch("backend.rinse_veewash_workload.is_step1_enabled", return_value=True),
        patch("backend.rinse_veewash_workload.get_step1_activation_date", return_value=D_AUG1),
        patch(
            "backend.rinse_veewash_shift_day.build_or_load_step1_for_date",
            side_effect=fake_build,
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline",
            return_value={"baseline_source": "latest_clean_veewash_scrape"},
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.format_baseline_banner_et",
            return_value="Baseline",
        ),
        patch(
            "backend.rinse_simple_shift_performance._attach_step1_lightweight_sync_statuses",
            return_value={"at_vendor": {"enabled": True}},
        ) as attach_sync,
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        ) as freshness,
    ):
        body = _try_build_step1_lightweight_summary(
            cursor,
            3,
            period_start=D_AUG2,
            period_end=D_AUG2,
            eval_at=None,
            t0=0.0,
        )

    assert body is not None
    assert len(calls) == 1
    assert calls[0]["persist_live"] is False
    freshness.assert_not_called()
    attach_sync.assert_not_called()
    assert body["data_unavailable"] is True
    assert body["unavailable_reason"] == "step1_snapshot_missing"
    assert body["at_vendor_module"]["daily_metrics_reliable"] is False
    assert body["at_vendor_module"]["veewash_step1_summary"]["completed"] is None
    assert "successful scan refresh" in (body["at_vendor_module"]["daily_metrics_ui_warning"] or "")
    assert body["rinse_sync"]["at_vendor"]["status"] == "snapshot_unavailable"


def test_drilldown_missing_snapshot_explicit_unavailable():
    from backend.rinse_veewash_step1_api import build_drilldown

    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_headline", return_value=None),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=None),
        patch("backend.rinse_veewash_step1_api.build_step1_payload") as rebuild,
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D_AUG2,
            metric="review_required",
            include_details=False,
        )
    rebuild.assert_not_called()
    assert out["bags"] == []
    assert out["snapshot_missing"] is True
    assert out["snapshot_available"] is False
    assert out["snapshot_status"] == "missing"
    assert out["data_unavailable"] is True
    assert out["unavailable_reason"] == "step1_snapshot_missing"
    assert "successful scan refresh" in (out.get("message") or "")
