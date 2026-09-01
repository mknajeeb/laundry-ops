"""
Portal scrape metadata from scrape.mjs (pagination stop reason).

Used to guard MISSING_FROM_LATEST_PORTAL_UPLOAD: partial scrapes that hit
RINSE_MAX_PAGES must not trigger portal absence completion.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

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

# Zero-row presence replacement requires scrape.mjs validation flags (see validate_presence_empty_result).
VALIDATED_EMPTY_STOP_REASONS = frozenset({"no_table_rows", "no_extractable_rows"})


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
    try:
        skipped_n = int(raw.get("skipped_ticket_count") or 0)
    except (TypeError, ValueError):
        skipped_n = 0
    skipped_tickets = raw.get("skipped_tickets")
    if not isinstance(skipped_tickets, list):
        skipped_tickets = []
    source_complete = raw.get("source_inspected_complete")
    return {
        "stopped_reason": stopped,
        "reached_max_pages": reached,
        "pages_scraped": pages,
        "max_pages_limit": max_lim,
        "page_start": raw.get("page_start"),
        "row_count": raw.get("row_count"),
        "scraped_at": raw.get("scraped_at"),
        "page_loaded": bool(raw.get("page_loaded")),
        "session_authenticated": bool(raw.get("session_authenticated")),
        "expected_status_in_url": bool(raw.get("expected_status_in_url")),
        "empty_table_detected": bool(raw.get("empty_table_detected")),
        "degraded": bool(raw.get("degraded") or raw.get("partial") or skipped_n > 0),
        "partial": bool(raw.get("partial") or raw.get("degraded") or skipped_n > 0),
        "skipped_ticket_count": skipped_n,
        "skipped_tickets": skipped_tickets[:40],
        "page_navigation_failed": bool(raw.get("page_navigation_failed")),
        "source_inspected_complete": (
            None if source_complete is None else bool(source_complete)
        ),
    }


def validate_presence_empty_result(
    scrape_meta: dict[str, Any] | Mapping[str, Any] | None,
    *,
    exit_code: int,
    parsed_row_count: int,
) -> tuple[bool, dict[str, bool]]:
    """
    True only when a zero-row portal export is a trustworthy empty queue.

    When False, callers must not deactivate existing presence rows (mark_missing).
    """
    checks: dict[str, bool] = {
        "portal_page_loaded": False,
        "authenticated_session": False,
        "expected_page_found": False,
        "pagination_completed": False,
        "explicit_empty_state": False,
        "no_timeout": exit_code != -1,
        "no_login_redirect": False,
        "no_parser_error": exit_code == 0,
        "not_degraded": True,
    }
    if parsed_row_count > 0:
        return False, checks

    meta = normalize_portal_scrape_meta(dict(scrape_meta) if scrape_meta else None) or {}
    checks["portal_page_loaded"] = bool(meta.get("page_loaded"))
    checks["authenticated_session"] = bool(meta.get("session_authenticated"))
    checks["expected_page_found"] = bool(meta.get("expected_status_in_url"))
    checks["explicit_empty_state"] = bool(meta.get("empty_table_detected"))
    checks["no_login_redirect"] = bool(meta.get("session_authenticated"))
    checks["not_degraded"] = not bool(meta.get("degraded") or meta.get("partial"))
    reason = str(meta.get("stopped_reason") or "").strip()
    checks["pagination_completed"] = (
        not bool(meta.get("reached_max_pages"))
        and reason in NATURAL_STOP_REASONS
        and reason in VALIDATED_EMPTY_STOP_REASONS
    )
    validated = all(checks.values())
    return validated, checks


def _meta_is_ship_window_discovery(meta: Mapping[str, Any]) -> bool:
    """Rolling ship_to_vendor window is discovery-only — never absence authority."""
    mode = str(meta.get("source_mode") or meta.get("source_role") or "").strip().lower()
    if mode in {
        "ship_to_vendor_window",
        "ship_window",
        "discovery",
        "discovery_only",
    }:
        return True
    if meta.get("absence_capable") is False:
        return True
    guard = meta.get("completeness_guard")
    if isinstance(guard, Mapping) and guard.get("allow_mark_missing") is False:
        return True
    sources = meta.get("tickets_sources") or meta.get("source_summaries") or []
    if not isinstance(sources, list):
        return False
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        url = str(src.get("url") or "")
        if "ship_to_vendor_date_start=" in url or "ship_to_vendor_date_end=" in url:
            return True
        label = str(src.get("label") or "").strip().lower()
        if label in {"wash_and_fold", "hang_dry"} and (
            src.get("ship_to_vendor_date_start") or src.get("ship_to_vendor_date_end")
        ):
            return True
    return False


def portal_scrape_meta_allows_absence_completion(meta: dict[str, Any] | None) -> bool:
    """
    True only when portal export is a trustworthy *complete* traversal.

    Manual uploads (meta None) are allowed (legacy full_snapshot=1).

    Hard invariant: any scheduled scrape meta must explicitly assert
    ``source_inspected_complete=True`` plus a natural stop reason, with no
    degraded/partial/skipped/max-pages signals. Failed, killed, reclaimed,
    or incomplete traversals must never publish Missing From Portal / absence.

    Rolling ship_to_vendor_date windows are discovery sources only: traversing
    every page of that window must never authorize Missing From Portal.
    """
    if meta is None:
        return True
    if _meta_is_ship_window_discovery(meta):
        return False
    if bool(meta.get("reached_max_pages")):
        return False
    if bool(meta.get("degraded") or meta.get("partial")):
        return False
    if bool(meta.get("page_navigation_failed")):
        return False
    try:
        if int(meta.get("skipped_ticket_count") or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False
    # Fail closed: missing/False completeness is not an authoritative snapshot.
    if meta.get("source_inspected_complete") is not True:
        return False
    reason = str(meta.get("stopped_reason") or "").strip()
    if reason == STOPPED_MAX_PAGES_REACHED:
        return False
    if reason in {
        "completed_with_skipped_tickets",
        "page_navigation_failed",
        "partial_portal_scrape",
    }:
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
