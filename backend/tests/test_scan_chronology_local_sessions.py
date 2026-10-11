"""Scan Chronology: independent scans + local sessions (Scan Chronology only)."""

from datetime import date, datetime

import pytest
from flask import Flask

from backend import scan_chronology_local_sessions as store
from backend.rinse_operational_day import build_operational_views, chronology_payload_from_views
from backend.scan_chronology_local_sessions import apply_local_sessions

DAY = date(2026, 10, 9)
PAYROLL_TABLES = ("shift_sessions", "shift_job_segments", "time_entries", "payroll", "attendance")


def _at(h, m=0):
    return datetime(2026, 10, 9, h, m)


class FakeCursor:
    """In-memory stand-in for the local-session table; records every statement."""

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.statements: list[str] = []
        self._next_id = 1
        self._result: list[dict] = []
        self.rowcount = 0
        self.lastrowid = None

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.statements.append(text)
        head = text.upper()
        self._result = []
        self.rowcount = 0
        if head.startswith("CREATE TABLE"):
            return
        if head.startswith("INSERT"):
            org, day, name, key, role, start, end, created_by, updated_by = params
            rid = self._next_id
            self._next_id += 1
            self.rows[rid] = {
                "id": rid,
                "organization_id": org,
                "session_date_et": day,
                "employee_name": name,
                "employee_key": key,
                "role_code": role,
                "started_at_et": start,
                "ended_at_et": end,
            }
            self.lastrowid = rid
            self.rowcount = 1
            return
        if head.startswith("UPDATE"):
            day, name, key, role, start, end, _actor, org, rid = params
            row = self.rows.get(rid)
            if row and row["organization_id"] == org:
                row.update(
                    session_date_et=day,
                    employee_name=name,
                    employee_key=key,
                    role_code=role,
                    started_at_et=start,
                    ended_at_et=end,
                )
                self.rowcount = 1
            return
        if head.startswith("DELETE"):
            org, rid = params
            if rid in self.rows and self.rows[rid]["organization_id"] == org:
                del self.rows[rid]
                self.rowcount = 1
            return
        if "EMPLOYEE_KEY = %S" in head:
            org, key, role, end, start, exclude = params
            self._result = [
                {"id": r["id"]}
                for r in self.rows.values()
                if r["organization_id"] == org
                and r["employee_key"] == key
                and r["role_code"] == role
                and r["started_at_et"] < end
                and r["ended_at_et"] > start
                and r["id"] != exclude
            ][:1]
            return
        if "AND ID = %S" in head:
            org, rid = params
            row = self.rows.get(rid)
            self._result = [dict(row)] if row and row["organization_id"] == org else []
            return
        if "SESSION_DATE_ET = %S" in head:
            org, day, *rest = params
            out = [
                dict(r)
                for r in self.rows.values()
                if r["organization_id"] == org and r["session_date_et"] == day
                and (not rest or r["role_code"] == rest[0])
            ]
            self._result = sorted(out, key=lambda r: (r["started_at_et"], r["id"]))
            return
        raise AssertionError(f"unexpected SQL: {text}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _reset_table_flag(monkeypatch):
    monkeypatch.setattr(store, "_TABLE_READY", False)


def _create(cur, employee, role, start, end, org=3):
    return store.create_local_session(
        cur, org, employee=employee, role=role, start_et=start, end_et=end, actor_user_id=1
    )


def _session(sid, employee, role, start, end):
    return {"id": sid, "employee": employee, "role": role, "start_et": start, "end_et": end}


def _sort(bag, employee, ts):
    return {"bag_id": bag, "employee": employee, "sort_time_et": ts, "time_et": ts}


def _ev(bag, purpose, ts, user, rack=None):
    return {
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "rack": rack,
        "id": 1,
        "scan_index": 1,
    }


# --- 1. Scans are visible without any payroll / attendance session -----------


def test_scans_visible_when_employee_has_no_payroll_session():
    events = [
        _ev("BAG1", "sent-to-vendor", _at(5), "Portal"),
        _ev("BAG1", "weight-entry", _at(6), "Francis (Veewash)"),
        _ev("BAG1", "add-photos", _at(6, 30), "Francis (Veewash)"),
        _ev("BAG1", "start-cleaning", _at(7), "Maria Perez", "W3-30-VW"),
        _ev("BAG1", "drying", _at(8), "Maria Perez", "D2-30-VW"),
    ]
    views = build_operational_views(
        events=events,
        segments=[],
        name_index={"francis (veewash)": (16, "Francis"), "maria perez": (31, "Maria Perez")},
        selected_date_et=DAY,
        now=_at(23),
    )
    assert [r["employee"] for r in views["weighing"]] == ["Francis"]
    assert [r["employee"] for r in views["sorting"]] == ["Francis"]
    assert [r["employee"] for r in views["washer_loads"]] == ["Maria Perez"]
    assert [r["employee"] for r in views["dryer_loads"]] == ["Maria Perez"]


def test_unmapped_scanner_keeps_portal_name_instead_of_disappearing():
    events = [
        _ev("BAG2", "sent-to-vendor", _at(5), "Portal"),
        _ev("BAG2", "add-photos", _at(6), "New Temp Worker"),
    ]
    views = build_operational_views(
        events=events, segments=[], name_index={}, selected_date_et=DAY, now=_at(23)
    )
    assert len(views["sorting"]) == 1
    assert views["sorting"][0]["employee"] == "New Temp Worker"
    assert views["sorting"][0]["user_id"] is None


def test_scans_without_session_are_marked_unassigned_and_excluded():
    rows = [_sort("B1", "Francis", _at(6)), _sort("B2", "Francis", _at(9))]
    out = apply_local_sessions(
        rows, [_session(1, "Francis", "sorting", _at(5), _at(8))], stage="sorting"
    )
    assert [r["session_status"] for r in rows] == ["matched", "unassigned"]
    assert rows[1]["local_session_id"] is None
    s = out["summary"]
    assert s["total_scans"] == 2
    assert s["matched_scans"] == 1
    assert s["unassigned_scans"] == 1
    assert s["scans_per_hour"] == round(1 / 3, 2)


def test_no_sessions_keeps_every_scan_visible():
    rows = [_sort(f"B{i}", "Francis", _at(6, i)) for i in range(5)]
    out = apply_local_sessions(rows, [], stage="sorting")
    assert len(rows) == 5
    assert all(r["session_status"] == "unassigned" for r in rows)
    assert out["summary"] == {
        "total_scans": 5,
        "matched_scans": 0,
        "unassigned_scans": 5,
        "total_sessions": 0,
        "total_hours": 0.0,
        "average_per_session": None,
        "scans_per_hour": None,
    }


# --- 2. Multiple sessions calculate independently ----------------------------


def test_multiple_sessions_for_one_employee_calculate_independently():
    rows = [_sort(f"A{i}", "Francis", _at(6, i * 5)) for i in range(10)]
    rows += [_sort(f"C{i}", "Francis", _at(10, i * 10)) for i in range(3)]
    rows += [_sort("GAP", "Francis", _at(9))]
    sessions = [
        _session(1, "Francis", "sorting", _at(6), _at(8)),
        _session(2, "Francis", "sorting", _at(10), _at(11, 30)),
    ]
    out = apply_local_sessions(rows, sessions, stage="sorting")
    first, second = out["sessions"]
    assert (first["scans"], first["hours"], first["scans_per_hour"]) == (10, 2.0, 5.0)
    assert (second["scans"], second["hours"], second["scans_per_hour"]) == (3, 1.5, 2.0)
    s = out["summary"]
    assert s["total_scans"] == 14
    assert s["total_sessions"] == 2
    assert s["total_hours"] == 3.5
    assert s["average_per_session"] == 6.5
    assert s["scans_per_hour"] == round(13 / 3.5, 2)
    assert s["unassigned_scans"] == 1


def test_hours_come_from_entered_times_not_first_to_last_scan():
    rows = [_sort("B1", "Francis", _at(7)), _sort("B2", "Francis", _at(7, 10))]
    out = apply_local_sessions(
        rows, [_session(1, "Francis", "sorting", _at(6), _at(10))], stage="sorting"
    )
    assert out["sessions"][0]["hours"] == 4.0
    assert out["summary"]["scans_per_hour"] == 0.5


def test_touching_sessions_count_boundary_scan_once():
    rows = [_sort("EDGE", "Francis", _at(8))]
    sessions = [
        _session(1, "Francis", "sorting", _at(6), _at(8)),
        _session(2, "Francis", "sorting", _at(8), _at(10)),
    ]
    out = apply_local_sessions(rows, sessions, stage="sorting")
    assert sum(s["scans"] for s in out["sessions"]) == 1
    assert rows[0]["local_session_id"] == 2


# --- 3. Role switches stay role-specific -------------------------------------


def test_role_switch_counts_only_matching_role():
    sessions = [
        _session(1, "Maria Perez", "sorting", _at(6), _at(8)),
        _session(2, "Maria Perez", "washing", _at(8), _at(11)),
    ]
    sort_rows = [_sort("S1", "Maria Perez", _at(7)), _sort("S2", "Maria Perez", _at(9))]
    sort_out = apply_local_sessions(sort_rows, sessions, stage="sorting")
    assert [s["id"] for s in sort_out["sessions"]] == [1]
    assert [r["session_status"] for r in sort_rows] == ["matched", "unassigned"]
    assert sort_out["summary"]["total_hours"] == 2.0

    wash_rows = [
        {"bag_id": "W1", "employee": "Maria Perez", "timestamp_et": _at(9), "washer_rack": "W1"},
        {"bag_id": "W2", "employee": "Maria Perez", "timestamp_et": _at(7), "washer_rack": "W2"},
    ]
    wash_out = apply_local_sessions(wash_rows, sessions, stage="washing")
    assert [s["id"] for s in wash_out["sessions"]] == [2]
    assert [r["session_status"] for r in wash_rows] == ["matched", "unassigned"]
    assert wash_out["summary"]["total_hours"] == 3.0
    assert wash_out["summary"]["scans_per_hour"] == round(1 / 3, 2)


def test_scan_from_other_employee_never_matches_session():
    rows = [_sort("B1", "Harrell France", _at(7))]
    out = apply_local_sessions(
        rows, [_session(1, "Francis", "sorting", _at(6), _at(8))], stage="sorting"
    )
    assert rows[0]["session_status"] == "unassigned"
    assert out["sessions"][0]["scans"] == 0


def test_employee_filter_scopes_sessions_and_summary():
    rows = [_sort("B1", "Francis", _at(7))]
    sessions = [
        _session(1, "Francis", "sorting", _at(6), _at(8)),
        _session(2, "Maria Perez", "sorting", _at(6), _at(9)),
    ]
    out = apply_local_sessions(rows, sessions, stage="sorting", employee_filter="francis")
    assert [s["id"] for s in out["sessions"]] == [1]
    assert out["summary"]["total_hours"] == 2.0


def test_folder_rows_match_on_fold_completion():
    rows = [{"bag_id": "F1", "employee": "Yesenia", "start_et": _at(11, 50), "end_et": _at(12, 10)}]
    out = apply_local_sessions(
        rows, [_session(1, "Yesenia", "folder", _at(12), _at(14))], stage="folder"
    )
    assert out["sessions"][0]["scans"] == 1


# --- 4. Store: overlap rules, validation, edit/delete -----------------------


def test_overlapping_session_same_employee_and_role_is_rejected():
    cur = FakeCursor()
    _create(cur, "Francis", "sorting", "2026-10-09T06:00", "2026-10-09T10:00")
    with pytest.raises(ValueError, match="overlapping"):
        _create(cur, "francis", "sorting", "2026-10-09T09:00", "2026-10-09T11:00")


def test_same_employee_different_role_and_touching_sessions_allowed():
    cur = FakeCursor()
    _create(cur, "Francis", "sorting", "2026-10-09T06:00", "2026-10-09T10:00")
    _create(cur, "Francis", "washing", "2026-10-09T09:00", "2026-10-09T11:00")
    _create(cur, "Francis", "sorting", "2026-10-09T10:00", "2026-10-09T12:00")
    assert len(cur.rows) == 3


@pytest.mark.parametrize(
    "start,end,role,message",
    [
        ("2026-10-09T10:00", "2026-10-09T09:00", "sorting", "after start"),
        ("2026-10-09T22:00", "2026-10-10T02:00", "sorting", "same ET day"),
        ("2026-10-09T06:00", "2026-10-09T07:00", "payroll", "role must be"),
    ],
)
def test_invalid_sessions_rejected(start, end, role, message):
    with pytest.raises(ValueError, match=message):
        _create(FakeCursor(), "Francis", role, start, end)


def test_offset_times_convert_to_et_wall():
    cur = FakeCursor()
    row = _create(cur, "Francis", "sorting", "2026-10-09T10:00:00Z", "2026-10-09T12:00:00Z")
    assert row["start_et"] == _at(6)
    assert row["end_et"] == _at(8)
    assert row["session_date_et"] == DAY


def test_update_ignores_itself_but_still_blocks_other_overlaps():
    cur = FakeCursor()
    a = _create(cur, "Francis", "sorting", "2026-10-09T06:00", "2026-10-09T08:00")
    _create(cur, "Francis", "sorting", "2026-10-09T09:00", "2026-10-09T10:00")
    moved = store.update_local_session(
        cur, 3, a["id"], employee="Francis", role="sorting",
        start_et="2026-10-09T05:30", end_et="2026-10-09T08:30",
    )
    assert moved["start_et"] == _at(5, 30)
    with pytest.raises(ValueError, match="overlapping"):
        store.update_local_session(
            cur, 3, a["id"], employee="Francis", role="sorting",
            start_et="2026-10-09T06:00", end_et="2026-10-09T09:30",
        )


def test_other_org_cannot_edit_or_delete():
    cur = FakeCursor()
    a = _create(cur, "Francis", "sorting", "2026-10-09T06:00", "2026-10-09T08:00")
    with pytest.raises(LookupError):
        store.update_local_session(
            cur, 99, a["id"], employee="Francis", role="sorting",
            start_et="2026-10-09T06:00", end_et="2026-10-09T07:00",
        )
    with pytest.raises(LookupError):
        store.delete_local_session(cur, 99, a["id"])
    assert a["id"] in cur.rows


def test_list_missing_table_returns_empty():
    class Missing(Exception):
        errno = 1146

    class Cur:
        def execute(self, *_a, **_k):
            raise Missing("Table doesn't exist")

    assert store.list_local_sessions(Cur(), 3, DAY) == []


# --- 5. Edit/delete only moves Scan Chronology numbers; payroll untouched ----


def _operational_rows():
    return {
        "date_et": DAY.isoformat(),
        "stage": "sorting",
        "summary": {"total_bags": 3},
        "sessions": [
            _sort("B1", "Francis", _at(6, 15)),
            _sort("B2", "Francis", _at(7, 45)),
            _sort("B3", "Francis", _at(9, 30)),
        ],
        "employees": ["Francis"],
        "machines": [],
        "grouping_rules": "",
    }


def test_edit_and_delete_change_only_chronology_summary(monkeypatch):
    from backend import rinse_operational_day
    from backend.rinse_scan_chronology import build_scan_chronology_payload

    monkeypatch.setattr(
        rinse_operational_day,
        "build_operational_chronology_payload",
        lambda *a, **k: _operational_rows(),
    )
    cur = FakeCursor()

    def summary():
        p = build_scan_chronology_payload(cur, 3, selected_date_et=DAY, stage="sorting")
        return p["local_sessions"]["summary"], p["sessions"]

    before, rows = summary()
    assert before["total_scans"] == 3 and before["unassigned_scans"] == 3
    assert len(rows) == 3

    s = _create(cur, "Francis", "sorting", "2026-10-09T06:00", "2026-10-09T08:00")
    created, _ = summary()
    assert (created["matched_scans"], created["total_hours"], created["scans_per_hour"]) == (2, 2.0, 1.0)

    store.update_local_session(
        cur, 3, s["id"], employee="Francis", role="sorting",
        start_et="2026-10-09T06:00", end_et="2026-10-09T10:00",
    )
    edited, _ = summary()
    assert (edited["matched_scans"], edited["total_hours"], edited["scans_per_hour"]) == (3, 4.0, 0.75)

    store.delete_local_session(cur, 3, s["id"])
    after, rows = summary()
    assert after["total_sessions"] == 0 and after["unassigned_scans"] == 3
    assert len(rows) == 3

    touched = " ".join(cur.statements).lower()
    assert "scan_chronology_local_sessions" in touched
    for table in PAYROLL_TABLES:
        assert table not in touched


# --- Routes ------------------------------------------------------------------


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, dictionary=False):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _client(monkeypatch, cur, roles):
    from backend import rinse_shift_analysis_routes as routes

    conn = _Conn(cur)
    monkeypatch.setattr(routes, "get_db", lambda: conn)
    app = Flask(__name__)
    routes.register_rinse_shift_analysis_routes(
        app,
        require_user=lambda _c: ({"user_id": 7, "roles": roles, "organization_id": 3}, None, None),
        require_admin=lambda _c: (None, None, None),
        user_org_id=lambda _me: 3,
        parse_date_value=lambda v: date.fromisoformat(str(v)[:10]),
    )
    return app.test_client(), conn


