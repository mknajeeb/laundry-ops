"""Supervisor portal rules. Auto-approval behavior is asserted, not replaced."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

from backend.rinse_performance_auto_approve import consider_employee_day_for_auto_approve
from backend.rinse_performance_roles import FOLDER_DEFAULT_BENCHMARK
from backend.supervisor_portal.adjustments import reported_employee_day, reported_session, validate_adjustment
from backend.supervisor_portal.permissions import can, strip_rinse_summary
from backend.supervisor_portal.quality import incident_totals, normalize_incident, points_for
from backend.supervisor_portal.reconciliation import classify_completed_bags
from backend.supervisor_portal.roles import primary_role_on
from backend.supervisor_portal.scoring import draft_policy, preview_score, refuse_activation
from backend.supervisor_portal.service import assemble_supervisor_day, team_comparison
from backend.supervisor_portal.training import checklist_ready, next_status, normalize_template


def _bag(index, **extra):
    row = {
        "bag_id": f"B{index:04d}",
        "order_instance_id": index,
        "pounds": 10,
        "completion_at": f"2026-11-14 12:{index % 60:02d}:00",
    }
    row.update(extra)
    return row


def _session_bag(index, status, **extra):
    row = _bag(index, employee="Ada", session_id="S1", publication_status=status)
    row.update(extra)
    return row


def test_november_14_unique_bags_reconcile():
    completed = [_bag(i) for i in range(1, 176)]
    sessions = [_session_bag(i, "APPROVED", approval_source="AUTO") for i in range(1, 157)]
    sessions += [_session_bag(i, "UNAPPROVED", session_id="S2") for i in range(157, 160)]
    sessions += [_session_bag(i, "EXCLUDED", session_id="S3") for i in range(160, 163)]
    outside = [_bag(i, employee="Bea") for i in range(163, 174)]
    report = classify_completed_bags(completed, session_membership=sessions, outside=outside, unmapped=[])
    assert report["categories"] == {
        "approved": 156,
        "pending": 3,
        "excluded": 3,
        "outside_session": 11,
        "nonqualifying": 2,
        "unmapped": 0,
        "unresolved": 0,
    }
    assert report["total_completed"] == 175
    assert report["total_accounted"] == 175
    assert report["unaccounted"] == 0
    assert report["invariant_holds"] is True


def test_duplicate_scan_and_reopen_count_once():
    completed = [
        _bag(1, completion_at="2026-11-14 09:00:00", order_instance_id=1),
        _bag(1, completion_at="2026-11-14 18:00:00", order_instance_id=2),
    ]
    report = classify_completed_bags(
        completed,
        session_membership=[_session_bag(1, "EXCLUDED")],
        outside=[_bag(1)],
    )
    assert report["total_completed"] == 1
    assert report["categories"]["excluded"] == 1
    bag = report["bags"][0]
    assert bag["order_ids"] == [1, 2]
    assert "duplicate_scan" in bag["secondary_flags"]
    assert "outside_session" in bag["secondary_flags"]
    assert bag["primary_category"] == "excluded"


def test_nonqualifying_bags_stay_in_the_total():
    report = classify_completed_bags([_bag(1), _bag(2)], session_membership=[], outside=[], unmapped=[])
    assert report["categories"]["nonqualifying"] == 2
    assert report["unaccounted"] == 0


def test_cross_midnight_membership_is_the_supplied_day_list():
    """The classifier does not drop a bag for its clock. The ET day filter stays upstream."""
    completed = [
        _bag(1, completion_at="2026-11-14 23:50:00"),
        _bag(2, completion_at="2026-11-15 00:20:00"),
    ]
    report = classify_completed_bags(
        completed,
        session_membership=[_session_bag(1, "APPROVED"), _session_bag(2, "APPROVED")],
    )
    assert report["total_completed"] == 2
    assert report["categories"]["approved"] == 2


def test_reporting_date_policy_remains_shift_date_et():
    from backend.rinse_step1_productivity_fast import load_completed_productivity_day_bags

    source = inspect.getsource(load_completed_productivity_day_bags)
    assert "shift_date_et" in source


def test_auto_approval_threshold_stays_independent():
    assert FOLDER_DEFAULT_BENCHMARK == 40.0
    source = inspect.getsource(consider_employee_day_for_auto_approve)
    assert "combined_weighted_lbs_per_hour" in source
    assert "supervisor_portal" not in source
    assert draft_policy()["active"] is False
    assert draft_policy()["auto_approval_threshold"] is None


def test_eligible_time_preserves_original_and_does_not_change_pounds():
    session = {
        "session_id": "S1",
        "performance_hours": 4,
        "total_pre_lbs": 160,
        "lbs_per_hour": 40,
        "start_time": "2026-11-14 08:00:00",
        "end_time": "2026-11-14 12:00:00",
    }
    adjustment = validate_adjustment(
        {"kind": "eligible_percent", "reason": "One hour was sorting", "session_id": "S1", "eligible_percent": 75},
        session,
    )
    report = reported_session(session, [adjustment])
    assert report["original_hours"] == 4
    assert report["eligible_hours"] == 3
    assert report["reported_lbs"] == 160
    assert report["reported_rate"] == round(160 / 3, 4)
    try:
        validate_adjustment(
            {"kind": "eligible_duration", "reason": "x", "session_id": "S1", "eligible_hours": 3, "corrected_lbs": 10},
            session,
        )
    except ValueError as exc:
        assert "pounds" in str(exc)
    else:
        raise AssertionError("pounds must not be editable")


def test_day_manual_rate_does_not_compound_session_rates():
    employee = {"employee": "Ada", "user_id": 7, "lbs_per_hour": 40}
    sessions = [
        {"session_id": "S1", "reported_lbs": 80, "eligible_hours": 2, "excluded": False},
        {"session_id": "S2", "reported_lbs": 80, "eligible_hours": 2, "excluded": False},
    ]
    day = reported_employee_day(
        employee,
        sessions,
        [{"kind": "day_manual_rate", "employee_user_id": 7, "manual_rate": 55, "reversed_at": None}],
    )
    assert day["reported_rate"] == 55
    assert day["precedence"] == "employee_day_manual_rate"
    assert day["session_rates_compounded"] is False
    assert day["reported_lbs"] == 160


def test_role_reallocation_creates_no_destination_output():
    session = {"session_id": "S1", "performance_hours": 4, "total_pre_lbs": 120, "lbs_per_hour": 30}
    adjustment = validate_adjustment(
        {
            "kind": "role_reallocation",
            "reason": "Second hour was weighing",
            "session_id": "S1",
            "reallocated_hours": 1,
            "reallocated_role_key": "WEIGH",
        },
        session,
    )
    report = reported_session(session, [adjustment])
    assert report["eligible_hours"] == 3
    assert report["reported_lbs"] == 120
    assert report["destination_output_lbs"] == 0
    assert report["reallocated_role_key"] == "WEIGH"


def test_reversed_adjustment_is_ignored():
    session = {"session_id": "S1", "performance_hours": 4, "total_pre_lbs": 80, "lbs_per_hour": 20}
    report = reported_session(
        session,
        [{"kind": "session_manual_rate", "session_id": "S1", "manual_rate": 99, "reversed_at": "2026-11-15"}],
    )
    assert report["reported_rate"] == 20


def test_quality_incident_is_counted_once_for_two_employees():
    incident = normalize_incident(
        {
            "issue_type": "damage",
            "quantity": 1,
            "reference": "rinse-issue-88",
            "employees": [
                {"user_id": 1, "employee_name": "Ada"},
                {"user_id": 2, "employee_name": "Bea"},
            ],
        },
        week=date(2026, 11, 14),
    )
    assert incident["week_start"] == "2026-11-09"
    version = {"weights": {"damage": 4}, "severity": {"major": 1.5}}
    points = points_for(1, "damage", "major", version)
    rows = [
        {**incident, "employee_points": points, "employees": [incident["employees"][0]]},
        {**incident, "employee_points": points, "employees": [incident["employees"][1]]},
    ]
    totals = incident_totals(rows)
    assert totals["incident_count"] == 1
    assert totals["employee_points"]["u:1"] == 6
    assert totals["employee_points"]["u:2"] == 6
    assert incident_totals([{**rows[0], "voided_at": "2026-11-15"}])["incident_count"] == 0


def test_scoring_stays_inactive_and_transparent():
    assert refuse_activation({"active": True}) == "scoring_activation_requires_explicit_authorization"
    preview = preview_score(
        actual=44,
        target=40,
        measurable=True,
        quality_points=3,
        volume=100,
        training_ratio=1,
        policy={"active": True, "weights": draft_policy()["weights"], "above_target_policy": "cap"},
    )
    assert preview["overall"] is None
    assert preview["activated"] is False
    assert preview["components"]["productivity"]["achievement"] == 1
    uncapped = preview_score(actual=44, target=40, measurable=True, quality_points=None, volume=10, training_ratio=None)
    assert uncapped["components"]["productivity"]["achievement"] == 1.1
    incomplete = preview_score(actual=None, target=40, measurable=False, quality_points=0, volume=10, training_ratio=1)
    assert incomplete["status"] == "incomplete"


def test_primary_role_change_does_not_rewrite_the_past():
    history = [
        {"role_key": "FOLDER", "effective_from": "2026-11-01", "effective_to": "2026-11-13"},
        {"role_key": "SORT", "effective_from": "2026-11-14", "effective_to": None},
    ]
    assert primary_role_on(history, date(2026, 11, 13))["role_key"] == "FOLDER"
    assert primary_role_on(history, date(2026, 11, 14))["role_key"] == "SORT"


def test_team_average_is_not_the_median():
    team = team_comparison(
        [
            {"reported_hours": 2, "reported_lbs": 100, "reported_rate": 50, "excluded": False},
            {"reported_hours": 2, "reported_lbs": 40, "reported_rate": 20, "excluded": False},
            {"reported_hours": 2, "reported_lbs": 60, "reported_rate": 30, "excluded": False},
            {"reported_hours": 1, "reported_lbs": 10, "reported_rate": 10, "excluded": True},
        ]
    )
    assert team["average_lbs_per_hour"] == round(200 / 6, 4)
    assert team["median_lbs_per_hour"] == 30
    assert team["eligible_pounds"] == 200


def test_rinse_summary_drops_names_notes_and_training():
    stripped = strip_rinse_summary(
        {
            "date_et": "2026-11-14",
            "volume": {"completed_bags": 10, "approved_bags": 8, "approved_pounds": 100, "accounted_bags": 10},
            "approved_productivity": {"approved_hours": 2, "approved_lbs_per_hour": 50, "target_lbs_per_hour": 40},
            "role_performance": [{"role_key": "FOLDER", "label": "Folding", "measurable": True, "unit": "lb/hr", "team_average": 50, "team_median": 48, "target": 40, "employee": "Ada"}],
            "quality": {"week_start": "2026-11-09", "incident_count": 1, "by_type": [{"issue_type": "damage", "incidents": 1}], "notes": "secret"},
            "employees": [{"employee": "Ada"}],
            "training": [{"notes": "private"}],
        }
    )
    assert "Ada" not in str(stripped)
    assert "secret" not in str(stripped)
    assert "private" not in str(stripped)
    assert stripped["volume"]["completed_bags"] == 10
    assert can({"RINSE"}, "view_portal") is False
    assert can({"RINSE"}, "view_rinse_aggregate") is True
    assert can({"OPS"}, "configure_weights") is False
    assert can({"ADMIN"}, "configure_weights") is True
    assert can({"ADMIN"}, "activate_scoring") is False
    assert can({"OPS"}, "adjust_session") is True


def test_training_checklist_does_not_imply_competency_and_trainee_cannot_verify():
    template = normalize_template({"title": "Folder orientation", "items": ["Watch", {"label": "Demonstrate", "required": True}]})
    assert len(template["items"]) == 2
    try:
        next_status(
            "awaiting_verification",
            "completed",
            checklist_complete=True,
            practical_required=True,
            competency_result=None,
            actor_is_trainee=False,
            actor_is_supervisor=True,
            actor_is_subject=False,
        )
    except ValueError as exc:
        assert "competency" in str(exc).lower()
    else:
        raise AssertionError("practical training requires a pass")
    try:
        next_status(
            "awaiting_verification",
            "completed",
            checklist_complete=True,
            practical_required=False,
            competency_result=None,
            actor_is_trainee=True,
            actor_is_supervisor=True,
            actor_is_subject=True,
        )
    except ValueError as exc:
        assert "trainee" in str(exc).lower()
    else:
        raise AssertionError("self verification must be refused")
    assert checklist_ready([{"id": 1, "required": True}], {1: True}) is True
    assert checklist_ready([{"id": 1, "required": True}], {1: False}) is False


def test_assemble_day_keeps_the_reconciliation_invariant():
    completed = [_bag(1), _bag(2)]
    day = {
        "employees": [
            {
                "employee": "Ada",
                "user_id": 3,
                "orders_completed": 1,
                "lbs_per_hour": 40,
                "performance_hours": 2,
                "sessions": [
                    {
                        "session_id": "S1",
                        "publication_status": "APPROVED",
                        "publication": {"status": "APPROVED", "approval_source": "AUTO"},
                        "performance_hours": 2,
                        "total_pre_lbs": 80,
                        "lbs_per_hour": 40,
                        "orders": [_bag(1, pre_lbs=80)],
                        "start_time": "2026-11-14 08:00:00",
                        "end_time": "2026-11-14 10:00:00",
                    }
                ],
            }
        ],
        "outside_folder_session_orders": [],
        "needs_attribution_orders": [],
    }
    payload = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=completed,
        day=day,
        auto_approval_threshold=40,
        scoring_target=None,
        auto_approve_enabled=True,
    )
    assert payload["reconciliation"]["categories"]["approved"] == 1
    assert payload["reconciliation"]["categories"]["nonqualifying"] == 1
    assert payload["reconciliation"]["invariant_holds"] is True
    assert payload["auto_approve"]["independent_of_scoring_target"] is True
    assert payload["achievement_target_source"] == "auto_approval_benchmark"
    assert payload["employees"][0]["score"]["overall"] is None


def test_migration_is_idempotent_and_non_destructive():
    sql = Path("backend/sql/supervisor_portal_v1.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS supervisor_session_adjustments" in sql
    assert "CREATE TABLE IF NOT EXISTS supervisor_quality_incidents" in sql
    assert "DROP TABLE" not in sql.upper().split("ROLLBACK")[0]
    assert "rinse_performance_session_approvals" not in sql
    assert "cleaning_task" not in sql
