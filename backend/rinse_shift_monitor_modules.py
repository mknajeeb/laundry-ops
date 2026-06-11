"""
Shift Monitor — five filtered operational modules with normalized record fields.

Modules:
  1. Rinse Portal Snapshot (point-in-time)
  2. At VeeWash / Facility Status
  3. Pending / Production Stage
  4. Exceptions
  5. Monitor
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_current_facility_snapshot import (
    PORTAL_VH_AT_VENDOR,
    PORTAL_VH_YET_TO_PROCESS,
    manual_vendor_home_counts,
)
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_drying_purpose,
    is_split_load_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
)
from backend.rinse_scan_time import system_datetime_to_et
from backend.rinse_work_pipeline import build_last_wash_detail, update_last_wash_if_newer

# Module drilldown tags
MOD_PORTAL_AT = "mod_portal_at_veewash"
MOD_PORTAL_PENDING = "mod_portal_pending_processing"
MOD_PORTAL_PROCESSED = "mod_portal_processed"

from backend.rinse_at_vendor_module import (
    MOD_AT_VENDOR_CHANGED_RUSH,
    MOD_AT_VENDOR_COMPLETED,
    MOD_AT_VENDOR_PENDING,
    MOD_AT_VENDOR_TOTAL,
)

MOD_FACILITY_TOTAL = MOD_AT_VENDOR_TOTAL
MOD_FACILITY_PENDING = MOD_AT_VENDOR_PENDING
MOD_FACILITY_PROCESSED = MOD_AT_VENDOR_COMPLETED
MOD_FACILITY_SENT = "mod_facility_sent"

MOD_PROD_TOTAL = "mod_prod_total_pending"
MOD_PROD_DONE = "mod_prod_done"
MOD_PROD_PENDING = "mod_prod_pending"
MOD_PROD_NOT_WEIGHED = "mod_prod_not_weighed"
MOD_PROD_WEIGHED_NOT_STARTED = "mod_prod_weighed_not_started"
MOD_PROD_SORTING_DONE = "mod_prod_sorting_done"
MOD_PROD_WASHING_STARTED = "mod_prod_washing_started"
MOD_PROD_DRYING_STARTED = "mod_prod_drying_started"
MOD_PROD_FOLDING_STARTED = "mod_prod_folding_started"
MOD_PROD_PROCESSED = "mod_prod_processed"
MOD_PROD_HD_NOT_STARTED = "mod_prod_hd_not_started"
MOD_PROD_HD_STARTED = "mod_prod_hd_started"
MOD_PROD_HD_COMPLETED = "mod_prod_hd_completed"
MOD_PROD_HD_PROCESSED = "mod_prod_hd_processed"

MOD_EX_WASHER = "mod_exc_washer_missing"
MOD_EX_DRYER = "mod_exc_dryer_missing"
MOD_EX_FOLDING = "mod_exc_folding_missing"
MOD_EX_CLEAN = "mod_exc_clean_missing"

MOD_MON_WEIGHT = "mod_mon_weight_discrepancy"

WF_ONLY_TAGS = frozenset(
    {
        MOD_PROD_NOT_WEIGHED,
        MOD_PROD_WEIGHED_NOT_STARTED,
        MOD_PROD_SORTING_DONE,
        MOD_PROD_WASHING_STARTED,
        MOD_PROD_DRYING_STARTED,
        MOD_PROD_FOLDING_STARTED,
    }
)
HD_ONLY_TAGS = frozenset(
    {
        MOD_PROD_HD_NOT_STARTED,
        MOD_PROD_HD_STARTED,
        MOD_PROD_HD_COMPLETED,
        MOD_PROD_HD_PROCESSED,
    }
)


def _norm_rush(rec: Mapping[str, Any]) -> str:
    label = str(rec.get("rush_label") or rec.get("computed_rush_label") or "").strip()
    bucket = str(rec.get("rush_bucket") or "")
    if label == "Rush" or bucket.startswith("rush"):
        return "RUSH"
    if label == "Non-Rush" or bucket.startswith("nonrush"):
        return "NON_RUSH"
    return "NON_RUSH"


def _norm_service(rec: Mapping[str, Any]) -> str:
    svc = str(rec.get("service_type") or rec.get("service_bucket") or "WF").upper()
    return svc if svc in ("WF", "HD") else "WF"


def _fmt_et(ts: Any) -> str | None:
    if isinstance(ts, datetime):
        et = system_datetime_to_et(ts)
        return et.strftime("%Y-%m-%d %H:%M:%S") if et else ts.isoformat()
    if ts:
        return str(ts)[:19]
    return None


def _has_weight(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_weight_entry_purpose(ev.get("purpose")) for ev in events)


def _has_start_cleaning(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_start_cleaning_purpose(ev.get("purpose")) for ev in events)


def _has_drying(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(is_drying_purpose(ev.get("purpose")) for ev in events)


def _has_sorting_done(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        is_add_photos_purpose(ev.get("purpose")) or is_split_load_purpose(ev.get("purpose"))
        for ev in events
    )


def _has_folding(events: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(ev.get("rack") or "").upper() == "FOLDING" for ev in events)


def _wf_production_stage(events: Sequence[Mapping[str, Any]], *, completed: bool) -> str | None:
    if completed:
        return MOD_PROD_PROCESSED
    if not _has_weight(events):
        return MOD_PROD_NOT_WEIGHED
    if not _has_start_cleaning(events):
        if _has_sorting_done(events):
            return MOD_PROD_SORTING_DONE
        return MOD_PROD_WEIGHED_NOT_STARTED
    if not _has_drying(events):
        return MOD_PROD_WASHING_STARTED
    if _has_folding(events):
        return MOD_PROD_FOLDING_STARTED
    if _has_drying(events):
        return MOD_PROD_DRYING_STARTED
    return MOD_PROD_WASHING_STARTED


def _exc_reason(tag: str) -> str:
    return {
        MOD_EX_WASHER: "Expected start-cleaning / washing evidence missing",
        MOD_EX_DRYER: "Expected drying scan/evidence missing",
        MOD_EX_FOLDING: "Expected folding scan/evidence missing",
        MOD_EX_CLEAN: "Expected final clean/completion scan missing",
    }.get(tag, "Scan exception")


def apply_module_tags(
    records: list[dict[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        events = events_by_bag.get(bid) or []
        tags = set(rec.get("drilldown_tags") or [])
        module_tags: set[str] = set()
        svc = _norm_service(rec)
        completed = bool(rec.get("completed"))

        if PORTAL_VH_AT_VENDOR in tags:
            module_tags.add(MOD_PORTAL_AT)
            if PORTAL_VH_YET_TO_PROCESS in tags:
                module_tags.add(MOD_PORTAL_PENDING)
            else:
                module_tags.add(MOD_PORTAL_PROCESSED)

        if "cfs_total" in tags:
            module_tags.add(MOD_FACILITY_TOTAL)
        if "cfs_in_progress" in tags:
            module_tags.add(MOD_FACILITY_PENDING)
            module_tags.add(MOD_PROD_TOTAL)
            if svc == "WF":
                stage = _wf_production_stage(events, completed=False)
                if stage:
                    module_tags.add(stage)
                if completed or "wf_completed_by_scan" in tags:
                    module_tags.add(MOD_PROD_DONE)
                    module_tags.add(MOD_PROD_PROCESSED)
            elif svc == "HD":
                if "hd_not_started" in tags:
                    module_tags.add(MOD_PROD_HD_NOT_STARTED)
                elif "hd_started_cleaning" in tags:
                    module_tags.add(MOD_PROD_HD_STARTED)
                if "hd_completed" in tags:
                    module_tags.add(MOD_PROD_HD_COMPLETED)
                    module_tags.add(MOD_PROD_DONE)
                if "hd_completed" in tags or "wf_completed_by_scan" in tags:
                    module_tags.add(MOD_PROD_HD_PROCESSED)
        if "cfs_completed_still_at_facility" in tags:
            module_tags.add(MOD_FACILITY_PROCESSED)
            module_tags.add(MOD_PROD_DONE)
            if svc == "WF" and "wf_completed_by_scan" in tags:
                module_tags.add(MOD_PROD_PROCESSED)
            if svc == "HD" and "hd_completed" in tags:
                module_tags.add(MOD_PROD_HD_COMPLETED)
                module_tags.add(MOD_PROD_HD_PROCESSED)
        if "cfs_sent_left" in tags:
            module_tags.add(MOD_FACILITY_SENT)

        if svc == "WF" and "cfs_in_progress" in tags and MOD_PROD_DONE not in module_tags:
            module_tags.add(MOD_PROD_PENDING)
        elif svc == "HD" and "cfs_in_progress" in tags and MOD_PROD_DONE not in module_tags:
            module_tags.add(MOD_PROD_PENDING)

        if svc == "WF" and "cfs_in_progress" in tags:
            if _has_weight(events) and not _has_start_cleaning(events):
                module_tags.add(MOD_EX_WASHER)
                rec["exception_reason"] = _exc_reason(MOD_EX_WASHER)
            elif _has_start_cleaning(events) and not _has_drying(events):
                module_tags.add(MOD_EX_DRYER)
                rec["exception_reason"] = _exc_reason(MOD_EX_DRYER)
            elif _has_drying(events) and not _has_folding(events) and not completed:
                module_tags.add(MOD_EX_FOLDING)
                rec["exception_reason"] = _exc_reason(MOD_EX_FOLDING)
        if svc == "WF" and "completed_without_clean" in tags:
            module_tags.add(MOD_EX_CLEAN)
            rec["exception_reason"] = _exc_reason(MOD_EX_CLEAN)

        wd = rec.get("weight_difference") or {}
        if svc == "WF" and wd.get("flagged"):
            module_tags.add(MOD_MON_WEIGHT)

        rec["service_bucket"] = svc
        rec["rush_bucket"] = _norm_rush(rec)
        rec["customer_name"] = rec.get("customer") or rec.get("name_clean")
        rec["last_activity_time_et"] = _fmt_et(
            rec.get("last_activity_time") or rec.get("last_scan_time")
        )
        rec["module_tags"] = sorted(module_tags)
        rec["drilldown_tags"] = sorted(set(rec.get("drilldown_tags") or []) | module_tags)


def filter_module_records(
    records: Sequence[Mapping[str, Any]],
    *,
    module_tag: str | None = None,
    rush_filter: str = "all",
    service_filter: str = "all",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if module_tag and module_tag not in (rec.get("module_tags") or []):
            continue
        rb = str(rec.get("rush_bucket") or "")
        if rush_filter == "rush" and rb != "RUSH":
            continue
        if rush_filter == "non_rush" and rb != "NON_RUSH":
            continue
        sb = str(rec.get("service_bucket") or rec.get("service_type") or "").upper()
        if service_filter == "wf" and sb != "WF":
            continue
        if service_filter == "hd" and sb != "HD":
            continue
        out.append(dict(rec))
    return out


def _card(
    card_id: str,
    label: str,
    module_tag: str,
    records: list[dict[str, Any]],
    *,
    wf_only: bool = False,
    hd_only: bool = False,
    informational: bool = False,
) -> dict[str, Any]:
    count = len([r for r in records if module_tag in (r.get("module_tags") or [])])
    return {
        "id": card_id,
        "label": label,
        "module_tag": module_tag,
        "count": count,
        "records_count": count,
        "clickable": not informational and bool(module_tag),
        "needs_review": False,
        "wf_only": wf_only,
        "hd_only": hd_only,
        "informational": informational,
    }


def _build_last_folding(
    records: list[dict[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    period_start: datetime,
    period_end_exclusive: datetime,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    last_overall = None
    last_rush = None
    last_nonrush = None
    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        for ev in events_by_bag.get(bid) or []:
            if str(ev.get("rack") or "").upper() != "FOLDING":
                continue
            ts = ev.get("scanned_at_parsed")
            if not isinstance(ts, datetime) or not (period_start <= ts < period_end_exclusive):
                continue
            detail = build_last_wash_detail(
                at=ts,
                bag_id=bid,
                customer=rec.get("customer_name") or rec.get("customer"),
                user=ev.get("user_name"),
                service_type=rec.get("service_bucket") or rec.get("service_type"),
                rush_label=rec.get("rush_label"),
                rush_bucket=rec.get("rush_bucket"),
            )
            detail["purpose"] = ev.get("purpose")
            last_overall = update_last_wash_if_newer(last_overall, detail)
            if rec.get("rush_bucket") == "RUSH" or rec.get("rush_label") == "Rush":
                last_rush = update_last_wash_if_newer(last_rush, detail)
            elif rec.get("rush_bucket") == "NON_RUSH" or rec.get("rush_label") == "Non-Rush":
                last_nonrush = update_last_wash_if_newer(last_nonrush, detail)
    return last_rush, last_nonrush, last_overall


def build_shift_monitor_modules(
    records: list[dict[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    period_start: date,
    period_end: date,
    period_start_dt: datetime,
    period_end_exclusive: datetime,
    portal_list_available: bool,
    portal_counts: Mapping[str, Any] | None,
    last_rush_wash: Mapping[str, Any] | None,
    last_nonrush_wash: Mapping[str, Any] | None,
    last_wash_overall: Mapping[str, Any] | None,
    today_et: date,
    at_vendor_module: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manual = manual_vendor_home_counts()
    portal = dict(portal_counts or {}) if portal_list_available and portal_counts else {}
    record_level_portal = bool(portal_list_available and portal)

    at_total = int(portal.get("at_veewash_total") or manual.get("at_veewash_total") or 0)
    at_pending = int(portal.get("at_veewash_yet_to_process") or manual.get("at_veewash_yet_to_process") or 0)
    at_processed = max(0, at_total - at_pending)
    due_total = int(portal.get("due_today_total") or manual.get("due_today_total") or 0)
    due_pending = int(portal.get("due_today_yet_to_process") or manual.get("due_today_yet_to_process") or 0)
    due_processed = max(0, due_total - due_pending)

    summary_only_portal_cards = [
        {
            "id": "portal_at",
            "label": "At VeeWash",
            "count": at_total,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
        {
            "id": "portal_pending",
            "label": "Pending Processing",
            "count": at_pending,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
        {
            "id": "portal_processed",
            "label": "Processed / Not Pending",
            "count": at_processed,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
        {
            "id": "portal_due_today",
            "label": "Due Today",
            "count": due_total,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
        {
            "id": "portal_due_today_pending",
            "label": "Due Today Pending",
            "count": due_pending,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
        {
            "id": "portal_due_today_processed",
            "label": "Due Today Processed / Not Pending",
            "count": due_processed,
            "clickable": False,
            "informational": True,
            "module_tag": None,
        },
    ]

    if record_level_portal:
        portal_at = len(filter_module_records(records, module_tag=MOD_PORTAL_AT))
        portal_pending = len(filter_module_records(records, module_tag=MOD_PORTAL_PENDING))
        portal_processed = len(filter_module_records(records, module_tag=MOD_PORTAL_PROCESSED))
        portal_cards = [
            _card("portal_at", "At VeeWash", MOD_PORTAL_AT, records),
            _card("portal_pending", "Pending Processing", MOD_PORTAL_PENDING, records),
            _card("portal_processed", "Processed / Not Pending", MOD_PORTAL_PROCESSED, records),
        ]
        portal_mode = "record_level"
        portal_note = None
    else:
        portal_at, portal_pending, portal_processed = at_total, at_pending, at_processed
        portal_cards = summary_only_portal_cards
        portal_mode = "summary_only"
        portal_note = "Portal filters unavailable because only summary counts are available."

    ops_label = (
        "Today ET Operations — 12:00 AM ET to now"
        if period_end == today_et
        else f"Selected ET Operations — {period_start.isoformat()} 12:00 AM ET to 11:59:59 PM ET"
    )

    av = dict(at_vendor_module or {})
    av_rows = list(av.get("rows") or [])
    av_selected = av.get("selected_date_et") or period_end.isoformat()
    facility_cards = list(av.get("cards") or []) or [
        _card("av_total", "Total Bags", MOD_AT_VENDOR_TOTAL, av_rows),
        _card("av_pending", "Pending", MOD_AT_VENDOR_PENDING, av_rows),
        _card("av_completed", "Completed", MOD_AT_VENDOR_COMPLETED, av_rows),
        {
            "id": "av_changed_rush",
            "label": "Changed to Rush",
            "module_tag": MOD_AT_VENDOR_CHANGED_RUSH,
            "count": int(av.get("changed_to_rush") or 0),
            "records_count": int(av.get("changed_to_rush") or 0),
            "clickable": True,
            "highlight": True,
        },
    ]

    production_cards = [
        _card("prod_total", "Total Pending", MOD_PROD_TOTAL, records),
        _card("prod_done", "Done", MOD_PROD_DONE, records),
        _card("prod_pending", "Pending", MOD_PROD_PENDING, records),
        _card("prod_not_weighed", "Not Weighed", MOD_PROD_NOT_WEIGHED, records, wf_only=True),
        _card("prod_weighed", "Weighed but Not Started", MOD_PROD_WEIGHED_NOT_STARTED, records, wf_only=True),
        _card("prod_sorting", "Sorting Done", MOD_PROD_SORTING_DONE, records, wf_only=True),
        _card("prod_washing", "Washing Started", MOD_PROD_WASHING_STARTED, records, wf_only=True),
        _card("prod_drying", "Drying Started", MOD_PROD_DRYING_STARTED, records, wf_only=True),
        _card("prod_folding", "Folding Started", MOD_PROD_FOLDING_STARTED, records, wf_only=True),
        _card("prod_processed", "Processed", MOD_PROD_PROCESSED, records),
        _card("prod_hd_not_started", "HD Not Started", MOD_PROD_HD_NOT_STARTED, records, hd_only=True),
        _card("prod_hd_started", "HD Started", MOD_PROD_HD_STARTED, records, hd_only=True),
        _card("prod_hd_completed", "HD Completed", MOD_PROD_HD_COMPLETED, records, hd_only=True),
        _card("prod_hd_processed", "HD Processed", MOD_PROD_HD_PROCESSED, records, hd_only=True),
    ]

    exception_cards = [
        _card("exc_washer", "Washer scan missing", MOD_EX_WASHER, records, wf_only=True),
        _card("exc_dryer", "Dryer scan missing", MOD_EX_DRYER, records, wf_only=True),
        _card("exc_folding", "Folding scan missing", MOD_EX_FOLDING, records, wf_only=True),
        _card("exc_clean", "Clean scan missing", MOD_EX_CLEAN, records, wf_only=True),
    ]

    last_rush_fold, last_nonrush_fold, last_fold = _build_last_folding(
        records, events_by_bag, period_start=period_start_dt, period_end_exclusive=period_end_exclusive
    )
    weight_count = len(filter_module_records(records, module_tag=MOD_MON_WEIGHT))

    monitor_cards = [
        {
            "id": "mon_weight",
            "label": "Weight Discrepancy",
            "module_tag": MOD_MON_WEIGHT,
            "count": weight_count,
            "records_count": weight_count,
            "clickable": True,
            "wf_only": True,
            "needs_review": False,
        },
        {
            "id": "mon_last_rush_wash",
            "label": "Last Rush Wash",
            "informational": True,
            "clickable": False,
            "detail": last_rush_wash,
        },
        {
            "id": "mon_last_nonrush_wash",
            "label": "Last Non-Rush Wash",
            "informational": True,
            "clickable": False,
            "detail": last_nonrush_wash,
        },
        {
            "id": "mon_last_wash",
            "label": "Last Wash",
            "informational": True,
            "clickable": False,
            "detail": last_wash_overall,
        },
        {
            "id": "mon_last_rush_fold",
            "label": "Last Rush Folding",
            "informational": True,
            "clickable": False,
            "detail": last_rush_fold,
        },
        {
            "id": "mon_last_nonrush_fold",
            "label": "Last Non-Rush Folding",
            "informational": True,
            "clickable": False,
            "detail": last_nonrush_fold,
        },
        {
            "id": "mon_last_fold",
            "label": "Last Folding",
            "informational": True,
            "clickable": False,
            "detail": last_fold,
        },
    ]

    return {
        "operations_window": {
            "label": ops_label,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "timezone": "America/New_York",
        },
        "portal_snapshot": {
            "title": "Rinse Portal Snapshot",
            "subtitle": "Rinse Portal Snapshot — point-in-time",
            "mode": portal_mode,
            "filters_enabled": record_level_portal,
            "note": portal_note,
            "summary": {
                "at_veewash": portal_at,
                "pending_processing": portal_pending,
                "processed": portal_processed,
                "due_today": due_total,
                "due_today_pending": due_pending,
                "due_today_processed": due_processed,
            },
            "cards": portal_cards,
        },
        "facility_status": {
            "title": "At Vendor",
            "subtitle": f"Selected ET day — {av_selected}",
            "filters_enabled": True,
            "cards": facility_cards,
            "rows_source": "at_vendor_module",
        },
        "production_stage": {
            "title": "Pending / Production Stage",
            "subtitle": "Current production stage buckets",
            "cards": production_cards,
        },
        "exceptions": {
            "title": "Exceptions",
            "subtitle": "WF scan-gap exceptions for current at-facility WIP",
            "cards": exception_cards,
        },
        "monitor": {
            "title": "Monitor",
            "subtitle": ops_label,
            "cards": monitor_cards,
        },
    }


def filter_cards_for_scope(
    cards: Sequence[Mapping[str, Any]],
    *,
    service_filter: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in cards:
        c = dict(card)
        if service_filter == "hd" and c.get("wf_only"):
            continue
        if service_filter == "wf" and c.get("hd_only"):
            continue
        out.append(c)
    return out
