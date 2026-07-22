"""
VeeWash Shift Monitor — Step 1: authoritative daily workload from At-Vendor scrape.

Operating model:

  * Eligibility: organization_id = 3 AND portal_status = at_vendor.
    RFV (ready_for_vendor) is inactive and never loaded into this workload.
  * Workload entry (WF and HD): first configured Dirty rack scan (facility_entry_racks).
    Service type comes from presence (WF vs HD). Rush/Non-Rush filters within service
    and never reclassifies HD as WF.
  * Recognized-entry check for COMPLETED_WITHOUT_RECOGNIZED_ENTRY:
      WF → Dirty required; HD → workitems-added required (in addition to Dirty membership).
    When completed without the service-appropriate signal, bag enters Active as Review Required.
  * workitems-added is NOT a WF workload entry event. Recognized entry:
      WF → first configured Dirty rack scan
      HD → first workitems-added scan (Dirty is not HD entry for CWO checks)
  * Completion: evaluate_bag_completion_v2 (canonical production resolver).
  * Review Required (manager-facing, reason_codes, one count per bag) includes:
      DISAPPEARED_WITHOUT_COMPLETION
      COMPLETED_WITHOUT_RECOGNIZED_ENTRY (was hidden CWO — now in Active as Review)
      WF_ZERO_OR_MISSING_POST_WEIGHT (WF only)
      SERVICE_CLASSIFICATION_MISMATCH / COMPLETION_DETAILS_MISSING (extensible)
  * Dashboard outcome priority: Review Required > Completed > Pending.
    Active = Completed + Pending + Review Required (no double count).

This module is read-only reporting logic. It does not write to the DB.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
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

KEY_STEP1_ENABLED = "veewash_step1_enabled"
KEY_STEP1_ACTIVATION_DATE = "veewash_step1_activation_date"
ENV_STEP1_ENABLED = "VEEWASH_STEP1_ENABLED"
_TRUTHY = ("1", "true", "yes", "on", "y")

PORTAL_AT_VENDOR = "at_vendor"
PORTAL_RFV = "ready_for_vendor"

ENTRY_SOURCE_DIRTY = "facility_dirty_scan"
# Backward-compatible aliases (Dirty is the sole workload entry for WF and HD).
ENTRY_SOURCE_WF_DIRTY = ENTRY_SOURCE_DIRTY
ENTRY_SOURCE_HD_DIRTY = ENTRY_SOURCE_DIRTY
ENTRY_SOURCE_HD_WIA = "hd_workitems_added"  # retained for tests/legacy; not used for entry
ENTRY_SOURCE_MANUAL_REVIEW = "manual_exception_review"

EXC_DISAPPEARED_WITHOUT_COMPLETION = "DISAPPEARED_WITHOUT_COMPLETION"
# Retained for import compatibility; no longer a user-facing operational category.
EXC_MISSING_ENTRY_SCAN = "MISSING_WORKLOAD_ENTRY_SCAN"

REASON_DISAPPEARED_WITHOUT_COMPLETION = "DISAPPEARED_WITHOUT_COMPLETION"
REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY = "COMPLETED_WITHOUT_RECOGNIZED_ENTRY"
REASON_WF_ZERO_OR_MISSING_POST_WEIGHT = "WF_ZERO_OR_MISSING_POST_WEIGHT"
# Back-compat alias for earlier Step-1 reason code string.
REASON_WF_ZERO_OR_MISSING_WEIGHT = REASON_WF_ZERO_OR_MISSING_POST_WEIGHT
REASON_WF_BULK_WORKITEM_REVIEW = "WF_BULK_WORKITEM_REVIEW"

REASON_SERVICE_CLASSIFICATION_MISMATCH = "SERVICE_CLASSIFICATION_MISMATCH"
REASON_COMPLETION_DETAILS_MISSING = "COMPLETION_DETAILS_MISSING"

REVIEW_REASON_CODES = (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    REASON_WF_BULK_WORKITEM_REVIEW,
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    REASON_COMPLETION_DETAILS_MISSING,
)

ENTRY_CLASS_NEW = "new_today"
ENTRY_CLASS_CARRYOVER = "carryover"
OUTCOME_COMPLETED = "completed"
OUTCOME_PENDING = "pending"
OUTCOME_DISAPPEARED = "disappeared_exception"
OUTCOME_REVIEW_REQUIRED = "review_required"

SERVICE_WF = "WF"
SERVICE_HD = "HD"


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


def _presence_et_date(dt: Any) -> date | None:
    """Presence first/last_seen timestamps are system UTC-naive → convert to ET date."""
    if not isinstance(dt, datetime):
        return None
    et = system_datetime_to_et(dt)
    return et.date() if et else None


def _service_of(pres: Mapping[str, Any]) -> str:
    return str(pres.get("service_type") or "").strip().upper()


def _is_rfv_status(portal_status: Any) -> bool:
    return str(portal_status or "").strip().lower() in {PORTAL_RFV, "rfv"}


def _is_at_vendor_status(portal_status: Any) -> bool:
    return str(portal_status or "").strip().lower() == PORTAL_AT_VENDOR


# --------------------------------------------------------------------------- #
# DB loaders (thin, read-only)                                                 #
# --------------------------------------------------------------------------- #
def load_presence_orders(
    cursor,
    organization_id: int,
    *,
    at_vendor_only: bool = True,
) -> dict[str, dict[str, Any]]:
    """Load presence rows for the org.

    Default ``at_vendor_only=True``: RFV rows are never loaded into Step-1 (RFV is
    inactive until explicitly re-enabled). Pass ``at_vendor_only=False`` only for
    offline diagnostics that intentionally inspect historical RFV rows.
    """
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return {}
    if at_vendor_only:
        cursor.execute(
            """
            SELECT bag_id, active, portal_status, customer_name, service_type,
                   rush_flag, estimated_delivery_date, first_seen_at, last_seen_at,
                   source_batch_id
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s
              AND LOWER(TRIM(COALESCE(portal_status, ''))) = %s
            """,
            (int(organization_id), PORTAL_AT_VENDOR),
        )
    else:
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


def split_presence_at_vendor_vs_rfv(
    presence_by_bag: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return (at_vendor_population, sorted RFV-excluded bag IDs).

    Processing eligibility requires portal_status = at_vendor.
    RFV (ready_for_vendor) is listed explicitly for reconciliation.
    Any other non-at_vendor status is dropped silently from the population
    (not counted as RFV).
    """
    at_vendor: dict[str, dict[str, Any]] = {}
    rfv_excluded: list[str] = []
    for bid, row in presence_by_bag.items():
        if _is_at_vendor_status(row.get("portal_status")):
            at_vendor[bid] = dict(row)
        elif _is_rfv_status(row.get("portal_status")):
            rfv_excluded.append(bid)
    return at_vendor, sorted(rfv_excluded)


