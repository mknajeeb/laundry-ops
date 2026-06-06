"""Admin debug payload for /performance data audit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from backend.checkout_batch_scope import latest_checkout_batch
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scan_time import RINSE_SCAN_SOURCE_TIMEZONE
from backend.rinse_folding_period import sql_date_column
from backend.rinse_folding_registry import aggregate_folding_leaderboard, list_folding_performance_rows
from backend.rinse_lifecycle_portal_scrape import fetch_latest_confirmed_full_portal_batch
from backend.rinse_processing_productivity import build_processing_productivity
from backend.rinse_shift_analysis import (
    LIFECYCLE_GROUP_LABELS,
    build_shift_analysis_summary,
    filter_lifecycle_pending_rows,
    get_pending_bag_status,
    _wf_lifecycle_bucket_sum,
)
from backend.rinse_shift_monitor import build_live_monitor_payload, build_staff_performance_payload, get_monitor_settings
from backend.rinse_processing_settings import get_processing_settings
from backend.ta_helpers import table_exists, table_has_column


def _date_field_meaning(date_field: str) -> str:
    f = str(date_field or "folding_work_date").strip().lower()
    if f == "date_clean":
        return "Rinse portal due date (registry.date_clean)"
    if f == "completed_at":
        return "Registry completion timestamp (Eastern calendar date)"
    return "Folding performance work_date (Eastern calendar; folding_end_at wall when set)"


def _latest_scrape_block(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    batch = latest_checkout_batch(cursor, org, source="auto")
    if not batch or batch.get("batch_id") is None:
        batch = latest_checkout_batch(cursor, org, source="manual")
    out: dict[str, Any] = {
        "batch_id": None,
        "confirmed_at": None,
        "rows_imported": 0,
        "wf_rows": 0,
        "hd_rows": 0,
        "rush_rows": 0,
        "non_rush_rows": 0,
        "unknown_speed_rows": 0,
    }
    if not batch:
        return out
    bid = int(batch["batch_id"])
    out["batch_id"] = bid
    confirmed = batch.get("confirmed_at")
    if isinstance(confirmed, datetime):
        out["confirmed_at"] = confirmed.isoformat()
    elif confirmed is not None:
        out["confirmed_at"] = str(confirmed)

    row_col = (
        "upload_batch_id"
        if table_has_column(cursor, "upload_batch_rows", "upload_batch_id")
        else "batch_id"
    )
    if not table_exists(cursor, "upload_batch_rows"):
        return out
    cursor.execute(
        f"""
        SELECT service_type, rush_type, row_status
        FROM upload_batch_rows
        WHERE {row_col} = %s
        """,
        (bid,),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    accepted = [r for r in rows if str(r.get("row_status") or "").upper() in ("ACCEPTED", "OVERRIDDEN")]
    out["rows_imported"] = len(accepted)
    for r in accepted:
        svc = str(r.get("service_type") or "").upper()
        if svc == "WF":
            out["wf_rows"] += 1
        elif svc == "HD":
            out["hd_rows"] += 1
        rush = str(r.get("rush_type") or "").upper()
        if rush == "RUSH":
            out["rush_rows"] += 1
        elif rush == "NON-RUSH":
            out["non_rush_rows"] += 1
        else:
            out["unknown_speed_rows"] += 1
    return out


def _registry_block(cursor, organization_id: int, period_start: date, period_end: date) -> dict[str, int]:
    if not table_exists(cursor, "rinse_bag_registry"):
        return {"total": 0, "completed": 0, "pending": 0, "wf": 0, "hd": 0}
    org = int(organization_id)
    org_clause = ""
    args: list[Any] = [period_start, period_end]
    if table_has_column(cursor, "rinse_bag_registry", "organization_id"):
        org_clause = " AND organization_id = %s"
        args.append(org)
    cursor.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN completion_status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
          SUM(CASE WHEN COALESCE(completion_status, '') != 'COMPLETED' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN UPPER(COALESCE(service_type, '')) = 'WF' THEN 1 ELSE 0 END) AS wf,
          SUM(CASE WHEN UPPER(COALESCE(service_type, '')) = 'HD' THEN 1 ELSE 0 END) AS hd
        FROM rinse_bag_registry
        WHERE date_clean >= %s AND date_clean <= %s{org_clause}
        """,
        tuple(args),
    )
    row = cursor.fetchone() or {}
    return {
        "total": int(row.get("total") or 0),
        "completed": int(row.get("completed") or 0),
        "pending": int(row.get("pending") or 0),
        "wf": int(row.get("wf") or 0),
        "hd": int(row.get("hd") or 0),
    }


