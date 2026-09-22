"""Rinse-safe read projections — employee-day publication cache, set-based.

HARD RULES:
- Never import or call live Management Performance builders.
- Prefer 1–3 SQL queries per endpoint (hard ceiling documented per handler).
- No N+1. No per-employee queries. No unbounded history on page load.

Published eligibility: dashboard_rankable=1 (fully APPROVED employee-days only).
Weekly rates: Σ day pounds / Σ day hours — never AVG of session or day rates.
rinse_performance_employee_day_publications is a derived cache only; metrics
come from Management compose/recompute_employee_day_metrics.
"""

from __future__ import annotations

import ast
import json
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from backend.rinse_performance_approvals import (
    APPROVALS_TABLE,
    current_et_week_start,
    et_week_bounds,
    ensure_rinse_performance_approval_tables,
)
from backend.rinse_performance_roles import (
    FOLDER_DEFAULT_BENCHMARK,
    ROLE_FOLDER,
    get_role,
    rinse_visible_roles,
    role_is_publishable,
)
from backend.rinse_folding_settings import KEY_LBS_PER_HOUR

# ---------------------------------------------------------------------------
# Process-local caches (short TTL — same pattern as shift selection tree)
# ---------------------------------------------------------------------------
_TABLES_READY = False
_TABLES_LOCK = threading.Lock()
_BENCH_CACHE: dict[int, tuple[float, float]] = {}
_BENCH_TTL_SEC = 60.0
_BENCH_LOCK = threading.Lock()

_LAST_PERF: dict[str, Any] = {}


def last_query_count() -> int:
    return int(_LAST_PERF.get("query_count") or 0)


def last_perf() -> dict[str, Any]:
    return dict(_LAST_PERF)


def _record_perf(**kwargs: Any) -> None:
    global _LAST_PERF
    _LAST_PERF = dict(kwargs)


def _ensure_tables_once(cursor) -> int:
    """At most one ensure per process lifetime (0 or 1+ DDL/info queries)."""
    global _TABLES_READY
    if _TABLES_READY:
        return 0
    with _TABLES_LOCK:
        if _TABLES_READY:
            return 0
        before = getattr(cursor, "_rinse_qcount", None)
        ensure_rinse_performance_approval_tables(cursor)
        _ensure_read_indexes(cursor)
        from backend.rinse_performance_employee_day import (
            ensure_employee_day_publication_tables,
        )

        ensure_employee_day_publication_tables(cursor)
        _TABLES_READY = True
        after = getattr(cursor, "_rinse_qcount", None)
        if before is not None and after is not None:
            return max(0, int(after) - int(before))
        return 0


def _ensure_read_indexes(cursor) -> None:
    """Idempotent index ensure for read paths (safe if already present)."""
    for name, cols in (
        (
            "idx_rinse_perf_read_role_week",
            "(organization_id, role_key, invalidated_at, business_date_et)",
        ),
        (
            "idx_rinse_perf_read_emp_hist",
            "(organization_id, role_key, employee_user_id, invalidated_at, "
            "business_date_et, published_session_start_et, id)",
        ),
    ):
        try:
            cursor.execute(
                f"ALTER TABLE {APPROVALS_TABLE} ADD KEY {name} {cols}"
            )
        except Exception:
            # Duplicate key name / already exists
            pass


class CountingCursor:
    """Thin wrapper that counts execute() calls for instrumentation/tests."""

    def __init__(self, cursor):
        self._c = cursor
        self._rinse_qcount = 0
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self._rinse_qcount += 1
        self.statements.append(" ".join(str(sql).split())[:500])
        if params is None:
            return self._c.execute(sql)
        return self._c.execute(sql, params)

    def executemany(self, sql, seq):
        self._rinse_qcount += 1
        return self._c.executemany(sql, seq)

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def __getattr__(self, name):
        return getattr(self._c, name)


def wrap_cursor(cursor) -> CountingCursor:
    if isinstance(cursor, CountingCursor):
        return cursor
    return CountingCursor(cursor)


def resolve_week(week_start: date | None) -> tuple[date, date]:
    start = week_start or current_et_week_start()
    return et_week_bounds(start)


