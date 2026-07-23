"""Route-level coverage for switch-task hang-fix / idempotency."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.shift_job_tracking import IdempotencyConflictError


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@contextmanager
def _patched_route_globals(*, request_json=None, headers=None, g_user_id=23):
    """Avoid patch()-ing Flask LocalProxies (raises outside request context)."""
    import backend.shift_job_tracking_routes as routes

    req = SimpleNamespace(
        json=request_json if request_json is not None else {},
        headers=headers or {},
    )
    g_ns = SimpleNamespace(ta_user={"id": g_user_id})
    old_req, old_g, old_jsonify = routes.request, routes.g, routes.jsonify
    routes.request = req
    routes.g = g_ns
    routes.jsonify = lambda body, **k: body
    try:
        yield routes
    finally:
        routes.request = old_req
        routes.g = old_g
        routes.jsonify = old_jsonify


def test_switch_task_requires_idempotency_key():
    import backend.shift_job_tracking_routes as routes

    view = _unwrap(routes.job_tracking_switch_job)
    with _patched_route_globals(request_json={"category_id": 1, "role_id": 2}):
        body, code = view()
    assert code == 400
    assert "idempotency_key" in body["error"]


def test_switch_task_rejects_when_feature_disabled():
    import backend.shift_job_tracking_routes as routes

    view = _unwrap(routes.job_tracking_switch_job)
    conn = MagicMock()
    with _patched_route_globals(
        request_json={"category_id": 1, "role_id": 2, "idempotency_key": "k1"}
    ), patch(
        "backend.shift_job_tracking_routes.get_db", return_value=conn
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=False,
    ), patch(
        "backend.shift_job_tracking_routes._tenant_id", return_value=3
    ):
        body, code = view()
    assert code == 403
    assert "disabled" in body["error"].lower()


def test_switch_task_conflict_returns_409():
    import backend.shift_job_tracking_routes as routes

    view = _unwrap(routes.job_tracking_switch_job)
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 99, "status": "active"}
    conn.cursor.return_value = cur
    with _patched_route_globals(
        request_json={"category_id": 1, "role_id": 2, "idempotency_key": "k1"}
    ), patch(
        "backend.shift_job_tracking_routes.get_db", return_value=conn
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.shift_job_tracking_routes._tenant_id", return_value=3
    ), patch(
        "backend.shift_job_tracking_routes.get_open_job_segment", return_value=None
    ), patch(
        "backend.shift_job_tracking.start_category_role_segment",
        side_effect=IdempotencyConflictError(
            "idempotency_key already used for a different category/role on this shift"
        ),
    ):
        body, code = view()
    assert code == 409
    assert body.get("code") == "idempotency_conflict"
    conn.rollback.assert_called()


def test_switch_task_accepts_header_idempotency_key():
    import backend.shift_job_tracking_routes as routes

    view = _unwrap(routes.job_tracking_switch_job)
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 99, "status": "active"}
    conn.cursor.return_value = cur
    seg = {
        "id": 5,
        "display_label": "DHS — Operator",
        "replayed": False,
        "noop": False,
        "unchanged": False,
    }
    with _patched_route_globals(
        request_json={"category_id": 1, "role_id": 2},
        headers={"Idempotency-Key": "hdr-key"},
    ), patch(
        "backend.shift_job_tracking_routes.get_db", return_value=conn
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.shift_job_tracking_routes._tenant_id", return_value=3
    ), patch(
        "backend.shift_job_tracking_routes.get_open_job_segment", return_value=None
    ), patch(
        "backend.shift_job_tracking_routes.enrich_session_job_tracking", return_value={}
    ), patch(
        "backend.shift_job_tracking_routes.write_audit"
    ), patch(
        "backend.shift_job_tracking.start_category_role_segment", return_value=seg
    ) as start:
        body = view()
    assert isinstance(body, dict)
    assert body["segment"]["id"] == 5
    assert start.call_args.kwargs["idempotency_key"] == "hdr-key"
    conn.commit.assert_called_once()
