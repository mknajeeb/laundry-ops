"""Rinse-safe read projections for Performance (approved snapshots only)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.rinse_performance_approvals import (
    current_et_week_start,
    et_week_bounds,
    list_active_approvals,
    weighted_rate_from_rows,
)
from backend.rinse_performance_folder_publisher import get_folder_benchmark
from backend.rinse_performance_roles import (
    ROLE_FOLDER,
    get_role,
    rinse_visible_roles,
    role_is_publishable,
)

# Query counter for tests / instrumentation (per-call list).
_LAST_QUERY_COUNT = 0


def last_query_count() -> int:
    return int(_LAST_QUERY_COUNT)


def _set_query_count(n: int) -> None:
    global _LAST_QUERY_COUNT
    _LAST_QUERY_COUNT = int(n)


def resolve_week(week_start: date | None) -> tuple[date, date]:
    start = week_start or current_et_week_start()
    return et_week_bounds(start)


def build_rinse_meta(cursor, organization_id: int) -> dict[str, Any]:
    roles = []
    q = 0
    for role in rinse_visible_roles():
        bench = None
        if role["role_key"] == ROLE_FOLDER:
            bench = get_folder_benchmark(cursor, organization_id)
            q += 1
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
    _set_query_count(q)
    return {
        "modules": [
            {"id": "performance", "label": "Performance", "enabled": True},
            {"id": "weekly_schedule", "label": "Weekly Schedule", "enabled": True},
            {"id": "supplies_rejects", "label": "Supplies & Rejects", "enabled": False},
            {"id": "issues", "label": "Issues", "enabled": False},
        ],
        "performance_roles": roles,
    }


def _employee_key(row: dict[str, Any]) -> str:
    uid = row.get("employee_user_id")
    if uid is not None:
        try:
            return f"u:{int(uid)}"
        except (TypeError, ValueError):
            pass
    return f"n:{str(row.get('employee_name') or '').strip().casefold()}"


def _employee_id(row: dict[str, Any]) -> str:
    uid = row.get("employee_user_id")
    if uid is not None:
        try:
            return str(int(uid))
        except (TypeError, ValueError):
            pass
    # Stable fallback for unmapped names (rare)
    name = str(row.get("employee_name") or "").strip()
    return f"name:{name}"


def build_role_leaderboard(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    week_start: date | None = None,
) -> dict[str, Any]:
    """Approved-only role leaderboard. Snapshot reads only — no Management builder."""
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
    rows = list_active_approvals(
        cursor,
        organization_id,
        role_key=rk,
        week_start=start,
        week_end=end,
    )
    # list_active_approvals may ensure tables (1) + select (1)
    q = 2
    bench = get_folder_benchmark(cursor, organization_id) if rk == ROLE_FOLDER else None
    if rk == ROLE_FOLDER:
        q += 1

    by_emp: dict[str, list[dict[str, Any]]] = {}
    emp_meta: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _employee_key(r)
        by_emp.setdefault(key, []).append(r)
        emp_meta[key] = {
            "employee_id": _employee_id(r),
            "employee_user_id": r.get("employee_user_id"),
            "name": r.get("employee_name"),
        }

    leaderboard = []
    for key, emp_rows in by_emp.items():
        avg = weighted_rate_from_rows(emp_rows)
        meta = emp_meta[key]
        vs = None if avg is None or bench is None else round(float(avg) - float(bench), 4)
        leaderboard.append(
            {
                "employee_id": meta["employee_id"],
                "employee_user_id": meta["employee_user_id"],
                "name": meta["name"],
                "weekly_avg": avg,
                "vs_benchmark": vs,
                "sessions": len(emp_rows),
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

    team = weighted_rate_from_rows(rows)
    _set_query_count(q)
    return {
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": role["metric_key"],
        "metric_label": role["metric_label"],
        "unit": role["unit"],
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "team_weekly_avg": team,
        "approved_session_count": len(rows),
        "leaderboard": leaderboard,
        "query_count": q,
    }


def build_employees_list(
    cursor,
    organization_id: int,
    *,
    week_start: date | None = None,
) -> dict[str, Any]:
    start, end = resolve_week(week_start)
    # Only live roles — Phase 1 FOLDER
    visible = rinse_visible_roles()
    rows: list[dict[str, Any]] = []
    q = 0
    for role in visible:
        chunk = list_active_approvals(
            cursor,
            organization_id,
            role_key=role["role_key"],
            week_start=start,
            week_end=end,
        )
        q += 2
        rows.extend(chunk)

    benches: dict[str, float | None] = {}
    for role in visible:
        if role["role_key"] == ROLE_FOLDER:
            benches[ROLE_FOLDER] = get_folder_benchmark(cursor, organization_id)
            q += 1
        else:
            benches[role["role_key"]] = None

    by_emp: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _employee_key(r)
        if key not in by_emp:
            by_emp[key] = {
                "employee_id": _employee_id(r),
                "employee_user_id": r.get("employee_user_id"),
                "name": r.get("employee_name"),
                "roles": {},
            }
        rk = str(r.get("role_key") or "").upper()
        by_emp[key]["roles"].setdefault(rk, []).append(r)

    employees = []
    for emp in by_emp.values():
        roles_summary = []
        for role in visible:
            rk = role["role_key"]
            emp_rows = emp["roles"].get(rk) or []
            if not emp_rows:
                continue
            avg = weighted_rate_from_rows(emp_rows)
            bench = benches.get(rk)
            roles_summary.append(
                {
                    "role_key": rk,
                    "display_name": role["display_name"],
                    "metric_key": role["metric_key"],
                    "unit": role["unit"],
                    "weekly_avg": avg,
                    "benchmark": bench,
                    "sessions": len(emp_rows),
                }
            )
        if not roles_summary:
            continue
        employees.append(
            {
                "employee_id": emp["employee_id"],
                "employee_user_id": emp["employee_user_id"],
                "name": emp["name"],
                "roles_summary": roles_summary,
            }
        )
    employees.sort(key=lambda e: str(e.get("name") or "").casefold())
    _set_query_count(q)
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "employees": employees,
        "query_count": q,
    }


def build_employee_detail(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    week_start: date | None = None,
) -> dict[str, Any]:
    start, end = resolve_week(week_start)
    eid = str(employee_id or "").strip()
    uid = None
    name = None
    if eid.startswith("name:"):
        name = eid[5:]
    else:
        try:
            uid = int(eid)
        except ValueError:
            name = eid

    visible = rinse_visible_roles()
    rows: list[dict[str, Any]] = []
    q = 0
    for role in visible:
        chunk = list_active_approvals(
            cursor,
            organization_id,
            role_key=role["role_key"],
            week_start=start,
            week_end=end,
            employee_user_id=uid,
            employee_name=name if uid is None else None,
        )
        q += 2
        # If looked up by uid, also allow name fallback when uid rows empty is fine
        rows.extend(chunk)

    if uid is not None and not rows:
        # Some snapshots may lack user_id — do not broaden by name automatically
        pass

    display_name = name
    if rows:
        display_name = rows[0].get("employee_name") or display_name

    benches: dict[str, float | None] = {}
    roles_summary = []
    for role in visible:
        rk = role["role_key"]
        if rk == ROLE_FOLDER:
            benches[rk] = get_folder_benchmark(cursor, organization_id)
            q += 1
        emp_rows = [r for r in rows if str(r.get("role_key") or "").upper() == rk]
        if not emp_rows:
            continue
        roles_summary.append(
            {
                "role_key": rk,
                "display_name": role["display_name"],
                "metric_key": role["metric_key"],
                "unit": role["unit"],
                "weekly_avg": weighted_rate_from_rows(emp_rows),
                "benchmark": benches.get(rk),
                "sessions": len(emp_rows),
            }
        )
    _set_query_count(q)
    return {
        "employee_id": eid,
        "employee_user_id": uid,
        "name": display_name,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "roles_summary": roles_summary,
        "query_count": q,
    }


def build_employee_role_history(
    cursor,
    organization_id: int,
    *,
    employee_id: str,
    role_key: str,
    week_start: date | None = None,
    last_n: int = 5,
) -> dict[str, Any]:
    rk = str(role_key).upper()
    if not role_is_publishable(rk):
        return {"error": "role_not_available", "role_key": rk, "sessions": [], "query_count": 0}
    role = get_role(rk)
    assert role is not None
    start, end = resolve_week(week_start)
    n = int(last_n or 5)
    if n not in (5, 10, 20):
        n = 5

    eid = str(employee_id or "").strip()
    uid = None
    name = None
    if eid.startswith("name:"):
        name = eid[5:]
    else:
        try:
            uid = int(eid)
        except ValueError:
            name = eid

    # Week rows for weekly avg
    week_rows = list_active_approvals(
        cursor,
        organization_id,
        role_key=rk,
        week_start=start,
        week_end=end,
        employee_user_id=uid,
        employee_name=name if uid is None else None,
    )
    # Last N approved across time (not limited to week) — still approved only
    all_rows = list_active_approvals(
        cursor,
        organization_id,
        role_key=rk,
        employee_user_id=uid,
        employee_name=name if uid is None else None,
    )
    q = 4
    # Sort newest first for last N
    all_rows_sorted = sorted(
        all_rows,
        key=lambda r: (
            str(r.get("business_date_et") or ""),
            str(r.get("published_session_start_et") or ""),
            int(r.get("id") or 0),
        ),
        reverse=True,
    )
    last_sessions = list(reversed(all_rows_sorted[:n]))

    bench = get_folder_benchmark(cursor, organization_id) if rk == ROLE_FOLDER else None
    if rk == ROLE_FOLDER:
        q += 1

    display_name = name
    if week_rows:
        display_name = week_rows[0].get("employee_name") or display_name
    elif last_sessions:
        display_name = last_sessions[0].get("employee_name") or display_name

    sessions_out = []
    for r in last_sessions:
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
            }
        )

    _set_query_count(q)
    return {
        "employee_id": eid,
        "employee_user_id": uid,
        "name": display_name,
        "role_key": rk,
        "display_name": role["display_name"],
        "metric_key": role["metric_key"],
        "metric_label": role["metric_label"],
        "unit": role["unit"],
        "benchmark": bench,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "weekly_avg": weighted_rate_from_rows(week_rows),
        "last_n": n,
        "sessions": sessions_out,
        "query_count": q,
    }
