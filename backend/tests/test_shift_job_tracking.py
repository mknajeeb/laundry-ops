"""Tests for shift category/role task tracking (Phase 1)."""

from __future__ import annotations

from datetime import datetime, time
from unittest.mock import MagicMock, patch

import pytest

from backend.shift_job_tracking import (
    DEFAULT_CATEGORIES,
    STANDARD_ROLES,
    build_shift_timeline,
    create_category,
    delete_category,
    enrich_session_job_tracking,
    get_last_check_in_assignment,
    resolve_scheduled_end_at,
    switch_category_role,
)


def test_default_categories_and_standard_roles():
    assert len(DEFAULT_CATEGORIES) == 4
    assert [c for c, _ in DEFAULT_CATEGORIES] == ["RINSE_WF", "RINSE_HD", "DHS", "DROP_OFF"]
    assert [n for _, n in DEFAULT_CATEGORIES] == ["Rinse WF", "Rinse HD", "DHS", "Drop Off"]
    assert STANDARD_ROLES == (("OPERATOR", "Operator"), ("FOLDER", "Folder"))


def test_resolve_scheduled_end_at_from_schedule():
    """Helper may still exist for other modules; Phase 1 tracking does not use it for force checkout."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = [
        {"start_time": time(9, 0), "end_time": time(15, 0), "work_date": datetime(2026, 7, 1).date()},
    ]

    with patch("backend.shift_job_tracking.table_exists", return_value=True):
        end = resolve_scheduled_end_at(
            conn, 1, 10, datetime(2026, 7, 1, 10, 30)
        )
    assert end == datetime(2026, 7, 1, 15, 0)


def test_switch_category_role_calls_start_segment():
    conn = MagicMock()
    with patch(
        "backend.shift_job_tracking.start_category_role_segment",
        return_value={"id": 1, "display_label": "DHS — Operator"},
    ) as mock_start:
        seg = switch_category_role(conn, 9, 1, 10, 3, 7)
    assert seg["display_label"] == "DHS — Operator"
    mock_start.assert_called_once_with(
        conn, 9, 1, 10, 3, 7, change_source="switch"
    )


def test_create_category_auto_assigns_operator_and_folder():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        None,  # duplicate code check
        (0,),  # max sort_order
        {"id": 11, "code": "OPERATOR"},  # OPERATOR exists
        {"id": 12, "code": "FOLDER"},  # FOLDER exists
        {
            "id": 50,
            "organization_id": 1,
            "code": "COMMERCIAL",
            "name": "Commercial",
            "sort_order": 0,
            "active": 1,
        },
    ]
    cursor.lastrowid = 50

    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.json_safe", side_effect=lambda x: x
    ):
        cat = create_category(cursor, 1, "Commercial")

    assert cat["id"] == 50
    assert cat["code"] == "COMMERCIAL"
    insert_sqls = [
        c.args[0]
        for c in cursor.execute.call_args_list
        if "INSERT INTO ta_task_category_roles" in str(c.args[0])
    ]
    assert len(insert_sqls) == 2
    role_ids_assigned = [
        c.args[1][2]
        for c in cursor.execute.call_args_list
        if "INSERT INTO ta_task_category_roles" in str(c.args[0])
    ]
    assert role_ids_assigned == [11, 12]


def test_delete_category_rejects_when_used():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 1, "name": "DHS", "organization_id": 1, "active": 1, "code": "DHS"},
        (3,),
    ]
    with patch("backend.shift_job_tracking.table_exists", return_value=True), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.json_safe", side_effect=lambda x: x
    ):
        with pytest.raises(ValueError, match="cannot be deleted"):
            delete_category(cursor, 1, 1)


def test_delete_category_when_unused():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 2, "name": "Commercial", "organization_id": 1, "active": 1, "code": "COMMERCIAL"},
        (0,),
    ]
    with patch("backend.shift_job_tracking.table_exists", return_value=True), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.json_safe", side_effect=lambda x: x
    ):
        delete_category(cursor, 1, 2)
    delete_sqls = [str(c.args[0]) for c in cursor.execute.call_args_list if "DELETE FROM" in str(c.args[0])]
    assert any("ta_task_category_roles" in s for s in delete_sqls)
    assert any("ta_task_categories" in s for s in delete_sqls)


def test_build_shift_timeline():
    rec = {
        "clock_in_at": datetime(2026, 7, 1, 7, 0),
        "clock_out_at": datetime(2026, 7, 1, 13, 30),
        "checkout_type": "manual",
    }
    segments = [
        {
            "category_id": 1,
            "role_id": 2,
            "category_code": "RINSE_WF",
            "role_code": "OPERATOR",
            "display_label": "Rinse WF — Operator",
            "started_at": datetime(2026, 7, 1, 7, 0),
            "ended_at": datetime(2026, 7, 1, 7, 25),
        },
        {
            "category_id": 1,
            "role_id": 3,
            "category_code": "RINSE_WF",
            "role_code": "FOLDER",
            "display_label": "Rinse WF — Folder",
            "started_at": datetime(2026, 7, 1, 7, 25),
            "ended_at": datetime(2026, 7, 1, 8, 15),
        },
    ]
    timeline = build_shift_timeline(rec, segments)
    assert timeline[0]["type"] == "check_in"
    assert timeline[1]["type"] == "task"
    assert timeline[1]["display_label"] == "Rinse WF — Operator"
    assert timeline[1]["category_code"] == "RINSE_WF"
    assert timeline[1]["role_code"] == "OPERATOR"
    assert timeline[-1]["type"] == "check_out"
    assert timeline[-1]["label"] == "Checked Out"


def test_get_last_check_in_assignment():
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {
        "category_id": 4,
        "role_id": 2,
        "category_role_id": 9,
        "category_code": "DHS",
        "role_code": "OPERATOR",
        "category_name_snapshot": "DHS",
        "role_name_snapshot": "Operator",
    }
    conn.cursor.return_value = cur
    with patch("backend.shift_job_tracking.table_exists", return_value=True), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch("backend.shift_job_tracking.json_safe", side_effect=lambda x: x):
        last = get_last_check_in_assignment(conn, 10)
    assert last["category_id"] == 4
    assert last["role_id"] == 2
    assert last["display_label"] == "DHS — Operator"


def test_enrich_session_job_tracking_payload():
    conn = MagicMock()
    seg_cur = MagicMock()
    seg_cur.fetchone.return_value = {
        "id": 9,
        "category_id": 1,
        "role_id": 2,
        "category_role_id": 5,
        "category_name_snapshot": "Rinse WF",
        "role_name_snapshot": "Operator",
        "display_label": "Rinse WF — Operator",
        "started_at": datetime(2026, 7, 1, 8, 0),
        "ended_at": None,
    }
    seg_cur.fetchall.return_value = []
    conn.cursor.return_value = seg_cur
    sess = {
        "id": 1,
        "status": "active",
        "current_category_id": 1,
        "current_role_id": 2,
    }
    with patch("backend.shift_job_tracking.table_exists", return_value=True), patch(
        "backend.shift_job_tracking.json_safe", side_effect=lambda x: x
    ):
        out = enrich_session_job_tracking(conn, sess, 10)
    assert out["current_display_label"] == "Rinse WF — Operator"
    assert out["current_category_id"] == 1
    assert out["current_role_id"] == 2
    assert "force_checkout_blocked" not in out
    assert "effective_force_checkout_at" not in out


def test_ensure_schema_skips_modify_when_job_name_id_nullable():
    from backend.shift_job_tracking import (
        ensure_shift_job_tracking_schema,
        reset_shift_job_tracking_schema_gate_for_tests,
    )

    reset_shift_job_tracking_schema_gate_for_tests()
    cursor = MagicMock()

    def table_exists_side(cur, name):
        return name in {
            "ta_task_categories",
            "ta_task_roles",
            "ta_task_category_roles",
            "ta_job_names",
            "shift_job_segments",
            "shift_sessions",
            "payroll_profiles",
        }

    with patch(
        "backend.shift_job_tracking.table_exists", side_effect=table_exists_side
    ), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch(
        "backend.shift_job_tracking._column_is_not_null", return_value=False
    ), patch(
        "backend.shift_job_tracking._add_index_if_missing", return_value=False
    ), patch(
        "backend.shift_job_tracking.invalidate_schema_cache"
    ) as inv:
        ensure_shift_job_tracking_schema(cursor)
        # Second call must be a no-op (process gate)
        ensure_shift_job_tracking_schema(cursor)

    modify_calls = [
        c
        for c in cursor.execute.call_args_list
        if c.args and "MODIFY COLUMN job_name_id" in str(c.args[0])
    ]
    assert modify_calls == []
    inv.assert_not_called()
    reset_shift_job_tracking_schema_gate_for_tests()


def test_ensure_schema_modifies_job_name_id_only_when_not_null():
    from backend.shift_job_tracking import (
        ensure_shift_job_tracking_schema,
        reset_shift_job_tracking_schema_gate_for_tests,
    )

    reset_shift_job_tracking_schema_gate_for_tests()
    cursor = MagicMock()

    def table_exists_side(cur, name):
        return name in {
            "ta_task_categories",
            "ta_task_roles",
            "ta_task_category_roles",
            "ta_job_names",
            "shift_job_segments",
            "shift_sessions",
            "payroll_profiles",
        }

    with patch(
        "backend.shift_job_tracking.table_exists", side_effect=table_exists_side
    ), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch(
        "backend.shift_job_tracking._column_is_not_null", return_value=True
    ), patch(
        "backend.shift_job_tracking._add_index_if_missing", return_value=False
    ), patch(
        "backend.shift_job_tracking.invalidate_schema_cache"
    ) as inv:
        ensure_shift_job_tracking_schema(cursor)

    modify_calls = [
        c
        for c in cursor.execute.call_args_list
        if c.args and "MODIFY COLUMN job_name_id" in str(c.args[0])
    ]
    assert len(modify_calls) == 1
    inv.assert_called_once()
    reset_shift_job_tracking_schema_gate_for_tests()


def test_ensure_schema_failed_is_retryable():
    from backend import shift_job_tracking as sjt

    sjt.reset_shift_job_tracking_schema_gate_for_tests()
    cursor = MagicMock()
    calls = {"n": 0}

    def flaky_ensure(cur):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ddl failed")

    with patch.object(sjt, "_ensure_shift_job_tracking_schema_unlocked", side_effect=flaky_ensure):
        with pytest.raises(RuntimeError, match="ddl failed"):
            sjt.ensure_shift_job_tracking_schema(cursor)
        # Gate must remain unset so a later request can retry.
        sjt.ensure_shift_job_tracking_schema(cursor)
        sjt.ensure_shift_job_tracking_schema(cursor)

    assert calls["n"] == 2
    sjt.reset_shift_job_tracking_schema_gate_for_tests()


def test_start_category_role_segment_idempotent_by_key():
    from backend.shift_job_tracking import start_category_role_segment

    conn = MagicMock()
    existing = {
        "id": 44,
        "shift_session_id": 9,
        "category_id": 3,
        "role_id": 7,
        "category_role_id": 12,
        "category_code": "DHS",
        "role_code": "OPERATOR",
        "category_name_snapshot": "DHS",
        "role_name_snapshot": "Operator",
        "started_at": datetime(2026, 7, 1, 9, 0),
        "change_source": "switch",
        "idempotency_key": "key-1",
    }
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 9},  # FOR UPDATE lock
        existing,  # idempotency lookup
    ]
    conn.cursor.return_value = cur

    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch("backend.shift_job_tracking.json_safe", side_effect=lambda x: x), patch(
        "backend.shift_job_tracking.resolve_active_assignment"
    ) as resolve_fn, patch(
        "backend.shift_job_tracking.close_open_job_segment"
    ) as close_fn:
        out = start_category_role_segment(
            conn, 9, 1, 10, 3, 7, idempotency_key="key-1"
        )

    assert out["id"] == 44
    assert out["replayed"] is True
    assert out["unchanged"] is True
    resolve_fn.assert_not_called()
    close_fn.assert_not_called()


def test_start_category_role_segment_noop_when_same_open_assignment():
    from backend.shift_job_tracking import start_category_role_segment

    conn = MagicMock()
    open_seg = {
        "id": 50,
        "shift_session_id": 9,
        "category_id": 3,
        "role_id": 7,
        "category_role_id": 12,
        "category_name_snapshot": "DHS",
        "role_name_snapshot": "Operator",
        "started_at": datetime(2026, 7, 1, 9, 0),
        "change_source": "switch",
    }
    lock_cur = MagicMock()
    lock_cur.fetchone.return_value = {"id": 9}
    conn.cursor.return_value = lock_cur
    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.resolve_active_assignment",
        return_value={
            "id": 12,
            "category_id": 3,
            "role_id": 7,
            "category_code": "DHS",
            "role_code": "OPERATOR",
            "category_name": "DHS",
            "role_name": "Operator",
            "display_label": "DHS — Operator",
        },
    ), patch(
        "backend.shift_job_tracking.get_open_job_segment", return_value=open_seg
    ), patch(
        "backend.shift_job_tracking._find_segment_by_idempotency_key", return_value=None
    ), patch("backend.shift_job_tracking.json_safe", side_effect=lambda x: x), patch(
        "backend.shift_job_tracking.close_open_job_segment"
    ) as close_fn:
        out = start_category_role_segment(
            conn, 9, 1, 10, 3, 7, idempotency_key="key-new"
        )

    assert out["id"] == 50
    assert out["noop"] is True
    assert out["unchanged"] is True
    assert out["started_at"] == "2026-07-01T09:00:00"
    close_fn.assert_not_called()


def test_start_category_role_segment_rejects_key_reuse_for_different_assignment():
    from backend.shift_job_tracking import (
        IdempotencyConflictError,
        start_category_role_segment,
    )

    conn = MagicMock()
    existing = {
        "id": 44,
        "shift_session_id": 9,
        "category_id": 3,
        "role_id": 7,
        "idempotency_key": "key-1",
    }
    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking._lock_shift_session_for_switch"
    ), patch(
        "backend.shift_job_tracking._find_segment_by_idempotency_key",
        return_value=existing,
    ):
        with pytest.raises(IdempotencyConflictError, match="already used"):
            start_category_role_segment(
                conn, 9, 1, 10, 1, 2, idempotency_key="key-1"
            )


def test_start_category_role_segment_real_switch_same_transition_timestamp():
    from backend.shift_job_tracking import start_category_role_segment

    conn = MagicMock()
    lock_cur = MagicMock()
    lock_cur.fetchone.return_value = {"id": 9}
    ins = MagicMock()
    ins.lastrowid = 77
    conn.cursor.side_effect = [lock_cur, ins]
    transition = datetime(2026, 7, 1, 10, 15, 30)
    closed = {}

    def close_side(conn_, session_id, ended_at, **kwargs):
        closed["ended_at"] = ended_at

    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking._find_segment_by_idempotency_key", return_value=None
    ), patch(
        "backend.shift_job_tracking.resolve_active_assignment",
        return_value={
            "id": 20,
            "category_id": 1,
            "role_id": 2,
            "category_code": "RINSE_WF",
            "role_code": "FOLDER",
            "category_name": "Rinse WF",
            "role_name": "Folder",
            "display_label": "Rinse WF — Folder",
        },
    ), patch(
        "backend.shift_job_tracking.get_open_job_segment",
        return_value={
            "id": 50,
            "category_id": 1,
            "role_id": 1,
            "started_at": datetime(2026, 7, 1, 9, 0),
        },
    ), patch(
        "backend.shift_job_tracking.close_open_job_segment", side_effect=close_side
    ), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch(
        "backend.shift_job_tracking.eastern_now_naive", return_value=transition
    ):
        out = start_category_role_segment(
            conn, 9, 1, 10, 1, 2, idempotency_key="switch-1"
        )

    assert out["id"] == 77
    assert out["noop"] is False
    assert closed["ended_at"] == transition
    assert out["started_at"] == transition.isoformat()
    insert_args = ins.execute.call_args_list[0].args[1]
    assert transition in insert_args


def test_concurrent_same_key_returns_winner_on_duplicate():
    from backend.shift_job_tracking import start_category_role_segment

    conn = MagicMock()
    lock_cur = MagicMock()
    lock_cur.fetchone.return_value = {"id": 9}
    ins = MagicMock()

    class Dup(Exception):
        def __init__(self):
            self.args = (1062, "Duplicate entry")

    ins.execute.side_effect = Dup()
    conn.cursor.side_effect = [lock_cur, ins]
    winner = {
        "id": 88,
        "shift_session_id": 9,
        "category_id": 1,
        "role_id": 2,
        "category_name_snapshot": "Rinse WF",
        "role_name_snapshot": "Folder",
        "started_at": datetime(2026, 7, 1, 10, 0),
        "idempotency_key": "same-key",
    }
    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking._find_segment_by_idempotency_key",
        side_effect=[None, winner],
    ), patch(
        "backend.shift_job_tracking.resolve_active_assignment",
        return_value={
            "id": 20,
            "category_id": 1,
            "role_id": 2,
            "category_code": "RINSE_WF",
            "role_code": "FOLDER",
            "category_name": "Rinse WF",
            "role_name": "Folder",
            "display_label": "Rinse WF — Folder",
        },
    ), patch(
        "backend.shift_job_tracking.get_open_job_segment",
        return_value={"id": 1, "category_id": 9, "role_id": 9},
    ), patch("backend.shift_job_tracking.close_open_job_segment"), patch(
        "backend.shift_job_tracking.table_has_column", return_value=True
    ), patch("backend.shift_job_tracking.json_safe", side_effect=lambda x: x):
        out = start_category_role_segment(
            conn, 9, 1, 10, 1, 2, idempotency_key="same-key"
        )
    assert out["id"] == 88
    assert out["replayed"] is True
