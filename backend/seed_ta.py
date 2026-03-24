"""
Create default admin user if none exists. Run after schema_ta.sql is applied.

Usage:
  MYSQL_PASSWORD=... python backend/seed_ta.py

Optional env:
  TA_ADMIN_EMAIL  (default admin@laundry.local)
  TA_ADMIN_PASSWORD (default ChangeMeNow!)
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db import get_db
from backend.ta_helpers import hash_password


def main():
    email = os.getenv("TA_ADMIN_EMAIL", "admin@laundry.local")
    password = os.getenv("TA_ADMIN_PASSWORD", "ChangeMeNow!")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            print(f"User {email} already exists — skipping.")
            return

        cur.execute("SELECT id FROM roles WHERE code='ADMIN' LIMIT 1")
        row = cur.fetchone()
        if not row:
            print("ADMIN role missing — run schema_ta.sql first.")
            sys.exit(1)

        role_id = row["id"]
        ph = hash_password(password)

        cur.execute(
            """
            INSERT INTO users (
              employee_id, first_name, last_name, email, hire_date,
              active, role_id, password_hash
            ) VALUES (%s,%s,%s,%s,CURDATE(),1,%s,%s)
            """,
            ("ADM001", "System", "Admin", email, role_id, ph),
        )

        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        uid = cur.fetchone()["id"]

        cur.execute("SELECT id FROM geofences WHERE active=1 ORDER BY id LIMIT 1")
        geo = cur.fetchone()
        if geo:
            cur.execute(
                "INSERT INTO user_geofences (user_id, geofence_id, is_primary) VALUES (%s,%s,1)",
                (uid, geo["id"]),
            )

        cur.execute("SELECT id FROM employment_categories WHERE active=1 ORDER BY id LIMIT 1")
        ec = cur.fetchone()
        if ec:
            cur.execute(
                """
                INSERT INTO user_employment_categories (user_id, employment_category_id, effective_from)
                VALUES (%s,%s,CURDATE())
                """,
                (uid, ec["id"]),
            )

        conn.commit()
        print(f"Created admin user {email} (assign geofence coordinates if needed).")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
