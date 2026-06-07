"""
Interactive schedule planner: coverage gaps, suggestions, draft/publish, change log.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from backend.payroll_schedule import (
    _cursor,
    _d,
    _enrich_entry,
    _overtime_threshold,
    _parse_time,
    _q2,
    _time_to_str,
    _where_active,
    check_schedule_warnings,
    compute_scheduled_hours,
    ensure_payroll_schedule_tables,
    enrich_worker_for_scheduling,
    get_org_schedule_settings,
    get_performance_preview,
    get_worker_availability,
    list_schedule_entries,
    list_workers,
    seed_schedule_defaults,
)
from backend.payroll_identity import payroll_week_bounds
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column


FRONTEND_ONLY_KEYS = frozenset(
    {
        "_dirty",
        "_deleted",
        "worker_name",
        "shift_name",
        "work_stream_name",
        "role_name",
        "location_name",
        "worker_category",
        "worker_category_label",
        "week_hours",
        "warnings",
        "performance_preview",
        "week_stats",
        "display_name",
        "profile_gaps",
        "geofence_ids",
        "mobile",
        "availability",
        "role_skills",
    }
)


def _sanitize_entry_for_save(item: dict) -> dict:
    """Strip frontend-only fields before persisting."""
    return {k: v for k, v in dict(item).items() if k not in FRONTEND_ONLY_KEYS}


def _infer_change_action(body: dict, old: Optional[dict]) -> str:
    new_status = str(body.get("status") or (old or {}).get("status") or "")
    old_status = str((old or {}).get("status") or "")
    if new_status in ("sick", "absent", "no_show") and old_status not in ("sick", "absent", "no_show"):
        return "mark_absent"
    if body.get("replacement_for_schedule_id"):
        return "replace_worker"
    return "draft_update"


def count_published_entries(conn, organization_id: int, start_date: str, end_date: str) -> int:
    ensure_payroll_schedule_v2(conn.cursor())
    c = _cursor(conn)
    c.execute(
        """
        SELECT COUNT(*) AS n FROM payroll_schedule_entries
        WHERE organization_id=%s AND work_date BETWEEN %s AND %s
          AND publish_status='published' AND status NOT IN ('cancelled', 'replaced')
        """,
        (int(organization_id), start_date, end_date),
    )
    row = c.fetchone() or {}
    return int(row.get("n") or 0)


def _ensure_active_columns(cursor) -> None:
    """Add `active` on planning tables when legacy prod schema omitted it."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    for table in (
        "payroll_shifts",
        "payroll_work_streams",
        "payroll_roles",
        "payroll_worker_profiles",
        "payroll_worker_role_skills",
        "payroll_schedule_coverage_targets",
    ):
        if table_exists(c, table) and not table_has_column(c, table, "active"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN active TINYINT(1) NOT NULL DEFAULT 1")
    invalidate_schema_cache()


def ensure_payroll_schedule_v2(cursor) -> None:
    ensure_payroll_schedule_tables(cursor)
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    _ensure_active_columns(c)
    cols = [
        ("payroll_schedule_org_settings", "underused_hours_threshold", "DECIMAL(6,2) NOT NULL DEFAULT 15.00"),
        ("payroll_schedule_org_settings", "heavy_hours_threshold", "DECIMAL(6,2) NOT NULL DEFAULT 35.00"),
        ("payroll_schedule_org_settings", "target_hours_per_week", "DECIMAL(6,2) NOT NULL DEFAULT 32.00"),
        ("payroll_schedule_org_settings", "payment_day_of_week", "TINYINT NOT NULL DEFAULT 6 COMMENT '0=Mon..6=Sun'"),
        ("payroll_schedule_entries", "publish_status", "VARCHAR(16) NOT NULL DEFAULT 'draft'"),
        ("payroll_schedule_entries", "published_at", "TIMESTAMP NULL"),
        ("payroll_schedule_entries", "published_by", "INT NULL"),
        ("payroll_schedule_entries", "worker_category_snapshot", "VARCHAR(32) NULL"),
        ("payroll_schedule_entries", "role_snapshot", "VARCHAR(64) NULL"),
        ("payroll_schedule_entries", "work_stream_snapshot", "VARCHAR(64) NULL"),
        ("payroll_schedule_entries", "shift_snapshot", "VARCHAR(64) NULL"),
        ("payroll_worker_profiles", "default_overtime_rate", "DECIMAL(10,2) NULL"),
    ]
    for table, col, ddl in cols:
        if table_exists(c, table) and not table_has_column(c, table, col):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    if not table_exists(c, "payroll_schedule_coverage_targets"):
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_schedule_coverage_targets (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              day_of_week TINYINT NULL,
              shift_id INT NOT NULL,
              work_stream_id INT NOT NULL,
              role_id INT NOT NULL,
              required_count INT NOT NULL DEFAULT 1,
              active TINYINT(1) NOT NULL DEFAULT 1,
              notes TEXT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_psct_org (organization_id, active)
            ) ENGINE=InnoDB
            """
        )
    if not table_exists(c, "payroll_schedule_change_log"):
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_schedule_change_log (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              schedule_entry_id INT NULL,
              action VARCHAR(32) NOT NULL,
              old_snapshot JSON NULL,
              new_snapshot JSON NULL,
              changed_by INT NULL,
              change_note TEXT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_pscl_org_date (organization_id, created_at)
            ) ENGINE=InnoDB
            """
        )


