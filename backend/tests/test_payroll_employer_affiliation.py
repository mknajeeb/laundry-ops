"""Tests for payroll employer affiliation helpers."""

from backend.payroll_employer_affiliation import (
    EMPLOYER_AFFILIATION_BOTH,
    EMPLOYER_AFFILIATION_NONE,
    EMPLOYER_AFFILIATION_RINSE,
    EMPLOYER_AFFILIATION_VEEWASH,
    employer_affiliation_from_flags,
    flags_from_employer_affiliation,
    normalize_employer_affiliation,
)


def test_flags_round_trip_rinse_exclusive():
    flags = flags_from_employer_affiliation(EMPLOYER_AFFILIATION_RINSE)
    assert flags == {
        "can_work_rinse": True,
        "can_work_drop_off": False,
        "can_work_both": False,
    }
    assert employer_affiliation_from_flags(flags) == EMPLOYER_AFFILIATION_RINSE


def test_flags_round_trip_veewash():
    flags = flags_from_employer_affiliation(EMPLOYER_AFFILIATION_VEEWASH)
    assert flags == {
        "can_work_rinse": False,
        "can_work_drop_off": True,
        "can_work_both": False,
    }
    assert employer_affiliation_from_flags(flags, organization_slug="washpro") == EMPLOYER_AFFILIATION_VEEWASH
    assert employer_affiliation_from_flags(flags, organization_slug="veewash") == "veewash"


def test_flags_round_trip_both():
    flags = flags_from_employer_affiliation(EMPLOYER_AFFILIATION_BOTH)
    assert flags == {
        "can_work_rinse": True,
        "can_work_drop_off": True,
        "can_work_both": True,
    }
    assert employer_affiliation_from_flags(flags) == EMPLOYER_AFFILIATION_BOTH


def test_legacy_all_true_maps_to_both():
    assert (
        employer_affiliation_from_flags(
            {"can_work_rinse": True, "can_work_drop_off": True, "can_work_both": True}
        )
        == EMPLOYER_AFFILIATION_BOTH
    )


def test_flags_round_trip_none():
    flags = flags_from_employer_affiliation(EMPLOYER_AFFILIATION_NONE)
    assert flags == {
        "can_work_rinse": False,
        "can_work_drop_off": False,
        "can_work_both": False,
    }
    assert employer_affiliation_from_flags(flags) == EMPLOYER_AFFILIATION_NONE


def test_normalize_employer_affiliation():
    assert normalize_employer_affiliation("Rinse_Exclusive") == EMPLOYER_AFFILIATION_RINSE
    assert normalize_employer_affiliation("NONE") == EMPLOYER_AFFILIATION_NONE
    assert normalize_employer_affiliation("invalid") is None


def test_save_employer_affiliation_none_clears_future_planned():
    from datetime import date, time
    from unittest.mock import MagicMock, patch

    from backend.payroll_employer_affiliation import save_employer_affiliation

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.rowcount = 2

    with patch(
        "backend.payroll_employer_affiliation._organization_slug", return_value="veewash"
    ), patch(
        "backend.payroll_schedule.save_scheduling_profile"
    ), patch(
        "backend.payroll_schedule.get_worker_by_user_id",
        return_value={"id": 1191, "display_name": "Paola Almiron"},
    ), patch(
        "backend.business_time.business_today", return_value=date(2026, 8, 28)
    ), patch(
        "backend.planned_weekly_schedule.clear_future_planned_schedule_entries_for_user",
        return_value=4,
    ) as clear_fn:
        out = save_employer_affiliation(conn, 3, 29, "none")

    assert out["employer_affiliation"] == "none"
    assert out["future_entries_cleared"] == 4
    clear_fn.assert_called_once()
    assert clear_fn.call_args.kwargs.get("as_of") == date(2026, 8, 28) or clear_fn.call_args[1].get(
        "as_of"
    ) == date(2026, 8, 28)
