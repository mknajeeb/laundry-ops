"""
Rinse scrape recovery watchdog — orphan reclaim + missed ACTIVE tick recovery.

This is NOT a continuous-chain successor watchdog. Between scheduled --once
ticks, "no scraper running" is the expected healthy state.

ACTIVE:
  - reclaim genuinely orphaned lease owners
  - if a scheduled tick was missed/failed, start at most ONE recovery --once

QUIET:
  - reclaim orphans if needed
  - never start a scraper (absence is healthy)
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
    if venv_python.is_file() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(
            str(venv_python),
            [str(venv_python), "-m", "backend.jobs.run_rinse_freshness_watchdog", *sys.argv[1:]],
        )


_reexec_with_project_venv()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rinse scrape recovery watchdog")
    p.add_argument("--organization-id", type=int, action="append", dest="organization_ids")
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids
    from backend.rinse_scrape_chain import ensure_recovery_once
    from backend.rinse_scrape_liveness import reclaim_orphan_owner
    from backend.rinse_scrape_schedule import (
        current_mode,
        load_schedule_config,
        mark_quiet_reclaim,
        quiet_reclaim_due,
        quiet_suppresses_automatic_start,
    )

    orgs = args.organization_ids or parse_scheduled_org_ids()
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cfg = load_schedule_config(cursor)
        mode = current_mode(config=cfg)
        quiet = quiet_suppresses_automatic_start(config=cfg)
        print(
            json.dumps(
                {
                    "watchdog_mode": mode,
                    "quiet_suppresses_automatic_start": quiet,
                    "schedule": cfg.to_public_dict(),
                },
                default=str,
            ),
            flush=True,
        )

        for oid in orgs:
            if quiet:
                due, due_detail = quiet_reclaim_due(cursor, int(oid))
                if not due:
                    print(
                        f"RECOVERY_BOUNDARY org={oid} action=quiet_expected_idle "
                        f"reclaim_throttled={due_detail.get('reason')}",
                        flush=True,
                    )
                    continue
                out = reclaim_orphan_owner(cursor, int(oid))
                mark_quiet_reclaim(
                    cursor, int(oid), reclaim_action=str(out.get("action") or "")
                )
                print(
                    f"RECOVERY_BOUNDARY org={oid} action=quiet_reclaim_only "
                    f"reclaim={out.get('action')} (no scrape start)",
                    flush=True,
                )
                conn.commit()
                continue

            out = reclaim_orphan_owner(cursor, int(oid))
            print(f"watchdog org={oid} reclaim={out}", flush=True)
            conn.commit()

            # ACTIVE: start recovery only when a tick was missed — not merely
            # because the chain is idle between ticks.
            restart = ensure_recovery_once(
                cursor,
                int(oid),
                trigger=f"watchdog_{out.get('action') or 'tick'}",
            )
            print(f"watchdog org={oid} recovery={restart}", flush=True)
            conn.commit()
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
