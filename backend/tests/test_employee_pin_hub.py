"""Tests for phone PIN hub feature gating and org pin_menu assignment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.employee_pin_hub import perform_pin_hub_open, resolve_hub_features


def _matched(roles=None, uid=10):
    return {
        "id": uid,
        "first_name": "Alex",
        "display_name": "Alex Tester",
        "_roles": roles or ["FRONT_DESK"],
    }


def test_resolve_hub_features_respects_org_pin_menu_off():
    conn = MagicMock()
    matched = _matched(["FRONT_DESK"])
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "features": {"switch_role": False, "checklist": True, "inventory": False},
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        features = resolve_hub_features(conn, org_id=3, matched=matched)
    assert features["switch_role"]["allowed"] is False
    assert features["switch_role"]["org_enabled"] is False
    assert features["checklist"]["allowed"] is True
    assert features["inventory"]["allowed"] is False


def test_resolve_hub_features_floor_role_when_org_enables_all():
    conn = MagicMock()
    matched = _matched(["FRONT_DESK"])
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "features": {"switch_role": True, "checklist": True, "inventory": True},
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        features = resolve_hub_features(conn, org_id=3, matched=matched)
    assert features["switch_role"]["allowed"] is True
    assert features["checklist"]["allowed"] is True
    assert features["inventory"]["allowed"] is True


def test_resolve_hub_features_inventory_module_off():
    conn = MagicMock()
    matched = _matched(["OPS"])
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "features": {"switch_role": True, "checklist": True, "inventory": True},
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=False
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        features = resolve_hub_features(conn, org_id=3, matched=matched)
    assert features["inventory"]["allowed"] is False
    assert features["switch_role"]["allowed"] is True


def test_perform_pin_hub_open_success_returns_menu():
    conn = MagicMock()
    matched = _matched(["FRONT_DESK"])
    with patch(
        "backend.employee_pin_hub.payroll_profiles_active", return_value=True
    ), patch(
        "backend.employee_pin_hub.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.employee_pin_hub.is_rate_limited", return_value=False
    ), patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={"enabled": True, "features": {"switch_role": True, "checklist": True}},
    ), patch(
        "backend.employee_pin_hub.resolve_user_by_attendance_pin", return_value=matched
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ), patch(
        "backend.employee_pin_hub.resolve_hub_features",
        return_value={
            "switch_role": {
                "id": "switch_role",
                "allowed": True,
                "path": "/attendance/role",
                "label": "Switch Role",
                "org_enabled": True,
            },
            "checklist": {
                "id": "checklist",
                "allowed": True,
                "path": "/attendance/maintenance",
                "label": "End-of-day checklist",
                "org_enabled": True,
            },
            "inventory": {
                "id": "inventory",
                "allowed": False,
                "path": "/inventory",
                "label": "Inventory",
                "org_enabled": True,
            },
        },
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub-token"
    ), patch(
        "backend.employee_pin_hub.issue_pin_session_token", return_value="mtl-token"
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["token"] == "hub-token"
    assert body["maintenance_token"] == "mtl-token"
    assert body["feature_order"] == ["switch_role", "checklist", "inventory"]
    assert body["features"]["switch_role"]["allowed"] is True


def test_perform_pin_hub_open_menu_disabled():
    conn = MagicMock()
    with patch(
        "backend.employee_pin_hub.payroll_profiles_active", return_value=True
    ), patch(
        "backend.employee_pin_hub.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.employee_pin_hub.is_rate_limited", return_value=False
    ), patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={"enabled": False, "features": {}},
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 403
    assert body["ok"] is False
