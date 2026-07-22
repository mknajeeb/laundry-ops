"""Step-1 employee productivity must not rebuild the legacy at-vendor module."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_employee_completed_bags import (
    _STEP1_PROD_CACHE,
    build_employee_productivity_dashboard_payload,
)

D1 = date(2026, 7, 22)


def test_step1_productivity_uses_snapshot_not_at_vendor_module():
    _STEP1_PROD_CACHE.clear()
    cursor = MagicMock()
    summary = {
        "total_operational_orders": 2,
        "segments": {
            "all": {
                "bag_ids": {
                    "new_today": ["BAG1", "BAG2"],
                    "carryover": [],
                    "completed": ["BAG1"],
                    "pending": ["BAG2"],
                    "review_required": [],
                }
            },
            "rush": {"completed": 1},
            "non_rush": {"completed": 0},
        },
    }
    day_bags = [
        {
            "bag_id": "BAG1",
            "service_type": "WF",
            "rush_status": "RUSH",
            "bag_snapshot": {"bag_id": "BAG1", "customer_name": "A"},
        },
        {
            "bag_id": "BAG2",
            "service_type": "WF",
            "rush_status": "RUSH",
            "bag_snapshot": {"bag_id": "BAG2", "customer_name": "B"},
        },
    ]
    emp_payload = {
        "employees": [{"employee": "Maria", "completed_bags": 1}],
        "reconciliation": {"ok": True, "credited_total": 1, "workload_completed_today": 1},
    }
    with (
        patch("backend.rinse_veewash_workload.is_step1_enabled", return_value=True),
        patch("backend.rinse_veewash_workload.get_step1_activation_date", return_value=D1),
        patch(
            "backend.rinse_veewash_shift_day.get_day_headline",
            return_value={"status": "OPEN", "headline": summary},
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=day_bags),
        patch(
            "backend.rinse_simple_shift_performance._load_bag_metadata",
            return_value={},
        ),
        patch(
            "backend.rinse_employee_completed_bags.build_employee_completed_bags_today",
            return_value=emp_payload,
        ) as build_emp,
        patch(
            "backend.rinse_employee_productivity_settings.include_hd_in_employee_productivity",
            return_value=False,
        ),
        patch(
            "backend.rinse_employee_productivity_presentation.apply_employee_productivity_scope",
            side_effect=lambda section, **_k: section,
        ),
        patch("backend.daily_shift_roster.list_roster_entries", return_value=[]),
        patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value={},
        ),
        patch("backend.daily_shift_labor_summary.build_labor_summary", return_value={}),
        patch("backend.rinse_at_vendor_module.build_at_vendor_module") as at_vendor,
    ):
        out = build_employee_productivity_dashboard_payload(
            cursor, 3, selected_date_et=D1, rush_filter="all"
        )
    at_vendor.assert_not_called()
    build_emp.assert_called_once()
    assert out["step1_lightweight_productivity"] is True
    assert out["employee_completed_bags_today"]["employees"]
    assert out["completed_today_kpi"] == 1
