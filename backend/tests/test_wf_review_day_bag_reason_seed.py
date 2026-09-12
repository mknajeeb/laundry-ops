"""Day-bag shell reason seed must match full expand codes without full rebuild."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.management_rinse_wf_review import _fresh_review_reasons_from_day_bags
from backend.rinse_veewash_workload import REASON_WF_BULK_WORKITEM_REVIEW


def test_day_bag_shell_seeds_bulk_review_for_completed_bags():
    day = date(2026, 9, 12)
    wf_rows = [
        {
            "bag_id": "COMP1",
            "service_type": "WF",
            "effective_status": "completed",
            "new_or_carryover": "new_today",
        },
        {
            "bag_id": "PEND1",
            "service_type": "WF",
            "effective_status": "pending",
            "new_or_carryover": "new_today",
        },
    ]

    def _expand(shell, **_kwargs):
        # Mimic expand_review_required: bulk only for completed.
        assert "COMP1" in (shell.get("completed_on_date") or [])
        assert "PEND1" in (shell.get("pending_end_of_date") or [])
        return {
            "review_reasons_by_bag": {
                "COMP1": [REASON_WF_BULK_WORKITEM_REVIEW],
            }
        }

    with (
        patch(
            "backend.rinse_veewash_review.load_bag_weight_map",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_review.load_registry_service_classification",
            return_value=({}, []),
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={"COMP1": {"count": 1}, "PEND1": {"count": 1}},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_scan_freshness.load_last_scan_at_by_bag",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_review.expand_review_required",
            side_effect=_expand,
        ) as expand,
    ):
        out = _fresh_review_reasons_from_day_bags(MagicMock(), 3, day, wf_rows)

    expand.assert_called_once()
    assert out == {"COMP1": [REASON_WF_BULK_WORKITEM_REVIEW]}
    assert "PEND1" not in out


def test_day_bag_shell_empty_rows_returns_empty():
    assert (
        _fresh_review_reasons_from_day_bags(
            MagicMock(), 3, date(2026, 9, 12), []
        )
        == {}
    )
