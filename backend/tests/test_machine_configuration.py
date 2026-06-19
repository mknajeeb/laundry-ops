"""Tests for machine rack configuration settings."""

from unittest.mock import MagicMock, patch

from backend.machine_configuration_settings import (
    DEFAULT_DRYER_CAPACITIES,
    DEFAULT_WASHER_CAPACITIES,
    get_machine_rack_config,
    save_machine_rack_config,
)


@patch("backend.machine_configuration_settings.table_exists", return_value=True)
class TestMachineConfigurationSettings:
    def test_defaults_when_missing(self, _table_exists):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cfg = get_machine_rack_config(cursor, 1)
        assert cfg["washers"] == DEFAULT_WASHER_CAPACITIES
        assert cfg["dryers"] == DEFAULT_DRYER_CAPACITIES

    def test_saved_config_is_authoritative(self, _table_exists):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "svalue": '{"washers": {"W24-30-VW": 32}, "dryers": {"D4-50-VW": 48}}',
        }
        cfg = get_machine_rack_config(cursor, 3)
        assert cfg["washers"] == {"W24-30-VW": 32.0}
        assert cfg["dryers"] == {"D4-50-VW": 48.0}
        assert "W29-40-VW" not in cfg["washers"]

    def test_save_replaces_entire_config(self, _table_exists):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        out = save_machine_rack_config(
            cursor,
            3,
            {"washers": {"W24-30-VW": 32}, "dryers": {"D4-50-VW": 48}},
        )
        assert out["washers"] == {"W24-30-VW": 32.0}
        assert out["dryers"] == {"D4-50-VW": 48.0}
        assert "W29-40-VW" not in out["washers"]

    def test_save_allows_deleting_racks(self, _table_exists):
        cursor = MagicMock()
        out = save_machine_rack_config(
            cursor,
            3,
            {"washers": {"W24-30-VW": 32}, "dryers": {}},
        )
        assert out["washers"] == {"W24-30-VW": 32.0}
        assert "W29-40-VW" not in out["washers"]
