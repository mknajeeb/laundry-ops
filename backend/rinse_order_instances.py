"""Immutable Rinse order_instance_id — one real service/order occurrence.

bag_id is reusable. order_instance_id is the durable identity for completion
terminal protection and day admission.

A COMPLETED service-cycle row is evidence, not automatically a new order.
A new instance requires authoritative new-order boundary evidence (pickup /
workitems / load-in) after the prior completed instance. EDD alone never
creates identity. Duplicate/reconciliation cycles map to one instance.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_et import naive_et_day_start
from backend.ta_helpers import table_exists

ORDER_INSTANCES_TABLE = "rinse_order_instances"

# Authoritative signals that a distinct customer order occurrence began.
_NEW_ORDER_BOUNDARY_PURPOSES = (
    "bag-picked-up",
    "workitems-added",
    "load-in",
)

# Heal-only: post-completion load-in / undelivered movement is logistics, not a
# new customer lifecycle. Do not use this set for OI creation gates.
_CUSTOMER_NEW_ORDER_BOUNDARY_PURPOSES = (
    "bag-picked-up",
    "workitems-added",
)


def ensure_rinse_order_instances_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ORDER_INSTANCES_TABLE} (
          order_instance_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          service_type VARCHAR(10) NOT NULL DEFAULT 'WF',
          cycle_anchor_at DATETIME NOT NULL,
          source_cycle_id BIGINT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          completed_at DATETIME NULL,
          completed_by_user_id INT NULL,
          completed_by_employee_name VARCHAR(255) NULL,
          completion_source VARCHAR(64) NULL,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_order_instance_cycle (
            organization_id, bag_id, service_type, cycle_anchor_at
          ),
          UNIQUE KEY uq_order_instance_source_cycle (source_cycle_id),
          KEY idx_order_instance_org_bag (organization_id, bag_id),
          KEY idx_order_instance_org_completed (organization_id, completed_at),
          KEY idx_order_instance_org_anchor (organization_id, cycle_anchor_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _svc(raw: Any) -> str:
    s = str(raw or "WF").strip().upper()
    return s or "WF"


def _et_date(ts: datetime | date | None) -> date | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    return None


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


def load_new_order_boundary_timestamps(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[datetime]:
    """ET-wall timestamps that mark a distinct customer order start."""
    by_bag = load_new_order_boundary_timestamps_for_bags(
        cursor, organization_id, [bag_id]
    )
    return list(by_bag.get(normalize_bag_id(bag_id) or "", []) or [])


def load_new_order_boundary_timestamps_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, list[datetime]]:
    """Batch load pickup/workitems/load-in timestamps for many bags."""
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[datetime]] = {b: [] for b in ids}
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    ph_bags = ",".join(["%s"] * len(ids))
    ph_purp = ",".join(["%s"] * len(_NEW_ORDER_BOUNDARY_PURPOSES))
    cursor.execute(
        f"""
        SELECT bag_id, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IN ({ph_bags})
          AND purpose IN ({ph_purp})
          AND scanned_at_parsed IS NOT NULL
        ORDER BY bag_id, scanned_at_parsed ASC
        """,
        (int(organization_id), *ids, *_NEW_ORDER_BOUNDARY_PURPOSES),
    )
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, dict) else row[0]
        )
        ts = _parse_dt(
            row.get("scanned_at_parsed") if isinstance(row, dict) else row[1]
        )
        if bid and ts is not None:
            out.setdefault(bid, []).append(ts)
    return out


def has_authoritative_new_order_boundary_after(
    cursor,
    organization_id: int,
    bag_id: str,
    after_dt: datetime | None,
    *,
    before_or_at: datetime | None = None,
    boundary_timestamps: Sequence[datetime] | None = None,
) -> bool:
    """True when pickup/workitems/load-in proves a new order after ``after_dt``.

    EDD changes, Missing state, and bare cycle_anchor alone are insufficient.
    """
    if after_dt is None:
        # No prior completion → first occurrence does not need a boundary proof.
        return True
    after = _parse_dt(after_dt)
    if after is None:
        return True
    end = _parse_dt(before_or_at)
    stamps = (
        list(boundary_timestamps)
        if boundary_timestamps is not None
        else load_new_order_boundary_timestamps(cursor, organization_id, bag_id)
    )
    for ts in stamps:
        if ts <= after:
            continue
        if end is not None and ts > end + timedelta(hours=12):
            # Boundary far after this cycle's completion is not for this occurrence.
            continue
        if end is None or ts <= end + timedelta(hours=12):
            return True
    return False


def has_customer_new_order_boundary_after(
    cursor,
    organization_id: int,
    bag_id: str,
    after_dt: datetime | None,
    *,
    before_or_at: datetime | None = None,
) -> bool:
    """True when pickup/workitems prove a new customer order after ``after_dt``.

    Unlike ``has_authoritative_new_order_boundary_after``, ignores bare ``load-in``
    (including undelivered-bag-load-in logistics after a completed lifecycle).
    Used only by portal-shell heal — does not change OI creation gates.
    """
    if after_dt is None:
        return True
    after = _parse_dt(after_dt)
    if after is None:
        return True
    end = _parse_dt(before_or_at)
    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_bag_scan_events"):
        return False
    ph = ",".join(["%s"] * len(_CUSTOMER_NEW_ORDER_BOUNDARY_PURPOSES))
    cursor.execute(
        f"""
        SELECT scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id = %s
          AND purpose IN ({ph})
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed > %s
        ORDER BY scanned_at_parsed ASC
        """,
        (int(organization_id), bid, *_CUSTOMER_NEW_ORDER_BOUNDARY_PURPOSES, after),
    )
    for row in cursor.fetchall() or []:
        ts = _parse_dt(row.get("scanned_at_parsed") if isinstance(row, dict) else row[0])
        if ts is None:
            continue
        if end is not None and ts > end:
            continue
        return True
    return False


def _preceding_completed_stv_oi(
    all_ois: Sequence[Mapping[str, Any]],
    valid_stv_anchors: set[datetime],
    orphan_anchor: datetime,
) -> dict[str, Any] | None:
    """Latest completed STV-backed OI whose lifecycle precedes the portal orphan."""
    candidates: list[dict[str, Any]] = []
    for o in all_ois:
        anchor = _parse_dt(o.get("cycle_anchor_at"))
        completed = _parse_dt(o.get("completed_at"))
        if anchor is None or completed is None:
            continue
        if anchor not in valid_stv_anchors:
            continue
        if anchor >= orphan_anchor:
            continue
        if completed > orphan_anchor + timedelta(hours=12):
            # Completion long after the shell is not this lifecycle.
            continue
        candidates.append(dict(o))
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            _parse_dt(r.get("cycle_anchor_at")) or datetime.min,
            int(r.get("order_instance_id") or 0),
        )
    )
    return candidates[-1]

def should_create_new_order_instance_for_cycle(
    cursor,
    organization_id: int,
    bag_id: str,
    cycle_row: Mapping[str, Any],
    *,
    prior_completed_at: datetime | None,
    boundary_timestamps: Sequence[datetime] | None = None,
) -> bool:
    """Whether this COMPLETED cycle starts a distinct order_instance.

    First completed occurrence for a bag → yes.
    Later cycle → only with authoritative new-order boundary after prior completion.
    """
    if prior_completed_at is None:
        return True
    completed = _parse_dt(cycle_row.get("completed_at"))
    anchor = _parse_dt(cycle_row.get("cycle_anchor_at"))
    before = completed or anchor
    return has_authoritative_new_order_boundary_after(
        cursor,
        organization_id,
        bag_id,
        prior_completed_at,
        before_or_at=before,
        boundary_timestamps=boundary_timestamps,
    )


def ensure_open_order_instance_for_new_active_cycle(
    cursor,
    organization_id: int,
    cycle_row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Create an open OI for a new ACTIVE cycle after a completed prior OI.

    Requires authoritative new-order boundary evidence (pickup / workitems /
    load-in) after the prior completed instance. STV-only lingering tickets
    without that boundary must not invent a new OI.

    When an open portal-discovery OI already covers the bag and this ACTIVE
    cycle is STV-backed, rebind that OI onto this cycle instead of forking.
    """
    status = str(cycle_row.get("status") or "").strip().upper()
    if status != "ACTIVE":
        return None
    if _parse_dt(cycle_row.get("completed_at")) is not None:
        return None
    bid = normalize_bag_id(cycle_row.get("bag_id"))
    anchor = _parse_dt(cycle_row.get("cycle_anchor_at"))
    if not bid or anchor is None:
        return None
    org = int(organization_id)
    svc = _svc(cycle_row.get("service_type") or "WF")
    existing = get_order_instance_by_cycle_key(
        cursor, org, bid, service_type=svc, cycle_anchor_at=anchor
    )
    if existing is not None:
        return existing
    prior = get_latest_order_instance_for_bag(
        cursor, org, bid, service_type=svc
    )
    prior_completed = _parse_dt((prior or {}).get("completed_at")) if prior else None
    if prior is not None and prior_completed is None:
        # Open prior OI — rebind portal-only orphan onto STV cycle when applicable.
        rebound = _maybe_rebind_open_portal_oi_to_stv_cycle(
            cursor, org, prior, cycle_row
        )
        return rebound or prior
    if prior_completed is not None:
        if not has_authoritative_new_order_boundary_after(
            cursor,
            org,
            bid,
            prior_completed,
            before_or_at=anchor,
        ):
            return None
    elif prior is not None:
        return prior
    return upsert_order_instance_from_cycle(cursor, org, cycle_row)


