"""Scrape completeness guard + two-consecutive-absence disappearance confirmation."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_scrape_completeness import (
    STATE_CONFIRMED,
    STATE_PENDING_CONFIRMATION,
    STATE_PRESENT,
    classify_runs_chronological,
    confirm_disappearances_from_runs,
    evaluate_scrape_completeness,
)


def _run(id_, rows, *, status="success", minute=0, meta=None):
    return {
        "id": id_,
        "rows_found": rows,
        "status": status,
        "started_at": datetime(2026, 7, 21, 10, minute),
        "scrape_meta_json": meta,
    }


# --------------------------------------------------------------------------- #
# 1. Write-time completeness guard                                            #
# --------------------------------------------------------------------------- #
def test_large_row_drop_blocks_mark_missing():
    # The Jul 21 incident: 107 -> 16 is a collapse, must not deactivate bags.
    g = evaluate_scrape_completeness(captured_rows=16, prior_complete_rows=107)
    assert g["allow_mark_missing"] is False
    assert "row_count_drop" in g["reason"]


def test_normal_small_variation_allows_mark_missing():
    # 107 -> 102 is normal churn: mark_missing allowed.
    g = evaluate_scrape_completeness(captured_rows=102, prior_complete_rows=107)
    assert g["allow_mark_missing"] is True
    assert g["reason"] is None


def test_small_prior_population_not_penalized():
    # Below the min-population threshold, legitimate swings are not flagged.
    g = evaluate_scrape_completeness(captured_rows=5, prior_complete_rows=22)
    assert g["allow_mark_missing"] is True


def test_portal_reconcile_mismatch_blocks_mark_missing():
    # Captured far below what the portal itself reported.
    g = evaluate_scrape_completeness(
        captured_rows=40, prior_complete_rows=None, portal_reported_orders=100
    )
    assert g["allow_mark_missing"] is False
    assert "portal_reconcile" in g["reason"]


def test_page_not_loaded_and_max_pages_block():
    assert evaluate_scrape_completeness(
        captured_rows=100, prior_complete_rows=100, page_loaded=False
    )["allow_mark_missing"] is False
    assert evaluate_scrape_completeness(
        captured_rows=100, prior_complete_rows=100, reached_max_pages=True
    )["allow_mark_missing"] is False


def test_first_run_bootstrap_is_trustworthy():
    g = evaluate_scrape_completeness(captured_rows=80, prior_complete_rows=None)
    assert g["allow_mark_missing"] is True


def test_single_dip_not_corroborated_is_anomalous():
    # 107 -> 16 with the previous run still at 107 → uncorroborated dip → anomalous.
    g = evaluate_scrape_completeness(
        captured_rows=16, prior_complete_rows=107, previous_run_rows=107
    )
    assert g["allow_mark_missing"] is False


def test_corroborated_level_shift_is_trustworthy():
    # 107 baseline, but the previous run was ALSO ~16 → real downward level shift.
    g = evaluate_scrape_completeness(
        captured_rows=16, prior_complete_rows=107, previous_run_rows=15
    )
    assert g["allow_mark_missing"] is True
    assert g["reason"] is None


# --------------------------------------------------------------------------- #
# 2. Read-time run trustworthiness classification                             #
# --------------------------------------------------------------------------- #
def test_anomalous_run_flagged_among_complete_runs():
    runs = [
        _run(1, 100, minute=0),
        _run(2, 105, minute=10),
        _run(3, 16, minute=20),   # collapse -> anomalous
        _run(4, 102, minute=30),
    ]
    annotated = {r["id"]: r for r in classify_runs_chronological(runs)}
    assert annotated[1]["trustworthy"] is True
    assert annotated[2]["trustworthy"] is True
    assert annotated[3]["trustworthy"] is False
    assert annotated[4]["trustworthy"] is True


def test_sustained_low_level_rebaselines_on_second_run():
    # 107 -> 16 (anomalous dip) -> 16 (corroborated, real level shift → trustworthy).
    runs = [
        _run(1, 107, minute=0),
        _run(2, 16, minute=10),   # first dip: anomalous
        _run(3, 16, minute=20),   # corroborated: trustworthy new level
    ]
    annotated = {r["id"]: r for r in classify_runs_chronological(runs)}
    assert annotated[1]["trustworthy"] is True
    assert annotated[2]["trustworthy"] is False
    assert annotated[3]["trustworthy"] is True


def test_failed_and_zero_row_runs_untrusted():
    runs = [_run(1, 100, minute=0), _run(2, 0, minute=10), _run(3, 100, status="failed", minute=20)]
    annotated = {r["id"]: r for r in classify_runs_chronological(runs)}
    assert annotated[2]["trustworthy"] is False
    assert annotated[3]["trustworthy"] is False


# --------------------------------------------------------------------------- #
# 3. Two-consecutive-complete-absence confirmation                            #
# --------------------------------------------------------------------------- #
def _confirm(runs, presence_by_run, bag="A"):
    annotated = classify_runs_chronological(runs)
    return confirm_disappearances_from_runs(annotated, presence_by_run, [bag])[bag]


def test_one_complete_absence_stays_pending():
    runs = [_run(1, 100, minute=0), _run(2, 100, minute=10)]
    # present in run1, absent in the latest complete run2.
    res = _confirm(runs, {1: {"A"}})
    assert res["state"] == STATE_PENDING_CONFIRMATION
    assert res["trustworthy_absent_runs"] == 1


def test_two_consecutive_complete_absences_confirm():
    runs = [_run(1, 100, minute=0), _run(2, 100, minute=10)]
    res = _confirm(runs, {})  # absent in both complete runs
    assert res["state"] == STATE_CONFIRMED
    assert res["trustworthy_absent_runs"] == 2


def test_bad_run_between_complete_runs_is_ignored():
    # r2 is an anomalous collapse (absent there does not count). Latest complete r3
    # still contains the bag → present, no exception.
    runs = [_run(1, 100, minute=0), _run(2, 10, minute=10), _run(3, 100, minute=20)]
    res = _confirm(runs, {1: {"A"}, 3: {"A"}})
    assert res["state"] == STATE_PRESENT
    assert res["trustworthy_absent_runs"] == 0


def test_bad_run_absence_does_not_count_toward_streak():
    # Absent in the anomalous r2 AND the complete r3, present in complete r1.
    # Only r3 (complete) counts → single absence → pending, not confirmed.
    runs = [_run(1, 100, minute=0), _run(2, 10, minute=10), _run(3, 100, minute=20)]
    res = _confirm(runs, {1: {"A"}})
    assert res["state"] == STATE_PENDING_CONFIRMATION
    assert res["trustworthy_absent_runs"] == 1


def test_bag_returns_after_one_absence_no_exception():
    runs = [_run(1, 100, minute=0), _run(2, 100, minute=10), _run(3, 100, minute=20)]
    # present, absent, present again → latest complete has it → present.
    res = _confirm(runs, {1: {"A"}, 3: {"A"}})
    assert res["state"] == STATE_PRESENT


def test_single_trustworthy_run_cannot_confirm():
    # Only one complete run absent → cannot reach two consecutive → pending at most.
    runs = [_run(1, 100, minute=0)]
    res = _confirm(runs, {})
    assert res["state"] == STATE_PENDING_CONFIRMATION
