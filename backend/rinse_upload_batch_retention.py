"""
Option C retention for Rinse upload/import artifacts.

Keep upload_batches headers and rinse_scrape_runs summaries; purge heavy child rows
(upload_batch_rows, upload_batch_scan_events) when safe.

Does NOT touch: orders_staging, rinse_bag_registry, rinse_bag_scan_events,
rinse_folding_performance, orders_final, checkout archive, payroll.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.ta_helpers import table_exists, table_has_column
from backend.upload_batch_cleanup import (
    delete_children_for_upload_batch,
    resolve_upload_batches_pk,
)

ET = ZoneInfo("America/New_York")
PURGEABLE_BATCH_STATES = frozenset({"CONFIRMED", "CLOSED"})


def default_retention_days() -> int:
    raw = os.getenv("RINSE_UPLOAD_BATCH_RETENTION_DAYS", "3")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def today_et() -> date:
    return datetime.now(ET).date()


def retention_cutoff_batch_date(today: date, older_than_days: int) -> date:
    """Purge batches with batch_date on or before this date (and not today)."""
    return today - timedelta(days=int(older_than_days))


def batch_date_eligible_for_retention(
    batch_date: date | None,
    *,
    today: date,
    cutoff: date,
) -> tuple[bool, str | None]:
    if batch_date is None:
        return False, "missing batch_date"
    if batch_date >= today:
        return False, "batch_date is today or in the future (America/New_York)"
    if batch_date > cutoff:
        return False, f"batch_date {batch_date.isoformat()} within retention window"
    return True, None


def ensure_upload_batch_retention_columns(cursor) -> None:
    if not table_exists(cursor, "upload_batches"):
        return
    if not table_has_column(cursor, "upload_batches", "raw_rows_purged_at"):
        cursor.execute(
            "ALTER TABLE upload_batches ADD COLUMN raw_rows_purged_at DATETIME NULL"
        )
    if not table_has_column(cursor, "upload_batches", "purged_summary_json"):
        cursor.execute(
            "ALTER TABLE upload_batches ADD COLUMN purged_summary_json TEXT NULL"
        )


def _parse_batch_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def get_latest_successful_imported_batch_id(cursor, organization_id: int) -> int | None:
    if not table_exists(cursor, "rinse_scrape_runs"):
        return None
    cursor.execute(
        """
        SELECT imported_batch_id
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'success' AND imported_batch_id IS NOT NULL
        ORDER BY finished_at DESC, started_at DESC
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    if not row:
        return None
    bid = row.get("imported_batch_id") if isinstance(row, dict) else row[0]
    return int(bid) if bid is not None else None


def _count_batch_rows(cursor, batch_id: int) -> dict[str, int]:
    if not table_exists(cursor, "upload_batch_rows"):
        return {
            "total_rows": 0,
            "accepted_rows": 0,
            "rejected_rows": 0,
            "attention_rows": 0,
            "deleted_rows": 0,
        }
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(row_status IN ('ACCEPTED', 'OVERRIDDEN')) AS accepted_rows,
            SUM(row_status = 'REJECTED_DUPLICATE') AS rejected_rows,
            SUM(row_status = 'NEEDS_ATTENTION') AS attention_rows,
            SUM(row_status = 'DELETED') AS deleted_rows
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone() or {}
    out = {}
    for key in (
        "total_rows",
        "accepted_rows",
        "rejected_rows",
        "attention_rows",
        "deleted_rows",
    ):
        out[key] = int((row.get(key) if isinstance(row, dict) else 0) or 0)
    return out


def _count_batch_scan_events(cursor, batch_id: int, organization_id: int) -> int:
    from backend.rinse_scan_events_upload import count_scan_events_for_batch

    return int(count_scan_events_for_batch(cursor, int(batch_id), organization_id))