def _seed_default_coverage_targets(conn, organization_id: int) -> None:
    c = _cursor(conn)
    c.execute(
        "SELECT COUNT(*) AS n FROM payroll_schedule_coverage_targets WHERE organization_id=%s",
        (int(organization_id),),
    )
    row = c.fetchone() or {}
    n = int(row.get("n") or 0)
    if n > 0:
        return
    shift_active = _where_active(c, "payroll_shifts")
    c.execute(
        f"SELECT id, name FROM payroll_shifts WHERE organization_id=%s AND {shift_active}",
        (int(organization_id),),
    )
    shifts = {r["name"].lower(): r["id"] for r in c.fetchall()}
    stream_active = _where_active(c, "payroll_work_streams")
    c.execute(
        f"SELECT id, name FROM payroll_work_streams WHERE organization_id=%s AND {stream_active}",
        (int(organization_id),),
    )
    streams = {r["name"].lower(): r["id"] for r in c.fetchall()}
    role_active = _where_active(c, "payroll_roles")
    c.execute(
        f"SELECT id, name FROM payroll_roles WHERE organization_id=%s AND {role_active}",
        (int(organization_id),),
    )
    roles = {r["name"].lower(): r["id"] for r in c.fetchall()}
    morning = shifts.get("morning")
    afternoon = shifts.get("afternoon")
    rinse = streams.get("rinse")
    drop = streams.get("drop off")
    op = roles.get("operator")
    folder = roles.get("folder")
    ins = conn.cursor()
    defaults = []
    if morning and rinse and op:
        defaults.append((None, morning, rinse, op, 1))
    if morning and rinse and folder:
        defaults.append((None, morning, rinse, folder, 2))
    if afternoon and drop and op:
        defaults.append((None, afternoon, drop, op, 1))
    if afternoon and drop and folder:
        defaults.append((None, afternoon, drop, folder, 1))
    for dow, sid, wsid, rid, cnt in defaults:
        ins.execute(
            """
            INSERT INTO payroll_schedule_coverage_targets
              (organization_id, day_of_week, shift_id, work_stream_id, role_id, required_count, active)
            VALUES (%s,%s,%s,%s,%s,%s,1)
            """,
            (int(organization_id), dow, sid, wsid, rid, cnt),
        )


