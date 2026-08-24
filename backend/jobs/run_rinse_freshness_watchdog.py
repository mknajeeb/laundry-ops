"""
Rinse scrape orphan watchdog — multi-signal reclaim + idle-chain successor.

Reclaim requires stale supervisor heartbeat AND no live ownership evidence
(ACA execution not Running, MySQL lock not held).

After a successful reclaim (or when the chain is already ownerless/idle),
start exactly one recovery successor. Deduplication lives in
``ensure_chain_successor`` (Running ACA / live lease / owner-await-reclaim).
"""

from __future__ import annotations

import argparse
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
    p = argparse.ArgumentParser(description="Rinse scrape orphan watchdog")
    p.add_argument("--organization-id", type=int, action="append", dest="organization_ids")
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids
    from backend.rinse_scrape_chain import ensure_chain_successor
    from backend.rinse_scrape_liveness import reclaim_orphan_owner

    orgs = args.organization_ids or parse_scheduled_org_ids()
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        for oid in orgs:
            out = reclaim_orphan_owner(cursor, int(oid))
            print(f"watchdog org={oid} reclaim={out}", flush=True)
            conn.commit()

            action = str(out.get("action") or "")
            # After reclaim / stale-owner clear, or when already idle, ensure one successor.
            if action in (
                "reclaimed",
                "cleared_stale_owner",
                "no_owner",
                "no_lease",
            ):
                restart = ensure_chain_successor(
                    cursor,
                    int(oid),
                    trigger=f"watchdog_{action}",
                )
                print(f"watchdog org={oid} successor={restart}", flush=True)
                conn.commit()
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
