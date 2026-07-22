"""Shift Monitor daily snapshot + close/reopen contracts."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_shift_day import (
    STATUS_CLOSED,
    STATUS_OPEN,
    close_shift_day,
    reopen_shift_day,
    summary_from_day_record,
    validate_close,
)
from backend.rinse_veewash_step1_api import apply_step1_correction


D1 = date(2026, 7, 21)


def _summary(*, review=0, completed=72, pending=9, active=90):
    return {
        "selected_date_et": D1.isoformat(),
        "active_workload": active,
        "completed": completed,
        "pending": pending,
        "new_today": 86,
        "exceptions": {"review_required": review},
        "segments": {
            "all": {
                "active_workload": active,
                "completed": completed,
                "pending": pending,
                "new_today": 86,
                "exceptions": {"review_required": review},
            },
            "wf": {
                "new_today": 74,
                "carryover": 0,
                "completed": 71,
                "pending": 0,
                "exceptions": {"review_required": min(review, 3)},
            },
            "hd": {
                "new_today": 12,
                "carryover": 4,
                "completed": 1,
                "pending": 9,
                "exceptions": {"review_required": max(0, review - 3)},
            },
        },
    }


def test_validate_close_blocks_unresolved_reviews():
    v = validate_close(_summary(review=9, active=90, completed=72, pending=9), allow_unresolved_reviews=False)
    assert v["ok"] is False
    assert "unresolved_review_required" in v["blocking"]


def test_validate_close_allows_override_flag():
    v = validate_close(_summary(review=9, active=90, completed=72, pending=9), allow_unresolved_reviews=True)
    assert v["ok"] is True
    assert v["review_required_count"] == 9


def test_validate_close_arithmetic():
    v = validate_close(
        _summary(review=0, completed=72, pending=9, active=90),
        allow_unresolved_reviews=False,
    )
    # 72+9+0 != 90
    assert v["ok"] is False
    assert "headline_arithmetic_mismatch" in v["blocking"]


def test_summary_from_day_record_marks_closed_readonly():
    day = {
        "status": STATUS_CLOSED,
        "opened_at": "2026-07-21T10:00:00",
        "closed_at": "2026-07-22T02:00:00",
        "closed_by_display_name": "Admin",
        "review_required_count": 0,
        "headline": _summary(review=0, active=81, completed=72, pending=9),
    }
    s = summary_from_day_record(day)
    assert s["shift_day"]["read_only"] is True
    assert s["shift_day"]["status"] == STATUS_CLOSED
    assert s["active_workload"] == 81


def test_reopen_requires_reason():
    cursor = MagicMock()
    with patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": STATUS_CLOSED}):
        out = reopen_shift_day(
            cursor,
            3,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
            reason="",
        )
    assert out["ok"] is False
    assert out["error"] == "reopen_reason_required"


def test_close_requires_override_reason_when_reviews_remain():
    cursor = MagicMock()
    summary = _summary(review=2, completed=72, pending=9, active=83)
    day = {"status": STATUS_OPEN}
    with patch(
        "backend.rinse_veewash_shift_day.build_or_load_step1_for_date",
        return_value=({}, summary, day),
    ):
        out = close_shift_day(
            cursor,
            3,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
            reason="",
            allow_unresolved_reviews=True,
        )
    assert out["ok"] is False
    assert out["error"] == "override_reason_required"


def test_correction_api_exports_callable():
    assert callable(apply_step1_correction)


def test_closed_day_blocks_corrections():
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_CLOSED},
    ):
        out = apply_step1_correction(
            cursor,
            3,
            bag_id="62MRUIXOGF",
            action="mark_completed",
            body={
                "selected_date_et": "2026-07-21",
                "reason": "test",
                "employee": "Ada",
                "completion_at": "2026-07-21T12:00:00",
            },
            actor_user_id=1,
            actor_display_name="Admin",
        )
    assert out["ok"] is False
    assert out["error"] == "shift_closed_reopen_required"


def test_prior_open_day_loads_snapshot_not_live():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    day = {
        "status": STATUS_OPEN,
        "headline": _summary(review=9, active=90, completed=72, pending=9),
        "opened_at": "2026-07-21T10:00:00",
        "last_sync_at": "2026-07-21T22:00:00",
        "review_required_count": 9,
    }
    bags = [
        {
            "bag_id": "62MRUIXOGF",
            "effective_status": "review_required",
            "review_reason_codes": ["COMPLETED_WITHOUT_RECOGNIZED_ENTRY"],
            "bag_snapshot": {"bag_id": "62MRUIXOGF", "outcome": "review_required"},
        }
    ]
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D1),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 7, 22)),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day.build_veewash_daily_workload") as live,
    ):
        wl, summary, meta = build_or_load_step1_for_date(cursor, 3, D1)
    live.assert_not_called()
    assert wl.get("from_snapshot") is True
    assert summary["active_workload"] == 90
    assert "62MRUIXOGF" in wl["review_required"]
    assert meta["status"] == STATUS_OPEN


def test_prior_reopened_day_keeps_snapshot():
    from backend.rinse_veewash_shift_day import STATUS_REOPENED, build_or_load_step1_for_date

    cursor = MagicMock()
    day = {
        "status": STATUS_REOPENED,
        "headline": _summary(review=9, active=90, completed=72, pending=9),
        "review_required_count": 9,
    }
    bags = [{"bag_id": "A", "effective_status": "pending", "bag_snapshot": {"bag_id": "A"}}]
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D1),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 7, 22)),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day.build_veewash_daily_workload") as live,
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot") as persist,
    ):
        wl, summary, meta = build_or_load_step1_for_date(cursor, 3, D1, persist_live=True)
    live.assert_not_called()
    persist.assert_not_called()
    assert wl.get("from_snapshot") is True
    assert summary["active_workload"] == 90
    assert meta["status"] == STATUS_REOPENED


def test_carryover_seeds_pending_bags():
    from backend.rinse_veewash_shift_day import _seed_next_day_carryover
    from backend.rinse_veewash_workload import OUTCOME_PENDING

    cursor = MagicMock()
    bags = [
        {"bag_id": "PEND1", "effective_status": OUTCOME_PENDING, "disposition": None, "bag_snapshot": {"bag_id": "PEND1"}},
        {"bag_id": "DONE1", "effective_status": "completed", "disposition": None, "bag_snapshot": {}},
        {
            "bag_id": "REV1",
            "effective_status": "review_required",
            "disposition": "CARRY_FORWARD",
            "bag_snapshot": {"bag_id": "REV1"},
        },
        {
            "bag_id": "REV2",
            "effective_status": "review_required",
            "disposition": "HISTORICAL_REVIEW_ONLY",
            "bag_snapshot": {},
        },
    ]
    with (
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": STATUS_OPEN}),
    ):
        _seed_next_day_carryover(cursor, 3, D1)
    # INSERT for each carry bag (pending + explicit carry-forward)
    assert cursor.execute.call_count >= 2
    sqls = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list)
    assert "rinse_shift_monitor_day_bags" in sqls


def test_closed_snapshot_not_rewritten_without_force():
    from backend.rinse_veewash_shift_day import persist_day_snapshot

    cursor = MagicMock()
    closed = {"status": STATUS_CLOSED, "headline": _summary(review=0, active=81)}
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=closed),
    ):
        out = persist_day_snapshot(
            cursor,
            3,
            D1,
            workload={"rows": []},
            summary=_summary(review=0, active=999),
            force=False,
        )
    assert out["status"] == STATUS_CLOSED
    cursor.execute.assert_not_called()
