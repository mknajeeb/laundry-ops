"""
VeeWash Shift Monitor — Step 1: authoritative daily workload from At-Vendor scrape.

Operating model:

  * Eligibility: organization_id = 3 AND portal_status = at_vendor.
    RFV (ready_for_vendor) is inactive and never loaded into this workload.
  * Workload entry (WF and HD): first scan into ANY configured facility entry rack
    (facility_entry_racks). Service type comes from presence (WF vs HD).
  * Recognized-entry check for COMPLETED_WITHOUT_RECOGNIZED_ENTRY:
      WF → configured facility entry rack required; HD → workitems-added required
      (in addition to entry-rack membership).
    When completed without the service-appropriate signal, bag enters Active as Review Required.
  * workitems-added is NOT a WF workload entry event. Recognized entry:
      WF → first configured facility entry rack scan
      HD → first workitems-added scan (entry rack is not HD entry for CWO checks)
  * Completion: shared ``rinse_cycle_boundary.resolve_current_cycle`` for a
    selected ET day. Required order:
    sent-to-vendor → configured entry move-bag → garments-reviewed →
    earliest later weight-entry. Review+weight without entry stays pending
    with ``ENTRY_NOT_FOUND``. Clean rack is not required. Manager
    correct_completion overrides still win **within the current cycle only**
    (prior-cycle corrections must not replace a later cycle's completion).
    Lifetime first-clean must not determine current-cycle status.
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

# Hard cutover: append-only daily membership starts this ET date for org 3.
STEP1_AUTHORITATIVE_START_ET = date(2026, 7, 23)

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
REASON_SCAN_CHRONOLOGY_STALE = "SCAN_CHRONOLOGY_STALE"
REASON_MANAGER_SENT_FOR_REVIEW = "MANAGER_SENT_FOR_REVIEW"
REASON_MISSING_PRE_EVIDENCE = "MISSING_PRE_EVIDENCE"
# Pending-only cycle diagnostic (not a Review Required code).
REASON_ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"

REVIEW_REASON_CODES = (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    REASON_WF_BULK_WORKITEM_REVIEW,
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    REASON_COMPLETION_DETAILS_MISSING,
    REASON_SCAN_CHRONOLOGY_STALE,
    REASON_MANAGER_SENT_FOR_REVIEW,
    REASON_MISSING_PRE_EVIDENCE,
)

ENTRY_CLASS_NEW = "new_today"
ENTRY_CLASS_CARRYOVER = "carryover"
OUTCOME_COMPLETED = "completed"
OUTCOME_PENDING = "pending"
OUTCOME_DISAPPEARED = "disappeared_exception"
OUTCOME_REVIEW_REQUIRED = "review_required"
# Release B close-archive: unresolved rows at day close (display: Unfinished at Close).
OUTCOME_STALE = "stale"

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


def _presence_edd_date(pres: Mapping[str, Any]) -> date | None:
    raw = pres.get("estimated_delivery_date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return _scan_et_date(raw) if isinstance(raw, datetime) else None


def _presence_delivery_texts(pres: Mapping[str, Any]) -> list[str]:
    import json

    texts: list[str] = []
    rj = pres.get("raw_row_json")
    if isinstance(rj, str) and rj.strip():
        try:
            rj = json.loads(rj)
        except (TypeError, ValueError, json.JSONDecodeError):
            rj = {}
    if isinstance(rj, Mapping):
        for key in ("estimated_delivery_text", "Date_Clean"):
            val = rj.get(key)
            if val:
                texts.append(str(val))
    for key in ("customer_name", "estimated_delivery_text"):
        val = pres.get(key)
        if val:
            texts.append(str(val))
    return texts


def _effective_portal_rush_flag(
    pres: Mapping[str, Any], selected_date_et: date
) -> Any:
    """Portal / At Vendor rush for the selected ET day.

    Future EDD is Non-Rush even when the stored portal cell still says RUSH.
    Stored ``rush_flag`` is the fallback when EDD / TODAY cannot be resolved.
    """
    from backend.rinse_at_vendor_module import AV_NON_RUSH, AV_RUSH, classify_at_vendor_rush

    bucket, _reason = classify_at_vendor_rush(
        latest_edd=_presence_edd_date(pres),
        delivery_texts=_presence_delivery_texts(pres),
        selected_date_et=selected_date_et,
        pending=True,
    )
    if bucket == AV_RUSH:
        return "RUSH"
    if bucket == AV_NON_RUSH:
        return "NON-RUSH"
    return pres.get("rush_flag")


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
    """
    First *classification-relevant* workitems-added scan per bag.

    Hang Dry identity uses workitems-added, but a workitems-added that occurs
    *before* the bag's first weight-entry is ignored (common false HD signal
    from upstream pickup tagging — e.g. 04FRSEC71H). When no weight-entry
    exists yet, workitems-added still counts.
    """
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}

    org = int(organization_id)
    first_weight_at: dict[str, Any] = {}
    cursor.execute(
        """
        SELECT bag_id, MIN(scanned_at_parsed) AS first_weight_at
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND LOWER(REPLACE(TRIM(COALESCE(purpose, '')), ' ', '-')) = 'weight-entry'
        GROUP BY bag_id
        """,
        (org,),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        ts = row.get("first_weight_at")
        if bid and ts is not None:
            first_weight_at[bid] = ts

    cursor.execute(
        """
        SELECT bag_id, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND LOWER(TRIM(COALESCE(purpose, ''))) IN ('workitems-added', 'workitems_added')
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (org,),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm_bag(row.get("bag_id"))
        ts = row.get("scanned_at_parsed")
        if not bid or ts is None or bid in out:
            continue
        wt_at = first_weight_at.get(bid)
        # Ignore workitems-added that precede the first weight-entry.
        if wt_at is not None and ts < wt_at:
            continue
        d = _scan_et_date(ts)
        if d is not None:
            out[bid] = {"first_entry_at": ts, "entry_date": d}
    return out


