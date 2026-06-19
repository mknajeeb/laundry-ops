"""Tests for unified scan chronology API routing."""

from datetime import date

import pytest

from backend.rinse_scan_chronology import VALID_STAGES, build_scan_chronology_payload


class TestScanChronologyPayload:
    def test_invalid_stage_raises(self):
        with pytest.raises(ValueError, match="stage must be one of"):
            build_scan_chronology_payload(
                None,
                1,
                selected_date_et=date(2026, 6, 18),
                stage="washing",
            )

    def test_valid_stages(self):
        assert VALID_STAGES == frozenset({"weighing", "sorting"})
