"""
Payroll scheduling — parameterized shifts, roles, work streams, availability.

Worker identity: users.id via payroll_worker_profiles (same key as payroll / clock).
Performance preview uses rinse_folding_user_map when available.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from backend.payroll_identity import get_payroll_period_settings, payroll_week_bounds
from backend.payroll_operations import worker_category_for_user
from backend.ta_helpers import json_safe, table_exists, table_has_column

SCHEDULE_STATUSES = (
    "scheduled",
    "clocked_in",
    "completed",
    "absent",
    "sick",
    "no_show",
    "replaced",
    "cancelled",
)
ABSENT_STATUSES = frozenset({"absent", "sick", "no_show"})

DEFAULT_SHIFTS = (
    ("Morning", "07:00:00", "15:00:00", 10),
    ("Afternoon", "15:00:00", "23:00:00", 20),
    ("Evening", "17:00:00", "01:00:00", 30),
    ("Night", "23:00:00", "07:00:00", 40),
)
DEFAULT_STREAMS = (("Rinse", 10), ("Drop Off", 20), ("Both", 30))
DEFAULT_ROLES = (
    ("Operator", 10),
    ("Folder", 20),
    ("Weighing", 30),
    ("Sorting", 40),
    ("Washing", 50),
    ("Drying", 60),
    ("Packing", 70),
    ("Supervisor", 80),
)


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def _q2(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _cursor(conn):
    return conn.cursor(dictionary=True)


def _dict_cursor(conn_or_cursor):
    """Dictionary cursor whether caller passed a connection or plain cursor."""
    if hasattr(conn_or_cursor, "cursor") and callable(getattr(conn_or_cursor, "cursor", None)):
        try:
            return conn_or_cursor.cursor(dictionary=True)
        except TypeError:
            pass
    conn = getattr(conn_or_cursor, "_connection", None) or getattr(conn_or_cursor, "connection", None)
    if conn is not None and hasattr(conn, "cursor"):
        return conn.cursor(dictionary=True)
    return conn_or_cursor


def _where_active(cursor, table: str, alias: str = "") -> str:
    """SQL predicate for active rows; safe when legacy DB lacks `active` column."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    prefix = f"{alias}." if alias else ""
    if table_exists(c, table) and table_has_column(c, table, "active"):
        return f"{prefix}active=1"
    return "1=1"


def _select_active_expr(cursor, table: str) -> str:
    """SELECT list fragment for active flag (defaults to 1 when column missing)."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    if table_exists(c, table) and table_has_column(c, table, "active"):
        return "active"
    return "1 AS active"


def _users_list_filter(cursor) -> str:
    """Who appears in scheduling worker list — tolerates production without users.active."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    if table_has_column(c, "users", "active"):
        return "(pp.user_id IS NOT NULL OR u.active = 1)"
    return "pp.user_id IS NOT NULL"


def ensure_payroll_schedule_tables(cursor) -> None:
    if table_exists(cursor, "payroll_schedule_entries"):
        return
    import pathlib

    sql_path = pathlib.Path(__file__).resolve().parent / "sql" / "payroll_schedule_v1.sql"
    raw = sql_path.read_text(encoding="utf-8")
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    for stmt in raw.split(";"):
        s = stmt.strip()
        if s and not s.startswith("--"):
            c.execute(s)


def seed_schedule_defaults(cursor, organization_id: int) -> None:
    ensure_payroll_schedule_tables(cursor)
    oid = int(organization_id)
    c = _dict_cursor(cursor)
    c.execute(
        "INSERT IGNORE INTO payroll_schedule_org_settings (organization_id) VALUES (%s)",
        (oid,),
    )
    c.execute("SELECT COUNT(*) AS n FROM payroll_shifts WHERE organization_id=%s", (oid,))
    shift_n = int((c.fetchone() or {}).get("n") or 0)
    if shift_n == 0:
        for name, start_t, end_t, sort in DEFAULT_SHIFTS:
            c.execute(
                """
                INSERT INTO payroll_shifts
                  (organization_id, name, start_time_default, end_time_default, sort_order, active)
                VALUES (%s, %s, %s, %s, %s, 1)
                """,
                (oid, name, start_t, end_t, sort),
            )
    c.execute("SELECT COUNT(*) AS n FROM payroll_work_streams WHERE organization_id=%s", (oid,))
    stream_n = int((c.fetchone() or {}).get("n") or 0)
    if stream_n == 0:
        for name, sort in DEFAULT_STREAMS:
            c.execute(
                """
                INSERT INTO payroll_work_streams (organization_id, name, sort_order, active)
                VALUES (%s, %s, %s, 1)
                """,
                (oid, name, sort),
            )
    c.execute("SELECT COUNT(*) AS n FROM payroll_roles WHERE organization_id=%s", (oid,))
    role_n = int((c.fetchone() or {}).get("n") or 0)
    if role_n == 0:
        for name, sort in DEFAULT_ROLES:
            c.execute(
                """
                INSERT INTO payroll_roles (organization_id, name, sort_order, active)
                VALUES (%s, %s, %s, CASE WHEN %s <= 20 THEN 1 ELSE 0 END)
                """,
                (oid, name, sort, sort),
            )


def _nullable_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _nullable_decimal(val: Any) -> Optional[Any]:
    if val is None or val == "":
        return None
    return val


def _parse_time(val: Any) -> Optional[time]:
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, timedelta):
        return (datetime.min + val).time()
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt).time()
        except ValueError:
            continue
    return None


def _time_to_str(t: Optional[time]) -> Optional[str]:
    if t is None:
        return None
    return t.strftime("%H:%M:%S")


def compute_scheduled_hours(start_t: time, end_t: time, break_minutes: int = 0) -> Decimal:
    """Hours between start/end minus break; supports overnight end."""
    base = date(2000, 1, 1)
    start_dt = datetime.combine(base, start_t)
    end_dt = datetime.combine(base, end_t)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    minutes = (end_dt - start_dt).total_seconds() / 60.0 - max(0, int(break_minutes or 0))
    return max(Decimal("0"), _d(minutes / 60.0))


