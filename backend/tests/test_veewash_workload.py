"""Step-1 VeeWash daily workload classification tests (At-Vendor, service-specific)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.rinse_veewash_workload import (
    EXC_DISAPPEARED_WITHOUT_COMPLETION,
    build_service_entry_map,
    build_step1_headline_summary,
    build_today_validation,
    classify_veewash_workload,
    merge_completions,
    split_presence_at_vendor_vs_rfv,
)

_FIXTURE_JUL21 = Path(__file__).resolve().parent / "fixtures" / "veewash_step1_jul21_org3.json"


def _parse_fixture_dt(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value
    text = str(value)
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if "T" in text:
        return datetime.fromisoformat(text)
    return date.fromisoformat(text)


def _hydrate_fixture_map(raw, *, date_keys, dt_keys):
    out = {}
    for bag_id, row in (raw or {}).items():
        item = dict(row)
        for key in date_keys:
            if key in item and item[key] is not None:
                parsed = _parse_fixture_dt(item[key])
                item[key] = parsed.date() if isinstance(parsed, datetime) else parsed
        for key in dt_keys:
            if key in item and item[key] is not None:
                item[key] = _parse_fixture_dt(item[key])
        out[bag_id] = item
    return out


def _load_jul21_fixture():
    payload = json.loads(_FIXTURE_JUL21.read_text())
    presence = _hydrate_fixture_map(
        payload["presence_by_bag"],
        date_keys=("estimated_delivery_date",),
        dt_keys=("first_seen_at", "last_seen_at"),
    )
    entry = _hydrate_fixture_map(
        payload["entry_by_bag"],
        date_keys=("entry_date",),
        dt_keys=("first_entry_at",),
    )
    completion = _hydrate_fixture_map(
        payload["completion_by_bag"],
        date_keys=("completion_date",),
        dt_keys=("completion_at",),
    )
    return payload, presence, entry, completion, payload.get("disappearance_state_by_bag") or {}

D0 = date(2026, 7, 20)
D1 = date(2026, 7, 21)


def _pres(active=1, service="WF", rush="RUSH", last_seen=None, portal="at_vendor"):
    ls = None
    if last_seen is not None:
        # Presence timestamps are UTC-naive; store so ET date == last_seen.
        ls = datetime(last_seen.year, last_seen.month, last_seen.day, 16, 0)
    return {
        "active": active,
        "service_type": service,
        "rush_flag": rush,
        "portal_status": portal,
        "last_seen_at": ls,
    }


def _entry(d, hour=6, source="wf_dirty_scan"):
    return {
        "first_entry_at": datetime(d.year, d.month, d.day, hour, 0),
        "entry_date": d,
        "entry_source": source,
    }


def _comp(d, hour=13, by="Jennifer (VeeWash)"):
    return {
        "completion_at": datetime(d.year, d.month, d.day, hour, 0),
        "completion_date": d,
        "completed_by": by,
        "completion_source": "evaluate_bag_completion_v2:clean-rack",
        "completion_kind": "clean-rack",
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
    assert out["pending_end_of_date"] == ["A"]


def test_at_vendor_without_entry_is_not_user_facing_missing_exception():
    out = _run(D0, {"A": _pres(active=1)}, {}, {})
    assert out["missing_entry_scan_exceptions"] == []
    assert "A" in out["not_in_workload"]
    assert out["new_today"] == [] and out["carryover"] == []


def test_unfinished_entered_bag_carries_to_next_day():
    presence, entry = {"A": _pres()}, {"A": _entry(D0)}
    out0 = _run(D0, presence, entry, {})
    out1 = _run(D1, presence, entry, {})
    assert out0["new_today"] == ["A"]
    assert out1["carryover"] == ["A"]
    row = next(r for r in out1["rows"] if r["bag_id"] == "A")
    assert row["original_entry_date"] == D0.isoformat()
    assert row["current_workload_date"] == D1.isoformat()


def test_completed_entered_bag_stops_carrying():
    presence, entry, comp = {"A": _pres()}, {"A": _entry(D0)}, {"A": _comp(D0)}
    out0 = _run(D0, presence, entry, comp)
    out1 = _run(D1, presence, entry, comp)
    assert out0["completed_on_date"] == ["A"]
    assert out1["new_today"] == [] and out1["carryover"] == []
    assert "A" in out1["not_in_workload"]


def test_cross_day_completion_pending_then_completed():
    presence, entry, comp = {"A": _pres()}, {"A": _entry(D0)}, {"A": _comp(D1, hour=9)}
    out0 = _run(D0, presence, entry, comp)
    out1 = _run(D1, presence, entry, comp)
    assert out0["new_today"] == ["A"] and out0["pending_end_of_date"] == ["A"]
    assert out1["carryover"] == ["A"] and out1["completed_on_date"] == ["A"]


def test_disappeared_unfinished_bag_is_review_required():
    out = _run(D0, {"A": _pres(active=0, last_seen=D0)}, {"A": _entry(D0)}, {})
    assert out["disappeared_without_completion_exceptions"] == ["A"]
    assert out["review_required"] == ["A"]
    assert out["pending_end_of_date"] == []
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["exception_reason"] == EXC_DISAPPEARED_WITHOUT_COMPLETION


def test_disappearance_scoped_to_its_day_not_flooding_later_days():
    presence = {"A": _pres(active=0, last_seen=D0)}
    entry = {"A": _entry(D0)}
    out0 = _run(D0, presence, entry, {})
    out1 = _run(D1, presence, entry, {})
    assert out0["disappeared_without_completion_exceptions"] == ["A"]
    assert out1["carryover"] == [] and out1["new_today"] == []
    assert out1["disappeared_prior_open_exceptions"] == ["A"]


def test_unconfirmed_absence_stays_pending_not_disappeared():
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
    out = _run_state(
        D0,
        {"A": _pres(active=0, last_seen=D0)},
        {"A": _entry(D0)},
        {},
        {"A": "PRESENT"},
    )
    assert out["disappeared_without_completion_exceptions"] == []
    assert "A" in out["pending_end_of_date"]


def test_completed_bag_absent_twice_remains_completed():
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
    assert out["missing_entry_scan_exceptions"] == []


def test_scan_only_bag_absent_from_presence_excluded():
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


def test_completed_without_recognized_entry_is_internal_only():
    out = _run(D0, {"A": _pres(active=1)}, {}, {"A": _comp(D0)})
    assert out["completed_on_date"] == []
    assert out["new_today"] == [] and out["carryover"] == []
    assert out["completed_without_recognized_entry"] == ["A"]
    assert out["review_required"] == []
    assert out["missing_entry_scan_exceptions"] == []
    row = next(r for r in out["rows"] if r["bag_id"] == "A")
    assert row["entry_scan_missing"] is True
    assert row["outcome"] == "completed"


def test_completion_wins_over_disappearance():
    out = _run(D0, {"A": _pres(active=0, last_seen=D0)}, {"A": _entry(D0)}, {"A": _comp(D0)})
    assert out["completed_on_date"] == ["A"]
    assert out["disappeared_without_completion_exceptions"] == []


def test_merge_prefers_clean_scan_over_rejected_registry():
    clean = {
        "A": {
            "completion_at": datetime(2026, 7, 20, 18, 50),
            "completion_date": D0,
            "completed_by": "Singh",
            "completion_source": "clean_rack_scan",
        }
    }
    merged = merge_completions({}, clean)
    assert merged["A"]["completion_date"] == D0
    assert merged["A"]["completion_source"] == "clean_rack_scan"


def test_merge_clean_scan_takes_precedence_when_both_present():
    reg = {
        "A": {
            "completion_at": datetime(2026, 7, 21, 1, 0),
            "completion_date": D1,
            "completed_by": None,
            "completion_source": "registry_completed_at",
        }
    }
    clean = {
        "A": {
            "completion_at": datetime(2026, 7, 20, 18, 50),
            "completion_date": D0,
            "completed_by": "Singh",
            "completion_source": "clean_rack_scan",
        }
    }
    merged = merge_completions(reg, clean)
    assert merged["A"]["completion_date"] == D0
    assert merged["A"]["completed_by"] == "Singh"


def test_merge_registry_fallback_when_no_clean_scan():
    reg = {
        "A": {
            "completion_at": datetime(2026, 7, 20, 10, 0),
            "completion_date": D0,
            "completed_by": None,
            "completion_source": "registry_completed_at",
        }
    }
    merged = merge_completions(reg, {})
    assert merged["A"]["completion_source"] == "registry_completed_at"


def test_rfv_split_excludes_ready_for_vendor():
    presence = {
        "AV": _pres(portal="at_vendor"),
        "RFV": _pres(portal="ready_for_vendor", service="HD"),
    }
    at_vendor, rfv = split_presence_at_vendor_vs_rfv(presence)
    assert set(at_vendor) == {"AV"}
    assert rfv == ["RFV"]


def test_service_entry_map_dirty_for_wf_and_hd():
    presence = {
        "WF1": _pres(service="WF"),
        "HD1": _pres(service="HD"),
        "HD_NO_DIRTY": _pres(service="HD"),
        "WF_NO_DIRTY": _pres(service="WF"),
    }
    dirty = {
        "WF1": _entry(D0),
        "HD1": _entry(D0),
    }
    # WIA alone must not enter either service.
    wia = {
        "HD_NO_DIRTY": _entry(D0, source="hd_workitems_added"),
        "WF_NO_DIRTY": _entry(D0, source="hd_workitems_added"),
    }
    entry = build_service_entry_map(presence, dirty_by_bag=dirty, wia_by_bag=wia)
    assert set(entry) == {"WF1", "HD1"}
    assert entry["WF1"]["entry_source"] == "facility_dirty_scan"
    assert entry["HD1"]["entry_source"] == "facility_dirty_scan"
    assert entry["HD1"]["service_type"] == "HD"
    assert "HD_NO_DIRTY" not in entry
    assert "WF_NO_DIRTY" not in entry


def test_hd_enters_via_dirty_not_wia():
    presence = {"H": _pres(service="HD", rush="RUSH")}
    out = _run(D0, presence, {"H": {**_entry(D0), "entry_source": "facility_dirty_scan", "service_type": "HD"}}, {})
    assert out["new_today"] == ["H"]


def test_hd_rush_without_dirty_does_not_enter():
    # Presence is HD Rush without Dirty — must not enter (WIA is not entry).
    presence = {"H": _pres(service="HD", rush="RUSH")}
    out = _run(D0, presence, {}, {})
    assert out["new_today"] == []
    assert "H" in out["not_in_workload"]


def test_today_validation_entry_backed_partition():
    presence = {
        "NEWDONE": _pres(),
        "CARRYPEND": _pres(),
        "GONE": _pres(active=0, last_seen=D0),
        "NOENTRY": _pres(active=1),
        "DONE_NOENTRY": _pres(active=1),
        "OLDGONE": _pres(active=0, last_seen=date(2026, 7, 18)),
    }
    entry = {
        "NEWDONE": _entry(D0),
        "CARRYPEND": _entry(date(2026, 7, 19)),
        "GONE": _entry(D0),
        "OLDGONE": _entry(date(2026, 7, 18)),
    }
    comp = {"NEWDONE": _comp(D0), "DONE_NOENTRY": _comp(D0)}
    res = _run(D0, presence, entry, comp)
    res["eligible_presence_orders"] = len(presence)
    res["active_presence_orders"] = sum(1 for p in presence.values() if p["active"] == 1)
    res["excluded_not_presence_backed"] = []
    res["rfv_excluded"] = []
    val = build_today_validation(res, selected_date_et=D0)
    inv = val["invariants"]
    assert inv["every_order_exactly_one_operational_path"]
    assert inv["active_workload_equals_new_plus_carryover"]
    assert inv["established_outcomes_partition"]
    assert inv["total_operational_reconciles"]
    ops = val["operational_paths"]
    assert ops["completed_entered"] == 1
    assert ops["completed_without_recognized_entry"] == 1
    assert ops["pending"] == 1
    assert ops["review_required"] == 1
    assert val["missing_entry_scan_exception"] == 0
    assert val["established_workload"] == 3


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
        "CARRY_PEND": _entry(D0 - timedelta(days=1)),
        "NEW_DONE": _entry(D0),
        "GONE": _entry(D0),
    }
    comp = {"NEW_DONE": _comp(D0)}
    out = _run(D0, presence, entry, comp)
    rec = out["reconciliation"]
    assert rec["total_active_workload_equals_new_plus_carryover"]
    assert rec["members_partitioned"]
    assert rec["pending_reconciles"]
    buckets = (
        out["completed_on_date"]
        + out["pending_end_of_date"]
        + out["disappeared_without_completion_exceptions"]
    )
    assert len(buckets) == len(set(buckets))


def test_headline_summary_simplified_exceptions_and_service_segments():
    yesterday = D0 - timedelta(days=1)
    presence = {
        "R_NEW_DONE": _pres(rush="RUSH"),
        "R_CARRY_PEND": _pres(rush="RUSH"),
        "N_NEW_PEND": _pres(rush="NON_RUSH"),
        "N_NOENTRY": _pres(rush="NON_RUSH"),
        "R_GONE": _pres(rush="RUSH", active=0, last_seen=D0),
        "HD_NEW": _pres(service="HD", rush="RUSH"),
    }
    entry = {
        "R_NEW_DONE": _entry(D0),
        "R_CARRY_PEND": _entry(yesterday),
        "N_NEW_PEND": _entry(D0),
        "R_GONE": _entry(D0),
        "HD_NEW": _entry(D0, source="facility_dirty_scan"),
    }
    # Tag HD row service via presence; entry map already built.
    for bid, e in entry.items():
        e["service_type"] = presence[bid]["service_type"]
    comp = {"R_NEW_DONE": _comp(D0)}
    out = _run(D0, presence, entry, comp)
    summ = build_step1_headline_summary(out, selected_date_et=D0, activation_date=D0)

    a = summ["segments"]["all"]
    assert a["active_workload"] == a["completed"] + a["pending"] + a["exceptions"]["review_required"]
    assert a["exceptions"]["missing_workload_entry_scan"] == 0
    assert a["exceptions"]["completed_awaiting_workload_assignment"] == 0
    assert summ["historical_unresolved_backlog"] == 0
    assert summ["segments"]["wf"]["new_today"] + summ["segments"]["hd"]["new_today"] == a["new_today"]
    assert "HD_NEW" in summ["segments"]["hd"]["bag_ids"]["new_today"]
    assert "HD_NEW" not in summ["segments"]["wf"]["bag_ids"]["new_today"]


def test_headline_future_edd_is_non_rush_even_when_stored_flag_is_rush():
    """Portal / At Vendor: EDD after selected ET date is Non-Rush (not stored RUSH cell)."""
    presence = {
        "FUTURE_NR": {
            **_pres(rush="RUSH"),
            "estimated_delivery_date": D0 + timedelta(days=1),
            "raw_row_json": {
                "estimated_delivery_text": "Thu 08/20/2026 RUSH",
                "Date_Clean": (D0 + timedelta(days=1)).isoformat(),
            },
        },
        "TODAY_RUSH": {
            **_pres(rush="RUSH"),
            "estimated_delivery_date": D0,
            "raw_row_json": {"estimated_delivery_text": "Wed 08/19/2026 TODAY"},
        },
    }
    entry = {
        "FUTURE_NR": _entry(D0),
        "TODAY_RUSH": _entry(D0),
    }
    out = _run(D0, presence, entry, {})
    summ = build_step1_headline_summary(out, selected_date_et=D0, activation_date=D0)
    assert "FUTURE_NR" in summ["segments"]["wf_non_rush"]["bag_ids"]["new_today"]
    assert "FUTURE_NR" not in summ["segments"]["wf_rush"]["bag_ids"]["new_today"]
    assert "TODAY_RUSH" in summ["segments"]["wf_rush"]["bag_ids"]["new_today"]
    assert summ["segments"]["wf_rush"]["total_workload"] == 1
    assert summ["segments"]["wf_non_rush"]["total_workload"] == 1


def test_jul21_fixture_locks_validated_dirty_entry_completion_model():
    """Offline lock of Dirty-only WF/HD entry + v2 completion for 2026-07-21 org-3."""
    payload, presence, entry, completion, state = _load_jul21_fixture()
    selected = date.fromisoformat(payload["selected_date_et"])
    assert selected == D1
    assert payload.get("entry_model") == "dirty_scan_wf_and_hd"
    assert payload.get("rfv_inactive") is True

    out = classify_veewash_workload(
        selected_date_et=selected,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag=state,
    )
    out["rfv_excluded"] = list(payload.get("rfv_excluded_expected") or [])
    expected = payload["expected_counts"]

    wf_new = [
        bid
        for bid in out["new_today"]
        if str((presence.get(bid) or {}).get("service_type") or "").upper() == "WF"
    ]
    hd_new = [
        bid
        for bid in out["new_today"]
        if str((presence.get(bid) or {}).get("service_type") or "").upper() == "HD"
    ]
    hd_carry = [
        bid
        for bid in out["carryover"]
        if str((presence.get(bid) or {}).get("service_type") or "").upper() == "HD"
    ]

    assert len(wf_new) == expected["wf_new"] == 73
    assert len(hd_new) == expected["hd_new"] == 12
    assert len(out["new_today"]) == expected["new_today"] == 85
    assert len(out["carryover"]) == expected["carryover"] == 4
    assert len(out["new_today"]) + len(out["carryover"]) == expected["active_workload"] == 89
    assert len(out["completed_on_date"]) == expected["completed"] == 72
    assert len(out["pending_end_of_date"]) == expected["pending"] == 9
    assert len(out["review_required"]) == expected["review_required"] == 8
    assert (
        len(out["completed_without_recognized_entry"])
        == expected["completed_without_recognized_entry"]
        == 1
    )
    assert out["missing_entry_scan_exceptions"] == []
    assert len(out["rfv_excluded"]) == expected["rfv_excluded"] == 0
    assert (
        len(out["completed_on_date"])
        + len(out["pending_end_of_date"])
        + len(out["review_required"])
        == 89
    )

    assert sorted(wf_new) == sorted(payload["wf_new_today"])
    assert sorted(hd_new) == sorted(payload["hd_new_today"])
    # Dirty today → HD New (not carryover). WIA is not the entry rule.
    assert "83VXJSQOUU" in hd_new
    assert "83VXJSQOUU" not in hd_carry
    for bid in ("0IWQ19G4ZV", "2KFDJYPGYC", "AIDMO1L7ZX", "EVL3TQOBNA"):
        assert bid in hd_new
        assert str((presence.get(bid) or {}).get("service_type") or "").upper() == "HD"

    f0 = next(r for r in out["rows"] if r["bag_id"] == "F0P0ZPLTWU")
    assert "F0P0ZPLTWU" in out["completed_on_date"]
    assert f0["completion_kind"] == "second-weight-entry"
    assert "C4QINNDXYU" in out["completed_on_date"]
    assert "EPRM6DYJ3H" in out["completed_on_date"]

    assert out["completed_without_recognized_entry"] == ["62MRUIXOGF"]
    assert "62MRUIXOGF" not in out["new_today"]
    assert "62MRUIXOGF" not in out["review_required"]

    # BBPKT completed on Jul 20 via second-weight; never Review Required on Jul 21.
    out_jul20 = classify_veewash_workload(
        selected_date_et=D0,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag=state,
    )
    bb = next(r for r in out_jul20["rows"] if r["bag_id"] == "BBPKT10ZVL")
    assert "BBPKT10ZVL" in out_jul20["completed_on_date"]
    assert bb["completion_kind"] == "second-weight-entry"
    assert "BBPKT10ZVL" not in out["review_required"]
    assert "BBPKT10ZVL" not in out["new_today"]

    # RFV inactive: no RFV bags in operational buckets; fixture lists none excluded.
    assert payload["rfv_excluded_expected"] == []
    assert out["rfv_excluded"] == []

    summ = build_step1_headline_summary(out, selected_date_et=selected, activation_date=selected)
    assert summ["wf_new_today"] == 73
    assert summ["hd_new_today"] == 12
    assert summ["new_today"] == 85
    assert summ["carryover"] == 4
    assert summ["active_workload"] == 89
    assert summ["completed"] == 72
    assert summ["pending"] == 9
    assert summ["exceptions"]["review_required"] == 8
    assert summ["exceptions"]["missing_workload_entry_scan"] == 0
    assert summ["exceptions"]["completed_awaiting_workload_assignment"] == 0
    assert summ["historical_unresolved_backlog"] == 0
    assert summ["historical_unresolved_backlog_bag_ids"] == []
    assert summ["rfv_excluded"] == 0
    assert summ["completed_without_recognized_entry"] == 1
    assert summ["completed_without_recognized_entry_bag_ids"] == ["62MRUIXOGF"]


def test_step1_headline_contract_hides_retired_exception_categories():
    """API summary keeps retired categories at zero / empty — not manager-facing."""
    presence = {
        "NEW": _pres(),
        "CWO": _pres(),
        "RFV": _pres(portal="ready_for_vendor"),
    }
    at_vendor, rfv = split_presence_at_vendor_vs_rfv(presence)
    entry = {"NEW": _entry(D0)}
    entry["NEW"]["service_type"] = "WF"
    out = _run(D0, at_vendor, entry, {"CWO": _comp(D0)})
    out["rfv_excluded"] = []  # RFV inactive — not loaded into Step-1
    summ = build_step1_headline_summary(out, selected_date_et=D0, activation_date=D0)

    exc = summ["exceptions"]
    assert set(exc) >= {
        "review_required",
        "missing_workload_entry_scan",
        "completed_awaiting_workload_assignment",
    }
    assert exc["missing_workload_entry_scan"] == 0
    assert exc["completed_awaiting_workload_assignment"] == 0
    assert summ["historical_unresolved_backlog"] == 0
    assert summ["historical_unresolved_backlog_bag_ids"] == []
    assert "CWO" in summ["completed_without_recognized_entry_bag_ids"]
    assert "CWO" not in summ["segments"]["all"]["bag_ids"]["review_required"]
    assert "RFV" not in summ["segments"]["all"]["bag_ids"]["new_today"]
    assert summ["rfv_excluded"] == 0


def test_step1_lightweight_read_path_exposes_simplified_exception_contract():
    """Lightweight Shift Monitor payload must not surface retired exception cards or RFV."""
    from datetime import datetime as dt
    from unittest.mock import MagicMock, patch

    from backend.rinse_simple_shift_performance import _try_build_step1_lightweight_summary

    payload, presence, entry, completion, state = _load_jul21_fixture()
    selected = date.fromisoformat(payload["selected_date_et"])
    classified = classify_veewash_workload(
        selected_date_et=selected,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag=state,
    )
    classified["rfv_excluded"] = []
    classified["organization_id"] = 3
    classified["selected_date_et"] = selected.isoformat()
    classified["entry_racks"] = ["VeeWash Dirty"]
    classified["eligible_presence_orders"] = len(presence)
    classified["active_presence_orders"] = sum(
        1 for row in presence.values() if int(row.get("active") or 0) == 1
    )
    classified["excluded_not_presence_backed"] = []

    cursor = MagicMock()
    baseline = {
        "baseline_source": "latest_clean_veewash_scrape",
        "baseline_time_et": "2026-07-21 06:00 ET",
        "at_vendor_scrape_ready": True,
        "needs_refresh_reason": None,
    }

    with (
        patch(
            "backend.rinse_veewash_workload.is_step1_enabled",
            return_value=True,
        ),
        patch(
            "backend.rinse_veewash_workload.get_step1_activation_date",
            return_value=selected,
        ),
        patch(
            "backend.rinse_veewash_workload.build_veewash_daily_workload",
            return_value=classified,
        ),
        patch(
            "backend.rinse_simple_shift_performance._attach_section_sync_statuses",
            return_value={
                "at_vendor": {"enabled": True},
                "ready_for_vendor": {"enabled": False, "status": "disabled"},
                "ready_for_vendor_enabled": False,
                "sync_cycle": {},
            },
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.format_baseline_banner_et",
            return_value="Baseline",
        ),
    ):
        body = _try_build_step1_lightweight_summary(
            cursor,
            3,
            period_start=selected,
            period_end=selected,
            baseline_ctx=baseline,
            baseline_ms=1.0,
            eval_at=dt(2026, 7, 21, 20, 0),
            t0=0.0,
        )

    assert body is not None
    assert body["veewash_step1_active"] is True
    assert body["performance_meta"]["step1_lightweight"] is True
    assert body["rinse_sync"]["ready_for_vendor_enabled"] is False
    assert body["ready_for_vendor"].get("inactive") is True
    summary = body["at_vendor_module"]["veewash_step1_summary"]
    assert summary["wf_new_today"] == 73
    assert summary["hd_new_today"] == 12
    assert summary["new_today"] == 85
    assert summary["active_workload"] == 89
    assert summary["exceptions"]["review_required"] == 8
    assert summary["exceptions"]["missing_workload_entry_scan"] == 0
    assert summary["exceptions"]["completed_awaiting_workload_assignment"] == 0
    assert summary["historical_unresolved_backlog"] == 0
    assert summary["historical_unresolved_backlog_bag_ids"] == []
    assert summary["completed_without_recognized_entry"] == 1
    assert summary["rfv_excluded"] == 0
