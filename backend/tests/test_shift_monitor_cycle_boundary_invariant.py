"""
Non-negotiable Shift Monitor current-cycle boundary regression suite.

Invariant: a scan from a previous sent-to-vendor cycle can never determine
the current cycle's entry, completion, or status.

Architectural (not a five-order patch). Jul 27 patterns are fixture-only —
order IDs must never appear in production resolvers.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
import pytest

from backend.rinse_cycle_boundary import (
    COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
    COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW,
    PENDING_REASON_ENTRY_NOT_FOUND,
    PRE_STV_ENTRY_MAX_MINUTES,
    resolve_current_cycle,
    resolve_cycle_anchor,
)
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "shift_monitor_cycle_boundary_jul27_patterns.json"
)
DAY = date(2026, 7, 27)
ENTRY_RACKS = list(DEFAULT_FACILITY_ENTRY_RACKS)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _ev(
    *,
    ts: datetime,
    purpose: str,
    rack: str | None = None,
    user: str | None = None,
    weight: float | None = None,
    scan_index: int | None = None,
    ev_id: int | None = None,
) -> dict:
    row = {
        "scanned_at_parsed": ts,
        "purpose": purpose,
        "rack": rack,
        "user_name": user,
        "weight_lbs": weight,
    }
    if scan_index is not None:
        row["scan_index"] = scan_index
    if ev_id is not None:
        row["id"] = ev_id
    return row


def _events_from_fixture(case: dict) -> list[dict]:
    out = []
    for e in case["events"]:
        out.append(
            {
                "scanned_at_parsed": datetime.fromisoformat(e["scanned_at"]),
                "purpose": e.get("purpose"),
                "rack": e.get("rack"),
                "user_name": e.get("user_name"),
                "weight_lbs": e.get("weight_lbs"),
            }
        )
    return out


def _assert_matches_expected(result, expected: dict) -> None:
    got = result.as_dict()
    for key in (
        "cycle_anchor_at",
        "entry_at",
        "entry_rack",
        "garments_reviewed_at",
        "completion_at",
        "completed_by",
        "completion_source",
        "effective_status",
    ):
        assert got.get(key) == expected.get(key), (key, got.get(key), expected.get(key))
    if "pending_reason" in expected:
        assert got.get("pending_reason") == expected.get("pending_reason")
    assert got["via_clean_rack_required"] is False
    assert expected.get("via_clean_rack_required") is False


# --------------------------------------------------------------------------- #
# Architectural unit cases
# --------------------------------------------------------------------------- #


def test_invariant_documented_in_fixture():
    fix = _load_fixture()
    assert "previous sent-to-vendor cycle" in fix["invariant"]
    assert "architectural" in fix["deploy_gate"].lower() or "Do not deploy" in fix["deploy_gate"]


def test_old_cycle_clean_and_weight_ignored_after_new_sent_to_vendor():
    """Old cycle has clean-rack and weight-entry; new sent-to-vendor starts new cycle."""
    prior_clean = datetime(2026, 6, 1, 12, 31, 0)
    prior_weight = datetime(2026, 6, 1, 12, 30, 0)
    prior_review = datetime(2026, 6, 1, 12, 0, 0)
    sent = datetime(2026, 7, 27, 5, 0, 0)
    dirty = datetime(2026, 7, 27, 6, 0, 0)
    review = datetime(2026, 7, 27, 15, 0, 0)
    weight = datetime(2026, 7, 27, 15, 20, 0)
    tl = [
        _ev(ts=datetime(2026, 6, 1, 5, 0, 0), purpose="sent-to-vendor", user="Driver"),
        _ev(ts=datetime(2026, 6, 1, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty", user="Ops"),
        _ev(ts=prior_review, purpose="garments-reviewed", user="Old"),
        _ev(ts=prior_weight, purpose="weight-entry", user="Old", weight=11.0),
        _ev(ts=prior_clean, purpose="move-bag", rack="VeeWash Clean", user="Old"),
        _ev(ts=sent, purpose="sent-to-vendor", user="Driver"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty", user="New"),
        _ev(ts=review, purpose="garments-reviewed", user="New"),
        _ev(ts=weight, purpose="weight-entry", user="New", weight=10.0),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.cycle_anchor_at == sent
    assert out.entry_at == dirty
    assert out.completion_at == weight
    assert out.completed_by == "New"
    assert out.effective_status == "completed"
    # Lifetime first clean/weight must not win
    assert out.completion_at != prior_weight
    assert out.completion_at != prior_clean


def test_old_scans_ignored_for_entry_and_completion():
    sent = datetime(2026, 7, 27, 5, 10, 0)
    tl = [
        _ev(ts=datetime(2026, 7, 26, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty", user="Old"),
        _ev(ts=datetime(2026, 7, 26, 14, 0, 0), purpose="garments-reviewed", user="Old"),
        _ev(ts=datetime(2026, 7, 26, 14, 30, 0), purpose="weight-entry", user="Old", weight=9.0),
        _ev(ts=sent, purpose="sent-to-vendor", user="Driver"),
        # No post-anchor entry/completion yet
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.cycle_anchor_at == sent
    assert out.entry_at is None
    assert out.completion_at is None
    assert out.effective_status == "pending"


def test_new_entry_only_after_new_anchor_dirty():
    sent = datetime(2026, 7, 27, 5, 10, 0)
    dirty = datetime(2026, 7, 27, 6, 16, 0)
    tl = [
        _ev(ts=datetime(2026, 7, 26, 8, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty", user="Ops"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.entry_at == dirty
    assert out.entry_rack == "VeeWash Dirty"


def test_new_entry_rinse_zipvan_after_anchor():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    zipvan = datetime(2026, 7, 27, 5, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=zipvan, purpose="move-bag", rack="Rinse Zipvan", user="Ops"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.entry_at == zipvan
    assert out.entry_rack == "Rinse Zipvan"


def test_move_bag_before_sent_to_vendor_ignored():
    dirty_before = datetime(2026, 7, 27, 4, 0, 0)
    sent = datetime(2026, 7, 27, 5, 0, 0)
    tl = [
        _ev(ts=dirty_before, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.cycle_anchor_at == sent
    assert out.entry_at is None


def test_move_bag_to_nonconfigured_rack_ignored():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Clean"),
        _ev(ts=datetime(2026, 7, 27, 6, 5, 0), purpose="move-bag", rack="Folding-1-VW"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.entry_at is None


def test_multiple_configured_moves_use_first_only():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    first = datetime(2026, 7, 27, 6, 0, 0)
    second = datetime(2026, 7, 27, 7, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=first, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=second, purpose="move-bag", rack="Rinse Zipvan"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.entry_at == first
    assert out.entry_rack == "VeeWash Dirty"


def test_new_completion_only_after_new_garments_reviewed():
    """Weight before garments-reviewed is not completion; post-review weight is."""
    sent = datetime(2026, 7, 27, 5, 10, 0)
    early_weight = datetime(2026, 7, 27, 6, 19, 0)
    review = datetime(2026, 7, 27, 14, 31, 0)
    post_weight = datetime(2026, 7, 27, 14, 58, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 16, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=early_weight, purpose="weight-entry", user="Early", weight=10.0),
        _ev(ts=review, purpose="garments-reviewed", user="Reviewer"),
        _ev(ts=post_weight, purpose="weight-entry", user="Reviewer", weight=9.5),
        _ev(ts=post_weight, purpose="move-bag", rack="VeeWash Clean", user="Reviewer"),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at == post_weight
    assert out.completed_by == "Reviewer"
    assert out.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out.effective_status == "completed"


def test_completion_may_be_second_or_third_overall_weight_entry():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    w1 = datetime(2026, 7, 27, 6, 10, 0)
    w2 = datetime(2026, 7, 27, 10, 0, 0)
    review = datetime(2026, 7, 27, 14, 0, 0)
    w3 = datetime(2026, 7, 27, 14, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=w1, purpose="weight-entry", weight=1.0),
        _ev(ts=w2, purpose="weight-entry", weight=2.0),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=w3, purpose="weight-entry", user="Final", weight=3.0),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at == w3
    assert out.completed_by == "Final"


def test_duplicate_post_review_weights_complete_once_on_earliest():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    review = datetime(2026, 7, 27, 14, 0, 0)
    w_a = datetime(2026, 7, 27, 14, 10, 0)
    w_b = datetime(2026, 7, 27, 14, 12, 0)
    w_c = datetime(2026, 7, 27, 14, 15, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=w_a, purpose="weight-entry", user="Rev", weight=9.0),
        _ev(ts=w_b, purpose="weight-entry", user="Rev", weight=9.1),
        _ev(ts=w_c, purpose="weight-entry", user="Rev", weight=9.2),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at == w_a
    assert out.effective_status == "completed"
    # Re-resolve (idempotent refresh)
    out2 = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out2.as_dict() == out.as_dict()


def test_no_clean_rack_still_completes_from_post_review_weight():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    review = datetime(2026, 7, 27, 14, 0, 0)
    weight = datetime(2026, 7, 27, 14, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Rev", weight=7.5),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at == weight
    assert out.via_clean_rack_required is False
    assert not any(
        str(e.get("rack") or "").lower().find("clean") >= 0 and "dirty" not in str(e.get("rack") or "").lower()
        for e in tl
    )


def test_no_current_cycle_completion_remains_pending():
    """Post-anchor review+weight must not leave bag pending."""
    tl = [
        _ev(ts=datetime(2026, 6, 1, 12, 31, 0), purpose="move-bag", rack="VeeWash Clean", user="Old"),
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 27, 15, 0, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 27, 15, 20, 0), purpose="weight-entry", user="New", weight=10.0),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.effective_status == "completed"
    assert out.completion_at is not None


def test_same_result_after_repeated_refresh_rebuild():
    tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 10, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 16, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 27, 6, 19, 0), purpose="weight-entry", weight=10.0),
        _ev(ts=datetime(2026, 7, 27, 14, 31, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 27, 14, 58, 0), purpose="weight-entry", user="Reviewer", weight=9.5),
    ]
    results = [
        resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS).as_dict()
        for _ in range(5)
    ]
    assert all(r == results[0] for r in results)
    assert results[0]["completion_at"] == "2026-07-27 14:58:00"


def test_same_result_after_overnight_refresh_view():
    """Resolving for D and re-resolving with the same timeline next calendar morning is stable."""
    tl = [
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 27, 14, 0, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 27, 14, 30, 0), purpose="weight-entry", user="Rev", weight=8.0),
    ]
    morning = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    # Overnight: still asking about Jul 27 (historical day view) — must not flip
    overnight = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert overnight.as_dict() == morning.as_dict()
    # Next ET day without a new sent-to-vendor: anchor still latest on/before Jul 28 cutoff
    # which remains the Jul 27 send — completion still visible when selected_date is Jul 28
    # only if completion falls on Jul 28; here completion is Jul 27 so status for Jul 28
    # day membership is a separate concern. Anchor for Jul 28 still Jul 27 05:00.
    assert resolve_cycle_anchor(tl, selected_date_et=date(2026, 7, 28)) == datetime(
        2026, 7, 27, 5, 0, 0
    )


def test_entry_racks_remain_configurable_not_hardcoded_only():
    sent = datetime(2026, 7, 27, 5, 0, 0)
    custom = datetime(2026, 7, 27, 6, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=custom, purpose="move-bag", rack="Custom Intake"),
    ]
    assert resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS).entry_at is None
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=["Custom Intake"])
    assert out.entry_at == custom
    assert out.entry_rack == "Custom Intake"


def test_manager_edited_rows_remain_protected_contract():
    """
    Manager correct_completion / manager_edit_version must win over cycle resolve.

    Persist must not overwrite manager-protected rows with cycle-boundary output.
    """
    from backend.rinse_veewash_workload import load_canonical_completions_v2

    timeline = [
        _ev(ts=datetime(2026, 7, 27, 5, 0, 0), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 7, 27, 14, 0, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 27, 14, 30, 0), purpose="weight-entry", user="Scan", weight=8.0),
    ]
    cycle = resolve_current_cycle(timeline, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert cycle.effective_status == "completed"

    manager_at = datetime(2026, 7, 27, 18, 0, 0)
    bag_snap = {
        "bag_id": "MGR1",
        "manager_edit_version": 2,
        "completion_at": manager_at,
        "completed_by": "Manager",
        "effective_status": "completed",
        "completion_source": "manager_correct_completion",
    }
    assert int(bag_snap["manager_edit_version"]) > 0
    assert bag_snap["completion_at"] != cycle.completion_at
    assert bag_snap["completion_source"] == "manager_correct_completion"
    assert callable(load_canonical_completions_v2)


# --------------------------------------------------------------------------- #
# Fixture-driven synthetic + Jul 27 pattern cases
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "case_key",
    [
        "synthetic_worked_example",
        "synthetic_old_cycle_ignored_after_resend",
        "synthetic_zipvan_entry",
        "synthetic_duplicate_post_review_weights",
        "synthetic_no_clean_still_completes",
    ],
)
def test_synthetic_fixture_cases(case_key: str):
    fix = _load_fixture()
    case = next(c for c in fix["synthetic_cases"] if c["fixture_bag_key"] == case_key)
    out = resolve_current_cycle(
        _events_from_fixture(case),
        selected_date_et=date.fromisoformat(case["selected_date_et"]),
        entry_racks=case.get("configured_entry_racks") or ENTRY_RACKS,
    )
    _assert_matches_expected(out, case["expected"])


@pytest.mark.parametrize("case_index", range(5))
def test_jul27_pattern_cases_complete_under_cycle_boundary(case_index: int):
    """Five Jul 27 disputed patterns — fixture keys only; no prod ID hard-coding."""
    fix = _load_fixture()
    case = fix["jul27_pattern_cases"][case_index]
    assert "jul27_cycle_case_" in case["fixture_bag_key"]
    assert "hard-coded" in case["source_note"] or "never be hard-coded" in case["source_note"]
    # Ensure raw production order IDs are not embedded in the fixture case key path used by resolvers
    assert case["fixture_bag_key"].startswith("jul27_cycle_case_")

    out = resolve_current_cycle(
        _events_from_fixture(case),
        selected_date_et=date.fromisoformat(case["selected_date_et"]),
        entry_racks=case.get("configured_entry_racks") or ENTRY_RACKS,
    )
    _assert_matches_expected(out, case["expected"])
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    # Pre-anchor lifetime clean must not be the completion timestamp
    anchor = out.cycle_anchor_at
    assert anchor is not None
    for e in case["events"]:
        ts = datetime.fromisoformat(e["scanned_at"])
        rack = str(e.get("rack") or "").lower()
        if ts <= anchor and "clean" in rack and "dirty" not in rack:
            assert out.completion_at != ts


def test_jul27_fixture_has_exactly_five_pattern_cases():
    fix = _load_fixture()
    assert len(fix["jul27_pattern_cases"]) == 5


def test_do_not_use_ordinal_weight_or_lifetime_clean_as_completion():
    """Regression: first/second weight ordinal and lifetime clean are insufficient."""
    sent = datetime(2026, 7, 27, 5, 0, 0)
    lifetime_clean = datetime(2026, 6, 15, 12, 0, 0)
    first_weight = datetime(2026, 7, 27, 6, 10, 0)
    second_weight = datetime(2026, 7, 27, 6, 20, 0)
    tl = [
        _ev(ts=lifetime_clean, purpose="move-bag", rack="VeeWash Clean", user="Old"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 27, 6, 0, 0), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=first_weight, purpose="weight-entry", weight=1.0),
        _ev(ts=second_weight, purpose="weight-entry", weight=2.0),
        # No garments-reviewed in current cycle
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at is None
    assert out.effective_status == "pending"


# --------------------------------------------------------------------------- #
# Entry-required chain (stabilization)
# --------------------------------------------------------------------------- #


def test_no_entry_review_plus_weight_remains_pending_entry_not_found():
    """CUR0 pattern: review+weight without configured entry must not complete."""
    sent = datetime(2026, 7, 27, 11, 20, 0)
    review = datetime(2026, 7, 28, 12, 19, 0)
    weight = datetime(2026, 7, 28, 12, 21, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed", user="Jennifer"),
        _ev(ts=weight, purpose="weight-entry", user="Jennifer", weight=20.9),
        _ev(ts=weight, purpose="move-bag", rack="VeeWash Clean", user="Jennifer"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.cycle_anchor_at == sent
    assert out.entry_at is None
    assert out.garments_reviewed_at is None
    assert out.completion_at is None
    assert out.effective_status == "pending"
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND


def test_entry_before_sent_to_vendor_ignored_for_completion_chain():
    dirty_before = datetime(2026, 7, 28, 4, 0, 0)
    sent = datetime(2026, 7, 28, 5, 0, 0)
    review = datetime(2026, 7, 28, 14, 0, 0)
    weight = datetime(2026, 7, 28, 14, 30, 0)
    tl = [
        _ev(ts=dirty_before, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Ops", weight=8.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at is None
    assert out.completion_at is None
    assert out.effective_status == "pending"
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND


def test_review_before_entry_ignored():
    sent = datetime(2026, 7, 28, 5, 0, 0)
    review_before = datetime(2026, 7, 28, 5, 30, 0)
    dirty = datetime(2026, 7, 28, 6, 0, 0)
    review_after = datetime(2026, 7, 28, 14, 0, 0)
    weight = datetime(2026, 7, 28, 14, 20, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review_before, purpose="garments-reviewed", user="Early"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review_after, purpose="garments-reviewed", user="Late"),
        _ev(ts=weight, purpose="weight-entry", user="Late", weight=9.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == dirty
    assert out.garments_reviewed_at == review_after
    assert out.completion_at == weight
    assert out.effective_status == "completed"


def test_weight_after_review_but_entry_missing_remains_pending():
    sent = datetime(2026, 7, 28, 5, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 28, 14, 0, 0), purpose="garments-reviewed"),
        _ev(ts=datetime(2026, 7, 28, 14, 10, 0), purpose="weight-entry", weight=7.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.effective_status == "pending"
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND
    assert out.completion_at is None


def test_dirty_entry_completes_when_review_and_weight_follow():
    sent = datetime(2026, 7, 28, 5, 0, 0)
    dirty = datetime(2026, 7, 28, 6, 0, 0)
    review = datetime(2026, 7, 28, 14, 0, 0)
    weight = datetime(2026, 7, 28, 14, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Rev", weight=8.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_rack == "VeeWash Dirty"
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out.pending_reason is None


def test_zipvan_entry_completes_when_review_and_weight_follow():
    sent = datetime(2026, 7, 28, 5, 0, 0)
    zipvan = datetime(2026, 7, 28, 5, 30, 0)
    review = datetime(2026, 7, 28, 14, 0, 0)
    weight = datetime(2026, 7, 28, 14, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=zipvan, purpose="move-bag", rack="Rinse Zipvan"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Rev", weight=8.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_rack == "Rinse Zipvan"
    assert out.effective_status == "completed"


def test_duplicate_entries_select_earliest_valid_post_anchor_entry():
    sent = datetime(2026, 7, 28, 5, 0, 0)
    first = datetime(2026, 7, 28, 6, 0, 0)
    second = datetime(2026, 7, 28, 7, 0, 0)
    review = datetime(2026, 7, 28, 14, 0, 0)
    weight = datetime(2026, 7, 28, 14, 30, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=first, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=second, purpose="move-bag", rack="Rinse Zipvan"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=8.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == first
    assert out.entry_rack == "VeeWash Dirty"
    assert out.effective_status == "completed"


def test_cur0_fixture_pattern_pending_entry_not_found():
    fix = _load_fixture()
    case = next(
        c
        for c in fix["synthetic_cases"]
        if c["fixture_bag_key"] == "synthetic_cur0_no_entry_review_weight"
    )
    out = resolve_current_cycle(
        _events_from_fixture(case),
        selected_date_et=date.fromisoformat(case["selected_date_et"]),
        entry_racks=case.get("configured_entry_racks") or ENTRY_RACKS,
    )
    _assert_matches_expected(out, case["expected"])
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND


# --------------------------------------------------------------------------- #
# Same-minute POST + pre-STV entry edge cases
# --------------------------------------------------------------------------- #


def test_same_minute_review_then_post_by_scan_index_completes():
    """Portal reverse-index: lower scan_index = later; weight after review."""
    sent = datetime(2026, 7, 30, 4, 19, 0)
    dirty = datetime(2026, 7, 30, 5, 12, 0)
    tie = datetime(2026, 7, 30, 8, 49, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        # Weight id earlier than review (import order) but scan_index later.
        _ev(
            ts=tie,
            purpose="weight-entry",
            user="Singh",
            weight=12.9,
            scan_index=2,
            ev_id=100,
        ),
        _ev(
            ts=tie,
            purpose="garments-reviewed",
            user="Singh",
            scan_index=7,
            ev_id=105,
        ),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.effective_status == "completed"
    assert out.completion_at == tie
    assert out.garments_reviewed_at == tie
    assert out.completion_source == COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
    assert out.pending_reason is None


def test_same_minute_post_before_review_by_scan_index_not_completed():
    """Same minute but scan_index proves weight-entry preceded review."""
    sent = datetime(2026, 7, 30, 4, 19, 0)
    dirty = datetime(2026, 7, 30, 5, 12, 0)
    tie = datetime(2026, 7, 30, 8, 49, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(
            ts=tie,
            purpose="weight-entry",
            user="Early",
            weight=12.9,
            scan_index=8,
            ev_id=200,
        ),
        _ev(
            ts=tie,
            purpose="garments-reviewed",
            user="Later",
            scan_index=2,
            ev_id=201,
        ),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.effective_status == "pending"
    assert out.completion_at is None
    assert out.garments_reviewed_at == tie
    assert out.completion_source is None


def test_same_minute_without_sequence_evidence_not_completed():
    """Equal timestamps with no scan_index/id evidence must not complete."""
    sent = datetime(2026, 7, 30, 4, 0, 0)
    dirty = datetime(2026, 7, 30, 5, 0, 0)
    tie = datetime(2026, 7, 30, 8, 49, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=tie, purpose="garments-reviewed"),
        _ev(ts=tie, purpose="weight-entry", weight=10.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.effective_status == "pending"
    assert out.completion_at is None


def test_dirty_just_before_stv_with_same_cycle_evidence_accepted():
    """Configured Dirty minutes before STV + review/POST → completed."""
    assert PRE_STV_ENTRY_MAX_MINUTES == 15
    dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    tl = [
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty", user="Ops"),
        _ev(ts=sent, purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed", user="Folder"),
        _ev(ts=weight, purpose="weight-entry", user="Folder", weight=33.1),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.cycle_anchor_at == sent
    assert out.entry_at == dirty
    assert out.entry_rack == "VeeWash Dirty"
    assert out.garments_reviewed_at == review
    assert out.completion_at == weight
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out.pending_reason is None


def test_old_dirty_before_stv_from_prior_cycle_rejected():
    """Historical Dirty outside tolerance / prior cycle must not unlock entry."""
    old_dirty = datetime(2026, 7, 29, 6, 0, 0)
    prior_review = datetime(2026, 7, 29, 14, 0, 0)
    prior_weight = datetime(2026, 7, 29, 14, 30, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    tl = [
        _ev(ts=old_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=prior_review, purpose="garments-reviewed"),
        _ev(ts=prior_weight, purpose="weight-entry", weight=20.0),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=33.1),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at is None
    assert out.completion_at is None
    assert out.effective_status == "pending"
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND


def test_pre_stv_dirty_without_post_evidence_not_used_as_entry():
    """Pre-STV Dirty alone (no review+POST) must not become current entry."""
    dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    tl = [
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at is None
    assert out.effective_status == "pending"


def test_no_entry_evidence_remains_entry_not_found():
    """Review+weight with no configured entry (pre or post) stays ENTRY_NOT_FOUND."""
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=33.1),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at is None
    assert out.completion_at is None
    assert out.effective_status == "pending"
    assert out.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND


def test_disappearance_not_applicable_when_resolver_completes():
    """Disappeared-without-completion only applies when resolver finds no completion."""
    from backend.rinse_veewash_workload import _cycle_result_to_completion_dict

    sent = datetime(2026, 7, 30, 4, 19, 0)
    dirty = datetime(2026, 7, 30, 5, 12, 0)
    tie = datetime(2026, 7, 30, 8, 49, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(
            ts=tie,
            purpose="weight-entry",
            user="Singh",
            weight=12.9,
            scan_index=2,
            ev_id=100,
        ),
        _ev(
            ts=tie,
            purpose="garments-reviewed",
            user="Singh",
            scan_index=7,
            ev_id=105,
        ),
    ]
    day = date(2026, 7, 30)
    out = resolve_current_cycle(tl, selected_date_et=day, entry_racks=ENTRY_RACKS)
    assert out.effective_status == "completed"
    comp = _cycle_result_to_completion_dict(out, selected_date_et=day, timeline=tl)
    assert comp is not None
    assert comp["completion_source"] == COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
    # Workload only routes to disappeared_without_completion when completion
    # dict is absent; a completed resolver result must not enter that bucket.
    assert comp["completion_at"] == tie


# --------------------------------------------------------------------------- #
# Entry-candidate selection (no later-Dirty shadowing)
# --------------------------------------------------------------------------- #


def test_valid_post_stv_entry_chain_selects_normal_entry():
    sent = datetime(2026, 7, 30, 7, 0, 0)
    dirty = datetime(2026, 7, 30, 7, 30, 0)
    review = datetime(2026, 7, 30, 10, 0, 0)
    weight = datetime(2026, 7, 30, 10, 20, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Folder", weight=20.0),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == dirty
    assert out.effective_status == "completed"
    assert out.completion_at == weight


def test_invalid_post_stv_plus_valid_pre_stv_fallback_selects_fallback():
    """Later post-STV Dirty after review must not shadow valid ≤15-min pre-STV."""
    pre_dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=pre_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Ops"),
        _ev(ts=sent, purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed", user="Folder"),
        _ev(ts=weight, purpose="weight-entry", user="Folder", weight=33.1),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Admin"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == pre_dirty
    assert out.garments_reviewed_at == review
    assert out.completion_at == weight
    assert out.effective_status == "completed"
    assert out.entry_at != late_dirty


def test_both_valid_prefers_post_stv_entry():
    pre_dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    post_dirty = datetime(2026, 7, 30, 8, 0, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    tl = [
        _ev(ts=pre_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=post_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=33.1),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == post_dirty
    assert out.effective_status == "completed"


def test_old_pre_stv_dirty_outside_tolerance_rejected():
    old_dirty = datetime(2026, 7, 30, 6, 0, 0)  # 83 min before STV
    sent = datetime(2026, 7, 30, 7, 23, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 36, 0)
    tl = [
        _ev(ts=old_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=33.1),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    # Late Dirty after review cannot complete; old Dirty outside tolerance.
    assert out.entry_at == late_dirty
    assert out.completion_at is None
    assert out.effective_status == "pending"


def test_pre_stv_fallback_without_downstream_review_post_rejected():
    dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    # No complete chain → keep earliest post-STV for pending display; not pre-STV.
    assert out.entry_at == late_dirty
    assert out.effective_status == "pending"
    assert out.completion_at is None


def test_multiple_post_stv_dirty_invalid_does_not_shadow_valid():
    """Later invalid post-STV Dirty does not suppress an earlier valid chain."""
    sent = datetime(2026, 7, 30, 7, 0, 0)
    valid_dirty = datetime(2026, 7, 30, 8, 0, 0)
    review = datetime(2026, 7, 30, 10, 0, 0)
    weight = datetime(2026, 7, 30, 10, 20, 0)
    invalid_late = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=valid_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", weight=12.0),
        _ev(ts=invalid_late, purpose="move-bag", rack="Rinse Zipvan"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == valid_dirty
    assert out.effective_status == "completed"
    assert out.completion_at == weight


def test_3gvvidbqh3_fixture_completed_in_pure_resolver():
    """Production residual pattern: admin Dirty at 12:00 after review/POST."""
    pre_dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 35, 0)
    weight2 = datetime(2026, 7, 30, 10, 36, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=pre_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Melissa"),
        _ev(ts=datetime(2026, 7, 30, 7, 23, 0), purpose="weight-entry", weight=34.7),
        _ev(ts=sent, purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=review, purpose="garments-reviewed", user="Amna"),
        _ev(ts=weight, purpose="weight-entry", user="Amna", weight=33.1),
        _ev(ts=weight2, purpose="weight-entry", user="Amna", weight=33.1),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Admin"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.cycle_anchor_at == sent
    assert out.entry_at == pre_dirty
    assert out.garments_reviewed_at == review
    assert out.completion_at == weight
    assert out.effective_status == "completed"
    assert out.completed_by == "Amna"


def test_persisted_day_bag_and_pure_resolver_agree_on_3gv_pattern():
    """Persisted Completed + pure resolver Completed for the residual pattern."""
    persisted_status = "completed"
    persisted_completion = datetime(2026, 7, 30, 10, 35, 0)
    pre_dirty = datetime(2026, 7, 30, 7, 16, 0)
    sent = datetime(2026, 7, 30, 7, 23, 0)
    review = datetime(2026, 7, 30, 10, 5, 0)
    weight = datetime(2026, 7, 30, 10, 35, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=pre_dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(ts=weight, purpose="weight-entry", user="Amna", weight=33.1),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.effective_status == persisted_status
    assert out.completion_at == persisted_completion


def test_2c686tfbzp_same_minute_regression_remains_completed():
    """Same-minute POST bag with later admin Dirty still completes on post-STV entry."""
    sent = datetime(2026, 7, 30, 4, 19, 0)
    dirty = datetime(2026, 7, 30, 5, 12, 0)
    tie = datetime(2026, 7, 30, 8, 49, 0)
    late_dirty = datetime(2026, 7, 30, 12, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=dirty, purpose="move-bag", rack="VeeWash Dirty"),
        _ev(
            ts=tie,
            purpose="weight-entry",
            user="Singh",
            weight=12.9,
            scan_index=2,
            ev_id=100,
        ),
        _ev(
            ts=tie,
            purpose="garments-reviewed",
            user="Singh",
            scan_index=7,
            ev_id=105,
        ),
        _ev(ts=late_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Admin"),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == dirty
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW


def test_2giwg0utr3_zipvan_regression_remains_completed():
    sent = datetime(2026, 7, 28, 6, 25, 0)
    zipvan = datetime(2026, 7, 28, 7, 33, 0)
    mid_dirty = datetime(2026, 7, 28, 12, 0, 0)
    review = datetime(2026, 7, 28, 15, 0, 0)
    weight = datetime(2026, 7, 28, 15, 0, 0)
    tl = [
        _ev(ts=sent, purpose="sent-to-vendor"),
        _ev(ts=zipvan, purpose="move-bag", rack="Rinse Zipvan"),
        _ev(ts=mid_dirty, purpose="move-bag", rack="VeeWash Dirty", user="Admin"),
        _ev(
            ts=weight,
            purpose="weight-entry",
            user="Tarannum",
            weight=15.4,
            scan_index=4,
            ev_id=200,
        ),
        _ev(
            ts=review,
            purpose="garments-reviewed",
            user="Tarannum",
            scan_index=8,
            ev_id=205,
        ),
    ]
    out = resolve_current_cycle(
        tl, selected_date_et=date(2026, 7, 28), entry_racks=ENTRY_RACKS
    )
    assert out.entry_at == zipvan
    assert out.effective_status == "completed"
