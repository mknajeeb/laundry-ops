"""
Phase 5E — mobile Revenue & Cost section entry.

Integration model
-----------------
Amounts authority remains ``dr_daily_entries`` / ``dr_daily_entry_lines``.
Mobile drafts/submissions live in ``drc_mobile_section_submissions``.

Employee submit: validate + calculate + snapshot only (status=submitted).
Manager approve: atomically apply stored snapshot into existing DRC lines.
Manager return: reopen for correction; never mutates DRC.

DRC line mapping on approval
----------------------------
Uses existing ``dr_daily_entries`` (unique org+entry_date) and upserts
``dr_daily_entry_lines`` by line_key:

- self_service → revenue.self_service.cash / .card
- drop_off → revenue.drop_off.cash / .card
- rinse → rinse WF pounds/amount + HD orders/amount
- commercial → commercial pounds/amount keys per account
- operating_costs → allowlisted cost variable keys

Insert when missing; update when empty/owned by this mobile submission.
Conflict (409) when a non-zero or foreign-sourced / override line already exists.

Business date: ``business_today()`` (America/New_York).

Section ownership: unique (organization_id, entry_date, section_key).
Revision: required expected_revision on draft save and submit (same pattern as 5D).

Section statuses: draft | submitted | approved | returned
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from backend.business_time import business_now, business_today
from backend.daily_revenue_cost_constants import (
    ENTRY_STATUS_OPEN,
    LK_COST_ADJUSTMENTS,
    LK_COST_MAINTENANCE,
    LK_COST_SUPPLIES,
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_RINSE_HD_AMOUNT,
    LK_RINSE_HD_ORDERS,
    LK_RINSE_WF_AMOUNT,
    LK_RINSE_WF_POUNDS,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    commercial_amount_key,
    commercial_pounds_key,
)
from backend.ta_helpers import table_exists


SECTION_SELF_SERVICE = "self_service"
SECTION_DROP_OFF = "drop_off"
SECTION_RINSE = "rinse"
SECTION_COMMERCIAL = "commercial"
SECTION_OPERATING_COSTS = "operating_costs"

SECTION_KEYS = (
    SECTION_SELF_SERVICE,
    SECTION_DROP_OFF,
    SECTION_RINSE,
    SECTION_COMMERCIAL,
    SECTION_OPERATING_COSTS,
)

SECTION_LABELS = {
    SECTION_SELF_SERVICE: "Self Service Revenue",
    SECTION_DROP_OFF: "Drop Off Revenue",
    SECTION_RINSE: "Rinse Revenue",
    SECTION_COMMERCIAL: "Commercial Revenue",
    SECTION_OPERATING_COSTS: "Operating Costs",
}

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_RETURNED = "returned"
# Legacy alias — normalize to returned when reading older rows.
STATUS_REJECTED = STATUS_RETURNED
TERMINAL_EMPLOYEE = frozenset({STATUS_SUBMITTED, STATUS_APPROVED})
EDITABLE_EMPLOYEE = frozenset({STATUS_DRAFT, STATUS_RETURNED})

WEEKDAY_ROWS = (
    (6, "Sunday"),
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
)

NOTIFY_DRC_MOBILE_SUBMITTED = "finance.drc.mobile_section.submitted"
NOTIFY_DRC_MOBILE_RETURNED = "finance.drc.mobile_section.returned"
NO_ASSIGNMENT_HELPER = "No Revenue & Cost entry assigned today."
DRAFT_CONFLICT_HELPER = (
    "This Revenue & Cost entry was updated on another device. "
    "Review the latest saved values, then retry your changes."
)
DAY_NOT_OPEN_HELPER = (
    "This business day is no longer open for mobile Revenue & Cost approval."
)
DRC_FIELD_CONFLICT_HELPER = (
    "This Revenue & Cost field already contains a value and was not overwritten."
)
SOURCE_MOBILE = "mobile"
CALC_VERSION = "drc_mobile_v1"
MAX_MONEY = Decimal("9999999.99")
MAX_QTY = Decimal("999999.99")
NOTE_MAX_LEN = 500

CONFLICT_TARGET_LINE = "target_line_conflict"
CONFLICT_DAY_NOT_OPEN = "day_not_open"
CONFLICT_NOT_SUBMITTED = "submission_not_submitted"
CONFLICT_REVISION = "revision_conflict"
CONFLICT_INVALID_SNAPSHOT = "invalid_snapshot"
CONFLICT_ORG_MISMATCH = "organization_mismatch"


def _normalize_status(raw: Any) -> str:
    st = str(raw or STATUS_DRAFT).lower().strip()
    if st == "rejected":
        return STATUS_RETURNED
    return st


# Operating-cost fields writable on mobile (explicit allowlist).
OPERATING_COST_FIELDS = (
    ("supplies", LK_COST_SUPPLIES, "Supplies"),
    ("maintenance", LK_COST_MAINTENANCE, "Maintenance"),
    ("adjustments", LK_COST_ADJUSTMENTS, "Adjustments"),
)


class DrcMobileEntryError(ValueError):
    def __init__(
        self,
        message: str,
        status: int = 400,
        *,
        conflict_type: str | None = None,
        audit_detail: dict | None = None,
        durable_conflict: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.conflict_type = conflict_type
        self.audit_detail = audit_detail or {}
        self.durable_conflict = bool(durable_conflict) or bool(conflict_type)


def approval_conflict_error(
    message: str,
    conflict_type: str,
    *,
    audit_detail: dict | None = None,
) -> DrcMobileEntryError:
    return DrcMobileEntryError(
        message,
        409,
        conflict_type=conflict_type,
        audit_detail=audit_detail or {},
        durable_conflict=True,
    )


def _naive_now() -> datetime:
    return business_now().replace(tzinfo=None)


def _parse_date(value: Any) -> date:
    if value is None or value == "":
        return business_today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def parse_money(raw: Any, *, allow_blank: bool = True) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None if allow_blank else Decimal("0")
    if isinstance(raw, bool):
        raise DrcMobileEntryError("Invalid money value.", 400)
    try:
        qty = Decimal(str(raw).strip().replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError, TypeError):
        raise DrcMobileEntryError("Value must be a number.", 400)
    if qty.is_nan() or qty.is_infinite():
        raise DrcMobileEntryError("Value must be a number.", 400)
    if qty < 0:
        raise DrcMobileEntryError("Value cannot be negative.", 400)
    if qty > MAX_MONEY:
        raise DrcMobileEntryError(f"Value cannot exceed {MAX_MONEY}.", 400)
    return qty


def parse_qty(raw: Any, *, allow_blank: bool = True) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None if allow_blank else Decimal("0")
    if isinstance(raw, bool):
        raise DrcMobileEntryError("Invalid quantity.", 400)
    try:
        qty = Decimal(str(raw).strip().replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        raise DrcMobileEntryError("Quantity must be a number.", 400)
    if qty.is_nan() or qty.is_infinite():
        raise DrcMobileEntryError("Quantity must be a number.", 400)
    if qty < 0:
        raise DrcMobileEntryError("Quantity cannot be negative.", 400)
    if qty > MAX_QTY:
        raise DrcMobileEntryError(f"Quantity cannot exceed {MAX_QTY}.", 400)
    return qty


def _parse_expected_revision(expected_revision: Any) -> int:
    if expected_revision is None or expected_revision == "":
        raise DrcMobileEntryError("expected_revision is required.", 400)
    try:
        return int(expected_revision)
    except (TypeError, ValueError):
        raise DrcMobileEntryError("Invalid draft revision.", 400)


def ensure_drc_mobile_entry_tables(cursor) -> None:
    """
    Idempotent schema ensure. Hot path skips CREATE TABLE IF NOT EXISTS when
    all three tables already exist (table_exists is process-cached). Prefer the
    controlled SQL migration ``backend/sql/drc_mobile_entry_v1.sql`` in production.
    """
    if (
        table_exists(cursor, "drc_weekday_section_assignments")
        and table_exists(cursor, "drc_mobile_section_submissions")
        and table_exists(cursor, "drc_mobile_section_events")
    ):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS drc_weekday_section_assignments (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          weekday TINYINT NOT NULL,
          section_key VARCHAR(40) NOT NULL,
          employee_id INT NULL,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          updated_by_user_id INT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE KEY uq_drc_weekday_org_day_section (organization_id, weekday, section_key),
          INDEX idx_drc_weekday_org_emp (organization_id, employee_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS drc_mobile_section_submissions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          entry_date DATE NOT NULL,
          section_key VARCHAR(40) NOT NULL,
          assigned_employee_id INT NOT NULL,
          assigned_employee_name VARCHAR(150) NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'draft',
          draft_revision INT NOT NULL DEFAULT 0,
          values_json JSON NULL,
          calculated_json JSON NULL,
          rate_snapshot_json JSON NULL,
          note VARCHAR(500) NULL,
          rejection_reason VARCHAR(500) NULL,
          daily_entry_id INT NULL,
          submitted_at DATETIME NULL,
          submitted_by_user_id INT NULL,
          reviewed_at DATETIME NULL,
          reviewed_by_user_id INT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_drc_mobile_org_date_section (organization_id, entry_date, section_key),
          INDEX idx_drc_mobile_org_status (organization_id, status),
          INDEX idx_drc_mobile_org_emp (organization_id, assigned_employee_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS drc_mobile_section_events (
          id INT AUTO_INCREMENT PRIMARY KEY,
          submission_id INT NOT NULL,
          organization_id INT NOT NULL,
          event_type VARCHAR(40) NOT NULL,
          actor_user_id INT NULL,
          detail_json JSON NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_drc_mobile_evt_sub (submission_id),
          INDEX idx_drc_mobile_evt_org (organization_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    from backend.ta_helpers import invalidate_schema_cache

    invalidate_schema_cache()


def _employee_display_name(cursor, organization_id: int, user_id: int) -> str:
    cursor.execute(
        """
        SELECT u.display_name, u.username, pp.first_name, pp.last_name
        FROM users u
        LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
        WHERE u.id=%s AND u.organization_id=%s
        LIMIT 1
        """,
        (int(user_id), int(organization_id)),
    )
    row = cursor.fetchone() or {}
    name = (row.get("display_name") or "").strip()
    if name:
        return name
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    combined = f"{first} {last}".strip()
    if combined:
        return combined
    return (row.get("username") or f"User {user_id}").strip()


def _log_event(cursor, submission_id: int, organization_id: int, event_type: str, *, actor_user_id=None, detail=None):
    cursor.execute(
        """
        INSERT INTO drc_mobile_section_events
          (submission_id, organization_id, event_type, actor_user_id, detail_json, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        """,
        (
            int(submission_id),
            int(organization_id),
            str(event_type)[:40],
            actor_user_id,
            _json_dump(detail) if detail is not None else None,
        ),
    )


def record_approval_conflict_audit(
    *,
    organization_id: int,
    submission_id: int,
    actor_user_id: int | None,
    conflict_type: str,
    audit_detail: dict | None = None,
    message: str | None = None,
) -> bool:
    """
    Persist approval_conflict outside a rolled-back approval transaction.
    Opens a separate short-lived DB connection and commits independently.
    """
    from backend.db import get_db

    detail = dict(audit_detail or {})
    detail.setdefault("organization_id", int(organization_id))
    detail.setdefault("submission_id", int(submission_id))
    detail.setdefault("conflict_type", str(conflict_type))
    detail.setdefault("reviewed_by_user_id", actor_user_id)
    if message:
        detail.setdefault("message", str(message)[:500])
    # Never persist secrets.
    for key in list(detail.keys()):
        if "token" in str(key).lower() or "session" in str(key).lower() or "password" in str(key).lower():
            detail.pop(key, None)

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        ensure_drc_mobile_entry_tables(cursor)
        _log_event(
            cursor,
            int(submission_id),
            int(organization_id),
            "approval_conflict",
            actor_user_id=actor_user_id,
            detail=detail,
        )
        conn.commit()
        return True
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ── Assignments ─────────────────────────────────────────────────────────────


def list_weekday_section_assignments(cursor, organization_id: int) -> list[dict]:
    ensure_drc_mobile_entry_tables(cursor)
    cursor.execute(
        """
        SELECT weekday, section_key, employee_id
        FROM drc_weekday_section_assignments
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    by = {(int(r["weekday"]), str(r["section_key"])): r.get("employee_id") for r in (cursor.fetchall() or [])}
    out = []
    for section in SECTION_KEYS:
        days = []
        for weekday, label in WEEKDAY_ROWS:
            eid = by.get((weekday, section))
            days.append(
                {
                    "weekday": weekday,
                    "label": label,
                    "employee_id": int(eid) if eid is not None else None,
                }
            )
        out.append(
            {
                "section_key": section,
                "section_label": SECTION_LABELS[section],
                "days": days,
            }
        )
    return out


def save_weekday_section_assignments(
    cursor,
    organization_id: int,
    assignments: list[dict],
    *,
    actor_user_id: Optional[int] = None,
) -> list[dict]:
    """
    assignments: [{section_key, weekday, employee_id}, ...]
    Rejects changing today's assignee for a section while an OPEN draft exists.
    """
    ensure_drc_mobile_entry_tables(cursor)
    oid = int(organization_id)
    today = business_today()
    today_wd = int(today.weekday())

    normalized: list[tuple[str, int, Optional[int]]] = []
    for row in assignments or []:
        section = str(row.get("section_key") or "").strip()
        if section not in SECTION_KEYS:
            continue
        try:
            wd = int(row.get("weekday"))
        except (TypeError, ValueError):
            continue
        if wd not in {w for w, _ in WEEKDAY_ROWS}:
            continue
        eid = row.get("employee_id")
        if eid in (None, "", "null"):
            eid_i = None
        else:
            eid_i = int(eid)
            cursor.execute(
                "SELECT id FROM users WHERE id=%s AND organization_id=%s LIMIT 1",
                (eid_i, oid),
            )
            if not cursor.fetchone():
                raise DrcMobileEntryError(f"Employee {eid_i} not found in this organization", 400)
        normalized.append((section, wd, eid_i))

    for section, wd, new_eid in normalized:
        if wd != today_wd:
            continue
        open_row = _get_submission_row(cursor, oid, today, section)
        if not open_row:
            continue
        st = _normalize_status(open_row.get("status"))
        if st not in EDITABLE_EMPLOYEE:
            continue
        old = open_row.get("assigned_employee_id")
        old_i = int(old) if old is not None else None
        if new_eid != old_i:
            raise DrcMobileEntryError(
                f"Cannot change today's {SECTION_LABELS[section]} assignee while an open draft exists.",
                409,
            )

    for section, wd, eid in normalized:
        cursor.execute(
            """
            INSERT INTO drc_weekday_section_assignments
              (organization_id, weekday, section_key, employee_id, updated_at, updated_by_user_id, created_at)
            VALUES (%s, %s, %s, %s, NOW(), %s, NOW())
            ON DUPLICATE KEY UPDATE
              employee_id = VALUES(employee_id),
              updated_at = NOW(),
              updated_by_user_id = VALUES(updated_by_user_id)
            """,
            (oid, wd, section, eid, actor_user_id),
        )
    return list_weekday_section_assignments(cursor, oid)


def sections_assigned_to_employee(
    cursor, organization_id: int, employee_id: int, on_date: Any = None
) -> list[str]:
    ensure_drc_mobile_entry_tables(cursor)
    d = _parse_date(on_date)
    wd = int(d.weekday())
    cursor.execute(
        """
        SELECT section_key FROM drc_weekday_section_assignments
        WHERE organization_id = %s AND weekday = %s AND employee_id = %s
        """,
        (int(organization_id), wd, int(employee_id)),
    )
    return [str(r["section_key"]) for r in (cursor.fetchall() or []) if r.get("section_key") in SECTION_KEYS]


def employee_has_any_section_today(cursor, organization_id: int, employee_id: int) -> bool:
    return bool(sections_assigned_to_employee(cursor, organization_id, employee_id))


# ── Field schemas / validation ───────────────────────────────────────────────


def _commercial_accounts(cursor, organization_id: int, on_date: date) -> list[dict]:
    from backend.daily_revenue_cost import list_commercial_accounts

    return list_commercial_accounts(cursor, int(organization_id), active_only=True, as_of=on_date) or []


def section_field_defs(cursor, organization_id: int, section_key: str, on_date: date) -> list[dict]:
    if section_key == SECTION_SELF_SERVICE:
        return [
            {"key": "cash", "label": "Cash", "kind": "money", "required": True},
            {"key": "card", "label": "Card", "kind": "money", "required": True},
        ]
    if section_key == SECTION_DROP_OFF:
        return [
            {"key": "cash", "label": "Cash", "kind": "money", "required": True},
            {"key": "card", "label": "Card", "kind": "money", "required": True},
        ]
    if section_key == SECTION_RINSE:
        return [
            {"key": "wf_pounds", "label": "WF Pounds", "kind": "qty", "required": True},
            {"key": "hd_orders", "label": "HD Orders", "kind": "qty", "required": True},
            {"key": "hd_revenue", "label": "HD Revenue", "kind": "money", "required": True},
        ]
    if section_key == SECTION_COMMERCIAL:
        accounts = _commercial_accounts(cursor, organization_id, on_date)
        fields = []
        for acct in accounts:
            aid = int(acct["id"])
            fields.append(
                {
                    "key": f"account_{aid}_pounds",
                    "label": f"{acct.get('name') or f'Account {aid}'} Pounds",
                    "kind": "qty",
                    "required": True,
                    "commercial_account_id": aid,
                    "account_name": acct.get("name"),
                }
            )
        if not fields:
            # Stable empty commercial surface
            fields.append(
                {
                    "key": "_none",
                    "label": "No commercial accounts configured",
                    "kind": "info",
                    "required": False,
                }
            )
        return fields
    if section_key == SECTION_OPERATING_COSTS:
        return [
            {"key": key, "label": label, "kind": "money", "required": True, "line_key": lk}
            for key, lk, label in OPERATING_COST_FIELDS
        ]
    raise DrcMobileEntryError("Unknown section.", 400)


def validate_section_values(
    cursor, organization_id: int, section_key: str, values: dict, on_date: date, *, require_complete: bool
) -> dict:
    defs = section_field_defs(cursor, organization_id, section_key, on_date)
    cleaned: dict[str, Any] = {}
    missing = []
    for f in defs:
        if f.get("kind") == "info":
            continue
        key = f["key"]
        raw = (values or {}).get(key)
        if f["kind"] == "money":
            parsed = parse_money(raw, allow_blank=True)
        else:
            parsed = parse_qty(raw, allow_blank=True)
        if parsed is None:
            if require_complete and f.get("required"):
                missing.append(f["label"])
            cleaned[key] = None
        else:
            cleaned[key] = float(parsed)
        if f.get("commercial_account_id") is not None:
            cleaned[f"{key}__account_id"] = int(f["commercial_account_id"])
    if require_complete and missing:
        raise DrcMobileEntryError(
            f"Complete all fields before submitting ({', '.join(missing)}).",
            400,
        )
    return cleaned


def section_progress(values: dict, field_defs: list[dict]) -> dict:
    required = [f for f in field_defs if f.get("required") and f.get("kind") != "info"]
    done = 0
    for f in required:
        v = (values or {}).get(f["key"])
        if v is not None and v != "":
            done += 1
    total = len(required)
    return {"done": done, "total": total, "complete": total > 0 and done == total}


# ── Submissions ──────────────────────────────────────────────────────────────


def _get_submission_row(cursor, organization_id: int, entry_date: date, section_key: str) -> Optional[dict]:
    cursor.execute(
        """
        SELECT * FROM drc_mobile_section_submissions
        WHERE organization_id = %s AND entry_date = %s AND section_key = %s
        LIMIT 1
        """,
        (int(organization_id), entry_date, section_key),
    )
    return cursor.fetchone()


def _serialize_submission(cursor, row: dict, *, include_defs: bool = True) -> dict:
    oid = int(row["organization_id"])
    d = row["entry_date"]
    if hasattr(d, "isoformat"):
        d_s = d.isoformat()
        d_obj = d if isinstance(d, date) and not isinstance(d, datetime) else _parse_date(d)
    else:
        d_s = str(d)[:10]
        d_obj = _parse_date(d)
    section = str(row["section_key"])
    values = _json_load(row.get("values_json")) or {}
    calculated = _json_load(row.get("calculated_json")) or {}
    snapshot = _json_load(row.get("rate_snapshot_json")) or {}
    defs = section_field_defs(cursor, oid, section, d_obj) if include_defs else []
    submitted_at = row.get("submitted_at")
    if hasattr(submitted_at, "isoformat"):
        submitted_at = submitted_at.isoformat()
    return {
        "id": int(row["id"]),
        "organization_id": oid,
        "entry_date": d_s,
        "business_date": d_s,
        "section_key": section,
        "section_label": SECTION_LABELS.get(section, section),
        "assigned_employee_id": int(row["assigned_employee_id"]),
        "assigned_employee_name": row.get("assigned_employee_name"),
        "status": _normalize_status(row.get("status")),
        "draft_revision": int(row.get("draft_revision") or 0),
        "values": values,
        "calculated": calculated,
        "rate_snapshot": snapshot,
        "note": row.get("note"),
        "rejection_reason": row.get("rejection_reason"),
        "return_reason": row.get("rejection_reason"),
        "daily_entry_id": row.get("daily_entry_id"),
        "submitted_at": submitted_at,
        "submitted_by_user_id": row.get("submitted_by_user_id"),
        "fields": defs,
        "progress": section_progress(values, defs),
        "on_hand_updated": False,
        "pending_manager_review": _normalize_status(row.get("status")) == STATUS_SUBMITTED,
    }


def ensure_section_draft(
    cursor,
    organization_id: int,
    employee_id: int,
    section_key: str,
    *,
    on_date: Optional[date] = None,
) -> dict:
    ensure_drc_mobile_entry_tables(cursor)
    oid = int(organization_id)
    eid = int(employee_id)
    section = str(section_key)
    if section not in SECTION_KEYS:
        raise DrcMobileEntryError("Unknown section.", 400)
    d = _parse_date(on_date)
    assigned = sections_assigned_to_employee(cursor, oid, eid, d)
    if section not in assigned:
        raise DrcMobileEntryError("Section not assigned to you today.", 403)

    row = _get_submission_row(cursor, oid, d, section)
    if row:
        st = _normalize_status(row.get("status"))
        owner = int(row.get("assigned_employee_id") or 0)
        if owner != eid and st in EDITABLE_EMPLOYEE:
            raise DrcMobileEntryError("This section draft belongs to another employee.", 403)
        if owner != eid and st in TERMINAL_EMPLOYEE:
            raise DrcMobileEntryError("This section was submitted by another assignee.", 403)
        return _serialize_submission(cursor, row)

    name = _employee_display_name(cursor, oid, eid)
    cursor.execute(
        """
        INSERT INTO drc_mobile_section_submissions
          (organization_id, entry_date, section_key, assigned_employee_id, assigned_employee_name,
           status, draft_revision, values_json, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, 0, %s, NOW())
        """,
        (oid, d, section, eid, name, STATUS_DRAFT, _json_dump({})),
    )
    sid = int(cursor.lastrowid)
    _log_event(cursor, sid, oid, "created", actor_user_id=eid)
    row = _get_submission_row(cursor, oid, d, section)
    return _serialize_submission(cursor, row)


def list_today_for_employee(
    cursor, organization_id: int, employee_id: int, *, on_date: Optional[date] = None
) -> dict:
    ensure_drc_mobile_entry_tables(cursor)
    oid = int(organization_id)
    eid = int(employee_id)
    d = _parse_date(on_date)
    sections = sections_assigned_to_employee(cursor, oid, eid, d)
    payloads = [ensure_section_draft(cursor, oid, eid, s, on_date=d) for s in sections]
    done = sum(1 for p in payloads if p["status"] in (STATUS_SUBMITTED, STATUS_APPROVED) or p["progress"]["complete"])
    all_submitted = bool(payloads) and all(
        p["status"] in (STATUS_SUBMITTED, STATUS_APPROVED) for p in payloads
    )
    return {
        "organization_id": oid,
        "business_date": d.isoformat(),
        "entry_date": d.isoformat(),
        "assigned_sections": payloads,
        "progress": {
            "sections_total": len(payloads),
            "sections_ready": done,
            "all_submitted": all_submitted,
        },
        "date_resolver": "business_today (America/New_York)",
    }


def save_section_draft(
    cursor,
    organization_id: int,
    employee_id: int,
    section_key: str,
    values: dict,
    *,
    note: Any = None,
    expected_revision: Any = None,
    on_date: Optional[date] = None,
) -> dict:
    ensure_drc_mobile_entry_tables(cursor)
    oid = int(organization_id)
    eid = int(employee_id)
    d = _parse_date(on_date)
    exp = _parse_expected_revision(expected_revision)
    payload = ensure_section_draft(cursor, oid, eid, section_key, on_date=d)
    row = _get_submission_row(cursor, oid, d, section_key)
    if not row:
        raise DrcMobileEntryError("Draft not found.", 404)
    status = _normalize_status(row.get("status"))
    if status not in EDITABLE_EMPLOYEE:
        raise DrcMobileEntryError("Section already submitted; editing is not allowed.", 409)
    if int(row.get("assigned_employee_id") or 0) != eid:
        raise DrcMobileEntryError("Section not assigned to you.", 403)
    cur_rev = int(row.get("draft_revision") or 0)
    if exp != cur_rev:
        raise DrcMobileEntryError(DRAFT_CONFLICT_HELPER, 409)

    cleaned = validate_section_values(cursor, oid, section_key, values or {}, d, require_complete=False)
    note_s = None
    if note is not None and str(note).strip():
        note_s = str(note).strip()
        if len(note_s) > NOTE_MAX_LEN:
            raise DrcMobileEntryError(f"Note cannot exceed {NOTE_MAX_LEN} characters.", 400)

    # Returned corrections stay returned until resubmit; drafts stay draft.
    next_status = status if status == STATUS_RETURNED else STATUS_DRAFT
    cursor.execute(
        """
        UPDATE drc_mobile_section_submissions
        SET values_json = %s,
            note = %s,
            draft_revision = draft_revision + 1,
            status = %s,
            updated_at = NOW()
        WHERE id = %s AND draft_revision = %s
        """,
        (
            _json_dump(cleaned),
            note_s if note_s is not None else row.get("note"),
            next_status,
            int(row["id"]),
            exp,
        ),
    )
    if cursor.rowcount == 0:
        raise DrcMobileEntryError(DRAFT_CONFLICT_HELPER, 409)
    _log_event(
        cursor,
        int(row["id"]),
        oid,
        "draft_saved",
        actor_user_id=eid,
        detail={"revision": cur_rev + 1, "section_key": section_key},
    )
    refreshed = _get_submission_row(cursor, oid, d, section_key)
    return _serialize_submission(cursor, refreshed)


def _lookup_daily_entry(cursor, organization_id: int, entry_date: date) -> Optional[dict]:
    from backend.daily_revenue_cost import ensure_daily_revenue_cost_tables

    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (int(organization_id), entry_date),
    )
    return cursor.fetchone()


