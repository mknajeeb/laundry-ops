#!/usr/bin/env python3
"""Dry-run folding exception rule changes for an org (no DB writes)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from typing import Any

sys.path.insert(0, ".")

EXCEPTION_CODES_REPORT = (
    "MISSING_CLEAN",
    "MISSING_FOLDING",
    "CLEAN_BEFORE_FOLDING",
    "FOLDING_DURATION_TOO_SHORT",
    "FOLDING_DURATION_TOO_LONG",
    "MULTIPLE_CLEAN_SCANS",
    "OVERLAP_OR_INVALID_TIMING",
    "MULTIPLE_FOLDING_SCANS",
)


def _resolve_batch_id(cursor, organization_id: int, raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if str(raw).strip().lower() == "latest":
        cursor.execute(
            """
            SELECT MAX(last_upload_batch_id) AS mx
            FROM rinse_bag_registry
            WHERE organization_id = %s
            """,
            (int(organization_id),),
        )
        row = cursor.fetchone() or {}
        mx = row.get("mx") if isinstance(row, dict) else row[0] if row else None
        return int(mx) if mx is not None else None
    return int(raw)


def _effective_scoring_status(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("scoring_status") or row.get("status") or "").upper()


def _normalize_warning_codes_json(raw: Any) -> str | None:
    from backend.rinse_bag_folding import parse_stored_warning_codes
    import json

    codes = parse_stored_warning_codes(raw)
    return json.dumps(codes) if codes else None


def _fields_after_recompute(
    existing: dict[str, Any] | None, compute
) -> dict[str, Any]:
    from backend.rinse_folding_scoring import scoring_fields_from_compute
    import json

    scoring = scoring_fields_from_compute(
        status=str(compute.status),
        exception_code=compute.exception_code,
        existing=existing,
        preserve_review=True,
    )
    warnings = list(getattr(compute, "warning_codes", ()) or ())
    return {
        "status": compute.status,
        "exception_code": compute.exception_code,
        "warning_codes": json.dumps(warnings) if warnings else None,
        "scoring_status": scoring["scoring_status"],
        "included_in_scoring": int(scoring["included_in_scoring"]),
    }


def _would_change(existing: dict[str, Any] | None, proposed: dict[str, Any]) -> bool:
    if not existing:
        return True
    for key in ("status", "exception_code", "warning_codes", "scoring_status", "included_in_scoring"):
        old = existing.get(key)
        new = proposed.get(key)
        if key == "included_in_scoring":
            old = int(old or 0)
            new = int(new or 0)
        elif key == "warning_codes":
            old = _normalize_warning_codes_json(old)
            new = _normalize_warning_codes_json(new)
        else:
            old = None if old is None else str(old)
            new = None if new is None else str(new)
        if old != new:
            return True
    return False


def _run_dry_run(
    cursor,
    *,
    org: int,
    from_batch: int | None,
    to_batch: int | None,
    label: str,
) -> dict[str, Any]:
    from backend.rinse_bag_completion import COMPLETION_COMPLETED
    from backend.rinse_bag_folding import (
        STATUS_CALCULATED,
        STATUS_EXCEPTION,
        WARNING_MULTIPLE_CLEAN_SCANS,
        FOLDING_WARNING_CODES,
    )
    from backend.rinse_bag_registry import fetch_persistent_scan_events_for_bag, get_registry_row
    from backend.rinse_folding_exception_rules import get_folding_exception_rules, get_folding_exception_rules_typed
    from backend.rinse_bag_folding import evaluate_folding_performance_for_bag
    from backend.rinse_folding_registry import ensure_rinse_folding_tables, get_folding_performance_row
    from backend.rinse_folding_scoring import SCORING_APPROVED

    ensure_rinse_folding_tables(cursor)
    rules_dict = get_folding_exception_rules(cursor, org)
    rules = get_folding_exception_rules_typed(cursor, org)

    cursor.execute(
        """
        SELECT COALESCE(scoring_status, status) AS st, COUNT(*) AS cnt
        FROM rinse_folding_performance
        WHERE organization_id = %s
        GROUP BY COALESCE(scoring_status, status)
        """,
        (org,),
    )
    current_status_counts: Counter[str] = Counter()
    for row in cursor.fetchall() or []:
        current_status_counts[str(row.get("st") or "").upper()] += int(row.get("cnt") or 0)

    sql = """
        SELECT bag_id FROM rinse_bag_registry
        WHERE organization_id = %s AND completion_status = %s
    """
    sql_args: list = [org, COMPLETION_COMPLETED]
    if from_batch is not None:
        sql += " AND last_upload_batch_id >= %s"
        sql_args.append(int(from_batch))
    if to_batch is not None:
        sql += " AND last_upload_batch_id <= %s"
        sql_args.append(int(to_batch))
    cursor.execute(sql, tuple(sql_args))
    bags = [r["bag_id"] for r in cursor.fetchall() or [] if r.get("bag_id")]

    calc_to_exception: list[dict[str, Any]] = []
    exception_to_calculated: list[dict[str, Any]] = []
    approved_preserved: list[dict[str, Any]] = []
    warning_only: list[dict[str, Any]] = []
    unchanged: list[str] = []
    would_change: list[dict[str, Any]] = []
    proposed_code_counts: Counter[str] = Counter()
    proposed_warning_code_counts: Counter[str] = Counter()
    current_code_counts: Counter[str] = Counter()

    for bid in bags:
        reg = get_registry_row(cursor, org, bid)
        if not reg:
            continue
        existing = get_folding_performance_row(cursor, org, bid)
        if existing and existing.get("exception_code"):
            current_code_counts[str(existing["exception_code"])] += 1

        events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
        compute = evaluate_folding_performance_for_bag(events, registry_row=reg, rules=rules)
        proposed = _fields_after_recompute(existing, compute)

        code = proposed.get("exception_code")
        if code:
            proposed_code_counts[str(code)] += 1
        from backend.rinse_bag_folding import parse_stored_warning_codes

        for wc in parse_stored_warning_codes(proposed.get("warning_codes")):
            proposed_warning_code_counts[str(wc)] += 1

        old_status = str((existing or {}).get("status") or "").upper()
        old_scoring = _effective_scoring_status(existing)
        new_status = str(proposed["status"] or "").upper()
        new_scoring = str(proposed["scoring_status"] or "").upper()
        new_code = proposed.get("exception_code")

        if not _would_change(existing, proposed):
            unchanged.append(bid)
            continue

        change_row = {
            "bag_id": bid,
            "before_status": old_status or None,
            "before_scoring": old_scoring or None,
            "before_code": (existing or {}).get("exception_code"),
            "after_status": new_status,
            "after_scoring": new_scoring,
            "after_code": new_code,
        }
        would_change.append(change_row)

        if old_status == STATUS_CALCULATED and new_status == STATUS_EXCEPTION:
            calc_to_exception.append(change_row)
        elif old_status == STATUS_EXCEPTION and new_status == STATUS_CALCULATED:
            exception_to_calculated.append(change_row)
        elif old_scoring == SCORING_APPROVED and new_scoring == SCORING_APPROVED:
            approved_preserved.append(change_row)
        elif (
            new_status == STATUS_CALCULATED
            and new_code
            and (new_code in FOLDING_WARNING_CODES or new_code == WARNING_MULTIPLE_CLEAN_SCANS)
        ):
            warning_only.append(change_row)

    report = {
        "label": label,
        "org": org,
        "batch_filter": {
            "from_batch": from_batch,
            "to_batch": to_batch,
        },
        "exception_rules": rules_dict,
        "exception_rules_typed": asdict(rules),
        "total_completed_bags_evaluated": len(bags),
        "current_status_counts": dict(current_status_counts),
        "proposed_changes": {
            "calculated_to_exception": len(calc_to_exception),
            "exception_to_calculated": len(exception_to_calculated),
            "approved_preserved": len(approved_preserved),
            "warning_only": len(warning_only),
            "unchanged": len(unchanged),
            "would_change_total": len(would_change),
        },
        "bags_calculated_to_exception": [r["bag_id"] for r in calc_to_exception],
        "bags_exception_to_calculated": [r["bag_id"] for r in exception_to_calculated],
        "bags_approved_preserved": [r["bag_id"] for r in approved_preserved],
        "bags_warning_only": [r["bag_id"] for r in warning_only],
        "bags_unchanged": unchanged,
        "bags_would_change": [r["bag_id"] for r in would_change],
        "bags_would_change_detail": would_change,
        "current_exception_code_counts": {
            c: current_code_counts.get(c, 0) for c in EXCEPTION_CODES_REPORT
        },
        "proposed_exception_code_counts": {
            c: proposed_code_counts.get(c, 0) for c in EXCEPTION_CODES_REPORT
        },
        "proposed_exception_code_counts_all": dict(proposed_code_counts),
        "proposed_warning_code_counts": dict(proposed_warning_code_counts),
        "safety": {
            "scan_timestamps_rewritten": False,
            "upload_staging_registry_rows_changed": False,
            "approved_reviewed_overrides_preserved": True,
            "notes": [
                "Dry-run only: no INSERT/UPDATE/DELETE executed.",
                "Recompute updates rinse_folding_performance only; scan events and registry are read-only.",
                "scoring_fields_from_compute(preserve_review=True) keeps APPROVED and EXCLUDED scoring.",
                "reviewed_at, reviewed_by_user_id, exception_review_note, admin_notes are not touched by recompute.",
            ],
        },
    }
    return report


def _print_report(report: dict[str, Any]) -> None:
    org = report["org"]
    bf = report["batch_filter"]
    print("=" * 72)
    print(report["label"])
    print("=" * 72)
    if bf["from_batch"] is not None or bf["to_batch"] is not None:
        print(f"Batch filter: from={bf['from_batch']} to={bf['to_batch']}")
    print()
    print("1. Current exception rule settings")
    print(json.dumps(report["exception_rules"], indent=2))
    print()
    print("2. Total completed bags evaluated:", report["total_completed_bags_evaluated"])
    print()
    print("3. Current status counts (rinse_folding_performance, org scope)")
    for st in ("CALCULATED", "EXCEPTION", "APPROVED", "EXCLUDED"):
        print(f"   {st}: {report['current_status_counts'].get(st, 0)}")
    print()
    pc = report["proposed_changes"]
    print("4. Proposed changes")
    print(f"   CALCULATED → EXCEPTION: {pc['calculated_to_exception']}")
    print(f"   EXCEPTION → CALCULATED: {pc['exception_to_calculated']}")
    print(f"   APPROVED preserved (scoring stays APPROVED): {pc['approved_preserved']}")
    print(f"   Warning-only rows: {pc['warning_only']}")
    print(f"   Unchanged: {pc['unchanged']}")
    print(f"   Total would change: {pc['would_change_total']}")
    print()
    print("5. Exception code counts (current stored / proposed after rules)")
    for c in EXCEPTION_CODES_REPORT:
        cur = report["current_exception_code_counts"].get(c, 0)
        prop = report["proposed_exception_code_counts"].get(c, 0)
        print(f"   {c}: current={cur} proposed={prop}")
    print()
    print("6. Bag IDs that would change")
    for bid in report["bags_would_change"]:
        print(f"   {bid}")
    if not report["bags_would_change"]:
        print("   (none)")
    print()
    print("7. Scan timestamps rewritten:", report["safety"]["scan_timestamps_rewritten"])
    print("8. Upload/staging/registry rows changed:", report["safety"]["upload_staging_registry_rows_changed"])
    print("9. Approved/reviewed overrides preserved:", report["safety"]["approved_reviewed_overrides_preserved"])
    for note in report["safety"]["notes"]:
        print(f"   - {note}")
    print()
    print("Dry-run only — no rows updated.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run folding exception rules recompute")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--from-batch", type=str, default=None)
    parser.add_argument("--to-batch", type=str, default=None)
    parser.add_argument("--json", action="store_true", help="Emit full JSON report to stdout")
    args = parser.parse_args()

    from backend.db import get_db

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        org = int(args.org)
        from_batch = _resolve_batch_id(cursor, org, args.from_batch)
        to_batch = _resolve_batch_id(cursor, org, args.to_batch)

        if from_batch is not None or to_batch is not None:
            label = f"Org {org} — batch filter {from_batch}..{to_batch}"
        else:
            label = f"Org {org} — all completed bags"

        report = _run_dry_run(
            cursor,
            org=org,
            from_batch=from_batch,
            to_batch=to_batch,
            label=label,
        )

        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            _print_report(report)
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
