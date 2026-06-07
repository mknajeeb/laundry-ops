"""Rinse cleaner-ticket portal presence (ready_for_vendor / at_vendor), separate from orders_staging."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_lifecycle_status import derive_bag_lifecycle_status
from backend.rinse_portal_csv import parse_rush_flag_from_portal_cells, portal_csv_to_orders_df
from backend.rinse_processing_settings import get_processing_settings
from backend.ta_helpers import table_exists

PORTAL_STATUS_READY = "ready_for_vendor"
PORTAL_STATUS_AT_VENDOR = "at_vendor"
PORTAL_STATUS_MARK_IN = "ready_for_mark_in"
VALID_PORTAL_STATUSES = frozenset({PORTAL_STATUS_READY, PORTAL_STATUS_AT_VENDOR})
# Status values accepted when building portal filter URLs (presence apply uses VALID_PORTAL_STATUSES only).
PORTAL_URL_STATUSES = frozenset({PORTAL_STATUS_READY, PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_MARK_IN})

PRESENCE_RUSH_UNKNOWN = "UNKNOWN"

PORTAL_TICKETS_ORIGIN = "https://www.rinse.com/cleanertickets/"
# Rinse requires the full filter query string — a bare ?status=… often returns an empty table.
PORTAL_FILTER_PARAM_ORDER: tuple[tuple[str, str], ...] = (
    ("q", ""),
    ("estimated_delivery_date_start", ""),
    ("estimated_delivery_date_end", ""),
    ("status", ""),
    ("speed", ""),
    ("transactionality", ""),
    ("service_types", ""),
    ("extra_qc", ""),
    ("rfd", ""),
    ("corporate_account", ""),
    ("vip", ""),
    ("assembled", ""),
    ("bagged", ""),
    ("steps_in_cleaning_process", ""),
    ("has_post_clean_weight", ""),
    ("pickup_date_start", ""),
    ("pickup_date_end", ""),
    ("ship_to_vendor_date_start", ""),
    ("ship_to_vendor_date_end", ""),
    ("receive_from_vendor_date_start", ""),
    ("receive_from_vendor_date_end", ""),
    ("page", "1"),
)

_TRANSITION_COLUMNS = (
    ("previous_portal_status", "VARCHAR(32) NULL AFTER portal_status"),
    ("portal_status_first_seen_at", "DATETIME(6) NULL AFTER last_seen_at"),
    ("portal_status_changed_at", "DATETIME(6) NULL AFTER portal_status_first_seen_at"),
)


def _presence_table_has_column(cursor, col_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'rinse_cleaner_ticket_presence'
          AND COLUMN_NAME = %s
        """,
        (col_name,),
    )
    row = cursor.fetchone()
    n = int(row["c"] if isinstance(row, dict) else row[0])
    return n > 0


def ensure_presence_transition_columns(cursor) -> None:
    """Add portal status transition columns to existing deployments."""
    ensure_rinse_cleaner_ticket_presence_table(cursor)
    for col_name, col_def in _TRANSITION_COLUMNS:
        if not _presence_table_has_column(cursor, col_name):
            cursor.execute(
                f"ALTER TABLE rinse_cleaner_ticket_presence ADD COLUMN {col_name} {col_def}"
            )
    cursor.execute(
        """
        UPDATE rinse_cleaner_ticket_presence
        SET
          portal_status_first_seen_at = COALESCE(portal_status_first_seen_at, first_seen_at),
          portal_status_changed_at = COALESCE(portal_status_changed_at, first_seen_at)
        WHERE portal_status_first_seen_at IS NULL OR portal_status_changed_at IS NULL
        """
    )


