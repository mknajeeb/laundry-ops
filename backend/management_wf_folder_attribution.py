"""Auditable attribution override layer for WF Folder Performance.

Wrong-scanner correction without rewriting historical scan events.
Original scanner attribution is preserved; effective employee/session drives rates.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.ta_helpers import table_exists

OVERRIDE_ACTIVE = "active"
OVERRIDE_RESET = "reset"
ACTION_MOVE = "move"
ACTION_RESET = "reset"


def ensure_wf_folder_attribution_tables(cursor) -> None:
    if not table_exists(cursor, "rinse_wf_folder_attribution_overrides"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rinse_wf_folder_attribution_overrides (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              bag_id VARCHAR(64) NOT NULL,
              selected_date_et DATE NOT NULL,
              original_employee_name VARCHAR(255) NOT NULL,
              original_scanner_name VARCHAR(255) NULL,
              original_completion_et DATETIME NULL,
              effective_employee_name VARCHAR(255) NOT NULL,
              effective_session_id VARCHAR(64) NULL,
              effective_segment_id INT NULL,
              override_status VARCHAR(32) NOT NULL DEFAULT 'active',
              actor_user_id INT NULL,
              actor_name VARCHAR(255) NULL,
              note VARCHAR(512) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_wf_folder_attr_org_bag_date (organization_id, bag_id, selected_date_et),
              KEY idx_wf_folder_attr_org_date (organization_id, selected_date_et),
              KEY idx_wf_folder_attr_status (organization_id, override_status, selected_date_et),
              KEY idx_wf_folder_attr_effective_emp (organization_id, effective_employee_name, selected_date_et)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, "rinse_wf_folder_attribution_override_events"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rinse_wf_folder_attribution_override_events (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              bag_id VARCHAR(64) NOT NULL,
              selected_date_et DATE NOT NULL,
              action VARCHAR(32) NOT NULL,
              original_employee_name VARCHAR(255) NULL,
              from_employee_name VARCHAR(255) NULL,
              to_employee_name VARCHAR(255) NULL,
              from_session_id VARCHAR(64) NULL,
              to_session_id VARCHAR(64) NULL,
              to_segment_id INT NULL,
              actor_user_id INT NULL,
              actor_name VARCHAR(255) NULL,
              note VARCHAR(512) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_wf_folder_attr_ev_org_date (organization_id, selected_date_et),
              KEY idx_wf_folder_attr_ev_bag (organization_id, bag_id),
              KEY idx_wf_folder_attr_ev_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _norm_name(raw: Any) -> str:
    return str(raw or "").strip()


def _bag_key(raw: Any) -> str:
    return str(raw or "").strip().upper()


def load_active_attribution_overrides(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return active overrides keyed by bag_id (upper)."""
    ensure_wf_folder_attribution_tables(cursor)
    if not table_exists(cursor, "rinse_wf_folder_attribution_overrides"):
        return {}
    org = int(organization_id)
    where = [
        "organization_id = %s",
        "selected_date_et = %s",
        "override_status = %s",
    ]
    params: list[Any] = [org, selected_date_et, OVERRIDE_ACTIVE]
    ids = [_bag_key(b) for b in (bag_ids or []) if b]
    if ids:
        ph = ",".join(["%s"] * len(ids))
        where.append(f"bag_id IN ({ph})")
        params.extend(ids)
    cursor.execute(
        f"""
        SELECT bag_id, selected_date_et,
               original_employee_name, original_scanner_name, original_completion_et,
               effective_employee_name, effective_session_id, effective_segment_id,
               override_status, actor_user_id, actor_name, note,
               created_at, updated_at
        FROM rinse_wf_folder_attribution_overrides
        WHERE {' AND '.join(where)}
        """,
        tuple(params),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _bag_key(row.get("bag_id"))
        if bid:
            out[bid] = dict(row)
    return out


def load_active_attribution_overrides_for_dates(
    cursor,
    organization_id: int,
    *,
    date_start_et: date,
    date_end_et: date,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Active overrides for a date range keyed by (date_iso, bag_id)."""
    ensure_wf_folder_attribution_tables(cursor)
    if not table_exists(cursor, "rinse_wf_folder_attribution_overrides"):
        return {}
    org = int(organization_id)
    cursor.execute(
        """
        SELECT bag_id, selected_date_et,
               original_employee_name, original_scanner_name, original_completion_et,
               effective_employee_name, effective_session_id, effective_segment_id,
               override_status, actor_user_id, actor_name, note,
               created_at, updated_at
        FROM rinse_wf_folder_attribution_overrides
        WHERE organization_id = %s
          AND selected_date_et >= %s
          AND selected_date_et <= %s
          AND override_status = %s
        """,
        (org, date_start_et, date_end_et, OVERRIDE_ACTIVE),
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _bag_key(row.get("bag_id"))
        day = row.get("selected_date_et")
        if not bid or day is None:
            continue
        day_iso = day.isoformat() if isinstance(day, date) else str(day)[:10]
        out[(day_iso, bid)] = dict(row)
    return out


def _record_event(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    action: str,
    original_employee_name: str | None,
    from_employee_name: str | None,
    to_employee_name: str | None,
    from_session_id: str | None,
    to_session_id: str | None,
    to_segment_id: int | None,
    actor_user_id: int | None,
    actor_name: str | None,
    note: str | None,
) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_wf_folder_attribution_override_events (
          organization_id, bag_id, selected_date_et, action,
          original_employee_name, from_employee_name, to_employee_name,
          from_session_id, to_session_id, to_segment_id,
          actor_user_id, actor_name, note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            _bag_key(bag_id),
            selected_date_et,
            action,
            original_employee_name,
            from_employee_name,
            to_employee_name,
            from_session_id,
            to_session_id,
            to_segment_id,
            actor_user_id,
            actor_name,
            note,
        ),
    )


def move_bag_attribution(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    original_employee_name: str,
    original_scanner_name: str | None,
    original_completion_et: datetime | str | None,
    from_employee_name: str | None,
    from_session_id: str | None,
    to_employee_name: str,
    to_session_id: str | None,
    to_segment_id: int | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Upsert an active attribution override for one bag."""
    ensure_wf_folder_attribution_tables(cursor)
    bid = _bag_key(bag_id)
    if not bid:
        raise ValueError("bag_id required")
    to_emp = _norm_name(to_employee_name)
    if not to_emp:
        raise ValueError("to_employee_name required")
    orig = _norm_name(original_employee_name) or to_emp
    scanner = _norm_name(original_scanner_name) or orig
    completion = _parse_dt(original_completion_et)
    sid = str(to_session_id).strip() if to_session_id else None
    if sid in ("", "null", "None", "unassigned", "UNASSIGNED"):
        sid = None
    org = int(organization_id)

    cursor.execute(
        """
        INSERT INTO rinse_wf_folder_attribution_overrides (
          organization_id, bag_id, selected_date_et,
          original_employee_name, original_scanner_name, original_completion_et,
          effective_employee_name, effective_session_id, effective_segment_id,
          override_status, actor_user_id, actor_name, note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          effective_employee_name = VALUES(effective_employee_name),
          effective_session_id = VALUES(effective_session_id),
          effective_segment_id = VALUES(effective_segment_id),
          override_status = VALUES(override_status),
          actor_user_id = VALUES(actor_user_id),
          actor_name = VALUES(actor_name),
          note = VALUES(note),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            org,
            bid,
            selected_date_et,
            orig,
            scanner,
            completion,
            to_emp,
            sid,
            to_segment_id,
            OVERRIDE_ACTIVE,
            actor_user_id,
            actor_name,
            note,
        ),
    )
    _record_event(
        cursor,
        org,
        bag_id=bid,
        selected_date_et=selected_date_et,
        action=ACTION_MOVE,
        original_employee_name=orig,
        from_employee_name=from_employee_name,
        to_employee_name=to_emp,
        from_session_id=from_session_id,
        to_session_id=sid,
        to_segment_id=to_segment_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        note=note,
    )
    return {
        "bag_id": bid,
        "selected_date_et": selected_date_et.isoformat(),
        "original_employee_name": orig,
        "original_scanner_name": scanner,
        "effective_employee_name": to_emp,
        "effective_session_id": sid,
        "effective_segment_id": to_segment_id,
        "override_status": OVERRIDE_ACTIVE,
        "reassigned": True,
    }


def reset_bag_attribution(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Clear override so original scanner attribution applies again."""
    ensure_wf_folder_attribution_tables(cursor)
    bid = _bag_key(bag_id)
    if not bid:
        raise ValueError("bag_id required")
    org = int(organization_id)
    existing = load_active_attribution_overrides(
        cursor, org, selected_date_et=selected_date_et, bag_ids=[bid]
    ).get(bid)
    if not existing:
        return {
            "bag_id": bid,
            "selected_date_et": selected_date_et.isoformat(),
            "override_status": OVERRIDE_RESET,
            "reset": False,
            "message": "No active override",
        }

    cursor.execute(
        """
        UPDATE rinse_wf_folder_attribution_overrides
        SET override_status = %s,
            actor_user_id = %s,
            actor_name = %s,
            note = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s
          AND bag_id = %s
          AND selected_date_et = %s
        """,
        (
            OVERRIDE_RESET,
            actor_user_id,
            actor_name,
            note,
            org,
            bid,
            selected_date_et,
        ),
    )
    _record_event(
        cursor,
        org,
        bag_id=bid,
        selected_date_et=selected_date_et,
        action=ACTION_RESET,
        original_employee_name=existing.get("original_employee_name"),
        from_employee_name=existing.get("effective_employee_name"),
        to_employee_name=existing.get("original_employee_name"),
        from_session_id=existing.get("effective_session_id"),
        to_session_id=None,
        to_segment_id=None,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        note=note,
    )
    return {
        "bag_id": bid,
        "selected_date_et": selected_date_et.isoformat(),
        "original_employee_name": existing.get("original_employee_name"),
        "override_status": OVERRIDE_RESET,
        "reset": True,
    }


def apply_override_to_bag(
    bag: Mapping[str, Any],
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Stamp effective attribution fields onto a bag dict without mutating scans."""
    b = dict(bag)
    original = _norm_name(
        b.get("original_scanner")
        or b.get("original_employee_name")
        or b.get("credited_employee")
        or b.get("completed_by_employee")
        or b.get("employee")
    )
    b.setdefault("original_scanner", original)
    b.setdefault("original_employee_name", original)
    if not override:
        b["effective_employee"] = original
        b["credited_employee"] = original
        b["employee"] = original
        b["attribution_overridden"] = False
        b["reassignment_indicator"] = False
        return b

    effective = _norm_name(override.get("effective_employee_name")) or original
    b["original_scanner"] = _norm_name(override.get("original_scanner_name")) or original
    b["original_employee_name"] = _norm_name(override.get("original_employee_name")) or original
    b["effective_employee"] = effective
    b["credited_employee"] = effective
    b["employee"] = effective
    b["completed_by_employee"] = effective
    b["attribution_overridden"] = True
    b["reassignment_indicator"] = True
    b["override_session_id"] = override.get("effective_session_id")
    b["override_segment_id"] = override.get("effective_segment_id")
    b["override_actor_name"] = override.get("actor_name")
    b["override_note"] = override.get("note")
    return b
