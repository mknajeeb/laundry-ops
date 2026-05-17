"""
Persistent Rinse bag registry + scan history (survives daily operational reset).
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    evaluate_bag_completion,
    normalize_bag_id,
)
from backend.rinse_scan_events_logic import _parse_scanned_at
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key, dedupe_key_from_row


def ensure_rinse_bag_registry_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_registry (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            completion_status VARCHAR(24) NOT NULL DEFAULT 'INCOMPLETE',
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
            user_name VARCHAR(255) NULL,
            purpose VARCHAR(255) NULL,
            last_location VARCHAR(8) NULL,
            last_scan VARCHAR(8) NULL,
            source_upload_batch_id INT NULL,
            source_filename VARCHAR(512) NULL,
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


def _scan_events_deduped_list_sql(*, full_row: bool, limit: int | None = None) -> str:
    cols = "*" if full_row else "e.id, e.rack, e.user_name, e.scanned_at_parsed, e.scan_index"
    lim = f" LIMIT {int(limit)}" if limit is not None else ""
    return f"""
        SELECT {cols}
        FROM rinse_bag_scan_events e
        INNER JOIN (
            SELECT MIN(id) AS keep_id
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id = %s
            GROUP BY dedupe_key
        ) k ON e.id = k.keep_id
        WHERE e.organization_id = %s AND e.bag_id = %s
        ORDER BY e.scanned_at_parsed ASC, e.scan_index ASC, e.id ASC
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
) -> str:
    """
    Insert or update one persistent scan row by (org, bag, dedupe_key).
    Returns 'inserted' or 'updated'.
    """
    ensure_rinse_bag_scan_events_table(cursor)
    if not _scan_events_table_has_column(cursor, "dedupe_key"):
        cursor.execute(
            "ALTER TABLE rinse_bag_scan_events ADD COLUMN dedupe_key VARCHAR(64) NULL AFTER bag_id"
        )
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
        cursor.execute(
            """
            UPDATE rinse_bag_scan_events
            SET
                scan_index = %s,
                rack = %s,
                time_scanned_raw = %s,
                scanned_at_parsed = %s,
                user_name = %s,
                purpose = %s,
                last_location = %s,
                last_scan = %s,
                source_upload_batch_id = %s,
                source_filename = %s,
                raw_json = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                scan_index,
                rack,
                time_scanned_raw,
                scanned_at_parsed,
                user_name,
                purpose,
                last_location,
                last_scan,
                int(source_upload_batch_id),
                source_filename,
                raw_json,
                int(row_id),
            ),
        )
        return "updated"

    cursor.execute(
        """
        INSERT INTO rinse_bag_scan_events (
            organization_id, bag_id, dedupe_key, scan_index, rack,
            time_scanned_raw, scanned_at_parsed, user_name, purpose,
            last_location, last_scan, source_upload_batch_id, source_filename, raw_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            bag_id,
            dedupe_key,
            scan_index,
            rack,
            time_scanned_raw,
            scanned_at_parsed,
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


def merge_scan_events_from_upload(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    events_df: pd.DataFrame,
    source_filename: str = "",
) -> dict[str, Any]:
    """
    Copy scan-events into rinse_bag_scan_events (idempotent per logical scan).

    Upserts by (organization_id, bag_id, dedupe_key) so re-uploading the same CSV
  across new upload batches does not accumulate duplicate rows.
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

    bag_ids = sorted(df["Bag ID"].unique().tolist())
    inserted = 0
    updated = 0

    for bag_id in bag_ids:
        bag_rows = df.loc[df["Bag ID"] == bag_id]
        for _, row in bag_rows.iterrows():
            scan_index = _scan_index_int(row.get("Scan Index"))
            rack = str(row.get("Rack", "") or "")[:128] or None
            time_raw = str(row.get("Time Scanned", "") or "")[:255] or None
            scanned_at = _parse_scanned_at(time_raw or "")
            scanned_db = None
            if scanned_at is not None and not pd.isna(scanned_at):
                try:
                    scanned_db = pd.Timestamp(scanned_at).to_pydatetime()
                except Exception:
                    scanned_db = None
            user_name = str(row.get("User", "") or "")[:255] or None
            purpose = str(row.get("Purpose", "") or "")[:255] or None
            last_loc = str(row.get("Last Location", "") or "")[:8] or None
            last_scan = str(row.get("Last Scan", "") or "")[:8] or None
            raw = {
                k: ("" if pd.isna(row.get(k)) else str(row.get(k)))
                for k in row.index
            }
            dedupe_key = compute_scan_event_dedupe_key(
                scan_index=scan_index,
                rack=rack,
                user_name=user_name,
                purpose=purpose,
                scanned_at_parsed=scanned_db,
            )
            action = upsert_scan_event_row(
                cursor,
                organization_id=org,
                bag_id=bag_id,
                dedupe_key=dedupe_key,
                scan_index=scan_index,
                rack=rack,
                time_scanned_raw=time_raw,
                scanned_at_parsed=scanned_db,
                user_name=user_name,
                purpose=purpose,
                last_location=last_loc,
                last_scan=last_scan,
                source_upload_batch_id=batch_id,
                source_filename=(source_filename or "")[:512] or None,
                raw_json=json.dumps(raw),
            )
            if action == "updated":
                updated += 1
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

    return {
        "bags_merged": len(bag_ids),
        "events_inserted": inserted,
        "events_updated": updated,
        "bag_ids": bag_ids,
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
        _scan_events_deduped_list_sql(full_row=False),
        (org, bid, org, bid),
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
                }
            )
    return out


def apply_completion_to_registry(
    cursor, organization_id: int, bag_id: str
) -> dict[str, Any]:
    bid = normalize_bag_id(bag_id)
    events = fetch_persistent_scan_events_for_bag(cursor, organization_id, bid)
    result = evaluate_bag_completion(events)
    fields = result.to_registry_update()

    ensure_rinse_bag_registry_table(cursor)
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
            int(organization_id),
            bid,
        ),
    )
    return {"bag_id": bid, **fields}


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
        _scan_events_deduped_list_sql(full_row=True, limit=lim),
        (org, bid, org, bid),
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
        SELECT id, organization_id, bag_id, scan_index, rack, user_name, purpose, scanned_at_parsed
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
