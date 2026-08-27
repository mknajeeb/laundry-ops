#!/usr/bin/env python3
"""Run terminal canonical WF day projection N times and report membership stability."""

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
        before = snapshot(cur, target)
        hashes: list[str] = []
        for i in range(passes):
            terminal_project_canonical_wf_day_snapshot(cur, ORG, target, force=True)
            conn.commit()
            after = snapshot(cur, target)
            hashes.append(after["bag_id_hash"])
        final = snapshot(cur, target)
        out = {
            "target_date_et": target.isoformat(),
            "passes": passes,
            "before": {k: v for k, v in before.items() if k != "bag_ids"},
            "after": {k: v for k, v in final.items() if k != "bag_ids"},
            "projection_hashes": hashes,
            "all_identical": len(set(hashes)) == 1,
        }
        print(json.dumps(out, indent=2, default=str))
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
