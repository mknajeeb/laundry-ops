"""Management Hub read API + mutation gate for wf_ops_maintenance."""

from __future__ import annotations

from flask import Flask, jsonify

from backend.management_today_routes import register_management_today_routes
from backend.management_wf_ops_maintenance import (
    refuse_wf_mutation_if_maintenance,
    wf_ops_maintenance_status,
)
from backend.wf_ops_reset_epoch import invalidate_wf_reset_epoch_cache, set_wf_ops_maintenance


class _MemCursor:
    def __init__(self):
        self.store = {}
        self._last = None

    def execute(self, sql, params=None):
        norm = " ".join(str(sql).split()).lower()
        params = tuple(params or ())
        if "select svalue from system_settings" in norm:
            val = self.store.get((int(params[0]), params[1]))
            self._last = {"svalue": val} if val is not None else None
            return
        if "insert into system_settings" in norm:
            self.store[(int(params[0]), params[1])] = params[2]
            self._last = None
            return
        self._last = None

    def fetchone(self):
        return self._last

    def close(self):
        pass


class _MemConn:
    def __init__(self, cur: _MemCursor):
        self._cur = cur

    def cursor(self, dictionary=True):
        return self._cur

    def close(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


def _patch_settings(monkeypatch):
    monkeypatch.setattr("backend.wf_ops_reset_epoch.table_exists", lambda *_: True)
    monkeypatch.setattr("backend.wf_ops_reset_epoch.table_has_column", lambda *_: True)
    invalidate_wf_reset_epoch_cache()


def _register_app(monkeypatch, cur: _MemCursor):
    _patch_settings(monkeypatch)
    app = Flask(__name__)

    def require_user(cursor):
        return (
            {"id": 1, "roles": ["MANAGER"], "organization_id": 3},
            None,
            None,
        )

    monkeypatch.setattr(
        "backend.management_today_routes.get_db", lambda: _MemConn(cur)
    )
    register_management_today_routes(
        app,
        require_user=require_user,
        user_org_id=lambda me: int(me.get("organization_id") or 3),
        parse_date_value=lambda raw: __import__("datetime").date.fromisoformat(raw),
    )
    return app


def test_wf_ops_maintenance_status_helper_on_off(monkeypatch):
    _patch_settings(monkeypatch)
    cur = _MemCursor()
    assert wf_ops_maintenance_status(cur, 3)["maintenance_on"] is False
    set_wf_ops_maintenance(cur, 3, True)
    body = wf_ops_maintenance_status(cur, 3)
    assert body["maintenance_on"] is True
    assert body["organization_id"] == 3
    assert body["settings_key"] == "wf_ops_maintenance"
    set_wf_ops_maintenance(cur, 3, False)
    assert wf_ops_maintenance_status(cur, 3)["maintenance_on"] is False


def test_refuse_wf_mutation_when_maintenance_on(monkeypatch):
    _patch_settings(monkeypatch)
    cur = _MemCursor()
    assert refuse_wf_mutation_if_maintenance(cur, 3) is None
    set_wf_ops_maintenance(cur, 3, True)
    app = Flask(__name__)
    with app.app_context():
        blocked = refuse_wf_mutation_if_maintenance(cur, 3)
        assert blocked is not None
        resp, code = blocked
        assert code == 503
        assert resp.get_json()["error"] == "wf_ops_maintenance_active"


def test_get_management_wf_ops_maintenance_api(monkeypatch):
    cur = _MemCursor()
    app = _register_app(monkeypatch, cur)
    client = app.test_client()

    r = client.get("/api/management/wf-ops-maintenance")
    assert r.status_code == 200
    assert r.get_json()["maintenance_on"] is False

    set_wf_ops_maintenance(cur, 3, True)
    r2 = client.get("/api/management/wf-ops-maintenance")
    assert r2.status_code == 200
    assert r2.get_json()["maintenance_on"] is True


def test_get_management_wf_ops_maintenance_forbidden(monkeypatch):
    cur = _MemCursor()
    _patch_settings(monkeypatch)
    app = Flask(__name__)

    def require_user(cursor):
        return ({"id": 2, "roles": ["EMPLOYEE"], "organization_id": 3}, None, None)

    monkeypatch.setattr(
        "backend.management_today_routes.get_db", lambda: _MemConn(cur)
    )
    register_management_today_routes(
        app,
        require_user=require_user,
        user_org_id=lambda me: 3,
        parse_date_value=lambda raw: __import__("datetime").date.fromisoformat(raw),
    )
    client = app.test_client()
    r = client.get("/api/management/wf-ops-maintenance")
    assert r.status_code == 403


def test_wf_mutation_route_blocked_when_maintenance_on(monkeypatch):
    cur = _MemCursor()
    app = _register_app(monkeypatch, cur)
    set_wf_ops_maintenance(cur, 3, True)
    client = app.test_client()
    r = client.post(
        "/api/management/rinse-wf/current-workload/BAG1/exclude",
        json={"reason": "test", "reason_code": "OTHER"},
        query_string={"date_et": "2026-09-17"},
    )
    assert r.status_code == 503
    assert r.get_json()["error"] == "wf_ops_maintenance_active"


def test_hd_routes_module_has_no_maintenance_gate():
    """Hang Dry mutations must remain independent of WF ops maintenance."""
    from pathlib import Path

    src = Path("backend/management_rinse_hd_routes.py").read_text()
    assert "refuse_wf_mutation_if_maintenance" not in src
    assert "wf_ops_maintenance" not in src
