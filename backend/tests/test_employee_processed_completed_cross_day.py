"""Regression: processed vs completed productivity across ET days.

Processed metrics follow employee production-event timestamps.
For WF, completed metrics follow post_processing_weight scan timestamps.
HD completed metrics still follow portal workload completion for the selected day.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
from backend.rinse_employee_completed_bags import build_employee_completed_bags_today
from backend.rinse_employee_productivity_presentation import apply_employee_productivity_scope
from backend.rinse_post_processing_weight_chronology import (
    extract_post_processing_weight_rows_from_events,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start

DAY1 = date(2026, 6, 10)
DAY2 = date(2026, 6, 11)
EMPLOYEE = "Alice Worker"
CLOCK_IN_D1 = datetime(2026, 6, 10, 8, 0)
CLOCK_IN_D2 = datetime(2026, 6, 11, 8, 0)


class _FakeCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []


def _ev(purpose: str, ts: datetime, *, user_name: str = EMPLOYEE, ev_id: int = 1) -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": ev_id,
        "user_name": user_name,
        "bag_id": "PLACEHOLDER",
    }


def _wf_events_for_post_processing(
    bag_id: str,
    *,
    anchor: datetime,
    pre_weight: datetime,
    processing: datetime,
    post_weight: datetime,
) -> list[dict]:
    return [
        {**_ev("sent-to-vendor", anchor, ev_id=1), "bag_id": bag_id},
        {**_ev("weight-entry", pre_weight, ev_id=2), "bag_id": bag_id},
        {**_ev("add-photos", processing, ev_id=3), "bag_id": bag_id},
        {**_ev("complete-cleaning", processing, ev_id=4), "bag_id": bag_id},
        {**_ev("weight-entry", post_weight, ev_id=5), "bag_id": bag_id},
    ]


def _processed_record(
    bag_id: str,
    processed_ts: datetime,
    *,
    employee: str = EMPLOYEE,
    lbs: float = 12.0,
    is_business_completed: bool = False,
) -> dict:
    return {
        "bag_id": bag_id,
        "service_type": "WF",
        "service_bucket": "WF",
        "employee_credited": employee,
        "processed_by_employee": employee,
        "processed_signal": "post_processing_weight",
        "processed_time": processed_ts.isoformat(),
        "processed_timestamp": processed_ts.isoformat(),
        "processed_lbs": lbs,
        "weight_missing": False,
        "is_business_completed": is_business_completed,
    }


def _completed_row(
    bag_id: str,
    *,
    completion_time: datetime,
    post_clean_weight: float = 12.0,
) -> dict:
    return {
        "bag_id": bag_id,
        "customer_name": "Customer",
        "service_type": "WF",
        "service_bucket": "WF",
        "at_vendor_status": "Completed",
        "module_tags": [MOD_AT_VENDOR_COMPLETED],
        "completion_time": completion_time.isoformat(),
        "completion_signal": "post_processing_weight",
        "post_clean_weight": post_clean_weight,
    }


class CrossDayRegressionHarness:
    """Build employee productivity sections with controlled processed + completed inputs."""

    def __init__(self) -> None:
        self.user_maps = {
            EMPLOYEE.casefold(): {"user_id": 42, "display_name": EMPLOYEE},
        }

    def build_section(
        self,
        *,
        selected_date_et: date,
        completed_rows: list[dict],
        events_by_bag: dict[str, list[dict]],
        processed_records: list[dict],
        clock_in: datetime,
    ) -> dict:
        sessions = {42: [{"clock_in_at": clock_in, "clock_out_at": None}]}

        def _shift_window(_c, _o, *, user_id, **kwargs):
            sess = sessions.get(user_id) or []
            if not sess:
                return None, None, "Clock-in missing"
            return sess[0].get("clock_in_at"), sess[0].get("clock_out_at"), None

        with patch("backend.ta_helpers.table_exists", return_value=True), patch(
            "backend.rinse_employee_processed_bags.build_employee_processed_bag_records",
            return_value=[dict(r) for r in processed_records],
        ), patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value=self.user_maps,
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value=sessions,
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            side_effect=_shift_window,
        ), patch(
            "backend.daily_shift_roster.list_roster_entries",
            return_value=[],
        ), patch(
            "backend.daily_shift_roster.build_roster_role_lookup",
            return_value={},
        ), patch(
            "backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk",
            return_value={},
        ), patch(
            "backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk",
            return_value={},
        ):
            raw = build_employee_completed_bags_today(
                _FakeCursor(),
                3,
                completed_rows=completed_rows,
                events_by_bag=events_by_bag,
                selected_date_et=selected_date_et,
                registry_meta_by_bag={},
            )
        return apply_employee_productivity_scope(raw, include_hd=False)

    @staticmethod
    def employee(section: dict, name: str = EMPLOYEE) -> dict:
        match = next((e for e in section.get("employees") or [] if e.get("employee") == name), None)
        if match is None:
            pytest.fail(f"Employee {name!r} not found in section")
        return match


class TestProcessedEventDayFiltering:
    """Guardrail: production events count only on the ET day they occurred."""

    def test_post_processing_weight_on_day1_not_counted_on_day2(self):
        anchor = datetime(2026, 6, 9, 12, 0)
        post_weight = datetime(2026, 6, 10, 11, 0)
        events = _wf_events_for_post_processing(
            "BAG001",
            anchor=anchor,
            pre_weight=datetime(2026, 6, 9, 13, 0),
            processing=datetime(2026, 6, 10, 10, 0),
            post_weight=post_weight,
        )
        day1_rows = extract_post_processing_weight_rows_from_events(
            events,
            day_start=naive_et_day_start(DAY1),
            day_end=naive_et_day_end_inclusive(DAY1),
        )
        day2_rows = extract_post_processing_weight_rows_from_events(
            events,
            day_start=naive_et_day_start(DAY2),
            day_end=naive_et_day_end_inclusive(DAY2),
        )
        assert len(day1_rows) == 1
        assert day1_rows[0]["bag_id"] == "BAG001"
        assert day1_rows[0]["timestamp_et"] == post_weight
        assert day2_rows == []


class TestCrossDayRegressionScenarios:
    harness = CrossDayRegressionHarness()

    def test_scenario1_day1_processed_none_completed(self):
        """Day 1: 10 WF post_processing scans → 10 completed, 0 pending."""
        processed_ts = datetime(2026, 6, 10, 10, 0)
        bag_ids = [f"BAG{i:02d}" for i in range(1, 11)]
        processed_records = [
            _processed_record(bid, processed_ts.replace(hour=10 + i % 5)) for i, bid in enumerate(bag_ids)
        ]
        events_by_bag = {
            bid: _wf_events_for_post_processing(
                bid,
                anchor=datetime(2026, 6, 9, 8, 0),
                pre_weight=datetime(2026, 6, 9, 9, 0),
                processing=datetime(2026, 6, 10, 9, 0),
                post_weight=datetime(2026, 6, 10, 10 + (i % 5)),
            )
            for i, bid in enumerate(bag_ids)
        }

        section = self.harness.build_section(
            selected_date_et=DAY1,
            completed_rows=[],
            events_by_bag=events_by_bag,
            processed_records=processed_records,
            clock_in=CLOCK_IN_D1,
        )
        emp = self.harness.employee(section)

        assert emp["processed_bags_count"] == 10
        assert emp["completed_bags"] == 10
        assert emp["pending_completion_count"] == 0
        assert len(emp["processed_bags"]) == 10
        assert len(emp["bags"]) == 10
        assert section["executive_summary"]["total_bags_processed"] == 10
        assert section["executive_summary"]["total_bags_completed"] == 10
        assert section["executive_summary"]["total_pending_completion"] == 0

    def test_scenario2_day2_completed_no_new_processing(self):
        """Day 2: portal carry-over completions do not re-credit WF post_processing from day 1."""
        bag_ids = [f"BAG{i:02d}" for i in range(1, 11)]
        completion_ts = datetime(2026, 6, 11, 14, 0)
        post_weight_ts = datetime(2026, 6, 10, 11, 0)  # processing happened day 1

        completed_rows = [
            _completed_row(bid, completion_time=completion_ts) for bid in bag_ids
        ]
        events_by_bag = {
            bid: _wf_events_for_post_processing(
                bid,
                anchor=datetime(2026, 6, 9, 8, 0),
                pre_weight=datetime(2026, 6, 9, 9, 0),
                processing=datetime(2026, 6, 10, 9, 0),
                post_weight=post_weight_ts,
            )
            for bid in bag_ids
        }

        section = self.harness.build_section(
            selected_date_et=DAY2,
            completed_rows=completed_rows,
            events_by_bag=events_by_bag,
            processed_records=[],  # no post_processing events on day 2
            clock_in=CLOCK_IN_D2,
        )

        assert section["employees"] == []
        assert section["reconciliation"]["ok"] is True
        assert section["reconciliation"]["employee_completed_bags_credited"] == 0
        assert section["reconciliation"]["portal_workload_completed_today"] == 10
        assert len(section["reconciliation"]["skipped_portal_wf_carryover_bags"]) == 10
        assert section["executive_summary"]["total_bags_processed"] == 0
        assert section["executive_summary"]["total_bags_completed"] == 0

    def test_scenario3_mixed_carry_over_day2(self):
        """Day 2: carry-over portal WF rows skipped; same-day post_processing scans credited."""
        carry_over_ids = [f"BAG{i:02d}" for i in range(1, 6)]
        new_processed_ids = [f"BAG{i:02d}" for i in range(9, 15)]  # 6 bags

        completion_ts = datetime(2026, 6, 11, 15, 0)
        day1_post_weight = datetime(2026, 6, 10, 12, 0)
        day2_post_weight_base = datetime(2026, 6, 11, 9, 0)

        completed_rows = [
            _completed_row(bid, completion_time=completion_ts) for bid in carry_over_ids
        ]
        processed_records = [
            _processed_record(
                bid,
                day2_post_weight_base.replace(minute=i * 5),
                is_business_completed=False,
            )
            for i, bid in enumerate(new_processed_ids)
        ]

        events_by_bag: dict[str, list[dict]] = {}
        for bid in carry_over_ids:
            events_by_bag[bid] = _wf_events_for_post_processing(
                bid,
                anchor=datetime(2026, 6, 9, 8, 0),
                pre_weight=datetime(2026, 6, 9, 9, 0),
                processing=datetime(2026, 6, 10, 9, 0),
                post_weight=day1_post_weight,
            )
        for i, bid in enumerate(new_processed_ids):
            events_by_bag[bid] = _wf_events_for_post_processing(
                bid,
                anchor=datetime(2026, 6, 9, 8, 0),
                pre_weight=datetime(2026, 6, 11, 8, 0),
                processing=datetime(2026, 6, 11, 8, 30),
                post_weight=day2_post_weight_base.replace(minute=i * 5),
            )

        section = self.harness.build_section(
            selected_date_et=DAY2,
            completed_rows=completed_rows,
            events_by_bag=events_by_bag,
            processed_records=processed_records,
            clock_in=CLOCK_IN_D2,
        )
        emp = self.harness.employee(section)

        assert emp["processed_bags_count"] == 6
        assert emp["completed_bags"] == 6
        assert emp["pending_completion_count"] == 0
        assert {b["bag_id"] for b in emp["processed_bags"]} == set(new_processed_ids)
        assert {b["bag_id"] for b in emp["bags"]} == set(new_processed_ids)
        assert emp["pending_completion_bags"] == []
        # Carry-over completions must not inflate processed count on day 2.
        assert not any(bid in {b["bag_id"] for b in emp["processed_bags"]} for bid in carry_over_ids)

    def test_scenario1_day1_eight_processed_matches_mixed_setup(self):
        """Day 1 subset for scenario 3 prelude: 8 WF post_processing scans → 8 completed."""
        bag_ids = [f"BAG{i:02d}" for i in range(1, 9)]
        processed_records = [
            _processed_record(bid, datetime(2026, 6, 10, 10, i)) for i, bid in enumerate(bag_ids)
        ]
        section = self.harness.build_section(
            selected_date_et=DAY1,
            completed_rows=[],
            events_by_bag={},
            processed_records=processed_records,
            clock_in=CLOCK_IN_D1,
        )
        emp = self.harness.employee(section)
        assert emp["processed_bags_count"] == 8
        assert emp["completed_bags"] == 8
        assert emp["pending_completion_count"] == 0

    def test_scan_derived_wf_completion_without_portal_row(self):
        """WF bags with post_processing_weight but missing from portal completed_rows still count."""
        processed_ts = datetime(2026, 6, 26, 10, 16)
        bag_ids = ["9MMFA3BII3", "4YHTQLLIPV", "AGYQRCWFN4"]
        processed_records = [_processed_record(bid, processed_ts) for bid in bag_ids]
        events_by_bag = {
            bid: _wf_events_for_post_processing(
                bid,
                anchor=datetime(2026, 6, 25, 8, 0),
                pre_weight=datetime(2026, 6, 26, 7, 17),
                processing=datetime(2026, 6, 26, 10, 0),
                post_weight=processed_ts,
            )
            for bid in bag_ids
        }
        section = self.harness.build_section(
            selected_date_et=date(2026, 6, 26),
            completed_rows=[],
            events_by_bag=events_by_bag,
            processed_records=processed_records,
            clock_in=datetime(2026, 6, 26, 8, 0),
        )
        emp = self.harness.employee(section)
        assert emp["processed_bags_count"] == 3
        assert emp["completed_bags"] == 3
        assert emp["pending_completion_count"] == 0
        assert {b["bag_id"] for b in emp["bags"]} == set(bag_ids)
        assert section["reconciliation"]["extra_scan_derived_wf_bags"] == sorted(bag_ids)
