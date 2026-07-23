"""Tests for public PIN role-switch (mobile shortcut)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.attendance_pin_role_switch import (
    FEATURE_DISABLED_MESSAGE,
    NOT_CLOCKED_IN_MESSAGE,
    perform_pin_role_switch,
)
from backend.shift_job_tracking import IdempotencyConflictError


def _mock_roles(_conn, _uid):
    return []


def test_pin_role_switch_requires_clocked_in():
    conn = MagicMock()
    matched = {"id": 23, "first_name": "Vee"}
    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value=matched,
    ), patch(
        "backend.attendance_pin_role_switch._active_shift", return_value=None
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ):
        body, status = perform_pin_role_switch(
            conn, "veewash", "1234", _mock_roles, "127.0.0.1"
        )
    assert status == 400
    assert body["error"] == NOT_CLOCKED_IN_MESSAGE


def test_pin_role_switch_requires_feature_enabled():
    conn = MagicMock()
    matched = {"id": 23, "first_name": "Vee"}
    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value=matched,
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=False,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ):
        body, status = perform_pin_role_switch(
            conn, "veewash", "1234", _mock_roles, "127.0.0.1"
        )
    assert status == 403
    assert body["error"] == FEATURE_DISABLED_MESSAGE


def test_pin_role_switch_opens_selection_tree():
    conn = MagicMock()
    matched = {"id": 23, "first_name": "Vee"}
    tree = [{"id": 1, "name": "DHS", "roles": [{"role_id": 2, "role_name": "Operator"}]}]
    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value=matched,
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.get_open_job_segment",
        return_value={
            "id": 7,
            "category_id": 1,
            "role_id": 2,
            "category_name_snapshot": "DHS",
            "role_name_snapshot": "Operator",
            "started_at": datetime(2026, 7, 22, 10, 0),
        },
    ), patch(
        "backend.attendance_pin_role_switch.seed_default_categories_and_roles"
    ), patch(
        "backend.attendance_pin_role_switch.list_active_selection_tree",
        return_value=tree,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ):
        body, status = perform_pin_role_switch(
            conn, "veewash", "1234", _mock_roles, "127.0.0.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["needs_selection"] is True
    assert body["selection_tree"] == tree
    assert body["current_display_label"] == "DHS — Operator"
    assert body["employee_first_name"] == "Vee"


def test_pin_role_switch_performs_switch():
    conn = MagicMock()
    matched = {"id": 23, "first_name": "Vee"}
    seg = {
        "id": 8,
        "display_label": "Rinse WF — Folder",
        "replayed": False,
        "noop": False,
        "unchanged": False,
    }
    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value=matched,
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.get_open_job_segment",
        return_value={"id": 7, "category_id": 1, "role_id": 2},
    ), patch(
        "backend.attendance_pin_role_switch.start_category_role_segment",
        return_value=seg,
    ) as start, patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ):
        body, status = perform_pin_role_switch(
            conn,
            "veewash",
            "1234",
            _mock_roles,
            "127.0.0.1",
            category_id=1,
            role_id=3,
            idempotency_key="abc",
        )
    assert status == 200
    assert body["action"] == "ROLE_SWITCHED"
    assert body["display_label"] == "Rinse WF — Folder"
    assert start.call_args.kwargs["idempotency_key"] == "abc"
    conn.commit.assert_called()


def test_pin_role_switch_conflict_returns_409():
    conn = MagicMock()
    matched = {"id": 23, "first_name": "Vee"}
    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value=matched,
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.get_open_job_segment",
        return_value={"id": 7},
    ), patch(
        "backend.attendance_pin_role_switch.start_category_role_segment",
        side_effect=IdempotencyConflictError("already used"),
    ):
        body, status = perform_pin_role_switch(
            conn,
            "veewash",
            "1234",
            _mock_roles,
            "127.0.0.1",
            category_id=1,
            role_id=2,
            idempotency_key="k1",
        )
    assert status == 409
    assert body["code"] == "idempotency_conflict"
