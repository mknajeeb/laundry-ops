"""Auto-approval, cycle credit, and immediate partial publication."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_performance_approvals import ACTION_INVALIDATE
from backend.rinse_performance_auto_approve import (
    auto_approve_finalized_folder_day,
    combined_weighted_lbs_per_hour,
    consider_employee_day_for_auto_approve,
    consider_session_for_auto_approve,
    enqueue_folder_segment_close,
    meets_target,
    session_evidence_is_complete,
)
from backend.rinse_performance_employee_day import (
    approved_contribution_is_rankable,
    compose_employee_day_from_sessions,
)
from backend.rinse_performance_folder_publisher import partition_employees_by_exclusion
from backend.rinse_performance_supervisor_adjustments import (
    attach_supervisor_adjustments,
    claim_cycle_credit,
    create_or_update_adjustment,
    cycle_key_for_order_instance,
    list_adjustments_for_day,
)


DAY = date(2026, 11, 12)
ENABLED_AT = datetime(2026, 11, 12, 6, 0, 0)


def _session(**overrides):
    row = {
        "session_id": "WF-900",
        "employee": "Ada",
        "role_status": "closed",
        "performance_hours": 2.0,
        "lbs_per_hour": 80.0,
        "orders_completed": 4,
        "end_time": "2026-11-12T14:00:00",
        "orders": [
            {"pre_weight_lbs": 40.0, "session_assignment": "assigned"},
            {"credited_weight_lbs": 40.0, "session_assignment": "assigned"},
        ],
    }
    row.update(overrides)
    return row


def test_evidence_and_target_gates():
    ok, reason = session_evidence_is_complete(_session())
    assert ok and reason == "ok"
    assert meets_target(_session(lbs_per_hour=55.0), 55.0)
    assert not meets_target(_session(lbs_per_hour=54.999), 55.0)
    incomplete, why = session_evidence_is_complete(
        _session(orders=[{"session_assignment": "assigned"}])
    )
    assert not incomplete and why == "incomplete_evidence"
    review, why = session_evidence_is_complete(
        _session(orders=[{"pre_weight_lbs": 10, "needs_review": True}])
    )
    assert not review and why == "needs_review"
    open_sess, why = session_evidence_is_complete(_session(role_status="open"))
    assert not open_sess and why == "open"


def test_auto_approve_skips_history_below_target_and_manual():
    historical = consider_session_for_auto_approve(
        MagicMock(),
        3,
        selected_date_et=DAY,
        session=_session(end_time="2026-11-11T18:00:00"),
        target=55.0,
        enabled_at=ENABLED_AT,
    )
    assert historical["status"] == "before_enable"

    below = consider_session_for_auto_approve(
        MagicMock(),
        3,
        selected_date_et=DAY,
        session=_session(lbs_per_hour=40.0),
        target=55.0,
        enabled_at=ENABLED_AT,
    )
    assert below["status"] == "below_target"

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"action": ACTION_INVALIDATE, "content_fingerprint": ""},
    ]
    with patch(
        "backend.rinse_performance_auto_approve.table_exists",
        return_value=True,
    ):
        blocked = consider_session_for_auto_approve(
            cursor,
            3,
            selected_date_et=DAY,
            session=_session(),
            target=55.0,
            enabled_at=ENABLED_AT,
        )
    assert blocked["status"] == "manual_precedence"


def test_auto_approve_is_idempotent_for_same_fingerprint():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    with patch(
        "backend.rinse_performance_auto_approve.table_exists",
        return_value=True,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        return_value={"invalidated_at": None, "excluded_at": None, "content_fingerprint": "fp"},
    ), patch(
        "backend.rinse_performance_auto_approve.folder_session_fingerprint",
        return_value="fp",
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
    ) as upsert:
        out = consider_session_for_auto_approve(
            cursor,
            3,
            selected_date_et=DAY,
            session=_session(),
            target=55.0,
            enabled_at=ENABLED_AT,
        )
    assert out["already_approved"] is True
    upsert.assert_not_called()


def test_cycle_keys_are_order_instance_identity():
    assert cycle_key_for_order_instance(44) == "oi:44"
    assert cycle_key_for_order_instance(None) is None
    assert cycle_key_for_order_instance(0) is None


def test_same_cycle_cannot_be_credited_twice_and_reprocess_can():
    credits = {}

    class CreditCursor:
        def execute(self, sql, params=None):
            text = " ".join(str(sql).split())
            self.params = params or ()
            if text.startswith("SELECT") and "released_at IS NULL" in text:
                org, key = params
                row = credits.get((org, key))
                self._row = row if row and row.get("released_at") is None else None
            elif text.startswith("UPDATE"):
                org, key = params
                row = credits.get((org, key))
                if row:
                    row["released_at"] = datetime(2026, 11, 12, 15, 0, 0)
                self._row = None
            elif text.startswith("INSERT"):
                org = params[0]
                key = params[4]
                credits[(org, key)] = {
                    "organization_id": org,
                    "cycle_key": key,
                    "employee_name": params[6],
                    "session_id": params[7],
                    "adjustment_key": params[8],
                    "released_at": None,
                }
                self._row = None
            else:
                self._row = None

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    cur = CreditCursor()
    with patch(
        "backend.rinse_performance_supervisor_adjustments.table_exists",
        return_value=True,
    ):
        first = claim_cycle_credit(
            cur,
            3,
            business_date_et=DAY,
            bag_id="B1",
            cycle_key="oi:10",
            order_instance_id=10,
            employee_user_id=7,
            employee_name="Ada",
            session_id=None,
            adjustment_key="ADJ-1",
            weight_lbs=12.0,
            actor_user_id=1,
        )
        second = claim_cycle_credit(
            cur,
            3,
            business_date_et=DAY,
            bag_id="B1",
            cycle_key="oi:10",
            order_instance_id=10,
            employee_user_id=8,
            employee_name="Bea",
            session_id=None,
            adjustment_key="ADJ-2",
            weight_lbs=12.0,
            actor_user_id=1,
        )
        again = claim_cycle_credit(
            cur,
            3,
            business_date_et=DAY,
            bag_id="B1",
            cycle_key="oi:99",
            order_instance_id=99,
            employee_user_id=8,
            employee_name="Bea",
            session_id=None,
            adjustment_key="ADJ-2",
            weight_lbs=12.0,
            actor_user_id=1,
        )
    assert first["ok"] is True
    assert second["ok"] is False
    assert second["status"] == "cycle_already_credited"
    assert again["ok"] is True


def test_adjustment_requires_reason_and_keeps_scores_distinct():
    stored = {}

    class AdjCursor:
        def execute(self, sql, params=None):
            text = " ".join(str(sql).split())
            self.params = params or ()
            if "FROM rinse_performance_supervisor_adjustments" in text:
                key = params[1]
                self._row = stored.get(key)
            elif text.startswith("INSERT INTO rinse_performance_supervisor_adjustments"):
                key = params[2]
                stored[key] = {
                    "adjustment_key": key,
                    "employee_name": params[4],
                    "employee_user_id": params[3],
                    "raw_lbs": params[7],
                    "corrected_lbs": params[11],
                    "approved_lbs_per_hour": params[17],
                    "reason": params[18],
                    "publication_status": params[20],
                    "target_session_id": params[5],
                    "business_date_et": params[1],
                }
                self._row = stored[key]
            elif text.startswith("INSERT INTO rinse_performance_supervisor_adjustment_events"):
                self._row = None
            else:
                self._row = None

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    cur = AdjCursor()
    with patch(
        "backend.rinse_performance_supervisor_adjustments.table_exists",
        return_value=True,
    ):
        missing = create_or_update_adjustment(
            cur,
            3,
            business_date_et=DAY,
            employee_user_id=7,
            employee_name="Ada",
            reason="  ",
            approved_lbs_per_hour=40.0,
        )
        saved = create_or_update_adjustment(
            cur,
            3,
            business_date_et=DAY,
            employee_user_id=7,
            employee_name="Ada",
            reason="Outside-session bags verified",
            raw_lbs=10.0,
            raw_hours=1.0,
            corrected_lbs=20.0,
            corrected_hours=1.0,
            approved_lbs_per_hour=40.0,
        )
    assert missing["status"] == "reason_required"
    assert saved["ok"] is True
    row = saved["adjustment"]
    assert float(row["raw_lbs"]) == 10.0
    assert float(row["corrected_lbs"]) == 20.0
    assert float(row["approved_lbs_per_hour"]) == 40.0


def test_partial_day_publishes_approved_session_only():
    sessions = [
        {
            "session_id": "1",
            "session_code": "WF-01",
            "employee": "Ada",
            "role_status": "closed",
            "publication_status": "APPROVED",
            "publication": {
                "status": "APPROVED",
                "published_numerator": 100.0,
                "published_denominator": 2.0,
                "published_metric_value": 50.0,
            },
            "orders_completed": 4,
            "total_pre_lbs": 100.0,
            "performance_hours": 2.0,
            "lbs_per_hour": 50.0,
        },
        {
            "session_id": "2",
            "session_code": "WF-02",
            "employee": "Ada",
            "role_status": "closed",
            "publication_status": "UNAPPROVED",
            "publication": {"status": "UNAPPROVED"},
            "orders_completed": 6,
            "total_pre_lbs": 300.0,
            "performance_hours": 3.0,
            "lbs_per_hour": 100.0,
        },
    ]
    emp = compose_employee_day_from_sessions(
        employee_name="Ada",
        employee_user_id=7,
        sessions=sessions,
        selected_date_et=DAY,
    )
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert approved_contribution_is_rankable(emp) is True
    assert emp["orders_completed"] == 4
    assert float(emp["total_pre_lbs"]) == 100.0
    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary_approved"]["employee_day_count"] == 1
    assert day["summary_approved"]["orders_completed"] == 4


def test_pending_only_stays_unranked_and_adjustment_publishes():
    pending = compose_employee_day_from_sessions(
        employee_name="Bea",
        employee_user_id=8,
        sessions=[
            {
                "session_id": "9",
                "employee": "Bea",
                "role_status": "closed",
                "publication_status": "UNAPPROVED",
                "publication": {"status": "UNAPPROVED"},
                "orders_completed": 3,
                "total_pre_lbs": 30.0,
                "performance_hours": 1.0,
            }
        ],
        selected_date_et=DAY,
    )
    assert approved_contribution_is_rankable(pending) is False
    day = {
        "selected_date_et": DAY,
        "employees": [pending],
        "summary": {},
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "employee_name": "Bea",
            "employee_user_id": 8,
            "publication_status": "NEEDS_APPROVAL",
            "target_session_id": None,
            "approved_hours": 1.0,
            "approved_lbs": 40.0,
            "approved_orders": 2,
            "approved_lbs_per_hour": 40.0,
        },
        {
            "employee_name": "Cara",
            "employee_user_id": 9,
            "publication_status": "APPROVED",
            "target_session_id": None,
            "approved_hours": 1.0,
            "approved_lbs": 70.0,
            "approved_orders": 3,
            "approved_lbs_per_hour": 70.0,
            "raw_lbs_per_hour": 10.0,
            "corrected_lbs_per_hour": 20.0,
        },
    ]
    with patch(
        "backend.rinse_performance_supervisor_adjustments.table_exists",
        return_value=True,
    ):
        attach_supervisor_adjustments(cursor, 3, day)
    cara = next(e for e in day["employees"] if e["employee"] == "Cara")
    assert cara["day_publication_status"] == "APPROVED"
    assert approved_contribution_is_rankable(cara) is True
    assert float(cara["total_pre_lbs"]) == 70.0
    assert cara["raw_lbs_per_hour"] == 10.0
    assert cara["corrected_lbs_per_hour"] == 20.0
    assert cara["approved_lbs_per_hour"] == 70.0
    bea = next(e for e in day["employees"] if e["employee"] == "Bea")
    assert approved_contribution_is_rankable(bea) is False


def test_ordinary_reads_do_not_create_feature_tables():
    class RecordingCursor:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(" ".join(str(sql).split()))

        def fetchall(self):
            return []

        def fetchone(self):
            return None

        def close(self):
            return None

    cursor = RecordingCursor()
    with patch(
        "backend.rinse_performance_supervisor_adjustments.table_exists",
        return_value=False,
    ):
        assert list_adjustments_for_day(cursor, 3, DAY) == []
        created = create_or_update_adjustment(
            cursor,
            3,
            business_date_et=DAY,
            employee_user_id=7,
            employee_name="Ada",
            reason="coverage",
        )
    assert created["status"] == "not_provisioned"
    assert not any("CREATE TABLE" in text or text.startswith("ALTER TABLE") for text in cursor.sql)

    conn = MagicMock()
    queue_cursor = RecordingCursor()
    conn.cursor.return_value = queue_cursor
    with patch(
        "backend.rinse_performance_auto_approve.table_exists",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.auto_approve_enabled",
        return_value=True,
    ):
        queue_cursor.fetchone = lambda: {
            "segment_id": 4,
            "role_code": "FOLDER",
            "category_code": "RINSE_WF",
            "ended_at": datetime(2026, 11, 12, 18, 0, 0),
            "organization_id": 3,
        }
        enqueue_folder_segment_close(conn, 9)
    assert not any("CREATE TABLE" in text or "INSERT INTO" in text for text in queue_cursor.sql)


def _weighted_session(session_id, lbs, hours, **overrides):
    rate = round(float(lbs) / float(hours), 4) if hours else None
    row = {
        "session_id": session_id,
        "total_pre_lbs": lbs,
        "performance_hours": hours,
        "lbs_per_hour": rate,
        "orders_completed": 2,
        "orders": [
            {"pre_lbs": lbs / 2, "session_assignment": "auto"},
            {"pre_lbs": lbs / 2, "session_assignment": "auto"},
        ],
        "end_time": "2026-11-12T14:00:00",
    }
    row.update(overrides)
    return _session(**row)


def test_combined_rate_is_total_pounds_over_total_hours():
    fast = _weighted_session("WF-1", 100, 1)
    slow = _weighted_session("WF-2", 10, 9)
    totals = combined_weighted_lbs_per_hour([fast, slow])
    assert totals["lbs_per_hour"] == 11.0
    assert round((100 / 1 + 10 / 9) / 2, 4) != 11.0


def test_public_pre_lbs_counts_as_complete_evidence():
    ok, reason = session_evidence_is_complete(
        _session(orders=[{"pre_lbs": 236, "session_assignment": "auto"}])
    )
    assert ok and reason == "ok"
    missing, why = session_evidence_is_complete(
        _session(orders=[{"session_assignment": "auto"}])
    )
    assert not missing and why == "incomplete_evidence"
    zero_fill, why = session_evidence_is_complete(
        _session(orders=[{"pre_lbs": 0, "session_assignment": "auto"}])
    )
    assert not zero_fill and why == "incomplete_evidence"
    flagged, why = session_evidence_is_complete(
        _session(
            orders=[
                {
                    "pre_lbs": 80,
                    "pre_weight_lbs": 80,
                    "missing_production_credit_weight": True,
                    "session_assignment": "auto",
                }
            ]
        )
    )
    assert not flagged and why == "incomplete_evidence"
    disagree, why = session_evidence_is_complete(
        _session(
            total_pre_lbs=80,
            orders=[{"pre_lbs": 80, "pre_weight_lbs": 10, "session_assignment": "auto"}],
        )
    )
    assert not disagree and why == "inconsistent_evidence"
    post_source, why = session_evidence_is_complete(
        _session(
            orders=[
                {
                    "pre_lbs": 80,
                    "credited_weight_source": "AUTHORITATIVE_POST",
                    "session_assignment": "auto",
                }
            ]
        )
    )
    assert not post_source and why == "inconsistent_evidence"
    canonical, why = session_evidence_is_complete(
        _session(
            total_pre_lbs=21.5,
            orders=[
                {
                    "pre_lbs": 21.5,
                    "pre_weight_lbs": 21.5,
                    "credited_weight_lbs": 21.5,
                    "evidence_pre_weight_lbs": 21.5,
                    "credited_weight_source": "EVIDENCE_PRE",
                    "credited_weight_basis": "CANONICAL_CURRENT_CYCLE_PRE",
                    "missing_production_credit_weight": False,
                    "session_assignment": "auto",
                }
            ],
        )
    )
    assert canonical and why == "ok"


def test_change_jobs_runner_drains_the_approval_queue():
    from backend.jobs.run_change_jobs import run_registered_change_jobs

    conn = MagicMock()
    with patch(
        "backend.hr_compliance.run_document_compliance_tick",
        side_effect=lambda *args, **kwargs: {"ok": True},
    ), patch(
        "backend.rinse_performance_auto_approve.process_pending_auto_approve_queue",
        return_value={"ok": True, "processed_days": 1},
    ) as process:
        out = run_registered_change_jobs(conn, dry_run=False)
        skipped = run_registered_change_jobs(conn, dry_run=True)
    assert out["folder_auto_approve"]["processed_days"] == 1
    conn.commit.assert_called_once()
    assert skipped["folder_auto_approve"]["reason"] == "dry_run"
    process.assert_called_once()


def test_named_lock_accepts_mysql_row_shapes():
    from backend.folder_auto_approve_scheduler import mysql_named_lock_acquired

    assert mysql_named_lock_acquired((1,))
    assert mysql_named_lock_acquired([1])
    assert mysql_named_lock_acquired({"GET_LOCK('washpro_folder_auto_approve', 5)": 1})
    assert not mysql_named_lock_acquired((0,))
    assert not mysql_named_lock_acquired((None,))
    assert not mysql_named_lock_acquired(None)
    assert not mysql_named_lock_acquired({})


def test_employee_day_auto_approves_on_combined_rate_not_each_session():
    fast = _weighted_session("WF-1", 80, 1)
    slow = _weighted_session("WF-2", 20, 1)
    cursor = MagicMock()
    with patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        return_value=None,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
        return_value={"ok": True, "session_id": "x"},
    ) as upsert:
        above = consider_employee_day_for_auto_approve(
            cursor,
            3,
            selected_date_et=DAY,
            employee_name="Ada",
            sessions=[fast, slow],
            target=40.0,
            enabled_at=ENABLED_AT,
        )
        at_target = consider_employee_day_for_auto_approve(
            cursor,
            3,
            selected_date_et=DAY,
            employee_name="Ada",
            sessions=[_weighted_session("WF-3", 40, 1)],
            target=40.0,
            enabled_at=ENABLED_AT,
        )
        below = consider_employee_day_for_auto_approve(
            cursor,
            3,
            selected_date_et=DAY,
            employee_name="Ada",
            sessions=[fast, slow],
            target=60.0,
            enabled_at=ENABLED_AT,
        )
    assert above["status"] == "auto_approved"
    assert above["lbs_per_hour"] == 50.0
    assert above["approved"] == 2
    assert at_target["status"] == "auto_approved"
    assert below["status"] == "below_target"
    assert below["approved"] == 0
    assert upsert.call_count == 3


def test_incomplete_open_historical_and_manual_days_stay_pending():
    complete = _weighted_session("WF-1", 80, 1)
    incomplete = _weighted_session("WF-2", 80, 1, orders=[{"session_assignment": "auto"}])
    cursor = MagicMock()
    with patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        return_value=None,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
    ) as upsert:
        missing = consider_employee_day_for_auto_approve(
            cursor, 3, selected_date_et=DAY, employee_name="Ada",
            sessions=[incomplete], target=40.0, enabled_at=ENABLED_AT,
        )
        still_open = consider_employee_day_for_auto_approve(
            cursor, 3, selected_date_et=DAY, employee_name="Ada",
            sessions=[complete, _weighted_session("WF-9", 10, 1, role_status="open", end_time=None)],
            target=40.0, enabled_at=ENABLED_AT,
        )
        historical = consider_employee_day_for_auto_approve(
            cursor, 3, selected_date_et=DAY, employee_name="Ada",
            sessions=[_weighted_session("WF-1", 236, 4.4, end_time="2026-11-12T14:17:33")],
            target=40.0, enabled_at=datetime(2026, 11, 12, 20, 16, 3),
        )
    assert missing["status"] == "incomplete_evidence"
    assert still_open["status"] == "open" and still_open["retry"] is True
    assert historical["status"] == "before_enable"
    upsert.assert_not_called()

    with patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        return_value=None,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        side_effect=lambda _c, _o, *, session_id, fingerprint: session_id == "WF-1",
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
        return_value={"ok": True},
    ) as upsert:
        mixed = consider_employee_day_for_auto_approve(
            cursor, 3, selected_date_et=DAY, employee_name="Ada",
            sessions=[complete, _weighted_session("WF-2", 80, 1)],
            target=40.0, enabled_at=ENABLED_AT,
        )
    assert mixed["approved"] == 1
    assert any(row["status"] == "manual_precedence" for row in mixed["results"])
    upsert.assert_called_once()


def test_auto_approve_retries_open_days_and_is_idempotent():
    closed = {
        "employee": "Ada",
        "sessions": [_weighted_session("WF-1", 80, 1)],
    }
    with patch(
        "backend.rinse_performance_auto_approve.auto_approve_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_performance_auto_approve.auto_approve_enabled_at",
        return_value=ENABLED_AT,
    ), patch(
        "backend.rinse_performance_auto_approve.get_folder_benchmark",
        return_value=40.0,
    ), patch(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        return_value={"employees": [{"employee": "Ada", "sessions": [_weighted_session("WF-1", 80, 1, role_status="open", end_time=None)]}]},
    ), patch(
        "backend.rinse_performance_auto_approve._mark_queue_processed",
    ) as mark:
        waiting = auto_approve_finalized_folder_day(MagicMock(), 3, selected_date_et=DAY)
    assert waiting["retry"] is True
    assert waiting["approved"] == 0
    mark.assert_not_called()

    approvals = {}

    def fake_get(_cursor, _org, *, role_key, session_id):
        return approvals.get(session_id)

    def fake_upsert(_cursor, _org, *, role_key, snapshot, **_kwargs):
        approvals[snapshot["session_id"]] = {
            "invalidated_at": None,
            "excluded_at": None,
            "content_fingerprint": snapshot["content_fingerprint"],
        }
        return {"ok": True, "session_id": snapshot["session_id"]}

    with patch(
        "backend.rinse_performance_auto_approve.auto_approve_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_performance_auto_approve.auto_approve_enabled_at",
        return_value=ENABLED_AT,
    ), patch(
        "backend.rinse_performance_auto_approve.get_folder_benchmark",
        return_value=40.0,
    ), patch(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        return_value={"employees": [closed]},
    ), patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        side_effect=fake_get,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
        side_effect=fake_upsert,
    ) as upsert, patch(
        "backend.rinse_performance_auto_approve._mark_queue_processed",
    ) as mark:
        first = auto_approve_finalized_folder_day(MagicMock(), 3, selected_date_et=DAY)
        second = auto_approve_finalized_folder_day(MagicMock(), 3, selected_date_et=DAY)
    assert first["approved"] == 1
    assert second["already_approved"] == 1
    assert second["approved"] == 0
    assert upsert.call_count == 1
    assert mark.call_count == 2


def test_speed_only_adjustment_publishes_without_fabricating_work():
    pending = compose_employee_day_from_sessions(
        employee_name="Ada",
        employee_user_id=7,
        sessions=[
            {
                "session_id": "WF-1",
                "employee": "Ada",
                "role_status": "closed",
                "publication_status": "UNAPPROVED",
                "publication": {"status": "UNAPPROVED"},
                "orders_completed": 11,
                "total_pre_lbs": 236.0,
                "performance_hours": 4.4,
                "lbs_per_hour": 53.6364,
            }
        ],
        selected_date_et=DAY,
    )
    assert pending["recorded_lbs_per_hour"] == round(236.0 / 4.4, 4)
    assert pending["orders_completed"] == 0
    day = {"selected_date_et": DAY, "employees": [pending]}
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "employee_name": "Ada",
            "employee_user_id": 7,
            "publication_status": "APPROVED",
            "target_session_id": None,
            "approved_hours": None,
            "approved_lbs": None,
            "approved_orders": None,
            "approved_lbs_per_hour": 48.0,
            "raw_lbs_per_hour": None,
            "corrected_lbs_per_hour": None,
        }
    ]
    with patch(
        "backend.rinse_performance_supervisor_adjustments.table_exists",
        return_value=True,
    ):
        attach_supervisor_adjustments(cursor, 3, day)
    ada = day["employees"][0]
    assert ada["speed_only_adjustment"] is True
    assert ada["approved_lbs_per_hour"] == 48.0
    assert ada["orders_completed"] == 0
    assert float(ada["total_pre_lbs"]) == 0.0
    assert ada["recorded_orders_completed"] == 11
    assert float(ada["recorded_total_pre_lbs"]) == 236.0
    assert approved_contribution_is_rankable(ada) is True


def test_excluded_session_is_left_out_of_the_combined_rate():
    kept = _weighted_session("WF-2", 30, 1)
    excluded = _weighted_session(
        "WF-1",
        200,
        1,
        publication_status="EXCLUDED",
        publication={"status": "EXCLUDED", "excluded": True},
    )
    with patch(
        "backend.rinse_performance_auto_approve.get_approval_row",
        return_value=None,
    ), patch(
        "backend.rinse_performance_auto_approve.manual_decision_blocks_auto",
        return_value=False,
    ), patch(
        "backend.rinse_performance_auto_approve.upsert_approved_snapshot",
    ) as upsert:
        out = consider_employee_day_for_auto_approve(
            MagicMock(),
            3,
            selected_date_et=DAY,
            employee_name="Ada",
            sessions=[excluded, kept],
            target=40.0,
            enabled_at=ENABLED_AT,
        )
    assert out["status"] == "below_target"
    assert out["lbs_per_hour"] == 30.0
    upsert.assert_not_called()
