"""Tests for person/shift-level Wash & Fold gaming aggregation."""

from datetime import datetime
from unittest.mock import patch

from backend.rinse_bag_folding import STATUS_CALCULATED, FoldingResult
from backend.rinse_bag_gaming_performance import (
    ACTIVITY_WASH_LOAD,
    ACTIVITY_WEIGHING,
    REVIEW_USER_AMBIGUOUS,
    build_bag_activity_slices,
)
from backend.rinse_shift_gaming_performance import evaluate_person_shift_gaming


def _ev(purpose, at, *, user="Alex", bag_id=None, scan_index=1, ev_id=1, rack="Scale"):
    row = {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }
    if bag_id is not None:
        row["bag_id"] = bag_id
    return row


def _bag(bag_id, events):
    return {"bag_id": bag_id, "events": events}


def _sv(*events):
    return [_ev("sent-to-vendor", datetime(2026, 5, 27, 8, 0), ev_id=1, scan_index=1)] + list(events)


CLOCK_IN = datetime(2026, 5, 27, 8, 0)
CLOCK_OUT = datetime(2026, 5, 27, 12, 0)


class TestBagActivitySlices:
    def test_weighing_assigned_to_weight_entry_user(self):
        events = _sv(
            _ev("cleaning", datetime(2026, 5, 27, 8, 50), user="Alice", ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), user="Alice", ev_id=3, scan_index=3),
        )
        slices = build_bag_activity_slices("B1", events)
        weighing = next(s for s in slices if s.activity == ACTIVITY_WEIGHING)
        assert weighing.assigned_user == "Alice"
        assert weighing.needs_review is False

    def test_wash_load_ambiguous_when_start_and_dry_users_differ(self):
        events = _sv(
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Carl", ev_id=2, scan_index=2),
            _ev("drying", datetime(2026, 5, 27, 9, 45), user="Dana", ev_id=3, scan_index=3),
        )
        wl = next(s for s in build_bag_activity_slices("B1", events) if s.activity == ACTIVITY_WASH_LOAD)
        assert wl.needs_review is True
        assert REVIEW_USER_AMBIGUOUS in wl.review_reasons
        assert wl.assigned_user == "Carl"

    def test_weighing_flags_operator_mismatch_but_assigns_weight_entry_user(self):
        events = _sv(
            _ev("cleaning", datetime(2026, 5, 27, 8, 50), user="Other", ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), user="Alice", ev_id=3, scan_index=3),
        )
        weighing = next(
            s for s in build_bag_activity_slices("B1", events) if s.activity == ACTIVITY_WEIGHING
        )
        assert weighing.assigned_user == "Alice"
        assert weighing.needs_review is True
        assert REVIEW_USER_AMBIGUOUS in weighing.review_reasons

    def test_sorting_flags_operator_mismatch_but_assigns_end_user(self):
        events = _sv(
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), user="Alice", ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), user="Alice", ev_id=3, scan_index=3),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 5), user="Alice", ev_id=4, scan_index=4),
            _ev("add-photos", datetime(2026, 5, 27, 9, 10), user="Bob", ev_id=5, scan_index=5),
        )
        sorting = next(
            s for s in build_bag_activity_slices("B1", events) if s.activity == "sorting"
        )
        assert sorting.assigned_user == "Bob"
        assert sorting.needs_review is True
        assert REVIEW_USER_AMBIGUOUS in sorting.review_reasons

    def test_ambiguous_wash_still_counts_in_shift_metrics(self):
        bags = [
            _bag(
                "B1",
                [
                    _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Carl"),
                    _ev("drying", datetime(2026, 5, 27, 9, 45), user="Dana"),
                ],
            ),
        ]
        out = evaluate_person_shift_gaming(
            user_id=1,
            user_name="Carl",
            shift_id=1,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["wash_load"],
        )
        assert out["activity_metrics"]["wash_load"]["bag_count"] == 1
        assert len(out["needs_review"]) == 1


