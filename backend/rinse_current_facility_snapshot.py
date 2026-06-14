"""
Current Facility Snapshot + Due Today Snapshot — matches Rinse Vendor Home.

Unified operational population (deduped by bag_id):
  active orders_staging + registry supplement + at_vendor/RFV presence + lifecycle rows

At Facility Total     = current at-VeeWash bags (excludes sent/left)
Yet to Process        = at facility, not operationally complete, not sent/left
Completed Still       = at facility, operationally complete, not sent/left

Due Today Total       = all known records with EDD = today (ET)
Due Today Yet to Process = due today, not yet processed
Due Today Completed   = due today total - yet to process

Separate from selected-day workload history (entered today + carryover).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2, find_strong_completion_evidence_v2
from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_lifecycle_status import FOLDED_COMPLETED, SENT_TO_RINSE
from backend.rinse_scan_purpose import (
    is_drying_purpose,
    is_processed_by_vendor_purpose,
    is_received_from_vendor_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    scan_purpose_indicates_sent_left,
)
from backend.rinse_work_pipeline import bag_is_sent_or_left
from backend.rinse_shift_analysis import LIFECYCLE_COMPLETED_STATUSES
from backend.ta_helpers import table_exists, table_has_column

_LOGISTICS_SENT = frozenset({"SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"})

CFS_AT_FACILITY = "cfs_at_facility"
CFS_IN_PROGRESS = "cfs_in_progress"
CFS_COMPLETED_STILL = "cfs_completed_still"
CFS_COMPLETED_STILL_AT_FACILITY = "cfs_completed_still_at_facility"
CFS_SENT_LEFT = "cfs_sent_left"

DTS_TOTAL = "dts_total"
DTS_YET_TO_PROCESS = "dts_yet_to_process"
DTS_COMPLETED_PROCESSED = "dts_completed_processed"

# Internal scan view tags (scan-completion semantics — not Vendor Home parity)
SCAN_DTS_TOTAL = "scan_dts_total"
SCAN_DTS_YET_TO_PROCESS = "scan_dts_yet_to_process"
SCAN_DTS_COMPLETED = "scan_dts_completed_processed"

# Portal Vendor Home drilldown tags (when presence list is loaded)
PORTAL_VH_AT_VENDOR = "portal_vh_at_vendor"
PORTAL_VH_YET_TO_PROCESS = "portal_vh_yet_to_process"
PORTAL_VH_DTS_TOTAL = "portal_vh_dts_total"
PORTAL_VH_DTS_PENDING = "portal_vh_dts_pending"

# Manual Vendor Home reference until direct scrape is available.
VENDOR_HOME_REFERENCE = {
    "source": "manual_screenshot",
    "reference_date": "2026-06-11",
    "at_veewash_total": 48,
    "at_veewash_yet_to_process": 26,
    "due_today_total": 30,
    "due_today_yet_to_process": 25,
    "vendor_home_reference_source": "manual_screenshot",
    # Legacy keys for backward compatibility
    "rinse_home_at_veewash": 48,
    "rinse_home_yet_to_process": 26,
}


def parse_record_date(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and len(raw.strip()) >= 10:
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def record_is_due_today(rec: Mapping[str, Any], today: date) -> bool:
    dc = parse_record_date(rec.get("date_clean") or rec.get("due_date"))
    return dc == today


def load_due_today_bag_ids(cursor, organization_id: int, today: date) -> set[str]:
    return set(load_due_today_rows(cursor, organization_id, today).keys())


def load_due_today_rows(cursor, organization_id: int, today: date) -> dict[str, dict[str, Any]]:
    """Bag rows with date_clean = today from active staging + registry supplement."""
    from backend.rinse_order_search import _active_staging_where_sql
    from backend.rinse_shift_analysis import _service_expr, resolve_effective_rush_for_row

    org = int(organization_id)
    rows: dict[str, dict[str, Any]] = {}

    if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_date = table_has_column(cursor, "orders_staging", "date_clean")
        if has_date:
            org_clause = " AND organization_id = %s" if has_org else ""
            args: list[Any] = []
            if has_org:
                args.append(org)
            args.append(today)
            svc_s = _service_expr("s")
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(s.ticket_id)) AS bag_id, {svc_s} AS service_type,
                       s.date_clean, s.name_clean, s.rush_type
                FROM orders_staging s
                WHERE ({active_where}){org_clause}
                  AND s.date_clean = %s
                  AND s.ticket_id IS NOT NULL AND TRIM(s.ticket_id) != ''
                """,
                tuple(args),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict) or not row.get("bag_id"):
                    continue
                bid = str(row["bag_id"]).strip().upper()
                svc = str(row.get("service_type") or "WF").upper()
                rows[bid] = {
                    "bag_id": bid,
                    "service_type": svc if svc in ("WF", "HD") else "WF",
                    "date_clean": row.get("date_clean") or today,
                    "name_clean": row.get("name_clean"),
                    "in_active_staging": True,
                    "record_scope": "hd_lifecycle" if svc == "HD" else "wf_lifecycle",
                    "effective_rush": resolve_effective_rush_for_row({**row, "service_type": svc}, today),
                    "source_seen_in": ["orders_staging"],
                }

    if table_exists(cursor, "rinse_bag_registry"):
        svc_r = _service_expr("r")
        cursor.execute(
            f"""
            SELECT UPPER(TRIM(r.bag_id)) AS bag_id, {svc_r} AS service_type,
                   r.date_clean, r.name_clean, r.rush_type
            FROM rinse_bag_registry r
            WHERE r.organization_id = %s AND r.date_clean = %s
              AND r.bag_id IS NOT NULL AND TRIM(r.bag_id) != ''
            """,
            (org, today),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict) or not row.get("bag_id"):
                continue
            bid = str(row["bag_id"]).strip().upper()
            if bid in rows:
                continue
            svc = str(row.get("service_type") or "WF").upper()
            rows[bid] = {
                "bag_id": bid,
                "service_type": svc if svc in ("WF", "HD") else "WF",
                "date_clean": row.get("date_clean") or today,
                "name_clean": row.get("name_clean"),
                "in_active_staging": False,
                "registry_supplement": True,
                "record_scope": "hd_lifecycle" if svc == "HD" else "wf_lifecycle",
                "effective_rush": resolve_effective_rush_for_row({**row, "service_type": svc}, today),
                "source_seen_in": ["registry"],
            }

    return rows


def _merge_row(
    rows: dict[str, dict[str, Any]],
    row: Mapping[str, Any],
    *,
    source: str,
) -> None:
    bid = str(row.get("bag_id") or "").strip().upper()
    if not bid:
        return
    existing = rows.get(bid) or {"bag_id": bid}
    sources = list(existing.get("source_seen_in") or [])
    if source not in sources:
        sources.append(source)
    merged = {**existing, **{k: v for k, v in dict(row).items() if v is not None}}
    merged["source_seen_in"] = sources
    rows[bid] = merged