def _cycle_row_is_stv_backed(cursor, organization_id: int, cycle_row: Mapping[str, Any]) -> bool:
    """True when cycle_anchor_at matches a valid STV boundary on the bag timeline."""
    from backend.rinse_wf_service_cycle import (
        _cycle_anchor_is_stv_backed,
        _load_timeline,
    )

    bid = normalize_bag_id(cycle_row.get("bag_id"))
    anchor = _parse_dt(cycle_row.get("cycle_anchor_at"))
    if not bid or anchor is None:
        return False
    timeline = _load_timeline(cursor, int(organization_id), bid)
    return _cycle_anchor_is_stv_backed(timeline, anchor)


def _oi_source_is_portal_discovery(cursor, oi_row: Mapping[str, Any]) -> bool:
    """True when the OI's source cycle (or matching cycle) was PORTAL_DISCOVERY."""
    source_cycle_id = oi_row.get("source_cycle_id")
    if source_cycle_id is not None and table_exists(cursor, "rinse_wf_service_cycles"):
        try:
            cursor.execute(
                """
                SELECT admitted_source FROM rinse_wf_service_cycles
                WHERE id = %s LIMIT 1
                """,
                (int(source_cycle_id),),
            )
            row = cursor.fetchone() or {}
            if str(row.get("admitted_source") or "") == "PORTAL_DISCOVERY":
                return True
        except (TypeError, ValueError):
            pass
    # Fallback: open OI whose anchor is not STV-backed.
    return not _cycle_row_is_stv_backed(cursor, int(oi_row.get("organization_id") or 0), oi_row)


