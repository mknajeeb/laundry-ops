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
    STEP1_AUTHORITATIVE_START_ET,
    VEEWASH_ORG_ID,
    build_step1_headline_summary,
    build_veewash_daily_workload,
    build_veewash_daily_workload_from_membership,
    get_step1_activation_date,
    today_et,
)
from backend.ta_helpers import table_exists

STATUS_NOT_STARTED = "NOT_STARTED"
STATUS_OPEN = "OPEN"
STATUS_READY_TO_CLOSE = "READY_TO_CLOSE"
STATUS_CLOSED = "CLOSED"
STATUS_REOPENED = "REOPENED"

DISPOSITION_CARRY_FORWARD = "CARRY_FORWARD"
DISPOSITION_COMPLETED = "COMPLETED"
DISPOSITION_EXCLUDE = "EXCLUDE"
DISPOSITION_HISTORICAL_REVIEW_ONLY = "HISTORICAL_REVIEW_ONLY"

_SHIFT_MONITOR_TABLES_READY = False

_HISTORY_UNAVAILABLE_MSG = (
    "Step-1 history before the authoritative start date is unavailable. "
    f"VeeWash Step-1 starts {STEP1_AUTHORITATIVE_START_ET.isoformat()} ET."
)


def _step1_cutover_date(organization_id: int, activation: date | None) -> date | None:
    """Earliest ET date Step-1 may serve for this org."""
    org = int(organization_id)
    if org == VEEWASH_ORG_ID:
        floor = STEP1_AUTHORITATIVE_START_ET
        if activation and activation > floor:
            return activation
        return floor
    return activation


