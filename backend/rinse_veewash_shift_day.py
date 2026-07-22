"""Persist VeeWash Step-1 daily Shift Monitor snapshots + close/reopen."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    VEEWASH_ORG_ID,
    build_step1_headline_summary,
    build_veewash_daily_workload,
    get_step1_activation_date,
    today_et,
)
from backend.ta_helpers import table_exists

STATUS_OPEN = "OPEN"
STATUS_READY_TO_CLOSE = "READY_TO_CLOSE"
STATUS_CLOSED = "CLOSED"
STATUS_REOPENED = "REOPENED"

DISPOSITION_CARRY_FORWARD = "CARRY_FORWARD"
DISPOSITION_COMPLETED = "COMPLETED"
DISPOSITION_EXCLUDE = "EXCLUDE"
DISPOSITION_HISTORICAL_REVIEW_ONLY = "HISTORICAL_REVIEW_ONLY"

_SHIFT_MONITOR_TABLES_READY = False


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace("Z", "")
    try:
        return datetime.fromisoformat(s[:19])
    except Exception:
        return None


def _commit(cursor) -> None:
    conn = (
        getattr(cursor, "connection", None)
        or getattr(cursor, "_connection", None)
        or getattr(getattr(cursor, "_cnx", None), "commit", None) and getattr(cursor, "_cnx", None)
    )
    if conn is None or not hasattr(conn, "commit"):
        return
    try:
        conn.commit()
    except Exception:
        pass


def ensure_shift_monitor_day_tables(cursor) -> None:
    global _SHIFT_MONITOR_TABLES_READY
    if _SHIFT_MONITOR_TABLES_READY:
        return
    # Always run CREATE IF NOT EXISTS for each table (partial deploys / missing siblings).
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_shift_monitor_days (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
          opened_at DATETIME NULL,
          last_sync_at DATETIME NULL,
          closed_at DATETIME NULL,
          closed_by_user_id INT NULL,
          closed_by_display_name VARCHAR(255) NULL,
          close_reason TEXT NULL,
          close_override TINYINT(1) NOT NULL DEFAULT 0,
          reopen_count INT NOT NULL DEFAULT 0,
          review_required_count INT NOT NULL DEFAULT 0,
          headline_json LONGTEXT NULL,
          workload_meta_json LONGTEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_shift_monitor_day (organization_id, shift_date_et),
          KEY idx_shift_monitor_day_status (organization_id, status, shift_date_et)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_shift_monitor_day_bags (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          service_type VARCHAR(16) NULL,
          rush_status VARCHAR(32) NULL,
          new_or_carryover VARCHAR(32) NULL,
          workload_entry_type VARCHAR(64) NULL,
          workload_entry_timestamp DATETIME NULL,
          pre_weight_lbs DECIMAL(10,4) NULL,
          post_weight_lbs DECIMAL(10,4) NULL,
          weight_lbs DECIMAL(10,4) NULL,
          canonical_completion_status VARCHAR(64) NULL,
          canonical_completion_timestamp DATETIME NULL,
          canonical_completion_employee VARCHAR(255) NULL,
          effective_status VARCHAR(64) NULL,
          review_reason_codes_json TEXT NULL,
          portal_status_at_sync VARCHAR(64) NULL,
          last_present_scrape DATETIME NULL,
          first_confirmed_absent_scrape DATETIME NULL,
          disposition VARCHAR(64) NULL,
          bag_snapshot_json LONGTEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_shift_monitor_day_bag (organization_id, shift_date_et, bag_id),
          KEY idx_shift_monitor_day_bag_status (organization_id, shift_date_et, effective_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_shift_monitor_close_audit (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          action VARCHAR(64) NOT NULL,
          actor_user_id INT NULL,
          actor_display_name VARCHAR(255) NULL,
          reason TEXT NULL,
          previous_status VARCHAR(32) NULL,
          new_status VARCHAR(32) NULL,
          checklist_json LONGTEXT NULL,
          totals_json LONGTEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          KEY idx_shift_close_audit_day (organization_id, shift_date_et, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _SHIFT_MONITOR_TABLES_READY = True


def get_day_record(cursor, organization_id: int, shift_date_et: date) -> dict[str, Any] | None:
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_shift_monitor_days
        WHERE organization_id = %s AND shift_date_et = %s
        LIMIT 1
        """,
        (int(organization_id), shift_date_et),
    )
    row = cursor.fetchone()
    if not row:
        return None
    out = dict(row)
    out["headline"] = _json_load(out.pop("headline_json", None))
    out["workload_meta"] = _json_load(out.pop("workload_meta_json", None))
    return out


