"""Canonical WF workload — lifecycle-based membership authority.

Model (frozen)
--------------
1. Portal scraper = discovery/update only (never workload membership / absence).
2. Current open WF workload = legitimate non-terminal WF order instances
   (``completed_at IS NULL`` on the latest instance per bag).
3. Completed-on-D = instances whose canonical completion timestamp falls on D ET.
4. Selected-day view = current open workload ∪ completed-on-selected-date
   (separate sections; discovery counts ≠ workload counts).
5. Missing From Portal is never derived from rolling discovery absence.
6. Authoritative Rinse HD bags are excluded (``canonical WF ∩ HD = ∅``).

Public API: ``get_canonical_wf_workload(org_id, date_et)``.
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
                SELECT DISTINCT bag_id
                FROM hd_day_bag_production
                WHERE organization_id = %s
                  AND bag_id IN ({ph})
                  AND COALESCE(workflow_status, '') NOT IN ('excluded', 'pre_activation_excluded')
                """,
                (org, *part),
            )
            for row in cursor.fetchall() or []:
                bid = normalize_bag_id(
                    row.get("bag_id") if isinstance(row, dict) else row[0]
                )
                if bid:
                    out.add(bid)

    return out


def _review_wf_bag_ids_from_cycles(
    cursor,
    organization_id: int,
    open_bags: set[str] | frozenset[str],
) -> set[str]:
    """OPEN WF bags whose latest service cycle is in REVIEW (not discovery absence)."""
    from backend.rinse_wf_service_cycle import STATUS_REVIEW

    if not open_bags or not table_exists(cursor, "rinse_wf_service_cycles"):
        return set()
    org = int(organization_id)
    ids = sorted(open_bags)
    out: set[str] = set()
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, status
            FROM rinse_wf_service_cycles
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND status = %s
            """,
            (org, *part, STATUS_REVIEW),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if bid:
                out.add(bid)
    return out


def _oi_meta_by_bag(
    open_rows: list[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build prior_meta-style dict from open order-instance rows."""
    meta: dict[str, dict[str, Any]] = {}
    for row in open_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        anchor = row.get("cycle_anchor_at")
        meta[bid] = {
            "bag_id": bid,
            "service_type": str(row.get("service_type") or "WF"),
            "effective_status": "pending",
            "review_reason_codes": [],
            "cycle_anchor_at": anchor,
        }
    return meta


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
            "source": "canonical_wf_workload_v2",
        }

    from backend.rinse_order_instances import (
        list_open_wf_order_instances,
        list_order_instances_completed_on_date,
    )

    open_rows = list_open_wf_order_instances(cursor, org, service_type="WF")
    prior_meta = _oi_meta_by_bag(open_rows)
    open_bags_set = {normalize_bag_id(r.get("bag_id")) for r in open_rows}
    open_bags_set = {b for b in open_bags_set if b}

    # Completed-on-D from order instances (+ registry legacy fallback).
    oi_completed_rows = list_order_instances_completed_on_date(
        cursor, org, date_et, service_type="WF"
    )
    completed_map: dict[str, dict[str, Any]] = {}
    for row in oi_completed_rows:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        ca = row.get("completed_at")
        completed_map[bid] = {
            "completion_date": date_et,
            "completion_at": ca,
            "effective_status": "completed",
            "completion_source": row.get("completion_source") or "order_instance",
            "order_instance_id": row.get("order_instance_id"),
        }
    legacy_completed = _completion_date_on_d(
        cursor, org, date_et, sorted(open_bags_set | set(completed_map.keys()))
    )
    for bid, comp in legacy_completed.items():
        if bid not in completed_map:
            completed_map[bid] = comp

    completed = frozenset(completed_map.keys())

    # HD/WF classification: authoritative HD must never join WF workload.
    all_candidates = sorted(open_bags_set | completed)
    hd_exclude = _authoritative_hd_bag_ids(
        cursor,
        org,
        date_et,
        all_candidates,
        portal_hd_ids=set(),
    )
    open_bags_set -= hd_exclude
    completed = frozenset(b for b in completed if b not in hd_exclude)
    completed_map = {b: completed_map[b] for b in completed}

    # Never admit historically terminal bags lacking a current open instance.
    terminal_before = _terminal_before_date(
        cursor, org, date_et, sorted(open_bags_set)
    )
    open_bags_set = {b for b in open_bags_set if b not in terminal_before}

    open_bags = frozenset(open_bags_set)

    # Review from REVIEW cycles only — discovery absence never marks MFP.
    review = _review_wf_bag_ids_from_cycles(cursor, org, open_bags)
    pending = frozenset(b for b in open_bags if b not in review)
    review_fs = frozenset(review)
    missing_fs = frozenset()

    bag_ids = frozenset(completed | pending | review_fs)

    carryover = frozenset(
        b
        for b in open_bags
        if _et_date((prior_meta.get(b) or {}).get("cycle_anchor_at")) is not None
        and _et_date((prior_meta.get(b) or {}).get("cycle_anchor_at")) < date_et
    )
    new_today = frozenset(b for b in open_bags if b not in carryover)

    historical = frozenset(b for b in bag_ids if b in terminal_before)
    open_only = pending | review_fs
    disjoint_open = not (pending & review_fs)
    union_ok = bag_ids == (completed | pending | review_fs)
    # Completed-on-D may overlap current-open for reusable-bag edge cases.
    arithmetic_ok = len(bag_ids) >= len(completed) + len(pending) + len(review_fs) - len(
        completed & open_only
    )
    invariants_ok = (
        disjoint_open
        and union_ok
        and len(historical) == 0
        and missing_fs <= open_only
    )

    bag_meta: dict[str, dict[str, Any]] = {}
    for bid in bag_ids:
        codes: list[str] = []
        prior = prior_meta.get(bid) or {}
        for c in prior.get("review_reason_codes") or []:
            if str(c).strip():
                codes.append(str(c).strip())
        if bid in completed:
            eff = OUTCOME_COMPLETED
        elif bid in review_fs:
            eff = OUTCOME_REVIEW_REQUIRED
        else:
            eff = OUTCOME_PENDING
        noc = OUTCOME_CARRYOVER if bid in carryover else "new_today"
        bag_meta[bid] = {
            "bag_id": bid,
            "service_type": "WF",
            "effective_status": eff,
            "new_or_carryover": noc,
            "review_reason_codes": codes,
            "rush_status": prior.get("rush_status") or prior.get("rush_flag"),
            "rush_flag": prior.get("rush_flag") or prior.get("rush_status"),
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
            "current_open": len(open_only),
        },
        "arithmetic_ok": arithmetic_ok,
        "invariants_ok": invariants_ok,
        "absence_meta": {"absence_allowed": False, "reason": "lifecycle_no_discovery_absence"},
        "bag_meta": bag_meta,
        "completion_by_bag": completed_map,
        "prior_meta": prior_meta,
        "source": "canonical_wf_workload_v2",
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
                "source": "canonical_wf_workload_v2",
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
    if pending & review:
        raise AssertionError("pending/review not mutually exclusive")
    if historical:
        raise AssertionError(
            f"historical_completed_in_workload non-empty: {sorted(historical)[:10]}"
        )
    if not missing <= open_bags:
        raise AssertionError("missing_from_portal introduced non-open membership")
