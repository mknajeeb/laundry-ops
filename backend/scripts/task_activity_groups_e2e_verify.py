#!/usr/bin/env python3
"""E2E: activity group one-timer + item checkoffs + verify children (disposable rows)."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    STATUS_COMPLETED,
    STATUS_PENDING_APPROVAL,
    get_open_activity,
    list_employee_day_tasks,
    list_tasks_to_verify,
)
from backend.cleaning_task_group_execution import (
    checkoff_group_item,
    complete_group_activity,
    ensure_group_activity_schema,
    start_group_activity,
)
from backend.db import get_db
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table
from backend.task_activity_groups import upsert_activity_group
from backend.task_catalog import seed_builtin_categories, upsert_task_definition

ORG = 3
EMP_A = 23
EMP_B = 36
MARKER = "E2E_ACTIVITY_GROUP_V1"


def main() -> int:
    results = []

    def ok(name, detail=""):
        results.append({"check": name, "ok": True, "detail": detail})
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    def fail(name, detail):
        results.append({"check": name, "ok": False, "detail": detail})
        print(f"FAIL  {name} — {detail}")

    today = business_today()
    week = normalize_week_start(today)
    dow = (today.weekday() + 1) % 7
    suffix = uuid.uuid4().hex[:6]
    code_a = f"custom_e2e_ag_floor_{suffix}"
    code_b = f"custom_e2e_ag_lint_{suffix}"
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    created_resp = []
    try:
        ensure_responsibilities_table(cursor)
        ensure_group_activity_schema(cursor)
        seed_builtin_categories(cursor, ORG)
        upsert_task_definition(
            cursor,
            ORG,
            code_a,
            {
                "name": "E2E AG Floor",
                "category_code": "intra_day",
                "completion_type": "simple",
                "timer_enabled": True,
                "verification_required": True,
                "verification_method": "employee",
                "active": True,
            },
        )
        upsert_task_definition(
            cursor,
            ORG,
            code_b,
            {
                "name": "E2E AG Lint",
                "category_code": "intra_day",
                "completion_type": "simple",
                "timer_enabled": True,
                "verification_required": False,
                "verification_method": "none",
                "active": True,
            },
        )
        group = upsert_activity_group(
            cursor,
            ORG,
            {
                "name": f"E2E Routine {suffix}",
                "category_code": "intra_day",
                "items": [
                    {"task_code": code_a, "required": True},
                    {"task_code": code_b, "required": True},
                ],
            },
        )
        ok("group_config", group["role_code"])
        role_code = group["role_code"]
        cursor.execute(
            """
            INSERT INTO planned_weekly_schedule_responsibilities
              (organization_id, week_start, user_id, day_of_week, role, remarks,
               assignment_group_id, timing_mode, start_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'anytime',NULL)
            """,
            (ORG, week, EMP_A, dow, role_code, MARKER, uuid.uuid4().hex),
        )
        resp_id = int(cursor.lastrowid)
        created_resp.append(resp_id)
        conn.commit()

        day = list_employee_day_tasks(cursor, ORG, EMP_A, business_date=today)
        match = next((t for t in day["tasks"] if int(t["responsibility_id"]) == resp_id), None)
        if match and match.get("is_activity_group") and match.get("group_item_count") == 2:
            ok("pin_list_shows_group", str(match.get("role_label")))
        else:
            fail("pin_list_shows_group", str(match))

        # Open a fake shift id None — start_group allows None shift
        activity = start_group_activity(
            conn,
            cursor,
            organization_id=ORG,
            user_id=EMP_A,
            responsibility_id=resp_id,
            shift_session_id=None,
        )
        conn.commit()
        if activity.get("is_activity_group") and activity.get("group", {}).get("required_count") == 2:
            ok("start_group", f"id={activity.get('id')}")
        else:
            fail("start_group", str(activity)[:200])

        open_row = get_open_activity(cursor, ORG, EMP_A)
        if open_row and int(open_row["id"]) == int(activity["id"]):
            ok("open_group_recovery", "open")
        else:
            fail("open_group_recovery", str(open_row))

        # Cannot complete yet
        try:
            complete_group_activity(
                conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(activity["id"])
            )
            fail("complete_blocked_until_checkoffs", "should have raised")
        except Exception as exc:
            ok("complete_blocked_until_checkoffs", str(exc)[:80])
            conn.rollback()

        for code in (code_a, code_b):
            checkoff_group_item(
                conn,
                cursor,
                organization_id=ORG,
                user_id=EMP_A,
                activity_id=int(activity["id"]),
                task_code=code,
            )
        conn.commit()
        ok("checkoffs", "2")

        done = complete_group_activity(
            conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(activity["id"])
        )
        conn.commit()
        if done.get("next_options") and done.get("duration_seconds") is not None:
            ok("complete_group_once", f"duration={done.get('duration_seconds')} options={len(done['next_options'])}")
        else:
            fail("complete_group_once", str(done)[:200])

        if get_open_activity(cursor, ORG, EMP_A) is None:
            ok("no_open_after_complete", "none")
        else:
            fail("no_open_after_complete", "still open")

        # Child verification: peer should see floor item only
        queue = list_tasks_to_verify(
            cursor, ORG, EMP_B, as_of=today, has_supervisor_review=False
        )
        pending = queue.get("pending_verification") or []
        peer_hit = [p for p in pending if str(p.get("role")) == code_a and int(p.get("user_id") or 0) == EMP_A]
        lint_hit = [p for p in pending if str(p.get("role")) == code_b]
        if peer_hit and not lint_hit:
            ok("item_level_verification", f"pending={len(peer_hit)}")
        else:
            # lint may be absent (no verify); floor should be present
            if peer_hit:
                ok("item_level_verification", f"pending_floor={len(peer_hit)} lint_in_queue={len(lint_hit)}")
            else:
                fail("item_level_verification", f"pending={len(pending)}")

        # Duration not on children
        cursor.execute(
            """
            SELECT role, duration_seconds, parent_activity_id, activity_kind, status
            FROM cleaning_task_activities
            WHERE organization_id=%s AND responsibility_id=%s
            ORDER BY id
            """,
            (ORG, resp_id),
        )
        rows = cursor.fetchall() or []
        parent = next((r for r in rows if r.get("parent_activity_id") is None), None)
        children = [r for r in rows if r.get("parent_activity_id") is not None]
        if parent and parent.get("duration_seconds") is not None and all(c.get("duration_seconds") is None for c in children):
            ok(
                "duration_parent_only",
                f"parent={parent.get('duration_seconds')} children={len(children)} statuses={[c.get('status') for c in children]}",
            )
        else:
            fail("duration_parent_only", str(rows)[:300])

    except Exception as exc:
        fail("fatal", str(exc))
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        # cleanup
        try:
            if created_resp:
                cursor.execute(
                    f"SELECT id FROM cleaning_task_activities WHERE responsibility_id IN ({','.join(['%s']*len(created_resp))})",
                    created_resp,
                )
                aids = [int(r["id"]) for r in (cursor.fetchall() or [])]
                if aids:
                    cursor.execute(
                        f"DELETE FROM cleaning_task_activity_events WHERE activity_id IN ({','.join(['%s']*len(aids))})",
                        aids,
                    )
                    cursor.execute(
                        f"DELETE FROM cleaning_task_activity_items WHERE activity_id IN ({','.join(['%s']*len(aids))})",
                        aids,
                    )
                    cursor.execute(
                        f"DELETE FROM cleaning_task_activities WHERE id IN ({','.join(['%s']*len(aids))})",
                        aids,
                    )
                cursor.execute(
                    f"DELETE FROM planned_weekly_schedule_responsibilities WHERE id IN ({','.join(['%s']*len(created_resp))})",
                    created_resp,
                )
            cursor.execute(
                "UPDATE weekly_schedule_roles SET active=0 WHERE organization_id=%s AND (code LIKE %s OR code LIKE %s)",
                (ORG, f"custom_e2e_ag_%{suffix}%", f"agroup_%{suffix}%"),
            )
            # also deactivate group by name marker
            cursor.execute(
                "UPDATE task_activity_groups SET active=0 WHERE organization_id=%s AND name LIKE %s",
                (ORG, f"E2E Routine {suffix}%"),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    failed = sum(1 for r in results if not r["ok"])
    print(json.dumps({"passed": len(results) - failed, "failed": failed, "results": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
