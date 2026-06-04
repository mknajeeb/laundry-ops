#!/usr/bin/env python3
"""
Seed sample workers for Payroll Planning staging QA.

Requires PAYROLL_PLANNING_ALLOW_MIGRATE=1 or a database name containing staging/test.
Does not delete existing users — creates/updates payroll_worker_profiles by email prefix.

Usage:
  PAYROLL_PLANNING_ALLOW_MIGRATE=1 python3 scripts/seed_payroll_planning_staging_workers.py --org-id 1
  PAYROLL_PLANNING_ALLOW_MIGRATE=1 python3 scripts/seed_payroll_planning_staging_workers.py --org-id 1 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from backend.db import get_db  # noqa: E402


def _migration_allowed() -> bool:
    if os.getenv("PAYROLL_PLANNING_ALLOW_MIGRATE") == "1":
        return True
    db = (os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "").lower()
    return "staging" in db or "test" in db


SAMPLES = [
    # email_suffix, display, category, rate, max_h/week, notes
    ("planning-w2-alice", "Planning W2 Alice", "w2", 18.0, 40, "complete"),
    ("planning-w2-bob", "Planning W2 Bob", "w2", 19.5, 40, "complete"),
    ("planning-1099-carla", "Planning 1099 Carla", "1099", 22.0, 45, "complete"),
    ("planning-1099-dan", "Planning 1099 Dan", "1099", 21.0, 45, "complete"),
    ("planning-temp-eve", "Planning Temp Eve", "temp", 20.0, 30, "complete"),
    ("planning-norate-frank", "Planning No Rate Frank", "w2", None, 40, "missing rate"),
    ("planning-noavail-grace", "Planning No Avail Grace", "w2", 17.0, 40, "no availability rows"),
    ("planning-noskill-henry", "Planning No Skill Henry", "w2", 18.0, 40, "no role skills"),
    ("planning-ot-irene", "Planning OT Irene", "w2", 20.0, 40, "near OT — seed ~36h schedule separately"),
    ("planning-wrongloc-jake", "Planning Wrong Loc Jake", "w2", 18.0, 40, "geofence mismatch"),
]


def main() -> int:
    if not _migration_allowed():
        print("Refusing: set PAYROLL_PLANNING_ALLOW_MIGRATE=1 or use a staging/test database.")
        return 1

    ap = argparse.ArgumentParser()
    ap.add_argument("--org-id", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_db()
    c = conn.cursor(dictionary=True)
    try:
        from backend.payroll_schedule import ensure_payroll_schedule_tables, save_scheduling_profile

        ensure_payroll_schedule_tables(c)
        conn.commit()

        for suffix, name, cat, rate, max_h, note in SAMPLES:
            email = f"{suffix}@staging.local"
            c.execute(
                "SELECT id FROM users WHERE email=%s AND organization_id=%s LIMIT 1",
                (email, args.org_id),
            )
            row = c.fetchone()
            if not row:
                if args.dry_run:
                    print(f"[dry-run] would create user {email} ({note})")
                    continue
                c.execute(
                    """
                    INSERT INTO users (organization_id, email, display_name, role, active)
                    VALUES (%s, %s, %s, 'EMPLOYEE', 1)
                    """,
                    (args.org_id, email, name),
                )
                user_id = c.lastrowid
            else:
                user_id = row["id"]

            profile = {
                "worker_category": cat,
                "default_hourly_rate": rate,
                "max_hours_per_week": max_h,
                "overtime_threshold_hours": 40,
                "scheduling_active": 1,
                "notes": f"Payroll planning QA seed — {note}",
            }
            if suffix == "planning-wrongloc-jake":
                profile["preferred_geofence_ids"] = []  # force location warnings in UI

            if args.dry_run:
                print(f"[dry-run] profile user_id={user_id} {email} ({note})")
                continue

            save_scheduling_profile(conn, args.org_id, int(user_id), profile, actor_user_id=None)

            if suffix == "planning-noavail-grace":
                c.execute("DELETE FROM payroll_worker_availability WHERE user_id=%s", (user_id,))
            if suffix == "planning-noskill-henry":
                c.execute("DELETE FROM payroll_worker_role_skills WHERE user_id=%s", (user_id,))

            print(f"OK user_id={user_id} {email} — {note}")

        if not args.dry_run:
            conn.commit()
        print("Seed complete. Open /employees and complete skills/availability for green badges where needed.")
        return 0
    finally:
        c.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
