"""Session payroll classification override.

Resolution for an America/New_York work date is:

1. shift_sessions.payroll_classification_override when set
2. otherwise the effective-dated employee classification

Role segments do not carry a classification. They inherit the session value.
The override does not choose a rate and does not move frozen payout lines.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

ALLOWED_CLASSIFICATION_OVERRIDES = ("w2", "contractor_1099", "temp")
_ALLOWED = frozenset(ALLOWED_CLASSIFICATION_OVERRIDES)
CLASSIFICATION_SOURCE_PROFILE = "profile"
CLASSIFICATION_SOURCE_RECORD = "record_override"
# build_batch_from_time_records refuses anything outside these statuses.
MUTABLE_BATCH_STATUSES = frozenset({"draft", "hours_reviewed"})


def normalize_payroll_classification_override(value: Any) -> Optional[str]:
    """NULL/blank/default means use the employee profile. Other values must be allowed."""
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in ("", "null", "none", "default", "profile", "employee_default"):
        return None
    aliases = {
        "w2": "w2",
        "w-2": "w2",
        "contractor_1099": "contractor_1099",
        "1099": "contractor_1099",
        "temp": "temp",
        "temp_one_time": "temp",
    }
    mapped = aliases.get(raw)
    if mapped not in _ALLOWED:
        raise ValueError(
            "Payroll classification override must be empty (employee default), "
            "w2, contractor_1099, or temp"
        )
    return mapped


def resolve_session_payroll_category(
    profile_category: Optional[str],
    session_override: Any,
) -> tuple[str, str]:
    """Return (worker_category, classification_source).

    This is the only payroll-generation rule for worker category. Callers pass
    the profile category already resolved for the America/New_York work date.
    """
    override = normalize_payroll_classification_override(session_override)
    if override:
        return override, CLASSIFICATION_SOURCE_RECORD
    profile = str(profile_category or "w2")
    return profile, CLASSIFICATION_SOURCE_PROFILE


def ensure_payroll_classification_schema(cursor) -> None:
    """Add the override column, append-only audit, and line snapshot. No backfill."""
    if table_exists(cursor, "shift_sessions") and not table_has_column(
        cursor, "shift_sessions", "payroll_classification_override"
    ):
        try:
            cursor.execute(
                """
                ALTER TABLE shift_sessions
                ADD COLUMN payroll_classification_override VARCHAR(32) NULL
                """
            )
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_session_classification_audit (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_session_id INT NOT NULL,
          actor_id INT NULL,
          created_at DATETIME NOT NULL,
          old_value VARCHAR(32) NULL,
          new_value VARCHAR(32) NULL,
          reason VARCHAR(500) NULL,
          KEY idx_ss_class_audit_session (shift_session_id, id)
        )
        """
    )
    if table_exists(cursor, "payout_batch_lines") and not table_has_column(
        cursor, "payout_batch_lines", "classification_provenance"
    ):
        try:
            cursor.execute(
                """
                ALTER TABLE payout_batch_lines
                ADD COLUMN classification_provenance JSON NULL
                """
            )
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()


def snapshot_category_for_session(provenance: Any, session_id: int) -> Optional[str]:
    """Category stored on the payout line at generation. Not the live profile."""
    rows = provenance
    if isinstance(rows, (bytes, bytearray)):
        rows = rows.decode("utf-8", errors="ignore")
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except Exception:
            return None
    if not isinstance(rows, list):
        return None
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("shift_session_id")) != int(session_id):
                continue
        except (TypeError, ValueError):
            continue
        cat = item.get("worker_category")
        return str(cat) if cat else None
    return None


