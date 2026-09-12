"""Performance / query-budget tests for Rinse dashboard snapshot reads."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from backend.rinse_performance_approvals import APPROVALS_TABLE, upsert_approved_snapshot
from backend.rinse_dashboard_performance import (
    assert_no_live_management_imports,
    build_employee_role_history,
    build_employees_list,
    build_role_leaderboard,
    clear_benchmark_cache,
    explain_leaderboard_sql,
    last_query_count,
    last_perf,
    payload_bytes,
)
from backend.rinse_performance_folder_publisher import session_card_to_snapshot
from backend.rinse_performance_roles import ROLE_FOLDER, ROLE_SORT
from backend import rinse_dashboard_performance as rdp


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
        "orders": [{"bag_id": "A1"}],
    }
    base.update(overrides)
    return base


class SnapshotCursor:
    """In-memory approval store that understands set-based read SQL."""

    def __init__(self):
        self.rows: list[dict] = []
        self.settings = {"rinse_folding_lbs_per_hour_target": "40"}
        self.query_count = 0
        self.statements: list[str] = []
        self._last = []
        self._rinse_qcount = 0

    def execute(self, sql, params=None):
        self.query_count += 1
        self._rinse_qcount += 1
        s = " ".join(str(sql).lower().split())
        self.statements.append(s[:300])
        params = params or ()

        if "create table" in s or "alter table" in s:
            self._last = []
            return
        if "information_schema" in s:
            self._last = [{"cnt": 1}]
            return
        if "from system_settings" in s:
            key = params[1] if len(params) > 1 else None
            val = self.settings.get(str(key))
            self._last = [{"svalue": val}] if val is not None else []
            return
        if "insert into system_settings" in s:
            self.settings[str(params[1])] = str(params[2])
            self._last = []
            return
        if "insert into rinse_performance_approval_events" in s:
            self._last = []
            return
        if "insert into rinse_performance_session_approvals" in s:
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
            # upsert by org/role/session
            self.rows = [
                r
                for r in self.rows
                if not (
                    int(r["organization_id"]) == int(org)
                    and r["role_key"] == str(rk).upper()
                    and r["session_id"] == str(sid)
                )
            ]
            self.rows.append(
                {
                    "id": len(self.rows) + 1,
                    "organization_id": int(org),
                    "business_date_et": biz,
                    "role_key": str(rk).upper(),
                    "session_id": str(sid),
                    "segment_id": seg,
                    "employee_user_id": uid,
                    "employee_name": name,
                    "metric_key": mk,
                    "metric_unit": mu,
                    "published_numerator": float(num),
                    "published_denominator": float(den),
                    "published_metric_value": float(metric),
                    "published_quantity": qty,
                    "published_duration_hours": dur,
                    "published_session_start_et": start,
                    "published_session_end_et": end,
                    "approved_by": approved_by,
                    "content_fingerprint": fp,
                    "invalidated_at": None,
                    "approved_at": datetime(2026, 9, 10, 12, 0, 0),
                }
            )
            self._last = []
            return

        if "update rinse_performance_session_approvals" in s and "invalidated_at" in s:
            reason = params[0]
            org = int(params[1])
            rk = str(params[2]).upper()
            for r in self.rows:
                if int(r["organization_id"]) != org or r["role_key"] != rk:
                    continue
                if r.get("invalidated_at") is not None:
                    continue
                if "session_id in" in s:
                    sids = {str(x) for x in params[3:]}
                    if str(r["session_id"]) not in sids:
                        continue
                r["invalidated_at"] = datetime(2026, 9, 10, 13, 0, 0)
                r["invalidated_reason"] = reason
            self._last = []
            return

        # Active SELECT helper
        def active(org, role=None, week_start=None, week_end=None, uid=None, name=None, roles=None):
            out = []
            for r in self.rows:
                if int(r["organization_id"]) != int(org):
                    continue
                if r.get("invalidated_at") is not None:
                    continue
                if role and r["role_key"] != str(role).upper():
                    continue
                if roles and r["role_key"] not in {str(x).upper() for x in roles}:
                    continue
                biz = r["business_date_et"]
                if week_start is not None and biz < week_start:
                    continue
                if week_end is not None and biz > week_end:
                    continue
                if uid is not None and int(r.get("employee_user_id") or -1) != int(uid):
                    continue
                if name is not None and str(r.get("employee_name") or "") != str(name):
                    continue
                out.append(dict(r))
            return out

        # Leaderboard GROUP BY
        if "sum(published_numerator)" in s and "group by employee_user_id, employee_name" in s and "role_key =" in s:
            org, rk, ws, we = params
            rows = active(org, role=rk, week_start=ws, week_end=we)
            grouped = {}
            for r in rows:
                key = (r.get("employee_user_id"), r.get("employee_name"))
                g = grouped.setdefault(
                    key,
                    {
                        "employee_user_id": r.get("employee_user_id"),
                        "employee_name": r.get("employee_name"),
                        "sum_num": 0.0,
                        "sum_den": 0.0,
                        "session_count": 0,
                    },
                )
                g["sum_num"] += float(r["published_numerator"])
                g["sum_den"] += float(r["published_denominator"])
                g["session_count"] += 1
            self._last = list(grouped.values())
            return

        # Week aggregate for one employee+role
        if "group by employee_name, employee_user_id" in s:
            org, rk, ws, we, emp = params
            if "employee_user_id" in s:
                rows = active(org, role=rk, week_start=ws, week_end=we, uid=emp)
            else:
                rows = active(org, role=rk, week_start=ws, week_end=we, name=emp)
            if not rows:
                self._last = []
                return
            self._last = [
                {
                    "employee_name": rows[0]["employee_name"],
                    "employee_user_id": rows[0]["employee_user_id"],
                    "sum_num": sum(float(r["published_numerator"]) for r in rows),
                    "sum_den": sum(float(r["published_denominator"]) for r in rows),
                    "session_count": len(rows),
                }
            ]
            return

        # Employee detail / employees: GROUP BY role_key (+ optional employee filter)
        if "sum(published_numerator)" in s and "group by role_key" in s:
            org = int(params[0])
            ws = params[1]
            we = params[2]
            idx = 3
            roles = None
            uid = None
            name = None
            if "role_key in" in s:
                # count placeholders roughly from remaining until employee filter
                # params: org, ws, we, *roles, [uid|name]
                n_roles = s.count("%s") - 3  # rough; refine below
                # Better parse: if employee_user_id at end
                if "employee_user_id=%s" in s or "employee_user_id = %s" in s:
                    uid = params[-1]
                    roles = list(params[3:-1])
                elif "employee_name=%s" in s or "employee_name = %s" in s:
                    name = params[-1]
                    roles = list(params[3:-1])
                else:
                    roles = list(params[3:])
            rows = active(org, week_start=ws, week_end=we, uid=uid, name=name, roles=roles)
            grouped = {}
            for r in rows:
                key = (r.get("role_key"), r.get("employee_user_id"), r.get("employee_name"))
                g = grouped.setdefault(
                    key,
                    {
                        "role_key": r.get("role_key"),
                        "employee_user_id": r.get("employee_user_id"),
                        "employee_name": r.get("employee_name"),
                        "sum_num": 0.0,
                        "sum_den": 0.0,
                        "session_count": 0,
                    },
                )
                g["sum_num"] += float(r["published_numerator"])
                g["sum_den"] += float(r["published_denominator"])
                g["session_count"] += 1
            self._last = list(grouped.values())
            return

        # Last N
        if "order by business_date_et desc" in s and "limit %s" in s:
            org, rk, emp, lim = params
            if "employee_user_id" in s:
                rows = active(org, role=rk, uid=emp)
            else:
                rows = active(org, role=rk, name=emp)
            rows.sort(
                key=lambda r: (
                    str(r.get("business_date_et")),
                    str(r.get("published_session_start_et") or ""),
                    int(r.get("id") or 0),
                ),
                reverse=True,
            )
            self._last = rows[: int(lim)]
            return

        # Employee detail cross-role with employee filter
        if "group by role_key, employee_user_id, employee_name" in s or (
            "sum(published_numerator)" in s and "employee_user_id=%s" in s and "group by role_key" in s
        ):
            # handled above for multi-role; fallback
            self._last = []
            return

        if "select *" in s and "from rinse_performance_session_approvals" in s:
            org = int(params[0])
            self._last = [dict(r) for r in self.rows if int(r["organization_id"]) == org and r.get("invalidated_at") is None]
            return

        self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last or [])


@pytest.fixture(autouse=True)
def _reset_module_state():
    rdp._TABLES_READY = True  # skip DDL noise in unit tests
    clear_benchmark_cache()
    yield
    clear_benchmark_cache()
    rdp._TABLES_READY = False


def _seed(cursor: SnapshotCursor, n_employees=20, sessions_per=5):
    with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
        for e in range(n_employees):
            for s in range(sessions_per):
                d = DAY - timedelta(days=s)
                sess = _closed_session(
                    session_id=f"WF-{e}-{s}",
                    employee=f"Emp{e}",
                    user_id=1000 + e,
                    total_pre_lbs=80 + e,
                    performance_hours=2.0,
                    lbs_per_hour=(80 + e) / 2.0,
                    start_time=f"{d.isoformat()}T08:00:00",
                    end_time=f"{d.isoformat()}T10:00:00",
                )
                snap = session_card_to_snapshot(sess, business_date_et=d)
                upsert_approved_snapshot(cursor, 3, role_key=ROLE_FOLDER, snapshot=snap)


class TestSnapshotOnlyGuard:
    def test_module_does_not_import_live_builder(self):
        assert_no_live_management_imports()

    def test_leaderboard_never_calls_live_builder(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=3, sessions_per=2)
        with patch(
            "backend.management_wf_folder_performance.build_day_folder_performance"
        ) as live, patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ), patch("backend.rinse_performance_approvals.table_exists", return_value=True):
            week_start = DAY - timedelta(days=DAY.weekday())
            build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            live.assert_not_called()


class TestQueryBudgets:
    def test_leaderboard_query_ceiling(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=30, sessions_per=7)
        with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
            "backend.rinse_performance_approvals.table_exists", return_value=True
        ):
            week_start = DAY - timedelta(days=DAY.weekday())
            # warm benchmark cache first call
            clear_benchmark_cache()
            p1 = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            assert p1["query_count"] <= 5
            # second call should be ≤3 (GROUP BY + maybe cached bench = 1)
            before = cur.query_count
            p2 = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            q2 = cur.query_count - before
            assert q2 <= 3
            assert p2["query_count"] <= 3
            assert p2["team_weekly_avg"] is not None
            assert last_query_count() <= 3

    def test_employees_query_ceiling(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=25, sessions_per=4)
        with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
            "backend.rinse_performance_approvals.table_exists", return_value=True
        ):
            clear_benchmark_cache()
            week_start = DAY - timedelta(days=DAY.weekday())
            payload = build_employees_list(cur, 3, week_start=week_start)
            assert payload["query_count"] <= 5
            assert len(payload["employees"]) == 25

    def test_last_n_uses_limit_not_full_history(self):
        cur = SnapshotCursor()
        # 40 historical sessions for one employee
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ):
            for i in range(40):
                d = DAY - timedelta(days=i)
                sess = _closed_session(
                    session_id=f"WF-hist-{i}",
                    user_id=42,
                    employee="Jennifer",
                    start_time=f"{d.isoformat()}T08:00:00",
                )
                upsert_approved_snapshot(
                    cur,
                    3,
                    role_key=ROLE_FOLDER,
                    snapshot=session_card_to_snapshot(sess, business_date_et=d),
                )
            clear_benchmark_cache()
            hist = build_employee_role_history(
                cur,
                3,
                employee_id="42",
                role_key=ROLE_FOLDER,
                week_start=DAY - timedelta(days=DAY.weekday()),
                last_n=5,
            )
            assert len(hist["sessions"]) == 5
            assert hist["query_count"] <= 4
            # Must be LIMIT-bounded (ORDER BY … DESC LIMIT N) — not a full history pull
            stmts = " ".join(hist["perf"]["statements"]).lower()
            assert "limit" in stmts or "order by business_date_et desc" in stmts
            assert hist["query_count"] <= 4

    def test_no_n_plus_one_statements(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=15, sessions_per=3)
        with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
            "backend.rinse_performance_approvals.table_exists", return_value=True
        ):
            clear_benchmark_cache()
            week_start = DAY - timedelta(days=DAY.weekday())
            before = cur.query_count
            build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            q = cur.query_count - before
            # Must not scale with employee count
            assert q < 15
            assert q <= 5


class TestWeightedAggregation:
    def test_sql_group_by_weighted(self):
        cur = SnapshotCursor()
        with patch("backend.rinse_performance_approvals.table_exists", return_value=True), patch(
            "backend.rinse_folding_settings.table_exists", return_value=True
        ):
            for sess in (
                _closed_session(session_id="WF-1", total_pre_lbs=80, performance_hours=2, lbs_per_hour=40),
                _closed_session(session_id="WF-2", total_pre_lbs=60, performance_hours=1, lbs_per_hour=60),
            ):
                upsert_approved_snapshot(
                    cur,
                    3,
                    role_key=ROLE_FOLDER,
                    snapshot=session_card_to_snapshot(sess, business_date_et=DAY),
                )
            clear_benchmark_cache()
            week_start = DAY - timedelta(days=DAY.weekday())
            payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            assert payload["team_weekly_avg"] == 46.6667
            assert payload["leaderboard"][0]["weekly_avg"] == 46.6667


class TestPayloadAndLoad:
    def test_leaderboard_payload_compact(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=10, sessions_per=3)
        with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
            "backend.rinse_performance_approvals.table_exists", return_value=True
        ):
            clear_benchmark_cache()
            week_start = DAY - timedelta(days=DAY.weekday())
            payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=week_start)
            size = payload_bytes(payload)
            # Compact: no session arrays in leaderboard
            assert "sessions" not in str(payload["leaderboard"][0]) or isinstance(
                payload["leaderboard"][0]["sessions"], int
            )
            assert size < 50_000
            assert "orders" not in json_blob(payload)

    def test_concurrent_reads(self):
        cur = SnapshotCursor()
        _seed(cur, n_employees=20, sessions_per=5)
        week_start = DAY - timedelta(days=DAY.weekday())

        def one(_i):
            # each thread gets own cursor view of same data via shared rows list
            c = SnapshotCursor()
            c.rows = list(cur.rows)
            c.settings = dict(cur.settings)
            with patch("backend.rinse_folding_settings.table_exists", return_value=True), patch(
                "backend.rinse_performance_approvals.table_exists", return_value=True
            ):
                clear_benchmark_cache()
                t0 = time.perf_counter()
                p = build_role_leaderboard(c, 3, role_key=ROLE_FOLDER, week_start=week_start)
                ms = (time.perf_counter() - t0) * 1000
                return p["query_count"], ms, p["approved_session_count"]

        times = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = [pool.submit(one, i) for i in range(10)]
            for f in as_completed(futs):
                q, ms, _ = f.result()
                assert q <= 5
                times.append(ms)
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95) - 1]
        # In-memory should be well under production ceilings
        assert p50 < 300
        assert p95 < 500
        assert max(times) < 1000


def json_blob(payload):
    import json

    return json.dumps(payload, default=str)


class TestExplainShape:
    def test_leaderboard_sql_is_set_based(self):
        sql = explain_leaderboard_sql().lower()
        assert "group by" in sql
        assert "sum(published_numerator)" in sql
        assert "invalidated_at is null" in sql
        assert "organization_id" in sql
        assert "business_date_et" in sql
        # No SELECT * of sessions for aggregation path
        assert "select *" not in sql.replace("explain", "")


class TestDisabledRole:
    def test_sort_unavailable(self):
        cur = SnapshotCursor()
        payload = build_role_leaderboard(cur, 3, role_key=ROLE_SORT)
        assert payload.get("error") == "role_not_available"
        assert payload.get("query_count", 0) == 0
