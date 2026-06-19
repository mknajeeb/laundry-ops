"""Tests for unified scan chronology API routing."""

from datetime import date

import pytest

from backend.rinse_scan_chronology import (
    DURATION_STAGES,
    EVENT_STAGES,
    UTIL_STAGES,
    VALID_STAGES,
    build_scan_chronology_payload,
)


class TestScanChronologyPayload:
    def test_invalid_stage_raises(self):
        with pytest.raises(ValueError, match="stage must be one of"):
            build_scan_chronology_payload(
                None,
                1,
                selected_date_et=date(2026, 6, 18),
                stage="folding",
            )

    def test_valid_stages(self):
        assert VALID_STAGES == frozenset(
            {
                "weighing",
                "sorting",
                "washing",
                "drying",
                "washer_utilization",
                "dryer_utilization",
                "user_activity",
            }
        )
        assert DURATION_STAGES == frozenset({"weighing", "sorting"})
        assert EVENT_STAGES == frozenset({"washing", "drying"})
        assert UTIL_STAGES == frozenset({"washer_utilization", "dryer_utilization"})
