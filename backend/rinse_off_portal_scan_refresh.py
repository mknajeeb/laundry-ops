"""Targeted scan refresh for off-portal Today's Workload Pending bags via direct ?q=BAGID lookup."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from backend.rinse_at_vendor_module import (
    AV_RUSH,
    AV_STATUS_COMPLETED,
    AV_STATUS_PENDING,
    _evaluate_bag_as_of,
    _load_wf_completion_supplement_for_bags,
    _merge_wf_completion_events_by_bag,
    _resolve_selected_day_anchor_ts,
    build_at_vendor_module,
)
from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_end_inclusive
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key
from backend.rinse_scan_events_logic import _parse_scanned_at
from backend.rinse_scan_events_upload import SCAN_EVENTS_CSV_COLUMNS, commit_scan_events_for_batch
from backend.rinse_scan_purpose import is_add_photos_purpose, is_weight_entry_purpose
from backend.rinse_scan_time import normalize_rack_value
from backend.ta_helpers import table_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETED_SCRAPE_SCRIPT = REPO_ROOT / "scripts" / "rinse-cleanertickets" / "scrape-targeted-bags.mjs"


def _env_flag(name: str, default: bool = False) -> bool:
    val = str(os.getenv(name, "") or "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def off_portal_refresh_enabled() -> bool:
    return _env_flag("RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED", default=False)


def off_portal_refresh_dry_run() -> bool:
    return _env_flag("RINSE_OFF_PORTAL_SCAN_REFRESH_DRY_RUN", default=False)


def off_portal_refresh_max_bags() -> int:
    try:
        return max(1, int(os.getenv("RINSE_OFF_PORTAL_SCAN_REFRESH_MAX_BAGS", "40") or 40))
    except (TypeError, ValueError):
        return 40


def off_portal_refresh_timeout_sec() -> int:
    try:
        return max(60, int(os.getenv("RINSE_OFF_PORTAL_SCAN_REFRESH_TIMEOUT_SEC", "3600") or 3600))
    except (TypeError, ValueError):
        return 3600


def off_portal_refresh_rush_only() -> bool:
    return _env_flag("RINSE_OFF_PORTAL_SCAN_REFRESH_RUSH_ONLY", default=False)


def _norm_purpose(purpose: str | None) -> str:
    return str(purpose or "").replace(" Last Scan", "").strip().lower()


def scan_content_key(
    *,
    bag_id: str | None = None,
    purpose: str | None = None,
    time_scanned_raw: str | None = None,
    rack: str | None = None,
    user_name: str | None = None,
) -> tuple[str, ...]:
    return (
        str(bag_id or "").strip().upper(),
        _norm_purpose(purpose),
        str(time_scanned_raw or "").strip().lower(),
        str(normalize_rack_value(rack) or "").strip().lower(),
        str(user_name or "").strip().lower(),
    )


def portal_event_to_csv_row(bag_id: str, ev: dict[str, Any]) -> dict[str, str]:
    purpose = str(ev.get("purpose") or "").strip()
    if ev.get("last_scan") == "Y" and purpose and "Last Scan" not in purpose:
        purpose = f"{purpose} Last Scan"
    return {
        "Bag ID": bag_id,
        "Scan Index": str(ev.get("scan_index") or ""),
        "Rack": str(ev.get("rack") or ""),
        "Time Scanned": str(ev.get("time_scanned") or ""),
        "User": str(ev.get("user") or ""),
        "Purpose": purpose,
        "Last Location": str(ev.get("last_location") or ""),
        "Last Scan": str(ev.get("last_scan") or ""),
    }


def portal_scans_to_events_df(bag_id: str, scans: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [portal_event_to_csv_row(bag_id, ev) for ev in scans]
    if not rows:
        return pd.DataFrame(columns=SCAN_EVENTS_CSV_COLUMNS)
    df = pd.DataFrame(rows, columns=SCAN_EVENTS_CSV_COLUMNS)
    df["scanned_at_parsed"] = df["Time Scanned"].map(_parse_scanned_at)
    return df


def _scraper_env_for_org(organization_id: int) -> dict[str, str]:
    from backend.rinse_bag_export_runner import scraper_dir
    from backend.rinse_vendor_config import rinse_scrape_env_for_organization

    _, vendor_env = rinse_scrape_env_for_organization(int(organization_id), scraper_dir=scraper_dir())
    return dict(vendor_env)


def run_targeted_portal_scrape(
    bag_ids: list[str],
    *,
    organization_id: int | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    ids = sorted({str(b or "").strip().upper() for b in bag_ids if str(b or "").strip()})
    if not ids:
        return {"bags": []}
    if not TARGETED_SCRAPE_SCRIPT.is_file():
        raise RuntimeError(f"Missing targeted scrape script: {TARGETED_SCRAPE_SCRIPT}")
    env = {**dict(os.environ)}
    if organization_id is not None:
        env.update(_scraper_env_for_org(organization_id))
    timeout = timeout_sec if timeout_sec is not None else off_portal_refresh_timeout_sec()
    proc = subprocess.run(
        ["node", str(TARGETED_SCRAPE_SCRIPT), *ids],
        cwd=str(TARGETED_SCRAPE_SCRIPT.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Targeted portal scrape failed rc={proc.returncode}\n"
            f"stderr={proc.stderr[-2000:]}\nstdout={proc.stdout[-2000:]}"
        )
    raw = proc.stdout.strip()
    start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"No JSON in targeted scrape output: {raw[-500:]}")
    return json.loads(raw[start:])


def _load_db_scan_keys(cursor, organization_id: int, bag_id: str) -> tuple[set[str], set[tuple[str, ...]]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set(), set()
    cursor.execute(
        """
        SELECT dedupe_key, bag_id, purpose, time_scanned_raw, rack, user_name
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND UPPER(TRIM(bag_id)) = %s
        """,
        (int(organization_id), bag_id),
    )
    dedupe_keys: set[str] = set()
    content_keys: set[tuple[str, ...]] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        dk = str(row.get("dedupe_key") or "").strip()
        if dk:
            dedupe_keys.add(dk)
        content_keys.add(
            scan_content_key(
                bag_id=row.get("bag_id"),
                purpose=row.get("purpose"),
                time_scanned_raw=row.get("time_scanned_raw"),
                rack=row.get("rack"),
                user_name=row.get("user_name"),
            )
        )
    return dedupe_keys, content_keys


def classify_portal_rows_against_db(
    cursor,
    organization_id: int,
    bag_id: str,
    scans: list[dict[str, Any]],
) -> dict[str, Any]:
    dedupe_keys, content_keys = _load_db_scan_keys(cursor, organization_id, bag_id)
    portal_rows = [portal_event_to_csv_row(bag_id, ev) for ev in scans]
    missing_rows: list[dict[str, str]] = []
    already_present = 0
    skipped_no_time = 0
    for row in portal_rows:
        time_raw = str(row.get("Time Scanned") or "").strip()
        if not time_raw:
            skipped_no_time += 1
            continue
        ck = scan_content_key(
            bag_id=bag_id,
            purpose=row.get("Purpose"),
            time_scanned_raw=time_raw,
            rack=row.get("Rack"),
            user_name=row.get("User"),
        )
        if ck in content_keys:
            already_present += 1
            continue
        try:
            scan_index = int(float(str(row.get("Scan Index") or "").strip())) if str(row.get("Scan Index") or "").strip() else None
        except (TypeError, ValueError):
            scan_index = None
        dk = compute_scan_event_dedupe_key(
            organization_id=int(organization_id),
            bag_id=bag_id,
            scan_index=scan_index,
            rack=row.get("Rack"),
            user_name=row.get("User"),
            purpose=row.get("Purpose"),
            time_scanned_raw=time_raw,
            scanned_at_parsed=_parse_scanned_at(time_raw),
        )
        if dk in dedupe_keys:
            already_present += 1
            continue
        missing_rows.append(row)
    return {
        "portal_scan_count": len(portal_rows),
        "missing_rows": missing_rows,
        "missing_row_count": len(missing_rows),
        "already_present_count": already_present,
        "skipped_no_time": skipped_no_time,
    }


def _weight_entries(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in scans:
        purpose = str(ev.get("purpose") or ev.get("Purpose") or "")
        if not is_weight_entry_purpose(purpose):
            continue
        ts_raw = str(ev.get("time_scanned") or ev.get("Time Scanned") or "")
        parsed = _parse_scanned_at(ts_raw) if ts_raw else None
        out.append({"ts": parsed, "ts_raw": ts_raw, "purpose": purpose, "user": ev.get("user") or ev.get("User")})
    return sorted(out, key=lambda r: (r.get("ts") or datetime.min, r.get("ts_raw") or ""))


def _completion_scans_after_ts(scans: list[dict[str, Any]], after: datetime | None) -> list[dict[str, str]]:
    if after is None:
        return []
    hits: list[dict[str, str]] = []
    for ev in scans:
        ts_raw = str(ev.get("time_scanned") or ev.get("Time Scanned") or "")
        parsed = _parse_scanned_at(ts_raw) if ts_raw else None
        if parsed is None or parsed <= after:
            continue
        purpose = _norm_purpose(ev.get("purpose") or ev.get("Purpose"))
        if any(
            token in purpose
            for token in (
                "weight-entry",
                "complete-cleaning",
                "processed-by-vendor",
                "delivery-prep-completed",
                "add-photos",
                "garments-reviewed",
                "assembly-printed-ct",
            )
        ):
            hits.append({"ts": str(parsed), "purpose": purpose, "raw": ts_raw})
    return hits


def simulate_status_after_import(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    module_row: dict[str, Any] | None,
    missing_rows: list[dict[str, str]],
) -> dict[str, Any]:
    from backend.rinse_at_vendor_module import _load_at_vendor_scan_events_for_bags

    scan_before = naive_et_day_end_exclusive(selected_date_et)
    av_scans = _load_at_vendor_scan_events_for_bags(
        cursor, int(organization_id), [bag_id], scanned_before=scan_before
    ).get(bag_id) or []
    wf_sup = _load_wf_completion_supplement_for_bags(
        cursor, int(organization_id), [bag_id], scanned_before=scan_before
    ).get(bag_id) or []
    merged = _merge_wf_completion_events_by_bag({bag_id: av_scans}, {bag_id: wf_sup}).get(bag_id) or []

    synthetic = []
    for row in missing_rows:
        synthetic.append(
            {
                "bag_id": bag_id,
                "purpose": row.get("Purpose"),
                "time_scanned_raw": row.get("Time Scanned"),
                "scanned_at_parsed": _parse_scanned_at(str(row.get("Time Scanned") or "")),
                "rack": row.get("Rack"),
                "user_name": row.get("User"),
                "scan_index": row.get("Scan Index"),
            }
        )
    timeline = list(merged) + synthetic
    svc = (module_row or {}).get("service_type") or (module_row or {}).get("service_bucket") or "WF"
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    anchor = _resolve_selected_day_anchor_ts(timeline, selected_date_et)
    status_before = (module_row or {}).get("at_vendor_status")
    status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
        timeline,
        service_type=str(svc).upper(),
        as_of_end=as_of_end,
        anchor_ts_override=anchor,
    )
    if module_row and module_row.get("daily_classification"):
        # Mirror daily_et_attribution pending override in _build_row.
        comp_date = comp_ts.date() if comp_ts is not None else None
        if not (
            status == AV_STATUS_COMPLETED
            and comp_date == selected_date_et
            and comp_ts is not None
            and comp_ts <= as_of_end
        ):
            status = AV_STATUS_PENDING
            signal = None
            comp_ts = None
    return {
        "status_before": status_before,
        "expected_status_after_import": status,
        "expected_completion_signal": signal,
        "expected_completion_ts": str(comp_ts) if comp_ts else None,
        "would_complete": status == AV_STATUS_COMPLETED,
    }


def compare_bag_portal_vs_db(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    portal_payload: dict[str, Any] | None = None,
    module_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bid = str(bag_id or "").strip().upper()
    if portal_payload is None:
        portal_payload = (run_targeted_portal_scrape([bid], organization_id=organization_id).get("bags") or [{}])[0]
    scans = portal_payload.get("scans") or []
    classified = classify_portal_rows_against_db(cursor, organization_id, bid, scans)
    missing_rows = classified["missing_rows"]
    missing_purposes = sorted({_norm_purpose(r.get("Purpose")) for r in missing_rows})

    cursor.execute(
        """
        SELECT COUNT(*) AS n, MAX(scanned_at_parsed) AS latest
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND UPPER(TRIM(bag_id)) = %s
        """,
        (int(organization_id), bid),
    )
    db_summary = dict(cursor.fetchone() or {})
    portal_latest = None
    if scans:
        parsed_scans = []
        for ev in scans:
            ts = _parse_scanned_at(str(ev.get("time_scanned") or ""))
            if ts:
                parsed_scans.append((ts, ev))
        if parsed_scans:
            ts, ev = max(parsed_scans, key=lambda x: x[0])
            portal_latest = {
                "ts": str(ts),
                "purpose": str(ev.get("purpose") or ""),
                "raw": str(ev.get("time_scanned") or ""),
            }

    weights = _weight_entries(scans)
    second_we = weights[1] if len(weights) >= 2 else None
    cursor.execute(
        """
        SELECT purpose, time_scanned_raw, user_name, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND UPPER(TRIM(bag_id)) = %s
        ORDER BY scanned_at_parsed, id
        """,
        (int(organization_id), bid),
    )
    db_weights = _weight_entries(
        [
            {
                "purpose": r.get("purpose"),
                "time_scanned": r.get("time_scanned_raw"),
                "user": r.get("user_name"),
            }
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict)
        ]
    )
    completion_after_second = _completion_scans_after_ts(
        scans,
        second_we.get("ts") if second_we else None,
    )
    sim = simulate_status_after_import(
        cursor,
        organization_id,
        bid,
        selected_date_et=selected_date_et,
        module_row=module_row,
        missing_rows=missing_rows,
    )
    return {
        "bag_id": bid,
        "portal_found": bool(portal_payload.get("found")),
        "portal_error": portal_payload.get("error"),
        "portal_row_count": classified["portal_scan_count"],
        "db_row_count": int(db_summary.get("n") or 0),
        "missing_row_count": classified["missing_row_count"],
        "already_present_count": classified["already_present_count"],
        "missing_purposes": missing_purposes,
        "latest_portal_scan": portal_latest,
        "latest_db_scan": {
            "ts": str(db_summary.get("latest")) if db_summary.get("latest") else None,
        },
        "portal_second_weight_entry": second_we,
        "db_weight_entries": db_weights,
        "completion_scans_after_second_weight_entry": completion_after_second,
        "expected_status_after_import": sim["expected_status_after_import"],
        "status_before": sim["status_before"],
        "would_complete": sim["would_complete"],
        "expected_completion_signal": sim["expected_completion_signal"],
    }


def get_latest_successful_crawl_batch_id(cursor, organization_id: int) -> int | None:
    if not table_exists(cursor, "rinse_scrape_runs"):
        return None
    cursor.execute(
        """
        SELECT imported_batch_id
        FROM rinse_scrape_runs
        WHERE organization_id = %s
          AND status IN ('success', 'needs_attention')
          AND imported_batch_id IS NOT NULL
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict) or not row.get("imported_batch_id"):
        return None
    return int(row["imported_batch_id"])


