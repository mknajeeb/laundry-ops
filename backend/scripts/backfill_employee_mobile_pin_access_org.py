#!/usr/bin/env python3
"""
Phase 5B.2 — Controlled single-organization Mobile PIN Access legacy backfill.

Usage:
  python3 backend/scripts/backfill_employee_mobile_pin_access_org.py \\
    --organization-id 3 --dry-run

  python3 backend/scripts/backfill_employee_mobile_pin_access_org.py \\
    --organization-id 3 --execute

Never touches another organization. Prefer --dry-run before --execute.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill employee_mobile_pin_access for exactly one organization."
    )
    parser.add_argument(
        "--organization-id",
        type=int,
        required=True,
        help="Single organization id to backfill (required).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report eligible/planned work without writing.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Run transactional backfill and write marker after verification.",
    )
    args = parser.parse_args(argv)

    from backend.db import get_db
    from backend.employee_mobile_pin_access import (
        MobilePinAccessBackfillError,
        run_org_mobile_pin_access_legacy_backfill,
    )

    conn = get_db()
    try:
        report = run_org_mobile_pin_access_legacy_backfill(
            conn,
            int(args.organization_id),
            dry_run=bool(args.dry_run),
        )
    except MobilePinAccessBackfillError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "organization_id": int(args.organization_id),
                    "dry_run": bool(args.dry_run),
                },
                indent=2,
                default=str,
            )
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "organization_id": int(args.organization_id),
                    "dry_run": bool(args.dry_run),
                },
                indent=2,
                default=str,
            )
        )
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
