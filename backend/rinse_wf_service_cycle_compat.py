"""Compatibility projection: canonical WF workload → legacy day_bags / Management.

Membership authority is ``get_canonical_wf_workload`` (not service cycles).
Service-cycle rows remain audit/history only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_veewash_shift_day import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    STATUS_OPEN,
    ensure_shift_monitor_day_tables,
    get_day_record,
    get_step1_activation_date,
    load_day_bags,
    persist_day_snapshot,
)
from backend.rinse_veewash_workload import build_step1_headline_summary
from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_REVIEW,
    ensure_wf_service_cycles_table,
    reporting_counts_for_date,
)

OUTCOME_CARRYOVER_QUERY = "opening_backlog_query_only"


def _parse_cycle_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "")[:19])
    except (TypeError, ValueError):
        return None


def _cycle_anchor_or_admit_on_date(
    *,
    admitted_at: datetime | None,
    cycle_anchor_at: datetime | None,
    shift_date_et: date,
) -> bool:
    day_start = naive_et_day_start(shift_date_et)
    day_end = day_start + timedelta(days=1)
    for dt in (admitted_at, cycle_anchor_at):
        if isinstance(dt, datetime) and day_start <= dt < day_end:
            return True
    return False


def _prior_day_terminal_completed_wf_bag_ids(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> set[str]:
    """WF bags terminally completed on the ET day immediately before shift_date_et."""
    from backend.business_time import system_datetime_to_et

    prior = shift_date_et - timedelta(days=1)
    out: set[str] = set()
    for row in load_day_bags(cursor, organization_id, prior) or []:
        if str(row.get("service_type") or "WF").upper() != "WF":
            continue
        if str(row.get("effective_status") or "").lower() != OUTCOME_COMPLETED:
            continue
        comp = row.get("canonical_completion_timestamp") or row.get("completion_at")
        comp_et = None
        if isinstance(comp, datetime):
            et = system_datetime_to_et(comp)
            comp_et = et.date() if et else None
        if comp_et == prior:
            bid = normalize_bag_id(row.get("bag_id"))
            if bid:
                out.add(bid)
    return out


def wf_terminal_ineligible_bag_ids(
    cursor,
    organization_id: int,
    shift_date_et: date,
    candidate_bag_ids,
    *,
    service_type_by_bag: Mapping[str, str] | None = None,
) -> set[str]:
    """Bag IDs with authoritative completion date strictly before shift_date_et.

    These bag IDs are ineligible for the selected day's WF workload when their
    *current* order occurrence completed before D. A later authoritative
    order_instance covering D (same physical bag_id) is not ineligible.

    Uses the same terminal authority as ``get_canonical_wf_workload``.
    """
    from backend.rinse_wf_canonical_workload import _terminal_before_date

    del service_type_by_bag  # WF persist guards use WF order instances
    ids = sorted(
        {
            normalize_bag_id(b)
            for b in (candidate_bag_ids or [])
            if normalize_bag_id(b)
        }
    )
    if not ids:
        return set()
    return _terminal_before_date(
        cursor, int(organization_id), shift_date_et, ids
    )


def final_wf_day_membership_bag_ids(
    cursor,
    organization_id: int,
    shift_date_et: date,
    candidate_bag_ids,
    *,
    service_type_by_bag: Mapping[str, str] | None = None,
) -> list[str]:
    """Single canonical WF membership admission rule for every writer.

    final = candidate bag IDs − { authoritative_completion_date_et < shift_date_et }
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in candidate_bag_ids or []:
        bid = normalize_bag_id(raw)
        if bid and bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    if not ordered:
        return []
    ineligible = wf_terminal_ineligible_bag_ids(
        cursor,
        organization_id,
        shift_date_et,
        ordered,
        service_type_by_bag=service_type_by_bag,
    )
    if not ineligible:
        return ordered
    return [bid for bid in ordered if bid not in ineligible]


