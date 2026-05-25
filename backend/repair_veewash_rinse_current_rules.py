"""
Tenant-scoped Rinse data repair / backfill for current business rules.

Default organization: VeeWash (org 3). Dry-run by default; idempotent apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from backend.repair_latest_upload_batch import (
    _apply_staging_for_accepted_rows,
    _collect_bag_ids_from_batch,
    _fix_stale_already_completed_rows,
    _load_portal_rows,
    _orders_status_capabilities,
    _upload_batches_pk,
    _where_active_at_washpro_sql,
    resolve_organization_id,
)
from backend.repair_upload_batch_ok_reasons import (
    analyze_repairs,
    apply_repairs,
    load_batches,
)
from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    REASON_ALREADY_COMPLETED,
    REASON_CLEAN_RACK_SCANNED,
    REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
    REASON_NO_CLEAN_SCAN,
    REASON_OK,
    REASON_POST_CLEAN_RACK_AND_USER,
    REASON_CLEAN_WITHOUT_QUALIFYING_LATER,
    REASON_UPDATED_EXISTING_BAG,
    ROW_ACCEPTED,
    ROW_REJECTED,
    classify_portal_upload_row,
    evaluate_bag_completion,
    normalize_bag_id,
)
from backend.rinse_bag_folding import evaluate_folding_performance_for_bag
from backend.rinse_bag_registry import (
    apply_completion_to_registry,
    fetch_persistent_scan_events_for_bag,
    get_registry_row,
    recompute_completion_for_bags,
)
from backend.rinse_bag_upload import find_active_staging_for_portal_upload
from backend.rinse_folding_registry import (
    get_folding_performance_row,
    recompute_folding_performance_for_bags,
    summarize_recompute_results,
)
from backend.rinse_portal_scrape_meta import (
    fetch_portal_scrape_meta_for_batch,
    portal_scrape_meta_allows_absence_completion,
)
from backend.rinse_scan_time import (
    serialize_rinse_scan_datetime_for_api,
    serialize_system_datetime_for_api,
)
from backend.rinse_scrape_status import fetch_scrape_run_for_batch
from backend.ta_helpers import table_exists, table_has_column

DEFAULT_ORG_ID = 3
LEGACY_COMPLETION_REASONS = frozenset(
    {
        REASON_POST_CLEAN_RACK_AND_USER,
        REASON_CLEAN_WITHOUT_QUALIFYING_LATER,
        "POST_CLEAN_RACK_AND_USER",
        "CLEAN_WITHOUT_QUALIFYING_LATER_SCAN",
        "WORKFLOW_THEN_CLEAN",
    }
)
CURRENT_COMPLETION_REASONS = frozenset(
    {
        REASON_NO_CLEAN_SCAN,
        REASON_CLEAN_RACK_SCANNED,
        REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
    }
)


@dataclass
class RepairCounters:
    upload_rows_inspected: int = 0
    upload_ok_to_updated: int = 0
    upload_wrong_reject_repaired: int = 0
    upload_wrong_accept_repaired: int = 0
    registry_recomputed: int = 0
    registry_legacy_reason_replaced: int = 0
    registry_would_change: int = 0
    staging_rows_inserted: int = 0
    staging_rows_updated: int = 0
    staging_rows_skipped: int = 0
    duplicate_active_staging_flagged: int = 0
    folding_rows_recomputed: int = 0
    folding_calculated_to_exception: int = 0
    folding_exception_created: int = 0
    folding_status_changes: int = 0
    folding_skipped: int = 0
    rows_skipped: int = 0
    warnings_manual_review: int = 0
    scrape_batches_linked: int = 0
    scrape_batches_unlinked: int = 0

    def to_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items()}


def _batch_anchor(row: dict[str, Any]) -> datetime | None:
    for key in ("confirmed_at", "created_at", "uploaded_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            return val
    return None


def _registry_completed_before(reg: dict[str, Any] | None, anchor: datetime | None) -> bool:
    if not reg:
        return False
    if str(reg.get("completion_status") or "").upper() != COMPLETION_COMPLETED:
        return False
    completed_at = reg.get("completed_at")
    if isinstance(completed_at, datetime) and isinstance(anchor, datetime):
        return completed_at < anchor
    return True


def resolve_batch_id_range(
    cursor,
    organization_id: int,
    from_batch: int,
    to_batch: str | int,
) -> list[int]:
    pk = _upload_batches_pk(cursor)
    org_clause = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_clause = " WHERE organization_id = %s"
        args.append(int(organization_id))

    if str(to_batch).strip().lower() == "latest":
        cursor.execute(
            f"SELECT MAX({pk}) AS mx FROM upload_batches{org_clause}",
            tuple(args),
        )
        row = cursor.fetchone()
        max_id = int((row or {}).get("mx") or from_batch)
        to_batch = max_id

    hi = int(to_batch)
    lo = int(from_batch)
    if hi < lo:
        lo, hi = hi, lo

    cursor.execute(
        f"""
        SELECT {pk} AS batch_id FROM upload_batches
        WHERE {pk} >= %s AND {pk} <= %s
        {('AND organization_id = %s' if org_clause else '')}
        ORDER BY {pk} ASC
        """,
        tuple([lo, hi, int(organization_id)] if org_clause else [lo, hi]),
    )
    return [int(r["batch_id"]) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def _load_batch_meta(cursor, org_id: int, batch_id: int) -> dict[str, Any]:
    pk = _upload_batches_pk(cursor)
    cols = [f"{pk} AS batch_id", "state", "batch_date"]
    for c in ("uploaded_at", "created_at", "confirmed_at", "full_snapshot", "portal_scrape_meta"):
        if table_has_column(cursor, "upload_batches", c):
            cols.append(c)
    org_sql = ""
    args: list[Any] = [int(batch_id)]
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_sql = " AND organization_id = %s"
        args.append(int(org_id))
    cursor.execute(
        f"SELECT {', '.join(cols)} FROM upload_batches WHERE {pk} = %s{org_sql} LIMIT 1",
        tuple(args),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else {}


def analyze_wrong_upload_classifications(
    cursor,
    org_id: int,
    batch_ids: list[int],
    batches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rows whose status/reason disagrees with current rules at batch anchor time."""
    cap = _orders_status_capabilities(cursor)
    active_where = _where_active_at_washpro_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")

    wrong_reject: list[dict[str, Any]] = []
    wrong_accept: list[dict[str, Any]] = []
    inspected = 0

    batch_by_id = {int(b["batch_id"]): b for b in batches}
    for bid in batch_ids:
        batch = batch_by_id.get(int(bid)) or _load_batch_meta(cursor, org_id, bid)
        anchor = _batch_anchor(batch)
        portal_rows = _load_portal_rows(cursor, bid)
        for row in portal_rows:
            inspected += 1
            status = str(row.get("row_status") or "").upper()
            reason = str(row.get("reason") or "")
            tid = normalize_bag_id(row.get("ticket_id"))
            if not tid:
                continue

            reg = get_registry_row(cursor, org_id, tid)
            completed_before = _registry_completed_before(reg, anchor)
            staging = find_active_staging_for_portal_upload(
                cursor,
                org_id,
                tid,
                active_where,
                has_staging_org=has_staging_org,
                portal_row={
                    "name_clean": row.get("name_clean"),
                    "weight_num": row.get("weight_num"),
                    "service_type": row.get("service_type"),
                    "date_clean": row.get("date_clean"),
                },
            )
            expected_status, expected_reason = classify_portal_upload_row(
                ticket_id=tid,
                was_completed_before_upload=completed_before,
                has_active_staging=bool(staging),
                row_date_before_batch=False,
            )

            if status == expected_status and reason == expected_reason:
                continue

            change = {
                "batch_id": bid,
                "row_id": row.get("row_id"),
                "ticket_id": tid,
                "from_status": status,
                "from_reason": reason,
                "to_status": expected_status,
                "to_reason": expected_reason,
                "completed_before_upload": completed_before,
                "has_active_staging": bool(staging),
                "registry_status": reg.get("completion_status") if reg else None,
            }

            if (
                status == ROW_REJECTED
                and reason == REASON_ALREADY_COMPLETED
                and expected_status == ROW_ACCEPTED
            ):
                wrong_reject.append(change)
            elif status in (ROW_ACCEPTED, "OVERRIDDEN") and (
                reason != expected_reason
                or (completed_before and expected_status == ROW_REJECTED)
            ):
                wrong_accept.append(change)

    return {
        "upload_rows_inspected_extra": inspected,
        "wrong_reject_to_accept": wrong_reject,
        "wrong_accept_to_fix": wrong_accept,
    }


