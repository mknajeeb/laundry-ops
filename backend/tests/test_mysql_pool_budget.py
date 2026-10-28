"""Pool size stays inside one worker's checkout budget. Does not open MySQL."""

from backend.db import configured_pool_size
from backend.management_wf_folder_performance import (
    parallel_day_workers,
    pop_stashed_baseline_day,
)


def test_default_pool_leaves_headroom(monkeypatch):
    monkeypatch.delenv("MYSQL_POOL_SIZE", raising=False)
    # Production default is 8 per worker, not the older 12-slot proposal.
    assert configured_pool_size() == 8


def test_pool_size_honors_env_and_bounds(monkeypatch):
    monkeypatch.setenv("MYSQL_POOL_SIZE", "32")
    assert configured_pool_size() == 32
    monkeypatch.setenv("MYSQL_POOL_SIZE", "1")
    assert configured_pool_size() == 4
    monkeypatch.setenv("MYSQL_POOL_SIZE", "nope")
    assert configured_pool_size() == 8


def test_parallel_day_workers_keep_one_connection_for_the_request():
    assert parallel_day_workers(30, 12) == 8
    assert parallel_day_workers(30, 8) == 7
    assert parallel_day_workers(2, 12) == 2
    assert parallel_day_workers(1, 12) == 1


def test_stashed_baseline_day_is_not_left_on_the_payload():
    from datetime import date

    payload = {
        "deltas": {"baseline_date_et": "2026-10-21"},
        "_baseline_day_payload": {"selected_date_et": "2026-10-21", "employees": []},
    }
    day = pop_stashed_baseline_day(payload, date(2026, 10, 21))
    assert day["selected_date_et"] == "2026-10-21"
    assert "_baseline_day_payload" not in payload
    assert pop_stashed_baseline_day({"_baseline_day_payload": {"selected_date_et": "2026-10-20"}}, date(2026, 10, 21)) is None
