#!/usr/bin/env python3
"""Cutover: reconstruct Aug 22 WF canonical cycles from durable evidence and publish."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main() -> int:
    from backend.db import get_db
    from backend.rinse_wf_service_cycle import reconstruct_cycles_from_durable_evidence
    from backend.rinse_wf_service_cycle_compat import project_canonical_cycles_to_day_snapshot

    org = int(os.getenv("WF_CUTOVER_ORG_ID") or "3")
    day = date.fromisoformat(os.getenv("WF_CUTOVER_DATE") or "2026-08-22")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        # WF membership bags for Aug 22 as seed list (not authority for lifecycle)
        cur.execute(
            """
            SELECT bag_id FROM rinse_shift_monitor_day_bags
            WHERE organization_id=%s AND shift_date_et=%s AND UPPER(service_type)='WF'
            """,
            (org, day.isoformat()),
        )
        seed = [r["bag_id"] for r in (cur.fetchall() or [])]
        recon = reconstruct_cycles_from_durable_evidence(cur, org, seed)
        conn.commit()
        proj = project_canonical_cycles_to_day_snapshot(cur, org, day, force=True)
        conn.commit()
        print({"reconstruct": recon, "projection": {k: proj.get(k) for k in proj if k != "day"}})
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
