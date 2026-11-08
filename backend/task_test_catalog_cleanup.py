"""Delete an explicit allowlist of disposable Task Management catalog rows.

The allowlist is the production review set: six inactive activity groups and
33 unused VeeWash task definitions. Matching is by organization slug and exact
code. A row with any activity, shared session, schedule assignment, checklist
use, audit event, or link from a group outside this allowlist is left in place
and the whole cleanup stops.
"""

from __future__ import annotations

from typing import Any

VEEWASH_GROUP_CODES = (
    "e2e_routine_34c74d",
    "e2e_routine_9e2133",
    "e2e_routine_e078a0",
    "e2e_routine_f54c78",
    "smoke_tvp_tvp_smoke_12faa6eb",
)

WASHPRO_GROUP_CODES = ("smoke_tvp_tvp_smoke_35a98f05",)

VEEWASH_TASK_CODES = (
    "custom_mvsiyo3g",
    "custom_shared_lint_b58433",
    "custom_smokelint_5a9583",
    "custom_smokelint_0955d0",
    "custom_smokelint_369c13",
    "custom_e2e_ag_floor_e078a0",
    "custom_e2e_ag_floor_f54c78",
    "custom_e2e_ag_floor_34c74d",
    "custom_e2e_ag_floor_9e2133",
    "custom_e2e_ag_floor_bcc92e",
    "custom_e2e_ag_lint_f54c78",
    "custom_e2e_ag_lint_e078a0",
    "custom_e2e_ag_lint_34c74d",
    "custom_e2e_ag_lint_9e2133",
    "custom_e2e_ag_lint_bcc92e",
    "custom_e2e_tmp_47d99297",
    "custom_e2e_tmp_b59efab7",
    "custom_e2e_tmp_a7ad4061",
    "custom_smokefloor_369c13",
    "custom_smokefloor_0955d0",
    "custom_shared_floor_b58433",
    "custom_smokefloor_5a9583",
    "custom_probe_floor_bf0e76",
    "custom_probe_lint_bf0e76",
    "custom_psmoke_bad_eee48879",
    "custom_psmoke_ok_eee48879",
    "custom_prod_smoke_93ab3162",
    "custom_prod_smoke_cedbb0e7",
    "custom_e2e_ag_floor_abc123",
    "custom_smokex_3321ed",
    "custom_shared_x_635ffb",
    "custom_smokey_3321ed",
    "custom_shared_y_635ffb",
)


def schedule_role_for_group(code: str) -> str:
    from backend.task_activity_groups import _schedule_role_code

    return _schedule_role_code(code)


def _count(cursor, sql: str, params: tuple) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(next(iter(row.values())) or 0)
    return int(row[0] or 0)


def _org_id(cursor, slug: str) -> int | None:
    cursor.execute("SELECT id FROM organizations WHERE slug=%s LIMIT 1", (slug,))
    row = cursor.fetchone()
    if not row:
        return None
    return int(row["id"] if isinstance(row, dict) else row[0])


def _history(cursor, organization_id: int, role_code: str) -> dict[str, int]:
    oid = int(organization_id)
    role = str(role_code)
    counts = {
        "activities": _count(
            cursor,
            "SELECT COUNT(*) AS c FROM cleaning_task_activities WHERE organization_id=%s AND role=%s",
            (oid, role),
        ),
        "shared_sessions": _count(
            cursor,
            "SELECT COUNT(*) AS c FROM cleaning_task_shared_sessions WHERE organization_id=%s AND role=%s",
            (oid, role),
        ),
        "schedule_assignments": _count(
            cursor,
            "SELECT COUNT(*) AS c FROM planned_weekly_schedule_responsibilities WHERE organization_id=%s AND role=%s",
            (oid, role),
        ),
        "shift_entries": _count(
            cursor,
            "SELECT COUNT(*) AS c FROM planned_weekly_schedule_entries WHERE organization_id=%s AND role=%s",
            (oid, role),
        ),
        "audit_events": _count(
            cursor,
            """
            SELECT COUNT(*) AS c
            FROM cleaning_task_activity_events e
            JOIN cleaning_task_activities a ON a.id = e.activity_id
            WHERE a.organization_id=%s AND a.role=%s
            """,
            (oid, role),
        ),
        "activity_items": _count(
            cursor,
            """
            SELECT COUNT(*) AS c
            FROM cleaning_task_activity_items i
            JOIN cleaning_task_activities a ON a.id = i.activity_id
            WHERE a.organization_id=%s AND a.role=%s
            """,
            (oid, role),
        ),
        "checklist_items": _count(
            cursor,
            """
            SELECT COUNT(*) AS c
            FROM task_checklist_items i
            JOIN task_checklists c ON c.id = i.checklist_id
            WHERE c.organization_id=%s AND i.task_code=%s
            """,
            (oid, role),
        ),
    }
    return {key: value for key, value in counts.items() if value}


