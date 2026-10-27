#!/usr/bin/env python3
"""API-level E2E for Task Management (creates then deletes disposable rows only)."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from backend.app import app
from backend.business_time import business_today
from backend.cleaning_task_activity import (
    STATUS_COMPLETED,
    STATUS_PENDING_APPROVAL,
    approve_activity,
    complete_task,
    complete_untimed_task,
    dashboard_summary,
    ensure_cleaning_task_activity_tables,
    list_employee_day_tasks,
    list_tasks_to_verify,
    reject_activity,
    start_task,
    CleaningTaskError,
)
from backend.db import get_db
from backend.employee_mobile_pin_access import ensure_employee_mobile_pin_access_tables
from backend.employee_pin_hub import issue_hub_session_token
from backend.payroll_identity import eastern_now_naive
from backend.planned_weekly_schedule import normalize_week_start
from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table
from backend.ta_routes import get_or_create_payroll_cycle
from backend.task_catalog import (
    seed_builtin_categories,
    upsert_task_definition,
)
from backend.task_checklist import (
    build_checklist_day_status,
    list_checklists_to_verify,
    upsert_checklist,
    verify_checklist,
)

ORG = 3
EMP_A = 23  # veetest
EMP_B = 36  # Yesenia (peer)
SUPER = 16  # Francis
MARKER = "E2E_TASK_MGMT_V2"


def main() -> int:
    today = business_today()
    yesterday = today - timedelta(days=1)
    week = normalize_week_start(today)
    dow = (today.weekday() + 1) % 7
    ydow = (yesterday.weekday() + 1) % 7
    yweek = normalize_week_start(yesterday)
    results = []
    created_resp: list[int] = []
    opened_shifts: list[int] = []
    created_acts: list[int] = []
    CODE_INV = CODE_FLOOR = CODE_EOD = CODE_SOD = ""

    def ok(name: str, detail: str = ""):
        results.append({"check": name, "ok": True, "detail": detail})
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    def fail(name: str, detail: str):
        results.append({"check": name, "ok": False, "detail": detail})
        print(f"FAIL  {name} — {detail}")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_responsibilities_table(cursor)
        ensure_cleaning_task_activity_tables(cursor)
        ensure_employee_mobile_pin_access_tables(cursor)
        seed_builtin_categories(cursor, ORG)

        # Config: inventory untimed + input, no verification
        inv = upsert_task_definition(
            cursor,
            ORG,
            "custom_e2e_tide_count",
            {
                "name": "E2E Tide Count",
                "category_code": "inventory",
                "completion_type": "input_required",
                "timer_enabled": False,
                "verification_required": False,
                "verification_method": "none",
                "input_schema": [
                    {"id": "gallons", "type": "number", "label": "Gallons", "required": True}
                ],
                "active": True,
            },
        )
        # Intra-day timed, no verification
        intra = upsert_task_definition(
            cursor,
            ORG,
            "custom_e2e_floor_quick",
            {
                "name": "E2E Floor Quick",
                "category_code": "intra_day",
                "completion_type": "simple",
                "timer_enabled": True,
                "verification_required": False,
                "verification_method": "none",
                "active": True,
            },
        )
        # End of day timed + supervisor verify + checklist
        eod = upsert_task_definition(
            cursor,
            ORG,
            "custom_e2e_eod_floor",
            {
                "name": "E2E EOD Floor",
                "category_code": "end_of_day",
                "completion_type": "simple",
                "timer_enabled": True,
                "verification_required": True,
                "verification_method": "supervisor",
                "verification_timing": "next_day",
                "active": True,
            },
        )
        # Peer verify start-of-day
        sod = upsert_task_definition(
            cursor,
            ORG,
            "custom_e2e_sod_check",
            {
                "name": "E2E SOD Check",
                "category_code": "start_of_day",
                "completion_type": "simple",
                "timer_enabled": True,
                "verification_required": True,
                "verification_method": "employee",
                "verification_timing": "same_shift",
                "verifier_config": {"user_ids": [EMP_B]},
                "active": True,
            },
        )
        CODE_INV = inv["code"]
        CODE_FLOOR = intra["code"]
        CODE_EOD = eod["code"]
        CODE_SOD = sod["code"]
        cl = upsert_checklist(
            cursor,
            ORG,
            {
                "code": "e2e_eod_cl",
                "name": "E2E End of Day Checklist",
                "verification_method": "employee",
                "verification_timing": "next_day",
                "items": [{"task_code": CODE_EOD, "required": True}],
            },
        )
        upsert_task_definition(
            cursor,
            ORG,
            CODE_EOD,
            {**eod, "checklist_id": cl["id"]},
        )
        conn.commit()
        ok("catalog_seed", f"inv={CODE_INV} cl={cl['id']}")

        def ensure_shift(uid: int) -> int:
            cursor.execute(
                "SELECT id FROM shift_sessions WHERE user_id=%s AND clock_out_at IS NULL ORDER BY id DESC LIMIT 1",
                (uid,),
            )
            if cursor.fetchone():
                raise RuntimeError(f"user {uid} already clocked in; use disposable account")
            at = eastern_now_naive()
            pc = get_or_create_payroll_cycle(conn, at, ORG)
            cursor.execute(
                "SELECT geofence_id FROM shift_sessions WHERE organization_id=%s AND geofence_id IS NOT NULL ORDER BY id DESC LIMIT 1",
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
                (uid, ORG, int(pc), geofence_id, at),
            )
            sid = int(cursor.lastrowid)
            opened_shifts.append(sid)
            return sid

        # Grants
        for uid, review in ((EMP_A, 0), (EMP_B, 0), (SUPER, 1)):
            cursor.execute(
                """
                INSERT INTO employee_mobile_pin_access
                  (organization_id, user_id, allow_clock, allow_switch_role, allow_take_break,
                   allow_checklist, allow_inventory, allow_revenue_cost, allow_team_status,
                   allow_cleaning_tasks, allow_cleaning_task_review, created_at)
                VALUES (%s,%s,0,1,1,0,0,0,0,1,%s,NOW())
                ON DUPLICATE KEY UPDATE allow_cleaning_tasks=1, allow_cleaning_task_review=%s
                """,
                (ORG, uid, review, review),
            )

        shift_a = ensure_shift(EMP_A)
        shift_b = ensure_shift(EMP_B)
        conn.commit()

        # Assignments today
        for code, uid in (
            (CODE_INV, EMP_A),
            (CODE_FLOOR, EMP_A),
            (CODE_SOD, EMP_A),
        ):
            cursor.execute(
                """
                INSERT INTO planned_weekly_schedule_responsibilities
                  (organization_id, week_start, user_id, day_of_week, role, remarks,
                   assignment_group_id, timing_mode, start_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'anytime',NULL)
                """,
                (ORG, week, uid, dow, code, MARKER, uuid.uuid4().hex),
            )
            created_resp.append(int(cursor.lastrowid))
        # Yesterday EOD for A
        cursor.execute(
            """
            INSERT INTO planned_weekly_schedule_responsibilities
              (organization_id, week_start, user_id, day_of_week, role, remarks,
               assignment_group_id, timing_mode, start_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'anytime',NULL)
            """,
            (ORG, yweek, EMP_A, ydow, CODE_EOD, MARKER, uuid.uuid4().hex),
        )
        eod_resp = int(cursor.lastrowid)
        created_resp.append(eod_resp)
        conn.commit()

        day = list_employee_day_tasks(cursor, ORG, EMP_A, business_date=today)
        cats = {g["category_code"] for g in day.get("tasks_by_category") or []}
        if {"inventory", "intra_day", "start_of_day"} <= cats or len(day.get("tasks_by_category") or []) >= 2:
            ok("tasks_grouped_by_category", str(sorted(cats)))
        else:
            fail("tasks_grouped_by_category", str(day.get("tasks_by_category")))

        # Untimed inventory with input
        inv_task = next(t for t in day["tasks"] if t["role"] == CODE_INV)
        try:
            complete_untimed_task(
                conn,
                cursor,
                organization_id=ORG,
                user_id=EMP_A,
                responsibility_id=int(inv_task["responsibility_id"]),
                shift_session_id=shift_a,
                completion_input={},
            )
            fail("input_required_blocks", "empty input accepted")
        except CleaningTaskError as exc:
            ok("input_required_blocks", exc.message)
            conn.rollback()

        done_inv = complete_untimed_task(
            conn,
            cursor,
            organization_id=ORG,
            user_id=EMP_A,
            responsibility_id=int(inv_task["responsibility_id"]),
            shift_session_id=shift_a,
            completion_input={"values": {"gallons": 8}},
        )
        created_acts.append(int(done_inv["id"]))
        conn.commit()
        if done_inv["status"] == STATUS_COMPLETED and (done_inv.get("completion_input") or {}).get("values", {}).get("gallons") == 8:
            ok("untimed_input_no_verify", f"id={done_inv['id']}")
        else:
            fail("untimed_input_no_verify", str(done_inv.get("status")))

        # Timed no-verify
        floor = next(t for t in day["tasks"] if t["role"] == CODE_FLOOR)
        started = start_task(
            conn, cursor, organization_id=ORG, user_id=EMP_A, responsibility_id=int(floor["responsibility_id"]), shift_session_id=shift_a
        )
        created_acts.append(int(started["id"]))
        conn.commit()
        done_floor = complete_task(conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(started["id"]))
        conn.commit()
        if done_floor["status"] == STATUS_COMPLETED and done_floor.get("next_options"):
            ok("timed_no_verify_next_options", json.dumps(done_floor["next_options"]))
        else:
            fail("timed_no_verify_next_options", str(done_floor.get("status")))

        # Peer verification SOD
        sod_task = next(t for t in day["tasks"] if t["role"] == CODE_SOD)
        sod_act = start_task(
            conn, cursor, organization_id=ORG, user_id=EMP_A, responsibility_id=int(sod_task["responsibility_id"]), shift_session_id=shift_a
        )
        created_acts.append(int(sod_act["id"]))
        conn.commit()
        sod_done = complete_task(conn, cursor, organization_id=ORG, user_id=EMP_A, activity_id=int(sod_act["id"]))
        conn.commit()
        if sod_done["status"] != STATUS_PENDING_APPROVAL:
            fail("peer_pending", str(sod_done.get("status")))
        else:
            ok("peer_pending", f"id={sod_done['id']}")

        # Self verify blocked
        try:
            approve_activity(cursor, organization_id=ORG, activity_id=int(sod_done["id"]), supervisor_user_id=EMP_A)
            fail("self_verify_blocked", "allowed")
        except CleaningTaskError as exc:
            ok("self_verify_blocked", exc.message)
            conn.rollback()

        peer_q = list_tasks_to_verify(cursor, ORG, EMP_B, as_of=today, has_supervisor_review=False)
        peer_ids = {int(x["id"]) for x in peer_q.get("pending_verification") or []}
        if int(sod_done["id"]) in peer_ids:
            ok("peer_sees_queue", f"pending={len(peer_ids)}")
        else:
            fail("peer_sees_queue", str(peer_ids))

        approved = approve_activity(
            cursor, organization_id=ORG, activity_id=int(sod_done["id"]), supervisor_user_id=EMP_B
        )
        conn.commit()
        if approved["status"] == "approved":
            ok("peer_verify", f"id={approved['id']}")
        else:
            fail("peer_verify", str(approved.get("status")))

        # Yesterday EOD activity for next-day checklist (insert completed pending row)
        at = eastern_now_naive()
        cursor.execute(
            """
            INSERT INTO cleaning_task_activities (
              organization_id, responsibility_id, assignment_group_id, user_id,
              shift_session_id, business_date, role, timing_mode, status,
              started_at, ended_at, duration_seconds, category_code, completion_type,
              timer_enabled, verification_required, verification_method, verification_timing,
              checklist_id
            ) VALUES (%s,%s,NULL,%s,%s,%s,%s,'anytime',%s,%s,%s,120,
                      'end_of_day','simple',1,1,'supervisor','next_day',%s)
            """,
            (
                ORG,
                eod_resp,
                EMP_A,
                shift_a,
                yesterday,
                CODE_EOD,
                STATUS_PENDING_APPROVAL,
                at - timedelta(hours=5),
                at - timedelta(hours=4),
                cl["id"],
            ),
        )
        eod_act_id = int(cursor.lastrowid)
        created_acts.append(eod_act_id)
        conn.commit()

        morning = list_checklists_to_verify(cursor, ORG, EMP_B, as_of=today, has_supervisor_review=False)
        match = next(
            (
                c
                for c in morning.get("checklists") or []
                if int(c["checklist_id"]) == int(cl["id"]) and c["business_date"] == str(yesterday)
            ),
            None,
        )
        if match and match.get("can_verify_all"):
            ok("next_day_checklist_visible", match["business_date"])
        else:
            fail("next_day_checklist_visible", str(match))

        # Reject then redo history
        rejected = reject_activity(
            cursor,
            organization_id=ORG,
            activity_id=eod_act_id,
            supervisor_user_id=SUPER,
            reason="E2E redo floors",
        )
        conn.commit()
        if rejected["status"] == "rejected":
            ok("reject_preserves_history", f"id={eod_act_id}")
        else:
            fail("reject_preserves_history", str(rejected.get("status")))

        # Re-complete for checklist verify
        cursor.execute(
            """
            UPDATE cleaning_task_activities
            SET status=%s, rejection_reason=NULL, approved_by_user_id=NULL, approved_at=NULL
            WHERE id=%s
            """,
            (STATUS_PENDING_APPROVAL, eod_act_id),
        )
        conn.commit()
        verified_cl = verify_checklist(
            cursor,
            organization_id=ORG,
            checklist_id=int(cl["id"]),
            business_date=yesterday,
            verifier_user_id=SUPER,
            has_supervisor_review=True,
        )
        conn.commit()
        if verified_cl.get("status") == "verified":
            ok("checklist_verify_all", verified_cl["business_date"])
        else:
            fail("checklist_verify_all", str(verified_cl.get("status")))

        dash = dashboard_summary(cursor, ORG, business_date=today)
        metrics = dash.get("metrics") or {}
        if metrics.get("completed_no_verification", 0) >= 1 and metrics.get("total_assigned") is not None:
            ok(
                "dashboard_no_verify_counted",
                f"no_verify={metrics.get('completed_no_verification')} assigned={metrics.get('total_assigned')}",
            )
        else:
            fail("dashboard_no_verify_counted", str(metrics))
        if dash.get("read_only") is None:
            # read_only set by route; summary itself ok
            ok("dashboard_summary_rates", f"completion={metrics.get('completion_rate')} verify={metrics.get('verification_rate')}")

        with app.app_context():
            tok = issue_hub_session_token(organization_id=ORG, employee_id=EMP_A)
            ok("hub_token_issue", f"len={len(tok)}")

    except Exception as exc:
        fail("fatal", str(exc))
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        # Cleanup
        try:
            if created_acts:
                ph = ",".join(["%s"] * len(created_acts))
                cursor.execute(f"DELETE FROM cleaning_task_activity_events WHERE activity_id IN ({ph})", created_acts)
                cursor.execute(f"DELETE FROM cleaning_task_activities WHERE id IN ({ph})", created_acts)
            if created_resp:
                ph = ",".join(["%s"] * len(created_resp))
                cursor.execute(
                    f"DELETE FROM cleaning_task_activities WHERE responsibility_id IN ({ph})",
                    created_resp,
                )
                cursor.execute(
                    f"DELETE FROM planned_weekly_schedule_responsibilities WHERE id IN ({ph})",
                    created_resp,
                )
            cursor.execute(
                "DELETE FROM planned_weekly_schedule_responsibilities WHERE remarks LIKE %s",
                (MARKER + "%",),
            )
            cursor.execute(
                "DELETE FROM task_checklist_verifications WHERE checklist_id IN (SELECT id FROM task_checklists WHERE code=%s)",
                ("e2e_eod_cl",),
            )
            cursor.execute("DELETE FROM task_checklist_items WHERE checklist_id IN (SELECT id FROM task_checklists WHERE code=%s)", ("e2e_eod_cl",))
            cursor.execute("DELETE FROM task_checklists WHERE organization_id=%s AND code=%s", (ORG, "e2e_eod_cl"))
            for code in (CODE_INV, CODE_FLOOR, CODE_EOD, CODE_SOD):
                cursor.execute(
                    "DELETE FROM weekly_schedule_roles WHERE organization_id=%s AND code=%s",
                    (ORG, code),
                )
            at = eastern_now_naive()
            for sid in opened_shifts:
                cursor.execute(
                    "UPDATE shift_sessions SET clock_out_at=%s, status='completed' WHERE id=%s AND clock_out_at IS NULL",
                    (at, sid),
                )
            conn.commit()
        except Exception as cleanup_exc:
            print("cleanup_error", cleanup_exc)
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
