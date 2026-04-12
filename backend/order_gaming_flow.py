"""
Dryer assignment / gaming flow: lock orders during ACTIVE handling, record dryers + ticket + times.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

_GAMING_COLS: tuple[tuple[str, str], ...] = (
    ("gaming_flow_status", "VARCHAR(32) NULL COMMENT 'NULL|ACTIVE|COMPLETED'"),
    ("gaming_locked_by_user_id", "INT NULL"),
    ("gaming_lock_token", "CHAR(36) NULL"),
    ("gaming_start_time", "DATETIME(6) NULL"),
    ("gaming_end_time", "DATETIME(6) NULL"),
    ("gaming_dryer_count", "INT NULL"),
    ("gaming_dryers_json", "LONGTEXT NULL"),
    ("gaming_ticket_blob_url", "VARCHAR(1024) NULL"),
    ("gaming_ticket_blob_name", "VARCHAR(512) NULL"),
    ("gaming_ticket_file_name", "VARCHAR(255) NULL"),
    ("gaming_ticket_storage", "VARCHAR(32) NULL"),
    ("gaming_ticket_size_bytes", "INT NULL"),
    ("gaming_ticket_image_base64", "LONGTEXT NULL"),
)


def ensure_order_gaming_flow_columns(cursor) -> None:
    if not table_exists(cursor, "orders_staging"):
        return
    changed = False
    for col, ddl in _GAMING_COLS:
        if table_has_column(cursor, "orders_staging", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE orders_staging ADD COLUMN {col} {ddl}")
            changed = True
        except Exception:
            pass
    if changed:
        invalidate_schema_cache()


def _logistics_sql(cap: dict[str, bool]) -> str:
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(
                    logistics_status,
                    CASE
                        WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                        WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                        ELSE 'AT_WASHPRO'
                    END
                ) AS logistics_status
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') AS logistics_status"
    if cap["has_status"]:
        return """
            CASE
                WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                ELSE 'AT_WASHPRO'
            END AS logistics_status
        """
    return "'AT_WASHPRO' AS logistics_status"


def _processing_sql(cap: dict[str, bool]) -> str:
    if cap["has_processing"]:
        if cap["has_status"]:
            return """
                COALESCE(
                    processing_status,
                    CASE WHEN status = 'PROCESSED' THEN 'PROCESSED' ELSE 'PENDING' END
                ) AS processing_status
            """
        return "COALESCE(processing_status, 'PENDING') AS processing_status"
    if cap["has_status"]:
        return "CASE WHEN status = 'PROCESSED' THEN 'PROCESSED' ELSE 'PENDING' END AS processing_status"
    return "'PENDING' AS processing_status"


def load_staging_order_row(cursor, order_id: int, tenant_oid: int, cap: dict[str, bool]) -> dict[str, Any] | None:
    logistics_sql = _logistics_sql(cap)
    processing_sql = _processing_sql(cap)
    gcols = ""
    if table_has_column(cursor, "orders_staging", "gaming_flow_status"):
        gcols = """
            , o.gaming_flow_status
            , o.gaming_locked_by_user_id
            , o.gaming_lock_token
            , o.gaming_dryer_count
            , o.gaming_dryers_json
        """
    org_sel = "o.organization_id" if table_has_column(cursor, "orders_staging", "organization_id") else "NULL AS organization_id"
    status_sel = ", o.status" if table_has_column(cursor, "orders_staging", "status") else ""
    sql = f"""
        SELECT
            o.id,
            {org_sel},
            {logistics_sql},
            {processing_sql}
            {status_sel}
            {gcols}
        FROM orders_staging o
        WHERE o.id = %s
    """
    args: list[Any] = [order_id]
    if table_has_column(cursor, "orders_staging", "organization_id"):
        sql += " AND o.organization_id = %s"
        args.append(tenant_oid)
    sql += " LIMIT 1"
    cursor.execute(sql, tuple(args))
    return cursor.fetchone()


def normalize_dryer_code(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.strip()
    if "://" in s:
        try:
            from urllib.parse import parse_qs, urlparse

            u = urlparse(s)
            qs = parse_qs(u.query)
            for key in ("dryer", "d", "id", "dry"):
                if key in qs and qs[key]:
                    s = str(qs[key][0])
                    break
            else:
                seg = [p for p in u.path.split("/") if p]
                if seg:
                    s = seg[-1]
        except Exception:
            pass
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s[:64] if s else ""


def _parse_dryers_json(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        return [normalize_dryer_code(x) for x in raw if normalize_dryer_code(x)]
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [normalize_dryer_code(x) for x in data if normalize_dryer_code(x)]


def _dryers_in_use_elsewhere(
    cursor, tenant_oid: int, exclude_order_id: int, dryer_code: str
) -> bool:
    if not dryer_code:
        return False
    sql = """
        SELECT id, gaming_dryers_json
        FROM orders_staging
        WHERE gaming_flow_status = 'ACTIVE'
          AND id != %s
    """
    args: list[Any] = [exclude_order_id]
    if table_has_column(cursor, "orders_staging", "organization_id"):
        sql += " AND organization_id = %s"
        args.append(tenant_oid)
    cursor.execute(sql, tuple(args))
    for r in cursor.fetchall() or []:
        codes = _parse_dryers_json(r.get("gaming_dryers_json"))
        if dryer_code in codes:
            return True
    return False


def gaming_select_fragment(cursor) -> str:
    """List API: never expose lock_token to clients (resume uses GET /gaming/session)."""
    if not table_has_column(cursor, "orders_staging", "gaming_flow_status"):
        return """
            , NULL AS gaming_flow_status
            , NULL AS gaming_locked_by_user_id
            , NULL AS gaming_start_time
            , NULL AS gaming_end_time
            , NULL AS gaming_dryer_count
            , NULL AS gaming_dryers_json
        """
    return """
        , o.gaming_flow_status
        , o.gaming_locked_by_user_id
        , o.gaming_start_time
        , o.gaming_end_time
        , o.gaming_dryer_count
        , o.gaming_dryers_json
    """


def get_session_for_user(
    cursor, me: dict[str, Any], tenant_oid: int, order_id: int, cap: dict[str, bool]
) -> tuple[dict[str, Any], int]:
    """Return lock_token only to the user who holds the active lock (resume / client sync)."""
    ensure_order_gaming_flow_columns(cursor)
    uid = int(me.get("user_id") or 0)
    row = load_staging_order_row(cursor, order_id, tenant_oid, cap)
    if not row:
        return {"error": "Order not found"}, 404
    st = (row.get("gaming_flow_status") or "").upper() or None
    out: dict[str, Any] = {
        "gaming_flow_status": st,
        "gaming_dryer_count": row.get("gaming_dryer_count"),
        "gaming_dryers": _parse_dryers_json(row.get("gaming_dryers_json")),
        "gaming_locked_by_user_id": row.get("gaming_locked_by_user_id"),
        "lock_token": None,
    }
    if st == "ACTIVE" and int(row.get("gaming_locked_by_user_id") or 0) == uid:
        tok = (row.get("gaming_lock_token") or "").strip()
        out["lock_token"] = tok or None
    return out, 200


def start_session(
    cursor,
    conn,
    me: dict[str, Any],
    tenant_oid: int,
    order_id: int,
    body: dict[str, Any],
    cap: dict[str, bool],
) -> tuple[dict[str, Any], int]:
    ensure_order_gaming_flow_columns(cursor)
    row = load_staging_order_row(cursor, order_id, tenant_oid, cap)
    if not row:
        return {"error": "Order not found"}, 404
    logistics = (row.get("logistics_status") or "").upper()
    if logistics in ("SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT", "FORCED_CHECKOUT"):
        return {"error": "Order not available for assignment"}, 409
    proc = (row.get("processing_status") or "").upper()
    if proc != "PENDING":
        return {"error": "Order is not pending"}, 409

    uid = int(me.get("user_id") or 0)
    status = (row.get("gaming_flow_status") or "").upper() or None
    if status == "COMPLETED":
        return {"error": "Dryer assignment already completed for this order"}, 409
    if status == "ACTIVE":
        locked_by = int(row.get("gaming_locked_by_user_id") or 0)
        if locked_by and locked_by != uid:
            return {"error": "Order is being handled by another user"}, 409
        token = (row.get("gaming_lock_token") or "").strip()
        if token and locked_by == uid:
            dryers = _parse_dryers_json(row.get("gaming_dryers_json"))
            return {
                "lock_token": token,
                "dryer_count": int(row.get("gaming_dryer_count") or 0),
                "dryers": dryers,
                "resumed": True,
            }, 200

    try:
        n = int(body.get("dryer_count") or 0)
    except Exception:
        n = 0
    if n < 1 or n > 20:
        return {"error": "dryer_count must be between 1 and 20"}, 400

    token = str(uuid.uuid4())
    cursor.execute(
        """
        UPDATE orders_staging
        SET
            gaming_flow_status = 'ACTIVE',
            gaming_locked_by_user_id = %s,
            gaming_lock_token = %s,
            gaming_start_time = NOW(6),
            gaming_end_time = NULL,
            gaming_dryer_count = %s,
            gaming_dryers_json = %s,
            gaming_ticket_blob_url = NULL,
            gaming_ticket_blob_name = NULL,
            gaming_ticket_file_name = NULL,
            gaming_ticket_storage = NULL,
            gaming_ticket_size_bytes = NULL,
            gaming_ticket_image_base64 = NULL
        WHERE id = %s
        """
        + (" AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""),
        (
            uid,
            token,
            n,
            json.dumps([]),
            order_id,
            *( [tenant_oid] if table_has_column(cursor, "orders_staging", "organization_id") else []),
        ),
    )
    conn.commit()
    return {"lock_token": token, "dryer_count": n, "dryers": [], "resumed": False}, 200


def _verify_lock(
    cursor, tenant_oid: int, order_id: int, me: dict, lock_token: str, cap: dict[str, bool]
) -> tuple[dict[str, Any] | None, str | None]:
    uid = int(me.get("user_id") or 0)
    if not lock_token:
        return None, "lock_token required"
    row = load_staging_order_row(cursor, order_id, tenant_oid, cap)
    if not row:
        return None, "Order not found"
    if (row.get("gaming_flow_status") or "").upper() != "ACTIVE":
        return None, "Session is not active"
    if (row.get("gaming_lock_token") or "").strip() != lock_token.strip():
        return None, "Invalid lock token"
    if int(row.get("gaming_locked_by_user_id") or 0) != uid:
        return None, "Not your session"
    return row, None


def scan_dryer(
    cursor,
    conn,
    me: dict[str, Any],
    tenant_oid: int,
    order_id: int,
    body: dict[str, Any],
    cap: dict[str, bool],
) -> tuple[dict[str, Any], int]:
    ensure_order_gaming_flow_columns(cursor)
    lock_token = str(body.get("lock_token") or "").strip()
    row, err = _verify_lock(cursor, tenant_oid, order_id, me, lock_token, cap)
    if err:
        return {"error": err}, 400 if "required" in err else 409

    code = normalize_dryer_code(body.get("dryer_code") or body.get("qr_text") or "")
    if not code:
        return {"error": "dryer_code required"}, 400

    dryers = _parse_dryers_json(row.get("gaming_dryers_json"))
    need = int(row.get("gaming_dryer_count") or 0)
    if len(dryers) >= need:
        return {"error": "All dryers already scanned"}, 409
    if code in dryers:
        return {"error": "Duplicate dryer"}, 409
    if _dryers_in_use_elsewhere(cursor, tenant_oid, order_id, code):
        return {"error": "Dryer is already assigned to another active order"}, 409

    dryers.append(code)
    cursor.execute(
        """
        UPDATE orders_staging
        SET gaming_dryers_json = %s
        WHERE id = %s
        """
        + (" AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""),
        (json.dumps(dryers), order_id, *( [tenant_oid] if table_has_column(cursor, "orders_staging", "organization_id") else [])),
    )
    conn.commit()
    return {"dryers": dryers, "complete": len(dryers) >= need}, 200


def complete_ticket(
    cursor,
    conn,
    me: dict[str, Any],
    tenant_oid: int,
    order_id: int,
    body: dict[str, Any],
    cap: dict[str, bool],
    save_ticket_image_fn,
) -> tuple[dict[str, Any], int]:
    ensure_order_gaming_flow_columns(cursor)
    lock_token = str(body.get("lock_token") or "").strip()
    row, err = _verify_lock(cursor, tenant_oid, order_id, me, lock_token, cap)
    if err:
        return {"error": err}, 400 if "required" in err else 409

    dryers = _parse_dryers_json(row.get("gaming_dryers_json"))
    need = int(row.get("gaming_dryer_count") or 0)
    if len(dryers) < need:
        return {"error": "Scan all dryers before uploading ticket"}, 409

    b64 = body.get("ticket_image_base64")
    fname = str(body.get("ticket_file_name") or "ticket.jpg").strip() or "ticket.jpg"
    if not b64:
        return {"error": "ticket_image_base64 required"}, 400

    saved = save_ticket_image_fn(b64, fname, order_id)
    if not saved:
        return {"error": "Failed to store ticket image"}, 500

    cursor.execute(
        """
        UPDATE orders_staging
        SET
            gaming_flow_status = 'COMPLETED',
            gaming_end_time = NOW(6),
            gaming_ticket_blob_url = %s,
            gaming_ticket_blob_name = %s,
            gaming_ticket_file_name = %s,
            gaming_ticket_storage = %s,
            gaming_ticket_size_bytes = %s,
            gaming_ticket_image_base64 = %s
        WHERE id = %s
        """
        + (" AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""),
        (
            saved.get("ticket_blob_url"),
            saved.get("ticket_blob_name"),
            fname,
            saved.get("ticket_storage"),
            saved.get("ticket_size_bytes"),
            saved.get("ticket_image_base64"),
            order_id,
            *( [tenant_oid] if table_has_column(cursor, "orders_staging", "organization_id") else []),
        ),
    )

    # Folding queue (Orders "Folded") keys off processing_status + order_process_submissions.user_id.
    # Without this, gaming COMPLETED still leaves the row PENDING with no processed_by.
    from backend.app import delete_ticket_blob, ensure_process_submissions_table, prune_old_ticket_images

    ensure_process_submissions_table(cursor)
    prune_old_ticket_images(cursor)

    proc_sets: list[str] = []
    if cap.get("has_processing"):
        proc_sets.append("processing_status = 'PROCESSED'")
    if cap.get("has_status"):
        current = (row.get("status") or "").upper()
        if current not in ("CHECKED_OUT", "SENT_TO_RINSE", "FORCED_CHECKOUT", "FORCE_CHECKOUT"):
            proc_sets.append("status = 'PROCESSED'")
    if proc_sets:
        org_sql = " AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""
        qargs: list[Any] = [order_id]
        if table_has_column(cursor, "orders_staging", "organization_id"):
            qargs.append(tenant_oid)
        cursor.execute(
            f"UPDATE orders_staging SET {', '.join(proc_sets)} WHERE id = %s{org_sql}",
            tuple(qargs),
        )

    cursor.execute(
        "SELECT ticket_blob_name, ticket_blob_url FROM order_process_submissions WHERE order_id = %s LIMIT 1",
        (order_id,),
    )
    prev_ops = cursor.fetchone() or {}
    cursor.execute(
        """
        INSERT INTO order_process_submissions
        (
            order_id,
            user_id,
            username,
            ticket_image_base64,
            ticket_file_name,
            ticket_blob_url,
            ticket_blob_name,
            ticket_storage,
            ticket_size_bytes,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            user_id = VALUES(user_id),
            username = VALUES(username),
            ticket_image_base64 = VALUES(ticket_image_base64),
            ticket_file_name = VALUES(ticket_file_name),
            ticket_blob_url = VALUES(ticket_blob_url),
            ticket_blob_name = VALUES(ticket_blob_name),
            ticket_storage = VALUES(ticket_storage),
            ticket_size_bytes = VALUES(ticket_size_bytes),
            updated_at = NOW()
        """,
        (
            order_id,
            me.get("user_id"),
            me.get("username"),
            saved.get("ticket_image_base64"),
            fname,
            saved.get("ticket_blob_url"),
            saved.get("ticket_blob_name"),
            saved.get("ticket_storage"),
            saved.get("ticket_size_bytes"),
        ),
    )
    if prev_ops.get("ticket_blob_name") and prev_ops.get("ticket_blob_name") != saved.get("ticket_blob_name"):
        delete_ticket_blob(prev_ops.get("ticket_blob_name"), prev_ops.get("ticket_blob_url"))

    conn.commit()
    return {"status": "COMPLETED", "gaming_end_time": True, "processing": "PROCESSED"}, 200


def cancel_session(
    cursor,
    conn,
    me: dict[str, Any],
    tenant_oid: int,
    order_id: int,
    body: dict[str, Any],
    cap: dict[str, bool],
) -> tuple[dict[str, Any], int]:
    ensure_order_gaming_flow_columns(cursor)
    lock_token = str(body.get("lock_token") or "").strip()
    row, err = _verify_lock(cursor, tenant_oid, order_id, me, lock_token, cap)
    if err:
        return {"error": err}, 400 if "required" in err else 409

    cursor.execute(
        """
        UPDATE orders_staging
        SET
            gaming_flow_status = NULL,
            gaming_locked_by_user_id = NULL,
            gaming_lock_token = NULL,
            gaming_start_time = NULL,
            gaming_end_time = NULL,
            gaming_dryer_count = NULL,
            gaming_dryers_json = NULL,
            gaming_ticket_blob_url = NULL,
            gaming_ticket_blob_name = NULL,
            gaming_ticket_file_name = NULL,
            gaming_ticket_storage = NULL,
            gaming_ticket_size_bytes = NULL,
            gaming_ticket_image_base64 = NULL
        WHERE id = %s
        """
        + (" AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""),
        (order_id, *( [tenant_oid] if table_has_column(cursor, "orders_staging", "organization_id") else [])),
    )
    conn.commit()
    return {"status": "cancelled"}, 200


def order_has_active_gaming(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return (row.get("gaming_flow_status") or "").upper() == "ACTIVE"
