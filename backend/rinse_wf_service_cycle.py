"""Canonical Rinse WF service-cycle lifecycle.

ADMIT ONCE → ACTIVE across days → COMPLETE ONCE (or REVIEW → resolution).

Midnight has zero effect. day_bags are a downstream compatibility projection only.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Collection, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_cycle_boundary import resolve_current_cycle
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.ta_helpers import table_exists

STATUS_ACTIVE = "ACTIVE"
STATUS_REVIEW = "REVIEW"
STATUS_COMPLETED = "COMPLETED"
STATUS_RESOLVED_OTHER = "RESOLVED_OTHER"

REVIEW_MISSING_FROM_PORTAL = "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"
SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE = "SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE"


def is_wf_canonical_lifecycle_enabled(cursor, organization_id: int) -> bool:
    """True when org uses durable WF service-cycle lifecycle (cutover forward)."""
    if not table_exists(cursor, "rinse_wf_service_cycles"):
        return False
    raw = os.getenv("WF_CANONICAL_LIFECYCLE_ORG_IDS", "3")
    try:
        allowed = {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError:
        allowed = {3}
    return int(organization_id) in allowed


def ensure_wf_service_cycles_table(cursor) -> None:
    if table_exists(cursor, "rinse_wf_service_cycles"):
        return
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parent / "sql" / "rinse_wf_service_cycles_v1.sql"
    ).read_text()
    lines = [
        ln
        for ln in sql.splitlines()
        if not ln.strip().startswith("--")
    ]
    body = "\n".join(lines)
    for stmt in body.split(";"):
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
               weight_role, weight_source, weight_observed_at, weight_attach_reason,
               weight_presence_run_id, source_filename, raw_json, scan_index, id
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
    bid = _norm_bag(bag_id)
    cycle = resolve_current_cycle(
        timeline,
        selected_date_et=day,
        cycle_anchor_override=cycle_anchor_at,
    )
    from backend.rinse_current_cycle_weight import resolve_bag_weight_info_canonical

    weights = resolve_bag_weight_info_canonical(
        cursor,
        organization_id,
        bid,
        selected_date_et=day,
        cycle_anchor_override=cycle_anchor_at,
    )
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


def _cycle_anchor_is_stv_backed(
    timeline: Sequence[Mapping[str, Any]], cycle_anchor_at: datetime
) -> bool:
    """True when anchor matches a sent-to-vendor / lifecycle boundary from scan evidence."""
    if not isinstance(cycle_anchor_at, datetime):
        return False
    for anchor in _valid_cycle_anchors(timeline):
        if anchor == cycle_anchor_at:
            return True
    return False


def _portal_only_discovery_active(active: Mapping[str, Any] | None) -> bool:
    if not active:
        return False
    if str(active.get("status") or "") not in (STATUS_ACTIVE, STATUS_REVIEW):
        return False
    return str(active.get("admitted_source") or "") == "PORTAL_DISCOVERY"


def _update_portal_cycle_metadata(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_anchor_at: datetime,
    portal_meta: Mapping[str, Any] | None,
    *,
    now_utc: datetime | None = None,
) -> bool:
    """Lightweight portal touch — no canonical resolution."""
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    if not bid or not isinstance(cycle_anchor_at, datetime):
        return False
    meta = portal_meta or {}
    now = now_utc or datetime.utcnow()
    last_seen = meta.get("last_seen_at") or now
    rush = meta.get("rush_flag") or meta.get("rush_status")
    est = meta.get("estimated_delivery_date")
    cur = cursor
    cur.execute(
        """
        UPDATE rinse_wf_service_cycles
        SET portal_last_seen_at = COALESCE(%s, portal_last_seen_at),
            rush_status = COALESCE(%s, rush_status),
            estimated_delivery_date = COALESCE(%s, estimated_delivery_date),
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s AND bag_id = %s AND cycle_anchor_at = %s
          AND status IN (%s, %s)
        """,
        (
            last_seen,
            rush,
            est,
            org,
            bid,
            cycle_anchor_at,
            STATUS_ACTIVE,
            STATUS_REVIEW,
        ),
    )
    return bool(getattr(cur, "rowcount", 0))


def _fetch_scoped_cycle_refresh_rows(
    cursor,
    organization_id: int,
    scoped_ids: Sequence[str],
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    """Latest legitimate ACTIVE/REVIEW per bag + completed-today lifecycle rows."""
    org = int(organization_id)
    ids = sorted({_norm_bag(b) for b in scoped_ids if _norm_bag(b)})
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    sql = f"""
        SELECT c.bag_id, c.cycle_anchor_at
        FROM rinse_wf_service_cycles c
        INNER JOIN (
            SELECT bag_id, MAX(cycle_anchor_at) AS max_anchor
            FROM rinse_wf_service_cycles
            WHERE organization_id = %s
              AND status IN (%s, %s)
              AND bag_id IN ({placeholders})
            GROUP BY bag_id
        ) latest
          ON c.organization_id = %s
         AND c.bag_id = latest.bag_id
         AND c.cycle_anchor_at = latest.max_anchor
        WHERE c.organization_id = %s
          AND c.status IN (%s, %s)
        UNION
        SELECT bag_id, cycle_anchor_at
        FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND status = %s
          AND completed_at >= %s
          AND completed_at < %s
          AND bag_id IN ({placeholders})
    """
    params: list[Any] = [
        org,
        STATUS_ACTIVE,
        STATUS_REVIEW,
        *ids,
        org,
        org,
        STATUS_ACTIVE,
        STATUS_REVIEW,
        org,
        STATUS_COMPLETED,
        day_start,
        day_end,
        *ids,
    ]
    cursor.execute(sql, tuple(params))
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def supersede_stale_portal_discovery_active_duplicates(
    cursor,
    organization_id: int,
    *,
    bag_ids: Collection[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """One-time hygiene: resolve proven portal-only duplicate ACTIVE rows (no deletes)."""
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    scope = sorted({_norm_bag(b) for b in (bag_ids or []) if _norm_bag(b)})
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "bags_scanned": 0,
        "bags_with_duplicates": 0,
        "rows_superseded": 0,
        "ambiguous_bags": [],
        "examples": [],
        "superseded": [],
    }
    if scope:
        ph = ", ".join(["%s"] * len(scope))
        cursor.execute(
            f"""
            SELECT DISTINCT bag_id FROM rinse_wf_service_cycles
            WHERE organization_id = %s AND status = %s AND bag_id IN ({ph})
            """,
            (org, STATUS_ACTIVE, *scope),
        )
        bag_list = [
            _norm_bag(r.get("bag_id"))
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict) and _norm_bag(r.get("bag_id"))
        ]
    else:
        cursor.execute(
            """
            SELECT bag_id, COUNT(*) AS c FROM rinse_wf_service_cycles
            WHERE organization_id = %s AND status = %s
            GROUP BY bag_id HAVING c > 1
            """,
            (org, STATUS_ACTIVE),
        )
        bag_list = [
            _norm_bag(r.get("bag_id"))
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict) and _norm_bag(r.get("bag_id"))
        ]

    for bid in sorted(set(bag_list)):
        report["bags_scanned"] += 1
        cursor.execute(
            """
            SELECT * FROM rinse_wf_service_cycles
            WHERE organization_id = %s AND bag_id = %s AND status = %s
            ORDER BY cycle_anchor_at ASC
            """,
            (org, bid, STATUS_ACTIVE),
        )
        active_rows = [
            dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)
        ]
        if len(active_rows) <= 1:
            continue
        report["bags_with_duplicates"] += 1
        timeline = _load_timeline(cursor, org, bid)
        valid_anchors = set(_valid_cycle_anchors(timeline))
        stv_rows = [
            r
            for r in active_rows
            if isinstance(r.get("cycle_anchor_at"), datetime)
            and r["cycle_anchor_at"] in valid_anchors
        ]
        if len(stv_rows) > 1:
            report["ambiguous_bags"].append(
                {"bag_id": bid, "reason": "multiple_stv_backed_active"}
            )
            continue
        if stv_rows:
            keeper = stv_rows[-1]
        else:
            keeper = active_rows[-1]
        keeper_id = keeper.get("id")
        for row in active_rows:
            if row.get("id") == keeper_id:
                continue
            if str(row.get("admitted_source") or "") != "PORTAL_DISCOVERY":
                report["ambiguous_bags"].append(
                    {
                        "bag_id": bid,
                        "reason": "non_portal_discovery_duplicate",
                        "cycle_id": row.get("id"),
                    }
                )
                continue
            anchor = row.get("cycle_anchor_at")
            if isinstance(anchor, datetime) and anchor in valid_anchors:
                report["ambiguous_bags"].append(
                    {
                        "bag_id": bid,
                        "reason": "stv_backed_not_keeper",
                        "cycle_id": row.get("id"),
                    }
                )
                continue
            action = {
                "bag_id": bid,
                "cycle_id": row.get("id"),
                "cycle_anchor_at": str(anchor),
                "keeper_id": keeper_id,
            }
            report["superseded"].append(action)
            if len(report["examples"]) < 10:
                report["examples"].append(action)
            if not dry_run:
                cursor.execute(
                    """
                    UPDATE rinse_wf_service_cycles
                    SET status = %s,
                        review_reason = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND organization_id = %s AND status = %s
                    """,
                    (
                        STATUS_RESOLVED_OTHER,
                        SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
                        int(row["id"]),
                        org,
                        STATUS_ACTIVE,
                    ),
                )
            report["rows_superseded"] += 1
    return report


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
    if row and str(row.get("status") or "").upper() == STATUS_COMPLETED:
        try:
            from backend.rinse_order_instances import sync_order_instance_on_cycle_completion

            sync_order_instance_on_cycle_completion(cursor, org, row)
        except Exception:
            # Order-instance sync must not block cycle persistence.
            pass
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
        # Completed cycles are immutable for lifecycle — refresh weights from canonical resolver.
        cycle_dict, weights = _cycle_resolution(cursor, org, bid, cycle_anchor_at)
        from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs

        refreshed_pre = authoritative_evidence_pre_lbs(weights)
        refreshed_post = weights.get("post_weight_lbs")
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
            pre_weight_lbs=refreshed_pre
            if refreshed_pre is not None
            else existing.get("pre_weight_lbs"),
            post_weight_lbs=refreshed_post
            if refreshed_post is not None
            else existing.get("post_weight_lbs"),
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

    row = upsert_service_cycle(
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
    if status == STATUS_ACTIVE and completed_at is None:
        try:
            from backend.rinse_order_instances import (
                ensure_open_order_instance_for_new_active_cycle,
            )

            ensure_open_order_instance_for_new_active_cycle(cursor, org, row)
        except Exception:
            pass
    return row


def _current_cycle_anchor(
    timeline: Sequence[Mapping[str, Any]], cutover_date_et: date
) -> datetime | None:
    from backend.rinse_cycle_boundary import resolve_cycle_anchor

    return resolve_cycle_anchor(timeline, selected_date_et=cutover_date_et)


def _parse_cycle_completion_at(cycle_dict: Mapping[str, Any]) -> datetime | None:
    comp_raw = cycle_dict.get("completion_at")
    if not comp_raw:
        return None
    if isinstance(comp_raw, datetime):
        return comp_raw
    return datetime.fromisoformat(str(comp_raw).replace("Z", "")[:19])


def _eligible_for_minimal_cutover_seed(
    cycle_dict: Mapping[str, Any], cutover_date_et: date
) -> bool:
    """Current open cycles, or cycles completed on the cutover date only."""
    status = str(cycle_dict.get("effective_status") or "").lower()
    if status == "completed":
        comp_at = _parse_cycle_completion_at(cycle_dict)
        return comp_at is not None and comp_at.date() == cutover_date_et
    return status in ("pending", "review", "active")


def _collect_minimal_cutover_bag_ids(
    cursor,
    organization_id: int,
    cutover_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> list[str]:
    """Operational hints only — lifecycle truth comes from current-cycle evidence."""
    org = int(organization_id)
    day_start = naive_et_day_start(cutover_date_et)
    day_end = day_start + timedelta(days=1)
    ids: set[str] = {_norm_bag(b) for b in (bag_ids or []) if _norm_bag(b)}
    cur = cursor
    if table_exists(cursor, "rinse_shift_monitor_day_bags"):
        cur.execute(
            """
            SELECT bag_id FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND shift_date_et = %s AND UPPER(service_type) = 'WF'
            """,
            (org, cutover_date_et.isoformat()),
        )
        ids.update(_norm_bag(r["bag_id"]) for r in (cur.fetchall() or []) if r.get("bag_id"))
    if table_exists(cursor, "rinse_bag_scan_events"):
        cur.execute(
            """
            SELECT DISTINCT bag_id FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND scanned_at_parsed >= %s AND scanned_at_parsed < %s
            """,
            (org, day_start, day_end),
        )
        ids.update(_norm_bag(r["bag_id"]) for r in (cur.fetchall() or []) if r.get("bag_id"))
    return sorted(b for b in ids if b)


def prune_historical_canonical_cycles(
    cursor,
    organization_id: int,
    cutover_date_et: date,
) -> dict[str, Any]:
    """Remove canonical rows outside cutover-forward scope (no historical migration)."""
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    cur = cursor
    cur.execute(
        """
        SELECT id, bag_id, cycle_anchor_at
        FROM rinse_wf_service_cycles
        WHERE organization_id = %s
        """,
        (org,),
    )
    to_delete: list[int] = []
    for row in cur.fetchall() or []:
        if not isinstance(row, dict):
            continue
        row_id = int(row["id"])
        bid = _norm_bag(row.get("bag_id"))
        anchor = row.get("cycle_anchor_at")
        if not bid or not isinstance(anchor, datetime):
            to_delete.append(row_id)
            continue
        timeline = _load_timeline(cursor, org, bid)
        current_anchor = _current_cycle_anchor(timeline, cutover_date_et)
        if current_anchor is None or anchor != current_anchor:
            to_delete.append(row_id)
            continue
        cycle_dict, _ = _cycle_resolution(
            cursor, org, bid, anchor, selected_date_et=cutover_date_et
        )
        if not _eligible_for_minimal_cutover_seed(cycle_dict, cutover_date_et):
            to_delete.append(row_id)
    deleted = 0
    for row_id in to_delete:
        cur.execute(
            "DELETE FROM rinse_wf_service_cycles WHERE id = %s AND organization_id = %s",
            (row_id, org),
        )
        deleted += int(cur.rowcount or 0)
    return {"deleted": deleted, "cutover_date_et": cutover_date_et.isoformat()}


def seed_minimal_cutover_cycles(
    cursor,
    organization_id: int,
    cutover_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Seed only current open WF cycles and today's completed cycles (cutover forward)."""
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    ids = _collect_minimal_cutover_bag_ids(cursor, org, cutover_date_et, bag_ids)
    admitted = skipped_historical = 0
    completed = 0
    for bid in ids:
        timeline = _load_timeline(cursor, org, bid)
        anchor = _current_cycle_anchor(timeline, cutover_date_et)
        if anchor is None:
            continue
        cycle_dict, _ = _cycle_resolution(
            cursor, org, bid, anchor, selected_date_et=cutover_date_et
        )
        if not _eligible_for_minimal_cutover_seed(cycle_dict, cutover_date_et):
            skipped_historical += 1
            continue
        row = admit_or_update_cycle_from_evidence(
            cursor,
            org,
            bid,
            anchor,
            admitted_source="CUTOVER_MINIMAL_SEED",
        )
        admitted += 1
        if str(row.get("status")) == STATUS_COMPLETED:
            completed += 1
    return {
        "bags_considered": len(ids),
        "cycles_upserted": admitted,
        "completed": completed,
        "skipped_historical": skipped_historical,
        "cutover_date_et": cutover_date_et.isoformat(),
    }


