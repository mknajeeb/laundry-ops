"""Restore CLOSED historical day published snapshot from day_bags (no live YTP).

Usage:
  ORG_ID=3 SHIFT_DATE_ET=2026-08-20 \\
  /path/to/.venv/bin/python -m backend.jobs.restore_closed_day_published_snapshot
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for p in (
        Path("/Users/kamisb./laundry_app/.env"),
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    import mysql.connector

    from backend.rinse_freshness_store import (
        ensure_freshness_tables,
        finish_cycle,
        insert_cycle,
        release_lane_lease_if_owner,
        take_lane_lease,
    )
    from backend.rinse_restore_closed_day_snapshot import (
        restore_closed_day_published_snapshot_from_day_bags,
    )

    e = _load_env()
    org = int(os.getenv("ORG_ID", "3") or 3)
    day = date.fromisoformat(
        str(os.getenv("SHIFT_DATE_ET", "2026-08-20") or "2026-08-20")[:10]
    )
    lane = str(os.getenv("LANE", "deep") or "deep")
    dry = str(os.getenv("DRY_RUN", "") or "").strip().lower() in ("1", "true", "yes")

    cnx = mysql.connector.connect(
        host=e["MYSQL_HOST"],
        user=e["MYSQL_USER"],
        password=e["MYSQL_PASSWORD"],
        database=e["MYSQL_DATABASE"],
        port=int(e.get("MYSQL_PORT") or 3306),
        buffered=True,
    )
    cur = cnx.cursor(dictionary=True)
    try:
        ensure_freshness_tables(cur)
        cnx.commit()
        if dry:
            from backend.rinse_veewash_shift_day import (
                get_day_record,
                summary_from_day_record,
                count_day_bag_status_buckets,
                _load_day_bag_status_projection,
            )

            day_rec = get_day_record(cur, org, day) or {}
            hl = summary_from_day_record(day_rec) or {}
            buckets = count_day_bag_status_buckets(
                _load_day_bag_status_projection(cur, org, day)
            )
            print(
                {
                    "dry_run": True,
                    "day_status": day_rec.get("status"),
                    "headline_wf": ((hl.get("segments") or {}).get("wf") or {}),
                    "status_buckets": buckets,
                }
            )
            return 0

        cycle_id = insert_cycle(cur, organization_id=org, lane=lane)
        cnx.commit()
        gen = take_lane_lease(cur, org, lane, cycle_id=int(cycle_id))
        cnx.commit()
        result = restore_closed_day_published_snapshot_from_day_bags(
            cur,
            organization_id=org,
            shift_date_et=day,
            lane=lane,
            lease_generation=int(gen),
            cycle_id=int(cycle_id),
        )
        if not result.get("ok"):
            finish_cycle(cur, int(cycle_id), cycle_status="FAILED")
            release_lane_lease_if_owner(cur, org, lane, int(gen))
            cnx.commit()
            print(result)
            return 2
        finish_cycle(cur, int(cycle_id), cycle_status="SUCCESS")
        release_lane_lease_if_owner(cur, org, lane, int(gen))
        cnx.commit()
        print(result)
        return 0
    finally:
        try:
            cur.close()
        except Exception:
            pass
        cnx.close()


if __name__ == "__main__":
    sys.exit(main())
