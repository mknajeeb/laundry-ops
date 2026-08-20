"""Grant Mobile PIN Access team_status to named managers in an org.

Usage:
  python -m scripts.grant_team_status_mpa --organization-id 3 --execute
  python -m scripts.grant_team_status_mpa --organization-id 3 --dry-run

Default names (org 3 initial rollout): VeeWash Test, Sarah Kamran.
Does not grant any other modules and never defaults team_status for new hires.
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow `python scripts/grant_team_status_mpa.py` from repo root.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_NAMES = ("VeeWash Test", "Sarah Kamran")


def _match_name(row: dict, wanted: set[str]) -> str | None:
    display = (row.get("display_name") or "").strip()
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    for name in wanted:
        if display.lower() == name.lower() or full.lower() == name.lower():
            return name
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-id", type=int, required=True)
    parser.add_argument(
        "--name",
        action="append",
        dest="names",
        help="Employee display/full name (repeatable). Defaults to rollout pair.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = not args.execute or args.dry_run
    names = tuple(args.names) if args.names else DEFAULT_NAMES
    wanted = set(names)

    from backend.db import get_db
    from backend.employee_mobile_pin_access import (
        ensure_employee_mobile_pin_access_tables,
        resolve_employee_mobile_pin_access,
        save_employee_mobile_pin_access,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        ensure_employee_mobile_pin_access_tables(cur)
        oid = int(args.organization_id)
        cur.execute(
            """
            SELECT u.id AS user_id, u.display_name, u.username,
                   pp.first_name, pp.last_name
            FROM users u
            LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
            WHERE u.organization_id = %s AND u.active = 1
            ORDER BY u.id
            """,
            (oid,),
        )
        rows = cur.fetchall() or []
        matched = []
        for row in rows:
            hit = _match_name(row, wanted)
            if hit:
                matched.append((int(row["user_id"]), hit, row))

        print(f"organization_id={oid} dry_run={dry}")
        print(f"wanted={sorted(wanted)}")
        print(f"matched={[(uid, name) for uid, name, _ in matched]}")
        missing = wanted - {name for _, name, _ in matched}
        if missing:
            print(f"WARNING missing names: {sorted(missing)}")

        for uid, name, _row in matched:
            grants = resolve_employee_mobile_pin_access(cur, oid, uid)
            before = bool(grants.get("team_status"))
            grants["team_status"] = True
            print(f"  user_id={uid} name={name!r} team_status {before} -> True")
            if dry:
                continue
            save_employee_mobile_pin_access(
                cur,
                oid,
                uid,
                grants=grants,
                actor_user_id=None,
            )
        if not dry:
            conn.commit()
            print("committed")
        else:
            print("dry-run only; pass --execute to write")
        return 0 if not missing else 2
    finally:
        try:
            cur.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
