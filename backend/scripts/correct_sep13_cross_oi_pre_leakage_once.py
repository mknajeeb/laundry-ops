#!/usr/bin/env python3
"""Bounded Sep 13 PRE nulling for two OIs only — dry-run by default.

Targets (do NOT delete/exclude/move OIs; do NOT delete historical observations):
  8MNDJDAV8D / OI 5493  → Sep 13 day_bag PRE = NULL
  9YTC6BJWAY / OI 5517  → Sep 13 day_bag PRE = NULL

Preserve:
  OI 5114 / Sep 11 PRE 26.7
  OI 5271 / Sep 12 PRE 16.3

Usage (from repo root):
  PYTHONPATH=. python3 backend/scripts/correct_sep13_cross_oi_pre_leakage_once.py
  PYTHONPATH=. python3 backend/scripts/correct_sep13_cross_oi_pre_leakage_once.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ORG = 3
DAY = date(2026, 9, 13)
TARGETS = (
    {
        "bag_id": "8MNDJDAV8D",
        "order_instance_id": 5493,
        "prior_oi": 5114,
        "prior_day": date(2026, 9, 11),
    },
    {
        "bag_id": "9YTC6BJWAY",
        "order_instance_id": 5517,
        "prior_oi": 5271,
        "prior_day": date(2026, 9, 12),
    },
)
EXPECTED_AFTER = {
    "pre_lbs": 2546.5,
    "pre_bags": 113,
    "post_lbs": 2399.4,
    "post_bags": 113,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write NULL PRE for the two Sep 13 day_bags only.",
    )
    parser.add_argument("--org", type=int, default=ORG)
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")

    from backend.db import get_db
    from backend.management_today import load_wf_day_weight_totals
    from backend.rinse_veewash_review import load_bag_weight_map

    report: dict = {
        "org": int(args.org),
        "day": DAY.isoformat(),
        "apply": bool(args.apply),
        "targets": [],
        "expected_after": EXPECTED_AFTER,
    }

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        before = load_wf_day_weight_totals(cur, int(args.org), DAY)
        report["before_totals"] = {
            "pre_lbs": before.get("pre_lbs") or before.get("pre_weight_lbs"),
            "pre_bags": before.get("pre_weight_bag_count"),
            "post_lbs": before.get("post_lbs") or before.get("post_weight_lbs"),
            "post_bags": before.get("post_weight_bag_count"),
        }

        for t in TARGETS:
            bid = t["bag_id"]
            wm = load_bag_weight_map(
                cur, int(args.org), [bid], selected_date_et=DAY
            )
            live_pre = (wm.get(bid) or {}).get("pre_weight_lbs")
            cur.execute(
                """
                SELECT bag_id, pre_weight_lbs, post_weight_lbs
                FROM rinse_shift_monitor_day_bags
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                LIMIT 1
                """,
                (int(args.org), DAY, bid),
            )
            day_row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT bag_id, pre_weight_lbs, post_weight_lbs
                FROM rinse_shift_monitor_day_bags
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                LIMIT 1
                """,
                (int(args.org), t["prior_day"], bid),
            )
            prior_day_row = cur.fetchone() or {}
            entry = {
                **t,
                "prior_day": t["prior_day"].isoformat(),
                "live_resolver_pre_lbs": live_pre,
                "sep13_day_bag_pre": day_row.get("pre_weight_lbs"),
                "sep13_day_bag_post": day_row.get("post_weight_lbs"),
                "prior_day_bag_pre": prior_day_row.get("pre_weight_lbs"),
            }
            if args.apply and day_row:
                cur.execute(
                    """
                    UPDATE rinse_shift_monitor_day_bags
                    SET pre_weight_lbs = NULL
                    WHERE organization_id = %s
                      AND shift_date_et = %s
                      AND bag_id = %s
                    """,
                    (int(args.org), DAY, bid),
                )
                entry["updated_rows"] = cur.rowcount
            report["targets"].append(entry)

        if args.apply:
            conn.commit()
        after = load_wf_day_weight_totals(cur, int(args.org), DAY)
        report["after_totals"] = {
            "pre_lbs": after.get("pre_lbs") or after.get("pre_weight_lbs"),
            "pre_bags": after.get("pre_weight_bag_count"),
            "post_lbs": after.get("post_lbs") or after.get("post_weight_lbs"),
            "post_bags": after.get("post_weight_bag_count"),
        }
        report["matches_expected"] = (
            report["after_totals"]["pre_lbs"] == EXPECTED_AFTER["pre_lbs"]
            and report["after_totals"]["pre_bags"] == EXPECTED_AFTER["pre_bags"]
            and report["after_totals"]["post_lbs"] == EXPECTED_AFTER["post_lbs"]
            and report["after_totals"]["post_bags"] == EXPECTED_AFTER["post_bags"]
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out_path = (
        Path("backups")
        / f"sep13_cross_oi_pre_correction_{'apply' if args.apply else 'dry'}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
