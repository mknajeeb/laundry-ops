"""Expanded Review Required: CWO in Active, WF post-weight events, no double-count."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_veewash_review import (
    build_review_by_reason,
    derive_pre_post_weights,
    expand_review_required,
)
from backend.rinse_veewash_workload import (
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    REASON_WF_ZERO_OR_MISSING_WEIGHT,
    build_step1_headline_summary,
    classify_veewash_workload,
)


D1 = date(2026, 7, 21)


def _pres(active=1, service="WF", rush="RUSH", last_seen=None, portal="at_vendor"):
    ls = None
    if last_seen is not None:
        ls = datetime(last_seen.year, last_seen.month, last_seen.day, 16, 0)
    return {
        "active": active,
        "service_type": service,
        "rush_flag": rush,
        "portal_status": portal,
        "last_seen_at": ls,
        "customer_name": "Test",
    }


def _entry(d, hour=6):
    return {
        "first_entry_at": datetime(d.year, d.month, d.day, hour, 0),
        "entry_date": d,
        "entry_source": "facility_dirty_scan",
    }


def _comp(d, hour=13, by="Francis (Veewash)"):
    return {
        "completion_at": datetime(d.year, d.month, d.day, hour, 0),
        "completion_date": d,
        "completed_by": by,
        "completion_source": "evaluate_bag_completion_v2:clean-rack",
    }


def test_derive_null_5_5_6_0():
    assert derive_pre_post_weights([None, 5.5, 6.0]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": 6.0,
    }


def test_derive_null_5_5_5_5_same_value_two_events():
    assert derive_pre_post_weights([None, 5.5, 5.5]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": 5.5,
    }


def test_derive_null_5_5_single_event_post_missing():
    assert derive_pre_post_weights([None, 5.5]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": None,
    }


def test_derive_0_5_5_6_0_zero_ignored():
    assert derive_pre_post_weights([0, 5.5, 6.0]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": 6.0,
    }


def test_derive_5_5_then_0_no_valid_post():
    assert derive_pre_post_weights([5.5, 0]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": None,
    }


def test_derive_5_5_null_6_0():
    assert derive_pre_post_weights([5.5, None, 6.0]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": 6.0,
    }


def test_derive_ignores_blank_and_negative():
    assert derive_pre_post_weights([None, "", -1, 5.5, 6.0]) == {
        "pre_weight_lbs": 5.5,
        "post_weight_lbs": 6.0,
    }


def test_cwo_bag_appears_in_review_required_not_completed():
    presence = {"62MRUIXOGF": _pres(service="WF", rush="RUSH")}
    entry = {}  # no Dirty
    completion = {"62MRUIXOGF": _comp(D1, hour=13, by="Francis (Veewash)")}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    assert "62MRUIXOGF" in (raw.get("completed_without_recognized_entry") or [])
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag={},
        weight_by_bag={"62MRUIXOGF": {"pre_weight_lbs": 5.0, "post_weight_lbs": 5.5}},
    )
    assert "62MRUIXOGF" in out["review_required"]
    assert "62MRUIXOGF" in out["new_today"]
    assert "62MRUIXOGF" not in out["completed_on_date"]
    row = next(r for r in out["rows"] if r["bag_id"] == "62MRUIXOGF")
    assert row["outcome"] == "review_required"
    assert row["canonical_status"] == "completed"
    assert REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in row["reason_codes"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in row["reason_codes"]


def test_cwo_still_counts_in_active_headline():
    presence = {"62MRUIXOGF": _pres(service="WF", rush="RUSH")}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},
        completion_by_bag={"62MRUIXOGF": _comp(D1)},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},
        weight_by_bag={"62MRUIXOGF": {"pre_weight_lbs": 5.0, "post_weight_lbs": 5.5}},
    )
    summary = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    assert summary["active_workload"] >= 1
    assert summary["exceptions"]["review_required"] >= 1
    assert summary["completed"] == 0 or "62MRUIXOGF" not in (
        (summary.get("segments") or {}).get("all", {}).get("bag_ids", {}).get("completed") or []
    )


def test_wf_zero_post_weight_in_review_pre_zero_ok_hd_exempt():
    presence = {
        "WFPOST0": _pres(service="WF"),
        "WFPRE0": _pres(service="WF"),
        "HDZERO1": _pres(service="HD"),
    }
    entry = {
        "WFPOST0": _entry(D1),
        "WFPRE0": _entry(D1),
        "HDZERO1": _entry(D1),
    }
    completion = {
        "WFPOST0": _comp(D1),
        "WFPRE0": _comp(D1),
        "HDZERO1": _comp(D1),
    }
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "WFPOST0": {"pre_weight_lbs": 5.5, "post_weight_lbs": 0},
            "WFPRE0": {"pre_weight_lbs": 0, "post_weight_lbs": 6.0},
            "HDZERO1": {"pre_weight_lbs": None, "post_weight_lbs": None},
        },
    )
    assert "WFPOST0" in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in out["review_reasons_by_bag"]["WFPOST0"]
    assert "WFPRE0" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("WFPRE0") or []
    )
    assert "HDZERO1" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("HDZERO1") or []
    )


def test_hd_with_one_or_no_weight_no_weight_review():
    presence = {
        "HDONE": _pres(service="HD"),
        "HDNONE": _pres(service="HD"),
    }
    entry = {"HDONE": _entry(D1), "HDNONE": _entry(D1)}
    completion = {"HDONE": _comp(D1), "HDNONE": _comp(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "HDONE": {"pre_weight_lbs": 4.0, "post_weight_lbs": None},
            "HDNONE": {"pre_weight_lbs": None, "post_weight_lbs": None},
        },
    )
    for bid in ("HDONE", "HDNONE"):
        assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (out["review_reasons_by_bag"].get(bid) or [])


def test_single_scrape_weight_post_missing_review():
    presence = {"WFPREONLY": _pres(service="WF", rush="RUSH")}
    entry = {"WFPREONLY": _entry(D1)}
    completion = {"WFPREONLY": _comp(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"WFPREONLY": {"pre_weight_lbs": 5.5, "post_weight_lbs": None}},
    )
    assert "WFPREONLY" in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in out["review_reasons_by_bag"]["WFPREONLY"]
    row = next(r for r in out["rows"] if r["bag_id"] == "WFPREONLY")
    assert row["pre_weight_lbs"] == 5.5
    assert row["post_weight_lbs"] is None


def test_same_value_two_events_no_weight_review():
    presence = {"WFSAME": _pres(service="WF")}
    entry = {"WFSAME": _entry(D1)}
    completion = {"WFSAME": _comp(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"WFSAME": {"pre_weight_lbs": 5.5, "post_weight_lbs": 5.5}},
    )
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (out["review_reasons_by_bag"].get("WFSAME") or [])


def test_no_double_count_and_review_by_reason_groups():
    presence = {"MULTI1": _pres(service="WF", active=0, last_seen=D1)}
    entry = {"MULTI1": _entry(D1)}
    completion = {}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"MULTI1": {"pre_weight_lbs": None, "post_weight_lbs": None}},
    )
    assert out["review_required"].count("MULTI1") == 1
    codes = out["review_reasons_by_bag"]["MULTI1"]
    assert REASON_DISAPPEARED_WITHOUT_COMPLETION in codes
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in codes
    by = build_review_by_reason(out)
    assert "MULTI1" in by[REASON_DISAPPEARED_WITHOUT_COMPLETION]
    assert "MULTI1" in by[REASON_WF_ZERO_OR_MISSING_POST_WEIGHT]
    summary = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    assert summary["exceptions"]["review_required"] == 1
    assert summary["active_workload"] == summary["completed"] + summary["pending"] + summary["exceptions"]["review_required"]


def test_manager_post_weight_correction_clears_only_weight_reason():
    """Valid corrected post clears WF_ZERO_OR_MISSING_POST_WEIGHT; keeps CWO."""
    presence = {"BOTH1": _pres(service="WF", rush="RUSH")}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},  # CWO
        completion_by_bag={"BOTH1": _comp(D1)},
    )
    # Before correction: missing post + CWO
    before = expand_review_required(
        dict(raw),
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},
        weight_by_bag={"BOTH1": {"pre_weight_lbs": 5.5, "post_weight_lbs": None}},
    )
    assert REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in before["review_reasons_by_bag"]["BOTH1"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in before["review_reasons_by_bag"]["BOTH1"]

    # After manager correction: effective post present
    after = expand_review_required(
        dict(raw),
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},
        weight_by_bag={
            "BOTH1": {
                "pre_weight_lbs": 5.5,
                "post_weight_lbs": 8.25,
                "corrected_post_weight_lbs": 8.25,
            }
        },
    )
    codes = after["review_reasons_by_bag"]["BOTH1"]
    assert REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in codes
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in codes
    assert REASON_WF_ZERO_OR_MISSING_WEIGHT not in codes
    assert "BOTH1" in after["review_required"]


def test_reason_alias_equals_post_weight_code():
    assert REASON_WF_ZERO_OR_MISSING_WEIGHT == REASON_WF_ZERO_OR_MISSING_POST_WEIGHT