def _ensure_open_daily_entry(cursor, organization_id: int, entry_date: date, user_id: int) -> dict:
    """Ensure a single open DRC day header exists. Never silently reopen locked/closed days."""
    header = _lookup_daily_entry(cursor, organization_id, entry_date)
    if not header:
        cursor.execute(
            """
            INSERT INTO dr_daily_entries (organization_id, entry_date, status, created_by, modified_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (int(organization_id), entry_date, ENTRY_STATUS_OPEN, user_id, user_id),
        )
        header = _lookup_daily_entry(cursor, organization_id, entry_date)
        return header
    status = str(header.get("status") or ENTRY_STATUS_OPEN).lower()
    if status != ENTRY_STATUS_OPEN:
        raise approval_conflict_error(
            DAY_NOT_OPEN_HELPER,
            CONFLICT_DAY_NOT_OPEN,
            audit_detail={"day_status": status},
        )
    return header


def _mobile_source_ref(submission_id: int) -> str:
    return f"mobile_section:{int(submission_id)}"


def _line_blocks_mobile_apply(existing_line: Optional[dict], submission_id: int) -> bool:
    """True when an existing DRC line must not be overwritten by mobile approval."""
    if not existing_line:
        return False
    source_ref = str(existing_line.get("source_ref") or "")
    if source_ref == _mobile_source_ref(submission_id):
        return False
    if bool(existing_line.get("is_manual_override")):
        return True
    amt = float(existing_line.get("amount") or 0)
    qty_raw = existing_line.get("quantity")
    qty = float(qty_raw) if qty_raw is not None and qty_raw != "" else 0.0
    if abs(amt) > 1e-9 or abs(qty) > 1e-9:
        return True
    # Non-empty foreign source_ref on a zeroed line still counts as owned elsewhere.
    if source_ref and not source_ref.startswith("mobile_section:"):
        return True
    return False


def _compute_section_snapshot(
    cursor,
    organization_id: int,
    entry_date: date,
    section_key: str,
    values: dict,
    *,
    submission_id: int,
) -> tuple[dict, dict]:
    """
    Authoritative backend calculation at employee submit time.
    Does not write dr_daily_entries / dr_daily_entry_lines.
    """
    from backend.daily_revenue_cost import (
        commercial_line_revenue_from_pricing,
        get_commercial_pricing_for_date,
        get_wf_schedule_for_date,
        wf_revenue_for_day,
    )

    existing_header = _lookup_daily_entry(cursor, organization_id, entry_date)
    exclude_entry_id = int(existing_header["id"]) if existing_header else None
    calculated: dict[str, Any] = {}
    snapshot: dict[str, Any] = {
        "section_key": section_key,
        "calc_version": CALC_VERSION,
        "computed_at": _naive_now().isoformat(),
        "submission_id": int(submission_id),
        "values": values,
    }

    if section_key == SECTION_SELF_SERVICE:
        cash = float(values.get("cash") or 0)
        card = float(values.get("card") or 0)
        calculated = {"cash": cash, "card": card, "total": cash + card}
        snapshot["line_plan"] = [
            {"line_key": LK_SELF_SERVICE_CASH, "category": "revenue", "amount": cash},
            {"line_key": LK_SELF_SERVICE_CARD, "category": "revenue", "amount": card},
        ]
    elif section_key == SECTION_DROP_OFF:
        cash = float(values.get("cash") or 0)
        card = float(values.get("card") or 0)
        calculated = {"cash": cash, "card": card, "total": cash + card}
        snapshot["line_plan"] = [
            {"line_key": LK_DROP_OFF_CASH, "category": "revenue", "amount": cash},
            {"line_key": LK_DROP_OFF_CARD, "category": "revenue", "amount": card},
        ]
    elif section_key == SECTION_RINSE:
        wf_pounds = float(values.get("wf_pounds") or 0)
        hd_orders = float(values.get("hd_orders") or 0)
        hd_revenue = float(values.get("hd_revenue") or 0)
        sched_id, tiers = get_wf_schedule_for_date(cursor, organization_id, entry_date)
        wf_rev, wf_meta = wf_revenue_for_day(
            cursor, organization_id, entry_date, wf_pounds, tiers, exclude_entry_id=exclude_entry_id
        )
        wf_snapshot = {
            "schedule_id": sched_id,
            "tiers": tiers,
            "mtd_meta": wf_meta,
            "calculated_amount": wf_rev,
            "quantity": wf_pounds,
        }
        snapshot["wf"] = wf_snapshot
        calculated = {
            "wf_pounds": wf_pounds,
            "wf_revenue": float(wf_rev),
            "hd_orders": hd_orders,
            "hd_revenue": hd_revenue,
            "total": float(wf_rev) + hd_revenue,
        }
        snapshot["line_plan"] = [
            {
                "line_key": LK_RINSE_WF_POUNDS,
                "category": "revenue",
                "amount": 0,
                "quantity": wf_pounds,
                "pricing_schedule_id": sched_id,
                "rate_snapshot": wf_snapshot,
            },
            {
                "line_key": LK_RINSE_WF_AMOUNT,
                "category": "revenue",
                "amount": float(wf_rev),
                "quantity": wf_pounds,
                "pricing_schedule_id": sched_id,
                "rate_snapshot": wf_snapshot,
            },
            {"line_key": LK_RINSE_HD_ORDERS, "category": "revenue", "amount": 0, "quantity": hd_orders},
            {"line_key": LK_RINSE_HD_AMOUNT, "category": "revenue", "amount": hd_revenue},
        ]
    elif section_key == SECTION_COMMERCIAL:
        accounts = _commercial_accounts(cursor, organization_id, entry_date)
        lines_out = []
        total = 0.0
        line_plan = []
        for acct in accounts:
            aid = int(acct["id"])
            key = f"account_{aid}_pounds"
            pounds = float(values.get(key) or 0)
            pricing = get_commercial_pricing_for_date(cursor, aid, entry_date) or {}
            rev = commercial_line_revenue_from_pricing(pounds, pricing)
            rate_snap = {"account_id": aid, "pricing": pricing, "pounds": pounds, "revenue": rev}
            snapshot[f"account_{aid}"] = rate_snap
            total += float(rev or 0)
            lines_out.append(
                {"account_id": aid, "name": acct.get("name"), "pounds": pounds, "revenue": float(rev or 0)}
            )
            line_plan.append(
                {
                    "line_key": commercial_pounds_key(aid),
                    "category": "revenue",
                    "amount": 0,
                    "quantity": pounds,
                    "commercial_account_id": aid,
                    "rate_snapshot": rate_snap,
                }
            )
            line_plan.append(
                {
                    "line_key": commercial_amount_key(aid),
                    "category": "revenue",
                    "amount": float(rev or 0),
                    "quantity": pounds,
                    "commercial_account_id": aid,
                    "rate_snapshot": rate_snap,
                }
            )
        calculated = {"lines": lines_out, "total": total}
        snapshot["line_plan"] = line_plan
    elif section_key == SECTION_OPERATING_COSTS:
        cost_out = {}
        line_plan = []
        for key, lk, _label in OPERATING_COST_FIELDS:
            amt = float(values.get(key) or 0)
            cost_out[key] = amt
            line_plan.append({"line_key": lk, "category": "cost_variable", "amount": amt})
        calculated = {**cost_out, "total": sum(cost_out.values())}
        snapshot["operating_cost_allowlist"] = [k for k, _, _ in OPERATING_COST_FIELDS]
        snapshot["line_plan"] = line_plan
    else:
        raise DrcMobileEntryError("Unknown section.", 400)

    snapshot["calculated"] = calculated
    return calculated, snapshot


def _validate_snapshot_for_apply(snapshot: dict, calculated: dict, section_key: str) -> None:
    if not isinstance(snapshot, dict) or not isinstance(calculated, dict):
        raise approval_conflict_error(
            "Submission snapshot is incomplete.",
            CONFLICT_INVALID_SNAPSHOT,
        )
    if snapshot.get("section_key") != section_key:
        raise approval_conflict_error(
            "Submission snapshot is incomplete.",
            CONFLICT_INVALID_SNAPSHOT,
            audit_detail={"reason": "section_mismatch"},
        )
    if not snapshot.get("line_plan"):
        raise approval_conflict_error(
            "Submission snapshot is incomplete.",
            CONFLICT_INVALID_SNAPSHOT,
            audit_detail={"reason": "missing_line_plan"},
        )
    if not snapshot.get("calc_version"):
        raise approval_conflict_error(
            "Submission snapshot is incomplete.",
            CONFLICT_INVALID_SNAPSHOT,
            audit_detail={"reason": "missing_calc_version"},
        )


def _apply_approved_section_from_snapshot(
    cursor,
    organization_id: int,
    entry_date: date,
    section_key: str,
    *,
    user_id: int,
    submission_id: int,
    calculated: dict,
    snapshot: dict,
) -> int:
    """
    Apply stored submit-time calculated values into existing DRC lines.
    Does not recalculate rates. Conflicts on foreign/manager values → 409.
    """
    from backend.daily_revenue_cost_schema import upsert_entry_line

    _validate_snapshot_for_apply(snapshot, calculated, section_key)
    header = _ensure_open_daily_entry(cursor, organization_id, entry_date, user_id)
    entry_id = int(header["id"])
    cursor.execute(
        "SELECT * FROM dr_daily_entry_lines WHERE daily_entry_id = %s",
        (entry_id,),
    )
    existing = {str(r["line_key"]): r for r in (cursor.fetchall() or [])}
    source_ref = _mobile_source_ref(submission_id)
    line_plan = snapshot.get("line_plan") or []

    # Preflight conflicts — no writes until all clear.
    for plan in line_plan:
        lk = str(plan["line_key"])
        if _line_blocks_mobile_apply(existing.get(lk), submission_id):
            existing_line = existing.get(lk) or {}
            raise approval_conflict_error(
                DRC_FIELD_CONFLICT_HELPER,
                CONFLICT_TARGET_LINE,
                audit_detail={
                    "line_key": lk,
                    "line_category": plan.get("category"),
                    "existing_source_system": existing_line.get("source_system"),
                    "existing_source_ref": existing_line.get("source_ref"),
                },
            )

    for plan in line_plan:
        lk = str(plan["line_key"])
        upsert_entry_line(
            cursor,
            daily_entry_id=entry_id,
            line_key=lk,
            line_category=plan.get("category") or "revenue",
            amount=float(plan.get("amount") or 0),
            quantity=None if plan.get("quantity") is None else float(plan["quantity"]),
            commercial_account_id=plan.get("commercial_account_id"),
            source_system=SOURCE_MOBILE,
            source_ref=source_ref,
            source_payload={
                "mobile_submission_id": submission_id,
                "section_key": section_key,
                "calc_version": snapshot.get("calc_version"),
            },
            is_override=False,
            user_id=user_id,
            pricing_schedule_id=plan.get("pricing_schedule_id"),
            rate_snapshot=plan.get("rate_snapshot") or snapshot,
            existing_line=existing.get(lk),
        )

    cursor.execute(
        "UPDATE dr_daily_entries SET modified_by = %s WHERE id = %s",
        (user_id, entry_id),
    )
    return entry_id


def _submit_section_core(
    cursor,
    organization_id: int,
    employee_id: int,
    section_key: str,
    *,
    expected_revision: Any = None,
    on_date: Optional[date] = None,
    notify: bool = True,
) -> dict:
    """Mark section submitted with calculation snapshot. Does not touch DRC tables."""
    ensure_drc_mobile_entry_tables(cursor)
    oid = int(organization_id)
    eid = int(employee_id)
    d = _parse_date(on_date)
    exp = _parse_expected_revision(expected_revision)
    ensure_section_draft(cursor, oid, eid, section_key, on_date=d)

    cursor.execute(
        """
        SELECT * FROM drc_mobile_section_submissions
        WHERE organization_id = %s AND entry_date = %s AND section_key = %s
        LIMIT 1 FOR UPDATE
        """,
        (oid, d, section_key),
    )
    row = cursor.fetchone()
    if not row:
        raise DrcMobileEntryError("Draft not found.", 404)
    if int(row.get("assigned_employee_id") or 0) != eid:
        raise DrcMobileEntryError("Section not assigned to you.", 403)

    status = _normalize_status(row.get("status"))
    if status in (STATUS_SUBMITTED, STATUS_APPROVED):
        return _serialize_submission(cursor, row)

    cur_rev = int(row.get("draft_revision") or 0)
    if exp != cur_rev:
        raise DrcMobileEntryError(DRAFT_CONFLICT_HELPER, 409)

    values = _json_load(row.get("values_json")) or {}
    validate_section_values(cursor, oid, section_key, values, d, require_complete=True)

    calculated, snapshot = _compute_section_snapshot(
        cursor, oid, d, section_key, values, submission_id=int(row["id"])
    )
    submitted_at = _naive_now()
    was_return = status == STATUS_RETURNED
    cursor.execute(
        """
        UPDATE drc_mobile_section_submissions
        SET status = %s,
            calculated_json = %s,
            rate_snapshot_json = %s,
            submitted_at = %s,
            submitted_by_user_id = %s,
            rejection_reason = NULL,
            reviewed_at = NULL,
            reviewed_by_user_id = NULL,
            updated_at = NOW()
        WHERE id = %s AND draft_revision = %s AND status IN (%s, %s, 'rejected')
        """,
        (
            STATUS_SUBMITTED,
            _json_dump(calculated),
            _json_dump(snapshot),
            submitted_at,
            eid,
            int(row["id"]),
            exp,
            STATUS_DRAFT,
            STATUS_RETURNED,
        ),
    )
    if cursor.rowcount == 0:
        refreshed = _get_submission_row(cursor, oid, d, section_key)
        if refreshed and _normalize_status(refreshed.get("status")) in (
            STATUS_SUBMITTED,
            STATUS_APPROVED,
        ):
            return _serialize_submission(cursor, refreshed)
        raise DrcMobileEntryError(DRAFT_CONFLICT_HELPER, 409)

    _log_event(
        cursor,
        int(row["id"]),
        oid,
        "resubmitted" if was_return else "submitted",
        actor_user_id=eid,
        detail={
            "section_key": section_key,
            "business_date": d.isoformat(),
            "revision": cur_rev,
            "calculated": calculated,
            "drc_applied": False,
        },
    )
    refreshed = _get_submission_row(cursor, oid, d, section_key)
    payload = _serialize_submission(cursor, refreshed)
    if notify:
        _notify_section_submitted(cursor, oid, payload)
    return payload


def submit_section(
    cursor,
    organization_id: int,
    employee_id: int,
    section_key: str,
    *,
    expected_revision: Any = None,
    on_date: Optional[date] = None,
) -> dict:
    return _submit_section_core(
        cursor,
        organization_id,
        employee_id,
        section_key,
        expected_revision=expected_revision,
        on_date=on_date,
        notify=True,
    )


def submit_all_assigned(
    cursor, organization_id: int, employee_id: int, *, on_date: Optional[date] = None
) -> dict:
    """Mark every assigned complete section Submitted. Does not apply into DRC."""
    today = list_today_for_employee(cursor, organization_id, employee_id, on_date=on_date)
    results = []
    newly_submitted = []
    for sec in today["assigned_sections"]:
        if sec["status"] in (STATUS_SUBMITTED, STATUS_APPROVED):
            results.append(sec)
            continue
        if not sec["progress"]["complete"]:
            raise DrcMobileEntryError(
                f"Complete {sec['section_label']} before submitting.",
                400,
            )
        payload = _submit_section_core(
            cursor,
            organization_id,
            employee_id,
            sec["section_key"],
            expected_revision=sec["draft_revision"],
            on_date=on_date,
            notify=False,
        )
        results.append(payload)
        newly_submitted.append(payload)
    if newly_submitted:
        _notify_sections_submitted_batch(cursor, int(organization_id), newly_submitted)
    return {
        **today,
        "assigned_sections": results,
        "progress": {
            "sections_total": len(results),
            "sections_ready": len(results),
            "all_submitted": all(r["status"] in (STATUS_SUBMITTED, STATUS_APPROVED) for r in results),
        },
    }


# ── Manager review ───────────────────────────────────────────────────────────


def list_mobile_submissions(cursor, organization_id: int, *, limit: int = 60) -> list[dict]:
    ensure_drc_mobile_entry_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM drc_mobile_section_submissions
        WHERE organization_id = %s
          AND status IN (%s, %s, %s, %s, 'rejected')
        ORDER BY entry_date DESC, submitted_at DESC, id DESC
        LIMIT %s
        """,
        (
            int(organization_id),
            STATUS_SUBMITTED,
            STATUS_APPROVED,
            STATUS_RETURNED,
            STATUS_DRAFT,
            int(limit),
        ),
    )
    rows = list(cursor.fetchall() or [])
    out = []
    for row in rows:
        st = _normalize_status(row.get("status"))
        if st == STATUS_DRAFT:
            continue
        out.append(_serialize_submission(cursor, row, include_defs=False))
    return out