def ensure_rinse_cleaner_ticket_presence_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            portal_status VARCHAR(32) NOT NULL,
            previous_portal_status VARCHAR(32) NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            first_seen_at DATETIME(6) NOT NULL,
            last_seen_at DATETIME(6) NOT NULL,
            portal_status_first_seen_at DATETIME(6) NULL,
            portal_status_changed_at DATETIME(6) NULL,
            source_batch_id VARCHAR(64) NULL,
            customer_name VARCHAR(255) NULL,
            estimated_delivery_date DATE NULL,
            rush_flag VARCHAR(32) NULL,
            service_type VARCHAR(64) NULL,
            raw_row_json JSON NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            UNIQUE KEY uq_rinse_presence_org_bag (organization_id, bag_id),
            KEY idx_rinse_presence_org_status (organization_id, portal_status, active),
            KEY idx_rinse_presence_org_last_seen (organization_id, last_seen_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_rinse_cleaner_ticket_presence_runs_table(cursor) -> None:
    from backend.ta_helpers import table_has_column

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence_runs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            portal_status VARCHAR(32) NOT NULL,
            source_batch_id VARCHAR(64) NOT NULL,
            source_url TEXT NULL,
            dry_run TINYINT(1) NOT NULL DEFAULT 0,
            rows_found INT NOT NULL DEFAULT 0,
            rows_inserted INT NOT NULL DEFAULT 0,
            rows_updated INT NOT NULL DEFAULT 0,
            rows_unchanged INT NOT NULL DEFAULT 0,
            rows_missing INT NOT NULL DEFAULT 0,
            errors_json JSON NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            KEY idx_presence_runs_org (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    extra_cols = (
        ("run_type", "VARCHAR(24) NULL"),
        ("status", "VARCHAR(24) NULL"),
        ("started_at", "DATETIME(6) NULL"),
        ("finished_at", "DATETIME(6) NULL"),
        ("duration_seconds", "INT NULL"),
        ("pages_visited", "INT NULL"),
        ("scrape_meta_json", "JSON NULL"),
    )
    for col, ddl in extra_cols:
        if not table_has_column(cursor, "rinse_cleaner_ticket_presence_runs", col):
            cursor.execute(
                f"ALTER TABLE rinse_cleaner_ticket_presence_runs ADD COLUMN {col} {ddl}"
            )


def ensure_presence_tables(cursor) -> None:
    ensure_rinse_cleaner_ticket_presence_table(cursor)
    ensure_rinse_cleaner_ticket_presence_runs_table(cursor)
    ensure_presence_transition_columns(cursor)


def build_tickets_url_for_portal_status(
    base_url: str,
    portal_status: str,
    *,
    page: int = 1,
) -> str:
    """
    Build the full Rinse cleaner-tickets filter URL for a portal status.

    Empty filter parameters are required — ``?status=ready_for_vendor`` alone often
    yields zero table rows even when the sidebar filter shows many tickets.
    """
    ps = str(portal_status or "").strip()
    if ps not in PORTAL_URL_STATUSES:
        raise ValueError(f"portal_status must be one of {sorted(PORTAL_URL_STATUSES)}")
    page_num = max(1, int(page))

    raw = (base_url or "").strip() or PORTAL_TICKETS_ORIGIN
    parsed = urlparse(raw)
    base_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))

    param_map: dict[str, str] = {k: v for k, v in PORTAL_FILTER_PARAM_ORDER}
    # Preserve tenant-specific non-filter overrides from configured base URL (e.g. q=).
    for key in param_map:
        if key in base_pairs and key not in ("status", "page"):
            param_map[key] = base_pairs[key]
    if base_pairs.get("q"):
        param_map["q"] = base_pairs["q"]

    param_map["status"] = ps
    param_map["page"] = str(page_num)

    ordered_keys = [k for k, _ in PORTAL_FILTER_PARAM_ORDER]
    out_pairs = [(k, param_map[k]) for k in ordered_keys]
    query = urlencode(out_pairs)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or "www.rinse.com"
    path = parsed.path or "/cleanertickets/"
    return urlunparse((scheme, netloc, path, "", query, ""))


