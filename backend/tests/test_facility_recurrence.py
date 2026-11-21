"""Recurrence, machine targets, and register sync. No production rows."""

from datetime import date

from backend.facility_machines import codes_missing_from_register
from backend.task_recurrence import (
    apply_generation,
    exclusion_covers,
    machine_codes_from_completion,
    machine_week_targets,
    normalize_recurrence,
    occurrence_key,
    plan_slots,
    reconcile_open_slots,
    reschedule_slot,
    schedule_occurrence_rows,
    skip_slot,
    unique_machine_codes,
    weekly_task_progress,
)


WEEK = date(2026, 11, 15)  # Sunday


def test_preferred_days_generate_those_occurrences_only():
    rule = normalize_recurrence(
        {"mode": "recurring", "weekly_frequency": 3, "weekdays": [1, 3, 5], "active": True}
    )
    slots = plan_slots(rule, WEEK)
    assert [slot["day_of_week"] for slot in slots] == [1, 3, 5]
    assert all(slot["scheduled"] for slot in slots)


def test_frequency_without_days_stays_unscheduled():
    rule = normalize_recurrence({"mode": "recurring", "weekly_frequency": 3, "weekdays": []})
    slots = plan_slots(rule, WEEK)
    assert len(slots) == 3
    assert all(slot["day_of_week"] is None for slot in slots)


def test_generation_is_idempotent_and_keeps_completed_slots():
    planned = plan_slots(
        normalize_recurrence({"mode": "recurring", "weekly_frequency": 2, "weekdays": [1, 3]}),
        WEEK,
    )
    first = apply_generation([], planned, task_code="custom_bathroom_cleaning", week_start=WEEK)
    assert len(first) == 2
    done = dict(first[0])
    done["status"] = "completed"
    second = apply_generation([done, first[1]], planned, task_code="custom_bathroom_cleaning", week_start=WEEK)
    assert second == []
    moved = reschedule_slot(first[1], 2, "Move to Tuesday")
    assert moved["recurrence_key"] == first[1]["recurrence_key"]
    assert moved["day_of_week"] == 2
    skipped = skip_slot(first[1], "Holiday")
    assert skipped["status"] == "skipped"


def test_weekday_change_keeps_the_slot_and_frequency_drop_cancels_only_open_slots():
    planned = plan_slots(
        normalize_recurrence({"mode": "recurring", "weekly_frequency": 2, "weekdays": [1, 3]}),
        WEEK,
    )
    existing = apply_generation([], planned, task_code="custom_facility_mopping", week_start=WEEK)
    moved = plan_slots(
        normalize_recurrence({"mode": "recurring", "weekly_frequency": 1, "weekdays": [2]}),
        WEEK,
    )
    assert occurrence_key("custom_facility_mopping", WEEK, planned[0]) == occurrence_key(
        "custom_facility_mopping", WEEK, moved[0]
    )
    updates = reconcile_open_slots(existing, moved, task_code="custom_facility_mopping", week_start=WEEK)
    by_key = {row["recurrence_key"]: row for row in updates}
    assert by_key[existing[0]["recurrence_key"]]["day_of_week"] == 2
    assert by_key[existing[1]["recurrence_key"]]["status"] == "cancelled"
    completed = dict(existing[1])
    completed["status"] = "completed"
    kept = reconcile_open_slots([existing[0], completed], moved, task_code="custom_facility_mopping", week_start=WEEK)
    assert completed["recurrence_key"] not in {row["recurrence_key"] for row in kept}


def test_unassigned_occurrences_are_planner_rows_and_assigned_ones_are_not_duplicated():
    occurrence = {
        "task_code": "custom_bathroom_cleaning",
        "recurrence_key": "custom_bathroom_cleaning:2026-11-15:slot:1",
        "status": "due",
        "day_of_week": None,
    }
    assigned = {
        "user_id": 7,
        "role": "custom_bathroom_cleaning",
        "remarks": "recurring:custom_bathroom_cleaning:2026-11-15:slot:1",
    }
    rows = schedule_occurrence_rows([occurrence], [assigned])
    assert rows == []
    assert assigned["recurring"] is True
    open_rows = schedule_occurrence_rows([occurrence], [])
    assert open_rows[0]["unassigned_occurrence"] is True
    assert open_rows[0]["user_id"] == 0
    assert open_rows[0]["day_of_week"] is None


def test_shared_occurrence_does_not_inflate_the_weekly_target():
    progress = weekly_task_progress(
        frequency=3,
        today=date(2026, 11, 21),
        occurrences=[
            {"status": "verified", "week_start": "2026-11-15", "day_of_week": 1},
            {"status": "pending_verification", "week_start": "2026-11-15", "day_of_week": 3},
            {"status": "due", "week_start": "2026-11-15", "day_of_week": 5},
        ],
    )
    assert progress["required"] == 3
    assert progress["completed"] == 2
    assert progress["verified"] == 1
    assert progress["pending_verification"] == 1
    assert progress["remaining"] == 1


def test_machine_frequency_is_per_machine_and_duplicates_count_once():
    assert unique_machine_codes(["W1", "W1", "w1", "W2"]) == ["W1", "W2"]
    codes = machine_codes_from_completion({"values": {"washer_machines": ["W1", "W1", "W2"]}})
    assert codes == ["W1", "W2"]
    machines = [
        {"machine_code": "W1", "cleaning_eligible": True, "operational_status": "operational"},
        {"machine_code": "W2", "cleaning_eligible": True, "operational_status": "operational"},
    ]
    cleanings = [
        {"machine_code": "W1", "occurrence_key": "a", "user_id": 4, "verified": True},
        {"machine_code": "W1", "occurrence_key": "a", "user_id": 5, "verified": True},
        {"machine_code": "W1", "occurrence_key": "b", "user_id": 4, "verified": False},
    ]
    totals = machine_week_targets(machines, cleanings, [], frequency=2, week_start=WEEK)
    by_code = {row["machine_code"]: row for row in totals["machines"]}
    assert by_code["W1"]["completed"] == 2
    assert by_code["W1"]["remaining"] == 0
    assert by_code["W2"]["completed"] == 0
    assert by_code["W2"]["remaining"] == 2
    assert totals["required"] == 4


def test_exclusion_is_prospective_and_register_does_not_rewrite_codes():
    assert exclusion_covers(
        {"effective_start": "2026-11-20", "effective_end": None, "machine_code": "W2"},
        WEEK,
    ) is False
    assert exclusion_covers(
        {"effective_start": "2026-11-15", "effective_end": "2026-11-18", "machine_code": "W2"},
        WEEK,
    ) is True
    added = codes_missing_from_register({"W1"}, {"washers": {"W1": 30, "W2": 20}, "dryers": {}})
    assert [row["machine_code"] for row in added] == ["W2"]


def test_repeated_reports_stay_separate():
    reports = [
        {"id": 1, "location_number": "W1", "status": "new"},
        {"id": 2, "location_number": "W1", "status": "new"},
    ]
    assert len({row["id"] for row in reports if row["location_number"] == "W1"}) == 2
