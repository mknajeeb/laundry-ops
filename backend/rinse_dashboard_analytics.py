"""Period-aware Rinse Performance analytics — publication cache only.

Uses the same weighted Σ pounds / Σ hours invariants as week boards.
Recent Sessions are diagnostic (approvals ORDER BY … LIMIT 3) and never
feed Published period / team / employee metrics.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from backend.business_time import business_today
from backend.rinse_dashboard_period import (
    RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS,
    compute_delta,
    resolve_period_and_compare,
)
from backend.rinse_dashboard_performance import (
    _employee_id_from_agg,
    _ensure_tables_once,
    _metric_value_for_row,
    _parse_employee_id,
    _rate,
    _record_perf,
    get_folder_benchmark_cached,
    wrap_cursor,
)
from backend.rinse_performance_approvals import APPROVALS_TABLE
from backend.rinse_performance_roles import (
    ROLE_FOLDER,
    all_roles_public,
    get_role,
    rinse_visible_roles,
    role_is_publishable,
)

_UNIT_MAP = {
    "lbs_hr": "lb/hr",
    "bags_hr": "bags/hr",
    "pounds": "lb",
    "bags": "bags",
    "hours": "hr",
}
_LABEL_MAP = {
    "lbs_hr": "Folding Speed",
    "bags_hr": "Bags/hr",
    "pounds": "Pounds",
    "bags": "Bags / Orders",
    "hours": "Hours",
}

_RANGE_TEAM_SQL = """
SELECT
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  SUM(orders_completed) AS sum_bags,
  SUM(total_pre_lbs) AS sum_lbs,
  SUM(COALESCE(performance_hours, 0)) AS sum_hours,
  COUNT(*) AS employee_day_count,
  COUNT(DISTINCT CONCAT(employee_user_id, ':', employee_name)) AS employee_count
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND dashboard_rankable = 1
  AND business_date_et >= %s
  AND business_date_et <= %s
"""

_RANGE_DAILY_SQL = """
SELECT
  business_date_et AS d,
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  SUM(orders_completed) AS sum_bags,
  SUM(total_pre_lbs) AS sum_lbs,
  SUM(COALESCE(performance_hours, 0)) AS sum_hours,
  COUNT(*) AS employee_day_count
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND dashboard_rankable = 1
  AND business_date_et >= %s
  AND business_date_et <= %s
GROUP BY business_date_et
ORDER BY business_date_et ASC
"""

_RANGE_EMP_SQL = """
SELECT
  employee_user_id,
  employee_name,
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  SUM(orders_completed) AS sum_bags,
  SUM(total_pre_lbs) AS sum_lbs,
  SUM(COALESCE(performance_hours, 0)) AS sum_hours,
  COUNT(*) AS employee_day_count,
  SUM(included_session_count) AS session_count
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND dashboard_rankable = 1
  AND business_date_et >= %s
  AND business_date_et <= %s
GROUP BY employee_user_id, employee_name
"""

_EMP_DAYS_RANGE_SQL = """
SELECT
  business_date_et,
  employee_user_id,
  employee_name,
  orders_completed,
  total_pre_lbs,
  performance_hours,
  published_numerator,
  published_denominator,
  published_metric_value,
  included_session_count,
  session_count,
  day_publication_status,
  dashboard_rankable,
  sessions_json
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND business_date_et >= %s
  AND business_date_et <= %s
  AND {emp_clause}
ORDER BY business_date_et ASC
"""

_RECENT_SESSIONS_SQL = """
SELECT
  session_id,
  business_date_et,
  role_key,
  employee_user_id,
  employee_name,
  published_numerator,
  published_denominator,
  published_metric_value,
  published_quantity,
  published_duration_hours,
  published_session_start_et,
  published_session_end_et,
  excluded_at,
  invalidated_at
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND invalidated_at IS NULL
  AND excluded_at IS NULL
  AND business_date_et >= %s
  AND {emp_clause}
ORDER BY
  COALESCE(published_session_end_et, published_session_start_et, business_date_et) DESC,
  id DESC
