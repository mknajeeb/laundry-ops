"""Fast-lane incremental Management projection + publish.

Partial portal inspection must never rebuild the whole day or infer absences.
Model: durable prior-day carryover + Dirty-eligible additive admits + reproject
→ atomic publish.

A 2-page / 50-row fast scrape is freshness observation only. Portal presence
alone never admits membership.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_freshness_publish import (
    begin_snapshot_build,
    mark_snapshot_failed,
    publish_snapshot,
)
from backend.rinse_freshness_store import LaneFencedError, assert_lane_writable, upsert_watermarks
from backend.rinse_workload_membership_eligibility import (
    headline_identity_ok,
    resolve_day_operational_membership,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm_bags(raw: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for b in raw or []:
        bid = normalize_bag_id(b)
        if bid and bid not in seen:
            seen.add(bid)
            out.append(bid)
    return out


def incremental_project_and_publish(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    affected_bag_ids: Sequence[str] | None,
    cycle_id: int,
    lease_generation: int,
    lane: str = "fast",
    batch_id: int | None = None,
    source_inspected_complete: bool = False,
    workload_meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge incremental bag changes into last-good day and publish.

    - Never deletes day bags for bags not seen in a partial scrape.
    - Seeds carryover from prior-day unfinished membership (no midnight scrape).
    - Only admits ``affected_bag_ids`` that independently satisfy Dirty eligibility.
    - Reprojects completions from chronology for the resulting membership.
    - Publishes an atomic Management snapshot on success (identity required).
    """
    from backend.rinse_veewash_shift_day import (
        STATUS_CLOSED,
        STATUS_NOT_STARTED,
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
    affected = _norm_bags(affected_bag_ids)
    out: dict[str, Any] = {
        "ok": False,
        "published": False,
        "mode": "incremental_fast",
        "source_inspected_complete": bool(source_inspected_complete),
        "affected_bag_count": len(affected),
        "absence_inference": False,
        "portal_presence_admits": False,
    }

    day_rec = get_day_record(cursor, org, day)
    if day_rec and str(day_rec.get("status") or "") == STATUS_CLOSED:
        out.update({"ok": True, "skipped": True, "reason": "day_closed"})
        return out

    existing_bags = load_day_bags(cursor, org, day) if day_rec else []
    existing_ops = [
        normalize_bag_id(b.get("bag_id"))
        for b in (existing_bags or [])
        if normalize_bag_id(b.get("bag_id"))
        and str(b.get("effective_status") or "").strip().lower()
        != "disappeared_prior_open_exception"
    ]

    resolved = resolve_day_operational_membership(
        cursor,
        org,
        day,
        extra_candidates=affected,
        existing_member_ids=existing_ops,
        service_type="WF",
        include_active_presence=False,
    )
    # HD members already on the day stay (WF Dirty rule does not strip HD).
    hd_existing = [
        normalize_bag_id(b.get("bag_id"))
        for b in (existing_bags or [])
        if normalize_bag_id(b.get("bag_id"))
        and str(b.get("service_type") or "").strip().upper() == "HD"
        and str(b.get("effective_status") or "").strip().lower()
        != "disappeared_prior_open_exception"
    ]
    # Portal-affected HD bags still need Dirty eligibility (same rack entry rule).
    hd_resolved = resolve_day_operational_membership(
        cursor,
        org,
        day,
        extra_candidates=affected,
        existing_member_ids=hd_existing,
        service_type="HD",
        include_active_presence=False,
    )

    member_ids = sorted(
        set(resolved.get("member_ids") or [])
        | set(hd_resolved.get("member_ids") or [])
    )
    new_admits = sorted(
        set(member_ids) - {normalize_bag_id(b) for b in existing_ops} - set(hd_existing)
    )
    out["membership_before"] = len(set(existing_ops) | set(hd_existing))
    out["new_admits"] = len(new_admits)
    out["membership_after"] = len(member_ids)
    out["carryover_bag_ids"] = list(resolved.get("carryover_bag_ids") or [])
    out["excluded_no_dirty"] = len(resolved.get("excluded_no_dirty") or [])
    out["excluded_completed_before"] = len(
        resolved.get("excluded_completed_before") or []
    )
    out["excluded_prior_disappearance"] = len(
        resolved.get("excluded_prior_disappearance") or []
    )
    out["membership_policy"] = "dirty_entry_v1"

    if not member_ids:
        out.update({"ok": False, "reason": "no_membership_to_project"})
        return out

    activation = get_step1_activation_date(cursor, org)
    # Frozen ids + membership meta so opening_carryover labels stick.
    membership_meta = {
        "ok": True,
        "membership_policy": "dirty_entry_v1",
        "opening_carryover_bag_ids": list(resolved.get("carryover_bag_ids") or []),
        "opening_new_bag_ids": [
            b
            for b in (resolved.get("new_or_other_bag_ids") or [])
            if b not in set(resolved.get("carryover_bag_ids") or [])
        ],
        "membership": {
            bid: {
                "bag_id": bid,
                "inclusion_source": (
                    "OPENING_CARRYOVER"
                    if bid in set(resolved.get("carryover_bag_ids") or [])
                    else "OPENING_NEW"
                ),
            }
            for bid in member_ids
        },
    }
    wl = build_veewash_daily_workload_from_membership(
        cursor,
        org,
        selected_date_et=day,
        frozen_member_ids=member_ids,
        membership=membership_meta,
    )
    summary = build_step1_headline_summary(
        wl,
        selected_date_et=day,
        activation_date=activation or day,
    )
    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")
    summary = dict(summary or {})
    summary["membership"] = membership_meta

    # Incomplete inspection: never allow absence / disappearance conclusions.
    chronology_complete = bool(source_inspected_complete)
    day_after, summary_after, _spec_ok = _persist_snapshot_then_attach_specialty(
        cursor,
        org,
        day,
        wl=wl,
        summary=summary,
        day=day_rec,
        chronology_complete=chronology_complete,
        projection_deferred_bag_ids=[],
    )
    # Ensure status leaves NOT_STARTED once we have membership.
    if day_after and str(day_after.get("status") or "") == STATUS_NOT_STARTED:
        status = derive_shift_day_status(
            summary_after,
            current_status=STATUS_OPEN,
            membership=summary_after.get("membership")
            if isinstance(summary_after.get("membership"), dict)
            else None,
        )
        now = _utcnow()
        _sync_day_header_from_persisted_bags(
            cursor,
            org,
            day,
            summary=summary_after,
            workload=wl,
            next_status=status or STATUS_OPEN,
            opened_at=day_after.get("opened_at") or now,
            now=now,
        )
        day_after = get_day_record(cursor, org, day) or day_after

    # Publish the day-bag–synced headline (identity: workload = completed +
    # pending + review), not the pre-persist classifier shell.
    if isinstance((day_after or {}).get("headline"), dict):
        summary_after = dict(day_after["headline"])

    upsert_watermarks(cursor, org, chronology_processed_through=_utcnow())

    headline = dict(summary_after or {})
    if not headline and isinstance((day_after or {}).get("headline"), dict):
        headline = dict(day_after["headline"])
    if not headline:
        out.update({"ok": False, "reason": "no_headline_after_incremental"})
        return out

    # Strip unavailable shells — this is a real publishable projection.
    headline.pop("data_unavailable", None)
    headline.pop("snapshot_missing", None)
    headline["snapshot_available"] = True
    headline["selected_date_et"] = day.isoformat()
    headline["freshness_projection_mode"] = "incremental_fast"
    headline["membership_policy"] = "dirty_entry_v1"

    ok_id, id_msg = headline_identity_ok(headline)
    if not ok_id:
        out.update(
            {
                "ok": False,
                "published": False,
                "reason": f"headline_identity_failed: {id_msg}",
            }
        )
        return out

    ver = begin_snapshot_build(
        cursor,
        organization_id=org,
        shift_date_et=day,
        cycle_id=int(cycle_id),
        lease_generation=int(lease_generation),
    )
    out["snapshot_version"] = ver
    try:
        assert_lane_writable(cursor, org, lane, int(lease_generation))
        publish_snapshot(
            cursor,
            organization_id=org,
            shift_date_et=day,
            version=ver,
            lease_generation=int(lease_generation),
            lane=lane,
            headline=headline,
            workload_meta={
                "cycle_id": int(cycle_id),
                "batch_id": batch_id,
                "mode": "incremental_fast",
                "source_inspected_complete": bool(source_inspected_complete),
                "affected_bag_count": len(affected),
                "new_admits": len(new_admits),
                "membership_after": len(member_ids),
                "absence_inference": False,
                "portal_presence_admits": False,
                "membership_policy": "dirty_entry_v1",
                "carryover_count": len(resolved.get("carryover_bag_ids") or []),
                "excluded_no_dirty": len(resolved.get("excluded_no_dirty") or []),
                "excluded_completed_before": len(
                    resolved.get("excluded_completed_before") or []
                ),
                "excluded_prior_disappearance": len(
                    resolved.get("excluded_prior_disappearance") or []
                ),
                **(workload_meta_extra or {}),
            },
        )
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_days
            SET last_sync_at = UTC_TIMESTAMP(6), updated_at = UTC_TIMESTAMP(6)
            WHERE organization_id = %s AND shift_date_et = %s
            """,
            (org, day),
        )
        upsert_watermarks(
            cursor,
            org,
            management_published_through=_utcnow(),
            last_fast_result="SUCCESS",
            last_fast_cycle_id=int(cycle_id),
        )
        out.update({"ok": True, "published": True, "headline_counts": {
            "active_workload": headline.get("active_workload") or headline.get("total_workload"),
            "completed": headline.get("completed"),
            "pending": headline.get("pending"),
            "review": (headline.get("exceptions") or {}).get("review_required")
            if isinstance(headline.get("exceptions"), dict)
            else headline.get("review_required_count"),
        }})
        return out
    except LaneFencedError as exc:
        mark_snapshot_failed(cursor, organization_id=org, shift_date_et=day, version=ver)
        out.update({"ok": False, "published": False, "reason": str(exc), "fenced": True})
        return out
    except Exception as exc:
        mark_snapshot_failed(cursor, organization_id=org, shift_date_et=day, version=ver)
        out.update({"ok": False, "published": False, "reason": f"publish_failed: {exc}"})
        return out
