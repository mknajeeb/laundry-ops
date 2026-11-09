"""PIN audit names must fit auth_pin_attempts.action, and audit failures stay 401/400."""

import re
from pathlib import Path

from flask import Flask

from backend.attendance_pin_punch import (
    INVALID_PIN_MESSAGE,
    PIN_AUDIT_ACTION_ALIASES,
    PIN_AUDIT_ACTION_MAX,
    PIN_AUDIT_ACTION_REJECTED,
    canonical_pin_audit_action,
    commit_pin_audit,
    record_pin_attempt,
)
from backend.attendance_pin_role_switch import NOT_CLOCKED_IN_MESSAGE
from backend.lost_found_routes import register_lost_found_routes

ROOT = Path(__file__).resolve().parents[2]
PIN_SOURCES = (
    ROOT / "backend" / "attendance_pin_punch.py",
    ROOT / "backend" / "attendance_pin_break.py",
    ROOT / "backend" / "attendance_pin_role_switch.py",
    ROOT / "backend" / "lost_found_routes.py",
    ROOT / "backend" / "maintenance_task_list_pin.py",
    ROOT / "backend" / "employee_pin_hub.py",
)


class _AuditConn:
    def __init__(self, *, insert_error=None, commit_error=None):
        self.inserts = []
        self.commits = 0
        self.rollbacks = 0
        self.insert_error = insert_error
        self.commit_error = commit_error
        self.closed = False

    def cursor(self, dictionary=False):
        return self

    def execute(self, sql, params=None):
        if "INSERT INTO auth_pin_attempts" in str(sql):
            self.inserts.append(params)
            if self.insert_error:
                raise self.insert_error
            return None
        raise AssertionError(sql)

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _collected_actions():
    names = set(PIN_AUDIT_ACTION_ALIASES.values())
    names.update(PIN_AUDIT_ACTION_ALIASES)
    for path in PIN_SOURCES:
        text = path.read_text(encoding="utf-8")
        names.update(re.findall(r'action\s*=\s*"([^"]+)"', text))
        prefixes = re.findall(r'(?:_pin|action_prefix)\(\s*"([^"]+)"', text)
        prefixes += re.findall(r'action_prefix\s*=\s*"([^"]+)"', text)
        for prefix in prefixes:
            for suffix in ("hub_fail", "fail", "not_in"):
                names.add(f"{prefix}_{suffix}")
    return names


def test_every_pin_audit_action_fits_the_column():
    raw_names = _collected_actions()
    assert "lost_found_reconciliation_hub_fail" in raw_names
    assert "pin_role_switch_module_denied_mutate" in raw_names
    stored = {name: canonical_pin_audit_action(name) for name in raw_names}
    assert stored["lost_found_reconciliation_hub_fail"] == "lost_found_recon_hub_fail"
    assert stored["pin_role_switch_module_denied_mutate"] == "pin_role_switch_denied_mutate"
    assert stored["lost_found_reconciliation_not_in"] == "lost_found_reconciliation_not_in"
    assert stored["lost_found_reconciliation_fail"] == "lost_found_reconciliation_fail"
    for name, canon in stored.items():
        assert canon is not None
        assert len(canon) <= PIN_AUDIT_ACTION_MAX, name
        if name not in PIN_AUDIT_ACTION_ALIASES:
            assert len(name) <= PIN_AUDIT_ACTION_MAX, name


def test_overlong_unknown_action_is_still_recorded(caplog, monkeypatch):
    monkeypatch.setattr(
        "backend.attendance_pin_punch.ensure_auth_pin_attempts_table",
        lambda _conn: True,
    )
    conn = _AuditConn()
    caplog.set_level("ERROR")
    ok = record_pin_attempt(
        conn,
        3,
        "127.0.0.1",
        False,
        action="x" * 40,
    )
    assert ok is True
    assert conn.inserts[0][-1] == PIN_AUDIT_ACTION_REJECTED
    assert len(PIN_AUDIT_ACTION_REJECTED) <= PIN_AUDIT_ACTION_MAX
    assert "pin audit action rejected" in caplog.text


def test_audit_insert_failure_does_not_raise(caplog, monkeypatch):
    monkeypatch.setattr(
        "backend.attendance_pin_punch.ensure_auth_pin_attempts_table",
        lambda _conn: True,
    )
    conn = _AuditConn(insert_error=RuntimeError("audit down"))
    caplog.set_level("ERROR")
    ok = record_pin_attempt(conn, 3, "127.0.0.1", False, action="pin_punch_fail")
    assert ok is False
    assert "pin audit insert failed" in caplog.text


