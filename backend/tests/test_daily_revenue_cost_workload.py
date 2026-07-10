"""Tests for DRC workload adapter."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from backend.daily_revenue_cost_constants import LK_RINSE_WF_POUNDS, SOURCE_WORKLOAD
from backend.daily_revenue_cost_workload import (
    build_workload_wf_daily_pounds,
    fetch_workload_wf_pounds_suggestion,
    resolve_workload_wf_line_for_save,
    should_apply_workload_wf_suggestion,
)


def test_build_workload_wf_daily_pounds_sums_wf_bag_weights():
    section = {
        "employees": [
            {
                "employee": "Alice",
                "bags": [
                    {"bag_id": "WF1", "service_type": "WF", "weight_lbs": 12.5},
                    {"bag_id": "HD1", "service_type": "HD", "weight_lbs": 99.0},
                    {"bag_id": "WF2", "service_type": "WF", "weight_lbs": 7.25},
                ],
            }
        ]
    }
    total, records, counts = build_workload_wf_daily_pounds(section, workload_summary={"wf_completed": 2})
    assert total == 19.75
    assert len(records) == 2
    assert counts["wf_completed_bag_count"] == 2
    assert counts["workload_wf_completed_count"] == 2


def test_fetch_workload_wf_pounds_suggestion_none_when_no_weighted_bags():
    with patch(
        "backend.rinse_at_vendor_module.build_at_vendor_module",
        return_value={"employee_completed_bags_today": {"employees": []}, "wf_completed": 0},
    ), patch("backend.rinse_shift_monitor_baseline.build_baseline_context", return_value={}), patch(
        "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline", return_value={}
    ):
        out = fetch_workload_wf_pounds_suggestion(object(), 1, date(2026, 7, 9))
    assert out is None


def test_fetch_workload_wf_pounds_suggestion_includes_metadata():
    av_payload = {
        "employee_completed_bags_today": {
            "employees": [
                {
                    "employee": "Alice",
                    "bags": [{"bag_id": "WF10", "service_type": "WF", "weight_lbs": 18.0}],
                }
            ]
        },
        "wf_completed": 1,
        "completed": 1,
    }
    with patch("backend.rinse_at_vendor_module.build_at_vendor_module", return_value=av_payload), patch(
        "backend.rinse_shift_monitor_baseline.build_baseline_context", return_value={}
    ), patch("backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline", return_value={}):
        out = fetch_workload_wf_pounds_suggestion(object(), 3, date(2026, 7, 9))
    assert out is not None
    assert out["line_key"] == LK_RINSE_WF_POUNDS
    assert out["source_system"] == SOURCE_WORKLOAD
    assert out["quantity"] == 18.0
    assert "workload-day:2026-07-09:org=3" in out["source_ref"]
    assert out["source_payload"]["total_pounds"] == 18.0
    assert out["source_payload"]["wf_completed_bag_count"] == 1


def test_should_not_apply_when_manual_override():
    line = {"source_system": SOURCE_WORKLOAD, "is_manual_override": 1, "quantity": 500}
    assert should_apply_workload_wf_suggestion(line) is False


def test_resolve_workload_preserves_override():
    existing = {
        "source_system": SOURCE_WORKLOAD,
        "is_manual_override": 1,
        "quantity": 500,
        "source_ref": "workload-day:2026-07-09:org=3",
    }
    out = resolve_workload_wf_line_for_save(
        payload_quantity=600,
        overrides={LK_RINSE_WF_POUNDS: {"is_manual_override": True, "reason": "Portal correction"}},
        existing_line=existing,
        suggestion={"quantity": 120, "source_system": SOURCE_WORKLOAD},
    )
    assert out["quantity"] == 600
    assert out["is_override"] is True
    assert out["override_reason"] == "Portal correction"


def test_resolve_workload_applies_suggestion_on_first_save():
    suggestion = {
        "quantity": 1250.5,
        "source_system": SOURCE_WORKLOAD,
        "source_ref": "workload-day:2026-07-09:org=3",
        "source_captured_at": "2026-07-09 12:00:00",
        "source_payload": {"total_pounds": 1250.5},
    }
    out = resolve_workload_wf_line_for_save(
        payload_quantity=1250.5,
        overrides={},
        existing_line=None,
        suggestion=suggestion,
    )
    assert out["quantity"] == 1250.5
    assert out["source_system"] == SOURCE_WORKLOAD
    assert out["source_ref"] == "workload-day:2026-07-09:org=3"
    assert out["is_override"] is False
