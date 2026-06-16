#!/usr/bin/env python3
"""
Seed direct-deposit bank details into hr_extended_profiles.work_json.direct_deposit.

Matches employees by normalized full name against payroll_profiles.
Run from repo root: python -m backend.scripts.seed_w2_direct_deposit
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import app
from backend.db import get_db
from backend.hr_compliance import ensure_hr_extended_profiles_table, upsert_hr_extended_profile

# From accountant spreadsheet (routing numbers preserved as text with leading zeros).
SEED_ROWS = [
    {
        "name": "Tarannum Mithila",
        "bank_account": "483104450186",
        "bank_routing": "021000322",
        "account_type": "checking",
    },
    {
        "name": "Jaspreet Singh",
        "bank_account": "36378614132",
        "bank_routing": "031176110",
        "account_type": "checking",
    },
    {
        "name": "Varun Kumar Mongia",
        "bank_account": "1290517897167",
        "bank_routing": "041215663",
        "account_type": "checking",
    },
    {
        "name": "Alex Coaxum",
        "bank_account": "483088875599",
        "bank_routing": "021000322",
        "account_type": "checking",
    },
    {
        "name": "Paola Almiron",
        "bank_account": "6782562960",
        "bank_routing": "021000089",
        "account_type": "checking",
    },
    {
        "name": "Evelyn Hernandez",
        "bank_account": "36326801166",
        "bank_routing": "031176110",
        "account_type": "checking",
    },
]


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main() -> int:
    with app.app_context():
        conn = get_db()
        try:
            cur = conn.cursor(dictionary=True)
            ensure_hr_extended_profiles_table(cur)
            cur.execute(
                """
                SELECT pp.user_id, pp.first_name, pp.last_name, u.organization_id
                FROM payroll_profiles pp
                JOIN users u ON u.id = pp.user_id
                """
            )
            profiles = cur.fetchall() or []
            by_name = {}
            for p in profiles:
                nm = norm_name(f"{p.get('first_name') or ''} {p.get('last_name') or ''}")
                by_name[nm] = p

            updated = []
            missing = []
            for row in SEED_ROWS:
                key = norm_name(row["name"])
                prof = by_name.get(key)
                if not prof:
                    missing.append(row["name"])
                    continue
                uid = int(prof["user_id"])
                oid = int(prof.get("organization_id") or 1)
                cur.execute(
                    "SELECT work_json FROM hr_extended_profiles WHERE user_id=%s LIMIT 1",
                    (uid,),
                )
                hr = cur.fetchone() or {}
                wj = hr.get("work_json")
                if isinstance(wj, str):
                    try:
                        wj = json.loads(wj)
                    except Exception:
                        wj = {}
                if isinstance(wj, list):
                    wj = {}
                if not isinstance(wj, dict):
                    wj = {}
                wj = dict(wj)
                wj["direct_deposit"] = {
                    "bank_account": row["bank_account"],
                    "bank_routing": row["bank_routing"],
                    "account_type": row["account_type"],
                    "deposit_full": True,
                }
                upsert_hr_extended_profile(conn, uid, oid, {"work_json": wj})
                updated.append(row["name"])

            conn.commit()
            print(f"Updated {len(updated)} employee(s): {', '.join(updated) or '—'}")
            if missing:
                print(f"Not found in payroll_profiles: {', '.join(missing)}")
            return 0 if not missing else 1
        finally:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
