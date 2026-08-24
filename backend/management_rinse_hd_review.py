"""Canonical Management Rinse HD Missing From Portal review membership.

Single source for headline counts and drawer/list membership. Uses the latest
successful, non-contaminated at_vendor presence traversal — not historical
day_bags snapshots or partial scrapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.management_rinse_hd import (
    STATUS_AWAITING_ENTRY,
    STATUS_AWAITING_FOLD,
    STATUS_COMPLETE,
    STATUS_MISSING_FROM_PORTAL,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    _norm_bag,
)
from backend.ta_helpers import table_exists


def _is_hd_presence_service(service_type: Any) -> bool:
    st = str(service_type or "").strip().upper()
    if not st:
        return False
    if st == "HD":
        return True
    return "HOME DELIVERY" in st or "HANG DRY" in st or st in ("HOME_DELIVERY", "HANG_DRY")

CATEGORY_MISSING_FROM_PORTAL = STATUS_MISSING_FROM_PORTAL
HD_REVIEW_REASON_MISSING_FROM_PORTAL = "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"

_ACTIVE_PRE_REVIEW_STATUSES = frozenset(
    {
        STATUS_PENDING_WASH,
        STATUS_WASHED,
        STATUS_AWAITING_FOLD,
        STATUS_AWAITING_ENTRY,
    }
)


def _is_full_traversal_success(run: Mapping[str, Any] | None) -> bool:
    if not run:
        return False
    status = str(run.get("status") or "").strip().lower()
    return status == "success"


def load_hd_latest_source_portal_context(
    cursor,
    organization_id: int,
) -> dict[str, Any]:
    """Latest successful full at_vendor presence traversal for HD source checks."""
    from backend.rinse_cleaner_ticket_presence import load_presence_run_snapshot_by_bag
    from backend.rinse_shift_monitor_baseline import (
        _is_successful_presence_run,
        is_contaminated_presence_run,
        latest_clean_at_vendor_presence_scrape,
    )

    org = int(organization_id)
    run = latest_clean_at_vendor_presence_scrape(cursor, org)
    if not run or not _is_successful_presence_run(run):
        return {
            "traversal_complete": False,
            "portal_bag_ids": set(),
            "presence_run_id": None,
            "finished_at": None,
            "reason": "no_successful_presence_run",
            "snapshot_by_bag": {},
        }
    if is_contaminated_presence_run(run, organization_id=org):
        return {
            "traversal_complete": False,
            "portal_bag_ids": set(),
            "presence_run_id": int(run.get("id") or 0) or None,
            "finished_at": run.get("finished_at"),
            "reason": "contaminated_presence_run",
            "snapshot_by_bag": {},
        }
    # Partial traversals must not create disappearance review.
    if not _is_full_traversal_success(run):
        return {
            "traversal_complete": False,
            "portal_bag_ids": set(),
            "presence_run_id": int(run.get("id") or 0) or None,
            "finished_at": run.get("finished_at"),
            "reason": "traversal_incomplete",
            "snapshot_by_bag": {},
        }

    run_id = int(run.get("id") or 0)
    snapshot = (
        load_presence_run_snapshot_by_bag(cursor, org, presence_run_id=run_id)
        if run_id and table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows")
        else {}
    )
    portal_bag_ids: set[str] = set()
    for bid, row in (snapshot or {}).items():
        if _is_hd_presence_service(row.get("service_type")):
            portal_bag_ids.add(_norm_bag(bid))

    return {
        "traversal_complete": True,
        "portal_bag_ids": portal_bag_ids,
        "presence_run_id": run_id or None,
        "finished_at": run.get("finished_at"),
        "reason": None,
        "snapshot_by_bag": snapshot,
    }


def hd_review_disposition_for_order(
    *,
    workflow_status: str,
    explicitly_complete: bool,
    bag_id: str,
    portal_context: Mapping[str, Any],
    presence_meta: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return display bucket + review context for one visible HD order."""
    wf = str(workflow_status or "").strip().lower()
    bid = _norm_bag(bag_id)
    presence = dict(presence_meta or {})
    last_seen = presence.get("last_seen_at")
    on_latest_source = bool(bid and bid in set(portal_context.get("portal_bag_ids") or set()))
    ctx = {
        "prior_hd_status": wf,
        "on_latest_source": on_latest_source,
        "latest_source_presence": on_latest_source,
        "last_portal_seen_at": last_seen,
        "review_reason": None,
        "latest_presence_run_id": portal_context.get("presence_run_id"),
        "latest_presence_finished_at": portal_context.get("finished_at"),
    }

    if explicitly_complete or wf == STATUS_COMPLETE:
        return STATUS_COMPLETE, ctx

    if not bool(portal_context.get("traversal_complete")):
        return wf, ctx

    if on_latest_source:
        return wf, ctx

    if wf in _ACTIVE_PRE_REVIEW_STATUSES:
        ctx["review_reason"] = HD_REVIEW_REASON_MISSING_FROM_PORTAL
        return STATUS_MISSING_FROM_PORTAL, ctx

    return wf, ctx


