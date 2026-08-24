"""HD performance attribution + lazy detail regression tests."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_hd_performance import (
    build_hd_employee_performance,
    build_hd_employee_performance_detail,
)


def _row(**kwargs):
    base = {
        "bag_id": "HD1",
        "washed_by_user_id": 10,
        "washed_by_name_snapshot": "Maria",
        "washed_at": datetime(2026, 8, 24, 8, 0),
        "folded_by_user_id": 20,
        "folded_by_name_snapshot": "Angelica",
        "folded_at": datetime(2026, 8, 24, 16, 0),
        "total_items": 5,
        "revenue": 30.0,
        "operations_date_et": date(2026, 8, 24),
        "workflow_status": "COMPLETE",
        "status": "COMPLETE",
    }
    base.update(kwargs)
    return base


def _perf(cursor, day, **kwargs):
    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria", 20: "Angelica", 30: "Jennifer"},
    ):
        return build_hd_employee_performance(cursor, 3, day, **kwargs)


def test_wash_credited_by_washed_at_employee():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(washed_by_user_id=30, folded_by_user_id=None, folded_at=None)]
    perf = _perf(cursor, date(2026, 8, 24))
    by = {e["user_id"]: e for e in perf["employees"]}
    assert by[30]["wash_count"] == 1
    assert by[30]["fold_count"] == 0


def test_fold_credited_by_folded_at_employee():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        _row(washed_by_user_id=None, washed_at=None, folded_by_user_id=20, folded_at=datetime(2026, 8, 24, 16, 0))
    ]
    perf = _perf(cursor, date(2026, 8, 24))
    by = {e["user_id"]: e for e in perf["employees"]}
    assert by[20]["fold_count"] == 1
    assert by[20]["wash_count"] == 0


def test_same_bag_credits_two_different_employees():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(washed_by_user_id=30, folded_by_user_id=20)]
    perf = _perf(cursor, date(2026, 8, 24))
    by = {e["user_id"]: e for e in perf["employees"]}
    assert by[30]["wash_count"] == 1 and by[30]["fold_count"] == 0
    assert by[20]["fold_count"] == 1 and by[20]["wash_count"] == 0


def test_day_attribution_uses_operation_timestamp_not_bag_day():
    cursor = MagicMock()
    washed_at = datetime(2026, 8, 23, 22, 0)
    folded_at = datetime(2026, 8, 24, 9, 0)
    cursor.fetchall.return_value = [
        _row(
            bag_id="CROSS",
            washed_at=washed_at,
            folded_at=folded_at,
            operations_date_et=date(2026, 8, 24),
        )
    ]
    wash_day = _perf(cursor, date(2026, 8, 23))
    fold_day = _perf(cursor, date(2026, 8, 24))
    assert sum(e["wash_count"] for e in wash_day["employees"]) == 1
    assert sum(e["fold_count"] for e in fold_day["employees"]) == 1


def test_cross_day_wash_and_fold_split():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        _row(
            bag_id="SPLIT",
            washed_at=datetime(2026, 8, 23, 10, 0),
            folded_at=datetime(2026, 8, 24, 15, 0),
            washed_by_user_id=30,
            folded_by_user_id=20,
            operations_date_et=date(2026, 8, 24),
        )
    ]
    aug23 = _perf(cursor, date(2026, 8, 23))
    aug24 = _perf(cursor, date(2026, 8, 24))
    assert {e["user_id"]: e["wash_count"] for e in aug23["employees"]} == {30: 1}
    assert {e["user_id"]: e["fold_count"] for e in aug24["employees"]} == {20: 1}


def test_manual_correction_clears_wash_credit():
    cursor = MagicMock()
    row = _row(washed_by_user_id=10, folded_by_user_id=None, folded_at=None)
    cursor.fetchall.return_value = [row]
    before = _perf(cursor, date(2026, 8, 24))
    cursor.fetchall.return_value = [{**row, "washed_at": None, "washed_by_user_id": None}]
    after = _perf(cursor, date(2026, 8, 24))
    assert before["employees"][0]["wash_count"] == 1
    assert after["employees"] == []


def test_correction_does_not_duplicate_credit():
    cursor = MagicMock()
    row = _row(bag_id="HD100", washed_by_user_id=10, folded_by_user_id=None, folded_at=None)
    cursor.fetchall.return_value = [row]
    perf = _perf(cursor, date(2026, 8, 24))
    maria = next(e for e in perf["employees"] if e["user_id"] == 10)
    assert maria["wash_count"] == 1
    assert len(maria["wash_bags"]) == 1


def test_move_back_reopen_does_not_double_credit():
    cursor = MagicMock()
    row = _row(bag_id="HD200", workflow_status="WASHED", status="WASHED")
    cursor.fetchall.return_value = [row]
    perf = _perf(cursor, date(2026, 8, 24))
    assert perf["summary"]["bags_washed"] == 1
    assert perf["summary"]["bags_folded"] == 1


def test_employee_totals_equal_unique_operation_events():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        _row(bag_id="A", washed_by_user_id=10, folded_by_user_id=10),
        _row(bag_id="B", washed_by_user_id=10, folded_by_user_id=20),
    ]
    perf = _perf(cursor, date(2026, 8, 24))
    maria = next(e for e in perf["employees"] if e["user_id"] == 10)
    assert maria["wash_count"] == 2
    assert maria["fold_count"] == 1
    assert perf["summary"]["bags_washed"] == 2
    assert perf["summary"]["bags_folded"] == 2


def test_summary_only_strips_bag_lists_but_keeps_counts():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(washed_by_user_id=10, folded_by_user_id=None, folded_at=None)]
    perf = _perf(cursor, date(2026, 8, 24), summary_only=True)
    emp = next(e for e in perf["employees"] if e["user_id"] == 10)
    assert emp["wash_count"] == 1
    assert "wash_bags" not in emp
    assert emp.get("first_wash_at") is not None


def test_detail_rows_reconcile_to_summary_totals():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        _row(bag_id="D1", washed_by_user_id=30, folded_by_user_id=None, folded_at=None),
        _row(bag_id="D2", washed_by_user_id=30, folded_by_user_id=None, folded_at=None),
    ]
    perf = _perf(cursor, date(2026, 8, 24), summary_only=False)
    jennifer = next(e for e in perf["employees"] if e["user_id"] == 30)
    assert jennifer["wash_count"] == len(jennifer["wash_bags"]) == 2


def test_lazy_detail_matches_summary_bag_ids():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(bag_id="LAZY1", washed_by_user_id=10, folded_by_user_id=20)]
    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria", 20: "Angelica"},
    ), patch(
        "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
        side_effect=lambda _c, _o, bags, **k: [{**b, "customer_name": "Test Customer"} for b in bags],
    ):
        summary = build_hd_employee_performance(cursor, 3, date(2026, 8, 24), summary_only=True)
        detail = build_hd_employee_performance_detail(cursor, 3, date(2026, 8, 24), 10)
    maria_summary = next(e for e in summary["employees"] if e["user_id"] == 10)
    assert detail["ok"] is True
    assert maria_summary["wash_count"] == len(detail["employee"]["wash_bags"]) == 1


def test_no_duplicate_employee_or_order_rows():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(bag_id="UNIQ")]
    perf = _perf(cursor, date(2026, 8, 24))
    assert len(perf["employees"]) == 2
    bag_ids = [b["bag_id"] for e in perf["employees"] for b in (e.get("wash_bags") or [])]
    assert bag_ids == ["UNIQ"]


def test_customer_name_resolves_in_detail():
    cursor = MagicMock()
    cursor.fetchall.return_value = [_row(bag_id="CN1", washed_by_user_id=10)]
    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria"},
    ), patch(
        "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
        side_effect=lambda _c, _o, bags, **k: [{**b, "customer_name": "Ada Lovelace"} for b in bags],
    ):
        detail = build_hd_employee_performance_detail(cursor, 3, date(2026, 8, 24), 10)
    assert detail["employee"]["wash_bags"][0]["customer_name"] == "Ada Lovelace"
