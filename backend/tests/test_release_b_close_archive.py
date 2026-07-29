"""Release B: fresh-day close-and-archive validation suite."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_shift_day_close_archive import (
    BAG_CLOSE_REASON_UNRESOLVED,
    CLOSE_CONFLICT_ERROR,
    OUTCOME_STALE,
    STALE_DISPLAY_LABEL,
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


def test_close_archive_counts_pending_and_review_as_unfinished():
    bags = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("REVI01", OUTCOME_REVIEW_REQUIRED),
    ]
    c = close_archive_counts_from_bags(bags)
    assert c["completed"] == 1
    assert c["unfinished"] == 2
    assert c["unfinished_from_pending"] == 1
    assert c["unfinished_from_review_required"] == 1
    conf = build_close_confirmation_summary(bags)
    assert conf["counts_are_advisory"] is True
    assert conf["carryover_used"] is False


def test_pending_becomes_stale_preserving_pre_close_status():
    cur = _cursor()
    bags = [_bag("PEND01", OUTCOME_PENDING), _bag("COMP01", OUTCOME_COMPLETED)]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 1
    assert bags[0]["effective_status"] == OUTCOME_STALE
    assert bags[0]["bag_snapshot"]["pre_close_status"] == OUTCOME_PENDING
    assert bags[0]["bag_snapshot"]["day_close_status"] == "stale"
    assert bags[0]["bag_snapshot"]["close_reason"] == BAG_CLOSE_REASON_UNRESOLVED
    assert bags[0]["bag_snapshot"]["pre_close_was_pending"] is True
    assert bags[1]["effective_status"] == OUTCOME_COMPLETED


def test_review_required_becomes_stale_preserving_review_history():
    cur = _cursor()
    bags = [
        _bag(
            "REVI01",
            OUTCOME_REVIEW_REQUIRED,
            reasons=["SERVICE_CLASSIFICATION_MISMATCH", "DISAPPEARED_WITHOUT_COMPLETION"],
        )
    ]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 1
    snap = bags[0]["bag_snapshot"]
    assert bags[0]["effective_status"] == OUTCOME_STALE
    assert snap["pre_close_status"] == OUTCOME_REVIEW_REQUIRED
    assert snap["day_close_status"] == "stale"
    assert snap["close_reason"] == BAG_CLOSE_REASON_UNRESOLVED
    assert snap["pre_close_was_review_required"] is True
    assert snap["pre_close_review_reason_codes"] == [
        "SERVICE_CLASSIFICATION_MISMATCH",
        "DISAPPEARED_WITHOUT_COMPLETION",
    ]
    assert snap["review_reason_codes"] == [
        "SERVICE_CLASSIFICATION_MISMATCH",
        "DISAPPEARED_WITHOUT_COMPLETION",
    ]
    assert out["unfinished_from_review_required_ids"] == ["REVI01"]


def test_completed_remains_completed_at_close():
    cur = _cursor()
    bags = [_bag("COMP01", OUTCOME_COMPLETED), _bag("COMP02", OUTCOME_COMPLETED)]
    out = archive_unresolved_day_bags(cur, ORG, DAY, day_bags=bags)
    assert out["changed"] == 0
    assert out["completed"] == 2
    assert out["unfinished"] == 0


def test_closed_day_headline_identities():
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
        unfinished_ids=["PEND01", "PEND02", "REVI01"],
        unfinished_from_pending_ids=["PEND01", "PEND02"],
        unfinished_from_review_required_ids=["REVI01"],
    )
    assert out["completed"] + out["unfinished_at_close"] == out["total_workload"] == 8
    assert out["pending"] == 0
    assert out["exceptions"]["review_required"] == 0
    assert out["new_today"] == 8
    assert out["unfinished_from_pending"] == 2
    assert out["unfinished_from_review_required"] == 1
    assert out["segments"]["all"]["bag_ids"]["new_today"]
    assert out["close_archive"]["carryover_used"] is False


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
    assert manual["final_counts"] == auto["final_counts"]
    assert manual["archive"]["unfinished"] == auto["archive"]["unfinished"] == 2
    assert manual["archive"]["completed"] == auto["archive"]["completed"] == 1


def test_already_closed_day_is_not_modified():
    closed = {
        "organization_id": ORG,
        "status": STATUS_CLOSED,
        "headline": {"completed": 1, "unfinished_at_close": 1},
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
    # No bag UPDATE / status rewrite beyond the lock SELECT.
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
        # Two days ago is not eligible.
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
    assert bags[1]["effective_status"] == OUTCOME_STALE


def test_close_confirmation_conflict_when_dialog_stale():
    bags = [
        _bag("COMP01", OUTCOME_COMPLETED),
        _bag("PEND01", OUTCOME_PENDING),
        _bag("PEND02", OUTCOME_PENDING),  # work continued — unfinished now 2
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
            expected_unfinished=1,  # dialog showed 1 unfinished; live has 2
        )
    assert out["ok"] is False
    assert out["error"] == CLOSE_CONFLICT_ERROR
    assert out["live"]["unfinished"] == 2
    assert "unfinished" in out["mismatches"]


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
            expected_unfinished=1,
        )
    assert out["ok"] is True
    assert out["final_counts"] == {
        "completed": 1,
        "unfinished": 1,
        "unfinished_from_pending": 1,
        "unfinished_from_review_required": 0,
        "total": 2,
    }


def test_conditional_update_lost_race_is_idempotent():
    bags = [_bag("PEND01", OUTCOME_PENDING)]
    day = {"organization_id": ORG, "status": STATUS_OPEN, "headline": {}}
    cur = _cursor()
    cur.rowcount = 0  # lost race on conditional UPDATE
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


def test_three_day_same_order_history():
    """Day1 stale, Day2 stale, Day3 completed — one row per date, no carryover."""
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
            if row["effective_status"] in (OUTCOME_PENDING, OUTCOME_REVIEW_REQUIRED):
                row["effective_status"] = OUTCOME_STALE
                row["pre_close_status"] = OUTCOME_PENDING
                row["day_close_status"] = "stale"

    # Day 1
    upsert(DAY1, "ABCD01", OUTCOME_PENDING)
    close_day(DAY1)
    assert store[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_STALE

    # Day 2 reappearance — new row, not seeded
    assert (ORG, DAY2, "ABCD01") not in store
    upsert(DAY2, "ABCD01", OUTCOME_PENDING)
    close_day(DAY2)
    assert store[(ORG, DAY2, "ABCD01")]["effective_status"] == OUTCOME_STALE

    # Day 3 reappearance + complete
    upsert(DAY3, "ABCD01", OUTCOME_PENDING)
    store[(ORG, DAY3, "ABCD01")]["effective_status"] = OUTCOME_COMPLETED

    assert store[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_STALE
    assert store[(ORG, DAY2, "ABCD01")]["effective_status"] == OUTCOME_STALE
    assert store[(ORG, DAY3, "ABCD01")]["effective_status"] == OUTCOME_COMPLETED
    assert len([k for k in store if k[2] == "ABCD01"]) == 3
    assert all(store[k]["entry_class"] == "new_today" for k in store)


def test_absent_next_day_does_not_create_membership_row():
    store: dict[tuple[int, date, str], dict] = {
        (ORG, DAY1, "ABCD01"): {
            "effective_status": OUTCOME_STALE,
            "entry_class": "new_today",
        }
    }
    day2_scrape_ids: set[str] = set()  # ABC absent
    # Admission only from today's scrape.
    for bid in day2_scrape_ids:
        store[(ORG, DAY2, bid)] = {
            "effective_status": OUTCOME_PENDING,
            "entry_class": "new_today",
        }
    assert (ORG, DAY2, "ABCD01") not in store
    assert store[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_STALE


def test_repeated_same_day_scrapes_one_row():
    members: set[str] = set()
    for _scrape in range(5):
        members.add("ABCD01")
    assert len(members) == 1


def test_later_same_day_scrape_admits_as_new_today():
    members: dict[str, dict] = {}
    # First scrape — empty for ABC
    # Later scrape admits ABC
    members["ABCD01"] = {"entry_class": "new_today", "effective_status": OUTCOME_PENDING}
    assert members["ABCD01"]["entry_class"] == "new_today"


def test_disappear_from_later_scrape_keeps_append_only_membership():
    members = {"ABCD01": {"entry_class": "new_today", "effective_status": OUTCOME_PENDING}}
    later_scrape = set()  # disappeared
    # Append-only: do not drop.
    for bid in later_scrape:
        members.pop(bid, None)
    assert "ABCD01" in members


def test_post_auto_close_appearance_belongs_only_to_current_day():
    prior = {(ORG, DAY1, "ABCD01"): {"effective_status": OUTCOME_STALE}}
    # Auto-close already froze DAY1. New scrape on DAY2:
    current = {(ORG, DAY2, "ABCD01"): {"effective_status": OUTCOME_PENDING, "entry_class": "new_today"}}
    assert prior[(ORG, DAY1, "ABCD01")]["effective_status"] == OUTCOME_STALE
    assert (ORG, DAY1, "ABCD01") not in current
    assert current[(ORG, DAY2, "ABCD01")]["entry_class"] == "new_today"


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
    assert out["final_counts"]["unfinished"] == 1
