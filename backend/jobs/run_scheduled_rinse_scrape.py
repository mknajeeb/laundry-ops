"""
Scheduled Rinse scrape (multi-tenant): Playwright + dual CSV import + auto-confirm.

Processes RINSE_SCHEDULED_ORG_IDS sequentially (one org at a time; per-org DB lock).

Local / ACA job:
  python -m backend.jobs.run_scheduled_rinse_scrape
  python -m backend.jobs.run_scheduled_rinse_scrape --organization-id 3
  python -m backend.jobs.run_scheduled_rinse_scrape --dry-run

Requires:
  RINSE_SCHEDULED_SCRAPE_ENABLED=1
  RINSE_SCHEDULED_ORG_IDS=3          # v1 VeeWash only; later e.g. 1,3
  RINSE_VEEWASH_ORG_IDS=3            # maps org → veewash vendor (add RINSE_WASHPRO_ORG_IDS when enabling Washpro)
  MYSQL_* and per-vendor RINSE_*_STORAGE_STATE on Azure Files (see docs/RINSE_SCHEDULED_SCRAPE_AZURE_DEPLOY.md)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _reexec_with_project_venv() -> None:
    repo = Path(__file__).resolve().parents[2]
    venv_python = repo / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(str(venv_python), [str(venv_python), "-m", "backend.jobs.run_scheduled_rinse_scrape", *sys.argv[1:]])


_reexec_with_project_venv()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run scheduled Rinse scrape pipeline")
    p.add_argument(
        "--organization-id",
        type=int,
        action="append",
        dest="organization_ids",
        help="Organization ID (repeatable). Default: RINSE_SCHEDULED_ORG_IDS",
    )
    p.add_argument(
        "--run-type",
        default="scheduled",
        choices=("scheduled", "manual", "server"),
        help="Recorded in rinse_scrape_runs.run_type",
    )
    p.add_argument("--dry-run", action="store_true", help="Resolve paths only; no scrape or DB writes")
    p.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Stop the sequential loop after N cycles (tests / probes). Default: until replica handoff.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle then exit (no sequential loop, no successor start).",
    )
    p.add_argument(
        "--force-fail",
        action="store_true",
        help="Fail the first cycle after lock+lease (self-heal failure proof).",
    )
    p.add_argument(
        "--force-stall",
        action="store_true",
        help="Hold lock without heartbeats after lease (self-heal stall proof).",
    )
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.release_revision import load_release_revision_stamps
    from backend.rinse_scrape_chain import run_continuous_scheduled_loop
    from backend.rinse_scheduled_scrape import run_all_scheduled_scrapes

    stamps = load_release_revision_stamps()
    print(
        json.dumps(
            {
                "scheduler_release_revision": stamps,
                "manager_lock_upsert_module": "backend.rinse_veewash_shift_day",
            },
            indent=2,
            default=str,
        ),
        flush=True,
    )

    conn = get_db()
    results = []
    try:
        if args.once or args.dry_run:
            results = run_all_scheduled_scrapes(
                conn,
                organization_ids=args.organization_ids,
                run_type=args.run_type,
                dry_run=args.dry_run,
            )
        else:
            results = run_continuous_scheduled_loop(
                conn,
                organization_ids=args.organization_ids,
                run_type=args.run_type,
                dry_run=False,
                max_cycles=args.max_cycles,
                force_fail=bool(args.force_fail),
                force_stall=bool(args.force_stall),
            )
    finally:
        owned_cycle = any(
            str(getattr(r, "status", "") or "") not in ("skipped", "")
            for r in results
        )
        # --once is a one-shot probe: it must not start a successor (that was the
        # Sep-1 pause mode). Continuous / --max-cycles exits still hand off.
        if args.once:
            print(
                "CHAIN_BOUNDARY successor_skipped reason=once_flag "
                f"owned_cycle={owned_cycle}",
                flush=True,
            )
        elif args.dry_run:
            print("CHAIN_BOUNDARY successor_skipped reason=dry_run", flush=True)
        elif not owned_cycle:
            print(
                "CHAIN_BOUNDARY successor_skipped reason=no_owned_cycle",
                flush=True,
            )
        else:
            try:
                from backend.rinse_scrape_chain import start_successor_execution

                print("CHAIN_BOUNDARY aca_identity_cleanup_start", flush=True)
                handoff = start_successor_execution(run_type=args.run_type)
                print(f"rinse chain successor {handoff}", flush=True)
                print("CHAIN_BOUNDARY aca_identity_cleanup_complete", flush=True)
            except Exception as exc:
                print(f"rinse chain successor failed: {exc}", flush=True)
        try:
            conn.close()
        except Exception:
            pass

    out = []
    exit_code = 0
    for r in results:
        item = {
            "organization_id": r.organization_id,
            "run_id": r.run_id,
            "status": r.status,
            "rinse_vendor": r.rinse_vendor,
            "tenant_slug": r.tenant_slug,
            "batch_id": r.batch_id,
            "portal_rows_count": r.portal_rows_count,
            "scan_events_count": r.scan_events_count,
            "error_message": r.error_message,
            "ready_for_vendor_status": r.ready_for_vendor_status,
            "ready_for_vendor_error": r.ready_for_vendor_error,
            "at_vendor_status": r.at_vendor_status,
            "log_path": str(r.paths.log_path) if r.paths else None,
            "detail": r.detail,
            "scheduler_runtime_revision": stamps.get("runtime_revision"),
            "scheduler_image_revision": stamps.get("image_revision"),
            "scheduler_source_revision": stamps.get("source_revision"),
        }
        out.append(item)
        if r.status == "failed":
            exit_code = 1
        elif r.status == "partial_success" and exit_code == 0:
            exit_code = 2
        elif r.status == "needs_attention" and exit_code == 0:
            exit_code = 3

    print(
        json.dumps(
            {
                "runs": out,
                "scheduler_release_revision": stamps,
            },
            indent=2,
            default=str,
        )
    )
    print(f"CHAIN_BOUNDARY process_exit exit_code={exit_code}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