def list_coverage_targets(conn, organization_id: int) -> list[dict[str, Any]]:
    ensure_payroll_schedule_v2(conn.cursor())
    seed_schedule_defaults(conn.cursor(), organization_id)
    _seed_default_coverage_targets(conn, organization_id)
    c = _cursor(conn)
    c.execute(
        """
        SELECT t.*, s.name AS shift_name, ws.name AS work_stream_name, r.name AS role_name
        FROM payroll_schedule_coverage_targets t
        JOIN payroll_shifts s ON s.id=t.shift_id
        JOIN payroll_work_streams ws ON ws.id=t.work_stream_id
        JOIN payroll_roles r ON r.id=t.role_id
        WHERE t.organization_id=%s
        ORDER BY t.day_of_week IS NULL DESC, t.day_of_week, s.sort_order, ws.sort_order, r.sort_order
        """,
        (int(organization_id),),
    )
    return [json_safe(r) for r in c.fetchall()]


def save_coverage_targets(conn, organization_id: int, items: list[dict]) -> list[dict[str, Any]]:
    ensure_payroll_schedule_v2(conn.cursor())
    c = conn.cursor()
    oid = int(organization_id)
    for item in items or []:
        if item.get("id"):
            c.execute(
                """
                UPDATE payroll_schedule_coverage_targets
                SET day_of_week=%s, shift_id=%s, work_stream_id=%s, role_id=%s,
                    required_count=%s, active=%s, notes=%s
                WHERE id=%s AND organization_id=%s
                """,
                (
                    item.get("day_of_week"),
                    item["shift_id"],
                    item["work_stream_id"],
                    item["role_id"],
                    int(item.get("required_count") or 1),
                    1 if item.get("active", True) else 0,
                    item.get("notes"),
                    int(item["id"]),
                    oid,
                ),
            )
        else:
            c.execute(
                """
                INSERT INTO payroll_schedule_coverage_targets
                  (organization_id, day_of_week, shift_id, work_stream_id, role_id, required_count, active, notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    oid,
                    item.get("day_of_week"),
                    item["shift_id"],
                    item["work_stream_id"],
                    item["role_id"],
                    int(item.get("required_count") or 1),
                    1 if item.get("active", True) else 0,
                    item.get("notes"),
                ),
            )
    return list_coverage_targets(conn, organization_id)


def _worker_balance_label(scheduled: Decimal, settings: dict, *, available: bool = True, days: int = 0) -> str:
    ot = _d(settings.get("overtime_threshold_hours") or 40)
    under = _d(settings.get("underused_hours_threshold") or 15)
    heavy = _d(settings.get("heavy_hours_threshold") or 35)
    if scheduled > ot:
        return "Overtime Risk"
    if scheduled >= heavy:
        return "Heavy"
    if available and scheduled < under and days <= 2:
        return "Underused"
    return "Balanced"


def _times_overlap(a: dict, b: dict) -> bool:
    st_a = _parse_time(a.get("start_time"))
    et_a = _parse_time(a.get("end_time"))
    st_b = _parse_time(b.get("start_time"))
    et_b = _parse_time(b.get("end_time"))
    if not all([st_a, et_a, st_b, et_b]):
        return False
    base = date(2000, 1, 1)
    from datetime import datetime as dt

    a0 = dt.combine(base, st_a)
    a1 = dt.combine(base, et_a)
    b0 = dt.combine(base, st_b)
    b1 = dt.combine(base, et_b)
    if a1 <= a0:
        a1 += timedelta(days=1)
    if b1 <= b0:
        b1 += timedelta(days=1)
    return a0 < b1 and b0 < a1


def load_plan_bundle(
    conn, organization_id: int, *, start_date: str, end_date: str
) -> dict[str, Any]:
    ensure_payroll_schedule_v2(conn.cursor())
    oid = int(organization_id)
    settings = get_org_schedule_settings(conn, oid)
    c = _cursor(conn)
    c.execute(
        "SELECT underused_hours_threshold, heavy_hours_threshold, target_hours_per_week, payment_day_of_week FROM payroll_schedule_org_settings WHERE organization_id=%s",
        (oid,),
    )
    bal = c.fetchone() or {}
    settings.update(
        {
            "underused_hours_threshold": float(bal.get("underused_hours_threshold") or 15),
            "heavy_hours_threshold": float(bal.get("heavy_hours_threshold") or 35),
            "target_hours_per_week": float(bal.get("target_hours_per_week") or 32),
            "payment_day_of_week": int(bal.get("payment_day_of_week") if bal.get("payment_day_of_week") is not None else 6),
        }
    )
    entries = list_schedule_entries(conn, oid, start_date=start_date, end_date=end_date)
    workers_raw = list_workers(conn, oid)
    workers = []
    for w in workers_raw:
        w = enrich_worker_for_scheduling(conn, oid, w)
        ws = date.fromisoformat(start_date[:10])
        week_start, week_end = payroll_week_bounds(conn, ws, oid)
        from backend.payroll_schedule import _approved_hours_week, _scheduled_hours_week

        scheduled = _scheduled_hours_week(conn, oid, int(w["id"]), week_start, week_end)
        approved = _approved_hours_week(conn, oid, int(w["user_id"]), week_start, week_end)
        w["approved_hours"] = _q2(approved)
        w["scheduled_hours_published"] = _q2(scheduled)
        workers.append(json_safe(w))
    coverage = list_coverage_targets(conn, oid)
    pub_count = count_published_entries(conn, oid, start_date, end_date)
    return json_safe(
        {
            "settings": settings,
            "entries": entries,
            "workers": workers,
            "coverage_targets": coverage,
            "start_date": start_date,
            "end_date": end_date,
            "published_count": pub_count,
        }
    )


def suggest_workers_for_shift(
    conn,
    organization_id: int,
    *,
    work_date: str,
    shift_id: int,
    work_stream_id: Optional[int] = None,
    role_id: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    break_minutes: int = 0,
    exclude_entry_id: Optional[int] = None,
) -> dict[str, Any]:
    ws = date.fromisoformat(work_date[:10])
    week_start, week_end = payroll_week_bounds(conn, int(organization_id), ws)
    bundle = load_plan_bundle(
        conn,
        organization_id,
        start_date=week_start.isoformat(),
        end_date=week_end.isoformat(),
    )
    settings = bundle["settings"]
    workers = bundle["workers"]
    entries = [
        e
        for e in bundle["entries"]
        if exclude_entry_id is None or int(e.get("id") or 0) != int(exclude_entry_id)
    ]
    c = _cursor(conn)
    c.execute("SELECT * FROM payroll_shifts WHERE id=%s", (int(shift_id),))
    shift = c.fetchone() or {}
    st = start_time or _time_to_str(_parse_time(shift.get("start_time_default")))
    et = end_time or _time_to_str(_parse_time(shift.get("end_time_default")))
    shift_hours = compute_scheduled_hours(_parse_time(st), _parse_time(et), break_minutes)
    dow = ws.weekday()
    day_entries = [e for e in entries if str(e.get("work_date"))[:10] == work_date[:10]]
    candidates = []
    for w in workers:
        wpid = int(w["id"])
        same_day = [e for e in day_entries if int(e.get("worker_profile_id") or 0) == wpid]
        probe = {"start_time": st, "end_time": et}
        if any(_times_overlap(probe, e) for e in same_day):
            continue
        reasons: list[str] = []
        score = 50
        reasons.append("Available: Yes")
        role_skills = w.get("role_skills") or []
        if role_id:
            has_role = any(int(s.get("role_id") or 0) == int(role_id) for s in role_skills)
            if has_role:
                score += 30
                reasons.append("Role Match: Yes")
            else:
                score -= 15
                reasons.append("Role Match: No")
        if work_stream_id:
            if any(int(s.get("work_stream_id") or 0) == int(work_stream_id) for s in role_skills):
                score += 20
                reasons.append("Work Stream Match: Yes")
        from backend.payroll_schedule import _scheduled_hours_week

        sched = _scheduled_hours_week(conn, organization_id, wpid, week_start, week_end)
        ot_threshold = _overtime_threshold(conn, organization_id, w)
        after = sched + shift_hours
        ot_risk = after > ot_threshold
        reasons.append(f"Current Weekly Hours: {_q2(sched)}")
        reasons.append(f"After This Shift: {_q2(after)}")
        reasons.append(f"Overtime Risk: {'Yes' if ot_risk else 'No'}")
        if ot_risk:
            score -= 50
        else:
            score += min(20, int(float(_q2(ot_threshold - after))))
        perf = w.get("performance_preview") or {}
        if perf.get("available"):
            score += 10
            reasons.append("Performance: Strong")
        else:
            reasons.append("Performance: No data yet")
        avail_rows = w.get("availability") or []
        day_avail = next((a for a in avail_rows if int(a.get("day_of_week", -1)) == dow), None)
        if day_avail and day_avail.get("unavailable_flag"):
            continue
        rate = _d(w.get("default_hourly_rate"))
        if rate > 0:
            score -= float(rate) * 0.5
        rec = "Good"
        if score >= 80 and not ot_risk:
            rec = "Best"
        elif ot_risk:
            rec = "Avoid unless necessary"
        balance = _worker_balance_label(sched, settings, days=0)
        candidates.append(
            json_safe(
                {
                    "worker_profile_id": wpid,
                    "user_id": w.get("user_id"),
                    "worker_name": w.get("worker_name") or w.get("display_name"),
                    "worker_category_label": w.get("worker_category_label"),
                    "score": score,
                    "recommendation": rec,
                    "reasons": reasons,
                    "current_weekly_hours": _q2(sched),
                    "projected_hours_after": _q2(after),
                    "overtime_risk_after": ot_risk,
                    "balance_label": balance,
                    "hourly_rate": _q2(rate) if rate > 0 else None,
                    "performance_preview": perf,
                }
            )
        )
    candidates.sort(key=lambda x: x["score"], reverse=True)
    c.execute("SELECT name FROM payroll_shifts WHERE id=%s", (int(shift_id),))
    shift_name = (c.fetchone() or {}).get("name")
    stream_name = role_name = ""
    if work_stream_id:
        c.execute("SELECT name FROM payroll_work_streams WHERE id=%s", (int(work_stream_id),))
        stream_name = (c.fetchone() or {}).get("name") or ""
    if role_id:
        c.execute("SELECT name FROM payroll_roles WHERE id=%s", (int(role_id),))
        role_name = (c.fetchone() or {}).get("name") or ""
    return json_safe(
        {
            "title": f"Suggestions for {shift_name} {stream_name} {role_name}".strip(),
            "work_date": work_date,
            "shift_hours": _q2(shift_hours),
            "suggestions": candidates[:10],
        }
    )


def _log_change(
    cursor,
    organization_id: int,
    *,
    entry_id: Optional[int],
    action: str,
    old: Optional[dict],
    new: Optional[dict],
    changed_by: Optional[int],
    note: Optional[str] = None,
) -> None:
    ensure_payroll_schedule_v2(cursor)
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    c.execute(
        """
        INSERT INTO payroll_schedule_change_log
          (organization_id, schedule_entry_id, action, old_snapshot, new_snapshot, changed_by, change_note)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            entry_id,
            action,
            json.dumps(old) if old else None,
            json.dumps(new) if new else None,
            changed_by,
            note,
        ),
    )


