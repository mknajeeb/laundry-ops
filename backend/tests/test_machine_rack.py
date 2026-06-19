"""Tests for washer/dryer rack detection."""

from backend.rinse_machine_rack import (
    extract_dryer_rack,
    extract_washer_rack,
    is_dryer_rack_code,
    is_washer_rack_code,
)


class TestWasherRackDetection:
    def test_washer_codes(self):
        assert is_washer_rack_code("W24-30-VW")
        assert is_washer_rack_code("W29-40-VW")
        assert is_washer_rack_code("W28-20-VW")
        assert not is_washer_rack_code("D4-50-VW")
        assert not is_washer_rack_code("Scale")

    def test_dryer_codes(self):
        assert is_dryer_rack_code("D4-50-VW")
        assert is_dryer_rack_code("D8-35-VW")
        assert not is_dryer_rack_code("W24-30-VW")

    def test_extract_from_rack_field(self):
        ev = {"rack": "W24-30-VW", "purpose": "start-cleaning"}
        assert extract_washer_rack(ev) == "W24-30-VW"
        assert extract_dryer_rack(ev) is None

    def test_extract_from_last_location(self):
        ev = {"last_location": "D8-35-VW", "purpose": "drying"}
        assert extract_dryer_rack(ev) == "D8-35-VW"

    def test_extract_from_raw_json(self):
        ev = {
            "rack": "Scale",
            "raw_json": {"Machine": "W29-40-VW"},
            "purpose": "start-cleaning",
        }
        assert extract_washer_rack(ev) == "W29-40-VW"

    def test_prefers_rack_field_over_last_location(self):
        ev = {
            "rack": "W26-30-VW",
            "last_location": "W25-30-VW",
            "purpose": "start-cleaning",
        }
        assert extract_washer_rack(ev) == "W26-30-VW"