def load_first_dirty_scans(
    cursor, organization_id: int, *, entry_racks: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """First configured Dirty / facility-entry rack scan per bag."""
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


# Backward-compatible alias used by older callers / tests.
def load_first_entry_scans(
    cursor, organization_id: int, *, entry_racks: Iterable[str]
) -> dict[str, dict[str, Any]]:
    return load_first_dirty_scans(cursor, organization_id, entry_racks=entry_racks)


def load_first_workitems_added_scans(
    cursor, organization_id: int
) -> dict[str, dict[str, Any]]:
    """First workitems-added scan per bag — HD recognized workload entry."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    cursor.execute(
        """
        SELECT bag_id, MIN(scanned_at_parsed) AS first_scan
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND LOWER(TRIM(COALESCE(purpose, ''))) IN ('workitems-added', 'workitems_added')
        GROUP BY bag_id
        """,
        (int(organization_id),),
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


def build_dirty_entry_map(
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    dirty_by_bag: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """WF and HD enter Active workload via first configured VeeWash Dirty scan."""
    out: dict[str, dict[str, Any]] = {}
    for bid, pres in presence_by_bag.items():
        svc = _service_of(pres)
        if svc not in (SERVICE_WF, SERVICE_HD):
            continue
        dirty = dirty_by_bag.get(bid)
        if not dirty:
            continue
        out[bid] = {
            **dict(dirty),
            "entry_source": ENTRY_SOURCE_DIRTY,
            "service_type": svc,
        }
    return out


def build_service_entry_map(
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    dirty_by_bag: Mapping[str, Mapping[str, Any]],
    wia_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Dirty membership for WF/HD. ``wia_by_bag`` used by callers for HD CWO checks."""
    _ = wia_by_bag
    return build_dirty_entry_map(presence_by_bag, dirty_by_bag=dirty_by_bag)


def _has_recognized_entry_for_service(
    svc: str,
    *,
    dirty_entry: Mapping[str, Any] | None,
    wia_entry: Mapping[str, Any] | None,
) -> bool:
    """Service-specific recognized entry for CWO / Review Required."""
    if svc == SERVICE_HD:
        return wia_entry is not None and wia_entry.get("entry_date") is not None
    # WF (and unknown): Dirty
    return dirty_entry is not None and dirty_entry.get("entry_date") is not None


def load_canonical_completions_v2(
    cursor, organization_id: int, bag_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Canonical completions via evaluate_bag_completion_v2 for the given bags."""
    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}

    # Bound IN lists — never full-table scan all org scan events.
    id_set = set(ids)
    by_bag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunk_size = 400
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            SELECT bag_id, rack, purpose, scanned_at_parsed, user_name, weight_lbs
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed IS NOT NULL
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *chunk),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = _norm_bag(row.get("bag_id"))
            if bid not in id_set:
                continue
            by_bag[bid].append(
                {
                    "rack": row.get("rack"),
                    "purpose": row.get("purpose"),
                    "scanned_at_parsed": row.get("scanned_at_parsed"),
                    "user_name": row.get("user_name"),
                    "weight_lbs": row.get("weight_lbs"),
                }
            )

    out: dict[str, dict[str, Any]] = {}
    for bid, timeline in by_bag.items():
        result = evaluate_bag_completion_v2(timeline)
        if not result.completed or result.completion_at is None:
            continue
        d = _scan_et_date(result.completion_at)
        if d is None:
            continue
        out[bid] = {
            "completion_at": result.completion_at,
            "completion_date": d,
            "completed_by": (str(result.completion_user or "").strip() or None),
            "completion_source": f"evaluate_bag_completion_v2:{result.completion_kind or 'completed'}",
            "completion_kind": result.completion_kind,
            "via_clean_rack": bool(result.via_clean_rack),
        }
    return out


def load_first_completion_scans(
    cursor, organization_id: int
) -> dict[str, dict[str, Any]]:
    """Deprecated Clean-only loader — retained for tests/legacy callers."""
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
        if bid not in out or ts < out[bid]["completion_at"]:
            out[bid] = {
                "completion_at": ts,
                "completion_date": d,
                "completed_by": (str(row.get("user_name") or "").strip() or None),
                "completion_source": "clean_rack_scan",
            }
    return out


def load_registry_completions(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    """Deprecated registry COMPLETED fallback — retained for tests/legacy callers."""
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
    """Legacy merge retained for unit tests; production uses load_canonical_completions_v2."""
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
    """Bags with an entry-rack scan but NOT in the At-Vendor scrape → excluded."""
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
              AND LOWER(COALESCE(p.portal_status, '')) = %s
          )
        """,
        (int(organization_id), *sorted(rack_keys), int(organization_id), PORTAL_AT_VENDOR),
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
    Classify the At-Vendor population for one ET day. Pure — no DB.

    Presence must already exclude RFV. Entry must already be service-specific.
    Completion must already come from evaluate_bag_completion_v2 (or a test double).
    """
    D = selected_date_et
    prev_day = D - timedelta(days=1)

    rows: list[dict[str, Any]] = []
    new_today: list[str] = []
    carryover: list[str] = []
    completed_on_date: list[str] = []
    pending_end_of_date: list[str] = []
    disappeared_exception: list[str] = []
    disappeared_prior_open: list[str] = []
    completed_without_recognized_entry: list[str] = []
    pending_disappearance_confirmation: list[str] = []
    not_in_workload: list[str] = []
    # Kept empty for API compatibility — no longer a user-facing category.
    missing_entry_exception: list[str] = []

    for bid in sorted(presence_by_bag.keys()):
        pres = presence_by_bag[bid]
        active = int(pres.get("active") or 0)
        entry = entry_by_bag.get(bid)
        comp = completion_by_bag.get(bid)
        entry_date = entry.get("entry_date") if entry else None
        entry_source = (entry.get("entry_source") if entry else None) or ENTRY_SOURCE_WF_DIRTY
        comp_date = comp.get("completion_date") if comp else None
        last_seen_date = _presence_et_date(pres.get("last_seen_at")) or _scan_et_date(
            pres.get("last_seen_at")
        )

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
            "service_type": _service_of(pres) or pres.get("service_type"),
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
            "completion_kind": comp.get("completion_kind") if comp else None,
        }

        # --- Canonical completion is authoritative. -----------------------------
        if comp_date is not None:
            has_entry = entry_date is not None
            if comp_date < D:
                not_in_workload.append(bid)
                rows.append(
                    {
                        **base,
                        "final_bucket": "not_in_workload",
                        "reason": "completed_before_selected_date",
                        "completion_date": comp_date.isoformat(),
                    }
                )
                continue
            if comp_date == D:
                if not has_entry:
                    # Proven completion without recognized WF Dirty / HD WIA entry.
                    # Internal reconciliation only — not New Today, not Review Required.
                    completed_without_recognized_entry.append(bid)
                    rows.append(
                        {
                            **base,
                            "entry_source": "completion_without_recognized_entry",
                            "current_workload_date": D.isoformat(),
                            "outcome": OUTCOME_COMPLETED,
                            "completion_date": comp_date.isoformat(),
                            "entry_scan_missing": True,
                            "final_bucket": "completed_without_recognized_entry",
                        }
                    )
                    continue
                is_new = entry_date >= D
                entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
                (new_today if is_new else carryover).append(bid)
                completed_on_date.append(bid)
                rows.append(
                    {
                        **base,
                        "entry_source": entry_source,
                        "entry_class": entry_class,
                        "current_workload_date": D.isoformat(),
                        "carried_from_date": None if is_new else prev_day.isoformat(),
                        "outcome": OUTCOME_COMPLETED,
                        "completion_date": comp_date.isoformat(),
                        "final_bucket": f"{entry_class}_{OUTCOME_COMPLETED}",
                    }
                )
                continue
            # Completes after D — pending member of D only if already entered by D.
            if not (entry_date is not None and entry_date <= D):
                not_in_workload.append(bid)
                rows.append(
                    {
                        **base,
                        "final_bucket": "not_in_workload",
                        "reason": "completes_after_selected_date_not_yet_entered",
                        "completion_date": comp_date.isoformat(),
                    }
                )
                continue
            is_new = entry_date == D
            entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
            (new_today if is_new else carryover).append(bid)
            pending_end_of_date.append(bid)
            rows.append(
                {
                    **base,
                    "entry_source": entry_source,
                    "entry_class": entry_class,
                    "current_workload_date": D.isoformat(),
                    "carried_from_date": None if is_new else prev_day.isoformat(),
                    "outcome": OUTCOME_PENDING,
                    "completion_date": comp_date.isoformat(),
                    "final_bucket": f"{entry_class}_{OUTCOME_PENDING}",
                }
            )
            continue

        # --- No completion. Membership requires a recognized service entry. ------
        if entry_date is None:
            # Not a manager-facing exception. At-Vendor without recognized entry
            # is simply outside today's processing workload (HD pending WIA, etc.).
            not_in_workload.append(bid)
            rows.append(
                {
                    **base,
                    "final_bucket": "not_in_workload",
                    "reason": "no_recognized_service_entry",
                }
            )
            continue

        if entry_date > D:
            not_in_workload.append(bid)
            rows.append(
                {
                    **base,
                    "final_bucket": "not_in_workload",
                    "reason": "entered_after_selected_date",
                }
            )
            continue

        if disappeared_date is not None and disappeared_date < D:
            disappeared_prior_open.append(bid)
            rows.append(
                {
                    **base,
                    "final_bucket": "disappeared_prior_open_exception",
                    "exception_reason": EXC_DISAPPEARED_WITHOUT_COMPLETION,
                    "disappeared_date": disappeared_date.isoformat(),
                }
            )
            continue

        is_new = entry_date == D
        entry_class = ENTRY_CLASS_NEW if is_new else ENTRY_CLASS_CARRYOVER
        (new_today if is_new else carryover).append(bid)
        member = {
            **base,
            "entry_source": entry_source,
            "entry_class": entry_class,
            "current_workload_date": D.isoformat(),
            "carried_from_date": None if is_new else prev_day.isoformat(),
        }
        if disappeared_date is not None and disappeared_date == D:
            outcome = OUTCOME_REVIEW_REQUIRED
            disappeared_exception.append(bid)
            member["final_bucket"] = "review_required"
            member["exception_reason"] = EXC_DISAPPEARED_WITHOUT_COMPLETION
            member["disappeared_date"] = disappeared_date.isoformat()
        else:
            outcome = OUTCOME_PENDING
            pending_end_of_date.append(bid)
            member["final_bucket"] = f"{entry_class}_{OUTCOME_PENDING}"
            if disappearance_state == STATE_PENDING_CONFIRMATION:
                pending_disappearance_confirmation.append(bid)
                member["awaiting_disappearance_confirmation"] = True
        member["outcome"] = outcome
        rows.append(member)

    total_active_workload = len(new_today) + len(carryover)
    pending_check = (
        total_active_workload - len(completed_on_date) - len(disappeared_exception)
    )

    return {
        "selected_date_et": D.isoformat(),
        "new_today": sorted(new_today),
        "carryover": sorted(carryover),
        "completed_on_date": sorted(completed_on_date),
        "pending_end_of_date": sorted(pending_end_of_date),
        "disappeared_without_completion_exceptions": sorted(disappeared_exception),
        "review_required": sorted(disappeared_exception),
        "missing_entry_scan_exceptions": sorted(missing_entry_exception),
        "disappeared_prior_open_exceptions": sorted(disappeared_prior_open),
        "completed_without_entry_scan": sorted(completed_without_recognized_entry),
        "completed_without_recognized_entry": sorted(completed_without_recognized_entry),
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
            "review_required": len(disappeared_exception),
            "missing_entry_scan": 0,
            "disappeared_prior_open": len(disappeared_prior_open),
            "completed_without_recognized_entry": len(completed_without_recognized_entry),
            "completed_without_entry_scan": len(completed_without_recognized_entry),
            "pending_disappearance_confirmation": len(pending_disappearance_confirmation),
            # Operational set = established workload only (entry-backed).
            "total_operational": total_active_workload,
            "not_in_workload": len(not_in_workload),
        },
        "reconciliation": {
            "total_active_workload_equals_new_plus_carryover": (
                total_active_workload == len(new_today) + len(carryover)
            ),
            "pending_reconciles": pending_check == len(pending_end_of_date),
            "pending_expected": pending_check,
            "pending_actual": len(pending_end_of_date),
            "members_partitioned": (
                total_active_workload
                == len(completed_on_date)
                + len(pending_end_of_date)
                + len(disappeared_exception)
            ),
            "active_equals_completed_plus_pending_plus_review": (
                total_active_workload
                == len(completed_on_date)
                + len(pending_end_of_date)
                + len(disappeared_exception)
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

    # RFV is inactive: never load ready_for_vendor presence into Step-1.
    presence = load_presence_orders(cursor, organization_id, at_vendor_only=True)
    rfv_excluded: list[str] = []

    dirty = load_first_dirty_scans(cursor, organization_id, entry_racks=racks)
    wia = load_first_workitems_added_scans(cursor, organization_id)
    entry = build_service_entry_map(
        presence, dirty_by_bag=dirty, wia_by_bag=wia
    )

    completion = load_canonical_completions_v2(cursor, organization_id, presence.keys())

    candidate_absent = [
        bid
        for bid, p in presence.items()
        if int(p.get("active") or 0) == 0 and bid not in completion
    ]
    disappearance_state = build_disappearance_confirmation(
        cursor, organization_id, candidate_absent, portal_status=PORTAL_AT_VENDOR
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

    from backend.rinse_veewash_review import (
        expand_review_required,
        load_bag_weight_map,
    )

    weight_ids = sorted(
        set(result.get("new_today") or [])
        | set(result.get("carryover") or [])
        | set(result.get("completed_on_date") or [])
        | set(result.get("completed_without_recognized_entry") or [])
        | set(presence.keys())
    )
    weights = load_bag_weight_map(cursor, organization_id, weight_ids)

    from backend.rinse_bulk_workitems import (
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )

    bulk_scans = load_bulk_workitem_scan_map(cursor, organization_id, weight_ids)
    bulk_resolutions = load_bulk_resolutions(
        cursor, organization_id, selected_date_et, weight_ids
    )
    bulk_lines = load_bag_bulk_lines(cursor, organization_id, selected_date_et, weight_ids)

    result = expand_review_required(
        result,
        selected_date_et=selected_date_et,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag=wia,
        weight_by_bag=weights,
        bulk_scan_by_bag=bulk_scans,
        bulk_resolution_by_bag=bulk_resolutions,
        bulk_lines_by_bag=bulk_lines,
    )
    result["disappearance_confirmation"] = disappearance_state
    result["organization_id"] = int(organization_id)
    result["entry_racks"] = racks
    result["eligible_presence_orders"] = len(presence)
    result["active_presence_orders"] = sum(
        1 for p in presence.values() if int(p.get("active") or 0) == 1
    )
    result["rfv_excluded"] = rfv_excluded
    result["rfv_excluded_count"] = len(rfv_excluded)
    result["excluded_not_presence_backed"] = load_excluded_not_presence_backed(
        cursor, organization_id, entry_racks=racks
    )
    result["rush_split"] = _rush_split(result["rows"])
    result["service_split"] = _service_split(result)
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

        return str(
            _get_setting(cursor, organization_id, KEY_STEP1_ENABLED) or ""
        ).strip().lower() in _TRUTHY
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
    """Step-1 build for TODAY only, with the end-of-day validation partition."""
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
    """Partition today's entry-backed operational orders into exactly one path each."""
    completed = set(result.get("completed_on_date") or [])
    cwo = set(
        result.get("completed_without_recognized_entry")
        or result.get("completed_without_entry_scan")
        or []
    )
    paths = {
        "completed_entered": sorted(completed),
        "completed_without_recognized_entry": sorted(cwo),
        "pending": sorted(result.get("pending_end_of_date") or []),
        "review_required": sorted(
            result.get("review_required")
            or result.get("disappeared_without_completion_exceptions")
            or []
        ),
    }
    # Operational (entry-backed) paths exclude completed_without_recognized_entry.
    operational_ids = (
        paths["completed_entered"] + paths["pending"] + paths["review_required"]
    )
    operational_total = len(operational_ids)
    unique_total = len(set(operational_ids))

    counts = result.get("counts") or {}
    established = int(counts.get("total_active_workload") or 0)
    completed_n = len(paths["completed_entered"])
    pending = len(paths["pending"])
    review = len(paths["review_required"])
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "total_scrape_orders_all_history": result.get("eligible_presence_orders"),
        "active_in_latest_scrape": result.get("active_presence_orders"),
        "total_operational_orders": operational_total,
        "established_workload": established,
        "new_today": counts.get("new_today"),
        "carryover": counts.get("carryover"),
        "established_outcomes": {
            "completed": completed_n,
            "pending": pending,
            "review_required": review,
        },
        "completed_without_recognized_entry": len(paths["completed_without_recognized_entry"]),
        "completed_awaiting_workload_assignment": 0,
        "missing_entry_scan_exception": 0,
        "rfv_excluded": len(result.get("rfv_excluded") or []),
        "operational_paths": {k: len(v) for k, v in paths.items()},
        "operational_path_bag_ids": paths,
        "standing_unresolved_backlog": 0,
        "excluded_not_presence_backed": len(result.get("excluded_not_presence_backed") or []),
        "invariants": {
            "every_order_exactly_one_operational_path": unique_total == operational_total,
            "active_workload_equals_new_plus_carryover": (
                established
                == (counts.get("new_today") or 0) + (counts.get("carryover") or 0)
            ),
            "established_outcomes_partition": established
            == completed_n + pending + review,
            "total_operational_reconciles": operational_total == established,
        },
    }


def build_step1_headline_summary(
    result: Mapping[str, Any], *, selected_date_et: date, activation_date: date
) -> dict[str, Any]:
    """Headline summary: WF/HD × Rush/Non-Rush, simplified exceptions."""
    rows = result.get("rows") or []
    meta_by_bag = {
        r.get("bag_id"): {
            "rush": _rush_bucket(r.get("rush_flag")),
            "service": str(r.get("service_type") or "").upper(),
        }
        for r in rows
        if r.get("bag_id")
    }

    def _filter(ids: list[str], *, service: str | None = None, rush: str | None = None) -> list[str]:
        out = []
        for bid in ids:
            m = meta_by_bag.get(bid) or {}
            if service and m.get("service") != service:
                continue
            if rush and m.get("rush") != rush:
                continue
            out.append(bid)
        return sorted(out)

    def _seg(ids_new, ids_carry, ids_completed, ids_pending, ids_review) -> dict[str, Any]:
        active = len(ids_new) + len(ids_carry)
        return {
            "new_today": len(ids_new),
            "carryover": len(ids_carry),
            "active_workload": active,
            "completed": len(ids_completed),
            "pending": len(ids_pending),
            "exceptions": {
                "review_required": len(ids_review),
                "disappeared_without_completion": len(ids_review),
                "missing_workload_entry_scan": 0,
                "completed_awaiting_workload_assignment": 0,
                "total": len(ids_review),
            },
            "total_operational_orders": active,
            "bag_ids": {
                "new_today": ids_new,
                "carryover": ids_carry,
                "completed": ids_completed,
                "pending": ids_pending,
                "review_required": ids_review,
                "disappeared_without_completion": ids_review,
                "missing_workload_entry_scan": [],
                "completed_awaiting_workload_assignment": [],
            },
        }

    all_new = list(result.get("new_today") or [])
    all_carry = list(result.get("carryover") or [])
    all_completed = list(result.get("completed_on_date") or [])
    all_pending = list(result.get("pending_end_of_date") or [])
    all_review = list(
        result.get("review_required")
        or result.get("disappeared_without_completion_exceptions")
        or []
    )
    cwo = list(
        result.get("completed_without_recognized_entry")
        or result.get("completed_without_entry_scan")
        or []
    )

    from backend.rinse_veewash_review import build_review_by_reason

    review_by_reason = build_review_by_reason(result)

    segments = {
        "all": _seg(all_new, all_carry, all_completed, all_pending, all_review),
        "rush": _seg(
            _filter(all_new, rush="RUSH"),
            _filter(all_carry, rush="RUSH"),
            _filter(all_completed, rush="RUSH"),
            _filter(all_pending, rush="RUSH"),
            _filter(all_review, rush="RUSH"),
        ),
        "non_rush": _seg(
            _filter(all_new, rush="NON_RUSH"),
            _filter(all_carry, rush="NON_RUSH"),
            _filter(all_completed, rush="NON_RUSH"),
            _filter(all_pending, rush="NON_RUSH"),
            _filter(all_review, rush="NON_RUSH"),
        ),
        "wf": _seg(
            _filter(all_new, service=SERVICE_WF),
            _filter(all_carry, service=SERVICE_WF),
            _filter(all_completed, service=SERVICE_WF),
            _filter(all_pending, service=SERVICE_WF),
            _filter(all_review, service=SERVICE_WF),
        ),
        "hd": _seg(
            _filter(all_new, service=SERVICE_HD),
            _filter(all_carry, service=SERVICE_HD),
            _filter(all_completed, service=SERVICE_HD),
            _filter(all_pending, service=SERVICE_HD),
            _filter(all_review, service=SERVICE_HD),
        ),
        "wf_rush": _seg(
            _filter(all_new, service=SERVICE_WF, rush="RUSH"),
            _filter(all_carry, service=SERVICE_WF, rush="RUSH"),
            _filter(all_completed, service=SERVICE_WF, rush="RUSH"),
            _filter(all_pending, service=SERVICE_WF, rush="RUSH"),
            _filter(all_review, service=SERVICE_WF, rush="RUSH"),
        ),
        "wf_non_rush": _seg(
            _filter(all_new, service=SERVICE_WF, rush="NON_RUSH"),
            _filter(all_carry, service=SERVICE_WF, rush="NON_RUSH"),
            _filter(all_completed, service=SERVICE_WF, rush="NON_RUSH"),
            _filter(all_pending, service=SERVICE_WF, rush="NON_RUSH"),
            _filter(all_review, service=SERVICE_WF, rush="NON_RUSH"),
        ),
        "hd_rush": _seg(
            _filter(all_new, service=SERVICE_HD, rush="RUSH"),
            _filter(all_carry, service=SERVICE_HD, rush="RUSH"),
            _filter(all_completed, service=SERVICE_HD, rush="RUSH"),
            _filter(all_pending, service=SERVICE_HD, rush="RUSH"),
            _filter(all_review, service=SERVICE_HD, rush="RUSH"),
        ),
        "hd_non_rush": _seg(
            _filter(all_new, service=SERVICE_HD, rush="NON_RUSH"),
            _filter(all_carry, service=SERVICE_HD, rush="NON_RUSH"),
            _filter(all_completed, service=SERVICE_HD, rush="NON_RUSH"),
            _filter(all_pending, service=SERVICE_HD, rush="NON_RUSH"),
            _filter(all_review, service=SERVICE_HD, rush="NON_RUSH"),
        ),
    }

    a = segments["all"]
    wf = segments["wf"]
    hd = segments["hd"]
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
        "wf_new_today": wf["new_today"],
        "hd_new_today": hd["new_today"],
        "historical_unresolved_backlog": 0,
        "historical_unresolved_backlog_bag_ids": [],
        "completed_without_recognized_entry": len(cwo),
        "completed_without_recognized_entry_bag_ids": sorted(cwo),
        "review_by_reason": review_by_reason,
        "review_reasons_by_bag": dict(result.get("review_reasons_by_bag") or {}),
        "rfv_excluded": len(result.get("rfv_excluded") or []),
        "rfv_excluded_bag_ids": list(result.get("rfv_excluded") or []),
        "segments": segments,
        "reconciliation_lines": {
            "new_today": (
                f"New Today {a['new_today']} = WF {wf['new_today']} + HD {hd['new_today']}"
            ),
            "active_workload": (
                f"Active Workload {a['active_workload']} = Completed {a['completed']}"
                f" + Pending {a['pending']}"
                f" + Review Required {exc['review_required']}"
            ),
        },
    }