def get_folder_benchmark_cached(cursor, organization_id: int) -> float:
    """One settings read per TTL window per org (lbs key only — not full folding bundle)."""
    org = int(organization_id)
    now = time.monotonic()
    with _BENCH_LOCK:
        hit = _BENCH_CACHE.get(org)
        if hit and (now - hit[0]) < _BENCH_TTL_SEC:
            return float(hit[1])

    value = float(FOLDER_DEFAULT_BENCHMARK)
    try:
        cursor.execute(
            "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
            (org, KEY_LBS_PER_HOUR),
        )
        row = cursor.fetchone()
        if row:
            raw = row.get("svalue") if isinstance(row, dict) else row[0]
            try:
                if raw is not None and str(raw).strip() != "":
                    value = float(str(raw).strip())
            except (TypeError, ValueError):
                value = float(FOLDER_DEFAULT_BENCHMARK)
    except Exception:
        value = float(FOLDER_DEFAULT_BENCHMARK)
    with _BENCH_LOCK:
        _BENCH_CACHE[org] = (now, value)
    return value


def clear_benchmark_cache(organization_id: int | None = None) -> None:
    with _BENCH_LOCK:
        if organization_id is None:
            _BENCH_CACHE.clear()
        else:
            _BENCH_CACHE.pop(int(organization_id), None)


def _rate(num: float, den: float) -> float | None:
    if den is None or float(den) <= 0:
        return None
    return round(float(num) / float(den), 4)


def _employee_id_from_agg(uid: Any, name: Any) -> str:
    if uid is not None:
        try:
            return str(int(uid))
        except (TypeError, ValueError):
            pass
    return f"name:{str(name or '').strip()}"


def _parse_employee_id(employee_id: str) -> tuple[int | None, str | None]:
    eid = str(employee_id or "").strip()
    if eid.startswith("name:"):
        return None, eid[5:]
    try:
        return int(eid), None
    except ValueError:
        return None, eid


# ---------------------------------------------------------------------------
# Meta (cheap — registry in-process + optional 1 benchmark read)
# ---------------------------------------------------------------------------
def build_rinse_meta(cursor, organization_id: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    cur = wrap_cursor(cursor)
    q_ensure = _ensure_tables_once(cur)
    roles = []
    for role in rinse_visible_roles():
        bench = None
        if role["role_key"] == ROLE_FOLDER:
            bench = get_folder_benchmark_cached(cur, organization_id)
        roles.append(
            {
                "role_key": role["role_key"],
                "display_name": role["display_name"],
                "metric_key": role["metric_key"],
                "metric_label": role["metric_label"],
                "unit": role["unit"],
                "benchmark": bench,
                "enabled": True,
                "rinse_visible": True,
            }
        )
    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "modules": [
            {"id": "performance", "label": "Performance", "enabled": True},
            {"id": "weekly_schedule", "label": "Weekly Schedule", "enabled": True},
            {"id": "supplies_rejects", "label": "Supplies & Rejects", "enabled": False},
            {"id": "issues", "label": "Issues", "enabled": False},
        ],
        "performance_roles": roles,
        "performance_unit": "employee_day",
        "eligibility_rule": "dashboard_rankable",
        "metrics": [
            {"key": "lbs_hr", "label": "Folding Speed", "unit": "lb/hr"},
            {"key": "bags_hr", "label": "Bags/hr", "unit": "bags/hr"},
            {"key": "pounds", "label": "Pounds", "unit": "lb"},
            {"key": "bags", "label": "Bags / Orders", "unit": "bags"},
            {"key": "hours", "label": "Hours", "unit": "hr"},
        ],
        "query_count": q,
        "perf": {"query_count": q, "ensure_queries": q_ensure, "wall_ms": wall_ms},
    }
    _record_perf(endpoint="meta", query_count=q, wall_ms=wall_ms)
    return payload




