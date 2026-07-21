"""
VeeWash Shift Monitor — Step 1: authoritative daily workload from the scrape.

Simple operating model (no RFV / ledger / reconciliation dependencies):

  * The VeeWash scrape (rinse_cleaner_ticket_presence, organization_id = 3) is the
    ONLY eligibility source. A row's existence there proves the bag is a valid
    VeeWash order. `active` only says whether it is currently present (1) or has
    disappeared (0) — it never erases workload membership.
  * A bag joins a day's workload when it has a qualifying entry-rack scan
    (configurable facility_entry_racks, default ["VeeWash Dirty"]). The workload
    date is the ET date of that scan.
  * A presence-backed bag that is still active but has no entry-rack scan is an
    exception seed: MISSING_WORKLOAD_ENTRY_SCAN (never auto-assigned to today).
  * Unfinished membership carries forward each ET day until completed or resolved.
  * Completion = first Clean-rack scan (existing rule); its ET date is the
    completion date and stops future carryover.
  * A bag that established membership, then goes active=0 without a completion, is
    an exception seed: DISAPPEARED_WITHOUT_COMPLETION (never silently excluded).

Registry is used only AFTER eligibility, for operational fields — never to decide
whether a bag belongs to VeeWash.

This module is read-only reporting logic. It does not write to the DB.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_time import normalize_rack_value, system_datetime_to_et
from backend.rinse_scrape_completeness import (
    STATE_CONFIRMED,
    STATE_PENDING_CONFIRMATION,
    STATE_PRESENT,
    build_disappearance_confirmation,
)
from backend.ta_helpers import table_exists

VEEWASH_ORG_ID = 3

# Feature flag + activation date. Step 1 is authoritative ONLY from the activation
# ET date forward; earlier days are never rebuilt and their disappearances stay in
# the read-only standing backlog (no historical exceptions are created).
KEY_STEP1_ENABLED = "veewash_step1_enabled"
KEY_STEP1_ACTIVATION_DATE = "veewash_step1_activation_date"
ENV_STEP1_ENABLED = "VEEWASH_STEP1_ENABLED"
_TRUTHY = ("1", "true", "yes", "on", "y")

ENTRY_SOURCE_RACK_SCAN = "rack_scan"
ENTRY_SOURCE_MANUAL_REVIEW = "manual_exception_review"

EXC_MISSING_ENTRY_SCAN = "MISSING_WORKLOAD_ENTRY_SCAN"
EXC_DISAPPEARED_WITHOUT_COMPLETION = "DISAPPEARED_WITHOUT_COMPLETION"

ENTRY_CLASS_NEW = "new_today"
ENTRY_CLASS_CARRYOVER = "carryover"
OUTCOME_COMPLETED = "completed"
OUTCOME_PENDING = "pending"
OUTCOME_DISAPPEARED = "disappeared_exception"


def _norm_bag(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _entry_rack_keys(entry_racks: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for rack in entry_racks or ():
        norm = normalize_rack_value(rack)
        if norm:
            keys.add(norm.casefold())
    return keys


def _scan_et_date(dt: Any) -> date | None:
    """Scan timestamps are stored as America/New_York naive — ET date is the date part."""
    if isinstance(dt, datetime):
        return dt.date()
    return None


# --------------------------------------------------------------------------- #
# DB loaders (thin, read-only)                                                 #
# --------------------------------------------------------------------------- #
def load_presence_orders(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    """Authoritative VeeWash order population — one row per bag ever scraped."""
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return {}
    cursor.execute(
        """
        SELECT bag_id, active, portal_status, customer_name, service_type,
               rush_flag, estimated_delivery_date, first_seen_at, last_seen_at,
               source_batch_id
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        if not bid:
            continue
        out[bid] = {
            "bag_id": bid,
            "active": int(row.get("active") or 0),
            "portal_status": row.get("portal_status"),
            "customer_name": row.get("customer_name"),
            "service_type": (str(row.get("service_type") or "").upper() or None),
            "rush_flag": row.get("rush_flag"),
            "estimated_delivery_date": row.get("estimated_delivery_date"),
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
            "source_batch_id": row.get("source_batch_id"),
        }
    return out


