"""Shift Analysis Dashboard: pending work, team summary, overall vs scoring."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    CHECKOUT_STATUS_CHECKED_OUT,
    CHECKOUT_STATUS_NEEDS_REVIEW,
    CHECKOUT_STATUS_NOT_CHECKED_OUT,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    LIFECYCLE_UNKNOWN,
    PENDING_WEIGHING,
    SENT_TO_RINSE,
    SENT_TO_VENDOR,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
    derive_bag_lifecycle_status,
)

from backend.rinse_folding_registry import aggregate_folding_leaderboard
from backend.rinse_folding_scoring import row_included_in_scoring
from backend.rinse_operations_dashboard import (
    _completed_expr,
    _service_expr,
    effective_rush_expr,
)
from backend.rinse_cleaner_ticket_presence import load_wf_presence_incoming_rows
from backend.rinse_order_search import _active_staging_where_sql
from backend.rinse_processing_productivity import build_processing_productivity
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_start_cleaning_purpose, is_weight_entry_purpose
from backend.rinse_shift_operational_exceptions import (
    OPERATIONAL_STAT_LABELS,
    aggregate_operational_stats,
    evaluate_bag_operational_profile,
)
from backend.ta_helpers import table_exists, table_has_column

STATUS_MODEL_LIFECYCLE_V1 = "lifecycle_v1"

LIFECYCLE_COMPLETED_STATUSES = frozenset({FOLDED_COMPLETED, SENT_TO_RINSE})

LIFECYCLE_GROUP_PENDING_WEIGHING = "pending_weighing"
LIFECYCLE_GROUP_WEIGHED_NOT_STARTED = "weighed_not_started"
LIFECYCLE_GROUP_SORTED_READY = "sorted_ready"
LIFECYCLE_GROUP_WASH_DRY = "wash_dry"
LIFECYCLE_GROUP_FOLDED = "folded"
LIFECYCLE_GROUP_SENT_TO_RINSE = "sent_to_rinse"
LIFECYCLE_GROUP_UNKNOWN = "unknown"
LIFECYCLE_GROUP_EARLY = "early_lifecycle"

LIFECYCLE_STATUS_TO_GROUP: dict[str, str] = {
    PENDING_WEIGHING: LIFECYCLE_GROUP_PENDING_WEIGHING,
    WEIGHED_NOT_STARTED: LIFECYCLE_GROUP_WEIGHED_NOT_STARTED,
    SORTED_READY_FOR_WASH: LIFECYCLE_GROUP_SORTED_READY,
    IN_WASHING: LIFECYCLE_GROUP_WASH_DRY,
    IN_DRYING: LIFECYCLE_GROUP_WASH_DRY,
    FOLDED_COMPLETED: LIFECYCLE_GROUP_FOLDED,
    SENT_TO_RINSE: LIFECYCLE_GROUP_SENT_TO_RINSE,
    LIFECYCLE_UNKNOWN: LIFECYCLE_GROUP_UNKNOWN,
    ASSIGNED_NOT_SENT_TO_VENDOR: LIFECYCLE_GROUP_EARLY,
    SENT_TO_VENDOR: LIFECYCLE_GROUP_EARLY,
}

LIFECYCLE_GROUP_TO_STATUSES: dict[str, frozenset[str]] = {
    LIFECYCLE_GROUP_PENDING_WEIGHING: frozenset({PENDING_WEIGHING}),
    LIFECYCLE_GROUP_WEIGHED_NOT_STARTED: frozenset({WEIGHED_NOT_STARTED}),
    LIFECYCLE_GROUP_SORTED_READY: frozenset({SORTED_READY_FOR_WASH}),
    LIFECYCLE_GROUP_WASH_DRY: frozenset({IN_WASHING, IN_DRYING}),
    LIFECYCLE_GROUP_FOLDED: frozenset({FOLDED_COMPLETED}),
    LIFECYCLE_GROUP_SENT_TO_RINSE: frozenset({SENT_TO_RINSE}),
    LIFECYCLE_GROUP_UNKNOWN: frozenset({LIFECYCLE_UNKNOWN}),
    LIFECYCLE_GROUP_EARLY: frozenset({ASSIGNED_NOT_SENT_TO_VENDOR, SENT_TO_VENDOR}),
}

LIFECYCLE_STATUS_LABELS: dict[str, str] = {
    ASSIGNED_NOT_SENT_TO_VENDOR: "Assigned — not sent to vendor",
    SENT_TO_VENDOR: "Sent to vendor",
    PENDING_WEIGHING: "Pending weighing",
    WEIGHED_NOT_STARTED: "Weighed — not started",
    SORTED_READY_FOR_WASH: "Sorted — ready for wash",
    IN_WASHING: "In washing",
    IN_DRYING: "In drying",
    FOLDED_COMPLETED: "Folded / completed",
    SENT_TO_RINSE: "Sent to Rinse",
    LIFECYCLE_UNKNOWN: "Unknown lifecycle",
}

LIFECYCLE_GROUP_LABELS: dict[str, str] = {
    LIFECYCLE_GROUP_PENDING_WEIGHING: "Pending Weighing",
    LIFECYCLE_GROUP_WEIGHED_NOT_STARTED: "Weighed / Not Started",
    LIFECYCLE_GROUP_SORTED_READY: "Sorted / Ready",
    LIFECYCLE_GROUP_WASH_DRY: "Wash / Dry",
    LIFECYCLE_GROUP_FOLDED: "Folded",
    LIFECYCLE_GROUP_SENT_TO_RINSE: "Sent to Rinse",
    LIFECYCLE_GROUP_UNKNOWN: "Unknown lifecycle",
    LIFECYCLE_GROUP_EARLY: "Early lifecycle",
    "completed": "Completed",
    "pending": "Pending",
    "needs_review": "Needs Review",
    "exceptions": "Exceptions",
}


def _parse_evaluation_time(raw: str | datetime | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def lifecycle_group_for_status(status: str | None) -> str:
    st = str(status or LIFECYCLE_UNKNOWN).strip().upper()
    if st == "UNKNOWN":
        st = LIFECYCLE_UNKNOWN
    return LIFECYCLE_STATUS_TO_GROUP.get(st, LIFECYCLE_GROUP_UNKNOWN)


def _empty_lifecycle_group_dict() -> dict[str, Any]:
    return {
        "total": 0,
        "completed": 0,
        "pending": 0,
        "needs_review": 0,
        "with_exceptions": 0,
        "by_lifecycle_status": {},
        "by_lifecycle_group": {key: 0 for key in LIFECYCLE_GROUP_TO_STATUSES},
    }


def _empty_checkout_rush_summary() -> dict[str, int]:
    return {
        "checkout_pending": 0,
        "checked_out": 0,
        "checkout_needs_review": 0,
    }


def _accumulate_lifecycle_group(
    group: dict[str, Any],
    *,
    lifecycle_status: str,
    lifecycle_group: str,
    is_completed: bool,
    needs_review: bool,
    has_exceptions: bool,
) -> None:
    group["total"] += 1
    if is_completed:
        group["completed"] += 1
    else:
        group["pending"] += 1
    if needs_review:
        group["needs_review"] += 1
    if has_exceptions:
        group["with_exceptions"] += 1
    by_status = group.setdefault("by_lifecycle_status", {})
    by_status[lifecycle_status] = int(by_status.get(lifecycle_status) or 0) + 1
    by_group = group.setdefault("by_lifecycle_group", {})
    by_group[lifecycle_group] = int(by_group.get(lifecycle_group) or 0) + 1


def _sum_lifecycle_groups(
    rush: dict[str, Any], non_rush: dict[str, Any]
) -> dict[str, Any]:
    combined = _empty_lifecycle_group_dict()
    for key in ("total", "completed", "pending", "needs_review", "with_exceptions"):
        combined[key] = int(rush.get(key) or 0) + int(non_rush.get(key) or 0)
    for st, cnt in (rush.get("by_lifecycle_status") or {}).items():
        combined["by_lifecycle_status"][st] = int(combined["by_lifecycle_status"].get(st) or 0) + int(cnt)
    for st, cnt in (non_rush.get("by_lifecycle_status") or {}).items():
        combined["by_lifecycle_status"][st] = int(combined["by_lifecycle_status"].get(st) or 0) + int(cnt)
    for grp in LIFECYCLE_GROUP_TO_STATUSES:
        combined["by_lifecycle_group"][grp] = int(
            (rush.get("by_lifecycle_group") or {}).get(grp) or 0
        ) + int((non_rush.get("by_lifecycle_group") or {}).get(grp) or 0)
    return combined


def _sum_legacy_groups(rush: dict[str, int], non_rush: dict[str, int]) -> dict[str, int]:
    combined = _empty_pending_group()
    for key in combined:
        combined[key] = int(rush.get(key) or 0) + int(non_rush.get(key) or 0)
    return combined


def filter_lifecycle_pending_rows(
    rows: list[dict[str, Any]],
    *,
    rush_group: str | None = None,
    lifecycle_group: str | None = None,
    lifecycle_status: str | None = None,
    filter_kind: str | None = None,
) -> list[dict[str, Any]]:
    """Filter lifecycle pending rows for dashboard drilldown."""
    out: list[dict[str, Any]] = []
    allowed_statuses = LIFECYCLE_GROUP_TO_STATUSES.get(str(lifecycle_group or "").strip())
    for row in rows:
        if not isinstance(row, dict):
            continue
        if rush_group == "rush" and not row.get("rush"):
            continue
        if rush_group == "non_rush" and row.get("rush"):
            continue
        st = str(row.get("current_lifecycle_status") or LIFECYCLE_UNKNOWN).strip()
        grp = str(row.get("lifecycle_group") or lifecycle_group_for_status(st))
        if lifecycle_status and st != lifecycle_status:
            continue
        if allowed_statuses is not None and st not in allowed_statuses:
            continue
        kind = str(filter_kind or "").strip().lower()
        if kind == "needs_review" and not row.get("needs_review"):
            continue
        if kind == "exceptions" and not (row.get("exception_flags") or []):
            continue
        if kind == "completed" and st not in LIFECYCLE_COMPLETED_STATUSES:
            continue
        if kind == "pending" and st in LIFECYCLE_COMPLETED_STATUSES:
            continue
        out.append(row)
    return out


def _load_mapped_internal_scan_users(cursor, organization_id: int) -> list[str]:
    if not table_exists(cursor, "rinse_folding_user_map"):
        return []
    active_clause = ""
    if table_has_column(cursor, "rinse_folding_user_map", "active"):
        active_clause = " AND active = 1"
    cursor.execute(
        f"""
        SELECT DISTINCT TRIM(rinse_user_name) AS rinse_user_name
        FROM rinse_folding_user_map
        WHERE organization_id = %s{active_clause}
          AND rinse_user_name IS NOT NULL AND TRIM(rinse_user_name) != ''
        """,
        (int(organization_id),),
    )
    names: list[str] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        n = str(row.get("rinse_user_name") or "").strip()
        if n:
            names.append(n)
    return names


def _staging_logistics_expr(cursor, alias: str = "s") -> str:
    has_logistics = table_has_column(cursor, "orders_staging", "logistics_status")
    has_status = table_has_column(cursor, "orders_staging", "status")
    if has_logistics:
        if has_status:
            return f"""
                COALESCE(
                    {alias}.logistics_status,
                    CASE
                        WHEN {alias}.status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                        WHEN {alias}.status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                        ELSE 'AT_WASHPRO'
                    END
                )
            """
        return f"COALESCE({alias}.logistics_status, 'AT_WASHPRO')"
    if has_status:
        return f"""
            CASE
                WHEN {alias}.status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                WHEN {alias}.status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                ELSE 'AT_WASHPRO'
            END
        """
    return "'AT_WASHPRO'"


def _load_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    org = int(organization_id)
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    chunk = 100
    for i in range(0, len(bag_ids), chunk):
        part = [b for b in bag_ids[i : i + chunk] if b]
        if not part:
            continue
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                out.setdefault(bid, []).append(row)
    return out


def build_operational_dashboard_data(
    cursor,
    organization_id: int,
    *,
    pending_payload: dict[str, Any],
    reject_no_start_cleaning_minutes: int | None = None,
) -> dict[str, Any]:
    """Evaluate operational exceptions and workitem stats for pending WF bags."""
    from backend.rinse_processing_settings import DEFAULT_REJECT_NO_START

    pending_rows = pending_payload.get("rows") or []
    if not isinstance(pending_rows, list):
        pending_rows = []
    reject_limit = int(reject_no_start_cleaning_minutes or DEFAULT_REJECT_NO_START)
    bag_ids = [
        str(r.get("bag_id") or "").strip()
        for r in pending_rows
        if isinstance(r, dict) and r.get("bag_id")
    ]
    events_by_bag = _load_scan_events_for_bags(cursor, int(organization_id), bag_ids)

    records: list[dict[str, Any]] = []
    for prow in pending_rows:
        if not isinstance(prow, dict):
            continue
        bid = str(prow.get("bag_id") or "").strip()
        if not bid:
            continue
        rec = evaluate_bag_operational_profile(
            events_by_bag.get(bid) or [],
            bag_meta=prow,
            reject_no_start_cleaning_minutes=reject_limit,
        )
        for key in (
            "lifecycle_group",
            "lifecycle_group_label",
            "current_lifecycle_status",
            "lifecycle_status_label",
            "status_timestamp",
            "status_source_event",
            "needs_review",
            "exception_flags",
            "operational_flags",
            "checkout_status",
            "stage_detail",
            "rush",
            "rush_label",
            "customer",
            "weight_lbs",
        ):
            if prow.get(key) is not None:
                rec[key] = prow[key]
        if prow.get("current_lifecycle_status"):
            rec["activity"] = "lifecycle"
        if prow.get("is_completed") is not None:
            rec["is_completed"] = bool(prow.get("is_completed"))
        elif str(prow.get("current_lifecycle_status") or "") in LIFECYCLE_COMPLETED_STATUSES:
            rec["is_completed"] = True
        records.append(rec)

    stats = aggregate_operational_stats(records)
    return {
        "stats": stats,
        "stat_labels": OPERATIONAL_STAT_LABELS,
        "records": records,
        "reject_no_start_cleaning_minutes": reject_limit,
        "total_operational_exceptions": (
            stats.get("order_reject_no_start_cleaning_after_limit", 0)
            + stats.get("completed_without_final_clean_scan", 0)
        ),
    }


def _empty_pending_group() -> dict[str, int]:
    return {
        "total": 0,
        "completed": 0,
        "pending": 0,
        "not_weighed": 0,
        "weighed_not_washed": 0,
        "in_washing": 0,
    }


def _accumulate_group(group: dict[str, int], *, completed: bool, bucket: str | None) -> None:
    group["total"] += 1
    if completed:
        group["completed"] += 1
    else:
        group["pending"] += 1
        if bucket == "not_weighed":
            group["not_weighed"] += 1
        elif bucket == "weighed_not_washed":
            group["weighed_not_washed"] += 1
        elif bucket == "in_washing":
            group["in_washing"] += 1


def _classify_pending_bucket(
    *,
    is_completed: bool,
    has_weight_entry: bool,
    has_start_cleaning: bool,
) -> str | None:
    if is_completed:
        return None
    if not has_weight_entry:
        return "not_weighed"
    if not has_start_cleaning:
        return "weighed_not_washed"
    return "in_washing"


def _bag_purpose_flags(cursor, organization_id: int, bag_ids: list[str]) -> dict[str, dict[str, bool]]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    org = int(organization_id)
    flags: dict[str, dict[str, bool]] = {}
    chunk = 200
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip()
            if not bid:
                continue
            st = flags.setdefault(bid, {"weight_entry": False, "start_cleaning": False})
            purpose = row.get("purpose")
            if is_weight_entry_purpose(purpose):
                st["weight_entry"] = True
            if is_start_cleaning_purpose(purpose):
                st["start_cleaning"] = True
    return flags


def _build_portal_reconciliation_meta(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    lifecycle_bag_ids: set[str],
    wf_meta: dict[str, Any],
) -> dict[str, Any]:
    """Compare lifecycle WF scope against latest portal CSV batch (CleanerTickets upload)."""
    org = int(organization_id)
    td = target_date
    out: dict[str, Any] = {
        "entity_type": "bags",
        "count_basis": {
            "lifecycle_scope": (
                "active orders_staging WF + registry supplement + incoming "
                "ready_for_vendor/at_vendor presence (not in staging)"
            ),
            "incoming_presence_scope": (
                "rinse_cleaner_ticket_presence active rows; ready_for_vendor "
                "counts as Assigned/Not Sent; not mixed into at-vendor staging"
            ),
            "portal_batch_scope": "latest confirmed upload_batch_rows (CleanerTickets CSV)",
            "portal_active_staging_scope": (
                "orders_staging rows matching active portal filter (excludes "
                "SENT_TO_RINSE, FORCE_CHECKOUT, CHECKED_OUT)"
            ),
            "hd_handling": "HD excluded from WF lifecycle; counted in hd_excluded",
            "completed_exclusion": (
                "FORCE_CHECKOUT / CHECKED_OUT staging rows excluded from wf_at_vendor_staging"
            ),
        },
        **wf_meta,
        "portal_batch_wf": None,
        "portal_batch_hd": None,
        "portal_batch_total": None,
        "portal_batch_wf_due_today": None,
        "portal_batch_gaps": [],
        "net_gap_vs_portal_batch_wf": None,
    }
    if not table_exists(cursor, "upload_batches") or not table_exists(cursor, "upload_batch_rows"):
        return out

    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"
    row_batch_col = (
        "upload_batch_id"
        if table_has_column(cursor, "upload_batch_rows", "upload_batch_id")
        else "batch_id"
    )
    org_clause = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_clause = " AND organization_id = %s"
        args.append(org)

    cursor.execute(
        f"""
        SELECT {batch_pk} AS batch_id
        FROM upload_batches
        WHERE confirmed_at IS NOT NULL{org_clause}
        ORDER BY confirmed_at DESC, {batch_pk} DESC
        LIMIT 1
        """,
        tuple(args),
    )
    batch_row = cursor.fetchone()
    if not batch_row or not isinstance(batch_row, dict):
        return out
    batch_id = batch_row.get("batch_id")
    if batch_id is None:
        return out

    cursor.execute(
        f"""
        SELECT ticket_id, service_type, date_clean, name_clean, row_status, reason, rush_type
        FROM upload_batch_rows
        WHERE {row_batch_col} = %s
        """,
        (batch_id,),
    )
    batch_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    batch_wf = [
        r
        for r in batch_rows
        if str(r.get("service_type") or "WF").upper() == "WF" and str(r.get("ticket_id") or "").strip()
    ]
    batch_hd = [r for r in batch_rows if str(r.get("service_type") or "WF").upper() != "WF"]
    batch_wf_ids = {str(r.get("ticket_id") or "").strip().upper() for r in batch_wf}
    lifecycle_ids = {str(b or "").strip().upper() for b in lifecycle_bag_ids if str(b or "").strip()}

    gaps: list[dict[str, Any]] = []
    for row in batch_wf:
        bid = str(row.get("ticket_id") or "").strip().upper()
        if not bid or bid in lifecycle_ids:
            continue
        cursor.execute(
            """
            SELECT status, logistics_status
            FROM orders_staging
            WHERE organization_id = %s AND ticket_id = %s
            LIMIT 1
            """,
            (org, bid),
        )
        staging = cursor.fetchone() if table_exists(cursor, "orders_staging") else None
        staging_present = isinstance(staging, dict)
        active_staging = False
        if staging_present:
            active_where = _active_staging_where_sql(cursor)
            cursor.execute(
                f"""
                SELECT 1 AS ok FROM orders_staging
                WHERE organization_id = %s AND ticket_id = %s AND ({active_where})
                LIMIT 1
                """,
                (org, bid),
            )
            active_staging = bool(cursor.fetchone())
        cursor.execute(
            "SELECT 1 AS ok FROM rinse_bag_registry WHERE organization_id = %s AND bag_id = %s LIMIT 1",
            (org, bid),
        )
        registry_present = bool(cursor.fetchone())
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM rinse_bag_scan_events WHERE organization_id = %s AND bag_id = %s",
            (org, bid),
        )
        scan_row = cursor.fetchone()
        scan_count = int((scan_row or {}).get("cnt") or 0) if isinstance(scan_row, dict) else 0
        rush = str(row.get("rush_type") or "").strip().upper()
        if not rush:
            dc = row.get("date_clean")
            rush = "RUSH" if isinstance(dc, date) and dc < td else "NON-RUSH"
        reason_excluded = "Not in lifecycle scope"
        if str(row.get("row_status") or "").upper() == "REJECTED_DUPLICATE":
            reason_excluded = f"Portal row rejected ({row.get('reason') or 'duplicate'})"
        elif staging_present and not active_staging:
            reason_excluded = (
                f"Staging inactive (status={staging.get('status')}, "
                f"logistics={staging.get('logistics_status')})"
            )
        elif not staging_present:
            reason_excluded = "Absent from orders_staging"
        elif row.get("date_clean") != td and not registry_present:
            reason_excluded = "date_clean != target_date and not in registry supplement"
        gaps.append(
            {
                "bag_id": bid,
                "customer": row.get("name_clean"),
                "rush_label": rush,
                "date_clean": row.get("date_clean").isoformat()
                if isinstance(row.get("date_clean"), date)
                else row.get("date_clean"),
                "portal_row_status": row.get("row_status"),
                "portal_reason": row.get("reason"),
                "orders_staging_present": staging_present,
                "orders_staging_active": active_staging,
                "registry_present": registry_present,
                "scan_events_present": scan_count > 0,
                "scan_event_count": scan_count,
                "reason_excluded_from_dashboard": reason_excluded,
            }
        )

    wf_due_today = sum(1 for r in batch_wf if r.get("date_clean") == td)
    lifecycle_total = int(wf_meta.get("wf_lifecycle_total") or wf_meta.get("wf_total") or 0)
    out.update(
        {
            "portal_batch_id": batch_id,
            "portal_batch_wf": len(batch_wf),
            "portal_batch_hd": len(batch_hd),
            "portal_batch_total": len(batch_rows),
            "portal_batch_wf_due_today": wf_due_today,
            "portal_batch_gaps": gaps,
            "net_gap_vs_portal_batch_wf": len(batch_wf) - lifecycle_total,
        }
    )
    return out


def _load_pending_bag_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    WF lifecycle bag rows: active orders_staging (same population as GET /dashboard),
    excluding HD service type, with registry completion when available. Also includes
    registry-only WF rows for target_date not already counted.
    """
    org = int(organization_id)
    td = target_date
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    portal_active_total = 0
    hd_excluded = 0
    wf_at_vendor_staging = 0
    wf_due_today_staging = 0
    wf_not_due_today_staging = 0
    wf_registry_supplement = 0

    has_staging = table_exists(cursor, "orders_staging") and table_has_column(
        cursor, "orders_staging", "ticket_id"
    )
    has_reg = table_exists(cursor, "rinse_bag_registry")

    if has_staging:
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_rush = table_has_column(cursor, "orders_staging", "rush_type")
        has_name = table_has_column(cursor, "orders_staging", "name_clean")
        has_weight = table_has_column(cursor, "orders_staging", "weight_num")
        logistics_expr = _staging_logistics_expr(cursor, "s")
        rush_s = (
            effective_rush_expr("s", date_col="date_clean")
            if has_rush
            else "CASE WHEN s.date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
        )
        svc_s = _service_expr("s")
        org_clause = " AND s.organization_id = %s" if has_org else ""
        st_args: list[Any] = [org] if has_org else []

        if has_reg:
            reg_join = (
                "LEFT JOIN rinse_bag_registry r ON r.bag_id = s.ticket_id AND r.organization_id = s.organization_id"
                if has_org
                else "LEFT JOIN rinse_bag_registry r ON r.bag_id = s.ticket_id"
            )
            rush_final = f"COALESCE(NULLIF({effective_rush_expr('r')}, ''), UPPER({rush_s}))"
            name_expr = (
                "COALESCE(r.name_clean, s.name_clean)"
                if has_name
                else "r.name_clean"
            )
            weight_expr = (
                "COALESCE(r.weight_num, s.weight_num)"
                if has_weight
                else "r.weight_num"
            )
            completed_expr = f"CASE WHEN {_completed_expr('r')} THEN 1 ELSE 0 END"
        else:
            reg_join = ""
            rush_final = f"UPPER({rush_s})"
            name_expr = "s.name_clean" if has_name else "NULL"
            weight_expr = "s.weight_num" if has_weight else "NULL"
            completed_expr = "0"

        has_date_clean = table_has_column(cursor, "orders_staging", "date_clean")
        date_clean_expr = "s.date_clean" if has_date_clean else "NULL"
        cursor.execute(
            f"""
            SELECT
                s.ticket_id AS bag_id,
                {svc_s} AS service_type,
                {rush_final} AS effective_rush,
                {completed_expr} AS is_completed,
                {name_expr} AS name_clean,
                {weight_expr} AS weight_num,
                {logistics_expr} AS logistics_status,
                {date_clean_expr} AS date_clean
            FROM orders_staging s
            {reg_join}
            WHERE ({active_where}){org_clause}
              AND s.ticket_id IS NOT NULL AND TRIM(s.ticket_id) != ''
            """,
            tuple(st_args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            portal_active_total += 1
            svc = str(row.get("service_type") or "WF").upper()
            if svc != "WF":
                hd_excluded += 1
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if not bid or bid in seen:
                continue
            seen.add(bid)
            wf_at_vendor_staging += 1
            dc = row.get("date_clean")
            if dc == td:
                wf_due_today_staging += 1
            else:
                wf_not_due_today_staging += 1
            rows.append(row)

    if has_reg:
        rush_r = effective_rush_expr("r")
        svc_r = _service_expr("r")
        done_r = _completed_expr("r")
        cursor.execute(
            f"""
            SELECT
                r.bag_id,
                {svc_r} AS service_type,
                {rush_r} AS effective_rush,
                CASE WHEN {done_r} THEN 1 ELSE 0 END AS is_completed,
                r.name_clean,
                r.weight_num,
                NULL AS logistics_status
            FROM rinse_bag_registry r
            WHERE r.organization_id = %s AND r.date_clean = %s
            """,
            (org, td),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            svc = str(row.get("service_type") or "WF").upper()
            if svc != "WF":
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if not bid or bid in seen:
                continue
            seen.add(bid)
            wf_registry_supplement += 1
            rows.append(row)

    presence_rows, presence_meta = load_wf_presence_incoming_rows(
        cursor, org, target_date=td, exclude_bag_ids=seen
    )
    for row in presence_rows:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid or bid in seen:
            continue
        seen.add(bid)
        rows.append(row)

    meta = {
        "scope": "wf_lifecycle",
        "portal_active_total": portal_active_total,
        "hd_excluded": hd_excluded,
        "wf_at_vendor_staging": wf_at_vendor_staging,
        "wf_due_today_staging": wf_due_today_staging,
        "wf_not_due_today_staging": wf_not_due_today_staging,
        "wf_registry_supplement": wf_registry_supplement,
        **presence_meta,
        "wf_lifecycle_total": len(rows),
        "wf_total": len(rows),
    }
    return rows, meta


def _build_legacy_pending_payload(
    bag_rows: list[dict[str, Any]],
    purpose_flags: dict[str, dict[str, bool]],
) -> dict[str, dict[str, int]]:
    rush = _empty_pending_group()
    non_rush = _empty_pending_group()
    for row in bag_rows:
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        is_rush = str(row.get("effective_rush") or "").upper() == "RUSH"
        is_completed = int(row.get("is_completed") or 0) == 1
        pf = purpose_flags.get(bid, {})
        bucket = _classify_pending_bucket(
            is_completed=is_completed,
            has_weight_entry=bool(pf.get("weight_entry")),
            has_start_cleaning=bool(pf.get("start_cleaning")),
        )
        target = rush if is_rush else non_rush
        _accumulate_group(target, completed=is_completed, bucket=bucket)
    return {
        "rush": rush,
        "non_rush": non_rush,
        "combined": _sum_legacy_groups(rush, non_rush),
    }


def build_lifecycle_pending_payload(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    """Lifecycle-based pending/completed counts for active portal WF bags."""
    org = int(organization_id)
    td = target_date
    eval_at = evaluation_time if isinstance(evaluation_time, datetime) else datetime.utcnow()

    bag_rows, portal_meta = _load_pending_bag_rows(cursor, org, target_date=td)
    bag_ids = [str(r.get("bag_id") or "").strip() for r in bag_rows if r.get("bag_id")]
    purpose_flags = _bag_purpose_flags(cursor, org, bag_ids)
    events_by_bag = _load_scan_events_for_bags(cursor, org, bag_ids)
    proc_settings = get_processing_settings(cursor, org)
    mapped_users = _load_mapped_internal_scan_users(cursor, org)

    rush = _empty_lifecycle_group_dict()
    non_rush = _empty_lifecycle_group_dict()
    checkout_rush = _empty_checkout_rush_summary()
    drilldown_rows: list[dict[str, Any]] = []

    for row in bag_rows:
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        is_rush = str(row.get("effective_rush") or "").upper() == "RUSH"
        pf = purpose_flags.get(bid, {})
        legacy_bucket = _classify_pending_bucket(
            is_completed=int(row.get("is_completed") or 0) == 1,
            has_weight_entry=bool(pf.get("weight_entry")),
            has_start_cleaning=bool(pf.get("start_cleaning")),
        )
        lifecycle_fallback = False
        try:
            lifecycle = derive_bag_lifecycle_status(
                events_by_bag.get(bid) or [],
                bag_id=bid,
                ready_for_vendor_presence=bool(row.get("ready_for_vendor_presence")),
                at_vendor_presence=bool(row.get("at_vendor_presence")),
                logistics_status=row.get("logistics_status"),
                mapped_internal_users=mapped_users,
                washing_minutes=int(proc_settings.get("washing_minutes") or 30),
                drying_minutes=int(proc_settings.get("drying_minutes") or 45),
                reject_after_create_issue_minutes=int(
                    proc_settings.get("reject_after_create_issue_minutes") or 45
                ),
                evaluation_time=eval_at,
            )
        except Exception:
            lifecycle = {
                "current_lifecycle_status": LIFECYCLE_UNKNOWN,
                "checkout_status": CHECKOUT_STATUS_NOT_CHECKED_OUT,
                "status_timestamp": None,
                "status_source_event": None,
                "operational_flags": {},
                "exception_flags": [],
                "needs_review": True,
                "stage_detail": {},
            }
            lifecycle_fallback = True

        lifecycle_status = str(
            lifecycle.get("current_lifecycle_status") or LIFECYCLE_UNKNOWN
        ).strip()
        lifecycle_group = lifecycle_group_for_status(lifecycle_status)
        is_completed = lifecycle_status in LIFECYCLE_COMPLETED_STATUSES
        exception_flags = list(lifecycle.get("exception_flags") or [])
        needs_review = (
            bool(lifecycle.get("needs_review"))
            or lifecycle_fallback
            or bool(row.get("needs_review_presence_svc"))
        )
        has_exceptions = len(exception_flags) > 0
        checkout_status = str(lifecycle.get("checkout_status") or CHECKOUT_STATUS_NOT_CHECKED_OUT)

        group_key = "rush" if is_rush else "non_rush"
        target = rush if is_rush else non_rush
        _accumulate_lifecycle_group(
            target,
            lifecycle_status=lifecycle_status,
            lifecycle_group=lifecycle_group,
            is_completed=is_completed,
            needs_review=needs_review,
            has_exceptions=has_exceptions,
        )

        if is_rush:
            if checkout_status == CHECKOUT_STATUS_NOT_CHECKED_OUT:
                checkout_rush["checkout_pending"] += 1
            elif checkout_status == CHECKOUT_STATUS_CHECKED_OUT:
                checkout_rush["checked_out"] += 1
            elif checkout_status == CHECKOUT_STATUS_NEEDS_REVIEW:
                checkout_rush["checkout_needs_review"] += 1

        drilldown_rows.append(
            {
                "bag_id": bid,
                "customer": row.get("name_clean"),
                "weight_lbs": row.get("weight_num"),
                "rush": is_rush,
                "rush_label": "Rush" if is_rush else "Non-Rush",
                "group": group_key,
                "current_lifecycle_status": lifecycle_status,
                "lifecycle_group": lifecycle_group,
                "lifecycle_status_label": LIFECYCLE_STATUS_LABELS.get(
                    lifecycle_status, lifecycle_status
                ),
                "lifecycle_group_label": LIFECYCLE_GROUP_LABELS.get(
                    lifecycle_group, lifecycle_group
                ),
                "status_timestamp": lifecycle.get("status_timestamp"),
                "status_source_event": lifecycle.get("status_source_event"),
                "needs_review": needs_review,
                "exception_flags": exception_flags,
                "operational_flags": lifecycle.get("operational_flags") or {},
                "checkout_status": checkout_status,
                "stage_detail": lifecycle.get("stage_detail") or {},
                "lifecycle_fallback": lifecycle_fallback,
                "legacy_pending_bucket": legacy_bucket,
                "is_completed": is_completed,
                "pending_bucket": legacy_bucket,
                "presence_source": bool(row.get("presence_source")),
                "presence_portal_status": row.get("presence_portal_status"),
            }
        )

    legacy_buckets = _build_legacy_pending_payload(bag_rows, purpose_flags)
    combined = _sum_lifecycle_groups(rush, non_rush)
    lifecycle_ids = {str(r.get("bag_id") or "").strip().upper() for r in bag_rows if r.get("bag_id")}
    portal_alignment = _build_portal_reconciliation_meta(
        cursor,
        org,
        target_date=td,
        lifecycle_bag_ids=lifecycle_ids,
        wf_meta=portal_meta,
    )

    return {
        "date": td.isoformat(),
        "status_model": STATUS_MODEL_LIFECYCLE_V1,
        "evaluation_time": eval_at.isoformat(),
        "completion_field": "lifecycle: FOLDED_COMPLETED or SENT_TO_RINSE",
        "service_scope": "WF bags only (HD excluded from lifecycle)",
        "portal_alignment": portal_alignment,
        "lifecycle_status_labels": LIFECYCLE_STATUS_LABELS,
        "lifecycle_group_labels": LIFECYCLE_GROUP_LABELS,
        "groups": {"rush": rush, "non_rush": non_rush, "combined": combined},
        "legacy_buckets": legacy_buckets,
        "checkout_summary": {
            "rush": checkout_rush,
            "labels": {
                "checkout_pending": "Rush checkout pending",
                "checked_out": "Rush checked out",
                "checkout_needs_review": "Checkout needs review",
            },
        },
        "rows": drilldown_rows,
    }


def get_pending_bag_status(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Lifecycle-based pending/completed WF bag counts by rush group.
    Legacy 3-bucket counts are retained under ``legacy_buckets`` for validation.
    """
    return build_lifecycle_pending_payload(
        cursor,
        organization_id,
        target_date=target_date,
        evaluation_time=evaluation_time,
    )


def _get_pending_bag_status_legacy_only(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> dict[str, Any]:
    """Previous 3-bucket pending model (kept for tests)."""
    org = int(organization_id)
    td = target_date
    rush = _empty_pending_group()
    non_rush = _empty_pending_group()
    combined = _empty_pending_group()
    drilldown_rows: list[dict[str, Any]] = []

    bag_rows, portal_meta = _load_pending_bag_rows(cursor, org, target_date=td)
    bag_ids = [str(r.get("bag_id") or "").strip() for r in bag_rows if r.get("bag_id")]
    purpose_flags = _bag_purpose_flags(cursor, org, bag_ids)

    for row in bag_rows:
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        is_rush = str(row.get("effective_rush") or "").upper() == "RUSH"
        is_completed = int(row.get("is_completed") or 0) == 1
        pf = purpose_flags.get(bid, {})
        bucket = _classify_pending_bucket(
            is_completed=is_completed,
            has_weight_entry=bool(pf.get("weight_entry")),
            has_start_cleaning=bool(pf.get("start_cleaning")),
        )
        group_key = "rush" if is_rush else "non_rush"
        for g in (rush if is_rush else non_rush, combined):
            _accumulate_group(g, completed=is_completed, bucket=bucket)
        drilldown_rows.append(
            {
                "bag_id": bid,
                "customer": row.get("name_clean"),
                "weight_lbs": row.get("weight_num"),
                "rush": is_rush,
                "rush_label": "Rush" if is_rush else "Non-Rush",
                "group": group_key,
                "is_completed": is_completed,
                "pending_bucket": bucket,
                "has_weight_entry": bool(pf.get("weight_entry")),
                "has_start_cleaning": bool(pf.get("start_cleaning")),
            }
        )

    return {
        "date": td.isoformat(),
        "completion_field": "registry.completion_status (COMPLETED = done)",
        "service_scope": "WF only (HD excluded)",
        "portal_alignment": portal_meta,
        "groups": {"rush": rush, "non_rush": non_rush, "combined": combined},
        "rows": drilldown_rows,
    }


def _sum_shift_clock_hours(cursor, organization_id: int, period_start: date, period_end: date) -> float:
    if not table_exists(cursor, "shift_sessions"):
        return 0.0
    from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et

    org = int(organization_id)
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    org_clause = ""
    args: list[Any] = [end_exclusive, start_dt]
    if table_has_column(cursor, "shift_sessions", "organization_id"):
        org_clause = " AND organization_id = %s"
        args = [org, end_exclusive, start_dt]
    cursor.execute(
        f"""
        SELECT clock_in_at, clock_out_at
        FROM shift_sessions
        WHERE clock_in_at < %s
          AND (clock_out_at IS NULL OR clock_out_at >= %s)
          AND status IN ('completed', 'active', 'auto_closed')
          {org_clause}
        """,
        tuple(args),
    )
    total_sec = 0
    for sh in cursor.fetchall() or []:
        if not isinstance(sh, dict):
            continue
        cin = sh.get("clock_in_at")
        cout = sh.get("clock_out_at") or end_incl
        if isinstance(cin, datetime) and isinstance(cout, datetime):
            os = max(cin, start_dt)
            oe = min(cout, end_incl)
            if oe > os:
                total_sec += int((oe - os).total_seconds())
    return round(total_sec / 3600.0, 4)


def build_shift_analysis_summary(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
    processing_activities: list[str] | None = None,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    """Team/day summary combining clock hours, processing, and folding metrics."""
    org = int(organization_id)
    acts = processing_activities or ["weighing", "sorting", "wash_load"]

    leaderboard = aggregate_folding_leaderboard(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
    )
    processing = build_processing_productivity(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
    )
    if not isinstance(processing, dict):
        processing = {}
    proc_settings = get_processing_settings(cursor, org)
    clock_hours = _sum_shift_clock_hours(cursor, org, period_start, period_end)

    lb_rows = leaderboard.get("users") if isinstance(leaderboard, dict) else []
    if not isinstance(lb_rows, list):
        lb_rows = []
    team = leaderboard.get("team") if isinstance(leaderboard.get("team"), dict) else {}
    rules_impact = leaderboard.get("period_bag_summary")
    if not isinstance(rules_impact, dict):
        rules_impact = {}
    scoring_bags = int(rules_impact.get("included_in_scoring") or team.get("bag_count") or 0)
    scoring_lbs = float(team.get("total_lbs") or 0)
    total_bags = int(team.get("bag_count") or 0)
    total_lbs = float(team.get("total_lbs") or 0)
    fold_hours = float(team.get("total_folding_seconds") or 0) / 3600.0

    proc_summary = processing.get("summary_all_users")
    if not isinstance(proc_summary, dict):
        proc_summary = {}
    proc_bags = int(proc_summary.get("total_bags") or 0)
    proc_hours = float(proc_summary.get("clocked_hours") or proc_summary.get("estimated_hours") or 0)
    proc_people = len(processing.get("users") or [])

    fold_people = len(lb_rows)

    overall = {
        "clocked_labor_hours": clock_hours,
        "processing_labor_hours": proc_hours,
        "folding_labor_hours": round(fold_hours, 4),
        "processing_people_count": proc_people,
        "folding_people_count": fold_people,
        "total_bags_processed": proc_bags,
        "total_bags_completed": total_bags,
        "total_lbs_processed": proc_summary.get("total_lbs"),
        "total_lbs_folded": total_lbs,
        "processing_bags_per_hour": proc_summary.get("bags_per_clocked_hour"),
        "folding_bags_per_hour": team.get("bags_per_hour"),
    }
    scoring = {
        "scoring_bags": scoring_bags,
        "scoring_lbs": scoring_lbs,
        "scoring_folding_hours": fold_hours,
        "scoring_processing_hours": proc_hours,
        "scoring_folding_bags_per_hour": team.get("bags_per_hour"),
        "scoring_folding_lbs_per_hour": team.get("lbs_per_hour"),
        "scoring_quality_percent": team.get("issue_free_percent"),
        "excluded_records": int(rules_impact.get("excluded_from_scoring") or 0),
        "exception_records_not_counted": int(rules_impact.get("excluded_from_scoring") or 0),
    }

    employees: list[dict[str, Any]] = []
    for row in lb_rows:
        if not isinstance(row, dict):
            continue
        uname = str(row.get("user_name") or "").strip()
        if not uname:
            continue
        employees.append(
            {
                "user_name": uname,
                "role": "folding",
                "clocked_hours": row.get("clocked_hours"),
                "overall_bags": row.get("bag_count"),
                "scoring_bags": row.get("bag_count"),
                "overall_lbs": row.get("total_lbs"),
                "scoring_lbs": row.get("scoring_lbs") or row.get("total_lbs"),
                "overall_bags_per_hour": row.get("bags_per_hour"),
                "scoring_bags_per_hour": row.get("bags_per_hour"),
                "overall_lbs_per_hour": row.get("lbs_per_hour"),
                "scoring_lbs_per_hour": row.get("lbs_per_hour"),
                "exceptions": row.get("exception_count") or row.get("issue_count"),
                "needs_review": row.get("exception_count") or 0,
            }
        )

    pending = get_pending_bag_status(
        cursor,
        org,
        target_date=period_end,
        evaluation_time=evaluation_time,
    )
    reject_limit = int(proc_settings.get("reject_no_start_cleaning_minutes") or 30)
    operational = build_operational_dashboard_data(
        cursor,
        org,
        pending_payload=pending,
        reject_no_start_cleaning_minutes=reject_limit,
    )

    from backend.rinse_shift_monitor import (
        build_live_monitor_payload,
        build_staff_performance_payload,
        get_monitor_settings,
    )
    from backend.tenant_feature_flags import get_tenant_feature_flags

    eval_at = evaluation_time if isinstance(evaluation_time, datetime) else datetime.utcnow()
    pending_rows = pending.get("rows") or []
    bag_ids = [str(r.get("bag_id") or "").strip() for r in pending_rows if isinstance(r, dict) and r.get("bag_id")]
    events_by_bag = _load_scan_events_for_bags(cursor, org, bag_ids)
    monitor_settings = get_monitor_settings(cursor, org, proc_settings)
    feature_flags = get_tenant_feature_flags(cursor, org)

    live_monitor = build_live_monitor_payload(
        pending_rows,
        events_by_bag=events_by_bag,
        monitor_settings=monitor_settings,
        evaluation_time=eval_at,
        proc_settings=proc_settings,
    )
    staff_performance = build_staff_performance_payload(
        pending_rows,
        events_by_bag=events_by_bag,
        folding_rows=lb_rows,
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "date_field": date_field,
        "selected_processing_activities": acts,
        "overall_production": overall,
        "scoring_data": scoring,
        "speed": {
            "processing": {
                "bags_per_hour": proc_summary.get("bags_per_clocked_hour"),
                "lbs_per_hour": proc_summary.get("lbs_per_clocked_hour"),
                "minutes_per_bag": proc_summary.get("minutes_per_bag"),
                "people_count": proc_people,
                "labor_hours": proc_hours,
            },
            "folding": {
                "bags_per_hour": team.get("bags_per_hour"),
                "lbs_per_hour": team.get("lbs_per_hour"),
                "minutes_per_bag": team.get("avg_minutes_per_bag"),
                "people_count": fold_people,
                "labor_hours": round(fold_hours, 4),
            },
            "combined": {
                "bags_per_hour": None,
                "lbs_per_hour": None,
                "labor_hours": round(clock_hours, 4),
                "people_count": max(proc_people, fold_people),
            },
        },
        "employees": employees,
        "pending": pending,
        "operational": operational,
        "processing_settings": proc_settings,
        "monitor_settings": monitor_settings,
        "live_monitor": live_monitor,
        "staff_performance": staff_performance,
        "feature_flags": feature_flags,
    }


def enrich_record_scoring_fields(row: dict[str, Any]) -> dict[str, Any]:
    included = row_included_in_scoring(row)
    code = str(row.get("exception_code") or "").strip()
    reason = code or (None if included else str(row.get("status") or ""))
    return {
        **row,
        "in_scoring": included,
        "reason_not_scoring": None if included else (reason or "Excluded"),
    }
