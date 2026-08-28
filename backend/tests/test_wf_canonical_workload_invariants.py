"""Invariant tests for get_canonical_wf_workload — WF source-of-truth boundary."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_wf_canonical_workload import (
    LIFECYCLE_COMPLETED,
    LIFECYCLE_OPEN,
    OUTCOME_CARRYOVER,
    REVIEW_MISSING_FROM_PORTAL,
    assert_canonical_workload_invariants,
    get_canonical_wf_workload,
    get_wf_bag_lifecycle,
)
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
)

ORG = 3
D = date(2026, 8, 28)
D_YDAY = date(2026, 8, 27)
D_30 = date(2026, 7, 29)


def _wl_patches(
    *,
    prior_open=None,
    prior_meta=None,
    presence=None,
    entry=None,
    registry_today=None,
    terminal=None,
    completed_map=None,
    present_for_absence=None,
    absence_meta=None,
):
    prior_open = set(prior_open or [])
    prior_meta = dict(prior_meta or {})
    presence = set(presence or [])
    entry = set(entry or [])
    registry_today = set(registry_today or [])
    terminal = set(terminal or [])
    completed_map = dict(completed_map or {})
    if absence_meta is None:
        absence_meta = {"absence_allowed": present_for_absence is not None}

    return (
        patch(
            "backend.rinse_wf_canonical_workload._prior_day_unfinished_wf_ids",
            return_value=(prior_open, prior_meta),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._same_day_presence_wf_ids",
            return_value=(presence, {}, 1),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._discover_same_day_entry_wf_ids",
            return_value=entry,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._registry_wf_completed_on_date",
            return_value=registry_today,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._terminal_before_date",
            return_value=terminal,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._completion_date_on_d",
            return_value=completed_map,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._latest_absence_capable_present_ids",
            return_value=(present_for_absence, absence_meta),
        ),
    )


def _run(cur=None, **kwargs):
    cur = cur or MagicMock()
    patches = _wl_patches(**kwargs)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        return get_canonical_wf_workload(cur, ORG, D)


def test_1_complete_yesterday_cannot_appear_today():
    wl = _run(
        prior_open={"OLD1"},
        presence={"OLD1"},
        terminal={"OLD1"},
    )
    assert "OLD1" not in wl["bag_ids"]
    assert_canonical_workload_invariants(wl)


def test_2_complete_30_days_ago_cannot_appear_today():
    wl = _run(
        presence={"ANCIENT"},
        entry={"ANCIENT"},
        terminal={"ANCIENT"},
    )
    assert "ANCIENT" not in wl["bag_ids"]
    assert len(wl["historical_completed_in_workload"]) == 0


def test_3_stale_active_cycle_cannot_resurrect():
    # Service cycles are not a seed — only prior_open / presence / entry / registry.
    # A stale ACTIVE cycle with no legitimate seed must not appear.
    wl = _run(prior_open=set(), presence=set(), entry=set(), terminal=set())
    assert wl["bag_ids"] == frozenset()


def test_4_portal_sees_completed_bag_again_cannot_resurrect():
    wl = _run(
        presence={"DONE01"},
        terminal={"DONE01"},
    )
    assert "DONE01" not in wl["bag_ids"]


def test_5_failed_scrape_cannot_create_absence():
    wl = _run(
        prior_open={"OPEN1"},
        present_for_absence=None,
        absence_meta={"absence_allowed": False, "reason": "failed"},
    )
    assert "OPEN1" in wl["pending"] or "OPEN1" in wl["review"]
    assert wl["missing_from_portal"] == frozenset()


def test_6_partial_scrape_cannot_create_absence():
    wl = _run(
        prior_open={"OPEN1"},
        present_for_absence=None,
        absence_meta={"absence_allowed": False, "reason": "no_full_traversal"},
    )
    assert wl["missing_from_portal"] == frozenset()


def test_7_full_scrape_may_establish_absence():
    wl = _run(
        prior_open={"OPEN1", "OPEN2"},
        present_for_absence={"OPEN1"},
        absence_meta={"absence_allowed": True},
    )
    assert "OPEN2" in wl["missing_from_portal"]
    assert "OPEN2" in wl["review"]
    assert "OPEN2" in wl["bag_ids"]
    assert REVIEW_MISSING_FROM_PORTAL in (wl["bag_meta"]["OPEN2"]["review_reason_codes"])


def test_8_missing_flag_cannot_introduce_workload_membership():
    # Absence of a bag that was never a legitimate open seed must not add it.
    wl = _run(
        prior_open={"OPEN1"},
        present_for_absence={"OPEN1"},  # ghost bag GHOST not present, but also not seeded
        absence_meta={"absence_allowed": True},
    )
    assert "GHOST" not in wl["bag_ids"]
    assert "GHOST" not in wl["missing_from_portal"]


def test_9_genuine_unfinished_yesterday_carries_into_today():
    wl = _run(
        prior_open={"CARRY1"},
        prior_meta={
            "CARRY1": {
                "effective_status": "pending",
                "review_reason_codes": [],
            }
        },
    )
    assert "CARRY1" in wl["carryover"]
    assert "CARRY1" in wl["pending"]
    assert wl["bag_meta"]["CARRY1"]["new_or_carryover"] == OUTCOME_CARRYOVER


def test_10_carryover_completes_today():
    wl = _run(
        prior_open={"CARRY1"},
        completed_map={
            "CARRY1": {
                "completion_date": D,
                "completion_at": datetime(2026, 8, 28, 14, 0),
                "effective_status": "completed",
            }
        },
    )
    assert "CARRY1" in wl["completed"]
    assert "CARRY1" not in wl["pending"]
    assert "CARRY1" in wl["carryover"]  # labeled carryover even when completed today
    assert wl["bag_meta"]["CARRY1"]["effective_status"] == OUTCOME_COMPLETED


def test_11_reproject_x10_identical_membership_hash():
    import hashlib

    hashes = []
    for _ in range(10):
        wl = _run(
            prior_open={"A", "B"},
            presence={"B", "C"},
            completed_map={"A": {"completion_date": D, "effective_status": "completed"}},
            present_for_absence={"B", "C"},
            absence_meta={"absence_allowed": True},
        )
        h = hashlib.sha256(",".join(sorted(wl["bag_ids"])).encode()).hexdigest()
        hashes.append(h)
        assert_canonical_workload_invariants(wl)
    assert len(set(hashes)) == 1


def test_12_stage_b_x10_identical_membership():
    # Stage-B must not grow membership — same seeds → same set every pass.
    import hashlib

    hashes = []
    for _ in range(10):
        wl = _run(prior_open={"P1"}, presence={"N1"}, entry={"N1"})
        hashes.append(hashlib.sha256(",".join(sorted(wl["bag_ids"])).encode()).hexdigest())
    assert len(set(hashes)) == 1
    assert wl["bag_ids"] == frozenset({"P1", "N1"})


def test_13_repeated_portal_scrapes_no_membership_growth_without_new_open():
    sizes = []
    for _ in range(10):
        wl = _run(presence={"N1", "N2"}, terminal={"N2"})
        sizes.append(len(wl["bag_ids"]))
    assert sizes == [1] * 10
    assert wl["bag_ids"] == frozenset({"N1"})


def test_14_multiple_service_cycles_no_duplicate_resurrection():
    # Cycles are not consulted; duplicate cycle noise cannot resurrect.
    wl = _run(prior_open={"X"}, terminal={"X"}, presence={"X"})
    assert "X" not in wl["bag_ids"]


def test_15_workload_equals_completed_plus_pending_plus_review():
    wl = _run(
        prior_open={"C1", "P1", "R1"},
        prior_meta={
            "R1": {"effective_status": "review_required", "review_reason_codes": ["SPEC"]},
            "P1": {"effective_status": "pending", "review_reason_codes": []},
            "C1": {"effective_status": "pending", "review_reason_codes": []},
        },
        completed_map={"C1": {"completion_date": D, "effective_status": "completed"}},
        present_for_absence={"P1", "R1"},
        absence_meta={"absence_allowed": True},
    )
    assert wl["counts"]["workload"] == (
        wl["counts"]["completed"] + wl["counts"]["pending"] + wl["counts"]["review"]
    )
    assert wl["arithmetic_ok"] is True
    assert_canonical_workload_invariants(wl)


def test_lifecycle_completed_is_terminal():
    cur = MagicMock()
    with patch(
        "backend.rinse_bag_registry.get_registry_row",
        return_value={
            "completion_status": "COMPLETED",
            "completed_at": datetime(2026, 8, 20, 12, 0),
        },
    ):
        life = get_wf_bag_lifecycle(cur, ORG, "BAG1")
    assert life["lifecycle"] == LIFECYCLE_COMPLETED


def test_lifecycle_open_default():
    cur = MagicMock()
    with patch("backend.rinse_bag_registry.get_registry_row", return_value=None):
        life = get_wf_bag_lifecycle(cur, ORG, "BAG1")
    assert life["lifecycle"] == LIFECYCLE_OPEN


def test_missing_subset_of_open_only():
    wl = _run(
        prior_open={"OPEN1"},
        completed_map={"OPEN1": {"completion_date": D}},
        present_for_absence=set(),
        absence_meta={"absence_allowed": True},
    )
    # Completed bags are not open — missing must not include them.
    assert "OPEN1" not in wl["missing_from_portal"]
    assert "OPEN1" in wl["completed"]
