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


def test_derive_one_weight_entry_pre_only():
    d = derive_pre_post_weights([5.5])
    assert d["pre_weight_lbs"] == 5.5
    assert d["post_weight_lbs"] is None
    assert d["post_weight_event_exists"] is False
    assert d["weight_entry_count"] == 1


def test_derive_two_weight_entry_pre_and_post():
    d = derive_pre_post_weights([5.5, 6.0])
    assert d["pre_weight_lbs"] == 5.5
    assert d["post_weight_lbs"] == 6.0
    assert d["post_weight_event_exists"] is True
    assert d["post_weight_value"] == 6.0
    assert d["weight_entry_count"] == 2


def test_derive_second_weight_entry_zero_is_post():
    d = derive_pre_post_weights([5.5, 0])
    assert d["pre_weight_lbs"] == 5.5
    assert d["post_weight_lbs"] == 0.0
    assert d["post_weight_event_exists"] is True
    assert d["post_weight_value"] == 0.0
    assert d["post_weight_valid_for_standard_weight_revenue"] is False


def test_derive_first_zero_still_pre_second_is_post():
    """Chronology only — first weight-entry is Pre even when 0."""
    d = derive_pre_post_weights([0, 6.0])
    assert d["pre_weight_lbs"] == 0.0
    assert d["post_weight_lbs"] == 6.0
    assert d["post_weight_event_exists"] is True


def test_resolve_weight_entry_pair_keeps_employee_and_timestamp():
    from backend.rinse_veewash_review import resolve_weight_entry_pair

    d = resolve_weight_entry_pair(
        [
            {
                "weight_lbs": 4.9,
                "scanned_at_parsed": datetime(2026, 7, 22, 6, 3),
                "user_name": "Varun",
            },
            {
                "weight_lbs": 0,
                "scanned_at_parsed": datetime(2026, 7, 22, 9, 44),
                "user_name": "Maria",
            },
        ]
    )
    assert d["pre_weight_employee"] == "Varun"
    assert d["post_weight_employee"] == "Maria"
    assert d["pre_weight_at"] == datetime(2026, 7, 22, 6, 3)
    assert d["post_weight_at"] == datetime(2026, 7, 22, 9, 44)


def test_resolve_weight_entry_pair_carries_enrichment_provenance():
    from backend.rinse_veewash_review import resolve_weight_entry_pair

    d = resolve_weight_entry_pair(
        [
            {
                "weight_lbs": 23.6,
                "scanned_at_parsed": datetime(2026, 7, 22, 6, 16),
                "weight_source": "portal_weight_num_historical",
                "weight_observed_at": datetime(2026, 7, 22, 6, 24),
                "weight_attach_batch_id": 2807,
                "weight_attach_reason": "RECOVERED_FROM_HISTORICAL_PORTAL_OBSERVATION",
            },
            {
                "weight_lbs": 22.6,
                "scanned_at_parsed": datetime(2026, 7, 22, 16, 42),
                "weight_source": "portal_weight_num",
                "weight_observed_at": datetime(2026, 7, 22, 16, 45),
                "weight_attach_batch_id": 2815,
                "weight_attach_reason": "CURRENT_WEIGHT_ATTACHED_TO_LATEST_EVENT",
            },
        ]
    )
    assert d["pre_weight_lbs"] == 23.6
    assert d["pre_weight_source"] == "portal_weight_num_historical"
    assert d["pre_weight_attach_batch_id"] == 2807
    assert d["post_weight_lbs"] == 22.6
    assert d["post_weight_source"] == "portal_weight_num"
    assert d["post_weight_attach_batch_id"] == 2815


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


def test_wf_recorded_zero_post_not_missing_post_review():
    """Recorded post weight 0 is not WF_ZERO_OR_MISSING_POST_WEIGHT."""
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
            "WFPOST0": {
                "pre_weight_lbs": 5.5,
                "post_weight_lbs": 0,
                "post_weight_event_exists": True,
                "post_weight_value": 0,
                "post_weight_valid_for_standard_weight_revenue": False,
            },
            "WFPRE0": {
                "pre_weight_lbs": 0,
                "post_weight_lbs": 6.0,
                "post_weight_event_exists": True,
                "post_weight_value": 6.0,
                "post_weight_valid_for_standard_weight_revenue": True,
            },
            "HDZERO1": {"pre_weight_lbs": None, "post_weight_lbs": None},
        },
    )
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("WFPOST0") or []
    )
    row = next(r for r in out["rows"] if r["bag_id"] == "WFPOST0")
    assert row.get("post_weight_event_exists") is True
    assert row.get("post_weight_value") == 0
    assert "WFPRE0" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("WFPRE0") or []
    )
    assert "HDZERO1" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("HDZERO1") or []
    )


