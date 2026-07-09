"""Schema guard, schedule validation, portable upsert, and workflow for Daily Revenue & Cost."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from backend.daily_revenue_cost_constants import (
    ENTRY_STATUS_APPROVED,
    ENTRY_STATUS_LOCKED,
    ENTRY_STATUS_OPEN,
    ENTRY_STATUS_REJECTED,
    ENTRY_STATUS_SUBMITTED,
    SOURCE_MANUAL,
)
from backend.ta_helpers import table_exists, table_has_column

SQL_SCHEMA_PATH = "backend/sql/daily_revenue_cost_v2.sql"

V1_MIGRATION_ERROR = (
    "Daily Revenue/Cost v1 schema detected. Automatic v2 bootstrap is blocked to protect data. "
    f"Run a manual migration or apply {SQL_SCHEMA_PATH} only on fresh environments. "
    "Do NOT auto-drop or overwrite v1 tables."
)


def detect_v1_schema(cursor) -> bool:
    """Return True if legacy v1 tables/columns are present."""
    if table_exists(cursor, "dr_daily_entry_lines"):
        return False
    if table_exists(cursor, "dr_cost_settings"):
        return True
    if table_exists(cursor, "dr_daily_entries") and table_has_column(cursor, "dr_daily_entries", "self_service_cash"):
        return True
    if table_exists(cursor, "dr_rinse_wf_tiers") and table_has_column(cursor, "dr_rinse_wf_tiers", "organization_id"):
        return True
    return False


def assert_v2_safe_bootstrap(cursor) -> None:
    if detect_v1_schema(cursor):
        raise RuntimeError(V1_MIGRATION_ERROR)


def _coerce_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val[:10])
    return None


def schedules_overlap(
    from_a: date,
    to_a: date | None,
    from_b: date,
    to_b: date | None,
) -> bool:
    from_b = _coerce_date(from_b) or from_a
    to_b = _coerce_date(to_b) if to_b is not None else None
    end_a = to_a or date.max
    end_b = to_b or date.max
    return from_a <= end_b and from_b <= end_a


def close_schedule_before(
    cursor,
    *,
    table: str,
    id_column: str,
    schedule_id: int,
    new_effective_from: date,
) -> date:
    """Set effective_to on prior schedule to day before new_effective_from."""
    close_date = new_effective_from - timedelta(days=1)
    cursor.execute(
        f"""
        UPDATE {table}
        SET effective_to = %s
        WHERE {id_column} = %s
          AND effective_from < %s
          AND (effective_to IS NULL OR effective_to >= %s)
        """,
        (close_date, schedule_id, new_effective_from, new_effective_from),
    )
    return close_date


def assert_no_overlapping_schedules(
    cursor,
    *,
    table: str,
    scope_column: str,
    scope_id: int,
    effective_from: date,
    effective_to: date | None = None,
    exclude_id: int | None = None,
) -> None:
    cursor.execute(
        f"SELECT id, effective_from, effective_to FROM {table} WHERE {scope_column} = %s",
        (scope_id,),
    )
    for row in cursor.fetchall() or []:
        sid = int(row["id"])
        if exclude_id and sid == exclude_id:
            continue
        ef = _coerce_date(row["effective_from"])
        et = _coerce_date(row.get("effective_to"))
        if ef and schedules_overlap(effective_from, effective_to, ef, et):
            raise ValueError(
                f"Overlapping schedule in {table} for {scope_column}={scope_id}: "
                f"existing id={sid} ({ef}..{et or 'open'}) conflicts with {effective_from}..{effective_to or 'open'}"
            )


def resolve_single_active_schedule(
    cursor,
    *,
    table: str,
    scope_column: str,
    scope_id: int,
    as_of: date,
) -> dict | None:
    cursor.execute(
        f"""
        SELECT * FROM {table}
        WHERE {scope_column} = %s
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC
        """,
        (scope_id, as_of, as_of),
    )
    rows = cursor.fetchall() or []
    if len(rows) > 1:
        ids = [int(r["id"]) for r in rows]
        raise ValueError(
            f"Ambiguous pricing: {len(rows)} active schedules in {table} "
            f"for {scope_column}={scope_id} on {as_of.isoformat()} (ids={ids})"
        )
    return rows[0] if rows else None


def json_dump(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, default=str)


def upsert_entry_line(
    cursor,
    *,
    daily_entry_id: int,
    line_key: str,
    line_category: str,
    amount: float,
    quantity: float | None = None,
    commercial_account_id: int | None = None,
    source_system: str = SOURCE_MANUAL,
    source_ref: str | None = None,
    source_payload: dict | None = None,
    is_override: bool = False,
    override_reason: str | None = None,
    user_id: int | None = None,
    pricing_schedule_id: int | None = None,
    rate_snapshot: dict | None = None,
    existing_line: dict | None = None,
    on_change: callable | None = None,
) -> None:
    """Portable upsert (SELECT + UPDATE/INSERT) for dr_daily_entry_lines."""
    old_amt = float(existing_line.get("amount") or 0) if existing_line else None
    payload_json = json_dump(source_payload)
    snapshot_json = json_dump(rate_snapshot)
    overridden_at = datetime.utcnow() if is_override else None
    overridden_by = user_id if is_override else None

    if existing_line:
        cursor.execute(
            """
            UPDATE dr_daily_entry_lines SET
              line_category = %s, amount = %s, quantity = %s, commercial_account_id = %s,
              source_system = %s, source_ref = %s, source_payload = %s,
              is_manual_override = %s, override_reason = %s, overridden_by = %s, overridden_at = %s,
              pricing_schedule_id = %s, rate_snapshot_json = %s
            WHERE id = %s
            """,
            (
                line_category, amount, quantity, commercial_account_id,
                source_system, source_ref, payload_json,
                1 if is_override else 0, override_reason, overridden_by, overridden_at,
                pricing_schedule_id, snapshot_json,
                int(existing_line["id"]),
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO dr_daily_entry_lines (
              daily_entry_id, line_key, line_category, amount, quantity, commercial_account_id,
              source_system, source_ref, source_payload,
              is_manual_override, override_reason, overridden_by, overridden_at,
              pricing_schedule_id, rate_snapshot_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                daily_entry_id, line_key, line_category, amount, quantity, commercial_account_id,
                source_system, source_ref, payload_json,
                1 if is_override else 0, override_reason, overridden_by, overridden_at,
                pricing_schedule_id, snapshot_json,
            ),
        )

    if on_change and existing_line is not None and old_amt is not None and old_amt != amount:
        on_change(line_key=line_key, old_value=str(old_amt), new_value=str(amount), is_override=is_override)


# ── Workflow ───────────────────────────────────────────────────────────────

EDITABLE_STATUSES = frozenset({ENTRY_STATUS_OPEN})

WORKFLOW_TRANSITIONS: dict[str, tuple[str, str]] = {
    "lock": (ENTRY_STATUS_OPEN, ENTRY_STATUS_LOCKED),
    "submit": (ENTRY_STATUS_OPEN, ENTRY_STATUS_SUBMITTED),
    "approve": (ENTRY_STATUS_SUBMITTED, ENTRY_STATUS_APPROVED),
    "reject": (ENTRY_STATUS_SUBMITTED, ENTRY_STATUS_REJECTED),
    "reopen": (ENTRY_STATUS_REJECTED, ENTRY_STATUS_OPEN),
}

WORKFLOW_AUDIT_EVENT = {
    "lock": "locked",
    "submit": "submitted",
    "approve": "approved",
    "reject": "rejected",
    "reopen": "reopened",
}


def assert_entry_editable(header: dict | None, payload: dict | None = None) -> None:
    if not header:
        return
    status = str(header.get("status") or ENTRY_STATUS_OPEN)
    if status == ENTRY_STATUS_REJECTED:
        if payload and payload.get("reopen"):
            return
        raise ValueError("Entry is rejected; use reopen action or pass reopen=true before editing")
    if status not in EDITABLE_STATUSES:
        raise ValueError(f"Entry status '{status}' cannot be edited through normal save")


def transition_entry_status(
    cursor,
    org_id: int,
    entry_date: date,
    action: str,
    *,
    user_id: int | None = None,
    notes: str | None = None,
    log_audit: callable,
) -> dict:
    action = (action or "").strip().lower()
    if action not in WORKFLOW_TRANSITIONS:
        raise ValueError(f"Unknown workflow action: {action}")

    cursor.execute(
        "SELECT * FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, entry_date),
    )
    header = cursor.fetchone()
    if not header:
        raise LookupError("Daily entry not found")

    required_from, new_status = WORKFLOW_TRANSITIONS[action]
    current = str(header.get("status") or ENTRY_STATUS_OPEN)
    if current != required_from:
        raise ValueError(f"Cannot {action} entry in status '{current}' (requires '{required_from}')")

    entry_id = int(header["id"])
    now = datetime.utcnow()
    updates: dict[str, Any] = {"status": new_status, "modified_by": user_id}

    if action == "lock":
        updates.update({"locked_by": user_id, "locked_at": now})
    elif action == "submit":
        updates.update({"submitted_by": user_id, "submitted_at": now})
    elif action in ("approve", "reject"):
        updates.update({"reviewed_by": user_id, "reviewed_at": now, "review_notes": notes})
    elif action == "reopen":
        updates.update({"review_notes": notes})

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    cursor.execute(
        f"UPDATE dr_daily_entries SET {set_clause} WHERE id = %s",
        tuple(updates.values()) + (entry_id,),
    )

    log_audit(
        cursor,
        entry_id,
        WORKFLOW_AUDIT_EVENT[action],
        actor_user_id=user_id,
        field_name="status",
        old_value=current,
        new_value=new_status,
        notes=notes,
    )

    cursor.execute("SELECT * FROM dr_daily_entries WHERE id = %s", (entry_id,))
    return cursor.fetchone()
