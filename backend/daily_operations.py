"""Daily Operations Phase 1A — day header, WF pounds, MTD weight revenue."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.rinse_veewash_workload import STEP1_AUTHORITATIVE_START_ET, VEEWASH_ORG_ID
from backend.ta_helpers import table_exists, table_has_column
from backend.wf_mtd_pricing import (
    allocate_wf_day_revenue_from_mtd,
    lbs as money_lbs,
)

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


def compare_daily_operations_to_finance_drc(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, Any]:
    """Compare Daily Ops WF math vs Finance DRC using shared allocator where possible."""
    from backend.daily_revenue_cost import get_wf_schedule_for_date, wf_revenue_for_day
    from backend.daily_revenue_cost_workload import fetch_workload_wf_pounds_suggestion

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
    suggestion = fetch_workload_wf_pounds_suggestion(cursor, organization_id, operations_date_et)

    diffs = {
        "eligible_completed_pounds": {
            "daily_operations": do_pounds,
            "finance_drc_suggestion": float((suggestion or {}).get("quantity") or 0)
            if suggestion
            else None,
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
        "notes": [
            "Finance DRC MTD-before comes from dr_daily_entry_lines; Daily Ops MTD-before sums eligibility pounds.",
            "Finance DRC workload suggestion pounds may differ from Daily Ops POST-authority eligibility.",
            "When both use the same mtd_before, day_pounds, and tiers, they call allocate_wf_day_revenue_from_mtd.",
        ],
        "daily_operations_summary": {
            "pounds": do_pounds,
            "revenue": (do_day.get("revenue") or {}).get("wf_weight_revenue"),
            "pricing_incomplete": (do_day.get("revenue") or {}).get("pricing_incomplete"),
            "missing_post": (do_day.get("kpis") or {}).get("missing_post_weights"),
        },
    }
