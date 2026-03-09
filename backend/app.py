import os
import math
import pandas as pd
from datetime import datetime, date

from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector

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
        return ""

    try:
        n = float(weight_num)
    except Exception:
        return ""

    if service == "HD":
        return str(int(round(n)))

    return f"{round(n, 2):.2f}"


def build_identity_key(name_clean, weight_num, service_type):
    return "|".join([
        normalize_name(name_clean),
        normalize_measure_by_service(weight_num, service_type),
        (service_type or "").strip().upper()
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


# ---------------------------------------------------
# Get Active Orders
# ---------------------------------------------------

@app.route("/orders", methods=["GET"])
def get_orders():

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
                batch_date,

                CASE
                    WHEN date_clean < CURDATE() THEN 'RUSH'
                    ELSE 'NON-RUSH'
                END AS rush_type,

                status,
                created_at

            FROM orders_staging
            WHERE status <> 'CHECKED_OUT'

            ORDER BY date_clean ASC, id ASC

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

        cursor.execute("""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                status
            FROM orders_staging
            WHERE id = %s
        """, (order_id,))

        order = cursor.fetchone()

        if not order:
            return jsonify({"error": "Order not found"}), 404

        if (order.get("status") or "").upper() == "CHECKED_OUT":
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

        cursor.execute("""
            UPDATE orders_staging
            SET status = 'CHECKED_OUT'
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

        format_strings = ",".join(["%s"] * len(order_ids))
        cursor.execute(f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
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

            if (row.get("status") or "").upper() == "CHECKED_OUT":
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
            cursor.execute(f"""
                UPDATE orders_staging
                SET status = 'CHECKED_OUT'
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

        cursor.execute("""
            UPDATE orders_staging
            SET status = 'PROCESSED'
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

        cursor.execute("""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type
            FROM orders_staging
            WHERE id = %s
        """, (order_id,))

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
# Dashboard Stats
# ---------------------------------------------------

@app.route("/dashboard", methods=["GET"])
def dashboard():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""

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
            WHERE status <> 'CHECKED_OUT'

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

        # Create batch first so conflicts can be tied to it
        cursor.execute("""
            INSERT INTO upload_batches
            (file_name, batch_date, orders_loaded)
            VALUES (%s, %s, %s)
        """, (
            file.filename,
            batch_date,
            0
        ))
        upload_batch_id = cursor.lastrowid

        # Build existing identity index from current active staging + final
        cursor.execute("""
            SELECT
                name_clean,
                weight_num,
                service_type
            FROM orders_staging
            WHERE status <> 'CHECKED_OUT'
        """)
        staging_rows = cursor.fetchall()

        cursor.execute("""
            SELECT
                name_clean,
                weight_num,
                service_type
            FROM orders_final
        """)
        final_rows = cursor.fetchall()

        existing_identity_keys = set()

        for r in staging_rows + final_rows:
            existing_identity_keys.add(
                build_identity_key(
                    r.get("name_clean"),
                    r.get("weight_num"),
                    r.get("service_type")
                )
            )

        insert_query = """

            INSERT INTO orders_staging
            (
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                status,
                batch_date
            )

            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)

        """

        inserted = 0
        conflicts = []
        seen_in_upload = set()

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

            # New rush logic:
            # 1) Explicit TODAY/RUSH markers remain RUSH
            # 2) Any row with date matching current batch_date is also RUSH
            row_date = date_clean if isinstance(date_clean, date) else parse_date_value(date_clean)
            is_batch_date_rush = (row_date == batch_date)
            rush_type = "RUSH" if (str(rush_type_raw).upper() == "RUSH" or is_batch_date_rush) else "NON-RUSH"

            identity_key = build_identity_key(name_clean, weight_num, service_type)

            if identity_key in seen_in_upload:
                conflicts.append({
                    "name": name_clean,
                    "weight": weight_num,
                    "service": service_type,
                    "date": str(date_clean),
                    "action_needed": "review",
                    "reason": "DUPLICATE_IN_UPLOAD",
                    "batch_id": upload_batch_id
                })

                cursor.execute("""
                    INSERT INTO upload_conflicts
                    (
                        upload_batch_id,
                        name_clean,
                        weight_num,
                        service_type,
                        date_clean,
                        rush_type,
                        reason,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
                """, (
                    upload_batch_id,
                    name_clean,
                    weight_num,
                    service_type,
                    row_date,
                    rush_type,
                    "DUPLICATE_IN_UPLOAD"
                ))

                continue

            if identity_key in existing_identity_keys:

                conflicts.append({
                    "name": name_clean,
                    "weight": weight_num,
                    "service": service_type,
                    "date": str(date_clean),
                    "action_needed": "review",
                    "reason": "MATCH_FOUND_IN_DB",
                    "batch_id": upload_batch_id
                })

                cursor.execute("""
                    INSERT INTO upload_conflicts
                    (
                        upload_batch_id,
                        name_clean,
                        weight_num,
                        service_type,
                        date_clean,
                        rush_type,
                        reason,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
                """, (
                    upload_batch_id,
                    name_clean,
                    weight_num,
                    service_type,
                    row_date,
                    rush_type,
                    "MATCH_FOUND_IN_DB"
                ))

                continue

            cursor.execute(insert_query, (

                row_date,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                batch_date

            ))

            inserted += 1
            seen_in_upload.add(identity_key)
            existing_identity_keys.add(identity_key)

        cursor.execute("""
            UPDATE upload_batches
            SET orders_loaded = %s
            WHERE id = %s
        """, (
            inserted,
            upload_batch_id
        ))

        conn.commit()

        return jsonify({

            "status": "uploaded",
            "batch_id": upload_batch_id,
            "rows_inserted": inserted,
            "conflicts": len(conflicts),
            "conflict_rows": conflicts,
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

        cursor.execute("""

            INSERT INTO orders_staging
            (
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                status,
                batch_date
            )

            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)

        """, (

            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            batch_date

        ))

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

    data = request.json

    order_id = data["order_id"]
    washer_id = data["washer_employee_id"]
    folder_id = data["folder_employee_id"]
    end_time = data["fold_end_time"]
    pieces = data["pieces"]
    issue = data["issue_type"]
    rinse_case = data["rinse_case_id"]

    conn = get_db()
    cursor = conn.cursor()

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
        end_time,
        pieces,
        issue,
        rinse_case
    ))

    cursor.execute("""

        UPDATE orders_staging
        SET status='PROCESSED'
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
# Upload Conflict Review APIs
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
            cursor.execute("""
                INSERT INTO orders_staging
                (
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    status,
                    batch_date
                )
                VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)
            """, (
                row["date_clean"],
                row["name_clean"],
                row["weight_num"],
                row["service_type"],
                row["rush_type"],
                today_batch_date
            ))
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