def get_org_schedule_settings(conn, organization_id: int) -> dict[str, Any]:
    from backend.payroll_schedule_planner import ensure_payroll_schedule_v2

    seed_schedule_defaults(conn.cursor(), organization_id)
    ensure_payroll_schedule_v2(conn.cursor())
    c = _cursor(conn)
    oid = int(organization_id)
    c.execute(
        """
        SELECT overtime_threshold_hours, default_break_minutes,
               underused_hours_threshold, heavy_hours_threshold, target_hours_per_week,
               payment_day_of_week
        FROM payroll_schedule_org_settings WHERE organization_id=%s
        """,
        (oid,),
    )
    org_row = c.fetchone() or {}
    period = get_payroll_period_settings(conn, oid) or {}
    from backend.payroll_planning_settings import ensure_planning_optional_columns

    ensure_planning_optional_columns(c)
    shift_cols = f"id, name, start_time_default, end_time_default, sort_order, {_select_active_expr(c, 'payroll_shifts')}"
    if table_has_column(c, "payroll_shifts", "notes"):
        shift_cols += ", notes"
    c.execute(
        f"""
        SELECT {shift_cols}
        FROM payroll_shifts WHERE organization_id=%s ORDER BY sort_order, name
        """,
        (oid,),
    )
    shifts = [json_safe(r) for r in c.fetchall()]
    for s in shifts:
        s["start_time_default"] = _time_to_str(_parse_time(s.get("start_time_default")))
        s["end_time_default"] = _time_to_str(_parse_time(s.get("end_time_default")))
    stream_cols = f"id, name, sort_order, {_select_active_expr(c, 'payroll_work_streams')}"
    if table_has_column(c, "payroll_work_streams", "notes"):
        stream_cols += ", notes"
    c.execute(
        f"""
        SELECT {stream_cols} FROM payroll_work_streams
        WHERE organization_id=%s ORDER BY sort_order, name
        """,
        (oid,),
    )
    streams = [json_safe(r) for r in c.fetchall()]
    role_cols = f"id, name, sort_order, {_select_active_expr(c, 'payroll_roles')}"
    if table_has_column(c, "payroll_roles", "role_group"):
        role_cols += ", role_group"
    c.execute(
        f"""
        SELECT {role_cols} FROM payroll_roles
        WHERE organization_id=%s ORDER BY sort_order, name
        """,
        (oid,),
    )
    roles = [json_safe(r) for r in c.fetchall()]
    return json_safe(
        {
            "shifts": shifts,
            "work_streams": streams,
            "roles": roles,
            "week_starts_on": int(period.get("week_starts_on") or 0),
            "overtime_threshold_hours": float(org_row.get("overtime_threshold_hours") or 40),
            "default_break_minutes": int(org_row.get("default_break_minutes") or 0),
            "underused_hours_threshold": float(org_row.get("underused_hours_threshold") or 15),
            "heavy_hours_threshold": float(org_row.get("heavy_hours_threshold") or 35),
            "target_hours_per_week": float(org_row.get("target_hours_per_week") or 32),
            "payment_day_of_week": int(org_row.get("payment_day_of_week") if org_row.get("payment_day_of_week") is not None else 6),
            "schedule_statuses": list(SCHEDULE_STATUSES),
        }
    )


def update_org_schedule_settings(conn, organization_id: int, body: dict) -> dict[str, Any]:
    seed_schedule_defaults(conn.cursor(), organization_id)
    c = conn.cursor()
    oid = int(organization_id)
    if body.get("overtime_threshold_hours") is not None:
        c.execute(
            """
            INSERT INTO payroll_schedule_org_settings (organization_id, overtime_threshold_hours)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE overtime_threshold_hours=VALUES(overtime_threshold_hours)
            """,
            (oid, float(body["overtime_threshold_hours"])),
        )
    for fld in ("underused_hours_threshold", "heavy_hours_threshold", "target_hours_per_week"):
        if body.get(fld) is not None:
            c.execute(
                f"""
                INSERT INTO payroll_schedule_org_settings (organization_id, {fld})
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE {fld}=VALUES({fld})
                """,
                (oid, float(body[fld])),
            )
    if body.get("default_break_minutes") is not None:
        c.execute(
            """
            INSERT INTO payroll_schedule_org_settings (organization_id, default_break_minutes)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE default_break_minutes=VALUES(default_break_minutes)
            """,
            (oid, int(body["default_break_minutes"])),
        )
    if body.get("payment_day_of_week") is not None:
        c.execute(
            """
            INSERT INTO payroll_schedule_org_settings (organization_id, payment_day_of_week)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE payment_day_of_week=VALUES(payment_day_of_week)
            """,
            (oid, int(body["payment_day_of_week"])),
        )
    from backend.payroll_planning_settings import ensure_planning_optional_columns

    ensure_planning_optional_columns(c)
    for key, table, cols in (
        ("shifts", "payroll_shifts", ("name", "start_time_default", "end_time_default", "sort_order", "active", "notes")),
        ("work_streams", "payroll_work_streams", ("name", "sort_order", "active", "notes")),
        ("roles", "payroll_roles", ("name", "sort_order", "active", "role_group")),
    ):
        items = body.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if item.get("id"):
                sets = []
                params = []
                for col in cols:
                    if col in item:
                        sets.append(f"{col}=%s")
                        params.append(item[col])
                if sets:
                    params.extend([int(item["id"]), oid])
                    c.execute(
                        f"UPDATE {table} SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
                        tuple(params),
                    )
            else:
                if table == "payroll_shifts":
                    c.execute(
                        f"""
                        INSERT INTO {table}
                          (organization_id, name, start_time_default, end_time_default, sort_order, active)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE sort_order=VALUES(sort_order), active=VALUES(active)
                        """,
                        (
                            oid,
                            name,
                            item.get("start_time_default") or "09:00:00",
                            item.get("end_time_default") or "17:00:00",
                            int(item.get("sort_order") or 0),
                            1 if item.get("active", True) else 0,
                        ),
                    )
                else:
                    c.execute(
                        f"""
                        INSERT INTO {table} (organization_id, name, sort_order, active)
                        VALUES (%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE sort_order=VALUES(sort_order), active=VALUES(active)
                        """,
                        (oid, name, int(item.get("sort_order") or 0), 1 if item.get("active", True) else 0),
                    )
    return get_org_schedule_settings(conn, organization_id)


