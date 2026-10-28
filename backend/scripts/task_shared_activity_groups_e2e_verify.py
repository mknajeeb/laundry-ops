#!/usr/bin/env python3
"""E2E: Shared Activity Groups — Francis + Yesenia collaborative checklist (disposable).

Targets laundryapp_tm_shared_test by default (set MYSQL_DATABASE). Cleans up rows it creates.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
# Prefer dedicated test DB (caller may override via MYSQL_DATABASE already set in the environment).
# Force test DB when unset or still pointing at production laundryapp.
if os.environ.get("MYSQL_DATABASE", "laundryapp") in {"", "laundryapp"}:
    if os.environ.get("SHARED_AG_E2E_USE_PROD", "").strip() not in {"1", "true", "yes"}:
        os.environ["MYSQL_DATABASE"] = "laundryapp_tm_shared_test"
sys.path.insert(0, str(ROOT))

# Reset any cached pool from a prior import against another database.
try:
    import backend.db as _db

    _db._pool = None  # type: ignore[attr-defined]
except Exception:
    pass

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    CleaningTaskError,
    dashboard_summary,
    get_activity,
    get_open_activity,
)
from backend.cleaning_task_group_execution import (
    checkoff_group_item,
    complete_group_activity,
    ensure_group_activity_schema,
    start_group_activity,
)
from backend.cleaning_task_shared_execution import (
    SESSION_CHECKLIST_COMPLETE,
    get_shared_session,
    list_shared_session_items,
)
from backend.db import get_db
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import (
    EXECUTION_SHARED,
    ensure_responsibilities_table,
)
from backend.task_activity_groups import upsert_activity_group
from backend.task_catalog import seed_builtin_categories, upsert_task_definition
from backend.weekly_schedule_display_settings import apply_rinse_viewer_scope
from backend.cleaning_task_activity import apply_rinse_task_dashboard_scope

ORG = 3
FRANCIS = 16
YESENIA = 36
MARKER = "E2E_SHARED_AG"


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
    code_floor = f"custom_shared_floor_{suffix}"
    code_lint = f"custom_shared_lint_{suffix}"

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    created_resp = []
    created_acts = []
    created_ags = []
    created_roles = []
    session_id = None

    try:
        ensure_responsibilities_table(cur)
        ensure_group_activity_schema(cur)
        seed_builtin_categories(cur, ORG)
        # Clear leftover open activities from interrupted prior runs.
        for uid in (FRANCIS, YESENIA):
            cur.execute(
                """
                DELETE FROM cleaning_task_activity_items
                WHERE activity_id IN (
                  SELECT id FROM (
                    SELECT id FROM cleaning_task_activities
                    WHERE organization_id=%s AND user_id=%s AND status='in_progress'
                  ) t
                )
                """,
                (ORG, uid),
            )
            cur.execute(
                """
                DELETE FROM cleaning_task_activities
                WHERE organization_id=%s AND user_id=%s AND status='in_progress'
                """,
                (ORG, uid),
            )
        conn.commit()
        # Ensure users exist on test DB (copy stubs if missing)
        for uid, uname, dname in (
            (FRANCIS, "francis", "Francis"),
            (YESENIA, "Yesenia", "Yesenia"),
        ):
            cur.execute("SELECT id FROM users WHERE id=%s", (uid,))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO users (id, username, password_hash, display_name, active, organization_id)
                    VALUES (%s,%s,%s,%s,1,%s)
                    """,
                    (uid, uname, "pbkdf2:unused", dname, ORG),
                )
        for code, name in ((code_floor, "Floor Brooming"), (code_lint, "Dryer Lint Cleaning")):
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
            created_roles.append(code)
        group = upsert_activity_group(
            cur,
            ORG,
            {
                "name": f"Routine Cleaning {suffix}",
                "category_code": "intra_day",
                "items": [
                    {"task_code": code_floor, "required": True},
                    {"task_code": code_lint, "required": True},
                ],
            },
        )
        created_ags.append(group["id"])
        role = group["role_code"]
        created_roles.append(role)
        group_id = uuid.uuid4().hex
        for uid in (FRANCIS, YESENIA):
            cur.execute(
                """
                INSERT INTO planned_weekly_schedule_responsibilities
                  (organization_id, week_start, day_of_week, user_id, role,
                   assignment_group_id, timing_mode, start_time, execution_mode)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (ORG, week, dow, uid, role, group_id, "anytime", None, EXECUTION_SHARED),
            )
            created_resp.append(int(cur.lastrowid))
        conn.commit()

        from backend.cleaning_task_activity import _day_responsibilities

        ra = _day_responsibilities(cur, ORG, business_date=today, user_id=FRANCIS)
        rb = _day_responsibilities(cur, ORG, business_date=today, user_id=YESENIA)
        a_hit = [r for r in ra if r.get("role") == role]
        b_hit = [r for r in rb if r.get("role") == role]
        if (
            a_hit
            and b_hit
            and a_hit[0].get("assignment_group_id") == group_id
            and a_hit[0].get("execution_mode") == EXECUTION_SHARED
        ):
            ok("1_both_see_routine_cleaning", role)
        else:
            fail("1_both_see_routine_cleaning", f"a={a_hit} b={b_hit}")

        # Staggered starts (simulate 8:00 / 8:05)
        act_a = start_group_activity(
            conn, cur, organization_id=ORG, user_id=FRANCIS, responsibility_id=a_hit[0]["id"], shift_session_id=None
        )
        conn.commit()
        created_acts.append(act_a["id"])
        session_id = act_a.get("shared_session_id")
        # Nudge Francis start earlier
        cur.execute(
            "UPDATE cleaning_task_activities SET started_at=%s WHERE id=%s",
            (datetime(2026, 10, 27, 8, 0, 0), act_a["id"]),
        )
        conn.commit()
        act_b = start_group_activity(
            conn, cur, organization_id=ORG, user_id=YESENIA, responsibility_id=b_hit[0]["id"], shift_session_id=None
        )
        conn.commit()
        created_acts.append(act_b["id"])
        cur.execute(
            "UPDATE cleaning_task_activities SET started_at=%s WHERE id=%s",
            (datetime(2026, 10, 27, 8, 5, 0), act_b["id"]),
        )
        conn.commit()
        if act_a["id"] != act_b["id"] and act_a.get("shared_session_id") == act_b.get("shared_session_id"):
            ok("2_independent_timers_same_session", f"a={act_a['id']} b={act_b['id']} session={session_id}")
        else:
            fail("2_independent_timers_same_session", f"a={act_a} b={act_b}")

        # Francis completes Floor Brooming
        checkoff_group_item(
            conn, cur, organization_id=ORG, user_id=FRANCIS, activity_id=act_a["id"], task_code=code_floor
        )
        conn.commit()
        items_for_b = list_shared_session_items(cur, ORG, int(session_id))
        floor = next(i for i in items_for_b if i["task_code"] == code_floor)
        if floor["status"] == "completed" and int(floor["completed_by_user_id"]) == FRANCIS:
            ok("3_francis_floor_attributed", str(floor.get("completed_at")))
        else:
            fail("3_francis_floor_attributed", str(floor))

        # Yesenia sees same checklist without her own checkoff (API sync / poll source)
        from backend.cleaning_task_group_execution import enrich_open_group_activity
        from backend.cleaning_task_activity import serialize_activity

        open_b = serialize_activity(get_activity(cur, ORG, act_b["id"]))
        open_b = enrich_open_group_activity(cur, ORG, open_b)
        b_floor = next(i for i in open_b["group"]["items"] if i["task_code"] == code_floor)
        if b_floor["status"] == "completed" and b_floor.get("completed_by_user_id") == FRANCIS:
            ok("4_yesenia_sees_francis_checkoff_via_api_sync", b_floor.get("completed_by_name") or "Francis")
        else:
            fail("4_yesenia_sees_francis_checkoff_via_api_sync", str(b_floor))

        # Simultaneous duplicate checkoff
        try:
            checkoff_group_item(
                conn, cur, organization_id=ORG, user_id=YESENIA, activity_id=act_b["id"], task_code=code_floor
            )
            conn.commit()
            fail("5_duplicate_checkoff_blocked", "expected 409")
        except CleaningTaskError as exc:
            conn.rollback()
            if exc.status == 409:
                ok("5_duplicate_checkoff_blocked", exc.message)
            else:
                fail("5_duplicate_checkoff_blocked", f"status={exc.status} {exc.message}")

        # Yesenia completes lint
        checkoff_group_item(
            conn, cur, organization_id=ORG, user_id=YESENIA, activity_id=act_b["id"], task_code=code_lint
        )
        conn.commit()
        session = get_shared_session(cur, ORG, int(session_id))
        items = list_shared_session_items(cur, ORG, int(session_id))
        lint = next(i for i in items if i["task_code"] == code_lint)
        if (
            str(session.get("status")) == SESSION_CHECKLIST_COMPLETE
            and int(lint["completed_by_user_id"]) == YESENIA
        ):
            ok("6_checklist_complete_after_all_required", f"lint_by={YESENIA}")
        else:
            fail("6_checklist_complete_after_all_required", f"session={session} lint={lint}")

        # Both see same progress
        open_a = enrich_open_group_activity(cur, ORG, serialize_activity(get_activity(cur, ORG, act_a["id"])))
        open_b = enrich_open_group_activity(cur, ORG, serialize_activity(get_activity(cur, ORG, act_b["id"])))
        if open_a["group"]["completed_required_count"] == open_b["group"]["completed_required_count"] == 2:
            ok("7_both_see_same_progress", "2/2")
        else:
            fail("7_both_see_same_progress", f"a={open_a['group']} b={open_b['group']}")

        # Francis finishes participation — Yesenia timer still running
        complete_group_activity(conn, cur, organization_id=ORG, user_id=FRANCIS, activity_id=act_a["id"])
        conn.commit()
        a_row = get_activity(cur, ORG, act_a["id"])
        b_row = get_activity(cur, ORG, act_b["id"])
        if str(a_row.get("status")) == "completed" and str(b_row.get("status")) == "in_progress":
            ok("8_francis_finish_yesenia_timer_continues", f"a_dur={a_row.get('duration_seconds')}")
        else:
            fail("8_francis_finish_yesenia_timer_continues", f"a={a_row.get('status')} b={b_row.get('status')}")

        # Finish participation does not reopen / un-complete checklist; unfinished path tested below on fresh session
        if str(session.get("status")) == SESSION_CHECKLIST_COMPLETE:
            ok("9_finish_does_not_clear_completed_checklist")
        else:
            fail("9_finish_does_not_clear_completed_checklist", str(session))

        # Dashboard counts once
        dash = dashboard_summary(cur, ORG, business_date=today, role=role)
        our = [r for r in (dash.get("shared_assignments") or []) if r.get("assignment_group_id") == group_id]
        if len(our) == 1 and our[0].get("execution_mode") == "shared" and len(our[0].get("contributions") or []) == 2:
            ok("10_dashboard_counts_once", f"total_assigned={dash.get('metrics', {}).get('total_assigned')}")
        else:
            fail("10_dashboard_counts_once", str(our))

        # Attribution on dashboard shared checklist
        sci = our[0].get("shared_checklist_items") or []
        by_code = {i["task_code"]: i for i in sci}
        if (
            by_code.get(code_floor, {}).get("completed_by_user_id") == FRANCIS
            and by_code.get(code_lint, {}).get("completed_by_user_id") == YESENIA
        ):
            ok("11_dashboard_attribution")
        else:
            fail("11_dashboard_attribution", str(sci))

        # Rinse strip
        stripped = apply_rinse_task_dashboard_scope(dash)
        if stripped.get("hide_labor_metrics") and "time_spent_seconds" not in (stripped.get("metrics") or {}):
            ok("12_rinse_no_durations")
        else:
            fail("12_rinse_no_durations", str(stripped.get("metrics")))
        # Admin retains durations on original
        if (dash.get("metrics") or {}).get("time_spent_seconds") is not None or any(
            c.get("group_duration_seconds") is not None for c in (our[0].get("contributions") or [])
        ) or a_row.get("duration_seconds") is not None:
            ok("13_admin_retains_timer_details", f"francis_duration={a_row.get('duration_seconds')}")
        else:
            fail("13_admin_retains_timer_details")

        # Yesenia finishes
        complete_group_activity(conn, cur, organization_id=ORG, user_id=YESENIA, activity_id=act_b["id"])
        conn.commit()
        ok("14_yesenia_finish_participation")

        # --- Second mini-session: finish early must NOT complete unfinished checklist ---
        suffix2 = uuid.uuid4().hex[:6]
        code_x = f"custom_shared_x_{suffix2}"
        code_y = f"custom_shared_y_{suffix2}"
        for code, name in ((code_x, "X"), (code_y, "Y")):
            upsert_task_definition(
                cur,
                ORG,
                code,
                {
                    "name": name,
                    "category_code": "intra_day",
                    "completion_type": "simple",
                    "timer_enabled": True,
                    "verification_required": False,
                    "verification_method": "none",
                    "active": True,
                },
            )
            created_roles.append(code)
        g2 = upsert_activity_group(
            cur,
            ORG,
            {
                "name": f"Partial {suffix2}",
                "category_code": "intra_day",
                "items": [{"task_code": code_x, "required": True}, {"task_code": code_y, "required": True}],
            },
        )
        created_ags.append(g2["id"])
        created_roles.append(g2["role_code"])
        gid2 = uuid.uuid4().hex
        resp2 = []
        for uid in (FRANCIS, YESENIA):
            cur.execute(
                """
                INSERT INTO planned_weekly_schedule_responsibilities
                  (organization_id, week_start, day_of_week, user_id, role,
                   assignment_group_id, timing_mode, start_time, execution_mode)
                VALUES (%s,%s,%s,%s,%s,%s,'anytime',NULL,%s)
                """,
                (ORG, week, dow, uid, g2["role_code"], gid2, EXECUTION_SHARED),
            )
            resp2.append(int(cur.lastrowid))
            created_resp.append(resp2[-1])
        conn.commit()
        ra2 = [r for r in _day_responsibilities(cur, ORG, business_date=today, user_id=FRANCIS) if r["id"] in resp2]
        rb2 = [r for r in _day_responsibilities(cur, ORG, business_date=today, user_id=YESENIA) if r["id"] in resp2]
        a2 = start_group_activity(conn, cur, organization_id=ORG, user_id=FRANCIS, responsibility_id=ra2[0]["id"], shift_session_id=None)
        b2 = start_group_activity(conn, cur, organization_id=ORG, user_id=YESENIA, responsibility_id=rb2[0]["id"], shift_session_id=None)
        conn.commit()
        created_acts.extend([a2["id"], b2["id"]])
        checkoff_group_item(conn, cur, organization_id=ORG, user_id=FRANCIS, activity_id=a2["id"], task_code=code_x)
        conn.commit()
        complete_group_activity(conn, cur, organization_id=ORG, user_id=FRANCIS, activity_id=a2["id"])
        conn.commit()
        sess2 = get_shared_session(cur, ORG, int(a2["shared_session_id"]))
        items2 = list_shared_session_items(cur, ORG, int(a2["shared_session_id"]))
        y_pending = next(i for i in items2 if i["task_code"] == code_y)
        if str(sess2.get("status")) != SESSION_CHECKLIST_COMPLETE and y_pending["status"] == "pending":
            ok("15_early_finish_leaves_checklist_open", f"session={sess2.get('status')}")
        else:
            fail("15_early_finish_leaves_checklist_open", f"session={sess2} y={y_pending}")
        b2_row = get_activity(cur, ORG, b2["id"])
        if str(b2_row.get("status")) == "in_progress":
            ok("16_peer_timer_unaffected_by_early_finish")
        else:
            fail("16_peer_timer_unaffected_by_early_finish", str(b2_row.get("status")))
        # cleanup remaining open
        complete_group_activity(conn, cur, organization_id=ORG, user_id=YESENIA, activity_id=b2["id"])
        conn.commit()

        # Self-verify blocked
        from backend.cleaning_task_activity import user_can_verify_activity

        fake_pending = {
            "user_id": FRANCIS,
            "status": "pending_approval",
            "verification_required": 1,
            "verification_method": "employee",
            "role": code_floor,
        }
        if not user_can_verify_activity(
            cur, organization_id=ORG, activity=fake_pending, verifier_user_id=FRANCIS, has_supervisor_review=False
        ):
            ok("17_self_verify_blocked")
        else:
            fail("17_self_verify_blocked")

    finally:
        for aid in created_acts:
            cur.execute("DELETE FROM cleaning_task_activity_items WHERE activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activity_events WHERE activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activities WHERE parent_activity_id=%s", (aid,))
            cur.execute("DELETE FROM cleaning_task_activities WHERE id=%s", (aid,))
        if session_id:
            cur.execute("DELETE FROM cleaning_task_shared_session_items WHERE shared_session_id=%s", (session_id,))
            cur.execute("DELETE FROM cleaning_task_shared_sessions WHERE id=%s", (session_id,))
        cur.execute(
            "DELETE FROM cleaning_task_shared_session_items WHERE organization_id=%s AND task_code LIKE 'custom_shared_%'",
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