def _staging_block(cursor, organization_id: int) -> dict[str, int]:
    if not table_exists(cursor, "orders_staging"):
        return {
            "active_total": 0,
            "active_wf": 0,
            "active_hd": 0,
            "active_rush": 0,
            "active_non_rush": 0,
            "checked_out": 0,
            "sent_to_rinse": 0,
            "force_checkout": 0,
        }
    org = int(organization_id)
    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_logistics = table_has_column(cursor, "orders_staging", "logistics_status")
    has_status = table_has_column(cursor, "orders_staging", "status")
    has_rush = table_has_column(cursor, "orders_staging", "rush_type")
    org_clause = " AND organization_id = %s" if has_org else ""
    args: list[Any] = [org] if has_org else []
    sent_expr = (
        "COALESCE(logistics_status, CASE WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE' "
        "WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT' ELSE 'AT_WASHPRO' END)"
        if has_logistics and has_status
        else ("COALESCE(logistics_status, 'AT_WASHPRO')" if has_logistics else "status")
    )
    rush_expr = "UPPER(COALESCE(rush_type, 'NON-RUSH'))" if has_rush else "'NON-RUSH'"
    cursor.execute(
        f"""
        SELECT
          SUM(CASE WHEN {sent_expr} NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT') THEN 1 ELSE 0 END) AS active_total,
          SUM(CASE WHEN {sent_expr} NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            AND UPPER(COALESCE(service_type, '')) = 'WF' THEN 1 ELSE 0 END) AS active_wf,
          SUM(CASE WHEN {sent_expr} NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            AND UPPER(COALESCE(service_type, '')) = 'HD' THEN 1 ELSE 0 END) AS active_hd,
          SUM(CASE WHEN {sent_expr} NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            AND {rush_expr} = 'RUSH' THEN 1 ELSE 0 END) AS active_rush,
          SUM(CASE WHEN {sent_expr} NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            AND {rush_expr} = 'NON-RUSH' THEN 1 ELSE 0 END) AS active_non_rush,
          SUM(CASE WHEN {sent_expr} IN ('SENT_TO_RINSE', 'CHECKED_OUT') OR status = 'CHECKED_OUT' THEN 1 ELSE 0 END) AS checked_out,
          SUM(CASE WHEN {sent_expr} = 'SENT_TO_RINSE' THEN 1 ELSE 0 END) AS sent_to_rinse,
          SUM(CASE WHEN {sent_expr} = 'FORCE_CHECKOUT' OR status = 'FORCED_CHECKOUT' THEN 1 ELSE 0 END) AS force_checkout
        FROM orders_staging
        WHERE 1=1{org_clause}
        """,
        tuple(args),
    )
    row = cursor.fetchone() or {}
    return {k: int(row.get(k) or 0) for k in (
        "active_total", "active_wf", "active_hd", "active_rush", "active_non_rush",
        "checked_out", "sent_to_rinse", "force_checkout",
    )}


def _lifecycle_reconciliation(group: Mapping[str, Any], *, service: str) -> dict[str, Any]:
    total = int(group.get("total") or 0)
    completed = int(group.get("completed") or 0)
    pending = int(group.get("pending") or 0)
    if service == "wf":
        bucket_sum = _wf_lifecycle_bucket_sum(dict(group))
        by_g = group.get("by_lifecycle_group") or {}
        by_s = group.get("by_lifecycle_status") or {}
        folded = int(by_g.get("folded") or 0)
        sent = int(by_g.get("sent_to_rinse") or 0)
        components = {
            "sent_to_vendor": int(by_s.get("SENT_TO_VENDOR") or 0),
            "pending_weighing": int(by_g.get("pending_weighing") or 0),
            "weighed_not_started": int(by_g.get("weighed_not_started") or 0),
            "sorted_ready": int(by_g.get("sorted_ready") or 0),
            "wash_dry": int(by_g.get("wash_dry") or 0),
            "folded_completed": folded,
            "sent_to_rinse": sent,
            "unknown_unreconciled": int(by_g.get("unknown") or 0),
        }
        bucket_total = bucket_sum
        completed_from_buckets = folded + sent
    else:
        components = {
            "pending": int(group.get("pending") or 0),
            "at_vendor": int(group.get("at_vendor") or 0),
            "processed_completed": int(group.get("processed_completed") or 0),
            "sent_to_rinse": int(group.get("sent_to_rinse") or 0),
        }
        bucket_total = sum(components.values())
        completed_from_buckets = int(group.get("processed_completed") or 0) + int(group.get("sent_to_rinse") or 0)

    unreconciled = total - bucket_total
    pending_check = total - completed
    return {
        "total": total,
        "completed": completed,
        "pending": pending,
        "completed_from_folded_plus_sent": completed_from_buckets,
        "pending_equals_total_minus_completed": pending == pending_check,
        "bucket_components": components,
        "bucket_sum": bucket_total,
        "unreconciled": unreconciled,
        "balances": unreconciled == 0 and pending == pending_check,
    }


