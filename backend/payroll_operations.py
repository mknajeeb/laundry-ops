"""Payroll operations: time records, payout batches, accountant summaries."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from backend.contractor_management import (
    compute_payment_summary_amounts,
    sum_payments_ytd,
    user_is_contractor,
    user_is_short_term_temp,
)
from backend.payroll_identity import (
    fetch_payroll_profile_row,
    get_or_create_payroll_cycle_unified,
    payroll_profiles_active,
)
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column


WORKER_CATEGORIES = ("w2", "contractor_1099", "temp")

CATEGORY_LABELS = {
    "w2": "W-2 Employee",
    "contractor_1099": "1099 Contractor",
    "temp": "Temp / One-Time",
}

BATCH_STATUSES = (
    "draft",
    "hours_reviewed",
    "sent_to_accountant",
    "accountant_reviewed",
    "approved_for_payment",
    "paid",
    "closed",
)


def worker_category_for_user(conn, user_id: int) -> str:
    try:
        has_1099 = user_is_contractor(conn, user_id)
        has_temp = user_is_short_term_temp(conn, user_id)
        if has_temp and not has_1099:
            return "temp"
        if has_1099:
            return "contractor_1099"
    except Exception:
        pass
    return "w2"


def _money(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")[:19])
    except Exception:
        return None


def format_hours_display(seconds: Any) -> str:
    if seconds is None:
        return "—"
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    dec = round(s / 3600, 2)
    if h > 0:
        return f"{h}h {m}m ({dec} h)"
    if m > 0:
        return f"{m}m ({dec} h)"
    return f"{dec} h"


def ensure_payroll_hours_approved_column(cursor) -> None:
    if not table_exists(cursor, "shift_sessions"):
        return
    if table_has_column(cursor, "shift_sessions", "payroll_hours_approved"):
        return
    try:
        cursor.execute(
            """
            ALTER TABLE shift_sessions
            ADD COLUMN payroll_hours_approved TINYINT(1) NOT NULL DEFAULT 0
            """
        )
    except Exception as exc:
        # 1060: duplicate column — another request added it first; refresh cache.
        if getattr(exc, "args", (None,))[0] != 1060:
            raise
    invalidate_schema_cache()


def time_record_status(row: dict) -> str:
    st = str(row.get("status") or "")
    if st == "active":
        return "open"
    if bool(row.get("payroll_hours_approved")):
        return "approved"
    if bool(row.get("manual_override")):
        return "pending_approval"
    if str(row.get("payroll_cycle_review_state") or "") == "approved":
        return "approved"
    if st in ("completed", "auto_closed"):
        return "completed"
    return st or "completed"


def ensure_payout_batches_tables(cursor) -> None:
    if not table_exists(cursor, "payout_batches"):
        cursor.execute(
            """
            CREATE TABLE payout_batches (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              batch_name VARCHAR(255) NOT NULL,
              worker_category VARCHAR(32) NOT NULL,
              pay_period_start DATE NOT NULL,
              pay_period_end DATE NOT NULL,
              payout_frequency VARCHAR(16) NOT NULL DEFAULT 'biweekly',
              status VARCHAR(32) NOT NULL DEFAULT 'draft',
              notes TEXT NULL,
              worker_count INT NOT NULL DEFAULT 0,
              total_approved_hours DECIMAL(12,2) NOT NULL DEFAULT 0,
              total_gross_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              total_adjustments DECIMAL(12,2) NOT NULL DEFAULT 0,
              total_payout_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              documents_missing_count INT NOT NULL DEFAULT 0,
              sent_to_accountant_at DATETIME NULL,
              paid_at DATETIME NULL,
              created_by INT NULL,
              approved_by INT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_pb_org_cat (organization_id, worker_category, pay_period_start),
              INDEX idx_pb_org_status (organization_id, status)
            ) ENGINE=InnoDB
            """
        )
    if not table_exists(cursor, "payout_batch_lines"):
        cursor.execute(
            """
            CREATE TABLE payout_batch_lines (
              id INT AUTO_INCREMENT PRIMARY KEY,
              batch_id INT NOT NULL,
              organization_id INT NOT NULL,
              user_id INT NULL,
              worker_name_snapshot VARCHAR(255) NOT NULL,
              worker_category VARCHAR(32) NOT NULL,
              approved_hours DECIMAL(10,2) NOT NULL DEFAULT 0,
              rate DECIMAL(10,2) NOT NULL DEFAULT 0,
              gross_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
              adjustments DECIMAL(10,2) NOT NULL DEFAULT 0,
              total_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
              payment_method VARCHAR(64) NULL,
              payment_reference VARCHAR(255) NULL,
              payment_date DATE NULL,
              line_status VARCHAR(32) NOT NULL DEFAULT 'pending',
              document_status VARCHAR(64) NULL,
              notes TEXT NULL,
              gross_wages DECIMAL(10,2) NULL,
              federal_withholding DECIMAL(10,2) NULL,
              state_withholding DECIMAL(10,2) NULL,
              city_withholding DECIMAL(10,2) NULL,
              social_security_withholding DECIMAL(10,2) NULL,
              medicare_withholding DECIMAL(10,2) NULL,
              other_deductions DECIMAL(10,2) NULL,
              net_pay DECIMAL(10,2) NULL,
              accountant_notes TEXT NULL,
              accountant_updated_at DATETIME NULL,
              accountant_updated_by INT NULL,
              source_type VARCHAR(32) NOT NULL DEFAULT 'manual',
              source_shift_session_ids JSON NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_pbl_batch (batch_id),
              CONSTRAINT fk_pbl_batch FOREIGN KEY (batch_id) REFERENCES payout_batches(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )


def list_time_records(
    conn,
    organization_id: int,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user_id: Optional[int] = None,
    worker_category: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    if not payroll_profiles_active(conn):
        return []
    chk = conn.cursor()
    ensure_payroll_hours_approved_column(chk)
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    has_remarks = table_has_column(chk, "shift_sessions", "period_adjustment_remarks")
    has_override = table_has_column(chk, "shift_sessions", "manual_override")
    has_hours_approved = table_has_column(chk, "shift_sessions", "payroll_hours_approved")
    has_review = table_has_column(chk, "payroll_cycles", "review_state")
    remarks_sel = (
        ", s.period_adjustment_remarks"
        if has_remarks
        else ", NULL AS period_adjustment_remarks"
    )
    override_sel = ", s.manual_override" if has_override else ", 0 AS manual_override"
    hours_approved_sel = (
        ", s.payroll_hours_approved"
        if has_hours_approved
        else ", 0 AS payroll_hours_approved"
    )
    review_sel = ", pc.review_state AS payroll_cycle_review_state" if has_review else ""
    if has_ss_org:
        org_clause = "s.organization_id = %s"
    else:
        org_clause = "u.organization_id = %s"
    c = conn.cursor(dictionary=True)
    q = f"""
        SELECT s.id, s.user_id, s.clock_in_at, s.clock_out_at, s.status,
               s.total_break_seconds, s.net_work_seconds
               {override_sel}{hours_approved_sel}{remarks_sel},
               pp.first_name, pp.last_name
               {review_sel}
        FROM shift_sessions s
        JOIN users u ON u.id = s.user_id
        JOIN payroll_profiles pp ON pp.user_id = s.user_id
        JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
        WHERE {org_clause}
    """
    params: list[Any] = [int(organization_id)]
    if from_date:
        q += " AND DATE(s.clock_in_at) >= %s"
        params.append(from_date)
    if to_date:
        q += " AND DATE(s.clock_in_at) <= %s"
        params.append(to_date)
    if user_id:
        q += " AND s.user_id = %s"
        params.append(int(user_id))
    q += " ORDER BY s.clock_in_at DESC, s.id DESC LIMIT %s"
    params.append(int(limit))
    c.execute(q, params)
    rows = c.fetchall() or []
    rate_cache: dict[int, dict] = {}
    out = []
    for row in rows:
        cat = worker_category_for_user(conn, int(row["user_id"]))
        if worker_category and worker_category != "all" and cat != worker_category:
            continue
        net = int(row.get("net_work_seconds") or 0)
        approved_sec = net
        uid = int(row["user_id"])
        if uid not in rate_cache:
            from backend.payroll_workflow import resolve_worker_hourly_rate

            rate_cache[uid] = resolve_worker_hourly_rate(conn, uid, int(organization_id))
        rate_info = rate_cache[uid]
        rec = {
            "id": row["id"],
            "user_id": row["user_id"],
            "worker_name": f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip(),
            "worker_category": cat,
            "worker_category_label": CATEGORY_LABELS.get(cat, cat),
            "work_date": str(row.get("clock_in_at") or "")[:10],
            "clock_in_at": row.get("clock_in_at"),
            "clock_out_at": row.get("clock_out_at"),
            "break_seconds": int(row.get("total_break_seconds") or 0),
            "total_hours_display": format_hours_display(net),
            "approved_hours": round(approved_sec / 3600, 2),
            "approved_hours_display": format_hours_display(approved_sec),
            "hourly_rate": rate_info.get("hourly_rate"),
            "rate_source": rate_info.get("rate_source"),
            "rate_missing": bool(rate_info.get("rate_missing")),
            "status": time_record_status(row),
            "notes": row.get("period_adjustment_remarks") or "",
            "payroll_hours_approved": bool(row.get("payroll_hours_approved")),
            "pending_approval": bool(row.get("manual_override"))
            and not bool(row.get("payroll_hours_approved")),
        }
        if status_filter and status_filter != "all" and rec["status"] != status_filter:
            continue
        out.append(json_safe(rec))
    return out


def _sum_break_seconds(conn, shift_id: int) -> int:
    chk = conn.cursor()
    if not table_exists(chk, "shift_breaks"):
        return 0
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT break_start_at, break_end_at FROM shift_breaks WHERE shift_session_id=%s",
        (int(shift_id),),
    )
    total = 0
    for row in c.fetchall() or []:
        start, end = row.get("break_start_at"), row.get("break_end_at")
        if start and end:
            total += int((end - start).total_seconds())
    return total


def _geofence_for_user(conn, user_id: int, organization_id: int) -> int:
    c = conn.cursor(dictionary=True)
    if table_exists(c, "user_geofences"):
        c.execute(
            """
            SELECT geofence_id FROM user_geofences
            WHERE user_id=%s
            ORDER BY is_primary DESC, geofence_id ASC
            LIMIT 1
            """,
            (int(user_id),),
        )
        row = c.fetchone()
        if row and row.get("geofence_id") is not None:
            return int(row["geofence_id"])
    chk = conn.cursor()
    if table_has_column(chk, "geofences", "organization_id"):
        c.execute(
            """
            SELECT id FROM geofences
            WHERE organization_id=%s AND active=1
            ORDER BY id ASC
            LIMIT 1
            """,
            (int(organization_id),),
        )
    else:
        c.execute(
            """
            SELECT id FROM geofences
            WHERE active=1
            ORDER BY id ASC
            LIMIT 1
            """,
        )
    row = c.fetchone()
    if row and row.get("id") is not None:
        return int(row["id"])
    raise ValueError(
        "No active geofence for this organization. Configure a geofence under Time & Attendance."
    )


def _employment_category_for_user(conn, user_id: int) -> Optional[int]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "user_employment_categories"):
        return None
    c.execute(
        """
        SELECT employment_category_id FROM user_employment_categories
        WHERE user_id=%s AND effective_from <= CURDATE()
          AND (effective_to IS NULL OR effective_to >= CURDATE())
        ORDER BY effective_from DESC LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone()
    if row and row.get("employment_category_id") is not None:
        return int(row["employment_category_id"])
    return None


def _session_in_org(conn, organization_id: int, session_id: int) -> bool:
    chk = conn.cursor()
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    c = conn.cursor(dictionary=True)
    if has_ss_org:
        c.execute(
            "SELECT id FROM shift_sessions WHERE id=%s AND organization_id=%s",
            (int(session_id), int(organization_id)),
        )
    else:
        c.execute(
            """
            SELECT s.id FROM shift_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id=%s AND u.organization_id=%s
            """,
            (int(session_id), int(organization_id)),
        )
    return c.fetchone() is not None


def _parse_clock_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def create_manual_time_record(
    conn,
    organization_id: int,
    *,
    user_id: int,
    clock_in_at: Any,
    clock_out_at: Any,
    remarks: str = "",
) -> dict:
    ci = _parse_clock_dt(clock_in_at)
    co = _parse_clock_dt(clock_out_at)
    if not ci or not co or co <= ci:
        raise ValueError("Clock out must be after clock in")
    uid = int(user_id)
    oid = int(organization_id)
    pc_id = get_or_create_payroll_cycle_unified(conn, ci, oid)
    net = int((co - ci).total_seconds())
    geofence_id = _geofence_for_user(conn, uid, oid)
    employment_category_id = _employment_category_for_user(conn, uid)

    chk = conn.cursor()
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    has_remarks = table_has_column(chk, "shift_sessions", "period_adjustment_remarks")
    has_manual = table_has_column(chk, "shift_sessions", "manual_override")

    cols = [
        "user_id",
        "payroll_cycle_id",
        "geofence_id",
        "employment_category_id",
        "clock_in_at",
        "clock_out_at",
        "status",
        "total_break_seconds",
        "net_work_seconds",
    ]
    vals: list[Any] = [uid, pc_id, geofence_id, employment_category_id, ci, co, "completed", 0, net]
    if has_ss_org:
        cols.insert(1, "organization_id")
        vals.insert(1, oid)
    if has_manual:
        cols.append("manual_override")
        vals.append(1)
    if has_remarks:
        cols.append("period_adjustment_remarks")
        vals.append((remarks or "Manual payroll entry")[:2000])

    placeholders = ", ".join(["%s"] * len(cols))
    c = conn.cursor()
    c.execute(
        f"INSERT INTO shift_sessions ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )
    sid = c.lastrowid
    conn.commit()
    items = list_time_records(conn, organization_id, limit=2000)
    for rec in items:
        if rec["id"] == sid:
            return rec
    return {"id": sid, "user_id": uid}


def update_time_record(
    conn,
    organization_id: int,
    session_id: int,
    *,
    clock_in_at: Any = None,
    clock_out_at: Any = None,
    remarks: Optional[str] = None,
) -> dict:
    sid = int(session_id)
    if not _session_in_org(conn, organization_id, sid):
        raise ValueError("Time record not found")

    chk = conn.cursor()
    has_remarks = table_has_column(chk, "shift_sessions", "period_adjustment_remarks")
    has_manual = table_has_column(chk, "shift_sessions", "manual_override")
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")

    ci = _parse_clock_dt(clock_in_at) if clock_in_at is not None else None
    co = _parse_clock_dt(clock_out_at) if clock_out_at is not None else None

    c = conn.cursor(dictionary=True)
    c.execute("SELECT clock_in_at, clock_out_at FROM shift_sessions WHERE id=%s", (sid,))
    cur = c.fetchone()
    if not cur:
        raise ValueError("Time record not found")

    new_ci = ci if ci is not None else cur.get("clock_in_at")
    new_co = co if co is not None else cur.get("clock_out_at")
    if isinstance(new_ci, str):
        new_ci = _parse_clock_dt(new_ci)
    if isinstance(new_co, str):
        new_co = _parse_clock_dt(new_co)
    if not new_ci or not new_co or new_co <= new_ci:
        raise ValueError("Clock out must be after clock in")

    updates = ["clock_in_at=%s", "clock_out_at=%s"]
    params: list[Any] = [new_ci, new_co]
    if has_manual:
        updates.append("manual_override=1")
    if has_remarks and remarks is not None:
        updates.append("period_adjustment_remarks=%s")
        params.append(str(remarks)[:2000])

    br = _sum_break_seconds(conn, sid)
    net = int((new_co - new_ci).total_seconds()) - br
    updates.extend(["total_break_seconds=%s", "net_work_seconds=%s", "status=%s"])
    params.extend([br, net, "completed"])

    where = "id=%s"
    params.append(sid)
    if has_ss_org:
        where += " AND organization_id=%s"
        params.append(int(organization_id))

    c2 = conn.cursor()
    c2.execute(f"UPDATE shift_sessions SET {', '.join(updates)} WHERE {where}", tuple(params))
    if c2.rowcount < 1:
        raise ValueError("Time record not found")
    conn.commit()

    items = list_time_records(conn, organization_id, limit=2000)
    for rec in items:
        if rec["id"] == sid:
            return rec
    return {"id": sid}


def approve_time_record(conn, organization_id: int, session_id: int) -> dict:
    if not _session_in_org(conn, organization_id, session_id):
        raise ValueError("Time record not found")
    chk = conn.cursor()
    ensure_payroll_hours_approved_column(chk)
    has_manual = table_has_column(chk, "shift_sessions", "manual_override")
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    sets = ["payroll_hours_approved=1"]
    if has_manual:
        sets.append("manual_override=0")
    where = "id=%s"
    params: list[Any] = [int(session_id)]
    if has_ss_org:
        where += " AND organization_id=%s"
        params.append(int(organization_id))
    c = conn.cursor()
    c.execute(f"UPDATE shift_sessions SET {', '.join(sets)} WHERE {where}", tuple(params))
    if c.rowcount < 1:
        raise ValueError("Time record not found")
    conn.commit()
    items = list_time_records(conn, organization_id, limit=2000)
    for rec in items:
        if rec["id"] == session_id:
            return rec
    return {"id": session_id, "status": "approved"}


def bulk_approve_time_records(
    conn,
    organization_id: int,
    *,
    session_ids: Optional[list[int]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user_id: Optional[int] = None,
    worker_category: Optional[str] = None,
) -> dict:
    if session_ids:
        ids = [int(x) for x in session_ids]
    else:
        records = list_time_records(
            conn,
            organization_id,
            from_date=from_date,
            to_date=to_date,
            user_id=user_id,
            worker_category=worker_category,
            limit=2000,
        )
        ids = [
            int(r["id"])
            for r in records
            if r.get("status") in ("pending_approval", "completed")
        ]
    approved = 0
    errors: list[dict] = []
    for sid in ids:
        try:
            approve_time_record(conn, organization_id, sid)
            approved += 1
        except ValueError as exc:
            errors.append({"id": sid, "error": str(exc)})
    return {"approved": approved, "skipped": len(errors), "errors": errors}


def delete_time_record(conn, organization_id: int, session_id: int) -> bool:
    chk = conn.cursor()
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    c = conn.cursor()
    if has_ss_org:
        c.execute(
            "DELETE FROM shift_sessions WHERE id=%s AND organization_id=%s",
            (int(session_id), int(organization_id)),
        )
    else:
        c.execute(
            """
            DELETE s FROM shift_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id=%s AND u.organization_id=%s
            """,
            (int(session_id), int(organization_id)),
        )
    conn.commit()
    return c.rowcount > 0


def _recompute_batch_totals(conn, batch_id: int) -> None:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT COUNT(*) AS cnt,
               COALESCE(SUM(approved_hours), 0) AS hours,
               COALESCE(SUM(gross_amount), 0) AS gross,
               COALESCE(SUM(adjustments), 0) AS adj,
               COALESCE(SUM(total_amount), 0) AS total
        FROM payout_batch_lines WHERE batch_id = %s
        """,
        (int(batch_id),),
    )
    agg = c.fetchone() or {}
    c2 = conn.cursor()
    c2.execute(
        """
        UPDATE payout_batches SET
          worker_count=%s, total_approved_hours=%s, total_gross_amount=%s,
          total_adjustments=%s, total_payout_amount=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        (
            int(agg.get("cnt") or 0),
            float(agg.get("hours") or 0),
            float(agg.get("gross") or 0),
            float(agg.get("adj") or 0),
            float(agg.get("total") or 0),
            int(batch_id),
        ),
    )


def list_payout_batches(
    conn, organization_id: int, *, worker_category: Optional[str] = None, limit: int = 100
) -> list[dict]:
    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    q = "SELECT * FROM payout_batches WHERE organization_id=%s"
    params: list[Any] = [int(organization_id)]
    if worker_category and worker_category != "all":
        q += " AND worker_category=%s"
        params.append(worker_category)
    q += " ORDER BY pay_period_start DESC, id DESC LIMIT %s"
    params.append(int(limit))
    c.execute(q, params)
    return [json_safe(r) for r in c.fetchall() or []]


def _fetch_payout_batch_core(conn, organization_id: int, batch_id: int) -> Optional[dict]:
    """Load batch + lines from DB without rate backfill or workflow enrichment."""
    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payout_batches WHERE id=%s AND organization_id=%s LIMIT 1",
        (int(batch_id), int(organization_id)),
    )
    batch = c.fetchone()
    if not batch:
        return None
    c.execute(
        "SELECT * FROM payout_batch_lines WHERE batch_id=%s ORDER BY worker_name_snapshot",
        (int(batch_id),),
    )
    lines = [json_safe(r) for r in c.fetchall() or []]
    batch = json_safe(batch)
    batch["lines"] = lines
    batch["worker_category_label"] = CATEGORY_LABELS.get(
        batch.get("worker_category"), batch.get("worker_category")
    )
    return batch


def get_payout_batch(conn, organization_id: int, batch_id: int) -> Optional[dict]:
    batch = _fetch_payout_batch_core(conn, organization_id, batch_id)
    if not batch:
        return None
    from backend.payroll_workflow import backfill_batch_line_rates, enrich_payout_batch

    if backfill_batch_line_rates(conn, organization_id, batch):
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM payout_batch_lines WHERE batch_id=%s ORDER BY worker_name_snapshot",
            (int(batch_id),),
        )
        batch["lines"] = [json_safe(r) for r in c.fetchall() or []]
    return enrich_payout_batch(conn, organization_id, batch)


def create_payout_batch(
    conn, organization_id: int, body: dict, *, created_by: Optional[int] = None
) -> dict:
    ensure_payout_batches_tables(conn.cursor())
    cat = str(body.get("worker_category") or "").strip()
    if cat not in WORKER_CATEGORIES:
        raise ValueError("worker_category must be w2, contractor_1099, or temp")
    freq = str(body.get("payout_frequency") or "biweekly").strip()
    if freq not in ("weekly", "biweekly"):
        freq = "biweekly"
    name = (body.get("batch_name") or "").strip() or f"{CATEGORY_LABELS[cat]} {body.get('pay_period_start')}"
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO payout_batches (
          organization_id, batch_name, worker_category, pay_period_start, pay_period_end,
          payout_frequency, status, notes, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            name[:255],
            cat,
            body.get("pay_period_start"),
            body.get("pay_period_end"),
            freq,
            str(body.get("status") or "draft"),
            body.get("notes"),
            created_by,
        ),
    )
    batch_id = int(c.lastrowid)
    if body.get("pay_period_start") and body.get("pay_period_end"):
        return build_batch_from_time_records(
            conn,
            organization_id,
            batch_id,
            from_date=str(body["pay_period_start"]),
            to_date=str(body["pay_period_end"]),
            allow_empty=True,
        )
    return get_payout_batch(conn, organization_id, batch_id) or {}


def update_payout_batch(
    conn, organization_id: int, batch_id: int, body: dict
) -> Optional[dict]:
    batch = _fetch_payout_batch_core(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        raise ValueError("Only draft or hours-reviewed batches can be edited")
    fields = []
    vals: list[Any] = []
    for key, col in (
        ("batch_name", "batch_name"),
        ("pay_period_start", "pay_period_start"),
        ("pay_period_end", "pay_period_end"),
        ("payout_frequency", "payout_frequency"),
        ("notes", "notes"),
    ):
        if key in body and body[key] is not None:
            fields.append(f"{col}=%s")
            vals.append(body[key])
    if not fields:
        return batch
    vals.extend([int(batch_id), int(organization_id)])
    c = conn.cursor()
    period_changed = any(
        k in body and body[k] is not None for k in ("pay_period_start", "pay_period_end")
    )
    c.execute(
        f"UPDATE payout_batches SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP "
        f"WHERE id=%s AND organization_id=%s",
        tuple(vals),
    )
    conn.commit()
    if period_changed:
        batch = get_payout_batch(conn, organization_id, batch_id) or {}
        if batch.get("pay_period_start") and batch.get("pay_period_end"):
            return build_batch_from_time_records(
                conn,
                organization_id,
                batch_id,
                from_date=str(batch["pay_period_start"]),
                to_date=str(batch["pay_period_end"]),
                allow_empty=True,
            )
    return get_payout_batch(conn, organization_id, batch_id)


def delete_payout_batch(conn, organization_id: int, batch_id: int) -> bool:
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        return False
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        raise ValueError("Only draft or hours-reviewed batches can be deleted")
    from backend.payroll_accrual import reverse_ledger_entries_for_batch

    reverse_ledger_entries_for_batch(conn, organization_id, int(batch_id))
    c = conn.cursor()
    c.execute(
        "DELETE FROM payout_batches WHERE id=%s AND organization_id=%s",
        (int(batch_id), int(organization_id)),
    )
    conn.commit()
    return c.rowcount > 0


def delete_payout_batch_line(conn, organization_id: int, line_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT batch_id FROM payout_batch_lines WHERE id=%s AND organization_id=%s",
        (int(line_id), int(organization_id)),
    )
    row = c.fetchone()
    if not row:
        return False
    batch_id = int(row["batch_id"])
    c2 = conn.cursor()
    c2.execute(
        "DELETE FROM payout_batch_lines WHERE id=%s AND organization_id=%s",
        (int(line_id), int(organization_id)),
    )
    _recompute_batch_totals(conn, batch_id)
    conn.commit()
    return True


def _compute_payout_line_amounts(
    conn,
    organization_id: int,
    batch: dict,
    body: dict,
    *,
    user_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    line_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> dict[str, Any]:
    """Compute gross/total with sick leave (W-2) or health credit (1099/temp)."""
    from backend.payroll_accrual import (
        process_contractor_line_health_credit,
        process_w2_line_accruals,
    )
    from backend.payroll_workflow import ensure_payout_batch_line_extensions

    ensure_payout_batch_line_extensions(conn.cursor())
    cat = str(batch.get("worker_category") or "")
    regular = float(_money(body.get("approved_hours") or body.get("hours") or 0))
    ot = float(_money(body.get("ot_hours") or 0))
    rate = float(_money(body.get("rate")))
    adj = float(_money(body.get("adjustments")))
    bonus = float(_money(body.get("bonus_tip_amount") or 0))
    reimb = float(_money(body.get("reimbursement_amount") or 0))
    uid = user_id or body.get("user_id")
    period_start = batch.get("pay_period_start")
    period_end = batch.get("pay_period_end")

    out: dict[str, Any] = {
        "approved_hours": regular,
        "ot_hours": ot,
        "rate": rate,
        "adjustments": adj,
        "bonus_tip_amount": bonus,
        "reimbursement_amount": reimb,
        "sick_hours_accrued": 0,
        "sick_hours_used": float(_money(body.get("sick_hours_used") or 0)),
        "sick_pay_amount": 0,
        "health_credit_amount": 0,
        "gross_amount": 0,
        "total_amount": 0,
        "line_type": str(body.get("line_type") or "REGULAR"),
    }

    if cat == "w2" and uid and batch_id and line_id:
        from backend.payroll_accrual import reverse_ledger_entries_for_line

        reverse_ledger_entries_for_line(conn, organization_id, int(line_id), created_by=created_by)
        acc = process_w2_line_accruals(
            conn,
            organization_id,
            user_id=int(uid),
            batch_id=int(batch_id),
            line_id=int(line_id),
            regular_hours=_money(regular),
            ot_hours=_money(ot),
            sick_hours_used=_money(out["sick_hours_used"]),
            hourly_rate=_money(rate),
            period_start=str(period_start) if period_start else None,
            period_end=str(period_end) if period_end else None,
            allow_sick_over_balance=bool(body.get("allow_sick_over_balance")),
            sick_override_note=body.get("sick_override_note"),
            created_by=created_by,
        )
        out.update(acc)
        out["gross_amount"] = acc["gross_wages"]
        out["total_amount"] = float(_money(acc["gross_wages"] + adj + bonus + reimb))
        return out

    eligible_hours = _money(regular + ot)
    if cat in ("contractor_1099", "temp") and uid and batch_id and line_id:
        from backend.payroll_accrual import reverse_ledger_entries_for_line

        reverse_ledger_entries_for_line(conn, organization_id, int(line_id), created_by=created_by)
        manual_hc = body.get("health_credit_amount")
        hc = process_contractor_line_health_credit(
            conn,
            organization_id,
            user_id=int(uid),
            worker_category=cat,
            batch_id=int(batch_id),
            line_id=int(line_id),
            eligible_hours=eligible_hours,
            manual_health_credit=_money(manual_hc) if manual_hc is not None else None,
            manual_note=body.get("health_credit_note"),
            period_start=str(period_start) if period_start else None,
            period_end=str(period_end) if period_end else None,
            created_by=created_by,
        )
        out["health_credit_amount"] = hc["health_credit_amount"]
        if cat == "contractor_1099":
            legacy_hc_hours = float(body.get("health_safety_credit_hours") or 0)
            amounts = compute_payment_summary_amounts(regular, rate, legacy_hc_hours, 0)
            base = amounts["service_amount"]
            out["gross_amount"] = base
            out["total_amount"] = float(
                _money(base + hc["health_credit_amount"] + adj + bonus + reimb)
            )
        else:
            base = float(_money(regular * rate))
            out["gross_amount"] = base
            out["total_amount"] = float(
                _money(base + hc["health_credit_amount"] + adj + bonus + reimb)
            )
        return out

    if cat == "contractor_1099":
        amounts = compute_payment_summary_amounts(
            regular, rate, body.get("health_safety_credit_hours") or 0, adj
        )
        out["gross_amount"] = amounts["service_amount"]
        out["total_amount"] = amounts["total_payment"] + bonus + reimb
    else:
        base = float(_money((regular + ot) * rate))
        out["gross_amount"] = base
        out["total_amount"] = base + adj + bonus + reimb
    return out


def update_payout_batch_line(
    conn, organization_id: int, batch_id: int, line_id: int, body: dict
) -> dict:
    batch = _fetch_payout_batch_core(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    cuid = conn.cursor(dictionary=True)
    cuid.execute(
        "SELECT user_id FROM payout_batch_lines WHERE id=%s AND batch_id=%s",
        (int(line_id), int(batch_id)),
    )
    u = cuid.fetchone() or {}
    uid = u.get("user_id")
    amounts = _compute_payout_line_amounts(
        conn,
        organization_id,
        batch,
        body,
        user_id=int(uid) if uid else None,
        batch_id=int(batch_id),
        line_id=int(line_id),
    )
    hours = amounts["approved_hours"]
    rate = amounts["rate"]
    adj = amounts["adjustments"]
    gross = amounts["gross_amount"]
    total = amounts["total_amount"]
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batch_lines SET
          approved_hours=%s, rate=%s, gross_amount=%s, adjustments=%s, total_amount=%s,
          ot_hours=%s, sick_hours_accrued=%s, sick_hours_used=%s, sick_pay_amount=%s,
          health_credit_amount=%s, bonus_tip_amount=%s, reimbursement_amount=%s,
          line_status=%s, notes=%s
        WHERE id=%s AND batch_id=%s AND organization_id=%s
        """,
        (
            hours,
            rate,
            gross,
            adj,
            total,
            amounts.get("ot_hours") or 0,
            amounts.get("sick_hours_accrued") or 0,
            amounts.get("sick_hours_used") or 0,
            amounts.get("sick_pay_amount") or 0,
            amounts.get("health_credit_amount") or 0,
            amounts.get("bonus_tip_amount") or 0,
            amounts.get("reimbursement_amount") or 0,
            str(body.get("line_status") or "pending_approval"),
            body.get("notes"),
            int(line_id),
            int(batch_id),
            int(organization_id),
        ),
    )
    _recompute_batch_totals(conn, batch_id)
    if batch["worker_category"] == "w2" and uid:
        from backend.payroll_workflow import persist_w2_line_taxes

        persist_w2_line_taxes(
            conn,
            organization_id,
            int(line_id),
            int(uid),
            gross,
            pay_period_start=str(batch.get("pay_period_start") or "") or None,
        )
    conn.commit()
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM payout_batch_lines WHERE id=%s", (int(line_id),))
    return json_safe(c2.fetchone() or {})


