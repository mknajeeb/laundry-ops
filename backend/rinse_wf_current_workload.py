"""WF Current Workload — open order-instance authority (date-free).

Current Workload = latest legitimate WF OI per bag where completed_at IS NULL.

Selected-date Completed is a separate concept (see get_selected_date_wf_completed).
Registry / day-bag / Performance COMPLETED never removes an open OI.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.business_time import business_today, system_datetime_to_et
from backend.rinse_bag_completion import COMPLETION_COMPLETED, normalize_bag_id
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_scan_purpose import normalize_scan_purpose
from backend.rinse_veewash_workload import (
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
)
from backend.ta_helpers import table_exists

REVIEW_REGISTRY_STALE_COMPLETED = "REGISTRY_COMPLETED_WITHOUT_OI_EVIDENCE"


def _et_date(dt: Any) -> date | None:
    if not isinstance(dt, datetime):
        return None
    et = system_datetime_to_et(dt)
    if et is None:
        return None
    return et.date()


def _norm_purpose(raw: Any) -> str:
    p = normalize_scan_purpose(raw)
    if p.startswith("sent-to-vendor"):
        return "sent-to-vendor"
    return p


def lifecycle_received_from_vendor_at(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime | None,
    *,
    lifecycle_end_exclusive: datetime | None = None,
) -> datetime | None:
    """Latest purpose=sent-to-vendor scan in this OI lifecycle window.

    Window: [cycle_anchor_at, lifecycle_end_exclusive).
    ``lifecycle_end_exclusive`` should be the next OI's cycle_anchor_at when
    known; otherwise open-ended (do not cut on every subsequent STV).
    Never uses lifetime MAX(bag_id) across reusable-bag history.
    """
    bid = normalize_bag_id(bag_id)
    if not bid or cycle_anchor_at is None:
        return None
    if not isinstance(cycle_anchor_at, datetime):
        return None
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return None
    org = int(organization_id)
    cursor.execute(
        """
        SELECT purpose, scanned_at_parsed, id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed >= %s
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (org, bid, cycle_anchor_at),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    if not rows:
        return None

    end = lifecycle_end_exclusive
    latest: datetime | None = None
    for row in rows:
        if _norm_purpose(row.get("purpose")) != "sent-to-vendor":
            continue
        ts = row.get("scanned_at_parsed")
        if not isinstance(ts, datetime):
            continue
        if ts < cycle_anchor_at:
            continue
        if end is not None and ts >= end:
            continue
        if latest is None or ts >= latest:
            latest = ts
    return latest


