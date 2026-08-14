"""Manager edits must reproject headline.specialty_metrics before return.

Does not rebuild membership or completion. Specialty classification inputs
(bulk lines / rejected / split) are supplied by a test store standing in for
attach_specialty_metrics_to_summary.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_hd_day_metrics import CLASSIFICATION_VERSION
from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

ORG = 3
DAY = date(2026, 8, 13)
BAG_A = "54HFABA2NB"
BAG_B = "EU13HA1Z1E"
OTHER = "OTHERBAG99"


def _seg(*, completed_ids=None, pending_ids=None, review_ids=None, new_today=None):
    completed_ids = list(completed_ids or [])
    pending_ids = list(pending_ids or [])
    review_ids = list(review_ids or [])
    new_today = list(
        new_today
        if new_today is not None
        else completed_ids + pending_ids + review_ids
    )
    total = len(new_today)
    return {
        "completed": len(completed_ids),
        "pending": len(pending_ids),
        "new_today": len(new_today),
        "carryover": 0,
        "active_workload": total,
        "total_workload": total,
        "exceptions": {
            "review_required": len(review_ids),
            "disappeared_without_completion": len(review_ids),
            "total": len(review_ids),
        },
        "bag_ids": {
            "new_today": new_today,
            "carryover": [],
            "completed": completed_ids,
            "pending": pending_ids,
            "review_required": review_ids,
            "disappeared_without_completion": list(review_ids),
        },
    }


def _pack(*, bath=(), comforter=(), rejected=(), split=()):
    def _one(key, ids):
        ids = list(ids)
        return {
            "key": key,
            "count": len(ids),
            "order_ids": ids,
            "orders": [{"bag_id": b} for b in ids],
        }

    return {
        "classification_version": CLASSIFICATION_VERSION,
        "comforter_orders": _one("comforter_orders", comforter),
        "bath_mat_orders": _one("bath_mat_orders", bath),
        "rejected_orders": _one("rejected_orders", rejected),
        "split_orders": _one("split_orders", split),
    }


def _frozen_specialty(*, bath=(), comforter=(), rejected=(), split=()):
    pack = _pack(bath=bath, comforter=comforter, rejected=rejected, split=split)
    return {"all": dict(pack), "wf": dict(pack), "hd": _pack()}


class SpecialtyStore:
    """Live specialty inputs after manager bulk-line edits (not the frozen pack)."""

    def __init__(self, *, bath=None, comforter=None, rejected=None, split=None):
        self.bath = dict(bath or {})
        self.comforter = dict(comforter or {})
        self.rejected = set(rejected or [])
        self.split = set(split or [])
        self.calls = 0

    def attach(self, cursor, organization_id, selected_date_et, summary, **_kwargs):
        self.calls += 1
        out = dict(summary or {})
        member = set()
        segs = out.get("segments") or {}
        for key in ("all", "wf", "hd"):
            bags = ((segs.get(key) or {}).get("bag_ids") or {})
            for bucket in (
                "new_today",
                "carryover",
                "completed",
                "pending",
                "review_required",
            ):
                member.update(str(b) for b in (bags.get(bucket) or []) if b)
        bath = sorted(b for b, qty in self.bath.items() if b in member and float(qty or 0) > 0)
        comforter = sorted(
            b for b, qty in self.comforter.items() if b in member and float(qty or 0) > 0
        )
        rejected = sorted(b for b in self.rejected if b in member)
        split = sorted(b for b in self.split if b in member)
        pack = _pack(
            bath=bath, comforter=comforter, rejected=rejected, split=split
        )
        out["specialty_metrics"] = {
            "all": dict(pack),
            "wf": dict(pack),
            "hd": _pack(),
        }
        out["comforter_order_count"] = pack["comforter_orders"]["count"]
        out["bath_mat_order_count"] = pack["bath_mat_orders"]["count"]
        out["rejected_order_count"] = pack["rejected_orders"]["count"]
        out["split_order_count"] = pack["split_orders"]["count"]
        return out


def _day_row(bag_id, *, status="review_required", emp="Evelin (VeeWash)", pre=27.0, post=27.0):
    return {
        "bag_id": bag_id,
        "effective_status": status,
        "service_type": "WF",
        "rush_status": "NON-RUSH",
        "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"] if status == "review_required" else [],
        "bag_snapshot": {"bag_id": bag_id, "outcome": status},
        "canonical_completion_status": status,
        "canonical_completion_employee": emp,
        "canonical_completion_timestamp": "2026-08-13T15:09:00",
        "pre_weight_lbs": pre,
        "post_weight_lbs": post,
        "weight_lbs": post,
    }


def _status_rows(segments, *, edited_bag, edited_status):
    rows = {}
    for seg in segments.values():
        bags = seg.get("bag_ids") or {}
        for bid in bags.get("completed") or []:
            rows[bid] = {
                "effective_status": "completed",
                "service_type": "WF",
                "rush_status": "NON-RUSH",
            }
        for bid in bags.get("pending") or []:
            rows[bid] = {
                "effective_status": "pending",
                "service_type": "WF",
                "rush_status": "NON-RUSH",
            }
        for bid in bags.get("review_required") or []:
            rows[bid] = {
                "effective_status": "review_required",
                "service_type": "WF",
                "rush_status": "NON-RUSH",
            }
        for bid in bags.get("new_today") or []:
            rows.setdefault(
                bid,
                {
                    "effective_status": "pending",
                    "service_type": "WF",
                    "rush_status": "NON-RUSH",
                },
            )
    rows[edited_bag] = {
        "effective_status": edited_status,
        "service_type": "WF",
        "rush_status": "NON-RUSH",
    }
    return rows


def _extract_headline(cursor):
    for c in reversed(cursor.execute.call_args_list):
        sql = str(c.args[0]) if c.args else ""
        if "UPDATE rinse_shift_monitor_days" in sql and "headline_json" in sql:
            return json.loads(c.args[1][1]), json.loads(c.args[1][2])
    return None, None


def _extract_day_bag_productivity(cursor):
    for c in cursor.execute.call_args_list:
        sql = str(c.args[0]) if c.args else ""
        if "UPDATE rinse_shift_monitor_day_bags" in sql and "productivity_credit_eligible" in sql:
            params = c.args[1]
            # trailing org, date, bag_id; productivity fields sit just before those.
            return {
                "productivity_employee_name": params[-8],
                "productivity_completed_at": params[-7],
                "productivity_weight_lbs": params[-6],
                "productivity_credit_eligible": params[-5],
                "productivity_exclusion_reason": params[-4],
                "bag_id": params[-1],
            }
    return None


def _run_patch(
    *,
    bag_id,
    store,
    segments,
    day_row,
    headline_extra=None,
    outcome_action="mark_completed",
    bulk_cleared=True,
    edited_status="completed",
    previous_status=None,
    previous_reasons=None,
):
    from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch

    cursor = MagicMock()
    headline = {
        "segments": segments,
        "completed": segments["all"]["completed"],
        "pending": segments["all"]["pending"],
        "total_workload": segments["all"]["total_workload"],
        "active_workload": segments["all"]["active_workload"],
        "exceptions": dict(segments["all"]["exceptions"]),
        "review_reasons_by_bag": {
            b: ["WF_BULK_WORKITEM_REVIEW"]
            for b in (segments["all"]["bag_ids"]["review_required"] or [])
        },
        "review_by_reason": {
            "WF_BULK_WORKITEM_REVIEW": list(segments["all"]["bag_ids"]["review_required"] or [])
        },
        "specialty_metrics": _frozen_specialty(),
        "comforter_order_count": 0,
        "bath_mat_order_count": 0,
        "rejected_order_count": 0,
        "split_order_count": 0,
    }
    if headline_extra:
        headline.update(headline_extra)
    day_rec = {
        "headline": headline,
        "workload_meta": {"review_reasons_by_bag": dict(headline["review_reasons_by_bag"])},
    }
    prev = previous_status or day_row.get("effective_status")
    status_rows = _status_rows(segments, edited_bag=bag_id, edited_status=edited_status)
    with patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=[day_row]
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=day_rec
    ), patch(
        "backend.rinse_veewash_shift_day._load_day_bag_status_projection",
        return_value=status_rows,
    ), patch(
        "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary",
        side_effect=store.attach,
    ):
        out = apply_manager_edit_day_bag_patch(
            cursor,
            ORG,
            DAY,
            bag_id,
            previous_effective_status=prev,
            previous_reason_codes=previous_reasons
            if previous_reasons is not None
            else list(day_row.get("review_reason_codes") or []),
            outcome_action=outcome_action,
            bulk_cleared=bulk_cleared,
            completion_at=day_row.get("canonical_completion_timestamp"),
            completed_by=day_row.get("canonical_completion_employee"),
            pre_weight_lbs=day_row.get("pre_weight_lbs"),
            post_weight_lbs=day_row.get("post_weight_lbs"),
        )
    patched, meta = _extract_headline(cursor)
    prod = _extract_day_bag_productivity(cursor)
    return out, patched, meta, prod, cursor


def test_bath_mat_add_and_complete_updates_specialty_immediately():
    store = SpecialtyStore(
        bath={BAG_A: 1},
        rejected=[BAG_A, OTHER],
        split=[BAG_A],
    )
    members = [BAG_A, BAG_B, OTHER]
    segments = {
        "all": _seg(completed_ids=[OTHER], review_ids=[BAG_A, BAG_B], new_today=members),
        "wf": _seg(completed_ids=[OTHER], review_ids=[BAG_A, BAG_B], new_today=members),
    }
    out, patched, meta, prod, _ = _run_patch(
        bag_id=BAG_A,
        store=store,
        segments=segments,
        day_row=_day_row(BAG_A, emp="Jennifer (VeeWash)", pre=20.6, post=18.0),
    )
    assert out["ok"] is True
    assert out["effective_status"] == "completed"
    assert out["specialty_reprojected"] is True
    assert store.calls == 1
    assert patched["bath_mat_order_count"] == 1
    assert patched["specialty_metrics"]["all"]["bath_mat_orders"]["order_ids"] == [BAG_A]
    assert patched["comforter_order_count"] == 0
    assert patched["rejected_order_count"] == 2
    assert patched["split_order_count"] == 1
    assert meta["specialty_metrics_reprojected"] is True
    # Membership unchanged (still 3 new_today).
    assert patched["segments"]["wf"]["bag_ids"]["new_today"] == members
    assert BAG_A in patched["segments"]["wf"]["bag_ids"]["completed"]
    assert BAG_A not in patched["segments"]["wf"]["bag_ids"]["review_required"]
    # Productivity credit intact: eligible + Evidence PRE, not POST.
    assert prod["productivity_credit_eligible"] == 1
    assert prod["productivity_weight_lbs"] == 20.6
    assert prod["productivity_employee_name"] == "Jennifer (VeeWash)"
    assert prod["productivity_exclusion_reason"] is None


def test_two_edited_bags_aggregate_bath_mat_count():
    store = SpecialtyStore(bath={BAG_A: 1}, rejected=[BAG_A, BAG_B], split=[BAG_A, BAG_B])
    members = [BAG_A, BAG_B, OTHER]
    segments = {
        "all": _seg(completed_ids=[OTHER], review_ids=[BAG_A, BAG_B], new_today=members),
        "wf": _seg(completed_ids=[OTHER], review_ids=[BAG_A, BAG_B], new_today=members),
    }
    out_a, patched_a, _, _, _ = _run_patch(
        bag_id=BAG_A,
        store=store,
        segments=segments,
        day_row=_day_row(BAG_A, emp="Jennifer (VeeWash)", pre=20.6, post=18.0),
    )
    assert patched_a["bath_mat_order_count"] == 1

    store.bath[BAG_B] = 1
    segments_after = {
        "all": _seg(completed_ids=[OTHER, BAG_A], review_ids=[BAG_B], new_today=members),
        "wf": _seg(completed_ids=[OTHER, BAG_A], review_ids=[BAG_B], new_today=members),
    }
    out_b, patched_b, _, prod_b, _ = _run_patch(
        bag_id=BAG_B,
        store=store,
        segments=segments_after,
        day_row=_day_row(BAG_B, emp="Evelin (VeeWash)", pre=27.0, post=27.0),
        headline_extra={
            "specialty_metrics": _frozen_specialty(bath=[BAG_A], rejected=[BAG_A, BAG_B], split=[BAG_A, BAG_B]),
            "bath_mat_order_count": 1,
            "rejected_order_count": 2,
            "split_order_count": 2,
        },
    )
    assert out_a["effective_status"] == "completed"
    assert out_b["effective_status"] == "completed"
    assert patched_b["bath_mat_order_count"] == 2
    assert set(patched_b["specialty_metrics"]["all"]["bath_mat_orders"]["order_ids"]) == {
        BAG_A,
        BAG_B,
    }
    assert patched_b["comforter_order_count"] == 0
    assert patched_b["rejected_order_count"] == 2
    assert patched_b["split_order_count"] == 2
    assert prod_b["productivity_credit_eligible"] == 1
    assert prod_b["productivity_weight_lbs"] == 27.0
    assert set(patched_b["segments"]["wf"]["bag_ids"]["new_today"]) == set(members)


def test_removing_specialty_item_updates_totals():
    store = SpecialtyStore(bath={BAG_A: 1, BAG_B: 1}, rejected=[BAG_A, BAG_B], split=[BAG_A, BAG_B])
    members = [BAG_A, BAG_B]
    segments = {
        "all": _seg(completed_ids=[BAG_A, BAG_B], new_today=members),
        "wf": _seg(completed_ids=[BAG_A, BAG_B], new_today=members),
    }
    store.bath.pop(BAG_A)
    _, patched, _, _, _ = _run_patch(
        bag_id=BAG_A,
        store=store,
        segments=segments,
        day_row=_day_row(BAG_A, status="completed", emp="Jennifer (VeeWash)", pre=20.6, post=18.0),
        outcome_action=None,
        bulk_cleared=False,
        edited_status="completed",
        previous_status="completed",
        previous_reasons=[],
        headline_extra={
            "specialty_metrics": _frozen_specialty(
                bath=[BAG_A, BAG_B], rejected=[BAG_A, BAG_B], split=[BAG_A, BAG_B]
            ),
            "bath_mat_order_count": 2,
            "rejected_order_count": 2,
            "split_order_count": 2,
        },
    )
    assert patched["bath_mat_order_count"] == 1
    assert patched["specialty_metrics"]["all"]["bath_mat_orders"]["order_ids"] == [BAG_B]
    assert patched["rejected_order_count"] == 2
    assert patched["split_order_count"] == 2
    assert patched["segments"]["wf"]["completed"] == 2


def test_changing_specialty_qty_keeps_order_in_totals():
    store = SpecialtyStore(bath={BAG_A: 2})
    members = [BAG_A]
    segments = {
        "all": _seg(completed_ids=[BAG_A], new_today=members),
        "wf": _seg(completed_ids=[BAG_A], new_today=members),
    }
    _, patched, _, _, _ = _run_patch(
        bag_id=BAG_A,
        store=store,
        segments=segments,
        day_row=_day_row(BAG_A, status="completed", pre=20.6, post=18.0),
        outcome_action=None,
        bulk_cleared=False,
        edited_status="completed",
        previous_status="completed",
        previous_reasons=[],
        headline_extra={
            "specialty_metrics": _frozen_specialty(bath=[BAG_A]),
            "bath_mat_order_count": 1,
        },
    )
    # Distinct-order count stays 1; bag remains in the Bath Mats card.
    assert patched["bath_mat_order_count"] == 1
    assert patched["specialty_metrics"]["all"]["bath_mat_orders"]["order_ids"] == [BAG_A]


def test_status_only_edit_does_not_corrupt_specialty_totals():
    store = SpecialtyStore(
        bath={BAG_A: 1, BAG_B: 1},
        rejected=[BAG_A, BAG_B],
        split=[BAG_A, BAG_B],
    )
    members = [BAG_A, BAG_B, OTHER]
    segments = {
        "all": _seg(completed_ids=[BAG_A, BAG_B], pending_ids=[OTHER], new_today=members),
        "wf": _seg(completed_ids=[BAG_A, BAG_B], pending_ids=[OTHER], new_today=members),
    }
    frozen = _frozen_specialty(
        bath=[BAG_A, BAG_B],
        rejected=[BAG_A, BAG_B],
        split=[BAG_A, BAG_B],
    )
    _, patched, _, prod, _ = _run_patch(
        bag_id=OTHER,
        store=store,
        segments=segments,
        day_row=_day_row(OTHER, status="pending", emp="Amna (Veewash)", pre=10.0, post=None),
        outcome_action="return_pending",
        bulk_cleared=False,
        edited_status="pending",
        previous_status="pending",
        previous_reasons=[],
        headline_extra={
            "specialty_metrics": frozen,
            "bath_mat_order_count": 2,
            "rejected_order_count": 2,
            "split_order_count": 2,
            "comforter_order_count": 0,
        },
    )
    assert patched["bath_mat_order_count"] == 2
    assert patched["rejected_order_count"] == 2
    assert patched["split_order_count"] == 2
    assert patched["comforter_order_count"] == 0
    assert set(patched["specialty_metrics"]["all"]["bath_mat_orders"]["order_ids"]) == {
        BAG_A,
        BAG_B,
    }
    assert OTHER in patched["segments"]["wf"]["bag_ids"]["pending"]
    assert BAG_A in patched["segments"]["wf"]["bag_ids"]["completed"]
    assert BAG_B in patched["segments"]["wf"]["bag_ids"]["completed"]
    assert prod["productivity_credit_eligible"] == 0
    assert prod["productivity_exclusion_reason"] == "effective_status=pending"


def test_productivity_eligibility_uses_pre_not_post_for_wf():
    proj = project_productivity_fields_for_day_bag(
        {
            "effective_status": "completed",
            "service_type": "WF",
            "canonical_completion_employee": "Jennifer (VeeWash)",
            "canonical_completion_timestamp": "2026-08-13T12:30:00",
            "pre_weight_lbs": 20.6,
            "post_weight_lbs": 18.0,
            "weight_lbs": 18.0,
        }
    )
    assert proj["productivity_credit_eligible"] == 1
    assert proj["productivity_weight_lbs"] == 20.6
    proj_review = project_productivity_fields_for_day_bag(
        {
            "effective_status": "review_required",
            "service_type": "WF",
            "canonical_completion_employee": "Jennifer (VeeWash)",
            "pre_weight_lbs": 20.6,
            "post_weight_lbs": 18.0,
        }
    )
    assert proj_review["productivity_credit_eligible"] == 0


def test_read_path_still_skips_frozen_v2_specialty_pack():
    """Interactive read must not rebuild specialty when the persisted pack is current."""
    from backend.rinse_veewash_shift_day import _ensure_specialty_metrics

    summary = {
        "specialty_metrics": _frozen_specialty(bath=[BAG_A, BAG_B], rejected=[BAG_A], split=[BAG_A]),
        "bath_mat_order_count": 0,
    }
    cursor = MagicMock()
    with patch(
        "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary"
    ) as attach:
        out = _ensure_specialty_metrics(cursor, ORG, DAY, summary)
    attach.assert_not_called()
    assert out["specialty_metrics"]["all"]["bath_mat_orders"]["count"] == 2
