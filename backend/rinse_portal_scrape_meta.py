"""
Portal scrape metadata from scrape.mjs (pagination stop reason).

Used to guard MISSING_FROM_LATEST_PORTAL_UPLOAD: partial scrapes that hit
RINSE_MAX_PAGES must not trigger portal absence completion.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.ta_helpers import table_exists, table_has_column

logger = logging.getLogger(__name__)

# scrape.mjs stopped_reason values (natural end = safe for portal absence)
STOPPED_MAX_PAGES_REACHED = "max_pages_reached"
NATURAL_STOP_REASONS = frozenset(
    {
        "pagination_redirect",
        "no_table_rows",
        "duplicate_page_fingerprint",
        "no_extractable_rows",
        "duplicate_bag_set",
        "no_next_page_ui",
    }
)


def meta_path_for_portal_csv(portal_csv_path: str | Path) -> Path:
    """Prefer scrape.mjs default: <csv>.meta.json"""
    p = Path(portal_csv_path)
    return p.with_name(p.name + ".meta.json")


def load_portal_scrape_meta_file(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read portal scrape meta %s: %s", p, e)
        return None
    return raw if isinstance(raw, dict) else None


def normalize_portal_scrape_meta(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    stopped = str(raw.get("stopped_reason") or "").strip() or None
    reached = bool(raw.get("reached_max_pages"))
    try:
        pages = int(raw.get("pages_scraped") or 0)
    except (TypeError, ValueError):
        pages = 0
    try:
        max_lim = int(raw.get("max_pages_limit") or 0)
    except (TypeError, ValueError):
        max_lim = 0
    return {
        "stopped_reason": stopped,
        "reached_max_pages": reached,
        "pages_scraped": pages,
        "max_pages_limit": max_lim,
        "page_start": raw.get("page_start"),
        "row_count": raw.get("row_count"),
        "scraped_at": raw.get("scraped_at"),
    }


def portal_scrape_meta_allows_absence_completion(meta: dict[str, Any] | None) -> bool:
    """
    True only when portal export is a trustworthy full snapshot.

    Manual uploads (meta None) are allowed (legacy full_snapshot=1).
    Scheduled scrapes with reached_max_pages must not complete absent bags.
    """
    if meta is None:
        return True
    if bool(meta.get("reached_max_pages")):
        return False
    reason = str(meta.get("stopped_reason") or "").strip()
    if reason == STOPPED_MAX_PAGES_REACHED:
        return False
    if reason in NATURAL_STOP_REASONS:
        return True
    # Unknown reason: conservative — do not run absence completion
    return False


def ensure_upload_batch_portal_scrape_meta_columns(cursor) -> None:
    if not table_exists(cursor, "upload_batches"):
        return
    for col, ddl in (
        ("full_snapshot", "TINYINT(1) NOT NULL DEFAULT 1"),
        (
            "portal_scrape_meta",
            "JSON NULL COMMENT 'Portal scrape stop metadata from scrape.mjs'",
        ),
    ):
        if not table_has_column(cursor, "upload_batches", col):
            cursor.execute(f"ALTER TABLE upload_batches ADD COLUMN {col} {ddl}")


def persist_portal_scrape_meta_on_batch(
    cursor,
    upload_batch_id: int,
    organization_id: int | None,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Store scrape meta on upload_batches and set full_snapshot accordingly.

    full_snapshot=0 when reached_max_pages (partial portal export).
    """
    ensure_upload_batch_portal_scrape_meta_columns(cursor)
    normalized = normalize_portal_scrape_meta(meta)
    allows = portal_scrape_meta_allows_absence_completion(normalized)
    full_snapshot = 1 if allows else 0
    meta_json = json.dumps(normalized) if normalized else None

    batch_pk = "batch_id" if table_has_column(cursor, "upload_batches", "batch_id") else "id"
    sql = f"""
        UPDATE upload_batches
        SET full_snapshot = %s, portal_scrape_meta = %s
        WHERE {batch_pk} = %s
    """
    args: list[Any] = [int(full_snapshot), meta_json, int(upload_batch_id)]
    if organization_id is not None and table_has_column(cursor, "upload_batches", "organization_id"):
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    cursor.execute(sql, tuple(args))

    return {
        "full_snapshot": bool(full_snapshot),
        "portal_scrape_meta": normalized,
        "portal_absence_allowed": allows,
    }


def fetch_portal_scrape_meta_for_batch(
    cursor, upload_batch_id: int, organization_id: int | None = None
) -> dict[str, Any] | None:
    if not table_exists(cursor, "upload_batches"):
        return None
    batch_pk = "batch_id" if table_has_column(cursor, "upload_batches", "batch_id") else "id"
    cols = ["portal_scrape_meta", "full_snapshot"] if table_has_column(
        cursor, "upload_batches", "portal_scrape_meta"
    ) else ["full_snapshot"] if table_has_column(cursor, "upload_batches", "full_snapshot") else []
    if not cols:
        return None
    sql = f"SELECT {', '.join(cols)} FROM upload_batches WHERE {batch_pk} = %s"
    args: list[Any] = [int(upload_batch_id)]
    if organization_id is not None and table_has_column(cursor, "upload_batches", "organization_id"):
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    cursor.execute(sql, tuple(args))
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None
    raw = row.get("portal_scrape_meta")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, dict):
        return normalize_portal_scrape_meta(raw)
    if row.get("full_snapshot") is not None:
        fs = bool(int(row.get("full_snapshot") or 0))
        if fs:
            # Legacy/manual full portal CSV confirm without scrape.mjs meta.
            return None
        return {
            "stopped_reason": None,
            "reached_max_pages": True,
            "pages_scraped": 0,
            "max_pages_limit": 0,
        }
    return None
