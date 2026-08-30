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

    # New cycle_anchor → new instance only with authoritative new-order evidence.
    # Duplicate/reconciliation completed cycles merge into the latest instance.
    latest = get_latest_order_instance_for_bag(
        cursor, org, bid, service_type=svc
    )
    prior_completed = (
        _parse_dt(latest.get("completed_at")) if latest else None
    )
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
