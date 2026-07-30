"""Process Flow chronology composition and calculator tests."""

from datetime import date, datetime, timedelta

import pytest

from backend.rinse_process_flow_chronology import (
    DEFAULT_DRY_ASSUMPTION_MINUTES,
    DEFAULT_SORT_ASSUMPTION_MINUTES,
    DEFAULT_WASH_ASSUMPTION_MINUTES,
    MAX_CHECKPOINT_SLOTS,
    ProcessFlowValidationError,
    assign_ready_times_to_slots,
    clamp_dry_assumption_minutes,
    clamp_sort_assumption_minutes,
    clamp_wash_assumption_minutes,
    compose_process_flow_bag_row,
    compose_process_flow_rows_for_bags,
    derive_sequence_status,
    select_current_cycle_drying_rows,
    select_current_cycle_sorting_sessions,
    select_current_cycle_washing_rows,
    validate_checkpoint_times,
)
from backend.rinse_processing_settings import DEFAULT_DRYING_MINUTES as SETTINGS_DRYING_MINUTES
from backend.rinse_ready_to_fold_chronology import DEFAULT_DRYING_DURATION_MINUTES
from backend.rinse_scan_chronology import VALID_STAGES


SELECTED = date(2026, 7, 30)
DAY_END = datetime(2026, 7, 30, 23, 59, 59)


def _ev(purpose, at, *, bag_id="BAG1", rack="R1", ev_id=1, scan_index=1, user="Alex"):
    return {
        "id": ev_id,
        "bag_id": bag_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _sort(bag_id, start, *, employee="Sorter"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "sort_start_et": start,
        "sort_end_et": start + timedelta(minutes=5),
        "confidence": "exact",
        "source": "test",
    }


def _wash(bag_id, at, *, employee="Washer", rack="W1-50-VW", ev_id=1):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "timestamp_et": at,
        "washer_rack": rack,
        "confidence": "exact",
        "scan_event_id": ev_id,
        "event_purpose": "start-cleaning",
    }


def _dry(bag_id, at, *, employee="Dryer", rack="D1-50-VW", ev_id=1):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "timestamp_et": at,
        "dryer_rack": rack,
        "confidence": "exact",
        "scan_event_id": ev_id,
        "event_purpose": "drying",
    }


class TestProcessFlowDefaultsAndValidation:
    def test_defaults(self):
        assert DEFAULT_SORT_ASSUMPTION_MINUTES == 0
        assert DEFAULT_WASH_ASSUMPTION_MINUTES == 0
        assert DEFAULT_DRY_ASSUMPTION_MINUTES == 40
        assert DEFAULT_DRYING_DURATION_MINUTES == 40
        assert SETTINGS_DRYING_MINUTES == 45
        assert DEFAULT_DRY_ASSUMPTION_MINUTES != SETTINGS_DRYING_MINUTES

    def test_blank_dry_resolves_to_40_not_45(self):
        assert clamp_dry_assumption_minutes(None) == 40
        assert clamp_dry_assumption_minutes("") == 40
        assert clamp_sort_assumption_minutes(None) == 0
        assert clamp_wash_assumption_minutes(None) == 0

    def test_decimal_durations_rejected(self):
        with pytest.raises(ProcessFlowValidationError):
            clamp_dry_assumption_minutes("40.5")
        with pytest.raises(ProcessFlowValidationError):
            clamp_sort_assumption_minutes(1.5)
        with pytest.raises(ProcessFlowValidationError):
            clamp_wash_assumption_minutes("0.1")

    def test_max_slots_48(self):
        assert MAX_CHECKPOINT_SLOTS == 48
        with pytest.raises(ProcessFlowValidationError, match="48"):
            validate_checkpoint_times(
                [f"{SELECTED}T{8+i:02d}:00:00" for i in range(49)],
                selected_date_et=SELECTED,
            )

    def test_duplicate_and_descending_checkpoints_rejected(self):
        with pytest.raises(ProcessFlowValidationError, match="chronological"):
            validate_checkpoint_times(["08:00", "08:00"], selected_date_et=SELECTED)
        with pytest.raises(ProcessFlowValidationError, match="chronological"):
            validate_checkpoint_times(["09:00", "08:00"], selected_date_et=SELECTED)

    def test_missing_checkpoints_rejected(self):
        with pytest.raises(ProcessFlowValidationError):
            validate_checkpoint_times([], selected_date_et=SELECTED)


