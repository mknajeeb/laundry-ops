"""Phase 1C Daily Operations — HD production overlay."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.daily_operations_hd import (
    STATUS_COMPLETE,
    STATUS_NOT_RECORDED,
    STATUS_PARTIALLY_RECORDED,
    compute_hd_day_revenue_totals,
    derive_hd_production_status,
    list_org_employee_options,
    resolve_employee_display_name,
    save_hd_production,
    sum_reviewed_wf_workitem_revenue,
    undo_hd_production,
    validate_hd_production_fields,
)

DAY = date(2026, 7, 23)


def test_list_org_employee_options_works_without_users_email_column():
    """Prod users table has no email — picker/save must not SELECT it unconditionally."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 7, "username": "ann", "display_name": "Ann"},
    ]
    with patch("backend.daily_operations_hd.table_exists", return_value=True), patch(
        "backend.daily_operations_hd.table_has_column",
        side_effect=lambda _c, _t, col: col == "active",
    ), patch(
        "backend.portal_system_users.is_portal_system_user", return_value=False
    ):
        opts = list_org_employee_options(cursor, 3)
    sql = cursor.execute.call_args[0][0]
    assert "email" not in sql.lower()
    assert any(o.get("user_id") == 7 and o.get("display_name") == "Ann" for o in opts)


def test_resolve_employee_display_name_works_without_users_email_column():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"display_name": "Ann", "username": "ann"}
    with patch(
        "backend.daily_operations_hd.table_has_column", return_value=False
    ):
        assert resolve_employee_display_name(cursor, 3, 7) == "Ann"
    sql = cursor.execute.call_args[0][0]
    assert "email" not in sql.lower()


def test_status_not_recorded_when_empty():
    assert derive_hd_production_status({}) == STATUS_NOT_RECORDED


def test_status_partial_when_only_washer():
    assert (
        derive_hd_production_status({"washed_by_user_id": 1, "washed_by_name_snapshot": "A"})
        == STATUS_PARTIALLY_RECORDED
    )


def test_status_complete_when_all_valid():
    fields = {
        "washed_by_user_id": 1,
        "folded_by_user_id": 2,
        "total_items": 5,
        "revenue": 40.0,
    }
    assert derive_hd_production_status(fields) == STATUS_COMPLETE


def test_same_employee_washer_and_folder_ok():
    fields = {
        "washed_by_user_id": 7,
        "folded_by_user_id": 7,
        "total_items": 1,
        "revenue": 10,
    }
    assert derive_hd_production_status(fields) == STATUS_COMPLETE
    assert validate_hd_production_fields(fields, require_complete=True) == []


def test_zero_revenue_requires_code_and_other_needs_note():
    base = {
        "washed_by_user_id": 1,
        "folded_by_user_id": 2,
        "total_items": 1,
        "revenue": 0,
    }
    assert "zero_revenue_reason_required" in validate_hd_production_fields(base)
    base["zero_revenue_reason_code"] = "OTHER"
    assert "zero_revenue_other_requires_note" in validate_hd_production_fields(base)
    base["zero_revenue_reason_note"] = "comp"
    assert validate_hd_production_fields(base, require_complete=True) == []


def test_zero_items_codes():
    fields = {
        "washed_by_user_id": 1,
        "folded_by_user_id": 1,
        "total_items": 0,
        "revenue": 5,
        "zero_items_reason_code": "EMPTY_BAG",
    }
    assert validate_hd_production_fields(fields, require_complete=True) == []


def test_negative_rejected():
    assert "negative_revenue_rejected" in validate_hd_production_fields({"revenue": -1})
    assert "negative_total_items_rejected" in validate_hd_production_fields({"total_items": -2})


def test_free_text_without_external_rejected():
    errs = validate_hd_production_fields(
        {"washed_by_override_name": "Bob", "washed_by_external": False}
    )
    assert "washed_by_free_text_requires_external_option" in errs