def _exclude_stale_prior_day_terminal_cycles(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop WF day-bag rows whose bag IDs fail ``final_wf_day_membership_bag_ids``."""
    if not bags:
        return bags
    bids = [
        normalize_bag_id(b.get("bag_id"))
        for b in bags
        if normalize_bag_id(b.get("bag_id"))
    ]
    if not bids:
        return bags
    kept = set(
        final_wf_day_membership_bag_ids(
            cursor, int(organization_id), shift_date_et, bids
        )
    )
    if len(kept) == len(bids):
        return bags
    return [b for b in bags if normalize_bag_id(b.get("bag_id")) in kept]


def apply_wf_selected_day_boundary_guard(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shared WF day-bag row guard — drop historically completed bag IDs."""
    return _exclude_stale_prior_day_terminal_cycles(
        cursor, organization_id, shift_date_et, list(bags or [])
    )


def resolve_canonical_wf_day_bag_rows_for_persist(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> list[dict[str, Any]]:
    """Deterministic WF day-bag rows for selected-day persist (single membership source).

    Membership comes only from ``get_canonical_wf_workload``. Service cycles,
    append-only scrape membership, and absence alone cannot admit bags.

    Same-day projected day_bags are NOT fed back into membership. Manager-edit
    fields may be preserved; review/Missing flags from a prior projection must
    not alter whether a bag belongs.
    """
    org = int(organization_id)
    bags = _canonical_wf_bags_for_date(cursor, org, shift_date_et)
    prior_wf = _prior_wf_day_bags_by_id(cursor, org, shift_date_et)
    out: list[dict[str, Any]] = []
    for b in bags:
        prior = prior_wf.get(normalize_bag_id(b.get("bag_id")))
        if prior and int(prior.get("manager_edit_version") or 0) > 0:
            out.append(_merge_wf_review_hints(b, prior))
        else:
            out.append(b)
    return out


def _cycle_row_rank(row: Mapping[str, Any]) -> tuple[int, float, float]:
    """Lower rank wins. COMPLETED beats REVIEW beats ACTIVE; then latest completion/anchor."""
    status = str(row.get("status") or STATUS_ACTIVE)
    if status == STATUS_COMPLETED:
        tier = 0
    elif status == STATUS_REVIEW:
        tier = 1
    else:
        tier = 2
    completed_at = row.get("completed_at")
    completed_ts = (
        completed_at.timestamp()
        if isinstance(completed_at, datetime)
        else 0.0
    )
    anchor = row.get("cycle_anchor_at")
    anchor_ts = anchor.timestamp() if isinstance(anchor, datetime) else 0.0
    return (tier, -completed_ts, -anchor_ts)


def _dedupe_canonical_cycle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One projection row per bag — duplicate cycle rows must not shadow COMPLETED."""
    by_bag: dict[str, dict[str, Any]] = {}
    for row in rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        prev = by_bag.get(bid)
        if prev is None or _cycle_row_rank(row) < _cycle_row_rank(prev):
            by_bag[bid] = row
    return list(by_bag.values())


def _canonical_wf_bags_for_date(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> list[dict[str, Any]]:
    """WF day-bag rows derived from ``get_canonical_wf_workload`` (not service cycles)."""
    from backend.rinse_wf_canonical_workload import (
        assert_canonical_workload_invariants,
        canonical_wf_day_bag_rows,
        get_canonical_wf_workload,
    )

    wl = get_canonical_wf_workload(cursor, int(organization_id), shift_date_et)
    assert_canonical_workload_invariants(wl)
    bags = canonical_wf_day_bag_rows(
        cursor, int(organization_id), shift_date_et, workload=wl
    )
    return _exclude_stale_prior_day_terminal_cycles(
        cursor, organization_id, shift_date_et, bags
    )


def _prior_wf_day_bags_by_id(
    cursor, organization_id: int, shift_date_et: date
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in load_day_bags(cursor, organization_id, shift_date_et) or []:
        if str(row.get("service_type") or "").upper() != "WF":
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out[bid] = row
    return out


def _merge_wf_review_hints(
    canonical_bag: dict[str, Any], prior_row: dict[str, Any] | None
) -> dict[str, Any]:
    if not prior_row:
        return canonical_bag
    merged = dict(canonical_bag)
    codes = sorted(
        {
            str(c)
            for c in (
                list(merged.get("review_reason_codes") or [])
                + list(prior_row.get("review_reason_codes") or [])
            )
            if str(c).strip()
        }
    )
    merged["review_reason_codes"] = codes
    if codes and merged.get("effective_status") == OUTCOME_PENDING:
        merged["effective_status"] = OUTCOME_REVIEW_REQUIRED
    if int(prior_row.get("manager_edit_version") or 0) > 0:
        for key in (
            "canonical_completion_status",
            "canonical_completion_timestamp",
            "canonical_completion_employee",
            "pre_weight_lbs",
            "post_weight_lbs",
        ):
            if prior_row.get(key) is not None:
                merged[key] = prior_row.get(key)
    return merged


def _preserved_hd_bag_dicts(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    exclude_bag_ids: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Preserve HD day_bags alongside a WF replace.

    Never re-inject bag IDs that belong to the frozen canonical WF set — a prior
    bad persist that labeled a WF bag as HD must not overwrite WF membership.

    Inverse (required after WF derives exclude authoritative HD): prior day_bag
    rows wrongly labeled WF that are authoritative HD must be kept as HD, or
    they vanish when canonical WF drops them.
    """
    from backend.rinse_wf_canonical_workload import _authoritative_hd_bag_ids

    exclude = {
        normalize_bag_id(b)
        for b in (exclude_bag_ids or set())
        if normalize_bag_id(b)
    }
    prior_rows = list(load_day_bags(cursor, organization_id, shift_date_et) or [])
    prior_ids = [
        normalize_bag_id(r.get("bag_id"))
        for r in prior_rows
        if normalize_bag_id(r.get("bag_id"))
    ]
    auth_hd = _authoritative_hd_bag_ids(
        cursor, int(organization_id), shift_date_et, prior_ids
    )
    bags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in prior_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid or bid in exclude or bid in seen:
            continue
        svc = str(row.get("service_type") or "").strip().upper()
        if svc == "WF" and bid not in auth_hd:
            continue
        # Non-WF rows stay as stored; mislabeled WF + authoritative HD → HD.
        out_svc = "HD" if (svc == "WF" and bid in auth_hd) else (row.get("service_type") or "HD")
        if str(out_svc).strip().upper() == "WF":
            continue
        seen.add(bid)
        snap = dict(row.get("bag_snapshot") or {})
        snap["service_type"] = out_svc
        bags.append(
            {
                "bag_id": bid,
                "service_type": out_svc,
                "rush_status": row.get("rush_status"),
                "rush_flag": row.get("rush_status"),
                "new_or_carryover": row.get("new_or_carryover"),
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "post_weight_lbs": row.get("post_weight_lbs"),
                "effective_status": row.get("effective_status"),
                "review_reason_codes": row.get("review_reason_codes") or [],
                "canonical_completion_status": row.get("canonical_completion_status"),
                "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
                "bag_snapshot": snap,
            }
        )
    return bags


def terminal_project_canonical_wf_day_snapshot(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Terminal write: one frozen canonical derivation → replace day_bags.

    Order is non-negotiable for idempotency:
      1) desired_set = get_canonical_wf_workload(source evidence, D)
      2) persisted_set := desired_set
      3) cycle reconcile is hygiene AFTER persist (must not re-drive membership)

    Never derive membership from the previous projected day snapshot, and never
    re-resolve membership after mutating service cycles in the same projection.
    """
    from backend.rinse_wf_canonical_workload import (
        assert_canonical_workload_invariants,
        canonical_wf_day_bag_rows,
        get_canonical_wf_workload,
    )
    from backend.rinse_wf_service_cycle import (
        reconcile_stale_active_wf_cycles_from_canonical_completion,
    )

    ensure_wf_service_cycles_table(cursor)
    ensure_shift_monitor_day_tables(cursor)
    org = int(organization_id)

    # Freeze membership from source evidence BEFORE any cycle mutation.
    workload_canon = get_canonical_wf_workload(cursor, org, shift_date_et)
    assert_canonical_workload_invariants(workload_canon)
    wf_bags = canonical_wf_day_bag_rows(
        cursor, org, shift_date_et, workload=workload_canon
    )
    # Preserve manager edits only — never re-admit via projected review/Missing.
    prior_wf = _prior_wf_day_bags_by_id(cursor, org, shift_date_et)
    merged_wf: list[dict[str, Any]] = []
    for b in wf_bags:
        prior = prior_wf.get(normalize_bag_id(b.get("bag_id")))
        if prior and int(prior.get("manager_edit_version") or 0) > 0:
            merged_wf.append(_merge_wf_review_hints(b, prior))
        else:
            merged_wf.append(b)
    wf_bags = merged_wf

    # Desired WF set wins: never preserve a stale HD label for the same bag_id.
    desired_wf_ids = {
        normalize_bag_id(b)
        for b in (workload_canon.get("bag_ids") or [])
        if normalize_bag_id(b)
    }
    hd_bags = _preserved_hd_bag_dicts(
        cursor, org, shift_date_et, exclude_bag_ids=desired_wf_ids
    )
    all_bags = wf_bags + hd_bags

    day = get_day_record(cursor, org, shift_date_et)
    status = str((day or {}).get("status") or STATUS_OPEN)
    rows: list[dict[str, Any]] = []
    new_today_ids: list[str] = []
    carryover_ids: list[str] = []
    completed_ids: list[str] = []
    pending_ids: list[str] = []
    review_ids: list[str] = []
    for b in all_bags:
        snap = dict(b.get("bag_snapshot") or {})
        # Row-level service_type wins over a stale snapshot label (e.g. WF→HD reclass).
        rows.append(
            {
                **b,
                **snap,
                "bag_id": b["bag_id"],
                "service_type": b.get("service_type") or snap.get("service_type"),
            }
        )
        bid = b["bag_id"]
        noc = str(b.get("new_or_carryover") or "")
        if noc == OUTCOME_CARRYOVER_QUERY or "carryover" in noc.lower():
            carryover_ids.append(bid)
        else:
            new_today_ids.append(bid)
        eff = b.get("effective_status")
        if eff == OUTCOME_COMPLETED:
            completed_ids.append(bid)
        elif eff == OUTCOME_REVIEW_REQUIRED:
            review_ids.append(bid)
        else:
            pending_ids.append(bid)
    wl = {
        "selected_date_et": shift_date_et.isoformat(),
        "rows": rows,
        "new_today": new_today_ids,
        "carryover": carryover_ids,
        "completed_on_date": completed_ids,
        "pending_end_of_date": pending_ids,
        "review_required": review_ids,
        "review_reasons_by_bag": {
            b["bag_id"]: b.get("review_reason_codes") or []
            for b in all_bags
            if b.get("review_reason_codes")
        },
        "from_snapshot": True,
        "shift_day_status": status,
        # Persist must not re-call get_canonical / resolve after this freeze.
        "canonical_membership_frozen": True,
        "canonical_bag_ids": sorted(workload_canon.get("bag_ids") or []),
    }
    activation = get_step1_activation_date(cursor, org) or shift_date_et
    summary = build_step1_headline_summary(
        wl,
        selected_date_et=shift_date_et,
        activation_date=activation,
    )
    counts = reporting_counts_for_date(cursor, org, shift_date_et)
    summary = {
        **summary,
        "membership": {
            "admitted_on_date": counts.get("admitted_on_date"),
            "completed_on_date": counts.get("completed_on_date"),
            "opening_backlog_query": counts.get("opening_backlog"),
            "active_now": counts.get("active_now"),
            "canonical_source": True,
            "canonical_workload_count": len(workload_canon.get("bag_ids") or []),
        },
        "headline_status_synced_from_day_bags": True,
    }
    out = persist_day_snapshot(
        cursor,
        org,
        shift_date_et,
        workload=wl,
        summary=summary,
        force=force,
        chronology_complete=True,
    )
    # Cycle hygiene only — must not feed back into membership this pass.
    reconcile_stale_active_wf_cycles_from_canonical_completion(
        cursor, org, shift_date_et
    )
    return out


def project_canonical_cycles_to_day_snapshot(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Alias for terminal projection (one-way canonical → day_bags)."""
    return terminal_project_canonical_wf_day_snapshot(
        cursor, organization_id, shift_date_et, force=force
    )
