"""Manager-edit version lock — not updated_at — for WF Review saves."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.rinse_step1_edit_bag import apply_unified_bag_edit, capture_bag_edit_state
from backend.rinse_veewash_shift_day import persist_day_snapshot
from backend.tests.test_step1_edit_bag import _FakeCursor, _day_bag_row

DAY = date(2026, 7, 24)
ORG = 3
BAG = "01ZKCLSLOCK"


def _cursor_with_bag(**overrides):
    row = _day_bag_row(
        bag_id=BAG,
        effective_status="review_required",
        manager_edit_version=overrides.pop("manager_edit_version", 0),
        updated_at=overrides.pop(
            "updated_at", datetime(2026, 7, 24, 10, 0, 0, 123456)
        ),
        **overrides,
    )
    return _FakeCursor(day_bags={(ORG, DAY, BAG): row}), row


def test_workitem_save_succeeds_after_source_and_productivity_refresh():
    """Open detail → source/productivity refresh → save with original version succeeds."""
    cur, row = _cursor_with_bag(manager_edit_version=3)
    token = int(row["manager_edit_version"])

    # Simulate source/day persist (must not bump manager_edit_version).
    with patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=[
            {"status": "OPEN", "opened_at": None},
            {"status": "OPEN", "headline": {}, "shift_date_et": DAY},
        ],
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        # Directly prove INSERT ... ON DUPLICATE preserves version clause.
        from backend.rinse_veewash_shift_day import persist_day_snapshot

        persist_day_snapshot(
            MagicMock(),
            ORG,
            DAY,
            workload={
                "rows": [
                    {
                        "bag_id": BAG,
                        "service_type": "WF",
                        "rush_status": "RUSH",
                        "effective_status": "review_required",
                        "bag_snapshot": {"bag_id": BAG},
                    }
                ]
            },
            summary={"exceptions": {"review_required": 1}},
        )

    # Bump updated_at as a background scrape might (without touching version).
    row["updated_at"] = datetime(2026, 7, 24, 10, 5, 0, 999999)
    assert int(row["manager_edit_version"]) == token

    with patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        out = apply_unified_bag_edit(
            cur,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 1, "name": "Comforter"}]},
            expected_manager_edit_version=token,
            expected_updated_at="2026-07-24T10:00:00.123456-04:00",  # stale/mismatched ts
        )
    assert out["ok"] is True, out
    assert int(row["manager_edit_version"]) == token + 1


def test_two_manager_clients_second_gets_409():
    cur, row = _cursor_with_bag(manager_edit_version=5)
    with patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        a = apply_unified_bag_edit(
            cur,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
            expected_manager_edit_version=5,
        )
        assert a["ok"] is True
        b = apply_unified_bag_edit(
            cur,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 2}]},
            expected_manager_edit_version=5,
        )
    assert b["ok"] is False
    assert b["status"] == 409
    assert b["error"] == "conflict"
    assert b["manager_edit_version"] == 6


def test_persist_day_snapshot_sql_preserves_manager_edit_version():
    cursor = MagicMock()
    with patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=[
            {"status": "OPEN", "opened_at": None},
            {"status": "OPEN", "headline": {}, "shift_date_et": DAY},
        ],
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        persist_day_snapshot(
            cursor,
            ORG,
            DAY,
            workload={
                "rows": [
                    {
                        "bag_id": BAG,
                        "service_type": "WF",
                        "rush_status": "RUSH",
                        "effective_status": "review_required",
                        "bag_snapshot": {"bag_id": BAG},
                    }
                ]
            },
            summary={"exceptions": {"review_required": 1}},
        )
    bag_sqls = [
        str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args and "INSERT INTO rinse_shift_monitor_day_bags" in str(c.args[0])
    ]
    assert bag_sqls
    compact = bag_sqls[0].replace(" ", "").replace("\n", "")
    assert "manager_edit_version=manager_edit_version" in compact
    assert "updated_at=updated_at" in compact
    assert "IF(manager_edit_version>0,effective_status,VALUES(effective_status))" in compact
    assert (
        "IF(manager_edit_version>0,canonical_completion_timestamp,"
        "VALUES(canonical_completion_timestamp))" in compact
    )


def test_legacy_updated_at_ignores_microseconds_and_offset():
    """Fallback path: truncated API timestamp must not false-conflict."""
    cur, row = _cursor_with_bag(
        manager_edit_version=0,
        updated_at=datetime(2026, 7, 24, 10, 0, 0, 123456),
    )
    with patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        out = apply_unified_bag_edit(
            cur,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
            # No expected_manager_edit_version — legacy FE path.
            expected_updated_at="2026-07-24T10:00:00-04:00",
        )
    assert out["ok"] is True, out


def test_capture_exposes_manager_edit_version():
    cur, row = _cursor_with_bag(manager_edit_version=9)
    state = capture_bag_edit_state(cur, ORG, DAY, BAG)
    assert state["manager_edit_version"] == 9