def read_portal_scrape_meta(meta_path: str) -> dict[str, Any]:
    """Load scrape.mjs portal meta JSON (pages scraped, stop reason, row_count)."""
    try:
        with open(meta_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def build_presence_scrape_debug(
    *,
    portal_status: str,
    source_url: str,
    rows: Sequence[Mapping[str, Any]],
    scrape_meta: Mapping[str, Any] | None = None,
    exit_code: int = 0,
) -> dict[str, Any]:
    """Debug block returned by presence scrape API."""
    meta = dict(scrape_meta or {})
    parsed_preview = [
        {
            "bag_id": r.get("bag_id"),
            "customer_name": r.get("customer_name"),
            "estimated_delivery_date": (
                r.get("estimated_delivery_date").isoformat()
                if hasattr(r.get("estimated_delivery_date"), "isoformat")
                else r.get("estimated_delivery_date")
            ),
            "rush_flag": r.get("rush_flag"),
            "service_type": r.get("service_type"),
        }
        for r in list(rows)[:5]
    ]
    return {
        "portal_status_requested": portal_status,
        "resolved_url": source_url,
        "scrape_exit_code": exit_code,
        "pages_visited": meta.get("pages_scraped"),
        "rows_per_page_meta": meta.get("rows_per_page"),
        "row_count_exported": meta.get("row_count"),
        "row_count_parsed": len(rows),
        "stopped_reason": meta.get("stopped_reason"),
        "max_pages_limit": meta.get("max_pages_limit"),
        "first_parsed_rows": parsed_preview,
        "rows_without_bag_id": sum(1 for r in rows if not r.get("bag_id")),
    }


def parse_presence_rows_from_portal_csv(csv_path: str) -> list[dict[str, Any]]:
    import pandas as pd

    raw_df = pd.read_csv(csv_path, encoding="utf-8-sig")
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    raw_by_bag: dict[str, dict[str, Any]] = {}
    for _, raw_r in raw_df.iterrows():
        from backend.rinse_portal_csv import _ticket_id_from_bag, _cell

        bag = _cell(raw_r, "Bag ID")
        bid = _ticket_id_from_bag(bag)
        if bid:
            raw_by_bag[bid] = {
                "date_raw": _cell(raw_r, "Date"),
                "customer": _cell(raw_r, "Customer"),
                "service_type_raw": _cell(raw_r, "Service Type"),
            }

    df = portal_csv_to_orders_df(csv_path)
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        bag_id = normalize_bag_id(r.get("ticket_id") or r.get("Bag ID"))
        if not bag_id:
            continue
        d_clean = r.get("Date_Clean")
        raw = raw_by_bag.get(bag_id, {})
        date_raw = raw.get("date_raw")
        cells = [
            x
            for x in (
                date_raw,
                raw.get("customer"),
                raw.get("service_type_raw"),
                r.get("Name_Clean"),
                r.get("ServiceType"),
            )
            if x
        ]
        rush_parsed = parse_rush_flag_from_portal_cells(cells)
        rush_from_df = str(r.get("RushType") or r.get("rush_type") or "").strip().upper()
        if rush_parsed in ("RUSH", "NON-RUSH"):
            rush = rush_parsed
        elif rush_from_df in ("RUSH", "NON-RUSH"):
            rush = rush_from_df
        else:
            rush = None
        svc = str(r.get("ServiceType") or raw.get("service_type_raw") or "").strip().upper() or None
        rows.append(
            {
                "bag_id": bag_id,
                "customer_name": (r.get("Name_Clean") or raw.get("customer") or "").strip() or None,
                "estimated_delivery_date": d_clean if isinstance(d_clean, date) else None,
                "rush_flag": rush,
                "service_type": svc,
                "raw_row_json": {
                    "Date_Clean": d_clean.isoformat() if hasattr(d_clean, "isoformat") else None,
                    "estimated_delivery_text": date_raw,
                    "Name_Clean": r.get("Name_Clean"),
                    "service_type": svc,
                    "rush_type": rush,
                    "ticket_id": bag_id,
                },
            }
        )
    return rows


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fetch_presence_row(cursor, organization_id: int, bag_id: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT *
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bag_id),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def get_presence_flags(cursor, organization_id: int, bag_id: str) -> tuple[bool, bool]:
    """Return (ready_for_vendor_presence, at_vendor_presence) for lifecycle engine."""
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return False, False
    row = _fetch_presence_row(cursor, organization_id, bag_id)
    if not row or not int(row.get("active") or 0):
        return False, False
    ps = str(row.get("portal_status") or "").strip()
    if ps == PORTAL_STATUS_READY:
        return True, False
    if ps == PORTAL_STATUS_AT_VENDOR:
        return False, True
    return False, False


def _rush_from_raw_row_json(raw_json: Any) -> str | None:
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw_json, dict):
        return None
    text = raw_json.get("estimated_delivery_text") or raw_json.get("Date_Clean") or ""
    if text and parse_rush_flag_from_portal_cells([text]) == "RUSH":
        return "RUSH"
    rt = str(raw_json.get("rush_type") or "").strip().upper()
    if rt in ("RUSH", "NON-RUSH"):
        return rt
    return None


