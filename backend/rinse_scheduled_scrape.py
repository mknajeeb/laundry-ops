"""
Server-side scheduled Rinse scrape: Playwright (Node) + dual CSV import + auto-confirm.

Run via: python -m backend.jobs.run_scheduled_rinse_scrape
Designed for Azure Container Apps scheduled jobs (isolated from laundryops-api).
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from backend.rinse_scrape_runs import (
    MYSQL_LOCK_HELD_REASON,
    acquire_scrape_lock,
    bind_run_lease,
    ensure_scrape_run_terminal,
    finish_scrape_run,
    insert_scrape_run,
    insert_skipped_scrape_run,
    merge_scrape_run_result_json,
    release_scrape_lock,
    scheduled_post_run_cooldown,
    scrape_run_heartbeat_interval_sec,
    scrape_stage_heartbeat,
    touch_scrape_run_progress,
)
from backend.rinse_scrape_lease import (
    FencedWriterError,
    assert_lease_writable,
    take_lease,
)
from backend.rinse_scrape_chain import hard_runtime_ceiling_seconds, stall_seconds
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


def av_single_pass_enabled() -> bool:
    """One Playwright Cleaner Tickets walk (scan-events) feeds portal CSV + presence + scans.

    Production sources are WF+HD ship-window URLs (ET yesterday→today), injected by
    ``_subprocess_env_for_vendor``. Default ON. Set ``RINSE_AV_SINGLE_PASS=0`` to
    restore the legacy triple scrape (presence + portal + scan-events) for emergency
    rollback.
    """
    raw = os.getenv("RINSE_AV_SINGLE_PASS")
    if raw is None or not str(raw).strip():
        return True
    return _truthy(raw)


def _materialize_portal_csv_from_scan_tickets(paths: "ScrapePaths", log: "_TeeLog") -> None:
    """Use scan-events tickets CSV as the portal import CSV (byte-compatible layout)."""
    tickets = paths.scan_tickets_csv
    portal = paths.portal_csv
    if not tickets.is_file():
        raise RuntimeError(f"Scan tickets CSV missing after single-pass scrape: {tickets}")
    shutil.copyfile(tickets, portal)
    tickets_meta = Path(str(tickets) + ".meta.json")
    portal_meta = Path(str(portal) + ".meta.json")
    if tickets_meta.is_file():
        shutil.copyfile(tickets_meta, portal_meta)
    elif not portal_meta.is_file():
        # Minimal natural-end meta so portal absence / confirm gates stay trustworthy.
        row_count = count_csv_data_rows(portal)
        portal_meta.write_text(
            json.dumps(
                {
                    "stopped_reason": "no_next_page_ui",
                    "reached_max_pages": False,
                    "pages_scraped": None,
                    "max_pages_limit": None,
                    "row_count": row_count,
                    "scraped_at": datetime.utcnow().isoformat() + "Z",
                    "page_loaded": True,
                    "session_authenticated": True,
                    "expected_status_in_url": True,
                    "empty_table_detected": row_count == 0,
                    "single_pass_source": "scan-events-tickets",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    log.write(
        f"Single-pass: materialized portal.csv from scan tickets "
        f"({count_csv_data_rows(portal)} rows)\n"
    )


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


def _step1_refresh_succeeded(detail: Mapping[str, Any] | None) -> bool:
    """True when Step-1 refresh already succeeded (or intentionally skipped)."""
    from backend.rinse_step1_scrape_refresh import step1_refresh_succeeded

    return step1_refresh_succeeded(detail)


def _combined_cycle_needs_step1_refresh(
    *,
    dry_run: bool,
    status: str | None,
    detail: Mapping[str, Any] | None,
) -> bool:
    """True when combined-cycle finish must guarantee a Step-1 refresh."""
    if dry_run:
        return False
    if str(status or "") not in ("success", "needs_attention"):
        return False
    # Retry when missing OR prior attempt failed (ok:false must not block retry).
    return not _step1_refresh_succeeded(detail)


def _persist_step1_refresh_diagnostics(
    cursor,
    organization_id: int,
    shift_date_et: date,
    diagnostics: Mapping[str, Any],
) -> None:
    """Merge Step-1 refresh diagnostics into the day workload_meta (compat shim)."""
    from backend.rinse_step1_scrape_refresh import _persist_day_meta_diagnostics

    _persist_day_meta_diagnostics(cursor, organization_id, shift_date_et, diagnostics)


def _mark_step1_refresh_failed_on_result(
    result: "ScheduledScrapeResult",
    refresh_detail: Mapping[str, Any] | None,
) -> None:
    """Surface refresh failure — never report green success while Stage B failed."""
    if _step1_refresh_succeeded({"step1_day_refresh": refresh_detail}):
        return
    err = None
    if isinstance(refresh_detail, dict):
        err = (
            refresh_detail.get("error")
            or refresh_detail.get("step1_refresh_status")
            or refresh_detail.get("status")
        )
    msg = (
        "Portal import succeeded, but Shift Monitor refresh failed. "
        f"Retry refresh. ({err or 'unknown_error'})"
    )
    result.detail["step1_refresh_failed"] = True
    result.detail["step1_day_refresh"] = dict(refresh_detail or {})
    result.detail["step1_day_refresh"]["status"] = (
        result.detail["step1_day_refresh"].get("status") or "failed"
    )
    result.detail["step1_day_refresh"]["step1_refresh_status"] = (
        result.detail["step1_day_refresh"].get("step1_refresh_status") or "FAILED"
    )
    result.detail["step1_day_refresh"]["ok"] = False
    if result.error_message:
        if "Shift Monitor refresh failed" not in str(result.error_message):
            result.error_message = f"{result.error_message}; {msg}"
    else:
        result.error_message = msg
    if str(result.status or "") == "success":
        result.status = "needs_attention"


def _merge_import_incomplete(detail: Mapping[str, Any] | None) -> bool:
    """True when persistent scan merge requires a *global* Stage-B freeze.

    Selective bag-level projection deferral (some bags incomplete, others
    eligible) does not count — those batches still run Stage-B for safe bags.
    """
    if not isinstance(detail, Mapping):
        return False
    from backend.rinse_step1_evidence_gate import merge_flags_indicate_incomplete

    for key in (
        "persistent_merge",
        "persistent_scan_merge",
        "scan_events_only_import",
    ):
        payload = detail.get(key)
        if isinstance(payload, Mapping) and merge_flags_indicate_incomplete(payload):
            return True
    finalize = detail.get("rinse_finalize")
    if isinstance(finalize, Mapping) and not finalize.get("deferred"):
        merge = finalize.get("persistent_merge") or finalize.get("persistent_scan_merge")
        if isinstance(merge, Mapping) and merge_flags_indicate_incomplete(merge):
            return True
    draft = detail.get("draft")
    if isinstance(draft, Mapping):
        merge = draft.get("persistent_scan_merge") or draft.get("persistent_merge")
        if isinstance(merge, Mapping) and merge_flags_indicate_incomplete(merge):
            return True
    confirm = detail.get("confirm")
    if isinstance(confirm, Mapping):
        finalize = confirm.get("rinse_finalize") or {}
        if isinstance(finalize, Mapping) and not finalize.get("deferred"):
            merge = finalize.get("persistent_merge") or finalize.get(
                "persistent_scan_merge"
            )
            if isinstance(merge, Mapping) and merge_flags_indicate_incomplete(merge):
                return True
    return False


def _refresh_open_step1_day_after_scrape(
    conn,
    cursor,
    *,
    org_id: int,
    log: "_TeeLog",
    scrape_batch_id: int | None = None,
    scrape_run_id: int | None = None,
    import_incomplete: bool = False,
    detail: Mapping[str, Any] | None = None,
    portal_presence_run_id: int | None = None,
) -> dict[str, Any]:
    """Compat wrapper — canonical owner is ``refresh_step1_after_scrape``.

    Atomic order: Stage B runs only after portal scrape + scan import commit.
    Incomplete/thinner merges force rebuild deferral (no provisional counts).
    Incomplete state is also persisted against the scan-import batch so later
    Stage-B paths (watchdog/retry/manual) cannot bypass the gate.
    """
    from backend.rinse_step1_evidence_gate import record_evidence_gate_from_merge
    from backend.rinse_step1_scrape_refresh import refresh_step1_after_scrape

    incomplete = bool(import_incomplete) or _merge_import_incomplete(detail)
    merge_payload: Mapping[str, Any] | None = None
    if isinstance(detail, Mapping):
        merge_payload = detail.get("persistent_merge")  # type: ignore[assignment]
        if not isinstance(merge_payload, Mapping):
            merge_payload = detail.get("persistent_scan_merge")  # type: ignore[assignment]
        if not isinstance(merge_payload, Mapping):
            draft = detail.get("draft") if isinstance(detail.get("draft"), Mapping) else {}
            if isinstance(draft, Mapping):
                merge_payload = draft.get("persistent_scan_merge") or draft.get(
                    "persistent_merge"
                )
        if not isinstance(merge_payload, Mapping):
            confirm = detail.get("confirm") if isinstance(detail.get("confirm"), Mapping) else {}
            finalize = (
                confirm.get("rinse_finalize") if isinstance(confirm, Mapping) else None
            )
            if isinstance(finalize, Mapping) and not finalize.get("deferred"):
                merge_payload = finalize.get("persistent_merge") or finalize.get(
                    "persistent_scan_merge"
                )
    if scrape_batch_id is not None:
        try:
            recorded = record_evidence_gate_from_merge(
                cursor,
                organization_id=org_id,
                import_batch_id=scrape_batch_id,
                scrape_run_id=scrape_run_id,
                portal_presence_run_id=portal_presence_run_id,
                merge=merge_payload
                if isinstance(merge_payload, Mapping)
                else {
                    "import_incomplete": incomplete,
                    "timeline_replacement_deferred": incomplete,
                },
                detail=detail if isinstance(detail, Mapping) else None,
            )
            if recorded and log is not None and hasattr(log, "write"):
                log.write(
                    f"Step-1 evidence gate recorded batch={scrape_batch_id} "
                    f"status={recorded.get('gate_status')} "
                    f"allow_persist={recorded.get('allow_persist')}\n"
                )
            try:
                conn.commit()
            except Exception:
                pass
        except Exception as exc:
            if log is not None and hasattr(log, "write"):
                log.write(f"WARNING: evidence gate record failed: {exc}\n")
    if incomplete and log is not None and hasattr(log, "write"):
        log.write(
            "Step-1 Stage B deferred: scan chronology import incomplete / "
            "timeline replacement deferred — retaining last consistent snapshot\n"
        )
    elif (
        isinstance(merge_payload, Mapping)
        and merge_payload.get("has_projection_deferred_bags")
        and log is not None
        and hasattr(log, "write")
    ):
        log.write(
            "Step-1 Stage B selective: "
            f"eligible={len(merge_payload.get('bags_projection_eligible') or [])} "
            f"deferred={len(merge_payload.get('bags_projection_deferred') or [])} "
            "— projecting safe bags only\n"
        )
    return refresh_step1_after_scrape(
        conn,
        cursor,
        organization_id=org_id,
        log=log,
        scrape_run_id=scrape_run_id,
        import_batch_id=scrape_batch_id,
        operations_date_et=_today_et(),
        force_incomplete=incomplete,
        import_incomplete=incomplete,
    )


def _stamp_et() -> str:
    return _now_et().strftime("%Y%m%d_%H%M%S")


def _run_wf_canonical_terminal_projection(
    conn,
    cursor,
    *,
    org_id: int,
    log: "_TeeLog | None",
    portal_csv_path: Path | None,
    portal_scrape_meta_path: Path | None = None,
    shift_date_et: date | None = None,
) -> dict[str, Any]:
    """Terminal canonical lifecycle + day_bags projection after finalize/Stage-B."""
    try:
        from backend.rinse_wf_service_cycle import (
            finalize_wf_canonical_lifecycle_terminal,
            is_wf_canonical_lifecycle_enabled,
        )

        if not is_wf_canonical_lifecycle_enabled(cursor, org_id):
            return {"skipped": True, "reason": "canonical_disabled"}
        if log is not None and hasattr(log, "write"):
            log.write(
                "WF canonical terminal projection start "
                f"org={org_id} portal_csv={portal_csv_path}\n"
            )
        out = finalize_wf_canonical_lifecycle_terminal(
            cursor,
            org_id,
            portal_csv_path=portal_csv_path,
            portal_scrape_meta_path=portal_scrape_meta_path,
            shift_date_et=shift_date_et or _today_et(),
        )
        conn.commit()
        if log is not None and hasattr(log, "write"):
            log.write(f"WF canonical terminal projection: {out}\n")
        return out
    except Exception as exc:
        if log is not None and hasattr(log, "write"):
            log.write(f"WARNING: WF canonical terminal projection failed: {exc}\n")
        return {"ok": False, "error": str(exc)}


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
    lease_generation: int | None = None


class _TeeLog:
    def __init__(self, path: Path):
        self._path = path
        self._file = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._stdout_q: queue.Queue[str | None] = queue.Queue(maxsize=500)
        self._stdout_thread = threading.Thread(
            target=self._drain_stdout, name="rinse-tee-stdout", daemon=True
        )
        self._stdout_thread.start()

    def _drain_stdout(self) -> None:
        """Never let a blocked ACA log pipe freeze scrape/Stage-B."""
        while True:
            msg = self._stdout_q.get()
            if msg is None:
                return
            try:
                sys.stdout.write(msg)
                sys.stdout.flush()
            except Exception:
                pass

    def write(self, msg: str) -> None:
        with self._lock:
            try:
                self._file.write(msg)
                self._file.flush()
            except Exception:
                pass
            try:
                self._stdout_q.put_nowait(msg)
            except queue.Full:
                pass

    def close(self) -> None:
        try:
            self._stdout_q.put_nowait(None)
        except queue.Full:
            pass
        try:
            self._file.close()
        except Exception:
            pass


def _run_bash_script(
    script: Path,
    extra_env: dict[str, str],
    log: _TeeLog,
    *,
    timeout_sec: int | None = None,
    heartbeat_fn: Callable[[], None] | None = None,
    progress_fn: Callable[[str], None] | None = None,
    supervisor_tick_fn: Callable[[], None] | None = None,
    hard_deadline_mono: float | None = None,
    outcome_out: list[dict[str, Any]] | None = None,
) -> int:
    from backend.rinse_scrape_subprocess_outcome import classify_subprocess_failure

    env = {**os.environ, **extra_env}
    log.write(f"\n--- bash {script} ---\n")
    timeout = int(timeout_sec) if timeout_sec is not None else combined_phase_timeout_sec()
    hb_interval = scrape_run_heartbeat_interval_sec()
    sup_interval = None
    if supervisor_tick_fn is not None:
        from backend.rinse_scrape_liveness import scrape_supervisor_heartbeat_interval_sec

        sup_interval = scrape_supervisor_heartbeat_interval_sec()
    started = time.monotonic()
    last_hb = started
    last_sup = started
    last_progress = [started]
    last_log_lines: list[str] = []
    stall_after = stall_seconds()
    proc = subprocess.Popen(
        ["bash", str(script)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    log.write(f"portal_subprocess pid={proc.pid}\n")

    def _pump(stream) -> None:
        if stream is None:
            return
        for line in stream:
            log.write(line)
            last_progress[0] = time.monotonic()
            last_log_lines.append(line.rstrip("\n"))
            if len(last_log_lines) > 80:
                del last_log_lines[:-80]
            if progress_fn:
                try:
                    progress_fn(line)
                except Exception:
                    pass

    t_out = threading.Thread(target=_pump, args=(proc.stdout,), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr,), daemon=True)
    t_out.start()
    t_err.start()
    timed_out = False
    stalled = False
    killed_by_parent = False

    def _stall_watchdog() -> None:
        nonlocal stalled, killed_by_parent
        while proc.poll() is None:
            if (time.monotonic() - last_progress[0]) >= stall_after:
                stalled = True
                killed_by_parent = True
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            time.sleep(2)

    t_watch = threading.Thread(target=_stall_watchdog, daemon=True)
    t_watch.start()
    try:
        while proc.poll() is None:
            now_m = time.monotonic()
            elapsed = now_m - started
            if elapsed >= timeout:
                timed_out = True
                killed_by_parent = True
                proc.kill()
                proc.wait(timeout=30)
                break
            if hard_deadline_mono is not None and now_m >= hard_deadline_mono:
                timed_out = True
                killed_by_parent = True
                proc.kill()
                proc.wait(timeout=30)
                break
            if stalled:
                proc.wait(timeout=30)
                break
            if (now_m - last_progress[0]) >= stall_after:
                stalled = True
                killed_by_parent = True
                proc.kill()
                proc.wait(timeout=30)
                break
            if heartbeat_fn and (now_m - last_hb) >= hb_interval:
                try:
                    heartbeat_fn()
                except FencedWriterError:
                    killed_by_parent = True
                    proc.kill()
                    proc.wait(timeout=30)
                    raise
                except Exception:
                    pass
                last_hb = time.monotonic()
            if (
                supervisor_tick_fn is not None
                and sup_interval is not None
                and (now_m - last_sup) >= sup_interval
            ):
                try:
                    supervisor_tick_fn()
                except Exception:
                    pass
                last_sup = time.monotonic()
            time.sleep(2)
    except FencedWriterError:
        raise
    except Exception:
        killed_by_parent = True
        proc.kill()
        raise
    if proc.poll() is None:
        proc.wait(timeout=30)
    t_out.join(timeout=30)
    t_err.join(timeout=30)
    elapsed_sec = round(time.monotonic() - started, 1)
    rc = -2 if stalled else (-1 if timed_out else int(proc.returncode or 0))
    if stalled:
        log.write(f"exit code: stalled after {stall_after}s without progress\n")
    elif timed_out:
        log.write(f"exit code: timeout after {timeout}s\n")
    else:
        log.write(f"exit code: {proc.returncode}\n")
    outcome = classify_subprocess_failure(
        returncode=rc,
        timed_out=timed_out,
        stalled=stalled,
        killed_by_parent=killed_by_parent,
        last_log_lines=last_log_lines,
        elapsed_sec=elapsed_sec,
    )
    outcome["pid"] = proc.pid
    outcome["script"] = str(script)
    if outcome.get("failure_class"):
        log.write(
            "portal_subprocess_outcome: "
            f"class={outcome.get('failure_class')} "
            f"signal={outcome.get('signal')} "
            f"elapsed_sec={elapsed_sec}\n"
        )
    if outcome_out is not None:
        outcome_out.append(outcome)
    return rc


def _subprocess_env_for_vendor(
    organization_id: int,
    vendor: str,
    paths: ScrapePaths,
    *,
    organization_slug: str | None = None,
    organization_name: str | None = None,
) -> dict[str, str]:
    from backend.rinse_bag_export_runner import scraper_dir
    from backend.rinse_ship_window_tickets_urls import build_scheduled_wf_hd_source_urls

    _, vendor_env = rinse_scrape_env_for_organization(
        int(organization_id),
        organization_slug=organization_slug,
        organization_name=organization_name,
        override_vendor=vendor,
        scraper_dir=scraper_dir(),
    )
    day = _today_label_et()
    tenant_data = tenant_data_dir(vendor)
    # Production scheduled sources: WF + HD with ET yesterday→today ship dates.
    # Overrides any Azure/legacy status=at_vendor RINSE_*_TICKETS_URL so the
    # scheduled job cannot accidentally scrape the old single At Vendor list.
    sources = build_scheduled_wf_hd_source_urls()
    source_urls_json = json.dumps(
        [{"label": s["label"], "url": s["url"]} for s in sources]
    )
    out = {
        **vendor_env,
        "RINSE_CSV_LAYOUT": "portal",
        "RINSE_TENANT_DATA_DIR": str(tenant_data),
        "OUTPUT_CSV": str(paths.portal_csv),
        "OUTPUT_SCAN_TICKETS_CSV": str(paths.scan_tickets_csv),
        "OUTPUT_SCAN_EVENTS_CSV": str(paths.scan_events_csv),
        "RINSE_TICKETS_SOURCE_URLS": source_urls_json,
        # First source also set as RINSE_TICKETS_URL for login next= fallback.
        "RINSE_TICKETS_URL": str(sources[0]["url"]),
        # Full traverse every run: no early-stop / no bag-set pagination abort.
        "RINSE_FULL_TRAVERSE": "1",
        "RINSE_PORTAL_EARLY_STOP": "0",
        "RINSE_BLOCK_HEAVY_ASSETS": "1",
        # Match proven ~1.17s/ticket laptop path: short settles + toggle-collapse.
        # Do not inherit inflated Azure/App Service settle waits.
        "RINSE_EXPAND_SETTLE_MS": "300",
        "RINSE_VENDORINLINE_SETTLE_MS": "50",
        "RINSE_PAGE_SETTLE_MS": "300",
        "RINSE_BAG_DETAILS_SETTLE_MS": "150",
        "RINSE_BAG_DOM_WAIT_MS": "200",
        "RINSE_BAG_DOM_POLL_MS": "40",
        "RINSE_TABLE_WAIT_MS": "200",
        "RINSE_TABLE_AFTER_MS": "40",
        "RINSE_TABLE_WHEEL_STEPS": "0",
        "RINSE_ROW_GAP_MS": "0",
        "RINSE_SCAN_TABLE_SETTLE_MS": "0",
        "RINSE_COLLAPSE_SETTLE_MS": "120",
        "RINSE_FAST_COLLAPSE": "1",
        "RINSE_SHOW_BAG_WAIT_MS": "1200",
    }
    # Tenant scripts default to dated names under output/; explicit paths win.
    if not (os.getenv("RINSE_MAX_PAGES") or "").strip():
        tenant_env = tenant_script_dir(vendor) / ".env"
        if tenant_env.is_file():
            for line in tenant_env.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("RINSE_MAX_PAGES=") and "=" in line:
                    out.setdefault("RINSE_MAX_PAGES", line.split("=", 1)[1].strip())
    # Ship-window lists are small (~5 pages); keep headroom without early-stop.
    out.setdefault("RINSE_MAX_PAGES", "40")
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
    lease_generation: int | None = None


def _resolve_combined_cycle_status(
    *,
    rfv_status: str | None,
    av_presence_status: str | None,
    import_status: str | None,
) -> str:
    """Map step outcomes to combined cycle status labels."""
    # RFV is retired from scheduled runtime — disabled is the only expected RFV outcome.
    if rfv_status not in ("success", "dry_run", "disabled"):
        return "RFV_FAILED"
    # pending_single_pass: presence applied inside import; import outcome is authoritative.
    if av_presence_status not in ("success", "dry_run", "pending_single_pass"):
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


def _fmt_et_wall(dt: datetime | None) -> str | None:
    if dt is None or not isinstance(dt, datetime):
        return None
    naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
    return naive.isoformat(sep=" ", timespec="seconds") + " ET"


def _fmt_system_utc_as_et(dt: datetime | None) -> str | None:
    from backend.rinse_scan_time import system_datetime_to_et

    et = system_datetime_to_et(dt)
    if et is None:
        return None
    return et.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds") + " ET"


def _newest_db_scan_et(cursor, organization_id: int) -> datetime | None:
    try:
        cursor.execute(
            """
            SELECT MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
            """,
            (int(organization_id),),
        )
        row = cursor.fetchone() or {}
        mx = row.get("mx") if isinstance(row, dict) else None
        return mx if isinstance(mx, datetime) else None
    except Exception:
        return None


def _newest_source_scan_et(events_df: Any) -> datetime | None:
    try:
        series = events_df["scanned_at_parsed"]
        mx = series.max() if hasattr(series, "max") else None
        if mx is None:
            return None
        try:
            import pandas as pd

            if pd.isna(mx):
                return None
        except Exception:
            pass
        if isinstance(mx, datetime):
            return mx.replace(tzinfo=None) if mx.tzinfo else mx
        return None
    except Exception:
        return None


def _source_to_db_lag_seconds(
    import_available_utc: datetime | None,
    source_scan_et: datetime | None,
) -> int | None:
    """DB availability (UTC system) minus authoritative source scan (ET wall)."""
    if import_available_utc is None or source_scan_et is None:
        return None
    from backend.rinse_scan_time import system_datetime_to_et

    import_et = system_datetime_to_et(import_available_utc)
    if import_et is None:
        return None
    import_naive = import_et.replace(tzinfo=None)
    src = source_scan_et.replace(tzinfo=None) if source_scan_et.tzinfo else source_scan_et
    return int((import_naive - src).total_seconds())


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
    log=None,
) -> None:
    detail = dict(result.detail or {})
    detail["sync_cycle"] = dict(sync_cycle)
    if ready_for_vendor_sync:
        detail["ready_for_vendor_sync"] = dict(ready_for_vendor_sync)
    if at_vendor_presence_sync:
        detail["at_vendor_presence_sync"] = dict(at_vendor_presence_sync)
    result.detail = detail
    result.finished_at = datetime.utcnow()
    _chain_boundary(
        log,
        "terminal_db_update_start",
        run_id=result.run_id,
        status=result.status,
    )
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
    _chain_boundary(
        log,
        "terminal_db_update_complete",
        run_id=result.run_id,
        status=result.status,
        finished_at=result.finished_at.isoformat() + "Z" if result.finished_at else None,
    )


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
    from backend.rinse_presence_scrape import (
        PresenceScrapeResult,
        rfv_scrape_enabled,
        run_presence_scrape_for_org,
    )

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

    # Sequential chain: scheduled runs are eligible immediately (GET_LOCK + lease).
    # Manual runs share the same overlap protection.
    cooldown = scheduled_post_run_cooldown(cursor, org_id, run_type=run_type)
    if not cooldown.get("ok_to_run"):
        next_run = cooldown.get("next_run_at")
        reason = cooldown.get("reason") or "post_run_cooldown"
        print(
            f"rinse scrape org={org_id} deferred ({reason})",
            flush=True,
        )
        result.status = "skipped"
        result.error_message = reason
        result.detail = {
            "sync_cycle": {
                "cycle_status": "skipped",
                "failure_message": reason,
                "skip_reason": "post_run_cooldown",
                "last_finished_at": (
                    cooldown["last_finished_at"].isoformat() + "Z"
                    if cooldown.get("last_finished_at")
                    else None
                ),
                "next_run_at": (
                    next_run.isoformat() + "Z" if next_run else None
                ),
                "remaining_seconds": cooldown.get("remaining_seconds"),
            }
        }
        # No DB skip row — ACA may poll frequently; avoid flooding rinse_scrape_runs.
        return result

    acquired, lock_reason = acquire_scrape_lock(cursor, org_id)
    lock_acquired_at = datetime.utcnow()
    conn.commit()
    if not acquired:
        skip_reason = (
            CYCLE_ALREADY_RUNNING
            if (
                "still active" in (lock_reason or "")
                or lock_reason == MYSQL_LOCK_HELD_REASON
            )
            else lock_reason
        )
        is_scheduled = str(run_type or "scheduled").strip().lower() == "scheduled"
        if not is_scheduled:
            insert_skipped_scrape_run(
                cursor,
                org_id,
                tenant_slug=slug,
                rinse_vendor=vendor,
                run_type=run_type,
                reason=skip_reason or CYCLE_ALREADY_RUNNING,
            )
            conn.commit()
        else:
            print(
                f"rinse scrape org={org_id} deferred ({skip_reason or CYCLE_ALREADY_RUNNING})",
                flush=True,
            )
        result.status = "skipped"
        result.error_message = skip_reason or CYCLE_ALREADY_RUNNING
        result.detail = {
            "sync_cycle": {
                "cycle_status": "skipped",
                "failure_message": result.error_message,
                "skip_reason": skip_reason or CYCLE_ALREADY_RUNNING,
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
    gen = take_lease(cursor, org_id, run_id=run_id)
    bind_run_lease(cursor, run_id, org_id, gen)
    result.lease_generation = gen
    conn.commit()
    result.run_id = run_id
    log = _TeeLog(paths.log_path)
    started_at = cycle_started_at
    result.detail["ingestion_lifecycle"] = {
        "scrape_run_id": run_id,
        "cron_scheduled_et": _fmt_system_utc_as_et(cycle_started_at),
        "main_lock_acquired_et": _fmt_system_utc_as_et(lock_acquired_at),
    }
    touch_scrape_run_progress(
        cursor, run_id, org_id, stage="starting", detail_patch=result.detail,
        lease_generation=gen,
    )
    conn.commit()

    rfv_detail: dict[str, Any] = {}
    av_presence_detail: dict[str, Any] = {}
    import_result: ScheduledScrapeResult | None = None
    delay_seconds: int | None = None

    run_terminal = False
    try:
        log.write(
            f"Combined sync cycle run_id={run_id} org={org_id} vendor={vendor} run_type={run_type}\n"
        )
        if str(os.getenv("RINSE_SCRAPE_FORCE_FAIL") or "").strip() in ("1", "true", "yes"):
            raise RuntimeError("forced ordinary failure (self-heal probe)")
        if str(os.getenv("RINSE_SCRAPE_FORCE_STALL") or "").strip() in ("1", "true", "yes"):
            # Hold the org lock with no further heartbeats so an external
            # watchdog/replacement execution can prove in-lock stall recovery.
            log.write(
                "FORCE_STALL: holding scrape lock without heartbeats "
                "(self-heal stall probe)\n"
            )
            print("FORCE_STALL holding lock without heartbeats", flush=True)
            while True:
                time.sleep(3600)
        # RFV is retired from scheduled/runtime cycles. Historical tables/code remain
        # dormant; do not scrape, wait on, or retry Ready for Vendor here.
        log.write(
            f"Ready for Vendor sync skipped org={org_id}: retired from scheduled runtime "
            f"(RFV_SCRAPE_ENABLED={os.getenv('RFV_SCRAPE_ENABLED') or 'unset'})\n"
        )
        rfv_result = PresenceScrapeResult(
            organization_id=org_id,
            portal_status="ready_for_vendor",
            status="disabled",
            skipped_reason="RFV retired from scheduled At Vendor sync",
            started_at=cycle_started_at,
            finished_at=datetime.utcnow(),
        )
        rfv_detail = build_ready_for_vendor_sync_detail(rfv_result)
        result.ready_for_vendor_status = "disabled"

        single_pass = av_single_pass_enabled()
        if single_pass:
            log.write(
                f"Cleaner Tickets single-pass enabled org={org_id}: "
                "WF+HD ship-window scan-events walk → portal CSV + presence + scans\n"
            )
            # Presence is applied inside run_scheduled_scrape_for_org after tickets land.
            av_presence_result = PresenceScrapeResult(
                organization_id=org_id,
                portal_status=PORTAL_STATUS_AT_VENDOR,
                status="pending_single_pass",
                started_at=datetime.utcnow(),
            )
            av_presence_detail = {}
            delay_seconds = 0
        else:
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
            if isinstance(rfv_result.finished_at, datetime) and isinstance(
                av_presence_result.started_at, datetime
            ):
                delay_seconds = max(
                    0,
                    int(
                        (
                            av_presence_result.started_at - rfv_result.finished_at
                        ).total_seconds()
                    ),
                )
            print(
                f"At Vendor presence sync done org={org_id} status={av_presence_result.status} "
                f"rows_found={(av_presence_result.stats or {}).get('rows_found')} "
                f"delay_seconds={delay_seconds}",
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
                    log=log,
                )
                return result

        combined_ctx = _CombinedCycleContext(
            run_id=int(run_id),
            paths=paths,
            log=log,
            started_at=started_at,
            lease_generation=result.lease_generation,
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
            av_presence_detail=av_presence_detail or None,
            # Targeted refresh runs post-lock after the main cycle is terminal.
            targeted_pending_refresh=False,
        )
        result.status = import_result.status
        result.at_vendor_status = import_result.at_vendor_status or import_result.status
        result.batch_id = import_result.batch_id
        result.portal_rows_count = import_result.portal_rows_count
        result.scan_events_count = import_result.scan_events_count
        result.error_message = import_result.error_message
        prior_life = dict((result.detail or {}).get("ingestion_lifecycle") or {})
        result.detail = dict(import_result.detail or {})
        import_life = dict(result.detail.get("ingestion_lifecycle") or {})
        life = {**prior_life, **import_life}
        life["scrape_run_id"] = run_id
        life["batch_id"] = result.batch_id
        # Prefer presence detail produced inside single-pass import when present.
        if isinstance(result.detail.get("at_vendor_presence_sync"), Mapping):
            av_presence_detail = dict(result.detail["at_vendor_presence_sync"])
        if isinstance(av_presence_detail, Mapping) and av_presence_detail.get("run_id") is not None:
            life["presence_run_id"] = av_presence_detail.get("run_id")
        result.detail["ingestion_lifecycle"] = life

        if single_pass:
            av_presence_status = (av_presence_detail or {}).get("status") or "pending_single_pass"
        else:
            av_presence_status = av_presence_result.status
        cycle_status = _resolve_combined_cycle_status(
            rfv_status=rfv_result.status,
            av_presence_status=av_presence_status,
            import_status=import_result.status,
        )
        confirm_payload = (import_result.detail or {}).get("confirm") or {}
        draft_payload = (import_result.detail or {}).get("draft") or {}
        finalize_payload = confirm_payload.get("rinse_finalize") or {}
        merge_payload = {}
        if isinstance(finalize_payload, Mapping) and not finalize_payload.get("deferred"):
            merge_payload = finalize_payload.get("persistent_merge") or {}
        if not merge_payload and isinstance(draft_payload, Mapping):
            merge_payload = draft_payload.get("persistent_scan_merge") or {}
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
        # Guarantee: every successful At-Vendor import rebuilds today's OPEN
        # Step-1 snapshot via the production backfill path (no duplicate logic).
        if _combined_cycle_needs_step1_refresh(
            dry_run=dry_run, status=result.status, detail=result.detail
        ):
            # Order: portal scrape → scan import commit → validate → Stage B.
            result.detail["persistent_merge"] = merge_payload
            presence_run_id = None
            if isinstance(av_presence_detail, Mapping):
                presence_run_id = av_presence_detail.get("run_id")
            result.detail["step1_day_refresh"] = _refresh_open_step1_day_after_scrape(
                conn,
                cursor,
                org_id=org_id,
                log=log,
                scrape_batch_id=result.batch_id,
                scrape_run_id=result.run_id or run_id,
                portal_presence_run_id=int(presence_run_id) if presence_run_id else None,
                detail={
                    **(result.detail or {}),
                    "persistent_merge": merge_payload,
                },
            )
            result.detail["step1_day_refresh_via"] = "combined_cycle_guarantee"
            if not dry_run and str(result.status or "") in ("success", "needs_attention"):
                # Import path already ran publish-stage WF terminal projection in-lock.
                # Do not run it a second time (was doubling the hang risk).
                if not isinstance(result.detail.get("wf_canonical_terminal"), dict):
                    result.detail["wf_canonical_terminal"] = _run_wf_canonical_terminal_projection(
                        conn,
                        cursor,
                        org_id=org_id,
                        log=log,
                        portal_csv_path=paths.portal_csv,
                        portal_scrape_meta_path=Path(str(paths.portal_csv) + ".meta.json"),
                    )
        if not dry_run and str(result.status or "") in ("success", "needs_attention"):
            _mark_step1_refresh_failed_on_result(
                result, result.detail.get("step1_day_refresh")
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
            log=log,
        )
        run_terminal = True
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
        try:
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
                log=log,
            )
            run_terminal = True
        except Exception as finish_exc:
            log.write(f"Combined sync finish ERROR: {finish_exc}\n")
    finally:
        if result.run_id and not run_terminal:
            try:
                term_status = str(result.status or "")
                if term_status in ("", "running", "skipped"):
                    term_status = "failed"
                ensure_scrape_run_terminal(
                    cursor,
                    int(result.run_id),
                    org_id,
                    status=term_status,
                    error_message=result.error_message
                    or "cycle ended without finish_scrape_run",
                    result_json=dict(result.detail or {}),
                )
                conn.commit()
            except Exception as term_exc:
                try:
                    log.write(f"Combined sync terminalize ERROR: {term_exc}\n")
                except Exception:
                    pass
        try:
            log.close()
        except Exception:
            pass
        _chain_boundary(log, "lock_release_start", run_id=result.run_id, org_id=org_id)
        release_scrape_lock(cursor, org_id)
        _chain_boundary(log, "lock_release_complete", run_id=result.run_id, org_id=org_id)
        try:
            if result.run_id:
                life = dict((result.detail or {}).get("ingestion_lifecycle") or {})
                life["main_lock_released_et"] = _fmt_system_utc_as_et(datetime.utcnow())
                life["scrape_terminal_status"] = result.status
                life["scrape_terminal_et"] = _fmt_system_utc_as_et(datetime.utcnow())
                result.detail["ingestion_lifecycle"] = life
                merge_scrape_run_result_json(
                    cursor,
                    int(result.run_id),
                    org_id,
                    {"ingestion_lifecycle": life},
                )
        except Exception:
            pass
        conn.commit()

    # Post-lock: best-effort targeted refresh must not hold the main scrape lock.
    if not dry_run and result.status not in ("skipped",):
        post_log = _TeeLog(paths.log_path)
        try:
            _run_post_lock_or_abandon(
                conn,
                cursor,
                org_id=org_id,
                result=result,
                run_type=run_type,
                targeted_pending_refresh=targeted_pending_refresh,
                log=post_log,
                after_main_failure=str(result.status or "")
                not in ("success", "needs_attention", "inspect_only"),
            )
        finally:
            post_log.close()
    return result


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


def _targeted_refresh_inserted_events(summary: Mapping[str, Any] | None) -> int:
    if not isinstance(summary, Mapping):
        return 0
    for key in ("missing_scans_imported", "events_inserted"):
        try:
            n = int(summary.get(key) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n
    return 0


def _targeted_refresh_needs_reproject(summary: Mapping[str, Any] | None) -> bool:
    """True only when targeted work committed new scan evidence worth a Stage-B pass."""
    if not isinstance(summary, Mapping):
        return False
    if _targeted_refresh_inserted_events(summary) > 0:
        return True
    try:
        if int(summary.get("bags_completed_after_refresh") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    backfill = summary.get("near_complete_wf_weight_backfill")
    if isinstance(backfill, Mapping):
        try:
            if int(backfill.get("applied") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _rinse_finalize_deferred(detail: Mapping[str, Any] | None) -> bool:
    """True when scheduled confirm skipped in-process finalize for post-lock."""
    if not isinstance(detail, Mapping):
        return False
    if detail.get("rinse_finalize_deferred"):
        return True
    confirm = detail.get("confirm")
    if not isinstance(confirm, Mapping):
        return False
    finalize = confirm.get("rinse_finalize")
    return isinstance(finalize, Mapping) and bool(finalize.get("deferred"))


def _chain_boundary(log, name: str, **fields: Any) -> None:
    """Emit an unambiguous ET/UTC boundary stamp for successor-gap debugging."""
    now = datetime.utcnow()
    extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    line = (
        f"CHAIN_BOUNDARY {name} utc={now.isoformat()}Z "
        f"et={_fmt_system_utc_as_et(now)}"
        + (f" {extra}" if extra else "")
        + "\n"
    )
    try:
        if log is not None:
            log.write(line)
    except Exception:
        pass
    print(line.rstrip(), flush=True)


def _run_in_lock_rinse_finalize(
    conn,
    cursor,
    *,
    org_id: int,
    batch_id: int,
    run_id: int | None,
    lease_generation: int | None,
    log,
    prior_persistent_merge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registry/folding finalize required before terminal success (in-lock)."""
    from backend.rinse_upload_finalize import (
        fetch_accepted_portal_rows_for_finalize,
        finalize_rinse_after_batch_confirm,
    )

    _chain_boundary(log, "finalize_start", batch_id=batch_id, run_id=run_id)
    if run_id:
        touch_scrape_run_progress(
            cursor,
            int(run_id),
            org_id,
            stage="finalizing",
            lease_generation=lease_generation,
        )
        conn.commit()
        if lease_generation is not None:
            assert_lease_writable(cursor, org_id, int(lease_generation))
    rows = fetch_accepted_portal_rows_for_finalize(cursor, batch_id)
    if run_id:
        touch_scrape_run_progress(
            cursor,
            int(run_id),
            org_id,
            stage="finalizing",
            lease_generation=lease_generation,
        )
        conn.commit()

    with scrape_stage_heartbeat(
        run_id,
        org_id,
        stage="finalizing",
        lease_generation=lease_generation,
    ):
        payload = finalize_rinse_after_batch_confirm(
            cursor,
            org_id,
            batch_id,
            accepted_portal_rows=rows,
            source_filename=f"batch_confirm_{batch_id}",
            prior_persistent_merge=prior_persistent_merge,
        )
        conn.commit()
    if run_id:
        touch_scrape_run_progress(
            cursor,
            int(run_id),
            org_id,
            stage="finalizing",
            lease_generation=lease_generation,
        )
        conn.commit()
    merge = payload.get("persistent_merge") or {}
    log.write(
        "In-lock rinse finalize: "
        f"events_inserted={merge.get('events_inserted')} "
        f"bags_merged={merge.get('bags_merged')} "
        f"skipped_redundant_draft_merge={bool(merge.get('skipped_redundant_draft_merge'))} "
        f"draft_events_inserted={merge.get('draft_events_inserted')}\n"
    )
    _chain_boundary(log, "finalize_complete", batch_id=batch_id, run_id=run_id)
    return payload


