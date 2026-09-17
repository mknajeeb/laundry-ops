"""
Scheduled Rinse scrape (multi-tenant): Playwright + dual CSV import + auto-confirm.

Normal production path (default):
  python -m backend.jobs.run_scheduled_rinse_scrape --once
  → at most one owned scrape cycle, no successor, schedule-gated for run_type=scheduled

Legacy continuous loop (opt-in only; not the normal schedule model):
  python -m backend.jobs.run_scheduled_rinse_scrape --continuous

Requires:
  RINSE_SCHEDULED_SCRAPE_ENABLED=1
  RINSE_SCHEDULED_ORG_IDS=3
  MYSQL_* and per-vendor RINSE_*_STORAGE_STATE
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


def _should_use_once(args: argparse.Namespace) -> bool:
    """Default production path is once; continuous is opt-in."""
    if args.dry_run:
        return True
    if args.continuous:
        return False
    if args.max_cycles is not None and not args.once:
        # Legacy probe: max-cycles without --once implies continuous loop.
        return False
    # Explicit --once, or default scheduled/manual one-shot.
    return True


def _schedule_gate_allows_run(conn, args: argparse.Namespace) -> tuple[bool, dict]:
    """
    For run_type=scheduled once invocations, no-op when no tick is due.

    Manual/server/recovery/--force-schedule bypass the due-tick gate.
    Continuous legacy path also bypasses (caller must not use this for normal ops).
    """
    from backend.rinse_scrape_schedule import (
        evaluate_schedule,
        get_last_completed_tick_key,
        load_schedule_config,
    )
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids

    if args.dry_run:
        return True, {"reason": "dry_run"}
    if str(args.run_type or "").strip().lower() != "scheduled":
        return True, {"reason": "non_scheduled_run_type"}
    if args.force_schedule:
        return True, {"reason": "force_schedule"}
    if args.continuous or (args.max_cycles is not None and not args.once):
        return True, {"reason": "continuous_legacy_path"}

    orgs = args.organization_ids or parse_scheduled_org_ids()
    if not orgs:
        return False, {"reason": "no_orgs"}

    cursor = conn.cursor(dictionary=True)
    try:
        cfg = load_schedule_config(cursor)
        # Gate on the first org (v1 single-tenant schedule).
        org = int(orgs[0])
        last_key = get_last_completed_tick_key(cursor, org)
        decision = evaluate_schedule(config=cfg, last_completed_tick_key=last_key)
        detail = decision.to_public_dict()
        detail["organization_id"] = org
        if decision.scrape_due:
            return True, detail
        return False, detail
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def _result_duration_seconds(r) -> float | None:
    started = getattr(r, "started_at", None)
    finished = getattr(r, "finished_at", None)
    if started and finished:
        try:
            return max(0.0, (finished - started).total_seconds())
        except Exception:
            return None
    return None


def _scrape_summary_for_result(r, *, schedule_detail: dict | None = None) -> dict:
    detail = getattr(r, "detail", None) or {}
    if not isinstance(detail, dict):
        detail = {}
    lifecycle = detail.get("lifecycle") if isinstance(detail.get("lifecycle"), dict) else {}
    query_budget = detail.get("query_budget") if isinstance(detail.get("query_budget"), dict) else None
    return {
        "event": "SCRAPE_SUMMARY",
        "run_id": getattr(r, "run_id", None),
        "organization_id": getattr(r, "organization_id", None),
        "status": getattr(r, "status", None),
        "duration_seconds": _result_duration_seconds(r),
        "portal_rows_count": getattr(r, "portal_rows_count", None),
        "scan_events_count": getattr(r, "scan_events_count", None),
        "batch_id": getattr(r, "batch_id", None),
        "changed_count": detail.get("changed_count") or detail.get("rows_changed"),
        "new_count": detail.get("new_count") or detail.get("rows_new"),
        "removed_count": detail.get("removed_count") or detail.get("rows_removed"),
        "lifecycle_changes": lifecycle.get("changes") or lifecycle.get("changed_count"),
        "query_budget": query_budget,
        "tick_key": (schedule_detail or {}).get("tick_key"),
        "mode": (schedule_detail or {}).get("mode"),
        "error_message": getattr(r, "error_message", None),
        "result": getattr(r, "status", None),
    }


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
        help="With --continuous: stop after N cycles. Ignored for default --once path.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run a single cycle then exit (default production behavior when not --continuous).",
    )
    p.add_argument(
        "--continuous",
        action="store_true",
        help=(
            "LEGACY: run the in-process continuous loop and successor handoff. "
            "Not used for normal ACTIVE/QUIET scheduling."
        ),
    )
    p.add_argument(
        "--force-schedule",
        action="store_true",
        help="Bypass schedule due-tick gate (manual/recovery).",
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
    use_once = _should_use_once(args)

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
                "execution_mode": "once" if use_once else "continuous_legacy",
            },
            indent=2,
            default=str,
        ),
        flush=True,
    )

    conn = get_db()
    results = []
    schedule_detail: dict = {}
    try:
        allowed, schedule_detail = _schedule_gate_allows_run(conn, args)
        print(
            f"SCHEDULE_BOUNDARY gate_allowed={allowed} "
            f"detail={json.dumps(schedule_detail, default=str)[:800]}",
            flush=True,
        )
        if not allowed:
            print(
                f"SCHEDULE_BOUNDARY skip reason={schedule_detail.get('reason')} "
                f"mode={schedule_detail.get('mode')} tick={schedule_detail.get('tick_key')}",
                flush=True,
            )
            results = []
        elif use_once:
            results = run_all_scheduled_scrapes(
                conn,
                organization_ids=args.organization_ids,
                run_type=args.run_type,
                dry_run=args.dry_run,
            )
            # Record tick completion for successful owned scheduled cycles.
            if (
                not args.dry_run
                and str(args.run_type or "").lower() == "scheduled"
                and schedule_detail.get("tick_key")
            ):
                try:
                    from backend.rinse_scrape_schedule import mark_tick_completed

                    cur = conn.cursor(dictionary=True)
                    try:
                        for r in results:
                            st = str(getattr(r, "status", "") or "")
                            if st in ("success", "partial_success", "needs_attention"):
                                mark_tick_completed(
                                    cur,
                                    int(getattr(r, "organization_id")),
                                    str(schedule_detail["tick_key"]),
                                    run_id=getattr(r, "run_id", None),
                                )
                        conn.commit()
                    finally:
                        cur.close()
                except Exception as tick_exc:
                    print(f"SCHEDULE_BOUNDARY tick_mark_failed: {tick_exc}", flush=True)
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
        # Default once path and dry-run never start a successor.
        if use_once or args.once or args.dry_run:
            pass  # expected; SCRAPE_SUMMARY covers outcome
        elif not owned_cycle:
            print(
                "CHAIN_BOUNDARY successor_skipped reason=no_owned_cycle",
                flush=True,
            )
        else:
            # Legacy continuous only.
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

    exit_code = 0
    summaries = []
    for r in results:
        summary = _scrape_summary_for_result(r, schedule_detail=schedule_detail)
        summaries.append(summary)
        print(json.dumps(summary, default=str), flush=True)
        if r.status == "failed":
            exit_code = 1
        elif r.status == "partial_success" and exit_code == 0:
            exit_code = 2
        elif r.status == "needs_attention" and exit_code == 0:
            exit_code = 3
        elif str(r.status or "") not in ("success", "skipped", "partial_success", "needs_attention", ""):
            if exit_code == 0 and r.error_message:
                print(
                    json.dumps(
                        {
                            "event": "SCRAPE_WARNING",
                            "run_id": r.run_id,
                            "status": r.status,
                            "error_message": r.error_message,
                        },
                        default=str,
                    ),
                    flush=True,
                )

    verbose = str(os.getenv("RINSE_SCRAPE_VERBOSE_RESULT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if verbose:
        out = []
        for r in results:
            out.append(
                {
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
            )
        print(
            json.dumps(
                {
                    "runs": out,
                    "scheduler_release_revision": stamps,
                    "schedule": schedule_detail,
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(
            json.dumps(
                {
                    "event": "SCRAPE_RUN_COMPLETE",
                    "exit_code": exit_code,
                    "summaries": summaries,
                    "scheduler_release_revision": {
                        k: stamps.get(k)
                        for k in ("runtime_revision", "image_revision", "source_revision")
                    },
                    "schedule_mode": (schedule_detail or {}).get("mode"),
                    "schedule_reason": (schedule_detail or {}).get("reason"),
                },
                default=str,
            ),
            flush=True,
        )
    print(f"CHAIN_BOUNDARY process_exit exit_code={exit_code}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