def save_draft_entries(
    conn,
    organization_id: int,
    entries: list[dict],
    *,
    created_by: Optional[int] = None,
) -> dict[str, Any]:
    from backend.payroll_schedule import create_schedule_entry, delete_schedule_entry, update_schedule_entry

    ensure_payroll_schedule_v2(conn.cursor())
    oid = int(organization_id)
    saved = []
    for item in entries or []:
        if item.get("_deleted"):
            eid = item.get("id")
            if eid and not str(eid).startswith("tmp"):
                old = item
                delete_schedule_entry(conn, oid, int(eid))
                _log_change(
                    conn.cursor(),
                    oid,
                    entry_id=int(eid),
                    action="delete",
                    old=old,
                    new=None,
                    changed_by=created_by,
                    note=item.get("change_note"),
                )
            continue
        body = _sanitize_entry_for_save(item)
        body["publish_status"] = "draft"
        eid = body.get("id") or item.get("id")
        change_note = body.get("change_note") or item.get("change_note")
        if eid and not str(eid).startswith("tmp"):
            old_row = _cursor(conn)
            old_row.execute("SELECT * FROM payroll_schedule_entries WHERE id=%s", (int(eid),))
            old = old_row.fetchone()
            action = _infer_change_action(body, dict(old) if old else None)
            out = update_schedule_entry(conn, oid, int(eid), body)
            conn.cursor().execute(
                "UPDATE payroll_schedule_entries SET publish_status='draft' WHERE id=%s",
                (int(eid),),
            )
            _log_change(
                conn.cursor(),
                oid,
                entry_id=int(eid),
                action=action,
                old=dict(old) if old else None,
                new=out,
                changed_by=created_by,
                note=change_note,
            )
            saved.append(out)
        else:
            body.pop("id", None)
            out = create_schedule_entry(conn, oid, body, created_by=created_by)
            conn.cursor().execute(
                "UPDATE payroll_schedule_entries SET publish_status='draft' WHERE id=%s",
                (int(out["id"]),),
            )
            _log_change(
                conn.cursor(),
                oid,
                entry_id=int(out["id"]),
                action="draft_create",
                old=None,
                new=out,
                changed_by=created_by,
                note=body.get("change_note"),
            )
            saved.append(out)
    return {"saved": saved, "count": len(saved)}


