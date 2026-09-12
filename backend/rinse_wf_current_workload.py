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
    preloaded_rows: Sequence[Mapping[str, Any]] | None = None,
) -> datetime | None:
    """Latest purpose=sent-to-vendor scan in this OI lifecycle window.

    Window: [cycle_anchor_at, lifecycle_end_exclusive).
    ``lifecycle_end_exclusive`` should be the next OI's cycle_anchor_at when
    known; otherwise open-ended (do not cut on every subsequent STV).
    Never uses lifetime MAX(bag_id) across reusable-bag history.

    When ``preloaded_rows`` is provided (Management bulk read), SQL is skipped;
    rows must already match the single-bag SELECT shape/filter.
    """
    bid = normalize_bag_id(bag_id)
    if not bid or cycle_anchor_at is None:
        return None
    if not isinstance(cycle_anchor_at, datetime):
        return None
    if preloaded_rows is None:
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
    else:
        rows = [dict(r) for r in preloaded_rows if isinstance(r, Mapping)]
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


# Process-local flag unused for default scrape path (still ensures when asked).
_OI_TABLE_ENSURED_THIS_PROCESS = False


def _next_oi_cycle_anchor(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime,
    *,
    ensure_schema: bool = True,
) -> datetime | None:
    """Next WF OI cycle_anchor_at for the same bag after this lifecycle (exclusive end).

    ``ensure_schema`` defaults True for scrape/stamp callers (unchanged).
    Management bulk reads pass False to avoid per-OI DDL.
    """
    global _OI_TABLE_ENSURED_THIS_PROCESS
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE, ensure_rinse_order_instances_table

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    if ensure_schema:
        ensure_rinse_order_instances_table(cursor)
        _OI_TABLE_ENSURED_THIS_PROCESS = True
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
    next_anchors: Mapping[tuple[str, datetime], datetime | None] | None = None,
    timelines_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ensure_schema: bool = True,
    registry_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> set[str]:
    """Review only for same-lifecycle registry contradiction without evidence.

    Historical bag-scoped registry (completed_at < OI anchor) is ignored.
    Same-lifecycle canonical/v2 evidence → not Review (OI should be stamped).
    ``resolve_current_cycle`` is never used here.
    ``as_of_date_et`` is ignored (compat kwarg).

    Management bulk path (``use_bulk_reads``): pass ``next_anchors`` /
    ``timelines_by_bag`` and optionally ``registry_by_bag``, or omit registry
    preload to load once via ``get_registry_rows_for_bags`` for all open bags.
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

    # One registry preload when Management bulk path is active (next_anchors
    # and/or ensure_schema=False). Avoids per-bag ensure+SELECT N+1.
    reg_map: Mapping[str, Mapping[str, Any]] | None = registry_by_bag
    use_bulk_registry = reg_map is not None or next_anchors is not None or not ensure_schema
    if reg_map is None and use_bulk_registry:
        from backend.rinse_bag_registry import get_registry_rows_for_bags

        reg_map = get_registry_rows_for_bags(
            cursor, int(organization_id), sorted(open_set)
        )

    review: set[str] = set()
    for row in rows:
        bid = normalize_bag_id(row.get("bag_id"))
        anchor = row.get("cycle_anchor_at")
        if not bid or not isinstance(anchor, datetime):
            continue
        if next_anchors is not None:
            end = next_anchors.get((bid, anchor))
        else:
            end = _next_oi_cycle_anchor(
                cursor,
                int(organization_id),
                bid,
                anchor,
                ensure_schema=ensure_schema,
            )
        if reg_map is not None:
            raw_reg = reg_map.get(bid)
            reg = dict(raw_reg) if isinstance(raw_reg, Mapping) else None
        else:
            reg = _registry_row_for_bag(cursor, int(organization_id), bid)
        if not _registry_completed_at_in_oi_window(reg, anchor, end):
            # Historical or non-completed registry → zero CW effect.
            continue
        tl = None
        if timelines_by_bag is not None:
            tl = timelines_by_bag.get(bid)
        evidence = evaluate_oi_lifecycle_completion_evidence(
            cursor,
            int(organization_id),
            bag_id=bid,
            cycle_anchor_at=anchor,
            lifecycle_end_exclusive=end,
            timeline=tl,
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
    use_bulk_reads: bool = False,
) -> dict[str, Any]:
    """Date-free Current Workload from open WF order instances only.

    ``as_of_date_et`` is ignored — CW never depends on the selected reporting day.
    ``use_bulk_reads`` (Management/API only): batch next-anchor + RFV/scan loads.
    Default False preserves scrape/stamp call-site SQL behavior.
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

    next_anchors = None
    rfv_rows_by_bag = None
    timelines_by_bag = None
    if use_bulk_reads and flat_rows:
        from backend.management_wf_lifecycle_bulk import (
            bulk_load_bag_timelines,
            bulk_load_lifecycle_rfv_scan_rows,
            bulk_load_next_oi_anchors,
        )

        oi_keys: list[tuple[str, datetime]] = []
        min_anchor_by_bag: dict[str, datetime] = {}
        for row in flat_rows:
            bid = normalize_bag_id(row.get("bag_id"))
            anchor = row.get("cycle_anchor_at")
            if not bid or not isinstance(anchor, datetime):
                continue
            oi_keys.append((bid, anchor))
            prev = min_anchor_by_bag.get(bid)
            if prev is None or anchor < prev:
                min_anchor_by_bag[bid] = anchor
        next_anchors = bulk_load_next_oi_anchors(cursor, org, oi_keys)
        if include_received_from_vendor:
            rfv_rows_by_bag = bulk_load_lifecycle_rfv_scan_rows(
                cursor, org, min_anchor_by_bag
            )
        timelines_by_bag = bulk_load_bag_timelines(cursor, org, sorted(open_bags))

    cycle_review = _review_wf_bag_ids_from_cycles(cursor, org, open_bags)
    conflict_review = registry_stale_completion_review_bags(
        cursor,
        org,
        sorted(open_bags),
        open_oi_rows=flat_rows,
        next_anchors=next_anchors,
        timelines_by_bag=timelines_by_bag,
        ensure_schema=not use_bulk_reads,
    )
    from backend.rinse_wf_disappeared_from_portal import (
        REASON_DISAPPEARED_FROM_PORTAL,
    )
    from backend.management_wf_review_cache import (
        get_qualified_disappeared_from_portal,
    )

    disappeared_ctx = get_qualified_disappeared_from_portal(
        cursor, org, flat_rows
    )
    disappeared_review = frozenset(disappeared_ctx.keys())
    review = frozenset(cycle_review | conflict_review | disappeared_review)
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
                    if next_anchors is not None:
                        end = next_anchors.get((bid, anchor))
                    else:
                        end = _next_oi_cycle_anchor(cursor, org, bid, anchor)
                rfv = lifecycle_received_from_vendor_at(
                    cursor,
                    org,
                    bid,
                    anchor,
                    lifecycle_end_exclusive=end,
                    preloaded_rows=(
                        (rfv_rows_by_bag or {}).get(bid)
                        if rfv_rows_by_bag is not None
                        else None
                    ),
                )
            in_review = bid in review
            reason_codes: list[str] = []
            if bid in conflict_review:
                reason_codes.append(REVIEW_REGISTRY_STALE_COMPLETED)
            if bid in disappeared_review:
                reason_codes.append(REASON_DISAPPEARED_FROM_PORTAL)
            dctx = disappeared_ctx.get(bid) or {}
            item: dict[str, Any] = {
                "bag_id": bid,
                "order_instance_id": row.get("order_instance_id"),
                "completed_at": None,
                "cycle_anchor_at": anchor,
                "lifecycle": LIFECYCLE_OPEN,
                "status": OUTCOME_REVIEW_REQUIRED if in_review else OUTCOME_PENDING,
                "review_reason_codes": reason_codes,
                "received_from_vendor_at": rfv,
                "rush_status": row.get("rush_status") or row.get("rush_flag"),
                "customer_name": row.get("customer_name") or dctx.get("customer_name"),
            }
            if dctx:
                item["disappeared_from_portal"] = {
                    "last_seen_at": dctx.get("last_seen_at"),
                    "last_present_run_id": dctx.get("last_present_run_id"),
                    "first_absent_run_id": dctx.get("first_absent_run_id"),
                    "reason_label": dctx.get("reason_label"),
                }
            items.append(item)

    if items:
        from backend.rinse_employee_productivity_sessions import (
            resolve_customer_names_for_bags,
        )

        items = resolve_customer_names_for_bags(
            cursor,
            org,
            items,
            selected_date_et=None,
        )

    payload = {
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

    # Soft manager overlay (manual review / exclude) — does not change OI open set.
    try:
        from backend.management_wf_cw_controls import (
            apply_cw_manager_overlay,
            bulk_load_active_cw_overrides,
        )

        overrides = bulk_load_active_cw_overrides(cursor, org, sorted(open_bags))
        payload = apply_cw_manager_overlay(payload, overrides)
    except Exception:
        # Presentation overlay must never break CW authority reads.
        pass

    return payload


def get_selected_date_wf_completed(
    cursor,
    organization_id: int,
    date_et: date,
    *,
    use_bulk_reads: bool = False,
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

    next_anchors = None
    rfv_rows_by_bag = None
    if use_bulk_reads and by_bag:
        from backend.management_wf_lifecycle_bulk import (
            bulk_load_lifecycle_rfv_scan_rows,
            bulk_load_next_oi_anchors,
        )

        oi_keys: list[tuple[str, datetime]] = []
        min_anchor_by_bag: dict[str, datetime] = {}
        for bid, row in by_bag.items():
            anchor = row.get("cycle_anchor_at")
            if not isinstance(anchor, datetime):
                continue
            oi_keys.append((bid, anchor))
            min_anchor_by_bag[bid] = anchor
        next_anchors = bulk_load_next_oi_anchors(cursor, org, oi_keys)
        rfv_rows_by_bag = bulk_load_lifecycle_rfv_scan_rows(
            cursor, org, min_anchor_by_bag
        )

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
        anchor = row.get("cycle_anchor_at")
        end = None
        if isinstance(anchor, datetime):
            if next_anchors is not None:
                end = next_anchors.get((bid, anchor))
            else:
                end = _next_oi_cycle_anchor(cursor, org, bid, anchor)
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
                    anchor,
                    lifecycle_end_exclusive=end,
                    preloaded_rows=(
                        (rfv_rows_by_bag or {}).get(bid)
                        if rfv_rows_by_bag is not None
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
