"""Canonical Rinse WF service-cycle lifecycle.

ADMIT ONCE → ACTIVE across days → COMPLETE ONCE (or REVIEW → resolution).

Midnight has zero effect. day_bags are a downstream compatibility projection only.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_cycle_boundary import resolve_current_cycle
from backend.rinse_current_cycle_weight import resolve_current_cycle_weights
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.ta_helpers import table_exists

STATUS_ACTIVE = "ACTIVE"
STATUS_REVIEW = "REVIEW"
STATUS_COMPLETED = "COMPLETED"
STATUS_RESOLVED_OTHER = "RESOLVED_OTHER"

REVIEW_MISSING_FROM_PORTAL = "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"


def ensure_wf_service_cycles_table(cursor) -> None:
    if table_exists(cursor, "rinse_wf_service_cycles"):
        return
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parent / "sql" / "rinse_wf_service_cycles_v1.sql"
    ).read_text()
    for stmt in sql.split(";"):
        s = stmt.strip()
        if s:
            cursor.execute(s)


def _norm_bag(raw: Any) -> str:
    return normalize_bag_id(raw) or ""


def _load_timeline(cursor, organization_id: int, bag_id: str) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cur = cursor
    cur.execute(
        """
        SELECT bag_id, rack, purpose, scanned_at_parsed, user_name, weight_lbs,
               weight_role, source_filename, raw_json, scan_index, id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
          AND scanned_at_parsed IS NOT NULL
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        """,
        (int(organization_id), bag_id),
    )
    return [dict(r) for r in (cur.fetchall() or []) if isinstance(r, dict)]


def _valid_cycle_anchors(timeline: Sequence[Mapping[str, Any]]) -> list[datetime]:
    from backend.rinse_cycle_boundary import resolve_cycle_anchor

    anchors: list[datetime] = []
    seen: set[datetime] = set()
    if not timeline:
        return anchors
    dates = sorted({d for d in (_event_date(ev) for ev in timeline) if d is not None})
    for d in dates:
        anchor = resolve_cycle_anchor(timeline, selected_date_et=d)
        if anchor is not None and anchor not in seen:
            seen.add(anchor)
            anchors.append(anchor)
    anchors.sort()
    return anchors


def _event_date(ev: Mapping[str, Any]) -> date | None:
    from backend.rinse_cycle_boundary import _event_ts

    ts = _event_ts(ev)
    return ts.date() if ts is not None else None


def _cycle_resolution(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime,
    *,
    selected_date_et: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    timeline = _load_timeline(cursor, organization_id, bag_id)
    day = selected_date_et or cycle_anchor_at.date()
    cycle = resolve_current_cycle(
        timeline,
        selected_date_et=day,
        cycle_anchor_override=cycle_anchor_at,
    )
    weights = resolve_current_cycle_weights(
        timeline,
        selected_date_et=day,
        cycle_anchor_override=cycle_anchor_at,
    ).as_weight_info()
    return cycle.as_dict(), weights


def get_cycle_by_key(
    cursor, organization_id: int, bag_id: str, cycle_anchor_at: datetime
) -> dict[str, Any] | None:
    ensure_wf_service_cycles_table(cursor)
    cur = cursor
    cur.execute(
        """
        SELECT * FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND bag_id = %s AND cycle_anchor_at = %s
        LIMIT 1
        """,
        (int(organization_id), _norm_bag(bag_id), cycle_anchor_at),
    )
    row = cur.fetchone()
    return dict(row) if isinstance(row, dict) else None


def get_active_cycle_for_bag(
    cursor, organization_id: int, bag_id: str
) -> dict[str, Any] | None:
    ensure_wf_service_cycles_table(cursor)
    cur = cursor
    cur.execute(
        """
        SELECT * FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND bag_id = %s
          AND status IN (%s, %s)
        ORDER BY cycle_anchor_at DESC
        LIMIT 1
        """,
        (int(organization_id), _norm_bag(bag_id), STATUS_ACTIVE, STATUS_REVIEW),
    )
    row = cur.fetchone()
    return dict(row) if isinstance(row, dict) else None


def upsert_service_cycle(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    cycle_anchor_at: datetime,
    admitted_at: datetime,
    admitted_source: str,
    status: str,
    completed_at: datetime | None = None,
    completion_source: str | None = None,
    rush_status: str | None = None,
    estimated_delivery_date: date | None = None,
    pre_weight_lbs: float | None = None,
    post_weight_lbs: float | None = None,
    review_reason: str | None = None,
    portal_last_seen_at: datetime | None = None,
    disappeared_at: datetime | None = None,
) -> dict[str, Any]:
    ensure_wf_service_cycles_table(cursor)
    bid = _norm_bag(bag_id)
    ticket_uid = bid
    org = int(organization_id)
    cur = cursor
    cur.execute(
        """
        INSERT INTO rinse_wf_service_cycles (
          organization_id, bag_id, ticket_uid, cycle_anchor_at, admitted_at,
          admitted_source, status, completed_at, completion_source,
          rush_status, estimated_delivery_date, pre_weight_lbs, post_weight_lbs,
          review_reason, portal_last_seen_at, disappeared_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          admitted_at = LEAST(rinse_wf_service_cycles.admitted_at, VALUES(admitted_at)),
          status = IF(
            rinse_wf_service_cycles.status = %s,
            rinse_wf_service_cycles.status,
            VALUES(status)
          ),
          completed_at = COALESCE(VALUES(completed_at), rinse_wf_service_cycles.completed_at),
          completion_source = COALESCE(VALUES(completion_source), rinse_wf_service_cycles.completion_source),
          rush_status = COALESCE(VALUES(rush_status), rinse_wf_service_cycles.rush_status),
          estimated_delivery_date = COALESCE(VALUES(estimated_delivery_date), rinse_wf_service_cycles.estimated_delivery_date),
          pre_weight_lbs = COALESCE(VALUES(pre_weight_lbs), rinse_wf_service_cycles.pre_weight_lbs),
          post_weight_lbs = COALESCE(VALUES(post_weight_lbs), rinse_wf_service_cycles.post_weight_lbs),
          review_reason = COALESCE(VALUES(review_reason), rinse_wf_service_cycles.review_reason),
          portal_last_seen_at = COALESCE(VALUES(portal_last_seen_at), rinse_wf_service_cycles.portal_last_seen_at),
          disappeared_at = COALESCE(VALUES(disappeared_at), rinse_wf_service_cycles.disappeared_at),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            org,
            bid,
            ticket_uid,
            cycle_anchor_at,
            admitted_at,
            admitted_source,
            status,
            completed_at,
            completion_source,
            rush_status,
            estimated_delivery_date,
            pre_weight_lbs,
            post_weight_lbs,
            review_reason,
            portal_last_seen_at,
            disappeared_at,
            STATUS_COMPLETED,
        ),
    )
    row = get_cycle_by_key(cursor, org, bid, cycle_anchor_at)
    return row or {}


