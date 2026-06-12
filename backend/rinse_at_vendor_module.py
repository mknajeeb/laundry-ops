"""
At Vendor Shift Monitor module — sent-to-vendor scope, lightweight queries.

Independent of CFS/staging/registry population. Uses selected ET day only.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import (
    naive_et_day_end_exclusive,
    naive_et_day_end_inclusive,
    naive_et_day_start,
)
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    gaming_events_from_records,
    lifecycle_anchor,
    ts_valid,
)
from backend.rinse_bag_activity_rules import _all_weight_entries_after_anchor
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_assembly_printed_ct_purpose,
    is_complete_cleaning_purpose,
    is_sent_to_vendor_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.rinse_scan_time import system_datetime_to_et
from backend.ta_helpers import table_exists, table_has_column

# Scan purposes needed for At Vendor scope/completion (no full lifecycle history).
_AT_VENDOR_PURPOSE_EXACT = (
    "weight-entry",
    "add-photos",
    "complete-cleaning",
    "garments-reviewed",
    "assembly-printed-ct",
    "workitems-added",
    "create-bulk-workitem",
    "create-workitem-bulk",
)


def _normalize_purpose_sql_expr() -> str:
    return "LOWER(REPLACE(COALESCE(purpose, ''), ' ', '-'))"


def _at_vendor_purpose_sql_filter(column: str = "purpose") -> str:
    expr = f"LOWER(REPLACE(COALESCE({column}, ''), ' ', '-'))"
    exact = ", ".join(f"'{p}'" for p in _AT_VENDOR_PURPOSE_EXACT)
    return f"({expr} IN ({exact}) OR LOCATE('sent-to-vendor', {expr}) > 0)"


def _purpose_matches_at_vendor(raw: str | None) -> bool:
    if is_sent_to_vendor_purpose(raw):
        return True
    if is_weight_entry_purpose(raw):
        return True
    if is_add_photos_purpose(raw):
        return True
    if is_complete_cleaning_purpose(raw):
        return True
    if is_assembly_printed_ct_purpose(raw):
        return True
    if _is_garments_reviewed_purpose(raw):
        return True
    norm = normalize_scan_purpose(raw)
    return norm in ("workitems-added", "create-bulk-workitem", "create-workitem-bulk")


def _format_et_display(ts: datetime | None) -> str | None:
    if not ts_valid(ts):
        return None
    et = system_datetime_to_et(ts)
    return et.strftime("%Y-%m-%d %H:%M:%S ET") if et else ts.isoformat()


MOD_AT_VENDOR_TOTAL = "mod_at_vendor_total"
MOD_AT_VENDOR_PENDING = "mod_at_vendor_pending"
MOD_AT_VENDOR_COMPLETED = "mod_at_vendor_completed"
MOD_AT_VENDOR_CHANGED_RUSH = "mod_at_vendor_changed_rush"

AV_RUSH = "RUSH"
AV_NON_RUSH = "NON_RUSH"
AV_UNKNOWN = "UNKNOWN_REVIEW"

AV_STATUS_PENDING = "Pending"
AV_STATUS_COMPLETED = "Completed"

CHANGED_RUSH_REASON_DAY_ADVANCE = (
    "Changed to Rush because selected ET date advanced and bag remained pending"
)
CHANGED_RUSH_REASON_EDD = (
    "Changed to Rush because EDD changed from future date to selected ET date"
)


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        et = system_datetime_to_et(raw)
        return et.date() if et else raw.date()
    if raw is not None and str(raw).strip():
        try:
            return date.fromisoformat(str(raw).strip()[:10])
        except ValueError:
            return None
    return None


def _event_et_date(ts: datetime | None) -> date | None:
    if not ts_valid(ts):
        return None
    et = system_datetime_to_et(ts)
    return et.date() if et else ts.date()


def _normalize_service(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in ("WF", "WASH & FOLD", "WASH AND FOLD"):
        return "WF"
    if text in ("HD", "HANG DRY", "HANG-DRY", "HOME DELIVERY"):
        return "HD"
    if "WASH" in text and "FOLD" in text:
        return "WF"
    if ("HANG" in text and "DRY" in text) or ("HOME" in text and "DELIV" in text):
        return "HD"
    if text in ("WF", "HD"):
        return text
    return AV_UNKNOWN


def _has_today_label(texts: Sequence[str]) -> bool:
    for text in texts:
        if text and "TODAY" in str(text).upper():
            return True
    return False


def _presence_raw_json(row: Mapping[str, Any]) -> dict[str, Any]:
    import json

    rj = row.get("raw_row_json")
    if isinstance(rj, dict):
        return rj
    if isinstance(rj, str) and rj.strip():
        try:
            parsed = json.loads(rj)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def classify_at_vendor_rush(
    *,
    latest_edd: date | None,
    delivery_texts: Sequence[str],
    selected_date_et: date,
    pending: bool,
) -> tuple[str, str]:
    if _has_today_label(delivery_texts):
        return AV_RUSH, "Rush because delivery/date text contains TODAY"
    if latest_edd is None:
        return AV_UNKNOWN, "Unknown because EDD missing or invalid"
    if latest_edd == selected_date_et:
        return AV_RUSH, f"Rush because EDD equals selected ET date {selected_date_et.isoformat()}"
    if latest_edd < selected_date_et:
        if pending:
            return AV_RUSH, f"Rush because EDD {latest_edd.isoformat()} is before selected ET date and bag is pending"
        return AV_RUSH, f"Rush because EDD {latest_edd.isoformat()} is before selected ET date"
    if latest_edd > selected_date_et:
        return AV_NON_RUSH, f"Non-Rush because EDD {latest_edd.isoformat()} is after selected ET date"
    return AV_UNKNOWN, "Unknown review"


def _load_registry_service_types(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, str | None]:
    org = int(organization_id)
    out: dict[str, str | None] = {bid: None for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "rinse_bag_registry"):
        return out
    chunk = 200
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT UPPER(TRIM(bag_id)) AS bag_id, service_type
            FROM rinse_bag_registry
            WHERE organization_id = %s AND UPPER(TRIM(bag_id)) IN ({ph})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid and row.get("service_type"):
                out[bid] = row.get("service_type")
    return out


INCLUSION_CARRY_IN = "carry_in_open_at_midnight"
INCLUSION_NEW_SENT = "new_sent_to_vendor_today"
INCLUSION_CLEAN_SCRAPE_SEED = "clean_veewash_scrape_seed"
INCLUSION_POST_BASELINE_SENT = "post_baseline_sent_to_vendor"


def _load_carry_in_open_at_midnight_bag_ids(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    new_sent_scan_ids: set[str] | None = None,
    sent_before_ids: set[str] | None = None,
) -> tuple[set[str], list[str], dict[str, list[dict[str, Any]]]]:
    """
    Bags sent-to-vendor before selected ET midnight and not completed before midnight.
    Loads purpose-filtered pre-midnight events for sent-before candidates only.
    Returns pre-midnight events for reuse when building final rows.
    """
    org = int(organization_id)
    start = naive_et_day_start(selected_date_et)
    prior_day_end = naive_et_day_end_inclusive(selected_date_et - timedelta(days=1))
    new_sent = new_sent_scan_ids or set()
    empty_events: dict[str, list[dict[str, Any]]] = {}
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set(), [], empty_events

    candidates = sent_before_ids
    if candidates is None:
        candidates = _load_sent_to_vendor_bag_ids_before_et_day(
            cursor, org, selected_date_et=selected_date_et
        )
    if not candidates:
        return set(), [], empty_events

    registry_service = _load_registry_service_types(cursor, org, sorted(candidates))
    events_by_bag = _load_at_vendor_scan_events_for_bags(
        cursor,
        org,
        sorted(candidates),
        scanned_before=start,
    )

    carry_in: set[str] = set()
    excluded: list[str] = []
    for bid in candidates:
        svc = _normalize_service(registry_service.get(bid))
        midnight_anchor = _latest_sent_to_vendor_ts(
            events_by_bag.get(bid) or [],
            before=start,
        )
        if midnight_anchor is not None:
            status, _, _, _ = _evaluate_bag_as_of(
                events_by_bag.get(bid) or [],
                service_type=svc,
                as_of_end=prior_day_end,
                anchor_ts_override=midnight_anchor,
            )
        else:
            status = _bag_status_as_of(
                events_by_bag.get(bid) or [],
                service_type=svc,
                as_of_end=prior_day_end,
            )
        if status == AV_STATUS_COMPLETED:
            if bid not in new_sent:
                excluded.append(bid)
            continue
        carry_in.add(bid)
    return carry_in, excluded, events_by_bag


def _load_bag_organization_ownership(
    cursor,
    bag_ids: list[str],
) -> dict[str, set[int]]:
    """Org IDs that own a bag per registry, scan events, and staging (not presence)."""
    out: dict[str, set[int]] = {bid: set() for bid in bag_ids if bid}
    if not bag_ids:
        return out
    chunk = 1000
    parts: list[str] = []
    args: list[Any] = []

    if table_exists(cursor, "rinse_bag_registry"):
        parts.append(
            """
            SELECT UPPER(TRIM(bag_id)) AS bag_id, organization_id
            FROM rinse_bag_registry
            WHERE UPPER(TRIM(bag_id)) IN ({ph})
            """
        )
    if table_exists(cursor, "rinse_bag_scan_events"):
        parts.append(
            """
            SELECT UPPER(TRIM(bag_id)) AS bag_id, organization_id
            FROM rinse_bag_scan_events
            WHERE UPPER(TRIM(bag_id)) IN ({ph})
            GROUP BY UPPER(TRIM(bag_id)), organization_id
            """
        )
    if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
        if table_has_column(cursor, "orders_staging", "organization_id"):
            parts.append(
                """
                SELECT UPPER(TRIM(ticket_id)) AS bag_id, organization_id
                FROM orders_staging
                WHERE UPPER(TRIM(ticket_id)) IN ({ph})
                GROUP BY UPPER(TRIM(ticket_id)), organization_id
                """
            )

    if not parts:
        return out

    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        union_sql = " UNION ALL ".join(p.replace("{ph}", ph) for p in parts)
        cursor.execute(union_sql, tuple(part * len(parts)))
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            oid = row.get("organization_id")
            if bid in out and oid is not None:
                out[bid].add(int(oid))
    return out


def _filter_cross_org_contaminated_bags(
    cursor,
    organization_id: int,
    bag_ids: set[str],
) -> tuple[set[str], list[dict[str, Any]]]:
    """
    Drop bags whose registry/scan/staging ownership is exclusively another org.
    Prevents Washpro rows scraped into VeeWash presence from entering At Vendor.
    """
    org = int(organization_id)
    if not bag_ids:
        return set(), []
    ownership = _load_bag_organization_ownership(cursor, sorted(bag_ids))
    kept: set[str] = set()
    excluded: list[dict[str, Any]] = []
    for bid in sorted(bag_ids):
        owner_orgs = ownership.get(bid) or set()
        if owner_orgs and org not in owner_orgs:
            excluded.append(
                {
                    "bag_id": bid,
                    "owner_organization_ids": sorted(owner_orgs),
                    "reason": "Bag owned by another organization in registry/scans/staging",
                }
            )
            continue
        kept.add(bid)
    return kept, excluded


def _bag_status_as_of(
    events: Sequence[Mapping[str, Any]],
    *,
    service_type: str,
    as_of_end: datetime,
) -> str:
    status, _, _, _ = _evaluate_bag_as_of(events, service_type=service_type, as_of_end=as_of_end)
    return status


def _load_sent_to_vendor_bag_id_sets_for_et_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> tuple[set[str], set[str]]:
    """Return (sent_before_midnight_ids, sent_during_day_ids) in one SQL round trip."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set(), set()
    start = naive_et_day_start(selected_date_et)
    end_excl = naive_et_day_end_exclusive(selected_date_et)
    org = int(organization_id)
    purpose_expr = _normalize_purpose_sql_expr()
    cursor.execute(
        f"""
        SELECT UPPER(TRIM(bag_id)) AS bag_id,
               MAX(CASE WHEN scanned_at_parsed < %s THEN 1 ELSE 0 END) AS sent_before,
               MAX(CASE WHEN scanned_at_parsed >= %s AND scanned_at_parsed < %s THEN 1 ELSE 0 END) AS sent_during
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND scanned_at_parsed IS NOT NULL
          AND LOCATE('sent-to-vendor', {purpose_expr}) > 0
        GROUP BY UPPER(TRIM(bag_id))
        """,
        (start, start, end_excl, org),
    )
    before: set[str] = set()
    during: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if int(row.get("sent_before") or 0):
            before.add(bid)
        if int(row.get("sent_during") or 0):
            during.add(bid)
    return before, during