def load_first_entry_scans(
    cursor, organization_id: int, *, entry_racks: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """First qualifying entry-rack scan per bag → establishes workload date."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    rack_keys = _entry_rack_keys(entry_racks)
    if not rack_keys:
        return {}
    placeholders = ",".join(["%s"] * len(rack_keys))
    cursor.execute(
        f"""
        SELECT bag_id, MIN(scanned_at_parsed) AS first_scan
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND rack IS NOT NULL AND TRIM(rack) != ''
          AND LOWER(TRIM(rack)) IN ({placeholders})
        GROUP BY bag_id
        """,
        (int(organization_id), *sorted(rack_keys)),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        ts = row.get("first_scan")
        d = _scan_et_date(ts)
        if bid and d is not None:
            out[bid] = {"first_entry_at": ts, "entry_date": d}
    return out


def load_first_completion_scans(
    cursor, organization_id: int
) -> dict[str, dict[str, Any]]:
    """First Clean-rack scan per bag → completion date/time + completing employee."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    cursor.execute(
        """
        SELECT e.bag_id, e.scanned_at_parsed AS clean_at, e.user_name
        FROM rinse_bag_scan_events e
        JOIN (
            SELECT bag_id, MIN(scanned_at_parsed) AS m
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND scanned_at_parsed IS NOT NULL
              AND rack IS NOT NULL
              AND LOWER(rack) LIKE %s
            GROUP BY bag_id
        ) f ON f.bag_id = e.bag_id AND f.m = e.scanned_at_parsed
        WHERE e.organization_id = %s
          AND e.rack IS NOT NULL
          AND LOWER(e.rack) LIKE %s
        """,
        (int(organization_id), "%clean%", int(organization_id), "%clean%"),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        ts = row.get("clean_at")
        d = _scan_et_date(ts)
        if not bid or d is None:
            continue
        # Keep earliest if the join yields duplicates (same bag, tie on time).
        if bid not in out or ts < out[bid]["completion_at"]:
            out[bid] = {
                "completion_at": ts,
                "completion_date": d,
                "completed_by": (str(row.get("user_name") or "").strip() or None),
                "completion_source": "clean_rack_scan",
            }
    return out


def load_registry_completions(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    """Operational completion field (used ONLY after scrape+scan eligibility).

    Registry ``completed_at`` captures completions however they were detected
    (Clean-rack scan AND post-processing-weight), so it is the authoritative
    completion timestamp. This is NOT an eligibility source.
    """
    if not table_exists(cursor, "rinse_bag_registry"):
        return {}
    cursor.execute(
        """
        SELECT bag_id, completed_at, first_clean_scan_at, completion_status
        FROM rinse_bag_registry
        WHERE organization_id = %s
          AND UPPER(COALESCE(completion_status, '')) = 'COMPLETED'
          AND (completed_at IS NOT NULL OR first_clean_scan_at IS NOT NULL)
        """,
        (int(organization_id),),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        ts = row.get("completed_at") or row.get("first_clean_scan_at")
        # Registry timestamps are written by jobs in UTC-naive; convert to ET for
        # the completion calendar date (scan timestamps, by contrast, are ET-naive).
        et = system_datetime_to_et(ts) if isinstance(ts, datetime) else None
        d = et.date() if et else None
        if bid and d is not None:
            out[bid] = {
                "completion_at": ts,
                "completion_date": d,
                "completed_by": None,
                "completion_source": "registry_completed_at",
            }
    return out


def merge_completions(
    registry_completions: Mapping[str, Mapping[str, Any]],
    clean_scan_completions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Canonical completion, independent of registry lifecycle status.

    The first Clean-rack scan is the ground-truth completion moment (it is exactly
    what the registry records as CLEAN_RACK_SCANNED) and it is trusted even when the
    old portal-absence job wrongly flipped the registry row to REJECTED. Registry
    ``completed_at`` is only a fallback for completions with no Clean-rack scan
    (e.g. HD or manual completions).
    """
    out: dict[str, dict[str, Any]] = {}
    for bid in set(registry_completions) | set(clean_scan_completions):
        clean = clean_scan_completions.get(bid)
        reg = registry_completions.get(bid)
        if clean:
            merged = dict(clean)
            merged.setdefault("completion_source", "clean_rack_scan")
            out[bid] = merged
        elif reg:
            out[bid] = dict(reg)
    return out


def load_excluded_not_presence_backed(
    cursor, organization_id: int, *, entry_racks: Iterable[str]
) -> list[str]:
    """Bags with an entry-rack scan but NOT in the VeeWash scrape → excluded."""
    if not table_exists(cursor, "rinse_bag_scan_events") or not table_exists(
        cursor, "rinse_cleaner_ticket_presence"
    ):
        return []
    rack_keys = _entry_rack_keys(entry_racks)
    if not rack_keys:
        return []
    placeholders = ",".join(["%s"] * len(rack_keys))
    cursor.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(e.bag_id)) AS bag_id
        FROM rinse_bag_scan_events e
        WHERE e.organization_id = %s
          AND e.rack IS NOT NULL AND TRIM(e.rack) != ''
          AND LOWER(TRIM(e.rack)) IN ({placeholders})
          AND NOT EXISTS (
            SELECT 1 FROM rinse_cleaner_ticket_presence p
            WHERE p.organization_id = %s
              AND UPPER(TRIM(p.bag_id)) = UPPER(TRIM(e.bag_id))
          )
        """,
        (int(organization_id), *sorted(rack_keys), int(organization_id)),
    )
    return sorted(
        _norm_bag(r.get("bag_id"))
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict) and _norm_bag(r.get("bag_id"))
    )


# --------------------------------------------------------------------------- #
# Pure classification                                                          #
# --------------------------------------------------------------------------- #
def classify_veewash_workload(
    *,
    selected_date_et: date,
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    entry_by_bag: Mapping[str, Mapping[str, Any]],
    completion_by_bag: Mapping[str, Mapping[str, Any]],
    disappearance_state_by_bag: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """
    Classify the presence-backed population for one ET day. Pure — no DB.

    Every presence-backed bag lands in exactly one of these mutually exclusive
    final buckets:
      new_today | carryover            (workload members for the day)
        each further tagged completed / pending / disappeared_exception
      missing_entry_scan_exception     (active, no entry scan — not yet in workload)
      not_in_workload                  (no membership relevant to this day)
    """
    D = selected_date_et
    prev_day = D - timedelta(days=1)

    rows: list[dict[str, Any]] = []
    new_today: list[str] = []
    carryover: list[str] = []
    completed_on_date: list[str] = []
    pending_end_of_date: list[str] = []
    disappeared_exception: list[str] = []
    missing_entry_exception: list[str] = []
    disappeared_prior_open: list[str] = []
    completed_without_entry_scan: list[str] = []
    pending_disappearance_confirmation: list[str] = []
    not_in_workload: list[str] = []

    for bid in sorted(presence_by_bag.keys()):
        pres = presence_by_bag[bid]
        active = int(pres.get("active") or 0)
        entry = entry_by_bag.get(bid)
        comp = completion_by_bag.get(bid)
        entry_date = entry.get("entry_date") if entry else None
        comp_date = comp.get("completion_date") if comp else None
        # Effective disappearance date: for a departed bag, the last ET day it was
        # seen in the portal. This scopes the exception to the day it went missing
        # instead of re-flooding every subsequent day's workload.
        last_seen_date = _scan_et_date(pres.get("last_seen_at"))
        # A bag is only a DISAPPEARED_WITHOUT_COMPLETION exception once its absence
        # is CONFIRMED across two consecutive trustworthy (complete) scrape runs. A
        # single missing / anomalous scrape must not create an exception: such bags
        # stay operationally Pending (state PENDING_DISAPPEARANCE_CONFIRMATION until
        # a second complete absence, or cleared if they return). When no confirmation
        # map is supplied the legacy behaviour (active==0 → disappeared) is preserved.
        disappearance_state: str | None = None
        if active == 0 and comp_date is None:
            if disappearance_state_by_bag is None:
                disappearance_state = STATE_CONFIRMED
            else:
                disappearance_state = disappearance_state_by_bag.get(bid, STATE_CONFIRMED)
        is_confirmed_disappeared = disappearance_state == STATE_CONFIRMED
        disappeared_date = last_seen_date if is_confirmed_disappeared else None

        base = {
            "bag_id": bid,
            "service_type": pres.get("service_type"),
            "rush_flag": pres.get("rush_flag"),
            "active": active,
            "portal_status": pres.get("portal_status"),
            "customer_name": pres.get("customer_name"),
            "original_entry_date": entry_date.isoformat() if entry_date else None,
            "last_seen_date": last_seen_date.isoformat() if last_seen_date else None,
            "disappearance_state": disappearance_state,
            "completion_at": comp.get("completion_at") if comp else None,
            "completed_by": comp.get("completed_by") if comp else None,
            "completion_source": comp.get("completion_source") if comp else None,
        }

        # --- COMPLETION IS AUTHORITATIVE, independent of the entry gate. ----------
        # A presence-backed bag that has a canonical completion was processed and
        # must never silently vanish from completion reporting — even if it never
        # scanned a configured entry rack, or the old portal-absence job wrongly
        # flipped its registry row to REJECTED.
        if comp_date is not None:
            has_entry = entry_date is not None
            if comp_date < D:
                not_in_workload.append(bid)
                rows.append({**base, "final_bucket": "not_in_workload",
                             "reason": "completed_before_selected_date",
                             "completion_date": comp_date.isoformat()})
                continue
            if comp_date == D:
                if not has_entry:
                    # Completed but never scanned a configured entry rack. It is NOT
                    # part of the established (entry-backed) workload — it awaits a
                    # workload-date assignment via the exception queue. Reported in
                    # its own bucket, excluded from Active Workload and official
                    # Completed totals.
                    completed_without_entry_scan.append(bid)
                    rows.append({
                        **base,
                        "entry_source": "completion_without_entry_scan",
                        "current_workload_date": D.isoformat(),
                        "outcome": OUTCOME_COMPLETED,
                        "completion_date": comp_date.isoformat(),
                        "entry_scan_missing": True,
                        "final_bucket": "completed_without_entry_scan",
                    })
                    continue
                # Established workload, completed on the selected day.
                is_new = entry_date >= D
                entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
                (new_today if is_new else carryover).append(bid)
                completed_on_date.append(bid)
                rows.append({
                    **base,
                    "entry_source": ENTRY_SOURCE_RACK_SCAN,
                    "entry_class": entry_class,
                    "current_workload_date": D.isoformat(),
                    "carried_from_date": None if is_new else prev_day.isoformat(),
                    "outcome": OUTCOME_COMPLETED,
                    "completion_date": comp_date.isoformat(),
                    "final_bucket": f"{entry_class}_{OUTCOME_COMPLETED}",
                })
                continue
            # comp_date > D: completes later. It is a pending member of D only if it
            # had already entered (Dirty scan) by D; otherwise it belongs to a later day.
            if not (entry_date is not None and entry_date <= D):
                not_in_workload.append(bid)
                rows.append({**base, "final_bucket": "not_in_workload",
                             "reason": "completes_after_selected_date_not_yet_entered",
                             "completion_date": comp_date.isoformat()})
                continue
            is_new = entry_date == D
            entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
            (new_today if is_new else carryover).append(bid)
            pending_end_of_date.append(bid)
            rows.append({**base,
                         "entry_source": ENTRY_SOURCE_RACK_SCAN,
                         "entry_class": entry_class,
                         "current_workload_date": D.isoformat(),
                         "carried_from_date": None if is_new else prev_day.isoformat(),
                         "outcome": OUTCOME_PENDING,
                         "completion_date": comp_date.isoformat(),
                         "final_bucket": f"{entry_class}_{OUTCOME_PENDING}"})
            continue

        # --- No completion. Membership depends on an established entry-rack scan. --
        if entry_date is None:
            if active == 1:
                missing_entry_exception.append(bid)
                rows.append({**base, "final_bucket": "missing_entry_scan_exception",
                             "exception_reason": EXC_MISSING_ENTRY_SCAN})
            else:
                not_in_workload.append(bid)
                rows.append({**base, "final_bucket": "not_in_workload",
                             "reason": "inactive_no_entry_scan"})
            continue

        if entry_date > D:
            not_in_workload.append(bid)
            rows.append({**base, "final_bucket": "not_in_workload",
                         "reason": "entered_after_selected_date"})
            continue

        # Disappeared without completion BEFORE the selected day → it left the
        # carryover stream when it went missing; open exception dated to that day.
        if disappeared_date is not None and disappeared_date < D:
            disappeared_prior_open.append(bid)
            rows.append({**base, "final_bucket": "disappeared_prior_open_exception",
                         "exception_reason": EXC_DISAPPEARED_WITHOUT_COMPLETION,
                         "disappeared_date": disappeared_date.isoformat()})
            continue

        # --- Member of this day's workload (entered by D, unfinished at start of D) ---
        is_new = entry_date == D
        entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
        (new_today if is_new else carryover).append(bid)
        member = {
            **base,
            "entry_source": ENTRY_SOURCE_RACK_SCAN,
            "entry_class": entry_class,
            "current_workload_date": D.isoformat(),
            "carried_from_date": None if is_new else prev_day.isoformat(),
        }
        if disappeared_date is not None and disappeared_date == D:
            outcome = OUTCOME_DISAPPEARED
            disappeared_exception.append(bid)
            member["final_bucket"] = "disappeared_without_completion_exception"
            member["exception_reason"] = EXC_DISAPPEARED_WITHOUT_COMPLETION
            member["disappeared_date"] = disappeared_date.isoformat()
        else:
            outcome = OUTCOME_PENDING
            pending_end_of_date.append(bid)
            member["final_bucket"] = f"{entry_class}_{OUTCOME_PENDING}"
            # Absent from the latest scrape but not yet confirmed (one trustworthy
            # absence, or an anomalous run). Stays in Pending; tracked internally.
            if disappearance_state == STATE_PENDING_CONFIRMATION:
                pending_disappearance_confirmation.append(bid)
                member["awaiting_disappearance_confirmation"] = True
        member["outcome"] = outcome
        rows.append(member)

    total_active_workload = len(new_today) + len(carryover)
    # Pending end of day = active workload - completed that day - disappeared (valid exclusion)
    pending_check = (
        total_active_workload - len(completed_on_date) - len(disappeared_exception)
    )
    total_operational = (
        total_active_workload
        + len(completed_without_entry_scan)
        + len(missing_entry_exception)
    )

    return {
        "selected_date_et": D.isoformat(),
        "new_today": sorted(new_today),
        "carryover": sorted(carryover),
        "completed_on_date": sorted(completed_on_date),
        "pending_end_of_date": sorted(pending_end_of_date),
        "disappeared_without_completion_exceptions": sorted(disappeared_exception),
        "missing_entry_scan_exceptions": sorted(missing_entry_exception),
        "disappeared_prior_open_exceptions": sorted(disappeared_prior_open),
        "completed_without_entry_scan": sorted(completed_without_entry_scan),
        "pending_disappearance_confirmation": sorted(pending_disappearance_confirmation),
        "not_in_workload": sorted(not_in_workload),
        "counts": {
            "new_today": len(new_today),
            "carryover": len(carryover),
            "total_active_workload": total_active_workload,
            "established_workload": total_active_workload,
            "completed_on_date": len(completed_on_date),
            "pending_end_of_date": len(pending_end_of_date),
            "disappeared_without_completion": len(disappeared_exception),
            "missing_entry_scan": len(missing_entry_exception),
            "disappeared_prior_open": len(disappeared_prior_open),
            "completed_without_entry_scan": len(completed_without_entry_scan),
            "pending_disappearance_confirmation": len(pending_disappearance_confirmation),
            "total_operational": total_operational,
            "not_in_workload": len(not_in_workload),
        },
        "reconciliation": {
            # total_active_workload = new_today + carryover (+ manual accepts — Step 2)
            "total_active_workload_equals_new_plus_carryover": (
                total_active_workload == len(new_today) + len(carryover)
            ),
            # pending = active_workload - completed - disappeared(valid exclusion)
            "pending_reconciles": pending_check == len(pending_end_of_date),
            "pending_expected": pending_check,
            "pending_actual": len(pending_end_of_date),
            # Established workload partitions into exactly completed | pending | disappeared.
            "members_partitioned": (
                total_active_workload
                == len(completed_on_date)
                + len(pending_end_of_date)
                + len(disappeared_exception)
            ),
            # total operational = established + completed-without-entry + missing-entry
            "total_operational_reconciles": (
                total_operational
                == total_active_workload
                + len(completed_without_entry_scan)
                + len(missing_entry_exception)
            ),
        },
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# Public builder                                                               #
# --------------------------------------------------------------------------- #
def build_veewash_daily_workload(
    cursor,
    organization_id: int = VEEWASH_ORG_ID,
    *,
    selected_date_et: date,
    entry_racks: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Read-only Step-1 daily workload reconciliation for one ET date."""
    racks = list(entry_racks) if entry_racks else None
    if racks is None:
        try:
            from backend.rinse_processing_settings import get_processing_settings

            racks = get_processing_settings(cursor, organization_id).get(
                "facility_entry_racks"
            ) or list(DEFAULT_FACILITY_ENTRY_RACKS)
        except Exception:
            racks = list(DEFAULT_FACILITY_ENTRY_RACKS)

    presence = load_presence_orders(cursor, organization_id)
    entry = load_first_entry_scans(cursor, organization_id, entry_racks=racks)
    completion = merge_completions(
        load_registry_completions(cursor, organization_id),
        load_first_completion_scans(cursor, organization_id),
    )

    # Confirm disappearances against the two most recent trustworthy scrape runs:
    # a single missing / anomalous scrape must not create an exception. Only bags
    # currently absent (active==0) with no canonical completion are candidates.
    candidate_absent = [
        bid
        for bid, p in presence.items()
        if int(p.get("active") or 0) == 0 and bid not in completion
    ]
    disappearance_state = build_disappearance_confirmation(
        cursor, organization_id, candidate_absent
    )
    disappearance_state_by_bag = {
        bid: info.get("state") for bid, info in disappearance_state.items()
    }

    result = classify_veewash_workload(
        selected_date_et=selected_date_et,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag=disappearance_state_by_bag,
    )
    result["disappearance_confirmation"] = disappearance_state
    result["organization_id"] = int(organization_id)
    result["entry_racks"] = racks
    result["eligible_presence_orders"] = len(presence)
    result["active_presence_orders"] = sum(
        1 for p in presence.values() if int(p.get("active") or 0) == 1
    )
    result["excluded_not_presence_backed"] = load_excluded_not_presence_backed(
        cursor, organization_id, entry_racks=racks
    )
    result["rush_split"] = _rush_split(result["rows"])
    return result


# --------------------------------------------------------------------------- #
# Feature flag + activation date                                               #
# --------------------------------------------------------------------------- #
def today_et() -> date:
    """Current ET calendar date (system clock is UTC-naive)."""
    et = system_datetime_to_et(datetime.utcnow())
    return et.date() if et else datetime.utcnow().date()


def is_step1_enabled(cursor, organization_id: int = VEEWASH_ORG_ID) -> bool:
    """Env override wins; otherwise the per-org system_settings flag (default off)."""
    env = os.environ.get(ENV_STEP1_ENABLED)
    if env is not None:
        return env.strip().lower() in _TRUTHY
    try:
        from backend.rinse_processing_settings import _get_setting

        return str(_get_setting(cursor, organization_id, KEY_STEP1_ENABLED) or "").strip().lower() in _TRUTHY
    except Exception:
        return False


def get_step1_activation_date(cursor, organization_id: int = VEEWASH_ORG_ID) -> date | None:
    try:
        from backend.rinse_processing_settings import _get_setting

        raw = _get_setting(cursor, organization_id, KEY_STEP1_ACTIVATION_DATE)
        if raw and str(raw).strip():
            return date.fromisoformat(str(raw)[:10])
    except Exception:
        pass
    return None


def enable_step1_today(
    cursor, organization_id: int = VEEWASH_ORG_ID, *, activation_date: date | None = None
) -> date:
    """Turn Step 1 on and pin the activation ET date (defaults to today)."""
    from backend.rinse_processing_settings import _set_setting

    d = activation_date or today_et()
    _set_setting(cursor, organization_id, KEY_STEP1_ENABLED, "true")
    _set_setting(cursor, organization_id, KEY_STEP1_ACTIVATION_DATE, d.isoformat())
    return d


def disable_step1(cursor, organization_id: int = VEEWASH_ORG_ID) -> None:
    from backend.rinse_processing_settings import _set_setting

    _set_setting(cursor, organization_id, KEY_STEP1_ENABLED, "false")


# --------------------------------------------------------------------------- #
# Today-scoped build + end-of-day validation                                   #
# --------------------------------------------------------------------------- #
def build_today_veewash_workload(
    cursor,
    organization_id: int = VEEWASH_ORG_ID,
    *,
    entry_racks: Iterable[str] | None = None,
    today_override: date | None = None,
) -> dict[str, Any]:
    """Step-1 build for TODAY only, with the end-of-day validation partition.

    Read-only. Historical days are never rebuilt: disappearances before the
    activation date remain in the standing backlog and are not turned into new
    exceptions here.
    """
    D = today_override or today_et()
    activation = get_step1_activation_date(cursor, organization_id) or D
    res = build_veewash_daily_workload(
        cursor, organization_id, selected_date_et=D, entry_racks=entry_racks
    )
    res["step1_enabled"] = is_step1_enabled(cursor, organization_id)
    res["activation_date_et"] = activation.isoformat()
    res["is_activation_day_or_later"] = D >= activation
    res["today_validation"] = build_today_validation(res, selected_date_et=D)
    return res


def build_today_validation(result: Mapping[str, Any], *, selected_date_et: date) -> dict[str, Any]:
    """Partition today's operational orders into exactly one path each.

    Operational paths (mutually exclusive):
      completed_entered_via_dirty | completed_without_entry_scan | pending |
      disappeared_without_completion | missing_entry_scan_exception

    Historical disappearances (standing backlog) and prior-completed-still-present
    rows are reported for context but are NOT part of today's operational set.
    """
    completed = set(result.get("completed_on_date") or [])
    cwo = set(result.get("completed_without_entry_scan") or [])
    paths = {
        "completed_entered_via_dirty": sorted(completed - cwo),
        "completed_without_entry_scan": sorted(cwo),
        "pending": sorted(result.get("pending_end_of_date") or []),
        "disappeared_without_completion": sorted(
            result.get("disappeared_without_completion_exceptions") or []
        ),
        "missing_entry_scan_exception": sorted(
            result.get("missing_entry_scan_exceptions") or []
        ),
    }
    all_ids: list[str] = []
    for ids in paths.values():
        all_ids.extend(ids)
    operational_total = len(all_ids)
    unique_total = len(set(all_ids))

    counts = result.get("counts") or {}
    established = int(counts.get("total_active_workload") or 0)
    completed = len(paths["completed_entered_via_dirty"])
    pending = len(paths["pending"])
    disappeared = len(paths["disappeared_without_completion"])
    completed_awaiting = len(paths["completed_without_entry_scan"])
    missing_entry = len(paths["missing_entry_scan_exception"])
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "total_scrape_orders_all_history": result.get("eligible_presence_orders"),
        "active_in_latest_scrape": result.get("active_presence_orders"),
        "total_operational_orders": operational_total,
        # Established (entry-backed) workload and its outcome partition.
        "established_workload": established,
        "new_today": counts.get("new_today"),
        "carryover": counts.get("carryover"),
        "established_outcomes": {
            "completed": completed,
            "pending": pending,
            "disappeared_exception": disappeared,
        },
        # Non-established operational buckets (kept OUT of established workload).
        "completed_awaiting_workload_assignment": completed_awaiting,
        "missing_entry_scan_exception": missing_entry,
        "operational_paths": {k: len(v) for k, v in paths.items()},
        "operational_path_bag_ids": paths,
        # Untouched historical context.
        "standing_unresolved_backlog": len(
            result.get("disappeared_prior_open_exceptions") or []
        ),
        "excluded_not_presence_backed": len(result.get("excluded_not_presence_backed") or []),
        "invariants": {
            "every_order_exactly_one_operational_path": unique_total == operational_total,
            "active_workload_equals_new_plus_carryover": (
                established
                == (counts.get("new_today") or 0) + (counts.get("carryover") or 0)
            ),
            # Established workload = completed(entry) + pending + disappeared.
            "established_outcomes_partition": established
            == completed + pending + disappeared,
            # total operational = established + completed-awaiting + missing-entry.
            "total_operational_reconciles": operational_total
            == established + completed_awaiting + missing_entry,
            # The completed-awaiting bag is NOT double-counted inside missing-entry.
            "no_double_count_completed_vs_missing_entry": not (
                set(paths["completed_without_entry_scan"])
                & set(paths["missing_entry_scan_exception"])
            ),
        },
    }


def build_step1_headline_summary(
    result: Mapping[str, Any], *, selected_date_et: date, activation_date: date
) -> dict[str, Any]:
    """Headline summary for the Shift Monitor, segmented by Rush / Non-Rush.

    Every category is provided per segment (all / rush / non_rush) with bag-ID lists
    so the UI can render authoritative, filter-correct totals without shipping the
    full row set. The historical backlog is intentionally NOT segmented — it is a
    separate read-only concern.
    """
    rows = result.get("rows") or []
    rush_by_bag = {
        r.get("bag_id"): _rush_bucket(r.get("rush_flag")) for r in rows if r.get("bag_id")
    }

    def _seg(segment: str) -> dict[str, Any]:
        def f(key: str) -> list[str]:
            ids = result.get(key) or []
            if segment == "all":
                return sorted(ids)
            return sorted(b for b in ids if rush_by_bag.get(b) == segment)

        new = f("new_today")
        carry = f("carryover")
        completed = f("completed_on_date")
        pending = f("pending_end_of_date")
        disappeared = f("disappeared_without_completion_exceptions")
        missing = f("missing_entry_scan_exceptions")
        cwo = f("completed_without_entry_scan")
        active = len(new) + len(carry)
        exceptions_total = len(disappeared) + len(missing) + len(cwo)
        return {
            "new_today": len(new),
            "carryover": len(carry),
            "active_workload": active,
            "completed": len(completed),
            "pending": len(pending),
            "exceptions": {
                "disappeared_without_completion": len(disappeared),
                "missing_workload_entry_scan": len(missing),
                "completed_awaiting_workload_assignment": len(cwo),
                "total": exceptions_total,
            },
            "total_operational_orders": active + len(missing) + len(cwo),
            "bag_ids": {
                "new_today": new,
                "carryover": carry,
                "completed": completed,
                "pending": pending,
                "disappeared_without_completion": disappeared,
                "missing_workload_entry_scan": missing,
                "completed_awaiting_workload_assignment": cwo,
            },
        }

    segments = {"all": _seg("all"), "rush": _seg("RUSH"), "non_rush": _seg("NON_RUSH")}
    a = segments["all"]
    exc = a["exceptions"]
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "activation_date_et": activation_date.isoformat(),
        "new_today": a["new_today"],
        "carryover": a["carryover"],
        "active_workload": a["active_workload"],
        "completed": a["completed"],
        "pending": a["pending"],
        "exceptions": exc,
        "total_operational_orders": a["total_operational_orders"],
        "historical_unresolved_backlog": len(
            result.get("disappeared_prior_open_exceptions") or []
        ),
        "historical_unresolved_backlog_bag_ids": sorted(
            result.get("disappeared_prior_open_exceptions") or []
        ),
        "segments": segments,
        "reconciliation_lines": {
            "active_workload": (
                f"Active Workload {a['active_workload']} = Completed {a['completed']}"
                f" + Pending {a['pending']}"
                f" + Disappeared {exc['disappeared_without_completion']}"
            ),
            "total_operational": (
                f"Total Operational Orders {a['total_operational_orders']}"
                f" = Active Workload {a['active_workload']}"
                f" + Missing Entry {exc['missing_workload_entry_scan']}"
                f" + Completed Awaiting Assignment {exc['completed_awaiting_workload_assignment']}"
            ),
        },
    }


def _rush_bucket(rush_flag: Any) -> str:
    v = str(rush_flag or "").strip().lower()
    if not v:
        return "UNKNOWN"
    if "non" in v:  # "non-rush" / "non rush"
        return "NON_RUSH"
    if "rush" in v or v in ("1", "true", "yes", "y"):
        return "RUSH"
    return "NON_RUSH"


def _rush_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rush / Non-Rush breakdown of the active workload (new + carryover)."""
    members = [
        r for r in rows
        if str(r.get("entry_class") or "") in (ENTRY_CLASS_NEW, ENTRY_CLASS_CARRYOVER)
    ]
    out = {"RUSH": [], "NON_RUSH": [], "UNKNOWN": []}
    for r in members:
        out[_rush_bucket(r.get("rush_flag"))].append(r.get("bag_id"))
    return {
        "rush_total": len(out["RUSH"]),
        "non_rush_total": len(out["NON_RUSH"]),
        "unknown_total": len(out["UNKNOWN"]),
        "rush_bag_ids": sorted(b for b in out["RUSH"] if b),
        "non_rush_bag_ids": sorted(b for b in out["NON_RUSH"] if b),
        "unknown_bag_ids": sorted(b for b in out["UNKNOWN"] if b),
    }
