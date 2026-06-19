"""Tests for org-3 Rinse Exclusive worker stream flag migration helpers."""

from backend.scripts.set_org3_rinse_exclusive_workers import (
    flags_already_rinse_exclusive,
    is_rinse_exclusive,
    normalize_display_name,
    plan_updates,
    should_skip_worker,
)


def test_normalize_display_name_collapses_whitespace():
    assert normalize_display_name("Guiying  Lin") == normalize_display_name("Guiying Lin")


def test_is_rinse_exclusive_matches_frontend_rules():
    assert is_rinse_exclusive({"can_work_rinse": True, "can_work_drop_off": False, "can_work_both": False})
    assert not is_rinse_exclusive({"can_work_rinse": True, "can_work_drop_off": True, "can_work_both": True})
    assert not is_rinse_exclusive({"can_work_rinse": False, "can_work_drop_off": False, "can_work_both": False})
    assert not is_rinse_exclusive({"can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 0})


def test_should_skip_guiying_lin_with_double_space():
    worker = {"display_name": "Guiying  Lin", "can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 1}
    assert should_skip_worker(worker)


def test_plan_updates_skips_guiying_and_already_exclusive():
    workers = [
        {"user_id": 27, "display_name": "Guiying  Lin", "can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 1},
        {"user_id": 22, "display_name": "Alec Coaxum", "can_work_rinse": 1, "can_work_drop_off": 0, "can_work_both": 0},
        {"user_id": 25, "display_name": "Aaliyah Rudowitz", "can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 1},
    ]
    plan = plan_updates(workers)
    assert len(plan["skipped_veewash"]) == 1
    assert plan["skipped_veewash"][0]["display_name"] == "Guiying  Lin"
    assert len(plan["already_rinse_exclusive"]) == 1
    assert len(plan["to_update"]) == 1
    assert plan["to_update"][0]["display_name"] == "Aaliyah Rudowitz"


def test_flags_already_rinse_exclusive():
    assert flags_already_rinse_exclusive({"can_work_rinse": 1, "can_work_drop_off": 0, "can_work_both": 0})
    assert not flags_already_rinse_exclusive({"can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 1})
