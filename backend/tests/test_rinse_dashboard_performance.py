"""Tests for Rinse Hub Performance Phase 1 — approvals + external projection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_performance_approvals import (
    ACTION_APPROVE,
    folder_session_fingerprint,
    get_approval_row,
    invalidate_approvals,
    list_active_approvals,
    session_is_approvable,
    unapprove_session,
    upsert_approved_snapshot,
    weighted_rate_from_rows,
    ensure_rinse_performance_approval_tables,
)
from backend.rinse_performance_folder_publisher import (
    approve_folder_day,
    approve_folder_session,
    get_folder_benchmark,
    put_folder_benchmark,
    reconcile_folder_approvals_for_day,
    session_card_to_snapshot,
)
from backend.rinse_performance_roles import (
    ROLE_FOLDER,
    ROLE_SORT,
    ROLE_WF_OPERATOR,
    get_role,
    rinse_visible_roles,
    role_is_publishable,
)
from backend.rinse_dashboard_performance import (
    build_employee_role_history,
    build_role_leaderboard,
    last_query_count,
)


DAY = date(2026, 9, 10)


def _closed_session(**overrides):
    base = {
        "session_id": "WF-100",
        "segment_id": 100,
        "employee": "Jennifer",
        "user_id": 42,
        "role_status": "closed",
        "performance_hours": 2.0,
        "total_pre_lbs": 92.0,
        "lbs_per_hour": 46.0,
        "orders_completed": 4,
        "start_time": "2026-09-10T08:00:00",
        "end_time": "2026-09-10T10:00:00",
        "performance_basis": "session_end",
        "selected_date_et": DAY.isoformat(),
        "orders": [{"bag_id": "A1"}, {"bag_id": "A2"}],
    }
    base.update(overrides)
    return base


class FakeCursor:
    """Minimal in-memory stand-in for approval table operations."""

    def __init__(self):
        self.approvals = {}
        self.events = []
        self._last = None
        self.settings = {"rinse_folding_lbs_per_hour_target": "40"}
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).lower().split())
        self.executed.append((s, params))
        params = params or ()

        if "create table" in s:
            self._last = None
            return

        if "information_schema" in s or "show tables" in s:
            self._last = [{"cnt": 1}]
            return

        if f"from rinse_performance_session_approvals" in s and "select *" in s and "session_id=%s" in s and "in (" not in s:
            # get_approval_row
            org, role, sid = params
            key = (int(org), str(role).upper(), str(sid))
            row = self.approvals.get(key)
            self._last = [row] if row else []
            return

        if "from rinse_performance_session_approvals" in s and "select session_id, invalidated_at" in s:
            org, role = params[0], params[1]
            sids = list(params[2:])
            out = []
            for sid in sids:
                row = self.approvals.get((int(org), str(role).upper(), str(sid)))
                if row:
                    out.append(row)
            self._last = out
            return

        if "insert into rinse_performance_approval_events" in s:
            self.events.append(params)
            self._last = None
            return

        if "insert into rinse_performance_session_approvals" in s:
            # upsert
            (
                org,
                biz,
                rk,
                sid,
                seg,
                uid,
                name,
                mk,
                mu,
                num,
                den,
                metric,
                qty,
                dur,
                start,
                end,
                approved_by,
                fp,
            ) = params
            key = (int(org), str(rk).upper(), str(sid))
            self.approvals[key] = {
                "id": len(self.approvals) + 1,
                "organization_id": int(org),
                "business_date_et": biz,
                "role_key": str(rk).upper(),
                "session_id": str(sid),
                "segment_id": seg,
                "employee_user_id": uid,
                "employee_name": name,
                "metric_key": mk,
                "metric_unit": mu,
                "published_numerator": num,
                "published_denominator": den,
                "published_metric_value": metric,
                "published_quantity": qty,
                "published_duration_hours": dur,
                "published_session_start_et": start,
                "published_session_end_et": end,
                "approved_by": approved_by,
                "content_fingerprint": fp,
                "invalidated_at": None,
                "invalidated_reason": None,
                "approved_at": datetime(2026, 9, 10, 12, 0, 0),
            }
            self._last = None
            return

        if "update rinse_performance_session_approvals" in s and "invalidated_at = now()" in s:
            reason = params[0]
            rest = params[1:]
            org = int(rest[0])
            rk = str(rest[1]).upper()
            # remaining filters
            for key, row in list(self.approvals.items()):
                if key[0] != org or key[1] != rk:
                    continue
                if row.get("invalidated_at") is not None:
                    continue
                match = True
                if "business_date_et=%s" in s and len(rest) >= 3 and "session_id in" not in s:
                    if row.get("business_date_et") != rest[2]:
                        match = False
                if "session_id in" in s:
                    sids = [str(x) for x in rest[2:]]
                    if str(row.get("session_id")) not in sids:
                        match = False
                if match:
                    row["invalidated_at"] = datetime(2026, 9, 10, 13, 0, 0)
                    row["invalidated_reason"] = reason
            self._last = None
            return

        if "select session_id, business_date_et, published_metric_value, content_fingerprint" in s:
            org = int(params[0])
            rk = str(params[1]).upper()
            out = []
            for key, row in self.approvals.items():
                if key[0] != org or key[1] != rk:
                    continue
                if row.get("invalidated_at") is not None:
                    continue
                if "business_date_et=%s" in s and len(params) >= 3 and "session_id in" not in s:
                    if row.get("business_date_et") != params[2]:
                        continue
                if "session_id in" in s:
                    sids = [str(x) for x in params[2:]]
                    if str(row.get("session_id")) not in sids:
                        continue
                out.append(row)
            self._last = out
            return

        if "from rinse_performance_session_approvals" in s and "invalidated_at is null" in s:
            org = int(params[0])
            out = []
            idx = 1
            role = None
            week_start = week_end = None
            uid = None
            name = None
            if "role_key=%s" in s:
                role = str(params[idx]).upper()
                idx += 1
            if "business_date_et >=" in s:
                week_start = params[idx]
                idx += 1
            if "business_date_et <=" in s:
                week_end = params[idx]
                idx += 1
            if "employee_user_id=%s" in s:
                uid = int(params[idx])
                idx += 1
            if "employee_name=%s" in s:
                name = params[idx]
                idx += 1
            for key, row in self.approvals.items():
                if key[0] != org or row.get("invalidated_at") is not None:
                    continue
                if role and key[1] != role:
                    continue
                biz = row.get("business_date_et")
                if week_start and biz < week_start:
                    continue
                if week_end and biz > week_end:
                    continue
                if uid is not None and int(row.get("employee_user_id") or -1) != uid:
                    continue
                if name is not None and str(row.get("employee_name") or "") != name:
                    continue
                out.append(dict(row))
            out.sort(key=lambda r: (str(r.get("business_date_et")), str(r.get("published_session_start_et") or ""), int(r.get("id") or 0)))
            self._last = out
            return

        if "from system_settings" in s:
            key = params[1] if len(params) > 1 else None
            val = self.settings.get(key)
            self._last = [{"svalue": val}] if val is not None else []
            return

        if "insert into system_settings" in s:
            org, key, val = params
            self.settings[str(key)] = str(val)
            self._last = None
            return

        self._last = []

    def fetchone(self):
        if not self._last:
            return None
        return self._last[0]

    def fetchall(self):
        return list(self._last or [])


@pytest.fixture
def cursor():
    cur = FakeCursor()
    # table_exists uses information_schema — make ensure create path work via patch
    with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
        yield cur


class TestRoleRegistry:
    def test_folder_publishable(self):
        assert role_is_publishable(ROLE_FOLDER)
        role = get_role(ROLE_FOLDER)
        assert role["metric_key"] == "lbs_per_hour"
        assert role["benchmark_setting_key"] == "rinse_folding_lbs_per_hour_target"

    def test_reserved_roles_not_publishable(self):
        assert not role_is_publishable(ROLE_SORT)
        assert not role_is_publishable(ROLE_WF_OPERATOR)
        assert not role_is_publishable("HD_OPERATOR")

    def test_rinse_visible_only_folder(self):
        keys = [r["role_key"] for r in rinse_visible_roles()]
        assert keys == [ROLE_FOLDER]


class TestApprovals:
    def test_open_session_cannot_approve(self):
        ok, reason = session_is_approvable(_closed_session(role_status="open"))
        assert not ok
        assert reason == "open"

    def test_unapproved_invisible(self, cursor):
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert rows == []

    def test_approve_closed_visible(self, cursor):
        sess = _closed_session()
        day = {
            "sessions": [sess],
            "employees": [{"employee": "Jennifer", "user_id": 42, "sessions": [sess]}],
        }
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_performance_folder_publisher.build_day_folder_performance",
            return_value=day,
        ):
            out = approve_folder_session(cursor, 3, selected_date_et=DAY, session_id="WF-100")
            assert out["ok"] is True
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert len(rows) == 1
        assert float(rows[0]["published_metric_value"]) == 46.0

    def test_approve_day_skips_open(self, cursor):
        closed = _closed_session(session_id="WF-1")
        opened = _closed_session(session_id="WF-2", role_status="open", performance_hours=1.0)
        empty = _closed_session(session_id="WF-3", performance_hours=0, lbs_per_hour=None, total_pre_lbs=0)
        day = {"sessions": [closed, opened, empty], "employees": []}
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_performance_folder_publisher.build_day_folder_performance",
            return_value=day,
        ):
            summary = approve_folder_day(cursor, 3, selected_date_et=DAY)
        assert summary["approved"] == 1
        assert summary["open"] == 1
        assert summary["invalid_empty"] == 1

    def test_weighted_rates(self):
        rows = [
            {"published_numerator": 80, "published_denominator": 2},  # 40
            {"published_numerator": 60, "published_denominator": 1},  # 60
        ]
        # weighted = 140/3 ≈ 46.6667 — NOT avg(40,60)=50
        assert weighted_rate_from_rows(rows) == 46.6667

    def test_invalidate_then_invisible(self, cursor):
        sess = _closed_session()
        snap = session_card_to_snapshot(sess, business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            invalidate_approvals(
                cursor, 3, role_key=ROLE_FOLDER, session_ids=["WF-100"], reason="test"
            )
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert rows == []

    def test_reapprove_publishes_corrected(self, cursor):
        sess = _closed_session()
        snap = session_card_to_snapshot(sess, business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            invalidate_approvals(
                cursor, 3, role_key=ROLE_FOLDER, session_ids=["WF-100"], reason="pre_correction"
            )
            sess2 = _closed_session(total_pre_lbs=100.0, lbs_per_hour=50.0)
            snap2 = session_card_to_snapshot(sess2, business_date_et=DAY)
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap2)
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert len(rows) == 1
        assert float(rows[0]["published_metric_value"]) == 50.0

    def test_fingerprint_change_reconcile(self, cursor):
        sess = _closed_session()
        snap = session_card_to_snapshot(sess, business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            changed = _closed_session(performance_hours=3.0, lbs_per_hour=30.6667)
            day = {"sessions": [changed], "employees": []}
            out = reconcile_folder_approvals_for_day(
                cursor, 3, selected_date_et=DAY, day=day
            )
            assert out["invalidated"] == 1
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert rows == []

    def test_benchmark_reuse_setting(self, cursor):
        with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
            "backend.rinse_performance_approvals.table_exists", return_value=True
        ):
            assert get_folder_benchmark(cursor, 3) == 40.0
            put_folder_benchmark(cursor, 3, 45.0)
            assert get_folder_benchmark(cursor, 3) == 45.0

    def test_benchmark_change_does_not_invalidate(self, cursor):
        sess = _closed_session()
        snap = session_card_to_snapshot(sess, business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ):
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            put_folder_benchmark(cursor, 3, 55.0)
            rows = list_active_approvals(cursor, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
        assert len(rows) == 1

    def test_unsupported_role_cannot_approve(self, cursor):
        snap = session_card_to_snapshot(_closed_session(), business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            with pytest.raises(ValueError):
                upsert_approved_snapshot(cursor, 3, role_key=ROLE_SORT, snapshot=snap)


class TestRinseProjection:
    def test_leaderboard_weighted_and_query_bounded(self, cursor):
        s1 = _closed_session(session_id="WF-1", total_pre_lbs=80, performance_hours=2, lbs_per_hour=40)
        s2 = _closed_session(session_id="WF-2", total_pre_lbs=60, performance_hours=1, lbs_per_hour=60)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ), patch(
            "backend.management_wf_folder_performance.build_day_folder_performance"
        ) as live:
            for sess in (s1, s2):
                upsert_approved_snapshot(
                    cursor,
                    3,
                    role_key=ROLE_FOLDER,
                    snapshot=session_card_to_snapshot(sess, business_date_et=DAY),
                )
            week_start = DAY - timedelta(days=DAY.weekday())
            payload = build_role_leaderboard(cursor, 3, role_key=ROLE_FOLDER, week_start=week_start)
            live.assert_not_called()
        assert payload["team_weekly_avg"] == 46.6667
        assert payload["leaderboard"][0]["weekly_avg"] == 46.6667
        assert payload["query_count"] <= 5
        assert last_query_count() <= 5

    def test_last_n_ignores_unapproved(self, cursor):
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ):
            for i in range(3):
                sess = _closed_session(
                    session_id=f"WF-{i}",
                    start_time=f"2026-09-0{i+1}T08:00:00",
                )
                snap = session_card_to_snapshot(sess, business_date_et=date(2026, 9, i + 1))
                upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            # unapproved fourth — never inserted
            hist = build_employee_role_history(
                cursor,
                3,
                employee_id="42",
                role_key=ROLE_FOLDER,
                week_start=date(2026, 9, 1),
                last_n=5,
            )
        assert len(hist["sessions"]) == 3

    def test_disabled_role_returns_unavailable(self, cursor):
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            payload = build_role_leaderboard(cursor, 3, role_key=ROLE_SORT)
        assert payload.get("error") == "role_not_available"

    def test_cross_org_isolation(self, cursor):
        snap = session_card_to_snapshot(_closed_session(), business_date_et=DAY)
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ):
            upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)
            week_start = DAY - timedelta(days=DAY.weekday())
            other = build_role_leaderboard(cursor, 99, role_key=ROLE_FOLDER, week_start=week_start)
        assert other["approved_session_count"] == 0
        assert other["leaderboard"] == []


class TestAuthHelpers:
    def test_rinse_dashboard_read_gate(self):
        from backend.rinse_dashboard_routes import _can_read_rinse_dashboard

        assert _can_read_rinse_dashboard({"roles": ["RINSE"]})
        assert _can_read_rinse_dashboard({"roles": ["ADMIN"]})
        assert not _can_read_rinse_dashboard({"roles": ["CHECKOUT"]})