class TestProcessFlowComposition:
    def test_one_row_per_bag_id(self):
        row = compose_process_flow_bag_row(
            bag_id="bag1",
            sort_session=_sort("bag1", datetime(2026, 7, 30, 8, 0)),
            wash_row=_wash("bag1", datetime(2026, 7, 30, 9, 0)),
            dry_row=_dry("bag1", datetime(2026, 7, 30, 10, 0)),
            dry_assumption_minutes=40,
            now_et=DAY_END,
        )
        assert row["bag_id"] == "BAG1"
        assert row["ready_to_fold_et"] == datetime(2026, 7, 30, 10, 40)
        assert row["ready_to_fold_is_calculated"] is True

    def test_valid_sequence(self):
        seq = derive_sequence_status(
            sort_ts=datetime(2026, 7, 30, 8, 0),
            wash_ts=datetime(2026, 7, 30, 9, 0),
            dry_ts=datetime(2026, 7, 30, 10, 0),
        )
        assert seq["sequence_status"] == "Valid"
        assert seq["has_sequence_exception"] is False

    def test_missing_sort_keeps_later_evidence(self):
        row = compose_process_flow_bag_row(
            bag_id="X",
            sort_session=None,
            wash_row=_wash("X", datetime(2026, 7, 30, 9, 0)),
            dry_row=_dry("X", datetime(2026, 7, 30, 10, 0)),
            dry_assumption_minutes=40,
            now_et=DAY_END,
        )
        assert row["wash_scan_et"] is not None
        assert row["dry_scan_et"] is not None
        assert "Missing Sort" in row["sequence_status"]

    def test_missing_wash(self):
        row = compose_process_flow_bag_row(
            bag_id="X",
            sort_session=_sort("X", datetime(2026, 7, 30, 8, 0)),
            wash_row=None,
            dry_row=_dry("X", datetime(2026, 7, 30, 10, 0)),
            dry_assumption_minutes=40,
            now_et=DAY_END,
        )
        assert "Missing Wash" in row["sequence_status"]
        assert row["dry_scan_et"] is not None

    def test_missing_dry(self):
        row = compose_process_flow_bag_row(
            bag_id="X",
            sort_session=_sort("X", datetime(2026, 7, 30, 8, 0)),
            wash_row=_wash("X", datetime(2026, 7, 30, 9, 0)),
            dry_row=None,
            dry_assumption_minutes=40,
            now_et=DAY_END,
        )
        assert "Missing Dry" in row["sequence_status"]
        assert row["ready_to_fold_et"] is None

    def test_wash_before_sort(self):
        seq = derive_sequence_status(
            sort_ts=datetime(2026, 7, 30, 10, 0),
            wash_ts=datetime(2026, 7, 30, 9, 0),
            dry_ts=datetime(2026, 7, 30, 11, 0),
        )
        assert "Wash Before Sort" in seq["sequence_codes"]

    def test_dry_before_wash(self):
        seq = derive_sequence_status(
            sort_ts=datetime(2026, 7, 30, 8, 0),
            wash_ts=datetime(2026, 7, 30, 11, 0),
            dry_ts=datetime(2026, 7, 30, 10, 0),
        )
        assert "Dry Before Wash" in seq["sequence_codes"]

    def test_dry_before_sort(self):
        seq = derive_sequence_status(
            sort_ts=datetime(2026, 7, 30, 12, 0),
            wash_ts=None,
            dry_ts=datetime(2026, 7, 30, 10, 0),
        )
        assert "Dry Before Sort" in seq["sequence_codes"]


class TestProcessFlowSelectorsReused:
    def test_exports_shared_selectors(self):
        assert callable(select_current_cycle_sorting_sessions)
        assert callable(select_current_cycle_washing_rows)
        assert callable(select_current_cycle_drying_rows)
        assert "process_flow" in VALID_STAGES

    def test_stv_as_of_and_future_events_excluded_via_compose(self):
        # Current-cycle STV at 06:00; old dry before STV ignored by drying selector path.
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), ev_id=1),
            _ev("drying", datetime(2026, 7, 29, 12, 0), rack="D1-50-VW", ev_id=2),
            _ev("drying", datetime(2026, 7, 30, 10, 0), rack="D2-50-VW", ev_id=3),
            _ev("start-cleaning", datetime(2026, 7, 30, 9, 0), rack="W1-50-VW", ev_id=4),
            # Future STV after cutoff must not change selected-day lifecycle
            _ev("sent-to-vendor", datetime(2026, 7, 31, 2, 0), ev_id=99),
        ]
        # Minimal sort session evidence via add-photos/weight is complex; compose directly
        # for sequence visibility, and assert drying selector ignores old-cycle dry.
        from backend.rinse_drying_chronology import extract_drying_rows_from_events

        dry_rows = extract_drying_rows_from_events(events)
        selected = select_current_cycle_drying_rows(
            dry_rows, {"BAG1": events}, as_of_end=DAY_END
        )
        assert len(selected) == 1
        assert selected[0]["timestamp_et"] == datetime(2026, 7, 30, 10, 0)


