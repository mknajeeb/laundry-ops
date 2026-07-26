"""HD-only Step-1 day presentation — isolated from WF / Employee Productivity.

Post-cutover HD rules:
- No prior-day HD carryover (unresolved yesterday does not seed today).
- Same-day HD admits are allowed any time during the ET day (opening scrape,
  later portal scrape, same-day HD workload entry, or other qualifying evidence).
- Prior completed HD order instances stay excluded on later days.
- Does not mutate WF / wf_rush / wf_non_rush segments or productivity fields.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_day_membership import INCLUSION_BASELINE
from backend.rinse_veewash_workload import STEP1_AUTHORITATIVE_START_ET

_HD_SEGMENT_KEYS = ("hd", "hd_rush", "hd_non_rush")
_COMBINED_SEGMENT_KEYS = ("all", "rush", "non_rush")


def _as_bag_set(ids: Any) -> set[str]:
    out: set[str] = set()
    for raw in ids or []:
        bid = normalize_bag_id(raw)
        if bid:
            out.add(bid)
    return out


def _recount_seg(seg: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(seg or {})
    bags = dict(out.get("bag_ids") or {})
    for key in (
        "new_today",
        "carryover",
        "completed",
        "pending",
        "review_required",
        "disappeared_without_completion",
        "missing_workload_entry_scan",
        "completed_awaiting_workload_assignment",
    ):
        bags[key] = sorted(_as_bag_set(bags.get(key)))
        if key in ("new_today", "carryover", "completed", "pending"):
            out[key] = len(bags[key])
    review = bags.get("review_required") or []
    bags["disappeared_without_completion"] = list(review)
    out["exceptions"] = {
        **dict(out.get("exceptions") or {}),
        "review_required": len(review),
        "disappeared_without_completion": len(review),
        "total": len(review),
    }
    active = len(bags.get("new_today") or []) + len(bags.get("carryover") or [])
    out["active_workload"] = active
    out["total_workload"] = active
    out["total_operational_orders"] = active
    out["bag_ids"] = bags
    return out


def _strip_ids_from_seg(seg: Mapping[str, Any], remove: set[str]) -> dict[str, Any]:
    if not remove:
        return _recount_seg(seg)
    out = dict(seg or {})
    bags = dict(out.get("bag_ids") or {})
    for key, vals in list(bags.items()):
        bags[key] = [b for b in (vals or []) if normalize_bag_id(b) not in remove]
    out["bag_ids"] = bags
    return _recount_seg(out)


def _hd_carryover_ids(segments: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in _HD_SEGMENT_KEYS:
        seg = segments.get(key) or {}
        ids |= _as_bag_set((seg.get("bag_ids") or {}).get("carryover"))
    return ids


def strip_hd_carryover_from_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Remove HD carryover bags from HD (+ combined) segments; leave WF untouched."""
    out = deepcopy(dict(summary or {}))
    segments = dict(out.get("segments") or {})
    remove = _hd_carryover_ids(segments)
    if not remove:
        # Still force HD carryover counters/lists to empty for terminology cleanup.
        for key in _HD_SEGMENT_KEYS:
            if key not in segments:
                continue
            seg = dict(segments[key] or {})
            bags = dict(seg.get("bag_ids") or {})
            bags["carryover"] = []
            seg["bag_ids"] = bags
            seg["carryover"] = 0
            segments[key] = _recount_seg(seg)
        out["segments"] = segments
        out["hd_policy"] = {
            **dict(out.get("hd_policy") or {}),
            "no_carryover": True,
            "carryover_removed_count": 0,
        }
        return out

    for key in _HD_SEGMENT_KEYS:
        if key in segments:
            segments[key] = _strip_ids_from_seg(segments[key], remove)
            bags = dict((segments[key].get("bag_ids") or {}))
            bags["carryover"] = []
            segments[key]["bag_ids"] = bags
            segments[key]["carryover"] = 0
            segments[key] = _recount_seg(segments[key])

    for key in _COMBINED_SEGMENT_KEYS:
        if key not in segments:
            continue
        # Only strip the HD carryover ids — never rewrite WF membership lists.
        segments[key] = _strip_ids_from_seg(segments[key], remove)

    out["segments"] = segments
    # Top-level carryover is the combined segment's remaining carryover (WF-only after strip).
    all_seg = segments.get("all") or {}
    out["carryover"] = int(all_seg.get("carryover") or 0)
    out["active_workload"] = int(all_seg.get("active_workload") or out.get("active_workload") or 0)
    out["total_workload"] = int(all_seg.get("total_workload") or out.get("total_workload") or 0)
    out["hd_policy"] = {
        **dict(out.get("hd_policy") or {}),
        "no_carryover": True,
        "carryover_removed_count": len(remove),
        "carryover_removed_bag_ids": sorted(remove),
    }
    return out


def _opening_scrape_bag_ids(membership: Mapping[str, Any] | None) -> set[str] | None:
    """Bag ids admitted by the day's first valid portal scrape."""
    if not isinstance(membership, dict):
        return None
    baseline = membership.get("baseline_bag_ids")
    if isinstance(baseline, (list, tuple, set)):
        return _as_bag_set(baseline)
    raw = membership.get("membership")
    if not isinstance(raw, dict):
        return None
    out: set[str] = set()
    for bid, row in raw.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("inclusion_source") or "") != INCLUSION_BASELINE:
            continue
        nb = normalize_bag_id(bid) or normalize_bag_id(row.get("bag_id"))
        if nb:
            out.add(nb)
    return out