def test_external_worker_requires_override_and_reason():
    errs = validate_hd_production_fields(
        {"washed_by_external": True, "washed_by_override_name": "", "reason": ""}
    )
    assert "washed_by_external_requires_override_name" in errs


def test_client_cannot_force_complete_via_status_field():
    # derive ignores any status key
    fields = {"status": STATUS_COMPLETE, "washed_by_user_id": 1}
    assert derive_hd_production_status(fields) == STATUS_PARTIALLY_RECORDED


def test_partial_revenue_excluded_from_day_total():
    cursor = MagicMock()
    membership = [{"bag_id": "H1", "day_bag_id": 1}, {"bag_id": "H2", "day_bag_id": 2}]
    facts = [
        {"bag_id": "H1", "status": STATUS_COMPLETE, "total_items": 2, "revenue": 50},
        {"bag_id": "H2", "status": STATUS_PARTIALLY_RECORDED, "total_items": 1, "revenue": 20},
    ]

    def fetchall_side():
        yield facts

    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags", return_value=membership
    ):
        cursor.fetchall.side_effect = [facts]
        out = compute_hd_day_revenue_totals(cursor, 3, DAY)
    assert out["complete_hd_revenue"] == 50.0
    assert out["partial_hd_revenue_entered"] == 20.0
    assert out["total_hd_revenue"] == 50.0
    assert out["complete"] == 1
    assert out["partially_recorded"] == 1


def test_orphan_fact_flagged():
    cursor = MagicMock()
    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags",
        return_value=[{"bag_id": "KEEP", "day_bag_id": 1}],
    ):
        cursor.fetchall.return_value = [
            {"bag_id": "ORPHAN", "status": STATUS_COMPLETE, "total_items": 1, "revenue": 9}
        ]
        out = compute_hd_day_revenue_totals(cursor, 3, DAY)
    assert out["orphan_production_facts"][0]["bag_id"] == "ORPHAN"
    assert out["orphan_production_facts"][0]["reconciliation_exception"] is True


def test_sum_reviewed_wi_only():
    cursor = MagicMock()
    with patch("backend.daily_operations_hd.table_exists", return_value=True):
        cursor.fetchone.return_value = {"total": Decimal("15.50")}
        assert sum_reviewed_wf_workitem_revenue(cursor, 3, DAY) == 15.5


def test_save_conflict_version_0():
    cursor = MagicMock()
    membership = {"BAGHD": {"bag_id": "BAGHD", "day_bag_id": 9}}
    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags",
        return_value=[membership["BAGHD"]],
    ), patch(
        "backend.daily_operations_hd.get_hd_production_row",
        return_value={"version": 2, "id": 1, "bag_id": "BAGHD"},
    ):
        out = save_hd_production(
            cursor,
            3,
            DAY,
            "BAGHD",
            {"version": 0, "reason": "x", "washed_by_user_id": 1},
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"
    assert out["current_version"] == 2


def test_non_hd_membership_rejected():
    cursor = MagicMock()
    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags", return_value=[]
    ):
        out = save_hd_production(
            cursor, 3, DAY, "WFONLY", {"version": 0, "reason": "x"}
        )
    assert out["ok"] is False
    assert out["error"] == "non_hd_membership_bag"


