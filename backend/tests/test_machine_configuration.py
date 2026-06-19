"""Tests for machine rack configuration settings."""

from unittest.mock import MagicMock

from backend.machine_configuration_settings import (
    DEFAULT_DRYER_CAPACITIES,
    DEFAULT_WASHER_CAPACITIES,
    get_machine_rack_config,
    save_machine_rack_config,
)


class TestMachineConfigurationSettings:
    def test_defaults_when_missing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cfg = get_machine_rack_config(cursor, 1)
        assert cfg["washers"] == DEFAULT_WASHER_CAPACITIES
        assert cfg["dryers"] == DEFAULT_DRYER_CAPACITIES

    def test_save_returns_merged_values(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        out = save_machine_rack_config(
            cursor,
            3,
            {"washers": {"W24-30-VW": 32}, "dryers": {"D4-50-VW": 48}},
        )
        assert out["washers"]["W24-30-VW"] == 32.0
        assert out["dryers"]["D4-50-VW"] == 48.0
        assert out["washers"]["W29-40-VW"] == DEFAULT_WASHER_CAPACITIES["W29-40-VW"]
