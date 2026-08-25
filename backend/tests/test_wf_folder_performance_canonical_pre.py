"""Performance PRE must match Management Rinse WF canonical PRE."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.management_wf_folder_performance import (
    apply_canonical_pre_to_folder_performance_bags,
    build_day_folder_performance,
    weighted_aggregate_rates,
)
from backend.rinse_folding_folder_role_productivity import _bag_credited_lbs_pre

ORG = 3
DAY = date(2026, 8, 24)


def test_overlay_replaces_stale_day_bag_pre_with_canonical():
    bags = [
        {
            "bag_id": "STALE1",
            "service_type": "WF",
            "pre_weight_lbs": 27.6,
            "productivity_weight_lbs": 27.6,
            "credited_weight_lbs": 27.6,
            "credited_weight_source": "EVIDENCE_PRE",
        },
        {
            "bag_id": "OK1",
            "service_type": "WF",
            "pre_weight_lbs": 20.0,
            "credited_weight_lbs": 20.0,
            "credited_weight_source": "EVIDENCE_PRE",
        },
    ]
    weight_map = {
        "STALE1": {"evidence_pre_weight_lbs": 26.4, "pre_weight_lbs": 26.4},
        "OK1": {"evidence_pre_weight_lbs": 20.0, "pre_weight_lbs": 20.0},
    }
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value=weight_map,
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        side_effect=lambda w: (w or {}).get("evidence_pre_weight_lbs"),
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    by_id = {b["bag_id"]: b for b in out}
    assert _bag_credited_lbs_pre(by_id["STALE1"]) == 26.4
    assert by_id["STALE1"].get("productivity_weight_lbs") is None
    assert _bag_credited_lbs_pre(by_id["OK1"]) == 20.0
    assert sum(_bag_credited_lbs_pre(b) for b in out) == 46.4


def test_overlay_does_not_use_post_weight():
    bags = [
        {
            "bag_id": "BAGPOST1",
            "service_type": "WF",
            "pre_weight_lbs": 30.0,
            "post_weight_lbs": 99.0,
            "credited_weight_lbs": 30.0,
        }
    ]
    weight_map = {
        "BAGPOST1": {
            "evidence_pre_weight_lbs": 21.0,
            "pre_weight_lbs": 21.0,
            "post_weight_lbs": 99.0,
        }
    }
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value=weight_map,
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        side_effect=lambda w: (w or {}).get("evidence_pre_weight_lbs"),
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert _bag_credited_lbs_pre(out[0]) == 21.0
    assert out[0].get("post_weight_lbs") == 99.0


def test_manager_correction_updates_performance_pre():
    bags = [
        {
            "bag_id": "CORR01",
            "service_type": "WF",
            "pre_weight_lbs": 40.0,
            "credited_weight_lbs": 40.0,
        }
    ]
    # Manager correction wins in authoritative_evidence_pre_lbs
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={"CORR01": {"corrected_pre_weight_lbs": 18.5}},
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        return_value=18.5,
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert _bag_credited_lbs_pre(out[0]) == 18.5


def test_clearing_manager_correction_returns_to_portal_pre():
    bags = [
        {
            "bag_id": "CORR01",
            "service_type": "WF",
            "pre_weight_lbs": 40.0,
            "credited_weight_lbs": 40.0,
        }
    ]
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={"CORR01": {"evidence_pre_weight_lbs": 22.0}},
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        return_value=22.0,
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert _bag_credited_lbs_pre(out[0]) == 22.0


def test_settled_bulk_only_stays_zero_credit():
    bags = [
        {
            "bag_id": "BULK01",
            "service_type": "WF",
            "pre_weight_lbs": 12.0,
            "credited_weight_lbs": 0.0,
            "settled_bulk_only": True,
        }
    ]
    with patch(
        "backend.rinse_settled_bulk_only_weight.row_is_settled_bulk_only_for_productivity",
        return_value=True,
    ), patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={"BULK01": {"evidence_pre_weight_lbs": 12.0}},
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert _bag_credited_lbs_pre(out[0]) == 0.0


def test_lb_hr_recomputes_from_canonical_numerator():
    rates = weighted_aggregate_rates(
        total_orders=113,
        total_pre_lbs=2297.3,
        total_session_hours=51.8976,
    )
    assert rates["lbs_per_hour"] == round(2297.3 / 51.8976, 4)
    assert rates["bags_per_hour"] == round(113 / 51.8976, 4)


def test_day_build_overlays_canonical_before_aggregation():
    """Overlay runs inside day build so stale day-bag PRE cannot win."""
    stale_bags = [
        {
            "bag_id": "BAGA0001",
            "service_type": "WF",
            "pre_weight_lbs": 30.0,
            "credited_weight_lbs": 30.0,
            "credited_weight_source": "EVIDENCE_PRE",
            "productivity_employee_name": "Folder A",
            "canonical_completion_employee": "Folder A",
            "productivity_completed_at": "2026-08-24 10:00:00",
            "canonical_completion_timestamp": "2026-08-24 10:00:00",
            "effective_status": "completed",
            "productivity_credit_eligible": 1,
            "employee": "Folder A",
            "credited_employee": "Folder A",
        },
        {
            "bag_id": "BAGB0001",
            "service_type": "WF",
            "pre_weight_lbs": 25.0,
            "credited_weight_lbs": 25.0,
            "credited_weight_source": "EVIDENCE_PRE",
            "productivity_employee_name": "Folder A",
            "canonical_completion_employee": "Folder A",
            "productivity_completed_at": "2026-08-24 10:05:00",
            "canonical_completion_timestamp": "2026-08-24 10:05:00",
            "effective_status": "completed",
            "productivity_credit_eligible": 1,
            "employee": "Folder A",
            "credited_employee": "Folder A",
        },
    ]
    weight_map = {
        "BAGA0001": {"evidence_pre_weight_lbs": 20.0},
        "BAGB0001": {"evidence_pre_weight_lbs": 18.5},
    }

    with (
        patch(
            "backend.management_wf_folder_performance.load_completed_productivity_day_bags",
            return_value=stale_bags,
        ),
        patch(
            "backend.management_wf_folder_performance.load_active_attribution_overrides",
            return_value={},
        ),
        patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value={},
        ),
        patch(
            "backend.management_wf_folder_performance.load_day_job_segments_by_user",
            return_value={},
        ),
        patch(
            "backend.management_wf_folder_performance.load_shift_sessions_by_id",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_review.load_bag_weight_map",
            return_value=weight_map,
        ),
        patch(
            "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
            side_effect=lambda w: (w or {}).get("evidence_pre_weight_lbs"),
        ),
    ):
        day = build_day_folder_performance(
            MagicMock(), ORG, selected_date_et=DAY, attach_customers=False
        )

    unmapped = day.get("unmapped_orders") or []
    assert len(unmapped) == 2
    assert round(sum(float(o.get("pre_lbs") or 0) for o in unmapped), 2) == 38.5
    raw = day.get("_unmapped_raw") or []
    assert round(sum(_bag_credited_lbs_pre(o) for o in raw), 2) == 38.5


def test_employee_pounds_equal_canonical_sum_of_employee_bags():
    bags = [
        {
            "bag_id": "EMPB0001",
            "service_type": "WF",
            "pre_weight_lbs": 50.0,
            "credited_weight_lbs": 50.0,
            "credited_weight_source": "EVIDENCE_PRE",
        },
        {
            "bag_id": "EMPB0002",
            "service_type": "WF",
            "pre_weight_lbs": 40.0,
            "credited_weight_lbs": 40.0,
            "credited_weight_source": "EVIDENCE_PRE",
        },
    ]
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={
            "EMPB0001": {"evidence_pre_weight_lbs": 12.0},
            "EMPB0002": {"evidence_pre_weight_lbs": 8.0},
        },
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        side_effect=lambda w: (w or {}).get("evidence_pre_weight_lbs"),
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert round(sum(_bag_credited_lbs_pre(b) for b in out), 2) == 20.0


def test_stale_persisted_pre_cannot_override_portal_canonical():
    bags = [
        {
            "bag_id": "STALE100",
            "service_type": "WF",
            "pre_weight_lbs": 100.0,
            "productivity_weight_lbs": 100.0,
            "credited_weight_lbs": 100.0,
        }
    ]
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={"STALE100": {"evidence_pre_weight_lbs": 7.3}},
    ), patch(
        "backend.rinse_current_cycle_weight.authoritative_evidence_pre_lbs",
        return_value=7.3,
    ):
        out = apply_canonical_pre_to_folder_performance_bags(
            MagicMock(), ORG, DAY, bags
        )
    assert _bag_credited_lbs_pre(out[0]) == 7.3
    assert out[0]["pre_weight_lbs"] == 7.3