def publish_schedule(
    conn,
    organization_id: int,
    *,
    start_date: str,
    end_date: str,
    changed_by: Optional[int] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    ensure_payroll_schedule_v2(conn.cursor())
    oid = int(organization_id)
    c = conn.cursor()
    c.execute(
        """
        SELECT id FROM payroll_schedule_entries
        WHERE organization_id=%s AND work_date BETWEEN %s AND %s
          AND (publish_status='draft' OR publish_status IS NULL)
          AND status NOT IN ('cancelled')
        """,
        (oid, start_date, end_date),
    )
    ids = [int(r[0]) for r in c.fetchall()]
    for eid in ids:
        c.execute(
            """
            UPDATE payroll_schedule_entries
            SET publish_status='published', published_at=NOW(), published_by=%s
            WHERE id=%s AND organization_id=%s
            """,
            (changed_by, eid, oid),
        )
        _log_change(
            c,
            oid,
            entry_id=eid,
            action="publish",
            old={"publish_status": "draft"},
            new={"publish_status": "published"},
            changed_by=changed_by,
            note=note,
        )
    return {"published_count": len(ids), "start_date": start_date, "end_date": end_date}


def list_change_log(conn, organization_id: int, *, start_date: Optional[str] = None, limit: int = 50) -> list:
    ensure_payroll_schedule_v2(conn.cursor())
    c = _cursor(conn)
    q = "SELECT * FROM payroll_schedule_change_log WHERE organization_id=%s"
    params: list[Any] = [int(organization_id)]
    if start_date:
        q += " AND DATE(created_at) >= %s"
        params.append(start_date)
    q += " ORDER BY id DESC LIMIT %s"
    params.append(int(limit))
    c.execute(q, tuple(params))
    return [json_safe(r) for r in c.fetchall()]
