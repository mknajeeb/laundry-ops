#!/usr/bin/env python3
"""Narrow org-3 WF ops maintenance control (ON / STATUS / OFF).

Touches ONLY system_settings key ``wf_ops_maintenance`` for the given org.

  python -m backend.scripts.wf_ops_maintenance_once --org 3 --status
  python -m backend.scripts.wf_ops_maintenance_once --org 3 --on
  python -m backend.scripts.wf_ops_maintenance_once --org 3 --off

Does NOT pause Azure, run reset, or enable retention.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for env_path in (REPO / ".env", Path("/Users/kamisb./laundry_app/.env")):
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break

sys.path.insert(0, str(REPO))

ALLOWED_ORGS = frozenset({3})


def main() -> int:
    p = argparse.ArgumentParser(description="WF ops maintenance flag for org 3")
    p.add_argument("--org", type=int, required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="Read-only status")
    g.add_argument("--on", action="store_true", help="Set wf_ops_maintenance=1")
    g.add_argument("--off", action="store_true", help="Set wf_ops_maintenance=0")
    args = p.parse_args()

    if int(args.org) not in ALLOWED_ORGS:
        print(f"REFUSED: organization_id={args.org} not allowed")
        return 2

    from backend.db import get_db
    from backend.wf_ops_reset_epoch import (
        WF_OPS_MAINTENANCE_KEY,
        get_wf_ops_maintenance,
        set_wf_ops_maintenance,
    )

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        before = get_wf_ops_maintenance(cur, args.org)
        action = "status"
        if args.on:
            action = "on"
            set_wf_ops_maintenance(cur, args.org, True)
            conn.commit()
        elif args.off:
            action = "off"
            set_wf_ops_maintenance(cur, args.org, False)
            conn.commit()
        after = get_wf_ops_maintenance(cur, args.org)
        report = {
            "organization_id": int(args.org),
            "action": action,
            "settings_key": WF_OPS_MAINTENANCE_KEY,
            "maintenance_on_before": before,
            "maintenance_on_after": after,
            "touched_keys": [WF_OPS_MAINTENANCE_KEY] if action != "status" else [],
        }
        print(json.dumps(report, indent=2))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
