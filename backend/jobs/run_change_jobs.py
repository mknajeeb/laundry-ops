"""
Run all registered "change" jobs (document compliance tick, …).

Local:
  python -m backend.jobs.run_change_jobs
  python -m backend.jobs.run_change_jobs --dry-run

Production without a host cron: call POST /internal/jobs/change-jobs with header
  X-Change-Jobs-Secret: <CHANGE_JOBS_SECRET>
(e.g. Azure Logic Apps, GitHub Actions scheduled workflow, Uptime Kuma heartbeat with shell, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run laundry_app batch jobs")
    p.add_argument("--dry-run", action="store_true", help="Log actions without writing or sending push")
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.hr_compliance import run_document_compliance_tick

    conn = get_db()
    try:
        out = run_document_compliance_tick(conn, dry_run=args.dry_run)
        print(json.dumps(out, indent=2, default=str))
        return 0 if not out.get("errors") else 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
