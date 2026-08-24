"""WF PRE-weight authority pipeline — recurrence-proof regression suite."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_current_cycle_weight import (
    STATUS_MANUAL_CORRECTION,
    authoritative_evidence_pre_lbs,
    load_current_cycle_weight_map,
    resolve_current_cycle_weights,
)
from backend.management_rinse_wf_review import _canonical_review_weights, _merge_review_weight_fields
from backend.management_today import load_wf_day_weight_totals


DAY = date(2026, 8, 24)


def _ev(purpose, ts, *, lbs=None, eid=1, rack=None, **extra):
    row = {
        "id": eid,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": "Op",
        "weight_lbs": lbs,
        "rack": rack,
    }
    row.update(extra)
    return row


def _obs_wf(ts, wf_lbs, run=1, row_id=1):
    return {
        "observed_at": ts,
        "wf_lbs_num": wf_lbs,
        "presence_run_id": run,
        "presence_run_row_id": row_id,
    }


def _base_events(*, preclean=17.6):
    return [
        _ev("sent-to-vendor", datetime(2026, 8, 24, 0, 52), eid=1, rack="VeeWash Dirty"),
        _ev(
            "weight-entry",
            datetime(2026, 8, 24, 8, 44),
            eid=2,
            lbs=preclean,
            weight_source="rinse_preclean_info",
            weight_role="PRE",
        ),
    ]


def test_portal_update_beats_older_portal_and_preclean():
    events = _base_events(preclean=17.6)
    obs = [
        _obs_wf(datetime(2026, 8, 24, 12, 0), 17.6, run=1),
        _obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=2),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    assert resolved.pre_weight_lbs == 15.7
    assert resolved.pre_weight_source == "portal_wf_lbs_num"


def test_manager_correction_beats_portal_wf_lbs():
    events = _base_events()
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        manual_pre_lbs=16.2,
    )
    assert resolved.pre_weight_lbs == 16.2
    assert resolved.pre_weight_source == "manager_correction"
    assert resolved.pre_resolution_status == STATUS_MANUAL_CORRECTION


def test_clearing_manager_correction_returns_to_portal_wf_lbs():
    events = _base_events()
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    corrected = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        manual_pre_lbs=16.2,
    )
    assert corrected.pre_weight_lbs == 16.2
    restored = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        manual_pre_lbs=None,
    )
    assert restored.pre_weight_lbs == 15.7
    assert restored.pre_weight_source == "portal_wf_lbs_num"


def test_repeated_resolution_is_idempotent_with_portal_authority():
    events = _base_events()
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    first = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    second = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    third = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    for r in (first, second, third):
        assert r.pre_weight_lbs == 15.7
        assert r.pre_weight_source == "portal_wf_lbs_num"


def test_stale_day_bag_pre_does_not_override_live_resolver():
    """Simulates refresh after reset/rebuild: live resolver wins over stale day-bag column."""
    events = _base_events()
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    stale_day_bag_pre = 17.6
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    assert stale_day_bag_pre != resolved.pre_weight_lbs
    assert authoritative_evidence_pre_lbs(resolved.as_weight_info()) == 15.7


def test_fresh_portal_stops_preclean_fallback():
    events = _base_events(preclean=17.6)
    without_portal = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=[]
    )
    assert without_portal.pre_weight_lbs == 17.6
    assert without_portal.pre_weight_source == "rinse_preclean_info"

    with_portal = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=[_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)],
    )
    assert with_portal.pre_weight_lbs == 15.7
    assert with_portal.pre_weight_source == "portal_wf_lbs_num"


def test_post_processing_scan_does_not_become_pre():
    events = _base_events() + [
        _ev("garments-reviewed", datetime(2026, 8, 24, 11, 0), eid=3),
        _ev(
            "weight-entry",
            datetime(2026, 8, 24, 15, 4),
            eid=4,
            lbs=16.2,
            weight_source="rinse_workitem_wf_lbs",
            weight_role="POST",
        ),
    ]
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=obs
    )
    assert resolved.pre_weight_lbs == 15.7
    assert resolved.post_weight_lbs == 16.2


def test_service_cycle_resolution_uses_canonical_db_resolver():
    from backend.rinse_wf_service_cycle import _cycle_resolution

    anchor = datetime(2026, 8, 24, 0, 52)
    canonical = {
        "pre_weight_lbs": 15.7,
        "pre_weight_source": "portal_wf_lbs_num",
        "post_weight_lbs": None,
    }
    cursor = MagicMock()
    cycle_result = MagicMock()
    cycle_result.as_dict.return_value = {"effective_status": "pending"}
    with patch(
        "backend.rinse_current_cycle_weight.resolve_bag_weight_info_canonical",
        return_value=canonical,
    ) as mock_resolve, patch(
        "backend.rinse_wf_service_cycle._load_timeline",
        return_value=[{"purpose": "sent-to-vendor", "scanned_at_parsed": anchor, "rack": "VeeWash Dirty"}],
    ), patch(
        "backend.rinse_wf_service_cycle.resolve_current_cycle",
        return_value=cycle_result,
    ):
        _cycle, weights = _cycle_resolution(cursor, 3, "BAG1", anchor, selected_date_et=DAY)
        mock_resolve.assert_called_once_with(
            cursor,
            3,
            "BAG1",
            selected_date_et=DAY,
            cycle_anchor_override=anchor,
        )
        assert weights["pre_weight_lbs"] == 15.7
        assert weights["pre_weight_source"] == "portal_wf_lbs_num"


def test_canonical_wf_day_projection_overlays_resolver_not_stale_cycle_pre():
    from backend.rinse_wf_service_cycle_compat import _canonical_wf_bags_for_date

    cursor = MagicMock()
    cycle_row = {
        "bag_id": "BAG1",
        "admitted_at": datetime(2026, 8, 24, 1, 0),
        "status": "ACTIVE",
        "rush_status": "NON-RUSH",
        "pre_weight_lbs": 17.6,
        "post_weight_lbs": None,
        "cycle_anchor_at": datetime(2026, 8, 24, 0, 52),
        "id": 1,
    }
    cursor.fetchall.return_value = [cycle_row]
    with patch(
        "backend.rinse_veewash_review.load_bag_weight_map",
        return_value={
            "BAG1": {
                "pre_weight_lbs": 15.7,
                "pre_weight_source": "portal_wf_lbs_num",
                "post_weight_lbs": None,
            }
        },
    ), patch(
        "backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans",
    ), patch(
        "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
        side_effect=lambda b: b,
    ):
        bags = _canonical_wf_bags_for_date(cursor, 3, DAY)
        assert len(bags) == 1
        assert bags[0]["pre_weight_lbs"] == 15.7
        assert bags[0]["pre_weight_source"] == "portal_wf_lbs_num"


def test_drawer_and_headline_share_canonical_pre(monkeypatch):
    weights = {
        "BAG1": {
            "pre_weight_lbs": 15.7,
            "pre_weight_source": "portal_wf_lbs_num",
            "post_weight_lbs": 16.2,
            "post_weight_event_id": 4,
        }
    }
    monkeypatch.setattr(
        "backend.management_rinse_wf_review._canonical_review_weights",
        lambda *a, **k: weights,
    )
    bag = {}
    _merge_review_weight_fields(bag, weights["BAG1"])
    assert bag["pre_weight_lbs"] == 15.7
    assert authoritative_evidence_pre_lbs(weights["BAG1"]) == 15.7

    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: True)
    monkeypatch.setattr("backend.management_today.table_has_column", lambda *a, **k: True)

    class _Cur:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            return [{"bag_id": "BAG1", "rush_status": "NON-RUSH"}]

    monkeypatch.setattr(
        "backend.rinse_veewash_review.load_bag_weight_map",
        lambda *a, **k: weights,
    )
    totals = load_wf_day_weight_totals(_Cur(), 3, DAY)
    assert totals["pre_lbs"] == 15.7
    assert str(totals["source"]).startswith("canonical_pre_resolver")


def test_load_current_cycle_weight_map_passes_cycle_anchor_override(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_resolve(timeline, **kwargs):
        captured["cycle_anchor_override"] = kwargs.get("cycle_anchor_override")
        return resolve_current_cycle_weights(timeline, **kwargs)

    monkeypatch.setattr(
        "backend.rinse_current_cycle_weight.resolve_current_cycle_weights",
        _fake_resolve,
    )
    monkeypatch.setattr(
        "backend.rinse_current_cycle_weight._load_manual_corrections",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "backend.rinse_current_cycle_weight.load_presence_weight_observations_for_bags",
        lambda *a, **k: {"BAG1": []},
    )

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    anchor = datetime(2026, 8, 24, 0, 52)
    load_current_cycle_weight_map(
        cursor,
        3,
        ["BAG1"],
        selected_date_et=DAY,
        cycle_anchor_overrides={"BAG1": anchor},
    )
    assert captured["cycle_anchor_override"] == anchor


def test_full_refresh_sequence_stays_on_portal_authority():
    """Simulate reset → rebuild → reproject → refresh as repeated canonical resolves."""
    events = _base_events(preclean=17.6)
    obs = [_obs_wf(datetime(2026, 8, 24, 18, 45), 15.7, run=9)]
    for _ in range(4):
        resolved = resolve_current_cycle_weights(
            events, selected_date_et=DAY, observations=obs
        )
        assert resolved.pre_weight_lbs == 15.7
        assert resolved.pre_weight_source == "portal_wf_lbs_num"
        assert resolved.pre_weight_lbs != 17.6