class TestScenarioAOnePersonAllActivities:
    """One person performs weighing, sorting, and washing for all bags."""

    def test_combined_metrics_single_operator(self):
        bags = [
            _bag(
                "B1",
                _sv(
                    _ev("cleaning", datetime(2026, 5, 27, 8, 30), user="Alex", ev_id=2, scan_index=2),
                    _ev("weight-entry", datetime(2026, 5, 27, 8, 35), user="Alex", ev_id=3, scan_index=3),
                    _ev("add-photos", datetime(2026, 5, 27, 8, 45), user="Alex", ev_id=4, scan_index=4),
                    _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Alex", ev_id=5, scan_index=5),
                    _ev("drying", datetime(2026, 5, 27, 9, 40), user="Alex", ev_id=6, scan_index=6),
                ),
            ),
            _bag(
                "B2",
                _sv(
                    _ev("cleaning", datetime(2026, 5, 27, 9, 50), user="Alex", ev_id=2, scan_index=2),
                    _ev("weight-entry", datetime(2026, 5, 27, 10, 0), user="Alex", ev_id=3, scan_index=3),
                    _ev("add-photos", datetime(2026, 5, 27, 10, 10), user="Alex", ev_id=4, scan_index=4),
                    _ev("start-cleaning", datetime(2026, 5, 27, 10, 20), user="Alex", ev_id=5, scan_index=5),
                    _ev("drying", datetime(2026, 5, 27, 11, 0), user="Alex", ev_id=6, scan_index=6),
                ),
            ),
        ]
        out = evaluate_person_shift_gaming(
            user_id=1,
            user_name="Alex",
            shift_id=100,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["weighing", "sorting", "wash_load"],
        )
        w = out["activity_metrics"]["weighing"]
        s = out["activity_metrics"]["sorting"]
        wl = out["activity_metrics"]["wash_load"]
        assert w["bag_count"] == 2
        assert s["bag_count"] == 2
        assert wl["bag_count"] == 2
        assert w["first_start_time"] == datetime(2026, 5, 27, 8, 30)
        assert w["last_end_time"] == datetime(2026, 5, 27, 10, 0)
        assert wl["first_start_time"] == datetime(2026, 5, 27, 9, 0)
        assert wl["last_end_time"] == datetime(2026, 5, 27, 11, 0)
        assert out["combined_metrics"]["distinct_bag_count"] == 2
        assert out["combined_metrics"]["first_start_time"] == datetime(2026, 5, 27, 8, 30)
        assert out["combined_metrics"]["last_end_time"] == datetime(2026, 5, 27, 11, 0)


class TestScenarioBSplitOperators:
    """Person A weighs, Person B sorts, Person C washes."""

    def test_each_person_gets_own_activity_counts(self):
        bags = [
            _bag(
                "B1",
                _sv(
                    _ev("cleaning", datetime(2026, 5, 27, 8, 30), user="Alice", ev_id=2, scan_index=2),
                    _ev("weight-entry", datetime(2026, 5, 27, 8, 35), user="Alice", ev_id=3, scan_index=3),
                    _ev("add-photos", datetime(2026, 5, 27, 8, 45), user="Bob", ev_id=4, scan_index=4),
                    _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Carol", ev_id=5, scan_index=5),
                    _ev("drying", datetime(2026, 5, 27, 9, 40), user="Carol", ev_id=6, scan_index=6),
                ),
            ),
        ]
        alice = evaluate_person_shift_gaming(
            user_id=1,
            user_name="Alice",
            shift_id=1,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["weighing"],
        )
        bob = evaluate_person_shift_gaming(
            user_id=2,
            user_name="Bob",
            shift_id=2,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["sorting"],
        )
        carol = evaluate_person_shift_gaming(
            user_id=3,
            user_name="Carol",
            shift_id=3,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["wash_load"],
        )
        assert alice["activity_metrics"]["weighing"]["bag_count"] == 1
        assert bob["activity_metrics"]["sorting"]["bag_count"] == 1
        assert carol["activity_metrics"]["wash_load"]["bag_count"] == 1
        assert "sorting" not in alice["activity_metrics"]
        assert "weighing" not in bob["activity_metrics"]