def build_dirty_entry_map(
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    dirty_by_bag: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """WF and HD enter Active workload via first scan into any configured entry rack."""
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


def _completion_employee_at(
    timeline: list[dict[str, Any]], completion_at: datetime
) -> str | None:
    """Operator on the completion event (prefer the weight-entry row)."""
    from backend.rinse_bag_activity_rules import _operator, event_ts
    from backend.rinse_cycle_boundary import _norm_purpose

    exact: list[Mapping[str, Any]] = []
    for ev in timeline:
        ts = event_ts(ev)
        if ts is None or ts != completion_at:
            continue
        exact.append(ev)
    if not exact:
        return None
    for ev in exact:
        if _norm_purpose(ev.get("purpose")) == "weight-entry":
            return _operator(ev)
    return _operator(exact[-1])


def _cycle_result_to_completion_dict(
    result: Any,
    *,
    selected_date_et: date,
    timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Same-day current-cycle completion dict for Step-1 classify, or None."""
    from backend.rinse_cycle_boundary import COMPLETION_SOURCE_POST_REVIEW_WEIGHT

    if result is None or getattr(result, "effective_status", None) != "completed":
        return None
    if getattr(result, "pending_reason", None):
        return None
    comp_ts = getattr(result, "completion_at", None)
    if comp_ts is None:
        return None
    d = _scan_et_date(comp_ts)
    if d != selected_date_et:
        return None
    completed_by = getattr(result, "completed_by", None)
    if not completed_by and timeline is not None:
        completed_by = _completion_employee_at(timeline, comp_ts)
    source = (
        getattr(result, "completion_source", None) or COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    )
    return {
        "completion_at": comp_ts,
        "completion_date": d,
        "completed_by": completed_by,
        "completion_source": source,
        "completion_kind": source,
        "via_clean_rack": False,
        "cycle_anchor_at": getattr(result, "cycle_anchor_at", None),
        "entry_at": getattr(result, "entry_at", None),
        "entry_rack": getattr(result, "entry_rack", None),
        "garments_reviewed_at": getattr(result, "garments_reviewed_at", None),
    }


def _cycle_anchored_completion_for_day(
    timeline: list[dict[str, Any]],
    *,
    selected_date_et: date,
    service_type: str = "WF",
    entry_racks: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    """Current-cycle same-day completion via shared ``rinse_cycle_boundary``.

    HD keeps the At Vendor HD signal path (garments-reviewed / complete-cleaning /
    assembly) so Hang Dry membership/completion rules are unchanged by this WF fix.
    """
    from backend.rinse_cycle_boundary import resolve_current_cycle
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS

    svc = str(service_type or "WF").strip().upper()
    racks = list(entry_racks) if entry_racks is not None else list(DEFAULT_FACILITY_ENTRY_RACKS)

    if svc == "HD":
        from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, _evaluate_bag_as_of

        day_end = naive_et_day_end_inclusive(selected_date_et)
        status, signal, comp_ts, anchor_ts, _fields = _evaluate_bag_as_of(
            timeline,
            service_type="HD",
            as_of_end=day_end,
        )
        if status != AV_STATUS_COMPLETED or comp_ts is None:
            return None
        d = _scan_et_date(comp_ts)
        if d != selected_date_et:
            return None
        return {
            "completion_at": comp_ts,
            "completion_date": d,
            "completed_by": _completion_employee_at(timeline, comp_ts),
            "completion_source": f"cycle_anchored:{signal or 'hd_completed'}",
            "completion_kind": signal or "hd_completed",
            "via_clean_rack": False,
            "cycle_anchor_at": anchor_ts,
            "cycle_signal": signal,
        }

    result = resolve_current_cycle(
        timeline,
        selected_date_et=selected_date_et,
        entry_racks=racks,
    )
    return _cycle_result_to_completion_dict(
        result, selected_date_et=selected_date_et, timeline=timeline
    )


def load_canonical_completions_v2(
    cursor,
    organization_id: int,
    bag_ids: Iterable[str],
    *,
    selected_date_et: date | None = None,
    service_type_by_bag: Mapping[str, str] | None = None,
    entry_racks: Iterable[str] | None = None,
    pending_reasons_out: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Canonical completions for Step-1 / ledger-aligned day outcomes.

    Precedence (highest wins):
      1. Manager ``correct_completion`` override (rinse_step1_corrections)
         **scoped to the current cycle** when ``selected_date_et`` is set
      2. When ``selected_date_et`` is set: shared ``rinse_cycle_boundary``
         current-cycle completion (WF) / HD At Vendor signal (HD)
      3. When no selected date: legacy ``evaluate_bag_completion_v2`` (report /
         non-day callers only — not used for Shift Monitor day status)

    When ``selected_date_et`` is set, lifetime first-clean is **never** emitted.
    That prevents ``completed_before_selected_date`` + membership reinject-as-pending
    for resend_today bags that completed again on D under the current cycle.

    Manager-cycle scoping (selected day only)
    ----------------------------------------
    Corrections have no dedicated cycle-id column. The durable association is
    ``new_values.completion_at``: a correction overrides only when that
    timestamp falls in the current cycle window
    ``[cycle_anchor_at, next_sent_to_vendor)`` from
    ``current_cycle_event_window`` (open cycles have no end). Prior-cycle
    corrections must not replace a later/current cycle's completion.
    Calendar-day equality alone is insufficient — cycles cross ET midnight.
    When ``selected_date_et`` is omitted, legacy callers keep unscoped apply.

    When ``pending_reasons_out`` is provided, WF bags that remain pending because
    the current cycle lacks a configured entry (``ENTRY_NOT_FOUND``) are recorded
    there without being treated as completed.
    """
    from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
    from backend.rinse_cycle_boundary import (
        PENDING_REASON_ENTRY_NOT_FOUND,
        current_cycle_event_window,
        manager_completion_belongs_to_cycle,
        resolve_current_cycle,
    )
    from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}

    racks = list(entry_racks) if entry_racks is not None else None
    if racks is None and selected_date_et is not None:
        try:
            from backend.rinse_processing_settings import get_processing_settings

            racks = get_processing_settings(cursor, organization_id).get(
                "facility_entry_racks"
            ) or list(DEFAULT_FACILITY_ENTRY_RACKS)
        except Exception:
            racks = list(DEFAULT_FACILITY_ENTRY_RACKS)

    # Bound IN lists — never full-table scan all org scan events.
    id_set = set(ids)
    by_bag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunk_size = 400
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            SELECT bag_id, rack, purpose, scanned_at_parsed, user_name, weight_lbs,
                   source_filename, raw_json
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
                    "source_filename": row.get("source_filename"),
                    "raw_json": row.get("raw_json"),
                }
            )

    out: dict[str, dict[str, Any]] = {}
    svc_map = {
        _norm_bag(k): str(v or "").strip().upper()
        for k, v in (service_type_by_bag or {}).items()
        if _norm_bag(k)
    }
    for bid, timeline in by_bag.items():
        if selected_date_et is not None:
            svc = svc_map.get(bid) or "WF"
            if str(svc).strip().upper() == "HD":
                cycle = _cycle_anchored_completion_for_day(
                    timeline,
                    selected_date_et=selected_date_et,
                    service_type="HD",
                    entry_racks=racks,
                )
                if cycle is not None:
                    out[bid] = cycle
                continue

            boundary = resolve_current_cycle(
                timeline,
                selected_date_et=selected_date_et,
                entry_racks=racks,
            )
            cycle = _cycle_result_to_completion_dict(
                boundary, selected_date_et=selected_date_et, timeline=timeline
            )
            if cycle is not None:
                out[bid] = cycle
            elif (
                pending_reasons_out is not None
                and boundary.pending_reason == PENDING_REASON_ENTRY_NOT_FOUND
            ):
                pending_reasons_out[bid] = PENDING_REASON_ENTRY_NOT_FOUND
            continue

        # No selected date: legacy lifetime resolver for non-day callers only.
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

    # Manager correct_completion overrides beat scan/cycle operator on rebuild.
    # Load even when scan completion is empty — otherwise Save→refresh reverts.
    # When selected_date_et is set, only apply corrections whose completion_at
    # belongs to the current cycle window (never a prior cycle's override).
    if ids and table_exists(cursor, "rinse_step1_corrections"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, new_values, created_at, id
            FROM rinse_step1_corrections
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND action = 'correct_completion'
            ORDER BY created_at ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        cycle_windows: dict[str, tuple[datetime | None, datetime | None]] = {}
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = _norm_bag(row.get("bag_id"))
            if not bid or bid not in ids:
                continue
            raw = row.get("new_values")
            if isinstance(raw, str):
                try:
                    import json

                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if not isinstance(raw, dict):
                continue
            emp = str(raw.get("completed_by") or raw.get("employee") or "").strip() or None
            ts_raw = raw.get("completion_at")
            ts = None
            if ts_raw not in (None, ""):
                if isinstance(ts_raw, datetime):
                    ts = ts_raw
                else:
                    try:
                        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "").replace(" ", "T", 1))
                    except ValueError:
                        ts = None
            if not emp and ts is None:
                continue

            if selected_date_et is not None:
                if bid not in cycle_windows:
                    cycle_windows[bid] = current_cycle_event_window(
                        by_bag.get(bid) or [],
                        selected_date_et=selected_date_et,
                        entry_racks=racks,
                    )
                cycle_start, cycle_end = cycle_windows[bid]
                if ts is not None:
                    if not manager_completion_belongs_to_cycle(
                        ts, cycle_start=cycle_start, cycle_end=cycle_end
                    ):
                        continue
                else:
                    # Employee-only correction without completion_at: overlay
                    # only onto an existing current-cycle completion.
                    existing_at = (out.get(bid) or {}).get("completion_at")
                    if not isinstance(existing_at, datetime):
                        continue
                    if not manager_completion_belongs_to_cycle(
                        existing_at, cycle_start=cycle_start, cycle_end=cycle_end
                    ):
                        continue

            # Apply even when scan-based completion is missing (same-cycle only
            # when selected_date_et is set).
            merged = dict(out.get(bid) or {})
            if emp:
                merged["completed_by"] = emp
            if ts is not None:
                merged["completion_at"] = ts
                d2 = _scan_et_date(ts)
                if d2 is not None:
                    merged["completion_date"] = d2
            merged["completion_source"] = "manager_correct_completion"
            out[bid] = merged
            if pending_reasons_out is not None:
                pending_reasons_out.pop(bid, None)
    return out