def _rush_bucket(rush_flag: Any) -> str:
    v = str(rush_flag or "").strip().lower()
    if not v:
        return "UNKNOWN"
    if "non" in v:
        return "NON_RUSH"
    if "rush" in v or v in ("1", "true", "yes", "y"):
        return "RUSH"
    return "NON_RUSH"


def _rush_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rush / Non-Rush breakdown of the active workload (new + carryover)."""
    members = [
        r
        for r in rows
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


def _service_split(result: Mapping[str, Any]) -> dict[str, Any]:
    rows = {r.get("bag_id"): r for r in (result.get("rows") or []) if r.get("bag_id")}

    def _svc_ids(key: str, service: str) -> list[str]:
        return sorted(
            b
            for b in (result.get(key) or [])
            if str((rows.get(b) or {}).get("service_type") or "").upper() == service
        )

    return {
        "wf": {
            "new_today": _svc_ids("new_today", SERVICE_WF),
            "carryover": _svc_ids("carryover", SERVICE_WF),
            "completed": _svc_ids("completed_on_date", SERVICE_WF),
            "pending": _svc_ids("pending_end_of_date", SERVICE_WF),
            "review_required": _svc_ids("review_required", SERVICE_WF)
            or _svc_ids("disappeared_without_completion_exceptions", SERVICE_WF),
        },
        "hd": {
            "new_today": _svc_ids("new_today", SERVICE_HD),
            "carryover": _svc_ids("carryover", SERVICE_HD),
            "completed": _svc_ids("completed_on_date", SERVICE_HD),
            "pending": _svc_ids("pending_end_of_date", SERVICE_HD),
            "review_required": _svc_ids("review_required", SERVICE_HD)
            or _svc_ids("disappeared_without_completion_exceptions", SERVICE_HD),
        },
    }
