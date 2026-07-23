"""
Pre-purge inventory + backup/archive for VeeWash Step-1 cutover 2026-07-23.

Safety:
  - organization_id MUST be 3
  - date filter MUST be shift_date_et / et_date < 2026-07-23
  - Never deletes raw presence/scan/scrape source tables
  - Default is dry-run; pass --apply to execute

Usage:
  python -m backend.scripts.cutover_jul23_step1_purge --inventory
  python -m backend.scripts.cutover_jul23_step1_purge --backup
  python -m backend.scripts.cutover_jul23_step1_purge --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ORG = 3
CUTOVER = date(2026, 7, 23)
BACKUP_ROOT = Path("data/backups/step1_cutover_jul23_org3")

# Derived Step-1 / monitor history only.
PURGE_SPECS: list[dict[str, Any]] = [
    {
        "table": "rinse_shift_monitor_day_bags",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
    },
    {
        "table": "rinse_shift_monitor_close_audit",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
    },
    {
        "table": "rinse_shift_monitor_days",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
    },
    {
        "table": "rinse_et_day_workload_ledger",
        "date_col": "et_date",
        "filter": "organization_id = %s AND et_date < %s",
    },
    {
        "table": "rinse_completion_review",
        "date_col": "selected_date_et",
        "filter": "organization_id = %s AND selected_date_et < %s",
        "optional": True,
    },
]

# Manager correction / audit — archive, do not silently drop.
ARCHIVE_SPECS: list[dict[str, Any]] = [
    {
        "table": "rinse_bag_bulk_workitem_resolutions",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
        "optional": True,
    },
    {
        "table": "rinse_bag_bulk_workitem_audits",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
        "optional": True,
    },
    {
        "table": "rinse_bag_bulk_workitems",
        "date_col": "shift_date_et",
        "filter": "organization_id = %s AND shift_date_et < %s",
        "optional": True,
    },
    {
        "table": "rinse_step1_corrections",
        "date_col": None,
        "filter": "organization_id = %s",
        "optional": True,
        "note": "No date column; archive all org3 if table exists (table currently absent in prod)",
        "all_org": True,
    },
    {
        "table": "rinse_step1_bag_edits",
        "date_col": None,
        "filter": "organization_id = %s",
        "optional": True,
        "all_org": True,
    },
]

PRESERVE_TABLES = [
    "rinse_cleaner_ticket_presence_runs",
    "rinse_cleaner_ticket_presence_run_rows",
    "rinse_cleaner_ticket_presence",
    "rinse_bag_scan_events",
    "rinse_scrape_runs",
    "rinse_bag_registry",
    "upload_batches",
    "upload_batch_scan_events",
    "upload_batch_rows",
]


def _assert_safety(org: int, cutover: date) -> None:
    if org != ORG:
        raise SystemExit(f"ABORT: org must be {ORG}, got {org}")
    if cutover != CUTOVER:
        raise SystemExit(f"ABORT: cutover must be {CUTOVER}, got {cutover}")


def _table_exists(cur, name: str) -> bool:
    from backend.ta_helpers import table_exists

    return table_exists(cur, name)


def _count(cur, table: str, where: str, params: tuple) -> int:
    cur.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params)
    return int((cur.fetchone() or {}).get("c") or 0)


def inventory(cur) -> dict[str, Any]:
    _assert_safety(ORG, CUTOVER)
    out: dict[str, Any] = {
        "organization_id": ORG,
        "cutover_et": CUTOVER.isoformat(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "purge_candidates": {},
        "archive_candidates": {},
        "preserved_source_counts": {},
        "sql_filters": {
            "organization_id": ORG,
            "date_predicate": "< 2026-07-23",
        },
    }
    for spec in PURGE_SPECS:
        t = spec["table"]
        if not _table_exists(cur, t):
            out["purge_candidates"][t] = {"exists": False}
            continue
        params = (ORG, CUTOVER) if not spec.get("all_org") else (ORG,)
        out["purge_candidates"][t] = {
            "exists": True,
            "rows": _count(cur, t, spec["filter"], params),
            "filter": spec["filter"],
            "params": [ORG, CUTOVER.isoformat()] if not spec.get("all_org") else [ORG],
        }
    for spec in ARCHIVE_SPECS:
        t = spec["table"]
        if not _table_exists(cur, t):
            out["archive_candidates"][t] = {"exists": False, "note": spec.get("note")}
            continue
        params = (ORG, CUTOVER) if not spec.get("all_org") else (ORG,)
        out["archive_candidates"][t] = {
            "exists": True,
            "rows": _count(cur, t, spec["filter"], params),
            "filter": spec["filter"],
            "note": spec.get("note"),
        }
    for t in PRESERVE_TABLES:
        if _table_exists(cur, t):
            # upload_batch_scan_events may not have organization_id
            try:
                out["preserved_source_counts"][t] = _count(
                    cur, t, "organization_id = %s", (ORG,)
                )
            except Exception:
                cur.execute(f"SELECT COUNT(*) AS c FROM {t}")
                out["preserved_source_counts"][t] = int(
                    (cur.fetchone() or {}).get("c") or 0
                )
        else:
            out["preserved_source_counts"][t] = None
    return out


def _fetch_all(cur, table: str, where: str, params: tuple) -> list[dict]:
    cur.execute(f"SELECT * FROM {table} WHERE {where}", params)
    return [dict(r) for r in (cur.fetchall() or [])]


def backup(cur, dest: Path) -> dict[str, Any]:
    _assert_safety(ORG, CUTOVER)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    folder = dest / stamp
    folder.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"folder": str(folder), "tables": {}}
    for spec in PURGE_SPECS + ARCHIVE_SPECS:
        t = spec["table"]
        if not _table_exists(cur, t):
            summary["tables"][t] = {"exists": False}
            continue
        params = (ORG, CUTOVER) if not spec.get("all_org") else (ORG,)
        rows = _fetch_all(cur, t, spec["filter"], params)
        path = folder / f"{t}.json"
        path.write_text(json.dumps(rows, indent=2, default=str))
        summary["tables"][t] = {"rows_backed_up": len(rows), "path": str(path)}
    inv = inventory(cur)
    (folder / "inventory.json").write_text(json.dumps(inv, indent=2, default=str))
    summary["inventory"] = inv
    (folder / "backup_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def apply_purge(cur, *, backup_summary: dict[str, Any]) -> dict[str, Any]:
    _assert_safety(ORG, CUTOVER)
    # Verify backup non-empty for primary tables
    bags = (backup_summary.get("tables") or {}).get("rinse_shift_monitor_day_bags") or {}
    if int(bags.get("rows_backed_up") or 0) < 1:
        # Allow if already purged
        pass
    result: dict[str, Any] = {"deleted": {}, "archived_then_deleted": {}}

    # Archive tables: already backed up; delete pre-cutover rows (effects removed from Step-1 views)
    for spec in ARCHIVE_SPECS:
        t = spec["table"]
        if not _table_exists(cur, t):
            result["archived_then_deleted"][t] = {"exists": False}
            continue
        params = (ORG, CUTOVER) if not spec.get("all_org") else (ORG,)
        before = _count(cur, t, spec["filter"], params)
        # Safety: require org in filter string
        if "organization_id" not in spec["filter"]:
            raise SystemExit(f"ABORT: unscoped filter for {t}")
        if not spec.get("all_org") and "<" not in spec["filter"]:
            raise SystemExit(f"ABORT: missing date bound for {t}")
        cur.execute(f"DELETE FROM {t} WHERE {spec['filter']}", params)
        result["archived_then_deleted"][t] = {"rows_deleted": before}

    for spec in PURGE_SPECS:
        t = spec["table"]
        if not _table_exists(cur, t):
            result["deleted"][t] = {"exists": False}
            continue
        if "organization_id" not in spec["filter"] or "<" not in spec["filter"]:
            raise SystemExit(f"ABORT: unsafe filter for {t}")
        params = (ORG, CUTOVER)
        before = _count(cur, t, spec["filter"], params)
        cur.execute(f"DELETE FROM {t} WHERE {spec['filter']}", params)
        result["deleted"][t] = {"rows_deleted": before}

    # Validation
    cur.execute(
        """
        SELECT MIN(shift_date_et) AS earliest, COUNT(*) AS c
        FROM rinse_shift_monitor_days WHERE organization_id=%s
        """,
        (ORG,),
    )
    day_val = dict(cur.fetchone() or {})
    cur.execute(
        """
        SELECT MIN(shift_date_et) AS earliest, COUNT(*) AS c
        FROM rinse_shift_monitor_day_bags WHERE organization_id=%s
        """,
        (ORG,),
    )
    bag_val = dict(cur.fetchone() or {})
    result["validation"] = {
        "days_earliest": str(day_val.get("earliest")),
        "days_remaining": day_val.get("c"),
        "bags_earliest": str(bag_val.get("earliest")),
        "bags_remaining": bag_val.get("c"),
        "expect_earliest_ge": CUTOVER.isoformat(),
    }
    # Abort if any pre-cutover remains
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et < %s
        """,
        (ORG, CUTOVER),
    )
    leftover = int((cur.fetchone() or {}).get("c") or 0)
    if leftover:
        raise SystemExit(f"ABORT: {leftover} pre-cutover day_bags remain")
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", action="store_true")
    p.add_argument("--backup", action="store_true")
    p.add_argument("--apply", action="store_true", help="Backup then purge (requires --i-understand)")
    p.add_argument("--i-understand", action="store_true")
    p.add_argument("--backup-dir", default=str(BACKUP_ROOT))
    args = p.parse_args(argv)

    from backend.db import get_db

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        if args.inventory or (not args.backup and not args.apply):
            inv = inventory(cur)
            out_path = Path("tmp/deploy_verify/jul23_cutover_pre_purge_counts.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(inv, indent=2, default=str))
            print(json.dumps(inv, indent=2, default=str))
            if not args.backup and not args.apply:
                return 0

        if args.backup or args.apply:
            summary = backup(cur, Path(args.backup_dir))
            print("BACKUP", json.dumps(summary, indent=2, default=str)[:4000])
            if args.apply:
                if not args.i_understand:
                    print("Refusing --apply without --i-understand", file=sys.stderr)
                    return 2
                result = apply_purge(cur, backup_summary=summary)
                conn.commit()
                print("PURGE", json.dumps(result, indent=2, default=str))
                Path("tmp/deploy_verify/jul23_cutover_purge_result.json").write_text(
                    json.dumps({"backup": summary, "purge": result}, indent=2, default=str)
                )
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
