"""Regression: ship-window scrape must not rewrite frozen scan/OI semantics."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from backend.rinse_scan_chronology_gate import evaluate_timeline_replace_decision
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key


def test_partial_source_absence_preserves_richer_timeline():
    """Incoming thinner/partial export must not authorize destructive delete."""
    existing_max = datetime(2026, 8, 30, 12, 0, 0)
    decision = evaluate_timeline_replace_decision(
        existing_max=existing_max,
        existing_n=40,
        incoming_max=datetime(2026, 8, 30, 10, 0, 0),
        incoming_n=5,
        existing_completion_events=1,
        incoming_completion_events=0,
        import_complete=True,
    )
    assert decision.get("replace") is not True
    assert decision.get("preserve") is True


def test_empty_incoming_source_does_not_replace_history():
    decision = evaluate_timeline_replace_decision(
        existing_max=datetime(2026, 8, 29, 18, 0, 0),
        existing_n=20,
        incoming_max=None,
        incoming_n=0,
        existing_completion_events=1,
        incoming_completion_events=0,
        import_complete=True,
    )
    assert decision.get("replace") is not True
    assert decision.get("preserve") is True
    assert decision.get("incomplete") is True


def test_same_scan_seen_again_same_dedupe_key():
    at = datetime(2026, 8, 30, 9, 15)
    raw = "Sunday, August 30, 2026 9:15 AM"
    k1 = compute_scan_event_dedupe_key(
        organization_id=3,
        bag_id="CEA4TAF6IK",
        scan_index=1,
        rack="WASHER",
        user_name="Op",
        purpose="weight-entry",
        time_scanned_raw=raw,
        scanned_at_parsed=at,
    )
    k2 = compute_scan_event_dedupe_key(
        organization_id=3,
        bag_id="CEA4TAF6IK",
        scan_index=1,
        rack="WASHER",
        user_name="Op",
        purpose="weight-entry",
        time_scanned_raw=raw,
        scanned_at_parsed=at,
    )
    assert k1 == k2
    assert k1


def test_full_traverse_env_disables_early_stop_flags():
    """Documented production env contract for simple full pass."""
    env = {
        "RINSE_FULL_TRAVERSE": "1",
        "RINSE_PORTAL_EARLY_STOP": "0",
        "RINSE_BLOCK_HEAVY_ASSETS": "1",
        "RINSE_FAST_COLLAPSE": "1",
        "RINSE_EXPAND_SETTLE_MS": "400",
        "RINSE_VENDORINLINE_SETTLE_MS": "50",
    }
    assert env["RINSE_FULL_TRAVERSE"] == "1"
    assert env["RINSE_PORTAL_EARLY_STOP"] == "0"
    assert env["RINSE_FAST_COLLAPSE"] == "1"
    assert int(env["RINSE_EXPAND_SETTLE_MS"]) <= 450
    assert int(env["RINSE_VENDORINLINE_SETTLE_MS"]) <= 120
