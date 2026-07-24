"""WF Employee Performance credits immutable Evidence PRE only."""

from __future__ import annotations

from backend.rinse_step1_productivity_fast import (
    CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE,
    _wf_credited_weight_fields,
    _weight_lbs,
    project_productivity_fields_for_day_bag,
)


def test_wf_credit_uses_pre_not_post():
    row = {
        "service_type": "WF",
        "pre_weight_lbs": 20.0,
        "post_weight_lbs": 18.0,
        "weight_lbs": 18.0,
        "productivity_weight_lbs": 18.0,
    }
    assert _weight_lbs(row) == 20.0
    credit = _wf_credited_weight_fields(row)
    assert credit["credited_weight_lbs"] == 20.0
    assert credit["credited_weight_source"] == CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE
    assert credit["missing_production_credit_weight"] is False


def test_wf_credit_ignores_manager_post_style_weight_lbs():
    row = {
        "service_type": "WF",
        "pre_weight_lbs": 20.0,
        "post_weight_lbs": 17.0,
        "weight_lbs": 17.0,
    }
    assert _weight_lbs(row) == 20.0


def test_wf_missing_pre_excludes_pounds_even_with_post():
    row = {
        "service_type": "WF",
        "pre_weight_lbs": None,
        "post_weight_lbs": 18.0,
        "weight_lbs": 18.0,
        "productivity_weight_lbs": 18.0,
    }
    assert _weight_lbs(row) is None
    credit = _wf_credited_weight_fields(row)
    assert credit["credited_weight_lbs"] is None
    assert credit["credited_weight_source"] is None
    assert credit["missing_production_credit_weight"] is True


def test_wf_missing_pre_ignores_canonical_style_fallback_in_weight_lbs():
    row = {
        "service_type": "WF",
        "pre_weight_lbs": None,
        "weight_lbs": 18.0,
        "post_weight_lbs": None,
    }
    credit = _wf_credited_weight_fields(row)
    assert credit["missing_production_credit_weight"] is True
    assert credit["credited_weight_lbs"] is None


def test_project_wf_uses_pre_only():
    out = project_productivity_fields_for_day_bag(
        {
            "service_type": "WF",
            "effective_status": "completed",
            "canonical_completion_employee": "Maria",
            "canonical_completion_timestamp": "2026-07-24 10:00:00",
            "pre_weight_lbs": 20.0,
            "post_weight_lbs": 18.0,
            "weight_lbs": 18.0,
        }
    )
    assert out["productivity_weight_lbs"] == 20.0


def test_project_wf_missing_pre_stores_null_not_post():
    out = project_productivity_fields_for_day_bag(
        {
            "service_type": "WF",
            "effective_status": "completed",
            "pre_weight_lbs": None,
            "post_weight_lbs": 18.0,
            "weight_lbs": 18.0,
        }
    )
    assert out["productivity_weight_lbs"] is None


def test_project_hd_unchanged_prefers_weight_then_post():
    out = project_productivity_fields_for_day_bag(
        {
            "service_type": "HD",
            "effective_status": "completed",
            "weight_lbs": 11.2,
            "post_weight_lbs": 9.0,
            "pre_weight_lbs": 8.0,
        }
    )
    assert out["productivity_weight_lbs"] == 11.2
