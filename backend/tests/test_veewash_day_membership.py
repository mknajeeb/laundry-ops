"""Append-only VeeWash day membership (Jul 23 cutover) — unit tests, no DB."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_day_membership import (
    INCLUSION_ADDED_LATER_IN_DAY,
    INCLUSION_FIRST_SCRAPE_BASELINE,
    STEP1_AUTHORITATIVE_START_ET,
    build_append_only_membership,
    list_valid_same_day_scrapes,
    select_first_valid_scrape_after_midnight,
)

D = date(2026, 7, 23)
assert STEP1_AUTHORITATIVE_START_ET == D

_BASELINE_MOD = "backend.rinse_shift_monitor_baseline"
_TA = "backend.ta_helpers"


def _run(
    run_id: int,
    *,
    finished: datetime,
    rows_found: int = 10,
    status: str = "success",
    dry_run: int = 0,
) -> dict:
    return {
        "id": run_id,
        "status": status,
        "rows_found": rows_found,
        "dry_run": dry_run,
        "finished_at": finished,
        "portal_status": "at_vendor",
        "organization_id": 3,
    }


def _cursor_with_run_rows(run_bags: dict[int, list[str]]) -> MagicMock:
    cursor = MagicMock()
    state: dict[str, object] = {"mode": None, "run_id": None}

    def execute(sql, params=None):
        s = " ".join(str(sql).split()).lower()
        params = params or ()
        if "count(*)" in s and "presence_run_id" in s:
            state["mode"] = "count"
            state["run_id"] = int(params[0])
        elif "from rinse_cleaner_ticket_presence_run_rows" in s and "select" in s:
            state["mode"] = "bags"
            state["run_id"] = int(params[0])
        else:
            state["mode"] = None

    def fetchone():
        if state["mode"] == "count":
            rid = state["run_id"]
            bags = run_bags.get(rid) or []
            return {"c": len(bags)}
        return {"c": 0}

    def fetchall():
        if state["mode"] == "bags":
            rid = state["run_id"]
            return [
                {
                    "bag_id": b,
                    "customer_name": None,
                    "estimated_delivery_date": None,
                    "rush_flag": None,
                    "service_type": "WF",
                    "portal_status": "at_vendor",
                    "raw_row_json": None,
                    "source_batch_id": None,
                }
                for b in (run_bags.get(rid) or [])
            ]
        return []

    cursor.execute.side_effect = execute
    cursor.fetchone.side_effect = fetchone
    cursor.fetchall.side_effect = fetchall
    return cursor


def test_first_scrape_after_midnight_is_baseline():
    scrapes = [
        _run(1, finished=datetime(2026, 7, 22, 23, 50), rows_found=50),
        _run(2, finished=datetime(2026, 7, 23, 0, 5), rows_found=40),
        _run(3, finished=datetime(2026, 7, 23, 8, 0), rows_found=42),
    ]
    run_bags = {2: ["AAAA", "BBBB"], 3: ["AAAA", "CCCC"]}
    cursor = _cursor_with_run_rows(run_bags)

    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
    ):
        baseline, delayed, skip = select_first_valid_scrape_after_midnight(cursor, 3, D)

    assert skip is None
    assert baseline is not None
    assert baseline["id"] == 2
    assert delayed is False


def test_failed_and_empty_scrapes_skipped():
    scrapes = [
        _run(10, finished=datetime(2026, 7, 23, 0, 2), rows_found=0),
        _run(12, finished=datetime(2026, 7, 23, 0, 20), rows_found=8),
    ]
    run_bags = {10: [], 12: ["BAGX1"]}
    cursor = _cursor_with_run_rows(run_bags)

    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
    ):
        baseline, delayed, skip = select_first_valid_scrape_after_midnight(cursor, 3, D)
        same_day = list_valid_same_day_scrapes(cursor, 3, D)

    assert skip is None
    assert baseline is not None
    assert baseline["id"] == 12
    assert delayed is True
    assert [r["id"] for r in same_day] == [12]


def test_later_bag_appended_disappearing_stays_idempotent_no_carryover():
    scrapes = [
        _run(100, finished=datetime(2026, 7, 23, 0, 3), rows_found=3),
        _run(101, finished=datetime(2026, 7, 23, 10, 0), rows_found=3),
        _run(102, finished=datetime(2026, 7, 23, 18, 0), rows_found=2),
    ]
    run_bags = {
        100: ["BAGA", "BAGB", "BAGC"],
        101: ["BAGA", "BAGB", "BAGD"],
        102: ["BAGA", "BAGD"],
    }
    cursor = _cursor_with_run_rows(run_bags)

    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
    ):
        m1 = build_append_only_membership(cursor, 3, D)
        m2 = build_append_only_membership(cursor, 3, D)

    assert m1["ok"] is True
    assert m1["baseline_presence_run_id"] == 100
    assert sorted(m1["baseline_bag_ids"]) == ["BAGA", "BAGB", "BAGC"]
    assert m1["added_later_count"] == 1
    assert m1["added_later"][0]["bag_id"] == "BAGD"
    assert m1["added_later"][0]["source_scrape_id"] == 101
    assert m1["total_count"] == 4

    by_id = m1["membership"]
    assert by_id["BAGA"]["inclusion_source"] == INCLUSION_FIRST_SCRAPE_BASELINE
    assert by_id["BAGB"]["inclusion_source"] == INCLUSION_FIRST_SCRAPE_BASELINE
    assert by_id["BAGC"]["inclusion_source"] == INCLUSION_FIRST_SCRAPE_BASELINE
    assert by_id["BAGD"]["inclusion_source"] == INCLUSION_ADDED_LATER_IN_DAY
    assert "BAGB" in by_id and "BAGC" in by_id
    assert m1["selected_date_et"] == D.isoformat()
    assert "carryover" not in m1
    assert m1["total_count"] == m2["total_count"]
    assert set(m1["membership"]) == set(m2["membership"])


def test_stale_chronology_does_not_promote_to_review():
    from backend.rinse_veewash_review import expand_review_required
    from backend.rinse_veewash_workload import REASON_SCAN_CHRONOLOGY_STALE

    t_early = datetime(2026, 7, 22, 8, 0, 0)
    t_portal = datetime(2026, 7, 23, 14, 0, 0)
    result = {
        "new_today": ["15M7MCEK4J"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["15M7MCEK4J"],
        "review_required": [],
        "disappeared_without_completion_exceptions": [],
        "rows": [
            {
                "bag_id": "15M7MCEK4J",
                "service_type": "WF",
                "outcome": "pending",
                "final_bucket": "pending",
            }
        ],
    }
    out = expand_review_required(
        result,
        selected_date_et=D,
        presence_by_bag={
            "15M7MCEK4J": {
                "service_type": "WF",
                "active": 1,
                "last_seen_at": t_portal,
                "rush_flag": "Rush",
            }
        },
        entry_by_bag={},
        last_scan_at_by_bag={"15M7MCEK4J": t_early},
    )
    assert "15M7MCEK4J" in out["pending_end_of_date"]
    assert "15M7MCEK4J" not in out["review_required"]
    assert REASON_SCAN_CHRONOLOGY_STALE not in (
        out.get("review_reasons_by_bag") or {}
    ).get("15M7MCEK4J", [])
    # Idle pending bags with scan history are not chronology-stale.
    assert "15M7MCEK4J" not in (out.get("stale_scan_chronology_bag_ids") or [])


def test_pending_without_scans_is_stale_association_warning():
    from backend.rinse_veewash_review import expand_review_required
    from backend.rinse_veewash_workload import REASON_SCAN_CHRONOLOGY_STALE

    t_portal = datetime(2026, 7, 23, 14, 0, 0)
    result = {
        "new_today": ["NOSCANBAG01"],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": ["NOSCANBAG01"],
        "review_required": [],
        "disappeared_without_completion_exceptions": [],
        "rows": [
            {
                "bag_id": "NOSCANBAG01",
                "service_type": "WF",
                "outcome": "pending",
                "final_bucket": "pending",
            }
        ],
    }
    out = expand_review_required(
        result,
        selected_date_et=D,
        presence_by_bag={
            "NOSCANBAG01": {
                "service_type": "WF",
                "active": 1,
                "last_seen_at": t_portal,
                "rush_flag": "Rush",
            }
        },
        entry_by_bag={},
        last_scan_at_by_bag={},
    )
    assert "NOSCANBAG01" in out["pending_end_of_date"]
    assert "NOSCANBAG01" not in out["review_required"]
    assert REASON_SCAN_CHRONOLOGY_STALE not in (
        out.get("review_reasons_by_bag") or {}
    ).get("NOSCANBAG01", [])
    assert "NOSCANBAG01" in (out.get("stale_scan_chronology_bag_ids") or [])


def test_pre_cutover_date_returns_unavailable():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch(
            "backend.rinse_veewash_shift_day.get_step1_activation_date",
            return_value=STEP1_AUTHORITATIVE_START_ET,
        ),
        patch(
            "backend.rinse_veewash_shift_day.build_veewash_daily_workload_from_membership"
        ) as memb,
        patch("backend.rinse_veewash_shift_day.build_veewash_daily_workload") as live,
    ):
        wl, summary, meta = build_or_load_step1_for_date(
            cursor, 3, date(2026, 7, 22)
        )
    live.assert_not_called()
    memb.assert_not_called()
    assert wl.get("step1_history_unavailable") is True
    assert summary.get("step1_history_unavailable") is True
    assert meta.get("step1_history_unavailable") is True
    assert summary.get("total_workload") == 0


def test_backfill_before_cutover_refused():
    from backend.rinse_veewash_shift_day import backfill_day_from_live

    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.get_step1_activation_date",
        return_value=STEP1_AUTHORITATIVE_START_ET,
    ):
        out = backfill_day_from_live(cursor, 3, date(2026, 7, 22))
    assert out["ok"] is False
    assert out["error"] == "before_cutover"