def _fetch_candidate_batches(cursor, organization_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "upload_batches"):
        return []
    ensure_upload_batch_retention_columns(cursor)
    pk = resolve_upload_batches_pk(cursor)
    cols = [f"{pk} AS batch_id", "batch_date"]
    if table_has_column(cursor, "upload_batches", "state"):
        cols.append("state")
    else:
        cols.append("'DRAFT' AS state")
    if table_has_column(cursor, "upload_batches", "raw_rows_purged_at"):
        cols.append("raw_rows_purged_at")
    if table_has_column(cursor, "upload_batches", "purged_summary_json"):
        cols.append("purged_summary_json")
    if table_has_column(cursor, "upload_batches", "confirmed_at"):
        cols.append("confirmed_at")
    where = "organization_id = %s" if table_has_column(cursor, "upload_batches", "organization_id") else "1=1"
    args: list[Any] = [int(organization_id)] if where != "1=1" else []
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM upload_batches
        WHERE {where}
        ORDER BY batch_date DESC, {pk} DESC
        """,
        tuple(args),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def evaluate_batch_for_heavy_row_purge(
    batch: dict[str, Any],
    *,
    organization_id: int,
    today: date,
    cutoff: date,
    latest_success_batch_id: int | None,
) -> dict[str, Any]:
    """Return eligibility verdict for one batch (no DB writes)."""
    batch_id = int(batch["batch_id"])
    state = str(batch.get("state") or "DRAFT").upper()
    batch_date = _parse_batch_date(batch.get("batch_date"))
    already_purged = batch.get("raw_rows_purged_at") is not None

    reasons: list[str] = []
    eligible = True

    if already_purged:
        eligible = False
        reasons.append("heavy rows already purged (header retained)")

    if state == "DRAFT":
        eligible = False
        reasons.append("DRAFT batch — never purged (confirm/close first)")

    if state not in PURGEABLE_BATCH_STATES:
        if state != "DRAFT":
            eligible = False
            reasons.append(f"state {state} is not CONFIRMED/CLOSED")

    ok_date, date_reason = batch_date_eligible_for_retention(
        batch_date, today=today, cutoff=cutoff
    )
    if not ok_date:
        eligible = False
        if date_reason:
            reasons.append(date_reason)

    if latest_success_batch_id is not None and batch_id == int(latest_success_batch_id):
        eligible = False
        reasons.append("linked to latest successful scheduled sync")

    return {
        "batch_id": batch_id,
        "batch_date": batch_date.isoformat() if batch_date else None,
        "state": state,
        "already_purged": already_purged,
        "eligible": eligible,
        "skip_reasons": reasons,
    }


def plan_heavy_row_purge(
    cursor,
    organization_id: int,
    *,
    older_than_days: int | None = None,
) -> dict[str, Any]:
    """Dry-run plan: batches and row counts eligible for Option C purge."""
    org = int(organization_id)
    retention = int(older_than_days or default_retention_days())
    today = today_et()
    cutoff = retention_cutoff_batch_date(today, retention)
    latest_success = get_latest_successful_imported_batch_id(cursor, org)

    candidates = _fetch_candidate_batches(cursor, org)
    to_purge: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_rows = 0
    total_scan = 0

    for batch in candidates:
        verdict = evaluate_batch_for_heavy_row_purge(
            batch,
            organization_id=org,
            today=today,
            cutoff=cutoff,
            latest_success_batch_id=latest_success,
        )
        batch_id = verdict["batch_id"]
        row_counts = _count_batch_rows(cursor, batch_id)
        scan_count = _count_batch_scan_events(cursor, batch_id, org)

        attention = row_counts.get("attention_rows", 0)
        if attention > 0 and verdict["eligible"]:
            verdict["eligible"] = False
            verdict["skip_reasons"].append(
                f"{attention} upload_batch_rows with NEEDS_ATTENTION"
            )

        entry = {
            **verdict,
            "upload_batch_rows": row_counts["total_rows"],
            "accepted_rows": row_counts["accepted_rows"],
            "rejected_rows": row_counts["rejected_rows"],
            "attention_rows": row_counts["attention_rows"],
            "upload_batch_scan_events": scan_count,
        }

        if verdict["eligible"]:
            if row_counts["total_rows"] == 0 and scan_count == 0:
                entry["note"] = "no heavy rows remain — will mark purged if apply"
            to_purge.append(entry)
            total_rows += row_counts["total_rows"]
            total_scan += scan_count
        else:
            skipped.append(entry)
            if attention > 0 and state_needs_warning(batch):
                warnings.append(
                    f"Batch #{batch_id} has {attention} NEEDS_ATTENTION row(s) — not purgeable"
                )

    scrape_runs = _plan_scrape_run_retention(cursor, org, to_purge)

    return {
        "organization_id": org,
        "retention_days": retention,
        "today_et": today.isoformat(),
        "cutoff_batch_date": cutoff.isoformat(),
        "latest_success_batch_id": latest_success,
        "batches_to_purge": to_purge,
        "skipped_batches": skipped,
        "totals": {
            "batches": len(to_purge),
            "upload_batch_rows": total_rows,
            "upload_batch_scan_events": total_scan,
        },
        "scrape_runs": scrape_runs,
        "tables_touched_on_apply": [
            "upload_batch_rows",
            "upload_batch_scan_events",
            "upload_batches (raw_rows_purged_at, purged_summary_json only)",
            "rinse_scrape_runs (optional result_json trim)",
        ],
        "tables_never_touched": [
            "orders_staging",
            "rinse_bag_registry",
            "rinse_bag_scan_events",
            "rinse_folding_performance",
            "orders_final",
            "checkout_history_snapshots",
            "checkout_history_orders",
            "checkout_history_checkouts",
        ],
        "warnings": warnings,
    }


def state_needs_warning(batch: dict[str, Any]) -> bool:
    return str(batch.get("state") or "").upper() in ("DRAFT", "CONFIRMED", "CLOSED")


def _plan_scrape_run_retention(
    cursor, organization_id: int, batches_to_purge: list[dict[str, Any]]
) -> dict[str, Any]:
    """Runs linked to purged batches: keep row, optionally trim heavy JSON."""
    if not table_exists(cursor, "rinse_scrape_runs"):
        return {"retain": [], "trim_heavy_fields": []}

    purge_ids = {int(b["batch_id"]) for b in batches_to_purge}
    if not purge_ids:
        return {"retain": [], "trim_heavy_fields": []}

    placeholders = ", ".join(["%s"] * len(purge_ids))
    cursor.execute(
        f"""
        SELECT id, imported_batch_id, status, started_at, result_json IS NOT NULL AS has_result_json
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND imported_batch_id IN ({placeholders})
        ORDER BY started_at DESC
        """,
        (int(organization_id), *purge_ids),
    )
    retain = []
    trim = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        item = {
            "run_id": row.get("id"),
            "imported_batch_id": row.get("imported_batch_id"),
            "status": row.get("status"),
            "started_at": str(row.get("started_at") or ""),
        }
        retain.append(item)
        if row.get("has_result_json"):
            trim.append({**item, "action": "null result_json on apply (keep run summary row)"})
    return {"retain": retain, "trim_heavy_fields": trim}


def apply_heavy_row_purge(
    cursor,
    organization_id: int,
    plan: dict[str, Any],
    *,
    trim_scrape_result_json: bool = True,
) -> dict[str, Any]:
    """Execute Option C purge from a plan produced by plan_heavy_row_purge."""
    ensure_upload_batch_retention_columns(cursor)
    pk = resolve_upload_batches_pk(cursor)
    org = int(organization_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    applied = {
        "batches_marked": 0,
        "upload_batch_rows_deleted": 0,
        "upload_batch_scan_events_deleted": 0,
        "scrape_runs_trimmed": 0,
    }

    for batch in plan.get("batches_to_purge") or []:
        batch_id = int(batch["batch_id"])
        row_counts = _count_batch_rows(cursor, batch_id)
        scan_count = _count_batch_scan_events(cursor, batch_id, org)
        summary = {
            **row_counts,
            "upload_batch_scan_events": scan_count,
            "purged_at_utc": now.isoformat() + "Z",
        }
        deleted = delete_children_for_upload_batch(
            cursor, batch_id, organization_id=org
        )
        applied["upload_batch_rows_deleted"] += deleted.get("upload_batch_rows", 0)
        applied["upload_batch_scan_events_deleted"] += deleted.get(
            "upload_batch_scan_events", 0
        )

        set_parts = [
            "raw_rows_purged_at = %s",
            "purged_summary_json = %s",
        ]
        args: list[Any] = [now, json.dumps(summary)]
        if table_has_column(cursor, "upload_batches", "updated_at"):
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
        where_org = ""
        if table_has_column(cursor, "upload_batches", "organization_id"):
            where_org = " AND organization_id = %s"
            args.extend([int(batch_id), org])
        else:
            args.append(int(batch_id))
        cursor.execute(
            f"""
            UPDATE upload_batches
            SET {", ".join(set_parts)}
            WHERE {pk} = %s{where_org}
            """,
            tuple(args),
        )
        applied["batches_marked"] += 1

    if trim_scrape_result_json and table_exists(cursor, "rinse_scrape_runs"):
        for item in (plan.get("scrape_runs") or {}).get("trim_heavy_fields") or []:
            rid = item.get("run_id")
            if rid is None:
                continue
            cursor.execute(
                """
                UPDATE rinse_scrape_runs SET result_json = NULL
                WHERE id = %s AND organization_id = %s
                """,
                (int(rid), org),
            )
            applied["scrape_runs_trimmed"] += int(cursor.rowcount or 0)

    return applied


def resolve_upload_batch_date_range(
    *,
    range_preset: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[date, date]:
    """America/New_York calendar range for upload batch list filters."""
    today = today_et()
    preset = (range_preset or "last_3_days").strip().lower().replace("-", "_")

    if preset == "today":
        return today, today
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset == "last_3_days":
        return today - timedelta(days=2), today
    if preset == "last_7_days":
        return today - timedelta(days=6), today
    if preset == "custom":
        if from_date is None or to_date is None:
            raise ValueError("from_date and to_date required for custom range")
        return from_date, to_date
    return today - timedelta(days=2), today


def et_date_range_to_utc_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Inclusive ET calendar dates → UTC naive bounds for started_at filtering."""
    start_et = datetime.combine(from_date, datetime.min.time(), tzinfo=ET)
    end_et = datetime.combine(to_date, datetime.max.time().replace(microsecond=0), tzinfo=ET)
    start_utc = start_et.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_et.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
