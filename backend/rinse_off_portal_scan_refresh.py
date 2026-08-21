"""Targeted scan refresh for off-portal Today's Workload Pending bags via direct ?q=BAGID lookup."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
    return _env_flag("RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED", default=True)


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


def off_portal_refresh_scheduled_timeout_sec() -> int:
    """Shorter cap for targeted refresh during scheduled scrape (non-blocking)."""
    try:
        return max(60, int(os.getenv("RINSE_OFF_PORTAL_SCAN_REFRESH_SCHEDULED_TIMEOUT_SEC", "300") or 300))
    except (TypeError, ValueError):
        return 300


def off_portal_refresh_chunk_size() -> int:
    try:
        return max(1, int(os.getenv("RINSE_OFF_PORTAL_SCAN_REFRESH_CHUNK_SIZE", "8") or 8))
    except (TypeError, ValueError):
        return 8


def off_portal_refresh_rush_only() -> bool:
    return _env_flag("RINSE_OFF_PORTAL_SCAN_REFRESH_RUSH_ONLY", default=False)


def build_targeted_refresh_sync_summary(
    detail: dict[str, Any] | None,
    *,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    """Normalize targeted refresh result for scrape metadata / sync status UI."""
    empty = {
        "targeted_refresh_ran": False,
        "targeted_bags_considered": 0,
        "targeted_bags_refreshed": 0,
        "missing_scans_imported": 0,
        "bags_completed_after_refresh": 0,
        "lookup_failures": 0,
    }
    if skipped_reason:
        return {**empty, "skipped_reason": skipped_reason}
    if not detail:
        return {**empty, "skipped_reason": "not_run"}
    if detail.get("error"):
        return {
            **empty,
            **{k: detail.get(k) for k in ("dry_run", "target_scope", "crawl_batch_id") if k in detail},
            "error": detail.get("error"),
            "targeted_refresh_ran": False,
        }

    bags = detail.get("bags") or []
    completed_after = sum(
        1
        for b in bags
        if b.get("status_before") == AV_STATUS_PENDING and b.get("status_after") == AV_STATUS_COMPLETED
    )
    dry = bool(detail.get("dry_run"))
    out = dict(detail)
    out.update(
        {
            "targeted_refresh_ran": not dry and not detail.get("error"),
            "targeted_bags_considered": len(detail.get("bag_ids_requested") or []),
            "targeted_bags_refreshed": int(detail.get("bags_processed") or 0),
            "missing_scans_imported": int(detail.get("events_inserted") or 0),
            "bags_completed_after_refresh": completed_after,
            "lookup_failures": int(detail.get("lookup_failed") or 0),
        }
    )
    if dry:
        out["targeted_refresh_ran"] = False
        out["skipped_reason"] = "dry_run"
    return out


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
    weight = ev.get("weight")
    if weight is None or weight == "":
        weight = ev.get("Weight")
    weight_source = ev.get("weight_source") or ev.get("Weight Source") or ""
    weight_role = ev.get("weight_role") or ev.get("Weight Role") or ""
    return {
        "Bag ID": bag_id,
        "Scan Index": str(ev.get("scan_index") or ""),
        "Rack": str(ev.get("rack") or ""),
        "Time Scanned": str(ev.get("time_scanned") or ""),
        "User": str(ev.get("user") or ""),
        "Purpose": purpose,
        "Last Location": str(ev.get("last_location") or ""),
        "Last Scan": str(ev.get("last_scan") or ""),
        "Weight": "" if weight is None or weight == "" else str(weight),
        "Weight Source": str(weight_source or ""),
        "Weight Role": str(weight_role or ""),
    }


def portal_scans_to_events_df(bag_id: str, scans: list[dict[str, Any]]) -> pd.DataFrame:
    from backend.rinse_scan_events_logic import SCAN_EVENT_WEIGHT_COLUMNS

    cols = list(SCAN_EVENTS_CSV_COLUMNS) + [
        c for c in SCAN_EVENT_WEIGHT_COLUMNS if c not in SCAN_EVENTS_CSV_COLUMNS
    ]
    rows = [portal_event_to_csv_row(bag_id, ev) for ev in scans]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols]
    df["scanned_at_parsed"] = df["Time Scanned"].map(_parse_scanned_at)
    return df


_AUTHORITATIVE_WEIGHT_SOURCES = frozenset(
    {
        "rinse_preclean_info",
        "rinse_postclean_info",
        "rinse_workitem_wf_lbs",
    }
)


def enrich_authoritative_weights_on_existing_events(
    cursor,
    organization_id: int,
    bag_id: str,
    scans: list[dict[str, Any]],
    *,
    source_upload_batch_id: int | None = None,
) -> dict[str, Any]:
    """Update existing weigh-entry rows with authoritative DOM Weight when present.

    Does not insert duplicate events — matches by content key / purpose+time+user.
    """
    from backend.rinse_bag_registry import upsert_scan_event_row
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

    org = int(organization_id)
    bid = str(bag_id or "").strip().upper()
    updated = 0
    skipped = 0
    for ev in scans or []:
        purpose = str(ev.get("purpose") or "")
        if not is_weight_entry_purpose(purpose):
            continue
        lbs = normalize_scan_weight_lbs(ev.get("weight"), allow_unit_suffix=True)
        src = str(ev.get("weight_source") or "").strip()
        role = str(ev.get("weight_role") or "").strip() or None
        if lbs is None or src not in _AUTHORITATIVE_WEIGHT_SOURCES:
            skipped += 1
            continue
        time_raw = str(ev.get("time_scanned") or "").strip()
        if not time_raw:
            skipped += 1
            continue
        scanned = _parse_scanned_at(time_raw)
        user_name = str(ev.get("user") or "")[:255] or None
        rack = str(ev.get("rack") or "")[:128] or None
        last_loc = str(ev.get("last_location") or "")[:8] or None
        last_scan = str(ev.get("last_scan") or "")[:8] or None
        try:
            scan_index = int(float(str(ev.get("scan_index") or "").strip())) if str(ev.get("scan_index") or "").strip() else None
        except (TypeError, ValueError):
            scan_index = None
        try:
            dk = compute_scan_event_dedupe_key(
                organization_id=org,
                bag_id=bid,
                rack=rack,
                user_name=user_name,
                purpose=purpose if "Last Scan" in purpose or not last_scan else (
                    f"{purpose} Last Scan" if last_scan == "Y" and "Last Scan" not in purpose else purpose
                ),
                time_scanned_raw=time_raw[:255],
                scanned_at_parsed=scanned,
                last_location=last_loc,
            )
        except ValueError:
            skipped += 1
            continue
        raw = {
            "Bag ID": bid,
            "Purpose": purpose,
            "Time Scanned": time_raw,
            "User": user_name or "",
            "Rack": rack or "",
            "Weight": lbs,
            "Weight Source": src,
            "Weight Role": role or "",
        }
        action = upsert_scan_event_row(
            cursor,
            organization_id=org,
            bag_id=bid,
            dedupe_key=dk,
            scan_index=scan_index,
            rack=rack,
            time_scanned_raw=time_raw[:255],
            scanned_at_parsed=scanned,
            user_name=user_name,
            purpose=purpose[:255] if purpose else None,
            last_location=last_loc,
            last_scan=last_scan,
            source_upload_batch_id=int(source_upload_batch_id or 0) or 0,
            source_filename="targeted-authoritative-weight-enrichment",
            raw_json=json.dumps(raw),
            credential_sourced=True,
            weight_lbs=float(lbs),
            weight_source=src,
            weight_role=role,
            overwrite_weight=True,
        )
        if action in ("metadata_updated", "inserted"):
            updated += 1
        else:
            skipped += 1
    return {"updated": updated, "skipped": skipped}

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
    chunk_size: int | None = None,
) -> dict[str, Any]:
    ids = sorted({str(b or "").strip().upper() for b in bag_ids if str(b or "").strip()})
    if not ids:
        return {"bags": [], "lookup_failed_bag_ids": [], "timed_out_bag_ids": []}
    if not TARGETED_SCRAPE_SCRIPT.is_file():
        raise RuntimeError(f"Missing targeted scrape script: {TARGETED_SCRAPE_SCRIPT}")

    env = {**dict(os.environ)}
    if organization_id is not None:
        env.update(_scraper_env_for_org(organization_id))

    total_timeout = timeout_sec if timeout_sec is not None else off_portal_refresh_timeout_sec()
    chunk_n = chunk_size if chunk_size is not None else off_portal_refresh_chunk_size()
    chunks: list[list[str]] = [ids[i : i + chunk_n] for i in range(0, len(ids), chunk_n)]
    per_chunk_timeout = max(60, total_timeout // max(1, len(chunks)))

    all_bags: list[dict[str, Any]] = []
    lookup_failed_bag_ids: list[str] = []
    timed_out_bag_ids: list[str] = []

    for chunk in chunks:
        try:
            proc = subprocess.run(
                ["node", str(TARGETED_SCRAPE_SCRIPT), *chunk],
                cwd=str(TARGETED_SCRAPE_SCRIPT.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=per_chunk_timeout,
            )
        except subprocess.TimeoutExpired:
            timed_out_bag_ids.extend(chunk)
            lookup_failed_bag_ids.extend(chunk)
            continue
        if proc.returncode != 0:
            lookup_failed_bag_ids.extend(chunk)
            continue
        raw = proc.stdout.strip()
        start = raw.find("{")
        if start < 0:
            lookup_failed_bag_ids.extend(chunk)
            continue
        try:
            payload = json.loads(raw[start:])
        except json.JSONDecodeError:
            lookup_failed_bag_ids.extend(chunk)
            continue
        chunk_bags = payload.get("bags") if isinstance(payload, dict) else None
        if not isinstance(chunk_bags, list):
            lookup_failed_bag_ids.extend(chunk)
            continue
        for bag in chunk_bags:
            if isinstance(bag, dict):
                all_bags.append(bag)
                bid = str(bag.get("bag_id") or "").strip().upper()
                if bid and not bag.get("found", True) and bag.get("scans") in (None, []):
                    if bid not in lookup_failed_bag_ids:
                        lookup_failed_bag_ids.append(bid)

    return {
        "bags": all_bags,
        "lookup_failed_bag_ids": sorted(set(lookup_failed_bag_ids)),
        "timed_out_bag_ids": sorted(set(timed_out_bag_ids)),
        "chunks_processed": len(chunks),
        "per_chunk_timeout_sec": per_chunk_timeout,
    }


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
            rack=row.get("Rack"),
            user_name=row.get("User"),
            purpose=row.get("Purpose"),
            time_scanned_raw=time_raw,
            scanned_at_parsed=_parse_scanned_at(time_raw),
            last_location=row.get("Last Location"),
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


def _pending_row_has_complete_cleaning(
    events: Sequence[Mapping[str, Any]] | None,
) -> bool:
    from backend.rinse_scan_purpose import is_complete_cleaning_purpose

    for ev in events or []:
        if is_complete_cleaning_purpose(ev.get("purpose")):
            return True
    return False


def resolve_pending_near_complete_bag_ids(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    baseline_ctx: dict[str, Any] | None = None,
    rush_only: bool = False,
    av_module: dict[str, Any] | None = None,
) -> list[str]:
    """
    Pending WF bags that already have complete-cleaning locally but no post-weight.

    These often remain "in latest crawl" after Events CSV lags behind the portal
    detail page (post weight-entry finished but scheduled scrape hasn't caught up).
    """
    from backend.rinse_at_vendor_module import _load_at_vendor_scan_events_for_bags

    org = int(organization_id)
    av = av_module or build_at_vendor_module(
        cursor, org, selected_date_et=selected_date_et, baseline_ctx=baseline_ctx
    )
    candidates: list[str] = []
    for row in av.get("rows") or []:
        if row.get("at_vendor_status") != AV_STATUS_PENDING:
            continue
        if str(row.get("service_type") or row.get("service_bucket") or "").upper() != "WF":
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if rush_only and row.get("rush_bucket") != AV_RUSH:
            continue
        candidates.append(bid)
    if not candidates or not hasattr(cursor, "execute"):
        return []

    events_by_bag = _load_at_vendor_scan_events_for_bags(cursor, org, candidates)
    near_complete: list[str] = []
    for bid in candidates:
        if _pending_row_has_complete_cleaning(events_by_bag.get(bid)):
            near_complete.append(bid)
    return near_complete


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

    # Also refresh pending WF bags that already folded locally but still lack
    # post-weight — even when the bag remains on the latest portal crawl list.
    near_complete = resolve_pending_near_complete_bag_ids(
        cursor,
        org,
        selected_date_et=selected_date_et,
        baseline_ctx=baseline_ctx,
        rush_only=rush_only,
        av_module=av,
    )
    for bid in near_complete:
        on_portal_map.setdefault(bid, bid in live)
        if bid in rush_pending or bid in other_pending:
            continue
        # Prefer rush ordering: look up rush from av rows.
        row = next(
            (
                r
                for r in (av.get("rows") or [])
                if str(r.get("bag_id") or "").strip().upper() == bid
            ),
            None,
        )
        if row and row.get("rush_bucket") == AV_RUSH:
            rush_pending.append(bid)
        elif not rush_only:
            other_pending.append(bid)

    return sorted(set(rush_pending)) + sorted(set(other_pending) - set(rush_pending)), batch_id, on_portal_map


def resolve_day_membership_chronology_refresh_bag_ids(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    max_bags: int | None = None,
) -> list[str]:
    """Day-bag membership that left At Vendor but may still gain chronology.

    Narrow continuity: once on the business-day workload, keep refreshing via
    ``?q=`` until we have garments-reviewed + post weigh-entry (or delivery-prep /
    load-out), without crawling every historical bag.
    """
    from backend.rinse_at_vendor_module import _load_active_at_vendor_presence_by_bag
    from backend.rinse_scan_purpose import is_complete_cleaning_purpose

    org = int(organization_id)
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return []
    live = _load_active_at_vendor_presence_by_bag(cursor, org)
    cursor.execute(
        """
        SELECT bag_id, effective_status, post_weight_lbs,
               JSON_UNQUOTE(JSON_EXTRACT(bag_snapshot_json, '$.disappearance_state')) AS dis
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'WF'
        ORDER BY bag_id
        """,
        (org, selected_date_et),
    )
    candidates: list[str] = []
    for row in cursor.fetchall() or []:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid or bid in live:
            continue
        # Still need chronology if missing POST or disappeared without completion.
        needs = (
            row.get("post_weight_lbs") is None
            or "DISAPPEAR" in str(row.get("dis") or "").upper()
            or str(row.get("effective_status") or "") in ("review_required", "pending", "")
        )
        if not needs:
            continue
        # Skip only when DB already has post-cycle weigh-entry after complete-cleaning.
        cursor.execute(
            """
            SELECT purpose, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND UPPER(TRIM(bag_id)) = %s
            ORDER BY scanned_at_parsed, id
            """,
            (org, bid),
        )
        events = cursor.fetchall() or []
        has_complete = any(is_complete_cleaning_purpose(e.get("purpose")) for e in events)
        we_after_complete = False
        complete_ts = None
        for e in events:
            if is_complete_cleaning_purpose(e.get("purpose")) and e.get("scanned_at_parsed"):
                complete_ts = e["scanned_at_parsed"]
        if complete_ts is not None:
            for e in events:
                if is_weight_entry_purpose(e.get("purpose")) and e.get("scanned_at_parsed"):
                    if e["scanned_at_parsed"] > complete_ts:
                        we_after_complete = True
                        break
        if has_complete and we_after_complete and row.get("post_weight_lbs") is not None:
            continue
        candidates.append(bid)
    limit = max_bags if max_bags is not None else off_portal_refresh_max_bags()
    return candidates[: max(1, int(limit))]


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
    timeout_sec: int | None = None,
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
        elif target_scope == "day_membership_chronology":
            targets = resolve_day_membership_chronology_refresh_bag_ids(
                cursor,
                org,
                selected_date_et=selected_date_et,
                max_bags=limit,
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

    portal = run_targeted_portal_scrape(
        targets, organization_id=org, timeout_sec=timeout_sec
    )
    portal_by_bag = {
        str(b.get("bag_id") or "").strip().upper(): b for b in portal.get("bags") or [] if b.get("bag_id")
    }
    lookup_failed_bag_ids = sorted(set(portal.get("lookup_failed_bag_ids") or []))
    timed_out_bag_ids = sorted(set(portal.get("timed_out_bag_ids") or []))
    scrape_failed_set = set(lookup_failed_bag_ids)

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
    lookup_failed = len(lookup_failed_bag_ids)
    bag_reports: list[dict[str, Any]] = []
    any_imported = False

    for bid in targets:
        if bid in scrape_failed_set:
            bag_reports.append(
                {
                    "bag_id": bid,
                    "lookup_ok": False,
                    "direct_lookup_success": False,
                    "status_before": rows_by_bag.get(bid, {}).get("at_vendor_status"),
                    "missing_scans_imported": 0,
                    "error": "timeout" if bid in timed_out_bag_ids else "targeted_scrape_failed",
                }
            )
            _log(
                f"targeted refresh skip {bid}: "
                f"{'timeout' if bid in timed_out_bag_ids else 'direct lookup failed'}"
            )
            continue
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
        weight_enrich: dict[str, Any] = {"updated": 0, "skipped": 0}
        if missing_rows and not dry and upload_batch_id is not None:
            from backend.rinse_scan_events_logic import SCAN_EVENT_WEIGHT_COLUMNS

            cols = list(SCAN_EVENTS_CSV_COLUMNS) + [
                c for c in SCAN_EVENT_WEIGHT_COLUMNS if c not in SCAN_EVENTS_CSV_COLUMNS
            ]
            df = pd.DataFrame(missing_rows)
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            df = df[cols]
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
                replace_existing=False,
            )
            imported_count = int(merge_result.get("events_inserted") or 0)
            any_imported = any_imported or imported_count > 0
            total_inserted += imported_count
            total_present += int(merge_result.get("events_already_present") or 0)
            total_skipped += int(merge_result.get("events_skipped_no_time") or 0)
        else:
            total_present += classified["already_present_count"]
            total_skipped += classified["skipped_no_time"]

        if not dry:
            weight_enrich = enrich_authoritative_weights_on_existing_events(
                cursor,
                org,
                bid,
                payload.get("scans") or [],
                source_upload_batch_id=upload_batch_id,
            )

        bag_reports.append(
            {
                "bag_id": bid,
                "lookup_ok": True,
                "direct_lookup_success": True,
                "on_current_portal_crawl": on_portal,
                "in_latest_portal_crawl_batch": in_latest_crawl,
                "missing_row_count": classified["missing_row_count"],
                "missing_scans_imported": imported_count,
                "authoritative_weight_enriched": weight_enrich.get("updated") or 0,
                "would_complete": compare.get("would_complete"),
                "status_before": module_row.get("at_vendor_status") or compare.get("status_before"),
                "pending_why_before": module_row.get("pending_why_label"),
                "expected_status_after_import": compare.get("expected_status_after_import"),
                "merge": merge_result,
                "weight_enrich": weight_enrich,
                "pre_clean_weight_lbs": payload.get("pre_clean_weight_lbs"),
                "post_weight_lbs": payload.get("post_weight_lbs"),
                "workitem_wf_lbs": payload.get("workitem_wf_lbs"),
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
        "timed_out_bag_ids": timed_out_bag_ids,
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
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Targeted ?q=BAGID refresh for pending / day-membership bags needing chronology.

    Includes bags that left At Vendor but remain on the business-day workload so
    later weigh-entry / completion events are still captured (Emery gap).
    """
    limit = off_portal_refresh_max_bags() if max_bags is None else max(1, int(max_bags))
    if bag_ids is not None:
        targets = list(bag_ids)
    else:
        pending, _crawl, _on_portal = resolve_pending_not_in_latest_crawl_bag_ids(
            cursor,
            int(organization_id),
            selected_date_et=selected_date_et,
            baseline_ctx=baseline_ctx,
            rush_only=rush_only,
            crawl_batch_id=int(upload_batch_id) if upload_batch_id else None,
        )
        continuity = resolve_day_membership_chronology_refresh_bag_ids(
            cursor,
            int(organization_id),
            selected_date_et=selected_date_et,
            max_bags=limit,
        )
        seen: set[str] = set()
        targets = []
        for bid in list(pending) + list(continuity):
            b = str(bid or "").strip().upper()
            if not b or b in seen:
                continue
            seen.add(b)
            targets.append(b)
            if len(targets) >= limit:
                break
        if log_fn:
            log_fn(
                f"targeted refresh candidates: pending_not_in_crawl={len(pending)} "
                f"day_membership_continuity={len(continuity)} selected={len(targets)}"
            )
    return refresh_off_portal_pending_scans(
        cursor,
        organization_id,
        upload_batch_id=upload_batch_id,
        selected_date_et=selected_date_et,
        baseline_ctx=baseline_ctx,
        bag_ids=targets,
        dry_run=dry_run,
        max_bags=limit,
        rush_only=rush_only,
        target_scope="not_in_latest_crawl+day_membership_chronology",
        log_fn=log_fn,
        timeout_sec=timeout_sec,
    )
