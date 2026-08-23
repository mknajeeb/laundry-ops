"""Regression tests for Management Rinse HD manual processing corrections."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_hd_performance import build_hd_employee_performance
from backend.management_rinse_hd import (
    ATTR_SOURCE_MANAGER,
    ATTR_SOURCE_SCAN,
    PROCESSING_ACTION_BACK_TO_AWAITING_FOLD,
    PROCESSING_ACTION_BACK_TO_PENDING_WASH,
    PROCESSING_ACTION_MARK_FOLDED,
    PROCESSING_ACTION_MARK_WASHED,
    STATUS_AWAITING_ENTRY,
    STATUS_COMPLETE,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    _hd_chronology_error,
    _persist_scan_state_for_admitted,
    apply_rinse_hd_processing_correction,
    resolve_order_state,
)


def _ev(purpose, at, user="Op", bag="HD100", eid=1):
    return {
        "id": eid,
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "user_name": user,
    }


def _fact(**overrides):
    base = {
        "id": 42,
        "bag_id": "HD100",
        "version": 3,
        "workflow_status": STATUS_PENDING_WASH,
        "status": "NOT_RECORDED",
        "operations_date_et": date(2026, 8, 23),
        "washed_at": None,
        "washed_by_user_id": None,
        "washed_attribution_source": None,
        "folded_at": None,
        "folded_by_user_id": None,
        "folded_attribution_source": None,
        "management_completed_at": None,
        "total_items": None,
        "revenue": None,
    }
    base.update(overrides)
    return base


def _detail_for_fact(fact, *, status=None):
    status = status or fact.get("workflow_status") or STATUS_PENDING_WASH
    return {
        "order": {
            "bag_id": fact["bag_id"],
            "status": status,
            "washed_at": fact.get("washed_at"),
            "washed_by_user_id": fact.get("washed_by_user_id"),
            "washed_by_name": fact.get("washed_by_name_snapshot"),
            "folded_at": fact.get("folded_at"),
            "folded_by_user_id": fact.get("folded_by_user_id"),
            "folded_by_name": fact.get("folded_by_name_snapshot"),
            "completion_at": fact.get("management_completed_at"),
        },
        "production": {
            "version": fact.get("version"),
            "items": fact.get("total_items"),
            "revenue": fact.get("revenue"),
            "workflow_status": status,
            "management_completed_at": fact.get("management_completed_at"),
        },
        "employees": [{"user_id": 10, "display_name": "Maria"}, {"user_id": 20, "display_name": "Tarannum"}],
    }


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._batch_user_names", return_value={10: "Maria", 20: "Tarannum"})
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_manual_wash_moves_to_awaiting_fold(mock_detail, mock_load, *_mocks):
    fact = _fact()
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_PENDING_WASH)
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action=PROCESSING_ACTION_MARK_WASHED,
        selected_date_et=date(2026, 8, 23),
        version=3,
        employee_user_id=10,
        operational_at=datetime(2026, 8, 23, 9, 0),
        actor_user_id=1,
        actor_display_name="Mgr",
    )
    assert out["ok"] is True
    assert out["workflow_status"] == STATUS_WASHED
    assert out["after"]["washed_attribution_source"] == ATTR_SOURCE_MANAGER
    assert cursor.execute.called


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._batch_user_names", return_value={20: "Tarannum"})
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_manual_fold_moves_to_awaiting_entry(mock_detail, mock_load, *_mocks):
    washed = datetime(2026, 8, 23, 9, 0)
    fact = _fact(
        workflow_status=STATUS_WASHED,
        washed_at=washed,
        washed_by_user_id=10,
        washed_attribution_source=ATTR_SOURCE_MANAGER,
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_WASHED)
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action=PROCESSING_ACTION_MARK_FOLDED,
        selected_date_et=date(2026, 8, 23),
        version=3,
        employee_user_id=20,
        operational_at=datetime(2026, 8, 23, 11, 0),
        actor_user_id=1,
        actor_display_name="Mgr",
    )
    assert out["ok"] is True
    assert out["workflow_status"] == STATUS_AWAITING_ENTRY
    assert out["after"]["folded_attribution_source"] == ATTR_SOURCE_MANAGER


@patch("backend.management_rinse_hd.mark_rinse_hd_complete")
@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_awaiting_entry_mark_complete_delegates(mock_detail, mock_load, _ens, _tbl, mock_complete):
    folded = datetime(2026, 8, 23, 11, 0)
    fact = _fact(
        workflow_status=STATUS_AWAITING_ENTRY,
        washed_at=datetime(2026, 8, 23, 9, 0),
        folded_at=folded,
        total_items=5,
        revenue=25.0,
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_AWAITING_ENTRY)
    mock_complete.return_value = {"ok": True, "workflow_status": STATUS_COMPLETE}
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action="mark_complete",
        selected_date_et=date(2026, 8, 23),
        version=3,
        actor_user_id=1,
        actor_display_name="Mgr",
    )
    assert out["ok"] is True
    mock_complete.assert_called_once()


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_back_to_pending_wash_from_awaiting_fold(mock_detail, mock_load, *_mocks):
    fact = _fact(
        workflow_status=STATUS_WASHED,
        washed_at=datetime(2026, 8, 23, 9, 0),
        washed_by_user_id=10,
        washed_attribution_source=ATTR_SOURCE_MANAGER,
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_WASHED)
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action=PROCESSING_ACTION_BACK_TO_PENDING_WASH,
        selected_date_et=date(2026, 8, 23),
        version=3,
        confirm_remove=True,
        actor_user_id=1,
    )
    assert out["ok"] is True
    assert out["workflow_status"] == STATUS_PENDING_WASH
    assert out["after"]["washed_at"] is None


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_back_to_awaiting_fold_from_awaiting_entry(mock_detail, mock_load, *_mocks):
    fact = _fact(
        workflow_status=STATUS_AWAITING_ENTRY,
        washed_at=datetime(2026, 8, 23, 9, 0),
        folded_at=datetime(2026, 8, 23, 11, 0),
        folded_by_user_id=20,
        total_items=4,
        revenue=18.0,
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_AWAITING_ENTRY)
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action=PROCESSING_ACTION_BACK_TO_AWAITING_FOLD,
        selected_date_et=date(2026, 8, 23),
        version=3,
        confirm_remove=True,
        actor_user_id=1,
    )
    assert out["ok"] is True
    assert out["workflow_status"] == STATUS_WASHED
    assert out["after"]["folded_at"] is None
    assert out["after"]["total_items"] is None


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_back_to_pending_wash_from_awaiting_entry(mock_detail, mock_load, *_mocks):
    fact = _fact(
        workflow_status=STATUS_AWAITING_ENTRY,
        washed_at=datetime(2026, 8, 23, 9, 0),
        folded_at=datetime(2026, 8, 23, 11, 0),
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_AWAITING_ENTRY)
    cursor = MagicMock()
    out = apply_rinse_hd_processing_correction(
        cursor,
        3,
        "HD100",
        action=PROCESSING_ACTION_BACK_TO_PENDING_WASH,
        selected_date_et=date(2026, 8, 23),
        version=3,
        confirm_remove=True,
        actor_user_id=1,
    )
    assert out["ok"] is True
    assert out["workflow_status"] == STATUS_PENDING_WASH


def test_manual_wash_then_normal_fold_scan():
    """Manager wash lock does not block a later legitimate fold scan."""
    events = [
        _ev("complete-cleaning", datetime(2026, 8, 23, 11, 0), user="Tarannum", eid=2),
    ]
    production = {
        "id": 1,
        "washed_at": datetime(2026, 8, 23, 9, 0),
        "washed_by_user_id": 10,
        "washed_attribution_source": ATTR_SOURCE_MANAGER,
        "folded_at": None,
        "folded_by_user_id": None,
        "folded_attribution_source": None,
        "workflow_status": STATUS_WASHED,
    }
    cursor = MagicMock()
    updated = _persist_scan_state_for_admitted(
        cursor,
        org=3,
        bid="HD100",
        events=events,
        production=production,
        user_maps={},
        activation=date(2026, 8, 21),
    )
    assert updated is not None
    assert updated["folded_at"] == datetime(2026, 8, 23, 11, 0)
    assert updated["workflow_status"] == STATUS_AWAITING_ENTRY
    state = resolve_order_state(
        events,
        service_hint="HD",
        production=updated,
        activation_date=date(2026, 8, 21),
    )
    assert state["status"] == STATUS_AWAITING_ENTRY
    assert state["washed_attribution_source"] == ATTR_SOURCE_MANAGER
    assert state["folded_attribution_source"] == ATTR_SOURCE_SCAN


def test_manual_wash_duplicate_wash_scan_ignored():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 23, 9, 30), user="Scanner", eid=2),
    ]
    production = {
        "id": 1,
        "washed_at": datetime(2026, 8, 23, 9, 0),
        "washed_by_user_id": 10,
        "washed_attribution_source": ATTR_SOURCE_MANAGER,
        "workflow_status": STATUS_WASHED,
    }
    cursor = MagicMock()
    updated = _persist_scan_state_for_admitted(
        cursor,
        org=3,
        bid="HD100",
        events=events,
        production=production,
        user_maps={},
        activation=date(2026, 8, 21),
    )
    assert updated["washed_by_user_id"] == 10
    assert updated["washed_at"] == datetime(2026, 8, 23, 9, 0)


def test_backward_correction_removes_performance_credit():
    washed_at = datetime(2026, 8, 23, 9, 0)
    row = {
        "bag_id": "HD100",
        "washed_by_user_id": 10,
        "washed_by_name_snapshot": "Maria",
        "washed_at": washed_at,
        "folded_by_user_id": None,
        "folded_at": None,
        "total_items": None,
        "revenue": None,
        "operations_date_et": date(2026, 8, 23),
        "workflow_status": STATUS_WASHED,
        "status": "NOT_RECORDED",
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria"},
    ):
        before = build_hd_employee_performance(cursor, 3, date(2026, 8, 23))
        row_cleared = {**row, "washed_at": None, "washed_by_user_id": None, "workflow_status": STATUS_PENDING_WASH}
        cursor.fetchall.return_value = [row_cleared]
        after = build_hd_employee_performance(cursor, 3, date(2026, 8, 23))
    assert before["employees"][0]["wash_count"] == 1
    assert after["employees"] == []


def test_chronology_validation_rejects_fold_before_wash():
    assert _hd_chronology_error(
        washed_at=datetime(2026, 8, 23, 11, 0),
        folded_at=datetime(2026, 8, 23, 9, 0),
    ) == "chronology_fold_before_wash"


@patch("backend.management_rinse_hd.table_exists", return_value=True)
@patch("backend.management_rinse_hd.ensure_management_hd_columns")
@patch("backend.management_rinse_hd._batch_user_names", return_value={10: "Maria"})
@patch("backend.management_rinse_hd._load_production_by_bag")
@patch("backend.management_rinse_hd.get_rinse_hd_order_detail")
def test_chronology_rejected_on_mark_folded(mock_detail, mock_load, *_mocks):
    fact = _fact(
        workflow_status=STATUS_WASHED,
        washed_at=datetime(2026, 8, 23, 11, 0),
        washed_by_user_id=10,
    )
    mock_load.return_value = {"HD100": fact}
    mock_detail.return_value = _detail_for_fact(fact, status=STATUS_WASHED)
    out = apply_rinse_hd_processing_correction(
        MagicMock(),
        3,
        "HD100",
        action=PROCESSING_ACTION_MARK_FOLDED,
        selected_date_et=date(2026, 8, 23),
        version=3,
        employee_user_id=10,
        operational_at=datetime(2026, 8, 23, 9, 0),
    )
    assert out["ok"] is False
    assert out["error"] == "chronology_fold_before_wash"


def test_no_duplicate_productivity_credit_after_manual_and_scan():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 23, 9, 30), user="Scanner", eid=2),
    ]
    production = {
        "id": 1,
        "washed_at": datetime(2026, 8, 23, 9, 0),
        "washed_by_user_id": 10,
        "washed_attribution_source": ATTR_SOURCE_MANAGER,
        "workflow_status": STATUS_WASHED,
    }
    updated = _persist_scan_state_for_admitted(
        MagicMock(),
        org=3,
        bid="HD100",
        events=events,
        production=production,
        user_maps={"scanner": {"user_id": 99}},
        activation=date(2026, 8, 21),
    )
    row = {
        "bag_id": "HD100",
        "washed_by_user_id": updated["washed_by_user_id"],
        "washed_at": updated["washed_at"],
        "folded_by_user_id": None,
        "folded_at": None,
        "total_items": None,
        "revenue": None,
        "operations_date_et": date(2026, 8, 23),
        "workflow_status": STATUS_WASHED,
        "status": "NOT_RECORDED",
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria"},
    ):
        perf = build_hd_employee_performance(cursor, 3, date(2026, 8, 23))
    assert len(perf["employees"]) == 1
    assert perf["employees"][0]["wash_count"] == 1
    assert perf["employees"][0]["user_id"] == 10


def test_normal_scan_workflow_unchanged():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 23, 9, 0), user="Maria", eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 23, 11, 0), user="Tarannum", eid=2),
    ]
    state = resolve_order_state(events, service_hint="HD", activation_date=date(2026, 8, 21))
    assert state["status"] == STATUS_AWAITING_ENTRY
    assert state["washed_by_name"] == "Maria"
    assert state["folded_by_name"] == "Tarannum"
    assert state["washed_attribution_source"] is None or state["washed_attribution_source"] == ATTR_SOURCE_SCAN
