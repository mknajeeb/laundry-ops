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

from backend.rinse_bag_export_runner import (
    _parse_env_truthy,
    export_enabled,
    run_bag_export_csv,
    scraper_dir,
)
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
        default = int(os.getenv("RINSE_SCRAPE_TIMEOUT_SEC", "900"))
    except (TypeError, ValueError):
        default = 900
    try:
        raw = os.getenv("RINSE_PRESENCE_PHASE_TIMEOUT_SEC")
        if raw is not None and str(raw).strip():
            return max(60, min(7200, int(raw)))
        return max(60, min(7200, default))
    except (TypeError, ValueError):
        return max(60, min(7200, default))


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


def rfv_scrape_enabled() -> bool:
    """Master kill-switch for ALL Ready-For-Vendor scraping/processing.

    Controlled by env ``RFV_SCRAPE_ENABLED`` (default ``false``). When disabled no
    scheduled, combined-cycle, manual, or API-triggered RFV scrape runs — regardless of
    the per-tenant ``enable_ready_for_vendor_scrape`` flag or any DB-driven override. This
    is intentionally an env/config default so a stale DB setting cannot re-enable RFV.

    RFV is inactive in Shift Monitor until this returns True: no scrape, no scheduled
    jobs, no RFV queue load, no RFV sync UI, no RFV workload contribution.
    """
    raw = (os.getenv("RFV_SCRAPE_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "on", "yes", "enabled"}


def rfv_feature_active() -> bool:
    """True only when RFV is explicitly re-enabled via ``RFV_SCRAPE_ENABLED``."""
    return rfv_scrape_enabled()


def ready_for_vendor_scrape_enabled(cursor, organization_id: int) -> bool:
    # Master kill-switch first: RFV_SCRAPE_ENABLED (default false) overrides the per-tenant
    # flag and any DB-driven override so RFV stays off until explicitly re-enabled.
    if not rfv_scrape_enabled():
        return False
    return is_feature_enabled(cursor, int(organization_id), "enable_ready_for_vendor_scrape")


def _scrape_data_root() -> Path:
    raw = (os.getenv("RINSE_SCRAPE_DATA_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "data" / "rinse-scrape"


def _tenant_data_dir(vendor: str) -> Path:
    return _scrape_data_root() / "tenants" / vendor.strip().lower()


def _load_tenant_dotenv(vendor: str) -> dict[str, str]:
    """Tenant .env from Azure Files mount or repo scripts/rinse-tenants/<vendor>/.env."""
    v = vendor.strip().lower()
    repo_tenant = Path(__file__).resolve().parent.parent / "scripts" / "rinse-tenants" / v
    for base in (_tenant_data_dir(v), repo_tenant):
        env_path = base / ".env"
        if not env_path.is_file():
            continue
        out: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key.startswith("RINSE_"):
                out[key] = val
        storage = out.get("RINSE_STORAGE_STATE")
        if storage and not Path(storage).is_absolute():
            out["RINSE_STORAGE_STATE"] = str((base / storage).resolve())
        return out
    return {}


def _merge_presence_scrape_env(vendor: str, vendor_env: dict[str, str]) -> dict[str, str]:
    """
    Merge tenant .env gaps and prefer mounted tenant rinse-auth.json when present.
    Keeps manual Refresh Both Syncs aligned with ACA scheduled job auth paths.
    """
    extra = dict(vendor_env)
    tenant = _load_tenant_dotenv(vendor)
    mounted_auth = _tenant_data_dir(vendor) / "rinse-auth.json"
    if mounted_auth.is_file() and mounted_auth.stat().st_size > 8:
        extra["RINSE_STORAGE_STATE"] = str(mounted_auth)
    for key, val in tenant.items():
        if key == "RINSE_STORAGE_STATE":
            continue
        extra.setdefault(key, val)
    return extra


def _stderr_tail(stderr: str, *, limit: int = 600) -> str:
    text = (stderr or "").strip()
    if not text:
        return ""
    return text[-limit:]


def _format_scrape_subprocess_error(code: int, stderr: str, *, phase_timeout: int) -> str:
    tail = _stderr_tail(stderr)
    if code == -1:
        base = f"Scrape timed out after {phase_timeout}s"
        return f"{base}: {tail}" if tail else base
    base = f"Scrape subprocess failed (exit {code})"
    return f"{base}: {tail}" if tail else base


def _preflight_presence_scrape(vendor: str, extra_env: dict[str, str]) -> str | None:
    """
    Fail fast before launching Playwright when the host cannot scrape reliably.

    Scheduled sync runs in the ACA job with Azure Files auth; manual Refresh Both Syncs
    hits laundryops-api and often lacks the same mount (see docs/RINSE_SCHEDULED_SCRAPE.md).
    """
    if _parse_env_truthy(os.getenv("RINSE_SCRAPE_REMOTE_ONLY")):
        from backend.rinse_aca_job_trigger import remote_only_user_message

        return remote_only_user_message()

    storage = (extra_env.get("RINSE_STORAGE_STATE") or "").strip()
    if storage and not Path(storage).is_file():
        mounted = _tenant_data_dir(vendor) / "rinse-auth.json"
        return (
            f"Rinse auth missing at {storage}. "
            f"Expected mounted auth at {mounted} when RINSE_SCRAPE_DATA_ROOT is configured."
        )

    if Path("/home/site").is_dir():
        mounted = _tenant_data_dir(vendor) / "rinse-auth.json"
        storage_path = Path(storage) if storage else None
        wwwroot = Path("/home/site/wwwroot")
        using_wwwroot_auth = (
            storage_path is not None
            and wwwroot in storage_path.parents
            and not mounted.is_file()
        )
        if using_wwwroot_auth:
            return (
                "Manual sync on App Service is using wwwroot rinse-auth; scheduled sync uses "
                f"Azure Files at {mounted}. Mount the rinse-scrape share on laundryops-api "
                "(RINSE_SCRAPE_DATA_ROOT=/data/rinse-scrape) or start the ACA scheduled job."
            )
    return None


def _resolve_max_pages(extra_env: dict[str, str], override: str | None) -> str:
    if override and str(override).strip():
        return str(override).strip()
    raw = (extra_env.get("RINSE_MAX_PAGES") or "").strip()
    if raw:
        return raw
    host_cap = (os.getenv("RINSE_MAX_PAGES") or "").strip()
    if host_cap:
        return host_cap
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
        # Quiet, non-error skip. Master kill-switch (RFV_SCRAPE_ENABLED) takes precedence in
        # the reason so an overlooked scheduler/manual/internal call cannot run RFV.
        result.status = "disabled"
        result.skipped_reason = (
            "RFV_SCRAPE_ENABLED=false"
            if not rfv_scrape_enabled()
            else "enable_ready_for_vendor_scrape=false"
        )
        result.finished_at = _utcnow()
        _log(f"Ready for Vendor scrape skipped org={org} ({result.skipped_reason})")
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
        scraper_dir=scraper_dir(),
    )
    result.rinse_vendor = vendor
    base_url = vendor_env.get("RINSE_TICKETS_URL") or ""
    source_url = build_tickets_url_for_portal_status(base_url, result.portal_status)
    result.source_url = source_url

    extra_env = _merge_presence_scrape_env(vendor, vendor_env)
    extra_env["RINSE_TICKETS_URL"] = source_url
    extra_env["RINSE_CSV_LAYOUT"] = "portal"
    extra_env["RINSE_ALLOW_EMPTY_EXPORT"] = "1"
    extra_env["RINSE_MAX_PAGES"] = _resolve_max_pages(extra_env, max_pages)
    extra_env.setdefault("RINSE_PAGE_SETTLE_MS", "2000")
    extra_env.setdefault("RINSE_TABLE_WAIT_MS", "800")

    preflight_error = _preflight_presence_scrape(vendor, extra_env)
    if preflight_error:
        result.status = "failed"
        result.error_message = preflight_error
        result.finished_at = _utcnow()
        _persist_failed_run(error_message=result.error_message)
        return result

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
                result.error_message = _format_scrape_subprocess_error(
                    code, stderr or "", phase_timeout=phase_timeout
                )
                scrape_meta = read_portal_scrape_meta(str(meta_path))
                result.scrape_debug = build_presence_scrape_debug(
                    portal_status=result.portal_status,
                    source_url=source_url,
                    rows=[],
                    scrape_meta=scrape_meta,
                    exit_code=code,
                )
                stderr_tail = _stderr_tail(stderr or "")
                if stderr_tail:
                    result.scrape_debug["stderr_tail"] = stderr_tail
                if stderr:
                    _log(stderr[-2000:] + "\n")
                result.finished_at = _utcnow()
                _persist_failed_run(error_message=result.error_message, scrape_meta=scrape_meta)
                return result

            rows = parse_presence_rows_from_portal_csv(str(csv_path))
            scrape_meta = read_portal_scrape_meta(str(meta_path))
            if result.portal_status == PORTAL_STATUS_AT_VENDOR:
                from backend.rinse_bag_export_runner import run_vendor_home_summary_scrape

                if not extract_vendor_home_summary_from_scrape_meta(scrape_meta):
                    vendor_home, supplement_err = run_vendor_home_summary_scrape(extra_env)
                    if extract_vendor_home_summary_from_scrape_meta(
                        {"vendor_home_summary": vendor_home}
                    ):
                        scrape_meta = {
                            **(scrape_meta or {}),
                            "vendor_home_summary": vendor_home,
                            "vendor_home_supplement": "scrape-vendor-home.mjs",
                        }
                        _log(
                            "Vendor Home summary supplement: "
                            f"at={vendor_home.get('orders_at_veewash')} "
                            f"ytp={vendor_home.get('orders_at_veewash_yet_to_process')}\n"
                        )
                    elif supplement_err:
                        scrape_meta = {
                            **(scrape_meta or {}),
                            "vendor_home_supplement_error": supplement_err[:2000],
                        }
                        _log(f"Vendor Home summary supplement failed: {supplement_err}\n")
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
            # Downstream evidence (membership + interval weight attach) after a
            # successful at_vendor board apply. Best-effort: evidence commit still
            # happens even if downstream fails (failed stage recorded on the run).
            if (
                not dry_run
                and stats.get("board_applied")
                and str(result.portal_status or "") == PORTAL_STATUS_AT_VENDOR
                and stats.get("run_id")
            ):
                try:
                    from backend.rinse_presence_evidence_pipeline import (
                        continue_presence_run_downstream,
                    )

                    downstream = continue_presence_run_downstream(
                        cursor, org, int(stats["run_id"])
                    )
                    stats["evidence_downstream"] = downstream
                except Exception as downstream_exc:
                    stats["evidence_downstream"] = {
                        "ok": False,
                        "error": str(downstream_exc),
                    }
                    try:
                        from backend.rinse_cleaner_ticket_presence import (
                            EVIDENCE_STAGE_BOARD_APPLIED,
                            set_presence_run_processing_stage,
                        )

                        set_presence_run_processing_stage(
                            cursor,
                            org,
                            int(stats["run_id"]),
                            stage=str(
                                stats.get("evidence_processing_stage")
                                or EVIDENCE_STAGE_BOARD_APPLIED
                            ),
                            failed_stage="evidence_downstream",
                            error=str(downstream_exc),
                        )
                    except Exception:
                        pass

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
