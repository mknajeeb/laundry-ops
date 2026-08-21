"""Authoritative Dirty-based operational membership eligibility.

Business rule (WF / HD Dirty entry racks):

A bag belongs to selected-date operational workload if:
  - it has a recognized Dirty entry-rack scan with entry_date <= selected_date ET
  - it has not completed (current cycle) before selected_date
  - it is not a confirmed disappearance from a prior day

Prior-day unfinished day members (pending / carried_forward / review_required)
seed next-day carryover without requiring a post-midnight portal scrape.

Portal At Vendor presence alone never admits membership.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id

# Prior-day statuses that seed next-day carryover (unfinished at day boundary).
_PRIOR_UNFINISHED_STATUSES = frozenset(
    {
        "pending",
        "carried_forward",
        "review_required",
    }
)


def load_prior_day_unfinished_member_ids(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    service_type: str | None = "WF",
) -> set[str]:
    """Durable prior-day unfinished membership → next-day carryover seeds.

    Independent of portal scrapes after midnight.
    """
    from backend.ta_helpers import table_exists

    prior = selected_date_et - timedelta(days=1)
    org = int(organization_id)
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return set()
    svc = str(service_type or "").strip().upper()
    params: list[Any] = [org, prior]
    svc_sql = ""
    if svc:
        svc_sql = " AND UPPER(TRIM(COALESCE(service_type, 'WF'))) = %s"
        params.append(svc)
    status_list = sorted(_PRIOR_UNFINISHED_STATUSES)
    ph = ",".join(["%s"] * len(status_list))
    params.extend(status_list)
    cursor.execute(
        f"""
        SELECT bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          {svc_sql}
          AND LOWER(TRIM(COALESCE(effective_status, ''))) IN ({ph})
        """,
        tuple(params),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, dict) else row[0]
        )
        if bid:
            out.add(bid)
    return out


def load_dirty_entry_dates(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str] | None = None,
    *,
    entry_racks: Sequence[str] | None = None,
) -> dict[str, date]:
    """bag_id → first Dirty entry-rack ET date (recognized service entry)."""
    from backend.rinse_processing_settings import (
        DEFAULT_FACILITY_ENTRY_RACKS,
        get_processing_settings,
    )
    from backend.rinse_veewash_workload import load_first_dirty_scans

    racks = list(entry_racks) if entry_racks is not None else None
    if racks is None:
        try:
            racks = get_processing_settings(cursor, organization_id).get(
                "facility_entry_racks"
            ) or list(DEFAULT_FACILITY_ENTRY_RACKS)
        except Exception:
            racks = list(DEFAULT_FACILITY_ENTRY_RACKS)
    dirty = load_first_dirty_scans(cursor, organization_id, entry_racks=racks)
    out: dict[str, date] = {}
    wanted = None
    if bag_ids is not None:
        wanted = {normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)}
    for bid, row in (dirty or {}).items():
        nb = normalize_bag_id(bid)
        if not nb:
            continue
        if wanted is not None and nb not in wanted:
            continue
        ed = row.get("entry_date") if isinstance(row, dict) else None
        if isinstance(ed, date):
            out[nb] = ed
    return out


def load_completed_before_date(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
    *,
    dirty_entry_by_bag: Mapping[str, date] | None = None,
) -> set[str]:
    """Bags completed for the current Dirty cycle before selected_date.

    Completions on days earlier than the bag's Dirty entry date are prior-cycle
    history and do not block membership.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids or not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return set()
    org = int(organization_id)
    dirty = dict(dirty_entry_by_bag or {})
    found: set[str] = set()
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, shift_date_et
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et < %s
              AND bag_id IN ({ph})
              AND LOWER(TRIM(COALESCE(effective_status, ''))) = 'completed'
            """,
            (org, selected_date_et, *part),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(
                row.get("bag_id") if isinstance(row, dict) else row[0]
            )
            if not bid:
                continue
            sd = row.get("shift_date_et") if isinstance(row, dict) else row[1]
            if not hasattr(sd, "isoformat"):
                try:
                    sd = date.fromisoformat(str(sd)[:10])
                except ValueError:
                    continue
            entry = dirty.get(bid)
            if entry is not None and sd < entry:
                continue
            found.add(bid)
    return found


def load_prior_day_disappearance_ids(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
) -> set[str]:
    """Prior-open exceptions already persisted on a day_bag before selected_date.

    Does not infer disappearance from live At Vendor active=0 (partial scrapes
    leave many unfinished bags inactive). Same-day disappearance remains a
    classifier concern for bags already in membership.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids or not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return set()
    org = int(organization_id)
    out: set[str] = set()
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id,
                   JSON_UNQUOTE(JSON_EXTRACT(bag_snapshot_json, '$.disappeared_date')) AS dd
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND shift_date_et < %s
              AND LOWER(TRIM(COALESCE(effective_status, ''))) = 'disappeared_prior_open_exception'
            """,
            (org, *part, selected_date_et),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(row.get("bag_id") if isinstance(row, dict) else None)
            if not bid:
                continue
            dd_raw = row.get("dd") if isinstance(row, dict) else None
            if dd_raw:
                try:
                    dd = date.fromisoformat(str(dd_raw)[:10])
                except ValueError:
                    dd = None
                if dd is not None and dd >= selected_date_et:
                    continue
            out.add(bid)
    return out


def filter_operationally_eligible_ids(
    cursor,
    organization_id: int,
    selected_date_et: date,
    candidate_bag_ids: Sequence[str],
    *,
    dirty_entry_by_bag: Mapping[str, date] | None = None,
    protect_from_disappearance: Sequence[str] | None = None,
    protect_from_completed_before: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Apply the Dirty/completion/disappearance business rule to candidates."""
    candidates = sorted(
        {normalize_bag_id(b) for b in candidate_bag_ids if normalize_bag_id(b)}
    )
    protected_dis = {
        normalize_bag_id(b)
        for b in (protect_from_disappearance or [])
        if normalize_bag_id(b)
    }
    protected_comp = {
        normalize_bag_id(b)
        for b in (protect_from_completed_before or [])
        if normalize_bag_id(b)
    }
    dirty = dict(dirty_entry_by_bag or {})
    missing = [b for b in candidates if b not in dirty]
    if missing:
        dirty.update(load_dirty_entry_dates(cursor, organization_id, missing))

    no_dirty: list[str] = []
    dated: list[str] = []
    for bid in candidates:
        ed = dirty.get(bid)
        if ed is None or ed > selected_date_et:
            no_dirty.append(bid)
        else:
            dated.append(bid)

    completed_before = load_completed_before_date(
        cursor,
        organization_id,
        selected_date_et,
        dated,
        dirty_entry_by_bag=dirty,
    )
    completed_before -= protected_comp
    after_comp = [b for b in dated if b not in completed_before]
    prior_disappear = load_prior_day_disappearance_ids(
        cursor, organization_id, selected_date_et, after_comp
    )
    prior_disappear -= protected_dis
    eligible = sorted(b for b in after_comp if b not in prior_disappear)
    return {
        "eligible": eligible,
        "excluded_no_dirty": sorted(no_dirty),
        "excluded_completed_before": sorted(completed_before),
        "excluded_prior_disappearance": sorted(prior_disappear),
        "dirty_entry_by_bag": {b: dirty[b] for b in eligible if b in dirty},
    }


