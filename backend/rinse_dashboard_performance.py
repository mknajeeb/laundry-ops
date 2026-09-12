"""Rinse-safe read projections — snapshot-only, set-based, query-budgeted.

HARD RULES:
- Never import or call live Management Performance builders.
- Prefer 1–3 SQL queries per endpoint (hard ceiling documented per handler).
- No N+1. No per-employee queries. No unbounded history on page load.
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
        "query_count": q,
        "perf": {"query_count": q, "ensure_queries": q_ensure, "wall_ms": wall_ms},
    }
    _record_perf(endpoint="meta", query_count=q, wall_ms=wall_ms)
    return payload


# ---------------------------------------------------------------------------
# Role leaderboard — preferably 2 queries (GROUP BY + benchmark)
# ---------------------------------------------------------------------------
_LEADERBOARD_SQL = f"""
SELECT
  employee_user_id,
  employee_name,
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  COUNT(*) AS session_count
FROM {APPROVALS_TABLE}
WHERE organization_id = %s
  AND role_key = %s
  AND invalidated_at IS NULL
  AND business_date_et >= %s
  AND business_date_et <= %s
GROUP BY employee_user_id, employee_name
"""


def build_role_leaderboard(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    week_start: date | None = None,
) -> dict[str, Any]:
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
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    cur.execute(_LEADERBOARD_SQL, (int(organization_id), rk, start, end))
    rows = [dict(r) for r in (cur.fetchall() or [])]

    bench = get_folder_benchmark_cached(cur, organization_id) if rk == ROLE_FOLDER else None

    team_num = 0.0
    team_den = 0.0
    team_sessions = 0
    leaderboard = []
    for r in rows:
        num = float(r.get("sum_num") or 0)
        den = float(r.get("sum_den") or 0)
        sess_n = int(r.get("session_count") or 0)
        avg = _rate(num, den)
        if den > 0:
            team_num += num
            team_den += den
        team_sessions += sess_n
        vs = None if avg is None or bench is None else round(float(avg) - float(bench), 4)
        leaderboard.append(
            {
                "employee_id": _employee_id_from_agg(r.get("employee_user_id"), r.get("employee_name")),
                "employee_user_id": r.get("employee_user_id"),
                "name": r.get("employee_name"),
                "weekly_avg": avg,
                "vs_benchmark": vs,
                "sessions": sess_n,
            }
        )
    leaderboard.sort(
        key=lambda e: (
            -(e["weekly_avg"] if e["weekly_avg"] is not None else -1e18),
            str(e.get("name") or "").casefold(),
        )
    )
    for i, row in enumerate(leaderboard, start=1):
        row["rank"] = i

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": role["metric_key"],
        "metric_label": role["metric_label"],
        "unit": role["unit"],
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "team_weekly_avg": _rate(team_num, team_den),
        "approved_session_count": team_sessions,
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
        rows_grouped=len(rows),
    )
    return payload


# ---------------------------------------------------------------------------
# Employees cross-role list — 1 week scan for all live roles + 1 benchmark
# ---------------------------------------------------------------------------
_EMPLOYEES_WEEK_SQL = f"""
SELECT
  role_key,
  employee_user_id,
  employee_name,
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  COUNT(*) AS session_count
FROM {APPROVALS_TABLE}
WHERE organization_id = %s
  AND invalidated_at IS NULL
  AND business_date_et >= %s
  AND business_date_et <= %s
  AND role_key IN ({{role_placeholders}})
GROUP BY role_key, employee_user_id, employee_name
"""


def build_employees_list(
    cursor,
    organization_id: int,
    *,
    week_start: date | None = None,
) -> dict[str, Any]:
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
    sql = _EMPLOYEES_WEEK_SQL.format(role_placeholders=placeholders)
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
                "sessions": int(r.get("session_count") or 0),
            }
        )

    employees = sorted(by_emp.values(), key=lambda e: str(e.get("name") or "").casefold())
    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
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
    """Cross-role week summary for one employee — 1–2 queries."""
    t0 = time.perf_counter()
    start, end = resolve_week(week_start)
    uid, name = _parse_employee_id(employee_id)
    visible = rinse_visible_roles()
    role_keys = [r["role_key"] for r in visible]
    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    clauses = [
        "organization_id=%s",
        "invalidated_at IS NULL",
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
               COUNT(*) AS session_count
        FROM {APPROVALS_TABLE}
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
                "weekly_avg": _rate(float(r.get("sum_num") or 0), float(r.get("sum_den") or 0)),
                "benchmark": benches.get(rk),
                "sessions": int(r.get("session_count") or 0),
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
        "roles_summary": roles_summary,
        "query_count": q,
        "perf": {"query_count": q, "wall_ms": wall_ms},
    }
    _record_perf(endpoint="employee_detail", query_count=q, wall_ms=wall_ms)
    return payload


# ---------------------------------------------------------------------------
# Employee + role history — week aggregate + LIMIT last_n (≤3 queries)
# ---------------------------------------------------------------------------
_LAST_N_SQL = f"""
SELECT
  session_id,
  business_date_et,
  published_metric_value,
  published_quantity,
  published_duration_hours,
  published_session_start_et,
  published_session_end_et,
  employee_name,
  employee_user_id
