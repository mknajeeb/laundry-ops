"""Daily Operations Phase 1B — unified WF bag review (POST + work items)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from backend.daily_operations import (
    STEP1_AUTHORITATIVE_START_ET,
    TRACKING_STARTED_MESSAGE,
    build_daily_operations_day,
    daily_operations_enabled_for_org,
    list_wf_completed_day_bags,
    resolve_authoritative_post_weight,
    resolve_evidence_post_weight,
    resolve_evidence_pre_weight,
    POST_SOURCE_MANAGER_CORRECTED,
    POST_SOURCE_MISSING,
    _norm_bag,
    _parse_weight,
    ensure_daily_operations_tables,
)
from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists, table_has_column
from backend.wf_mtd_pricing import allocate_wf_day_revenue_from_mtd, lbs as money_lbs, money

MONEY_Q = Decimal("0.01")
LBS_Q = Decimal("0.01")

STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_PARTIALLY_REVIEWED = "PARTIALLY_REVIEWED"
STATUS_REVIEWED = "REVIEWED"
STATUS_ACCEPTED_EXCEPTION = "ACCEPTED_EXCEPTION"

RES_BILLABLE_ITEMS = "BILLABLE_ITEMS"
RES_NO_BILLABLE_ITEMS = "NO_BILLABLE_ITEMS"
RES_ACCEPTED_MISSING_POST = "ACCEPTED_MISSING_POST"
RES_POST_CORRECTED = "POST_CORRECTED"

FILTER_ALL = "all"
FILTER_REVIEW_REQUIRED = "review_required"
FILTER_MISSING_POST = "missing_post"
FILTER_WORK_ITEMS = "work_items_detected"
FILTER_REVIEWED = "reviewed"
FILTER_ACCEPTED = "accepted_exceptions"
FILTER_CORRECTED_POST = "corrected_post"


def ensure_wf_review_tables(cursor) -> None:
    ensure_daily_operations_tables(cursor)
    if not table_exists(cursor, "wf_day_bag_revenue"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wf_day_bag_revenue (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              operations_date_et DATE NOT NULL,
              day_bag_id BIGINT NULL,
              bag_id VARCHAR(32) NOT NULL,
              authoritative_post_weight_lbs DECIMAL(10,4) NULL,
              post_weight_source VARCHAR(64) NULL,
              post_weight_scan_event_id BIGINT NULL,
              post_weight_presence_run_id BIGINT NULL,
              post_weight_presence_run_row_id BIGINT NULL,
              post_weight_corrected TINYINT(1) NOT NULL DEFAULT 0,
              original_post_weight_lbs DECIMAL(10,4) NULL,
              post_weight_correction_reason VARCHAR(512) NULL,
              estimated_weight_revenue DECIMAL(12,2) NULL,
              workitem_revenue DECIMAL(12,2) NOT NULL DEFAULT 0,
              estimated_total_revenue DECIMAL(12,2) NULL,
              review_status VARCHAR(32) NOT NULL DEFAULT 'REVIEW_REQUIRED',
              review_resolution VARCHAR(64) NULL,
              reviewed_by_user_id INT NULL,
              reviewed_at DATETIME NULL,
              notes TEXT NULL,
              version INT NOT NULL DEFAULT 1,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_wf_day_bag_rev (organization_id, operations_date_et, bag_id),
              INDEX idx_wf_day_bag_rev_status (organization_id, operations_date_et, review_status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, "wf_day_bag_revenue_audits"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wf_day_bag_revenue_audits (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              operations_date_et DATE NOT NULL,
              bag_id VARCHAR(32) NOT NULL,
              wf_day_bag_revenue_id BIGINT NULL,
              action VARCHAR(64) NOT NULL,
              version_before INT NULL,
              version_after INT NULL,
              before_json JSON NULL,
              after_json JSON NULL,
              reason VARCHAR(512) NULL,
              actor_user_id INT NULL,
              actor_display_name VARCHAR(255) NULL,
              is_undo TINYINT(1) NOT NULL DEFAULT 0,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_wf_bag_rev_aud_bag (organization_id, operations_date_et, bag_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def get_wf_day_bag_revenue_row(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
) -> dict[str, Any] | None:
    ensure_wf_review_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM wf_day_bag_revenue
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), operations_date_et, _norm_bag(bag_id)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def resolve_post_weight_for_daily_ops(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    operations_date_et: date,
) -> dict[str, Any]:
    """
    POST authority for Daily Ops Phase 1B:
    1. Active manager correction on wf_day_bag_revenue
    2. Existing Phase 1A resolver (step1 correction → POST role → canonical)
    """
    bid = _norm_bag(bag_id)
    fact = get_wf_day_bag_revenue_row(cursor, organization_id, operations_date_et, bid)
    if fact and int(fact.get("post_weight_corrected") or 0) == 1 and fact.get("authoritative_post_weight_lbs") is not None:
        return {
            "bag_id": bid,
            "weight_lbs": float(fact["authoritative_post_weight_lbs"]),
            "source": POST_SOURCE_MANAGER_CORRECTED,
            "scan_event_id": fact.get("post_weight_scan_event_id"),
            "presence_run_id": fact.get("post_weight_presence_run_id"),
            "presence_run_row_id": fact.get("post_weight_presence_run_row_id"),
            "missing": False,
            "corrected": True,
            "original_post_weight_lbs": float(fact["original_post_weight_lbs"])
            if fact.get("original_post_weight_lbs") is not None
            else None,
            "correction_reason": fact.get("post_weight_correction_reason"),
            "fact_version": int(fact.get("version") or 1),
        }
    base = resolve_authoritative_post_weight(
        cursor, organization_id, bid, operations_date_et=operations_date_et
    )
    base["corrected"] = False
    if fact:
        base["fact_version"] = int(fact.get("version") or 1)
    return base


def allocate_estimated_bag_weight_revenues(
    *,
    day_weight_revenue: Any,
    bags: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Reporting-only allocation:
    estimated = day_rev × bag_lbs / day_total_lbs
    Residual cents assigned deterministically by bag_id order.
    """
    day_rev = _d(day_weight_revenue).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    eligible = []
    for b in bags:
        bid = _norm_bag(b.get("bag_id"))
        lbs_v = b.get("post_weight_lbs")
        if bid and lbs_v is not None:
            eligible.append({"bag_id": bid, "lbs": _d(lbs_v)})
    eligible.sort(key=lambda x: x["bag_id"])
    total_lbs = sum((x["lbs"] for x in eligible), Decimal("0"))
    if day_rev <= 0 or total_lbs <= 0:
        return [
            {
                "bag_id": x["bag_id"],
                "estimated_weight_revenue": 0.0,
                "allocation_note": "reporting_estimate_zero_base",
            }
            for x in eligible
        ]

    allocated: list[dict[str, Any]] = []
    running = Decimal("0")
    for i, row in enumerate(eligible):
        if i == len(eligible) - 1:
            share = (day_rev - running).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        else:
            raw = (day_rev * row["lbs"] / total_lbs).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            share = raw
            running += share
        allocated.append(
            {
                "bag_id": row["bag_id"],
                "estimated_weight_revenue": money(share),
                "allocation_note": "reporting_estimate_only",
            }
        )
    return allocated


