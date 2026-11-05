#!/usr/bin/env python3
"""Prepare a disposable database for the Task Management release candidate.

Set MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, and MYSQL_DATABASE.
Refuses hosts that look like Azure production unless ALLOW_PRODUCTION_SCHEMA=1.
Does not backfill participation sessions or acknowledgments.
With no MYSQL_HOST, prints the expected shape and exits without connecting.
"""

from __future__ import annotations

import os
import sys

BLOCKED_HOST_MARKERS = ("azure", "laundryops", "database.windows.net")


def main() -> int:
    host = os.environ.get("MYSQL_HOST") or ""
    if not host:
        from backend.task_schema_prep import EXPECTED_COLUMNS

        print({"connected": False, "expected": EXPECTED_COLUMNS})
        return 0
    if os.environ.get("ALLOW_PRODUCTION_SCHEMA") != "1":
        lowered = host.lower()
        if any(marker in lowered for marker in BLOCKED_HOST_MARKERS):
            print(f"Refusing schema preparation for host {host}.", file=sys.stderr)
            return 2
    import mysql.connector

    from backend.task_schema_prep import prepare_task_management_schema

    conn = mysql.connector.connect(
        host=host,
        user=os.environ["MYSQL_USER"],
        password=os.environ.get("MYSQL_PASSWORD") or "",
        database=os.environ["MYSQL_DATABASE"],
    )
    cursor = conn.cursor(dictionary=True)
    try:
        report = prepare_task_management_schema(cursor)
        conn.commit()
    finally:
        conn.close()
    print(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