URL = "/rinse/shift-analysis/scan-chronology/local-sessions"
BODY = {
    "employee": "Francis",
    "role": "sorting",
    "start_et": "2026-10-09T06:00",
    "end_et": "2026-10-09T08:00",
}


def test_route_create_edit_delete_for_manager(monkeypatch):
    cur = FakeCursor()
    client, conn = _client(monkeypatch, cur, ["MANAGER"])
    resp = client.post(URL, json=BODY)
    assert resp.status_code == 200, resp.get_json()
    sid = resp.get_json()["session"]["id"]

    resp = client.post(URL, json={**BODY, "start_et": "2026-10-09T07:00", "end_et": "2026-10-09T09:00"})
    assert resp.status_code == 400
    assert "overlapping" in resp.get_json()["error"]

    resp = client.put(f"{URL}/{sid}", json={**BODY, "end_et": "2026-10-09T09:00"})
    assert resp.status_code == 200
    assert cur.rows[sid]["ended_at_et"] == _at(9)

    assert client.delete(f"{URL}/{sid}").status_code == 200
    assert client.delete(f"{URL}/{sid}").status_code == 404
    assert cur.rows == {}


def test_route_rejects_non_manager(monkeypatch):
    cur = FakeCursor()
    client, _ = _client(monkeypatch, cur, ["EMPLOYEE"])
    assert client.post(URL, json=BODY).status_code == 403
    assert cur.rows == {}
    assert cur.statements == []
