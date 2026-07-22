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
