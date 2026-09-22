"""Tarannum employee-day publication — Rinse Hub must not publish partial days."""

from __future__ import annotations

from datetime import date

from backend.rinse_dashboard_performance import build_role_leaderboard, build_employee_role_history
from backend.rinse_performance_employee_day import (
    DAY_PUBLICATIONS_TABLE,
    compose_employee_day_from_sessions,
    sync_employee_day_publication,
)
from backend.rinse_performance_roles import ROLE_FOLDER


DAY = date(2026, 9, 21)


def _sess(sid, code, status, bags, lbs, hours):
    return {
        "session_id": sid,
        "session_code": code,
        "segment_id": int(sid) if str(sid).isdigit() else abs(hash(sid)) % 100000,
        "publication_status": status,
        "publication": {"status": status, "excluded": status == "EXCLUDED"},
        "orders_completed": bags,
        "total_pre_lbs": lbs,
        "performance_hours": hours,
        "lbs_per_hour": round(lbs / hours, 4) if hours else None,
        "role_status": "closed",
        "include_in_authoritative_aggregate": True,
        "start_time": "2026-09-21T08:00:00",
        "end_time": "2026-09-21T12:00:00",
        "employee": "Tarannum",
    }


def _tarannum_three():
    return [
        _sess("1", "WF-01", "UNAPPROVED", 8, 205.0, 4.7),
        _sess("2", "WF-02", "UNAPPROVED", 3, 48.0, 0.9),
        _sess("3", "WF-03", "APPROVED", 4, 100.0, 1.5),
    ]


