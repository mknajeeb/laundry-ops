"""Expanded Review Required: CWO in Active, WF zero-weight, no double-count."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_veewash_review import expand_review_required, build_review_by_reason
from backend.rinse_veewash_workload import (
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
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
        weight_by_bag={"62MRUIXOGF": 5.5},
    )
    assert "62MRUIXOGF" in out["review_required"]
    assert "62MRUIXOGF" in out["new_today"]
    assert "62MRUIXOGF" not in out["completed_on_date"]
    row = next(r for r in out["rows"] if r["bag_id"] == "62MRUIXOGF")
    assert row["outcome"] == "review_required"
    assert row["canonical_status"] == "completed"
    assert REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in row["reason_codes"]
    assert out["reconciliation"]["active_equals_completed_plus_pending_plus_review"]


def test_cwo_not_double_counted_in_headline():
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
        weight_by_bag={"62MRUIXOGF": 5.5},
    )
    summ = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    assert summ["active_workload"] == summ["completed"] + summ["pending"] + summ["exceptions"]["review_required"]
    assert "62MRUIXOGF" in summ["segments"]["wf_rush"]["bag_ids"]["review_required"]
    assert "62MRUIXOGF" not in summ["segments"]["wf_rush"]["bag_ids"]["completed"]


def test_wf_zero_weight_in_review_hd_exempt():
    presence = {
        "WFZERO1": _pres(service="WF", rush="RUSH"),
        "HDZERO1": _pres(service="HD", rush="RUSH"),
    }
    entry = {"WFZERO1": _entry(D1), "HDZERO1": _entry(D1)}
    completion = {"WFZERO1": _comp(D1), "HDZERO1": _comp(D1)}
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
        wia_by_bag={"HDZERO1": _entry(D1)},
        weight_by_bag={"WFZERO1": 0, "HDZERO1": None},
    )
    assert "WFZERO1" in out["review_required"]
    assert "WFZERO1" not in out["completed_on_date"]
    assert REASON_WF_ZERO_OR_MISSING_WEIGHT in out["review_reasons_by_bag"]["WFZERO1"]
    # HD missing weight must NOT trigger weight review
    assert "HDZERO1" not in out["review_required"] or REASON_WF_ZERO_OR_MISSING_WEIGHT not in (
        out["review_reasons_by_bag"].get("HDZERO1") or []
    )
    assert "HDZERO1" in out["completed_on_date"]


def test_multiple_reasons_one_review_count():
    presence = {"MULTI1": _pres(service="WF", rush="NON_RUSH", active=0, last_seen=D1)}
    entry = {"MULTI1": _entry(D1)}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
        disappearance_state_by_bag={"MULTI1": "DISAPPEARED_WITHOUT_COMPLETION"},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={"MULTI1": None},
    )
    assert out["counts"]["review_required"] == 1
    codes = out["review_reasons_by_bag"]["MULTI1"]
    assert REASON_DISAPPEARED_WITHOUT_COMPLETION in codes
    assert REASON_WF_ZERO_OR_MISSING_WEIGHT in codes
    by = build_review_by_reason(out)
    assert "MULTI1" in by[REASON_DISAPPEARED_WITHOUT_COMPLETION]
    assert "MULTI1" in by[REASON_WF_ZERO_OR_MISSING_WEIGHT]
