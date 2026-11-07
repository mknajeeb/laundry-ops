#!/usr/bin/env python3
"""Prepare Lost & Found tables and the End of Day Activity definition.

Additive and idempotent. Safe to run twice. Does not rewrite existing
Task Management rows. Refuses any host other than localhost so this
cannot be pointed at the production database by the default connection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _refuse_unless_local() -> None:
    host = (os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "").strip().lower()
    database = (os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "").strip().lower()
    if host not in _LOCAL_HOSTS:
        raise SystemExit(
            f"Refusing schema preparation: MYSQL_HOST must be local, got {host or '(unset)'}."
        )
    if database in {"", "laundryapp"}:
        raise SystemExit(
            "Refusing schema preparation: set MYSQL_DATABASE to an isolated database name."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--twice",
        action="store_true",
        help="Run preparation a second time and print both results.",
    )
    args = parser.parse_args()
    _refuse_unless_local()
    from backend.db import get_db
    from backend.lost_found import prepare_lost_found_schema

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        first = prepare_lost_found_schema(cursor)
        conn.commit()
        payload = {"first": first}
        if args.twice:
            second = prepare_lost_found_schema(cursor)
            conn.commit()
            payload["second"] = second
        print(json.dumps(payload, indent=2, default=str))
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    raise SystemExit(main())
