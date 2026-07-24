"""Phase 1B Daily Operations — unified WF bag review."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.daily_operations import (
    POST_SOURCE_MANAGER_CORRECTED,
    POST_SOURCE_WEIGHT_ROLE_POST,
    resolve_authoritative_post_weight,
    resolve_evidence_post_weight,
)
from backend.daily_operations_wf_review import (
    FILTER_MISSING_POST,
    FILTER_REVIEW_REQUIRED,
    FILTER_WORK_ITEMS,
    RES_BILLABLE_ITEMS,
    RES_NO_BILLABLE_ITEMS,
    STATUS_ACCEPTED_EXCEPTION,
    STATUS_REVIEWED,
    _validate_save_payload,
    allocate_estimated_bag_weight_revenues,
    build_wf_review_queue,
    resolve_post_weight_for_daily_ops,
    save_wf_review,
    undo_wf_review,
)
from backend.wf_mtd_pricing import allocate_wf_day_revenue_from_mtd

DAY = date(2026, 7, 23)
TIERS = [
    {"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.00},
    {"tier_number": 2, "max_lbs": None, "rate_per_lb": 0.95},
]


def test_estimated_allocations_sum_to_day_revenue():
    bags = [
        {"bag_id": "B003", "post_weight_lbs": 10},
        {"bag_id": "B001", "post_weight_lbs": 20},
        {"bag_id": "B002", "post_weight_lbs": 30},
    ]
    day_rev = 100.0
    allocs = allocate_estimated_bag_weight_revenues(day_weight_revenue=day_rev, bags=bags)
    assert sum(a["estimated_weight_revenue"] for a in allocs) == pytest.approx(100.0)
    # Deterministic residual to last bag_id sort order
    assert [a["bag_id"] for a in allocs] == ["B001", "B002", "B003"]


def test_estimated_allocations_zero_total_pounds():
    allocs = allocate_estimated_bag_weight_revenues(
        day_weight_revenue=50,
        bags=[{"bag_id": "A", "post_weight_lbs": 0}],
    )
    assert allocs[0]["estimated_weight_revenue"] == 0.0


def test_residual_rounding_deterministic():
    bags = [
        {"bag_id": "Z", "post_weight_lbs": 1},
        {"bag_id": "A", "post_weight_lbs": 1},
        {"bag_id": "M", "post_weight_lbs": 1},
    ]
    a1 = allocate_estimated_bag_weight_revenues(day_weight_revenue=10.00, bags=bags)
    a2 = allocate_estimated_bag_weight_revenues(day_weight_revenue=10.00, bags=list(reversed(bags)))
    assert a1 == a2
    assert sum(x["estimated_weight_revenue"] for x in a1) == 10.0


def test_validate_rejects_negative_and_zero_without_reason():
    assert "negative_post_weight_rejected" in _validate_save_payload(
        {"corrected_post_weight_lbs": -1, "reason": "x", "no_billable_items": True, "no_billable_reason": "n"},
        current_post=10,
    )
    assert "zero_post_requires_reason" in _validate_save_payload(
        {"corrected_post_weight_lbs": 0, "no_billable_items": True, "no_billable_reason": "n"},
        current_post=10,
    )
    assert "explicit_workitem_resolution_required" in _validate_save_payload(
        {"reason": "x", "items": []},
        current_post=10,
    )


def test_validate_explicit_no_billable():
    errs = _validate_save_payload(
        {
            "reason": "none",
            "no_billable_items": True,
            "no_billable_reason": "detected but not billable",
        },
        current_post=12.5,
    )
    assert errs == []


def test_validate_positive_work_items():
    errs = _validate_save_payload(
        {"reason": "ok", "items": [{"workitem_id": 1, "quantity": 2}]},
        current_post=12.5,
    )
    assert errs == []


def test_evidence_resolver_never_uses_manager_correction():
    cursor = MagicMock()
    with patch(
        "backend.daily_operations._post_role_scan_events",
        return_value=[{"id": 9, "weight_lbs": 11.5, "weight_source": "scan"}],
    ), patch("backend.daily_operations._canonical_post_processing_event", return_value=None), patch(
        "backend.daily_operations._latest_manager_post_correction",
        return_value={"weight_lbs": 99.0, "source": POST_SOURCE_MANAGER_CORRECTED},
    ):
        ev = resolve_evidence_post_weight(cursor, 3, "BAG1", operations_date_et=DAY)
        auth = resolve_authoritative_post_weight(cursor, 3, "BAG1", operations_date_et=DAY)
    assert ev["weight_lbs"] == 11.5
    assert ev["source"] == POST_SOURCE_WEIGHT_ROLE_POST
    assert auth["weight_lbs"] == 99.0


def test_do_resolver_prefers_fact_correction():
    cursor = MagicMock()
    with patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        return_value={
            "post_weight_corrected": 1,
            "authoritative_post_weight_lbs": 42.25,
            "original_post_weight_lbs": 40.0,
            "post_weight_correction_reason": "scale check",
            "version": 3,
        },
    ), patch(
        "backend.daily_operations_wf_review.resolve_authoritative_post_weight",
        return_value={"weight_lbs": 40.0, "source": POST_SOURCE_WEIGHT_ROLE_POST, "missing": False},
    ):
        out = resolve_post_weight_for_daily_ops(cursor, 3, "BAG1", operations_date_et=DAY)
    assert out["weight_lbs"] == 42.25
    assert out["source"] == POST_SOURCE_MANAGER_CORRECTED
    assert out["corrected"] is True


def test_queue_missing_post_and_work_items():
    cursor = MagicMock()
    bags = [
        {
            "bag_id": "MISS1",
            "day_bag_id": 1,
            "canonical_completion_status": "completed",
            "canonical_completion_timestamp": "2026-07-23T12:00:00",
            "review_reason_codes_json": "[]",
        },
        {
            "bag_id": "WI1",
            "day_bag_id": 2,
            "canonical_completion_status": "completed",
            "canonical_completion_timestamp": "2026-07-23T13:00:00",
            "review_reason_codes_json": '["WF_BULK_WORKITEM_REVIEW"]',
        },
    ]

    def post_side(cursor, org, bag_id, *, operations_date_et):
        if bag_id == "MISS1":
            return {"weight_lbs": None, "missing": True, "source": "missing_post_weight", "corrected": False}
        return {"weight_lbs": 10.0, "missing": False, "source": POST_SOURCE_WEIGHT_ROLE_POST, "corrected": False}

    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.daily_operations_enabled_for_org", return_value=True
    ), patch(
        "backend.daily_operations_wf_review.list_wf_completed_day_bags", return_value=bags
    ), patch(
        "backend.daily_operations_wf_review.resolve_post_weight_for_daily_ops", side_effect=post_side
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row", return_value=None
    ), patch(
        "backend.daily_operations_wf_review._workitem_activity_detected",
        side_effect=lambda c, o, b: {
            "detected": b == "WI1",
            "count": 2 if b == "WI1" else 0,
            "first_at": None,
            "last_at": None,
            "purposes": ["BULK"],
        },
    ), patch(
        "backend.daily_operations_wf_review._bulk_review_unresolved",
        side_effect=lambda *a, **k: a[3] == "WI1" if len(a) > 3 else False,
    ):
        miss = build_wf_review_queue(cursor, 3, DAY, filter_key=FILTER_MISSING_POST)
        wi = build_wf_review_queue(cursor, 3, DAY, filter_key=FILTER_WORK_ITEMS)
        req = build_wf_review_queue(cursor, 3, DAY, filter_key=FILTER_REVIEW_REQUIRED)

    assert miss["jul23_membership_rebuild"] is False
    assert {x["bag_id"] for x in miss["items"]} == {"MISS1"}
    assert {x["bag_id"] for x in wi["items"]} == {"WI1"}
    assert {x["bag_id"] for x in req["items"]} >= {"MISS1", "WI1"}


def test_save_optimistic_lock_conflict():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 1},
        "post_weight": {
            "authoritative_post_weight_lbs": 10.0,
            "evidence_post_weight_lbs": 10.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": 1,
            "presence_run_id": None,
            "presence_run_row_id": None,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 2},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", return_value=detail
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        return_value={"version": 5, "id": 9},
    ):
        out = save_wf_review(
            cursor,
            3,
            DAY,
            "BAG1",
            {
                "version": 2,
                "reason": "x",
                "no_billable_items": True,
                "no_billable_reason": "n",
            },
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"
    assert out["status"] == 409


def test_save_atomic_rollback_on_workitem_failure():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 1},
        "post_weight": {
            "authoritative_post_weight_lbs": 10.0,
            "evidence_post_weight_lbs": 10.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": 1,
            "presence_run_id": None,
            "presence_run_row_id": None,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 1},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", return_value=detail
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row", return_value={"version": 1}
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": False, "error": "boom"},
    ), patch("backend.rinse_veewash_step1_api._record_correction") as corr:
        out = save_wf_review(
            cursor,
            3,
            DAY,
            "BAG1",
            {
                "version": 1,
                "reason": "x",
                "no_billable_items": True,
                "no_billable_reason": "n",
            },
        )
    assert out["ok"] is False
    assert out["error"] == "workitem_save_failed"
    corr.assert_not_called()
    # No fact upsert after WI failure
    assert cursor.execute.call_count == 0 or all(
        "INSERT INTO wf_day_bag_revenue" not in str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args
    )


def test_save_manager_post_correction_priority_and_no_scan_mutation():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 7, "bag_id": "BAG1"},
        "post_weight": {
            "authoritative_post_weight_lbs": 10.0,
            "evidence_post_weight_lbs": 10.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": 55,
            "presence_run_id": 100,
            "presence_run_row_id": 200,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 1},
    }
    day_out = {
        "kpis": {
            "wf_completed_pounds": 12.5,
            "wf_weight_revenue": 12.5,
            "missing_post_weights": 0,
            "outstanding_wf_workitem_reviews": 0,
        },
        "revenue": {"wf_weight_revenue": 12.5},
        "drilldowns": {"included_wf_bags": [{"bag_id": "BAG1", "post_weight_lbs": 12.5}]},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", side_effect=[detail, {**detail, "ok": True}]
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        side_effect=[
            {"version": 1, "id": 1},
            {
                "id": 1,
                "version": 2,
                "post_weight_corrected": 1,
                "authoritative_post_weight_lbs": 12.5,
                "workitem_revenue": 0,
            },
        ],
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True, "items_total": 0},
    ), patch("backend.rinse_veewash_step1_api._record_correction") as corr, patch(
        "backend.daily_operations_wf_review.build_daily_operations_day", return_value=day_out
    ), patch("backend.daily_operations_wf_review._recompute_estimated_allocations"):
        out = save_wf_review(
            cursor,
            3,
            DAY,
            "BAG1",
            {
                "version": 1,
                "reason": "scale",
                "corrected_post_weight_lbs": 12.5,
                "post_weight_correction_reason": "scale",
                "no_billable_items": True,
                "no_billable_reason": "none",
            },
            actor_user_id=9,
            actor_display_name="Mgr",
        )
    assert out["ok"] is True
    assert out["review_status"] == STATUS_REVIEWED
    assert RES_NO_BILLABLE_ITEMS in out["review_resolution"]
    corr.assert_called_once()
    sqls = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list if c.args)
    assert "rinse_cleaner_ticket_presence_run_rows" not in sqls
    assert "INSERT INTO rinse_bag_scan_events" not in sqls
    assert "UPDATE rinse_shift_monitor_day_bags" in sqls


def test_save_billable_lines_resolution():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 1},
        "post_weight": {
            "authoritative_post_weight_lbs": 8.0,
            "evidence_post_weight_lbs": 8.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": None,
            "presence_run_id": None,
            "presence_run_row_id": None,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 1},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", side_effect=[detail, detail]
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        side_effect=[{"version": 1}, {"id": 3, "version": 2, "workitem_revenue": 15}],
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True, "items_total": 15.0},
    ) as wi, patch("backend.daily_operations_wf_review.build_daily_operations_day", return_value={"kpis": {}, "revenue": {}, "drilldowns": {"included_wf_bags": []}}), patch(
        "backend.daily_operations_wf_review._recompute_estimated_allocations"
    ):
        out = save_wf_review(
            cursor,
            3,
            DAY,
            "BAG2",
            {
                "version": 1,
                "reason": "bill",
                "items": [{"workitem_id": 4, "quantity": 3}],
            },
        )
    assert out["ok"] is True
    assert out["review_resolution"] == RES_BILLABLE_ITEMS
    assert wi.call_args.kwargs.get("no_chargeable") is False
    assert wi.call_args.kwargs.get("items") == [{"workitem_id": 4, "quantity": 3}]


def test_undo_creates_new_version_and_restores_authority():
    cursor = MagicMock()
    fact = {
        "id": 10,
        "version": 3,
        "authoritative_post_weight_lbs": 20.0,
        "post_weight_corrected": 1,
        "original_post_weight_lbs": 10.0,
        "workitem_revenue": 5,
    }
    before = {
        "fact": {
            "authoritative_post_weight_lbs": 10.0,
            "post_weight_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "post_weight_scan_event_id": 1,
            "post_weight_presence_run_id": None,
            "post_weight_presence_run_row_id": None,
            "post_weight_corrected": 0,
            "original_post_weight_lbs": 10.0,
            "post_weight_correction_reason": None,
            "workitem_revenue": 0,
            "review_status": "REVIEW_REQUIRED",
            "review_resolution": None,
            "notes": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
        },
        "workitems": [],
        "resolution": None,
    }
    audit_row = {"id": 100, "before_json": before, "is_undo": 0}

    def fetchone_side():
        # sequence depends on call order inside undo
        yield fact  # get_wf_day_bag_revenue_row first via ensure path? mocked
        yield audit_row
        yield None  # no later edit
        yield {**fact, "version": 4, "post_weight_corrected": 0, "authoritative_post_weight_lbs": 10.0}

    # Simpler: patch get_wf_day_bag_revenue_row and cursor.fetchone
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        side_effect=[fact, {**fact, "version": 4, "post_weight_corrected": 0, "authoritative_post_weight_lbs": 10.0}],
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems", return_value={"ok": True}
    ), patch("backend.rinse_veewash_step1_api._record_correction") as corr, patch(
        "backend.daily_operations_wf_review.build_daily_operations_day",
        return_value={"kpis": {}, "revenue": {}, "drilldowns": {"included_wf_bags": []}},
    ), patch("backend.daily_operations_wf_review._recompute_estimated_allocations"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail",
        return_value={"ok": True, "review": {"version": 4}},
    ), patch("backend.daily_operations_wf_review._json_load", return_value=before):
        cursor.fetchone.side_effect = [audit_row, None]
        out = undo_wf_review(
            cursor,
            3,
            DAY,
            "BAG1",
            reason="revert",
            actor_user_id=1,
            actor_display_name="Ops",
        )
    assert out["ok"] is True
    assert out["version"] == 4
    corr.assert_called_once()
    assert corr.call_args.kwargs.get("action") == "undo_correct_weight" or corr.call_args[1].get(
        "action"
    ) == "undo_correct_weight" or any(
        c.kwargs.get("action") == "undo_correct_weight" or (c.args and False)
        for c in [corr.call_args]
    )
    # Verify action via call kwargs/args
    called_action = corr.call_args.kwargs.get("action")
    if called_action is None and corr.call_args.args:
        # positional after cursor, org
        pass
    assert corr.call_args.kwargs["action"] == "undo_correct_weight"


def test_day_pounds_and_mtd_update_after_correction_math():
    # Pure pricing: correcting +2.5 lbs at tier1 increases day revenue by 2.5
    before = allocate_wf_day_revenue_from_mtd(0, 100, TIERS)
    after = allocate_wf_day_revenue_from_mtd(0, 102.5, TIERS)
    assert after["weight_revenue_today"] == pytest.approx(before["weight_revenue_today"] + 2.5)


def test_accepted_exception_status_constant():
    assert STATUS_ACCEPTED_EXCEPTION == "ACCEPTED_EXCEPTION"


def test_portal_weight_not_in_evidence_path():
    """Evidence path uses POST-role scans / canonical only — never portal upload weight."""
    cursor = MagicMock()
    with patch("backend.daily_operations._post_role_scan_events", return_value=[]), patch(
        "backend.daily_operations._canonical_post_processing_event", return_value=None
    ) as canon:
        out = resolve_evidence_post_weight(cursor, 3, "X", operations_date_et=DAY)
    assert out["missing"] is True
    # canonical helper is the only fallback; portal is not consulted here
    canon.assert_called_once()


def test_evidence_pre_is_immutable_and_uses_earliest_pre_role():
    from backend.daily_operations import PRE_SOURCE_WEIGHT_ROLE_PRE, resolve_evidence_pre_weight

    cursor = MagicMock()
    with patch(
        "backend.daily_operations._pre_role_scan_events",
        return_value=[
            {"id": 1, "weight_lbs": 18.7, "weight_observed_at": "2026-07-23T08:00:00", "weight_source": "presence"},
            {"id": 2, "weight_lbs": 19.0, "weight_observed_at": "2026-07-23T09:00:00"},
        ],
    ):
        out = resolve_evidence_pre_weight(cursor, 3, "BAG1")
    assert out["weight_lbs"] == 18.7
    assert out["source"] == PRE_SOURCE_WEIGHT_ROLE_PRE
    assert out["editable"] is False
    assert out["scan_event_id"] == 1


def test_weight_summary_shape_on_detail():
    cursor = MagicMock()
    bag = {
        "bag_id": "BAG1",
        "day_bag_id": 1,
        "canonical_completion_status": "completed",
        "canonical_completion_timestamp": "2026-07-23T12:00:00",
        "review_reason_codes_json": "[]",
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.list_wf_completed_day_bags", return_value=[bag]
    ), patch(
        "backend.daily_operations_wf_review.resolve_post_weight_for_daily_ops",
        return_value={
            "weight_lbs": 20.5,
            "source": POST_SOURCE_WEIGHT_ROLE_POST,
            "missing": False,
            "corrected": False,
            "scan_event_id": 9,
        },
    ), patch(
        "backend.daily_operations_wf_review.resolve_evidence_post_weight",
        return_value={
            "weight_lbs": 20.5,
            "source": POST_SOURCE_WEIGHT_ROLE_POST,
            "observed_at": "2026-07-23T11:00:00",
            "scan_event_id": 9,
            "missing": False,
        },
    ), patch(
        "backend.daily_operations_wf_review.resolve_evidence_pre_weight",
        return_value={
            "weight_lbs": 18.7,
            "source": "scan_weight_role_pre",
            "observed_at": "2026-07-23T08:00:00",
            "scan_event_id": 3,
            "missing": False,
            "editable": False,
        },
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row", return_value=None
    ), patch(
        "backend.rinse_bulk_workitems.list_workitems", return_value=[]
    ), patch(
        "backend.rinse_bulk_workitems.load_bag_bulk_audits", return_value={}
    ), patch(
        "backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}
    ), patch(
        "backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}
    ), patch(
        "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}
    ), patch(
        "backend.daily_operations_wf_review._queue_flags_for_bag",
        return_value={
            "review_required": False,
            "missing_post": False,
            "work_items_detected": False,
            "review_status": "REVIEW_REQUIRED",
            "review_resolution": None,
        },
    ), patch("backend.daily_operations_wf_review.table_exists", return_value=False):
        from backend.daily_operations_wf_review import get_wf_review_detail

        out = get_wf_review_detail(cursor, 3, DAY, "BAG1")
    assert out["ok"] is True
    assert out["weight_summary"]["pre_weight"] == 18.7
    assert out["weight_summary"]["pre_timestamp"] == "2026-07-23T08:00:00"
    assert out["weight_summary"]["pre_source"] == "scan_weight_role_pre"
    assert out["weight_summary"]["post_weight"] == 20.5
    assert out["weight_summary"]["manager_corrected_post"] is None
    assert out["pre_weight"]["editable"] is False
    assert out["weight_summary"]["pre_editable"] is False
