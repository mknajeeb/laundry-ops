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
from typing import Any
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


def _run_bash_script(script: Path, extra_env: dict[str, str], log: _TeeLog) -> int:
    env = {**os.environ, **extra_env}
    log.write(f"\n--- bash {script} ---\n")
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=scrape_timeout_sec(),
    )
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
        return at_vendor_status if av_ok else "failed"
    if av_ok and rfv_status == "failed":
        return "partial_success"
    if not av_ok:
        return "failed"
    return at_vendor_status


def run_scheduled_scrape_for_org(
    conn,
    organization_id: int,
    *,
    run_type: str = "scheduled",
    dry_run: bool = False,
) -> ScheduledScrapeResult:
    """
    Full pipeline for one organization. Caller owns conn commit/rollback.
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
        result.error_message = f"Missing tenant scripts: {tenant_dir}"
        return result

    paths = build_run_paths(
        org_id, run_type, tenant_slug=slug, rinse_vendor=vendor
    )
    result.paths = paths

    if dry_run:
        result.status = "skipped"
        result.detail = {"dry_run": True, "paths": str(paths.run_dir)}
        return result

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
        result.error_message = lock_reason
        return result

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
    log = _TeeLog(paths.log_path)

    result.at_vendor_status = "failed"
    env: dict[str, str] = {}
    try:
        try:
            log.write(f"Scheduled Rinse scrape org={org_id} vendor={vendor} run_id={run_id}\n")
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

            if _run_bash_script(scan_script, env, log) != 0:
                raise RuntimeError("Scan-events scrape subprocess failed")

            portal_rows = count_csv_data_rows(paths.portal_csv)
            scan_rows = count_csv_data_rows(paths.scan_events_csv)
            result.portal_rows_count = portal_rows
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
                )
            batch_id = int(draft_payload["batch_id"])
            result.batch_id = batch_id
            log.write(f"Draft batch_id={batch_id} rows_inserted={draft_payload.get('rows_inserted')}\n")

            accepted = _count_accepted_rows(cursor, batch_id)
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

            result.status = final_status
            result.at_vendor_status = final_status
            result.detail = {
                "draft": draft_payload,
                "confirm": confirm_payload,
                "warnings": warnings,
                "attention_count": attention,
                "accepted_count": accepted,
            }

        except Exception as e:
            conn.rollback()
            result.status = "failed"
            result.at_vendor_status = "failed"
            result.error_message = str(e)
            log.write(f"ERROR: {e}\n")

        # Step 2: Ready for Vendor presence sync (presence table only; optional per tenant flag).
        try:
            from backend.rinse_presence_scrape import run_presence_scrape_for_org

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
                max_pages=env.get("RINSE_MAX_PAGES") or None,
                log_write=log.write,
            )
            result.ready_for_vendor_status = rfv_result.status
            if rfv_result.status == "failed":
                result.ready_for_vendor_error = rfv_result.error_message
            result.detail["ready_for_vendor_sync"] = {
                "status": rfv_result.status,
                "skipped_reason": rfv_result.skipped_reason,
                "error_message": rfv_result.error_message,
                "rows_found": (rfv_result.stats or {}).get("rows_found"),
                "rows_inserted": (rfv_result.stats or {}).get("rows_inserted"),
                "rows_updated": (rfv_result.stats or {}).get("rows_updated"),
                "rows_missing": (rfv_result.stats or {}).get("rows_missing"),
                "active_rows": (rfv_result.stats or {}).get("active_rows"),
                "stats": rfv_result.stats,
                "scrape_debug": rfv_result.scrape_debug,
                "started_at": rfv_result.started_at.isoformat() if rfv_result.started_at else None,
                "finished_at": rfv_result.finished_at.isoformat() if rfv_result.finished_at else None,
                "duration_seconds": rfv_result.duration_seconds,
            }
        except Exception as rfv_exc:
            result.ready_for_vendor_status = "failed"
            result.ready_for_vendor_error = str(rfv_exc)
            result.detail.setdefault("ready_for_vendor_sync", {})["error_message"] = str(rfv_exc)
            log.write(f"Ready for Vendor sync ERROR: {rfv_exc}\n")

        result.status = _combine_scheduled_status(
            result.at_vendor_status or result.status,
            result.ready_for_vendor_status,
        )
        if result.status == "partial_success" and not result.error_message:
            result.error_message = result.ready_for_vendor_error or "Ready for Vendor sync failed"

    finally:
        log.close()
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
            run_scheduled_scrape_for_org(conn, oid, run_type=run_type, dry_run=dry_run)
        )
    return results
