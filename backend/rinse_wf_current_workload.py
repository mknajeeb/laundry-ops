"""WF Current Workload — open order-instance authority (date-free).

Current Workload = every legitimate open WF OI (``completed_at IS NULL``).

Selected-date Completed is a separate concept (see get_selected_date_wf_completed).
Registry / day-bag / Performance COMPLETED never removes an open OI.
Conflict evidence is OI/lifecycle-scoped — never selected-date reporting.
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


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return datetime(raw.year, raw.month, raw.day)
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")[:19])
    except ValueError:
        return None


def _load_bag_timeline(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[dict[str, Any]]:
    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT purpose, scanned_at_parsed, time_scanned_raw, user_name,
               weight_lbs, rack, source_filename, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
          AND scanned_at_parsed IS NOT NULL
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), bid),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _events_in_oi_lifecycle_window(
    timeline: Sequence[Mapping[str, Any]],
    cycle_anchor_at: datetime,
    lifecycle_end_exclusive: datetime | None,
) -> list[dict[str, Any]]:
    """Events in [OI anchor, next OI anchor). Never cut on intra-lifecycle STV."""
    out: list[dict[str, Any]] = []
    for ev in timeline:
        ts = ev.get("scanned_at_parsed")
        if not isinstance(ts, datetime):
            continue
        if ts < cycle_anchor_at:
            continue
        if lifecycle_end_exclusive is not None and ts >= lifecycle_end_exclusive:
            continue
        out.append(dict(ev))
    return out


def evaluate_oi_lifecycle_completion_evidence(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    cycle_anchor_at: datetime,
    lifecycle_end_exclusive: datetime | None = None,
    timeline: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Canonical/v2 completion evidence inside one OI lifecycle window.

    Reuses existing clean-rack + strong/QC signals (``evaluate_bag_completion_v2``
    and classic clean-rack). Does **not** use ``resolve_current_cycle`` (that
    truncates at the next STV and misses same-lifecycle production completion).
    """
    from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
    from backend.rinse_bag_completion import (
        COMPLETION_COMPLETED as CLASSIC_COMPLETED,
        evaluate_bag_completion,
    )
    from backend.rinse_bag_stage_bounds import gaming_events_from_records

    bid = normalize_bag_id(bag_id)
    if not bid or not isinstance(cycle_anchor_at, datetime):
        return None
    tl = list(timeline) if timeline is not None else _load_bag_timeline(
        cursor, organization_id, bid
    )
    scoped = _events_in_oi_lifecycle_window(
        tl, cycle_anchor_at, lifecycle_end_exclusive
    )
    if not scoped:
        return None

    v2 = evaluate_bag_completion_v2(gaming_events_from_records(scoped))
    if (
        v2.completed
        and isinstance(v2.completion_at, datetime)
        and v2.completion_at >= cycle_anchor_at
        and (
            lifecycle_end_exclusive is None
            or v2.completion_at < lifecycle_end_exclusive
        )
    ):
        return {
            "completed": True,
            "completion_at": v2.completion_at,
            "completion_kind": v2.completion_kind,
            "completion_user": v2.completion_user,
            "via_clean_rack": bool(v2.via_clean_rack),
            "evidence_family": "v2",
        }

    classic = evaluate_bag_completion(scoped)
    classic_at = classic.trigger_scan_at or classic.first_clean_scan_at
    if (
        str(classic.completion_status or "").upper() == CLASSIC_COMPLETED
        and isinstance(classic_at, datetime)
        and classic_at >= cycle_anchor_at
        and (
            lifecycle_end_exclusive is None or classic_at < lifecycle_end_exclusive
        )
    ):
        return {
            "completed": True,
            "completion_at": classic_at,
            "completion_kind": classic.trigger_kind or classic.completion_reason,
            "completion_user": None,
            "via_clean_rack": str(classic.completion_reason or "").upper()
            == "CLEAN_RACK_SCANNED"
            or str(classic.trigger_kind or "").upper() == "CLEAN_RACK",
            "evidence_family": "classic",
        }
    return None


def _oi_has_valid_lifecycle_completion(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    cycle_anchor_at: datetime,
    lifecycle_end_exclusive: datetime | None = None,
) -> bool:
    """True when canonical/v2 completion exists inside this OI window."""
    return (
        evaluate_oi_lifecycle_completion_evidence(
            cursor,
            organization_id,
            bag_id=bag_id,
            cycle_anchor_at=cycle_anchor_at,
            lifecycle_end_exclusive=lifecycle_end_exclusive,
        )
        is not None
    )


def _registry_row_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
) -> dict[str, Any] | None:
    from backend.rinse_bag_registry import get_registry_rows_for_bags

    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_bag_registry"):
        return None
    rows = get_registry_rows_for_bags(cursor, int(organization_id), [bid]) or {}
    row = rows.get(bid)
    return dict(row) if isinstance(row, dict) else None