def load_all_at_vendor_presence_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    exclude_bag_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All active at_vendor presence rows (WF + HD) from portal scrape."""
    from backend.rinse_cleaner_ticket_presence import (
        PORTAL_STATUS_AT_VENDOR,
        _presence_effective_rush,
        _presence_service_type,
    )

    org = int(organization_id)
    excluded = {str(b or "").strip().upper() for b in (exclude_bag_ids or set()) if str(b or "").strip()}
    meta: dict[str, Any] = {"at_vendor_presence_wf": 0, "at_vendor_presence_hd": 0, "at_vendor_presence_unknown": 0}
    rows: list[dict[str, Any]] = []
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return rows, meta

    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               rush_flag, service_type, portal_status_first_seen_at, last_seen_at, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid or bid in excluded:
            continue
        svc_raw = _presence_service_type(raw) or str(raw.get("service_type") or "").strip().upper()
        svc = svc_raw if svc_raw in ("WF", "HD") else "WF"
        if svc == "HD":
            meta["at_vendor_presence_hd"] += 1
        elif svc == "WF":
            meta["at_vendor_presence_wf"] += 1
        else:
            meta["at_vendor_presence_unknown"] += 1
        rows.append(
            {
                "bag_id": bid,
                "service_type": svc,
                "effective_rush": _presence_effective_rush(raw, target_date),
                "name_clean": raw.get("customer_name"),
                "date_clean": raw.get("estimated_delivery_date"),
                "in_active_staging": False,
                "registry_supplement": False,
                "at_vendor_presence": True,
                "presence_source": True,
                "presence_portal_status": PORTAL_STATUS_AT_VENDOR,
                "record_scope": "hd_lifecycle" if svc == "HD" else "wf_lifecycle",
                "source_seen_in": ["at_vendor_presence"],
            }
        )
    return rows, meta


def load_unified_at_facility_population(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """
    Unified at-VeeWash population — staging + registry supplement + at_vendor presence.
    Matches lifecycle pending scope, not staging-only.
    """
    from backend.rinse_shift_analysis import (
        _load_hd_production_bag_rows,
        _load_pending_bag_rows,
        load_active_staging_population_rows,
    )

    org = int(organization_id)
    rows: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {
        "staging_count": 0,
        "registry_supplement_count": 0,
        "at_vendor_presence_count": 0,
        "wf_lifecycle_count": 0,
        "hd_lifecycle_count": 0,
    }

    staging_pop, staging_meta = load_active_staging_population_rows(cursor, org, target_date=target_date)
    meta["staging_count"] = len(staging_pop)
    for row in staging_pop:
        _merge_row(rows, row, source="orders_staging")

    wf_rows, wf_meta = _load_pending_bag_rows(cursor, org, target_date=target_date)
    hd_rows, hd_meta = _load_hd_production_bag_rows(cursor, org, target_date=target_date)
    meta["wf_lifecycle_count"] = len(wf_rows)
    meta["hd_lifecycle_count"] = len(hd_rows)
    meta["wf_lifecycle_meta"] = wf_meta
    meta["hd_lifecycle_meta"] = hd_meta

    for row in wf_rows:
        src = "registry" if row.get("registry_supplement") else (
            "at_vendor_presence" if row.get("presence_source") else "orders_staging"
        )
        if row.get("registry_supplement"):
            meta["registry_supplement_count"] += 1
        _merge_row(rows, row, source=src)

    for row in hd_rows:
        src = "registry" if row.get("registry_supplement") else (
            "at_vendor_presence" if row.get("at_vendor_presence") or row.get("presence_source") else "orders_staging"
        )
        if row.get("registry_supplement"):
            meta["registry_supplement_count"] += 1
        _merge_row(rows, row, source=src)

    seen = set(rows.keys())
    presence_rows, presence_meta = load_all_at_vendor_presence_rows(
        cursor, org, target_date=target_date, exclude_bag_ids=seen
    )
    meta["at_vendor_presence_count"] = len(presence_rows)
    meta["at_vendor_presence_meta"] = presence_meta
    for row in presence_rows:
        _merge_row(rows, row, source="at_vendor_presence")

    meta["unified_total"] = len(rows)
    meta["staging_meta"] = staging_meta
    return rows, meta


def load_unified_due_today_population(
    cursor,
    organization_id: int,
    today: date,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Due today from staging, registry, RFV/incoming presence, and lifecycle rows."""
    from backend.rinse_cleaner_ticket_presence import (
        PORTAL_STATUS_READY,
        _presence_effective_rush,
        _presence_service_type,
    )
    from backend.rinse_shift_analysis import _load_hd_production_bag_rows, _load_pending_bag_rows

    org = int(organization_id)
    rows = load_due_today_rows(cursor, org, today)
    meta: dict[str, Any] = {
        "staging_registry_count": len(rows),
        "rfv_incoming_count": 0,
        "lifecycle_due_today_count": 0,
    }

    for bid, row in list(rows.items()):
        srcs = list(row.get("source_seen_in") or [])
        if row.get("in_active_staging") and "orders_staging" not in srcs:
            srcs.append("orders_staging")
        elif row.get("registry_supplement") and "registry" not in srcs:
            srcs.append("registry")
        row["source_seen_in"] = srcs or ["orders_staging" if row.get("in_active_staging") else "registry"]

    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        cursor.execute(
            """
            SELECT bag_id, customer_name, estimated_delivery_date, service_type, raw_row_json, portal_status
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND active = 1 AND portal_status = %s
              AND estimated_delivery_date = %s
            """,
            (org, PORTAL_STATUS_READY, today),
        )
        for raw in cursor.fetchall() or []:
            if not isinstance(raw, dict) or not raw.get("bag_id"):
                continue
            bid = str(raw["bag_id"]).strip().upper()
            svc = _presence_service_type(raw) or str(raw.get("service_type") or "WF").upper()
            row = {
                "bag_id": bid,
                "service_type": svc if svc in ("WF", "HD") else "WF",
                "date_clean": today,
                "name_clean": raw.get("customer_name"),
                "effective_rush": _presence_effective_rush(raw, today),
                "record_scope": "incoming",
                "ready_for_vendor": True,
                "presence_source": True,
            }
            _merge_row(rows, row, source="ready_for_vendor_presence")
            meta["rfv_incoming_count"] += 1

    wf_rows, _ = _load_pending_bag_rows(cursor, org, target_date=today)
    hd_rows, _ = _load_hd_production_bag_rows(cursor, org, target_date=today)
    for row in wf_rows + hd_rows:
        if parse_record_date(row.get("date_clean")) != today:
            continue
        src = "lifecycle"
        if row.get("registry_supplement"):
            src = "registry"
        elif row.get("in_active_staging"):
            src = "orders_staging"
        elif row.get("presence_source") or row.get("at_vendor_presence"):
            src = "at_vendor_presence"
        _merge_row(rows, row, source=src)
        meta["lifecycle_due_today_count"] += 1

    meta["unified_due_today_total"] = len(rows)
    return rows, meta


