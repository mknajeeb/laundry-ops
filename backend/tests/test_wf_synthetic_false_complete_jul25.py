"""Regression: synthetic near-complete weight must not complete WF Step-1.

Production bag BHLNPU0MJH (org 3, 2026-07-25) was marked COMPLETED via
``evaluate_bag_completion_v2:second-weight-entry`` solely because a
``near_complete_wf_weight_backfill`` synthetic weight-entry was inserted while
the bag remained active on VeeWash Dirty with only one real portal weight.
"""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
from backend.rinse_near_complete_wf_backfill import BACKFILL_SOURCE

DAY = date(2026, 7, 25)
BAG = "BHLNPU0MJH"


def _bhln_timeline(*, include_synthetic: bool = True):
    """Portal evidence for BHLNPU0MJH — Dirty, one real weight, complete-cleaning."""
    rows = [
        {
            "id": 1551625,
            "purpose": "sent-to-vendor",
            "rack": "VeeWash Dirty",
            "user_name": "Shaday Snipes",
            "scanned_at_parsed": datetime(2026, 7, 25, 5, 54),
            "source_filename": "batch_confirm_2935",
        },
        {
            "id": 1551626,
            "purpose": "weight-entry",
            "rack": None,
            "user_name": "Varun (VeeWash)",
            "weight_lbs": 14.8,
            "scanned_at_parsed": datetime(2026, 7, 25, 6, 40),
            "source_filename": "batch_confirm_2935",
        },
        {
            "id": 1551629,
            "purpose": "split-load",
            "rack": None,
            "user_name": "Francis (Veewash)",
            "scanned_at_parsed": datetime(2026, 7, 25, 11, 3),
            "source_filename": "batch_confirm_2935",
        },
        {
            "id": 1551636,
            "purpose": "complete-cleaning Last Scan",
            "rack": None,
            "user_name": "Varun (VeeWash)",
            "scanned_at_parsed": datetime(2026, 7, 25, 11, 50),
            "source_filename": "batch_confirm_2935",
        },
    ]
    if include_synthetic:
        rows.append(
            {
                "id": 1552036,
                "purpose": "weight-entry",
                "rack": None,
                "user_name": "Varun (VeeWash)",
                "weight_lbs": 14.8,
                "scanned_at_parsed": datetime(2026, 7, 25, 11, 51),
                "source_filename": BACKFILL_SOURCE,
                "raw_json": {
                    "synthetic": True,
                    "backfill_source": BACKFILL_SOURCE,
                },
            }
        )
    return rows


def test_bhlnpu0mjh_synthetic_second_weight_does_not_complete():
    result = evaluate_bag_completion_v2(_bhln_timeline(include_synthetic=True))
    assert result.completed is False
    assert result.completion_kind is None
    assert result.via_clean_rack is False


def test_bhlnpu0mjh_without_synthetic_is_pending():
    result = evaluate_bag_completion_v2(_bhln_timeline(include_synthetic=False))
    assert result.completed is False


def test_real_portal_second_weight_still_completes():
    """Legitimate post-clean portal weight-entry remains authoritative."""
    timeline = _bhln_timeline(include_synthetic=False) + [
        {
            "id": 999,
            "purpose": "weight-entry Last Scan",
            "rack": None,
            "user_name": "Evelin (VeeWash)",
            "weight_lbs": 14.5,
            "scanned_at_parsed": datetime(2026, 7, 25, 12, 10),
            "source_filename": "batch_confirm_2935",
        }
    ]
    result = evaluate_bag_completion_v2(timeline)
    assert result.completed is True
    assert result.completion_kind == "second-weight-entry"
    assert result.via_clean_rack is False


def test_jul25_regression_fixture_identity():
    assert BAG == "BHLNPU0MJH"
    assert DAY.isoformat() == "2026-07-25"
