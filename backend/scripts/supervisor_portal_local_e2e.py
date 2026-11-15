#!/usr/bin/env python3
"""Authenticated supervisor-portal checks against a disposable local MySQL.

Refuses Azure and any host other than 127.0.0.1. Synthetic bags are labeled
in the printed results. They do not prove production history.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3308"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "local-only"
os.environ["MYSQL_DATABASE"] = "supervisor_portal_isolated"
os.environ["FLASK_SECRET_KEY"] = "supervisor-local-isolated"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = ""

HOST = os.environ["MYSQL_HOST"]
if "azure" in HOST or HOST.endswith("database.azure.com"):
    raise SystemExit(f"Refusing to run against {HOST}")
if os.environ["MYSQL_DATABASE"] == "laundryapp":
    raise SystemExit("Refusing the production database name")

sys.path.insert(0, str(ROOT))

import mysql.connector
from werkzeug.security import generate_password_hash

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def admin_conn(database: str | None = None):
    return mysql.connector.connect(
        host="127.0.0.1",
        port=3308,
        user="root",
        password="local-only",
        database=database,
        autocommit=True,
    )


def apply_sql(cursor, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    statements = []
    buff = []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buff.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(buff))
            buff = []
    for statement in statements:
        cursor.execute(statement)


def bootstrap() -> None:
    root = mysql.connector.connect(host="127.0.0.1", port=3308, user="root", password="local-only")
    cur = root.cursor()
    cur.execute("DROP DATABASE IF EXISTS supervisor_portal_isolated")
    cur.execute("DROP DATABASE IF EXISTS supervisor_portal_rollback")
    cur.execute("CREATE DATABASE supervisor_portal_isolated CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute("CREATE DATABASE supervisor_portal_rollback CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    root.close()
    sql = ROOT / "backend/sql/supervisor_portal_v1.sql"
    conn = admin_conn("supervisor_portal_isolated")
    cur = conn.cursor()
    apply_sql(cur, sql)
    apply_sql(cur, sql)
    cur.execute("SHOW TABLES LIKE 'supervisor_%'")
    tables = [row[0] for row in cur.fetchall()]
    check("migration applies twice", "supervisor_session_adjustments" in tables, f"{len(tables)} tables")
    cur.execute("START TRANSACTION")
    cur.execute(
        "INSERT INTO supervisor_feature_flags (organization_id, flag_key, enabled) VALUES (1, 'probe', 1)"
    )
    cur.execute("ROLLBACK")
    cur.execute("SELECT COUNT(*) FROM supervisor_feature_flags")
    check("insert rolls back", cur.fetchone()[0] == 0)
    conn.close()

    rollback = admin_conn("supervisor_portal_rollback")
    rcur = rollback.cursor()
    apply_sql(rcur, sql)
    rcur.execute("INSERT INTO supervisor_feature_flags (organization_id, flag_key, enabled) VALUES (1, 'keep', 1)")
    for table in (
        "supervisor_training_progress",
        "supervisor_training_assignments",
        "supervisor_training_items",
        "supervisor_training_versions",
        "supervisor_training_templates",
        "supervisor_quality_incident_employees",
        "supervisor_quality_incidents",
        "supervisor_quality_weight_versions",
        "supervisor_quality_issue_types",
        "supervisor_session_adjustments",
        "supervisor_employee_primary_roles",
        "supervisor_role_targets",
        "supervisor_feature_flags",
    ):
        rcur.execute(f"DROP TABLE IF EXISTS {table}")
    rcur.execute("SHOW TABLES LIKE 'supervisor_%'")
    check("documented rollback drops supervisor tables", rcur.fetchall() == [])
    apply_sql(rcur, sql)
    rcur.execute("SELECT COUNT(*) FROM supervisor_feature_flags")
    check("migration recreates empty tables after rollback", rcur.fetchone()[0] == 0)
    rollback.close()

    password = generate_password_hash("local-test-pass")
    conn = admin_conn("supervisor_portal_isolated")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE organizations (
          id INT PRIMARY KEY,
          slug VARCHAR(64) NOT NULL,
          display_name VARCHAR(200) NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE roles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          code VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(100) NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE users (
          id INT PRIMARY KEY,
          username VARCHAR(100) NOT NULL UNIQUE,
          password_hash VARCHAR(255) NOT NULL,
          display_name VARCHAR(150) NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          organization_id INT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE user_roles (
          user_id INT NOT NULL,
          role_id INT NOT NULL,
          PRIMARY KEY (user_id, role_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE auth_sessions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          token VARCHAR(120) NOT NULL UNIQUE,
          expires_at DATETIME NOT NULL,
          revoked TINYINT(1) NOT NULL DEFAULT 0,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at DATETIME NULL
        )
        """
    )
    cur.execute("INSERT INTO organizations (id, slug, display_name) VALUES (1, 'local-lab', 'Local Lab')")
    people = [
        (1, "admin", "Local Admin", "ADMIN"),
        (2, "ops", "Local Ops", "OPS"),
        (3, "supervisor", "Local Supervisor", "MANAGER"),
        (4, "ada", "Ada Folder", "EMPLOYEE"),
        (5, "bea", "Bea Folder", "EMPLOYEE"),
        (6, "rinse", "Rinse Viewer", "RINSE"),
    ]
    for user_id, username, display, role in people:
        cur.execute("INSERT IGNORE INTO roles (code, name) VALUES (%s, %s)", (role, role))
        cur.execute("SELECT id FROM roles WHERE code=%s", (role,))
        role_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO users (id, username, password_hash, display_name, organization_id) VALUES (%s,%s,%s,%s,1)",
            (user_id, username, password, display),
        )
        cur.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)", (user_id, role_id))
    conn.close()