def _maybe_rebind_open_portal_oi_to_stv_cycle(
    cursor,
    organization_id: int,
    open_oi: Mapping[str, Any],
    stv_cycle_row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Re-key an open portal-discovery OI onto a legitimate STV ACTIVE cycle."""
    if not _cycle_row_is_stv_backed(cursor, organization_id, stv_cycle_row):
        return None
    oi_with_org = dict(open_oi)
    oi_with_org.setdefault("organization_id", organization_id)
    if not _oi_source_is_portal_discovery(cursor, oi_with_org):
        return None
    oid = int(open_oi["order_instance_id"])
    new_anchor = _parse_dt(stv_cycle_row.get("cycle_anchor_at"))
    if new_anchor is None:
        return None
    # Do not steal a completed OI or collide with an existing cycle key.
    conflict = get_order_instance_by_cycle_key(
        cursor,
        organization_id,
        open_oi.get("bag_id"),
        service_type=_svc(open_oi.get("service_type") or "WF"),
        cycle_anchor_at=new_anchor,
    )
    if conflict is not None and int(conflict["order_instance_id"]) != oid:
        return None
    source_cycle_id = None
    try:
        if stv_cycle_row.get("id") is not None:
            source_cycle_id = int(stv_cycle_row["id"])
    except (TypeError, ValueError):
        source_cycle_id = None
    cursor.execute(
        f"""
        UPDATE {ORDER_INSTANCES_TABLE}
        SET cycle_anchor_at = %s,
            source_cycle_id = COALESCE(%s, source_cycle_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE order_instance_id = %s
          AND completed_at IS NULL
        """,
        (new_anchor, source_cycle_id, oid),
    )
    return get_order_instance_by_id(cursor, oid)


def heal_same_lifecycle_portal_orphan_ois(
    cursor,
    organization_id: int,
    *,
    bag_ids: Sequence[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Bounded heal: delete proven portal-discovery OI orphans for one org.

    Candidate proof (all required):
    - orphan OI is open
    - orphan cycle admitted_source = PORTAL_DISCOVERY (or anchor not STV-backed)
    - a preceding completed STV-backed OI exists with anchor < orphan anchor
    - orphan anchor is strictly after that STV anchor
    - no customer new-order boundary (pickup/workitems) between STV completion
      and orphan anchor — bare post-completion load-in is logistics, not a
      new lifecycle (creation gates still use load-in)

    Does not touch the three genuine stale-registry Review OIs.
    """
    from backend.rinse_wf_service_cycle import (
        SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
        STATUS_ACTIVE,
        STATUS_RESOLVED_OTHER,
        STATUS_REVIEW,
        _load_timeline,
        _valid_cycle_anchors,
    )

    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "organization_id": org,
        "candidates": [],
        "healed": [],
        "ambiguous": [],
        "skipped_genuine_review": [],
    }
    genuine_protect = {
        ("BUEKCP33J1", 3585),
        ("BZ9AOU641G", 3963),
        ("C1PI050KEU", 3587),
    }
    scope = sorted({normalize_bag_id(b) for b in (bag_ids or []) if normalize_bag_id(b)})
    if scope:
        ph = ", ".join(["%s"] * len(scope))
        cursor.execute(
            f"""
            SELECT * FROM {ORDER_INSTANCES_TABLE}
            WHERE organization_id = %s AND service_type = 'WF'
              AND bag_id IN ({ph})
            ORDER BY bag_id, cycle_anchor_at, order_instance_id
            """,
            (org, *scope),
        )
    else:
        cursor.execute(
            f"""
            SELECT * FROM {ORDER_INSTANCES_TABLE}
            WHERE organization_id = %s AND service_type = 'WF'
              AND completed_at IS NULL
            ORDER BY bag_id, cycle_anchor_at, order_instance_id
            """,
            (org,),
        )
    open_orphans = [
        dict(r)
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict) and _parse_dt(r.get("completed_at")) is None
    ]
    # If scoped with bag_ids, also include open rows only was wrong — reload all
    # OIs per bag for those bags when scope set.
    bags_needed = sorted({normalize_bag_id(r.get("bag_id")) for r in open_orphans if normalize_bag_id(r.get("bag_id"))})
    if not scope:
        bags_needed = bags_needed  # all bags with open OIs
    for bid in bags_needed:
        all_ois = list_order_instances_for_bag(cursor, org, bid, service_type="WF")
        if len(all_ois) < 2:
            continue
        timeline = _load_timeline(cursor, org, bid)
        valid = set(_valid_cycle_anchors(timeline))
        stv_ois = [
            o
            for o in all_ois
            if isinstance(o.get("cycle_anchor_at"), datetime)
            and o["cycle_anchor_at"] in valid
        ]
        portal_open = [
            o
            for o in all_ois
            if _parse_dt(o.get("completed_at")) is None
            and isinstance(o.get("cycle_anchor_at"), datetime)
            and o["cycle_anchor_at"] not in valid
            and _oi_source_is_portal_discovery(
                cursor, {**o, "organization_id": org}
            )
        ]
        if not portal_open or not stv_ois:
            continue
        for orphan in portal_open:
            oid = int(orphan["order_instance_id"])
            o_anchor = _parse_dt(orphan.get("cycle_anchor_at"))
            if o_anchor is None:
                report["ambiguous"].append(
                    {"bag_id": bid, "orphan_oi": oid, "reason": "orphan_anchor_missing"}
                )
                continue
            if (bid, oid) in genuine_protect:
                report["skipped_genuine_review"].append(
                    {"bag_id": bid, "order_instance_id": oid}
                )
                continue
            # Correct preceding lifecycle: completed STV OI before this shell —
            # never a later unrelated reusable-bag OI.
            legit = _preceding_completed_stv_oi(all_ois, valid, o_anchor)
            if legit is None:
                report["ambiguous"].append(
                    {
                        "bag_id": bid,
                        "orphan_oi": oid,
                        "reason": "no_preceding_completed_stv_oi",
                    }
                )
                continue
            legit_anchor = _parse_dt(legit.get("cycle_anchor_at"))
            legit_completed = _parse_dt(legit.get("completed_at"))
            if legit_anchor is None or legit_completed is None:
                report["ambiguous"].append(
                    {
                        "bag_id": bid,
                        "orphan_oi": oid,
                        "reason": "preceding_stv_incomplete",
                    }
                )
                continue
            if o_anchor <= legit_anchor:
                report["ambiguous"].append(
                    {
                        "bag_id": bid,
                        "orphan_oi": oid,
                        "reason": "orphan_anchor_not_after_stv",
                    }
                )
                continue
            # Customer new-order boundary only (not post-completion load-in).
            if has_customer_new_order_boundary_after(
                cursor,
                org,
                bid,
                legit_completed,
                before_or_at=o_anchor,
            ):
                report["ambiguous"].append(
                    {
                        "bag_id": bid,
                        "orphan_oi": oid,
                        "reason": "customer_boundary_between_stv_and_orphan",
                        "legitimate_oi": int(legit["order_instance_id"]),
                    }
                )
                continue
            cand = {
                "bag_id": bid,
                "orphan_oi": oid,
                "legitimate_oi": int(legit["order_instance_id"]),
                "orphan_anchor": str(o_anchor),
                "legitimate_lifecycle_anchor": str(legit_anchor),
                "completion_at": str(legit_completed),
                "evidence": (
                    "portal_discovery_shell_after_preceding_completed_stv_"
                    "no_customer_new_order_boundary"
                ),
            }
            report["candidates"].append(cand)
            if dry_run:
                continue
            if orphan.get("source_cycle_id") is not None:
                cursor.execute(
                    """
                    UPDATE rinse_wf_service_cycles
                    SET status = %s,
                        review_reason = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND organization_id = %s
                      AND status IN (%s, %s)
                    """,
                    (
                        STATUS_RESOLVED_OTHER,
                        SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
                        int(orphan["source_cycle_id"]),
                        org,
                        STATUS_ACTIVE,
                        STATUS_REVIEW,
                    ),
                )
            cursor.execute(
                f"""
                DELETE FROM {ORDER_INSTANCES_TABLE}
                WHERE order_instance_id = %s
                  AND organization_id = %s
                  AND completed_at IS NULL
                """,
                (oid, org),
            )
            # Prevent scrape from recreating shells from leftover portal cycles.
            cursor.execute(
                """
                UPDATE rinse_wf_service_cycles
                SET status = %s,
                    review_reason = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = %s
                  AND bag_id = %s
                  AND status IN (%s, %s)
                  AND UPPER(COALESCE(admitted_source, '')) = 'PORTAL_DISCOVERY'
                """,
                (
                    STATUS_RESOLVED_OTHER,
                    SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
                    org,
                    bid,
                    STATUS_ACTIVE,
                    STATUS_REVIEW,
                ),
            )
            report["healed"].append(cand)
    return report


