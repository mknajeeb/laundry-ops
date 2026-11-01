#!/usr/bin/env python3
"""Local MySQL validation for Activity checklist responsibility.

Refuses Azure/production hosts. Uses the Flask routes against laundryapp_task_validation.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
os.environ.setdefault("MYSQL_PORT", "3307")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "taskval")
os.environ.setdefault("MYSQL_DATABASE", "laundryapp_task_validation")
os.environ.setdefault("FLASK_SECRET_KEY", "local-task-validation")

HOST = os.environ["MYSQL_HOST"]
if "azure" in HOST or HOST.endswith("database.azure.com"):
    raise SystemExit(f"Refusing to run against {HOST}")

sys.path.insert(0, str(ROOT))

import mysql.connector
from werkzeug.security import generate_password_hash

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def connect():
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        autocommit=True,
    )


def bootstrap() -> None:
    admin = mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
    )
    admin_cur = admin.cursor()
    admin_cur.execute("DROP DATABASE IF EXISTS laundryapp_task_validation")
    admin_cur.execute(
        "CREATE DATABASE laundryapp_task_validation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    admin.close()
    password = generate_password_hash("taskval-pass")
    pin_alex = generate_password_hash("1111")
    pin_sam = generate_password_hash("2222")
    pin_mgr = generate_password_hash("3333")
    conn = connect()
    cur = conn.cursor()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS organizations (
          id INT PRIMARY KEY,
          slug VARCHAR(64) NOT NULL,
          display_name VARCHAR(200) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          code VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(100) NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
          id INT PRIMARY KEY,
          username VARCHAR(100) NOT NULL UNIQUE,
          password_hash VARCHAR(255) NOT NULL,
          display_name VARCHAR(150) NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          organization_id INT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_roles (
          user_id INT NOT NULL,
          role_id INT NOT NULL,
          PRIMARY KEY (user_id, role_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          token VARCHAR(120) NOT NULL UNIQUE,
          expires_at DATETIME NOT NULL,
          revoked TINYINT(1) NOT NULL DEFAULT 0,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payroll_profiles (
          user_id INT PRIMARY KEY,
          first_name VARCHAR(128) NOT NULL,
          last_name VARCHAR(128) NOT NULL,
          email VARCHAR(255) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          password_hash VARCHAR(255) NOT NULL,
          termination_date DATE NULL,
          attendance_pin_hash VARCHAR(255) NULL,
          attendance_pin_last4 VARCHAR(4) NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payroll_worker_profiles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          default_hourly_rate DECIMAL(10,2) NULL,
          can_work_rinse TINYINT(1) NOT NULL DEFAULT 1,
          can_work_drop_off TINYINT(1) NOT NULL DEFAULT 1,
          can_work_both TINYINT(1) NOT NULL DEFAULT 1,
          active TINYINT(1) NOT NULL DEFAULT 1,
          UNIQUE KEY uq_pwp_user (organization_id, user_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_settings (
          organization_id INT NOT NULL,
          skey VARCHAR(128) NOT NULL,
          svalue TEXT NOT NULL,
          PRIMARY KEY (organization_id, skey)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS geofences (
          id INT PRIMARY KEY,
          name VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payroll_cycles (
          id INT PRIMARY KEY,
          cycle_ref VARCHAR(64) NOT NULL,
          week_start_date DATE NOT NULL,
          week_end_date DATE NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'open'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shift_sessions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          payroll_cycle_id INT NOT NULL,
          geofence_id INT NULL,
          clock_in_at DATETIME NOT NULL,
          clock_out_at DATETIME NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shift_breaks (
          id INT AUTO_INCREMENT PRIMARY KEY,
          shift_session_id INT NOT NULL,
          break_start_at DATETIME NOT NULL,
          break_end_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_activity_groups (
          id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          code VARCHAR(40) NOT NULL,
          name VARCHAR(80) NOT NULL,
          category_code VARCHAR(40) NOT NULL,
          display_order INT NOT NULL DEFAULT 0,
          active TINYINT(1) NOT NULL DEFAULT 1,
          instructions TEXT NULL,
          require_checklist_before_completion TINYINT(1) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE KEY uq_tag_org_code (organization_id, code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_activity_group_items (
          id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          group_id INT NOT NULL,
          task_code VARCHAR(64) NOT NULL,
          display_order INT NOT NULL DEFAULT 0,
          required TINYINT(1) NOT NULL DEFAULT 1,
          UNIQUE KEY uq_tagi (group_id, task_code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleaning_task_shared_sessions (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          assignment_group_id VARCHAR(36) NOT NULL,
          business_date DATE NOT NULL,
          role VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL,
          checklist_completed_at DATETIME NULL,
          UNIQUE KEY uq_ctss (organization_id, assignment_group_id, business_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleaning_task_shared_session_items (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shared_session_id BIGINT NOT NULL,
          task_code VARCHAR(64) NOT NULL,
          display_order INT NOT NULL DEFAULT 0,
          required TINYINT(1) NOT NULL DEFAULT 1,
          status VARCHAR(32) NOT NULL,
          completed_at DATETIME NULL,
          completed_by_user_id INT NULL,
          completion_input_json TEXT NULL,
          child_activity_id BIGINT NULL,
          UNIQUE KEY uq_ctssi (shared_session_id, task_code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleaning_task_activity_items (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          activity_id BIGINT NOT NULL,
          task_code VARCHAR(64) NOT NULL,
          display_order INT NOT NULL DEFAULT 0,
          required TINYINT(1) NOT NULL DEFAULT 1,
          status VARCHAR(32) NOT NULL,
          completed_at DATETIME NULL,
          completion_input_json TEXT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS planned_weekly_schedule_responsibilities (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          day_of_week TINYINT NOT NULL,
          role VARCHAR(40) NOT NULL,
          remarks VARCHAR(255) NULL,
          assignment_group_id VARCHAR(36) NULL,
          timing_mode VARCHAR(20) NOT NULL DEFAULT 'anytime',
          start_time TIME NULL,
          execution_mode VARCHAR(20) NOT NULL DEFAULT 'individual',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for stmt in statements:
        cur.execute(stmt)
    cur.execute(
        "INSERT INTO organizations (id, slug, display_name, active) VALUES (3, 'veewash', 'VeeWash', 1)"
    )
    for code, name in (
        ("ADMIN", "Admin"),
        ("MANAGER", "Manager"),
        ("EMPLOYEE", "Employee"),
        ("RINSE", "Rinse"),
    ):
        cur.execute("INSERT INTO roles (code, name) VALUES (%s, %s)", (code, name))
    cur.execute("SELECT id, code FROM roles")
    role_ids = {code: rid for rid, code in cur.fetchall()}
    users = [
        (1, "veewash.admin", "VeeWash Admin", "ADMIN", None, None),
        (2, "alex", "Alex", "EMPLOYEE", pin_alex, "1111"),
        (3, "sam", "Sam", "EMPLOYEE", pin_sam, "2222"),
        (4, "francis", "Francis", "MANAGER", pin_mgr, "3333"),
        (5, "rinse.viewer", "Rinse Viewer", "RINSE", None, None),
        (99, "out.named", "Outsider", "EMPLOYEE", None, None),
    ]
    for uid, username, display, role, pin_hash, last4 in users:
        cur.execute(
            """
            INSERT INTO users (id, username, password_hash, display_name, active, organization_id)
            VALUES (%s, %s, %s, %s, 1, 3)
            """,
            (uid, username, password, display),
        )
        cur.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)", (uid, role_ids[role]))
        first, last = display.split(" ", 1) if " " in display else (display, "User")
        cur.execute(
            """
            INSERT INTO payroll_profiles
              (user_id, first_name, last_name, email, active, password_hash, attendance_pin_hash, attendance_pin_last4)
            VALUES (%s, %s, %s, %s, 1, %s, %s, %s)
            """,
            (uid, first, last, f"{username}@veewash.test", password, pin_hash, last4),
        )
        if uid != 5:
            cur.execute(
                """
                INSERT INTO payroll_worker_profiles
                  (organization_id, user_id, can_work_rinse, can_work_drop_off, can_work_both, active)
                VALUES (3, %s, 0, 1, 0, 1)
                """,
                (uid,),
            )
    clock = json.dumps({"clock": {"shared_device_attendance": True}, "pin_menu": {"enabled": True}})
    cur.execute(
        "INSERT INTO system_settings (organization_id, skey, svalue) VALUES (3, 'clock_payroll_ui_json', %s)",
        (clock,),
    )
    cur.execute("INSERT INTO geofences (id, name) VALUES (1, 'Plant')")
    cur.execute(
        "INSERT INTO payroll_cycles (id, cycle_ref, week_start_date, week_end_date, status) VALUES (1, 'PC-LOCAL', '2026-10-26', '2026-11-01', 'open')"
    )
    now = datetime.now().replace(microsecond=0)
    for uid in (2, 3, 4):
        cur.execute(
            """
            INSERT INTO shift_sessions (user_id, payroll_cycle_id, geofence_id, clock_in_at, status)
            VALUES (%s, 1, 1, %s, 'active')
            """,
            (uid, now),
        )
    cur.execute(
        """
        INSERT INTO task_activity_groups
          (id, organization_id, code, name, category_code, active, instructions)
        VALUES (1, 3, 'historical_closing', 'Historical Closing', 'intra_day', 1, 'Leave the historical note')
        """
    )
    cur.execute(
        """
        INSERT INTO task_activity_group_items (id, organization_id, group_id, task_code, display_order, required)
        VALUES (1, 3, 1, 'historical_floor', 10, 1), (2, 3, 1, 'historical_lint', 20, 1)
        """
    )
    cur.execute(
        """
        INSERT INTO cleaning_task_shared_sessions
          (id, organization_id, assignment_group_id, business_date, role, status, checklist_completed_at)
        VALUES (1, 3, 'hist-group', '2026-10-31', 'agroup_historical_closing', 'checklist_complete', '2026-10-31 18:05:00')
        """
    )
    cur.execute(
        """
        INSERT INTO cleaning_task_shared_session_items
          (id, organization_id, shared_session_id, task_code, display_order, required, status, completed_at, completed_by_user_id, completion_input_json)
        VALUES (1, 3, 1, 'historical_floor', 10, 1, 'completed', '2026-10-31 18:04:00', 2, '{"values":{},"remarks":"historical"}')
        """
    )
    cur.execute(
        """
        INSERT INTO cleaning_task_activity_items
          (id, organization_id, activity_id, task_code, required, status, completed_at, completion_input_json)
        VALUES (1, 3, 50, 'historical_lint', 1, 'completed', '2026-10-31 18:06:00', '{"values":{},"remarks":"kept"}')
        """
    )
    cur.execute(
        """
        INSERT INTO planned_weekly_schedule_responsibilities
          (organization_id, week_start, user_id, day_of_week, role, assignment_group_id, execution_mode)
        VALUES (3, '2026-10-25', 2, 6, 'agroup_historical_closing', 'hist-group', 'shared')
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def snapshot(cur) -> dict:
    out = {}
    cur.execute("SELECT id, name, instructions FROM task_activity_groups WHERE id=1")
    out["group"] = cur.fetchone()
    cur.execute("SELECT id, task_code, required FROM task_activity_group_items WHERE group_id=1 ORDER BY id")
    out["items"] = cur.fetchall()
    cur.execute(
        """
        SELECT id, status, completed_at, completed_by_user_id, completion_input_json
        FROM cleaning_task_shared_session_items WHERE id=1
        """
    )
    out["shared"] = cur.fetchone()
    cur.execute(
        "SELECT id, status, completed_at, completion_input_json FROM cleaning_task_activity_items WHERE id=1"
    )
    out["activity_item"] = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS c FROM planned_weekly_schedule_responsibilities WHERE assignment_group_id='hist-group'")
    out["resp_count"] = cur.fetchone()["c"]
    return out