def test_wf_bulk_with_post_zero_stays_in_wf_rush_active():
    """WF Rush bag: pre>0, post=0, create-workitem-bulk → bulk review, stays in Active."""
    from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW

    presence = {"7OPZ6IZ0X7": _pres(service="HD", rush="RUSH")}  # portal mis-tag
    entry = {"7OPZ6IZ0X7": _entry(D1)}
    completion = {"7OPZ6IZ0X7": _comp(D1)}
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
            "7OPZ6IZ0X7": {
                "pre_weight_lbs": 4.9,
                "post_weight_lbs": 0.0,
                "post_weight_event_exists": True,
                "post_weight_value": 0.0,
                "post_weight_valid_for_standard_weight_revenue": False,
            }
        },
        bulk_scan_by_bag={
            "7OPZ6IZ0X7": {
                "count": 1,
                "first_at": datetime(2026, 7, 22, 7, 31),
                "employee": "Francis (Veewash)",
            }
        },
        registry_service_by_bag={"7OPZ6IZ0X7": "WF"},
    )
    assert "7OPZ6IZ0X7" in out["new_today"]  # still Active
    assert "7OPZ6IZ0X7" in out["review_required"]
    codes = out["review_reasons_by_bag"]["7OPZ6IZ0X7"]
    assert REASON_WF_BULK_WORKITEM_REVIEW in codes
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in codes
    row = next(r for r in out["rows"] if r["bag_id"] == "7OPZ6IZ0X7")
    assert row["service_type"] == "WF"
    summary = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    wf_rush = summary["segments"]["wf_rush"]
    assert "7OPZ6IZ0X7" in (wf_rush["bag_ids"]["new_today"] + wf_rush["bag_ids"]["carryover"])
    assert "7OPZ6IZ0X7" in wf_rush["bag_ids"]["review_required"]
    assert "7OPZ6IZ0X7" in (summary.get("review_by_reason") or {}).get(
        REASON_WF_BULK_WORKITEM_REVIEW, []
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


def test_pending_wf_with_pre_only_stays_pending_not_review():
    """During live shift, pre-only WF bags that are not completed stay Pending."""
    presence = {"WFPEND1": _pres(service="WF", active=1)}
    entry = {"WFPEND1": _entry(D1)}
    completion = {}  # not completed
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    assert "WFPEND1" in (raw.get("pending_end_of_date") or [])
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"WFPEND1": {"pre_weight_lbs": 12.5, "post_weight_lbs": None}},
    )
    assert "WFPEND1" not in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (out["review_reasons_by_bag"].get("WFPEND1") or [])
    assert "WFPEND1" in out["pending_end_of_date"]
    row = next(r for r in out["rows"] if r["bag_id"] == "WFPEND1")
    assert row["pre_weight_lbs"] == 12.5
    assert row["post_weight_lbs"] is None


def test_completed_wf_pre_only_goes_to_review():
    presence = {"WFCOMP1": _pres(service="WF")}
    entry = {"WFCOMP1": _entry(D1)}
    completion = {"WFCOMP1": _comp(D1)}
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
        weight_by_bag={"WFCOMP1": {"pre_weight_lbs": 12.5, "post_weight_lbs": None}},
    )
    assert "WFCOMP1" in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in out["review_reasons_by_bag"]["WFCOMP1"]
    assert "WFCOMP1" not in out["completed_on_date"]


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
        weight_by_bag={
            "WFSAME": {
                "pre_weight_lbs": 5.5,
                "post_weight_lbs": 5.5,
                "post_weight_event_exists": True,
                "weight_entry_count": 2,
            }
        },
    )
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (out["review_reasons_by_bag"].get("WFSAME") or [])


def test_completed_wf_two_weight_entries_no_missing_post_review():
    presence = {"WFTWO": _pres(service="WF")}
    entry = {"WFTWO": _entry(D1)}
    completion = {"WFTWO": _comp(D1)}
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
            "WFTWO": {
                "pre_weight_lbs": 4.9,
                "post_weight_lbs": 0.0,
                "post_weight_event_exists": True,
                "post_weight_value": 0.0,
                "weight_entry_count": 2,
            }
        },
    )
    assert "WFTWO" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("WFTWO") or []
    )
    assert "WFTWO" in out["completed_on_date"]


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
        # Disappeared + not completed: weight reason must NOT apply (no completion gate).
        weight_by_bag={"MULTI1": {"pre_weight_lbs": 5.5, "post_weight_lbs": None}},
    )
    assert out["review_required"].count("MULTI1") == 1
    codes = out["review_reasons_by_bag"]["MULTI1"]
    assert REASON_DISAPPEARED_WITHOUT_COMPLETION in codes
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in codes
    by = build_review_by_reason(out)
    assert "MULTI1" in by[REASON_DISAPPEARED_WITHOUT_COMPLETION]
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


