"""Dispatch manual Refresh Both Syncs without running Playwright in the API worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.rinse_aca_job_trigger import (
    aca_job_trigger_configured,
    manual_sync_must_not_run_local_playwright,
    remote_only_user_message,
    start_rinse_scrape_aca_job,
)
from backend.rinse_scheduled_scrape import CYCLE_ALREADY_RUNNING
from backend.rinse_scrape_runs import is_scrape_cycle_running


@dataclass
class ManualSyncDispatchResult:
    organization_id: int
    mode: str
    overall_status: str
    http_status: int = 200
    message: str | None = None
    error_message: str | None = None
    aca_execution_name: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "organization_id": self.organization_id,
            "overall_status": self.overall_status,
            "dispatch_mode": self.mode,
            "message": self.message,
            "sync_cycle": {
                "cycle_status": self.overall_status,
                "dispatch_mode": self.mode,
            },
        }
        if self.error_message:
            payload["error"] = self.error_message
        if self.aca_execution_name:
            payload["aca_execution_name"] = self.aca_execution_name
            payload["sync_cycle"]["aca_execution_name"] = self.aca_execution_name
        payload.update(self.detail)
        return payload


def dispatch_manual_rinse_sync(
    conn,
    organization_id: int,
    *,
    dry_run: bool = False,
) -> ManualSyncDispatchResult:
    org = int(organization_id)
    cursor = conn.cursor(dictionary=True)

    if dry_run:
        mode = "aca_job" if aca_job_trigger_configured() else "local_combined"
        if manual_sync_must_not_run_local_playwright() and not aca_job_trigger_configured():
            mode = "remote_only_blocked"
        return ManualSyncDispatchResult(
            organization_id=org,
            mode=mode,
            overall_status="dry_run",
            message=f"Dry run — would use {mode}",
        )

    running, run_hint = is_scrape_cycle_running(cursor, org)
    if running:
        return ManualSyncDispatchResult(
            organization_id=org,
            mode="blocked",
            overall_status="ALREADY_RUNNING",
            http_status=409,
            error_message=CYCLE_ALREADY_RUNNING,
            message="A Rinse sync cycle is already running for this organization.",
            detail={"running_hint": run_hint},
        )

    if aca_job_trigger_configured():
        started = start_rinse_scrape_aca_job(org, run_type="manual")
        if not started.ok:
            return ManualSyncDispatchResult(
                organization_id=org,
                mode="aca_job",
                overall_status="failed",
                http_status=502,
                error_message=started.error_message,
                message=started.error_message,
            )
        return ManualSyncDispatchResult(
            organization_id=org,
            mode="aca_job",
            overall_status="queued",
            http_status=202,
            message=(
                "Scheduler job started. Dashboard will refresh when the sync cycle completes "
                "(typically a few minutes)."
            ),
            aca_execution_name=started.execution_name,
            detail={
                "ready_for_vendor_sync": {"status": "queued", "message": "Waiting for scheduler"},
                "at_vendor_sync": {"status": "queued", "message": "Waiting for scheduler"},
            },
        )

    if manual_sync_must_not_run_local_playwright():
        msg = remote_only_user_message()
        return ManualSyncDispatchResult(
            organization_id=org,
            mode="remote_only_blocked",
            overall_status="failed",
            http_status=503,
            error_message=msg,
            message=msg,
            detail={
                "ready_for_vendor_sync": {
                    "status": "failed",
                    "error_message": msg,
                },
            },
        )

    from backend.rinse_scheduled_scrape import run_rinse_combined_sync_for_org

    combined = run_rinse_combined_sync_for_org(
        conn,
        org,
        run_type="manual",
        dry_run=False,
    )
    if combined.status == "skipped" and combined.error_message == CYCLE_ALREADY_RUNNING:
        return ManualSyncDispatchResult(
            organization_id=org,
            mode="local_combined",
            overall_status="ALREADY_RUNNING",
            http_status=409,
            error_message=CYCLE_ALREADY_RUNNING,
            message="A Rinse sync cycle is already running for this organization.",
        )

    rfv_detail = dict((combined.detail or {}).get("ready_for_vendor_sync") or {})
    av_presence_detail = dict((combined.detail or {}).get("at_vendor_presence_sync") or {})
    sync_cycle = dict((combined.detail or {}).get("sync_cycle") or {})
    http_status = 200
    if combined.status == "failed":
        http_status = 502
    elif combined.status == "partial_success":
        http_status = 207

    return ManualSyncDispatchResult(
        organization_id=org,
        mode="local_combined",
        overall_status=combined.status,
        http_status=http_status,
        message=f"Local combined sync finished with status {combined.status}",
        error_message=combined.error_message,
        detail={
            "sync_cycle": sync_cycle,
            "sync_cycle_id": sync_cycle.get("sync_cycle_id") or combined.run_id,
            "cycle_status": sync_cycle.get("cycle_status") or combined.status,
            "at_vendor_sync": {
                "status": combined.at_vendor_status or combined.status,
                "run_id": combined.run_id,
                "batch_id": combined.batch_id,
                "portal_rows_count": combined.portal_rows_count,
                "scan_events_count": combined.scan_events_count,
                "error_message": combined.error_message,
            },
            "at_vendor_presence_sync": av_presence_detail,
            "ready_for_vendor_sync": rfv_detail,
        },
    )
