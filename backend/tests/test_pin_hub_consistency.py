"""PIN Hub consistency: Role visibility, current role, Inventory + R&C + Hang Dry gates."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.employee_pin_hub import (
    PIN_HUB_FEATURE_DEFS,
    apply_attendance_gates_to_features,
    resolve_hub_features,
)


def _pin_menu(**feats):
    base = {
        "switch_role": True,
        "revenue_cost": True,
        "hang_dry": True,
        "checklist": True,
        "inventory": True,
    }
    base.update(feats)
    return {"enabled": True, "allow_clock_from_hub": True, "features": base}


def test_feature_defs_include_revenue_hang_dry_and_inventory_labels():
    ids = [d["id"] for d in PIN_HUB_FEATURE_DEFS]
    assert ids == [
        "switch_role",
        "revenue_cost",
        "hang_dry",
        "checklist",
        "inventory",
    ]
    by_id = {d["id"]: d for d in PIN_HUB_FEATURE_DEFS}
    assert by_id["revenue_cost"]["label"] == "Revenue & Cash"
    assert by_id["revenue_cost"]["path"] == "/revenue-cost/floor"
    assert by_id["hang_dry"]["label"] == "Hang Dry"
    assert by_id["hang_dry"]["path"] == "/hang-dry/floor"
    assert by_id["inventory"]["label"] == "Inventory"


def test_role_stays_allowed_when_clocked_out():
    feats = {"switch_role": {"id": "switch_role", "allowed": True}}
    gated = apply_attendance_gates_to_features(feats, {"clocked_in": False})
    assert gated["switch_role"]["allowed"] is True
    assert gated["switch_role"]["requires_clock_in"] is True


def test_hub_hides_inventory_revenue_and_hang_dry_when_employee_off():
    emp = {
        "clock": False,
        "switch_role": True,
        "checklist": True,
        "inventory": False,
        "revenue_cost": False,
        "hang_dry": False,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings", return_value=_pin_menu()
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched={"id": 23, "_roles": []},
            employee_module_access=emp,
        )
    assert feats["switch_role"]["allowed"] is True
    assert feats["inventory"]["allowed"] is False
    assert feats["revenue_cost"]["allowed"] is False
    assert feats["hang_dry"]["allowed"] is False


def test_hub_shows_inventory_revenue_and_hang_dry_when_employee_on():
    emp = {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": True,
        "revenue_cost": True,
        "hang_dry": True,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings", return_value=_pin_menu()
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched={"id": 23, "_roles": []},
            employee_module_access=emp,
        )
    assert feats["inventory"]["allowed"] is True
    assert feats["inventory"]["label"] == "Inventory"
    assert feats["revenue_cost"]["allowed"] is True
    assert feats["revenue_cost"]["label"] == "Revenue & Cash"
    assert feats["hang_dry"]["allowed"] is True
    assert feats["hang_dry"]["label"] == "Hang Dry"