LIMIT %s
"""

_DAY_EMPLOYEES_SQL = """
SELECT
  employee_user_id,
  employee_name,
  orders_completed,
  total_pre_lbs,
  performance_hours,
  published_numerator,
  published_denominator,
  published_metric_value,
  included_session_count,
  session_count,
  day_publication_status,
  dashboard_rankable,
  sessions_json
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND business_date_et = %s
ORDER BY
  CASE WHEN dashboard_rankable = 1 THEN 0 ELSE 1 END,
  employee_name ASC
"""


def _agg_totals(row: dict[str, Any] | None, metric_key: str) -> dict[str, Any]:
    r = row or {}
    num = float(r.get("sum_num") or 0)
    den = float(r.get("sum_den") or 0)
    bags = int(r.get("sum_bags") or 0)
    lbs = float(r.get("sum_lbs") or 0)
    hours = float(r.get("sum_hours") or 0)
    days = int(r.get("employee_day_count") or 0)
    employees = int(r.get("employee_count") or 0)
    avg = _rate(num, den)
    metric = _metric_value_for_row(
        metric=metric_key,
        sum_lbs=lbs,
        sum_hours=hours,
        sum_bags=bags,
        weekly_avg=avg,
    )
    return {
        "team_avg": avg,
        "metric_value": metric,
        "approved_employee_days": days,
        "employees": employees,
        "included_hours": round(hours, 4) if hours else 0.0,
        "included_pounds": round(lbs, 2),
        "included_bags": bags,
        "sum_num": num,
        "sum_den": den,
    }


def _kpi_block(totals: dict[str, Any], prior: dict[str, Any] | None, bench: float | None, metric_key: str) -> dict[str, Any]:
    prior = prior or {}
    vs_target = None
    if (
        metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
        and totals.get("metric_value") is not None
        and bench is not None
    ):
        vs_target = round(float(totals["metric_value"]) - float(bench), 4)
    return {
        "team_average": totals.get("metric_value") if metric_key.startswith("lbs") or metric_key in {"lbs_hr", "folding_speed", "bags_hr"} else totals.get("metric_value"),
        "team_avg_lbs_hr": totals.get("team_avg"),
        "metric_value": totals.get("metric_value"),
        "benchmark": bench,
        "vs_target": vs_target,
        "approved_employee_days": totals.get("approved_employee_days"),
        "employees": totals.get("employees"),
        "included_hours": totals.get("included_hours"),
        "included_pounds": totals.get("included_pounds"),
        "included_bags": totals.get("included_bags"),
        "deltas": {
            "metric": compute_delta(totals.get("metric_value"), prior.get("metric_value")),
            "approved_employee_days": compute_delta(
                totals.get("approved_employee_days"), prior.get("approved_employee_days")
            ),
            "included_hours": compute_delta(totals.get("included_hours"), prior.get("included_hours")),
            "included_pounds": compute_delta(totals.get("included_pounds"), prior.get("included_pounds")),
            "included_bags": compute_delta(totals.get("included_bags"), prior.get("included_bags")),
        },
    }


def _fetch_team_totals(cur, table: str, oid: int, role_key: str, start: date, end: date, metric_key: str) -> dict[str, Any]:
    cur.execute(
        _RANGE_TEAM_SQL.format(table=table),
        (oid, role_key, start, end),
    )
    row = cur.fetchone()
    return _agg_totals(dict(row) if row else {}, metric_key)


def _fetch_daily_series(cur, table: str, oid: int, role_key: str, start: date, end: date, metric_key: str) -> list[dict[str, Any]]:
    cur.execute(
        _RANGE_DAILY_SQL.format(table=table),
        (oid, role_key, start, end),
    )
    by_date: dict[str, dict[str, Any]] = {}
    for raw in cur.fetchall() or []:
        r = dict(raw)
        d = r.get("d")
        date_s = d.isoformat() if hasattr(d, "isoformat") else str(d or "")
        totals = _agg_totals(
            {
                "sum_num": r.get("sum_num"),
                "sum_den": r.get("sum_den"),
                "sum_bags": r.get("sum_bags"),
                "sum_lbs": r.get("sum_lbs"),
                "sum_hours": r.get("sum_hours"),
                "employee_day_count": r.get("employee_day_count"),
            },
            metric_key,
        )
        by_date[date_s] = {
            "date": date_s,
            "metric_value": totals["metric_value"],
            "hours": totals["included_hours"],
            "pounds": totals["included_pounds"],
            "bags": totals["included_bags"],
            "approved_employee_days": totals["approved_employee_days"],
        }
    out: list[dict[str, Any]] = []
    cur_d = start
    while cur_d <= end:
        key = cur_d.isoformat()
        out.append(
            by_date.get(
                key,
                {
                    "date": key,
                    "metric_value": None,
                    "hours": 0,
                    "pounds": 0,
                    "bags": 0,
                    "approved_employee_days": 0,
                },
            )
        )
        cur_d += timedelta(days=1)
    return out


def _fetch_employee_rows(
    cur, table: str, oid: int, role_key: str, start: date, end: date, metric_key: str, bench: float | None
) -> list[dict[str, Any]]:
    cur.execute(
        _RANGE_EMP_SQL.format(table=table),
        (oid, role_key, start, end),
    )
    rows = []
    for raw in cur.fetchall() or []:
        r = dict(raw)
        num = float(r.get("sum_num") or 0)
        den = float(r.get("sum_den") or 0)
        bags = int(r.get("sum_bags") or 0)
        lbs = float(r.get("sum_lbs") or 0)
        hours = float(r.get("sum_hours") or 0)
        avg = _rate(num, den)
        selected = _metric_value_for_row(
            metric=metric_key, sum_lbs=lbs, sum_hours=hours, sum_bags=bags, weekly_avg=avg
        )
        vs = None
        if (
            metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
            and selected is not None
            and bench is not None
        ):
            vs = round(float(selected) - float(bench), 4)
        rows.append(
            {
                "employee_id": _employee_id_from_agg(r.get("employee_user_id"), r.get("employee_name")),
                "employee_user_id": r.get("employee_user_id"),
                "name": r.get("employee_name"),
                "metric_value": selected,
                "weekly_avg": avg,
                "vs_target": vs,
                "vs_benchmark": vs,
                "employee_days": int(r.get("employee_day_count") or 0),
                "days": int(r.get("employee_day_count") or 0),
                "sessions": int(r.get("session_count") or 0),
                "hours": round(hours, 4) if hours else None,
                "pounds": round(lbs, 2),
                "bags": bags,
            }
        )
    rows.sort(
        key=lambda e: (
            -(e["metric_value"] if e.get("metric_value") is not None else -1e18),
            str(e.get("name") or "").casefold(),
        )
    )
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def build_performance_overview(
    cursor,
    organization_id: int,
    *,
    role_key: str = ROLE_FOLDER,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    compare: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk}
    windows = resolve_period_and_compare(
        period=period, start=start, end=end, week_start=week_start, compare=compare
    )
    current = windows["current"]
    baseline = windows["compare"]
    metric_key = str(metric or "lbs_hr").lower()
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    oid = int(organization_id)
    table = DAY_PUBLICATIONS_TABLE
    bench = get_folder_benchmark_cached(cur, oid) if rk == ROLE_FOLDER else None

    cur_totals = _fetch_team_totals(cur, table, oid, rk, current["start"], current["end"], metric_key)
    prior_totals = None
    compare_series = None
    if baseline is not None:
        prior_totals = _fetch_team_totals(
            cur, table, oid, rk, baseline["start"], baseline["end"], metric_key
        )
        compare_series = _fetch_daily_series(
            cur, table, oid, rk, baseline["start"], baseline["end"], metric_key
        )

    daily_series = _fetch_daily_series(cur, table, oid, rk, current["start"], current["end"], metric_key)
    snapshot = _fetch_employee_rows(
        cur, table, oid, rk, current["start"], current["end"], metric_key, bench
    )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "view": "overview",
        "role_key": rk,
        "metric_key": metric_key,
        "metric_label": _LABEL_MAP.get(metric_key, "Metric"),
        "unit": _UNIT_MAP.get(metric_key, ""),
        "performance_unit": "employee_day",
        "eligibility_rule": "dashboard_rankable",
        "period": {
            "key": current["key"],
            "label": current["label"],
            "start_et": current["start_et"],
            "end_et": current["end_et"],
            "day_count": current["day_count"],
        },
        "compare": (
            {
                "key": baseline["key"],
                "label": baseline["label"],
                "start_et": baseline["start_et"],
                "end_et": baseline["end_et"],
                "day_count": baseline["day_count"],
            }
            if baseline
            else None
        ),
        "kpis": _kpi_block(cur_totals, prior_totals, bench, metric_key),
        "daily_series": daily_series,
        "compare_daily_series": compare_series,
        "employee_snapshot": snapshot,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms, "statements": list(cur.statements)},
    }
    _record_perf(endpoint="overview", query_count=q, wall_ms=wall_ms)
    return payload


def build_roles_summary(
    cursor,
    organization_id: int,
    *,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    compare: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """Multi-role table scaffolding. Live data for publishable roles only."""
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    windows = resolve_period_and_compare(
        period=period, start=start, end=end, week_start=week_start, compare=compare
    )
    current = windows["current"]
    baseline = windows["compare"]
    metric_key = str(metric or "lbs_hr").lower()
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    oid = int(organization_id)
    table = DAY_PUBLICATIONS_TABLE
    folder_bench = get_folder_benchmark_cached(cur, oid)

    roles_out: list[dict[str, Any]] = []
    for role in all_roles_public():
        rk = role["role_key"]
        enabled = bool(role.get("enabled") and role.get("has_publisher") and role.get("rinse_visible"))
        if not enabled:
            roles_out.append(
                {
                    "role_key": rk,
                    "display_name": role["display_name"],
                    "enabled": False,
                    "metric_value": None,
                    "vs_target": None,
                    "employee_days": 0,
                    "employees": 0,
                    "hours": None,
                    "pounds": None,
                    "bags": None,
                    "trend": None,
                    "benchmark": None,
                    "note": "publisher_not_live",
                }
            )
            continue
        bench = folder_bench if rk == ROLE_FOLDER else None
        totals = _fetch_team_totals(cur, table, oid, rk, current["start"], current["end"], metric_key)
        prior = None
        if baseline is not None:
            prior = _fetch_team_totals(
                cur, table, oid, rk, baseline["start"], baseline["end"], metric_key
            )
        series = _fetch_daily_series(cur, table, oid, rk, current["start"], current["end"], metric_key)
        metric_delta = compute_delta(
            totals.get("metric_value"), (prior or {}).get("metric_value")
        )
        trend = None
        if metric_delta.get("absolute") is not None:
            if metric_delta["absolute"] > 0:
                trend = "up"
            elif metric_delta["absolute"] < 0:
                trend = "down"
            else:
                trend = "flat"
        vs = None
        if (
            metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
            and totals.get("metric_value") is not None
            and bench is not None
        ):
            vs = round(float(totals["metric_value"]) - float(bench), 4)
        roles_out.append(
            {
                "role_key": rk,
                "display_name": role["display_name"],
                "enabled": True,
                "metric_value": totals.get("metric_value"),
                "vs_target": vs,
                "employee_days": totals.get("approved_employee_days"),
                "employees": totals.get("employees"),
                "hours": totals.get("included_hours"),
                "pounds": totals.get("included_pounds"),
                "bags": totals.get("included_bags"),
                "trend": trend,
                "benchmark": bench,
                "deltas": metric_delta,
                "daily_series": series,
            }
        )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "view": "by_role",
        "metric_key": metric_key,
        "metric_label": _LABEL_MAP.get(metric_key, "Metric"),
        "unit": _UNIT_MAP.get(metric_key, ""),
        "period": {
            "key": current["key"],
            "label": current["label"],
            "start_et": current["start_et"],
            "end_et": current["end_et"],
        },
        "compare": (
            {
                "key": baseline["key"],
                "label": baseline["label"],
                "start_et": baseline["start_et"],
                "end_et": baseline["end_et"],
            }
            if baseline
            else None
        ),
        "roles": roles_out,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms},
    }


def build_role_period_board(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    compare: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """Period-scoped role leaderboard + daily trend (extends week board)."""
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk, "leaderboard": []}
    role = get_role(rk)
    assert role is not None
    windows = resolve_period_and_compare(
        period=period, start=start, end=end, week_start=week_start, compare=compare
    )
    current = windows["current"]
    baseline = windows["compare"]
    metric_key = str(metric or "lbs_hr").lower()
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    oid = int(organization_id)
    table = DAY_PUBLICATIONS_TABLE
    bench = get_folder_benchmark_cached(cur, oid) if rk == ROLE_FOLDER else None

    cur_totals = _fetch_team_totals(cur, table, oid, rk, current["start"], current["end"], metric_key)
    prior_totals = None
    if baseline is not None:
        prior_totals = _fetch_team_totals(
            cur, table, oid, rk, baseline["start"], baseline["end"], metric_key
        )
    leaderboard = _fetch_employee_rows(
        cur, table, oid, rk, current["start"], current["end"], metric_key, bench
    )
    daily_series = _fetch_daily_series(cur, table, oid, rk, current["start"], current["end"], metric_key)
    compare_series = None
    if baseline is not None:
        compare_series = _fetch_daily_series(
            cur, table, oid, rk, baseline["start"], baseline["end"], metric_key
        )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "view": "by_role_detail",
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": metric_key,
        "metric_label": _LABEL_MAP.get(metric_key, role["metric_label"]),
        "unit": _UNIT_MAP.get(metric_key, role["unit"]),
        "performance_unit": "employee_day",
        "eligibility_rule": "dashboard_rankable",
        "benchmark": bench,
        "period": {
            "key": current["key"],
            "label": current["label"],
            "start_et": current["start_et"],
            "end_et": current["end_et"],
        },
        "compare": (
            {
                "key": baseline["key"],
                "label": baseline["label"],
                "start_et": baseline["start_et"],
                "end_et": baseline["end_et"],
            }
            if baseline
            else None
        ),
        # Compatibility aliases for existing FE
        "week_start": current["start_et"],
        "week_end": current["end_et"],
        "team_weekly_avg": cur_totals.get("team_avg"),
        "team_metric_value": cur_totals.get("metric_value"),
        "approved_employee_day_count": cur_totals.get("approved_employee_days"),
        "approved_session_count": cur_totals.get("approved_employee_days"),
        "included_hours": cur_totals.get("included_hours"),
        "included_pounds": cur_totals.get("included_pounds"),
        "included_bags": cur_totals.get("included_bags"),
        "kpis": _kpi_block(cur_totals, prior_totals, bench, metric_key),
        "leaderboard": leaderboard,
        "daily_series": daily_series,
        "compare_daily_series": compare_series,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms, "statements": list(cur.statements)},
    }


def fetch_recent_sessions_diagnostic(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    role_key: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Last N relevant sessions for diagnostic UI only.

    Set-based: ORDER BY session end/start DESC LIMIT N.
    Safety lookback (RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS) prevents unbounded
    scans — it does NOT redefine “last N” as “sessions in the last N days.”
    """
    uid, name = _parse_employee_id(employee_id)
    if uid is not None:
        emp_clause = "employee_user_id = %s"
        emp_param: Any = uid
    else:
        emp_clause = "employee_name = %s"
        emp_param = str(name or "").strip()

    floor = business_today() - timedelta(days=RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS)
    sql = _RECENT_SESSIONS_SQL.format(table=APPROVALS_TABLE, emp_clause=emp_clause)
    cursor.execute(
        sql,
        (int(organization_id), str(role_key).upper(), floor, emp_param, int(limit)),
    )
    out: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        r = dict(raw)
        d = r.get("business_date_et")
        date_s = d.isoformat() if hasattr(d, "isoformat") else str(d or "")
        hours = (
            float(r["published_duration_hours"])
            if r.get("published_duration_hours") is not None
            else None
        )
        pounds = (
            float(r["published_numerator"])
            if r.get("published_numerator") is not None
            else (
                float(r["published_quantity"])
                if r.get("published_quantity") is not None
                else None
            )
        )
        rate = (
            float(r["published_metric_value"])
            if r.get("published_metric_value") is not None
            else None
        )
        out.append(
            {
                "date": date_s,
                "session_id": r.get("session_id"),
                "session_code": r.get("session_id"),
                "role_key": r.get("role_key"),
                "pounds": round(pounds, 2) if pounds is not None else None,
                "bags": None,  # bag count not on approval row; diagnostic only
                "hours": round(hours, 4) if hours is not None else None,
                "lbs_hr": round(rate, 4) if rate is not None else None,
                "status": "APPROVED",
                "session_start_et": (
                    r["published_session_start_et"].isoformat(sep=" ")
                    if hasattr(r.get("published_session_start_et"), "isoformat")
                    else r.get("published_session_start_et")
                ),
                "session_end_et": (
                    r["published_session_end_et"].isoformat(sep=" ")
                    if hasattr(r.get("published_session_end_et"), "isoformat")
                    else r.get("published_session_end_et")
                ),
                "diagnostic_only": True,
            }
        )
    return out