def main() -> int:
    bootstrap()
    from backend.db import get_db
    from backend.ta_helpers import invalidate_schema_cache
    from backend.task_activity_groups import ensure_task_activity_group_tables

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    before = snapshot(cur)
    ensure_task_activity_group_tables(cur)
    conn.commit()
    invalidate_schema_cache()
    ensure_task_activity_group_tables(cur)
    conn.commit()
    after = snapshot(cur)
    check("historical activity group unchanged", before["group"] == after["group"], str(after["group"]))
    check("historical checklist items unchanged", before["items"] == after["items"])
    check("historical shared check-off unchanged", before["shared"] == after["shared"], str(after["shared"]))
    check("historical activity item unchanged", before["activity_item"] == after["activity_item"])
    check("historical assignment row remains", before["resp_count"] == after["resp_count"] == 1)
    cur.execute(
        """
        SELECT COLUMN_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'task_activity_group_items'
          AND COLUMN_NAME IN ('responsibility_mode', 'responsibility_user_ids_json', 'section_label', 'section_order')
        """
    )
    cols = {row["COLUMN_NAME"] for row in cur.fetchall()}
    check(
        "responsibility columns exist after repeated ensure",
        cols == {"responsibility_mode", "responsibility_user_ids_json", "section_label", "section_order"},
        str(sorted(cols)),
    )
    cur.execute("SELECT responsibility_mode FROM task_activity_group_items WHERE id=1")
    check("existing item defaults to Anyone on Team", (cur.fetchone() or {}).get("responsibility_mode") == "team")
    cur.execute("SHOW TABLES LIKE 'task_activity_item_date_overrides'")
    check("date override table exists", cur.fetchone() is not None)
    cur.close()
    conn.close()

    # Second process start: ensure again and confirm no duplicate-column failure.
    import subprocess

    second = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sys
