#!/usr/bin/env python3
"""Idempotent backfill of rinse_order_instances from COMPLETED service cycles."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--organization-id", type=int, default=None)
    p.add_argument("--env-file", type=str, default=None)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    _load_dotenv(Path(args.env_file) if args.env_file else root / ".env")

    from backend.db import get_db
    from backend.rinse_order_instances import (
        backfill_order_instances_from_service_cycles,
        ensure_rinse_order_instances_table,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    ensure_rinse_order_instances_table(cur)
    # Fast SQL path for all COMPLETED cycles
    if args.organization_id is None:
        cur.execute(
            """
            INSERT INTO rinse_order_instances (
              organization_id, bag_id, service_type, cycle_anchor_at, source_cycle_id,
              completed_at, completion_source
            )
            SELECT organization_id, UPPER(TRIM(bag_id)), 'WF', cycle_anchor_at, id,
                   completed_at, completion_source
            FROM rinse_wf_service_cycles
            WHERE status='COMPLETED'
              AND completed_at IS NOT NULL
              AND cycle_anchor_at IS NOT NULL
            ON DUPLICATE KEY UPDATE
              source_cycle_id = COALESCE(VALUES(source_cycle_id), rinse_order_instances.source_cycle_id),
              completed_at = COALESCE(VALUES(completed_at), rinse_order_instances.completed_at),
              completion_source = COALESCE(
                VALUES(completion_source), rinse_order_instances.completion_source
              )
            """
        )
    else:
        cur.execute(
            """
            INSERT INTO rinse_order_instances (
              organization_id, bag_id, service_type, cycle_anchor_at, source_cycle_id,
              completed_at, completion_source
            )
            SELECT organization_id, UPPER(TRIM(bag_id)), 'WF', cycle_anchor_at, id,
                   completed_at, completion_source
            FROM rinse_wf_service_cycles
            WHERE organization_id=%s
              AND status='COMPLETED'
              AND completed_at IS NOT NULL
              AND cycle_anchor_at IS NOT NULL
            ON DUPLICATE KEY UPDATE
              source_cycle_id = COALESCE(VALUES(source_cycle_id), rinse_order_instances.source_cycle_id),
              completed_at = COALESCE(VALUES(completed_at), rinse_order_instances.completed_at),
              completion_source = COALESCE(
                VALUES(completion_source), rinse_order_instances.completion_source
              )
            """,
            (int(args.organization_id),),
        )
    conn.commit()
    stats = backfill_order_instances_from_service_cycles(
        cur, args.organization_id
    )
    conn.commit()
    print(json.dumps({"sql_rowcount": cur.rowcount, **stats}, indent=2))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