def test_save_complete_and_day_refresh():
    cursor = MagicMock()
    membership = [{"bag_id": "H1", "day_bag_id": 3}]

    def resolve_name(cursor, org, uid):
        return f"Emp{uid}"

    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags", return_value=membership
    ), patch(
        "backend.daily_operations_hd.get_hd_production_row",
        side_effect=[
            None,
            {
                "id": 10,
                "bag_id": "H1",
                "version": 1,
                "status": STATUS_COMPLETE,
                "washed_by_user_id": 1,
                "folded_by_user_id": 1,
                "washed_by_name_snapshot": "Emp1",
                "folded_by_name_snapshot": "Emp1",
                "total_items": 4,
                "revenue": 55.0,
            },
        ],
    ), patch(
        "backend.daily_operations_hd.resolve_employee_display_name", side_effect=resolve_name
    ), patch(
        "backend.daily_operations_hd.build_daily_operations_day",
        return_value={"revenue": {"hd_revenue": 55.0, "wf_workitem_revenue": 10.0, "total_revenue": 65.0}},
    ), patch(
        "backend.daily_operations_hd.compute_hd_day_revenue_totals",
        return_value={"complete_hd_revenue": 55.0},
    ):
        # users org check
        cursor.fetchone.return_value = {"id": 1}
        out = save_hd_production(
            cursor,
            3,
            DAY,
            "H1",
            {
                "version": 0,
                "reason": "entered",
                "washed_by_user_id": 1,
                "folded_by_user_id": 1,
                "total_items": 4,
                "revenue": 55,
            },
            actor_user_id=9,
        )
    assert out["ok"] is True
    assert out["status"] == STATUS_COMPLETE
    assert out["version"] == 1


def test_undo_first_save_restores_not_recorded():
    cursor = MagicMock()
    fact = {
        "id": 5,
        "bag_id": "H1",
        "version": 1,
        "status": STATUS_COMPLETE,
        "washed_by_user_id": 1,
        "folded_by_user_id": 2,
        "total_items": 3,
        "revenue": 12,
    }
    audit = {"id": 100, "before_json": {"exists": False}, "is_undo": 0}
    restored = {
        **fact,
        "version": 2,
        "status": STATUS_NOT_RECORDED,
        "washed_by_user_id": None,
        "folded_by_user_id": None,
        "total_items": None,
        "revenue": None,
    }
    with patch("backend.daily_operations_hd.ensure_hd_production_tables"), patch(
        "backend.daily_operations_hd.get_hd_production_row", side_effect=[fact, restored, restored]
    ), patch(
        "backend.daily_operations_hd.list_hd_day_membership_bags",
        return_value=[{"bag_id": "H1", "day_bag_id": 1}],
    ), patch(
        "backend.daily_operations_hd._json_load", return_value={"exists": False}
    ), patch(
        "backend.daily_operations_hd.build_daily_operations_day",
        return_value={"revenue": {"hd_revenue": 0, "total_revenue": 0}},
    ), patch(
        "backend.daily_operations_hd.compute_hd_day_revenue_totals",
        return_value={"complete_hd_revenue": 0.0},
    ):
        cursor.fetchone.side_effect = [audit, None]
        out = undo_hd_production(cursor, 3, DAY, "H1", reason="revert")
    assert out["ok"] is True
    assert out["production"]["status"] == STATUS_NOT_RECORDED
    assert out["version"] == 2


def test_export_includes_summary_keys():
    from backend.daily_operations_hd import export_hd_production_csv

    with patch(
        "backend.daily_operations_hd.build_hd_production_queue",
        return_value={
            "items": [
                {
                    "bag_id": "H1",
                    "status": STATUS_COMPLETE,
                    "membership": {"rush_status": "RUSH", "first_available": None},
                    "washed_by_name_snapshot": "A",
                    "folded_by_name_snapshot": "B",
                    "total_items": 2,
                    "revenue": 10,
                    "included_in_day_revenue": True,
                    "version": 1,
                }
            ],
            "summary": {
                "hd_orders_available": 1,
                "not_recorded": 0,
                "partially_recorded": 0,
                "complete": 1,
                "complete_total_items": 2,
                "complete_hd_revenue": 10.0,
                "partial_hd_revenue_entered": 0.0,
            },
        },
    ):
        name, body = export_hd_production_csv(MagicMock(), 3, DAY)
    assert "hd_production_2026-07-23.csv" == name
    assert "Complete HD Revenue" not in body  # key names are snake
    assert "complete_hd_revenue" in body
    assert "H1" in body
