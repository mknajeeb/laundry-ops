"""Tests for bag volume labor forecast settings schema."""

from backend.payroll_bag_volume_forecast import (
    DEFAULT_BAG_VOLUME_FORECAST,
    compute_bag_volume_forecast_placeholder,
    merge_legacy_forecast_assumptions,
    validate_bag_volume_forecast,
)


def test_default_schema_has_calculations_disabled():
    assert DEFAULT_BAG_VOLUME_FORECAST["calculations_enabled"] is False
    assert DEFAULT_BAG_VOLUME_FORECAST["default_method"] == "compare"


def test_validate_role_speed_parameter():
    data = {
        "default_method": "planning",
        "role_speed_parameters": [
            {
                "role_id": 1,
                "work_stream_id": 2,
                "unit_type": "bags_per_hour",
                "planning_speed": 4,
                "active": True,
            }
        ],
    }
    assert validate_bag_volume_forecast(data) == []


def test_validate_rejects_duplicate():
    data = {
        "default_method": "compare",
        "role_speed_parameters": [
            {"role_id": 1, "work_stream_id": 2, "unit_type": "bags_per_hour", "planning_speed": 4},
            {"role_id": 1, "work_stream_id": 2, "unit_type": "bags_per_hour", "planning_speed": 5},
        ],
    }
    errs = validate_bag_volume_forecast(data)
    assert any("Duplicate" in e for e in errs)


def test_merge_legacy_weight():
    out = merge_legacy_forecast_assumptions({}, {"average_rinse_bag_weight_lbs": 22})
    assert float(out["global_defaults"]["average_bag_weight_lbs"]) == 22.0


def test_placeholder_disabled():
    out = compute_bag_volume_forecast_placeholder(settings=DEFAULT_BAG_VOLUME_FORECAST, bag_count=100)
    assert out["status"] == "disabled"
