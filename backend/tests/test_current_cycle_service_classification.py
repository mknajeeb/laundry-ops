"""Current-cycle service classification vs prior-cycle COMPLETED registry."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import (
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    build_step1_headline_summary,
    classify_veewash_workload,
)


D1 = date(2026, 8, 17)


def _pres(service="WF", rush="RUSH", active=1):
    return {
        "active": active,
        "service_type": service,
        "rush_flag": rush,
        "portal_status": "at_vendor",
        "last_seen_at": datetime(2026, 8, 17, 10, 0),
        "customer_name": "Test",
    }


def _entry(d=D1, hour=6):
    return {
        "first_entry_at": datetime(d.year, d.month, d.day, hour, 0),
        "entry_date": d,
        "entry_source": "facility_dirty_scan",
    }


def _comp(d=D1, hour=13):
    return {
        "completion_at": datetime(d.year, d.month, d.day, hour, 0),
        "completion_date": d,
        "completed_by": "Francis (Veewash)",
        "completion_source": "post_review_weight",
    }


def _classify_and_expand(
    bag: str,
    *,
    portal: str,
    registry: str,
    historical: bool,
    rush: str = "RUSH",
    completed: bool = False,
    current_registry_conflict: bool = False,
):
    """
    current_registry_conflict: incomplete (current-cycle) registry differs from portal.
    historical: COMPLETED prior-cycle registry (must not override portal).
    """
    presence = {bag: _pres(service=portal, rush=rush)}
    entry = {bag: _entry()}
    completion = {bag: _comp()} if completed else {}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    if bag not in (raw.get("new_today") or []) and bag not in (raw.get("carryover") or []):
        raw.setdefault("new_today", []).append(bag)
        raw.setdefault("rows", []).append(
            {
                "bag_id": bag,
                "service_type": portal,
                "outcome": "completed" if completed else "pending",
                "rush_flag": rush,
            }
        )
    hist = [bag] if historical else []
    # When testing genuine current-cycle conflict, registry is NOT historical.
    if current_registry_conflict:
        hist = []
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            bag: {
                "pre_weight_lbs": 23.5,
                "post_weight_event_exists": False,
                "weight_entry_count": 1,
            }
        },
        registry_service_by_bag={bag: registry},
        registry_historical_completed_bags=hist,
    )
    row = next(r for r in out["rows"] if r["bag_id"] == bag)
    return out, row


def test_a_prior_hd_completed_current_wf_is_wf():
    """A: prior HD COMPLETED → current portal WF → WF, no stale mismatch."""
    bag = "DQU4E7DZFI"
    out, row = _classify_and_expand(
        bag, portal="WF", registry="HD", historical=True, rush="RUSH"
    )
    assert row["service_type"] == "WF"
    assert REASON_SERVICE_CLASSIFICATION_MISMATCH not in (
        out.get("review_reasons_by_bag") or {}
    ).get(bag, [])
    summary = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    wf_rush_ids = (
        summary["segments"]["wf_rush"]["bag_ids"]["new_today"]
        + summary["segments"]["wf_rush"]["bag_ids"]["carryover"]
        + summary["segments"]["wf_rush"]["bag_ids"]["pending"]
        + summary["segments"]["wf_rush"]["bag_ids"]["completed"]
        + summary["segments"]["wf_rush"]["bag_ids"]["review_required"]
    )
    assert bag in wf_rush_ids
    hd_ids = (
        summary["segments"]["hd_rush"]["bag_ids"]["new_today"]
        + summary["segments"]["hd_rush"]["bag_ids"]["carryover"]
        + summary["segments"]["hd_rush"]["bag_ids"]["pending"]
        + summary["segments"]["hd_rush"]["bag_ids"]["completed"]
        + summary["segments"]["hd_rush"]["bag_ids"]["review_required"]
    )
    assert bag not in hd_ids


def test_b_prior_wf_completed_current_hd_is_hd():
    """B: prior WF COMPLETED → current portal HD → HD."""
    bag = "BAGPRIORWF"
    out, row = _classify_and_expand(
        bag, portal="HD", registry="WF", historical=True, rush="RUSH"
    )
    assert row["service_type"] == "HD"
    assert REASON_SERVICE_CLASSIFICATION_MISMATCH not in (
        out.get("review_reasons_by_bag") or {}
    ).get(bag, [])


def test_c_historical_registry_vs_current_portal_portal_wins():
    """C: historical registry vs current portal → current wins both directions."""
    _, row_wf = _classify_and_expand(
        "HIST1", portal="WF", registry="HD", historical=True
    )
    _, row_hd = _classify_and_expand(
        "HIST2", portal="HD", registry="WF", historical=True
    )
    assert row_wf["service_type"] == "WF"
    assert row_hd["service_type"] == "HD"
    assert row_wf.get("registry_service_historical") is True
    assert row_hd.get("registry_service_historical") is True


def test_d_genuine_current_cycle_conflict_preserves_portal_membership():
    """D: incomplete registry HD vs portal WF → membership WF; Review may remain."""
    bag = "CURCONFLICT"
    out, row = _classify_and_expand(
        bag,
        portal="WF",
        registry="HD",
        historical=False,
        current_registry_conflict=True,
        completed=True,
    )
    assert row["service_type"] == "WF"
    # Completed + genuine conflict may keep Review reason.
    codes = (out.get("review_reasons_by_bag") or {}).get(bag) or []
    assert REASON_SERVICE_CLASSIFICATION_MISMATCH in codes
    assert bag in (out.get("review_required") or [])


def test_e_review_reason_does_not_remove_known_wf_from_wf_workload():
    """E: SERVICE_CLASSIFICATION_MISMATCH must not remap known WF into HD."""
    bag = "KEEPWF1"
    out, row = _classify_and_expand(
        bag,
        portal="WF",
        registry="HD",
        historical=False,
        current_registry_conflict=True,
        completed=True,
        rush="RUSH",
    )
    assert row["service_type"] == "WF"
    summary = build_step1_headline_summary(out, selected_date_et=D1, activation_date=D1)
    wf_ids = (
        summary["segments"]["wf_rush"]["bag_ids"]["new_today"]
        + summary["segments"]["wf_rush"]["bag_ids"]["carryover"]
        + summary["segments"]["wf_rush"]["bag_ids"]["pending"]
        + summary["segments"]["wf_rush"]["bag_ids"]["completed"]
        + summary["segments"]["wf_rush"]["bag_ids"]["review_required"]
    )
    assert bag in wf_ids


def test_f_reusable_bag_tag_across_cycles():
    """F: same bag_id reused — prior COMPLETED HD does not stick on new WF cycle."""
    bag = "REUSEBAG1"
    # Cycle 1 completed as HD (historical).
    out1, row1 = _classify_and_expand(
        bag, portal="HD", registry="HD", historical=False, completed=True
    )
    assert row1["service_type"] == "HD"
    # Cycle 2: same bag returns as WF; registry still COMPLETED HD from cycle 1.
    out2, row2 = _classify_and_expand(
        bag, portal="WF", registry="HD", historical=True, completed=False, rush="RUSH"
    )
    assert row2["service_type"] == "WF"
    assert REASON_SERVICE_CLASSIFICATION_MISMATCH not in (
        out2.get("review_reasons_by_bag") or {}
    ).get(bag, [])
    # No contamination from cycle-1 outcome into cycle-2 reasons.
    assert bag not in (out2.get("review_required") or [])
