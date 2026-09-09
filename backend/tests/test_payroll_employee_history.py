"""Employee payroll history + batch details enrich cache (no math changes)."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.payroll_batch_enrich_cache import bulk_user_display_meta
from backend.payroll_payout_details import _filter_batches_by_history_range


def test_filter_batches_by_history_range_this_year():
    batches = [
        {"id": 1, "pay_period_end": "2026-01-15"},
        {"id": 2, "pay_period_end": "2025-12-31"},
        {"id": 3, "pay_period_end": "2026-08-01"},
    ]
    with patch(
        "backend.business_time.business_today",
        return_value=date(2026, 9, 8),
    ):
        out = _filter_batches_by_history_range(batches, "this_year")
    assert [b["id"] for b in out] == [1, 3]


def test_filter_batches_by_history_range_last_n():
    batches = [{"id": i, "pay_period_end": f"2026-0{i}-01"} for i in range(1, 8)]
    with patch(
        "backend.business_time.business_today",
        return_value=date(2026, 9, 8),
    ):
        assert [b["id"] for b in _filter_batches_by_history_range(batches, "last_5")] == [
            1,
            2,
            3,
            4,
            5,
        ]


def test_bulk_user_display_meta_empty():
    conn = MagicMock()
    assert bulk_user_display_meta(conn, []) == {}


def test_panel_skips_details_without_worker():
    from pathlib import Path

    text = Path("frontend/src/components/AccountantEmployeePaystubsPanel.jsx").read_text()
    assert "Select a worker to view payroll history." in text
    assert "getEmployeePayrollHistory" in text
    assert "scopedBatches.map" not in text
    assert 'viewMode === "employee" && !selectedWorker' in text


def test_employee_history_route_registered():
    from pathlib import Path

    routes = Path("backend/ta_routes.py").read_text()
    assert '/payroll/employee/<int:user_id>/history' in routes
    assert "list_employee_payroll_history" in routes
