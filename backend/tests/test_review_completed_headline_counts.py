"""Review Required → Completed must update Step-1 headline KPI cards."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

ORG = 3
DAY = date(2026, 7, 28)
BAG = "REVTODONE1"
OTHER = "OTHERBAG99"


def _seg(
    *,
    completed_ids=None,
    pending_ids=None,
    review_ids=None,
    new_today=None,
    carryover=None,
    completed=None,
    pending=None,
    review=None,
    total=None,
):
    completed_ids = list(completed_ids or [])
    pending_ids = list(pending_ids or [])
    review_ids = list(review_ids or [])
    new_today = list(new_today if new_today is not None else completed_ids + pending_ids + review_ids)
    carryover = list(carryover or [])
    if completed is None:
        completed = len(completed_ids)
    if pending is None:
        pending = len(pending_ids)
    if review is None:
        review = len(review_ids)
    if total is None:
        total = len(new_today) + len(carryover)
    return {
        "completed": completed,
        "pending": pending,
        "new_today": len(new_today),
        "carryover": len(carryover),
        "active_workload": total,
        "total_workload": total,
        "exceptions": {
            "review_required": review,
            "disappeared_without_completion": review,
            "total": review,
        },
        "bag_ids": {
            "new_today": new_today,
            "carryover": carryover,
            "completed": completed_ids,
            "pending": pending_ids,
            "review_required": review_ids,
            "disappeared_without_completion": list(review_ids),
        },
    }


def _headline_from_segments(segments):
    all_seg = segments["all"]
    return {
        "segments": segments,
        "completed": all_seg["completed"],
        "pending": all_seg["pending"],
        "total_workload": all_seg["total_workload"],
        "active_workload": all_seg["active_workload"],
        "exceptions": dict(all_seg["exceptions"]),
        "review_reasons_by_bag": {BAG: ["WF_BULK_WORKITEM_REVIEW"]},
        "review_by_reason": {"WF_BULK_WORKITEM_REVIEW": [BAG]},
    }


def test_move_helper_review_only_membership_adds_completed():
    from backend.rinse_veewash_shift_day import _move_bag_in_segment_bucket

    seg = {
        "completed": 5,
        "pending": 2,
        "exceptions": {"review_required": 1, "total": 1},
        "bag_ids": {
            "completed": [],
            "pending": [],
            "review_required": [BAG],
            "new_today": [],
        },
    }
    out = _move_bag_in_segment_bucket(
        seg, BAG, old_bucket="review_required", new_bucket="completed"
    )
    assert BAG in out["bag_ids"]["completed"]
    assert BAG not in out["bag_ids"]["review_required"]
    assert out["completed"] == 1  # recalculated from unique IDs
    assert out["exceptions"]["review_required"] == 0


def test_strip_helper_does_not_require_prior_list_membership():
    from backend.rinse_veewash_shift_day import _strip_bag_from_review_segments

    segments = {
        "wf": {
            "completed": 10,
            "pending": 0,
            "total_workload": 11,
            "active_workload": 11,
            "exceptions": {"review_required": 1, "total": 1},
            "bag_ids": {
                "completed": [],
                "pending": [],
                "review_required": [],
                "new_today": [],
            },
        }
    }
    out = _strip_bag_from_review_segments(segments, BAG, new_bucket="completed")
    assert BAG in out["wf"]["bag_ids"]["completed"]
    assert out["wf"]["completed"] == 1
    assert out["wf"]["exceptions"]["review_required"] == 0


def test_apply_day_bag_statuses_empty_bag_ids_recalculates_from_statuses():
    from backend.rinse_veewash_shift_day import _apply_day_bag_statuses_to_headline

    headline = {
        "segments": {
            "all": {
                "completed": 10,
                "pending": 5,
                "total_workload": 16,
                "active_workload": 16,
                "exceptions": {"review_required": 1, "total": 1},
                "bag_ids": {},
            },
            "wf": {
                "completed": 10,
                "pending": 5,
                "total_workload": 16,
                "active_workload": 16,
                "exceptions": {"review_required": 1, "total": 1},
                "bag_ids": {},
            },
        },
        "completed": 10,
        "pending": 5,
        "total_workload": 16,
        "exceptions": {"review_required": 1},
    }
    status_by_bag = {
        BAG: {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "NON-RUSH",
        },
        OTHER: {
            "effective_status": "pending",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
        "DONE1": {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
    }
    out = _apply_day_bag_statuses_to_headline(headline, status_by_bag)
    wf = out["segments"]["wf"]
    assert set(wf["bag_ids"]["completed"]) == {BAG, "DONE1"}
    assert set(wf["bag_ids"]["pending"]) == {OTHER}
    assert wf["bag_ids"]["review_required"] == []
    assert wf["completed"] == 2
    assert wf["pending"] == 1
    assert wf["exceptions"]["review_required"] == 0
    # No membership lists → total recovered from status partition.
    assert wf["total_workload"] == 3


def _run_mark_completed_patch(*, segments, day_row_status="review_required", status_rows=None):
    from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch

    cursor = MagicMock()
    day_row = {
        "bag_id": BAG,
        "effective_status": day_row_status,
        "service_type": "WF",
        "rush_status": "NON-RUSH",
        "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
        "bag_snapshot": {"bag_id": BAG, "outcome": day_row_status},
        "canonical_completion_status": day_row_status,
    }
    headline = _headline_from_segments(segments)
    day_rec = {
        "headline": headline,
        "workload_meta": {"review_reasons_by_bag": {BAG: ["WF_BULK_WORKITEM_REVIEW"]}},
    }
    if status_rows is None:
        # Projection after UPDATE should show this bag completed + others unchanged.
        status_rows = {}
        for seg in segments.values():
            bags = seg.get("bag_ids") or {}
            for bid in bags.get("completed") or []:
                status_rows[bid] = {
                    "effective_status": "completed",
                    "service_type": "WF",
                    "rush_status": "RUSH",
                }
            for bid in bags.get("pending") or []:
                status_rows[bid] = {
                    "effective_status": "pending",
                    "service_type": "WF",
                    "rush_status": "RUSH",
                }
            for bid in bags.get("review_required") or []:
                status_rows[bid] = {
                    "effective_status": "review_required",
                    "service_type": "WF",
                    "rush_status": "NON-RUSH",
                }
            for bid in bags.get("new_today") or []:
                status_rows.setdefault(
                    bid,
                    {
                        "effective_status": "pending",
                        "service_type": "WF",
                        "rush_status": "RUSH",
                    },
                )
        status_rows[BAG] = {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "NON-RUSH",
        }

    with patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=[day_row]
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=day_rec
    ), patch(
        "backend.rinse_veewash_shift_day._load_day_bag_status_projection",
        return_value=status_rows,
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={},
    ):
        out = apply_manager_edit_day_bag_patch(
            cursor,
            ORG,
            DAY,
            BAG,
            previous_effective_status="review_required",
            previous_reason_codes=["WF_BULK_WORKITEM_REVIEW"],
            outcome_action="mark_completed",
            bulk_cleared=True,
            completion_at="2026-07-28T12:00:00",
            completed_by="Tester",
        )

    headline_update = None
    for c in cursor.execute.call_args_list:
        sql = str(c.args[0]) if c.args else ""
        if "UPDATE rinse_shift_monitor_days" in sql and "headline_json" in sql:
            headline_update = c.args[1]
            break
    assert headline_update is not None
    patched = json.loads(headline_update[1])
    return out, patched


def test_review_to_completed_increments_completed_and_decrements_review():
    segments = {
        "all": _seg(
            completed_ids=[OTHER],
            pending_ids=[],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            total=2,
        ),
        "wf": _seg(
            completed_ids=[OTHER],
            pending_ids=[],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            total=2,
        ),
    }
    out, headline = _run_mark_completed_patch(segments=segments)
    assert out["ok"] is True
    assert out["effective_status"] == "completed"
    wf = headline["segments"]["wf"]
    assert wf["completed"] == 2
    assert wf["exceptions"]["review_required"] == 0
    assert wf["pending"] == 0
    assert wf["total_workload"] == 2
    assert BAG in wf["bag_ids"]["completed"]
    assert BAG not in wf["bag_ids"]["review_required"]
    assert OTHER in wf["bag_ids"]["completed"]
    assert headline["completed"] == 2
    assert headline["exceptions"]["review_required"] == 0


def test_bag_missing_from_completed_ids_is_added():
    segments = {
        "all": _seg(
            completed_ids=[OTHER],  # BAG missing from completed ids
            pending_ids=[],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            completed=1,
            review=1,
            total=2,
        ),
        "wf": _seg(
            completed_ids=[OTHER],
            pending_ids=[],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            completed=1,
            review=1,
            total=2,
        ),
    }
    _, headline = _run_mark_completed_patch(segments=segments)
    assert BAG in headline["segments"]["wf"]["bag_ids"]["completed"]
    assert headline["segments"]["wf"]["completed"] == 2


def test_bag_present_only_in_review_required_still_moves():
    segments = {
        "all": _seg(
            completed_ids=[],
            pending_ids=[],
            review_ids=[BAG],
            new_today=[BAG],
            completed=0,
            review=1,
            total=1,
        ),
        "wf": _seg(
            completed_ids=[],
            pending_ids=[],
            review_ids=[BAG],
            new_today=[BAG],
            completed=0,
            review=1,
            total=1,
        ),
    }
    _, headline = _run_mark_completed_patch(segments=segments)
    wf = headline["segments"]["wf"]
    assert wf["bag_ids"]["completed"] == [BAG]
    assert wf["bag_ids"]["review_required"] == []
    assert wf["completed"] == 1
    assert wf["exceptions"]["review_required"] == 0


def test_empty_bag_ids_still_produce_correct_counts():
    segments = {
        "all": _seg(
            completed_ids=[],
            pending_ids=[],
            review_ids=[],
            new_today=[],
            completed=10,
            pending=5,
            review=1,
            total=16,
        ),
        "wf": _seg(
            completed_ids=[],
            pending_ids=[],
            review_ids=[],
            new_today=[],
            completed=10,
            pending=5,
            review=1,
            total=16,
        ),
    }
    status_rows = {
        BAG: {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "NON-RUSH",
        },
        OTHER: {
            "effective_status": "pending",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
        "DONEX": {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
    }
    _, headline = _run_mark_completed_patch(segments=segments, status_rows=status_rows)
    wf = headline["segments"]["wf"]
    assert set(wf["bag_ids"]["completed"]) == {BAG, "DONEX"}
    assert wf["completed"] == 2
    assert wf["pending"] == 1
    assert wf["exceptions"]["review_required"] == 0
    # No membership lists → total recovered from status partition.
    assert wf["total_workload"] == 3
    assert headline["total_workload"] == 3


def test_numeric_counts_recalculated_from_unique_ids_no_duplicates():
    from backend.rinse_veewash_shift_day import _move_bag_in_segment_bucket

    seg = {
        "completed": 0,
        "pending": 0,
        "exceptions": {"review_required": 2, "total": 2},
        "bag_ids": {
            "completed": [BAG, BAG],
            "pending": [],
            "review_required": [BAG, BAG],
            "new_today": [BAG],
        },
    }
    out = _move_bag_in_segment_bucket(
        seg, BAG, old_bucket="review_required", new_bucket="completed"
    )
    assert out["bag_ids"]["completed"] == [BAG]
    assert out["bag_ids"]["review_required"] == []
    assert out["completed"] == 1
    assert out["exceptions"]["review_required"] == 0


def test_repeated_save_is_idempotent():
    segments = {
        "all": _seg(
            completed_ids=[OTHER],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            total=2,
        ),
        "wf": _seg(
            completed_ids=[OTHER],
            review_ids=[BAG],
            new_today=[OTHER, BAG],
            total=2,
        ),
    }
    _, first = _run_mark_completed_patch(segments=segments)
    # Second pass: already completed in day_bag + headline
    segments2 = {
        "all": first["segments"]["all"],
        "wf": first["segments"]["wf"],
    }
    status_rows = {
        OTHER: {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
        BAG: {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "NON-RUSH",
        },
    }
    _, second = _run_mark_completed_patch(
        segments=segments2,
        day_row_status="completed",
        status_rows=status_rows,
    )
    assert second["segments"]["wf"]["completed"] == first["segments"]["wf"]["completed"] == 2
    assert second["segments"]["wf"]["exceptions"]["review_required"] == 0
    assert second["segments"]["wf"]["bag_ids"]["completed"].count(BAG) == 1


def test_summary_from_day_record_receives_updated_counts():
    """Frontend reload path reads summary_from_day_record → same patched headline."""
    from backend.rinse_veewash_shift_day import summary_from_day_record

    segments = {
        "all": _seg(
            completed_ids=[OTHER, BAG],
            review_ids=[],
            new_today=[OTHER, BAG],
            total=2,
        ),
        "wf": _seg(
            completed_ids=[OTHER, BAG],
            review_ids=[],
            new_today=[OTHER, BAG],
            total=2,
        ),
    }
    day = {
        "status": "OPEN",
        "headline": _headline_from_segments(segments),
        "workload_meta": {},
        "shift_date_et": DAY,
        "organization_id": ORG,
    }
    summary = summary_from_day_record(day)
    assert summary is not None
    assert summary["segments"]["wf"]["completed"] == 2
    assert summary["segments"]["wf"]["exceptions"]["review_required"] == 0
    assert summary["completed"] == 2


def test_hd_review_complete_does_not_call_persist_live_rebuild():
    from backend.rinse_veewash_step1_api import apply_step1_correction

    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_step1_review.save_step1_hd_review",
        return_value={
            "ok": True,
            "step1_outcome": "completed",
            "review": {"review_status": "COMPLETED"},
        },
    ), patch(
        "backend.rinse_veewash_shift_day.apply_manager_edit_day_bag_patch",
        return_value={
            "ok": True,
            "effective_status": "completed",
            "headline_patched": True,
        },
    ) as patch_fn, patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[
            {
                "bag_id": BAG,
                "effective_status": "review_required",
                "review_reason_codes": ["HD_COMPLETION_DETAILS_MISSING"],
            }
        ],
    ), patch(
        "backend.rinse_veewash_shift_day.build_or_load_step1_for_date"
    ) as rebuild:
        out = apply_step1_correction(
            cursor,
            ORG,
            bag_id=BAG,
            action="mark_hd_completed",
            body={"selected_date_et": DAY.isoformat(), "bag_id": BAG},
        )
    assert out["ok"] is True
    assert patch_fn.called
    assert rebuild.call_count == 0
    # manager_edit_version bump to protect against later persist_live
    bump_sql = " ".join(
        str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args
    )
    assert "manager_edit_version" in bump_sql


def test_pending_unchanged_when_prior_was_review_required():
    segments = {
        "all": _seg(
            completed_ids=[OTHER],
            pending_ids=["PEND1"],
            review_ids=[BAG],
            new_today=[OTHER, "PEND1", BAG],
            total=3,
        ),
        "wf": _seg(
            completed_ids=[OTHER],
            pending_ids=["PEND1"],
            review_ids=[BAG],
            new_today=[OTHER, "PEND1", BAG],
            total=3,
        ),
    }
    _, headline = _run_mark_completed_patch(segments=segments)
    assert headline["segments"]["wf"]["pending"] == 1
    assert headline["segments"]["wf"]["bag_ids"]["pending"] == ["PEND1"]
    assert headline["segments"]["wf"]["total_workload"] == 3


def test_headline_day_bag_status_invariant_holds_after_review_complete():
    from backend.rinse_veewash_shift_day import verify_headline_day_bag_status_invariant

    segments = {
        "all": _seg(
            completed_ids=[OTHER],
            pending_ids=["PEND1"],
            review_ids=[BAG],
            new_today=[OTHER, "PEND1", BAG],
            total=3,
        ),
        "wf": _seg(
            completed_ids=[OTHER],
            pending_ids=["PEND1"],
            review_ids=[BAG],
            new_today=[OTHER, "PEND1", BAG],
            total=3,
        ),
    }
    _, headline = _run_mark_completed_patch(segments=segments)
    status_rows = {
        OTHER: {"effective_status": "completed", "service_type": "WF", "rush_status": "RUSH"},
        "PEND1": {"effective_status": "pending", "service_type": "WF", "rush_status": "RUSH"},
        BAG: {"effective_status": "completed", "service_type": "WF", "rush_status": "NON-RUSH"},
    }
    inv = verify_headline_day_bag_status_invariant(headline, status_rows, context="unit")
    assert inv["ok"] is True
    assert inv["headline"]["completed_count"] == 2
    assert inv["headline"]["pending_count"] == 1
    assert inv["headline"]["review_required_count"] == 0
    assert inv["headline"]["total_workload"] == 3
    assert (
        inv["headline"]["completed_count"]
        + inv["headline"]["pending_count"]
        + inv["headline"]["review_required_count"]
        == inv["headline"]["total_workload"]
    )


def test_headline_invariant_logs_mismatch_when_counts_diverge():
    from backend.rinse_veewash_shift_day import verify_headline_day_bag_status_invariant

    headline = {
        "completed": 9,
        "pending": 0,
        "completed_count": 9,
        "pending_count": 0,
        "review_required_count": 0,
        "total_workload": 10,
        "exceptions": {"review_required": 0},
        "segments": {
            "all": {
                "completed": 9,
                "pending": 0,
                "total_workload": 10,
                "exceptions": {"review_required": 0},
                "bag_ids": {
                    "new_today": [BAG, OTHER],
                    "carryover": [],
                    "completed": [BAG],
                    "pending": [],
                    "review_required": [],
                },
            }
        },
    }
    status_rows = {
        BAG: {"effective_status": "completed"},
        OTHER: {"effective_status": "pending"},
    }
    inv = verify_headline_day_bag_status_invariant(headline, status_rows, context="mismatch")
    assert inv["ok"] is False
    assert inv["mismatches"]
