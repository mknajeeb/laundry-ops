"""HD date-scoped / no-carryover + specialty metrics acceptance tests.

WF and Employee Productivity business logic are not exercised here beyond asserting
HD presentation does not mutate WF segment bag lists.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_hd_day_metrics import (
    build_day_specialty_metrics,
    is_canonical_rejected,
    normalize_specialty_item_name,
    specialty_order_ids_from_summary,
)
from backend.rinse_hd_day_presentation import (
    finalize_hd_step1_summary,
    strip_hd_carryover_from_summary,
)
from backend.rinse_scan_freshness import build_scan_data_freshness, freshness_from_day_and_presence
from backend.rinse_veewash_day_membership import INCLUSION_ADDED_LATER, INCLUSION_BASELINE


def _seg(new, carry, completed=None, pending=None, review=None):
    completed = completed or []
    pending = pending or []
    review = review or []
    return {
        "new_today": len(new),
        "carryover": len(carry),
        "active_workload": len(new) + len(carry),
        "total_workload": len(new) + len(carry),
        "completed": len(completed),
        "pending": len(pending),
        "exceptions": {
            "review_required": len(review),
            "disappeared_without_completion": len(review),
            "total": len(review),
        },
        "bag_ids": {
            "new_today": list(new),
            "carryover": list(carry),
            "completed": list(completed),
            "pending": list(pending),
            "review_required": list(review),
            "disappeared_without_completion": list(review),
        },
    }


def _summary_with_hd_carryover():
    wf_new = ["WF01", "WF02"]
    hd_new = ["HDNEW1"]
    hd_carry = ["HDCARRY1", "HDCARRY2"]
    return {
        "selected_date_et": "2026-07-25",
        "segments": {
            "wf": _seg(wf_new, []),
            "hd": _seg(hd_new, hd_carry, pending=["HDNEW1"], review=list(hd_carry)),
            "hd_rush": _seg([], hd_carry[:1], review=hd_carry[:1]),
            "hd_non_rush": _seg(hd_new, hd_carry[1:], pending=["HDNEW1"], review=hd_carry[1:]),
            "all": _seg(wf_new + hd_new, hd_carry, pending=["HDNEW1"], review=list(hd_carry)),
            "rush": _seg([], hd_carry[:1], review=hd_carry[:1]),
            "non_rush": _seg(wf_new + hd_new, hd_carry[1:], pending=["HDNEW1"], review=hd_carry[1:]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(wf_new, []),
        },
        "membership": {
            "baseline_bag_ids": ["WF01", "WF02", "HDNEW1"],
            "added_later_bag_ids": ["HDADD1"],
            "membership": {
                "WF01": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "WF"},
                "WF02": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "WF"},
                "HDNEW1": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "HD"},
                "HDADD1": {
                    "inclusion_source": INCLUSION_ADDED_LATER,
                    "service_type_portal": "HD",
                },
            },
        },
    }


def test_a_prior_shift_open_does_not_carry_hd_into_next_day():
    """Test A — Jul 25 HD membership excludes Jul 24 HD carryover bags."""
    summary = _summary_with_hd_carryover()
    # Simulate an ADDED_LATER HD also present in HD new_today (should be stripped).
    summary["segments"]["hd"]["bag_ids"]["new_today"] = ["HDNEW1", "HDADD1"]
    summary["segments"]["hd"]["new_today"] = 2
    summary["segments"]["hd"]["active_workload"] = 4
    out = finalize_hd_step1_summary(
        summary,
        selected_date_et=date(2026, 7, 25),
        membership=summary["membership"],
    )
    hd = out["segments"]["hd"]
    assert hd["carryover"] == 0
    assert hd["bag_ids"]["carryover"] == []
    assert "HDCARRY1" not in (hd["bag_ids"]["new_today"] + hd["bag_ids"]["review_required"])
    assert "HDCARRY2" not in (hd["bag_ids"]["new_today"] + hd["bag_ids"]["review_required"])
    assert "HDADD1" not in hd["bag_ids"]["new_today"]
    assert hd["bag_ids"]["new_today"] == ["HDNEW1"]
    # WF untouched
    assert out["segments"]["wf"]["bag_ids"]["new_today"] == ["WF01", "WF02"]
    assert out["segments"]["wf"]["carryover"] == 0


def test_b_historical_immutability_presentation_skips_prior_day():
    """Test B helper — prior-day read must not heal via should_apply when not today."""
    from backend.rinse_hd_day_presentation import should_apply_hd_presentation_on_read

    assert (
        should_apply_hd_presentation_on_read(
            selected_date_et=date(2026, 7, 24),
            today=date(2026, 7, 25),
            day_status="OPEN",
        )
        is False
    )


def test_c_hd_presentation_does_not_mutate_wf_lists():
    """Test C — WF bag lists identical before/after HD finalize."""
    summary = _summary_with_hd_carryover()
    before_wf = deepcopy(summary["segments"]["wf"])
    out = finalize_hd_step1_summary(
        summary,
        selected_date_et=date(2026, 7, 25),
        membership=summary["membership"],
    )
    assert out["segments"]["wf"] == before_wf


def test_d_specialty_card_count_equals_distinct_orders():
    """Test D — card count == distinct order numbers in drawer list."""
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).lower().split())
        if "from rinse_bag_bulk_workitems" in s:
            cursor.fetchall.return_value = [
                {"bag_id": "COMP01", "workitem_name_snapshot": "Comforter", "quantity": 2},
                {"bag_id": "COMP01", "workitem_name_snapshot": "Comforter", "quantity": 1},
                {"bag_id": "COMP02", "workitem_name_snapshot": "Comforters", "quantity": 1},
                {"bag_id": "BATH01", "workitem_name_snapshot": "Bath Mat", "quantity": 2},
            ]
        elif "from rinse_bag_registry" in s:
            cursor.fetchall.return_value = [
                {
                    "bag_id": "REJ001",
                    "completion_status": "REJECTED",
                    "completion_reason": "CREATE_ISSUE_NO_COMPLETION_PORTAL_DEPARTURE",
                    "completed_at": datetime(2026, 7, 24, 12, 0, 0),
                    "service_type": "WF",
                    "name_clean": "Acme",
                    "rush_type": "RUSH",
                },
                {
                    "bag_id": "REV001",
                    "completion_status": "REJECTED",
                    "completion_reason": "MISSING_FROM_LATEST_PORTAL_SCRAPE",
                    "completed_at": datetime(2026, 7, 24, 12, 0, 0),
                    "service_type": "HD",
                    "name_clean": "Gone",
                    "rush_type": "NON-RUSH",
                },
            ]
        elif "from rinse_cleaner_ticket_presence" in s:
            cursor.fetchall.return_value = []
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.rinse_hd_day_metrics.table_exists", return_value=True), patch(
        "backend.rinse_hd_day_metrics._load_split_orders_from_supply_usage",
        return_value={
            "SPLT01": {
                "order_id": "SPLT01",
                "split_order": True,
                "split_status": "confirmed",
                "split_confirmed": True,
                "washer_load_count": 2,
                "washer_racks": ["W-1", "W-2"],
                "customer": "Split Cust",
                "service_type": "WF",
            }
        },
    ):
        summary = {
            "segments": {
                "all": _seg(
                    ["COMP01", "COMP02", "BATH01", "REJ001", "REV001", "SPLT01"],
                    [],
                    review=["REV001"],
                ),
                "wf": _seg(["COMP01", "COMP02", "BATH01", "REJ001", "SPLT01"], []),
                "hd": _seg(["REV001"], [], review=["REV001"]),
            }
        }
        metrics = build_day_specialty_metrics(
            cursor, 3, date(2026, 7, 24), summary, service="all"
        )
    assert metrics["comforter_orders"]["count"] == 2
    assert metrics["comforter_orders"]["count"] == len(
        set(metrics["comforter_orders"]["order_ids"])
    )
    assert metrics["comforter_orders"]["orders"][0]["quantity"] == 3.0  # COMP01 2+1
    assert metrics["bath_mat_orders"]["count"] == 1
    assert metrics["rejected_orders"]["count"] == 1
    assert metrics["rejected_orders"]["order_ids"] == ["REJ001"]
    assert metrics["split_orders"]["count"] == 1
    assert metrics["split_orders"]["order_ids"] == ["SPLT01"]
    # Drawer id helper matches card.
    summary["specialty_metrics"] = {"all": metrics}
    assert specialty_order_ids_from_summary(
        summary, metric="comforter_orders", service="all"
    ) == ["COMP01", "COMP02"]
    assert specialty_order_ids_from_summary(
        summary, metric="split_orders", service="all"
    ) == ["SPLT01"]


def test_e_review_required_disappearance_not_rejected():
    """Test E — Review Required disappearance must not appear under Rejected."""
    assert is_canonical_rejected(
        completion_status="REJECTED",
        completion_reason="MISSING_FROM_LATEST_PORTAL_SCRAPE",
    ) is False
    assert is_canonical_rejected(
        completion_status="REJECTED",
        completion_reason="CREATE_ISSUE_NO_COMPLETION_PORTAL_DEPARTURE",
    ) is True
    assert is_canonical_rejected(completion_status="INCOMPLETE") is False


def test_f_next_day_scrape_does_not_flag_prior_day_freshness():
    """Test F — historical freshness ignores live next-day portal pipeline."""
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).lower().split())
        if "from rinse_bag_scan_events" in s and "max(scanned_at_parsed)" in s:
            cursor.fetchone.return_value = {"mx": datetime(2026, 7, 24, 18, 0, 0)}
        elif "from rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchone.return_value = {"finished_at": datetime(2026, 7, 24, 8, 0, 0)}
        else:
            cursor.fetchone.return_value = {}
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.rinse_veewash_workload.today_et", return_value=date(2026, 7, 25)):
        with patch("backend.ta_helpers.table_exists", return_value=True):
            out = freshness_from_day_and_presence(
                cursor,
                3,
                date(2026, 7, 24),
                day_meta={"last_sync_at": datetime(2026, 7, 24, 22, 0, 0)},
                pending_bag_ids=["PEND01"],
                sample_bag_ids=["PEND01"],
            )
    assert out["status"] == "ok"
    assert out["pending_trust"] == "trusted"
    assert out["portal_ahead_bag_count"] == 0
    assert out["trust_pending_from_missing_completion"] is True


def test_normalize_specialty_item_names():
    assert normalize_specialty_item_name("Comforter") == "comforter"
    assert normalize_specialty_item_name("Comforters") == "comforter"
    assert normalize_specialty_item_name("Bath Mat") == "bath_mat"
    assert normalize_specialty_item_name("Bath Mats") == "bath_mat"
    assert normalize_specialty_item_name("Bath-Mat") == "bath_mat"
    assert normalize_specialty_item_name("Jeans") is None


def test_strip_hd_carryover_leaves_wf_combined_carryover_if_wf_only():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], ["WCARRY1"]),
            "hd": _seg(["HD01"], ["HCARRY1"]),
            "all": _seg(["WF01", "HD01"], ["WCARRY1", "HCARRY1"]),
            "hd_rush": _seg([], ["HCARRY1"]),
            "hd_non_rush": _seg(["HD01"], []),
            "rush": _seg([], ["WCARRY1", "HCARRY1"]),
            "non_rush": _seg(["WF01", "HD01"], []),
            "wf_rush": _seg([], ["WCARRY1"]),
            "wf_non_rush": _seg(["WF01"], []),
        }
    }
    out = strip_hd_carryover_from_summary(summary)
    assert out["segments"]["hd"]["carryover"] == 0
    assert "HCARRY1" not in out["segments"]["all"]["bag_ids"]["carryover"]
    assert "WCARRY1" in out["segments"]["all"]["bag_ids"]["carryover"]
    assert out["segments"]["wf"]["bag_ids"]["carryover"] == ["WCARRY1"]


def test_build_scan_data_freshness_ok_shape():
    payload = build_scan_data_freshness(
        selected_date_et=date(2026, 7, 24),
        shift_last_sync_at=None,
        most_recent_persisted_scan_at=None,
    )
    assert payload["portal_ahead_bag_count"] == 0
    assert payload["pending_trust"] == "trusted"