def _worker_display_name(c, user_id: int) -> str:
    """Resolve display name from payroll_profiles and/or users (schema varies by tenant)."""
    name_parts = []
    if table_has_column(c, "payroll_profiles", "first_name"):
        name_parts.append("NULLIF(TRIM(CONCAT(pp.first_name,' ',pp.last_name)), '')")
    if table_has_column(c, "users", "display_name"):
        name_parts.append("NULLIF(TRIM(u.display_name), '')")
    if table_has_column(c, "users", "username"):
        name_parts.append("NULLIF(TRIM(u.username), '')")
    if table_has_column(c, "payroll_profiles", "email"):
        name_parts.append("NULLIF(TRIM(pp.email), '')")
    if table_has_column(c, "users", "email"):
        name_parts.append("NULLIF(TRIM(u.email), '')")
    name_parts.append("CONCAT('User #', u.id)")
    coalesce = ", ".join(name_parts)
    c.execute(
        f"""
        SELECT COALESCE({coalesce}) AS nm
        FROM users u
        LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
        WHERE u.id=%s LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone() or {}
    return str(row.get("nm") or f"User #{user_id}")


def ensure_worker_profile(
    conn, organization_id: int, user_id: int, *, sync_category: bool = True
) -> dict[str, Any]:
    from backend.payroll_schedule_planner import ensure_payroll_schedule_v2
    from backend.payroll_worker_defaults import (
        ensure_worker_profile_payroll_defaults,
        is_blank_rate,
        new_worker_payroll_defaults,
    )

    ensure_payroll_schedule_v2(conn.cursor())
    seed_schedule_defaults(conn.cursor(), organization_id)
    c = _cursor(conn)
    oid = int(organization_id)
    uid = int(user_id)
    c.execute(
        "SELECT * FROM payroll_worker_profiles WHERE organization_id=%s AND user_id=%s",
        (oid, uid),
    )
    row = c.fetchone()
    cat = worker_category_for_user(conn, uid) if sync_category else (row or {}).get("worker_category", "w2")
    if not row:
        from backend.payroll_workflow import resolve_worker_hourly_rate

        rate_info = resolve_worker_hourly_rate(conn, uid, oid)
        defaults = new_worker_payroll_defaults(hourly_rate=rate_info.get("hourly_rate"))
        ins = conn.cursor()
        ins.execute(
            """
            INSERT INTO payroll_worker_profiles
              (organization_id, user_id, worker_category, default_hourly_rate,
               default_overtime_rate, max_hours_per_week, overtime_threshold, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1)
            """,
            (
                oid,
                uid,
                cat,
                defaults["default_hourly_rate"],
                defaults["default_overtime_rate"],
                defaults["max_hours_per_week"],
                defaults["overtime_threshold"],
            ),
        )
        c.execute(
            "SELECT * FROM payroll_worker_profiles WHERE organization_id=%s AND user_id=%s",
            (oid, uid),
        )
        row = c.fetchone()
    elif sync_category and row.get("worker_category") != cat:
        conn.cursor().execute(
            "UPDATE payroll_worker_profiles SET worker_category=%s WHERE id=%s",
            (cat, int(row["id"])),
        )
        row["worker_category"] = cat
    row = dict(row or {})
    if is_blank_rate(row.get("default_hourly_rate")):
        from backend.payroll_workflow import resolve_worker_hourly_rate

        resolved = resolve_worker_hourly_rate(conn, uid, oid)
        if resolved.get("hourly_rate"):
            row["default_hourly_rate"] = resolved["hourly_rate"]
            row["hourly_rate_source"] = resolved.get("rate_source")
            if row.get("id"):
                conn.cursor().execute(
                    """
                    UPDATE payroll_worker_profiles
                    SET default_hourly_rate=%s
                    WHERE id=%s AND organization_id=%s
                      AND (default_hourly_rate IS NULL OR default_hourly_rate <= 0)
                    """,
                    (resolved["hourly_rate"], int(row["id"]), oid),
                )
    if row.get("id"):
        ensure_worker_profile_payroll_defaults(conn, oid, int(row["id"]))
        c.execute(
            "SELECT * FROM payroll_worker_profiles WHERE organization_id=%s AND user_id=%s",
            (oid, uid),
        )
        row = dict(c.fetchone() or row)
    row["display_name"] = _worker_display_name(c, uid)
    row["worker_profile_id"] = row.get("id")
    row["worker_name"] = row["display_name"]
    row["worker_category_label"] = {"w2": "W-2", "contractor_1099": "1099", "temp": "Temp"}.get(
        str(row.get("worker_category")), str(row.get("worker_category"))
    )
    return json_safe(row)


def list_workers(conn, organization_id: int, *, active_only: bool = True) -> list[dict[str, Any]]:
    from backend.payroll_worker_defaults import backfill_payroll_worker_defaults

    seed_schedule_defaults(conn.cursor(), organization_id)
    backfill_payroll_worker_defaults(conn, int(organization_id))
    c = _cursor(conn)
    oid = int(organization_id)
    user_filter = _users_list_filter(c)
    c.execute(
        f"""
        SELECT DISTINCT u.id AS user_id
        FROM users u
        LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
        WHERE u.organization_id=%s AND {user_filter}
        ORDER BY u.id
        """,
        (oid,),
    )
    user_ids = [int(r["user_id"]) for r in c.fetchall() if r.get("user_id")]
    out = []
    for uid in user_ids:
        prof = ensure_worker_profile(conn, oid, uid)
        if active_only and not prof.get("active"):
            continue
        out.append(prof)
    return out


def get_worker_availability(conn, organization_id: int, worker_profile_id: int) -> dict[str, Any]:
    c = _cursor(conn)
    c.execute(
        """
        SELECT a.* FROM payroll_worker_availability a
        JOIN payroll_worker_profiles p ON p.id=a.worker_profile_id
        WHERE a.worker_profile_id=%s AND p.organization_id=%s
        ORDER BY a.day_of_week
        """,
        (int(worker_profile_id), int(organization_id)),
    )
    rows = [json_safe(r) for r in c.fetchall()]
    for r in rows:
        r["available_from"] = _time_to_str(_parse_time(r.get("available_from")))
        r["available_to"] = _time_to_str(_parse_time(r.get("available_to")))
    skill_active = _where_active(c, "payroll_worker_role_skills", "s")
    c.execute(
        f"""
        SELECT s.*, r.name AS role_name, ws.name AS work_stream_name
        FROM payroll_worker_role_skills s
        JOIN payroll_roles r ON r.id=s.role_id
        LEFT JOIN payroll_work_streams ws ON ws.id=s.work_stream_id
        WHERE s.worker_profile_id=%s AND {skill_active}
        """,
        (int(worker_profile_id),),
    )
    skills = [json_safe(r) for r in c.fetchall()]
    return {"availability": rows, "role_skills": skills}


def _user_geofence_ids(conn, user_id: int) -> list[int]:
    c = _cursor(conn)
    if not table_exists(c, "user_geofences"):
        return []
    ug_active = _where_active(c, "user_geofences")
    c.execute(
        f"SELECT geofence_id FROM user_geofences WHERE user_id=%s AND {ug_active}",
        (int(user_id),),
    )
    return [int(r["geofence_id"]) for r in c.fetchall() if r.get("geofence_id") is not None]


def worker_profile_gaps(
    worker: dict, *, availability: Optional[list] = None, role_skills: Optional[list] = None
) -> list[str]:
    """Profile completeness checks — source of truth is payroll_worker_profiles + skills."""
    gaps: list[str] = []
    if not worker:
        return gaps
    if not worker.get("active"):
        gaps.append("Worker inactive")
    if not worker.get("worker_category"):
        gaps.append("Payroll category missing")
    if _d(worker.get("default_hourly_rate") or 0) <= 0:
        gaps.append("Missing hourly rate")
    skills = [s for s in (role_skills or worker.get("role_skills") or []) if s.get("active", True)]
    if not skills:
        gaps.append("No role skill assigned")
    has_stream_skill = any(s.get("work_stream_id") for s in skills)
    stream_ok = (
        has_stream_skill
        or worker.get("can_work_rinse")
        or worker.get("can_work_drop_off")
        or worker.get("can_work_both")
    )
    if not stream_ok:
        gaps.append("No work stream skill assigned")
    avail = availability if availability is not None else worker.get("availability") or []
    if not avail:
        gaps.append("No availability set")
    elif not any(not a.get("unavailable_flag") for a in avail):
        gaps.append("No availability set")
    if not worker.get("preferred_shift_id"):
        gaps.append("No preferred shift")
    return gaps


PROFILE_COMPLETENESS_CHECKS = (
    ("active", "Worker inactive", lambda w, _a, _s: bool(w.get("active"))),
    ("category", "Payroll category missing", lambda w, _a, _s: bool(w.get("worker_category"))),
    ("rate", "Missing hourly rate", lambda w, _a, _s: _d(w.get("default_hourly_rate") or 0) > 0),
    ("role_skill", "No role skill assigned", lambda w, _a, skills: bool([s for s in skills if s.get("active", True)])),
    (
        "stream_skill",
        "No work stream skill assigned",
        lambda w, _a, skills: bool(
            any(s.get("work_stream_id") for s in skills if s.get("active", True))
            or w.get("can_work_rinse")
            or w.get("can_work_drop_off")
            or w.get("can_work_both")
        ),
    ),
    (
        "availability",
        "No availability set",
        lambda w, avail, _s: bool(avail)
        and any(not a.get("unavailable_flag") for a in avail),
    ),
    ("preferred_shift", "No preferred shift", lambda w, _a, _s: bool(w.get("preferred_shift_id"))),
    (
        "performance",
        "No performance mapping",
        lambda w, _a, _s: bool((w.get("performance_preview") or {}).get("available")),
    ),
)


def profile_completeness(worker: dict) -> dict[str, Any]:
    avail = worker.get("availability") or []
    skills = worker.get("role_skills") or []
    missing: list[str] = []
    passed = 0
    for _key, label, fn in PROFILE_COMPLETENESS_CHECKS:
        if fn(worker, avail, skills):
            passed += 1
        else:
            missing.append(label)
    total = len(PROFILE_COMPLETENESS_CHECKS)
    score = int(round(100 * passed / total)) if total else 0
    return {"score": score, "missing": missing, "passed": passed, "total": total}


def scheduling_readiness_badge(worker: dict) -> dict[str, Any]:
    gaps = worker.get("profile_gaps") or worker_profile_gaps(worker)
    if not worker.get("active"):
        return {"label": "Inactive", "color": "default", "ready": False, "gaps": gaps}
    gap_set = set(gaps)
    if "Missing hourly rate" in gap_set:
        return {"label": "Missing Rate", "color": "error", "ready": False, "gaps": gaps}
    if "No availability set" in gap_set:
        return {"label": "Missing Availability", "color": "warning", "ready": False, "gaps": gaps}
    if "No role skill assigned" in gap_set:
        return {"label": "Missing Role", "color": "warning", "ready": False, "gaps": gaps}
    if "No work stream skill assigned" in gap_set:
        return {"label": "Missing Stream", "color": "warning", "ready": False, "gaps": gaps}
    if gaps:
        return {"label": "Needs Review", "color": "info", "ready": False, "gaps": gaps}
    return {"label": "Ready for Scheduling", "color": "success", "ready": True, "gaps": []}


def get_worker_by_user_id(conn, organization_id: int, user_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    uid = int(user_id)
    prof = ensure_worker_profile(conn, oid, uid)
    return enrich_worker_for_scheduling(conn, oid, prof)


def get_scheduling_profile_bundle(conn, organization_id: int, user_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    worker = get_worker_by_user_id(conn, oid, user_id)
    settings = get_org_schedule_settings(conn, oid)
    c = _cursor(conn)
    gf_active = _where_active(c, "geofences")
    c.execute(
        f"SELECT id, name FROM geofences WHERE organization_id=%s AND {gf_active} ORDER BY name",
        (oid,),
    )
    geofences = [json_safe(r) for r in c.fetchall()]
    assigned = worker.get("geofence_ids") or []
    worker["assigned_locations"] = [g for g in geofences if int(g["id"]) in assigned]
    worker["profile_gaps"] = worker_profile_gaps(worker)
    completeness = profile_completeness(worker)
    readiness = scheduling_readiness_badge(worker)
    return json_safe(
        {
            "worker": worker,
            "settings": settings,
            "geofences": geofences,
            "completeness": completeness,
            "readiness": readiness,
        }
    )


def save_scheduling_profile(conn, organization_id: int, user_id: int, body: dict) -> dict[str, Any]:
    oid = int(organization_id)
    uid = int(user_id)
    prof = ensure_worker_profile(conn, oid, uid)
    wpid = int(prof["id"])
    c = _cursor(conn)
    profile_fields = {}
    for fld in (
        "default_hourly_rate",
        "default_overtime_rate",
        "max_hours_per_week",
        "overtime_threshold",
        "can_work_rinse",
        "can_work_drop_off",
        "can_work_both",
        "preferred_shift_id",
        "preferred_role_id",
        "notes",
        "active",
    ):
        if fld in body:
            profile_fields[fld] = body[fld]
    if profile_fields:
        sets = []
        params = []
        for fld, val in profile_fields.items():
            if fld.startswith("can_work_") or fld == "active":
                val = 1 if val else 0
            elif fld in ("preferred_shift_id", "preferred_role_id"):
                val = _nullable_int(val)
            elif fld in (
                "default_hourly_rate",
                "default_overtime_rate",
                "max_hours_per_week",
                "overtime_threshold",
            ):
                val = _nullable_decimal(val)
            elif fld == "notes" and val == "":
                val = None
            sets.append(f"{fld}=%s")
            params.append(val)
        params.extend([wpid, oid])
        c.execute(
            f"UPDATE payroll_worker_profiles SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
            tuple(params),
        )
        if "default_hourly_rate" in profile_fields and profile_fields["default_hourly_rate"] is not None:
            prof["default_hourly_rate"] = profile_fields["default_hourly_rate"]
    save_body = {
        k: body[k]
        for k in (
            "availability",
            "role_skills",
            "default_hourly_rate",
            "default_overtime_rate",
            "max_hours_per_week",
            "overtime_threshold",
            "can_work_rinse",
            "can_work_drop_off",
            "can_work_both",
            "preferred_shift_id",
            "preferred_role_id",
            "notes",
            "active",
        )
        if k in body
    }
    if save_body:
        save_worker_availability(conn, oid, wpid, save_body)
    return get_scheduling_profile_bundle(conn, oid, uid)


def list_workers_enriched(conn, organization_id: int, *, active_only: bool = False) -> list[dict[str, Any]]:
    """Workers with scheduling readiness for People list / filters."""
    out = []
    for w in list_workers(conn, organization_id, active_only=active_only):
        enriched = enrich_worker_for_scheduling(conn, int(organization_id), w)
        enriched["profile_gaps"] = worker_profile_gaps(enriched)
        enriched["completeness"] = profile_completeness(enriched)
        enriched["readiness"] = scheduling_readiness_badge(enriched)
        out.append(enriched)
    return out


def enrich_worker_for_scheduling(conn, organization_id: int, worker: dict) -> dict[str, Any]:
    """Attach profile fields used by the planner — never duplicate in schedule forms."""
    c = _cursor(conn)
    uid = int(worker["user_id"])
    c.execute(
        "SELECT mobile, first_name, last_name FROM payroll_profiles WHERE user_id=%s LIMIT 1",
        (uid,),
    )
    pp = c.fetchone() or {}
    avail = get_worker_availability(conn, int(organization_id), int(worker["id"]))
    out = dict(worker)
    out["mobile"] = pp.get("mobile")
    out["geofence_ids"] = _user_geofence_ids(conn, uid)
    out["availability"] = avail.get("availability") or []
    out["role_skills"] = avail.get("role_skills") or []
    out["profile_gaps"] = worker_profile_gaps(out, availability=out["availability"], role_skills=out["role_skills"])
    out["performance_preview"] = get_performance_preview(conn, int(organization_id), uid)
    out["completeness"] = profile_completeness(out)
    out["readiness"] = scheduling_readiness_badge(out)
    return json_safe(out)


def _lookup_name(c, table: str, row_id: Optional[int]) -> Optional[str]:
    if not row_id:
        return None
    c.execute(f"SELECT name FROM {table} WHERE id=%s LIMIT 1", (int(row_id),))
    return (c.fetchone() or {}).get("name")


def apply_profile_to_entry(
    conn, organization_id: int, entry: dict, worker_profile: dict
) -> dict[str, Any]:
    """
    Pull rate + snapshot labels from worker profile at save time.
    Client-sent rate/category fields are ignored — profile is source of truth.
    """
    from backend.payroll_workflow import resolve_worker_hourly_rate

    c = _cursor(conn)
    oid = int(organization_id)
    prof = dict(worker_profile)
    uid = int(prof["user_id"])
    merged = dict(entry)
    rate = prof.get("default_hourly_rate")
    if rate is None or _d(rate) <= 0:
        rate = resolve_worker_hourly_rate(conn, uid, oid).get("hourly_rate")
    rate_d = _d(rate or 0)
    merged["hourly_rate_snapshot"] = _q2(rate_d) if rate_d > 0 else None
    hours = _d(merged.get("scheduled_hours") or 0)
    if hours > 0 and rate_d > 0:
        merged["estimated_cost"] = _q2(hours * rate_d)
    cat = prof.get("worker_category") or worker_category_for_user(conn, uid)
    merged["worker_category_snapshot"] = str(cat)[:32] if cat else None
    merged["shift_snapshot"] = _lookup_name(c, "payroll_shifts", merged.get("shift_id"))
    merged["role_snapshot"] = _lookup_name(c, "payroll_roles", merged.get("role_id"))
    merged["work_stream_snapshot"] = _lookup_name(c, "payroll_work_streams", merged.get("work_stream_id"))
    return merged


def save_worker_availability(
    conn, organization_id: int, worker_profile_id: int, body: dict
) -> dict[str, Any]:
    c = conn.cursor()
    oid = int(organization_id)
    wpid = int(worker_profile_id)
    c.execute(
        "SELECT id FROM payroll_worker_profiles WHERE id=%s AND organization_id=%s",
        (wpid, oid),
    )
    if not c.fetchone():
        raise ValueError("Worker profile not found")
    profile_update_keys = (
        "max_hours_per_week",
        "overtime_threshold",
        "can_work_rinse",
        "can_work_drop_off",
        "can_work_both",
        "preferred_shift_id",
        "preferred_role_id",
        "notes",
        "default_hourly_rate",
        "default_overtime_rate",
        "active",
    )
    if any(k in body for k in profile_update_keys):
        sets = []
        params = []
        for fld in profile_update_keys:
            if fld in body:
                val = body[fld]
                if fld.startswith("can_work_") or fld == "active":
                    val = 1 if val else 0
                elif fld in ("preferred_shift_id", "preferred_role_id"):
                    val = _nullable_int(val)
                elif fld in (
                    "default_hourly_rate",
                    "default_overtime_rate",
                    "max_hours_per_week",
                    "overtime_threshold",
                ):
                    val = _nullable_decimal(val)
                elif fld == "notes" and val == "":
                    val = None
                sets.append(f"{fld}=%s")
                params.append(val)
        if sets:
            params.extend([wpid, oid])
            c.execute(
                f"UPDATE payroll_worker_profiles SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
                tuple(params),
            )
    for row in body.get("availability") or []:
        if not isinstance(row, dict):
            continue
        dow = int(row.get("day_of_week", 0))
        c.execute(
            """
            INSERT INTO payroll_worker_availability
              (worker_profile_id, day_of_week, available_from, available_to,
               preferred_shift_id, unavailable_flag, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              available_from=VALUES(available_from),
              available_to=VALUES(available_to),
              preferred_shift_id=VALUES(preferred_shift_id),
              unavailable_flag=VALUES(unavailable_flag),
              notes=VALUES(notes)
            """,
            (
                wpid,
                dow,
                row.get("available_from") or None,
                row.get("available_to") or None,
                _nullable_int(row.get("preferred_shift_id")),
                1 if row.get("unavailable_flag") else 0,
                row.get("notes") or None,
            ),
        )
    for skill in body.get("role_skills") or []:
        if not isinstance(skill, dict):
            continue
        if not skill.get("role_id"):
            continue
        c.execute(
            """
            INSERT INTO payroll_worker_role_skills
              (worker_profile_id, role_id, work_stream_id, skill_level, active)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE skill_level=VALUES(skill_level), active=VALUES(active)
            """,
            (
                wpid,
                int(skill["role_id"]),
                _nullable_int(skill.get("work_stream_id")),
                int(skill.get("skill_level") or 1),
                1 if skill.get("active", True) else 0,
            ),
        )
    return get_worker_availability(conn, organization_id, wpid)


def _overtime_threshold(conn, organization_id: int, worker_profile: dict) -> Decimal:
    if worker_profile.get("overtime_threshold") is not None:
        return _d(worker_profile["overtime_threshold"])
    c = _cursor(conn)
    c.execute(
        "SELECT overtime_threshold_hours FROM payroll_schedule_org_settings WHERE organization_id=%s",
        (int(organization_id),),
    )
    row = c.fetchone() or {}
    return _d(row.get("overtime_threshold_hours") or 40)


def _approved_hours_week(conn, organization_id: int, user_id: int, week_start: date, week_end: date) -> Decimal:
    c = _cursor(conn)
    if not table_exists(c, "shift_sessions"):
        return Decimal("0")
    has_org = True
    try:
        from backend.ta_helpers import table_has_column

        has_org = table_has_column(c, "shift_sessions", "organization_id")
        has_approved = table_has_column(c, "shift_sessions", "payroll_hours_approved")
    except Exception:
        has_approved = False
    org_sql = " AND s.organization_id=%s" if has_org else ""
    params: list[Any] = [int(user_id), week_start.isoformat(), week_end.isoformat()]
    if has_org:
        params.append(int(organization_id))
    c.execute(
        f"""
        SELECT COALESCE(SUM(
          CASE
            WHEN s.clock_out_at IS NOT NULL THEN
              GREATEST(0, TIMESTAMPDIFF(SECOND, s.clock_in_at, s.clock_out_at)
                - COALESCE((SELECT SUM(TIMESTAMPDIFF(SECOND, b.start_at, COALESCE(b.end_at, s.clock_out_at)))
                    FROM shift_breaks b WHERE b.session_id=s.id), 0))
            ELSE 0
          END
        ), 0) AS secs
        FROM shift_sessions s
        WHERE s.user_id=%s
          AND DATE(s.clock_in_at) BETWEEN %s AND %s
          {org_sql}
        """,
        tuple(params),
    )
    row = c.fetchone() or {}
    secs = int(row.get("secs") or 0)
    if has_approved:
        c.execute(
            f"""
            SELECT COALESCE(SUM(payroll_hours_approved), 0) AS hrs
            FROM shift_sessions s
            WHERE s.user_id=%s AND DATE(s.clock_in_at) BETWEEN %s AND %s
              AND payroll_hours_approved IS NOT NULL {org_sql}
            """,
            tuple(params),
        )
        appr = c.fetchone() or {}
        if appr.get("hrs"):
            return _d(appr["hrs"])
    return _d(secs / 3600.0)


def _scheduled_hours_week(
    conn, organization_id: int, worker_profile_id: int, week_start: date, week_end: date
) -> Decimal:
    c = _cursor(conn)
    c.execute(
        """
        SELECT COALESCE(SUM(scheduled_hours), 0) AS hrs
        FROM payroll_schedule_entries
        WHERE organization_id=%s AND worker_profile_id=%s
          AND work_date BETWEEN %s AND %s
          AND status NOT IN ('cancelled', 'replaced')
        """,
        (int(organization_id), int(worker_profile_id), week_start, week_end),
    )
    row = c.fetchone() or {}
    return _d(row.get("hrs"))


def worker_week_hours(conn, organization_id: int, worker_profile: dict, week_start: date) -> dict[str, Any]:
    week_end = week_start + timedelta(days=6)
    uid = int(worker_profile["user_id"])
    wpid = int(worker_profile["id"])
    scheduled = _scheduled_hours_week(conn, organization_id, wpid, week_start, week_end)
    approved = _approved_hours_week(conn, organization_id, uid, week_start, week_end)
    ot_threshold = _overtime_threshold(conn, organization_id, worker_profile)
    max_week = _d(worker_profile.get("max_hours_per_week")) if worker_profile.get("max_hours_per_week") else None
    projected = max(scheduled, approved)
    remaining = ot_threshold - projected
    at_risk = projected > ot_threshold
    if max_week and scheduled > max_week:
        at_risk = True
    return json_safe(
        {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "scheduled_hours": _q2(scheduled),
            "approved_hours": _q2(approved),
            "projected_hours": _q2(projected),
            "overtime_threshold": _q2(ot_threshold),
            "hours_remaining_before_overtime": _q2(max(Decimal("0"), remaining)),
            "overtime_risk": at_risk,
            "max_hours_per_week": _q2(max_week) if max_week else None,
        }
    )


def _enrich_entry(conn, organization_id: int, row: dict) -> dict[str, Any]:
    c = _cursor(conn)
    out = dict(row)
    wpid = int(out["worker_profile_id"])
    c.execute("SELECT * FROM payroll_worker_profiles WHERE id=%s", (wpid,))
    prof = c.fetchone() or {}
    out["user_id"] = prof.get("user_id")
    out["worker_category"] = prof.get("worker_category")
    out["worker_category_label"] = {"w2": "W-2", "contractor_1099": "1099", "temp": "Temp"}.get(
        str(prof.get("worker_category")), str(prof.get("worker_category"))
    )
    out["worker_name"] = _worker_display_name(c, int(prof.get("user_id") or 0))
    out["start_time"] = _time_to_str(_parse_time(out.get("start_time")))
    out["end_time"] = _time_to_str(_parse_time(out.get("end_time")))
    for tbl, key, label in (
        ("payroll_shifts", "shift_id", "shift_name"),
        ("payroll_work_streams", "work_stream_id", "work_stream_name"),
        ("payroll_roles", "role_id", "role_name"),
        ("geofences", "geofence_id", "location_name"),
    ):
        fid = out.get(key)
        if fid:
            c.execute(f"SELECT name FROM {tbl} WHERE id=%s LIMIT 1", (int(fid),))
            nm = (c.fetchone() or {}).get("name")
            out[label] = nm
    ws = date.fromisoformat(str(out["work_date"])[:10])
    week_start, _ = payroll_week_bounds(conn, ws, organization_id)
    out["week_hours"] = worker_week_hours(conn, organization_id, prof, week_start)
    out["warnings"] = check_schedule_warnings(conn, organization_id, out, prof)
    out["performance_preview"] = get_performance_preview(conn, organization_id, int(prof.get("user_id") or 0))
    return json_safe(out)


def check_schedule_warnings(
    conn, organization_id: int, entry: dict, worker_profile: Optional[dict] = None
) -> list[str]:
    warnings: list[str] = []
    if not worker_profile:
        c = _cursor(conn)
        c.execute(
            "SELECT * FROM payroll_worker_profiles WHERE id=%s",
            (int(entry["worker_profile_id"]),),
        )
        worker_profile = c.fetchone() or {}
    work_date = date.fromisoformat(str(entry["work_date"])[:10])
    dow = work_date.weekday()
    c = _cursor(conn)
    c.execute(
        """
        SELECT * FROM payroll_worker_availability
        WHERE worker_profile_id=%s AND day_of_week=%s LIMIT 1
        """,
        (int(worker_profile["id"]), dow),
    )
    avail = c.fetchone()
    if avail and avail.get("unavailable_flag"):
        warnings.append("Worker marked unavailable on this day")
    elif avail and avail.get("available_from") and avail.get("available_to"):
        st = _parse_time(entry.get("start_time"))
        et = _parse_time(entry.get("end_time"))
        af = _parse_time(avail.get("available_from"))
        at = _parse_time(avail.get("available_to"))
        if st and et and af and at and (st < af or et > at):
            warnings.append("Shift times outside worker availability window")
    stream_id = entry.get("work_stream_id")
    if stream_id:
        c.execute("SELECT name FROM payroll_work_streams WHERE id=%s", (int(stream_id),))
        sn = ((c.fetchone() or {}).get("name") or "").lower()
        if "rinse" in sn and not worker_profile.get("can_work_rinse"):
            warnings.append("Worker not flagged for Rinse work stream")
        if "drop" in sn and not worker_profile.get("can_work_drop_off"):
            warnings.append("Worker not flagged for Drop Off work stream")
    role_id = entry.get("role_id")
    skill_active = _where_active(c, "payroll_worker_role_skills")
    if role_id:
        c.execute(
            f"""
            SELECT 1 FROM payroll_worker_role_skills
            WHERE worker_profile_id=%s AND role_id=%s AND {skill_active} LIMIT 1
            """,
            (int(worker_profile["id"]), int(role_id)),
        )
        if not c.fetchone():
            warnings.append("Worker has no active skill record for this role")
        elif stream_id:
            c.execute(
                f"""
                SELECT 1 FROM payroll_worker_role_skills
                WHERE worker_profile_id=%s AND role_id=%s AND work_stream_id=%s AND {skill_active} LIMIT 1
                """,
                (int(worker_profile["id"]), int(role_id), int(stream_id)),
            )
            if not c.fetchone():
                c.execute(
                    f"""
                    SELECT 1 FROM payroll_worker_role_skills
                    WHERE worker_profile_id=%s AND role_id=%s AND work_stream_id IS NULL AND {skill_active} LIMIT 1
                    """,
                    (int(worker_profile["id"]), int(role_id)),
                )
                if not c.fetchone():
                    warnings.append("Worker has no skill record for this role and work stream")
    pref_shift = worker_profile.get("preferred_shift_id")
    if pref_shift and entry.get("shift_id") and int(pref_shift) != int(entry["shift_id"]):
        warnings.append("Shift differs from worker preferred shift")
    for gap in worker_profile_gaps(worker_profile):
        if gap not in warnings:
            warnings.append(gap)
    week_start, _ = payroll_week_bounds(conn, work_date, organization_id)
    wh = worker_week_hours(conn, organization_id, worker_profile, week_start)
    entry_hours = _d(entry.get("scheduled_hours") or 0)
    if wh["overtime_risk"] or _d(wh["projected_hours"]) + entry_hours > _d(wh["overtime_threshold"]):
        warnings.append("Overtime risk — projected hours exceed threshold")
    return warnings


def get_performance_preview(conn, organization_id: int, user_id: int) -> dict[str, Any]:
    c = _cursor(conn)
    map_active = _where_active(c, "rinse_folding_user_map")
    c.execute(
        f"""
        SELECT rinse_user_name FROM rinse_folding_user_map
        WHERE organization_id=%s AND user_id=%s AND {map_active} LIMIT 1
        """,
        (int(organization_id), int(user_id)),
    )
    mapping = c.fetchone()
    if not mapping:
        return {"available": False, "message": "No performance data yet"}
    rinse_name = mapping.get("rinse_user_name")
    try:
        from backend.rinse_folding_user_productivity import load_user_performance_rows

        end = date.today()
        start = end - timedelta(days=30)
        rows = load_user_performance_rows(c, int(organization_id), user_name=rinse_name, period_start=start, period_end=end)
        if not rows:
            return {"available": False, "message": "No performance data yet", "rinse_user_name": rinse_name}
        bags = len(rows)
        def _perf_row_val(row, key, alt=None):
            if isinstance(row, dict):
                return row.get(key) if row.get(key) is not None else (row.get(alt) if alt else None)
            return None

        total_lbs = sum(
            float(_perf_row_val(r, "weight_lbs", "registry_weight_num") or 0) for r in rows
        )
        total_sec = sum(
            int(_perf_row_val(r, "duration_seconds") or 0)
            for r in rows
            if _perf_row_val(r, "duration_seconds")
        )
        hours = total_sec / 3600.0 if total_sec > 0 else 0
        return json_safe(
            {
                "available": True,
                "rinse_user_name": rinse_name,
                "avg_bags_per_hour": round(bags / hours, 2) if hours > 0 else None,
                "avg_lbs_per_hour": round(total_lbs / hours, 2) if hours > 0 else None,
                "bags_30d": bags,
                "period_days": 30,
                "attendance_reliability": None,
                "recent_issues": [],
                "role_fit": None,
            }
        )
    except Exception:
        return {"available": False, "message": "No performance data yet"}


def list_schedule_entries(
    conn, organization_id: int, *, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    seed_schedule_defaults(conn.cursor(), organization_id)
    c = _cursor(conn)
    c.execute(
        """
        SELECT e.* FROM payroll_schedule_entries e
        WHERE e.organization_id=%s AND e.work_date BETWEEN %s AND %s
        ORDER BY e.work_date, e.start_time, e.id
        """,
        (int(organization_id), start_date, end_date),
    )
    return [_enrich_entry(conn, organization_id, dict(r)) for r in c.fetchall()]


def create_schedule_entry(conn, organization_id: int, body: dict, *, created_by: Optional[int] = None) -> dict:
    from backend.payroll_schedule_planner import ensure_payroll_schedule_v2

    seed_schedule_defaults(conn.cursor(), organization_id)
    ensure_payroll_schedule_v2(conn.cursor())
    oid = int(organization_id)
    wpid = int(body["worker_profile_id"])
    c = _cursor(conn)
    c.execute("SELECT * FROM payroll_worker_profiles WHERE id=%s AND organization_id=%s", (wpid, oid))
    prof = c.fetchone()
    if not prof and body.get("user_id"):
        prof = ensure_worker_profile(conn, oid, int(body["user_id"]))
    if not prof:
        raise ValueError("worker_profile_id required")
    shift_id = int(body["shift_id"])
    c.execute("SELECT * FROM payroll_shifts WHERE id=%s AND organization_id=%s", (shift_id, oid))
    shift = c.fetchone()
    if not shift:
        raise ValueError("Invalid shift")
    start_t = _parse_time(body.get("start_time") or shift.get("start_time_default"))
    end_t = _parse_time(body.get("end_time") or shift.get("end_time_default"))
    if not start_t or not end_t:
        raise ValueError("start_time and end_time required")
    break_m = int(body.get("break_minutes") or 0)
    hours = compute_scheduled_hours(start_t, end_t, break_m)
    body_merged = apply_profile_to_entry(
        conn,
        oid,
        {
            **body,
            "start_time": _time_to_str(start_t),
            "end_time": _time_to_str(end_t),
            "break_minutes": break_m,
            "scheduled_hours": _q2(hours),
        },
        prof,
    )
    rate_d = _d(body_merged.get("hourly_rate_snapshot") or 0)
    cost = body_merged.get("estimated_cost")
    status = str(body.get("status") or "scheduled")
    if status not in SCHEDULE_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    ins = conn.cursor()
    ins.execute(
        """
        INSERT INTO payroll_schedule_entries (
          organization_id, worker_profile_id, work_date, shift_id, work_stream_id, role_id,
          geofence_id, start_time, end_time, break_minutes, scheduled_hours,
          hourly_rate_snapshot, worker_category_snapshot, role_snapshot, work_stream_snapshot, shift_snapshot,
          estimated_cost, status, replacement_for_schedule_id, notes,
          created_by, publish_status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            oid,
            wpid,
            body["work_date"],
            shift_id,
            body.get("work_stream_id"),
            body.get("role_id"),
            body.get("geofence_id"),
            _time_to_str(start_t),
            _time_to_str(end_t),
            break_m,
            _q2(hours),
            body_merged.get("hourly_rate_snapshot"),
            body_merged.get("worker_category_snapshot"),
            body_merged.get("role_snapshot"),
            body_merged.get("work_stream_snapshot"),
            body_merged.get("shift_snapshot"),
            cost,
            status,
            body.get("replacement_for_schedule_id"),
            body.get("notes"),
            created_by,
            str(body.get("publish_status") or "draft"),
        ),
    )
    entry_id = int(ins.lastrowid)
    c.execute("SELECT * FROM payroll_schedule_entries WHERE id=%s", (entry_id,))
    return _enrich_entry(conn, organization_id, dict(c.fetchone()))


def update_schedule_entry(conn, organization_id: int, entry_id: int, body: dict) -> dict:
    c = _cursor(conn)
    c.execute(
        "SELECT * FROM payroll_schedule_entries WHERE id=%s AND organization_id=%s",
        (int(entry_id), int(organization_id)),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Schedule entry not found")
    merged = dict(row)
    merged.update({k: v for k, v in body.items() if v is not None})
    start_t = _parse_time(merged.get("start_time"))
    end_t = _parse_time(merged.get("end_time"))
    break_m = int(merged.get("break_minutes") or 0)
    if start_t and end_t:
        hours = compute_scheduled_hours(start_t, end_t, break_m)
        merged["scheduled_hours"] = _q2(hours)
    c.execute("SELECT * FROM payroll_worker_profiles WHERE id=%s", (int(merged["worker_profile_id"]),))
    prof = c.fetchone() or {}
    if prof:
        merged = apply_profile_to_entry(conn, organization_id, merged, prof)
    if body.get("status") and body["status"] not in SCHEDULE_STATUSES:
        raise ValueError("Invalid status")
    upd = conn.cursor()
    fields = (
        "work_date",
        "shift_id",
        "work_stream_id",
        "role_id",
        "geofence_id",
        "start_time",
        "end_time",
        "break_minutes",
        "scheduled_hours",
        "hourly_rate_snapshot",
        "worker_category_snapshot",
        "role_snapshot",
        "work_stream_snapshot",
        "shift_snapshot",
        "estimated_cost",
        "status",
        "replacement_for_schedule_id",
        "notes",
        "publish_status",
    )
    sets = []
    params = []
    for f in fields:
        if f in body or (f in merged and f in ("scheduled_hours", "estimated_cost")):
            val = merged.get(f)
            if f in ("start_time", "end_time") and val:
                val = _time_to_str(_parse_time(val))
            sets.append(f"{f}=%s")
            params.append(val)
    if sets:
        params.extend([int(entry_id), int(organization_id)])
        upd.execute(
            f"UPDATE payroll_schedule_entries SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
            tuple(params),
        )
    c.execute("SELECT * FROM payroll_schedule_entries WHERE id=%s", (int(entry_id),))
    return _enrich_entry(conn, organization_id, dict(c.fetchone()))


def delete_schedule_entry(conn, organization_id: int, entry_id: int) -> None:
    conn.cursor().execute(
        "DELETE FROM payroll_schedule_entries WHERE id=%s AND organization_id=%s",
        (int(entry_id), int(organization_id)),
    )


def day_summary(conn, organization_id: int, work_date: str, settings: dict) -> dict[str, Any]:
    entries = list_schedule_entries(conn, organization_id, start_date=work_date, end_date=work_date)
    active = [e for e in entries if e.get("status") not in ("cancelled", "replaced")]
    shift_names = {s["id"]: s["name"] for s in settings.get("shifts") or []}
    stream_names = {s["id"]: s["name"] for s in settings.get("work_streams") or []}
    role_names = {r["id"]: r["name"] for r in settings.get("roles") or []}
    by_shift: dict[str, list] = {}
    ot_risk = 0
    for e in active:
        sn = e.get("shift_name") or shift_names.get(e.get("shift_id"), "Other")
        by_shift.setdefault(sn, []).append(e)
        if e.get("week_hours", {}).get("overtime_risk"):
            ot_risk += 1
    def _count_stream(keyword: str) -> int:
        return sum(
            1
            for e in active
            if keyword.lower() in str(e.get("work_stream_name") or "").lower()
        )

    def _count_role(keyword: str) -> int:
        return sum(
            1 for e in active if keyword.lower() in str(e.get("role_name") or "").lower()
        )

    morning = sum(len(v) for k, v in by_shift.items() if "morning" in k.lower())
    afternoon = sum(len(v) for k, v in by_shift.items() if "afternoon" in k.lower())
    return json_safe(
        {
            "work_date": work_date,
            "total_scheduled": len(active),
            "morning_scheduled": morning,
            "afternoon_scheduled": afternoon,
            "rinse_coverage": _count_stream("rinse") + _count_stream("both"),
            "drop_off_coverage": _count_stream("drop") + _count_stream("both"),
            "operator_coverage": _count_role("operator"),
            "folder_coverage": _count_role("folder"),
            "overtime_risk_count": ot_risk,
            "by_shift": by_shift,
            "entries": active,
        }
    )


def weekly_summary(conn, organization_id: int, week_start: str) -> dict[str, Any]:
    ws = date.fromisoformat(week_start[:10])
    we = ws + timedelta(days=6)
    settings = get_org_schedule_settings(conn, organization_id)
    entries = list_schedule_entries(
        conn, organization_id, start_date=ws.isoformat(), end_date=we.isoformat()
    )
    workers = list_workers(conn, organization_id)
    worker_map = {int(w["id"]): w for w in workers}
    rows = []
    for w in workers:
        wpid = int(w["id"])
        wh = worker_week_hours(conn, organization_id, w, ws)
        days: dict[str, list] = {}
        for e in entries:
            if int(e["worker_profile_id"]) != wpid:
                continue
            d = str(e["work_date"])[:10]
            days.setdefault(d, []).append(e)
        rows.append(
            {
                "worker_profile_id": wpid,
                "user_id": w["user_id"],
                "worker_name": w.get("display_name"),
                "worker_category": w.get("worker_category"),
                "worker_category_label": w.get("worker_category_label"),
                "week_hours": wh,
                "days": days,
                "performance_preview": get_performance_preview(conn, organization_id, int(w["user_id"])),
            }
        )
    return json_safe(
        {
            "week_start": ws.isoformat(),
            "week_end": we.isoformat(),
            "settings": settings,
            "workers": rows,
            "entries": entries,
        }
    )


def overtime_risk_report(conn, organization_id: int, week_start: str) -> dict[str, Any]:
    summary = weekly_summary(conn, organization_id, week_start)
    at_risk = [w for w in summary["workers"] if w.get("week_hours", {}).get("overtime_risk")]
    return json_safe(
        {
            "week_start": summary["week_start"],
            "week_end": summary["week_end"],
            "overtime_threshold": summary["settings"].get("overtime_threshold_hours"),
            "at_risk_workers": at_risk,
            "count": len(at_risk),
        }
    )


def replacement_suggestions(conn, organization_id: int, schedule_entry_id: int) -> dict[str, Any]:
    c = _cursor(conn)
    c.execute(
        "SELECT * FROM payroll_schedule_entries WHERE id=%s AND organization_id=%s",
        (int(schedule_entry_id), int(organization_id)),
    )
    entry = c.fetchone()
    if not entry:
        raise ValueError("Schedule entry not found")
    enriched = _enrich_entry(conn, organization_id, dict(entry))
    work_date = date.fromisoformat(str(entry["work_date"])[:10])
    week_start, _ = payroll_week_bounds(conn, work_date, organization_id)
    candidates = []
    for w in list_workers(conn, organization_id):
        if int(w["id"]) == int(entry["worker_profile_id"]):
            continue
        probe = dict(enriched)
        probe["worker_profile_id"] = w["id"]
        probe["scheduled_hours"] = entry.get("scheduled_hours")
        warnings = check_schedule_warnings(conn, organization_id, probe, w)
        if any("unavailable" in x.lower() for x in warnings):
            continue
        wh = worker_week_hours(conn, organization_id, w, week_start)
        add_hours = _d(entry.get("scheduled_hours"))
        projected_after = _d(wh["projected_hours"]) + add_hours
        score = 100
        skill_active = _where_active(c, "payroll_worker_role_skills")
        if entry.get("role_id"):
            c.execute(
                f"""
                SELECT 1 FROM payroll_worker_role_skills
                WHERE worker_profile_id=%s AND role_id=%s AND {skill_active}
                """,
                (int(w["id"]), int(entry["role_id"])),
            )
            if c.fetchone():
                score += 30
            else:
                score -= 20
        if entry.get("work_stream_id"):
            c.execute(
                f"""
                SELECT 1 FROM payroll_worker_role_skills
                WHERE worker_profile_id=%s AND work_stream_id=%s AND {skill_active}
                """,
                (int(w["id"]), int(entry["work_stream_id"])),
            )
            if c.fetchone():
                score += 20
        if wh.get("overtime_risk") or projected_after > _d(wh["overtime_threshold"]):
            score -= 40
        else:
            score += int(float(wh.get("hours_remaining_before_overtime") or 0))
        perf = get_performance_preview(conn, organization_id, int(w["user_id"]))
        if perf.get("available"):
            score += 10
        role_match = "Yes"
        stream_match = "Yes"
        if entry.get("role_id"):
            c.execute(
                f"SELECT 1 FROM payroll_worker_role_skills WHERE worker_profile_id=%s AND role_id=%s AND {skill_active} LIMIT 1",
                (int(w["id"]), int(entry["role_id"])),
            )
            if not c.fetchone():
                role_match = "No"
        if entry.get("work_stream_id"):
            c.execute(
                f"SELECT 1 FROM payroll_worker_role_skills WHERE worker_profile_id=%s AND work_stream_id=%s AND {skill_active} LIMIT 1",
                (int(w["id"]), int(entry["work_stream_id"])),
            )
            if not c.fetchone():
                stream_match = "No"
        current_h = _d(wh.get("scheduled_hours") or wh.get("projected_hours"))
        ot_after = projected_after > _d(wh["overtime_threshold"])
        rec = "Best" if score >= 120 and not ot_after else ("Avoid" if ot_after else "Good")
        rate = _d(w.get("default_hourly_rate") or 0)
        reasons = [
            "Available: Yes",
            f"Role match: {role_match}",
            f"Stream match: {stream_match}",
            f"Current weekly hours: {_q2(current_h)}",
            f"After replacement: {_q2(projected_after)}",
            f"Overtime risk: {'Yes' if ot_after else 'No'}",
            f"Estimated added cost: ${_q2(add_hours * rate)}",
        ]
        candidates.append(
            json_safe(
                {
                    "worker_profile_id": w["id"],
                    "user_id": w["user_id"],
                    "worker_name": w.get("display_name"),
                    "worker_category": w.get("worker_category"),
                    "score": score,
                    "recommendation": rec,
                    "reasons": reasons,
                    "current_weekly_hours": _q2(current_h),
                    "week_hours": wh,
                    "projected_hours_after": _q2(projected_after),
                    "overtime_risk_after": ot_after,
                    "hourly_rate": _q2(rate) if rate > 0 else None,
                    "estimated_added_cost": _q2(add_hours * rate),
                    "performance_preview": perf,
                    "warnings": warnings,
                }
            )
        )
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return json_safe(
        {
            "entry": enriched,
            "suggestions": candidates[:10],
        }
    )
