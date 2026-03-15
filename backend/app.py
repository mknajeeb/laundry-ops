import os
import math
import uuid
import base64
import pandas as pd
from datetime import datetime, date, timedelta

from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash
from urllib.parse import urlparse

try:
    from azure.storage.blob import (
        BlobServiceClient,
        BlobSasPermissions,
        ContentSettings,
        generate_blob_sas,
    )
except Exception:
    BlobServiceClient = None
    BlobSasPermissions = None
    ContentSettings = None
    generate_blob_sas = None

from etl.transform_orders import transform_orders


# ---------------------------------------------------
# Flask App Setup
# ---------------------------------------------------

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------
# Database Connection
# ---------------------------------------------------

def get_db():
    return mysql.connector.connect(
        host="mkncentralussrv1.mysql.database.azure.com",
        user="kamsee",
        password="Allah786$",
        database="laundryapp",
        port=3306
    )


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def parse_date_value(value):

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    value = str(value).strip()

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        pass

    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").date()
    except Exception:
        pass

    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        pass

    raise ValueError(f"Could not parse date: {value}")


def normalize_weight(value):

    if pd.isna(value):
        return None

    try:
        return round(float(value), 2)
    except Exception:
        return None


def build_fingerprint(name_clean, weight_num, service_type):

    name_part = (name_clean or "").strip().upper()
    weight_part = "" if weight_num is None else f"{round(float(weight_num), 2):.2f}"
    service_part = (service_type or "").strip().upper()

    return f"{name_part}|{weight_part}|{service_part}"


def normalize_name(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().split())


def normalize_measure_by_service(weight_num, service_type):
    service = (service_type or "").strip().upper()
    if weight_num is None:
        # For HD, blank and 0 are operationally treated the same.
        return "0" if service == "HD" else ""

    try:
        n = float(weight_num)
    except Exception:
        return ""

    if service == "HD":
        return str(int(round(n)))

    return f"{round(n, 2):.2f}"


def normalize_date_key(date_value):
    if date_value is None or date_value == "":
        return ""
    if isinstance(date_value, datetime):
        return date_value.date().isoformat()
    if isinstance(date_value, date):
        return date_value.isoformat()
    try:
        return parse_date_value(date_value).isoformat()
    except Exception:
        return str(date_value).strip()


def build_identity_key(name_clean, weight_num, service_type, date_clean):
    return "|".join([
        normalize_name(name_clean),
        normalize_measure_by_service(weight_num, service_type),
        (service_type or "").strip().upper(),
        normalize_date_key(date_clean)
    ])


def haversine_meters(lat1, lon1, lat2, lon2):
    radius_m = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_m * c


def fetch_active_geofence(cursor):
    cursor.execute("""
        SELECT
            id,
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_at
        FROM geofence_settings
        WHERE active = TRUE
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
    """)

    geofence = cursor.fetchone()

    if geofence:
        return geofence

    cursor.execute("""
        SELECT
            id,
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_at
        FROM geofence_settings
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
    """)

    return cursor.fetchone()


def get_upload_conflicts_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_conflicts LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_conflicts LIKE 'conflict_id'")
    has_conflict_id = cursor.fetchone()
    if has_conflict_id:
        return "conflict_id"

    raise ValueError("upload_conflicts table must include 'id' or 'conflict_id' primary key")


def get_upload_batches_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'batch_id'")
    has_batch_id = cursor.fetchone()
    if has_batch_id:
        return "batch_id"

    raise ValueError("upload_batches table must include 'id' or 'batch_id' primary key")


def get_upload_batch_rows_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_batch_rows LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_batch_rows LIKE 'row_id'")
    has_row_id = cursor.fetchone()
    if has_row_id:
        return "row_id"

    raise ValueError("upload_batch_rows table must include 'id' or 'row_id' primary key")


def table_has_column(cursor, table_name, col_name):
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (col_name,))
    return cursor.fetchone() is not None


def table_exists(cursor, table_name):
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def delete_identity_rows(cursor, table_name, rows, name_col, weight_col, service_col, date_col):
    if not rows:
        return 0

    deleted = 0
    for row in rows:
        cursor.execute(
            f"""
                DELETE FROM {table_name}
                WHERE UPPER(TRIM({name_col})) = UPPER(TRIM(%s))
                  AND {service_col} = %s
                  AND (({weight_col} IS NULL AND %s IS NULL) OR {weight_col} = %s)
                  AND {date_col} = %s
            """,
            (
                row.get("name_clean"),
                row.get("service_type"),
                row.get("weight_num"),
                row.get("weight_num"),
                row.get("date_clean"),
            ),
        )
        deleted += cursor.rowcount or 0

    return deleted


def get_bearer_token():
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def current_user_from_token(cursor):
    token = get_bearer_token()
    if not token:
        return None

    cursor.execute("""
        SELECT
            s.id AS session_id,
            s.user_id,
            s.token,
            s.expires_at,
            s.revoked,
            u.username,
            u.display_name,
            u.active
        FROM auth_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = %s
        LIMIT 1
    """, (token,))
    row = cursor.fetchone()
    if not row:
        return None
    if row.get("revoked"):
        return None
    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.utcnow():
        return None
    if not row.get("active", False):
        return None
    return row


def fetch_user_roles(cursor, user_id):
    cursor.execute("""
        SELECT r.code
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
    """, (user_id,))
    return [str(r["code"]).upper() for r in cursor.fetchall()]


def require_admin(cursor):
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    roles = fetch_user_roles(cursor, me["user_id"])
    if "ADMIN" not in roles:
        return None, jsonify({"error": "Forbidden"}), 403
    me["roles"] = roles
    return me, None, None


def require_user(cursor):
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    me["roles"] = fetch_user_roles(cursor, me["user_id"])
    return me, None, None


def ensure_process_submissions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_process_submissions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL UNIQUE,
            user_id INT NULL,
            username VARCHAR(100) NULL,
            ticket_image_base64 LONGTEXT NULL,
            ticket_file_name VARCHAR(255) NULL,
            ticket_blob_url VARCHAR(1024) NULL,
            ticket_blob_name VARCHAR(512) NULL,
            ticket_storage VARCHAR(20) NULL,
            ticket_size_bytes INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL
        )
    """)
    if not table_has_column(cursor, "order_process_submissions", "ticket_blob_url"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_blob_url VARCHAR(1024) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_blob_name"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_blob_name VARCHAR(512) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_storage"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_storage VARCHAR(20) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_size_bytes"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_size_bytes INT NULL")


def ensure_order_processing_exceptions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_processing_exceptions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL UNIQUE,
            user_id INT NULL,
            username VARCHAR(100) NULL,
            service_type VARCHAR(10) NULL,
            original_measure DECIMAL(8,2) NULL,
            submitted_measure DECIMAL(8,2) NULL,
            difference_measure DECIMAL(8,2) NULL,
            date_clean DATE NULL,
            batch_date DATE NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL
        )
    """)


def ticket_retention_days():
    try:
        days = int(os.getenv("ORDER_TICKET_RETENTION_DAYS", "60"))
    except Exception:
        days = 60
    return max(1, min(days, 365))


def ticket_storage_mode():
    mode = str(os.getenv("ORDER_TICKET_STORAGE_MODE", "") or "").strip().lower()
    if mode in {"blob", "db"}:
        return mode
    return "blob" if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else "db"


def _blob_container_name():
    return str(os.getenv("ORDER_TICKET_CONTAINER", "order-tickets") or "order-tickets").strip()


def _blob_service_client():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str or BlobServiceClient is None:
        return None
    return BlobServiceClient.from_connection_string(conn_str)


def _ensure_blob_container():
    client = _blob_service_client()
    if client is None:
        return None
    container = _blob_container_name()
    cc = client.get_container_client(container)
    try:
        cc.create_container()
    except Exception:
        pass
    return cc


def _infer_content_type(file_name):
    name = str(file_name or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _blob_name_from_url(url):
    try:
        parsed = urlparse(url or "")
        path = parsed.path or ""
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return None
        # /container/blob/path -> remove container segment
        return "/".join(parts[1:])
    except Exception:
        return None


def save_ticket_image(ticket_image_base64, ticket_file_name, order_id):
    if not ticket_image_base64:
        return None

    data = base64.b64decode(ticket_image_base64)
    size = len(data)

    if ticket_storage_mode() == "blob":
        cc = _ensure_blob_container()
        if cc is not None:
            now = datetime.utcnow()
            blob_name = f"orders/{now.strftime('%Y/%m/%d')}/{order_id}_{uuid.uuid4().hex}_{ticket_file_name or 'ticket.jpg'}"
            bc = cc.get_blob_client(blob_name)
            kwargs = {}
            if ContentSettings is not None:
                kwargs["content_settings"] = ContentSettings(content_type=_infer_content_type(ticket_file_name))
            bc.upload_blob(data, overwrite=True, **kwargs)
            return {
                "ticket_storage": "blob",
                "ticket_blob_url": bc.url,
                "ticket_blob_name": blob_name,
                "ticket_image_base64": None,
                "ticket_size_bytes": size,
            }

    return {
        "ticket_storage": "db",
        "ticket_blob_url": None,
        "ticket_blob_name": None,
        "ticket_image_base64": ticket_image_base64,
        "ticket_size_bytes": size,
    }


def build_ticket_read_url(blob_name, blob_url):
    if not blob_name:
        return blob_url
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str or generate_blob_sas is None or BlobSasPermissions is None:
        return blob_url
    try:
        client = _blob_service_client()
        if client is None:
            return blob_url
        account_name = client.account_name
        cred = client.credential
        account_key = getattr(cred, "account_key", None)
        if not account_key:
            return blob_url
        token = generate_blob_sas(
            account_name=account_name,
            container_name=_blob_container_name(),
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=30),
        )
        if not token:
            return blob_url
        return f"https://{account_name}.blob.core.windows.net/{_blob_container_name()}/{blob_name}?{token}"
    except Exception:
        return blob_url


def delete_ticket_blob(blob_name=None, blob_url=None):
    cc = _ensure_blob_container()
    if cc is None:
        return
    name = blob_name or _blob_name_from_url(blob_url)
    if not name:
        return
    try:
        cc.get_blob_client(name).delete_blob(delete_snapshots="include")
    except Exception:
        pass


def prune_old_ticket_images(cursor):
    days = ticket_retention_days()
    cursor.execute("""
        SELECT id, ticket_blob_name, ticket_blob_url
        FROM order_process_submissions
        WHERE
            (ticket_image_base64 IS NOT NULL OR ticket_blob_url IS NOT NULL)
            AND COALESCE(updated_at, created_at) < (NOW() - INTERVAL %s DAY)
    """, (days,))
    old_rows = cursor.fetchall() or []
    for r in old_rows:
        delete_ticket_blob(r.get("ticket_blob_name"), r.get("ticket_blob_url"))

    cursor.execute("""
        UPDATE order_process_submissions
        SET
            ticket_image_base64 = NULL,
            ticket_file_name = NULL,
            ticket_blob_url = NULL,
            ticket_blob_name = NULL,
            ticket_storage = NULL,
            ticket_size_bytes = NULL,
            updated_at = NOW()
        WHERE
            (ticket_image_base64 IS NOT NULL OR ticket_blob_url IS NOT NULL)
            AND COALESCE(updated_at, created_at) < (NOW() - INTERVAL %s DAY)
    """, (days,))


def upload_batches_time_col(cursor):
    if table_has_column(cursor, "upload_batches", "created_at"):
        return "created_at"
    if table_has_column(cursor, "upload_batches", "uploaded_at"):
        return "uploaded_at"
    return None


def orders_status_capabilities(cursor):
    return {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }


def ensure_ticket_id_columns(cursor):
    if table_exists(cursor, "orders_staging") and not table_has_column(cursor, "orders_staging", "ticket_id"):
        cursor.execute("ALTER TABLE orders_staging ADD COLUMN ticket_id VARCHAR(120) NULL")
    if table_exists(cursor, "orders_final") and not table_has_column(cursor, "orders_final", "ticket_id"):
        cursor.execute("ALTER TABLE orders_final ADD COLUMN ticket_id VARCHAR(120) NULL")


def orders_logistics_select_sql(cap):
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


def orders_processing_select_sql(cap):
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


def where_active_at_washpro_sql(cap):
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if cap["has_status"]:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def where_not_sent_or_forced_sql(cap):
    return where_active_at_washpro_sql(cap)


# ---------------------------------------------------
# Get Active Orders
# ---------------------------------------------------

@app.route("/orders", methods=["GET"])
def get_orders():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        active_where = where_active_at_washpro_sql(cap)
        include_all = as_bool(request.args.get("include_all"), default=False)
        where_clause = "1 = 1" if include_all else active_where
        has_submissions = table_exists(cursor, "order_process_submissions")
        submission_select = ""
        submission_join = ""
        if has_submissions:
            has_ops_order_id = table_has_column(cursor, "order_process_submissions", "order_id")
            has_ops_user_id = table_has_column(cursor, "order_process_submissions", "user_id")
            has_ops_username = table_has_column(cursor, "order_process_submissions", "username")
            has_ops_updated_at = table_has_column(cursor, "order_process_submissions", "updated_at")
            has_ops_ticket_blob_url = table_has_column(cursor, "order_process_submissions", "ticket_blob_url")
            has_ops_ticket_b64 = table_has_column(cursor, "order_process_submissions", "ticket_image_base64")
            has_ops_ticket_file_name = table_has_column(cursor, "order_process_submissions", "ticket_file_name")
            has_ops_id = table_has_column(cursor, "order_process_submissions", "id")

            has_ticket_expr_parts = []
            if has_ops_ticket_blob_url:
                has_ticket_expr_parts.append("(ops.ticket_blob_url IS NOT NULL AND ops.ticket_blob_url <> '')")
            if has_ops_ticket_b64:
                has_ticket_expr_parts.append("(ops.ticket_image_base64 IS NOT NULL AND ops.ticket_image_base64 <> '')")
            has_ticket_expr = " OR ".join(has_ticket_expr_parts) if has_ticket_expr_parts else "FALSE"

            submission_select = f"""
                , {"ops.user_id" if has_ops_user_id else "NULL"} AS processed_by_user_id
                , {"ops.username" if has_ops_username else "NULL"} AS processed_by_username
                , {"ops.updated_at" if has_ops_updated_at else "NULL"} AS processed_at
                , CASE
                    WHEN ({has_ticket_expr})
                    THEN 1 ELSE 0
                  END AS has_ticket_image
                , {"ops.ticket_file_name" if has_ops_ticket_file_name else "NULL"} AS ticket_file_name
                , {"ops.id" if has_ops_id else "NULL"} AS ticket_id
            """
            submission_join = "LEFT JOIN order_process_submissions ops ON ops.order_id = o.id" if has_ops_order_id else ""

        cursor.execute(f"""

            SELECT
                o.id,
                o.date_clean,
                o.name_clean,
                o.weight_num,
                o.service_type,
                o.batch_date,
                {"o.ticket_id" if cap["has_ticket_id"] else "NULL"} AS ticket_id,

                CASE
                    WHEN o.date_clean < CURDATE() THEN 'RUSH'
                    ELSE 'NON-RUSH'
                END AS rush_type,

                {logistics_sql},
                {processing_sql},
                o.status,
                o.created_at
                {submission_select}

            FROM orders_staging o
            {submission_join}
            WHERE {where_clause}

            ORDER BY o.date_clean ASC, o.id ASC

        """)

        orders = cursor.fetchall()

        return jsonify(orders)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Checkout Single Order
# ---------------------------------------------------

@app.route("/checkout", methods=["POST"])
def checkout_order():

    data = request.json or {}
    order_id = data.get("order_id")
    employee = (data.get("employee") or "").strip() or "Unknown"

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)

        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                {logistics_sql},
                status
            FROM orders_staging
            WHERE id = %s
        """, (order_id,))

        order = cursor.fetchone()

        if not order:
            return jsonify({"error": "Order not found"}), 404

        if (order.get("logistics_status") or "").upper() in ["SENT_TO_RINSE", "CHECKED_OUT"]:
            return jsonify({"error": "Order already checked out"}), 409

        cursor.execute("""
            INSERT INTO checkout_log
            (
                order_id,
                name,
                weight,
                service,
                rush_date,
                employee
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            order["id"],
            order["name_clean"],
            order["weight_num"],
            order["service_type"],
            order["date_clean"],
            employee
        ))

        set_parts = []
        if cap["has_logistics"]:
            set_parts.append("logistics_status = 'SENT_TO_RINSE'")
        if cap["has_status"]:
            set_parts.append("status = 'CHECKED_OUT'")
        if not set_parts:
            set_parts.append("status = 'CHECKED_OUT'")

        cursor.execute(f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """, (order_id,))

        conn.commit()
        return jsonify({"status": "checked_out", "order_id": order_id})

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Checkout Bulk Orders
# ---------------------------------------------------

@app.route("/checkout_bulk", methods=["POST"])
def checkout_bulk():

    data = request.json or {}
    order_ids = data.get("order_ids") or []
    employee = (data.get("employee") or "").strip() or "Unknown"

    if not isinstance(order_ids, list) or not order_ids:
        return jsonify({"error": "order_ids must be a non-empty array"}), 400

    # Ensure stable ordering and avoid duplicates
    order_ids = list(dict.fromkeys(order_ids))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)

        format_strings = ",".join(["%s"] * len(order_ids))
        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                {logistics_sql},
                status
            FROM orders_staging
            WHERE id IN ({format_strings})
        """, tuple(order_ids))

        rows = cursor.fetchall()
        rows_by_id = {row["id"]: row for row in rows}

        not_found = []
        already_checked_out = []
        checkout_candidates = []

        for oid in order_ids:
            row = rows_by_id.get(oid)

            if not row:
                not_found.append(oid)
                continue

            if (row.get("logistics_status") or "").upper() in ["SENT_TO_RINSE", "CHECKED_OUT"]:
                already_checked_out.append(oid)
                continue

            checkout_candidates.append(row)

        for order in checkout_candidates:
            cursor.execute("""
                INSERT INTO checkout_log
                (
                    order_id,
                    name,
                    weight,
                    service,
                    rush_date,
                    employee
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                order["id"],
                order["name_clean"],
                order["weight_num"],
                order["service_type"],
                order["date_clean"],
                employee
            ))

        if checkout_candidates:
            checkout_ids = [row["id"] for row in checkout_candidates]
            update_strings = ",".join(["%s"] * len(checkout_ids))
            set_parts = []
            if cap["has_logistics"]:
                set_parts.append("logistics_status = 'SENT_TO_RINSE'")
            if cap["has_status"]:
                set_parts.append("status = 'CHECKED_OUT'")
            if not set_parts:
                set_parts.append("status = 'CHECKED_OUT'")

            cursor.execute(f"""
                UPDATE orders_staging
                SET {", ".join(set_parts)}
                WHERE id IN ({update_strings})
            """, tuple(checkout_ids))

        conn.commit()

        return jsonify({
            "status": "bulk_checkout_complete",
            "requested": len(order_ids),
            "checked_out": len(checkout_candidates),
            "not_found": not_found,
            "already_checked_out": already_checked_out
        })

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Get Checkout Log
# ---------------------------------------------------

@app.route("/checkout_log", methods=["GET"])
def get_checkout_log():

    checkout_date = (request.args.get("date") or "").strip()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        if checkout_date:
            cursor.execute("""
                SELECT
                    id,
                    order_id,
                    name,
                    weight,
                    service,
                    rush_date,
                    checkout_time,
                    employee
                FROM checkout_log
                WHERE DATE(checkout_time) = %s
                ORDER BY checkout_time DESC, id DESC
            """, (checkout_date,))
        else:
            cursor.execute("""
                SELECT
                    id,
                    order_id,
                    name,
                    weight,
                    service,
                    rush_date,
                    checkout_time,
                    employee
                FROM checkout_log
                WHERE DATE(checkout_time) = CURDATE()
                ORDER BY checkout_time DESC, id DESC
            """)

        return jsonify(cursor.fetchall())

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Undo Checkout (Mistake Recovery)
# ---------------------------------------------------

@app.route("/checkout_undo", methods=["POST"])
def checkout_undo():

    data = request.json or {}
    order_id = data.get("order_id")

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cap = orders_status_capabilities(cursor)
        cursor.execute("""
            SELECT id, status
            FROM orders_staging
            WHERE id = %s
        """, (order_id,))
        order_row = cursor.fetchone()

        if not order_row:
            return jsonify({"error": "Order not found"}), 404

        cursor.execute("""
            SELECT id
            FROM checkout_log
            WHERE order_id = %s
            ORDER BY checkout_time DESC, id DESC
            LIMIT 1
        """, (order_id,))
        log_row = cursor.fetchone()

        if log_row:
            cursor.execute(
                "DELETE FROM checkout_log WHERE id = %s",
                (log_row["id"],)
            )

        set_parts = []
        if cap["has_logistics"]:
            set_parts.append("logistics_status = 'AT_WASHPRO'")
        if cap["has_status"]:
            set_parts.append("status = 'PROCESSED'")
        if not set_parts:
            set_parts.append("status = 'PROCESSED'")

        cursor.execute(f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """, (order_id,))

        conn.commit()
        return jsonify({"status": "checkout_undone", "order_id": order_id})

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Get Final Orders
# ---------------------------------------------------

