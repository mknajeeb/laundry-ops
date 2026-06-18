"""Tests for shift operations timeline (read-only analytics)."""

from datetime import date, datetime

from backend.rinse_operations_timeline import (
    ACTIVITY_DRYING,
    ACTIVITY_FOLDING,
    ACTIVITY_OTHER,
    ACTIVITY_SORTING,
    ACTIVITY_WASHING,
    ACTIVITY_WEIGHING,
    build_employee_activity,
    build_operations_timeline_summary,
    build_shift_timeline_rows,
    purpose_to_activity_category,
)


SELECTED = date(2026, 6, 18)


def _ev(bag_id, purpose, at, *, scan_index=1, ev_id=1, user="Alex", rack="Scale"):
    return {
        "id": ev_id,
        "bag_id": bag_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestPurposeCategoryMapping:
    def test_weight_entry_is_weighing(self):
        assert purpose_to_activity_category("weight-entry") == ACTIVITY_WEIGHING

    def test_add_photos_is_sorting(self):
        assert purpose_to_activity_category("add-photos") == ACTIVITY_SORTING

    def test_start_cleaning_is_washing(self):
        assert purpose_to_activity_category("start-cleaning") == ACTIVITY_WASHING

    def test_drying_is_drying(self):
        assert purpose_to_activity_category("drying") == ACTIVITY_DRYING

    def test_clean_rack_is_folding(self):
        assert purpose_to_activity_category("move-bag", rack="Clean Rack A") == ACTIVITY_FOLDING

    def test_unknown_is_other(self):
        assert purpose_to_activity_category("load-in") == ACTIVITY_OTHER


class TestShiftTimeline:
    def test_chronology_order_by_timestamp(self):
        events = [
            _ev("B2", "weight-entry", datetime(2026, 6, 18, 10, 0), ev_id=2, scan_index=2),
            _ev("B1", "add-photos", datetime(2026, 6, 18, 9, 0), ev_id=1, scan_index=1),
        ]
        rows = build_shift_timeline_rows(events)
        assert len(rows) == 2
        assert rows[0]["bag_id"] == "B1"
        assert rows[1]["bag_id"] == "B2"
        assert rows[0]["index"] == 1
        assert rows[1]["index"] == 2

    def test_timeline_includes_category_and_employee(self):
        events = [_ev("B1", "weight-entry", datetime(2026, 6, 18, 9, 0), user="Sam")]
        rows = build_shift_timeline_rows(events)
        assert rows[0]["employee"] == "Sam"
        assert rows[0]["activity_category"] == ACTIVITY_WEIGHING


class TestSummaryKpis:
    def test_empty_state(self):
        summary = build_operations_timeline_summary([], [], [])
        assert summary["total_active_orders"] == 0
        assert summary["total_scans"] == 0
        assert summary["first_activity_et"] is None
        assert summary["total_sorting_seconds"] == 0

    def test_kpi_aggregation(self):
        events = [
            _ev("B1", "weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=1),
            _ev("B1", "add-photos", datetime(2026, 6, 18, 9, 10), ev_id=2, scan_index=2),
            _ev("B2", "drying", datetime(2026, 6, 18, 10, 0), ev_id=3),
        ]
        rows = build_shift_timeline_rows(events)
        employee_rows = build_employee_activity(rows)
        summary = build_operations_timeline_summary(rows, [], employee_rows)
        assert summary["total_scans"] == 3
        assert summary["total_active_orders"] == 2
        assert summary["first_activity_et"] == datetime(2026, 6, 18, 9, 0)
        assert summary["last_activity_et"] == datetime(2026, 6, 18, 10, 0)


class TestEmployeeActivity:
    def test_groups_by_employee(self):
        events = [
            _ev("B1", "weight-entry", datetime(2026, 6, 18, 9, 0), user="Alex", ev_id=1),
            _ev("B2", "drying", datetime(2026, 6, 18, 9, 5), user="Bob", ev_id=2),
        ]
        rows = build_shift_timeline_rows(events)
        activity = build_employee_activity(rows)
        names = {a["employee"] for a in activity}
        assert names == {"Alex", "Bob"}

    def test_idle_gap_between_blocks(self):
        events = [
            _ev("B1", "weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=1),
            _ev("B1", "drying", datetime(2026, 6, 18, 9, 30), ev_id=2, scan_index=2),
        ]
        rows = build_shift_timeline_rows(events)
        activity = build_employee_activity(rows)
        assert len(activity) == 1
        assert len(activity[0]["blocks"]) == 2
        assert activity[0]["idle_gaps"][0]["duration_seconds"] == 1800