def _effective_status_for_row(row: Mapping[str, Any], review_ids: set[str]) -> str:
    bid = normalize_bag_id(row.get("bag_id"))
    if bid in review_ids or row.get("outcome") == OUTCOME_REVIEW_REQUIRED:
        return OUTCOME_REVIEW_REQUIRED
    outcome = str(row.get("outcome") or row.get("final_bucket") or "")
    if OUTCOME_COMPLETED in outcome or outcome.endswith("_completed"):
        return OUTCOME_COMPLETED
    if "pending" in outcome or outcome == OUTCOME_PENDING:
        return OUTCOME_PENDING
    if row.get("final_bucket") == "completed_without_recognized_entry":
        return OUTCOME_REVIEW_REQUIRED
    return outcome or OUTCOME_PENDING


def _bag_rows_from_workload(wl: Mapping[str, Any], summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    review_ids = set(wl.get("review_required") or summary.get("segments", {}).get("all", {}).get("bag_ids", {}).get("review_required") or [])
    reasons = wl.get("review_reasons_by_bag") or summary.get("review_reasons_by_bag") or {}
    rows_out: list[dict[str, Any]] = []
    for row in wl.get("rows") or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        entry_class = row.get("entry_class")
        eff = _effective_status_for_row(row, review_ids)
        # Only persist bags that are part of the day's operational set.
        if entry_class not in ("new_today", "carryover") and bid not in review_ids:
            # Still keep CWO / review bags that were force-included.
            if eff != OUTCOME_REVIEW_REQUIRED and row.get("final_bucket") != "review_required":
                continue
        rows_out.append(
            {
                "bag_id": bid,
                "service_type": row.get("service_type"),
                "rush_status": row.get("rush_flag"),
                "new_or_carryover": entry_class,
                "workload_entry_type": row.get("entry_source"),
                "workload_entry_timestamp": row.get("first_entry_at") or row.get("original_entry_date"),
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "post_weight_lbs": row.get("post_weight_lbs"),
                "weight_lbs": row.get("weight_lbs"),
                "canonical_completion_status": row.get("canonical_status") or row.get("outcome"),
                "canonical_completion_timestamp": row.get("completion_at"),
                "canonical_completion_employee": row.get("completed_by"),
                "effective_status": eff,
                "review_reason_codes": list(reasons.get(bid) or row.get("reason_codes") or []),
                "portal_status_at_sync": row.get("portal_status"),
                "last_present_scrape": row.get("last_seen_date") or row.get("last_seen_at"),
                "first_confirmed_absent_scrape": row.get("disappeared_date"),
                "disposition": row.get("disposition"),
                "bag_snapshot": dict(row),
            }
        )
    return rows_out


def persist_day_snapshot(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    workload: Mapping[str, Any],
    summary: Mapping[str, Any],
    status: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Upsert day header + bag rows. No-op for CLOSED days unless force=True."""
    ensure_shift_monitor_day_tables(cursor)
    existing = get_day_record(cursor, organization_id, shift_date_et)
    if existing and existing.get("status") == STATUS_CLOSED and not force:
        return existing

    review_n = int((summary.get("exceptions") or {}).get("review_required") or 0)
    now = datetime.utcnow()
    next_status = status or (
        STATUS_READY_TO_CLOSE
        if review_n == 0
        else (existing or {}).get("status") or STATUS_OPEN
    )
    if existing and existing.get("status") == STATUS_REOPENED and status is None:
        next_status = STATUS_REOPENED if review_n > 0 else STATUS_READY_TO_CLOSE

    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_days (
          organization_id, shift_date_et, status, opened_at, last_sync_at,
          review_required_count, headline_json, workload_meta_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          status = VALUES(status),
          last_sync_at = VALUES(last_sync_at),
          review_required_count = VALUES(review_required_count),
          headline_json = VALUES(headline_json),
          workload_meta_json = VALUES(workload_meta_json),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(organization_id),
            shift_date_et,
            next_status,
            (existing or {}).get("opened_at") or now,
            now,
            review_n,
            _json_dump(summary),
            _json_dump(
                {
                    "selected_date_et": shift_date_et.isoformat(),
                    "counts": workload.get("counts"),
                    "review_reasons_by_bag": workload.get("review_reasons_by_bag")
                    or summary.get("review_reasons_by_bag"),
                    "review_by_reason": summary.get("review_by_reason"),
                }
            ),
        ),
    )

    bags = _bag_rows_from_workload(workload, summary)
    for b in bags:
        cursor.execute(
            """
            INSERT INTO rinse_shift_monitor_day_bags (
              organization_id, shift_date_et, bag_id, service_type, rush_status,
              new_or_carryover, workload_entry_type, workload_entry_timestamp,
              pre_weight_lbs, post_weight_lbs, weight_lbs,
              canonical_completion_status, canonical_completion_timestamp,
              canonical_completion_employee, effective_status,
              review_reason_codes_json, portal_status_at_sync,
              last_present_scrape, first_confirmed_absent_scrape, disposition,
              bag_snapshot_json
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON DUPLICATE KEY UPDATE
              service_type=VALUES(service_type),
              rush_status=VALUES(rush_status),
              new_or_carryover=VALUES(new_or_carryover),
              workload_entry_type=VALUES(workload_entry_type),
              workload_entry_timestamp=VALUES(workload_entry_timestamp),
              pre_weight_lbs=VALUES(pre_weight_lbs),
              post_weight_lbs=VALUES(post_weight_lbs),
              weight_lbs=VALUES(weight_lbs),
              canonical_completion_status=VALUES(canonical_completion_status),
              canonical_completion_timestamp=VALUES(canonical_completion_timestamp),
              canonical_completion_employee=VALUES(canonical_completion_employee),
              effective_status=VALUES(effective_status),
              review_reason_codes_json=VALUES(review_reason_codes_json),
              portal_status_at_sync=VALUES(portal_status_at_sync),
              last_present_scrape=VALUES(last_present_scrape),
              first_confirmed_absent_scrape=VALUES(first_confirmed_absent_scrape),
              disposition=COALESCE(VALUES(disposition), disposition),
              bag_snapshot_json=VALUES(bag_snapshot_json),
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(organization_id),
                shift_date_et,
                b["bag_id"],
                b.get("service_type"),
                b.get("rush_status"),
                b.get("new_or_carryover"),
                b.get("workload_entry_type"),
                _dt(b.get("workload_entry_timestamp")),
                b.get("pre_weight_lbs"),
                b.get("post_weight_lbs"),
                b.get("weight_lbs"),
                b.get("canonical_completion_status"),
                _dt(b.get("canonical_completion_timestamp")),
                b.get("canonical_completion_employee"),
                b.get("effective_status"),
                _json_dump(b.get("review_reason_codes")),
                b.get("portal_status_at_sync"),
                _dt(b.get("last_present_scrape")),
                _dt(b.get("first_confirmed_absent_scrape")),
                b.get("disposition"),
                _json_dump(b.get("bag_snapshot")),
            ),
        )
    return get_day_record(cursor, organization_id, shift_date_et) or {}


def _hydrate_day_bag_row(row: Mapping[str, Any]) -> dict[str, Any]:
    d = dict(row)
    d["review_reason_codes"] = _json_load(d.pop("review_reason_codes_json", None)) or []
    d["bag_snapshot"] = _json_load(d.pop("bag_snapshot_json", None)) or {}
    return d


def load_day_bags(cursor, organization_id: int, shift_date_et: date) -> list[dict[str, Any]]:
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
        ORDER BY bag_id
        """,
        (int(organization_id), shift_date_et),
    )
    return [_hydrate_day_bag_row(row) for row in (cursor.fetchall() or [])]


def load_day_bags_by_ids(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_ids: list[str],
) -> list[dict[str, Any]]:
    """Load only the requested day-bag rows (drawer page / single-bag detail)."""
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return []
    ensure_shift_monitor_day_tables(cursor)
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT *
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND bag_id IN ({placeholders})
        ORDER BY bag_id
        """,
        (int(organization_id), shift_date_et, *ids),
    )
    by_id = {
        normalize_bag_id(row.get("bag_id")): _hydrate_day_bag_row(row)
        for row in (cursor.fetchall() or [])
    }
    return [by_id[b] for b in ids if b in by_id]


