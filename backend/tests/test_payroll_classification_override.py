"""Record-level payroll classification override. No production batches."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_classification import (
    frozen_line_classification_warnings,
    normalize_payroll_classification_override,
    resolve_session_payroll_category,
    set_session_payroll_classification_override,
    snapshot_category_for_session,
    write_line_classification_provenance,
)
from backend.payroll_operations import (
    approve_time_record,
    build_batch_from_time_records,
    list_time_records,
    time_record_status,
    update_time_record,
)
from backend.payroll_overtime import (
    aggregate_classified_batch_lines,
    split_hours_for_overtime,
    weekly_ot_policy_category,
)


def _rec(**kwargs):
    base = {
        "id": 1,
        "user_id": 7,
        "worker_name": "Ada",
        "approved_hours": 8,
        "worker_category": "w2",
        "profile_worker_category": "w2",
        "classification_source": "profile",
        "clock_in_at": "2026-09-14T13:00:00",
    }
    base.update(kwargs)
    return base


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        self.conn.writes.append((sql, params))
        if "UPDATE shift_sessions" in sql and params:
            self.conn.session["payroll_classification_override"] = params[0]
            if "payroll_hours_approved=0" in sql:
                self.conn.session["payroll_hours_approved"] = 0

    def fetchone(self):
        if "FROM shift_sessions" in self._sql:
            return self.conn.session
        return None

    def fetchall(self):
        if "payout_batch_lines" in self._sql:
            return self.conn.frozen
        return []


class _Conn:
    def __init__(self, session, frozen=None):
        self.session = session
        self.frozen = frozen or []
        self.writes = []
        self.commits = 0

    def cursor(self, dictionary=False):
        return _Cur(self)

    def commit(self):
        self.commits += 1


def _set(conn, value, reason="correct friday"):
    with patch("backend.payroll_classification.ensure_payroll_classification_schema"), patch(
        "backend.payroll_operations._session_in_org", return_value=True
    ), patch(
        "backend.payroll_operations.worker_category_for_user", return_value="w2"
    ):
        return set_session_payroll_classification_override(
            conn,
            3,
            41,
            value=value,
            actor_id=9,
            reason=reason,
        )


def test_null_override_uses_profile_and_record_override_wins():
    assert resolve_session_payroll_category("w2", None) == ("w2", "profile")
    assert resolve_session_payroll_category("w2", "") == ("w2", "profile")
    assert resolve_session_payroll_category("w2", "temp") == ("temp", "record_override")
    assert resolve_session_payroll_category("contractor_1099", "w2") == ("w2", "record_override")
    with pytest.raises(ValueError):
        normalize_payroll_classification_override("tryout")


def test_one_day_temp_override_leaves_surrounding_profile_days():
    conn = MagicMock()
    c = MagicMock()
    conn.cursor.return_value = c
    c.fetchall.return_value = [
        {
            "id": 1,
            "user_id": 7,
            "clock_in_at": datetime(2026, 9, 17, 14, 0, 0),
            "clock_out_at": datetime(2026, 9, 17, 22, 0, 0),
            "status": "completed",
            "total_break_seconds": 0,
            "net_work_seconds": 8 * 3600,
            "manual_override": 0,
            "payroll_hours_approved": 1,
            "payroll_classification_override": None,
            "period_adjustment_remarks": None,
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
        {
            "id": 2,
            "user_id": 7,
            "clock_in_at": datetime(2026, 9, 18, 14, 0, 0),
            "clock_out_at": datetime(2026, 9, 18, 22, 0, 0),
            "status": "completed",
            "total_break_seconds": 0,
            "net_work_seconds": 8 * 3600,
            "manual_override": 0,
            "payroll_hours_approved": 1,
            "payroll_classification_override": "temp",
            "period_adjustment_remarks": None,
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    ]

    class _Lookup:
        def rate_for(self, uid):
            return {"hourly_rate": 20, "rate_source": "profile", "rate_missing": False}

        def category_for(self, uid, on=None):
            return "w2"

    with patch("backend.payroll_operations.payroll_profiles_active", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", return_value=True), patch(
        "backend.payroll_operations.table_exists", return_value=False
    ), patch(
        "backend.payroll_list_lookup_cache.build_payroll_list_lookup_cache",
        return_value=_Lookup(),
    ), patch(
        "backend.payroll_time_record_breaks.attach_breaks_to_time_records"
    ):
        items = list_time_records(conn, 3, from_date="2026-09-14", to_date="2026-09-20")

    by_id = {item["id"]: item for item in items}
    assert by_id[1]["worker_category"] == "w2"
    assert by_id[1]["classification_source"] == "profile"
    assert by_id[1]["profile_worker_category"] == "w2"
    assert by_id[2]["worker_category"] == "temp"
    assert by_id[2]["classification_source"] == "record_override"
    assert by_id[2]["profile_worker_category"] == "w2"


def test_multi_role_session_inherits_one_classification():
    rec = _rec(
        id=5,
        worker_category="temp",
        classification_source="record_override",
        approved_hours=8,
        role_segments=[{"role_id": 1}, {"role_id": 2}],
    )
    lines = aggregate_classified_batch_lines(
        [rec], batch_category="temp", threshold_hours=40, ot_enabled=True
    )
    assert len(lines) == 1
    assert lines[0]["classification_provenance"][0]["shift_session_id"] == 5
    assert lines[0]["classification_provenance"][0]["worker_category"] == "temp"
    assert lines[0]["classification_provenance"][0]["classification_source"] == "record_override"
    assert lines[0]["session_ids"] == [5]


def test_override_clears_approval_and_keeps_audit_then_is_idempotent():
    conn = _Conn(
        {
            "id": 41,
            "user_id": 7,
            "clock_in_at": datetime(2026, 9, 18, 14, 0, 0),
            "payroll_hours_approved": 1,
            "payroll_classification_override": None,
        }
    )
    first = _set(conn, "temp", reason="friday was temp")
    assert first["approval_cleared"] is True
    assert first["payroll_hours_approved"] is False
    assert first["audit_appended"] is True
    assert first["worker_category"] == "temp"
    assert time_record_status({"status": "completed", "payroll_hours_approved": 0}) != "approved"
    updates = [sql for sql, _params in conn.writes if "UPDATE shift_sessions" in sql]
    assert updates and "payroll_hours_approved=0" in updates[0]
    assert "net_work_seconds" not in updates[0]
    assert "clock_in_at" not in updates[0]
    inserts = [item for item in conn.writes if "shift_session_classification_audit" in item[0]]
    assert len(inserts) == 1
    params = inserts[0][1]
    assert params[0] == 3
    assert params[1] == 41
    assert params[2] == 9
    assert isinstance(params[3], datetime)
    assert params[4] is None
    assert params[5] == "temp"
    assert params[6] == "friday was temp"
    assert not any("UPDATE payout_batch_lines" in sql for sql, _p in conn.writes)

    second = _set(conn, "temp", reason="again")
    assert second["audit_appended"] is False
    assert second["approval_cleared"] is False
    assert len([item for item in conn.writes if "shift_session_classification_audit" in item[0]]) == 1


def test_clearing_override_returns_to_profile():
    conn = _Conn(
        {
            "id": 41,
            "user_id": 7,
            "clock_in_at": datetime(2026, 9, 18, 14, 0, 0),
            "payroll_hours_approved": 0,
            "payroll_classification_override": "temp",
        }
    )
    result = _set(conn, None, reason="")
    assert result["payroll_classification_override"] is None
    assert result["worker_category"] == "w2"
    assert result["classification_source"] == "profile"
    assert result["audit_appended"] is True
    insert = [item for item in conn.writes if "shift_session_classification_audit" in item[0]][-1]
    assert insert[1][4] == "temp"
    assert insert[1][5] is None


def test_hour_edit_does_not_clear_classification_override():
    conn = MagicMock()
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 18, 8, 0),
        "clock_out_at": datetime(2026, 9, 18, 16, 0),
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]
    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_time_record_breaks.recompute_session_work_seconds", return_value={"id": 9, "total_break_seconds": 0, "net_work_seconds": None, "approved_hours": None, "hours_changed": False, "approval_cleared": False, "has_open_break": False}), patch(
        "backend.payroll_operations._resync_role_segments_to_session_clock", return_value=False
    ):
        update_time_record(
            conn,
            3,
            41,
            clock_in_at="2026-09-18 09:00:00",
            clock_out_at="2026-09-18 17:00:00",
        )
    sql = update_cur.execute.call_args[0][0]
    assert "payroll_classification_override" not in sql


def test_reapprove_keeps_override():
    conn = MagicMock()
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd]
    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", return_value=False), patch(
        "backend.payroll_time_record_breaks.assert_no_open_break_for_approval"
    ):
        rec = approve_time_record(conn, 3, 41)
    sql = upd.execute.call_args[0][0]
    assert "payroll_hours_approved=1" in sql
    assert "payroll_classification_override" not in sql
    assert rec["payroll_hours_approved"] is True


def test_frozen_historical_line_warns_and_is_not_rewritten():
    provenance = [
        {
            "shift_session_id": 41,
            "worker_category": "w2",
            "classification_source": "profile",
        }
    ]
    assert snapshot_category_for_session(provenance, 41) == "w2"
    conn = _Conn(
        {
            "id": 41,
            "user_id": 7,
            "clock_in_at": datetime(2026, 9, 18, 14, 0, 0),
            "payroll_hours_approved": 1,
            "payroll_classification_override": None,
        },
        frozen=[
            {
                "batch_id": 900,
                "batch_name": "W2-TEST-ONLY",
                "status": "paid",
                "batch_category": "w2",
                "line_id": 12,
                "line_category": "w2",
                "source_shift_session_ids": [41],
                "classification_provenance": provenance,
            }
        ],
    )
    with patch("backend.payroll_classification.table_exists", return_value=True), patch(
        "backend.payroll_classification.table_has_column", return_value=True
    ):
        result = _set(conn, "temp", reason="too late for history")
    assert result["warnings"]
    assert result["warnings"][0]["frozen_category"] == "w2"
    assert result["warnings"][0]["requested_category"] == "temp"
    assert "not moved" in result["warnings"][0]["message"]
    assert not any("UPDATE payout" in sql or "DELETE FROM payout" in sql for sql, _p in conn.writes)


def test_profile_edit_after_snapshot_does_not_change_stored_category():
    stored = [
        {
            "shift_session_id": 41,
            "worker_category": "w2",
            "classification_source": "profile",
        }
    ]
    assert snapshot_category_for_session(stored, 41) == "w2"
    warnings = frozen_line_classification_warnings(
        [
            {
                "batch_id": 1,
                "batch_name": "W2-TEST-ONLY",
                "status": "sent_to_accountant",
                "line_category": "temp",
                "source_shift_session_ids": [41],
                "classification_provenance": stored,
            }
        ],
        41,
        "temp",
    )
    assert warnings
    assert warnings[0]["frozen_category"] == "w2"
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    with patch("backend.payroll_classification.ensure_payroll_classification_schema"), patch(
        "backend.payroll_classification.table_has_column", return_value=True
    ):
        write_line_classification_provenance(conn, 12, stored)
    sql, params = cur.execute.call_args[0]
    assert sql == "UPDATE payout_batch_lines SET classification_provenance=%s WHERE id=%s"
    assert "approved_hours" not in sql
    assert "gross_amount" not in sql
    assert params[1] == 12


def test_paid_batch_sync_is_refused():
    with patch(
        "backend.payroll_operations._fetch_payout_batch_core",
        return_value={"id": 50, "status": "paid", "worker_category": "w2"},
    ):
        with pytest.raises(ValueError, match="reopened for correction"):
            build_batch_from_time_records(
                MagicMock(),
                3,
                50,
                from_date="2026-09-14",
                to_date="2026-09-20",
            )


def test_weekly_ot_keeps_hours_on_the_owning_classification():
    records = [
        _rec(id=1, approved_hours=18, clock_in_at="2026-09-16T13:00:00"),
        _rec(id=2, approved_hours=18, clock_in_at="2026-09-17T13:00:00"),
        _rec(
            id=3,
            approved_hours=8,
            clock_in_at="2026-09-18T13:00:00",
            worker_category="temp",
            classification_source="record_override",
        ),
        _rec(id=4, approved_hours=8, clock_in_at="2026-09-19T13:00:00"),
    ]
    assert weekly_ot_policy_category(records) == "w2"
    w2 = aggregate_classified_batch_lines(
        records, batch_category="w2", threshold_hours=40, ot_enabled=True
    )
    temp = aggregate_classified_batch_lines(
        records, batch_category="temp", threshold_hours=40, ot_enabled=True
    )
    assert w2[0]["approved_hours"] == 36
    assert w2[0]["ot_hours"] == 8
    assert w2[0]["session_ids"] == [1, 2, 4]
    assert temp[0]["approved_hours"] == 4
    assert temp[0]["ot_hours"] == 4
    assert temp[0]["session_ids"] == [3]
    disappeared = split_hours_for_overtime(44, threshold=40, enabled=True)
    assert (w2[0]["approved_hours"], w2[0]["ot_hours"]) != (
        float(disappeared[0]),
        float(disappeared[1]),
    )


def test_single_category_ot_totals_match_existing_split():
    records = [
        _rec(id=1, approved_hours=15, clock_in_at="2026-09-14T13:00:00"),
        _rec(id=2, approved_hours=15, clock_in_at="2026-09-15T13:00:00"),
        _rec(id=3, approved_hours=15, clock_in_at="2026-09-16T13:00:00"),
    ]
    lines = aggregate_classified_batch_lines(
        records, batch_category="w2", threshold_hours=40, ot_enabled=True
    )
    regular, ot = split_hours_for_overtime(45, threshold=40, enabled=True)
    assert lines[0]["approved_hours"] == float(regular)
    assert lines[0]["ot_hours"] == float(ot)
    assert all(item["classification_source"] == "profile" for item in lines[0]["classification_provenance"])
