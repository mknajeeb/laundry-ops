"""
Persistent Rinse bag registry + scan history (survives daily operational reset).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Sequence

import pandas as pd

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    COMPLETION_REJECTED,
    REASON_NO_CLEAN_SCAN,
    CompletionResult,
    completion_result_references_persisted_events,
    evaluate_bag_completion,
    normalize_bag_id,
)
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key, dedupe_key_from_row
from backend.rinse_scan_time import (
    RINSE_SCAN_SOURCE_TIMEZONE,
    normalize_rack_value,
    parse_rinse_scanned_at,
)


def ensure_rinse_bag_registry_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_registry (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            completion_status VARCHAR(32) NOT NULL DEFAULT 'INCOMPLETE',
            completed_at DATETIME NULL,
            completion_reason VARCHAR(64) NULL,
            first_clean_scan_at DATETIME NULL,
            first_clean_scan_event_id INT NULL,
            trigger_scan_at DATETIME NULL,
            trigger_scan_event_id INT NULL,
            trigger_kind VARCHAR(32) NULL,
            name_clean VARCHAR(255) NULL,
            weight_num DECIMAL(8,2) NULL,
            service_type VARCHAR(10) NULL,
            date_clean DATE NULL,
            last_upload_batch_id INT NULL,
            last_staging_order_id INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_rinse_bag_org_bag (organization_id, bag_id),
            KEY idx_rinse_bag_org_status (organization_id, completion_status),
            KEY idx_rinse_bag_completed_at (organization_id, completed_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Widen legacy completion_status columns to hold longer lifecycle states
    # (e.g. COMPLETION_REVIEW_REQUIRED = 26 chars).
    cursor.execute(
        """
        SELECT CHARACTER_MAXIMUM_LENGTH AS len FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'rinse_bag_registry'
          AND COLUMN_NAME = 'completion_status'
        """
    )
    row = cursor.fetchone()
    cur_len = None
    if row is not None:
        cur_len = row.get("len") if isinstance(row, dict) else row[0]
    if cur_len is not None and int(cur_len) < 32:
        cursor.execute(
            "ALTER TABLE rinse_bag_registry "
            "MODIFY COLUMN completion_status VARCHAR(32) NOT NULL DEFAULT 'INCOMPLETE'"
        )


def _scan_events_table_has_column(cursor, col_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'rinse_bag_scan_events'
          AND COLUMN_NAME = %s
        """,
        (col_name,),
    )
    row = cursor.fetchone()
    n = int(row["c"] if isinstance(row, dict) else row[0])
    return n > 0


