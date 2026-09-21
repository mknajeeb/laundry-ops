"""Synthetic acceptance for session rate override + employee-week OT disable."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_overtime import (
    aggregate_classified_batch_lines,
    allocate_session_overtime,
    split_hours_for_overtime,
)
from backend.payroll_session_rate import (
    normalize_payroll_rate_override,
    resolve_session_hourly_rate,
    set_session_payroll_rate_override,
)
from backend.payroll_week_ot import (
    OT_MODE_DEFAULT,
    OT_MODE_DISABLE,
    normalize_ot_week_mode,
    set_employee_week_ot_override,
)


def _rec(**kwargs):
    base = {
        "id": 1,
        "user_id": 7,
        "worker_name": "Ada",
        "approved_hours": 8,
        "worker_category": "temp",
        "profile_worker_category": "w2",
        "classification_source": "record_override",
        "clock_in_at": "2026-09-14T13:00:00",
        "resolved_hourly_rate": 17,
        "rate_source": "profile",
        "profile_hourly_rate": 17,
        "payroll_rate_override": None,
        "payroll_week_start": "2026-09-14",
        "ot_week_mode": "default",
    }
    base.update(kwargs)
    return base


def test_rate_resolution_profile_then_override():
    rate, source, ov = resolve_session_hourly_rate(17, None)
    assert float(rate) == 17
    assert source == "profile"
    assert ov is None
    rate, source, ov = resolve_session_hourly_rate(17, 20)
    assert float(rate) == 20
    assert source == "session_override"
    assert float(ov) == 20
    assert normalize_payroll_rate_override("") is None
    assert normalize_payroll_rate_override("18.5") == Decimal("18.50")
    with pytest.raises(ValueError):
        normalize_payroll_rate_override(0)


def test_temp_override_does_not_imply_rate_change():
    """Classification Temp without rate override keeps profile/effective rate."""
    rate, source, _ = resolve_session_hourly_rate(17.0, None)
    assert float(rate) == 17.0
    assert source == "profile"


def test_aggregate_uses_session_rate_override():
    records = [
        _rec(id=1, approved_hours=10, resolved_hourly_rate=17, rate_source="profile"),
        _rec(
            id=2,
            approved_hours=10,
            resolved_hourly_rate=20,
            rate_source="session_override",
            payroll_rate_override=20,
            clock_in_at="2026-09-15T13:00:00",
        ),
    ]
    lines = aggregate_classified_batch_lines(
        records, batch_category="temp", threshold_hours=40, ot_enabled=True
    )
    assert len(lines) == 2
    by_rate = {l["rate"]: l for l in lines}
    assert by_rate[17.0]["approved_hours"] == 10
    assert by_rate[20.0]["approved_hours"] == 10
    assert by_rate[20.0]["classification_provenance"][0]["rate_source"] == "session_override"
    assert by_rate[17.0]["classification_provenance"][0]["rate_source"] == "profile"


def test_disable_ot_keeps_all_hours_regular_via_existing_allocator():
    sessions = [
        _rec(id=1, approved_hours=15, clock_in_at="2026-09-14T13:00:00"),
        _rec(id=2, approved_hours=15, clock_in_at="2026-09-15T13:00:00"),
        _rec(id=3, approved_hours=15, clock_in_at="2026-09-16T13:00:00"),
    ]
    standard = allocate_session_overtime(sessions, threshold=40, enabled=True)
    assert sum(r for r, _ in standard.values()) == Decimal("40.00")
    assert sum(o for _, o in standard.values()) == Decimal("5.00")
    disabled = allocate_session_overtime(sessions, threshold=40, enabled=False)
    assert sum(r for r, _ in disabled.values()) == Decimal("45.00")
    assert sum(o for _, o in disabled.values()) == Decimal("0.00")
    # Same result through aggregate
    for s in sessions:
        s["ot_week_mode"] = "disable_ot"
        s["worker_category"] = "w2"
        s["classification_source"] = "profile"
    lines = aggregate_classified_batch_lines(
        sessions,
        batch_category="w2",
        threshold_hours=40,
        ot_enabled=True,
        week_ot_enabled={"2026-09-14": False},
    )
    assert len(lines) == 1
    assert lines[0]["approved_hours"] == 45
    assert lines[0]["ot_hours"] == 0
    assert lines[0]["ot_week_override_snapshot"] == "disable_ot"
    reg, ot = split_hours_for_overtime(45, threshold=40, enabled=True)
    assert (lines[0]["approved_hours"], lines[0]["ot_hours"]) != (float(reg), float(ot))


def test_mixed_w2_temp_rates_with_disable_ot():
    records = [
        _rec(
            id=1,
            worker_category="w2",
            classification_source="profile",
            approved_hours=25,
            resolved_hourly_rate=18,
            clock_in_at="2026-09-14T10:00:00",
            ot_week_mode="disable_ot",
        ),
        _rec(
            id=2,
            worker_category="temp",
            classification_source="record_override",
            approved_hours=20,
            resolved_hourly_rate=20,
            payroll_rate_override=20,
            rate_source="session_override",
            clock_in_at="2026-09-15T10:00:00",
            ot_week_mode="disable_ot",
        ),
    ]
    week_flags = {"2026-09-14": False}
    w2 = aggregate_classified_batch_lines(
        records,
        batch_category="w2",
        threshold_hours=40,
        ot_enabled=True,
        week_ot_enabled=week_flags,
    )
    temp = aggregate_classified_batch_lines(
        records,
        batch_category="temp",
        threshold_hours=40,
        ot_enabled=True,
        week_ot_enabled=week_flags,
    )
    assert w2[0]["ot_hours"] == 0
    assert w2[0]["approved_hours"] == 25
    assert w2[0]["rate"] == 18
    assert temp[0]["ot_hours"] == 0
    assert temp[0]["approved_hours"] == 20
    assert temp[0]["rate"] == 20
    assert temp[0]["classification_provenance"][0]["worker_category"] == "temp"


class _RateCur:
    def __init__(self, conn):
        self.conn = conn
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        self.conn.writes.append((sql, params))
        if "UPDATE shift_sessions" in sql and params:
            self.conn.session["payroll_rate_override"] = params[0]
            if "payroll_hours_approved=0" in sql:
                self.conn.session["payroll_hours_approved"] = 0

    def fetchone(self):
        if "FROM shift_sessions" in self._sql:
            return self.conn.session
        return None

    def fetchall(self):
        return []


class _RateConn:
    def __init__(self, session):
        self.session = session
        self.writes = []
        self.commits = 0

    def cursor(self, dictionary=False):
        return _RateCur(self)

    def commit(self):
        self.commits += 1


def test_rate_override_clears_only_that_session_approval():
    conn = _RateConn(
        {
            "id": 41,
            "user_id": 7,
            "clock_in_at": "2026-09-14T13:00:00",
            "payroll_hours_approved": 1,
            "payroll_rate_override": None,
        }
    )
    with patch("backend.payroll_session_rate.ensure_payroll_session_rate_schema"), patch(
        "backend.payroll_operations._session_in_org", return_value=True
    ), patch(
        "backend.payroll_workflow.resolve_worker_hourly_rate",
        return_value={"hourly_rate": 17, "rate_source": "profile"},
    ):
        out = set_session_payroll_rate_override(
            conn, 3, 41, value=20, actor_id=9, reason="temp bump"
        )
    assert out["approval_cleared"] is True
    assert out["payroll_rate_override"] == 20.0
    assert any("payroll_hours_approved=0" in w[0] for w in conn.writes)
    assert any("shift_session_rate_audit" in w[0] for w in conn.writes)


class _OtCur:
    def __init__(self, conn):
        self.conn = conn
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        self.conn.writes.append((sql, params))
        if "FROM employee_payroll_week_ot_overrides" in sql and "SELECT" in sql:
            self.conn._pending = self.conn.existing
        if "UPDATE shift_sessions" in sql or (
            "SET s.payroll_hours_approved=0" in sql
        ):
            self.conn.cleared = getattr(self.conn, "cleared", 0) + 2
            self.rowcount = 2
        else:
            self.rowcount = 0

    def fetchone(self):
        if "SELECT ot_mode" in self._sql:
            return self.conn.existing
        return None

    def fetchall(self):
        return []


class _OtConn:
    def __init__(self, existing=None):
        self.existing = existing
        self.writes = []
        self.commits = 0
        self.cleared = 0

    def cursor(self, dictionary=False):
        return _OtCur(self)

    def commit(self):
        self.commits += 1


def test_week_ot_override_clears_week_approvals_and_audits():
    conn = _OtConn(existing=None)
    with patch("backend.payroll_week_ot.ensure_payroll_week_ot_schema"), patch(
        "backend.payroll_week_ot.get_employee_week_ot_mode", return_value=OT_MODE_DEFAULT
    ), patch(
        "backend.payroll_identity.payroll_week_bounds",
        return_value=(date(2026, 9, 14), date(2026, 9, 20)),
    ), patch(
        "backend.payroll_week_ot._clear_week_session_approvals", return_value=3
    ) as clear_fn, patch(
        "backend.payroll_week_ot.table_has_column", return_value=True
    ):
        out = set_employee_week_ot_override(
            conn,
            3,
            7,
            "2026-09-16",
            ot_mode="disable_ot",
            actor_id=9,
            reason="no ot this week",
        )
    assert out["ot_mode"] == OT_MODE_DISABLE
    assert out["approval_cleared_count"] == 3
    assert out["payroll_week_start"] == "2026-09-14"
    clear_fn.assert_called_once()
    assert any("employee_payroll_week_ot_override_audit" in w[0] for w in conn.writes)
    assert normalize_ot_week_mode("Standard") == OT_MODE_DEFAULT
    assert normalize_ot_week_mode("disable_ot") == OT_MODE_DISABLE