def _next_oi_cycle_anchor(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime,
) -> datetime | None:
    """Next WF OI cycle_anchor_at for the same bag after this lifecycle (exclusive end)."""
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE, ensure_rinse_order_instances_table

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    ensure_rinse_order_instances_table(cursor)
    cursor.execute(
        f"""
        SELECT cycle_anchor_at
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND bag_id = %s
          AND service_type = 'WF'
          AND cycle_anchor_at > %s
        ORDER BY cycle_anchor_at ASC
        LIMIT 1
        """,
        (int(organization_id), bid, cycle_anchor_at),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return None
    end = row.get("cycle_anchor_at")
    return end if isinstance(end, datetime) else None


def _registry_completed_open_bags(
    cursor,
    organization_id: int,
    open_bags: Sequence[str],
) -> set[str]:
    """Open bag_ids whose registry row is COMPLETED (stale vs open OI)."""
    from backend.rinse_bag_registry import get_registry_rows_for_bags

    ids = sorted({normalize_bag_id(b) for b in open_bags if normalize_bag_id(b)})
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return set()
    rows = get_registry_rows_for_bags(cursor, int(organization_id), ids) or {}
    out: set[str] = set()
    for bid, row in rows.items():
        if str(row.get("completion_status") or "").strip().upper() != COMPLETION_COMPLETED:
            continue
        nb = normalize_bag_id(bid)
        if nb:
            out.add(nb)
    return out


def _bags_with_valid_current_cycle_completion(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    as_of_date_et: date | None = None,
) -> set[str]:
    """Bags whose canonical current-cycle resolver reports completed."""
    from backend.rinse_veewash_workload import load_canonical_completions_v2

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return set()
    day = as_of_date_et or business_today()
    comps = (
        load_canonical_completions_v2(
            cursor,
            int(organization_id),
            ids,
            selected_date_et=day,
            service_type_by_bag={b: "WF" for b in ids},
        )
        or {}
    )
    out: set[str] = set()
    for bid, comp in comps.items():
        if not isinstance(comp, Mapping):
            continue
        if str(comp.get("effective_status") or "").lower() != "completed":
            continue
        if comp.get("completion_at") is None:
            continue
        nb = normalize_bag_id(bid)
        if nb:
            out.add(nb)
    return out


def registry_stale_completion_review_bags(
    cursor,
    organization_id: int,
    open_bags: Sequence[str],
    *,
    as_of_date_et: date | None = None,
) -> set[str]:
    """Open OI + registry COMPLETED + no valid current-OI completion → Review.

    Does not complete the OI. Does not remove it from Current Workload.
    """
    open_set = {normalize_bag_id(b) for b in open_bags if normalize_bag_id(b)}
    if not open_set:
        return set()
    reg_done = _registry_completed_open_bags(cursor, organization_id, sorted(open_set))
    candidates = open_set & reg_done
    if not candidates:
        return set()
    has_evidence = _bags_with_valid_current_cycle_completion(
        cursor,
        organization_id,
        sorted(candidates),
        as_of_date_et=as_of_date_et,
    )
    return candidates - has_evidence


def get_current_wf_workload(
    cursor,
    organization_id: int,
    *,
    include_received_from_vendor: bool = True,
    as_of_date_et: date | None = None,
) -> dict[str, Any]:
    """Date-free Current Workload from open WF order instances only."""
    from backend.rinse_order_instances import list_open_wf_order_instances
    from backend.rinse_wf_canonical_workload import (
        LIFECYCLE_OPEN,
        _authoritative_hd_bag_ids,
        _review_wf_bag_ids_from_cycles,
    )

    org = int(organization_id)
    open_rows = list_open_wf_order_instances(cursor, org, service_type="WF")
    open_by_bag: dict[str, dict[str, Any]] = {}
    for row in open_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        open_by_bag[bid] = dict(row)

    open_bags = set(open_by_bag.keys())
    # HD exclusion only — never registry/terminal/carry-forward.
    hd_exclude = _authoritative_hd_bag_ids(
        cursor,
        org,
        as_of_date_et or business_today(),
        sorted(open_bags),
        portal_hd_ids=set(),
    )
    for bid in hd_exclude:
        open_by_bag.pop(bid, None)
    open_bags = set(open_by_bag.keys())

    cycle_review = _review_wf_bag_ids_from_cycles(cursor, org, open_bags)
    conflict_review = registry_stale_completion_review_bags(
        cursor,
        org,
        sorted(open_bags),
        as_of_date_et=as_of_date_et,
    )
    review = frozenset(cycle_review | conflict_review)
    pending = frozenset(b for b in open_bags if b not in review)

    items: list[dict[str, Any]] = []
    for bid in sorted(open_bags):
        row = open_by_bag[bid]
        anchor = row.get("cycle_anchor_at")
        rfv = None
        if include_received_from_vendor:
            end = None
            if isinstance(anchor, datetime):
                end = _next_oi_cycle_anchor(cursor, org, bid, anchor)
            rfv = lifecycle_received_from_vendor_at(
                cursor,
                org,
                bid,
                anchor,
                lifecycle_end_exclusive=end,
            )
        in_review = bid in review
        reason_codes: list[str] = []
        if bid in conflict_review:
            reason_codes.append(REVIEW_REGISTRY_STALE_COMPLETED)
        items.append(
            {
                "bag_id": bid,
                "order_instance_id": row.get("order_instance_id"),
                "completed_at": None,
                "cycle_anchor_at": anchor,
                "lifecycle": LIFECYCLE_OPEN,
                "status": OUTCOME_REVIEW_REQUIRED if in_review else OUTCOME_PENDING,
                "review_reason_codes": reason_codes,
                "received_from_vendor_at": rfv,
                "rush_status": row.get("rush_status") or row.get("rush_flag"),
                "customer_name": row.get("customer_name"),
            }
        )

    return {
        "organization_id": org,
        "date_independent": True,
        "pending": pending,
        "review": review,
        "open": frozenset(open_bags),
        "counts": {
            "pending": len(pending),
            "review": len(review),
            "open": len(open_bags),
        },
        "items": items,
        "source": "current_wf_workload_open_oi_v1",
    }


def get_selected_date_wf_completed(
    cursor,
    organization_id: int,
    date_et: date,
) -> dict[str, Any]:
    """Completed reporting for ET date D — OI.completed_at only (no registry)."""
    from backend.rinse_order_instances import list_order_instances_completed_on_date
    from backend.rinse_wf_canonical_workload import (
        LIFECYCLE_COMPLETED,
        _authoritative_hd_bag_ids,
    )

    org = int(organization_id)
    rows = list_order_instances_completed_on_date(
        cursor, org, date_et, service_type="WF"
    )
    by_bag: dict[str, dict[str, Any]] = {}
    for row in rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        # Prefer latest completed OI if multiple on same day (reusable edge).
        prev = by_bag.get(bid)
        if prev is None or int(row.get("order_instance_id") or 0) >= int(
            prev.get("order_instance_id") or 0
        ):
            by_bag[bid] = dict(row)

    bag_ids = set(by_bag.keys())
    hd_exclude = _authoritative_hd_bag_ids(
        cursor, org, date_et, sorted(bag_ids), portal_hd_ids=set()
    )
    for bid in hd_exclude:
        by_bag.pop(bid, None)
    bag_ids = set(by_bag.keys())

    completed = frozenset(bag_ids)
    items: list[dict[str, Any]] = []
    completion_by_bag: dict[str, dict[str, Any]] = {}
    for bid in sorted(bag_ids):
        row = by_bag[bid]
        ca = row.get("completed_at")
        completion_by_bag[bid] = {
            "completion_date": date_et,
            "completion_at": ca,
            "effective_status": "completed",
            "completion_source": row.get("completion_source") or "order_instance",
            "order_instance_id": row.get("order_instance_id"),
        }
        items.append(
            {
                "bag_id": bid,
                "order_instance_id": row.get("order_instance_id"),
                "completed_at": ca,
                "completed_date_et": date_et.isoformat(),
                "lifecycle": LIFECYCLE_COMPLETED,
                "completion_source": row.get("completion_source") or "order_instance",
                "received_from_vendor_at": lifecycle_received_from_vendor_at(
                    cursor,
                    org,
                    bid,
                    row.get("cycle_anchor_at"),
                    lifecycle_end_exclusive=(
                        _next_oi_cycle_anchor(
                            cursor, org, bid, row["cycle_anchor_at"]
                        )
                        if isinstance(row.get("cycle_anchor_at"), datetime)
                        else None
                    ),
                ),
            }
        )

    return {
        "organization_id": org,
        "date_et": date_et.isoformat(),
        "completed": completed,
        "counts": {"completed": len(completed)},
        "items": items,
        "completion_by_bag": completion_by_bag,
        "source": "selected_date_wf_completed_oi_v1",
    }
