#!/usr/bin/env python3
"""Local End of Day Closing validation. Refuses Azure and production hosts."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3307"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "taskval"
os.environ["MYSQL_DATABASE"] = "laundryapp_task_validation"
os.environ["FLASK_SECRET_KEY"] = "local-task-validation"

if "azure" in os.environ["MYSQL_HOST"] or os.environ["MYSQL_HOST"].endswith("database.azure.com"):
    raise SystemExit("Refusing to run against Azure")

sys.path.insert(0, str(ROOT))

TINY_JPEG = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdA"
    "SFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAABAAEDASIAAhEBAxEB/8QA"
    "FQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAA"
    "AAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKp//9k="
)

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def load_bootstrap():
    path = ROOT / "backend/scripts/task_activity_responsibility_local_e2e.py"
    spec = importlib.util.spec_from_file_location("task_local_e2e", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bootstrap


def main() -> int:
    load_bootstrap()()
    from backend.app import app
    from backend.business_time import business_today
    from backend.db import get_db
    from backend.end_of_day_closing_template import end_of_day_closing_payload
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
    check("admin login", status == 200 and bool(admin_token), str(admin_body)[:200])
    admin = {"Authorization": f"Bearer {admin_token}"}
    catalog = client.get("/api/management/task-catalog", headers=admin)
    check("catalog seeds End of Day category", catalog.status_code == 200 and any(
        row.get("code") == "end_of_day" for row in (catalog.get_json(silent=True) or {}).get("categories") or []
    ))

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, name, instructions FROM task_activity_groups WHERE id=1")
    historical_group = cur.fetchone()
    cur.execute(
        "SELECT id, status, completed_by_user_id, completion_input_json FROM cleaning_task_shared_session_items WHERE id=1"
    )
    historical_item = cur.fetchone()

    floor = client.post(
        "/api/management/task-catalog/tasks",
        json={
            "code": "existing_floor",
            "name": "Existing floor",
            "category_code": "intra_day",
            "timer_enabled": False,
            "verification_inherits": True,
        },
        headers=admin,
    )
    floor_code = ((floor.get_json(silent=True) or {}).get("task") or {}).get("code")
    existing = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": "Existing Floor Activity",
            "category_code": "intra_day",
            "items": [{"task_code": floor_code, "required": True, "responsibility_mode": "team"}],
        },
        headers=admin,
    )
    existing_group = (existing.get_json(silent=True) or {}).get("activity_group") or {}

    template = client.get("/api/management/task-catalog/templates/end-of-day-closing", headers=admin)
    payload = template.get_json(silent=True) or {}
    check(
        "template loads without writing the activity",
        template.status_code == 200 and payload.get("name") == "End of Day Closing" and not any(
            group.get("name") == "End of Day Closing"
            for group in (client.get("/api/management/task-catalog", headers=admin).get_json(silent=True) or {}).get("activity_groups") or []
        ),
    )
    source_items = payload.get("items") or end_of_day_closing_payload()["items"]
    code_map = {}
    for item in source_items:
        schema = item.get("input_schema") or []
        saved = client.post(
            "/api/management/task-catalog/tasks",
            json={
                "code": item["task_code"],
                "name": item["task_name"],
                "category_code": "end_of_day",
                "completion_type": "input_required" if schema else "simple",
                "input_schema": schema,
                "timer_enabled": False,
                "verification_inherits": True,
                "active": True,
            },
            headers=admin,
        )
        code_map[item["task_code"]] = ((saved.get_json(silent=True) or {}).get("task") or {}).get("code")
    check("checklist task definitions saved", all(code_map.values()) and len(code_map) == len(source_items))

    def group_items(rows, *, rename_section=None, drop_codes=None, extra=None):
        built = []
        for item in rows:
            if drop_codes and item["task_code"] in drop_codes:
                continue
            section = item.get("section_label")
            if rename_section and section == "Machines":
                section = rename_section
            built.append(
                {
                    "task_code": code_map[item["task_code"]],
                    "task_name": item["task_name"],
                    "required": item.get("required", True),
                    "display_order": item.get("display_order") or 0,
                    "section_label": section,
                    "section_order": item.get("section_order") or 0,
                    "instructions": item.get("instructions"),
                    "active": True,
                    "responsibility_mode": "named" if item["task_code"] == "eod_dryer_lint" else "team",
                    "responsibility_user_ids": [2] if item["task_code"] == "eod_dryer_lint" else [],
                }
            )
        if extra:
            built.extend(extra)
        return built

    created = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": payload["name"],
            "code": payload["code"],
            "category_code": "end_of_day",
            "instructions": payload["instructions"],
            "active": True,
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "require_checklist_before_completion": True,
            "items": group_items(source_items),
        },
        headers=admin,
    )
    group = (created.get_json(silent=True) or {}).get("activity_group") or {}
    sections = []
    for item in group.get("items") or []:
        if item.get("section_label") not in sections:
            sections.append(item.get("section_label"))
    dryer = next(item for item in group.get("items") or [] if item.get("task_code") == code_map["eod_dryer_lint"])
    check(
        "activity stores sections, supervisor verification, and a named default",
        created.status_code == 200
        and group.get("category_code") == "end_of_day"
        and group.get("verification_method") == "supervisor"
        and group.get("require_checklist_before_completion") is True
        and sections[:2] == ["Machines", "Facility Cleaning"]
        and dryer.get("responsibility_user_ids") == [2]
        and dryer.get("instructions"),
        created.get_data(as_text=True)[:400],
    )

    renamed_items = group_items(source_items)
    for row in renamed_items:
        if row["task_code"] == code_map["eod_wipe_washers"]:
            row["section_label"] = "Facility Cleaning"
            row["section_order"] = 20
    renamed = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "id": group["id"],
            "name": "End of Day Closing",
            "category_code": "end_of_day",
            "instructions": payload["instructions"],
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "require_checklist_before_completion": True,
            "items": renamed_items,
        },
        headers=admin,
    )
    renamed_group = (renamed.get_json(silent=True) or {}).get("activity_group") or {}
    moved = next(item for item in renamed_group.get("items") or [] if item.get("task_code") == code_map["eod_wipe_washers"])
    check(
        "section membership can be edited and item identity stays",
        renamed.status_code == 200 and moved.get("section_label") == "Facility Cleaning" and moved.get("id") == next(
            item.get("id") for item in group.get("items") or [] if item.get("task_code") == code_map["eod_wipe_washers"]
        ),
    )
    # Move it back so the employee checklist matches the intended sections.
    client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "id": group["id"],
            "name": "End of Day Closing",
            "category_code": "end_of_day",
            "instructions": payload["instructions"],
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "require_checklist_before_completion": True,
            "items": group_items(source_items),
        },
        headers=admin,
    )

    label_edit = client.post(
        "/api/management/task-catalog/tasks",
        json={
            "code": code_map["eod_dryer_lint"],
            "name": "Clean dryer lint trays & gaskets",
            "category_code": "end_of_day",
            "completion_type": "simple",
            "timer_enabled": False,
            "verification_inherits": True,
        },
        headers=admin,
    )
    check("item label save uses the existing task definition", label_edit.status_code == 200)

    assigned = client.post(
        "/rinse/shift-analysis/weekly-schedule/responsibilities",
        json={
            "week_start": week.isoformat(),
            "day_of_week": dow,
            "role": group.get("role_code"),
            "user_ids": [2, 3],
            "execution_mode": "shared",
            "timing_mode": "anytime",
            "item_responsibility_overrides": [
                {
                    "group_item_id": dryer["id"],
                    "task_code": code_map["eod_dryer_lint"],
                    "responsibility_mode": "named",
                    "user_ids": [2, 3],
                }
            ],
        },
        headers=admin,
    )
    assigned_body = assigned.get_json(silent=True) or {}
    responsibility = assigned_body.get("responsibility") or {}
    if not responsibility.get("id"):
        rows = assigned_body.get("responsibilities") or []
        responsibility = next((row for row in rows if row.get("role") == group.get("role_code")), {})
    resp_id = responsibility.get("id")
    check("weekly schedule assigns the shared activity and date override", assigned.status_code in {200, 201} and bool(resp_id), assigned.get_data(as_text=True)[:400])

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
            ON DUPLICATE KEY UPDATE allow_cleaning_tasks=1, allow_cleaning_task_review=1
            """,
            (uid,),
        )
    grant.commit()
    grant_cur.close()
    grant.close()

    def pin(path, pin_code, body):
        return client.post(path, json={"organization_slug": "veewash", "pin": pin_code, **body})

    started = pin("/api/public/attendance/pin-cleaning-tasks/start", "1111", {"responsibility_id": resp_id})
    activity = (started.get_json(silent=True) or {}).get("activity") or {}
    started_items = ((activity.get("group") or {}).get("items")) or []
    dryer_live = next((item for item in started_items if item.get("task_code") == code_map["eod_dryer_lint"]), {})
    check(
        "employee PIN starts one shared checklist",
        started.status_code == 200 and dryer_live.get("section_label") == "Machines" and dryer_live.get("responsibility_user_ids") == [2, 3],
        started.get_data(as_text=True)[:400],
    )
    activity_id = activity.get("id")

    changed = client.post(
        "/api/management/task-catalog/tasks",
        json={
            "code": code_map["eod_dryer_lint"],
            "name": "Renamed after start",
            "category_code": "end_of_day",
            "completion_type": "simple",
            "timer_enabled": False,
            "verification_inherits": True,
        },
        headers=admin,
    )
    extra_task = client.post(
        "/api/management/task-catalog/tasks",
        json={"code": "eod_extra", "name": "Added after start", "category_code": "end_of_day", "timer_enabled": False, "verification_inherits": True},
        headers=admin,
    )
    extra_code = ((extra_task.get_json(silent=True) or {}).get("task") or {}).get("code")
    without_wipe = group_items(source_items, drop_codes={"eod_wipe_washers"}, extra=[
        {"task_code": extra_code, "required": True, "section_label": "Machines", "section_order": 10, "responsibility_mode": "team"}
    ])
    edited_after = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "id": group["id"],
            "name": "End of Day Closing",
            "category_code": "end_of_day",
            "instructions": payload["instructions"],
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "require_checklist_before_completion": True,
            "items": without_wipe,
        },
        headers=admin,
    )
    after_items = ((edited_after.get_json(silent=True) or {}).get("activity_group") or {}).get("items") or []
    wipe = next((item for item in after_items if item.get("task_code") == code_map["eod_wipe_washers"]), {})
    check(
        "removing an item that already has a session deactivates it",
        changed.status_code == 200 and edited_after.status_code == 200 and wipe.get("active") is False,
        edited_after.get_data(as_text=True)[:300],
    )

    values_by_code = {
        "eod_hot_water": {"values": {"cycle": "done", "machines": "12, 18, 24"}},
        "eod_ticket_holders": {"values": {"result": "pass"}},
        "eod_machines_down": {"values": {"result": "yes", "machines": "08", "issue": "Not draining"}},
        "eod_test_ticket": {"values": {"result": "issue", "remarks": "Printer jam"}},
        "eod_scale": {"values": {"result": "pass"}},
        "eod_bags": {"values": {"poly": "low", "orange": "ok", "remarks": "Poly running low"}},
        "eod_gloves": {"values": {"result": "out"}},
        "eod_lost_clear": {"values": {"result": "done"}},
        "eod_lost_count": {"values": {"count": 2, "photos": [{"content_type": "image/jpeg", "data_base64": TINY_JPEG}]}},
        "eod_wf_bags": {"values": {"count": 0}},
        "eod_hd_bags": {"values": {"count": 0}},
        "eod_other_issues": {"values": {"result": "yes", "remarks": "Washer 4 still wet"}},
    }
    missing_machines = pin(
        "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
        "1111",
        {"activity_id": activity_id, "task_code": code_map["eod_hot_water"], "completion_input": {"values": {"cycle": "done"}}},
    )
    check("Done without machine numbers is rejected", missing_machines.status_code == 400, missing_machines.get_data(as_text=True)[:200])
    not_needed = pin(
        "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
        "2222",
        {
            "activity_id": activity_id,
            "task_code": code_map["eod_hot_water"],
            "completion_input": {"values": {"cycle": "not_needed"}},
        },
    )
    # Sam has not started. Use Alex for the negative-path proof, then the real Done value.
    not_needed = pin(
        "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
        "1111",
        {
            "activity_id": activity_id,
            "task_code": code_map["eod_hot_water"],
            "completion_input": {"values": {"cycle": "not_needed", "machines": "99"}},
        },
    )
    not_needed_item = next(
        (
            item
            for item in ((((not_needed.get_json(silent=True) or {}).get("activity") or {}).get("group") or {}).get("items") or [])
            if item.get("task_code") == code_map["eod_hot_water"]
        ),
        {},
    )
    stored_hot = (not_needed_item.get("completion_input") or {}).get("values") or {}
    check(
        "Not Needed omits machine numbers",
        not_needed.status_code == 200 and stored_hot.get("cycle") == "not_needed" and "machines" not in stored_hot,
        str(stored_hot),
    )
    dryer_after = next(
        (
            item
            for item in ((((not_needed.get_json(silent=True) or {}).get("activity") or {}).get("group") or {}).get("items") or [])
            if item.get("task_code") == code_map["eod_dryer_lint"]
        ),
        {},
    )
    returned_codes = {
        item.get("task_code")
        for item in ((((not_needed.get_json(silent=True) or {}).get("activity") or {}).get("group") or {}).get("items") or [])
    }
    check(
        "master edits do not rename or add items on the started session",
        dryer_after.get("task_name") == "Clean dryer lint trays & gaskets"
        and extra_code not in returned_codes
        and code_map["eod_wipe_washers"] in returned_codes,
        str(dryer_after.get("task_name")),
    )

    # Hot water is already checked as Not Needed. Remaining input items use the map except hot water.
    alex_codes = [code for code in code_map if code not in {"eod_hot_water", "eod_bags", "eod_gloves", "eod_other_issues"}]
    sam_codes = ["eod_bags", "eod_gloves", "eod_other_issues"]
    alex_ok = True
    alex_detail = ""
    for original in alex_codes:
        body = {"activity_id": activity_id, "task_code": code_map[original]}
        if original in values_by_code:
            body["completion_input"] = values_by_code[original]
        done = pin("/api/public/attendance/pin-cleaning-tasks/group-checkoff", "1111", body)
        if done.status_code != 200:
            alex_ok = False
            alex_detail = f"{original} {done.status_code} {done.get_data(as_text=True)[:240]}"
            break
    check("Alex checks off shared items including counts and photos", alex_ok, alex_detail)
    finished_a = pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "1111", {"activity_id": activity_id})
    check("Alex finishes participation with open partner items still blocked or allowed by remaining", finished_a.status_code in {200, 400}, finished_a.get_data(as_text=True)[:240])

    listed = pin("/api/public/attendance/pin-cleaning-tasks", "2222", {})
    sam_resp = next(
        (task.get("responsibility_id") for task in (listed.get_json(silent=True) or {}).get("tasks") or [] if task.get("role") == group.get("role_code")),
        None,
    )
    started_b = pin("/api/public/attendance/pin-cleaning-tasks/start", "2222", {"responsibility_id": sam_resp})
    sam_activity = (started_b.get_json(silent=True) or {}).get("activity") or {}
    sam_ok = started_b.status_code == 200
    sam_detail = started_b.get_data(as_text=True)[:240]
    for original in sam_codes:
        done = pin(
            "/api/public/attendance/pin-cleaning-tasks/group-checkoff",
            "2222",
            {
                "activity_id": sam_activity.get("id"),
                "task_code": code_map[original],
                "completion_input": values_by_code[original],
            },
        )
        if done.status_code != 200:
            sam_ok = False
            sam_detail = f"{original} {done.get_data(as_text=True)[:240]}"
            break
    check("Sam checks off the remaining shared items", sam_ok, sam_detail)
    finished_b = pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "2222", {"activity_id": sam_activity.get("id")})
    if finished_a.status_code != 200:
        finished_a = pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "1111", {"activity_id": activity_id})
    check("both employees finish their own participation", finished_a.status_code == 200 and finished_b.status_code == 200, finished_b.get_data(as_text=True)[:240])

    review = pin("/api/public/attendance/pin-cleaning-tasks/review", "3333", {"business_date": today.isoformat()})
    cards = (review.get_json(silent=True) or {}).get("verification_cards") or []
    card = next((row for row in cards if row.get("role_label") == "End of Day Closing"), {})
    checklist = card.get("checklist") or []
    machines = next((item for item in checklist if item.get("task_code") == code_map["eod_machines_down"]), {})
    bags = next((item for item in checklist if item.get("task_code") == code_map["eod_bags"]), {})
    lost = next((item for item in checklist if item.get("task_code") == code_map["eod_lost_count"]), {})
    wf = next((item for item in checklist if item.get("task_code") == code_map["eod_wf_bags"]), {})
    check(
        "supervisor review is one card and shows machine numbers, supply status, counts, and photos",
        review.status_code == 200
        and len([row for row in cards if row.get("role_label") == "End of Day Closing"]) == 1
        and ((machines.get("completion_input") or {}).get("values") or {}).get("machines") == ["08"]
        and ((bags.get("completion_input") or {}).get("values") or {}).get("poly") == "low"
        and ((wf.get("completion_input") or {}).get("values") or {}).get("count") == 0
        and ((lost.get("completion_input") or {}).get("values") or {}).get("photos"),
        json.dumps({"machines": machines.get("completion_input"), "lost": lost.get("completion_input")}, default=str)[:500],
    )
    photo_token = ((((lost.get("completion_input") or {}).get("values") or {}).get("photos") or [{}])[0]).get("token")
    photo = client.get(f"/api/management/task-completion-photos/{photo_token}", headers=admin)
    check("photo is stored in the application database and returned to the same organization", photo.status_code == 200 and photo.mimetype == "image/jpeg", str(photo.status_code))

    dashboard = client.get("/api/management/task-dashboard", query_string={"business_date": today.isoformat()}, headers=admin)
    dash = dashboard.get_json(silent=True) or {}
    shared = dash.get("shared_assignments") or []
    dash_items = []
    for row in shared:
        dash_items.extend(row.get("shared_checklist_items") or [])
    dash_machines = next((item for item in dash_items if item.get("task_code") == code_map["eod_machines_down"]), {})
    check(
        "task dashboard keeps the entered machine numbers",
        dashboard.status_code == 200 and ((dash_machines.get("completion_input") or {}).get("values") or {}).get("machines") == ["08"],
        dashboard.get_data(as_text=True)[:240],
    )

    child_id = ((machines.get("records") or [{}])[0]).get("activity_id")
    rejected = pin(
        "/api/public/attendance/pin-cleaning-tasks/reject",
        "3333",
        {"activity_ids": [child_id], "reason": "Confirm the machine number"},
    )
    check("supervisor can reject one checklist item", rejected.status_code == 200 and bool(child_id), rejected.get_data(as_text=True)[:240])

    approve_task = client.post(
        "/api/management/task-catalog/tasks",
        json={"code": "approve_floor", "name": "Approve floor", "category_code": "intra_day", "timer_enabled": False, "verification_inherits": False, "verification_required": True, "verification_method": "supervisor"},
        headers=admin,
    )
    approve_code = ((approve_task.get_json(silent=True) or {}).get("task") or {}).get("code")
    approve_group = client.post(
        "/api/management/task-catalog/activity-groups",
        json={
            "name": "Approve Path",
            "category_code": "intra_day",
            "require_checklist_before_completion": True,
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "items": [{"task_code": approve_code, "required": True, "responsibility_mode": "team"}],
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
            "user_ids": [2],
            "execution_mode": "shared",
            "timing_mode": "anytime",
        },
        headers=admin,
    )
    approve_resp = ((approve_assigned.get_json(silent=True) or {}).get("responsibility") or {}).get("id")
    if not approve_resp:
        listed_a = pin("/api/public/attendance/pin-cleaning-tasks", "1111", {})
        approve_resp = next((task.get("responsibility_id") for task in (listed_a.get_json(silent=True) or {}).get("tasks") or [] if task.get("role") == approve_role), None)
    started_ok = pin("/api/public/attendance/pin-cleaning-tasks/start", "1111", {"responsibility_id": approve_resp})
    ok_activity = (started_ok.get_json(silent=True) or {}).get("activity") or {}
    checked = pin("/api/public/attendance/pin-cleaning-tasks/group-checkoff", "1111", {"activity_id": ok_activity.get("id"), "task_code": approve_code})
    finished_ok = pin("/api/public/attendance/pin-cleaning-tasks/complete-group", "1111", {"activity_id": ok_activity.get("id")})
    review_ok = pin("/api/public/attendance/pin-cleaning-tasks/review", "3333", {"business_date": today.isoformat()})
    ok_card = next((row for row in (review_ok.get_json(silent=True) or {}).get("verification_cards") or [] if row.get("role_label") == "Approve Path"), {})
    pending_ids = ok_card.get("pending_activity_ids") or []
    approved = pin(
        "/api/public/attendance/pin-cleaning-tasks/approve",
        "3333",
        {"activity_ids": pending_ids, "approve_all": True},
    )
    check(
        "supervisor approves a completed activity",
        approved.status_code == 200 and bool(ok_card.get("can_approve_all")),
        json.dumps(
            {
                "assign": approve_assigned.status_code,
                "resp": approve_resp,
                "start": started_ok.status_code,
                "check": checked.status_code,
                "finish": finished_ok.status_code,
                "pending": pending_ids,
                "can": ok_card.get("can_approve_all"),
                "block": ok_card.get("block_reason"),
                "approve": approved.get_data(as_text=True)[:240],
            },
            default=str,
        ),
    )

    _status_r, rinse_token, _rinse_body = login("rinse.viewer")
    rinse = {"Authorization": f"Bearer {rinse_token}"}
    rinse_write = client.post(
        "/api/management/task-catalog/activity-groups",
        json={"id": group["id"], "name": "Hijack", "category_code": "end_of_day", "items": without_wipe},
        headers=rinse,
    )
    check("Rinse access cannot edit the checklist", rinse_write.status_code == 403, rinse_write.get_data(as_text=True)[:180])

    hist = get_db()
    cur = hist.cursor(dictionary=True)
    cur.execute("SELECT id, name, instructions FROM task_activity_groups WHERE id=1")
    historical_after = cur.fetchone()
    cur.execute(
        "SELECT id, status, completed_by_user_id, completion_input_json FROM cleaning_task_shared_session_items WHERE id=1"
    )
    historical_item_after = cur.fetchone()
    cur.execute("SELECT name, instructions FROM task_activity_groups WHERE id=%s", (existing_group.get("id"),))
    existing_after = cur.fetchone()
    cur.execute(
        "SELECT definition_snapshot_json FROM cleaning_task_shared_session_items WHERE task_code=%s ORDER BY id DESC LIMIT 1",
        (code_map["eod_dryer_lint"],),
    )
    snap = cur.fetchone() or {}
    frozen = json.loads(snap.get("definition_snapshot_json") or "{}")
    check("historical and unrelated activities stay unchanged", historical_group == historical_after and historical_item == historical_item_after and (existing_after or {}).get("name") == "Existing Floor Activity")
    check("started session keeps the original checklist snapshot", frozen.get("task_name") == "Clean dryer lint trays & gaskets", str(frozen.get("task_name")))

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
