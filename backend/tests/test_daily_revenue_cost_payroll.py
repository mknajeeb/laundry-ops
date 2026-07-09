"""Tests for DRC payroll adapter."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from backend.daily_revenue_cost_constants import LK_PAYROLL_TOTAL, SOURCE_PAYROLL
from backend.daily_revenue_cost_payroll import (
    build_payroll_daily_total,
    fetch_payroll_total_suggestion,
    resolve_payroll_line_for_save,
    should_apply_payroll_suggestion,
)


def test_build_payroll_daily_total_sums_hours_times_rate():
    records = [
        {"id": 1, "approved_hours": 8, "hourly_rate": 19.5, "worker_name": "Alice"},
        {"id": 2, "approved_hours": 6, "hourly_rate": 17.0, "worker_name": "Bob"},
    ]
    total, workers = build_payroll_daily_total(records)
    assert total == 258.0
    assert len(workers) == 2


def test_fetch_payroll_total_suggestion_none_when_no_records():
    with patch(
        "backend.daily_shift_roster_payroll.list_payroll_time_records_for_date",
        return_value=[],
    ):
        out = fetch_payroll_total_suggestion(object(), 1, date(2026, 7, 9))
    assert out is None


def test_fetch_payroll_total_suggestion_includes_metadata():
    records = [
        {
            "id": 10,
            "user_id": 5,
            "approved_hours": 8,
            "hourly_rate": 20,
            "worker_name": "Alice",
            "status": "closed",
            "work_date": "2026-07-09",
        }
    ]
    with patch(
        "backend.daily_shift_roster_payroll.list_payroll_time_records_for_date",
        return_value=records,
    ):
        out = fetch_payroll_total_suggestion(object(), 1, date(2026, 7, 9))
    assert out is not None
    assert out["line_key"] == LK_PAYROLL_TOTAL
    assert out["source_system"] == SOURCE_PAYROLL
    assert out["amount"] == 160.0
    assert "payroll-day:2026-07-09" in out["source_ref"]
    assert out["source_payload"]["record_count"] == 1


def test_should_not_apply_when_manual_override():
    line = {"source_system": SOURCE_PAYROLL, "is_manual_override": 1, "amount": 500}
    assert should_apply_payroll_suggestion(line) is False


def test_resolve_payroll_preserves_override():
    existing = {"source_system": SOURCE_PAYROLL, "is_manual_override": 1, "amount": 500, "source_ref": "x"}
    out = resolve_payroll_line_for_save(
        payload_amount=600,
        overrides={LK_PAYROLL_TOTAL: {"is_manual_override": True, "reason": "Bonus"}},
        existing_line=existing,
        suggestion={"amount": 160, "source_system": SOURCE_PAYROLL},
    )
    assert out["amount"] == 600
    assert out["is_override"] is True
    assert out["override_reason"] == "Bonus"


def test_resolve_payroll_applies_suggestion_on_first_save():
    suggestion = {
        "amount": 642.15,
        "source_system": SOURCE_PAYROLL,
        "source_ref": "payroll-day:2026-07-09",
        "source_captured_at": "2026-07-09 12:00:00",
        "source_payload": {"total_gross": 642.15},
    }
    out = resolve_payroll_line_for_save(
        payload_amount=642.15,
        overrides={},
        existing_line=None,
        suggestion=suggestion,
    )
    assert out["amount"] == 642.15
    assert out["source_system"] == SOURCE_PAYROLL
    assert out["source_ref"] == "payroll-day:2026-07-09"
    assert out["is_override"] is False