def analyze_registry_completion(
    cursor, org_id: int, bag_ids: set[str]
) -> dict[str, Any]:
    legacy: list[dict[str, Any]] = []
    would_change: list[dict[str, Any]] = []
    portal_absence: list[dict[str, Any]] = []

    for bid in sorted(bag_ids):
        reg = get_registry_row(cursor, org_id, bid)
        if not reg:
            continue
        cur_reason = str(reg.get("completion_reason") or "")
        if cur_reason == REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD:
            portal_absence.append(
                {
                    "bag_id": bid,
                    "completion_status": reg.get("completion_status"),
                    "completed_at": reg.get("completed_at"),
                }
            )
        events = fetch_persistent_scan_events_for_bag(cursor, org_id, bid)
        expected = evaluate_bag_completion(events)
        exp_fields = expected.to_registry_update()
        exp_reason = str(exp_fields.get("completion_reason") or "")
        exp_status = str(exp_fields.get("completion_status") or "")

        if cur_reason in LEGACY_COMPLETION_REASONS:
            legacy.append(
                {
                    "bag_id": bid,
                    "from_reason": cur_reason,
                    "to_status": exp_status,
                    "to_reason": exp_reason,
                }
            )

        cur_status = str(reg.get("completion_status") or "")
        if cur_status != exp_status or (
            cur_reason not in CURRENT_COMPLETION_REASONS
            and cur_reason not in LEGACY_COMPLETION_REASONS
            and cur_reason != exp_reason
        ):
            if cur_reason != REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD:
                would_change.append(
                    {
                        "bag_id": bid,
                        "from_status": cur_status,
                        "from_reason": cur_reason,
                        "to_status": exp_status,
                        "to_reason": exp_reason,
                    }
                )

    return {
        "legacy_reason_bags": legacy,
        "would_change_bags": would_change,
        "portal_absence_completed": portal_absence,
    }


