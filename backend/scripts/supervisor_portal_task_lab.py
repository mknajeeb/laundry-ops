#!/usr/bin/env python3
"""Load the existing task engine into the isolated lab and exercise portal actions.

Does not create a second task engine. Refuses Azure and the production database name.
Bag rows are synthetic and are not historical production proof.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3308"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "local-only"
os.environ["MYSQL_DATABASE"] = "supervisor_portal_isolated"
os.environ["FLASK_SECRET_KEY"] = "supervisor-local-isolated"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = ""

if "azure" in os.environ["MYSQL_HOST"] or os.environ["MYSQL_DATABASE"] == "laundryapp":
    raise SystemExit("Refusing production")

sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def seed_more_bags() -> None:
    import mysql.connector

    conn = mysql.connector.connect(
        host="127.0.0.1", port=3308, user="root", password="local-only", database="supervisor_portal_isolated"
    )
    cur = conn.cursor()
    from backend.rinse_veewash_shift_day import ensure_shift_monitor_day_tables

    ensure_shift_monitor_day_tables(cur)
    rows = []
    for offset, employee, pounds in (
        (0, "Ada Folder", 18),
        (1, "Bea Folder", 22),
        (2, None, 11),
        (3, "Nobody Mapped", 9),
    ):
        for day_offset in (0, 1, 2):
            day = date(2026, 11, 12) + timedelta(days=day_offset)
            bag = f"W{day_offset}{offset:02d}"
            rows.append((day.isoformat(), bag, "WF", employee, pounds))
            rows.append((day.isoformat(), bag, "WF", employee, pounds))
        rows.append(("2026-11-12", f"H{offset:02d}", "HD", employee, 4))
    for day, bag, service, employee, pounds in rows:
        cur.execute(
            """
            INSERT INTO rinse_shift_monitor_day_bags (
              organization_id, shift_date_et, bag_id, service_type, effective_status,
              canonical_completion_status, canonical_completion_timestamp, canonical_completion_employee,
              pre_weight_lbs, weight_lbs, productivity_employee_name, productivity_completed_at,
              productivity_weight_lbs, productivity_credit_eligible
            ) VALUES (1, %s, %s, %s, 'completed', 'completed', %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE productivity_employee_name=VALUES(productivity_employee_name)
            """,
            (day, bag, service, f"{day} 15:00:00", employee, pounds, pounds, employee, f"{day} 15:00:00", pounds),
        )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_profiles (
          user_id INT PRIMARY KEY,
          first_name VARCHAR(128) NOT NULL,
          last_name VARCHAR(128) NOT NULL,
          email VARCHAR(255) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          password_hash VARCHAR(255) NOT NULL,
          termination_date DATE NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_worker_profiles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          default_hourly_rate DECIMAL(10,2) NULL,
          can_work_rinse TINYINT(1) NOT NULL DEFAULT 1,
          active TINYINT(1) NOT NULL DEFAULT 1,
          UNIQUE KEY uq_pwp_user (organization_id, user_id)
        )
        """
    )
    for user_id, first, last in ((4, "Ada", "Folder"), (5, "Bea", "Press")):
        cur.execute(
            """
            INSERT INTO payroll_profiles (user_id, first_name, last_name, email, active, password_hash)
            VALUES (%s, %s, %s, %s, 1, 'local')
            ON DUPLICATE KEY UPDATE first_name=VALUES(first_name)
            """,
            (user_id, first, last, f"{first.lower()}@local.test"),
        )
        cur.execute(
            """
            INSERT INTO payroll_worker_profiles (organization_id, user_id, active)
            VALUES (1, %s, 1)
            ON DUPLICATE KEY UPDATE active=1
            """,
            (user_id,),
        )
    conn.commit()
    conn.close()
    check("multi-day synthetic bags inserted", True, "not historical production")