def _load_sent_to_vendor_bag_ids_before_et_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> set[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    start = naive_et_day_start(selected_date_et)
    org = int(organization_id)
    purpose_expr = _normalize_purpose_sql_expr()
    cursor.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed < %s
          AND LOCATE('sent-to-vendor', {purpose_expr}) > 0
        """,
        (org, start),
    )
    return {
        str(row.get("bag_id") or "").strip().upper()
        for row in (cursor.fetchall() or [])
        if isinstance(row, dict) and row.get("bag_id")
    }


def _load_sent_to_vendor_bag_ids_during_et_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> set[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    start = naive_et_day_start(selected_date_et)
    end_excl = naive_et_day_end_exclusive(selected_date_et)
    org = int(organization_id)
    purpose_expr = _normalize_purpose_sql_expr()
    cursor.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
          AND LOCATE('sent-to-vendor', {purpose_expr}) > 0
        """,
        (org, start, end_excl),
    )
    return {
        str(row.get("bag_id") or "").strip().upper()
        for row in (cursor.fetchall() or [])
        if isinstance(row, dict) and row.get("bag_id")
    }


def _load_presence_carry_in_candidates(
    cursor,
    organization_id: int,
    *,
    start_of_day_et: datetime,
) -> list[dict[str, Any]]:
    """Bags seen at_vendor before midnight that were still on portal during selected ET day."""
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR

    org = int(organization_id)
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return []
    has_status_first = table_has_column(cursor, "rinse_cleaner_ticket_presence", "portal_status_first_seen_at")
    first_seen_expr = (
        "COALESCE(portal_status_first_seen_at, first_seen_at)"
        if has_status_first
        else "first_seen_at"
    )
    cursor.execute(
        f"""
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json, active, last_seen_at, first_seen_at
               {", portal_status_first_seen_at" if has_status_first else ""}
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s
          AND portal_status = %s
          AND {first_seen_expr} < %s
          AND last_seen_at >= %s
        ORDER BY UPPER(TRIM(bag_id))
        """,
        (org, PORTAL_STATUS_AT_VENDOR, start_of_day_et, start_of_day_et),
    )
    out: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        out.append(dict(raw, bag_id=bid))
    return out


def _load_active_at_vendor_presence_by_bag(
    cursor,
    organization_id: int,
) -> dict[str, dict[str, Any]]:
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_current_facility_snapshot import portal_at_vendor_yet_to_process

    org = int(organization_id)
    out: dict[str, dict[str, Any]] = {}
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return out
    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json, active, last_seen_at
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        out[bid] = {
            "bag_id": bid,
            "customer_name": raw.get("customer_name"),
            "service_type": raw.get("service_type"),
            "estimated_delivery_date": raw.get("estimated_delivery_date"),
            "raw_row_json": raw.get("raw_row_json"),
            "delivery_source": "presence",
            "portal_status": PORTAL_STATUS_AT_VENDOR,
            "active_presence": True,
            "portal_yet_to_process": portal_at_vendor_yet_to_process(raw),
        }
    return out


