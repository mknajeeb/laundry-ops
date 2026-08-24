"""Review persisted-reason loader — review_required day-bag rows only."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

ORG = 3
DAY = date(2026, 8, 24)


def test_load_persisted_reasons_review_required_only():
    from backend.rinse_veewash_shift_day import _load_persisted_review_reasons_by_bag

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": "MISSING1",
            "review_reason_codes_json": '["DISAPPEARED_WITHOUT_COMPLETION"]',
            "effective_status": "review_required",
        },
        {
            "bag_id": "COMPBULK1",
            "review_reason_codes_json": '["WF_BULK_WORKITEM_REVIEW"]',
            "effective_status": "completed",
        },
    ]
    out = _load_persisted_review_reasons_by_bag(cursor, ORG, DAY)
    assert out["MISSING1"] == ["DISAPPEARED_WITHOUT_COMPLETION"]
    assert "COMPBULK1" not in out
