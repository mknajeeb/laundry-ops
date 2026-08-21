"""Prior-open exceptions must not inflate today's Management workload."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_shift_day import _apply_day_bag_statuses_to_headline
from backend.rinse_veewash_workload import classify_veewash_workload

D0 = date(2026, 8, 20)
D1 = date(2026, 8, 21)


def _pres(*, active=0, last_seen, bag_id="BAG0A"):
    ls = datetime(last_seen.year, last_seen.month, last_seen.day, 16, 0)
    return {
        "bag_id": bag_id,
        "active": active,
        "portal_status": "at_vendor",
        "service_type": "WF",
        "rush_flag": "RUSH",
        "last_seen_at": ls,
        "first_seen_at": ls,
    }


def _entry(d):
    return {"entry_date": d, "entry_source": "facility_dirty_scan", "entry_at": None}


def test_classifier_prior_open_not_in_later_day_workload():
    presence = {"BAG0A": _pres(active=0, last_seen=D0)}
    entry = {"BAG0A": _entry(D0)}
    out0 = classify_veewash_workload(
        selected_date_et=D0,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
        disappearance_state_by_bag={"BAG0A": "DISAPPEARED_WITHOUT_COMPLETION"},
    )
    out1 = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
        disappearance_state_by_bag={"BAG0A": "DISAPPEARED_WITHOUT_COMPLETION"},
    )
    assert out0["review_required"] == ["BAG0A"]
    assert out1["new_today"] == []
    assert out1["carryover"] == []
    assert out1["pending_end_of_date"] == []
    assert out1["disappeared_prior_open_exceptions"] == ["BAG0A"]
    assert out1["counts"]["total_active_workload"] == 0


def test_frozen_membership_does_not_force_prior_open_into_pending():
    from backend.rinse_veewash_workload import build_veewash_daily_workload_from_membership

    presence = {
        "BAG0A": _pres(active=0, last_seen=D0, bag_id="BAG0A"),
        "BAG0B": {
            "bag_id": "BAG0B",
            "active": 1,
            "portal_status": "at_vendor",
            "service_type": "WF",
            "rush_flag": "NON-RUSH",
            "last_seen_at": datetime(D1.year, D1.month, D1.day, 16, 0),
            "first_seen_at": datetime(D1.year, D1.month, D1.day, 16, 0),
        },
    }
    entry = {
        "BAG0A": _entry(D0),
        "BAG0B": _entry(D1),
    }

    with (
        patch(
            "backend.rinse_veewash_day_membership.build_append_only_membership",
            return_value={"ok": True, "membership": {}},
        ),
        patch("backend.rinse_veewash_workload.load_presence_orders", return_value=presence),
        patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value={},
        ),
        patch("backend.rinse_veewash_workload.load_first_dirty_scans", return_value={}),
        patch(
            "backend.rinse_veewash_workload.load_first_workitems_added_scans",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.build_service_entry_map",
            return_value=entry,
        ),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.build_disappearance_confirmation",
            return_value={
                "BAG0A": {"state": "DISAPPEARED_WITHOUT_COMPLETION"},
            },
        ),
        patch(
            "backend.rinse_veewash_review.expand_review_required",
            side_effect=lambda result, **kwargs: result,
        ),
        patch("backend.rinse_veewash_review.load_bag_weight_map", return_value={}),
        patch(
            "backend.rinse_veewash_review.load_registry_service_classification",
            return_value=({}, set()),
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_scan_freshness.load_last_scan_at_by_bag", return_value={}),
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={},
        ),
    ):
        result = build_veewash_daily_workload_from_membership(
            MagicMock(),
            3,
            selected_date_et=D1,
            frozen_member_ids=["BAG0A", "BAG0B"],
        )

    assert result["disappeared_prior_open_exceptions"] == ["BAG0A"]
    assert "BAG0A" not in result["new_today"]
    assert "BAG0A" not in result["pending_end_of_date"]
    assert result["new_today"] == ["BAG0B"]
    assert result["pending_end_of_date"] == ["BAG0B"]
    assert result["counts"]["total_workload"] == 1
    by_id = {r["bag_id"]: r for r in result["rows"]}
    assert by_id["BAG0A"]["final_bucket"] == "disappeared_prior_open_exception"
    assert by_id["BAG0A"].get("entry_class") in (None, "")
    assert "pending" in (
        by_id["BAG0B"].get("final_bucket") or by_id["BAG0B"].get("outcome") or ""
    )


def test_headline_drops_prior_open_from_workload_total():
    headline = {
        "segments": {
            "wf": {
                "total_workload": 3,
                "active_workload": 3,
                "completed": 0,
                "pending": 3,
                "exceptions": {"review_required": 0, "total": 0},
                "bag_ids": {
                    "new_today": ["PEND01", "PEND02", "XCPT01"],
                    "carryover": [],
                    "pending": ["PEND01", "PEND02", "XCPT01"],
                    "completed": [],
                    "review_required": [],
                },
            },
            "all": {
                "total_workload": 3,
                "active_workload": 3,
                "completed": 0,
                "pending": 3,
                "exceptions": {"review_required": 0, "total": 0},
                "bag_ids": {
                    "new_today": ["PEND01", "PEND02", "XCPT01"],
                    "carryover": [],
                    "pending": ["PEND01", "PEND02", "XCPT01"],
                    "completed": [],
                    "review_required": [],
                },
            },
        },
        "total_workload": 3,
        "pending": 3,
        "completed": 0,
    }
    status_by_bag = {
        "PEND01": {
            "effective_status": "pending",
            "service_type": "WF",
            "rush_status": None,
        },
        "PEND02": {
            "effective_status": "pending",
            "service_type": "WF",
            "rush_status": None,
        },
        "XCPT01": {
            "effective_status": "disappeared_prior_open_exception",
            "service_type": "WF",
            "rush_status": "RUSH",
        },
    }
    out = _apply_day_bag_statuses_to_headline(headline, status_by_bag)
    wf = out["segments"]["wf"]
    assert wf["total_workload"] == 2
    assert wf["pending"] == 2
    assert (wf.get("exceptions") or {}).get("review_required") == 0
    assert set(wf["bag_ids"]["pending"]) == {"PEND01", "PEND02"}
    assert "XCPT01" not in (wf["bag_ids"].get("new_today") or [])
    assert wf["total_workload"] == wf["completed"] + wf["pending"] + (
        wf.get("exceptions") or {}
    ).get("review_required", 0)