def apply_hd_same_day_membership_policy(
    summary: Mapping[str, Any],
    membership: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Keep all remaining HD bags after prior-day carryover strip.

    Fresh start means no yesterday carryover — not midnight-only membership.
    Opening-scrape AND later same-day HD admits (ADDED_LATER / workload entry /
    later portal appearance) stay in HD segments. WF unchanged.
    """
    opening = _opening_scrape_bag_ids(membership)
    out = deepcopy(dict(summary or {}))
    segments = dict(out.get("segments") or {})

    # Belt-and-suspenders: carryover lists must stay empty for HD segments.
    for key in _HD_SEGMENT_KEYS:
        if key not in segments:
            continue
        seg = dict(segments[key] or {})
        bags = dict(seg.get("bag_ids") or {})
        bags["carryover"] = []
        # Fold any residual carryover ids that still appear under new_today into
        # new_today only when already present there; strip pure carryover leftovers
        # was already handled by strip_hd_carryover_from_summary.
        seg["bag_ids"] = bags
        seg["carryover"] = 0
        segments[key] = _recount_seg(seg)

    hd_seg = segments.get("hd") or {}
    hd_bags = dict(hd_seg.get("bag_ids") or {})
    current_hd: set[str] = set()
    for key in ("new_today", "completed", "pending", "review_required"):
        current_hd |= _as_bag_set(hd_bags.get(key))

    opening_ids = opening if opening is not None else set()
    opening_admitted = current_hd & opening_ids
    same_day_later = current_hd - opening_ids if opening is not None else set(current_hd)

    out["segments"] = segments
    all_seg = segments.get("all") or {}
    out["carryover"] = int(all_seg.get("carryover") or 0)
    out["active_workload"] = int(all_seg.get("active_workload") or 0)
    out["total_workload"] = int(all_seg.get("total_workload") or 0)
    out["hd_policy"] = {
        **dict(out.get("hd_policy") or {}),
        "no_carryover": True,
        "opening_scrape_restricted": False,
        "same_day_adds_allowed": True,
        "opening_scrape_admit_count": len(opening_admitted),
        "same_day_later_admit_count": len(same_day_later),
        "removed_non_opening_hd_count": 0,
        "membership_source": "same_day_qualifying_evidence",
        "same_day_later_bag_ids": sorted(same_day_later),
    }
    if opening is None:
        out["hd_policy"]["reason"] = "membership_unavailable"
    out["hd_carryover_enabled"] = False
    return out


# Back-compat alias — old name implied opening-scrape-only (incorrect).
def restrict_hd_to_opening_scrape(
    summary: Mapping[str, Any],
    membership: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return apply_hd_same_day_membership_policy(summary, membership)


def finalize_hd_step1_summary(
    summary: Mapping[str, Any],
    *,
    selected_date_et: date,
    membership: Mapping[str, Any] | None = None,
    apply: bool | None = None,
    cursor=None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Apply HD date-scoped / no-carryover / review / prior-complete presentation."""
    if apply is False:
        return dict(summary or {})
    if selected_date_et < STEP1_AUTHORITATIVE_START_ET:
        return dict(summary or {})
    mem = membership if membership is not None else (summary or {}).get("membership")
    out = strip_hd_carryover_from_summary(summary)
    out = apply_hd_same_day_membership_policy(out, mem if isinstance(mem, dict) else None)

    if cursor is not None and organization_id is not None:
        try:
            from backend.rinse_hd_step1_review import (
                apply_hd_review_status_to_summary,
                build_hd_dashboard_totals,
                exclude_prior_completed_hd_from_summary,
                load_hd_production_status_map,
                load_hd_workitems_added_bag_ids,
                load_prior_completed_hd_bag_ids,
            )

            prior_done = load_prior_completed_hd_bag_ids(
                cursor, int(organization_id), before_date=selected_date_et
            )
            # Only exclude IDs that would otherwise sit in today's HD segment.
            hd_ids = set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("new_today")
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("carryover")
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("completed")
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get(
                    "review_required"
                )
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("pending")
                or []
            )
            drop = {b for b in prior_done if b in hd_ids}
            if drop:
                out = exclude_prior_completed_hd_from_summary(out, drop)

            remaining = set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("new_today")
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get(
                    "review_required"
                )
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("completed")
                or []
            ) | set(
                ((out.get("segments") or {}).get("hd") or {}).get("bag_ids", {}).get("pending")
                or []
            )
            prod = load_hd_production_status_map(
                cursor, int(organization_id), selected_date_et, sorted(remaining)
            )
            wia_ids = load_hd_workitems_added_bag_ids(
                cursor, int(organization_id), sorted(remaining)
            )
            out = apply_hd_review_status_to_summary(
                out,
                production_by_bag=prod,
                workitems_added_bag_ids=wia_ids,
            )
            out["hd_dashboard_totals"] = build_hd_dashboard_totals(
                cursor,
                int(organization_id),
                selected_date_et,
                hd_segment=(out.get("segments") or {}).get("hd"),
            )
        except Exception:
            # Presentation must never break WF summary serving.
            pass
    return out


def should_apply_hd_presentation_on_read(
    *,
    selected_date_et: date,
    today: date,
    day_status: str | None,
) -> bool:
    """Heal HD carryover on read for the live ET day only (historical stays frozen)."""
    if selected_date_et < STEP1_AUTHORITATIVE_START_ET:
        return False
    if selected_date_et != today:
        return False
    status = str(day_status or "").strip().upper()
    return status != "CLOSED"
