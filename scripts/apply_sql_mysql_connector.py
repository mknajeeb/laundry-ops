#!/usr/bin/env python3
"""
Apply a .sql file using mysql-connector-python (same auth/TLS as backend/db.py).

Use this when the mysql CLI fails with:
  ERROR 2059 (HY000): Authentication plugin 'mysql_native_password' cannot be loaded
Homebrew mysql 9+ often omits that plugin; the Python connector negotiates auth without it.

Usage:
  python3 scripts/apply_sql_mysql_connector.py [path/to/file.sql]
  # default: backend/sql/hr_compliance_v1.sql
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import mysql.connector


def _connect_kwargs() -> dict:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST")
    user = os.getenv("MYSQL_USER") or os.getenv("DB_USER")
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME")
    port = int(os.getenv("MYSQL_PORT") or os.getenv("DB_PORT") or "3306")
    if not all([host, user, password, database]):
        raise SystemExit(
            "Set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME (or MYSQL_*) in project root .env"
        )
    kwargs: dict = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port,
    }
    ssl_ca = os.getenv("MYSQL_SSL_CA")
    if ssl_ca:
        kwargs["ssl_ca"] = ssl_ca
        kwargs["ssl_disabled"] = False
    elif os.getenv("MYSQL_SSL_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
        kwargs["ssl_disabled"] = False
    return kwargs


def _statements(sql: str):
    """Split on ';' — fine for our DDL files (no semicolons inside strings)."""
    for part in sql.split(";"):
        stmt = part.strip()
        if not stmt:
            continue
        lines = []
        for line in stmt.splitlines():
            ls = line.strip()
            if not ls or ls.startswith("--"):
                continue
            lines.append(line)
        stmt = "\n".join(lines).strip()
        if stmt:
            yield stmt


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    sql_path = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else root / "backend/sql/hr_compliance_v1.sql"
    )
    if not sql_path.is_file():
        print(f"Missing file: {sql_path}", file=sys.stderr)
        sys.exit(1)
    sql = sql_path.read_text(encoding="utf-8")
    kwargs = _connect_kwargs()
    print(
        f"Applying {sql_path} → {kwargs['user']}@{kwargs['host']}:{kwargs['port']}/{kwargs['database']}"
    )
    conn = mysql.connector.connect(**kwargs)
    try:
        cur = conn.cursor()
        for stmt in _statements(sql):
            cur.execute(stmt)
            # Consume result sets (e.g. final SELECT note) so commit does not fail.
            try:
                while True:
                    _ = cur.fetchall()
                    if not cur.nextset():
                        break
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