def _scan_events_table_has_index(cursor, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'rinse_bag_scan_events'
          AND INDEX_NAME = %s
        """,
        (index_name,),
    )
    row = cursor.fetchone()
    n = int(row["c"] if isinstance(row, dict) else row[0])
    return n > 0


def ensure_rinse_bag_scan_events_dedupe_schema(cursor) -> None:
    """Add dedupe_key column + unique (org, bag, dedupe_key) when missing."""
    ensure_rinse_bag_scan_events_table(cursor)
    if not _scan_events_table_has_column(cursor, "dedupe_key"):
        cursor.execute(
            "ALTER TABLE rinse_bag_scan_events ADD COLUMN dedupe_key VARCHAR(64) NULL AFTER bag_id"
        )
    if not _scan_events_table_has_index(cursor, "uq_rbse_org_bag_dedupe"):
        backfill_scan_event_dedupe_keys(cursor)
        delete_duplicate_scan_events(cursor)
        cursor.execute(
            """
            CREATE UNIQUE INDEX uq_rbse_org_bag_dedupe
            ON rinse_bag_scan_events (organization_id, bag_id, dedupe_key)
            """
        )


def ensure_rinse_bag_scan_events_table(cursor) -> None:
    """Create base table (without calling dedupe migration — avoids recursion)."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_scan_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            dedupe_key VARCHAR(64) NULL,
            scan_index INT NULL,
            rack VARCHAR(128) NULL,
            time_scanned_raw VARCHAR(255) NULL,
            scanned_at_parsed DATETIME NULL,
            source_timezone VARCHAR(64) NOT NULL DEFAULT 'America/New_York',
            user_name VARCHAR(255) NULL,
            purpose VARCHAR(255) NULL,
            last_location VARCHAR(8) NULL,
            last_scan VARCHAR(8) NULL,
            source_upload_batch_id INT NULL,
            source_filename VARCHAR(512) NULL,
            last_seen_at DATETIME NULL,
            raw_json JSON NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_rbse_org_bag (organization_id, bag_id),
            KEY idx_rbse_org_bag_time (organization_id, bag_id, scanned_at_parsed, scan_index),
            KEY idx_rbse_batch (source_upload_batch_id),
            KEY idx_rbse_org_batch_bag (organization_id, source_upload_batch_id, bag_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _ensure_rinse_bag_scan_events_audit_columns(cursor)


def _ensure_rinse_bag_scan_events_audit_columns(cursor) -> None:
    for col, ddl in (
        ("source_timezone", "VARCHAR(64) NOT NULL DEFAULT 'America/New_York'"),
        ("last_seen_at", "DATETIME NULL"),
    ):
        if not _scan_events_table_has_column(cursor, col):
            cursor.execute(
                f"ALTER TABLE rinse_bag_scan_events ADD COLUMN {col} {ddl}"
            )


def ensure_rinse_bag_tables(cursor) -> None:
    ensure_rinse_bag_registry_table(cursor)
    ensure_rinse_bag_scan_events_table(cursor)
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)


def fetch_pre_existing_completed_bag_ids(
    cursor, organization_id: int, bag_ids: list[str]
) -> set[str]:
    """Bag IDs already COMPLETED in registry before the current upload begins."""
    ensure_rinse_bag_registry_table(cursor)
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not normalized:
        return set()
    placeholders = ", ".join(["%s"] * len(normalized))
    cursor.execute(
        f"""
        SELECT bag_id FROM rinse_bag_registry
        WHERE organization_id = %s
          AND bag_id IN ({placeholders})
          AND completion_status = %s
        """,
        [int(organization_id), *normalized, COMPLETION_COMPLETED],
    )
    rows = cursor.fetchall()
    out: set[str] = set()
    for r in rows:
        bid = r.get("bag_id") if isinstance(r, dict) else r[0]
        nb = normalize_bag_id(bid)
        if nb:
            out.add(nb)
    return out


def is_bag_already_completed(cursor, organization_id: int, bag_id: str) -> bool:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    ensure_rinse_bag_registry_table(cursor)
    cursor.execute(
        """
        SELECT completion_status FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bid),
    )
    row = cursor.fetchone()
    if not row:
        return False
    status = row["completion_status"] if isinstance(row, dict) else row[0]
    return str(status or "").upper() == COMPLETION_COMPLETED


def is_bag_portal_scrape_rejected(cursor, organization_id: int, bag_id: str) -> bool:
    """True when registry marks bag rejected for disappearing from a full portal scrape."""
    from backend.rinse_bag_completion import (
        COMPLETION_REJECTED,
        REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE,
    )

    row = get_registry_row(cursor, organization_id, bag_id)
    if not row:
        return False
    return (
        str(row.get("completion_status") or "").upper() == COMPLETION_REJECTED
        and str(row.get("completion_reason") or "").strip()
        == REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE
    )


def mark_registry_rejected_portal_absence(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    rejected_at: datetime | None = None,
    force: bool = False,
) -> bool:
    """
    Mark bag REJECTED because it was incomplete and missing from the latest full portal upload.
    """
    from backend.rinse_bag_completion import (
        COMPLETION_REJECTED,
        REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE,
        TRIGGER_KIND_PORTAL_SCRAPE_ABSENCE_REJECT,
    )

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    existing = get_registry_row(cursor, org, bid)
    if existing and str(existing.get("completion_status") or "").upper() in (
        COMPLETION_REJECTED,
        COMPLETION_COMPLETED,
    ):
        if is_bag_portal_scrape_rejected(cursor, org, bid):
            return False
        if (
            not force
            and str(existing.get("completion_status") or "").upper() == COMPLETION_COMPLETED
        ):
            return False

    when = rejected_at or datetime.utcnow()
    batch_id = int(upload_batch_id)
    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status, completion_reason,
            completed_at, trigger_kind, last_upload_batch_id, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            completion_status = VALUES(completion_status),
            completion_reason = VALUES(completion_reason),
            completed_at = VALUES(completed_at),
            trigger_kind = VALUES(trigger_kind),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_REJECTED,
            REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE,
            when,
            TRIGGER_KIND_PORTAL_SCRAPE_ABSENCE_REJECT,
            batch_id,
        ),
    )
    return True


def mark_registry_rejected_create_issue_portal_departure(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    rejected_at: datetime | None = None,
    create_issue_at: datetime | None = None,
    force: bool = False,
) -> bool:
    """Mark bag REJECTED after create-issue workflow with no valid completion before portal departure."""
    from backend.rinse_bag_completion import (
        COMPLETION_REJECTED,
        REASON_CREATE_ISSUE_NO_COMPLETION_PORTAL_DEPARTURE,
        TRIGGER_KIND_CREATE_ISSUE_PORTAL_DEPARTURE_REJECT,
    )

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    existing = get_registry_row(cursor, org, bid)
    if existing and str(existing.get("completion_status") or "").upper() == COMPLETION_COMPLETED:
        if not force:
            return False

    when = rejected_at or datetime.utcnow()
    trigger_at = create_issue_at or when
    batch_id = int(upload_batch_id)
    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status, completion_reason,
            completed_at, trigger_kind, trigger_scan_at, last_upload_batch_id,
            created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            completion_status = VALUES(completion_status),
            completion_reason = VALUES(completion_reason),
            completed_at = VALUES(completed_at),
            trigger_kind = VALUES(trigger_kind),
            trigger_scan_at = VALUES(trigger_scan_at),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_REJECTED,
            REASON_CREATE_ISSUE_NO_COMPLETION_PORTAL_DEPARTURE,
            when,
            TRIGGER_KIND_CREATE_ISSUE_PORTAL_DEPARTURE_REJECT,
            trigger_at,
            batch_id,
        ),
    )
    return True


def deactivate_at_vendor_presence_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> int:
    """Deactivate live At Vendor presence rows for rejected / departed bags."""
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return 0
    org = int(organization_id)
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not normalized:
        return 0
    deactivated = 0
    chunk_size = 200
    now = datetime.utcnow()
    for i in range(0, len(normalized), chunk_size):
        chunk = normalized[i : i + chunk_size]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            UPDATE rinse_cleaner_ticket_presence
            SET active = 0, last_seen_at = %s
            WHERE organization_id = %s
              AND portal_status = %s
              AND active = 1
              AND UPPER(TRIM(bag_id)) IN ({placeholders})
            """,
            (now, org, PORTAL_STATUS_AT_VENDOR, *[b.upper() for b in chunk]),
        )
        deactivated += int(cursor.rowcount or 0)
    return deactivated


def mark_registry_completed_portal_absence(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    completed_at: datetime | None = None,
) -> bool:
    """
    Mark bag COMPLETED because it was missing from the latest full portal upload.
    Inserts a registry row when the bag only existed on staging.
    """
    from backend.rinse_bag_completion import (
        COMPLETION_COMPLETED,
        REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
        TRIGGER_KIND_PORTAL_ABSENCE,
    )

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    existing = get_registry_row(cursor, org, bid)
    if existing and str(existing.get("completion_status") or "").upper() == COMPLETION_COMPLETED:
        return False

    when = completed_at or datetime.utcnow()
    batch_id = int(upload_batch_id)
    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status, completion_reason,
            completed_at, trigger_kind, last_upload_batch_id, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            completion_status = VALUES(completion_status),
            completion_reason = VALUES(completion_reason),
            completed_at = VALUES(completed_at),
            trigger_kind = VALUES(trigger_kind),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_COMPLETED,
            REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
            when,
            TRIGGER_KIND_PORTAL_ABSENCE,
            batch_id,
        ),
    )
    return True


