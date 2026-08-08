"""Phase 5E — mobile Revenue & Cost section entry (approval-time DRC apply)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.drc_mobile_entry import (
    DAY_NOT_OPEN_HELPER,
    DRAFT_CONFLICT_HELPER,
    DRC_FIELD_CONFLICT_HELPER,
    NO_ASSIGNMENT_HELPER,
    SECTION_COMMERCIAL,
    SECTION_DROP_OFF,
    SECTION_RINSE,
    SECTION_SELF_SERVICE,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_RETURNED,
    STATUS_SUBMITTED,
    DrcMobileEntryError,
    ensure_section_draft,
    list_today_for_employee,
    list_weekday_section_assignments,
    review_mobile_submission,
    save_section_draft,
    save_weekday_section_assignments,
    sections_assigned_to_employee,
    submit_section,
)


TODAY = date(2026, 7, 24)  # Friday → weekday 4


def _rev(cur, org_id, on_date, section) -> int:
    row = cur.subs.get((org_id, str(on_date), section)) or {}
    return int(row.get("draft_revision") or 0)


def _save(cur, section, values, *, eid=42, org_id=3, on_date=TODAY, rev=None, note=None):
    return save_section_draft(
        cur,
        org_id,
        eid,
        section,
        values,
        note=note,
        on_date=on_date,
        expected_revision=_rev(cur, org_id, on_date, section) if rev is None else rev,
    )


def _submit(cur, section, *, eid=42, org_id=3, on_date=TODAY, rev=None):
    return submit_section(
        cur,
        org_id,
        eid,
        section,
        on_date=on_date,
        expected_revision=_rev(cur, org_id, on_date, section) if rev is None else rev,
    )


def _snap(total=30.0):
    return (
        {"cash": 10.0, "card": 20.0, "total": total},
        {
            "section_key": SECTION_SELF_SERVICE,
            "calc_version": "drc_mobile_v1",
            "line_plan": [
                {"line_key": "self_service_cash", "category": "revenue", "amount": 10.0},
                {"line_key": "self_service_card", "category": "revenue", "amount": 20.0},
            ],
            "calculated": {"cash": 10.0, "card": 20.0, "total": total},
        },
    )


class FakeCursor:
    def __init__(self):
        self.assignments = {}
        self.subs = {}
        self.events = []
        self.users = {(3, 10), (3, 11), (3, 42), (3, 99)}
        self.user_names = {10: "Alex", 11: "Sam", 42: "Jennifer", 99: "Other Org"}
        self.daily_entries = {}
        self.daily_lines = {}
        self.drc_writes = 0
        self._result = None
        self._results = []
        self.lastrowid = 0
        self.rowcount = 0
        self._next_id = 1

    def execute(self, sql, params=None):
        sql_n = " ".join(str(sql).split())
        params = params or ()
        if "CREATE TABLE IF NOT EXISTS drc_" in sql_n:
            return
        if "FROM drc_weekday_section_assignments" in sql_n and "SELECT weekday, section_key" in sql_n:
            oid = int(params[0])
            self._results = [
                {"weekday": wd, "section_key": sk, "employee_id": eid}
                for (o, wd, sk), eid in self.assignments.items()
                if o == oid
            ]
            return
        if "SELECT section_key FROM drc_weekday_section_assignments" in sql_n:
            oid, wd, eid = int(params[0]), int(params[1]), int(params[2])
            self._results = [
                {"section_key": sk}
                for (o, w, sk), e in self.assignments.items()
                if o == oid and w == wd and e == eid
            ]
            return
        if "INSERT INTO drc_weekday_section_assignments" in sql_n:
            oid, wd, sk, eid = int(params[0]), int(params[1]), params[2], params[3]
            self.assignments[(oid, wd, sk)] = None if eid is None else int(eid)
            return
        if "FROM users WHERE id=" in sql_n and "SELECT id FROM" in sql_n:
            uid, oid = int(params[0]), int(params[1])
            self._result = {"id": uid} if (oid, uid) in self.users else None
            return
        if "SELECT display_name" in sql_n:
            uid = int(params[0])
            self._result = {
                "display_name": self.user_names.get(uid, f"User {uid}"),
                "username": f"u{uid}",
                "first_name": "",
                "last_name": "",
            }
            return
        if "FROM drc_mobile_section_submissions" in sql_n and "organization_id = %s AND id = %s" in sql_n:
            oid, sid = int(params[0]), int(params[1])
            self._result = next(
                (r for r in self.subs.values() if int(r["organization_id"]) == oid and int(r["id"]) == sid),
                None,
            )
            return
        if "FROM drc_mobile_section_submissions" in sql_n and "entry_date = %s AND section_key" in sql_n:
            oid, d, sk = int(params[0]), str(params[1]), params[2]
            self._result = self.subs.get((oid, str(d)[:10], sk))
            return
        if "FROM drc_mobile_section_submissions" in sql_n and "ORDER BY entry_date" in sql_n:
            oid = int(params[0])
            self._results = [r for r in self.subs.values() if int(r["organization_id"]) == oid]
            return
        if "INSERT INTO drc_mobile_section_submissions" in sql_n:
            oid, d, sk, eid, name, status, values_json = (
                int(params[0]),
                str(params[1])[:10],
                params[2],
                int(params[3]),
                params[4],
                params[5],
                params[6],
            )
            sid = self._next_id
            self._next_id += 1
            self.lastrowid = sid
            self.subs[(oid, d, sk)] = {
                "id": sid,
                "organization_id": oid,
                "entry_date": date.fromisoformat(d),
                "section_key": sk,
                "assigned_employee_id": eid,
                "assigned_employee_name": name,
                "status": status,
                "draft_revision": 0,
                "values_json": values_json,
                "calculated_json": None,
                "rate_snapshot_json": None,
                "note": None,
                "rejection_reason": None,
                "daily_entry_id": None,
                "submitted_at": None,
                "submitted_by_user_id": None,
                "reviewed_at": None,
                "reviewed_by_user_id": None,
            }
            self.rowcount = 1
            return
        if "UPDATE drc_mobile_section_submissions" in sql_n and "calculated_json" in sql_n:
            # submit path: status, calc, snap, submitted_at, eid, sid, exp, draft, returned
            status, calc, snap, submitted_at, eid, sid, exp = params[:7]
            row = next((r for r in self.subs.values() if int(r["id"]) == int(sid)), None)
            if (
                not row
                or int(row["draft_revision"]) != int(exp)
                or str(row["status"]) not in (STATUS_DRAFT, STATUS_RETURNED, "rejected")
            ):
                self.rowcount = 0
                return
            row["status"] = status
            row["calculated_json"] = calc
            row["rate_snapshot_json"] = snap
            row["submitted_at"] = submitted_at
            row["submitted_by_user_id"] = eid
            row["rejection_reason"] = None
            row["reviewed_at"] = None
            row["reviewed_by_user_id"] = None
            self.rowcount = 1
            return
        if "UPDATE drc_mobile_section_submissions" in sql_n and "daily_entry_id = %s" in sql_n:
            status, entry_id, actor, sid, expected_status = params
            row = next((r for r in self.subs.values() if int(r["id"]) == int(sid)), None)
            if not row or str(row["status"]) != str(expected_status):
                self.rowcount = 0
                return
            row["status"] = status
            row["daily_entry_id"] = entry_id
            row["rejection_reason"] = None
            row["reviewed_by_user_id"] = actor
            self.rowcount = 1
            return
        if "UPDATE drc_mobile_section_submissions" in sql_n and "draft_revision = draft_revision + 1" in sql_n:
            if "rejection_reason" in sql_n and "reviewed_at" in sql_n:
                # return path
                status, reason, actor, sid, expected_status = params
                row = next((r for r in self.subs.values() if int(r["id"]) == int(sid)), None)
                if not row or str(row["status"]) != str(expected_status):
                    self.rowcount = 0
                    return
                row["status"] = status
                row["rejection_reason"] = reason
                row["reviewed_by_user_id"] = actor
                row["draft_revision"] = int(row["draft_revision"]) + 1
                self.rowcount = 1
                return
            # draft save
            values_json, note, status, sid, exp = params[0], params[1], params[2], int(params[3]), int(params[4])
            row = next((r for r in self.subs.values() if int(r["id"]) == sid), None)
            if not row or int(row["draft_revision"]) != exp:
                self.rowcount = 0
                return
            row["values_json"] = values_json
            row["note"] = note
            row["status"] = status
            row["draft_revision"] = int(row["draft_revision"]) + 1
            self.rowcount = 1
            return
        if "INSERT INTO drc_mobile_section_events" in sql_n:
            self.events.append(
                {
                    "submission_id": params[0],
                    "organization_id": params[1],
                    "event_type": params[2],
                    "actor_user_id": params[3],
                    "detail_json": params[4],
                }
            )
            return
        if "FROM dr_daily_entries" in sql_n and "entry_date" in sql_n:
            oid, d = int(params[0]), str(params[1])[:10]
            self._result = self.daily_entries.get((oid, d))
            return
        if "INSERT INTO dr_daily_entries" in sql_n:
            oid, d = int(params[0]), str(params[1])[:10]
            eid = self._next_id
            self._next_id += 1
            self.daily_entries[(oid, d)] = {
                "id": eid,
                "organization_id": oid,
                "entry_date": date.fromisoformat(d),
                "status": "open",
            }
            self.daily_lines[eid] = {}
            self.rowcount = 1
            return
        if "FROM dr_daily_entry_lines" in sql_n:
            entry_id = int(params[0])
            self._results = list(self.daily_lines.get(entry_id, {}).values())
            return
        if "UPDATE dr_daily_entries SET modified_by" in sql_n:
            return
        if "notification_event_definitions" in sql_n or "INSERT IGNORE INTO notification" in sql_n:
            return
        self._result = None
        self._results = []

    def fetchone(self):
        r = self._result
        self._result = None
        return r

    def fetchall(self):
        r = self._results
        self._results = []
        return r


@pytest.fixture
def cur():
    return FakeCursor()


@pytest.fixture(autouse=True)
def _patch_today():
    with patch("backend.drc_mobile_entry.business_today", return_value=TODAY), patch(
        "backend.drc_mobile_entry.business_now"
    ) as bn:
        bn.return_value = MagicMock()
        bn.return_value.replace.return_value = MagicMock(isoformat=lambda: "2026-07-24T22:14:00")
        yield


def _assign_ss(cur, eid=42):
    save_weekday_section_assignments(
        cur,
        3,
        [{"section_key": SECTION_SELF_SERVICE, "weekday": 4, "employee_id": eid}],
    )


def test_weekday_section_assignment(cur):
    save_weekday_section_assignments(
        cur,
        3,
        [
            {"section_key": SECTION_SELF_SERVICE, "weekday": 4, "employee_id": 42},
            {"section_key": SECTION_DROP_OFF, "weekday": 4, "employee_id": 10},
        ],
        actor_user_id=1,
    )
    rows = list_weekday_section_assignments(cur, 3)
    ss = next(r for r in rows if r["section_key"] == SECTION_SELF_SERVICE)
    fri = next(d for d in ss["days"] if d["weekday"] == 4)
    assert fri["employee_id"] == 42
    assert sections_assigned_to_employee(cur, 3, 42, TODAY) == [SECTION_SELF_SERVICE]


def test_different_sections_different_employees(cur):
    save_weekday_section_assignments(
        cur,
        3,
        [
            {"section_key": SECTION_SELF_SERVICE, "weekday": 4, "employee_id": 42},
            {"section_key": SECTION_RINSE, "weekday": 4, "employee_id": 10},
        ],
    )
    assert sections_assigned_to_employee(cur, 3, 42, TODAY) == [SECTION_SELF_SERVICE]
    assert sections_assigned_to_employee(cur, 3, 10, TODAY) == [SECTION_RINSE]


def test_employee_multiple_sections(cur):
    save_weekday_section_assignments(
        cur,
        3,
        [
            {"section_key": SECTION_SELF_SERVICE, "weekday": 4, "employee_id": 42},
            {"section_key": SECTION_DROP_OFF, "weekday": 4, "employee_id": 42},
        ],
    )
    assert set(sections_assigned_to_employee(cur, 3, 42, TODAY)) == {
        SECTION_SELF_SERVICE,
        SECTION_DROP_OFF,
    }


def test_unassigned_employee_denied(cur):
    _assign_ss(cur)
    with pytest.raises(DrcMobileEntryError) as ei:
        ensure_section_draft(cur, 3, 10, SECTION_SELF_SERVICE, on_date=TODAY)
    assert ei.value.status == 403


def test_organization_isolation(cur):
    _assign_ss(cur)
    assert sections_assigned_to_employee(cur, 9, 42, TODAY) == []
    with pytest.raises(DrcMobileEntryError):
        ensure_section_draft(cur, 9, 42, SECTION_SELF_SERVICE, on_date=TODAY)


def test_draft_creation_and_revisioned_autosave(cur):
    _assign_ss(cur)
    draft = ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    assert draft["draft_revision"] == 0
    saved = _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    assert saved["draft_revision"] == 1
    assert any(e["event_type"] == "draft_saved" for e in cur.events)


def test_stale_save_409_and_conflict_retry(cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 1, "card": 2})
    with pytest.raises(DrcMobileEntryError) as ei:
        _save(cur, SECTION_SELF_SERVICE, {"cash": 9, "card": 9}, rev=0)
    assert ei.value.status == 409
    assert DRAFT_CONFLICT_HELPER in str(ei.value)
    saved = _save(cur, SECTION_SELF_SERVICE, {"cash": 9, "card": 9})
    assert saved["draft_revision"] == 2


@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
def test_employee_submit_does_not_touch_drc(notify, compute, cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    out = _submit(cur, SECTION_SELF_SERVICE)
    assert out["status"] == STATUS_SUBMITTED
    assert out["pending_manager_review"] is True
    assert out["daily_entry_id"] is None
    assert cur.daily_entries == {}
    assert cur.daily_lines == {}
    assert any(e["event_type"] == "submitted" for e in cur.events)
    notify.assert_called_once()
    compute.assert_called_once()


@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
def test_stale_submit_409(notify, compute, cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    with pytest.raises(DrcMobileEntryError) as ei:
        _submit(cur, SECTION_SELF_SERVICE, rev=0)
    assert ei.value.status == 409


@patch("backend.drc_mobile_entry._apply_approved_section_from_snapshot", return_value=555)
@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
def test_manager_approval_applies_once_and_idempotent(notify, compute, apply, cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    sub = _submit(cur, SECTION_SELF_SERVICE)
    approved = review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
    assert approved["status"] == STATUS_APPROVED
    assert approved["daily_entry_id"] == 555
    assert apply.call_count == 1
    again = review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
    assert again["status"] == STATUS_APPROVED
    assert apply.call_count == 1  # idempotent, no second apply
    assert any(e["event_type"] == "approved" for e in cur.events)


@patch("backend.drc_mobile_entry._apply_approved_section_from_snapshot", return_value=555)
@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
@patch("backend.drc_mobile_entry._notify_section_returned")
def test_return_does_not_apply_and_blocks_approved_return(nret, nsub, compute, apply, cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 5, "card": 5})
    sub = _submit(cur, SECTION_SELF_SERVICE)
    returned = review_mobile_submission(
        cur, 3, sub["id"], action="return", actor_user_id=1, reason="Fix card total"
    )
    assert returned["status"] == STATUS_RETURNED
    assert returned["return_reason"] == "Fix card total"
    assert apply.call_count == 0
    assert cur.daily_entries == {}
    assert any(e["event_type"] == "returned" for e in cur.events)

    # resubmit still does not apply
    corrected = _save(cur, SECTION_SELF_SERVICE, {"cash": 6, "card": 6})
    assert corrected["status"] == STATUS_RETURNED
    again = _submit(cur, SECTION_SELF_SERVICE)
    assert again["status"] == STATUS_SUBMITTED
    assert again["daily_entry_id"] is None
    assert any(e["event_type"] == "resubmitted" for e in cur.events)

    approved = review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
    assert approved["status"] == STATUS_APPROVED
    assert apply.call_count == 1
    with pytest.raises(DrcMobileEntryError) as ei:
        review_mobile_submission(cur, 3, sub["id"], action="return", actor_user_id=1, reason="Nope")
    assert ei.value.status == 409


@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
def test_approval_conflicts_leave_submitted_without_in_txn_conflict_audit(notify, compute, cur):
    from backend.drc_mobile_entry import (
        CONFLICT_DAY_NOT_OPEN,
        CONFLICT_TARGET_LINE,
        approval_conflict_error,
    )

    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    sub = _submit(cur, SECTION_SELF_SERVICE)
    cur.events.clear()

    with patch(
        "backend.drc_mobile_entry._apply_approved_section_from_snapshot",
        side_effect=approval_conflict_error(DAY_NOT_OPEN_HELPER, CONFLICT_DAY_NOT_OPEN),
    ):
        with pytest.raises(DrcMobileEntryError) as ei:
            review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
        assert ei.value.status == 409
        assert ei.value.conflict_type == CONFLICT_DAY_NOT_OPEN
        assert ei.value.durable_conflict is True
        assert DAY_NOT_OPEN_HELPER in str(ei.value)
    row = cur.subs[(3, str(TODAY), SECTION_SELF_SERVICE)]
    assert row["status"] == STATUS_SUBMITTED
    assert row.get("daily_entry_id") is None
    # Conflict must not be written inside the failed txn (would roll back).
    assert not any(e["event_type"] == "approval_conflict" for e in cur.events)
    assert not any(e["event_type"] == "approved" for e in cur.events)

    with patch(
        "backend.drc_mobile_entry._apply_approved_section_from_snapshot",
        side_effect=approval_conflict_error(
            DRC_FIELD_CONFLICT_HELPER,
            CONFLICT_TARGET_LINE,
            audit_detail={"line_key": "revenue.self_service.cash"},
        ),
    ):
        with pytest.raises(DrcMobileEntryError) as ei:
            review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
        assert ei.value.conflict_type == CONFLICT_TARGET_LINE
        assert "already contains a value" in str(ei.value)
    assert cur.subs[(3, str(TODAY), SECTION_SELF_SERVICE)]["status"] == STATUS_SUBMITTED


def test_durable_approval_conflict_audit_commits_separately():
    from backend.drc_mobile_entry import (
        CONFLICT_TARGET_LINE,
        record_approval_conflict_audit,
    )

    durable = FakeCursor()
    conn = MagicMock()
    conn.cursor.return_value = durable
    with patch("backend.db.get_db", return_value=conn), patch(
        "backend.drc_mobile_entry.ensure_drc_mobile_entry_tables"
    ):
        ok = record_approval_conflict_audit(
            organization_id=3,
            submission_id=77,
            actor_user_id=1,
            conflict_type=CONFLICT_TARGET_LINE,
            audit_detail={
                "business_date": "2026-07-24",
                "section_key": SECTION_SELF_SERVICE,
                "line_key": "revenue.self_service.cash",
                "revision": 2,
                "session_token": "should-be-stripped",
            },
            message=DRC_FIELD_CONFLICT_HELPER,
        )
    assert ok is True
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conflict_events = [e for e in durable.events if e["event_type"] == "approval_conflict"]
    assert len(conflict_events) == 1
    detail = conflict_events[0]["detail_json"]
    assert "session_token" not in detail
    assert CONFLICT_TARGET_LINE in detail
    assert "revenue.self_service.cash" in detail


def test_failed_approval_leaves_no_partial_drc_or_approved_status(cur):
    from backend.drc_mobile_entry import CONFLICT_DAY_NOT_OPEN, approval_conflict_error

    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 10, "card": 20})
    with patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap()), patch(
        "backend.drc_mobile_entry._notify_section_submitted"
    ):
        sub = _submit(cur, SECTION_SELF_SERVICE)
    with patch(
        "backend.drc_mobile_entry._apply_approved_section_from_snapshot",
        side_effect=approval_conflict_error(DAY_NOT_OPEN_HELPER, CONFLICT_DAY_NOT_OPEN),
    ):
        with pytest.raises(DrcMobileEntryError):
            review_mobile_submission(cur, 3, sub["id"], action="approve", actor_user_id=1)
    row = cur.subs[(3, str(TODAY), SECTION_SELF_SERVICE)]
    assert row["status"] == STATUS_SUBMITTED
    assert row.get("daily_entry_id") is None
    assert cur.daily_entries == {}
    assert cur.daily_lines == {}
    assert not any(e["event_type"] == "approved" for e in cur.events)


@patch("backend.drc_mobile_entry._apply_approved_section_from_snapshot", return_value=100)
@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.drc_mobile_entry._notify_section_submitted")
def test_separate_sections_approve_independently(notify, compute, apply, cur):
    save_weekday_section_assignments(
        cur,
        3,
        [
            {"section_key": SECTION_SELF_SERVICE, "weekday": 4, "employee_id": 42},
            {"section_key": SECTION_DROP_OFF, "weekday": 4, "employee_id": 10},
        ],
    )
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    ensure_section_draft(cur, 3, 10, SECTION_DROP_OFF, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 1, "card": 1})
    save_section_draft(
        cur, 3, 10, SECTION_DROP_OFF, {"cash": 2, "card": 2}, expected_revision=0, on_date=TODAY
    )
    a = _submit(cur, SECTION_SELF_SERVICE)
    b = submit_section(cur, 3, 10, SECTION_DROP_OFF, expected_revision=1, on_date=TODAY)
    review_mobile_submission(cur, 3, a["id"], action="approve", actor_user_id=1)
    assert cur.subs[(3, str(TODAY), SECTION_DROP_OFF)]["status"] == STATUS_SUBMITTED
    review_mobile_submission(cur, 3, b["id"], action="approve", actor_user_id=1)
    assert apply.call_count == 2


def test_line_blocks_and_snapshot_apply_no_recalc(cur):
    from backend.drc_mobile_entry import (
        _apply_approved_section_from_snapshot,
        _line_blocks_mobile_apply,
    )

    assert _line_blocks_mobile_apply(None, 1) is False
    assert _line_blocks_mobile_apply({"source_ref": "mobile_section:1", "amount": 10}, 1) is False
    assert _line_blocks_mobile_apply({"source_ref": "manual", "amount": 10}, 1) is True
    assert _line_blocks_mobile_apply({"is_manual_override": 1, "amount": 0}, 1) is True

    calc, snap = _snap(40)
    # mutate rates in a fake "current" world — apply must use snapshot amounts
    with patch("backend.daily_revenue_cost.ensure_daily_revenue_cost_tables"), patch(
        "backend.daily_revenue_cost_schema.upsert_entry_line"
    ) as upsert:
        entry_id = _apply_approved_section_from_snapshot(
            cur,
            3,
            TODAY,
            SECTION_SELF_SERVICE,
            user_id=1,
            submission_id=9,
            calculated=calc,
            snapshot=snap,
        )
        assert entry_id
        assert upsert.call_count == 2
        amounts = [c.kwargs["amount"] for c in upsert.call_args_list]
        assert amounts == [10.0, 20.0]


@patch("backend.daily_revenue_cost.list_commercial_accounts")
def test_backend_formula_validation_rinse_and_commercial(list_accts, cur):
    list_accts.return_value = [{"id": 1, "name": "DHS"}]
    save_weekday_section_assignments(
        cur,
        3,
        [
            {"section_key": SECTION_RINSE, "weekday": 4, "employee_id": 42},
            {"section_key": SECTION_COMMERCIAL, "weekday": 4, "employee_id": 42},
        ],
    )
    ensure_section_draft(cur, 3, 42, SECTION_RINSE, on_date=TODAY)
    with pytest.raises(DrcMobileEntryError):
        _save(cur, SECTION_RINSE, {"wf_pounds": -1, "hd_orders": 0, "hd_revenue": 0})
    ok = _save(cur, SECTION_RINSE, {"wf_pounds": 12, "hd_orders": 2, "hd_revenue": 40})
    assert ok["values"]["wf_pounds"] == 12.0


@patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap())
@patch("backend.notification_service.dispatch_notification_event")
@patch("backend.drc_mobile_entry.table_exists", return_value=True)
def test_notification_on_employee_submission(table_exists, dispatch, compute, cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 1, "card": 0})
    _submit(cur, SECTION_SELF_SERVICE)
    assert dispatch.called
    assert dispatch.call_args.kwargs["title"] == "Revenue & Cost Submitted"


def test_et_business_date_resolution(cur):
    _assign_ss(cur)
    today = list_today_for_employee(cur, 3, 42)
    assert today["business_date"] == TODAY.isoformat()
    assert today["date_resolver"] == "business_today (America/New_York)"


def test_no_assignment_helper_constant():
    assert "No Revenue & Cost entry assigned today" in NO_ASSIGNMENT_HELPER


def test_reject_alias_means_return(cur):
    _assign_ss(cur)
    ensure_section_draft(cur, 3, 42, SECTION_SELF_SERVICE, on_date=TODAY)
    _save(cur, SECTION_SELF_SERVICE, {"cash": 1, "card": 1})
    with patch("backend.drc_mobile_entry._compute_section_snapshot", return_value=_snap()), patch(
        "backend.drc_mobile_entry._notify_section_submitted"
    ), patch("backend.drc_mobile_entry._notify_section_returned"):
        sub = _submit(cur, SECTION_SELF_SERVICE)
        out = review_mobile_submission(
            cur, 3, sub["id"], action="reject", actor_user_id=1, reason="Please fix"
        )
    assert out["status"] == STATUS_RETURNED
