"""
Canonical operational ownership per Rinse bag_id.

WashPro and VeeWash must not share mutable operational rows. One global owner per bag_id;
all ingest paths gate writes through assert_operational_write_allowed().
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_vendor_config import resolve_rinse_vendor
from backend.ta_helpers import table_exists, table_has_column

SOURCE_REGISTRY = "registry"
SOURCE_SCAN_EVENT = "scan_event"
SOURCE_STAGING = "staging"
SOURCE_PRESENCE = "presence"
SOURCE_GATE_FIRST_WRITE = "gate_first_write"
SOURCE_AUDIT_BACKFILL = "audit_backfill"

REJECT_REASON_NOT_OWNER = "operational_owner_mismatch"
REJECT_REASON_GATE_DISABLED = "gate_disabled"

_ASSIGNMENT_SOURCE_RANK = {
    SOURCE_REGISTRY: 0,
    SOURCE_SCAN_EVENT: 1,
    SOURCE_STAGING: 2,
    SOURCE_PRESENCE: 3,
    SOURCE_GATE_FIRST_WRITE: 4,
    SOURCE_AUDIT_BACKFILL: 5,
}


@dataclass(frozen=True)
class CanonicalOwner:
    bag_id: str
    owner_organization_id: int
    owner_rinse_vendor: str
    assigned_at: datetime
    assignment_source: str
    locked: bool = True
    from_table: bool = False


def operational_owner_gate_enabled() -> bool:
    raw = str(os.getenv("RINSE_OPERATIONAL_OWNER_GATE_ENABLED", "1") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return datetime(raw.year, raw.month, raw.day)
    text = str(raw).strip()
    if not text:
        return None
    if "T" in text:
        text = text.replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:n], fmt)
        except ValueError:
            continue
    return None


def _rinse_vendor_for_org(organization_id: int) -> str:
    return resolve_rinse_vendor(int(organization_id))


def ensure_operational_owner_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_operational_owner (
          bag_id VARCHAR(64) NOT NULL PRIMARY KEY,
          owner_organization_id INT NOT NULL,
          owner_rinse_vendor VARCHAR(16) NOT NULL,
          assigned_at DATETIME NOT NULL,
          assignment_source VARCHAR(32) NOT NULL,
          locked TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          KEY idx_rboo_owner_org (owner_organization_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _fetch_owner_row(cursor, bag_id: str) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_bag_operational_owner"):
        return None
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    cursor.execute(
        """
        SELECT bag_id, owner_organization_id, owner_rinse_vendor,
               assigned_at, assignment_source, locked
        FROM rinse_bag_operational_owner
        WHERE UPPER(TRIM(bag_id)) = %s
        LIMIT 1
        """,
        (bid,),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def _owner_from_row(row: Mapping[str, Any]) -> CanonicalOwner:
    return CanonicalOwner(
        bag_id=str(row.get("bag_id") or "").strip().upper(),
        owner_organization_id=int(row.get("owner_organization_id") or 0),
        owner_rinse_vendor=str(row.get("owner_rinse_vendor") or "").strip().lower(),
        assigned_at=_parse_ts(row.get("assigned_at")) or datetime.min,
        assignment_source=str(row.get("assignment_source") or SOURCE_AUDIT_BACKFILL),
        locked=bool(int(row.get("locked") or 1)),
        from_table=True,
    )


def _collect_evidence_candidates(
    cursor,
    bag_ids: Sequence[str],
) -> dict[str, list[tuple[int, datetime, str]]]:
    """Per bag_id: list of (org_id, assigned_at, source)."""
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[tuple[int, datetime, str]]] = {b: [] for b in normalized}
    if not normalized:
        return out

    chunk = 500
    for i in range(0, len(normalized), chunk):
        part = normalized[i : i + chunk]
        ph = ",".join(["%s"] * len(part))

        if table_exists(cursor, "rinse_bag_registry"):
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(bag_id)) AS bag_id, organization_id, created_at
                FROM rinse_bag_registry
                WHERE UPPER(TRIM(bag_id)) IN ({ph})
                """,
                tuple(part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                ts = _parse_ts(row.get("created_at"))
                oid = row.get("organization_id")
                if bid in out and ts and oid is not None:
                    out[bid].append((int(oid), ts, SOURCE_REGISTRY))

        if table_exists(cursor, "rinse_bag_scan_events"):
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(bag_id)) AS bag_id, organization_id,
                       MIN(COALESCE(scanned_at_parsed, created_at)) AS first_at
                FROM rinse_bag_scan_events
                WHERE UPPER(TRIM(bag_id)) IN ({ph})
                GROUP BY UPPER(TRIM(bag_id)), organization_id
                """,
                tuple(part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                ts = _parse_ts(row.get("first_at"))
                oid = row.get("organization_id")
                if bid in out and ts and oid is not None:
                    out[bid].append((int(oid), ts, SOURCE_SCAN_EVENT))

        if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
            org_clause = ""
            args: list[Any] = list(part)
            if table_has_column(cursor, "orders_staging", "created_at"):
                ts_col = "created_at"
            elif table_has_column(cursor, "orders_staging", "batch_date"):
                ts_col = "batch_date"
            else:
                ts_col = None
            if ts_col:
                cursor.execute(
                    f"""
                    SELECT UPPER(TRIM(ticket_id)) AS bag_id, organization_id,
                           MIN({ts_col}) AS first_at
                    FROM orders_staging
                    WHERE UPPER(TRIM(ticket_id)) IN ({ph})
                    GROUP BY UPPER(TRIM(ticket_id)), organization_id
                    """,
                    tuple(part),
                )
                for row in cursor.fetchall() or []:
                    if not isinstance(row, dict):
                        continue
                    bid = str(row.get("bag_id") or "").strip().upper()
                    ts = _parse_ts(row.get("first_at"))
                    oid = row.get("organization_id")
                    if bid in out and ts and oid is not None:
                        out[bid].append((int(oid), ts, SOURCE_STAGING))

        if table_exists(cursor, "rinse_cleaner_ticket_presence"):
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(bag_id)) AS bag_id, organization_id,
                       MIN(first_seen_at) AS first_at
                FROM rinse_cleaner_ticket_presence
                WHERE UPPER(TRIM(bag_id)) IN ({ph})
                GROUP BY UPPER(TRIM(bag_id)), organization_id
                """,
                tuple(part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                ts = _parse_ts(row.get("first_at"))
                oid = row.get("organization_id")
                if bid in out and ts and oid is not None:
                    out[bid].append((int(oid), ts, SOURCE_PRESENCE))

    return out


def _pick_canonical_from_candidates(
    bag_id: str,
    candidates: Sequence[tuple[int, datetime, str]],
) -> CanonicalOwner | None:
    if not candidates:
        return None
    best: tuple[int, datetime, str] | None = None
    for org_id, ts, source in candidates:
        if best is None:
            best = (org_id, ts, source)
            continue
        if ts < best[1]:
            best = (org_id, ts, source)
        elif ts == best[1]:
            rank_new = _ASSIGNMENT_SOURCE_RANK.get(source, 99)
            rank_old = _ASSIGNMENT_SOURCE_RANK.get(best[2], 99)
            if rank_new < rank_old:
                best = (org_id, ts, source)
            elif rank_new == rank_old and org_id < best[0]:
                best = (org_id, ts, source)
    if not best:
        return None
    org_id, ts, source = best
    return CanonicalOwner(
        bag_id=bag_id,
        owner_organization_id=org_id,
        owner_rinse_vendor=_rinse_vendor_for_org(org_id),
        assigned_at=ts,
        assignment_source=source,
        locked=True,
        from_table=False,
    )


def resolve_canonical_owner(cursor, bag_id: str) -> CanonicalOwner | None:
    """Table row if present; else earliest evidence across all orgs."""
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    row = _fetch_owner_row(cursor, bid)
    if row:
        return _owner_from_row(row)
    evidence = _collect_evidence_candidates(cursor, [bid]).get(bid) or []
    return _pick_canonical_from_candidates(bid, evidence)


def resolve_canonical_owners(
    cursor,
    bag_ids: Sequence[str],
) -> dict[str, CanonicalOwner]:
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, CanonicalOwner] = {}
    if not normalized:
        return out

    if table_exists(cursor, "rinse_bag_operational_owner"):
        chunk = 500
        for i in range(0, len(normalized), chunk):
            part = normalized[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id, owner_organization_id, owner_rinse_vendor,
                       assigned_at, assignment_source, locked
                FROM rinse_bag_operational_owner
                WHERE UPPER(TRIM(bag_id)) IN ({ph})
                """,
                tuple(part),
            )
            for row in cursor.fetchall() or []:
                if isinstance(row, dict):
                    owner = _owner_from_row(row)
                    out[owner.bag_id] = owner

    remaining = [b for b in normalized if b not in out]
    if remaining:
        evidence_map = _collect_evidence_candidates(cursor, remaining)
        for bid in remaining:
            owner = _pick_canonical_from_candidates(bid, evidence_map.get(bid) or [])
            if owner:
                out[bid] = owner
    return out


def upsert_canonical_owner(
    cursor,
    owner: CanonicalOwner,
    *,
    allow_replace: bool = False,
) -> bool:
    ensure_operational_owner_table(cursor)
    existing = _fetch_owner_row(cursor, owner.bag_id)
    if existing and not allow_replace:
        return False
    cursor.execute(
        """
        INSERT INTO rinse_bag_operational_owner (
            bag_id, owner_organization_id, owner_rinse_vendor,
            assigned_at, assignment_source, locked
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            owner_organization_id = IF(%s, VALUES(owner_organization_id), owner_organization_id),
            owner_rinse_vendor = IF(%s, VALUES(owner_rinse_vendor), owner_rinse_vendor),
            assigned_at = IF(%s, VALUES(assigned_at), assigned_at),
            assignment_source = IF(%s, VALUES(assignment_source), assignment_source),
            updated_at = NOW()
        """,
        (
            owner.bag_id,
            owner.owner_organization_id,
            owner.owner_rinse_vendor,
            owner.assigned_at,
            owner.assignment_source,
            1 if owner.locked else 0,
            allow_replace,
            allow_replace,
            allow_replace,
            allow_replace,
        ),
    )
    return True


def assign_owner_on_first_write(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    context: str,
) -> CanonicalOwner | None:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    existing = resolve_canonical_owner(cursor, bid)
    if existing:
        return existing
    now = datetime.utcnow()
    owner = CanonicalOwner(
        bag_id=bid,
        owner_organization_id=int(organization_id),
        owner_rinse_vendor=_rinse_vendor_for_org(int(organization_id)),
        assigned_at=now,
        assignment_source=SOURCE_GATE_FIRST_WRITE,
        locked=True,
        from_table=False,
    )
    upsert_canonical_owner(cursor, owner, allow_replace=False)
    return owner


def assert_operational_write_allowed(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    context: str = "write",
    assign_on_first: bool = True,
) -> tuple[bool, str | None, CanonicalOwner | None]:
    """
    Return (allowed, reject_reason, canonical_owner).
    When allowed with no prior owner and assign_on_first, records canonical owner for target org.
    """
    if not operational_owner_gate_enabled():
        return True, None, None

    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return False, "missing_bag_id", None

    owner = resolve_canonical_owner(cursor, bid)
    if owner is None:
        if assign_on_first:
            owner = assign_owner_on_first_write(cursor, org, bid, context=context)
            return True, None, owner
        return True, None, None

    if owner.owner_organization_id != org:
        return False, REJECT_REASON_NOT_OWNER, owner
    return True, None, owner


def filter_bag_ids_for_operational_write(
    cursor,
    organization_id: int,
    bag_ids: set[str] | Sequence[str],
    *,
    context: str = "batch",
    assign_on_first: bool = True,
) -> tuple[set[str], list[dict[str, Any]]]:
    allowed: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for raw in bag_ids:
        bid = normalize_bag_id(raw)
        if not bid:
            rejected.append({"bag_id": raw, "reason": "missing_bag_id", "context": context})
            continue
        ok, reason, owner = assert_operational_write_allowed(
            cursor,
            organization_id,
            bid,
            context=context,
            assign_on_first=assign_on_first,
        )
        if ok:
            allowed.add(bid)
        else:
            rejected.append(
                {
                    "bag_id": bid,
                    "reason": reason,
                    "context": context,
                    "canonical_owner_organization_id": owner.owner_organization_id if owner else None,
                    "canonical_owner_rinse_vendor": owner.owner_rinse_vendor if owner else None,
                    "assignment_source": owner.assignment_source if owner else None,
                }
            )
    return allowed, rejected


def list_bag_ids_with_org_rows(cursor, organization_id: int) -> set[str]:
    """All bag_ids appearing in any org-scoped operational table for this org."""
    org = int(organization_id)
    out: set[str] = set()
    chunk_queries: list[tuple[str, tuple[Any, ...]]] = []

    if table_exists(cursor, "rinse_bag_registry"):
        chunk_queries.append(
            (
                "SELECT UPPER(TRIM(bag_id)) AS bag_id FROM rinse_bag_registry WHERE organization_id = %s",
                (org,),
            )
        )
    if table_exists(cursor, "rinse_bag_scan_events"):
        chunk_queries.append(
            (
                "SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id FROM rinse_bag_scan_events WHERE organization_id = %s",
                (org,),
            )
        )
    if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
        if table_has_column(cursor, "orders_staging", "organization_id"):
            chunk_queries.append(
                (
                    "SELECT DISTINCT UPPER(TRIM(ticket_id)) AS bag_id FROM orders_staging WHERE organization_id = %s",
                    (org,),
                )
            )
    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        chunk_queries.append(
            (
                "SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id FROM rinse_cleaner_ticket_presence WHERE organization_id = %s",
                (org,),
            )
        )
    if table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        chunk_queries.append(
            (
                "SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id FROM rinse_cleaner_ticket_presence_run_rows WHERE organization_id = %s",
                (org,),
            )
        )

    for sql, args in chunk_queries:
        cursor.execute(sql, args)
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("bag_id"):
                out.add(str(row["bag_id"]).strip().upper())
    return out


def _count_rows_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, int]]:
    org = int(organization_id)
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    counts: dict[str, dict[str, int]] = {
        "rinse_bag_registry": 0,
        "rinse_bag_scan_events": 0,
        "orders_staging": 0,
        "rinse_cleaner_ticket_presence": 0,
        "rinse_cleaner_ticket_presence_run_rows": 0,
        "upload_batch_scan_events": 0,
        "rinse_folding_performance": 0,
    }
    if not normalized:
        return counts

    chunk = 200
    for i in range(0, len(normalized), chunk):
        part = normalized[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        args_tail = tuple(part)

        if table_exists(cursor, "rinse_bag_registry"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM rinse_bag_registry WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["rinse_bag_registry"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "rinse_bag_scan_events"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["rinse_bag_scan_events"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
            if table_has_column(cursor, "orders_staging", "organization_id"):
                cursor.execute(
                    f"SELECT COUNT(*) AS c FROM orders_staging WHERE organization_id=%s AND UPPER(TRIM(ticket_id)) IN ({ph})",
                    (org, *args_tail),
                )
                counts["orders_staging"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "rinse_cleaner_ticket_presence"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["rinse_cleaner_ticket_presence"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence_run_rows WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["rinse_cleaner_ticket_presence_run_rows"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "upload_batch_scan_events"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM upload_batch_scan_events WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["upload_batch_scan_events"] += int((cursor.fetchone() or {}).get("c") or 0)

        if table_exists(cursor, "rinse_folding_performance"):
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM rinse_folding_performance WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph})",
                (org, *args_tail),
            )
            counts["rinse_folding_performance"] += int((cursor.fetchone() or {}).get("c") or 0)

    return counts


def audit_org_operational_isolation(
    cursor,
    organization_id: int,
) -> dict[str, Any]:
    """
    Phase 1 audit: every bag_id in org operational tables vs canonical owner.
  Returns rows where canonical owner != organization_id.
    """
    org = int(organization_id)
    bag_ids = list_bag_ids_with_org_rows(cursor, org)
    owners = resolve_canonical_owners(cursor, list(bag_ids))

    mismatched: list[dict[str, Any]] = []
    matched = 0
    unassigned = 0
    for bid in sorted(bag_ids):
        owner = owners.get(bid)
        if owner is None:
            unassigned += 1
            mismatched.append(
                {
                    "bag_id": bid,
                    "canonical_owner_organization_id": None,
                    "assignment_source": None,
                    "assigned_at": None,
                    "owner_rinse_vendor": None,
                    "mismatch_reason": "no_canonical_evidence",
                }
            )
            continue
        if owner.owner_organization_id == org:
            matched += 1
        else:
            row_counts = _count_rows_for_bags(cursor, org, [bid])
            mismatched.append(
                {
                    "bag_id": bid,
                    "canonical_owner_organization_id": owner.owner_organization_id,
                    "owner_rinse_vendor": owner.owner_rinse_vendor,
                    "assignment_source": owner.assignment_source,
                    "assigned_at": owner.assigned_at.isoformat(sep=" "),
                    "from_owner_table": owner.from_table,
                    "mismatch_reason": REJECT_REASON_NOT_OWNER,
                    "org_row_counts": row_counts,
                }
            )

    mismatch_ids = [m["bag_id"] for m in mismatched if m.get("canonical_owner_organization_id") is not None]
    aggregate_counts = _count_rows_for_bags(cursor, org, mismatch_ids)

    return {
        "organization_id": org,
        "bag_ids_in_org_tables": len(bag_ids),
        "canonical_owner_matches_org": matched,
        "canonical_owner_mismatch_count": len(mismatched) - unassigned,
        "no_canonical_evidence_count": unassigned,
        "mismatched_bags": mismatched,
        "aggregate_row_counts_for_mismatched": aggregate_counts,
    }


def backfill_canonical_owners_from_audit(
    cursor,
    organization_id: int | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Upsert canonical owners from evidence for all bags seen in org tables (or all evidence)."""
    if organization_id is not None:
        bag_ids = list_bag_ids_with_org_rows(cursor, int(organization_id))
    else:
        bag_ids = set()
        if table_exists(cursor, "rinse_bag_registry"):
            cursor.execute("SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id FROM rinse_bag_registry")
            for row in cursor.fetchall() or []:
                if isinstance(row, dict) and row.get("bag_id"):
                    bag_ids.add(str(row["bag_id"]).strip().upper())

    owners = resolve_canonical_owners(cursor, list(bag_ids))
    inserted = 0
    skipped_existing = 0
    for bid, owner in owners.items():
        existing = _fetch_owner_row(cursor, bid)
        if existing:
            skipped_existing += 1
            continue
        backfill_owner = CanonicalOwner(
            bag_id=bid,
            owner_organization_id=owner.owner_organization_id,
            owner_rinse_vendor=owner.owner_rinse_vendor,
            assigned_at=owner.assigned_at,
            assignment_source=SOURCE_AUDIT_BACKFILL,
            locked=True,
        )
        if not dry_run:
            upsert_canonical_owner(cursor, backfill_owner, allow_replace=False)
        inserted += 1

    return {
        "dry_run": dry_run,
        "bag_ids_considered": len(bag_ids),
        "canonical_resolved": len(owners),
        "would_insert": inserted,
        "skipped_existing_table_row": skipped_existing,
    }