def build_employee_period_history(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    role_key: str,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    compare: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """Employee period summary + employee-day trend + nested sessions + recent diagnostic."""
    import json

    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk, "employee_days": []}
    role = get_role(rk)
    assert role is not None
    windows = resolve_period_and_compare(
        period=period, start=start, end=end, week_start=week_start, compare=compare
    )
    current = windows["current"]
    baseline = windows["compare"]
    metric_key = str(metric or "lbs_hr").lower()
    uid, name = _parse_employee_id(employee_id)
    if uid is not None:
        emp_clause = "employee_user_id = %s"
        emp_param: Any = uid
    else:
        emp_clause = "employee_name = %s"
        emp_param = str(name or "").strip()

    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    oid = int(organization_id)
    table = DAY_PUBLICATIONS_TABLE
    bench = get_folder_benchmark_cached(cur, oid) if rk == ROLE_FOLDER else None

    sql = _EMP_DAYS_RANGE_SQL.format(table=table, emp_clause=emp_clause)
    cur.execute(sql, (oid, rk, current["start"], current["end"], emp_param))
    day_rows = [dict(r) for r in (cur.fetchall() or [])]

    display_name = name
    if day_rows:
        display_name = day_rows[0].get("employee_name") or display_name

    sum_num = sum_den = sum_lbs = sum_hours = 0.0
    sum_bags = published_days = 0
    employee_days: list[dict[str, Any]] = []
    for r in day_rows:
        biz = r.get("business_date_et")
        date_s = biz.isoformat() if hasattr(biz, "isoformat") else str(biz or "")
        lbs = float(r.get("total_pre_lbs") or 0)
        hours = float(r.get("performance_hours") or 0) if r.get("performance_hours") is not None else 0.0
        bags = int(r.get("orders_completed") or 0)
        day_rate = (
            float(r["published_metric_value"])
            if r.get("published_metric_value") is not None
            else _rate(lbs, hours)
        )
        metric_value = _metric_value_for_row(
            metric=metric_key, sum_lbs=lbs, sum_hours=hours, sum_bags=bags, weekly_avg=day_rate
        )
        sessions = []
        raw_json = r.get("sessions_json")
        if raw_json:
            try:
                sessions = json.loads(raw_json) if isinstance(raw_json, str) else list(raw_json)
            except Exception:
                sessions = []
        rankable = bool(int(r.get("dashboard_rankable") or 0))
        if rankable:
            published_days += 1
            sum_num += float(r.get("published_numerator") or lbs)
            sum_den += float(r.get("published_denominator") or hours)
            sum_bags += bags
            sum_lbs += lbs
            sum_hours += hours
        vs = None
        if (
            metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
            and metric_value is not None
            and bench is not None
        ):
            vs = round(float(metric_value) - float(bench), 4)
        employee_days.append(
            {
                "date": date_s,
                "metric_value": metric_value,
                "lbs_per_hour": day_rate,
                "vs_target": vs,
                "pounds": round(lbs, 2),
                "bags": bags,
                "hours": round(hours, 4) if hours else None,
                "status": r.get("day_publication_status")
                or ("APPROVED" if rankable else "NEEDS_APPROVAL"),
                "dashboard_rankable": rankable,
                "included_session_count": int(r.get("included_session_count") or 0),
                "session_count": int(r.get("session_count") or len(sessions)),
                "sessions": sessions,
            }
        )

    period_avg = _rate(sum_num, sum_den)
    period_metric = _metric_value_for_row(
        metric=metric_key,
        sum_lbs=sum_lbs,
        sum_hours=sum_hours,
        sum_bags=sum_bags,
        weekly_avg=period_avg,
    )
    vs_target = None
    if (
        metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
        and period_metric is not None
        and bench is not None
    ):
        vs_target = round(float(period_metric) - float(bench), 4)

    prior_summary = None
    if baseline is not None:
        cur.execute(sql, (oid, rk, baseline["start"], baseline["end"], emp_param))
        prior_rows = [dict(r) for r in (cur.fetchall() or [])]
        p_num = p_den = p_lbs = p_hours = 0.0
        p_bags = p_days = 0
        for r in prior_rows:
            if not bool(int(r.get("dashboard_rankable") or 0)):
                continue
            p_days += 1
            lbs = float(r.get("total_pre_lbs") or 0)
            hours = float(r.get("performance_hours") or 0) if r.get("performance_hours") is not None else 0.0
            bags = int(r.get("orders_completed") or 0)
            p_num += float(r.get("published_numerator") or lbs)
            p_den += float(r.get("published_denominator") or hours)
            p_lbs += lbs
            p_hours += hours
            p_bags += bags
        p_avg = _rate(p_num, p_den)
        prior_summary = {
            "metric_value": _metric_value_for_row(
                metric=metric_key,
                sum_lbs=p_lbs,
                sum_hours=p_hours,
                sum_bags=p_bags,
                weekly_avg=p_avg,
            ),
            "approved_employee_days": p_days,
            "included_hours": round(p_hours, 4) if p_hours else 0.0,
            "included_pounds": round(p_lbs, 2),
            "included_bags": p_bags,
        }

    # Diagnostic only — separate query; never mixed into period_avg above.
    recent = fetch_recent_sessions_diagnostic(
        cur, oid, employee_id=employee_id, role_key=rk, limit=3
    )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    cur_summary = {
        "metric_value": period_metric,
        "weekly_avg": period_avg,
        "vs_target": vs_target,
        "approved_employee_days": published_days,
        "included_hours": round(sum_hours, 4) if sum_hours else 0.0,
        "included_pounds": round(sum_lbs, 2),
        "included_bags": sum_bags,
    }
    return {
        "view": "by_employee",
        "employee_id": str(employee_id),
        "employee_user_id": uid if uid is not None else (day_rows[0].get("employee_user_id") if day_rows else None),
        "name": display_name,
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": metric_key,
        "metric_label": _LABEL_MAP.get(metric_key, role["metric_label"]),
        "unit": _UNIT_MAP.get(metric_key, role["unit"]),
        "benchmark": bench,
        "period": {
            "key": current["key"],
            "label": current["label"],
            "start_et": current["start_et"],
            "end_et": current["end_et"],
        },
        "compare": (
            {
                "key": baseline["key"],
                "label": baseline["label"],
                "start_et": baseline["start_et"],
                "end_et": baseline["end_et"],
            }
            if baseline
            else None
        ),
        "summary": cur_summary,
        "prior_summary": prior_summary,
        "deltas": {
            "metric": compute_delta(
                cur_summary.get("metric_value"),
                (prior_summary or {}).get("metric_value"),
            ),
            "approved_employee_days": compute_delta(
                cur_summary.get("approved_employee_days"),
                (prior_summary or {}).get("approved_employee_days"),
            ),
            "included_hours": compute_delta(
                cur_summary.get("included_hours"),
                (prior_summary or {}).get("included_hours"),
            ),
            "included_pounds": compute_delta(
                cur_summary.get("included_pounds"),
                (prior_summary or {}).get("included_pounds"),
            ),
            "included_bags": compute_delta(
                cur_summary.get("included_bags"),
                (prior_summary or {}).get("included_bags"),
            ),
        },
        "week_start": current["start_et"],
        "week_end": current["end_et"],
        "weekly_avg": period_avg,
        "approved_employee_day_count": published_days,
        "included_bags": sum_bags,
        "included_pounds": round(sum_lbs, 2),
        "included_hours": round(sum_hours, 4) if sum_hours else 0,
        "employee_days": employee_days,
        "recent_sessions_diagnostic": recent,
        "recent_sessions_note": (
            "Diagnostic only. Last 3 relevant sessions by session time "
            f"(safety lookback {RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS} days). "
            "Never used for Published period/team metrics."
        ),
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms, "statements": list(cur.statements)},
    }


