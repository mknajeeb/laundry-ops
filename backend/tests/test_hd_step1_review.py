"""HD Step-1 manager review: status, validation, totals, next-day exclusion."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.daily_operations_hd import STATUS_COMPLETE, STATUS_NOT_RECORDED, STATUS_PARTIALLY_RECORDED
from backend.rinse_hd_step1_review import (
    STEP1_COMPLETED,
    STEP1_REVIEW_REQUIRED,
    apply_hd_review_status_to_summary,
    assert_hd_completed_implies_authoritative_fields,
    build_hd_dashboard_totals,
    exclude_prior_completed_hd_from_summary,
    hd_completed_authoritative_field_violations,
    is_authoritative_hd_complete,
    map_production_status_to_step1,
    parse_hd_item_count,
    public_hd_review_fact,
    quantize_hd_revenue,
    save_step1_hd_review,
    undo_step1_hd_review,
    validate_step1_hd_completion_fields,
)
from backend.tests.test_hd_no_carryover_and_specialty_metrics import _seg


def test_new_hd_order_enters_review_required():
    assert map_production_status_to_step1(None) == STEP1_REVIEW_REQUIRED
    assert map_production_status_to_step1(STATUS_NOT_RECORDED) == STEP1_REVIEW_REQUIRED
    assert map_production_status_to_step1(STATUS_PARTIALLY_RECORDED) == STEP1_REVIEW_REQUIRED
    assert map_production_status_to_step1(STATUS_COMPLETE) == STEP1_COMPLETED


def test_partial_hd_review_remains_review_required():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], [], completed=["WF01"]),
            "hd": _seg(["HDNEW1", "HDPART1"], [], completed=[], pending=["HDNEW1", "HDPART1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDNEW1", "HDPART1"], []),
            "all": _seg(["WF01", "HDNEW1", "HDPART1"], [], completed=["WF01"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01", "HDNEW1", "HDPART1"], [], completed=["WF01"]),
        }
    }
    before_wf = deepcopy(summary["segments"]["wf"])
    prod = {
        "HDPART1": {
            "status": STATUS_PARTIALLY_RECORDED,
            "total_items": 2,
            "revenue": None,
            "washed_by_user_id": 1,
        },
    }
    out = apply_hd_review_status_to_summary(summary, production_by_bag=prod)
    assert out["segments"]["wf"] == before_wf
    hd = out["segments"]["hd"]
    assert set(hd["bag_ids"]["review_required"]) == {"HDNEW1", "HDPART1"}
    assert hd["bag_ids"]["completed"] == []
    assert hd["pending"] == 0


def test_item_count_rules():
    assert parse_hd_item_count("") is None
    assert parse_hd_item_count(None) is None
    assert parse_hd_item_count(0) == 0
    assert parse_hd_item_count("3") == 3
    with pytest.raises(ValueError, match="negative_item_count"):
        parse_hd_item_count(-1)
    with pytest.raises(ValueError, match="invalid_item_count"):
        parse_hd_item_count("1.5")
    with pytest.raises(ValueError, match="invalid_item_count"):
        parse_hd_item_count("abc")


def test_revenue_rules_and_rounding():
    assert quantize_hd_revenue("") is None
    assert quantize_hd_revenue(None) is None
    assert quantize_hd_revenue(0) == Decimal("0.00")
    assert quantize_hd_revenue("1.005") == Decimal("1.01")
    assert quantize_hd_revenue("1.004") == Decimal("1.00")
    with pytest.raises(ValueError, match="negative_total_revenue"):
        quantize_hd_revenue(-0.01)
    with pytest.raises(ValueError, match="invalid_total_revenue"):
        quantize_hd_revenue("not-a-number")


def test_cannot_complete_without_any_required_field():
    assert "item_count_required" in validate_step1_hd_completion_fields(
        {"total_revenue": 1, "washed_by_user_id": 1, "folded_by_user_id": 1}
    )
    assert "total_revenue_required" in validate_step1_hd_completion_fields(
        {"item_count": 1, "washed_by_user_id": 1, "folded_by_user_id": 1}
    )
    assert "washed_by_required" in validate_step1_hd_completion_fields(
        {"item_count": 1, "total_revenue": 1, "folded_by_user_id": 1}
    )
    assert "folded_by_required" in validate_step1_hd_completion_fields(
        {"item_count": 1, "total_revenue": 1, "washed_by_user_id": 1}
    )


def test_zero_item_count_and_zero_revenue_accepted():
    assert (
        validate_step1_hd_completion_fields(
            {
                "item_count": 0,
                "total_revenue": Decimal("0.00"),
                "washed_by_user_id": 3,
                "folded_by_user_id": 4,
            }
        )
        == []
    )


def test_same_employee_allowed_for_washed_and_folded():
    assert (
        validate_step1_hd_completion_fields(
            {
                "item_count": 2,
                "total_revenue": 9.5,
                "washed_by_user_id": 42,
                "folded_by_user_id": 42,
            }
        )
        == []
    )


def test_completed_contributes_items_and_revenue_partial_does_not():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.compute_hd_day_revenue_totals",
        return_value={
            "complete_total_items": 5,
            "complete_hd_revenue": 42.5,
            "total_hd_revenue": 42.5,
        },
    ):
        totals = build_hd_dashboard_totals(
            cursor,
            3,
            date(2026, 7, 24),
            hd_segment=_seg(["H1", "H2"], [], completed=["H1"], review=["H2"]),
        )
    assert totals["total_items"] == 5
    assert totals["hd_revenue"] == 42.5
    assert totals["total_revenue"] == 42.5
    assert totals["completed"] == 1
    assert totals["review_required"] == 1
    partial = public_hd_review_fact(
        {"status": STATUS_PARTIALLY_RECORDED, "total_items": 9, "revenue": 99}
    )
    assert partial["included_in_authoritative_totals"] is False
    assert partial["review_status"] == STEP1_REVIEW_REQUIRED
    complete = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 2,
            "revenue": 5,
            "washed_by_user_id": 1,
            "folded_by_user_id": 2,
        }
    )
    assert complete["included_in_authoritative_totals"] is True
    assert complete["review_status"] == STEP1_COMPLETED
    assert_hd_completed_implies_authoritative_fields(complete)

def test_prior_completed_excluded_from_next_day_new_instance_kept():
    summary = {
        "segments": {
            "hd": _seg(["HDKEEP1", "HDDONE1"], [], pending=["HDKEEP1", "HDDONE1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDKEEP1", "HDDONE1"], []),
            "all": _seg(["HDKEEP1", "HDDONE1", "WF01"], []),
            "wf": _seg(["WF01"], []),
            "rush": _seg([], []),
            "non_rush": _seg(["HDKEEP1", "HDDONE1", "WF01"], []),
        }
    }
    out = exclude_prior_completed_hd_from_summary(summary, {"HDDONE1"})
    assert "HDDONE1" not in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert "HDKEEP1" in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert "WF01" in out["segments"]["wf"]["bag_ids"]["new_today"]


def test_prior_day_history_untouched_by_next_day_exclusion():
    prior_day = {
        "segments": {
            "hd": _seg(["HDDONE1"], [], completed=["HDDONE1"]),
            "wf": _seg(["WF01"], [], completed=["WF01"]),
        }
    }
    next_day = {
        "segments": {
            "hd": _seg(["HDDONE1", "HDNEW2"], [], pending=["HDDONE1", "HDNEW2"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDDONE1", "HDNEW2"], []),
            "all": _seg(["HDDONE1", "HDNEW2", "WF02"], []),
            "wf": _seg(["WF02"], []),
            "rush": _seg([], []),
            "non_rush": _seg(["HDDONE1", "HDNEW2", "WF02"], []),
        }
    }
    prior_before = deepcopy(prior_day)
    next_out = exclude_prior_completed_hd_from_summary(next_day, {"HDDONE1"})
    assert prior_day == prior_before
    assert "HDDONE1" in prior_day["segments"]["hd"]["bag_ids"]["completed"]
    assert "HDDONE1" not in next_out["segments"]["hd"]["bag_ids"]["new_today"]
    assert "HDNEW2" in next_out["segments"]["hd"]["bag_ids"]["new_today"]


def test_save_rejects_free_text_and_negative_revenue():
    cursor = MagicMock()
    out = save_step1_hd_review(
        cursor,
        3,
        date(2026, 7, 24),
        "HDORDER1",
        {
            "version": 0,
            "washed_by_override_name": "Free Text",
            "item_count": 1,
            "total_revenue": 1,
        },
        require_complete=True,
    )
    assert out["ok"] is False
    assert "washed_by_free_text_not_allowed" in out["errors"]

    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=True
    ):
        out2 = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "item_count": 1,
                "total_revenue": -5,
                "washed_by_user_id": 1,
                "folded_by_user_id": 1,
            },
            require_complete=True,
        )
    assert out2["ok"] is False
    assert "negative_total_revenue" in out2["errors"]


def test_cannot_complete_with_missing_item_count():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=True
    ):
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "washed_by_user_id": 1,
                "folded_by_user_id": 1,
                "item_count": None,
                "total_revenue": 10,
            },
            require_complete=True,
        )
    assert out["ok"] is False
    assert "item_count_required" in out["errors"]


def test_save_mark_completed_happy_path():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=True
    ), patch(
        "backend.rinse_hd_step1_review.save_hd_production",
        return_value={
            "ok": True,
            "production": {
                "status": STATUS_COMPLETE,
                "total_items": 0,
                "revenue": 0.0,
                "washed_by_user_id": 11,
                "washed_by_name_snapshot": "Ann",
                "folded_by_user_id": 11,
                "folded_by_name_snapshot": "Ann",
                "version": 1,
            },
        },
    ) as save_mock:
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "item_count": 0,
                "total_revenue": 0,
                "washed_by_user_id": 11,
                "folded_by_user_id": 11,
                "reason": "complete",
            },
            require_complete=True,
        )
    assert out["ok"] is True
    assert out["review_status"] == STEP1_COMPLETED
    assert out["step1_outcome"] == "completed"
    payload = save_mock.call_args[0][4]
    assert payload["total_items"] == 0
    assert payload["revenue"] == 0.0
    assert payload["washed_by_user_id"] == 11
    assert payload["folded_by_user_id"] == 11
    assert payload["defer_complete"] is False


def test_save_review_defers_complete_until_mark_completed():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=True
    ), patch(
        "backend.rinse_hd_step1_review.save_hd_production",
        return_value={
            "ok": True,
            "production": {
                "status": STATUS_PARTIALLY_RECORDED,
                "total_items": 2,
                "revenue": 9.5,
                "washed_by_user_id": 11,
                "washed_by_name_snapshot": "Ann",
                "folded_by_user_id": 12,
                "folded_by_name_snapshot": "Bob",
                "version": 1,
            },
        },
    ) as save_mock:
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "item_count": 2,
                "total_revenue": 9.5,
                "washed_by_user_id": 11,
                "folded_by_user_id": 12,
            },
            require_complete=False,
        )
    assert out["ok"] is True
    assert out["review_status"] == STEP1_REVIEW_REQUIRED
    assert save_mock.call_args[0][4]["defer_complete"] is True


def test_washed_and_folded_selection_passed_to_save():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=True
    ), patch(
        "backend.rinse_hd_step1_review.save_hd_production",
        return_value={
            "ok": True,
            "production": {
                "status": STATUS_PARTIALLY_RECORDED,
                "total_items": 1,
                "revenue": 2.0,
                "washed_by_user_id": 7,
                "washed_by_name_snapshot": "Wash Emp",
                "folded_by_user_id": 8,
                "folded_by_name_snapshot": "Fold Emp",
                "version": 1,
            },
        },
    ) as save_mock:
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "item_count": 1,
                "total_revenue": 2,
                "washed_by_user_id": 7,
                "folded_by_user_id": 8,
            },
            require_complete=False,
        )
    assert out["ok"] is True
    payload = save_mock.call_args[0][4]
    assert payload["washed_by_user_id"] == 7
    assert payload["folded_by_user_id"] == 8
    assert out["review"]["washed_by_name_snapshot"] == "Wash Emp"
    assert out["review"]["folded_by_name_snapshot"] == "Fold Emp"


def test_completed_review_stores_employee_snapshots():
    fact = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 4,
            "revenue": 12.5,
            "washed_by_user_id": 7,
            "washed_by_name_snapshot": "Washed Name",
            "folded_by_user_id": 8,
            "folded_by_name_snapshot": "Folded Name",
            "version": 3,
        }
    )
    assert fact["washed_by_name_snapshot"] == "Washed Name"
    assert fact["folded_by_name_snapshot"] == "Folded Name"
    assert fact["included_in_authoritative_totals"] is True
    assert fact["review_status"] == STEP1_COMPLETED


def test_inactive_or_cross_org_employee_rejected_for_new_selection():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=None
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=False
    ):
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 0,
                "item_count": 1,
                "total_revenue": 1,
                "washed_by_user_id": 99,
                "folded_by_user_id": 99,
            },
            require_complete=True,
        )
    assert out["ok"] is False
    assert "washed_by_inactive_or_cross_org" in out["errors"]


def test_inactive_employee_may_be_retained_on_existing_record():
    cursor = MagicMock()
    existing = {
        "status": STATUS_COMPLETE,
        "total_items": 1,
        "revenue": 1.0,
        "washed_by_user_id": 99,
        "folded_by_user_id": 99,
        "version": 1,
    }
    with patch(
        "backend.rinse_hd_step1_review.get_hd_production_row", return_value=existing
    ), patch(
        "backend.rinse_hd_step1_review._employee_is_active_org_member", return_value=False
    ), patch(
        "backend.rinse_hd_step1_review.save_hd_production",
        return_value={
            "ok": True,
            "production": {
                **existing,
                "version": 2,
                "washed_by_name_snapshot": "Old",
                "folded_by_name_snapshot": "Old",
            },
        },
    ):
        out = save_step1_hd_review(
            cursor,
            3,
            date(2026, 7, 24),
            "HDORDER1",
            {
                "version": 1,
                "item_count": 1,
                "total_revenue": 1,
                "washed_by_user_id": 99,
                "folded_by_user_id": 99,
            },
            require_complete=True,
        )
    assert out["ok"] is True


def test_undo_restores_prior_fields():
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.undo_hd_production",
        return_value={
            "ok": True,
            "production": {
                "status": STATUS_PARTIALLY_RECORDED,
                "total_items": 1,
                "revenue": 3.0,
                "washed_by_user_id": 1,
                "washed_by_name_snapshot": "Old Wash",
                "folded_by_user_id": 2,
                "folded_by_name_snapshot": "Old Fold",
                "version": 2,
            },
        },
    ):
        out = undo_step1_hd_review(cursor, 3, date(2026, 7, 24), "HDORDER1")
    assert out["ok"] is True
    assert out["review_status"] == STEP1_REVIEW_REQUIRED
    assert out["review"]["washed_by_name_snapshot"] == "Old Wash"
    assert out["review"]["folded_by_name_snapshot"] == "Old Fold"
    assert out["review"]["item_count"] == 1
    assert out["review"]["total_revenue"] == 3.0


def _valid_completed_hd_record(**overrides):
    base = {
        "status": STATUS_COMPLETE,
        "item_count": 3,
        "total_items": 3,
        "total_revenue": 12.5,
        "revenue": 12.5,
        "washed_by_user_id": 11,
        "folded_by_user_id": 12,
    }
    base.update(overrides)
    return base


def test_hd_completed_missing_item_count_fails_invariant():
    record = _valid_completed_hd_record(item_count=None, total_items=None)
    missing = hd_completed_authoritative_field_violations(record)
    assert "item_count" in missing
    with pytest.raises(AssertionError):
        assert_hd_completed_implies_authoritative_fields(record)
    public = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": None,
            "revenue": 12.5,
            "washed_by_user_id": 11,
            "folded_by_user_id": 12,
        }
    )
    assert public["review_status"] == STEP1_REVIEW_REQUIRED
    assert public["production_status"] == STATUS_PARTIALLY_RECORDED
    assert public["included_in_authoritative_totals"] is False


def test_hd_completed_missing_revenue_fails_invariant():
    record = _valid_completed_hd_record(total_revenue=None, revenue=None)
    missing = hd_completed_authoritative_field_violations(record)
    assert "total_revenue" in missing
    with pytest.raises(AssertionError):
        assert_hd_completed_implies_authoritative_fields(record)
    public = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 3,
            "revenue": None,
            "washed_by_user_id": 11,
            "folded_by_user_id": 12,
        }
    )
    assert public["review_status"] == STEP1_REVIEW_REQUIRED
    assert public["included_in_authoritative_totals"] is False


def test_hd_completed_missing_washed_by_fails_invariant():
    record = _valid_completed_hd_record(washed_by_user_id=None)
    missing = hd_completed_authoritative_field_violations(record)
    assert "washed_by_user_id" in missing
    with pytest.raises(AssertionError):
        assert_hd_completed_implies_authoritative_fields(record)
    public = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 3,
            "revenue": 12.5,
            "washed_by_user_id": None,
            "folded_by_user_id": 12,
        }
    )
    assert public["review_status"] == STEP1_REVIEW_REQUIRED


def test_hd_completed_missing_folded_by_fails_invariant():
    record = _valid_completed_hd_record(folded_by_user_id=None)
    missing = hd_completed_authoritative_field_violations(record)
    assert "folded_by_user_id" in missing
    with pytest.raises(AssertionError):
        assert_hd_completed_implies_authoritative_fields(record)
    public = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 3,
            "revenue": 12.5,
            "washed_by_user_id": 11,
            "folded_by_user_id": None,
        }
    )
    assert public["review_status"] == STEP1_REVIEW_REQUIRED


def test_hd_valid_completed_record_passes_invariant():
    record = _valid_completed_hd_record()
    assert hd_completed_authoritative_field_violations(record) == []
    assert_hd_completed_implies_authoritative_fields(record)
    assert is_authoritative_hd_complete(record) is True
    public = public_hd_review_fact(
        {
            "status": STATUS_COMPLETE,
            "total_items": 3,
            "revenue": 12.5,
            "washed_by_user_id": 11,
            "folded_by_user_id": 12,
        }
    )
    assert public["review_status"] == STEP1_COMPLETED
    assert public["included_in_authoritative_totals"] is True
    assert_hd_completed_implies_authoritative_fields(public)


def test_hd_partition_incomplete_complete_stays_review_required():
    """Status partition: incomplete COMPLETE rows must not enter HD completed."""
    summary = {
        "segments": {
            "hd": _seg(["HDGOOD", "HDBAD"], [], pending=["HDGOOD", "HDBAD"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDGOOD", "HDBAD"], []),
        }
    }
    prod = {
        "HDGOOD": {
            "status": STATUS_COMPLETE,
            "total_items": 2,
            "revenue": 8.0,
            "washed_by_user_id": 1,
            "folded_by_user_id": 2,
        },
        "HDBAD": {
            "status": STATUS_COMPLETE,
            "total_items": 2,
            "revenue": 8.0,
            "washed_by_user_id": 1,
            # folded_by missing
        },
    }
    out = apply_hd_review_status_to_summary(summary, production_by_bag=prod)
    hd = out["segments"]["hd"]
    assert "HDGOOD" in hd["bag_ids"]["completed"]
    assert "HDBAD" in hd["bag_ids"]["review_required"]
    assert "HDBAD" not in hd["bag_ids"]["completed"]
    for bid in hd["bag_ids"]["completed"]:
        assert is_authoritative_hd_complete(prod[bid])
        assert_hd_completed_implies_authoritative_fields(
            public_hd_review_fact(prod[bid])
        )
