"""Persist VeeWash Step-1 daily Shift Monitor snapshots + close/reopen."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Mapping, Sequence

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

logger = logging.getLogger(__name__)

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


_SNAPSHOT_MISSING_MSG = (
    "Shift Monitor snapshot is not available yet. "
    "Counts will appear after a successful scan refresh."
)


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


def _snapshot_missing_step1_payload(
    selected_date_et: date,
    *,
    message: str = _SNAPSHOT_MISSING_MSG,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fast interactive-read payload when no persisted Step-1 day snapshot exists.

    Counts are intentionally null (not zero) so the UI shows Unavailable instead of
    fabricated live values. Callers with persist_live=True must not use this path.
    """
    empty_seg = {
        "active_workload": None,
        "total_workload": None,
        "completed": None,
        "pending": None,
        "new_today": None,
        "carryover": None,
        "exceptions": {"review_required": None, "total": None},
        "bag_ids": {
            "active_workload": [],
            "completed": [],
            "pending": [],
            "review_required": [],
            "new_today": [],
            "carryover": [],
        },
    }
    flags = {
        "snapshot_available": False,
        "snapshot_status": "missing",
        "data_unavailable": True,
        "unavailable_reason": "step1_snapshot_missing",
        "snapshot_missing": True,
        "message": message,
    }
    wl = {
        "selected_date_et": selected_date_et.isoformat(),
        "rows": [],
        "new_today": [],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": [],
        "review_required": [],
        "review_reasons_by_bag": {},
        "total_workload": None,
        "from_snapshot": False,
        **flags,
    }
    summary = {
        "selected_date_et": selected_date_et.isoformat(),
        "active_workload": None,
        "total_workload": None,
        "completed": None,
        "pending": None,
        "new_today": None,
        "carryover": None,
        "exceptions": {"review_required": None, "total": None},
        "segments": {
            "all": dict(empty_seg),
            "wf": dict(empty_seg),
            "hd": dict(empty_seg),
        },
        "shift_day": {
            "status": None,
            "read_only": True,
            "review_required_count": None,
            **flags,
        },
        "shift_day_status": None,
        **flags,
    }
    day_meta = {
        "status": None,
        "shift_date_et": selected_date_et,
        **flags,
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

    opening_carry = int(mem.get("opening_carryover_count") or 0)
    opening_new = int(mem.get("opening_new_count") or 0)
    if opening_carry or opening_new:
        opening = opening_carry + opening_new
    else:
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

    # Distinct bags admitted today (Opening Carryover ∪ Opening New ∪ Added).
    admitted_ids: set[str] = set()
    for svc in ("all", "wf", "hd"):
        bags = ((segs.get(svc) or {}).get("bag_ids") or {})
        for key in (
            "new_today",
            "carryover",
            "opening_carryover",
            "opening_new",
            "added_during_day",
            "completed",
            "pending",
            "review_required",
        ):
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
    eff_raw = str(row.get("effective_status") or "").strip().lower()
    if eff_raw in (OUTCOME_COMPLETED, "completed") or eff_raw.endswith("_completed"):
        return OUTCOME_COMPLETED
    if eff_raw in (OUTCOME_REVIEW_REQUIRED, "review_required"):
        return OUTCOME_REVIEW_REQUIRED
    if eff_raw in (OUTCOME_PENDING, "pending") or "pending" in eff_raw:
        return OUTCOME_PENDING
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
    # Prefer finalized summary review lists (HD WIA-only Review Required) over raw wl.
    summary_review = (
        ((summary.get("segments") or {}).get("all") or {}).get("bag_ids") or {}
    ).get("review_required")
    review_ids = set(
        summary_review if summary_review is not None else (wl.get("review_required") or [])
    )
    hd_completed = {
        normalize_bag_id(b)
        for b in (
            (((summary.get("segments") or {}).get("hd") or {}).get("bag_ids") or {}).get(
                "completed"
            )
            or []
        )
        if normalize_bag_id(b)
    }
    reasons = wl.get("review_reasons_by_bag") or summary.get("review_reasons_by_bag") or {}
    # Snapshot shells historically only populated review_required list keys. Treat every
    # row on a from_snapshot shell as day membership so a re-persist cannot DELETE
    # completed / pending bags and wipe Employee Productivity.
    if wl.get("from_snapshot"):
        member_ids = {
            normalize_bag_id(r.get("bag_id"))
            for r in (wl.get("rows") or [])
            if r.get("bag_id")
        }
        member_ids.discard("")
    else:
        member_ids = _operational_membership_ids(wl)
    rows_out: list[dict[str, Any]] = []
    for row in wl.get("rows") or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        # Never persist presence-only / not_in_workload rows onto the day table.
        if member_ids and bid not in member_ids:
            continue
        fb_skip = str(row.get("final_bucket") or row.get("outcome") or "").strip().lower()
        if fb_skip in (
            "not_in_workload",
            "disappeared_prior_open_exception",
        ):
            # Historical prior-open exceptions are diagnostics, not day membership.
            continue
        entry_class = row.get("entry_class") or row.get("inclusion_source") or "new_today"
        # Normalize inclusion_source constants onto stable entry_class labels.
        if entry_class in ("OPENING_CARRYOVER", "opening_carryover", "carryover"):
            entry_class = "opening_carryover"
        elif entry_class in ("OPENING_NEW", "opening_new", "FIRST_SCRAPE_BASELINE"):
            entry_class = "opening_new"
        elif entry_class in ("ADDED_LATER_IN_DAY", "added_during_day", "ADDED_LATER"):
            entry_class = "added_during_day"
        elif entry_class == "new_today":
            entry_class = "opening_new"
        eff = _effective_status_for_row(row, review_ids)
        if bid in hd_completed:
            eff = OUTCOME_COMPLETED
        elif (
            str(row.get("service_type") or "").strip().upper() == "HD"
            and bid not in review_ids
            and eff != OUTCOME_COMPLETED
        ):
            # Non-WIA HD members stay pending members (not auto Review Required).
            eff = OUTCOME_PENDING
        # Only persist bags that are part of the day's operational set.
        # Snapshot rows are already the day membership — do not drop by entry_class.
        _persistable_entry = (
            "new_today",
            "carryover",
            "opening_carryover",
            "opening_new",
            "added_during_day",
        )
        if (
            not wl.get("from_snapshot")
            and entry_class not in _persistable_entry
            and bid not in review_ids
        ):
            # Still keep CWO / review bags that were force-included.
            if eff != OUTCOME_REVIEW_REQUIRED and row.get("final_bucket") != "review_required":
                continue
        snap = dict(row)
        if eff == OUTCOME_COMPLETED:
            snap["outcome"] = OUTCOME_COMPLETED
            # Drop stale pre-cycle classify reasons once current-cycle completion wins.
            if snap.get("reason") in (
                "completed_before_selected_date",
                "completes_after_selected_date_not_yet_entered",
            ):
                snap.pop("reason", None)
            fb = str(snap.get("final_bucket") or "")
            if (
                not fb
                or "pending" in fb
                or fb == "not_in_workload"
                or "completed_before" in fb
            ):
                snap["final_bucket"] = f"{entry_class}_{OUTCOME_COMPLETED}"
            if row.get("completion_source"):
                snap["completion_source"] = row.get("completion_source")
            if row.get("cycle_anchor_at") is not None:
                snap["cycle_anchor_at"] = row.get("cycle_anchor_at")
        elif row.get("pending_reason"):
            snap["pending_reason"] = row.get("pending_reason")
            snap["reason"] = row.get("pending_reason")
        if entry_class == "opening_carryover":
            new_or_carry = "carryover"
        elif entry_class == "added_during_day":
            new_or_carry = "added_during_day"
        else:
            new_or_carry = "opening_new"
        # Columns and snapshot must carry the same resolved PRE/POST facts.
        pre_lbs = row.get("pre_weight_lbs")
        post_lbs = row.get("post_weight_lbs")
        weight_lbs = row.get("weight_lbs")
        if weight_lbs is None and post_lbs is not None:
            weight_lbs = post_lbs
        snap["pre_weight_lbs"] = pre_lbs
        snap["post_weight_lbs"] = post_lbs
        if weight_lbs is not None:
            snap["weight_lbs"] = weight_lbs
        for _wk in (
            "pre_weight_at",
            "post_weight_at",
            "pre_weight_employee",
            "post_weight_employee",
            "pre_weight_attach_reason",
            "post_weight_attach_reason",
            "pre_weight_source",
            "post_weight_source",
            "pre_resolution_status",
            "post_resolution_status",
        ):
            if row.get(_wk) is not None:
                snap[_wk] = row.get(_wk)
        from backend.rinse_day_bag_completion_projection import normalize_completion_fields

        comp_ts, comp_emp = normalize_completion_fields({**row, "bag_snapshot": snap})
        rows_out.append(
            {
                "bag_id": bid,
                "service_type": row.get("service_type"),
                "rush_status": row.get("rush_flag"),
                "new_or_carryover": new_or_carry,
                "workload_entry_type": row.get("entry_source"),
                "workload_entry_timestamp": row.get("first_entry_at")
                or row.get("entry_at")
                or row.get("original_entry_date"),
                "pre_weight_lbs": pre_lbs,
                "post_weight_lbs": post_lbs,
                "weight_lbs": weight_lbs,
                "canonical_completion_status": row.get("canonical_status")
                or snap.get("outcome")
                or row.get("outcome"),
                "canonical_completion_timestamp": comp_ts,
                "canonical_completion_employee": comp_emp,
                "effective_status": eff,
                "review_reason_codes": list(reasons.get(bid) or row.get("reason_codes") or []),
                "portal_status_at_sync": row.get("portal_status"),
                "last_present_scrape": row.get("last_seen_date") or row.get("last_seen_at"),
                "first_confirmed_absent_scrape": row.get("disappeared_date"),
                "disposition": row.get("disposition"),
                "bag_snapshot": snap,
            }
        )
    return rows_out


def _day_bag_manager_lock_upsert_sql() -> str:
    """INSERT ... ON DUPLICATE KEY UPDATE for day bags with manager precedence.

    When ``manager_edit_version > 0``, automatic refresh must not overwrite
    manager-controlled decision fields. Observational scrape fields still update.
    Uses INSERT alias ``incoming`` (MySQL 8.0.19+) so VALUES() is not required.
    """
    return """
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
            ) AS incoming
            ON DUPLICATE KEY UPDATE
              service_type=incoming.service_type,
              rush_status=incoming.rush_status,
              new_or_carryover=incoming.new_or_carryover,
              workload_entry_type=incoming.workload_entry_type,
              workload_entry_timestamp=incoming.workload_entry_timestamp,
              pre_weight_lbs=incoming.pre_weight_lbs,
              post_weight_lbs=incoming.post_weight_lbs,
              weight_lbs=incoming.weight_lbs,
              -- Manager decision > automatic classifier > raw scrape.
              -- manager_edit_version > 0: preserve decision fields; never keep
              -- only the version token while replacing status/outcome.
              canonical_completion_status=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.canonical_completion_status,
                incoming.canonical_completion_status
              ),
              canonical_completion_timestamp=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.canonical_completion_timestamp,
                incoming.canonical_completion_timestamp
              ),
              canonical_completion_employee=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.canonical_completion_employee,
                incoming.canonical_completion_employee
              ),
              effective_status=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.effective_status,
                incoming.effective_status
              ),
              review_reason_codes_json=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.review_reason_codes_json,
                incoming.review_reason_codes_json
              ),
              portal_status_at_sync=incoming.portal_status_at_sync,
              last_present_scrape=incoming.last_present_scrape,
              first_confirmed_absent_scrape=incoming.first_confirmed_absent_scrape,
              disposition=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.disposition,
                COALESCE(incoming.disposition, rinse_shift_monitor_day_bags.disposition)
              ),
              -- Manager lock preserves decision fields in the snapshot, but PRE/POST
              -- weight facts must stay aligned with day-bag columns (no dual-state).
              bag_snapshot_json=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                JSON_SET(
                  CAST(
                    COALESCE(
                      rinse_shift_monitor_day_bags.bag_snapshot_json,
                      '{}'
                    ) AS JSON
                  ),
                  '$.pre_weight_lbs', incoming.pre_weight_lbs,
                  '$.post_weight_lbs', incoming.post_weight_lbs,
                  '$.weight_lbs', incoming.weight_lbs,
                  '$.pre_weight_at',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.pre_weight_at'),
                  '$.post_weight_at',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.post_weight_at'),
                  '$.pre_weight_employee',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.pre_weight_employee'),
                  '$.post_weight_employee',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.post_weight_employee'),
                  '$.pre_weight_attach_reason',
                    JSON_EXTRACT(
                      CAST(incoming.bag_snapshot_json AS JSON),
                      '$.pre_weight_attach_reason'
                    ),
                  '$.post_weight_attach_reason',
                    JSON_EXTRACT(
                      CAST(incoming.bag_snapshot_json AS JSON),
                      '$.post_weight_attach_reason'
                    ),
                  '$.pre_weight_source',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.pre_weight_source'),
                  '$.post_weight_source',
                    JSON_EXTRACT(CAST(incoming.bag_snapshot_json AS JSON), '$.post_weight_source'),
                  '$.pre_resolution_status',
                    JSON_EXTRACT(
                      CAST(incoming.bag_snapshot_json AS JSON),
                      '$.pre_resolution_status'
                    ),
                  '$.post_resolution_status',
                    JSON_EXTRACT(
                      CAST(incoming.bag_snapshot_json AS JSON),
                      '$.post_resolution_status'
                    )
                ),
                incoming.bag_snapshot_json
              ),
              productivity_employee_name=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.productivity_employee_name,
                incoming.productivity_employee_name
              ),
              productivity_completed_at=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.productivity_completed_at,
                incoming.productivity_completed_at
              ),
              productivity_weight_lbs=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.productivity_weight_lbs,
                incoming.productivity_weight_lbs
              ),
              productivity_credit_eligible=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.productivity_credit_eligible,
                incoming.productivity_credit_eligible
              ),
              productivity_exclusion_reason=IF(
                rinse_shift_monitor_day_bags.manager_edit_version > 0,
                rinse_shift_monitor_day_bags.productivity_exclusion_reason,
                incoming.productivity_exclusion_reason
              ),
              -- Never bump the manager-edit optimistic-lock token on refresh.
              updated_at=rinse_shift_monitor_day_bags.updated_at,
              manager_edit_version=rinse_shift_monitor_day_bags.manager_edit_version
            """


def _load_persisted_review_reasons_by_bag(
    cursor, organization_id: int, shift_date_et: date
) -> dict[str, list[str]]:
    """Authoritative review reasons from protected day-bag rows (review_required only)."""
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT bag_id, review_reason_codes_json, effective_status
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (int(organization_id), shift_date_et),
    )
    raw = cursor.fetchall()
    if not isinstance(raw, (list, tuple)):
        raw = []
    out: dict[str, list[str]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        if _headline_bucket_for_status(row.get("effective_status")) != "review_required":
            continue
        codes = _json_load(row.get("review_reason_codes_json")) or []
        if isinstance(codes, list) and codes:
            out[bid] = [str(c) for c in codes if str(c).strip()]
    return out


def _review_by_reason_from_map(
    reasons_by_bag: Mapping[str, list[str]],
) -> dict[str, list[str]]:
    by_reason: dict[str, list[str]] = {}
    for bid, codes in (reasons_by_bag or {}).items():
        nb = normalize_bag_id(bid)
        if not nb:
            continue
        for code in codes or []:
            key = str(code or "").strip()
            if not key:
                continue
            by_reason.setdefault(key, []).append(nb)
    for key in list(by_reason):
        by_reason[key] = sorted(set(by_reason[key]))
    return by_reason


def _sync_day_header_from_persisted_bags(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    summary: Mapping[str, Any],
    workload: Mapping[str, Any],
    next_status: str,
    opened_at: Any,
    now: datetime,
) -> dict[str, Any]:
    """Persist headline_json from protected day-bag statuses (not live classifier).

    Live classifier review reasons are retained under
    ``workload_meta.auto_classifier_review_reasons_by_bag`` as diagnostics only.
    """
    status_by_bag = _load_day_bag_status_projection(
        cursor, organization_id, shift_date_et
    )
    headline = _apply_day_bag_statuses_to_headline(dict(summary or {}), status_by_bag)
    persisted_reasons = _load_persisted_review_reasons_by_bag(
        cursor, organization_id, shift_date_et
    )
    headline["review_reasons_by_bag"] = persisted_reasons
    headline["review_by_reason"] = _review_by_reason_from_map(persisted_reasons)

    auto_reasons = (
        (workload or {}).get("review_reasons_by_bag")
        or (summary or {}).get("review_reasons_by_bag")
        or {}
    )
    auto_norm = {
        normalize_bag_id(k): [str(c) for c in (v or []) if str(c).strip()]
        for k, v in dict(auto_reasons).items()
        if normalize_bag_id(k)
    }
    buckets = count_day_bag_status_buckets(status_by_bag)
    review_n = int(buckets.get("review_required_count") or 0)
    meta = {
        "selected_date_et": shift_date_et.isoformat(),
        "counts": {
            **dict((workload or {}).get("counts") or {}),
            "completed": buckets.get("completed_count"),
            "pending": buckets.get("pending_count"),
            "review_required": review_n,
            "total_workload": buckets.get("status_total"),
        },
        # UI / drawer authority: protected persisted day-bag reasons only.
        "review_reasons_by_bag": persisted_reasons,
        "review_by_reason": headline.get("review_by_reason"),
        # Diagnostics only — must not drive effective_status or Review Required cards.
        "auto_classifier_review_reasons_by_bag": auto_norm,
        "headline_status_synced_from_day_bags": True,
    }
    headline["completed_count"] = int(buckets.get("completed_count") or 0)
    headline["pending_count"] = int(buckets.get("pending_count") or 0)
    headline["review_required_count"] = review_n

    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_days (
          organization_id, shift_date_et, status, opened_at, last_sync_at,
          review_required_count, headline_json, workload_meta_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
        ON DUPLICATE KEY UPDATE
          status = incoming.status,
          opened_at = COALESCE(
            rinse_shift_monitor_days.opened_at, incoming.opened_at
          ),
          last_sync_at = incoming.last_sync_at,
          review_required_count = incoming.review_required_count,
          headline_json = incoming.headline_json,
          workload_meta_json = incoming.workload_meta_json,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(organization_id),
            shift_date_et,
            next_status,
            opened_at,
            now,
            review_n,
            _json_dump(headline),
            _json_dump(meta),
        ),
    )
    return {
        "headline": headline,
        "workload_meta": meta,
        "review_required_count": review_n,
        "status_buckets": buckets,
    }


