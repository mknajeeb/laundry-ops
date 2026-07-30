"""Settled bulk-only POST projection + EP gate (presentation overlay)."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_bulk_workitems import RESOLUTION_ITEMS
from backend.rinse_settled_bulk_only_weight import (
    PROD_EXCLUSION_SETTLED_BULK_ONLY,
    apply_settled_bulk_only_post_overlay,
    final_portal_wf_lbs_from_observations,
    is_manual_correction_protected,
    is_settled_bulk_only,
    project_productivity_override_for_settled_bulk_only,
    row_is_settled_bulk_only_for_productivity,
)
from backend.rinse_step1_productivity_fast import (
    _weight_lbs,
    _wf_credited_weight_fields,
    project_productivity_fields_for_day_bag,
)


def _lines(name: str = "Comforter", qty: int = 1):
    return [
        {
            "workitem_name": name,
            "quantity": qty,
            "unit_price": 15.0,
            "line_total": 15.0 * qty,
        }
    ]


def _resolution_items(total: float = 15.0):
    return {
        "resolution_type": RESOLUTION_ITEMS,
        "items_total": total,
        "no_charge_reason": None,
    }


def _weight_info(
    *,
    pre: float = 8.3,
    post: float = 8.3,
    revenue_valid: bool = True,
    post_exists: bool = True,
    status: str = "CONFIRMED",
    garments_reviewed: bool = True,
    corrected_post=None,
):
    info = {
        "pre_weight_lbs": pre,
        "post_weight_lbs": post,
        "post_weight_value": post,
        "post_weight_event_exists": post_exists,
        "post_weight_valid_for_standard_weight_revenue": revenue_valid,
        "post_resolution_status": status,
        "weight_entry_count": 2 if post_exists else 1,
        "pre_weight_employee": "Op PRE",
        "post_weight_employee": "Op POST",
        "pre_weight_at": datetime(2026, 7, 28, 8, 0),
        "post_weight_at": datetime(2026, 7, 28, 14, 0),
        "garments_reviewed_at": datetime(2026, 7, 28, 13, 50) if garments_reviewed else None,
    }
    if corrected_post is not None:
        info["corrected_post_weight_lbs"] = corrected_post
        info["post_resolution_status"] = "MANUAL_CORRECTION"
    return info


def test_settled_comforter_only_forces_post_to_final_portal_zero():
    info = _weight_info(pre=8.3, post=8.3, revenue_valid=True)
    assert is_settled_bulk_only(
        final_portal_wf=0.0,
        lines=_lines("Comforter"),
        resolution=_resolution_items(),
        weight_info=info,
    )
    out = apply_settled_bulk_only_post_overlay(info, final_portal_wf=0.0)
    assert out["pre_weight_lbs"] == 8.3
    assert out["post_weight_lbs"] == 0.0
    assert out["post_weight_value"] == 0.0
    assert out["authoritative_post_weight_lbs"] == 0.0
    assert out["post_weight_valid_for_standard_weight_revenue"] is False
    assert out["settled_bulk_only"] is True
    # Raw/early POST preserved for evidence
    assert out["raw_post_weight_lbs"] == 8.3
    assert out["pre_weight_employee"] == "Op PRE"
    assert out["post_weight_employee"] == "Op POST"


def test_settled_bath_mat_only_same_behavior():
    info = _weight_info(pre=6.2, post=6.2, revenue_valid=True)
    assert is_settled_bulk_only(
        final_portal_wf=0.0,
        lines=_lines("Bath Mat"),
        resolution=_resolution_items(),
        weight_info=info,
    )
    out = apply_settled_bulk_only_post_overlay(info, final_portal_wf=0.0)
    assert out["pre_weight_lbs"] == 6.2
    assert out["post_weight_lbs"] == 0.0


def test_temporary_zero_does_not_activate():
    # Portal zero but no POST evidence / no garments-reviewed
    info = _weight_info(
        pre=8.3,
        post=None,
        revenue_valid=False,
        post_exists=False,
        status="WAITING_FOR_EVENT",
        garments_reviewed=False,
    )
    info["post_weight_lbs"] = None
    info["post_weight_value"] = None
    info["post_weight_at"] = None
    info["weight_entry_count"] = 1
    assert (
        is_settled_bulk_only(
            final_portal_wf=0.0,
            lines=_lines("Comforter"),
            resolution=_resolution_items(),
            weight_info=info,
        )
        is False
    )


def test_mixed_wf_plus_comforter_unchanged():
    info = _weight_info(pre=31.1, post=27.5, revenue_valid=True)
    assert (
        is_settled_bulk_only(
            final_portal_wf=27.5,
            lines=_lines("Comforter"),
            resolution=_resolution_items(),
            weight_info=info,
        )
        is False
    )


def test_manual_correction_preserved():
    info = _weight_info(pre=8.3, post=0.0, revenue_valid=False, corrected_post=0.0)
    assert is_manual_correction_protected(info) is True
    assert (
        is_settled_bulk_only(
            final_portal_wf=0.0,
            lines=_lines("Comforter"),
            resolution=_resolution_items(),
            weight_info=info,
        )
        is False
    )


def test_bulk_review_open_without_confirmed_quantity_no_full_overlay():
    info = _weight_info(pre=14.8, post=0.0, revenue_valid=False)
    assert (
        is_settled_bulk_only(
            final_portal_wf=0.0,
            lines=[],  # no chargeable qty yet
            resolution=None,
            weight_info=info,
        )
        is False
    )


def test_employee_productivity_bulk_only_zero_credit():
    row = {
        "service_type": "WF",
        "effective_status": "completed",
        "pre_weight_lbs": 8.3,
        "post_weight_lbs": 0.0,
        "settled_bulk_only": True,
        "canonical_completion_employee": "Yessenia (Veewash)",
        "canonical_completion_timestamp": datetime(2026, 7, 28, 14, 15),
    }
    proj = project_productivity_fields_for_day_bag(row)
    assert proj["productivity_weight_lbs"] == 0.0
    assert proj["productivity_credit_eligible"] == 0
    assert proj["productivity_exclusion_reason"] == PROD_EXCLUSION_SETTLED_BULK_ONLY

    # Future eligibility flip must still not credit PRE
    flipped = {
        **row,
        "productivity_credit_eligible": 1,
        "productivity_exclusion_reason": PROD_EXCLUSION_SETTLED_BULK_ONLY,
        "productivity_weight_lbs": 0.0,
    }
    assert _weight_lbs(flipped) == 0.0
    credited = _wf_credited_weight_fields(flipped)
    assert credited["credited_weight_lbs"] == 0.0
    assert credited["pre_weight_lbs"] == 8.3  # evidence PRE still visible


def test_raw_evidence_operators_remain_visible_after_overlay():
    info = _weight_info(pre=9.1, post=9.1)
    out = apply_settled_bulk_only_post_overlay(info, final_portal_wf=0.0)
    assert out["pre_weight_employee"] == "Op PRE"
    assert out["post_weight_employee"] == "Op POST"
    assert out["pre_weight_at"] == datetime(2026, 7, 28, 8, 0)
    assert out["post_weight_at"] == datetime(2026, 7, 28, 14, 0)
    assert out["raw_post_weight_lbs"] == 9.1


def test_normal_wf_regression_helper_does_not_trigger():
    info = _weight_info(pre=22.0, post=20.1, revenue_valid=True)
    assert (
        is_settled_bulk_only(
            final_portal_wf=20.1,
            lines=[],
            resolution=None,
            weight_info=info,
        )
        is False
    )
    # Productivity still credits PRE for normal completed WF
    row = {
        "service_type": "WF",
        "effective_status": "completed",
        "pre_weight_lbs": 22.0,
        "post_weight_lbs": 20.1,
        "settled_bulk_only": False,
        "canonical_completion_employee": "Amna (Veewash)",
    }
    proj = project_productivity_fields_for_day_bag(row)
    assert proj["productivity_weight_lbs"] == 22.0
    assert proj["productivity_credit_eligible"] == 1
    assert _weight_lbs(row) == 22.0


def test_final_portal_wf_prefers_wf_lbs_then_zero_weight_num():
    obs = [
        {"wf_lbs_num": 9.1, "weight_num": 9.1},
        {"wf_lbs_num": None, "weight_num": 0.0},
    ]
    assert final_portal_wf_lbs_from_observations(obs) == 0.0


def test_row_flag_and_exclusion_reason_are_durable_gates():
    assert row_is_settled_bulk_only_for_productivity({"settled_bulk_only": True})
    assert row_is_settled_bulk_only_for_productivity(
        {"productivity_exclusion_reason": PROD_EXCLUSION_SETTLED_BULK_ONLY}
    )
    base = {
        "productivity_weight_lbs": 9.1,
        "productivity_credit_eligible": 1,
        "productivity_exclusion_reason": None,
    }
    overr = project_productivity_override_for_settled_bulk_only(base)
    assert overr["productivity_weight_lbs"] == 0.0
    assert overr["productivity_credit_eligible"] == 0
