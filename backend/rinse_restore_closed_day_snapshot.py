"""Restore a CLOSED day's published Management snapshot from day_bags.

Never uses live/current Rinse YTP. Historical membership stays on that
business date's persisted day_bags + day headline, with weight totals merged.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def restore_closed_day_published_snapshot_from_day_bags(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    lane: str = "deep",
    lease_generation: int | None = None,
    cycle_id: int | None = None,
) -> dict[str, Any]:
    """Rebuild headline from persisted day_bags and republish for Management."""
    from backend.management_today import load_wf_day_weight_totals
    from backend.rinse_freshness_publish import begin_snapshot_build, publish_snapshot
    from backend.rinse_freshness_store import get_watermarks
    from backend.rinse_management_headline_guard import (
        headline_has_wf_workload_segments,
        merge_weights_into_headline,
    )
    from backend.rinse_veewash_shift_day import (
        STATUS_CLOSED,
        _sync_day_header_from_persisted_bags,
        get_day_record,
        summary_from_day_record,
    )

    org = int(organization_id)
    day = shift_date_et
    day_rec = get_day_record(cursor, org, day)
    if not day_rec:
        return {"ok": False, "reason": "no_day_record"}
    status = str(day_rec.get("status") or "").upper()
    if status != STATUS_CLOSED:
        return {
            "ok": False,
            "reason": f"day_not_closed:{status}",
            "hint": "only restore CLOSED historical days via this path",
        }

    base = summary_from_day_record(day_rec) or dict(day_rec.get("headline") or {})
    # Rebuild membership ID lists from THIS day's day_bags only (never live YTP).
    cursor.execute(
        """
        SELECT bag_id, service_type, new_or_carryover, effective_status
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (org, day),
    )
    rows = cursor.fetchall() or []
    membership_by_seg: dict[str, dict[str, list[str]]] = {
        "all": {"new_today": [], "carryover": []},
        "wf": {"new_today": [], "carryover": []},
        "hd": {"new_today": [], "carryover": []},
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        svc = str(row.get("service_type") or "WF").strip().upper()
        nc = str(row.get("new_or_carryover") or "").strip().lower()
        is_carry = nc in ("carryover", "opening_carryover", "carried_in")
        bucket = "carryover" if is_carry else "new_today"
        membership_by_seg["all"][bucket].append(bid)
        if svc == "HD":
            membership_by_seg["hd"][bucket].append(bid)
        else:
            membership_by_seg["wf"][bucket].append(bid)

    summary = dict(base)
    segments = dict(summary.get("segments") or {})
    for seg_name, lists in membership_by_seg.items():
        seg_out = dict(segments.get(seg_name) or {})
        bag_ids = dict(seg_out.get("bag_ids") or {})
        bag_ids["new_today"] = sorted(set(lists["new_today"]))
        bag_ids["carryover"] = sorted(set(lists["carryover"]))
        seg_out["bag_ids"] = bag_ids
        # Drop frozen totals so status sync recomputes from day-bag buckets
        # while preserving the membership ID lists we just rebuilt.
        for k in ("total_workload", "active_workload"):
            seg_out.pop(k, None)
        segments[seg_name] = seg_out
    summary["segments"] = segments
    synced = _sync_day_header_from_persisted_bags(
        cursor,
        org,
        day,
        summary=summary,
        workload=day_rec.get("workload_meta") or {},
        next_status=STATUS_CLOSED,
        opened_at=day_rec.get("opened_at") or _utcnow(),
        now=_utcnow(),
    )
    headline = dict(synced.get("headline") or {})
    weights = load_wf_day_weight_totals(cursor, org, day)
    headline = merge_weights_into_headline(
        headline,
        weights,
        repair_tag="restore_closed_day_from_day_bags",
    )
    headline["snapshot_available"] = True
    headline["selected_date_et"] = day.isoformat()
    headline["shift_day_status"] = STATUS_CLOSED
    if not headline_has_wf_workload_segments(headline):
        return {
            "ok": False,
            "reason": "headline_still_missing_workload_after_sync",
            "buckets": synced.get("status_buckets"),
        }

    wm = get_watermarks(cursor, org) or {}
    gen = int(lease_generation if lease_generation is not None else 0)
    if gen <= 0:
        return {"ok": False, "reason": "lease_generation_required"}
    cid = int(cycle_id or 0)
    if cid <= 0:
        return {"ok": False, "reason": "cycle_id_required"}
    ver = begin_snapshot_build(
        cursor,
        organization_id=org,
        shift_date_et=day,
        cycle_id=cid,
        lease_generation=gen,
    )
    publish_snapshot(
        cursor,
        organization_id=org,
        shift_date_et=day,
        version=ver,
        lease_generation=gen,
        lane=lane,
        headline=headline,
        workload_meta={
            "mode": "restore_closed_day_from_day_bags",
            "source": "rinse_shift_monitor_day_bags",
            "never_used_live_ytp": True,
            "status_buckets": synced.get("status_buckets"),
            "watermarks_note": {
                "last_fast_result": wm.get("last_fast_result"),
            },
        },
    )
    wf = ((headline.get("segments") or {}).get("wf") or {})
    return {
        "ok": True,
        "published": True,
        "snapshot_version": ver,
        "cycle_id": cid,
        "shift_date_et": day.isoformat(),
        "wf": {
            "total_workload": wf.get("total_workload"),
            "completed": wf.get("completed"),
            "pending": wf.get("pending"),
            "carried_forward": wf.get("carried_forward"),
            "review": (wf.get("exceptions") or {}).get("review_required"),
            "new_today": wf.get("new_today"),
            "carryover": wf.get("carryover"),
        },
        "weights": weights,
        "status_buckets": synced.get("status_buckets"),
    }