def persist_day_snapshot(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    workload: Mapping[str, Any],
    summary: Mapping[str, Any],
    status: str | None = None,
    force: bool = False,
    chronology_complete: bool = True,
    projection_deferred_bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Upsert day header + bag rows. No-op for CLOSED days unless force=True.

    Manager precedence: rows with ``manager_edit_version > 0`` keep their
    decision fields across automatic scrape/Step-1 rebuilds. Headline counts
    and Review ID sets are projected from the protected day-bag rows after
    UPSERT — never from the live classifier summary alone.

    When ``chronology_complete`` is False, previously persisted Completed bags
    are not downgraded to Pending/Review by temporary missing scan evidence.

    ``projection_deferred_bag_ids`` are bag-scoped Stage-B holds: those rows
    keep prior persisted status while eligible bags rebuild normally.
    """
    ensure_shift_monitor_day_tables(cursor)
    existing = get_day_record(cursor, organization_id, shift_date_et)
    if existing and existing.get("status") == STATUS_CLOSED and not force:
        return existing

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

    # Ensure day header row exists before bag UPSERTs (shell only; headline
    # rewritten from protected day bags after the bag loop).
    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_days (
          organization_id, shift_date_et, status, opened_at, last_sync_at,
          review_required_count, headline_json, workload_meta_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
        ON DUPLICATE KEY UPDATE
          status = incoming.status,
          opened_at = COALESCE(
            rinse_shift_monitor_days.opened_at, incoming.opened_at
          ),
          last_sync_at = incoming.last_sync_at,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(organization_id),
            shift_date_et,
            next_status,
            opened_at,
            now,
            int((existing or {}).get("review_required_count") or 0),
            _json_dump((existing or {}).get("headline") or summary),
            _json_dump((existing or {}).get("workload_meta") or {}),
        ),
    )

    bags = _bag_rows_from_workload(workload, summary)
    from backend.rinse_day_bag_completion_projection import (
        apply_normalized_completion_fields,
        enrich_bags_completion_from_scans,
    )
    from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag
    from backend.rinse_scan_chronology_gate import should_preserve_persisted_completion

    enrich_bags_completion_from_scans(
        cursor, organization_id, shift_date_et, bags
    )
    bags = [apply_normalized_completion_fields(b) for b in bags]

    from backend.rinse_wf_service_cycle_compat import (
        apply_wf_selected_day_boundary_guard,
        final_wf_day_membership_bag_ids,
    )

    other_rows: list[dict[str, Any]] = []
    wf_candidate_rows: list[dict[str, Any]] = []
    for b in bags:
        svc = str(
            b.get("service_type")
            or (b.get("bag_snapshot") or {}).get("service_type")
            or "WF"
        ).upper()
        if svc == "WF":
            wf_candidate_rows.append(b)
        else:
            other_rows.append(b)

    try:
        from backend.rinse_wf_service_cycle import is_wf_canonical_lifecycle_enabled
        from backend.rinse_wf_service_cycle_compat import (
            resolve_canonical_wf_day_bag_rows_for_persist,
        )

        if is_wf_canonical_lifecycle_enabled(cursor, int(organization_id)):
            # When terminal_project already froze get_canonical_wf_workload into
            # this workload, replace-only from those rows — never re-derive after
            # cycle reconcile / prior projection artifacts.
            frozen = bool((workload or {}).get("canonical_membership_frozen"))
            if frozen and wf_candidate_rows:
                # Keep frozen WF candidates from the workload payload.
                pass
            else:
                wf_candidate_rows = resolve_canonical_wf_day_bag_rows_for_persist(
                    cursor, int(organization_id), shift_date_et
                )
    except Exception:
        logger.exception(
            "WF canonical day-bag replace failed during persist org=%s date=%s; "
            "fail-closed to zero WF bags (never unfiltered Stage-B)",
            organization_id,
            shift_date_et,
        )
        wf_candidate_rows = []

    # Non-negotiable: candidate − {completion_date_et < D} immediately before upsert.
    # Fail closed — never persist unfiltered WF bags if the guard errors.
    try:
        wf_candidate_rows = apply_wf_selected_day_boundary_guard(
            cursor, int(organization_id), shift_date_et, wf_candidate_rows
        )
    except Exception:
        logger.exception(
            "WF terminal membership guard failed during persist org=%s date=%s; "
            "dropping all WF candidates (fail closed)",
            organization_id,
            shift_date_et,
        )
        try:
            kept_ids = set(
                final_wf_day_membership_bag_ids(
                    cursor,
                    int(organization_id),
                    shift_date_et,
                    [
                        normalize_bag_id(b.get("bag_id"))
                        for b in wf_candidate_rows
                        if normalize_bag_id(b.get("bag_id"))
                    ],
                )
            )
            wf_candidate_rows = [
                b
                for b in wf_candidate_rows
                if normalize_bag_id(b.get("bag_id")) in kept_ids
            ]
        except Exception:
            logger.exception(
                "WF terminal membership fail-closed also failed org=%s date=%s; "
                "persisting zero WF bags",
                organization_id,
                shift_date_et,
            )
            wf_candidate_rows = []

    # WF membership wins on bag_id collisions. A prior bad persist that labeled a
    # canonical WF bag as HD must not overwrite the WF row on upsert.
    wf_ids = {
        normalize_bag_id(b.get("bag_id"))
        for b in wf_candidate_rows
        if normalize_bag_id(b.get("bag_id"))
    }
    if wf_ids:
        other_rows = [
            b
            for b in other_rows
            if normalize_bag_id(b.get("bag_id")) not in wf_ids
        ]
    bags = wf_candidate_rows + other_rows

    deferred_ids = {
        normalize_bag_id(b)
        for b in (projection_deferred_bag_ids or [])
        if normalize_bag_id(b)
    }

    # Prior statuses for incomplete-chronology / bag-level projection deferral.
    prior_by_id: dict[str, dict[str, Any]] = {}
    if (not chronology_complete) or deferred_ids:
        try:
            for row in load_day_bags(cursor, organization_id, shift_date_et) or []:
                bid = normalize_bag_id(row.get("bag_id"))
                if bid:
                    prior_by_id[bid] = dict(row)
        except Exception:
            prior_by_id = {}

    upsert_sql = _day_bag_manager_lock_upsert_sql()
    for b in bags:
        bid = normalize_bag_id(b.get("bag_id"))
        prior = prior_by_id.get(bid) if bid else None
        bag_deferred = bool(bid and bid in deferred_ids)
        if prior and (
            bag_deferred
            or should_preserve_persisted_completion(
                previous_status=prior.get("effective_status"),
                incoming_status=b.get("effective_status"),
                chronology_complete=chronology_complete and not bag_deferred,
                manager_edit_version=int(prior.get("manager_edit_version") or 0),
            )
        ):
            # Keep prior confirmed completion while chronology is incomplete
            # or this bag's merge was projection-deferred.
            b = dict(b)
            b["effective_status"] = prior.get("effective_status") or "completed"
            b["canonical_completion_status"] = (
                prior.get("canonical_completion_status") or b.get("canonical_completion_status")
            )
            b["canonical_completion_timestamp"] = (
                prior.get("canonical_completion_timestamp")
                or b.get("canonical_completion_timestamp")
            )
            b["canonical_completion_employee"] = (
                prior.get("canonical_completion_employee")
                or b.get("canonical_completion_employee")
            )
            b["review_reason_codes"] = prior.get("review_reason_codes") or []
        proj = project_productivity_fields_for_day_bag(b)
        cursor.execute(
            upsert_sql,
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
    # Never delete manager-locked rows even if a buggy rebuild omits them.
    keep_ids = sorted({normalize_bag_id(b.get("bag_id")) for b in bags if b.get("bag_id")})
    if keep_ids:
        placeholders = ",".join(["%s"] * len(keep_ids))
        cursor.execute(
            f"""
            DELETE FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND bag_id NOT IN ({placeholders})
              AND manager_edit_version = 0
            """,
            (int(organization_id), shift_date_et, *keep_ids),
        )
    else:
        # Persist intentionally has zero bag rows (e.g. terminal fail-closed).
        # Still remove unmanaged orphans so historical contamination cannot linger.
        cursor.execute(
            """
            DELETE FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND manager_edit_version = 0
            """,
            (int(organization_id), shift_date_et),
        )
    try:
        from backend.rinse_wf_service_cycle_compat import wf_terminal_ineligible_bag_ids

        persisted_wf_ids = sorted(
            {
                normalize_bag_id(r.get("bag_id"))
                for r in (load_day_bags(cursor, organization_id, shift_date_et) or [])
                if normalize_bag_id(r.get("bag_id"))
                and str(r.get("service_type") or "WF").upper() == "WF"
            }
        )
        terminal_drop = sorted(
            wf_terminal_ineligible_bag_ids(
                cursor, int(organization_id), shift_date_et, persisted_wf_ids
            )
        )
        if terminal_drop:
            drop_ph = ",".join(["%s"] * len(terminal_drop))
            cursor.execute(
                f"""
                DELETE FROM rinse_shift_monitor_day_bags
                WHERE organization_id = %s
                  AND shift_date_et = %s
                  AND UPPER(COALESCE(service_type, 'WF')) = 'WF'
                  AND bag_id IN ({drop_ph})
                """,
                (int(organization_id), shift_date_et, *terminal_drop),
            )
    except Exception:
        logger.exception(
            "WF terminal membership purge failed during persist org=%s date=%s",
            organization_id,
            shift_date_et,
        )

    _sync_day_header_from_persisted_bags(
        cursor,
        organization_id,
        shift_date_et,
        summary=summary,
        workload=workload,
        next_status=next_status,
        opened_at=opened_at,
        now=now,
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
    if s in ("carried_forward",):
        return "carried_forward"
    if s in ("stale", "unfinished_at_close", "stale_for_day"):
        return "unfinished_at_close"
    if s == OUTCOME_PENDING or s == "pending" or "pending" in s:
        return "pending"
    if s in ("excluded", "exclude"):
        return "excluded"
    return None


_STATUS_BAG_ID_KEYS = (
    "completed",
    "pending",
    "review_required",
    "carried_forward",
    "unfinished_at_close",
    "disappeared_without_completion",
)

_SEGMENT_FILTERS: dict[str, tuple[str | None, str | None]] = {
    "all": (None, None),
    "wf": ("WF", None),
    "hd": ("HD", None),
    "rush": (None, "RUSH"),
    "non_rush": (None, "NON_RUSH"),
    "wf_rush": ("WF", "RUSH"),
    "wf_non_rush": ("WF", "NON_RUSH"),
    "hd_rush": ("HD", "RUSH"),
    "hd_non_rush": ("HD", "NON_RUSH"),
}


def _unique_bag_id_list(vals: Any) -> list[str]:
    return sorted(
        {
            normalize_bag_id(x)
            for x in list(vals or [])
            if normalize_bag_id(x)
        }
    )


def _rush_norm(rush: Any) -> str:
    v = str(rush or "").strip().lower()
    if not v:
        return ""
    if "non" in v:
        return "NON_RUSH"
    if "rush" in v or v in ("1", "true", "yes", "y"):
        return "RUSH"
    return "NON_RUSH"


def _service_norm(service: Any) -> str:
    return str(service or "").strip().upper()


def _segment_filters(name: str) -> tuple[str | None, str | None]:
    return _SEGMENT_FILTERS.get(str(name or "").strip().lower(), (None, None))


def _matches_segment_filters(
    meta: Mapping[str, Any],
    *,
    service: str | None,
    rush: str | None,
) -> bool:
    if service:
        svc = _service_norm(meta.get("service_type"))
        # Missing service on a day-bag row must not drop the bag from WF/HD sync.
        if svc and svc != service:
            return False
    if rush:
        r = _rush_norm(meta.get("rush_status") or meta.get("rush_flag"))
        if r and r != rush:
            return False
    return True


def _recalc_status_counts_from_ids(seg: Mapping[str, Any]) -> dict[str, Any]:
    """Set completed/pending/review/carried counts from unique bag_ids lists."""
    out = dict(seg or {})
    bag_ids = dict(out.get("bag_ids") or {})
    completed = _unique_bag_id_list(bag_ids.get("completed"))
    pending = _unique_bag_id_list(bag_ids.get("pending"))
    review = _unique_bag_id_list(bag_ids.get("review_required"))
    carried = _unique_bag_id_list(bag_ids.get("carried_forward"))
    unfinished = _unique_bag_id_list(bag_ids.get("unfinished_at_close"))
    bag_ids["completed"] = completed
    bag_ids["pending"] = pending
    bag_ids["review_required"] = review
    bag_ids["carried_forward"] = carried
    bag_ids["unfinished_at_close"] = unfinished
    bag_ids["disappeared_without_completion"] = list(review)
    out["bag_ids"] = bag_ids
    out["completed"] = len(completed)
    out["pending"] = len(pending)
    out["carried_forward"] = len(carried)
    out["unfinished_at_close"] = len(unfinished)
    out["exceptions"] = {
        **dict(out.get("exceptions") or {}),
        "review_required": len(review),
        "carried_forward": len(carried),
        "unfinished_at_close": len(unfinished),
        "disappeared_without_completion": len(review),
        "total": len(review),
    }
    return out


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
    """Move one bag between status lists. Does not require prior list membership."""
    out = dict(seg or {})
    bid_n = normalize_bag_id(bid)
    if not bid_n:
        return out
    bag_ids = dict(out.get("bag_ids") or {})

    if old_bucket and old_bucket != new_bucket:
        bag_ids[old_bucket] = [
            x
            for x in list(bag_ids.get(old_bucket) or [])
            if normalize_bag_id(x) != bid_n
        ]
        if old_bucket == "review_required":
            bag_ids["disappeared_without_completion"] = [
                x
                for x in list(bag_ids.get("disappeared_without_completion") or [])
                if normalize_bag_id(x) != bid_n
            ]

    if new_bucket and new_bucket != "excluded":
        for key in _STATUS_BAG_ID_KEYS:
            if key == new_bucket:
                continue
            if key == "disappeared_without_completion" and new_bucket == "review_required":
                continue
            bag_ids[key] = [
                x
                for x in list(bag_ids.get(key) or [])
                if normalize_bag_id(x) != bid_n
            ]
        bag_ids[new_bucket] = _unique_bag_id_list(
            list(bag_ids.get(new_bucket) or []) + [bid_n]
        )
        if new_bucket == "review_required":
            bag_ids["disappeared_without_completion"] = list(bag_ids[new_bucket])

    out["bag_ids"] = bag_ids
    return _recalc_status_counts_from_ids(out)


def _strip_bag_from_review_segments(
    segments: Mapping[str, Any],
    bid: str,
    *,
    new_bucket: str | None,
) -> dict[str, Any]:
    """Remove bag from review_required and place in new_bucket (atomic per segment)."""
    out: dict[str, Any] = {}
    for name, seg in dict(segments or {}).items():
        if new_bucket and new_bucket not in (None, "excluded", "review_required"):
            out[name] = _move_bag_in_segment_bucket(
                seg, bid, old_bucket="review_required", new_bucket=new_bucket
            )
        else:
            out[name] = _move_bag_in_segment_bucket(
                seg, bid, old_bucket="review_required", new_bucket=None
            )
    return out


def _load_day_bag_status_projection(
    cursor, organization_id: int, shift_date_et: date
) -> dict[str, dict[str, Any]]:
    """bag_id → status projection fields for headline sync."""
    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT bag_id, effective_status, service_type, rush_status,
               disposition, canonical_completion_status, bag_snapshot_json
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (int(organization_id), shift_date_et),
    )
    raw = cursor.fetchall()
    if not isinstance(raw, (list, tuple)):
        raw = []
    out: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        snap = _json_load(row.get("bag_snapshot_json")) or {}
        out[bid] = {
            "effective_status": row.get("effective_status"),
            "service_type": row.get("service_type"),
            "rush_status": row.get("rush_status"),
            "disposition": row.get("disposition"),
            "canonical_completion_status": row.get("canonical_completion_status"),
            "keep_completed_while_in_review": bool(
                snap.get("keep_completed_while_in_review")
            ),
        }
    return out


def _apply_day_bag_statuses_to_headline(
    headline: Mapping[str, Any],
    status_by_bag: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild status bag_ids/counts from persisted day-bag effective_status.

    Day-bag ``effective_status`` is authoritative. Headline JSON is only a
    derived projection.

    Hard invariant: workload == completed + pending + review
    (+ carried_forward / unfinished_at_close on closed days). All four
    headline counts come from the same classified bag-ID set — unbucketed
    statuses (e.g. disappeared_prior_open_exception) never inflate workload.
    """
    out = dict(headline or {})
    segments = dict(out.get("segments") or {})
    if not segments:
        segments = {"all": {}, "wf": {}, "hd": {}}

    _ops_buckets = (
        "completed",
        "pending",
        "review_required",
        "carried_forward",
        "unfinished_at_close",
    )

    for name, seg in list(segments.items()):
        seg_out = dict(seg or {})
        bag_ids = dict(seg_out.get("bag_ids") or {})
        new_today = _unique_bag_id_list(bag_ids.get("new_today"))
        carryover = _unique_bag_id_list(bag_ids.get("carryover"))

        svc_filter, rush_filter = _segment_filters(name)
        prior_bucket: dict[str, str] = {}
        for key in _ops_buckets:
            for bid in _unique_bag_id_list(bag_ids.get(key)):
                prior_bucket[bid] = key

        # Authoritative membership for status projection: new_today + carryover.
        # Do not expand membership from stale status ID lists (that desyncs total).
        if new_today or carryover:
            members = set(new_today) | set(carryover)
        else:
            members = {
                bid
                for bid, meta in status_by_bag.items()
                if _matches_segment_filters(
                    meta, service=svc_filter, rush=rush_filter
                )
                and _headline_bucket_for_status(meta.get("effective_status"))
                in _ops_buckets
            }
        if (new_today or carryover) and (svc_filter or rush_filter):
            filtered = set()
            for bid in members:
                meta = status_by_bag.get(bid)
                if meta is None:
                    filtered.add(bid)
                    continue
                if _matches_segment_filters(
                    meta, service=svc_filter, rush=rush_filter
                ):
                    filtered.add(bid)
            members = filtered

        completed: list[str] = []
        pending: list[str] = []
        review: list[str] = []
        carried: list[str] = []
        unfinished: list[str] = []
        for bid in sorted(members):
            meta = status_by_bag.get(bid)
            if meta:
                bucket = _headline_bucket_for_status(meta.get("effective_status"))
            else:
                bucket = prior_bucket.get(bid)
            if bucket == "completed":
                completed.append(bid)
            elif bucket == "pending":
                pending.append(bid)
            elif bucket == "review_required":
                review.append(bid)
            elif bucket == "carried_forward":
                carried.append(bid)
            elif bucket == "unfinished_at_close":
                unfinished.append(bid)

        # Same canonical bag-ID set for membership + status + workload totals.
        classified = set(completed) | set(pending) | set(review) | set(carried) | set(
            unfinished
        )
        new_today = [b for b in new_today if b in classified]
        carryover = [b for b in carryover if b in classified]
        # Classified bags missing from membership lists still belong in new_today.
        listed = set(new_today) | set(carryover)
        for bid in sorted(classified - listed):
            new_today.append(bid)

        bag_ids["new_today"] = _unique_bag_id_list(new_today)
        bag_ids["carryover"] = _unique_bag_id_list(carryover)
        bag_ids["completed"] = completed
        bag_ids["pending"] = pending
        bag_ids["review_required"] = review
        bag_ids["carried_forward"] = carried
        bag_ids["unfinished_at_close"] = unfinished
        bag_ids["disappeared_without_completion"] = list(review)
        seg_out["bag_ids"] = bag_ids
        seg_out = _recalc_status_counts_from_ids(seg_out)
        total_i = (
            int(seg_out.get("completed") or 0)
            + int(seg_out.get("pending") or 0)
            + int(seg_out.get("carried_forward") or 0)
            + int(seg_out.get("unfinished_at_close") or 0)
            + int((seg_out.get("exceptions") or {}).get("review_required") or 0)
        )
        seg_out["new_today"] = len(bag_ids["new_today"])
        seg_out["carryover"] = len(bag_ids["carryover"])
        seg_out["total_workload"] = total_i
        seg_out["active_workload"] = total_i
        seg_out["total_operational_orders"] = total_i
        segments[name] = seg_out

    out["segments"] = segments
    all_seg = dict(segments.get("all") or {})
    out["completed"] = all_seg.get("completed", out.get("completed"))
    out["pending"] = all_seg.get("pending", out.get("pending"))
    out["carried_forward"] = all_seg.get("carried_forward", out.get("carried_forward"))
    out["exceptions"] = dict(
        all_seg.get("exceptions") or out.get("exceptions") or {}
    )
    if all_seg.get("total_workload") is not None:
        out["total_workload"] = all_seg.get("total_workload")
        out["active_workload"] = all_seg.get(
            "active_workload", all_seg.get("total_workload")
        )
    # Canonical day-level status counts (projection of day-bag effective_status).
    out["completed_count"] = int(out.get("completed") or 0)
    out["pending_count"] = int(out.get("pending") or 0)
    out["carried_forward_count"] = int(out.get("carried_forward") or 0)
    out["review_required_count"] = int(
        (out.get("exceptions") or {}).get("review_required") or 0
    )
    return out


def count_day_bag_status_buckets(
    status_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    member_ids: set[str] | None = None,
) -> dict[str, int]:
    """Count authoritative day-bag statuses (optionally scoped to membership)."""
    completed = pending = review = unfinished = carried = 0
    for bid, meta in (status_by_bag or {}).items():
        if member_ids is not None and bid not in member_ids:
            continue
        bucket = _headline_bucket_for_status((meta or {}).get("effective_status"))
        if bucket == "completed":
            completed += 1
        elif bucket == "pending":
            pending += 1
        elif bucket == "review_required":
            review += 1
        elif bucket == "carried_forward":
            carried += 1
        elif bucket == "unfinished_at_close":
            unfinished += 1
    return {
        "completed_count": completed,
        "pending_count": pending,
        "review_required_count": review,
        "carried_forward_count": carried,
        "unfinished_at_close_count": unfinished,
        # Open: completed+pending+review. Closed: completed+review+carried(+legacy stale).
        "status_total": completed + pending + review + carried + unfinished,
    }


def verify_headline_day_bag_status_invariant(
    headline: Mapping[str, Any],
    status_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    context: str = "",
) -> dict[str, Any]:
    """Invariant: headline status counts == day-bag effective_status counts.

    For a refreshed Shift Monitor day (all-segment / day membership):

      review_required_count = COUNT(day_bags WHERE effective_status = review_required)
      completed_count       = COUNT(day_bags WHERE effective_status = completed)
      pending_count         = COUNT(day_bags WHERE effective_status = pending)
      total_workload        = review_required + completed + pending

    (Excluded bags are outside the operational status total.)

    Mismatches are logged clearly and returned — never silently swallowed.
    """
    all_seg = ((headline or {}).get("segments") or {}).get("all") or {}
    bags = all_seg.get("bag_ids") or {}
    members = set(_unique_bag_id_list(bags.get("new_today"))) | set(
        _unique_bag_id_list(bags.get("carryover"))
    )
    if not members:
        # Fall back to union of status lists / full day-bag projection.
        for key in ("completed", "pending", "review_required"):
            members.update(_unique_bag_id_list(bags.get(key)))
        if not members:
            members = {
                bid
                for bid, meta in (status_by_bag or {}).items()
                if _headline_bucket_for_status((meta or {}).get("effective_status"))
                in ("completed", "pending", "review_required")
            }

    expected = count_day_bag_status_buckets(status_by_bag, member_ids=members)
    # Membership bags missing from the projection still count via headline prior buckets.
    for bid in members:
        if bid in status_by_bag:
            continue
        if bid in _unique_bag_id_list(bags.get("completed")):
            expected["completed_count"] += 1
            expected["status_total"] += 1
        elif bid in _unique_bag_id_list(bags.get("pending")):
            expected["pending_count"] += 1
            expected["status_total"] += 1
        elif bid in _unique_bag_id_list(bags.get("review_required")):
            expected["review_required_count"] += 1
            expected["status_total"] += 1
    got_completed = int(
        headline.get("completed_count")
        if headline.get("completed_count") is not None
        else headline.get("completed")
        if headline.get("completed") is not None
        else all_seg.get("completed")
        or 0
    )
    got_pending = int(
        headline.get("pending_count")
        if headline.get("pending_count") is not None
        else headline.get("pending")
        if headline.get("pending") is not None
        else all_seg.get("pending")
        or 0
    )
    got_review = int(
        headline.get("review_required_count")
        if headline.get("review_required_count") is not None
        else (headline.get("exceptions") or {}).get("review_required")
        if (headline.get("exceptions") or {}).get("review_required") is not None
        else (all_seg.get("exceptions") or {}).get("review_required")
        or 0
    )
    got_total = headline.get("total_workload")
    if got_total is None:
        got_total = all_seg.get("total_workload")
    if got_total is None:
        got_total = all_seg.get("active_workload")
    try:
        got_total_i = int(got_total) if got_total is not None else None
    except (TypeError, ValueError):
        got_total_i = None

    # Unique-ID set lengths must match numeric counts.
    id_completed = len(_unique_bag_id_list(bags.get("completed")))
    id_pending = len(_unique_bag_id_list(bags.get("pending")))
    id_review = len(_unique_bag_id_list(bags.get("review_required")))

    mismatches: list[str] = []
    if got_completed != expected["completed_count"]:
        mismatches.append(
            f"completed_count headline={got_completed} day_bags={expected['completed_count']}"
        )
    if got_pending != expected["pending_count"]:
        mismatches.append(
            f"pending_count headline={got_pending} day_bags={expected['pending_count']}"
        )
    if got_review != expected["review_required_count"]:
        mismatches.append(
            f"review_required_count headline={got_review} day_bags={expected['review_required_count']}"
        )
    if got_completed != id_completed or got_pending != id_pending or got_review != id_review:
        mismatches.append(
            "status_counts_ne_unique_id_lens "
            f"counts=({got_completed},{got_pending},{got_review}) "
            f"ids=({id_completed},{id_pending},{id_review})"
        )
    status_sum = got_completed + got_pending + got_review
    if got_total_i is not None and got_total_i != status_sum:
        mismatches.append(
            f"total_workload={got_total_i} != completed+pending+review={status_sum}"
        )

    ok = not mismatches
    result = {
        "ok": ok,
        "context": context or None,
        "expected": expected,
        "headline": {
            "completed_count": got_completed,
            "pending_count": got_pending,
            "review_required_count": got_review,
            "total_workload": got_total_i,
        },
        "mismatches": mismatches,
    }
    if not ok:
        logger.error(
            "headline_day_bag_status_invariant_mismatch context=%s mismatches=%s expected=%s headline=%s",
            context,
            mismatches,
            expected,
            result["headline"],
        )
    return result


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
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    """Fast post-edit sync: one day_bag + headline counts (no full day rebuild).

    Must run only after the manager edit lock check has already succeeded.
    Does not bump ``manager_edit_version`` / ``updated_at``.

    Reprojects ``headline.specialty_metrics`` from current membership + live
    specialty classification inputs so bag status and Specialty cards stay
    internally consistent after the edit.

    ``move_to_review`` / send-back preserves operational completion facts
    (disposition + canonical completion timestamp/employee) when the bag
    was already completed — only management-review membership changes.
    """
    from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW
    from backend.rinse_manual_review import (
        resolve_send_back_reasons,
        stamp_manual_review_resolved,
        stamp_manual_review_sent_back,
    )

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
        from backend.management_rinse_wf_review import strip_specialty_only_resolved_reasons
        from backend.rinse_bulk_workitems import load_bag_bulk_lines, load_bulk_resolutions

        bulk_lines = load_bag_bulk_lines(cursor, organization_id, shift_date_et, [bid]).get(bid) or []
        bulk_res = load_bulk_resolutions(cursor, organization_id, shift_date_et, [bid]).get(bid)
        effective_post = (
            post_weight_lbs
            if post_weight_lbs is not None
            else day_row.get("post_weight_lbs")
        )
        reasons = strip_specialty_only_resolved_reasons(
            reasons,
            bulk_lines=bulk_lines,
            bulk_resolution=bulk_res,
            post_weight_lbs=effective_post,
            bulk_cleared=True,
        )

    snap = dict(day_row.get("bag_snapshot") or {})
    prior_canon = str(day_row.get("canonical_completion_status") or "").strip() or None
    prior_disposition = day_row.get("disposition")
    was_operationally_completed = (
        prev_status in (OUTCOME_COMPLETED, "completed")
        or str(prior_disposition or "").upper() == DISPOSITION_COMPLETED
        or (prior_canon and ("completed" in prior_canon.lower()))
        or bool(day_row.get("canonical_completion_timestamp"))
        or bool(snap.get("completion_at"))
    )

    outcome = str(outcome_action or "").strip().lower() or None
    stamp_resolved = False
    stamp_sent_back = False
    reasons_for_stamp: list[str] | None = None
    if outcome == "mark_completed":
        # Confirm Completed must not fake-clear bulk review — rebuild would put it
        # back unless items/no-charge were saved (bulk_cleared).
        pending_bulk = (
            REASON_WF_BULK_WORKITEM_REVIEW in {str(r) for r in reasons}
            and not bulk_cleared
        )
        if pending_bulk:
            new_status = OUTCOME_REVIEW_REQUIRED
            reasons = [REASON_WF_BULK_WORKITEM_REVIEW]
            disposition = day_row.get("disposition") or DISPOSITION_COMPLETED
            canon_status = prior_canon or OUTCOME_COMPLETED
        else:
            new_status = OUTCOME_COMPLETED
            # Capture prior review reasons before clearing for Manually Reviewed.
            if prev_status == OUTCOME_REVIEW_REQUIRED or reasons:
                stamp_resolved = True
                reasons_for_stamp = list(reasons)
            reasons = []
            disposition = DISPOSITION_COMPLETED
            canon_status = OUTCOME_COMPLETED
    elif outcome == "return_pending":
        new_status = OUTCOME_PENDING
        reasons = []
        disposition = DISPOSITION_CARRY_FORWARD
        canon_status = OUTCOME_PENDING
    elif outcome == "exclude":
        new_status = "excluded"
        reasons = []
        disposition = DISPOSITION_EXCLUDE
        canon_status = "excluded"
    elif outcome == "move_to_review":
        new_status = OUTCOME_REVIEW_REQUIRED
        reasons = resolve_send_back_reasons(
            snap=snap,
            previous_reason_codes=reasons,
            explicit_reason_code=reason_code,
        )
        disposition = prior_disposition or (
            DISPOSITION_COMPLETED if was_operationally_completed else day_row.get("disposition")
        )
        # Keep operational completion status when bag was already completed.
        if was_operationally_completed:
            canon_status = prior_canon or OUTCOME_COMPLETED
        else:
            canon_status = OUTCOME_REVIEW_REQUIRED
        stamp_sent_back = True
    else:
        if reasons:
            new_status = OUTCOME_REVIEW_REQUIRED
            disposition = day_row.get("disposition")
            canon_status = (
                prior_canon or OUTCOME_COMPLETED
                if was_operationally_completed
                else OUTCOME_REVIEW_REQUIRED
            )
        else:
            # Bulk/fields-only save cleared the last review reason.
            canon = str(day_row.get("canonical_completion_status") or "").lower()
            if completion_at or canon in (OUTCOME_COMPLETED, "completed") or "completed" in canon:
                new_status = OUTCOME_COMPLETED
                disposition = DISPOSITION_COMPLETED
                canon_status = OUTCOME_COMPLETED
                if prev_status == OUTCOME_REVIEW_REQUIRED:
                    stamp_resolved = True
                    reasons_for_stamp = list(
                        previous_reason_codes
                        if previous_reason_codes is not None
                        else (day_row.get("review_reason_codes") or [])
                    )
            else:
                new_status = OUTCOME_PENDING
                disposition = DISPOSITION_CARRY_FORWARD
                canon_status = OUTCOME_PENDING

    if stamp_resolved:
        prior_for_stamp = list(reasons_for_stamp) if reasons_for_stamp is not None else list(
            previous_reason_codes
            if previous_reason_codes is not None
            else (day_row.get("review_reason_codes") or [])
        )
        snap = stamp_manual_review_resolved(
            snap,
            prior_reason_codes=prior_for_stamp,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
    if stamp_sent_back:
        snap = stamp_manual_review_sent_back(
            snap,
            reason_codes=reasons,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        if was_operationally_completed:
            snap["keep_completed_while_in_review"] = True
    if stamp_resolved or new_status == OUTCOME_COMPLETED:
        snap.pop("keep_completed_while_in_review", None)

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
    # Productivity / completion credit still follows operational completion when
    # the bag is only in management review (send-back), not unfinished.
    productivity_status = (
        OUTCOME_COMPLETED
        if (new_status == OUTCOME_REVIEW_REQUIRED and was_operationally_completed)
        else new_status
    )
    try:
        from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

        proj = project_productivity_fields_for_day_bag(
            {
                "effective_status": productivity_status,
                "service_type": day_row.get("service_type"),
                "canonical_completion_employee": completed_by
                if completed_by is not None
                else day_row.get("canonical_completion_employee"),
                "canonical_completion_timestamp": completion_at
                if completion_at is not None
                else day_row.get("canonical_completion_timestamp"),
                "weight_lbs": weight_lbs,
                "pre_weight_lbs": pre_weight_lbs
                if pre_weight_lbs is not None
                else day_row.get("pre_weight_lbs"),
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
            canon_status,
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

    # Patch headline counts from persisted day-bag effective_status (same source
    # as drawer membership). Do not depend on prior bag_ids list membership.
    specialty_reprojected = False
    day = get_day_record(cursor, organization_id, shift_date_et)
    if day:
        try:
            headline = dict(day.get("headline") or {})
            status_by_bag = _load_day_bag_status_projection(
                cursor, organization_id, shift_date_et
            )
            # Ensure the just-updated row is visible even if the SELECT is stale
            # on unusual drivers (same cursor should see it).
            status_by_bag[bid] = {
                **dict(status_by_bag.get(bid) or {}),
                "effective_status": new_status,
                "service_type": (status_by_bag.get(bid) or {}).get("service_type")
                or day_row.get("service_type"),
                "rush_status": (status_by_bag.get(bid) or {}).get("rush_status")
                or day_row.get("rush_status"),
                "disposition": disposition or day_row.get("disposition"),
                "canonical_completion_status": canon_status,
                "keep_completed_while_in_review": bool(
                    snap.get("keep_completed_while_in_review")
                ),
            }
            old_bucket = _headline_bucket_for_status(prev_status)
            new_bucket = _headline_bucket_for_status(new_status)
            # Incremental move keeps ID lists correct even when status projection
            # is empty (brand-new day); then full sync reconciles from day bags.
            segments = dict(headline.get("segments") or {})
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
            headline["segments"] = segments
            headline = _apply_day_bag_statuses_to_headline(headline, status_by_bag)
            invariant = verify_headline_day_bag_status_invariant(
                headline,
                status_by_bag,
                context=(
                    f"org={organization_id} date={shift_date_et} bag={bid} "
                    f"{prev_status}->{new_status}"
                ),
            )
            if not invariant.get("ok"):
                # Do not silently accept a broken projection.
                raise RuntimeError(
                    "headline_day_bag_status_invariant_mismatch: "
                    + "; ".join(invariant.get("mismatches") or [])
                )

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
            review_by_reason = dict(headline.get("review_by_reason") or {})
            if new_bucket != "review_required":
                cleaned = {}
                for code, ids in review_by_reason.items():
                    kept = [
                        x for x in list(ids or []) if normalize_bag_id(x) != bid
                    ]
                    if kept:
                        cleaned[code] = kept
                review_by_reason = cleaned
                headline["review_by_reason"] = review_by_reason
            meta = dict(day.get("workload_meta") or {})
            meta["review_reasons_by_bag"] = reasons_by_bag
            if "review_by_reason" in headline:
                meta["review_by_reason"] = review_by_reason
            meta["headline_status_synced_from_day_bags"] = True
            try:
                headline = _reproject_specialty_metrics_on_headline(
                    cursor, organization_id, shift_date_et, headline
                )
                specialty_reprojected = True
                meta["specialty_metrics_reprojected"] = True
            except Exception:
                logger.exception(
                    "specialty_reproject_failed org=%s date=%s bag=%s",
                    organization_id,
                    shift_date_et,
                    bid,
                )
                # Drop the frozen pack so the next read rebuilds specialty only
                # (membership / completion stay as just patched).
                headline.pop("specialty_metrics", None)
                for _k in (
                    "comforter_order_count",
                    "bath_mat_order_count",
                    "rejected_order_count",
                    "split_order_count",
                ):
                    headline.pop(_k, None)
                meta["specialty_metrics_reprojected"] = False
            review_n = int(
                (headline.get("exceptions") or {}).get("review_required") or 0
            )
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
        except Exception as exc:
            logger.exception(
                "headline_patch_failed org=%s date=%s bag=%s prev=%s new=%s",
                organization_id,
                shift_date_et,
                bid,
                prev_status,
                new_status,
            )
            # Day-bag row already updated; preserve that write. Surface headline
            # failure explicitly — do not swallow.
            return {
                "ok": True,
                "bag_id": bid,
                "previous_effective_status": prev_status,
                "effective_status": new_status,
                "review_reason_codes": reasons,
                "headline_patched": False,
                "headline_patch_error": "headline_patch_failed",
                "detail": str(exc),
            }

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
        "headline_patched": bool(day),
        "specialty_reprojected": specialty_reprojected,
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
    *,
    status_only: bool = False,
) -> list[dict[str, Any]]:
    """Load only the requested day-bag rows (drawer page / single-bag detail)."""
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return []
    ensure_shift_monitor_day_tables(cursor)
    placeholders = ",".join(["%s"] * len(ids))
    select_sql = (
        "bag_id, effective_status"
        if status_only
        else "*"
    )
    cursor.execute(
        f"""
        SELECT {select_sql}
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


def _reproject_specialty_metrics_on_headline(
    cursor,
    organization_id: int,
    shift_date_et: date,
    headline: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute specialty packs onto a headline after a manager bag edit.

    Uses current headline membership plus live bulk-line / rejected / split
    inputs. Does not rebuild bag membership or completion.
    """
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

    return attach_specialty_metrics_to_summary(
        cursor, organization_id, shift_date_et, dict(headline or {})
    )


def _ensure_specialty_metrics(
    cursor,
    organization_id: int,
    selected_date_et: date,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach specialty metrics when missing (read path). Does not alter WF counts."""
    out = dict(summary or {})
    packs = out.get("specialty_metrics")
    if isinstance(packs, dict) and packs:
        all_pack = packs.get("all") or {}
        # Rebuild when older snapshots lack Split Orders or use pre-create-issue
        # rejected classification (v1 registry-based).
        try:
            from backend.rinse_hd_day_metrics import CLASSIFICATION_VERSION

            ver = int(all_pack.get("classification_version") or 0)
        except Exception:
            ver = 0
        if isinstance(all_pack.get("split_orders"), dict) and ver >= CLASSIFICATION_VERSION:
            return out
    try:
        from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

        return attach_specialty_metrics_to_summary(
            cursor, organization_id, selected_date_et, out
        )
    except Exception:
        return out


def summary_from_day_record(
    day: Mapping[str, Any],
    *,
    cursor=None,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    headline = day.get("headline")
    if isinstance(headline, dict) and headline:
        out = dict(headline)
        out["shift_day_status"] = day.get("status")
        meta = day.get("workload_meta") if isinstance(day.get("workload_meta"), dict) else {}
        step1_refresh = (
            meta.get("step1_refresh") if isinstance(meta.get("step1_refresh"), dict) else {}
        )
        # Prefer explicit Step-1 refresh finish time; fall back to last_sync_at
        # (persist_day_snapshot stamps last_sync_at on every successful rebuild).
        step1_refreshed_at = (
            step1_refresh.get("finished_at")
            or day.get("last_sync_at")
        )
        refresh_status = (
            step1_refresh.get("step1_refresh_status")
            or step1_refresh.get("status")
        )
        refresh_status_u = str(refresh_status or "").upper()
        rebuild_deferred = bool(
            step1_refresh.get("rebuild_deferred")
            or step1_refresh.get("deferred")
            or refresh_status_u == "DEFERRED"
        )
        out["shift_day"] = {
            "status": day.get("status"),
            "opened_at": day.get("opened_at"),
            "last_sync_at": day.get("last_sync_at"),
            "step1_refreshed_at": step1_refreshed_at,
            "step1_refresh_status": refresh_status,
            "step1_refresh_error": step1_refresh.get("error")
            or step1_refresh.get("step1_refresh_error")
            or (step1_refresh.get("reason") if rebuild_deferred else None),
            "step1_refresh_scrape_batch_id": step1_refresh.get("scrape_batch_id")
            or step1_refresh.get("import_batch_id"),
            "step1_refresh_day_bags_rebuilt": step1_refresh.get("day_bags_rebuilt"),
            "step1_refresh_failed": (
                refresh_status_u in ("FAILED", "FAIL", "ERROR")
                or (
                    step1_refresh.get("ok") is False
                    and not rebuild_deferred
                )
            ),
            "rebuild_deferred": rebuild_deferred,
            "last_consistent_snapshot": step1_refresh.get("last_consistent_snapshot"),
            "step1_refresh_message": step1_refresh.get("message"),
            "closed_at": day.get("closed_at"),
            "closed_by_display_name": day.get("closed_by_display_name"),
            "close_reason": day.get("close_reason"),
            "close_override": bool(day.get("close_override")),
            "reopen_count": day.get("reopen_count") or 0,
            "review_required_count": day.get("review_required_count") or 0,
            "read_only": day.get("status") == STATUS_CLOSED,
        }
        # Live ET day only: heal HD carryover in the response without rewriting WF.
        try:
            shift_date = day.get("shift_date_et")
            if isinstance(shift_date, str):
                shift_date = date.fromisoformat(str(shift_date)[:10])
            from backend.rinse_hd_day_presentation import (
                finalize_hd_step1_summary,
                should_apply_hd_presentation_on_read,
            )

            if (
                isinstance(shift_date, date)
                and should_apply_hd_presentation_on_read(
                    selected_date_et=shift_date,
                    today=today_et(),
                    day_status=day.get("status"),
                )
            ):
                org = organization_id
                if org is None:
                    try:
                        org = int(day.get("organization_id")) if day.get("organization_id") is not None else None
                    except Exception:
                        org = None
                out = finalize_hd_step1_summary(
                    out,
                    selected_date_et=shift_date,
                    membership=out.get("membership")
                    if isinstance(out.get("membership"), dict)
                    else None,
                    cursor=cursor,
                    organization_id=org,
                )
        except Exception:
            pass
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
    Today / REOPENED / missing-day rebuild + persist only when ``persist_live=True``
    (scrape / backfill / explicit Stage-B refresh).

    Interactive reads (``persist_live=False``) never run a full live Step-1 rebuild:
    when no valid persisted snapshot exists they return a fast snapshot-unavailable
    payload instead.

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

    today = today_et()
    # Release B: any access to "today" idempotently archives yesterday if still open.
    # Manual close is not required for the new day to begin.
    if selected_date_et == today:
        try:
            from backend.rinse_shift_day_close_archive import (
                ensure_prior_et_day_archived_on_rollover,
            )

            rollover = ensure_prior_et_day_archived_on_rollover(
                cursor, organization_id, today=today
            )
            if rollover and rollover.get("ok"):
                _commit(cursor)
        except Exception:
            logger.exception(
                "release_b_auto_rollover_archive_failed org=%s today=%s",
                organization_id,
                today,
            )

    day = get_day_record(cursor, organization_id, selected_date_et)
    status = (day or {}).get("status")

    def _summary_shell(day_rec: Mapping[str, Any], *, status_value: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        summary = summary_from_day_record(
            day_rec, cursor=cursor, organization_id=organization_id
        )
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
            summary = _ensure_specialty_metrics(
                cursor, organization_id, selected_date_et, summary
            )
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
                summary = _ensure_specialty_metrics(
                    cursor, organization_id, selected_date_et, summary
                )
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
                summary = _ensure_specialty_metrics(
                    cursor, organization_id, selected_date_et, summary
                )
                return wl, summary, day_out

    # Interactive / read-only path: never rebuild when the persisted day is missing.
    # Stage-B scrape / backfill / explicit refresh call with persist_live=True.
    if not persist_live:
        return _snapshot_missing_step1_payload(selected_date_et)

    # Canonical lifecycle: never persist append-only Stage-B membership from this path.
    # Terminal projection + final_wf_day_membership_bag_ids is the only writer.
    try:
        from backend.rinse_wf_service_cycle import is_wf_canonical_lifecycle_enabled
        from backend.rinse_wf_service_cycle_compat import (
            terminal_project_canonical_wf_day_snapshot,
        )

        if is_wf_canonical_lifecycle_enabled(cursor, int(organization_id)):
            terminal_project_canonical_wf_day_snapshot(
                cursor,
                int(organization_id),
                selected_date_et,
                force=True,
            )
            _commit(cursor)
            day = get_day_record(cursor, organization_id, selected_date_et)
            return _summary_shell(day or {}, status_value=str((day or {}).get("status") or STATUS_OPEN))
    except Exception:
        logger.exception(
            "canonical terminal project via build_or_load failed org=%s date=%s",
            organization_id,
            selected_date_et,
        )

    # Legacy / non-canonical reconstruct path (today, or missing prior-day snapshot).
    # On/after VeeWash Jul 23 cutover: append-only membership rebuild (not live presence rewrite).
    wl = _build_step1_workload_for_date(cursor, organization_id, selected_date_et)
    summary = build_step1_headline_summary(
        wl, selected_date_et=selected_date_et, activation_date=activation
    )
    # HD-only post-process: no prior-day carryover; same-day HD admits allowed. WF untouched.
    from backend.rinse_hd_day_presentation import finalize_hd_step1_summary
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")
    summary = finalize_hd_step1_summary(
        summary,
        selected_date_et=selected_date_et,
        membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
        cursor=cursor,
        organization_id=organization_id,
    )
    summary = attach_specialty_metrics_to_summary(
        cursor, organization_id, selected_date_et, summary
    )

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
        summary = summary_from_day_record(
            day, cursor=cursor, organization_id=organization_id
        ) or summary
    else:
        summary["shift_day"] = {
            "status": next_status,
            "read_only": False,
            "review_required_count": review_n,
        }
        summary["shift_day_status"] = next_status
    return wl, summary, day or {"status": next_status, "shift_date_et": selected_date_et}


CLOSE_NOT_READY_ERROR = "shift_not_ready_to_close"
CLOSE_NOT_READY_MESSAGE = (
    "Complete or review all admitted orders before closing the shift."
)
HD_CLOSE_REVIEW_REQUIRED_MESSAGE = (
    "HD batch cannot be closed while orders require review."
)

# Release B: close archives unfinished work (pending/review → stale). The legacy
# "shift_not_ready_to_close" gate remains available for diagnostics via
# validate_close(), but close_shift_day no longer blocks on unresolved rows.


def _segment_count(seg: Mapping[str, Any] | None, key: str) -> int:
    s = seg or {}
    if key == "review_required":
        return int((s.get("exceptions") or {}).get("review_required") or s.get("review_required") or 0)
    return int(s.get(key) or 0)


def _count_hd_partially_recorded(
    cursor,
    organization_id: int,
    shift_date_et: date,
    hd_bag_ids: set[str],
) -> int:
    """Count admitted HD bags with PARTIALLY_RECORDED production facts."""
    if not cursor or not hd_bag_ids:
        return 0
    try:
        from backend.daily_operations_hd import STATUS_PARTIALLY_RECORDED, ensure_hd_production_tables
        from backend.ta_helpers import table_exists

        ensure_hd_production_tables(cursor)
        if not table_exists(cursor, "hd_day_bag_production"):
            return 0
        ids = sorted(hd_bag_ids)
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id
            FROM hd_day_bag_production
            WHERE organization_id = %s
              AND operations_date_et = %s
              AND status = %s
              AND bag_id IN ({placeholders})
            """,
            (int(organization_id), shift_date_et, STATUS_PARTIALLY_RECORDED, *ids),
        )
        return len(
            {
                normalize_bag_id(r.get("bag_id"))
                for r in (cursor.fetchall() or [])
                if isinstance(r, dict) and normalize_bag_id(r.get("bag_id"))
            }
        )
    except Exception:
        return 0


def compute_close_blocking_counts(
    summary: Mapping[str, Any],
    *,
    cursor=None,
    organization_id: int | None = None,
    shift_date_et: date | None = None,
    day_bags: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authoritative close-gate counts.

    Close is allowed only when every admitted order is COMPLETED or approved
    EXCLUDED, and all pending / review / partial / unresolved counts are zero:

      total_admitted_workload == completed + approved_excluded
      pending = review_required = partially_recorded = unresolved_exceptions = 0
    """
    segs = summary.get("segments") or {}
    all_seg = segs.get("all") or {}
    wf = segs.get("wf") or {}
    hd = segs.get("hd") or {}

    completed = 0
    approved_excluded = 0
    wf_pending = 0
    wf_review_required = 0
    hd_review_required = 0
    hd_pending_members = 0
    other_unresolved = 0
    hd_member_ids: set[str] = set()

    if day_bags is not None:
        for bag in day_bags:
            bid = normalize_bag_id(bag.get("bag_id"))
            if not bid:
                continue
            svc = str(bag.get("service_type") or "").strip().upper()
            eff = str(bag.get("effective_status") or "").strip().lower()
            if svc == "HD":
                hd_member_ids.add(bid)
            if eff in ("excluded", "exclude"):
                approved_excluded += 1
                continue
            if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
                completed += 1
                continue
            if eff == OUTCOME_PENDING or "pending" in eff:
                if svc == "WF":
                    wf_pending += 1
                elif svc == "HD":
                    # HD members without workitems-added stay pending members;
                    # they do not block close (only Review Required does).
                    hd_pending_members += 1
                else:
                    other_unresolved += 1
                continue
            if eff == OUTCOME_REVIEW_REQUIRED or eff == "review_required":
                if svc == "WF":
                    wf_review_required += 1
                elif svc == "HD":
                    hd_review_required += 1
                else:
                    other_unresolved += 1
                continue
            # Unknown / unresolved exception status on an admitted day bag.
            other_unresolved += 1
    else:
        # Headline-only path (status bar). Prefer segment counts.
        completed = _segment_count(all_seg, "completed") or int(summary.get("completed") or 0)
        approved_excluded = int(
            all_seg.get("excluded")
            or len(((all_seg.get("bag_ids") or {}).get("excluded") or []))
            or 0
        )
        wf_pending = _segment_count(wf, "pending")
        wf_review_required = _segment_count(wf, "review_required")
        # HD pending members are not Review Required and do not block close.
        hd_review_required = _segment_count(hd, "review_required")
        hd_pending_members = _segment_count(hd, "pending")
        # Bags listed under all.review but not attributed to WF/HD.
        all_review = _segment_count(all_seg, "review_required") or int(
            (summary.get("exceptions") or {}).get("review_required") or 0
        )
        attributed_review = wf_review_required + hd_review_required
        if all_review > attributed_review:
            other_unresolved += all_review - attributed_review
        for bid in (hd.get("bag_ids") or {}).get("new_today") or []:
            nb = normalize_bag_id(bid)
            if nb:
                hd_member_ids.add(nb)
        for bid in (hd.get("bag_ids") or {}).get("review_required") or []:
            nb = normalize_bag_id(bid)
            if nb:
                hd_member_ids.add(nb)
        for bid in (hd.get("bag_ids") or {}).get("completed") or []:
            nb = normalize_bag_id(bid)
            if nb:
                hd_member_ids.add(nb)
        for bid in (hd.get("bag_ids") or {}).get("pending") or []:
            nb = normalize_bag_id(bid)
            if nb:
                hd_member_ids.add(nb)

    hd_partially_recorded = 0
    if (
        cursor is not None
        and organization_id is not None
        and isinstance(shift_date_et, date)
    ):
        hd_partially_recorded = _count_hd_partially_recorded(
            cursor, int(organization_id), shift_date_et, hd_member_ids
        )
        # Partials are a subset of HD review; keep both visible, avoid double-block noise
        # by subtracting partials from the non-partial HD review display count.
        if hd_partially_recorded and hd_review_required >= hd_partially_recorded:
            hd_review_required = hd_review_required - hd_partially_recorded

    pending_total = wf_pending
    review_total = wf_review_required + hd_review_required + hd_partially_recorded
    accounted = (
        completed
        + approved_excluded
        + pending_total
        + review_total
        + other_unresolved
        + hd_pending_members
    )
    headline_active = int(
        all_seg.get("active_workload") or summary.get("active_workload") or 0
    )
    # When the headline active count exceeds accounted buckets, treat the gap as
    # other unresolved (snapshot drift / unbucketed exceptions).
    if day_bags is None and headline_active > accounted:
        other_unresolved += headline_active - accounted
        accounted = headline_active

    blocking_counts = {
        "wf_pending": int(wf_pending),
        "wf_review_required": int(wf_review_required),
        "hd_review_required": int(hd_review_required),
        "hd_partially_recorded": int(hd_partially_recorded),
        "hd_pending_members": int(hd_pending_members),
        "other_unresolved": int(other_unresolved),
    }
    # HD pending members (no workitems-added) may remain when closing; they are
    # not Review Required and must not fail the close identity check.
    identity_ok = (
        pending_total == 0
        and review_total == 0
        and other_unresolved == 0
        and accounted == completed + approved_excluded + hd_pending_members
    )
    return {
        "blocking_counts": blocking_counts,
        "completed": int(completed),
        "approved_excluded": int(approved_excluded),
        "pending": int(pending_total),
        "review_required": int(review_total),
        "partially_recorded": int(hd_partially_recorded),
        "unresolved_exceptions": int(other_unresolved),
        "total_admitted_workload": int(accounted),
        "identity_ok": bool(identity_ok),
    }


def validate_close(
    summary: Mapping[str, Any],
    *,
    allow_unresolved_reviews: bool = False,  # deprecated — ignored; override close removed
    cursor=None,
    organization_id: int | None = None,
    shift_date_et: date | None = None,
    day_bags: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Strict close gate. Override / unresolved-review bypass is not permitted."""
    del allow_unresolved_reviews  # explicit: no override path
    segs = summary.get("segments") or {}
    all_seg = segs.get("all") or {}
    wf = segs.get("wf") or {}
    hd = segs.get("hd") or {}

    gate = compute_close_blocking_counts(
        summary,
        cursor=cursor,
        organization_id=organization_id,
        shift_date_et=shift_date_et,
        day_bags=day_bags,
    )
    counts = gate["blocking_counts"]
    review_n = int(gate["review_required"])
    completed = int(gate["completed"])
    pending = int(gate["pending"])
    active = int(gate["total_admitted_workload"])
    excluded = int(gate["approved_excluded"])
    arithmetic_ok = bool(gate["identity_ok"])

    service_ok = (
        int(wf.get("new_today") or 0) + int(hd.get("new_today") or 0)
        == int(all_seg.get("new_today") or summary.get("new_today") or 0)
    )
    review_by_reason = summary.get("review_by_reason") or {}
    bulk_ids = review_by_reason.get("WF_BULK_WORKITEM_REVIEW") or []
    bulk_n = len(bulk_ids)

    checklist = {
        "workload_reconciled": arithmetic_ok,
        "completed_reviewed": counts["wf_pending"] == 0 and counts["wf_review_required"] == 0,
        "pending_confirmed": counts["wf_pending"] == 0,
        "review_required_cleared": review_n == 0,
        "wf_zero_weight_resolved": counts["wf_review_required"] == 0,
        "completed_without_entry_resolved": counts["wf_review_required"] == 0,
        "disappeared_reviewed": counts["other_unresolved"] == 0 and counts["wf_review_required"] == 0,
        "bulk_workitems_reviewed": bulk_n == 0,
        "carryover_confirmed": True,
        "service_totals_ok": service_ok,
        "arithmetic_ok": arithmetic_ok,
        "hd_review_cleared": counts["hd_review_required"] == 0,
        "hd_partial_cleared": counts["hd_partially_recorded"] == 0,
        "override_close_allowed": False,
    }

    blocking: list[str] = []
    if counts["wf_pending"] > 0:
        blocking.append("wf_pending")
    if counts["wf_review_required"] > 0:
        blocking.append("wf_review_required")
    if counts["hd_review_required"] > 0:
        blocking.append("hd_review_required")
    if counts["hd_partially_recorded"] > 0:
        blocking.append("hd_partially_recorded")
    if counts["other_unresolved"] > 0:
        blocking.append("other_unresolved")
    if bulk_n > 0 and "wf_review_required" not in blocking:
        # Bulk workitems are a WF review reason; ensure they block even if headline drifted.
        blocking.append("wf_review_required")
        counts["wf_review_required"] = max(counts["wf_review_required"], bulk_n)
        checklist["bulk_workitems_reviewed"] = False
    if not arithmetic_ok and not blocking:
        blocking.append("headline_arithmetic_mismatch")
        counts["other_unresolved"] = max(counts["other_unresolved"], 1)

    ok = not blocking
    if ok:
        message = None
    elif counts["hd_review_required"] > 0 or counts["hd_partially_recorded"] > 0:
        message = HD_CLOSE_REVIEW_REQUIRED_MESSAGE
    else:
        message = CLOSE_NOT_READY_MESSAGE
    return {
        "ok": ok,
        "blocking": blocking,
        "blocking_counts": counts,
        "error": None if ok else CLOSE_NOT_READY_ERROR,
        "message": message,
        "checklist": checklist,
        "review_required_count": review_n,
        "bulk_workitem_review_count": bulk_n,
        "totals": {
            "active": active,
            "completed": completed,
            "pending": pending,
            "review_required": review_n,
            "approved_excluded": excluded,
            "wf": {
                "new_today": wf.get("new_today"),
                "carryover": wf.get("carryover"),
                "completed": wf.get("completed"),
                "pending": counts["wf_pending"],
                "review_required": counts["wf_review_required"],
            },
            "hd": {
                "new_today": hd.get("new_today"),
                "carryover": hd.get("carryover"),
                "completed": hd.get("completed"),
                "pending": counts.get("hd_pending_members") or 0,
                "review_required": counts["hd_review_required"],
                "partially_recorded": counts["hd_partially_recorded"],
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
    allow_unresolved_reviews: bool = False,  # deprecated — ignored
    checklist: Mapping[str, Any] | None = None,
    expected_completed: int | None = None,
    expected_unfinished: int | None = None,
) -> dict[str, Any]:
    """Close = archive-and-freeze the persisted Step-1 day (Release B).

    Pending + Review Required become ``stale`` (Unfinished at Close).
    Completed remains completed. Membership/status are frozen; next-day carryover
    is never seeded. Manual close does not create tomorrow's membership.

    Idempotent for already-closed days (no bag/headline rewrite).
    Optional ``expected_completed`` / ``expected_unfinished`` guard against a
    stale close dialog; mismatch returns conflict without closing.
    """
    del allow_unresolved_reviews  # override close removed
    from backend.rinse_shift_day_close_archive import finalize_day_close_archive

    return finalize_day_close_archive(
        cursor,
        organization_id,
        shift_date_et,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        reason=reason,
        mode="manual",
        checklist=checklist,
        expected_completed=expected_completed,
        expected_unfinished=expected_unfinished,
    )


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

    # Restore close-time statuses so managers can continue working after reopen.
    # carried_forward → pending; legacy stale → pre_close_status; review stays review.
    bags = load_day_bags(cursor, organization_id, shift_date_et)
    for bag in bags:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        snap = dict(bag.get("bag_snapshot") or {})
        pre = str(snap.get("pre_close_status") or "").strip().lower()
        eff = str(bag.get("effective_status") or "").strip().lower()
        if eff == "carried_forward":
            restore = OUTCOME_PENDING
            reasons: list[Any] = []
        elif eff in ("stale", "unfinished_at_close", "stale_for_day"):
            restore = (
                pre
                if pre
                in (
                    OUTCOME_PENDING,
                    OUTCOME_REVIEW_REQUIRED,
                    "pending",
                    "review_required",
                )
                else OUTCOME_PENDING
            )
            reasons = snap.get("pre_close_review_reason_codes") or []
        else:
            continue
        snap.pop("day_close_status", None)
        snap.pop("day_close_label", None)
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET effective_status=%s,
                review_reason_codes_json=%s,
                bag_snapshot_json=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
            """,
            (
                restore,
                _json_dump(reasons if restore == OUTCOME_REVIEW_REQUIRED else []),
                _json_dump(snap),
                int(organization_id),
                shift_date_et,
                bid,
            ),
        )

    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET status=%s, reopen_count=reopen_count+1, close_override=0,
            closed_at=NULL, closed_by_user_id=NULL, closed_by_display_name=NULL,
            close_reason=NULL,
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
    # Caller owns the DB transaction.
    return {"ok": True, "day": get_day_record(cursor, organization_id, shift_date_et)}


def _seed_next_day_carryover(
    cursor, organization_id: int, closed_date: date
) -> None:
    """Disabled (Release B). Kept for reference only — do not call.

    Fresh-day close-and-archive never seeds unresolved prior-day rows into the
    next ET day. Next-day membership comes only from that day's Rinse scrapes.
    """
    del cursor, organization_id, closed_date
    return


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


def step1_snapshot_present(cursor, organization_id: int, shift_date_et: date) -> bool:
    """True when the day has a persisted headline and day_bags (usable Today)."""
    rec = get_day_record(cursor, int(organization_id), shift_date_et)
    if not rec:
        return False
    headline = rec.get("headline")
    if not isinstance(headline, Mapping) or not headline:
        return False
    try:
        if day_bag_count(cursor, int(organization_id), shift_date_et) > 0:
            return True
    except Exception:
        pass
    # Headline counts mean a snapshot was persisted even if day_bags cannot
    # be queried (tests / transient DB). Do not treat that as missing.
    if headline.get("completed") is not None or headline.get("pending") is not None:
        return True
    bag_ids = ((headline.get("segments") or {}).get("all") or {}).get("bag_ids") or {}
    if isinstance(bag_ids, Mapping):
        for key in ("pending", "completed", "review_required"):
            ids = bag_ids.get(key)
            if isinstance(ids, (list, tuple)) and ids:
                return True
    return False


def _persist_snapshot_then_attach_specialty(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    wl: Mapping[str, Any],
    summary: Mapping[str, Any],
    day: Mapping[str, Any] | None,
    chronology_complete: bool,
    projection_deferred_bag_ids: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Persist OPEN day + day_bags + headline, then best-effort specialty.

    Specialty attach is optional and must not block Today existing. A hang or
    failure after the first persist leaves a usable snapshot in place.
    """
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary
    from backend.rinse_hd_day_presentation import finalize_hd_step1_summary

    org = int(organization_id)
    summary = dict(summary or {})
    summary = finalize_hd_step1_summary(
        summary,
        selected_date_et=shift_date_et,
        membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
        cursor=cursor,
        organization_id=org,
    )
    status = derive_shift_day_status(
        summary,
        current_status=(day or {}).get("status"),
        membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
    )
    deferred = list(projection_deferred_bag_ids or [])
    persisted = persist_day_snapshot(
        cursor,
        org,
        shift_date_et,
        workload=wl,
        summary=summary,
        status=status,
        force=True,
        chronology_complete=bool(chronology_complete),
        projection_deferred_bag_ids=deferred,
    )
    _commit(cursor)
    specialty_ok = False
    before_spec = summary.get("specialty_metrics")
    try:
        attached = attach_specialty_metrics_to_summary(
            cursor, org, shift_date_et, summary
        )
        summary = attached if isinstance(attached, dict) else summary
        specialty_ok = True
        if summary.get("specialty_metrics") != before_spec:
            persisted = persist_day_snapshot(
                cursor,
                org,
                shift_date_et,
                workload=wl,
                summary=summary,
                status=status,
                force=True,
                chronology_complete=bool(chronology_complete),
                projection_deferred_bag_ids=deferred,
            )
            _commit(cursor)
    except Exception:
        logger.exception(
            "specialty metrics attach failed after Today snapshot persist org=%s date=%s",
            org,
            shift_date_et,
        )
    return persisted, summary, specialty_ok


def reproject_day_bag_completions_from_chronology(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    chronology_complete: bool = True,
) -> dict[str, Any]:
    """Re-project completion onto an existing day-bag membership set.

    Checkpoint 2A: scan chronology may gain review/POST evidence after the last
    Stage-B ``backfill_day_from_live``. Presence downstream previously marked
    ``projections_refreshed`` as a read-time no-op, so day_bags stayed Pending
    even when ``resolve_current_cycle`` already returned completed.

    This path:
      - freezes membership to already-persisted day-bag IDs (no admit/remove)
      - rebuilds workload outcomes from scan chronology
      - compares frozen IDs to full rebuilt membership (``new_today`` ∪
        ``carryover`` / ``opening_carryover``) so CP2B Opening Carryover is not
        a false divergence
      - persists via ``persist_day_snapshot`` (same projection function as Stage-B)

    Does not change carryover / opening-scrape / evidence-gate policy.
    """
    org = int(organization_id)
    day = get_day_record(cursor, org, shift_date_et)
    if not day:
        if shift_date_et == today_et():
            created = backfill_day_from_live(
                cursor,
                org,
                shift_date_et,
                chronology_complete=bool(chronology_complete),
            )
            created = dict(created or {})
            created.setdefault("reason", "day_missing_created_today")
            return created
        return {
            "ok": True,
            "skipped": True,
            "reason": "day_missing",
            "persisted": False,
            "membership_count": 0,
            "completed_count": 0,
        }
    if str(day.get("status") or "") == STATUS_CLOSED:
        return {
            "ok": True,
            "skipped": True,
            "reason": "day_closed",
            "persisted": False,
            "membership_count": 0,
            "completed_count": 0,
        }

    existing_bags = load_day_bags(cursor, org, shift_date_et)
    frozen = sorted(
        {
            normalize_bag_id(b.get("bag_id"))
            for b in existing_bags
            if normalize_bag_id(b.get("bag_id"))
        }
    )
    if not frozen:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_day_bags",
            "persisted": False,
            "membership_count": 0,
            "completed_count": 0,
        }

    activation = get_step1_activation_date(cursor, org)
    wl = build_veewash_daily_workload_from_membership(
        cursor,
        org,
        selected_date_et=shift_date_et,
        frozen_member_ids=frozen,
    )
    # Full rebuilt membership = new_today ∪ carryover (CP2B Opening Carryover
    # lives outside new_today). Dedupe by bag ID before comparing to frozen.
    member_ids = sorted(
        {
            normalize_bag_id(b)
            for b in (
                list(wl.get("new_today") or [])
                + list(wl.get("carryover") or [])
                + list(wl.get("opening_carryover") or [])
            )
            if normalize_bag_id(b)
        }
    )
    if member_ids != frozen:
        return {
            "ok": False,
            "error": "frozen_membership_diverged",
            "persisted": False,
            "membership_count": len(frozen),
            "rebuild_membership_count": len(member_ids),
            "only_in_rebuild": sorted(set(member_ids) - set(frozen))[:20],
            "missing_from_rebuild": sorted(set(frozen) - set(member_ids))[:20],
        }

    summary = build_step1_headline_summary(
        wl,
        selected_date_et=shift_date_et,
        activation_date=activation or shift_date_et,
    )
    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")

    day, summary, _specialty_ok = _persist_snapshot_then_attach_specialty(
        cursor,
        org,
        shift_date_et,
        wl=wl,
        summary=summary,
        day=day,
        chronology_complete=bool(chronology_complete),
    )
    bags_after = load_day_bags(cursor, org, shift_date_et)
    completed_n = sum(
        1
        for b in bags_after
        if str(b.get("effective_status") or "").lower() == OUTCOME_COMPLETED
    )
    return {
        "ok": True,
        "persisted": True,
        "skipped": False,
        "membership_count": len(frozen),
        "completed_count": completed_n,
        "summary_totals": {
            "active": summary.get("active_workload"),
            "total_workload": summary.get("total_workload"),
            "completed": summary.get("completed"),
            "pending": summary.get("pending"),
            "review_required": (summary.get("exceptions") or {}).get("review_required"),
        },
        "day": day,
    }


def _canonical_terminal_projection_succeeded(
    projection: Mapping[str, Any] | None,
    day_after: Mapping[str, Any] | None,
) -> bool:
    """``persist_day_snapshot`` / terminal projection return a day record, not ``{ok: true}``."""
    if isinstance(projection, Mapping):
        if projection.get("ok") is True:
            return True
        if projection.get("ok") is False:
            return False
        if projection.get("status") or projection.get("last_sync_at"):
            return True
    if isinstance(day_after, Mapping) and day_after.get("last_sync_at"):
        return True
    return False


def backfill_day_from_live(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    force: bool = False,
    chronology_complete: bool = True,
    import_batch_id: int | None = None,
    scrape_run_id: int | None = None,
    bypass_evidence_gate: bool = False,
    projection_deferred_bag_ids: Sequence[str] | None = None,
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

    today = today_et()

    # Canonical lifecycle orgs must always persist through terminal projection +
    # final_wf_day_membership_bag_ids — never append-only Stage-B membership alone.
    try:
        from backend.rinse_wf_service_cycle import is_wf_canonical_lifecycle_enabled
        from backend.rinse_wf_service_cycle_compat import (
            terminal_project_canonical_wf_day_snapshot,
        )

        if is_wf_canonical_lifecycle_enabled(cursor, int(organization_id)):
            proj = terminal_project_canonical_wf_day_snapshot(
                cursor,
                int(organization_id),
                shift_date_et,
                force=force,
            )
            day_after = get_day_record(cursor, organization_id, shift_date_et) or {}
            proj_ok = _canonical_terminal_projection_succeeded(proj, day_after)
            headline = (
                summary_from_day_record(
                    day_after, cursor=cursor, organization_id=int(organization_id)
                )
                or {}
            )
            wf = (headline.get("segments") or {}).get("wf") or {}
            return {
                "ok": proj_ok,
                "persisted": proj_ok,
                "historical_canonical_reproject": shift_date_et < today,
                "canonical_terminal_reproject": True,
                "day": day_after,
                "summary_totals": {
                    "active": headline.get("active_workload"),
                    "total_workload": wf.get("total_workload")
                    or wf.get("active_workload"),
                    "completed": wf.get("completed"),
                    "pending": wf.get("pending"),
                    "review_required": (wf.get("exceptions") or {}).get(
                        "review_required"
                    ),
                },
                "bag_count": len(
                    load_day_bags(cursor, organization_id, shift_date_et) or []
                ),
                "chronology_complete": bool(chronology_complete),
                "projection": proj,
            }
    except Exception:
        logger.exception(
            "canonical terminal reproject failed org=%s date=%s",
            organization_id,
            shift_date_et,
        )

    # Durable incomplete-batch gate: refuse day-bag / headline writes while the
    # evidence batch Stage B would use is marked incomplete.
    deferred_ids = [normalize_bag_id(b) for b in (projection_deferred_bag_ids or []) if normalize_bag_id(b)]
    if chronology_complete and not bypass_evidence_gate:
        from backend.rinse_step1_evidence_gate import (
            evaluate_durable_evidence_gate,
            fetch_projection_deferred_bag_ids,
        )
        from backend.rinse_scan_chronology_gate import last_consistent_snapshot_counts

        durable = evaluate_durable_evidence_gate(
            cursor,
            int(organization_id),
            import_batch_id=import_batch_id,
            scrape_run_id=scrape_run_id,
        )
        if not deferred_ids:
            deferred_ids = list(durable.get("projection_deferred_bag_ids") or [])
            if not deferred_ids:
                deferred_ids = fetch_projection_deferred_bag_ids(
                    cursor,
                    int(organization_id),
                    durable.get("import_batch_id") or import_batch_id,
                )
        if durable.get("blocking"):
            reason = str(durable.get("gate_reason") or "import_batch_incomplete")
            return {
                "ok": True,
                "deferred": True,
                "rebuild_deferred": True,
                "persisted": False,
                "reason": reason,
                "gate_decision": "defer",
                "gate_reason": reason,
                "gate_status": durable.get("gate_status"),
                "import_batch_id": durable.get("import_batch_id"),
                "scrape_run_id": durable.get("scrape_run_id"),
                "portal_presence_run_id": durable.get("portal_presence_run_id"),
                "evidence_generation_id": durable.get("evidence_generation_id"),
                "projection_deferred_bag_ids": deferred_ids,
                "last_consistent_snapshot": last_consistent_snapshot_counts(
                    day,
                    cursor=cursor,
                    organization_id=int(organization_id),
                    shift_date_et=shift_date_et,
                ),
                "day": day,
                "durable_evidence_gate": durable,
                "message": (
                    "Scan chronology updating — counts have not been replaced. "
                    "Last consistent snapshot retained."
                ),
            }

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
    # Persist membership + headline FIRST so Today is available even if
    # specialty (or later optional work) hangs.
    day, summary, specialty_ok = _persist_snapshot_then_attach_specialty(
        cursor,
        organization_id,
        shift_date_et,
        wl=wl,
        summary=summary,
        day=day,
        chronology_complete=bool(chronology_complete),
        projection_deferred_bag_ids=deferred_ids,
    )
    return {
        "ok": True,
        "persisted": True,
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
        "chronology_complete": bool(chronology_complete),
        "specialty_metrics_attached": specialty_ok,
        "projection_deferred_bag_ids": deferred_ids,
        "projection_deferred_count": len(deferred_ids),
    }
