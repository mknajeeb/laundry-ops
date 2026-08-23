"""
Rinse scrape orphan watchdog — multi-signal reclaim only.

Reclaim requires stale supervisor heartbeat AND no live ownership evidence
(ACA execution not Running, MySQL lock not held).
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
        os.execv(str(venv_python), [str(venv_python), "-m", "backend.jobs.run_rinse_freshness_watchdog", *sys.argv[1:]])


_reexec_with_project_venv()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rinse scrape orphan watchdog")
    p.add_argument("--organization-id", type=int, action="append", dest="organization_ids")
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids
    from backend.rinse_scrape_liveness import reclaim_orphan_owner

    orgs = args.organization_ids or parse_scheduled_org_ids()
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        for oid in orgs:
            out = reclaim_orphan_owner(cursor, int(oid))
            print(f"watchdog org={oid} {out}", flush=True)
            conn.commit()
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