def _assert_partition_invariants(out: dict) -> None:
    completed = set(out.get("completed_on_date") or [])
    pending = set(out.get("pending_end_of_date") or [])
    review = set(out.get("review_required") or [])
    assert not (completed & pending)
    assert not (completed & review)
    assert not (pending & review)
    active = set(out.get("new_today") or []) | set(out.get("carryover") or [])
    # Active members are partitioned across the three statuses.
    assert active == completed | pending | review
    counts = out.get("counts") or {}
    assert counts.get("completed_on_date") == len(completed)
    assert counts.get("pending_end_of_date") == len(pending)
    assert counts.get("review_required") == len(review)
    assert (
        counts.get("total_active_workload")
        == len(completed) + len(pending) + len(review)
    )


def test_incomplete_bulk_workitem_stays_pending():
    from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW

    presence = {"INCBULK1": _pres(service="WF")}
    entry = {"INCBULK1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        bulk_scan_by_bag={
            "INCBULK1": {
                "count": 1,
                "first_at": datetime(2026, 7, 21, 9, 40),
                "employee": "Yessenia",
            }
        },
    )
    assert "INCBULK1" in out["pending_end_of_date"]
    assert "INCBULK1" not in out["review_required"]
    assert REASON_WF_BULK_WORKITEM_REVIEW not in (
        out["review_reasons_by_bag"].get("INCBULK1") or []
    )
    _assert_partition_invariants(out)


def test_incomplete_split_load_stays_pending():
    """Split-load alone (no completion) must not enter Review Required."""
    presence = {"INCSPLIT1": _pres(service="WF")}
    entry = {"INCSPLIT1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"INCSPLIT1": {"pre_weight_lbs": 20.0, "post_weight_lbs": None}},
    )
    assert "INCSPLIT1" in out["pending_end_of_date"]
    assert "INCSPLIT1" not in out["review_required"]
    _assert_partition_invariants(out)


def test_incomplete_missing_post_stays_pending():
    presence = {"INCPOST1": _pres(service="WF")}
    entry = {"INCPOST1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "INCPOST1": {
                "pre_weight_lbs": 12.0,
                "post_weight_lbs": None,
                "post_weight_event_exists": False,
                "weight_entry_count": 1,
            }
        },
    )
    assert "INCPOST1" in out["pending_end_of_date"]
    assert "INCPOST1" not in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        out["review_reasons_by_bag"].get("INCPOST1") or []
    )
    _assert_partition_invariants(out)


def test_completed_bulk_workitem_goes_review_required():
    from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW

    presence = {"CMPBULK1": _pres(service="WF")}
    entry = {"CMPBULK1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={"CMPBULK1": _comp(D1)},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "CMPBULK1": {
                "pre_weight_lbs": 10.0,
                "post_weight_lbs": 9.0,
                "post_weight_event_exists": True,
                "post_weight_value": 9.0,
                "weight_entry_count": 2,
            }
        },
        bulk_scan_by_bag={
            "CMPBULK1": {
                "count": 1,
                "first_at": datetime(2026, 7, 21, 9, 40),
                "employee": "Yessenia",
            }
        },
    )
    assert "CMPBULK1" in out["review_required"]
    assert "CMPBULK1" not in out["pending_end_of_date"]
    assert "CMPBULK1" not in out["completed_on_date"]
    assert REASON_WF_BULK_WORKITEM_REVIEW in out["review_reasons_by_bag"]["CMPBULK1"]
    _assert_partition_invariants(out)


def test_completed_missing_post_goes_review_required():
    presence = {"CMPPOST1": _pres(service="WF")}
    entry = {"CMPPOST1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={"CMPPOST1": _comp(D1)},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "CMPPOST1": {
                "pre_weight_lbs": 12.0,
                "post_weight_lbs": None,
                "post_weight_event_exists": False,
                "weight_entry_count": 1,
            }
        },
    )
    assert "CMPPOST1" in out["review_required"]
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in out["review_reasons_by_bag"]["CMPPOST1"]
    _assert_partition_invariants(out)


def test_completed_no_exception_stays_completed():
    presence = {"CMPOK1": _pres(service="WF")}
    entry = {"CMPOK1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={"CMPOK1": _comp(D1)},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "CMPOK1": {
                "pre_weight_lbs": 12.0,
                "post_weight_lbs": 11.0,
                "post_weight_event_exists": True,
                "post_weight_value": 11.0,
                "weight_entry_count": 2,
            }
        },
    )
    assert "CMPOK1" in out["completed_on_date"]
    assert "CMPOK1" not in out["review_required"]
    assert "CMPOK1" not in out["pending_end_of_date"]
    assert not (out["review_reasons_by_bag"].get("CMPOK1") or [])
    _assert_partition_invariants(out)
