#!/usr/bin/env python3
"""E2E: supervisor manual shared AG attribution (Francis/Yesenia) + no auto-verify.

Uses laundryapp by default when SHARED_AG_E2E_USE_PROD=1, else prefers test DB.
Cleans up disposable rows.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
if os.environ.get("MYSQL_DATABASE", "laundryapp") in {"", "laundryapp"}:
    if os.environ.get("SHARED_AG_E2E_USE_PROD", "").strip() not in {"1", "true", "yes"}:
        os.environ["MYSQL_DATABASE"] = "laundryapp_tm_shared_test"
sys.path.insert(0, str(ROOT))

try:
    import backend.db as _db

    _db._pool = None  # type: ignore[attr-defined]
except Exception:
    pass

from backend.business_time import business_today
from backend.cleaning_task_activity import get_activity, dashboard_summary
from backend.cleaning_task_group_execution import ensure_group_activity_schema
from backend.cleaning_task_manual_completion import (
    ensure_manual_completion_schema,
    record_manual_completion,
)
from backend.db import get_db
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import (
    EXECUTION_SHARED,
    ensure_responsibilities_table,
)
from backend.task_activity_groups import upsert_activity_group
from backend.task_catalog import seed_builtin_categories, upsert_task_definition

ORG = 3
FRANCIS = 16
YESENIA = 36
SUPERVISOR = 15


def main() -> int:
    results = []

    def ok(name, detail=""):
        results.append({"check": name, "ok": True, "detail": detail})
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    def fail(name, detail=""):
        results.append({"check": name, "ok": False, "detail": detail})
        print(f"FAIL  {name} — {detail}")

    today = business_today()
    week = normalize_week_start(today)
    dow = (today.weekday() + 1) % 7
    suffix = uuid.uuid4().hex[:6]
    codes = {
        "floor": f"custom_man_floor_{suffix}",
        "washer": f"custom_man_washer_{suffix}",
        "lint": f"custom_man_lint_{suffix}",
    }
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    created_resp = []
    created_ags = []
    created_roles = list(codes.values())
    created_acts = []
    gid = None

    try:
        ensure_responsibilities_table(cur)
        ensure_group_activity_schema(cur)
        ensure_manual_completion_schema(cur)
        seed_builtin_categories(cur, ORG)
        for code, name in (
            (codes["floor"], "Floor Brooming"),
            (codes["washer"], "Washer Wipe Down"),
            (codes["lint"], "Dryer Lint Cleaning"),
        ):
            upsert_task_definition(
                cur,
                ORG,
                code,
                {
                    "name": name,
                    "category_code": "intra_day",
                    "completion_type": "simple",
                    "timer_enabled": True,
                    "verification_required": True,
                    "verification_method": "employee",
                    "active": True,
                },
            )
        group = upsert_activity_group(
            cur,
            ORG,
            {
                "name": f"Routine Cleaning {suffix}",
                "category_code": "intra_day",
                "items": [
                    {"task_code": codes["floor"], "required": True},
                    {"task_code": codes["washer"], "required": True},
                    {"task_code": codes["lint"], "required": True},
                ],
            },
        )
        created_ags.append(group["id"])
        created_roles.append(group["role_code"])
        gid = uuid.uuid4().hex
        resp_by_user = {}
        for uid in (FRANCIS, YESENIA):
            cur.execute(
                """
                INSERT INTO planned_weekly_schedule_responsibilities
                  (organization_id, week_start, day_of_week, user_id, role,
                   assignment_group_id, timing_mode, start_time, execution_mode)
                VALUES (%s,%s,%s,%s,%s,%s,'anytime',NULL,%s)
                """,
                (ORG, week, dow, uid, group["role_code"], gid, EXECUTION_SHARED),
            )
            rid = int(cur.lastrowid)
            created_resp.append(rid)
            resp_by_user[uid] = rid
        conn.commit()

        completed_at = datetime(2026, 10, 28, 10, 15, 0)
        act = record_manual_completion(
            conn,
            cur,
            organization_id=ORG,
            supervisor_user_id=SUPERVISOR,
            responsibility_id=resp_by_user[FRANCIS],
            employee_user_id=FRANCIS,
            completed_at=completed_at,
            started_at=datetime(2026, 10, 28, 10, 0, 0),
            reason="Employees forgot PIN app after shared cleaning",
            remarks="Supervisor backfill",
            shared_item_completions=[
                {"task_code": codes["floor"], "completed_by_user_id": FRANCIS},
                {"task_code": codes["washer"], "completed_by_user_id": YESENIA},
                {"task_code": codes["lint"], "completed_by_user_id": FRANCIS},
            ],
            business_date=today,
        )
        conn.commit()
        created_acts.append(act["id"])
        session_id = act.get("shared_session_id")

        # Attribution on shared session items
        cur.execute(
            """
            SELECT task_code, completed_by_user_id, status
            FROM cleaning_task_shared_session_items
            WHERE organization_id=%s AND shared_session_id=%s
            """,
            (ORG, int(session_id or 0)),
        )
        rows = {r["task_code"]: r for r in (cur.fetchall() or [])}
        if (
            int(rows.get(codes["floor"], {}).get("completed_by_user_id") or 0) == FRANCIS
            and int(rows.get(codes["washer"], {}).get("completed_by_user_id") or 0) == YESENIA
            and int(rows.get(codes["lint"], {}).get("completed_by_user_id") or 0) == FRANCIS
        ):
            ok("shared_per_item_attribution", "Francis/Yesenia/Francis")
        else:
            fail("shared_per_item_attribution", str(rows))

        # Parent AG timer may complete without verification; item children must still need verify.
        refreshed = get_activity(cur, ORG, int(act["id"]))
        cur.execute(
            """
            SELECT id, role, status, approved_by_user_id FROM cleaning_task_activities
            WHERE organization_id=%s AND parent_activity_id=%s
            """,
            (ORG, int(act["id"])),
        )
        children = cur.fetchall() or []
        # Also include Yesenia's item children
        cur.execute(
            """
            SELECT id, role, status, approved_by_user_id FROM cleaning_task_activities
            WHERE organization_id=%s AND assignment_group_id=%s AND activity_kind='group_item'
            """,
            (ORG, gid),
        )
        children = cur.fetchall() or []
        pending_children = [
            c for c in children if str(c.get("status")) == "pending_approval" and c.get("approved_by_user_id") is None
        ]
        if str(refreshed.get("completion_source")) == "manual" and (
            str(refreshed.get("status")) in {"completed", "pending_approval"}
            and (pending_children or str(refreshed.get("status")) == "pending_approval")
        ):
            ok(
                "manual_not_auto_verified",
                f"parent={refreshed.get('status')} pending_items={len(pending_children)}",
            )
        else:
            fail(
                "manual_not_auto_verified",
                f"parent={refreshed.get('status')} children={children}",
            )

        # Dashboard shared checklist attribution
        dash = dashboard_summary(cur, ORG, business_date=today, role=group["role_code"])
        shared = [r for r in (dash.get("shared_assignments") or []) if r.get("assignment_group_id") == gid]
        if len(shared) == 1:
            ok("dashboard_counts_once")
            sci = {i["task_code"]: i for i in (shared[0].get("shared_checklist_items") or [])}
            if (
                sci.get(codes["floor"], {}).get("completed_by_user_id") == FRANCIS
                and sci.get(codes["washer"], {}).get("completed_by_user_id") == YESENIA
            ):
                ok("dashboard_shared_attribution")
            else:
                fail("dashboard_shared_attribution", str(sci))
            if shared[0].get("activity_group_items"):
                ok("dashboard_exposes_group_templates", str(len(shared[0]["activity_group_items"])))
            else:
                fail("dashboard_exposes_group_templates")
            if shared[0].get("members") and len(shared[0]["members"]) == 2:
                ok("dashboard_exposes_members")
            else:
                fail("dashboard_exposes_members", str(shared[0].get("members")))
        else:
            fail("dashboard_counts_once", str(shared))

        # Audit events exist
        cur.execute(
            """
            SELECT event_type FROM cleaning_task_activity_events
            WHERE organization_id=%s AND activity_id=%s
            """,
            (ORG, int(act["id"])),
        )
        types = {r["event_type"] for r in (cur.fetchall() or [])}
        if "manual_completed" in types and "manual_shared_item_attributed" in types:
            ok("audit_events_present", str(sorted(types)))
        else:
            # attributions may be on Yesenia's activity
            cur.execute(
                """
                SELECT event_type FROM cleaning_task_activity_events
                WHERE organization_id=%s AND event_type LIKE 'manual_shared%%'
                  AND activity_id IN (
                    SELECT id FROM cleaning_task_activities WHERE organization_id=%s AND assignment_group_id=%s
                  )
                """,
                (ORG, ORG, gid),
            )
            types2 = {r["event_type"] for r in (cur.fetchall() or [])}
            if "manual_shared_item_attributed" in types2:
                ok("audit_events_present", str(sorted(types | types2)))
            else:
                fail("audit_events_present", str(types | types2))

    finally:
        if gid:
            cur.execute(
                "SELECT id FROM cleaning_task_activities WHERE organization_id=%s AND assignment_group_id=%s",
                (ORG, gid),
            )
        else:
            cur.execute("SELECT id FROM cleaning_task_activities WHERE 1=0")
        for row in cur.fetchall() or []:
            created_acts.append(int(row["id"]))
        for aid in set(created_acts):
            cur.execute("DELETE FROM cleaning_task_activity_items WHERE activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activity_events WHERE activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activities WHERE parent_activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activities WHERE id=%s", (aid,))
        cur.execute(
            "DELETE FROM cleaning_task_shared_session_items WHERE organization_id=%s AND task_code LIKE 'custom_man_%%'",
            (ORG,),
        )
        cur.execute(
            "DELETE s FROM cleaning_task_shared_sessions s LEFT JOIN cleaning_task_shared_session_items i ON i.shared_session_id=s.id WHERE s.organization_id=%s AND i.id IS NULL",
            (ORG,),
        )
        for rid in created_resp:
            cur.execute("DELETE FROM planned_weekly_schedule_responsibilities WHERE id=%s", (rid,))
        for agid in created_ags:
            cur.execute("DELETE FROM task_activity_group_items WHERE group_id=%s", (agid,))
            cur.execute("DELETE FROM task_activity_groups WHERE id=%s", (agid,))
        for code in created_roles:
            cur.execute(
                "UPDATE weekly_schedule_roles SET active=0 WHERE organization_id=%s AND code=%s",
                (ORG, code),
            )
        conn.commit()
        cur.close()
        conn.close()
        print("CLEANUP_DONE")

    failed = [r for r in results if not r["ok"]]
    print(f"SUMMARY {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
