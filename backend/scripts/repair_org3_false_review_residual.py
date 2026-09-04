#!/usr/bin/env python3
"""Bounded org-3 residual false-Review repair (7 portal shells + 7ZS).

Usage:
  PYTHONPATH=. python3 backend/scripts/repair_org3_false_review_residual.py --dry-run
  PYTHONPATH=. python3 backend/scripts/repair_org3_false_review_residual.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RESIDUAL_SHELL_BAGS = (
    "1MKHJV1F9B",
    "2DJ1ZORNT4",
    "38YF6XU7H7",
    "4N3AHI06HJ",
    "95K7BJEKXZ",
    "DO9SNQDZ29",
    "E1I08UIBU1",
)
SEVEN_ZS_BAG = "7ZS1AE302U"
GENUINE_REVIEW = (
    ("BUEKCP33J1", 3585),
    ("BZ9AOU641G", 3963),
    ("C1PI050KEU", 3587),
)


def _load_env() -> None:
    for candidate in (
        Path("/Users/kamisb./laundry_app-revenue-cash-prod-fix/.env"),
        Path(".env"),
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--org", type=int, default=3)
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and args.dry_run:
        raise SystemExit("pass only one of --dry-run / --apply")

    _load_env()
    from backend.db import get_db
    from backend.rinse_order_instances import (
        heal_same_lifecycle_portal_orphan_ois,
        repair_open_portal_oi_with_stv_strong_completion,
    )
    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload
    from backend.business_time import business_today
    from datetime import timedelta

    dry_run = not args.apply
    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        heal = heal_same_lifecycle_portal_orphan_ois(
            cur,
            org,
            bag_ids=list(RESIDUAL_SHELL_BAGS),
            dry_run=dry_run,
        )
        seven_zs = repair_open_portal_oi_with_stv_strong_completion(
            cur, org, SEVEN_ZS_BAG, dry_run=dry_run
        )
        if args.apply:
            conn.commit()

        today = business_today()
        yesterday = today - timedelta(days=1)
        # Acceptance snapshot (CW is date-free; selected date only affects Completed).
        cw_today = get_canonical_wf_workload(cur, org, today)
        cw_yday = get_canonical_wf_workload(cur, org, yesterday)

        def _cw_summary(wl: dict) -> dict:
            cw = (
                wl.get("current_workload")
                if isinstance(wl.get("current_workload"), dict)
                else wl
            )
            items = list(cw.get("items") or [])
            review = [
                {
                    "bag_id": i.get("bag_id"),
                    "order_instance_id": i.get("order_instance_id"),
                    "review_reason_codes": i.get("review_reason_codes"),
                }
                for i in items
                if i.get("status") == "review_required"
            ]
            return {
                "open": int((cw.get("counts") or {}).get("open") or len(cw.get("open") or [])),
                "pending": int(
                    (cw.get("counts") or {}).get("pending") or len(cw.get("pending") or [])
                ),
                "review": int(
                    (cw.get("counts") or {}).get("review") or len(cw.get("review") or [])
                ),
                "review_rows": review,
                "open_bags": sorted(cw.get("open") or []),
                "review_bags": sorted(cw.get("review") or []),
            }

        report = {
            "dry_run": dry_run,
            "organization_id": org,
            "heal": heal,
            "seven_zs": seven_zs,
            "genuine_protect": [
                {"bag_id": b, "order_instance_id": oid} for b, oid in GENUINE_REVIEW
            ],
            "cw_today": _cw_summary(cw_today),
            "cw_yesterday": _cw_summary(cw_yday),
            "as_of": {"today": str(today), "yesterday": str(yesterday)},
        }
        out_dir = Path("backups")
        out_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"repair_org{org}_false_review_residual_{stamp}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": dry_run,
                    "report_path": str(path),
                    "heal_candidates": len(heal.get("candidates") or []),
                    "heal_healed": len(heal.get("healed") or []),
                    "heal_ambiguous": heal.get("ambiguous") or [],
                    "seven_zs": {
                        "ok": seven_zs.get("ok"),
                        "error": seven_zs.get("error"),
                        "action": seven_zs.get("action"),
                        "stv_anchor": seven_zs.get("stv_anchor"),
                        "completion_at": seven_zs.get("completion_at"),
                        "completion_kind": seven_zs.get("completion_kind"),
                        "portal_shell_ois": seven_zs.get("portal_shell_ois"),
                        "stamped_oi": seven_zs.get("stamped_oi"),
                    },
                    "cw_today": report["cw_today"],
                    "cw_yesterday_counts": {
                        k: report["cw_yesterday"][k]
                        for k in ("open", "pending", "review")
                    },
                },
                indent=2,
                default=str,
            )
        )
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
