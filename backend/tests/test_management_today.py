"""Contract tests: Management Hub TODAY is a compact read model over existing sources."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.management_today import (
    assert_compact_today_payload,
    build_management_today_payload,
    clear_management_today_cache,
    extract_hd_kpis,
    extract_labor_kpis,
    extract_other_revenue,
    extract_review,
    extract_rinse_step1,
    extract_supplies,
    extract_wf_kpis,
)


def _headline():
    return {
        "exceptions": {"review_required": 5},
        "comforter_order_count": 4,
        "bath_mat_order_count": 2,
        "rejected_order_count": 8,
        "split_order_count": 42,
        "specialty_metrics": {
            "wf": {
                "comforter_orders": {"count": 4, "order_ids": ["A", "B", "C", "D"]},
                "bath_mat_orders": {"count": 2, "order_ids": ["D", "E"]},
                "rejected_orders": {"count": 8, "order_ids": ["R1"]},
                "split_orders": {"count": 42, "order_ids": ["S1"]},
            }
        },
        "hd_dashboard_totals": {
            "total_hd_orders": 13,
            "completed": 12,
            "review_required": 1,
            "total_items": 48,
            "hd_revenue": 210.5,
        },
        "segments": {
            "all": {"exceptions": {"review_required": 5}},
            "wf": {
                "total_workload": 97,
                "active_workload": 97,
                "completed": 70,
                "pending": 1,
                "exceptions": {"review_required": 26},
                "bag_ids": {
                    "completed": ["SHOULD_NOT_LEAK", "A", "B"],
                    "pending": ["C"],
                    "review_required": ["D", "R1", "S1"],
                },
            },
            "wf_rush": {
                "total_workload": 12,
                "completed": 8,
                "pending": 0,
                "exceptions": {"review_required": 4},
                "bag_ids": {"review_required": ["R1"], "completed": ["A"]},
            },
            "hd": {
                "total_workload": 13,
                "completed": 12,
                "pending": 3,
                "exceptions": {"review_required": 1},
                "bag_ids": {"completed": ["HD1"]},
            },
        },
    }


def test_wf_kpis_match_step1_headline_scalars():
    wf = extract_wf_kpis(_headline(), lbs_processed=1940.25)
    assert wf["bags"] == 97
    assert wf["completed"] == 70
    assert wf["lbs_processed"] == 1940.25
    assert wf["specialty"] == 5  # unique A,B,C,D,E
    assert wf["rejects"] == 8
    assert wf["reject_pct"] == 8.2
    assert wf["split_pct"] == 43.3
    assert "bag_ids" not in wf


def test_hd_kpis_use_step1_counts_and_production_facts():
    hd = extract_hd_kpis(
        _headline(),
        {
            "complete": 9,
            "complete_total_items": 48,
            "complete_hd_revenue": 210.5,
            "not_recorded": 4,
            "partially_recorded": 1,
            "orphan_production_facts": [{"bag_id": "X"}],
        },
    )
    assert hd["completed_orders"] == 12
    assert hd["open_in_process"] == 3
    assert hd["items"] == 48
    assert hd["revenue"] == 210.5
    assert "orphan_production_facts" not in hd


def test_other_revenue_sums_drc_cash_card_and_commercial():
    lines = {
        "revenue.self_service.cash": {"amount": 10},
        "revenue.self_service.card": {"amount": 20.25},
        "revenue.drop_off.cash": {"amount": 5},
        "revenue.drop_off.card": {"amount": 7.5},
        "revenue.commercial.1.amount": {"amount": 40},
        "revenue.commercial.2.amount": {"amount": 12.5},
        "revenue.rinse_wf.amount": {"amount": 999},
    }
    rev = extract_other_revenue(lines)
    assert rev["self_service"] == 30.25
    assert rev["drop_off"] == 12.5
    assert rev["dhs"] == 52.5


def test_labor_hours_from_time_management_segments_not_scan_gaps():
    day_start = datetime(2026, 8, 15, 0, 0, 0)
    clip_end = datetime(2026, 8, 15, 16, 0, 0)
    segs = [
        {
            "user_id": 1,
            "category_code": "RINSE_WF",
            "started_at": datetime(2026, 8, 15, 8, 0, 0),
            "ended_at": datetime(2026, 8, 15, 12, 0, 0),
        },
        {
            "user_id": 2,
            "category_code": "RINSE_HD",
            "started_at": datetime(2026, 8, 15, 9, 0, 0),
            "ended_at": datetime(2026, 8, 15, 11, 0, 0),
        },
        {
            "user_id": 3,
            "category_code": "DROP_OFF",
            "started_at": datetime(2026, 8, 15, 10, 0, 0),
            "ended_at": datetime(2026, 8, 15, 11, 30, 0),
        },
        {
            "user_id": 4,
            "category_code": "DHS",
            "started_at": datetime(2026, 8, 15, 12, 0, 0),
            "ended_at": None,
        },
    ]
    labor = extract_labor_kpis(
        segs,
        day_start=day_start,
        clip_end=clip_end,
        rates_by_user={1: 20.0, 2: 18.0, 3: 16.0, 4: 15.0},
    )
    assert labor["rinse_wf_hours"] == 4.0
    assert labor["rinse_hd_hours"] == 2.0
    assert labor["drop_off_hours"] == 1.5
    assert labor["dhs_hours"] == 4.0
    assert labor["total_hours"] == 11.5
    assert labor["rinse_wf_dollars"] == 80.0
    assert labor["total_dollars"] == 80.0 + 36.0 + 24.0 + 60.0


def test_supplies_extract_usage_only_no_order_rows():
    report = {
        "orders": [{"order_id": "X", "supplies_used": ["Tide"]}],
        "usage_by_supply": {
            "Tide": {"orders": 10, "doses": 12, "ounces": 24.0},
            "Downy": {"orders": 4, "doses": 4, "ounces": 4.0},
            "OxiClean": {"orders": 2, "doses": 2, "ounces": 2.0},
            "All Free & Clear": {"orders": 1, "doses": 1, "ounces": 2.0},
        },
        "rush_filtering_supported": False,
        "rush_filtering_reason": "supply_usage_engine_has_no_rush_status",
    }
    supplies = extract_supplies(report)
    assert supplies["Tide"]["ounces"] == 24.0
    assert supplies["cost_available"] is False
    assert supplies["cost"] is None
    assert supplies["available"] is True
    assert supplies["rush_filtering_supported"] is False
    assert "orders" not in supplies["Tide"]


def test_review_does_not_fake_specialty_vs_portal_split():
    review = extract_review({"review_required_count": 5}, _headline())
    assert review["split_available"] is False
    assert review["review_required"] == 5
    assert review["specialty_items"] is None
    assert review["missing_from_portal"] is None


def test_compact_payload_uses_upstream_builders_and_strips_collections():
    clear_management_today_cache()
    day = date(2026, 8, 15)
    headline = _headline()
    hd_totals = {
        "complete": 9,
        "complete_total_items": 48,
        "complete_hd_revenue": 210.5,
        "not_recorded": 4,
        "partially_recorded": 1,
        "orphan_production_facts": [{"bag_id": "X"}],
    }
    pound_totals = {
        "today_wf_completed_pounds": 1940.25,
        "included_bags": [{"bag_id": "Z"}],
        "missing_post_bags": [],
    }
    supply_report = {
        "orders": [{"order_id": "BAG1"}],
        "usage_by_supply": {
            "Tide": {"orders": 3, "doses": 3, "ounces": 6.0},
            "Downy": {"orders": 0, "doses": 0, "ounces": 0.0},
            "OxiClean": {"orders": 0, "doses": 0, "ounces": 0.0},
            "All Free & Clear": {"orders": 0, "doses": 0, "ounces": 0.0},
        },
    }

    with patch("backend.management_today._load_headline", return_value=({"review_required_count": 5}, headline)), patch(
        "backend.management_today._load_wf_lbs", return_value=1940.25
    ), patch(
        "backend.management_today.load_wf_day_weight_totals",
        return_value={
            "pre_lbs": 2000.0,
            "post_lbs": 1940.25,
            "pre_weight_lbs": 2000.0,
            "post_weight_lbs": 1940.25,
            "pre_weight_bag_count": 97,
            "post_weight_bag_count": 70,
            "rush_filtering_supported": True,
            "source": "rinse_shift_monitor_day_bags.pre_weight_lbs/post_weight_lbs",
            "by_rush": {
                "all": {
                    "pre_lbs": 2000.0,
                    "post_lbs": 1940.25,
                    "pre_weight_lbs": 2000.0,
                    "post_weight_lbs": 1940.25,
                    "pre_weight_bag_count": 97,
                    "post_weight_bag_count": 70,
                },
                "rush": {
                    "pre_lbs": 1500.0,
                    "post_lbs": 1400.0,
                    "pre_weight_lbs": 1500.0,
                    "post_weight_lbs": 1400.0,
                    "pre_weight_bag_count": 60,
                    "post_weight_bag_count": 56,
                },
                "non_rush": {
                    "pre_lbs": 500.0,
                    "post_lbs": 540.25,
                    "pre_weight_lbs": 500.0,
                    "post_weight_lbs": 540.25,
                    "pre_weight_bag_count": 37,
                    "post_weight_bag_count": 14,
                },
            },
        },
    ), patch(
        "backend.management_today._load_hd_totals", return_value=hd_totals
    ), patch(
        "backend.management_today._load_drc_lines",
        return_value={
            "revenue.self_service.cash": {"amount": 11},
            "revenue.self_service.card": {"amount": 9},
            "revenue.drop_off.cash": {"amount": 4},
            "revenue.drop_off.card": {"amount": 6},
            "revenue.commercial.8.amount": {"amount": 33},
        },
    ), patch(
        "backend.management_today._load_labor_segments",
        return_value=[
            {
                "user_id": 1,
                "category_code": "RINSE_WF",
                "started_at": datetime(2026, 8, 15, 8, 0, 0),
                "ended_at": datetime(2026, 8, 15, 10, 0, 0),
            }
        ],
    ), patch(
        "backend.management_today._load_labor_rates", return_value={1: 20.0}
    ), patch(
        "backend.management_today._load_supplies", return_value=extract_supplies(supply_report)
    ), patch(
        "backend.management_today.business_today", return_value=day
    ), patch(
        "backend.management_today.business_now", return_value=datetime(2026, 8, 15, 16, 12, 0)
    ):
        payload = build_management_today_payload(object(), 3, day, bypass_cache=True)

    assert payload["wf"]["bags"] == 97
    assert payload["wf"]["lbs_processed"] == 1940.25
    assert payload["wf"]["completed"] == 70
    assert payload["hd"]["completed_orders"] == 12
    assert payload["hd"]["items"] == 48
    assert payload["hd"]["revenue"] == 210.5
    assert payload["other_revenue"]["self_service"] == 20.0
    assert payload["other_revenue"]["drop_off"] == 10.0
    assert payload["other_revenue"]["dhs"] == 33.0
    assert payload["labor"]["rinse_wf_hours"] == 2.0
    assert payload["labor"]["total_dollars"] == 40.0
    assert payload["supplies"]["Tide"]["ounces"] == 6.0
    assert payload["review"]["review_required"] == 5
    assert payload["review"]["split_available"] is False
    rinse = payload["rinse"]
    assert rinse["segments"]["wf"]["total_workload"] == 97
    assert rinse["segments"]["wf"]["completed"] == 70
    assert rinse["segments"]["wf"]["pending"] == 1
    assert rinse["segments"]["wf"]["exceptions"]["review_required"] == 26
    assert "bag_ids" not in rinse["segments"]["wf"]
    assert rinse["specialty_metrics"]["wf"]["rejected_orders"] == {"count": 1}
    assert rinse["specialty_metrics"]["wf"]["comforter_orders"] == {"count": 4}
    assert "order_ids" not in rinse["specialty_metrics"]["wf"]["comforter_orders"]
    assert rinse["hd_dashboard_totals"]["total_hd_orders"] == 13
    assert rinse["weight_totals"]["pre_lbs"] == 2000.0
    assert rinse["weight_totals"]["post_lbs"] == 1940.25
    assert_compact_today_payload(payload)
    dumped = str(payload)
    assert "SHOULD_NOT_LEAK" not in dumped
    assert "orphan_production_facts" not in dumped
    assert pound_totals["included_bags"][0]["bag_id"] not in dumped


def test_wf_lbs_prefers_persisted_daily_ops_pounds():
    class Cur:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return {"today_wf_completed_pounds": 12.5}

    with patch("backend.daily_operations.daily_operations_enabled_for_org", return_value=True), patch(
        "backend.daily_operations.ensure_daily_operations_tables"
    ), patch(
        "backend.management_today.table_exists", return_value=True
    ), patch(
        "backend.daily_operations.compute_day_wf_pound_totals"
    ) as compute:
        from backend.management_today import _load_wf_lbs

        assert _load_wf_lbs(Cur(), 3, date(2026, 8, 15)) == 12.5
        compute.assert_not_called()


def test_today_cache_returns_same_scalars_without_rebuild():
    clear_management_today_cache()
    day = date(2026, 8, 14)
    with patch("backend.management_today._load_headline", return_value=({"review_required_count": 1}, _headline())) as hl, patch(
        "backend.management_today._load_wf_lbs", return_value=100.0
    ), patch(
        "backend.management_today.load_wf_day_weight_totals",
        return_value={
            "pre_lbs": 110.0,
            "post_lbs": 100.0,
            "pre_weight_lbs": 110.0,
            "post_weight_lbs": 100.0,
            "pre_weight_bag_count": 10,
            "post_weight_bag_count": 8,
            "rush_filtering_supported": True,
            "source": "rinse_shift_monitor_day_bags.pre_weight_lbs/post_weight_lbs",
            "by_rush": {
                "all": {
                    "pre_lbs": 110.0,
                    "post_lbs": 100.0,
                    "pre_weight_lbs": 110.0,
                    "post_weight_lbs": 100.0,
                    "pre_weight_bag_count": 10,
                    "post_weight_bag_count": 8,
                },
                "rush": {
                    "pre_lbs": None,
                    "post_lbs": None,
                    "pre_weight_lbs": None,
                    "post_weight_lbs": None,
                    "pre_weight_bag_count": 0,
                    "post_weight_bag_count": 0,
                },
                "non_rush": {
                    "pre_lbs": None,
                    "post_lbs": None,
                    "pre_weight_lbs": None,
                    "post_weight_lbs": None,
                    "pre_weight_bag_count": 0,
                    "post_weight_bag_count": 0,
                },
            },
        },
    ), patch(
        "backend.management_today._load_hd_totals", return_value={}
    ), patch(
        "backend.management_today._load_drc_lines", return_value={}
    ), patch(
        "backend.management_today._load_labor_segments", return_value=[]
    ), patch(
        "backend.management_today._load_labor_rates", return_value={}
    ), patch(
        "backend.management_today._load_supplies",
        return_value=extract_supplies({"usage_by_supply": {}}),
    ), patch(
        "backend.management_today.business_today", return_value=date(2026, 8, 15)
    ), patch(
        "backend.management_today.business_now", return_value=datetime(2026, 8, 15, 9, 0, 0)
    ):
        first = build_management_today_payload(object(), 3, day, bypass_cache=True)
        second = build_management_today_payload(object(), 3, day, bypass_cache=False)
    assert second["wf"]["bags"] == first["wf"]["bags"]
    assert second["_meta"]["cached"] is True
    assert hl.call_count == 1


def test_extract_rinse_step1_keeps_shift_analysis_counts_without_ids():
    rinse = extract_rinse_step1(_headline(), {"complete_total_items": 48, "complete_hd_revenue": 210.5}, {
        "status": "OPEN",
        "review_required_count": 27,
    })
    wf = rinse["segments"]["wf"]
    assert wf["total_workload"] == 97
    assert wf["completed"] == 70
    assert wf["pending"] == 1
    assert wf["exceptions"]["review_required"] == 26
    assert "bag_ids" not in wf
    assert rinse["specialty_metrics"]["wf"]["comforter_orders"]["count"] == 4
    assert rinse["specialty_metrics"]["wf"]["bath_mat_orders"]["count"] == 1
    assert rinse["specialty_metrics"]["wf"]["rejected_orders"]["count"] == 1
    assert rinse["specialty_metrics"]["wf_rush"]["rejected_orders"]["count"] == 1
    assert rinse["hd_dashboard_totals"]["total_hd_orders"] == 13
    assert rinse["hd_dashboard_totals"]["completed"] == 12
    assert rinse["hd_dashboard_totals"]["review_required"] == 1
    assert_compact_today_payload({"rinse": rinse})
