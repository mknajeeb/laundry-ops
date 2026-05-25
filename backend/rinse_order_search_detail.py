"""
Order Search lifecycle detail — registry, uploads, staging, scans, folding, scrape.

Each section loads independently; failures become empty sections + section_errors
instead of failing the whole detail response.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from backend.rinse_bag_folding import (
    FOLDING_WARNING_CODES,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    STATUS_EXCLUDED,
    WARNING_MULTIPLE_CLEAN_SCANS,
    rack_contains_clean,
    rack_contains_folding,
)
from backend.rinse_bag_registry import list_scan_events_for_bag
from backend.rinse_bag_upload import find_active_staging_by_ticket_id
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scrape_status import fetch_scrape_run_for_batch
from backend.ta_helpers import table_exists, table_has_column

log = logging.getLogger(__name__)

PURGED_ROW_MESSAGE = (
    "Raw upload row detail was purged after retention period. Batch summary remains available."
)

FOLDING_CODE_LABELS: dict[str, str] = {
    "MISSING_SCAN_EVENTS": "No scan events are stored for this bag.",
    "MISSING_FOLDING": "No FOLDING rack scan was found.",
    "MISSING_CLEAN": "No CLEAN rack scan was found after folding.",
    "CLEAN_BEFORE_FOLDING": "A CLEAN scan occurred before the folding scan (invalid order).",
    "INVALID_TIMESTAMPS": "Folding or clean scan timestamps could not be parsed reliably.",
    "MISSING_ASSIGNED_USER": "Neither the folding nor the end clean scan has an assigned user.",
    "MULTIPLE_FOLDING_SCANS": "More than one FOLDING rack scan was found; folding cannot be calculated automatically.",
    "FOLDING_DURATION_TOO_SHORT": "Folding interval is under 10 minutes.",
    WARNING_MULTIPLE_CLEAN_SCANS: (
        "More than one CLEAN rack scan occurred after the folding scan. "
        "Duration still uses the first FOLDING scan and the last CLEAN scan after folding."
    ),
}


def _upload_batches_pk(cursor) -> str:
    if table_has_column(cursor, "upload_batches", "batch_id"):
        return "batch_id"
    return "id"


def _safe_section(
    section_errors: dict[str, str],
    name: str,
    fn: Callable[[], Any],
    default: Any,
) -> Any:
    try:
        return fn()
    except Exception as exc:
        log.warning("order detail section %s failed: %s", name, exc, exc_info=True)
        section_errors[name] = str(exc)
        return default


def _folding_rates(perf: dict[str, Any] | None) -> dict[str, Any]:
    if not perf:
        return {"lbs_per_hour": None, "bags_per_hour": None}
    dur = perf.get("duration_seconds")
    weight = perf.get("weight_lbs")
    try:
        secs = float(dur) if dur is not None else 0.0
        lbs = float(weight) if weight is not None else None
    except (TypeError, ValueError):
        secs, lbs = 0.0, None
    hours = secs / 3600.0 if secs > 0 else 0.0
    lbs_hr = round(lbs / hours, 2) if hours > 0 and lbs is not None else None
    bags_hr = round(1.0 / hours, 2) if hours > 0 else None
    return {"lbs_per_hour": lbs_hr, "bags_per_hour": bags_hr}


def _event_brief(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ev.get("id"),
        "scan_index": ev.get("scan_index"),
        "purpose": ev.get("purpose"),
        "rack": ev.get("rack"),
        "user_name": ev.get("user_name"),
        "time_scanned_raw": ev.get("time_scanned_raw"),
        "scanned_at_parsed": ev.get("scanned_at_parsed"),
        "source_upload_batch_id": ev.get("source_upload_batch_id"),
        "created_at": ev.get("created_at"),
    }


def build_folding_detail(
    perf: dict[str, Any] | None,
    scan_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not perf:
        return None
    code = str(perf.get("exception_code") or "").strip() or None
    status = str(perf.get("status") or "").upper()
    excluded = bool(int(perf.get("excluded_from_performance") or 0))
    included = status == STATUS_CALCULATED and not excluded

    by_id: dict[int, dict[str, Any]] = {}
    for ev in scan_events:
        eid = ev.get("id")
        if eid is None:
            continue
        try:
            by_id[int(eid)] = ev
        except (TypeError, ValueError):
            continue

    start_id = perf.get("folding_start_event_id")
    end_id = perf.get("folding_end_event_id")
    scans_used: list[dict[str, Any]] = []
    try:
        if start_id is not None and int(start_id) in by_id:
            scans_used.append(_event_brief(by_id[int(start_id)]))
        if end_id is not None and int(end_id) in by_id and int(end_id) != int(start_id or -1):
            scans_used.append(_event_brief(by_id[int(end_id)]))
    except (TypeError, ValueError):
        pass

    folding_scans = []
    clean_scans = []
    for ev in scan_events:
        if rack_contains_folding(ev.get("rack")):
            folding_scans.append(_event_brief(ev))
        if rack_contains_clean(ev.get("rack")):
            clean_scans.append(_event_brief(ev))

    plain = FOLDING_CODE_LABELS.get(code or "", "")
    if code == WARNING_MULTIPLE_CLEAN_SCANS:
        plain = FOLDING_CODE_LABELS[WARNING_MULTIPLE_CLEAN_SCANS]
    elif code and not plain:
        plain = f"Folding code: {code}."
    if not plain and status == STATUS_CALCULATED:
        plain = "Folding interval calculated from FOLDING → CLEAN scans."
    if status == STATUS_EXCLUDED:
        plain = (plain + " " if plain else "") + "This bag is excluded from performance scoring."

    warning_only = code in FOLDING_WARNING_CODES if code else False
    rates = _folding_rates(perf)

    return {
        "performance": perf,
        "weight_lbs": perf.get("weight_lbs"),
        "status": status,
        "exception_code": code,
        "plain_english_reason": plain or None,
        "included_in_scoring": included,
        "warning_only": warning_only,
        "excluded_from_performance": excluded,
        "admin_notes": perf.get("admin_notes"),
        "scans_used_for_calculation": scans_used,
        "folding_rack_scans": folding_scans,
        "clean_rack_scans": clean_scans,
        "folding_scan_count": perf.get("folding_scan_count"),
        "clean_scan_count": perf.get("clean_scan_count"),
        **rates,
    }


def _staging_columns(cursor) -> list[str]:
    """Only columns that exist on orders_staging (production schemas vary)."""
    candidates = [
        "id",
        "ticket_id",
        "date_clean",
        "name_clean",
        "weight_num",
        "service_type",
        "rush_type",
        "batch_date",
        "created_at",
        "updated_at",
        "status",
        "checkout_status",
        "logistics_status",
        "processing_status",
        "checked_out_at",
        "closed_at",
    ]
    if not table_exists(cursor, "orders_staging"):
        return ["id"]
    return [c for c in candidates if table_has_column(cursor, "orders_staging", c)]


def _row_is_active_staging(row: dict[str, Any]) -> bool:
    logistics = str(row.get("logistics_status") or "").strip().upper()
    status = str(row.get("status") or "").strip().upper()
    if row.get("logistics_status") is not None or logistics:
        if not logistics:
            if status == "CHECKED_OUT":
                logistics = "SENT_TO_RINSE"
            elif status == "FORCED_CHECKOUT":
                logistics = "FORCE_CHECKOUT"
            else:
                logistics = "AT_WASHPRO"
        return logistics not in ("SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT")
    if row.get("status") is not None or status:
        return status not in ("CHECKED_OUT", "FORCED_CHECKOUT")
    return True


def list_staging_history_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    has_staging_org: bool,
    has_ticket_id_col: bool,
) -> list[dict[str, Any]]:
    if not has_ticket_id_col or not table_exists(cursor, "orders_staging"):
        return []
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    cols = _staging_columns(cursor)
    if "ticket_id" not in cols:
        return []
    sql = f"SELECT {', '.join(cols)} FROM orders_staging WHERE ticket_id = %s"
    args: list[Any] = [bid]
    if has_staging_org and table_has_column(cursor, "orders_staging", "organization_id"):
        sql += " AND organization_id = %s"
        args.append(int(organization_id))
    sql += " ORDER BY id DESC LIMIT 50"
    cursor.execute(sql, tuple(args))
    rows = list(cursor.fetchall() or [])
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({**row, "active_in_checkout": _row_is_active_staging(row)})
    return out


def _collect_upload_batch_ids(
    cursor,
    organization_id: int,
    bag_id: str,
    registry: dict[str, Any],
) -> list[int]:
    ids: set[int] = set()
    for key in ("last_upload_batch_id", "last_seen_upload_batch_id"):
        if not table_has_column(cursor, "rinse_bag_registry", key):
            continue
        v = registry.get(key)
        if v is not None:
            try:
                ids.add(int(v))
            except (TypeError, ValueError):
                pass

    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            """
            SELECT DISTINCT upload_batch_id FROM upload_batch_rows
            WHERE ticket_id = %s
            ORDER BY upload_batch_id DESC
            """,
            (bag_id,),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("upload_batch_id") is not None:
                ids.add(int(row["upload_batch_id"]))

    if table_exists(cursor, "rinse_bag_scan_events") and table_has_column(
        cursor, "rinse_bag_scan_events", "source_upload_batch_id"
    ):
        cursor.execute(
            """
            SELECT DISTINCT source_upload_batch_id FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id = %s AND source_upload_batch_id IS NOT NULL
            """,
            (int(organization_id), bag_id),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("source_upload_batch_id") is not None:
                ids.add(int(row["source_upload_batch_id"]))

    return sorted(ids, reverse=True)


def list_upload_history_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    registry: dict[str, Any],
    *,
    upload_batch_row_pk: str = "id",
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "upload_batches"):
        return []

    batch_ids = _collect_upload_batch_ids(cursor, organization_id, bag_id, registry)
    if not batch_ids:
        return []

    pk = _upload_batches_pk(cursor)
    has_purged = table_has_column(cursor, "upload_batches", "raw_rows_purged_at")
    has_summary = table_has_column(cursor, "upload_batches", "purged_summary_json")
    ub_cols = [f"{pk} AS batch_id", "state", "batch_date"]
    if table_has_column(cursor, "upload_batches", "created_at"):
        ub_cols.append("created_at")
    elif table_has_column(cursor, "upload_batches", "uploaded_at"):
        ub_cols.append("uploaded_at AS created_at")
    if table_has_column(cursor, "upload_batches", "confirmed_at"):
        ub_cols.append("confirmed_at")
    if has_purged:
        ub_cols.append("raw_rows_purged_at")
    if has_summary:
        ub_cols.append("purged_summary_json")

    placeholders = ", ".join(["%s"] * len(batch_ids))
    cursor.execute(
        f"""
        SELECT {", ".join(ub_cols)}
        FROM upload_batches
        WHERE {pk} IN ({placeholders})
        ORDER BY {pk} DESC
        """,
        tuple(batch_ids),
    )
    batches_by_id: dict[int, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if isinstance(row, dict) and row.get("batch_id") is not None:
            batches_by_id[int(row["batch_id"])] = row

    rows_by_batch: dict[int, dict[str, Any]] = {}
    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            f"""
            SELECT ubr.id, ubr.upload_batch_id, ubr.row_status, ubr.reason,
                   ubr.date_clean, ubr.name_clean, ubr.created_at,
                   ub.state, ub.confirmed_at, ub.batch_date,
                   ub.created_at AS batch_created_at
            FROM upload_batch_rows ubr
            LEFT JOIN upload_batches ub ON ub.{pk} = ubr.upload_batch_id
            WHERE ubr.ticket_id = %s
            ORDER BY ubr.upload_batch_id DESC, ubr.{upload_batch_row_pk} DESC
            """,
            (bag_id,),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("upload_batch_id") is not None:
                bid = int(row["upload_batch_id"])
                if bid not in rows_by_batch:
                    rows_by_batch[bid] = row

    history: list[dict[str, Any]] = []
    for batch_id in batch_ids:
        batch = batches_by_id.get(batch_id) or {}
        row = rows_by_batch.get(batch_id)
        purged = bool(batch.get("raw_rows_purged_at")) if has_purged else False
        entry: dict[str, Any] = {
            "upload_batch_id": batch_id,
            "batch_state": batch.get("state") or (row.get("state") if row else None),
            "batch_date": batch.get("batch_date") or (row.get("batch_date") if row else None),
            "batch_created_at": batch.get("created_at") or (row.get("batch_created_at") if row else None),
            "confirmed_at": batch.get("confirmed_at") or (row.get("confirmed_at") if row else None),
            "row_status": row.get("row_status") if row else None,
            "reason": row.get("reason") if row else None,
            "row_created_at": row.get("created_at") if row else None,
            "row_id": row.get("id") if row else None,
            "raw_rows_purged": purged,
            "row_purged": purged and row is None,
        }
        if purged and row is None:
            entry["purged_message"] = PURGED_ROW_MESSAGE
        history.append(entry)

    return history


def list_folding_overrides_safe(
    cursor, organization_id: int, bag_id: str
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_folding_performance_overrides"):
        return []
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    cursor.execute(
        """
        SELECT id, organization_id, performance_id, bag_id, field_name,
               old_value, new_value, actor_user_id, notes, created_at
        FROM rinse_folding_performance_overrides
        WHERE organization_id = %s AND bag_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (int(organization_id), bid),
    )
    return list(cursor.fetchall() or [])