def login(client, username: str):
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "local-test-pass", "organization": "local-lab"},
    )
    body = response.get_json(silent=True) or {}
    token = body.get("token") or (body.get("user") or {}).get("token")
    if not token and isinstance(body, dict):
        token = body.get("access_token")
    return response.status_code, token, body


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def exercise(client) -> None:
    codes = {}
    tokens = {}
    for name in ("admin", "ops", "supervisor", "ada", "rinse"):
        status, token, body = login(client, name)
        codes[name] = status
        tokens[name] = token
        check(f"login {name}", status == 200 and bool(token), str(body)[:180])

    admin = auth(tokens["admin"])
    ops = auth(tokens["ops"])
    employee = auth(tokens["ada"])
    rinse = auth(tokens["rinse"])

    denied = client.get("/api/supervisor/day?date=2026-11-14", headers=employee)
    check("employee cannot open the portal", denied.status_code == 403, str(denied.status_code))
    rinse_day = client.get("/api/supervisor/day?date=2026-11-14", headers=rinse)
    check("rinse cannot open the portal", rinse_day.status_code == 403, str(rinse_day.status_code))

    target_denied = client.post(
        "/api/supervisor/targets",
        json={"role_key": "FOLDER", "target_value": 45, "effective_from": "2026-11-01", "unit": "lb/hr"},
        headers=ops,
    )
    check("ops cannot publish a scoring target", target_denied.status_code == 403, str(target_denied.status_code))
    target = client.post(
        "/api/supervisor/targets",
        json={"role_key": "FOLDER", "target_value": 45, "effective_from": "2026-11-01", "unit": "lb/hr"},
        headers=admin,
    )
    check("admin can publish a scoring target", target.status_code == 200, target.get_data(as_text=True)[:160])
    activated = client.post("/api/supervisor/scoring/policy", json={"active": True}, headers=admin)
    check("scoring stays inactive", activated.status_code == 409, activated.get_data(as_text=True)[:160])

    seeded = seed_bags()
    check("synthetic bags inserted", seeded, "labeled synthetic, not historical")
    day = client.get("/api/supervisor/day?date=2026-11-14&period=day", headers=admin)
    payload = day.get_json(silent=True) or {}
    recon = payload.get("reconciliation") or {}
    check(
        "synthetic day accounts for every WF bag",
        day.status_code == 200 and recon.get("unaccounted") == 0 and recon.get("total_completed") == recon.get("total_accounted"),
        f"status {day.status_code} completed={recon.get('total_completed')} accounted={recon.get('total_accounted')} {str(payload)[:220]}",
    )
    week = client.get("/api/supervisor/day?date=2026-11-14&period=week", headers=admin)
    week_body = week.get_json(silent=True) or {}
    check(
        "week rate is totals, not an average of daily rates",
        week.status_code == 200 and week_body.get("period") == "week",
        f"status {week.status_code} period {week_body.get('period')}",
    )

    adjustment = client.post(
        "/api/supervisor/adjustments",
        json={
            "date": "2026-11-14",
            "kind": "day_manual_rate",
            "manual_rate": 55,
            "reason": "Local lab override",
            "employee_user_id": 4,
            "employee_name": "Ada Folder",
        },
        headers=admin,
    )
    adjustment_body = adjustment.get_json(silent=True) or {}
    check("day override is stored", adjustment.status_code == 200 and adjustment_body.get("id"), str(adjustment_body)[:180])
    if adjustment_body.get("id"):
        reversed_row = client.post(
            f"/api/supervisor/adjustments/{adjustment_body['id']}/reverse",
            json={"reason": "Local lab reversal"},
            headers=admin,
        )
        check("override reverses", reversed_row.status_code == 200, reversed_row.get_data(as_text=True)[:120])

    client.post("/api/supervisor/quality/types", json={"install_starter": True}, headers=admin)
    weights = client.post(
        "/api/supervisor/quality/weights",
        json={"effective_from": "2026-11-09", "status": "published", "weights": {"damage": 4}, "severity": {"major": 1.5}},
        headers=admin,
    )
    check("weight version publishes", weights.status_code == 200, weights.get_data(as_text=True)[:120])
    nameless = client.post(
        "/api/supervisor/quality/assignments",
        json={"week": "2026-11-14", "issue_type": "damage", "reference": "LAB-NAME", "employees": [{"employee_name": "Ada Folder"}]},
        headers=admin,
    )
    check("name-only issue is rejected", nameless.status_code == 400, nameless.get_data(as_text=True)[:160])
    issue = client.post(
        "/api/supervisor/quality/assignments",
        json={
            "week": "2026-11-14",
            "issue_type": "damage",
            "reference": "LAB-1",
            "quantity": 1,
            "severity": "major",
            "role_key": "FOLDER",
            "employees": [
                {"user_id": 4, "employee_name": "Ada Folder", "role_key": "FOLDER"},
                {"user_id": 5, "employee_name": "Bea Folder", "role_key": "FOLDER"},
            ],
        },
        headers=admin,
    )
    issue_body = issue.get_json(silent=True) or {}
    week_quality = client.get("/api/supervisor/quality/week?date=2026-11-14", headers=admin).get_json(silent=True) or {}
    linked = [int(row.get("user_id")) for row in ((week_quality.get("incidents") or [{}])[0].get("employees") or [])]
    check("issue keeps both account ids", issue.status_code == 200 and set(linked) == {4, 5}, str(linked))
    check("two employees are one incident", (week_quality.get("totals") or {}).get("incident_count") == 1, str(week_quality.get("totals")))

    template = client.post(
        "/api/supervisor/training/templates",
        json={
            "title": "Folding SOP",
            "role_key": "FOLDER",
            "instructions": "Fold to the posted standard.",
            "practical_required": True,
            "items": ["Read the SOP", "Fold a sample bag"],
        },
        headers=admin,
    )
    template_body = template.get_json(silent=True) or {}
    version_id = template_body.get("version_id")
    check("training template saves", template.status_code == 200 and version_id, str(template_body)[:160])
    revised = client.post(
        "/api/supervisor/training/templates",
        json={"title": "Folding SOP", "role_key": "FOLDER", "items": ["Read the revised SOP", "Fold a sample bag"]},
        headers=admin,
    )
    revised_body = revised.get_json(silent=True) or {}
    check("SOP update creates a new version", revised.status_code == 200 and revised_body.get("version_number") == 2, str(revised_body)[:120])
    assigned = client.post(
        "/api/supervisor/training/assignments",
        json={
            "version_id": version_id,
            "trainee_user_id": 4,
            "reason": "corrective",
            "assigned_on": "2026-11-14",
            "due_on": "2026-11-16",
        },
        headers=admin,
    )
    assigned_body = assigned.get_json(silent=True) or {}
    assignment_id = (assigned_body.get("ids") or [None])[0]
    check("corrective training uses Ada's account", assigned.status_code == 200 and assignment_id, str(assigned_body)[:180])

    from backend.employee_pin_hub import issue_hub_session_token

    with client.application.app_context():
        hub = issue_hub_session_token(organization_id=1, employee_id=4)
        other = issue_hub_session_token(organization_id=1, employee_id=5)
    listed = client.post("/api/public/attendance/pin-training", json={"hub_token": hub})
    rows = (listed.get_json(silent=True) or {}).get("assignments") or []
    check("PIN lists only Ada's training", listed.status_code == 200 and len(rows) == 1 and rows[0]["id"] == assignment_id, str(rows)[:180])
    items = rows[0].get("items") or [] if rows else []
    for index, item in enumerate(items):
        client.post(
            "/api/public/attendance/pin-training/progress",
            json={
                "hub_token": hub,
                "assignment_id": assignment_id,
                "item_id": item["id"],
                "done": True,
                **({"status": "in_progress"} if index == 0 else {}),
            },
        )
    submitted = client.post(
        "/api/public/attendance/pin-training/progress",
        json={"hub_token": hub, "assignment_id": assignment_id, "status": "awaiting_verification"},
    )
    check("employee submits for verification", submitted.status_code == 200, submitted.get_data(as_text=True)[:180])
    self_approve = client.post(
        "/api/public/attendance/pin-training/progress",
        json={"hub_token": hub, "assignment_id": assignment_id, "status": "completed"},
    )
    check("employee cannot approve competency", self_approve.status_code == 400, self_approve.get_data(as_text=True)[:160])
    stolen = client.post(
        "/api/public/attendance/pin-training/progress",
        json={"hub_token": other, "assignment_id": assignment_id, "status": "in_progress"},
    )
    check("another employee cannot open Ada's assignment", stolen.status_code == 404, str(stolen.status_code))
    approved = client.post(
        f"/api/supervisor/training/assignments/{assignment_id}/progress",
        json={"status": "completed", "competency_result": "pass"},
        headers=admin,
    )
    check("supervisor approves competency", approved.status_code == 200, approved.get_data(as_text=True)[:160])
    again = client.post("/api/public/attendance/pin-training", json={"hub_token": hub})
    status = ((again.get_json(silent=True) or {}).get("assignments") or [{}])[0].get("status")
    result = ((again.get_json(silent=True) or {}).get("assignments") or [{}])[0].get("competency_result")
    check("employee sees approved competency", status == "completed" and result == "pass", f"{status} {result}")

    failed_assignment = client.post(
        "/api/supervisor/training/assignments",
        json={"version_id": revised_body.get("version_id"), "trainee_user_id": 5, "reason": "sop_update", "assigned_on": "2026-11-14"},
        headers=admin,
    )
    failed_id = ((failed_assignment.get_json(silent=True) or {}).get("ids") or [None])[0]
    if failed_id:
        client.post(
            f"/api/supervisor/training/assignments/{failed_id}/progress",
            json={"status": "in_progress"},
            headers=admin,
        )
        listed_bea = client.post("/api/public/attendance/pin-training", json={"hub_token": other}).get_json(silent=True) or {}
        bea_items = ((listed_bea.get("assignments") or [{}])[0]).get("items") or []
        for item in bea_items:
            client.post(
                "/api/public/attendance/pin-training/progress",
                json={"hub_token": other, "assignment_id": failed_id, "item_id": item["id"], "done": True},
            )
        client.post(
            "/api/public/attendance/pin-training/progress",
            json={"hub_token": other, "assignment_id": failed_id, "status": "awaiting_verification"},
        )
        rejected = client.post(
            f"/api/supervisor/training/assignments/{failed_id}/progress",
            json={"status": "failed", "competency_result": "retrain"},
            headers=admin,
        )
        check("supervisor can require retraining", rejected.status_code == 200, rejected.get_data(as_text=True)[:140])

    summary = client.get("/api/supervisor/rinse-summary?date=2026-11-14", headers=rinse)
    text = summary.get_data(as_text=True)
    leaked = any(word in text for word in ("Ada", "Bea", "wages", "supervisor_notes", "local-test"))
    check("rinse summary hides names and notes", summary.status_code == 200 and not leaked, text[:240])
    roles = client.get("/api/supervisor/roles", headers=ops)
    role_body = roles.get_json(silent=True) or {}
    ready = [row["role_key"] for row in role_body.get("roles") or [] if row.get("scoring_ready")]
    check("only folding is ready to score", roles.status_code == 200 and ready == ["FOLDER"], str(ready))


