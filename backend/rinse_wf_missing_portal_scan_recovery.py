"""Recover Missing From Portal bags using authoritative scan completion only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id, rack_contains_clean
from backend.rinse_bag_gaming_performance import gaming_events_from_records
from backend.rinse_bag_stage_bounds import event_ts as _event_ts, ts_valid as _ts_valid
from backend.rinse_shift_operational_exceptions import find_strong_completion_evidence

# Never auto-complete from disappearance / portal-absence inference alone.
_DISAPPEARANCE_INFERENCE_MARKERS = (
    "portal_departure",
    "portal_absence",
    "absence_completion",
    "disappeared",
    "disappearance",
)


def scan_evidence_authorizes_terminal_completion(comp: Mapping[str, Any] | None) -> bool:
    """True when completion dict comes from scan/cycle evidence, not disappearance alone."""
    if not comp or comp.get("completion_at") is None:
        return False
    src = str(comp.get("completion_source") or "").strip().lower()
    if not src:
        return False
    return not any(marker in src for marker in _DISAPPEARANCE_INFERENCE_MARKERS)


def _completion_on_selected_day(completion_at: datetime, selected_date_et: date) -> bool:
    from backend.business_time import system_datetime_to_et

    if isinstance(completion_at, datetime):
        et = system_datetime_to_et(completion_at)
        return bool(et and et.date() == selected_date_et)
    return False


def _load_scan_timeline(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[dict[str, Any]]:
    from backend.ta_helpers import table_exists

    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT bag_id, rack, purpose, scanned_at_parsed, user_name, weight_lbs,
               source_filename, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id = %s
          AND scanned_at_parsed IS NOT NULL
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), bid),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _resolve_authoritative_scan_completion(
    cursor,
    organization_id: int,
    bag_id: str,
    selected_date_et: date,
    *,
    canonical_comp: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve terminal completion from canonical resolver or direct scan timeline."""
    if scan_evidence_authorizes_terminal_completion(canonical_comp):
        return dict(canonical_comp)

    timeline = gaming_events_from_records(
        _load_scan_timeline(cursor, organization_id, bag_id)
    )
    if not timeline:
        return None

    for ev in timeline:
        if rack_contains_clean(ev.get("rack")):
            ts = _event_ts(ev)
            if _ts_valid(ts) and _completion_on_selected_day(ts, selected_date_et):
                user = str(ev.get("user") or ev.get("user_name") or "").strip() or None
                return {
                    "completion_at": ts,
                    "completed_by": user,
                    "completion_source": "clean_rack_scan",
                }

    evidence = find_strong_completion_evidence(timeline)
    if evidence is None:
        return None
    ev, ts, kind = evidence
    if not _ts_valid(ts) or not _completion_on_selected_day(ts, selected_date_et):
        return None
    user = str(ev.get("user") or ev.get("user_name") or "").strip() or None
    return {
        "completion_at": ts,
        "completed_by": user,
        "completion_source": f"strong_scan_evidence:{kind}",
    }


def recover_missing_portal_bags_from_scan_evidence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bag_ids: Sequence[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Complete canonical cycles for Missing From Portal bags with scan terminal evidence."""
    from backend.management_rinse_wf_review import (
        CATEGORY_MISSING_PORTAL,
        compute_canonical_wf_review_membership,
    )
    from backend.rinse_veewash_workload import load_canonical_completions_v2
    from backend.rinse_wf_service_cycle import (
        apply_manager_review_resolution_to_canonical_cycle,
        is_wf_canonical_lifecycle_enabled,
    )

    org = int(organization_id)
    if not is_wf_canonical_lifecycle_enabled(cursor, org):
        return {
            "ok": False,
            "reason": "canonical_lifecycle_disabled",
            "date_et": selected_date_et.isoformat(),
        }

    membership = compute_canonical_wf_review_membership(
        cursor, org, selected_date_et
    )
    missing_ids = sorted(
        {
            normalize_bag_id(b)
            for b in (bag_ids or membership.get(CATEGORY_MISSING_PORTAL) or [])
            if normalize_bag_id(b)
        }
    )
    if not missing_ids:
        return {
            "ok": True,
            "date_et": selected_date_et.isoformat(),
            "missing_before": 0,
            "auto_recovered": [],
            "manual_required": [],
            "auto_recovered_count": 0,
            "manual_required_count": 0,
        }

    svc_map = {bid: "WF" for bid in missing_ids}
    comps = load_canonical_completions_v2(
        cursor,
        org,
        missing_ids,
        selected_date_et=selected_date_et,
        service_type_by_bag=svc_map,
    )

    auto_recovered: list[str] = []
    manual_required: list[str] = []
    errors: dict[str, str] = {}

    for bid in missing_ids:
        comp = _resolve_authoritative_scan_completion(
            cursor,
            org,
            bid,
            selected_date_et,
            canonical_comp=comps.get(bid),
        )
        if not comp:
            manual_required.append(bid)
            continue
        if dry_run:
            auto_recovered.append(bid)
            continue
        try:
            row = apply_manager_review_resolution_to_canonical_cycle(
                cursor,
                org,
                bid,
                completed_at=comp["completion_at"],
                completion_source=str(
                    comp.get("completion_source") or "scan_evidence_recovery"
                ),
                resolved_by="scan_evidence_recovery",
                resolution_note="Auto-completed from authoritative scan terminal evidence",
            )
            if row:
                auto_recovered.append(bid)
            else:
                manual_required.append(bid)
                errors[bid] = "no_active_cycle"
        except Exception as exc:
            manual_required.append(bid)
            errors[bid] = str(exc)

    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "missing_before": len(missing_ids),
        "auto_recovered": auto_recovered,
        "manual_required": manual_required,
        "auto_recovered_count": len(auto_recovered),
        "manual_required_count": len(manual_required),
        "errors": errors,
        "dry_run": dry_run,
    }