def _load_clean_scrape_seed_presence_by_bag(
    cursor,
    organization_id: int,
    *,
    source_batch_id: str,
) -> dict[str, dict[str, Any]]:
    """Active at_vendor presence rows from the approved clean VeeWash scrape batch."""
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_current_facility_snapshot import portal_at_vendor_yet_to_process
    from backend.rinse_shift_monitor_baseline import is_contaminated_presence_batch

    org = int(organization_id)
    batch_id = str(source_batch_id or "").strip()
    out: dict[str, dict[str, Any]] = {}
    if not batch_id or is_contaminated_presence_batch(batch_id):
        return out
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return out
    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json, active, last_seen_at, source_batch_id
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
          AND source_batch_id = %s
        ORDER BY UPPER(TRIM(bag_id))
        """,
        (org, PORTAL_STATUS_AT_VENDOR, batch_id),
    )
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        out[bid] = {
            "bag_id": bid,
            "customer_name": raw.get("customer_name"),
            "service_type": raw.get("service_type"),
            "estimated_delivery_date": raw.get("estimated_delivery_date"),
            "raw_row_json": raw.get("raw_row_json"),
            "delivery_source": "presence",
            "portal_status": PORTAL_STATUS_AT_VENDOR,
            "active_presence": True,
            "portal_yet_to_process": portal_at_vendor_yet_to_process(raw),
            "source_batch_id": raw.get("source_batch_id"),
        }
    return out


def _load_post_baseline_sent_to_vendor_bag_ids(
    cursor,
    organization_id: int,
    *,
    baseline_start_naive_et: datetime,
    through_end: datetime,
) -> set[str]:
    """Bags with sent-to-vendor scan on/after baseline through selected-day end."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    org = int(organization_id)
    purpose_expr = _normalize_purpose_sql_expr()
    cursor.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
          AND LOCATE('sent-to-vendor', {purpose_expr}) > 0
        """,
        (org, baseline_start_naive_et, through_end),
    )
    return {
        str(row.get("bag_id") or "").strip().upper()
        for row in (cursor.fetchall() or [])
        if isinstance(row, dict) and row.get("bag_id")
    }


def _count_contaminated_active_presence_rows(cursor, organization_id: int) -> int:
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_shift_monitor_baseline import is_contaminated_presence_batch

    org = int(organization_id)
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return 0
    cursor.execute(
        """
        SELECT source_batch_id
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND portal_status = %s AND active = 1
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    count = 0
    for row in cursor.fetchall() or []:
        if isinstance(row, dict) and is_contaminated_presence_batch(row.get("source_batch_id")):
            count += 1
    return count


