"""Phase 5B.1 Step 3 — End-of-Day Checklist employee Mobile PIN Access."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from backend.employee_mobile_pin_access import DENIED_MODULE_MESSAGE
from backend.tests.test_employee_mobile_pin_access import FakeCursor


def _access_row(*, checklist: bool, revenue_cost: bool = True, switch_role: bool = True):
    return {
        "clock": True,
        "switch_role": switch_role,
        "checklist": checklist,
        "inventory": True,
        "revenue_cost": revenue_cost,
        "team_status": False,
    }


def _open_patches(access_cur, *, assigned=True, matched_id=42):
    conn = MagicMock()
    conn.cursor.return_value = access_cur
    return conn, [
        patch(
            "backend.maintenance_task_list_pin.payroll_profiles_active", return_value=True
        ),
        patch(
            "backend.maintenance_task_list_pin.fetch_organization_by_slug",
            return_value={"id": 3, "slug": "veewash"},
        ),
        patch("backend.maintenance_task_list_pin.is_rate_limited", return_value=False),
        patch(
            "backend.maintenance_task_list_pin.shared_device_attendance_enabled",
            return_value=True,
        ),
        patch(
            "backend.maintenance_task_list_pin.resolve_user_by_attendance_pin",
            return_value={"id": matched_id, "display_name": "Pat", "first_name": "Pat"},
        ),
        patch("backend.maintenance_task_list_pin.record_pin_attempt"),
        patch(
            "backend.maintenance_task_list_module.ensure_maintenance_task_list_tables"
        ),
        patch(
            "backend.maintenance_task_list_module.employee_assigned_for_date",
            return_value=assigned,
        ),
    ]


def test_direct_pin_open_allowed_assigned_issues_token():
    from contextlib import ExitStack

    from backend.maintenance_task_list_pin import perform_pin_maintenance_open

    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=True)
    conn, patches = _open_patches(cur, assigned=True)
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        issue = stack.enter_context(
            patch(
                "backend.maintenance_task_list_pin.issue_pin_session_token",
                return_value="mtl-ok",
            )
        )
        body, status = perform_pin_maintenance_open(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 200
    assert body["ok"] is True
    assert body["token"] == "mtl-ok"
    issue.assert_called_once()


def test_direct_pin_open_denied_assigned_no_token():
    from backend.maintenance_task_list_pin import perform_pin_maintenance_open

    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=False)
    conn, patches = _open_patches(cur, assigned=True)
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        issue = stack.enter_context(
            patch("backend.maintenance_task_list_pin.issue_pin_session_token")
        )
        body, status = perform_pin_maintenance_open(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 403
    assert DENIED_MODULE_MESSAGE in body["error"]
    issue.assert_not_called()


def test_direct_pin_open_allowed_unassigned_keeps_assignment_denial():
    from backend.maintenance_task_list_pin import perform_pin_maintenance_open

    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=True)
    conn, patches = _open_patches(cur, assigned=False)
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        issue = stack.enter_context(
            patch("backend.maintenance_task_list_pin.issue_pin_session_token")
        )
        body, status = perform_pin_maintenance_open(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 403
    assert "not assigned" in body["error"].lower()
    issue.assert_not_called()


def _build_public_client(access_cur: FakeCursor):
    from backend.maintenance_task_list_routes import register_maintenance_task_list_routes

    app = Flask(__name__)
    me = {"user_id": 1, "id": 1, "roles": ["ADMIN"]}

    register_maintenance_task_list_routes(
        app,
        require_user=lambda c: (me, None, None),
        require_admin=lambda c: (me, None, None),
        require_admin_or_ops=lambda c: (me, None, None),
        user_org_id=lambda _me: 3,
        parse_date_value=lambda raw: raw,
        fetch_user_roles=lambda *_: ["EMPLOYEE"],
        get_request_ip=lambda: "1.1.1.1",
        effective_washpro_permission_keys=lambda *_: {
            "maintenance.tasks.reports",
            "maintenance.tasks.manage",
        },
    )
    conn = MagicMock()
    conn.cursor.return_value = access_cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()
    return app.test_client(), conn


def test_session_revocation_blocks_today_item_save_submit():
    """Unexpired maintenance token rejected after checklist=false; no mutations."""
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=True)
    client, conn = _build_public_client(cur)
    session = {"organization_id": 3, "employee_id": 42}
    headers = {"Authorization": "Bearer mtl-token", "X-Maintenance-Session": "mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value=session,
    ), patch(
        "backend.maintenance_task_list_routes.ensure_maintenance_task_list_tables"
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list",
        return_value={
            "id": 9,
            "task_date": "2026-07-17",
            "employee_id": 42,
            "status": "in_progress",
            "items": [],
        },
    ) as create_list:
        ok = client.get("/api/public/maintenance-task-list/today", headers=headers)
    assert ok.status_code == 200
    create_list.assert_called_once()

    cur.access[(3, 42)]["checklist"] = False

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value=session,
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list"
    ) as create2, patch(
        "backend.maintenance_task_list_routes.get_task_list"
    ) as get_list, patch(
        "backend.maintenance_task_list_routes.save_task_item"
    ) as save_item, patch(
        "backend.maintenance_task_list_routes.save_progress"
    ) as save_prog, patch(
        "backend.maintenance_task_list_routes.submit_task_list"
    ) as submit:
        today = client.get("/api/public/maintenance-task-list/today", headers=headers)
        item = client.patch(
            "/api/public/maintenance-task-list/9/items/1",
            headers=headers,
            json={"completed": True},
        )
        save = client.post(
            "/api/public/maintenance-task-list/9/save",
            headers=headers,
            json={"items": []},
        )
        sub = client.post(
            "/api/public/maintenance-task-list/9/submit",
            headers=headers,
            json={},
        )
    assert today.status_code == 403
    assert item.status_code == 403
    assert save.status_code == 403
    assert sub.status_code == 403
    assert DENIED_MODULE_MESSAGE in today.get_json()["error"]
    create2.assert_not_called()
    get_list.assert_not_called()
    save_item.assert_not_called()
    save_prog.assert_not_called()
    submit.assert_not_called()


def test_denied_token_cannot_use_list_id_directly():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=False)
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.maintenance_task_list_routes.save_progress"
    ) as save_prog:
        res = client.post(
            "/api/public/maintenance-task-list/99/save",
            headers=headers,
            json={"items": []},
        )
    assert res.status_code == 403
    save_prog.assert_not_called()


def test_cross_employee_list_ownership_still_enforced_when_allowed():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=True)
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.maintenance_task_list_routes.get_task_list",
        return_value={"id": 9, "employee_id": 99, "organization_id": 3},
    ), patch(
        "backend.maintenance_task_list_routes.save_task_item"
    ) as save_item:
        res = client.patch(
            "/api/public/maintenance-task-list/9/items/1",
            headers=headers,
            json={"completed": True},
        )
    assert res.status_code == 403
    assert res.get_json()["error"] == "Forbidden"
    save_item.assert_not_called()


def test_cross_org_access_row_does_not_authorize():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.backfill_orgs[99] = 1
    cur.access[(99, 42)] = _access_row(checklist=True)
    # No (3, 42) row after marker → deny
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list"
    ) as create:
        res = client.get("/api/public/maintenance-task-list/today", headers=headers)
    assert res.status_code == 403
    create.assert_not_called()


def test_missing_row_after_backfill_denies_session():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list"
    ) as create:
        res = client.get("/api/public/maintenance-task-list/today", headers=headers)
    assert res.status_code == 403
    create.assert_not_called()


def test_pre_marker_missing_row_allows_session():
    cur = FakeCursor()
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.employee_mobile_pin_access.ensure_org_mobile_pin_access_backfill",
        side_effect=lambda cursor, oid: None,
    ), patch(
        "backend.employee_mobile_pin_access._org_is_backfilled", return_value=False
    ), patch(
        "backend.employee_mobile_pin_access.get_access_row", return_value=None
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ), patch(
        "backend.maintenance_task_list_routes.ensure_maintenance_task_list_tables"
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list",
        return_value={"id": 1, "task_date": "2026-07-17", "employee_id": 42, "items": []},
    ) as create:
        res = client.get("/api/public/maintenance-task-list/today", headers=headers)
    assert res.status_code == 200
    create.assert_called_once()


def test_inactive_employee_session_rejected():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(checklist=True)
    cur.inactive_users.add((3, 42))
    client, conn = _build_public_client(cur)
    headers = {"Authorization": "Bearer mtl-token"}

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.verify_pin_session_token",
        return_value={"organization_id": 3, "employee_id": 42},
    ), patch(
        "backend.maintenance_task_list_routes.get_or_create_task_list"
    ) as create:
        res = client.get("/api/public/maintenance-task-list/today", headers=headers)
    assert res.status_code == 401
    create.assert_not_called()


def test_manager_reports_unaffected_when_employee_checklist_false():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 1)] = _access_row(checklist=False)
    cur.users.add((3, 1))
    client, conn = _build_public_client(cur)

    with patch(
        "backend.maintenance_task_list_routes.get_db", return_value=conn
    ), patch(
        "backend.maintenance_task_list_routes.list_submission_summaries",
        return_value=[],
    ) as reports, patch(
        "backend.employee_mobile_pin_access.assert_employee_allows_module"
    ) as assert_mod:
        res = client.get("/api/maintenance-task-list/reports")
    assert res.status_code == 200
    reports.assert_called_once()
    assert_mod.assert_not_called()


def test_hub_employee_denied_hides_checklist_and_no_maintenance_token():
    from backend.employee_pin_hub import perform_pin_hub_open, resolve_hub_features

    matched = {"id": 10, "_roles": []}
    emp = _access_row(checklist=False)
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
            },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(), org_id=3, matched=matched, employee_module_access=emp
        )
    assert feats["checklist"]["allowed"] is False

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
        return_value={"enabled": True, "features": {"checklist": True}},
    ), patch(
        "backend.employee_pin_hub.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Pat", "first_name": "Pat"},
    ), patch(
        "backend.employee_pin_hub.record_pin_attempt"
    ), patch(
        "backend.employee_mobile_pin_access.resolve_employee_mobile_pin_access",
        return_value=emp,
    ), patch(
        "backend.employee_pin_hub.resolve_hub_features",
        return_value={
            "checklist": {
                "id": "checklist",
                "allowed": False,
                "employee_allowed": False,
                "label": "End-of-Day Checklist",
            },
            "switch_role": {"id": "switch_role", "allowed": False},
            "inventory": {"id": "inventory", "allowed": False},
            "revenue_cost": {"id": "revenue_cost", "allowed": False},
        },
    ), patch(
        "backend.employee_pin_hub.attendance_snapshot_for_hub",
        return_value={"shared_device_enabled": True, "clocked_in": True, "on_break": False},
    ), patch(
        "backend.employee_pin_hub.issue_hub_session_token", return_value="hub"
    ), patch(
        "backend.employee_pin_hub.issue_pin_session_token", return_value="mtl"
    ) as issue_mtl:
        body, status = perform_pin_hub_open(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 200
    assert body["maintenance_token"] is None
    issue_mtl.assert_not_called()


def test_checklist_permission_is_independent_of_inventory_grant():
    from backend.employee_mobile_pin_access import (
        MobilePinAccessDeniedError,
        assert_employee_allows_module,
        employee_module_enforced,
    )

    assert employee_module_enforced("checklist")
    assert employee_module_enforced("inventory")
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 10)] = _access_row(checklist=True)
    cur.access[(3, 10)]["inventory"] = False
    assert_employee_allows_module(cur, 3, 10, "checklist")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "inventory")
