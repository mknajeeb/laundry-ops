"""Step-1 VeeWash daily workload classification tests (scrape-gated)."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_veewash_workload import (
    EXC_DISAPPEARED_WITHOUT_COMPLETION,
    EXC_MISSING_ENTRY_SCAN,
    build_step1_headline_summary,
    build_today_validation,
    classify_veewash_workload,
    merge_completions,
)

D0 = date(2026, 7, 20)
D1 = date(2026, 7, 21)


def _pres(active=1, service="WF", rush="RUSH", last_seen=None):
    ls = None
    if last_seen is not None:
        ls = datetime(last_seen.year, last_seen.month, last_seen.day, 23, 0)
    return {
        "active": active,
        "service_type": service,
        "rush_flag": rush,
        "last_seen_at": ls,
    }


def _entry(d, hour=6):
    return {"first_entry_at": datetime(d.year, d.month, d.day, hour, 0), "entry_date": d}


def _comp(d, hour=13, by="Jennifer (VeeWash)"):
    return {
        "completion_at": datetime(d.year, d.month, d.day, hour, 0),
        "completion_date": d,
        "completed_by": by,
    }


def _run(selected, presence, entry, completion):
    return classify_veewash_workload(
        selected_date_et=selected,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )


def _run_state(selected, presence, entry, completion, state):
    return classify_veewash_workload(
        selected_date_et=selected,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag=state,
    )


def test_scrape_backed_plus_dirty_scan_enters_scan_date():
    out = _run(D0, {"A": _pres()}, {"A": _entry(D0)}, {})
    assert out["new_today"] == ["A"]
    assert out["carryover"] == []
    assert out["pending_end_of_date"] == ["A"]  # active, not completed


def test_scrape_backed_without_entry_scan_is_missing_entry_exception():
    out = _run(D0, {"A": _pres(active=1)}, {}, {})
    assert out["missing_entry_scan_exceptions"] == ["A"]
    assert out["new_today"] == [] and out["carryover"] == []
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["exception_reason"] == EXC_MISSING_ENTRY_SCAN


def test_unfinished_entered_bag_carries_to_next_day():
    presence, entry = {"A": _pres()}, {"A": _entry(D0)}
    out0 = _run(D0, presence, entry, {})
    out1 = _run(D1, presence, entry, {})
    assert out0["new_today"] == ["A"]
    assert out1["carryover"] == ["A"]
    row = next(r for r in out1["rows"] if r["bag_id"] == "A")
    assert row["original_entry_date"] == D0.isoformat()
    assert row["current_workload_date"] == D1.isoformat()
    assert row["carried_from_date"] == D0.isoformat()


def test_completed_entered_bag_stops_carrying():
    presence, entry, comp = {"A": _pres()}, {"A": _entry(D0)}, {"A": _comp(D0)}
    out0 = _run(D0, presence, entry, comp)
    out1 = _run(D1, presence, entry, comp)
    assert out0["completed_on_date"] == ["A"]
    # Completed on D0 → not part of D1 workload at all.
    assert out1["new_today"] == [] and out1["carryover"] == []
    assert "A" in out1["not_in_workload"]


def test_cross_day_completion_pending_then_completed():
    presence, entry, comp = {"A": _pres()}, {"A": _entry(D0)}, {"A": _comp(D1, hour=9)}
    out0 = _run(D0, presence, entry, comp)
    out1 = _run(D1, presence, entry, comp)
    # July 20: entered, not completed that day → pending / carried forward.
    assert out0["new_today"] == ["A"] and out0["pending_end_of_date"] == ["A"]
    # July 21: carryover + completed that day, credited.
    assert out1["carryover"] == ["A"] and out1["completed_on_date"] == ["A"]


def test_disappeared_unfinished_bag_is_disappearance_exception():
    # Went missing (last seen) on D0 without completion.
    out = _run(D0, {"A": _pres(active=0, last_seen=D0)}, {"A": _entry(D0)}, {})
    assert out["disappeared_without_completion_exceptions"] == ["A"]
    assert out["pending_end_of_date"] == []
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["exception_reason"] == EXC_DISAPPEARED_WITHOUT_COMPLETION


def test_disappearance_scoped_to_its_day_not_flooding_later_days():
    # Bag disappeared (last seen) on D0; it must NOT count as D1 active workload —
    # it is a prior-day open exception, not perpetual carryover.
    presence = {"A": _pres(active=0, last_seen=D0)}
    entry = {"A": _entry(D0)}
    out0 = _run(D0, presence, entry, {})
    out1 = _run(D1, presence, entry, {})
    assert out0["disappeared_without_completion_exceptions"] == ["A"]
    assert out1["carryover"] == [] and out1["new_today"] == []
    assert out1["disappeared_prior_open_exceptions"] == ["A"]


def test_unconfirmed_absence_stays_pending_not_disappeared():
    # active=0 but only one trustworthy absence → PENDING_DISAPPEARANCE_CONFIRMATION.
    # It must remain operationally Pending, NOT a disappearance exception.
    out = _run_state(
        D0,
        {"A": _pres(active=0, last_seen=D0)},
        {"A": _entry(D0)},
        {},
        {"A": "PENDING_DISAPPEARANCE_CONFIRMATION"},
    )
    assert out["disappeared_without_completion_exceptions"] == []
    assert "A" in out["pending_end_of_date"]
    assert out["pending_disappearance_confirmation"] == ["A"]
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["awaiting_disappearance_confirmation"] is True


def test_confirmed_absence_becomes_disappearance_exception():
    out = _run_state(
        D0,
        {"A": _pres(active=0, last_seen=D0)},
        {"A": _entry(D0)},
        {},
        {"A": "DISAPPEARED_WITHOUT_COMPLETION"},
    )
    assert out["disappeared_without_completion_exceptions"] == ["A"]
    assert "A" not in out["pending_end_of_date"]


def test_present_in_latest_complete_scrape_stays_pending():
    # Live active flag stale (0) from a bad scrape, but confirmation says PRESENT.
    out = _run_state(
        D0,
        {"A": _pres(active=0, last_seen=D0)},
        {"A": _entry(D0)},
        {},
        {"A": "PRESENT"},
    )
    assert out["disappeared_without_completion_exceptions"] == []
    assert "A" in out["pending_end_of_date"]
    assert out["pending_disappearance_confirmation"] == []


def test_completed_bag_absent_twice_remains_completed():
    # Even a CONFIRMED absence never overrides a canonical completion.
    out = _run_state(
        D0,
        {"A": _pres(active=0, last_seen=D0)},
        {"A": _entry(D0)},
        {"A": _comp(D0)},
        {"A": "DISAPPEARED_WITHOUT_COMPLETION"},
    )
    assert out["completed_on_date"] == ["A"]
    assert out["disappeared_without_completion_exceptions"] == []


def test_present_unfinished_bag_stays_pending_not_disappeared():
    # active=1 → still present; unfinished → pending, never a disappearance.
    out = _run(D0, {"A": _pres(active=1, last_seen=D0)}, {"A": _entry(D0)}, {})
    assert out["pending_end_of_date"] == ["A"]
    assert out["disappeared_without_completion_exceptions"] == []


def test_completed_bag_that_disappears_remains_completed():
    out = _run(D0, {"A": _pres(active=0, last_seen=D0)}, {"A": _entry(D0)}, {"A": _comp(D0)})
    assert out["completed_on_date"] == ["A"]
    assert out["disappeared_without_completion_exceptions"] == []


def test_historical_inactive_without_membership_not_included():
    out = _run(D0, {"A": _pres(active=0)}, {}, {})
    assert "A" in out["not_in_workload"]
    assert out["new_today"] == [] and out["carryover"] == []
    assert out["missing_entry_scan_exceptions"] == []  # inactive → not a missing-scan seed


def test_scan_only_bag_absent_from_presence_excluded():
    # B has an entry scan but is NOT in the scrape population → never classified.
    out = _run(D0, {"A": _pres()}, {"A": _entry(D0), "B": _entry(D0)}, {})
    all_ids = set()
    for key in (
        "new_today",
        "carryover",
        "completed_on_date",
        "pending_end_of_date",
        "disappeared_without_completion_exceptions",
        "missing_entry_scan_exceptions",
        "not_in_workload",
    ):
        all_ids.update(out[key])
    assert "B" not in all_ids
    assert all_ids == {"A"}


def test_completed_bag_without_entry_scan_still_counts_as_completed():
    # Completed (Clean scan) but never scanned VeeWash Dirty (entered via Zipvan).
    # Must NOT vanish from completion reporting; counted + flagged as data-quality.
    out = _run(D0, {"A": _pres(active=1)}, {}, {"A": _comp(D0)})
    # NOT in official Completed nor Active Workload — it is a separate bucket.
    assert out["completed_on_date"] == []
    assert out["new_today"] == [] and out["carryover"] == []
    assert out["completed_without_entry_scan"] == ["A"]
    assert out["missing_entry_scan_exceptions"] == []  # completion wins over missing-entry
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["entry_scan_missing"] is True
    assert row["outcome"] == "completed"


def test_completion_wins_over_disappearance():
    # active=0 but a completion exists → completed, never a disappearance exception.
    out = _run(D0, {"A": _pres(active=0, last_seen=D0)}, {"A": _entry(D0)}, {"A": _comp(D0)})
    assert out["completed_on_date"] == ["A"]
    assert out["disappeared_without_completion_exceptions"] == []


def test_merge_prefers_clean_scan_over_rejected_registry():
    # Registry has NO COMPLETED row (old job flipped it to REJECTED, so it is absent
    # from registry_completions), but a Clean-rack scan exists → treated as completed.
    clean = {"A": {"completion_at": datetime(2026, 7, 20, 18, 50), "completion_date": D0,
                   "completed_by": "Singh", "completion_source": "clean_rack_scan"}}
    merged = merge_completions({}, clean)
    assert merged["A"]["completion_date"] == D0
    assert merged["A"]["completion_source"] == "clean_rack_scan"


def test_merge_clean_scan_takes_precedence_when_both_present():
    reg = {"A": {"completion_at": datetime(2026, 7, 21, 1, 0), "completion_date": D1,
                 "completed_by": None, "completion_source": "registry_completed_at"}}
    clean = {"A": {"completion_at": datetime(2026, 7, 20, 18, 50), "completion_date": D0,
                   "completed_by": "Singh", "completion_source": "clean_rack_scan"}}
    merged = merge_completions(reg, clean)
    assert merged["A"]["completion_date"] == D0  # ground-truth clean scan wins
    assert merged["A"]["completed_by"] == "Singh"


def test_merge_registry_fallback_when_no_clean_scan():
    # HD/manual completion with no Clean-rack scan → registry supplies completion.
    reg = {"A": {"completion_at": datetime(2026, 7, 20, 10, 0), "completion_date": D0,
                 "completed_by": None, "completion_source": "registry_completed_at"}}
    merged = merge_completions(reg, {})
    assert merged["A"]["completion_source"] == "registry_completed_at"


def test_today_validation_exactly_one_operational_path():
    presence = {
        "NEWDONE": _pres(),
        "CARRYPEND": _pres(),
        "GONE": _pres(active=0, last_seen=D0),
        "NOENTRY": _pres(active=1),          # active, no entry scan → missing-entry
        "DONE_NOENTRY": _pres(active=1),     # completed but no entry scan
        "OLDGONE": _pres(active=0, last_seen=date(2026, 7, 18)),  # standing backlog
    }
    entry = {
        "NEWDONE": _entry(D0),
        "CARRYPEND": _entry(date(2026, 7, 19)),
        "GONE": _entry(D0),
        "OLDGONE": _entry(date(2026, 7, 18)),
    }
    comp = {"NEWDONE": _comp(D0), "DONE_NOENTRY": _comp(D0)}
    res = _run(D0, presence, entry, comp)
    # Emulate the builder-provided context fields the validation reads.
    res["eligible_presence_orders"] = len(presence)
    res["active_presence_orders"] = sum(1 for p in presence.values() if p["active"] == 1)
    res["excluded_not_presence_backed"] = []
    val = build_today_validation(res, selected_date_et=D0)
    inv = val["invariants"]
    assert inv["every_order_exactly_one_operational_path"]
    assert inv["active_workload_equals_new_plus_carryover"]
    assert inv["established_outcomes_partition"]
    assert inv["total_operational_reconciles"]
    assert inv["no_double_count_completed_vs_missing_entry"]
    ops = val["operational_paths"]
    assert ops["completed_entered_via_dirty"] == 1  # NEWDONE
    assert ops["completed_without_entry_scan"] == 1  # DONE_NOENTRY
    assert ops["pending"] == 1  # CARRYPEND
    assert ops["disappeared_without_completion"] == 1  # GONE
    assert ops["missing_entry_scan_exception"] == 1  # NOENTRY
    # completed-without-entry is NOT part of established workload.
    # Entry-backed members: NEWDONE (completed) + CARRYPEND (pending) + GONE (disappeared) = 3.
    assert val["established_workload"] == 3
    assert val["completed_awaiting_workload_assignment"] == 1
    # Historical disappearance is NOT part of today's operational set.
    assert val["standing_unresolved_backlog"] == 1  # OLDGONE
    assert "OLDGONE" not in sum(val["operational_path_bag_ids"].values(), [])


def test_repeated_builds_are_identical():
    presence = {"A": _pres(), "B": _pres(active=0), "C": _pres()}
    entry = {"A": _entry(D0), "B": _entry(D0)}
    comp = {"B": _comp(D0)}
    assert _run(D0, presence, entry, comp) == _run(D0, presence, entry, comp)


def test_members_partition_and_reconciliation():
    presence = {
        "NEW_PEND": _pres(),
        "CARRY_PEND": _pres(),
        "NEW_DONE": _pres(),
        "GONE": _pres(active=0, last_seen=D0),
    }
    entry = {
        "NEW_PEND": _entry(D0),
        "CARRY_PEND": _entry(D0 - __import__("datetime").timedelta(days=1)),
        "NEW_DONE": _entry(D0),
        "GONE": _entry(D0),
    }
    comp = {"NEW_DONE": _comp(D0)}
    out = _run(D0, presence, entry, comp)
    rec = out["reconciliation"]
    assert rec["total_active_workload_equals_new_plus_carryover"]
    assert rec["members_partitioned"]
    assert rec["pending_reconciles"]
    # No bag appears in more than one outcome bucket.
    buckets = (
        out["completed_on_date"]
        + out["pending_end_of_date"]
        + out["disappeared_without_completion_exceptions"]
    )
    assert len(buckets) == len(set(buckets))


def test_headline_summary_segments_and_reconciliation():
    import datetime as _dt

    yesterday = D0 - _dt.timedelta(days=1)
    presence = {
        "R_NEW_DONE": _pres(rush="RUSH"),
        "R_CARRY_PEND": _pres(rush="RUSH"),
        "N_NEW_PEND": _pres(rush="NON_RUSH"),
        "N_MISS": _pres(rush="NON_RUSH"),  # active, no entry scan -> missing entry
        "R_GONE": _pres(rush="RUSH", active=0, last_seen=D0),
    }
    entry = {
        "R_NEW_DONE": _entry(D0),
        "R_CARRY_PEND": _entry(yesterday),
        "N_NEW_PEND": _entry(D0),
        "R_GONE": _entry(D0),
    }
    comp = {"R_NEW_DONE": _comp(D0)}
    out = _run(D0, presence, entry, comp)
    summ = build_step1_headline_summary(out, selected_date_et=D0, activation_date=D0)

    a = summ["segments"]["all"]
    r = summ["segments"]["rush"]
    n = summ["segments"]["non_rush"]

    # Active workload reconciles: completed + pending + disappeared.
    assert a["active_workload"] == a["completed"] + a["pending"] + a["exceptions"][
        "disappeared_without_completion"
    ]
    # Total operational = active + missing-entry + completed-awaiting.
    assert a["total_operational_orders"] == (
        a["active_workload"]
        + a["exceptions"]["missing_workload_entry_scan"]
        + a["exceptions"]["completed_awaiting_workload_assignment"]
    )
    # Rush + Non-Rush segments partition the "all" totals (no unknown here).
    assert r["active_workload"] + n["active_workload"] == a["active_workload"]
    assert r["completed"] + n["completed"] == a["completed"]
    assert r["pending"] + n["pending"] == a["pending"]
    # Each segment independently reconciles too.
    for s in (r, n):
        assert s["active_workload"] == s["completed"] + s["pending"] + s["exceptions"][
            "disappeared_without_completion"
        ]
    # Missing-entry bag is Non-Rush and not double-counted in the active workload.
    assert "N_MISS" in n["bag_ids"]["missing_workload_entry_scan"]
    assert "N_MISS" not in a["bag_ids"]["new_today"]
    assert "N_MISS" not in a["bag_ids"]["carryover"]
