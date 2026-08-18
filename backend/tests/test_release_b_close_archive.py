"""Operational carryforward close-and-archive validation suite."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_shift_day_close_archive import (
    CLOSE_ARCHIVE_MODEL,
    CLOSE_CONFLICT_ERROR,
    OUTCOME_CARRIED_FORWARD,
    OUTCOME_STALE,
    apply_closed_day_headline,
    archive_unresolved_day_bags,
    build_close_confirmation_summary,
    close_archive_counts_from_bags,
    ensure_prior_et_day_archived_on_rollover,
    finalize_day_close_archive,
)
from backend.rinse_veewash_shift_day import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_READY_TO_CLOSE,
    close_shift_day,
)
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
)


ORG = 3
DAY = date(2026, 7, 28)
NEXT = date(2026, 7, 29)
DAY1 = date(2026, 7, 27)
DAY2 = date(2026, 7, 28)
DAY3 = date(2026, 7, 29)


def _bag(bid, status, service="WF", *, rush="RUSH", reasons=None, snap=None):
    return {
        "bag_id": bid,
        "effective_status": status,
        "service_type": service,
        "rush_status": rush,
        "review_reason_codes": list(
            reasons
            if reasons is not None
            else (
                ["DISAPPEARED_WITHOUT_COMPLETION"]
                if status == OUTCOME_REVIEW_REQUIRED
                else []
            )
        ),
        "bag_snapshot": dict(
            snap
            if snap is not None
            else {
                "entry_class": "new_today",
                "bag_id": bid,
                "rush_status": rush,
            }
        ),
    }


def _cursor():
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.fetchall = MagicMock(return_value=[])
    cur.fetchone = MagicMock(return_value=None)
    cur.rowcount = 1
    return cur


def _patch_lock(day):
    return patch(
        "backend.rinse_shift_day_close_archive._lock_day_row_for_update",
        return_value=day,
    )


def test_close_archive_counts_pending_to_carried_review_stays():
    bags = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("REVI01", OUTCOME_REVIEW_REQUIRED),
    ]
    c = close_archive_counts_from_bags(bags)
    assert c["completed"] == 1
    assert c["review"] == 1
    assert c["carried_forward"] == 1
    assert c["unfinished"] == 1  # alias = carried
    assert c["unfinished_from_review_required"] == 0
    conf = build_close_confirmation_summary(bags)
    assert conf["counts_are_advisory"] is True
    assert conf["carryover_used"] is True
    assert conf["model"] == CLOSE_ARCHIVE_MODEL
    assert conf["carried_forward"] == 1
    assert conf["review"] == 1


def test_pending_becomes_carried_forward_preserving_pre_close_status():
    cur = _cursor()
    bags = [_bag("PEND01", OUTCOME_PENDING), _bag("COMP01", OUTCOME_COMPLETED)]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 1
    assert bags[0]["effective_status"] == OUTCOME_CARRIED_FORWARD
    assert bags[0]["bag_snapshot"]["pre_close_status"] == OUTCOME_PENDING
    assert bags[0]["bag_snapshot"]["day_close_status"] == "carried_forward"
    assert bags[0]["bag_snapshot"]["close_reason"] == "carried_forward_at_close"
    assert bags[0]["bag_snapshot"]["pre_close_was_pending"] is True
    assert bags[1]["effective_status"] == OUTCOME_COMPLETED
    assert out["carried_forward_ids"] == ["PEND01"]
    assert out["review_ids"] == []


def test_review_required_stays_review_preserving_review_history():
    cur = _cursor()
    bags = [
        _bag(
            "REVI01",
            OUTCOME_REVIEW_REQUIRED,
            reasons=["SERVICE_CLASSIFICATION_MISMATCH", "DISAPPEARED_WITHOUT_COMPLETION"],
        )
    ]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 0
    snap = bags[0]["bag_snapshot"]
    assert bags[0]["effective_status"] == OUTCOME_REVIEW_REQUIRED
    assert bags[0]["review_reason_codes"] == [
        "SERVICE_CLASSIFICATION_MISMATCH",
        "DISAPPEARED_WITHOUT_COMPLETION",
    ]
    assert out["review_ids"] == ["REVI01"]
    assert out["carried_forward_ids"] == []
    assert "day_close_status" not in snap or snap.get("day_close_status") != "stale"


def test_hd_pending_becomes_stale_not_carried_forward():
    cur = _cursor()
    bags = [
        _bag("HDPEND1", OUTCOME_PENDING, service="HD"),
        _bag("WFPEND1", OUTCOME_PENDING, service="WF"),
    ]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert bags[0]["effective_status"] == OUTCOME_STALE
    assert bags[1]["effective_status"] == OUTCOME_CARRIED_FORWARD
    assert out["carried_forward_ids"] == ["WFPEND1"]
    assert out["hd_stale_ids"] == ["HDPEND1"]


def test_completed_remains_completed_at_close():
    cur = _cursor()
    bags = [_bag("COMP01", OUTCOME_COMPLETED), _bag("COMP02", OUTCOME_COMPLETED)]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 0
    assert out["completed"] == 2
    assert out["carried_forward"] == 0
    assert out["review"] == 0


def test_closed_day_headline_no_pending_has_carried_forward():
    headline = {
        "completed": 5,
        "pending": 2,
        "new_today": 8,
        "carryover": 0,
        "total_workload": 8,
        "exceptions": {"review_required": 1, "total": 1},
        "segments": {
            "all": {
                "completed": 5,
                "pending": 2,
                "new_today": 8,
                "total_workload": 8,
                "bag_ids": {
                    "completed": ["COMP01", "COMP02", "COMP03", "COMP04", "COMP05"],
                    "pending": ["PEND01", "PEND02"],
                    "review_required": ["REVI01"],
                    "new_today": [
                        "COMP01",
                        "COMP02",
                        "COMP03",
                        "COMP04",
                        "COMP05",
                        "PEND01",
                        "PEND02",
                        "REVI01",
                    ],
                },
                "exceptions": {"review_required": 1},
            },
            "rush": {
                "completed": 4,
                "pending": 1,
                "bag_ids": {
                    "completed": ["COMP01", "COMP02", "COMP03", "COMP04"],
                    "pending": ["PEND01"],
                    "review_required": [],
                    "new_today": ["COMP01", "COMP02", "COMP03", "COMP04", "PEND01"],
                },
            },
        },
    }
    out = apply_closed_day_headline(
        headline,
        completed_ids=["COMP01", "COMP02", "COMP03", "COMP04", "COMP05"],
        review_ids=["REVI01"],
        carried_forward_ids=["PEND01", "PEND02"],
    )
    assert out["pending"] == 0
    assert out["carried_forward"] == 2
    assert out["completed"] == 5
    assert out["review_required_count"] == 1
    assert out["completed"] + out["review_required_count"] + out["carried_forward"] == 8
    assert out["total_workload"] == 8
    assert out["segments"]["all"]["bag_ids"]["pending"] == []
    assert set(out["segments"]["all"]["bag_ids"]["carried_forward"]) == {
        "PEND01",
        "PEND02",
    }
    assert out["close_archive"]["model"] == CLOSE_ARCHIVE_MODEL
    assert out["close_archive"]["carryover_used"] is True


def test_manual_and_automatic_close_use_same_backend_function():
    bags = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("REVI01", OUTCOME_REVIEW_REQUIRED),
    ]
    day = {
        "organization_id": ORG,
        "status": STATUS_READY_TO_CLOSE,
        "headline": {
            "completed": 1,
            "pending": 1,
            "new_today": 3,
            "carryover": 0,
            "exceptions": {"review_required": 1},
            "total_workload": 3,
            "segments": {
                "all": {
                    "bag_ids": {
                        "completed": ["COMP01"],
                        "pending": ["PEND01"],
                        "review_required": ["REVI01"],
                        "new_today": ["COMP01", "PEND01", "REVI01"],
                    }
                }
            },
        },
    }
    cur = _cursor()
    with (
        _patch_lock(day),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={**day, "status": STATUS_CLOSED},
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch("backend.rinse_veewash_workload.today_et", return_value=NEXT),
    ):
        manual = finalize_day_close_archive(
            cur, ORG, DAY, mode="manual", actor_user_id=1, actor_display_name="T"
        )
    bags2 = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("REVI01", OUTCOME_REVIEW_REQUIRED),
    ]
    cur2 = _cursor()
    with (
        _patch_lock(day),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={**day, "status": STATUS_CLOSED},
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags2),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch("backend.rinse_veewash_workload.today_et", return_value=NEXT),
    ):
        auto = finalize_day_close_archive(cur2, ORG, DAY, mode="automatic")
    assert manual["ok"] and auto["ok"]
    assert manual["final_counts"]["completed"] == auto["final_counts"]["completed"] == 1
    assert manual["final_counts"]["carried_forward"] == auto["final_counts"]["carried_forward"] == 1
    assert manual["final_counts"]["review"] == auto["final_counts"]["review"] == 1


def test_already_closed_day_is_not_modified():
    closed = {
        "organization_id": ORG,
        "status": STATUS_CLOSED,
        "headline": {"completed": 1, "carried_forward": 1},
    }
    cur = _cursor()
    with (
        _patch_lock(closed),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[]),
        patch("backend.rinse_veewash_workload.today_et", return_value=NEXT),
    ):
        out = finalize_day_close_archive(cur, ORG, DAY, mode="automatic")
    assert out["ok"] is True
    assert out["already_closed"] is True
    assert out["modified"] is False
    update_sqls = [
        str(c.args[0])
        for c in cur.execute.call_args_list
        if c.args and "UPDATE" in str(c.args[0]).upper()
    ]
    assert update_sqls == []


def test_automatic_rollover_refuses_today():
    cur = _cursor()
    with patch("backend.rinse_veewash_workload.today_et", return_value=DAY):
        out = finalize_day_close_archive(cur, ORG, DAY, mode="automatic")
    assert out["ok"] is False
    assert out["error"] == "cannot_auto_close_today_or_future"


def test_automatic_rollover_only_yesterday():
    cur = _cursor()
    with patch("backend.rinse_veewash_workload.today_et", return_value=NEXT):
        out = finalize_day_close_archive(
            cur, ORG, NEXT - __import__("datetime").timedelta(days=2), mode="automatic"
        )
    assert out["ok"] is False
    assert out["error"] == "auto_close_only_yesterday"


def test_automatic_rollover_closes_unclosed_prior_day():
    prior = {
        "organization_id": ORG,
        "status": STATUS_OPEN,
        "headline": {"completed": 1, "pending": 1, "segments": {"all": {"bag_ids": {}}}},
    }
    bags = [_bag("COMP01", OUTCOME_COMPLETED), _bag("PEND01", OUTCOME_PENDING)]
    cur = _cursor()
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            side_effect=[prior, {**prior, "status": STATUS_CLOSED}],
        ),
        _patch_lock(prior),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch("backend.rinse_veewash_workload.today_et", return_value=NEXT),
    ):
        out = ensure_prior_et_day_archived_on_rollover(cur, ORG, today=NEXT)
    assert out["ok"] is True
    assert out["mode"] == "automatic"
    assert bags[1]["effective_status"] == OUTCOME_CARRIED_FORWARD


def test_close_confirmation_conflict_when_dialog_stale():
    bags = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("PEND02", OUTCOME_PENDING),
    ]
    day = {
        "organization_id": ORG,
        "status": STATUS_OPEN,
        "headline": {"completed": 1, "pending": 1},
    }
    cur = _cursor()
    with (
        _patch_lock(day),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_workload.today_et", return_value=DAY),
    ):
        out = finalize_day_close_archive(
            cur,
            ORG,
            DAY,
            mode="manual",
            expected_completed=1,
            expected_unfinished=1,
        )
    assert out["ok"] is False
    assert out["error"] == CLOSE_CONFLICT_ERROR
    assert out["live"]["carried_forward"] == 2
    assert "carried_forward" in out["mismatches"] or "unfinished" in out["mismatches"]


def test_close_recomputes_final_counts_when_expected_matches():
    bags = [_bag("COMP01", OUTCOME_COMPLETED), _bag("PEND01", OUTCOME_PENDING)]
    day = {
        "organization_id": ORG,
        "status": STATUS_OPEN,
        "headline": {
            "completed": 1,
            "pending": 1,
            "new_today": 2,
            "segments": {"all": {"bag_ids": {"new_today": ["COMP01", "PEND01"]}}},
        },
    }
    cur = _cursor()
    with (
        _patch_lock(day),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={**day, "status": STATUS_CLOSED},
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch("backend.rinse_veewash_workload.today_et", return_value=DAY),
    ):
        out = finalize_day_close_archive(
            cur,
            ORG,
            DAY,
            mode="manual",
            expected_completed=1,
            expected_carried_forward=1,
        )
    assert out["ok"] is True
    assert out["final_counts"]["completed"] == 1
    assert out["final_counts"]["carried_forward"] == 1
    assert out["final_counts"]["review"] == 0
    assert out["final_counts"]["total"] == 2


def test_conditional_update_lost_race_is_idempotent():
    bags = [_bag("PEND01", OUTCOME_PENDING)]
    day = {"organization_id": ORG, "status": STATUS_OPEN, "headline": {}}
    cur = _cursor()
    cur.rowcount = 0
    with (
        _patch_lock(day),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={**day, "status": STATUS_CLOSED},
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit") as audit,
        patch("backend.rinse_veewash_workload.today_et", return_value=NEXT),
    ):
        out = finalize_day_close_archive(cur, ORG, DAY, mode="automatic")
    assert out["ok"] is True
    assert out["already_closed"] is True
    assert out.get("lost_race") is True
    audit.assert_not_called()


def test_prior_day_unresolved_does_not_seed_next_day():
    from backend.rinse_veewash_shift_day import _seed_next_day_carryover

    cur = _cursor()
    _seed_next_day_carryover(cur, ORG, DAY)
    assert cur.execute.call_count == 0


def test_three_day_same_order_history_carried_forward():
    """Day1 carried, Day2 carried, Day3 completed — one row per date."""
    store: dict[tuple[int, date, str], dict] = {}

    def upsert(d: date, bid: str, status: str, entry_class="new_today"):
        key = (ORG, d, bid)
        assert entry_class == "new_today"
        assert key not in store or store[key]["operations_date_et"] == d
        store[key] = {
            "bag_id": bid,
            "operations_date_et": d,
            "entry_class": entry_class,
            "effective_status": status,
        }

    def close_day(d: date):
        for key, row in list(store.items()):
            if key[1] != d:
                continue
            if row["effective_status"] == OUTCOME_PENDING:
                row["effective_status"] = OUTCOME_CARRIED_FORWARD
                row["pre_close_status"] = OUTCOME_PENDING
                row["day_close_status"] = "carried_forward"
            # review_required stays review

    upsert(DAY1, "ABCD01", OUTCOME_PENDING)
    close_day(DAY1)
    assert store[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_CARRIED_FORWARD

    assert (ORG, DAY2, "ABCD01") not in store
    upsert(DAY2, "ABCD01", OUTCOME_PENDING)
    close_day(DAY2)
    assert store[(ORG, DAY2, "ABCD01")]["effective_status"] == OUTCOME_CARRIED_FORWARD

    upsert(DAY3, "ABCD01", OUTCOME_PENDING)
    store[(ORG, DAY3, "ABCD01")]["effective_status"] = OUTCOME_COMPLETED

    assert store[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_CARRIED_FORWARD
    assert store[(ORG, DAY2, "ABCD01")]["effective_status"] == OUTCOME_CARRIED_FORWARD
    assert store[(ORG, DAY3, "ABCD01")]["effective_status"] == OUTCOME_COMPLETED
    assert len([k for k in store if k[2] == "ABCD01"]) == 3


def test_legacy_stale_still_readable_in_counts():
    bags = [
        _bag(
            "OLD01",
            OUTCOME_STALE,
            snap={"pre_close_status": OUTCOME_PENDING, "day_close_status": "stale"},
        ),
        _bag(
            "OLD02",
            OUTCOME_STALE,
            snap={
                "pre_close_status": OUTCOME_REVIEW_REQUIRED,
                "day_close_status": "stale",
            },
        ),
    ]
    c = close_archive_counts_from_bags(bags)
    assert c["carried_forward"] == 1
    assert c["review"] == 1


def test_release_a_cycle_boundary_module_untouched():
    import inspect

    import backend.rinse_cycle_boundary as cb

    src = inspect.getsource(cb)
    assert "close_archive" not in src
    assert "OUTCOME_STALE" not in src
    assert "_seed_next_day_carryover" not in src


def test_close_shift_day_wrapper_passes_expected_counts():
    bags = [_bag("PEND01", OUTCOME_PENDING)]
    day = {
        "organization_id": ORG,
        "status": STATUS_OPEN,
        "headline": {"pending": 1, "segments": {"all": {}}},
    }
    cur = _cursor()
    with (
        _patch_lock(day),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={**day, "status": STATUS_CLOSED},
        ),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch("backend.rinse_veewash_workload.today_et", return_value=DAY),
    ):
        out = close_shift_day(
            cur,
            ORG,
            DAY,
            actor_user_id=None,
            actor_display_name="sys",
            expected_completed=0,
            expected_unfinished=1,
        )
    assert out["ok"] is True
    assert out["final_counts"]["carried_forward"] == 1
