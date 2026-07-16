"""High-confidence backfill for near-complete WF bags missing post-processing weight.

When a folder has already run complete-cleaning and the registry has a portal
weight, but Events CSV never captured the final weight-entry (often after the bag
left the portal crawl / was wrongly REJECTED as MISSING_FROM_LATEST_PORTAL_SCRAPE),
insert a synthetic post-processing weight-entry so At Vendor + employee productivity
reconcile.

Eligibility (all required):
- WF bag pending in At Vendor (or still near-complete after targeted refresh)
- complete-cleaning on the selected ET day
- no post-processing weight after latest processing scan
- registry weight_num > 0
- credit to the complete-cleaning scan user
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

BACKFILL_SOURCE = "near_complete_wf_weight_backfill"


def near_complete_weight_backfill_enabled() -> bool:
    raw = (os.getenv("RINSE_NEAR_COMPLETE_WEIGHT_BACKFILL_ENABLED") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _latest_complete_cleaning_on_day(
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
) -> tuple[datetime | None, dict[str, Any] | None]:
    from backend.rinse_bag_stage_bounds import event_ts
    from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
    from backend.rinse_scan_purpose import is_complete_cleaning_purpose

    start = naive_et_day_start(selected_date_et)
    end = naive_et_day_end_inclusive(selected_date_et)
    best: tuple[datetime, dict[str, Any]] | None = None
    for ev in events:
        if not is_complete_cleaning_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev) or ev.get("scanned_at_parsed")
        if not isinstance(ts, datetime):
            continue
        if start <= ts <= end:
            if best is None or ts > best[0]:
                best = (ts, dict(ev))
    if best is None:
        return None, None
    return best


def _registry_weight_lbs(cursor, organization_id: int, bag_id: str) -> float | None:
    cursor.execute(
        """
        SELECT weight_num, completion_status, completion_reason
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bag_id),
    )
    row = cursor.fetchone() or {}
    raw = row.get("weight_num") if isinstance(row, dict) else None
    if raw is None:
        return None
    try:
        lbs = float(raw)
    except (TypeError, ValueError):
        return None
    return lbs if lbs > 0 else None


