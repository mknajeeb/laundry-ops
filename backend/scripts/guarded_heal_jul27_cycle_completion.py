#!/usr/bin/env python3
"""Guarded Jul 27 org3 WF completion heal — frozen membership only.

Run ONLY after Release A is live on production.

Does NOT change carryover policy. Freezes membership to the persisted 94 IDs
before rebuild so an OPEN day cannot admit new bags during the heal.

Usage:
  # dry-run (default): rebuild in memory, report diffs, write no DB changes
  python backend/scripts/guarded_heal_jul27_cycle_completion.py

  # apply: persist snapshot after guards pass
  python backend/scripts/guarded_heal_jul27_cycle_completion.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Prefer laundry_app .env for DB credentials when running from a worktree.
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

ORG = 3
DAY = date(2026, 7, 27)
EXPECTED_FIVE = (
    "11Q5I8QGW9",
    "59KNGSUWLO",
    "9LSH830YYF",
    "AF04FPMZGL",
    "N3R07Y4TSB",
)


def _norm(bid) -> str:
    return str(bid or "").strip().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist after guards pass")
    parser.add_argument(
        "--out",
        default="/tmp/guarded_heal_jul27_report.json",
        help="Report JSON path",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.rinse_processing_settings import (
        DEFAULT_FACILITY_ENTRY_RACKS,
        get_processing_settings,
    )
    from backend.rinse_veewash_shift_day import (
        build_step1_headline_summary,
        derive_shift_day_status,
        get_day_record,
        get_step1_activation_date,
        load_day_bags,
        persist_day_snapshot,
        _commit,
    )
    from backend.rinse_veewash_workload import build_veewash_daily_workload_from_membership

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    day = get_day_record(cur, ORG, DAY)
    bags = load_day_bags(cur, ORG, DAY)
    wf = [b for b in bags if str(b.get("service_type") or "WF").upper() == "WF"]
    before_by = {_norm(b.get("bag_id")): b for b in wf}
    frozen = sorted(before_by)
    if len(frozen) != 94:
        print(f"ABORT: expected 94 persisted WF members, got {len(frozen)}")
        return 2

    before_status = {bid: str(b.get("effective_status") or "") for bid, b in before_by.items()}
    before_rush = {bid: str(b.get("rush_status") or "") for bid, b in before_by.items()}
    before_mgr = {bid: int(b.get("manager_edit_version") or 0) for bid, b in before_by.items()}
    headline = (day or {}).get("headline") or {}

    settings = get_processing_settings(cur, ORG)
    racks = settings.get("facility_entry_racks") or list(DEFAULT_FACILITY_ENTRY_RACKS)

    wl = build_veewash_daily_workload_from_membership(
        cur,
        ORG,
        selected_date_et=DAY,
        frozen_member_ids=frozen,
        entry_racks=racks,
    )
    rows = wl.get("rows") or []
    after_ids = sorted({_norm(r.get("bag_id")) for r in rows if r.get("bag_id")})
    if after_ids != frozen:
        print("ABORT: rebuilt membership diverged from frozen 94")
        print("only_in_rebuild", sorted(set(after_ids) - set(frozen))[:20])
        print("missing_from_rebuild", sorted(set(frozen) - set(after_ids))[:20])
        return 3

    after_status = {
        _norm(r.get("bag_id")): str(r.get("outcome") or r.get("effective_status") or "")
        for r in rows
    }
    # Map outcome names to day-bag effective_status vocabulary
    def _as_eff(v: str) -> str:
        v = (v or "").lower()
        if v in ("completed", "complete"):
            return "completed"
        if v in ("pending",):
            return "pending"
        if v in ("review_required", "review"):
            return "review_required"
        return v

    after_eff = {bid: _as_eff(st) for bid, st in after_status.items()}

    changed = sorted(
        bid for bid in frozen if before_status.get(bid) != after_eff.get(bid)
    )
    unexpected = [bid for bid in changed if bid not in EXPECTED_FIVE]
    missing_five = [
        bid
        for bid in EXPECTED_FIVE
        if not (
            before_status.get(bid) == "pending" and after_eff.get(bid) == "completed"
        )
    ]
    mgr_nonzero = [bid for bid in EXPECTED_FIVE if before_mgr.get(bid, 0) != 0]
    rush_changed = [
        bid for bid in frozen if before_rush.get(bid) != str((before_by[bid].get("rush_status") or ""))
    ]
    # rush is unchanged by rebuild unless rows rewrite rush — compare before vs rebuilt row rush if present
    rush_changed = []
    row_by = {_norm(r.get("bag_id")): r for r in rows}
    for bid in frozen:
        before_r = before_rush.get(bid) or ""
        after_r = str(
            row_by.get(bid, {}).get("rush_flag")
            or row_by.get(bid, {}).get("rush_status")
            or row_by.get(bid, {}).get("effective_rush")
            or before_r
        )
        # Normalize NON-RUSH vs Non-Rush
        def _rn(x: str) -> str:
            x = (x or "").upper().replace("_", "-")
            if "NON" in x:
                return "NON-RUSH"
            if "RUSH" in x:
                return "RUSH"
            return x

        if _rn(before_r) and _rn(after_r) and _rn(before_r) != _rn(after_r):
            rush_changed.append(bid)

    completed_n = sum(1 for bid in frozen if after_eff.get(bid) == "completed")
    pending_n = sum(1 for bid in frozen if after_eff.get(bid) == "pending")
    review_n = sum(1 for bid in frozen if after_eff.get(bid) == "review_required")

    report = {
        "mode": "apply" if args.apply else "dry_run",
        "org": ORG,
        "day": DAY.isoformat(),
        "day_status": (day or {}).get("status"),
        "frozen_membership": 94,
        "before_headline": {
            "completed": headline.get("completed"),
            "pending": headline.get("pending"),
            "review_required": (headline.get("exceptions") or {}).get("review_required"),
            "total_workload": headline.get("total_workload") or headline.get("active_workload"),
        },
        "after_counts": {
            "total": 94,
            "completed": completed_n,
            "pending": pending_n,
            "review": review_n,
        },
        "changed_ids": changed,
        "unexpected_changes": unexpected,
        "missing_five_transitions": missing_five,
        "manager_edit_nonzero": mgr_nonzero,
        "rush_changed": rush_changed,
        "guards_ok": (
            not unexpected
            and not missing_five
            and not mgr_nonzero
            and not rush_changed
            and completed_n == 86
            and pending_n == 8
            and review_n == 0
            and after_ids == frozen
        ),
        "five_before_after": {
            bid: {
                "before": before_status.get(bid),
                "after": after_eff.get(bid),
                "manager_edit_version": before_mgr.get(bid),
                "rush_status": before_rush.get(bid),
                "stale_completion_ts": str(
                    before_by[bid].get("canonical_completion_timestamp")
                ),
            }
            for bid in EXPECTED_FIVE
        },
        "persisted": False,
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    print(json.dumps({k: report[k] for k in (
        "mode", "guards_ok", "after_counts", "changed_ids", "unexpected_changes",
        "missing_five_transitions", "five_before_after"
    )}, indent=2, default=str))

    if not report["guards_ok"]:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
        print(f"ABORT: guards failed; wrote {args.out}; no DB writes")
        return 4

    if not args.apply:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
        print(f"DRY-RUN OK; wrote {args.out}; no DB writes")
        return 0

    activation = get_step1_activation_date(cur, ORG)
    summary = build_step1_headline_summary(
        wl, selected_date_et=DAY, activation_date=activation or DAY
    )
    if isinstance(wl.get("membership"), dict) and "membership" not in (summary or {}):
        summary = dict(summary)
        summary["membership"] = wl.get("membership")
    from backend.rinse_hd_day_presentation import finalize_hd_step1_summary
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

    summary = finalize_hd_step1_summary(
        summary,
        selected_date_et=DAY,
        membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
        cursor=cur,
        organization_id=ORG,
    )
    summary = attach_specialty_metrics_to_summary(cur, ORG, DAY, summary)

    persist_day_snapshot(
        cur,
        ORG,
        DAY,
        workload=wl,
        summary=summary,
        status=derive_shift_day_status(
            summary,
            current_status=(day or {}).get("status"),
            membership=wl.get("membership") if isinstance(wl.get("membership"), dict) else None,
        ),
        force=True,
    )
    _commit(cur)

    # Re-read verification
    bags2 = load_day_bags(cur, ORG, DAY)
    wf2 = [b for b in bags2 if str(b.get("service_type") or "WF").upper() == "WF"]
    ids2 = sorted({_norm(b.get("bag_id")) for b in wf2})
    st2 = {_norm(b.get("bag_id")): str(b.get("effective_status") or "") for b in wf2}
    day2 = get_day_record(cur, ORG, DAY)
    h2 = (day2 or {}).get("headline") or {}
    report["persisted"] = True
    report["post_persist"] = {
        "membership": len(ids2),
        "membership_match": ids2 == frozen,
        "completed": sum(1 for s in st2.values() if s == "completed"),
        "pending": sum(1 for s in st2.values() if s == "pending"),
        "headline_completed": h2.get("completed"),
        "headline_pending": h2.get("pending"),
        "five": {bid: st2.get(bid) for bid in EXPECTED_FIVE},
    }
    Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["post_persist"], indent=2, default=str))
    if (
        report["post_persist"]["membership"] != 94
        or report["post_persist"]["completed"] != 86
        or report["post_persist"]["pending"] != 8
        or any(report["post_persist"]["five"].get(b) != "completed" for b in EXPECTED_FIVE)
    ):
        print("WARN: post-persist verification mismatch — inspect and rollback if needed")
        return 5
    print(f"APPLY OK; wrote {args.out}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