def update_payout_batch_status(
    conn, organization_id: int, batch_id: int, status: str, *, actor_id: Optional[int] = None
) -> Optional[dict]:
    if status not in BATCH_STATUSES:
        raise ValueError("Invalid batch status")
    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor()
    extra = ""
    if status == "sent_to_accountant":
        extra = ", sent_to_accountant_at=COALESCE(sent_to_accountant_at, NOW())"
    elif status == "paid":
        extra = ", paid_at=COALESCE(paid_at, NOW())"
    c.execute(
        f"""
        UPDATE payout_batches SET status=%s, approved_by=COALESCE(approved_by, %s),
        updated_at=CURRENT_TIMESTAMP{extra}
        WHERE id=%s AND organization_id=%s
        """,
        (status, actor_id, int(batch_id), int(organization_id)),
    )
    return get_payout_batch(conn, organization_id, batch_id)


def add_payout_batch_line(
    conn, organization_id: int, batch_id: int, body: dict
) -> dict:
    batch = _fetch_payout_batch_core(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    line_cat = str(body.get("worker_category") or batch["worker_category"])
    if line_cat != batch["worker_category"]:
        raise ValueError("Line worker_category must match batch category")
    uid = body.get("user_id")
    if uid:
        uid = int(uid)
        if worker_category_for_user(conn, uid) != batch["worker_category"]:
            raise ValueError("Worker category does not match batch")
    name = (body.get("worker_name_snapshot") or body.get("worker_name") or "").strip()
    if not name and uid:
        u = fetch_payroll_profile_row(conn, uid)
        if u:
            name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
    if not name:
        raise ValueError("worker_name required")
    from backend.payroll_workflow import apply_w2_fields_on_line_insert, ensure_payout_batch_line_extensions

    ensure_payout_batch_line_extensions(conn.cursor())
    w2_extra = {}
    stub_gross = float(_money(body.get("approved_hours") or 0) * _money(body.get("rate") or 0))
    if uid and batch["worker_category"] == "w2":
        w2_extra = apply_w2_fields_on_line_insert(
            conn, int(uid), batch["worker_category"], stub_gross, organization_id
        )
    payment_status = str(body.get("payment_status") or "pending")
    tax_calc_status = w2_extra.get("tax_calc_status") or (
        "not_applicable" if batch["worker_category"] != "w2" else "pending"
    )
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO payout_batch_lines (
          batch_id, organization_id, user_id, worker_name_snapshot, worker_category,
          approved_hours, rate, gross_amount, adjustments, total_amount,
          payment_method, payment_reference, payment_date, line_status,
          document_status, notes, gross_wages, source_type, source_shift_session_ids,
          payment_status, tax_calc_status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(batch_id),
            int(organization_id),
            uid,
            name[:255],
            line_cat,
            float(_money(body.get("approved_hours") or 0)),
            float(_money(body.get("rate") or 0)),
            stub_gross,
            float(_money(body.get("adjustments") or 0)),
            stub_gross,
            (body.get("payment_method") or "")[:64] or None,
            (body.get("payment_reference") or "")[:255] or None,
            body.get("payment_date"),
            str(body.get("line_status") or "pending_approval"),
            body.get("document_status"),
            body.get("notes"),
            w2_extra.get("gross_wages") if batch["worker_category"] == "w2" else None,
            str(body.get("source_type") or "manual"),
            json.dumps(body.get("source_shift_session_ids"))
            if body.get("source_shift_session_ids")
            else None,
            payment_status,
            tax_calc_status,
        ),
    )
    line_id = int(c.lastrowid)
    amounts = _compute_payout_line_amounts(
        conn,
        organization_id,
        batch,
        body,
        user_id=int(uid) if uid else None,
        batch_id=int(batch_id),
        line_id=line_id,
    )
    gross = amounts["gross_amount"]
    total = amounts["total_amount"]
    c.execute(
        """
        UPDATE payout_batch_lines SET
          approved_hours=%s, rate=%s, gross_amount=%s, adjustments=%s, total_amount=%s,
          ot_hours=%s, sick_hours_accrued=%s, sick_hours_used=%s, sick_pay_amount=%s,
          health_credit_amount=%s, bonus_tip_amount=%s, reimbursement_amount=%s,
          gross_wages=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            amounts["approved_hours"],
            amounts["rate"],
            gross,
            amounts["adjustments"],
            total,
            amounts.get("ot_hours") or 0,
            amounts.get("sick_hours_accrued") or 0,
            amounts.get("sick_hours_used") or 0,
            amounts.get("sick_pay_amount") or 0,
            amounts.get("health_credit_amount") or 0,
            amounts.get("bonus_tip_amount") or 0,
            amounts.get("reimbursement_amount") or 0,
            gross if batch["worker_category"] == "w2" else None,
            line_id,
            int(organization_id),
        ),
    )
    _recompute_batch_totals(conn, batch_id)
    if uid and batch["worker_category"] == "w2":
        from backend.payroll_workflow import persist_w2_line_taxes

        persist_w2_line_taxes(
            conn,
            organization_id,
            line_id,
            int(uid),
            gross,
            pay_period_start=str(batch.get("pay_period_start") or "") or None,
        )
    conn.commit()
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM payout_batch_lines WHERE id=%s", (line_id,))
    return json_safe(c2.fetchone() or {})


def build_batch_from_time_records(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    from_date: str,
    to_date: str,
    allow_empty: bool = False,
) -> dict:
    batch = _fetch_payout_batch_core(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        raise ValueError("Only draft or hours-reviewed batches can sync from time records")
    fd = from_date or batch.get("pay_period_start")
    td = to_date or batch.get("pay_period_end")
    records = list_time_records(
        conn,
        organization_id,
        from_date=fd,
        to_date=td,
        worker_category=batch["worker_category"],
        status_filter="approved",
    )
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM payout_batch_lines
        WHERE batch_id=%s AND organization_id=%s AND source_type='clock_records'
        """,
        (int(batch_id), int(organization_id)),
    )
    if not records:
        _recompute_batch_totals(conn, batch_id)
        conn.commit()
        if allow_empty:
            return get_payout_batch(conn, organization_id, batch_id) or {}
        raise ValueError(
            "No approved time records in this period. Approve hours on the Time Records tab first."
        )
    by_user: dict[int, dict] = {}
    for rec in records:
        uid = int(rec["user_id"])
        if uid not in by_user:
            by_user[uid] = {
                "user_id": uid,
                "worker_name": rec["worker_name"],
                "hours": 0.0,
                "session_ids": [],
            }
        by_user[uid]["hours"] += float(rec.get("approved_hours") or 0)
        by_user[uid]["session_ids"].append(rec["id"])
    for uid, agg in by_user.items():
        from backend.payroll_workflow import resolve_rate_for_batch_line

        rate = resolve_rate_for_batch_line(conn, organization_id, uid)
        add_payout_batch_line(
            conn,
            organization_id,
            batch_id,
            {
                "user_id": uid,
                "worker_name_snapshot": agg["worker_name"],
                "approved_hours": agg["hours"],
                "rate": rate,
                "adjustments": 0,
                "line_status": "approved",
                "source_type": "clock_records",
                "source_shift_session_ids": agg["session_ids"],
            },
        )
    conn.commit()
    from backend.payroll_workflow import recalculate_w2_batch_taxes

    recalculate_w2_batch_taxes(conn, organization_id, batch_id)
    return get_payout_batch(conn, organization_id, batch_id) or {}