def compute_canonical_hd_missing_membership(
    visible_orders: Sequence[Mapping[str, Any]],
    portal_context: Mapping[str, Any],
    *,
    presence_meta_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authoritative Missing From Portal membership for visible HD orders."""
    presence_meta_by_bag = presence_meta_by_bag or {}
    missing: list[str] = []
    disposition: dict[str, str] = {}
    context_by_bag: dict[str, dict[str, Any]] = {}

    for raw in visible_orders or []:
        if not isinstance(raw, Mapping):
            continue
        bid = _norm_bag(raw.get("bag_id"))
        if not bid:
            continue
        wf = str(raw.get("workflow_status") or raw.get("status") or "").strip().lower()
        explicit = bool(raw.get("explicitly_complete"))
        if raw.get("completion_at"):
            explicit = True
        display, ctx = hd_review_disposition_for_order(
            workflow_status=wf,
            explicitly_complete=explicit,
            bag_id=bid,
            portal_context=portal_context,
            presence_meta=presence_meta_by_bag.get(bid),
        )
        disposition[bid] = display
        context_by_bag[bid] = ctx
        if display == STATUS_MISSING_FROM_PORTAL:
            missing.append(bid)

    missing = sorted(set(missing))
    return {
        CATEGORY_MISSING_FROM_PORTAL: missing,
        "disposition": disposition,
        "context_by_bag": context_by_bag,
        "portal_context": {
            "traversal_complete": bool(portal_context.get("traversal_complete")),
            "presence_run_id": portal_context.get("presence_run_id"),
            "finished_at": portal_context.get("finished_at"),
            "reason": portal_context.get("reason"),
            "portal_hd_count": len(portal_context.get("portal_bag_ids") or []),
        },
        "counts": {CATEGORY_MISSING_FROM_PORTAL: len(missing)},
    }


def enrich_hd_order_with_review(
    order: dict[str, Any],
    membership: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply canonical review disposition fields onto a compact HD order row."""
    bid = _norm_bag(order.get("bag_id"))
    disposition = dict(membership.get("disposition") or {})
    context_by_bag = dict(membership.get("context_by_bag") or {})
    ctx = dict(context_by_bag.get(bid) or {})
    prior = str(ctx.get("prior_hd_status") or order.get("workflow_status") or order.get("status") or "")
    display = disposition.get(bid) or order.get("status")
    row = dict(order)
    row["workflow_status"] = prior
    row["status"] = display
    row["prior_hd_status"] = prior
    row["review_reason"] = ctx.get("review_reason")
    row["on_latest_portal"] = bool(ctx.get("on_latest_source"))
    row["on_latest_source"] = bool(ctx.get("on_latest_source"))
    row["latest_source_presence"] = bool(ctx.get("latest_source_presence"))
    row["last_portal_seen_at"] = ctx.get("last_portal_seen_at")
    row["disappeared_from_portal"] = display == STATUS_MISSING_FROM_PORTAL
    row["latest_presence_run_id"] = ctx.get("latest_presence_run_id")
    row["latest_presence_finished_at"] = ctx.get("latest_presence_finished_at")
    if display == STATUS_MISSING_FROM_PORTAL:
        row["status_legacy"] = prior
    return row


def format_hd_customer_name(order: Mapping[str, Any] | None) -> str:
    if not isinstance(order, Mapping):
        return "Customer unavailable"
    name = str(
        order.get("customer_name")
        or order.get("name_clean")
        or order.get("customer")
        or ""
    ).strip()
    return name or "Customer unavailable"
