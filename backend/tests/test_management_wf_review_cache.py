"""Review membership / DFP derived-cache reuse."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_wf_review_cache import (
    clear_wf_review_derived_cache,
    get_canonical_wf_review_membership_cached,
    get_qualified_disappeared_from_portal,
    reset_review_cache_stats,
    review_cache_stats,
)


def setup_function(_fn=None):
    clear_wf_review_derived_cache()
    reset_review_cache_stats()


def teardown_function(_fn=None):
    clear_wf_review_derived_cache()
    reset_review_cache_stats()


def test_dfp_compute_once_per_org_under_reuse():
    open_rows = [
        {
            "bag_id": "BAG1",
            "order_instance_id": 1,
            "cycle_anchor_at": datetime(2026, 9, 9, 22, 0),
            "completed_at": None,
        }
    ]
    payload = {
        "BAG1": {
            "bag_id": "BAG1",
            "reason_code": "DISAPPEARED_FROM_PORTAL",
        }
    }
    with patch(
        "backend.rinse_wf_disappeared_from_portal.qualify_disappeared_from_portal_bags",
        return_value=payload,
    ) as qualify:
        a = get_qualified_disappeared_from_portal(MagicMock(), 3, open_rows)
        b = get_qualified_disappeared_from_portal(MagicMock(), 3, open_rows)
    assert a == payload
    assert b == payload
    assert qualify.call_count == 1
    stats = review_cache_stats()
    assert stats["dfp_compute"] == 1
    assert stats["dfp_cache_hit"] == 1


def test_dfp_cache_isolated_by_org():
    with patch(
        "backend.rinse_wf_disappeared_from_portal.qualify_disappeared_from_portal_bags",
        side_effect=lambda *_a, **_k: {"X": {"bag_id": "X"}},
    ) as qualify:
        get_qualified_disappeared_from_portal(MagicMock(), 3, [])
        get_qualified_disappeared_from_portal(MagicMock(), 9, [])
    assert qualify.call_count == 2


def test_membership_cache_hit_skips_rebuild():
    membership = {
        "specialty_items": ["S1"],
        "missing_from_portal": ["M1"],
        "split_order_review": [],
        "manual_review": [],
        "unknown_review": [],
        "counts": {
            "specialty_items": 1,
            "missing_from_portal": 1,
            "split_order_review": 0,
            "manual_review": 0,
            "unknown_review": 0,
            "review_required": 2,
        },
        "reason_category_map": {},
        "precedence": "x",
        "employee_performance_hint": {},
        "codes_by_bag": {"M1": ["DISAPPEARED_FROM_PORTAL"]},
    }
    with patch(
        "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
        return_value=membership,
    ) as compute:
        a = get_canonical_wf_review_membership_cached(
            MagicMock(), 3, date(2026, 9, 12)
        )
        b = get_canonical_wf_review_membership_cached(
            MagicMock(), 3, date(2026, 9, 12)
        )
    assert a["missing_from_portal"] == ["M1"]
    assert b["missing_from_portal"] == ["M1"]
    assert compute.call_count == 1
    stats = review_cache_stats()
    assert stats["membership_compute"] == 1
    assert stats["membership_cache_hit"] == 1


def test_membership_cache_isolated_by_org_and_date():
    with patch(
        "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
        return_value={"counts": {}, "specialty_items": [], "missing_from_portal": []},
    ) as compute:
        get_canonical_wf_review_membership_cached(MagicMock(), 3, date(2026, 9, 12))
        get_canonical_wf_review_membership_cached(MagicMock(), 3, date(2026, 9, 11))
        get_canonical_wf_review_membership_cached(MagicMock(), 4, date(2026, 9, 12))
    assert compute.call_count == 3


def test_clear_management_today_cache_clears_review_derived():
    from backend.management_today import clear_management_today_cache

    with patch(
        "backend.rinse_wf_disappeared_from_portal.qualify_disappeared_from_portal_bags",
        return_value={"A": {"bag_id": "A"}},
    ):
        get_qualified_disappeared_from_portal(MagicMock(), 3, [])
    assert review_cache_stats()["dfp_compute"] == 1
    clear_management_today_cache(3, date(2026, 9, 12))
    with patch(
        "backend.rinse_wf_disappeared_from_portal.qualify_disappeared_from_portal_bags",
        return_value={"A": {"bag_id": "A"}},
    ) as qualify:
        get_qualified_disappeared_from_portal(MagicMock(), 3, [])
    assert qualify.call_count == 1


def test_list_path_reuses_membership_cache():
    """Category list must not recompute membership when cache is warm."""
    from backend.management_rinse_wf_review import build_management_review_list

    membership = {
        "specialty_items": [],
        "missing_from_portal": ["9B5V934T45"],
        "split_order_review": [],
        "manual_review": [],
        "unknown_review": [],
        "counts": {
            "specialty_items": 0,
            "missing_from_portal": 1,
            "split_order_review": 0,
            "manual_review": 0,
            "unknown_review": 0,
            "review_required": 1,
        },
        "reason_category_map": {},
        "precedence": "",
        "employee_performance_hint": {},
        "codes_by_bag": {"9B5V934T45": ["DISAPPEARED_FROM_PORTAL"]},
        "disposition": {"9B5V934T45": "missing_from_portal"},
    }
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
            return_value=membership,
        ) as compute,
        patch(
            "backend.management_rinse_wf_review.clear_stale_completed_wf_review_day_bag_codes",
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[
                {
                    "bag_id": "9B5V934T45",
                    "service_type": "WF",
                    "effective_status": "review_required",
                    "review_reason_codes": ["DISAPPEARED_FROM_PORTAL"],
                    "bag_snapshot": {"customer_name": "Shengyu Bai"},
                }
            ],
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
            side_effect=lambda *_a, **_k: [
                {"bag_id": "9B5V934T45", "customer_name": "Shengyu Bai"}
            ],
        ),
    ):
        # Warm cache via first call
        get_canonical_wf_review_membership_cached(cur, 3, date(2026, 9, 12))
        assert compute.call_count == 1
        out = build_management_review_list(
            cur, 3, date(2026, 9, 12), category="missing_from_portal"
        )
        # Second membership resolve must be cache hit
        assert compute.call_count == 1
    assert out.get("ok") is not False
    bags = out.get("bags") or []
    assert any(b.get("bag_id") == "9B5V934T45" for b in bags)
    hit = next(b for b in bags if b.get("bag_id") == "9B5V934T45")
    assert "DISAPPEARED_FROM_PORTAL" in (hit.get("reason_codes") or [])
    assert hit.get("short_reason") == "Disappeared From Portal"


def test_membership_prefers_day_bag_shell_over_full_workload_rebuild():
    """Empty headline reasons must not rebuild full Veewash membership."""
    from backend.management_rinse_wf_review import compute_canonical_wf_review_membership

    day = date(2026, 9, 12)
    wf_row = {
        "bag_id": "COMP1",
        "service_type": "WF",
        "effective_status": "completed",
        "new_or_carryover": "new_today",
        "review_reason_codes": [],
    }
    membership_shell = {
        "specialty_items": ["COMP1"],
        "missing_from_portal": [],
        "split_order_review": [],
        "manual_review": [],
        "unknown_review": [],
        "counts": {
            "specialty_items": 1,
            "missing_from_portal": 0,
            "split_order_review": 0,
            "manual_review": 0,
            "unknown_review": 0,
            "review_required": 1,
        },
        "reason_category_map": {},
        "precedence": "specialty>missing>manual",
        "employee_performance_hint": {},
        "codes_by_bag": {"COMP1": ["WF_BULK_WORKITEM_REVIEW"]},
        "disposition": {"COMP1": "specialty_items"},
        "excluded": [],
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[wf_row],
        ),
        patch(
            "backend.management_rinse_wf_review._fresh_review_reasons_from_day_bags",
            return_value={"COMP1": ["WF_BULK_WORKITEM_REVIEW"]},
        ) as seed,
        patch(
            "backend.rinse_veewash_workload.build_veewash_daily_workload_from_membership",
        ) as full_rebuild,
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=[],
        ),
        patch(
            "backend.management_wf_review_cache.get_qualified_disappeared_from_portal",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"COMP1": [{"qty": 1}]},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={"COMP1": {"count": 1}},
        ),
        patch(
            "backend.rinse_bulk_workitems.bag_bulk_review_cleared",
            return_value=False,
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
    ):
        out = compute_canonical_wf_review_membership(
            MagicMock(),
            3,
            day,
            headline={"review_reasons_by_bag": {}, "review_by_reason": {}},
        )
    seed.assert_called_once()
    full_rebuild.assert_not_called()
    assert "COMP1" in (out.get("specialty_items") or [])


def test_secondary_counts_reuse_same_membership_as_drawer():
    """Secondary review counts and drawer list share one membership compute."""
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    membership = {
        "specialty_items": ["S1"],
        "missing_from_portal": ["9B5V934T45"],
        "split_order_review": ["P1"],
        "manual_review": [],
        "unknown_review": [],
        "counts": {
            "specialty_items": 1,
            "missing_from_portal": 1,
            "split_order_review": 1,
            "manual_review": 0,
            "unknown_review": 0,
            "review_required": 3,
        },
        "reason_category_map": {"specialty_items": ["WF_BULK_WORKITEM_REVIEW"]},
        "precedence": "split>specialty>missing>manual",
        "employee_performance_hint": {},
        "codes_by_bag": {
            "S1": ["WF_BULK_WORKITEM_REVIEW"],
            "9B5V934T45": ["DISAPPEARED_FROM_PORTAL"],
            "P1": ["SPLIT_ORDER_REVIEW"],
        },
        "disposition": {
            "S1": "specialty_items",
            "9B5V934T45": "missing_from_portal",
            "P1": "split_order_review",
        },
    }
    cur = MagicMock()
    with (
        patch(
            "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
            return_value=membership,
        ) as compute,
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value={}),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.clear_stale_completed_wf_review_day_bag_codes",
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[
                {
                    "bag_id": "S1",
                    "service_type": "WF",
                    "effective_status": "completed",
                    "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
                    "bag_snapshot": {},
                }
            ],
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch(
            "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
            side_effect=lambda *_a, **_k: [{"bag_id": "S1", "customer_name": "X"}],
        ),
    ):
        counts = review_category_count_payload(
            {}, cursor=cur, organization_id=3, selected_date_et=date(2026, 9, 12)
        )
        assert compute.call_count == 1
        build_management_review_list(
            cur, 3, date(2026, 9, 12), category="specialty_items"
        )
        assert compute.call_count == 1
    assert counts["specialty_items"] == 1
    assert counts["missing_from_portal"] == 1
    assert counts["split_order_review"] == 1
    assert counts["precedence"] == membership["precedence"]
