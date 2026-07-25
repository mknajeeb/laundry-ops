"""Step-1 drill-down + manager correction actions for Review Required."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_operator_manual_correction import (
    apply_operator_approved_manual_completion,
    write_operator_audit_log,
)
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_veewash_workload import (
    SERVICE_HD,
    SERVICE_WF,
    VEEWASH_ORG_ID,
    build_step1_headline_summary,
    build_veewash_daily_workload,
    get_step1_activation_date,
    today_et,
)
from backend.ta_helpers import table_exists


def _refresh_step1_day_snapshot_after_mutation(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bag_id: str | None = None,
    outcome_action: str | None = None,
    bulk_cleared: bool = False,
) -> None:
    """Fast post-mutation sync for one bag (no full-day rebuild).

    Full ``build_veewash_daily_workload`` + ``persist_day_snapshot`` can take
    well over the FE 60s timeout and hung Save on Review Required.
    """
    from backend.rinse_veewash_shift_day import (
        apply_manager_edit_day_bag_patch,
        load_day_bags_by_ids,
        _commit,
    )

    bid = normalize_bag_id(bag_id) if bag_id else ""
    if not bid:
        return
    rows = load_day_bags_by_ids(cursor, organization_id, selected_date_et, [bid])
    day_row = rows[0] if rows else {}
    apply_manager_edit_day_bag_patch(
        cursor,
        organization_id,
        selected_date_et,
        bid,
        previous_effective_status=day_row.get("effective_status"),
        previous_reason_codes=list(day_row.get("review_reason_codes") or []),
        outcome_action=outcome_action,
        bulk_cleared=bool(bulk_cleared),
        completion_at=day_row.get("canonical_completion_timestamp"),
        completed_by=day_row.get("canonical_completion_employee"),
        pre_weight_lbs=day_row.get("pre_weight_lbs"),
        post_weight_lbs=day_row.get("post_weight_lbs"),
    )
    _commit(cursor)


def ensure_step1_correction_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_corrections (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(32) NOT NULL,
            action VARCHAR(64) NOT NULL,
            reason_code VARCHAR(64) NULL,
            reason_text VARCHAR(512) NOT NULL,
            previous_values JSON NULL,
            new_values JSON NULL,
            actor_user_id INT NULL,
            actor_display_name VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_step1_corr_org_bag (organization_id, bag_id),
            INDEX idx_step1_corr_created (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip().replace("Z", "")
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        if " " in text:
            return datetime.fromisoformat(text.replace(" ", "T", 1))
        d = date.fromisoformat(text[:10])
        return datetime(d.year, d.month, d.day, 12, 0, 0)
    except ValueError:
        return None


def _record_correction(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    action: str,
    reason_text: str,
    reason_code: str | None,
    previous_values: dict | None,
    new_values: dict | None,
    actor_user_id: int | None,
    actor_display_name: str | None,
) -> None:
    ensure_step1_correction_table(cursor)
    cursor.execute(
        """
        INSERT INTO rinse_step1_corrections (
            organization_id, bag_id, action, reason_code, reason_text,
            previous_values, new_values, actor_user_id, actor_display_name
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            normalize_bag_id(bag_id),
            action,
            reason_code,
            reason_text,
            json.dumps(previous_values, default=str) if previous_values else None,
            json.dumps(new_values, default=str) if new_values else None,
            actor_user_id,
            actor_display_name,
        ),
    )
    write_operator_audit_log(
        cursor,
        organization_id,
        bag_id=bag_id,
        action=f"step1_{action}",
        old_value=previous_values,
        new_value=new_values,
        remarks=reason_text,
        actor_user_id=actor_user_id,
    )


def build_step1_payload(cursor, organization_id: int, selected_date_et: date) -> dict[str, Any]:
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    wl, summary, day = build_or_load_step1_for_date(
        cursor, organization_id, selected_date_et, persist_live=True
    )
    return {"workload": wl, "summary": summary, "day": day}