def _clock_hours_diagnostic(
    cursor,
    organization_id: int,
    period_start: date,
    period_end: date,
    clock_hours: float | None,
) -> dict[str, Any]:
    org = int(organization_id)
    out: dict[str, Any] = {
        "total_hours": clock_hours,
        "mapped_users": [],
        "unmapped_users": [],
        "reason_if_missing": "",
    }
    if not table_exists(cursor, "shift_sessions"):
        out["reason_if_missing"] = "Clock source not configured (shift_sessions table missing)"
        return out

    from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et
    from backend.rinse_folding_user_productivity import get_user_map

    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    org_clause = ""
    args: list[Any] = [end_exclusive, start_dt]
    if table_has_column(cursor, "shift_sessions", "organization_id"):
        org_clause = " AND organization_id = %s"
        args = [org, end_exclusive, start_dt]
    user_col = "user_id"
    cursor.execute(
        f"""
        SELECT DISTINCT {user_col} AS uid
        FROM shift_sessions
        WHERE clock_in_at < %s
          AND (clock_out_at IS NULL OR clock_out_at >= %s)
          AND status IN ('completed', 'active', 'auto_closed')
          {org_clause}
        """,
        tuple(args),
    )
    user_ids = [int(r.get("uid")) for r in (cursor.fetchall() or []) if isinstance(r, dict) and r.get("uid") is not None]
    if not user_ids:
        out["reason_if_missing"] = "No clock records found for selected Eastern date range"
        return out

    session_users: list[str] = []
    if table_exists(cursor, "users"):
        ph = ", ".join(["%s"] * len(user_ids))
        cursor.execute(f"SELECT id, name, email FROM users WHERE id IN ({ph})", tuple(user_ids))
        id_to_name = {
            int(r["id"]): str(r.get("name") or r.get("email") or f"user#{r['id']}")
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict)
        }
        session_users = [id_to_name.get(uid, f"user#{uid}") for uid in user_ids]
    else:
        session_users = [f"user#{uid}" for uid in user_ids]

    user_map = get_user_map(cursor, org) if table_exists(cursor, "rinse_folding_user_map") else {}
    mapped = sorted({user_map[u] for u in session_users if u in user_map and user_map[u]})
    unmapped = sorted({u for u in session_users if u not in user_map})
    out["mapped_users"] = mapped
    out["unmapped_users"] = unmapped
    if clock_hours is None or float(clock_hours or 0) <= 0:
        out["reason_if_missing"] = (
            "Clock records exist but total hours is zero for the selected range"
            if session_users
            else "No clock records found for selected date range"
        )
    return out


