"""Rebuild one ET day's Management membership from Dirty-entry business rule."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_workload_membership_eligibility import (
    headline_identity_ok,
    load_dirty_entry_dates,
    resolve_day_operational_membership,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rebuild_day_membership_from_dirty_rule(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    publish: bool = True,
    lane: str = "fast",
    lease_generation: int | None = None,
    cycle_id: int | None = None,
) -> dict[str, Any]:
    """Recompute day_bags + headline (+ optional publish) from Dirty eligibility.

    Discovers candidates from:
      - all Dirty entries with entry_date <= selected_date
      - prior-day unfinished durable members
      - current day operational members (excluding prior-open exceptions)
    """
    from backend.rinse_freshness_publish import begin_snapshot_build, publish_snapshot
    from backend.rinse_freshness_store import get_watermarks
    from backend.rinse_veewash_shift_day import (
        STATUS_OPEN,
        _persist_snapshot_then_attach_specialty,
        _sync_day_header_from_persisted_bags,
        build_step1_headline_summary,
        derive_shift_day_status,
        get_day_record,
        get_step1_activation_date,
        load_day_bags,
    )
    from backend.rinse_veewash_workload import build_veewash_daily_workload_from_membership

    org = int(organization_id)
    day = shift_date_et
    dirty = load_dirty_entry_dates(cursor, org)
    # New Dirty entrants on this ET day only — do not admit every historical Dirty.
    dirty_today = [bid for bid, ed in dirty.items() if ed == day]
    existing = load_day_bags(cursor, org, day) or []
    existing_ops = [
        normalize_bag_id(b.get("bag_id"))
        for b in existing
        if normalize_bag_id(b.get("bag_id"))
        and str(b.get("effective_status") or "").strip().lower()
        != "disappeared_prior_open_exception"
    ]
    existing_wf = [
        normalize_bag_id(b.get("bag_id"))
        for b in existing
        if normalize_bag_id(b.get("bag_id"))
        and str(b.get("service_type") or "WF").strip().upper() != "HD"
        and str(b.get("effective_status") or "").strip().lower()
        != "disappeared_prior_open_exception"
    ]
    existing_hd = [
        normalize_bag_id(b.get("bag_id"))
        for b in existing
        if normalize_bag_id(b.get("bag_id"))
        and str(b.get("service_type") or "").strip().upper() == "HD"
        and str(b.get("effective_status") or "").strip().lower()
        != "disappeared_prior_open_exception"
    ]

    wf = resolve_day_operational_membership(
        cursor,
        org,
        day,
        extra_candidates=dirty_today,
        existing_member_ids=existing_wf,
        service_type="WF",
        include_active_presence=True,
    )
    hd = resolve_day_operational_membership(
        cursor,
        org,
        day,
        extra_candidates=dirty_today,
        existing_member_ids=existing_hd,
        service_type="HD",
        include_active_presence=False,
    )
    member_ids = sorted(set(wf["member_ids"]) | set(hd["member_ids"]))
    membership_meta = {
        "ok": True,
        "membership_policy": "dirty_entry_v1",
        "opening_carryover_bag_ids": list(wf.get("carryover_bag_ids") or []),
        "opening_new_bag_ids": list(wf.get("new_or_other_bag_ids") or []),
        "membership": {
            bid: {
                "bag_id": bid,
                "inclusion_source": (
                    "OPENING_CARRYOVER"
                    if bid in set(wf.get("carryover_bag_ids") or [])
                    else "OPENING_NEW"
                ),
                "service_type_portal": (
                    "HD" if bid in set(hd.get("member_ids") or []) else "WF"
                ),
            }
            for bid in member_ids
        },
    }

    activation = get_step1_activation_date(cursor, org)
    wl = build_veewash_daily_workload_from_membership(
        cursor,
        org,
        selected_date_et=day,
        frozen_member_ids=member_ids,
        membership=membership_meta,
    )
    summary = build_step1_headline_summary(
        wl, selected_date_et=day, activation_date=activation or day
    )
    summary = dict(summary or {})
    summary["membership"] = membership_meta
    summary["membership_policy"] = "dirty_entry_v1"

    day_rec = get_day_record(cursor, org, day)
    day_after, summary_after, _ = _persist_snapshot_then_attach_specialty(
        cursor,
        org,
        day,
        wl=wl,
        summary=summary,
        day=day_rec,
        chronology_complete=True,
        projection_deferred_bag_ids=[],
    )
    status = derive_shift_day_status(
        summary_after,
        current_status=STATUS_OPEN,
        membership=membership_meta,
    )
    now = _utcnow()
    _sync_day_header_from_persisted_bags(
        cursor,
        org,
        day,
        summary=summary_after,
        workload=wl,
        next_status=status or STATUS_OPEN,
        opened_at=(day_after or {}).get("opened_at") or now,
        now=now,
    )
    day_after = get_day_record(cursor, org, day) or day_after
    headline = dict((day_after or {}).get("headline") or summary_after or {})
    ok_id, id_msg = headline_identity_ok(headline)
    out: dict[str, Any] = {
        "ok": ok_id,
        "identity": id_msg,
        "member_count": len(member_ids),
        "wf": {
            "members": len(wf.get("member_ids") or []),
            "carryover": len(wf.get("carryover_bag_ids") or []),
            "new_or_other": len(wf.get("new_or_other_bag_ids") or []),
            "excluded_completed_before": len(wf.get("excluded_completed_before") or []),
            "excluded_prior_disappearance": len(
                wf.get("excluded_prior_disappearance") or []
            ),
            "carryover_bag_ids": list(wf.get("carryover_bag_ids") or []),
            "new_or_other_bag_ids": list(wf.get("new_or_other_bag_ids") or []),
            "excluded_completed_before_bag_ids": list(
                wf.get("excluded_completed_before") or []
            ),
            "excluded_prior_disappearance_bag_ids": list(
                wf.get("excluded_prior_disappearance") or []
            ),
        },
        "headline_counts": {},
    }
    wf_seg = ((headline.get("segments") or {}).get("wf") or {})
    out["headline_counts"] = {
        "total_workload": wf_seg.get("total_workload"),
        "completed": wf_seg.get("completed"),
        "pending": wf_seg.get("pending"),
        "review": (wf_seg.get("exceptions") or {}).get("review_required"),
    }
    if not ok_id:
        out["published"] = False
        out["reason"] = f"headline_identity_failed: {id_msg}"
        return out

    if not publish:
        out["published"] = False
        return out

    wm = get_watermarks(cursor, org) or {}
    # Prefer live lease generation when available.
    cursor.execute(
        """
        SELECT generation FROM rinse_freshness_lane_lease
        WHERE organization_id=%s AND lane=%s LIMIT 1
        """,
        (org, lane),
    )
    row = cursor.fetchone() or {}
    gen = int(
        lease_generation
        if lease_generation is not None
        else (row.get("generation") if isinstance(row, dict) else 0) or 0
    )
    cid = int(cycle_id or wm.get("last_fast_cycle_id") or 0) + 1
    ver = begin_snapshot_build(
        cursor,
        organization_id=org,
        shift_date_et=day,
        cycle_id=cid,
        lease_generation=gen,
    )
    headline["snapshot_available"] = True
    headline["selected_date_et"] = day.isoformat()
    headline["membership_policy"] = "dirty_entry_v1"
    headline["freshness_projection_mode"] = "dirty_membership_repair"
    publish_snapshot(
        cursor,
        organization_id=org,
        shift_date_et=day,
        version=ver,
        lease_generation=gen,
        lane=lane,
        headline=headline,
        workload_meta={
            "mode": "dirty_membership_repair",
            "membership_policy": "dirty_entry_v1",
            "cycle_id": cid,
            "membership_after": len(member_ids),
            "carryover_count": len(wf.get("carryover_bag_ids") or []),
            "absence_inference": False,
            "portal_presence_admits": False,
            "repair": "dirty_entry_membership_v1",
        },
    )
    out["published"] = True
    out["snapshot_version"] = ver
    out["cycle_id"] = cid
    return out
