"""
Upload Rinse scan-events CSV (Bag ID + scan columns only) into upload_batch_scan_events.

Separate from portal order import — does not touch upload_batch_rows or orders.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scan_events_logic import EVENTS_REQUIRED, SCAN_EVENT_COLUMNS, _parse_scanned_at

SCAN_EVENTS_CSV_COLUMNS = ["Bag ID", *SCAN_EVENT_COLUMNS]


def validate_scan_events_columns(df: pd.DataFrame) -> None:
    cols = {str(c).strip() for c in df.columns}
    missing = EVENTS_REQUIRED - cols
    if missing:
        raise ValueError(
            "Missing required scan-events columns: "
            + ", ".join(sorted(missing))
            + ". Expected: "
            + ", ".join(SCAN_EVENTS_CSV_COLUMNS)
        )


def normalize_scan_bag_id(value: Any) -> str:
    return normalize_bag_id(value)


def normalize_scan_event_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normalize event rows; return (dataframe, warnings)."""
    out = df.copy()
    warnings: list[str] = []

    out["Bag ID"] = out["Bag ID"].map(normalize_scan_bag_id)
    empty_bag = out["Bag ID"].eq("")
    if empty_bag.any():
        n = int(empty_bag.sum())
        warnings.append(f"{n} row(s) missing Bag ID were skipped.")
        out = out.loc[~empty_bag].copy()

    for col in SCAN_EVENT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype(str).str.strip()

    scan_idx = pd.to_numeric(out.get("Scan Index", pd.Series([""] * len(out))), errors="coerce")
    out["_scan_index_num"] = scan_idx

    out["scanned_at_parsed"] = out["Time Scanned"].map(_parse_scanned_at)
    bad_time = out["Time Scanned"].astype(str).str.strip().ne("") & out["scanned_at_parsed"].isna()
    if bad_time.any():
        n = int(bad_time.sum())
        warnings.append(f"{n} row(s) had Time Scanned text that could not be parsed (stored as raw).")

    out = out.drop(columns=["_scan_index_num"], errors="ignore")
    return out, warnings


def parse_scan_events_csv(file_or_path) -> tuple[pd.DataFrame, list[str]]:
    """Read events CSV; validate columns; normalize rows."""
    df = pd.read_csv(file_or_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    validate_scan_events_columns(df)
    return normalize_scan_event_rows(df)


def ensure_upload_batch_scan_events_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_batch_scan_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            upload_batch_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            scan_index INT NULL,
            rack VARCHAR(64) NULL,
            time_scanned_raw VARCHAR(255) NULL,
            scanned_at_parsed DATETIME NULL,
            user_name VARCHAR(255) NULL,
            purpose VARCHAR(255) NULL,
            last_location VARCHAR(8) NULL,
            last_scan VARCHAR(8) NULL,
            raw_json JSON NULL,
            source_filename VARCHAR(512) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ubse_batch (upload_batch_id),
            INDEX idx_ubse_org_batch (organization_id, upload_batch_id),
            INDEX idx_ubse_bag (bag_id),
            INDEX idx_ubse_batch_bag (upload_batch_id, bag_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _row_to_db_tuple(
    organization_id: int,
    upload_batch_id: int,
    row: pd.Series,
    source_filename: str,
) -> tuple:
    scan_raw = row.get("Scan Index", "")
    scan_index = None
    if str(scan_raw).strip():
        try:
            scan_index = int(float(str(scan_raw).strip()))
        except (TypeError, ValueError):
            scan_index = None

    scanned_at = row.get("scanned_at_parsed")
    scanned_at_db = None
    if scanned_at is not None and not pd.isna(scanned_at):
        try:
            scanned_at_db = pd.Timestamp(scanned_at).to_pydatetime()
        except Exception:
            scanned_at_db = None

    raw = {
        k: ("" if pd.isna(row.get(k)) else str(row.get(k)))
        for k in SCAN_EVENTS_CSV_COLUMNS
        if k in row.index
    }

    return (
        int(organization_id),
        int(upload_batch_id),
        normalize_scan_bag_id(row.get("Bag ID")),
        scan_index,
        str(row.get("Rack", "") or "")[:64] or None,
        str(row.get("Time Scanned", "") or "")[:255] or None,
        scanned_at_db,
        str(row.get("User", "") or "")[:255] or None,
        str(row.get("Purpose", "") or "")[:255] or None,
        str(row.get("Last Location", "") or "")[:8] or None,
        str(row.get("Last Scan", "") or "")[:8] or None,
        json.dumps(raw),
        (source_filename or "")[:512] or None,
    )


def commit_scan_events_for_batch(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    df: pd.DataFrame,
    source_filename: str = "",
    *,
    replace_existing: bool = True,
) -> dict:
    """
    Insert scan event rows for an upload batch.
    Replaces prior events for the batch when replace_existing=True.
    """
    ensure_upload_batch_scan_events_table(cursor)

    if replace_existing:
        cursor.execute(
            """
            DELETE FROM upload_batch_scan_events
            WHERE upload_batch_id = %s AND organization_id = %s
            """,
            (int(upload_batch_id), int(organization_id)),
        )
        deleted = cursor.rowcount or 0
    else:
        deleted = 0

    if df.empty:
        return {
            "rows_inserted": 0,
            "bags_with_events": 0,
            "replaced_prior_rows": deleted,
        }

    insert_sql = """
        INSERT INTO upload_batch_scan_events (
            organization_id, upload_batch_id, bag_id, scan_index, rack,
            time_scanned_raw, scanned_at_parsed, user_name, purpose,
            last_location, last_scan, raw_json, source_filename
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    rows = [_row_to_db_tuple(organization_id, upload_batch_id, r, source_filename) for _, r in df.iterrows()]
    cursor.executemany(insert_sql, rows)

    bags = df["Bag ID"].nunique() if "Bag ID" in df.columns else 0
    return {
        "rows_inserted": len(rows),
        "bags_with_events": int(bags),
        "replaced_prior_rows": deleted,
    }


def count_scan_events_for_batch(cursor, upload_batch_id: int, organization_id: int | None = None) -> int:
    if not organization_id:
        cursor.execute(
            "SELECT COUNT(*) AS c FROM upload_batch_scan_events WHERE upload_batch_id = %s",
            (int(upload_batch_id),),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*) AS c FROM upload_batch_scan_events
            WHERE upload_batch_id = %s AND organization_id = %s
            """,
            (int(upload_batch_id), int(organization_id)),
        )
    row = cursor.fetchone()
    if not row:
        return 0
    return int(row["c"] if isinstance(row, dict) else row[0])