# ---------------------------------------------------------------------------
# Role leaderboard — employee-day publications (not raw approved sessions)
# ---------------------------------------------------------------------------
_DAY_LEADERBOARD_SQL = """
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


def _metric_value_for_row(
    *,
    metric: str,
    sum_lbs: float,
    sum_hours: float,
    sum_bags: int,
    weekly_avg: float | None,
) -> float | None:
    m = str(metric or "lbs_hr").lower()
    if m in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}:
        return weekly_avg
    if m in {"bags_hr", "bags_per_hour"}:
        return _rate(float(sum_bags), sum_hours)
    if m in {"pounds", "lbs", "total_pre_lbs"}:
        return round(sum_lbs, 2)
    if m in {"bags", "orders", "orders_completed"}:
        return float(sum_bags)
    if m in {"hours", "performance_hours"}:
        return round(sum_hours, 4) if sum_hours else None
    return weekly_avg


def build_role_leaderboard(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    week_start: date | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """Published weekly board from fully APPROVED employee-days only.

    Never ranks a single approved session from a partially approved day.
    Weekly rate = Σ day pounds / Σ day hours (never AVG of session rates).
    """
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {
            "error": "role_not_available",
            "role_key": rk,
            "leaderboard": [],
            "query_count": 0,
        }
    role = get_role(rk)
    assert role is not None
    start, end = resolve_week(week_start)
    metric_key = str(metric or "lbs_hr").lower()
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    sql = _DAY_LEADERBOARD_SQL.format(table=DAY_PUBLICATIONS_TABLE)
    cur.execute(sql, (int(organization_id), rk, start, end))
    rows = [dict(r) for r in (cur.fetchall() or [])]

    bench = get_folder_benchmark_cached(cur, organization_id) if rk == ROLE_FOLDER else None

    team_num = 0.0
    team_den = 0.0
    team_days = 0
    team_bags = 0
    team_lbs = 0.0
    team_hours = 0.0
    leaderboard = []
    for r in rows:
        num = float(r.get("sum_num") or 0)
        den = float(r.get("sum_den") or 0)
        day_n = int(r.get("employee_day_count") or 0)
        bags = int(r.get("sum_bags") or 0)
        lbs = float(r.get("sum_lbs") or 0)
        hours = float(r.get("sum_hours") or 0)
        avg = _rate(num, den)
        selected = _metric_value_for_row(
            metric=metric_key,
            sum_lbs=lbs,
            sum_hours=hours,
            sum_bags=bags,
            weekly_avg=avg,
        )
        if den > 0:
            team_num += num
            team_den += den
        team_days += day_n
        team_bags += bags
        team_lbs += lbs
        team_hours += hours
        vs = None
        if (
            metric_key in {"lbs_hr", "lb_hr", "folding_speed", "lbs_per_hour"}
            and selected is not None
            and bench is not None
        ):
            vs = round(float(selected) - float(bench), 4)
        leaderboard.append(
            {
                "employee_id": _employee_id_from_agg(
                    r.get("employee_user_id"), r.get("employee_name")
                ),
                "employee_user_id": r.get("employee_user_id"),
                "name": r.get("employee_name"),
                "weekly_avg": avg,
                "metric_value": selected,
                "vs_benchmark": vs,
                "vs_target": vs,
                "employee_days": day_n,
                "days": day_n,
                "sessions": int(r.get("session_count") or 0),
                "orders_completed": bags,
                "bags": bags,
                "total_pre_lbs": round(lbs, 2),
                "pounds": round(lbs, 2),
                "performance_hours": round(hours, 4) if hours else None,
                "hours": round(hours, 4) if hours else None,
            }
        )

    leaderboard.sort(
        key=lambda e: (
            -(e["metric_value"] if e.get("metric_value") is not None else -1e18),
            str(e.get("name") or "").casefold(),
        )
    )
    for i, row in enumerate(leaderboard, start=1):
        row["rank"] = i

    team_avg = _rate(team_num, team_den)
    unit_map = {
        "lbs_hr": "lb/hr",
        "bags_hr": "bags/hr",
        "pounds": "lb",
        "bags": "bags",
        "hours": "hr",
    }
    label_map = {
        "lbs_hr": "Folding Speed",
        "bags_hr": "Bags/hr",
        "pounds": "Pounds",
        "bags": "Bags / Orders",
        "hours": "Hours",
    }

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": metric_key,
        "metric_label": label_map.get(metric_key, role["metric_label"]),
        "unit": unit_map.get(metric_key, role["unit"]),
        "performance_unit": "employee_day",
        "eligibility_rule": "dashboard_rankable",
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "team_weekly_avg": team_avg,
        "team_metric_value": _metric_value_for_row(
            metric=metric_key,
            sum_lbs=team_lbs,
            sum_hours=team_hours,
            sum_bags=team_bags,
            weekly_avg=team_avg,
        ),
        "approved_employee_day_count": team_days,
        "approved_session_count": team_days,
        "included_hours": round(team_hours, 4) if team_hours else 0,
        "included_pounds": round(team_lbs, 2),
        "included_bags": team_bags,
        "leaderboard": leaderboard,
        "query_count": q,
        "perf": {
            "query_count": q,
            "wall_ms": wall_ms,
            "rows_grouped": len(rows),
            "statements": list(cur.statements),
        },
    }
    _record_perf(
        endpoint="role_leaderboard",
        query_count=q,
        wall_ms=wall_ms,
        rows=len(rows),
    )
    return payload


_EMPLOYEES_WEEK_SQL = """
SELECT
  role_key,
  employee_user_id,
  employee_name,
  SUM(CASE WHEN dashboard_rankable = 1 THEN published_numerator ELSE 0 END) AS sum_num,
  SUM(CASE WHEN dashboard_rankable = 1 THEN published_denominator ELSE 0 END) AS sum_den,
  SUM(CASE WHEN dashboard_rankable = 1 THEN orders_completed ELSE 0 END) AS sum_bags,
  SUM(CASE WHEN dashboard_rankable = 1 THEN total_pre_lbs ELSE 0 END) AS sum_lbs,
  SUM(CASE WHEN dashboard_rankable = 1 THEN COALESCE(performance_hours, 0) ELSE 0 END) AS sum_hours,
  SUM(CASE WHEN dashboard_rankable = 1 THEN 1 ELSE 0 END) AS employee_day_count,
  COUNT(*) AS visible_day_count
