"""Phase 5B.1 Step 2 — Revenue & Cost employee Mobile PIN Access on /mobile/* routes."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from backend.employee_mobile_pin_access import DENIED_MODULE_MESSAGE
from backend.tests.test_employee_mobile_pin_access import FakeCursor


TODAY = date(2026, 7, 17)  # Friday


def _access_row(*, revenue_cost: bool, switch_role: bool = True):
    return {
        "clock": True,
        "switch_role": switch_role,
        "take_break": True,
        "checklist": True,
        "inventory": True,
        "revenue_cost": revenue_cost,
        "team_status": False,
    }


def _build_client(access_cur: FakeCursor, *, user_id=42, org_id=3, roles=None):
    """Minimal Flask app with employee /mobile/* routes and mocked auth + DB."""
    from backend.drc_mobile_entry_routes import register_drc_mobile_entry_routes

    app = Flask(__name__)
    me = {
        "user_id": user_id,
        "id": user_id,
        "roles": roles if roles is not None else ["EMPLOYEE"],
    }

    def require_user(_cursor):
        return me, None, None

    def user_org_id(_me):
        return org_id

    def parse_date_value(raw):
        return date.fromisoformat(str(raw)[:10])

    register_drc_mobile_entry_routes(
        app,
        require_user=require_user,
        require_admin=lambda c: (me, None, None),
        user_org_id=user_org_id,
        parse_date_value=parse_date_value,
        effective_washpro_permission_keys=lambda *_: set(),
    )

    conn = MagicMock()
    conn.cursor.return_value = access_cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    return app.test_client(), conn


def test_mobile_today_denied_when_revenue_cost_false():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee"
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 403
    assert DENIED_MODULE_MESSAGE in res.get_json()["error"]
    list_today.assert_not_called()


def test_mobile_draft_denied_when_revenue_cost_false_no_mutation():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.save_section_draft"
    ) as save_draft:
        res = client.put(
            "/finance/daily-revenue-cost/mobile/sections/self_service/draft",
            json={"values": {"cash": 1}, "entry_date": TODAY.isoformat()},
        )
    assert res.status_code == 403
    save_draft.assert_not_called()


def test_mobile_section_submit_denied_when_revenue_cost_false_no_mutation():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.submit_section"
    ) as submit:
        res = client.post(
            "/finance/daily-revenue-cost/mobile/sections/self_service/submit",
            json={"entry_date": TODAY.isoformat()},
        )
    assert res.status_code == 403
    submit.assert_not_called()


def test_mobile_submit_all_denied_when_revenue_cost_false_no_mutation():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.submit_all_assigned"
    ) as submit_all:
        res = client.post(
            "/finance/daily-revenue-cost/mobile/submit",
            json={"entry_date": TODAY.isoformat()},
        )
    assert res.status_code == 403
    submit_all.assert_not_called()


def test_assignment_alone_does_not_grant_when_revenue_cost_denied():
    """Phase 5E assignee with revenue_cost=false still gets 403 before list_today."""
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee",
        return_value={"assigned_sections": [{"section_key": "self_service"}]},
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 403
    list_today.assert_not_called()


def test_revocation_mid_session_blocks_read_and_write():
    """Same bearer identity: allowed → load ok; revoke → next read/write 403, no mutate."""
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=True)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee",
        return_value={"business_date": TODAY.isoformat(), "assigned_sections": []},
    ) as list_today:
        ok = client.get("/finance/daily-revenue-cost/mobile/today")
    assert ok.status_code == 200
    list_today.assert_called_once()

    # Manager revokes while employee still holds the 12h Washpro token.
    cur.access[(3, 42)]["revenue_cost"] = False

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee"
    ) as list_today2, patch(
        "backend.drc_mobile_entry.save_section_draft"
    ) as save_draft:
        read_res = client.get("/finance/daily-revenue-cost/mobile/today")
        write_res = client.put(
            "/finance/daily-revenue-cost/mobile/sections/self_service/draft",
            json={"values": {"cash": 9}, "entry_date": TODAY.isoformat()},
        )
    assert read_res.status_code == 403
    assert write_res.status_code == 403
    list_today2.assert_not_called()
    save_draft.assert_not_called()


def test_allowed_employee_reaches_list_today():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 42)] = _access_row(revenue_cost=True)
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee",
        return_value={"business_date": TODAY.isoformat(), "assigned_sections": []},
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 200
    list_today.assert_called_once()
    assert list_today.call_args.args[1] == 3
    assert list_today.call_args.args[2] == 42


def test_manager_weekday_assignments_skip_employee_revenue_cost_gate():
    """Manager routes use _manager — employee Mobile PIN Access must not apply."""
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    # Even with revenue_cost false, manager path must not 403 for that reason.
    cur.access[(3, 1)] = _access_row(revenue_cost=False)
    client, conn = _build_client(cur, user_id=1, roles=["ADMIN"])

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_weekday_section_assignments",
        return_value=[],
    ) as list_asg, patch(
        "backend.employee_mobile_pin_access.assert_employee_allows_module"
    ) as assert_mod:
        res = client.get("/finance/daily-revenue-cost/mobile/weekday-assignments")
    assert res.status_code == 200
    list_asg.assert_called_once()
    assert_mod.assert_not_called()


def test_missing_row_after_backfill_denies_revenue_cost_on_mobile():
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    # No access row → post-marker deny-by-default.
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee"
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 403
    list_today.assert_not_called()


def test_pre_marker_missing_row_denies_revenue_cost_on_mobile():
    cur = FakeCursor()
    # Unmarked org + missing row → Role + Take a Break only (not all apps).
    client, conn = _build_client(cur)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.employee_mobile_pin_access.ensure_org_mobile_pin_access_backfill",
        side_effect=lambda cursor, oid: None,
    ), patch(
        "backend.employee_mobile_pin_access._org_is_backfilled", return_value=False
    ), patch(
        "backend.employee_mobile_pin_access.get_access_row", return_value=None
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ), patch(
        "backend.drc_mobile_entry.list_today_for_employee",
        return_value={"assigned_sections": []},
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 403
    list_today.assert_not_called()


def test_cross_org_access_row_does_not_grant_request_org():
    """Access granted in org 99 must not authorize org 3 mobile calls."""
    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.backfill_orgs[99] = 1
    cur.access[(99, 42)] = _access_row(revenue_cost=True)
    # No row for (3, 42) after marker → deny.
    client, conn = _build_client(cur, org_id=3)

    with patch("backend.drc_mobile_entry_routes.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.list_today_for_employee"
    ) as list_today:
        res = client.get("/finance/daily-revenue-cost/mobile/today")
    assert res.status_code == 403
    list_today.assert_not_called()


def test_revenue_cost_permission_does_not_grant_switch_role():
    from backend.employee_mobile_pin_access import assert_employee_allows_module
    from backend.employee_mobile_pin_access import MobilePinAccessDeniedError

    cur = FakeCursor()
    cur.backfill_orgs[3] = 1
    cur.access[(3, 10)] = _access_row(revenue_cost=True, switch_role=False)
    assert_employee_allows_module(cur, 3, 10, "revenue_cost")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "switch_role")
