#!/usr/bin/env python3
"""Release validation for Lost & Found against an isolated local database.

Refuses any host other than localhost and the production database name.
Does not push, migrate, or deploy.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from datetime import timedelta

os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3307"
os.environ["MYSQL_USER"] = "lf"
os.environ["MYSQL_PASSWORD"] = "lfpass"
os.environ["MYSQL_DATABASE"] = "lost_found_isolated"
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "3307"
os.environ["DB_USER"] = "lf"
os.environ["DB_PASSWORD"] = "lfpass"
os.environ["DB_NAME"] = "lost_found_isolated"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = ""
os.environ["LOST_FOUND_MEDIA_ROOT"] = "/tmp/lf-media"
os.environ["FLASK_SECRET_KEY"] = "lost-found-isolated-validation"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)

RESULTS: dict = {}


def fail(step: str, detail: str) -> None:
    RESULTS.setdefault("failures", []).append({"step": step, "detail": detail})
    print(f"FAIL {step}: {detail}", file=sys.stderr)


def check(step: str, ok: bool, detail: str = "") -> None:
    RESULTS.setdefault("checks", []).append({"step": step, "ok": bool(ok), "detail": detail})
    print(("OK " if ok else "FAIL ") + step + (f" — {detail}" if detail else ""))
    if not ok:
        RESULTS.setdefault("failures", []).append({"step": step, "detail": detail})


def main() -> int:
    from werkzeug.security import generate_password_hash

    from backend.business_time import business_today
    from backend.db import get_db
    from backend.lost_found import ACTIVITY_CODE, prepare_lost_found_schema
    from backend.planned_weekly_schedule import ensure_planned_weekly_schedule_table
    from backend.planned_weekly_schedule_responsibilities import (
        create_responsibility,
        ensure_responsibilities_table,
    )
    from backend.task_catalog import ensure_task_catalog_tables, list_task_definitions

    import mysql.connector

    admin = mysql.connector.connect(
        host="127.0.0.1",
        port=3307,
        user="lf",
        password="lfpass",
    )
    admin_cur = admin.cursor()
    admin_cur.execute("DROP DATABASE IF EXISTS lost_found_isolated")
    admin_cur.execute("CREATE DATABASE lost_found_isolated")
    admin.commit()
    admin.close()

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    day = business_today()
    week = day - timedelta(days=(day.weekday() + 1) % 7)
    dow = (day.weekday() + 1) % 7
    pin_hash = generate_password_hash("2468")
    password_hash = generate_password_hash("supervisor-pass")
    ui = json.dumps(
        {
            "clock": {"shared_device_attendance": True},
            "pin_menu": {"enabled": True, "allow_clock_from_hub": True, "features": {}},
        }
    )

    statements = [
        """
        CREATE TABLE organizations (
          id INT PRIMARY KEY,
          slug VARCHAR(64) NOT NULL,
          display_name VARCHAR(160) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE users (
          id INT PRIMARY KEY,
          username VARCHAR(80) NOT NULL,
          password_hash VARCHAR(255) NOT NULL,
          display_name VARCHAR(160) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          organization_id INT NOT NULL
        )
        """,
        """
        CREATE TABLE roles (
          id INT PRIMARY KEY,
          code VARCHAR(40) NOT NULL
        )
        """,
        """
        CREATE TABLE user_roles (
          user_id INT NOT NULL,
          role_id INT NOT NULL,
          PRIMARY KEY (user_id, role_id)
        )
        """,
        """
        CREATE TABLE payroll_profiles (
          user_id INT PRIMARY KEY,
          first_name VARCHAR(80) NULL,
          last_name VARCHAR(80) NULL,
          attendance_pin_hash VARCHAR(255) NULL,
          attendance_pin_last4 VARCHAR(4) NULL,
          termination_date DATE NULL
        )
        """,
        """
        CREATE TABLE system_settings (
          organization_id INT NOT NULL,
          skey VARCHAR(120) NOT NULL,
          svalue TEXT NULL,
          PRIMARY KEY (organization_id, skey)
        )
        """,
        """
        CREATE TABLE shift_sessions (
          id INT PRIMARY KEY,
          user_id INT NOT NULL,
          organization_id INT NOT NULL,
          status VARCHAR(20) NOT NULL,
          clock_in_at DATETIME NULL,
          clock_out_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE shift_breaks (
          id INT PRIMARY KEY,
          shift_session_id INT NOT NULL,
          break_start_at DATETIME NULL,
          break_end_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE auth_sessions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          token VARCHAR(80) NOT NULL,
          expires_at DATETIME NOT NULL,
          revoked TINYINT(1) NOT NULL DEFAULT 0,
          created_at DATETIME NOT NULL,
          last_seen_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE audit_log (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NULL,
          actor_user_id INT NULL,
          entity_type VARCHAR(40) NULL,
          entity_id VARCHAR(64) NULL,
          action VARCHAR(64) NULL,
          old_value TEXT NULL,
          new_value TEXT NULL,
          remarks VARCHAR(500) NULL
        )
        """,
        """
        CREATE TABLE orders (
          id INT PRIMARY KEY,
          organization_id INT NOT NULL,
          reference VARCHAR(80) NOT NULL,
          marker VARCHAR(40) NOT NULL
        )
        """,
        """
        CREATE TABLE payroll_worker_profiles (
          id INT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          can_work_rinse TINYINT(1) NOT NULL DEFAULT 0,
          can_work_drop_off TINYINT(1) NOT NULL DEFAULT 1,
          can_work_both TINYINT(1) NOT NULL DEFAULT 0,
          business_entity VARCHAR(32) NULL,
          default_hourly_rate DECIMAL(10,2) NULL
        )
        """,
    ]
    for sql in statements:
        cur.execute(sql)
    ensure_planned_weekly_schedule_table(cur)
    ensure_task_catalog_tables(cur)
    ensure_responsibilities_table(cur)

    cur.executemany(
        "INSERT INTO organizations (id, slug, display_name, active) VALUES (%s,%s,%s,1)",
        [(1, "veewash", "VeeWash"), (2, "otherwash", "Other Wash")],
    )
    cur.executemany(
        """
        INSERT INTO users (id, username, password_hash, display_name, active, organization_id)
        VALUES (%s,%s,%s,%s,1,%s)
        """,
        [
            (2, "ana", password_hash, "Ana Employee", 1),
            (3, "sam", password_hash, "Sam Supervisor", 1),
            (4, "ben", password_hash, "Ben Other", 2),
            (5, "rinse", password_hash, "Rinse Partner", 1),
        ],
    )
    cur.executemany(
        "INSERT INTO roles (id, code) VALUES (%s,%s)",
        [(1, "OPS"), (2, "RINSE"), (3, "EMPLOYEE")],
    )
    cur.executemany(
        "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
        [(3, 1), (4, 1), (5, 2), (2, 3)],
    )
    cur.executemany(
        """
        INSERT INTO payroll_profiles
          (user_id, first_name, last_name, attendance_pin_hash, attendance_pin_last4)
        VALUES (%s,%s,%s,%s,%s)
        """,
        [
            (2, "Ana", "Employee", pin_hash, "2468"),
            (3, "Sam", "Supervisor", None, None),
            (4, "Ben", "Other", None, None),
        ],
    )
    cur.executemany(
        "INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)",
        [
            (1, "clock_payroll_ui_json", ui),
            (2, "clock_payroll_ui_json", ui),
        ],
    )
    cur.execute(
        """
        INSERT INTO shift_sessions (id, user_id, organization_id, status, clock_in_at)
        VALUES (10, 2, 1, 'active', NOW())
        """
    )
    cur.execute(
        "INSERT INTO orders (id, organization_id, reference, marker) VALUES (1, 1, 'R-100', 'untouched')"
    )
    cur.execute(
        """
        INSERT INTO weekly_schedule_roles (
          organization_id, code, name, role_group, display_order, active,
          uses_time_slots, remarks_enabled, task_category_code, completion_type,
          timer_enabled, verification_required, verification_method, verification_timing
        ) VALUES (1, 'custom_keep_fold', 'Keep Existing Fold', 'CLEANING', 3, 1,
                  0, 1, 'end_of_day', 'simple', 0, 1, 'supervisor', 'same_shift')
        """
    )
    cur.execute("SELECT id, code, name FROM weekly_schedule_roles WHERE code='custom_keep_fold'")
    sentinel = cur.fetchone()
    cur.execute(
        """
        INSERT INTO planned_weekly_schedule_responsibilities (
          organization_id, week_start, user_id, day_of_week, role, remarks,
          assignment_group_id, timing_mode, start_time, execution_mode
        ) VALUES (%s,%s,%s,%s,'custom_keep_fold',NULL,%s,'anytime',NULL,'individual')
        """,
        (1, week, 2, dow, "sentinel-group"),
    )
    cur.execute(
        "SELECT COUNT(*) AS n FROM planned_weekly_schedule_responsibilities WHERE role='custom_keep_fold'"
    )
    sentinel_assignments = int(cur.fetchone()["n"])
    role_count_before = _count(cur, "weekly_schedule_roles")
    conn.commit()

    first = prepare_lost_found_schema(cur)
    conn.commit()
    second = prepare_lost_found_schema(cur)
    conn.commit()
    RESULTS["schema"] = {"first": first, "second": second}
    created_second = [row["table"] for row in second["tables"] if row.get("created")]
    added_second = [row for row in second["tables"] if row.get("columns_added")]
    check("schema second run creates nothing", created_second == [] and added_second == [], str(second["tables"]))
    for org_row in second["activities"]:
        check(
            f"activity definitions stable org {org_row['organization_id']}",
            org_row["definitions_before"] == org_row["definitions_after"] == 1,
            json.dumps(org_row),
        )
    cur.execute("SELECT id, code, name FROM weekly_schedule_roles WHERE code='custom_keep_fold'")
    sentinel_after = cur.fetchone()
    check("existing task definition preserved", sentinel_after == sentinel, str(sentinel_after))
    cur.execute(
        "SELECT COUNT(*) AS n FROM planned_weekly_schedule_responsibilities WHERE role='custom_keep_fold'"
    )
    check(
        "existing assignment preserved",
        int(cur.fetchone()["n"]) == sentinel_assignments,
        "",
    )
    cur.execute(
        """
        SELECT organization_id, code, COUNT(*) AS n
        FROM weekly_schedule_roles
        GROUP BY organization_id, code
        HAVING n > 1
        """
    )
    duplicate_codes = cur.fetchall() or []
    check(
        "no duplicate activity or role codes",
        duplicate_codes == [],
        str(duplicate_codes),
    )
    RESULTS["task_rows_before"] = role_count_before
    RESULTS["task_rows_after_prepare"] = _count(cur, "weekly_schedule_roles")
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM weekly_schedule_roles
        WHERE code=%s
        GROUP BY organization_id
        """,
        (ACTIVITY_CODE,),
    )
    counts = [int(row["n"]) for row in cur.fetchall() or []]
    check("one activity definition per organization", counts == [1, 1], str(counts))
    catalog = list_task_definitions(cur, 1)
    eod = [
        item
        for item in catalog
        if item.get("code") == ACTIVITY_CODE and item.get("category_code") == "end_of_day"
    ]
    check("activity is an End of Day catalog task", len(eod) == 1, str(eod[:1]))

    assigned, err = create_responsibility(
        conn,
        cur,
        1,
        week_start=week,
        data={"user_id": 2, "day_of_week": dow, "role": ACTIVITY_CODE, "timing_mode": "anytime"},
    )
    conn.commit()
    check("weekly schedule assignment", assigned is not None, err or "")
    again, again_err = create_responsibility(
        conn,
        cur,
        1,
        week_start=week,
        data={"user_id": 2, "day_of_week": dow, "role": ACTIVITY_CODE, "timing_mode": "anytime"},
    )
    check("duplicate assignment rejected", again is None and "already has" in (again_err or ""), again_err or "")
    cur.execute(
        "SELECT COUNT(*) AS n FROM planned_weekly_schedule_responsibilities WHERE role=%s",
        (ACTIVITY_CODE,),
    )
    check("one Lost & Found assignment", int(cur.fetchone()["n"]) == 1, "")
    responsibility_id = int(assigned["id"]) if assigned else 0

    # Apply the real notification tables after users exist (group members reference users).
    _apply_sql_file(cur, "notification_module_v1.sql")
    conn.commit()

    from backend.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    hub = client.post(
        "/api/public/attendance/pin-hub",
        json={"organization_slug": "veewash", "pin": "2468"},
    )
    hub_body = hub.get_json() or {}
    check("employee PIN login", hub.status_code == 200 and hub_body.get("ok"), hub.get_data(as_text=True)[:500])
    token = hub_body.get("token")
    check("PIN hub shows the employee clocked in", bool((hub_body.get("attendance") or {}).get("clocked_in")), "")

    login = client.post(
        "/auth/login",
        json={"username": "sam", "password": "supervisor-pass", "organization_slug": "veewash"},
    )
    login_body = login.get_json() or {}
    check("supervisor desktop login", login.status_code == 200 and bool(login_body.get("token")), login.get_data(as_text=True)[:400])
    supervisor = {"Authorization": f"Bearer {login_body.get('token')}"}
    other = client.post(
        "/auth/login",
        json={"username": "ben", "password": "supervisor-pass", "organization_slug": "otherwash"},
    )
    other_auth = {"Authorization": f"Bearer {(other.get_json() or {}).get('token')}"}
    rinse = client.post(
        "/auth/login",
        json={"username": "rinse", "password": "supervisor-pass", "organization_slug": "veewash"},
    )
    rinse_auth = {"Authorization": f"Bearer {(rinse.get_json() or {}).get('token')}"}

    def report(kind, number=None, detail=None, client_id="req", filename="photo.png", raw=PNG, extra=None):
        data = {
            "organization_slug": "veewash",
            "hub_token": token,
            "client_request_id": client_id,
            "location_kind": kind,
        }
        if number is not None:
            data["location_number"] = number
        if detail is not None:
            data["location_detail"] = detail
        if extra:
            data.update(extra)
        if filename is not None:
            data["photos"] = (io.BytesIO(raw), filename)
        return client.post("/api/public/attendance/pin-lost-found/report", data=data)

    no_photo = client.post(
        "/api/public/attendance/pin-lost-found/report",
        data={
            "organization_slug": "veewash",
            "hub_token": token,
            "client_request_id": "no-photo",
            "location_kind": "floor",
        },
    )
    check("missing photo rejected", no_photo.status_code == 400 and (no_photo.get_json() or {}).get("code") == "photo_required", no_photo.get_data(as_text=True)[:240])
    bad = report("floor", client_id="bad-photo", filename="notes.txt", raw=b"not an image")
    check("invalid photo rejected", bad.status_code == 400, bad.get_data(as_text=True)[:240])
    cur.execute("SELECT COUNT(*) AS n FROM found_items")
    check("failed uploads created no reports", int(cur.fetchone()["n"]) == 0, "")

    first_report = report("floor", client_id="floor-item-1")
    first_body = first_report.get_json() or {}
    check("floor report created", first_report.status_code == 200 and first_body.get("created") is True, first_report.get_data(as_text=True)[:300])
    retry = report("floor", client_id="floor-item-1")
    retry_body = retry.get_json() or {}
    check("duplicate submission returns the same item", retry.status_code == 200 and retry_body.get("created") is False and retry_body.get("item", {}).get("id") == first_body.get("item", {}).get("id"), "")
    conn.commit()
    cur.execute("SELECT COUNT(*) AS n FROM found_items WHERE client_request_id='floor-item-1'")
    check("duplicate submission stored one row", int(cur.fetchone()["n"]) == 1, "")

    washer_missing = report("washer", client_id="washer-missing-number")
    dryer_missing = report("dryer", client_id="dryer-missing-number")
    table_missing = report("folding_table", client_id="table-missing-number")
    check("washer number required", washer_missing.status_code == 400, washer_missing.get_data(as_text=True)[:180])
    check("dryer number required", dryer_missing.status_code == 400, dryer_missing.get_data(as_text=True)[:180])
    check("folding table number required", table_missing.status_code == 400, table_missing.get_data(as_text=True)[:180])
    washer = report("washer", number="12", client_id="washer-number-12")
    dryer = report("dryer", number="4", client_id="dryer-number-04")
    table = report("folding_table", number="3", client_id="table-number-03")
    check("washer number accepted", washer.status_code == 200 and "12" in ((washer.get_json() or {}).get("item") or {}).get("location_label", ""), "")
    check("dryer number accepted", dryer.status_code == 200 and "4" in ((dryer.get_json() or {}).get("item") or {}).get("location_label", ""), "")
    check("folding table number accepted", table.status_code == 200 and "3" in ((table.get_json() or {}).get("item") or {}).get("location_label", ""), "")

    from itertools import combinations

    flag_names = ("redry_missing_ticket", "redry_mesh_bag", "redry_wrong_pocket")
    no_flag = report(
        "dryer",
        number="D1",
        client_id="redry-no-flag",
        extra={"report_category": "redry"},
    )
    check("re-dry without a checkbox rejected", no_flag.status_code == 400 and (no_flag.get_json() or {}).get("code") == "redry_flag_required", no_flag.get_data(as_text=True)[:220])
    no_pocket = report(
        "dryer",
        client_id="redry-no-pocket",
        extra={"report_category": "redry", "redry_missing_ticket": "1"},
    )
    check("re-dry without a pocket rejected", no_pocket.status_code == 400, no_pocket.get_data(as_text=True)[:220])
    redry_ids = []
    for size in (1, 2, 3):
        for picked in combinations(flag_names, size):
            extra = {"report_category": "redry"}
            extra.update({name: "1" if name in picked else "0" for name in flag_names})
            body = report("dryer", number="D4", client_id=f"redry-{size}-{'-'.join(picked)}", extra=extra)
            item = (body.get_json() or {}).get("item") or {}
            flags = item.get("redry_flags") or {}
            expected = {
                "missing_ticket": "redry_missing_ticket" in picked,
                "mesh_bag": "redry_mesh_bag" in picked,
                "wrong_pocket": "redry_wrong_pocket" in picked,
            }
            ok = body.status_code == 200 and item.get("report_category") == "redry" and flags == expected
            check(f"re-dry flags {','.join(picked)}", ok, body.get_data(as_text=True)[:240])
            if item.get("id"):
                redry_ids.append(item["id"])
    check("re-dry reports created", bool(redry_ids), str(redry_ids))
    stored_redry = client.post(
        f"/api/lost-found/{(redry_ids or [0])[0]}/status",
        json={"status": "stored"},
        headers=supervisor,
    )
    check("re-dry cannot be stored", stored_redry.status_code == 400, stored_redry.get_data(as_text=True)[:200])
    resolved_redry = client.post(
        f"/api/lost-found/{(redry_ids or [0])[-1]}/status",
        json={"status": "resolved", "reason": "Corrected the dryer pocket"},
        headers=supervisor,
    )
    check("re-dry resolved with a note", resolved_redry.status_code == 200, resolved_redry.get_data(as_text=True)[:200])
    pockets = client.post(
        "/api/lost-found/redry-pockets",
        json={"pockets": ["D4", "D4", "D9"]},
        headers=supervisor,
    )
    check("designated pockets saved once", pockets.status_code == 200 and (pockets.get_json() or {}).get("pockets") == ["D4", "D9"], pockets.get_data(as_text=True)[:200])
    locale = client.post("/api/me/ui-locale", json={"locale": "es"}, headers=supervisor)
    check("supervisor language persisted", locale.status_code == 200 and (locale.get_json() or {}).get("locale") == "es", locale.get_data(as_text=True)[:200])

    photo_id = ((first_body.get("item") or {}).get("photos") or [{}])[0].get("id")
    photo = client.get(
        f"/api/public/attendance/pin-lost-found/photos/{photo_id}?organization_slug=veewash&hub_token={token}"
    )
    check("employee can retrieve the private photo", photo.status_code == 200 and photo.data.startswith(b"\x89PNG"), f"status={photo.status_code}")
    stolen = client.get(
        f"/api/public/attendance/pin-lost-found/photos/{photo_id}?organization_slug=otherwash&hub_token={token}"
    )
    check("photo is not served for another organization", stolen.status_code in {401, 403, 404}, str(stolen.status_code))

    conn.commit()
    cur.execute(
        """
        SELECT organization_id, user_id, channel, status, detail
        FROM notification_delivery_log
        WHERE event_key='lost_found.item_reported'
        """
    )
    deliveries = cur.fetchall() or []
    RESULTS["notifications"] = deliveries
    orgs = {int(row["organization_id"]) for row in deliveries}
    users = {int(row["user_id"]) for row in deliveries}
    check("notification attempted for the reporting organization only", orgs == {1}, str(deliveries))
    check("notification audience is the same-org supervisor", users == {3}, str(deliveries))
    floor_deliveries = [
        row for row in deliveries if "floor-1" in json.dumps(row, default=str) or True
    ]
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM notification_delivery_log
        WHERE event_key='lost_found.item_reported'
          AND JSON_EXTRACT(payload_json, '$.found_item_id') = %s
        """,
        (int(first_body["item"]["id"]),),
    )
    check("duplicate report did not send another notification", int(cur.fetchone()["n"]) == 1, "")

    desktop = client.get("/api/lost-found?scope=today", headers=supervisor)
    desktop_body = desktop.get_json() or {}
    check("supervisor desktop lists today's reports", desktop.status_code == 200 and len(desktop_body.get("items") or []) >= 4, desktop.get_data(as_text=True)[:240])
    denied = client.get("/api/lost-found", headers=rinse_auth)
    check("rinse role cannot open Lost & Found", denied.status_code == 403, denied.get_data(as_text=True)[:180])
    foreign = client.get(f"/api/lost-found/{first_body['item']['id']}", headers=other_auth)
    check("other organization cannot open the report", foreign.status_code == 404, foreign.get_data(as_text=True)[:180])
    desktop_photo = client.get(f"/api/lost-found/photos/{photo_id}", headers=supervisor)
    check("supervisor can open the photo", desktop_photo.status_code == 200 and desktop_photo.data.startswith(b"\x89PNG"), str(desktop_photo.status_code))
    foreign_photo = client.get(f"/api/lost-found/photos/{photo_id}", headers=other_auth)
    check("other organization cannot open the photo", foreign_photo.status_code == 404, str(foreign_photo.status_code))

    stored_item = washer.get_json()["item"]
    returned_item = dryer.get_json()["item"]
    stored = client.post(
        f"/api/lost-found/{stored_item['id']}/status",
        json={"status": "stored", "comment": "Held in the box"},
        headers=supervisor,
    )
    returned = client.post(
        f"/api/lost-found/{returned_item['id']}/status",
        json={"status": "returned", "order_reference": "R-100", "comment": "Matched to the customer order"},
        headers=supervisor,
    )
    check("stored status saved", stored.status_code == 200, stored.get_data(as_text=True)[:240])
    check("returned status keeps the order reference", returned.status_code == 200 and (returned.get_json() or {}).get("item", {}).get("order_reference") == "R-100", returned.get_data(as_text=True)[:300])
    conn.commit()
    cur.execute("SELECT reference, marker FROM orders")
    check("rinse order row was not modified", cur.fetchone() == {"reference": "R-100", "marker": "untouched"}, "")
    conn.commit()
    cur.execute(
        "SELECT event_type FROM found_item_events WHERE found_item_id=%s ORDER BY id",
        (returned_item["id"],),
    )
    history = [row["event_type"] for row in cur.fetchall() or []]
    check("returned item keeps status history", "reported" in history and "status_changed" in history, str(history))

    yesterday = day - timedelta(days=1)
    cur.execute(
        "UPDATE found_items SET business_date=%s WHERE id=%s",
        (yesterday, stored_item["id"]),
    )
    conn.commit()
    opened = client.post(
        "/api/public/attendance/pin-lost-found/reconciliation",
        data={"organization_slug": "veewash", "hub_token": token},
    )
    opened_body = opened.get_json() or {}
    check("reconciliation opens", opened.status_code == 200, opened.get_data(as_text=True)[:300])
    carried_ids = [int(item["id"]) for item in opened_body.get("items") or [] if item.get("carried_forward")]
    check("stored item carries forward", stored_item["id"] in carried_ids, str(carried_ids))
    late = report("cart", number="9", client_id="late-cart-item")
    late_body = late.get_json() or {}
    check("report while reconciliation is open", late.status_code == 200 and late_body.get("created") is True, late.get_data(as_text=True)[:240])
    again_view = client.post(
        "/api/public/attendance/pin-lost-found/reconciliation",
        data={"organization_slug": "veewash", "hub_token": token},
    )
    again_ids = [int(item["id"]) for item in (again_view.get_json() or {}).get("items") or []]
    check("late report is in the open reconciliation", int(late_body.get("item", {}).get("id") or 0) in again_ids, str(again_ids))

    review = again_view.get_json() or {}
    redry_review = review.get("redry_items") or []
    check(
        "re-dry compliance is separate from the box",
        len(redry_review) >= 1 and all(item.get("report_category") == "redry" for item in redry_review),
        str(review.get("counts")),
    )
    account_errors = []
    for item in (review.get("items") or []) + redry_review:
        res = client.post(
            "/api/public/attendance/pin-lost-found/account",
            json={
                "organization_slug": "veewash",
                "hub_token": token,
                "item_id": item["id"],
                "action": "confirm",
                "comment": "Checked at close",
            },
        )
        if res.status_code != 200:
            account_errors.append(res.get_data(as_text=True)[:200])
    check("item comments recorded", account_errors == [], "; ".join(account_errors))
    box = client.post(
        "/api/public/attendance/pin-lost-found/box-photo",
        data={"organization_slug": "veewash", "hub_token": token, "photos": (io.BytesIO(PNG), "box.png")},
    )
    check("final box photo saved", box.status_code == 200, box.get_data(as_text=True)[:240])

    from backend.cleaning_task_activity import approve_activity, complete_untimed_task, reject_activity

    try:
        completed = complete_untimed_task(
            conn,
            cur,
            organization_id=1,
            user_id=2,
            responsibility_id=responsibility_id,
            shift_session_id=10,
        )
        conn.commit()
        check("activity completion", completed.get("status") == "pending_approval", str(completed.get("status")))
    except Exception as exc:
        completed = {}
        fail("activity completion", f"{exc}\n{traceback.format_exc()}")
    activity_id = int(completed.get("id") or 0)
    cur.execute("SELECT status FROM found_item_reconciliations WHERE organization_id=1 AND business_date=%s", (day,))
    check("reconciliation snapshot completed", (cur.fetchone() or {}).get("status") == "completed", "")
    if activity_id:
        rejected = reject_activity(
            cur, organization_id=1, activity_id=activity_id, supervisor_user_id=3, reason="Photo was unclear"
        )
        conn.commit()
        check("supervisor rejection", rejected.get("status") == "rejected", str(rejected.get("status")))
        cur.execute("SELECT status FROM found_item_reconciliations WHERE organization_id=1 AND business_date=%s", (day,))
        check("rejection reopens reconciliation", (cur.fetchone() or {}).get("status") == "open", "")
        cur.execute("SELECT COUNT(*) AS n FROM found_item_reconciliation_snapshots WHERE organization_id=1")
        snapshots_after_reject = int(cur.fetchone()["n"])
        check("rejection keeps the historical snapshot", snapshots_after_reject >= 1, str(snapshots_after_reject))
        recompleted = complete_untimed_task(
            conn,
            cur,
            organization_id=1,
            user_id=2,
            responsibility_id=responsibility_id,
            shift_session_id=10,
        )
        conn.commit()
        approved = approve_activity(
            cur, organization_id=1, activity_id=int(recompleted["id"]), supervisor_user_id=3
        )
        conn.commit()
        check("supervisor verification", approved.get("status") == "approved", str(approved.get("status")))

    cur.execute("SELECT id, code, name FROM weekly_schedule_roles WHERE code='custom_keep_fold'")
    check("task definition still unchanged after workflow", cur.fetchone() == sentinel, "")
    print(json.dumps({"failures": RESULTS.get("failures", [])}, indent=2, default=str))
    return 1 if RESULTS.get("failures") else 0


def _count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
    return int(cur.fetchone()["n"])


def _apply_sql_file(cur, name: str) -> None:
    from pathlib import Path

    raw = (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
    statement = []
    for line in raw.splitlines():
        if line.strip().startswith("--"):
            continue
        statement.append(line)
        if line.rstrip().endswith(";"):
            sql = "\n".join(statement).strip().rstrip(";")
            statement = []
            if sql:
                cur.execute(sql)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