class PubCursor:
    """Minimal cursor for publication upsert + leaderboard GROUP BY."""

    def __init__(self):
        self.rows = {}
        self._last = None
        self.executed = []
        self._rinse_qcount = 0
        self.statements = []
        self.settings = {"rinse_folding_lbs_per_hour_target": "40"}

    def execute(self, sql, params=None):
        self._rinse_qcount += 1
        s = " ".join(str(sql).lower().split())
        self.statements.append(s[:300])
        self.executed.append((s, params))
        params = params or ()
        if "create table" in s or "alter table" in s:
            self._last = None
            return
        if "information_schema" in s:
            self._last = [{"cnt": 1}]
            return
        if (
            f"from {DAY_PUBLICATIONS_TABLE}" in s
            and "employee_user_id, employee_name" in s
            and "group by" not in s
            and "order by" not in s
            and "sum(" not in s
        ):
            org, rk, biz = params
            self._last = [
                {
                    "employee_user_id": row["employee_user_id"],
                    "employee_name": row["employee_name"],
                }
                for key, row in self.rows.items()
                if key[0] == int(org)
                and key[1] == str(rk).upper()
                and key[2] == biz
            ]
            return
        if "from system_settings" in s:
            key = params[1] if len(params) > 1 else None
            val = self.settings.get(str(key))
            self._last = [{"svalue": val}] if val is not None else []
            return
        if f"delete from {DAY_PUBLICATIONS_TABLE}" in s:
            org, rk, biz, uid, name = params
            keys = [
                k
                for k in list(self.rows)
                if k[0] == int(org)
                and k[1] == str(rk).upper()
                and k[2] == biz
                and int(k[3]) == int(uid)
                and k[4] == name
            ]
            for k in keys:
                del self.rows[k]
            self._last = None
            return
        if f"insert into {DAY_PUBLICATIONS_TABLE}" in s:
            (
                org,
                rk,
                biz,
                uid,
                name,
                bags,
                lbs,
                hours,
                bags_hr,
                num,
                den,
                rate,
                inc,
                scount,
                status,
                rankable,
                sessions_json,
            ) = params[:17]
            key = (int(org), str(rk).upper(), biz, int(uid or 0), name)
            self.rows[key] = {
                "organization_id": int(org),
                "role_key": str(rk).upper(),
                "business_date_et": biz,
                "employee_user_id": int(uid or 0),
                "employee_name": name,
                "orders_completed": int(bags),
                "total_pre_lbs": float(lbs),
                "performance_hours": float(hours) if hours is not None else None,
                "bags_per_hour": float(bags_hr) if bags_hr is not None else None,
                "published_numerator": float(num),
                "published_denominator": float(den),
                "published_metric_value": float(rate) if rate is not None else None,
                "included_session_count": int(inc),
                "session_count": int(scount),
                "day_publication_status": status,
                "dashboard_rankable": int(rankable),
                "sessions_json": sessions_json,
            }
            self._last = None
            return
        if f"from {DAY_PUBLICATIONS_TABLE}" in s and "group by" in s:
            org, rk, ws, we = params[:4]
            grouped = {}
            for key, row in self.rows.items():
                if key[0] != int(org) or key[1] != str(rk).upper():
                    continue
                if not int(row.get("dashboard_rankable") or 0):
                    continue
                biz = row["business_date_et"]
                if biz < ws or biz > we:
                    continue
                gkey = (row["employee_user_id"], row["employee_name"])
                g = grouped.setdefault(
                    gkey,
                    {
                        "employee_user_id": row["employee_user_id"],
                        "employee_name": row["employee_name"],
                        "sum_num": 0.0,
                        "sum_den": 0.0,
                        "sum_bags": 0,
                        "sum_lbs": 0.0,
                        "sum_hours": 0.0,
                        "employee_day_count": 0,
                        "session_count": 0,
                    },
                )
                g["sum_num"] += float(row["published_numerator"])
                g["sum_den"] += float(row["published_denominator"])
                g["sum_bags"] += int(row["orders_completed"])
                g["sum_lbs"] += float(row["total_pre_lbs"])
                g["sum_hours"] += float(row.get("performance_hours") or 0)
                g["employee_day_count"] += 1
                g["session_count"] += int(row.get("included_session_count") or 0)
            self._last = list(grouped.values())
            return
        if f"from {DAY_PUBLICATIONS_TABLE}" in s and "order by business_date_et" in s:
            org, rk, ws, we, emp = params
            out = []
            for key, row in self.rows.items():
                if key[0] != int(org) or key[1] != str(rk).upper():
                    continue
                if row["business_date_et"] < ws or row["business_date_et"] > we:
                    continue
                if int(emp) == int(row["employee_user_id"]) or str(emp) == row["employee_name"]:
                    out.append(dict(row))
            out.sort(key=lambda r: r["business_date_et"])
            self._last = out
            return
        self._last = []

    def fetchone(self):
        if isinstance(self._last, list):
            return self._last[0] if self._last else None
        return self._last

    def fetchall(self):
        return list(self._last or [])


def test_tarannum_partial_live_ok_but_not_published():
    """WF-03-only Live Performance; Rinse Published must stay empty (no 64.9 / 1 session)."""
    sessions = _tarannum_three()
    emp = compose_employee_day_from_sessions(
        employee_name="Tarannum",
        employee_user_id=7,
        sessions=sessions,
        selected_date_et=DAY,
    )
    assert len(emp["sessions"]) == 3
    assert emp["orders_completed"] == 4
    assert abs(float(emp["total_pre_lbs"]) - 100.0) < 0.01
    assert abs(float(emp["performance_hours"]) - 1.5) < 0.01
    assert abs(float(emp["lbs_per_hour"]) - (100.0 / 1.5)) < 0.05
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False

    cur = PubCursor()
    sync_employee_day_publication(cur, 3, emp, role_key=ROLE_FOLDER, business_date_et=DAY)
    # Partial day is cached with rankable=0 for By Employee Status — not Published.
    assert len(cur.rows) == 1
    only = next(iter(cur.rows.values()))
    assert int(only["dashboard_rankable"]) == 0
    assert abs(float(only["published_metric_value"]) - (100.0 / 1.5)) < 0.05

    payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=DAY)
    names = [r["name"] for r in payload.get("leaderboard") or []]
    assert "Tarannum" not in names
    assert payload.get("approved_employee_day_count") == 0
    # Must not look like the old session board (64.9 / Sessions=1).
    assert all((r.get("days") or 0) != 1 or "Tarannum" not in str(r.get("name")) for r in payload.get("leaderboard") or [])


