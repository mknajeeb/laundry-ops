"""Tests for shift analysis route helpers."""

from datetime import date
from unittest.mock import MagicMock

from backend.rinse_folding_period import parse_range_from_request


class TestParseRangeFromRequestContract:
    def test_returns_four_values(self):
        args = MagicMock()
        args.get.side_effect = lambda k, default=None: {
            "date_start": "2026-05-28",
            "date_end": "2026-05-28",
            "date_field": "folding_work_date",
        }.get(k, default)

        def parse_date_value(raw):
            return date.fromisoformat(str(raw))

        start, end, label, date_field = parse_range_from_request(args, parse_date_value)
        assert start == date(2026, 5, 28)
        assert end == date(2026, 5, 28)
        assert date_field == "folding_work_date"
        assert label in ("today", "custom")
