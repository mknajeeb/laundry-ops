"""Regression: specialty drawer inline surface + review completion → Performance."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_rinse_wf_review import (
    CATEGORY_SPECIALTY,
    clear_stale_completed_wf_review_day_bag_codes,
    review_drawer_section_flags,
)
from backend.rinse_step1_productivity_fast import (
    load_completed_productivity_day_bags,
    project_productivity_fields_for_day_bag,
)
from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch


def test_manager_sent_for_review_has_specialty_review_flag_without_bulk():
    flags = review_drawer_section_flags(["MANAGER_SENT_FOR_REVIEW"])
    assert flags["has_specialty_bulk"] is False
    assert flags["has_specialty_review"] is True


def test_clear_stale_completed_review_codes_for_non_member():
    membership = {
        CATEGORY_SPECIALTY: [],
        "disposition": {"203X9YTMPW": None},
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": "203X9YTMPW",
            "review_reason_codes_json": '["SERVICE_CLASSIFICATION_MISMATCH"]',
            "effective_status": "completed",
            "canonical_completion_status": "completed",
        }
    ]
    cursor.rowcount = 1
    n = clear_stale_completed_wf_review_day_bag_codes(
        cursor, 3, date(2026, 8, 25), membership
    )
    assert n == 1
    update_calls = [c for c in cursor.execute.call_args_list if "UPDATE" in str(c[0][0])]
    assert update_calls
    assert "review_reason_codes_json = '[]'" in update_calls[-1][0][0]


def test_manager_completion_projects_productivity_fields():
    proj = project_productivity_fields_for_day_bag(
        {
            "effective_status": "completed",
            "service_type": "WF",
            "canonical_completion_employee": "Yessenia (Veewash)",
            "canonical_completion_timestamp": datetime(2026, 8, 25, 13, 5),
            "pre_weight_lbs": 12.3,
            "post_weight_lbs": 0.0,
        }
    )
    assert proj["productivity_employee_name"] == "Yessenia (Veewash)"
    assert proj["productivity_credit_eligible"] == 1
    assert proj["productivity_completed_at"] == datetime(2026, 8, 25, 13, 5)


@patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"headline": {}})
@patch(
    "backend.rinse_veewash_shift_day.verify_headline_day_bag_status_invariant",
    return_value={"ok": True},
)
@patch("backend.rinse_veewash_shift_day._load_day_bag_status_projection", return_value={})
@patch(
    "backend.rinse_veewash_shift_day._apply_day_bag_statuses_to_headline",
    side_effect=lambda h, _: h,
)
@patch("backend.rinse_veewash_shift_day.load_day_bags_by_ids")
def test_apply_manager_edit_mark_completed_writes_productivity_columns(
    mock_load, *_patches
):
    mock_load.return_value = [
        {
            "bag_id": "SPECX01",
            "service_type": "WF",
            "effective_status": "review_required",
            "review_reason_codes": ["SERVICE_CLASSIFICATION_MISMATCH"],
            "pre_weight_lbs": 12.3,
            "post_weight_lbs": None,
            "bag_snapshot": {},
            "manager_edit_version": 0,
        }
    ]
    cursor = MagicMock()
    cursor.rowcount = 1
    apply_manager_edit_day_bag_patch(
        cursor,
        3,
        date(2026, 8, 25),
        "SPECX01",
        previous_effective_status="review_required",
        previous_reason_codes=["SERVICE_CLASSIFICATION_MISMATCH"],
        outcome_action="mark_completed",
        bulk_cleared=True,
        completion_at=datetime(2026, 8, 25, 13, 5),
        completed_by="Yessenia (Veewash)",
        post_weight_lbs=0.0,
    )
    update_sql = " ".join(str(c[0][0]) for c in cursor.execute.call_args_list if c[0])
    assert "productivity_employee_name" in update_sql
    assert "canonical_completion_employee" in update_sql


def test_load_completed_productivity_day_bags_maps_canonical_employee():
    raw_row = {
        "bag_id": "203X9YTMPW",
        "service_type": "WF",
        "rush_status": "NON-RUSH",
        "effective_status": "completed",
        "pre_weight_lbs": 12.3,
        "post_weight_lbs": 0.0,
        "canonical_completion_status": "completed",
        "canonical_completion_timestamp": datetime(2026, 8, 25, 13, 5),
        "canonical_completion_employee": "Yessenia (Veewash)",
        "productivity_employee_name": "Yessenia (Veewash)",
        "productivity_completed_at": datetime(2026, 8, 25, 13, 5),
        "productivity_credit_eligible": 1,
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [raw_row]
    with patch(
        "backend.rinse_step1_productivity_fast._day_bags_have_productivity_projection",
        return_value=True,
    ), patch(
        "backend.rinse_step1_productivity_fast._credit_eligible_day_bag",
        return_value=True,
    ), patch(
        "backend.rinse_step1_productivity_fast._row_matches_scope",
        return_value=True,
    ):
        bags = load_completed_productivity_day_bags(
            cursor, 3, date(2026, 8, 25), include_hd=False
        )
    assert len(bags) == 1
    assert bags[0]["employee"] == "Yessenia (Veewash)"
    assert bags[0]["completion_timestamp"] == "2026-08-25 13:05:00"
