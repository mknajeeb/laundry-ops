"""HR Timeline — internal manager log for coaching, warnings, recognition, separation notes."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from backend.ta_helpers import json_safe, table_exists

HR_TIMELINE_ENTRY_TYPES = frozenset(
    {
        "coaching",
        "warning",
        "attendance_issue",
        "performance_issue",
        "safety_issue",
        "customer_complaint",
        "recognition",
        "separation_note",
        "management_note",
        "offer_letter",
    }
)

HR_TIMELINE_ENTRY_TYPE_LABELS = {
    "coaching": "Coaching",
    "warning": "Warning",
    "attendance_issue": "Attendance Issue",
    "performance_issue": "Performance Issue",
    "safety_issue": "Safety Issue",
    "customer_complaint": "Customer Complaint",
    "recognition": "Recognition",
    "separation_note": "Separation Note",
    "management_note": "Management Note",
    "offer_letter": "Offer Letter",
}

HR_TIMELINE_CATEGORIES = frozenset(
    {
        "Attendance & Reliability",
        "Productivity",
        "Quality",
        "Customer Item Care",
        "Conduct & Professionalism",
        "Safety",
        "Recognition",
        "General",
    }
)

DISCIPLINE_EMAIL_TEMPLATE_IDS = frozenset(
    {
        "coaching_late_arrival",
        "warning_pattern_tardiness",
        "warning_attendance_reliability",
        "separation_attendance",
        "warning_performance",
        "separation_performance",
        "warning_customer_quality",
        "separation_customer_serious",
    }
)

TEMPLATE_TO_ENTRY_TYPE = {
    "coaching_late_arrival": "coaching",
    "warning_pattern_tardiness": "warning",
    "warning_attendance_reliability": "warning",
    "separation_attendance": "separation_note",
    "warning_performance": "warning",
    "separation_performance": "separation_note",
    "warning_customer_quality": "warning",
    "separation_customer_serious": "separation_note",
}

TEMPLATE_TO_CATEGORY = {
    "coaching_late_arrival": "Attendance & Reliability",
    "warning_pattern_tardiness": "Attendance & Reliability",
    "warning_attendance_reliability": "Attendance & Reliability",
    "separation_attendance": "Attendance & Reliability",
    "warning_performance": "Productivity",
    "separation_performance": "Productivity",
    "warning_customer_quality": "Customer Item Care",
    "separation_customer_serious": "Customer Item Care",
}


def ensure_hr_timeline_table(cursor) -> None:
    if table_exists(cursor, "hr_timeline_entries"):
        return
    cursor.execute(
        """
        CREATE TABLE hr_timeline_entries (
          id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          entry_type VARCHAR(32) NOT NULL,
          category VARCHAR(64) NOT NULL,
          description TEXT NOT NULL,
          entry_date DATE NOT NULL,
          manager_user_id INT NOT NULL,
          manager_name_snapshot VARCHAR(255) NULL,
          attachment_uri VARCHAR(512) NULL,
          email_template_id VARCHAR(64) NULL,
          email_subject VARCHAR(512) NULL,
          email_body TEXT NULL,
          email_sent_at DATETIME NULL,
          created_by INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_hr_timeline_org_user (organization_id, user_id),
          INDEX idx_hr_timeline_entry_date (entry_date),
          INDEX idx_hr_timeline_type (entry_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _parse_entry_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    s = str(raw or "").strip()[:10]
    if not s:
        return date.today()
    return date.fromisoformat(s)


def _manager_display(conn, manager_user_id: int) -> str:
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT name, email FROM users WHERE id=%s LIMIT 1",
        (int(manager_user_id),),
    )
    row = c.fetchone() or {}
    name = (row.get("name") or "").strip()
    if name:
        return name
    return (row.get("email") or f"User {manager_user_id}").strip()


def _serialize_row(row: dict) -> dict:
    out = dict(row)
    for k in ("entry_date", "email_sent_at", "created_at", "updated_at"):
        v = out.get(k)
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat(timespec="seconds") if isinstance(v, datetime) else v.isoformat()
    out["entry_type_label"] = HR_TIMELINE_ENTRY_TYPE_LABELS.get(
        str(out.get("entry_type") or ""), out.get("entry_type")
    )
    return json_safe(out)


def list_hr_timeline_entries(
    conn,
    organization_id: int,
    user_id: int,
    *,
    limit: int = 200,
) -> list[dict]:
    ensure_hr_timeline_table(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM hr_timeline_entries
        WHERE organization_id=%s AND user_id=%s
        ORDER BY entry_date DESC, id DESC
        LIMIT %s
        """,
        (int(organization_id), int(user_id), int(limit)),
    )
    return [_serialize_row(dict(r)) for r in c.fetchall() or []]


def get_hr_timeline_entry(
    conn, organization_id: int, user_id: int, entry_id: int
) -> Optional[dict]:
    ensure_hr_timeline_table(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM hr_timeline_entries
        WHERE id=%s AND organization_id=%s AND user_id=%s
        LIMIT 1
        """,
        (int(entry_id), int(organization_id), int(user_id)),
    )
    row = c.fetchone()
    return _serialize_row(dict(row)) if row else None


def create_hr_timeline_entry(
    conn,
    organization_id: int,
    user_id: int,
    body: dict,
    *,
    actor_id: int,
) -> dict:
    ensure_hr_timeline_table(conn.cursor())
    entry_type = str(body.get("entry_type") or "").strip().lower()
    if entry_type not in HR_TIMELINE_ENTRY_TYPES:
        raise ValueError(f"Invalid entry_type: {entry_type}")
    category = str(body.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    description = str(body.get("description") or "").strip()
    if not description:
        raise ValueError("description is required")
    entry_date = _parse_entry_date(body.get("entry_date"))
    manager_user_id = int(body.get("manager_user_id") or actor_id)
    manager_name = str(body.get("manager_name_snapshot") or "").strip()
    if not manager_name:
        manager_name = _manager_display(conn, manager_user_id)
    attachment_uri = body.get("attachment_uri")
    if attachment_uri is not None:
        attachment_uri = str(attachment_uri).strip() or None
    email_template_id = body.get("email_template_id")
    if email_template_id is not None:
        email_template_id = str(email_template_id).strip() or None
    email_subject = body.get("email_subject")
    if email_subject is not None:
        email_subject = str(email_subject).strip() or None
    email_body = body.get("email_body")
    if email_body is not None:
        email_body = str(email_body).strip() or None
    email_sent = bool(body.get("email_sent"))
    email_sent_at = datetime.utcnow() if email_sent else None

    c = conn.cursor()
    c.execute(
        """
        INSERT INTO hr_timeline_entries (
          organization_id, user_id, entry_type, category, description, entry_date,
          manager_user_id, manager_name_snapshot, attachment_uri,
          email_template_id, email_subject, email_body, email_sent_at, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(user_id),
            entry_type,
            category,
            description,
            entry_date.isoformat(),
            manager_user_id,
            manager_name,
            attachment_uri,
            email_template_id,
            email_subject,
            email_body,
            email_sent_at,
            int(actor_id),
        ),
    )
    entry_id = c.lastrowid
    conn.commit()
    return get_hr_timeline_entry(conn, organization_id, user_id, int(entry_id)) or {}


def update_hr_timeline_entry(
    conn,
    organization_id: int,
    user_id: int,
    entry_id: int,
    body: dict,
    *,
    actor_id: int,
) -> dict:
    existing = get_hr_timeline_entry(conn, organization_id, user_id, entry_id)
    if not existing:
        raise ValueError("Timeline entry not found")
    fields: dict[str, Any] = {}
    if "entry_type" in body:
        et = str(body.get("entry_type") or "").strip().lower()
        if et not in HR_TIMELINE_ENTRY_TYPES:
            raise ValueError(f"Invalid entry_type: {et}")
        fields["entry_type"] = et
    if "category" in body:
        cat = str(body.get("category") or "").strip()
        if not cat:
            raise ValueError("category cannot be empty")
        fields["category"] = cat
    if "description" in body:
        desc = str(body.get("description") or "").strip()
        if not desc:
            raise ValueError("description cannot be empty")
        fields["description"] = desc
    if "entry_date" in body:
        fields["entry_date"] = _parse_entry_date(body.get("entry_date")).isoformat()
    if "manager_user_id" in body:
        fields["manager_user_id"] = int(body.get("manager_user_id"))
    if "manager_name_snapshot" in body:
        fields["manager_name_snapshot"] = str(body.get("manager_name_snapshot") or "").strip()
    if "attachment_uri" in body:
        uri = body.get("attachment_uri")
        fields["attachment_uri"] = str(uri).strip() if uri else None
    if "email_sent" in body and body.get("email_sent"):
        fields["email_sent_at"] = datetime.utcnow()
    if not fields:
        return existing
    cols = ", ".join(f"{k}=%s" for k in fields)
    vals = list(fields.values()) + [int(entry_id), int(organization_id), int(user_id)]
    c = conn.cursor()
    c.execute(
        f"UPDATE hr_timeline_entries SET {cols}, updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s AND user_id=%s",
        tuple(vals),
    )
    conn.commit()
    return get_hr_timeline_entry(conn, organization_id, user_id, entry_id) or {}


def delete_hr_timeline_entry(
    conn, organization_id: int, user_id: int, entry_id: int
) -> bool:
    ensure_hr_timeline_table(conn.cursor())
    c = conn.cursor()
    c.execute(
        "DELETE FROM hr_timeline_entries WHERE id=%s AND organization_id=%s AND user_id=%s",
        (int(entry_id), int(organization_id), int(user_id)),
    )
    conn.commit()
    return c.rowcount > 0


def render_discipline_email_template(
    template_id: str,
    *,
    worker_lane: str = "employee_w2",
    fields: Optional[dict] = None,
) -> dict:
    """Return subject + body for a discipline template (employee vs contractor wording)."""
    tid = str(template_id or "").strip()
    if tid not in DISCIPLINE_EMAIL_TEMPLATE_IDS:
        raise ValueError("Unknown email template")
    fields = dict(fields or {})
    is_contractor = str(worker_lane).startswith("contractor") or worker_lane == "contractor_1099"
    emp = "[your employment with VeeWash / WashPro is ending"
    con = "[the company is stopping future assignments"
    end_phrase = con if is_contractor else emp
    assign = "accepted assignments" if is_contractor else "shifts"
    shift = "assignment" if is_contractor else "shift"
    sep_conseq = "the company may stop offering assignments" if is_contractor else "employment may end"
    name = fields.get("worker_name") or "[Name]"
    manager = fields.get("manager_name") or "[Manager Name]"
    title = fields.get("manager_title") or "[Title]"
    today = fields.get("date") or "[Date]"
    location = fields.get("location") or "[location]"
    scheduled = fields.get("scheduled_start") or "[scheduled start time]"
    actual = fields.get("actual_time") or "[actual time]"
    issue = fields.get("issue_summary") or "[brief factual summary]"
    examples = fields.get("examples") or "[Date / time examples]"
    effective = fields.get("effective_date") or "[date / immediately]"
    contact = fields.get("contact_name") or "[contact name]"

    subjects = {
        "coaching_late_arrival": f"Coaching – Late Arrival – {name} – {today}",
        "warning_pattern_tardiness": f"Warning – Pattern of Tardiness – {name}",
        "warning_attendance_reliability": f"Warning – Attendance / Reliability – {name}",
        "separation_attendance": f"Separation Notice – Attendance – {name}",
        "warning_performance": f"Warning – Performance – {name}",
        "separation_performance": f"Separation Notice – Performance – {name}",
        "warning_customer_quality": f"Warning – Customer Item Care / Quality – {name}",
        "separation_customer_serious": f"Separation Notice – Serious Incident – {name}",
    }

    if tid == "coaching_late_arrival":
        body = (
            f"Hi {name},\n\n"
            f"This message documents coaching regarding your late arrival on {today} for your scheduled {shift} at {location}.\n\n"
            f"You were expected to be clocked in and ready to work at {scheduled}. You arrived / clocked in at {actual}.\n\n"
            f"Expectation: Arrive and clock in on time for every scheduled {shift}. "
            f"Being ready to work means clocked in and at your assigned station unless your supervisor directs otherwise.\n\n"
            f"Category: Attendance & Reliability\n\n"
            f"This is coaching, not a formal warning. Per company policy, a second late arrival may result in a formal warning. "
            f"Continued tardiness or a pattern of attendance issues may result in {sep_conseq} at management discretion.\n\n"
            f"If you have questions, contact me directly.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "warning_pattern_tardiness":
        body = (
            f"Hi {name},\n\n"
            f"This is a formal warning regarding a pattern of tardiness.\n\n"
            f"Issue: Despite prior coaching, you have continued to arrive late for scheduled {assign}. Recent examples:\n{examples}\n\n"
            f"Category: Attendance & Reliability\n\n"
            f"Expectation: You must arrive and clock in on time for every scheduled {shift}. Repeated lateness is not acceptable.\n\n"
            f"Consequence: If this pattern continues, {sep_conseq} without further warning.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "warning_attendance_reliability":
        body = (
            f"Hi {name},\n\n"
            f"This is a formal warning regarding attendance and reliability.\n\n"
            f"Issue: {issue}\n\n"
            f"Dates / examples:\n{examples}\n\n"
            f"Category: Attendance & Reliability\n\n"
            f"Expectation: Follow the call-out procedure in the Performance Standards Addendum. "
            f"Notify management before missing work when possible.\n\n"
            f"Consequence: Continued attendance or reliability problems may result in {sep_conseq}.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "separation_attendance":
        body = (
            f"Hi {name},\n\n"
            f"This message serves as notice that {end_phrase}] effective {effective}.\n\n"
            f"Reason: Attendance and reliability. Specifically: {issue}\n\n"
            f"Category: Attendance & Reliability\n\n"
            f"Company property: Return keys, access cards, and company materials as directed. "
            f"Contact {contact} for final pay / payment / property questions.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "warning_performance":
        body = (
            f"Hi {name},\n\n"
            f"This is a formal warning regarding performance.\n\n"
            f"Issue: {issue}\n\n"
            f"Examples / period reviewed: {examples}\n\n"
            f"Category: Productivity / Quality\n\n"
            f"Expectation: Meet operational standards established by management in Performance Settings, dashboards, or supervisor direction. Improvement is required immediately.\n\n"
            f"Consequence: Continued underperformance may result in {sep_conseq}.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "separation_performance":
        body = (
            f"Hi {name},\n\n"
            f"This message serves as notice that {end_phrase}] effective {effective}.\n\n"
            f"Reason: Performance. Summary: {issue}\n\n"
            f"Category: Productivity / Quality\n\n"
            f"Contact {contact} for final pay / payment questions.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    elif tid == "warning_customer_quality":
        body = (
            f"Hi {name},\n\n"
            f"This is a formal warning regarding customer item care and/or quality.\n\n"
            f"Issue: {issue}\n\n"
            f"Incident(s): {examples}\n\n"
            f"Category: Customer Item Care / Quality\n\n"
            f"Expectation: Handle garments and linens carefully, follow labels and instructions, report problems immediately.\n\n"
            f"Consequence: Further incidents may result in {sep_conseq}. Serious incidents may result in immediate action without further warning.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )
    else:  # separation_customer_serious
        body = (
            f"Hi {name},\n\n"
            f"This message serves as notice that {end_phrase} immediately], effective {effective}.\n\n"
            f"Reason: {issue}\n\n"
            f"Category: Customer Item Care / Quality / Conduct\n\n"
            f"Management exercised discretion under company policy. No prior warning was required if applicable.\n\n"
            f"Contact {contact} for payment / property questions only.\n\n"
            f"{manager}\n{title}\nVeeWash / WashPro\n{today}"
        )

    return {
        "template_id": tid,
        "subject": subjects[tid],
        "body": body,
        "entry_type": TEMPLATE_TO_ENTRY_TYPE[tid],
        "category": TEMPLATE_TO_CATEGORY.get(tid, "General"),
        "worker_lane": worker_lane,
    }


def create_discipline_email_timeline_entry(
    conn,
    organization_id: int,
    user_id: int,
    body: dict,
    *,
    actor_id: int,
) -> dict:
    template_id = str(body.get("template_id") or "").strip()
    worker_lane = str(body.get("worker_lane") or "employee_w2")
    fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    rendered = render_discipline_email_template(template_id, worker_lane=worker_lane, fields=fields)
    description = str(body.get("description") or rendered["body"]).strip()
    entry_date = body.get("entry_date") or fields.get("date") or date.today().isoformat()
    payload = {
        "entry_type": rendered["entry_type"],
        "category": body.get("category") or rendered["category"],
        "description": description,
        "entry_date": entry_date,
        "manager_user_id": body.get("manager_user_id") or actor_id,
        "manager_name_snapshot": body.get("manager_name_snapshot") or fields.get("manager_name"),
        "attachment_uri": body.get("attachment_uri"),
        "email_template_id": template_id,
        "email_subject": rendered["subject"],
        "email_body": rendered["body"],
        "email_sent": bool(body.get("email_sent")),
    }
    entry = create_hr_timeline_entry(conn, organization_id, user_id, payload, actor_id=actor_id)
    return {
        "entry": entry,
        "email": {
            "subject": rendered["subject"],
            "body": rendered["body"],
            "template_id": template_id,
        },
    }


def hr_timeline_meta() -> dict:
    return json_safe(
        {
            "entry_types": [
                {"id": k, "label": v} for k, v in HR_TIMELINE_ENTRY_TYPE_LABELS.items()
            ],
            "categories": sorted(HR_TIMELINE_CATEGORIES),
            "email_templates": [
                {"id": tid, "entry_type": TEMPLATE_TO_ENTRY_TYPE[tid], "category": TEMPLATE_TO_CATEGORY.get(tid)}
                for tid in sorted(DISCIPLINE_EMAIL_TEMPLATE_IDS)
            ],
        }
    )
