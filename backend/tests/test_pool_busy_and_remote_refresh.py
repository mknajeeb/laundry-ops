"""Pool-busy HTTP responses and remote-only targeted refresh. No live MySQL."""

from __future__ import annotations

import os

os.environ["DAILY_OPERATIONAL_RESET_EMBEDDED_SCHEDULER"] = "0"

import logging

import pytest
from mysql.connector import errors as mysql_errors

import backend.db as db
from backend.app import app
from backend.db import DATABASE_BUSY_MESSAGE
from backend.rinse_aca_job_trigger import remote_only_user_message
from backend.rinse_bag_export_runner import export_enabled
from backend.rinse_scheduled_scrape import av_single_pass_enabled

_LEAK_MARKERS = (
    "pool exhausted",
    "mysql",
    "password",
    "mkncentral",
    "traceback",
    "PoolError",
)


class _ExhaustedPool:
    def __init__(self) -> None:
        self.attempts = 0
        self.returned = 0

    def get_connection(self):
        self.attempts += 1
        raise mysql_errors.PoolError("Failed getting connection; pool exhausted")


def _client():
    app.debug = False
    app.testing = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app.test_client()


def _exhaust(monkeypatch) -> _ExhaustedPool:
    pool = _ExhaustedPool()
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "0")
    monkeypatch.setattr(db, "_ensure_pool", lambda: pool)
    return pool


def _assert_busy(resp, pool: _ExhaustedPool) -> None:
    assert resp.status_code == 503
    assert resp.content_type.startswith("application/json")
    body = resp.get_json()
    assert body == {"error": DATABASE_BUSY_MESSAGE}
    raw = resp.get_data(as_text=True).lower()
    for marker in _LEAK_MARKERS:
        assert marker not in raw
    assert pool.returned == 0
    assert pool.attempts >= 1


def test_login_pool_busy_is_safe_503(monkeypatch, caplog):
    pool = _exhaust(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="backend.db"):
        resp = _client().post(
            "/auth/login",
            json={"username": "employee", "password": "secret"},
        )
    _assert_busy(resp, pool)
    assert "mysql_pool_exhausted" in caplog.text
    assert "password" not in caplog.text.lower()


def test_pin_unlock_pool_busy_is_safe_503(monkeypatch):
    pool = _exhaust(monkeypatch)
    resp = _client().post(
        "/auth/attendance-pin-unlock",
        json={"organization_slug": "veewash", "pin": "1234"},
    )
    _assert_busy(resp, pool)


def test_pin_punch_pool_busy_is_safe_503(monkeypatch):
    pool = _exhaust(monkeypatch)
    resp = _client().post(
        "/api/public/attendance/pin-punch",
        json={"organization_slug": "veewash", "pin": "1234"},
    )
    _assert_busy(resp, pool)


def test_health_db_pool_busy_is_safe_503(monkeypatch):
    pool = _exhaust(monkeypatch)
    resp = _client().get("/health/db")
    _assert_busy(resp, pool)


def test_health_live_ignores_exhausted_pool(monkeypatch):
    pool = _exhaust(monkeypatch)
    resp = _client().get("/health/live")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "alive"
    assert pool.attempts == 0


def test_login_unrelated_error_is_not_rewritten(monkeypatch):
    def _boom():
        raise RuntimeError("unique-login-detail")

    monkeypatch.setattr("backend.app.get_db", _boom)
    resp = _client().post(
        "/auth/login",
        json={"username": "employee", "password": "secret"},
    )
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "unique-login-detail"


def test_health_db_unrelated_error_is_not_rewritten(monkeypatch):
    def _boom():
        raise RuntimeError("unique-health-detail")

    monkeypatch.setattr("backend.app.get_db", _boom)
    resp = _client().get("/health/db")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "unique-health-detail"


def test_targeted_refresh_remote_only_does_not_run_playwright(monkeypatch):
    monkeypatch.setenv("RINSE_SCRAPE_REMOTE_ONLY", "1")
    calls = {"n": 0}

    def _playwright(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("local playwright must not run")

    monkeypatch.setattr(
        "backend.rinse_off_portal_scan_refresh.refresh_pending_workload_scans_via_direct_lookup",
        _playwright,
    )
    monkeypatch.setattr(
        "backend.rinse_shift_analysis_routes.get_db",
        lambda: (_ for _ in ()).throw(AssertionError("db must not be opened")),
    )
    resp = _client().post("/api/rinse/sync/targeted-pending-refresh", json={})
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["dispatch_mode"] == "remote_only_blocked"
    assert body["error"] == remote_only_user_message()
    assert calls["n"] == 0


def test_targeted_refresh_without_remote_only_reaches_database(monkeypatch):
    monkeypatch.delenv("RINSE_SCRAPE_REMOTE_ONLY", raising=False)

    def _boom():
        raise RuntimeError("reached-db")

    monkeypatch.setattr("backend.rinse_shift_analysis_routes.get_db", _boom)
    app.config["PROPAGATE_EXCEPTIONS"] = True
    try:
        with pytest.raises(RuntimeError, match="reached-db"):
            app.test_client().post("/api/rinse/sync/targeted-pending-refresh", json={})
    finally:
        app.config["PROPAGATE_EXCEPTIONS"] = False


@pytest.mark.parametrize(
    "path",
    [
        "/admin/rinse/bag-export",
        "/admin/rinse/import-upload-batch",
        "/admin/rinse/import-upload-batch/jobs",
    ],
)
def test_export_flag_off_disables_api_routes_before_playwright(monkeypatch, path):
    monkeypatch.setenv("RINSE_BAG_EXPORT_ENABLED", "0")
    monkeypatch.delenv("APPSETTING_RINSE_BAG_EXPORT_ENABLED", raising=False)
    calls = {"n": 0}

    def _playwright(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("playwright")

    monkeypatch.setattr("backend.rinse_export_routes.run_bag_export_csv", _playwright)
    resp = _client().post(path, json={})
    assert resp.status_code == 503
    assert "disabled" in resp.get_json()["error"].lower()
    assert calls["n"] == 0
    assert export_enabled() is False


def test_export_flag_off_does_not_disable_aca_single_pass(monkeypatch):
    monkeypatch.setenv("RINSE_BAG_EXPORT_ENABLED", "0")
    monkeypatch.delenv("RINSE_AV_SINGLE_PASS", raising=False)
    assert export_enabled() is False
    assert av_single_pass_enabled() is True