def day_bag_count(cursor, organization_id: int, shift_date_et: date) -> int:
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT COUNT(*) AS n
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (int(organization_id), shift_date_et),
    )
    row = cursor.fetchone() or {}
    return int(row.get("n") or 0)


def summary_from_day_record(day: Mapping[str, Any]) -> dict[str, Any] | None:
    headline = day.get("headline")
    if isinstance(headline, dict) and headline:
        out = dict(headline)
        out["shift_day_status"] = day.get("status")
        out["shift_day"] = {
            "status": day.get("status"),
            "opened_at": day.get("opened_at"),
            "last_sync_at": day.get("last_sync_at"),
            "closed_at": day.get("closed_at"),
            "closed_by_display_name": day.get("closed_by_display_name"),
            "close_reason": day.get("close_reason"),
            "close_override": bool(day.get("close_override")),
            "reopen_count": day.get("reopen_count") or 0,
            "review_required_count": day.get("review_required_count") or 0,
            "read_only": day.get("status") == STATUS_CLOSED,
        }
        return out
    return None


def _workload_shell_from_bags(
    bags: list[dict[str, Any]],
    *,
    selected_date_et: date,
    status: str,
) -> dict[str, Any]:
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "rows": [b.get("bag_snapshot") or {"bag_id": b["bag_id"], **b} for b in bags],
        "review_required": [
            b["bag_id"]
            for b in bags
            if b.get("effective_status") == OUTCOME_REVIEW_REQUIRED
        ],
        "review_reasons_by_bag": {
            b["bag_id"]: b.get("review_reason_codes") or []
            for b in bags
            if b.get("review_reason_codes")
        },
        "from_snapshot": True,
        "shift_day_status": status,
    }


