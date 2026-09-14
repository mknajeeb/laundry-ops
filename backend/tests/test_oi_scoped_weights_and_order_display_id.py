"""Order display id + OI-scoped portal PRE regression tests."""

from __future__ import annotations

from datetime import date, datetime

from backend.order_display_id import (
    format_order_display_id,
    parse_order_display_id,
)
from backend.rinse_current_cycle_weight import resolve_current_cycle_weights


DAY = date(2026, 9, 13)


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


def test_format_order_display_id_with_edd():
    assert (
        format_order_display_id("8MNDJDAV8D", 5493, estimated_delivery_date="2026-09-14")
        == "8MNDJDAV8D-OI-09142026"
    )


def test_format_order_display_id_fallback_without_edd():
    assert format_order_display_id("8MNDJDAV8D", 5493) == "8MNDJDAV8D-OI-5493"


def test_parse_order_display_id_edd_and_oi_fallback():
    edd = parse_order_display_id("8MNDJDAV8D-OI-09142026")
    assert edd["bag_id"] == "8MNDJDAV8D"
    assert edd["form"] == "edd"
    assert edd["estimated_delivery_date"] == date(2026, 9, 14)

    fb = parse_order_display_id("9YTC6BJWAY-OI-5517")
    assert fb["bag_id"] == "9YTC6BJWAY"
    assert fb["order_instance_id"] == 5517
    assert fb["form"] == "oi_fallback"


def test_old_oi_portal_weight_cannot_cross_into_new_oi():
    """Prior-lifecycle portal wf_lbs must not become new OI PRE (same bag)."""
    events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 22, 40), eid=10, rack="VeeWash Dirty"),
    ]
    obs = [_obs_wf(datetime(2026, 9, 12, 22, 35), 26.7, run=7697, row_id=478387)]
    blocked = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        allow_portal_weight_fallback=False,
    )
    assert blocked.pre_weight_lbs is None

    still_blocked = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        allow_portal_weight_fallback=True,
    )
    assert still_blocked.pre_weight_lbs is None


def test_allow_portal_false_means_no_portal_pre_even_in_lifecycle():
    events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 8, 0), eid=1, rack="VeeWash Dirty"),
    ]
    obs = [_obs_wf(datetime(2026, 9, 13, 10, 0), 16.3, run=1)]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        allow_portal_weight_fallback=False,
    )
    assert resolved.pre_weight_lbs is None
    assert "portal_wf_lbs_pre_override_disabled" in (resolved.notes or ())


def test_genuine_current_cycle_preclean_still_works():
    events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 8, 0), eid=1, rack="VeeWash Dirty"),
        _ev(
            "weight-entry",
            datetime(2026, 9, 13, 9, 0),
            eid=2,
            lbs=18.2,
            weight_source="rinse_preclean_info",
            weight_role="PRE",
        ),
    ]
    obs = [_obs_wf(datetime(2026, 9, 12, 22, 0), 99.0, run=9)]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        allow_portal_weight_fallback=False,
    )
    assert resolved.pre_weight_lbs == 18.2
    assert resolved.pre_weight_source == "rinse_preclean_info"


def test_manager_correction_still_works():
    events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 8, 0), eid=1, rack="VeeWash Dirty"),
    ]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=[],
        manual_pre_lbs=21.5,
        allow_portal_weight_fallback=False,
    )
    assert resolved.pre_weight_lbs == 21.5
    assert resolved.pre_weight_source == "manager_correction"


def test_explicit_current_lifecycle_portal_fallback_still_works():
    events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 8, 0), eid=1, rack="VeeWash Dirty"),
    ]
    obs = [_obs_wf(datetime(2026, 9, 13, 10, 30), 14.4, run=2)]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=obs,
        allow_portal_weight_fallback=True,
    )
    assert resolved.pre_weight_lbs == 14.4
    assert resolved.pre_weight_source == "portal_wf_lbs_num"


def test_sep11_style_prior_oi_keeps_weight_sep13_new_oi_null():
    """Prior OI retains 26.7; Sep 13 new OI with same bag has no PRE from leak."""
    prior_events = [
        _ev("sent-to-vendor", datetime(2026, 9, 11, 7, 0), eid=1, rack="VeeWash Dirty"),
        _ev(
            "weight-entry",
            datetime(2026, 9, 11, 8, 0),
            eid=2,
            lbs=26.7,
            weight_source="rinse_preclean_info",
            weight_role="PRE",
        ),
    ]
    prior = resolve_current_cycle_weights(
        prior_events,
        selected_date_et=date(2026, 9, 11),
        observations=[],
        allow_portal_weight_fallback=False,
    )
    assert prior.pre_weight_lbs == 26.7

    new_events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 22, 40), eid=10, rack="VeeWash Dirty"),
    ]
    leaked_obs = [_obs_wf(datetime(2026, 9, 12, 22, 35), 26.7, run=7697)]
    new_oi = resolve_current_cycle_weights(
        new_events,
        selected_date_et=DAY,
        observations=leaked_obs,
        allow_portal_weight_fallback=False,
    )
    assert new_oi.pre_weight_lbs is None


def test_sep12_style_prior_oi_keeps_weight_sep13_new_oi_null():
    prior_events = [
        _ev("sent-to-vendor", datetime(2026, 9, 12, 7, 0), eid=1, rack="VeeWash Dirty"),
        _ev(
            "weight-entry",
            datetime(2026, 9, 12, 8, 0),
            eid=2,
            lbs=16.3,
            weight_source="rinse_preclean_info",
            weight_role="PRE",
        ),
    ]
    prior = resolve_current_cycle_weights(
        prior_events,
        selected_date_et=date(2026, 9, 12),
        observations=[],
        allow_portal_weight_fallback=False,
    )
    assert prior.pre_weight_lbs == 16.3

    new_events = [
        _ev("sent-to-vendor", datetime(2026, 9, 13, 22, 45), eid=10, rack="VeeWash Dirty"),
    ]
    leaked_obs = [_obs_wf(datetime(2026, 9, 12, 22, 35), 16.3, run=7697)]
    new_oi = resolve_current_cycle_weights(
        new_events,
        selected_date_et=DAY,
        observations=leaked_obs,
        allow_portal_weight_fallback=False,
    )
    assert new_oi.pre_weight_lbs is None
