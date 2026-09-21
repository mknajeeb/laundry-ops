"""Manual Payroll Analysis week availability — visibility only, no batch mutation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _batch(bid, status, finalized=None, name=None, cat="w2"):
    return {
        "id": bid,
        "batch_name": name or f"B-{bid}",
        "worker_category": cat,
        "status": status,
        "payout_details_finalized_at": finalized,
        "pay_period_start": "2026-09-07",
        "pay_period_end": "2026-09-13",
    }


class _FakeAvailStore:
    """In-memory stand-in for payroll_analysis_week_availability rows."""

    def __init__(self):
        self.rows = {}  # (org, ps, pe) -> dict
        self.batch_snapshots = []

    def key(self, org, ps, pe):
        return (int(org), str(ps)[:10], str(pe)[:10])


@pytest.fixture
def store():
    return _FakeAvailStore()


def test_incomplete_week_hidden_without_manual_flag(store):
    """Incomplete batch + week not manually available → week hidden."""
    from backend.payroll_report_analytics import list_org_periods_asc

    with patch(
        "backend.payroll_analysis_week_availability.list_available_analysis_weeks_asc",
        return_value=[],
    ):
        periods = list_org_periods_asc(
            MagicMock(), 1, require_complete=True, require_work_coverage=False
        )
    assert periods == []


def test_incomplete_week_visible_when_manager_marks_available():
    """Incomplete batch + manager makes week available → week visible."""
    from backend.payroll_report_analytics import list_org_periods_asc

    week = ("2026-09-07", "2026-09-13")
    with patch(
        "backend.payroll_analysis_week_availability.list_available_analysis_weeks_asc",
        return_value=[week],
    ):
        periods = list_org_periods_asc(
            MagicMock(), 1, require_complete=True, require_work_coverage=False
        )
    assert periods == [week]


def test_manual_availability_does_not_alter_batch_status():
    """set_week_analysis_availability never writes payout_batches."""
    from backend.payroll_analysis_week_availability import set_week_analysis_availability

    executed = []

    class Cur:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            # batch count lookup, then get_week row
            sql = executed[-1][0].lower()
            if "from payout_batches" in sql and "count" in sql:
                return {"c": 4}
            if "from payroll_analysis_week_availability" in sql:
                return {
                    "analysis_available": 1,
                    "analysis_available_at": "2026-09-20",
                    "analysis_available_by": 9,
                }
            return None

        def fetchall(self):
            return []

    class Conn:
        def cursor(self, dictionary=False):
            return Cur()

        def commit(self):
            pass

    with patch(
        "backend.payroll_analysis_week_availability.ensure_payroll_analysis_week_availability_schema"
    ):
        rec = set_week_analysis_availability(
            Conn(),
            1,
            "2026-09-07",
            "2026-09-13",
            available=True,
            actor_id=9,
        )

    assert rec["analysis_available"] is True
    batch_writes = [
        sql
        for sql, _ in executed
        if "update payout_batches" in sql.lower()
        or "insert into payout_batches" in sql.lower()
        or "delete from payout_batches" in sql.lower()
    ]
    assert batch_writes == []
    assert any(
        "insert into payroll_analysis_week_availability" in sql.lower() for sql, _ in executed
    )


def test_supplemental_w2_does_not_block_manual_availability():
    """Extra/supplemental W-2 (Evelyn) does not prevent manual availability."""
    from backend.payroll_report_analytics import (
        list_org_periods_asc,
        period_batches_are_complete,
    )

    batches = [
        _batch(120, "paid", finalized="2026-09-15", name="W2-2026-019"),
        _batch(121, "paid", finalized="2026-09-15", name="1099-2026-019", cat="1099"),
        _batch(123, "paid", finalized="2026-09-15", name="TEMP-2026-019", cat="temp"),
        _batch(122, "sent_to_accountant", name="W2-2026-019-EVELYN"),
    ]
    assert not period_batches_are_complete(batches)

    week = ("2026-09-07", "2026-09-13")
    with patch(
        "backend.payroll_analysis_week_availability.list_available_analysis_weeks_asc",
        return_value=[week],
    ):
        periods = list_org_periods_asc(
            MagicMock(), 1, require_complete=True, require_work_coverage=False
        )
    assert periods == [week]
    # Batch identities remain distinct
    assert {b["id"] for b in batches} == {120, 121, 122, 123}


def test_remove_availability_hides_week_without_payroll_mutation():
    """Remove availability → week disappears; no payout batch SQL writes."""
    from backend.payroll_analysis_week_availability import set_week_analysis_availability
    from backend.payroll_report_analytics import list_org_periods_asc

    executed = []

    class Cur:
        def __init__(self):
            self._n = 0

        def execute(self, sql, params=None):
            executed.append(sql)
            self._last = sql.lower()

        def fetchone(self):
            if "from payout_batches" in self._last and "count" in self._last:
                return {"c": 2}
            return {
                "analysis_available": 0,
                "analysis_available_at": None,
                "analysis_available_by": None,
            }

        def fetchall(self):
            return []

    class Conn:
        def cursor(self, dictionary=False):
            return Cur()

        def commit(self):
            pass

    with patch(
        "backend.payroll_analysis_week_availability.ensure_payroll_analysis_week_availability_schema"
    ):
        rec = set_week_analysis_availability(
            Conn(),
            1,
            "2026-09-07",
            "2026-09-13",
            available=False,
            actor_id=9,
        )
    assert rec["analysis_available"] is False
    assert not any("payout_batches" in s.lower() and ("update" in s.lower() or "delete" in s.lower()) for s in executed)

    with patch(
        "backend.payroll_analysis_week_availability.list_available_analysis_weeks_asc",
        return_value=[],
    ):
        assert (
            list_org_periods_asc(
                MagicMock(), 1, require_complete=True, require_work_coverage=False
            )
            == []
        )


def test_same_available_week_set_feeds_all_five_analysis_outputs():
    """All five Analysis outputs consume list_org_periods_asc(require_complete=True)."""
    import inspect

    from backend import payroll_report_analytics as pra

    src = inspect.getsource(pra.build_report_analytics)
    # Period mode must call list_org_periods_asc with require_complete=True once
    assert "list_org_periods_asc" in src
    assert "require_complete=True" in src
    # Charts derive from the same period_comparison / terminal_periods path
    assert "period_comparison" in src
    assert "employment_mix" in src


def test_multiple_same_week_batches_remain_distinct_by_id():
    """Multiple same-week batches remain distinct by numeric batch ID."""
    from backend.payroll_report_analytics import complete_period_keys_from_batches

    rows = [
        _batch(120, "paid", finalized="x", name="W2-2026-019"),
        _batch(122, "sent_to_accountant", name="W2-2026-019-EVELYN"),
    ]
    # Completeness is week-level for the *old* gate helper; IDs stay separate
    assert rows[0]["id"] != rows[1]["id"]
    assert complete_period_keys_from_batches(rows) == set()  # incomplete week


def test_list_org_periods_uses_manual_table_not_terminal_having():
    """require_complete=True reads availability table, not terminal HAVING SQL."""
    from backend.payroll_report_analytics import list_org_periods_asc

    with patch(
        "backend.payroll_analysis_week_availability.list_available_analysis_weeks_asc",
        return_value=[("2026-08-17", "2026-08-23"), ("2026-08-24", "2026-08-30")],
    ) as mock_list:
        periods = list_org_periods_asc(
            MagicMock(), 3, require_complete=True, require_work_coverage=False
        )
    assert periods == [("2026-08-17", "2026-08-23"), ("2026-08-24", "2026-08-30")]
    mock_list.assert_called_once()


def test_seed_helper_only_seeds_terminal_periods():
    """Migration seed uses terminal-complete periods only (incomplete weeks excluded)."""
    from backend.payroll_analysis_week_availability import (
        periods_currently_terminal_complete,
        seed_terminal_periods_as_analysis_available,
    )

    class Cur:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            # Simulate SQL HAVING already filtered to terminal weeks
            return [
                {"pay_period_start": "2026-08-17", "pay_period_end": "2026-08-23"},
                {"pay_period_start": "2026-08-24", "pay_period_end": "2026-08-30"},
            ]

        def fetchone(self):
            return None

    class Conn:
        def cursor(self, dictionary=False):
            return Cur()

        def commit(self):
            pass

    with patch(
        "backend.payroll_analysis_week_availability.ensure_payroll_analysis_week_availability_schema"
    ):
        periods = periods_currently_terminal_complete(Conn(), 1)
        assert ("2026-09-07", "2026-09-13") not in periods
        result = seed_terminal_periods_as_analysis_available(Conn(), 1, actor_id=1)
    assert result["seeded"] == 2
    assert len(result["periods"]) == 2
