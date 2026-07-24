"""Phase 1A Daily Operations — shared MTD pricing, eligibility, POST authority."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.daily_operations import (
    TRACKING_STARTED_MESSAGE,
    build_daily_operations_day,
    daily_operations_enabled_for_org,
    resolve_authoritative_post_weight,
)
from backend.daily_revenue_cost import cumulative_wf_revenue, wf_revenue_for_day
from backend.rinse_veewash_workload import STEP1_AUTHORITATIVE_START_ET
from backend.wf_mtd_pricing import allocate_wf_day_revenue_from_mtd, cumulative_wf_revenue as shared_cum

DEFAULT_TIERS = [
    {"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.00},
    {"tier_number": 2, "max_lbs": None, "rate_per_lb": 0.95},
]


def test_shared_pricing_is_single_implementation():
    assert cumulative_wf_revenue(6000, DEFAULT_TIERS) == shared_cum(6000, DEFAULT_TIERS)
    assert cumulative_wf_revenue(6000, DEFAULT_TIERS) == Decimal("5950.00")


def test_exactly_5000_mtd_stays_tier1():
    out = allocate_wf_day_revenue_from_mtd(4900, 100, DEFAULT_TIERS)
    assert out["tier1_pounds_today"] == 100.0
    assert out["tier2_pounds_today"] == 0.0
    assert out["weight_revenue_today"] == 100.0
    assert out["mtd_pounds_after"] == 5000.0


def test_crossing_5000_during_day_splits():
    out = allocate_wf_day_revenue_from_mtd(4950, 100, DEFAULT_TIERS)
    assert out["tier1_pounds_today"] == 50.0
    assert out["tier2_pounds_today"] == 50.0
    assert out["weight_revenue_today"] == 97.5
    assert out["mtd_pounds_before"] == 4950.0
    assert out["mtd_pounds_after"] == 5050.0


def test_day_after_threshold_uses_tier2():
    out = allocate_wf_day_revenue_from_mtd(5000, 100, DEFAULT_TIERS)
    assert out["tier1_pounds_today"] == 0.0
    assert out["tier2_pounds_today"] == 100.0
    assert out["weight_revenue_today"] == 95.0


def test_month_boundary_resets_mtd_position():
    # Caller supplies month-local mtd_before=0 on the 1st.
    out = allocate_wf_day_revenue_from_mtd(0, 100, DEFAULT_TIERS)
    assert out["mtd_pounds_before"] == 0.0
    assert out["tier1_pounds_today"] == 100.0
    assert out["weight_revenue_today"] == 100.0


def test_decimal_rounding_deterministic():
    out = allocate_wf_day_revenue_from_mtd(4999.99, 0.02, DEFAULT_TIERS)
    assert out["weight_revenue_today"] == round(out["weight_revenue_today"], 2)
    # 0.01 stays tier1 @1.00 + 0.01 tier2 @0.95
    assert out["tier1_pounds_today"] == 0.01
    assert out["tier2_pounds_today"] == 0.01
    assert out["weight_revenue_today"] == 0.02  # 0.01 + 0.0095 -> 0.02 half-up on lines? 
    # Line revenues quantized separately: 0.01*1=0.01, 0.01*0.95=0.01 → sum of applied may differ from day_rev
    # day_rev uses cumulative difference which is authoritative:
    before = shared_cum(4999.99, DEFAULT_TIERS)
    after = shared_cum(5000.01, DEFAULT_TIERS)
    assert out["weight_revenue_today"] == float((after - before).quantize(Decimal("0.01")))


def test_drc_wf_revenue_for_day_uses_shared_allocator():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"mtd": 4950}
    rev, meta = wf_revenue_for_day(cursor, 3, date(2026, 8, 5), 100, tiers=DEFAULT_TIERS)
    shared = allocate_wf_day_revenue_from_mtd(4950, 100, DEFAULT_TIERS)
    assert rev == shared["weight_revenue_today"]
    assert meta["applied_tiers"] == shared["applied_tiers"]


def test_org_feature_flag():
    assert daily_operations_enabled_for_org(3) is True
    assert daily_operations_enabled_for_org(1) is False


def test_pre_jul23_unavailable():
    cursor = MagicMock()
    out = build_daily_operations_day(cursor, 3, date(2026, 7, 22), persist=False)
    assert out["available"] is False
    assert out["message"] == TRACKING_STARTED_MESSAGE
    assert out["tracking_started_et"] == STEP1_AUTHORITATIVE_START_ET.isoformat()


def test_jul23_membership_not_rebuilt():
    cursor = MagicMock()
    with patch("backend.daily_operations.ensure_daily_operations_tables"), patch(
        "backend.daily_operations.compute_day_wf_pound_totals",
        return_value={
            "included_bags": [],
            "missing_post_bags": [],
            "completed_wf_bag_count": 0,
            "included_count": 0,
            "missing_post_weight_count": 0,
            "today_wf_completed_pounds": 0.0,
        },
    ), patch("backend.daily_operations.compute_mtd_pounds_before", return_value=0.0), patch(
        "backend.daily_operations.count_outstanding_wf_workitem_reviews", return_value=0
    ), patch(
        "backend.daily_revenue_cost.ensure_daily_revenue_cost_tables"
    ), patch(
        "backend.daily_revenue_cost.ensure_veewash_aug1_2026_wf_schedule",
        return_value={"created": False},
    ), patch(
        "backend.daily_revenue_cost.get_wf_schedule_for_date",
        return_value=(None, []),
    ), patch(
        "backend.daily_operations_hd.ensure_hd_production_tables"
    ), patch(
        "backend.daily_operations_hd.sum_reviewed_wf_workitem_revenue", return_value=0.0
    ), patch(
        "backend.daily_operations_hd.compute_hd_day_revenue_totals",
        return_value={
            "hd_orders_available": 0,
            "not_recorded": 0,
            "partially_recorded": 0,
            "complete": 0,
            "complete_total_items": 0,
            "complete_hd_revenue": 0.0,
            "partial_hd_revenue_entered": 0.0,
            "total_hd_revenue": 0.0,
            "orphan_production_facts": [],
        },
    ):
        out = build_daily_operations_day(cursor, 3, date(2026, 7, 23), persist=False)
    assert out["available"] is True
    assert out["diagnostics"]["eligibility"]["jul23_membership_rebuild"] is False
    assert out["revenue"]["pricing_incomplete"] is True


def test_aug1_schedule_applies_math_not_jul31():
    jul = allocate_wf_day_revenue_from_mtd(0, 100, [])
    assert jul["pricing_complete"] is False
    assert jul["weight_revenue_today"] == 0.0
    aug = allocate_wf_day_revenue_from_mtd(0, 100, DEFAULT_TIERS)
    assert aug["pricing_complete"] is True
    assert aug["weight_revenue_today"] == 100.0


def test_missing_pricing_marks_incomplete():
    cursor = MagicMock()
    with patch("backend.daily_operations.ensure_daily_operations_tables"), patch(
        "backend.daily_operations.compute_day_wf_pound_totals",
        return_value={
            "included_bags": [{"bag_id": "ABC"}],
            "missing_post_bags": [],
            "completed_wf_bag_count": 1,
            "included_count": 1,
            "missing_post_weight_count": 0,
            "today_wf_completed_pounds": 10.0,
        },
    ), patch("backend.daily_operations.compute_mtd_pounds_before", return_value=0.0), patch(
        "backend.daily_operations.count_outstanding_wf_workitem_reviews", return_value=0
    ), patch(
        "backend.daily_revenue_cost.ensure_daily_revenue_cost_tables"
    ), patch(
        "backend.daily_revenue_cost.ensure_veewash_aug1_2026_wf_schedule",
        return_value={"created": False},
    ), patch(
        "backend.daily_revenue_cost.get_wf_schedule_for_date",
        return_value=(None, []),
    ), patch(
        "backend.daily_operations_hd.ensure_hd_production_tables"
    ), patch(
        "backend.daily_operations_hd.sum_reviewed_wf_workitem_revenue", return_value=12.5
    ), patch(
        "backend.daily_operations_hd.compute_hd_day_revenue_totals",
        return_value={
            "hd_orders_available": 2,
            "not_recorded": 1,
            "partially_recorded": 0,
            "complete": 1,
            "complete_total_items": 3,
            "complete_hd_revenue": 40.0,
            "partial_hd_revenue_entered": 5.0,
            "total_hd_revenue": 40.0,
            "orphan_production_facts": [],
        },
    ):
        out = build_daily_operations_day(cursor, 3, date(2026, 7, 23), persist=False)
    assert out["kpis"]["pricing_incomplete"] is True
    assert out["kpis"]["wf_weight_revenue"] is None
    assert out["kpis"]["wf_workitem_revenue"] == 12.5
    assert out["kpis"]["hd_revenue"] == 40.0
    assert out["kpis"]["partial_hd_revenue_entered"] == 5.0
    assert out["kpis"]["total_revenue"] == 52.5


def test_manager_corrected_post_priority():
    cursor = MagicMock()
    with patch("backend.daily_operations._latest_manager_post_correction") as corr, patch(
        "backend.daily_operations._post_role_scan_events"
    ) as posts, patch(
        "backend.daily_operations._canonical_post_processing_event"
    ) as canon:
        corr.return_value = {
            "weight_lbs": 12.5,
            "source": "manager_corrected_post",
            "correction_id": 1,
            "scan_event_id": None,
        }
        posts.return_value = [{"id": 9, "weight_lbs": 99}]
        canon.return_value = {"weight_lbs": 88, "source": "canonical"}
        out = resolve_authoritative_post_weight(cursor, 3, "BAG1", operations_date_et=date(2026, 7, 23))
    assert out["weight_lbs"] == 12.5
    assert out["source"] == "manager_corrected_post"
    posts.assert_not_called()
    canon.assert_not_called()


def test_post_role_before_canonical():
    cursor = MagicMock()
    with patch("backend.daily_operations._latest_manager_post_correction", return_value=None), patch(
        "backend.daily_operations._post_role_scan_events",
        return_value=[{"id": 7, "weight_lbs": 20.5, "weight_source": "presence_run_weight_num"}],
    ), patch("backend.daily_operations._canonical_post_processing_event") as canon:
        out = resolve_authoritative_post_weight(cursor, 3, "BAG1", operations_date_et=date(2026, 7, 23))
    assert out["weight_lbs"] == 20.5
    assert out["source"] == "scan_weight_role_post"
    canon.assert_not_called()


def test_missing_post_is_exception():
    cursor = MagicMock()
    with patch("backend.daily_operations._latest_manager_post_correction", return_value=None), patch(
        "backend.daily_operations._post_role_scan_events", return_value=[]
    ), patch("backend.daily_operations._canonical_post_processing_event", return_value=None):
        out = resolve_authoritative_post_weight(cursor, 3, "BAG1", operations_date_et=date(2026, 7, 23))
    assert out["missing"] is True
    assert out["weight_lbs"] is None


def test_classify_exclusion_reasons_are_exclusive():
    from backend.daily_operations import (
        EXCL_INCOMPLETE,
        EXCL_MISSING_MEMBERSHIP,
        EXCL_MISSING_POST,
        EXCL_WRONG_WORKFLOW,
        classify_finance_bag_vs_daily_operations,
    )

    ops = date(2026, 7, 23)
    base = dict(
        finance_weight_lbs=10.0,
        operations_date_et=ops,
        membership_ids={"A", "B", "C", "D"},
        manual_exclusions=set(),
        do_included_ids=set(),
        do_missing_post_ids={"D"},
    )
    assert (
        classify_finance_bag_vs_daily_operations(
            bag_id="A",
            day_bag={"service_type": "HD", "canonical_completion_status": "completed"},
            **base,
        )["exclusion_reason"]
        == EXCL_WRONG_WORKFLOW
    )
    assert (
        classify_finance_bag_vs_daily_operations(
            bag_id="Z",
            day_bag=None,
            **base,
        )["exclusion_reason"]
        == EXCL_MISSING_MEMBERSHIP
    )
    assert (
        classify_finance_bag_vs_daily_operations(
            bag_id="B",
            day_bag={"service_type": "WF", "canonical_completion_status": "pending"},
            **base,
        )["exclusion_reason"]
        == EXCL_INCOMPLETE
    )
    assert (
        classify_finance_bag_vs_daily_operations(
            bag_id="D",
            day_bag={"service_type": "WF", "canonical_completion_status": "completed"},
            **base,
        )["exclusion_reason"]
        == EXCL_MISSING_POST
    )
    included = classify_finance_bag_vs_daily_operations(
        bag_id="C",
        day_bag={"service_type": "WF", "canonical_completion_status": "completed"},
        finance_weight_lbs=10.0,
        operations_date_et=ops,
        membership_ids={"C"},
        manual_exclusions=set(),
        do_included_ids={"C"},
        do_missing_post_ids=set(),
    )
    assert included["fate"] == "included"
    assert included["exclusion_reason"] is None


def test_reconciliation_assigns_one_reason_and_balances():
    from backend.daily_operations import reconcile_finance_wf_pounds_to_daily_operations

    do_day = {
        "revenue": {"wf_completed_pounds": 20.0},
        "drilldowns": {
            "included_wf_bags": [
                {"bag_id": "IN1", "post_weight_lbs": 20.0, "post_weight_source": "scan_weight_role_post"}
            ],
            "missing_post_weight_bags": [
                {"bag_id": "MP1", "post_weight_lbs": None}
            ],
        },
    }
    finance = {
        "available": True,
        "error": None,
        "quantity": 100.0,
        "records": [
            {"bag_id": "IN1", "weight_lbs": 20.0, "completion_timestamp": "2026-07-23T12:00:00"},
            {"bag_id": "MP1", "weight_lbs": 30.0, "completion_timestamp": "2026-07-23T12:00:00"},
            {"bag_id": "HD1", "weight_lbs": 25.0, "completion_timestamp": "2026-07-23T12:00:00"},
            {"bag_id": "OUT1", "weight_lbs": 25.0, "completion_timestamp": "2026-07-22T12:00:00"},
        ],
        "counts": {},
    }
    day_bags = {
        "IN1": {"service_type": "WF", "canonical_completion_status": "completed"},
        "MP1": {"service_type": "WF", "canonical_completion_status": "completed"},
        "HD1": {"service_type": "HD", "canonical_completion_status": "completed"},
    }
    with patch(
        "backend.daily_operations.fetch_finance_wf_suggestion_records", return_value=finance
    ), patch(
        "backend.daily_operations.load_day_bag_index", return_value=day_bags
    ), patch(
        "backend.daily_operations.load_day_membership_bag_ids",
        return_value={"IN1", "MP1", "HD1"},
    ), patch(
        "backend.daily_operations.load_manual_daily_ops_exclusions", return_value=set()
    ):
        out = reconcile_finance_wf_pounds_to_daily_operations(
            MagicMock(), 3, date(2026, 7, 23), do_day=do_day
        )

    assert out["finance_suggested_pounds"] == 100.0
    assert out["identity"]["finance_equals_included_plus_excluded"] is True
    assert out["identity"]["every_excluded_bag_has_one_reason"] is True
    by_reason = {r["reason"]: r for r in out["excluded"]}
    assert by_reason["missing_post"]["pounds"] == 30.0
    assert by_reason["wrong_workflow"]["pounds"] == 25.0
    assert by_reason["completed_outside_selected_et_day"]["pounds"] == 25.0
    assert out["included_from_finance"]["finance_pounds"] == 20.0
    assert out["daily_operations_eligible_pounds"] == 20.0
    excluded_bags = [b for r in out["excluded"] for b in r["bags"]]
    assert len(excluded_bags) == 3
    assert len({b["bag_id"] for b in excluded_bags}) == 3
    assert all(b.get("exclusion_reason") for b in excluded_bags)