def normalize_step1_queue_metric(raw: str | None) -> str:
    """
    Map KPI queue aliases onto headline bag_ids keys.

    HD Production Recorded / Missing are UI labels for completed / pending.
    """
    key = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "all": "active_workload",
        "total": "active_workload",
        "total_workload": "active_workload",
        "active": "active_workload",
        "active_workload": "active_workload",
        "completed": "completed",
        "production_recorded": "completed",
        "pending": "pending",
        "production_missing": "pending",
        "review": "review_required",
        "review_required": "review_required",
        "new_today": "new_today",
        "carryover": "carryover",
        "washed": "completed",
        "folded": "completed",
    }
    if key in aliases:
        return aliases[key]
    # Unknown queue → safe default (empty review is better than leaking all bags).
    return "review_required"


def _filter_bag_ids(
    summary: dict[str, Any],
    *,
    metric: str,
    service: str,
    rush: str,
    reason_code: str | None = None,
) -> list[str]:
    from backend.rinse_veewash_workload import _rush_bucket

    segs = summary.get("segments") or {}
    # Resolve segment key
    svc = (service or "all").lower()
    r = (rush or "all").lower().replace("-", "_")
    if svc == "wf" and r == "rush":
        key = "wf_rush"
    elif svc == "wf" and r == "non_rush":
        key = "wf_non_rush"
    elif svc == "hd" and r == "rush":
        key = "hd_rush"
    elif svc == "hd" and r == "non_rush":
        key = "hd_non_rush"
    elif svc == "wf":
        key = "wf"
    elif svc == "hd":
        key = "hd"
    elif r == "rush":
        key = "rush"
    elif r == "non_rush":
        key = "non_rush"
    else:
        key = "all"

    seg = segs.get(key) or {}
    # Do not silently fall back to "all" when a specific service segment is missing —
    # that would open the full queue for a WF/HD card.
    if not seg and key != "all":
        return []
    if not seg:
        seg = segs.get("all") or {}
    bags = seg.get("bag_ids") or {}
    metric_norm = normalize_step1_queue_metric(metric)
    metric_key = {
        "new_today": "new_today",
        "carryover": "carryover",
        "completed": "completed",
        "pending": "pending",
        "review_required": "review_required",
        "active_workload": None,
    }.get(metric_norm, metric_norm)

    if metric_key is None:
        # Active = New + Carryover (includes CWO bags added via Review expand).
        ids = list(bags.get("new_today") or []) + list(bags.get("carryover") or [])
    else:
        ids = list(bags.get(metric_key) or [])

    code = str(reason_code or "").strip()
    if code:
        by_reason = summary.get("review_by_reason") or {}
        reason_ids = set(by_reason.get(code) or [])
        if code == "WF_ZERO_OR_MISSING_WEIGHT":
            reason_ids |= set(by_reason.get("WF_ZERO_OR_MISSING_POST_WEIGHT") or [])
        ids = [b for b in ids if b in reason_ids] if ids else sorted(reason_ids)
    return sorted(set(ids))


def load_scans_for_bags(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Load complete persisted chronology for bags (no SQL LIMIT on events)."""
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    from backend.ta_helpers import table_has_column

    placeholders = ",".join(["%s"] * len(bag_ids))
    provenance_cols = ""
    if table_has_column(cursor, "rinse_bag_scan_events", "weight_source"):
        provenance_cols = (
            ", weight_observed_at, weight_source, "
            "weight_attach_batch_id, weight_attach_reason"
        )
    cursor.execute(
        f"""
        SELECT id, bag_id, scanned_at_parsed, purpose, rack, user_name, weight_lbs
               {provenance_cols}
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id IN ({placeholders})
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), *bag_ids),
    )
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in bag_ids}
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if bid in out:
            out[bid].append(
                {
                    "id": row.get("id"),
                    "scanned_at_parsed": row.get("scanned_at_parsed"),
                    "purpose": row.get("purpose"),
                    "raw_purpose": row.get("purpose"),
                    "rack": row.get("rack"),
                    "user_name": row.get("user_name"),
                    "weight_lbs": float(row["weight_lbs"])
                    if row.get("weight_lbs") is not None
                    else None,
                    "weight_source": row.get("weight_source"),
                    "weight_observed_at": row.get("weight_observed_at"),
                    "weight_attach_batch_id": row.get("weight_attach_batch_id"),
                    "weight_attach_reason": row.get("weight_attach_reason"),
                    "source_table": "rinse_bag_scan_events",
                }
            )
    return out


