"""Break-end requires category/role when tracking is enabled."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@contextmanager
def _patched_break_end_globals(*, request_json=None, g_user_id=23):
    import backend.ta_routes as routes

    req = SimpleNamespace(json=request_json if request_json is not None else {})
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


def test_break_end_requires_category_role_when_tracking_on():
    import backend.ta_routes as routes

    view = _unwrap(routes.break_end)
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 55, "status": "active", "user_id": 23}
    conn.cursor.return_value = cur
    tree = [{"id": 1, "name": "Wash", "roles": [{"role_id": 9, "role_name": "Folder"}]}]

    with _patched_break_end_globals(request_json={}), patch(
        "backend.ta_routes.get_db", return_value=conn
    ), patch("backend.ta_routes._tenant_id", return_value=3), patch(
        "backend.ta_routes.get_open_break", return_value={"id": 7}
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.shift_job_tracking.seed_default_categories_and_roles"
    ), patch(
        "backend.shift_job_tracking.list_active_selection_tree", return_value=tree
    ):
        body, code = view()

    assert code == 400
    assert body["needs_category_role"] is True
    assert body["selection_tree"] == tree


def test_break_end_starts_segment_on_resume():
    import backend.ta_routes as routes

    view = _unwrap(routes.break_end)
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 55, "status": "active", "user_id": 23},
        {"id": 7, "break_start_at": "2026-07-22 10:00:00", "break_end_at": "2026-07-22 10:15:00"},
    ]
    conn.cursor.return_value = cur
    segment = {"id": 100, "display_label": "Wash — Folder"}

    with _patched_break_end_globals(
        request_json={"category_id": 1, "role_id": 9}
    ), patch("backend.ta_routes.get_db", return_value=conn), patch(
        "backend.ta_routes._tenant_id", return_value=3
    ), patch(
        "backend.ta_routes.get_open_break", return_value={"id": 7}
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.shift_job_tracking.start_category_role_segment", return_value=segment
    ) as start_seg, patch(
        "backend.ta_routes.eastern_now_naive", return_value="2026-07-22 10:15:00"
    ):
        body = view()

    assert body["segment"] == segment
    start_seg.assert_called_once()
    assert start_seg.call_args.kwargs["change_source"] == "break_resume"
    assert start_seg.call_args.args[4] == 1
    assert start_seg.call_args.args[5] == 9