def _insert_post_processing_weight_scan(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    scanned_at: datetime,
    user_name: str | None,
    weight_lbs: float,
    anchor_purpose: str | None,
) -> dict[str, Any]:
    from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
    from backend.rinse_scan_event_identity import dedupe_key_from_row
    from backend.rinse_workload_bag_weight import ensure_scan_events_weight_lbs_column

    ensure_rinse_bag_scan_events_table(cursor)
    ensure_scan_events_weight_lbs_column(cursor)
    time_raw = scanned_at.strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "organization_id": organization_id,
        "bag_id": bag_id,
        "purpose": "weight-entry",
        "scanned_at_parsed": scanned_at,
        "time_scanned_raw": time_raw,
        "user_name": user_name,
        "rack": None,
        "scan_index": None,
        "last_location": None,
        "last_scan": None,
    }
    dedupe_key = dedupe_key_from_row(row)
    cursor.execute(
        """
        SELECT id, weight_lbs FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s AND dedupe_key = %s
        LIMIT 1
        """,
        (int(organization_id), bag_id, dedupe_key),
    )
    existing = cursor.fetchone()
    if existing:
        if existing.get("weight_lbs") is None:
            cursor.execute(
                """
                UPDATE rinse_bag_scan_events
                SET weight_lbs = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (weight_lbs, existing["id"]),
            )
            return {
                "action": "updated_existing_scan_weight",
                "scan_event_id": existing["id"],
                "dedupe_key": dedupe_key,
            }
        return {
            "action": "scan_already_exists",
            "scan_event_id": existing["id"],
            "dedupe_key": dedupe_key,
        }

    raw_json = json.dumps(
        {
            "Bag ID": bag_id,
            "Purpose": "weight-entry",
            "Time Scanned": time_raw,
            "User": user_name or "",
            "backfill_source": BACKFILL_SOURCE,
            "anchor_purpose": anchor_purpose,
            "Weight": weight_lbs,
        }
    )
    cursor.execute(
        """
        INSERT INTO rinse_bag_scan_events (
            organization_id, bag_id, dedupe_key, scan_index, rack,
            time_scanned_raw, scanned_at_parsed, source_timezone,
            user_name, purpose, last_location, last_scan,
            source_upload_batch_id, source_filename, weight_lbs,
            last_seen_at, raw_json, created_at, updated_at
        ) VALUES (
            %s, %s, %s, NULL, NULL,
            %s, %s, 'America/New_York',
            %s, 'weight-entry', NULL, NULL,
            0, %s, %s,
            NOW(), %s, NOW(), NOW()
        )
        """,
        (
            int(organization_id),
            bag_id,
            dedupe_key,
            time_raw,
            scanned_at,
            user_name,
            BACKFILL_SOURCE,
            weight_lbs,
            raw_json,
        ),
    )
    return {
        "action": "inserted_post_processing_weight_scan",
        "scan_event_id": cursor.lastrowid,
        "dedupe_key": dedupe_key,
        "weight_lbs": weight_lbs,
        "scanned_at": scanned_at.isoformat(),
    }


def plan_near_complete_wf_backfill_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a plan dict; eligible=True only for high-confidence near-complete bags."""
    from backend.rinse_at_vendor_module import (
        _load_at_vendor_scan_events_for_bags,
        _resolve_selected_day_anchor_ts,
    )
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_wf_weight_events import wf_post_processing_weight_completion

    bid = str(bag_id or "").strip().upper()
    org = int(organization_id)
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    if events is None:
        events = _load_at_vendor_scan_events_for_bags(
            cursor, org, [bid], scanned_before=as_of_end
        ).get(bid, [])

    cc_ts, cc_ev = _latest_complete_cleaning_on_day(events, selected_date_et)
    weight_lbs = _registry_weight_lbs(cursor, org, bid)
    anchor = _resolve_selected_day_anchor_ts(events, selected_date_et)
    timeline = gaming_events_from_records(list(events))
    weight_hit = (
        wf_post_processing_weight_completion(
            timeline, anchor_ts=anchor, as_of_end=as_of_end
        )
        if anchor is not None
        else None
    )

    plan: dict[str, Any] = {
        "bag_id": bid,
        "eligible": False,
        "complete_cleaning_ts": cc_ts.isoformat() if cc_ts else None,
        "credited_employee": (cc_ev or {}).get("user_name"),
        "registry_weight_lbs": weight_lbs,
        "has_post_processing_weight": weight_hit is not None,
    }
    if cc_ts is None or cc_ev is None:
        plan["skip_reason"] = "no_complete_cleaning_on_selected_day"
        return plan
    if weight_lbs is None:
        plan["skip_reason"] = "no_registry_weight"
        return plan
    if weight_hit is not None:
        plan["skip_reason"] = "already_has_post_processing_weight"
        return plan

    plan["eligible"] = True
    plan["proposed_scanned_at"] = (cc_ts + timedelta(minutes=1)).isoformat()
    plan["anchor_purpose"] = str(cc_ev.get("purpose") or "complete-cleaning")
    return plan


def apply_near_complete_wf_backfill_for_bag(
    conn,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Insert synthetic post-weight, restore wrongful portal rejection, recompute."""
    from backend.rinse_at_vendor_module import (
        AV_STATUS_COMPLETED,
        _evaluate_bag_as_of,
        _load_at_vendor_scan_events_for_bags,
        _resolve_selected_day_anchor_ts,
    )
    from backend.rinse_bag_registry import recompute_completion_for_bags
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_portal_departure_completion import restore_portal_scrape_rejected_bag
    from backend.rinse_wf_weight_events import wf_post_processing_weight_completion

    org = int(organization_id)
    bid = str(bag_id or "").strip().upper()
    cur = conn.cursor(dictionary=True)
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    events = _load_at_vendor_scan_events_for_bags(
        cur, org, [bid], scanned_before=as_of_end
    ).get(bid, [])
    plan = plan_near_complete_wf_backfill_for_bag(
        cur, org, bid, selected_date_et=selected_date_et, events=events
    )
    if not plan.get("eligible"):
        return {**plan, "applied": False, "dry_run": dry_run}

    if dry_run:
        return {**plan, "applied": False, "dry_run": True, "would_apply": True}

    cc_ts = datetime.fromisoformat(plan["complete_cleaning_ts"])
    post_ts = cc_ts + timedelta(minutes=1)
    weight_lbs = float(plan["registry_weight_lbs"])
    user_name = plan.get("credited_employee")

    prior_autocommit = getattr(conn, "autocommit", True)
    conn.autocommit = False
    conn.rollback()
    steps: list[dict[str, Any]] = []
    try:
        insert_result = _insert_post_processing_weight_scan(
            cur,
            org,
            bid,
            scanned_at=post_ts,
            user_name=user_name,
            weight_lbs=weight_lbs,
            anchor_purpose=plan.get("anchor_purpose"),
        )
        steps.append({"insert_weight_scan": insert_result})

        restored = restore_portal_scrape_rejected_bag(cur, org, bid)
        steps.append({"restore_registry_rejection": restored})

        recompute = recompute_completion_for_bags(cur, org, [bid])
        steps.append({"recompute_registry": recompute})

        events_after = _load_at_vendor_scan_events_for_bags(
            cur, org, [bid], scanned_before=as_of_end
        ).get(bid, [])
        anchor_after = _resolve_selected_day_anchor_ts(events_after, selected_date_et)
        timeline = gaming_events_from_records(events_after)
        status_after, signal_after, comp_ts, _, _ = _evaluate_bag_as_of(
            events_after,
            service_type="WF",
            as_of_end=as_of_end,
            anchor_ts_override=anchor_after,
        )
        weight_hit = (
            wf_post_processing_weight_completion(
                timeline, anchor_ts=anchor_after, as_of_end=as_of_end
            )
            if anchor_after
            else None
        )
        success = status_after == AV_STATUS_COMPLETED and weight_hit is not None
        if success:
            conn.commit()
        else:
            conn.rollback()
        conn.autocommit = prior_autocommit
        return {
            **plan,
            "applied": success,
            "dry_run": False,
            "success": success,
            "steps": steps,
            "after": {
                "at_vendor_status": status_after,
                "completion_signal": signal_after,
                "completion_ts": str(comp_ts) if comp_ts else None,
                "post_processing_weight_lbs": (
                    weight_hit.second_weight_lbs if weight_hit else None
                ),
            },
        }
    except Exception as exc:
        conn.rollback()
        conn.autocommit = prior_autocommit
        return {
            **plan,
            "applied": False,
            "dry_run": False,
            "success": False,
            "error": str(exc),
            "steps": steps,
        }


def backfill_near_complete_wf_after_refresh(
    conn,
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    bag_ids: list[str] | None = None,
    dry_run: bool | None = None,
    max_bags: int = 25,
    log_fn=None,
) -> dict[str, Any]:
    """
    After targeted portal refresh, backfill remaining near-complete WF bags
    that still lack post-processing weight but have registry lbs.
    """
    from backend.rinse_off_portal_scan_refresh import resolve_pending_near_complete_bag_ids
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not near_complete_weight_backfill_enabled():
        _log("Near-complete WF weight backfill skipped (disabled)")
        return {"skipped": True, "reason": "disabled", "bags": []}

    org = int(organization_id)
    dry = bool(dry_run) if dry_run is not None else False
    ctx = baseline_ctx or build_baseline_context(
        cursor, org, get_shift_monitor_baseline(cursor, org)
    )
    targets = [str(b).upper() for b in (bag_ids or []) if b]
    if not targets:
        targets = resolve_pending_near_complete_bag_ids(
            cursor,
            org,
            selected_date_et=selected_date_et,
            baseline_ctx=ctx,
        )
    targets = targets[: max(1, int(max_bags))]

    results: list[dict[str, Any]] = []
    applied = 0
    eligible = 0
    for bid in targets:
        out = apply_near_complete_wf_backfill_for_bag(
            conn,
            org,
            bid,
            selected_date_et=selected_date_et,
            dry_run=dry,
        )
        results.append(out)
        if out.get("eligible"):
            eligible += 1
        if out.get("applied"):
            applied += 1
            _log(
                f"Near-complete WF backfill applied {bid} "
                f"-> {((out.get('after') or {}).get('at_vendor_status'))} "
                f"credit={out.get('credited_employee')} lbs={out.get('registry_weight_lbs')}"
            )
        elif out.get("eligible") and dry:
            _log(f"Near-complete WF backfill would apply {bid}")

    return {
        "dry_run": dry,
        "bags_considered": len(targets),
        "eligible": eligible,
        "applied": applied,
        "bags": results,
    }