FROM {APPROVALS_TABLE}
WHERE organization_id = %s
  AND role_key = %s
  AND invalidated_at IS NULL
  AND {{emp_clause}}
ORDER BY business_date_et DESC, published_session_start_et DESC, id DESC
LIMIT %s
"""

_WEEK_AGG_SQL = f"""
SELECT
  employee_name,
  employee_user_id,
  SUM(published_numerator) AS sum_num,
  SUM(published_denominator) AS sum_den,
  COUNT(*) AS session_count
FROM {APPROVALS_TABLE}
WHERE organization_id = %s
  AND role_key = %s
  AND invalidated_at IS NULL
  AND business_date_et >= %s
  AND business_date_et <= %s
  AND {{emp_clause}}
GROUP BY employee_name, employee_user_id
LIMIT 1
"""


def build_employee_role_history(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    role_key: str,
    week_start: date | None = None,
    last_n: int = 5,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk, "sessions": [], "query_count": 0}
    role = get_role(rk)
    assert role is not None
    start, end = resolve_week(week_start)
    n = int(last_n or 5)
    if n not in (5, 10, 20):
        n = 5
    uid, name = _parse_employee_id(employee_id)

    if uid is not None:
        emp_clause = "employee_user_id = %s"
        emp_param: Any = uid
    else:
        emp_clause = "employee_name = %s"
        emp_param = str(name or "").strip()

    cur = wrap_cursor(cursor)
    _ensure_tables_once(cur)

    week_sql = _WEEK_AGG_SQL.format(emp_clause=emp_clause)
    cur.execute(week_sql, (int(organization_id), rk, start, end, emp_param))
    week_row = cur.fetchone()
    week = dict(week_row) if week_row else {}

    last_sql = _LAST_N_SQL.format(emp_clause=emp_clause)
    cur.execute(last_sql, (int(organization_id), rk, emp_param, n))
    last_rows = [dict(r) for r in (cur.fetchall() or [])]
    # Chronological for chart (oldest → newest)
    last_rows.reverse()

    bench = get_folder_benchmark_cached(cur, organization_id) if rk == ROLE_FOLDER else None

    display_name = name
    if week.get("employee_name"):
        display_name = week.get("employee_name")
    elif last_rows:
        display_name = last_rows[0].get("employee_name") or display_name

    sessions_out = []
    for r in last_rows:
        biz = r.get("business_date_et")
        sessions_out.append(
            {
                "session_id": r.get("session_id"),
                "date": biz.isoformat() if hasattr(biz, "isoformat") else str(biz or ""),
                "metric_value": (
                    float(r["published_metric_value"])
                    if r.get("published_metric_value") is not None
                    else None
                ),
                "quantity": (
                    float(r["published_quantity"])
                    if r.get("published_quantity") is not None
                    else None
                ),
                "duration_hours": (
                    float(r["published_duration_hours"])
                    if r.get("published_duration_hours") is not None
                    else None
                ),
            }
        )

    q = int(cur._rinse_qcount)
    wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = {
        "employee_id": str(employee_id),
        "employee_user_id": uid if uid is not None else week.get("employee_user_id"),
        "name": display_name,
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": role["metric_key"],
        "metric_label": role["metric_label"],
        "unit": role["unit"],
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "weekly_avg": _rate(float(week.get("sum_num") or 0), float(week.get("sum_den") or 0)),
        "last_n": n,
        "sessions": sessions_out,
        "query_count": q,
        "perf": {
            "query_count": q,
            "wall_ms": wall_ms,
            "last_n_rows": len(sessions_out),
            "statements": list(cur.statements),
        },
    }
    _record_perf(endpoint="employee_role_history", query_count=q, wall_ms=wall_ms)
    return payload


def explain_leaderboard_sql() -> str:
    """Canonical EXPLAIN target for ops / acceptance."""
    return f"EXPLAIN {_LEADERBOARD_SQL.strip()}"


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


# Re-export setting key for tests / docs
BENCHMARK_SETTING_KEY = KEY_LBS_PER_HOUR


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))
