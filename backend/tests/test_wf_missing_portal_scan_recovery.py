"""Portal subprocess failure classification and missing-portal scan recovery."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_scrape_subprocess_outcome import (
    FAILURE_CHROMIUM_CRASH,
    FAILURE_PAGE_NAVIGATION_HANG,
    FAILURE_PHASE_TIMEOUT,
    FAILURE_PLAYWRIGHT_HANG,
    FAILURE_STALL_NO_PROGRESS,
    classify_subprocess_failure,
)
from backend.rinse_wf_missing_portal_scan_recovery import (
    recover_missing_portal_bags_from_scan_evidence,
    scan_evidence_authorizes_terminal_completion,
)


def test_scan_evidence_rejects_disappearance_only_source():
    assert scan_evidence_authorizes_terminal_completion(
        {
            "completion_at": datetime(2026, 8, 26, 14, 0),
            "completion_source": "portal_departure_recovery",
        }
    ) is False
    assert scan_evidence_authorizes_terminal_completion(
        {
            "completion_at": datetime(2026, 8, 26, 14, 0),
            "completion_source": "clean_rack_scan",
        }
    ) is True


def test_classify_chromium_crash_from_signal():
    out = classify_subprocess_failure(returncode=-11, last_log_lines=["Segmentation fault"])
    assert out["failure_class"] == FAILURE_CHROMIUM_CRASH
    assert out["signal"] == 11


def test_classify_playwright_hang_from_log_tail():
    out = classify_subprocess_failure(
        returncode=-2,
        stalled=True,
        last_log_lines=["Playwright timeout 30000ms exceeded waiting for locator"],
    )
    assert out["failure_class"] == FAILURE_PLAYWRIGHT_HANG


def test_classify_navigation_hang_from_log_tail():
    out = classify_subprocess_failure(
        returncode=-2,
        stalled=True,
        last_log_lines=["page.goto: Navigation timeout of 30000 ms exceeded"],
    )
    assert out["failure_class"] == FAILURE_PAGE_NAVIGATION_HANG


def test_classify_phase_timeout():
    out = classify_subprocess_failure(returncode=-1, timed_out=True)
    assert out["failure_class"] == FAILURE_PHASE_TIMEOUT


def test_classify_stall_without_specific_log():
    out = classify_subprocess_failure(returncode=-2, stalled=True, last_log_lines=[])
    assert out["failure_class"] == FAILURE_STALL_NO_PROGRESS


@patch("backend.rinse_wf_service_cycle.apply_manager_review_resolution_to_canonical_cycle")
@patch("backend.rinse_wf_missing_portal_scan_recovery._resolve_authoritative_scan_completion")
@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled")
def test_recover_missing_portal_only_scan_backed(
    mock_enabled,
    mock_membership,
    mock_resolve,
    mock_apply,
):
    mock_enabled.return_value = True
    mock_membership.return_value = {
        "missing_from_portal": ["4GBT78YKCG", "E7CAWJYCVO", "0N9T0YZ2S1"],
    }

    def _resolve(_c, _o, bid, _d, canonical_comp=None):
        if bid == "4GBT78YKCG":
            return {
                "completion_at": datetime(2026, 8, 26, 12, 0),
                "completion_source": "clean_rack_scan",
            }
        return None

    mock_resolve.side_effect = _resolve
    mock_apply.return_value = {"bag_id": "4GBT78YKCG"}

    out = recover_missing_portal_bags_from_scan_evidence(
        MagicMock(),
        3,
        date(2026, 8, 26),
        bag_ids=["4GBT78YKCG", "E7CAWJYCVO", "0N9T0YZ2S1"],
    )
    assert out["missing_before"] == 3
    assert out["auto_recovered_count"] == 1
    assert out["auto_recovered"] == ["4GBT78YKCG"]
    assert sorted(out["manual_required"]) == ["0N9T0YZ2S1", "E7CAWJYCVO"]
    mock_apply.assert_called_once()
