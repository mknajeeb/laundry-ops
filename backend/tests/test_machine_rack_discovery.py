"""Tests for rack discovery from scan events and config merge."""

from backend.machine_configuration_settings import merge_discovered_racks
from backend.rinse_machine_rack import (
    discover_racks_from_scan_events,
    parse_rack_capacity_lb,
)


class TestRackCapacityParsing:
    def test_washer_middle_segment(self):
        assert parse_rack_capacity_lb("W24-30-VW") == 30.0
        assert parse_rack_capacity_lb("W28-20-VW") == 20.0

    def test_dryer_middle_segment(self):
        assert parse_rack_capacity_lb("D4-50-VW") == 50.0
        assert parse_rack_capacity_lb("D8-50-VW") == 50.0

    def test_non_matching_code(self):
        assert parse_rack_capacity_lb("Scale") is None
        assert parse_rack_capacity_lb("") is None


class TestDiscoverRacksFromScanEvents:
    def test_collects_unique_codes_without_capacity(self):
        events = [
            {"rack": "W24-30-VW"},
            {"last_location": "D4-50-VW"},
            {"raw_json": {"Machine": "W29-40-VW"}},
            {"rack": "W24-30-VW", "last_location": "Scale"},
        ]
        out = discover_racks_from_scan_events(events)
        assert set(out["washers"]) == {"W24-30-VW", "W29-40-VW"}
        assert set(out["dryers"]) == {"D4-50-VW"}
        assert all(v is None for v in out["washers"].values())
        assert all(v is None for v in out["dryers"].values())

    def test_ignores_non_machine_codes(self):
        events = [{"rack": "Scale", "last_location": "Folding"}]
        assert discover_racks_from_scan_events(events) == {"washers": {}, "dryers": {}}


class TestMergeDiscoveredRacks:
    def test_adds_new_without_overwriting(self):
        current = {
            "washers": {"W24-30-VW": 32.0},
            "dryers": {"D4-50-VW": 48.0},
        }
        discovered = {
            "washers": {"W24-30-VW": None, "W29-40-VW": None},
            "dryers": {"D4-50-VW": None, "D8-50-VW": None},
        }
        merged, stats = merge_discovered_racks(current, discovered)
        assert merged["washers"]["W24-30-VW"] == 32.0
        assert merged["washers"]["W29-40-VW"] == 40.0
        assert merged["dryers"]["D4-50-VW"] == 48.0
        assert merged["dryers"]["D8-50-VW"] == 50.0
        assert stats == {
            "new_washers": 1,
            "new_dryers": 1,
            "existing_washers": 1,
            "existing_dryers": 1,
        }

    def test_unknown_code_uses_kind_default(self):
        current = {"washers": {}, "dryers": {}}
        discovered = {"washers": {"W99-99-VW": None}, "dryers": {"D99-99-VW": None}}
        merged, stats = merge_discovered_racks(current, discovered)
        assert merged["washers"]["W99-99-VW"] == 30.0
        assert merged["dryers"]["D99-99-VW"] == 50.0
        assert stats["new_washers"] == 1
        assert stats["new_dryers"] == 1