def stamp_open_oi_from_lifecycle_completion_evidence(
    cursor,
    organization_id: int,
    oi_row: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Stamp open WF OI + owning cycle from OI-window canonical/v2 evidence.

    Uses existing ``upsert_service_cycle`` → ``sync_order_instance_on_cycle_completion``.
    Does not invent completion signals. Does not touch other bags' OIs.
    """
    from backend.rinse_bag_completion import REASON_STRONG_COMPLETION_EVIDENCE
    from backend.rinse_wf_current_workload import (
        _next_oi_cycle_anchor,
        evaluate_oi_lifecycle_completion_evidence,
    )
    from backend.rinse_wf_service_cycle import (
        STATUS_COMPLETED,
        get_cycle_by_key,
        upsert_service_cycle,
    )

    org = int(organization_id)
    bid = normalize_bag_id(oi_row.get("bag_id"))
    anchor = _parse_dt(oi_row.get("cycle_anchor_at"))
    oid = oi_row.get("order_instance_id")
    out: dict[str, Any] = {
        "ok": False,
        "dry_run": bool(dry_run),
        "bag_id": bid,
        "order_instance_id": oid,
        "action": None,
    }
    if not bid or anchor is None:
        out["error"] = "invalid_oi"
        return out
    if _parse_dt(oi_row.get("completed_at")) is not None:
        out["ok"] = True
        out["action"] = "already_completed"
        return out

    end = _next_oi_cycle_anchor(cursor, org, bid, anchor)
    ev = evidence or evaluate_oi_lifecycle_completion_evidence(
        cursor,
        org,
        bag_id=bid,
        cycle_anchor_at=anchor,
        lifecycle_end_exclusive=end,
    )
    if not ev or not isinstance(ev.get("completion_at"), datetime):
        out["error"] = "no_lifecycle_completion_evidence"
        return out

    completion_at = ev["completion_at"]
    if bool(ev.get("via_clean_rack")):
        completion_source = "CLEAN_RACK_SCANNED"
    else:
        completion_source = REASON_STRONG_COMPLETION_EVIDENCE
    out.update(
        {
            "ok": True,
            "action": "stamp_oi_completed",
            "completion_at": str(completion_at),
            "completion_source": completion_source,
            "completion_kind": ev.get("completion_kind"),
            "evidence_family": ev.get("evidence_family"),
        }
    )
    if dry_run:
        return out

    existing = get_cycle_by_key(cursor, org, bid, anchor) or {}
    admitted_source = str(existing.get("admitted_source") or "").strip()
    if not admitted_source:
        admitted_source = "SCAN_EVIDENCE_REFRESH"
    row = upsert_service_cycle(
        cursor,
        org,
        bag_id=bid,
        cycle_anchor_at=anchor,
        admitted_at=existing.get("admitted_at") or anchor,
        admitted_source=admitted_source,
        status=STATUS_COMPLETED,
        completed_at=completion_at,
        completion_source=completion_source,
        rush_status=existing.get("rush_status"),
        estimated_delivery_date=existing.get("estimated_delivery_date"),
        pre_weight_lbs=existing.get("pre_weight_lbs"),
        post_weight_lbs=existing.get("post_weight_lbs"),
        portal_last_seen_at=existing.get("portal_last_seen_at"),
    )
    stamped = upsert_order_instance_from_cycle(
        cursor,
        org,
        {
            **(row or {}),
            "bag_id": bid,
            "service_type": "WF",
            "status": STATUS_COMPLETED,
            "cycle_anchor_at": anchor,
            "completed_at": completion_at,
            "completion_source": completion_source,
            "id": (row or {}).get("id") or existing.get("id") or oi_row.get("source_cycle_id"),
        },
        completed_by_employee_name=ev.get("completion_user"),
    )
    out["stamped_oi"] = (stamped or {}).get("order_instance_id") or oid
    return out


def classify_and_stamp_open_ois_lifecycle_completion(
    cursor,
    organization_id: int,
    *,
    dry_run: bool = True,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Classify open WF OIs; optionally stamp those with lifecycle completion evidence."""
    from backend.rinse_wf_current_workload import (
        _next_oi_cycle_anchor,
        _registry_completed_at_in_oi_window,
        _registry_row_for_bag,
        evaluate_oi_lifecycle_completion_evidence,
    )

    org = int(organization_id)
    ensure_rinse_order_instances_table(cursor)
    open_rows = list_open_wf_order_instances(cursor, org, service_type="WF")
    scope = None
    if bag_ids:
        scope = {normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)}
        open_rows = [
            r for r in open_rows if normalize_bag_id(r.get("bag_id")) in scope
        ]

    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "organization_id": org,
        "should_close": [],
        "pending": [],
        "review": [],
        "stamped": [],
        "errors": [],
    }
    # Pass 1: classify only (no writes) so stamp SQL cannot interfere with evidence reads.
    close_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in open_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        anchor = _parse_dt(row.get("cycle_anchor_at"))
        oid = row.get("order_instance_id")
        if not bid or anchor is None:
            continue
        end = _next_oi_cycle_anchor(cursor, org, bid, anchor)
        evidence = evaluate_oi_lifecycle_completion_evidence(
            cursor,
            org,
            bag_id=bid,
            cycle_anchor_at=anchor,
            lifecycle_end_exclusive=end,
        )
        reg = _registry_row_for_bag(cursor, org, bid)
        reg_same = _registry_completed_at_in_oi_window(reg, anchor, end)
        entry = {
            "bag_id": bid,
            "order_instance_id": oid,
            "cycle_anchor_at": str(anchor),
            "registry_completed_at": str(reg.get("completed_at"))
            if reg and reg.get("completed_at")
            else None,
            "registry_same_lifecycle": reg_same,
        }
        if evidence is not None:
            entry["evidence"] = {
                "completion_at": str(evidence.get("completion_at")),
                "completion_kind": evidence.get("completion_kind"),
                "evidence_family": evidence.get("evidence_family"),
            }
            report["should_close"].append(entry)
            close_rows.append((dict(row), evidence))
            continue
        if reg_same:
            entry["reason"] = "same_lifecycle_registry_without_evidence"
            report["review"].append(entry)
        else:
            entry["reason"] = "genuinely_open"
            report["pending"].append(entry)

    # Pass 2: stamp proven completions.
    for row, evidence in close_rows:
        stamped = stamp_open_oi_from_lifecycle_completion_evidence(
            cursor, org, row, evidence=evidence, dry_run=dry_run
        )
        if stamped.get("ok") and stamped.get("action") in (
            "stamp_oi_completed",
            "already_completed",
        ):
            report["stamped"].append(stamped)
        elif not stamped.get("ok"):
            report["errors"].append(stamped)
    report["counts"] = {
        "open_before": len(open_rows),
        "should_close": len(report["should_close"]),
        "pending": len(report["pending"]),
        "review": len(report["review"]),
        "stamped": len(report["stamped"]),
        "errors": len(report["errors"]),
    }
    return report


