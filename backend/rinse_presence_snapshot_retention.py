"""Presence snapshot retention — retain authoritative scrape evidence.

Historical note (pre evidence-first):
  KEEP_LATEST_SUCCESSFUL_SNAPSHOTS = 3
  prune_presence_run_snapshots deleted older successful run_rows + orphan runs
  after every successful apply_presence_scrape.

That deleted same-day baselines (e.g. Jul 23 org3 run #3472) and broke
membership / Pre-Post rebuild. Authoritative evidence is never pruned by
latest-N.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
from backend.ta_helpers import table_exists

# Deprecated: retained only so imports/tests that reference the symbol still resolve.
# Do not use for pruning authoritative evidence.
KEEP_LATEST_SUCCESSFUL_SNAPSHOTS = 0

# Org 3 (VeeWash) cutover: retain every valid run/row from this date forward.
EVIDENCE_RETENTION_FLOOR_ET = date(2026, 7, 23)
EVIDENCE_RETENTION_ORG_IDS = frozenset({3})

RETENTION_POLICY = "retain_all_authoritative_evidence"


def _is_successful_presence_run(run: Mapping[str, Any]) -> bool:
    status = str(run.get("status") or "").strip().lower()
    if status in ("success", "partial"):
        return True
    errors = run.get("errors_json")
    return status == "" and errors in (None, "", "[]", "null", "NULL")


def _list_successful_presence_runs(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    rinse_vendor: str | None = None,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return []
    org = int(organization_id)
    ps = str(portal_status or "").strip()
    vendor = str(rinse_vendor or "").strip().lower() or None
    sql = """
        SELECT id, organization_id, portal_status, source_batch_id, status, finished_at, created_at,
               scrape_meta_json, rows_found
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND portal_status = %s AND dry_run = 0
        ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
    """
    cursor.execute(sql, (org, ps))
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or not _is_successful_presence_run(row):
            continue
        if vendor:
            meta = row.get("scrape_meta_json")
            meta_vendor = None
            if isinstance(meta, dict):
                meta_vendor = str(meta.get("rinse_vendor") or meta.get("resolved_vendor") or "").strip().lower()
            if meta_vendor and meta_vendor != vendor:
                continue
        out.append(dict(row))
    return out


def resolve_protected_presence_run_ids(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    selected_date_et: date | None = None,
) -> set[int]:
    """
    All successful runs are protected under retain-all policy.

    selected_date_et is accepted for call-site compatibility.
    """
    del selected_date_et
    runs = _list_successful_presence_runs(cursor, organization_id, portal_status=portal_status)
    return {int(r.get("id") or 0) for r in runs if int(r.get("id") or 0)}


def prune_presence_run_snapshots(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    rinse_vendor: str | None = None,
    selected_date_et: date | None = None,
    keep_latest: int | None = None,
) -> dict[str, Any]:
    """
    No-op prune for authoritative evidence.

    Never deletes presence run headers or run rows used for membership / Pre-Post.
    Long-term storage should archive offline rather than delete.
    """
    del keep_latest  # latest-N pruning removed
    runs = []
    if table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        runs = _list_successful_presence_runs(
            cursor, organization_id, portal_status=portal_status, rinse_vendor=rinse_vendor
        )
    keep_ids = sorted(int(r.get("id") or 0) for r in runs if int(r.get("id") or 0))
    return {
        "portal_status": portal_status,
        "rinse_vendor": rinse_vendor,
        "selected_date_et": selected_date_et.isoformat() if selected_date_et else None,
        "policy": RETENTION_POLICY,
        "evidence_floor_et": EVIDENCE_RETENTION_FLOOR_ET.isoformat(),
        "protected_org_ids": sorted(EVIDENCE_RETENTION_ORG_IDS),
        "runs_before": len(keep_ids),
        "kept_run_ids": keep_ids,
        "pruned_run_ids": [],
        "deleted_run_rows": 0,
        "deleted_runs": 0,
        "protected_baseline_run_ids": [],
        "note": (
            "Authoritative presence evidence is retained indefinitely. "
            f"Org {sorted(EVIDENCE_RETENTION_ORG_IDS)} floor "
            f"{EVIDENCE_RETENTION_FLOOR_ET.isoformat()}; no latest-N deletion."
        ),
    }


# Re-export for callers that imported baseline helper through this module historically.
def select_daily_at_vendor_baseline_scrape(*args, **kwargs):
    from backend.rinse_shift_monitor_baseline import select_daily_at_vendor_baseline_scrape as _sel

    return _sel(*args, **kwargs)


__all__ = [
    "KEEP_LATEST_SUCCESSFUL_SNAPSHOTS",
    "EVIDENCE_RETENTION_FLOOR_ET",
    "EVIDENCE_RETENTION_ORG_IDS",
    "RETENTION_POLICY",
    "PORTAL_STATUS_AT_VENDOR",
    "prune_presence_run_snapshots",
    "resolve_protected_presence_run_ids",
    "select_daily_at_vendor_baseline_scrape",
]