def test_audit_commit_failure_does_not_raise(caplog):
    conn = _AuditConn(commit_error=RuntimeError("commit down"))
    caplog.set_level("ERROR")
    assert commit_pin_audit(conn) is False
    assert conn.rollbacks == 1
    assert "pin audit commit failed" in caplog.text


def _reconciliation_client(monkeypatch, conn, *, hub_error=None, matched=None, shift=None):
    calls = {"view": 0}

    def verify(_token):
        if hub_error:
            raise hub_error
        return {"organization_id": 3, "employee_id": 33}

    monkeypatch.setattr("backend.db.get_db", lambda: conn)
    monkeypatch.setattr("backend.attendance_pin_break.payroll_profiles_active", lambda _c: True)
    monkeypatch.setattr(
        "backend.attendance_pin_break.fetch_organization_by_slug",
        lambda _c, _s: {"id": 3},
    )
    monkeypatch.setattr(
        "backend.attendance_pin_break.shared_device_attendance_enabled",
        lambda _c, _o: True,
    )
    monkeypatch.setattr("backend.attendance_pin_break.is_rate_limited", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "backend.attendance_pin_punch.ensure_auth_pin_attempts_table",
        lambda _conn: True,
    )
    monkeypatch.setattr("backend.employee_pin_hub.verify_hub_session_token", verify)
    if matched is not None or shift is not None:
        monkeypatch.setattr(
            "backend.attendance_pin_break._resolve_user_by_hub_token",
            lambda *_a, **_k: matched,
        )
        monkeypatch.setattr(
            "backend.attendance_pin_break._active_shift",
            lambda *_a, **_k: shift,
        )

    def view(*_a, **_k):
        calls["view"] += 1
        return {"items": [{"id": 4}], "ready": True}

    monkeypatch.setattr("backend.lost_found_routes.reconciliation_view", view)
    app = Flask(__name__)
    register_lost_found_routes(
        app,
        require_user=lambda _c: ({"user_id": 15, "roles": ["ADMIN"]}, None, None),
        user_org_id=lambda _m: 3,
        fetch_user_roles=lambda *_a, **_k: ["CLOCK"],
        get_request_ip=lambda: "203.0.113.10",
    )
    return app.test_client(), calls


def _post(client, token="hub-token"):
    return client.post(
        "/api/public/attendance/pin-lost-found/reconciliation",
        json={"organization_slug": "veewash", "hub_token": token},
    )


def test_invalid_hub_token_returns_401_when_audit_insert_and_commit_fail(monkeypatch):
    conn = _AuditConn(
        insert_error=RuntimeError("data too long"),
        commit_error=RuntimeError("commit down"),
    )
    client, calls = _reconciliation_client(
        monkeypatch,
        conn,
        hub_error=ValueError("Invalid session. Enter your PIN again."),
    )
    res = _post(client, "not-a-token")
    body = res.get_json()
    assert res.status_code == 401
    assert body["ok"] is False
    assert body["error"] == INVALID_PIN_MESSAGE
    assert res.content_type.startswith("application/json")
    assert conn.inserts[0][-1] == "lost_found_recon_hub_fail"
    assert len(conn.inserts[0][-1]) <= PIN_AUDIT_ACTION_MAX
    assert calls["view"] == 0
    assert conn.rollbacks == 1


def test_expired_hub_token_returns_401(monkeypatch):
    conn = _AuditConn()
    client, calls = _reconciliation_client(
        monkeypatch,
        conn,
        hub_error=ValueError("Session expired. Enter your PIN again."),
    )
    res = _post(client, "expired-token")
    assert res.status_code == 401
    assert res.get_json()["error"] == INVALID_PIN_MESSAGE
    assert conn.inserts[0][-1] == "lost_found_recon_hub_fail"
    assert conn.inserts[0][3] == 0
    assert calls["view"] == 0


def test_reconciliation_without_active_shift_is_denied(monkeypatch):
    conn = _AuditConn()
    client, calls = _reconciliation_client(
        monkeypatch,
        conn,
        matched={"id": 33, "display_name": "Sarah Kamran", "username": "Sarah_kams"},
        shift=None,
    )
    res = _post(client)
    assert res.status_code == 400
    assert res.get_json()["error"] == NOT_CLOCKED_IN_MESSAGE
    assert conn.inserts[0][-1] == "lost_found_reconciliation_not_in"
    assert conn.inserts[0][2] == 33
    assert calls["view"] == 0


def test_reconciliation_with_active_shift_still_loads(monkeypatch):
    conn = _AuditConn()
    client, calls = _reconciliation_client(
        monkeypatch,
        conn,
        matched={"id": 33, "display_name": "Sarah Kamran", "username": "Sarah_kams"},
        shift={"id": 2234},
    )
    res = _post(client)
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["items"] == [{"id": 4}]
    assert calls["view"] == 1
    assert conn.inserts == []