class TestScenarioCMixedOperators:
    """Person A weighs and sorts; Person B washes."""

    def test_partial_activity_selection(self):
        bags = [
            _bag(
                "B1",
                _sv(
                    _ev("cleaning", datetime(2026, 5, 27, 8, 30), user="Alice", ev_id=2, scan_index=2),
                    _ev("weight-entry", datetime(2026, 5, 27, 8, 35), user="Alice", ev_id=3, scan_index=3),
                    _ev("add-photos", datetime(2026, 5, 27, 8, 45), user="Alice", ev_id=4, scan_index=4),
                    _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Bob", ev_id=5, scan_index=5),
                    _ev("drying", datetime(2026, 5, 27, 9, 40), user="Bob", ev_id=6, scan_index=6),
                ),
            ),
        ]
        alice = evaluate_person_shift_gaming(
            user_id=1,
            user_name="Alice",
            shift_id=1,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["weighing", "sorting"],
        )
        bob = evaluate_person_shift_gaming(
            user_id=2,
            user_name="Bob",
            shift_id=2,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["wash_load"],
        )
        assert alice["activity_metrics"]["weighing"]["bag_count"] == 1
        assert alice["activity_metrics"]["sorting"]["bag_count"] == 1
        assert alice["combined_metrics"]["distinct_bag_count"] == 1
        assert bob["activity_metrics"]["wash_load"]["bag_count"] == 1
        assert "weighing" not in bob["activity_metrics"]


class TestWashLoadShiftEnd:
    def test_last_end_uses_start_cleaning_when_no_drying_in_shift(self):
        """Last washing action may be start-cleaning only."""
        bags = [
            _bag(
                "B1",
                _sv(
                    _ev("start-cleaning", datetime(2026, 5, 27, 9, 0), user="Alex", ev_id=2, scan_index=2),
                    _ev("drying", datetime(2026, 5, 27, 9, 30), user="Alex", ev_id=3, scan_index=3),
                ),
            ),
            _bag(
                "B2",
                _sv(
                    _ev("start-cleaning", datetime(2026, 5, 27, 10, 30), user="Alex", ev_id=2, scan_index=2),
                ),
            ),
        ]
        out = evaluate_person_shift_gaming(
            user_id=1,
            user_name="Alex",
            shift_id=1,
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            bags=bags,
            selected_activities=["wash_load"],
        )
        wl = out["activity_metrics"]["wash_load"]
        assert wl["bag_count"] == 1
        assert wl["last_end_time"] == datetime(2026, 5, 27, 10, 30)


class TestFoldingUsesExistingLogic:
    def test_folding_metrics_from_existing_assignment(self):
        bags = [
            {
                "bag_id": "B1",
                "events": [
                    _ev("fold", datetime(2026, 5, 27, 10, 0), user="Alex", rack="FOLDING"),
                    _ev("clean", datetime(2026, 5, 27, 10, 20), user="Alex", rack="CLEAN"),
                ],
            },
        ]
        mock_fold = FoldingResult(
            status=STATUS_CALCULATED,
            exception_code=None,
            folding_start_at=datetime(2026, 5, 27, 10, 0),
            folding_end_at=datetime(2026, 5, 27, 10, 20),
            duration_seconds=1200,
            folding_start_event_id=1,
            folding_end_event_id=2,
            folding_start_rack="FOLDING",
            folding_end_rack="CLEAN",
            assigned_user_name="Alex",
            assigned_user_name_source="FOLDING_SCAN",
            folding_scan_count=1,
            clean_scan_count=1,
            work_date=datetime(2026, 5, 27).date(),
        )
        with patch(
            "backend.rinse_bag_gaming_performance.evaluate_folding_performance_for_bag",
            return_value=mock_fold,
        ):
            out = evaluate_person_shift_gaming(
                user_id=1,
                user_name="Alex",
                shift_id=1,
                clock_in=CLOCK_IN,
                clock_out=CLOCK_OUT,
                bags=bags,
                selected_activities=["folding"],
            )
        fold = out["activity_metrics"]["folding"]
        assert fold["bag_count"] == 1
        assert fold["duration_seconds"] == 1200
