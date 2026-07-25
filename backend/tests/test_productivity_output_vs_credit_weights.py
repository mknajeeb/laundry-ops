"""Overall completed output (POST) vs employee credit (PRE) must stay independent."""

from __future__ import annotations

from backend.rinse_employee_productivity_presentation import (
    _build_executive_summary,
    _recalc_employee_metrics,
)


def _emp_with_bags(bags):
    return _recalc_employee_metrics(
        {
            "employee": "Ada",
            "clock_in_time": "2026-07-24T08:00:00",
            "productive_hours": 8.0,
            "productivity_end_source": "last_completion",
        },
        bags,
    )


def test_pre_post_split_overall_output_vs_employee_credit():
    emp = _emp_with_bags(
        [
            {
                "bag_id": "B1",
                "service_type": "WF",
                "completion_time": "2026-07-24T10:00:00",
                "completed_lbs": 25.0,
                "credited_weight_lbs": 25.0,
                "output_weight_lbs": 24.3,
                "pre_weight_lbs": 25.0,
                "post_weight_lbs": 24.3,
            }
        ]
    )
    assert emp["total_completed_lbs"] == 25.0
    assert emp["total_output_lbs"] == 24.3

    summary = _build_executive_summary([emp])
    assert summary["total_pounds_completed"] == 24.3
    assert summary["total_output_lbs"] == 24.3
    assert summary["total_credited_lbs"] == 25.0
    assert summary["completed_weight_basis"] == "AUTHORITATIVE_POST"
    assert summary["employee_credit_weight_basis"] == "EVIDENCE_PRE"


def test_manager_post_correction_changes_output_not_credit():
    emp = _emp_with_bags(
        [
            {
                "bag_id": "B1",
                "service_type": "WF",
                "completion_time": "2026-07-24T10:00:00",
                "completed_lbs": 25.0,
                "credited_weight_lbs": 25.0,
                "output_weight_lbs": 23.8,
            }
        ]
    )
    summary = _build_executive_summary([emp])
    assert summary["total_pounds_completed"] == 23.8
    assert summary["total_credited_lbs"] == 25.0


def test_canonical_post_fallback_for_output_keeps_pre_credit():
    emp = _emp_with_bags(
        [
            {
                "bag_id": "B1",
                "service_type": "WF",
                "completion_time": "2026-07-24T10:00:00",
                "completed_lbs": 25.0,
                "credited_weight_lbs": 25.0,
                "output_weight_lbs": 24.0,
            }
        ]
    )
    summary = _build_executive_summary([emp])
    assert summary["total_pounds_completed"] == 24.0
    assert summary["total_credited_lbs"] == 25.0


def test_missing_pre_excludes_credit_but_output_may_remain():
    emp = _emp_with_bags(
        [
            {
                "bag_id": "B1",
                "service_type": "WF",
                "completion_time": "2026-07-24T10:00:00",
                "completed_lbs": None,
                "credited_weight_lbs": None,
                "output_weight_lbs": 24.0,
                "missing_production_credit_weight": True,
            }
        ]
    )
    assert emp["total_completed_lbs"] == 0
    assert emp["total_output_lbs"] == 24.0
    summary = _build_executive_summary([emp])
    assert summary["total_pounds_completed"] == 24.0
    assert summary["total_credited_lbs"] == 0


def test_overall_avg_lbs_hour_uses_output_not_credit():
    emp = _emp_with_bags(
        [
            {
                "bag_id": "B1",
                "service_type": "WF",
                "completion_time": "2026-07-24T16:00:00",
                "completed_lbs": 40.0,
                "credited_weight_lbs": 40.0,
                "output_weight_lbs": 32.0,
            }
        ]
    )
    # Force known productive hours on the recalc path.
    emp["productive_hours"] = 8.0
    summary = _build_executive_summary([emp])
    assert summary["total_pounds_completed"] == 32.0
    assert summary["average_completed_pounds_per_hour"] == 4.0
