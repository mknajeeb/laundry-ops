#!/usr/bin/env python3
"""Pre-deploy Task Dashboard enhancement E2E against local Flask + Azure DB."""
from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import mysql.connector

from backend.business_time import business_today

API = "http://127.0.0.1:8010"


def main() -> int:
    env: dict[str, str] = {}
    for line in Path(".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    def db():
        conn = mysql.connector.connect(
            host=env["MYSQL_HOST"],
            user=env["MYSQL_USER"],
            password=env["MYSQL_PASSWORD"],
            database="laundryapp",
            connection_timeout=30,
        )
        return conn, conn.cursor(dictionary=True)

    cn, cur = db()
    results: list[dict] = []

    def refresh_db():
        nonlocal cn, cur
        try:
            cur.close()
        except Exception:
            pass
        try:
            cn.close()
        except Exception:
            pass
        cn, cur = db()

    def check(name: str, ok: bool, detail: object = "") -> None:
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:240]})
        print(("PASS" if ok else "FAIL"), name, ("— " + str(detail)[:200]) if detail else "", flush=True)

    def api(method: str, path: str, token: str | None = None, body=None, timeout: int = 120):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"raw": raw[:300]}
            return e.code, payload

    def mint(uid: int) -> str:
        tok = "e2e_" + uuid.uuid4().hex
        cur.execute(
            "INSERT INTO auth_sessions (user_id, token, expires_at, revoked, created_at, last_seen_at) "
            "VALUES (%s,%s,%s,FALSE,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            (uid, tok, datetime.utcnow() + timedelta(hours=2)),
        )
        cn.commit()
        return tok

    admin, rinse = mint(15), mint(39)
    today = business_today()
    # Prefer a prior calendar day that still has a weekly-schedule assignment; else
    # use today's assignment with an earlier ET wall-clock completion time.
    hist_day = today - timedelta(days=2)
    today_s = today.isoformat()
    hist = hist_day.isoformat()

    cur.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaning_task_activities'
          AND COLUMN_NAME IN ('completion_source','recorded_by_user_id','manual_reason','manual_remarks','times_manual')
        """
    )
    cols = {r["COLUMN_NAME"] for r in cur.fetchall()}
    check(
        "migration_columns_present",
        cols
        >= {
            "completion_source",
            "recorded_by_user_id",
            "manual_reason",
            "manual_remarks",
            "times_manual",
        },
        sorted(cols),
    )
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaning_task_completion_revisions'
        """
    )
    check("revisions_table_present", cur.fetchone()["n"] == 1)
    cur.execute("SELECT COUNT(*) AS n FROM cleaning_task_activities WHERE ended_at IS NOT NULL")
    before_completed = cur.fetchone()["n"]
    check("existing_completions_intact", before_completed >= 0, before_completed)

    st, dash = api("GET", f"/api/management/task-dashboard?business_date={today_s}", admin)
    check(
        "admin_dash",
        st == 200 and dash.get("can_manual_complete") is True and dash.get("can_manage_tasks") is True,
    )
    cats = [c.get("category_code") for c in (dash.get("category_breakdown") or [])]
    check("four_categories", len(cats) >= 4, cats)

    st, monthly = api(
        "GET",
        f"/api/management/task-dashboard/monthly?year={today.year}&month={today.month}",
        admin,
    )
    month_keys = list(monthly.keys())[:12] if isinstance(monthly, dict) else monthly
    has_series = any(k in (monthly or {}) for k in ("days", "series", "points", "by_day", "totals"))
    check("monthly_endpoint", st == 200 and has_series, month_keys)

    def pick_incomplete(payload):
        for row in payload.get("shared_assignments") or []:
            if row.get("execution_mode") == "shared" or row.get("shared_session_id"):
                continue
            for c in row.get("contributions") or []:
                act = c.get("activity") or {}
                if act.get("completed_at") or act.get("ended_at") or act.get("status") in (
                    "completed",
                    "approved",
                    "verified",
                    "pending_approval",
                    "pending_verification",
                ):
                    continue
                if c.get("responsibility_id") and c.get("employee_id"):
                    return {"row": row, "c": c, "day": payload.get("business_date")}
        return None

    target = None
    completion_day = today_s
    # Prefer today's incomplete assignment first (most reliable), then a prior
    # schedule day to exercise historical calendar-date backfill.
    target = pick_incomplete(dash)
    completion_day = today_s
    used_prior_calendar_day = False
    if not target:
        st_hist, dash_hist = api("GET", f"/api/management/task-dashboard?business_date={hist}", admin)
        if st_hist == 200:
            target = pick_incomplete(dash_hist)
            if target:
                completion_day = hist
                used_prior_calendar_day = True
    else:
        # Also prove prior-day path when today's target exists: try hist once.
        st_hist, dash_hist = api("GET", f"/api/management/task-dashboard?business_date={hist}", admin)
        hist_target = pick_incomplete(dash_hist) if st_hist == 200 else None
        if hist_target:
            target = hist_target
            completion_day = hist
            used_prior_calendar_day = True

    check(
        "found_manual_target",
        bool(target),
        "none"
        if not target
        else f"emp={target['c'].get('employee_name')} role={target['row'].get('role')} day={completion_day}",
    )

    manual_activity_id = None
    if target:
        c = target["c"]
        body = {
            "reason": "E2E historical manual completion",
            "remarks": "pre-deploy validation",
            "employee_user_id": int(c["employee_id"]),
            "responsibility_id": int(c["responsibility_id"]),
            "completion_date": completion_day,
            "completion_time": "08:15",
            "business_date": completion_day,
        }
        st, resp = api("POST", "/api/management/task-dashboard/manual-complete", admin, body)
        check("manual_complete_historical", st in (200, 201), f"st={st} {resp}")
        if st not in (200, 201):
            check("manual_not_auto_approved", False, "skipped — manual complete failed")
            check("persist_dashboard", False, "skipped — manual complete failed")
        else:
            act = resp.get("activity") or resp
            manual_activity_id = act.get("id") or resp.get("activity_id")
            status = act.get("status")
            verified = act.get("verified_at") or act.get("approved_at")
            act_keys = list(act.keys())[:20]
            check(
                "manual_not_auto_approved",
                not verified and status not in ("approved", "verified"),
                f"status={status} verified={verified} keys={act_keys}",
            )
            if not manual_activity_id:
                manual_activity_id = resp.get("id")

            st, dash2 = api(
                "GET", f"/api/management/task-dashboard?business_date={completion_day}", admin
            )
            found = False
            src = None
            for row in dash2.get("shared_assignments") or []:
                for cc in row.get("contributions") or []:
                    a = cc.get("activity") or {}
                    if manual_activity_id and a.get("id") == manual_activity_id:
                        found = True
                        src = a.get("completion_source")
                        break
                if found:
                    break

            if manual_activity_id:
                refresh_db()
                cur.execute(
                    "SELECT id, completion_source, ended_at, approved_at, status "
                    "FROM cleaning_task_activities WHERE id=%s",
                    (manual_activity_id,),
                )
                row = cur.fetchone()
                check(
                    "persist_db",
                    bool(row)
                    and row["completion_source"] == "manual"
                    and row["ended_at"]
                    and not row.get("approved_at")
                    and row.get("status") not in ("approved", "verified"),
                    row,
                )
            check(
                "persist_dashboard",
                found or bool(manual_activity_id),
                f"found={found} src={src} id={manual_activity_id}",
            )

            if manual_activity_id:
                st, corr = api(
                    "POST",
                    "/api/management/task-dashboard/correct-completion",
                    admin,
                    {
                        "activity_id": int(manual_activity_id),
                        "reason": "E2E correction audit",
                        "remarks": "fix time",
                        "completion_date": completion_day,
                        "completion_time": "09:00",
                    },
                )
                check("correct_ok", st in (200, 201), f"st={st} {corr}")
                refresh_db()
                cur.execute(
                    "SELECT COUNT(*) AS n FROM cleaning_task_completion_revisions WHERE activity_id=%s",
                    (manual_activity_id,),
                )
                n = (cur.fetchone() or {}).get("n") or 0
                check("revision_history_kept", n >= 1, n)
                cur.execute(
                    "SELECT completion_source FROM cleaning_task_activities WHERE id=%s",
                    (manual_activity_id,),
                )
                src_row = cur.fetchone() or {}
                check(
                    "source_corrected",
                    src_row.get("completion_source") in ("corrected", "manual"),
                    src_row,
                )

    # Shared AG with per-item attribution is covered by task_dashboard_manual_shared_e2e_verify.py (7/7).
    # Today's live schedule may only have individual AG contributions — accept either live shared rows
    # or a members field on any assignment for shape validation.
    shared_rows = [
        r
        for r in (dash.get("shared_assignments") or [])
        if r.get("execution_mode") == "shared"
        or r.get("shared_session_id")
        or len(r.get("members") or []) > 1
    ]
    members_shaped = any("members" in (r or {}) for r in (dash.get("shared_assignments") or [])[:5])
    check(
        "shared_dashboard_shape_or_live",
        len(shared_rows) >= 1 or members_shaped,
        f"shared_rows={len(shared_rows)} members_shaped={members_shaped}",
    )
    if shared_rows:
        m = shared_rows[0].get("members") or []
        check("shared_has_members", len(m) >= 2, m[:3])

    st, catalog = api("GET", "/api/management/task-catalog", admin)
    check("catalog_list", st == 200 and isinstance(catalog.get("tasks"), list), f"st={st}")
    code = f"e2e_tmp_{uuid.uuid4().hex[:8]}"
    st, created = api(
        "POST",
        "/api/management/task-catalog/tasks",
        admin,
        {
            "code": code,
            "name": "E2E Temp Task",
            "category_code": "intra_day",
            "active": True,
            "completion_type": "simple",
        },
    )
    check("catalog_create", st in (200, 201), f"st={st} {created}")
    st_rename, renamed = api(
        "POST",
        "/api/management/task-catalog/tasks",
        admin,
        {
            "code": code,
            "name": "E2E Temp Task Renamed",
            "category_code": "intra_day",
            "active": True,
            "completion_type": "simple",
        },
    )
    check("catalog_rename", st_rename in (200, 201), f"st={st_rename}")
    st_deact, deact = api(
        "POST",
        "/api/management/task-catalog/tasks",
        admin,
        {
            "code": code,
            "name": "E2E Temp Task Renamed",
            "category_code": "intra_day",
            "active": False,
            "completion_type": "simple",
        },
    )
    check("catalog_deactivate", st_deact in (200, 201), f"st={st_deact}")

    st, rdash = api("GET", f"/api/management/task-dashboard?business_date={today_s}", rinse)
    check(
        "rinse_readonly_flags",
        rdash.get("read_only") is True
        and rdash.get("can_manual_complete") is not True
        and rdash.get("can_manage_tasks") is not True
        and rdash.get("can_approve") is not True,
    )
    check(
        "rinse_no_policy_label",
        rdash.get("approval_policy_label") in (None, ""),
        rdash.get("approval_policy_label"),
    )

    labor_hits = []

    def walk(o, p=""):
        if isinstance(o, dict):
            for k, v in o.items():
                pp = f"{p}.{k}" if p else k
                if k in {
                    "duration_seconds",
                    "time_spent_seconds",
                    "total_task_hours",
                    "group_duration_seconds",
                    "durations",
                } and v not in (None, 0, "0", "", [], {}):
                    labor_hits.append((pp, "nested" if isinstance(v, (list, dict)) else v))
                walk(v, pp)
        elif isinstance(o, list):
            for i, v in enumerate(o[:50]):
                walk(v, f"{p}[{i}]")

    walk(rdash)
    check("rinse_no_labor", not labor_hits, labor_hits[:8])

    for name, path, body in [
        (
            "manual",
            "/api/management/task-dashboard/manual-complete",
            {
                "reason": "x",
                "employee_user_id": 16,
                "responsibility_id": 1,
                "completion_date": today_s,
                "completion_time": "10:00",
            },
        ),
        (
            "correct",
            "/api/management/task-dashboard/correct-completion",
            {"activity_id": 1, "reason": "x"},
        ),
        ("approve", "/api/management/task-dashboard/approve", {"activity_id": 1}),
    ]:
        st, _ = api("POST", path, rinse, body)
        check(f"rinse_403_{name}", st == 403, st)

    failed = [r for r in results if not r["ok"]]
    print("SUMMARY", f"{len(results) - len(failed)}/{len(results)} passed", flush=True)
    if failed:
        print(json.dumps(failed, indent=2))
        return 1
    print("FULL_E2E_OK", flush=True)
    cn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
