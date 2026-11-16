"""Supervisor portal rules. Auto-approval behavior is asserted, not replaced."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

from backend.rinse_performance_auto_approve import consider_employee_day_for_auto_approve
from backend.rinse_performance_roles import FOLDER_DEFAULT_BENCHMARK
from backend.supervisor_portal.adjustments import reported_employee_day, reported_session, validate_adjustment
from backend.supervisor_portal.period import aggregate_period
from backend.supervisor_portal.permissions import can, strip_rinse_summary
from backend.supervisor_portal.quality import incident_totals, normalize_incident, points_for
from backend.supervisor_portal.reconciliation import classify_completed_bags
from backend.supervisor_portal.roles import ROLE_CATALOG, primary_role_on
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


def test_period_rate_uses_totals_not_averaged_daily_rates():
    days = [
        {
            "date_et": "2026-11-10",
            "reconciliation": {"total_completed": 2, "total_accounted": 2, "unaccounted": 0, "categories": {"approved": 2}},
            "approved_productivity": {"approved_hours": 2, "approved_pounds": 100},
            "achievement_target_lbs_per_hour": 40,
            "employees": [{"employee": "Ada", "user_id": 7, "bags": 2, "pounds": 100, "eligible_hours": 2}],
        },
        {
            "date_et": "2026-11-11",
            "reconciliation": {"total_completed": 1, "total_accounted": 1, "unaccounted": 0, "categories": {"approved": 1}},
            "approved_productivity": {"approved_hours": 1, "approved_pounds": 60},
            "achievement_target_lbs_per_hour": 40,
            "employees": [{"employee": "Ada", "user_id": 7, "bags": 1, "pounds": 60, "eligible_hours": 1}],
        },
    ]
    combined = aggregate_period(days, quality={"employee_points": {"u:7": 4}, "incident_count": 1})
    ada = combined["employees"][0]
    assert ada["pounds"] == 160
    assert ada["eligible_hours"] == 3
    assert ada["reported_rate"] == round(160 / 3, 4)
    assert round((50 + 60) / 2, 4) != ada["reported_rate"]
    assert ada["quality_points"] == 4
    assert combined["reconciliation"]["total_completed"] == 3
    assert combined["reconciliation"]["bags"] == []
    assert combined["trend"][0]["rate"] == 50
    assert combined["trend"][1]["rate"] == 60


def test_quality_assignment_requires_an_account_id():
    try:
        normalize_incident(
            {"issue_type": "damage", "reference": "R1", "employees": [{"employee_name": "Ada"}]},
            week=date(2026, 11, 14),
        )
    except ValueError as exc:
        assert "account id" in str(exc)
    else:
        raise AssertionError("name-only assignment was accepted")


def test_captured_role_rate_does_not_invent_hours():
    from backend.supervisor_portal.role_measurement import measure_captured

    missing = measure_captured("SORT", {"output_quantity": 40})
    assert missing["rate"] is None
    assert missing["scoring_ready"] is False
    captured = measure_captured("SORT", {"eligible_hours": 2, "output_quantity": 40})
    assert captured["rate"] == 20
    assert captured["scoring_ready"] is False
    folding = measure_captured("FOLDER", {"eligible_hours": 2, "output_quantity": 80})
    assert folding["rate"] == 40
    assert folding["scoring_ready"] is True


def test_only_folding_is_ready_for_target_scoring():
    measurable = [row["role_key"] for row in ROLE_CATALOG if row["measurable"]]
    assert measurable == ["FOLDER"]
    for key in ("SORT", "WEIGH", "WASH", "DRY", "HD_OPERATOR", "HD_FOLDER"):
        row = next(item for item in ROLE_CATALOG if item["role_key"] == key)
        assert row["measurable"] is False
        assert row["reason"]


def test_employee_cannot_verify_training():
    try:
        next_status(
            "awaiting_verification",
            "completed",
            checklist_complete=True,
            practical_required=True,
            competency_result="pass",
            actor_is_trainee=True,
            actor_is_supervisor=False,
            actor_is_subject=True,
        )
    except ValueError as exc:
        assert "cannot verify" in str(exc)
    else:
        raise AssertionError("employee verification was allowed")


APPROVED_NOVEMBER_14 = (
    ("Yessenia (Veewash)", 20, 491.7, 8.0297, 61.2352, 2.4908),
    ("Francis (Veewash)", 2, 52.8, 0.8908, 59.2726, 2.2452),
    ("Aserisa Salazar (Veewash)", 11, 240.4, 4.3125, 55.7449, 2.5507),
    ("Rocio Ramos (Veewash)", 16, 400.8, 8.2134, 48.7983, 1.9480),
    ("Angelica (Veewash)", 25, 474.4, 9.7478, 48.6674, 2.5647),
    ("Maria Rivera (Veewash)", 19, 454.3, 9.6333, 47.1593, 1.9723),
    ("Lily Chen (veewash)", 6, 148.1, 3.2356, 45.7720, 1.8544),
    ("Maria (Veewash)", 11, 264.5, 5.7997, 45.6058, 1.8966),
    ("Ingris Ramirez (Veewash)", 17, 427.0, 9.7778, 43.6704, 1.7386),
    ("Evelin (VeeWash)", 11, 206.7, 5.0958, 40.5628, 2.1586),
    ("Gabriela Aguilar (Veewash)", 18, 352.2, 10.3867, 33.9087, 1.7330),
)

SIX_DAY_COUNTS = (
    (date(2026, 11, 9), {"pending": 173, "outside_session": 4}),
    (date(2026, 11, 10), {"pending": 161, "outside_session": 7, "nonqualifying": 2}),
    (date(2026, 11, 11), {"pending": 136, "outside_session": 27, "nonqualifying": 2}),
    (date(2026, 11, 12), {"pending": 158, "outside_session": 15, "nonqualifying": 2}),
    (date(2026, 11, 13), {"pending": 158, "outside_session": 16}),
    (date(2026, 11, 14), {"approved": 156, "pending": 3, "excluded": 3, "outside_session": 11, "nonqualifying": 2}),
)


def _measured_session(session_id, status, bags, pounds, hours, employee, bag_ids):
    orders = [
        _bag(bag_id, employee=employee, session_id=session_id, publication_status=status, pounds=pounds)
        for bag_id in bag_ids
    ]
    return {
        "session_id": session_id,
        "publication_status": status,
        "publication": {"status": status, "approval_source": "AUTO" if status == "APPROVED" else None},
        "performance_hours": hours,
        "total_pre_lbs": pounds,
        "lbs_per_hour": round(pounds / hours, 4) if hours else None,
        "orders_completed": bags,
        "orders": orders,
        "start_time": "2026-11-14 08:00:00",
        "end_time": "2026-11-14 16:00:00",
    }


def _november_14_day(*, pending_extra=True, francis_status="APPROVED"):
    employees = []
    completed = []
    next_bag = 1
    for index, (name, bags, pounds, hours, _rate, _bags_rate) in enumerate(APPROVED_NOVEMBER_14, start=1):
        status = francis_status if name.startswith("Francis") else "APPROVED"
        bag_ids = list(range(next_bag, next_bag + bags))
        next_bag += bags
        sessions = [_measured_session(f"S{index}", status, bags, pounds, hours, name, bag_ids)]
        if name.startswith("Gabriela") and pending_extra:
            extra_ids = list(range(next_bag, next_bag + 4))
            next_bag += 4
            sessions.append(_measured_session("S-pending", "UNAPPROVED", 4, 400.0, 8.0, name, extra_ids))
        if name.startswith("Francis"):
            sessions.append(_measured_session("S-excluded", "EXCLUDED", 1, 99.0, 1.0, name, [9000]))
            completed.extend(sessions[-1]["orders"])
        for session in sessions:
            completed.extend(session["orders"])
        employees.append(
            {
                "employee": name,
                "user_id": index,
                "orders_completed": bags + (4 if name.startswith("Gabriela") and pending_extra else 0),
                "total_pre_lbs": pounds + (400.0 if name.startswith("Gabriela") and pending_extra else 0),
                "performance_hours": hours + (8.0 if name.startswith("Gabriela") and pending_extra else 0),
                "lbs_per_hour": None,
                "sessions": sessions,
            }
        )
    outside = [_bag(9100 + i, employee="Outside") for i in range(11)]
    completed.extend(outside)
    missing = [_bag(9200 + i) for i in range(2)]
    completed.extend(missing)
    return employees, completed, outside


def test_approved_rows_ignore_pending_and_excluded_pounds():
    employees, completed, outside = _november_14_day()
    payload = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=completed,
        day={"employees": employees, "outside_folder_session_orders": outside, "needs_attribution_orders": []},
        auto_approval_threshold=40,
        scoring_target=None,
        auto_approve_enabled=True,
    )
    by_name = {row["employee"]: row for row in payload["employees"]}
    for name, bags, pounds, hours, rate, bags_rate in APPROVED_NOVEMBER_14:
        row = by_name[name]
        assert row["bags"] == bags
        assert row["pounds"] == pounds
        assert row["eligible_hours"] == hours
        assert row["reported_rate"] == rate
        assert row["bags_per_hour"] == bags_rate
        assert row["score"]["overall"] is None
        assert row["score"]["activated"] is False
        assert row["measurement_basis"] == "approved_sessions"
    gabriela = by_name["Gabriela Aguilar (Veewash)"]
    assert gabriela["pending_bags"] == 4
    assert gabriela["pending_pounds"] == 400.0
    assert gabriela["pending_hours"] == 8.0
    assert gabriela["reported_rate"] == round(352.2 / 10.3867, 4)
    francis = by_name["Francis (Veewash)"]
    assert francis["pending_pounds"] == 0
    assert francis["pounds"] == 52.8
    approved = payload["approved_productivity"]
    assert approved["approved_bags"] == 156
    assert approved["approved_session_bags"] == 156
    assert approved["approved_pounds"] == 3512.9
    assert approved["approved_hours"] == 75.1231
    assert approved["approved_lbs_per_hour"] == 46.7619
    assert approved["pending_pounds"] == 400.0
    assert approved["pending_is_excluded_from_approved_rate"] is True
    assert payload["team"]["eligible_pounds"] == 3512.9
    assert payload["team"]["average_lbs_per_hour"] == 46.7619
    assert payload["reconciliation"]["categories"]["excluded"] == 1
    assert payload["reconciliation"]["categories"]["outside_session"] == 11
    assert payload["reconciliation"]["categories"]["nonqualifying"] == 2
    assert payload["reconciliation"]["categories"]["unmapped"] == 0
    assert payload["reconciliation"]["invariant_holds"] is True
    assert draft_policy()["active"] is False


def test_reversing_approval_moves_pounds_to_pending():
    employees, completed, outside = _november_14_day(pending_extra=False, francis_status="APPROVED")
    approved = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=completed,
        day={"employees": employees, "outside_folder_session_orders": outside, "needs_attribution_orders": []},
        auto_approval_threshold=40,
    )
    reversed_employees, reversed_completed, reversed_outside = _november_14_day(
        pending_extra=False, francis_status="UNAPPROVED"
    )
    pending = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=reversed_completed,
        day={
            "employees": reversed_employees,
            "outside_folder_session_orders": reversed_outside,
            "needs_attribution_orders": [],
        },
        auto_approval_threshold=40,
    )
    assert approved["approved_productivity"]["approved_pounds"] == 3512.9
    assert pending["approved_productivity"]["approved_pounds"] == round(3512.9 - 52.8, 4)
    francis = next(row for row in pending["employees"] if row["employee"].startswith("Francis"))
    assert francis["bags"] == 0
    assert francis["pounds"] == 0
    assert francis["reported_rate"] is None
    assert francis["pending_bags"] == 2
    assert francis["pending_pounds"] == 52.8
    assert francis["pending_hours"] == 0.8908
    assert pending["reconciliation"]["categories"]["approved"] == 154
    assert pending["reconciliation"]["categories"]["pending"] == 2


def test_week_and_month_keep_pending_out_of_the_approved_rate():
    employees, completed, outside = _november_14_day(pending_extra=True)
    november_14 = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=completed,
        day={"employees": employees, "outside_folder_session_orders": outside, "needs_attribution_orders": []},
        auto_approval_threshold=40,
    )
    waiting = assemble_supervisor_day(
        selected_date=date(2026, 11, 9),
        completed=[_bag(1, employee="Ada", session_id="P", publication_status="UNAPPROVED")],
        day={
            "employees": [
                {
                    "employee": "Ada Waiting",
                    "user_id": 50,
                    "orders_completed": 8,
                    "total_pre_lbs": 900,
                    "performance_hours": 10,
                    "sessions": [
                        _measured_session("PW", "UNAPPROVED", 8, 900, 10, "Ada Waiting", [1]),
                    ],
                }
            ],
            "outside_folder_session_orders": [],
            "needs_attribution_orders": [],
        },
        auto_approval_threshold=40,
    )
    combined = aggregate_period([november_14, waiting])
    assert combined["approved_productivity"]["approved_pounds"] == 3512.9
    assert combined["approved_productivity"]["approved_hours"] == 75.1231
    assert combined["approved_productivity"]["approved_lbs_per_hour"] == 46.7619
    assert combined["approved_productivity"]["pending_pounds"] == round(400.0 + 900, 4)
    assert combined["team"]["eligible_pounds"] == 3512.9
    assert combined["team"]["average_lbs_per_hour"] == 46.7619
    ada = next(row for row in combined["employees"] if row["employee"] == "Ada Waiting")
    assert ada["bags"] == 0
    assert ada["pounds"] == 0
    assert ada["reported_rate"] is None
    assert ada["pending_pounds"] == 900
    gabriela = next(row for row in combined["employees"] if row["employee"].startswith("Gabriela"))
    assert gabriela["pounds"] == 352.2
    assert gabriela["pending_pounds"] == 400.0
    assert gabriela["reported_rate"] == 33.9087
    assert combined["trend"][0]["basis"] == "approved"
    assert combined["reconciliation"]["cross_day_bag_ids_stay_separate"] is True
    assert combined["measurement_note"]


def test_six_day_categories_keep_each_business_date():
    seen = set()
    reused = []
    sequence = 1
    payloads = []
    for day, counts in SIX_DAY_COUNTS:
        completed = []
        sessions = []
        outside = []
        for category, count in counts.items():
            for offset in range(count):
                reuse = day == date(2026, 11, 10) and category == "pending" and offset < 7
                if reuse:
                    bag_id = reused[offset]
                else:
                    bag_id = f"D{sequence:04d}"
                    sequence += 1
                    if day == date(2026, 11, 9) and category == "pending" and len(reused) < 7:
                        reused.append(bag_id)
                seen.add(bag_id)
                row = {
                    "bag_id": bag_id,
                    "order_instance_id": f"{day.isoformat()}-{bag_id}",
                    "pounds": 10,
                    "completion_at": f"{day.isoformat()} 12:00:00",
                }
                completed.append(row)
                if category == "approved":
                    sessions.append({**row, "publication_status": "APPROVED", "session_id": "A", "employee": "Ada"})
                elif category == "pending":
                    sessions.append({**row, "publication_status": "UNAPPROVED", "session_id": "P", "employee": "Ada"})
                elif category == "excluded":
                    sessions.append({**row, "publication_status": "EXCLUDED", "session_id": "E", "employee": "Ada"})
                elif category == "outside_session":
                    outside.append(row)
        report = classify_completed_bags(completed, session_membership=sessions, outside=outside, unmapped=[])
        expected = {key: 0 for key in (
            "approved", "pending", "excluded", "outside_session", "nonqualifying", "unmapped", "unresolved"
        )}
        expected.update(counts)
        assert report["categories"] == expected
        assert report["invariant_holds"] is True
        assert report["total_completed"] == sum(counts.values())
        payloads.append(
            {
                "date_et": day.isoformat(),
                "reconciliation": report,
                "approved_productivity": {"approved_hours": 0, "approved_pounds": 0, "pending_hours": 0, "pending_pounds": 0},
                "employees": [],
            }
        )
    assert len(seen) == 1029
    assert sum(sum(counts.values()) for _day, counts in SIX_DAY_COUNTS) == 1036
    combined = aggregate_period(payloads)
    assert combined["reconciliation"]["total_completed"] == 1036
    assert combined["reconciliation"]["categories"] == {
        "approved": 156,
        "pending": 789,
        "excluded": 3,
        "outside_session": 80,
        "nonqualifying": 8,
        "unmapped": 0,
        "unresolved": 0,
    }
    assert combined["reconciliation"]["invariant_holds"] is True
    assert combined["reconciliation"]["cross_day_bag_ids_stay_separate"] is True


def test_manager_corrected_pre_stays_on_its_approval_state():
    from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs

    corrected = authoritative_evidence_pre_lbs(
        {"corrected_pre_weight_lbs": 18.5, "pre_weight_lbs": 40.0, "post_weight_lbs": 12.0}
    )
    scan = authoritative_evidence_pre_lbs({"pre_weight_lbs": 40.0, "post_weight_lbs": 12.0})
    assert corrected == 18.5
    assert scan == 40.0
    payload = assemble_supervisor_day(
        selected_date=date(2026, 11, 14),
        completed=[
            _bag(1, employee="Ada", session_id="A", publication_status="APPROVED"),
            _bag(2, employee="Ada", session_id="P", publication_status="UNAPPROVED"),
        ],
        day={
            "employees": [
                {
                    "employee": "Ada",
                    "user_id": 3,
                    "sessions": [
                        _measured_session("A", "APPROVED", 1, corrected, 1.0, "Ada", [1]),
                        _measured_session("P", "UNAPPROVED", 1, scan, 1.0, "Ada", [2]),
                    ],
                }
            ],
            "outside_folder_session_orders": [],
            "needs_attribution_orders": [],
        },
        auto_approval_threshold=40,
    )
    ada = payload["employees"][0]
    assert ada["pounds"] == 18.5
    assert ada["bags"] == 1
    assert ada["pending_pounds"] == 40.0
    assert ada["pending_bags"] == 1
    assert payload["approved_productivity"]["approved_lbs_per_hour"] == 18.5


def test_portal_pilot_stays_off_until_a_flag_is_set():
    from backend.supervisor_portal.store import read_flags

    source = inspect.getsource(read_flags)
    assert '"supervisor_portal": False' in source
    assert '"employee_pin_training": False' in source
    assert '"scoring_active": False' in source
    assert "flags[\"scoring_active\"] = False" in source


def test_migration_is_idempotent_and_non_destructive():
    sql = Path("backend/sql/supervisor_portal_v1.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS supervisor_session_adjustments" in sql
    assert "CREATE TABLE IF NOT EXISTS supervisor_quality_incidents" in sql
    assert "DROP TABLE" not in sql.upper().split("ROLLBACK")[0]
    assert "rinse_performance_session_approvals" not in sql
    assert "cleaning_task" not in sql
