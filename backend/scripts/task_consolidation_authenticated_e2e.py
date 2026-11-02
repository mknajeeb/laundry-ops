#!/usr/bin/env python3
"""Authenticated Task Management workflow on a disposable local database.

Refuses any Azure or production host. Drops only vw_consolidation_e2e
on 127.0.0.1.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3307"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "taskval"
os.environ["MYSQL_DATABASE"] = "vw_consolidation_e2e"
os.environ["FLASK_SECRET_KEY"] = "local-task-validation"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ.pop("MYSQL_SSL_CA", None)
os.environ.pop("MYSQL_SSL_REQUIRED", None)

HOST = os.environ["MYSQL_HOST"]
if "azure" in HOST or HOST.endswith("database.azure.com") or os.environ["MYSQL_DATABASE"] == "laundryapp":
    raise SystemExit(f"Refusing to run against {HOST}/{os.environ['MYSQL_DATABASE']}")

sys.path.insert(0, str(ROOT))

import inspect  # noqa: E402

import backend.scripts.task_activity_responsibility_local_e2e as _bootstrap_mod  # noqa: E402


def bootstrap() -> None:
    source = inspect.getsource(_bootstrap_mod.bootstrap).replace(
        "laundryapp_task_validation", "vw_consolidation_e2e"
    )
    namespace = dict(_bootstrap_mod.__dict__)
    exec(source, namespace)
    namespace["bootstrap"]()

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def main() -> int:
    bootstrap()
    import backend.db as db

    original_kwargs = db._connection_kwargs

    def _local_kwargs():
        data = original_kwargs()
        data["autocommit"] = True
        return data

    db._connection_kwargs = _local_kwargs
    from backend.app import app
    from backend.business_time import business_today
    from backend.cleaning_task_activity import list_tasks_to_verify
    from backend.db import get_db
    from backend.dryer_lint_transition import preview_lily_dryer_lint
    from backend.employee_mobile_pin_access import ensure_employee_mobile_pin_access_tables
    from backend.intra_day_activity_groups import apply_intra_day_activity_groups
    from backend.planned_weekly_schedule import ensure_planned_weekly_schedule_table, normalize_week_start
    from backend.task_activity_groups import upsert_activity_group
    from backend.task_activity_remarks import migrate_legacy_remarks

    prep = get_db()
    cur = prep.cursor()
    ensure_planned_weekly_schedule_table(cur)
    ensure_employee_mobile_pin_access_tables(cur)
    for uid in (2, 3, 4):
        cur.execute(
            """
            INSERT INTO employee_mobile_pin_access (
              organization_id, user_id, allow_clock, allow_switch_role, allow_take_break,
              allow_checklist, allow_inventory, allow_revenue_cost, allow_team_status,
              allow_cleaning_tasks, allow_cleaning_task_review
            ) VALUES (3, %s, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            ON DUPLICATE KEY UPDATE allow_cleaning_tasks=1, allow_cleaning_task_review=1
            """,
            (uid,),
        )
    prep.commit()
    cur.close()
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
    check("admin login", status == 200 and bool(admin_token), str(admin_body)[:300])
    admin = {"Authorization": f"Bearer {admin_token}"}

    def post_task(code, name):
        return client.post(
            "/api/management/task-catalog/tasks",
            json={
                "code": code,
                "name": name,
                "category_code": "intra_day",
                "verification_required": True,
                "verification_method": "supervisor",
                "verification_inherits": False,
                "timer_enabled": True,
                "instructions": f"How to complete {name}.",
            },
            headers=admin,
        )

    created = [
        post_task("custom_check_washer_residue", "Check washer residue"),
        post_task("washer_cleaning", "Wipe down washers"),
        post_task("floor_cleaning", "Floor sweeping"),
        post_task("lint_cleaning", "Dryer lint cleaning"),
    ]
    check(
        "checklist definitions saved",
        all(row.status_code == 200 for row in created),
        str([row.status_code for row in created]) + " " + created[0].get_data(as_text=True)[:240],
    )

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    first_groups = apply_intra_day_activity_groups(cursor, 3)
    conn.commit()
    second_groups = apply_intra_day_activity_groups(cursor, 3)
    conn.commit()
    check(
        "activity groups apply twice without new ids",
        [row.get("id") for row in first_groups] == [row.get("id") for row in second_groups] and len(first_groups) == 3,
        str([row.get("id") for row in second_groups]),
    )
    upsert_activity_group(
        cursor,
        3,
        {
            "code": "floor_washer",
            "name": "Floor & Washer",
            "category_code": "intra_day",
            "active": True,
            "require_checklist_before_completion": False,
            "items": [
                {
                    "task_code": "floor_cleaning",
                    "section_label": "Floor Cleaning",
                    "required": False,
                    "display_order": 10,
                }
            ],
        },
    )
    conn.commit()

    assigned = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": "agroup_washer_cleaning",
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    body = assigned.get_json(silent=True) or {}
    check("shared washer activity assigned", assigned.status_code in {200, 201}, assigned.get_data(as_text=True)[:500])

    blocked = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": "lint_cleaning",
            "user_ids": [2],
            "execution_mode": "individual",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    blocked_text = blocked.get_data(as_text=True)
    check(
        "new competing lint assignment is blocked",
        blocked.status_code >= 400 and "Dryer Lint Cleaning" in blocked_text,
        blocked_text[:300],
    )
    blocked_floor = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": "agroup_floor_washer",
            "user_ids": [2],
            "execution_mode": "individual",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    check(
        "new floor and washer assignment is blocked",
        blocked_floor.status_code >= 400,
        blocked_floor.get_data(as_text=True)[:300],
    )

    cursor.execute(
        """
        INSERT INTO planned_weekly_schedule_responsibilities
          (organization_id, week_start, user_id, day_of_week, role, timing_mode, execution_mode)
        VALUES
          (3, %s, 2, %s, 'agroup_floor_washer', 'anytime', 'individual'),
          (3, %s, 3, %s, 'lint_cleaning', 'specific_time', 'individual')
        """,
        (week, dow, week, dow),
    )
    cursor.execute(
        """
        UPDATE planned_weekly_schedule_responsibilities
        SET start_time='08:00:00'
        WHERE organization_id=3 AND role='lint_cleaning' AND user_id=3
        """
    )
    conn.commit()
    cursor.execute(
        """
        SELECT id, role, user_id FROM planned_weekly_schedule_responsibilities
        WHERE organization_id=3 AND week_start=%s AND day_of_week=%s
        """,
        (week, dow),
    )
    saved_rows = cursor.fetchall()
    by_role = {}
    for row in saved_rows:
        by_role.setdefault(row["role"], []).append(row)
    washer_ids = [row["id"] for row in by_role.get("agroup_washer_cleaning") or []]
    floor_id = (by_role.get("agroup_floor_washer") or [{}])[0].get("id")
    lint_id = (by_role.get("lint_cleaning") or [{}])[0].get("id")
    check("existing floor and lint rows remain", bool(floor_id and lint_id), str(saved_rows))
    check("shared washer rows saved", len(washer_ids) == 2, str(saved_rows))
    if len(washer_ids) != 2:
        print(f"FAILED early / {len(RESULTS)}")
        return 1

    def pin(path, pin_code, payload):
        return client.post(path, json={"organization_slug": "veewash", "pin": pin_code, **payload})

    alex_start = pin(
        "/api/public/attendance/pin-cleaning-tasks/start",
        "1111",
        {"responsibility_id": washer_ids[0]},
    )
    sam_start = pin(
        "/api/public/attendance/pin-cleaning-tasks/start",
        "2222",
        {"responsibility_id": washer_ids[1]},
    )
    alex_body = alex_start.get_json(silent=True) or {}
    sam_body = sam_start.get_json(silent=True) or {}
    alex_activity = (alex_body.get("activity") or {}).get("id")
    sam_activity = (sam_body.get("activity") or {}).get("id")
    alex_items = [item.get("task_code") for item in ((alex_body.get("activity") or {}).get("group") or {}).get("items") or []]
    check(
        "both employees start independent timers on one checklist",
        alex_start.status_code == 200
        and sam_start.status_code == 200
        and alex_activity
        and sam_activity
        and alex_activity != sam_activity
        and alex_items == ["custom_check_washer_residue", "washer_cleaning"],
        json.dumps({"alex": alex_start.status_code, "sam": sam_start.status_code, "items": alex_items, "bodies": [alex_body.get("error"), sam_body.get("error")]})[:500],
    )

    too_early = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "1111",
        {"activity_id": alex_activity},
    )
    check(
        "required checklist blocks finishing",
        too_early.status_code == 400,
        too_early.get_data(as_text=True)[:240],
    )

    def worker(user_id, activity_id, task_code, remark):
        local = get_db()
        local_cur = local.cursor(dictionary=True)
        try:
            if task_code:
                from backend.cleaning_task_group_execution import checkoff_group_item

                checkoff_group_item(
                    local,
                    local_cur,
                    organization_id=3,
                    user_id=user_id,
                    activity_id=activity_id,
                    task_code=task_code,
                )
            from backend.cleaning_task_activity import get_activity
            from backend.task_activity_remarks import append_remark

            row = get_activity(local_cur, 3, activity_id)
            append_remark(
                local_cur,
                organization_id=3,
                activity=row,
                author_user_id=user_id,
                author_name="Alex" if user_id == 2 else "Sam",
                author_role="employee",
                body=remark,
                task_code=task_code,
            )
            local.commit()
            return "ok"
        finally:
            local_cur.close()
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, 2, alex_activity, "custom_check_washer_residue", "Residue in washer 2"),
            pool.submit(worker, 3, sam_activity, "washer_cleaning", "Wiped washer 2"),
        ]
        concurrent = [item.result() for item in futures]
    check("concurrent checklist updates and remarks", concurrent == ["ok", "ok"], str(concurrent))

    sam_list = pin("/api/public/attendance/pin-cleaning-tasks", "2222", {})
    sam_list_body = sam_list.get_json(silent=True) or {}
    open_rows = sam_list_body.get("activities") or sam_list_body.get("open_activities") or []
    if isinstance(sam_list_body.get("activity"), dict):
        open_rows = [sam_list_body["activity"]]
    shared = None
    blob = json.dumps(sam_list_body)
    check(
        "employee B sees the completed item and both remarks",
        "custom_check_washer_residue" in blob and "Residue in washer 2" in blob and "Wiped washer 2" in blob,
        blob[:700],
    )

    alex_done = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "1111",
        {"activity_id": alex_activity},
    )
    sam_still = pin("/api/public/attendance/pin-cleaning-tasks", "2222", {})
    sam_done = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "2222",
        {"activity_id": sam_activity},
    )
    check(
        "employee A finishes while employee B continues, then B finishes",
        alex_done.status_code == 200 and sam_still.status_code == 200 and sam_done.status_code == 200,
        json.dumps(
            {
                "alex": alex_done.status_code,
                "sam_list": sam_still.status_code,
                "sam": sam_done.status_code,
                "sam_error": (sam_done.get_json(silent=True) or {}).get("error"),
                "alex_error": (alex_done.get_json(silent=True) or {}).get("error"),
            }
        ),
    )

    floor_started = pin(
        "/api/public/attendance/pin-cleaning-tasks/start",
        "1111",
        {"responsibility_id": floor_id},
    )
    floor_body = floor_started.get_json(silent=True) or {}
    floor_activity = (floor_body.get("activity") or {}).get("id")
    floor_done = pin(
        "/api/public/attendance/pin-cleaning-tasks/complete-group",
        "1111",
        {"activity_id": floor_activity, "remark": "Existing floor assignment"},
    ) if floor_activity else None
    lint_started = pin(
        "/api/public/attendance/pin-cleaning-tasks/start",
        "2222",
        {"responsibility_id": lint_id},
    )
    lint_body = lint_started.get_json(silent=True) or {}
    lint_activity = (lint_body.get("activity") or {}).get("id")
    lint_done = None
    if lint_activity:
        lint_done = pin(
            "/api/public/attendance/pin-cleaning-tasks/complete",
            "2222",
            {"activity_id": lint_activity},
        )
    check(
        "existing floor washer and lint assignments still run",
        floor_started.status_code == 200
        and floor_done is not None
        and floor_done.status_code == 200
        and lint_started.status_code == 200
        and lint_done is not None
        and lint_done.status_code == 200,
        json.dumps(
            {
                "floor": floor_started.status_code,
                "floor_done": None if floor_done is None else floor_done.status_code,
                "lint": lint_started.status_code,
                "lint_done": None if lint_done is None else lint_done.status_code,
                "floor_error": floor_body.get("error"),
                "lint_error": lint_body.get("error"),
            }
        ),
    )

    cursor.close()
    conn.close()
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id FROM cleaning_task_activities
        WHERE organization_id=3 AND assignment_group_id IS NOT NULL
          AND activity_kind='group_item' AND status='pending_approval'
          AND role IN ('custom_check_washer_residue', 'washer_cleaning')
        """
    )
    child_ids = [int(row["id"]) for row in cursor.fetchall()]
    approved = client.post(
        "/api/management/task-dashboard/approve",
        json={"activity_ids": child_ids, "approve_all": False, "supervisor_remark": "Machines verified"},
        headers=admin,
    )
    check(
        "supervisor verifies the checklist section",
        approved.status_code == 200 and len(child_ids) >= 2,
        approved.get_data(as_text=True)[:400] + f" ids={child_ids}",
    )

    dash = client.get(
        "/api/management/task-dashboard",
        query_string={"business_date": today.isoformat()},
        headers=admin,
    )
    dash_body = dash.get_json(silent=True) or {}
    washer_cards = [
        row
        for row in dash_body.get("shared_assignments") or []
        if row.get("role") == "agroup_washer_cleaning"
    ]
    contributions = (washer_cards[0].get("contributions") or []) if washer_cards else []
    remarks = (washer_cards[0].get("remarks") or []) if washer_cards else []
    remark_names = {row.get("author_name") for row in remarks}
    check(
        "dashboard counts the washer activity once and lists both employees",
        len(washer_cards) == 1 and len(contributions) == 2 and {"Alex", "Sam"} <= remark_names,
        json.dumps(
            {
                "cards": len(washer_cards),
                "people": [row.get("employee_name") for row in contributions],
                "remarks": [row.get("author_name") for row in remarks],
                "metrics": dash_body.get("metrics"),
            }
        )[:700],
    )
    monthly = client.get(
        "/api/management/task-dashboard/monthly",
        query_string={"start": today.isoformat(), "end": today.isoformat()},
        headers=admin,
    )
    check(
        "dashboard date range loads",
        monthly.status_code == 200,
        monthly.get_data(as_text=True)[:240],
    )

    rinse_status, rinse_token, rinse_body = login("rinse.viewer")
    rinse = {"Authorization": f"Bearer {rinse_token}"} if rinse_token else {}
    rinse_dash = client.get(
        "/api/management/task-dashboard",
        query_string={"business_date": today.isoformat()},
        headers=rinse,
    )
    rinse_payload = rinse_dash.get_json(silent=True) or {}
    rinse_text = json.dumps(rinse_payload)
    rinse_edit = client.post(
        "/api/management/task-dashboard/remarks",
        json={"activity_id": alex_activity, "body": "Rinse should not write"},
        headers=rinse,
    )
    check(
        "rinse cannot see remarks, durations, or editing controls",
        rinse_status == 200
        and rinse_dash.status_code == 200
        and rinse_payload.get("read_only") is True
        and rinse_payload.get("can_approve") is False
        and "Residue in washer 2" not in rinse_text
        and "duration_seconds" not in rinse_text
        and rinse_edit.status_code == 403,
        json.dumps({"login": rinse_status, "dash": rinse_dash.status_code, "edit": rinse_edit.status_code, "error": rinse_body.get("error")})[:400],
    )

    cursor.execute(
        """
        INSERT INTO cleaning_task_activities (
          organization_id, responsibility_id, user_id, business_date, role, status, started_at,
          completion_input_json, rejection_reason
        ) VALUES (
          3, %s, 2, %s, 'lint_cleaning', 'completed', '2026-10-31 18:00:00',
          %s, 'Keep this rejection separate'
        )
        """,
        (
            lint_id,
            today,
            json.dumps(
                {
                    "employee_remark": {
                        "text": "Historical lint note",
                        "author_user_id": 2,
                        "author_name": "Alex",
                        "at": "2026-10-31 18:00:00",
                    },
                    "supervisor_remark": {"text": "No author on this one"},
                }
            ),
        ),
    )
    historical_id = int(cursor.lastrowid)
    conn.commit()
    listed = None
    from backend.task_activity_remarks import list_remarks_for_activity

    cursor.execute("SELECT * FROM cleaning_task_activities WHERE id=%s", (historical_id,))
    historical = cursor.fetchone()
    listed = list_remarks_for_activity(cursor, 3, historical)
    first_migration = migrate_legacy_remarks(cursor, 3)
    conn.commit()
    second_migration = migrate_legacy_remarks(cursor, 3)
    conn.commit()
    cursor.execute("SELECT completion_input_json, rejection_reason FROM cleaning_task_activities WHERE id=%s", (historical_id,))
    preserved = cursor.fetchone()
    check(
        "historical remarks stay visible and migrate once",
        any(row.get("body") == "Historical lint note" for row in listed)
        and any(row.get("body") == "No author on this one" and row.get("author_name") is None for row in listed)
        and first_migration["inserted"] >= 1
        and second_migration["inserted"] == 0
        and "Historical lint note" in str(preserved["completion_input_json"])
        and preserved["rejection_reason"] == "Keep this rejection separate",
        json.dumps({"first": first_migration, "second": second_migration, "visible": [row.get("body") for row in listed]}),
    )

    cursor.execute(
        """
        INSERT INTO cleaning_task_activities (
          organization_id, responsibility_id, user_id, business_date, role, status, started_at,
          verification_timing, verification_required
        ) VALUES (3, %s, 3, %s, 'lint_cleaning', 'pending_approval', NOW(), 'next_day', 1)
        """,
        (lint_id, today),
    )
    conn.commit()
    today_queue = list_tasks_to_verify(cursor, 3, 1, as_of=today, verifier_roles=["ADMIN"], has_supervisor_review=True)
    tomorrow_queue = list_tasks_to_verify(
        cursor, 3, 1, as_of=today + timedelta(days=1), verifier_roles=["ADMIN"], has_supervisor_review=True
    )
    check(
        "next-day verification waits until the following business day",
        not any(row.get("verification_timing") == "next_day" for row in today_queue["pending_verification"])
        and any(row.get("verification_timing") == "next_day" for row in tomorrow_queue["pending_verification"]),
        json.dumps({"today": today_queue["count"], "tomorrow": tomorrow_queue["count"]}),
    )

    preview = preview_lily_dryer_lint(
        [
            {"id": 191, "employee_name": "Amna", "role": "lint_cleaning", "week_start": "2026-11-01", "day_of_week": 1, "timing_mode": "specific_time", "start_time": "08:30"},
            {"id": 7, "employee_name": "Lily Chen", "role": "lint_cleaning", "week_start": "2026-11-08", "day_of_week": 0, "timing_mode": "anytime"},
            {"id": 8, "employee_name": "Lily Chen", "role": "lint_cleaning", "week_start": "2026-11-15", "day_of_week": 0, "timing_mode": "anytime"},
        ]
    )
    check(
        "assignment migration preview leaves November 2 and November 8",
        preview["converted"][0]["id"] == 8 and preview["untouched"][0]["scheduled_date"] == "2026-11-02",
        preview["transition_date"],
    )
    out = {
        "results": RESULTS,
        "washer_card": washer_cards[0] if washer_cards else None,
        "preview": preview,
        "remarks_migration": {"first": first_migration, "second": second_migration},
    }
    Path("/tmp/vw-consolidation-workflow.json").write_text(json.dumps(out, default=str), encoding="utf-8")
    cursor.close()
    conn.close()
    failed = [name for ok, name, _detail in RESULTS if not ok]
    print(f"FAILED {len(failed)} / {len(RESULTS)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