def build_or_load_step1_for_date(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    persist_live: bool = True,
    include_bag_rows: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Return (workload, summary, day_meta).

    CLOSED days always load frozen headline.
    Prior OPEN/READY_TO_CLOSE days load the persisted snapshot (never live portal rebuild).
    Today and REOPENED days rebuild live and persist.
    Missing prior-day snapshot: one-time reconstruct from source + persist.

    When ``include_bag_rows`` is False (dashboard cards), return headline/summary only and
    skip loading every day-bag snapshot into memory.
    """
    ensure_shift_monitor_day_tables(cursor)
    activation = get_step1_activation_date(cursor, organization_id) or selected_date_et
    day = get_day_record(cursor, organization_id, selected_date_et)
    today = today_et()
    status = (day or {}).get("status")

    def _summary_shell(day_rec: Mapping[str, Any], *, status_value: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        summary = summary_from_day_record(day_rec)
        if not summary:
            return {}, {}, dict(day_rec)
        if not include_bag_rows:
            return (
                {
                    "selected_date_et": selected_date_et.isoformat(),
                    "rows": [],
                    "from_snapshot": True,
                    "shift_day_status": status_value,
                    "review_required": [],
                    "review_reasons_by_bag": {},
                    "bag_rows_omitted": True,
                },
                summary,
                dict(day_rec),
            )
        bags = load_day_bags(cursor, organization_id, selected_date_et)
        return (
            _workload_shell_from_bags(bags, selected_date_et=selected_date_et, status=status_value),
            summary,
            dict(day_rec),
        )

    if day and status == STATUS_CLOSED:
        wl, summary, day_out = _summary_shell(day, status_value=STATUS_CLOSED)
        if summary:
            return wl, summary, day_out

    # Snapshot-first read path (dashboard cards + drawers): serve persisted headline
    # for today and prior days when bags/headline exist. Live rebuild is reserved for
    # persist_live=True (scrape / backfill / explicit refresh).
    if (
        day
        and status in (STATUS_OPEN, STATUS_READY_TO_CLOSE, STATUS_REOPENED)
        and day.get("headline")
        and not persist_live
    ):
        has_bags = (not include_bag_rows) or day_bag_count(cursor, organization_id, selected_date_et) > 0
        if has_bags or not include_bag_rows:
            wl, summary, day_out = _summary_shell(day, status_value=str(status))
            if summary:
                return wl, summary, day_out

    # Historical OPEN/READY/REOPENED snapshots stay stable after first persist (midnight-safe).
    # REOPENED prior days keep the frozen bag set until an explicit backfill/correction rebuild.
    if (
        day
        and selected_date_et < today
        and status in (STATUS_OPEN, STATUS_READY_TO_CLOSE, STATUS_REOPENED)
        and day.get("headline")
    ):
        has_bags = (not include_bag_rows) or day_bag_count(cursor, organization_id, selected_date_et) > 0
        if has_bags:
            wl, summary, day_out = _summary_shell(day, status_value=str(status))
            if summary:
                return wl, summary, day_out

    # Live / reconstruct path (today, or missing prior-day snapshot).
    wl = build_veewash_daily_workload(
        cursor, organization_id, selected_date_et=selected_date_et
    )
    summary = build_step1_headline_summary(
        wl, selected_date_et=selected_date_et, activation_date=activation
    )

    review_n = int((summary.get("exceptions") or {}).get("review_required") or 0)
    next_status = status or STATUS_OPEN
    if next_status in (STATUS_OPEN, STATUS_REOPENED, STATUS_READY_TO_CLOSE, None):
        next_status = STATUS_READY_TO_CLOSE if review_n == 0 else STATUS_OPEN
        if status == STATUS_REOPENED and review_n > 0:
            next_status = STATUS_REOPENED

    # Never silently rewrite a prior-day snapshot from a partial live rebuild.
    should_persist = persist_live and (
        selected_date_et == today
        or day is None
        or (
            selected_date_et < today
            and status in (STATUS_OPEN, STATUS_READY_TO_CLOSE, STATUS_REOPENED)
            and day_bag_count(cursor, organization_id, selected_date_et) == 0
        )
    )
    if should_persist and (not day or status != STATUS_CLOSED):
        day = persist_day_snapshot(
            cursor,
            organization_id,
            selected_date_et,
            workload=wl,
            summary=summary,
            status=next_status,
        )
        _commit(cursor)

    if day:
        summary = summary_from_day_record(day) or summary
    else:
        summary["shift_day"] = {
            "status": next_status,
            "read_only": False,
            "review_required_count": review_n,
        }
        summary["shift_day_status"] = next_status
    return wl, summary, day or {"status": next_status, "shift_date_et": selected_date_et}


def validate_close(
    summary: Mapping[str, Any],
    *,
    allow_unresolved_reviews: bool = False,
) -> dict[str, Any]:
    segs = summary.get("segments") or {}
    all_seg = segs.get("all") or {}
    review_n = int((all_seg.get("exceptions") or summary.get("exceptions") or {}).get("review_required") or 0)
    completed = int(all_seg.get("completed") or summary.get("completed") or 0)
    pending = int(all_seg.get("pending") or summary.get("pending") or 0)
    active = int(all_seg.get("active_workload") or summary.get("active_workload") or 0)
    arithmetic_ok = active == completed + pending + review_n

    wf = segs.get("wf") or {}
    hd = segs.get("hd") or {}
    service_ok = (
        int(wf.get("new_today") or 0) + int(hd.get("new_today") or 0)
        == int(all_seg.get("new_today") or summary.get("new_today") or 0)
    )
    checklist = {
        "workload_reconciled": arithmetic_ok,
        "completed_reviewed": True,
        "pending_confirmed": True,
        "review_required_cleared": review_n == 0,
        "wf_zero_weight_resolved": True,
        "completed_without_entry_resolved": True,
        "disappeared_reviewed": True,
        "bulk_workitems_reviewed": True,
        "carryover_confirmed": True,
        "service_totals_ok": service_ok,
        "arithmetic_ok": arithmetic_ok,
    }
    # Explicit bulk unresolved count (also covered by review_required_cleared).
    review_by_reason = summary.get("review_by_reason") or {}
    bulk_ids = review_by_reason.get("WF_BULK_WORKITEM_REVIEW") or []
    bulk_n = len(bulk_ids)
    checklist["bulk_workitems_reviewed"] = bulk_n == 0
    blocking = []
    if review_n > 0 and not allow_unresolved_reviews:
        blocking.append("unresolved_review_required")
    if bulk_n > 0 and not allow_unresolved_reviews:
        blocking.append("unresolved_bulk_workitem_review")
        checklist["bulk_workitems_reviewed"] = False
    if not arithmetic_ok:
        blocking.append("headline_arithmetic_mismatch")
    return {
        "ok": not blocking,
        "blocking": blocking,
        "checklist": checklist,
        "review_required_count": review_n,
        "bulk_workitem_review_count": bulk_n,
        "totals": {
            "active": active,
            "completed": completed,
            "pending": pending,
            "review_required": review_n,
            "wf": {
                "new_today": wf.get("new_today"),
                "carryover": wf.get("carryover"),
                "completed": wf.get("completed"),
                "pending": wf.get("pending"),
                "review_required": (wf.get("exceptions") or {}).get("review_required"),
            },
            "hd": {
                "new_today": hd.get("new_today"),
                "carryover": hd.get("carryover"),
                "completed": hd.get("completed"),
                "pending": hd.get("pending"),
                "review_required": (hd.get("exceptions") or {}).get("review_required"),
            },
        },
    }


def _write_audit(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    action: str,
    actor_user_id: int | None,
    actor_display_name: str | None,
    reason: str | None,
    previous_status: str | None,
    new_status: str | None,
    checklist: Mapping[str, Any] | None = None,
    totals: Mapping[str, Any] | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_close_audit (
          organization_id, shift_date_et, action, actor_user_id, actor_display_name,
          reason, previous_status, new_status, checklist_json, totals_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            shift_date_et,
            action,
            actor_user_id,
            actor_display_name,
            reason,
            previous_status,
            new_status,
            _json_dump(checklist),
            _json_dump(totals),
        ),
    )


def close_shift_day(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    actor_user_id: int | None,
    actor_display_name: str | None,
    reason: str | None = None,
    allow_unresolved_reviews: bool = False,
    checklist: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # Prefer already-persisted prior-day snapshot; do not live-rebuild on close.
    wl, summary, day = build_or_load_step1_for_date(
        cursor,
        organization_id,
        shift_date_et,
        persist_live=(shift_date_et == today_et()),
    )
    if (day or {}).get("status") == STATUS_CLOSED:
        return {"ok": False, "error": "already_closed", "day": day}

    validation = validate_close(summary, allow_unresolved_reviews=allow_unresolved_reviews)
    if not validation["ok"]:
        return {"ok": False, "error": "validation_failed", "validation": validation}

    if allow_unresolved_reviews and validation["review_required_count"] > 0 and not (reason or "").strip():
        return {"ok": False, "error": "override_reason_required", "validation": validation}

    # Final freeze persist
    day = persist_day_snapshot(
        cursor,
        organization_id,
        shift_date_et,
        workload=wl,
        summary=summary,
        status=STATUS_CLOSED,
        force=True,
    )
    now = datetime.utcnow()
    prev = (day or {}).get("status")
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET status=%s, closed_at=%s, closed_by_user_id=%s, closed_by_display_name=%s,
            close_reason=%s, close_override=%s, review_required_count=%s,
            headline_json=%s, updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (
            STATUS_CLOSED,
            now,
            actor_user_id,
            actor_display_name,
            reason,
            1 if allow_unresolved_reviews and validation["review_required_count"] > 0 else 0,
            validation["review_required_count"],
            _json_dump(summary),
            int(organization_id),
            shift_date_et,
        ),
    )
    _write_audit(
        cursor,
        organization_id,
        shift_date_et,
        action="CLOSE_OVERRIDE" if allow_unresolved_reviews and validation["review_required_count"] > 0 else "CLOSE",
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        reason=reason,
        previous_status=prev,
        new_status=STATUS_CLOSED,
        checklist=checklist or validation["checklist"],
        totals=validation["totals"],
    )

    # Seed next-day carryover bag stubs from pending + explicit carry-forward dispositions.
    _seed_next_day_carryover(cursor, organization_id, shift_date_et)

    _commit(cursor)
    return {
        "ok": True,
        "day": get_day_record(cursor, organization_id, shift_date_et),
        "validation": validation,
    }


def reopen_shift_day(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    actor_user_id: int | None,
    actor_display_name: str | None,
    reason: str,
) -> dict[str, Any]:
    if not (reason or "").strip():
        return {"ok": False, "error": "reopen_reason_required"}
    day = get_day_record(cursor, organization_id, shift_date_et)
    if not day:
        return {"ok": False, "error": "day_not_found"}
    if day.get("status") != STATUS_CLOSED:
        return {"ok": False, "error": "not_closed", "day": day}
    prev = day.get("status")
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET status=%s, reopen_count=reopen_count+1, close_override=0,
            updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (STATUS_REOPENED, int(organization_id), shift_date_et),
    )
    _write_audit(
        cursor,
        organization_id,
        shift_date_et,
        action="REOPEN",
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        reason=reason,
        previous_status=prev,
        new_status=STATUS_REOPENED,
    )
    _commit(cursor)
    return {"ok": True, "day": get_day_record(cursor, organization_id, shift_date_et)}


def _seed_next_day_carryover(
    cursor, organization_id: int, closed_date: date
) -> None:
    from datetime import timedelta

    next_day = closed_date + timedelta(days=1)
    bags = load_day_bags(cursor, organization_id, closed_date)
    carry_ids = []
    for b in bags:
        disp = (b.get("disposition") or "").upper()
        eff = b.get("effective_status")
        if disp == DISPOSITION_CARRY_FORWARD:
            carry_ids.append(b)
            continue
        if disp in (DISPOSITION_COMPLETED, DISPOSITION_EXCLUDE, DISPOSITION_HISTORICAL_REVIEW_ONLY):
            continue
        if eff == OUTCOME_PENDING:
            carry_ids.append(b)

    if not carry_ids:
        return
    # Ensure next day header exists as OPEN without wiping if already present.
    existing = get_day_record(cursor, organization_id, next_day)
    if not existing:
        cursor.execute(
            """
            INSERT INTO rinse_shift_monitor_days (
              organization_id, shift_date_et, status, opened_at, last_sync_at,
              review_required_count
            ) VALUES (%s,%s,%s,%s,%s,0)
            """,
            (int(organization_id), next_day, STATUS_OPEN, datetime.utcnow(), datetime.utcnow()),
        )
    for b in carry_ids:
        snap = dict(b.get("bag_snapshot") or {})
        snap["entry_class"] = "carryover"
        snap["carried_from_date"] = closed_date.isoformat()
        cursor.execute(
            """
            INSERT INTO rinse_shift_monitor_day_bags (
              organization_id, shift_date_et, bag_id, service_type, rush_status,
              new_or_carryover, workload_entry_type, workload_entry_timestamp,
              pre_weight_lbs, post_weight_lbs, weight_lbs,
              canonical_completion_status, canonical_completion_timestamp,
              canonical_completion_employee, effective_status,
              review_reason_codes_json, portal_status_at_sync,
              last_present_scrape, first_confirmed_absent_scrape, disposition,
              bag_snapshot_json
            ) VALUES (
              %s,%s,%s,%s,%s,'carryover',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s
            )
            ON DUPLICATE KEY UPDATE
              new_or_carryover='carryover',
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(organization_id),
                next_day,
                b["bag_id"],
                b.get("service_type"),
                b.get("rush_status"),
                b.get("workload_entry_type"),
                b.get("workload_entry_timestamp"),
                b.get("pre_weight_lbs"),
                b.get("post_weight_lbs"),
                b.get("weight_lbs"),
                b.get("canonical_completion_status"),
                b.get("canonical_completion_timestamp"),
                b.get("canonical_completion_employee"),
                OUTCOME_PENDING,
                _json_dump(b.get("review_reason_codes")),
                b.get("portal_status_at_sync"),
                b.get("last_present_scrape"),
                b.get("first_confirmed_absent_scrape"),
                _json_dump(snap),
            ),
        )