def _outside_group_links(cursor, organization_id: int, task_code: str, allowed_group_ids: set[int]) -> int:
    cursor.execute(
        """
        SELECT group_id FROM task_activity_group_items
        WHERE organization_id=%s AND task_code=%s
        """,
        (int(organization_id), task_code),
    )
    outside = 0
    for row in cursor.fetchall() or []:
        group_id = int(row["group_id"] if isinstance(row, dict) else row[0])
        if group_id not in allowed_group_ids:
            outside += 1
    return outside


def plan_test_catalog_cleanup(cursor) -> dict[str, Any]:
    """Read-only plan. Does not delete."""
    veewash = _org_id(cursor, "veewash")
    washpro = _org_id(cursor, "washpro")
    groups: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    allowed_group_ids: set[int] = set()

    def consider_group(org_id: int | None, slug: str, code: str) -> None:
        if org_id is None:
            blockers.append({"slug": slug, "code": code, "reason": "organization missing"})
            return
        cursor.execute(
            """
            SELECT id, code, name, active FROM task_activity_groups
            WHERE organization_id=%s AND code=%s LIMIT 1
            """,
            (org_id, code),
        )
        row = cursor.fetchone()
        role = schedule_role_for_group(code)
        if not row:
            groups.append({"slug": slug, "code": code, "role": role, "status": "absent"})
            return
        group_id = int(row["id"] if isinstance(row, dict) else row[0])
        active = int(row["active"] if isinstance(row, dict) else row[2])
        history = _history(cursor, org_id, role)
        item_history = _history(cursor, org_id, code)
        problems = {**history, **{f"code_{key}": value for key, value in item_history.items()}}
        if active:
            problems["active_group"] = 1
        if problems:
            blockers.append({"slug": slug, "code": code, "role": role, "history": problems})
            return
        allowed_group_ids.add(group_id)
        groups.append(
            {
                "slug": slug,
                "organization_id": org_id,
                "id": group_id,
                "code": code,
                "role": role,
                "status": "ready",
            }
        )

    for code in VEEWASH_GROUP_CODES:
        consider_group(veewash, "veewash", code)
    for code in WASHPRO_GROUP_CODES:
        consider_group(washpro, "washpro", code)

    if veewash is None:
        blockers.append({"slug": "veewash", "reason": "organization missing"})
    else:
        for code in VEEWASH_TASK_CODES:
            cursor.execute(
                """
                SELECT id, active FROM weekly_schedule_roles
                WHERE organization_id=%s AND code=%s LIMIT 1
                """,
                (veewash, code),
            )
            row = cursor.fetchone()
            if not row:
                tasks.append({"code": code, "status": "absent"})
                continue
            active = int(row["active"] if isinstance(row, dict) else row[1])
            history = _history(cursor, veewash, code)
            outside = _outside_group_links(cursor, veewash, code, allowed_group_ids)
            if outside:
                history["outside_group_items"] = outside
            if active:
                history["active_definition"] = 1
            if history:
                blockers.append({"slug": "veewash", "code": code, "history": history})
                continue
            tasks.append(
                {
                    "code": code,
                    "organization_id": veewash,
                    "id": int(row["id"] if isinstance(row, dict) else row[0]),
                    "status": "ready",
                }
            )

    return {
        "ok": not blockers,
        "groups": groups,
        "tasks": tasks,
        "blockers": blockers,
        "ready_groups": sum(1 for row in groups if row.get("status") == "ready"),
        "ready_tasks": sum(1 for row in tasks if row.get("status") == "ready"),
    }


def apply_test_catalog_cleanup(cursor) -> dict[str, Any]:
    """Delete only rows the plan marks ready. Caller commits."""
    plan = plan_test_catalog_cleanup(cursor)
    if not plan["ok"]:
        plan["deleted"] = False
        return plan
    deleted_groups = []
    deleted_roles = []
    for group in plan["groups"]:
        if group.get("status") != "ready":
            continue
        org_id = int(group["organization_id"])
        group_id = int(group["id"])
        cursor.execute(
            "DELETE FROM task_activity_group_items WHERE organization_id=%s AND group_id=%s",
            (org_id, group_id),
        )
        cursor.execute(
            "DELETE FROM task_activity_groups WHERE organization_id=%s AND id=%s AND code=%s AND active=0",
            (org_id, group_id, group["code"]),
        )
        cursor.execute(
            "DELETE FROM weekly_schedule_roles WHERE organization_id=%s AND code=%s",
            (org_id, group["role"]),
        )
        deleted_groups.append(group["code"])
        deleted_roles.append(group["role"])
    deleted_tasks = []
    for task in plan["tasks"]:
        if task.get("status") != "ready":
            continue
        cursor.execute(
            """
            DELETE FROM weekly_schedule_roles
            WHERE organization_id=%s AND id=%s AND code=%s AND active=0
            """,
            (int(task["organization_id"]), int(task["id"]), task["code"]),
        )
        deleted_tasks.append(task["code"])
    plan["deleted"] = True
    plan["deleted_groups"] = deleted_groups
    plan["deleted_roles"] = deleted_roles
    plan["deleted_tasks"] = deleted_tasks
    return plan
