"""OI-scoped folder/fold attribution for WF Folder Performance (read-path only).

Performance must not use ``resolve_current_cycle`` to recover folder employee
after a fold has already occurred (later Dirty STV re-anchors that resolver).

Qualifying Folder Performance membership requires same-lifecycle
``garments-reviewed`` evidence. Lifecycle strong completion without fold
(e.g. processed-by-vendor alone) is excluded from Folder Performance — it
does not mutate OI / CW completion.

Does not write day-bag or OI rows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_employee_workload_productivity import UNASSIGNED_EMPLOYEE
from backend.rinse_scan_purpose import normalize_scan_purpose
from backend.ta_helpers import table_exists

EXCEPTION_NEEDS_ATTRIBUTION = "needs_attribution"
EXCEPTION_OUTSIDE_FOLDER_SESSION = "outside_folder_session"


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")[:19])
    except ValueError:
        return None


def _norm_purpose(raw: Any) -> str:
    p = normalize_scan_purpose(raw)
    if p.startswith("sent-to-vendor"):
        return "sent-to-vendor"
    return p


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if not ev:
        return None
    name = str(ev.get("user_name") or ev.get("user") or "").strip()
    return name or None


def is_provable_folder_employee(name: Any) -> bool:
    s = str(name or "").strip()
    if not s:
        return False
    if s.casefold() == UNASSIGNED_EMPLOYEE.casefold():
        return False
    if s.casefold() in {"unassigned", "unknown", "none", "null"}:
        return False
    return True


def extract_oi_window_folder_fold_evidence(
    events: Sequence[Mapping[str, Any]],
    *,
    cycle_anchor_at: datetime,
    lifecycle_end_exclusive: datetime | None = None,
) -> dict[str, Any] | None:
    """Return fold evidence inside one OI window, or None if no garments-reviewed.

    Fold complete prefers post-GR weight-entry, else post-GR processed-by-vendor
    when it is the established fold-signoff chain companion. Employee prefers
    the fold-complete operator, falling back to garments-reviewed user.
    """
    if not isinstance(cycle_anchor_at, datetime):
        return None
    scoped: list[dict[str, Any]] = []
    for ev in events or []:
        ts = ev.get("scanned_at_parsed")
        if not isinstance(ts, datetime):
            continue
        if ts < cycle_anchor_at:
            continue
        if lifecycle_end_exclusive is not None and ts >= lifecycle_end_exclusive:
            continue
        scoped.append(dict(ev))
    if not scoped:
        return None

    gr_events = [
        e
        for e in scoped
        if _norm_purpose(e.get("purpose")) == "garments-reviewed"
        and isinstance(e.get("scanned_at_parsed"), datetime)
    ]
    if not gr_events:
        return None

    gr = gr_events[-1]
    gr_at = gr["scanned_at_parsed"]
    assert isinstance(gr_at, datetime)

    weight_after: dict[str, Any] | None = None
    pbv_after: dict[str, Any] | None = None
    for e in scoped:
        ts = e.get("scanned_at_parsed")
        if not isinstance(ts, datetime) or ts < gr_at:
            continue
        purpose = _norm_purpose(e.get("purpose"))
        if purpose == "weight-entry" and weight_after is None:
            weight_after = e
        if purpose == "processed-by-vendor" and pbv_after is None:
            pbv_after = e

    fold_ev = weight_after or pbv_after or gr
    fold_at = fold_ev.get("scanned_at_parsed")
    if not isinstance(fold_at, datetime):
        return None
    fold_user = _operator(fold_ev) or _operator(gr)
    if not is_provable_folder_employee(fold_user):
        # Still qualifying fold evidence for membership; employee may be missing.
        fold_user = _operator(gr) if is_provable_folder_employee(_operator(gr)) else None

    return {
        "qualifying_fold": True,
        "garments_reviewed_at": gr_at,
        "garments_reviewed_user": _operator(gr),
        "fold_complete_at": fold_at,
        "fold_employee": fold_user,
        "fold_complete_purpose": _norm_purpose(fold_ev.get("purpose")),
        "order_instance_id": None,
        "cycle_anchor_at": cycle_anchor_at,
        "lifecycle_end_exclusive": lifecycle_end_exclusive,
    }


def resolve_day_bag_folder_oi(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    completion_hint: datetime | None = None,
) -> dict[str, Any] | None:
    """Pick the WF OI whose lifecycle owns this day's folder completion.

    Prefer OI whose ``completed_at`` matches the day-bag completion hint.
    Never uses bag-lifetime latest user; OI identity only.
    """
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        ensure_rinse_order_instances_table,
    )

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    ensure_rinse_order_instances_table(cursor)
    if not table_exists(cursor, ORDER_INSTANCES_TABLE):
        return None
    cursor.execute(
        f"""
        SELECT order_instance_id, bag_id, cycle_anchor_at, completed_at, completion_source
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND bag_id = %s
          AND service_type = 'WF'
        ORDER BY order_instance_id ASC
        """,
        (int(organization_id), bid),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    if not rows:
        return None

    hint = completion_hint
    if hint is not None:
        for row in rows:
            comp = row.get("completed_at")
            if (
                isinstance(comp, datetime)
                and abs((comp - hint).total_seconds()) <= 60
            ):
                return row

    for row in reversed(rows):
        comp = row.get("completed_at")
        if isinstance(comp, datetime) and comp.date() == selected_date_et:
            return row

    for row in reversed(rows):
        anchor = row.get("cycle_anchor_at")
        if isinstance(anchor, datetime) and anchor.date() == selected_date_et:
            return row
    return None


def resolve_folder_fold_attribution_for_bag(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    completion_hint: datetime | None = None,
    timeline: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """OI-scoped qualifying folder fold evidence for one bag on selected date."""
    from backend.rinse_wf_current_workload import (
        _load_bag_timeline,
        _next_oi_cycle_anchor,
    )

    oi = resolve_day_bag_folder_oi(
        cursor,
        organization_id,
        bag_id=bag_id,
        selected_date_et=selected_date_et,
        completion_hint=completion_hint,
    )
    if not oi:
        return None
    anchor = oi.get("cycle_anchor_at")
    if not isinstance(anchor, datetime):
        return None
    end = _next_oi_cycle_anchor(cursor, organization_id, bag_id, anchor)
    tl = list(timeline) if timeline is not None else _load_bag_timeline(
        cursor, organization_id, bag_id
    )
    evidence = extract_oi_window_folder_fold_evidence(
        tl,
        cycle_anchor_at=anchor,
        lifecycle_end_exclusive=end,
    )
    if not evidence:
        return None
    evidence["order_instance_id"] = oi.get("order_instance_id")
    evidence["oi_completed_at"] = oi.get("completed_at")
    evidence["oi_completion_source"] = oi.get("completion_source")
    return evidence


def enrich_folder_performance_bags_with_oi_fold_attribution(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bags: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Filter to qualifying folds and fill missing employee from OI-window evidence.

    Returns only bags that have garments-reviewed in the owning OI window.
    Does not rewrite persisted day-bag / OI columns.
    """
    out: list[dict[str, Any]] = []
    for raw in bags or []:
        bag = dict(raw)
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        hint = _parse_dt(
            bag.get("completion_time")
            or bag.get("completion_timestamp")
            or bag.get("productivity_completed_at")
            or bag.get("canonical_completion_timestamp")
        )
        evidence = resolve_folder_fold_attribution_for_bag(
            cursor,
            organization_id,
            bag_id=bid,
            selected_date_et=selected_date_et,
            completion_hint=hint,
        )
        if not evidence:
            # Non-fold lifecycle completion (e.g. PBV-only) — exclude from Folder Perf.
            continue

        bag["folder_fold_qualified"] = True
        bag["order_instance_id"] = evidence.get("order_instance_id")
        bag["garments_reviewed_at"] = (
            evidence["garments_reviewed_at"].isoformat(sep=" ")
            if isinstance(evidence.get("garments_reviewed_at"), datetime)
            else None
        )
        fold_at = evidence.get("fold_complete_at")
        if isinstance(fold_at, datetime):
            fold_iso = fold_at.isoformat(sep=" ")
            bag["fold_complete_at"] = fold_iso
            # Session match / Fold complete display use the fold-signoff chain.
            # For ordinary GR→weight-entry this equals prior completion_at.
            bag["completion_time"] = fold_iso
            bag["completion_timestamp"] = fold_iso
            bag["completion_time_et"] = fold_iso

        fold_emp = evidence.get("fold_employee")
        existing = (
            bag.get("effective_employee")
            or bag.get("credited_employee")
            or bag.get("employee")
        )
        if is_provable_folder_employee(fold_emp) and not is_provable_folder_employee(
            existing
        ):
            bag["credited_employee"] = fold_emp
            bag["employee"] = fold_emp
            bag["completed_by_employee"] = fold_emp
            bag["folder_employee_source"] = "oi_window_fold_evidence"
        elif is_provable_folder_employee(existing):
            bag["folder_employee_source"] = "day_bag_or_override"
        else:
            bag["folder_employee_source"] = "missing"

        bag["folder_fold_complete_purpose"] = evidence.get("fold_complete_purpose")
        out.append(bag)
    return out
