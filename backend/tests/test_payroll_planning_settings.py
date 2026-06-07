"""Tests for payroll planning maintenance extras."""


def test_default_scheduling_extras():
    from backend.payroll_planning_settings import DEFAULT_SCHEDULING_EXTRAS

    assert DEFAULT_SCHEDULING_EXTRAS["late_grace_minutes"] == 10


def test_save_and_load_extras_roundtrip():
    from unittest.mock import MagicMock, patch

    from backend.payroll_planning_settings import (
        get_planning_maintenance_extras,
        save_planning_maintenance_extras,
    )

    store = {}

    def fake_get(conn, oid, key, default):
        return store.get(key, dict(default))

    def fake_set(conn, oid, key, data):
        store[key] = data

    conn = MagicMock()
    with patch("backend.payroll_planning_settings.ensure_planning_optional_columns"):
        with patch("backend.payroll_planning_settings._get_json_setting", side_effect=fake_get):
            with patch("backend.payroll_planning_settings._set_json_setting", side_effect=fake_set):
                save_planning_maintenance_extras(
                    conn,
                    1,
                    {"scheduling_rules": {"late_grace_minutes": 12}},
                )
                out = get_planning_maintenance_extras(conn, 1)
    assert out["scheduling_rules"]["late_grace_minutes"] == 12


def test_bag_volume_forecast_in_extras():
    from unittest.mock import MagicMock, patch

    from backend.payroll_planning_settings import get_planning_maintenance_extras

    store = {}

    def fake_get(conn, oid, key, default):
        if key == "payroll_bag_volume_forecast_v1":
            return {
                "default_method": "compare",
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
        return store.get(key, dict(default))

    conn = MagicMock()
    with patch("backend.payroll_planning_settings.ensure_planning_optional_columns"):
        with patch("backend.payroll_planning_settings._get_json_setting", side_effect=fake_get):
            out = get_planning_maintenance_extras(conn, 1)
    assert out["bag_volume_forecast"]["default_method"] == "compare"
    assert len(out["bag_volume_forecast"]["role_speed_parameters"]) == 1
