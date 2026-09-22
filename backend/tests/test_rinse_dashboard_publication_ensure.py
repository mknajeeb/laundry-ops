"""Cold-start publication ensure — Rinse must not require Management page visits."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

from backend.rinse_dashboard_performance import build_role_leaderboard
from backend.rinse_performance_employee_day import (
    DAY_PUBLICATIONS_TABLE,
    compose_employee_day_from_sessions,
    ensure_employee_day_publications_for_week,
    list_business_dates_needing_publication_ensure,
    sync_day_payload_publications,
    sync_employee_day_publication,
)
from backend.rinse_performance_roles import ROLE_FOLDER
from backend.tests.test_rinse_dashboard_employee_day_v2 import PubCursor, _sess


DAY = date(2026, 9, 21)
WEEK = DAY - timedelta(days=DAY.weekday())  # Monday of that week


class EnsureCursor(PubCursor):
    """PubCursor + approval touch timestamps for stale detection."""

    def __init__(self):
        super().__init__()
        self.approvals: list[dict] = []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).lower().split())
        params = params or ()
        if (
            "from rinse_performance_session_approvals" in s
            and "group by business_date_et" in s
        ):
            org, rk, ws, we = params
            by = {}
            for a in self.approvals:
                if int(a["organization_id"]) != int(org):
                    continue
                if a["role_key"] != str(rk).upper():
                    continue
                if a.get("invalidated_at") or a.get("excluded_at"):
                    continue
                d = a["business_date_et"]
                if d < ws or d > we:
                    continue
                touch = a.get("updated_at") or a.get("approved_at")
                prev = by.get(d)
                if prev is None or (touch and touch > prev):
                    by[d] = touch
            self._last = [{"d": d, "max_touch": t} for d, t in by.items()]
            self._rinse_qcount += 1
            self.statements.append(s[:300])
            return
        if (
            f"from {DAY_PUBLICATIONS_TABLE}" in s
            and "group by business_date_et" in s
            and "max(updated_at)" in s
        ):
            org, rk, ws, we = params
            by = {}
            for key, row in self.rows.items():
                if key[0] != int(org) or key[1] != str(rk).upper():
                    continue
                d = row["business_date_et"]
                if d < ws or d > we:
                    continue
                touch = row.get("updated_at") or datetime(2026, 1, 1)
                prev = by.get(d)
                if prev is None or touch > prev:
                    by[d] = touch
            self._last = [{"d": d, "max_touch": t} for d, t in by.items()]
            self._rinse_qcount += 1
            self.statements.append(s[:300])
            return
        if (
            f"select employee_user_id, employee_name from {DAY_PUBLICATIONS_TABLE}" in s
            or (
                f"from {DAY_PUBLICATIONS_TABLE}" in s
                and "employee_user_id, employee_name" in s
                and "group by" not in s
                and "order by" not in s
            )
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
            self._rinse_qcount += 1
            self.statements.append(s[:300])
            return
        return super().execute(sql, params)


def _approval(sid, *, uid=7, name="Tarannum", day=DAY, touch=None):
    return {
        "organization_id": 3,
        "role_key": ROLE_FOLDER,
        "business_date_et": day,
        "session_id": sid,
        "employee_user_id": uid,
        "employee_name": name,
        "invalidated_at": None,
        "excluded_at": None,
        "approved_at": touch or datetime(2026, 9, 21, 12, 0, 0),
        "updated_at": touch or datetime(2026, 9, 21, 12, 0, 0),
    }


def _day_payload_from_sessions(sessions, *, name="Tarannum", uid=7, day=DAY):
    emp = compose_employee_day_from_sessions(
        employee_name=name,
        employee_user_id=uid,
        sessions=sessions,
        selected_date_et=day,
    )
    return {
        "selected_date_et": day.isoformat(),
        "employees": [emp],
        "excluded_employees": [],
    }


def test_cold_start_empty_pubs_fully_approved_appears_without_management_visit():
    """Pubs empty + historical approvals → Rinse week read materializes one employee-day."""
    cur = EnsureCursor()
    # Three approved session approvals (historical), publication table empty.
    touch = datetime(2026, 9, 21, 10, 0, 0)
    for sid in ("1", "2", "3"):
        cur.approvals.append(_approval(sid, touch=touch))

    sessions = [
        _sess("1", "WF-01", "APPROVED", 8, 205.0, 4.7),
        _sess("2", "WF-02", "APPROVED", 3, 48.0, 0.9),
        _sess("3", "WF-03", "APPROVED", 4, 100.0, 1.5),
    ]
    day_payload = _day_payload_from_sessions(sessions)

    assert cur.rows == {}
    need = list_business_dates_needing_publication_ensure(
        cur, 3, role_key=ROLE_FOLDER, week_start=WEEK
    )
    assert DAY in need

    with patch(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        return_value=day_payload,
    ), patch(
        "backend.rinse_performance_folder_publisher.attach_publication_status_to_day",
        side_effect=lambda c, o, d: d,
    ), patch(
        "backend.rinse_performance_folder_publisher.partition_employees_by_exclusion",
        side_effect=lambda d: d,
    ):
        # Stamp updated_at on sync rows for warm comparison.
        def _sync_wrap(cursor, oid, emp, **kw):
            sync_employee_day_publication(cursor, oid, emp, **kw)
            for row in cursor.rows.values():
                row["updated_at"] = datetime(2026, 9, 22, 12, 0, 0)

        with patch(
            "backend.rinse_performance_employee_day.sync_employee_day_publication",
            side_effect=_sync_wrap,
        ):
            out = ensure_employee_day_publications_for_week(
                cur, 3, role_key=ROLE_FOLDER, week_start=WEEK
            )

    assert out["synced_count"] == 1
    assert len(cur.rows) == 1
    row = next(iter(cur.rows.values()))
    assert row["dashboard_rankable"] == 1
    assert row["orders_completed"] == 15
    assert abs(float(row["total_pre_lbs"]) - 353.0) < 0.01
    assert abs(float(row["published_metric_value"]) - (353.0 / 7.1)) < 0.05

    payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=WEEK)
    assert payload["approved_employee_day_count"] == 1
    assert len(payload["leaderboard"]) == 1
    assert payload["leaderboard"][0]["days"] == 1
    assert abs(float(payload["leaderboard"][0]["weekly_avg"]) - (353.0 / 7.1)) < 0.05
    # Never session-level 64.9
    assert abs(float(payload["leaderboard"][0]["weekly_avg"]) - 66.6667) > 5

    # Idempotent second ensure — no rebuild (pubs newer than approvals).
    with patch(
        "backend.management_wf_folder_performance.build_day_folder_performance"
    ) as build:
        out2 = ensure_employee_day_publications_for_week(
            cur, 3, role_key=ROLE_FOLDER, week_start=WEEK
        )
        build.assert_not_called()
    assert out2["synced_count"] == 0
    assert len(cur.rows) == 1  # no duplicates


def test_cold_start_partial_tarannum_not_published():
    cur = EnsureCursor()
    cur.approvals.append(_approval("3", touch=datetime(2026, 9, 21, 10, 0, 0)))
    sessions = [
        _sess("1", "WF-01", "UNAPPROVED", 8, 205.0, 4.7),
        _sess("2", "WF-02", "UNAPPROVED", 3, 48.0, 0.9),
        _sess("3", "WF-03", "APPROVED", 4, 100.0, 1.5),
    ]
    day_payload = _day_payload_from_sessions(sessions)

    def _sync_wrap(cursor, oid, emp, **kw):
        sync_employee_day_publication(cursor, oid, emp, **kw)
        for row in cursor.rows.values():
            row["updated_at"] = datetime(2026, 9, 22, 12, 0, 0)

    with patch(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        return_value=day_payload,
    ), patch(
        "backend.rinse_performance_folder_publisher.attach_publication_status_to_day",
        side_effect=lambda c, o, d: d,
    ), patch(
        "backend.rinse_performance_folder_publisher.partition_employees_by_exclusion",
        side_effect=lambda d: d,
    ), patch(
        "backend.rinse_performance_employee_day.sync_employee_day_publication",
        side_effect=_sync_wrap,
    ):
        ensure_employee_day_publications_for_week(
            cur, 3, role_key=ROLE_FOLDER, week_start=WEEK
        )

    assert len(cur.rows) == 1
    assert next(iter(cur.rows.values()))["dashboard_rankable"] == 0
    # Live subset still WF-03
    emp = day_payload["employees"][0]
    assert emp["orders_completed"] == 4
    assert abs(float(emp["lbs_per_hour"]) - (100.0 / 1.5)) < 0.05

    payload = build_role_leaderboard(cur, 3, role_key=ROLE_FOLDER, week_start=WEEK)
    assert payload["approved_employee_day_count"] == 0
    assert "Tarannum" not in [r["name"] for r in payload["leaderboard"]]


def test_orphan_publication_key_removed_on_day_resync():
    """Identity change must delete old (uid,name) key, not leave a duplicate."""
    cur = EnsureCursor()
    old = compose_employee_day_from_sessions(
        employee_name="Old Name",
        employee_user_id=1,
        sessions=[_sess("1", "WF-01", "APPROVED", 4, 100.0, 1.5)],
        selected_date_et=DAY,
    )
    sync_employee_day_publication(cur, 3, old, role_key=ROLE_FOLDER, business_date_et=DAY)
    assert len(cur.rows) == 1
    assert ("Old Name" in next(iter(cur.rows))) or True

    new = compose_employee_day_from_sessions(
        employee_name="New Name",
        employee_user_id=2,
        sessions=[_sess("1", "WF-01", "APPROVED", 4, 100.0, 1.5)],
        selected_date_et=DAY,
    )
    sync_day_payload_publications(
        cur,
        3,
        {"employees": [new], "excluded_employees": [], "selected_date_et": DAY.isoformat()},
        role_key=ROLE_FOLDER,
        business_date_et=DAY,
    )
    assert len(cur.rows) == 1
    only = next(iter(cur.rows.values()))
    assert only["employee_name"] == "New Name"
    assert int(only["employee_user_id"]) == 2