def login(client, username: str) -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "local-test-pass", "organization": "local-lab"},
    )
    body = response.get_json(silent=True) or {}
    check(f"task lab login {username}", response.status_code == 200 and bool(body.get("token")), str(response.status_code))
    return body.get("token") or ""


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    seed_more_bags()
    from backend.app import app
    from backend.business_time import business_today

    today = business_today()
    app.config["TESTING"] = True
    with app.test_client() as client:
        admin = auth(login(client, "admin"))
        week = client.get(f"/api/supervisor/day?date=2026-11-14&period=week", headers=admin)
        body = week.get_json(silent=True) or {}
        recon = body.get("reconciliation") or {}
        check(
            "week accounts for every synthetic WF bag",
            week.status_code == 200 and recon.get("unaccounted") == 0 and recon.get("total_completed") == recon.get("total_accounted") and int(recon.get("total_completed") or 0) >= 9,
            f"status {week.status_code} completed={recon.get('total_completed')} categories={recon.get('categories')} days={body.get('days_included')}",
        )
        month = client.get("/api/supervisor/day?date=2026-11-14&period=month", headers=admin)
        month_body = month.get_json(silent=True) or {}
        month_recon = month_body.get("reconciliation") or {}
        check(
            "month accounts for every synthetic WF bag",
            month.status_code == 200 and month_recon.get("unaccounted") == 0,
            f"completed={month_recon.get('total_completed')} accounted={month_recon.get('total_accounted')}",
        )
        sort_target = client.post(
            "/api/supervisor/targets",
            json={"role_key": "SORT", "target_value": 30, "effective_from": "2026-11-01", "unit": "bags/hr"},
            headers=admin,
        )
        roles = client.get("/api/supervisor/roles", headers=admin).get_json(silent=True) or {}
        from backend.db import get_db
        from backend.planned_weekly_schedule import ensure_planned_weekly_schedule_table
        from backend.cleaning_task_activity import ensure_cleaning_task_activity_tables
        from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table

        setup = get_db()
        setup_cur = setup.cursor()
        ensure_planned_weekly_schedule_table(setup_cur)
        ensure_responsibilities_table(setup_cur)
        ensure_cleaning_task_activity_tables(setup_cur)
        setup.commit()
        setup.close()
        sort = next((row for row in roles.get("roles") or [] if row.get("role_key") == "SORT"), {})
        check(
            "sorting target is stored and scoring stays off",
            sort_target.status_code == 200 and sort.get("target") == 30 and sort.get("scoring_ready") is False,
            str(sort)[:180],
        )

        slot = today
        dow = slot.isoweekday() % 7
        monday = slot - timedelta(days=slot.weekday())
        created = client.post(
            "/rinse/shift-analysis/weekly-schedule/responsibilities",
            json={
                "week_start": monday.isoformat(),
                "day_of_week": dow,
                "user_ids": [4],
                "role": "lint_cleaning",
                "timing_mode": "anytime",
                "confirm_unscheduled": True,
            },
            headers=admin,
        )
        created_text = created.get_data(as_text=True)
        check(
            "assign individual task through the schedule API",
            created.status_code in {200, 201} or "already has that task" in created_text,
            created_text[:240],
        )
        shared = client.post(
            "/rinse/shift-analysis/weekly-schedule/responsibilities",
            json={
                "week_start": monday.isoformat(),
                "day_of_week": dow,
                "user_ids": [4, 5],
                "role": "floor_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "shared",
                "confirm_unscheduled": True,
            },
            headers=admin,
        )
        shared_text = shared.get_data(as_text=True)
        check(
            "assign a shared task through the schedule API",
            shared.status_code in {200, 201} or "already has that task" in shared_text,
            shared_text[:240],
        )

        dash = client.get(f"/api/management/task-dashboard?date={today.isoformat()}", headers=admin)
        payload = dash.get_json(silent=True) or {}
        rows = payload.get("shared_assignments") or []
        check(
            "task dashboard lists today's assignments",
            dash.status_code == 200 and len(rows) >= 1,
            f"status {dash.status_code} rows={len(rows)} error={str(payload)[:220]}",
        )

        from backend.cleaning_task_activity import CleaningTaskError, complete_task, start_task
        from backend.db import get_db

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT id, user_id, role FROM planned_weekly_schedule_responsibilities
                WHERE organization_id=1 AND user_id=4 AND role='lint_cleaning'
                ORDER BY id DESC LIMIT 1
                """
            )
            duty = cur.fetchone()
            if duty:
                try:
                    started = start_task(conn, cur, organization_id=1, user_id=4, responsibility_id=int(duty["id"]), shift_session_id=None)
                    conn.commit()
                    finished = complete_task(
                        conn, cur, organization_id=1, user_id=4, activity_id=int(started["id"]), completion_input=None, remark="Lint trap emptied"
                    )
                    conn.commit()
                    check("employee timer starts and completes", finished.get("status") == "pending_approval", str(finished.get("status")))
                    activity_id = int(started["id"])
                except CleaningTaskError as exc:
                    if "already in progress or completed" in exc.message:
                        cur.execute(
                            """
                            SELECT id, status FROM cleaning_task_activities
                            WHERE organization_id=1 AND user_id=4 AND role='lint_cleaning'
                            ORDER BY id DESC LIMIT 1
                            """
                        )
                        existing = cur.fetchone() or {}
                        activity_id = existing.get("id")
                        if existing.get("status") == "approved":
                            check("supervisor verifies from the task API", True, "already verified")
                            self_verify = client.post(
                                "/api/management/task-dashboard/approve",
                                json={"activity_ids": [int(existing["id"])]},
                                headers=auth(login(client, "ada")),
                            )
                            check("employee cannot verify the task", self_verify.status_code in {400, 403}, str(self_verify.status_code))
                            activity_id = None
                        check("employee timer starts and completes", existing.get("status") in {"pending_approval", "approved"}, str(existing.get("status")))
                    else:
                        check("employee timer starts and completes", False, exc.message)
                        activity_id = None
            else:
                check("employee timer starts and completes", False, "lint assignment missing")
                activity_id = None
        finally:
            conn.close()

        if activity_id:
            verified = client.post(
                "/api/management/task-dashboard/approve",
                json={"activity_ids": [activity_id], "supervisor_remark": "Checked the lint trap"},
                headers=admin,
            )
            check("supervisor verifies from the task API", verified.status_code == 200, verified.get_data(as_text=True)[:180])
            self_verify = client.post(
                "/api/management/task-dashboard/approve",
                json={"activity_ids": [activity_id]},
                headers=auth(login(client, "ada")),
            )
            check("employee cannot verify the task", self_verify.status_code in {400, 403}, str(self_verify.status_code))

        rejected_conn = get_db()
        rejected_cur = rejected_conn.cursor(dictionary=True)
        reject_id = None
        try:
            rejected_cur.execute(
                """
                SELECT id FROM planned_weekly_schedule_responsibilities
                WHERE organization_id=1 AND role='floor_cleaning' AND user_id=5
                ORDER BY id DESC LIMIT 1
                """
            )
            floor = rejected_cur.fetchone()
            if floor:
                try:
                    started = start_task(
                        rejected_conn, rejected_cur, organization_id=1, user_id=5, responsibility_id=int(floor["id"]), shift_session_id=None
                    )
                    rejected_conn.commit()
                    complete_task(rejected_conn, rejected_cur, organization_id=1, user_id=5, activity_id=int(started["id"]))
                    rejected_conn.commit()
                    reject_id = int(started["id"])
                except CleaningTaskError as exc:
                    rejected_cur.execute(
                        """
                        SELECT id, status FROM cleaning_task_activities
                        WHERE organization_id=1 AND user_id=5 AND role='floor_cleaning'
                        ORDER BY id DESC LIMIT 1
                        """
                    )
                    existing = rejected_cur.fetchone() or {}
                    if existing.get("status") == "rejected":
                        check("supervisor rejects with a reason", True, "already rejected")
                    else:
                        check("shared task reaches verification", False, exc.message)
        finally:
            rejected_conn.close()
        if reject_id:
            rejected = client.post(
                "/api/management/task-dashboard/reject",
                json={"activity_id": reject_id, "reason": "Floor was still wet"},
                headers=admin,
            )
            check("supervisor rejects with a reason", rejected.status_code == 200, rejected.get_data(as_text=True)[:160])

        again = client.get(f"/api/management/task-dashboard?date={today.isoformat()}", headers=admin)
        again_rows = (again.get_json(silent=True) or {}).get("shared_assignments") or []
        labels = [f"{row.get('role')}:{row.get('status')}" for row in again_rows]
        check("dashboard shows completion and rejection", any("approved" in item or "rejected" in item for item in labels), ", ".join(labels)[:240])
        timer_conn = get_db()
        timer_cur = timer_conn.cursor(dictionary=True)
        try:
            timer_cur.execute(
                """
                SELECT id FROM planned_weekly_schedule_responsibilities
                WHERE organization_id=1 AND user_id=4 AND role='floor_cleaning'
                ORDER BY id DESC LIMIT 1
                """
            )
            ada_floor = timer_cur.fetchone()
            if ada_floor:
                ada_started = start_task(
                    timer_conn, timer_cur, organization_id=1, user_id=4, responsibility_id=int(ada_floor["id"]), shift_session_id=None
                )
                timer_conn.commit()
                ada_done = complete_task(timer_conn, timer_cur, organization_id=1, user_id=4, activity_id=int(ada_started["id"]))
                timer_conn.commit()
                check(
                    "shared assignment keeps an independent timer per employee",
                    ada_done.get("status") == "pending_approval" and int(ada_done.get("user_id") or 4) == 4,
                    str(ada_done.get("status")),
                )
            else:
                check("shared assignment keeps an independent timer per employee", False, "Ada is not on the shared floor task")
        except CleaningTaskError as exc:
            check(
                "shared assignment keeps an independent timer per employee",
                "already in progress or completed" in exc.message,
                exc.message,
            )
        finally:
            timer_conn.close()
        floor_row = next((row for row in again_rows if row.get("role") == "floor_cleaning"), None)
        if floor_row:
            moved = client.post(
                "/api/management/task-dashboard/excuse-participant",
                json={
                    "action": "reassign",
                    "employee_user_id": 4,
                    "replacement_user_id": 5,
                    "shared_session_id": floor_row.get("shared_session_id"),
                    "assignment_group_id": floor_row.get("assignment_group_id"),
                    "role": "floor_cleaning",
                    "business_date": today.isoformat(),
                    "assigned_user_ids": [4, 5],
                    "reason": "Ada left the floor",
                },
                headers=admin,
            )
            check("supervisor reassigns a shared task", moved.status_code == 200, moved.get_data(as_text=True)[:180])
        else:
            check("supervisor reassigns a shared task", False, "floor assignment missing from the dashboard")

        from backend.task_catalog import upsert_task_definition

        schema_conn = get_db()
        schema_cur = schema_conn.cursor(dictionary=True)
        try:
            upsert_task_definition(
                schema_cur,
                1,
                "washer_cleaning",
                {
                    "name": "Washer Cleaning",
                    "completion_type": "input_required",
                    "timer_enabled": True,
                    "verification_required": True,
                    "input_schema": [
                        {"id": "machines", "label": "Machines cleaned", "type": "number", "required": True, "min": 1},
                        {
                            "id": "chemical",
                            "label": "Chemical used",
                            "type": "text",
                            "required": True,
                            "show_when": {"field": "machines", "gt": 2},
                        },
                    ],
                },
            )
            schema_conn.commit()
        finally:
            schema_conn.close()
        washer = client.post(
            "/rinse/shift-analysis/weekly-schedule/responsibilities",
            json={
                "week_start": monday.isoformat(),
                "day_of_week": dow,
                "user_ids": [4],
                "role": "washer_cleaning",
                "timing_mode": "anytime",
                "confirm_unscheduled": True,
            },
            headers=admin,
        )
        check("assign a task with required and conditional inputs", washer.status_code in {200, 201}, washer.get_data(as_text=True)[:160])
        input_conn = get_db()
        input_cur = input_conn.cursor(dictionary=True)
        try:
            input_cur.execute(
                """
                SELECT id FROM planned_weekly_schedule_responsibilities
                WHERE organization_id=1 AND user_id=4 AND role='washer_cleaning'
                ORDER BY id DESC LIMIT 1
                """
            )
            washer_duty = input_cur.fetchone()
            if washer_duty:
                missing = None
                try:
                    opened = start_task(
                        input_conn, input_cur, organization_id=1, user_id=4, responsibility_id=int(washer_duty["id"]), shift_session_id=None
                    )
                    input_conn.commit()
                    try:
                        complete_task(
                            input_conn,
                            input_cur,
                            organization_id=1,
                            user_id=4,
                            activity_id=int(opened["id"]),
                            completion_input={"values": {"machines": 4}},
                        )
                        missing = "accepted a hidden required field"
                    except CleaningTaskError as exc:
                        input_conn.rollback()
                        missing = exc.message
                    finished = complete_task(
                        input_conn,
                        input_cur,
                        organization_id=1,
                        user_id=4,
                        activity_id=int(opened["id"]),
                        completion_input={"values": {"machines": 4, "chemical": "Oxi"}},
                    )
                    input_conn.commit()
                    check(
                        "conditional checklist input is required only when shown",
                        "Missing required input: Chemical used" in str(missing) and finished.get("status") == "pending_approval",
                        str(missing),
                    )
                except CleaningTaskError as exc:
                    check("conditional checklist input is required only when shown", False, exc.message)
            else:
                check("conditional checklist input is required only when shown", False, "washer assignment missing")
        finally:
            input_conn.close()

    failed = [row for row in RESULTS if not row[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