def _workitem_activity_detected(cursor, organization_id: int, bag_id: str) -> dict[str, Any]:
    from backend.rinse_bulk_workitems import load_bulk_workitem_scan_map

    m = load_bulk_workitem_scan_map(cursor, organization_id, [bag_id]).get(_norm_bag(bag_id)) or {}
    return {
        "detected": bool(int(m.get("count") or 0) > 0),
        "count": int(m.get("count") or 0),
        "first_at": m.get("first_at"),
        "last_at": m.get("last_at"),
        "purposes": m.get("purposes") or [],
    }


def _bulk_review_unresolved(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    *,
    review_reason_codes_json: Any = None,
) -> bool:
    from backend.rinse_bulk_workitems import (
        REASON_WF_BULK_WORKITEM_REVIEW,
        bag_bulk_review_cleared,
        load_bag_bulk_lines,
        load_bulk_resolutions,
    )

    blob = review_reason_codes_json
    if not isinstance(blob, str):
        blob = json.dumps(blob or [])
    activity = _workitem_activity_detected(cursor, organization_id, bag_id)
    if REASON_WF_BULK_WORKITEM_REVIEW not in blob and not activity["detected"]:
        # Still check unresolved resolution rows / lines for bags already in review.
        pass
    bid = _norm_bag(bag_id)
    res = load_bulk_resolutions(cursor, organization_id, operations_date_et, [bid]).get(bid)
    lines = load_bag_bulk_lines(cursor, organization_id, operations_date_et, [bid]).get(bid)
    needs = REASON_WF_BULK_WORKITEM_REVIEW in blob or activity["detected"]
    if not needs and not res and not lines:
        return False
    if needs and not bag_bulk_review_cleared(res, lines):
        return True
    return False


