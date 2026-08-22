#!/usr/bin/env python3
"""Minimal cutover: seed current open + today's completed WF cycles; project today only."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main() -> int:
    from backend.db import get_db
    from backend.rinse_wf_service_cycle import (
        prune_historical_canonical_cycles,
        seed_minimal_cutover_cycles,
    )
    from backend.rinse_wf_service_cycle_compat import project_canonical_cycles_to_day_snapshot

    org = int(os.getenv("WF_CUTOVER_ORG_ID") or "3")
    day = date.fromisoformat(os.getenv("WF_CUTOVER_DATE") or "2026-08-22")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        pruned = prune_historical_canonical_cycles(cur, org, day)
        seeded = seed_minimal_cutover_cycles(cur, org, day)
        conn.commit()
        proj = project_canonical_cycles_to_day_snapshot(cur, org, day, force=True)
        conn.commit()
        print(
            {
                "pruned": pruned,
                "seeded": seeded,
                "projection": {k: proj.get(k) for k in proj if k != "day"},
            }
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