def _apply_resolution_to_cycle_row(
    cycle_row: dict[str, Any],
    cycle: Mapping[str, Any],
    weights: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(cycle_row.get("status") or STATUS_ACTIVE)
    completed_at = cycle_row.get("completed_at")
    completion_source = cycle_row.get("completion_source")
    if str(cycle.get("effective_status") or "").lower() == "completed":
        comp_ts = cycle.get("completion_at")
        if comp_ts:
            if isinstance(comp_ts, str):
                completed_at = datetime.fromisoformat(comp_ts.replace("Z", "")[:19])
            elif isinstance(comp_ts, datetime):
                completed_at = comp_ts
            status = STATUS_COMPLETED
            completion_source = cycle.get("completion_source")
    pre = weights.get("pre_weight_lbs")
    post = weights.get("post_weight_lbs")
    return {
        **cycle_row,
        "status": status,
        "completed_at": completed_at,
        "completion_source": completion_source,
        "pre_weight_lbs": pre if pre is not None else cycle_row.get("pre_weight_lbs"),
        "post_weight_lbs": post if post is not None else cycle_row.get("post_weight_lbs"),
    }


def admit_or_update_cycle_from_evidence(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime,
    *,
    admitted_at: datetime | None = None,
    admitted_source: str = "DURABLE_EVIDENCE",
    portal_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent admit/update for one service occurrence."""
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    admitted = admitted_at or cycle_anchor_at
    existing = get_cycle_by_key(cursor, org, bid, cycle_anchor_at)
    if existing and str(existing.get("status")) == STATUS_COMPLETED:
        # Completed cycles are immutable except manager review resolution path.
        cycle_dict, weights = _cycle_resolution(cursor, org, bid, cycle_anchor_at)
        return upsert_service_cycle(
            cursor,
            org,
            bag_id=bid,
            cycle_anchor_at=cycle_anchor_at,
            admitted_at=existing.get("admitted_at") or admitted,
            admitted_source=str(existing.get("admitted_source") or admitted_source),
            status=STATUS_COMPLETED,
            completed_at=existing.get("completed_at"),
            completion_source=existing.get("completion_source"),
            rush_status=(portal_meta or {}).get("rush_flag") or existing.get("rush_status"),
            estimated_delivery_date=(portal_meta or {}).get("estimated_delivery_date")
            or existing.get("estimated_delivery_date"),
            pre_weight_lbs=existing.get("pre_weight_lbs"),
            post_weight_lbs=existing.get("post_weight_lbs"),
            portal_last_seen_at=(portal_meta or {}).get("last_seen_at")
            or existing.get("portal_last_seen_at"),
        )

    cycle_dict, weights = _cycle_resolution(cursor, org, bid, cycle_anchor_at)
    status = STATUS_ACTIVE
    completed_at = None
    completion_source = None
    if str(cycle_dict.get("effective_status") or "").lower() == "completed":
        status = STATUS_COMPLETED
        comp_raw = cycle_dict.get("completion_at")
        if comp_raw:
            completed_at = (
                datetime.fromisoformat(str(comp_raw).replace("Z", "")[:19])
                if isinstance(comp_raw, str)
                else comp_raw
            )
        completion_source = cycle_dict.get("completion_source")

    return upsert_service_cycle(
        cursor,
        org,
        bag_id=bid,
        cycle_anchor_at=cycle_anchor_at,
        admitted_at=existing.get("admitted_at") if existing else admitted,
        admitted_source=str((existing or {}).get("admitted_source") or admitted_source),
        status=status,
        completed_at=completed_at,
        completion_source=completion_source,
        rush_status=(portal_meta or {}).get("rush_flag"),
        estimated_delivery_date=(portal_meta or {}).get("estimated_delivery_date"),
        pre_weight_lbs=weights.get("pre_weight_lbs"),
        post_weight_lbs=weights.get("post_weight_lbs"),
        portal_last_seen_at=(portal_meta or {}).get("last_seen_at"),
    )


def reconstruct_cycles_from_durable_evidence(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build canonical cycles from rinse_bag_scan_events (migration/cutover)."""
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    ids = sorted({_norm_bag(b) for b in (bag_ids or []) if _norm_bag(b)})
    if not ids:
        cur = cursor
        cur.execute(
            """
            SELECT DISTINCT bag_id FROM rinse_bag_scan_events
            WHERE organization_id = %s
            """,
            (org,),
        )
        ids = sorted(_norm_bag(r["bag_id"]) for r in (cur.fetchall() or []) if r.get("bag_id"))

    admitted = 0
    completed = 0
    for bid in ids:
        timeline = _load_timeline(cursor, org, bid)
        anchors = _valid_cycle_anchors(timeline)
        if not anchors:
            continue
        for anchor in anchors:
            row = admit_or_update_cycle_from_evidence(
                cursor, org, bid, anchor, admitted_source="MIGRATION_RECONSTRUCT"
            )
            admitted += 1
            if str(row.get("status")) == STATUS_COMPLETED:
                completed += 1
    return {"bags": len(ids), "cycles_upserted": admitted, "completed": completed}


def sync_portal_discovery(
    cursor,
    organization_id: int,
    portal_bags: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """After full At-Vendor traversal: admit new cycles, refresh active ones."""
    org = int(organization_id)
    now_utc = now or datetime.utcnow()
    admitted = updated = 0
    for raw_bid, meta in (portal_bags or {}).items():
        bid = _norm_bag(raw_bid)
        if not bid:
            continue
        svc = str((meta or {}).get("service_type") or "WF").upper()
        if svc not in ("WF", "WASH AND FOLD", "WASH&FOLD"):
            continue
        timeline = _load_timeline(cursor, org, bid)
        anchors = _valid_cycle_anchors(timeline)
        anchor = anchors[-1] if anchors else None
        active = get_active_cycle_for_bag(cursor, org, bid)
        if active and anchor is not None:
            active_anchor = active.get("cycle_anchor_at")
            if (
                isinstance(active_anchor, datetime)
                and anchor > active_anchor
                and str(active.get("status")) == STATUS_COMPLETED
            ):
                admit_or_update_cycle_from_evidence(
                    cursor,
                    org,
                    bid,
                    anchor,
                    admitted_at=now_utc,
                    admitted_source="PORTAL_DISCOVERY",
                    portal_meta=meta,
                )
                admitted += 1
                continue
            if isinstance(active_anchor, datetime) and anchor == active_anchor:
                admit_or_update_cycle_from_evidence(
                    cursor,
                    org,
                    bid,
                    anchor,
                    admitted_source="PORTAL_REDISCOVERY",
                    portal_meta={**(meta or {}), "last_seen_at": now_utc},
                )
                updated += 1
                continue
        if anchor is None:
            # Portal-only admit before first STV: anchor = now, will merge when STV arrives
            anchor = now_utc
        if not get_cycle_by_key(cursor, org, bid, anchor):
            admit_or_update_cycle_from_evidence(
                cursor,
                org,
                bid,
                anchor,
                admitted_at=now_utc,
                admitted_source="PORTAL_DISCOVERY",
                portal_meta={**(meta or {}), "last_seen_at": now_utc},
            )
            admitted += 1
        else:
            admit_or_update_cycle_from_evidence(
                cursor,
                org,
                bid,
                anchor,
                admitted_source="PORTAL_REDISCOVERY",
                portal_meta={**(meta or {}), "last_seen_at": now_utc},
            )
            updated += 1
    return {"admitted": admitted, "updated": updated}


def handle_disappeared_active_cycles(
    cursor,
    organization_id: int,
    portal_bag_ids: set[str],
    *,
    traversal_complete: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """After complete traversal, ACTIVE cycles missing from portal → complete or review."""
    if not traversal_complete:
        return {"skipped": True, "reason": "traversal_incomplete"}
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    now_utc = now or datetime.utcnow()
    portal_norm = {_norm_bag(b) for b in portal_bag_ids if _norm_bag(b)}
    cur = cursor
    cur.execute(
        """
        SELECT * FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND status = %s
        """,
        (org, STATUS_ACTIVE),
    )
    completed = review = 0
    for row in cur.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        if bid in portal_norm:
            continue
        anchor = row.get("cycle_anchor_at")
        if not isinstance(anchor, datetime):
            continue
        cycle_dict, weights = _cycle_resolution(cursor, org, bid, anchor)
        if str(cycle_dict.get("effective_status") or "").lower() == "completed":
            comp_raw = cycle_dict.get("completion_at")
            comp_at = (
                datetime.fromisoformat(str(comp_raw).replace("Z", "")[:19])
                if isinstance(comp_raw, str)
                else comp_raw
            )
            upsert_service_cycle(
                cursor,
                org,
                bag_id=bid,
                cycle_anchor_at=anchor,
                admitted_at=row.get("admitted_at") or anchor,
                admitted_source=str(row.get("admitted_source") or "PORTAL_DISCOVERY"),
                status=STATUS_COMPLETED,
                completed_at=comp_at,
                completion_source=cycle_dict.get("completion_source"),
                pre_weight_lbs=weights.get("pre_weight_lbs") or row.get("pre_weight_lbs"),
                post_weight_lbs=weights.get("post_weight_lbs") or row.get("post_weight_lbs"),
                disappeared_at=now_utc,
            )
            completed += 1
        else:
            upsert_service_cycle(
                cursor,
                org,
                bag_id=bid,
                cycle_anchor_at=anchor,
                admitted_at=row.get("admitted_at") or anchor,
                admitted_source=str(row.get("admitted_source") or "PORTAL_DISCOVERY"),
                status=STATUS_REVIEW,
                review_reason=REVIEW_MISSING_FROM_PORTAL,
                disappeared_at=now_utc,
            )
            review += 1
    return {"completed": completed, "review": review}


def reporting_counts_for_date(
    cursor, organization_id: int, selected_date_et: date
) -> dict[str, Any]:
    """Date-filtered reporting dimensions (not workload = completed + pending)."""
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    day_start = naive_et_day_start(selected_date_et)
    day_end = day_start + timedelta(days=1)
    cur = cursor

    cur.execute(
        """
        SELECT COUNT(*) n FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND admitted_at >= %s AND admitted_at < %s
        """,
        (org, day_start, day_end),
    )
    admitted = int((cur.fetchone() or {}).get("n") or 0)

    cur.execute(
        """
        SELECT COUNT(*) n FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND completed_at >= %s AND completed_at < %s
          AND status = %s
        """,
        (org, day_start, day_end, STATUS_COMPLETED),
    )
    completed = int((cur.fetchone() or {}).get("n") or 0)

    cur.execute(
        """
        SELECT COUNT(*) n FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND status IN (%s, %s)
        """,
        (org, STATUS_ACTIVE, STATUS_REVIEW),
    )
    active_now = int((cur.fetchone() or {}).get("n") or 0)

    cur.execute(
        """
        SELECT COUNT(*) n FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND admitted_at < %s
          AND status IN (%s, %s)
          AND (completed_at IS NULL OR completed_at >= %s)
        """,
        (org, day_start, STATUS_ACTIVE, STATUS_REVIEW, day_start),
    )
    opening_backlog = int((cur.fetchone() or {}).get("n") or 0)

    cur.execute(
        """
        SELECT COUNT(*) n FROM rinse_wf_service_cycles
        WHERE organization_id = %s AND status = %s
        """,
        (org, STATUS_REVIEW),
    )
    review = int((cur.fetchone() or {}).get("n") or 0)

    cur.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(pre_weight_lbs),0) pre_lbs,
               COUNT(post_weight_lbs) post_bags, COALESCE(SUM(post_weight_lbs),0) post_lbs
        FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND (admitted_at < %s OR completed_at >= %s)
          AND pre_weight_lbs IS NOT NULL
        """,
        (org, day_end, day_start),
    )
    w = cur.fetchone() or {}

    return {
        "admitted_on_date": admitted,
        "completed_on_date": completed,
        "active_now": active_now,
        "opening_backlog": opening_backlog,
        "review_unresolved": review,
        "pre_bags": int(w.get("n") or 0),
        "pre_lbs": float(w.get("pre_lbs") or 0),
        "post_bags": int(w.get("post_bags") or 0),
        "post_lbs": float(w.get("post_lbs") or 0),
    }


def sync_wf_cycles_after_portal_presence(
    conn,
    cursor,
    organization_id: int,
    *,
    portal_csv_path,
    portal_scrape_meta_path=None,
) -> dict[str, Any]:
    """Hook after full portal presence apply: admit/update canonical WF cycles."""
    from pathlib import Path

    from backend.rinse_cleaner_ticket_presence import parse_presence_rows_from_portal_csv
    from backend.rinse_portal_scrape_meta import read_portal_scrape_meta

    org = int(organization_id)
    rows = parse_presence_rows_from_portal_csv(str(portal_csv_path))
    portal_bags: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id") or row.get("ticket_id"))
        if not bid:
            continue
        portal_bags[bid] = {
            "service_type": row.get("service_type") or "WF",
            "rush_flag": row.get("rush_flag"),
            "estimated_delivery_date": row.get("estimated_delivery_date"),
            "last_seen_at": datetime.utcnow(),
        }
    meta = read_portal_scrape_meta(str(portal_scrape_meta_path or Path(str(portal_csv_path) + ".meta.json"))) or {}
    traversal_complete = str(meta.get("stopped_reason") or "") in (
        "no_next_page_ui",
        "natural_end",
        "",
    ) or not meta.get("reached_max_pages")
    discovery = sync_portal_discovery(cursor, org, portal_bags)
    disappearance = handle_disappeared_active_cycles(
        cursor,
        org,
        set(portal_bags.keys()),
        traversal_complete=bool(traversal_complete),
    )
    from backend.business_time import business_today
    from backend.rinse_wf_service_cycle_compat import project_canonical_cycles_to_day_snapshot

    today = business_today()
    projection = project_canonical_cycles_to_day_snapshot(cursor, org, today, force=True)
    return {
        "discovery": discovery,
        "disappearance": disappearance,
        "projection": {
            "ok": projection.get("ok", True),
            "shift_date_et": str(today),
        },
    }
