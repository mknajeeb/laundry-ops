"""
Integration: Step-1 and At Vendor both consume shared rinse_cycle_boundary.

Replaces the earlier clean-rack-oriented cycle experiment.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, _evaluate_bag_as_of
from backend.rinse_cycle_boundary import (
    COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
    resolve_current_cycle,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_veewash_shift_day import _bag_rows_from_workload
from backend.rinse_veewash_workload import (
    _cycle_anchored_completion_for_day,
    classify_veewash_workload,
    load_canonical_completions_v2,
)

DAY = date(2026, 7, 27)


def _ev(*, ts, purpose=None, rack=None, user=None, weight=None):
    return {
        "scanned_at_parsed": ts,
        "purpose": purpose,
        "rack": rack,
        "user_name": user,
        "weight_lbs": weight,
    }


def _resend_post_review_timeline():
    """Old clean + weight, then Jul 27 resend with Dirty → review → weight (no Clean required)."""
    return [
        _ev(
            ts=datetime(2026, 6, 29, 16, 45, 0),
            purpose="move-bag",
            rack="VeeWash Clean",
            user="Old",
        ),
        _ev(ts=datetime(2026, 6, 29, 16, 45, 0), purpose="weight-entry", user="Old", weight=12.0),
        _ev(ts=datetime(2026, 7, 27, 5, 10, 0), purpose="sent-to-vendor", user="Driver"),
        _ev(
            ts=datetime(2026, 7, 27, 6, 16, 0),
            purpose="move-bag",
            rack="VeeWash Dirty",
            user="Ops",
        ),
        _ev(ts=datetime(2026, 7, 27, 6, 19, 0), purpose="weight-entry", user="Early", weight=10.0),
        _ev(
            ts=datetime(2026, 7, 27, 14, 31, 0),
            purpose="garments-reviewed",
            user="Yessenia (Veewash)",
        ),
        _ev(
            ts=datetime(2026, 7, 27, 14, 58, 0),
            purpose="weight-entry",
            user="Yessenia (Veewash)",
            weight=9.5,
        ),
    ]


def test_step1_helper_uses_shared_cycle_resolver_not_lifetime_clean():
    tl = _resend_post_review_timeline()
    out = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    assert out is not None
    assert out["completion_at"] == datetime(2026, 7, 27, 14, 58, 0)
    assert out["completed_by"] == "Yessenia (Veewash)"
    assert out["completion_source"] == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out["via_clean_rack"] is False
    assert out["cycle_anchor_at"] == datetime(2026, 7, 27, 5, 10, 0)
    assert out["entry_at"] == datetime(2026, 7, 27, 6, 16, 0)


def test_at_vendor_uses_shared_cycle_resolver():
    tl = _resend_post_review_timeline()
    status, signal, comp_ts, anchor, _ = _evaluate_bag_as_of(
        tl, service_type="WF", as_of_end=naive_et_day_end_inclusive(DAY)
    )
    assert status == AV_STATUS_COMPLETED
    assert signal == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert comp_ts == datetime(2026, 7, 27, 14, 58, 0)
    assert anchor == datetime(2026, 7, 27, 5, 10, 0)


def test_step1_and_at_vendor_agree():
    tl = _resend_post_review_timeline()
    step = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    status, signal, comp_ts, anchor, _ = _evaluate_bag_as_of(
        tl, service_type="WF", as_of_end=naive_et_day_end_inclusive(DAY)
    )
    shared = resolve_current_cycle(tl, selected_date_et=DAY)
    assert step["completion_at"] == comp_ts == shared.completion_at
    assert step["cycle_anchor_at"] == anchor == shared.cycle_anchor_at
    assert signal == shared.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT


def test_load_canonical_with_selected_date_ignores_lifetime_clean():
    tl = _resend_post_review_timeline()
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [
            {
                "bag_id": "BAG1",
                "rack": e.get("rack"),
                "purpose": e.get("purpose"),
                "scanned_at_parsed": e["scanned_at_parsed"],
                "user_name": e.get("user_name"),
                "weight_lbs": e.get("weight_lbs"),
                "source_filename": None,
                "raw_json": None,
            }
            for e in tl
        ],
        [],  # no manager corrections
    ]
    # table_exists checks
    with patch("backend.rinse_veewash_workload.table_exists", return_value=True):
        out = load_canonical_completions_v2(
            cursor,
            3,
            ["BAG1"],
            selected_date_et=DAY,
            service_type_by_bag={"BAG1": "WF"},
            entry_racks=["VeeWash Dirty", "Rinse Zipvan"],
        )
    assert "BAG1" in out
    assert out["BAG1"]["completion_at"] == datetime(2026, 7, 27, 14, 58, 0)
    assert out["BAG1"]["completion_source"] == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out["BAG1"]["via_clean_rack"] is False


def test_no_clean_scan_required_for_completion():
    tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 27, 14, 0, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 27, 14, 30, 0), purpose="weight-entry", user="Rev", weight=8.0),
    ]
    assert not any("clean" in str(e.get("rack") or "").lower() for e in tl)
    step = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    assert step is not None
    status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
        tl, service_type="WF", as_of_end=naive_et_day_end_inclusive(DAY)
    )
    assert status == AV_STATUS_COMPLETED
    assert comp_ts == step["completion_at"]


def test_ordinary_first_cycle_bag_still_completes():
    tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 5, 30, 0), purpose="move-bag", rack="Rinse Zipvan"),
        _ev(ts=datetime(2026, 7, 27, 10, 0, 0), purpose="garments-reviewed", user="A"),
        _ev(ts=datetime(2026, 7, 27, 10, 15, 0), purpose="weight-entry", user="A", weight=7.0),
    ]
    out = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    assert out["entry_rack"] == "Rinse Zipvan"
    assert out["completion_at"] == datetime(2026, 7, 27, 10, 15, 0)


def test_classify_marks_resend_completed_not_completed_before_selected_date():
    presence = {
        "BAG1": {
            "bag_id": "BAG1",
            "active": 1,
            "portal_status": "at_vendor",
            "service_type": "WF",
            "rush_flag": "RUSH",
            "last_seen_at": datetime(2026, 7, 27, 20, 0, 0),
        }
    }
    entry = {
        "BAG1": {
            "entry_date": DAY,
            "entry_at": datetime(2026, 7, 27, 6, 16, 0),
            "entry_source": "facility_dirty_scan",
        }
    }
    completion = {
        "BAG1": {
            "completion_at": datetime(2026, 7, 27, 14, 58, 0),
            "completion_date": DAY,
            "completed_by": "Yessenia (Veewash)",
            "completion_source": COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
        }
    }
    result = classify_veewash_workload(
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    assert "BAG1" in result["completed_on_date"]
    row = next(r for r in result["rows"] if r["bag_id"] == "BAG1")
    assert row["outcome"] == "completed"
    assert row.get("reason") != "completed_before_selected_date"


def test_persisted_day_bag_fields_agree_with_resolver():
    wl = {
        "rows": [
            {
                "bag_id": "BAG1",
                "service_type": "WF",
                "rush_flag": "RUSH",
                "entry_class": "new_today",
                "entry_source": "facility_dirty_scan",
                "entry_at": datetime(2026, 7, 27, 6, 16, 0),
                "outcome": "completed",
                "final_bucket": "new_today_completed",
                "completion_at": datetime(2026, 7, 27, 14, 58, 0),
                "completed_by": "Yessenia (Veewash)",
                "completion_source": COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
                "reason": "completed_before_selected_date",  # stale — must be cleared
            }
        ],
        "review_required": [],
    }
    bags = _bag_rows_from_workload(wl, {})
    assert len(bags) == 1
    b = bags[0]
    assert b["effective_status"] == "completed"
    assert b["canonical_completion_timestamp"] == datetime(2026, 7, 27, 14, 58, 0)
    assert b["canonical_completion_employee"] == "Yessenia (Veewash)"
    assert b["bag_snapshot"]["outcome"] == "completed"
    assert "completed_before_selected_date" not in str(b["bag_snapshot"].get("reason"))
    assert b["bag_snapshot"]["completion_source"] == COMPLETION_SOURCE_POST_REVIEW_WEIGHT


def test_manager_correct_completion_beats_cycle_resolver():
    tl = _resend_post_review_timeline()
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [
            {
                "bag_id": "BAG1",
                "rack": e.get("rack"),
                "purpose": e.get("purpose"),
                "scanned_at_parsed": e["scanned_at_parsed"],
                "user_name": e.get("user_name"),
                "weight_lbs": e.get("weight_lbs"),
                "source_filename": None,
                "raw_json": None,
            }
            for e in tl
        ],
        [
            {
                "bag_id": "BAG1",
                "new_values": {
                    "completed_by": "Manager",
                    "completion_at": "2026-07-27T18:00:00",
                },
                "created_at": datetime(2026, 7, 27, 19, 0, 0),
                "id": 1,
            }
        ],
    ]
    with patch("backend.rinse_veewash_workload.table_exists", return_value=True):
        out = load_canonical_completions_v2(
            cursor,
            3,
            ["BAG1"],
            selected_date_et=DAY,
            service_type_by_bag={"BAG1": "WF"},
            entry_racks=["VeeWash Dirty", "Rinse Zipvan"],
        )
    assert out["BAG1"]["completion_source"] == "manager_correct_completion"
    assert out["BAG1"]["completed_by"] == "Manager"
    assert out["BAG1"]["completion_at"] == datetime(2026, 7, 27, 18, 0, 0)


def test_repeated_cycle_resolve_idempotent():
    tl = _resend_post_review_timeline()
    a = resolve_current_cycle(tl, selected_date_et=DAY).as_dict()
    b = resolve_current_cycle(tl, selected_date_et=DAY).as_dict()
    c = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    assert a == b
    assert c["completion_at"] == datetime.fromisoformat(a["completion_at"])


def test_ssp_wf_operational_completion_uses_cycle_boundary_not_clean():
    from backend.rinse_simple_shift_performance import _wf_day_operational_completion

    tl = _resend_post_review_timeline()
    out = _wf_day_operational_completion(tl, selected_date_et=DAY)
    shared = resolve_current_cycle(tl, selected_date_et=DAY)
    assert out.completed is True
    assert out.via_clean_rack is False
    assert out.completion_at == shared.completion_at == datetime(2026, 7, 27, 14, 58, 0)
    assert out.completion_kind == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out.completion_user == "Yessenia (Veewash)"


def test_ssp_same_day_filter_ignores_next_day_cycle_completion():
    from backend.rinse_simple_shift_performance import _wf_day_operational_completion

    tl = [
        _ev(ts=datetime(2026, 7, 27, 15, 18, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 28, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 28, 10, 24, 0), purpose="garments-reviewed", user="Maria"),
        _ev(ts=datetime(2026, 7, 28, 10, 25, 0), purpose="weight-entry", user="Maria", weight=11.6),
    ]
    shared = resolve_current_cycle(tl, selected_date_et=DAY)
    assert shared.effective_status == "completed"
    assert shared.entry_at == datetime(2026, 7, 28, 6, 0, 0)
    assert shared.completion_at == datetime(2026, 7, 28, 10, 25, 0)
    op = _wf_day_operational_completion(tl, selected_date_et=DAY)
    assert op.completed is False
    assert op.completion_at is None
    step = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
    assert step is None


def test_canonical_bag_completion_result_marks_manager_override():
    from backend.rinse_simple_shift_performance import _bag_completion_result_from_canonical

    out = _bag_completion_result_from_canonical(
        {
            "completion_at": datetime(2026, 7, 27, 15, 15, 0),
            "completed_by": "Amna (Veewash)",
            "completion_source": "manager_correct_completion",
        }
    )
    assert out.completed is True
    assert out.completion_kind == "manager_correct_completion"
    assert out.completion_user == "Amna (Veewash)"
    assert _bag_completion_result_from_canonical(None).completed is False

def test_ssp_ignores_old_cycle_clean_when_current_cycle_pending():
    from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
    from backend.rinse_simple_shift_performance import _wf_day_operational_completion

    tl = [
        _ev(ts=datetime(2026, 6, 29, 16, 45, 0), purpose="move-bag", rack="VeeWash Clean", user="Old"),
        _ev(ts=datetime(2026, 6, 29, 16, 45, 0), purpose="weight-entry", user="Old", weight=12.0),
        _ev(ts=datetime(2026, 7, 27, 5, 10, 0), purpose="sent-to-vendor", user="Driver"),
        _ev(ts=datetime(2026, 7, 27, 6, 16, 0), purpose="move-bag", rack="VeeWash Dirty", user="Ops"),
        # No garments-reviewed / post-review weight in current cycle
    ]
    legacy = evaluate_bag_completion_v2(tl)
    assert legacy.completed is True  # lifetime Clean still "completes" under v2
    op = _wf_day_operational_completion(tl, selected_date_et=DAY)
    assert op.completed is False
    assert op.via_clean_rack is False


def test_ssp_hd_still_uses_legacy_v2():
    from backend.rinse_simple_shift_performance import _operational_completion_for_bag

    tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 16, 0, 0), purpose="move-bag", rack="VeeWash Clean"),
    ]
    out = _operational_completion_for_bag(
        tl, service_type="HD", selected_date_et=DAY
    )
    assert out.completed is True
    assert out.via_clean_rack is True
    assert out.completion_kind == "clean-rack"


def test_facility_tracker_status_agrees_with_ssp_cycle_completion():
    from backend.rinse_facility_tracker import classify_facility_bag_status
    from backend.rinse_simple_shift_performance import _wf_day_operational_completion

    tl = _resend_post_review_timeline()
    completion = _wf_day_operational_completion(tl, selected_date_et=DAY)
    rec = {"bag_id": "BAG1", "completed": completion.completed, "service_type": "WF"}
    status = classify_facility_bag_status(rec, None, tl, completion)
    assert status in ("still_at_facility", "left_sent")  # completed subset
    pending_tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 10, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 16, 0), purpose="move-bag", rack="VeeWash Dirty"),
    ]
    pending_comp = _wf_day_operational_completion(pending_tl, selected_date_et=DAY)
    pending_rec = {
        "bag_id": "BAG2",
        "completed": pending_comp.completed,
        "service_type": "WF",
    }
    assert classify_facility_bag_status(pending_rec, None, pending_tl, pending_comp) == "pending"


def test_step1_at_vendor_ssp_facility_status_sets_agree():
    """Parity: same WF timeline → same completed boolean across operational surfaces."""
    from backend.rinse_facility_tracker import classify_facility_bag_status
    from backend.rinse_simple_shift_performance import _wf_day_operational_completion

    cases = [
        ("resend_complete", _resend_post_review_timeline(), True),
        (
            "no_clean_complete",
            [
                _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
                _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
                _ev(ts=datetime(2026, 7, 27, 14, 0, 0), purpose="garments-reviewed"),
                _ev(ts=datetime(2026, 7, 27, 14, 30, 0), purpose="weight-entry", user="Rev", weight=8.0),
            ],
            True,
        ),
        (
            "current_cycle_pending_old_clean",
            [
                _ev(ts=datetime(2026, 6, 1, 10, 0, 0), purpose="move-bag", rack="VeeWash Clean"),
                _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
                _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
            ],
            False,
        ),
        (
            "duplicate_post_review_weights_complete_once",
            [
                _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
                _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
                _ev(ts=datetime(2026, 7, 27, 14, 0, 0), purpose="garments-reviewed"),
                _ev(ts=datetime(2026, 7, 27, 14, 30, 0), purpose="weight-entry", user="A", weight=8.0),
                _ev(ts=datetime(2026, 7, 27, 15, 0, 0), purpose="weight-entry", user="B", weight=8.1),
            ],
            True,
        ),
    ]
    for name, tl, expect_completed in cases:
        step = _cycle_anchored_completion_for_day(tl, selected_date_et=DAY, service_type="WF")
        status, _signal, comp_ts, _, _ = _evaluate_bag_as_of(
            tl, service_type="WF", as_of_end=naive_et_day_end_inclusive(DAY)
        )
        ssp = _wf_day_operational_completion(tl, selected_date_et=DAY)
        shared = resolve_current_cycle(tl, selected_date_et=DAY)
        step_completed = step is not None
        av_completed = status == AV_STATUS_COMPLETED
        assert step_completed is expect_completed, name
        assert av_completed is expect_completed, name
        assert ssp.completed is expect_completed, name
        assert (shared.effective_status == "completed") is expect_completed, name
        if expect_completed:
            assert step["completion_at"] == comp_ts == ssp.completion_at == shared.completion_at
        rec = {"bag_id": name, "completed": ssp.completed}
        ft = classify_facility_bag_status(rec, None, tl, ssp)
        if expect_completed:
            assert ft in ("still_at_facility", "left_sent"), name
        else:
            assert ft == "pending", name


def test_extract_bag_activity_credits_still_uses_legacy_v2_attribution():
    """Attribution must remain on evaluate_bag_completion_v2 inside extract_bag_activity_credits."""
    from backend.rinse_bag_activity_rules import ROLE_FOLDING, extract_bag_activity_credits

    # Old Clean alone → legacy v2 still emits a folding credit; cycle would be pending.
    tl = [
        _ev(ts=datetime(2026, 6, 29, 16, 45, 0), purpose="move-bag", rack="VeeWash Clean", user="Folder"),
        _ev(ts=datetime(2026, 7, 27, 5, 10, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 16, 0), purpose="move-bag", rack="VeeWash Dirty"),
    ]
    credits = extract_bag_activity_credits("BAG1", tl, customer="X", default_lbs=10.0)
    folding = [c for c in credits if c.role == ROLE_FOLDING]
    assert folding, "legacy attribution still credits Clean-rack folding"
    assert folding[0].employee == "Folder"