def _parse_presence_date(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _presence_raw_row_json(row: Mapping[str, Any]) -> dict[str, Any]:
    rj = row.get("raw_row_json")
    if isinstance(rj, dict):
        return rj
    if isinstance(rj, str) and rj.strip():
        try:
            parsed = json.loads(rj)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _infer_service_type_from_text(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    if text in ("WF", "WASH & FOLD", "WASH AND FOLD"):
        return "WF"
    if text in ("HD", "HOME DELIVERY", "HANG DRY", "HANG-DRY"):
        return "HD"
    if "HOME" in text and "DELIV" in text:
        return "HD"
    if "HANG" in text and "DRY" in text:
        return "HD"
    if "WASH" in text and "FOLD" in text:
        return "WF"
    return None


def _presence_service_type(row: Mapping[str, Any]) -> str | None:
    svc_raw = str(row.get("service_type") or "").strip().upper()
    if svc_raw in ("WF", "HD"):
        return svc_raw
    rj = _presence_raw_row_json(row)
    for key in ("service_type", "ServiceType", "service_type_raw"):
        inferred = _infer_service_type_from_text(rj.get(key))
        if inferred:
            return inferred
    return _infer_service_type_from_text(svc_raw)


def _presence_effective_rush(row: Mapping[str, Any], target_date: date) -> str:
    rf = str(row.get("rush_flag") or "").strip().upper()
    if rf == "RUSH":
        return "RUSH"
    if rf == "NON-RUSH":
        return "NON-RUSH"
    parsed = _rush_from_raw_row_json(row.get("raw_row_json"))
    if parsed == "RUSH":
        return "RUSH"
    if parsed == "NON-RUSH":
        return "NON-RUSH"
    edd = _parse_presence_date(row.get("estimated_delivery_date"))
    if edd is None:
        rj = _presence_raw_row_json(row)
        edd = _parse_presence_date(rj.get("Date_Clean"))
    if edd is not None:
        return "RUSH" if edd < target_date else "NON-RUSH"
    return PRESENCE_RUSH_UNKNOWN


def load_wf_presence_at_vendor_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    exclude_bag_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    WF at_vendor presence rows not already in staging — supplements WF production lifecycle.

    ready_for_vendor rows belong in Incoming / Unassigned, not WF lifecycle.
    """
    meta = {
        "wf_at_vendor_presence_only": 0,
        "hd_presence_excluded": 0,
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return [], meta

    org = int(organization_id)
    td = target_date
    excluded = {str(b or "").strip().upper() for b in exclude_bag_ids if str(b or "").strip()}
    cursor.execute(
        """
        SELECT
            bag_id, portal_status, customer_name, estimated_delivery_date,
            rush_flag, service_type, portal_status_first_seen_at, last_seen_at, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    rows: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid or bid in excluded:
            continue
        svc_raw = str(raw.get("service_type") or "").strip().upper()
        if svc_raw == "HD":
            meta["hd_presence_excluded"] += 1
            continue
        if svc_raw and svc_raw != "WF":
            meta["hd_presence_excluded"] += 1
            continue
        if not svc_raw:
            continue
        meta["wf_at_vendor_presence_only"] += 1
        rows.append(
            {
                "bag_id": bid,
                "service_type": "WF",
                "effective_rush": _presence_effective_rush(raw, td),
                "is_completed": 0,
                "name_clean": raw.get("customer_name"),
                "weight_num": None,
                "logistics_status": None,
                "date_clean": raw.get("estimated_delivery_date"),
                "ready_for_vendor_presence": False,
                "at_vendor_presence": True,
                "presence_source": True,
                "presence_portal_status": PORTAL_STATUS_AT_VENDOR,
                "presence_first_seen_at": raw.get("portal_status_first_seen_at"),
                "presence_last_seen_at": raw.get("last_seen_at"),
            }
        )
    return rows, meta


def load_incoming_unassigned_presence_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    exclude_bag_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All active ready_for_vendor presence rows (WF, HD, unknown) — Incoming / Unassigned scope."""
    meta = {
        "incoming_total": 0,
        "incoming_wf": 0,
        "incoming_hd": 0,
        "incoming_unknown_service": 0,
        "incoming_rush": 0,
        "incoming_non_rush": 0,
        "incoming_unknown_rush": 0,
        "last_presence_refresh_at": None,
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return [], meta

    org = int(organization_id)
    td = target_date
    excluded = {str(b or "").strip().upper() for b in (exclude_bag_ids or set()) if str(b or "").strip()}
    cursor.execute(
        """
        SELECT
            bag_id, portal_status, customer_name, estimated_delivery_date,
            rush_flag, service_type, portal_status_first_seen_at, last_seen_at, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        ORDER BY last_seen_at DESC
        """,
        (org, PORTAL_STATUS_READY),
    )
    rows: list[dict[str, Any]] = []
    latest_seen: datetime | None = None
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid or bid in excluded:
            continue
        ls = raw.get("last_seen_at")
        if isinstance(ls, datetime) and (latest_seen is None or ls > latest_seen):
            latest_seen = ls
        svc_raw = _presence_service_type(raw) or ""
        eff_rush = _presence_effective_rush(raw, td)
        needs_review = not svc_raw or eff_rush == PRESENCE_RUSH_UNKNOWN

        meta["incoming_total"] += 1
        if svc_raw == "WF":
            meta["incoming_wf"] += 1
        elif svc_raw == "HD":
            meta["incoming_hd"] += 1
        else:
            meta["incoming_unknown_service"] += 1
        if eff_rush == "RUSH":
            meta["incoming_rush"] += 1
        elif eff_rush == "NON-RUSH":
            meta["incoming_non_rush"] += 1
        else:
            meta["incoming_unknown_rush"] += 1

        rj = raw.get("raw_row_json")
        if isinstance(rj, str):
            try:
                rj = json.loads(rj)
            except (json.JSONDecodeError, TypeError):
                rj = {}
        group_key = (
            "rush"
            if eff_rush == "RUSH"
            else ("non_rush" if eff_rush == "NON-RUSH" else "unknown_rush")
        )
        rows.append(
            {
                "bag_id": bid,
                "customer": raw.get("customer_name"),
                "service_type": svc_raw or None,
                "effective_rush": eff_rush,
                "rush": eff_rush == "RUSH",
                "group": group_key,
                "rush_label": (
                    "Rush"
                    if eff_rush == "RUSH"
                    else ("Non-Rush" if eff_rush == "NON-RUSH" else "Unknown speed")
                ),
                "portal_status": PORTAL_STATUS_READY,
                "estimated_delivery_date": raw.get("estimated_delivery_date"),
                "estimated_delivery_text": (rj or {}).get("estimated_delivery_text"),
                "needs_review": needs_review,
                "presence_source": True,
                "record_scope": "incoming",
                "ready_for_vendor": True,
            }
        )
    meta["last_presence_refresh_at"] = latest_seen.isoformat() if latest_seen else None
    return rows, meta


# Backward-compatible alias used in tests
def load_wf_presence_incoming_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    exclude_bag_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deprecated name — returns at_vendor WF rows for production lifecycle supplement only."""
    return load_wf_presence_at_vendor_rows(
        cursor, organization_id, target_date=target_date, exclude_bag_ids=exclude_bag_ids
    )


def load_presence_portal_snapshot_counts(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> dict[str, Any]:
    """Active presence rows broken down for reconciliation (not lifecycle scope)."""
    out: dict[str, Any] = {
        "ready_for_vendor_total": 0,
        "ready_for_vendor_wf": 0,
        "ready_for_vendor_hd": 0,
        "ready_for_vendor_unknown_service": 0,
        "ready_for_vendor_rush": 0,
        "ready_for_vendor_non_rush": 0,
        "ready_for_vendor_unknown_rush": 0,
        "at_vendor_wf": 0,
        "at_vendor_hd": 0,
        "last_presence_refresh_at": None,
        "sample_ready_for_vendor_rows": [],
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return out

    org = int(organization_id)
    td = target_date
    cursor.execute(
        """
        SELECT
            bag_id, portal_status, customer_name, estimated_delivery_date,
            rush_flag, service_type, last_seen_at, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1
          AND portal_status IN (%s, %s)
        ORDER BY last_seen_at DESC
        """,
        (org, PORTAL_STATUS_READY, PORTAL_STATUS_AT_VENDOR),
    )
    rows = cursor.fetchall() or []
    latest_seen: datetime | None = None
    samples: list[dict[str, Any]] = []

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        ls = raw.get("last_seen_at")
        if isinstance(ls, datetime) and (latest_seen is None or ls > latest_seen):
            latest_seen = ls
        ps = str(raw.get("portal_status") or "").strip()
        svc = str(raw.get("service_type") or "").strip().upper()
        eff_rush = _presence_effective_rush(raw, td)

        if ps == PORTAL_STATUS_READY:
            out["ready_for_vendor_total"] += 1
            if svc == "HD":
                out["ready_for_vendor_hd"] += 1
            elif svc == "WF":
                out["ready_for_vendor_wf"] += 1
                if eff_rush == "RUSH":
                    out["ready_for_vendor_rush"] += 1
                elif eff_rush == "NON-RUSH":
                    out["ready_for_vendor_non_rush"] += 1
                else:
                    out["ready_for_vendor_unknown_rush"] += 1
            else:
                out["ready_for_vendor_unknown_service"] += 1
            if len(samples) < 10:
                rj = raw.get("raw_row_json")
                if isinstance(rj, str):
                    try:
                        rj = json.loads(rj)
                    except (json.JSONDecodeError, TypeError):
                        rj = {}
                samples.append(
                    {
                        "bag_id": raw.get("bag_id"),
                        "service_type": svc or None,
                        "rush_flag": raw.get("rush_flag"),
                        "effective_rush": eff_rush,
                        "estimated_delivery_text": (rj or {}).get("estimated_delivery_text"),
                    }
                )
        elif ps == PORTAL_STATUS_AT_VENDOR:
            if svc == "HD":
                out["at_vendor_hd"] += 1
            elif svc == "WF" or not svc:
                out["at_vendor_wf"] += 1

    out["last_presence_refresh_at"] = latest_seen.isoformat() if latest_seen else None
    out["sample_ready_for_vendor_rows"] = samples
    return out


def apply_presence_scrape(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    rows: Sequence[Mapping[str, Any]],
    source_batch_id: str | None = None,
    source_url: str | None = None,
    dry_run: bool = True,
    mark_missing: bool = False,
    run_type: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    status: str | None = None,
    scrape_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ps = str(portal_status or "").strip()
    if ps not in VALID_PORTAL_STATUSES:
        raise ValueError(f"Invalid portal_status: {portal_status}")

    ensure_presence_tables(cursor)
    org = int(organization_id)
    batch_id = (source_batch_id or "").strip() or uuid.uuid4().hex
    now = _utc_now()
    seen: set[str] = set()
    stats = {
        "organization_id": org,
        "portal_status": ps,
        "source_batch_id": batch_id,
        "source_url": source_url,
        "dry_run": bool(dry_run),
        "rows_found": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_unchanged": 0,
        "rows_missing": 0,
        "errors": [],
    }

    for raw in rows:
        bag_id = normalize_bag_id(raw.get("bag_id"))
        if not bag_id:
            stats["errors"].append({"error": "missing bag_id", "row": dict(raw)})
            continue
        seen.add(bag_id)
        stats["rows_found"] += 1

        existing = _fetch_presence_row(cursor, org, bag_id)
        payload = {
            "portal_status": ps,
            "active": 1,
            "last_seen_at": now,
            "source_batch_id": batch_id,
            "customer_name": raw.get("customer_name"),
            "estimated_delivery_date": raw.get("estimated_delivery_date"),
            "rush_flag": raw.get("rush_flag"),
            "service_type": raw.get("service_type"),
            "raw_row_json": json.dumps(raw.get("raw_row_json") or {}),
        }

        if existing is None:
            stats["rows_inserted"] += 1
            if not dry_run:
                cursor.execute(
                    """
                    INSERT INTO rinse_cleaner_ticket_presence (
                        organization_id, bag_id, portal_status, previous_portal_status, active,
                        first_seen_at, last_seen_at, portal_status_first_seen_at,
                        portal_status_changed_at, source_batch_id,
                        customer_name, estimated_delivery_date, rush_flag,
                        service_type, raw_row_json
                    ) VALUES (%s,%s,%s,NULL,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        org,
                        bag_id,
                        ps,
                        now,
                        now,
                        now,
                        now,
                        batch_id,
                        payload["customer_name"],
                        payload["estimated_delivery_date"],
                        payload["rush_flag"],
                        payload["service_type"],
                        payload["raw_row_json"],
                    ),
                )
        else:
            existing_status = str(existing.get("portal_status") or "")
            status_changed = existing_status != ps
            was_inactive = int(existing.get("active") or 0) != 1
            metadata_changed = (
                was_inactive
                or str(existing.get("source_batch_id") or "") != batch_id
                or (existing.get("customer_name") or None) != payload["customer_name"]
                or (existing.get("estimated_delivery_date") or None) != payload["estimated_delivery_date"]
                or (existing.get("rush_flag") or None) != payload["rush_flag"]
                or (existing.get("service_type") or None) != payload["service_type"]
            )
            changed = status_changed or metadata_changed
            if changed:
                stats["rows_updated"] += 1
            else:
                stats["rows_unchanged"] += 1
            if not dry_run and changed:
                if status_changed:
                    cursor.execute(
                        """
                        UPDATE rinse_cleaner_ticket_presence
                        SET portal_status=%s, previous_portal_status=%s, active=1,
                            last_seen_at=%s, portal_status_first_seen_at=%s,
                            portal_status_changed_at=%s, source_batch_id=%s,
                            customer_name=%s, estimated_delivery_date=%s, rush_flag=%s,
                            service_type=%s, raw_row_json=%s
                        WHERE organization_id=%s AND bag_id=%s
                        """,
                        (
                            ps,
                            existing_status or None,
                            now,
                            now,
                            now,
                            batch_id,
                            payload["customer_name"],
                            payload["estimated_delivery_date"],
                            payload["rush_flag"],
                            payload["service_type"],
                            payload["raw_row_json"],
                            org,
                            bag_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE rinse_cleaner_ticket_presence
                        SET active=1, last_seen_at=%s, source_batch_id=%s,
                            customer_name=%s, estimated_delivery_date=%s, rush_flag=%s,
                            service_type=%s, raw_row_json=%s
                        WHERE organization_id=%s AND bag_id=%s
                        """,
                        (
                            now,
                            batch_id,
                            payload["customer_name"],
                            payload["estimated_delivery_date"],
                            payload["rush_flag"],
                            payload["service_type"],
                            payload["raw_row_json"],
                            org,
                            bag_id,
                        ),
                    )

    if mark_missing:
        cursor.execute(
            """
            SELECT bag_id FROM rinse_cleaner_ticket_presence
            WHERE organization_id=%s AND portal_status=%s AND active=1
            """,
            (org, ps),
        )
        for row in cursor.fetchall() or []:
            bid = row.get("bag_id") if isinstance(row, dict) else row[0]
            if bid and bid not in seen:
                stats["rows_missing"] += 1
                if not dry_run:
                    cursor.execute(
                        """
                        UPDATE rinse_cleaner_ticket_presence
                        SET active=0, last_seen_at=%s
                        WHERE organization_id=%s AND bag_id=%s
                        """,
                        (now, org, bid),
                    )

    if not dry_run:
        run_started = started_at or now
        run_finished = finished_at or now
        duration_seconds = None
        if run_started and run_finished:
            duration_seconds = max(0, int((run_finished - run_started).total_seconds()))
        pages_visited = None
        if scrape_meta and scrape_meta.get("pages_scraped") is not None:
            try:
                pages_visited = int(scrape_meta.get("pages_scraped"))
            except (TypeError, ValueError):
                pages_visited = None
        run_status = status or ("success" if not stats["errors"] else "partial")
        cursor.execute(
            """
            INSERT INTO rinse_cleaner_ticket_presence_runs (
                organization_id, portal_status, source_batch_id, source_url, dry_run,
                rows_found, rows_inserted, rows_updated, rows_unchanged, rows_missing,
                errors_json, run_type, status, started_at, finished_at, duration_seconds,
                pages_visited, scrape_meta_json
            ) VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                org,
                ps,
                batch_id,
                source_url,
                stats["rows_found"],
                stats["rows_inserted"],
                stats["rows_updated"],
                stats["rows_unchanged"],
                stats["rows_missing"],
                json.dumps(stats["errors"]) if stats["errors"] else None,
                run_type,
                run_status,
                run_started,
                run_finished,
                duration_seconds,
                pages_visited,
                json.dumps(dict(scrape_meta)) if scrape_meta else None,
            ),
        )

    return stats


def build_lifecycle_status_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    scan_events: Sequence[Mapping[str, Any]] | None = None,
    logistics_status: str | None = None,
    mapped_internal_users: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Lifecycle snapshot including portal presence flags (for detail/debug, not dashboard)."""
    from backend.rinse_bag_registry import list_scan_events_for_bag

    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"error": "invalid bag_id"}

    org = int(organization_id)
    events = list(scan_events) if scan_events is not None else list_scan_events_for_bag(cursor, org, bid)
    ready_presence, at_presence = get_presence_flags(cursor, org, bid)
    proc = get_processing_settings(cursor, org)

    lifecycle = derive_bag_lifecycle_status(
        events,
        bag_id=bid,
        ready_for_vendor_presence=ready_presence,
        at_vendor_presence=at_presence,
        logistics_status=logistics_status,
        mapped_internal_users=mapped_internal_users,
        washing_minutes=int(proc.get("washing_minutes") or 30),
        drying_minutes=int(proc.get("drying_minutes") or 45),
        reject_after_create_issue_minutes=int(proc.get("reject_after_create_issue_minutes") or 45),
    )
    return {
        "lifecycle_status": lifecycle,
        "portal_presence": {
            "ready_for_vendor_presence": ready_presence,
            "at_vendor_presence": at_presence,
            "row": _fetch_presence_row(cursor, org, bid) if table_exists(cursor, "rinse_cleaner_ticket_presence") else None,
        },
    }


def presence_url_status_from_url(url: str) -> str | None:
    m = re.search(r"[?&]status=([^&]+)", url or "")
    if not m:
        return None
    val = m.group(1).strip()
    return val if val in VALID_PORTAL_STATUSES else val
