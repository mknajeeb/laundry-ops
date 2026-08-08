#!/usr/bin/env python3
"""Apply Phase 5E DRC mobile schema (controlled migration). Idempotent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.db import get_db
from backend.ta_helpers import table_exists


SQL_PATH = ROOT / "backend" / "sql" / "drc_mobile_entry_v1.sql"
TABLES = (
    "drc_weekday_section_assignments",
    "drc_mobile_section_submissions",
    "drc_mobile_section_events",
)


def main() -> int:
    sql = SQL_PATH.read_text(encoding="utf-8")
    # Strip comments / SELECT note; keep CREATE TABLE statements.
    statements = []
    buf = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped.upper().startswith("SELECT "):
            continue
        if stripped.upper().startswith("SET "):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if buf:
        statements.append("\n".join(buf))

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    before = {t: table_exists(cur, t) for t in TABLES}
    print("before", before)
    for stmt in statements:
        cur.execute(stmt)
    conn.commit()
    from backend.ta_helpers import invalidate_schema_cache

    invalidate_schema_cache()
    after = {t: table_exists(cur, t) for t in TABLES}
    print("after", after)
    cur.close()
    conn.close()
    if not all(after.values()):
        print("ERROR: not all tables present", file=sys.stderr)
        return 1
    print("drc_mobile_entry_v1 applied OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