def seed_bags() -> bool:
    conn = admin_conn("supervisor_portal_isolated")
    cur = conn.cursor()
    from backend.rinse_veewash_shift_day import ensure_shift_monitor_day_tables

    ensure_shift_monitor_day_tables(cur)
    rows = [
        ("B1001", "WF", "Ada Folder", 20),
        ("B1002", "WF", "Ada Folder", 20),
        ("B1003", "WF", None, 10),
        ("B1001", "WF", "Ada Folder", 20),
        ("H1001", "HD", "Ada Folder", 8),
    ]
    for bag_id, service, employee, pounds in rows:
        cur.execute(
            """
            INSERT INTO rinse_shift_monitor_day_bags (
              organization_id, shift_date_et, bag_id, service_type, effective_status,
              canonical_completion_status, canonical_completion_timestamp, canonical_completion_employee,
              pre_weight_lbs, weight_lbs, productivity_employee_name, productivity_completed_at,
              productivity_weight_lbs, productivity_credit_eligible
            ) VALUES (1, '2026-11-14', %s, %s, 'completed', 'completed', '2026-11-14 12:00:00', %s, %s, %s, %s, '2026-11-14 12:00:00', %s, 1)
            ON DUPLICATE KEY UPDATE productivity_credit_eligible=1
            """,
            (bag_id, service, employee, pounds, pounds, employee, pounds),
        )
    conn.commit()
    conn.close()
    return True


def main() -> int:
    bootstrap()
    from backend.app import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        exercise(client)
    failed = [row for row in RESULTS if not row[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
