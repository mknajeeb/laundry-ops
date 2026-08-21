"""Tests for phone PIN hub feature gating and org pin_menu assignment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.employee_pin_hub import (
    apply_attendance_gates_to_features,
    perform_pin_hub_open,
    resolve_hub_features,
)


def _matched(roles=None, uid=10):
    return {
        "id": uid,
        "first_name": "Alex",
        "display_name": "Alex Tester",
        "_roles": roles or ["FRONT_DESK"],
    }


def test_resolve_hub_features_org_assign_shows_checklist_without_floor_role():
    conn = MagicMock()
    matched = _matched([])  # no FRONT_DESK/OPS
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
        features = resolve_hub_features(
            conn,
            org_id=3,
            matched=matched,
            employee_module_access={
                "clock": True,
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
            },
        )
    assert features["checklist"]["allowed"] is True
    assert features["inventory"]["allowed"] is True
    assert features["switch_role"]["allowed"] is True


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
        features = resolve_hub_features(
            conn,
            org_id=3,
            matched=matched,
            employee_module_access={"clock": True, "switch_role": True, "checklist": True},
        )
    assert features["switch_role"]["allowed"] is False
    assert features["switch_role"]["org_enabled"] is False
    assert features["checklist"]["allowed"] is True
    assert features["inventory"]["allowed"] is False


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
        features = resolve_hub_features(
            conn,
            org_id=3,
            matched=matched,
            employee_module_access={"clock": True, "switch_role": True, "checklist": True},
        )
    assert features["inventory"]["allowed"] is False
    assert features["switch_role"]["allowed"] is True


def test_apply_attendance_gates_keeps_role_visible_when_clocked_out():
    features = {
        "switch_role": {"id": "switch_role", "allowed": True, "label": "Switch Role"},
        "checklist": {"id": "checklist", "allowed": True},
    }
    gated = apply_attendance_gates_to_features(
        features, {"clocked_in": False, "shared_device_enabled": True}
    )
    assert gated["switch_role"]["allowed"] is True
    assert gated["switch_role"]["requires_clock_in"] is True
    assert gated["switch_role"]["blocked_reason"] == "not_clocked_in"
    assert gated["checklist"]["allowed"] is True
    # Original map not mutated
    assert features["switch_role"].get("requires_clock_in") is None


def test_apply_attendance_gates_keeps_switch_role_when_clocked_in():
    features = {"switch_role": {"id": "switch_role", "allowed": True}}
    gated = apply_attendance_gates_to_features(features, {"clocked_in": True})
    assert gated["switch_role"]["allowed"] is True
    assert gated["switch_role"].get("requires_clock_in") is None
    assert gated["take_break"]["allowed"] is True


def test_apply_attendance_gates_hides_take_break_when_permission_off():
    features = {"switch_role": {"id": "switch_role", "allowed": True}}
    gated = apply_attendance_gates_to_features(
        features, {"clocked_in": True, "on_break": False}, allow_take_break=False
    )
    assert gated.get("take_break") is None
    assert gated["switch_role"]["allowed"] is True


def test_apply_attendance_gates_resume_even_when_take_break_denied():
    features = {
        "switch_role": {"id": "switch_role", "allowed": True},
        "revenue_cost": {"id": "revenue_cost", "allowed": True},
    }
    gated = apply_attendance_gates_to_features(
        features,
        {"clocked_in": True, "on_break": True},
        allow_take_break=False,
    )
    assert gated.get("take_break") is None
    assert gated["resume_work"]["allowed"] is True
    assert gated["switch_role"]["blocked_reason"] == "on_break"


def test_apply_attendance_gates_break_mode_hides_working_tiles():
    features = {
        "switch_role": {"id": "switch_role", "allowed": True},
        "revenue_cost": {"id": "revenue_cost", "allowed": True},
        "checklist": {"id": "checklist", "allowed": True},
        "inventory": {"id": "inventory", "allowed": True},
        "team_status": {"id": "team_status", "allowed": True},
    }
    gated = apply_attendance_gates_to_features(
        features, {"clocked_in": True, "on_break": True}
    )
    assert gated["switch_role"]["allowed"] is False
    assert gated["switch_role"]["blocked_reason"] == "on_break"
    assert gated["resume_work"]["allowed"] is True
    assert gated.get("take_break") is None
    for fid in ("revenue_cost", "checklist", "inventory", "team_status"):
        assert gated[fid]["allowed"] is False
        assert gated[fid]["blocked_reason"] == "on_break"


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
        "backend.employee_mobile_pin_access.resolve_employee_mobile_pin_access",
        return_value={
            "clock": True,
            "switch_role": True,
            "take_break": True,
            "checklist": True,
            "inventory": False,
            "revenue_cost": False,
            "team_status": False,
        },
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
        "backend.employee_pin_hub.attendance_snapshot_for_hub",
        return_value={
            "shared_device_enabled": True,
            "clocked_in": True,
            "on_break": False,
        },
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub-token"
    ), patch(
        "backend.employee_pin_hub.issue_pin_session_token", return_value="mtl-token"
    ), patch(
        "backend.maintenance_task_list_module.ensure_maintenance_task_list_tables"
    ), patch(
        "backend.maintenance_task_list_module.employee_assigned_for_date",
        return_value=True,
    ), patch(
        "backend.shift_job_tracking.list_active_selection_tree",
        return_value=[{"id": 1, "code": "RINSE_WF", "roles": []}],
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["token"] == "hub-token"
    assert body["maintenance_token"] == "mtl-token"
    from backend.employee_pin_hub import PIN_HUB_FEATURE_DEFS

    # Clocked-in + not on break injects Take a Break after Role.
    base_order = [d["id"] for d in PIN_HUB_FEATURE_DEFS]
    assert body["feature_order"] == ["switch_role", "take_break"] + [
        x for x in base_order if x not in ("switch_role", "take_break")
    ]
    assert body["features"]["switch_role"]["allowed"] is True
    assert body["features"]["take_break"]["allowed"] is True
    assert body["features"]["checklist"].get("disabled") is not True
    assert body["attendance"]["clocked_in"] is True
    assert body["attendance"]["shared_device_enabled"] is True
    assert body["selection_tree"] == [{"id": 1, "code": "RINSE_WF", "roles": []}]


def test_perform_pin_hub_open_disables_checklist_when_unassigned():
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
        return_value={"enabled": True, "features": {"checklist": True}},
    ), patch(
        "backend.employee_pin_hub.resolve_user_by_attendance_pin", return_value=matched
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ), patch(
        "backend.employee_pin_hub.resolve_hub_features",
        return_value={
            "switch_role": {"id": "switch_role", "allowed": False},
            "checklist": {
                "id": "checklist",
                "allowed": True,
                "path": "/attendance/maintenance",
                "label": "End-of-day checklist",
                "org_enabled": True,
            },
            "inventory": {"id": "inventory", "allowed": False},
        },
    ), patch(
        "backend.employee_pin_hub.attendance_snapshot_for_hub",
        return_value={"shared_device_enabled": True, "clocked_in": True, "on_break": False},
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub-token"
    ), patch(
        "backend.employee_pin_hub.issue_pin_session_token", return_value="mtl-token"
    ), patch(
        "backend.maintenance_task_list_module.ensure_maintenance_task_list_tables"
    ), patch(
        "backend.maintenance_task_list_module.employee_assigned_for_date",
        return_value=False,
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 200
    assert body["maintenance_token"] is None
    assert body["features"]["checklist"]["disabled"] is True
    assert body["features"]["checklist"]["disabled_helper"] == (
        "No maintenance checklist assigned today."
    )


def test_perform_pin_hub_open_clock_only_when_features_gated_off():
    """Hub may open with only Clock when shared-device attendance is on."""
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
        return_value={"enabled": True, "features": {}},
    ), patch(
        "backend.employee_pin_hub.resolve_user_by_attendance_pin", return_value=matched
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ), patch(
        "backend.employee_pin_hub.resolve_hub_features",
        return_value={
            "switch_role": {"id": "switch_role", "allowed": False},
            "checklist": {"id": "checklist", "allowed": False},
            "inventory": {"id": "inventory", "allowed": False},
        },
    ), patch(
        "backend.employee_pin_hub.attendance_snapshot_for_hub",
        return_value={
            "shared_device_enabled": True,
            "allow_clock_from_hub": True,
            "clocked_in": False,
            "on_break": False,
        },
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub-token"
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["attendance"]["shared_device_enabled"] is True


def test_perform_pin_hub_open_when_all_features_off_still_ok():
    """Clock tile is always on the hub, so empty feature lists still open."""
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
        return_value={"enabled": True, "allow_clock_from_hub": False, "features": {}},
    ), patch(
        "backend.employee_pin_hub.resolve_user_by_attendance_pin", return_value=matched
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ), patch(
        "backend.employee_pin_hub.resolve_hub_features",
        return_value={
            "switch_role": {"id": "switch_role", "allowed": False},
            "checklist": {"id": "checklist", "allowed": False},
            "inventory": {"id": "inventory", "allowed": False},
        },
    ), patch(
        "backend.employee_pin_hub.attendance_snapshot_for_hub",
        return_value={
            "shared_device_enabled": False,
            "allow_clock_from_hub": False,
            "clocked_in": False,
            "on_break": False,
        },
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub-token"
    ):
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: ["FRONT_DESK"], "127.0.0.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["attendance"]["allow_clock_from_hub"] is False


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
