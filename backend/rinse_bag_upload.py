"""
Bag-ID–controlled Rinse portal upload and confirm helpers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED, COMPLETION_INCOMPLETE, normalize_bag_id
from backend.rinse_bag_registry import (
    ensure_rinse_bag_registry_table,
    get_registry_row,
    is_bag_already_completed,
)


def _ensure_registry_v2_columns(cursor) -> None:
    ensure_rinse_bag_registry_table(cursor)
    for col, ddl in (
        ("rush_type", "VARCHAR(20) NULL"),
        ("last_seen_upload_batch_id", "INT NULL"),
        ("last_seen_at", "DATETIME NULL"),
    ):
        cursor.execute(
            """
            SELECT COUNT(*) AS c FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'rinse_bag_registry'
              AND COLUMN_NAME = %s
            """,
            (col,),
        )
        row = cursor.fetchone()
        n = int(row["c"] if isinstance(row, dict) else row[0])
        if n == 0:
            cursor.execute(f"ALTER TABLE rinse_bag_registry ADD COLUMN {col} {ddl}")


def upsert_registry_from_portal_row(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    *,
    ticket_id: str,
    name_clean: str,
    weight_num: Any,
    service_type: str,
    date_clean: date,
    rush_type: str,
    is_completed: bool,
) -> None:
    """Registry snapshot on portal upload."""
    _ensure_registry_v2_columns(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(ticket_id)
    if not bid:
        return

    reg = get_registry_row(cursor, org, bid)
    batch_id = int(upload_batch_id)

    if is_completed or (reg and str(reg.get("completion_status") or "").upper() == COMPLETION_COMPLETED):
        cursor.execute(
            """
            INSERT INTO rinse_bag_registry (organization_id, bag_id, completion_status, last_seen_upload_batch_id, last_seen_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                last_seen_upload_batch_id = VALUES(last_seen_upload_batch_id),
                last_seen_at = NOW(),
                updated_at = NOW()
            """,
            (org, bid, COMPLETION_COMPLETED, batch_id),
        )
        return

    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status,
            name_clean, weight_num, service_type, date_clean, rush_type,
            last_upload_batch_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name_clean = VALUES(name_clean),
            weight_num = VALUES(weight_num),
            service_type = VALUES(service_type),
            date_clean = VALUES(date_clean),
            rush_type = VALUES(rush_type),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_INCOMPLETE,
            name_clean,
            weight_num,
            service_type,
            date_clean,
            rush_type,
            batch_id,
        ),
    )


def fetch_registry_map_for_bag_ids(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, dict]:
    _ensure_registry_v2_columns(cursor)
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not normalized:
        return {}
    placeholders = ", ".join(["%s"] * len(normalized))
    cursor.execute(
        f"""
        SELECT bag_id, completion_status, completion_reason, completed_at,
               trigger_kind, first_clean_scan_at, trigger_scan_at
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id IN ({placeholders})
        """,
        [int(organization_id), *normalized],
    )
    out: dict[str, dict] = {}
    for row in cursor.fetchall() or []:
        r = row if isinstance(row, dict) else {}
        if not isinstance(row, dict):
            continue
        out[str(row["bag_id"])] = row
    return out


def find_active_staging_by_ticket_id(
    cursor,
    organization_id: int,
    ticket_id: str,
    active_where_sql: str,
    *,
    has_staging_org: bool,
    has_ticket_id_col: bool,
) -> dict | None:
    """Latest active staging row for this Bag ID."""
    if not has_ticket_id_col:
        return None
    bid = normalize_bag_id(ticket_id)
    if not bid:
        return None
    sql = f"""
        SELECT id, date_clean, name_clean, weight_num, service_type, rush_type, batch_date, ticket_id
        FROM orders_staging
        WHERE ticket_id = %s AND ({active_where_sql})
    """
    args: list[Any] = [bid]
    if has_staging_org:
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    sql += " ORDER BY id DESC LIMIT 1"
    cursor.execute(sql, tuple(args))
    return cursor.fetchone()


def update_staging_from_upload_row(
    cursor,
    staging_id: int,
    row: dict,
    batch_date: date,
    cap: dict,
    *,
    organization_id: int | None = None,
    has_staging_org: bool = False,
) -> None:
    set_parts = [
        "date_clean = %s",
        "name_clean = %s",
        "weight_num = %s",
        "service_type = %s",
        "rush_type = %s",
        "batch_date = %s",
    ]
    args: list[Any] = [
        row["date_clean"],
        row["name_clean"],
        row["weight_num"],
        row["service_type"],
        row["rush_type"],
        batch_date,
    ]
    if cap.get("has_logistics"):
        set_parts.append("logistics_status = %s")
        args.append("AT_WASHPRO")
    if cap.get("has_processing"):
        set_parts.append("processing_status = %s")
        args.append("PENDING")
    if cap.get("has_status"):
        set_parts.append("status = %s")
        args.append("PENDING")

    tid = normalize_bag_id(row.get("ticket_id"))
    if cap.get("has_ticket_id") and tid:
        set_parts.append("ticket_id = %s")
        args.append(tid[:120])

    args.append(int(staging_id))
    sql = f"UPDATE orders_staging SET {', '.join(set_parts)} WHERE id = %s"
    if has_staging_org and organization_id is not None:
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    cursor.execute(sql, tuple(args))


def enrich_upload_batch_rows_with_registry(
    cursor, organization_id: int, rows: list[dict]
) -> list[dict]:
    bag_ids = []
    for r in rows:
        tid = normalize_bag_id(r.get("ticket_id"))
        if tid:
            bag_ids.append(tid)
    reg_map = fetch_registry_map_for_bag_ids(cursor, organization_id, bag_ids)
    out = []
    for r in rows:
        row = dict(r)
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid:
            row["registry_status"] = None
            row["registry_not_found"] = False
            row["completion_reason"] = None
            row["completed_at"] = None
            row["trigger_kind"] = None
        elif tid in reg_map:
            reg = reg_map[tid]
            row["registry_status"] = reg.get("completion_status")
            row["registry_not_found"] = False
            row["completion_reason"] = reg.get("completion_reason")
            row["completed_at"] = reg.get("completed_at")
            if isinstance(row["completed_at"], datetime):
                row["completed_at"] = row["completed_at"].isoformat()
            row["trigger_kind"] = reg.get("trigger_kind")
        else:
            row["registry_status"] = None
            row["registry_not_found"] = True
            row["completion_reason"] = None
            row["completed_at"] = None
            row["trigger_kind"] = None
        out.append(row)
    return out


def get_bag_admin_detail(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    active_where_sql: str,
    has_staging_org: bool,
    has_ticket_id_col: bool,
    upload_batch_row_pk: str = "id",
) -> dict | None:
    from backend.rinse_bag_registry import get_registry_row, list_scan_events_for_bag

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    reg = get_registry_row(cursor, organization_id, bid)
    if not reg:
        return None

    detail: dict[str, Any] = {
        "registry": reg,
        "scan_events": list_scan_events_for_bag(cursor, organization_id, bid),
        "latest_upload_batch_row": None,
        "staging_order": find_active_staging_by_ticket_id(
            cursor,
            organization_id,
            bid,
            active_where_sql,
            has_staging_org=has_staging_org,
            has_ticket_id_col=has_ticket_id_col,
        ),
    }

    if reg.get("last_upload_batch_id"):
        cursor.execute(
            f"""
            SELECT * FROM upload_batch_rows
            WHERE upload_batch_id = %s AND ticket_id = %s
            ORDER BY {upload_batch_row_pk} DESC
            LIMIT 1
            """,
            (int(reg["last_upload_batch_id"]), bid),
        )
        detail["latest_upload_batch_row"] = cursor.fetchone()

    return detail


def recompute_bag_completion_with_audit(
    cursor, organization_id: int, bag_id: str
) -> dict[str, Any]:
    from backend.rinse_bag_registry import apply_completion_to_registry

    bid = normalize_bag_id(bag_id)
    before_reg = get_registry_row(cursor, organization_id, bid)
    before = {
        "completion_status": (before_reg or {}).get("completion_status"),
        "completion_reason": (before_reg or {}).get("completion_reason"),
        "completed_at": (before_reg or {}).get("completed_at"),
    }
    after_fields = apply_completion_to_registry(cursor, organization_id, bid)
    return {"bag_id": bid, "before": before, "after": after_fields}
