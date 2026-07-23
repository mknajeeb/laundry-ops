"""Daily Operations Phase 1A — day header, WF pounds, MTD weight revenue."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from backend.rinse_veewash_workload import STEP1_AUTHORITATIVE_START_ET, VEEWASH_ORG_ID
from backend.ta_helpers import table_exists, table_has_column
from backend.wf_mtd_pricing import (
    allocate_wf_day_revenue_from_mtd,
    lbs as money_lbs,
)

# Exclusion reasons for Finance → Daily Operations pound reconciliation.
# Each finance-suggested bag receives exactly one reason when not eligible in Daily Ops.
EXCL_INCOMPLETE = "incomplete_bags"
EXCL_MISSING_POST = "missing_post"
EXCL_WRONG_WORKFLOW = "wrong_workflow"
EXCL_COMPLETED_OUTSIDE_DAY = "completed_outside_selected_et_day"
EXCL_MANUAL = "manual_exclusions"
EXCL_MISSING_MEMBERSHIP = "missing_membership"
EXCL_OTHER = "other"

EXCLUSION_REASON_ORDER = (
    EXCL_MANUAL,
    EXCL_WRONG_WORKFLOW,
    EXCL_COMPLETED_OUTSIDE_DAY,
    EXCL_MISSING_MEMBERSHIP,
    EXCL_INCOMPLETE,
    EXCL_MISSING_POST,
    EXCL_OTHER,
)

EXCLUSION_LABELS = {
    EXCL_INCOMPLETE: "Incomplete bags",
    EXCL_MISSING_POST: "Missing POST",
    EXCL_WRONG_WORKFLOW: "Wrong workflow",
    EXCL_COMPLETED_OUTSIDE_DAY: "Completed outside selected ET day",
    EXCL_MANUAL: "Manual exclusions",
    EXCL_MISSING_MEMBERSHIP: "Missing membership",
    EXCL_OTHER: "Other",
}

DAILY_OPERATIONS_ORG_IDS = frozenset({VEEWASH_ORG_ID})
TRACKING_STARTED_MESSAGE = "Daily Operations tracking started July 23, 2026."

STATUS_OPEN = "OPEN"
STATUS_READY = "READY"
STATUS_CLOSED = "CLOSED"
STATUS_REOPENED = "REOPENED"
STATUS_UNAVAILABLE = "UNAVAILABLE"

POST_SOURCE_MANAGER_CORRECTED = "manager_corrected_post"
POST_SOURCE_WEIGHT_ROLE_POST = "scan_weight_role_post"
POST_SOURCE_CANONICAL_POST_EVENT = "canonical_post_processing_post_event"
POST_SOURCE_MISSING = "missing_post_weight"

SQL_SCHEMA_PATH = "backend/sql/daily_operations_v1.sql"


def daily_operations_enabled_for_org(organization_id: int) -> bool:
    return int(organization_id) in DAILY_OPERATIONS_ORG_IDS


def ensure_daily_operations_tables(cursor) -> None:
    if table_exists(cursor, "daily_operations_days"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_operations_days (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          operations_date_et DATE NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
          wf_rate_plan_id INT NULL,
          pricing_schedule_snapshot_json JSON NULL,
          mtd_pounds_before DECIMAL(12,2) NULL,
          today_wf_completed_pounds DECIMAL(12,2) NULL,
          tier1_pounds_today DECIMAL(12,2) NULL,
          tier2_pounds_today DECIMAL(12,2) NULL,
          tier1_revenue_today DECIMAL(12,2) NULL,
          tier2_revenue_today DECIMAL(12,2) NULL,
          wf_weight_revenue DECIMAL(12,2) NULL,
          mtd_pounds_after DECIMAL(12,2) NULL,
          missing_post_weight_count INT NOT NULL DEFAULT 0,
          outstanding_workitem_review_count INT NOT NULL DEFAULT 0,
          pricing_incomplete TINYINT(1) NOT NULL DEFAULT 0,
          diagnostics_json JSON NULL,
          closed_at DATETIME NULL,
          closed_by_user_id INT NULL,
          reopened_at DATETIME NULL,
          reopened_by_user_id INT NULL,
          version INT NOT NULL DEFAULT 1,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_daily_ops_org_date (organization_id, operations_date_et),
          INDEX idx_daily_ops_org_status (organization_id, status, operations_date_et)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _norm_bag(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _parse_weight(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

        return normalize_scan_weight_lbs(raw)
    except Exception:
        try:
            return float(Decimal(str(raw)))
        except Exception:
            return None


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _is_completed_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return bool(s) and "completed" in s and "without" not in s


def list_wf_completed_day_bags(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> list[dict[str, Any]]:
    """
    WF bags on append-only ET-day membership that are canonically completed.

    Read-only against rinse_shift_monitor_day_bags (+ optional ledger filter).
    Does not rebuild Jul 23 membership.
    """
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return []
    org = int(organization_id)
    cursor.execute(
        """
        SELECT bag_id, service_type, canonical_completion_status,
               canonical_completion_timestamp, post_weight_lbs, weight_lbs,
               pre_weight_lbs, review_reason_codes_json, effective_status, id AS day_bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'WF'
        ORDER BY bag_id
        """,
        (org, operations_date_et),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    completed = [r for r in rows if _is_completed_status(r.get("canonical_completion_status"))]

    if table_exists(cursor, "rinse_et_day_workload_ledger"):
        cursor.execute(
            """
            SELECT bag_id FROM rinse_et_day_workload_ledger
            WHERE organization_id = %s AND et_date = %s
            """,
            (org, operations_date_et),
        )
        member = {_norm_bag(r.get("bag_id")) for r in (cursor.fetchall() or [])}
        if member:
            completed = [r for r in completed if _norm_bag(r.get("bag_id")) in member]
    return completed


def _latest_manager_post_correction(
    cursor,
    organization_id: int,
    bag_id: str,
) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_step1_corrections"):
        return None
    cursor.execute(
        """
        SELECT id, new_values, reason_text, created_at, actor_user_id
        FROM rinse_step1_corrections
        WHERE organization_id = %s
          AND bag_id = %s
          AND action = 'correct_weight'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (int(organization_id), bag_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    raw = _json_load(row.get("new_values")) or {}
    if not isinstance(raw, dict):
        return None
    post = _parse_weight(
        raw.get("corrected_post_weight_lbs", raw.get("post_weight_lbs", raw.get("weight_lbs")))
    )
    if post is None:
        return None
    return {
        "weight_lbs": post,
        "source": POST_SOURCE_MANAGER_CORRECTED,
        "correction_id": int(row["id"]),
        "reason": row.get("reason_text"),
        "corrected_at": row.get("created_at"),
        "scan_event_id": None,
    }


def _post_role_scan_events(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    if not table_has_column(cursor, "rinse_bag_scan_events", "weight_role"):
        return []
    cursor.execute(
        """
        SELECT id, bag_id, weight_lbs, weight_role, weight_source, weight_observed_at,
               scanned_at_parsed, purpose, weight_presence_run_id, weight_presence_run_row_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id = %s
          AND UPPER(COALESCE(weight_role, '')) = 'POST'
          AND weight_lbs IS NOT NULL
        ORDER BY COALESCE(weight_observed_at, scanned_at_parsed) ASC, id ASC
        """,
        (int(organization_id), bag_id),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _canonical_post_processing_event(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    operations_date_et: date,
) -> dict[str, Any] | None:
    """Resolve chronology post-processing weight event; use only if it is a POST-role event."""
    from backend.rinse_employee_completed_bags import _resolve_anchor_ts
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_post_processing_weight_chronology import _load_scan_events_for_bags
    from backend.rinse_workload_bag_weight import trace_wf_completion_weight

    events = _load_scan_events_for_bags(cursor, int(organization_id), [bag_id])
    as_of_end = naive_et_day_end_inclusive(operations_date_et)
    anchor = _resolve_anchor_ts(events, operations_date_et)
    trace = trace_wf_completion_weight(
        bag_id=bag_id,
        events=events,
        credit_ts=None,
        anchor_ts=anchor,
        as_of_end=as_of_end,
        selected_date_et=operations_date_et,
        portal_upload_weight=None,
    )
    event_id = trace.get("completion_event_id")
    parsed = trace.get("scan_weight_lbs_parsed")
    if event_id is None or parsed is None:
        return None
    # Locate the event and require it matches POST authority (weight_role POST when present).
    match = None
    for ev in events or []:
        if int(ev.get("id") or 0) == int(event_id):
            match = ev
            break
    if not match:
        return None
    role = str(match.get("weight_role") or "").strip().upper()
    if role and role != "POST":
        return None
    return {
        "weight_lbs": float(parsed),
        "source": POST_SOURCE_CANONICAL_POST_EVENT,
        "scan_event_id": int(event_id),
        "weight_role": role or None,
        "trace": {
            "completion_event_id": event_id,
            "completion_scan_purpose": trace.get("completion_scan_purpose"),
        },
    }


def resolve_authoritative_post_weight(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    operations_date_et: date,
) -> dict[str, Any]:
    """
    POST weight authority:
    1. Manager-corrected POST
    2. Scan enrichment weight_role=POST
    3. Canonical post-processing weight only when that event is POST-authoritative
    """
    bid = _norm_bag(bag_id)
    corrected = _latest_manager_post_correction(cursor, organization_id, bid)
    if corrected:
        return {**corrected, "bag_id": bid, "missing": False}

    post_events = _post_role_scan_events(cursor, organization_id, bid)
    if post_events:
        # Prefer latest POST observation.
        chosen = post_events[-1]
        weight = _parse_weight(chosen.get("weight_lbs"))
        if weight is not None:
            return {
                "bag_id": bid,
                "weight_lbs": weight,
                "source": POST_SOURCE_WEIGHT_ROLE_POST,
                "scan_event_id": int(chosen["id"]) if chosen.get("id") is not None else None,
                "weight_role": "POST",
                "weight_source": chosen.get("weight_source"),
                "observed_at": chosen.get("weight_observed_at") or chosen.get("scanned_at_parsed"),
                "missing": False,
            }

    canonical = _canonical_post_processing_event(
        cursor, organization_id, bid, operations_date_et=operations_date_et
    )
    if canonical:
        return {**canonical, "bag_id": bid, "missing": False}

    return {
        "bag_id": bid,
        "weight_lbs": None,
        "source": POST_SOURCE_MISSING,
        "scan_event_id": None,
        "missing": True,
    }


def count_outstanding_wf_workitem_reviews(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> int:
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return 0
    from backend.rinse_bulk_workitems import (
        REASON_WF_BULK_WORKITEM_REVIEW,
        bag_bulk_review_cleared,
        load_bag_bulk_lines,
        load_bulk_resolutions,
    )

    cursor.execute(
        """
        SELECT bag_id, review_reason_codes_json
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'WF'
        """,
        (int(organization_id), operations_date_et),
    )
    candidates: list[str] = []
    for row in cursor.fetchall() or []:
        raw = row.get("review_reason_codes_json")
        blob = raw if isinstance(raw, str) else json.dumps(raw or [])
        if REASON_WF_BULK_WORKITEM_REVIEW in blob:
            candidates.append(_norm_bag(row.get("bag_id")))
    if not candidates:
        return 0
    resolutions = load_bulk_resolutions(cursor, organization_id, operations_date_et, candidates)
    lines = load_bag_bulk_lines(cursor, organization_id, operations_date_et, candidates)
    outstanding = 0
    for bid in candidates:
        if not bag_bulk_review_cleared(resolutions.get(bid), lines.get(bid)):
            outstanding += 1
    return outstanding


def compute_day_wf_pound_totals(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, Any]:
    bags = list_wf_completed_day_bags(cursor, organization_id, operations_date_et)
    included: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    total = Decimal("0")
    for row in bags:
        bid = _norm_bag(row.get("bag_id"))
        post = resolve_authoritative_post_weight(
            cursor, organization_id, bid, operations_date_et=operations_date_et
        )
        entry = {
            "bag_id": bid,
            "day_bag_id": row.get("day_bag_id"),
            "canonical_completion_status": row.get("canonical_completion_status"),
            "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
            "post_weight_lbs": post.get("weight_lbs"),
            "post_weight_source": post.get("source"),
            "post_weight_scan_event_id": post.get("scan_event_id"),
            "post_weight_corrected": post.get("source") == POST_SOURCE_MANAGER_CORRECTED,
            "reviewable_zero": post.get("weight_lbs") == 0,
        }
        if post.get("missing") or post.get("weight_lbs") is None:
            missing.append(entry)
            continue
        total += Decimal(str(post["weight_lbs"]))
        included.append(entry)
    return {
        "included_bags": included,
        "missing_post_bags": missing,
        "completed_wf_bag_count": len(bags),
        "included_count": len(included),
        "missing_post_weight_count": len(missing),
        "today_wf_completed_pounds": money_lbs(total),
    }


def compute_mtd_pounds_before(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> float:
    """Sum Daily Operations eligible pounds for earlier days in the same ET month."""
    month_start = operations_date_et.replace(day=1)
    total = Decimal("0")
    d = month_start
    while d < operations_date_et:
        if d >= STEP1_AUTHORITATIVE_START_ET:
            day_totals = compute_day_wf_pound_totals(cursor, organization_id, d)
            total += Decimal(str(day_totals["today_wf_completed_pounds"] or 0))
        d += timedelta(days=1)
    return money_lbs(total)


def build_daily_operations_day(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    persist: bool = True,
    user_id: int | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    ensure_daily_operations_tables(cursor)

    if not daily_operations_enabled_for_org(org):
        return {
            "available": False,
            "organization_id": org,
            "operations_date_et": operations_date_et.isoformat(),
            "status": STATUS_UNAVAILABLE,
            "reason": "daily_operations_not_enabled_for_organization",
            "message": "Daily Operations is enabled for organization 3 only in Phase 1A.",
        }

    if operations_date_et < STEP1_AUTHORITATIVE_START_ET:
        return {
            "available": False,
            "organization_id": org,
            "operations_date_et": operations_date_et.isoformat(),
            "status": STATUS_UNAVAILABLE,
            "reason": "before_tracking_start",
            "message": TRACKING_STARTED_MESSAGE,
            "tracking_started_et": STEP1_AUTHORITATIVE_START_ET.isoformat(),
        }

    from backend.daily_revenue_cost import (
        ensure_daily_revenue_cost_tables,
        ensure_veewash_aug1_2026_wf_schedule,
        get_wf_schedule_for_date,
    )

    ensure_daily_revenue_cost_tables(cursor)
    schedule_seed = ensure_veewash_aug1_2026_wf_schedule(cursor, org, user_id=user_id)

    pound_totals = compute_day_wf_pound_totals(cursor, org, operations_date_et)
    mtd_before = compute_mtd_pounds_before(cursor, org, operations_date_et)
    schedule_id, tiers = get_wf_schedule_for_date(cursor, org, operations_date_et)
    pricing_incomplete = schedule_id is None or not tiers

    if pricing_incomplete:
        allocation = allocate_wf_day_revenue_from_mtd(
            mtd_before, pound_totals["today_wf_completed_pounds"], []
        )
        allocation["pricing_complete"] = False
        weight_revenue = None
    else:
        allocation = allocate_wf_day_revenue_from_mtd(
            mtd_before, pound_totals["today_wf_completed_pounds"], tiers
        )
        weight_revenue = allocation["weight_revenue_today"]

    outstanding_reviews = count_outstanding_wf_workitem_reviews(
        cursor, org, operations_date_et
    )

    schedule_snapshot = None
    if schedule_id is not None:
        cursor.execute(
            "SELECT id, name, effective_from, effective_to FROM dr_rinse_wf_pricing_schedules WHERE id = %s",
            (schedule_id,),
        )
        srow = cursor.fetchone() or {}
        schedule_snapshot = {
            "id": schedule_id,
            "name": srow.get("name"),
            "effective_from": srow.get("effective_from").isoformat()
            if hasattr(srow.get("effective_from"), "isoformat")
            else srow.get("effective_from"),
            "effective_to": srow.get("effective_to").isoformat()
            if hasattr(srow.get("effective_to"), "isoformat")
            else srow.get("effective_to"),
            "tiers": tiers,
        }

    diagnostics = {
        "schedule_seed": schedule_seed,
        "eligibility": {
            "membership_source": "rinse_shift_monitor_day_bags + rinse_et_day_workload_ledger",
            "service": "WF",
            "completion": "canonical_completion_status contains completed",
            "jul23_membership_rebuild": False,
        },
        "post_weight_authority": [
            POST_SOURCE_MANAGER_CORRECTED,
            POST_SOURCE_WEIGHT_ROLE_POST,
            POST_SOURCE_CANONICAL_POST_EVENT,
        ],
        "never_used": [
            "pre_weight",
            "live_portal_weight",
            "registry_weight",
            "incomplete_order_weight",
            "guessed_weight",
        ],
        "pricing_model": "month_to_date_cumulative_shared_with_finance_drc",
        "pricing_incomplete": pricing_incomplete,
    }

    status = STATUS_OPEN
    payload = {
        "available": True,
        "organization_id": org,
        "operations_date_et": operations_date_et.isoformat(),
        "status": status,
        "tracking_started_et": STEP1_AUTHORITATIVE_START_ET.isoformat(),
        "kpis": {
            "wf_completed_pounds": pound_totals["today_wf_completed_pounds"],
            "wf_weight_revenue": weight_revenue,
            "missing_post_weights": pound_totals["missing_post_weight_count"],
            "outstanding_wf_workitem_reviews": outstanding_reviews,
            "pricing_incomplete": pricing_incomplete,
        },
        "revenue": {
            "wf_completed_pounds": pound_totals["today_wf_completed_pounds"],
            "wf_weight_revenue": weight_revenue,
            "mtd_pounds_before": allocation["mtd_pounds_before"],
            "mtd_pounds_after": allocation["mtd_pounds_after"],
            "tier1_pounds_today": allocation["tier1_pounds_today"] if not pricing_incomplete else None,
            "tier2_pounds_today": allocation["tier2_pounds_today"] if not pricing_incomplete else None,
            "tier1_revenue_today": allocation["tier1_revenue_today"] if not pricing_incomplete else None,
            "tier2_revenue_today": allocation["tier2_revenue_today"] if not pricing_incomplete else None,
            "applied_tiers": allocation["applied_tiers"] if not pricing_incomplete else [],
            "pricing_incomplete": pricing_incomplete,
            "pricing_schedule": schedule_snapshot,
        },
        "drilldowns": {
            "included_wf_bags": pound_totals["included_bags"],
            "missing_post_weight_bags": pound_totals["missing_post_bags"],
        },
        "counts": {
            "completed_wf_bags": pound_totals["completed_wf_bag_count"],
            "included_with_post": pound_totals["included_count"],
            "missing_post_weight": pound_totals["missing_post_weight_count"],
            "outstanding_workitem_reviews": outstanding_reviews,
        },
        "links": {
            "workitem_maintenance": "/performance/settings",
            "wf_rate_maintenance": "/finance/daily-revenue-cost",
            "shift_monitor": "/performance",
            "finance_drc": "/finance/daily-revenue-cost",
        },
        "placeholders": {
            "labor": "Coming in later phase",
            "hd_revenue": "Coming in later phase",
            "combined_profitability": "Coming in later phase",
        },
        "diagnostics": diagnostics,
    }

    if persist:
        cursor.execute(
            """
            INSERT INTO daily_operations_days (
              organization_id, operations_date_et, status, wf_rate_plan_id,
              pricing_schedule_snapshot_json, mtd_pounds_before, today_wf_completed_pounds,
              tier1_pounds_today, tier2_pounds_today, tier1_revenue_today, tier2_revenue_today,
              wf_weight_revenue, mtd_pounds_after, missing_post_weight_count,
              outstanding_workitem_review_count, pricing_incomplete, diagnostics_json
            ) VALUES (
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
              status=VALUES(status),
              wf_rate_plan_id=VALUES(wf_rate_plan_id),
              pricing_schedule_snapshot_json=VALUES(pricing_schedule_snapshot_json),
              mtd_pounds_before=VALUES(mtd_pounds_before),
              today_wf_completed_pounds=VALUES(today_wf_completed_pounds),
              tier1_pounds_today=VALUES(tier1_pounds_today),
              tier2_pounds_today=VALUES(tier2_pounds_today),
              tier1_revenue_today=VALUES(tier1_revenue_today),
              tier2_revenue_today=VALUES(tier2_revenue_today),
              wf_weight_revenue=VALUES(wf_weight_revenue),
              mtd_pounds_after=VALUES(mtd_pounds_after),
              missing_post_weight_count=VALUES(missing_post_weight_count),
              outstanding_workitem_review_count=VALUES(outstanding_workitem_review_count),
              pricing_incomplete=VALUES(pricing_incomplete),
              diagnostics_json=VALUES(diagnostics_json),
              version=version+1
            """,
            (
                org,
                operations_date_et,
                status,
                schedule_id,
                json.dumps(schedule_snapshot) if schedule_snapshot else None,
                allocation["mtd_pounds_before"],
                pound_totals["today_wf_completed_pounds"],
                allocation["tier1_pounds_today"] if not pricing_incomplete else None,
                allocation["tier2_pounds_today"] if not pricing_incomplete else None,
                allocation["tier1_revenue_today"] if not pricing_incomplete else None,
                allocation["tier2_revenue_today"] if not pricing_incomplete else None,
                weight_revenue,
                allocation["mtd_pounds_after"],
                pound_totals["missing_post_weight_count"],
                outstanding_reviews,
                1 if pricing_incomplete else 0,
                json.dumps(diagnostics, default=str),
            ),
        )
        cursor.execute(
            """
            SELECT id, version FROM daily_operations_days
            WHERE organization_id = %s AND operations_date_et = %s
            """,
            (org, operations_date_et),
        )
        hdr = cursor.fetchone() or {}
        payload["day_id"] = int(hdr["id"]) if hdr.get("id") is not None else None
        payload["version"] = int(hdr.get("version") or 1)

    return payload


def load_day_bag_index(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, dict[str, Any]]:
    """All day-bag rows for the ET day, keyed by bag_id."""
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return {}
    cursor.execute(
        """
        SELECT bag_id, service_type, canonical_completion_status,
               canonical_completion_timestamp, post_weight_lbs, weight_lbs,
               pre_weight_lbs, review_reason_codes_json, effective_status,
               disposition, id AS day_bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (int(organization_id), operations_date_et),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        if bid:
            out[bid] = dict(row)
    return out


def load_day_membership_bag_ids(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> set[str]:
    """Append-only ledger membership when present; else day-bag ids for the date."""
    if table_exists(cursor, "rinse_et_day_workload_ledger"):
        cursor.execute(
            """
            SELECT bag_id FROM rinse_et_day_workload_ledger
            WHERE organization_id = %s AND et_date = %s
            """,
            (int(organization_id), operations_date_et),
        )
        member = {_norm_bag(r.get("bag_id")) for r in (cursor.fetchall() or [])}
        if member:
            return member
    return set(load_day_bag_index(cursor, organization_id, operations_date_et).keys())


def load_manual_daily_ops_exclusions(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> set[str]:
    """Optional Phase later table; empty until exclusions exist."""
    if not table_exists(cursor, "daily_operations_bag_exclusions"):
        return set()
    cursor.execute(
        """
        SELECT bag_id FROM daily_operations_bag_exclusions
        WHERE organization_id = %s
          AND operations_date_et = %s
          AND excluded = 1
        """,
        (int(organization_id), operations_date_et),
    )
    return {_norm_bag(r.get("bag_id")) for r in (cursor.fetchall() or [])}


def _completion_date_et(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text = str(raw).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def classify_finance_bag_vs_daily_operations(
    *,
    bag_id: str,
    finance_weight_lbs: float | None,
    operations_date_et: date,
    day_bag: Mapping[str, Any] | None,
    membership_ids: set[str],
    manual_exclusions: set[str],
    do_included_ids: set[str],
    do_missing_post_ids: set[str],
    finance_completion_timestamp: Any = None,
) -> dict[str, Any]:
    """
    Assign exactly one fate for a Finance-suggested bag.

    Returns either inclusion or a single exclusion reason.
    """
    bid = _norm_bag(bag_id)
    fin_lbs = money_lbs(finance_weight_lbs) if finance_weight_lbs is not None else None

    if bid in do_included_ids:
        return {
            "bag_id": bid,
            "fate": "included",
            "exclusion_reason": None,
            "finance_weight_lbs": fin_lbs,
        }

    if bid in manual_exclusions:
        reason = EXCL_MANUAL
    elif day_bag is not None and str(day_bag.get("service_type") or "").upper() not in ("", "WF"):
        reason = EXCL_WRONG_WORKFLOW
    else:
        fin_comp_day = _completion_date_et(finance_completion_timestamp)
        day_comp_day = _completion_date_et(
            (day_bag or {}).get("canonical_completion_timestamp") if day_bag else None
        )
        completed_here = bool(day_bag) and _is_completed_status(day_bag.get("canonical_completion_status"))
        if (
            not completed_here
            and fin_comp_day is not None
            and fin_comp_day != operations_date_et
        ):
            reason = EXCL_COMPLETED_OUTSIDE_DAY
        elif (
            not completed_here
            and day_comp_day is not None
            and day_comp_day != operations_date_et
        ):
            reason = EXCL_COMPLETED_OUTSIDE_DAY
        elif bid not in membership_ids or day_bag is None:
            reason = EXCL_MISSING_MEMBERSHIP
        elif not completed_here:
            reason = EXCL_INCOMPLETE
        elif bid in do_missing_post_ids:
            reason = EXCL_MISSING_POST
        else:
            reason = EXCL_OTHER

    return {
        "bag_id": bid,
        "fate": "excluded",
        "exclusion_reason": reason,
        "exclusion_label": EXCLUSION_LABELS.get(reason, reason),
        "finance_weight_lbs": fin_lbs,
        "service_type": (day_bag or {}).get("service_type") if day_bag else None,
        "canonical_completion_status": (day_bag or {}).get("canonical_completion_status")
        if day_bag
        else None,
        "in_membership": bid in membership_ids,
    }


def fetch_finance_wf_suggestion_records(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, Any]:
    """Finance DRC workload suggestion with full bag records (even when total is 0)."""
    from backend.daily_revenue_cost_workload import (
        build_workload_wf_daily_pounds,
        _cursor_connection,
    )

    conn = _cursor_connection(cursor)
    empty = {
        "quantity": 0.0,
        "records": [],
        "counts": {},
        "available": False,
        "error": None,
    }
    if conn is None:
        empty["error"] = "no_connection"
        return empty
    try:
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else cursor
        from backend.rinse_at_vendor_module import build_at_vendor_module
        from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline

        baseline = build_baseline_context(cur, int(organization_id), get_shift_monitor_baseline(cur, int(organization_id)))
        av = build_at_vendor_module(
            cur,
            int(organization_id),
            selected_date_et=operations_date_et,
            baseline_ctx=baseline,
        )
        section = av.get("employee_completed_bags_today") or {}
        workload_summary = {
            "wf_completed": av.get("wf_completed"),
            "completed_today": av.get("completed") or av.get("completed_today_count"),
        }
        total, records, counts = build_workload_wf_daily_pounds(
            section, workload_summary=workload_summary
        )
        return {
            "quantity": float(total),
            "records": records,
            "counts": counts,
            "available": True,
            "error": None,
        }
    except Exception as exc:
        empty["error"] = str(exc)
        return empty


def reconcile_finance_wf_pounds_to_daily_operations(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    do_day: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Explain every Finance-suggested pound vs Daily Operations eligibility.

    Each Finance bag with pounds gets exactly one fate: included or one exclusion reason.
    """
    org = int(organization_id)
    if do_day is None:
        do_day = build_daily_operations_day(cursor, org, operations_date_et, persist=False)

    finance = fetch_finance_wf_suggestion_records(cursor, org, operations_date_et)
    day_bags = load_day_bag_index(cursor, org, operations_date_et)
    membership = load_day_membership_bag_ids(cursor, org, operations_date_et)
    manual = load_manual_daily_ops_exclusions(cursor, org, operations_date_et)

    drill = (do_day or {}).get("drilldowns") or {}
    included_rows = list(drill.get("included_wf_bags") or [])
    missing_rows = list(drill.get("missing_post_weight_bags") or [])
    do_included_by_id = {_norm_bag(r.get("bag_id")): r for r in included_rows}
    do_missing_ids = {_norm_bag(r.get("bag_id")) for r in missing_rows}
    do_included_ids = set(do_included_by_id.keys())
    do_pounds = float(((do_day or {}).get("revenue") or {}).get("wf_completed_pounds") or 0)

    excluded_buckets: dict[str, dict[str, Any]] = {
        key: {"reason": key, "label": EXCLUSION_LABELS[key], "pounds": 0.0, "bag_count": 0, "bags": []}
        for key in EXCLUSION_REASON_ORDER
    }
    included_from_finance: list[dict[str, Any]] = []
    finance_pounds_included = Decimal("0")
    finance_pounds_excluded = Decimal("0")
    finance_pounds_total = Decimal("0")
    seen_finance: set[str] = set()

    for rec in finance.get("records") or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("weight_missing") or rec.get("weight_lbs") is None:
            # Not part of Finance suggested pound total.
            continue
        bid = _norm_bag(rec.get("bag_id"))
        if not bid or bid in seen_finance:
            continue
        seen_finance.add(bid)
        fin_lbs = Decimal(str(rec.get("weight_lbs")))
        finance_pounds_total += fin_lbs
        classified = classify_finance_bag_vs_daily_operations(
            bag_id=bid,
            finance_weight_lbs=float(fin_lbs),
            operations_date_et=operations_date_et,
            day_bag=day_bags.get(bid),
            membership_ids=membership,
            manual_exclusions=manual,
            do_included_ids=do_included_ids,
            do_missing_post_ids=do_missing_ids,
            finance_completion_timestamp=rec.get("completion_timestamp"),
        )
        if classified["fate"] == "included":
            do_row = do_included_by_id.get(bid) or {}
            do_lbs = do_row.get("post_weight_lbs")
            delta = None
            if do_lbs is not None:
                delta = money_lbs(Decimal(str(fin_lbs)) - Decimal(str(do_lbs)))
            included_from_finance.append(
                {
                    **classified,
                    "daily_operations_weight_lbs": float(do_lbs) if do_lbs is not None else None,
                    "weight_delta_finance_minus_do": delta,
                    "post_weight_source": do_row.get("post_weight_source"),
                }
            )
            finance_pounds_included += fin_lbs
        else:
            reason = classified["exclusion_reason"] or EXCL_OTHER
            bucket = excluded_buckets[reason]
            bucket["bags"].append(classified)
            bucket["bag_count"] += 1
            bucket["pounds"] = money_lbs(Decimal(str(bucket["pounds"])) + fin_lbs)
            finance_pounds_excluded += fin_lbs

    # Bags eligible in Daily Ops but absent from Finance suggestion.
    only_in_do: list[dict[str, Any]] = []
    only_in_do_pounds = Decimal("0")
    for bid, row in do_included_by_id.items():
        if bid in seen_finance:
            continue
        lbs_v = row.get("post_weight_lbs")
        only_in_do.append(
            {
                "bag_id": bid,
                "daily_operations_weight_lbs": float(lbs_v) if lbs_v is not None else None,
                "post_weight_source": row.get("post_weight_source"),
                "note": "Eligible in Daily Operations but not present in Finance workload suggestion",
            }
        )
        if lbs_v is not None:
            only_in_do_pounds += Decimal(str(lbs_v))

    excluded_summary = [
        {
            "reason": key,
            "label": EXCLUSION_LABELS[key],
            "pounds": excluded_buckets[key]["pounds"],
            "bag_count": excluded_buckets[key]["bag_count"],
            "bags": excluded_buckets[key]["bags"],
        }
        for key in EXCLUSION_REASON_ORDER
    ]

    # Identity: every finance pound is either included or excluded once.
    identity_ok = money_lbs(finance_pounds_total) == money_lbs(
        finance_pounds_included + finance_pounds_excluded
    )
    unexplained_finance_bags = []  # reserved; classification always assigns a reason

    return {
        "operations_date_et": operations_date_et.isoformat(),
        "finance_suggested_pounds": money_lbs(finance_pounds_total),
        "finance_suggestion_available": bool(finance.get("available")),
        "finance_suggestion_error": finance.get("error"),
        "finance_bag_count_with_weight": len(seen_finance),
        "excluded": excluded_summary,
        "excluded_pounds_total": money_lbs(finance_pounds_excluded),
        "included_from_finance": {
            "bag_count": len(included_from_finance),
            "finance_pounds": money_lbs(finance_pounds_included),
            "bags": included_from_finance,
        },
        "only_in_daily_operations": {
            "bag_count": len(only_in_do),
            "pounds": money_lbs(only_in_do_pounds),
            "bags": only_in_do,
        },
        "daily_operations_eligible_pounds": do_pounds,
        "identity": {
            "finance_equals_included_plus_excluded": identity_ok,
            "finance_pounds": money_lbs(finance_pounds_total),
            "included_finance_pounds": money_lbs(finance_pounds_included),
            "excluded_finance_pounds": money_lbs(finance_pounds_excluded),
            "unexplained_finance_bags": unexplained_finance_bags,
            "every_excluded_bag_has_one_reason": True,
        },
        "bridge": {
            "formula": (
                "finance_suggested_pounds - excluded_pounds_total "
                "+ only_in_daily_operations.pounds ≈ daily_operations_eligible_pounds "
                "(weight-authority deltas on overlapping bags may remain)"
            ),
            "finance_minus_excluded": money_lbs(finance_pounds_total - finance_pounds_excluded),
            "plus_only_in_do": money_lbs(
                finance_pounds_total - finance_pounds_excluded + only_in_do_pounds
            ),
            "daily_operations_eligible_pounds": do_pounds,
        },
    }


def compare_daily_operations_to_finance_drc(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, Any]:
    """Compare Daily Ops WF math vs Finance DRC using shared allocator where possible."""
    from backend.daily_revenue_cost import get_wf_schedule_for_date, wf_revenue_for_day

    do_day = build_daily_operations_day(
        cursor, organization_id, operations_date_et, persist=False
    )
    if not do_day.get("available"):
        return {"available": False, "daily_operations": do_day}

    do_pounds = float((do_day.get("revenue") or {}).get("wf_completed_pounds") or 0)
    schedule_id, tiers = get_wf_schedule_for_date(cursor, organization_id, operations_date_et)
    drc_rev, drc_meta = wf_revenue_for_day(
        cursor, organization_id, operations_date_et, do_pounds, tiers=tiers or []
    )
    # Shared allocator with Daily Ops MTD (eligibility-based), for pricing-parity check.
    do_mtd_before = float((do_day.get("revenue") or {}).get("mtd_pounds_before") or 0)
    shared_same_inputs = allocate_wf_day_revenue_from_mtd(do_mtd_before, do_pounds, tiers or [])
    reconciliation = reconcile_finance_wf_pounds_to_daily_operations(
        cursor,
        organization_id,
        operations_date_et,
        do_day=do_day,
    )

    diffs = {
        "eligible_completed_pounds": {
            "daily_operations": do_pounds,
            "finance_drc_suggestion": reconciliation.get("finance_suggested_pounds"),
        },
        "mtd_pounds_before": {
            "daily_operations_eligibility_mtd": do_mtd_before,
            "finance_drc_entry_lines_mtd": drc_meta.get("mtd_pounds_before"),
        },
        "daily_weight_revenue": {
            "daily_operations": (do_day.get("revenue") or {}).get("wf_weight_revenue"),
            "finance_drc_with_do_day_pounds": drc_rev,
            "shared_allocator_with_do_mtd": shared_same_inputs.get("weight_revenue_today"),
        },
        "tier_allocation": {
            "daily_operations": (do_day.get("revenue") or {}).get("applied_tiers"),
            "finance_drc_with_do_day_pounds": drc_meta.get("applied_tiers"),
            "shared_allocator_with_do_mtd": shared_same_inputs.get("applied_tiers"),
        },
    }

    # Pricing logic parity: same mtd_before + day_pounds + tiers must match.
    pricing_logic_match = True
    if schedule_id and tiers:
        pricing_logic_match = float(shared_same_inputs["weight_revenue_today"]) == float(
            (do_day.get("revenue") or {}).get("wf_weight_revenue") or 0
        )

    return {
        "available": True,
        "operations_date_et": operations_date_et.isoformat(),
        "pricing_schedule_id": schedule_id,
        "pricing_logic_shared": True,
        "pricing_logic_match_on_same_inputs": pricing_logic_match,
        "differences": diffs,
        "pound_reconciliation": reconciliation,
        "notes": [
            "Finance DRC MTD-before comes from dr_daily_entry_lines; Daily Ops MTD-before sums eligibility pounds.",
            "Pound gaps are explained in pound_reconciliation with exactly one exclusion reason per Finance bag.",
            "When both use the same mtd_before, day_pounds, and tiers, they call allocate_wf_day_revenue_from_mtd.",
        ],
        "daily_operations_summary": {
            "pounds": do_pounds,
            "revenue": (do_day.get("revenue") or {}).get("wf_weight_revenue"),
            "pricing_incomplete": (do_day.get("revenue") or {}).get("pricing_incomplete"),
            "missing_post": (do_day.get("kpis") or {}).get("missing_post_weights"),
        },
    }