def reconstruct_cycles_from_durable_evidence(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str] | None = None,
    *,
    cutover_date_et: date | None = None,
) -> dict[str, Any]:
    """Minimal cutover seed only — does not migrate historical WF cycles."""
    from backend.business_time import business_today

    day = cutover_date_et or business_today()
    return seed_minimal_cutover_cycles(cursor, organization_id, day, bag_ids)


def sync_portal_discovery(
    cursor,
    organization_id: int,
    portal_bags: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
    evidence_refreshed_bag_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """After full At-Vendor traversal: admit new cycles, refresh active ones.

    Presence alone must never fork a second OI/cycle while an ACTIVE/REVIEW
    cycle already owns the bag. ``now_utc`` portal anchors are only allowed
    when there is no open cycle.
    """
    org = int(organization_id)
    now_utc = now or datetime.utcnow()
    refreshed = {
        _norm_bag(b) for b in (evidence_refreshed_bag_ids or []) if _norm_bag(b)
    }
    admitted = updated = metadata_only = 0
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
        portal_meta = {**(meta or {}), "last_seen_at": now_utc}
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
                if bid in refreshed and _update_portal_cycle_metadata(
                    cursor,
                    org,
                    bid,
                    active_anchor,
                    portal_meta,
                    now_utc=now_utc,
                ):
                    metadata_only += 1
                else:
                    admit_or_update_cycle_from_evidence(
                        cursor,
                        org,
                        bid,
                        anchor,
                        admitted_source="PORTAL_REDISCOVERY",
                        portal_meta=portal_meta,
                    )
                    updated += 1
                continue
            # ACTIVE/REVIEW owns the bag; STV timeline advanced to a different
            # anchor → migrate to STV (same lifecycle), never seed now_utc.
            if (
                isinstance(active_anchor, datetime)
                and anchor != active_anchor
                and str(active.get("status")) in (STATUS_ACTIVE, STATUS_REVIEW)
            ):
                if _portal_only_discovery_active(active) and anchor in anchors:
                    # Supersede portal-only active; admit STV-backed cycle.
                    cursor.execute(
                        """
                        UPDATE rinse_wf_service_cycles
                        SET status = %s,
                            review_reason = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE organization_id = %s AND bag_id = %s
                          AND cycle_anchor_at = %s AND status IN (%s, %s)
                        """,
                        (
                            STATUS_RESOLVED_OTHER,
                            SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
                            org,
                            bid,
                            active_anchor,
                            STATUS_ACTIVE,
                            STATUS_REVIEW,
                        ),
                    )
                    admit_or_update_cycle_from_evidence(
                        cursor,
                        org,
                        bid,
                        anchor,
                        admitted_at=now_utc,
                        admitted_source="SCAN_EVIDENCE_REFRESH",
                        portal_meta=portal_meta,
                    )
                    admitted += 1
                    continue
                # Non-portal active with different STV: refresh metadata on keeper.
                if bid in refreshed and _update_portal_cycle_metadata(
                    cursor,
                    org,
                    bid,
                    active_anchor,
                    portal_meta,
                    now_utc=now_utc,
                ):
                    metadata_only += 1
                else:
                    admit_or_update_cycle_from_evidence(
                        cursor,
                        org,
                        bid,
                        active_anchor,
                        admitted_source="PORTAL_REDISCOVERY",
                        portal_meta=portal_meta,
                    )
                    updated += 1
                continue
        if anchor is None:
            # Reuse ANY open cycle — never invent now_utc while ACTIVE/REVIEW exists.
            if active and str(active.get("status")) in (STATUS_ACTIVE, STATUS_REVIEW):
                active_anchor = active.get("cycle_anchor_at")
                if isinstance(active_anchor, datetime):
                    if bid in refreshed and _update_portal_cycle_metadata(
                        cursor,
                        org,
                        bid,
                        active_anchor,
                        portal_meta,
                        now_utc=now_utc,
                    ):
                        metadata_only += 1
                    else:
                        admit_or_update_cycle_from_evidence(
                            cursor,
                            org,
                            bid,
                            active_anchor,
                            admitted_source="PORTAL_REDISCOVERY",
                            portal_meta=portal_meta,
                        )
                        updated += 1
                    continue
            anchor = now_utc
        if not get_cycle_by_key(cursor, org, bid, anchor):
            admit_or_update_cycle_from_evidence(
                cursor,
                org,
                bid,
                anchor,
                admitted_at=now_utc,
                admitted_source="PORTAL_DISCOVERY",
                portal_meta=portal_meta,
            )
            admitted += 1
        elif bid in refreshed and isinstance(anchor, datetime):
            if _update_portal_cycle_metadata(
                cursor,
                org,
                bid,
                anchor,
                portal_meta,
                now_utc=now_utc,
            ):
                metadata_only += 1
            else:
                admit_or_update_cycle_from_evidence(
                    cursor,
                    org,
                    bid,
                    anchor,
                    admitted_source="PORTAL_REDISCOVERY",
                    portal_meta=portal_meta,
                )
                updated += 1
        else:
            admit_or_update_cycle_from_evidence(
                cursor,
                org,
                bid,
                anchor,
                admitted_source="PORTAL_REDISCOVERY",
                portal_meta=portal_meta,
            )
            updated += 1
    return {
        "admitted": admitted,
        "updated": updated,
        "metadata_only": metadata_only,
    }


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


def _parse_portal_bags_from_csv(portal_csv_path) -> dict[str, dict[str, Any]]:
    from backend.rinse_presence_scrape import parse_presence_rows_from_portal_csv

    portal_bags: dict[str, dict[str, Any]] = {}
    rows = parse_presence_rows_from_portal_csv(str(portal_csv_path))
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
    return portal_bags


def _portal_traversal_complete(portal_scrape_meta_path) -> bool:
    """Single SoT with portal absence: only a complete traversal may mark absence.

    Fail closed when meta path/file is missing — never treat an unknown scrape
    as authoritative portal presence/absence.
    """
    from backend.rinse_portal_scrape_meta import (
        load_portal_scrape_meta_file,
        normalize_portal_scrape_meta,
        portal_scrape_meta_allows_absence_completion,
    )

    if not portal_scrape_meta_path:
        return False
    raw = load_portal_scrape_meta_file(portal_scrape_meta_path)
    if not raw:
        return False
    return portal_scrape_meta_allows_absence_completion(
        normalize_portal_scrape_meta(raw)
    )


def refresh_canonical_cycles_from_evidence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bag_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Reconcile open/review and today's completed cycles from durable scan evidence.

    When ``bag_ids`` is provided (scrape terminal / publish path), only those bags
    are refreshed. Unscoped refresh of every ACTIVE/REVIEW row is unsafe at
    production scale (1000+ rows × per-bag timeline admit ≈ multi-minute hang
    that never reaches finish_scrape_run).
    """
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    day_start = naive_et_day_start(selected_date_et)
    day_end = day_start + timedelta(days=1)
    cur = cursor
    scoped_ids: list[str] | None = None
    if bag_ids is not None:
        scoped_ids = sorted(
            {normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)}
        )
        if not scoped_ids:
            return {
                "refreshed": 0,
                "selected_date_et": selected_date_et.isoformat(),
                "scoped": True,
                "bag_count": 0,
            }
    sql = """
        SELECT bag_id, cycle_anchor_at FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND (
            status IN (%s, %s)
            OR (status = %s AND completed_at >= %s AND completed_at < %s)
          )
        """
    params: list[Any] = [org, STATUS_ACTIVE, STATUS_REVIEW, STATUS_COMPLETED, day_start, day_end]
    rows: list[dict[str, Any]]
    if scoped_ids is not None:
        rows = _fetch_scoped_cycle_refresh_rows(
            cur, org, scoped_ids, day_start, day_end
        )
    else:
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in (cur.fetchall() or []) if isinstance(r, dict)]
    refreshed = 0
    for row in rows:
        bid = _norm_bag(row.get("bag_id"))
        anchor = row.get("cycle_anchor_at")
        if not bid or not isinstance(anchor, datetime):
            continue
        admit_or_update_cycle_from_evidence(
            cursor,
            org,
            bid,
            anchor,
            admitted_source="SCAN_EVIDENCE_REFRESH",
        )
        refreshed += 1
    out: dict[str, Any] = {
        "refreshed": refreshed,
        "selected_date_et": selected_date_et.isoformat(),
    }
    if scoped_ids is not None:
        out["scoped"] = True
        out["bag_count"] = len(scoped_ids)
    return out


def reconcile_stale_active_wf_cycles_from_canonical_completion(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> dict[str, Any]:
    """Close ACTIVE/REVIEW cycles when canonical completion already exists.

    Prevents canonically completed bag IDs from lingering as ACTIVE with
    completed_at=NULL. Workload exclusion still applies even if a stale row
    remains, but lifecycle rows should match completion evidence.
    """
    ensure_wf_service_cycles_table(cursor)
    org = int(organization_id)
    day_start = naive_et_day_start(shift_date_et)
    cur = cursor
    cur.execute(
        """
        SELECT id, bag_id, cycle_anchor_at, status, admitted_at,
               pre_weight_lbs, post_weight_lbs, rush_status, estimated_delivery_date,
               admitted_source, portal_last_seen_at
        FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND status IN (%s, %s)
          AND completed_at IS NULL
        """,
        (org, STATUS_ACTIVE, STATUS_REVIEW),
    )
    rows = [r for r in (cur.fetchall() or []) if isinstance(r, dict)]
    bag_ids = sorted(
        {
            normalize_bag_id(r.get("bag_id"))
            for r in rows
            if normalize_bag_id(r.get("bag_id"))
        }
    )
    if not bag_ids:
        return {"closed": 0, "bag_ids": []}

    from backend.rinse_veewash_workload import load_canonical_completions_v2

    comps = load_canonical_completions_v2(
        cursor,
        org,
        bag_ids,
        selected_date_et=shift_date_et,
    ) or {}
    closed_bags: set[str] = set()
    closed_cycles = 0
    for row in rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        comp = comps.get(bid) or {}
        comp_at = comp.get("completion_at")
        comp_date = comp.get("completion_date")
        if isinstance(comp_at, str):
            try:
                comp_at = datetime.fromisoformat(comp_at.replace("Z", "")[:19])
            except ValueError:
                comp_at = None
        terminal = False
        if comp_date is not None and comp_date < shift_date_et:
            terminal = True
        elif isinstance(comp_at, datetime) and comp_at < day_start:
            terminal = True
        elif (
            str(comp.get("effective_status") or "").lower() == "completed"
            and isinstance(comp_at, datetime)
            and comp_at < day_start
        ):
            terminal = True
        if not terminal:
            continue
        anchor = row.get("cycle_anchor_at")
        if not isinstance(anchor, datetime):
            continue
        upsert_service_cycle(
            cursor,
            org,
            bag_id=bid,
            cycle_anchor_at=anchor,
            admitted_at=row.get("admitted_at") or anchor,
            admitted_source=str(row.get("admitted_source") or "SCAN_EVIDENCE_REFRESH"),
            status=STATUS_COMPLETED,
            completed_at=comp_at if isinstance(comp_at, datetime) else None,
            completion_source=str(comp.get("completion_source") or "CANONICAL_RECONCILE"),
            rush_status=row.get("rush_status"),
            estimated_delivery_date=row.get("estimated_delivery_date"),
            pre_weight_lbs=row.get("pre_weight_lbs"),
            post_weight_lbs=row.get("post_weight_lbs"),
            portal_last_seen_at=row.get("portal_last_seen_at"),
            review_reason=None,
        )
        closed_cycles += 1
        closed_bags.add(bid)
    return {
        "closed": closed_cycles,
        "bag_ids": sorted(closed_bags),
        "selected_date_et": shift_date_et.isoformat(),
    }


def apply_manager_review_resolution_to_canonical_cycle(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    completed_at: datetime,
    completion_source: str = "manager_correct_completion",
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> dict[str, Any] | None:
    """Write manager Review resolution back to the canonical service cycle."""
    if not is_wf_canonical_lifecycle_enabled(cursor, organization_id):
        return None
    cycle = get_active_cycle_for_bag(cursor, organization_id, bag_id)
    if not cycle:
        return None
    anchor = cycle.get("cycle_anchor_at")
    if not isinstance(anchor, datetime):
        return None
    cycle_dict, weights = _cycle_resolution(cursor, int(organization_id), bag_id, anchor)
    _ = cycle_dict
    row = upsert_service_cycle(
        cursor,
        int(organization_id),
        bag_id=bag_id,
        cycle_anchor_at=anchor,
        admitted_at=cycle.get("admitted_at") or anchor,
        admitted_source=str(cycle.get("admitted_source") or "PORTAL_DISCOVERY"),
        status=STATUS_COMPLETED,
        completed_at=completed_at,
        completion_source=completion_source,
        rush_status=cycle.get("rush_status"),
        estimated_delivery_date=cycle.get("estimated_delivery_date"),
        pre_weight_lbs=weights.get("pre_weight_lbs") or cycle.get("pre_weight_lbs"),
        post_weight_lbs=weights.get("post_weight_lbs") or cycle.get("post_weight_lbs"),
        review_reason=None,
    )
    cur = cursor
    cur.execute(
        """
        UPDATE rinse_wf_service_cycles
        SET review_resolved_at = %s,
            review_resolved_by = %s,
            review_resolution_note = %s,
            review_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s AND bag_id = %s AND cycle_anchor_at = %s
        """,
        (
            datetime.utcnow(),
            resolved_by,
            resolution_note,
            int(organization_id),
            _norm_bag(bag_id),
            anchor,
        ),
    )
    return row


def sync_wf_cycles_after_portal_presence(
    conn,
    cursor,
    organization_id: int,
    *,
    portal_csv_path,
    portal_scrape_meta_path=None,
) -> dict[str, Any]:
    """After portal presence apply: discovery/disappearance only (no day_bags projection)."""
    from pathlib import Path

    if not is_wf_canonical_lifecycle_enabled(cursor, organization_id):
        return {"skipped": True, "reason": "canonical_disabled"}

    org = int(organization_id)
    portal_bags = _parse_portal_bags_from_csv(portal_csv_path)
    meta_path = portal_scrape_meta_path or Path(str(portal_csv_path) + ".meta.json")
    traversal_complete = _portal_traversal_complete(meta_path)
    discovery = sync_portal_discovery(cursor, org, portal_bags)
    disappearance = handle_disappeared_active_cycles(
        cursor,
        org,
        set(portal_bags.keys()),
        traversal_complete=bool(traversal_complete),
    )
    return {
        "discovery": discovery,
        "disappearance": disappearance,
        "projection": {"deferred": True},
    }


def finalize_wf_canonical_lifecycle_terminal(
    cursor,
    organization_id: int,
    *,
    portal_csv_path=None,
    portal_scrape_meta_path=None,
    shift_date_et: date | None = None,
) -> dict[str, Any]:
    """Terminal scrape/finalize hook: refresh evidence, portal sync, project day_bags."""
    from backend.business_time import business_today
    from backend.rinse_wf_service_cycle_compat import (
        terminal_project_canonical_wf_day_snapshot,
    )

    if not is_wf_canonical_lifecycle_enabled(cursor, organization_id):
        return {"skipped": True, "reason": "canonical_disabled"}

    org = int(organization_id)
    day = shift_date_et or business_today()
    portal_bags: dict[str, Any] = {}
    scope: set[str] | None = None
    if portal_csv_path is not None:
        portal_bags = _parse_portal_bags_from_csv(portal_csv_path)
        # Scrape publish must never unbounded-refresh every ACTIVE/REVIEW cycle.
        scope = set(portal_bags.keys())
    # One scoped evidence refresh per publish. A second refresh after
    # discovery/disappearance is redundant:
    # - sync_portal_discovery already admit_or_update's each portal bag
    # - handle_disappeared_active_cycles upserts bags *outside* portal scope
    #   (second scoped refresh would not touch them anyway)
    evidence = refresh_canonical_cycles_from_evidence(
        cursor, org, day, bag_ids=scope
    )
    refresh_calls = 1
    discovery: dict[str, Any] = {}
    disappearance: dict[str, Any] = {}
    if portal_csv_path is not None:
        from pathlib import Path

        meta_path = portal_scrape_meta_path or Path(str(portal_csv_path) + ".meta.json")
        discovery = sync_portal_discovery(
            cursor,
            org,
            portal_bags,
            evidence_refreshed_bag_ids=scope,
        )
        disappearance = handle_disappeared_active_cycles(
            cursor,
            org,
            set(portal_bags.keys()),
            traversal_complete=_portal_traversal_complete(meta_path),
        )
    projection = terminal_project_canonical_wf_day_snapshot(
        cursor, org, day, force=True
    )
    return {
        "ok": True,
        "evidence": evidence,
        "discovery": discovery,
        "disappearance": disappearance,
        "canonical_refresh_calls": refresh_calls,
        "projection": {
            "ok": projection.get("ok", True),
            "shift_date_et": day.isoformat(),
            "canonical_source": True,
        },
    }
