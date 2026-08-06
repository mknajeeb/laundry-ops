"""Checkpoint 2A: day-bag completion projection from scan chronology."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_evidence_pipeline import continue_presence_run_downstream
from backend.rinse_veewash_shift_day import reproject_day_bag_completions_from_chronology


def test_reproject_freezes_membership_and_persists_completions():
    cursor = MagicMock()
    frozen = ["BAG1", "BAG2", "BAG3"]
    wl = {
        "new_today": list(frozen),
        "completed_on_date": ["BAG1"],
        "pending_end_of_date": ["BAG2"],
        "review_required": ["BAG3"],
        "rows": [
            {"bag_id": "BAG1", "outcome": "completed", "service_type": "WF"},
            {"bag_id": "BAG2", "outcome": "pending", "service_type": "WF"},
            {"bag_id": "BAG3", "outcome": "review_required", "service_type": "HD"},
        ],
        "membership": {"ok": True, "total_count": 3},
    }
    summary = {
        "active_workload": 3,
        "total_workload": 3,
        "completed": 1,
        "pending": 1,
        "exceptions": {"review_required": 1},
        "membership": wl["membership"],
    }

    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"status": "OPEN"},
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            side_effect=[
                [{"bag_id": b} for b in frozen],
                [
                    {"bag_id": "BAG1", "effective_status": "completed"},
                    {"bag_id": "BAG2", "effective_status": "pending"},
                    {"bag_id": "BAG3", "effective_status": "review_required"},
                ],
            ],
        ),
        patch(
            "backend.rinse_veewash_shift_day.get_step1_activation_date",
            return_value=date(2026, 7, 23),
        ),
        patch(
            "backend.rinse_veewash_shift_day.build_veewash_daily_workload_from_membership",
            return_value=wl,
        ) as build_wl,
        patch(
            "backend.rinse_veewash_shift_day.build_step1_headline_summary",
            return_value=summary,
        ),
        patch(
            "backend.rinse_hd_day_presentation.finalize_hd_step1_summary",
            side_effect=lambda s, **k: s,
        ),
        patch(
            "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary",
            side_effect=lambda _c, _o, _d, s, **k: s,
        ),
        patch(
            "backend.rinse_veewash_shift_day.persist_day_snapshot",
            return_value={"status": "OPEN"},
        ) as persist,
        patch("backend.rinse_veewash_shift_day._commit"),
        patch(
            "backend.rinse_veewash_shift_day.derive_shift_day_status",
            return_value="OPEN",
        ),
    ):
        out = reproject_day_bag_completions_from_chronology(
            cursor, 3, date(2026, 8, 6)
        )

    assert out["ok"] is True
    assert out["persisted"] is True
    assert out["membership_count"] == 3
    assert out["completed_count"] == 1
    build_wl.assert_called_once()
    assert build_wl.call_args.kwargs.get("frozen_member_ids") == frozen
    persist.assert_called_once()


def test_presence_projections_stage_calls_day_bag_reproject():
    cursor = MagicMock()
    run = {
        "id": 99,
        "organization_id": 3,
        "status": "success",
        "evidence_processing_stage": "weights_attached",
        "finished_at": datetime(2026, 8, 6, 19, 15, 0),
    }

    with (
        patch(
            "backend.rinse_presence_evidence_pipeline._load_presence_run",
            return_value=run,
        ),
        patch(
            "backend.rinse_presence_evidence_pipeline._et_date_from_run",
            return_value=date(2026, 8, 6),
        ),
        patch(
            "backend.rinse_veewash_shift_day.reproject_day_bag_completions_from_chronology",
            return_value={
                "ok": True,
                "persisted": True,
                "skipped": False,
                "membership_count": 79,
                "completed_count": 46,
                "summary_totals": {"completed": 46},
            },
        ) as reproject,
        patch(
            "backend.rinse_presence_evidence_pipeline.set_presence_run_processing_stage"
        ) as set_stage,
    ):
        out = continue_presence_run_downstream(cursor, 3, 99)

    assert out["ok"] is True
    assert out["projections"]["mode"] == "day_bag_completion_reproject"
    assert out["projections"]["completed_count"] == 46
    reproject.assert_called_once()
    assert set_stage.called
    assert "projections_refreshed" in (out.get("stages_completed") or [])


def test_presence_reprojects_even_when_stage_already_projections_refreshed():
    """Old read_time_noop marker must not block completion refresh."""
    cursor = MagicMock()
    run = {
        "id": 100,
        "organization_id": 3,
        "status": "success",
        "evidence_processing_stage": "projections_refreshed",
        "finished_at": datetime(2026, 8, 6, 19, 15, 0),
    }

    with (
        patch(
            "backend.rinse_presence_evidence_pipeline._load_presence_run",
            return_value=run,
        ),
        patch(
            "backend.rinse_presence_evidence_pipeline._et_date_from_run",
            return_value=date(2026, 8, 6),
        ),
        patch(
            "backend.rinse_veewash_shift_day.reproject_day_bag_completions_from_chronology",
            return_value={
                "ok": True,
                "persisted": True,
                "skipped": False,
                "membership_count": 79,
                "completed_count": 46,
            },
        ) as reproject,
        patch(
            "backend.rinse_presence_evidence_pipeline.set_presence_run_processing_stage"
        ),
    ):
        out = continue_presence_run_downstream(cursor, 3, 100)

    assert out["ok"] is True
    reproject.assert_called_once()
    assert out["projections"]["completed_count"] == 46