def build_vendor_home_gap_analysis(
    *,
    records: Sequence[Mapping[str, Any]],
    unified_at_facility: Mapping[str, Mapping[str, Any]],
    unified_due_today: Mapping[str, Mapping[str, Any]],
    cfs_reconciliation: Mapping[str, Any],
    dts_reconciliation: Mapping[str, Any],
    unified_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain mismatch vs Vendor Home reference with identifiable missing/excluded records."""
    ref = VENDOR_HOME_REFERENCE
    dash_at = int(cfs_reconciliation.get("dashboard_at_facility") or cfs_reconciliation.get("at_facility_total") or 0)
    dash_proc = int(cfs_reconciliation.get("dashboard_in_progress") or cfs_reconciliation.get("in_progress") or 0)
    dash_due = int(dts_reconciliation.get("dashboard_due_today") or dts_reconciliation.get("due_today_total") or 0)
    dash_due_proc = int(
        dts_reconciliation.get("dashboard_due_today_pending") or dts_reconciliation.get("due_today_yet_to_process") or 0
    )

    cfs_ids = {
        str(r.get("bag_id") or "").strip().upper()
        for r in records
        if "cfs_total" in (r.get("drilldown_tags") or []) and r.get("bag_id")
    }
    sent_left_ids = {
        str(r.get("bag_id") or "").strip().upper()
        for r in records
        if "cfs_sent_left" in (r.get("drilldown_tags") or []) and r.get("bag_id")
    }
    staging_only = {
        bid for bid, row in unified_at_facility.items()
        if (row.get("source_seen_in") or []) == ["orders_staging"]
    }
    not_staging = {
        bid for bid, row in unified_at_facility.items()
        if bid in cfs_ids and "orders_staging" not in (row.get("source_seen_in") or [])
    }

    missing_or_excluded: list[dict[str, Any]] = []
    for bid in sorted(not_staging)[:25]:
        row = unified_at_facility.get(bid) or {}
        rec = next((r for r in records if str(r.get("bag_id") or "").upper() == bid), {})
        missing_or_excluded.append(
            {
                "ticket_id": bid,
                "bag_id": bid,
                "customer": row.get("name_clean") or rec.get("customer"),
                "edd": parse_record_date(row.get("date_clean") or rec.get("date_clean")),
                "service_type": row.get("service_type") or rec.get("service_type"),
                "source_seen_in": row.get("source_seen_in") or [],
                "excluded_reason": "Included via registry/presence — was missing from active orders_staging-only snapshot",
            }
        )

    for bid in sorted(sent_left_ids & set(unified_at_facility.keys()))[:15]:
        row = unified_at_facility.get(bid) or {}
        rec = next((r for r in records if str(r.get("bag_id") or "").upper() == bid), {})
        missing_or_excluded.append(
            {
                "ticket_id": bid,
                "bag_id": bid,
                "customer": row.get("name_clean") or rec.get("customer"),
                "edd": parse_record_date(row.get("date_clean") or rec.get("date_clean")),
                "service_type": row.get("service_type") or rec.get("service_type"),
                "source_seen_in": row.get("source_seen_in") or [],
                "excluded_reason": "In unified population but excluded from At Facility Total (sent/left or completed checkout)",
            }
        )

    presence_count = int((unified_meta or {}).get("at_vendor_presence_count") or 0)
    notes: list[str] = []
    if presence_count == 0:
        notes.append(
            "rinse_cleaner_ticket_presence is empty for this org — At Vendor / RFV portal scrape not loaded locally. "
            "Vendor Home likely includes portal rows we cannot match until presence sync runs."
        )
    if dash_at != ref.get("at_veewash_total"):
        notes.append(
            f"Unified at-facility population={len(unified_at_facility)} tagged cfs_total={dash_at} "
            f"vs Vendor Home {ref.get('at_veewash_total')}. "
            f"Gap may be unscrape portal rows ({ref.get('at_veewash_total', 0) - len(unified_at_facility)} bags)."
        )
    if dash_due != ref.get("due_today_total"):
        notes.append(
            f"Unified due-today population={len(unified_due_today)} vs Vendor Home {ref.get('due_today_total')}. "
            "Missing due-today RFV/incoming rows likely require presence scrape."
        )
    if not missing_or_excluded and dash_at != ref.get("at_veewash_total"):
        missing_or_excluded.append(
            {
                "excluded_reason": (
                    "Cannot identify exact missing bag IDs from Vendor Home summary only — "
                    "need direct scrape of Vendor Home underlying list or successful At Vendor presence sync."
                )
            }
        )

    return {
        "vendor_home_at_veewash": ref.get("at_veewash_total"),
        "dashboard_at_facility": dash_at,
        "unified_at_facility_population": len(unified_at_facility),
        "difference_at_facility": dash_at - int(ref.get("at_veewash_total") or 0),
        "portal_scrape_gap_at_facility": int(ref.get("at_veewash_total") or 0) - len(unified_at_facility),
        "cfs_sent_left_excluded_count": len(sent_left_ids),
        "vendor_home_yet_to_process": ref.get("at_veewash_yet_to_process"),
        "dashboard_in_progress": dash_proc,
        "difference_in_progress": dash_proc - int(ref.get("at_veewash_yet_to_process") or 0),
        "vendor_home_due_today": ref.get("due_today_total"),
        "dashboard_due_today": dash_due,
        "unified_due_today_population": len(unified_due_today),
        "difference_due_today": dash_due - int(ref.get("due_today_total") or 0),
        "portal_scrape_gap_due_today": int(ref.get("due_today_total") or 0) - len(unified_due_today),
        "vendor_home_due_today_yet_to_process": ref.get("due_today_yet_to_process"),
        "dashboard_due_today_pending": dash_due_proc,
        "difference_due_today_pending": dash_due_proc - int(ref.get("due_today_yet_to_process") or 0),
        "staging_only_at_facility_count": len(staging_only),
        "non_staging_at_facility_count": len(not_staging),
        "missing_or_excluded_records": missing_or_excluded,
        "notes": notes,
        "ok": bool(cfs_reconciliation.get("ok")) and bool(dts_reconciliation.get("ok")),
    }


def _has_weight_entry(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_weight_entry_purpose(ev.get("purpose")) for ev in events)


def _has_start_cleaning(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_start_cleaning_purpose(ev.get("purpose")) for ev in events)


def _has_drying(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_drying_purpose(ev.get("purpose")) for ev in events)


def _merged_snapshot_fields(
    pending_row: Mapping[str, Any] | None,
    meta: Mapping[str, Any],
    *,
    record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out = {**dict(meta or {}), **dict(pending_row or {})}
    if record:
        for key in (
            "raw_status",
            "current_stage",
            "current_status",
            "current_lifecycle_status",
            "completed",
            "completion_kind",
        ):
            val = record.get(key)
            if val is not None and val != "":
                out[key] = val
    return out


def scan_events_indicate_sent_left(events: Sequence[Mapping[str, Any]] | None) -> bool:
    for ev in events or []:
        if scan_purpose_indicates_sent_left(ev.get("purpose")):
            return True
    return False


def wf_lifecycle_or_meta_indicates_complete(
    pending_row: Mapping[str, Any] | None,
    meta: Mapping[str, Any],
    *,
    record: Mapping[str, Any] | None = None,
) -> bool:
    merged = _merged_snapshot_fields(pending_row, meta, record=record)
    status = str(
        merged.get("current_lifecycle_status")
        or merged.get("raw_status")
        or merged.get("current_status")
        or merged.get("current_stage")
        or merged.get("lifecycle_status")
        or ""
    ).upper()
    if status in LIFECYCLE_COMPLETED_STATUSES or status == FOLDED_COMPLETED:
        return True
    for key in (
        "processed_by_vendor",
        "received_from_vendor",
        "vendor_processed",
        "vendor_received",
        "processed_by_vendor_checked",
        "received_from_vendor_checked",
    ):
        val = merged.get(key)
        if val in (True, 1, "1", "checked", "yes", "true", "Y", "CHECKED"):
            return True
    return False


def wf_scan_events_indicate_complete(events: Sequence[Mapping[str, Any]] | None) -> bool:
    for ev in events or []:
        if rack_contains_clean(ev.get("rack")):
            return True
        purpose = ev.get("purpose")
        if is_processed_by_vendor_purpose(purpose) or is_received_from_vendor_purpose(purpose):
            return True
    return find_strong_completion_evidence_v2(events or []) is not None


def bag_is_sent_left_from_facility(
    pending_row: Mapping[str, Any] | None,
    completion: Any,
    meta: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] | None = None,
    *,
    completion_events: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Sent/left for Current Facility Snapshot — still-at-facility complete bags stay counted."""
    timeline = list(completion_events if completion_events is not None else (events or []))
    if scan_events_indicate_sent_left(timeline):
        return True
    merged: dict[str, Any] = {**dict(meta or {}), **dict(pending_row or {})}
    lifecycle = str(
        merged.get("current_lifecycle_status")
        or merged.get("current_status")
        or merged.get("lifecycle_status")
        or ""
    ).upper()
    logistics = str(merged.get("logistics_status") or merged.get("status") or "").upper()
    if lifecycle in _LOGISTICS_SENT or lifecycle == SENT_TO_RINSE:
        return True
    if logistics in _LOGISTICS_SENT:
        return True
    op_complete = bag_is_operationally_complete(
        service_type=str(merged.get("service_type") or "WF"),
        completion=completion,
        events=events or [],
        pending_row=pending_row,
        meta=meta,
        completion_events=timeline,
    )
    if op_complete and pending_row and pending_row.get("in_active_staging"):
        return False
    return bag_is_sent_or_left(pending_row, completion, meta, timeline)


def bag_is_due_today_processed(
    *,
    operationally_complete: bool,
    sent_left: bool,
) -> bool:
    return operationally_complete or sent_left


def bag_is_operationally_complete(
    *,
    service_type: str,
    completion: Any,
    events: Sequence[Mapping[str, Any]],
    pending_row: Mapping[str, Any] | None,
    meta: Mapping[str, Any],
    completion_events: Sequence[Mapping[str, Any]] | None = None,
    record: Mapping[str, Any] | None = None,
) -> bool:
    svc = str(service_type or "").upper()
    timeline = list(completion_events if completion_events is not None else events)
    if svc == "HD":
        from backend.rinse_hd_production_status import derive_hd_production_status

        hd = derive_hd_production_status(
            timeline,
            at_vendor_presence=True,
            logistics_status=meta.get("logistics_status") or meta.get("status"),
            lifecycle_status=(pending_row or {}).get("current_lifecycle_status"),
        )
        return bool(hd.get("hd_completed"))
    if completion and getattr(completion, "completed", False):
        return True
    if wf_lifecycle_or_meta_indicates_complete(pending_row, meta, record=record):
        return True
    if wf_scan_events_indicate_complete(timeline):
        return True
    return False


def classify_current_facility_bag(
    *,
    in_active_staging: bool,
    sent_left: bool,
    operationally_complete: bool,
) -> str | None:
    if not in_active_staging:
        return None
    if sent_left:
        return CFS_SENT_LEFT
    if operationally_complete:
        return CFS_COMPLETED_STILL
    return CFS_IN_PROGRESS


def wf_in_progress_bucket_and_reason(
    *,
    has_weigh: bool,
    has_start_cleaning: bool,
    has_drying: bool,
    pending_folding: bool,
) -> tuple[str, str]:
    if not has_weigh:
        return "wf_not_weighed", "No weight-entry after facility entry"
    if not has_start_cleaning:
        return "wf_weighed_not_started", "Weight entry exists, but start-cleaning is missing."
    if not has_drying:
        return "wf_pending_drying", "start-cleaning exists, drying scan missing"
    if pending_folding:
        return "wf_pending_folding", "dried but not folded/completed on our side"
    return "wf_started_washing", "start-cleaning and drying exist; awaiting fold/completion"


def hd_in_progress_bucket_and_reason(
    *,
    hd_production: Mapping[str, Any],
) -> tuple[str, str]:
    if not hd_production.get("hd_started"):
        return "hd_not_started", "HD order has no workitem/create-workitem after facility entry"
    return "hd_started_cleaning", "workitem exists, add-photos after workitem missing"


def build_vendor_home_reconciliation(
    *,
    at_facility: int,
    in_progress: int,
    completed_still: int,
    rinse_home_at_veewash: int | None = None,
    rinse_home_yet_to_process: int | None = None,
) -> dict[str, Any]:
    ref_at = rinse_home_at_veewash if rinse_home_at_veewash is not None else VENDOR_HOME_REFERENCE.get("at_veewash_total")
    ref_proc = (
        rinse_home_yet_to_process
        if rinse_home_yet_to_process is not None
        else VENDOR_HOME_REFERENCE.get("at_veewash_yet_to_process")
    )
    out: dict[str, Any] = {
        "dashboard_at_facility": at_facility,
        "dashboard_in_progress": in_progress,
        "completed_still_at_facility": completed_still,
        "at_facility_total": at_facility,
        "in_progress": in_progress,
        "rinse_home_at_veewash": ref_at,
        "rinse_home_yet_to_process": ref_proc,
        "difference_at_facility": None,
        "difference_in_progress": None,
        "reconciled_at_facility": None,
        "reconciled_in_progress": None,
        "identity_ok": in_progress + completed_still == at_facility,
        "ok": in_progress + completed_still == at_facility,
        "comparison_status": "Vendor Home comparison pending — manually verify against Rinse Home",
        "vendor_home_reference_source": VENDOR_HOME_REFERENCE.get("vendor_home_reference_source"),
    }
    if ref_at is not None:
        out["difference_at_facility"] = at_facility - int(ref_at)
        out["reconciled_at_facility"] = out["difference_at_facility"] == 0
    if ref_proc is not None:
        out["difference_in_progress"] = in_progress - int(ref_proc)
        out["reconciled_in_progress"] = out["difference_in_progress"] == 0
    if ref_at is not None and ref_proc is not None:
        vendor_ok = bool(out["reconciled_at_facility"] and out["reconciled_in_progress"])
        out["ok"] = bool(out["identity_ok"]) and vendor_ok
        if vendor_ok and out["identity_ok"]:
            out["comparison_status"] = "Reconciled to Rinse Vendor Home"
        else:
            out["comparison_status"] = "Mismatch vs Rinse Vendor Home — see differences"
    return out


def build_due_today_reconciliation(
    *,
    due_today_total: int,
    yet_to_process: int,
    completed_processed: int,
    rinse_due_today_total: int | None = None,
    rinse_due_today_yet_to_process: int | None = None,
) -> dict[str, Any]:
    ref_total = (
        rinse_due_today_total
        if rinse_due_today_total is not None
        else VENDOR_HOME_REFERENCE.get("due_today_total")
    )
    ref_pending = (
        rinse_due_today_yet_to_process
        if rinse_due_today_yet_to_process is not None
        else VENDOR_HOME_REFERENCE.get("due_today_yet_to_process")
    )
    out: dict[str, Any] = {
        "dashboard_due_today": due_today_total,
        "dashboard_due_today_pending": yet_to_process,
        "dashboard_due_today_completed": completed_processed,
        "due_today_total": due_today_total,
        "due_today_yet_to_process": yet_to_process,
        "due_today_completed_processed": completed_processed,
        "rinse_due_today_total": ref_total,
        "rinse_due_today_yet_to_process": ref_pending,
        "difference_due_today": None,
        "difference_due_today_pending": None,
        "identity_ok": yet_to_process + completed_processed == due_today_total,
        "ok": yet_to_process + completed_processed == due_today_total,
        "comparison_status": "Due today comparison pending — manually verify against Rinse Home",
        "vendor_home_reference_source": VENDOR_HOME_REFERENCE.get("vendor_home_reference_source"),
    }
    if ref_total is not None:
        out["difference_due_today"] = due_today_total - int(ref_total)
        out["reconciled_due_today"] = out["difference_due_today"] == 0
    if ref_pending is not None:
        out["difference_due_today_pending"] = yet_to_process - int(ref_pending)
        out["reconciled_due_today_pending"] = out["difference_due_today_pending"] == 0
    if ref_total is not None and ref_pending is not None:
        vendor_ok = bool(out.get("reconciled_due_today") and out.get("reconciled_due_today_pending"))
        out["ok"] = bool(out["identity_ok"]) and vendor_ok
        if vendor_ok and out["identity_ok"]:
            out["comparison_status"] = "Reconciled to Rinse Vendor Home — due today"
        else:
            out["comparison_status"] = "Mismatch vs Rinse Vendor Home — due today"
    return out


def build_vendor_home_debug_audit(
    *,
    cfs_reconciliation: Mapping[str, Any],
    dts_reconciliation: Mapping[str, Any],
    cfs_debug_ids: Mapping[str, Sequence[str]],
    dts_debug_ids: Mapping[str, Sequence[str]],
    gap_analysis: Mapping[str, Any] | None = None,
    unified_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ref = VENDOR_HOME_REFERENCE
    out = {
        "vendor_home_reference": {
            "source": ref.get("source") or ref.get("vendor_home_reference_source"),
            "date": ref.get("reference_date"),
            "at_veewash_total": ref.get("at_veewash_total"),
            "at_veewash_yet_to_process": ref.get("at_veewash_yet_to_process"),
            "due_today_total": ref.get("due_today_total"),
            "due_today_yet_to_process": ref.get("due_today_yet_to_process"),
        },
        "current_facility_snapshot": {
            "dashboard_at_facility": cfs_reconciliation.get("dashboard_at_facility"),
            "dashboard_in_progress": cfs_reconciliation.get("dashboard_in_progress"),
            "completed_still_at_facility": cfs_reconciliation.get("completed_still_at_facility"),
            "difference_at_facility": cfs_reconciliation.get("difference_at_facility"),
            "difference_in_progress": cfs_reconciliation.get("difference_in_progress"),
            "ok": cfs_reconciliation.get("ok"),
            **dict(cfs_debug_ids),
        },
        "due_today_snapshot": {
            "dashboard_due_today": dts_reconciliation.get("dashboard_due_today"),
            "dashboard_due_today_pending": dts_reconciliation.get("dashboard_due_today_pending"),
            "dashboard_due_today_completed": dts_reconciliation.get("dashboard_due_today_completed"),
            "difference_due_today": dts_reconciliation.get("difference_due_today"),
            "difference_due_today_pending": dts_reconciliation.get("difference_due_today_pending"),
            "ok": dts_reconciliation.get("ok"),
            **dict(dts_debug_ids),
        },
        "unified_population_meta": dict(unified_meta or {}),
        "vendor_home_gap_analysis": dict(gap_analysis or {}),
    }
    return out


def build_snapshot_debug_ids(records: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    def _ids(tag: str) -> list[str]:
        return sorted(
            str(r.get("bag_id") or "").strip().upper()
            for r in records
            if tag in (r.get("drilldown_tags") or []) and r.get("bag_id")
        )

    return {
        "cfs_total_ids": _ids("cfs_total"),
        "cfs_in_progress_ids": _ids("cfs_in_progress"),
        "cfs_completed_still_at_facility_ids": _ids("cfs_completed_still_at_facility"),
        "wf_weighed_not_started_ids": _ids("wf_weighed_not_started"),
        "hd_not_started_ids": _ids("hd_not_started"),
    }


def build_due_today_debug_ids(records: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    def _ids(tag: str) -> list[str]:
        return sorted(
            str(r.get("bag_id") or "").strip().upper()
            for r in records
            if tag in (r.get("drilldown_tags") or []) and r.get("bag_id")
        )

    return {
        "dts_total_ids": _ids("dts_total"),
        "dts_yet_to_process_ids": _ids("dts_yet_to_process"),
        "dts_completed_processed_ids": _ids("dts_completed_processed"),
        "dts_wf_pending_ids": _ids("dts_wf_pending"),
        "dts_hd_pending_ids": _ids("dts_hd_pending"),
        "scan_dts_yet_to_process_ids": _ids("scan_dts_yet_to_process"),
        "scan_dts_completed_ids": _ids("scan_dts_completed_processed"),
    }


def count_presence_rows(cursor, organization_id: int) -> dict[str, Any]:
    """Active at_vendor / RFV presence row counts for parity alerts."""
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_READY

    org = int(organization_id)
    out: dict[str, Any] = {
        "at_vendor_active": 0,
        "rfv_active": 0,
        "portal_list_available": False,
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return out
    for ps, key in ((PORTAL_STATUS_AT_VENDOR, "at_vendor_active"), (PORTAL_STATUS_READY, "rfv_active")):
        cursor.execute(
            """
            SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND active = 1 AND portal_status = %s
            """,
            (org, ps),
        )
        row = cursor.fetchone()
        out[key] = int((row or {}).get("c") or 0)
    out["portal_list_available"] = out["at_vendor_active"] > 0 or out["rfv_active"] > 0
    return out


def portal_at_vendor_yet_to_process(row: Mapping[str, Any]) -> bool:
    """Portal yet-to-process — conservative when cleaning-step text is missing."""
    from backend.rinse_cleaner_ticket_presence import _presence_raw_row_json

    raw = _presence_raw_row_json(row)
    steps = str(raw.get("steps_in_cleaning_process") or row.get("steps_in_cleaning_process") or "").strip().lower()
    if not steps:
        return True
    done_markers = ("complete", "completed", "delivered", "picked up", "out for delivery", "checked out")
    return not any(m in steps for m in done_markers)


def portal_at_vendor_has_cleaning_steps(row: Mapping[str, Any]) -> bool:
    """True when portal scrape captured steps_in_cleaning_process for this row."""
    from backend.rinse_cleaner_ticket_presence import _presence_raw_row_json

    raw = _presence_raw_row_json(row)
    steps = str(raw.get("steps_in_cleaning_process") or row.get("steps_in_cleaning_process") or "").strip()
    return bool(steps)


PORTAL_YTP_SOURCE_CLEANING_STEPS = "portal_cleaning_steps"
PORTAL_YTP_SOURCE_INFERRED_FALLBACK = "inferred_fallback"
PORTAL_YTP_SOURCE_PARTIAL_INFERRED = "partial_inferred_fallback"
PORTAL_YTP_SOURCE_NO_ACTIVE_PRESENCE = "no_active_presence"
PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT = "vendor_home_page_direct"
PORTAL_SNAPSHOT_SOURCE_PRESENCE_LIST = "portal_presence_list"
PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE = "unavailable"


def _parse_json_obj(raw: Any) -> dict[str, Any] | None:
    import json

    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return dict(parsed) if isinstance(parsed, dict) else None
    return None


def extract_vendor_home_summary_from_scrape_meta(
    scrape_meta: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize direct Vendor Home summary counts from presence scrape metadata."""
    meta = dict(scrape_meta or {})
    summary = _parse_json_obj(meta.get("vendor_home_summary")) or _parse_json_obj(
        meta.get("vendor_home_counts")
    )
    if not summary:
        return None

    def _int_field(*keys: str) -> int | None:
        for key in keys:
            if key not in summary or summary.get(key) is None:
                continue
            try:
                return int(summary[key])
            except (TypeError, ValueError):
                continue
        return None

    orders_at_veewash = _int_field("orders_at_veewash", "at_veewash_total")
    orders_ytp = _int_field(
        "orders_at_veewash_yet_to_process",
        "at_veewash_yet_to_process",
    )
    due_today = _int_field("due_today", "due_today_total")
    due_ytp = _int_field("due_today_yet_to_process")
    if all(v is None for v in (orders_at_veewash, orders_ytp, due_today, due_ytp)):
        return None

    scraped_at = summary.get("scraped_at") or meta.get("scraped_at")
    return {
        "source": PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT,
        "scraped_at": scraped_at,
        "orders_at_veewash": orders_at_veewash,
        "orders_at_veewash_yet_to_process": orders_ytp,
        "due_today": due_today,
        "due_today_yet_to_process": due_ytp,
        "reliable": orders_at_veewash is not None or orders_ytp is not None,
    }


def load_latest_vendor_home_direct_counts(
    cursor,
    organization_id: int,
) -> dict[str, Any]:
    """
    Latest direct Vendor Home summary scraped during presence sync.
    Stored on rinse_cleaner_ticket_presence_runs.scrape_meta_json.vendor_home_summary.
    """
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR

    org = int(organization_id)
    out: dict[str, Any] = {
        "available": False,
        "source": PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE,
        "orders_at_veewash": None,
        "orders_at_veewash_yet_to_process": None,
        "due_today": None,
        "due_today_yet_to_process": None,
        "scraped_at": None,
        "presence_run_id": None,
        "presence_run_finished_at": None,
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return out

    cursor.execute(
        """
        SELECT id, finished_at, scrape_meta_json
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s
          AND portal_status = %s
          AND status = 'success'
        ORDER BY finished_at DESC, id DESC
        LIMIT 1
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return out

    summary = extract_vendor_home_summary_from_scrape_meta(
        _parse_json_obj(row.get("scrape_meta_json"))
    )
    if not summary:
        return out

    out.update(summary)
    out["available"] = True
    out["presence_run_id"] = row.get("id")
    finished = row.get("finished_at")
    out["presence_run_finished_at"] = (
        finished.isoformat() if hasattr(finished, "isoformat") else finished
    )
    return out


def build_portal_snapshot_vendor_home_fields(
    cursor,
    organization_id: int,
    *,
    today: date,
    module: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Current Portal Snapshot display fields for /performance.
    Prefers direct Vendor Home page counts; never uses missing cleaning-step inference for ytp.
    """
    av = dict(module or {})
    org = int(organization_id)
    direct = load_latest_vendor_home_direct_counts(cursor, org)
    presence_meta = count_presence_rows(cursor, org)
    presence_total = int(presence_meta.get("at_vendor_active") or 0)

    orders_at_veewash: int | None = None
    orders_source = PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE
    orders_reliable = False

    if direct.get("available") and direct.get("orders_at_veewash") is not None:
        orders_at_veewash = int(direct["orders_at_veewash"])
        orders_source = PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT
        orders_reliable = True
    elif presence_total > 0:
        orders_at_veewash = presence_total
        orders_source = PORTAL_SNAPSHOT_SOURCE_PRESENCE_LIST
        orders_reliable = True
    elif av.get("current_portal_snapshot_total") is not None:
        orders_at_veewash = int(av.get("current_portal_snapshot_total") or 0)
        orders_source = PORTAL_SNAPSHOT_SOURCE_PRESENCE_LIST
        orders_reliable = True

    ytp: int | None = None
    ytp_reliable = False
    ytp_source = PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE
    if direct.get("available") and direct.get("orders_at_veewash_yet_to_process") is not None:
        ytp = int(direct["orders_at_veewash_yet_to_process"])
        ytp_reliable = True
        ytp_source = PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT

    due_today: int | None = None
    due_today_reliable = False
    due_today_source = PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE
    if direct.get("available") and direct.get("due_today") is not None:
        due_today = int(direct["due_today"])
        due_today_reliable = True
        due_today_source = PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT

    due_ytp: int | None = None
    due_ytp_reliable = False
    due_ytp_source = PORTAL_SNAPSHOT_SOURCE_UNAVAILABLE
    if direct.get("available") and direct.get("due_today_yet_to_process") is not None:
        due_ytp = int(direct["due_today_yet_to_process"])
        due_ytp_reliable = True
        due_ytp_source = PORTAL_SNAPSHOT_SOURCE_VENDOR_HOME_DIRECT

    presence_reconciliation = {
        "active_at_vendor_presence_count": presence_total,
        "direct_vendor_home_total": direct.get("orders_at_veewash"),
        "difference": (
            presence_total - int(direct["orders_at_veewash"])
            if direct.get("orders_at_veewash") is not None
            else None
        ),
    }

    return {
        "orders_at_veewash": orders_at_veewash,
        "orders_at_veewash_reliable": orders_reliable,
        "orders_at_veewash_source": orders_source,
        "orders_at_veewash_yet_to_process": ytp if ytp_reliable else None,
        "orders_at_veewash_yet_to_process_reliable": ytp_reliable,
        "orders_at_veewash_yet_to_process_source": ytp_source,
        "due_today": due_today,
        "due_today_reliable": due_today_reliable,
        "due_today_source": due_today_source,
        "due_today_yet_to_process": due_ytp if due_ytp_reliable else None,
        "due_today_yet_to_process_reliable": due_ytp_reliable,
        "due_today_yet_to_process_source": due_ytp_source,
        "portal_snapshot_scrape_at": direct.get("scraped_at") or direct.get("presence_run_finished_at"),
        "portal_snapshot_presence_run_id": direct.get("presence_run_id"),
        "portal_snapshot_presence_reconciliation": presence_reconciliation,
        "current_portal_snapshot_total": orders_at_veewash,
        "portal_snapshot_yet_to_process": ytp if ytp_reliable else None,
        "portal_snapshot_yet_to_process_reliable": ytp_reliable,
        "portal_snapshot_yet_to_process_source": ytp_source,
    }


def summarize_portal_snapshot_yet_to_process(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Summarize yet-to-process for active at_vendor portal snapshot rows.

    Count is only returned when every row has portal cleaning-step metadata.
    Missing steps default portal_at_vendor_yet_to_process() to True (conservative fallback)
    and must not be shown as a trusted Vendor Home pending count.
    """
    total = len(rows)
    if total == 0:
        return {
            "portal_snapshot_yet_to_process": None,
            "portal_snapshot_yet_to_process_reliable": False,
            "portal_snapshot_yet_to_process_source": PORTAL_YTP_SOURCE_NO_ACTIVE_PRESENCE,
            "portal_snapshot_yet_to_process_rows_with_steps": 0,
            "portal_snapshot_yet_to_process_rows_total": 0,
        }

    with_steps = sum(1 for row in rows if portal_at_vendor_has_cleaning_steps(row))
    reliable = with_steps == total
    if reliable:
        source = PORTAL_YTP_SOURCE_CLEANING_STEPS
    elif with_steps == 0:
        source = PORTAL_YTP_SOURCE_INFERRED_FALLBACK
    else:
        source = PORTAL_YTP_SOURCE_PARTIAL_INFERRED

    yet_to_process = sum(1 for row in rows if portal_at_vendor_yet_to_process(row))
    return {
        "portal_snapshot_yet_to_process": yet_to_process if reliable else None,
        "portal_snapshot_yet_to_process_reliable": reliable,
        "portal_snapshot_yet_to_process_source": source,
        "portal_snapshot_yet_to_process_rows_with_steps": with_steps,
        "portal_snapshot_yet_to_process_rows_total": total,
    }


def load_portal_vendor_home_counts(
    cursor,
    organization_id: int,
    today: date,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Counts from rinse_cleaner_ticket_presence when loaded.
    Returns (counts or None, presence_meta, at_vendor_rows).
    """
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_READY

    org = int(organization_id)
    meta = count_presence_rows(cursor, org)
    at_rows: list[dict[str, Any]] = []
    due_rows: list[dict[str, Any]] = []

    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return None, meta, at_rows, due_rows

    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    at_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    with_steps = sum(1 for r in at_rows if portal_at_vendor_has_cleaning_steps(r))
    ytp_reliable = bool(at_rows) and with_steps == len(at_rows)
    ytp = sum(1 for r in at_rows if portal_at_vendor_yet_to_process(r)) if ytp_reliable else None
    processed = (len(at_rows) - int(ytp)) if ytp is not None else None

    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1
          AND portal_status IN (%s, %s)
          AND estimated_delivery_date = %s
        """,
        (org, PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_READY, today),
    )
    due_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    due_ytp = sum(
        1
        for r in due_rows
        if portal_at_vendor_yet_to_process(r) or str(r.get("portal_status")) == PORTAL_STATUS_READY
    )
    due_processed = len(due_rows) - due_ytp

    if not meta["portal_list_available"]:
        return None, meta, at_rows, due_rows

    counts = {
        "source": "portal_presence",
        "at_veewash_total": len(at_rows),
        "at_veewash_yet_to_process": ytp,
        "at_veewash_yet_to_process_reliable": ytp_reliable,
        "at_veewash_processed": processed,
        "due_today_total": len(due_rows),
        "due_today_yet_to_process": due_ytp,
        "due_today_processed": due_processed,
    }
    return counts, meta, at_rows, due_rows


def manual_vendor_home_counts() -> dict[str, Any]:
    ref = VENDOR_HOME_REFERENCE
    at_total = int(ref.get("at_veewash_total") or 0)
    at_ytp = int(ref.get("at_veewash_yet_to_process") or 0)
    due_total = int(ref.get("due_today_total") or 0)
    due_ytp = int(ref.get("due_today_yet_to_process") or 0)
    return {
        "source": "manual_screenshot",
        "reference_date": ref.get("reference_date"),
        "at_veewash_total": at_total,
        "at_veewash_yet_to_process": at_ytp,
        "at_veewash_processed": max(0, at_total - at_ytp),
        "due_today_total": due_total,
        "due_today_yet_to_process": due_ytp,
        "due_today_processed": max(0, due_total - due_ytp),
    }


def apply_portal_vendor_home_tags_on_records(
    records: list[dict[str, Any]],
    *,
    at_vendor_rows: Sequence[Mapping[str, Any]],
    due_today_portal_rows: Sequence[Mapping[str, Any]],
) -> None:
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_READY

    rec_by_id = {str(r.get("bag_id") or "").strip().upper(): r for r in records if r.get("bag_id")}
    for raw in at_vendor_rows:
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        rec = rec_by_id.get(bid) or {
            "bag_id": bid,
            "customer": raw.get("customer_name"),
            "service_type": str(raw.get("service_type") or "WF").upper(),
            "source_seen_in": ["at_vendor_presence"],
        }
        if bid not in rec_by_id:
            records.append(rec)
            rec_by_id[bid] = rec
        tags = set(rec.get("drilldown_tags") or [])
        tags.add(PORTAL_VH_AT_VENDOR)
        if portal_at_vendor_yet_to_process(raw):
            tags.add(PORTAL_VH_YET_TO_PROCESS)
        edd = parse_record_date(raw.get("estimated_delivery_date"))
        if edd:
            iso = edd.isoformat()
            rec["date_clean"] = iso
            rec["due_date"] = iso
        rec["vendor_home_bucket_reason"] = "At VeeWash per portal presence (at_vendor)"
        rec["drilldown_tags"] = sorted(tags)

    for raw in due_today_portal_rows:
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        rec = rec_by_id.get(bid) or {
            "bag_id": bid,
            "customer": raw.get("customer_name"),
            "service_type": str(raw.get("service_type") or "WF").upper(),
            "source_seen_in": ["at_vendor_presence" if str(raw.get("portal_status")) != PORTAL_STATUS_READY else "ready_for_vendor_presence"],
        }
        if bid not in rec_by_id:
            records.append(rec)
            rec_by_id[bid] = rec
        tags = set(rec.get("drilldown_tags") or [])
        tags.add(PORTAL_VH_DTS_TOTAL)
        is_pending = portal_at_vendor_yet_to_process(raw) or str(raw.get("portal_status")) == PORTAL_STATUS_READY
        if is_pending:
            tags.add(PORTAL_VH_DTS_PENDING)
        edd = parse_record_date(raw.get("estimated_delivery_date"))
        if edd:
            rec["date_clean"] = edd.isoformat()
            rec["due_date"] = edd.isoformat()
        rec["vendor_home_bucket_reason"] = "Due today per portal presence EDD"
        rec["drilldown_tags"] = sorted(tags)


def backfill_record_due_dates(
    records: list[dict[str, Any]],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    *,
    presence_edd_by_bag: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Backfill date_clean/due_date on drilldown rows from staging → registry → presence."""
    missing_before = 0
    missing_after = 0
    presence_edd = presence_edd_by_bag or {}
    for rec in records:
        if parse_record_date(rec.get("date_clean") or rec.get("due_date")):
            continue
        missing_before += 1
        bid = str(rec.get("bag_id") or "").strip().upper()
        meta = meta_by_bag.get(bid) or {}
        dc = (
            parse_record_date(meta.get("date_clean"))
            or parse_record_date(meta.get("due_date"))
            or parse_record_date(presence_edd.get(bid))
        )
        if dc:
            iso = dc.isoformat()
            rec["date_clean"] = iso
            rec["due_date"] = iso
            if meta.get("date_clean"):
                rec["due_date_source"] = "orders_staging"
            elif meta.get("due_date"):
                rec["due_date_source"] = "registry"
            else:
                rec["due_date_source"] = "presence"
        if not parse_record_date(rec.get("date_clean") or rec.get("due_date")):
            missing_after += 1
    return {"missing_before": missing_before, "missing_after": missing_after}


def load_presence_edd_by_bag(cursor, organization_id: int) -> dict[str, date]:
    org = int(organization_id)
    out: dict[str, date] = {}
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return out
    cursor.execute(
        """
        SELECT UPPER(TRIM(bag_id)) AS bag_id, estimated_delivery_date
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND estimated_delivery_date IS NOT NULL
        """,
        (org,),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or not row.get("bag_id"):
            continue
        dc = parse_record_date(row.get("estimated_delivery_date"))
        if dc:
            out[str(row["bag_id"]).strip().upper()] = dc
    return out


def build_vendor_home_parity(
    *,
    vendor_home_view: Mapping[str, Any],
    internal_scan_view: Mapping[str, Any],
    presence_meta: Mapping[str, Any],
    portal_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Top-level Vendor Home parity payload — portal/manual vs internal scan."""
    manual = manual_vendor_home_counts()
    vh = dict(vendor_home_view)
    internal = dict(internal_scan_view)
    portal = dict(portal_counts or {})
    source = str(vh.get("source") or manual.get("source") or "manual_screenshot")
    at_total = vh.get("at_veewash_total", manual.get("at_veewash_total"))
    at_ytp = vh.get("at_veewash_yet_to_process", manual.get("at_veewash_yet_to_process"))
    due_total = vh.get("due_today_total", manual.get("due_today_total"))
    due_ytp = vh.get("due_today_yet_to_process", manual.get("due_today_yet_to_process"))

    portal_available = bool(presence_meta.get("portal_list_available"))
    reason_parts: list[str] = []
    if not portal_available:
        reason_parts.append("presence table empty / portal status unavailable")
    if source == "manual_screenshot":
        reason_parts.append(
            "Vendor Home reference is manual screenshot — dashboard cannot fully reconcile until portal list scrape is available"
        )

    scan_at = int(internal.get("at_facility_total") or 0)
    scan_ytp = int(internal.get("in_progress") or 0)
    scan_due = int(internal.get("due_today_total") or 0)
    scan_due_ytp = int(internal.get("due_today_yet_to_process") or 0)

    reconciled = (
        portal_available
        and bool(portal_counts)
        and source != "manual_screenshot"
        and portal.get("at_veewash_total") is not None
        and int(portal.get("at_veewash_total") or 0) == int(at_total or 0)
        and int(portal.get("at_veewash_yet_to_process") or 0) == int(at_ytp or 0)
    )

    return {
        "source": "portal_or_manual_reference" if portal_available else "manual_screenshot",
        "vendor_home_view_source": source,
        "at_veewash_total": at_total,
        "at_veewash_yet_to_process": at_ytp,
        "at_veewash_processed": vh.get("at_veewash_processed", manual.get("at_veewash_processed")),
        "due_today_total": due_total,
        "due_today_yet_to_process": due_ytp,
        "due_today_processed": vh.get("due_today_processed", manual.get("due_today_processed")),
        "internal_scan": {
            "at_facility_total": scan_at,
            "in_progress": scan_ytp,
            "completed_still_at_facility": int(internal.get("completed_still_at_facility") or 0),
            "due_today_total": scan_due,
            "due_today_yet_to_process": scan_due_ytp,
            "due_today_completed": int(internal.get("due_today_completed") or 0),
        },
        "presence": {
            "at_vendor_active": int(presence_meta.get("at_vendor_active") or 0),
            "rfv_active": int(presence_meta.get("rfv_active") or 0),
            "portal_list_available": portal_available,
        },
        "portal_counts": portal or None,
        "reconciled": reconciled,
        "needs_review": True,
        "reason": "; ".join(reason_parts) if reason_parts else "Portal list loaded — compare portal vs manual reference",
        "comparison": {
            "at_veewash": {
                "vendor_home_total": at_total,
                "vendor_home_yet_to_process": at_ytp,
                "internal_scan_total": scan_at,
                "internal_scan_in_progress": scan_ytp,
                "difference_total": (scan_at - int(at_total or 0)) if at_total is not None else None,
                "difference_yet_to_process": (scan_ytp - int(at_ytp or 0)) if at_ytp is not None else None,
                "status": "Needs Review",
            },
            "due_today": {
                "vendor_home_total": due_total,
                "vendor_home_yet_to_process": due_ytp,
                "internal_scan_total": scan_due,
                "internal_scan_pending": scan_due_ytp,
                "difference_total": (scan_due - int(due_total or 0)) if due_total is not None else None,
                "difference_pending": (scan_due_ytp - int(due_ytp or 0)) if due_ytp is not None else None,
                "status": "Needs Review",
            },
        },
    }


def build_vendor_home_view_section(
    *,
    portal_counts: Mapping[str, Any] | None,
    presence_meta: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    record_count_fn: Any,
) -> dict[str, Any]:
    """Vendor Home view cards — portal when available, else manual reference (non-clickable)."""
    manual = manual_vendor_home_counts()
    portal_available = bool(presence_meta.get("portal_list_available"))
    manual_only = not portal_available or not portal_counts
    counts = dict(portal_counts if portal_available and portal_counts else manual)
    source = str(counts.get("source") or "manual_screenshot")

    def _vh_card(label: str, count: Any, portal_tag: str | None) -> dict[str, Any]:
        cnt = int(count) if count is not None else None
        rec_cnt = record_count_fn(records, portal_tag) if portal_tag and not manual_only else None
        clickable = bool(portal_tag and not manual_only and rec_cnt is not None and cnt == rec_cnt)
        return {
            "label": label,
            "count": cnt,
            "drilldown_tag": portal_tag if not manual_only else None,
            "records_count": rec_cnt,
            "clickable": clickable,
            "needs_review": False,
            "vendor_home_view": True,
            "manual_reference_only": manual_only,
            "under_review_reason": (
                "Manual Vendor Home reference — no record-level list available."
                if manual_only
                else None
            ),
        }

    at_total = counts.get("at_veewash_total")
    at_ytp = counts.get("at_veewash_yet_to_process")
    at_proc = counts.get("at_veewash_processed")
    if at_proc is None and at_total is not None and at_ytp is not None:
        at_proc = int(at_total) - int(at_ytp)

    due_total = counts.get("due_today_total")
    due_ytp = counts.get("due_today_yet_to_process")
    due_proc = counts.get("due_today_processed")
    if due_proc is None and due_total is not None and due_ytp is not None:
        due_proc = int(due_total) - int(due_ytp)

    cards = [
        _vh_card("At VeeWash Total", at_total, PORTAL_VH_AT_VENDOR if not manual_only else None),
        _vh_card("Vendor Home Yet to Process", at_ytp, PORTAL_VH_YET_TO_PROCESS if not manual_only else None),
        _vh_card("Processed per Vendor Home", at_proc, None),
    ]
    due_cards = [
        _vh_card("Due Today Total", due_total, PORTAL_VH_DTS_TOTAL if not manual_only else None),
        _vh_card("Vendor Home Due Today Pending", due_ytp, PORTAL_VH_DTS_PENDING if not manual_only else None),
        _vh_card("Due Today Processed", due_proc, None),
    ]
    return {
        "source": source,
        "manual_reference_only": manual_only,
        "portal_list_available": portal_available,
        "at_veewash_total": at_total,
        "at_veewash_yet_to_process": at_ytp,
        "at_veewash_processed": at_proc,
        "due_today_total": due_total,
        "due_today_yet_to_process": due_ytp,
        "due_today_processed": due_proc,
        "cards": cards,
        "due_today_cards": due_cards,
        "alert": (
            "Portal presence not loaded — Vendor Home parity cannot be record-level reconciled."
            if not portal_available
            else None
        ),
    }