def bag_in_portal_crawl_batch(
    cursor,
    organization_id: int,
    batch_id: int,
    bag_id: str,
) -> bool:
    bid = str(bag_id or "").strip().upper()
    if not bid:
        return False
    cursor.execute(
        """
        SELECT 1
        FROM upload_batch_rows
        WHERE upload_batch_id = %s AND UPPER(TRIM(ticket_id)) = %s
        LIMIT 1
        """,
        (int(batch_id), bid),
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        """
        SELECT 1
        FROM upload_batch_scan_events
        WHERE organization_id = %s AND upload_batch_id = %s AND UPPER(TRIM(bag_id)) = %s
        LIMIT 1
        """,
        (int(organization_id), int(batch_id), bid),
    )
    return cursor.fetchone() is not None


def resolve_pending_not_in_latest_crawl_bag_ids(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    rush_only: bool = False,
    crawl_batch_id: int | None = None,
) -> tuple[list[str], int | None, dict[str, bool]]:
    """Today's Workload Pending bags absent from the latest portal crawl export."""
    from backend.rinse_at_vendor_module import _load_active_at_vendor_presence_by_bag

    org = int(organization_id)
    batch_id = crawl_batch_id if crawl_batch_id is not None else get_latest_successful_crawl_batch_id(cursor, org)
    av = build_at_vendor_module(
        cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
    )
    live = _load_active_at_vendor_presence_by_bag(cursor, org)
    rush_pending: list[str] = []
    other_pending: list[str] = []
    on_portal_map: dict[str, bool] = {}
    for row in av.get("rows") or []:
        if row.get("at_vendor_status") != AV_STATUS_PENDING:
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        on_portal_map[bid] = bid in live
        if batch_id and bag_in_portal_crawl_batch(cursor, org, batch_id, bid):
            continue
        if row.get("rush_bucket") == AV_RUSH:
            rush_pending.append(bid)
        elif not rush_only:
            other_pending.append(bid)
    return sorted(rush_pending) + sorted(other_pending), batch_id, on_portal_map