FROM {table}
WHERE organization_id = %s
  AND business_date_et >= %s
  AND business_date_et <= %s
  AND role_key IN ({role_placeholders})
GROUP BY role_key, employee_user_id, employee_name
"""


def build_employees_list(
    cursor,
    organization_id: int,
    *,
    week_start: date | None = None,
) -> dict[str, Any]:
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    start, end = resolve_week(week_start)
    visible = rinse_visible_roles()
    role_keys = [r["role_key"] for r in visible]
    if not role_keys:
        return {
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "employees": [],
            "query_count": 0,
        }

    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)
    placeholders = ",".join(["%s"] * len(role_keys))
    sql = _EMPLOYEES_WEEK_SQL.format(
        table=DAY_PUBLICATIONS_TABLE, role_placeholders=placeholders
    )
    cur.execute(sql, tuple([int(organization_id), start, end] + role_keys))
    rows = [dict(r) for r in (cur.fetchall() or [])]

    benches: dict[str, float | None] = {}
    if ROLE_FOLDER in role_keys:
        benches[ROLE_FOLDER] = get_folder_benchmark_cached(cur, organization_id)

    by_emp: dict[str, dict[str, Any]] = {}
    role_meta = {r["role_key"]: r for r in visible}
    for r in rows:
        uid = r.get("employee_user_id")
        name = r.get("employee_name")
        eid = _employee_id_from_agg(uid, name)
        key = f"u:{uid}" if uid is not None else f"n:{str(name or '').casefold()}"
        if key not in by_emp:
            by_emp[key] = {
                "employee_id": eid,
                "employee_user_id": uid,
                "name": name,
                "roles_summary": [],
            }
        rk = str(r.get("role_key") or "").upper()
        meta = role_meta.get(rk) or {}
        avg = _rate(float(r.get("sum_num") or 0), float(r.get("sum_den") or 0))
        by_emp[key]["roles_summary"].append(
            {
                "role_key": rk,
                "display_name": meta.get("display_name"),
                "metric_key": meta.get("metric_key"),
                "unit": meta.get("unit"),
                "weekly_avg": avg,
                "benchmark": benches.get(rk),
                "employee_days": int(r.get("employee_day_count") or 0),
                "days": int(r.get("employee_day_count") or 0),
                "visible_days": int(r.get("visible_day_count") or r.get("employee_day_count") or 0),
                "sessions": int(r.get("employee_day_count") or 0),
                "bags": int(r.get("sum_bags") or 0),
                "pounds": round(float(r.get("sum_lbs") or 0), 2),
                "hours": round(float(r.get("sum_hours") or 0), 4),
            }
        )

    employees = sorted(by_emp.values(), key=lambda e: str(e.get("name") or "").casefold())
    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "performance_unit": "employee_day",
        "employees": employees,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms, "rows_grouped": len(rows)},
    }
    _record_perf(endpoint="employees", query_count=q, wall_ms=wall_ms)
    return payload


def build_employee_detail(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    week_start: date | None = None,
) -> dict[str, Any]:
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    start, end = resolve_week(week_start)
    uid, name = _parse_employee_id(employee_id)
    visible = rinse_visible_roles()
    role_keys = [r["role_key"] for r in visible]
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    clauses = [
        "organization_id=%s",
        "dashboard_rankable = 1",
        "business_date_et >= %s",
        "business_date_et <= %s",
    ]
    params: list[Any] = [int(organization_id), start, end]
    if role_keys:
        placeholders = ",".join(["%s"] * len(role_keys))
        clauses.append(f"role_key IN ({placeholders})")
        params.extend(role_keys)
    if uid is not None:
        clauses.append("employee_user_id=%s")
        params.append(uid)
    else:
        clauses.append("employee_name=%s")
        params.append(str(name or "").strip())

    cur.execute(
        f"""
        SELECT role_key, employee_user_id, employee_name,
               SUM(published_numerator) AS sum_num,
               SUM(published_denominator) AS sum_den,
               SUM(orders_completed) AS sum_bags,
               SUM(total_pre_lbs) AS sum_lbs,
               SUM(COALESCE(performance_hours, 0)) AS sum_hours,
               COUNT(*) AS employee_day_count
        FROM {DAY_PUBLICATIONS_TABLE}
        WHERE {" AND ".join(clauses)}
        GROUP BY role_key, employee_user_id, employee_name
        """,
        tuple(params),
    )
    rows = [dict(r) for r in (cur.fetchall() or [])]
    benches: dict[str, float | None] = {}
    if any(r.get("role_key") == ROLE_FOLDER for r in rows) or ROLE_FOLDER in role_keys:
        benches[ROLE_FOLDER] = get_folder_benchmark_cached(cur, organization_id)

    display_name = name
    if rows:
        display_name = rows[0].get("employee_name") or display_name
    role_meta = {r["role_key"]: r for r in visible}
    roles_summary = []
    for r in rows:
        rk = str(r.get("role_key") or "").upper()
        meta = role_meta.get(rk) or {}
        roles_summary.append(
            {
                "role_key": rk,
                "display_name": meta.get("display_name"),
                "metric_key": meta.get("metric_key"),
                "unit": meta.get("unit"),
                "weekly_avg": _rate(
                    float(r.get("sum_num") or 0), float(r.get("sum_den") or 0)
                ),
                "benchmark": benches.get(rk),
                "employee_days": int(r.get("employee_day_count") or 0),
                "days": int(r.get("employee_day_count") or 0),
                "sessions": int(r.get("employee_day_count") or 0),
                "bags": int(r.get("sum_bags") or 0),
                "pounds": round(float(r.get("sum_lbs") or 0), 2),
                "hours": round(float(r.get("sum_hours") or 0), 4),
            }
        )
    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "employee_id": str(employee_id),
        "employee_user_id": uid,
        "name": display_name,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "performance_unit": "employee_day",
        "roles_summary": roles_summary,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms},
    }
    _record_perf(endpoint="employee_detail", query_count=q, wall_ms=wall_ms)
    return payload


_EMP_DAYS_WEEK_SQL = """
SELECT
  business_date_et,
  employee_name,
  employee_user_id,
  orders_completed,
  total_pre_lbs,
  performance_hours,
  bags_per_hour,
  published_metric_value,
  published_numerator,
  published_denominator,
  day_publication_status,
  dashboard_rankable,
  included_session_count,
  session_count,
  sessions_json
