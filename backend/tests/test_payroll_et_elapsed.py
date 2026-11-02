"""Eastern wall elapsed time, including the 2026 DST transitions."""

from datetime import datetime

from backend.payroll_et_elapsed import et_wall_elapsed_seconds
from backend.payroll_operations import session_ids_locked_by_finalized_payroll


def test_gabriela_nov1_shift_does_not_cross_the_fallback_hour():
    # 5:10:10 AM to 2:20:00 PM ET, both after the 2:00 AM fallback.
    start = datetime(2026, 11, 1, 5, 10, 10)
    end = datetime(2026, 11, 1, 14, 20, 0)
    assert et_wall_elapsed_seconds(start, end) == 32990


def test_fallback_hour_is_included_when_the_shift_spans_it():
    # Varun 12:48 AM through 12:08 PM on the day clocks fall back.
    # Naive wall subtraction is 11h 20m; real elapsed time is 12h 20m.
    start = datetime(2026, 11, 1, 0, 48, 0)
    end = datetime(2026, 11, 1, 12, 8, 0)
    assert et_wall_elapsed_seconds(start, end) == 12 * 3600 + 20 * 60
    naive = int((end - start).total_seconds())
    assert et_wall_elapsed_seconds(start, end) - naive == 3600


def test_spring_forward_does_not_pay_the_missing_hour():
    # 1:30 AM to 4:00 AM on 2026-03-08. Clocks jump 2:00 AM -> 3:00 AM.
    start = datetime(2026, 3, 8, 1, 30, 0)
    end = datetime(2026, 3, 8, 4, 0, 0)
    assert et_wall_elapsed_seconds(start, end) == 90 * 60
    assert int((end - start).total_seconds()) - et_wall_elapsed_seconds(start, end) == 3600


def test_overnight_shift_away_from_dst_is_wall_duration():
    start = datetime(2026, 10, 27, 22, 0, 0)
    end = datetime(2026, 10, 28, 6, 15, 0)
    assert et_wall_elapsed_seconds(start, end) == 8 * 3600 + 15 * 60


def test_break_deduction_uses_the_same_elapsed_rule():
    start = datetime(2026, 11, 1, 0, 48, 0)
    end = datetime(2026, 11, 1, 12, 8, 0)
    break_seconds = 1834
    net = max(0, et_wall_elapsed_seconds(start, end) - break_seconds)
    assert net == 12 * 3600 + 20 * 60 - 1834


def test_finalized_payload_locks_only_listed_sessions():
    locked = session_ids_locked_by_finalized_payroll(
        [2118, 2108, 1975],
        ["[1975, 1990]", [2104]],
    )
    assert locked == {1975}


def test_finalized_payload_accepts_decoded_lists():
    assert session_ids_locked_by_finalized_payroll([10], [[10, "11"]]) == {10}