def repair_open_portal_oi_with_stv_strong_completion(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Bind STV-owned OI + stamp strong completion; remove portal shell.

    Uses existing ``evaluate_bag_completion_v2`` / STRONG_COMPLETION_EVIDENCE
    signals (QC / processed-by-vendor / …) scoped to the STV lifecycle window.
    Does not invent a new completion definition.
    """
    from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
    from backend.rinse_bag_completion import REASON_STRONG_COMPLETION_EVIDENCE
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_wf_service_cycle import (
        STATUS_ACTIVE,
        STATUS_COMPLETED,
        STATUS_RESOLVED_OTHER,
        STATUS_REVIEW,
        SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
        _load_timeline,
        _valid_cycle_anchors,
        get_cycle_by_key,
        upsert_service_cycle,
    )

    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    out: dict[str, Any] = {
        "ok": False,
        "dry_run": bool(dry_run),
        "bag_id": bid,
        "action": None,
    }
    if not bid:
        out["error"] = "invalid_bag_id"
        return out
    all_ois = list_order_instances_for_bag(cursor, org, bid, service_type="WF")
    open_ois = [o for o in all_ois if _parse_dt(o.get("completed_at")) is None]
    if not open_ois:
        out["error"] = "no_open_oi"
        return out
    # Never touch the three genuine Review OIs.
    genuine_protect = {3585, 3587, 3963}
    if any(int(o["order_instance_id"]) in genuine_protect for o in open_ois):
        out["error"] = "genuine_review_protected"
        return out

    timeline = _load_timeline(cursor, org, bid)
    valid = list(_valid_cycle_anchors(timeline))
    valid_set = set(valid)
    if not valid:
        out["error"] = "no_stv_anchor"
        return out
    portal_shells = [
        o
        for o in open_ois
        if isinstance(o.get("cycle_anchor_at"), datetime)
        and o["cycle_anchor_at"] not in valid_set
        and _oi_source_is_portal_discovery(cursor, {**o, "organization_id": org})
    ]
    if not portal_shells:
        out["error"] = "no_portal_shell"
        return out
    portal_anchors = [
        _parse_dt(o.get("cycle_anchor_at"))
        for o in portal_shells
        if _parse_dt(o.get("cycle_anchor_at")) is not None
    ]
    earliest_portal = min(portal_anchors) if portal_anchors else None
    # STV lifecycle that owns this production: latest valid STV before the shell.
    preceding_stvs = [
        a for a in valid if earliest_portal is None or a < earliest_portal
    ]
    if not preceding_stvs:
        out["error"] = "no_stv_before_portal_shell"
        out["portal_shell_ois"] = [int(o["order_instance_id"]) for o in portal_shells]
        return out
    stv_anchor = preceding_stvs[-1]

    # Strong completion evidence on/after this STV (existing v2 path).
    # Cap at next STV so a later reusable-bag lifecycle cannot bleed in.
    next_stvs = [a for a in valid if a > stv_anchor]
    window_end = next_stvs[0] if next_stvs else None
    scoped = [
        e
        for e in timeline
        if isinstance(e.get("scanned_at_parsed"), datetime)
        and e["scanned_at_parsed"] >= stv_anchor
        and (window_end is None or e["scanned_at_parsed"] < window_end)
    ]
    v2 = evaluate_bag_completion_v2(gaming_events_from_records(scoped))
    if not v2.completed or not isinstance(v2.completion_at, datetime):
        out["error"] = "no_strong_completion_in_stv_window"
        out["stv_anchor"] = str(stv_anchor)
        out["v2"] = {
            "completed": bool(v2.completed),
            "kind": v2.completion_kind,
        }
        return out
    if v2.completion_at < stv_anchor:
        out["error"] = "strong_completion_before_stv"
        return out

    completion_source = REASON_STRONG_COMPLETION_EVIDENCE
    out.update(
        {
            "ok": True,
            "stv_anchor": str(stv_anchor),
            "completion_at": str(v2.completion_at),
            "completion_kind": v2.completion_kind,
            "completion_source": completion_source,
            "completion_user": v2.completion_user,
            "portal_shell_ois": [int(o["order_instance_id"]) for o in portal_shells],
            "action": "stamp_stv_oi_delete_portal_shells",
        }
    )
    if dry_run:
        return out

    # Complete / upsert the STV service cycle; sync stamps the OI.
    existing = get_cycle_by_key(cursor, org, bid, stv_anchor) or {}
    admitted_source = str(existing.get("admitted_source") or "").strip()
    if not admitted_source or admitted_source.upper() == "PORTAL_DISCOVERY":
        admitted_source = "SCAN_EVIDENCE_REFRESH"
    row = upsert_service_cycle(
        cursor,
        org,
        bag_id=bid,
        cycle_anchor_at=stv_anchor,
        admitted_at=existing.get("admitted_at") or stv_anchor,
        admitted_source=admitted_source,
        status=STATUS_COMPLETED,
        completed_at=v2.completion_at,
        completion_source=completion_source,
        rush_status=existing.get("rush_status"),
        estimated_delivery_date=existing.get("estimated_delivery_date"),
        pre_weight_lbs=existing.get("pre_weight_lbs"),
        post_weight_lbs=existing.get("post_weight_lbs"),
        portal_last_seen_at=existing.get("portal_last_seen_at"),
    )
    stamped = upsert_order_instance_from_cycle(
        cursor,
        org,
        {
            **(row or {}),
            "bag_id": bid,
            "service_type": "WF",
            "status": STATUS_COMPLETED,
            "cycle_anchor_at": stv_anchor,
            "completed_at": v2.completion_at,
            "completion_source": completion_source,
            "id": (row or {}).get("id") or existing.get("id"),
        },
        completed_by_employee_name=v2.completion_user,
    )
    out["stamped_oi"] = (stamped or {}).get("order_instance_id")

    # Remove open portal shells only (and supersede their portal cycles).
    for shell in portal_shells:
        sid = shell.get("source_cycle_id")
        if sid is not None:
            cursor.execute(
                """
                UPDATE rinse_wf_service_cycles
                SET status = %s,
                    review_reason = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND organization_id = %s
                  AND status IN (%s, %s)
                """,
                (
                    STATUS_RESOLVED_OTHER,
                    SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
                    int(sid),
                    org,
                    STATUS_ACTIVE,
                    STATUS_REVIEW,
                ),
            )
        cursor.execute(
            f"""
            DELETE FROM {ORDER_INSTANCES_TABLE}
            WHERE order_instance_id = %s
              AND organization_id = %s
              AND completed_at IS NULL
            """,
            (int(shell["order_instance_id"]), org),
        )
    # Supersede any other open PORTAL_DISCOVERY cycles for this bag so scrape
    # cannot recreate a shell OI after the STV lifecycle is stamped complete.
    keeper_id = (row or {}).get("id") or existing.get("id")
    cursor.execute(
        """
        UPDATE rinse_wf_service_cycles
        SET status = %s,
            review_reason = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s
          AND bag_id = %s
          AND status IN (%s, %s)
          AND UPPER(COALESCE(admitted_source, '')) = 'PORTAL_DISCOVERY'
          AND (%s IS NULL OR id <> %s)
        """,
        (
            STATUS_RESOLVED_OTHER,
            SUPERSEDED_PORTAL_DISCOVERY_DUPLICATE,
            org,
            bid,
            STATUS_ACTIVE,
            STATUS_REVIEW,
            keeper_id,
            keeper_id,
        ),
    )
    return out


def get_order_instance_by_id(
    cursor, order_instance_id: int
) -> dict[str, Any] | None:
    ensure_rinse_order_instances_table(cursor)
    cursor.execute(
        f"""
        SELECT * FROM {ORDER_INSTANCES_TABLE}
        WHERE order_instance_id = %s
        LIMIT 1
        """,
        (int(order_instance_id),),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def get_order_instance_by_cycle_key(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    service_type: str = "WF",
    cycle_anchor_at: datetime,
) -> dict[str, Any] | None:
    ensure_rinse_order_instances_table(cursor)
    bid = normalize_bag_id(bag_id)
    anchor = _parse_dt(cycle_anchor_at)
    if not bid or anchor is None:
        return None
    cursor.execute(
        f"""
        SELECT * FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND bag_id = %s
          AND service_type = %s
          AND cycle_anchor_at = %s
        LIMIT 1
        """,
        (int(organization_id), bid, _svc(service_type), anchor),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def get_order_instance_by_source_cycle_id(
    cursor, source_cycle_id: int
) -> dict[str, Any] | None:
    ensure_rinse_order_instances_table(cursor)
    cursor.execute(
        f"""
        SELECT * FROM {ORDER_INSTANCES_TABLE}
        WHERE source_cycle_id = %s
        LIMIT 1
        """,
        (int(source_cycle_id),),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def list_order_instances_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    service_type: str | None = None,
) -> list[dict[str, Any]]:
    ensure_rinse_order_instances_table(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    sql = f"""
        SELECT * FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s AND bag_id = %s
    """
    params: list[Any] = [int(organization_id), bid]
    if service_type is not None:
        sql += " AND service_type = %s"
        params.append(_svc(service_type))
    sql += " ORDER BY cycle_anchor_at ASC, order_instance_id ASC"
    cursor.execute(sql, tuple(params))
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def get_latest_order_instance_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    service_type: str | None = "WF",
) -> dict[str, Any] | None:
    rows = list_order_instances_for_bag(
        cursor, organization_id, bag_id, service_type=service_type
    )
    return rows[-1] if rows else None


def list_open_wf_order_instances(
    cursor,
    organization_id: int,
    *,
    service_type: str = "WF",
) -> list[dict[str, Any]]:
    """All open (``completed_at IS NULL``) WF order instances.

    Does **not** collapse to MAX(order_instance_id) per bag — orphan portal
    duplicates must remain visible until healed, and completion ownership is
    cycle-keyed rather than latest-id.
    """
    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    svc = _svc(service_type)
    cursor.execute(
        f"""
        SELECT *
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND service_type = %s
          AND completed_at IS NULL
        ORDER BY bag_id ASC, cycle_anchor_at ASC, order_instance_id ASC
        """,
        (org, svc),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def list_order_instances_completed_on_date(
    cursor,
    organization_id: int,
    date_et: date,
    *,
    service_type: str = "WF",
) -> list[dict[str, Any]]:
    """Order instances whose authoritative completion falls on ET date ``date_et``."""
    from backend.business_time import system_datetime_to_et

    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    svc = _svc(service_type)
    day_start = naive_et_day_start(date_et)
    day_end = day_start + timedelta(days=1)
    pad_start = day_start - timedelta(hours=6)
    pad_end = day_end + timedelta(hours=6)
    cursor.execute(
        f"""
        SELECT *
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND service_type = %s
          AND completed_at IS NOT NULL
          AND completed_at >= %s
          AND completed_at < %s
        """,
        (org, svc, pad_start, pad_end),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        completed_at = _parse_dt(row.get("completed_at"))
        if completed_at is None:
            continue
        et = system_datetime_to_et(completed_at)
        if et is not None and et.date() == date_et:
            out.append(dict(row))
    return out


def upsert_order_instance_from_cycle(
    cursor,
    organization_id: int,
    cycle_row: Mapping[str, Any],
    *,
    completed_by_employee_name: str | None = None,
    completed_by_user_id: int | None = None,
) -> dict[str, Any] | None:
    """Create/update one order instance from an authoritative service-cycle row.

    Requires cycle_anchor_at. COMPLETED cycles stamp completed_*; ACTIVE/REVIEW
    may create an open instance (completed_at NULL) only when explicitly
    requested via a COMPLETED row or when syncing completion fields from a
    later COMPLETED cycle. Stale REVIEW duplicates must not invent instances —
    callers should pass authoritative COMPLETED cycles for backfill.
    """
    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(cycle_row.get("bag_id"))
    anchor = _parse_dt(cycle_row.get("cycle_anchor_at"))
    if not bid or anchor is None:
        return None
    svc = _svc(cycle_row.get("service_type") or "WF")
    source_cycle_id = None
    try:
        if cycle_row.get("id") is not None:
            source_cycle_id = int(cycle_row["id"])
    except (TypeError, ValueError):
        source_cycle_id = None

    status = str(cycle_row.get("status") or "").strip().upper()
    completed_at = _parse_dt(cycle_row.get("completed_at"))
    completion_source = (
        str(cycle_row.get("completion_source") or "").strip() or None
    )
    # Only COMPLETED cycles (or rows with completed_at) become completed instances.
    if status != "COMPLETED" and completed_at is None:
        # Open instance: only if this is clearly the current admitted ACTIVE cycle
        # with no completed_at. Prefer not creating from REVIEW/stale rows.
        if status not in ("ACTIVE",):
            return get_order_instance_by_cycle_key(
                cursor, org, bid, service_type=svc, cycle_anchor_at=anchor
            ) or (
                get_order_instance_by_source_cycle_id(cursor, source_cycle_id)
                if source_cycle_id
                else None
            )

    emp = (
        str(completed_by_employee_name or "").strip()
        or None
    )

    # Prefer existing by source_cycle_id or cycle key (idempotent).
    existing = None
    if source_cycle_id is not None:
        existing = get_order_instance_by_source_cycle_id(cursor, source_cycle_id)
    if existing is None:
        existing = get_order_instance_by_cycle_key(
            cursor, org, bid, service_type=svc, cycle_anchor_at=anchor
        )

    if existing:
        oid = int(existing["order_instance_id"])
        # Never clear a completed stamp; only fill forward.
        new_completed = completed_at or _parse_dt(existing.get("completed_at"))
        new_source = completion_source or existing.get("completion_source")
        new_emp = emp or existing.get("completed_by_employee_name")
        new_uid = completed_by_user_id
        if new_uid is None and existing.get("completed_by_user_id") is not None:
            try:
                new_uid = int(existing["completed_by_user_id"])
            except (TypeError, ValueError):
                new_uid = None
        new_cycle_id = source_cycle_id or existing.get("source_cycle_id")
        cursor.execute(
            f"""
            UPDATE {ORDER_INSTANCES_TABLE}
            SET source_cycle_id = COALESCE(%s, source_cycle_id),
                completed_at = COALESCE(%s, completed_at),
                completed_by_user_id = COALESCE(%s, completed_by_user_id),
                completed_by_employee_name = COALESCE(%s, completed_by_employee_name),
                completion_source = COALESCE(%s, completion_source),
                updated_at = CURRENT_TIMESTAMP
            WHERE order_instance_id = %s
            """,
            (new_cycle_id, new_completed, new_uid, new_emp, new_source, oid),
        )
        return get_order_instance_by_id(cursor, oid)

    # Prefer rebinding an open portal-discovery OI onto this completing STV cycle
    # instead of inserting a second OI for the same lifecycle.
    if status == "COMPLETED" or completed_at is not None:
        open_rows = [
            r
            for r in list_order_instances_for_bag(cursor, org, bid, service_type=svc)
            if _parse_dt(r.get("completed_at")) is None
        ]
        for open_oi in open_rows:
            rebound = _maybe_rebind_open_portal_oi_to_stv_cycle(
                cursor, org, open_oi, cycle_row
            )
            target = rebound
            if target is None and _parse_dt(open_oi.get("cycle_anchor_at")) == anchor:
                target = open_oi
            if target is None:
                continue
            oid = int(target["order_instance_id"])
            cursor.execute(
                f"""
                UPDATE {ORDER_INSTANCES_TABLE}
                SET completed_at = COALESCE(%s, completed_at),
                    completed_by_user_id = COALESCE(%s, completed_by_user_id),
                    completed_by_employee_name = COALESCE(%s, completed_by_employee_name),
                    completion_source = COALESCE(%s, completion_source),
                    source_cycle_id = COALESCE(%s, source_cycle_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_instance_id = %s
                """,
                (
                    completed_at,
                    completed_by_user_id,
                    emp,
                    completion_source,
                    source_cycle_id,
                    oid,
                ),
            )
            return get_order_instance_by_id(cursor, oid)
        # Open OI(s) exist but none matched this cycle — never invent a second
        # OI while the bag still has an open instance (same-lifecycle guard).
        if open_rows:
            oid = int(open_rows[-1]["order_instance_id"])
            return get_order_instance_by_id(cursor, oid)

    # New cycle_anchor → new instance only with authoritative new-order evidence.
    # Duplicate/reconciliation completed cycles merge into the latest instance.
    latest = get_latest_order_instance_for_bag(
        cursor, org, bid, service_type=svc
    )
    prior_completed = (
        _parse_dt(latest.get("completed_at")) if latest else None
    )
    if latest is not None and prior_completed is None:
        # Still open — do not insert another OI for this bag.
        return get_order_instance_by_id(cursor, int(latest["order_instance_id"]))
    if latest is not None and not should_create_new_order_instance_for_cycle(
        cursor,
        org,
        bid,
        cycle_row,
        prior_completed_at=prior_completed,
    ):
        oid = int(latest["order_instance_id"])
        new_completed = completed_at or prior_completed
        new_source = completion_source or latest.get("completion_source")
        new_emp = emp or latest.get("completed_by_employee_name")
        cursor.execute(
            f"""
            UPDATE {ORDER_INSTANCES_TABLE}
            SET completed_at = COALESCE(%s, completed_at),
                completed_by_employee_name = COALESCE(%s, completed_by_employee_name),
                completion_source = COALESCE(%s, completion_source),
                updated_at = CURRENT_TIMESTAMP
            WHERE order_instance_id = %s
            """,
            (new_completed, new_emp, new_source, oid),
        )
        return get_order_instance_by_id(cursor, oid)

    cursor.execute(
        f"""
        INSERT INTO {ORDER_INSTANCES_TABLE} (
          organization_id, bag_id, service_type, cycle_anchor_at, source_cycle_id,
          completed_at, completed_by_user_id, completed_by_employee_name,
          completion_source
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            org,
            bid,
            svc,
            anchor,
            source_cycle_id,
            completed_at if status == "COMPLETED" or completed_at else None,
            completed_by_user_id,
            emp,
            completion_source if (status == "COMPLETED" or completed_at) else None,
        ),
    )
    new_id = cursor.lastrowid
    if new_id:
        return get_order_instance_by_id(cursor, int(new_id))
    return get_order_instance_by_cycle_key(
        cursor, org, bid, service_type=svc, cycle_anchor_at=anchor
    )


def is_authoritative_completed_cycle(cycle_row: Mapping[str, Any]) -> bool:
    """True for a real completed service occurrence (not stale REVIEW shells)."""
    status = str(cycle_row.get("status") or "").strip().upper()
    if status != "COMPLETED":
        return False
    if _parse_dt(cycle_row.get("cycle_anchor_at")) is None:
        return False
    if _parse_dt(cycle_row.get("completed_at")) is None:
        return False
    return True


def backfill_order_instances_from_service_cycles(
    cursor,
    organization_id: int | None = None,
    *,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Idempotent backfill from COMPLETED cycles with new-order boundary gating.

    Multiple reconciliation COMPLETED cycles for one real order map to one
    instance. A later cycle becomes a new instance only when pickup/workitems/
    load-in proves a distinct occurrence after the prior completion.
    """
    ensure_rinse_order_instances_table(cursor)
    if not table_exists(cursor, "rinse_wf_service_cycles"):
        return {"created": 0, "updated": 0, "skipped": 0, "bags_multi": 0}

    where = ["status = 'COMPLETED'", "completed_at IS NOT NULL", "cycle_anchor_at IS NOT NULL"]
    params: list[Any] = []
    if organization_id is not None:
        where.append("organization_id = %s")
        params.append(int(organization_id))
    if bag_ids:
        ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
        if not ids:
            return {"created": 0, "updated": 0, "skipped": 0, "bags_multi": 0}
        ph = ",".join(["%s"] * len(ids))
        where.append(f"UPPER(bag_id) IN ({ph})")
        params.extend(ids)

    cursor.execute(
        f"""
        SELECT id, organization_id, bag_id, cycle_anchor_at, admitted_at,
               status, completed_at, completion_source, rush_status
        FROM rinse_wf_service_cycles
        WHERE {' AND '.join(where)}
        ORDER BY organization_id, bag_id, completed_at, cycle_anchor_at, id
        """,
        tuple(params),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]

    created = updated = skipped = 0
    before_ids: set[int] = set()
    cursor.execute(
        f"SELECT order_instance_id FROM {ORDER_INSTANCES_TABLE}"
        + (" WHERE organization_id = %s" if organization_id is not None else ""),
        (int(organization_id),) if organization_id is not None else (),
    )
    for r in cursor.fetchall() or []:
        try:
            before_ids.add(int(r["order_instance_id"] if isinstance(r, dict) else r[0]))
        except (TypeError, ValueError, KeyError):
            pass

    # Per bag: only seed instances from cycles that pass new-order gating.
    by_bag: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        if not is_authoritative_completed_cycle(row):
            skipped += 1
            continue
        org_i = int(row["organization_id"])
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            skipped += 1
            continue
        by_bag.setdefault((org_i, bid), []).append(row)

    # One scan round-trip per org scope (not per bag).
    all_bags = sorted({bid for (_o, bid) in by_bag.keys()})
    boundaries_by_bag: dict[str, list[datetime]] = {}
    if organization_id is not None:
        boundaries_by_bag = load_new_order_boundary_timestamps_for_bags(
            cursor, int(organization_id), all_bags
        )
    else:
        by_org_bags: dict[int, list[str]] = {}
        for org_i, bid in by_bag.keys():
            by_org_bags.setdefault(org_i, []).append(bid)
        for org_i, bags in by_org_bags.items():
            boundaries_by_bag.update(
                load_new_order_boundary_timestamps_for_bags(cursor, org_i, bags)
            )

    for (org_i, bid), cycles in by_bag.items():
        prior_completed: datetime | None = None
        boundaries = boundaries_by_bag.get(bid) or []
        for row in cycles:
            row = dict(row)
            row.setdefault("service_type", "WF")
            if not should_create_new_order_instance_for_cycle(
                cursor,
                org_i,
                bid,
                row,
                prior_completed_at=prior_completed,
                boundary_timestamps=boundaries,
            ):
                # Merge evidence into latest instance; do not create another.
                skipped += 1
                latest = get_latest_order_instance_for_bag(
                    cursor, org_i, bid, service_type="WF"
                )
                if latest is not None:
                    upsert_order_instance_from_cycle(cursor, org_i, row)
                    updated += 1
                continue
            cid = int(row["id"]) if row.get("id") is not None else None
            prior = (
                get_order_instance_by_source_cycle_id(cursor, cid) if cid else None
            )
            if prior is None:
                prior = get_order_instance_by_cycle_key(
                    cursor,
                    org_i,
                    bid,
                    service_type="WF",
                    cycle_anchor_at=_parse_dt(row.get("cycle_anchor_at")),  # type: ignore[arg-type]
                )
            inst = upsert_order_instance_from_cycle(cursor, org_i, row)
            if inst is None:
                skipped += 1
                continue
            oid = int(inst["order_instance_id"])
            if prior is None and oid not in before_ids:
                created += 1
                before_ids.add(oid)
            else:
                updated += 1
            prior_completed = _parse_dt(inst.get("completed_at")) or prior_completed

    bags_multi = 0
    cursor.execute(
        f"""
        SELECT bag_id, COUNT(*) AS n
        FROM {ORDER_INSTANCES_TABLE}
        WHERE 1=1
        {" AND organization_id = %s" if organization_id is not None else ""}
        GROUP BY organization_id, bag_id
        HAVING COUNT(*) > 1
        """,
        (int(organization_id),) if organization_id is not None else (),
    )
    bags_multi = len(cursor.fetchall() or [])

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "bags_multi": bags_multi,
        "completed_cycles_seen": len(rows),
    }


def rebuild_order_instances_for_org(cursor, organization_id: int) -> dict[str, Any]:
    """Replace derived org order_instances from the corrected resolver.

    Deletes only rinse_order_instances for this org. Never touches cycles,
    registry, scans, day production, or Performance history.

    Fast path: seed one instance per bag from the earliest COMPLETED cycle,
    then add later instances only when pickup/workitems/load-in proves a
    new order after the prior completion.
    """
    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    cursor.execute(
        f"SELECT COUNT(*) AS n FROM {ORDER_INSTANCES_TABLE} WHERE organization_id = %s",
        (org,),
    )
    row = cursor.fetchone() or {}
    before = int(row["n"] if isinstance(row, dict) else row[0] or 0)
    cursor.execute(
        f"DELETE FROM {ORDER_INSTANCES_TABLE} WHERE organization_id = %s",
        (org,),
    )

    if not table_exists(cursor, "rinse_wf_service_cycles"):
        return {
            "organization_id": org,
            "deleted_before": before,
            "after_count": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "bags_multi": 0,
        }

    # Earliest COMPLETED cycle per bag → first instance (no boundary required).
    print("rebuild: load completed cycles", flush=True)
    cursor.execute(
        """
        SELECT id, organization_id, bag_id, cycle_anchor_at, completed_at,
               completion_source
        FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND status = 'COMPLETED'
          AND completed_at IS NOT NULL
          AND cycle_anchor_at IS NOT NULL
        ORDER BY UPPER(TRIM(bag_id)), completed_at, id
        """,
        (org,),
    )
    all_cycles = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    print("rebuild: cycles", len(all_cycles), flush=True)
    by_bag: dict[str, list[dict[str, Any]]] = {}
    for r in all_cycles:
        bid = normalize_bag_id(r.get("bag_id"))
        if bid:
            by_bag.setdefault(bid, []).append(r)

    first_by_bag: dict[str, dict[str, Any]] = {
        bid: cycles[0] for bid, cycles in by_bag.items() if cycles
    }

    created = 0
    print("rebuild: insert first instances", len(first_by_bag), flush=True)
    for i, (bid, row) in enumerate(sorted(first_by_bag.items())):
        row = dict(row)
        row["bag_id"] = bid
        row.setdefault("service_type", "WF")
        row["status"] = "COMPLETED"
        inst = upsert_order_instance_from_cycle(cursor, org, row)
        if inst is not None:
            created += 1
        if (i + 1) % 100 == 0:
            print("rebuild: first", i + 1, flush=True)

    print("rebuild: load boundaries", flush=True)
    boundaries_by_bag = load_new_order_boundary_timestamps_for_bags(
        cursor, org, sorted(by_bag.keys())
    )
    print("rebuild: boundaries bags", len(boundaries_by_bag), flush=True)
    extra = skipped = 0
    for bid, cycles in by_bag.items():
        if len(cycles) <= 1:
            continue
        first = first_by_bag.get(bid)
        prior_completed = _parse_dt(first.get("completed_at")) if first else None
        first_id = int(first["id"]) if first and first.get("id") is not None else None
        boundaries = boundaries_by_bag.get(bid) or []
        for row in cycles:
            if first_id is not None and int(row.get("id") or 0) == first_id:
                continue
            row = dict(row)
            row["bag_id"] = bid
            row.setdefault("service_type", "WF")
            row["status"] = "COMPLETED"
            if not should_create_new_order_instance_for_cycle(
                cursor,
                org,
                bid,
                row,
                prior_completed_at=prior_completed,
                boundary_timestamps=boundaries,
            ):
                skipped += 1
                continue
            existing = (
                get_order_instance_by_source_cycle_id(cursor, int(row["id"]))
                if row.get("id") is not None
                else None
            )
            if existing is None:
                existing = get_order_instance_by_cycle_key(
                    cursor,
                    org,
                    bid,
                    service_type="WF",
                    cycle_anchor_at=_parse_dt(row.get("cycle_anchor_at")),  # type: ignore[arg-type]
                )
            if existing is not None:
                skipped += 1
                continue
            inst = upsert_order_instance_from_cycle(cursor, org, row)
            if inst is None:
                skipped += 1
                continue
            extra += 1
            prior_completed = _parse_dt(inst.get("completed_at")) or prior_completed

    print("rebuild: extras", extra, "skipped", skipped, flush=True)

    cursor.execute(
        f"SELECT COUNT(*) AS n FROM {ORDER_INSTANCES_TABLE} WHERE organization_id = %s",
        (org,),
    )
    row = cursor.fetchone() or {}
    after = int(row["n"] if isinstance(row, dict) else row[0] or 0)
    cursor.execute(
        f"""
        SELECT COUNT(*) AS n FROM (
          SELECT bag_id FROM {ORDER_INSTANCES_TABLE}
          WHERE organization_id = %s
          GROUP BY bag_id HAVING COUNT(*) > 1
        ) t
        """,
        (org,),
    )
    row = cursor.fetchone() or {}
    bags_multi = int(row["n"] if isinstance(row, dict) else row[0] or 0)
    return {
        "organization_id": org,
        "deleted_before": before,
        "after_count": after,
        "created": created + extra,
        "updated": 0,
        "skipped": skipped,
        "bags_multi": bags_multi,
        "first_instances": created,
        "extra_instances": extra,
    }


def bag_has_order_instance_covering_date(
    cursor,
    organization_id: int,
    bag_id: str,
    date_et: date,
    *,
    service_type: str = "WF",
) -> bool:
    """True if a genuine order instance belongs on date_et.

    Completed-on-D covers. Open (incomplete) instances cover via anchor on D
    or overnight from D-1. A completed instance whose completed_at is *before*
    D does NOT cover D merely because cycle_anchor_at falls on D (44N8).
    """
    rows = list_order_instances_for_bag(
        cursor, organization_id, bag_id, service_type=service_type
    )
    day_start = naive_et_day_start(date_et)
    next_start = day_start + timedelta(days=1)
    prior_start = naive_et_day_start(date_et - timedelta(days=1))
    for row in rows:
        anchor = _parse_dt(row.get("cycle_anchor_at"))
        completed = _parse_dt(row.get("completed_at"))
        if completed is not None and day_start <= completed < next_start:
            return True
        if completed is not None and completed < day_start:
            # Prior completed occurrence — not a covering instance for D.
            continue
        if completed is None and anchor is not None:
            if day_start <= anchor < next_start:
                return True
            if prior_start <= anchor < day_start:
                return True
    return False


def bags_with_order_instance_covering_date(
    cursor,
    organization_id: int,
    date_et: date,
    bag_ids: Sequence[str],
    *,
    service_type: str = "WF",
) -> set[str]:
    ensure_rinse_order_instances_table(cursor)
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return set()
    out: set[str] = set()
    ph = ",".join(["%s"] * len(ids))
    day_start = naive_et_day_start(date_et)
    prior_start = naive_et_day_start(date_et - timedelta(days=1))
    next_start = day_start + timedelta(days=1)
    cursor.execute(
        f"""
        SELECT bag_id, cycle_anchor_at, completed_at
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND service_type = %s
          AND bag_id IN ({ph})
        """,
        (int(organization_id), _svc(service_type), *ids),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        anchor = _parse_dt(row.get("cycle_anchor_at"))
        completed = _parse_dt(row.get("completed_at"))
        if completed is not None and day_start <= completed < next_start:
            out.add(bid)
            continue
        if completed is not None and completed < day_start:
            # Completed before D: anchor-on-D alone is insufficient (44N8).
            continue
        if completed is None and anchor is not None:
            if day_start <= anchor < next_start:
                out.add(bid)
                continue
            if prior_start <= anchor < day_start:
                out.add(bid)
    return out


def is_current_order_instance_completed(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    service_type: str = "WF",
) -> bool:
    """True when the latest order instance for the bag is completed.

    Falls back to rinse_bag_registry when no order_instances exist yet.
    """
    ensure_rinse_order_instances_table(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    latest = get_latest_order_instance_for_bag(
        cursor, organization_id, bid, service_type=service_type
    )
    if latest is not None:
        return _parse_dt(latest.get("completed_at")) is not None

    # Fallback: legacy registry (pre-backfill bags)
    from backend.rinse_bag_completion import COMPLETION_COMPLETED
    from backend.rinse_bag_registry import get_registry_row

    reg = get_registry_row(cursor, int(organization_id), bid) or {}
    return str(reg.get("completion_status") or "").upper() == COMPLETION_COMPLETED


def sync_order_instance_on_cycle_completion(
    cursor,
    organization_id: int,
    cycle_row: Mapping[str, Any],
    *,
    completed_by_employee_name: str | None = None,
) -> dict[str, Any] | None:
    """Call when a service cycle reaches COMPLETED."""
    if not is_authoritative_completed_cycle(cycle_row):
        return None
    row = dict(cycle_row)
    row.setdefault("service_type", "WF")
    return upsert_order_instance_from_cycle(
        cursor,
        organization_id,
        row,
        completed_by_employee_name=completed_by_employee_name,
    )