def analyze_portal_absence_safety(
    cursor, org_id: int, batch_ids: list[int], portal_absence_bags: list[dict]
) -> dict[str, Any]:
    """Batches where absence completion may have been unsafe (partial scrape)."""
    unsafe_batches: list[dict[str, Any]] = []
    reversal_candidates: list[dict[str, Any]] = []

    for bid in batch_ids:
        meta = fetch_portal_scrape_meta_for_batch(cursor, bid, org_id)
        allows = portal_scrape_meta_allows_absence_completion(meta)
        batch = _load_batch_meta(cursor, org_id, bid)
        if not allows and str(batch.get("state") or "").upper() == "CONFIRMED":
            unsafe_batches.append(
                {
                    "batch_id": bid,
                    "portal_scrape_meta": meta,
                    "full_snapshot": batch.get("full_snapshot"),
                }
            )

    for item in portal_absence_bags:
        reversal_candidates.append(
            {
                "bag_id": item["bag_id"],
                "note": "Registry COMPLETED via MISSING_FROM_LATEST; review if partial scrape",
                "manual_review": True,
            }
        )

    return {
        "unsafe_absence_batches": unsafe_batches,
        "reversal_candidates": reversal_candidates,
    }


def analyze_folding_changes(cursor, org_id: int, bag_ids: list[str]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    skipped = 0
    for bid in bag_ids:
        reg = get_registry_row(cursor, org_id, bid)
        if not reg or str(reg.get("completion_status") or "").upper() != COMPLETION_COMPLETED:
            skipped += 1
            continue
        current = get_folding_performance_row(cursor, org_id, bid)
        if current and table_exists(cursor, "rinse_folding_performance_overrides"):
            cursor.execute(
                """
                SELECT 1 FROM rinse_folding_performance_overrides
                WHERE organization_id = %s AND bag_id = %s LIMIT 1
                """,
                (org_id, bid),
            )
            if cursor.fetchone():
                skipped += 1
                continue
        events = fetch_persistent_scan_events_for_bag(cursor, org_id, bid)
        result = evaluate_folding_performance_for_bag(events, registry_row=reg)
        row_fields = result.to_performance_row(
            registry_completion_status=COMPLETION_COMPLETED
        )
        new_status = str(row_fields.get("status") or "")
        new_code = str(row_fields.get("exception_code") or "")
        cur_status = str((current or {}).get("status") or "")
        cur_code = str((current or {}).get("exception_code") or "")
        if not current:
            changes.append(
                {
                    "bag_id": bid,
                    "action": "create",
                    "to_status": new_status,
                    "to_code": new_code,
                }
            )
        elif cur_status != new_status or cur_code != new_code:
            changes.append(
                {
                    "bag_id": bid,
                    "from_status": cur_status,
                    "from_code": cur_code,
                    "to_status": new_status,
                    "to_code": new_code,
                }
            )

    calc_to_exc = sum(
        1
        for c in changes
        if c.get("from_status") == "CALCULATED" and c.get("to_status") == "EXCEPTION"
    )
    return {
        "folding_changes": changes,
        "folding_skipped_not_completed_or_override": skipped,
        "folding_calculated_to_exception": calc_to_exc,
    }


def analyze_scrape_linkage(cursor, org_id: int, batch_ids: list[int]) -> dict[str, Any]:
    linked: list[dict[str, Any]] = []
    unlinked: list[int] = []
    for bid in batch_ids:
        run = fetch_scrape_run_for_batch(cursor, org_id, bid)
        if run:
            linked.append(
                {
                    "batch_id": bid,
                    "scrape_run_id": run.get("scrape_run_id"),
                    "scrape_status": run.get("scrape_status"),
                }
            )
        else:
            unlinked.append(bid)
    return {"linked": linked, "unlinked_batch_ids": unlinked}


def analyze_timezone_spot_checks(cursor, org_id: int) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    cursor.execute(
        """
        SELECT bag_id, time_scanned_raw, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id = %s
        ORDER BY scan_index ASC LIMIT 1
        """,
        (org_id, "6QUX3NWKDA"),
    )
    scan = cursor.fetchone()
    if scan:
        p = scan.get("scanned_at_parsed")
        checks.append(
            {
                "check": "scan_event_6QUX3NWKDA",
                "raw": scan.get("time_scanned_raw"),
                "api_iso": serialize_rinse_scan_datetime_for_api(p) if p else None,
                "expect_display": "5:25 PM ET (not 1:25 PM)",
            }
        )

    if table_exists(cursor, "rinse_scrape_runs"):
        cursor.execute(
            """
            SELECT finished_at FROM rinse_scrape_runs
            WHERE organization_id = %s AND status = 'success'
            ORDER BY finished_at DESC LIMIT 1
            """,
            (org_id,),
        )
        row = cursor.fetchone()
        if row and row.get("finished_at"):
            fin = row["finished_at"]
            checks.append(
                {
                    "check": "latest_scrape_finished_at",
                    "db_naive_utc": str(fin),
                    "api_iso_system": serialize_system_datetime_for_api(fin),
                    "expect": "ET display ~4h earlier than mis-tagged UTC-as-ET",
                }
            )
    return {"timezone_spot_checks": checks, "db_rewrite_needed": False}


def build_repair_plan(
    cursor,
    *,
    organization_id: int,
    from_batch: int,
    to_batch: str | int = "latest",
) -> dict[str, Any]:
    org_id = int(organization_id)
    batch_ids = resolve_batch_id_range(cursor, org_id, from_batch, to_batch)
    if not batch_ids:
        raise ValueError(f"No upload batches in range {from_batch}..{to_batch} for org {org_id}")

    batches = load_batches(cursor, org_id, batch_ids)
    ok_report = analyze_repairs(cursor, org_id, batch_ids)
    wrong = analyze_wrong_upload_classifications(cursor, org_id, batch_ids, batches)

    all_bags: set[str] = set()
    for bid in batch_ids:
        all_bags.update(_collect_bag_ids_from_batch(cursor, org_id, bid))

    registry_report = analyze_registry_completion(cursor, org_id, all_bags)
    absence_safety = analyze_portal_absence_safety(
        cursor,
        org_id,
        batch_ids,
        registry_report.get("portal_absence_completed") or [],
    )

    completed_for_folding = [
        b
        for b in sorted(all_bags)
        if get_registry_row(cursor, org_id, b)
        and str(get_registry_row(cursor, org_id, b).get("completion_status") or "").upper()
        == COMPLETION_COMPLETED
    ]
    folding_report = analyze_folding_changes(cursor, org_id, completed_for_folding)
    scrape_report = analyze_scrape_linkage(cursor, org_id, batch_ids)
    tz_report = analyze_timezone_spot_checks(cursor, org_id)

    staging_dry: dict[str, int] = {
        "staging_rows_inserted": 0,
        "staging_rows_updated": 0,
        "staging_rows_skipped_identity_dup": 0,
    }
    cap = _orders_status_capabilities(cursor)
    active_where = _where_active_at_washpro_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")

    for b in batches:
        bid = int(b["batch_id"])
        if str(b.get("state") or "").upper() != "CONFIRMED":
            continue
        portal_rows = _load_portal_rows(cursor, bid)
        accepted = [
            r
            for r in portal_rows
            if str(r.get("row_status") or "").upper() in ("ACCEPTED", "OVERRIDDEN")
        ]
        stats = _apply_staging_for_accepted_rows(
            cursor,
            org_id,
            b,
            accepted,
            cap=cap,
            active_where=active_where,
            has_staging_org=has_staging_org,
            dry_run=True,
        )
        for k in staging_dry:
            staging_dry[k] += int(stats.get(k) or 0)

    counters = RepairCounters(
        upload_rows_inspected=wrong.get("upload_rows_inspected_extra", 0),
        upload_ok_to_updated=len(ok_report.get("to_update") or []),
        upload_wrong_reject_repaired=len(wrong.get("wrong_reject_to_accept") or []),
        upload_wrong_accept_repaired=len(wrong.get("wrong_accept_to_fix") or []),
        registry_legacy_reason_replaced=len(registry_report.get("legacy_reason_bags") or []),
        registry_would_change=len(registry_report.get("would_change_bags") or []),
        staging_rows_inserted=staging_dry["staging_rows_inserted"],
        staging_rows_updated=staging_dry["staging_rows_updated"],
        staging_rows_skipped=staging_dry["staging_rows_skipped_identity_dup"],
        duplicate_active_staging_flagged=len(ok_report.get("duplicate_active_staging") or []),
        folding_status_changes=len(folding_report.get("folding_changes") or []),
        folding_calculated_to_exception=folding_report.get("folding_calculated_to_exception", 0),
        folding_skipped=folding_report.get("folding_skipped_not_completed_or_override", 0),
        warnings_manual_review=len(absence_safety.get("reversal_candidates") or [])
        + len(absence_safety.get("unsafe_absence_batches") or []),
        scrape_batches_linked=len(scrape_report.get("linked") or []),
        scrape_batches_unlinked=len(scrape_report.get("unlinked_batch_ids") or []),
    )

    bags_to_change = sorted(
        {
            *(u.get("ticket_id") for u in ok_report.get("to_update") or []),
            *(c.get("ticket_id") for c in wrong.get("wrong_reject_to_accept") or []),
            *(c.get("ticket_id") for c in wrong.get("wrong_accept_to_fix") or []),
            *(c.get("bag_id") for c in registry_report.get("would_change_bags") or []),
            *(c.get("bag_id") for c in registry_report.get("legacy_reason_bags") or []),
            *(c.get("bag_id") for c in folding_report.get("folding_changes") or []),
        }
    )

    by_batch: list[dict[str, Any]] = []
    for b in batches:
        bid = int(b["batch_id"])
        by_batch.append(
            {
                "batch_id": bid,
                "state": b.get("state"),
                "ok_to_updated": sum(
                    1 for u in ok_report.get("to_update") or [] if u.get("batch_id") == bid
                ),
                "wrong_reject": sum(
                    1
                    for c in wrong.get("wrong_reject_to_accept") or []
                    if c.get("batch_id") == bid
                ),
                "wrong_accept": sum(
                    1
                    for c in wrong.get("wrong_accept_to_fix") or []
                    if c.get("batch_id") == bid
                ),
                "scrape_linked": any(
                    x.get("batch_id") == bid for x in scrape_report.get("linked") or []
                ),
            }
        )

    by_issue = {
        "ok_to_updated_existing_bag": len(ok_report.get("to_update") or []),
        "wrong_already_completed_reject": len(wrong.get("wrong_reject_to_accept") or []),
        "wrong_accept_reason": len(wrong.get("wrong_accept_to_fix") or []),
        "registry_legacy_reason": len(registry_report.get("legacy_reason_bags") or []),
        "registry_rule_recompute": len(registry_report.get("would_change_bags") or []),
        "folding_recompute": len(folding_report.get("folding_changes") or []),
        "duplicate_active_staging": len(ok_report.get("duplicate_active_staging") or []),
        "portal_absence_bags": len(registry_report.get("portal_absence_completed") or []),
        "unsafe_absence_batches": len(absence_safety.get("unsafe_absence_batches") or []),
    }

    return {
        "organization_id": org_id,
        "batch_ids": batch_ids,
        "from_batch": from_batch,
        "to_batch": batch_ids[-1] if batch_ids else to_batch,
        "counters": counters.to_dict(),
        "summary_by_batch": by_batch,
        "summary_by_issue_type": by_issue,
        "bag_ids_to_change": bags_to_change,
        "manual_review_bags": sorted(
            {
                *(c.get("bag_id") for c in absence_safety.get("reversal_candidates") or []),
            }
        ),
        "ok_to_updated_detail": ok_report.get("to_update") or [],
        "wrong_reject_detail": wrong.get("wrong_reject_to_accept") or [],
        "wrong_accept_detail": wrong.get("wrong_accept_to_fix") or [],
        "registry_legacy_detail": registry_report.get("legacy_reason_bags") or [],
        "registry_change_detail": registry_report.get("would_change_bags") or [],
        "folding_change_detail": folding_report.get("folding_changes") or [],
        "duplicate_active_staging": ok_report.get("duplicate_active_staging") or [],
        "portal_absence_safety": absence_safety,
        "scrape_linkage": scrape_report,
        "timezone": tz_report,
        "production_safe_to_apply": counters.warnings_manual_review == 0,
        "notes": [
            "Timezone: API/UI only; DB scan timestamps are not rewritten.",
            "Portal absence reversals are NOT auto-applied; review manual_review_bags first.",
            "Script is idempotent: apply only updates rows where current value differs.",
        ],
    }


def apply_upload_row_fixes(cursor, plan: dict[str, Any]) -> int:
    from backend.repair_upload_batch_ok_reasons import _upload_batch_rows_pk

    n = 0
    row_pk = _upload_batch_rows_pk(cursor)

    for u in plan.get("ok_to_updated_detail") or []:
        cursor.execute(
            f"""
            UPDATE upload_batch_rows
            SET reason = %s, updated_at = NOW()
            WHERE {row_pk} = %s
              AND row_status = 'ACCEPTED'
              AND UPPER(COALESCE(reason,'')) = %s
            """,
            (REASON_UPDATED_EXISTING_BAG, int(u["row_id"]), REASON_OK),
        )
        n += cursor.rowcount

    for c in plan.get("wrong_reject_detail") or [] + plan.get("wrong_accept_detail") or []:
        cursor.execute(
            f"""
            UPDATE upload_batch_rows
            SET row_status = %s, reason = %s, updated_at = NOW()
            WHERE {row_pk} = %s
              AND (row_status != %s OR COALESCE(reason,'') != %s)
            """,
            (
                c["to_status"],
                c["to_reason"],
                int(c["row_id"]),
                c["to_status"],
                c["to_reason"],
            ),
        )
        n += cursor.rowcount
    return n


def apply_repair_plan(
    cursor,
    plan: dict[str, Any],
    *,
    allow_absence_reversal: bool = False,
) -> dict[str, Any]:
    org_id = int(plan["organization_id"])
    batch_ids = plan["batch_ids"]
    applied: dict[str, Any] = {"upload_row_updates": 0, "batches_staging": []}

    applied["upload_row_updates"] = apply_upload_row_fixes(cursor, plan)

    cap = _orders_status_capabilities(cursor)
    active_where = _where_active_at_washpro_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    batches = load_batches(cursor, org_id, batch_ids)

    for b in batches:
        bid = int(b["batch_id"])
        if str(b.get("state") or "").upper() != "CONFIRMED":
            continue
        portal_rows = _load_portal_rows(cursor, bid)
        _fix_stale_already_completed_rows(
            cursor,
            org_id,
            portal_rows,
            cap=cap,
            active_where=active_where,
            has_staging_org=has_staging_org,
            dry_run=False,
        )
        accepted = [
            r
            for r in portal_rows
            if str(r.get("row_status") or "").upper() in ("ACCEPTED", "OVERRIDDEN")
        ]
        stats = _apply_staging_for_accepted_rows(
            cursor,
            org_id,
            b,
            accepted,
            cap=cap,
            active_where=active_where,
            has_staging_org=has_staging_org,
            dry_run=False,
        )
        applied["batches_staging"].append({"batch_id": bid, **stats})

    all_bags: set[str] = set()
    for bid in batch_ids:
        all_bags.update(_collect_bag_ids_from_batch(cursor, org_id, bid))

    completion_payload = recompute_completion_for_bags(cursor, org_id, sorted(all_bags))
    applied["completion"] = completion_payload

    completed = [
        b
        for b in sorted(all_bags)
        if get_registry_row(cursor, org_id, b)
        and str(get_registry_row(cursor, org_id, b).get("completion_status") or "").upper()
        == COMPLETION_COMPLETED
    ]
    folding_payload = recompute_folding_performance_for_bags(
        cursor, org_id, completed, source_recompute_kind="veewash_repair"
    )
    applied["folding_summary"] = summarize_recompute_results(
        folding_payload.get("bags") or []
    )
    applied["allow_absence_reversal"] = allow_absence_reversal
    if allow_absence_reversal:
        applied["absence_reversal"] = "not_implemented_requires_manual_review"

    return applied


def plan_to_json(plan: dict[str, Any]) -> str:
    def _default(o: Any) -> str:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)

    return json.dumps(plan, indent=2, default=_default)
