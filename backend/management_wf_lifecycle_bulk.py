"""Management/API read-path bulk loaders for WF lifecycle enrichment.

Read-only. Does not create/stamp OIs, alter STV windows, or touch scrape paths.
Used only when Management/Performance opt into ``use_bulk_reads=True``.

Parity target: identical results to per-bag ``_next_oi_cycle_anchor`` and
``lifecycle_received_from_vendor_at`` / ``_load_bag_timeline``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists

# (bag_id, cycle_anchor_at) → next cycle_anchor_at or None
NextAnchorMap = dict[tuple[str, datetime], datetime | None]
TimelineMap = dict[str, list[dict[str, Any]]]
RfvScanMap = dict[str, list[dict[str, Any]]]


def _as_naive_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    return None


def bulk_load_next_oi_anchors(
    cursor,
    organization_id: int,
    oi_keys: Sequence[tuple[str, datetime]],
) -> NextAnchorMap:
    """Bulk equivalent of ``_next_oi_cycle_anchor`` for many (bag, anchor) keys.

    Does **not** run CREATE TABLE. Table must already exist (production / write
    paths ensure it).
    """
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE

    out: NextAnchorMap = {}
    keys: list[tuple[str, datetime]] = []
    for bid_raw, anchor in oi_keys:
        bid = normalize_bag_id(bid_raw)
        anc = _as_naive_dt(anchor)
        if not bid or anc is None:
            continue
        keys.append((bid, anc))
        out[(bid, anc)] = None
    if not keys:
        return out
    if not table_exists(cursor, ORDER_INSTANCES_TABLE):
        return out

    bags = sorted({b for b, _ in keys})
    org = int(organization_id)
    # All WF anchors for these bags — derive next-in-memory (same ORDER BY as
    # single-bag LIMIT 1 lookup).
    by_bag: dict[str, list[datetime]] = {b: [] for b in bags}
    chunk = 200
    for i in range(0, len(bags), chunk):
        part = bags[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, cycle_anchor_at
            FROM {ORDER_INSTANCES_TABLE}
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND service_type = 'WF'
            ORDER BY bag_id ASC, cycle_anchor_at ASC
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            anc = _as_naive_dt(row.get("cycle_anchor_at"))
            if bid and anc is not None and bid in by_bag:
                by_bag[bid].append(anc)

    for bid, anc in keys:
        nxt = None
        for cand in by_bag.get(bid) or []:
            if cand > anc:
                nxt = cand
                break
        out[(bid, anc)] = nxt
    return out


def bulk_load_lifecycle_rfv_scan_rows(
    cursor,
    organization_id: int,
    bag_min_anchors: Mapping[str, datetime],
) -> RfvScanMap:
    """Bulk rows matching ``lifecycle_received_from_vendor_at`` per-bag SELECT.

    For each bag, loads ``purpose, scanned_at_parsed, id`` with
    ``scanned_at_parsed >= that bag's min cycle_anchor`` (same predicate as the
    single-bag query). Callers still filter STV by lifecycle window in
    ``lifecycle_received_from_vendor_at(..., preloaded_rows=...)``.
    """
    out: RfvScanMap = {}
    items: list[tuple[str, datetime]] = []
    for bid_raw, anc in (bag_min_anchors or {}).items():
        bid = normalize_bag_id(bid_raw)
        a = _as_naive_dt(anc)
        if bid and a is not None:
            items.append((bid, a))
            out[bid] = []
    if not items:
        return out
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return out

    org = int(organization_id)
    # Global floor so one IN query covers all bags; per-bag filter restores
    # exact single-bag ``scanned_at_parsed >= anchor`` semantics.
    global_floor = min(a for _, a in items)
    bags = sorted({b for b, _ in items})
    min_by_bag = {b: a for b, a in items}
    chunk = 200
    for i in range(0, len(bags), chunk):
        part = bags[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose, scanned_at_parsed, id
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed >= %s
            ORDER BY bag_id ASC, scanned_at_parsed ASC, id ASC
            """,
            (org, *part, global_floor),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            ts = _as_naive_dt(row.get("scanned_at_parsed"))
            if not bid or ts is None or bid not in min_by_bag:
                continue
            if ts < min_by_bag[bid]:
                continue
            out.setdefault(bid, []).append(
                {
                    "purpose": row.get("purpose"),
                    "scanned_at_parsed": ts,
                    "id": row.get("id"),
                }
            )
    return out


def bulk_load_bag_timelines(
    cursor,
    organization_id: int,
    bag_ids: Iterable[str],
) -> TimelineMap:
    """Bulk equivalent of ``_load_bag_timeline``."""
    bags = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: TimelineMap = {b: [] for b in bags}
    if not bags:
        return out
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    org = int(organization_id)
    chunk = 200
    for i in range(0, len(bags), chunk):
        part = bags[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose, scanned_at_parsed, time_scanned_raw, user_name,
                   weight_lbs, rack, source_filename, raw_json
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed IS NOT NULL
            ORDER BY bag_id ASC, scanned_at_parsed ASC, id ASC
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid or bid not in out:
                continue
            out[bid].append(dict(row))
    return out


def bulk_load_wf_order_instances_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """All WF OIs for bags — for Performance folder OI resolution (no DDL)."""
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE

    bags = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in bags}
    if not bags or not table_exists(cursor, ORDER_INSTANCES_TABLE):
        return out
    org = int(organization_id)
    chunk = 200
    for i in range(0, len(bags), chunk):
        part = bags[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT order_instance_id, bag_id, cycle_anchor_at, completed_at, completion_source
            FROM {ORDER_INSTANCES_TABLE}
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND service_type = 'WF'
            ORDER BY bag_id ASC, order_instance_id ASC
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if bid and bid in out:
                out[bid].append(dict(row))
    return out
