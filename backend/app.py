import os
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

                CASE
                    WHEN date_clean < CURDATE() THEN 'RUSH'
                    ELSE 'NON-RUSH'
                END AS rush_type,

                status,
                created_at

            FROM orders_staging

            ORDER BY date_clean ASC, id ASC

        """)

        orders = cursor.fetchall()

        return jsonify(orders)

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

                SUM(service_type = 'WF') AS wf_total,
                SUM(service_type = 'HD') AS hd_total,

                SUM(service_type = 'WF' AND date_clean < CURDATE()) AS wf_rush,
                SUM(service_type = 'WF' AND date_clean >= CURDATE()) AS wf_non_rush,

                SUM(service_type = 'HD' AND date_clean < CURDATE()) AS hd_rush,
                SUM(service_type = 'HD' AND date_clean >= CURDATE()) AS hd_non_rush

            FROM orders_staging

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

        batch_date = date.today()

        cursor.execute("""

            SELECT
                name_clean,
                weight_num,
                service_type

            FROM orders_final

            WHERE cleaned_at >= NOW() - INTERVAL 2 DAY

        """)

        recent_final_rows = cursor.fetchall()

        recent_final_fingerprints = set(

            build_fingerprint(
                r["name_clean"],
                r["weight_num"],
                r["service_type"]
            )

            for r in recent_final_rows

        )

        cursor.execute("DELETE FROM orders_staging")

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

        for _, row in orders_df.iterrows():

            date_clean = row.get("Date_Clean")
            name_clean = row.get("Name_Clean")
            weight_num = row.get("Weight_Num")
            service_type = row.get("ServiceType")
            rush_type = row.get("RushType")

            if pd.isna(date_clean) or pd.isna(name_clean):
                continue

            if pd.isna(weight_num):
                weight_num = None

            fingerprint = row.get("fingerprint")

            if fingerprint in recent_final_fingerprints:

                conflicts.append({
                    "name": name_clean,
                    "weight": weight_num,
                    "service": service_type,
                    "date": str(date_clean),
                    "action_needed": "review"
                })

                continue

            cursor.execute(insert_query, (

                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                batch_date

            ))

            inserted += 1

        cursor.execute("""

            INSERT INTO upload_batches
            (file_name, batch_date, orders_loaded)

            VALUES (%s, %s, %s)

        """, (

            file.filename,
            batch_date,
            inserted

        ))

        conn.commit()

        return jsonify({

            "status": "uploaded",
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
# Run Server
# ---------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)  
    