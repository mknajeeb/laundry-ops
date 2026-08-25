"""One-way compatibility projection: canonical WF cycles → legacy day_bags / Management."""

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


def _exclude_stale_prior_day_terminal_cycles(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop prior-day terminal completions re-admitted via stale ACTIVE cycle rows."""
    prior_done = _prior_day_terminal_completed_wf_bag_ids(
        cursor, organization_id, shift_date_et
    )
    if not prior_done:
        return bags
    kept: list[dict[str, Any]] = []
    for bag in bags:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid or bid not in prior_done:
            kept.append(bag)
            continue
        snap = bag.get("bag_snapshot") or {}
        admitted = _parse_cycle_dt(snap.get("admitted_at"))
        anchor = _parse_cycle_dt(snap.get("cycle_anchor_at"))
        if _cycle_anchor_or_admit_on_date(
            admitted_at=admitted,
            cycle_anchor_at=anchor,
            shift_date_et=shift_date_et,
        ):
            kept.append(bag)
    return kept


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
    org = int(organization_id)
    day_start = naive_et_day_start(shift_date_et)
    day_end = day_start + timedelta(days=1)
    cur = cursor
    cur.execute(
        """
        SELECT * FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND (
            (admitted_at >= %s AND admitted_at < %s)
            OR (completed_at >= %s AND completed_at < %s)
            OR (
              admitted_at < %s
              AND status IN (%s, %s)
              AND (completed_at IS NULL OR completed_at >= %s)
            )
          )
        ORDER BY cycle_anchor_at ASC
        """,
        (
            org,
            day_start,
            day_end,
            day_start,
            day_end,
            day_start,
            STATUS_ACTIVE,
            STATUS_REVIEW,
            day_start,
        ),
    )
    bags: list[dict[str, Any]] = []
    for c in _dedupe_canonical_cycle_rows(
        [c for c in (cur.fetchall() or []) if isinstance(c, dict)]
    ):
        bid = c.get("bag_id")
        if not bid:
            continue
        admitted_at = c.get("admitted_at")
        anchor_at = c.get("cycle_anchor_at")
        status = str(c.get("status") or STATUS_ACTIVE)
        if status == STATUS_COMPLETED:
            eff = OUTCOME_COMPLETED
        elif status == STATUS_REVIEW:
            eff = OUTCOME_REVIEW_REQUIRED
        else:
            eff = OUTCOME_PENDING

        if _cycle_anchor_or_admit_on_date(
            admitted_at=admitted_at if isinstance(admitted_at, datetime) else None,
            cycle_anchor_at=anchor_at if isinstance(anchor_at, datetime) else None,
            shift_date_et=shift_date_et,
        ):
            new_or_carry = "new_today"
        elif isinstance(admitted_at, datetime) and admitted_at < day_start:
            new_or_carry = OUTCOME_CARRYOVER_QUERY
        else:
            new_or_carry = "new_today"

        rush = c.get("rush_status")
        bags.append(
            {
                "bag_id": bid,
                "service_type": "WF",
                "rush_status": rush,
                "rush_flag": rush,
                "new_or_carryover": new_or_carry,
                "pre_weight_lbs": c.get("pre_weight_lbs"),
                "post_weight_lbs": c.get("post_weight_lbs"),
                "canonical_completion_status": (
                    OUTCOME_COMPLETED if eff == OUTCOME_COMPLETED else eff
                ),
                "canonical_completion_timestamp": c.get("completed_at"),
                "effective_status": eff,
                "review_reason_codes": (
                    [c.get("review_reason")] if c.get("review_reason") else []
                ),
                "bag_snapshot": {
                    "cycle_id": c.get("id"),
                    "cycle_anchor_at": str(c.get("cycle_anchor_at")),
                    "admitted_at": str(admitted_at),
                    "completion_source": c.get("completion_source"),
                    "canonical_projection": True,
                },
                "completion_at": c.get("completed_at"),
            }
        )
    bags = _exclude_stale_prior_day_terminal_cycles(
        cursor, organization_id, shift_date_et, bags
    )
    if bags:
        from backend.rinse_day_bag_completion_projection import (
            apply_normalized_completion_fields,
            enrich_bags_completion_from_scans,
        )
        from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs
        from backend.rinse_veewash_review import load_bag_weight_map

        enrich_bags_completion_from_scans(
            cursor, organization_id, shift_date_et, bags
        )
        bags = [apply_normalized_completion_fields(b) for b in bags]
        bag_ids = [normalize_bag_id(b.get("bag_id")) for b in bags if b.get("bag_id")]
        weight_map = load_bag_weight_map(
            cursor,
            organization_id,
            bag_ids,
            selected_date_et=shift_date_et,
        )
        for bag in bags:
            bid = normalize_bag_id(bag.get("bag_id"))
            if not bid:
                continue
            resolved = weight_map.get(bid) or {}
            evidence_pre = authoritative_evidence_pre_lbs(resolved)
            if evidence_pre is not None:
                bag["pre_weight_lbs"] = evidence_pre
            if resolved.get("post_weight_lbs") is not None:
                bag["post_weight_lbs"] = resolved.get("post_weight_lbs")
            if resolved.get("pre_weight_source"):
                bag["pre_weight_source"] = resolved.get("pre_weight_source")
    return bags


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
    cursor, organization_id: int, shift_date_et: date
) -> list[dict[str, Any]]:
    bags: list[dict[str, Any]] = []
    for row in load_day_bags(cursor, organization_id, shift_date_et) or []:
        if str(row.get("service_type") or "").upper() == "WF":
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        bags.append(
            {
                "bag_id": bid,
                "service_type": row.get("service_type"),
                "rush_status": row.get("rush_status"),
                "rush_flag": row.get("rush_status"),
                "new_or_carryover": row.get("new_or_carryover"),
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "post_weight_lbs": row.get("post_weight_lbs"),
                "effective_status": row.get("effective_status"),
                "review_reason_codes": row.get("review_reason_codes") or [],
                "canonical_completion_status": row.get("canonical_completion_status"),
                "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
                "bag_snapshot": row.get("bag_snapshot") or {},
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
    """Terminal write: canonical WF rows + preserved HD rows → day_bags / Management."""
    ensure_wf_service_cycles_table(cursor)
    ensure_shift_monitor_day_tables(cursor)
    org = int(organization_id)
    prior_wf = _prior_wf_day_bags_by_id(cursor, org, shift_date_et)
    wf_bags = [
        _merge_wf_review_hints(b, prior_wf.get(normalize_bag_id(b.get("bag_id"))))
        for b in _canonical_wf_bags_for_date(cursor, org, shift_date_et)
    ]
    hd_bags = _preserved_hd_bag_dicts(cursor, org, shift_date_et)
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
        rows.append({**b, **snap, "bag_id": b["bag_id"]})
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
        },
        "headline_status_synced_from_day_bags": True,
    }
    return persist_day_snapshot(
        cursor,
        org,
        shift_date_et,
        workload=wl,
        summary=summary,
        force=force,
        chronology_complete=True,
    )


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
