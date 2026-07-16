"""
Server-side scheduled Rinse scrape: Playwright (Node) + dual CSV import + auto-confirm.

Run via: python -m backend.jobs.run_scheduled_rinse_scrape
Designed for Azure Container Apps scheduled jobs (isolated from laundryops-api).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from backend.rinse_scrape_runs import (
    acquire_scrape_lock,
    finish_scrape_run,
    insert_scrape_run,
    insert_skipped_scrape_run,
    release_scrape_lock,
)
from backend.rinse_vendor_config import resolve_rinse_vendor, rinse_scrape_env_for_organization

ET = ZoneInfo("America/New_York")
REPO_ROOT = Path(__file__).resolve().parent.parent


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    v = str(raw).strip().lower()
    return v in ("1", "true", "yes", "on")


def scheduled_scrape_enabled() -> bool:
    return _truthy(os.getenv("RINSE_SCHEDULED_SCRAPE_ENABLED"))


def portal_auto_confirm_force_enabled() -> bool:
    return _truthy(os.getenv("RINSE_PORTAL_AUTO_CONFIRM_FORCE"))


def _resolve_force_portal_confirm(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return portal_auto_confirm_force_enabled()


def parse_scheduled_org_ids() -> list[int]:
    """
    Comma/semicolon-separated organization IDs to process sequentially each run.
    Example v1: 3  |  Future: 1,3,5

    Uses RINSE_SCHEDULED_ORG_IDS only. (RINSE_VEEWASH_ORG_IDS is a legacy fallback when unset.)
    """
    raw = (os.getenv("RINSE_SCHEDULED_ORG_IDS") or "").strip()
    if not raw:
        raw = (os.getenv("RINSE_VEEWASH_ORG_IDS") or "").strip()
    out: list[int] = []
    seen: set[int] = set()
    for part in re.split(r"[,;\s]+", raw):
        if not part:
            continue
        try:
            oid = int(part)
        except ValueError:
            continue
        if oid not in seen:
            seen.add(oid)
            out.append(oid)
    return out


def tenant_data_dir(vendor: str) -> Path:
    """Persistent auth + .env on Azure Files: /data/rinse-scrape/tenants/<vendor>/."""
    return scrape_data_root() / "tenants" / vendor.strip().lower()


def scrape_data_root() -> Path:
    raw = (os.getenv("RINSE_SCRAPE_DATA_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return REPO_ROOT / "data" / "rinse-scrape"


def scrape_timeout_sec() -> int:
    try:
        return max(60, min(7200, int(os.getenv("RINSE_SCRAPE_TIMEOUT_SEC", "1800"))))
    except (TypeError, ValueError):
        return 1800


def combined_phase_timeout_sec() -> int:
    """Per-phase timeout for combined sync (RFV presence, AV presence, AV CSV import)."""
    try:
        return max(60, min(7200, int(os.getenv("RINSE_COMBINED_PHASE_TIMEOUT_SEC", "900"))))
    except (TypeError, ValueError):
        return 900


def _now_et() -> datetime:
    return datetime.now(ET)


def _today_et() -> date:
    return _now_et().date()


def _stamp_et() -> str:
    return _now_et().strftime("%Y%m%d_%H%M%S")


def _today_label_et() -> str:
    return _today_et().isoformat()


def count_csv_data_rows(path: Path) -> int:
    """Non-empty lines minus header."""
    if not path.is_file():
        return 0
    lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s:
                lines.append(s)
    return max(0, len(lines) - 1)


def _org_slug_name(cursor, organization_id: int) -> tuple[str | None, str | None]:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "organizations"):
        return None, None
    cursor.execute(
        """
        SELECT slug, display_name
        FROM organizations
        WHERE id = %s
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None, None
    slug = (row.get("slug") or "").strip() or None
    name = (row.get("display_name") or "").strip() or None
    return slug, name


def tenant_script_dir(vendor: str) -> Path:
    return REPO_ROOT / "scripts" / "rinse-tenants" / vendor.strip().lower()


@dataclass
class ScrapePaths:
    run_dir: Path
    portal_csv: Path
    scan_tickets_csv: Path
    scan_events_csv: Path
    log_path: Path


def build_run_paths(
    organization_id: int,
    run_type: str,
    *,
    tenant_slug: str | None = None,
    rinse_vendor: str | None = None,
) -> ScrapePaths:
    """
    Per-organization audit folder (never shared between tenants).
    runs/org_<id>_<slug>/... or runs/org_<id>/... if slug unknown.
    """
    day = _today_label_et()
    stamp = _stamp_et()
    slug_part = (tenant_slug or rinse_vendor or "org").strip().lower()
    slug_part = re.sub(r"[^a-z0-9_-]+", "-", slug_part).strip("-") or "org"
    run_root = scrape_data_root() / "runs" / f"org_{int(organization_id)}_{slug_part}"
    run_dir = run_root / f"{day}_{stamp}_{run_type}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return ScrapePaths(
        run_dir=run_dir,
        portal_csv=run_dir / "portal.csv",
        scan_tickets_csv=run_dir / "scan-events-tickets.csv",
        scan_events_csv=run_dir / "scan-events-events.csv",
        log_path=run_dir / "orchestrator.log",
    )