def apply_cycle_pending_reasons(
    result: dict[str, Any],
    pending_reasons: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Attach ENTRY_NOT_FOUND (and similar) to pending rows without promoting Review."""
    if not pending_reasons:
        return result
    out = dict(result)
    rows = []
    for row in result.get("rows") or []:
        if not isinstance(row, Mapping):
            rows.append(row)
            continue
        bid = _norm_bag(row.get("bag_id"))
        reason = pending_reasons.get(bid) if bid else None
        if not reason:
            rows.append(dict(row))
            continue
        outcome = str(row.get("outcome") or row.get("final_bucket") or "").lower()
        if "completed" in outcome or outcome == OUTCOME_REVIEW_REQUIRED:
            rows.append(dict(row))
            continue
        updated = dict(row)
        updated["pending_reason"] = reason
        codes = [str(c) for c in (updated.get("reason_codes") or []) if str(c).strip()]
        if reason not in codes:
            codes.append(reason)
        updated["reason_codes"] = codes
        rows.append(updated)
    out["rows"] = rows
    out["cycle_pending_reasons_by_bag"] = {
        _norm_bag(k): str(v)
        for k, v in pending_reasons.items()
        if _norm_bag(k) and str(v).strip()
    }
    return out


def _apply_cycle_entry_overlay(
    entry_by_bag: dict[str, dict[str, Any]],
    completion_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    selected_date_et: date,
    member_ids: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Prefer current-cycle configured-rack entry timestamps when present."""
    member_set = (
        {_norm_bag(b) for b in member_ids if _norm_bag(b)}
        if member_ids is not None
        else None
    )
    out = dict(entry_by_bag)
    for bid, comp in completion_by_bag.items():
        bid = _norm_bag(bid)
        if not bid:
            continue
        if member_set is not None and bid not in member_set:
            continue
        entry_at = comp.get("entry_at")
        if entry_at is None:
            continue
        ed = _scan_et_date(entry_at)
        if ed != selected_date_et:
            continue
        prev = dict(out.get(bid) or {})
        prev.update(
            {
                "entry_date": ed,
                "entry_at": entry_at,
                "entry_source": prev.get("entry_source") or ENTRY_SOURCE_DIRTY,
                "entry_rack": comp.get("entry_rack") or prev.get("entry_rack"),
                "cycle_anchored_entry": True,
            }
        )
        out[bid] = prev
    return out


# NOTE: legacy helpers below retained for tests; day status uses load_canonical_completions_v2.

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
    Completion must already come from load_canonical_completions_v2 / cycle boundary
    (or a test double).
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
            "rush_flag": _effective_portal_rush_flag(pres, D),
            "estimated_delivery_date": _presence_edd_date(pres),
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

    cycle_pending_reasons: dict[str, str] = {}
    completion = load_canonical_completions_v2(
        cursor,
        organization_id,
        presence.keys(),
        selected_date_et=selected_date_et,
        service_type_by_bag={
            _norm_bag(bid): str((pres or {}).get("service_type") or "WF")
            for bid, pres in presence.items()
        },
        entry_racks=racks,
        pending_reasons_out=cycle_pending_reasons,
    )
    entry = _apply_cycle_entry_overlay(
        entry, completion, selected_date_et=selected_date_et
    )

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
        load_registry_service_classification,
    )

    weight_ids = sorted(
        set(result.get("new_today") or [])
        | set(result.get("carryover") or [])
        | set(result.get("completed_on_date") or [])
        | set(result.get("completed_without_recognized_entry") or [])
        | set(presence.keys())
    )
    weights = load_bag_weight_map(
        cursor, organization_id, weight_ids, selected_date_et=selected_date_et
    )
    registry_services, registry_historical = load_registry_service_classification(
        cursor, organization_id, weight_ids
    )

    from backend.rinse_bulk_workitems import (
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )

    bulk_scans = load_bulk_workitem_scan_map(
        cursor, organization_id, weight_ids, selected_date_et=selected_date_et
    )
    bulk_resolutions = load_bulk_resolutions(
        cursor, organization_id, selected_date_et, weight_ids
    )
    bulk_lines = load_bag_bulk_lines(cursor, organization_id, selected_date_et, weight_ids)

    from backend.rinse_scan_freshness import (
        freshness_from_day_and_presence,
        load_last_scan_at_by_bag,
    )

    last_scans = load_last_scan_at_by_bag(cursor, organization_id, weight_ids)

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
        registry_service_by_bag=registry_services,
        registry_historical_completed_bags=registry_historical,
        last_scan_at_by_bag=last_scans,
    )
    result = apply_cycle_pending_reasons(result, cycle_pending_reasons)
    result["data_freshness"] = freshness_from_day_and_presence(
        cursor,
        organization_id,
        selected_date_et,
        sample_bag_ids=weight_ids,
        pending_bag_ids=result.get("pending_end_of_date") or result.get("pending") or [],
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
    counts = result.get("counts") or {}
    if "total_workload" not in counts:
        counts = dict(counts)
        counts["total_workload"] = int(
            counts.get("total_active_workload")
            or (len(result.get("new_today") or []) + len(result.get("carryover") or []))
        )
        result["counts"] = counts
    result.setdefault("total_workload", counts.get("total_workload"))
    return result


def build_veewash_daily_workload_from_membership(
    cursor,
    organization_id: int = VEEWASH_ORG_ID,
    *,
    selected_date_et: date,
    entry_racks: Iterable[str] | None = None,
    frozen_member_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """
    Step-1 daily workload using append-only same-day scrape membership.

    Membership (baseline + later additions) defines which bags are in the day.
    Classification / review still run on those bags; disappearing from later
    scrapes does not remove membership.

    Completion / current-cycle entry come from shared ``rinse_cycle_boundary``.

    ``frozen_member_ids``: optional pin to an existing day-bag ID set (e.g. controlled
    validation / heal). Does not change fresh-start or carryover admission policy.
    """
    from backend.rinse_cleaner_ticket_presence import load_presence_run_snapshot_by_bag
    from backend.rinse_veewash_day_membership import (
        build_append_only_membership,
        membership_bag_ids,
    )

    membership = build_append_only_membership(
        cursor, organization_id, selected_date_et
    )
    # HD membership follows append-only same-day scrape evidence (not EDD).
    # EDD gate intentionally bypassed — future-EDD HD that appears today stays.
    # Prior-completed HD exclusion runs in finalize_hd_step1_summary.
    member_ids = membership_bag_ids(membership)
    from backend.rinse_wf_service_cycle_compat import final_wf_day_membership_bag_ids

    member_ids = final_wf_day_membership_bag_ids(
        cursor, organization_id, selected_date_et, member_ids
    )
    if frozen_member_ids is not None:
        freeze = sorted({_norm_bag(b) for b in frozen_member_ids if _norm_bag(b)})
        freeze = final_wf_day_membership_bag_ids(
            cursor, organization_id, selected_date_et, freeze
        )
        member_ids = freeze
        mem_rows = dict(membership.get("membership") or {})
        membership = dict(membership)
        membership["membership"] = {
            bid: mem_rows.get(bid) or {"bag_id": bid} for bid in freeze
        }
        membership["frozen_member_ids"] = list(freeze)
    member_set = set(member_ids)

    racks = list(entry_racks) if entry_racks else None
    if racks is None:
        try:
            from backend.rinse_processing_settings import get_processing_settings

            racks = get_processing_settings(cursor, organization_id).get(
                "facility_entry_racks"
            ) or list(DEFAULT_FACILITY_ENTRY_RACKS)
        except Exception:
            racks = list(DEFAULT_FACILITY_ENTRY_RACKS)

    live_presence = load_presence_orders(cursor, organization_id, at_vendor_only=True)
    presence: dict[str, dict[str, Any]] = {}
    for bid in member_ids:
        if bid in live_presence:
            presence[bid] = dict(live_presence[bid])

    # Reconstruct minimal presence for membership bags missing from live table.
    run_ids: list[int] = []
    baseline_id = membership.get("baseline_presence_run_id")
    if baseline_id:
        run_ids.append(int(baseline_id))
    for sid in membership.get("later_scrape_ids") or []:
        run_ids.append(int(sid))
    for added in membership.get("added_later") or []:
        sid = added.get("source_scrape_id") if isinstance(added, dict) else None
        if sid is not None:
            run_ids.append(int(sid))
    # Deduplicate while preserving order
    seen_runs: set[int] = set()
    uniq_runs: list[int] = []
    for rid in run_ids:
        if rid in seen_runs:
            continue
        seen_runs.add(rid)
        uniq_runs.append(rid)

    mem_rows = membership.get("membership") or {}
    if isinstance(mem_rows, dict):
        for bid, mrow in mem_rows.items():
            bid = _norm_bag(bid)
            if not bid or bid in presence:
                continue
            presence[bid] = {
                "bag_id": bid,
                "active": 1,
                "portal_status": PORTAL_AT_VENDOR,
                "customer_name": (mrow or {}).get("customer_name"),
                "service_type": (
                    str((mrow or {}).get("service_type_portal") or "").upper() or None
                ),
                "rush_flag": (mrow or {}).get("rush_flag"),
                "estimated_delivery_date": (mrow or {}).get("estimated_delivery_date"),
                "first_seen_at": (mrow or {}).get("first_seen_portal_at"),
                "last_seen_at": (mrow or {}).get("last_seen_during_day"),
                "source_batch_id": None,
                "from_membership_meta": True,
            }

    for run_id in uniq_runs:
        try:
            snap = load_presence_run_snapshot_by_bag(
                cursor, organization_id, presence_run_id=run_id
            )
        except Exception:
            snap = {}
        for bid, row in (snap or {}).items():
            bid = _norm_bag(bid)
            if bid not in member_set:
                continue
            if bid in presence and not presence[bid].get("from_membership_meta"):
                continue
            # Prefer snapshot fields when reconstructing / enriching stubs.
            if bid not in presence or presence[bid].get("from_membership_meta"):
                presence[bid] = {
                    "bag_id": bid,
                    "active": 1,
                    "portal_status": row.get("portal_status") or PORTAL_AT_VENDOR,
                    "customer_name": row.get("customer_name")
                    or (presence.get(bid) or {}).get("customer_name"),
                    "service_type": (
                        str(row.get("service_type") or "").upper()
                        or (presence.get(bid) or {}).get("service_type")
                    ),
                    "rush_flag": row.get("rush_flag")
                    or (presence.get(bid) or {}).get("rush_flag"),
                    "estimated_delivery_date": row.get("estimated_delivery_date"),
                    "first_seen_at": (presence.get(bid) or {}).get("first_seen_at"),
                    "last_seen_at": (presence.get(bid) or {}).get("last_seen_at"),
                    "source_batch_id": row.get("source_batch_id"),
                    "from_membership_snapshot": True,
                }

    for bid in member_ids:
        if bid not in presence:
            presence[bid] = {
                "bag_id": bid,
                "active": 1,
                "portal_status": PORTAL_AT_VENDOR,
                "customer_name": None,
                "service_type": None,
                "rush_flag": None,
                "estimated_delivery_date": None,
                "first_seen_at": None,
                "last_seen_at": None,
                "source_batch_id": None,
                "from_membership_stub": True,
            }

    dirty = load_first_dirty_scans(cursor, organization_id, entry_racks=racks)
    wia = load_first_workitems_added_scans(cursor, organization_id)
    entry = build_service_entry_map(
        presence, dirty_by_bag=dirty, wia_by_bag=wia
    )
    # Membership bags are in-day regardless of recognized entry: synthesize a
    # same-day entry so classify keeps them in the operational set.
    for bid in member_ids:
        if bid not in entry:
            entry[bid] = {
                "entry_date": selected_date_et,
                "entry_source": ENTRY_SOURCE_MANUAL_REVIEW,
                "entry_at": None,
                "membership_synthetic_entry": True,
            }

    completion_ids = sorted(member_set | set(presence.keys()))
    cycle_pending_reasons: dict[str, str] = {}
    completion = load_canonical_completions_v2(
        cursor,
        organization_id,
        completion_ids,
        selected_date_et=selected_date_et,
        service_type_by_bag={
            _norm_bag(bid): str((pres or {}).get("service_type") or "WF")
            for bid, pres in presence.items()
        },
        entry_racks=racks,
        pending_reasons_out=cycle_pending_reasons,
    )
    entry = _apply_cycle_entry_overlay(
        entry,
        completion,
        selected_date_et=selected_date_et,
        member_ids=member_ids,
    )
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
        load_registry_service_classification,
    )

    weight_ids = sorted(member_set | set(presence.keys()))
    weights = load_bag_weight_map(
        cursor, organization_id, weight_ids, selected_date_et=selected_date_et
    )
    registry_services, registry_historical = load_registry_service_classification(
        cursor, organization_id, weight_ids
    )

    from backend.rinse_bulk_workitems import (
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )

    bulk_scans = load_bulk_workitem_scan_map(
        cursor, organization_id, weight_ids, selected_date_et=selected_date_et
    )
    bulk_resolutions = load_bulk_resolutions(
        cursor, organization_id, selected_date_et, weight_ids
    )
    bulk_lines = load_bag_bulk_lines(cursor, organization_id, selected_date_et, weight_ids)

    from backend.rinse_scan_freshness import (
        freshness_from_day_and_presence,
        load_last_scan_at_by_bag,
    )

    last_scans = load_last_scan_at_by_bag(cursor, organization_id, weight_ids)

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
        registry_service_by_bag=registry_services,
        registry_historical_completed_bags=registry_historical,
        last_scan_at_by_bag=last_scans,
    )
    result = apply_cycle_pending_reasons(result, cycle_pending_reasons)

    # CP2B membership buckets: Opening Carryover / Opening New / Added During Day.
    from backend.rinse_veewash_day_membership import (
        INCLUSION_ADDED_LATER,
        INCLUSION_OPENING_CARRYOVER,
        INCLUSION_OPENING_NEW,
    )

    mem_by_bag = membership.get("membership") or {}
    opening_carryover = [
        _norm_bag(b)
        for b in (membership.get("opening_carryover_bag_ids") or [])
        if _norm_bag(b) in member_set
    ]
    if not opening_carryover and isinstance(mem_by_bag, dict):
        opening_carryover = sorted(
            bid
            for bid, row in mem_by_bag.items()
            if _norm_bag(bid) in member_set
            and str((row or {}).get("inclusion_source") or "") == INCLUSION_OPENING_CARRYOVER
        )
    opening_new = [
        _norm_bag(b)
        for b in (membership.get("opening_new_bag_ids") or [])
        if _norm_bag(b) in member_set
    ]
    if not opening_new and isinstance(mem_by_bag, dict):
        opening_new = sorted(
            bid
            for bid, row in mem_by_bag.items()
            if _norm_bag(bid) in member_set
            and str((row or {}).get("inclusion_source") or "")
            in (INCLUSION_OPENING_NEW, "FIRST_SCRAPE_BASELINE")
        )
    added_during = [
        _norm_bag(b)
        for b in (membership.get("added_later_bag_ids") or [])
        if _norm_bag(b) in member_set
    ]
    if not added_during and isinstance(mem_by_bag, dict):
        added_during = sorted(
            bid
            for bid, row in mem_by_bag.items()
            if _norm_bag(bid) in member_set
            and str((row or {}).get("inclusion_source") or "") == INCLUSION_ADDED_LATER
        )

    # Segment compat: carryover = Opening Carryover; new_today = Opening New ∪ Added.
    carry_set = {_norm_bag(b) for b in opening_carryover}
    new_set = ({_norm_bag(b) for b in opening_new} | {_norm_bag(b) for b in added_during}) - carry_set
    # Any frozen/orphan member not classified still counts in new_today.
    unclassified = member_set - carry_set - new_set
    new_set |= unclassified

    total = len(member_ids)
    result["carryover"] = sorted(carry_set)
    result["new_today"] = sorted(new_set)
    result["opening_carryover"] = sorted(carry_set)
    result["opening_new"] = sorted({_norm_bag(b) for b in opening_new} & member_set)
    result["added_during_day"] = sorted({_norm_bag(b) for b in added_during} & member_set)

    # Membership bags must never remain "not_in_workload" — they are in today's set.
    not_in = set(result.get("not_in_workload") or [])
    if not_in:
        result["not_in_workload"] = sorted(not_in - member_set)
    pending = set(result.get("pending_end_of_date") or [])
    completed = set(result.get("completed_on_date") or [])
    review = set(result.get("review_required") or [])
    for bid in member_ids:
        if bid in completed or bid in review or bid in pending:
            continue
        pending.add(bid)
    result["pending_end_of_date"] = sorted(pending)

    def _entry_class_for(bid: str, incl_src: str | None) -> str:
        src = str(incl_src or "")
        if src == INCLUSION_OPENING_CARRYOVER or bid in carry_set:
            return "opening_carryover"
        if src == INCLUSION_ADDED_LATER or bid in set(result["added_during_day"]):
            return "added_during_day"
        if src in (INCLUSION_OPENING_NEW, "FIRST_SCRAPE_BASELINE") or bid in set(
            result["opening_new"]
        ):
            return "opening_new"
        return "opening_new" if bid in new_set else "opening_carryover"

    for row in result.get("rows") or []:
        bid = row.get("bag_id")
        if bid not in member_set:
            continue
        incl = mem_by_bag.get(bid) or {}
        entry_class = _entry_class_for(bid, incl.get("inclusion_source"))
        row["entry_class"] = entry_class
        row["inclusion_source"] = incl.get("inclusion_source")
        # Never label Opening Carryover as New Today.
        if entry_class == "opening_carryover":
            row["new_or_carryover"] = "carryover"
        elif entry_class == "added_during_day":
            row["new_or_carryover"] = "added_during_day"
        else:
            row["new_or_carryover"] = "opening_new"
        if row.get("outcome") == "not_in_workload" or row.get("final_bucket") == "not_in_workload":
            if bid in completed:
                row["outcome"] = "completed"
                row["final_bucket"] = f"{entry_class}_completed"
            elif bid in review:
                row["outcome"] = "review_required"
                row["final_bucket"] = "review_required"
            else:
                row["outcome"] = "pending"
                row["final_bucket"] = f"{entry_class}_pending"

    counts = dict(result.get("counts") or {})
    counts["carryover"] = len(result.get("carryover") or [])
    counts["new_today"] = len(result.get("new_today") or [])
    counts["opening_carryover"] = len(result.get("opening_carryover") or [])
    counts["opening_new"] = len(result.get("opening_new") or [])
    counts["added_during_day"] = len(result.get("added_during_day") or [])
    counts["not_in_workload"] = len(result.get("not_in_workload") or [])
    counts["pending"] = len(result.get("pending_end_of_date") or [])
    counts["total_workload"] = total
    counts["total_active_workload"] = total
    counts["established_workload"] = total
    counts["total_operational"] = total
    result["counts"] = counts
    result["total_workload"] = total
    result["membership"] = membership
    result["data_freshness"] = freshness_from_day_and_presence(
        cursor,
        organization_id,
        selected_date_et,
        sample_bag_ids=weight_ids,
        pending_bag_ids=result.get("pending_end_of_date") or result.get("pending") or [],
    )
    result["disappearance_confirmation"] = disappearance_state
    result["organization_id"] = int(organization_id)
    result["entry_racks"] = racks
    result["eligible_presence_orders"] = len(presence)
    result["active_presence_orders"] = sum(
        1 for p in presence.values() if int(p.get("active") or 0) == 1
    )
    result["rfv_excluded"] = []
    result["rfv_excluded_count"] = 0
    result["excluded_not_presence_backed"] = []
    result["rush_split"] = _rush_split(result["rows"])
    result["service_split"] = _service_split(result)
    result["workload_source"] = "append_only_membership"
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
            parsed = date.fromisoformat(str(raw)[:10])
            if int(organization_id) == VEEWASH_ORG_ID and parsed < STEP1_AUTHORITATIVE_START_ET:
                return STEP1_AUTHORITATIVE_START_ET
            return parsed
    except Exception:
        pass
    if int(organization_id) == VEEWASH_ORG_ID:
        return STEP1_AUTHORITATIVE_START_ET
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
        # Prefer membership/total when present; keep new+carryover for compat.
        active = len(ids_new) + len(ids_carry)
        return {
            "new_today": len(ids_new),
            "carryover": len(ids_carry),
            "active_workload": active,
            "total_workload": active,
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
    # Prefer explicit membership / total_workload when the builder attached it.
    total_workload = result.get("total_workload")
    if total_workload is None:
        counts = result.get("counts") or {}
        total_workload = counts.get("total_workload")
    if total_workload is not None:
        try:
            total_workload = int(total_workload)
        except (TypeError, ValueError):
            total_workload = a["active_workload"]
        a["active_workload"] = total_workload
        a["total_workload"] = total_workload
        a["total_operational_orders"] = total_workload
    else:
        total_workload = a["active_workload"]
        a["total_workload"] = total_workload

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "activation_date_et": activation_date.isoformat(),
        "new_today": a["new_today"],
        "carryover": a["carryover"],
        "active_workload": a["active_workload"],
        "total_workload": total_workload,
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
        "data_freshness": result.get("data_freshness"),
        "rfv_excluded": len(result.get("rfv_excluded") or []),
        "rfv_excluded_bag_ids": list(result.get("rfv_excluded") or []),
        "membership": result.get("membership"),
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
            "total_workload": f"Total Workload {total_workload}",
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
