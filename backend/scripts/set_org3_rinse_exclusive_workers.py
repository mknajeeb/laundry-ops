#!/usr/bin/env python3
"""
Set org-3 weekly schedule workers to Rinse Exclusive tab flags, except Guiying Lin.

Rinse Exclusive tab (frontend): can_work_rinse=true AND can_work_drop_off=false AND can_work_both=false
VeeWash tab: everyone else.

Only updates payroll_worker_profiles stream flags — no schedule/shift rows.

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.set_org3_rinse_exclusive_workers --dry-run
  python3 -m backend.scripts.set_org3_rinse_exclusive_workers --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG_ID = 3
VEEWASH_KEEP_NAME = "Guiying Lin"

RINSE_EXCLUSIVE_FLAGS = {
    "can_work_rinse": True,
    "can_work_drop_off": False,
    "can_work_both": False,
}


def normalize_display_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def is_rinse_exclusive(flags: dict[str, Any]) -> bool:
    """Mirror frontend weeklyScheduleEmployerTabs.isRinseExclusiveEmployee."""
    def stream_flag(value: Any) -> bool:
        return value is not False and value != 0

    rinse = stream_flag(flags.get("can_work_rinse"))
    drop_off = stream_flag(flags.get("can_work_drop_off"))
    both = stream_flag(flags.get("can_work_both"))
    return rinse and not drop_off and not both


def worker_snapshot(worker: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": worker.get("user_id"),
        "worker_profile_id": worker.get("worker_profile_id"),
        "display_name": worker.get("display_name"),
        "can_work_rinse": bool(worker.get("can_work_rinse")),
        "can_work_drop_off": bool(worker.get("can_work_drop_off")),
        "can_work_both": bool(worker.get("can_work_both")),
        "rinse_exclusive_tab": is_rinse_exclusive(worker),
    }


def should_skip_worker(worker: dict[str, Any], keep_name: str = VEEWASH_KEEP_NAME) -> bool:
    return normalize_display_name(worker.get("display_name")) == normalize_display_name(keep_name)


def flags_already_rinse_exclusive(worker: dict[str, Any]) -> bool:
    return (
        bool(worker.get("can_work_rinse"))
        and not bool(worker.get("can_work_drop_off"))
        and not bool(worker.get("can_work_both"))
    )


def plan_updates(workers: list[dict[str, Any]], keep_name: str = VEEWASH_KEEP_NAME) -> dict[str, Any]:
    keep_normalized = normalize_display_name(keep_name)
    to_update: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []

    for worker in workers:
        snap = worker_snapshot(worker)
        if should_skip_worker(worker, keep_name):
            skipped.append(snap)
            continue
        if flags_already_rinse_exclusive(worker):
            already.append(snap)
            continue
        to_update.append(
            {
                **snap,
                "after": {
                    **RINSE_EXCLUSIVE_FLAGS,
                    "rinse_exclusive_tab": True,
                },
            }
        )

    return {
        "organization_id": ORG_ID,
        "keep_on_veewash_name": keep_name,
        "keep_on_veewash_normalized": keep_normalized,
        "total_active_workers": len(workers),
        "skipped_veewash": skipped,
        "already_rinse_exclusive": already,
        "to_update": to_update,
    }


def apply_updates(conn, plan: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.payroll_schedule import ensure_worker_profile

    applied: list[dict[str, Any]] = []
    for item in plan.get("to_update") or []:
        uid = int(item["user_id"])
        ensure_worker_profile(conn, ORG_ID, uid)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE payroll_worker_profiles
               SET can_work_rinse=%s, can_work_drop_off=%s, can_work_both=%s
             WHERE organization_id=%s AND user_id=%s
            """,
            (1, 0, 0, ORG_ID, uid),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                f"Expected 1 row updated for user_id={uid} ({item.get('display_name')!r}), got {cur.rowcount}"
            )
        applied.append(item)
    conn.commit()
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move org-3 schedule workers to Rinse Exclusive tab except Guiying Lin"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes only")
    parser.add_argument("--apply", action="store_true", help="Apply stream flag updates")
    parser.add_argument("--org", type=int, default=ORG_ID, help="Organization id (default: 3)")
    parser.add_argument(
        "--keep-name",
        type=str,
        default=VEEWASH_KEEP_NAME,
        help="Worker display name to keep on VeeWash tab (default: Guiying Lin)",
    )
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.db import get_db
    from backend.payroll_schedule import list_schedule_workers_for_grid

    org = int(args.org)
    if org != ORG_ID:
        parser.error(f"This script is scoped to org {ORG_ID}; got --org {org}")

    conn = get_db()
    try:
        workers = list_schedule_workers_for_grid(conn, org)
        before = [worker_snapshot(w) for w in workers]
        plan = plan_updates(workers, keep_name=args.keep_name)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_dir = REPO_ROOT / "data"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"org3_rinse_exclusive_workers_{stamp}.json"

        report: dict[str, Any] = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "dry_run" if args.dry_run else "apply",
            "before": before,
            "plan": plan,
        }

        print(f"Org {org} active schedule workers: {plan['total_active_workers']}")
        print(f"Keep on VeeWash: {len(plan['skipped_veewash'])}")
        for row in plan["skipped_veewash"]:
            print(f"  SKIP {row['display_name']!r} (flags unchanged)")
        print(f"Already Rinse Exclusive: {len(plan['already_rinse_exclusive'])}")
        for row in plan["already_rinse_exclusive"]:
            print(f"  OK   {row['display_name']!r}")
        print(f"To update: {len(plan['to_update'])}")
        for row in plan["to_update"]:
            print(f"  SET  {row['display_name']!r} -> rinse=1 drop_off=0 both=0")

        if args.dry_run:
            report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"Dry-run report: {report_path}")
            return 0

        applied = apply_updates(conn, plan)
        after_workers = list_schedule_workers_for_grid(conn, org)
        after = [worker_snapshot(w) for w in after_workers]
        report["applied"] = applied
        report["after"] = after

        rinse_count = sum(1 for w in after if w["rinse_exclusive_tab"])
        veewash_count = len(after) - rinse_count
        report["tab_counts_after"] = {
            "rinse_exclusive": rinse_count,
            "veewash": veewash_count,
        }

        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Applied updates: {len(applied)}")
        print(f"After tab counts — Rinse Exclusive: {rinse_count}, VeeWash: {veewash_count}")
        print(f"Apply report: {report_path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
