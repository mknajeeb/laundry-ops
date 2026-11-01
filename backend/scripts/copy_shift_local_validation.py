#!/usr/bin/env python3
"""Copy Shift checks against local MySQL only.

Clones laundryapp_task_validation into laundryapp_copy_shift_validation, then
uses the Weekly Schedule HTTP routes. Refuses any Azure host. Does not write
the source validation database or production.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3307"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "taskval"
os.environ["MYSQL_DATABASE"] = "laundryapp_copy_shift_validation"
os.environ["FLASK_SECRET_KEY"] = "local-copy-shift-validation"

HOST = os.environ["MYSQL_HOST"]
if "azure" in HOST or HOST.endswith("database.azure.com"):
    raise SystemExit(f"Refusing to run against {HOST}")

SOURCE_DB = "laundryapp_task_validation"
TARGET_DB = "laundryapp_copy_shift_validation"
WEEK = "2026-11-01"

sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail else ""))


def mysql_admin(sql: str) -> None:
    subprocess.run(
        [
            "mysql",
            f"--host={HOST}",
            f"--port={os.environ['MYSQL_PORT']}",
            f"--user={os.environ['MYSQL_USER']}",
            f"--password={os.environ['MYSQL_PASSWORD']}",
            "-e",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def clone_database() -> None:
    mysql_admin(
        f"DROP DATABASE IF EXISTS {TARGET_DB}; "
        f"CREATE DATABASE {TARGET_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    dump = subprocess.run(
        [
            "mysqldump",
            f"--host={HOST}",
            f"--port={os.environ['MYSQL_PORT']}",
            f"--user={os.environ['MYSQL_USER']}",
            f"--password={os.environ['MYSQL_PASSWORD']}",
            "--single-transaction",
            "--set-gtid-purged=OFF",
            SOURCE_DB,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "mysql",
            f"--host={HOST}",
            f"--port={os.environ['MYSQL_PORT']}",
            f"--user={os.environ['MYSQL_USER']}",
            f"--password={os.environ['MYSQL_PASSWORD']}",
            TARGET_DB,
        ],
        check=True,
        input=dump.stdout,
        capture_output=True,
    )


def counts(cur) -> dict[str, int]:
    found = {}
    for table in (
        "payroll_cycles",
        "payroll_profiles",
        "payroll_worker_profiles",
        "cleaning_task_shared_sessions",
        "cleaning_task_shared_session_items",
        "cleaning_task_activity",
    ):
        cur.execute("SHOW TABLES LIKE %s", (table,))
        if not cur.fetchone():
            found[table] = -1
            continue
        cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
        found[table] = int((cur.fetchone() or {}).get("n") or 0)
    return found


def main() -> int:
    clone_database()
    from backend.app import app
    from backend.db import get_db

    client = app.test_client()
    login = client.post(
        "/auth/login",
        json={"username": "veewash.admin", "password": "taskval-pass", "organization_slug": "veewash"},
    )
    body = login.get_json(silent=True) or {}
    token = body.get("token")
    check("admin login", login.status_code == 200 and bool(token), str(body)[:240])
    if not token:
        return 1
    headers = {"Authorization": f"Bearer {token}"}

    def post(path, payload):
        res = client.post(path, json=payload, headers=headers)
        return res.status_code, res.get_json(silent=True) or {}

    status, created = post(
        "/rinse/shift-analysis/weekly-schedule",
        {
            "week_start": WEEK,
            "user_id": 2,
            "day_of_week": 1,
            "start_time": "08:00",
            "end_time": "16:00",
            "break_minutes": 45,
            "unscheduled_break_minutes": 15,
            "break_slots": [{"start_time": "12:00", "end_time": "12:30"}],
            "assignments": [
                {"role": "wash", "full_shift": False, "start_time": "08:00", "end_time": "12:00", "remarks": "Early wash"},
                {"role": "fold", "full_shift": False, "start_time": "12:00", "end_time": "16:00", "remarks": "Fold after"},
            ],
        },
    )
    source = created.get("entry") or {}
    check("source shift created", status == 201 and bool(source.get("id")), str(created.get("error") or source)[:300])
    status, evening = post(
        "/rinse/shift-analysis/weekly-schedule",
        {
            "week_start": WEEK,
            "user_id": 2,
            "day_of_week": 1,
            "start_time": "17:00",
            "end_time": "21:00",
            "assignments": [{"role": "fold", "full_shift": True}],
        },
    )
    check("second shift created", status == 201, str(evening.get("error") or "")[:200])
    status, blocked = post(
        "/rinse/shift-analysis/weekly-schedule",
        {
            "week_start": WEEK,
            "user_id": 4,
            "day_of_week": 2,
            "start_time": "07:00",
            "end_time": "11:00",
            "assignments": [{"role": "fold", "full_shift": True}],
        },
    )
    check("existing Tuesday shift created", status == 201, str(blocked.get("error") or "")[:200])
    for payload, label in (
        (
            {
                "week_start": WEEK,
                "day_of_week": 1,
                "role": "lint_cleaning",
                "user_ids": [2],
                "timing_mode": "specific_time",
                "start_time": "10:00",
                "remarks": "Front machines",
            },
            "lint task",
        ),
        (
            {
                "week_start": WEEK,
                "day_of_week": 1,
                "role": "floor_cleaning",
                "user_ids": [2],
                "timing_mode": "specific_time",
                "start_time": "18:00",
                "remarks": "Evening floors",
            },
            "evening task",
        ),
        (
            {
                "week_start": WEEK,
                "day_of_week": 1,
                "role": "agroup_routine_cleaning",
                "user_ids": [2, 3],
                "execution_mode": "shared",
                "timing_mode": "anytime",
            },
            "shared Monday activity",
        ),
        (
            {
                "week_start": WEEK,
                "day_of_week": 4,
                "role": "agroup_routine_cleaning",
                "user_ids": [2, 3],
                "execution_mode": "shared",
                "timing_mode": "anytime",
            },
            "shared Thursday activity",
        ),
        (
            {
                "week_start": WEEK,
                "day_of_week": 5,
                "role": "agroup_routine_cleaning",
                "user_ids": [2, 3],
                "execution_mode": "shared",
                "timing_mode": "anytime",
            },
            "shared Friday activity",
        ),
    ):
        status, result = post("/rinse/shift-analysis/weekly-schedule/responsibilities", payload)
        check(label, status == 201, str(result.get("error") or result.get("code") or "")[:300])

    source_id = int(source["id"])
    status, preview = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy-preview",
        {"user_ids": [3, 4], "days_of_week": [2, 4], "conflict_mode": "skip"},
    )
    tasks = {row["role"]: row for row in (preview.get("source") or {}).get("tasks") or []}
    check(
        "preview selects this shift's task and leaves the other shift's task off",
        status == 200
        and tasks.get("lint_cleaning", {}).get("selected_by_default") is True
        and tasks.get("floor_cleaning", {}).get("selected_by_default") is False,
        str({role: (row.get("selected_by_default"), row.get("selection_note")) for role, row in tasks.items()})[:400],
    )
    check(
        "preview skips the existing Tuesday shift",
        preview.get("counts", {}).get("skip", 0) >= 1 and preview.get("counts", {}).get("create", 0) >= 1,
        str(preview.get("counts")),
    )

    db = get_db()
    cur = db.cursor(dictionary=True)
    before = counts(cur)
    cur.execute(
        """
        SELECT id, user_id, day_of_week, start_time, end_time, break_minutes, role_assignments
        FROM planned_weekly_schedule_entries WHERE id=%s
        """,
        (source_id,),
    )
    source_before = dict(cur.fetchone() or {})
    cur.close()
    db.close()

    status, copied = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {"user_ids": [4], "days_of_week": [3], "conflict_mode": "skip"},
    )
    copy = copied.get("copy") or {}
    check("copy one employee one day", status == 200 and copy.get("message") == "1 shift copied.", str(copied.get("error") or copy)[:300])

    shared_tasks = ["lint_cleaning", "agroup_routine_cleaning"]
    status, joined_preview = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy-preview",
        {"user_ids": [4], "days_of_week": [4], "conflict_mode": "skip", "task_roles": shared_tasks},
    )
    activities = joined_preview.get("activities") or []
    join_note = " ".join(note for target in joined_preview.get("targets") or [] for note in target.get("notes") or [])
    check(
        "Thursday copy offers joining the existing shared activity",
        status == 200 and activities and activities[0].get("mode") == "join" and "Adds Francis" in join_note,
        join_note[:300],
    )
    status, joined = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {"user_ids": [4], "days_of_week": [4], "conflict_mode": "skip", "task_roles": shared_tasks},
    )
    check("join existing activity", status == 200, str(joined.get("error") or joined.get("copy"))[:300])

    status, separate_preview = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy-preview",
        {
            "user_ids": [4],
            "days_of_week": [5],
            "conflict_mode": "skip",
            "task_roles": shared_tasks,
            "activity_modes": [{"role": "agroup_routine_cleaning", "mode": "independent"}],
        },
    )
    separate_target = (separate_preview.get("targets") or [{}])[0]
    check(
        "independent copy is offered and does not silently change a shared checklist",
        status == 200
        and (separate_preview.get("activities") or [{}])[0].get("mode") == "independent"
        and "separate assignment" in " ".join(separate_target.get("notes") or []),
        str(separate_target.get("notes") or separate_target.get("issues"))[:400],
    )
    status, separate = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {
            "user_ids": [4],
            "days_of_week": [5],
            "conflict_mode": "skip",
            "task_roles": shared_tasks,
            "activity_modes": [{"role": "agroup_routine_cleaning", "mode": "independent"}],
            "resolutions": [
                {"user_id": 4, "day_of_week": 5, "action": "copy_without_checklist"}
            ]
            if separate_target.get("action") == "needs_resolution"
            else [],
        },
    )
    check("independent activity copy", status == 200, str(separate.get("error") or "")[:300])

    status, selected = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {"user_ids": [3], "days_of_week": [6], "conflict_mode": "skip", "task_roles": ["lint_cleaning"]},
    )
    check("selected task only", status == 200, str(selected.get("error") or "")[:240])

    status, skipped = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {"user_ids": [4], "days_of_week": [2], "conflict_mode": "skip"},
    )
    skipped_copy = skipped.get("copy") or {}
    check(
        "existing shift skipped",
        status == 200 and skipped_copy.get("skipped") == 1 and "skipped" in skipped_copy.get("message", ""),
        str(skipped_copy)[:240],
    )
    status, replaced = post(
        f"/rinse/shift-analysis/weekly-schedule/{source_id}/copy",
        {"user_ids": [4], "days_of_week": [2], "conflict_mode": "replace", "confirm_replace": True},
    )
    check("replacement confirmed", status == 200 and (replaced.get("copy") or {}).get("replaced") == 1, str(replaced.get("error") or "")[:240])

    db = get_db()
    cur = db.cursor(dictionary=True)
    after = counts(cur)
    check("attendance, payroll, and completed activity rows unchanged", before == after, f"{before} -> {after}")
    cur.execute(
        """
        SELECT id, user_id, day_of_week, start_time, end_time, break_minutes, role_assignments
        FROM planned_weekly_schedule_entries WHERE id=%s
        """,
        (source_id,),
    )
    source_after = dict(cur.fetchone() or {})
    check("source shift unchanged", source_before == source_after, str(source_after)[:240])
    cur.execute(
        """
        SELECT user_id, day_of_week, role, assignment_group_id, execution_mode, timing_mode, start_time, remarks
        FROM planned_weekly_schedule_responsibilities
        WHERE week_start=%s
        ORDER BY day_of_week, role, user_id
        """,
        (WEEK,),
    )
    rows = cur.fetchall()
    thursday = [row for row in rows if int(row["day_of_week"]) == 4 and row["role"] == "agroup_routine_cleaning"]
    thursday_groups = {row["assignment_group_id"] for row in thursday}
    check(
        "Alex joined Thursday's shared activity",
        {row["user_id"] for row in thursday} == {2, 3, 4} and len(thursday_groups) == 1 and all(row["execution_mode"] == "shared" for row in thursday),
        str(thursday),
    )
    friday_activity = [row for row in rows if int(row["day_of_week"]) == 5 and row["role"] == "agroup_routine_cleaning"]
    friday_shared = [row for row in friday_activity if row["user_id"] in {2, 3}]
    friday_own = [row for row in friday_activity if row["user_id"] == 4]
    check(
        "independent Friday activity is a separate group",
        len(friday_own) == 1
        and friday_own[0]["execution_mode"] == "individual"
        and friday_own[0]["assignment_group_id"] not in {row["assignment_group_id"] for row in friday_shared}
        and {row["user_id"] for row in friday_shared} == {2, 3},
        str(friday_activity),
    )
    saturday = [row for row in rows if int(row["day_of_week"]) == 6 and row["user_id"] == 3]
    check("Saturday copy kept only the selected task", [row["role"] for row in saturday] == ["lint_cleaning"], str(saturday))
    cur.execute(
        """
        SELECT user_id, day_of_week, start_time, end_time, break_minutes
        FROM planned_weekly_schedule_entries
        WHERE week_start=%s AND user_id=4 AND day_of_week=3
        """,
        (WEEK,),
    )
    francis = cur.fetchone() or {}
    def clock(value) -> str:
        if hasattr(value, "total_seconds"):
            seconds = int(value.total_seconds())
            return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"
        return str(value)[:5]

    check(
        "copied shift keeps times and break",
        clock(francis.get("start_time")) == "08:00"
        and clock(francis.get("end_time")) == "16:00"
        and int(francis.get("break_minutes") or 0) == 45,
        str(francis),
    )
    cur.execute(
        """
        SELECT business_date, user_ids_json
        FROM task_activity_item_date_overrides
        WHERE business_date BETWEEN '2026-11-01' AND '2026-11-07'
        """
    )
    overrides = cur.fetchall()
    check("checklist names were written for the copy", bool(overrides), str(overrides)[:400])
    cur.close()
    db.close()
    failed = [item for item in RESULTS if not item[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        sys.stderr.write((exc.stderr or b"").decode()[-1000:])
        raise