@app.route("/orders/final", methods=["GET"])
def get_final_orders():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""

            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                cleaned_by,
                cleaned_at,
                created_at

            FROM orders_final

            ORDER BY cleaned_at DESC, id DESC

        """)

        rows = cursor.fetchall()

        return jsonify(rows)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Update Order
# ---------------------------------------------------

@app.route("/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        _, err_resp, err_code = require_admin(cursor)
        if err_resp:
            return err_resp, err_code
        ensure_ticket_id_columns(cursor)
        has_ticket_id = table_has_column(cursor, "orders_staging", "ticket_id")

        cursor.execute("""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type
                {ticket_select}
            FROM orders_staging
            WHERE id = %s
        """.format(ticket_select=", ticket_id" if has_ticket_id else ""), (order_id,))

        existing = cursor.fetchone()

        if not existing:
            return jsonify({"error": "Order not found"}), 404

        date_clean = (
            parse_date_value(data.get("date_clean"))
            if data.get("date_clean") not in [None, ""]
            else existing["date_clean"]
        )

        name_clean = (
            data.get("name_clean")
            if data.get("name_clean") not in [None, ""]
            else existing["name_clean"]
        )

        weight_num = (
            normalize_weight(data.get("weight_num"))
            if data.get("weight_num") not in [None, ""]
            else existing["weight_num"]
        )

        service_type = (
            data.get("service_type")
            if data.get("service_type") not in [None, ""]
            else existing["service_type"]
        )
        ticket_id = (
            str(data.get("ticket_id")).strip()
            if has_ticket_id and data.get("ticket_id") not in [None, ""]
            else (existing.get("ticket_id") if has_ticket_id else None)
        )
        if has_ticket_id and ticket_id == "":
            ticket_id = None

        if has_ticket_id:
            cursor.execute("""
                UPDATE orders_staging
                SET
                    date_clean = %s,
                    name_clean = %s,
                    weight_num = %s,
                    service_type = %s,
                    ticket_id = %s
                WHERE id = %s
            """, (
                date_clean,
                name_clean,
                weight_num,
                service_type,
                ticket_id,
                order_id
            ))
        else:
            cursor.execute("""
                UPDATE orders_staging
                SET
                    date_clean = %s,
                    name_clean = %s,
                    weight_num = %s,
                    service_type = %s
                WHERE id = %s
            """, (
                date_clean,
                name_clean,
                weight_num,
                service_type,
                order_id
            ))

        conn.commit()

        return jsonify({"status": "updated"})

    except Exception as e:

        conn.rollback()

        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Delete Order
# ---------------------------------------------------

@app.route("/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):

    conn = get_db()
    cursor = conn.cursor()

    try:
        _, err_resp, err_code = require_admin(cursor)
        if err_resp:
            return err_resp, err_code

        cursor.execute(
            "DELETE FROM orders_staging WHERE id = %s",
            (order_id,)
        )

        conn.commit()

        return jsonify({"status": "deleted"})

    except Exception as e:

        conn.rollback()

        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Self Processing + Ticket Upload
# ---------------------------------------------------

@app.route("/orders/<int:order_id>/submit_processed", methods=["POST"])
def submit_processed_order(order_id):

    data = request.json or {}
    ticket_image_base64 = data.get("ticket_image_base64")
    ticket_file_name = data.get("ticket_file_name")
    ticket_id = str(data.get("ticket_id") or "").strip()
    weight_num = data.get("weight_num")
    parsed_weight = normalize_weight(weight_num) if weight_num not in [None, ""] else None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_process_submissions_table(cursor)
        ensure_order_processing_exceptions_table(cursor)
        ensure_ticket_id_columns(cursor)
        prune_old_ticket_images(cursor)
        cap = orders_status_capabilities(cursor)

        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                batch_date,
                service_type,
                weight_num,
                {logistics_sql},
                {processing_sql},
                status
            FROM orders_staging
            WHERE id = %s
            LIMIT 1
        """, (order_id,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Order not found"}), 404

        logistics_status = (row.get("logistics_status") or "").upper()
        if logistics_status in ["SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"]:
            return jsonify({"error": "Order already sent/checked out"}), 409

        service_type = (row.get("service_type") or "").strip().upper()
        if parsed_weight is not None and service_type == "HD":
            if abs(parsed_weight - round(parsed_weight)) > 1e-9:
                return jsonify({"error": "HD count must be a whole number"}), 400

        set_parts = []
        if cap["has_processing"]:
            set_parts.append("processing_status = 'PROCESSED'")
        if cap["has_status"]:
            current = (row.get("status") or "").upper()
            if current not in ["CHECKED_OUT", "SENT_TO_RINSE", "FORCED_CHECKOUT", "FORCE_CHECKOUT"]:
                set_parts.append("status = 'PROCESSED'")
        if not set_parts:
            set_parts.append("status = 'PROCESSED'")

        if parsed_weight is not None:
            set_parts.append("weight_num = %s")
        if cap.get("has_ticket_id", False) and ticket_id:
            set_parts.append("ticket_id = %s")

        update_vals = []
        if parsed_weight is not None:
            update_vals.append(parsed_weight)
        if cap.get("has_ticket_id", False) and ticket_id:
            update_vals.append(ticket_id)
        update_vals.append(order_id)

        cursor.execute(f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """, tuple(update_vals))

        if parsed_weight is not None:
            original_measure = row.get("weight_num")
            if service_type == "HD":
                original_val = float(int(round(float(original_measure or 0))))
                submitted_val = float(int(round(parsed_weight)))
            else:
                original_val = round(float(original_measure or 0), 2)
                submitted_val = round(float(parsed_weight), 2)
            diff_val = round(submitted_val - original_val, 2)

            if abs(diff_val) > 0:
                cursor.execute("""
                    INSERT INTO order_processing_exceptions
                    (
                        order_id,
                        user_id,
                        username,
                        service_type,
                        original_measure,
                        submitted_measure,
                        difference_measure,
                        date_clean,
                        batch_date,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        user_id = VALUES(user_id),
                        username = VALUES(username),
                        service_type = VALUES(service_type),
                        original_measure = VALUES(original_measure),
                        submitted_measure = VALUES(submitted_measure),
                        difference_measure = VALUES(difference_measure),
                        date_clean = VALUES(date_clean),
                        batch_date = VALUES(batch_date),
                        updated_at = NOW()
                """, (
                    order_id,
                    me["user_id"],
                    me.get("username"),
                    service_type,
                    original_val,
                    submitted_val,
                    diff_val,
                    row.get("date_clean"),
                    row.get("batch_date"),
                ))
            else:
                cursor.execute("DELETE FROM order_processing_exceptions WHERE order_id = %s", (order_id,))

        cursor.execute("SELECT ticket_blob_name, ticket_blob_url FROM order_process_submissions WHERE order_id = %s LIMIT 1", (order_id,))
        prev = cursor.fetchone() or {}
        ticket_payload = save_ticket_image(ticket_image_base64, ticket_file_name, order_id) if ticket_image_base64 else None

        cursor.execute("""
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
                ticket_image_base64 = IFNULL(VALUES(ticket_image_base64), ticket_image_base64),
                ticket_file_name = IFNULL(VALUES(ticket_file_name), ticket_file_name),
                ticket_blob_url = IFNULL(VALUES(ticket_blob_url), ticket_blob_url),
                ticket_blob_name = IFNULL(VALUES(ticket_blob_name), ticket_blob_name),
                ticket_storage = IFNULL(VALUES(ticket_storage), ticket_storage),
                ticket_size_bytes = IFNULL(VALUES(ticket_size_bytes), ticket_size_bytes),
                updated_at = NOW()
        """, (
            order_id,
            me["user_id"],
            me.get("username"),
            ticket_payload["ticket_image_base64"] if ticket_payload else None,
            ticket_file_name,
            ticket_payload["ticket_blob_url"] if ticket_payload else None,
            ticket_payload["ticket_blob_name"] if ticket_payload else None,
            ticket_payload["ticket_storage"] if ticket_payload else None,
            ticket_payload["ticket_size_bytes"] if ticket_payload else None,
        ))

        if ticket_payload and prev.get("ticket_blob_name") and prev.get("ticket_blob_name") != ticket_payload.get("ticket_blob_name"):
            delete_ticket_blob(prev.get("ticket_blob_name"), prev.get("ticket_blob_url"))

        conn.commit()
        return jsonify({"status": "processed_submitted", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["POST"])
def add_order_ticket(order_id):

    data = request.json or {}
    ticket_image_base64 = data.get("ticket_image_base64")
    ticket_file_name = data.get("ticket_file_name")

    if not ticket_image_base64:
        return jsonify({"error": "ticket_image_base64 is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)
        cursor.execute("SELECT id FROM orders_staging WHERE id = %s LIMIT 1", (order_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Order not found"}), 404

        cursor.execute("SELECT ticket_blob_name, ticket_blob_url FROM order_process_submissions WHERE order_id = %s LIMIT 1", (order_id,))
        prev = cursor.fetchone() or {}
        ticket_payload = save_ticket_image(ticket_image_base64, ticket_file_name, order_id)

        cursor.execute("""
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
        """, (
            order_id,
            me["user_id"],
            me.get("username"),
            ticket_payload["ticket_image_base64"],
            ticket_file_name,
            ticket_payload["ticket_blob_url"],
            ticket_payload["ticket_blob_name"],
            ticket_payload["ticket_storage"],
            ticket_payload["ticket_size_bytes"],
        ))

        if prev.get("ticket_blob_name") and prev.get("ticket_blob_name") != ticket_payload.get("ticket_blob_name"):
            delete_ticket_blob(prev.get("ticket_blob_name"), prev.get("ticket_blob_url"))

        conn.commit()
        return jsonify({"status": "ticket_saved", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["GET"])
def get_order_ticket(order_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)
        cursor.execute("""
            SELECT
                id,
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
            FROM order_process_submissions
            WHERE order_id = %s
            LIMIT 1
        """, (order_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Ticket not found"}), 404

        roles = fetch_user_roles(cursor, me["user_id"])
        is_admin = "ADMIN" in roles
        owner = int(row.get("user_id") or 0) == int(me["user_id"])
        if not is_admin and not owner:
            return jsonify({"error": "Forbidden"}), 403

        row["ticket_image_url"] = build_ticket_read_url(row.get("ticket_blob_name"), row.get("ticket_blob_url"))
        row["has_ticket_image"] = 1 if row.get("ticket_image_base64") or row.get("ticket_blob_url") else 0
        return jsonify(row)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["DELETE"])
def delete_order_ticket(order_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_process_submissions_table(cursor)
        cursor.execute("""
            SELECT id, user_id, ticket_blob_name, ticket_blob_url
            FROM order_process_submissions
            WHERE order_id = %s
            LIMIT 1
        """, (order_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Ticket not found"}), 404

        roles = fetch_user_roles(cursor, me["user_id"])
        is_admin = "ADMIN" in roles
        owner = int(row.get("user_id") or 0) == int(me["user_id"])
        if not is_admin and not owner:
            return jsonify({"error": "Forbidden"}), 403

        cursor.execute("""
            UPDATE order_process_submissions
            SET
                ticket_image_base64 = NULL,
                ticket_file_name = NULL,
                ticket_blob_url = NULL,
                ticket_blob_name = NULL,
                ticket_storage = NULL,
                ticket_size_bytes = NULL,
                updated_at = NOW()
            WHERE order_id = %s
        """, (order_id,))
        delete_ticket_blob(row.get("ticket_blob_name"), row.get("ticket_blob_url"))
        conn.commit()
        return jsonify({"status": "ticket_deleted", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/order_tickets", methods=["GET"])
def list_order_tickets():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        roles = fetch_user_roles(cursor, me["user_id"])
        if "ADMIN" not in roles:
            return jsonify({"error": "Forbidden"}), 403

        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)

        try:
            limit = int(request.args.get("limit", 200))
        except Exception:
            limit = 200
        limit = max(1, min(limit, 1000))

        cursor.execute("""
            SELECT
                s.id,
                s.order_id,
                s.user_id,
                s.username,
                s.ticket_file_name,
                s.ticket_blob_url,
                s.ticket_blob_name,
                s.ticket_storage,
                s.ticket_size_bytes,
                CASE
                    WHEN (s.ticket_blob_url IS NOT NULL AND s.ticket_blob_url <> '')
                      OR (s.ticket_image_base64 IS NOT NULL AND s.ticket_image_base64 <> '')
                    THEN 1 ELSE 0
                END AS has_ticket_image,
                s.created_at,
                s.updated_at,
                o.name_clean,
                o.date_clean,
                o.service_type,
                o.weight_num
            FROM order_process_submissions s
            LEFT JOIN orders_staging o ON o.id = s.order_id
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC
            LIMIT %s
        """, (limit,))

        rows = cursor.fetchall() or []
        for r in rows:
            r["ticket_image_url"] = build_ticket_read_url(r.get("ticket_blob_name"), r.get("ticket_blob_url"))
        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------

@app.route("/dashboard", methods=["GET"])
def dashboard():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cap = orders_status_capabilities(cursor)
        active_where = where_active_at_washpro_sql(cap)

        cursor.execute(f"""

            SELECT

                COUNT(*) AS total_orders,
                MAX(batch_date) AS batch_date,
                DAYNAME(MAX(batch_date)) AS batch_day,

                SUM(service_type = 'WF') AS wf_total,
                SUM(service_type = 'HD') AS hd_total,

                SUM(service_type = 'WF' AND date_clean < CURDATE()) AS wf_rush,
                SUM(service_type = 'WF' AND date_clean >= CURDATE()) AS wf_non_rush,

                SUM(service_type = 'HD' AND date_clean < CURDATE()) AS hd_rush,
                SUM(service_type = 'HD' AND date_clean >= CURDATE()) AS hd_non_rush

            FROM orders_staging
            WHERE {active_where}

        """)

        stats = cursor.fetchone()

        if stats:

            for k, v in stats.items():

                if v is None:
                    stats[k] = 0

        return jsonify(stats)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Upload Orders
# ---------------------------------------------------

def summarize_batch_rows(cursor, batch_id, row_pk):
    cursor.execute(f"""
        SELECT
            COUNT(*) AS total_rows,
            SUM(row_status IN ('ACCEPTED', 'OVERRIDDEN')) AS accepted_rows,
            SUM(row_status = 'REJECTED_DUPLICATE') AS rejected_rows,
            SUM(row_status = 'NEEDS_ATTENTION') AS attention_rows,
            SUM(row_status = 'DELETED') AS deleted_rows
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
    """, (batch_id,))
    summary = cursor.fetchone() or {}
    for key in ["total_rows", "accepted_rows", "rejected_rows", "attention_rows", "deleted_rows"]:
        if summary.get(key) is None:
            summary[key] = 0
    return summary


@app.route("/upload_orders", methods=["POST"])
def upload_orders():

    conn = None
    cursor = None

    try:

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        os.makedirs("uploads", exist_ok=True)

        filepath = os.path.join("uploads", file.filename)

        file.save(filepath)

        df = pd.read_excel(filepath, header=None)

        orders_df, summary_df, ops_summary = transform_orders(df)

        orders_df["Name_Clean"] = orders_df["Name_Clean"].astype(str).str.strip()

        orders_df["Weight_Num"] = orders_df["Weight_Num"].apply(normalize_weight)

        orders_df["fingerprint"] = orders_df.apply(
            lambda row: build_fingerprint(
                row.get("Name_Clean"),
                row.get("Weight_Num"),
                row.get("ServiceType")
            ),
            axis=1
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        requested_batch_date = request.form.get("batch_date")
        batch_date = parse_date_value(requested_batch_date) if requested_batch_date else date.today()

        upload_batches_pk = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)

        has_state = table_has_column(cursor, "upload_batches", "state")
        has_closed_at = table_has_column(cursor, "upload_batches", "closed_at")
        has_updated_at = table_has_column(cursor, "upload_batches", "updated_at")
        has_rows_inserted = table_has_column(cursor, "upload_batches", "rows_inserted")
        time_col = upload_batches_time_col(cursor)

        if has_state:
            # Close any open draft batch first.
            close_clause = "state = 'CLOSED'"
            if has_closed_at:
                close_clause += ", closed_at = NOW()"
            if has_updated_at:
                close_clause += ", updated_at = NOW()"

            cursor.execute(f"""
                UPDATE upload_batches
                SET {close_clause}
                WHERE state = 'DRAFT'
            """)

            # Same-day overwrite: close previous non-confirmed batch for same date.
            cursor.execute(f"""
                UPDATE upload_batches
                SET {close_clause}
                WHERE batch_date = %s
                AND state <> 'CONFIRMED'
            """, (batch_date,))

        insert_cols = ["file_name", "batch_date", "orders_loaded"]
        insert_vals = ["%s", "%s", "%s"]
        insert_args = [file.filename, batch_date, 0]

        if has_state:
            insert_cols.append("state")
            insert_vals.append("'DRAFT'")
        if time_col == "created_at":
            insert_cols.append("created_at")
            insert_vals.append("NOW()")

        cursor.execute(f"""
            INSERT INTO upload_batches
            ({", ".join(insert_cols)})
            VALUES ({", ".join(insert_vals)})
        """, tuple(insert_args))
        upload_batch_id = cursor.lastrowid

        # Configurable lookback window for duplicate checks against final records.
        try:
            duplicate_lookback_days = int(os.getenv("DUPLICATE_LOOKBACK_DAYS", "3"))
        except Exception:
            duplicate_lookback_days = 3
        duplicate_lookback_days = max(1, min(duplicate_lookback_days, 30))

        cap = orders_status_capabilities(cursor)

        # Build identity index from all staging rows (including checked/forced/processed).
        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                {logistics_sql},
                {processing_sql},
                status
            FROM orders_staging
        """)
        staging_rows = cursor.fetchall()
        existing_identity_reasons = {}

        def staging_reason_for_status(raw_logistics, raw_status):
            logistics = (raw_logistics or "").strip().upper()
            status = (raw_status or "").strip().upper()
            # If logistics_status exists, trust it as source of truth.
            if logistics:
                if logistics in ["SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"]:
                    return "ALREADY_SENT_OR_FORCED"
                return "DUPLICATE_IN_STAGING"

            # Legacy fallback only when logistics_status column is not present.
            if status in ["CHECKED_OUT", "SENT_TO_RINSE", "FORCED_CHECKOUT", "FORCE_CHECKOUT"]:
                return "ALREADY_SENT_OR_FORCED"
            return "DUPLICATE_IN_STAGING"

        for r in staging_rows:
            identity_key = build_identity_key(
                r.get("name_clean"),
                r.get("weight_num"),
                r.get("service_type"),
                r.get("date_clean")
            )
            next_reason = staging_reason_for_status(r.get("logistics_status"), r.get("status"))
            prev_reason = existing_identity_reasons.get(identity_key)
            # Keep the stronger signal if we already have one.
            if prev_reason != "ALREADY_SENT_OR_FORCED":
                existing_identity_reasons[identity_key] = next_reason

        final_cutoff = datetime.utcnow() - timedelta(days=duplicate_lookback_days)
        cursor.execute("""
            SELECT
                date_clean,
                name_clean,
                weight_num,
                service_type
            FROM orders_final
            WHERE cleaned_at >= %s
        """, (final_cutoff,))
        final_rows = cursor.fetchall()
        final_identity_keys = set(
            build_identity_key(
                r.get("name_clean"),
                r.get("weight_num"),
                r.get("service_type"),
                r.get("date_clean")
            )
            for r in final_rows
        )

        inserted = 0
        rejected = 0
        needs_attention = 0
        for _, row in orders_df.iterrows():

            date_clean = row.get("Date_Clean")
            name_clean = row.get("Name_Clean")
            weight_num = row.get("Weight_Num")
            service_type = row.get("ServiceType")
            rush_type_raw = row.get("RushType")

            if pd.isna(date_clean) or pd.isna(name_clean):
                continue

            if pd.isna(weight_num):
                weight_num = None

            if isinstance(date_clean, datetime):
                row_date = date_clean.date()
            elif isinstance(date_clean, date):
                row_date = date_clean
            else:
                row_date = parse_date_value(date_clean)
            is_batch_date_rush = (row_date == batch_date)
            rush_type = "RUSH" if (str(rush_type_raw).upper() == "RUSH" or is_batch_date_rush) else "NON-RUSH"

            identity_key = build_identity_key(name_clean, weight_num, service_type, row_date)
            row_status = "ACCEPTED"
            reason = "OK"

            if row_date < batch_date:
                row_status = "NEEDS_ATTENTION"
                reason = "OLDER_THAN_BATCH_DATE"
                needs_attention += 1
            elif identity_key in final_identity_keys:
                row_status = "REJECTED_DUPLICATE"
                reason = "ALREADY_IN_FINAL"
                rejected += 1
            elif identity_key in existing_identity_reasons:
                row_status = "REJECTED_DUPLICATE"
                reason = existing_identity_reasons[identity_key]
                rejected += 1
            else:
                inserted += 1

            cursor.execute("""
                INSERT INTO upload_batch_rows
                (
                    upload_batch_id,
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    row_status,
                    reason,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """, (
                upload_batch_id,
                row_date,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                row_status,
                reason
            ))

        set_parts = ["orders_loaded = %s"]
        set_args = [inserted]
        if has_rows_inserted:
            set_parts.append("rows_inserted = %s")
            set_args.append(inserted)
        if has_state:
            set_parts.append("state = 'DRAFT'")
        if has_updated_at:
            set_parts.append("updated_at = NOW()")

        set_args.append(upload_batch_id)
        cursor.execute(f"""
            UPDATE upload_batches
            SET {", ".join(set_parts)}
            WHERE {upload_batches_pk} = %s
        """, tuple(set_args))

        conn.commit()
        summary = summarize_batch_rows(cursor, upload_batch_id, row_pk)

        return jsonify({

            "status": "draft_uploaded",
            "batch_id": upload_batch_id,
            "batch_state": "DRAFT",
            "rows_inserted": inserted,
            "rejected_rows": rejected,
            "needs_attention_rows": needs_attention,
            "duplicate_lookback_days": duplicate_lookback_days,
            "summary": summary,
            "summary_rows": 0 if summary_df is None else len(summary_df)

        })

    except Exception as e:

        if conn:
            conn.rollback()

        print("UPLOAD ERROR:", str(e))

        return jsonify({

            "status": "error",
            "message": str(e)

        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ---------------------------------------------------
# Create Manual Order
# ---------------------------------------------------

@app.route("/orders/create_manual", methods=["POST"])
def create_manual_order():

    data = request.json or {}

    try:

        date_clean = parse_date_value(data.get("date_clean"))
        name_clean = (data.get("name_clean") or "").strip()
        weight_num = normalize_weight(data.get("weight_num"))
        service_type = (data.get("service_type") or "").strip()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()

        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400

        batch_date = date.today()

        conn = get_db()
        cursor = conn.cursor()
        cap = orders_status_capabilities(cursor)

        cols = [
            "date_clean",
            "name_clean",
            "weight_num",
            "service_type",
            "rush_type",
            "batch_date",
        ]
        vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
        args = [date_clean, name_clean, weight_num, service_type, rush_type, batch_date]

        if cap["has_logistics"]:
            cols.append("logistics_status")
            vals.append("%s")
            args.append("AT_WASHPRO")
        if cap["has_processing"]:
            cols.append("processing_status")
            vals.append("%s")
            args.append("PENDING")
        if cap["has_status"]:
            cols.append("status")
            vals.append("%s")
            args.append("PENDING")

        cursor.execute(f"""
            INSERT INTO orders_staging
            ({", ".join(cols)})
            VALUES ({", ".join(vals)})
        """, tuple(args))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"status": "created"})

    except Exception as e:

        return jsonify({"error": str(e)}), 500
    
# ---------------------------------------------------
# Employees API
# ---------------------------------------------------


@app.route("/employees", methods=["GET"])
def get_employees():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT id, name, role
        FROM employees
        WHERE active = TRUE
        ORDER BY name

    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(rows)

# ---------------------------------------------------
# Issue Dropdown API
# ---------------------------------------------------


@app.route("/issues", methods=["GET"])
def get_issues():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, issue_name
        FROM issue_types
        ORDER BY issue_name
    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(rows)

# ---------------------------------------------------
# Start Folder Shift
# ---------------------------------------------------


@app.route("/folder_shift/start", methods=["POST"])
def start_shift():

    data = request.json

    employee_id = data["employee_id"]
    start_time = data["start_time"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""

        INSERT INTO folder_shifts
        (employee_id, shift_date, shift_start_time)

        VALUES (%s, CURDATE(), %s)

    """, (employee_id, start_time))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "shift_started"})

# ---------------------------------------------------
# Get Current Shift
# ---------------------------------------------------

@app.route("/folder_shift/current", methods=["GET"])
def current_shift():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *
        FROM folder_shifts
        WHERE shift_date = CURDATE()
        ORDER BY id DESC
        LIMIT 1

    """)

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify(row)

# ---------------------------------------------------
# Enter Folding Record
# ---------------------------------------------------


@app.route("/order_processing", methods=["POST"])
def process_order():

    data = request.json or {}

    order_id = data.get("order_id")
    washer_id = data.get("washer_employee_id")
    folder_id = data.get("folder_employee_id")
    end_time = data.get("fold_end_time")
    pieces = data.get("pieces")
    issue = data.get("issue_type")
    rinse_case = data.get("rinse_case_id")
    processing_date = data.get("processing_date")

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400
    if washer_id in [None, ""] or folder_id in [None, ""]:
        return jsonify({"error": "washer_employee_id and folder_employee_id are required"}), 400

    try:
        order_id = int(order_id)
        washer_id = int(washer_id)
        folder_id = int(folder_id)
    except Exception:
        return jsonify({"error": "order_id, washer_employee_id, folder_employee_id must be numeric"}), 400

    if pieces in [None, ""]:
        pieces = None
    else:
        try:
            pieces = int(pieces)
        except Exception:
            return jsonify({"error": "pieces must be numeric"}), 400

    end_dt = None
    if end_time not in [None, ""]:
        # Accept ISO datetime, HH:MM (24h), or HH:MM AM/PM with optional processing_date.
        raw_end_time = str(end_time).strip()
        if processing_date not in [None, ""]:
            try:
                d = parse_date_value(processing_date)
                try:
                    t = datetime.strptime(raw_end_time, "%I:%M %p").time()
                except Exception:
                    t = datetime.strptime(raw_end_time, "%H:%M").time()
                end_dt = datetime.combine(d, t)
            except Exception:
                end_dt = None
        if end_dt is None:
            try:
                end_dt = datetime.fromisoformat(raw_end_time)
            except Exception:
                end_dt = None

    conn = get_db()
    cursor = conn.cursor()
    cap = orders_status_capabilities(cursor)

    cursor.execute("""

        INSERT INTO order_processing
        (
            order_id,
            washer_employee_id,
            folder_employee_id,
            fold_end_time,
            pieces,
            issue_type,
            rinse_case_id
        )

        VALUES (%s,%s,%s,%s,%s,%s,%s)

    """, (
        order_id,
        washer_id,
        folder_id,
        end_dt,
        pieces,
        issue,
        rinse_case
    ))

    set_parts = []
    if cap["has_processing"]:
        set_parts.append("processing_status='PROCESSED'")
    if cap["has_status"]:
        set_parts.append("status='PROCESSED'")
    if not set_parts:
        set_parts.append("status='PROCESSED'")

    cursor.execute(f"""

        UPDATE orders_staging
        SET {", ".join(set_parts)}
        WHERE id=%s

    """, (order_id,))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status":"recorded"})

# ---------------------------------------------------
# Scoreboard API
# ---------------------------------------------------

@app.route("/scoreboard", methods=["GET"])
def scoreboard():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT

        e.name,
        COUNT(*) as bags

        FROM order_processing p

        JOIN employees e
        ON p.folder_employee_id = e.id

        WHERE DATE(p.created_at)=CURDATE()

        GROUP BY e.id
        ORDER BY bags DESC

    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(rows)

# ---------------------------------------------------
# Maintenance APIs
# ---------------------------------------------------

@app.route("/issues/add", methods=["POST"])
def add_issue():

    data=request.json

    conn=get_db()
    cursor=conn.cursor()

    cursor.execute("""

    INSERT INTO issue_types(issue_name)
    VALUES(%s)

    """,(data["issue_name"],))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status":"added"})


# ---------------------------------------------------
# Geofence Config APIs
# ---------------------------------------------------

@app.route("/geofence/config", methods=["GET"])
def get_geofence_config():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"configured": False, "geofence": None})

        return jsonify({"configured": True, "geofence": geofence})

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Auth / RBAC APIs
# ---------------------------------------------------