def get_mobile_submission(cursor, organization_id: int, submission_id: int) -> dict:
    ensure_drc_mobile_entry_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM drc_mobile_section_submissions
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(submission_id)),
    )
    row = cursor.fetchone()
    if not row:
        raise DrcMobileEntryError("Submission not found.", 404)
    return _serialize_submission(cursor, row)


def review_mobile_submission(
    cursor,
    organization_id: int,
    submission_id: int,
    *,
    action: str,
    actor_user_id: int,
    reason: str | None = None,
) -> dict:
    """
    approve → apply snapshot into DRC atomically, then mark approved.
    return (alias reject) → reopen for correction; never mutates DRC.
    Approved rows cannot be returned in Phase 5E.
    """
    ensure_drc_mobile_entry_tables(cursor)
    action = (action or "").strip().lower()
    if action == "reject":
        action = "return"
    if action not in ("approve", "return"):
        raise DrcMobileEntryError("Unknown review action.", 400)

    cursor.execute(
        """
        SELECT * FROM drc_mobile_section_submissions
        WHERE organization_id = %s AND id = %s
        LIMIT 1 FOR UPDATE
        """,
        (int(organization_id), int(submission_id)),
    )
    row = cursor.fetchone()
    if not row:
        raise DrcMobileEntryError("Submission not found.", 404)
    status = _normalize_status(row.get("status"))
    section_key = str(row["section_key"])
    entry_date = row["entry_date"]
    if hasattr(entry_date, "isoformat"):
        d_obj = entry_date if isinstance(entry_date, date) and not isinstance(entry_date, datetime) else _parse_date(entry_date)
    else:
        d_obj = _parse_date(entry_date)
    sid = int(submission_id)
    oid = int(organization_id)

    if action == "approve":
        if status == STATUS_APPROVED:
            # Idempotent: already applied.
            return _serialize_submission(cursor, row)
        if status != STATUS_SUBMITTED:
            raise approval_conflict_error(
                "Only submitted sections can be approved.",
                CONFLICT_NOT_SUBMITTED,
                audit_detail={
                    "organization_id": oid,
                    "business_date": d_obj.isoformat(),
                    "submission_id": sid,
                    "section_key": section_key,
                    "section_label": SECTION_LABELS.get(section_key, section_key),
                    "submitted_by_user_id": row.get("submitted_by_user_id"),
                    "assigned_employee_id": row.get("assigned_employee_id"),
                    "assigned_employee_name": row.get("assigned_employee_name"),
                    "reviewed_by_user_id": int(actor_user_id),
                    "revision": int(row.get("draft_revision") or 0),
                    "current_status": status,
                },
            )

        # approval_attempted stays in this txn (success path commits; conflicts roll it back).
        _log_event(
            cursor,
            sid,
            oid,
            "approval_attempted",
            actor_user_id=actor_user_id,
            detail={"section_key": section_key, "business_date": d_obj.isoformat()},
        )
        calculated = _json_load(row.get("calculated_json")) or {}
        snapshot = _json_load(row.get("rate_snapshot_json")) or {}
        try:
            entry_id = _apply_approved_section_from_snapshot(
                cursor,
                oid,
                d_obj,
                section_key,
                user_id=int(actor_user_id),
                submission_id=sid,
                calculated=calculated,
                snapshot=snapshot,
            )
        except DrcMobileEntryError as exc:
            # Do not write approval_conflict here — it would roll back with the txn.
            # Routes call record_approval_conflict_audit after rollback.
            if not getattr(exc, "durable_conflict", False):
                raise approval_conflict_error(
                    str(exc),
                    CONFLICT_REVISION,
                    audit_detail={"wrapped": True},
                ) from exc
            # Enrich with submission context for the durable writer.
            detail = {
                "organization_id": oid,
                "business_date": d_obj.isoformat(),
                "submission_id": sid,
                "section_key": section_key,
                "section_label": SECTION_LABELS.get(section_key, section_key),
                "submitted_by_user_id": row.get("submitted_by_user_id"),
                "assigned_employee_id": row.get("assigned_employee_id"),
                "assigned_employee_name": row.get("assigned_employee_name"),
                "reviewed_by_user_id": int(actor_user_id),
                "revision": int(row.get("draft_revision") or 0),
                "conflict_type": exc.conflict_type,
                **(exc.audit_detail or {}),
            }
            raise DrcMobileEntryError(
                str(exc),
                409,
                conflict_type=exc.conflict_type,
                audit_detail=detail,
                durable_conflict=True,
            ) from exc

        cursor.execute(
            """
            UPDATE drc_mobile_section_submissions
            SET status = %s,
                daily_entry_id = %s,
                rejection_reason = NULL,
                reviewed_at = NOW(),
                reviewed_by_user_id = %s,
                updated_at = NOW()
            WHERE id = %s AND status = %s
            """,
            (STATUS_APPROVED, entry_id, int(actor_user_id), sid, STATUS_SUBMITTED),
        )
        if cursor.rowcount == 0:
            raise approval_conflict_error(
                DRAFT_CONFLICT_HELPER,
                CONFLICT_REVISION,
                audit_detail={
                    "organization_id": oid,
                    "business_date": d_obj.isoformat(),
                    "submission_id": sid,
                    "section_key": section_key,
                    "submitted_by_user_id": row.get("submitted_by_user_id"),
                    "assigned_employee_id": row.get("assigned_employee_id"),
                    "reviewed_by_user_id": int(actor_user_id),
                    "revision": int(row.get("draft_revision") or 0),
                },
            )
        _log_event(
            cursor,
            sid,
            oid,
            "approved",
            actor_user_id=actor_user_id,
            detail={
                "section_key": section_key,
                "business_date": d_obj.isoformat(),
                "daily_entry_id": entry_id,
                "revision": int(row.get("draft_revision") or 0),
            },
        )
        return get_mobile_submission(cursor, organization_id, submission_id)

    # return for correction
    if status == STATUS_APPROVED:
        raise DrcMobileEntryError(
            "Approved submissions cannot be returned. Use the existing Daily Revenue & Cost override workflow.",
            409,
        )
    if status != STATUS_SUBMITTED:
        raise DrcMobileEntryError("Only submitted sections can be returned for correction.", 400)
    reason_s = (reason or "").strip()
    if not reason_s:
        raise DrcMobileEntryError("Return reason is required.", 400)
    if len(reason_s) > NOTE_MAX_LEN:
        raise DrcMobileEntryError(f"Reason cannot exceed {NOTE_MAX_LEN} characters.", 400)

    cursor.execute(
        """
        UPDATE drc_mobile_section_submissions
        SET status = %s,
            rejection_reason = %s,
            draft_revision = draft_revision + 1,
            reviewed_at = NOW(),
            reviewed_by_user_id = %s,
            updated_at = NOW()
        WHERE id = %s AND status = %s
        """,
        (STATUS_RETURNED, reason_s, int(actor_user_id), sid, STATUS_SUBMITTED),
    )
    if cursor.rowcount == 0:
        raise DrcMobileEntryError(DRAFT_CONFLICT_HELPER, 409)
    _log_event(
        cursor,
        sid,
        oid,
        "returned",
        actor_user_id=actor_user_id,
        detail={
            "reason": reason_s,
            "section_key": section_key,
            "business_date": d_obj.isoformat(),
            "revision": int(row.get("draft_revision") or 0) + 1,
            "drc_applied": False,
        },
    )
    # Optional employee-facing return notify (best-effort; may no-op if infra is manager-only).
    try:
        payload = get_mobile_submission(cursor, organization_id, submission_id)
        _notify_section_returned(cursor, oid, payload)
    except Exception:
        pass
    return get_mobile_submission(cursor, organization_id, submission_id)


