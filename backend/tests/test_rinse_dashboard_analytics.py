"""Period analytics: weighting, Tarannum exclusion, recent-sessions isolation, query budget."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.rinse_dashboard_analytics import (
    build_employee_period_history,
    build_performance_overview,
    build_roles_summary,
    fetch_recent_sessions_diagnostic,
)
from backend.rinse_dashboard_period import RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS
from backend.rinse_dashboard_performance import clear_benchmark_cache
from backend.rinse_performance_roles import ROLE_FOLDER


class AnalyticsCursor:
    """Minimal in-memory cursor covering period analytics SQL shapes."""

    def __init__(self):
        self.pub_rows: list[dict] = []
        self.approval_rows: list[dict] = []
        self.settings = {"rinse_folding_lbs_per_hour_target": "40"}
        self._last = []
        self._rinse_qcount = 0
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self._rinse_qcount += 1
        s = " ".join(str(sql).lower().split())
        self.statements.append(s[:400])
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

        def pubs(org, rk, start, end, *, rankable_only=True, uid=None, name=None):
            out = []
            for r in self.pub_rows:
                if int(r["organization_id"]) != int(org):
                    continue
                if r["role_key"] != str(rk).upper():
                    continue
                if rankable_only and not int(r.get("dashboard_rankable") or 0):
                    continue
                biz = r["business_date_et"]
                if biz < start or biz > end:
                    continue
                if uid is not None and int(r.get("employee_user_id") or -1) != int(uid):
                    continue
                if name is not None and str(r.get("employee_name") or "") != str(name):
                    continue
                out.append(dict(r))
            return out

        # Team totals (no GROUP BY employee)
        if (
            "from rinse_performance_employee_day_publications" in s
            and "sum(published_numerator)" in s
            and "group by" not in s
            and "dashboard_rankable = 1" in s
        ):
            org, rk, start, end = params
            rows = pubs(org, rk, start, end)
            self._last = [
                {
                    "sum_num": sum(float(r["published_numerator"]) for r in rows),
                    "sum_den": sum(float(r["published_denominator"]) for r in rows),
                    "sum_bags": sum(int(r.get("orders_completed") or 0) for r in rows),
                    "sum_lbs": sum(float(r.get("total_pre_lbs") or 0) for r in rows),
                    "sum_hours": sum(float(r.get("performance_hours") or 0) for r in rows),
                    "employee_day_count": len(rows),
                    "employee_count": len(
                        {(r.get("employee_user_id"), r.get("employee_name")) for r in rows}
                    ),
                }
            ]
            return

        # Daily series
        if (
            "from rinse_performance_employee_day_publications" in s
            and "group by business_date_et" in s
        ):
            org, rk, start, end = params
            rows = pubs(org, rk, start, end)
            by_d: dict = {}
            for r in rows:
                d = r["business_date_et"]
                g = by_d.setdefault(
                    d,
                    {
                        "d": d,
                        "sum_num": 0.0,
                        "sum_den": 0.0,
                        "sum_bags": 0,
                        "sum_lbs": 0.0,
                        "sum_hours": 0.0,
                        "employee_day_count": 0,
                    },
                )
                g["sum_num"] += float(r["published_numerator"])
                g["sum_den"] += float(r["published_denominator"])
                g["sum_bags"] += int(r.get("orders_completed") or 0)
                g["sum_lbs"] += float(r.get("total_pre_lbs") or 0)
                g["sum_hours"] += float(r.get("performance_hours") or 0)
                g["employee_day_count"] += 1
            self._last = [by_d[k] for k in sorted(by_d.keys())]
            return

        # Employee snapshot / leaderboard
        if (
            "from rinse_performance_employee_day_publications" in s
            and "group by employee_user_id, employee_name" in s
        ):
            org, rk, start, end = params
            rows = pubs(org, rk, start, end)
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
                        "sum_bags": 0,
                        "sum_lbs": 0.0,
                        "sum_hours": 0.0,
                        "employee_day_count": 0,
                        "session_count": 0,
                    },
                )
                g["sum_num"] += float(r["published_numerator"])
                g["sum_den"] += float(r["published_denominator"])
                g["sum_bags"] += int(r.get("orders_completed") or 0)
                g["sum_lbs"] += float(r.get("total_pre_lbs") or 0)
                g["sum_hours"] += float(r.get("performance_hours") or 0)
                g["employee_day_count"] += 1
                g["session_count"] += int(r.get("included_session_count") or 0)
            self._last = list(grouped.values())
            return

        # Employee day rows (history)
        if (
            "from rinse_performance_employee_day_publications" in s
            and "order by business_date_et asc" in s
        ):
            org, rk, start, end, emp = params
            if "employee_user_id" in s:
                rows = pubs(org, rk, start, end, rankable_only=False, uid=emp)
            else:
                rows = pubs(org, rk, start, end, rankable_only=False, name=emp)
            rows.sort(key=lambda r: str(r.get("business_date_et")))
            self._last = rows
            return

        # Recent sessions diagnostic
        if (
            "from rinse_performance_session_approvals" in s
            and "limit %s" in s
            and "order by" in s
        ):
            org, rk, floor, emp, lim = params
            rows = []
            for r in self.approval_rows:
                if int(r["organization_id"]) != int(org):
                    continue
                if r["role_key"] != str(rk).upper():
                    continue
                if r.get("invalidated_at") is not None or r.get("excluded_at") is not None:
                    continue
                if r["business_date_et"] < floor:
                    continue
                if "employee_user_id" in s and int(r.get("employee_user_id") or -1) != int(emp):
                    continue
                if "employee_name" in s and "employee_user_id" not in s:
                    if str(r.get("employee_name") or "") != str(emp):
                        continue
                rows.append(dict(r))
            rows.sort(
                key=lambda r: (
                    r.get("published_session_end_et")
                    or r.get("published_session_start_et")
                    or datetime.combine(r["business_date_et"], datetime.min.time()),
                    r.get("id") or 0,
                ),
                reverse=True,
            )
            self._last = rows[: int(lim)]
            return

        self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


def _pub(**kw):
    base = {
        "organization_id": 1,
        "role_key": ROLE_FOLDER,
        "business_date_et": date(2026, 9, 15),
        "employee_user_id": 10,
        "employee_name": "Jennifer",
        "orders_completed": 10,
        "total_pre_lbs": 200.0,
        "performance_hours": 4.0,
        "published_numerator": 200.0,
        "published_denominator": 4.0,
        "published_metric_value": 50.0,
        "included_session_count": 1,
        "session_count": 1,
        "day_publication_status": "APPROVED",
        "dashboard_rankable": 1,
        "sessions_json": "[]",
    }
    base.update(kw)
    return base


def _approval(**kw):
    base = {
        "id": 1,
        "organization_id": 1,
        "role_key": ROLE_FOLDER,
        "session_id": "WF-1",
        "business_date_et": date(2026, 9, 15),
        "employee_user_id": 10,
        "employee_name": "Jennifer",
        "published_numerator": 100.0,
        "published_denominator": 2.0,
        "published_metric_value": 50.0,
        "published_quantity": 100.0,
        "published_duration_hours": 2.0,
        "published_session_start_et": datetime(2026, 9, 15, 8, 0, 0),
        "published_session_end_et": datetime(2026, 9, 15, 10, 0, 0),
        "invalidated_at": None,
        "excluded_at": None,
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clear_bench():
    clear_benchmark_cache()
    yield
    clear_benchmark_cache()


def test_period_metric_is_weighted_sum_not_avg_of_day_rates():
    cur = AnalyticsCursor()
    # Day A: 100 lb / 2 hr = 50; Day B: 300 lb / 6 hr = 50 → wait need different rates
    # Day A: 100/2=50; Day B: 200/5=40; weighted = 300/7 ≈ 42.857 ≠ avg(50,40)=45
    cur.pub_rows = [
        _pub(
            business_date_et=date(2026, 9, 15),
            total_pre_lbs=100.0,
            performance_hours=2.0,
            published_numerator=100.0,
            published_denominator=2.0,
            published_metric_value=50.0,
        ),
        _pub(
            business_date_et=date(2026, 9, 16),
            total_pre_lbs=200.0,
            performance_hours=5.0,
            published_numerator=200.0,
            published_denominator=5.0,
            published_metric_value=40.0,
            orders_completed=12,
        ),
    ]
    payload = build_performance_overview(
        cur,
        1,
        period="custom",
        start=date(2026, 9, 15),
        end=date(2026, 9, 16),
        compare="none",
        metric="lbs_hr",
    )
    assert payload["kpis"]["metric_value"] == pytest.approx(300.0 / 7.0, rel=1e-4)
    assert payload["kpis"]["metric_value"] != pytest.approx(45.0)


def test_tarannum_partial_excluded_from_overview():
    cur = AnalyticsCursor()
    cur.pub_rows = [
        _pub(employee_user_id=1, employee_name="Jennifer", dashboard_rankable=1),
        _pub(
            employee_user_id=2,
            employee_name="Tarannum",
            dashboard_rankable=0,
            day_publication_status="PARTIALLY_APPROVED",
            total_pre_lbs=500.0,
            performance_hours=10.0,
            published_numerator=500.0,
            published_denominator=10.0,
        ),
    ]
    payload = build_performance_overview(
        cur,
        1,
        period="custom",
        start=date(2026, 9, 15),
        end=date(2026, 9, 15),
        compare="none",
    )
    names = [e["name"] for e in payload["employee_snapshot"]]
    assert "Jennifer" in names
    assert "Tarannum" not in names
    assert payload["kpis"]["approved_employee_days"] == 1


def test_recent_sessions_are_last_3_by_time_not_14_day_window():
    cur = AnalyticsCursor()
    # Sessions spanning > 14 days; still returns the 3 most recent
    base = date(2026, 9, 21)
    for i, days_ago in enumerate([2, 10, 40, 100]):
        d = base - timedelta(days=days_ago)
        cur.approval_rows.append(
            _approval(
                id=i + 1,
                session_id=f"WF-{i}",
                business_date_et=d,
                published_session_start_et=datetime(d.year, d.month, d.day, 8, 0, 0),
                published_session_end_et=datetime(d.year, d.month, d.day, 10, 0, 0),
                published_metric_value=40.0 + i,
            )
        )
    recent = fetch_recent_sessions_diagnostic(cur, 1, employee_id="10", role_key=ROLE_FOLDER, limit=3)
    assert len(recent) == 3
    assert [r["session_id"] for r in recent] == ["WF-0", "WF-1", "WF-2"]
    assert recent[2]["date"] == (base - timedelta(days=40)).isoformat()
    assert RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS >= 365


def test_recent_sessions_do_not_affect_period_metric():
    cur = AnalyticsCursor()
    # One published employee-day at 50 lb/hr
    cur.pub_rows = [
        _pub(
            business_date_et=date(2026, 9, 21),
            total_pre_lbs=100.0,
            performance_hours=2.0,
            published_numerator=100.0,
            published_denominator=2.0,
            published_metric_value=50.0,
        )
    ]
    # Diagnostic sessions with wild rates
    for i in range(3):
        d = date(2026, 9, 10 + i)
        cur.approval_rows.append(
            _approval(
                id=i + 1,
                session_id=f"S{i}",
                business_date_et=d,
                published_numerator=999.0,
                published_denominator=1.0,
                published_metric_value=999.0,
                published_session_end_et=datetime(d.year, d.month, d.day, 12, 0, 0),
            )
        )
    hist = build_employee_period_history(
        cur,
        1,
        employee_id="10",
        role_key=ROLE_FOLDER,
        period="custom",
        start=date(2026, 9, 21),
        end=date(2026, 9, 21),
        compare="none",
        metric="lbs_hr",
    )
    assert hist["summary"]["metric_value"] == pytest.approx(50.0)
    assert len(hist["recent_sessions_diagnostic"]) == 3
    assert all(s.get("diagnostic_only") for s in hist["recent_sessions_diagnostic"])
    # Period metric must not equal session avg
    assert hist["summary"]["metric_value"] != pytest.approx(999.0)


def test_overview_query_budget_bounded():
    cur = AnalyticsCursor()
    cur.pub_rows = [
        _pub(business_date_et=date(2026, 9, 15) + timedelta(days=i), employee_user_id=10 + (i % 3))
        for i in range(7)
    ]
    for r in cur.pub_rows:
        r["employee_name"] = f"Emp{r['employee_user_id']}"
    before = cur._rinse_qcount
    payload = build_performance_overview(
        cur,
        1,
        period="last_7_days",
        compare="previous_period",
        metric="lbs_hr",
    )
    used = cur._rinse_qcount - before
    # tables ensure + bench + team×2 + daily×2 + emp snapshot — no N+1 per employee/day
    assert used <= 12
    assert payload["query_count"] == used
    assert "employee_snapshot" in payload
    # No per-employee SELECT loops
    emp_selects = [st for st in cur.statements if "employee_user_id =" in st and "limit" not in st]
    assert len(emp_selects) == 0


def test_roles_summary_scaffolds_disabled_roles():
    cur = AnalyticsCursor()
    cur.pub_rows = [_pub()]
    payload = build_roles_summary(
        cur,
        1,
        period="custom",
        start=date(2026, 9, 15),
        end=date(2026, 9, 15),
        compare="none",
    )
    keys = {r["role_key"]: r for r in payload["roles"]}
    assert keys["FOLDER"]["enabled"] is True
    assert keys["FOLDER"]["metric_value"] is not None
    assert keys["SORT"]["enabled"] is False
    assert keys["SORT"]["note"] == "publisher_not_live"
