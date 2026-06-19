"""Tests for scan chronology coverage audit."""

from datetime import date, datetime

from backend.rinse_scan_chronology import VALID_STAGES, build_scan_chronology_payload
from backend.rinse_scan_coverage_audit import (
    STATUS_EXCEPTION,
    STATUS_FOUND,
    STATUS_INFERRED,
    STATUS_MISSING,
    apply_coverage_exception_rules,
    bag_matches_employee_filter,
    build_coverage_audit_row,
    build_coverage_audit_summary,
    is_fully_covered,
    map_stage_sessions_for_bag,
)

SELECTED = date(2026, 6, 18)


def _weighing_row(*, bag_id="ABC123", confidence="exact", start=None, end=None, employee="Maria"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "start_et": start or datetime(2026, 6, 18, 7, 5),
        "end_et": end or datetime(2026, 6, 18, 7, 6),
        "confidence": confidence,
    }


def _sorting_row(*, bag_id="ABC123", confidence="exact", start=None, end=None, employee="Maria"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "start_et": start or datetime(2026, 6, 18, 7, 20),
        "end_et": end or datetime(2026, 6, 18, 7, 28),
        "confidence": confidence,
    }


def _washing_row(*, bag_id="ABC123", confidence="exact", ts=None, employee="Maria"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "timestamp_et": ts or datetime(2026, 6, 18, 8, 14),
        "confidence": confidence,
    }


def _drying_row(*, bag_id="ABC123", confidence="exact", ts=None, employee="Maria"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "timestamp_et": ts or datetime(2026, 6, 18, 9, 42),
        "confidence": confidence,
    }


class TestStageStatusMapping:
    def test_fully_covered_bag_all_found(self):
        mapped = map_stage_sessions_for_bag(
            "ABC123",
            weighing_sessions=[_weighing_row()],
            sorting_sessions=[_sorting_row()],
            washing_sessions=[_washing_row()],
            drying_sessions=[_drying_row()],
            selected_date_et=SELECTED,
        )
        assert mapped["statuses"] == {
            "weighing": STATUS_FOUND,
            "sorting": STATUS_FOUND,
            "washing": STATUS_FOUND,
            "drying": STATUS_FOUND,
        }

    def test_inferred_weighing_acceptable_for_full_coverage(self):
        mapped = map_stage_sessions_for_bag(
            "ABC123",
            weighing_sessions=[_weighing_row(confidence="inferred")],
            sorting_sessions=[_sorting_row()],
            washing_sessions=[_washing_row()],
            drying_sessions=[_drying_row()],
            selected_date_et=SELECTED,
        )
        assert mapped["statuses"]["weighing"] == STATUS_INFERRED
        assert is_fully_covered(mapped["statuses"])

    def test_missing_stages_when_no_chronology_rows(self):
        mapped = map_stage_sessions_for_bag(
            "ABC123",
            weighing_sessions=[_weighing_row()],
            selected_date_et=SELECTED,
        )
        assert mapped["statuses"]["weighing"] == STATUS_FOUND
        assert mapped["statuses"]["sorting"] == STATUS_MISSING
        assert mapped["statuses"]["washing"] == STATUS_MISSING
        assert mapped["statuses"]["drying"] == STATUS_MISSING


class TestExceptionRules:
    def test_washing_without_sorting_is_exception(self):
        statuses = {
            "weighing": STATUS_FOUND,
            "sorting": STATUS_MISSING,
            "washing": STATUS_FOUND,
            "drying": STATUS_MISSING,
        }
        updated, notes = apply_coverage_exception_rules(statuses)
        assert updated["washing"] == STATUS_EXCEPTION
        assert any("Washing without sorting" in n for n in notes)

    def test_drying_without_washing_is_exception(self):
        statuses = {
            "weighing": STATUS_FOUND,
            "sorting": STATUS_FOUND,
            "washing": STATUS_MISSING,
            "drying": STATUS_FOUND,
        }
        updated, notes = apply_coverage_exception_rules(statuses)
        assert updated["drying"] == STATUS_EXCEPTION
        assert any("Drying without washing" in n for n in notes)

    def test_multiple_missing_stages_note(self):
        statuses = {
            "weighing": STATUS_MISSING,
            "sorting": STATUS_MISSING,
            "washing": STATUS_MISSING,
            "drying": STATUS_FOUND,
        }
        _, notes = apply_coverage_exception_rules(statuses)
        assert any("3 stages missing" in n for n in notes)


class TestCoverageAuditRow:
    def test_build_row_includes_metadata_and_summary_fields(self):
        row = build_coverage_audit_row(
            "ABC123",
            selected_date_et=SELECTED,
            inclusion_sources=["scan_activity"],
            metadata={"name_clean": "Jane Doe", "service_type": "WF", "last_staging_order_id": 42},
            processed_completed_et=datetime(2026, 6, 18, 9, 42),
            weighing_sessions=[_weighing_row()],
            sorting_sessions=[_sorting_row()],
            washing_sessions=[_washing_row()],
            drying_sessions=[_drying_row()],
        )
        assert row["bag_id"] == "ABC123"
        assert row["customer"] == "Jane Doe"
        assert row["service_type"] == "WF"
        assert row["order_id"] == 42
        assert row["fully_covered"] is True
        assert row["has_exception"] is False
        assert row["weighing_status"] == STATUS_FOUND

    def test_summary_counts(self):
        rows = [
            build_coverage_audit_row(
                "A",
                selected_date_et=SELECTED,
                weighing_sessions=[_weighing_row(bag_id="A")],
                sorting_sessions=[_sorting_row(bag_id="A")],
                washing_sessions=[_washing_row(bag_id="A")],
                drying_sessions=[_drying_row(bag_id="A")],
            ),
            build_coverage_audit_row(
                "B",
                selected_date_et=SELECTED,
                washing_sessions=[_washing_row(bag_id="B", employee="Alex")],
            ),
        ]
        summary = build_coverage_audit_summary(rows)
        assert summary["total_processed_bags"] == 2
        assert summary["fully_covered_bags"] == 1
        assert summary["missing_sorting"] >= 1
        assert summary["exception_bags"] >= 1


class TestEmployeeFilter:
    def test_bag_matches_when_employee_in_any_stage(self):
        assert bag_matches_employee_filter(
            bag_id="ABC123",
            employee_filter="Maria",
            washing_sessions=[_washing_row()],
        )
        assert not bag_matches_employee_filter(
            bag_id="ABC123",
            employee_filter="Bob",
            washing_sessions=[_washing_row()],
        )


class TestScanChronologyRouting:
    def test_coverage_audit_in_valid_stages(self):
        assert "coverage_audit" in VALID_STAGES

    def test_invalid_stage_still_raises(self):
        import pytest

        with pytest.raises(ValueError, match="stage must be one of"):
            build_scan_chronology_payload(
                None,
                1,
                selected_date_et=SELECTED,
                stage="folding",
            )