def resolve_off_portal_pending_bag_ids(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    rush_only: bool = False,
) -> list[str]:
    from backend.rinse_at_vendor_module import _load_active_at_vendor_presence_by_bag

    av = build_at_vendor_module(
        cursor,
        int(organization_id),
        selected_date_et=selected_date_et,
        baseline_ctx=baseline_ctx,
    )
    live = _load_active_at_vendor_presence_by_bag(cursor, int(organization_id))
    rush_pending: list[str] = []
    other_pending: list[str] = []
    for row in av.get("rows") or []:
        if row.get("at_vendor_status") != AV_STATUS_PENDING:
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid or bid in live:
            continue
        if row.get("rush_bucket") == AV_RUSH:
            rush_pending.append(bid)
        elif not rush_only:
            other_pending.append(bid)
    return sorted(rush_pending) + sorted(other_pending)


def refresh_off_portal_pending_scans(
    cursor,
    organization_id: int,
    *,
    upload_batch_id: int | None,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    bag_ids: list[str] | None = None,
    dry_run: bool | None = None,
    max_bags: int | None = None,
    rush_only: bool | None = None,
    target_scope: str = "off_portal",
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Direct ?q=BAGID refresh. target_scope=not_in_latest_crawl includes on-portal pending bags missing from crawl."""
    from backend.rinse_bag_registry import merge_scan_events_from_upload

    org = int(organization_id)
    dry = off_portal_refresh_dry_run() if dry_run is None else bool(dry_run)
    limit = off_portal_refresh_max_bags() if max_bags is None else max(1, int(max_bags))
    rush_filter = off_portal_refresh_rush_only() if rush_only is None else bool(rush_only)

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    targets = list(bag_ids or [])
    crawl_batch_id: int | None = None
    on_portal_map: dict[str, bool] = {}
    if not targets:
        if target_scope == "not_in_latest_crawl":
            targets, crawl_batch_id, on_portal_map = resolve_pending_not_in_latest_crawl_bag_ids(
                cursor,
                org,
                selected_date_et=selected_date_et,
                baseline_ctx=baseline_ctx,
                rush_only=rush_filter,
                crawl_batch_id=int(upload_batch_id) if upload_batch_id else None,
            )
        else:
            targets = resolve_off_portal_pending_bag_ids(
                cursor,
                org,
                selected_date_et=selected_date_et,
                baseline_ctx=baseline_ctx,
                rush_only=rush_filter,
            )
    targets = targets[:limit]

    from backend.rinse_bag_operational_owner import filter_bag_ids_for_operational_write

    allowed_targets, owner_rejected = filter_bag_ids_for_operational_write(
        cursor, org, targets, context="off_portal_refresh", assign_on_first=False
    )
    targets = sorted(allowed_targets)

    if not targets:
        return {
            "dry_run": dry,
            "target_scope": target_scope,
            "crawl_batch_id": crawl_batch_id,
            "bag_ids_requested": [],
            "bags_processed": 0,
            "events_inserted": 0,
            "events_already_present": 0,
            "events_skipped_no_time": 0,
            "lookup_failed": 0,
            "lookup_failed_bag_ids": [],
            "operational_owner_rejected": owner_rejected,
            "bags": [],
        }

    portal = run_targeted_portal_scrape(targets, organization_id=org)
    portal_by_bag = {
        str(b.get("bag_id") or "").strip().upper(): b for b in portal.get("bags") or [] if b.get("bag_id")
    }

    av = build_at_vendor_module(
        cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
    )
    rows_by_bag = {str(r.get("bag_id") or "").upper(): r for r in av.get("rows") or []}

    if not on_portal_map:
        from backend.rinse_at_vendor_module import _load_active_at_vendor_presence_by_bag

        live = _load_active_at_vendor_presence_by_bag(cursor, org)
        on_portal_map = {bid: bid in live for bid in targets}
    if crawl_batch_id is None:
        crawl_batch_id = int(upload_batch_id) if upload_batch_id else get_latest_successful_crawl_batch_id(cursor, org)

    total_inserted = 0
    total_present = 0
    total_skipped = 0
    lookup_failed = 0
    lookup_failed_bag_ids: list[str] = []
    bag_reports: list[dict[str, Any]] = []
    any_imported = False

    for bid in targets:
        module_row = rows_by_bag.get(bid) or {}
        on_portal = bool(on_portal_map.get(bid))
        in_latest_crawl = (
            bool(crawl_batch_id and bag_in_portal_crawl_batch(cursor, org, int(crawl_batch_id), bid))
        )
        payload = portal_by_bag.get(bid) or {"bag_id": bid, "found": False, "scans": []}
        if not payload.get("found"):
            lookup_failed += 1
            lookup_failed_bag_ids.append(bid)
            bag_reports.append(
                {
                    "bag_id": bid,
                    "lookup_ok": False,
                    "direct_lookup_success": False,
                    "on_current_portal_crawl": on_portal,
                    "in_latest_portal_crawl_batch": in_latest_crawl,
                    "status_before": module_row.get("at_vendor_status"),
                    "pending_why_before": module_row.get("pending_why_label"),
                    "missing_scans_imported": 0,
                    "error": payload.get("error"),
                }
            )
            _log(f"targeted refresh skip {bid}: direct lookup failed")
            continue
        classified = classify_portal_rows_against_db(cursor, org, bid, payload.get("scans") or [])
        missing_rows = classified["missing_rows"]
        compare = compare_bag_portal_vs_db(
            cursor,
            org,
            bid,
            selected_date_et=selected_date_et,
            portal_payload=payload,
            module_row=rows_by_bag.get(bid),
        )
        merge_result: dict[str, Any] = {}
        imported_count = 0
        if missing_rows and not dry and upload_batch_id is not None:
            df = pd.DataFrame(missing_rows, columns=SCAN_EVENTS_CSV_COLUMNS)
            df["scanned_at_parsed"] = df["Time Scanned"].map(_parse_scanned_at)
            source_name = f"targeted-direct-{bid.lower()}.csv"
            commit_scan_events_for_batch(
                cursor,
                org,
                int(upload_batch_id),
                df,
                source_name,
                replace_existing=False,
            )
            merge_result = merge_scan_events_from_upload(
                cursor,
                org,
                int(upload_batch_id),
                df,
                source_name,
            )
            imported_count = int(merge_result.get("events_inserted") or 0)
            any_imported = any_imported or imported_count > 0
            total_inserted += imported_count
            total_present += int(merge_result.get("events_already_present") or 0)
            total_skipped += int(merge_result.get("events_skipped_no_time") or 0)
        else:
            total_present += classified["already_present_count"]
            total_skipped += classified["skipped_no_time"]

        bag_reports.append(
            {
                "bag_id": bid,
                "lookup_ok": True,
                "direct_lookup_success": True,
                "on_current_portal_crawl": on_portal,
                "in_latest_portal_crawl_batch": in_latest_crawl,
                "missing_row_count": classified["missing_row_count"],
                "missing_scans_imported": imported_count,
                "would_complete": compare.get("would_complete"),
                "status_before": module_row.get("at_vendor_status") or compare.get("status_before"),
                "pending_why_before": module_row.get("pending_why_label"),
                "expected_status_after_import": compare.get("expected_status_after_import"),
                "merge": merge_result,
                **compare,
            }
        )
        _log(
            f"targeted refresh {bid}: missing={classified['missing_row_count']} "
            f"imported={imported_count} would_complete={compare.get('would_complete')} dry_run={dry}"
        )

    if any_imported and not dry:
        av_after = build_at_vendor_module(
            cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
        )
        rows_after = {str(r.get("bag_id") or "").upper(): r for r in av_after.get("rows") or []}
        for bag in bag_reports:
            bid = str(bag.get("bag_id") or "").upper()
            row_after = rows_after.get(bid) or {}
            status_after = row_after.get("at_vendor_status")
            bag["status_after"] = status_after
            bag["pending_why_after"] = row_after.get("pending_why_label")
            if status_after == AV_STATUS_PENDING:
                bag["reason_still_pending"] = row_after.get("pending_why_label") or "Pending after targeted refresh"
            elif status_after == AV_STATUS_COMPLETED:
                bag["reason_still_pending"] = None
            else:
                bag["reason_still_pending"] = row_after.get("pending_why_label")
    else:
        for bag in bag_reports:
            if not bag.get("lookup_ok"):
                continue
            expected = bag.get("expected_status_after_import")
            bag["status_after"] = expected if dry or not any_imported else bag.get("status_before")
            if expected == AV_STATUS_PENDING:
                bag["reason_still_pending"] = bag.get("pending_why_before") or "Pending — no new scans imported"
            elif expected == AV_STATUS_COMPLETED:
                bag["reason_still_pending"] = None

    return {
        "dry_run": dry,
        "target_scope": target_scope,
        "upload_batch_id": upload_batch_id,
        "crawl_batch_id": crawl_batch_id,
        "selected_date_et": selected_date_et.isoformat(),
        "bag_ids_requested": targets,
        "bags_processed": len([b for b in bag_reports if b.get("lookup_ok")]),
        "events_inserted": total_inserted,
        "events_already_present": total_present,
        "events_skipped_no_time": total_skipped,
        "lookup_failed": lookup_failed,
        "lookup_failed_bag_ids": lookup_failed_bag_ids,
        "bags": bag_reports,
    }


def refresh_pending_workload_scans_via_direct_lookup(
    cursor,
    organization_id: int,
    *,
    upload_batch_id: int | None,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    bag_ids: list[str] | None = None,
    dry_run: bool = False,
    max_bags: int | None = None,
    rush_only: bool = False,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Targeted ?q=BAGID refresh for pending workload bags not in the latest portal crawl."""
    return refresh_off_portal_pending_scans(
        cursor,
        organization_id,
        upload_batch_id=upload_batch_id,
        selected_date_et=selected_date_et,
        baseline_ctx=baseline_ctx,
        bag_ids=bag_ids,
        dry_run=dry_run,
        max_bags=max_bags,
        rush_only=rush_only,
        target_scope="not_in_latest_crawl",
        log_fn=log_fn,
    )