def build_daily_board(
    cursor,
    organization_id: int,
    *,
    business_date: date,
    role_key: str = ROLE_FOLDER,
    metric: str | None = None,
) -> dict[str, Any]:
    """Single business-date operational board."""
    import json

    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk}
    metric_key = str(metric or "lbs_hr").lower()
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    oid = int(organization_id)
    table = DAY_PUBLICATIONS_TABLE
    bench = get_folder_benchmark_cached(cur, oid) if rk == ROLE_FOLDER else None

    totals = _fetch_team_totals(cur, table, oid, rk, business_date, business_date, metric_key)
    cur.execute(_DAY_EMPLOYEES_SQL.format(table=table), (oid, rk, business_date))
    employees = []
    for raw in cur.fetchall() or []:
        r = dict(raw)
        lbs = float(r.get("total_pre_lbs") or 0)
        hours = float(r.get("performance_hours") or 0) if r.get("performance_hours") is not None else 0.0
        bags = int(r.get("orders_completed") or 0)
        rankable = bool(int(r.get("dashboard_rankable") or 0))
        day_rate = (
            float(r["published_metric_value"])
            if r.get("published_metric_value") is not None
            else _rate(lbs, hours)
        )
        metric_value = _metric_value_for_row(
            metric=metric_key, sum_lbs=lbs, sum_hours=hours, sum_bags=bags, weekly_avg=day_rate
        )
        vs = None
        if (
            metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
            and metric_value is not None
            and bench is not None
            and rankable
        ):
            vs = round(float(metric_value) - float(bench), 4)
        sessions = []
        raw_json = r.get("sessions_json")
        if raw_json:
            try:
                sessions = json.loads(raw_json) if isinstance(raw_json, str) else list(raw_json)
            except Exception:
                sessions = []
        employees.append(
            {
                "employee_id": _employee_id_from_agg(r.get("employee_user_id"), r.get("employee_name")),
                "name": r.get("employee_name"),
                "role_key": rk,
                "metric_value": metric_value if rankable else None,
                "vs_target": vs,
                "hours": round(hours, 4) if hours else None,
                "pounds": round(lbs, 2),
                "bags": bags,
                "status": r.get("day_publication_status")
                or ("APPROVED" if rankable else "NEEDS_APPROVAL"),
                "dashboard_rankable": rankable,
                "sessions": sessions,
            }
        )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "view": "daily",
        "business_date_et": business_date.isoformat(),
        "role_key": rk,
        "metric_key": metric_key,
        "metric_label": _LABEL_MAP.get(metric_key, "Metric"),
        "unit": _UNIT_MAP.get(metric_key, ""),
        "benchmark": bench,
        "kpis": _kpi_block(totals, None, bench, metric_key),
        "employees": employees,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms},
    }
