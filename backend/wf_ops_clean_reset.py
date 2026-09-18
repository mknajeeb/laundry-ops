"""WF-only operational clean reset: archive to JSONL, then service-scoped DELETE.

This is **not** ``rinse_ops_baseline_reset``. That module clears org-wide Rinse
operational state and would wipe Rinse HD along with WF. Every target here is
scoped by an explicit service predicate so HD production, HD order instances and
HD presence survive untouched.

What happens to each family:

``clear``          archive gzip JSONL, then DELETE the WF-scoped rows
``registry_reset`` UPDATE ``rinse_bag_registry`` completion fields to INCOMPLETE
                   (identity/config columns are retained; no registry row is deleted)
``retain_epoch``   physically retained; suppressed logically by ``wf_reset_epoch_at``
``preserve``       never read for mutation; counted before/after as a drift guard

Upload history follows strategy D: ``upload_batch_scan_events`` (~6.6M rows) and
``rinse_bag_scan_events`` are far too expensive and too shared to delete, and
``upload_batches`` / ``upload_batch_rows`` / ``upload_conflicts`` are the only
recovery path for a bad baseline. All four are kept and fenced by the epoch.

Usage (via script):
  python -m backend.scripts.wf_ops_clean_reset_once --org 3
  python -m backend.scripts.wf_ops_clean_reset_once --org 3 --apply  # needs unlock+maintenance
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from backend.ta_helpers import table_exists, table_has_column
from backend.wf_ops_reset_epoch import (
    WF_OPS_MAINTENANCE_KEY,
    WF_RESET_EPOCH_KEY,
    WF_TRUSTED_BASELINE_KEY,
    get_wf_ops_maintenance,
    get_wf_reset_epoch_at,
    set_wf_reset_epoch_at,
)

# Hard allow-list — refuse any other tenant until explicitly expanded.
ALLOWED_ORGANIZATION_IDS = frozenset({3})

# Code-level hard block removed for the authorized release SHA.
# Apply STILL requires BOTH ``--apply`` and ``WF_CLEAN_RESET_APPLY_UNLOCK=1``
# plus ``wf_ops_maintenance`` already ON for the org. Dry-run is the default.
APPLY_BLOCKED = False

APPLY_UNLOCK_ENV = "WF_CLEAN_RESET_APPLY_UNLOCK"

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / "backups"

ACTION_CLEAR = "clear"
ACTION_RETAIN_EPOCH = "retain_epoch"
ACTION_REGISTRY_RESET = "registry_reset"
ACTION_PRESERVE = "preserve"

# Rows whose own service_type is WF (NULL defaults to WF — legacy WF rows).
WF_SERVICE_PREDICATE = "organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) = 'WF'"
ORG_PREDICATE = "organization_id = %s"
# Bags whose CURRENT registry service_type is WF. Documented risk: a bag that was
# WF when the row was written but is HD today keeps its folding rows.
REGISTRY_WF_BAG_PREDICATE = (
    "organization_id = %s AND bag_id IN ("
    "SELECT bag_id FROM rinse_bag_registry "
    "WHERE organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) = 'WF')"
)
# Registry rows to neutralize: currently WF only.
# HD completion/trigger state is left alone — HD production history must survive.
# Reused bag IDs that are WF today cannot inherit a prior WF COMPLETED/trigger.
REGISTRY_RESET_PREDICATE = (
    "organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) = 'WF'"
)

# Identity / configuration kept on every registry row.
REGISTRY_RETAINED_COLUMNS: tuple[str, ...] = (
    "id",
    "organization_id",
    "bag_id",
    "name_clean",
    "weight_num",
    "service_type",
    "date_clean",
    "last_upload_batch_id",
    "last_staging_order_id",
    "created_at",
)

# Completion state cleared so no reused bag ID inherits a prior lifecycle.
REGISTRY_RESET_COLUMNS: tuple[str, ...] = (
    "completion_status",
    "completed_at",
    "completion_reason",
    "first_clean_scan_at",
    "first_clean_scan_event_id",
    "trigger_scan_at",
    "trigger_scan_event_id",
    "trigger_kind",
)

_PAGE_COLUMN_CANDIDATES: tuple[str, ...] = ("id", "order_instance_id")


@dataclass(frozen=True)
class TargetSpec:
    """One WF-scoped reset target."""

    table: str
    action: str
    predicate: str = ""
    # Number of %s placeholders in ``predicate`` (all of them are organization_id).
    param_count: int = 1
    requires_columns: tuple[str, ...] = ()
    requires_tables: tuple[str, ...] = ()
    notes: str = ""

    @property
    def archives(self) -> bool:
        return self.action in (ACTION_CLEAR, ACTION_REGISTRY_RESET)


def _wf_service_target(table: str, notes: str = "") -> TargetSpec:
    return TargetSpec(
        table,
        ACTION_CLEAR,
        WF_SERVICE_PREDICATE,
        requires_columns=("organization_id", "service_type"),
        notes=notes,
    )


def _org_target(table: str, notes: str = "") -> TargetSpec:
    return TargetSpec(
        table,
        ACTION_CLEAR,
        ORG_PREDICATE,
        requires_columns=("organization_id",),
        notes=notes,
    )


def _registry_bag_target(table: str, notes: str = "") -> TargetSpec:
    return TargetSpec(
        table,
        ACTION_CLEAR,
        REGISTRY_WF_BAG_PREDICATE,
        param_count=2,
        requires_columns=("organization_id", "bag_id"),
        requires_tables=("rinse_bag_registry",),
        notes=notes,
    )


def _retain_epoch(table: str, notes: str) -> TargetSpec:
    return TargetSpec(table, ACTION_RETAIN_EPOCH, notes=notes)


# Children before parents. rinse_order_instances references rinse_wf_service_cycles
# through source_cycle_id, so order instances are cleared before cycles.
TARGETS: tuple[TargetSpec, ...] = (
    # Manager decisions and attribution overrides (WF-only tables).
    _org_target("rinse_wf_bag_split_decisions", "WF split decisions"),
    _org_target("rinse_wf_folder_attribution_override_events", "WF attribution audit"),
    _org_target("rinse_wf_folder_attribution_overrides", "WF attribution overrides"),
    # Review / Daily Ops WF bag facts.
    _org_target("wf_day_bag_revenue_audits", "WF revenue audit child"),
    _org_target("wf_day_bag_revenue", "WF per-bag revenue"),
    # Bulk bag lines (catalog rinse_bulk_workitems is preserved).
    _org_target("rinse_bag_bulk_workitem_audits", "bulk audit child"),
    _org_target("rinse_bag_bulk_workitem_resolutions", "bulk resolution child"),
    _org_target("rinse_bag_bulk_workitems", "bulk lines on WF bags"),
    # Folding performance — scoped by CURRENT registry service_type.
    _registry_bag_target(
        "rinse_folding_performance_overrides",
        "RISK: bags that are HD today keep folding override rows",
    ),
    _registry_bag_target(
        "rinse_folding_performance",
        "RISK: bags that are HD today keep folding rows",
    ),
    # Presence — current WF presence only; HD presence rows are left alone.
    _wf_service_target("rinse_cleaner_ticket_presence_run_rows", "WF presence run rows"),
    _wf_service_target("rinse_cleaner_ticket_presence", "current WF presence"),
    # Management projection + lifecycle.
    _wf_service_target("rinse_shift_monitor_day_bags", "WF day-bag projection"),
    _wf_service_target("rinse_order_instances", "WF order instances"),
    _org_target("rinse_wf_service_cycles", "canonical WF lifecycle (WF-only table)"),
    # Operational staging rows for WF only. HD staging and all finance tables stay.
    _wf_service_target(
        "orders_staging",
        "WF staging rows only — Supplies SI contamination; HD staging preserved",
    ),
    # Registry: UPDATE, never DELETE.
    TargetSpec(
        "rinse_bag_registry",
        ACTION_REGISTRY_RESET,
        REGISTRY_RESET_PREDICATE,
        requires_columns=("organization_id", "completion_status"),
        notes="identity/config retained; completion fields reset to INCOMPLETE",
    ),
    # Strategy D — retained physically, fenced by wf_reset_epoch_at.
    _retain_epoch(
        "upload_batch_scan_events",
        "~6.6M rows; too expensive and too shared to delete (strategy D)",
    ),
    _retain_epoch(
        "rinse_bag_scan_events",
        "durable scan chronology; pre-epoch events may not admit a cycle",
    ),
    _retain_epoch("upload_batches", "shared upload history; baseline recovery path"),
    _retain_epoch("upload_batch_rows", "shared upload history; baseline recovery path"),
    _retain_epoch("upload_conflicts", "shared upload history; baseline recovery path"),
    _retain_epoch(
        "rinse_employee_bag_session_assignments",
        "STOP: no service_type column — WF-only cannot be proven; epoch note instead",
    ),
    _retain_epoch(
        "rinse_shift_monitor_days",
        "shared day parent — wiping would drop HD day aggregates",
    ),
    _retain_epoch(
        "rinse_shift_monitor_close_audit",
        "shared day parent — wiping would drop HD close audit",
    ),
    _retain_epoch("rinse_scrape_runs", "shared scrape infrastructure"),
    _retain_epoch("rinse_import_jobs", "shared scrape infrastructure"),
    _retain_epoch("rinse_scrape_org_lease", "shared scrape infrastructure"),
    _retain_epoch("rinse_step1_scrape_refresh", "shared Stage-B infrastructure"),
    _retain_epoch("rinse_step1_evidence_gate", "shared Stage-B infrastructure"),
)

# Explicitly never touched. Counted before/after as a drift guard.
PRESERVED_TABLES: tuple[str, ...] = (
    # Rinse HD
    "hd_day_bag_production",
    "hd_day_bag_production_audits",
    # Finance
    "checkout_log",
    "orders_final",
    "checkout_history_snapshots",
    "checkout_history_orders",
    "checkout_history_checkouts",
    # People
    "employees",
    "employee_profiles",
    "users",
    "auth_sessions",
    "payroll_cycles",
    "payroll_payments",
    "payroll_shifts",
    # Config / catalogs
    "system_settings",
    "rinse_bulk_workitems",
    "rinse_folding_user_map",
    "rinse_folding_excluded_users",
    "rinse_bag_operational_owner",
)

# Tables that can still hand pre-reset facts back to WF, and what stops them.
RESURRECTION_GUARDS: tuple[tuple[str, str], ...] = (
    (
        "rinse_bag_scan_events",
        "rinse_wf_service_cycle._load_timeline drops scans before the epoch, so "
        "no pre-epoch STV can produce a cycle anchor",
    ),
    (
        "upload_batch_scan_events",
        "re-import replays into rinse_bag_scan_events, which is epoch-filtered "
        "before any lifecycle admission",
    ),
    (
        "upload_batches",
        "re-confirming an old batch cannot admit a cycle: admission reads the "
        "epoch-filtered timeline",
    ),
    (
        "rinse_employee_bag_session_assignments",
        "retained (no service_type column); rows keyed to pre-epoch dates are "
        "not re-read by the post-reset WF day",
    ),
    (
        "rinse_shift_monitor_days",
        "shared day parent retained; WF day bags are rebuilt from the new "
        "canonical projection only",
    ),
)


def _require_allowed_org(organization_id: int) -> int:
    org = int(organization_id)
    if org not in ALLOWED_ORGANIZATION_IDS:
        raise ValueError(
            f"organization_id={org} is not in ALLOWED_ORGANIZATION_IDS="
            f"{sorted(ALLOWED_ORGANIZATION_IDS)}"
        )
    return org


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _params(spec: TargetSpec, org: int) -> tuple[int, ...]:
    return tuple(org for _ in range(spec.param_count))


def _scalar(cursor) -> int:
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("c") or 0)
    return int(row[0] or 0)


def _count_where(cursor, table: str, where: str, params: Sequence[Any]) -> int:
    cursor.execute(f"SELECT COUNT(*) AS c FROM `{table}` WHERE {where}", tuple(params))
    return _scalar(cursor)


def _count_all(cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) AS c FROM `{table}`")
    return _scalar(cursor)


def _page_column(cursor, table: str) -> str | None:
    for col in _PAGE_COLUMN_CANDIDATES:
        if table_has_column(cursor, table, col):
            return col
    return None


def validate_target(cursor, spec: TargetSpec) -> str | None:
    """Return a STOP reason when this target cannot be safely WF-scoped."""
    if spec.action in (ACTION_RETAIN_EPOCH, ACTION_PRESERVE):
        return None
    if not table_exists(cursor, spec.table):
        return None  # missing table is a skip, not a stop
    for dep in spec.requires_tables:
        if not table_exists(cursor, dep):
            return f"{spec.table}: required table {dep} missing"
    for col in spec.requires_columns:
        if not table_has_column(cursor, spec.table, col):
            return f"{spec.table}: missing {col} (cannot prove WF-only scope)"
    if not spec.predicate:
        return f"{spec.table}: no predicate for action {spec.action!r}"
    return None


def _iter_rows(
    cursor, spec: TargetSpec, org: int, *, chunk: int = 2000
) -> Iterator[dict[str, Any]]:
    page_col = _page_column(cursor, spec.table)
    base = _params(spec, org)
    last_id = 0
    while True:
        if page_col:
            cursor.execute(
                f"""
                SELECT * FROM `{spec.table}`
                WHERE {spec.predicate} AND `{page_col}` > %s
                ORDER BY `{page_col}` ASC
                LIMIT %s
                """,
                (*base, last_id, chunk),
            )
        else:
            cursor.execute(
                f"SELECT * FROM `{spec.table}` WHERE {spec.predicate}", base
            )
        rows = cursor.fetchall() or []
        if not rows:
            break
        for row in rows:
            data = row if isinstance(row, dict) else dict(row)
            yield data
            if page_col and data.get(page_col) is not None:
                last_id = max(last_id, int(data[page_col]))
        if not page_col or len(rows) < chunk:
            break


def archive_target(cursor, spec: TargetSpec, org: int, dest: Path) -> int:
    """Write every in-scope row to a gzip JSONL file. Returns rows written."""
    if not spec.archives or not table_exists(cursor, spec.table):
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        for row in _iter_rows(cursor, spec, org):
            fh.write(json.dumps(row, default=_json_default, separators=(",", ":")))
            fh.write("\n")
            written += 1
    return written


def clear_target(cursor, spec: TargetSpec, org: int) -> int:
    if spec.action != ACTION_CLEAR:
        raise ValueError(f"{spec.table}: clear_target called for action {spec.action!r}")
    if not table_exists(cursor, spec.table):
        return 0
    cursor.execute(
        f"DELETE FROM `{spec.table}` WHERE {spec.predicate}", _params(spec, org)
    )
    return int(cursor.rowcount or 0)


def registry_reset(cursor, org: int) -> int:
    """Neutralize completion state on WF / previously-completed registry rows."""
    spec = registry_target()
    if not table_exists(cursor, spec.table):
        return 0
    assignments = ", ".join(
        "completion_status = 'INCOMPLETE'" if col == "completion_status" else f"{col} = NULL"
        for col in REGISTRY_RESET_COLUMNS
        if table_has_column(cursor, spec.table, col)
    )
    cursor.execute(
        f"UPDATE `{spec.table}` SET {assignments} WHERE {spec.predicate}",
        _params(spec, org),
    )
    return int(cursor.rowcount or 0)


def registry_target() -> TargetSpec:
    for spec in TARGETS:
        if spec.action == ACTION_REGISTRY_RESET:
            return spec
    raise LookupError("no registry_reset target configured")


def clear_targets() -> tuple[TargetSpec, ...]:
    return tuple(s for s in TARGETS if s.action == ACTION_CLEAR)


def retained_targets() -> tuple[TargetSpec, ...]:
    return tuple(s for s in TARGETS if s.action == ACTION_RETAIN_EPOCH)


def _hd_rows_in_scope(cursor, spec: TargetSpec, org: int) -> int | None:
    """Rows the predicate would delete that are NOT WF. Must always be 0."""
    if not table_has_column(cursor, spec.table, "service_type"):
        return None
    return _count_where(
        cursor,
        spec.table,
        f"({spec.predicate}) AND UPPER(COALESCE(service_type, 'WF')) <> 'WF'",
        _params(spec, org),
    )


def _non_wf_rows_protected(cursor, spec: TargetSpec, org: int) -> int | None:
    if not table_has_column(cursor, spec.table, "service_type"):
        return None
    return _count_where(
        cursor,
        spec.table,
        "organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) <> 'WF'",
        (org,),
    )


def _hd_now_bags_retained(cursor, spec: TargetSpec, org: int) -> int | None:
    """Registry-scoped targets: rows kept because the bag is HD in the registry today."""
    if spec.predicate != REGISTRY_WF_BAG_PREDICATE:
        return None
    return _count_where(
        cursor,
        spec.table,
        "organization_id = %s AND bag_id IN ("
        "SELECT bag_id FROM rinse_bag_registry "
        "WHERE organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) <> 'WF')",
        (org, org),
    )


def _sample_order_instances(cursor, org: int, limit: int = 10) -> list[dict[str, Any]]:
    """WF order instances as BAGID-OI-MMDDYYYY display ids."""
    if not table_exists(cursor, "rinse_order_instances"):
        return []
    from backend.order_display_id import format_order_display_id

    join_cycles = table_exists(cursor, "rinse_wf_service_cycles")
    if join_cycles:
        cursor.execute(
            """
            SELECT oi.order_instance_id, oi.bag_id, oi.cycle_anchor_at, oi.completed_at,
                   c.estimated_delivery_date
            FROM rinse_order_instances oi
            LEFT JOIN rinse_wf_service_cycles c ON c.id = oi.source_cycle_id
            WHERE oi.organization_id = %s
              AND UPPER(COALESCE(oi.service_type, 'WF')) = 'WF'
            ORDER BY oi.order_instance_id DESC
            LIMIT %s
            """,
            (org, int(limit)),
        )
    else:
        cursor.execute(
            """
            SELECT order_instance_id, bag_id, cycle_anchor_at, completed_at,
                   NULL AS estimated_delivery_date
            FROM rinse_order_instances
            WHERE organization_id = %s AND UPPER(COALESCE(service_type, 'WF')) = 'WF'
            ORDER BY order_instance_id DESC
            LIMIT %s
            """,
            (org, int(limit)),
        )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "order_display_id": format_order_display_id(
                    row.get("bag_id"),
                    row.get("order_instance_id"),
                    estimated_delivery_date=row.get("estimated_delivery_date"),
                ),
                "order_instance_id": row.get("order_instance_id"),
                "bag_id": row.get("bag_id"),
                "cycle_anchor_at": row.get("cycle_anchor_at"),
                "completed_at": row.get("completed_at"),
            }
        )
    return out


def _sample_registry_rows(cursor, org: int, limit: int = 10) -> list[dict[str, Any]]:
    spec = registry_target()
    if not table_exists(cursor, spec.table):
        return []
    cursor.execute(
        f"""
        SELECT bag_id, service_type, completion_status, completed_at, completion_reason
        FROM `{spec.table}`
        WHERE {spec.predicate}
        ORDER BY completed_at DESC
        LIMIT %s
        """,
        (*_params(spec, org), int(limit)),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def inventory_wf_clean_reset(cursor, organization_id: int) -> dict[str, Any]:
    """Counts + scope proof for every target. Pure SELECT."""
    org = _require_allowed_org(organization_id)
    stop_reasons: list[str] = []
    targets: list[dict[str, Any]] = []

    for spec in TARGETS:
        exists = table_exists(cursor, spec.table)
        entry: dict[str, Any] = {
            "table": spec.table,
            "action": spec.action,
            "exists": exists,
            "predicate": spec.predicate or None,
            "notes": spec.notes,
            "rows_in_scope": 0,
            "rows_to_archive": 0,
            "rows_to_clear": 0,
            "rows_to_update": 0,
            "rows_retained": 0,
            "hd_rows_in_scope": None,
            "non_wf_rows_reset": None,
            "non_wf_rows_protected": None,
            "hd_now_bags_retained": None,
            "scoped_ok": True,
        }
        if not exists:
            entry["notes"] = (entry["notes"] + " (table missing)").strip()
            targets.append(entry)
            continue

        bad = validate_target(cursor, spec)
        if bad:
            stop_reasons.append(bad)
            entry["scoped_ok"] = False
            entry["notes"] = bad
            targets.append(entry)
            continue

        if spec.action in (ACTION_RETAIN_EPOCH, ACTION_PRESERVE):
            if table_has_column(cursor, spec.table, "organization_id"):
                entry["rows_retained"] = _count_where(
                    cursor, spec.table, ORG_PREDICATE, (org,)
                )
            else:
                entry["rows_retained"] = _count_all(cursor, spec.table)
            targets.append(entry)
            continue

        n = _count_where(cursor, spec.table, spec.predicate, _params(spec, org))
        entry["rows_in_scope"] = n
        entry["rows_to_archive"] = n
        if spec.action == ACTION_CLEAR:
            entry["rows_to_clear"] = n
            # No DELETE may ever reach a non-WF row.
            entry["hd_rows_in_scope"] = _hd_rows_in_scope(cursor, spec, org)
            if entry["hd_rows_in_scope"]:
                stop_reasons.append(
                    f"{spec.table}: {entry['hd_rows_in_scope']} non-WF rows match the "
                    "clear predicate (HD would be destroyed)"
                )
                entry["scoped_ok"] = False
        else:
            # The registry UPDATE deliberately covers non-WF rows that still
            # carry a completion, so a reused bag ID cannot inherit it. Nothing
            # is deleted and no HD identity column is touched.
            entry["rows_to_update"] = n
            entry["non_wf_rows_reset"] = _hd_rows_in_scope(cursor, spec, org)
        entry["non_wf_rows_protected"] = _non_wf_rows_protected(cursor, spec, org)
        entry["hd_now_bags_retained"] = _hd_now_bags_retained(cursor, spec, org)
        targets.append(entry)

    preserved: dict[str, int | str] = {}
    for table in PRESERVED_TABLES:
        if not table_exists(cursor, table):
            preserved[table] = "missing"
            continue
        if table_has_column(cursor, table, "organization_id"):
            preserved[table] = _count_where(cursor, table, ORG_PREDICATE, (org,))
        else:
            preserved[table] = _count_all(cursor, table)

    hd_in_scope_total = sum(int(t["hd_rows_in_scope"] or 0) for t in targets)
    return {
        "organization_id": org,
        "safe": not stop_reasons,
        "stop_reasons": stop_reasons,
        "targets": targets,
        "preserved_counts": preserved,
        "scope_protection": {
            "hd_rows_in_clear_scope": hd_in_scope_total,
            "expected": 0,
            "ok": hd_in_scope_total == 0,
            "non_wf_rows_protected": {
                t["table"]: t["non_wf_rows_protected"]
                for t in targets
                if t["non_wf_rows_protected"] is not None
            },
            "hd_now_bags_retained": {
                t["table"]: t["hd_now_bags_retained"]
                for t in targets
                if t["hd_now_bags_retained"] is not None
            },
            "non_wf_registry_rows_reset": {
                t["table"]: t["non_wf_rows_reset"]
                for t in targets
                if t["non_wf_rows_reset"] is not None
            },
        },
        "totals": {
            "archive_rows": sum(int(t["rows_to_archive"] or 0) for t in targets),
            "clear_rows": sum(int(t["rows_to_clear"] or 0) for t in targets),
            "registry_update_rows": sum(int(t["rows_to_update"] or 0) for t in targets),
            "retained_rows": sum(int(t["rows_retained"] or 0) for t in targets),
        },
    }


def _archive_dir_for(org: int, stamp: str, archive_root: Path | None) -> Path:
    root = Path(archive_root or DEFAULT_ARCHIVE_ROOT)
    return root / f"wf_ops_clean_reset_org{org}_{stamp}"


def build_dry_run_report(
    cursor,
    organization_id: int,
    *,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    """Read-only report. Issues SELECTs only — safe against a live production DB."""
    org = _require_allowed_org(organization_id)
    inv = inventory_wf_clean_reset(cursor, org)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    archive_dir = _archive_dir_for(org, stamp, archive_root)

    archive_plan = [
        {
            "table": t["table"],
            "action": t["action"],
            "rows_to_archive": t["rows_to_archive"],
            "rows_to_clear": t["rows_to_clear"],
            "rows_to_update": t["rows_to_update"],
            "archive_destination": (
                str(archive_dir / "tables" / f"{t['table']}.jsonl.gz")
                if t["rows_to_archive"] or t["action"] == ACTION_REGISTRY_RESET
                else None
            ),
        }
        for t in inv["targets"]
        if t["action"] in (ACTION_CLEAR, ACTION_REGISTRY_RESET)
    ]

    retained = {t["table"]: t["rows_retained"] for t in inv["targets"] if t["action"] == ACTION_RETAIN_EPOCH}
    guard_by_table = dict(RESURRECTION_GUARDS)
    resurrection_residual = [
        {
            "table": table,
            "rows_retained": rows,
            "guard": guard_by_table.get(
                table, "epoch fence only — no WF read path reconstructs from this table"
            ),
        }
        for table, rows in retained.items()
    ]

    epoch = get_wf_reset_epoch_at(cursor, org, use_cache=False)
    return {
        **inv,
        "dry_run": True,
        "applied": False,
        "apply_blocked": APPLY_BLOCKED,
        "generated_at_utc": now.isoformat(),
        "archive_dir": str(archive_dir),
        "current_state": {
            t["table"]: {
                "exists": t["exists"],
                "action": t["action"],
                "rows_in_scope": t["rows_in_scope"],
                "rows_retained": t["rows_retained"],
            }
            for t in inv["targets"]
        },
        "archive_plan": archive_plan,
        "samples": {
            "order_instances": _sample_order_instances(cursor, org),
            "registry_rows_to_reset": _sample_registry_rows(cursor, org),
        },
        "resurrection_residual": resurrection_residual,
        "registry_reset": {
            "table": registry_target().table,
            "predicate": REGISTRY_RESET_PREDICATE,
            "retained_columns": list(REGISTRY_RETAINED_COLUMNS),
            "reset_columns": list(REGISTRY_RESET_COLUMNS),
            "rows_to_update": sum(
                int(t["rows_to_update"] or 0) for t in inv["targets"]
            ),
        },
        "epoch": {
            "settings_key": WF_RESET_EPOCH_KEY,
            "maintenance_key": WF_OPS_MAINTENANCE_KEY,
            "trusted_baseline_key": WF_TRUSTED_BASELINE_KEY,
            "current_value": epoch.isoformat() if epoch else None,
            "maintenance_on": get_wf_ops_maintenance(cursor, org),
            "would_write": "on --apply only",
        },
    }


def _apply_gate_error(cursor, org: int) -> str | None:
    if APPLY_BLOCKED:
        return (
            "APPLY_BLOCKED=True — production apply is disabled in code. Dry-run only."
        )
    if str(os.getenv(APPLY_UNLOCK_ENV) or "").strip() != "1":
        return f"{APPLY_UNLOCK_ENV}=1 is required to apply"
    if not get_wf_ops_maintenance(cursor, org):
        return (
            f"{WF_OPS_MAINTENANCE_KEY} must already be ON for this org before apply"
        )
    return None


def run_wf_clean_reset(
    conn,
    organization_id: int,
    *,
    dry_run: bool = True,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    """Dry-run report always. Archive + WF-scoped clear only when unblocked."""
    org = _require_allowed_org(organization_id)
    cursor = conn.cursor(dictionary=True)
    report = build_dry_run_report(cursor, org, archive_root=archive_root)

    if dry_run:
        return report

    report["dry_run"] = False
    gate_error = _apply_gate_error(cursor, org)
    if gate_error:
        report["error"] = gate_error
        return report
    if not report["safe"]:
        report["error"] = "STOP: one or more targets cannot be safely WF-scoped"
        return report

    archive_dir = Path(report["archive_dir"])
    tables_dir = archive_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    archive_results: list[dict[str, Any]] = []
    for spec in TARGETS:
        if not spec.archives or not table_exists(cursor, spec.table):
            continue
        path = tables_dir / f"{spec.table}.jsonl.gz"
        archive_results.append(
            {
                "table": spec.table,
                "archived_rows": archive_target(cursor, spec, org, path),
                "path": str(path),
            }
        )
    report["archive_results"] = archive_results
    (archive_dir / "MANIFEST.json").write_text(
        json.dumps(
            {
                "organization_id": org,
                "created_at_utc": report["generated_at_utc"],
                "inventory": report["current_state"],
                "archive_results": archive_results,
            },
            indent=2,
            default=_json_default,
        )
    )

    clear_results: list[dict[str, Any]] = []
    for spec in clear_targets():
        if not table_exists(cursor, spec.table):
            continue
        clear_results.append(
            {"table": spec.table, "cleared_rows": clear_target(cursor, spec, org)}
        )
    report["clear_results"] = clear_results
    report["registry_reset_rows"] = registry_reset(cursor, org)
    report["epoch"]["written_value"] = set_wf_reset_epoch_at(cursor, org).isoformat()

    conn.commit()
    report["applied"] = True

    post = inventory_wf_clean_reset(cursor, org)
    report["post_inventory"] = post
    report["preserved_counts_after"] = post["preserved_counts"]
    return report


def restore_from_archive(
    cursor,
    archive_dir: Path | str,
    *,
    tables: Sequence[str] | None = None,
) -> dict[str, int]:
    """Re-insert archived rows. Used by fixture tests and manual recovery."""
    root = Path(archive_dir)
    tables_dir = root / "tables" if (root / "tables").is_dir() else root
    wanted = set(tables) if tables else None
    restored: dict[str, int] = {}
    for path in sorted(tables_dir.glob("*.jsonl.gz")):
        table = path.name[: -len(".jsonl.gz")]
        if wanted is not None and table not in wanted:
            continue
        count = 0
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if not isinstance(row, dict) or not row:
                    continue
                cols = list(row.keys())
                placeholders = ", ".join(["%s"] * len(cols))
                col_sql = ", ".join(f"`{c}`" for c in cols)
                cursor.execute(
                    f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})",
                    tuple(row[c] for c in cols),
                )
                count += 1
        restored[table] = count
    return restored


def format_dry_run_report(report: dict[str, Any]) -> str:
    """Operator-facing text. ET first for any business timestamp."""
    org = report.get("organization_id")
    lines: list[str] = [
        f"WF-ONLY CLEAN RESET — organization_id={org}",
        f"generated_at_utc={report.get('generated_at_utc')}  "
        f"apply_blocked={report.get('apply_blocked')}",
        "",
        "1. CURRENT STATE",
        f"{'TABLE':46} {'ACTION':16} {'IN SCOPE':>10} {'RETAINED':>10}",
        "-" * 86,
    ]
    for t in report.get("targets") or []:
        lines.append(
            f"{t['table']:46} {t['action']:16} "
            f"{t['rows_in_scope']:>10} {t['rows_retained']:>10}"
        )

    scope = report.get("scope_protection") or {}
    lines += [
        "",
        "2. SCOPE PROTECTION (HD must be 0)",
        f"  hd_rows_in_clear_scope = {scope.get('hd_rows_in_clear_scope')} "
        f"(expected {scope.get('expected')}) ok={scope.get('ok')}",
    ]
    for table, n in (scope.get("non_wf_rows_protected") or {}).items():
        lines.append(f"  protected non-WF rows  {table:44} {n}")
    for table, n in (scope.get("hd_now_bags_retained") or {}).items():
        lines.append(f"  RISK retained HD-now   {table:44} {n}")
    for table, n in (scope.get("non_wf_registry_rows_reset") or {}).items():
        lines.append(f"  non-WF completion reset (UPDATE, no delete) {table:22} {n}")

    lines += ["", "3. ARCHIVE PLAN"]
    for row in report.get("archive_plan") or []:
        lines.append(
            f"  {row['table']:46} archive={row['rows_to_archive']:>8} "
            f"clear={row['rows_to_clear']:>8} update={row['rows_to_update']:>8}"
        )
    totals = report.get("totals") or {}
    lines.append(
        f"  {'TOTAL':46} archive={totals.get('archive_rows', 0):>8} "
        f"clear={totals.get('clear_rows', 0):>8} "
        f"update={totals.get('registry_update_rows', 0):>8}"
    )
    lines.append(f"  archive_dir: {report.get('archive_dir')}")

    samples = report.get("samples") or {}
    lines += ["", "4. SAMPLES"]
    for s in (samples.get("order_instances") or [])[:10]:
        lines.append(
            f"  OI  {str(s.get('order_display_id')):28} "
            f"anchor={s.get('cycle_anchor_at')} completed={s.get('completed_at')}"
        )
    for s in (samples.get("registry_rows_to_reset") or [])[:10]:
        lines.append(
            f"  REG {str(s.get('bag_id')):12} svc={str(s.get('service_type')):4} "
            f"{s.get('completion_status')} completed_at={s.get('completed_at')}"
        )

    lines += ["", "5. RESURRECTION RESIDUAL (retained + epoch-fenced)"]
    for row in report.get("resurrection_residual") or []:
        lines.append(f"  {row['table']:46} rows={row['rows_retained']}")
        lines.append(f"      guard: {row['guard']}")

    epoch = report.get("epoch") or {}
    lines += [
        "",
        "6. EPOCH / MAINTENANCE",
        f"  {WF_RESET_EPOCH_KEY} = {epoch.get('current_value')}",
        f"  {WF_OPS_MAINTENANCE_KEY} on = {epoch.get('maintenance_on')}",
    ]

    if report.get("stop_reasons"):
        lines += ["", "STOP REASONS:"]
        lines += [f"  - {s}" for s in report["stop_reasons"]]
    return "\n".join(lines)