def _run_post_lock_rinse_finalize(
    conn,
    cursor,
    *,
    org_id: int,
    batch_id: int,
    log,
) -> dict[str, Any]:
    """Best-effort registry/folding finalize after Stage-B + main lock release."""
    from backend.rinse_upload_finalize import (
        fetch_accepted_portal_rows_for_finalize,
        finalize_rinse_after_batch_confirm,
    )

    rows = fetch_accepted_portal_rows_for_finalize(cursor, batch_id)
    payload = finalize_rinse_after_batch_confirm(
        cursor,
        org_id,
        batch_id,
        accepted_portal_rows=rows,
        source_filename=f"batch_confirm_{batch_id}",
    )
    conn.commit()
    log.write(
        "Post-lock rinse finalize: "
        f"events_inserted={(payload.get('persistent_merge') or {}).get('events_inserted')} "
        f"bags_merged={(payload.get('persistent_merge') or {}).get('bags_merged')}\n"
    )
    return payload


def _post_lock_targeted_enabled(run_type: str) -> bool:
    """Scheduled continuous chain skips post-lock targeted by default.

    Finalize/Stage-B already completed in-lock before terminal success. Optional
    targeted pending refresh must not delay the next cycle.
    """
    if str(os.getenv("RINSE_POST_LOCK_TARGETED_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    return str(run_type or "scheduled").strip().lower() != "scheduled"


def _run_post_lock_or_abandon(
    conn,
    cursor,
    *,
    org_id: int,
    result: ScheduledScrapeResult,
    run_type: str,
    targeted_pending_refresh: bool | None,
    log,
    after_main_failure: bool,
) -> None:
    """Best-effort post-lock only. Never blocks healthy successor/next cycle.

    Finalize is no longer deferred here — required work finished in-lock.
    """
    if not _post_lock_targeted_enabled(run_type):
        try:
            log.write(
                "Post-lock targeted refresh skipped "
                "(scheduled continuous chain; finalize already in-lock)\n"
            )
        except Exception:
            pass
        _chain_boundary(log, "post_lock_skipped")
        return
    _chain_boundary(log, "post_lock_targeted_start")
    try:
        _run_post_lock_targeted_refresh(
            conn,
            cursor,
            org_id=org_id,
            result=result,
            run_type=run_type,
            targeted_pending_refresh=targeted_pending_refresh,
            log=log,
            after_main_failure=after_main_failure,
        )
    except Exception as exc:
        try:
            log.write(f"Post-lock targeted refresh ERROR (non-fatal): {exc}\n")
        except Exception:
            pass
    _chain_boundary(log, "post_lock_targeted_complete")


def _run_post_lock_targeted_refresh(
    conn,
    cursor,
    *,
    org_id: int,
    result: ScheduledScrapeResult,
    run_type: str,
    targeted_pending_refresh: bool | None,
    log,
    after_main_failure: bool = False,
) -> None:
    """Best-effort targeted refresh after the main scrape is terminal and unlocked.

    Must not reopen ``rinse_scrape_runs`` as running or change a successful main
    status on targeted failure. New scan events may trigger a separate Today-only
    Stage-B reprojection after commit.
    """
    if log is None:
        return

    main_status_before = result.status
    upload_batch_id = result.batch_id
    post_lock_patch: dict[str, Any] = {}
    if _rinse_finalize_deferred(result.detail) and upload_batch_id:
        try:
            finalize_payload = _run_post_lock_rinse_finalize(
                conn,
                cursor,
                org_id=org_id,
                batch_id=int(upload_batch_id),
                log=log,
            )
            post_lock_patch["rinse_finalize_post_lock"] = {
                **dict(finalize_payload or {}),
                "post_lock": True,
            }
        except Exception as finalize_exc:
            post_lock_patch["rinse_finalize_post_lock"] = {
                "ok": False,
                "error": str(finalize_exc),
                "post_lock": True,
            }
            log.write(
                f"Post-lock rinse finalize ERROR (non-fatal): {finalize_exc}\n"
            )
        result.detail = {**(result.detail or {}), **post_lock_patch}
        result.status = main_status_before
        if result.run_id:
            try:
                merge_scrape_run_result_json(
                    cursor, int(result.run_id), int(org_id), post_lock_patch
                )
                conn.commit()
            except Exception as merge_exc:
                log.write(
                    f"WARNING: could not persist post-lock finalize detail: {merge_exc}\n"
                )

    upload_batch_id = result.batch_id
    if after_main_failure and not upload_batch_id:
        try:
            cursor.execute(
                """
                SELECT batch_id FROM upload_batches
                WHERE organization_id = %s AND state = 'CONFIRMED'
                ORDER BY batch_id DESC LIMIT 1
                """,
                (org_id,),
            )
            brow = cursor.fetchone() or {}
            upload_batch_id = brow.get("batch_id") if isinstance(brow, dict) else None
        except Exception:
            upload_batch_id = None

    main_status_before = result.status
    try:
        summary = _run_targeted_pending_scan_refresh(
            conn,
            cursor,
            org_id=org_id,
            upload_batch_id=int(upload_batch_id) if upload_batch_id else None,
            batch_date=_today_et(),
            run_type=run_type,
            targeted_pending_refresh=targeted_pending_refresh,
            log=log,
        )
    except Exception as exc:
        summary = {
            "targeted_refresh_ran": False,
            "error": str(exc),
            "post_lock": True,
        }
        log.write(f"Post-lock targeted pending refresh ERROR (non-fatal): {exc}\n")

    if summary is None:
        return

    patch: dict[str, Any] = {
        "targeted_pending_scan_refresh": {**dict(summary), "post_lock": True},
    }
    if after_main_failure:
        patch["targeted_refresh_after_scrape_failure"] = True

    reproject_detail: dict[str, Any] | None = None
    if _targeted_refresh_needs_reproject(summary):
        try:
            reproject_detail = _refresh_open_step1_day_after_scrape(
                conn,
                cursor,
                org_id=org_id,
                log=log,
                scrape_batch_id=int(upload_batch_id) if upload_batch_id else None,
                scrape_run_id=result.run_id,
                detail={
                    "targeted_pending_scan_refresh": summary,
                    "post_lock_targeted_reproject": True,
                },
            )
            patch["targeted_post_lock_step1_refresh"] = reproject_detail
            log.write(
                "Post-lock Stage-B reproject after targeted scan events "
                f"inserted={_targeted_refresh_inserted_events(summary)}\n"
            )
            if reproject_detail and reproject_detail.get("ok") and not reproject_detail.get(
                "deferred"
            ):
                patch["wf_canonical_terminal_post_lock"] = (
                    _run_wf_canonical_terminal_projection(
                        conn,
                        cursor,
                        org_id=org_id,
                        log=log,
                        portal_csv_path=None,
                    )
                )
        except Exception as reproject_exc:
            reproject_detail = {
                "ok": False,
                "status": "failed",
                "error": str(reproject_exc),
                "post_lock": True,
            }
            patch["targeted_post_lock_step1_refresh"] = reproject_detail
            log.write(
                f"Post-lock Stage-B reproject ERROR (non-fatal): {reproject_exc}\n"
            )
    else:
        patch["targeted_post_lock_step1_refresh"] = {
            "skipped": True,
            "reason": "no_targeted_events",
            "post_lock": True,
        }
        log.write("Post-lock Stage-B reproject skipped (no targeted events)\n")

    result.detail = {**(result.detail or {}), **patch}
    # Never let post-lock work flip a terminal main status.
    result.status = main_status_before

    if result.run_id:
        try:
            merge_scrape_run_result_json(
                cursor, int(result.run_id), int(org_id), patch
            )
            conn.commit()
        except Exception as merge_exc:
            log.write(
                f"WARNING: could not persist post-lock targeted detail: {merge_exc}\n"
            )


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
    scrape_run_id: int | None = None,
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
        scrape_run_id=scrape_run_id,
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
        result.lease_generation = combined_cycle.lease_generation
    else:
        run_id = insert_scrape_run(
            cursor,
            org_id,
            tenant_slug=slug,
            rinse_vendor=vendor,
            run_type=run_type,
            log_path=str(paths.log_path),
        )
        gen = take_lease(cursor, org_id, run_id=run_id)
        bind_run_lease(cursor, run_id, org_id, gen)
        result.lease_generation = gen
        conn.commit()
        result.run_id = run_id
        started_at = datetime.utcnow()
        result.started_at = started_at
        log = _TeeLog(paths.log_path)

    lease_gen = result.lease_generation
    elapsed_already = 0
    if isinstance(started_at, datetime):
        elapsed_already = max(0, int((datetime.utcnow() - started_at).total_seconds()))
    hard_deadline_mono = time.monotonic() + max(
        60, hard_runtime_ceiling_seconds() - elapsed_already
    )

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
            single_pass = av_single_pass_enabled()

            if single_pass:
                # One Playwright walk: scan-events writes tickets (=portal) + events.
                # Timing comes from _subprocess_env_for_vendor (lean settles + collapse).
                # Do not re-inflate EXPAND/VENDORINLINE here — that alone made ACA ~7× slower.
                env["OUTPUT_PORTAL_SCRAPE_META"] = str(paths.scan_tickets_csv) + ".meta.json"
                log.write(
                    "Single-pass At Vendor: scan-events only "
                    "(portal + presence + scans from one expand walk)\n"
                )
                scan_download_started = datetime.utcnow()
                touch_scrape_run_progress(
                    cursor, run_id, org_id, stage="portal_scrape",
                    lease_generation=lease_gen,
                )
                conn.commit()

                def _scan_heartbeat() -> None:
                    if lease_gen is not None:
                        assert_lease_writable(cursor, org_id, int(lease_gen))
                    touch_scrape_run_progress(
                        cursor, run_id, org_id, stage="portal_scrape",
                        progress=False,
                        lease_generation=lease_gen,
                    )
                    conn.commit()

                last_prog_commit = [0.0]

                def _scan_progress(_line: str) -> None:
                    now_m = time.monotonic()
                    if now_m - last_prog_commit[0] < 15:
                        return
                    last_prog_commit[0] = now_m
                    touch_scrape_run_progress(
                        cursor, run_id, org_id, stage="portal_scrape",
                        lease_generation=lease_gen,
                    )
                    conn.commit()

                def _portal_supervisor_tick() -> None:
                    if lease_gen is not None:
                        from backend.rinse_scrape_liveness import touch_supervisor_heartbeat

                        touch_supervisor_heartbeat(
                            org_id, int(lease_gen), stage="portal_scrape"
                        )

                portal_outcome: list[dict[str, Any]] = []
                with scrape_stage_heartbeat(
                    run_id, org_id, stage="portal_scrape", lease_generation=lease_gen,
                ):
                    rc = _run_bash_script(
                        scan_script,
                        env,
                        log,
                        timeout_sec=scrape_timeout_sec(),
                        heartbeat_fn=_scan_heartbeat,
                        progress_fn=_scan_progress,
                        supervisor_tick_fn=_portal_supervisor_tick,
                        hard_deadline_mono=hard_deadline_mono,
                        outcome_out=portal_outcome,
                    )
                if portal_outcome:
                    from backend.rinse_scrape_subprocess_outcome import (
                        merge_portal_subprocess_outcome,
                    )

                    result.detail = merge_portal_subprocess_outcome(
                        result.detail, portal_outcome[0], stage="portal_scrape"
                    )
                if rc == -2:
                    raise RuntimeError(
                        f"FAILED_STALLED: no scrape progress for {stall_seconds()}s"
                    )
                if rc != 0:
                    raise RuntimeError("Scan-events scrape subprocess failed")
                scan_download_completed = datetime.utcnow()
                _materialize_portal_csv_from_scan_tickets(paths, log)

                from backend.rinse_presence_scrape import (
                    apply_at_vendor_presence_from_portal_csv,
                )

                presence_started = datetime.utcnow()
                touch_scrape_run_progress(
                    cursor, run_id, org_id, stage="scan_import",
                    lease_generation=lease_gen,
                )
                conn.commit()
                with scrape_stage_heartbeat(
                    run_id, org_id, stage="scan_import", lease_generation=lease_gen,
                ):
                    presence_result = apply_at_vendor_presence_from_portal_csv(
                        conn,
                        org_id,
                        portal_csv_path=paths.portal_csv,
                        portal_scrape_meta_path=Path(str(paths.portal_csv) + ".meta.json"),
                        run_type=run_type,
                        dry_run=False,
                        mark_missing=True,
                        log_write=log.write,
                        started_at=presence_started,
                    )
                presence_detail = build_presence_sync_detail(presence_result)
                result.detail["at_vendor_presence_sync"] = presence_detail
                result.detail["av_single_pass"] = True
                if presence_result.status not in ("success", "dry_run"):
                    raise RuntimeError(
                        presence_result.error_message
                        or "At Vendor presence apply from single-pass CSV failed"
                    )
                try:
                    from backend.rinse_wf_service_cycle import (
                        sync_wf_cycles_after_portal_presence,
                    )

                    cycle_sync = sync_wf_cycles_after_portal_presence(
                        conn,
                        cursor,
                        org_id,
                        portal_csv_path=paths.portal_csv,
                        portal_scrape_meta_path=Path(str(paths.portal_csv) + ".meta.json"),
                    )
                    result.detail["wf_service_cycle_sync"] = cycle_sync
                    conn.commit()
                except Exception as cycle_exc:
                    log.write(f"WARNING: wf service cycle sync: {cycle_exc}\n")
            else:
                def _portal_supervisor_tick() -> None:
                    if lease_gen is not None:
                        from backend.rinse_scrape_liveness import touch_supervisor_heartbeat

                        touch_supervisor_heartbeat(
                            org_id, int(lease_gen), stage="portal_scrape"
                        )

                portal_outcome: list[dict[str, Any]] = []
                with scrape_stage_heartbeat(
                    run_id, org_id, stage="portal_scrape", lease_generation=lease_gen,
                ):
                    rc = _run_bash_script(
                        portal_script,
                        env,
                        log,
                        supervisor_tick_fn=_portal_supervisor_tick,
                        outcome_out=portal_outcome,
                    )
                if portal_outcome:
                    from backend.rinse_scrape_subprocess_outcome import (
                        merge_portal_subprocess_outcome,
                    )

                    result.detail = merge_portal_subprocess_outcome(
                        result.detail, portal_outcome[0], stage="portal_scrape"
                    )
                if rc != 0:
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
                batch_date = _today_et()

                if not dry_run:
                    if single_pass and paths.scan_events_csv.is_file():
                        # Events already scraped in the single-pass walk.
                        from backend.rinse_combined_upload import commit_scheduled_scan_events_only
                        from backend.rinse_scan_events_upload import parse_scan_events_csv

                        scan_rows = count_csv_data_rows(paths.scan_events_csv)
                        if scan_rows >= 1:
                            events_name = f"scheduled-rinse-events-{_stamp_et()}.csv"
                            events_df, _warnings = parse_scan_events_csv(
                                str(paths.scan_events_csv)
                            )
                            scan_events_only_detail = commit_scheduled_scan_events_only(
                                conn,
                                cursor,
                                org_id,
                                batch_date,
                                events_name,
                                events_df,
                                scrape_run_id=run_id,
                            )
                            scan_events_only_detail = {
                                **(scan_events_only_detail or {}),
                                "status": "scan_events_imported",
                                "scan_rows": scan_rows,
                            }
                        else:
                            scan_events_only_detail = {
                                "status": "scan_events_csv_empty",
                                "scan_rows": 0,
                            }
                    else:
                        scan_events_only_detail = _import_scan_events_when_portal_gate_blocked(
                            conn,
                            cursor,
                            org_id=org_id,
                            paths=paths,
                            scan_script=scan_script,
                            env=env,
                            log=log,
                            batch_date=batch_date,
                            scrape_run_id=run_id,
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

                result.detail = {
                    **(result.detail or {}),
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
                # Portal confirm may be gated, but scan-only imports still land
                # events — refresh Step-1 so Completed/Pending do not freeze.
                # Targeted pending refresh runs post-lock after main terminal.
                if not dry_run:
                    result.detail["step1_day_refresh"] = _refresh_open_step1_day_after_scrape(
                        conn,
                        cursor,
                        org_id=org_id,
                        log=log,
                        scrape_batch_id=result.batch_id,
                        scrape_run_id=run_id,
                        detail=result.detail,
                    )
                    _mark_step1_refresh_failed_on_result(
                        result, result.detail.get("step1_day_refresh")
                    )
                conn.commit()
                return result

            if not single_pass:
                scan_download_started = datetime.utcnow()
                if _run_bash_script(scan_script, env, log) != 0:
                    raise RuntimeError("Scan-events scrape subprocess failed")
                scan_download_completed = datetime.utcnow()
            # else: scan already completed in the single-pass block above

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

            touch_scrape_run_progress(
                cursor, run_id, org_id, stage="scan_import",
                lease_generation=lease_gen,
            )
            conn.commit()
            if lease_gen is not None:
                assert_lease_writable(cursor, org_id, int(lease_gen))

            orders_df = portal_csv_to_orders_df(str(paths.portal_csv))
            events_df, warnings = parse_scan_events_csv(str(paths.scan_events_csv))
            newest_source_scan = _newest_source_scan_et(events_df)
            newest_db_before = _newest_db_scan_et(cursor, org_id)

            if len(orders_df) < 1:
                raise RuntimeError("Portal CSV parsed to zero order rows")

            from backend.rinse_portal_scrape_meta import meta_path_for_portal_csv

            portal_meta_path = meta_path_for_portal_csv(paths.portal_csv)
            from backend.rinse_portal_scrape_meta import (
                load_portal_scrape_meta_file,
                prepare_scheduled_ship_window_portal_meta,
            )

            portal_meta = prepare_scheduled_ship_window_portal_meta(
                load_portal_scrape_meta_file(portal_meta_path),
                meta_path=str(portal_meta_path),
            )
            with scrape_stage_heartbeat(
                run_id, org_id, stage="scan_import", lease_generation=lease_gen,
            ):
                draft_payload = commit_rinse_combined_upload(
                    conn,
                    cursor,
                    org_id,
                    batch_date,
                    portal_name,
                    orders_df,
                    events_name,
                    events_df,
                    portal_scrape_meta=portal_meta,
                    portal_scrape_meta_path=str(portal_meta_path),
                    scrape_run_id=run_id,
                )
            newest_db_after = _newest_db_scan_et(cursor, org_id)
            merge_available_at = datetime.utcnow()
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

            stale_resolve = resolve_stale_portal_attention_rows_before_confirm(
                cursor, org_id, batch_id
            )
            isolated_stale = int(stale_resolve.get("isolated_count") or 0)
            if isolated_stale:
                log.write(
                    f"Isolated {isolated_stale} OLDER_THAN_BATCH_DATE row(s) "
                    f"(tickets={stale_resolve.get('isolated_ticket_ids')}, "
                    f"null_ticket={stale_resolve.get('isolated_null_ticket_rows')}); "
                    "non-blocking for confirm\n"
                )
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
                    touch_scrape_run_progress(
                        cursor, run_id, org_id, stage="merge",
                        lease_generation=lease_gen,
                    )
                    conn.commit()
                    if lease_gen is not None:
                        assert_lease_writable(cursor, org_id, int(lease_gen))
                    # Staging + CONFIRMED only. Registry/folding finalize runs
                    # in-lock after Stage-B so terminal success means Management
                    # projection work for this cycle is finished.
                    with scrape_stage_heartbeat(
                        run_id, org_id, stage="merge", lease_generation=lease_gen,
                    ):
                        confirm_payload = confirm_upload_batch_core(
                            cursor,
                            org_id,
                            batch_id,
                            force_confirm=False,
                            run_finalize=False,
                        )
                    log.write(f"Auto-confirmed batch_id={batch_id}\n")
                except UploadBatchConfirmError as e:
                    conn.rollback()
                    raise RuntimeError(str(e)) from e

            conn.commit()

            off_portal_refresh_detail: dict[str, Any] | None = None
            step1_refresh_detail: dict[str, Any] | None = None
            finalize_payload: dict[str, Any] | None = None
            wf_canonical_terminal: dict[str, Any] | None = None
            if not dry_run and batch_id and final_status in ("success", "needs_attention"):
                touch_scrape_run_progress(
                    cursor, run_id, org_id, stage="stage_b_rebuild",
                    lease_generation=lease_gen,
                )
                conn.commit()
                if lease_gen is not None:
                    assert_lease_writable(cursor, org_id, int(lease_gen))
                _chain_boundary(log, "stage_b_start", batch_id=batch_id, run_id=run_id)
                # Main locked path: Stage-B after confirm, then required finalize.
                with scrape_stage_heartbeat(
                    run_id, org_id, stage="stage_b_rebuild", lease_generation=lease_gen,
                ):
                    step1_refresh_detail = _refresh_open_step1_day_after_scrape(
                        conn,
                        cursor,
                        org_id=org_id,
                        log=log,
                        scrape_batch_id=int(batch_id) if batch_id else None,
                        scrape_run_id=run_id,
                        detail={
                            "confirm": confirm_payload,
                            "draft": draft_payload,
                        },
                    )
                _chain_boundary(
                    log,
                    "stage_b_complete",
                    batch_id=batch_id,
                    run_id=run_id,
                    status=(step1_refresh_detail or {}).get("step1_refresh_status"),
                )
                # Required Management-visible finalize before terminal success.
                finalize_payload = _run_in_lock_rinse_finalize(
                    conn,
                    cursor,
                    org_id=org_id,
                    batch_id=int(batch_id),
                    run_id=run_id,
                    lease_generation=lease_gen,
                    log=log,
                    prior_persistent_merge=(
                        (draft_payload or {}).get("persistent_scan_merge")
                        if isinstance(draft_payload, dict)
                        else None
                    ),
                )
                if isinstance(confirm_payload, dict):
                    confirm_payload = {
                        **confirm_payload,
                        "rinse_finalize": {
                            **dict(finalize_payload or {}),
                            "deferred": False,
                            "in_lock": True,
                        },
                    }
                with scrape_stage_heartbeat(
                    run_id, org_id, stage="publish", lease_generation=lease_gen,
                ):
                    wf_canonical_terminal = _run_wf_canonical_terminal_projection(
                        conn,
                        cursor,
                        org_id=org_id,
                        log=log,
                        portal_csv_path=paths.portal_csv,
                        portal_scrape_meta_path=Path(str(paths.portal_csv) + ".meta.json"),
                    )

            result.status = final_status
            result.at_vendor_status = final_status
            confirmed_at = datetime.utcnow() if confirm_payload else None
            lag_seconds = _source_to_db_lag_seconds(
                confirmed_at or merge_available_at, newest_source_scan
            )
            db_advanced = bool(
                newest_db_after
                and newest_db_before
                and newest_db_after > newest_db_before
            ) or bool(
                newest_source_scan
                and newest_db_after
                and newest_db_after >= newest_source_scan
            )
            evidence = None
            stage_b_status = None
            if isinstance(step1_refresh_detail, dict):
                durable = step1_refresh_detail.get("durable_evidence_gate") or {}
                if isinstance(durable, dict):
                    evidence = durable.get("gate_status") or durable.get("status")
                stage_b_status = step1_refresh_detail.get("step1_refresh_status")
                if step1_refresh_detail.get("deferred"):
                    stage_b_status = stage_b_status or "DEFERRED"
            result.detail = {
                **{
                    k: v
                    for k, v in (result.detail or {}).items()
                    if k
                    in (
                        "at_vendor_presence_sync",
                        "av_single_pass",
                        "ready_for_vendor_sync",
                    )
                },
                "draft": draft_payload,
                "confirm": confirm_payload,
                "warnings": warnings,
                "attention_count": attention,
                "accepted_count": accepted,
                "portal_confirm_gate": portal_gate,
                "ingestion_lifecycle": {
                    "scrape_run_id": run_id,
                    "batch_id": batch_id,
                    "source_scan_download_started_et": _fmt_system_utc_as_et(
                        scan_download_started
                    ),
                    "source_scan_download_completed_et": _fmt_system_utc_as_et(
                        scan_download_completed
                    ),
                    "newest_source_scan_et": _fmt_et_wall(newest_source_scan),
                    "newest_db_scan_et_before": _fmt_et_wall(newest_db_before),
                    "newest_db_scan_et_after": _fmt_et_wall(newest_db_after),
                    "source_to_db_lag_seconds": lag_seconds,
                    "newest_scan_advanced": db_advanced,
                    "batch_confirmed_et": _fmt_system_utc_as_et(confirmed_at),
                    "evidence_gate": evidence,
                    "stage_b": stage_b_status,
                    "finalize_in_lock": bool(finalize_payload),
                },
            }
            if finalize_payload is not None:
                result.detail["rinse_finalize"] = {
                    **dict(finalize_payload),
                    "deferred": False,
                    "in_lock": True,
                }
                result.detail.pop("rinse_finalize_deferred", None)
            if portal_gate.get("force_override"):
                result.detail["sync_warning"] = portal_gate.get("warning")
            if off_portal_refresh_detail is not None:
                result.detail["off_portal_scan_refresh"] = off_portal_refresh_detail
            if step1_refresh_detail is not None:
                result.detail["step1_day_refresh"] = step1_refresh_detail
                _mark_step1_refresh_failed_on_result(result, step1_refresh_detail)
            if wf_canonical_terminal is not None:
                result.detail["wf_canonical_terminal"] = wf_canonical_terminal

        except Exception as e:
            conn.rollback()
            result.status = "failed"
            result.at_vendor_status = "failed"
            result.error_message = str(e)
            log.write(f"ERROR: {e}\n")
            # Targeted pending refresh runs post-lock after main terminal —
            # do not hold the scrape lock for Playwright lookups on failure.

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
        except Exception as finish_exc:
            try:
                log.write(f"Standalone finish ERROR: {finish_exc}\n")
            except Exception:
                pass
            try:
                term_status = str(result.status or "") or "failed"
                if term_status == "running":
                    term_status = "failed"
                ensure_scrape_run_terminal(
                    cursor,
                    int(run_id),
                    org_id,
                    status=term_status,
                    error_message=result.error_message or str(finish_exc),
                    result_json=dict(result.detail or {}),
                )
                conn.commit()
            except Exception:
                pass
        finally:
            release_scrape_lock(cursor, org_id)
            conn.commit()

    # Standalone (non-combined) path: targeted refresh only after main terminal + unlock.
    if not dry_run and result.status not in ("skipped",):
        post_log = _TeeLog(paths.log_path)
        try:
            _run_post_lock_or_abandon(
                conn,
                cursor,
                org_id=org_id,
                result=result,
                run_type=run_type,
                targeted_pending_refresh=targeted_pending_refresh,
                log=post_log,
                after_main_failure=str(result.status or "")
                not in ("success", "needs_attention", "inspect_only"),
            )
        finally:
            post_log.close()

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
        # Watchdog: retry any prior successful imports whose Stage B failed.
        if not dry_run:
            try:
                from backend.rinse_step1_scrape_refresh import retry_failed_step1_refreshes

                cursor = conn.cursor(dictionary=True)
                try:
                    watchdog = retry_failed_step1_refreshes(
                        conn, cursor, organization_id=int(oid), limit=5
                    )
                    if watchdog.get("retried"):
                        print(
                            f"step1 refresh watchdog org={oid} "
                            f"retried={watchdog.get('retried')} "
                            f"failed={watchdog.get('failed')}",
                            flush=True,
                        )
                    if watchdog.get("alert"):
                        print(
                            f"ALERT: Step-1 refresh still failing for org={oid} "
                            f"after max attempts",
                            flush=True,
                        )
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass
            except Exception as watchdog_exc:
                print(
                    f"WARNING: Step-1 refresh watchdog failed org={oid}: {watchdog_exc}",
                    flush=True,
                )
        results.append(
            run_rinse_combined_sync_for_org(conn, oid, run_type=run_type, dry_run=dry_run)
        )
    return results
