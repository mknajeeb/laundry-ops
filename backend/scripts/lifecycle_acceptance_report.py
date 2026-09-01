#!/usr/bin/env python3
"""Lifecycle workload acceptance metrics (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORG = 3


def _discovery_counts(cur, org: int, day: date) -> dict[str, int]:
    from backend.ta_helpers import table_exists

    wf = hd = 0
    if table_exists(cur, "rinse_cleaner_ticket_presence"):
        cur.execute(
            """
            SELECT service_type, COUNT(*) AS n
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND active = 1
            GROUP BY service_type
            """,
            (org,),
        )
        for row in cur.fetchall() or []:
            svc = str(row.get("service_type") or "").strip().upper()
            n = int(row.get("n") or 0)
            if svc in ("WF", "WASH_AND_FOLD", "WASH AND FOLD"):
                wf += n
            elif svc in ("HD", "HANG_DRY", "HANG DRY"):
                hd += n
    return {"discovery_wf": wf, "discovery_hd": hd}


def report(cur, day: date) -> dict:
    from backend.business_time import business_today
    from backend.management_rinse_hd import build_rinse_hd_day
    from backend.management_rinse_wf_review import compute_canonical_wf_review_membership
    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload

    wl = get_canonical_wf_workload(cur, ORG, day)
    open_only = (wl.get("pending") or frozenset()) | (wl.get("review") or frozenset())
    review_mem = compute_canonical_wf_review_membership(cur, ORG, day) or {}
    mfp_ids = review_mem.get("missing_from_portal") or []

    hd = build_rinse_hd_day(cur, ORG, day, status="all")
    hd_summary = hd.get("summary") or {}
    hd_counts = hd.get("counts") or {}

    disc = _discovery_counts(cur, ORG, day)

    return {
        "date_et": day.isoformat(),
        "business_today_et": business_today().isoformat(),
        "wf_current_open": len(open_only),
        "wf_completed_today": len(wl.get("completed") or []),
        "wf_review": len(wl.get("review") or []),
        "wf_mfp": len(mfp_ids),
        "hd_current_open": int(hd_summary.get("open_orders") or 0),
        "hd_completed_today": int(hd_summary.get("completed_today") or 0),
        "discovery_wf": disc["discovery_wf"],
        "discovery_hd": disc["discovery_hd"],
        "wf_invariants_ok": bool(wl.get("invariants_ok")),
        "wf_source": wl.get("source"),
        "hd_admitted_total": int(hd_summary.get("admitted_total") or 0),
        "hd_missing_from_portal": int(hd_counts.get("missing_from_portal") or 0),
        "wf_open_sample": sorted(open_only)[:5],
        "wf_completed_sample": sorted(wl.get("completed") or [])[:5],
        "hd_open_sample": [
            o.get("bag_id")
            for o in (hd.get("orders") or [])
            if str(o.get("status") or "") not in ("complete", "Complete")
        ][:5],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lifecycle_acceptance_report.py YYYY-MM-DD", file=sys.stderr)
        return 2
    day = date.fromisoformat(sys.argv[1])
    from backend.db import get_db

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        out = report(cur, day)
        print(json.dumps(out, indent=2, default=str))
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