FROM {table}
WHERE organization_id = %s
  AND role_key = %s
  AND business_date_et >= %s
  AND business_date_et <= %s
  AND {emp_clause}
ORDER BY business_date_et ASC
"""


def build_employee_role_history(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    role_key: str,
    week_start: date | None = None,
    last_n: int = 5,
    metric: str | None = None,
) -> dict[str, Any]:
    """Employee → Day hierarchy for the selected week (sessions nested per day)."""
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {
            "error": "role_not_available",
            "role_key": rk,
            "employee_days": [],
            "sessions": [],
            "query_count": 0,
        }
    role = get_role(rk)
    assert role is not None
    start, end = resolve_week(week_start)
    metric_key = str(metric or "lbs_hr").lower()
    n = int(last_n or 7)
    if n not in (5, 7, 10, 20):
        n = 7
    uid, name = _parse_employee_id(employee_id)

    if uid is not None:
        emp_clause = "employee_user_id = %s"
        emp_param: Any = uid
    else:
        emp_clause = "employee_name = %s"
        emp_param = str(name or "").strip()

    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    sql = _EMP_DAYS_WEEK_SQL.format(table=DAY_PUBLICATIONS_TABLE, emp_clause=emp_clause)
    cur.execute(sql, (int(organization_id), rk, start, end, emp_param))
    day_rows = [dict(r) for r in (cur.fetchall() or [])]

    bench = get_folder_benchmark_cached(cur, organization_id) if rk == ROLE_FOLDER else None

    display_name = name
    if day_rows:
        display_name = day_rows[0].get("employee_name") or display_name

    sum_num = 0.0
    sum_den = 0.0
    sum_bags = 0
    sum_lbs = 0.0
    sum_hours = 0.0
    published_days = 0
    employee_days: list[dict[str, Any]] = []
    for r in day_rows:
        biz = r.get("business_date_et")
        date_s = biz.isoformat() if hasattr(biz, "isoformat") else str(biz or "")
        lbs = float(r.get("total_pre_lbs") or 0)
        hours = (
            float(r.get("performance_hours") or 0)
            if r.get("performance_hours") is not None
            else 0.0
        )
        bags = int(r.get("orders_completed") or 0)
        day_rate = (
            float(r["published_metric_value"])
            if r.get("published_metric_value") is not None
            else _rate(lbs, hours)
        )
        metric_value = _metric_value_for_row(
            metric=metric_key,
            sum_lbs=lbs,
            sum_hours=hours,
            sum_bags=bags,
            weekly_avg=day_rate,
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
        employee_days.append(
            {
                "date": date_s,
                "metric_value": metric_value,
                "lbs_per_hour": day_rate,
                "pounds": round(lbs, 2),
                "bags": bags,
                "orders_completed": bags,
                "hours": round(hours, 4) if hours else None,
                "performance_hours": round(hours, 4) if hours else None,
                "status": r.get("day_publication_status")
                or ("APPROVED" if rankable else "NEEDS_APPROVAL"),
                "dashboard_rankable": rankable,
                "included_session_count": int(r.get("included_session_count") or 0),
                "session_count": int(r.get("session_count") or len(sessions)),
                "sessions": sessions,
            }
        )

    chart_days = employee_days[-n:] if len(employee_days) > n else employee_days
    sessions_out = [
        {
            "session_id": f"day:{d['date']}",
            "date": d["date"],
            "metric_value": d["metric_value"],
            "quantity": d["pounds"],
            "duration_hours": d["hours"],
            "status": d["status"],
            "dashboard_rankable": d["dashboard_rankable"],
        }
        for d in chart_days
    ]

    weekly_avg = _rate(sum_num, sum_den)
    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "employee_id": str(employee_id),
        "employee_user_id": uid
        if uid is not None
        else (day_rows[0].get("employee_user_id") if day_rows else None),
        "name": display_name,
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": metric_key,
        "metric_label": role["metric_label"],
        "unit": role["unit"],
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "weekly_avg": weekly_avg,
        "approved_employee_day_count": published_days,
        "included_bags": sum_bags,
        "included_pounds": round(sum_lbs, 2),
        "included_hours": round(sum_hours, 4) if sum_hours else 0,
        "last_n": n,
        "employee_days": employee_days,
        "sessions": sessions_out,
        "query_count": q,
        "perf": {
            "query_count": q,
            "wall_ms": wall_ms,
            "employee_day_rows": len(employee_days),
            "statements": list(cur.statements),
        },
    }
    _record_perf(endpoint="employee_role_history", query_count=q, wall_ms=wall_ms)
    return payload


def explain_leaderboard_sql() -> str:
    from backend.rinse_performance_employee_day import DAY_PUBLICATIONS_TABLE

    return f"EXPLAIN {_DAY_LEADERBOARD_SQL.format(table=DAY_PUBLICATIONS_TABLE).strip()}"


def assert_no_live_management_imports() -> None:
    """Regression guard: this module must not import live Management calculators."""
    path = Path(__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {
        "backend.management_wf_folder_performance",
        "management_wf_folder_performance",
        "backend.rinse_step1_productivity_fast",
        "backend.rinse_employee_completed_bags",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden:
                    raise AssertionError(f"forbidden import: {alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in forbidden:
                raise AssertionError(f"forbidden import from: {mod}")
            for alias in node.names:
                if alias.name in {
                    "build_day_folder_performance",
                    "build_folder_performance_dashboard",
                }:
                    raise AssertionError(f"forbidden symbol import: {alias.name}")


BENCHMARK_SETTING_KEY = KEY_LBS_PER_HOUR


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))
