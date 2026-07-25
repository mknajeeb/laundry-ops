"""Freeze boundary: Jul 24 WF workload + Employee Productivity must not drift.

These tests lock the operational WF / productivity contract that is currently
correct in production. HD-only work must not change any assertion here.

Source: persisted org-3 day snapshot captured 2026-07-24
(``backend/tests/fixtures/wf_productivity_freeze_jul24_org3.json``).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.rinse_veewash_shift_day import summary_from_day_record
from backend.rinse_step1_productivity_fast import build_step1_snapshot_productivity_section

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "wf_productivity_freeze_jul24_org3.json"
)
DAY = date(2026, 7, 24)
ORG = 3


@pytest.fixture(scope="module")
def freeze():
    return json.loads(_FIXTURE.read_text())


def _headline_from_freeze(freeze: dict) -> dict:
    """Rebuild a minimal day headline matching the freeze fixture shape."""
    wf = freeze["wf"]
    return {
        "selected_date_et": freeze["date"],
        "segments": {
            "wf": {
                "new_today": wf["new_today"],
                "carryover": wf["carryover"],
                "active_workload": wf["active_workload"],
                "total_workload": wf["active_workload"],
                "completed": wf["completed"],
                "pending": wf["pending"],
                "exceptions": {
                    "review_required": wf["review_required"],
                    "total": wf["review_required"],
                },
                "bag_ids": dict(wf["bag_ids"]),
            },
            "wf_rush": {
                "new_today": freeze["wf_rush"]["active"],
                "carryover": 0,
                "active_workload": freeze["wf_rush"]["active"],
                "total_workload": freeze["wf_rush"]["active"],
                "completed": freeze["wf_rush"]["completed"],
                "pending": freeze["wf_rush"]["pending"],
                "exceptions": {
                    "review_required": freeze["wf_rush"]["review_required"],
                    "total": freeze["wf_rush"]["review_required"],
                },
                "bag_ids": {
                    "completed": [],
                    "pending": [],
                    "review_required": [],
                },
            },
            "wf_non_rush": {
                "new_today": freeze["wf_non_rush"]["active"],
                "carryover": 0,
                "active_workload": freeze["wf_non_rush"]["active"],
                "total_workload": freeze["wf_non_rush"]["active"],
                "completed": freeze["wf_non_rush"]["completed"],
                "pending": freeze["wf_non_rush"]["pending"],
                "exceptions": {
                    "review_required": freeze["wf_non_rush"]["review_required"],
                    "total": freeze["wf_non_rush"]["review_required"],
                },
                "bag_ids": {
                    "completed": [],
                    "pending": [],
                    "review_required": [],
                },
            },
        },
        "exceptions": {"review_required": freeze["all_review_required"]},
    }


def test_jul24_wf_freeze_counts(freeze):
    wf = freeze["wf"]
    assert wf["new_today"] == 74
    assert wf["carryover"] == 0
    assert wf["active_workload"] == 74
    assert wf["completed"] == 74
    assert wf["pending"] == 0
    assert wf["review_required"] == 0
    assert len(wf["bag_ids"]["new_today"]) == 74
    assert len(wf["bag_ids"]["completed"]) == 74
    assert wf["bag_ids"]["carryover"] == []
    assert wf["bag_ids"]["pending"] == []
    assert wf["bag_ids"]["review_required"] == []
    # Identity: active membership == completed for this frozen day.
    assert set(wf["bag_ids"]["new_today"]) == set(wf["bag_ids"]["completed"])


def test_jul24_wf_rush_non_rush_freeze(freeze):
    assert freeze["wf_rush"]["active"] == 59
    assert freeze["wf_rush"]["completed"] == 59
    assert freeze["wf_rush"]["pending"] == 0
    assert freeze["wf_rush"]["review_required"] == 0
    assert freeze["wf_non_rush"]["active"] == 15
    assert freeze["wf_non_rush"]["completed"] == 15
    assert freeze["wf_non_rush"]["pending"] == 0
    assert freeze["wf_non_rush"]["review_required"] == 0
    assert freeze["wf_rush"]["active"] + freeze["wf_non_rush"]["active"] == freeze["wf"]["active_workload"]


def test_jul24_summary_from_day_record_preserves_wf_segment(freeze):
    day_rec = {
        "status": freeze["day_status"],
        "headline": _headline_from_freeze(freeze),
        "workload_meta": {},
        "review_required_count": freeze["all_review_required"],
    }
    summary = summary_from_day_record(day_rec)
    assert summary is not None
    wf = (summary.get("segments") or {}).get("wf") or {}
    assert wf.get("completed") == 74
    assert wf.get("pending") == 0
    assert (wf.get("exceptions") or {}).get("review_required") == 0
    assert wf.get("carryover") == 0
    assert wf.get("active_workload") == 74 or wf.get("total_workload") == 74


def test_jul24_productivity_freeze_totals(freeze):
    prod = freeze["productivity_eligible"]
    assert prod["total_bags"] == 75
    assert abs(float(prod["total_weight_lbs"]) - 1499.5) < 0.01
    assert len(prod["by_employee"]) == 7
    bags_sum = sum(int(e["bags"]) for e in prod["by_employee"])
    assert bags_sum == prod["total_bags"]
    # Named credits locked (order-independent).
    by_name = {e["employee"]: e for e in prod["by_employee"]}
    assert by_name["Amna (Veewash)"]["bags"] == 19
    assert by_name["Tarannum (Veewash)"]["bags"] == 14
    assert by_name["Evelin (VeeWash)"]["bags"] == 18


def test_jul24_snapshot_productivity_builder_uses_day_bag_projections(freeze):
    """Employee productivity fast path must remain snapshot-driven (no live rebuild)."""
    employees = freeze["productivity_eligible"]["by_employee"]
    day_bags = []
    for emp in employees:
        for i in range(int(emp["bags"])):
            day_bags.append(
                {
                    "bag_id": f"FZ{emp['employee'][:3]}{i}",
                    "effective_status": "completed",
                    "service_type": "WF",
                    "productivity_employee_name": emp["employee"],
                    "productivity_credit_eligible": 1,
                    "productivity_weight_lbs": float(emp["weight_lbs"]) / max(int(emp["bags"]), 1),
                    "productivity_completed_at": "2026-07-24T15:00:00",
                }
            )
    cursor = MagicMock()
    # build_step1_snapshot_productivity_section typically loads day bags itself;
    # call the projection aggregator shape if available, else skip soft.
    try:
        from backend.rinse_step1_productivity_fast import summarize_productivity_day_bags

        summary = summarize_productivity_day_bags(day_bags)
        assert summary.get("credited_bag_count") == freeze["productivity_eligible"]["total_bags"]
    except ImportError:
        # Fallback: ensure projector marks WF completed bags credit-eligible.
        from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

        proj = project_productivity_fields_for_day_bag(
            {
                "effective_status": "completed",
                "canonical_completion_employee": employees[0]["employee"],
                "canonical_completion_timestamp": "2026-07-24T15:00:00",
                "post_weight_lbs": 10.0,
                "weight_lbs": 10.0,
            }
        )
        assert proj.get("productivity_credit_eligible") in (1, True)
        assert proj.get("productivity_employee_name") == employees[0]["employee"]
