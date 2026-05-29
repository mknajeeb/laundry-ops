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
from backend.rinse_portal_csv import portal_csv_to_orders_df
from backend.rinse_processing_settings import get_processing_settings
from backend.ta_helpers import table_exists

PORTAL_STATUS_READY = "ready_for_vendor"
PORTAL_STATUS_AT_VENDOR = "at_vendor"
VALID_PORTAL_STATUSES = frozenset({PORTAL_STATUS_READY, PORTAL_STATUS_AT_VENDOR})


def ensure_rinse_cleaner_ticket_presence_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            portal_status VARCHAR(32) NOT NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            first_seen_at DATETIME(6) NOT NULL,
            last_seen_at DATETIME(6) NOT NULL,
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


def ensure_presence_tables(cursor) -> None:
    ensure_rinse_cleaner_ticket_presence_table(cursor)
    ensure_rinse_cleaner_ticket_presence_runs_table(cursor)


def build_tickets_url_for_portal_status(base_url: str, portal_status: str) -> str:
    ps = str(portal_status or "").strip()
    if ps not in VALID_PORTAL_STATUSES:
        raise ValueError(f"portal_status must be one of {sorted(VALID_PORTAL_STATUSES)}")
    raw = (base_url or "").strip()
    if not raw:
        raw = (
            "https://www.rinse.com/cleanertickets/?q=&estimated_delivery_date_start="
            "&estimated_delivery_date_end=&status=at_vendor&speed=&transactionality="
            "&service_types=&extra_qc=&rfd=&corporate_account=&vip=&assembled=&bagged="
            "&steps_in_cleaning_process=&has_post_clean_weight=&pickup_date_start="
            "&pickup_date_end=&ship_to_vendor_date_start=&ship_to_vendor_date_end="
            "&receive_from_vendor_date_start=&receive_from_vendor_date_end="
        )
    parsed = urlparse(raw)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    out_pairs: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == "status":
            out_pairs.append(("status", ps))
            replaced = True
        else:
            out_pairs.append((k, v))
    if not replaced:
        out_pairs.insert(0, ("status", ps))
    query = urlencode(out_pairs)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def parse_presence_rows_from_portal_csv(csv_path: str) -> list[dict[str, Any]]:
    df = portal_csv_to_orders_df(csv_path)
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        bag_id = normalize_bag_id(r.get("ticket_id") or r.get("Bag ID"))
        if not bag_id:
            continue
        d_clean = r.get("Date_Clean")
        est_delivery = d_clean.isoformat() if hasattr(d_clean, "isoformat") else None
        rush = str(r.get("rush_type") or r.get("Rush_Type") or "").strip() or None
        rows.append(
            {
                "bag_id": bag_id,
                "customer_name": (r.get("Name_Clean") or r.get("Customer") or "").strip() or None,
                "estimated_delivery_date": d_clean if isinstance(d_clean, date) else None,
                "rush_flag": rush,
                "service_type": (r.get("service_type") or r.get("Service_Type") or "").strip() or None,
                "raw_row_json": {
                    "Date_Clean": est_delivery,
                    "Name_Clean": r.get("Name_Clean"),
                    "service_type": r.get("service_type"),
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
                        organization_id, bag_id, portal_status, active,
                        first_seen_at, last_seen_at, source_batch_id,
                        customer_name, estimated_delivery_date, rush_flag,
                        service_type, raw_row_json
                    ) VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        org,
                        bag_id,
                        ps,
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
            changed = (
                str(existing.get("portal_status") or "") != ps
                or int(existing.get("active") or 0) != 1
                or str(existing.get("source_batch_id") or "") != batch_id
                or (existing.get("customer_name") or None) != payload["customer_name"]
            )
            if changed:
                stats["rows_updated"] += 1
            else:
                stats["rows_unchanged"] += 1
            if not dry_run and changed:
                cursor.execute(
                    """
                    UPDATE rinse_cleaner_ticket_presence
                    SET portal_status=%s, active=1, last_seen_at=%s, source_batch_id=%s,
                        customer_name=%s, estimated_delivery_date=%s, rush_flag=%s,
                        service_type=%s, raw_row_json=%s
                    WHERE organization_id=%s AND bag_id=%s
                    """,
                    (
                        ps,
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
        cursor.execute(
            """
            INSERT INTO rinse_cleaner_ticket_presence_runs (
                organization_id, portal_status, source_batch_id, source_url, dry_run,
                rows_found, rows_inserted, rows_updated, rows_unchanged, rows_missing,
                errors_json
            ) VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s)
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
        drying_minutes=int(proc.get("drying_minutes") or 40),
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