from pathlib import Path
os.environ.update({
  "MYSQL_HOST":"127.0.0.1","MYSQL_PORT":"3307","MYSQL_USER":"root",
  "MYSQL_PASSWORD":"taskval","MYSQL_DATABASE":"laundryapp_task_validation",
})
sys.path.insert(0, %r)
from backend.db import get_db
from backend.task_activity_groups import ensure_task_activity_group_tables
conn = get_db()
cur = conn.cursor()
ensure_task_activity_group_tables(cur)
ensure_task_activity_group_tables(cur)
conn.commit()
cur.execute("SELECT COUNT(*) FROM task_activity_group_items WHERE id IN (1,2)")
print(cur.fetchone()[0])
conn.close()
"""
            % str(ROOT),
        ],
        capture_output=True,
        text=True,
    )
    check(
        "second application start reapplies migration safely",
        second.returncode == 0 and second.stdout.strip() == "2",
        (second.stderr or second.stdout)[-400:],
    )

    from backend.app import app
    from backend.business_time import business_today
    from backend.planned_weekly_schedule import (
        ensure_planned_weekly_schedule_exclusions_table,
        ensure_planned_weekly_schedule_table,
        normalize_week_start,
    )

    prep = get_db()
    prep_cur = prep.cursor()
    ensure_planned_weekly_schedule_table(prep_cur)
    ensure_planned_weekly_schedule_exclusions_table(prep_cur)
    prep.commit()
    prep_cur.close()
    prep.close()

    today = business_today()
    week = normalize_week_start(today)
    dow = (today.weekday() + 1) % 7
    client = app.test_client()

    def login(username: str):
        res = client.post(
            "/auth/login",
            json={"username": username, "password": "taskval-pass", "organization_slug": "veewash"},
        )
        body = res.get_json(silent=True) or {}
        return res.status_code, body.get("token"), body

    status, admin_token, admin_body = login("veewash.admin")
    check("admin login", status == 200 and bool(admin_token), str(admin_body)[:240])
    admin = {"Authorization": f"Bearer {admin_token}"}

    catalog = client.get("/api/management/task-catalog", headers=admin)
    check("task catalog loads and seeds categories", catalog.status_code == 200, catalog.get_data(as_text=True)[:240])

    def post_task(code, name, **extra):
        payload = {
            "code": code,
            "name": name,
            "category_code": "intra_day",
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_inherits": False,
            "timer_enabled": False,
            **extra,
        }
        return client.post("/api/management/task-catalog/tasks", json=payload, headers=admin)

    tasks = [
        post_task("floor", "Floor broom"),
        post_task("lint", "Dryer lint"),
        post_task("trash", "Trash run"),
        post_task(
            "note",
            "Closing note",
            completion_type="input_required",
            input_schema=[{"id": "note", "type": "text", "label": "Note", "required": False}],
        ),
    ]
    check("create checklist task definitions", all(r.status_code == 200 for r in tasks), str([r.status_code for r in tasks]))
    task_codes = [r.get_json()["task"]["code"] for r in tasks]

    created = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": "Routine Cleaning",
            "category_code": "intra_day",
            "require_checklist_before_completion": True,
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "items": [
                {"task_code": task_codes[0], "responsibility_mode": "team", "required": True},
                {"task_code": task_codes[1], "responsibility_mode": "named", "responsibility_user_ids": [2], "required": True},
                {"task_code": task_codes[2], "responsibility_mode": "named", "responsibility_user_ids": [2, 3], "required": True},
                {"task_code": task_codes[3], "responsibility_mode": "team", "required": True},
            ],
        },
        headers=admin,
    )
    group = (created.get_json(silent=True) or {}).get("activity_group") or {}
    modes = {item["task_code"]: item.get("responsibility_mode") for item in group.get("items") or []}
    named = {item["task_code"]: item.get("responsibility_user_ids") for item in group.get("items") or []}
    check(
        "activity create stores team, one employee, and multiple employees",
        created.status_code == 200
        and modes.get(task_codes[0]) == "team"
        and named.get(task_codes[1]) == [2]
        and named.get(task_codes[2]) == [2, 3],
        created.get_data(as_text=True)[:400],
    )
    edited = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "id": group.get("id"),
            "name": "Routine Cleaning",
            "category_code": "intra_day",
            "require_checklist_before_completion": True,
            "items": [
                {"task_code": task_codes[0], "responsibility_mode": "team", "required": True},
                {"task_code": task_codes[1], "responsibility_mode": "named", "responsibility_user_ids": [2, 3], "required": True},
                {"task_code": task_codes[2], "responsibility_mode": "named", "responsibility_user_ids": [3], "required": True},
                {"task_code": task_codes[3], "responsibility_mode": "team", "required": True},
            ],
        },
        headers=admin,
    )
    edited_group = (edited.get_json(silent=True) or {}).get("activity_group") or {}
    edited_named = {item["task_code"]: item.get("responsibility_user_ids") for item in edited_group.get("items") or []}
    same_ids = [item.get("id") for item in group.get("items") or []] == [item.get("id") for item in edited_group.get("items") or []]
    check(
        "activity edit keeps item ids and updates named employees",
        edited.status_code == 200 and same_ids and edited_named.get(task_codes[1]) == [2, 3],
        edited.get_data(as_text=True)[:400],
    )
    role = edited_group.get("role_code")

    # Restore one-employee lint for the PIN scenario after the edit proof.
    client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "id": group.get("id"),
            "name": "Routine Cleaning",
            "category_code": "intra_day",
            "require_checklist_before_completion": True,
            "items": [
                {"task_code": task_codes[0], "responsibility_mode": "team", "required": True},
                {"task_code": task_codes[1], "responsibility_mode": "named", "responsibility_user_ids": [2], "required": True},
                {"task_code": task_codes[2], "responsibility_mode": "named", "responsibility_user_ids": [2, 3], "required": True},
                {"task_code": task_codes[3], "responsibility_mode": "team", "required": True},
            ],
        },
        headers=admin,
    )

    outsider = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": "Outsider Named",
            "category_code": "intra_day",
            "items": [
                {"task_code": task_codes[1], "responsibility_mode": "named", "responsibility_user_ids": [99], "required": True}
            ],
        },
        headers=admin,
    )
    outsider_group = (outsider.get_json(silent=True) or {}).get("activity_group") or {}
    blocked = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": outsider_group.get("role_code"),
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    blocked_body = blocked.get_json(silent=True) or {}
    check(
        "unscheduled master name blocks the date save",
        blocked.status_code == 409 and blocked_body.get("code") == "item_responsibility",
        blocked.get_data(as_text=True)[:400],
    )
    resolved = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": outsider_group.get("role_code"),
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
            "item_responsibility_overrides": [
                {
                    "group_item_id": (outsider_group.get("items") or [{}])[0].get("id"),
                    "task_code": task_codes[1],
                    "responsibility_mode": "named",
                    "user_ids": [2],
                }
            ],
        },
        headers=admin,
    )
    check("date override resolves the unscheduled name", resolved.status_code == 201, resolved.get_data(as_text=True)[:300])
    master_after = client.get("/api/management/task-catalog", headers=admin).get_json()
    master_item = next(
        item
        for g in master_after.get("activity_groups") or []
        if g.get("id") == outsider_group.get("id")
        for item in g.get("items") or []
    )
    check(
        "master Activity still names the unscheduled employee",
        master_item.get("responsibility_user_ids") == [99],
        str(master_item.get("responsibility_user_ids")),
    )
    db = get_db()
    dbc = db.cursor(dictionary=True)
    dbc.execute(
        """
        SELECT responsibility_mode, user_ids_json, business_date
        FROM task_activity_item_date_overrides
        WHERE group_item_id=%s
        """,
        (master_item["id"],),
    )
    override_row = dbc.fetchone()
    check(
        "date override persists for this date only",
        override_row
        and str(override_row["business_date"])[:10] == (week + timedelta(days=dow)).isoformat()
        and override_row["responsibility_mode"] == "named"
        and json.loads(override_row["user_ids_json"]) == [2],
        str(override_row),
    )

    assigned = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": role,
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    assigned_body = assigned.get_json(silent=True) or {}
    responsibility = assigned_body.get("responsibility") or (assigned_body.get("assigned_tasks") or {}).get("items", [{}])[0]
    if not responsibility and isinstance(assigned_body.get("responsibilities"), list):
        responsibility = next((row for row in assigned_body["responsibilities"] if row.get("role") == role), {})
    resp_id = (responsibility or {}).get("id")
    check("shared activity assigned to Alex and Sam", assigned.status_code == 201 and bool(resp_id), assigned.get_data(as_text=True)[:500])

    reloaded = client.get(
        "/rinse/shift-analysis/weekly-schedule",
        query_string={"week_start": week.isoformat()},
        headers=admin,
    )
    reload_body = reloaded.get_json(silent=True) or {}
    daily = reload_body.get("daily_responsibilities") or reload_body.get("responsibilities") or []
    flat = []
    if isinstance(daily, dict):
        for rows in daily.values():
            if isinstance(rows, list):
                flat.extend(rows)
    elif isinstance(daily, list):
        flat = daily
    found = any(str(row.get("role")) == str(role) for row in flat if isinstance(row, dict))
    check("weekly schedule reload still shows the assignment", reloaded.status_code == 200 and found, reloaded.get_data(as_text=True)[:400])
    outsider_row = next(
        (row for row in flat if isinstance(row, dict) and row.get("role") == outsider_group.get("role_code")),
        {},
    )
    lint_code = ((outsider_group.get("items") or [{}])[0]).get("task_code")
    lint_item = next((item for item in outsider_row.get("checklist_items") or [] if item.get("task_code") == lint_code), {})
    check(
        "reloaded schedule shows the date override, not the master name",
        lint_item.get("date_override") is True and lint_item.get("responsibility_user_ids") == [2],
        str(lint_item),
    )

    # Remove Sam while Dryer lint is only Alex, but Trash names both. Removal of Alex is the block.
    remove = client.put(
        f"/rinse/shift-analysis/weekly-schedule/responsibilities/{resp_id}",
        json={
            "day_of_week": dow,
            "role": role,
            "user_ids": [3],
            "execution_mode": "individual",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    remove_body = remove.get_json(silent=True) or {}
    check(
        "removing an employee with an open named item is blocked",
        remove.status_code == 409 and any(item.get("task_code") == task_codes[1] for item in remove_body.get("items") or []),
        remove.get_data(as_text=True)[:400],
    )
    reassigned = client.put(
        f"/rinse/shift-analysis/weekly-schedule/responsibilities/{resp_id}",
        json={
            "day_of_week": dow,
            "role": role,
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
            "item_responsibility_overrides": [
                {"task_code": task_codes[0], "responsibility_mode": "team", "user_ids": []},
            ],
        },
        headers=admin,
    )
    check("reassignment that keeps the named employee saves", reassigned.status_code == 200, reassigned.get_data(as_text=True)[:240])

    grant = get_db()
    grant_cur = grant.cursor()
    from backend.employee_mobile_pin_access import ensure_employee_mobile_pin_access_tables

    ensure_employee_mobile_pin_access_tables(grant_cur)
    for uid in (2, 3, 4):
        grant_cur.execute(
            """
            INSERT INTO employee_mobile_pin_access (
              organization_id, user_id, allow_clock, allow_switch_role, allow_take_break,
              allow_checklist, allow_inventory, allow_revenue_cost, allow_team_status,
              allow_cleaning_tasks, allow_cleaning_task_review
            ) VALUES (3, %s, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            ON DUPLICATE KEY UPDATE
              allow_cleaning_tasks=1, allow_cleaning_task_review=1
            """,
            (uid,),
        )
    grant.commit()
    grant_cur.close()
    grant.close()

    def pin(path, pin_code, payload):
        return client.post(
            path,
            json={"organization_slug": "veewash", "pin": pin_code, **payload},
        )

    started = pin("/api/public/attendance/pin-cleaning-tasks/start", "1111", {"responsibility_id": resp_id})
    started_body = started.get_json(silent=True) or {}
    activity = started_body.get("activity") or {}
    items = ((activity.get("group") or {}).get("items")) or []
    mine = [item["task_code"] for item in items if item.get("responsibility_mode") != "named" or 2 in (item.get("responsibility_user_ids") or [])]
    other = [item["task_code"] for item in items if item.get("responsibility_mode") == "named" and 2 not in (item.get("responsibility_user_ids") or [])]
    check(
        "employee PIN starts the activity and splits My Items",
        started.status_code == 200 and task_codes[0] in mine and task_codes[1] in mine and activity.get("id"),
        started.get_data(as_text=True)[:500],
    )
    activity_id = activity.get("id")
    noted = pin(
        "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
        "1111",
        {
            "activity_id": activity_id,
            "task_code": task_codes[3],
            "completion_input": {"values": {"note": "Washer 4"}, "remarks": "Left the mop by the door"},
        },
    )
    noted_body = noted.get_json(silent=True) or {}
    noted_item = next(
        (item for item in (((noted_body.get("activity") or {}).get("group") or {}).get("items") or []) if item.get("task_code") == task_codes[3]),
        {},
    )
    check(
        "shared check-off stores remarks and the actual checker",
        noted.status_code == 200
        and noted_item.get("status") == "completed"
        and noted_item.get("completed_by_user_id") == 2
        and (noted_item.get("completion_input") or {}).get("remarks") == "Left the mop by the door",
        noted.get_data(as_text=True)[:500],
    )
    for code in (task_codes[0], task_codes[1], task_codes[2]):
        done = pin(
            "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
            "1111",
            {"activity_id": activity_id, "task_code": code},
        )
        if done.status_code != 200:
            check(f"check off {code}", False, done.get_data(as_text=True)[:300])
            break
    else:
        check("Alex can check off team, own, and shared named items once", True)

    finished_a = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "1111",
        {"activity_id": activity_id},
    )
    check("Alex finishes participation", finished_a.status_code == 200, finished_a.get_data(as_text=True)[:300])
    def own_responsibility(pin_code, role_code):
        listed = pin("/api/public/attendance/pin-cleaning-tasks", pin_code, {})
        body = listed.get_json(silent=True) or {}
        row = next((task for task in body.get("tasks") or [] if task.get("role") == role_code), {})
        return row.get("responsibility_id")

    sam_resp = own_responsibility("2222", role)
    started_b = pin("/api/public/attendance/pin-cleaning-tasks/start", "2222", {"responsibility_id": sam_resp})
    b_activity = (started_b.get_json(silent=True) or {}).get("activity") or {}
    b_items = ((b_activity.get("group") or {}).get("items")) or []
    unchecked_partner = [
        item for item in b_items if item.get("status") != "completed" and item.get("task_code") in task_codes
    ]
    check(
        "partner sees the shared items already checked off",
        started_b.status_code == 200 and not unchecked_partner and any(item.get("completed_by_user_id") == 2 for item in b_items),
        started_b.get_data(as_text=True)[:400],
    )
    finished_b = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "2222",
        {"activity_id": b_activity.get("id")},
    )
    check("Sam finishes participation", finished_b.status_code == 200, finished_b.get_data(as_text=True)[:300])

    review = pin("/api/public/attendance/pin-cleaning-tasks/review", "3333", {"business_date": today.isoformat()})
    review_body = review.get_json(silent=True) or {}
    cards = review_body.get("verification_cards") or []
    card = next((row for row in cards if row.get("role_label") == "Routine Cleaning"), None)
    floor = next((item for item in (card or {}).get("checklist") or [] if "Floor" in str(item.get("task_label"))), None)
    check(
        "supervisor sees one shared checker, not a partner not-checked row",
        review.status_code == 200 and card and floor and floor.get("checked_off") and len(floor.get("records") or []) == 1
        and (floor.get("records") or [{}])[0].get("employee_name") in {"Alex", "Alex User"}
        and floor.get("responsibility_label") == "Anyone on Team",
        json.dumps({"status": review.status_code, "card": card}, default=str)[:700],
    )
    child_id = ((floor or {}).get("records") or [{}])[0].get("activity_id")
    rejected = pin(
        "/api/public/attendance/pin-cleaning-tasks/reject",
        "3333",
        {"activity_ids": [child_id], "reason": "Redo the floor"},
    )
    check("supervisor rejects one checklist item", rejected.status_code == 200, rejected.get_data(as_text=True)[:300])

    approve_group = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": "Approve Path",
            "category_code": "intra_day",
            "require_checklist_before_completion": True,
            "items": [{"task_code": task_codes[0], "responsibility_mode": "team", "required": True}],
        },
        headers=admin,
    )
    approve_role = ((approve_group.get_json(silent=True) or {}).get("activity_group") or {}).get("role_code")
    approve_assigned = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": approve_role,
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    alex_approve = own_responsibility("1111", approve_role)
    sam_approve = own_responsibility("2222", approve_role)
    a2 = pin("/api/public/attendance/pin-cleaning-tasks/start", "1111", {"responsibility_id": alex_approve})
    a2_id = ((a2.get_json(silent=True) or {}).get("activity") or {}).get("id")
    pin("/api/public/attendance/pin-cleaning-tasks/group-checkoff", "1111", {"activity_id": a2_id, "task_code": task_codes[0]})
    pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "1111", {"activity_id": a2_id})
    b2 = pin("/api/public/attendance/pin-cleaning-tasks/start", "2222", {"responsibility_id": sam_approve})
    b2_id = ((b2.get_json(silent=True) or {}).get("activity") or {}).get("id")
    pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "2222", {"activity_id": b2_id})
    review2 = pin("/api/public/attendance/pin-cleaning-tasks/review", "3333", {"business_date": today.isoformat()})
    card2 = next(
        (row for row in (review2.get_json(silent=True) or {}).get("verification_cards") or [] if row.get("role_label") == "Approve Path"),
        {},
    )
    approved = pin(
        "/api/public/attendance/pin-cleaning-tasks/approve",
        "3333",
        {"activity_ids": card2.get("pending_activity_ids") or [], "approve_all": True},
    )
    check(
        "supervisor approves the activity when eligible",
        approved.status_code == 200 and bool(card2.get("can_approve_all")),
        approved.get_data(as_text=True)[:400],
    )

    status_r, rinse_token, rinse_body = login("rinse.viewer")
    check("rinse viewer can log in", status_r == 200 and bool(rinse_token), str(rinse_body)[:200])
    rinse = {"Authorization": f"Bearer {rinse_token}"}
    rinse_put = client.put(
        f"/rinse/shift-analysis/weekly-schedule/responsibilities/{resp_id}",
        json={"day_of_week": dow, "role": role, "user_ids": [2], "timing_mode": "anytime"},
        headers=rinse,
    )
    rinse_group = client.post(
        "/api/management/task-catalog/activity-groups",
        json={"id": group.get("id"), "name": "Hijack", "category_code": "intra_day", "items": [{"task_code": task_codes[0]}]},
        headers=rinse,
    )
    check(
        "rinse viewer cannot change assignments or checklist responsibility",
        rinse_put.status_code == 403 and rinse_group.status_code == 403,
        f"put={rinse_put.status_code} group={rinse_group.status_code} {rinse_put.get_data(as_text=True)[:180]}",
    )
    dbc.close()
    db.close()

    failed = [row for row in RESULTS if not row[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
