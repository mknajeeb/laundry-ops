import os
import pandas as pd
from datetime import datetime, date

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from backend.db import get_db
from backend.ta_routes import register_ta_routes
from etl.transform_orders import transform_orders

load_dotenv()

# ---------------------------------------------------
# Flask App Setup
# ---------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-for-production")
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

register_ta_routes(app)


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

            WHERE status != 'CHECKED_OUT'

            ORDER BY date_clean ASC, id ASC

        """)

        orders = cursor.fetchall()

        return jsonify(orders)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# CHECKOUT SINGLE ORDER
# ---------------------------------------------------

@app.route("/checkout", methods=["POST"])
def checkout_order():

    data = request.json

    order_id = data.get("order_id")
    employee = data.get("employee")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""

            SELECT
                id,
                name_clean,
                weight_num,
                service_type,
                date_clean

            FROM orders_staging
            WHERE id=%s

        """, (order_id,))

        order = cursor.fetchone()

        if not order:
            return jsonify({"error": "Order not found"}), 404


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

            VALUES (%s,%s,%s,%s,%s,%s)

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
            SET status='CHECKED_OUT'
            WHERE id=%s

        """, (order_id,))

        conn.commit()

        return jsonify({"status": "checked_out"})

    except Exception as e:

        conn.rollback()

        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# BULK CHECKOUT
# ---------------------------------------------------

@app.route("/checkout_bulk", methods=["POST"])
def checkout_bulk():

    data = request.json

    order_ids = data.get("order_ids", [])
    employee = data.get("employee")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        for oid in order_ids:

            cursor.execute("""

                SELECT
                    id,
                    name_clean,
                    weight_num,
                    service_type,
                    date_clean

                FROM orders_staging
                WHERE id=%s

            """, (oid,))

            order = cursor.fetchone()

            if not order:
                continue

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

                VALUES (%s,%s,%s,%s,%s,%s)

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
                SET status='CHECKED_OUT'
                WHERE id=%s

            """, (oid,))


        conn.commit()

        return jsonify({"status": "bulk_checkout_complete"})

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

            WHERE status != 'CHECKED_OUT'

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
# Root Health Endpoint
# ---------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "LaundryOps API",
        "status": "running"
    })


# ---------------------------------------------------
# Run Server
# ---------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5001)