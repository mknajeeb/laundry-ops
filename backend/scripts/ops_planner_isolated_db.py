"""Isolated MySQL for Operations Planner checks. Not production.

Start the server first:

    mysqld --datadir=/tmp/ops-planner-mysql-data --port=3307 \\
      --socket=/tmp/ops-planner-mysql.sock --bind-address=127.0.0.1 --mysqlx=0

Then: python3 -m backend.scripts.ops_planner_isolated_db
"""

from __future__ import annotations

import pathlib

import mysql.connector

HOST = "127.0.0.1"
PORT = 3307
USER = "root"
DATABASE = "ops_planner_test"
PLANNER_SQL = pathlib.Path(__file__).resolve().parents[1] / "sql" / "operations_planner_v2.sql"

SEED = """
CREATE TABLE IF NOT EXISTS organizations (
  id INT PRIMARY KEY,
  slug VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS users (
  id INT PRIMARY KEY,
  organization_id INT NOT NULL,
  display_name VARCHAR(128) NULL,
  username VARCHAR(64) NULL,
  email VARCHAR(128) NULL,
  active TINYINT NOT NULL DEFAULT 1,
  termination_date DATE NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_profiles (
  user_id INT PRIMARY KEY,
  first_name VARCHAR(64) NULL,
  last_name VARCHAR(64) NULL,
  email VARCHAR(128) NULL,
  date_of_birth DATE NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_worker_profiles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  active TINYINT NOT NULL DEFAULT 1,
  can_work_rinse TINYINT NOT NULL DEFAULT 0,
  can_work_drop_off TINYINT NOT NULL DEFAULT 1,
  can_work_both TINYINT NOT NULL DEFAULT 0,
  business_entity VARCHAR(32) NULL,
  default_hourly_rate DECIMAL(10,2) NULL,
  UNIQUE KEY uq_worker (organization_id, user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS cleaning_task_activities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  responsibility_id INT NOT NULL,
  status VARCHAR(32) NOT NULL,
  parent_activity_id INT NULL,
  activity_kind VARCHAR(32) NULL
) ENGINE=InnoDB;

INSERT INTO organizations (id, slug, name)
VALUES (1, 'washpro', 'Washpro Test')
ON DUPLICATE KEY UPDATE slug=VALUES(slug);

INSERT INTO users (id, organization_id, display_name, username, email, active)
VALUES
  (1, 1, 'Manager Quinn', 'manager', 'manager@example.test', 1),
  (7, 1, 'Amina Cole', 'amina', 'amina@example.test', 1),
  (8, 1, 'Luis Ortega', 'luis', 'luis@example.test', 1),
  (9, 1, 'Priya Shah', 'priya', 'priya@example.test', 1)
ON DUPLICATE KEY UPDATE display_name=VALUES(display_name);

INSERT INTO payroll_profiles (user_id, first_name, last_name, email)
VALUES
  (1, 'Quinn', 'Manager', 'manager@example.test'),
  (7, 'Amina', 'Cole', 'amina@example.test'),
  (8, 'Luis', 'Ortega', 'luis@example.test'),
  (9, 'Priya', 'Shah', 'priya@example.test')
ON DUPLICATE KEY UPDATE first_name=VALUES(first_name);

INSERT INTO payroll_worker_profiles
  (organization_id, user_id, active, can_work_rinse, can_work_drop_off, can_work_both)
VALUES
  (1, 1, 1, 0, 1, 0),
  (1, 7, 1, 0, 1, 0),
  (1, 8, 1, 0, 1, 0),
  (1, 9, 1, 0, 1, 0)
ON DUPLICATE KEY UPDATE active=VALUES(active);
"""


def connect(database: str | None = DATABASE):
    return mysql.connector.connect(
        host=HOST,
        port=PORT,
        user=USER,
        database=database,
        autocommit=False,
    )


def apply_statements(cursor, script: str) -> None:
    pending = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        pending.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(pending).strip().rstrip(";")
            pending = []
            if statement:
                cursor.execute(statement)
                while True:
                    if getattr(cursor, "with_rows", False):
                        cursor.fetchall()
                    nxt = getattr(cursor, "nextset", None)
                    if not nxt or not nxt():
                        break


def prepare() -> None:
    root = connect(database=None)
    root.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    root.commit()
    root.close()
    conn = connect()
    cursor = conn.cursor()
    apply_statements(cursor, PLANNER_SQL.read_text(encoding="utf-8"))
    from backend.weekly_schedule_roles import ensure_weekly_schedule_roles_table

    ensure_weekly_schedule_roles_table(cursor)
    short_code_sql = PLANNER_SQL.parent / "weekly_schedule_roles_short_code_v1.sql"
    apply_statements(cursor, short_code_sql.read_text(encoding="utf-8"))
    apply_statements(cursor, SEED)
    cursor.execute(
        """
        INSERT INTO ops_planner_org_flags (organization_id, manager_pilot, employee_pilot, paystub_access)
        VALUES (1, 1, 1, 0)
        ON DUPLICATE KEY UPDATE manager_pilot=1, employee_pilot=1, paystub_access=0
        """
    )
    cursor.execute(
        """
        INSERT INTO ops_planner_employee_access
          (organization_id, user_id, schedule_enabled, hours_enabled, paystub_enabled)
        VALUES (1, 7, 1, 1, 0)
        ON DUPLICATE KEY UPDATE schedule_enabled=1, hours_enabled=1
        """
    )
    conn.commit()
    cursor.close()
    conn.close()


def build_app():
    """Authenticated manager routes against the local ops_planner_test database."""
    from flask import Flask

    from backend.operations_planner_v2_routes import register_operations_planner_v2_routes
    from backend.scripts import ops_planner_isolated_db as db

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "ops-planner-isolated-test"

    def get_db():
        return db.connect()

    def require_user(_cursor):
        return {"user_id": 1, "id": 1, "organization_id": 1, "roles": ["ADMIN", "OPS"]}, None, None

    import backend.db as backend_db
    import backend.operations_planner_v2_routes as routes

    backend_db.get_db = get_db
    routes.get_db = get_db
    register_operations_planner_v2_routes(
        app,
        require_user=require_user,
        require_admin=require_user,
        require_admin_or_ops=require_user,
        user_org_id=lambda me: int(me["organization_id"]),
    )

    @app.get("/health")
    def health():
        return {"ok": True, "database": DATABASE, "host": HOST, "port": PORT}

    @app.get("/rinse/shift-analysis/weekly-schedule")
    def isolated_weekly_schedule():
        from datetime import date

        from flask import jsonify, request

        from backend.business_time import business_today
        from backend.rinse_scan_time import json_safe_rinse
        from backend.rinse_shift_analysis_routes import _display_week_payload
        from backend.weekly_schedule_week import (
            current_schedule_monday,
            parse_schedule_date,
            schedule_monday_containing,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            raw_week = (request.args.get("week_start") or "").strip()
            if not raw_week:
                week_start = current_schedule_monday(business_today())
            else:
                parsed_week = parse_schedule_date(raw_week)
                week_start = schedule_monday_containing(parsed_week) if parsed_week else None
            if not isinstance(week_start, date):
                return jsonify({"error": "week_start must be YYYY-MM-DD"}), 400
            payload = _display_week_payload(conn, cursor, 1, week_start, ["ADMIN", "OPS"])
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    return app


def serve() -> None:
    prepare()
    build_app().run(host="127.0.0.1", port=8000, debug=False)


if __name__ == "__main__":
    serve()