def test_tarannum_fully_approved_publishes_one_employee_day():
    sessions = [
        _sess("1", "WF-01", "APPROVED", 8, 205.0, 4.7),
        _sess("2", "WF-02", "APPROVED", 3, 48.0, 0.9),
        _sess("3", "WF-03", "APPROVED", 4, 100.0, 1.5),
    ]
    emp = compose_employee_day_from_sessions(
        employee_name="Tarannum",
        employee_user_id=7,
        sessions=sessions,
        selected_date_et=DAY,
    )
    assert emp["dashboard_rankable"] is True
    assert emp["orders_completed"] == 15
    assert abs(float(emp["lbs_per_hour"]) - (353.0 / 7.1)) < 0.05

    cur = PubCursor()
    sync_employee_day_publication(cur, 3, emp, role_key=ROLE_FOLDER, business_date_et=DAY)
    assert len(cur.rows) == 1
    assert next(iter(cur.rows.values()))["dashboard_rankable"] == 1

    payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=DAY)
    assert payload["approved_employee_day_count"] == 1
    assert payload["included_bags"] == 15
    assert abs(float(payload["included_pounds"]) - 353.0) < 0.01
    assert abs(float(payload["included_hours"]) - 7.1) < 0.01
    rows = payload["leaderboard"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Tarannum"
    assert rows[0]["days"] == 1
    assert rows[0]["bags"] == 15
    assert abs(float(rows[0]["weekly_avg"]) - (353.0 / 7.1)) < 0.05
    assert abs(float(rows[0]["weekly_avg"]) - 66.6667) > 5.0


def test_tarannum_disapprove_clears_published_rankable():
    sessions = [
        _sess("1", "WF-01", "APPROVED", 8, 205.0, 4.7),
        _sess("2", "WF-02", "APPROVED", 3, 48.0, 0.9),
        _sess("3", "WF-03", "APPROVED", 4, 100.0, 1.5),
    ]
    emp = compose_employee_day_from_sessions(
        employee_name="Tarannum",
        employee_user_id=7,
        sessions=sessions,
        selected_date_et=DAY,
    )
    cur = PubCursor()
    sync_employee_day_publication(cur, 3, emp, role_key=ROLE_FOLDER, business_date_et=DAY)
    assert next(iter(cur.rows.values()))["dashboard_rankable"] == 1

    sessions[2]["publication_status"] = "UNAPPROVED"
    sessions[2]["publication"] = {"status": "UNAPPROVED"}
    emp2 = compose_employee_day_from_sessions(
        employee_name="Tarannum",
        employee_user_id=7,
        sessions=sessions,
        selected_date_et=DAY,
    )
    assert emp2["day_publication_status"] == "PARTIALLY_APPROVED"
    sync_employee_day_publication(cur, 3, emp2, role_key=ROLE_FOLDER, business_date_et=DAY)
    assert next(iter(cur.rows.values()))["dashboard_rankable"] == 0

    payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=DAY)
    assert payload["approved_employee_day_count"] == 0
    assert "Tarannum" not in [r["name"] for r in payload["leaderboard"]]

    hist = build_employee_role_history(
        cur, 3, employee_id="7", role_key=ROLE_FOLDER, week_start=DAY
    )
    assert len(hist["employee_days"]) == 1
    assert hist["employee_days"][0]["status"] == "PARTIALLY_APPROVED"
    assert hist["employee_days"][0]["dashboard_rankable"] is False
    assert len(hist["employee_days"][0]["sessions"]) == 3