def list_close_audit(
    cursor, organization_id: int, shift_date_et: date
) -> list[dict[str, Any]]:
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_shift_monitor_close_audit
        WHERE organization_id=%s AND shift_date_et=%s
        ORDER BY created_at ASC, id ASC
        """,
        (int(organization_id), shift_date_et),
    )
    out = []
    for row in cursor.fetchall() or []:
        d = dict(row)
        d["checklist"] = _json_load(d.pop("checklist_json", None))
        d["totals"] = _json_load(d.pop("totals_json", None))
        out.append(d)
    return out


def backfill_day_from_live(
    cursor, organization_id: int, shift_date_et: date, *, force: bool = False
) -> dict[str, Any]:
    """Rebuild and persist a day from source (activation onward)."""
    activation = get_step1_activation_date(cursor, organization_id)
    if activation and shift_date_et < activation:
        return {"ok": False, "error": "before_activation"}
    day = get_day_record(cursor, organization_id, shift_date_et)
    if day and day.get("status") == STATUS_CLOSED and not force:
        return {"ok": False, "error": "day_closed", "day": day}
    if day and day.get("status") == STATUS_CLOSED and force:
        reopen_shift_day(
            cursor,
            organization_id,
            shift_date_et,
            actor_user_id=None,
            actor_display_name="system_backfill",
            reason="force backfill of closed day",
        )
    # Explicit source rebuild + persist even for prior dates.
    wl = build_veewash_daily_workload(
        cursor, organization_id, selected_date_et=shift_date_et
    )
    summary = build_step1_headline_summary(
        wl,
        selected_date_et=shift_date_et,
        activation_date=activation or shift_date_et,
    )
    review_n = int((summary.get("exceptions") or {}).get("review_required") or 0)
    day = persist_day_snapshot(
        cursor,
        organization_id,
        shift_date_et,
        workload=wl,
        summary=summary,
        status=STATUS_READY_TO_CLOSE if review_n == 0 else STATUS_OPEN,
        force=True,
    )
    _commit(cursor)
    return {
        "ok": True,
        "day": day,
        "summary_totals": {
            "active": summary.get("active_workload"),
            "completed": summary.get("completed"),
            "pending": summary.get("pending"),
            "review_required": (summary.get("exceptions") or {}).get("review_required"),
        },
        "bag_count": len(load_day_bags(cursor, organization_id, shift_date_et)),
    }