def _queue_flags_for_bag(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_row: Mapping[str, Any],
    post: Mapping[str, Any],
    fact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    bid = _norm_bag(bag_row.get("bag_id"))
    missing_post = bool(post.get("missing") or post.get("weight_lbs") is None)
    activity = _workitem_activity_detected(cursor, organization_id, bid)
    unresolved_wi = _bulk_review_unresolved(
        cursor,
        organization_id,
        operations_date_et,
        bid,
        review_reason_codes_json=bag_row.get("review_reason_codes_json"),
    )
    corrected = bool(post.get("corrected") or (fact and int(fact.get("post_weight_corrected") or 0)))
    status = str((fact or {}).get("review_status") or STATUS_REVIEW_REQUIRED)
    resolution = (fact or {}).get("review_resolution")
    explicit_open = status == STATUS_REVIEW_REQUIRED and fact is not None and not resolution

    review_required = False
    if missing_post and status != STATUS_ACCEPTED_EXCEPTION:
        review_required = True
    if unresolved_wi:
        review_required = True
    if activity["detected"] and status not in (STATUS_REVIEWED, STATUS_ACCEPTED_EXCEPTION):
        # Detected activity needs explicit billable / no-billable confirmation.
        from backend.rinse_bulk_workitems import bag_bulk_review_cleared, load_bag_bulk_lines, load_bulk_resolutions

        res = load_bulk_resolutions(cursor, organization_id, operations_date_et, [bid]).get(bid)
        lines = load_bag_bulk_lines(cursor, organization_id, operations_date_et, [bid]).get(bid)
        if not bag_bulk_review_cleared(res, lines):
            review_required = True
    if corrected and status == STATUS_REVIEW_REQUIRED:
        review_required = True
    if explicit_open:
        review_required = True

    return {
        "missing_post": missing_post,
        "work_items_detected": activity["detected"],
        "workitem_review_unresolved": unresolved_wi,
        "post_corrected": corrected,
        "review_required": review_required,
        "activity": activity,
        "review_status": status,
        "review_resolution": resolution,
    }


def build_wf_review_queue(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    filter_key: str = FILTER_ALL,
) -> dict[str, Any]:
    org = int(organization_id)
    ensure_wf_review_tables(cursor)
    if not daily_operations_enabled_for_org(org):
        return {"available": False, "reason": "not_enabled"}
    if operations_date_et < STEP1_AUTHORITATIVE_START_ET:
        return {"available": False, "message": TRACKING_STARTED_MESSAGE}

    completed = list_wf_completed_day_bags(cursor, org, operations_date_et)
    items: list[dict[str, Any]] = []
    for row in completed:
        bid = _norm_bag(row.get("bag_id"))
        post = resolve_post_weight_for_daily_ops(cursor, org, bid, operations_date_et=operations_date_et)
        fact = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
        flags = _queue_flags_for_bag(cursor, org, operations_date_et, row, post, fact)
        pre = resolve_evidence_pre_weight(cursor, org, bid)
        # Queue includes bags that need review OR already have a fact/reviewed state for filters.
        include = (
            flags["review_required"]
            or flags["missing_post"]
            or flags["work_items_detected"]
            or flags["post_corrected"]
            or fact is not None
        )
        if not include:
            continue
        item = {
            "bag_id": bid,
            "day_bag_id": row.get("day_bag_id"),
            "service_type": "WF",
            "canonical_completion_status": row.get("canonical_completion_status"),
            "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
            "pre_weight_lbs": pre.get("weight_lbs"),
            "pre_weight_source": pre.get("source"),
            "pre_weight_at": pre.get("observed_at"),
            "post_weight_lbs": post.get("weight_lbs"),
            "post_weight_source": post.get("source"),
            "post_weight_corrected": flags["post_corrected"],
            "review_status": flags["review_status"],
            "review_resolution": flags["review_resolution"],
            "version": int((fact or {}).get("version") or post.get("fact_version") or 1),
            "flags": flags,
            "workitem_revenue": float((fact or {}).get("workitem_revenue") or 0),
            "estimated_weight_revenue": float(fact["estimated_weight_revenue"])
            if fact and fact.get("estimated_weight_revenue") is not None
            else None,
        }
        items.append(item)

    fk = str(filter_key or FILTER_ALL).strip().lower()
    filtered = []
    for it in items:
        f = it["flags"]
        if fk == FILTER_ALL:
            filtered.append(it)
        elif fk == FILTER_REVIEW_REQUIRED and f["review_required"]:
            filtered.append(it)
        elif fk == FILTER_MISSING_POST and f["missing_post"]:
            filtered.append(it)
        elif fk == FILTER_WORK_ITEMS and f["work_items_detected"]:
            filtered.append(it)
        elif fk == FILTER_REVIEWED and it["review_status"] == STATUS_REVIEWED:
            filtered.append(it)
        elif fk == FILTER_ACCEPTED and it["review_status"] == STATUS_ACCEPTED_EXCEPTION:
            filtered.append(it)
        elif fk == FILTER_CORRECTED_POST and f["post_corrected"]:
            filtered.append(it)

    return {
        "available": True,
        "operations_date_et": operations_date_et.isoformat(),
        "filter": fk,
        "count": len(filtered),
        "items": filtered,
        "jul23_membership_rebuild": False,
    }


def get_wf_review_detail(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
) -> dict[str, Any]:
    from backend.rinse_bulk_workitems import (
        list_workitems,
        load_bag_bulk_audits,
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )

    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    ensure_wf_review_tables(cursor)
    completed = {
        _norm_bag(r.get("bag_id")): r
        for r in list_wf_completed_day_bags(cursor, org, operations_date_et)
    }
    row = completed.get(bid)
    if not row:
        return {"ok": False, "error": "bag_not_completed_wf_on_day", "bag_id": bid}

    post = resolve_post_weight_for_daily_ops(cursor, org, bid, operations_date_et=operations_date_et)
    evidence_post = resolve_evidence_post_weight(
        cursor, org, bid, operations_date_et=operations_date_et
    )
    evidence_pre = resolve_evidence_pre_weight(cursor, org, bid)
    fact = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
    evidence_weight = evidence_post.get("weight_lbs")
    if fact and fact.get("original_post_weight_lbs") is not None:
        evidence_weight = float(fact["original_post_weight_lbs"])
    evidence_post_ts = evidence_post.get("observed_at")
    if evidence_post.get("scan_event_id") and not evidence_post_ts and table_exists(
        cursor, "rinse_bag_scan_events"
    ):
        cursor.execute(
            """
            SELECT COALESCE(weight_observed_at, scanned_at_parsed) AS observed_at
            FROM rinse_bag_scan_events WHERE id = %s LIMIT 1
            """,
            (int(evidence_post["scan_event_id"]),),
        )
        ts_row = cursor.fetchone() or {}
        evidence_post_ts = ts_row.get("observed_at")

    lines = load_bag_bulk_lines(cursor, org, operations_date_et, [bid]).get(bid) or []
    resolution = load_bulk_resolutions(cursor, org, operations_date_et, [bid]).get(bid)
    audits = load_bag_bulk_audits(cursor, org, operations_date_et, [bid]).get(bid) or []
    scan = load_bulk_workitem_scan_map(cursor, org, [bid]).get(bid) or {}
    catalog = list_workitems(cursor, org, active_only=True)
    flags = _queue_flags_for_bag(cursor, org, operations_date_et, row, post, fact)

    wi_rev = sum(float(x.get("line_total") or 0) for x in lines)
    if resolution and str(resolution.get("resolution_type") or "") == "no_charge":
        wi_rev = 0.0

    # Enrich scan event provenance when available
    presence_run_id = post.get("presence_run_id")
    presence_run_row_id = post.get("presence_run_row_id")
    if post.get("scan_event_id") and table_exists(cursor, "rinse_bag_scan_events"):
        cols = "id, weight_lbs, weight_role, weight_source"
        if table_has_column(cursor, "rinse_bag_scan_events", "weight_presence_run_id"):
            cols += ", weight_presence_run_id, weight_presence_run_row_id"
        cursor.execute(
            f"SELECT {cols} FROM rinse_bag_scan_events WHERE id = %s LIMIT 1",
            (int(post["scan_event_id"]),),
        )
        sev = cursor.fetchone() or {}
        presence_run_id = presence_run_id or sev.get("weight_presence_run_id")
        presence_run_row_id = presence_run_row_id or sev.get("weight_presence_run_row_id")

    cursor.execute(
        """
        SELECT id, action, version_before, version_after, before_json, after_json,
               reason, actor_user_id, actor_display_name, is_undo, created_at
        FROM wf_day_bag_revenue_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
        ORDER BY id DESC
        LIMIT 25
        """,
        (org, operations_date_et, bid),
    )
    do_audits = []
    for a in cursor.fetchall() or []:
        do_audits.append(
            {
                **dict(a),
                "before": _json_load(a.get("before_json")),
                "after": _json_load(a.get("after_json")),
            }
        )

    return {
        "ok": True,
        "operations_date_et": operations_date_et.isoformat(),
        "bag": {
            "bag_id": bid,
            "service_type": "WF",
            "day_bag_id": row.get("day_bag_id"),
            "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
            "canonical_completion_status": row.get("canonical_completion_status"),
            "membership_source": "rinse_shift_monitor_day_bags + rinse_et_day_workload_ledger",
            "rush_status": row.get("rush_flag") or row.get("rush_status"),
        },
        "pre_weight": {
            "weight_lbs": evidence_pre.get("weight_lbs"),
            "timestamp": evidence_pre.get("observed_at"),
            "source": evidence_pre.get("source"),
            "scan_event_id": evidence_pre.get("scan_event_id"),
            "presence_run_id": evidence_pre.get("presence_run_id"),
            "presence_run_row_id": evidence_pre.get("presence_run_row_id"),
            "weight_source": evidence_pre.get("weight_source"),
            "missing": bool(evidence_pre.get("missing")),
            "editable": False,
        },
        "post_weight": {
            "evidence_post_weight_lbs": evidence_weight,
            "evidence_source": evidence_post.get("source"),
            "evidence_timestamp": evidence_post_ts or evidence_post.get("observed_at"),
            "authoritative_post_weight_lbs": post.get("weight_lbs"),
            "authoritative_source": post.get("source"),
            "scan_event_id": post.get("scan_event_id") or evidence_post.get("scan_event_id"),
            "presence_run_id": presence_run_id or evidence_post.get("presence_run_id"),
            "presence_run_row_id": presence_run_row_id or evidence_post.get("presence_run_row_id"),
            "manager_corrected": bool(post.get("corrected")),
            "original_post_weight_lbs": post.get("original_post_weight_lbs")
            if post.get("corrected")
            else evidence_weight,
            "correction_reason": post.get("correction_reason"),
            "missing": bool(post.get("missing") or evidence_post.get("missing")),
        },
        # Compact PRE/POST visibility for operational dashboards (PRE immutable).
        "weight_summary": {
            "pre_weight": evidence_pre.get("weight_lbs"),
            "pre_timestamp": evidence_pre.get("observed_at"),
            "pre_source": evidence_pre.get("source"),
            "post_weight": evidence_weight,
            "post_timestamp": evidence_post_ts or evidence_post.get("observed_at"),
            "post_source": evidence_post.get("source"),
            "manager_corrected_post": float(post["weight_lbs"])
            if post.get("corrected") and post.get("weight_lbs") is not None
            else None,
            "authoritative_post_weight": post.get("weight_lbs"),
            "pre_editable": False,
            "post_editable": True,
        },
        "workitems": {
            "catalog": catalog,
            "lines": lines,
            "resolution": resolution,
            "detected_evidence": scan,
            "audits": audits[:20],
            "workitem_revenue": wi_rev,
        },
        "review": {
            "status": flags["review_status"],
            "resolution": flags["review_resolution"],
            "flags": flags,
            "notes": (fact or {}).get("notes"),
            "version": int((fact or {}).get("version") or 1),
            "reviewed_at": (fact or {}).get("reviewed_at"),
            "reviewed_by_user_id": (fact or {}).get("reviewed_by_user_id"),
            "estimated_weight_revenue": float(fact["estimated_weight_revenue"])
            if fact and fact.get("estimated_weight_revenue") is not None
            else None,
            "estimated_total_revenue": float(fact["estimated_total_revenue"])
            if fact and fact.get("estimated_total_revenue") is not None
            else None,
        },
        "audits": do_audits,
        "labels": {
            "evidence_pre": "Evidence PRE Weight",
            "evidence_post": "Evidence POST Weight",
            "manager_corrected_post": "Manager-Corrected POST Weight",
            "estimated_bag_weight_revenue": "Estimated Bag Weight Revenue",
            "workitem_revenue": "Work-Item Revenue",
            "estimated_bag_total": "Estimated Bag Total",
            "day_level_impact": "Day-Level Revenue Impact",
            "estimated_allocation_note": "Estimated allocation for reporting only",
            "pre_immutable": "PRE is evidence-only and not editable",
        },
    }


def preview_wf_review_save(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    detail = get_wf_review_detail(cursor, org, operations_date_et, bid)
    if not detail.get("ok"):
        return detail

    day = build_daily_operations_day(cursor, org, operations_date_et, persist=False)
    current_post = detail["post_weight"]["authoritative_post_weight_lbs"]
    proposed = payload.get("corrected_post_weight_lbs", payload.get("post_weight_lbs"))
    if proposed is None or proposed == "":
        proposed_post = current_post
        correcting = False
    else:
        proposed_post = _parse_weight(proposed)
        correcting = True

    items = list(payload.get("items") or [])
    no_billable = bool(payload.get("no_billable_items") or payload.get("no_chargeable"))
    accept_missing = bool(payload.get("accept_missing_post"))

    wi_subtotal = Decimal("0")
    if no_billable:
        wi_subtotal = Decimal("0")
    else:
        from backend.rinse_bulk_workitems import get_workitem, list_workitems

        catalog = {int(w["id"]): w for w in list_workitems(cursor, org, active_only=False)}
        for raw in items:
            wid = int(raw.get("workitem_id") or raw.get("id") or 0)
            qty = int(raw.get("quantity") or 0)
            if wid <= 0 or qty <= 0:
                continue
            wi = catalog.get(wid) or get_workitem(cursor, org, wid)
            if not wi:
                continue
            unit = _d(wi.get("current_unit_price"))
            wi_subtotal += (unit * qty).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    # Day pounds impact
    included = list((day.get("drilldowns") or {}).get("included_wf_bags") or [])
    missing = list((day.get("drilldowns") or {}).get("missing_post_weight_bags") or [])
    current_day_lbs = _d((day.get("revenue") or {}).get("wf_completed_pounds") or 0)
    current_rev = (day.get("revenue") or {}).get("wf_weight_revenue")
    mtd_before = _d((day.get("revenue") or {}).get("mtd_pounds_before") or 0)
    tiers = ((day.get("revenue") or {}).get("pricing_schedule") or {}).get("tiers") or []

    # Rebuild projected pounds: replace this bag's contribution
    projected_lbs = current_day_lbs
    was_included = any(_norm_bag(x.get("bag_id")) == bid for x in included)
    old_lbs = Decimal("0")
    for x in included:
        if _norm_bag(x.get("bag_id")) == bid and x.get("post_weight_lbs") is not None:
            old_lbs = _d(x.get("post_weight_lbs"))
            break
    if was_included:
        projected_lbs -= old_lbs
    if accept_missing or proposed_post is None:
        new_lbs = Decimal("0")
    else:
        new_lbs = _d(proposed_post)
        projected_lbs += new_lbs
    if projected_lbs < 0:
        projected_lbs = Decimal("0")

    pricing_incomplete = bool((day.get("revenue") or {}).get("pricing_incomplete"))
    if pricing_incomplete or not tiers:
        projected_alloc = {"weight_revenue_today": None, "applied_tiers": [], "pricing_complete": False}
        current_alloc = {"weight_revenue_today": current_rev, "applied_tiers": (day.get("revenue") or {}).get("applied_tiers")}
    else:
        current_alloc = allocate_wf_day_revenue_from_mtd(mtd_before, current_day_lbs, tiers)
        projected_alloc = allocate_wf_day_revenue_from_mtd(mtd_before, projected_lbs, tiers)

    # Estimated bag weight revenue under projected day
    bag_rows = []
    for x in included:
        b = _norm_bag(x.get("bag_id"))
        if b == bid:
            continue
        bag_rows.append({"bag_id": b, "post_weight_lbs": x.get("post_weight_lbs")})
    if proposed_post is not None and not accept_missing:
        bag_rows.append({"bag_id": bid, "post_weight_lbs": float(proposed_post)})
    est_map = {
        a["bag_id"]: a["estimated_weight_revenue"]
        for a in allocate_estimated_bag_weight_revenues(
            day_weight_revenue=projected_alloc.get("weight_revenue_today") or 0,
            bags=bag_rows,
        )
    }
    est_bag = est_map.get(bid)
    est_total = None
    if est_bag is not None:
        est_total = money(_d(est_bag) + wi_subtotal)

    return {
        "ok": True,
        "bag_id": bid,
        "current_authoritative_post": current_post,
        "proposed_corrected_post": float(proposed_post) if proposed_post is not None else None,
        "correcting_post": correcting and proposed_post != current_post,
        "accept_missing_post": accept_missing,
        "day_pounds": {
            "current": money_lbs(current_day_lbs),
            "projected": money_lbs(projected_lbs),
            "delta": money_lbs(projected_lbs - current_day_lbs),
        },
        "day_weight_revenue": {
            "current": current_rev,
            "projected": projected_alloc.get("weight_revenue_today"),
            "current_tiers": current_alloc.get("applied_tiers"),
            "projected_tiers": projected_alloc.get("applied_tiers"),
            "pricing_incomplete": pricing_incomplete,
        },
        "workitem_subtotal": money(wi_subtotal),
        "estimated_bag_weight_revenue": est_bag,
        "estimated_bag_total_revenue": est_total,
        "estimated_allocation_note": "Estimated allocation for reporting only",
        "exceptions_impact": {
            "missing_post_currently": any(_norm_bag(x.get("bag_id")) == bid for x in missing),
            "missing_post_after": bool(accept_missing or proposed_post is None),
        },
        "labels": detail.get("labels"),
    }


def _validate_save_payload(payload: Mapping[str, Any], *, current_post: Any) -> list[str]:
    errors: list[str] = []
    accept_missing = bool(payload.get("accept_missing_post"))
    no_billable = bool(payload.get("no_billable_items") or payload.get("no_chargeable"))
    items = list(payload.get("items") or [])
    reason = str(payload.get("reason") or "").strip()
    reason_code = str(payload.get("reason_code") or "").strip().upper()
    reason_note = str(payload.get("reason_note") or reason).strip()
    corr_reason = str(payload.get("post_weight_correction_reason") or reason_note or reason).strip()

    corrected_raw = payload.get("corrected_post_weight_lbs", payload.get("post_weight_lbs"))
    correcting = corrected_raw not in (None, "")
    post_materially_changed = False
    if correcting:
        lbs_v = _parse_weight(corrected_raw)
        if lbs_v is None:
            errors.append("invalid_post_weight")
        elif lbs_v < 0:
            errors.append("negative_post_weight_rejected")
        else:
            post_materially_changed = current_post is None or float(lbs_v) != float(current_post)
            if lbs_v == 0 and not (reason_code or corr_reason):
                errors.append("zero_post_requires_reason")
            elif post_materially_changed and not (reason_code or corr_reason):
                errors.append("post_correction_reason_code_required")
            elif post_materially_changed and reason_code == "OTHER" and not reason_note and not corr_reason:
                errors.append("reason_note_required_for_other")
    elif accept_missing:
        if not (reason_code or reason):
            errors.append("accepted_missing_post_reason_code_required")
        elif reason_code == "OTHER" and not reason_note:
            errors.append("reason_note_required_for_other")
    else:
        if current_post is None and not correcting:
            errors.append("missing_post_requires_correction_or_accept")

    # Explicit work-item resolution required — never imply from empty lines.
    if no_billable:
        if not str(payload.get("no_billable_reason") or payload.get("no_charge_reason") or reason).strip():
            errors.append("no_billable_reason_required")
    else:
        positive = any(int(x.get("quantity") or 0) > 0 for x in items)
        if not positive:
            errors.append("explicit_workitem_resolution_required")

    # Routine work-item / review saves do NOT require a free-text reason.
    return errors


def save_wf_review(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Atomic unified save: POST correction + work items + review fact + audit."""
    from backend.rinse_bulk_workitems import save_bag_bulk_workitems
    from backend.rinse_veewash_step1_api import _record_correction

    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    ensure_wf_review_tables(cursor)
    detail = get_wf_review_detail(cursor, org, operations_date_et, bid)
    if not detail.get("ok"):
        return detail

    expected_version = payload.get("version")
    fact = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
    current_version = int((fact or {}).get("version") or 1)
    if expected_version is not None and int(expected_version) != current_version:
        return {
            "ok": False,
            "error": "conflict",
            "status": 409,
            "current_version": current_version,
            "current": detail,
        }

    current_post = detail["post_weight"]["authoritative_post_weight_lbs"]
    evidence_post = detail["post_weight"]["evidence_post_weight_lbs"]
    errors = _validate_save_payload(payload, current_post=current_post)
    if errors:
        return {"ok": False, "error": "validation_failed", "errors": errors}

    reason_code = str(payload.get("reason_code") or "").strip().upper() or None
    reason_note = str(payload.get("reason_note") or payload.get("reason") or "").strip() or None
    notes = str(payload.get("notes") or "").strip() or None
    accept_missing = bool(payload.get("accept_missing_post"))
    no_billable = bool(payload.get("no_billable_items") or payload.get("no_chargeable"))
    corrected_raw = payload.get("corrected_post_weight_lbs", payload.get("post_weight_lbs"))
    correcting = corrected_raw not in (None, "")
    corrected_lbs = _parse_weight(corrected_raw) if correcting else None
    corr_reason = str(
        payload.get("post_weight_correction_reason") or reason_note or reason_code or ""
    ).strip()

    # System action codes for routine saves (audit still recorded).
    post_changed = correcting and corrected_lbs is not None and (
        current_post is None or float(corrected_lbs) != float(current_post)
    )
    if post_changed or accept_missing:
        reason = corr_reason or (
            f"{reason_code}: {reason_note}" if reason_code and reason_note else (reason_code or reason_note or "")
        )
    else:
        reason = reason_note or ("WORKITEMS_UPDATED" if not no_billable else "REVIEW_SAVED")

    before_state = {
        "fact": fact,
        "post": detail["post_weight"],
        "workitems": detail["workitems"]["lines"],
        "resolution": detail["workitems"]["resolution"],
        "review": detail["review"],
    }

    # 1) Work items via existing saver
    if no_billable:
        wi_out = save_bag_bulk_workitems(
            cursor,
            org,
            shift_date_et=operations_date_et,
            bag_id=bid,
            items=[],
            no_chargeable=True,
            no_charge_reason=str(
                payload.get("no_billable_reason") or payload.get("no_charge_reason") or reason
            ).strip(),
            reason=reason,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            allow_closed=True,
            allow_system_audit_reason=True,
        )
        if not wi_out.get("ok"):
            return {"ok": False, "error": "workitem_save_failed", "detail": wi_out}
        review_resolution = RES_NO_BILLABLE_ITEMS
        workitem_revenue = 0.0
    else:
        items = [
            {"workitem_id": int(x.get("workitem_id") or x.get("id")), "quantity": int(x.get("quantity") or 0)}
            for x in (payload.get("items") or [])
            if int(x.get("quantity") or 0) > 0 and int(x.get("workitem_id") or x.get("id") or 0) > 0
        ]
        if not items and not payload.get("skip_workitem_resolution"):
            return {"ok": False, "error": "explicit_workitem_resolution_required"}
        wi_out = save_bag_bulk_workitems(
            cursor,
            org,
            shift_date_et=operations_date_et,
            bag_id=bid,
            items=items,
            no_chargeable=False,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            allow_closed=True,
            allow_system_audit_reason=True,
        )
        if not wi_out.get("ok"):
            return {"ok": False, "error": "workitem_save_failed", "detail": wi_out}
        review_resolution = RES_BILLABLE_ITEMS
        workitem_revenue = float(wi_out.get("items_total") or 0)

    # 2) POST correction overlay + step1 correction for shared resolver
    post_corrected = 0
    authoritative = current_post
    original = evidence_post
    post_source = detail["post_weight"]["authoritative_source"]
    scan_event_id = detail["post_weight"].get("scan_event_id")
    presence_run_id = detail["post_weight"].get("presence_run_id")
    presence_run_row_id = detail["post_weight"].get("presence_run_row_id")

    if accept_missing:
        authoritative = None
        post_source = "accepted_missing_post"
        review_status = STATUS_ACCEPTED_EXCEPTION
        base_res = review_resolution
        review_resolution = (
            f"{base_res}+{RES_ACCEPTED_MISSING_POST}"
            if base_res in (RES_BILLABLE_ITEMS, RES_NO_BILLABLE_ITEMS)
            else RES_ACCEPTED_MISSING_POST
        )
    elif correcting and corrected_lbs is not None:
        if current_post is None or float(corrected_lbs) != float(current_post):
            post_corrected = 1
            authoritative = float(corrected_lbs)
            post_source = POST_SOURCE_MANAGER_CORRECTED
            _record_correction(
                cursor,
                org,
                bag_id=bid,
                action="correct_weight",
                reason_text=corr_reason,
                reason_code="DAILY_OPS_WF_REVIEW",
                previous_values={
                    "post_weight_lbs": current_post,
                    "operations_date_et": operations_date_et.isoformat(),
                },
                new_values={
                    "post_weight_lbs": float(corrected_lbs),
                    "corrected_post_weight_lbs": float(corrected_lbs),
                    "operations_date_et": operations_date_et.isoformat(),
                },
                actor_user_id=actor_user_id,
                actor_display_name=actor_display_name,
            )
            # Mirror onto day_bags projection for Shift Monitor display (does not touch scan/presence).
            cursor.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET post_weight_lbs = %s, weight_lbs = %s
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (float(corrected_lbs), float(corrected_lbs), org, operations_date_et, bid),
            )
        review_status = STATUS_REVIEWED
        if review_resolution == RES_BILLABLE_ITEMS or review_resolution == RES_NO_BILLABLE_ITEMS:
            pass
        if post_corrected:
            # Coexist marker
            if review_resolution in (RES_BILLABLE_ITEMS, RES_NO_BILLABLE_ITEMS):
                review_resolution = f"{review_resolution}+{RES_POST_CORRECTED}"
            else:
                review_resolution = RES_POST_CORRECTED
    else:
        authoritative = float(current_post) if current_post is not None else None
        review_status = STATUS_REVIEWED

    new_version = current_version + 1
    day_bag_id = detail["bag"].get("day_bag_id")

    cursor.execute(
        """
        INSERT INTO wf_day_bag_revenue (
          organization_id, operations_date_et, day_bag_id, bag_id,
          authoritative_post_weight_lbs, post_weight_source, post_weight_scan_event_id,
          post_weight_presence_run_id, post_weight_presence_run_row_id,
          post_weight_corrected, original_post_weight_lbs, post_weight_correction_reason,
          estimated_weight_revenue, workitem_revenue, estimated_total_revenue,
          review_status, review_resolution, reviewed_by_user_id, reviewed_at, notes, version
        ) VALUES (
          %s, %s, %s, %s,
          %s, %s, %s,
          %s, %s,
          %s, %s, %s,
          NULL, %s, NULL,
          %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
          day_bag_id=VALUES(day_bag_id),
          authoritative_post_weight_lbs=VALUES(authoritative_post_weight_lbs),
          post_weight_source=VALUES(post_weight_source),
          post_weight_scan_event_id=VALUES(post_weight_scan_event_id),
          post_weight_presence_run_id=VALUES(post_weight_presence_run_id),
          post_weight_presence_run_row_id=VALUES(post_weight_presence_run_row_id),
          post_weight_corrected=VALUES(post_weight_corrected),
          original_post_weight_lbs=VALUES(original_post_weight_lbs),
          post_weight_correction_reason=VALUES(post_weight_correction_reason),
          workitem_revenue=VALUES(workitem_revenue),
          review_status=VALUES(review_status),
          review_resolution=VALUES(review_resolution),
          reviewed_by_user_id=VALUES(reviewed_by_user_id),
          reviewed_at=VALUES(reviewed_at),
          notes=VALUES(notes),
          version=VALUES(version)
        """,
        (
            org,
            operations_date_et,
            day_bag_id,
            bid,
            authoritative,
            post_source,
            scan_event_id,
            presence_run_id,
            presence_run_row_id,
            post_corrected,
            original,
            corr_reason if post_corrected else None,
            workitem_revenue,
            review_status,
            review_resolution,
            actor_user_id,
            datetime.utcnow(),
            notes,
            new_version,
        ),
    )

    # Refresh day + estimated allocations
    day = build_daily_operations_day(cursor, org, operations_date_et, persist=True)
    _recompute_estimated_allocations(cursor, org, operations_date_et, day)

    fact_after = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
    cursor.execute(
        """
        INSERT INTO wf_day_bag_revenue_audits (
          organization_id, operations_date_et, bag_id, wf_day_bag_revenue_id,
          action, version_before, version_after, before_json, after_json,
          reason, actor_user_id, actor_display_name, is_undo
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
        """,
        (
            org,
            operations_date_et,
            bid,
            (fact_after or {}).get("id"),
            "unified_review_save",
            current_version,
            new_version,
            _json_dump(before_state),
            _json_dump({"fact": fact_after, "workitem_save": wi_out}),
            reason,
            actor_user_id,
            actor_display_name,
        ),
    )

    return {
        "ok": True,
        "bag_id": bid,
        "version": new_version,
        "review_status": review_status,
        "review_resolution": review_resolution,
        "day": {
            "wf_completed_pounds": (day.get("kpis") or {}).get("wf_completed_pounds"),
            "wf_weight_revenue": (day.get("kpis") or {}).get("wf_weight_revenue"),
            "missing_post_weights": (day.get("kpis") or {}).get("missing_post_weights"),
            "outstanding_wf_workitem_reviews": (day.get("kpis") or {}).get(
                "outstanding_wf_workitem_reviews"
            ),
        },
        "detail": get_wf_review_detail(cursor, org, operations_date_et, bid),
    }


def _recompute_estimated_allocations(
    cursor,
    organization_id: int,
    operations_date_et: date,
    day: Mapping[str, Any],
) -> None:
    day_rev = (day.get("revenue") or {}).get("wf_weight_revenue") or 0
    included = list((day.get("drilldowns") or {}).get("included_wf_bags") or [])
    allocs = allocate_estimated_bag_weight_revenues(day_weight_revenue=day_rev, bags=included)
    by_id = {a["bag_id"]: a["estimated_weight_revenue"] for a in allocs}
    for row in included:
        bid = _norm_bag(row.get("bag_id"))
        est = by_id.get(bid)
        if est is None:
            continue
        fact = get_wf_day_bag_revenue_row(cursor, organization_id, operations_date_et, bid)
        wi = float((fact or {}).get("workitem_revenue") or 0)
        total = money(_d(est) + _d(wi))
        if not fact:
            continue
        cursor.execute(
            """
            UPDATE wf_day_bag_revenue
            SET estimated_weight_revenue = %s, estimated_total_revenue = %s
            WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
            """,
            (est, total, int(organization_id), operations_date_et, bid),
        )


def undo_wf_review(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    *,
    reason: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Undo latest unified review by restoring previous audited state (new version)."""
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    reason_text = str(reason or "").strip()
    if not reason_text:
        return {"ok": False, "error": "reason_required"}
    ensure_wf_review_tables(cursor)
    fact = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
    if not fact:
        return {"ok": False, "error": "no_review_to_undo"}

    cursor.execute(
        """
        SELECT * FROM wf_day_bag_revenue_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
          AND is_undo = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (org, operations_date_et, bid),
    )
    latest = cursor.fetchone()
    if not latest:
        return {"ok": False, "error": "no_undoable_audit"}

    # Block if a newer non-undo audit exists after this — we selected latest non-undo.
    cursor.execute(
        """
        SELECT id FROM wf_day_bag_revenue_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
          AND id > %s AND is_undo = 0
        LIMIT 1
        """,
        (org, operations_date_et, bid, int(latest["id"])),
    )
    if cursor.fetchone():
        return {"ok": False, "error": "later_edit_depends"}

    before = _json_load(latest.get("before_json")) or {}
    prev_fact = before.get("fact")
    current_version = int(fact.get("version") or 1)
    new_version = current_version + 1

    if not prev_fact:
        # Clear correction / mark review required again
        cursor.execute(
            """
            UPDATE wf_day_bag_revenue
            SET post_weight_corrected = 0,
                post_weight_correction_reason = NULL,
                authoritative_post_weight_lbs = original_post_weight_lbs,
                post_weight_source = %s,
                review_status = %s,
                review_resolution = NULL,
                notes = NULL,
                version = %s,
                reviewed_at = NULL,
                reviewed_by_user_id = NULL
            WHERE id = %s
            """,
            (POST_SOURCE_MISSING, STATUS_REVIEW_REQUIRED, new_version, int(fact["id"])),
        )
    else:
        cursor.execute(
            """
            UPDATE wf_day_bag_revenue
            SET authoritative_post_weight_lbs = %s,
                post_weight_source = %s,
                post_weight_scan_event_id = %s,
                post_weight_presence_run_id = %s,
                post_weight_presence_run_row_id = %s,
                post_weight_corrected = %s,
                original_post_weight_lbs = %s,
                post_weight_correction_reason = %s,
                workitem_revenue = %s,
                review_status = %s,
                review_resolution = %s,
                notes = %s,
                version = %s,
                reviewed_by_user_id = %s,
                reviewed_at = %s
            WHERE id = %s
            """,
            (
                prev_fact.get("authoritative_post_weight_lbs"),
                prev_fact.get("post_weight_source"),
                prev_fact.get("post_weight_scan_event_id"),
                prev_fact.get("post_weight_presence_run_id"),
                prev_fact.get("post_weight_presence_run_row_id"),
                int(prev_fact.get("post_weight_corrected") or 0),
                prev_fact.get("original_post_weight_lbs"),
                prev_fact.get("post_weight_correction_reason"),
                float(prev_fact.get("workitem_revenue") or 0),
                prev_fact.get("review_status") or STATUS_REVIEW_REQUIRED,
                prev_fact.get("review_resolution"),
                prev_fact.get("notes"),
                new_version,
                prev_fact.get("reviewed_by_user_id"),
                prev_fact.get("reviewed_at"),
                int(fact["id"]),
            ),
        )

    # Restore prior workitem lines from before snapshot when present
    prior_lines = before.get("workitems") or []
    prior_res = before.get("resolution")
    from backend.rinse_bulk_workitems import save_bag_bulk_workitems

    if prior_res and str(prior_res.get("resolution_type") or "") == "no_charge":
        save_bag_bulk_workitems(
            cursor,
            org,
            shift_date_et=operations_date_et,
            bag_id=bid,
            items=[],
            no_chargeable=True,
            no_charge_reason=str(prior_res.get("no_charge_reason") or "undo_restore"),
            reason=reason_text,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            allow_closed=True,
        )
    else:
        items = [
            {"workitem_id": int(x.get("workitem_id")), "quantity": int(x.get("quantity") or 0)}
            for x in prior_lines
            if int(x.get("workitem_id") or 0) > 0 and int(x.get("quantity") or 0) > 0
        ]
        save_bag_bulk_workitems(
            cursor,
            org,
            shift_date_et=operations_date_et,
            bag_id=bid,
            items=items,
            no_chargeable=False,
            reason=reason_text,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            allow_closed=True,
            allow_empty_clear=True,
        )

    after = get_wf_day_bag_revenue_row(cursor, org, operations_date_et, bid)
    # Clear shared step1 correction authority without deleting prior correction audits.
    from backend.rinse_veewash_step1_api import _record_correction

    _record_correction(
        cursor,
        org,
        bag_id=bid,
        action="undo_correct_weight",
        reason_text=reason_text,
        reason_code="DAILY_OPS_WF_REVIEW_UNDO",
        previous_values={
            "post_weight_lbs": fact.get("authoritative_post_weight_lbs"),
            "operations_date_et": operations_date_et.isoformat(),
        },
        new_values={
            "cleared": True,
            "operations_date_et": operations_date_et.isoformat(),
        },
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )
    cursor.execute(
        """
        INSERT INTO wf_day_bag_revenue_audits (
          organization_id, operations_date_et, bag_id, wf_day_bag_revenue_id,
          action, version_before, version_after, before_json, after_json,
          reason, actor_user_id, actor_display_name, is_undo
        ) VALUES (%s, %s, %s, %s, 'undo_review', %s, %s, %s, %s, %s, %s, %s, 1)
        """,
        (
            org,
            operations_date_et,
            bid,
            (after or {}).get("id"),
            current_version,
            new_version,
            _json_dump({"fact": fact}),
            _json_dump({"fact": after}),
            reason_text,
            actor_user_id,
            actor_display_name,
        ),
    )
    day = build_daily_operations_day(cursor, org, operations_date_et, persist=True)
    _recompute_estimated_allocations(cursor, org, operations_date_et, day)
    return {
        "ok": True,
        "bag_id": bid,
        "version": new_version,
        "detail": get_wf_review_detail(cursor, org, operations_date_et, bid),
        "day_kpis": day.get("kpis"),
    }