def accountant_ytd_summary(
    conn, organization_id: int, *, year: Optional[int] = None, worker_category: Optional[str] = None
) -> list[dict]:
    year = int(year or date.today().year)
    if not payroll_profiles_active(conn):
        return []
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pp.user_id, pp.first_name, pp.last_name
        FROM payroll_profiles pp
        JOIN users u ON u.id = pp.user_id
        WHERE u.organization_id = %s
        ORDER BY pp.last_name, pp.first_name
        """,
        (int(organization_id),),
    )
    out = []
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        cat = worker_category_for_user(conn, uid)
        if worker_category and worker_category != "all" and cat != worker_category:
            continue
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        ytd_paid = 0.0
        payment_count = 0
        last_payment = None
        if cat in ("contractor_1099", "temp"):
            y = sum_payments_ytd(conn, organization_id, uid, year=year)
            ytd_paid = float(y.get("total_paid_ytd") or 0)
            payment_count = int(y.get("payment_count") or 0)
        ensure_payout_batches_tables(conn.cursor())
        c2 = conn.cursor(dictionary=True)
        c2.execute(
            """
            SELECT COALESCE(SUM(pbl.total_amount), 0) AS paid,
                   COUNT(*) AS cnt,
                   MAX(pbl.payment_date) AS last_dt
            FROM payout_batch_lines pbl
            JOIN payout_batches pb ON pb.id = pbl.batch_id
            WHERE pb.organization_id = %s AND pbl.user_id = %s
              AND pb.worker_category = %s
              AND pb.status IN ('paid', 'closed', 'approved_for_payment')
              AND YEAR(COALESCE(pbl.payment_date, pb.pay_period_end)) = %s
            """,
            (int(organization_id), uid, cat, year),
        )
        pl = c2.fetchone() or {}
        batch_paid = float(pl.get("paid") or 0)
        if batch_paid > ytd_paid:
            ytd_paid = batch_paid
        payment_count += int(pl.get("cnt") or 0)
        if pl.get("last_dt"):
            last_payment = str(pl["last_dt"])[:10]
        weeks = max(1, payment_count)
        out.append(
            json_safe(
                {
                    "user_id": uid,
                    "worker_name": name,
                    "worker_category": cat,
                    "worker_category_label": CATEGORY_LABELS.get(cat, cat),
                    "year": year,
                    "total_paid_ytd": ytd_paid,
                    "payment_count": payment_count,
                    "avg_weekly_pay": round(ytd_paid / weeks, 2),
                    "avg_monthly_pay": round(ytd_paid / max(1, weeks / 4.33), 2),
                    "last_payment_date": last_payment,
                    "reporting_threshold_warning": cat != "w2" and ytd_paid >= 600,
                }
            )
        )
    return out
