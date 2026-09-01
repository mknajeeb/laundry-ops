"""Scoped org Rinse operational archive + clear for a clean baseline.

Archives org-scoped Rinse WF/HD operational state to gzip JSONL files, then
deletes only those org rows. Never TRUNCATE. Never touches employees, payroll,
auth, bag registry, folding user maps, or bulk workitem catalogs.

Usage (via script):
  python -m backend.scripts.rinse_ops_baseline_reset_once --org 3
  python -m backend.scripts.rinse_ops_baseline_reset_once --org 3 --apply
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from backend.ta_helpers import table_exists, table_has_column
from backend.upload_batch_cleanup import resolve_upload_batches_pk

# Hard allow-list — refuse any other tenant until explicitly expanded.
ALLOWED_ORGANIZATION_IDS = frozenset({3})

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / "backups"


@dataclass(frozen=True)
class TargetSpec:
    """One archive/clear target."""

    table: str
    # How rows are scoped for this org.
    # - "organization_id" / "owner_organization_id": direct column
    # - "via_upload_batches": join upload_batches.organization_id
    # - "via_step1_edits": join rinse_step1_bag_edits.organization_id
    # - "lease_row": rinse_scrape_org_lease PK organization_id
    scope: str
    archive: bool = True
    clear: bool = True
    notes: str = ""


# Order: children before parents within each family.
TARGETS: tuple[TargetSpec, ...] = (
    # Upload batch children (no org column on rows/conflicts)
    TargetSpec("upload_batch_rows", "via_upload_batches"),
    TargetSpec("upload_conflicts", "via_upload_batches"),
    TargetSpec("upload_batch_scan_events", "organization_id"),
    TargetSpec("upload_batches", "organization_id"),
    # Step-1 edit children
    TargetSpec("rinse_step1_bag_edit_deltas", "via_step1_edits"),
    TargetSpec("rinse_step1_bag_edits", "organization_id"),
    TargetSpec("rinse_step1_corrections", "organization_id"),
    TargetSpec("rinse_wf_bag_split_decisions", "organization_id"),
    # Presence
    TargetSpec("rinse_cleaner_ticket_presence_run_rows", "organization_id"),
    TargetSpec("rinse_cleaner_ticket_presence_runs", "organization_id"),
    TargetSpec("rinse_cleaner_ticket_presence", "organization_id"),
    # Performance / attribution derived from Rinse bags
    TargetSpec("rinse_folding_performance_overrides", "organization_id"),
    TargetSpec("rinse_folding_performance", "organization_id"),
    TargetSpec("rinse_wf_folder_attribution_override_events", "organization_id"),
    TargetSpec("rinse_wf_folder_attribution_overrides", "organization_id"),
    TargetSpec("rinse_employee_bag_session_assignments", "organization_id"),
    # Review / Daily Ops bag facts
    TargetSpec("wf_day_bag_revenue_audits", "organization_id"),
    TargetSpec("wf_day_bag_revenue", "organization_id"),
    TargetSpec("hd_day_bag_production_audits", "organization_id"),
    TargetSpec("hd_day_bag_production", "organization_id"),
    # Bulk bag lines (keep catalog rinse_bulk_workitems)
    TargetSpec("rinse_bag_bulk_workitem_audits", "organization_id"),
    TargetSpec("rinse_bag_bulk_workitem_resolutions", "organization_id"),
    TargetSpec("rinse_bag_bulk_workitems", "organization_id"),
    # Lifecycle + Management projection
    TargetSpec("rinse_order_instances", "organization_id"),
    TargetSpec("rinse_wf_service_cycles", "organization_id"),
    TargetSpec("rinse_shift_monitor_day_bags", "organization_id"),
    TargetSpec("rinse_shift_monitor_close_audit", "organization_id"),
    TargetSpec("rinse_shift_monitor_days", "organization_id"),
    # Scan chronology (ops history for these orders)
    TargetSpec("rinse_bag_scan_events", "organization_id"),
    # Scrape / Stage-B / import
    TargetSpec("rinse_step1_scrape_refresh", "organization_id"),
    TargetSpec("rinse_step1_evidence_gate", "organization_id"),
    TargetSpec("rinse_import_jobs", "organization_id"),
    TargetSpec("rinse_scrape_runs", "organization_id"),
    TargetSpec("rinse_weight_observation_migration_archive", "organization_id"),
    TargetSpec(
        "rinse_scrape_org_lease",
        "lease_row",
        notes="Clear org lease row so no zombie lock remains",
    ),
)

# Explicitly never touched by this reset (documented for inventory / guards).
PRESERVED_TABLES: tuple[str, ...] = (
    "employees",
    "employee_profiles",
    "employee_breaks",
    "attendance_events",
    "attendance_discrepancies",
    "users",
    "user_roles",
    "auth_sessions",
    "auth_pin_attempts",
    "employee_mobile_pin_access",
    "payroll_cycles",
    "payroll_payments",
    "payroll_adjustments",
    "payroll_profiles",
    "payroll_shifts",
    "payroll_schedule_entries",
    "payroll_accrual_ledger",
    "system_settings",
    "rinse_bag_registry",
    "rinse_bag_operational_owner",
    "rinse_folding_user_map",
    "rinse_folding_excluded_users",
    "rinse_bulk_workitems",
    "orders_staging",
    "checkout_log",
    "orders_final",
    "checkout_history_snapshots",
    "checkout_history_orders",
    "checkout_history_checkouts",
)


def _require_allowed_org(organization_id: int) -> int:
    org = int(organization_id)
    if org not in ALLOWED_ORGANIZATION_IDS:
        raise ValueError(
            f"organization_id={org} is not in ALLOWED_ORGANIZATION_IDS={sorted(ALLOWED_ORGANIZATION_IDS)}"
        )
    return org


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _count_direct(cursor, table: str, org_col: str, org: int) -> int:
    cursor.execute(
        f"SELECT COUNT(*) AS c FROM `{table}` WHERE `{org_col}` = %s",
        (org,),
    )
    row = cursor.fetchone() or {}
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def _count_via_upload_batches(cursor, table: str, org: int) -> int:
    pk = resolve_upload_batches_pk(cursor)
    cursor.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM `{table}` child
        INNER JOIN upload_batches b ON b.`{pk}` = child.upload_batch_id
        WHERE b.organization_id = %s
        """,
        (org,),
    )
    row = cursor.fetchone() or {}
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def _count_via_step1_edits(cursor, table: str, org: int) -> int:
    cursor.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM `{table}` d
        INNER JOIN rinse_step1_bag_edits e ON e.id = d.edit_id
        WHERE e.organization_id = %s
        """,
        (org,),
    )
    row = cursor.fetchone() or {}
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0)


def _iter_direct(
    cursor, table: str, org_col: str, org: int, *, chunk: int = 2000
) -> Iterator[dict[str, Any]]:
    last_id = 0
    # Prefer numeric id paging when present; else one-shot fetch (small tables).
    has_id = table_has_column(cursor, table, "id")
    while True:
        if has_id:
            cursor.execute(
                f"""
                SELECT * FROM `{table}`
                WHERE `{org_col}` = %s AND id > %s
                ORDER BY id ASC
                LIMIT %s
                """,
                (org, last_id, chunk),
            )
        else:
            cursor.execute(
                f"SELECT * FROM `{table}` WHERE `{org_col}` = %s",
                (org,),
            )
        rows = cursor.fetchall() or []
        if not rows:
            break
        for row in rows:
            if isinstance(row, dict):
                yield row
                if has_id and row.get("id") is not None:
                    last_id = max(last_id, int(row["id"]))
            else:
                yield dict(row)
        if not has_id or len(rows) < chunk:
            break


def _iter_via_upload_batches(
    cursor, table: str, org: int, *, chunk: int = 2000
) -> Iterator[dict[str, Any]]:
    pk = resolve_upload_batches_pk(cursor)
    last_id = 0
    has_id = table_has_column(cursor, table, "id")
    while True:
        if has_id:
            cursor.execute(
                f"""
                SELECT child.*
                FROM `{table}` child
                INNER JOIN upload_batches b ON b.`{pk}` = child.upload_batch_id
                WHERE b.organization_id = %s AND child.id > %s
                ORDER BY child.id ASC
                LIMIT %s
                """,
                (org, last_id, chunk),
            )
        else:
            cursor.execute(
                f"""
                SELECT child.*
                FROM `{table}` child
                INNER JOIN upload_batches b ON b.`{pk}` = child.upload_batch_id
                WHERE b.organization_id = %s
                """,
                (org,),
            )
        rows = cursor.fetchall() or []
        if not rows:
            break
        for row in rows:
            d = row if isinstance(row, dict) else dict(row)
            yield d
            if has_id and d.get("id") is not None:
                last_id = max(last_id, int(d["id"]))
        if not has_id or len(rows) < chunk:
            break


def _iter_via_step1_edits(
    cursor, table: str, org: int, *, chunk: int = 2000
) -> Iterator[dict[str, Any]]:
    last_id = 0
    while True:
        cursor.execute(
            f"""
            SELECT d.*
            FROM `{table}` d
            INNER JOIN rinse_step1_bag_edits e ON e.id = d.edit_id
            WHERE e.organization_id = %s AND d.id > %s
            ORDER BY d.id ASC
            LIMIT %s
            """,
            (org, last_id, chunk),
        )
        rows = cursor.fetchall() or []
        if not rows:
            break
        for row in rows:
            d = row if isinstance(row, dict) else dict(row)
            yield d
            last_id = max(last_id, int(d["id"]))
        if len(rows) < chunk:
            break


def _delete_direct(cursor, table: str, org_col: str, org: int) -> int:
    cursor.execute(f"DELETE FROM `{table}` WHERE `{org_col}` = %s", (org,))
    return int(cursor.rowcount or 0)


def _delete_via_upload_batches(cursor, table: str, org: int) -> int:
    pk = resolve_upload_batches_pk(cursor)
    cursor.execute(
        f"""
        DELETE child FROM `{table}` child
        INNER JOIN upload_batches b ON b.`{pk}` = child.upload_batch_id
        WHERE b.organization_id = %s
        """,
        (org,),
    )
    return int(cursor.rowcount or 0)


def _delete_via_step1_edits(cursor, table: str, org: int) -> int:
    cursor.execute(
        f"""
        DELETE d FROM `{table}` d
        INNER JOIN rinse_step1_bag_edits e ON e.id = d.edit_id
        WHERE e.organization_id = %s
        """,
        (org,),
    )
    return int(cursor.rowcount or 0)


def _validate_target(cursor, spec: TargetSpec) -> str | None:
    """Return stop reason if target cannot be safely org-scoped; else None."""
    if not table_exists(cursor, spec.table):
        return None  # skip missing tables
    if spec.scope == "organization_id":
        if not table_has_column(cursor, spec.table, "organization_id"):
            return f"{spec.table}: missing organization_id"
        return None
    if spec.scope == "owner_organization_id":
        if not table_has_column(cursor, spec.table, "owner_organization_id"):
            return f"{spec.table}: missing owner_organization_id"
        return None
    if spec.scope == "lease_row":
        if not table_has_column(cursor, spec.table, "organization_id"):
            return f"{spec.table}: missing organization_id"
        return None
    if spec.scope == "via_upload_batches":
        if not table_exists(cursor, "upload_batches"):
            return f"{spec.table}: upload_batches missing"
        if not table_has_column(cursor, "upload_batches", "organization_id"):
            return (
                f"{spec.table}: upload_batches lacks organization_id "
                "(would be unsafe to clear via parent)"
            )
        if not table_has_column(cursor, spec.table, "upload_batch_id"):
            return f"{spec.table}: missing upload_batch_id"
        return None
    if spec.scope == "via_step1_edits":
        if not table_exists(cursor, "rinse_step1_bag_edits"):
            return f"{spec.table}: rinse_step1_bag_edits missing"
        if not table_has_column(cursor, "rinse_step1_bag_edits", "organization_id"):
            return f"{spec.table}: edits lack organization_id"
        if not table_has_column(cursor, spec.table, "edit_id"):
            return f"{spec.table}: missing edit_id"
        return None
    return f"{spec.table}: unknown scope {spec.scope!r}"


def inventory_org_rinse_ops(cursor, organization_id: int) -> dict[str, Any]:
    """Dry-run style inventory. Raises if any target cannot be org-scoped."""
    org = _require_allowed_org(organization_id)
    rows: list[dict[str, Any]] = []
    stop_reasons: list[str] = []

    for spec in TARGETS:
        if not table_exists(cursor, spec.table):
            rows.append(
                {
                    "table": spec.table,
                    "exists": False,
                    "scope": spec.scope,
                    "org3_rows_to_archive": 0,
                    "org3_rows_to_clear": 0,
                    "archive_destination": "(table missing — skip)",
                    "tenant_scoped_ok": True,
                    "notes": "missing",
                }
            )
            continue
        bad = _validate_target(cursor, spec)
        if bad:
            stop_reasons.append(bad)
            rows.append(
                {
                    "table": spec.table,
                    "exists": True,
                    "scope": spec.scope,
                    "org3_rows_to_archive": None,
                    "org3_rows_to_clear": None,
                    "archive_destination": "STOP",
                    "tenant_scoped_ok": False,
                    "notes": bad,
                }
            )
            continue

        if spec.scope in ("organization_id", "lease_row"):
            n = _count_direct(cursor, spec.table, "organization_id", org)
        elif spec.scope == "owner_organization_id":
            n = _count_direct(cursor, spec.table, "owner_organization_id", org)
        elif spec.scope == "via_upload_batches":
            n = _count_via_upload_batches(cursor, spec.table, org)
        elif spec.scope == "via_step1_edits":
            n = _count_via_step1_edits(cursor, spec.table, org)
        else:
            n = 0

        rows.append(
            {
                "table": spec.table,
                "exists": True,
                "scope": spec.scope,
                "org3_rows_to_archive": n if spec.archive else 0,
                "org3_rows_to_clear": n if spec.clear else 0,
                "archive_destination": f"backups/rinse_ops_baseline_reset_org{org}_*/tables/{spec.table}.jsonl.gz",
                "tenant_scoped_ok": True,
                "notes": spec.notes,
            }
        )

    preserved: dict[str, int | str] = {}
    for t in PRESERVED_TABLES:
        if not table_exists(cursor, t):
            preserved[t] = "missing"
            continue
        org_col = None
        for c in ("organization_id", "owner_organization_id"):
            if table_has_column(cursor, t, c):
                org_col = c
                break
        if org_col:
            preserved[t] = _count_direct(cursor, t, org_col, org)
        else:
            cursor.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
            r = cursor.fetchone() or {}
            preserved[t] = int((r.get("c") if isinstance(r, dict) else r[0]) or 0)

    return {
        "organization_id": org,
        "safe": not stop_reasons,
        "stop_reasons": stop_reasons,
        "targets": rows,
        "preserved_counts": preserved,
        "totals": {
            "archive_rows": sum(int(r["org3_rows_to_archive"] or 0) for r in rows),
            "clear_rows": sum(int(r["org3_rows_to_clear"] or 0) for r in rows),
        },
    }


def _archive_table(
    cursor,
    spec: TargetSpec,
    org: int,
    dest: Path,
) -> int:
    if not spec.archive or not table_exists(cursor, spec.table):
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    if spec.scope in ("organization_id", "lease_row"):
        it = _iter_direct(cursor, spec.table, "organization_id", org)
    elif spec.scope == "via_upload_batches":
        it = _iter_via_upload_batches(cursor, spec.table, org)
    elif spec.scope == "via_step1_edits":
        it = _iter_via_step1_edits(cursor, spec.table, org)
    else:
        it = iter(())

    n = 0
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        for row in it:
            fh.write(json.dumps(row, default=_json_default, separators=(",", ":")))
            fh.write("\n")
            n += 1
    return n


def _clear_table(cursor, spec: TargetSpec, org: int) -> int:
    if not spec.clear or not table_exists(cursor, spec.table):
        return 0
    if spec.scope in ("organization_id", "lease_row"):
        return _delete_direct(cursor, spec.table, "organization_id", org)
    if spec.scope == "via_upload_batches":
        return _delete_via_upload_batches(cursor, spec.table, org)
    if spec.scope == "via_step1_edits":
        return _delete_via_step1_edits(cursor, spec.table, org)
    raise ValueError(f"cannot clear {spec.table} with scope {spec.scope}")


def run_org_rinse_ops_baseline_reset(
    conn,
    organization_id: int,
    *,
    dry_run: bool = True,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    """Inventory (always). Archive+clear when dry_run=False."""
    org = _require_allowed_org(organization_id)
    cursor = conn.cursor(dictionary=True)
    inv = inventory_org_rinse_ops(cursor, org)
    if not inv["safe"]:
        return {
            **inv,
            "applied": False,
            "error": "STOP: one or more tables cannot be safely org-scoped",
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(archive_root or DEFAULT_ARCHIVE_ROOT)
    archive_dir = root / f"rinse_ops_baseline_reset_org{org}_{stamp}"
    report: dict[str, Any] = {
        **inv,
        "applied": False,
        "dry_run": dry_run,
        "archive_dir": str(archive_dir),
        "archive_results": [],
        "clear_results": [],
        "preserved_counts_after": None,
    }

    if dry_run:
        return report

    archive_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = archive_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: archive all targets first
    for spec in TARGETS:
        if not table_exists(cursor, spec.table):
            continue
        path = tables_dir / f"{spec.table}.jsonl.gz"
        n = _archive_table(cursor, spec, org, path)
        report["archive_results"].append(
            {"table": spec.table, "archived_rows": n, "path": str(path)}
        )

    (archive_dir / "MANIFEST.json").write_text(
        json.dumps(
            {
                "organization_id": org,
                "created_at_utc": stamp,
                "inventory": inv,
                "archive_results": report["archive_results"],
            },
            indent=2,
            default=_json_default,
        )
    )

    # Phase 2: clear in TARGETS order (children first)
    for spec in TARGETS:
        if not table_exists(cursor, spec.table):
            continue
        n = _clear_table(cursor, spec, org)
        report["clear_results"].append({"table": spec.table, "cleared_rows": n})

    conn.commit()
    report["applied"] = True

    # Post counts
    post = inventory_org_rinse_ops(cursor, org)
    report["post_inventory"] = post
    report["preserved_counts_after"] = post["preserved_counts"]
    report["active_remaining"] = {
        r["table"]: r["org3_rows_to_clear"]
        for r in post["targets"]
        if int(r.get("org3_rows_to_clear") or 0) > 0
    }
    return report


def format_inventory_table(inv: dict[str, Any]) -> str:
    lines = [
        f"{'TABLE':48} {'ARCHIVE':>10} {'CLEAR':>10} {'SCOPE':22} DEST",
        "-" * 120,
    ]
    for r in inv.get("targets") or []:
        lines.append(
            f"{r['table']:48} {str(r.get('org3_rows_to_archive')):>10} "
            f"{str(r.get('org3_rows_to_clear')):>10} {r.get('scope',''):22} "
            f"{r.get('archive_destination','')}"
        )
    tot = inv.get("totals") or {}
    lines.append("-" * 120)
    lines.append(
        f"{'TOTAL':48} {tot.get('archive_rows',0):>10} {tot.get('clear_rows',0):>10}"
    )
    if inv.get("stop_reasons"):
        lines.append("STOP REASONS:")
        for s in inv["stop_reasons"]:
            lines.append(f"  - {s}")
    return "\n".join(lines)
