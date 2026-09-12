"""Set-based first-absence: oracle equivalence + query-count bounds."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from backend.rinse_wf_disappeared_from_portal import (
    _first_establishing_absence_run,
    _first_establishing_absence_runs_bulk,
    _pick_first_establishing_from_candidates,
)


class _CountingCursor:
    """Minimal dictionary cursor that records execute SQL families."""

    def __init__(self, *, runs_after_min: list[dict[str, Any]], present_pairs: set[tuple[str, int]]):
        self.runs_after_min = list(runs_after_min)
        self.present_pairs = set(present_pairs)
        self.query_count = 0
        self.sqls: list[str] = []
        self._result: list[dict[str, Any]] = []
        self._mode = "idle"

    def execute(self, sql: str, params=None):
        self.query_count += 1
        s = " ".join(str(sql).split()).lower()
        self.sqls.append(s)
        params = params or ()
        if "from rinse_cleaner_ticket_presence_runs" in s and "id >" in s:
            # Bulk: id > min_lp  OR oracle: id > lp LIMIT
            min_lp = int(params[2]) if len(params) >= 3 else 0
            cands = [r for r in self.runs_after_min if int(r["id"]) > min_lp]
            if "limit" in s and len(params) >= 4:
                cands = cands[: int(params[3])]
            self._result = [dict(r) for r in cands]
            self._mode = "runs"
            return
        if "from rinse_cleaner_ticket_presence_run_rows" in s:
            # Oracle: bag_id = %s AND presence_run_id IN (...)
            # Bulk: bag_id IN (...) AND presence_run_id IN (...)
            if "bag_id = %s" in s or "bag_id = ?" in s:
                bag = str(params[1])
                run_ids = [int(x) for x in params[2:]]
                self._result = [
                    {"presence_run_id": rid, "bag_id": bag}
                    for rid in run_ids
                    if (bag, rid) in self.present_pairs
                ]
            else:
                # bulk: org, *bags, *runs
                # Find split: count IN clauses from sql
                # params = (org, bag1..bagN, run1..runM)
                # Reconstruct from present_pairs ∩ requested
                bags = set()
                runs = set()
                # Heuristic: after org, values that look like bag ids are strings without being int-only
                for p in params[1:]:
                    if isinstance(p, str) and not str(p).isdigit():
                        bags.add(p)
                    else:
                        try:
                            runs.add(int(p))
                        except (TypeError, ValueError):
                            bags.add(str(p))
                # Better: bags are those in present_pairs bag side requested
                # Parse IN list sizes from sql
                import re

                ins = re.findall(r"in\s*\(([^)]+)\)", s)
                if len(ins) >= 2:
                    n_bags = ins[0].count("%s") + ins[0].count("?")
                    bags_list = [str(x) for x in params[1 : 1 + n_bags]]
                    runs_list = [int(x) for x in params[1 + n_bags :]]
                    bags = set(bags_list)
                    runs = set(runs_list)
                self._result = [
                    {"presence_run_id": rid, "bag_id": bid}
                    for bid, rid in self.present_pairs
                    if bid in bags and rid in runs
                ]
            self._mode = "rows"
            return
        self._result = []
        self._mode = "other"

    def fetchall(self):
        return list(self._result)


def _run(
    rid: int,
    *,
    status: str = "success",
    rows_found: int = 10,
    allow_missing: bool | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if allow_missing is not None:
        meta["completeness_guard"] = {"allow_mark_missing": allow_missing}
    return {
        "id": rid,
        "status": status,
        "rows_found": rows_found,
        "started_at": datetime(2026, 9, 10, 1, 0),
        "finished_at": datetime(2026, 9, 10, 1, 1),
        "scrape_meta_json": None if not meta else __import__("json").dumps(meta),
    }


def test_pick_skips_failed_and_present():
    cands = [
        _run(1, status="failed"),
        _run(2, rows_found=0),
        _run(3, allow_missing=False),
        _run(4),  # present
        _run(5),  # first establishing
    ]
    # re-parse path uses scrape_meta_json; inject scrape_meta for allow_missing case
    cands[2]["scrape_meta"] = {"completeness_guard": {"allow_mark_missing": False}}
    picked = _pick_first_establishing_from_candidates(cands, present_run_ids={4})
    assert picked is not None
    assert picked["id"] == 5


def test_bulk_matches_oracle_different_last_present():
    """Bags with different last_present boundaries get identical first-absent."""
    runs = [_run(i) for i in range(10, 60)]
    # BAGA last=10 → window 11..50; present in 11 → first absent 12
    # BAGB last=20 → window 21..60; present in 21,22 → first absent 23
    # BAGC last=10 → present nowhere → first absent 11
    present = {("BAGA", 11), ("BAGB", 21), ("BAGB", 22)}
    last_present = {"BAGA": 10, "BAGB": 20, "BAGC": 10}

    # Oracle per bag
    oracle = {}
    for bid, lp in last_present.items():
        cur = _CountingCursor(runs_after_min=runs, present_pairs=present)
        with patch(
            "backend.rinse_wf_disappeared_from_portal.table_exists",
            return_value=True,
        ):
            oracle[bid] = _first_establishing_absence_run(
                cur, 3, bag_id=bid, last_present_run_id=lp
            )

    bulk_cur = _CountingCursor(runs_after_min=runs, present_pairs=present)
    with patch(
        "backend.rinse_wf_disappeared_from_portal.table_exists",
        return_value=True,
    ):
        bulk = _first_establishing_absence_runs_bulk(
            bulk_cur, 3, last_present, look_ahead=40
        )

    for bid in last_present:
        o = oracle[bid]
        b = bulk.get(bid)
        assert (o is None) == (b is None)
        if o is not None:
            assert o["id"] == b["id"]

    assert oracle["BAGA"]["id"] == 12
    assert oracle["BAGB"]["id"] == 23
    assert oracle["BAGC"]["id"] == 11


def test_bulk_respects_look_ahead_limit_like_oracle():
    """Unsuccessful runs count toward LIMIT 40 — same as oracle."""
    # last_present=1 → window ids 2..41 are 40 failed runs; success at 42 is outside LIMIT.
    runs = [_run(i, status="failed") for i in range(2, 42)]
    runs.append(_run(42, status="success"))
    last_present = {"BAGLIMIT01": 1}
    present: set[tuple[str, int]] = set()

    with patch(
        "backend.rinse_wf_disappeared_from_portal.table_exists",
        return_value=True,
    ):
        oracle = _first_establishing_absence_run(
            _CountingCursor(runs_after_min=runs, present_pairs=present),
            3,
            bag_id="BAGLIMIT01",
            last_present_run_id=1,
            look_ahead=40,
        )
        bulk = _first_establishing_absence_runs_bulk(
            _CountingCursor(runs_after_min=runs, present_pairs=present),
            3,
            last_present,
            look_ahead=40,
        )
    assert oracle is None
    assert "BAGLIMIT01" not in bulk


def test_bulk_query_count_does_not_scale_with_bags():
    runs = [_run(i) for i in range(100, 200)]
    present: set[tuple[str, int]] = set()

    def _measure(n_bags: int) -> int:
        last_present = {f"BAG{i:04d}XX": 100 for i in range(n_bags)}
        cur = _CountingCursor(runs_after_min=runs, present_pairs=present)
        with patch(
            "backend.rinse_wf_disappeared_from_portal.table_exists",
            return_value=True,
        ):
            _first_establishing_absence_runs_bulk(cur, 3, last_present, look_ahead=40)
        return sum(
            1
            for s in cur.sqls
            if "presence_runs" in s or "presence_run_rows" in s
        )

    q1 = _measure(1)
    q10 = _measure(10)
    q25 = _measure(25)
    q50 = _measure(50)
    assert q1 <= 4
    assert q10 == q1
    assert q25 == q1
    assert q50 == q1
    assert q50 < 50


def test_bulk_handles_intermittent_reappearance():
    runs = [_run(i) for i in range(1, 10)]
    # last=2 → window starts at 3; present in 3 and 4 → first absent 5
    present = {("BAGREAPP1", 3), ("BAGREAPP1", 4)}
    last_present = {"BAGREAPP1": 2}
    with patch(
        "backend.rinse_wf_disappeared_from_portal.table_exists",
        return_value=True,
    ):
        oracle = _first_establishing_absence_run(
            _CountingCursor(runs_after_min=runs, present_pairs=present),
            3,
            bag_id="BAGREAPP1",
            last_present_run_id=2,
        )
        bulk = _first_establishing_absence_runs_bulk(
            _CountingCursor(runs_after_min=runs, present_pairs=present),
            3,
            last_present,
        )
    assert oracle["id"] == 5
    assert bulk["BAGREAPP1"]["id"] == 5


def test_bulk_skips_dry_run_via_sql_filter():
    """Dry-run rows are excluded by SQL predicate (not present in runs_after_min fixture)."""
    runs = [_run(5), _run(6)]
    last_present = {"BAGDRYRUN1": 4}
    with patch(
        "backend.rinse_wf_disappeared_from_portal.table_exists",
        return_value=True,
    ):
        bulk = _first_establishing_absence_runs_bulk(
            _CountingCursor(runs_after_min=runs, present_pairs=set()),
            3,
            last_present,
        )
    assert bulk["BAGDRYRUN1"]["id"] == 5


def test_qualify_uses_bulk_not_per_bag_loop():
    from backend.rinse_scrape_completeness import STATE_CONFIRMED
    from backend.rinse_wf_disappeared_from_portal import (
        qualify_disappeared_from_portal_bags,
    )

    oi = {
        "bag_id": "9B5V934T45",
        "order_instance_id": 4942,
        "cycle_anchor_at": datetime(2026, 9, 9, 22, 4),
        "completed_at": None,
        "customer_name": "Shengyu Bai",
    }
    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={
                "9B5V934T45": {
                    "bag_id": "9B5V934T45",
                    "active": 0,
                    "first_seen_at": datetime(2026, 9, 10, 2, 5),
                    "last_seen_at": datetime(2026, 9, 10, 2, 44),
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "9B5V934T45": {
                    "state": STATE_CONFIRMED,
                    "trustworthy_absent_runs": 2,
                    "absent_run_ids": [7203],
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._last_present_run_ids",
            return_value={"9B5V934T45": 7202},
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._first_establishing_absence_runs_bulk",
            return_value={
                "9B5V934T45": {
                    "id": 7203,
                    "scrape_meta": {
                        "source_mode": "ship_to_vendor_window",
                        "tickets_sources": [
                            {
                                "label": "wash_and_fold",
                                "ship_to_vendor_date_start": "2026-09-09",
                                "ship_to_vendor_date_end": "2026-09-10",
                            }
                        ],
                    },
                }
            },
        ) as bulk,
        patch(
            "backend.rinse_wf_disappeared_from_portal._first_establishing_absence_run",
        ) as oracle,
    ):
        out = qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi])
    bulk.assert_called_once()
    oracle.assert_not_called()
    assert out["9B5V934T45"]["first_absent_run_id"] == 7203
