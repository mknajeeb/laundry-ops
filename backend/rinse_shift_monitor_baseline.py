"""
Live Shift Monitor baseline — ignore pre-baseline history for live dashboard counts.

Historical data remains in DB for audit/search; live dashboard uses only:
  - latest successful At Vendor scrape after baseline
  - latest successful RFV scrape after baseline
  - scan events on/after baseline (ET wall time)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from backend.rinse_bag_stage_bounds import event_ts
from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_scan_time import (
    RINSE_SCAN_SOURCE_TIMEZONE,
    naive_system_utc,
    serialize_system_datetime_for_api,
    system_datetime_to_et,
)
from backend.ta_helpers import table_exists

ET = ZoneInfo(RINSE_SCAN_SOURCE_TIMEZONE)
_UTC = ZoneInfo("UTC")

KEY_BASELINE_START = "shift_monitor_baseline_start_at_et"
KEY_BASELINE_SOURCE = "shift_monitor_baseline_source"
KEY_BASELINE_NOTE = "shift_monitor_baseline_note"

DEFAULT_BASELINE_START_ET = "2026-06-10 00:00:00"
DEFAULT_BASELINE_SOURCE = "manual_reset"
DEFAULT_BASELINE_NOTE = (
    "Live dashboard restarted from today ET to avoid historical data contamination"
)

REASON_IN_AT_VENDOR_SCRAPE = (
    "Included because bag appears in latest At Vendor scrape after baseline."
)
REASON_IN_RFV_SCRAPE = (
    "Included because bag appears in latest RFV scrape after baseline."
)
REASON_EXCLUDED_PRE_BASELINE = (
    "Excluded from live dashboard because only pre-baseline history exists."
)


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def parse_baseline_start_naive_et(raw: str | None) -> datetime:
    """Parse baseline start as naive America/New_York wall datetime."""
    text = str(raw or DEFAULT_BASELINE_START_ET).strip()
    if "T" in text:
        text = text.replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            dt = datetime.strptime(text[:n], fmt)
            if fmt == "%Y-%m-%d":
                return naive_et_day_start(dt.date())
            return dt
        except ValueError:
            continue
    return naive_et_day_start(date(2026, 6, 10))


def baseline_start_utc_naive(baseline_start_naive_et: datetime) -> datetime:
    aware = baseline_start_naive_et.replace(tzinfo=ET)
    return aware.astimezone(_UTC).replace(tzinfo=None)


def get_shift_monitor_baseline(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    start_raw = _get_setting(cursor, org, KEY_BASELINE_START) or DEFAULT_BASELINE_START_ET
    start_naive_et = parse_baseline_start_naive_et(start_raw)
    source = _get_setting(cursor, org, KEY_BASELINE_SOURCE) or DEFAULT_BASELINE_SOURCE
    note = _get_setting(cursor, org, KEY_BASELINE_NOTE) or DEFAULT_BASELINE_NOTE
    return {
        "active": True,
        "shift_monitor_baseline_start_at_et": start_naive_et.strftime("%Y-%m-%d %H:%M:%S"),
        "shift_monitor_baseline_start_at_et_iso": start_naive_et.isoformat(),
        "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
        "baseline_source": source,
        "baseline_note": note,
        "baseline_start_utc": serialize_system_datetime_for_api(baseline_start_utc_naive(start_naive_et)),
    }


def put_shift_monitor_baseline(
    cursor,
    organization_id: int,
    *,
    start_at_et: str | None = None,
    baseline_source: str | None = None,
    baseline_note: str | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    if start_at_et is not None:
        parsed = parse_baseline_start_naive_et(start_at_et)
        _set_setting(cursor, org, KEY_BASELINE_START, parsed.strftime("%Y-%m-%d %H:%M:%S"))
    if baseline_source is not None:
        _set_setting(cursor, org, KEY_BASELINE_SOURCE, str(baseline_source))
    if baseline_note is not None:
        _set_setting(cursor, org, KEY_BASELINE_NOTE, str(baseline_note))
    return get_shift_monitor_baseline(cursor, org)


def _fmt_scrape_time(run: Mapping[str, Any] | None) -> str | None:
    if not run:
        return None
    raw = run.get("finished_at") or run.get("started_at") or run.get("created_at")
    if isinstance(raw, datetime):
        et = system_datetime_to_et(raw)
        if et is not None:
            return et.strftime("%Y-%m-%d %H:%M:%S")
    return str(raw) if raw else None


def latest_at_vendor_scrape_after_baseline(
    cursor,
    organization_id: int,
    baseline_utc: datetime,
) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_scrape_runs"):
        return None
    org = int(organization_id)
    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id, error_message, run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'success'
          AND COALESCE(finished_at, started_at) >= %s
        ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (org, baseline_utc),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def latest_rfv_scrape_after_baseline(
    cursor,
    organization_id: int,
    baseline_utc: datetime,
) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return None
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_READY

    org = int(organization_id)
    cursor.execute(
        """
        SELECT *
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND portal_status = %s AND dry_run = 0
          AND (
            status IN ('success', 'partial')
            OR (status IS NULL AND (errors_json IS NULL OR errors_json = '' OR errors_json = '[]'))
          )
          AND COALESCE(finished_at, created_at) >= %s
        ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (org, PORTAL_STATUS_READY, baseline_utc),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def build_baseline_context(cursor, organization_id: int, baseline: Mapping[str, Any]) -> dict[str, Any]:
    start_naive_et = parse_baseline_start_naive_et(baseline.get("shift_monitor_baseline_start_at_et"))
    baseline_utc = baseline_start_utc_naive(start_naive_et)
    av_run = latest_at_vendor_scrape_after_baseline(cursor, organization_id, baseline_utc)
    rfv_run = latest_rfv_scrape_after_baseline(cursor, organization_id, baseline_utc)
    return {
        **dict(baseline),
        "baseline_start_naive_et": start_naive_et,
        "baseline_start_utc": baseline_utc,
        "latest_at_vendor_scrape_after_baseline": _fmt_scrape_time(av_run),
        "latest_at_vendor_scrape_run_id": av_run.get("id") if av_run else None,
        "latest_at_vendor_scrape_batch_id": av_run.get("imported_batch_id") if av_run else None,
        "latest_rfv_scrape_after_baseline": _fmt_scrape_time(rfv_run),
        "latest_rfv_scrape_run_id": rfv_run.get("id") if rfv_run else None,
        "at_vendor_scrape_ready": av_run is not None,
        "rfv_scrape_ready": rfv_run is not None,
        "needs_refresh": av_run is None,
        "needs_refresh_reason": (
            "Needs Refresh — no post-baseline At Vendor scrape found"
            if av_run is None
            else None
        ),
    }


