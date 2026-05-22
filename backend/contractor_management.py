"""1099 contractor forms: list contractors from payroll, prefill, payment summaries."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from backend.hr_compliance import ensure_hr_extended_profiles_table, fetch_hr_org_settings
from backend.hr_forms.delivery import infer_user_form_lanes
from backend.payroll_identity import fetch_payroll_profile_row, payroll_profiles_active
from backend.ta_helpers import json_safe, table_exists, table_has_column


def ensure_contractor_payment_summaries_table(cursor) -> None:
    if not table_exists(cursor, "contractor_payment_summaries"):
        cursor.execute(
            """
            CREATE TABLE contractor_payment_summaries (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              user_id INT NULL,
              contractor_type VARCHAR(32) NOT NULL DEFAULT 'regular',
              worker_name_snapshot VARCHAR(255) NULL,
              worker_phone_snapshot VARCHAR(64) NULL,
              worker_email_snapshot VARCHAR(255) NULL,
              work_performed TEXT NULL,
              pay_period_start DATE NULL,
              pay_period_end DATE NULL,
              invoice_date DATE NULL,
              approved_service_hours DECIMAL(10,2) NOT NULL DEFAULT 0,
              service_rate DECIMAL(10,2) NOT NULL DEFAULT 0,
              health_safety_credit_hours DECIMAL(10,2) NOT NULL DEFAULT 0,
              adjustments DECIMAL(10,2) NOT NULL DEFAULT 0,
              service_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
              health_safety_credit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
              total_payment DECIMAL(10,2) NOT NULL DEFAULT 0,
              total_amount_due DECIMAL(10,2) NULL,
              amount_paid DECIMAL(10,2) NULL,
              payment_date DATE NULL,
              payment_method VARCHAR(64) NULL,
              payment_reference VARCHAR(255) NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'paid',
              notes TEXT NULL,
              form_snapshot_json JSON NULL,
              clock_hours_source VARCHAR(32) NOT NULL DEFAULT 'manual',
              source_type VARCHAR(32) NOT NULL DEFAULT 'manual',
              source_clock_batch_id INT NULL,
              signed_document_record_id BIGINT NULL,
              created_by INT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_cps_org_user (organization_id, user_id, created_at),
              INDEX idx_cps_org_year (organization_id, payment_date),
              CONSTRAINT fk_cps_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )
        return
    extras = [
        ("contractor_type", "VARCHAR(32) NOT NULL DEFAULT 'regular'"),
        ("worker_name_snapshot", "VARCHAR(255) NULL"),
        ("worker_phone_snapshot", "VARCHAR(64) NULL"),
        ("worker_email_snapshot", "VARCHAR(255) NULL"),
        ("work_performed", "TEXT NULL"),
        ("total_amount_due", "DECIMAL(10,2) NULL"),
        ("amount_paid", "DECIMAL(10,2) NULL"),
        ("payment_date", "DATE NULL"),
        ("status", "VARCHAR(32) NOT NULL DEFAULT 'paid'"),
        ("source_type", "VARCHAR(32) NOT NULL DEFAULT 'manual'"),
        ("source_clock_batch_id", "INT NULL"),
        ("signed_document_record_id", "BIGINT NULL"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    ]
    for col, typedef in extras:
        if not table_has_column(cursor, "contractor_payment_summaries", col):
            cursor.execute(
                f"ALTER TABLE contractor_payment_summaries ADD COLUMN {col} {typedef}"
            )
    if table_has_column(cursor, "contractor_payment_summaries", "user_id"):
        try:
            cursor.execute(
                "ALTER TABLE contractor_payment_summaries MODIFY user_id INT NULL"
            )
        except Exception:
            pass


def _user_form_lanes(conn, user_id: int) -> list[str]:
    try:
        return infer_user_form_lanes(conn, int(user_id))
    except Exception:
        return []


def user_is_contractor(conn, user_id: int) -> bool:
    return "contractor_1099" in _user_form_lanes(conn, user_id)


def user_is_short_term_temp(conn, user_id: int) -> bool:
    return "temp_worker" in _user_form_lanes(conn, user_id)


def user_in_contractor_management(conn, user_id: int) -> bool:
    lanes = _user_form_lanes(conn, user_id)
    return "contractor_1099" in lanes or "temp_worker" in lanes


def worker_kind_for_user(conn, user_id: int) -> str:
    lanes = _user_form_lanes(conn, user_id)
    has_1099 = "contractor_1099" in lanes
    has_temp = "temp_worker" in lanes
    if has_temp and not has_1099:
        return "short_term"
    if has_1099 and not has_temp:
        return "1099"
    if has_1099 and has_temp:
        return "1099_and_temp"
    return "other"


def _json_load(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return None


def _money(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def compute_payment_summary_amounts(
    approved_hours: Any,
    service_rate: Any,
    health_safety_credit_hours: Any,
    adjustments: Any,
) -> dict[str, float]:
    hours = _money(approved_hours)
    rate = _money(service_rate)
    hs_hours = _money(health_safety_credit_hours)
    adj = _money(adjustments)
    service_amount = (hours * rate).quantize(Decimal("0.01"))
    hs_amount = (hs_hours * rate).quantize(Decimal("0.01"))
    total = (service_amount + hs_amount + adj).quantize(Decimal("0.01"))
    return {
        "service_amount": float(service_amount),
        "health_safety_credit_amount": float(hs_amount),
        "total_payment": float(total),
    }


def _latest_hourly_rate(conn, user_id: int) -> Optional[float]:
    cur = conn.cursor()
    if not table_exists(cur, "user_rates"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT ur.hourly_rate
        FROM user_rates ur
        WHERE ur.user_id = %s
          AND (ur.end_date IS NULL OR ur.end_date >= CURDATE())
        ORDER BY ur.effective_date DESC, ur.id DESC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone()
    if not row or row.get("hourly_rate") is None:
        return None
    return float(row["hourly_rate"])


def _latest_payment_method_label(conn, user_id: int) -> Optional[str]:
    cur = conn.cursor()
    if not table_exists(cur, "payroll_payments"):
        return None
    if not table_exists(cur, "payment_methods"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pm.name
        FROM payroll_payments pp
        JOIN payment_methods pm ON pm.id = pp.payment_method_id
        WHERE pp.user_id = %s AND pp.payment_method_id IS NOT NULL
        ORDER BY pp.updated_at DESC, pp.id DESC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone()
    return str(row["name"]).strip() if row and row.get("name") else None


def _contractor_json_from_hr(conn, user_id: int) -> dict:
    cur = conn.cursor()
    ensure_hr_extended_profiles_table(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT contractor_json, emergency_contacts_json FROM hr_extended_profiles WHERE user_id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone() or {}
    cj = _json_load(row.get("contractor_json")) or {}
    if not isinstance(cj, dict):
        cj = {}
    ec = _json_load(row.get("emergency_contacts_json"))
    return cj, ec if isinstance(ec, list) else []


def _format_emergency_contact(contacts: list) -> str:
    if not contacts:
        return ""
    c0 = contacts[0] if isinstance(contacts[0], dict) else {}
    parts = [
        str(c0.get("name") or "").strip(),
        str(c0.get("relationship") or "").strip(),
        str(c0.get("phone") or c0.get("alt_phone") or "").strip(),
    ]
    return " — ".join(p for p in parts if p)


def _employment_category_summary(conn, user_id: int) -> str:
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT ec.name, ec.code
            FROM user_employment_categories uec
            JOIN employment_categories ec ON ec.id = uec.employment_category_id
            WHERE uec.user_id = %s
              AND uec.effective_from <= CURDATE()
              AND (uec.effective_to IS NULL OR uec.effective_to >= CURDATE())
            ORDER BY uec.effective_from DESC
            """,
            (int(user_id),),
        )
        rows = c.fetchall() or []
    except Exception:
        return ""
    names = [str(r.get("name") or r.get("code") or "").strip() for r in rows if r]
    return ", ".join(n for n in names if n)


def build_contractor_prefill(conn, user_id: int, organization_id: int) -> dict[str, Any]:
    u = fetch_payroll_profile_row(conn, int(user_id))
    if not u:
        raise ValueError("No payroll profile for this user")
    cj, emergency = _contractor_json_from_hr(conn, user_id)
    org = fetch_hr_org_settings(conn, int(organization_id))
    first = str(u.get("first_name") or "").strip()
    last = str(u.get("last_name") or "").strip()
    full_name = " ".join(p for p in (first, last) if p).strip()
    rate = cj.get("rate_per_hour") or cj.get("hourly_rate") or _latest_hourly_rate(conn, user_id)
    pm = (
        str(cj.get("payment_method") or "").strip()
        or _latest_payment_method_label(conn, user_id)
        or ""
    )
    active = bool(u.get("active", True))
    term = u.get("termination_date")
    if term:
        status = "Inactive"
    elif active:
        status = "Active"
    else:
        status = "Inactive"
    return json_safe(
        {
            "user_id": int(user_id),
            "contractor_id": str(u.get("employee_id") or user_id),
            "full_name": full_name,
            "first_name": first,
            "last_name": last,
            "business_name": str(cj.get("business_name") or cj.get("dba") or "").strip(),
            "phone": str(u.get("mobile") or cj.get("phone") or "").strip(),
            "email": str(u.get("email") or "").strip(),
            "address": str(u.get("address") or cj.get("address") or "").strip(),
            "emergency_contact": _format_emergency_contact(emergency)
            or str(cj.get("emergency_contact") or "").strip(),
            "service_type": str(cj.get("service_type") or "").strip()
            or _employment_category_summary(conn, user_id),
            "rate_per_hour": float(rate) if rate is not None else None,
            "payment_method": pm,
            "payment_cycle": str(cj.get("payment_cycle") or "Biweekly").strip(),
            "status": status,
            "start_date": str(u.get("hire_date") or "")[:10] if u.get("hire_date") else "",
            "onboarding_date": str(cj.get("onboarding_date") or u.get("hire_date") or "")[:10]
            if (cj.get("onboarding_date") or u.get("hire_date"))
            else "",
            "company_name": str(org.get("employer_name") or "VeeWash / Washpro").strip(),
            "company_address": str(
                org.get("employer_address")
                or "10438 Jamaica Avenue, Richmond Hill, NY 11418"
            ).strip(),
            "organization_logo_url": u.get("organization_logo_url"),
            "is_contractor": user_is_contractor(conn, user_id),
            "is_short_term": user_is_short_term_temp(conn, user_id),
            "worker_kind": worker_kind_for_user(conn, user_id),
        }
    )


def list_tenant_contractors(conn, organization_id: int) -> list[dict]:
    if not payroll_profiles_active(conn):
        return []
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pp.user_id
        FROM payroll_profiles pp
        JOIN users u ON u.id = pp.user_id
        WHERE u.organization_id = %s
        ORDER BY pp.last_name, pp.first_name
        """,
        (int(organization_id),),
    )
    out: list[dict] = []
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        if not user_in_contractor_management(conn, uid):
            continue
        u = fetch_payroll_profile_row(conn, uid)
        if not u:
            continue
        pre = build_contractor_prefill(conn, uid, organization_id)
        kind = worker_kind_for_user(conn, uid)
        out.append(
            {
                "user_id": uid,
                "full_name": pre.get("full_name"),
                "contractor_id": pre.get("contractor_id"),
                "status": pre.get("status"),
                "rate_per_hour": pre.get("rate_per_hour"),
                "email": pre.get("email"),
                "worker_kind": kind,
                "is_short_term": kind in ("short_term", "1099_and_temp"),
            }
        )
    return out


def sum_payments_ytd(
    conn,
    organization_id: int,
    user_id: int,
    *,
    year: Optional[int] = None,
) -> dict[str, Any]:
    """Sum saved contractor payment summaries for calendar year (invoice/pay period date)."""
    ensure_contractor_payment_summaries_table(conn.cursor())
    y = int(year or date.today().year)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT COALESCE(SUM(COALESCE(amount_paid, total_payment)), 0) AS total_paid,
               COUNT(*) AS payment_count
        FROM contractor_payment_summaries
        WHERE organization_id = %s AND user_id = %s
          AND (status IS NULL OR status IN ('paid', 'finalized'))
          AND YEAR(COALESCE(payment_date, invoice_date, pay_period_end, DATE(created_at))) = %s
        """,
        (int(organization_id), int(user_id), y),
    )
    row = c.fetchone() or {}
    total = float(_money(row.get("total_paid")))
    return {
        "year": y,
        "total_paid_ytd": total,
        "payment_count": int(row.get("payment_count") or 0),
    }


def list_payment_summaries(conn, organization_id: int, user_id: int, *, limit: int = 50) -> list[dict]:
    ensure_contractor_payment_summaries_table(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT *
        FROM contractor_payment_summaries
        WHERE organization_id = %s AND user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(organization_id), int(user_id), int(limit)),
    )
    rows = c.fetchall() or []
    for r in rows:
        snap = _json_load(r.get("form_snapshot_json"))
        if isinstance(snap, dict):
            r["form_snapshot_json"] = snap
    return [json_safe(r) for r in rows]


def create_payment_summary(
    conn,
    organization_id: int,
    user_id: Optional[int],
    body: dict,
    *,
    created_by: Optional[int] = None,
) -> dict:
    ensure_contractor_payment_summaries_table(conn.cursor())
    hours = body.get("approved_hours") or body.get("approved_service_hours")
    adj = body.get("adjustment_amount") if body.get("adjustment_amount") is not None else body.get("adjustments")
    hs = body.get("health_safety_credit_hours") or 0
    if body.get("contractor_type") in ("temp", "one_time"):
        hs = 0
    amounts = compute_payment_summary_amounts(
        hours,
        body.get("service_rate"),
        hs,
        adj,
    )
    total_due = body.get("total_amount_due")
    if total_due is None:
        total_due = amounts["total_payment"]
    amount_paid = body.get("amount_paid")
    if amount_paid is None:
        amount_paid = total_due
    snapshot = body.get("form_snapshot_json")
    if not isinstance(snapshot, dict) and user_id:
        try:
            snapshot = build_contractor_prefill(conn, int(user_id), organization_id)
        except ValueError:
            snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    clock_src = str(body.get("clock_hours_source") or body.get("source_type") or "manual").strip() or "manual"
    if clock_src not in ("manual", "clock", "clock_records"):
        clock_src = "manual"
    status = str(body.get("status") or "paid").strip() or "paid"
    if status not in ("draft", "finalized", "paid", "void"):
        status = "paid"
    ctype = str(body.get("contractor_type") or "regular").strip() or "regular"
    if ctype not in ("regular", "temp", "one_time"):
        ctype = "regular"
    pay_date = body.get("payment_date") or body.get("invoice_date") or date.today().isoformat()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO contractor_payment_summaries (
          organization_id, user_id, contractor_type,
          worker_name_snapshot, worker_phone_snapshot, worker_email_snapshot, work_performed,
          pay_period_start, pay_period_end, invoice_date, payment_date,
          approved_service_hours, service_rate, health_safety_credit_hours, adjustments,
          service_amount, health_safety_credit_amount, total_payment,
          total_amount_due, amount_paid, status,
          payment_method, payment_reference, notes, form_snapshot_json,
          clock_hours_source, source_type, source_clock_batch_id,
          signed_document_record_id, created_by
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """,
        (
            int(organization_id),
            int(user_id) if user_id else None,
            ctype,
            (body.get("worker_name") or body.get("worker_name_snapshot") or "")[:255] or None,
            (body.get("worker_phone") or body.get("worker_phone_snapshot") or "")[:64] or None,
            (body.get("worker_email") or body.get("worker_email_snapshot") or "")[:255] or None,
            body.get("work_performed"),
            body.get("work_period_start") or body.get("pay_period_start") or None,
            body.get("work_period_end") or body.get("pay_period_end") or None,
            body.get("invoice_date") or date.today().isoformat(),
            pay_date[:10] if pay_date else None,
            float(_money(hours)),
            float(_money(body.get("service_rate"))),
            float(_money(hs)),
            float(_money(adj)),
            amounts["service_amount"],
            amounts["health_safety_credit_amount"],
            float(_money(total_due)),
            float(_money(total_due)),
            float(_money(amount_paid)),
            status,
            (body.get("payment_method") or "")[:64] or None,
            (body.get("payment_reference") or "")[:255] or None,
            body.get("notes"),
            json.dumps(snapshot),
            clock_src,
            str(body.get("source_type") or clock_src)[:32],
            body.get("source_clock_batch_id"),
            body.get("signed_document_record_id"),
            created_by,
        ),
    )
    new_id = int(c.lastrowid)
    c2 = conn.cursor(dictionary=True)
    c2.execute(
        "SELECT * FROM contractor_payment_summaries WHERE id=%s LIMIT 1",
        (new_id,),
    )
    row = c2.fetchone() or {}
    row["form_snapshot_json"] = snapshot
    return json_safe(row)


CONTRACTOR_FORM_CATALOG = [
    {
        "id": "invoice_payment_receipt",
        "title": "Contractor Invoice & Payment Receipt",
        "interactive": True,
    },
    {
        "id": "first_time_packet",
        "title": "First-Time Contractor Packet",
        "sections": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
    },
    {
        "id": "rate_confirmation",
        "title": "Contractor Rate / Payment Confirmation",
        "sections": ["3"],
    },
    {"id": "written_warning", "title": "Written Warning / Notice", "sections": ["13"]},
    {"id": "probation_review", "title": "Two-Week Probation Review", "sections": ["14"]},
    {"id": "final_warning", "title": "Final Warning / Last Opportunity Notice", "sections": ["15"]},
    {
        "id": "termination_notice",
        "title": "Termination / Non-Offer of Future Assignments Notice",
        "sections": ["16"],
    },
    {"id": "incident_report", "title": "Incident / Injury Report", "sections": ["17"]},
    {
        "id": "clock_payment_correction",
        "title": "Clock / Payment Correction Request",
        "sections": ["18"],
    },
    {
        "id": "property_return_checklist",
        "title": "Property / Access Return Checklist",
        "sections": ["19"],
    },
]