@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, username, password_hash, display_name, active
            FROM users
            WHERE username = %s
            LIMIT 1
        """, (username,))
        user = cursor.fetchone()
        if not user or not user.get("active"):
            return jsonify({"error": "Invalid credentials"}), 401

        stored_hash = user.get("password_hash") or ""
        password_ok = False

        # Backward compatibility: allow legacy plain-text rows and migrate to hash.
        if stored_hash.startswith(("pbkdf2:", "scrypt:")):
            try:
                password_ok = check_password_hash(stored_hash, password)
            except Exception:
                password_ok = False
        else:
            password_ok = (stored_hash == password)
            if password_ok:
                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (generate_password_hash(password), user["id"])
                )

        if not password_ok:
            return jsonify({"error": "Invalid credentials"}), 401

        token = uuid.uuid4().hex
        expires_at = datetime.utcnow() + timedelta(hours=12)
        cursor.execute("""
            INSERT INTO auth_sessions
            (user_id, token, expires_at, revoked, created_at, last_seen_at)
            VALUES (%s, %s, %s, FALSE, NOW(), NOW())
        """, (user["id"], token, expires_at))

        roles = fetch_user_roles(cursor, user["id"])
        conn.commit()
        return jsonify({
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user.get("display_name") or user["username"],
                "roles": roles,
            }
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/me", methods=["GET"])
def auth_me():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me = current_user_from_token(cursor)
        if not me:
            return jsonify({"error": "Unauthorized"}), 401
        roles = fetch_user_roles(cursor, me["user_id"])
        cursor.execute("UPDATE auth_sessions SET last_seen_at = NOW() WHERE id = %s", (me["session_id"],))
        conn.commit()
        return jsonify({
            "id": me["user_id"],
            "username": me["username"],
            "display_name": me.get("display_name") or me["username"],
            "roles": roles
        })
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    token = get_bearer_token()
    if not token:
        return jsonify({"status": "ok"})
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE auth_sessions SET revoked = TRUE WHERE token = %s", (token,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/roles", methods=["GET"])
def auth_roles():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, code, name FROM roles ORDER BY code")
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/users", methods=["GET", "POST"])
def auth_users():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, status_code = require_admin(cursor)
        if err:
            return err, status_code

        if request.method == "GET":
            cursor.execute("""
                SELECT id, username, display_name, active, created_at
                FROM users
                ORDER BY username
            """)
            users = cursor.fetchall()
            for u in users:
                u["roles"] = fetch_user_roles(cursor, u["id"])
            return jsonify(users)

        data = request.json or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        display_name = (data.get("display_name") or "").strip() or username
        active = bool(data.get("active", True))
        role_codes = [str(r).upper() for r in (data.get("roles") or [])]
        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400

        password_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users
            (username, password_hash, display_name, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
        """, (username, password_hash, display_name, active))
        user_id = cursor.lastrowid

        if role_codes:
            cursor.execute("SELECT id, code FROM roles WHERE code IN ({})".format(",".join(["%s"] * len(role_codes))), tuple(role_codes))
            role_map = {r["code"].upper(): r["id"] for r in cursor.fetchall()}
            for code in role_codes:
                rid = role_map.get(code)
                if rid:
                    cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)", (user_id, rid))

        conn.commit()
        return jsonify({"status": "created", "user_id": user_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Maintenance APIs
# ---------------------------------------------------

@app.route("/maintenance/tasks", methods=["GET", "POST"])
def maintenance_tasks_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT id, task_code, task_name, category, active, created_at, updated_at
                FROM maintenance_tasks
                ORDER BY task_name
            """)
            return jsonify(cursor.fetchall())

        data = request.json or {}
        task_code = (data.get("task_code") or "").strip().upper()
        task_name = (data.get("task_name") or "").strip()
        category = (data.get("category") or "CLEANING").strip().upper()
        active = bool(data.get("active", True))
        if not task_code or not task_name:
            return jsonify({"error": "task_code and task_name are required"}), 400

        cursor.execute("""
            INSERT INTO maintenance_tasks
            (task_code, task_name, category, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
        """, (task_code, task_name, category, active))
        conn.commit()
        return jsonify({"status": "created", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/assignments", methods=["GET", "POST"])
def maintenance_assignments_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            status = (request.args.get("status") or "").strip().upper()
            where = ""
            args = []
            if status:
                where = "WHERE a.status = %s"
                args.append(status)
            cursor.execute(f"""
                SELECT
                    a.id,
                    a.task_id,
                    t.task_name,
                    a.assigned_to_employee_id,
                    a.assigned_to_name,
                    a.due_date,
                    a.frequency_type,
                    a.frequency_interval,
                    a.weekdays_csv,
                    a.status,
                    a.notes,
                    a.created_at
                FROM maintenance_assignments a
                JOIN maintenance_tasks t ON t.id = a.task_id
                {where}
                ORDER BY a.due_date ASC, a.id ASC
            """, tuple(args))
            return jsonify(cursor.fetchall())

        data = request.json or {}
        task_id = data.get("task_id")
        assigned_to_employee_id = data.get("assigned_to_employee_id")
        assigned_to_name = (data.get("assigned_to_name") or "").strip() or None
        due_date = parse_date_value(data.get("due_date"))
        frequency_type = (data.get("frequency_type") or "ONE_TIME").strip().upper()
        frequency_interval = int(data.get("frequency_interval") or 1)
        weekdays_csv = (data.get("weekdays_csv") or "").strip() or None
        notes = (data.get("notes") or "").strip() or None
        created_by = (data.get("created_by") or "admin").strip()

        if task_id in [None, ""] or due_date is None:
            return jsonify({"error": "task_id and due_date are required"}), 400

        cursor.execute("""
            INSERT INTO maintenance_assignments
            (
              task_id, assigned_to_employee_id, assigned_to_name, due_date,
              frequency_type, frequency_interval, weekdays_csv, status, notes, created_by, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ASSIGNED', %s, %s, NOW(), NOW())
        """, (
            int(task_id),
            int(assigned_to_employee_id) if assigned_to_employee_id not in [None, ""] else None,
            assigned_to_name,
            due_date,
            frequency_type,
            frequency_interval,
            weekdays_csv,
            notes,
            created_by
        ))
        conn.commit()
        return jsonify({"status": "assigned", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/logs", methods=["GET", "POST"])
def maintenance_logs_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT
                    l.id,
                    l.assignment_id,
                    l.task_id,
                    t.task_name,
                    l.performed_by_employee_id,
                    l.performed_by_name,
                    l.performed_date,
                    l.start_time,
                    l.end_time,
                    l.pit1_done,
                    l.pit2_done,
                    l.big_pit_done,
                    l.washer_no,
                    l.notes,
                    l.source_type,
                    l.created_at
                FROM maintenance_logs l
                JOIN maintenance_tasks t ON t.id = l.task_id
                ORDER BY l.performed_date DESC, l.id DESC
                LIMIT 500
            """)
            return jsonify(cursor.fetchall())

        data = request.json or {}
        assignment_id = data.get("assignment_id")
        task_id = data.get("task_id")
        if task_id in [None, ""]:
            return jsonify({"error": "task_id is required"}), 400

        performed_by_employee_id = data.get("performed_by_employee_id")
        performed_by_name = (data.get("performed_by_name") or "").strip()
        performed_date = parse_date_value(data.get("performed_date")) or date.today()
        start_time_raw = (data.get("start_time") or "").strip()
        end_time_raw = (data.get("end_time") or "").strip()
        notes = (data.get("notes") or "").strip() or None
        washer_no = (data.get("washer_no") or "").strip() or None
        source_type = (data.get("source_type") or ("ASSIGNED" if assignment_id else "ADHOC")).strip().upper()

        if not performed_by_name:
            return jsonify({"error": "performed_by_name is required"}), 400

        def parse_dt(s):
            if not s:
                return None
            try:
                t = datetime.strptime(s, "%I:%M %p").time()
                return datetime.combine(performed_date, t)
            except Exception:
                pass
            try:
                t = datetime.strptime(s, "%H:%M").time()
                return datetime.combine(performed_date, t)
            except Exception:
                pass
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

        start_dt = parse_dt(start_time_raw)
        end_dt = parse_dt(end_time_raw)

        cursor.execute("""
            INSERT INTO maintenance_logs
            (
              assignment_id, task_id, performed_by_employee_id, performed_by_name, performed_date,
              start_time, end_time, pit1_done, pit2_done, big_pit_done, washer_no, notes, source_type, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            int(assignment_id) if assignment_id not in [None, ""] else None,
            int(task_id),
            int(performed_by_employee_id) if performed_by_employee_id not in [None, ""] else None,
            performed_by_name,
            performed_date,
            start_dt,
            end_dt,
            bool(data.get("pit1_done", False)),
            bool(data.get("pit2_done", False)),
            bool(data.get("big_pit_done", False)),
            washer_no,
            notes,
            source_type
        ))

        if assignment_id not in [None, ""]:
            cursor.execute("UPDATE maintenance_assignments SET status = 'COMPLETED', updated_at = NOW() WHERE id = %s", (int(assignment_id),))

        conn.commit()
        return jsonify({"status": "logged", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Inventory APIs
# ---------------------------------------------------

@app.route("/inventory/items", methods=["GET", "POST"])
def inventory_items_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT
                    id, item_name, category, vendor_name, unit_label,
                    reorder_threshold, on_hand_qty, active, created_at, updated_at
                FROM inventory_items
                ORDER BY category, item_name
            """)
            return jsonify(cursor.fetchall())

        data = request.json or {}
        item_name = (data.get("item_name") or "").strip()
        category = (data.get("category") or "SUPPLY").strip().upper()
        vendor_name = (data.get("vendor_name") or "").strip() or None
        unit_label = (data.get("unit_label") or "unit").strip()
        reorder_threshold = float(data.get("reorder_threshold") or 0)
        on_hand_qty = float(data.get("on_hand_qty") or 0)
        active = bool(data.get("active", True))
        if not item_name:
            return jsonify({"error": "item_name is required"}), 400
        cursor.execute("""
            INSERT INTO inventory_items
            (item_name, category, vendor_name, unit_label, reorder_threshold, on_hand_qty, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (item_name, category, vendor_name, unit_label, reorder_threshold, on_hand_qty, active))
        conn.commit()
        return jsonify({"status": "created", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/counts", methods=["POST"])
def inventory_count_api():
    data = request.json or {}
    item_id = data.get("item_id")
    counted_qty = data.get("counted_qty")
    counted_by = (data.get("counted_by") or "").strip() or "system"
    notes = (data.get("notes") or "").strip() or None

    if item_id in [None, ""] or counted_qty in [None, ""]:
        return jsonify({"error": "item_id and counted_qty are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO inventory_counts
            (item_id, counted_qty, counted_by, counted_at, notes)
            VALUES (%s, %s, %s, NOW(), %s)
        """, (int(item_id), float(counted_qty), counted_by, notes))

        cursor.execute("""
            UPDATE inventory_items
            SET on_hand_qty = %s, updated_at = NOW()
            WHERE id = %s
        """, (float(counted_qty), int(item_id)))

        conn.commit()
        return jsonify({"status": "count_saved"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/bag_sales", methods=["GET", "POST"])
def inventory_bag_sales_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT id, sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at
                FROM bag_sales
                ORDER BY sale_date DESC, id DESC
                LIMIT 500
            """)
            return jsonify(cursor.fetchall())

        data = request.json or {}
        sale_date = parse_date_value(data.get("sale_date")) or date.today()
        customer_name = (data.get("customer_name") or "").strip()
        sale_type = (data.get("sale_type") or "DROP_OFF").strip().upper()
        qty = int(data.get("qty") or 0)
        amount_paid = (data.get("amount_paid") or "").strip() or None
        entered_by = (data.get("entered_by") or "").strip() or None
        if not customer_name or qty <= 0:
            return jsonify({"error": "customer_name and qty>0 are required"}), 400

        cursor.execute("""
            INSERT INTO bag_sales
            (sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (sale_date, customer_name, sale_type, qty, amount_paid, entered_by))

        # Auto-decrement first active BAG item (if configured).
        cursor.execute("""
            SELECT id, on_hand_qty
            FROM inventory_items
            WHERE category = 'BAG' AND active = TRUE
            ORDER BY id ASC
            LIMIT 1
        """)
        bag_item = cursor.fetchone()
        if bag_item:
            next_qty = float(bag_item["on_hand_qty"] or 0) - float(qty)
            cursor.execute(
                "UPDATE inventory_items SET on_hand_qty = %s, updated_at = NOW() WHERE id = %s",
                (next_qty, bag_item["id"]),
            )

        conn.commit()
        return jsonify({"status": "sale_saved"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/low_stock", methods=["GET"])
def inventory_low_stock():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                id, item_name, category, vendor_name, unit_label, on_hand_qty, reorder_threshold
            FROM inventory_items
            WHERE active = TRUE
              AND on_hand_qty <= reorder_threshold
            ORDER BY category, item_name
        """)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/geofence/config", methods=["POST"])
def save_geofence_config():

    data = request.json or {}

    label = (data.get("label") or "").strip() or "Primary"
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    radius_m = data.get("radius_m")
    updated_by = (data.get("updated_by") or "").strip() or "admin"
    active = bool(data.get("active", True))

    try:
        latitude = float(latitude)
        longitude = float(longitude)
        radius_m = int(radius_m)
    except Exception:
        return jsonify({"error": "latitude, longitude, radius_m are required numeric values"}), 400

    if radius_m <= 0:
        return jsonify({"error": "radius_m must be > 0"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        if active:
            cursor.execute("UPDATE geofence_settings SET active = FALSE")

        cursor.execute("""
            INSERT INTO geofence_settings
            (
                label,
                latitude,
                longitude,
                radius_m,
                active,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_by
        ))

        conn.commit()
        return jsonify({"status": "saved"})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Attendance / Clock APIs
# ---------------------------------------------------

@app.route("/attendance/punch", methods=["POST"])
def attendance_punch():

    data = request.json or {}

    employee_id = data.get("employee_id")
    event_type = (data.get("event_type") or "").strip().upper()
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    notes = (data.get("notes") or "").strip() or None
    personal_bags = data.get("personal_bags")
    device_time = data.get("device_time")

    allowed_events = {
        "CLOCK_IN",
        "CLOCK_OUT",
        "BREAK_START",
        "BREAK_END",
        "RINSE_SHIFT_START",
        "RINSE_SHIFT_END"
    }

    if event_type not in allowed_events:
        return jsonify({"error": "Invalid event_type"}), 400

    if employee_id in [None, ""]:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        employee_id = int(employee_id)
        latitude = float(latitude)
        longitude = float(longitude)
    except Exception:
        return jsonify({"error": "employee_id, latitude, longitude must be numeric"}), 400

    if personal_bags in [None, ""]:
        personal_bags = None
    else:
        try:
            personal_bags = int(personal_bags)
        except Exception:
            return jsonify({"error": "personal_bags must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"error": "No geofence configured"}), 400

        distance_m = haversine_meters(
            latitude,
            longitude,
            float(geofence["latitude"]),
            float(geofence["longitude"])
        )
        within_geofence = distance_m <= float(geofence["radius_m"])

        if not within_geofence:
            return jsonify({
                "error": "Outside geofence",
                "distance_m": round(distance_m, 2),
                "radius_m": geofence["radius_m"]
            }), 403

        cursor.execute("""
            INSERT INTO attendance_events
            (
                employee_id,
                event_type,
                event_time,
                device_time,
                latitude,
                longitude,
                within_geofence,
                distance_m,
                geofence_id,
                notes,
                personal_bags
            )
            VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            employee_id,
            event_type,
            device_time,
            latitude,
            longitude,
            within_geofence,
            round(distance_m, 2),
            geofence["id"],
            notes,
            personal_bags
        ))

        # Update latest known presence for near-real-time monitoring
        cursor.execute("""
            INSERT INTO employee_geo_presence
            (
                employee_id,
                is_inside,
                latitude,
                longitude,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                is_inside = VALUES(is_inside),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                last_seen_at = VALUES(last_seen_at)
        """, (
            employee_id,
            within_geofence,
            latitude,
            longitude
        ))

        conn.commit()

        return jsonify({
            "status": "recorded",
            "event_type": event_type,
            "within_geofence": within_geofence,
            "distance_m": round(distance_m, 2),
            "radius_m": geofence["radius_m"]
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/location_ping", methods=["POST"])
def attendance_location_ping():

    data = request.json or {}
    employee_id = data.get("employee_id")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if employee_id in [None, ""] or latitude in [None, ""] or longitude in [None, ""]:
        return jsonify({"error": "employee_id, latitude, longitude are required"}), 400

    try:
        employee_id = int(employee_id)
        latitude = float(latitude)
        longitude = float(longitude)
    except Exception:
        return jsonify({"error": "employee_id, latitude, longitude must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"error": "No geofence configured"}), 400

        distance_m = haversine_meters(
            latitude,
            longitude,
            float(geofence["latitude"]),
            float(geofence["longitude"])
        )
        is_inside = distance_m <= float(geofence["radius_m"])

        cursor.execute("""
            SELECT is_inside
            FROM employee_geo_presence
            WHERE employee_id = %s
        """, (employee_id,))
        prev_row = cursor.fetchone()
        previous_inside = None if not prev_row else bool(prev_row["is_inside"])

        cursor.execute("""
            INSERT INTO employee_geo_presence
            (
                employee_id,
                is_inside,
                latitude,
                longitude,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                is_inside = VALUES(is_inside),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                last_seen_at = VALUES(last_seen_at)
        """, (
            employee_id,
            is_inside,
            latitude,
            longitude
        ))

        transition = None

        if previous_inside is not None and previous_inside != is_inside:
            transition = "ENTER" if is_inside else "EXIT"

            cursor.execute("""
                INSERT INTO geofence_alerts
                (
                    employee_id,
                    transition_type,
                    geofence_id,
                    latitude,
                    longitude,
                    distance_m,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (
                employee_id,
                transition,
                geofence["id"],
                latitude,
                longitude,
                round(distance_m, 2)
            ))

        conn.commit()

        return jsonify({
            "status": "ok",
            "is_inside": is_inside,
            "transition": transition,
            "distance_m": round(distance_m, 2),
            "radius_m": geofence["radius_m"]
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/alerts", methods=["GET"])
def attendance_alerts():

    since_id = request.args.get("since_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        if since_id not in [None, ""]:
            cursor.execute("""
                SELECT
                    a.id,
                    a.employee_id,
                    e.name AS employee_name,
                    a.transition_type,
                    a.distance_m,
                    a.created_at
                FROM geofence_alerts a
                LEFT JOIN employees e
                ON e.id = a.employee_id
                WHERE a.id > %s
                ORDER BY a.id ASC
                LIMIT 200
            """, (int(since_id),))
        else:
            cursor.execute("""
                SELECT
                    a.id,
                    a.employee_id,
                    e.name AS employee_name,
                    a.transition_type,
                    a.distance_m,
                    a.created_at
                FROM geofence_alerts a
                LEFT JOIN employees e
                ON e.id = a.employee_id
                ORDER BY a.id DESC
                LIMIT 200
            """)

        return jsonify(cursor.fetchall())

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/live", methods=["GET"])
def attendance_live():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                t.employee_id,
                e.name,
                t.last_event,
                p.is_inside,
                p.last_seen_at
            FROM
            (
                SELECT
                    employee_id,
                    SUBSTRING_INDEX(
                        GROUP_CONCAT(event_type ORDER BY event_time DESC, id DESC),
                        ',',
                        1
                    ) AS last_event
                FROM attendance_events
                WHERE DATE(event_time) = CURDATE()
                AND event_type IN ('CLOCK_IN', 'CLOCK_OUT')
                GROUP BY employee_id
            ) t
            LEFT JOIN employees e
            ON e.id = t.employee_id
            LEFT JOIN employee_geo_presence p
            ON p.employee_id = t.employee_id
            ORDER BY e.name
        """)

        rows = cursor.fetchall()

        at_work = [
            row for row in rows
            if (row.get("last_event") or "").upper() == "CLOCK_IN"
        ]

        return jsonify({
            "at_work_count": len(at_work),
            "at_work": at_work,
            "all_today": rows
        })

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/events_today", methods=["GET"])
def attendance_events_today():

    employee_id = request.args.get("employee_id")

    if employee_id in [None, ""]:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        employee_id = int(employee_id)
    except Exception:
        return jsonify({"error": "employee_id must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                id,
                employee_id,
                event_type,
                event_time,
                notes,
                personal_bags
            FROM attendance_events
            WHERE employee_id = %s
            AND DATE(event_time) = CURDATE()
            ORDER BY event_time DESC, id DESC
        """, (employee_id,))

        rows = cursor.fetchall()
        return jsonify(rows)

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Batch Review APIs
# ---------------------------------------------------

@app.route("/upload_batches/current", methods=["GET"])
def get_current_upload_batch():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        selected_cols = [
            f"{pk_col} AS id",
            "file_name",
            "batch_date",
            "orders_loaded",
        ]

        if table_has_column(cursor, "upload_batches", "state"):
            selected_cols.append("state")
        else:
            selected_cols.append("'DRAFT' AS state")

        # Pick whichever time columns exist in this environment.
        if table_has_column(cursor, "upload_batches", "created_at"):
            selected_cols.append("created_at")
        elif table_has_column(cursor, "upload_batches", "uploaded_at"):
            selected_cols.append("uploaded_at AS created_at")
        else:
            selected_cols.append("NULL AS created_at")

        if table_has_column(cursor, "upload_batches", "updated_at"):
            selected_cols.append("updated_at")
        else:
            selected_cols.append("NULL AS updated_at")

        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            selected_cols.append("confirmed_at")
        else:
            selected_cols.append("NULL AS confirmed_at")

        if table_has_column(cursor, "upload_batches", "closed_at"):
            selected_cols.append("closed_at")
        else:
            selected_cols.append("NULL AS closed_at")

        cursor.execute(f"""
            SELECT
                {", ".join(selected_cols)}
            FROM upload_batches
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return jsonify(None)

        row_pk = get_upload_batch_rows_pk(cursor)
        summary = summarize_batch_rows(cursor, row["id"], row_pk)
        row["summary"] = summary
        return jsonify(row)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches", methods=["GET"])
def list_upload_batches():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        limit = request.args.get("limit", default=20, type=int) or 20
        limit = max(1, min(limit, 100))

        selected_cols = [
            f"{pk_col} AS id",
            "file_name",
            "batch_date",
            "orders_loaded",
        ]

        if table_has_column(cursor, "upload_batches", "state"):
            selected_cols.append("state")
        else:
            selected_cols.append("'DRAFT' AS state")

        if table_has_column(cursor, "upload_batches", "created_at"):
            selected_cols.append("created_at")
        elif table_has_column(cursor, "upload_batches", "uploaded_at"):
            selected_cols.append("uploaded_at AS created_at")
        else:
            selected_cols.append("NULL AS created_at")

        if table_has_column(cursor, "upload_batches", "updated_at"):
            selected_cols.append("updated_at")
        else:
            selected_cols.append("NULL AS updated_at")

        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            selected_cols.append("confirmed_at")
        else:
            selected_cols.append("NULL AS confirmed_at")

        if table_has_column(cursor, "upload_batches", "closed_at"):
            selected_cols.append("closed_at")
        else:
            selected_cols.append("NULL AS closed_at")

        cursor.execute(f"""
            SELECT
                {", ".join(selected_cols)}
            FROM upload_batches
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall() or []

        row_pk = get_upload_batch_rows_pk(cursor)
        for row in rows:
            row["summary"] = summarize_batch_rows(cursor, row["id"], row_pk)

        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/current/reset", methods=["POST"])
def reset_current_draft_batch():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        where_state = "WHERE state = 'DRAFT'" if table_has_column(cursor, "upload_batches", "state") else ""

        cursor.execute(f"""
            SELECT {pk_col} AS id, state
            FROM upload_batches
            {where_state}
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT 1
        """)
        batch = cursor.fetchone()

        if not batch:
            return jsonify({
                "status": "nothing_to_reset",
                "message": "No draft batch available."
            })

        batch_id = batch["id"]
        row_pk = get_upload_batch_rows_pk(cursor)
        summary = summarize_batch_rows(cursor, batch_id, row_pk)

        cursor.execute("""
            DELETE FROM upload_batch_rows
            WHERE upload_batch_id = %s
        """, (batch_id,))

        cursor.execute(f"""
            DELETE FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))

        conn.commit()
        return jsonify({
            "status": "draft_reset",
            "batch_id": batch_id,
            "deleted_row_count": summary.get("total_rows", 0)
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/reset_all", methods=["POST"])
def reset_all_upload_batches():

    data = request.json or {}
    cascade_data = as_bool(data.get("cascade_data"), True)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        row_pk = get_upload_batch_rows_pk(cursor)
        batch_pk = get_upload_batches_pk(cursor)

        cursor.execute(f"SELECT COUNT(*) AS cnt FROM upload_batch_rows")
        rows_before = (cursor.fetchone() or {}).get("cnt", 0) or 0

        cursor.execute(f"SELECT COUNT(*) AS cnt FROM upload_batches")
        batches_before = (cursor.fetchone() or {}).get("cnt", 0) or 0

        cursor.execute("DELETE FROM upload_batch_rows")
        cursor.execute("DELETE FROM upload_batches")

        cascade_deleted = {
            "orders_staging": 0,
            "orders_final": 0,
            "checkout_log": 0,
            "order_processing": 0,
        }
        if cascade_data:
            for table_name in ["order_processing", "checkout_log", "orders_final", "orders_staging"]:
                if table_exists(cursor, table_name):
                    cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
                    before = (cursor.fetchone() or {}).get("cnt", 0) or 0
                    cursor.execute(f"DELETE FROM {table_name}")
                    cascade_deleted[table_name] = before

        # Reset auto-increment where possible for cleaner testing
        try:
            cursor.execute("ALTER TABLE upload_batch_rows AUTO_INCREMENT = 1")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE upload_batches AUTO_INCREMENT = 1")
        except Exception:
            pass

        conn.commit()
        return jsonify({
            "status": "reset_complete",
            "deleted_rows": rows_before,
            "deleted_batches": batches_before,
            "cascade_data": cascade_data,
            "cascade_deleted": cascade_deleted,
            "row_pk": row_pk,
            "batch_pk": batch_pk
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/delete", methods=["POST"])
def delete_upload_batch(batch_id):

    data = request.json or {}
    cascade_data = as_bool(data.get("cascade_data"), True)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        batch_pk = get_upload_batches_pk(cursor)
        cursor.execute(f"""
            SELECT {batch_pk} AS id, state
            FROM upload_batches
            WHERE {batch_pk} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404

        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
        """, (batch_id,))
        row_count = (cursor.fetchone() or {}).get("cnt", 0) or 0

        cascade_deleted = {
            "orders_staging": 0,
            "orders_final": 0,
            "checkout_log": 0,
            "order_processing": 0,
        }
        if cascade_data:
            cursor.execute("""
                SELECT
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                  AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
            """, (batch_id,))
            identity_rows = cursor.fetchall()

            staging_ids = []
            if table_exists(cursor, "orders_staging"):
                for row in identity_rows:
                    cursor.execute("""
                        SELECT id
                        FROM orders_staging
                        WHERE UPPER(TRIM(name_clean)) = UPPER(TRIM(%s))
                          AND service_type = %s
                          AND ((weight_num IS NULL AND %s IS NULL) OR weight_num = %s)
                          AND date_clean = %s
                    """, (
                        row.get("name_clean"),
                        row.get("service_type"),
                        row.get("weight_num"),
                        row.get("weight_num"),
                        row.get("date_clean"),
                    ))
                    staging_ids.extend([r["id"] for r in cursor.fetchall()])

                cascade_deleted["orders_staging"] = delete_identity_rows(
                    cursor,
                    "orders_staging",
                    identity_rows,
                    "name_clean",
                    "weight_num",
                    "service_type",
                    "date_clean",
                )

            if table_exists(cursor, "orders_final"):
                has_date_clean_final = table_has_column(cursor, "orders_final", "date_clean")
                if has_date_clean_final:
                    cascade_deleted["orders_final"] = delete_identity_rows(
                        cursor,
                        "orders_final",
                        identity_rows,
                        "name_clean",
                        "weight_num",
                        "service_type",
                        "date_clean",
                    )

            if table_exists(cursor, "checkout_log"):
                for row in identity_rows:
                    cursor.execute("""
                        DELETE FROM checkout_log
                        WHERE UPPER(TRIM(name)) = UPPER(TRIM(%s))
                          AND service = %s
                          AND ((weight IS NULL AND %s IS NULL) OR weight = %s)
                          AND rush_date = %s
                    """, (
                        row.get("name_clean"),
                        row.get("service_type"),
                        row.get("weight_num"),
                        row.get("weight_num"),
                        row.get("date_clean"),
                    ))
                    cascade_deleted["checkout_log"] += cursor.rowcount or 0

            if staging_ids and table_exists(cursor, "order_processing"):
                placeholders = ", ".join(["%s"] * len(staging_ids))
                cursor.execute(
                    f"DELETE FROM order_processing WHERE order_id IN ({placeholders})",
                    tuple(staging_ids),
                )
                cascade_deleted["order_processing"] = cursor.rowcount or 0

        cursor.execute("""
            DELETE FROM upload_batch_rows
            WHERE upload_batch_id = %s
        """, (batch_id,))

        cursor.execute(f"""
            DELETE FROM upload_batches
            WHERE {batch_pk} = %s
        """, (batch_id,))

        conn.commit()
        return jsonify({
            "status": "batch_deleted",
            "batch_id": batch_id,
            "deleted_rows": row_count,
            "cascade_data": cascade_data,
            "cascade_deleted": cascade_deleted,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows", methods=["GET"])
def get_upload_batch_rows(batch_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    row_status = (request.args.get("row_status") or "").strip().upper()

    try:
        row_pk = get_upload_batch_rows_pk(cursor)
        if row_status:
            cursor.execute(f"""
                SELECT
                    {row_pk} AS id,
                    upload_batch_id,
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    row_status,
                    reason,
                    created_at,
                    updated_at
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                AND row_status = %s
                ORDER BY {row_pk} ASC
            """, (batch_id, row_status))
        else:
            cursor.execute(f"""
                SELECT
                    {row_pk} AS id,
                    upload_batch_id,
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    row_status,
                    reason,
                    created_at,
                    updated_at
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                ORDER BY {row_pk} ASC
            """, (batch_id,))

        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/<int:row_id>/override", methods=["POST"])
def override_upload_batch_row(batch_id, row_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)

        cursor.execute(f"""
            SELECT {pk_col} AS id, batch_date, state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        cursor.execute(f"""
            SELECT {row_pk} AS id
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (batch_id, row_id))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({"error": "Batch row not found"}), 404

        date_clean = parse_date_value(data.get("date_clean")) if data.get("date_clean") not in [None, ""] else None
        name_clean = (data.get("name_clean") or "").strip()
        service_type = (data.get("service_type") or "").strip().upper()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()
        weight_num = normalize_weight(data.get("weight_num"))

        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400
        if service_type not in ["WF", "HD"]:
            return jsonify({"error": "service_type must be WF or HD"}), 400
        if rush_type not in ["RUSH", "NON-RUSH"]:
            return jsonify({"error": "rush_type must be RUSH or NON-RUSH"}), 400

        requested_row_status = (data.get("row_status") or "").strip().upper()
        requested_reason = (data.get("reason") or "").strip()

        reason = "OVERRIDDEN_BY_USER"
        row_status = "OVERRIDDEN"
        if date_clean and date_clean < batch["batch_date"]:
            row_status = "NEEDS_ATTENTION"
            reason = "OLDER_THAN_BATCH_DATE"

        allowed_manual_statuses = {
            "ACCEPTED",
            "OVERRIDDEN",
            "NEEDS_ATTENTION",
            "REJECTED_DUPLICATE",
            "DELETED",
        }
        if requested_row_status:
            if requested_row_status not in allowed_manual_statuses:
                return jsonify({"error": "row_status is invalid"}), 400
            row_status = requested_row_status

        if requested_reason:
            reason = requested_reason

        cursor.execute(f"""
            UPDATE upload_batch_rows
            SET
                date_clean = %s,
                name_clean = %s,
                weight_num = %s,
                service_type = %s,
                rush_type = %s,
                row_status = %s,
                reason = %s,
                updated_at = NOW()
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            row_status,
            reason,
            batch_id,
            row_id
        ))

        conn.commit()
        return jsonify({"status": "row_updated", "row_id": row_id, "row_status": row_status})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/<int:row_id>/delete", methods=["POST"])
def delete_upload_batch_row(batch_id, row_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)
        cursor.execute(f"""
            SELECT state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        cursor.execute(f"""
            UPDATE upload_batch_rows
            SET row_status = 'DELETED', reason = 'DELETED_BY_USER', updated_at = NOW()
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (batch_id, row_id))
        conn.commit()
        return jsonify({"status": "row_deleted", "row_id": row_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/add", methods=["POST"])
def add_upload_batch_row(batch_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)

        cursor.execute(f"""
            SELECT {pk_col} AS id, batch_date, state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        date_clean = parse_date_value(data.get("date_clean")) if data.get("date_clean") not in [None, ""] else None
        name_clean = (data.get("name_clean") or "").strip()
        service_type = (data.get("service_type") or "").strip().upper()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()
        weight_num = normalize_weight(data.get("weight_num"))

        if not date_clean:
            return jsonify({"error": "date_clean is required"}), 400
        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400
        if service_type not in ["WF", "HD"]:
            return jsonify({"error": "service_type must be WF or HD"}), 400
        if rush_type not in ["RUSH", "NON-RUSH"]:
            return jsonify({"error": "rush_type must be RUSH or NON-RUSH"}), 400

        row_status = "OVERRIDDEN"
        reason = "ADDED_BY_USER"
        if date_clean < batch["batch_date"]:
            row_status = "NEEDS_ATTENTION"
            reason = "OLDER_THAN_BATCH_DATE"

        cursor.execute("""
            INSERT INTO upload_batch_rows
            (
                upload_batch_id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                row_status,
                reason,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (
            batch_id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            row_status,
            reason
        ))
        new_row_id = cursor.lastrowid
        conn.commit()
        return jsonify({"status": "row_added", "row_id": new_row_id, "row_status": row_status})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/confirm", methods=["POST"])
def confirm_upload_batch(batch_id):

    data = request.json or {}
    force_confirm = bool(data.get("force_confirm"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        batch_pk = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)
        cap = orders_status_capabilities(cursor)

        cursor.execute(f"""
            SELECT {batch_pk} AS id, batch_date, state
            FROM upload_batches
            WHERE {batch_pk} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"status": "already_confirmed"}), 200

        cursor.execute(f"""
            SELECT COUNT(*) AS attention_count
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status = 'NEEDS_ATTENTION'
        """, (batch_id,))
        attention_count = (cursor.fetchone() or {}).get("attention_count", 0) or 0
        if attention_count > 0 and not force_confirm:
            return jsonify({
                "error": "Batch has NEEDS_ATTENTION rows",
                "attention_count": attention_count
            }), 409

        cursor.execute(f"""
            SELECT
                {row_pk} AS id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """, (batch_id,))
        accepted_rows = cursor.fetchall()

        # Safety guard: do not let a fully rejected draft mutate live staging/final.
        if len(accepted_rows) == 0:
            return jsonify({
                "error": "Batch has no ACCEPTED/OVERRIDDEN rows. Nothing to apply.",
                "accepted_count": 0
            }), 409

        uploaded_identity_keys = set()
        for row in accepted_rows:
            uploaded_identity_keys.add(
                build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            )

        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        not_sent_where = where_not_sent_or_forced_sql(cap)

        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                {logistics_sql},
                {processing_sql},
                status,
                batch_date
            FROM orders_staging
            WHERE {not_sent_where}
            AND (
                batch_date IS NULL
                OR batch_date < %s
            )
        """, (batch["batch_date"],))
        staging_rows = cursor.fetchall()

        forced_pending = 0
        moved_to_final = 0
        for row in staging_rows:
            identity_key = build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            if identity_key in uploaded_identity_keys:
                continue

            row_processing = (row.get("processing_status") or row.get("status") or "").upper()
            if row_processing == "PROCESSED":
                cursor.execute("""
                    INSERT INTO orders_final
                    (
                        date_clean,
                        name_clean,
                        weight_num,
                        service_type,
                        rush_type,
                        cleaned_by,
                        cleaned_at,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                """, (
                    row["date_clean"],
                    row["name_clean"],
                    row["weight_num"],
                    row["service_type"],
                    row["rush_type"],
                    "SYSTEM_FORCE"
                ))
                cursor.execute("DELETE FROM orders_staging WHERE id = %s", (row["id"],))
                moved_to_final += 1
            else:
                set_parts = []
                if cap["has_logistics"]:
                    set_parts.append("logistics_status = 'FORCE_CHECKOUT'")
                if cap["has_status"]:
                    set_parts.append("status = 'FORCED_CHECKOUT'")
                if not set_parts:
                    set_parts.append("status = 'FORCED_CHECKOUT'")

                cursor.execute(f"""
                    UPDATE orders_staging
                    SET {", ".join(set_parts)}
                    WHERE id = %s
                """, (row["id"],))
                forced_pending += 1

        cursor.execute(f"""
            SELECT date_clean, name_clean, weight_num, service_type
            FROM orders_staging
            WHERE {not_sent_where}
        """)
        current_staging_rows = cursor.fetchall()
        existing_identity_before_insert = set(
            build_identity_key(r["name_clean"], r["weight_num"], r["service_type"], r["date_clean"])
            for r in current_staging_rows
        )

        inserted = 0
        for row in accepted_rows:
            identity_key = build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            if identity_key in existing_identity_before_insert:
                continue

            cols = [
                "date_clean",
                "name_clean",
                "weight_num",
                "service_type",
                "rush_type",
                "batch_date",
            ]
            vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
            args = [
                row["date_clean"],
                row["name_clean"],
                row["weight_num"],
                row["service_type"],
                row["rush_type"],
                batch["batch_date"],
            ]

            if cap["has_logistics"]:
                cols.append("logistics_status")
                vals.append("%s")
                args.append("AT_WASHPRO")
            if cap["has_processing"]:
                cols.append("processing_status")
                vals.append("%s")
                args.append("PENDING")
            if cap["has_status"]:
                cols.append("status")
                vals.append("%s")
                args.append("PENDING")

            cursor.execute(f"""
                INSERT INTO orders_staging
                ({", ".join(cols)})
                VALUES ({", ".join(vals)})
            """, tuple(args))
            inserted += 1

        set_parts = ["state = 'CONFIRMED'"] if table_has_column(cursor, "upload_batches", "state") else []
        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            set_parts.append("confirmed_at = NOW()")
        if table_has_column(cursor, "upload_batches", "closed_at"):
            set_parts.append("closed_at = NOW()")
        if table_has_column(cursor, "upload_batches", "updated_at"):
            set_parts.append("updated_at = NOW()")

        if set_parts:
            cursor.execute(f"""
                UPDATE upload_batches
                SET {", ".join(set_parts)}
                WHERE {batch_pk} = %s
            """, (batch_id,))

        conn.commit()
        return jsonify({
            "status": "batch_confirmed",
            "batch_id": batch_id,
            "inserted_to_staging": inserted,
            "forced_checkout_pending": forced_pending,
            "moved_to_final": moved_to_final
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Upload Conflict Review APIs (legacy)
# ---------------------------------------------------

@app.route("/upload_conflicts", methods=["GET"])
def get_upload_conflicts():

    batch_id = request.args.get("batch_id")
    status = (request.args.get("status") or "PENDING").strip().upper()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_conflicts_pk(cursor)
        if batch_id not in [None, ""]:
            cursor.execute("""
                SELECT
                    {pk} AS id,
                    upload_batch_id,
                    name_clean,
                    weight_num,
                    service_type,
                    date_clean,
                    rush_type,
                    reason,
                    status,
                    created_at
                FROM upload_conflicts
                WHERE upload_batch_id = %s
                AND status = %s
                ORDER BY {pk} ASC
            """.format(pk=pk_col), (int(batch_id), status))
        else:
            cursor.execute("""
                SELECT
                    {pk} AS id,
                    upload_batch_id,
                    name_clean,
                    weight_num,
                    service_type,
                    date_clean,
                    rush_type,
                    reason,
                    status,
                    created_at
                FROM upload_conflicts
                WHERE status = %s
                ORDER BY {pk} ASC
                LIMIT 500
            """.format(pk=pk_col), (status,))

        return jsonify(cursor.fetchall())

    finally:
        cursor.close()
        conn.close()


@app.route("/upload_conflicts/override", methods=["POST"])
def override_upload_conflicts():

    data = request.json or {}
    conflict_ids = data.get("conflict_ids") or []
    overridden_by = (data.get("overridden_by") or "").strip() or "admin"

    if not isinstance(conflict_ids, list) or not conflict_ids:
        return jsonify({"error": "conflict_ids must be a non-empty array"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        pk_col = get_upload_conflicts_pk(cursor)
        cap = orders_status_capabilities(cursor)
        placeholders = ",".join(["%s"] * len(conflict_ids))
        cursor.execute(f"""
            SELECT
                {pk_col} AS id,
                name_clean,
                weight_num,
                service_type,
                date_clean,
                rush_type,
                upload_batch_id
            FROM upload_conflicts
            WHERE {pk_col} IN ({placeholders})
            AND status = 'PENDING'
        """, tuple(conflict_ids))
        rows = cursor.fetchall()

        inserted = 0
        today_batch_date = date.today()

        for row in rows:
            cols = [
                "date_clean",
                "name_clean",
                "weight_num",
                "service_type",
                "rush_type",
                "batch_date",
            ]
            vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
            args = [
                row["date_clean"],
                row["name_clean"],
                row["weight_num"],
                row["service_type"],
                row["rush_type"],
                today_batch_date,
            ]

            if cap["has_logistics"]:
                cols.append("logistics_status")
                vals.append("%s")
                args.append("AT_WASHPRO")
            if cap["has_processing"]:
                cols.append("processing_status")
                vals.append("%s")
                args.append("PENDING")
            if cap["has_status"]:
                cols.append("status")
                vals.append("%s")
                args.append("PENDING")

            cursor.execute(f"""
                INSERT INTO orders_staging
                ({", ".join(cols)})
                VALUES ({", ".join(vals)})
            """, tuple(args))
            inserted += 1

            cursor.execute("""
                UPDATE upload_conflicts
                SET
                    status = 'OVERRIDDEN',
                    overridden_by = %s,
                    overridden_at = NOW()
                WHERE {pk} = %s
            """.format(pk=pk_col), (
                overridden_by,
                row["id"]
            ))

        conn.commit()

        return jsonify({
            "status": "overridden",
            "requested": len(conflict_ids),
            "overridden": inserted
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
# ---------------------------------------------------
# Root Health Endpoint
# ---------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "LaundryOps API",
        "status": "running"
    })
