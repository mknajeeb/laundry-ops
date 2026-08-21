"""Helpers to keep Management published headlines structurally valid."""

from __future__ import annotations

from typing import Any, Mapping


def _unique_ids(vals: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(vals or []):
        bid = str(raw or "").strip().upper()
        if not bid or bid in seen:
            continue
        seen.add(bid)
        out.append(bid)
    return out


def finalize_closed_day_management_workload(
    headline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Closed-day Management final workload excludes carried_forward.

    Final production identity:
      Workload = Completed + Pending + Review

    ``carried_forward`` bag IDs and counts remain on the headline for audit
    lineage (bags moved to the next business day) but must not inflate the
    closed-day Management workload total. Those bags belong to the next day's
    carryover / opening workload — never both days' final totals.
    """
    out = dict(headline or {})
    segments = dict(out.get("segments") or {})
    for name, seg in list(segments.items()):
        seg_out = dict(seg or {})
        bags = dict(seg_out.get("bag_ids") or {})
        completed = _unique_ids(bags.get("completed"))
        pending = _unique_ids(bags.get("pending"))
        review = _unique_ids(bags.get("review_required"))
        carried = _unique_ids(bags.get("carried_forward"))
        unfinished = _unique_ids(bags.get("unfinished_at_close"))
        bags["completed"] = completed
        bags["pending"] = pending
        bags["review_required"] = review
        bags["carried_forward"] = carried
        bags["unfinished_at_close"] = unfinished
        seg_out["bag_ids"] = bags
        seg_out["completed"] = len(completed)
        seg_out["pending"] = len(pending)
        seg_out["carried_forward"] = len(carried)
        seg_out["unfinished_at_close"] = len(unfinished)
        exceptions = dict(seg_out.get("exceptions") or {})
        exceptions["review_required"] = len(review)
        exceptions["carried_forward"] = len(carried)
        exceptions["unfinished_at_close"] = len(unfinished)
        exceptions["moved_forward_to_next_day"] = len(carried)
        exceptions["total"] = len(review)
        seg_out["exceptions"] = exceptions
        total = len(completed) + len(pending) + len(review)
        seg_out["total_workload"] = total
        seg_out["active_workload"] = total
        seg_out["total_operational_orders"] = total
        seg_out["closed_day_final_excludes_carried_forward"] = True
        seg_out["moved_forward_count"] = len(carried)
        segments[name] = seg_out
    out["segments"] = segments
    all_seg = dict(segments.get("all") or segments.get("wf") or {})
    if all_seg:
        out["completed"] = all_seg.get("completed", out.get("completed"))
        out["pending"] = all_seg.get("pending", out.get("pending"))
        out["carried_forward"] = all_seg.get("carried_forward", out.get("carried_forward"))
        out["exceptions"] = dict(all_seg.get("exceptions") or out.get("exceptions") or {})
        out["total_workload"] = all_seg.get("total_workload")
        out["active_workload"] = all_seg.get("active_workload")
        out["completed_count"] = int(all_seg.get("completed") or 0)
        out["pending_count"] = int(all_seg.get("pending") or 0)
        out["carried_forward_count"] = int(all_seg.get("carried_forward") or 0)
        out["review_required_count"] = int(
            (all_seg.get("exceptions") or {}).get("review_required") or 0
        )
        out["moved_forward_count"] = int(all_seg.get("moved_forward_count") or 0)
        out["closed_day_final_excludes_carried_forward"] = True
    return out


def headline_has_wf_workload_segments(headline: Mapping[str, Any] | None) -> bool:
    """True when headline carries Management WF workload segments (not weights-only)."""
    hl = dict(headline or {})
    segs = dict(hl.get("segments") or {})
    wf = dict(segs.get("wf") or {})
    if not wf:
        # Legacy flat headline still counts if it has total_workload.
        try:
            total = hl.get("total_workload")
            if total is None:
                total = hl.get("active_workload")
            if total is None:
                return False
            int(total)
            return True
        except (TypeError, ValueError):
            return False
    try:
        total = wf.get("total_workload")
        if total is None:
            total = wf.get("active_workload")
        if total is None:
            return False
        int(total)
        return True
    except (TypeError, ValueError):
        return False


def merge_weights_into_headline(
    base: Mapping[str, Any] | None,
    weights: Mapping[str, Any] | None,
    *,
    repair_tag: str | None = None,
) -> dict[str, Any]:
    """Overlay weight totals onto an existing Management headline without wiping segments."""
    out = dict(base or {})
    if weights:
        out["weights"] = dict(weights)
    if repair_tag:
        out["repair"] = repair_tag
    return out
