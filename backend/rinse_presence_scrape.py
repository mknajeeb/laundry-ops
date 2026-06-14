"""
Run Ready for Vendor / at_vendor portal presence scrapes (presence table only).

Used by manual admin API, Shift Monitor refresh, and scheduled Rinse sync step 2.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from backend.rinse_bag_export_runner import export_enabled, run_bag_export_csv
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    apply_presence_scrape,
    build_presence_scrape_debug,
    build_tickets_url_for_portal_status,
    ensure_presence_tables,
    parse_presence_rows_from_portal_csv,
    read_portal_scrape_meta,
    record_presence_scrape_run,
)
from backend.rinse_current_facility_snapshot import extract_vendor_home_summary_from_scrape_meta
from backend.rinse_portal_scrape_meta import validate_presence_empty_result
from backend.rinse_vendor_config import rinse_scrape_env_for_organization
from backend.tenant_feature_flags import is_feature_enabled


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def presence_phase_timeout_sec() -> int:
    """Per-phase cap for combined-sync presence scrapes (browser launch through CSV write)."""
    try:
        return max(60, min(7200, int(os.getenv("RINSE_PRESENCE_PHASE_TIMEOUT_SEC", "900"))))
    except (TypeError, ValueError):
        return 900


@dataclass
class PresenceScrapeResult:
    organization_id: int
    portal_status: str
    status: str = "failed"
    skipped_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    scrape_debug: dict[str, Any] = field(default_factory=dict)
    rinse_vendor: str | None = None
    source_url: str | None = None

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.finished_at:
            return max(0, int((self.finished_at - self.started_at).total_seconds()))
        return None


def ready_for_vendor_scrape_enabled(cursor, organization_id: int) -> bool:
    return is_feature_enabled(cursor, int(organization_id), "enable_ready_for_vendor_scrape")


def _resolve_max_pages(extra_env: dict[str, str], override: str | None) -> str:
    if override and str(override).strip():
        return str(override).strip()
    raw = (extra_env.get("RINSE_MAX_PAGES") or "").strip()
    if raw:
        return raw
    return "500"


def run_presence_scrape_for_org(
    conn,
    organization_id: int,
    *,
    portal_status: str = PORTAL_STATUS_READY,
    dry_run: bool = False,
    mark_missing: bool = False,
    run_type: str = "scheduled",
    organization_slug: str | None = None,
    organization_name: str | None = None,
    rinse_vendor: str | None = None,
    max_pages: str | None = None,
    log_write: Callable[[str], None] | None = None,
) -> PresenceScrapeResult:
    """
    Scrape portal CSV and upsert rinse_cleaner_ticket_presence only.
    Does not touch orders_staging, checkout, or registry completion.
    """
    org = int(organization_id)
    result = PresenceScrapeResult(
        organization_id=org,
        portal_status=str(portal_status or PORTAL_STATUS_READY).strip(),
        started_at=_utcnow(),
    )
    cursor = conn.cursor(dictionary=True)
    batch_id = f"{run_type}-{uuid.uuid4().hex}"
    source_url: str | None = None

    def _log(msg: str) -> None:
        if log_write:
            log_write(msg)

    def _persist_failed_run(
        *,
        error_message: str,
        scrape_meta: dict[str, Any] | None = None,
    ) -> None:
        if dry_run or result.status == "disabled":
            return
        ensure_presence_tables(cursor)
        record_presence_scrape_run(
            cursor,
            org,
            portal_status=result.portal_status,
            source_batch_id=batch_id,
            source_url=source_url,
            run_type=run_type,
            status="failed",
            started_at=result.started_at,
            finished_at=result.finished_at or _utcnow(),
            errors=[error_message],
            scrape_meta=scrape_meta,
        )
        conn.commit()

    if portal_status == PORTAL_STATUS_READY and not ready_for_vendor_scrape_enabled(cursor, org):
        result.status = "disabled"
        result.skipped_reason = "enable_ready_for_vendor_scrape=false"
        result.finished_at = _utcnow()
        return result

    if not export_enabled():
        result.status = "failed"
        result.error_message = "Rinse scrape disabled (RINSE_BAG_EXPORT_ENABLED not set)"
        result.finished_at = _utcnow()
        _persist_failed_run(error_message=result.error_message)
        return result

    vendor, vendor_env = rinse_scrape_env_for_organization(
        org,
        organization_slug=organization_slug,
        organization_name=organization_name,
        override_vendor=rinse_vendor,
    )
    result.rinse_vendor = vendor
    base_url = vendor_env.get("RINSE_TICKETS_URL") or ""
    source_url = build_tickets_url_for_portal_status(base_url, result.portal_status)
    result.source_url = source_url

    extra_env = dict(vendor_env)
    extra_env["RINSE_TICKETS_URL"] = source_url
    extra_env["RINSE_CSV_LAYOUT"] = "portal"
    extra_env["RINSE_ALLOW_EMPTY_EXPORT"] = "1"
    extra_env["RINSE_MAX_PAGES"] = _resolve_max_pages(extra_env, max_pages)
    extra_env.setdefault("RINSE_PAGE_SETTLE_MS", "2000")
    extra_env.setdefault("RINSE_TABLE_WAIT_MS", "800")

    _log(
        f"Presence scrape org={org} status={result.portal_status} vendor={vendor} "
        f"max_pages={extra_env['RINSE_MAX_PAGES']}\n"
    )

    try:
        with tempfile.TemporaryDirectory(prefix="rinse-presence-") as tmp:
            csv_path = Path(tmp) / f"presence-{result.portal_status}.csv"
            meta_path = Path(str(csv_path) + ".meta.json")
            extra_env["OUTPUT_PORTAL_SCRAPE_META"] = str(meta_path)
            phase_timeout = presence_phase_timeout_sec()
            code, stdout, stderr = run_bag_export_csv(
                csv_path,
                extra_env=extra_env,
                timeout_sec=phase_timeout,
            )
            if code != 0:
                result.status = "failed"
                result.error_message = (
                    "Scrape subprocess failed"
                    if code != -1
                    else f"Scrape timed out after {phase_timeout}s"
                )
                scrape_meta = read_portal_scrape_meta(str(meta_path))
                result.scrape_debug = build_presence_scrape_debug(
                    portal_status=result.portal_status,
                    source_url=source_url,
                    rows=[],
                    scrape_meta=scrape_meta,
                    exit_code=code,
                )
                if stderr:
                    _log(stderr[-2000:] + "\n")
                result.finished_at = _utcnow()
                _persist_failed_run(error_message=result.error_message, scrape_meta=scrape_meta)
                return result

            rows = parse_presence_rows_from_portal_csv(str(csv_path))
            scrape_meta = read_portal_scrape_meta(str(meta_path))
            if (
                result.portal_status == PORTAL_STATUS_AT_VENDOR
                and not extract_vendor_home_summary_from_scrape_meta(scrape_meta)
            ):
                from backend.rinse_bag_export_runner import run_vendor_home_summary_scrape

                vendor_home = run_vendor_home_summary_scrape(extra_env)
                if vendor_home:
                    scrape_meta = {**(scrape_meta or {}), "vendor_home_summary": vendor_home}
                    _log(
                        "Vendor Home summary supplement: "
                        f"at={vendor_home.get('orders_at_veewash')} "
                        f"ytp={vendor_home.get('orders_at_veewash_yet_to_process')}\n"
                    )
            scrape_debug = build_presence_scrape_debug(
                portal_status=result.portal_status,
                source_url=source_url,
                rows=rows,
                scrape_meta=scrape_meta,
                exit_code=code,
            )
            result.scrape_debug = scrape_debug

            empty_validated = False
            empty_checks: dict[str, bool] = {}
            if len(rows) == 0:
                empty_validated, empty_checks = validate_presence_empty_result(
                    scrape_meta,
                    exit_code=code,
                    parsed_row_count=len(rows),
                )
                scrape_debug["empty_result_validated"] = empty_validated
                scrape_debug["empty_result_checks"] = empty_checks
                if mark_missing and not empty_validated:
                    result.status = "failed"
                    result.error_message = (
                        "Zero-row presence scrape not validated — preserving existing active population"
                    )
                    result.finished_at = _utcnow()
                    _persist_failed_run(
                        error_message=result.error_message,
                        scrape_meta={
                            **(scrape_meta or {}),
                            "empty_result_validated": False,
                            "empty_result_checks": empty_checks,
                        },
                    )
                    result.stats = {
                        "rows_found": 0,
                        "empty_result_validated": False,
                        "empty_result_checks": empty_checks,
                    }
                    _log(f"Presence scrape rejected unvalidated empty export checks={empty_checks}\n")
                    return result

            ensure_presence_tables(cursor)
            result.finished_at = _utcnow()
            effective_mark_missing = mark_missing and (len(rows) > 0 or empty_validated)
            stats = apply_presence_scrape(
                cursor,
                org,
                portal_status=result.portal_status,
                rows=rows,
                source_batch_id=batch_id,
                source_url=source_url,
                dry_run=dry_run,
                mark_missing=effective_mark_missing,
                run_type=run_type,
                started_at=result.started_at,
                finished_at=result.finished_at,
                status="success" if not dry_run else "dry_run",
                scrape_meta={
                    **(scrape_meta or {}),
                    "empty_result_validated": empty_validated if len(rows) == 0 else None,
                    "empty_result_checks": empty_checks if len(rows) == 0 else None,
                },
            )
            if len(rows) == 0:
                stats["empty_result_validated"] = empty_validated
                stats["empty_result_checks"] = empty_checks
            if not dry_run:
                conn.commit()
            else:
                conn.rollback()

            result.stats = stats
            result.status = "success" if not dry_run else "dry_run"
            _log(
                f"Presence scrape done rows_found={stats.get('rows_found')} "
                f"inserted={stats.get('rows_inserted')} updated={stats.get('rows_updated')} "
                f"pages={scrape_debug.get('pages_visited')}\n"
            )
            if stdout:
                _log((stdout or "")[-1000:] + "\n")
            return result
    except Exception as exc:
        conn.rollback()
        result.status = "failed"
        result.error_message = str(exc)
        result.finished_at = _utcnow()
        _log(f"Presence scrape ERROR: {exc}\n")
        _persist_failed_run(error_message=result.error_message)
        return result
