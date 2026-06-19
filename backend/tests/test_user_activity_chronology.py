"""Tests for user activity chronology (merged weighing/sorting/washing/drying)."""

from datetime import datetime

import pytest

from backend.rinse_scan_chronology import (
    VALID_ACTIVITY_TYPE_FILTERS,
    build_user_activity_chronology_payload,
    build_user_activity_summary,
    group_activities_by_employee,
    merge_stage_sessions_to_activities,
)


class TestMergeStageSessionsToActivities:
    def test_merges_and_sorts_chronologically(self):
        activities = merge_stage_sessions_to_activities(
            weighing_sessions=[
                {
                    "start_et": datetime(2026, 6, 18, 7, 5),
                    "end_et": datetime(2026, 6, 18, 7, 6),
                    "duration_seconds": 60,
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "confidence": "exact",
                    "source": "cleaning → weight-entry",
                }
            ],
            sorting_sessions=[
                {
                    "start_et": datetime(2026, 6, 18, 7, 20),
                    "end_et": datetime(2026, 6, 18, 7, 28),
                    "duration_seconds": 480,
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "confidence": "exact",
                    "source": "weight-entry → add-photos",
                }
            ],
            washing_sessions=[
                {
                    "timestamp_et": datetime(2026, 6, 18, 8, 14),
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "washer_rack": "W24-30-VW",
                    "confidence": "exact",
                    "event_purpose": "start-cleaning",
                }
            ],
            drying_sessions=[
                {
                    "timestamp_et": datetime(2026, 6, 18, 9, 42),
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "dryer_rack": "D4-50-VW",
                    "confidence": "exact",
                    "event_purpose": "drying",
                }
            ],
        )
        assert [a["activity_type"] for a in activities] == [
            "weighing",
            "sorting",
            "washing",
            "drying",
        ]
        assert activities[2]["machine_or_rack"] == "W24-30-VW"
        assert activities[3]["machine_or_rack"] == "D4-50-VW"
        assert activities[0]["duration_seconds"] == 60
        assert activities[2]["duration_seconds"] is None

    def test_unknown_employee_bucket(self):
        activities = merge_stage_sessions_to_activities(
            washing_sessions=[
                {
                    "timestamp_et": datetime(2026, 6, 18, 8, 0),
                    "bag_id": "B1",
                    "employee": None,
                    "washer_rack": "W24-30-VW",
                    "confidence": "inferred",
                    "event_purpose": "start-cleaning",
                }
            ],
        )
        assert activities[0]["employee"] == "Unknown"


class TestUserActivitySummaryAndGrouping:
    def test_summary_counts(self):
        activities = merge_stage_sessions_to_activities(
            weighing_sessions=[
                {
                    "start_et": datetime(2026, 6, 18, 7, 0),
                    "end_et": datetime(2026, 6, 18, 7, 1),
                    "duration_seconds": 60,
                    "bag_id": "A",
                    "employee": "Maria",
                    "confidence": "exact",
                    "source": "x",
                }
            ],
            sorting_sessions=[
                {
                    "start_et": datetime(2026, 6, 18, 7, 20),
                    "end_et": datetime(2026, 6, 18, 7, 28),
                    "duration_seconds": 480,
                    "bag_id": "A",
                    "employee": "Alex",
                    "confidence": "exact",
                    "source": "y",
                }
            ],
            washing_sessions=[
                {
                    "timestamp_et": datetime(2026, 6, 18, 8, 0),
                    "bag_id": "B",
                    "employee": "Maria",
                    "washer_rack": "W24-30-VW",
                    "confidence": "exact",
                    "event_purpose": "start-cleaning",
                }
            ],
        )
        summary = build_user_activity_summary(activities)
        assert summary["active_employees"] == 2
        assert summary["total_activities"] == 3
        assert summary["weighing_count"] == 1
        assert summary["sorting_sessions"] == 1
        assert summary["washer_loads"] == 1
        assert summary["dryer_loads"] == 0
        assert summary["first_activity_et"] == datetime(2026, 6, 18, 7, 0)
        assert summary["last_activity_et"] == datetime(2026, 6, 18, 8, 0)

    def test_group_by_employee(self):
        activities = merge_stage_sessions_to_activities(
            weighing_sessions=[
                {
                    "start_et": datetime(2026, 6, 18, 7, 5),
                    "end_et": datetime(2026, 6, 18, 7, 6),
                    "duration_seconds": 60,
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "confidence": "exact",
                    "source": "x",
                }
            ],
            washing_sessions=[
                {
                    "timestamp_et": datetime(2026, 6, 18, 8, 14),
                    "bag_id": "ABC123",
                    "employee": "Maria",
                    "washer_rack": "W24-30-VW",
                    "confidence": "exact",
                    "event_purpose": "start-cleaning",
                }
            ],
        )
        groups = group_activities_by_employee(activities)
        assert len(groups) == 1
        assert groups[0]["employee"] == "Maria"
        assert groups[0]["summary"]["total_activities"] == 2
        assert groups[0]["summary"]["weighing_count"] == 1
        assert groups[0]["summary"]["washer_loads"] == 1


class TestUserActivityPayloadValidation:
    def test_invalid_activity_type_raises(self):
        with pytest.raises(ValueError, match="activity_type must be one of"):
            build_user_activity_chronology_payload(
                None,
                1,
                selected_date_et=datetime(2026, 6, 18).date(),
                activity_type_filter="folding",
            )

    def test_valid_activity_type_filters(self):
        assert VALID_ACTIVITY_TYPE_FILTERS == frozenset(
            {"all", "weighing", "sorting", "washing", "drying"}
        )
