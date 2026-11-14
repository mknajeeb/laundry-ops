"""Auto-approval, cycle credit, and immediate partial publication."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_performance_approvals import ACTION_INVALIDATE
from backend.rinse_performance_auto_approve import (
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
