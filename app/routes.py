from flask import jsonify
from app.db import get_db_connection

def get_orders():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM orders ORDER BY id DESC")

    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return orders