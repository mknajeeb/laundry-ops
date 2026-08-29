"""Canonical WF daily workload — single public membership authority.

Model (non-negotiable)
----------------------
1. Portal scraper = evidence collector only (never owns membership / resurrection).
2. Terminality belongs to an order_instance (seeded from service-cycle
   cycle_anchor_at), not permanently to physical bag_id. A completed order
   instance never reopens; a later authoritative cycle for the same bag_id
   may enter a later day's workload as a new order_instance.
3. Daily workload is DERIVED for ET date D, never append-only accumulation:
     completed = canonical completion date == D
     pending / review = not terminal AND legitimately open for D
     carryover = unfinished OPEN bags from before D
4. Missing From Portal is a review attribute on an already-legitimate OPEN bag.
   It never introduces membership.
5. Service cycles are audit/history + order_instance seed — not membership
   admission by themselves.
6. Authoritative Rinse HD bags are excluded before freeze
   (``canonical WF ∩ authoritative HD = ∅``).

Public API: ``get_canonical_wf_workload(org_id, date_et)``.
Every Management WF consumer must use this (directly or via the day persist path).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from backend.business_time import system_datetime_to_et
from backend.rinse_bag_completion import COMPLETION_COMPLETED, normalize_bag_id
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    STEP1_AUTHORITATIVE_START_ET,
)
from backend.ta_helpers import table_exists

LIFECYCLE_OPEN = "OPEN"
LIFECYCLE_COMPLETED = "COMPLETED"

_PRIOR_OPEN_STATUSES = frozenset(
    {
        "pending",
        "review_required",
        "carried_forward",
    }
)

OUTCOME_CARRYOVER = "opening_backlog_query_only"
REVIEW_MISSING_FROM_PORTAL = "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL"


def _et_date(dt: Any) -> date | None:
    if not isinstance(dt, datetime):
        return None
    et = system_datetime_to_et(dt)
    if et is None:
        return None
    return et.date()


def get_wf_bag_lifecycle(
    cursor,
    organization_id: int,
    bag_id: str,
) -> dict[str, Any]:
    """Current order-occurrence lifecycle for a physical bag_id.

    COMPLETED means the *latest* order_instance (or legacy registry row) is
    completed. A later authoritative cycle creates a new open occurrence.
    """
    from backend.rinse_bag_registry import get_registry_row
    from backend.rinse_order_instances import get_latest_order_instance_for_bag

    bid = normalize_bag_id(bag_id)
    if not bid:
        return {
            "bag_id": "",
            "lifecycle": LIFECYCLE_OPEN,
            "completed_at": None,
            "completed_date_et": None,
        }
    latest = get_latest_order_instance_for_bag(
        cursor, int(organization_id), bid, service_type="WF"
    )
    if latest is not None:
        completed_at = latest.get("completed_at")
        if isinstance(completed_at, datetime):
            return {
                "bag_id": bid,
                "lifecycle": LIFECYCLE_COMPLETED,
                "completed_at": completed_at,
                "completed_date_et": _et_date(completed_at),
                "order_instance_id": latest.get("order_instance_id"),
            }
        return {
            "bag_id": bid,
            "lifecycle": LIFECYCLE_OPEN,
            "completed_at": None,
            "completed_date_et": None,
            "order_instance_id": latest.get("order_instance_id"),
        }

    row = get_registry_row(cursor, int(organization_id), bid) or {}
    status = str(row.get("completion_status") or "").strip().upper()
    completed_at = row.get("completed_at")
    if status == COMPLETION_COMPLETED:
        return {
            "bag_id": bid,
            "lifecycle": LIFECYCLE_COMPLETED,
            "completed_at": completed_at,
            "completed_date_et": _et_date(completed_at)
            if isinstance(completed_at, datetime)
            else None,
        }
    return {
        "bag_id": bid,
        "lifecycle": LIFECYCLE_OPEN,
        "completed_at": None,
        "completed_date_et": None,
    }


def _registry_completed_date_by_bag(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, date]:
    """bag_id → ET completion date for registry COMPLETED rows."""
    from backend.rinse_bag_registry import get_registry_rows_for_bags

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return {}
    rows = get_registry_rows_for_bags(cursor, int(organization_id), ids) or {}
    out: dict[str, date] = {}
    for bid, row in rows.items():
        if str(row.get("completion_status") or "").strip().upper() != COMPLETION_COMPLETED:
            continue
        d = _et_date(row.get("completed_at"))
        if d is not None:
            out[normalize_bag_id(bid)] = d
    return out


def _registry_wf_completed_on_date(
    cursor,
    organization_id: int,
    date_et: date,
) -> set[str]:
    """WF (or unknown service) registry bags completed on ET date D."""
    if not table_exists(cursor, "rinse_bag_registry"):
        return set()
    day_start = naive_et_day_start(date_et)
    day_end = day_start + timedelta(days=1)
    # Storage timestamps are UTC; convert window via aware ET bounds → UTC compare
    # by loading candidates in a padded UTC window then filtering ET date.
    pad_start = day_start - timedelta(hours=6)
    pad_end = day_end + timedelta(hours=6)
    cursor.execute(
        """
        SELECT bag_id, completed_at, service_type
        FROM rinse_bag_registry
        WHERE organization_id = %s
          AND completion_status = %s
          AND completed_at IS NOT NULL
          AND completed_at >= %s
          AND completed_at < %s
        """,
        (int(organization_id), COMPLETION_COMPLETED, pad_start, pad_end),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        svc = str(row.get("service_type") or "WF").strip().upper()
        if svc and svc not in ("WF",):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        if _et_date(row.get("completed_at")) == date_et:
            out.add(bid)
    return out


def _prior_day_unfinished_wf_ids(
    cursor,
    organization_id: int,
    date_et: date,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """Genuinely unfinished OPEN WF bags from D-1 day_bags (carryover seeds)."""
    from backend.rinse_veewash_shift_day import load_day_bags

    prior = date_et - timedelta(days=1)
    if prior < STEP1_AUTHORITATIVE_START_ET:
        return set(), {}
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return set(), {}
    ids: set[str] = set()
    meta: dict[str, dict[str, Any]] = {}
    for row in load_day_bags(cursor, int(organization_id), prior) or []:
        if str(row.get("service_type") or "WF").upper() != "WF":
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        status = str(row.get("effective_status") or "").strip().lower()
        if status not in _PRIOR_OPEN_STATUSES:
            continue
        ids.add(bid)
        meta[bid] = dict(row)
    return ids, meta


def _same_day_presence_wf_ids(
    cursor,
    organization_id: int,
    date_et: date,
) -> tuple[set[str], dict[str, dict[str, Any]], int | None, set[str]]:
    """WF bag IDs observed on valid same-day presence scrapes (presence evidence only).

    Failed / empty / partial-baseline scrapes are excluded by
    ``is_valid_baseline_scrape``. Absence is NOT derived here.

    Also returns ``portal_hd_ids``: bag IDs labeled HD on any valid same-day
    scrape (used to exclude authoritative HD from WF membership).
    """
    from backend.rinse_veewash_day_membership import (
        list_valid_same_day_scrapes,
        load_run_bag_rows,
    )

    ids: set[str] = set()
    meta: dict[str, dict[str, Any]] = {}
    portal_hd: set[str] = set()
    latest_run_id: int | None = None
    for run in list_valid_same_day_scrapes(cursor, int(organization_id), date_et):
        run_id = int(run.get("id") or 0) or None
        if run_id:
            latest_run_id = run_id
        for row in load_run_bag_rows(cursor, int(run["id"])):
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid:
                continue
            svc = str(row.get("service_type") or "WF").strip().upper()
            if svc == "HD":
                portal_hd.add(bid)
                continue
            if svc and svc != "WF":
                continue
            ids.add(bid)
            meta[bid] = row
    return ids, meta, latest_run_id, portal_hd


def _authoritative_hd_bag_ids(
    cursor,
    organization_id: int,
    date_et: date,
    bag_ids: list[str],
    *,
    portal_hd_ids: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """Authoritative Rinse HD bags among ``bag_ids`` — must never join WF.

    Authority (any one is sufficient) for *this* occurrence — not a permanent
    bag-level blacklist:
      - registry ``service_type = HD``
      - same-day portal scrape labeled HD
      - durable ``hd_day_bag_production`` row for ET date D
      - current ticket presence labeled HD
    Missing/review must never override this classification.
    """
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return set()
    org = int(organization_id)
    out: set[str] = set()
    id_set = set(ids)

    portal = {
        normalize_bag_id(b)
        for b in (portal_hd_ids or set())
        if normalize_bag_id(b)
    }
    out |= portal & id_set

    if table_exists(cursor, "rinse_bag_registry"):
        from backend.rinse_bag_registry import get_registry_rows_for_bags

        rows = get_registry_rows_for_bags(cursor, org, ids) or {}
        for bid, row in rows.items():
            nb = normalize_bag_id(bid)
            if not nb:
                continue
            if str(row.get("service_type") or "").strip().upper() == "HD":
                out.add(nb)

    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        chunk = 200
        for i in range(0, len(ids), chunk):
            part = ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id
                FROM rinse_cleaner_ticket_presence
                WHERE organization_id = %s
                  AND bag_id IN ({ph})
                  AND UPPER(TRIM(COALESCE(service_type, ''))) = 'HD'
                """,
                (org, *part),
            )
            for row in cursor.fetchall() or []:
                bid = normalize_bag_id(
                    row.get("bag_id") if isinstance(row, dict) else row[0]
                )
                if bid:
                    out.add(bid)

    if table_exists(cursor, "hd_day_bag_production"):
        chunk = 200
        for i in range(0, len(ids), chunk):
            part = ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id
                FROM hd_day_bag_production
                WHERE organization_id = %s
                  AND operations_date_et = %s
                  AND bag_id IN ({ph})
                """,
                (org, date_et, *part),
            )
            for row in cursor.fetchall() or []:
                bid = normalize_bag_id(
                    row.get("bag_id") if isinstance(row, dict) else row[0]
                )
                if bid:
                    out.add(bid)

    return out


def _discover_same_day_entry_wf_ids(
    cursor,
    organization_id: int,
    date_et: date,
) -> set[str]:
    """Bags with same-day facility-entry rack evidence (OPEN discovery, not absence)."""
    from backend.rinse_veewash_day_membership import _facility_entry_rack_keys

    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    rack_keys = _facility_entry_rack_keys(cursor, int(organization_id))
    if not rack_keys:
        return set()
    rack_ph = ",".join(["%s"] * len(rack_keys))
    cursor.execute(
        f"""
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < DATE_ADD(%s, INTERVAL 1 DAY)
          AND rack IS NOT NULL AND TRIM(rack) != ''
          AND LOWER(TRIM(rack)) IN ({rack_ph})
        """,
        (int(organization_id), date_et, date_et, *rack_keys),
    )
    return {
        normalize_bag_id(r.get("bag_id") if isinstance(r, dict) else r[0])
        for r in (cursor.fetchall() or [])
        if normalize_bag_id(r.get("bag_id") if isinstance(r, dict) else r[0])
    }


def _terminal_before_date(
    cursor,
    organization_id: int,
    date_et: date,
    bag_ids: list[str],
) -> set[str]:
    """Bags whose *current* order occurrence completed strictly before D.

    Carve-out requires an order_instance that *covers* D under the strict
    covering rule (completed-on-D, or open instance anchored on/overnight into
    D). A prior completion plus a malformed later cycle_anchor alone does not
    reopen the bag. Stale ACTIVE / Missing / EDD alone never carve out.
    """
    from backend.rinse_order_instances import bags_with_order_instance_covering_date
    from backend.rinse_veewash_day_membership import (
        _bags_canonically_completed_before_opening,
    )

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return set()
    reg = _registry_completed_date_by_bag(cursor, organization_id, ids)
    terminal = {bid for bid, d in reg.items() if d < date_et}
    # Carve out bags with a later/same-day order instance covering D.
    if terminal:
        covering = bags_with_order_instance_covering_date(
            cursor, int(organization_id), date_et, sorted(terminal), service_type="WF"
        )
        terminal -= covering
    remaining = [b for b in ids if b not in terminal]
    if remaining:
        terminal |= _bags_canonically_completed_before_opening(
            cursor,
            int(organization_id),
            date_et,
            remaining,
            service_type_by_bag={b: "WF" for b in remaining},
        )
        # Same carve-out after scan/cycle-based terminal detection.
        if terminal:
            covering = bags_with_order_instance_covering_date(
                cursor,
                int(organization_id),
                date_et,
                sorted(terminal),
                service_type="WF",
            )
            terminal -= covering
    return terminal


def _completion_date_on_d(
    cursor,
    organization_id: int,
    date_et: date,
    bag_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """bag_id → completion dict for bags completed on ET date D."""
    from backend.rinse_veewash_workload import load_canonical_completions_v2

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, dict[str, Any]] = {}
    if not ids:
        return out
    comps = (
        load_canonical_completions_v2(
            cursor,
            int(organization_id),
            ids,
            selected_date_et=date_et,
            service_type_by_bag={b: "WF" for b in ids},
        )
        or {}
    )
    for bid, comp in comps.items():
        nb = normalize_bag_id(bid)
        if not nb or not isinstance(comp, Mapping):
            continue
        cd = comp.get("completion_date")
        ca = comp.get("completion_at")
        if cd == date_et:
            out[nb] = dict(comp)
        elif isinstance(ca, datetime) and _et_date(ca) == date_et:
            out[nb] = dict(comp)
        elif str(comp.get("effective_status") or "").lower() == "completed":
            if cd == date_et or (isinstance(ca, datetime) and _et_date(ca) == date_et):
                out[nb] = dict(comp)
    reg_today = _registry_wf_completed_on_date(cursor, organization_id, date_et)
    for bid in reg_today:
        if bid in ids and bid not in out:
            out[bid] = {
                "completion_date": date_et,
                "effective_status": "completed",
                "completion_source": "registry",
            }
    return out


def _latest_absence_capable_present_ids(
    cursor,
    organization_id: int,
    date_et: date,
) -> tuple[set[str] | None, dict[str, Any]]:
    """Present bag IDs from the latest same-day scrape that may publish absence.

    Returns (None, meta) when no absence-capable full traversal exists —
    callers must NOT invent Missing From Portal.
    """
    from backend.rinse_portal_scrape_meta import portal_scrape_meta_allows_absence_completion
    from backend.rinse_veewash_day_membership import (
        _read_run_meta,
        list_valid_same_day_scrapes,
        load_run_bag_rows,
    )

    runs = list_valid_same_day_scrapes(cursor, int(organization_id), date_et)
    if not runs:
        return None, {"absence_allowed": False, "reason": "no_valid_same_day_scrape"}
    # Newest first for absence authority.
    for run in reversed(runs):
        meta = _read_run_meta(run)
        if not portal_scrape_meta_allows_absence_completion(meta):
            continue
        present = {
            normalize_bag_id(r.get("bag_id"))
            for r in load_run_bag_rows(cursor, int(run["id"]))
            if normalize_bag_id(r.get("bag_id"))
        }
        return present, {
            "absence_allowed": True,
            "presence_run_id": int(run["id"]),
            "present_count": len(present),
        }
    return None, {"absence_allowed": False, "reason": "no_full_traversal"}


def get_canonical_wf_workload(
    cursor,
    organization_id: int,
    date_et: date,
) -> dict[str, Any]:
    """Single public WF membership derivation for ET date ``date_et``.

    Returns immutable bag-ID sets with invariants:
      workload == completed ∪ pending ∪ review
      pairwise disjoint
      count == sum
      historical_completed_in_workload == 0
    """
    org = int(organization_id)
    if date_et < STEP1_AUTHORITATIVE_START_ET:
        empty = frozenset()
        return {
            "organization_id": org,
            "date_et": date_et.isoformat(),
            "completed": empty,
            "pending": empty,
            "review": empty,
            "bag_ids": empty,
            "new_today": empty,
            "carryover": empty,
            "missing_from_portal": empty,
            "historical_completed_in_workload": empty,
            "counts": {
                "completed": 0,
                "pending": 0,
                "review": 0,
                "workload": 0,
                "new_today": 0,
                "carryover": 0,
                "missing_from_portal": 0,
            },
            "arithmetic_ok": True,
            "invariants_ok": True,
            "bag_meta": {},
            "completion_by_bag": {},
            "source": "canonical_wf_workload_v1",
        }

    prior_open, prior_meta = _prior_day_unfinished_wf_ids(cursor, org, date_et)
    presence_ids, presence_meta, _latest_run, portal_hd_ids = _same_day_presence_wf_ids(
        cursor, org, date_et
    )
    entry_ids = _discover_same_day_entry_wf_ids(cursor, org, date_et)
    registry_done_today = _registry_wf_completed_on_date(cursor, org, date_et)

    seed = set(prior_open) | set(presence_ids) | set(entry_ids) | set(registry_done_today)
    terminal_before = _terminal_before_date(cursor, org, date_et, sorted(seed))
    # Permanent lifecycle: never admit historically completed bag IDs.
    candidates = {b for b in seed if b not in terminal_before}
    # HD/WF classification BEFORE freeze: authoritative HD ∩ WF must be empty.
    hd_exclude = _authoritative_hd_bag_ids(
        cursor,
        org,
        date_et,
        sorted(candidates),
        portal_hd_ids=portal_hd_ids,
    )
    candidates = {b for b in candidates if b not in hd_exclude}

    completed_map = _completion_date_on_d(cursor, org, date_et, sorted(candidates))
    completed = frozenset(completed_map.keys()) & frozenset(candidates)

    open_bags = frozenset(b for b in candidates if b not in completed)

    # Historical day freeze: never write current-day open ACTIVE/REVIEW bags
    # backward onto D < business_today merely because they are still open.
    # Historical D may keep completed-on-D and legitimate D-1 unfinished
    # carryover; presence/entry alone cannot retroactively grow open membership.
    from backend.business_time import business_today

    if date_et < business_today():
        open_bags = frozenset(b for b in open_bags if b in prior_open)

    carryover = frozenset(b for b in prior_open if b in candidates and b in (completed | open_bags))
    new_today = frozenset(
        b for b in (completed | open_bags) if b not in prior_open
    )

    present_ids, absence_meta = _latest_absence_capable_present_ids(
        cursor, org, date_et
    )
    missing: set[str] = set()
    if present_ids is not None:
        # Review attribute only — never introduce membership from absence.
        missing = {b for b in open_bags if b not in present_ids}

    review: set[str] = set()
    for bid in open_bags:
        prior = prior_meta.get(bid) or {}
        prior_status = str(prior.get("effective_status") or "").strip().lower()
        prior_codes = [
            str(c).strip()
            for c in (prior.get("review_reason_codes") or [])
            if str(c).strip()
        ]
        if prior_status == "review_required" or prior_codes:
            review.add(bid)
        if bid in missing:
            review.add(bid)

    pending = frozenset(b for b in open_bags if b not in review)
    review_fs = frozenset(review)
    missing_fs = frozenset(missing)
    bag_ids = frozenset(completed | pending | review_fs)

    historical = frozenset(b for b in bag_ids if b in terminal_before)
    disjoint = (
        not (completed & pending)
        and not (completed & review_fs)
        and not (pending & review_fs)
    )
    union_ok = bag_ids == (completed | pending | review_fs)
    arithmetic_ok = len(bag_ids) == len(completed) + len(pending) + len(review_fs)
    invariants_ok = (
        disjoint
        and union_ok
        and arithmetic_ok
        and len(historical) == 0
        and missing_fs <= open_bags
    )

    bag_meta: dict[str, dict[str, Any]] = {}
    for bid in bag_ids:
        codes: list[str] = []
        prior = prior_meta.get(bid) or {}
        for c in prior.get("review_reason_codes") or []:
            if str(c).strip():
                codes.append(str(c).strip())
        if bid in missing_fs and REVIEW_MISSING_FROM_PORTAL not in codes:
            codes.append(REVIEW_MISSING_FROM_PORTAL)
        if bid in completed:
            eff = OUTCOME_COMPLETED
        elif bid in review_fs:
            eff = OUTCOME_REVIEW_REQUIRED
        else:
            eff = OUTCOME_PENDING
        noc = OUTCOME_CARRYOVER if bid in carryover else "new_today"
        rush = None
        if bid in prior_meta:
            rush = prior_meta[bid].get("rush_status") or prior_meta[bid].get("rush_flag")
        if rush is None and bid in presence_meta:
            rush = presence_meta[bid].get("rush_flag")
        bag_meta[bid] = {
            "bag_id": bid,
            "service_type": "WF",
            "effective_status": eff,
            "new_or_carryover": noc,
            "review_reason_codes": codes,
            "rush_status": rush,
            "rush_flag": rush,
            "lifecycle": (
                LIFECYCLE_COMPLETED if bid in completed else LIFECYCLE_OPEN
            ),
            "from_canonical_workload": True,
        }

    return {
        "organization_id": org,
        "date_et": date_et.isoformat(),
        "completed": completed,
        "pending": pending,
        "review": review_fs,
        "bag_ids": bag_ids,
        "new_today": new_today,
        "carryover": carryover,
        "missing_from_portal": missing_fs,
        "historical_completed_in_workload": historical,
        "counts": {
            "completed": len(completed),
            "pending": len(pending),
            "review": len(review_fs),
            "workload": len(bag_ids),
            "new_today": len(new_today),
            "carryover": len(carryover),
            "missing_from_portal": len(missing_fs),
        },
        "arithmetic_ok": arithmetic_ok,
        "invariants_ok": invariants_ok,
        "absence_meta": absence_meta,
        "bag_meta": bag_meta,
        "completion_by_bag": completed_map,
        "prior_meta": prior_meta,
        "source": "canonical_wf_workload_v1",
    }


def canonical_wf_day_bag_rows(
    cursor,
    organization_id: int,
    date_et: date,
    *,
    workload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Materialize day-bag row dicts from ``get_canonical_wf_workload``."""
    wl = workload or get_canonical_wf_workload(cursor, organization_id, date_et)
    bag_meta = dict(wl.get("bag_meta") or {})
    completion_by_bag = dict(wl.get("completion_by_bag") or {})
    prior_meta = dict(wl.get("prior_meta") or {})
    rows: list[dict[str, Any]] = []
    for bid in sorted(wl.get("bag_ids") or []):
        meta = dict(bag_meta.get(bid) or {"bag_id": bid, "service_type": "WF"})
        prior = prior_meta.get(bid) or {}
        comp = completion_by_bag.get(bid) or {}
        comp_at = comp.get("completion_at") or prior.get("canonical_completion_timestamp")
        row = {
            **meta,
            "pre_weight_lbs": prior.get("pre_weight_lbs"),
            "post_weight_lbs": prior.get("post_weight_lbs"),
            "canonical_completion_status": (
                OUTCOME_COMPLETED
                if meta.get("effective_status") == OUTCOME_COMPLETED
                else meta.get("effective_status")
            ),
            "canonical_completion_timestamp": comp_at,
            "canonical_completion_employee": (
                comp.get("completion_employee")
                or prior.get("canonical_completion_employee")
            ),
            "completion_at": comp_at,
            "bag_snapshot": {
                "canonical_workload": True,
                "source": "canonical_wf_workload_v1",
                "review_reason": (meta.get("review_reason_codes") or [None])[0],
                "completion_source": comp.get("completion_source"),
            },
        }
        rows.append(row)

    if rows:
        from backend.rinse_day_bag_completion_projection import (
            apply_normalized_completion_fields,
            enrich_bags_completion_from_scans,
        )
        from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs
        from backend.rinse_veewash_review import load_bag_weight_map

        enrich_bags_completion_from_scans(
            cursor, organization_id, date_et, rows
        )
        rows = [apply_normalized_completion_fields(b) for b in rows]
        bag_ids = [normalize_bag_id(b.get("bag_id")) for b in rows if b.get("bag_id")]
        weight_map = load_bag_weight_map(
            cursor,
            organization_id,
            bag_ids,
            selected_date_et=date_et,
        )
        for bag in rows:
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
    return rows


def assert_canonical_workload_invariants(workload: Mapping[str, Any]) -> None:
    """Raise AssertionError when membership invariants fail."""
    completed = set(workload.get("completed") or [])
    pending = set(workload.get("pending") or [])
    review = set(workload.get("review") or [])
    bag_ids = set(workload.get("bag_ids") or [])
    historical = set(workload.get("historical_completed_in_workload") or [])
    missing = set(workload.get("missing_from_portal") or [])
    open_bags = pending | review
    if bag_ids != completed | pending | review:
        raise AssertionError("workload union mismatch")
    if completed & pending or completed & review or pending & review:
        raise AssertionError("workload sets not mutually exclusive")
    if len(bag_ids) != len(completed) + len(pending) + len(review):
        raise AssertionError("workload arithmetic failed")
    if historical:
        raise AssertionError(
            f"historical_completed_in_workload non-empty: {sorted(historical)[:10]}"
        )
    if not missing <= open_bags:
        raise AssertionError("missing_from_portal introduced non-open membership")
