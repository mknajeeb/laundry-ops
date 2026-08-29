"""Immutable Rinse order_instance_id — one real service/order occurrence.

bag_id is reusable. order_instance_id is the durable identity for completion
terminal protection and day admission.

Seed: authoritative rinse_wf_service_cycles rows (cycle_anchor_at).
EDD is never used as identity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_et import naive_et_day_start
from backend.ta_helpers import table_exists

ORDER_INSTANCES_TABLE = "rinse_order_instances"


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
    """Idempotent backfill from COMPLETED rinse_wf_service_cycles only.

    Stale REVIEW / duplicate ACTIVE shells are skipped. Same
    (org, bag, service_type, cycle_anchor_at) resolves to one instance.
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
        ORDER BY organization_id, bag_id, cycle_anchor_at, id
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

    for row in rows:
        if not is_authoritative_completed_cycle(row):
            skipped += 1
            continue
        # WF-only spine for now (HD deferred unless same terminal path requires it).
        row = dict(row)
        row.setdefault("service_type", "WF")
        cid = int(row["id"]) if row.get("id") is not None else None
        prior = (
            get_order_instance_by_source_cycle_id(cursor, cid) if cid else None
        )
        if prior is None:
            prior = get_order_instance_by_cycle_key(
                cursor,
                int(row["organization_id"]),
                str(row.get("bag_id")),
                service_type="WF",
                cycle_anchor_at=_parse_dt(row.get("cycle_anchor_at")),  # type: ignore[arg-type]
            )
        inst = upsert_order_instance_from_cycle(
            cursor,
            int(row["organization_id"]),
            row,
        )
        if inst is None:
            skipped += 1
            continue
        oid = int(inst["order_instance_id"])
        if prior is None and oid not in before_ids:
            created += 1
            before_ids.add(oid)
        else:
            updated += 1

    # Count bags with >1 instance in scope
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


def bag_has_order_instance_covering_date(
    cursor,
    organization_id: int,
    bag_id: str,
    date_et: date,
    *,
    service_type: str = "WF",
) -> bool:
    """True if an order instance belongs on date_et (anchor or completion).

    Used to keep a bag out of terminal-before exclusion when a later real
    occurrence exists on D.
    """
    rows = list_order_instances_for_bag(
        cursor, organization_id, bag_id, service_type=service_type
    )
    for row in rows:
        anchor = _parse_dt(row.get("cycle_anchor_at"))
        completed = _parse_dt(row.get("completed_at"))
        if anchor is not None and _et_date(anchor) == date_et:
            return True
        if completed is not None and _et_date(completed) == date_et:
            return True
        # Open overnight instance: anchored prior day, still incomplete on D.
        if completed is None and anchor is not None:
            ad = _et_date(anchor)
            if ad is not None and ad >= date_et - timedelta(days=1) and ad <= date_et:
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
        if anchor is not None and day_start <= anchor < next_start:
            out.add(bid)
            continue
        # In-progress overnight: open instance anchored prior day
        if (
            completed is None
            and anchor is not None
            and prior_start <= anchor < day_start
        ):
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
