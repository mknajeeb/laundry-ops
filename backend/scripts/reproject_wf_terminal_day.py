#!/usr/bin/env python3
"""Run terminal canonical WF day projection N times and report membership stability.

Uses ``get_canonical_wf_workload`` via ``terminal_project_canonical_wf_day_snapshot``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORG = 3


def _bag_hash(bag_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(bag_ids)).encode()).hexdigest()[:16]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: reproject_wf_terminal_day.py YYYY-MM-DD [passes=3]", file=sys.stderr)
        return 2
    target = date.fromisoformat(sys.argv[1])
    passes = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    from backend.db import get_db
    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload
    from backend.rinse_wf_service_cycle_compat import terminal_project_canonical_wf_day_snapshot

    import importlib.util

    snap_path = Path(__file__).resolve().parent / "wf_acceptance_snapshot.py"
    spec = importlib.util.spec_from_file_location("wf_acceptance_snapshot", snap_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    snapshot = mod.snapshot

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        derived = get_canonical_wf_workload(cur, ORG, target)
        before = snapshot(cur, target)
        hashes: list[str] = []
        derived_hashes: list[str] = []
        for _i in range(passes):
            d = get_canonical_wf_workload(cur, ORG, target)
            derived_hashes.append(_bag_hash(sorted(d["bag_ids"])))
            terminal_project_canonical_wf_day_snapshot(cur, ORG, target, force=True)
            conn.commit()
            after = snapshot(cur, target)
            hashes.append(after["bag_id_hash"])
        final = snapshot(cur, target)
        out = {
            "target_date_et": target.isoformat(),
            "passes": passes,
            "derived_before_persist": {
                "workload": derived["counts"]["workload"],
                "completed": derived["counts"]["completed"],
                "pending": derived["counts"]["pending"],
                "review": derived["counts"]["review"],
                "new_today": derived["counts"]["new_today"],
                "carryover": derived["counts"]["carryover"],
                "missing_from_portal": derived["counts"]["missing_from_portal"],
                "historical_completed": len(derived["historical_completed_in_workload"]),
                "arithmetic_ok": derived["arithmetic_ok"],
                "invariants_ok": derived["invariants_ok"],
                "bag_id_hash": _bag_hash(sorted(derived["bag_ids"])),
            },
            "before": {k: v for k, v in before.items() if k != "bag_ids"},
            "after": {k: v for k, v in final.items() if k != "bag_ids"},
            "projection_hashes": hashes,
            "derived_hashes": derived_hashes,
            "all_identical": len(set(hashes)) == 1,
            "derived_identical": len(set(derived_hashes)) == 1,
        }
        print(json.dumps(out, indent=2, default=str))
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