def _load_baseline_gated_at_vendor_population(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Clean VeeWash baseline population:
      seed from latest clean at_vendor presence scrape
      + post-baseline sent-to-vendor through selected ET day end.
    No pre-baseline carry-in or contaminated presence rows.
    """
    org = int(organization_id)
    start_of_day_et = naive_et_day_start(selected_date_et)
    end_of_day_et = naive_et_day_end_inclusive(selected_date_et)
    baseline_start = baseline_ctx.get("baseline_start_naive_et")
    if not isinstance(baseline_start, datetime):
        return [], {
            "available": False,
            "reason": "Clean VeeWash baseline start time unavailable",
            "start_of_day_et": start_of_day_et.isoformat(),
            "end_of_day_et": end_of_day_et.isoformat(),
        }

    source_batch_id = str(
        baseline_ctx.get("latest_at_vendor_presence_source_batch_id")
        or baseline_ctx.get("baseline_source_batch_id")
        or ""
    ).strip()
    seed_by_bag = _load_clean_scrape_seed_presence_by_bag(
        cursor, org, source_batch_id=source_batch_id
    )
    post_baseline_sent_ids = _load_post_baseline_sent_to_vendor_bag_ids(
        cursor,
        org,
        baseline_start_naive_et=baseline_start,
        through_end=end_of_day_et,
    )
    seed_ids = set(seed_by_bag.keys())
    population_ids = seed_ids | post_baseline_sent_ids

    cross_org_candidates = set(population_ids)
    kept_ids, cross_org_excluded = _filter_cross_org_contaminated_bags(
        cursor, org, cross_org_candidates
    )
    population_ids = kept_ids
    seed_ids &= population_ids
    post_baseline_sent_ids &= population_ids

    registry_service = _load_registry_service_types(cursor, org, sorted(population_ids))
    meta_by_bag = _load_delivery_meta(cursor, org, sorted(population_ids))

    population: list[dict[str, Any]] = []
    for bid in sorted(population_ids):
        is_seed = bid in seed_ids
        is_post_sent = bid in post_baseline_sent_ids and bid not in seed_ids
        if is_seed and is_post_sent:
            inclusion = f"{INCLUSION_CLEAN_SCRAPE_SEED}+{INCLUSION_POST_BASELINE_SENT}"
            inclusion_reason = (
                "Clean VeeWash scrape seed plus post-baseline sent-to-vendor during selected ET day"
            )
        elif is_seed:
            inclusion = INCLUSION_CLEAN_SCRAPE_SEED
            inclusion_reason = "Clean VeeWash at_vendor presence scrape seed population"
        else:
            inclusion = INCLUSION_POST_BASELINE_SENT
            inclusion_reason = "Post-baseline sent-to-vendor during selected ET day"

        meta = dict(meta_by_bag.get(bid) or {"bag_id": bid})
        if bid in seed_by_bag:
            meta = {**meta, **seed_by_bag[bid]}
        elif not meta.get("service_type") and registry_service.get(bid):
            meta["service_type"] = registry_service.get(bid)
        meta.setdefault("active_presence", bid in seed_by_bag)

        population.append(
            {
                **meta,
                "bag_id": bid,
                "population_inclusion": inclusion,
                "inclusion_reason": inclusion_reason,
                "currently_on_vendor_home": bid in seed_by_bag,
            }
        )

    current_live_vendor_home_total = len(seed_by_bag)
    contaminated_excluded = _count_contaminated_active_presence_rows(cursor, org)

    return population, {
        "available": True,
        "reason": None,
        "start_of_day_et": start_of_day_et.isoformat(),
        "end_of_day_et": end_of_day_et.isoformat(),
        "baseline_time_et": baseline_start.isoformat(),
        "baseline_source_batch_id": source_batch_id,
        "baseline_presence_run_id": baseline_ctx.get("baseline_presence_run_id"),
        "current_live_vendor_home_total": current_live_vendor_home_total,
        "clean_scrape_seed_count": len(seed_ids),
        "post_baseline_sent_count": len(post_baseline_sent_ids - seed_ids),
        "post_baseline_sent_total_count": len(post_baseline_sent_ids),
        "carry_in_open_at_midnight_count": 0,
        "new_sent_to_vendor_today_count": len(post_baseline_sent_ids - seed_ids),
        "portal_live_supplement_count": 0,
        "new_during_selected_day_count": len(post_baseline_sent_ids - seed_ids),
        "overlap_carry_in_and_new_sent_count": 0,
        "selected_day_at_vendor_total": len(population_ids),
        "pre_baseline_carry_in_excluded_count": None,
        "contaminated_presence_rows_excluded_count": contaminated_excluded,
        "cross_org_excluded_bags": cross_org_excluded,
        "cross_org_excluded_from_live_presence": [
            entry
            for entry in cross_org_excluded
            if str(entry.get("bag_id") or "").strip().upper() in seed_by_bag
        ],
        "scope": "clean_veewash_baseline",
        "population_source": "clean_veewash_baseline",
        "uses_clean_veewash_baseline": True,
    }


def _load_selected_day_at_vendor_population(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Cumulative selected ET-day At Vendor population:
      carry-in open at 12:00 AM ET (not completed before midnight)
      + new sent-to-vendor during selected ET day.
    """
    org = int(organization_id)
    start_of_day_et = naive_et_day_start(selected_date_et)
    end_of_day_et = naive_et_day_end_inclusive(selected_date_et)
    prior_day_end = naive_et_day_end_inclusive(selected_date_et - timedelta(days=1))

    live_presence_by_bag = _load_active_at_vendor_presence_by_bag(cursor, org)

    has_scans = table_exists(cursor, "rinse_bag_scan_events")
    has_presence = table_exists(cursor, "rinse_cleaner_ticket_presence")
    if not has_scans and not has_presence:
        return [], {
            "available": False,
            "reason": "Scan events and cleaner-ticket presence tables unavailable",
            "start_of_day_et": start_of_day_et.isoformat(),
            "end_of_day_et": end_of_day_et.isoformat(),
            "current_live_vendor_home_total": len(live_presence_by_bag),
        }

    sent_before_ids: set[str] = set()
    new_sent_scan_ids: set[str] = set()
    if has_scans:
        sent_before_ids, new_sent_scan_ids = _load_sent_to_vendor_bag_id_sets_for_et_day(
            cursor, org, selected_date_et=selected_date_et
        )
    presence_carry_rows = (
        _load_presence_carry_in_candidates(cursor, org, start_of_day_et=start_of_day_et)
        if has_presence
        else []
    )
    presence_carry_by_bag = {r["bag_id"]: r for r in presence_carry_rows}

    carry_in_ids: set[str] = set()
    excluded_completed_before_midnight: list[str] = []
    carry_in_pre_midnight_events: dict[str, list[dict[str, Any]]] = {}
    if has_scans:
        carry_in_ids, excluded_completed_before_midnight, carry_in_pre_midnight_events = (
            _load_carry_in_open_at_midnight_bag_ids(
                cursor,
                org,
                selected_date_et=selected_date_et,
                new_sent_scan_ids=new_sent_scan_ids,
                sent_before_ids=sent_before_ids,
            )
        )

    for bid, pres in presence_carry_by_bag.items():
        if bid in carry_in_ids or bid in new_sent_scan_ids:
            continue
        carry_in_ids.add(bid)

    registry_service: dict[str, str | None] = {}
    if carry_in_ids or new_sent_scan_ids or presence_carry_by_bag:
        registry_service = _load_registry_service_types(
            cursor, org, sorted(carry_in_ids | new_sent_scan_ids | set(presence_carry_by_bag.keys()))
        )

    new_sent_ids = set(new_sent_scan_ids)
    population_ids = carry_in_ids | new_sent_ids

    portal_live_supplement_ids: set[str] = set()
    for bid in live_presence_by_bag:
        if bid not in population_ids:
            portal_live_supplement_ids.add(bid)
            population_ids.add(bid)
            new_sent_ids.add(bid)

    cross_org_candidates = population_ids | set(live_presence_by_bag.keys())
    kept_ids, cross_org_excluded = _filter_cross_org_contaminated_bags(
        cursor, org, cross_org_candidates
    )
    live_cross_org_excluded = [
        entry
        for entry in cross_org_excluded
        if str(entry.get("bag_id") or "").strip().upper() in live_presence_by_bag
    ]
    live_presence_by_bag = {
        bid: live_presence_by_bag[bid] for bid in live_presence_by_bag if bid in kept_ids
    }
    current_live_vendor_home_total = len(live_presence_by_bag)
    population_ids = kept_ids & population_ids
    carry_in_ids &= population_ids
    new_sent_ids &= population_ids
    portal_live_supplement_ids &= population_ids

    meta_by_bag = _load_delivery_meta(cursor, org, sorted(population_ids))

    population: list[dict[str, Any]] = []
    for bid in sorted(population_ids):
        is_carry = bid in carry_in_ids
        is_new = bid in new_sent_ids
        is_portal_supplement = bid in portal_live_supplement_ids
        if is_portal_supplement and not is_carry:
            inclusion = "portal_live_at_vendor"
            inclusion_reason = (
                "Active at_vendor portal presence during selected ET day "
                "(no sent-to-vendor scan in scope yet)"
            )
        elif is_carry and is_new and not is_portal_supplement:
            inclusion = f"{INCLUSION_CARRY_IN}+{INCLUSION_NEW_SENT}"
            inclusion_reason = (
                "Open at vendor before midnight and new sent-to-vendor during selected ET day"
            )
        elif is_carry and is_new:
            inclusion = f"{INCLUSION_CARRY_IN}+{INCLUSION_NEW_SENT}"
            inclusion_reason = (
                "Open at vendor before midnight and new sent-to-vendor during selected ET day"
            )
        elif is_new:
            inclusion = INCLUSION_NEW_SENT
            inclusion_reason = "New sent-to-vendor during selected ET day"
        else:
            inclusion = INCLUSION_CARRY_IN
            inclusion_reason = "Open at vendor before midnight and not completed before midnight"

        meta = dict(meta_by_bag.get(bid) or {"bag_id": bid})
        if bid in live_presence_by_bag:
            meta = {**meta, **live_presence_by_bag[bid]}
        elif bid in presence_carry_by_bag:
            pres = presence_carry_by_bag[bid]
            meta.setdefault("customer_name", pres.get("customer_name"))
            meta.setdefault("service_type", pres.get("service_type"))
            meta.setdefault("estimated_delivery_date", pres.get("estimated_delivery_date"))
            meta.setdefault("raw_row_json", pres.get("raw_row_json"))
            meta.setdefault("delivery_source", "presence")
            meta.setdefault("portal_status", pres.get("portal_status"))
            meta["active_presence"] = bool(pres.get("active"))
        else:
            meta.setdefault("active_presence", False)

        if not meta.get("service_type") and registry_service.get(bid):
            meta["service_type"] = registry_service.get(bid)

        population.append(
            {
                **meta,
                "bag_id": bid,
                "population_inclusion": inclusion,
                "inclusion_reason": inclusion_reason,
                "currently_on_vendor_home": bid in live_presence_by_bag,
            }
        )

    excluded_completed_before_midnight = sorted(set(excluded_completed_before_midnight))
    overlap_carry_and_new_ids = sorted(carry_in_ids & new_sent_ids)
    new_scan_only_ids = sorted(new_sent_scan_ids - carry_in_ids)
    gone_but_counted = sorted(bid for bid in population_ids if bid not in live_presence_by_bag)

    return population, {
        "available": True,
        "reason": None,
        "start_of_day_et": start_of_day_et.isoformat(),
        "end_of_day_et": end_of_day_et.isoformat(),
        "current_live_vendor_home_total": current_live_vendor_home_total,
        "carry_in_open_at_midnight_count": len(carry_in_ids),
        "new_sent_to_vendor_today_count": len(new_sent_scan_ids),
        "portal_live_supplement_count": len(portal_live_supplement_ids),
        "new_during_selected_day_count": len(new_sent_ids),
        "overlap_carry_in_and_new_sent_count": len(overlap_carry_and_new_ids),
        "selected_day_at_vendor_total": len(population_ids),
        "bags_completed_before_midnight_excluded": excluded_completed_before_midnight,
        "bags_entered_after_midnight": sorted(new_sent_scan_ids),
        "bags_new_sent_only_today": new_scan_only_ids,
        "bags_gone_from_vendor_home_but_counted": gone_but_counted,
        "cross_org_excluded_bags": cross_org_excluded,
        "cross_org_excluded_from_live_presence": live_cross_org_excluded,
        "carry_in_candidate_bags_scanned": len(carry_in_ids) + len(excluded_completed_before_midnight),
        "sent_before_candidate_count": len(sent_before_ids) if has_scans else 0,
        "carry_in_pre_midnight_events": carry_in_pre_midnight_events,
        "registry_service_cache": registry_service,
        "scope": "selected_day_cumulative",
        "population_source": "selected_day_cumulative",
    }


def _load_at_vendor_presence_population(
    cursor,
    organization_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Live Vendor Home orders-at-VeeWash population from active cleaner-ticket presence."""
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_current_facility_snapshot import portal_at_vendor_yet_to_process

    org = int(organization_id)
    meta: dict[str, Any] = {
        "available": False,
        "vendor_home_at_veewash_total": 0,
        "reason": "No active at_vendor presence rows",
    }
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        meta["reason"] = "rinse_cleaner_ticket_presence table unavailable"
        return [], meta

    cursor.execute(
        """
        SELECT bag_id, portal_status, customer_name, estimated_delivery_date,
               service_type, raw_row_json, active, last_seen_at
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        ORDER BY UPPER(TRIM(bag_id))
        """,
        (org, PORTAL_STATUS_AT_VENDOR),
    )
    rows: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        rows.append(
            {
                "bag_id": bid,
                "customer_name": raw.get("customer_name"),
                "service_type": raw.get("service_type"),
                "estimated_delivery_date": raw.get("estimated_delivery_date"),
                "raw_row_json": raw.get("raw_row_json"),
                "delivery_source": "presence",
                "portal_status": PORTAL_STATUS_AT_VENDOR,
                "active_presence": True,
                "portal_yet_to_process": portal_at_vendor_yet_to_process(raw),
                "inclusion_reason": (
                    "Active at_vendor cleaner-ticket presence (Vendor Home orders at VeeWash)"
                ),
            }
        )

    if rows:
        meta = {
            "available": True,
            "vendor_home_at_veewash_total": len(rows),
            "reason": None,
        }
    return rows, meta


def _unavailable_at_vendor_module(
    selected_date_et: date,
    *,
    reason: str,
    population_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    meta = dict(population_meta or {})
    start_of_day_et = meta.get("start_of_day_et") or naive_et_day_start(selected_date_et).isoformat()
    return {
        "live": False,
        "unavailable_reason": reason,
        "selected_date_et": selected_date_et.isoformat(),
        "start_of_day_et": start_of_day_et,
        "end_of_day_et": meta.get("end_of_day_et") or naive_et_day_end_inclusive(selected_date_et).isoformat(),
        "rows": [],
        "cards": [],
        "total": None,
        "pending": None,
        "completed": None,
        "changed_to_rush": None,
        "total_equals_pending_plus_completed": None,
        "uses_scans": True,
        "scope": "selected_day_cumulative",
        "population_source": "selected_day_cumulative",
        "current_live_vendor_home_total": meta.get("current_live_vendor_home_total"),
        "vendor_home_at_veewash_total": meta.get("current_live_vendor_home_total"),
        "selected_day_at_vendor_total": None,
        "population_meta": meta,
        "presence_meta": meta,
    }


def explain_historical_scope_vs_presence(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    historical_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Diagnostic helper: compare old sent-to-vendor historical scope to live presence population.
    """
    presence_population, presence_meta = _load_at_vendor_presence_population(cursor, organization_id)
    presence_ids = {str(p.get("bag_id") or "").strip().upper() for p in presence_population if p.get("bag_id")}
    presence_by_id = {p["bag_id"]: p for p in presence_population}

    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    org = int(organization_id)
    if historical_rows is None:
        candidate_ids = sorted(_load_sent_to_vendor_bag_ids(cursor, org, through_date=selected_date_et))
        service_by_bag = _load_registry_service_types(cursor, org, candidate_ids)
        events_by_bag = _load_at_vendor_scan_events_for_bags(cursor, org, candidate_ids)
        meta_by_bag = _load_delivery_meta(cursor, org, candidate_ids)
        historical_rows = []
        for bid in candidate_ids:
            svc = _normalize_service(service_by_bag.get(bid))
            if not _bag_in_at_vendor_scope(
                events_by_bag.get(bid) or [],
                service_type=svc,
                selected_date_et=selected_date_et,
                as_of_end=as_of_end,
            ):
                continue
            meta = dict(meta_by_bag.get(bid) or {"bag_id": bid})
            if not meta.get("service_type") and service_by_bag.get(bid):
                meta["service_type"] = service_by_bag.get(bid)
            row = _build_row(
                bag_id=bid,
                meta=meta,
                events=events_by_bag.get(bid) or [],
                selected_date_et=selected_date_et,
                as_of_end=as_of_end,
            )
            if row:
                historical_rows.append(row)

    historical_ids = {str(r.get("bag_id") or "").strip().upper() for r in historical_rows if r.get("bag_id")}
    extra_ids = sorted(historical_ids - presence_ids)
    missing_ids = sorted(presence_ids - historical_ids)
    hist_by_id = {r["bag_id"]: r for r in historical_rows if r.get("bag_id")}

    extras: list[dict[str, Any]] = []
    for bid in extra_ids:
        row = hist_by_id.get(bid) or {}
        pres = presence_by_id.get(bid) or {}
        extras.append(
            {
                "bag_id": bid,
                "service_type": row.get("service_bucket") or row.get("service_type"),
                "sent_to_vendor_time": row.get("sent_to_vendor_time_et") or row.get("sent_to_vendor_time"),
                "completion_signal": row.get("completion_signal"),
                "at_vendor_status": row.get("at_vendor_status"),
                "active_in_cleaner_ticket_presence": bool(pres.get("active_presence")),
                "portal_status": pres.get("portal_status"),
                "reason_included_by_old_logic": (
                    "Historical sent-to-vendor scope included bag not in live at_vendor presence"
                ),
            }
        )

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "vendor_home_at_veewash_total": len(presence_ids),
        "historical_scope_total": len(historical_ids),
        "difference": len(historical_ids) - len(presence_ids),
        "extra_in_historical_not_presence": extras,
        "missing_from_historical_in_presence": missing_ids,
        "presence_meta": presence_meta,
    }


def _load_delivery_meta(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, dict[str, Any]]:
    org = int(organization_id)
    out: dict[str, dict[str, Any]] = {bid: {"bag_id": bid} for bid in bag_ids if bid}
    if not bag_ids:
        return out

    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        chunk = 1000
        for i in range(0, len(bag_ids), chunk):
            part = bag_ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id, estimated_delivery_date, customer_name, service_type, raw_row_json, active
                FROM rinse_cleaner_ticket_presence
                WHERE organization_id = %s AND portal_status = 'at_vendor'
                  AND UPPER(TRIM(bag_id)) IN ({ph})
                ORDER BY active DESC, last_seen_at DESC
                """,
                (org, *part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                if bid and not out.get(bid, {}).get("delivery_source"):
                    out[bid] = {
                        **out.get(bid, {}),
                        **row,
                        "delivery_source": "presence",
                        "active_presence": bool(row.get("active")),
                    }

    if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
        chunk = 1000
        for i in range(0, len(bag_ids), chunk):
            part = bag_ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            org_clause = " AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""
            args: list[Any] = list(part)
            if org_clause:
                args.append(org)
            notes_sel = "notes" if table_has_column(cursor, "orders_staging", "notes") else "NULL AS notes"
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(ticket_id)) AS bag_id, date_clean, name_clean, service_type, {notes_sel}
                FROM orders_staging
                WHERE UPPER(TRIM(ticket_id)) IN ({ph}){org_clause}
                """,
                tuple(args),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                if bid and out.get(bid, {}).get("delivery_source") != "presence":
                    out[bid] = {**out.get(bid, {}), **row, "delivery_source": "orders_staging"}

    if table_exists(cursor, "rinse_bag_registry"):
        chunk = 1000
        for i in range(0, len(bag_ids), chunk):
            part = bag_ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id, date_clean, name_clean, service_type
                FROM rinse_bag_registry
                WHERE organization_id = %s AND UPPER(TRIM(bag_id)) IN ({ph})
                """,
                (org, *part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                if bid and not out.get(bid, {}).get("delivery_source"):
                    out[bid] = {**out.get(bid, {}), **row, "delivery_source": "registry"}

    return out


def resolve_delivery_fields(meta: Mapping[str, Any]) -> tuple[date | None, list[str], str]:
    source = str(meta.get("delivery_source") or "unknown")
    texts: list[str] = []
    edd: date | None = None

    if meta.get("delivery_source") == "presence":
        edd = _parse_date(meta.get("estimated_delivery_date"))
        rj = _presence_raw_json(meta)
        for key in ("estimated_delivery_text", "Date_Clean", "Date"):
            val = rj.get(key)
            if val is not None and str(val).strip():
                texts.append(str(val).strip())
        if meta.get("customer_name"):
            texts.append(str(meta.get("customer_name")))
    elif meta.get("delivery_source") == "orders_staging":
        edd = _parse_date(meta.get("date_clean"))
        if meta.get("notes"):
            texts.append(str(meta.get("notes")))
        if meta.get("name_clean"):
            texts.append(str(meta.get("name_clean")))
    else:
        edd = _parse_date(meta.get("date_clean"))
        if meta.get("name_clean"):
            texts.append(str(meta.get("name_clean")))

    if edd is None:
        for text in texts:
            parsed = _parse_date(text)
            if parsed is not None:
                edd = parsed
                break
    return edd, texts, source


def _is_garments_reviewed_purpose(raw: str | None) -> bool:
    return "garments-reviewed" in normalize_scan_purpose(raw)


def _is_hd_completion_purpose(raw: str | None) -> bool:
    return (
        is_complete_cleaning_purpose(raw)
        or is_assembly_printed_ct_purpose(raw)
        or _is_garments_reviewed_purpose(raw)
    )


def _events_as_of(timeline: Sequence[Mapping[str, Any]], as_of_end: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in timeline:
        ts = event_ts(ev)
        if ts_valid(ts) and ts <= as_of_end:
            out.append(dict(ev))
    return out


def _wf_completion_signal(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> tuple[str | None, datetime | None]:
    anchored = events_on_or_after(timeline, anchor_ts)
    anchored = _events_as_of(anchored, as_of_end)
    weights = _all_weight_entries_after_anchor(anchored)
    if len(weights) >= 2:
        ev, ts = weights[1]
        return str(ev.get("purpose") or "weight-entry"), ts
    return None, None


def _hd_completion_signal(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> tuple[str | None, datetime | None]:
    anchored = events_on_or_after(timeline, anchor_ts)
    anchored = _events_as_of(anchored, as_of_end)
    add_photos_count = 0
    best: tuple[datetime, str] | None = None
    for ev in anchored:
        purpose = ev.get("purpose")
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        if _is_hd_completion_purpose(purpose):
            if best is None or ts < best[0]:
                best = (ts, str(purpose or "hd-completion"))
        if is_add_photos_purpose(purpose):
            add_photos_count += 1
            if add_photos_count >= 2:
                if best is None or ts < best[0]:
                    best = (ts, "second add-photos")
    if best is None:
        return None, None
    return best[1], best[0]


def _latest_sent_to_vendor_ts(
    events: Sequence[Mapping[str, Any]],
    *,
    on_or_after: datetime | None = None,
    before: datetime | None = None,
) -> datetime | None:
    best: datetime | None = None
    for ev in gaming_events_from_records(events):
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        if on_or_after is not None and ts < on_or_after:
            continue
        if before is not None and ts >= before:
            continue
        if best is None or ts > best:
            best = ts
    return best


def _resolve_selected_day_anchor_ts(
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
) -> datetime | None:
    start = naive_et_day_start(selected_date_et)
    end_excl = naive_et_day_end_exclusive(selected_date_et)
    during = _latest_sent_to_vendor_ts(events, on_or_after=start, before=end_excl)
    if during is not None:
        return during
    return _latest_sent_to_vendor_ts(events, before=start)


def _evaluate_bag_as_of(
    events: Sequence[Mapping[str, Any]],
    *,
    service_type: str,
    as_of_end: datetime,
    anchor_ts_override: datetime | None = None,
) -> tuple[str, str | None, datetime | None, datetime | None]:
    timeline = gaming_events_from_records(events)
    anchor_ts = anchor_ts_override
    anchor_ev = None
    if anchor_ts is None:
        anchor_ts, anchor_ev = lifecycle_anchor(timeline)
    if anchor_ts is None:
        for ev in timeline:
            if is_sent_to_vendor_purpose(ev.get("purpose")):
                ts = event_ts(ev)
                if ts_valid(ts):
                    anchor_ts = ts
                    anchor_ev = ev
                    break
    if anchor_ts is None or not ts_valid(anchor_ts):
        return AV_STATUS_PENDING, None, None, None

    svc = service_type if service_type in ("WF", "HD") else AV_UNKNOWN
    if svc == "HD":
        signal, comp_ts = _hd_completion_signal(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
    else:
        signal, comp_ts = _wf_completion_signal(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)

    if comp_ts is not None:
        return AV_STATUS_COMPLETED, signal, comp_ts, anchor_ts
    return AV_STATUS_PENDING, None, None, anchor_ts


def _load_sent_to_vendor_bag_ids(cursor, organization_id: int, *, through_date: date) -> set[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    end_excl = naive_et_day_end_exclusive(through_date)
    org = int(organization_id)
    purpose_expr = _normalize_purpose_sql_expr()
    cursor.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed < %s
          AND LOCATE('sent-to-vendor', {purpose_expr}) > 0
        """,
        (org, end_excl),
    )
    return {
        str(row.get("bag_id") or "").strip().upper()
        for row in (cursor.fetchall() or [])
        if isinstance(row, dict) and row.get("bag_id")
    }