def get_registry_row(cursor, organization_id: int, bag_id: str) -> dict | None:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    ensure_rinse_bag_registry_table(cursor)
    cursor.execute(
        """
        SELECT * FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bid),
    )
    return cursor.fetchone()


def _scan_index_int(val: Any) -> int | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return None


def _scan_events_timeline_list_sql(*, full_row: bool, limit: int | None = None) -> str:
    """
    All persisted scan rows for a bag in ET timeline order.

    Do not GROUP BY dedupe_key — distinct logical scans remain visible even when
    dedupe_key was null/blank on legacy rows.
    """
    if full_row:
        cols = """
            id, bag_id, scan_index, rack, user_name, purpose,
            time_scanned_raw, scanned_at_parsed, source_timezone, dedupe_key,
            source_upload_batch_id, created_at, updated_at, last_seen_at
        """
    else:
        cols = "id, rack, user_name, scanned_at_parsed, scan_index, purpose"
    lim = f" LIMIT {int(limit)}" if limit is not None else ""
    return f"""
        SELECT {cols}
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        {lim}
    """


def upsert_scan_event_row(
    cursor,
    *,
    organization_id: int,
    bag_id: str,
    dedupe_key: str,
    scan_index: int | None,
    rack: str | None,
    time_scanned_raw: str | None,
    scanned_at_parsed,
    user_name: str | None,
    purpose: str | None,
    last_location: str | None,
    last_scan: str | None,
    source_upload_batch_id: int,
    source_filename: str | None,
    raw_json: str | None,
    credential_sourced: bool = False,
    weight_lbs: float | None = None,
) -> str:
    """
    Insert a new scan row, or touch metadata only when dedupe_key matches.

    Scan facts (time, rack, user, purpose, scan_index, bag_id) are immutable after
    insert. A different timestamp/rack/user/purpose yields a different dedupe_key
    and therefore a new row.
    """
    from backend.rinse_bag_operational_owner import assert_operational_write_allowed
    from backend.rinse_workload_bag_weight import ensure_scan_events_weight_lbs_column
    from backend.ta_helpers import table_has_column

    allowed, _, _ = assert_operational_write_allowed(
        cursor,
        int(organization_id),
        bag_id,
        context="scan_event_upsert",
        assign_on_first=True,
        credential_sourced=credential_sourced,
    )
    if not allowed:
        return "rejected_operational_owner"

    ensure_rinse_bag_scan_events_table(cursor)
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    ensure_scan_events_weight_lbs_column(cursor)
    has_weight_col = table_has_column(cursor, "rinse_bag_scan_events", "weight_lbs")
    cursor.execute(
        """
        SELECT id FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s AND dedupe_key = %s
        LIMIT 1
        """,
        (int(organization_id), bag_id, dedupe_key),
    )
    existing = cursor.fetchone()
    if existing:
        row_id = existing["id"] if isinstance(existing, dict) else existing[0]
        if has_weight_col and weight_lbs is not None:
            cursor.execute(
                """
                UPDATE rinse_bag_scan_events
                SET
                    source_upload_batch_id = COALESCE(%s, source_upload_batch_id),
                    source_filename = COALESCE(NULLIF(%s, ''), source_filename),
                    user_name = COALESCE(NULLIF(%s, ''), user_name),
                    purpose = COALESCE(NULLIF(%s, ''), purpose),
                    last_location = COALESCE(NULLIF(%s, ''), last_location),
                    last_scan = COALESCE(NULLIF(%s, ''), last_scan),
                    raw_json = COALESCE(%s, raw_json),
                    weight_lbs = COALESCE(weight_lbs, %s),
                    last_seen_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    int(source_upload_batch_id),
                    source_filename,
                    user_name,
                    purpose,
                    last_location,
                    last_scan,
                    raw_json,
                    weight_lbs,
                    int(row_id),
                ),
            )
        else:
            cursor.execute(
                """
                UPDATE rinse_bag_scan_events
                SET
                    source_upload_batch_id = COALESCE(%s, source_upload_batch_id),
                    source_filename = COALESCE(NULLIF(%s, ''), source_filename),
                    user_name = COALESCE(NULLIF(%s, ''), user_name),
                    purpose = COALESCE(NULLIF(%s, ''), purpose),
                    last_location = COALESCE(NULLIF(%s, ''), last_location),
                    last_scan = COALESCE(NULLIF(%s, ''), last_scan),
                    raw_json = COALESCE(%s, raw_json),
                    last_seen_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    int(source_upload_batch_id),
                    source_filename,
                    user_name,
                    purpose,
                    last_location,
                    last_scan,
                    raw_json,
                    int(row_id),
                ),
            )
        return "metadata_updated"

    if has_weight_col:
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, dedupe_key, scan_index, rack,
                time_scanned_raw, scanned_at_parsed, source_timezone,
                user_name, purpose,
                last_location, last_scan, source_upload_batch_id, source_filename,
                last_seen_at, raw_json, weight_lbs
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
            """,
            (
                int(organization_id),
                bag_id,
                dedupe_key,
                scan_index,
                rack,
                time_scanned_raw,
                scanned_at_parsed,
                RINSE_SCAN_SOURCE_TIMEZONE,
                user_name,
                purpose,
                last_location,
                last_scan,
                int(source_upload_batch_id),
                source_filename,
                raw_json,
                weight_lbs,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, dedupe_key, scan_index, rack,
                time_scanned_raw, scanned_at_parsed, source_timezone,
                user_name, purpose,
                last_location, last_scan, source_upload_batch_id, source_filename,
                last_seen_at, raw_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            """,
            (
                int(organization_id),
                bag_id,
                dedupe_key,
                scan_index,
                rack,
                time_scanned_raw,
                scanned_at_parsed,
                RINSE_SCAN_SOURCE_TIMEZONE,
                user_name,
                purpose,
                last_location,
                last_scan,
                int(source_upload_batch_id),
                source_filename,
                raw_json,
            ),
        )
    return "inserted"


def delete_persistent_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: list[str] | tuple[str, ...],
) -> int:
    """Remove all persistent scan rows for bags before a full portal-timeline replace."""
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    org = int(organization_id)
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not normalized:
        return 0
    deleted = 0
    chunk_size = 200
    for i in range(0, len(normalized), chunk_size):
        chunk = normalized[i : i + chunk_size]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            DELETE FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (org, *chunk),
        )
        deleted += int(cursor.rowcount or 0)
    return deleted


def _incoming_scan_bounds_from_rows(bag_rows: pd.DataFrame) -> tuple[datetime | None, int]:
    """Max scanned_at + count of parseable rows in an events-CSV slice."""
    max_ts: datetime | None = None
    count = 0
    if bag_rows is None or bag_rows.empty:
        return None, 0
    for _, row in bag_rows.iterrows():
        time_raw = str(row.get("Time Scanned", "") or "").strip()
        if not time_raw:
            continue
        scanned = parse_rinse_scanned_at(time_raw)
        if scanned is None:
            continue
        count += 1
        if max_ts is None or scanned > max_ts:
            max_ts = scanned
    return max_ts, count


def _persistent_scan_bounds_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, tuple[datetime | None, int]]:
    """Existing max(scanned_at_parsed) + count per bag."""
    out: dict[str, tuple[datetime | None, int]] = {
        normalize_bag_id(b): (None, 0) for b in bag_ids if normalize_bag_id(b)
    }
    ids = sorted(out.keys())
    if not ids:
        return out
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, COUNT(*) AS n, MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({ph})
            GROUP BY bag_id
            """,
            (int(organization_id), *part),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(row.get("bag_id") if isinstance(row, dict) else row[0])
            if not bid:
                continue
            if isinstance(row, dict):
                out[bid] = (row.get("mx"), int(row.get("n") or 0))
            else:
                out[bid] = (row[2], int(row[1] or 0))
    return out


def _should_replace_scan_timeline(
    *,
    existing_max: datetime | None,
    existing_n: int,
    incoming_max: datetime | None,
    incoming_n: int,
) -> bool:
    """
    Replace only when the incoming export is at least as fresh and not thinner.

    Truncated scrapes (older max timestamp, or fewer rows without a newer max)
    must not delete later persisted scans.
    """
    if existing_n <= 0:
        return True
    if incoming_n <= 0:
        return False
    if existing_max is not None and incoming_max is not None and existing_max > incoming_max:
        return False
    if incoming_n < existing_n and (
        incoming_max is None
        or existing_max is None
        or incoming_max <= existing_max
    ):
        return False
    return True


def merge_scan_events_from_upload(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    events_df: pd.DataFrame,
    source_filename: str = "",
    *,
    replace_existing: bool = True,
    credential_sourced: bool = False,
) -> dict[str, Any]:
    """
    Copy scan-events into rinse_bag_scan_events.

    When replace_existing=True (default), each bag's prior persistent timeline is
    deleted first so the portal export fully replaces old cycle scans.
    Upserts by (organization_id, bag_id, dedupe_key) within the import batch.
    Ensures registry row exists per bag.
    """
    ensure_rinse_bag_tables(cursor)
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    org = int(organization_id)
    batch_id = int(upload_batch_id)

    if events_df.empty:
        return {"bags_merged": 0, "events_inserted": 0, "bag_ids": []}

    df = events_df.copy()
    if "Bag ID" not in df.columns:
        raise ValueError("Events CSV missing Bag ID column")

    df["Bag ID"] = df["Bag ID"].map(normalize_bag_id)
    df = df.loc[df["Bag ID"].astype(str).str.len() > 0]

    from backend.rinse_bag_operational_owner import filter_bag_ids_for_operational_write

    raw_bag_ids = sorted(df["Bag ID"].unique().tolist())
    allowed_ids, owner_rejected = filter_bag_ids_for_operational_write(
        cursor,
        org,
        raw_bag_ids,
        context="scan_import",
        assign_on_first=True,
        credential_sourced=credential_sourced,
    )
    bag_ids = sorted(allowed_ids)
    events_deleted = 0
    bags_replace: list[str] = []
    bags_preserve_existing: list[str] = []
    preserved_weight_enrichment: dict[tuple[str, str], dict[str, Any]] = {}
    if replace_existing and bag_ids:
        # Never wipe a richer persisted timeline with a truncated scrape export.
        # Additive upsert still runs for preserved bags so new rows can land.
        existing_bounds = _persistent_scan_bounds_for_bags(cursor, org, bag_ids)
        for bag_id in bag_ids:
            bag_rows = df.loc[df["Bag ID"] == bag_id]
            incoming_max, incoming_n = _incoming_scan_bounds_from_rows(bag_rows)
            existing_max, existing_n = existing_bounds.get(bag_id, (None, 0))
            if _should_replace_scan_timeline(
                existing_max=existing_max,
                existing_n=existing_n,
                incoming_max=incoming_max,
                incoming_n=incoming_n,
            ):
                bags_replace.append(bag_id)
            else:
                bags_preserve_existing.append(bag_id)
        if bags_replace:
            # Events CSV never carries Weight — a full timeline replace deletes
            # the rows that previously had portal weight_num attached. Snapshot
            # before delete and restore after the upsert loop so enrichment
            # (weight_lbs + provenance) survives the rebuild.
            from backend.rinse_scan_weight_enrichment import snapshot_weight_enrichment

            preserved_weight_enrichment = snapshot_weight_enrichment(cursor, org, bags_replace)
            events_deleted = delete_persistent_scan_events_for_bags(cursor, org, bags_replace)
    inserted = 0
    metadata_updated = 0
    skipped_no_time = 0
    rejected_owner = len(owner_rejected)

    for bag_id in bag_ids:
        bag_rows = df.loc[df["Bag ID"] == bag_id]
        for _, row in bag_rows.iterrows():
            scan_index = _scan_index_int(row.get("Scan Index"))
            rack = normalize_rack_value(str(row.get("Rack", "") or ""))
            if rack:
                rack = rack[:128]
            time_raw = str(row.get("Time Scanned", "") or "").strip()
            if not time_raw:
                skipped_no_time += 1
                continue
            time_raw_db = time_raw[:255]
            scanned_db = parse_rinse_scanned_at(time_raw)
            user_name = str(row.get("User", "") or "")[:255] or None
            purpose = str(row.get("Purpose", "") or "")[:255] or None
            last_loc = str(row.get("Last Location", "") or "")[:8] or None
            last_scan_flag = str(row.get("Last Scan", "") or "")[:8] or None
            raw = {
                k: ("" if pd.isna(row.get(k)) else str(row.get(k)))
                for k in row.index
            }
            from backend.rinse_wf_weight_events import normalize_scan_weight_lbs, parse_weight_lbs_from_scan_event

            weight_lbs = None
            for key in ("Weight", "weight", "# WF LBS", "WF LBS", "weight_lbs", "weight_num", "pounds", "lbs"):
                if key in row.index:
                    weight_lbs = normalize_scan_weight_lbs(row.get(key), allow_unit_suffix=True)
                    if weight_lbs is not None:
                        break
            if weight_lbs is None:
                weight_lbs = parse_weight_lbs_from_scan_event({"raw_json": raw, "purpose": purpose})
            try:
                dedupe_key = compute_scan_event_dedupe_key(
                    organization_id=org,
                    bag_id=bag_id,
                    rack=rack,
                    user_name=user_name,
                    purpose=purpose,
                    time_scanned_raw=time_raw_db,
                    scanned_at_parsed=scanned_db,
                    last_location=last_loc,
                )
            except ValueError:
                skipped_no_time += 1
                continue
            action = upsert_scan_event_row(
                cursor,
                organization_id=org,
                bag_id=bag_id,
                dedupe_key=dedupe_key,
                scan_index=scan_index,
                rack=rack,
                time_scanned_raw=time_raw_db,
                scanned_at_parsed=scanned_db,
                user_name=user_name,
                purpose=purpose,
                last_location=last_loc,
                last_scan=last_scan_flag,
                source_upload_batch_id=batch_id,
                source_filename=(source_filename or "")[:512] or None,
                raw_json=json.dumps(raw),
                credential_sourced=credential_sourced,
                weight_lbs=weight_lbs,
            )
            if action == "rejected_operational_owner":
                rejected_owner += 1
                continue
            if action == "metadata_updated":
                metadata_updated += 1
            else:
                inserted += 1

        cursor.execute(
            """
            INSERT INTO rinse_bag_registry (organization_id, bag_id, last_upload_batch_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                last_upload_batch_id = VALUES(last_upload_batch_id),
                updated_at = NOW()
            """,
            (org, bag_id, batch_id),
        )

    weight_enrichment_restored = 0
    weight_enrichment_restore_stats: dict = {}
    if preserved_weight_enrichment:
        from backend.rinse_scan_weight_enrichment import restore_weight_enrichment

        weight_enrichment_restore_stats = restore_weight_enrichment(
            cursor, org, preserved_weight_enrichment
        )
        weight_enrichment_restored = int(
            weight_enrichment_restore_stats.get("updated") or 0
        )

    return {
        "bags_merged": len(bag_ids),
        "events_inserted": inserted,
        "events_deleted": events_deleted,
        "events_already_present": metadata_updated,
        "events_metadata_updated": metadata_updated,
        "events_updated": metadata_updated,
        "events_skipped_no_time": skipped_no_time,
        "bags_rejected_operational_owner": rejected_owner,
        "operational_owner_rejected": owner_rejected,
        "replace_existing": replace_existing,
        "bags_replaced": bags_replace if replace_existing else list(bag_ids),
        "bags_preserve_existing_timeline": bags_preserve_existing,
        "bag_ids": bag_ids,
        "weight_enrichment_preserved": len(preserved_weight_enrichment),
        "weight_enrichment_restored": weight_enrichment_restored,
        "weight_enrichment_restore_stats": weight_enrichment_restore_stats,
    }


def fetch_persistent_scan_events_for_bag(
    cursor, organization_id: int, bag_id: str
) -> list[dict[str, Any]]:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    org = int(organization_id)
    cursor.execute(
        _scan_events_timeline_list_sql(full_row=False),
        (org, bid),
    )
    rows = cursor.fetchall() or []
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append(
                {
                    "id": r[0],
                    "rack": r[1],
                    "user_name": r[2],
                    "scanned_at_parsed": r[3],
                    "scan_index": r[4],
                    "purpose": r[5] if len(r) > 5 else None,
                }
            )
    return out


def apply_completion_to_registry(
    cursor, organization_id: int, bag_id: str
) -> dict[str, Any]:
    from backend.rinse_bag_completion import STATUS_COMPLETION_REVIEW_REQUIRED

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if is_bag_portal_scrape_rejected(cursor, org, bid):
        return {
            "bag_id": bid,
            "completion_status": COMPLETION_REJECTED,
            "skipped": "portal_scrape_rejected",
        }
    existing_row = get_registry_row(cursor, org, bid)
    review_required = (
        existing_row is not None
        and str(existing_row.get("completion_status") or "").upper()
        == STATUS_COMPLETION_REVIEW_REQUIRED
    )
    events = fetch_persistent_scan_events_for_bag(cursor, organization_id, bid)
    result = evaluate_bag_completion(events)
    if result.completion_status != COMPLETION_COMPLETED:
        from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
        from backend.rinse_bag_completion import (
            REASON_STRONG_COMPLETION_EVIDENCE,
            _event_id_from_mapping,
            order_events_for_completion,
        )
        from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid

        v2 = evaluate_bag_completion_v2(gaming_events_from_records(events))
        if v2.completed and ts_valid(v2.completion_at):
            result = CompletionResult(
                completion_status=COMPLETION_COMPLETED,
                completion_reason=REASON_STRONG_COMPLETION_EVIDENCE,
                first_clean_scan_at=None,
                first_clean_scan_event_id=None,
                trigger_scan_at=v2.completion_at,
                trigger_scan_event_id=_event_id_from_mapping(
                    next(
                        (
                            ev
                            for ev in order_events_for_completion(events)
                            if event_ts(ev) == v2.completion_at
                        ),
                        {},
                    )
                ),
                trigger_kind=v2.completion_kind,
            )
    if result.completion_status == COMPLETION_COMPLETED and not completion_result_references_persisted_events(
        result, events
    ):
        result = CompletionResult(
            completion_status=COMPLETION_INCOMPLETE,
            completion_reason=REASON_NO_CLEAN_SCAN,
            first_clean_scan_at=None,
            first_clean_scan_event_id=None,
            trigger_scan_at=None,
            trigger_scan_event_id=None,
            trigger_kind=None,
        )
    # A bag already routed to Completion Review must not be silently downgraded to
    # INCOMPLETE by a scan-only recompute — only a real completion may promote it.
    if review_required and result.completion_status != COMPLETION_COMPLETED:
        return {
            "bag_id": bid,
            "completion_status": STATUS_COMPLETION_REVIEW_REQUIRED,
            "skipped": "completion_review_required",
        }

    fields = result.to_registry_update()

    ensure_rinse_bag_registry_table(cursor)
    org = int(organization_id)
    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (organization_id, bag_id)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE updated_at = NOW()
        """,
        (org, bid),
    )
    cursor.execute(
        """
        UPDATE rinse_bag_registry
        SET
            completion_status = %s,
            completion_reason = %s,
            completed_at = %s,
            first_clean_scan_at = %s,
            first_clean_scan_event_id = %s,
            trigger_scan_at = %s,
            trigger_scan_event_id = %s,
            trigger_kind = %s,
            updated_at = NOW()
        WHERE organization_id = %s AND bag_id = %s
        """,
        (
            fields["completion_status"],
            fields["completion_reason"],
            fields["completed_at"],
            fields["first_clean_scan_at"],
            fields["first_clean_scan_event_id"],
            fields["trigger_scan_at"],
            fields["trigger_scan_event_id"],
            fields["trigger_kind"],
            org,
            bid,
        ),
    )
    out = {"bag_id": bid, **fields}
    if fields.get("completion_status") != COMPLETION_COMPLETED:
        from backend.rinse_folding_registry import delete_folding_performance_for_bag

        if delete_folding_performance_for_bag(cursor, organization_id, bid):
            out["folding_performance_deleted"] = True
    return out


def recompute_completion_for_bags(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, Any]:
    summaries = []
    completed = 0
    for raw in bag_ids:
        bid = normalize_bag_id(raw)
        if not bid:
            continue
        summary = apply_completion_to_registry(cursor, organization_id, bid)
        summaries.append(summary)
        if summary.get("completion_status") == COMPLETION_COMPLETED:
            completed += 1
    return {
        "bags_recomputed": len(summaries),
        "bags_completed": completed,
        "bags": summaries,
    }


def list_registry_rows(
    cursor,
    organization_id: int,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    ensure_rinse_bag_registry_table(cursor)
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    sql = "SELECT * FROM rinse_bag_registry WHERE organization_id = %s"
    args: list[Any] = [int(organization_id)]
    if status:
        sql += " AND completion_status = %s"
        args.append(str(status).strip().upper()[:24])
    sql += " ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s"
    args.extend([lim, off])
    cursor.execute(sql, tuple(args))
    return list(cursor.fetchall() or [])


def list_scan_events_for_bag(
    cursor, organization_id: int, bag_id: str, *, limit: int = 500
) -> list[dict]:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    org = int(organization_id)
    lim = max(1, min(int(limit), 2000))
    cursor.execute(
        _scan_events_timeline_list_sql(full_row=True, limit=lim),
        (org, bid),
    )
    return list(cursor.fetchall() or [])


def backfill_scan_event_dedupe_keys(cursor, organization_id: int | None = None) -> int:
    """Set dedupe_key on rows where it is null/empty. Returns rows updated."""
    ensure_rinse_bag_scan_events_table(cursor)
    if not _scan_events_table_has_column(cursor, "dedupe_key"):
        cursor.execute(
            "ALTER TABLE rinse_bag_scan_events ADD COLUMN dedupe_key VARCHAR(64) NULL AFTER bag_id"
        )
    sql = """
        SELECT id, organization_id, bag_id, scan_index, rack, user_name, purpose,
               time_scanned_raw, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE dedupe_key IS NULL OR dedupe_key = ''
    """
    args: list[Any] = []
    if organization_id is not None:
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    cursor.execute(sql, tuple(args))
    rows = cursor.fetchall() or []
    n = 0
    for r in rows:
        dk = dedupe_key_from_row(r if isinstance(r, dict) else {})
        if not isinstance(r, dict):
            continue
        cursor.execute(
            "UPDATE rinse_bag_scan_events SET dedupe_key = %s WHERE id = %s",
            (dk, int(r["id"])),
        )
        n += 1
    return n


def delete_duplicate_scan_events(cursor, organization_id: int | None = None) -> int:
    """
    Delete exact duplicate scan rows (same org, bag, dedupe_key), keeping MIN(id).
    Does not touch rinse_bag_registry.
    """
    backfill_scan_event_dedupe_keys(cursor, organization_id)
    org_filter = ""
    args: list[Any] = []
    if organization_id is not None:
        org_filter = " AND e.organization_id = %s"
        args.append(int(organization_id))
    cursor.execute(
        f"""
        DELETE e FROM rinse_bag_scan_events e
        INNER JOIN rinse_bag_scan_events e2
          ON e.organization_id = e2.organization_id
          AND e.bag_id = e2.bag_id
          AND e.dedupe_key = e2.dedupe_key
          AND e.dedupe_key IS NOT NULL
          AND e.dedupe_key != ''
          AND e.id > e2.id
        WHERE 1=1{org_filter}
        """,
        tuple(args),
    )
    return int(cursor.rowcount or 0)
