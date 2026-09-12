#!/usr/bin/env python3
"""Print Rinse dashboard query-budget acceptance table (in-memory load sim).

Optional: set MYSQL_* env and RUN_EXPLAIN=1 to print EXPLAIN on production-like DB.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import date, timedelta
from unittest.mock import patch

from backend.tests.test_rinse_dashboard_query_budget import (
    DAY,
    SnapshotCursor,
    _seed,
)
from backend.rinse_dashboard_performance import (
    build_employee_role_history,
    build_employees_list,
    build_role_leaderboard,
    clear_benchmark_cache,
    explain_leaderboard_sql,
    payload_bytes,
)
from backend import rinse_dashboard_performance as rdp
from backend.rinse_performance_roles import ROLE_FOLDER


def _bench(fn, rounds=25):
    times = []
    last = None
    for i in range(rounds):
        if i == 0:
            clear_benchmark_cache()
        t0 = time.perf_counter()
        last = fn()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {
        "p50_ms": round(times[len(times) // 2], 2),
        "p95_ms": round(times[int(len(times) * 0.95) - 1], 2),
        "max_ms": round(max(times), 2),
        "query_count": last.get("query_count"),
        "payload_bytes": payload_bytes(last),
        "rows": last.get("perf", {}).get("rows_grouped")
        or last.get("perf", {}).get("last_n_rows")
        or len(last.get("employees") or last.get("leaderboard") or []),
    }


def main():
    rdp._TABLES_READY = True
    cur = SnapshotCursor()
    _seed(cur, n_employees=40, sessions_per=8)
    week_start = DAY - timedelta(days=DAY.weekday())

    with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
        role = _bench(
            lambda: build_role_leaderboard(
                cur, 3, role_key=ROLE_FOLDER, week_start=week_start
            )
        )
        emps = _bench(lambda: build_employees_list(cur, 3, week_start=week_start))
        hist5 = _bench(
            lambda: build_employee_role_history(
                cur,
                3,
                employee_id="1000",
                role_key=ROLE_FOLDER,
                week_start=week_start,
                last_n=5,
            )
        )
        hist20 = _bench(
            lambda: build_employee_role_history(
                cur,
                3,
                employee_id="1000",
                role_key=ROLE_FOLDER,
                week_start=week_start,
                last_n=20,
            )
        )

    print("=== Rinse dashboard query budget (seeded 40 employees × 8 sessions) ===")
    rows = [
        ("GET .../roles/FOLDER", role),
        ("GET .../employees", emps),
        ("GET .../roles/FOLDER last_n=5", hist5),
        ("GET .../roles/FOLDER last_n=20", hist20),
    ]
    print(
        f"{'Endpoint':<36} {'SQL':>4} {'p50ms':>7} {'p95ms':>7} {'maxms':>7} {'payload':>8} {'rows':>6}"
    )
    for name, m in rows:
        print(
            f"{name:<36} {m['query_count']:>4} {m['p50_ms']:>7} {m['p95_ms']:>7} "
            f"{m['max_ms']:>7} {m['payload_bytes']:>8} {m['rows']:>6}"
        )
    print("\nLeaderboard SQL (EXPLAIN target):")
    print(explain_leaderboard_sql())
    print(
        "\nIndex strategy: idx_rinse_perf_read_role_week "
        "(organization_id, role_key, invalidated_at, business_date_et); "
        "idx_rinse_perf_read_emp_hist "
        "(organization_id, role_key, employee_user_id, invalidated_at, "
        "business_date_et, published_session_start_et, id)"
    )
    print(
        "Expected EXPLAIN: ref/range on idx_rinse_perf_read_role_week; "
        "no full table scan; GROUP BY may use temporary/filesort on small "
        "employee cardinality only."
    )

    if os.getenv("RUN_EXPLAIN") == "1":
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            # Bound literals — the explain_leaderboard_sql() helper keeps %s for apps.
            cursor.execute(
                """
                EXPLAIN SELECT
                  employee_user_id,
                  employee_name,
                  SUM(published_numerator) AS sum_num,
                  SUM(published_denominator) AS sum_den,
                  COUNT(*) AS session_count
                FROM rinse_performance_session_approvals
                WHERE organization_id = 3
                  AND role_key = 'FOLDER'
                  AND invalidated_at IS NULL
                  AND excluded_at IS NULL
                  AND business_date_et >= '2026-09-07'
                  AND business_date_et <= '2026-09-13'
                GROUP BY employee_user_id, employee_name
                """
            )
            print("\nEXPLAIN rows:")
            for row in cursor.fetchall() or []:
                print(json.dumps(row, default=str))
            cursor.execute(
                """
                EXPLAIN SELECT session_id, business_date_et, published_metric_value
                FROM rinse_performance_session_approvals
                WHERE organization_id = 3
                  AND role_key = 'FOLDER'
                  AND invalidated_at IS NULL
                  AND excluded_at IS NULL
                  AND employee_user_id = 38
                ORDER BY business_date_et DESC, published_session_start_et DESC, id DESC
                LIMIT 5
                """
            )
            print("\nEXPLAIN emp hist:")
            for row in cursor.fetchall() or []:
                print(json.dumps(row, default=str))
        finally:
            cursor.close()
            conn.close()


if __name__ == "__main__":
    main()
