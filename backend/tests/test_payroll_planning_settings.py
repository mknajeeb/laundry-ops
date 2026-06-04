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
