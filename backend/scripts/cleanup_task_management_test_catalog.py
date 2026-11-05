#!/usr/bin/env python3
"""Dry-run or apply the approved disposable Task Management catalog cleanup.

Refuses Azure production unless ALLOW_PRODUCTION_CLEANUP=1.
Deletes only when APPLY=1. The default is a read-only plan.
"""

from __future__ import annotations

import json
import os
import sys

BLOCKED_HOST_MARKERS = ("azure", "laundryops", "database.windows.net")


def main() -> int:
    host = os.environ.get("MYSQL_HOST") or ""
    apply = os.environ.get("APPLY") == "1"
    if not host:
        print(json.dumps({"connected": False, "apply": apply}))
        return 0
    lowered = host.lower()
    if any(marker in lowered for marker in BLOCKED_HOST_MARKERS):
        if os.environ.get("ALLOW_PRODUCTION_CLEANUP") != "1":
            print(f"Refusing cleanup for host {host}.", file=sys.stderr)
            return 2
        if apply:
            print("Refusing to apply cleanup on production from this command.", file=sys.stderr)
            print("Production deletion requires a separate explicit authorization.", file=sys.stderr)
            return 2
    import mysql.connector

    from backend.task_test_catalog_cleanup import apply_test_catalog_cleanup, plan_test_catalog_cleanup

    conn = mysql.connector.connect(
        host=host,
        user=os.environ["MYSQL_USER"],
        password=os.environ.get("MYSQL_PASSWORD") or "",
        database=os.environ["MYSQL_DATABASE"],
    )
    cursor = conn.cursor(dictionary=True)
    try:
        if apply:
            report = apply_test_catalog_cleanup(cursor)
            if report.get("deleted"):
                conn.commit()
            else:
                conn.rollback()
        else:
            report = plan_test_catalog_cleanup(cursor)
            report["deleted"] = False
    finally:
        conn.close()
    print(json.dumps(report, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
