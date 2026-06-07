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
import sys


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
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_scheduled_scrape import run_all_scheduled_scrapes

    conn = get_db()
    try:
        results = run_all_scheduled_scrapes(
            conn,
            organization_ids=args.organization_ids,
            run_type=args.run_type,
            dry_run=args.dry_run,
        )
    finally:
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
        }
        out.append(item)
        if r.status == "failed":
            exit_code = 1
        elif r.status == "partial_success" and exit_code == 0:
            exit_code = 2
        elif r.status == "needs_attention" and exit_code == 0:
            exit_code = 3

    print(json.dumps({"runs": out}, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
