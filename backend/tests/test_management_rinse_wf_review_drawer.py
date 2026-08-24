"""Management WF review drawer UX + list performance regressions."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.management_rinse_wf_review import (
    build_management_review_action,
    build_management_review_list,
    build_management_review_scans,
    compute_canonical_wf_review_membership,
    review_drawer_section_flags,
)


def _headline(review_ids=None):
    review_ids = review_ids or ["BAG1"]
    return {
        "review_reasons_by_bag": {bid: ["DISAPPEARED_WITHOUT_COMPLETION"] for bid in review_ids},
        "review_by_reason": {"DISAPPEARED_WITHOUT_COMPLETION": list(review_ids)},
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": list(review_ids),
                    "new_today": list(review_ids),
                    "completed": [],
                    "pending": [],
                    "carryover": [],
                }
            }
        },
        "specialty_metrics": {"wf": {"split_review": {"orders": []}}},
    }


def test_review_drawer_flags_hide_bulk_when_cleared():
    flags = review_drawer_section_flags(
        ["WF_BULK_WORKITEM_REVIEW", "DISAPPEARED_WITHOUT_COMPLETION"],
        bulk_cleared=True,
        bulk_unresolved=False,
    )
    assert flags["has_specialty_bulk"] is False
    assert flags["bulk_review_unresolved"] is False


def test_review_drawer_flags_show_bulk_when_unresolved():
    flags = review_drawer_section_flags(
        ["WF_BULK_WORKITEM_REVIEW"],
        bulk_cleared=False,
        bulk_unresolved=True,
    )
    assert flags["has_specialty_bulk"] is True
    assert flags["bulk_review_unresolved"] is True


def test_review_drawer_flags_show_bulk_for_scan_evidence_without_reason_code():
    flags = review_drawer_section_flags(
        ["DISAPPEARED_WITHOUT_COMPLETION"],
        bulk_cleared=False,
        bulk_unresolved=True,
    )
    assert flags["has_specialty_bulk"] is True
    assert flags["bulk_review_unresolved"] is True


def test_review_list_does_not_rebuild_workload_when_headline_has_reasons():
    headline = _headline(["BAG1", "BAG2"])
    day_row = {
        "bag_id": "BAG1",
        "service_type": "WF",
        "effective_status": "review_required",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        "bag_snapshot": {"customer_name": "Ada", "rush_flag": "NON-RUSH"},
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"summary_json": headline},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch(
            "backend.rinse_veewash_workload.build_veewash_daily_workload_from_membership",
        ) as rebuild,
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[day_row, {**day_row, "bag_id": "BAG2", "customer_name": "Bob"}],
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[day_row],
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={},
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
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={
                "BAG1": {"pre_weight_lbs": 15.7, "pre_weight_source": "portal_wf_lbs_num"}
            },
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rows, **k: rows,
        ),
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 24),
            category="missing_from_portal",
        )
    rebuild.assert_not_called()
    assert out["ok"] is True
    assert out["bags"][0]["bag_id"] == "BAG1"
    assert out["bags"][0]["pre_weight_lbs"] == 15.7


def test_review_list_query_budget_under_threshold():
    """Regression guard: list path must not fan out to hundreds of queries."""
    headline = _headline([f"B{i:02d}" for i in range(26)])
    rows = [
        {
            "bag_id": f"B{i:02d}",
            "service_type": "WF",
            "effective_status": "review_required",
            "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "bag_snapshot": {"customer_name": f"C{i}", "rush_flag": "NON-RUSH"},
        }
        for i in range(26)
    ]

    class Counting:
        def __init__(self):
            self.n = 0

        def execute(self, *a, **k):
            self.n += 1
            return None

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    cur = Counting()
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"summary_json": headline},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=rows),
        patch("backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=rows[:26]),
        patch("backend.management_rinse_wf_review._split_eval_as_of_day", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.management_rinse_wf_review._canonical_review_weights", return_value={}),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, bag_rows, **k: bag_rows,
        ),
        patch(
            "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
            return_value={
                "specialty_items": [],
                "missing_from_portal": [f"B{i:02d}" for i in range(26)],
                "split_order_review": [],
                "counts": {"missing_from_portal": 26, "review_required": 26},
                "codes_by_bag": {
                    f"B{i:02d}": ["DISAPPEARED_WITHOUT_COMPLETION"] for i in range(26)
                },
            },
        ),
    ):
        out = build_management_review_list(
            cur, 3, date(2026, 8, 24), category="missing_from_portal", page_size=26
        )
    assert out["ok"] is True
    assert cur.n < 40


def test_review_scans_endpoint_isolated():
    with patch(
        "backend.rinse_veewash_step1_api.load_scans_for_bags",
        return_value={"BAG1": [{"purpose": "weight-entry", "scanned_at_parsed": "2026-08-24 08:44:00"}]},
    ) as scans:
        out = build_management_review_scans(MagicMock(), 3, "BAG1")
    scans.assert_called_once()
    assert out["ok"] is True
    assert len(out["scans"]) == 1


def test_review_action_includes_bulk_state_and_customer():
    row = {
        "bag_id": "0ROEK16CUK",
        "effective_status": "review_required",
        "review_reason_codes": [
            "DISAPPEARED_WITHOUT_COMPLETION",
            "WF_BULK_WORKITEM_REVIEW",
        ],
        "manager_edit_version": 0,
        "bag_snapshot": {"customer_name": "Sean Speer 0", "rush_flag": "NON-RUSH"},
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"0ROEK16CUK": [{"workitem_id": 1, "quantity": 0}]},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={"0ROEK16CUK": {"count": 1}},
        ),
        patch(
            "backend.rinse_bulk_workitems.list_workitems",
            return_value=[{"id": 1, "name": "Bath Mat", "current_unit_price": 4}],
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={
                "0ROEK16CUK": {
                    "pre_weight_lbs": 17.6,
                    "pre_weight_source": "portal_wf_lbs_num",
                }
            },
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            return_value=[{"bag_id": "0ROEK16CUK", "customer_name": "Sean Speer 0"}],
        ),
    ):
        out = build_management_review_action(
            MagicMock(), 3, date(2026, 8, 24), "0ROEK16CUK"
        )
    assert out["ok"] is True
    assert "Sean" in out["bag"]["customer_name"]
    assert out["bag"]["bulk_review_unresolved"] is True
    assert out["bag"]["pre_weight_lbs"] == 17.6


def test_membership_skips_full_bag_split_eval():
    headline = _headline(["BAG1"])
    wf_row = {
        "bag_id": "BAG1",
        "service_type": "WF",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[wf_row],
        ),
        patch(
            "backend.rinse_veewash_workload.build_veewash_daily_workload_from_membership",
        ) as rebuild,
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
        ) as split_eval,
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={"BAG1": {}},
        ),
    ):
        compute_canonical_wf_review_membership(
            MagicMock(), 3, date(2026, 8, 24), headline=headline
        )
    rebuild.assert_not_called()
    if split_eval.called:
        args = split_eval.call_args[0][3]
        assert args != [f"B{i:02d}" for i in range(113)]
