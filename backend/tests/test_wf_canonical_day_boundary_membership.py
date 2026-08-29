"""Regression: WF canonical projection must not resurrect prior-day terminal completions."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_wf_service_cycle import STATUS_ACTIVE, STATUS_COMPLETED
from backend.rinse_wf_service_cycle_compat import (
    OUTCOME_CARRYOVER_QUERY,
    _canonical_wf_bags_for_date,
    _cycle_anchor_or_admit_on_date,
    _exclude_stale_prior_day_terminal_cycles,
    _prior_day_terminal_completed_wf_bag_ids,
    final_wf_day_membership_bag_ids,
    terminal_project_canonical_wf_day_snapshot,
    wf_terminal_ineligible_bag_ids,
)
from backend.rinse_veewash_workload import OUTCOME_COMPLETED, OUTCOME_PENDING

ORG = 3
AUG24 = date(2026, 8, 24)
AUG25 = date(2026, 8, 25)
_COMPLETED_BEFORE = (
    "backend.rinse_veewash_day_membership._bags_canonically_completed_before_opening"
)
_REGISTRY_COMPLETED = (
    "backend.rinse_wf_canonical_workload._registry_completed_date_by_bag"
)
_ENRICH = "backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans"
_APPLY = "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields"
_WEIGHTS = "backend.rinse_veewash_review.load_bag_weight_map"
AUG26 = date(2026, 8, 26)
AUG28 = date(2026, 8, 28)


def _enrich_patches():
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with (
            patch(_ENRICH),
            patch(_APPLY, side_effect=lambda b: b),
            patch(_WEIGHTS, return_value={}),
        ):
            yield

    return _ctx()


def _stale_active_cycle(
    bag_id: str,
    *,
    admitted: datetime | None = None,
    anchor: datetime | None = None,
) -> dict:
    admitted = admitted or datetime(2026, 8, 24, 10, 0)
    anchor = anchor or admitted
    return {
        "id": 1,
        "bag_id": bag_id,
        "cycle_anchor_at": anchor,
        "admitted_at": admitted,
        "status": STATUS_ACTIVE,
        "completed_at": None,
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": None,
        "rush_status": None,
        "review_reason": None,
        "completion_source": None,
    }


def _prior_completed_day_bag(bag_id: str, *, completed_at: datetime) -> dict:
    return {
        "bag_id": bag_id,
        "service_type": "WF",
        "effective_status": OUTCOME_COMPLETED,
        "canonical_completion_timestamp": completed_at,
        "completion_at": completed_at,
    }


def _mock_cursor_with_cycles(cycles: list[dict]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = cycles
    return cur


def _patch_canonical_seeds(
    *,
    prior_open=None,
    prior_meta=None,
    presence=None,
    entry=None,
    registry_today=None,
    terminal=None,
    completed_map=None,
    present_for_absence=None,
):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with (
            patch(
                "backend.rinse_wf_canonical_workload._prior_day_unfinished_wf_ids",
                return_value=(set(prior_open or []), dict(prior_meta or {})),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._same_day_presence_wf_ids",
                return_value=(set(presence or []), {}, None, set()),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._discover_same_day_entry_wf_ids",
                return_value=set(entry or []),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._registry_wf_completed_on_date",
                return_value=set(registry_today or []),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._terminal_before_date",
                return_value=set(terminal or []),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._completion_date_on_d",
                return_value=dict(completed_map or {}),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._latest_absence_capable_present_ids",
                return_value=(present_for_absence, {"absence_allowed": present_for_absence is not None}),
            ),
            patch(
                "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
                return_value=set(),
            ),
            _enrich_patches(),
        ):
            yield

    return _ctx()


def test_completed_aug24_bag_does_not_appear_aug25_workload():
    with _patch_canonical_seeds(
        prior_open={"STALE01"},
        presence={"STALE01"},
        terminal={"STALE01"},
    ):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert [b["bag_id"] for b in bags] == []


def test_unfinished_aug24_bag_carries_into_aug25():
    with _patch_canonical_seeds(
        prior_open={"CARRY01"},
        prior_meta={"CARRY01": {"effective_status": OUTCOME_PENDING}},
    ):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert len(bags) == 1
    assert bags[0]["bag_id"] == "CARRY01"
    assert bags[0]["new_or_carryover"] == OUTCOME_CARRYOVER_QUERY


def test_prior_completed_bag_excluded_even_with_new_cycle_anchor():
    """Portal/cycle rediscovery cannot resurrect a historically completed bag ID."""
    with _patch_canonical_seeds(
        presence={"REOPN01"},
        entry={"REOPN01"},
        terminal={"REOPN01"},
    ):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert bags == []


def test_completed_two_days_ago_excluded():
    with _patch_canonical_seeds(presence={"OLD001"}, terminal={"OLD001"}):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert bags == []


def test_completed_today_included_as_completed():
    with _patch_canonical_seeds(
        presence={"TODAY1"},
        completed_map={
            "TODAY1": {
                "completion_date": AUG25,
                "completion_at": datetime(2026, 8, 25, 12, 0),
                "effective_status": "completed",
            }
        },
    ):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert len(bags) == 1
    assert bags[0]["bag_id"] == "TODAY1"
    assert bags[0]["effective_status"] == OUTCOME_COMPLETED


@patch("backend.rinse_wf_service_cycle_compat.load_day_bags")
def test_prior_day_terminal_set_uses_completion_et_date(load_day_bags):
    load_day_bags.return_value = [
        _prior_completed_day_bag(
            "DONE001",
            completed_at=datetime(2026, 8, 24, 23, 59),
        ),
        {
            "bag_id": "DONE002",
            "service_type": "WF",
            "effective_status": OUTCOME_COMPLETED,
            "canonical_completion_timestamp": datetime(2026, 8, 23, 12, 0),
        },
    ]
    done = _prior_day_terminal_completed_wf_bag_ids(MagicMock(), ORG, AUG25)
    assert done == {"DONE001"}


def test_cycle_anchor_or_admit_on_date_midnight_crossing():
    assert _cycle_anchor_or_admit_on_date(
        admitted_at=datetime(2026, 8, 24, 23, 50),
        cycle_anchor_at=datetime(2026, 8, 25, 0, 10),
        shift_date_et=AUG25,
    )
    assert not _cycle_anchor_or_admit_on_date(
        admitted_at=datetime(2026, 8, 24, 10, 0),
        cycle_anchor_at=datetime(2026, 8, 24, 10, 0),
        shift_date_et=AUG25,
    )


@patch(_REGISTRY_COMPLETED, return_value={})
@patch(_COMPLETED_BEFORE, return_value={"STALE01"})
def test_exclude_filter_drops_historically_completed_bag(
    _completed_before, _registry_completed
):
    bags = [
        {
            "bag_id": "STALE01",
            "bag_snapshot": {
                "admitted_at": str(datetime(2026, 8, 25, 7, 0)),
                "cycle_anchor_at": str(datetime(2026, 8, 25, 7, 0)),
            },
        },
        {"bag_id": "CARY002", "bag_snapshot": {}},
    ]
    kept = _exclude_stale_prior_day_terminal_cycles(MagicMock(), ORG, AUG25, bags)
    assert [b["bag_id"] for b in kept] == ["CARY002"]


@patch(_REGISTRY_COMPLETED, return_value={})
@patch(_COMPLETED_BEFORE, return_value={"STALE01"})
def test_final_wf_day_membership_bag_ids_is_single_admission_gate(
    _completed_before, _registry_completed
):
    kept = final_wf_day_membership_bag_ids(
        MagicMock(), ORG, AUG25, ["STALE01", "CARY002", "STALE01"]
    )
    assert kept == ["CARY002"]
    ineligible = wf_terminal_ineligible_bag_ids(
        MagicMock(), ORG, AUG25, ["STALE01", "CARY002"]
    )
    assert ineligible == {"STALE01"}


@patch(_COMPLETED_BEFORE, return_value=set())
@patch(
    _REGISTRY_COMPLETED,
    return_value={"0CBONWGV5R": AUG26},
)
def test_registry_completed_before_d_ineligible_even_when_cycle_active(
    _registry_completed, _completed_before
):
    """Aug28 incident: registry COMPLETED + stale ACTIVE cycle must still be rejected."""
    ineligible = wf_terminal_ineligible_bag_ids(
        MagicMock(), ORG, AUG28, ["0CBONWGV5R", "FRSH001"]
    )
    assert ineligible == {"0CBONWGV5R"}
    kept = final_wf_day_membership_bag_ids(
        MagicMock(), ORG, AUG28, ["0CBONWGV5R", "FRSH001"]
    )
    assert kept == ["FRSH001"]


@patch("backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags")
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN"})
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans")
@patch(
    "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
    side_effect=lambda b: b,
)
@patch(
    "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
    return_value={},
)
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(_COMPLETED_BEFORE, return_value=set())
@patch(_REGISTRY_COMPLETED, return_value={"0CBONWGV5R": AUG26})
@patch(
    "backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist",
)
def test_aug28_incident_missing_active_not_admitted_across_10_persists(
    mock_resolve,
    _registry_completed,
    _completed_before,
    _canonical_enabled,
    _prod,
    _apply,
    _enrich,
    _ensure,
    _get_day,
    _load,
    _sync,
):
    """Reproduce 21:05 writer: completed Aug26 + ACTIVE Missing review must never enter Aug28.

    Simulates cycle-based resolve still emitting the bag (ACA f7318c1e behavior) while
    the persist choke-point registry guard rejects it. Ten automatic rebuilds → growth 0.
    """
    from backend.rinse_veewash_shift_day import persist_day_snapshot
    from backend.rinse_veewash_workload import OUTCOME_REVIEW_REQUIRED

    contaminated = {
        "bag_id": "0CBONWGV5R",
        "service_type": "WF",
        "effective_status": OUTCOME_REVIEW_REQUIRED,
        "review_reason_codes": ["MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"],
        "new_or_carryover": "carryover",
        "bag_snapshot": {"cycle_status": STATUS_ACTIVE},
    }
    fresh = {
        "bag_id": "FRSH001",
        "service_type": "WF",
        "effective_status": OUTCOME_PENDING,
        "review_reason_codes": [],
        "new_or_carryover": "new_today",
        "bag_snapshot": {},
    }
    # Old cycle-based resolve would emit both; guard must drop registry-terminal.
    mock_resolve.return_value = [contaminated, fresh]
    cursor = MagicMock()
    membership_wl = {
        "rows": [contaminated, fresh],
        "new_today": ["FRSH001"],
        "carryover": ["0CBONWGV5R"],
        "completed_on_date": [],
        "pending_end_of_date": [],
        "review_required": ["0CBONWGV5R", "FRSH001"],
    }
    summary = {"completed": 0, "pending": 0, "review_required": 2}
    for _ in range(10):
        cursor.execute.reset_mock()
        persist_day_snapshot(
            cursor, ORG, AUG28, workload=membership_wl, summary=summary, force=True
        )
        upsert_calls = [
            c
            for c in cursor.execute.call_args_list
            if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
        ]
        persisted_ids = sorted({c[0][1][2] for c in upsert_calls})
        assert persisted_ids == ["FRSH001"]
        assert "0CBONWGV5R" not in persisted_ids


def test_completed_bag_seen_again_on_portal_still_excluded():
    with _patch_canonical_seeds(presence={"PORT01"}, terminal={"PORT01"}):
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert bags == []


@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[])
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={})
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
def test_terminal_project_derives_before_reconcile_and_freezes_membership(
    _day_tbl,
    _cyc_tbl,
    counts,
    _prior,
    _hd,
    headline,
    persist,
):
    """Projection must freeze get_canonical set before cycle reconcile mutates state."""
    counts.return_value = {
        "admitted_on_date": 1,
        "completed_on_date": 0,
        "opening_backlog": 0,
        "active_now": 1,
    }
    headline.return_value = {
        "completed": 0,
        "pending": 1,
        "review_required": 0,
        "segments": {"wf": {"completed": 0, "pending": 1, "review_required": 0}},
    }
    persist.return_value = {"ok": True}
    call_order: list[str] = []

    def _derive(cursor, org, day):
        call_order.append("derive")
        return {
            "bag_ids": frozenset({"FRSH001"}),
            "completed": frozenset(),
            "pending": frozenset({"FRSH001"}),
            "review": frozenset(),
            "missing_from_portal": frozenset(),
            "historical_completed_in_workload": frozenset(),
            "new_today": frozenset({"FRSH001"}),
            "carryover": frozenset(),
            "bag_meta": {
                "FRSH001": {
                    "bag_id": "FRSH001",
                    "service_type": "WF",
                    "effective_status": "pending",
                    "new_or_carryover": "new_today",
                    "review_reason_codes": [],
                }
            },
            "completion_by_bag": {},
            "prior_meta": {},
            "counts": {"workload": 1, "completed": 0, "pending": 1, "review": 0},
            "arithmetic_ok": True,
            "invariants_ok": True,
        }

    def _reconcile(cursor, org, day):
        call_order.append("reconcile")
        return {"closed": 0, "bag_ids": []}

    def _persist(*args, **kwargs):
        call_order.append("persist")
        wl = kwargs.get("workload") or {}
        assert wl.get("canonical_membership_frozen") is True
        assert set(wl.get("canonical_bag_ids") or []) == {"FRSH001"}
        return {"ok": True}

    persist.side_effect = _persist
    cur = MagicMock()
    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle_compat.get_step1_activation_date",
            return_value=date(2026, 7, 1),
        ),
        patch(
            "backend.rinse_wf_canonical_workload.get_canonical_wf_workload",
            side_effect=_derive,
        ),
        patch(
            "backend.rinse_wf_canonical_workload.canonical_wf_day_bag_rows",
            side_effect=lambda *a, **k: [
                {
                    "bag_id": "FRSH001",
                    "service_type": "WF",
                    "effective_status": "pending",
                    "new_or_carryover": "new_today",
                    "review_reason_codes": [],
                    "bag_snapshot": {},
                }
            ],
        ),
        patch(
            "backend.rinse_wf_canonical_workload.assert_canonical_workload_invariants",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            side_effect=_reconcile,
        ),
    ):
        for _ in range(10):
            call_order.clear()
            terminal_project_canonical_wf_day_snapshot(cur, ORG, AUG25)
            assert call_order == ["derive", "persist", "reconcile"]


@patch(
    "backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags",
    return_value={"headline": {}, "status_buckets": {}},
)
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value=None)
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch(
    "backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans",
    return_value=None,
)
@patch(
    "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
    side_effect=lambda b: b,
)
@patch(
    "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
    return_value={},
)
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(
    "backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist",
)
def test_persist_frozen_canonical_membership_does_not_reresolve(
    mock_resolve,
    _canonical_enabled,
    _prod,
    _apply,
    _enrich,
    _ensure,
    _get_day,
    _load,
    _sync,
):
    """Frozen workload from terminal_project must not call resolve again."""
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    fresh = {
        "bag_id": "FRSH001",
        "service_type": "WF",
        "effective_status": "pending",
        "review_reason_codes": [],
        "new_or_carryover": "new_today",
        "bag_snapshot": {},
    }
    mock_resolve.return_value = [
        {**fresh, "bag_id": "SHOULD_NOT_APPEAR"},
    ]
    cursor = MagicMock()
    wl = {
        "rows": [fresh],
        "new_today": ["FRSH001"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["FRSH001"],
        "review_required": [],
        "from_snapshot": True,
        "canonical_membership_frozen": True,
        "canonical_bag_ids": ["FRSH001"],
    }
    persist_day_snapshot(
        cursor,
        ORG,
        AUG25,
        workload=wl,
        summary={"membership": {"canonical_source": True}},
        force=True,
    )
    mock_resolve.assert_not_called()
    upsert_calls = [
        c
        for c in cursor.execute.call_args_list
        if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
    ]
    persisted_ids = sorted({c[0][1][2] for c in upsert_calls})
    assert persisted_ids == ["FRSH001"]


def test_active_null_completed_at_still_excluded():
    # Stale ACTIVE cycle alone (no legitimate seed) cannot admit.
    with _patch_canonical_seeds():
        bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert bags == []


@patch(_REGISTRY_COMPLETED, return_value={})
@patch(_COMPLETED_BEFORE, return_value={"STALE01"})
@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[])
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id")
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
@patch("backend.rinse_wf_service_cycle_compat.load_day_bags")
def test_terminal_projection_idempotent_drops_stale_completed(
    load_day_bags,
    _day_tbl,
    _cyc_tbl,
    counts,
    prior_by_id,
    _hd,
    headline,
    persist,
    _completed_before,
    _registry_completed,
):
    load_day_bags.side_effect = lambda _c, _o, d: (
        [_prior_completed_day_bag("STALE01", completed_at=datetime(2026, 8, 24, 13, 0))]
        if d == AUG24
        else []
    )
    prior_by_id.return_value = {}
    counts.return_value = {
        "admitted_on_date": 1,
        "completed_on_date": 0,
        "opening_backlog": 1,
        "active_now": 1,
    }
    headline.return_value = {
        "completed": 0,
        "pending": 1,
        "review_required": 0,
        "segments": {"wf": {"completed": 0, "pending": 1, "review_required": 0}},
    }
    persist.return_value = {"ok": True}
    cur = MagicMock()
    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle_compat.get_step1_activation_date",
            return_value=date(2026, 7, 1),
        ),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
        _patch_canonical_seeds(
            presence={"FRSH001"},
            terminal={"STALE01"},
        ),
    ):
        terminal_project_canonical_wf_day_snapshot(cur, ORG, AUG25)
    workload = persist.call_args.kwargs.get("workload") or persist.call_args[1]["workload"]
    assert "STALE01" not in (workload.get("pending_end_of_date") or [])
    assert "STALE01" not in (workload.get("new_today") or [])
    assert "STALE01" not in (workload.get("carryover") or [])
    assert "FRSH001" in (workload.get("new_today") or [])


@patch("backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags")
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN"})
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans")
@patch("backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields", side_effect=lambda b: b)
@patch("backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag", return_value={})
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(
    "backend.rinse_wf_service_cycle_compat.apply_wf_selected_day_boundary_guard",
    side_effect=lambda _c, _o, _d, bags: bags,
)
@patch("backend.rinse_wf_service_cycle_compat.wf_terminal_ineligible_bag_ids", return_value=set())
@patch("backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist")
def test_persist_day_snapshot_replaces_stage_b_wf_with_canonical_membership(
    resolve_canonical,
    _ineligible,
    _guard,
    _enabled,
    _proj,
    _apply,
    _enrich,
    _ensure,
    _day,
    _load,
    _sync,
):
    """Stage-B append-only membership must not persist — canonical replace is authoritative."""
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    resolve_canonical.return_value = [
        {
            "bag_id": "FRSH001",
            "service_type": "WF",
            "effective_status": OUTCOME_PENDING,
            "new_or_carryover": "opening_new",
            "bag_snapshot": {
                "admitted_at": str(datetime(2026, 8, 25, 9, 0)),
                "cycle_anchor_at": str(datetime(2026, 8, 25, 9, 0)),
                "canonical_projection": True,
            },
        }
    ]
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    wl = {
        "rows": [
            {
                "bag_id": "STALE01",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "new_or_carryover": "opening_new",
                "bag_snapshot": {
                    "admitted_at": str(datetime(2026, 8, 24, 23, 9)),
                    "cycle_anchor_at": str(datetime(2026, 8, 24, 23, 9)),
                },
            },
            {
                "bag_id": "FRSH001",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "new_or_carryover": "opening_new",
                "bag_snapshot": {
                    "admitted_at": str(datetime(2026, 8, 25, 9, 0)),
                    "cycle_anchor_at": str(datetime(2026, 8, 25, 9, 0)),
                },
            },
        ],
        "new_today": ["STALE01", "FRSH001"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["STALE01", "FRSH001"],
        "review_required": [],
    }
    summary = {"completed": 0, "pending": 2, "review_required": 0}
    persist_day_snapshot(cursor, ORG, AUG25, workload=wl, summary=summary, force=True)
    upsert_calls = [
        c
        for c in cursor.execute.call_args_list
        if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
    ]
    assert upsert_calls
    persisted_ids = [c[0][1][2] for c in upsert_calls]
    assert "STALE01" not in persisted_ids
    assert "FRSH001" in persisted_ids
    delete_sql = next(
        (str(c[0][0]) for c in cursor.execute.call_args_list if "DELETE FROM rinse_shift_monitor_day_bags" in str(c[0][0])),
        "",
    )
    assert "DELETE FROM rinse_shift_monitor_day_bags" in delete_sql


@patch("backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags")
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN"})
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans")
@patch("backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields", side_effect=lambda b: b)
@patch("backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag", return_value={})
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(
    "backend.rinse_wf_service_cycle_compat.apply_wf_selected_day_boundary_guard",
    side_effect=lambda _c, _o, _d, bags: [
        b for b in bags if normalize_bag_id(b.get("bag_id")) != "STALE01"
    ],
)
@patch("backend.rinse_wf_service_cycle_compat.wf_terminal_ineligible_bag_ids", return_value={"STALE01"})
@patch(
    "backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist",
    side_effect=RuntimeError("resolver timeout"),
)
def test_persist_fail_closed_excludes_historical_when_canonical_replace_fails(
    _resolve,
    _ineligible,
    _guard,
    _enabled,
    _proj,
    _apply,
    _enrich,
    _ensure,
    _day,
    _load,
    _sync,
):
    """If canonical replace throws, persist zero WF bags — never Stage-B fallback."""
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    wl = {
        "rows": [
            {
                "bag_id": "STALE01",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "bag_snapshot": {},
            },
            {
                "bag_id": "FRSH001",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "bag_snapshot": {},
            },
        ],
        "new_today": ["STALE01", "FRSH001"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["STALE01", "FRSH001"],
        "review_required": [],
    }
    persist_day_snapshot(
        cursor, ORG, AUG25, workload=wl, summary={"pending": 2}, force=True
    )
    upsert_calls = [
        c
        for c in cursor.execute.call_args_list
        if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
    ]
    persisted_ids = sorted({c[0][1][2] for c in upsert_calls})
    assert persisted_ids == []


@patch("backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags")
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN"})
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans")
@patch("backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields", side_effect=lambda b: b)
@patch("backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag", return_value={})
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(
    "backend.rinse_wf_service_cycle_compat.apply_wf_selected_day_boundary_guard",
    side_effect=lambda _c, _o, _d, bags: bags,
)
@patch("backend.rinse_wf_service_cycle_compat.wf_terminal_ineligible_bag_ids", return_value=set())
@patch("backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist")
def test_persist_day_snapshot_idempotent_across_repeated_automatic_rebuilds(
    resolve_canonical,
    _ineligible,
    _guard,
    _enabled,
    _proj,
    _apply,
    _enrich,
    _ensure,
    _day,
    _load,
    _sync,
):
    """Repeated Stage-B/specialty persist passes must not grow WF membership."""
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    canonical_rows = [
        {
            "bag_id": "FRSH001",
            "service_type": "WF",
            "effective_status": OUTCOME_PENDING,
            "new_or_carryover": "opening_new",
            "bag_snapshot": {"cycle_id": 9, "canonical_projection": True},
        }
    ]
    resolve_canonical.return_value = canonical_rows
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    membership_wl = {
        "rows": [
            {
                "bag_id": "STALE01",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "bag_snapshot": {},
            },
            {
                "bag_id": "FRSH001",
                "service_type": "WF",
                "effective_status": OUTCOME_PENDING,
                "bag_snapshot": {},
            },
        ],
        "new_today": ["STALE01", "FRSH001"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["STALE01", "FRSH001"],
        "review_required": [],
    }
    summary = {"completed": 0, "pending": 2, "review_required": 0}
    for _ in range(5):
        cursor.execute.reset_mock()
        persist_day_snapshot(
            cursor, ORG, AUG25, workload=membership_wl, summary=summary, force=True
        )
        upsert_calls = [
            c
            for c in cursor.execute.call_args_list
            if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
        ]
        persisted_ids = sorted({c[0][1][2] for c in upsert_calls})
        assert persisted_ids == ["FRSH001"]


@patch(_REGISTRY_COMPLETED, return_value={})
@patch(_COMPLETED_BEFORE, return_value={"STALE01"})
@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[])
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={})
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
@patch("backend.rinse_wf_service_cycle_compat.load_day_bags")
def test_automatic_terminal_rebuild_idempotent_three_passes(
    load_day_bags,
    _day_tbl,
    _cyc_tbl,
    counts,
    _prior,
    _hd,
    headline,
    persist,
    _completed_before,
    _registry_completed,
):
    """Simulate repeated scrape finalize projections — membership must stay at guarded size."""
    load_day_bags.side_effect = lambda _c, _o, d: (
        [_prior_completed_day_bag("STALE01", completed_at=datetime(2026, 8, 24, 13, 0))]
        if d == AUG24
        else []
    )
    counts.return_value = {
        "admitted_on_date": 1,
        "completed_on_date": 0,
        "opening_backlog": 0,
        "active_now": 1,
    }
    headline.return_value = {
        "completed": 0,
        "pending": 1,
        "review_required": 0,
        "segments": {"wf": {"completed": 0, "pending": 1, "review_required": 0}},
    }
    persist.return_value = {"ok": True}
    cur = MagicMock()
    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle_compat.get_step1_activation_date",
            return_value=date(2026, 7, 1),
        ),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
        _patch_canonical_seeds(
            presence={"FRSH001"},
            terminal={"STALE01"},
        ),
    ):
        for _ in range(3):
            terminal_project_canonical_wf_day_snapshot(cur, ORG, AUG25)
    workloads = [
        (c.kwargs.get("workload") or c[1]["workload"])
        for c in persist.call_args_list
    ]
    assert len(workloads) == 3
    for wl in workloads:
        ids = {r.get("bag_id") for r in (wl.get("rows") or [])}
        assert "STALE01" not in ids
        assert "FRSH001" in ids
        assert len(ids) == 1


@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[])
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={})
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
@patch("backend.rinse_wf_service_cycle_compat.load_day_bags")
def test_workload_headline_equals_completed_plus_pending_plus_review(
    load_day_bags,
    _day_tbl,
    _cyc_tbl,
    counts,
    _prior,
    _hd,
    headline,
    persist,
):
    load_day_bags.return_value = []
    counts.return_value = {"admitted_on_date": 3, "completed_on_date": 1, "opening_backlog": 0}
    headline.return_value = {
        "completed": 1,
        "pending": 1,
        "review_required": 1,
        "segments": {
            "wf": {
                "completed": 1,
                "pending": 1,
                "review_required": 1,
                "bag_ids": {
                    "completed": ["COMP001"],
                    "pending": ["PEND001"],
                    "review_required": ["REVW001"],
                },
            }
        },
    }
    persist.return_value = {"ok": True}
    cur = MagicMock()
    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle_compat.get_step1_activation_date",
            return_value=date(2026, 7, 1),
        ),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
        _patch_canonical_seeds(
            presence={"COMP001", "PEND001", "REVW001"},
            prior_meta={
                "REVW001": {
                    "effective_status": "review_required",
                    "review_reason_codes": ["MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"],
                }
            },
            prior_open={"REVW001"},
            completed_map={
                "COMP001": {
                    "completion_date": AUG25,
                    "completion_at": datetime(2026, 8, 25, 12, 0),
                    "effective_status": "completed",
                }
            },
            present_for_absence={"COMP001", "PEND001"},
        ),
    ):
        terminal_project_canonical_wf_day_snapshot(cur, ORG, AUG25)
    summary = persist.call_args.kwargs.get("summary") or persist.call_args[1]["summary"]
    wf = summary["segments"]["wf"]
    assert wf["completed"] + wf["pending"] + wf["review_required"] == 3


def test_pre_resolver_does_not_create_day_membership_by_itself():
    """PRE weight enrichment must not admit historically completed bags."""
    weight_map = {"STALE01": {"pre_weight_lbs": 99.0, "pre_weight_source": "PRE"}}
    with _patch_canonical_seeds(presence={"STALE01"}, terminal={"STALE01"}):
        with patch(_WEIGHTS, return_value=weight_map):
            bags = _canonical_wf_bags_for_date(MagicMock(), ORG, AUG25)
    assert bags == []


AUG26 = date(2026, 8, 26)
AUG27 = date(2026, 8, 27)
_CLEAN_AUG26_WORKLOAD = 126


def _clean_aug26_day_record() -> dict:
    return {
        "status": "OPEN",
        "shift_date_et": AUG26.isoformat(),
        "headline": {
            "segments": {
                "wf": {
                    "total_workload": _CLEAN_AUG26_WORKLOAD,
                    "completed": 101,
                    "pending": 0,
                    "review_required": 25,
                    "exceptions": {"review_required": 25},
                }
            }
        },
    }


@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[{"bag_id": f"B{i}"} for i in range(_CLEAN_AUG26_WORKLOAD)])
@patch("backend.rinse_veewash_shift_day.summary_from_day_record")
@patch("backend.rinse_veewash_shift_day.get_day_record")
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch("backend.rinse_wf_service_cycle_compat.terminal_project_canonical_wf_day_snapshot")
@patch("backend.rinse_veewash_workload.build_veewash_daily_workload_from_membership")
@patch("backend.rinse_veewash_shift_day.today_et", return_value=AUG27)
def test_historical_backfill_uses_terminal_canonical_not_additive_membership(
    mock_today,
    mock_membership,
    mock_terminal,
    _canonical_enabled,
    mock_get_day,
    mock_summary,
    _load_day_bags,
):
    """Aug 26 must not re-enter via append-only Stage-B when today is Aug 27."""
    from backend.rinse_veewash_shift_day import backfill_day_from_live

    mock_get_day.return_value = _clean_aug26_day_record()
    mock_terminal.return_value = {"ok": True, "shift_date_et": AUG26.isoformat()}
    mock_summary.return_value = _clean_aug26_day_record()["headline"]

    out = backfill_day_from_live(
        MagicMock(),
        ORG,
        AUG26,
        force=True,
        bypass_evidence_gate=True,
    )

    assert out.get("historical_canonical_reproject") is True
    assert out.get("ok") is True
    mock_terminal.assert_called_once()
    mock_membership.assert_not_called()


@patch(_REGISTRY_COMPLETED, return_value={})
@patch(_COMPLETED_BEFORE, return_value=set())
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[{"bag_id": f"B{i}"} for i in range(_CLEAN_AUG26_WORKLOAD)])
@patch("backend.rinse_veewash_shift_day.summary_from_day_record")
@patch("backend.rinse_veewash_shift_day.get_day_record")
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch("backend.rinse_wf_service_cycle_compat.terminal_project_canonical_wf_day_snapshot")
@patch("backend.rinse_veewash_workload.build_veewash_daily_workload_from_membership")
@patch("backend.rinse_veewash_shift_day.today_et", return_value=AUG27)
def test_next_day_sync_does_not_resurrect_historical_completed_on_aug26(
    mock_today,
    mock_membership,
    mock_terminal,
    _canonical_enabled,
    mock_get_day,
    mock_summary,
    _load_day_bags,
    _completed_before,
    _registry_completed,
):
    """Clean Aug 26 canonical snapshot stays 126 after next-day sync/rebuild."""
    from backend.rinse_veewash_shift_day import backfill_day_from_live

    mock_terminal.return_value = {
        "ok": True,
        "bag_count": _CLEAN_AUG26_WORKLOAD,
    }
    mock_get_day.return_value = _clean_aug26_day_record()
    mock_summary.return_value = _clean_aug26_day_record()["headline"]

    out = backfill_day_from_live(
        MagicMock(),
        ORG,
        AUG26,
        force=True,
        bypass_evidence_gate=True,
    )

    assert out.get("historical_canonical_reproject") is True
    assert out.get("bag_count") == _CLEAN_AUG26_WORKLOAD
    mock_membership.assert_not_called()
    mock_terminal.assert_called_once()


def test_preserved_hd_excludes_canonical_wf_bag_ids():
    """Stale HD labels for bags in desired WF set must not be re-injected."""
    from backend.rinse_wf_service_cycle_compat import _preserved_hd_bag_dicts

    prior_rows = [
        {
            "bag_id": "WFHD001",
            "service_type": "HD",
            "effective_status": "pending",
            "review_reason_codes": [],
            "bag_snapshot": {},
        },
        {
            "bag_id": "HDONLY1",
            "service_type": "HD",
            "effective_status": "pending",
            "review_reason_codes": [],
            "bag_snapshot": {},
        },
    ]
    with (
        patch(
            "backend.rinse_wf_service_cycle_compat.load_day_bags",
            return_value=prior_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value={"HDONLY1", "WFHD001"},
        ),
    ):
        out = _preserved_hd_bag_dicts(
            MagicMock(), ORG, AUG28, exclude_bag_ids={"WFHD001"}
        )
    assert [b["bag_id"] for b in out] == ["HDONLY1"]


def test_preserved_hd_reclassifies_mislabeled_wf_authoritative_hd():
    """Authoritative HD bag wrongly persisted as WF must be kept as HD when not in desired WF."""
    from backend.rinse_wf_service_cycle_compat import _preserved_hd_bag_dicts

    prior_rows = [
        {
            "bag_id": "7M07HHS5BU",
            "service_type": "WF",
            "effective_status": "review_required",
            "review_reason_codes": ["MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"],
            "bag_snapshot": {},
        },
        {
            "bag_id": "WFKEEP1",
            "service_type": "WF",
            "effective_status": "pending",
            "review_reason_codes": [],
            "bag_snapshot": {},
        },
    ]
    with (
        patch(
            "backend.rinse_wf_service_cycle_compat.load_day_bags",
            return_value=prior_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value={"7M07HHS5BU"},
        ),
    ):
        out = _preserved_hd_bag_dicts(
            MagicMock(), ORG, AUG28, exclude_bag_ids={"WFKEEP1"}
        )
    assert len(out) == 1
    assert out[0]["bag_id"] == "7M07HHS5BU"
    assert out[0]["service_type"] == "HD"


@patch(
    "backend.rinse_veewash_shift_day._sync_day_header_from_persisted_bags",
    return_value={"headline": {}, "status_buckets": {}},
)
@patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[])
@patch("backend.rinse_veewash_shift_day.get_day_record", return_value=None)
@patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables")
@patch(
    "backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans",
    return_value=None,
)
@patch(
    "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
    side_effect=lambda b: b,
)
@patch(
    "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
    return_value={},
)
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch(
    "backend.rinse_wf_service_cycle_compat.apply_wf_selected_day_boundary_guard",
    side_effect=lambda _c, _o, _d, bags: bags,
)
@patch("backend.rinse_wf_service_cycle_compat.wf_terminal_ineligible_bag_ids", return_value=set())
@patch(
    "backend.rinse_wf_service_cycle_compat.resolve_canonical_wf_day_bag_rows_for_persist",
)
def test_persist_wf_wins_over_colliding_hd_label(
    mock_resolve,
    _ineligible,
    _guard,
    _canonical_enabled,
    _prod,
    _apply,
    _enrich,
    _ensure,
    _get_day,
    _load,
    _sync,
):
    """Frozen WF row must not be overwritten by a duplicate HD bag_id on upsert."""
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    mock_resolve.return_value = []
    cursor = MagicMock()
    wl = {
        "rows": [
            {
                "bag_id": "2QFDTDTULL",
                "service_type": "WF",
                "effective_status": "pending",
                "review_reason_codes": [],
                "new_or_carryover": "new_today",
                "bag_snapshot": {"service_type": "WF"},
            },
            {
                "bag_id": "2QFDTDTULL",
                "service_type": "HD",
                "effective_status": "pending",
                "review_reason_codes": [],
                "new_or_carryover": "new_today",
                "bag_snapshot": {"service_type": "HD"},
            },
            {
                "bag_id": "HDONLY1",
                "service_type": "HD",
                "effective_status": "pending",
                "review_reason_codes": [],
                "new_or_carryover": "new_today",
                "bag_snapshot": {"service_type": "HD"},
            },
        ],
        "new_today": ["2QFDTDTULL", "HDONLY1"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["2QFDTDTULL", "HDONLY1"],
        "review_required": [],
        "from_snapshot": True,
        "canonical_membership_frozen": True,
        "canonical_bag_ids": ["2QFDTDTULL"],
    }
    persist_day_snapshot(
        cursor,
        ORG,
        AUG28,
        workload=wl,
        summary={"membership": {"canonical_source": True}},
        force=True,
    )
    mock_resolve.assert_not_called()
    upsert_calls = [
        c
        for c in cursor.execute.call_args_list
        if c[0] and "INSERT INTO rinse_shift_monitor_day_bags" in str(c[0][0])
    ]
    by_id: dict[str, str] = {}
    for c in upsert_calls:
        params = c[0][1]
        by_id[params[2]] = str(params[3] or "").upper()
    assert by_id == {"2QFDTDTULL": "WF", "HDONLY1": "HD"}


@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={})
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
def test_terminal_project_excludes_stale_hd_from_desired_wf_set(
    _day_tbl,
    _cyc_tbl,
    counts,
    _prior,
    headline,
    persist,
):
    """terminal_project must not merge stale HD rows for canonical WF bag IDs."""
    counts.return_value = {
        "admitted_on_date": 1,
        "completed_on_date": 0,
        "opening_backlog": 0,
        "active_now": 1,
    }
    headline.return_value = {
        "completed": 0,
        "pending": 1,
        "review_required": 0,
        "segments": {"wf": {"completed": 0, "pending": 1, "review_required": 0}},
    }
    persist.return_value = {"ok": True}
    cur = MagicMock()

    def _fake_hd(cursor, org, day, *, exclude_bag_ids=None):
        exclude = {normalize_bag_id(b) for b in (exclude_bag_ids or set()) if normalize_bag_id(b)}
        rows = [
            {
                "bag_id": "2QFDTDTULL",
                "service_type": "HD",
                "effective_status": "pending",
                "review_reason_codes": [],
                "bag_snapshot": {},
            },
            {
                "bag_id": "HDONLY1",
                "service_type": "HD",
                "effective_status": "pending",
                "review_reason_codes": [],
                "bag_snapshot": {},
            },
        ]
        return [r for r in rows if r["bag_id"] not in exclude]

    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle_compat.get_step1_activation_date",
            return_value=date(2026, 7, 1),
        ),
        patch(
            "backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts",
            side_effect=_fake_hd,
        ),
        patch(
            "backend.rinse_wf_canonical_workload.get_canonical_wf_workload",
            return_value={
                "bag_ids": frozenset({"2QFDTDTULL"}),
                "completed": frozenset(),
                "pending": frozenset({"2QFDTDTULL"}),
                "review": frozenset(),
                "missing_from_portal": frozenset(),
                "historical_completed_in_workload": frozenset(),
                "new_today": frozenset({"2QFDTDTULL"}),
                "carryover": frozenset(),
                "bag_meta": {
                    "2QFDTDTULL": {
                        "bag_id": "2QFDTDTULL",
                        "service_type": "WF",
                        "effective_status": "pending",
                        "new_or_carryover": "new_today",
                        "review_reason_codes": [],
                    }
                },
                "completion_by_bag": {},
                "prior_meta": {},
                "counts": {"workload": 1, "completed": 0, "pending": 1, "review": 0},
                "arithmetic_ok": True,
                "invariants_ok": True,
            },
        ),
        patch(
            "backend.rinse_wf_canonical_workload.canonical_wf_day_bag_rows",
            return_value=[
                {
                    "bag_id": "2QFDTDTULL",
                    "service_type": "WF",
                    "effective_status": "pending",
                    "new_or_carryover": "new_today",
                    "review_reason_codes": [],
                    "bag_snapshot": {},
                }
            ],
        ),
        patch(
            "backend.rinse_wf_canonical_workload.assert_canonical_workload_invariants",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
    ):
        terminal_project_canonical_wf_day_snapshot(cur, ORG, AUG28)

    workload = persist.call_args.kwargs.get("workload") or persist.call_args[1]["workload"]
    rows = workload.get("rows") or []
    by_id = {normalize_bag_id(r.get("bag_id")): r for r in rows}
    assert by_id["2QFDTDTULL"]["service_type"] == "WF"
    assert by_id["HDONLY1"]["service_type"] == "HD"
    assert set(workload.get("canonical_bag_ids") or []) == {"2QFDTDTULL"}
    # Frozen path: public canonical count matches WF rows fed to persist.
    wf_row_ids = {
        normalize_bag_id(r.get("bag_id"))
        for r in rows
        if str(r.get("service_type") or "").upper() == "WF"
    }
    assert wf_row_ids == set(workload.get("canonical_bag_ids") or [])