def _session_ids(raw: Any) -> set[int]:
    if raw is None or raw == "":
        return set()
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return set()
    if isinstance(raw, (list, tuple, set)):
        out: set[int] = set()
        for item in raw:
            try:
                out.add(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return set()


def frozen_line_classification_warnings(
    lines: list[dict],
    session_id: int,
    new_category: str,
) -> list[dict]:
    """Warn when a frozen line sourced from this session disagrees. Do not move it."""
    warnings = []
    for row in lines or []:
        status = str(row.get("status") or row.get("batch_status") or "").strip().lower()
        if status in MUTABLE_BATCH_STATUSES:
            continue
        if int(session_id) not in _session_ids(row.get("source_shift_session_ids")):
            continue
        stored = snapshot_category_for_session(
            row.get("classification_provenance"), session_id
        )
        if not stored:
            stored = row.get("line_category") or row.get("worker_category") or row.get(
                "batch_category"
            )
        if str(stored or "") == str(new_category):
            continue
        batch_name = row.get("batch_name") or f"Batch {row.get('batch_id')}"
        warnings.append(
            {
                "batch_id": row.get("batch_id"),
                "batch_name": batch_name,
                "batch_status": status,
                "line_id": row.get("line_id"),
                "frozen_category": stored,
                "requested_category": new_category,
                "message": (
                    f"{batch_name} is {status or 'frozen'} and was not moved. "
                    "Historical payroll keeps the category snapshotted at generation."
                ),
            }
        )
    return warnings


def write_line_classification_provenance(conn, line_id: int, provenance: list[dict]) -> None:
    """Snapshot source + resolved category onto the line. Does not change amounts."""
    cur = conn.cursor()
    ensure_payroll_classification_schema(cur)
    if not table_has_column(cur, "payout_batch_lines", "classification_provenance"):
        return
    cur.execute(
        "UPDATE payout_batch_lines SET classification_provenance=%s WHERE id=%s",
        (json.dumps(provenance or []), int(line_id)),
    )


def set_session_payroll_classification_override(
    conn,
    organization_id: int,
    session_id: int,
    *,
    value: Any,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """Set or clear the session override. Same value does not append another audit row.

    An already payroll-approved session keeps its hours and the new override, but
    payroll_hours_approved is cleared so it must be reapproved before batch sync.
    """
    from backend.payroll_operations import (
        _session_in_org,
        _session_work_date_et,
        worker_category_for_user,
    )

    sid = int(session_id)
    cur = conn.cursor()
    ensure_payroll_classification_schema(cur)
    if not _session_in_org(conn, organization_id, sid):
        raise ValueError("Time record not found")
    new_value = normalize_payroll_classification_override(value)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, user_id, clock_in_at, payroll_hours_approved,
               payroll_classification_override
        FROM shift_sessions
        WHERE id=%s
        """,
        (sid,),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Time record not found")
    old_value = normalize_payroll_classification_override(
        row.get("payroll_classification_override")
    )
    work_day = _session_work_date_et(row.get("clock_in_at"))
    profile = worker_category_for_user(
        conn, int(row["user_id"]), on=work_day
    )
    resolved, source = resolve_session_payroll_category(profile, new_value)
    if old_value == new_value:
        return {
            "id": sid,
            "payroll_classification_override": new_value,
            "worker_category": resolved,
            "classification_source": source,
            "profile_worker_category": profile,
            "payroll_hours_approved": bool(row.get("payroll_hours_approved")),
            "approval_cleared": False,
            "audit_appended": False,
            "warnings": [],
        }

    approved = bool(row.get("payroll_hours_approved"))
    sets = ["payroll_classification_override=%s"]
    params: list[Any] = [new_value]
    if approved:
        sets.append("payroll_hours_approved=0")
    params.append(sid)
    c.execute(
        f"UPDATE shift_sessions SET {', '.join(sets)} WHERE id=%s",
        tuple(params),
    )
    reason_text = str(reason or "").strip()[:500] or None
    c.execute(
        """
        INSERT INTO shift_session_classification_audit (
          organization_id, shift_session_id, actor_id, created_at,
          old_value, new_value, reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            sid,
            int(actor_id) if actor_id is not None else None,
            datetime.utcnow(),
            old_value,
            new_value,
            reason_text,
        ),
    )
    warnings = _load_frozen_warnings(conn, organization_id, sid, resolved)
    conn.commit()
    return {
        "id": sid,
        "payroll_classification_override": new_value,
        "worker_category": resolved,
        "classification_source": source,
        "profile_worker_category": profile,
        "payroll_hours_approved": False if approved else bool(row.get("payroll_hours_approved")),
        "approval_cleared": approved,
        "audit_appended": True,
        "warnings": warnings,
    }


def _load_frozen_warnings(conn, organization_id: int, session_id: int, new_category: str):
    chk = conn.cursor()
    if not table_exists(chk, "payout_batch_lines") or not table_exists(chk, "payout_batches"):
        return []
    prov_sel = (
        ", pbl.classification_provenance"
        if table_has_column(chk, "payout_batch_lines", "classification_provenance")
        else ", NULL AS classification_provenance"
    )
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT pb.id AS batch_id, pb.batch_name, pb.status,
               pb.worker_category AS batch_category,
               pbl.id AS line_id, pbl.worker_category AS line_category,
               pbl.source_shift_session_ids
               {prov_sel}
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id=%s
          AND pb.status NOT IN ('draft', 'hours_reviewed')
          AND pbl.source_shift_session_ids IS NOT NULL
        """,
        (int(organization_id),),
    )
    return frozen_line_classification_warnings(c.fetchall() or [], session_id, new_category)