def list_scrape_sources_safe(
    cursor, organization_id: int, upload_history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scrape_sources: list[dict[str, Any]] = []
    seen: set[int] = set()
    org = int(organization_id)
    for uh in upload_history:
        batch_id = uh.get("upload_batch_id")
        if batch_id is None:
            continue
        try:
            bid_int = int(batch_id)
        except (TypeError, ValueError):
            continue
        if bid_int in seen:
            continue
        seen.add(bid_int)
        try:
            run = fetch_scrape_run_for_batch(cursor, org, bid_int)
        except Exception as exc:
            log.warning("scrape source batch %s: %s", bid_int, exc)
            continue
        if run:
            scrape_sources.append({"upload_batch_id": bid_int, **run})
    return scrape_sources


def empty_lifecycle_detail_shell(bag_id: str, registry: dict[str, Any] | None) -> dict[str, Any]:
    reg = registry or {}
    summary = {
        "bag_id": reg.get("bag_id") or bag_id,
        "customer": reg.get("name_clean"),
        "completion_status": reg.get("completion_status"),
        "completion_reason": reg.get("completion_reason"),
        "completed_at": reg.get("completed_at"),
        "date_clean": reg.get("date_clean"),
        "weight": reg.get("weight_num"),
        "service_type": reg.get("service_type"),
        "rush_type": reg.get("rush_type"),
        "last_upload_batch_id": reg.get("last_upload_batch_id"),
        "last_staging_order_id": reg.get("last_staging_order_id"),
    }
    return {
        "bag_id": normalize_bag_id(bag_id) or bag_id,
        "registry": reg,
        "registry_summary": summary,
        "upload_history": [],
        "staging_history": [],
        "staging": None,
        "staging_active": None,
        "scan_events": [],
        "folding": None,
        "folding_performance": None,
        "scrape_sources": [],
        "latest_upload_batch_row": None,
        "section_errors": {},
    }


def build_order_lifecycle_detail(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    active_where_sql: str,
    has_staging_org: bool,
    has_ticket_id_col: bool,
    upload_batch_row_pk: str,
) -> dict[str, Any] | None:
    from backend.rinse_bag_registry import get_registry_row

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    org = int(organization_id)
    reg = get_registry_row(cursor, org, bid)
    if not reg:
        return None

    section_errors: dict[str, str] = {}
    detail = empty_lifecycle_detail_shell(bid, reg)

    detail["scan_events"] = _safe_section(
        section_errors,
        "scan_events",
        lambda: list_scan_events_for_bag(cursor, org, bid),
        [],
    )
    detail["upload_history"] = _safe_section(
        section_errors,
        "upload_history",
        lambda: list_upload_history_for_bag(
            cursor, org, bid, reg, upload_batch_row_pk=upload_batch_row_pk
        ),
        [],
    )
    detail["staging_history"] = _safe_section(
        section_errors,
        "staging_history",
        lambda: list_staging_history_for_bag(
            cursor,
            org,
            bid,
            has_staging_org=has_staging_org,
            has_ticket_id_col=has_ticket_id_col,
        ),
        [],
    )
    detail["staging_active"] = _safe_section(
        section_errors,
        "staging_active",
        lambda: find_active_staging_by_ticket_id(
            cursor,
            org,
            bid,
            active_where_sql,
            has_staging_org=has_staging_org,
            has_ticket_id_col=has_ticket_id_col,
        ),
        None,
    )
    detail["staging"] = detail["staging_active"]

    folding_perf = None
    if table_exists(cursor, "rinse_folding_performance"):
        folding_perf = _safe_section(
            section_errors,
            "folding_performance",
            lambda: _fetch_folding_row(cursor, org, bid),
            None,
        )
    detail["folding_performance"] = folding_perf

    overrides = _safe_section(
        section_errors,
        "folding_overrides",
        lambda: list_folding_overrides_safe(cursor, org, bid),
        [],
    )
    folding_detail = None
    try:
        folding_detail = build_folding_detail(
            folding_perf if isinstance(folding_perf, dict) else None,
            detail["scan_events"] or [],
        )
        if folding_detail is not None:
            folding_detail["override_history"] = overrides
    except Exception as exc:
        section_errors["folding"] = str(exc)
        log.warning("folding detail build failed: %s", exc, exc_info=True)
    detail["folding"] = folding_detail

    detail["scrape_sources"] = _safe_section(
        section_errors,
        "scrape_sources",
        lambda: list_scrape_sources_safe(cursor, org, detail["upload_history"] or []),
        [],
    )

    if section_errors:
        detail["section_errors"] = section_errors

    return detail


def _fetch_folding_row(cursor, org: int, bid: str) -> dict[str, Any] | None:
    cursor.execute(
        "SELECT * FROM rinse_folding_performance WHERE organization_id = %s AND bag_id = %s LIMIT 1",
        (org, bid),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None