def _load_at_vendor_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: list[str],
    *,
    scanned_before: datetime | None = None,
    scanned_on_or_after: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    org = int(organization_id)
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    purpose_filter = _at_vendor_purpose_sql_filter()
    time_clauses: list[str] = []
    time_args: list[Any] = []
    if scanned_before is not None:
        time_clauses.append("scanned_at_parsed < %s")
        time_args.append(scanned_before)
    if scanned_on_or_after is not None:
        time_clauses.append("scanned_at_parsed >= %s")
        time_args.append(scanned_on_or_after)
    time_sql = (" AND " + " AND ".join(time_clauses)) if time_clauses else ""
    chunk = 1000
    for i in range(0, len(bag_ids), chunk):
        part = [b for b in bag_ids[i : i + chunk] if b]
        if not part:
            continue
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND UPPER(TRIM(bag_id)) IN ({placeholders})
              AND {purpose_filter}
              {time_sql}
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part, *time_args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            if not _purpose_matches_at_vendor(row.get("purpose")):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid:
                out.setdefault(bid, []).append(row)
    return out


def _load_prior_edd_from_batches_bulk(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, tuple[date | None, str | None]]:
    out: dict[str, tuple[date | None, str | None]] = {bid: (None, None) for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "upload_batch_rows") or not table_exists(cursor, "upload_batches"):
        return out
    if not table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        return out
    org = int(organization_id)
    batch_pk = "id" if table_has_column(cursor, "upload_batches", "id") else "batch_id"
    row_batch_col = (
        "upload_batch_id"
        if table_has_column(cursor, "upload_batch_rows", "upload_batch_id")
        else "batch_id"
    )
    org_clause = " AND ub.organization_id = %s" if table_has_column(cursor, "upload_batches", "organization_id") else ""
    chunk = 1000
    for i in range(0, len(bag_ids), chunk):
        part = [b for b in bag_ids[i : i + chunk] if b]
        if not part:
            continue
        placeholders = ",".join(["%s"] * len(part))
        args: list[Any] = list(part)
        if org_clause:
            args.append(org)
        cursor.execute(
            f"""
            SELECT bag_id, date_clean
            FROM (
                SELECT UPPER(TRIM(ubr.ticket_id)) AS bag_id,
                       ubr.date_clean,
                       ROW_NUMBER() OVER (
                           PARTITION BY UPPER(TRIM(ubr.ticket_id))
                           ORDER BY ub.confirmed_at DESC
                       ) AS rn
                FROM upload_batch_rows ubr
                INNER JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}
                WHERE UPPER(TRIM(ubr.ticket_id)) IN ({placeholders})
                  AND ub.confirmed_at IS NOT NULL{org_clause}
            ) ranked
            WHERE rn = 2
            """,
            tuple(args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid in out:
                out[bid] = (_parse_date(row.get("date_clean")), "upload_batch_rows")
    return out


def _bag_in_at_vendor_scope(
    events: Sequence[Mapping[str, Any]],
    *,
    service_type: str,
    selected_date_et: date,
    as_of_end: datetime,
) -> tuple[str, str | None, datetime | None, datetime | None] | None:
    status, completion_signal, completion_ts, sent_ts = _evaluate_bag_as_of(
        events, service_type=service_type, as_of_end=as_of_end
    )
    if sent_ts is None:
        return None
    sent_date = _event_et_date(sent_ts)
    if sent_date is None or sent_date > selected_date_et:
        return None
    if status == AV_STATUS_COMPLETED and completion_ts is not None:
        comp_date = _event_et_date(completion_ts)
        if comp_date is not None and comp_date < selected_date_et:
            return None
    return status, completion_signal, completion_ts, sent_ts


def _apply_prior_edd_changed_to_rush(
    row: dict[str, Any],
    *,
    prior_edd: date | None,
    prior_source: str | None,
    selected_date_et: date,
) -> None:
    if prior_edd is None:
        return
    row["previous_edd"] = prior_edd.isoformat()
    row["prior_edd_source"] = prior_source
    prior_rush_at_selected, _ = classify_at_vendor_rush(
        latest_edd=prior_edd,
        delivery_texts=[],
        selected_date_et=selected_date_et,
        pending=True,
    )
    if (
        row.get("at_vendor_status") == AV_STATUS_PENDING
        and row.get("rush_bucket") == AV_RUSH
        and prior_rush_at_selected == AV_NON_RUSH
        and MOD_AT_VENDOR_CHANGED_RUSH not in row.get("module_tags", [])
    ):
        row["changed_to_rush"] = True
        row["changed_to_rush_reason"] = CHANGED_RUSH_REASON_EDD
        row["previous_rush_bucket"] = prior_rush_at_selected
        row["module_tags"] = list(row.get("module_tags") or []) + [MOD_AT_VENDOR_CHANGED_RUSH]
        row["drilldown_tags"] = row["module_tags"]


def _build_row(
    *,
    bag_id: str,
    meta: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
    as_of_end: datetime,
    prior_edd_info: tuple[date | None, str | None] | None = None,
) -> dict[str, Any]:
    svc = _normalize_service(meta.get("service_type"))
    anchor_ts = _resolve_selected_day_anchor_ts(events, selected_date_et)
    status, completion_signal, completion_ts, sent_ts = _evaluate_bag_as_of(
        events,
        service_type=svc,
        as_of_end=as_of_end,
        anchor_ts_override=anchor_ts,
    )

    latest_edd, delivery_texts, delivery_source = resolve_delivery_fields(meta)
    pending = status == AV_STATUS_PENDING
    rush_bucket, rush_reason = classify_at_vendor_rush(
        latest_edd=latest_edd,
        delivery_texts=delivery_texts,
        selected_date_et=selected_date_et,
        pending=pending,
    )
    prev_day = selected_date_et - timedelta(days=1)
    previous_rush, _ = classify_at_vendor_rush(
        latest_edd=latest_edd,
        delivery_texts=delivery_texts,
        selected_date_et=prev_day,
        pending=True,
    )

    changed_to_rush = False
    changed_reason = None
    previous_edd = None
    prior_edd_source = None
    if pending and rush_bucket == AV_RUSH and previous_rush == AV_NON_RUSH:
        changed_to_rush = True
        changed_reason = CHANGED_RUSH_REASON_DAY_ADVANCE

    module_tags = [MOD_AT_VENDOR_TOTAL]
    if status == AV_STATUS_PENDING:
        module_tags.append(MOD_AT_VENDOR_PENDING)
    else:
        module_tags.append(MOD_AT_VENDOR_COMPLETED)
    if changed_to_rush:
        module_tags.append(MOD_AT_VENDOR_CHANGED_RUSH)

    customer = meta.get("customer_name") or meta.get("name_clean")
    row = {
        "bag_id": bag_id,
        "customer": customer,
        "customer_name": customer,
        "service_type": svc if svc in ("WF", "HD") else None,
        "service_bucket": svc,
        "rush_bucket": rush_bucket,
        "rush_label": (
            "Rush"
            if rush_bucket == AV_RUSH
            else ("Non-Rush" if rush_bucket == AV_NON_RUSH else "Unknown Review")
        ),
        "estimated_delivery_date": latest_edd.isoformat() if latest_edd else None,
        "date_clean": latest_edd.isoformat() if latest_edd else None,
        "has_today_label": _has_today_label(delivery_texts),
        "today_label": "yes" if _has_today_label(delivery_texts) else "no",
        "sent_to_vendor_time": sent_ts.isoformat() if sent_ts else None,
        "sent_to_vendor_time_et": _format_et_display(sent_ts),
        "completion_signal": completion_signal,
        "completion_time": completion_ts.isoformat() if completion_ts else None,
        "completion_time_et": _format_et_display(completion_ts),
        "at_vendor_status": status,
        "facility_status": status.lower(),
        "reason": rush_reason,
        "rush_reason": rush_reason,
        "status_reason": (
            "Pending — sent-to-vendor scan missing"
            if sent_ts is None
            else (
                "Pending — second weight-entry after sent-to-vendor missing"
                if status == AV_STATUS_PENDING and svc == "WF"
                else (
                    "Pending — HD completion signal missing"
                    if status == AV_STATUS_PENDING
                    else f"Completed — {completion_signal}"
                )
            )
        ),
        "portal_yet_to_process": meta.get("portal_yet_to_process"),
        "active_presence": meta.get("active_presence", True),
        "portal_status": meta.get("portal_status"),
        "inclusion_reason": meta.get(
            "inclusion_reason",
            "Active at_vendor cleaner-ticket presence (Vendor Home orders at VeeWash)",
        ),
        "population_source": meta.get("population_source", "presence"),
        "delivery_source": delivery_source,
        "selected_date_et": selected_date_et.isoformat(),
        "population_inclusion": meta.get("population_inclusion"),
        "currently_on_vendor_home": meta.get("currently_on_vendor_home"),
        "left_vendor_home_but_counted": (
            meta.get("currently_on_vendor_home") is False
            and bool(meta.get("population_inclusion"))
        ),
        "previous_rush_bucket": previous_rush,
        "previous_edd": previous_edd.isoformat() if previous_edd else None,
        "prior_edd_source": prior_edd_source,
        "changed_to_rush": changed_to_rush,
        "changed_to_rush_reason": changed_reason,
        "module_tags": module_tags,
        "drilldown_tags": module_tags,
    }
    if prior_edd_info is not None:
        prior_edd, prior_source = prior_edd_info
        _apply_prior_edd_changed_to_rush(
            row,
            prior_edd=prior_edd,
            prior_source=prior_source,
            selected_date_et=selected_date_et,
        )
    return row


def build_at_vendor_module(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.rinse_shift_monitor_baseline import uses_clean_veewash_baseline

    org = int(organization_id)
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    start_of_day_et = naive_et_day_start(selected_date_et)
    t0 = time.perf_counter()
    step_ms: dict[str, float] = {}
    uses_clean_baseline = uses_clean_veewash_baseline(baseline_ctx)

    t_pop = time.perf_counter()
    if uses_clean_baseline and baseline_ctx:
        population, population_meta = _load_baseline_gated_at_vendor_population(
            cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
        )
    else:
        population, population_meta = _load_selected_day_at_vendor_population(
            cursor, org, selected_date_et=selected_date_et
        )
    step_ms["population_ms"] = round((time.perf_counter() - t_pop) * 1000, 1)
    if not population_meta.get("available"):
        reason = str(
            population_meta.get("reason")
            or "At Vendor selected-day population unavailable"
        )
        return _unavailable_at_vendor_module(
            selected_date_et,
            reason=reason,
            population_meta=population_meta,
        )

    bag_ids = [str(p.get("bag_id") or "").strip().upper() for p in population if p.get("bag_id")]
    carry_in_pre_midnight_events = population_meta.pop("carry_in_pre_midnight_events", None) or {}
    population_meta.pop("registry_service_cache", None)
    t_events = time.perf_counter()
    if uses_clean_baseline and baseline_ctx:
        baseline_start = baseline_ctx.get("baseline_start_naive_et")
        events_by_bag = _load_at_vendor_scan_events_for_bags(
            cursor,
            org,
            bag_ids,
            scanned_on_or_after=baseline_start if isinstance(baseline_start, datetime) else None,
        )
        carry_in_events_reused = 0
    else:
        cached_bag_ids = [bid for bid in bag_ids if bid in carry_in_pre_midnight_events]
        uncached_bag_ids = [bid for bid in bag_ids if bid not in carry_in_pre_midnight_events]
        post_midnight_by_bag = _load_at_vendor_scan_events_for_bags(
            cursor,
            org,
            cached_bag_ids,
            scanned_on_or_after=start_of_day_et,
        )
        full_events_by_bag = _load_at_vendor_scan_events_for_bags(cursor, org, uncached_bag_ids)
        events_by_bag: dict[str, list[dict[str, Any]]] = {}
        for bid in cached_bag_ids:
            events_by_bag[bid] = list(carry_in_pre_midnight_events.get(bid) or []) + list(
                post_midnight_by_bag.get(bid) or []
            )
        for bid in uncached_bag_ids:
            events_by_bag[bid] = list(full_events_by_bag.get(bid) or [])
        carry_in_events_reused = sum(
            len(carry_in_pre_midnight_events.get(bid) or []) for bid in cached_bag_ids
        )
    step_ms["final_events_ms"] = round((time.perf_counter() - t_events) * 1000, 1)
    scan_events_loaded = sum(len(events_by_bag.get(bid) or []) for bid in bag_ids)
    registry_cache = population_meta.get("registry_service_cache") or {}
    registry_service = (
        registry_cache
        if isinstance(registry_cache, dict) and registry_cache
        else _load_registry_service_types(cursor, org, bag_ids)
    )

    t_rows = time.perf_counter()
    rows: list[dict[str, Any]] = []
    pending_for_prior_edd: list[str] = []
    for pres in population:
        bid = str(pres.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        meta = dict(pres)
        if not meta.get("service_type") and registry_service.get(bid):
            meta["service_type"] = registry_service.get(bid)
        row = _build_row(
            bag_id=bid,
            meta=meta,
            events=events_by_bag.get(bid) or [],
            selected_date_et=selected_date_et,
            as_of_end=as_of_end,
        )
        rows.append(row)
        if (
            row.get("at_vendor_status") == AV_STATUS_PENDING
            and MOD_AT_VENDOR_CHANGED_RUSH not in row.get("module_tags", [])
        ):
            pending_for_prior_edd.append(bid)
    step_ms["rows_ms"] = round((time.perf_counter() - t_rows) * 1000, 1)

    t_edd = time.perf_counter()
    prior_edd_map = _load_prior_edd_from_batches_bulk(cursor, org, pending_for_prior_edd)
    step_ms["prior_edd_ms"] = round((time.perf_counter() - t_edd) * 1000, 1)
    for row in rows:
        prior_info = prior_edd_map.get(row.get("bag_id") or "")
        if prior_info and prior_info[0] is not None:
            _apply_prior_edd_changed_to_rush(
                row,
                prior_edd=prior_info[0],
                prior_source=prior_info[1],
                selected_date_et=selected_date_et,
            )

    pending_rows = [r for r in rows if MOD_AT_VENDOR_PENDING in r.get("module_tags", [])]
    completed_rows = [r for r in rows if MOD_AT_VENDOR_COMPLETED in r.get("module_tags", [])]
    changed_rows = [r for r in rows if MOD_AT_VENDOR_CHANGED_RUSH in r.get("module_tags", [])]

    current_live_vendor_home_total = int(population_meta.get("current_live_vendor_home_total") or 0)
    selected_day_total = len(rows)
    pending = len(pending_rows)
    completed = len(completed_rows)
    changed_to_rush = len(changed_rows)

    prior_day_end = naive_et_day_end_inclusive(selected_date_et - timedelta(days=1))
    bags_completed_today: list[str] = []
    for row in completed_rows:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        svc = _normalize_service(row.get("service_type"))
        midnight_anchor = _latest_sent_to_vendor_ts(
            events_by_bag.get(bid) or [],
            before=start_of_day_et,
        )
        if midnight_anchor is not None:
            midnight_status, _, _, _ = _evaluate_bag_as_of(
                events_by_bag.get(bid) or [],
                service_type=svc,
                as_of_end=prior_day_end,
                anchor_ts_override=midnight_anchor,
            )
        else:
            midnight_status = _bag_status_as_of(
                events_by_bag.get(bid) or [],
                service_type=svc,
                as_of_end=prior_day_end,
            )
        if midnight_status != AV_STATUS_COMPLETED:
            bags_completed_today.append(bid)

    gone_but_counted = sorted(
        str(r.get("bag_id") or "").strip().upper()
        for r in rows
        if r.get("bag_id") and r.get("currently_on_vendor_home") is not True
    )

    live_presence_pending = sum(
        1 for r in rows if r.get("currently_on_vendor_home") and r.get("portal_yet_to_process")
    )
    live_presence_completed = max(
        0,
        current_live_vendor_home_total
        - sum(1 for r in rows if r.get("currently_on_vendor_home") and r.get("portal_yet_to_process") is False),
    )
    pending_diff_vs_live = pending - live_presence_pending
    completed_diff_vs_live = completed - live_presence_completed
    timing_tolerance = 2

    population_meta = {
        **population_meta,
        "bags_completed_today": bags_completed_today,
        "bags_gone_from_vendor_home_but_counted": gone_but_counted,
        "selected_day_at_vendor_total": selected_day_total,
    }

    carry_in_count = int(population_meta.get("carry_in_open_at_midnight_count") or 0)
    new_sent_count = int(population_meta.get("new_during_selected_day_count") or population_meta.get("new_sent_to_vendor_today_count") or 0)
    portal_supplement = int(population_meta.get("portal_live_supplement_count") or 0)
    overlap_carry_and_new = int(population_meta.get("overlap_carry_in_and_new_sent_count") or 0)
    if uses_clean_baseline:
        seed_count = int(population_meta.get("clean_scrape_seed_count") or 0)
        post_sent_count = int(population_meta.get("post_baseline_sent_count") or 0)
        expected_total = seed_count + post_sent_count
        scope = "clean_veewash_baseline"
        population_source = "clean_veewash_baseline"
        timing_variance_reason = (
            "Current Vendor Home is the clean VeeWash at_vendor presence scrape seed. "
            "Selected-day At Vendor total adds post-baseline sent-to-vendor bags only."
        )
        reconciliation_note = (
            "Selected-day total = clean VeeWash scrape seed + post-baseline sent-to-vendor. "
            "Pre-baseline carry-in and contaminated presence rows are excluded from live counts."
        )
    else:
        expected_total = carry_in_count + new_sent_count - overlap_carry_and_new
        scope = "selected_day_cumulative"
        population_source = "selected_day_cumulative"
        timing_variance_reason = (
            "Current Vendor Home is a live moment-in-time snapshot. Selected-day At Vendor "
            "total uses carry-in at midnight plus new sent-to-vendor during the ET day."
        )
        reconciliation_note = (
            "Current Vendor Home does not control selected-day total. "
            "Selected-day total = carry-in open at midnight + new sent-to-vendor today."
        )

    cards = [
        {
            "id": "av_total",
            "label": "Total Bags",
            "module_tag": MOD_AT_VENDOR_TOTAL,
            "count": selected_day_total,
            "records_count": selected_day_total,
            "clickable": True,
        },
        {
            "id": "av_pending",
            "label": "Pending",
            "module_tag": MOD_AT_VENDOR_PENDING,
            "count": pending,
            "records_count": pending,
            "clickable": True,
        },
        {
            "id": "av_completed",
            "label": "Completed",
            "module_tag": MOD_AT_VENDOR_COMPLETED,
            "count": completed,
            "records_count": completed,
            "clickable": True,
        },
        {
            "id": "av_changed_rush",
            "label": "Changed to Rush",
            "module_tag": MOD_AT_VENDOR_CHANGED_RUSH,
            "count": changed_to_rush,
            "records_count": changed_to_rush,
            "clickable": True,
            "highlight": True,
        },
    ]

    return {
        "live": True,
        "selected_date_et": selected_date_et.isoformat(),
        "start_of_day_et": start_of_day_et.isoformat(),
        "end_of_day_et": as_of_end.isoformat(),
        "rows": rows,
        "cards": cards,
        "total": selected_day_total,
        "pending": pending,
        "completed": completed,
        "changed_to_rush": changed_to_rush,
        "total_equals_pending_plus_completed": selected_day_total == pending + completed,
        "uses_scans": True,
        "scope": scope,
        "population_source": population_source,
        "uses_clean_veewash_baseline": uses_clean_baseline,
        "current_live_vendor_home_total": current_live_vendor_home_total,
        "vendor_home_at_veewash_total": current_live_vendor_home_total,
        "selected_day_at_vendor_total": selected_day_total,
        "carry_in_open_at_midnight_count": population_meta.get("carry_in_open_at_midnight_count"),
        "new_sent_to_vendor_today_count": population_meta.get("new_sent_to_vendor_today_count"),
        "total_reconciles_to_vendor_home": False,
        "reconciliation": {
            "current_live_vendor_home_total": current_live_vendor_home_total,
            "selected_day_at_vendor_total": selected_day_total,
            "carry_in_open_at_midnight_count": population_meta.get("carry_in_open_at_midnight_count"),
            "new_sent_to_vendor_today_count": population_meta.get("new_sent_to_vendor_today_count"),
            "portal_live_supplement_count": population_meta.get("portal_live_supplement_count"),
            "new_during_selected_day_count": population_meta.get("new_during_selected_day_count"),
            "at_vendor_total": selected_day_total,
            "at_vendor_pending": pending,
            "at_vendor_completed": completed,
            "difference_total_vs_live_vendor_home": selected_day_total - current_live_vendor_home_total,
            "difference_pending_vs_live_vendor_home": pending_diff_vs_live,
            "difference_completed_vs_live_vendor_home": completed_diff_vs_live,
            "total_reconciles_to_selected_day_formula": (
                selected_day_total == expected_total
            ),
            "overlap_carry_in_and_new_sent_count": overlap_carry_and_new,
            "pending_within_timing_tolerance": abs(pending_diff_vs_live) <= timing_tolerance,
            "completed_within_timing_tolerance": abs(completed_diff_vs_live) <= timing_tolerance,
            "timing_tolerance_bags": timing_tolerance,
            "timing_variance_reason": timing_variance_reason,
            "note": reconciliation_note,
        },
        "population_meta": population_meta,
        "presence_meta": population_meta,
        "perf": {
            "presence_bags": current_live_vendor_home_total,
            "selected_day_bags": selected_day_total,
            "scoped_bags": selected_day_total,
            "scan_events_loaded": scan_events_loaded,
            "carry_in_events_reused": carry_in_events_reused,
            "uses_purpose_filter": True,
            "carry_in_candidate_bags_scanned": population_meta.get("carry_in_candidate_bags_scanned"),
            "sent_before_candidate_count": population_meta.get("sent_before_candidate_count"),
            "total_build_ms": round((time.perf_counter() - t0) * 1000, 1),
            "step_ms": step_ms,
        },
    }
