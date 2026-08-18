"""Canonical WF Split evaluator — owner matrix + supply + manager persistence."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.rinse_wf_canonical_split import (
    MANAGER_DECISION_NOT_SPLIT,
    MANAGER_DECISION_SPLIT,
    REASON_MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER,
    REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE,
    REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND,
    STATE_CONFIRMED_NOT_SPLIT,
    STATE_CONFIRMED_SPLIT,
    STATE_MANAGER_NOT_SPLIT,
    STATE_MANAGER_SPLIT,
    STATE_PENDING,
    STATE_REVIEW_REQUIRED,
    evaluate_bag_split,
    evaluate_bags_split,
    pack_canonical_split_orders,
    save_manager_split_decision,
    supply_day_finalizable,
)


def _ev(
    purpose: str,
    ts: datetime,
    *,
    eid: int,
    bag: str = "BAGSPLIT01",
    rack: str | None = None,
    user: str = "Alex",
) -> dict:
    return {
        "id": eid,
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "scan_index": eid,
        "rack": rack,
        "user_name": user,
    }


STV = datetime(2026, 8, 17, 6, 0, 0)
W1 = datetime(2026, 8, 17, 8, 0, 0)
W2 = datetime(2026, 8, 17, 8, 15, 0)
MARKER = datetime(2026, 8, 17, 7, 50, 0)
DRY = datetime(2026, 8, 17, 9, 0, 0)
CC = datetime(2026, 8, 17, 9, 30, 0)


def _base_cycle(*, bag: str = "BAGSPLIT01") -> list[dict]:
    return [_ev("sent-to-vendor", STV, eid=1, bag=bag, rack="VeeWash Dirty")]


# ---------------------------------------------------------------------------
# Owner matrix (closed / disappearance)
# ---------------------------------------------------------------------------


def test_01_marker_yes_loads_ge2_confirmed_split():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="W62-30-VW"),
        _ev("drying", DRY, eid=5, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_CONFIRMED_SPLIT
    assert out["canonical_split"] is True
    assert out["review_required"] is False
    assert out["processing_units"] == 2
    assert out["split_marker_present"] is True
    assert out["washer_load_count"] == 2


def test_02_marker_no_loads_lt2_confirmed_not_split():
    events = _base_cycle() + [
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),
        _ev("drying", DRY, eid=3, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_CONFIRMED_NOT_SPLIT
    assert out["canonical_split"] is False
    assert out["processing_units"] == 1


def test_03_marker_yes_loads_lt2_review_second_washer():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("drying", DRY, eid=4, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_REVIEW_REQUIRED
    assert out["canonical_split"] is None
    assert out["review_reason"] == REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND


def test_04_marker_no_loads_ge2_review_multiple_washers():
    events = _base_cycle() + [
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=3, rack="W62-30-VW"),
        _ev("drying", DRY, eid=4, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_REVIEW_REQUIRED
    assert out["canonical_split"] is None
    assert out["review_reason"] == REASON_MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER


def test_05_open_wash_marker_yes_one_washer_pending():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_PENDING
    assert out["canonical_split"] is None
    assert out["pending"] is True


def test_06_open_wash_no_marker_one_washer_pending():
    events = _base_cycle() + [
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_PENDING


def test_07_open_wash_two_washers_still_pending_until_close():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="W62-30-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_PENDING


def test_08_close_via_complete_cleaning_when_no_drying():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="W62-30-VW"),
        _ev("complete-cleaning", CC, eid=5),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["washing_closed"] is True
    assert out["close_event_purpose"] == "complete-cleaning"
    assert out["state"] == STATE_CONFIRMED_SPLIT


def test_09_drying_preferred_over_later_complete_cleaning():
    events = _base_cycle() + [
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),
        _ev("drying", DRY, eid=3, rack="D10-50-VW"),
        _ev("complete-cleaning", CC, eid=4),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["close_event_purpose"] == "drying"


def test_10_inferred_non_w_start_cleaning_not_counted():
    """Chronology may show inferred racks; canonical physical count requires W*."""
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="VeeWash Clean"),  # not W*
        _ev("drying", DRY, eid=5, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["washer_load_count"] == 1
    assert out["state"] == STATE_REVIEW_REQUIRED
    assert out["review_reason"] == REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND


def test_11_disappearance_same_matrix_confirmed_split():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="W62-30-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01", disappeared=True)
    assert out["state"] == STATE_CONFIRMED_SPLIT


def test_12_disappearance_marker_one_w_review():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01", disappeared=True)
    assert out["state"] == STATE_REVIEW_REQUIRED
    assert out["review_reason"] == REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND


def test_13_disappearance_incomplete_start_cleaning_without_w():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="VeeWash Clean"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01", disappeared=True)
    assert out["state"] == STATE_REVIEW_REQUIRED
    assert out["review_reason"] == REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE


def test_14_manager_split_overrides_review():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("drying", DRY, eid=4, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(
        events,
        bag_id="BAGSPLIT01",
        manager_decision={"decision": "split", "by": "Manager", "note": "ok"},
    )
    assert out["state"] == STATE_MANAGER_SPLIT
    assert out["canonical_split"] is True
    assert out["split_marker_present"] is True  # evidence retained
    assert out["processing_units"] == 2


def test_15_manager_not_split_overrides_confirmed():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, rack="W62-30-VW"),
        _ev("drying", DRY, eid=5, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(
        events,
        bag_id="BAGSPLIT01",
        manager_decision={"decision": "not_split"},
    )
    assert out["state"] == STATE_MANAGER_NOT_SPLIT
    assert out["canonical_split"] is False
    assert out["processing_units"] == 1


def test_16_duplicate_same_rack_same_ts_deduped_not_split():
    events = _base_cycle() + [
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),
        _ev("start-cleaning", W1, eid=2, rack="W61-30-VW"),  # same event id
        _ev("drying", DRY, eid=3, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["washer_load_count"] == 1
    assert out["state"] == STATE_CONFIRMED_NOT_SPLIT


def test_17_zero_loads_closed_not_split():
    events = _base_cycle() + [
        _ev("drying", DRY, eid=2, rack="D10-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="BAGSPLIT01")
    assert out["state"] == STATE_CONFIRMED_NOT_SPLIT


def test_18_supply_finalizable_blocked_by_pending_and_review():
    evaluations = {
        "A": {"state": STATE_PENDING, "split_finalized": False},
        "B": {"state": STATE_REVIEW_REQUIRED, "split_finalized": False},
        "C": {"state": STATE_CONFIRMED_SPLIT, "split_finalized": True},
    }
    fin = supply_day_finalizable(evaluations)
    assert fin["finalizable"] is False
    assert fin["split_pending_count"] == 1
    assert fin["split_review_count"] == 1
    assert fin["supply_status"] == "not_final"


def test_19_supply_finalizable_when_all_resolved():
    evaluations = {
        "A": {"state": STATE_CONFIRMED_SPLIT, "split_finalized": True},
        "B": {"state": STATE_CONFIRMED_NOT_SPLIT, "split_finalized": True},
        "C": {"state": STATE_MANAGER_SPLIT, "split_finalized": True},
    }
    fin = supply_day_finalizable(evaluations)
    assert fin["finalizable"] is True
    assert fin["supply_status"] == "final"


def test_20_all_rush_plus_non_rush_unique_bags():
    """Management ALL split count = unique bags (rush ∪ non-rush), no double-count."""
    rush_ev = evaluate_bag_split(
        _base_cycle(bag="RUSHBAG001")
        + [
            _ev("split-load", MARKER, eid=2, bag="RUSHBAG001"),
            _ev("start-cleaning", W1, eid=3, bag="RUSHBAG001", rack="W61-30-VW"),
            _ev("start-cleaning", W2, eid=4, bag="RUSHBAG001", rack="W62-30-VW"),
            _ev("drying", DRY, eid=5, bag="RUSHBAG001", rack="D10-50-VW"),
        ],
        bag_id="RUSHBAG001",
    )
    non_ev = evaluate_bag_split(
        _base_cycle(bag="NONRBAG002")
        + [
            _ev("split-load", MARKER, eid=2, bag="NONRBAG002"),
            _ev("start-cleaning", W1, eid=3, bag="NONRBAG002", rack="W61-30-VW"),
            _ev("start-cleaning", W2, eid=4, bag="NONRBAG002", rack="W62-30-VW"),
            _ev("drying", DRY, eid=5, bag="NONRBAG002", rack="D10-50-VW"),
        ],
        bag_id="NONRBAG002",
    )
    pack = pack_canonical_split_orders(
        {"RUSHBAG001": rush_ev, "NONRBAG002": non_ev},
        ctx_by_bag={
            "RUSHBAG001": {"rush": "RUSH", "service": "WF"},
            "NONRBAG002": {"rush": "STANDARD", "service": "WF"},
        },
    )
    all_ids = set(pack["split_orders"]["order_ids"])
    rush_ids = {
        bid
        for bid, o in ((x["bag_id"], x) for x in pack["split_orders"]["orders"])
        if str(o.get("rush") or "").upper() == "RUSH"
    }
    non_ids = all_ids - rush_ids
    assert pack["split_orders"]["count"] == 2
    assert all_ids == rush_ids | non_ids
    assert len(all_ids) == len(rush_ids) + len(non_ids)


def test_manager_decision_save_survives_rebuild_table():
    """save_manager_split_decision writes dedicated table (rebuild-safe)."""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    # table_exists path: first call may create
    from backend import rinse_wf_canonical_split as mod

    mod._SPLIT_DECISION_TABLES_READY = True
    result = save_manager_split_decision(
        cursor,
        3,
        datetime(2026, 8, 17).date(),
        "BAGSPLIT01",
        decision="split",
        note="verified",
        decided_by_display_name="Manager",
    )
    assert result["ok"] is True
    assert result["decision"] == MANAGER_DECISION_SPLIT
    assert cursor.execute.called
    sql = cursor.execute.call_args[0][0]
    assert "rinse_wf_bag_split_decisions" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql


def test_batch_evaluate_applies_manager_map():
    events = _base_cycle() + [
        _ev("split-load", MARKER, eid=2),
        _ev("start-cleaning", W1, eid=3, rack="W61-30-VW"),
        _ev("drying", DRY, eid=4, rack="D10-50-VW"),
    ]
    out = evaluate_bags_split(
        {"BAGSPLIT01": events},
        manager_decisions={"BAGSPLIT01": {"decision": MANAGER_DECISION_NOT_SPLIT}},
    )
    assert out["BAGSPLIT01"]["state"] == STATE_MANAGER_NOT_SPLIT


def test_0chdia_style_marker_plus_one_w_plus_inferred_is_review_when_closed():
    """Audit bag pattern: split-load + W* + inferred non-W → not auto-confirmed."""
    events = _base_cycle(bag="0CHDIA263C") + [
        _ev("split-load", MARKER, eid=2, bag="0CHDIA263C"),
        _ev("start-cleaning", W1, eid=3, bag="0CHDIA263C", rack="W61-30-VW"),
        _ev("start-cleaning", W2, eid=4, bag="0CHDIA263C", rack="D36-50-VW"),  # dryer rack on wash
        _ev("drying", DRY, eid=5, bag="0CHDIA263C", rack="D36-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="0CHDIA263C")
    assert out["washer_load_count"] == 1
    assert out["state"] == STATE_REVIEW_REQUIRED


def test_dual_w_with_marker_confirmed():
    events = _base_cycle(bag="4CD3HO10DC") + [
        _ev("split-load", MARKER, eid=2, bag="4CD3HO10DC"),
        _ev("start-cleaning", W1, eid=3, bag="4CD3HO10DC", rack="W24-30-VW"),
        _ev("start-cleaning", W2, eid=4, bag="4CD3HO10DC", rack="W25-30-VW"),
        _ev("drying", DRY, eid=5, bag="4CD3HO10DC", rack="D4-50-VW"),
    ]
    out = evaluate_bag_split(events, bag_id="4CD3HO10DC")
    assert out["state"] == STATE_CONFIRMED_SPLIT
    assert out["canonical_split"] is True


def test_evaluate_day_wf_splits_truncates_next_day_evidence():
    """D+1 split-load / washer must not create REVIEW_REQUIRED as-of day D."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_wf_canonical_split import evaluate_day_wf_splits

    day = date(2026, 8, 17)
    # Aug-17-style: bag still operationally pending at D close; split contradiction
    # only appears from D+1 marker + close (still only 1 washer).
    d_only = _base_cycle(bag="3WXRM6SYAR") + [
        _ev("start-cleaning", W1, eid=2, bag="3WXRM6SYAR", rack="W61-30-VW"),
    ]
    d_plus_next = d_only + [
        _ev("split-load", datetime(2026, 8, 18, 7, 50, 0), eid=3, bag="3WXRM6SYAR"),
        _ev("drying", datetime(2026, 8, 18, 9, 0, 0), eid=4, bag="3WXRM6SYAR", rack="D10-50-VW"),
    ]
    end = naive_et_day_end_inclusive(day)
    truncated = [e for e in d_plus_next if e["scanned_at_parsed"] <= end]
    assert truncated == d_only

    cur = MagicMock()
    with (
        patch(
            "backend.rinse_wf_canonical_split._load_events_for_bags",
            return_value={"3WXRM6SYAR": truncated},
        ) as load,
        patch(
            "backend.rinse_wf_canonical_split.load_manager_split_decisions",
            return_value={},
        ),
    ):
        out = evaluate_day_wf_splits(
            cur, 3, day, ["3WXRM6SYAR"], truncate_to_selected_day=True
        )
    assert load.call_args.kwargs.get("as_of_end") == end
    # Mid-wash / no close on D → PENDING, not Split Order Review.
    assert out["3WXRM6SYAR"]["state"] == STATE_PENDING
    assert out["3WXRM6SYAR"]["state"] != STATE_REVIEW_REQUIRED
    # Full live timeline (no cutoff) → REVIEW (marker YES + loads < 2 after close).
    full = evaluate_bag_split(d_plus_next, bag_id="3WXRM6SYAR")
    assert full["state"] == STATE_REVIEW_REQUIRED