def build_drilldown(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    metric: str,
    service: str = "all",
    rush: str = "all",
    include_details: bool = False,
    bag_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
    reason_code: str | None = None,
) -> dict[str, Any]:
    """
    Step-1 metric drawer payload.

    Default: bag summaries only (fast). Pass bag_id + include_details for one-bag
    chronology/corrections. Paginate summary lists (default 25).

    Uses persisted day headline for ID filtering, then loads only the current page
    of day-bag rows (never the full day snapshot set on list open).
    """
    import time

    from backend.rinse_bulk_workitems import (
        list_workitems,
        load_bag_bulk_audits,
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )
    from backend.rinse_veewash_shift_day import (
        _workload_shell_from_bags,
        get_day_headline,
        load_day_bags_by_ids,
        summary_from_day_record,
    )

    t0 = time.perf_counter()
    t_snap = time.perf_counter()
    day_rec = get_day_headline(cursor, organization_id, selected_date_et)
    summary = summary_from_day_record(day_rec) if day_rec else None
    snap_ms = (time.perf_counter() - t_snap) * 1000.0

    # Read path only: never call build_step1_payload(persist_live=True). Opening a
    # drawer/modal must not rebuild the live day. Missing snapshot → empty queue.
    if not (day_rec and summary):
        return {
            "selected_date_et": selected_date_et.isoformat(),
            "metric": metric,
            "service": service,
            "rush": rush,
            "bags": [],
            "active_bulk_workitems": [],
            "pagination": {
                "page": max(1, int(page or 1)),
                "page_size": max(1, min(100, int(page_size or 25))),
                "total": 0,
                "has_more": False,
            },
            "snapshot_missing": True,
            "timing_ms": {
                "total": round((time.perf_counter() - t0) * 1000.0, 1),
                "snapshot": round(snap_ms, 1),
            },
        }

    ids = _filter_bag_ids(
        summary or {},
        metric=metric,
        service=service,
        rush=rush,
        reason_code=reason_code,
    )
    if bag_id:
        bid = normalize_bag_id(bag_id)
        ids = [bid] if bid else []

    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 25)))
    total = len(ids)
    start = (page - 1) * page_size
    page_ids = ids if (include_details and bag_id) else ids[start : start + page_size]

    t_bags = time.perf_counter()
    snap_bags = (
        load_day_bags_by_ids(cursor, organization_id, selected_date_et, page_ids)
        if page_ids
        else []
    )
    bags_ms = (time.perf_counter() - t_bags) * 1000.0

    # Prefer page snapshots; if IDs exist but rows are missing, still do not rebuild.
    wl = _workload_shell_from_bags(
        snap_bags,
        selected_date_et=selected_date_et,
        status=str((day_rec or {}).get("status") or "OPEN"),
    )

    rows_by_id = {r.get("bag_id"): r for r in (wl.get("rows") or []) if r.get("bag_id")}
    for sb in snap_bags:
        bid = sb.get("bag_id")
        if not bid:
            continue
        snap = sb.get("bag_snapshot") or {}
        rows_by_id[bid] = {
            **(rows_by_id.get(bid) or {}),
            **snap,
            "bag_id": bid,
            "customer_name": snap.get("customer_name")
            or (rows_by_id.get(bid) or {}).get("customer_name"),
            "service_type": snap.get("service_type") or sb.get("service_type"),
            "rush_flag": snap.get("rush_flag") or sb.get("rush_status"),
            "pre_weight_lbs": snap.get("pre_weight_lbs", sb.get("pre_weight_lbs")),
            "post_weight_lbs": snap.get("post_weight_lbs", sb.get("post_weight_lbs")),
            "weight_lbs": snap.get("weight_lbs", sb.get("weight_lbs")),
            "completion_at": snap.get("completion_at")
            or sb.get("canonical_completion_timestamp"),
            "completed_by": snap.get("completed_by")
            or sb.get("canonical_completion_employee"),
            "reason_codes": snap.get("reason_codes") or sb.get("review_reason_codes") or [],
            "outcome": snap.get("outcome") or sb.get("effective_status"),
            "final_bucket": snap.get("final_bucket") or sb.get("effective_status"),
            "entry_class": snap.get("entry_class") or sb.get("new_or_carryover"),
            "original_entry_date": snap.get("original_entry_date")
            or sb.get("workload_entry_timestamp"),
            "entry_source": snap.get("entry_source") or sb.get("workload_entry_type"),
            "portal_status": snap.get("portal_status") or sb.get("portal_status_at_sync"),
            "post_weight_event_exists": snap.get("post_weight_event_exists"),
            "updated_at": sb.get("updated_at"),
            "day_bag_updated_at": sb.get("updated_at"),
            "manager_edit_version": int(sb.get("manager_edit_version") or 0),
        }

    reasons = wl.get("review_reasons_by_bag") or (summary or {}).get("review_reasons_by_bag") or {}
    for sb in snap_bags:
        bid = sb.get("bag_id")
        if bid and sb.get("review_reason_codes") and bid not in reasons:
            reasons[bid] = list(sb.get("review_reason_codes") or [])

    # List path: reason codes + denormalized snapshot fields are enough.
    # Full bulk lines/scans load only on bag expand. Catalog loads for the bulk-reason
    # drawer (or expand) so managers can edit without waiting for every line query.
    need_bulk_catalog = bool(include_details) or str(reason_code or "") == "WF_BULK_WORKITEM_REVIEW"
    need_bulk_lines = bool(include_details)
    bulk_scans: dict = {}
    bulk_lines: dict = {}
    bulk_resolutions: dict = {}
    active_catalog: list = []
    if page_ids and need_bulk_lines:
        bulk_scans = load_bulk_workitem_scan_map(cursor, organization_id, page_ids)
        bulk_lines = load_bag_bulk_lines(
            cursor, organization_id, selected_date_et, page_ids
        )
        bulk_resolutions = load_bulk_resolutions(
            cursor, organization_id, selected_date_et, page_ids
        )
    if need_bulk_catalog:
        active_catalog = list_workitems(cursor, organization_id, active_only=True)


    scans: dict[str, list] = {b: [] for b in page_ids}
    corrections: dict[str, list] = {b: [] for b in page_ids}
    bulk_audits: dict[str, list] = {b: [] for b in page_ids}
    last_edits: dict[str, dict] = {}
    detail_ms = 0.0
    if include_details and page_ids:
        t_detail = time.perf_counter()
        scans = load_scans_for_bags(cursor, organization_id, page_ids)
        if table_exists(cursor, "rinse_step1_corrections"):
            placeholders = ",".join(["%s"] * len(page_ids))
            cursor.execute(
                f"""
                SELECT bag_id, action, reason_code, reason_text, previous_values, new_values,
                       actor_display_name, created_at
                FROM rinse_step1_corrections
                WHERE organization_id = %s AND bag_id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                (int(organization_id), *page_ids),
            )
            for row in cursor.fetchall() or []:
                bid = normalize_bag_id(row.get("bag_id"))
                if bid in corrections:
                    corrections[bid].append(
                        {
                            "action": row.get("action"),
                            "reason_code": row.get("reason_code"),
                            "reason_text": row.get("reason_text"),
                            "previous_values": row.get("previous_values"),
                            "new_values": row.get("new_values"),
                            "actor_display_name": row.get("actor_display_name"),
                            "created_at": row.get("created_at"),
                        }
                    )
        if table_exists(cursor, "rinse_step1_bag_edits"):
            placeholders = ",".join(["%s"] * len(page_ids))
            cursor.execute(
                f"""
                SELECT id, bag_id, reason, is_undo, created_at
                FROM rinse_step1_bag_edits
                WHERE organization_id = %s
                  AND shift_date_et = %s
                  AND bag_id IN ({placeholders})
                ORDER BY id DESC
                """,
                (int(organization_id), selected_date_et, *page_ids),
            )
            for row in cursor.fetchall() or []:
                bid = normalize_bag_id(row.get("bag_id"))
                if not bid or bid in last_edits:
                    continue
                last_edits[bid] = {
                    "last_edit_id": int(row["id"]),
                    "last_edit_reason": row.get("reason"),
                    "last_edit_is_undo": bool(row.get("is_undo")),
                    "last_edit_undoable": not bool(row.get("is_undo")),
                    "last_edit_at": row.get("created_at"),
                }
        for bid in page_ids:
            bulk_audits[bid] = load_bag_bulk_audits(
                cursor, organization_id, selected_date_et, bid
            )
        detail_ms = (time.perf_counter() - t_detail) * 1000.0

    bags = []
    for bid in page_ids:
        r = rows_by_id.get(bid) or {}
        lines = bulk_lines.get(bid) or r.get("bulk_workitems") or []
        scan_info = bulk_scans.get(bid) or r.get("bulk_workitem_scan") or {}
        item = {
            "bag_id": bid,
            "customer_name": r.get("customer_name"),
            "service_type": r.get("service_type"),
            "rush_flag": r.get("rush_flag"),
            "entry_class": r.get("entry_class"),
            "dashboard_status": r.get("outcome") or r.get("final_bucket"),
            "canonical_status": r.get("canonical_status"),
            "reason_codes": list(reasons.get(bid) or r.get("reason_codes") or []),
            "weight_lbs": r.get("weight_lbs"),
            "pre_weight_lbs": r.get("pre_weight_lbs"),
            "post_weight_lbs": r.get("post_weight_lbs"),
            "post_weight_event_exists": r.get("post_weight_event_exists"),
            "pre_weight_at": r.get("pre_weight_at"),
            "post_weight_at": r.get("post_weight_at"),
            "pre_weight_source": r.get("pre_weight_source"),
            "pre_weight_observed_at": r.get("pre_weight_observed_at"),
            "pre_weight_attach_batch_id": r.get("pre_weight_attach_batch_id"),
            "pre_weight_attach_reason": r.get("pre_weight_attach_reason"),
            "post_weight_source": r.get("post_weight_source"),
            "post_weight_observed_at": r.get("post_weight_observed_at"),
            "post_weight_attach_batch_id": r.get("post_weight_attach_batch_id"),
            "post_weight_attach_reason": r.get("post_weight_attach_reason"),
            "entry_at": r.get("original_entry_date") or r.get("first_entry_at"),
            "entry_source": r.get("entry_source"),
            "completion_at": r.get("completion_at"),
            "completed_by": r.get("completed_by"),
            "portal_status": r.get("portal_status"),
            "last_seen_at": r.get("last_seen_date"),
            "updated_at": r.get("updated_at") or r.get("day_bag_updated_at"),
            "day_bag_updated_at": r.get("day_bag_updated_at") or r.get("updated_at"),
            "manager_edit_version": int(
                r.get("manager_edit_version")
                if r.get("manager_edit_version") is not None
                else 0
            ),
            "bulk_workitem_scan": scan_info,
            "bulk_workitems": lines if include_details else [],
            "bulk_resolution": bulk_resolutions.get(bid) or r.get("bulk_resolution"),
            "bulk_item_total": round(sum(float(x.get("line_total") or 0) for x in lines), 2),
            "bulk_review_required": bool(
                "WF_BULK_WORKITEM_REVIEW"
                in (reasons.get(bid) or r.get("reason_codes") or [])
            ),
            "system_result": {
                "outcome": r.get("outcome"),
                "canonical_status": r.get("canonical_status"),
                "reason_codes": list(reasons.get(bid) or r.get("reason_codes") or []),
                "completion_at": r.get("completion_at"),
                "completed_by": r.get("completed_by"),
            },
        }
        if include_details:
            item["scans"] = scans.get(bid) or []
            item["corrections"] = corrections.get(bid) or []
            item["bulk_audits"] = bulk_audits.get(bid) or []
            item["bulk_workitems"] = lines
            edit_meta = last_edits.get(bid) or {}
            item.update(edit_meta)
            # Overlay live scan-row Pre/Post + provenance (day snapshot may lag).
            from backend.rinse_scan_purpose import is_weight_entry_purpose
            from backend.rinse_veewash_review import resolve_weight_entry_pair

            weight_events = [
                s
                for s in (item["scans"] or [])
                if is_weight_entry_purpose(s.get("purpose") or s.get("raw_purpose"))
            ]
            live = resolve_weight_entry_pair(weight_events)
            for key in (
                "pre_weight_lbs",
                "post_weight_lbs",
                "post_weight_value",
                "post_weight_event_exists",
                "weight_entry_count",
                "pre_weight_source",
                "pre_weight_observed_at",
                "pre_weight_attach_batch_id",
                "pre_weight_attach_reason",
                "post_weight_source",
                "post_weight_observed_at",
                "post_weight_attach_batch_id",
                "post_weight_attach_reason",
                "pre_weight_at",
                "post_weight_at",
            ):
                if live.get(key) is not None:
                    item[key] = live.get(key)
            # Explicit nulls from a real empty pre still win over stale snapshot
            # when live chronology has weight-entry rows.
            if weight_events:
                item["pre_weight_lbs"] = live.get("pre_weight_lbs")
                item["post_weight_lbs"] = live.get("post_weight_lbs")
                item["post_weight_value"] = live.get("post_weight_value")
                item["post_weight_event_exists"] = live.get("post_weight_event_exists")
                item["weight_entry_count"] = live.get("weight_entry_count")

        else:
            item["scans"] = []
            item["corrections"] = []
            item["bulk_audits"] = []
        bags.append(item)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # Drawer list needs reason counts, not full bag-id maps (keeps payload small).
    review_counts = {
        k: len(v or [])
        for k, v in ((summary or {}).get("review_by_reason") or {}).items()
    }
    from backend.rinse_scan_freshness import freshness_from_day_and_presence

    pending_ids = list(((summary or {}).get("segments") or {}).get("all", {}).get("bag_ids", {}).get("pending") or [])
    if not pending_ids and metric == "pending":
        pending_ids = list(page_ids or [])
    data_freshness = freshness_from_day_and_presence(
        cursor,
        organization_id,
        selected_date_et,
        day_meta=day_rec,
        sample_bag_ids=page_ids,
        pending_bag_ids=pending_ids,
    )
    if summary is not None:
        summary = dict(summary)
        summary["data_freshness"] = data_freshness
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "metric": metric,
        "service": service,
        "rush": rush,
        "reason_code": reason_code,
        "bags": bags,
        "active_bulk_workitems": active_catalog,
        "review_by_reason": review_counts,
        "data_freshness": data_freshness,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        },
        "include_details": bool(include_details),
        "timing_ms": {
            "total": round(elapsed_ms, 1),
            "headline": round(snap_ms, 1),
            "page_bags": round(bags_ms, 1),
            "detail_queries": round(detail_ms, 1),
        },
    }



def apply_step1_correction(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    action: str,
    body: dict[str, Any],
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    bid = normalize_bag_id(bag_id)
    action = str(action or "").strip().lower()
    reason = str(body.get("reason") or body.get("correction_reason") or "").strip()
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}

    if action == "save_bulk_workitems":
        from backend.rinse_bulk_workitems import save_bag_bulk_workitems

        day_raw = body.get("selected_date_et") or body.get("date")
        day = today_et()
        if day_raw:
            try:
                day = date.fromisoformat(str(day_raw)[:10])
            except ValueError:
                pass
        out = save_bag_bulk_workitems(
            cursor,
            organization_id,
            shift_date_et=day,
            bag_id=bid,
            items=list(body.get("items") or []),
            no_chargeable=bool(body.get("no_chargeable") or body.get("no_chargeable_bulk_items")),
            no_charge_reason=str(body.get("no_charge_reason") or reason or "").strip() or None,
            reason=reason or None,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        if out.get("ok"):
            try:
                from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

                clear_step1_productivity_cache(organization_id, day)
            except Exception:
                pass
            # Fast single-bag queue sync (full day rebuild hung Save for 60s+).
            try:
                _refresh_step1_day_snapshot_after_mutation(
                    cursor,
                    organization_id,
                    day,
                    bag_id=bid,
                    bulk_cleared=True,
                )
            except Exception:
                pass
        return out

    if not reason and action not in ("undo_bag_edit", "edit_bag", "save_bulk_workitems"):
        return {"ok": False, "error": "reason_required"}

    day_raw = body.get("selected_date_et") or body.get("date")
    day = today_et()
    if day_raw:
        try:
            day = date.fromisoformat(str(day_raw)[:10])
        except ValueError:
            pass

    from backend.rinse_veewash_shift_day import STATUS_CLOSED, get_day_record

    day_rec = get_day_record(cursor, organization_id, day)
    if day_rec and day_rec.get("status") == STATUS_CLOSED:
        return {
            "ok": False,
            "error": "shift_closed_reopen_required",
            "day_status": STATUS_CLOSED,
        }

    # edit_bag / undo must NOT rebuild the day BEFORE the optimistic-lock check
    # (that caused false "bag updated while reviewing" conflicts). After a
    # successful mutation, refresh the persisted day so Review Required / Completed
    # membership matches registry + bulk resolution.
    if action == "edit_bag":
        from backend.rinse_step1_edit_bag import apply_unified_bag_edit

        out = apply_unified_bag_edit(
            cursor,
            organization_id,
            bag_id=bid,
            selected_date_et=day,
            reason=reason,
            draft=dict(body.get("draft") or {}),
            expected_updated_at=body.get("expected_updated_at"),
            expected_manager_edit_version=body.get("expected_manager_edit_version"),
            outcome_action=body.get("outcome_action"),
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            reason_code=body.get("reason_code"),
            reason_note=body.get("reason_note") or body.get("reason") or None,
        )
        if out.get("ok"):
            try:
                from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

                clear_step1_productivity_cache(organization_id, day)
            except Exception:
                pass
            # Membership already patched inside apply_unified_bag_edit.
        return out

    if action == "undo_bag_edit":
        from backend.rinse_step1_edit_bag import undo_bag_edit

        edit_id_raw = body.get("edit_id")
        try:
            edit_id = int(edit_id_raw)
        except (TypeError, ValueError):
            return {"ok": False, "error": "edit_id_required"}
        out = undo_bag_edit(
            cursor,
            organization_id,
            edit_id=edit_id,
            reason=body.get("reason") or reason or None,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        if out.get("ok"):
            try:
                from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

                clear_step1_productivity_cache(organization_id, day)
            except Exception:
                pass
            try:
                restored = (out.get("after") or out.get("bag") or {})
                _refresh_step1_day_snapshot_after_mutation(
                    cursor,
                    organization_id,
                    day,
                    bag_id=bid,
                    outcome_action=None,
                    bulk_cleared=bool(restored.get("bulk_items") or restored.get("no_chargeable")),
                )
            except Exception:
                out = {
                    **out,
                    "warning": "day_snapshot_refresh_failed",
                }
        return out

    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(organization_id, day)
    except Exception:
        pass
    # Snapshot prior row from workload (legacy correction actions only).
    payload = build_step1_payload(cursor, organization_id, day)
    prior = next(
        (r for r in (payload["workload"].get("rows") or []) if r.get("bag_id") == bid),
        {},
    )

    if action in ("mark_completed", "correct_completion"):
        emp = str(body.get("employee") or body.get("completed_by") or "").strip()
        ts = _parse_dt(body.get("completion_at") or body.get("completion_timestamp"))
        if not emp or not ts:
            return {"ok": False, "error": "employee_and_completion_at_required"}
        weight = body.get("weight_lbs")
        try:
            weight_f = float(weight) if weight not in (None, "") else 0.1
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_weight"}
        # Need an upload batch id — use 0 sentinel if helper requires int
        out = apply_operator_approved_manual_completion(
            cursor,
            organization_id,
            bid,
            credited_employee=emp,
            weight_lbs=weight_f,
            selected_date_et=day,
            completion_timestamp=ts,
            upload_batch_id=int(body.get("upload_batch_id") or 0),
            remarks=reason,
            actor_user_id=actor_user_id,
        )
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code=str(body.get("reason_code") or "MANUAL_COMPLETION"),
            previous_values=prior,
            new_values={"completion_at": ts.isoformat(), "employee": emp, "result": out},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {"ok": True, "action": action, "result": out}

    if action == "correct_weight":
        try:
            weight_f = float(body.get("weight_lbs"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "weight_lbs_required"}
        if weight_f <= 0:
            return {"ok": False, "error": "weight_must_be_positive"}
        emp = str(body.get("employee") or "manager").strip()
        ts = _parse_dt(body.get("weight_at") or body.get("completion_at")) or datetime.utcnow()
        detected_pre = prior.get("pre_weight_lbs")
        detected_post = prior.get("post_weight_lbs")
        # Correction updates effective post only — never mutate source scan events.
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code="WF_ZERO_OR_MISSING_POST_WEIGHT",
            previous_values={
                "pre_weight_lbs": detected_pre,
                "post_weight_lbs": detected_post,
                "original_detected_pre_weight": detected_pre,
                "original_detected_post_weight": detected_post,
            },
            new_values={
                "pre_weight_lbs": detected_pre,
                "post_weight_lbs": weight_f,
                "corrected_post_weight_lbs": weight_f,
                "original_detected_pre_weight": detected_pre,
                "original_detected_post_weight": detected_post,
                "weight_at": ts.isoformat(),
                "employee": emp,
                "manager": actor_display_name,
                "manager_user_id": actor_user_id,
            },
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {
            "ok": True,
            "action": action,
            "weight_lbs": weight_f,
            "post_weight_lbs": weight_f,
            "pre_weight_lbs": detected_pre,
            "original_detected_pre_weight": detected_pre,
            "original_detected_post_weight": detected_post,
            "corrected_post_weight_lbs": weight_f,
        }

    if action == "correct_entry":
        svc = str(body.get("service_type") or prior.get("service_type") or SERVICE_WF).upper()
        ts = _parse_dt(body.get("entry_at") or body.get("entry_timestamp"))
        if not ts:
            return {"ok": False, "error": "entry_at_required"}
        if svc == SERVICE_HD:
            purpose = "workitems-added"
            rack = None
        else:
            purpose = "move-bag"
            rack = str(body.get("rack") or (DEFAULT_FACILITY_ENTRY_RACKS[0] if DEFAULT_FACILITY_ENTRY_RACKS else "VeeWash Dirty"))
        from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
        from backend.rinse_scan_event_identity import dedupe_key_from_row

        ensure_rinse_bag_scan_events_table(cursor)
        time_raw = ts.strftime("%Y-%m-%d %H:%M:%S")
        emp = str(body.get("employee") or actor_display_name or "manager").strip()
        row = {
            "organization_id": int(organization_id),
            "bag_id": bid,
            "purpose": purpose,
            "scanned_at_parsed": ts,
            "time_scanned_raw": time_raw,
            "user_name": emp,
            "rack": rack,
        }
        dedupe = dedupe_key_from_row(row)
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, purpose, scanned_at_parsed, time_scanned_raw,
                user_name, rack, dedupe_key, raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE scanned_at_parsed=VALUES(scanned_at_parsed),
                rack=VALUES(rack), purpose=VALUES(purpose)
            """,
            (
                int(organization_id),
                bid,
                purpose,
                ts,
                time_raw,
                emp,
                rack,
                dedupe,
                json.dumps(
                    {
                        "backfill_source": "step1_correct_entry",
                        "service_type": svc,
                        "operator_approved": True,
                    }
                ),
            ),
        )
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code="COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
            previous_values={"entry": prior.get("original_entry_date"), "service": prior.get("service_type")},
            new_values={
                "service_type": svc,
                "entry_at": ts.isoformat(),
                "purpose": purpose,
                "rack": rack,
            },
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {"ok": True, "action": action, "entry_at": ts.isoformat(), "service_type": svc}

    if action in ("return_pending", "exclude", "move_to_review"):
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code=str(
                body.get("reason_code")
                or ("SCAN_CHRONOLOGY_STALE" if action == "move_to_review" else action.upper())
            ),
            previous_values=prior,
            new_values={"status": action},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        # Soft flag via correction table; reporting prefers corrections on next expand.
        return {"ok": True, "action": action, "note": "audit_recorded"}

    return {"ok": False, "error": f"unknown_action:{action}"}
