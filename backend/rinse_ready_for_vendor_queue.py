"""
Ready for Vendor queue — snapshot-only module.

Live counts come only from the latest successful RFV scrape (active presence rows).
No scans, staging backfill, or internal production logic.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_processing_settings import resolve_rfv_rush_cutoff_setting
from backend.rinse_scan_time import system_datetime_to_et
from backend.rinse_shift_monitor_baseline import latest_rfv_scrape_after_baseline
from backend.ta_helpers import table_exists

RFV_RUSH = "RUSH"
RFV_NON_RUSH = "NON_RUSH"
RFV_UNKNOWN = "UNKNOWN_REVIEW"
RFV_SOURCE = "ready_for_vendor_scrape"

_DELIVERY_JSON_KEYS = (
    "estimated_delivery_text",
    "Date",
    "Date_Clean",
    "estimated_delivery_raw",
)


def _presence_raw_row_json(row: Mapping[str, Any]) -> dict[str, Any]:
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


def _parse_presence_date(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
        from backend.rinse_portal_csv import parse_portal_date

        try:
            return parse_portal_date(text)
        except Exception:
            return None
    return None


def _infer_service_type_from_text(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    if text in ("WF", "WASH & FOLD", "WASH AND FOLD"):
        return "WF"
    if text in ("HD", "HOME DELIVERY", "HANG DRY", "HANG-DRY"):
        return "HD"
    if "HOME" in text and "DELIV" in text:
        return "HD"
    if "HANG" in text and "DRY" in text:
        return "HD"
    if "WASH" in text and "FOLD" in text:
        return "WF"
    return None


def _rfv_service_bucket(row: Mapping[str, Any]) -> str:
    svc_raw = str(row.get("service_type") or "").strip().upper()
    if svc_raw in ("WF", "HD"):
        return svc_raw
    rj = _presence_raw_row_json(row)
    for key in ("service_type", "ServiceType", "service_type_raw", "Sub-Service", "sub_service"):
        inferred = _infer_service_type_from_text(str(rj.get(key) or ""))
        if inferred:
            return inferred
    from etl.transform_orders import classify_service

    meaningful = [
        rj.get(k)
        for k in ("service_type", "ServiceType", "service_type_raw", "Sub-Service", "sub_service")
        if rj.get(k) is not None and str(rj.get(k)).strip()
    ]
    if meaningful:
        try:
            st = str(classify_service(meaningful) or "").strip().upper()
            if st in ("WF", "HD"):
                return st
        except Exception:
            pass
    inferred = _infer_service_type_from_text(svc_raw)
    return inferred if inferred in ("WF", "HD") else RFV_UNKNOWN


def _delivery_date_texts(row: Mapping[str, Any]) -> list[str]:
    rj = _presence_raw_row_json(row)
    out: list[str] = []
    for key in _DELIVERY_JSON_KEYS:
        val = rj.get(key)
        if val is not None and str(val).strip():
            out.append(str(val).strip())
    edd = row.get("estimated_delivery_date")
    if edd is not None and str(edd).strip():
        out.append(str(edd).strip())
    return out


def _has_today_label(row: Mapping[str, Any]) -> bool:
    for text in _delivery_date_texts(row):
        if "TODAY" in text.upper():
            return True
    return False


def _estimated_delivery_date_et(row: Mapping[str, Any]) -> date | None:
    edd = _parse_presence_date(row.get("estimated_delivery_date"))
    if edd is not None:
        return edd
    rj = _presence_raw_row_json(row)
    for key in ("Date_Clean", "Date", "estimated_delivery_text", "estimated_delivery_raw"):
        edd = _parse_presence_date(rj.get(key))
        if edd is not None:
            return edd
    return None


def _estimated_delivery_raw(row: Mapping[str, Any]) -> str | None:
    texts = _delivery_date_texts(row)
    return texts[0] if texts else None


def _scrape_time_et_from_run(run: Mapping[str, Any] | None) -> datetime | None:
    if not run:
        return None
    raw = run.get("finished_at") or run.get("created_at")
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        try:
            raw = datetime.fromisoformat(raw.replace("Z", "+00:00")[:26])
        except ValueError:
            return None
    if not isinstance(raw, datetime):
        return None
    et = system_datetime_to_et(raw)
    if et is not None:
        return et.replace(tzinfo=None)
    return raw.replace(tzinfo=None)


def classify_rfv_rush_bucket(
    *,
    has_today: bool,
    estimated_delivery_date_et: date | None,
    scrape_time_et: datetime,
    cutoff_time: time,
) -> tuple[str, str]:
    if has_today:
        return RFV_RUSH, "Rush because RFV row contains TODAY"

    if estimated_delivery_date_et is None:
        return RFV_UNKNOWN, "Unknown because EDD missing or invalid"

    scrape_date = scrape_time_et.date()
    if estimated_delivery_date_et < scrape_date:
        return RFV_RUSH, "Rush because RFV delivery date is past due"

    scrape_clock = scrape_time_et.time()
    before_cutoff = scrape_clock < cutoff_time

    if before_cutoff:
        if estimated_delivery_date_et == scrape_date:
            return RFV_RUSH, f"Rush because EDD equals scrape date {scrape_date.isoformat()}"
        if estimated_delivery_date_et > scrape_date:
            return (
                RFV_NON_RUSH,
                f"Non-Rush because EDD {estimated_delivery_date_et.isoformat()} is after scrape date {scrape_date.isoformat()}",
            )
    else:
        tomorrow = scrape_date + timedelta(days=1)
        if estimated_delivery_date_et == scrape_date:
            return RFV_RUSH, f"Rush because EDD equals scrape date {scrape_date.isoformat()}"
        if estimated_delivery_date_et == tomorrow:
            return (
                RFV_RUSH,
                "Rush because EDD is next day and RFV scrape ran at/after cutoff",
            )
        if estimated_delivery_date_et > tomorrow:
            return (
                RFV_NON_RUSH,
                f"Non-Rush because EDD {estimated_delivery_date_et.isoformat()} is after {tomorrow.isoformat()}",
            )

    return RFV_NON_RUSH, "Non-Rush by RFV cutoff rule"


def _drilldown_tags_for_row(rush_bucket: str, service_bucket: str) -> list[str]:
    tags = ["ready_for_vendor"]
    if rush_bucket == RFV_RUSH:
        tags.append("rfv_rush")
    elif rush_bucket == RFV_NON_RUSH:
        tags.append("rfv_non_rush")
    else:
        tags.append("rfv_unknown_needs_review")

    if service_bucket == "WF":
        tags.append("rfv_wf")
    elif service_bucket == "HD":
        tags.append("rfv_hd")

    if rush_bucket == RFV_RUSH and service_bucket == "WF":
        tags.append("rfv_rush_wf")
    elif rush_bucket == RFV_RUSH and service_bucket == "HD":
        tags.append("rfv_rush_hd")
    elif rush_bucket == RFV_NON_RUSH and service_bucket == "WF":
        tags.append("rfv_nonrush_wf")
    elif rush_bucket == RFV_NON_RUSH and service_bucket == "HD":
        tags.append("rfv_nonrush_hd")
    elif rush_bucket == RFV_UNKNOWN or service_bucket == RFV_UNKNOWN:
        tags.append("rfv_unknown_needs_review")

    return tags


def normalize_rfv_presence_row(
    row: Mapping[str, Any],
    *,
    scrape_time_et: datetime,
    cutoff_time: time,
) -> dict[str, Any]:
    bid = str(row.get("bag_id") or "").strip().upper()
    has_today = _has_today_label(row)
    edd = _estimated_delivery_date_et(row)
    service_bucket = _rfv_service_bucket(row)
    rush_bucket, reason = classify_rfv_rush_bucket(
        has_today=has_today,
        estimated_delivery_date_et=edd,
        scrape_time_et=scrape_time_et,
        cutoff_time=cutoff_time,
    )
    edd_iso = edd.isoformat() if edd is not None else None
    cutoff_label = cutoff_time.strftime("%H:%M")
    scrape_label = scrape_time_et.strftime("%Y-%m-%d %H:%M:%S")
    scrape_date_label = scrape_time_et.date().isoformat()
    return {
        "bag_id": bid,
        "customer_name": row.get("customer_name"),
        "estimated_delivery_raw": _estimated_delivery_raw(row),
        "estimated_delivery_date_et": edd_iso,
        "has_today_label": has_today,
        "service_bucket": service_bucket,
        "service_type": service_bucket if service_bucket in ("WF", "HD") else None,
        "rush_bucket": rush_bucket,
        "rush_label": (
            "Rush"
            if rush_bucket == RFV_RUSH
            else ("Non-Rush" if rush_bucket == RFV_NON_RUSH else "Unknown Review")
        ),
        "source": RFV_SOURCE,
        "reason": reason,
        "rfv_rush_cutoff_time_et": cutoff_label,
        "rfv_scrape_time_et": scrape_label,
        "rfv_scrape_date_et": scrape_date_label,
        "drilldown_tags": _drilldown_tags_for_row(rush_bucket, service_bucket),
        "record_scope": "incoming",
        "ready_for_vendor": True,
        "presence_source": True,
    }


def _load_active_rfv_presence_rows(
    cursor,
    organization_id: int,
    *,
    source_batch_id: str | None = None,
) -> list[dict[str, Any]]:
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_READY

    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return []
    org = int(organization_id)
    batch_id = str(source_batch_id or "").strip()
    if not batch_id:
        return []
    cursor.execute(
        """
        SELECT bag_id, customer_name, estimated_delivery_date, service_type, rush_flag, raw_row_json
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
          AND source_batch_id = %s
        ORDER BY last_seen_at DESC
        """,
        (org, PORTAL_STATUS_READY, batch_id),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict) and r.get("bag_id")]


def _count_tag(rows: Sequence[Mapping[str, Any]], tag: str) -> int:
    return sum(1 for r in rows if tag in (r.get("drilldown_tags") or []))


def _aggregate_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(rows),
        "rush_wf": 0,
        "rush_hd": 0,
        "nonrush_wf": 0,
        "nonrush_hd": 0,
        "unknown_needs_review": 0,
    }
    for row in rows:
        rush = row.get("rush_bucket")
        svc = row.get("service_bucket")
        if rush == RFV_RUSH and svc == "WF":
            counts["rush_wf"] += 1
        elif rush == RFV_RUSH and svc == "HD":
            counts["rush_hd"] += 1
        elif rush == RFV_NON_RUSH and svc == "WF":
            counts["nonrush_wf"] += 1
        elif rush == RFV_NON_RUSH and svc == "HD":
            counts["nonrush_hd"] += 1
        if rush == RFV_UNKNOWN or svc == RFV_UNKNOWN:
            counts["unknown_needs_review"] += 1
    counts["rush_total"] = counts["rush_wf"] + counts["rush_hd"]
    counts["nonrush_total"] = counts["nonrush_wf"] + counts["nonrush_hd"]
    counts["wf_total"] = counts["rush_wf"] + counts["nonrush_wf"]
    counts["hd_total"] = counts["rush_hd"] + counts["nonrush_hd"]
    return counts


def _make_rfv_card(label: str, count: int | None, tag: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    records_count = _count_tag(rows, tag) if tag else None
    if count is None:
        return {
            "label": label,
            "count": None,
            "drilldown_tag": tag,
            "records_count": records_count,
            "clickable": False,
            "needs_review": True,
        }
    parity = int(count) == int(records_count or 0)
    return {
        "label": label,
        "count": int(count),
        "drilldown_tag": tag,
        "records_count": int(records_count or 0),
        "clickable": parity,
        "needs_review": not parity,
    }


def _build_rfv_cards(section: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not section.get("live"):
        return []
    return [
        _make_rfv_card("Ready for Vendor Total", section.get("total"), "ready_for_vendor", rows),
        _make_rfv_card("Rush", section.get("rush_total"), "rfv_rush", rows),
        _make_rfv_card("Non-Rush", section.get("nonrush_total"), "rfv_non_rush", rows),
        _make_rfv_card("WF", section.get("wf_total"), "rfv_wf", rows),
        _make_rfv_card("HD", section.get("hd_total"), "rfv_hd", rows),
        _make_rfv_card("Rush WF", section.get("rush_wf"), "rfv_rush_wf", rows),
        _make_rfv_card("Rush HD", section.get("rush_hd"), "rfv_rush_hd", rows),
        _make_rfv_card("Non-Rush WF", section.get("nonrush_wf"), "rfv_nonrush_wf", rows),
        _make_rfv_card("Non-Rush HD", section.get("nonrush_hd"), "rfv_nonrush_hd", rows),
        _make_rfv_card("Unknown Review", section.get("unknown_needs_review"), "rfv_unknown_needs_review", rows),
    ]


def _finalize_section_counts(section: dict[str, Any]) -> None:
    parts = (
        int(section.get("rush_wf") or 0)
        + int(section.get("rush_hd") or 0)
        + int(section.get("nonrush_wf") or 0)
        + int(section.get("nonrush_hd") or 0)
        + int(section.get("unknown_needs_review") or 0)
    )
    total = int(section.get("total") or 0)
    rush_total = int(section.get("rush_wf") or 0) + int(section.get("rush_hd") or 0)
    nonrush_display = int(section.get("nonrush_wf") or 0) + int(section.get("nonrush_hd") or 0)
    nonrush_reconcile = nonrush_display + int(section.get("unknown_needs_review") or 0)
    section["rush_total"] = rush_total
    section["nonrush_total"] = nonrush_display
    section["split_sum"] = parts
    section["counts_add_up"] = total == parts
    section["rush_nonrush_reconciled"] = total == rush_total + nonrush_reconcile
    section["unreconciled"] = max(0, total - parts) if total != parts else 0


def build_ready_for_vendor_queue(
    cursor,
    organization_id: int,
    *,
    baseline_ctx: Mapping[str, Any],
    rfv_sync: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build snapshot-only Ready for Vendor section and normalized rows."""
    org = int(organization_id)
    sync = dict(rfv_sync or {})
    cutoff_cfg = resolve_rfv_rush_cutoff_setting(cursor, org)
    cutoff_time = cutoff_cfg["cutoff_time"]
    cutoff_label = cutoff_cfg["rfv_rush_cutoff_time_et"]
    cutoff_source = cutoff_cfg["rfv_rush_cutoff_source"]

    baseline_utc = baseline_ctx.get("baseline_start_utc")
    rfv_run = None
    if baseline_utc is not None:
        rfv_run = latest_rfv_scrape_after_baseline(cursor, org, baseline_utc)
    rfv_batch_id = str(
        baseline_ctx.get("latest_rfv_presence_source_batch_id")
        or (rfv_run.get("source_batch_id") if rfv_run else "")
        or ""
    ).strip()

    scrape_time_et = _scrape_time_et_from_run(rfv_run)
    scrape_time_et_label = scrape_time_et.strftime("%Y-%m-%d %H:%M:%S") if scrape_time_et else None
    scrape_date_et_label = scrape_time_et.date().isoformat() if scrape_time_et else None

    meta: dict[str, Any] = {
        "source": RFV_SOURCE,
        "rfv_scrape_ready": bool(baseline_ctx.get("rfv_scrape_ready")),
        "rfv_scrape_time_et": scrape_time_et_label,
        "rfv_scrape_date_et": scrape_date_et_label,
        "scrape_time_et": scrape_time_et_label,
        "scrape_date_et": scrape_date_et_label,
        "rfv_rush_cutoff_time_et": cutoff_label,
        "rfv_rush_cutoff_source": cutoff_source,
        "latest_rfv_scrape_run_id": rfv_run.get("id") if rfv_run else None,
        "latest_rfv_presence_source_batch_id": rfv_batch_id or None,
        "active_rows": 0,
        "uses_scans": False,
    }

    last_refreshed_at = (
        sync.get("last_refreshed_at")
        or sync.get("last_success_at")
        or scrape_time_et_label
    )
    base_sync = sync if sync else {"sync_name": "Ready for Vendor Sync"}

    def _unavailable(reason: str) -> dict[str, Any]:
        section = {
            "live": False,
            "under_review": True,
            "total": None,
            "rush_total": None,
            "nonrush_total": None,
            "wf_total": None,
            "hd_total": None,
            "rush_wf": None,
            "rush_hd": None,
            "nonrush_wf": None,
            "nonrush_hd": None,
            "unknown_needs_review": None,
            "rows": [],
            "source": "Ready for Vendor queue",
            "last_refreshed_at": last_refreshed_at,
            "sync_status": base_sync,
            "unavailable_reason": reason,
            "data_quality_warning": reason,
            "drilldown_filter": "ready_for_vendor",
            "drilldown_source": "ready_for_vendor_rows",
            "rfv_scrape_time_et": scrape_time_et_label,
            "rfv_scrape_date_et": scrape_date_et_label,
            "scrape_time_et": scrape_time_et_label,
            "rfv_rush_cutoff_time_et": cutoff_label,
            "rfv_rush_cutoff_source": cutoff_source,
            "cards": [],
            "parity_ok": True,
            "rows_found": sync.get("rows_found"),
            "active_rows": sync.get("active_rows"),
        }
        return {"section": section, "rows": [], "bag_ids": set(), "meta": meta, "legacy_incoming_rows": []}

    enabled = sync.get("enabled", True)
    latest_status = str(sync.get("latest_status") or sync.get("status") or "")
    skipped_reason = sync.get("skipped_reason")
    error_message = sync.get("error") or sync.get("error_message")
    stale = bool(sync.get("stale"))

    if not enabled or latest_status == "disabled" or skipped_reason:
        return _unavailable(f"Ready for Vendor Sync skipped: {skipped_reason or 'feature flag disabled'}")
    if latest_status == "failed" or sync.get("latest_failed"):
        return _unavailable(f"Ready for Vendor Sync failed: {error_message or 'unknown error'}")
    active_probe = _load_active_rfv_presence_rows(cursor, org, source_batch_id=rfv_batch_id)
    zero_active_rows = len(active_probe) == 0
    if stale and not sync.get("zero_rows_success") and not zero_active_rows:
        stale_ref = last_refreshed_at or "unknown"
        return _unavailable(
            f"Ready for Vendor sync stale — last refresh {stale_ref}. Refresh Both Syncs before using live counts."
        )
    if not baseline_ctx.get("rfv_scrape_ready") or not rfv_batch_id:
        return _unavailable("No post-baseline RFV scrape — live snapshot unavailable")

    raw_rows = active_probe
    meta["active_rows"] = len(raw_rows)

    if raw_rows:
        normalized = [
            normalize_rfv_presence_row(r, scrape_time_et=scrape_time_et, cutoff_time=cutoff_time)
            for r in raw_rows
        ]
    else:
        normalized = []
    counts = _aggregate_counts(normalized)

    section: dict[str, Any] = {
        "live": True,
        "under_review": False,
        "total": counts["total"],
        "rush_total": counts["rush_total"],
        "nonrush_total": counts["nonrush_total"],
        "wf_total": counts["wf_total"],
        "hd_total": counts["hd_total"],
        "rush_wf": counts["rush_wf"],
        "rush_hd": counts["rush_hd"],
        "nonrush_wf": counts["nonrush_wf"],
        "nonrush_hd": counts["nonrush_hd"],
        "unknown_needs_review": counts["unknown_needs_review"],
        "rows": normalized,
        "source": "Ready for Vendor queue",
        "last_refreshed_at": last_refreshed_at,
        "sync_status": base_sync,
        "drilldown_filter": "ready_for_vendor",
        "drilldown_source": "ready_for_vendor_rows",
        "rfv_scrape_time_et": scrape_time_et_label,
        "rfv_scrape_date_et": scrape_date_et_label,
        "scrape_time_et": scrape_time_et_label,
        "scrape_date_et": scrape_date_et_label,
        "rfv_rush_cutoff_time_et": cutoff_label,
        "rfv_rush_cutoff_source": cutoff_source,
        "rows_found": sync.get("rows_found"),
        "active_rows": meta["active_rows"],
        "skipped_reason": skipped_reason,
        "error": error_message,
        "snapshot_only": True,
        "uses_scans": False,
    }
    if sync.get("zero_rows_success") or counts["total"] == 0:
        section["zero_rows_success"] = bool(sync.get("zero_rows_success") or counts["total"] == 0)
        if counts["total"] == 0:
            section["data_quality_warning"] = "Ready for Vendor = 0 after latest RFV scrape"
    _finalize_section_counts(section)
    section["cards"] = _build_rfv_cards(section, normalized)
    section["parity_ok"] = all(not c.get("needs_review") for c in section["cards"] if c.get("drilldown_tag"))

    legacy_incoming = [
        {
            "bag_id": r["bag_id"],
            "date_clean": r.get("estimated_delivery_date_et"),
            "effective_rush": r.get("rush_bucket"),
            "service_type": r.get("service_type"),
            "record_scope": "incoming",
            "ready_for_vendor": True,
            "presence_source": True,
        }
        for r in normalized
    ]

    bag_ids = {str(r.get("bag_id") or "").strip().upper() for r in normalized if r.get("bag_id")}

    return {
        "section": section,
        "rows": normalized,
        "bag_ids": bag_ids,
        "meta": meta,
        "legacy_incoming_rows": legacy_incoming,
    }
