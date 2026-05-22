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
from backend.payroll_identity import fetch_payroll_profile_row, payroll_profiles_active
from backend.ta_helpers import json_safe, table_exists, table_has_column


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


def time_record_status(row: dict) -> str:
    st = str(row.get("status") or "")
    if st == "active":
        return "open"
    if bool(row.get("manual_override")) or bool(row.get("needs_correction")):
        return "needs_correction"
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
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    has_remarks = table_has_column(chk, "shift_sessions", "period_adjustment_remarks")
    has_override = table_has_column(chk, "shift_sessions", "manual_override")
    has_review = table_has_column(chk, "payroll_cycles", "review_state")
    remarks_sel = (
        ", s.period_adjustment_remarks"
        if has_remarks
        else ", NULL AS period_adjustment_remarks"
    )
    override_sel = ", s.manual_override" if has_override else ", 0 AS manual_override"
    review_sel = ", pc.review_state AS payroll_cycle_review_state" if has_review else ""
    if has_ss_org:
        org_clause = "s.organization_id = %s"
    else:
        org_clause = "u.organization_id = %s"
    c = conn.cursor(dictionary=True)
    q = f"""
        SELECT s.id, s.user_id, s.clock_in_at, s.clock_out_at, s.status,
               s.total_break_seconds, s.net_work_seconds
               {override_sel}{remarks_sel},
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
    out = []
    for row in rows:
        cat = worker_category_for_user(conn, int(row["user_id"]))
        if worker_category and worker_category != "all" and cat != worker_category:
            continue
        net = int(row.get("net_work_seconds") or 0)
        approved_sec = net
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
            "status": time_record_status(row),
            "notes": row.get("period_adjustment_remarks") or "",
            "needs_correction": bool(row.get("manual_override")),
        }
        if status_filter and status_filter != "all" and rec["status"] != status_filter:
            continue
        out.append(json_safe(rec))
    return out


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


def get_payout_batch(conn, organization_id: int, batch_id: int) -> Optional[dict]:
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
    return get_payout_batch(conn, organization_id, batch_id) or {}


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
    batch = get_payout_batch(conn, organization_id, batch_id)
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
    hours = float(_money(body.get("approved_hours")))
    rate = float(_money(body.get("rate")))
    adj = float(_money(body.get("adjustments")))
    if batch["worker_category"] == "contractor_1099":
        amounts = compute_payment_summary_amounts(
            hours, rate, body.get("health_safety_credit_hours") or 0, adj
        )
        gross = amounts["service_amount"]
        total = amounts["total_payment"]
    else:
        gross = float(_money(hours * rate))
        total = gross + adj
    name = (body.get("worker_name_snapshot") or body.get("worker_name") or "").strip()
    if not name and uid:
        u = fetch_payroll_profile_row(conn, uid)
        if u:
            name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
    if not name:
        raise ValueError("worker_name required")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO payout_batch_lines (
          batch_id, organization_id, user_id, worker_name_snapshot, worker_category,
          approved_hours, rate, gross_amount, adjustments, total_amount,
          payment_method, payment_reference, payment_date, line_status,
          document_status, notes, gross_wages, source_type, source_shift_session_ids
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(batch_id),
            int(organization_id),
            uid,
            name[:255],
            line_cat,
            hours,
            rate,
            gross,
            adj,
            total,
            (body.get("payment_method") or "")[:64] or None,
            (body.get("payment_reference") or "")[:255] or None,
            body.get("payment_date"),
            str(body.get("line_status") or "pending"),
            body.get("document_status"),
            body.get("notes"),
            gross if batch["worker_category"] == "w2" else None,
            str(body.get("source_type") or "manual"),
            json.dumps(body.get("source_shift_session_ids"))
            if body.get("source_shift_session_ids")
            else None,
        ),
    )
    _recompute_batch_totals(conn, batch_id)
    line_id = int(c.lastrowid)
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM payout_batch_lines WHERE id=%s", (line_id,))
    return json_safe(c2.fetchone() or {})


def build_batch_from_time_records(
    conn, organization_id: int, batch_id: int, *, from_date: str, to_date: str
) -> dict:
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    records = list_time_records(
        conn,
        organization_id,
        from_date=from_date,
        to_date=to_date,
        worker_category=batch["worker_category"],
        status_filter="approved",
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
        rate = 0.0
        if batch["worker_category"] != "temp":
            try:
                from backend.contractor_management import build_contractor_prefill

                pre = build_contractor_prefill(conn, uid, organization_id)
                rate = float(pre.get("rate_per_hour") or 0)
            except Exception:
                rate = 0.0
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
                "source_type": "clock_records",
                "source_shift_session_ids": agg["session_ids"],
            },
        )
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