def load_active_presence_bag_ids(
    cursor,
    organization_id: int,
    *,
    service_type: str | None = "WF",
) -> set[str]:
    """Bags currently active on At Vendor presence (portal enrichment candidates)."""
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return set()
    org = int(organization_id)
    svc = str(service_type or "").strip().upper()
    params: list[Any] = [org]
    svc_sql = ""
    if svc:
        svc_sql = " AND UPPER(TRIM(COALESCE(service_type, 'WF'))) = %s"
        params.append(svc)
    cursor.execute(
        f"""
        SELECT bag_id
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s
          AND active = 1
          AND LOWER(TRIM(COALESCE(portal_status, ''))) = 'at_vendor'
          {svc_sql}
        """,
        tuple(params),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, dict) else row[0]
        )
        if bid:
            out.add(bid)
    return out


def resolve_day_operational_membership(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    extra_candidates: Sequence[str] | None = None,
    existing_member_ids: Sequence[str] | None = None,
    service_type: str | None = "WF",
    include_active_presence: bool = True,
) -> dict[str, Any]:
    """Deterministic operational membership for a business day.

    Seeds:
      1) prior-day unfinished durable members (carryover)
      2) existing operational day members (except prior-open exceptions)
      3) Dirty-today entrants (via extra_candidates or dirty dates)
      4) optionally active At Vendor presence bags (enrichment only — still Dirty-gated)

    Portal presence is never sufficient by itself.
    """
    prior_unfinished = load_prior_day_unfinished_member_ids(
        cursor,
        organization_id,
        selected_date_et,
        service_type=service_type,
    )
    existing = {
        normalize_bag_id(b)
        for b in (existing_member_ids or [])
        if normalize_bag_id(b)
    }
    extras = {
        normalize_bag_id(b)
        for b in (extra_candidates or [])
        if normalize_bag_id(b)
    }
    dirty = load_dirty_entry_dates(cursor, organization_id)
    dirty_today = {
        bid for bid, ed in dirty.items() if ed == selected_date_et
    }
    presence_active: set[str] = set()
    if include_active_presence:
        presence_active = load_active_presence_bag_ids(
            cursor, organization_id, service_type=service_type
        )
    candidates = sorted(
        prior_unfinished | existing | extras | dirty_today | presence_active
    )
    filtered = filter_operationally_eligible_ids(
        cursor,
        organization_id,
        selected_date_et,
        candidates,
        dirty_entry_by_bag=dirty,
        protect_from_disappearance=sorted(prior_unfinished),
        protect_from_completed_before=sorted(prior_unfinished),
    )
    eligible = set(filtered["eligible"])
    carryover = sorted(prior_unfinished & eligible)
    new_or_existing = sorted(eligible - set(carryover))
    return {
        "ok": True,
        "selected_date_et": selected_date_et.isoformat(),
        "member_ids": sorted(eligible),
        "carryover_bag_ids": carryover,
        "new_or_other_bag_ids": new_or_existing,
        "prior_unfinished_seed": sorted(prior_unfinished),
        "excluded_no_dirty": filtered["excluded_no_dirty"],
        "excluded_completed_before": filtered["excluded_completed_before"],
        "excluded_prior_disappearance": filtered["excluded_prior_disappearance"],
        "dirty_entry_by_bag": {
            k: v.isoformat() if hasattr(v, "isoformat") else v
            for k, v in (filtered.get("dirty_entry_by_bag") or {}).items()
        },
        "membership_policy": "dirty_entry_v1",
    }


def headline_identity_ok(headline: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Workload must equal Completed + Pending + Review for WF (and all)."""
    hl = dict(headline or {})
    segs = dict(hl.get("segments") or {})
    problems: list[str] = []
    for key in ("wf", "all"):
        seg = dict(segs.get(key) or {})
        if not seg:
            continue
        try:
            total = int(
                seg.get("total_workload")
                if seg.get("total_workload") is not None
                else (seg.get("active_workload") or 0)
            )
            completed = int(seg.get("completed") or 0)
            pending = int(seg.get("pending") or 0)
            review = int(
                (seg.get("exceptions") or {}).get("review_required")
                or (seg.get("exceptions") or {}).get("total")
                or 0
            )
        except (TypeError, ValueError):
            problems.append(f"{key}:non_int_counts")
            continue
        if total != completed + pending + review:
            problems.append(
                f"{key}: {total} != {completed}+{pending}+{review}"
            )
    if problems:
        return False, "; ".join(problems)
    return True, "ok"
