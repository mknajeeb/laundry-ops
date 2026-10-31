"""P0 health endpoints — liveness must not depend on DB or revision stamps."""

from __future__ import annotations

from backend.app import app


def test_health_live_always_200():
    client = app.test_client()
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "alive"


def test_health_includes_liveness_path_pointer():
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.get_json()
    assert body.get("liveness_path") == "/health/live"
    assert "status" in body


def test_health_live_does_not_call_get_db(monkeypatch):
    def _boom():
        raise AssertionError("get_db must not be called from /health/live")

    monkeypatch.setattr("backend.db.get_db", _boom)
    monkeypatch.setattr("backend.app.get_db", _boom, raising=False)
    client = app.test_client()
    assert client.get("/health/live").status_code == 200


def test_health_live_does_not_load_revision_stamps(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("revision stamps must not be loaded from /health/live")

    monkeypatch.setattr("backend.release_revision.load_release_revision_stamps", _boom)
    client = app.test_client()
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "alive"