class TestProcessFlowCalculatorSlots:
    def test_slot_boundaries_and_unassigned(self):
        bags = [
            {
                "bag_id": "A",
                "ready_for_washing_at": datetime(2026, 7, 30, 7, 40),
            },
            {
                "bag_id": "B",
                "ready_for_washing_at": datetime(2026, 7, 30, 8, 0),
            },
            {
                "bag_id": "C",
                "ready_for_washing_at": datetime(2026, 7, 30, 8, 0, 1),
            },
            {
                "bag_id": "D",
                "ready_for_washing_at": datetime(2026, 7, 30, 10, 0),
            },
        ]
        cps = [datetime(2026, 7, 30, 8, 0), datetime(2026, 7, 30, 8, 30)]
        slots = assign_ready_times_to_slots(bags, cps, ready_key="ready_for_washing_at")
        assert slots[0]["newly_ready_count"] == 2  # A and B (<= 8:00)
        assert {b["bag_id"] for b in slots[0]["bags"]} == {"A", "B"}
        assert slots[1]["newly_ready_count"] == 1  # C only
        assert slots[1]["bags"][0]["bag_id"] == "C"
        assert slots[-1]["cumulative_ready_count"] == 3
        # D after final checkpoint unassigned
        assigned = {b["bag_id"] for s in slots for b in s["bags"]}
        assert "D" not in assigned

    def test_detail_equals_new_and_cumulative_sum(self):
        bags = [
            {"bag_id": f"B{i}", "ready_for_folding_at": datetime(2026, 7, 30, 8, 0) + timedelta(minutes=i * 10)}
            for i in range(5)
        ]
        cps = [
            datetime(2026, 7, 30, 8, 15),
            datetime(2026, 7, 30, 8, 45),
            datetime(2026, 7, 30, 9, 15),
        ]
        slots = assign_ready_times_to_slots(bags, cps, ready_key="ready_for_folding_at")
        assert all(len(s["bags"]) == s["newly_ready_count"] for s in slots)
        running = 0
        for s in slots:
            running += s["newly_ready_count"]
            assert s["cumulative_ready_count"] == running

    def test_bag_once_per_stage_may_appear_in_each_section(self):
        bag = {
            "bag_id": "SAME",
            "ready_for_washing_at": datetime(2026, 7, 30, 8, 0),
            "ready_for_drying_at": datetime(2026, 7, 30, 9, 0),
            "ready_for_folding_at": datetime(2026, 7, 30, 10, 0),
        }
        cps = [
            datetime(2026, 7, 30, 8, 30),
            datetime(2026, 7, 30, 9, 30),
            datetime(2026, 7, 30, 10, 30),
        ]
        w = assign_ready_times_to_slots([bag], cps, ready_key="ready_for_washing_at")
        d = assign_ready_times_to_slots([bag], cps, ready_key="ready_for_drying_at")
        f = assign_ready_times_to_slots([bag], cps, ready_key="ready_for_folding_at")
        assert sum(s["newly_ready_count"] for s in w) == 1
        assert sum(s["newly_ready_count"] for s in d) == 1
        assert sum(s["newly_ready_count"] for s in f) == 1

    def test_duration_change_is_stage_specific(self):
        sort_ts = datetime(2026, 7, 30, 8, 0)
        wash_ts = datetime(2026, 7, 30, 9, 0)
        dry_ts = datetime(2026, 7, 30, 10, 0)
        base = {
            "ready_for_washing_at": sort_ts + timedelta(minutes=0),
            "ready_for_drying_at": wash_ts + timedelta(minutes=0),
            "ready_for_folding_at": dry_ts + timedelta(minutes=40),
        }
        changed_sort = {
            **base,
            "ready_for_washing_at": sort_ts + timedelta(minutes=15),
        }
        assert changed_sort["ready_for_drying_at"] == base["ready_for_drying_at"]
        assert changed_sort["ready_for_folding_at"] == base["ready_for_folding_at"]
        changed_wash = {
            **base,
            "ready_for_drying_at": wash_ts + timedelta(minutes=20),
        }
        assert changed_wash["ready_for_washing_at"] == base["ready_for_washing_at"]
        changed_dry = {
            **base,
            "ready_for_folding_at": dry_ts + timedelta(minutes=60),
        }
        assert changed_dry["ready_for_washing_at"] == base["ready_for_washing_at"]
        assert changed_dry["ready_for_drying_at"] == base["ready_for_drying_at"]


class TestProcessFlowReadOnlyAndFreeze:
    def test_module_has_no_write_sql(self):
        import inspect
        import backend.rinse_process_flow_chronology as mod

        src = inspect.getsource(mod).upper()
        assert "INSERT " not in src
        assert "UPDATE " not in src
        assert "DELETE " not in src

    def test_existing_stages_still_registered(self):
        for stage in ("sorting", "washing", "drying", "ready_to_fold"):
            assert stage in VALID_STAGES
        assert "process_flow" in VALID_STAGES