def _unavailable_step1_payload(
    selected_date_et: date,
    *,
    message: str = _HISTORY_UNAVAILABLE_MSG,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    wl = {
        "selected_date_et": selected_date_et.isoformat(),
        "rows": [],
        "new_today": [],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": [],
        "review_required": [],
        "review_reasons_by_bag": {},
        "step1_history_unavailable": True,
        "message": message,
        "total_workload": 0,
    }
    summary = {
        "selected_date_et": selected_date_et.isoformat(),
        "active_workload": 0,
        "total_workload": 0,
        "completed": 0,
        "pending": 0,
        "new_today": 0,
        "carryover": 0,
        "exceptions": {"review_required": 0, "total": 0},
        "step1_history_unavailable": True,
        "message": message,
        "segments": {
            "all": {
                "active_workload": 0,
                "total_workload": 0,
                "completed": 0,
                "pending": 0,
                "new_today": 0,
                "carryover": 0,
                "exceptions": {"review_required": 0, "total": 0},
            }
        },
    }
    day_meta = {
        "status": None,
        "shift_date_et": selected_date_et,
        "step1_history_unavailable": True,
        "message": message,
    }
    return wl, summary, day_meta


def count_admitted_operational_workload(
    summary: Mapping[str, Any] | None,
    membership: Mapping[str, Any] | None = None,
) -> int:
    """
    Count of today's admitted operational bags.

    Uses opening scrape admits + added-during-day. Does NOT count
    excluded_prior_day_carryin_count, historical bags, or future scrapes.
    """
    summary = summary or {}
    mem = membership if isinstance(membership, dict) else summary.get("membership")
    mem = mem if isinstance(mem, dict) else {}

    opening = int(
        mem.get("opening_scrape_admit_count")
        if mem.get("opening_scrape_admit_count") is not None
        else (mem.get("baseline_count") or 0)
    )
    added = int(
        mem.get("added_during_day_count")
        if mem.get("added_during_day_count") is not None
        else (mem.get("added_later_count") or 0)
    )
    from_membership = max(0, opening) + max(0, added)

    segs = summary.get("segments") or {}
    all_seg = segs.get("all") if isinstance(segs.get("all"), dict) else {}
    total = int(
        all_seg.get("total_workload")
        if all_seg.get("total_workload") is not None
        else (summary.get("total_workload") or 0)
    )
    active = int(
        all_seg.get("active_workload")
        if all_seg.get("active_workload") is not None
        else (summary.get("active_workload") or 0)
    )
    new_today = int(
        all_seg.get("new_today")
        if all_seg.get("new_today") is not None
        else (summary.get("new_today") or 0)
    )
    completed = int(
        all_seg.get("completed")
        if all_seg.get("completed") is not None
        else (summary.get("completed") or 0)
    )

    # Distinct bags admitted today — do not count carryover-only membership.
    admitted_ids: set[str] = set()
    for svc in ("all", "wf", "hd"):
        bags = ((segs.get(svc) or {}).get("bag_ids") or {})
        for key in ("new_today", "completed", "pending", "review_required"):
            for raw in bags.get(key) or []:
                bid = normalize_bag_id(raw)
                if bid:
                    admitted_ids.add(bid)

    return max(from_membership, total, active, new_today, completed, len(admitted_ids))


def derive_shift_day_status(
    summary: Mapping[str, Any] | None,
    *,
    current_status: str | None = None,
    membership: Mapping[str, Any] | None = None,
) -> str:
    """
    Shift Monitor day status from admitted workload + pending/review queues.

    NOT_STARTED  — no operational work admitted today
    OPEN         — work admitted and pending or review remains
    READY_TO_CLOSE — work admitted and pending=0 and review=0
    REOPENED     — preserved while queues remain after reopen
    CLOSED       — never auto-derived here (manager action only)
    """
    cur = str(current_status or "").strip().upper() or None
    if cur == STATUS_CLOSED:
        return STATUS_CLOSED

    summary = summary or {}
    segs = summary.get("segments") or {}
    all_seg = segs.get("all") if isinstance(segs.get("all"), dict) else {}
    pending = int(
        all_seg.get("pending")
        if all_seg.get("pending") is not None
        else (summary.get("pending") or 0)
    )
    review = int(
        (all_seg.get("exceptions") or summary.get("exceptions") or {}).get("review_required")
        or 0
    )
    admitted = count_admitted_operational_workload(summary, membership)

    # Reopened days already had a closed shift — never collapse to NOT_STARTED.
    if cur == STATUS_REOPENED:
        if pending > 0 or review > 0:
            return STATUS_REOPENED
        return STATUS_READY_TO_CLOSE if admitted > 0 else STATUS_REOPENED

    if admitted <= 0:
        return STATUS_NOT_STARTED

    if pending == 0 and review == 0:
        return STATUS_READY_TO_CLOSE
    return STATUS_OPEN


def _build_step1_workload_for_date(
    cursor,
    organization_id: int,
    selected_date_et: date,
):
    """Use append-only membership rebuild on/after VeeWash cutover."""
    if (
        int(organization_id) == VEEWASH_ORG_ID
        and selected_date_et >= STEP1_AUTHORITATIVE_START_ET
    ):
        return build_veewash_daily_workload_from_membership(
            cursor, organization_id, selected_date_et=selected_date_et
        )
    return build_veewash_daily_workload(
        cursor, organization_id, selected_date_et=selected_date_et
    )


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
          manager_edit_version INT NOT NULL DEFAULT 0,
          UNIQUE KEY uq_shift_monitor_day_bag (organization_id, shift_date_et, bag_id),
          KEY idx_shift_monitor_day_bag_status (organization_id, shift_date_et, effective_status),
          KEY idx_shift_monitor_day_bag_svc (organization_id, shift_date_et, service_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Productivity projection columns (additive; safe on existing tables).
    for col_sql in (
        "ADD COLUMN productivity_employee_name VARCHAR(255) NULL",
        "ADD COLUMN productivity_completed_at DATETIME NULL",
        "ADD COLUMN productivity_weight_lbs DECIMAL(10,4) NULL",
        "ADD COLUMN productivity_credit_eligible TINYINT(1) NULL",
        "ADD COLUMN productivity_exclusion_reason VARCHAR(128) NULL",
        # Manager-edit optimistic lock — never bumped by scrape/productivity/source sync.
        "ADD COLUMN manager_edit_version INT NOT NULL DEFAULT 0",
    ):
        try:
            cursor.execute(f"ALTER TABLE rinse_shift_monitor_day_bags {col_sql}")
        except Exception:
            pass
    try:
        cursor.execute(
            """
            ALTER TABLE rinse_shift_monitor_day_bags
              ADD KEY idx_shift_monitor_day_bag_prod_emp
                (organization_id, shift_date_et, productivity_credit_eligible, productivity_employee_name)
            """
        )
    except Exception:
        pass
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
        SELECT id, organization_id, shift_date_et, status, opened_at, last_sync_at,
               closed_at, closed_by_user_id, closed_by_display_name, close_reason,
               close_override, reopen_count, review_required_count, created_at, updated_at,
               headline_json, workload_meta_json
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


def get_day_headline(cursor, organization_id: int, shift_date_et: date) -> dict[str, Any] | None:
    """Fast path for drawers: status + headline only (skips unused day columns)."""
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT status, reopen_count, review_required_count, headline_json
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
    out["workload_meta"] = {}
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


def _operational_membership_ids(wl: Mapping[str, Any]) -> set[str]:
    """Bags that belong on the persisted day snapshot (never all presence rows)."""
    ids: set[str] = set()
    for key in (
        "new_today",
        "carryover",
        "completed_on_date",
        "pending_end_of_date",
        "review_required",
        "disappeared_without_completion_exceptions",
        "completed_without_recognized_entry",
        "completed_without_entry_scan",
    ):
        for bid in wl.get(key) or []:
            nb = normalize_bag_id(bid)
            if nb:
                ids.add(nb)
    return ids


def _bag_rows_from_workload(wl: Mapping[str, Any], summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    review_ids = set(wl.get("review_required") or summary.get("segments", {}).get("all", {}).get("bag_ids", {}).get("review_required") or [])
    reasons = wl.get("review_reasons_by_bag") or summary.get("review_reasons_by_bag") or {}
    member_ids = _operational_membership_ids(wl)
    rows_out: list[dict[str, Any]] = []
    for row in wl.get("rows") or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        # Never persist presence-only / not_in_workload rows onto the day table.
        if member_ids and bid not in member_ids:
            continue
        entry_class = row.get("entry_class") or row.get("inclusion_source") or "new_today"
        if entry_class in ("carryover", "FIRST_SCRAPE_BASELINE", "ADDED_LATER_IN_DAY"):
            # Persist operational membership without carryover classification.
            entry_class = "new_today" if entry_class != "carryover" else "new_today"
        if entry_class == "carryover":
            entry_class = "new_today"
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
                "new_or_carryover": "workload" if entry_class else None,
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
    # When caller passes an explicit status (e.g. CLOSED), keep it. Otherwise derive
    # from admitted workload + pending/review — never READY_TO_CLOSE on empty days.
    if status is not None:
        next_status = status
    else:
        next_status = derive_shift_day_status(
            summary,
            current_status=(existing or {}).get("status"),
            membership=(
                summary.get("membership") if isinstance(summary.get("membership"), dict) else None
            ),
        )
    # Stamp opened_at only once the shift actually starts (leaves NOT_STARTED).
    opened_at = (existing or {}).get("opened_at")
    if next_status not in (STATUS_NOT_STARTED, None) and not opened_at:
        opened_at = now
    elif next_status == STATUS_NOT_STARTED:
        opened_at = opened_at  # leave null until first admit
    else:
        opened_at = opened_at or now

    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_days (
          organization_id, shift_date_et, status, opened_at, last_sync_at,
          review_required_count, headline_json, workload_meta_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          status = VALUES(status),
          opened_at = COALESCE(rinse_shift_monitor_days.opened_at, VALUES(opened_at)),
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
            opened_at,
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
    from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

    for b in bags:
        proj = project_productivity_fields_for_day_bag(b)
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
              bag_snapshot_json,
              productivity_employee_name, productivity_completed_at,
              productivity_weight_lbs, productivity_credit_eligible,
              productivity_exclusion_reason,
              manager_edit_version
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,%s,
              0
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
              productivity_employee_name=VALUES(productivity_employee_name),
              productivity_completed_at=VALUES(productivity_completed_at),
              productivity_weight_lbs=VALUES(productivity_weight_lbs),
              productivity_credit_eligible=VALUES(productivity_credit_eligible),
              productivity_exclusion_reason=VALUES(productivity_exclusion_reason),
              -- Source/membership/productivity refresh must never bump the manager-edit
              -- optimistic-lock token (manager_edit_version or updated_at).
              updated_at=updated_at,
              manager_edit_version=manager_edit_version
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
                proj.get("productivity_employee_name"),
                _dt(proj.get("productivity_completed_at")),
                proj.get("productivity_weight_lbs"),
                proj.get("productivity_credit_eligible"),
                proj.get("productivity_exclusion_reason"),
            ),
        )
    # Drop presence-only / stale orphans left by older persist bugs.
    keep_ids = sorted({normalize_bag_id(b.get("bag_id")) for b in bags if b.get("bag_id")})
    if keep_ids:
        placeholders = ",".join(["%s"] * len(keep_ids))
        cursor.execute(
            f"""
            DELETE FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND bag_id NOT IN ({placeholders})
            """,
            (int(organization_id), shift_date_et, *keep_ids),
        )
    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(organization_id, shift_date_et)
    except Exception:
        pass
    return get_day_record(cursor, organization_id, shift_date_et) or {}


def _hydrate_day_bag_row(row: Mapping[str, Any]) -> dict[str, Any]:
    d = dict(row)
    d["review_reason_codes"] = _json_load(d.pop("review_reason_codes_json", None)) or []
    d["bag_snapshot"] = _json_load(d.pop("bag_snapshot_json", None)) or {}
    return d


def _headline_bucket_for_status(status: str | None) -> str | None:
    s = str(status or "").strip().lower()
    if s == OUTCOME_REVIEW_REQUIRED or s == "review_required":
        return "review_required"
    if s == OUTCOME_COMPLETED or s == "completed" or s.endswith("_completed"):
        return "completed"
    if s == OUTCOME_PENDING or s == "pending" or "pending" in s:
        return "pending"
    if s in ("excluded", "exclude"):
        return "excluded"
    return None


def _segment_lists_bag(seg: Mapping[str, Any], bid: str) -> bool:
    bags = (seg or {}).get("bag_ids") or {}
    for vals in bags.values():
        for x in list(vals or []):
            if normalize_bag_id(x) == bid:
                return True
    return False


def _move_bag_in_segment_bucket(
    seg: Mapping[str, Any],
    bid: str,
    *,
    old_bucket: str | None,
    new_bucket: str | None,
) -> dict[str, Any]:
    """Move one bag between completed/pending/review_required lists inside a segment."""
    out = dict(seg or {})
    if not _segment_lists_bag(out, bid):
        return out
    bag_ids = dict(out.get("bag_ids") or {})
    if old_bucket and old_bucket != new_bucket:
        old_list = [
            x for x in list(bag_ids.get(old_bucket) or []) if normalize_bag_id(x) != bid
        ]
        bag_ids[old_bucket] = old_list
        out[old_bucket] = len(old_list)
        if old_bucket == "review_required":
            out["exceptions"] = {
                **dict(out.get("exceptions") or {}),
                "review_required": len(old_list),
                "disappeared_without_completion": len(old_list),
                "total": len(old_list),
            }
    if new_bucket and new_bucket != "excluded":
        new_list = sorted(
            {
                normalize_bag_id(x)
                for x in list(bag_ids.get(new_bucket) or [])
                if normalize_bag_id(x)
            }
            | {bid}
        )
        bag_ids[new_bucket] = new_list
        out[new_bucket] = len(new_list)
        if new_bucket == "review_required":
            out["exceptions"] = {
                **dict(out.get("exceptions") or {}),
                "review_required": len(new_list),
                "disappeared_without_completion": len(new_list),
                "total": len(new_list),
            }
    out["bag_ids"] = bag_ids
    return out


def _strip_bag_from_review_segments(
    segments: Mapping[str, Any],
    bid: str,
    *,
    new_bucket: str | None,
) -> dict[str, Any]:
    """Force-remove bag from every segment's review_required list, then place in new_bucket."""
    out: dict[str, Any] = {}
    for name, seg in dict(segments or {}).items():
        moved = _move_bag_in_segment_bucket(
            seg, bid, old_bucket="review_required", new_bucket=None
        )
        if new_bucket and new_bucket not in (None, "excluded", "review_required"):
            moved = _move_bag_in_segment_bucket(
                moved, bid, old_bucket=None, new_bucket=new_bucket
            )
        out[name] = moved
    return out


def apply_manager_edit_day_bag_patch(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_id: str,
    *,
    previous_effective_status: str | None,
    previous_reason_codes: list[str] | None = None,
    outcome_action: str | None = None,
    bulk_cleared: bool = False,
    completion_at: Any = None,
    completed_by: str | None = None,
    pre_weight_lbs: Any = None,
    post_weight_lbs: Any = None,
) -> dict[str, Any]:
    """Fast post-edit sync: one day_bag + headline counts (no full day rebuild).

    Must run only after the manager edit lock check has already succeeded.
    Does not bump ``manager_edit_version`` / ``updated_at``.
    """
    from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW

    ensure_shift_monitor_day_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}

    rows = load_day_bags_by_ids(cursor, organization_id, shift_date_et, [bid])
    day_row = rows[0] if rows else {}
    prev_status = str(
        previous_effective_status
        or day_row.get("effective_status")
        or ""
    ).strip().lower() or None
    reasons = list(previous_reason_codes if previous_reason_codes is not None else (day_row.get("review_reason_codes") or []))
    if bulk_cleared:
        reasons = [r for r in reasons if str(r) != REASON_WF_BULK_WORKITEM_REVIEW]

    outcome = str(outcome_action or "").strip().lower() or None
    if outcome == "mark_completed":
        new_status = OUTCOME_COMPLETED
        reasons = []
        disposition = DISPOSITION_COMPLETED
    elif outcome == "return_pending":
        new_status = OUTCOME_PENDING
        reasons = []
        disposition = DISPOSITION_CARRY_FORWARD
    elif outcome == "exclude":
        new_status = "excluded"
        reasons = []
        disposition = DISPOSITION_EXCLUDE
    else:
        if reasons:
            new_status = OUTCOME_REVIEW_REQUIRED
            disposition = day_row.get("disposition")
        else:
            # Bulk/fields-only save cleared the last review reason.
            canon = str(day_row.get("canonical_completion_status") or "").lower()
            if completion_at or canon in (OUTCOME_COMPLETED, "completed") or "completed" in canon:
                new_status = OUTCOME_COMPLETED
                disposition = DISPOSITION_COMPLETED
            else:
                new_status = OUTCOME_PENDING
                disposition = DISPOSITION_CARRY_FORWARD

    snap = dict(day_row.get("bag_snapshot") or {})
    snap.update(
        {
            "outcome": new_status,
            "final_bucket": new_status,
            "reason_codes": list(reasons),
            "effective_status": new_status,
        }
    )
    if completion_at is not None:
        snap["completion_at"] = (
            completion_at.isoformat() if hasattr(completion_at, "isoformat") else completion_at
        )
    if completed_by is not None:
        snap["completed_by"] = completed_by
    if pre_weight_lbs is not None:
        snap["pre_weight_lbs"] = pre_weight_lbs
    if post_weight_lbs is not None:
        snap["post_weight_lbs"] = post_weight_lbs
        snap["weight_lbs"] = post_weight_lbs

    weight_lbs = post_weight_lbs if post_weight_lbs is not None else day_row.get("weight_lbs")
    try:
        from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

        proj = project_productivity_fields_for_day_bag(
            {
                "effective_status": new_status,
                "canonical_completion_employee": completed_by
                if completed_by is not None
                else day_row.get("canonical_completion_employee"),
                "canonical_completion_timestamp": completion_at
                if completion_at is not None
                else day_row.get("canonical_completion_timestamp"),
                "weight_lbs": weight_lbs,
                "post_weight_lbs": post_weight_lbs
                if post_weight_lbs is not None
                else day_row.get("post_weight_lbs"),
            }
        )
    except Exception:
        proj = {}

    cursor.execute(
        """
        UPDATE rinse_shift_monitor_day_bags
        SET effective_status = %s,
            review_reason_codes_json = %s,
            canonical_completion_status = %s,
            canonical_completion_timestamp = COALESCE(%s, canonical_completion_timestamp),
            canonical_completion_employee = COALESCE(%s, canonical_completion_employee),
            pre_weight_lbs = COALESCE(%s, pre_weight_lbs),
            post_weight_lbs = COALESCE(%s, post_weight_lbs),
            weight_lbs = COALESCE(%s, weight_lbs),
            disposition = COALESCE(%s, disposition),
            bag_snapshot_json = %s,
            productivity_employee_name = %s,
            productivity_completed_at = %s,
            productivity_weight_lbs = %s,
            productivity_credit_eligible = %s,
            productivity_exclusion_reason = %s,
            updated_at = updated_at
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        """,
        (
            new_status,
            _json_dump(reasons),
            new_status,
            _dt(completion_at) if completion_at is not None else None,
            completed_by,
            pre_weight_lbs,
            post_weight_lbs,
            weight_lbs,
            disposition,
            _json_dump(snap),
            proj.get("productivity_employee_name"),
            _dt(proj.get("productivity_completed_at")),
            proj.get("productivity_weight_lbs"),
            proj.get("productivity_credit_eligible"),
            proj.get("productivity_exclusion_reason"),
            int(organization_id),
            shift_date_et,
            bid,
        ),
    )

    # Patch headline counts / bag_id lists for the status transition.
    # Must update WF/HD/rush segments too — drawers read those, not only "all".
    day = get_day_record(cursor, organization_id, shift_date_et)
    if day:
        headline = dict(day.get("headline") or {})
        segments = dict(headline.get("segments") or {})
        old_bucket = _headline_bucket_for_status(prev_status)
        new_bucket = _headline_bucket_for_status(new_status)
        # Always strip from review_required when leaving review — day_bag may already
        # say "completed" while WF/rush segments still list the bag (stale KPI).
        if new_bucket != "review_required":
            segments = _strip_bag_from_review_segments(
                segments, bid, new_bucket=new_bucket
            )
        elif old_bucket and old_bucket != new_bucket:
            for seg_name, seg in list(segments.items()):
                segments[seg_name] = _move_bag_in_segment_bucket(
                    seg,
                    bid,
                    old_bucket=old_bucket,
                    new_bucket=new_bucket,
                )
        all_seg = dict(segments.get("all") or {})
        headline["segments"] = segments
        headline["completed"] = all_seg.get("completed", headline.get("completed"))
        headline["pending"] = all_seg.get("pending", headline.get("pending"))
        headline["exceptions"] = dict(all_seg.get("exceptions") or headline.get("exceptions") or {})
        review_n = int((headline.get("exceptions") or {}).get("review_required") or 0)
        # Prefer WF-accurate total from all segment after strip.
        reasons_by_bag = dict(
            (day.get("workload_meta") or {}).get("review_reasons_by_bag")
            or headline.get("review_reasons_by_bag")
            or {}
        )
        if reasons:
            reasons_by_bag[bid] = list(reasons)
        else:
            reasons_by_bag.pop(bid, None)
        headline["review_reasons_by_bag"] = reasons_by_bag
        # Drop bag from review_by_reason indexes when leaving review.
        review_by_reason = dict(headline.get("review_by_reason") or {})
        if new_bucket != "review_required":
            cleaned = {}
            for code, ids in review_by_reason.items():
                kept = [x for x in list(ids or []) if normalize_bag_id(x) != bid]
                if kept:
                    cleaned[code] = kept
            review_by_reason = cleaned
            headline["review_by_reason"] = review_by_reason
        meta = dict(day.get("workload_meta") or {})
        meta["review_reasons_by_bag"] = reasons_by_bag
        if "review_by_reason" in headline:
            meta["review_by_reason"] = review_by_reason
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_days
            SET review_required_count = %s,
                headline_json = %s,
                workload_meta_json = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = %s AND shift_date_et = %s
            """,
            (
                review_n,
                _json_dump(headline),
                _json_dump(meta),
                int(organization_id),
                shift_date_et,
            ),
        )

    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(organization_id, shift_date_et)
    except Exception:
        pass

    return {
        "ok": True,
        "bag_id": bid,
        "previous_effective_status": prev_status,
        "effective_status": new_status,
        "review_reason_codes": reasons,
    }


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
    cutover = _step1_cutover_date(organization_id, activation)
    if cutover and selected_date_et < cutover:
        return _unavailable_step1_payload(selected_date_et)
    if (
        int(organization_id) == VEEWASH_ORG_ID
        and selected_date_et < STEP1_AUTHORITATIVE_START_ET
    ):
        return _unavailable_step1_payload(selected_date_et)

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
        and status
        in (
            STATUS_OPEN,
            STATUS_READY_TO_CLOSE,
            STATUS_REOPENED,
            STATUS_NOT_STARTED,
        )
        and day.get("headline")
        and not persist_live
    ):
        has_bags = (not include_bag_rows) or day_bag_count(cursor, organization_id, selected_date_et) > 0
        if has_bags or not include_bag_rows:
            wl, summary, day_out = _summary_shell(day, status_value=str(status))
            if summary:
                return wl, summary, day_out

    # Historical OPEN/READY/REOPENED/NOT_STARTED snapshots stay stable after first persist.
    # REOPENED prior days keep the frozen bag set until an explicit backfill/correction rebuild.
    if (
        day
        and selected_date_et < today
        and status
        in (
            STATUS_OPEN,
            STATUS_READY_TO_CLOSE,
            STATUS_REOPENED,
            STATUS_NOT_STARTED,
        )
        and day.get("headline")
    ):
        has_bags = (not include_bag_rows) or day_bag_count(cursor, organization_id, selected_date_et) > 0
        if has_bags:
            wl, summary, day_out = _summary_shell(day, status_value=str(status))
            if summary:
                return wl, summary, day_out

    # Live / reconstruct path (today, or missing prior-day snapshot).
    # On/after VeeWash Jul 23 cutover: append-only membership rebuild (not live presence rewrite).
    wl = _build_step1_workload_for_date(cursor, organization_id, selected_date_et)
    summary = build_step1_headline_summary(
        wl, selected_date_et=selected_date_et, activation_date=activation
    )

    # Ensure membership is available for admitted-workload status derivation.
    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")

    review_n = int((summary.get("exceptions") or {}).get("review_required") or 0)
    next_status = derive_shift_day_status(
        summary,
        current_status=status,
        membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
    )

    # Never silently rewrite a prior-day snapshot from a partial live rebuild.
    should_persist = persist_live and (
        selected_date_et == today
        or day is None
        or (
            selected_date_et < today
            and status
            in (
                STATUS_OPEN,
                STATUS_READY_TO_CLOSE,
                STATUS_REOPENED,
                STATUS_NOT_STARTED,
            )
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
    if (day or {}).get("status") == STATUS_NOT_STARTED or derive_shift_day_status(
        summary,
        current_status=(day or {}).get("status"),
        membership=summary.get("membership") if isinstance(summary.get("membership"), dict) else None,
    ) == STATUS_NOT_STARTED:
        return {
            "ok": False,
            "error": "shift_not_started",
            "message": "Shift has not started — nothing to close.",
            "day": day,
        }

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
    # Cutover 2026-07-23: next day starts from its own after-midnight scrape.
    # Do not seed carryover rows into the following ET day.
    # _seed_next_day_carryover(cursor, organization_id, shift_date_et)

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
    """Rebuild and persist a day from source (activation / cutover onward)."""
    activation = get_step1_activation_date(cursor, organization_id)
    cutover = _step1_cutover_date(organization_id, activation)
    if cutover and shift_date_et < cutover:
        return {
            "ok": False,
            "error": "before_cutover",
            "cutover_date_et": cutover.isoformat(),
            "message": _HISTORY_UNAVAILABLE_MSG,
        }
    if (
        int(organization_id) == VEEWASH_ORG_ID
        and shift_date_et < STEP1_AUTHORITATIVE_START_ET
    ):
        return {
            "ok": False,
            "error": "before_cutover",
            "cutover_date_et": STEP1_AUTHORITATIVE_START_ET.isoformat(),
            "message": _HISTORY_UNAVAILABLE_MSG,
        }
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
    # On/after cutover: same-day membership rebuild (not live presence rewrite).
    wl = _build_step1_workload_for_date(cursor, organization_id, shift_date_et)
    summary = build_step1_headline_summary(
        wl,
        selected_date_et=shift_date_et,
        activation_date=activation or shift_date_et,
    )
    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")
    review_n = int((summary.get("exceptions") or {}).get("review_required") or 0)
    day = persist_day_snapshot(
        cursor,
        organization_id,
        shift_date_et,
        workload=wl,
        summary=summary,
        status=derive_shift_day_status(
            summary,
            current_status=(day or {}).get("status"),
            membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
        ),
        force=True,
    )
    _commit(cursor)
    return {
        "ok": True,
        "day": day,
        "summary_totals": {
            "active": summary.get("active_workload"),
            "total_workload": summary.get("total_workload"),
            "completed": summary.get("completed"),
            "pending": summary.get("pending"),
            "review_required": (summary.get("exceptions") or {}).get("review_required"),
        },
        "membership": wl.get("membership"),
        "bag_count": len(load_day_bags(cursor, organization_id, shift_date_et)),
    }