@dataclass
class ScheduledScrapeResult:
    organization_id: int
    run_id: int | None = None
    status: str = "failed"
    at_vendor_status: str = "failed"
    ready_for_vendor_status: str | None = None
    rinse_vendor: str = ""
    tenant_slug: str | None = None
    batch_id: int | None = None
    portal_rows_count: int = 0
    scan_events_count: int = 0
    paths: ScrapePaths | None = None
    error_message: str | None = None
    ready_for_vendor_error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class _TeeLog:
    def __init__(self, path: Path):
        self._path = path
        self._file = path.open("a", encoding="utf-8")

    def write(self, msg: str) -> None:
        sys.stdout.write(msg)
        self._file.write(msg)
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _run_bash_script(script: Path, extra_env: dict[str, str], log: _TeeLog, *, timeout_sec: int | None = None) -> int:
    env = {**os.environ, **extra_env}
    log.write(f"\n--- bash {script} ---\n")
    timeout = int(timeout_sec) if timeout_sec is not None else combined_phase_timeout_sec()
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log.write(f"exit code: timeout after {timeout}s\n")
        if exc.stdout:
            log.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", errors="replace"))
        if exc.stderr:
            log.write(exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace"))
        return -1
    if proc.stdout:
        log.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            log.write("\n")
    if proc.stderr:
        log.write(proc.stderr)
        if not proc.stderr.endswith("\n"):
            log.write("\n")
    log.write(f"exit code: {proc.returncode}\n")
    return int(proc.returncode)


def _subprocess_env_for_vendor(
    organization_id: int,
    vendor: str,
    paths: ScrapePaths,
    *,
    organization_slug: str | None = None,
    organization_name: str | None = None,
) -> dict[str, str]:
    from backend.rinse_bag_export_runner import scraper_dir

    _, vendor_env = rinse_scrape_env_for_organization(
        int(organization_id),
        organization_slug=organization_slug,
        organization_name=organization_name,
        override_vendor=vendor,
        scraper_dir=scraper_dir(),
    )
    day = _today_label_et()
    tenant_data = tenant_data_dir(vendor)
    out = {
        **vendor_env,
        "RINSE_CSV_LAYOUT": "portal",
        "RINSE_TENANT_DATA_DIR": str(tenant_data),
        "OUTPUT_CSV": str(paths.portal_csv),
        "OUTPUT_SCAN_TICKETS_CSV": str(paths.scan_tickets_csv),
        "OUTPUT_SCAN_EVENTS_CSV": str(paths.scan_events_csv),
    }
    # Tenant scripts default to dated names under output/; explicit paths win.
    if not (os.getenv("RINSE_MAX_PAGES") or "").strip():
        tenant_env = tenant_script_dir(vendor) / ".env"
        if tenant_env.is_file():
            for line in tenant_env.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("RINSE_MAX_PAGES=") and "=" in line:
                    out.setdefault("RINSE_MAX_PAGES", line.split("=", 1)[1].strip())
    out.setdefault("RINSE_MAX_PAGES", "20")
    return out


def _count_attention_rows(cursor, batch_id: int) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM upload_batch_rows
        WHERE upload_batch_id = %s AND row_status = 'NEEDS_ATTENTION'
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone() or {}
    return int(row.get("c") if isinstance(row, dict) else row[0] or 0)


def _count_accepted_rows(cursor, batch_id: int) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM upload_batch_rows
        WHERE upload_batch_id = %s AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone() or {}
    return int(row.get("c") if isinstance(row, dict) else row[0] or 0)


def _combine_scheduled_status(at_vendor_status: str, rfv_status: str | None) -> str:
    """Overall scheduled run status from separate At Vendor + Ready for Vendor steps."""
    av_ok = at_vendor_status in ("success", "needs_attention")
    if rfv_status is None or rfv_status == "disabled":
        return at_vendor_status
    if rfv_status in ("success", "dry_run"):
        return at_vendor_status if av_ok else "partial_success"
    if av_ok and rfv_status == "failed":
        return "partial_success"
    if not av_ok:
        return "failed"
    return at_vendor_status


CYCLE_ALREADY_RUNNING = "ALREADY_RUNNING"


def build_presence_sync_detail(presence_result) -> dict[str, Any]:
    """Serialize a portal presence scrape result for API / cycle metadata."""
    stats = presence_result.stats or {}
    return {
        "status": presence_result.status,
        "skipped_reason": presence_result.skipped_reason,
        "error_message": presence_result.error_message,
        "run_id": stats.get("run_id"),
        "rows_found": stats.get("rows_found"),
        "rows_inserted": stats.get("rows_inserted"),
        "rows_updated": stats.get("rows_updated"),
        "rows_missing": stats.get("rows_missing"),
        "active_rows": stats.get("active_rows"),
        "snapshot_rows_persisted": stats.get("snapshot_rows_persisted"),
        "empty_result_validated": stats.get("empty_result_validated"),
        "stats": stats,
        "scrape_debug": presence_result.scrape_debug,
        "started_at": presence_result.started_at.isoformat() if presence_result.started_at else None,
        "finished_at": presence_result.finished_at.isoformat() if presence_result.finished_at else None,
        "duration_seconds": presence_result.duration_seconds,
    }


def build_ready_for_vendor_sync_detail(rfv_result) -> dict[str, Any]:
    """Serialize Ready for Vendor presence scrape result for API payloads."""
    return build_presence_sync_detail(rfv_result)


@dataclass
class _CombinedCycleContext:
    """When set, CSV import reuses an existing combined cycle run + lock."""

    run_id: int
    paths: ScrapePaths
    log: "_TeeLog"
    started_at: datetime


def _resolve_combined_cycle_status(
    *,
    rfv_status: str | None,
    av_presence_status: str | None,
    import_status: str | None,
) -> str:
    """Map step outcomes to combined cycle status labels."""
    if rfv_status in (None, "failed", "disabled") or (
        rfv_status not in ("success", "dry_run") and rfv_status is not None
    ):
        return "RFV_FAILED"
    if av_presence_status not in ("success", "dry_run"):
        return "AT_VENDOR_FAILED"
    if import_status in ("failed", "skipped"):
        return "AT_VENDOR_IMPORT_FAILED"
    if import_status == "needs_attention":
        return "needs_attention"
    if import_status == "inspect_only":
        return "inspect_only"
    if import_status in ("success", "dry_run"):
        return "success"
    return str(import_status or "failed")


def _build_sync_cycle_metadata(
    *,
    sync_cycle_id: int | None,
    cycle_started_at: datetime | None,
    rfv_detail: Mapping[str, Any] | None,
    av_presence_detail: Mapping[str, Any] | None,
    import_started_at: datetime | None,
    import_finished_at: datetime | None,
    delay_seconds: int | None,
    cycle_status: str,
    at_vendor_ran: bool | None = None,
    at_vendor_skipped_reason: str | None = None,
    failure_message: str | None = None,
    scan_events_inserted: int | None = None,
    scan_events_already_present: int | None = None,
) -> dict[str, Any]:
    rfv = dict(rfv_detail or {})
    avp = dict(av_presence_detail or {})
    out = {
        "sync_cycle_id": sync_cycle_id,
        "cycle_started_at": cycle_started_at.isoformat() if isinstance(cycle_started_at, datetime) else None,
        "cycle_status": cycle_status,
        "rfv_status": rfv.get("status"),
        "rfv_started_at": rfv.get("started_at"),
        "rfv_completed_at": rfv.get("finished_at"),
        "rfv_run_id": rfv.get("run_id"),
        "at_vendor_presence_started_at": avp.get("started_at"),
        "at_vendor_presence_completed_at": avp.get("finished_at"),
        "at_vendor_run_id": avp.get("run_id"),
        "at_vendor_started_at": (
            import_started_at.isoformat() if isinstance(import_started_at, datetime) else avp.get("started_at")
        ),
        "at_vendor_completed_at": (
            import_finished_at.isoformat() if isinstance(import_finished_at, datetime) else None
        ),
        "at_vendor_status": None,
        "delay_seconds": delay_seconds,
        "at_vendor_ran": at_vendor_ran,
        "at_vendor_skipped_reason": at_vendor_skipped_reason,
        "failure_message": failure_message,
        "rfv_error": rfv.get("error_message"),
        "at_vendor_presence_error": avp.get("error_message"),
    }
    if scan_events_inserted is not None:
        out["scan_events_inserted"] = int(scan_events_inserted)
    if scan_events_already_present is not None:
        out["scan_events_already_present"] = int(scan_events_already_present)
    return out


def _finish_combined_cycle_run(
    conn,
    cursor,
    *,
    organization_id: int,
    result: ScheduledScrapeResult,
    started_at: datetime,
    paths: ScrapePaths,
    sync_cycle: Mapping[str, Any],
    ready_for_vendor_sync: Mapping[str, Any] | None = None,
    at_vendor_presence_sync: Mapping[str, Any] | None = None,
) -> None:
    detail = dict(result.detail or {})
    detail["sync_cycle"] = dict(sync_cycle)
    if ready_for_vendor_sync:
        detail["ready_for_vendor_sync"] = dict(ready_for_vendor_sync)
    if at_vendor_presence_sync:
        detail["at_vendor_presence_sync"] = dict(at_vendor_presence_sync)
    result.detail = detail
    result.finished_at = datetime.utcnow()
    if result.run_id:
        finish_scrape_run(
            cursor,
            int(result.run_id),
            int(organization_id),
            status=result.status,
            started_at=started_at,
            portal_csv_path=str(paths.portal_csv) if paths.portal_csv.is_file() else None,
            scan_events_csv_path=str(paths.scan_tickets_csv) if paths.scan_tickets_csv.is_file() else None,
            scan_events_events_path=str(paths.scan_events_csv) if paths.scan_events_csv.is_file() else None,
            portal_rows_count=result.portal_rows_count,
            scan_events_count=result.scan_events_count,
            imported_batch_id=result.batch_id,
            error_message=result.error_message,
            log_path=str(paths.log_path),
            result_json=detail,
        )
        conn.commit()


def _apply_rfv_to_scheduled_result(
    result: ScheduledScrapeResult,
    *,
    rfv_result,
    rfv_detail: dict[str, Any],
) -> ScheduledScrapeResult:
    """Merge Ready for Vendor step into scheduled scrape result and overall status."""
    result.detail["ready_for_vendor_sync"] = rfv_detail
    result.ready_for_vendor_status = rfv_result.status
    if rfv_result.status == "failed":
        result.ready_for_vendor_error = rfv_result.error_message
    result.status = _combine_scheduled_status(
        result.at_vendor_status or result.status,
        rfv_result.status,
    )
    if result.status == "partial_success" and not result.error_message:
        result.error_message = result.ready_for_vendor_error or "Ready for Vendor sync failed"
    return result


def run_rinse_combined_sync_for_org(
    conn,
    organization_id: int,
    *,
    run_type: str = "scheduled",
    dry_run: bool = False,
    targeted_pending_refresh: bool | None = None,
) -> ScheduledScrapeResult:
    """
    Combined presence sync: RFV presence → At Vendor presence → scan CSV import.
    Shared by manual Refresh Both Syncs and scheduled ACA cron.
    """
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_presence_scrape import run_presence_scrape_for_org

    org_id = int(organization_id)
    cursor = conn.cursor(dictionary=True)
    slug, org_name = _org_slug_name(cursor, org_id)
    vendor = resolve_rinse_vendor(org_id, organization_slug=slug, organization_name=org_name)

    result = ScheduledScrapeResult(
        organization_id=org_id,
        tenant_slug=slug,
        rinse_vendor=vendor,
    )
    cycle_started_at = datetime.utcnow()
    result.started_at = cycle_started_at

    if dry_run:
        result.status = "skipped"
        result.at_vendor_status = "skipped"
        result.detail = {"dry_run": True, "sync_cycle": {"cycle_status": "dry_run"}}
        return result

    acquired, lock_reason = acquire_scrape_lock(cursor, org_id)
    conn.commit()
    if not acquired:
        skip_reason = CYCLE_ALREADY_RUNNING if "still active" in (lock_reason or "") else lock_reason
        insert_skipped_scrape_run(
            cursor,
            org_id,
            tenant_slug=slug,
            rinse_vendor=vendor,
            run_type=run_type,
            reason=skip_reason or CYCLE_ALREADY_RUNNING,
        )
        conn.commit()
        result.status = "skipped"
        result.error_message = skip_reason or CYCLE_ALREADY_RUNNING
        result.detail = {
            "sync_cycle": {
                "cycle_status": "skipped",
                "failure_message": result.error_message,
            }
        }
        return result

    paths = build_run_paths(org_id, run_type, tenant_slug=slug, rinse_vendor=vendor)
    result.paths = paths
    run_id = insert_scrape_run(
        cursor,
        org_id,
        tenant_slug=slug,
        rinse_vendor=vendor,
        run_type=run_type,
        log_path=str(paths.log_path),
    )
    conn.commit()
    result.run_id = run_id
    log = _TeeLog(paths.log_path)
    started_at = cycle_started_at

    rfv_detail: dict[str, Any] = {}
    av_presence_detail: dict[str, Any] = {}
    import_result: ScheduledScrapeResult | None = None
    delay_seconds: int | None = None

    try:
        print(
            f"Ready for Vendor sync org={org_id} vendor={vendor} run_type={run_type}",
            flush=True,
        )
        log.write(
            f"Combined sync cycle run_id={run_id} org={org_id} vendor={vendor} run_type={run_type}\n"
        )
        rfv_result = run_presence_scrape_for_org(
            conn,
            org_id,
            portal_status="ready_for_vendor",
            dry_run=False,
            mark_missing=True,
            run_type=run_type,
            organization_slug=slug,
            organization_name=org_name,
            rinse_vendor=vendor,
            log_write=log.write,
        )
        rfv_detail = build_ready_for_vendor_sync_detail(rfv_result)
        result.ready_for_vendor_status = rfv_result.status
        conn.commit()
        print(
            f"Ready for Vendor sync done org={org_id} status={rfv_result.status} "
            f"rows_found={(rfv_result.stats or {}).get('rows_found')}",
            flush=True,
        )

        if rfv_result.status not in ("success", "dry_run"):
            cycle_status = "RFV_FAILED"
            result.status = "failed"
            result.at_vendor_status = "skipped"
            result.error_message = rfv_result.error_message or "Ready for Vendor presence scrape failed"
            sync_cycle = _build_sync_cycle_metadata(
                sync_cycle_id=run_id,
                cycle_started_at=cycle_started_at,
                rfv_detail=rfv_detail,
                av_presence_detail=None,
                import_started_at=None,
                import_finished_at=None,
                delay_seconds=None,
                cycle_status=cycle_status,
                at_vendor_ran=False,
                at_vendor_skipped_reason="RFV presence scrape failed",
                failure_message=result.error_message,
            )
            _finish_combined_cycle_run(
                conn,
                cursor,
                organization_id=org_id,
                result=result,
                started_at=started_at,
                paths=paths,
                sync_cycle=sync_cycle,
                ready_for_vendor_sync=rfv_detail,
            )
            return result

        print(
            f"At Vendor presence sync org={org_id} vendor={vendor} run_type={run_type}",
            flush=True,
        )
        av_presence_result = run_presence_scrape_for_org(
            conn,
            org_id,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            dry_run=False,
            mark_missing=True,
            run_type=run_type,
            organization_slug=slug,
            organization_name=org_name,
            rinse_vendor=vendor,
            log_write=log.write,
        )
        av_presence_detail = build_presence_sync_detail(av_presence_result)
        conn.commit()
        if isinstance(rfv_result.finished_at, datetime) and isinstance(av_presence_result.started_at, datetime):
            delay_seconds = max(0, int((av_presence_result.started_at - rfv_result.finished_at).total_seconds()))
        print(
            f"At Vendor presence sync done org={org_id} status={av_presence_result.status} "
            f"rows_found={(av_presence_result.stats or {}).get('rows_found')} delay_seconds={delay_seconds}",
            flush=True,
        )

        if av_presence_result.status not in ("success", "dry_run"):
            cycle_status = "AT_VENDOR_FAILED"
            result.status = "failed"
            result.at_vendor_status = "failed"
            result.error_message = (
                av_presence_result.error_message or "At Vendor presence scrape failed"
            )
            sync_cycle = _build_sync_cycle_metadata(
                sync_cycle_id=run_id,
                cycle_started_at=cycle_started_at,
                rfv_detail=rfv_detail,
                av_presence_detail=av_presence_detail,
                import_started_at=None,
                import_finished_at=None,
                delay_seconds=delay_seconds,
                cycle_status=cycle_status,
                at_vendor_ran=False,
                at_vendor_skipped_reason="At Vendor presence scrape failed",
                failure_message=result.error_message,
            )
            _finish_combined_cycle_run(
                conn,
                cursor,
                organization_id=org_id,
                result=result,
                started_at=started_at,
                paths=paths,
                sync_cycle=sync_cycle,
                ready_for_vendor_sync=rfv_detail,
                at_vendor_presence_sync=av_presence_detail,
            )
            return result

        combined_ctx = _CombinedCycleContext(
            run_id=int(run_id),
            paths=paths,
            log=log,
            started_at=started_at,
        )
        import_result = run_scheduled_scrape_for_org(
            conn,
            org_id,
            run_type=run_type,
            dry_run=False,
            rfv_detail=rfv_detail,
            rfv_status=rfv_result.status,
            rfv_error=rfv_result.error_message,
            combined_cycle=combined_ctx,
            av_presence_detail=av_presence_detail,
            targeted_pending_refresh=targeted_pending_refresh,
        )
        result.status = import_result.status
        result.at_vendor_status = import_result.at_vendor_status or import_result.status
        result.batch_id = import_result.batch_id
        result.portal_rows_count = import_result.portal_rows_count
        result.scan_events_count = import_result.scan_events_count
        result.error_message = import_result.error_message
        result.detail = dict(import_result.detail or {})

        cycle_status = _resolve_combined_cycle_status(
            rfv_status=rfv_result.status,
            av_presence_status=av_presence_result.status,
            import_status=import_result.status,
        )
        confirm_payload = (import_result.detail or {}).get("confirm") or {}
        merge_payload = (confirm_payload.get("rinse_finalize") or {}).get("persistent_merge") or {}
        scan_inserted = merge_payload.get("events_inserted")
        scan_already = merge_payload.get("events_already_present")
        if scan_already is None:
            scan_already = merge_payload.get("events_metadata_updated")
        sync_cycle = _build_sync_cycle_metadata(
            sync_cycle_id=run_id,
            cycle_started_at=cycle_started_at,
            rfv_detail=rfv_detail,
            av_presence_detail=av_presence_detail,
            import_started_at=import_result.started_at,
            import_finished_at=import_result.finished_at,
            delay_seconds=delay_seconds,
            cycle_status=cycle_status,
            at_vendor_ran=True,
            at_vendor_skipped_reason=None,
            failure_message=result.error_message if cycle_status not in ("success", "needs_attention") else None,
            scan_events_inserted=scan_inserted,
            scan_events_already_present=scan_already,
        )
        sync_cycle["at_vendor_status"] = result.at_vendor_status
        result.detail["sync_cycle"] = sync_cycle
        result.detail["ready_for_vendor_sync"] = rfv_detail
        result.detail["at_vendor_presence_sync"] = av_presence_detail
        _finish_combined_cycle_run(
            conn,
            cursor,
            organization_id=org_id,
            result=result,
            started_at=started_at,
            paths=paths,
            sync_cycle=sync_cycle,
            ready_for_vendor_sync=rfv_detail,
            at_vendor_presence_sync=av_presence_detail,
        )
        return result
    except Exception as exc:
        conn.rollback()
        result.status = "failed"
        result.at_vendor_status = "failed"
        result.error_message = str(exc)
        log.write(f"Combined sync ERROR: {exc}\n")
        sync_cycle = _build_sync_cycle_metadata(
            sync_cycle_id=run_id,
            cycle_started_at=cycle_started_at,
            rfv_detail=rfv_detail or None,
            av_presence_detail=av_presence_detail or None,
            import_started_at=import_result.started_at if import_result else None,
            import_finished_at=import_result.finished_at if import_result else None,
            delay_seconds=delay_seconds,
            cycle_status="failed",
            failure_message=str(exc),
        )
        _finish_combined_cycle_run(
            conn,
            cursor,
            organization_id=org_id,
            result=result,
            started_at=started_at,
            paths=paths,
            sync_cycle=sync_cycle,
            ready_for_vendor_sync=rfv_detail or None,
            at_vendor_presence_sync=av_presence_detail or None,
        )
        return result
    finally:
        log.close()
        release_scrape_lock(cursor, org_id)
        conn.commit()


def _build_gate_block_operational_log(
    portal_gate: Mapping[str, Any],
    scan_events_only_detail: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merge = (scan_events_only_detail or {}).get("persistent_scan_merge") or {}
    imported_count = int(merge.get("events_inserted") or 0)
    scan_batch_id = (scan_events_only_detail or {}).get("batch_id")
    import_status = (scan_events_only_detail or {}).get("status")
    import_attempted = scan_events_only_detail is not None
    return {
        "portal_confirm_blocked": portal_gate.get("confirm_decision") == "inspect_only",
        "portal_confirm_block_reason": portal_gate.get("reason"),
        "scan_events_import_attempted": import_attempted,
        "scan_events_imported_count": imported_count if import_status == "scan_events_imported" else 0,
        "scan_events_import_status": import_status,
        "scan_only_batch_id": scan_batch_id,
    }


def _run_targeted_pending_scan_refresh(
    conn,
    cursor,
    *,
    org_id: int,
    upload_batch_id: int | None,
    batch_date: date,
    run_type: str,
    targeted_pending_refresh: bool | None,
    log,
) -> dict[str, Any] | None:
    from backend.rinse_off_portal_scan_refresh import (
        build_targeted_refresh_sync_summary,
        off_portal_refresh_dry_run,
        off_portal_refresh_enabled,
        off_portal_refresh_rush_only,
        off_portal_refresh_scheduled_timeout_sec,
        refresh_pending_workload_scans_via_direct_lookup,
    )
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    refresh_enabled = off_portal_refresh_enabled()
    run_targeted = (
        targeted_pending_refresh
        if targeted_pending_refresh is not None
        else (run_type == "manual" or refresh_enabled)
    )
    if not run_targeted:
        log.write(
            "Targeted pending scan refresh skipped "
            "(RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED=0)\n"
        )
        return build_targeted_refresh_sync_summary(
            None,
            skipped_reason="RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED=0",
        )

    try:
        refresh_dry = off_portal_refresh_dry_run() if run_type == "scheduled" else False
        refresh_timeout = (
            off_portal_refresh_scheduled_timeout_sec() if run_type == "scheduled" else None
        )
        baseline_ctx = build_baseline_context(
            cursor, org_id, get_shift_monitor_baseline(cursor, org_id)
        )
        raw_refresh = refresh_pending_workload_scans_via_direct_lookup(
            cursor,
            org_id,
            upload_batch_id=upload_batch_id,
            selected_date_et=batch_date,
            baseline_ctx=baseline_ctx,
            dry_run=refresh_dry,
            rush_only=off_portal_refresh_rush_only(),
            log_fn=lambda msg: log.write(msg + "\n"),
            timeout_sec=refresh_timeout,
        )
        if not refresh_dry:
            conn.commit()
        summary = build_targeted_refresh_sync_summary(raw_refresh)
        log.write(
            "Targeted pending scan refresh: "
            f"considered={summary.get('targeted_bags_considered')} "
            f"refreshed={summary.get('targeted_bags_refreshed')} "
            f"inserted={summary.get('missing_scans_imported')} "
            f"completed={summary.get('bags_completed_after_refresh')} "
            f"lookup_failed={summary.get('lookup_failures')} "
            f"dry_run={refresh_dry}\n"
        )

        # High-confidence: still-pending near-complete WF bags with registry
        # weight but no post-processing weight-entry (portal scrape lag / wrongful
        # MISSING_FROM_LATEST_PORTAL_SCRAPE rejection).
        try:
            from backend.rinse_near_complete_wf_backfill import (
                backfill_near_complete_wf_after_refresh,
            )

            backfill = backfill_near_complete_wf_after_refresh(
                conn,
                cursor,
                org_id,
                selected_date_et=batch_date,
                baseline_ctx=baseline_ctx,
                dry_run=refresh_dry,
                log_fn=lambda msg: log.write(msg + "\n"),
            )
            summary["near_complete_wf_weight_backfill"] = {
                "dry_run": backfill.get("dry_run"),
                "bags_considered": backfill.get("bags_considered"),
                "eligible": backfill.get("eligible"),
                "applied": backfill.get("applied"),
                "skipped": backfill.get("skipped"),
            }
            log.write(
                "Near-complete WF weight backfill: "
                f"considered={backfill.get('bags_considered')} "
                f"eligible={backfill.get('eligible')} "
                f"applied={backfill.get('applied')} "
                f"dry_run={backfill.get('dry_run')}\n"
            )
        except Exception as backfill_exc:
            log.write(
                f"Near-complete WF weight backfill ERROR (non-fatal): {backfill_exc}\n"
            )
            summary["near_complete_wf_weight_backfill"] = {"error": str(backfill_exc)}

        return summary
    except Exception as refresh_exc:
        conn.rollback()
        log.write(f"Targeted pending scan refresh ERROR (non-fatal): {refresh_exc}\n")
        return build_targeted_refresh_sync_summary({"error": str(refresh_exc)})


def _import_scan_events_when_portal_gate_blocked(
    conn,
    cursor,
    *,
    org_id: int,
    paths: ScrapePaths,
    scan_script: Path,
    env: dict[str, str],
    log,
    batch_date: date,
) -> dict[str, Any] | None:
    """Run scan-events scrape and merge into persistent storage despite ACA gate block."""
    if _run_bash_script(scan_script, env, log) != 0:
        log.write("Scan-events scrape failed during inspect_only recovery path\n")
        return {"status": "scan_events_scrape_failed"}

    scan_rows = count_csv_data_rows(paths.scan_events_csv)
    log.write(f"Scan-events scrape (inspect_only path): rows={scan_rows}\n")
    if scan_rows < 1:
        log.write("Scan-events CSV empty during inspect_only recovery path\n")
        return {"status": "scan_events_csv_empty", "scan_rows": scan_rows}

    from backend.rinse_combined_upload import commit_scheduled_scan_events_only
    from backend.rinse_scan_events_upload import parse_scan_events_csv

    events_name = f"scheduled-rinse-events-{_stamp_et()}.csv"
    events_df, warnings = parse_scan_events_csv(str(paths.scan_events_csv))
    if events_df.empty:
        log.write("Scan-events CSV parsed to zero rows during inspect_only recovery path\n")
        return {
            "status": "scan_events_parse_empty",
            "scan_rows": scan_rows,
            "warnings": warnings,
        }

    payload = commit_scheduled_scan_events_only(
        conn,
        cursor,
        org_id,
        batch_date,
        events_name,
        events_df,
    )
    log.write(
        "Scan-events-only import during inspect_only: "
        f"batch_id={payload.get('batch_id')} "
        f"events_inserted={(payload.get('persistent_scan_merge') or {}).get('events_inserted')} "
        f"bags_merged={(payload.get('persistent_scan_merge') or {}).get('bags_merged')}\n"
    )
    return {
        "status": "scan_events_imported",
        "scan_rows": scan_rows,
        "warnings": warnings,
        **payload,
    }


def run_scheduled_scrape_for_org(
    conn,
    organization_id: int,
    *,
    run_type: str = "scheduled",
    dry_run: bool = False,
    rfv_detail: dict[str, Any] | None = None,
    rfv_status: str | None = None,
    rfv_error: str | None = None,
    combined_cycle: _CombinedCycleContext | None = None,
    av_presence_detail: dict[str, Any] | None = None,
    targeted_pending_refresh: bool | None = None,
    force_portal_confirm: bool | None = None,
) -> ScheduledScrapeResult:
    """
    At Vendor bag-detail CSV scrape + scan import.
    When invoked from run_rinse_combined_sync_for_org, combined_cycle reuses the cycle run/lock.
    """
    org_id = int(organization_id)
    result = ScheduledScrapeResult(organization_id=org_id)
    cursor = conn.cursor(dictionary=True)

    slug, org_name = _org_slug_name(cursor, org_id)
    result.tenant_slug = slug

    vendor = resolve_rinse_vendor(org_id, organization_slug=slug, organization_name=org_name)
    result.rinse_vendor = vendor

    tenant_dir = tenant_script_dir(vendor)
    if not tenant_dir.is_dir():
        result.at_vendor_status = "failed"
        result.error_message = f"Missing tenant scripts: {tenant_dir}"
        return result

    using_combined = combined_cycle is not None
    if using_combined:
        paths = combined_cycle.paths
        log = combined_cycle.log
        run_id = int(combined_cycle.run_id)
        started_at = combined_cycle.started_at
    else:
        paths = build_run_paths(
            org_id, run_type, tenant_slug=slug, rinse_vendor=vendor
        )
        log = None
        run_id = 0
        started_at = datetime.utcnow()

    result.paths = paths

    if dry_run:
        result.status = "skipped"
        result.at_vendor_status = "skipped"
        result.detail = {"dry_run": True, "paths": str(paths.run_dir)}
        return result

    if using_combined:
        acquired, lock_reason = True, ""
    else:
        acquired, lock_reason = acquire_scrape_lock(cursor, org_id)
        conn.commit()
    if not acquired:
        insert_skipped_scrape_run(
            cursor,
            org_id,
            tenant_slug=slug,
            rinse_vendor=vendor,
            run_type=run_type,
            reason=lock_reason,
        )
        conn.commit()
        result.status = "skipped"
        result.at_vendor_status = "skipped"
        result.error_message = lock_reason
        return result

    if using_combined:
        result.run_id = run_id
        result.started_at = started_at
    else:
        run_id = insert_scrape_run(
            cursor,
            org_id,
            tenant_slug=slug,
            rinse_vendor=vendor,
            run_type=run_type,
            log_path=str(paths.log_path),
        )
        conn.commit()
        result.run_id = run_id
        started_at = datetime.utcnow()
        result.started_at = started_at
        log = _TeeLog(paths.log_path)

    result.at_vendor_status = "failed"
    env: dict[str, str] = {}
    own_log = not using_combined
    try:
        try:
            log.write(f"At Vendor CSV import org={org_id} vendor={vendor} run_id={run_id}\n")
            log.write(f"America/New_York batch_date={_today_label_et()}\n")

            env = _subprocess_env_for_vendor(
                org_id, vendor, paths, organization_slug=slug, organization_name=org_name
            )
            portal_script = tenant_dir / "run-production-scrape.sh"
            scan_script = tenant_dir / "run-scan-events.sh"

            if _run_bash_script(portal_script, env, log) != 0:
                raise RuntimeError("Portal scrape subprocess failed")

            if not paths.portal_csv.is_file() or count_csv_data_rows(paths.portal_csv) < 1:
                raise RuntimeError("Portal CSV missing or empty after scrape")

            from backend.rinse_portal_confirm_gate import evaluate_portal_confirm_gate

            force_confirm = _resolve_force_portal_confirm(force_portal_confirm)
            portal_gate = evaluate_portal_confirm_gate(
                paths.portal_csv, force_confirm=force_confirm
            )
            portal_rows = int(portal_gate.get("total_rows") or count_csv_data_rows(paths.portal_csv))
            result.portal_rows_count = portal_rows
            log.write(
                "Portal confirm gate: "
                f"decision={portal_gate.get('confirm_decision')} "
                f"reason={portal_gate.get('reason')} "
                f"clean_si={portal_gate.get('rows_with_clean_si')} "
                f"credible_flags={portal_gate.get('rows_with_credible_flags')} "
                f"template_flags={portal_gate.get('rows_with_template_like_flags')}\n"
            )
            if portal_gate.get("force_override"):
                log.write(f"WARNING: {portal_gate.get('warning')}\n")

            if not portal_gate.get("should_create_batch"):
                gate_warning = portal_gate.get("warning") or portal_gate.get("reason")
                log.write(f"{gate_warning}\n")
                result.status = "inspect_only"
                result.at_vendor_status = "inspect_only"
                result.error_message = gate_warning
                scan_events_only_detail: dict[str, Any] | None = None
                targeted_pending_refresh_detail: dict[str, Any] | None = None
                batch_date = _today_et()

                if not dry_run:
                    scan_events_only_detail = _import_scan_events_when_portal_gate_blocked(
                        conn,
                        cursor,
                        org_id=org_id,
                        paths=paths,
                        scan_script=scan_script,
                        env=env,
                        log=log,
                        batch_date=batch_date,
                    )
                    if scan_events_only_detail:
                        result.scan_events_count = int(
                            scan_events_only_detail.get("scan_rows")
                            or (scan_events_only_detail.get("scan_events_batch") or {}).get(
                                "rows_inserted"
                            )
                            or 0
                        )
                        scan_batch_id = scan_events_only_detail.get("batch_id")
                        if scan_batch_id:
                            result.batch_id = int(scan_batch_id)

                    targeted_pending_refresh_detail = _run_targeted_pending_scan_refresh(
                        conn,
                        cursor,
                        org_id=org_id,
                        upload_batch_id=result.batch_id,
                        batch_date=batch_date,
                        run_type=run_type,
                        targeted_pending_refresh=targeted_pending_refresh,
                        log=log,
                    )

                result.detail = {
                    "portal_confirm_gate": portal_gate,
                    "sync_warning": gate_warning,
                    "scan_events_only_import": scan_events_only_detail,
                    **_build_gate_block_operational_log(portal_gate, scan_events_only_detail),
                }
                log.write(
                    "Operational: "
                    f"portal_confirm_blocked={result.detail.get('portal_confirm_blocked')} "
                    f"scan_events_import_attempted={result.detail.get('scan_events_import_attempted')} "
                    f"scan_events_imported_count={result.detail.get('scan_events_imported_count')} "
                    f"scan_only_batch_id={result.detail.get('scan_only_batch_id')} "
                    f"portal_confirm_block_reason={result.detail.get('portal_confirm_block_reason')}\n"
                )
                if targeted_pending_refresh_detail is not None:
                    result.detail["targeted_pending_scan_refresh"] = targeted_pending_refresh_detail
                conn.commit()
                return result

            if _run_bash_script(scan_script, env, log) != 0:
                raise RuntimeError("Scan-events scrape subprocess failed")

            scan_rows = count_csv_data_rows(paths.scan_events_csv)
            result.scan_events_count = scan_rows

            if scan_rows < 1:
                raise RuntimeError("Scan-events CSV missing or empty after scrape")

            from backend.rinse_combined_upload import commit_rinse_combined_upload
            from backend.rinse_portal_csv import portal_csv_to_orders_df
            from backend.rinse_scan_events_upload import parse_scan_events_csv

            batch_date = _today_et()
            portal_name = f"scheduled-rinse-portal-{_stamp_et()}.csv"
            events_name = f"scheduled-rinse-events-{_stamp_et()}.csv"

            orders_df = portal_csv_to_orders_df(str(paths.portal_csv))
            events_df, warnings = parse_scan_events_csv(str(paths.scan_events_csv))

            if len(orders_df) < 1:
                raise RuntimeError("Portal CSV parsed to zero order rows")

            from backend.rinse_portal_scrape_meta import meta_path_for_portal_csv

            portal_meta_path = meta_path_for_portal_csv(paths.portal_csv)
            draft_payload = commit_rinse_combined_upload(
                conn,
                cursor,
                org_id,
                batch_date,
                portal_name,
                orders_df,
                events_name,
                events_df,
                portal_scrape_meta_path=str(portal_meta_path),
            )
            if not draft_payload.get("portal_absence_allowed"):
                log.write(
                    "WARNING: portal scrape hit max pages — "
                    "MISSING_FROM_LATEST_PORTAL_UPLOAD will be skipped on confirm\n"
                    "(rejected rule applies only on full portal snapshots)\n"
                )
            batch_id = int(draft_payload["batch_id"])
            result.batch_id = batch_id
            log.write(f"Draft batch_id={batch_id} rows_inserted={draft_payload.get('rows_inserted')}\n")

            accepted = _count_accepted_rows(cursor, batch_id)
            from backend.manual_checkout_eligibility import (
                resolve_stale_portal_attention_rows_before_confirm,
            )

            resolve_stale_portal_attention_rows_before_confirm(cursor, org_id, batch_id)
            attention = _count_attention_rows(cursor, batch_id)

            if accepted < 1:
                conn.rollback()
                raise RuntimeError("All portal rows rejected; nothing to apply")

            confirm_payload: dict[str, Any] | None = None
            final_status = "success"

            if attention > 0:
                final_status = "needs_attention"
                result.error_message = (
                    f"Draft batch {batch_id} has {attention} NEEDS_ATTENTION row(s); not auto-confirmed"
                )
                log.write(f"{result.error_message}\n")
            else:
                from backend.upload_batch_confirm import (
                    UploadBatchConfirmError,
                    confirm_upload_batch_core,
                )

                try:
                    confirm_payload = confirm_upload_batch_core(
                        cursor, org_id, batch_id, force_confirm=False
                    )
                    log.write(f"Auto-confirmed batch_id={batch_id}\n")
                except UploadBatchConfirmError as e:
                    conn.rollback()
                    raise RuntimeError(str(e)) from e

            conn.commit()

            off_portal_refresh_detail: dict[str, Any] | None = None
            targeted_pending_refresh_detail: dict[str, Any] | None = None
            if not dry_run and batch_id and final_status in ("success", "needs_attention"):
                targeted_pending_refresh_detail = _run_targeted_pending_scan_refresh(
                    conn,
                    cursor,
                    org_id=org_id,
                    upload_batch_id=int(batch_id),
                    batch_date=batch_date,
                    run_type=run_type,
                    targeted_pending_refresh=targeted_pending_refresh,
                    log=log,
                )

            result.status = final_status
            result.at_vendor_status = final_status
            result.detail = {
                "draft": draft_payload,
                "confirm": confirm_payload,
                "warnings": warnings,
                "attention_count": attention,
                "accepted_count": accepted,
                "portal_confirm_gate": portal_gate,
            }
            if portal_gate.get("force_override"):
                result.detail["sync_warning"] = portal_gate.get("warning")
            if off_portal_refresh_detail is not None:
                result.detail["off_portal_scan_refresh"] = off_portal_refresh_detail
            if targeted_pending_refresh_detail is not None:
                result.detail["targeted_pending_scan_refresh"] = targeted_pending_refresh_detail

        except Exception as e:
            conn.rollback()
            result.status = "failed"
            result.at_vendor_status = "failed"
            result.error_message = str(e)
            log.write(f"ERROR: {e}\n")
            # Best-effort: still pull near-complete pending bags via direct
            # ?q= lookup when the Events CSV scrape/import path fails.
            if not dry_run:
                try:
                    fallback_batch_id = result.batch_id
                    if not fallback_batch_id:
                        cursor.execute(
                            """
                            SELECT batch_id FROM upload_batches
                            WHERE organization_id = %s AND state = 'CONFIRMED'
                            ORDER BY batch_id DESC LIMIT 1
                            """,
                            (org_id,),
                        )
                        brow = cursor.fetchone() or {}
                        fallback_batch_id = brow.get("batch_id") if isinstance(brow, dict) else None
                    targeted_pending_refresh_detail = _run_targeted_pending_scan_refresh(
                        conn,
                        cursor,
                        org_id=org_id,
                        upload_batch_id=int(fallback_batch_id) if fallback_batch_id else None,
                        batch_date=_today_et(),
                        run_type=run_type,
                        targeted_pending_refresh=targeted_pending_refresh,
                        log=log,
                    )
                    if targeted_pending_refresh_detail is not None:
                        result.detail["targeted_pending_scan_refresh"] = (
                            targeted_pending_refresh_detail
                        )
                        result.detail["targeted_refresh_after_scrape_failure"] = True
                except Exception as refresh_exc:
                    log.write(
                        f"Targeted pending scan refresh after scrape failure "
                        f"ERROR (non-fatal): {refresh_exc}\n"
                    )

        if rfv_detail is not None:
            result.detail["ready_for_vendor_sync"] = rfv_detail
            result.ready_for_vendor_status = rfv_status
            if rfv_status == "failed":
                result.ready_for_vendor_error = rfv_error
            if not using_combined:
                result.status = _combine_scheduled_status(
                    result.at_vendor_status or result.status,
                    rfv_status,
                )
                if result.status == "partial_success" and not result.error_message:
                    result.error_message = rfv_error or "Ready for Vendor sync failed"
        if av_presence_detail:
            result.detail["at_vendor_presence_sync"] = av_presence_detail

    finally:
        if own_log and log is not None:
            log.close()
        result.finished_at = datetime.utcnow()
        if using_combined:
            return result
        try:
            finish_scrape_run(
                cursor,
                int(run_id),
                org_id,
                status=result.status,
                started_at=started_at,
                portal_csv_path=str(paths.portal_csv) if paths.portal_csv.is_file() else None,
                scan_events_csv_path=str(paths.scan_tickets_csv)
                if paths.scan_tickets_csv.is_file()
                else None,
                scan_events_events_path=str(paths.scan_events_csv)
                if paths.scan_events_csv.is_file()
                else None,
                portal_rows_count=result.portal_rows_count,
                scan_events_count=result.scan_events_count,
                imported_batch_id=result.batch_id,
                error_message=result.error_message,
                log_path=str(paths.log_path),
                result_json=result.detail,
            )
            conn.commit()
        finally:
            release_scrape_lock(cursor, org_id)
            conn.commit()

    return result


def run_all_scheduled_scrapes(
    conn,
    *,
    organization_ids: list[int] | None = None,
    run_type: str = "scheduled",
    dry_run: bool = False,
) -> list[ScheduledScrapeResult]:
    """
    Process each organization sequentially (v1: no parallel scrapes).
    Per-org MySQL GET_LOCK + rinse_scrape_runs row — one tenant running does not block another.
    """
    if not scheduled_scrape_enabled() and not dry_run:
        raise RuntimeError("RINSE_SCHEDULED_SCRAPE_ENABLED is not set")

    orgs = organization_ids if organization_ids is not None else parse_scheduled_org_ids()
    if not orgs:
        raise RuntimeError("No organization IDs configured (RINSE_SCHEDULED_ORG_IDS)")

    print(
        f"rinse scheduled scrape: {len(orgs)} organization(s) sequential — {orgs}",
        flush=True,
    )

    results: list[ScheduledScrapeResult] = []
    for i, oid in enumerate(orgs, start=1):
        print(f"--- organization {oid} ({i}/{len(orgs)}) ---", flush=True)
        results.append(
            run_rinse_combined_sync_for_org(conn, oid, run_type=run_type, dry_run=dry_run)
        )
    return results