def _registry_completed_at_in_oi_window(
    registry_row: Mapping[str, Any] | None,
    cycle_anchor_at: datetime,
    lifecycle_end_exclusive: datetime | None,
) -> bool:
    """True when bag registry completion timestamp belongs to this OI window.

    Historical registry (completed_at < OI anchor) → False (ignore for CW).
    """
    if not registry_row:
        return False
    if (
        str(registry_row.get("completion_status") or "").strip().upper()
        != COMPLETION_COMPLETED
    ):
        return False
    reg_at = _parse_dt(registry_row.get("completed_at"))
    if reg_at is None or not isinstance(cycle_anchor_at, datetime):
        return False
    if reg_at < cycle_anchor_at:
        return False
    if lifecycle_end_exclusive is not None and reg_at >= lifecycle_end_exclusive:
        return False
    return True


def registry_stale_completion_review_bags(
    cursor,
    organization_id: int,
    open_bags: Sequence[str],
    *,
    open_oi_rows: Sequence[Mapping[str, Any]] | None = None,
    as_of_date_et: date | None = None,
) -> set[str]:
    """Review only for same-lifecycle registry contradiction without evidence.

    Historical bag-scoped registry (completed_at < OI anchor) is ignored.
    Same-lifecycle canonical/v2 evidence → not Review (OI should be stamped).
    ``resolve_current_cycle`` is never used here.
    ``as_of_date_et`` is ignored (compat kwarg).
    """
    _ = as_of_date_et
    open_set = {normalize_bag_id(b) for b in open_bags if normalize_bag_id(b)}
    if not open_set:
        return set()
    rows = [
        r
        for r in (open_oi_rows or [])
        if normalize_bag_id((r or {}).get("bag_id")) in open_set
    ]
    if not rows:
        from backend.rinse_order_instances import list_open_wf_order_instances

        rows = [
            r
            for r in list_open_wf_order_instances(cursor, int(organization_id))
            if normalize_bag_id(r.get("bag_id")) in open_set
        ]

    review: set[str] = set()
    for row in rows:
        bid = normalize_bag_id(row.get("bag_id"))
        anchor = row.get("cycle_anchor_at")
        if not bid or not isinstance(anchor, datetime):
            continue
        end = _next_oi_cycle_anchor(cursor, int(organization_id), bid, anchor)
        reg = _registry_row_for_bag(cursor, int(organization_id), bid)
        if not _registry_completed_at_in_oi_window(reg, anchor, end):
            # Historical or non-completed registry → zero CW effect.
            continue
        evidence = evaluate_oi_lifecycle_completion_evidence(
            cursor,
            int(organization_id),
            bag_id=bid,
            cycle_anchor_at=anchor,
            lifecycle_end_exclusive=end,
        )
        if evidence is not None:
            # Evidence exists → complete via stamp path; not Review.
            continue
        # Same-lifecycle registry claim without canonical/v2 evidence.
        review.add(bid)
    return review


def get_current_wf_workload(
    cursor,
    organization_id: int,
    *,
    include_received_from_vendor: bool = True,
    as_of_date_et: date | None = None,
) -> dict[str, Any]:
    """Date-free Current Workload from open WF order instances only.

    ``as_of_date_et`` is ignored — CW never depends on the selected reporting day.
    """
    _ = as_of_date_et
    from backend.rinse_order_instances import list_open_wf_order_instances
    from backend.rinse_wf_canonical_workload import (
        LIFECYCLE_OPEN,
        _authoritative_hd_bag_ids,
        _review_wf_bag_ids_from_cycles,
    )

    org = int(organization_id)
    open_rows = list_open_wf_order_instances(cursor, org, service_type="WF")
    # Prefer STV-backed / earliest open OI per bag for bag-level sets; keep all
    # open OIs as items after HD filter.
    rows_by_bag: dict[str, list[dict[str, Any]]] = {}
    for row in open_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        rows_by_bag.setdefault(bid, []).append(dict(row))

    open_bags = set(rows_by_bag.keys())
    # HD exclusion uses business_today only — never selected reporting date.
    hd_exclude = _authoritative_hd_bag_ids(
        cursor,
        org,
        business_today(),
        sorted(open_bags),
        portal_hd_ids=set(),
    )
    for bid in hd_exclude:
        rows_by_bag.pop(bid, None)
    open_bags = set(rows_by_bag.keys())

    flat_rows = [r for rows in rows_by_bag.values() for r in rows]
    cycle_review = _review_wf_bag_ids_from_cycles(cursor, org, open_bags)
    conflict_review = registry_stale_completion_review_bags(
        cursor,
        org,
        sorted(open_bags),
        open_oi_rows=flat_rows,
    )
    review = frozenset(cycle_review | conflict_review)
    pending = frozenset(b for b in open_bags if b not in review)

    items: list[dict[str, Any]] = []
    for bid in sorted(open_bags):
        for row in sorted(
            rows_by_bag[bid],
            key=lambda r: (
                r.get("cycle_anchor_at") or datetime.min,
                int(r.get("order_instance_id") or 0),
            ),
        ):
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

    # Bag-level equation: one bag → one pending/review membership.
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