def filter_events_after_baseline(
    events: Sequence[Mapping[str, Any]],
    baseline_start_naive_et: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events:
        ts = event_ts(ev)
        if ts is None or ts == datetime.min:
            continue
        if ts >= baseline_start_naive_et:
            out.append(dict(ev))
    return out


def filter_events_by_bag_after_baseline(
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    baseline_start_naive_et: datetime,
) -> dict[str, list[dict[str, Any]]]:
    return {
        bid: filter_events_after_baseline(evts, baseline_start_naive_et)
        for bid, evts in events_by_bag.items()
    }


def load_live_at_facility_population(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    baseline_ctx: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """
    Live at-VeeWash population — latest post-baseline At Vendor scrape (active staging) only.
    No registry supplement or pre-baseline lifecycle carryover.
    """
    from backend.rinse_current_facility_snapshot import _merge_row
    from backend.rinse_shift_analysis import load_active_staging_population_rows

    org = int(organization_id)
    meta: dict[str, Any] = {
        "source": "live_baseline_at_vendor_scrape",
        "live_baseline_active": True,
        "at_vendor_scrape_ready": bool(baseline_ctx.get("at_vendor_scrape_ready")),
        "latest_at_vendor_scrape_after_baseline": baseline_ctx.get("latest_at_vendor_scrape_after_baseline"),
        "staging_count": 0,
        "registry_supplement_count": 0,
        "at_vendor_presence_count": 0,
        "unified_total": 0,
        "excluded_pre_baseline_only_count": 0,
    }
    rows: dict[str, dict[str, Any]] = {}
    if not baseline_ctx.get("at_vendor_scrape_ready"):
        meta["needs_refresh"] = True
        meta["needs_refresh_reason"] = baseline_ctx.get("needs_refresh_reason")
        return rows, meta

    staging_pop, staging_meta = load_active_staging_population_rows(cursor, org, target_date=target_date)
    meta["staging_count"] = len(staging_pop)
    meta["staging_meta"] = staging_meta
    for row in staging_pop:
        enriched = {
            **row,
            "in_active_staging": True,
            "registry_supplement": False,
            "baseline_inclusion_reason": REASON_IN_AT_VENDOR_SCRAPE,
            "live_dashboard": True,
        }
        _merge_row(rows, enriched, source="orders_staging")

    meta["unified_total"] = len(rows)
    return rows, meta


def load_live_rfv_incoming_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    baseline_ctx: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """RFV/incoming rows from presence — only when post-baseline RFV scrape exists."""
    from backend.rinse_cleaner_ticket_presence import (
        PORTAL_STATUS_READY,
        _presence_effective_rush,
        _presence_service_type,
    )

    org = int(organization_id)
    meta: dict[str, Any] = {
        "source": "live_baseline_rfv_scrape",
        "rfv_scrape_ready": bool(baseline_ctx.get("rfv_scrape_ready")),
        "latest_rfv_scrape_after_baseline": baseline_ctx.get("latest_rfv_scrape_after_baseline"),
        "row_count": 0,
        "zero_rows_after_baseline": False,
    }
    if not baseline_ctx.get("rfv_scrape_ready"):
        return [], meta

    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        meta["zero_rows_after_baseline"] = True
        return [], meta

    cursor.execute(
        """
        SELECT bag_id, customer_name, estimated_delivery_date, service_type, raw_row_json, portal_status
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s AND active = 1 AND portal_status = %s
        """,
        (org, PORTAL_STATUS_READY),
    )
    out: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict) or not raw.get("bag_id"):
            continue
        bid = str(raw["bag_id"]).strip().upper()
        svc = _presence_service_type(raw) or str(raw.get("service_type") or "WF").upper()
        out.append(
            {
                "bag_id": bid,
                "service_type": svc if svc in ("WF", "HD") else "WF",
                "date_clean": raw.get("estimated_delivery_date"),
                "name_clean": raw.get("customer_name"),
                "effective_rush": _presence_effective_rush(raw, target_date),
                "record_scope": "incoming",
                "ready_for_vendor": True,
                "presence_source": True,
                "source_seen_in": ["ready_for_vendor_presence"],
                "baseline_inclusion_reason": REASON_IN_RFV_SCRAPE,
                "live_dashboard": True,
            }
        )
    meta["row_count"] = len(out)
    meta["zero_rows_after_baseline"] = len(out) == 0
    return out, meta


def load_live_due_today_population(
    cursor,
    organization_id: int,
    today: date,
    *,
    baseline_ctx: Mapping[str, Any],
    live_at_facility: Mapping[str, Mapping[str, Any]],
    live_rfv_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Due today from live scrape + post-baseline RFV only — no registry-only rows."""
    from backend.rinse_current_facility_snapshot import _merge_row, parse_record_date

    rows: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {
        "source": "live_baseline_due_today",
        "staging_registry_count": 0,
        "rfv_incoming_count": 0,
        "unified_due_today_total": 0,
    }

    for bid, row in live_at_facility.items():
        dc = parse_record_date(row.get("date_clean") or row.get("due_date"))
        if dc != today:
            continue
        enriched = {
            **row,
            "baseline_inclusion_reason": REASON_IN_AT_VENDOR_SCRAPE,
            "live_dashboard": True,
        }
        _merge_row(rows, enriched, source="orders_staging")
        meta["staging_registry_count"] += 1

    for row in live_rfv_rows:
        dc = parse_record_date(row.get("date_clean") or row.get("due_date"))
        if dc != today:
            continue
        _merge_row(rows, dict(row), source="ready_for_vendor_presence")
        meta["rfv_incoming_count"] += 1

    meta["unified_due_today_total"] = len(rows)
    return rows, meta


def apply_live_baseline_to_pending_incoming(
    pending: dict[str, Any],
    live_rfv_rows: Sequence[Mapping[str, Any]],
    *,
    baseline_ctx: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace incoming/RFV rows with live baseline RFV only."""
    out = dict(pending)
    incoming = dict(pending.get("incoming") or {})
    if not baseline_ctx.get("rfv_scrape_ready"):
        incoming["rows"] = []
        incoming["live_baseline_cleared"] = True
        incoming["unavailable_reason"] = "No post-baseline RFV scrape — stale RFV rows excluded"
    else:
        incoming["rows"] = list(live_rfv_rows)
        incoming["live_baseline"] = True
        if not live_rfv_rows:
            incoming["zero_rows_after_baseline"] = True
    out["incoming"] = incoming
    return out


def compute_excluded_pre_baseline_only(
    *,
    legacy_unified_at: Mapping[str, Mapping[str, Any]],
    live_at_facility: Mapping[str, Mapping[str, Any]],
    live_due_today: Mapping[str, Mapping[str, Any]],
    live_rfv_bids: set[str],
) -> tuple[int, list[dict[str, Any]]]:
    """Bags that would have appeared pre-baseline but are excluded from live dashboard."""
    live_ids = (
        set(live_at_facility.keys())
        | set(live_due_today.keys())
        | live_rfv_bids
    )
    excluded: list[dict[str, Any]] = []
    for bid, row in legacy_unified_at.items():
        if bid in live_ids:
            continue
        src = list(row.get("source_seen_in") or [])
        if row.get("registry_supplement") or "registry" in src:
            excluded.append(
                {
                    "bag_id": bid,
                    "source_seen_in": src,
                    "baseline_inclusion_reason": REASON_EXCLUDED_PRE_BASELINE,
                }
            )
    return len(excluded), excluded


def build_baseline_debug_block(
    *,
    baseline_ctx: Mapping[str, Any],
    live_record_count: int,
    excluded_pre_baseline_only_count: int,
    excluded_samples: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "baseline": {
            "shift_monitor_baseline_start_at_et": baseline_ctx.get("shift_monitor_baseline_start_at_et"),
            "baseline_source": baseline_ctx.get("baseline_source"),
            "baseline_note": baseline_ctx.get("baseline_note"),
            "timezone": baseline_ctx.get("timezone"),
            "latest_at_vendor_scrape_after_baseline": baseline_ctx.get(
                "latest_at_vendor_scrape_after_baseline"
            ),
            "latest_rfv_scrape_after_baseline": baseline_ctx.get("latest_rfv_scrape_after_baseline"),
            "live_dashboard_record_count": int(live_record_count),
            "excluded_pre_baseline_only_count": int(excluded_pre_baseline_only_count),
            "needs_refresh": bool(baseline_ctx.get("needs_refresh")),
            "needs_refresh_reason": baseline_ctx.get("needs_refresh_reason"),
        },
        "excluded_pre_baseline_samples": list(excluded_samples or [])[:25],
        "included_via_current_scrape": (
            "Records included when present in latest post-baseline At Vendor or RFV scrape."
        ),
    }


def format_baseline_banner_et(baseline_ctx: Mapping[str, Any]) -> str:
    start = baseline_ctx.get("shift_monitor_baseline_start_at_et") or DEFAULT_BASELINE_START_ET
    try:
        dt = parse_baseline_start_naive_et(str(start))
        label = dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
        if label.startswith("0"):
            label = label[1:]
        return f"Live Dashboard Baseline: {label} ET"
    except Exception:
        return f"Live Dashboard Baseline: {start} ET"
