"""Lost & Found records for one facility organization.

One row per reported item. Photographs, status changes, and reconciliation
snapshots are append-only history. ``reported_at`` and the other business
clocks are naive America/New_York wall times (same as task activities).
This module does not write Rinse order rows.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence

from backend.lost_found_rules import (
    ACTIVITY_CODE,
    CARRY_FORWARD_STATUSES,
    NOTIFY_EVENT_KEY,
    LostFoundError,
    as_day,
    as_dt,
    format_et_report,
    item_in_reconciliation_scope,
    reconciliation_blockers,
    snapshot_is_current,
    validate_location,
    validate_status_change,
)
from backend.payroll_identity import eastern_now_naive
from backend.ta_helpers import table_exists

logger = logging.getLogger(__name__)

ITEMS = "found_items"
PHOTOS = "found_item_photos"
EVENTS = "found_item_events"
ACCOUNTS = "found_item_accounts"
RECONCILIATIONS = "found_item_reconciliations"
SNAPSHOTS = "found_item_reconciliation_snapshots"

_SUPERVISOR_ROLES = ("ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN")


def _ensure_table(cursor, name: str, ddl: str) -> None:
    if table_exists(cursor, name):
        return
    cursor.execute(ddl)


def ensure_lost_found_tables(cursor) -> None:
    _ensure_table(
        cursor,
        ITEMS,
        f"""
        CREATE TABLE IF NOT EXISTS {ITEMS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          client_request_id VARCHAR(64) NOT NULL,
          reported_by_user_id INT NOT NULL,
          reporter_name VARCHAR(160) NOT NULL,
          facility_name VARCHAR(200) NULL,
          shift_session_id INT NULL,
          business_date DATE NOT NULL,
          reported_at DATETIME NOT NULL,
          location_kind VARCHAR(32) NOT NULL,
          location_number VARCHAR(40) NULL,
          location_detail VARCHAR(160) NULL,
          location_label VARCHAR(200) NOT NULL,
          notes VARCHAR(1000) NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'new',
          order_reference VARCHAR(80) NULL,
          status_comment VARCHAR(1000) NULL,
          resolved_reason VARCHAR(500) NULL,
          revision INT NOT NULL DEFAULT 1,
          status_changed_at DATETIME NOT NULL,
          status_changed_by_user_id INT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL,
          UNIQUE KEY uq_found_item_client (organization_id, client_request_id),
          KEY idx_found_item_org_day (organization_id, business_date),
          KEY idx_found_item_org_status (organization_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _ensure_table(
        cursor,
        PHOTOS,
        f"""
        CREATE TABLE IF NOT EXISTS {PHOTOS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          found_item_id BIGINT NULL,
          business_date DATE NULL,
          photo_role VARCHAR(20) NOT NULL,
          blob_name VARCHAR(255) NOT NULL,
          stored_filename VARCHAR(80) NOT NULL,
          content_type VARCHAR(80) NOT NULL,
          storage VARCHAR(16) NOT NULL,
          captured_at DATETIME NOT NULL,
          uploaded_by_user_id INT NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          KEY idx_found_photo_item (found_item_id),
          KEY idx_found_photo_day (organization_id, business_date, photo_role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )
    _ensure_table(
        cursor,
        EVENTS,
        f"""
        CREATE TABLE IF NOT EXISTS {EVENTS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          found_item_id BIGINT NULL,
          event_type VARCHAR(40) NOT NULL,
          actor_user_id INT NULL,
          actor_name VARCHAR(160) NULL,
          payload_json TEXT NULL,
          created_at DATETIME NOT NULL,
          KEY idx_found_event_item (found_item_id),
          KEY idx_found_event_org (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )
    _ensure_table(
        cursor,
        ACCOUNTS,
        f"""
        CREATE TABLE IF NOT EXISTS {ACCOUNTS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          business_date DATE NOT NULL,
          found_item_id BIGINT NOT NULL,
          revision INT NOT NULL,
          status_snapshot VARCHAR(32) NOT NULL,
          escalated TINYINT(1) NOT NULL DEFAULT 0,
          comment VARCHAR(1000) NULL,
          accounted_by_user_id INT NOT NULL,
          accounted_by_name VARCHAR(160) NULL,
          accounted_at DATETIME NOT NULL,
          UNIQUE KEY uq_found_account (organization_id, business_date, found_item_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )
    _ensure_table(
        cursor,
        RECONCILIATIONS,
        f"""
        CREATE TABLE IF NOT EXISTS {RECONCILIATIONS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          business_date DATE NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'open',
          started_at DATETIME NOT NULL,
          completed_at DATETIME NULL,
          completed_by_user_id INT NULL,
          activity_id BIGINT NULL,
          box_photo_id BIGINT NULL,
          UNIQUE KEY uq_found_recon (organization_id, business_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )
    _ensure_table(
        cursor,
        SNAPSHOTS,
        f"""
        CREATE TABLE IF NOT EXISTS {SNAPSHOTS} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          business_date DATE NOT NULL,
          activity_id BIGINT NULL,
          completed_by_user_id INT NOT NULL,
          completed_by_name VARCHAR(160) NULL,
          completed_at DATETIME NOT NULL,
          box_photo_id BIGINT NULL,
          snapshot_json LONGTEXT NOT NULL,
          KEY idx_found_snap_day (organization_id, business_date, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _loads(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _write_audit(
    cursor,
    *,
    organization_id: int,
    actor_user_id: int | None,
    item_id: int | None,
    action: str,
    old: Any,
    new: Any,
    remarks: str,
) -> None:
    if not table_exists(cursor, "audit_log"):
        return
    try:
        cursor.execute(
            """
            INSERT INTO audit_log (
              organization_id, actor_user_id, entity_type, entity_id,
              action, old_value, new_value, remarks
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                actor_user_id,
                "found_item",
                str(item_id) if item_id is not None else None,
                action[:64],
                _json(old) if old is not None else None,
                _json(new) if new is not None else None,
                (remarks or "")[:500],
            ),
        )
    except Exception:
        logger.debug("found item audit_log insert skipped", exc_info=True)


def _event(
    cursor,
    *,
    organization_id: int,
    found_item_id: int | None,
    event_type: str,
    actor_user_id: int | None,
    actor_name: str | None,
    payload: Mapping[str, Any] | None,
    at: datetime,
) -> None:
    cursor.execute(
        f"""
        INSERT INTO {EVENTS} (
          organization_id, found_item_id, event_type, actor_user_id, actor_name,
          payload_json, created_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(found_item_id) if found_item_id is not None else None,
            event_type[:40],
            actor_user_id,
            (actor_name or "")[:160] or None,
            _json(payload) if payload is not None else None,
            at,
        ),
    )


def _photo_out(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "found_item_id": int(row["found_item_id"]) if row.get("found_item_id") not in (None, "") else None,
        "photo_role": row.get("photo_role"),
        "content_type": row.get("content_type"),
        "captured_at": as_dt(row.get("captured_at")).isoformat(sep=" ") if as_dt(row.get("captured_at")) else None,
        "captured_at_display": format_et_report(row.get("captured_at")),
        "uploaded_by_user_id": row.get("uploaded_by_user_id"),
    }


def _event_out(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "event_type": row.get("event_type"),
        "actor_user_id": row.get("actor_user_id"),
        "actor_name": row.get("actor_name"),
        "created_at_display": format_et_report(row.get("created_at")),
        "payload": _loads(row.get("payload_json")) or {},
    }


def serialize_item(
    row: Mapping[str, Any],
    *,
    photos: Sequence[Mapping[str, Any]] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    account: Mapping[str, Any] | None = None,
    reconciliation_date: Any = None,
) -> dict[str, Any]:
    reported = as_dt(row.get("reported_at"))
    changed = as_dt(row.get("status_changed_at"))
    day = as_day(row.get("business_date"))
    recon_day = as_day(reconciliation_date) if reconciliation_date else day
    return {
        "id": int(row["id"]),
        "organization_id": int(row["organization_id"]),
        "client_request_id": row.get("client_request_id"),
        "business_date": day,
        "reported_at": reported.isoformat(sep=" ") if reported else None,
        "reported_at_display": format_et_report(reported),
        "employee_id": int(row["reported_by_user_id"]) if row.get("reported_by_user_id") is not None else None,
        "employee_name": row.get("reporter_name"),
        "facility_name": row.get("facility_name"),
        "shift_session_id": int(row["shift_session_id"]) if row.get("shift_session_id") not in (None, "") else None,
        "location_kind": row.get("location_kind"),
        "location_number": row.get("location_number"),
        "location_detail": row.get("location_detail"),
        "location_label": row.get("location_label"),
        "notes": row.get("notes"),
        "status": row.get("status"),
        "order_reference": row.get("order_reference"),
        "status_comment": row.get("status_comment"),
        "resolved_reason": row.get("resolved_reason"),
        "revision": int(row.get("revision") or 1),
        "status_changed_at_display": format_et_report(changed),
        "status_changed_by_user_id": row.get("status_changed_by_user_id"),
        "photos": [_photo_out(p) for p in (photos or [])],
        "events": [_event_out(e) for e in (events or [])],
        "account": _account_out(account) if account else None,
        "carried_forward": bool(reconciliation_date) and day < recon_day,
    }


def _account_out(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "revision": int(row.get("revision") or 0),
        "status_snapshot": row.get("status_snapshot"),
        "escalated": bool(row.get("escalated")),
        "comment": row.get("comment"),
        "accounted_by_user_id": row.get("accounted_by_user_id"),
        "accounted_by_name": row.get("accounted_by_name"),
        "accounted_at_display": format_et_report(row.get("accounted_at")),
    }


def _fetch_one(cursor, sql: str, params: Sequence[Any]) -> dict[str, Any] | None:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return dict(row) if row else None


def _fetch_all(cursor, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return [dict(r) for r in (cursor.fetchall() or [])]


def get_item(cursor, organization_id: int, item_id: int) -> dict[str, Any] | None:
    ensure_lost_found_tables(cursor)
    return _fetch_one(
        cursor,
        f"SELECT * FROM {ITEMS} WHERE organization_id=%s AND id=%s LIMIT 1",
        (int(organization_id), int(item_id)),
    )


def _by_client(cursor, organization_id: int, client_request_id: str) -> dict[str, Any] | None:
    return _fetch_one(
        cursor,
        f"""
        SELECT * FROM {ITEMS}
        WHERE organization_id=%s AND client_request_id=%s
        LIMIT 1
        """,
        (int(organization_id), client_request_id),
    )


def _photos_for(cursor, organization_id: int, item_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    if not item_ids:
        return {}
    marks = ",".join(["%s"] * len(item_ids))
    rows = _fetch_all(
        cursor,
        f"""
        SELECT * FROM {PHOTOS}
        WHERE organization_id=%s AND found_item_id IN ({marks})
        ORDER BY id ASC
        """,
        (int(organization_id), *[int(i) for i in item_ids]),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["found_item_id"]), []).append(row)
    return grouped


def _events_for(cursor, organization_id: int, item_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    if not item_ids:
        return {}
    marks = ",".join(["%s"] * len(item_ids))
    rows = _fetch_all(
        cursor,
        f"""
        SELECT * FROM {EVENTS}
        WHERE organization_id=%s AND found_item_id IN ({marks})
        ORDER BY id ASC
        """,
        (int(organization_id), *[int(i) for i in item_ids]),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["found_item_id"]), []).append(row)
    return grouped


def _hydrate(cursor, organization_id: int, rows: Sequence[Mapping[str, Any]], *, reconciliation_date: Any = None) -> list[dict[str, Any]]:
    ids = [int(r["id"]) for r in rows]
    photos = _photos_for(cursor, organization_id, ids)
    events = _events_for(cursor, organization_id, ids)
    return [
        serialize_item(
            row,
            photos=photos.get(int(row["id"]), []),
            events=events.get(int(row["id"]), []),
            reconciliation_date=reconciliation_date,
        )
        for row in rows
    ]


def report_found_item(
    cursor,
    *,
    organization_id: int,
    client_request_id: str,
    user_id: int,
    reporter_name: str,
    facility_name: str | None,
    shift_session_id: int | None,
    business_date: date,
    location_kind: str,
    location_number: str | None,
    location_detail: str | None,
    notes: str | None,
) -> tuple[dict[str, Any], bool]:
    """Create one item, or return the original when the same client request is retried."""
    ensure_lost_found_tables(cursor)
    request_id = str(client_request_id or "").strip()
    if len(request_id) < 8 or len(request_id) > 64 or any(ch.isspace() for ch in request_id):
        raise LostFoundError("A client request id is required.", code="client_request_required")
    existing = _by_client(cursor, organization_id, request_id)
    if existing:
        hydrated = _hydrate(cursor, organization_id, [existing])
        return hydrated[0], False
    location = validate_location(location_kind, location_number, location_detail)
    note = " ".join(str(notes or "").split())[:1000] or None
    at = eastern_now_naive().replace(microsecond=0)
    cursor.execute(
        f"""
        INSERT INTO {ITEMS} (
          organization_id, client_request_id, reported_by_user_id, reporter_name,
          facility_name, shift_session_id, business_date, reported_at,
          location_kind, location_number, location_detail, location_label, notes,
          status, revision, status_changed_at, status_changed_by_user_id, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            request_id,
            int(user_id),
            (reporter_name or "Employee")[:160],
            (facility_name or "")[:200] or None,
            int(shift_session_id) if shift_session_id else None,
            business_date,
            at,
            location["location_kind"],
            location["location_number"],
            location["location_detail"],
            location["location_label"],
            note,
            "new",
            1,
            at,
            int(user_id),
            at,
        ),
    )
    item_id = int(cursor.lastrowid)
    created = get_item(cursor, organization_id, item_id)
    if not created:
        raced = _by_client(cursor, organization_id, request_id)
        if raced:
            return _hydrate(cursor, organization_id, [raced])[0], False
        raise LostFoundError("Could not save the found item.", status=500, code="save_failed")
    _event(
        cursor,
        organization_id=organization_id,
        found_item_id=item_id,
        event_type="reported",
        actor_user_id=int(user_id),
        actor_name=reporter_name,
        payload={
            "location_label": location["location_label"],
            "status": "new",
            "shift_session_id": int(shift_session_id) if shift_session_id else None,
        },
        at=at,
    )
    _write_audit(
        cursor,
        organization_id=organization_id,
        actor_user_id=int(user_id),
        item_id=item_id,
        action="found_item_reported",
        old=None,
        new={"status": "new", "location_label": location["location_label"]},
        remarks=location["location_label"],
    )
    _mark_open_reconciliation_stale(cursor, organization_id, business_date)
    return _hydrate(cursor, organization_id, [created])[0], True


def add_item_photo(
    cursor,
    *,
    organization_id: int,
    found_item_id: int,
    user_id: int,
    stored: Mapping[str, str],
) -> dict[str, Any]:
    ensure_lost_found_tables(cursor)
    item = get_item(cursor, organization_id, found_item_id)
    if not item:
        raise LostFoundError("Found item not found.", status=404, code="not_found")
    at = eastern_now_naive().replace(microsecond=0)
    cursor.execute(
        f"""
        INSERT INTO {PHOTOS} (
          organization_id, found_item_id, business_date, photo_role, blob_name,
          stored_filename, content_type, storage, captured_at, uploaded_by_user_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(found_item_id),
            item.get("business_date"),
            "discovery",
            stored["blob_name"],
            stored["stored_filename"],
            stored["content_type"],
            stored["storage"],
            at,
            int(user_id),
        ),
    )
    return {"id": int(cursor.lastrowid), "captured_at": at}


def change_status(
    cursor,
    *,
    organization_id: int,
    item_id: int,
    actor_user_id: int,
    actor_name: str | None,
    status: str,
    order_reference: str | None = None,
    comment: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    ensure_lost_found_tables(cursor)
    current = get_item(cursor, organization_id, item_id)
    if not current:
        raise LostFoundError("Found item not found.", status=404, code="not_found")
    cleaned = validate_status_change(
        status,
        order_reference=order_reference,
        comment=comment,
        reason=reason,
    )
    at = eastern_now_naive().replace(microsecond=0)
    revision = int(current.get("revision") or 1) + 1
    before = {
        "status": current.get("status"),
        "order_reference": current.get("order_reference"),
        "status_comment": current.get("status_comment"),
        "resolved_reason": current.get("resolved_reason"),
        "revision": int(current.get("revision") or 1),
    }
    cursor.execute(
        f"""
        UPDATE {ITEMS}
        SET status=%s, order_reference=%s, status_comment=%s, resolved_reason=%s,
            revision=%s, status_changed_at=%s, status_changed_by_user_id=%s, updated_at=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            cleaned["status"],
            cleaned["order_reference"],
            cleaned["status_comment"],
            cleaned["resolved_reason"],
            revision,
            at,
            int(actor_user_id),
            at,
            int(item_id),
            int(organization_id),
        ),
    )
    _event(
        cursor,
        organization_id=organization_id,
        found_item_id=int(item_id),
        event_type="status_changed",
        actor_user_id=int(actor_user_id),
        actor_name=actor_name,
        payload={"from": before, "to": {**cleaned, "revision": revision}},
        at=at,
    )
    _write_audit(
        cursor,
        organization_id=organization_id,
        actor_user_id=int(actor_user_id),
        item_id=int(item_id),
        action="found_item_status",
        old=before,
        new={**cleaned, "revision": revision},
        remarks=cleaned["status"],
    )
    updated = get_item(cursor, organization_id, item_id)
    return _hydrate(cursor, organization_id, [updated or current])[0]


def list_found_items(
    cursor,
    organization_id: int,
    *,
    business_date: date | None = None,
    before_date: date | None = None,
) -> list[dict[str, Any]]:
    ensure_lost_found_tables(cursor)
    if business_date is not None:
        rows = _fetch_all(
            cursor,
            f"""
            SELECT * FROM {ITEMS}
            WHERE organization_id=%s AND business_date=%s
            ORDER BY reported_at ASC, id ASC
            """,
            (int(organization_id), business_date),
        )
    elif before_date is not None:
        rows = _fetch_all(
            cursor,
            f"""
            SELECT * FROM {ITEMS}
            WHERE organization_id=%s AND business_date < %s
            ORDER BY reported_at DESC, id DESC
            LIMIT 300
            """,
            (int(organization_id), before_date),
        )
    else:
        rows = _fetch_all(
            cursor,
            f"""
            SELECT * FROM {ITEMS}
            WHERE organization_id=%s
            ORDER BY reported_at DESC, id DESC
            LIMIT 300
            """,
            (int(organization_id),),
        )
    return _hydrate(cursor, organization_id, rows)


def location_choices(cursor, organization_id: int) -> dict[str, list[str]]:
    washers: list[str] = []
    dryers: list[str] = []
    try:
        from backend.machine_configuration_settings import get_machine_rack_config

        config = get_machine_rack_config(cursor, int(organization_id))
        washers = sorted((config.get("washers") or {}).keys())
        dryers = sorted((config.get("dryers") or {}).keys())
    except Exception:
        logger.debug("machine identifiers unavailable", exc_info=True)
    return {"washers": washers, "dryers": dryers, "folding_tables": []}


def _scope_rows(cursor, organization_id: int, business_date: date) -> list[dict[str, Any]]:
    marks = ",".join(["%s"] * len(CARRY_FORWARD_STATUSES))
    return _fetch_all(
        cursor,
        f"""
        SELECT * FROM {ITEMS}
        WHERE organization_id=%s
          AND (business_date=%s OR status IN ({marks}))
        ORDER BY reported_at ASC, id ASC
        """,
        (int(organization_id), business_date, *sorted(CARRY_FORWARD_STATUSES)),
    )


def _accounts_for_day(cursor, organization_id: int, business_date: date) -> dict[int, dict[str, Any]]:
    rows = _fetch_all(
        cursor,
        f"SELECT * FROM {ACCOUNTS} WHERE organization_id=%s AND business_date=%s",
        (int(organization_id), business_date),
    )
    return {int(row["found_item_id"]): row for row in rows}


def _latest_box_photo(cursor, organization_id: int, business_date: date) -> dict[str, Any] | None:
    return _fetch_one(
        cursor,
        f"""
        SELECT * FROM {PHOTOS}
        WHERE organization_id=%s AND business_date=%s AND photo_role='box'
        ORDER BY captured_at DESC, id DESC
        LIMIT 1
        """,
        (int(organization_id), business_date),
    )


def _reconciliation_row(cursor, organization_id: int, business_date: date) -> dict[str, Any] | None:
    return _fetch_one(
        cursor,
        f"SELECT * FROM {RECONCILIATIONS} WHERE organization_id=%s AND business_date=%s LIMIT 1",
        (int(organization_id), business_date),
    )


def ensure_reconciliation_open(cursor, organization_id: int, business_date: date) -> dict[str, Any]:
    ensure_lost_found_tables(cursor)
    row = _reconciliation_row(cursor, organization_id, business_date)
    if row:
        return row
    at = eastern_now_naive().replace(microsecond=0)
    cursor.execute(
        f"""
        INSERT INTO {RECONCILIATIONS} (
          organization_id, business_date, status, started_at
        ) VALUES (%s,%s,'open',%s)
        """,
        (int(organization_id), business_date, at),
    )
    created = _reconciliation_row(cursor, organization_id, business_date)
    if not created:
        raise LostFoundError("Could not open reconciliation.", status=500, code="save_failed")
    return created


def reconciliation_view(cursor, organization_id: int, business_date: date) -> dict[str, Any]:
    recon = ensure_reconciliation_open(cursor, organization_id, business_date)
    raw_items = [
        row for row in _scope_rows(cursor, organization_id, business_date)
        if item_in_reconciliation_scope(row, business_date)
    ]
    accounts = _accounts_for_day(cursor, organization_id, business_date)
    photos = _photos_for(cursor, organization_id, [int(r["id"]) for r in raw_items])
    events = _events_for(cursor, organization_id, [int(r["id"]) for r in raw_items])
    items = [
        serialize_item(
            row,
            photos=photos.get(int(row["id"]), []),
            events=events.get(int(row["id"]), []),
            account=accounts.get(int(row["id"])),
            reconciliation_date=business_date,
        )
        for row in raw_items
    ]
    box = _latest_box_photo(cursor, organization_id, business_date)
    blockers = []
    if str(recon.get("status") or "") != "completed":
        blockers = reconciliation_blockers(
            raw_items,
            accounts,
            box_photo=box,
            started_at=recon.get("started_at"),
        )
    latest = _latest_snapshot(cursor, organization_id, business_date)
    return {
        "business_date": as_day(business_date),
        "status": recon.get("status") or "open",
        "started_at_display": format_et_report(recon.get("started_at")),
        "completed_at_display": format_et_report(recon.get("completed_at")),
        "activity_id": recon.get("activity_id"),
        "activity_code": ACTIVITY_CODE,
        "items": items,
        "blockers": blockers,
        "box_photo": _photo_out(box) if box else None,
        "snapshot": _snapshot_summary(latest) if latest else None,
    }


def account_item(
    cursor,
    *,
    organization_id: int,
    business_date: date,
    item_id: int,
    actor_user_id: int,
    actor_name: str | None,
    action: str,
    status: str | None = None,
    order_reference: str | None = None,
    comment: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    ensure_reconciliation_open(cursor, organization_id, business_date)
    kind = str(action or "").strip().lower()
    if kind not in {"confirm", "escalate", "update"}:
        raise LostFoundError("Choose confirm, escalate, or update.", code="invalid_action")
    current = get_item(cursor, organization_id, item_id)
    if not current or not item_in_reconciliation_scope(current, business_date):
        raise LostFoundError("That found item is not part of this reconciliation.", status=404, code="not_found")
    if kind == "update":
        current = change_status(
            cursor,
            organization_id=organization_id,
            item_id=item_id,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            status=str(status or ""),
            order_reference=order_reference,
            comment=comment,
            reason=reason,
        )
        stored = get_item(cursor, organization_id, item_id) or {}
    else:
        stored = current
    at = eastern_now_naive().replace(microsecond=0)
    revision = int(stored.get("revision") or current.get("revision") or 1)
    escalated = 1 if kind == "escalate" else 0
    note = " ".join(str(comment or "").split())[:1000] or None
    existing = _fetch_one(
        cursor,
        f"""
        SELECT id FROM {ACCOUNTS}
        WHERE organization_id=%s AND business_date=%s AND found_item_id=%s
        LIMIT 1
        """,
        (int(organization_id), business_date, int(item_id)),
    )
    values = (
        revision,
        stored.get("status") or current.get("status"),
        escalated,
        note,
        int(actor_user_id),
        (actor_name or "")[:160] or None,
        at,
        int(organization_id),
        business_date,
        int(item_id),
    )
    if existing:
        cursor.execute(
            f"""
            UPDATE {ACCOUNTS}
            SET revision=%s, status_snapshot=%s, escalated=%s, comment=%s,
                accounted_by_user_id=%s, accounted_by_name=%s, accounted_at=%s
            WHERE organization_id=%s AND business_date=%s AND found_item_id=%s
            """,
            values,
        )
    else:
        cursor.execute(
            f"""
            INSERT INTO {ACCOUNTS} (
              revision, status_snapshot, escalated, comment, accounted_by_user_id,
              accounted_by_name, accounted_at, organization_id, business_date, found_item_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            values,
        )
    _event(
        cursor,
        organization_id=organization_id,
        found_item_id=int(item_id),
        event_type="escalated" if escalated else "accounted",
        actor_user_id=int(actor_user_id),
        actor_name=actor_name,
        payload={"action": kind, "revision": revision, "comment": note, "business_date": as_day(business_date)},
        at=at,
    )
    return reconciliation_view(cursor, organization_id, business_date)


def add_box_photo(
    cursor,
    *,
    organization_id: int,
    business_date: date,
    user_id: int,
    stored: Mapping[str, str],
) -> dict[str, Any]:
    recon = ensure_reconciliation_open(cursor, organization_id, business_date)
    at = eastern_now_naive().replace(microsecond=0)
    cursor.execute(
        f"""
        INSERT INTO {PHOTOS} (
          organization_id, found_item_id, business_date, photo_role, blob_name,
          stored_filename, content_type, storage, captured_at, uploaded_by_user_id
        ) VALUES (%s,NULL,%s,'box',%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            business_date,
            stored["blob_name"],
            stored["stored_filename"],
            stored["content_type"],
            stored["storage"],
            at,
            int(user_id),
        ),
    )
    photo_id = int(cursor.lastrowid)
    cursor.execute(
        f"UPDATE {RECONCILIATIONS} SET box_photo_id=%s WHERE id=%s AND organization_id=%s",
        (photo_id, int(recon["id"]), int(organization_id)),
    )
    return reconciliation_view(cursor, organization_id, business_date)


def _latest_snapshot(cursor, organization_id: int, business_date: date) -> dict[str, Any] | None:
    row = _fetch_one(
        cursor,
        f"""
        SELECT * FROM {SNAPSHOTS}
        WHERE organization_id=%s AND business_date=%s
        ORDER BY id DESC LIMIT 1
        """,
        (int(organization_id), business_date),
    )
    if not row:
        return None
    row["snapshot"] = _loads(row.get("snapshot_json")) or {}
    return row


def _snapshot_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else _loads(row.get("snapshot_json")) or {}
    return {
        "id": int(row["id"]),
        "completed_at_display": format_et_report(row.get("completed_at")),
        "completed_by_user_id": row.get("completed_by_user_id"),
        "completed_by_name": row.get("completed_by_name"),
        "activity_id": row.get("activity_id"),
        "box_photo_id": row.get("box_photo_id"),
        "item_count": len(payload.get("items") or []),
    }


def _live_scope(cursor, organization_id: int, business_date: date) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    recon = ensure_reconciliation_open(cursor, organization_id, business_date)
    raw = [
        row for row in _scope_rows(cursor, organization_id, business_date)
        if item_in_reconciliation_scope(row, business_date)
    ]
    accounts = _accounts_for_day(cursor, organization_id, business_date)
    box = _latest_box_photo(cursor, organization_id, business_date)
    return raw, accounts, box, recon


def snapshot_reconciliation_on_complete(
    cursor,
    *,
    organization_id: int,
    user_id: int,
    user_name: str | None,
    business_date: date,
    activity_id: int | None,
) -> dict[str, Any]:
    raw, accounts, box, recon = _live_scope(cursor, organization_id, business_date)
    blockers = reconciliation_blockers(raw, accounts, box_photo=box, started_at=recon.get("started_at"))
    if blockers:
        raise LostFoundError(
            blockers[0]["message"],
            code=str(blockers[0].get("code") or "reconciliation_blocked"),
            blockers=blockers,
        )
    box_id = int(box["id"]) if box else None
    if str(recon.get("status") or "") == "completed":
        latest = _latest_snapshot(cursor, organization_id, business_date)
        stale = snapshot_is_current(
            (latest or {}).get("snapshot"),
            raw,
            box_photo_id=box_id,
        )
        if latest and not stale:
            return _snapshot_summary(latest)
    at = eastern_now_naive().replace(microsecond=0)
    payload = {
        "business_date": as_day(business_date),
        "completed_at": at.isoformat(sep=" "),
        "completed_by_user_id": int(user_id),
        "completed_by_name": user_name,
        "activity_id": int(activity_id) if activity_id else None,
        "box_photo_id": box_id,
        "items": [
            {
                "id": int(row["id"]),
                "revision": int(row.get("revision") or 1),
                "status": row.get("status"),
                "location_label": row.get("location_label"),
                "business_date": as_day(row.get("business_date")),
                "reported_at_display": format_et_report(row.get("reported_at")),
                "employee_name": row.get("reporter_name"),
                "escalated": bool((accounts.get(int(row["id"])) or {}).get("escalated")),
            }
            for row in raw
        ],
    }
    cursor.execute(
        f"""
        INSERT INTO {SNAPSHOTS} (
          organization_id, business_date, activity_id, completed_by_user_id,
          completed_by_name, completed_at, box_photo_id, snapshot_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            business_date,
            int(activity_id) if activity_id else None,
            int(user_id),
            (user_name or "")[:160] or None,
            at,
            box_id,
            _json(payload),
        ),
    )
    cursor.execute(
        f"""
        UPDATE {RECONCILIATIONS}
        SET status='completed', completed_at=%s, completed_by_user_id=%s,
            activity_id=%s, box_photo_id=%s
        WHERE organization_id=%s AND business_date=%s
        """,
        (
            at,
            int(user_id),
            int(activity_id) if activity_id else None,
            box_id,
            int(organization_id),
            business_date,
        ),
    )
    _write_audit(
        cursor,
        organization_id=organization_id,
        actor_user_id=int(user_id),
        item_id=None,
        action="found_item_reconciliation_completed",
        old=None,
        new={"business_date": as_day(business_date), "item_count": len(raw), "activity_id": activity_id},
        remarks=f"Lost & Found reconciliation {as_day(business_date)}",
    )
    return payload


def _coerce_day(value: Any) -> date:
    return date.fromisoformat(as_day(value))


def assert_reconciliation_current_for_approval(
    cursor,
    *,
    organization_id: int,
    business_date: Any,
) -> None:
    business_date = _coerce_day(business_date)
    ensure_lost_found_tables(cursor)
    if not table_exists(cursor, ITEMS):
        return
    raw = [
        row for row in _scope_rows(cursor, organization_id, business_date)
        if item_in_reconciliation_scope(row, business_date)
    ]
    box = _latest_box_photo(cursor, organization_id, business_date)
    latest = _latest_snapshot(cursor, organization_id, business_date)
    blockers = snapshot_is_current(
        (latest or {}).get("snapshot") if latest else None,
        raw,
        box_photo_id=int(box["id"]) if box else None,
    )
    if blockers:
        raise LostFoundError(
            blockers[0]["message"],
            code=str(blockers[0].get("code") or "snapshot_stale"),
            blockers=blockers,
        )


def reopen_reconciliation(cursor, organization_id: int, business_date: Any) -> None:
    business_date = _coerce_day(business_date)
    ensure_lost_found_tables(cursor)
    cursor.execute(
        f"""
        UPDATE {RECONCILIATIONS}
        SET status='open', completed_at=NULL
        WHERE organization_id=%s AND business_date=%s
        """,
        (int(organization_id), business_date),
    )


def _activity_status(cursor, organization_id: int, activity_id: int | None) -> str | None:
    if not activity_id or not table_exists(cursor, "cleaning_task_activities"):
        return None
    row = _fetch_one(
        cursor,
        """
        SELECT status FROM cleaning_task_activities
        WHERE organization_id=%s AND id=%s LIMIT 1
        """,
        (int(organization_id), int(activity_id)),
    )
    return str(row.get("status")) if row else None


def _mark_open_reconciliation_stale(cursor, organization_id: int, business_date: date) -> None:
    """A report after submission, before verification, must be included again."""
    row = _reconciliation_row(cursor, organization_id, business_date)
    if not row or str(row.get("status") or "") != "completed":
        return
    status = _activity_status(cursor, organization_id, row.get("activity_id"))
    if status in {None, "pending_approval", "rejected", "in_progress"}:
        reopen_reconciliation(cursor, organization_id, business_date)


def gate_lost_found_activity_completion(
    cursor,
    *,
    organization_id: int,
    user_id: int,
    user_name: str | None,
    business_date: Any,
    activity_id: int | None,
    role_codes: Sequence[Any],
) -> dict[str, Any] | None:
    codes = {str(code or "") for code in role_codes}
    if ACTIVITY_CODE not in codes:
        return None
    day_text = as_day(business_date)
    try:
        day = date.fromisoformat(day_text)
    except ValueError as exc:
        raise LostFoundError("Reconciliation day is missing.", code="invalid") from exc
    return snapshot_reconciliation_on_complete(
        cursor,
        organization_id=int(organization_id),
        user_id=int(user_id),
        user_name=user_name,
        business_date=day,
        activity_id=int(activity_id) if activity_id else None,
    )


def get_photo_row(cursor, organization_id: int, photo_id: int) -> dict[str, Any] | None:
    ensure_lost_found_tables(cursor)
    return _fetch_one(
        cursor,
        f"SELECT * FROM {PHOTOS} WHERE organization_id=%s AND id=%s LIMIT 1",
        (int(organization_id), int(photo_id)),
    )


def ensure_lost_found_activity(cursor, organization_id: int) -> None:
    """Seed the End of Day activity once. Later catalog edits stay put."""
    from backend.task_catalog import get_task_definition, seed_builtin_categories, upsert_task_definition

    seed_builtin_categories(cursor, int(organization_id))
    if get_task_definition(cursor, int(organization_id), ACTIVITY_CODE):
        return
    upsert_task_definition(
        cursor,
        int(organization_id),
        ACTIVITY_CODE,
        {
            "name": "Lost & Found Reconciliation",
            "category_code": "end_of_day",
            "completion_type": "simple",
            "timer_enabled": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "display_order": 90,
            "active": True,
        },
    )


def notify_found_item(cursor, organization_id: int, item: Mapping[str, Any]) -> None:
    """In-app push to this organization's supervisor audience only."""
    try:
        if not table_exists(cursor, "notification_event_definitions"):
            return
        cursor.execute(
            """
            INSERT IGNORE INTO notification_event_definitions
              (organization_id, event_key, display_name, description, is_active)
            VALUES (%s,%s,%s,%s,1)
            """,
            (
                int(organization_id),
                NOTIFY_EVENT_KEY,
                "Lost & Found item reported",
                "A found item was reported at this facility.",
            ),
        )
        cursor.execute(
            """
            SELECT id FROM notification_event_definitions
            WHERE organization_id=%s AND event_key=%s LIMIT 1
            """,
            (int(organization_id), NOTIFY_EVENT_KEY),
        )
        event = cursor.fetchone()
        if not event:
            return
        event_id = int(event["id"] if isinstance(event, dict) else event[0])
        _seed_supervisor_audience(cursor, organization_id, event_id)
        from backend.notification_service import dispatch_notification_event

        when = item.get("reported_at_display") or ""
        where = item.get("location_label") or "the facility"
        who = item.get("employee_name") or "An employee"
        dispatch_notification_event(
            cursor,
            organization_id=int(organization_id),
            event_key=NOTIFY_EVENT_KEY,
            title="Found item reported",
            body=f"{who} reported a found item at {where}. {when}".strip(),
            data={
                "found_item_id": item.get("id"),
                "open_path": "/management/lost-found",
                "location_label": where,
                "business_date": item.get("business_date"),
            },
            channels=["push"],
        )
    except Exception:
        logger.debug("lost found notification skipped", exc_info=True)


def _seed_supervisor_audience(cursor, organization_id: int, event_id: int) -> None:
    if not table_exists(cursor, "notification_event_audiences"):
        return
    cursor.execute(
        """
        SELECT id FROM notification_event_audiences
        WHERE event_definition_id=%s AND organization_id=%s LIMIT 1
        """,
        (int(event_id), int(organization_id)),
    )
    if cursor.fetchone():
        return
    if not table_exists(cursor, "user_roles") or not table_exists(cursor, "roles"):
        return
    marks = ",".join(["%s"] * len(_SUPERVISOR_ROLES))
    cursor.execute(
        f"""
        SELECT DISTINCT u.id
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        WHERE u.organization_id=%s
          AND COALESCE(u.active, 1)=1
          AND UPPER(r.code) IN ({marks})
        """,
        (int(organization_id), *_SUPERVISOR_ROLES),
    )
    for row in cursor.fetchall() or []:
        user_id = row.get("id") if isinstance(row, dict) else row[0]
        if user_id is None:
            continue
        cursor.execute(
            """
            INSERT IGNORE INTO notification_event_audiences
              (event_definition_id, organization_id, target_type, target_id, rule_kind)
            VALUES (%s,%s,'user',%s,'include')
            """,
            (int(event_id), int(organization_id), int(user_id)),
        )