def _drilldown_parity(
    pending: dict[str, Any],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare KPI counts to filter_lifecycle_pending_rows drilldown sizes."""
    rows = pending.get("rows") or []
    wf = (pending.get("wf_lifecycle") or {}).get("groups") or {}
    hd = (pending.get("hd_lifecycle") or {}).get("groups") or {}
    incoming = (pending.get("incoming") or {}).get("groups") or {}
    combined_wf = wf.get("combined") or {}
    combined_hd = hd.get("combined") or {}
    combined_in = incoming.get("combined") or {}
    exc = pending.get("exceptions") or {}

    checks: list[tuple[str, int | None, dict[str, Any]]] = [
        ("incoming.total", int(combined_in.get("total") or 0), {"incoming_only": True}),
        ("wf_lifecycle.total", int(combined_wf.get("total") or 0), {"record_scope": "wf_lifecycle"}),
        ("wf_lifecycle.completed", int(combined_wf.get("completed") or 0), {"record_scope": "wf_lifecycle", "filter_kind": "completed"}),
        ("wf_lifecycle.pending", int(combined_wf.get("pending") or 0), {"record_scope": "wf_lifecycle", "filter_kind": "pending"}),
        ("hd_lifecycle.total", int(combined_hd.get("total") or 0), {"record_scope": "hd_lifecycle"}),
        ("hd_lifecycle.completed", int(combined_hd.get("completed") or 0), {"record_scope": "hd_lifecycle", "filter_kind": "completed"}),
        ("exceptions.wf.needs_review", int((exc.get("wf") or {}).get("needs_review") or 0), {"filter_kind": "needs_review", "record_scope": "wf_lifecycle"}),
    ]
    by_g = combined_wf.get("by_lifecycle_group") or {}
    for grp, label in LIFECYCLE_GROUP_LABELS.items():
        cnt = int(by_g.get(grp) or 0)
        if cnt:
            checks.append(
                (f"wf_lifecycle.{label}", cnt, {"lifecycle_group": grp, "record_scope": "wf_lifecycle"})
            )

    out: list[dict[str, Any]] = []
    for label, expected, filt in checks:
        if expected is None:
            continue
        filtered = filter_lifecycle_pending_rows(rows, **filt)
        actual = len(filtered)
        out.append(
            {
                "label": label,
                "count_shown": expected,
                "drilldown_rows": actual,
                "match": expected == actual,
                "filter": filt,
            }
        )

    staff = summary.get("staff_performance") or {}
    for task in staff.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        name = task.get("task_name") or task.get("user_name")
        expected = int(task.get("bag_count") or 0)
        recs = [r for r in (staff.get("records") or []) if r.get("task_name") == name or r.get("user_name") == name]
        out.append(
            {
                "label": f"staff_performance.{name}",
                "count_shown": expected,
                "drilldown_rows": len(recs),
                "match": expected == len(recs),
                "filter": {"task": name},
            }
        )
    return out


def build_shift_analysis_debug_payload(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    summary = build_shift_analysis_summary(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
        evaluation_time=evaluation_time,
    )
    pending = summary.get("pending") or get_pending_bag_status(
        cursor, org, target_date=period_end, evaluation_time=evaluation_time
    )
    wf_groups = (pending.get("wf_lifecycle") or {}).get("groups") or {}
    hd_groups = (pending.get("hd_lifecycle") or {}).get("groups") or {}
    wf_combined = wf_groups.get("combined") or {}
    hd_combined = hd_groups.get("combined") or {}
    incoming_meta = (pending.get("incoming") or {}).get("summary") or {}

    leaderboard = aggregate_folding_leaderboard(
        cursor, org, period_start=period_start, period_end=period_end, date_field=date_field
    )
    team = leaderboard.get("team") if isinstance(leaderboard.get("team"), dict) else {}
    rules = leaderboard.get("period_bag_summary") if isinstance(leaderboard.get("period_bag_summary"), dict) else {}
    perf_rows = list_folding_performance_rows(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
        limit=5000,
        offset=0,
        include_total=True,
    )
    all_perf = perf_rows.get("rows") or [] if isinstance(perf_rows, dict) else []
    scoring_rows = [r for r in all_perf if r.get("included_in_scoring") is not False and not r.get("exception_code")]
    excluded_rows = [r for r in all_perf if r.get("included_in_scoring") is False or r.get("exception_code")]

    lifecycle_folded = int((wf_combined.get("by_lifecycle_group") or {}).get("folded") or 0)
    lifecycle_completed = int(wf_combined.get("completed") or 0)

    clock_hours = (summary.get("overall_production") or {}).get("clocked_labor_hours")

    payload = {
        "organization_id": org,
        "selected_date_scope": {
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            "date_meaning": _date_field_meaning(date_field),
            "date_field": date_field,
            "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
            "lifecycle_snapshot_date": period_end.isoformat(),
            "note": "Lifecycle/presence counts use period_end (target date). Team labor uses [start_date, end_date] inclusive.",
        },
        "latest_scrape": _latest_scrape_block(cursor, org),
        "registry": _registry_block(cursor, org, period_start, period_end),
        "staging": _staging_block(cursor, org),
        "presence": {
            "ready_for_vendor_total": int(incoming_meta.get("incoming_total") or 0),
            "ready_for_vendor_wf": int(incoming_meta.get("incoming_wf") or 0),
            "ready_for_vendor_hd": int(incoming_meta.get("incoming_hd") or 0),
            "ready_for_vendor_rush": int(incoming_meta.get("incoming_rush") or 0),
            "ready_for_vendor_non_rush": int(incoming_meta.get("incoming_non_rush") or 0),
            "ready_for_vendor_unknown": int(incoming_meta.get("incoming_unknown_rush") or 0),
            "last_refreshed_at": incoming_meta.get("last_presence_refresh_at"),
        },
        "lifecycle": {
            "wf": _lifecycle_reconciliation(wf_combined, service="wf"),
            "hd": _lifecycle_reconciliation(hd_combined, service="hd"),
            "unreconciled": {
                "wf_bag_ids": [
                    r.get("bag_id")
                    for r in (pending.get("wf_lifecycle") or {}).get("rows") or []
                    if str(r.get("lifecycle_group") or "") == "unknown"
                ],
                "wf_count_integrity": pending.get("count_integrity"),
                "wf_group_unreconciled": int(wf_combined.get("unreconciled") or 0),
            },
        },
        "folding_scoring": {
            "records_total": len(all_perf),
            "scoring_records": len(scoring_rows),
            "excluded_records": len(excluded_rows),
            "bags_folded": int(team.get("bag_count") or 0),
            "lbs_folded": float(team.get("total_lbs") or 0),
            "lifecycle_wf_folded_bucket": lifecycle_folded,
            "lifecycle_wf_completed": lifecycle_completed,
            "mismatch_note": (
                "Team & Labor 'Bags folded' counts folding performance rows in selected date range "
                "(scoring-eligible by default), NOT lifecycle WF folded bucket on target date."
            ),
        },
        "staff_performance": {
            "processing_records": len((summary.get("operational") or {}).get("records") or []),
            "folding_records": len(all_perf),
            "employees": summary.get("employees") or [],
        },
        "clock_hours": _clock_hours_diagnostic(cursor, org, period_start, period_end, clock_hours),
        "drilldown_parity": _drilldown_parity(pending, summary),
        "unknown_rush_analysis": {
            "wf_unknown_rush_total": int((wf_groups.get("unknown_rush") or {}).get("total") or 0),
            "hd_unknown_rush_total": int((hd_groups.get("unknown_rush") or {}).get("total") or 0),
            "incoming_unknown_rush": int(incoming_meta.get("incoming_unknown_rush") or 0),
            "wf_unknown_bags": [
                {
                    "bag_id": r.get("bag_id"),
                    "effective_rush": r.get("effective_rush"),
                    "rush_label": r.get("rush_label"),
                }
                for r in (pending.get("wf_lifecycle") or {}).get("rows") or []
                if r.get("group") == "unknown_rush"
            ][:50],
        },
        "ui_field_map": _ui_field_map(),
    }
    return payload


def _ui_field_map() -> list[dict[str, str]]:
    """Map visible /performance labels to backend sources."""
    rows = [
        ("Clocked hrs", "overall_production.clocked_labor_hours", "build_shift_analysis_summary → _sum_shift_clock_hours", "shift_sessions", "Eastern period overlap", "history", "WF+HD", "WF+HD", "all", "n/a"),
        ("Bags folded", "overall_production.total_bags_completed", "aggregate_folding_leaderboard team.bag_count", "rinse_folding_performance", "date_field period", "history/scoring", "WF", "no", "all", "scoring default"),
        ("Lbs folded", "overall_production.total_lbs_folded", "aggregate_folding_leaderboard team.total_lbs", "rinse_folding_performance", "date_field period", "history", "WF", "no", "all", "scoring"),
        ("Scoring bags", "scoring_data.scoring_bags", "period_bag_summary.included_in_scoring", "rinse_folding_performance", "date_field period", "history", "WF", "no", "scoring", "yes"),
        ("WF lifecycle total", "pending.wf_lifecycle.groups.combined.total", "build_lifecycle_pending_payload", "registry+staging+presence", "period_end target date", "current snapshot", "WF", "no", "rush+non+unknown", "n/a"),
        ("HD lifecycle total", "pending.hd_lifecycle.groups.combined.total", "build_lifecycle_pending_payload", "registry HD rows", "period_end", "current snapshot", "no", "HD", "rush+non+unknown", "n/a"),
        ("Incoming total", "pending.incoming.groups.combined.total", "load_incoming_unassigned_presence_rows", "rinse_cleaner_ticket_presence", "period_end", "current snapshot", "WF+HD", "WF+HD", "rush+non+unknown", "n/a"),
    ]
    return [
        {
            "ui_label": r[0],
            "backend_field": r[1],
            "function": r[2],
            "source_tables": r[3],
            "date_basis": r[4],
            "portal_vs_history": r[5],
            "includes_wf": r[6],
            "includes_hd": r[7],
            "rush_scope": r[8],
            "scoring_only": r[9],
        }
        for r in rows
    ]
