#!/usr/bin/env python3
"""Safe pre-deploy verification for Cleaning / Tasks (creates then deletes test rows only)."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    approve_activity,
    complete_task,
    dashboard_summary,
    ensure_cleaning_task_activity_tables,
    get_open_activity,
    list_employee_day_tasks,
    list_supervisor_queue,
    reject_activity,
    start_task,
    CleaningTaskError,
)
from backend.db import get_db
from backend.employee_mobile_pin_access import ensure_employee_mobile_pin_access_tables
from backend.payroll_identity import eastern_now_naive
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table

ORG = 3
# Disposable test accounts — not production floor names used for live ops.
EMP_A = 23  # veetest
EMP_B = 36  # Yesenia — only used if no open shift, then we open/close ourselves
SUPER = 18  # chelci as alternate supervisor actor (approval id only; no PIN needed in-process)
MARKER = "E2E_CLEANING_TASK_PREDEPLOY"


def main() -> int:
    today = business_today()
    week = normalize_week_start(today)
    dow = (today.weekday() + 1) % 7
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    created_resp: list[int] = []
    created_acts: list[int] = []
    opened_shifts: list[int] = []
    access_backup = None
    results = []

    def ok(name: str, detail: str = ""):
        results.append({"check": name, "ok": True, "detail": detail})
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    def fail(name: str, detail: str):
        results.append({"check": name, "ok": False, "detail": detail})
        print(f"FAIL  {name} — {detail}")

    try:
        ensure_responsibilities_table(cursor)
        ensure_cleaning_task_activity_tables(cursor)
        ensure_employee_mobile_pin_access_tables(cursor)

        # Snapshot access for EMP_A
        cursor.execute(
            """
            SELECT allow_cleaning_tasks, allow_cleaning_task_review
            FROM employee_mobile_pin_access
            WHERE organization_id=%s AND user_id=%s
            """,
            (ORG, EMP_A),
        )
        access_backup = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO employee_mobile_pin_access
              (organization_id, user_id, allow_clock, allow_switch_role, allow_take_break,
               allow_checklist, allow_inventory, allow_revenue_cost, allow_team_status,
               allow_cleaning_tasks, allow_cleaning_task_review, created_at)
            VALUES (%s,%s,0,1,1,0,0,0,0,1,0,NOW())
            ON DUPLICATE KEY UPDATE
              allow_cleaning_tasks=1
            """,
            (ORG, EMP_A),
        )

        from backend.ta_routes import get_or_create_payroll_cycle

        def _ensure_open_shift(user_id: int) -> tuple[int, bool]:
            cursor.execute(
                """
                SELECT id FROM shift_sessions
                WHERE user_id=%s AND clock_out_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (int(user_id),),
            )
            existing = cursor.fetchone()
            if existing:
                # Never attach disposable cleaning tests to a live floor shift.
                raise RuntimeError(
                    f"user {user_id} already has open shift {existing['id']}; "
                    "pick a clocked-out test account"
                )
            at = eastern_now_naive()
            pc_id = get_or_create_payroll_cycle(conn, at, ORG)
            cursor.execute(
                """
                SELECT geofence_id FROM shift_sessions
                WHERE organization_id=%s AND geofence_id IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (ORG,),
            )
            gf = cursor.fetchone()
            geofence_id = int(gf["geofence_id"]) if gf and gf.get("geofence_id") is not None else 1
            cursor.execute(
                """
                INSERT INTO shift_sessions (
                  user_id, organization_id, payroll_cycle_id, geofence_id,
                  employment_category_id, clock_in_at, status
                ) VALUES (%s,%s,%s,%s,NULL,%s,'active')
                """,
                (int(user_id), ORG, int(pc_id), geofence_id, at),
            )
            sid = int(cursor.lastrowid)
            opened_shifts.append(sid)
            return sid, True

        shift_a, _ = _ensure_open_shift(EMP_A)
        shift_b, _ = _ensure_open_shift(EMP_B)

        group_id = uuid.uuid4().hex
        # Shared floor cleaning for A+B
        for uid in (EMP_A, EMP_B):
            cursor.execute(
                """
                INSERT INTO planned_weekly_schedule_responsibilities
                  (organization_id, week_start, user_id, day_of_week, role, remarks,
                   assignment_group_id, timing_mode, start_time)
                VALUES (%s,%s,%s,%s,'floor_cleaning',%s,%s,'anytime',NULL)
                """,
                (ORG, week, uid, dow, MARKER, group_id),
            )
            created_resp.append(int(cursor.lastrowid))
        # Solo lint for A
        cursor.execute(
            """
            INSERT INTO planned_weekly_schedule_responsibilities
              (organization_id, week_start, user_id, day_of_week, role, remarks,
               assignment_group_id, timing_mode, start_time)
            VALUES (%s,%s,%s,%s,'lint_cleaning',%s,%s,'before_break',NULL)
            """,
            (ORG, week, EMP_A, dow, MARKER, uuid.uuid4().hex),
        )
        created_resp.append(int(cursor.lastrowid))
        conn.commit()

        day_a = list_employee_day_tasks(cursor, ORG, EMP_A, business_date=today)
        day_b = list_employee_day_tasks(cursor, ORG, EMP_B, business_date=today)
        shared_a = [t for t in day_a["tasks"] if t.get("role") == "floor_cleaning" and t.get("shared")]
        shared_b = [t for t in day_b["tasks"] if t.get("role") == "floor_cleaning" and t.get("shared")]
        if shared_a and shared_b:
            ok("shared_visible_both", f"A={shared_a[0]['responsibility_id']} B={shared_b[0]['responsibility_id']}")
        else:
            fail("shared_visible_both", f"A={len(shared_a)} B={len(shared_b)}")

        floor_a = shared_a[0]["responsibility_id"]
        lint_a = next(t["responsibility_id"] for t in day_a["tasks"] if t["role"] == "lint_cleaning")

        # Seed a production-role segment so we can prove it closes on cleaning start.
        from backend.shift_job_tracking import get_open_job_segment, start_category_role_segment

        try:
            start_category_role_segment(
                conn,
                shift_a,
                organization_id=ORG,
                user_id=EMP_A,
                category_id=1,
                role_id=1,
                change_source="e2e_seed",
            )
            conn.commit()
        except Exception as seed_exc:
            print("role_seed_skip", seed_exc)
            try:
                conn.rollback()
            except Exception:
                pass

        before_seg = get_open_job_segment(conn, shift_a)
        act1 = start_task(
            conn, cursor, organization_id=ORG, user_id=EMP_A, responsibility_id=floor_a, shift_session_id=shift_a
        )
        created_acts.append(int(act1["id"]))
        conn.commit()
        after_seg = get_open_job_segment(conn, shift_a)
        cursor.execute("SELECT id, clock_out_at FROM shift_sessions WHERE id=%s", (shift_a,))
        shift_row = cursor.fetchone()
        if shift_row and shift_row.get("clock_out_at") is None:
            ok("shift_clock_continues", f"shift={shift_a}")
        else:
            fail("shift_clock_continues", str(shift_row))
        if before_seg and after_seg:
            fail("role_timer_paused", "open segment still present after cleaning start")
        else:
            ok("role_timer_paused", f"before={bool(before_seg)} after={bool(after_seg)}")

        # Overlap blocked: second start
        try:
            start_task(
                conn, cursor, organization_id=ORG, user_id=EMP_A, responsibility_id=lint_a, shift_session_id=shift_a
            )
            fail("overlap_blocked", "second start allowed")
        except CleaningTaskError as exc:
            ok("overlap_blocked", exc.message)
        conn.rollback()

        # B individual timer on same shared task
        act_b = start_task(
            conn, cursor, organization_id=ORG, user_id=EMP_B, responsibility_id=shared_b[0]["responsibility_id"], shift_session_id=shift_b
        )
        created_acts.append(int(act_b["id"]))
        conn.commit()
        if int(act_b["id"]) != int(act1["id"]):
            ok("shared_individual_timers", f"A={act1['id']} B={act_b['id']}")
        else:
            fail("shared_individual_timers", "same activity id")

        done = complete_task(conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(act1["id"]))
        conn.commit()
        if done["status"] == STATUS_PENDING_APPROVAL and done.get("next_options"):
            ok("complete_pending_approval", json.dumps(done["next_options"]))
        else:
            fail("complete_pending_approval", str(done.get("status")))

        queue = list_supervisor_queue(cursor, ORG, business_date=today)
        pending_ids = {
            int(x["activity"]["id"])
            for x in queue["pending_approval"]
            if x.get("activity")
        }
        if int(act1["id"]) in pending_ids:
            ok("supervisor_sees_pending", f"pending={len(pending_ids)}")
        else:
            fail("supervisor_sees_pending", str(pending_ids))

        if queue.get("approval_policy") == "per_employee_contribution":
            ok("approval_policy_per_contribution")
        else:
            fail("approval_policy_per_contribution", str(queue.get("approval_policy")))

        try:
            approve_activity(
                cursor, organization_id=ORG, activity_id=int(act1["id"]), supervisor_user_id=EMP_A
            )
            fail("self_approve_blocked", "self approve allowed")
        except CleaningTaskError as exc:
            ok("self_approve_blocked", exc.message)
        conn.rollback()

        rejected = reject_activity(
            cursor,
            organization_id=ORG,
            activity_id=int(act1["id"]),
            supervisor_user_id=SUPER,
            reason="E2E redo required",
        )
        conn.commit()
        if rejected["status"] == STATUS_REJECTED:
            ok("reject_keeps_history", f"id={rejected['id']} reason={rejected['rejection_reason']}")
        else:
            fail("reject_keeps_history", str(rejected))

        # Redo: start again — new activity, old rejected remains
        act_redo = start_task(
            conn, cursor, organization_id=ORG, user_id=EMP_A, responsibility_id=floor_a, shift_session_id=shift_a
        )
        created_acts.append(int(act_redo["id"]))
        conn.commit()
        cursor.execute(
            "SELECT id, status FROM cleaning_task_activities WHERE id IN (%s,%s) ORDER BY id",
            (int(act1["id"]), int(act_redo["id"])),
        )
        hist = cursor.fetchall() or []
        if len(hist) == 2 and any(r["status"] == STATUS_REJECTED for r in hist):
            ok("reject_redo_preserves_history", str(hist))
        else:
            fail("reject_redo_preserves_history", str(hist))

        complete_task(conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(act_redo["id"]))
        conn.commit()
        approved = approve_activity(
            cursor, organization_id=ORG, activity_id=int(act_redo["id"]), supervisor_user_id=SUPER
        )
        conn.commit()
        if approved["status"] == "approved":
            ok("supervisor_approve", f"id={approved['id']}")
        else:
            fail("supervisor_approve", str(approved))

        dash = dashboard_summary(cursor, ORG, business_date=today)
        if dash["metrics"]["total_assigned"] >= 1 and "started" in dash["metrics"]:
            ok(
                "dashboard_metrics",
                f"assigned={dash['metrics']['total_assigned']} started={dash['metrics']['started']} "
                f"pending={dash['metrics']['pending_approval']}",
            )
        else:
            fail("dashboard_metrics", str(dash["metrics"]))
        # Shared floor should appear once among our marker assignments
        marker_shared = [
            r
            for r in dash.get("shared_assignments") or []
            if r.get("role") == "floor_cleaning"
            and any(c.get("responsibility_id") in created_resp for c in r.get("contributions") or [])
        ]
        if marker_shared and marker_shared[0].get("shared") and len(marker_shared[0]["contributions"]) == 2:
            ok("dashboard_shared_once", marker_shared[0]["assignment_key"])
        else:
            fail("dashboard_shared_once", str(marker_shared))

        if dash.get("shift_end") is not None:
            ok("shift_end_present", f"blocking={len(dash['shift_end'].get('blocking_close') or [])}")
        else:
            fail("shift_end_present", "missing")

        open_after = get_open_activity(cursor, ORG, EMP_A)
        if open_after is None:
            ok("no_open_after_complete")
        else:
            fail("no_open_after_complete", str(open_after))

    except Exception as exc:
        fail("unexpected", f"{type(exc).__name__}: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        # Cleanup test rows only
        try:
            if created_acts:
                placeholders = ",".join(["%s"] * len(created_acts))
                cursor.execute(
                    f"DELETE FROM cleaning_task_activity_events WHERE activity_id IN ({placeholders})",
                    tuple(created_acts),
                )
                cursor.execute(
                    f"DELETE FROM cleaning_task_activities WHERE id IN ({placeholders})",
                    tuple(created_acts),
                )
            # Also delete any leftover activities on our responsibility ids
            if created_resp:
                placeholders = ",".join(["%s"] * len(created_resp))
                cursor.execute(
                    f"SELECT id FROM cleaning_task_activities WHERE responsibility_id IN ({placeholders})",
                    tuple(created_resp),
                )
                extra = [int(r["id"]) for r in (cursor.fetchall() or [])]
                if extra:
                    ph = ",".join(["%s"] * len(extra))
                    cursor.execute(
                        f"DELETE FROM cleaning_task_activity_events WHERE activity_id IN ({ph})",
                        tuple(extra),
                    )
                    cursor.execute(
                        f"DELETE FROM cleaning_task_activities WHERE id IN ({ph})",
                        tuple(extra),
                    )
                cursor.execute(
                    f"DELETE FROM planned_weekly_schedule_responsibilities WHERE id IN ({placeholders})",
                    tuple(created_resp),
                )
            # Close shifts we opened
            for sid in opened_shifts:
                cursor.execute(
                    "UPDATE shift_sessions SET clock_out_at=%s WHERE id=%s AND clock_out_at IS NULL",
                    (eastern_now_naive(), sid),
                )
            # Restore access
            if access_backup is None:
                cursor.execute(
                    """
                    UPDATE employee_mobile_pin_access
                    SET allow_cleaning_tasks=0
                    WHERE organization_id=%s AND user_id=%s
                    """,
                    (ORG, EMP_A),
                )
            else:
                cursor.execute(
                    """
                    UPDATE employee_mobile_pin_access
                    SET allow_cleaning_tasks=%s, allow_cleaning_task_review=%s
                    WHERE organization_id=%s AND user_id=%s
                    """,
                    (
                        access_backup.get("allow_cleaning_tasks") or 0,
                        access_backup.get("allow_cleaning_task_review") or 0,
                        ORG,
                        EMP_A,
                    ),
                )
            conn.commit()
            print("CLEANUP done")
        except Exception as cleanup_exc:
            print("CLEANUP error", cleanup_exc)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass

    failed = [r for r in results if not r["ok"]]
    print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed), "results": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
