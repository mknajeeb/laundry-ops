"""Checkpoint 2B — Opening Carryover membership (unit tests, no DB)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_day_membership import (
    INCLUSION_ADDED_LATER,
    INCLUSION_OPENING_CARRYOVER,
    INCLUSION_OPENING_NEW,
    build_append_only_membership,
    classify_opening_scrape_membership,
    membership_bag_ids,
)

DAY = date(2026, 8, 6)
_BASELINE_MOD = "backend.rinse_shift_monitor_baseline"
_TA = "backend.ta_helpers"
_MEM = "backend.rinse_veewash_day_membership"
_ELIG = "backend.rinse_workload_membership_eligibility"


def _dirty_pass_through(*args, **kwargs):
    """Unit tests supply scrape rows without Dirty scans — treat as eligible."""
    candidates = args[3] if len(args) > 3 else kwargs.get("candidate_bag_ids") or []
    ids = sorted({str(b).strip().upper() for b in candidates if str(b).strip()})
    return {
        "eligible": ids,
        "excluded_no_dirty": [],
        "excluded_completed_before": [],
        "excluded_prior_disappearance": [],
        "dirty_entry_by_bag": {},
    }


def _elig_patches(**extra):
    """Dirty gate + durable unfinished seed patches for scrape membership tests."""
    prior = extra.pop("prior_unfinished", None)
    patches = [
        patch(f"{_ELIG}.filter_operationally_eligible_ids", side_effect=_dirty_pass_through),
    ]
    if prior is not None:
        patches.append(
            patch(f"{_ELIG}.load_prior_day_unfinished_member_ids", return_value=set(prior))
        )
    for k, v in extra.items():
        patches.append(patch(k, v))
    return patches


def _run(run_id: int, *, finished: datetime, rows_found: int = 10) -> dict:
    return {
        "id": run_id,
        "status": "success",
        "rows_found": rows_found,
        "dry_run": 0,
        "finished_at": finished,
        "portal_status": "at_vendor",
        "organization_id": 3,
    }


def _cursor_with_run_rows(run_bags: dict[int, list[tuple[str, str, str]]]) -> MagicMock:
    """run_bags: run_id -> list of (bag_id, service_type, rush_flag)."""
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
            return {"c": len(run_bags.get(rid) or [])}
        return {"c": 0}

    def fetchall():
        if state["mode"] == "bags":
            rid = state["run_id"]
            return [
                {
                    "bag_id": b,
                    "customer_name": None,
                    "estimated_delivery_date": None,
                    "rush_flag": rush,
                    "service_type": svc,
                    "portal_status": "at_vendor",
                    "raw_row_json": None,
                    "source_batch_id": None,
                }
                for b, svc, rush in (run_bags.get(rid) or [])
            ]
        return []

    cursor.execute.side_effect = execute
    cursor.fetchone.side_effect = fetchone
    cursor.fetchall.side_effect = fetchall
    return cursor


def test_prior_day_active_wf_becomes_opening_carryover():
    membership = {
        "WFOLD1": {
            "bag_id": "WFOLD1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
            "rush_flag": "RUSH",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"WFOLD1"}),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
    ):
        kept, excluded, meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    assert excluded == []
    assert kept["WFOLD1"]["inclusion_source"] == INCLUSION_OPENING_CARRYOVER
    assert meta["opening_carryover_bag_ids"] == ["WFOLD1"]
    assert meta["opening_new_bag_ids"] == []


def test_prior_day_active_hd_becomes_opening_carryover():
    membership = {
        "HDOLD1": {
            "bag_id": "HDOLD1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "HD",
            "rush_flag": "NON-RUSH",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"HDOLD1"}),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
    ):
        kept, excluded, meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    assert excluded == []
    assert kept["HDOLD1"]["inclusion_source"] == INCLUSION_OPENING_CARRYOVER
    assert meta["opening_carryover_bag_ids"] == ["HDOLD1"]


def test_no_same_day_dirty_scan_required_for_carryover():
    membership = {
        "NODIRTY1": {
            "bag_id": "NODIRTY1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"NODIRTY1"}),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
        patch(f"{_MEM}._bags_with_same_day_entry_evidence") as dirty,
    ):
        kept, excluded, _meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    dirty.assert_not_called()
    assert "NODIRTY1" in kept
    assert excluded == []


def test_completed_before_opening_excluded():
    membership = {
        "DONE1": {
            "bag_id": "DONE1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
        "KEEP1": {
            "bag_id": "KEEP1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"DONE1", "KEEP1"}),
        patch(
            f"{_MEM}._bags_canonically_completed_before_opening",
            return_value={"DONE1"},
        ),
    ):
        kept, excluded, meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    assert excluded == ["DONE1"]
    assert "DONE1" not in kept
    assert kept["KEEP1"]["inclusion_source"] == INCLUSION_OPENING_CARRYOVER
    assert meta["excluded_completed_before_opening_bag_ids"] == ["DONE1"]


def test_manager_completed_before_opening_excluded():
    # Covered by completed helper returning the manager-completed id.
    membership = {
        "MGR1": {
            "bag_id": "MGR1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"MGR1"}),
        patch(
            f"{_MEM}._bags_canonically_completed_before_opening",
            return_value={"MGR1"},
        ),
    ):
        kept, excluded, _meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    assert excluded == ["MGR1"]
    assert kept == {}


def test_clean_only_and_pbv_only_not_excluded():
    """Clean / PBV alone are not completion evidence — bags stay if not completed."""
    membership = {
        "CLEAN1": {
            "bag_id": "CLEAN1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
        "PBV1": {
            "bag_id": "PBV1",
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
        },
    }
    with (
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"CLEAN1", "PBV1"}),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
    ):
        kept, excluded, meta = classify_opening_scrape_membership(
            MagicMock(), 3, DAY, membership
        )
    assert excluded == []
    assert set(meta["opening_carryover_bag_ids"]) == {"CLEAN1", "PBV1"}
    assert "CLEAN1" in kept and "PBV1" in kept


def test_opening_carryover_keeps_portal_rush_non_rush():
    scrapes = [
        _run(3968, finished=datetime(2026, 8, 6, 0, 10), rows_found=3),
        _run(3969, finished=datetime(2026, 8, 6, 10, 0), rows_found=1),
    ]
    run_bags = {
        3968: [
            ("CARRYRUSH", "WF", "RUSH"),
            ("CARRYNON", "WF", "NON-RUSH"),
            ("OPENNEW1", "WF", "RUSH"),
        ],
        3969: [("ADDED1", "WF", "NON-RUSH")],
    }
    cursor = _cursor_with_run_rows(run_bags)
    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"CARRYRUSH", "CARRYNON"}),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
        patch(f"{_ELIG}.filter_operationally_eligible_ids", side_effect=_dirty_pass_through),
        patch(
            f"{_ELIG}.load_prior_day_unfinished_member_ids",
            return_value={"CARRYRUSH", "CARRYNON"},
        ),
    ):
        mem = build_append_only_membership(cursor, 3, DAY)

    assert mem["opening_carryover_count"] == 2
    assert mem["opening_carryover_rush_count"] == 1
    assert mem["opening_carryover_non_rush_count"] == 1
    assert mem["opening_carryover_rush_bag_ids"] == ["CARRYRUSH"]
    assert mem["opening_carryover_non_rush_bag_ids"] == ["CARRYNON"]
    assert mem["membership"]["CARRYRUSH"]["rush_flag"] == "RUSH"
    assert mem["membership"]["CARRYNON"]["rush_flag"] == "NON-RUSH"


def test_opening_carryover_not_labeled_new_today_and_buckets_separate():
    scrapes = [
        _run(1, finished=datetime(2026, 8, 6, 0, 5), rows_found=3),
        _run(2, finished=datetime(2026, 8, 6, 12, 0), rows_found=2),
    ]
    run_bags = {
        1: [
            ("CARRY1", "WF", "RUSH"),
            ("NEW1", "HD", "NON-RUSH"),
            ("DONE1", "WF", "RUSH"),
        ],
        2: [("ADDED1", "WF", "RUSH"), ("CARRY1", "WF", "RUSH")],
    }
    cursor = _cursor_with_run_rows(run_bags)
    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value={"CARRY1", "DONE1"}),
        patch(
            f"{_MEM}._bags_canonically_completed_before_opening",
            return_value={"DONE1"},
        ),
        patch(f"{_ELIG}.filter_operationally_eligible_ids", side_effect=_dirty_pass_through),
        patch(
            f"{_ELIG}.load_prior_day_unfinished_member_ids",
            return_value={"CARRY1"},
        ),
    ):
        mem = build_append_only_membership(cursor, 3, DAY)

    assert mem["opening_carryover_bag_ids"] == ["CARRY1"]
    assert mem["opening_new_bag_ids"] == ["NEW1"]
    assert mem["added_later_bag_ids"] == ["ADDED1"]
    assert mem["excluded_completed_before_opening_bag_ids"] == ["DONE1"]
    assert mem["membership"]["CARRY1"]["inclusion_source"] == INCLUSION_OPENING_CARRYOVER
    assert mem["membership"]["NEW1"]["inclusion_source"] == INCLUSION_OPENING_NEW
    assert mem["membership"]["ADDED1"]["inclusion_source"] == INCLUSION_ADDED_LATER
    assert mem["fresh_start_no_prior_day_carryover"] is False
    assert "Fresh start" not in (mem.get("membership_copy") or "")
    assert mem["total_count"] == 3
    assert mem["opening_carryover_count"] + mem["opening_new_count"] + mem[
        "added_later_count"
    ] == mem["total_count"]

    ids = membership_bag_ids(mem)
    assert len(ids) == len(set(ids))
    assert "DONE1" not in ids
    assert set(ids) == {"ADDED1", "CARRY1", "NEW1"}

    svc = mem["service_membership"]
    assert svc["WF"]["opening_carryover"] == ["CARRY1"]
    assert svc["HD"]["opening_new"] == ["NEW1"]
    assert svc["WF"]["added_during_day"] == ["ADDED1"]
    assert svc["WF"]["total"] + svc["HD"]["total"] == mem["total_count"]


def test_append_only_retained_is_subset_not_additive():
    """Bags that leave later scrapes stay in membership; retained ⊆ total."""
    scrapes = [
        _run(1, finished=datetime(2026, 8, 6, 0, 5), rows_found=2),
        _run(2, finished=datetime(2026, 8, 6, 14, 0), rows_found=1),
    ]
    run_bags = {
        1: [("KEEP1", "WF", "RUSH"), ("LEFT1", "WF", "NON-RUSH")],
        2: [("KEEP1", "WF", "RUSH")],  # LEFT1 disappeared — still retained
    }
    cursor = _cursor_with_run_rows(run_bags)
    with (
        patch(f"{_BASELINE_MOD}.list_clean_at_vendor_presence_scrapes", return_value=scrapes),
        patch(
            f"{_BASELINE_MOD}._presence_run_finished_naive_et",
            side_effect=lambda r: r.get("finished_at") if r else None,
        ),
        patch(f"{_TA}.table_exists", return_value=True),
        patch(f"{_MEM}._load_prior_day_membership_ids", return_value=set()),
        patch(f"{_MEM}._bags_canonically_completed_before_opening", return_value=set()),
        patch(f"{_ELIG}.filter_operationally_eligible_ids", side_effect=_dirty_pass_through),
        patch(f"{_ELIG}.load_prior_day_unfinished_member_ids", return_value=set()),
    ):
        mem = build_append_only_membership(cursor, 3, DAY)

    total = set(membership_bag_ids(mem))
    assert "LEFT1" in total
    # Retained status is subset: opening+added already equals total (not +retained).
    additive = (
        set(mem["opening_carryover_bag_ids"])
        | set(mem["opening_new_bag_ids"])
        | set(mem["added_later_bag_ids"])
    )
    assert additive == total
    assert len(additive) == mem["total_count"]


def test_workload_maps_carryover_not_new_today():
    from backend.rinse_veewash_workload import build_veewash_daily_workload_from_membership

    membership = {
        "ok": True,
        "baseline_presence_run_id": 1,
        "later_scrape_ids": [],
        "opening_carryover_bag_ids": ["CARRY1"],
        "opening_new_bag_ids": ["NEW1"],
        "added_later_bag_ids": ["ADD1"],
        "membership": {
            "CARRY1": {
                "bag_id": "CARRY1",
                "inclusion_source": INCLUSION_OPENING_CARRYOVER,
                "service_type_portal": "WF",
                "rush_flag": "RUSH",
                "customer_name": "A",
            },
            "NEW1": {
                "bag_id": "NEW1",
                "inclusion_source": INCLUSION_OPENING_NEW,
                "service_type_portal": "WF",
                "rush_flag": "NON-RUSH",
                "customer_name": "B",
            },
            "ADD1": {
                "bag_id": "ADD1",
                "inclusion_source": INCLUSION_ADDED_LATER,
                "service_type_portal": "HD",
                "rush_flag": "RUSH",
                "customer_name": "C",
            },
        },
    }

    with (
        patch(
            "backend.rinse_veewash_day_membership.build_append_only_membership",
            return_value=membership,
        ),
        patch(
            "backend.rinse_veewash_workload.load_presence_orders",
            return_value={},
        ),
        patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.load_first_dirty_scans",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.load_first_workitems_added_scans",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_workload.build_disappearance_confirmation",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_review.expand_review_required",
            side_effect=lambda result, **kwargs: result,
        ),
        patch(
            "backend.rinse_veewash_review.load_bag_weight_map",
            return_value={},
        ),
        patch(
            "backend.rinse_veewash_review.load_registry_service_map",
            return_value={},
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_scan_freshness.load_last_scan_at_by_bag", return_value={}),
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={},
        ),
    ):
        result = build_veewash_daily_workload_from_membership(
            MagicMock(), 3, selected_date_et=DAY
        )

    assert result["opening_carryover"] == ["CARRY1"]
    assert result["opening_new"] == ["NEW1"]
    assert result["added_during_day"] == ["ADD1"]
    assert result["carryover"] == ["CARRY1"]
    assert "CARRY1" not in result["new_today"]
    assert set(result["new_today"]) == {"ADD1", "NEW1"}
    by_id = {r["bag_id"]: r for r in result["rows"]}
    assert by_id["CARRY1"]["entry_class"] == "opening_carryover"
    assert by_id["CARRY1"]["new_or_carryover"] == "carryover"
    assert by_id["NEW1"]["entry_class"] == "opening_new"
    assert by_id["ADD1"]["entry_class"] == "added_during_day"
    assert result["counts"]["total_workload"] == 3
    assert (
        result["counts"]["opening_carryover"]
        + result["counts"]["opening_new"]
        + result["counts"]["added_during_day"]
        == 3
    )


def test_hd_strip_preserves_opening_carryover():
    from backend.rinse_hd_day_presentation import strip_hd_carryover_from_summary
    from backend.tests.test_hd_no_carryover_and_specialty_metrics import _seg

    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "all": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
        }
    }
    membership = {"opening_carryover_bag_ids": ["HDCARRY1"]}
    out = strip_hd_carryover_from_summary(summary, membership)
    assert "HDCARRY1" in out["segments"]["hd"]["bag_ids"]["carryover"]
    assert out["hd_policy"]["opening_carryover_enabled"] is True
    assert out["hd_policy"]["carryover_removed_count"] == 0


def test_aug6_membership_contract_locked_counts():
    """Lock the Aug 6 controlled CP2B membership contract (fixture, not live DB)."""
    carry = [f"C{i:02d}" for i in range(41)]
    opening_new = [f"N{i:02d}" for i in range(11)]
    added = [f"A{i:02d}" for i in range(68)]
    rush = carry[:25]
    non_rush = carry[25:]
    assert len(rush) == 25 and len(non_rush) == 16

    wf_carry = carry[:20]
    hd_carry = carry[20:]
    assert len(wf_carry) == 20 and len(hd_carry) == 21
    wf_new = opening_new
    hd_new: list[str] = []
    wf_added = added[:63]
    hd_added = added[63:]
    assert len(wf_added) == 63 and len(hd_added) == 5

    membership_rows = {}
    for bid in wf_carry:
        membership_rows[bid] = {
            "bag_id": bid,
            "inclusion_source": INCLUSION_OPENING_CARRYOVER,
            "service_type_portal": "WF",
            "rush_flag": "RUSH" if bid in rush else "NON-RUSH",
        }
    for bid in hd_carry:
        membership_rows[bid] = {
            "bag_id": bid,
            "inclusion_source": INCLUSION_OPENING_CARRYOVER,
            "service_type_portal": "HD",
            "rush_flag": "RUSH" if bid in rush else "NON-RUSH",
        }
    for bid in wf_new:
        membership_rows[bid] = {
            "bag_id": bid,
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
            "rush_flag": "RUSH",
        }
    for bid in wf_added:
        membership_rows[bid] = {
            "bag_id": bid,
            "inclusion_source": INCLUSION_ADDED_LATER,
            "service_type_portal": "WF",
            "rush_flag": "RUSH",
        }
    for bid in hd_added:
        membership_rows[bid] = {
            "bag_id": bid,
            "inclusion_source": INCLUSION_ADDED_LATER,
            "service_type_portal": "HD",
            "rush_flag": "NON-RUSH",
        }

    from backend.rinse_veewash_day_membership import _service_membership_breakdown

    svc = _service_membership_breakdown(membership_rows)
    total_ids = set(membership_rows)
    retained_subset = {"N00"}  # example retained id already in Opening New
    assert len(total_ids) == 120
    assert len(carry) == 41
    assert len(rush) == 25
    assert len(non_rush) == 16
    assert len(opening_new) == 11
    assert len(added) == 68
    assert len(carry) + len(opening_new) + len(added) == 120
    assert retained_subset <= total_ids
    assert len(total_ids | retained_subset) == 120  # retained not additive
    assert svc["WF"]["opening_carryover_count"] == 20
    assert svc["WF"]["opening_new_count"] == 11
    assert svc["WF"]["added_during_day_count"] == 63
    assert svc["WF"]["total"] == 94
    assert svc["HD"]["opening_carryover_count"] == 21
    assert svc["HD"]["opening_new_count"] == 0
    assert svc["HD"]["added_during_day_count"] == 5
    assert svc["HD"]["total"] == 26
    assert svc["WF"]["total"] + svc["HD"]["total"] == 120
    assert len(set(svc["WF"]["opening_carryover"] + svc["HD"]["opening_carryover"])) == 41
    excluded_completed = 9
    opening_portal = 61
    assert opening_portal == 41 + 11 + excluded_completed