def _ensure_notify_definition(cursor, organization_id: int, event_key: str, display_name: str, description: str) -> None:
    if not table_exists(cursor, "notification_event_definitions"):
        return
    cursor.execute(
        """
        INSERT IGNORE INTO notification_event_definitions
          (organization_id, event_key, display_name, description, is_active)
        VALUES (%s, %s, %s, %s, 1)
        """,
        (int(organization_id), event_key, display_name, description),
    )


def _format_submission_date_label(date_s: str) -> str:
    try:
        d = date.fromisoformat(str(date_s)[:10])
        return f"{d.strftime('%B')} {d.day}"
    except Exception:
        return date_s


def _notify_section_submitted(cursor, organization_id: int, payload: dict) -> None:
    _notify_sections_submitted_batch(cursor, organization_id, [payload])


def _short_section_label(payload: dict) -> str:
    lab = payload.get("section_label") or payload.get("section_key") or "section"
    return str(lab).replace(" Revenue", "").replace(" Costs", "").strip()


def _notify_sections_submitted_batch(cursor, organization_id: int, payloads: list[dict]) -> None:
    if not payloads:
        return
    try:
        _ensure_notify_definition(
            cursor,
            organization_id,
            NOTIFY_DRC_MOBILE_SUBMITTED,
            "Revenue & Cost Submitted",
            "Fired when an employee submits a mobile Revenue & Cost section for manager review.",
        )
        from backend.notification_service import dispatch_notification_event

        first = payloads[0]
        name = first.get("assigned_employee_name") or "Employee"
        date_s = first.get("business_date") or ""
        labels = []
        for p in payloads:
            short = _short_section_label(p)
            if short and short not in labels:
                labels.append(short)
        if len(labels) == 1:
            sections_txt = labels[0]
        elif len(labels) == 2:
            sections_txt = f"{labels[0]} and {labels[1]}"
        else:
            sections_txt = ", ".join(labels[:-1]) + f", and {labels[-1]}"
        date_label = _format_submission_date_label(date_s)
        sid = first.get("id")
        open_path = (
            f"/finance/daily-revenue-cost?tab=entry&mobile_submission_id={sid}"
            f"&business_date={date_s}"
        )
        dispatch_notification_event(
            cursor,
            organization_id=int(organization_id),
            event_key=NOTIFY_DRC_MOBILE_SUBMITTED,
            title="Revenue & Cost Submitted",
            body=f"{name} submitted {sections_txt} for {date_label}.",
            data={
                "organization_id": int(organization_id),
                "submission_id": sid,
                "submission_ids": [p.get("id") for p in payloads],
                "section_keys": [p.get("section_key") for p in payloads],
                "business_date": date_s,
                "submitted_employee": name,
                "open_path": open_path,
            },
        )
    except Exception:
        pass


def _notify_section_returned(cursor, organization_id: int, payload: dict) -> None:
    """
    Best-effort return notification.
    Limitation: existing notify infra is primarily manager-oriented; this may no-op
    for employee inboxes depending on org event subscriptions.
    """
    try:
        _ensure_notify_definition(
            cursor,
            organization_id,
            NOTIFY_DRC_MOBILE_RETURNED,
            "Revenue & Cost Returned",
            "Fired when a manager returns a mobile Revenue & Cost section for correction.",
        )
        from backend.notification_service import dispatch_notification_event

        date_s = payload.get("business_date") or ""
        date_label = _format_submission_date_label(date_s)
        short = _short_section_label(payload)
        dispatch_notification_event(
            cursor,
            organization_id=int(organization_id),
            event_key=NOTIFY_DRC_MOBILE_RETURNED,
            title="Revenue & Cost Returned",
            body=f"Your {short} submission for {date_label} was returned for correction.",
            data={
                "organization_id": int(organization_id),
                "submission_id": payload.get("id"),
                "section_key": payload.get("section_key"),
                "business_date": date_s,
                "return_reason": payload.get("return_reason") or payload.get("rejection_reason"),
                "open_path": "/revenue-cost/floor",
            },
        )
    except Exception:
        pass
