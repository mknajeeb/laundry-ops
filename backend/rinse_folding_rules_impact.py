"""Rule impact summaries: stored DB counts vs dry-run projections."""

from __future__ import annotations

from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_folding_exception_rules import (
    MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION,
    MULTIPLE_CLEAN_WARNING_EARLIEST,
    MULTIPLE_CLEAN_WARNING_LATEST,
    MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
    MULTIPLE_FOLDING_WARNING_EARLIEST,
    MULTIPLE_FOLDING_WARNING_LATEST,
    normalize_rules_api_dict,
)
from backend.rinse_folding_period import sql_period_filter_sql_and_args
from backend.rinse_bag_folding import parse_stored_warning_codes
from backend.rinse_folding_registry import ensure_rinse_folding_tables

EXCEPTION_CODES = (
    "MISSING_CLEAN",
    "MISSING_FOLDING",
    "CLEAN_BEFORE_FOLDING",
    "FOLDING_DURATION_TOO_SHORT",
    "FOLDING_DURATION_TOO_LONG",
    "MULTIPLE_CLEAN_SCANS",
    "OVERLAP_OR_INVALID_TIMING",
    "MULTIPLE_FOLDING_SCANS",
)


def _behavior_label(behavior: str, *, kind: str) -> str:
    if behavior == "exception":
        return "Exception — blocks scoring"
    if behavior.endswith("_latest"):
        return f"Warning — use latest {kind}, kept in scoring"
    return f"Warning — use earliest {kind}, kept in scoring"


def rules_status_summary(rules: dict[str, Any]) -> dict[str, Any]:
    r = normalize_rules_api_dict(rules)
    mf = r.get("multiple_folding_scans_behavior") or MULTIPLE_FOLDING_WARNING_EARLIEST
    mc = r.get("multiple_clean_scans_behavior") or MULTIPLE_CLEAN_WARNING_EARLIEST
    return {
        "min_duration_minutes": r.get("min_duration_minutes"),
        "max_duration_minutes": r.get("max_duration_minutes"),
        "min_duration_rule": "On" if r.get("rule_min_duration_enabled") else "Off",
        "max_duration_rule": "On" if r.get("rule_max_duration_enabled") else "Off",
        "multiple_folding_scans": _behavior_label(mf, kind="folding scan"),
        "multiple_folding_scans_behavior": mf,
        "multiple_clean_scans": _behavior_label(mc, kind="clean scan"),
        "multiple_clean_scans_behavior": mc,
        "missing_clean": "Exception" if r.get("rule_missing_clean") else "Off",
        "missing_folding": "Exception" if r.get("rule_missing_folding") else "Off",
        "clean_before_folding": "Exception" if r.get("rule_clean_before_folding") else "Off",
        "overlap_invalid_timing": "Exception" if r.get("rule_overlap_invalid_timing") else "Off",
    }


def _empty_code_counts() -> dict[str, int]:
    return {c: 0 for c in EXCEPTION_CODES}


def _impact_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    codes = _empty_code_counts()
    total = 0
    in_scoring = 0
    not_in_scoring = 0
    mf_warning_in_scoring = 0
    mf_exception = 0
    mf_secondary_warning = 0
    mc_warning_in_scoring = 0
    mc_exception = 0
    mc_secondary_warning = 0

    warning_in_scoring = 0

    for row in rows:
        total += 1
        code = str(row.get("exception_code") or "").strip()
        if code:
            codes[code] = codes.get(code, 0) + 1
        secondary = parse_stored_warning_codes(row.get("warning_codes"))
        included = bool(int(row.get("included_in_scoring") or 0))
        st = str(row.get("scoring_status") or row.get("status") or "").upper()
        if included and code and st != "EXCEPTION":
            warning_in_scoring += 1
        if included:
            in_scoring += 1
        else:
            not_in_scoring += 1
        if code == "MULTIPLE_FOLDING_SCANS":
            if included:
                mf_warning_in_scoring += 1
            elif st == "EXCEPTION":
                mf_exception += 1
        elif "MULTIPLE_FOLDING_SCANS" in secondary:
            mf_secondary_warning += 1
        if code == "MULTIPLE_CLEAN_SCANS":
            if included:
                mc_warning_in_scoring += 1
            elif st == "EXCEPTION":
                mc_exception += 1
        elif "MULTIPLE_CLEAN_SCANS" in secondary:
            mc_secondary_warning += 1

    return {
        "total_bags": total,
        "included_in_scoring": in_scoring,
        "excluded_from_scoring": not_in_scoring,
        "warning_in_scoring": warning_in_scoring,
        "too_short_duration": codes.get("FOLDING_DURATION_TOO_SHORT", 0),
        "too_long_duration": codes.get("FOLDING_DURATION_TOO_LONG", 0),
        "multiple_folding_scans_warning_in_scoring": mf_warning_in_scoring,
        "multiple_folding_scans_exception": mf_exception,
        "multiple_folding_scans_secondary_warning": mf_secondary_warning,
        "multiple_clean_scans_warning_in_scoring": mc_warning_in_scoring,
        "multiple_clean_scans_exception": mc_exception,
        "multiple_clean_scans_secondary_warning": mc_secondary_warning,
        "missing_clean": codes.get("MISSING_CLEAN", 0),
        "missing_folding": codes.get("MISSING_FOLDING", 0),
        "clean_before_folding": codes.get("CLEAN_BEFORE_FOLDING", 0),
        "overlap_invalid_timing": codes.get("OVERLAP_OR_INVALID_TIMING", 0),
        "exception_code_counts": codes,
    }


def stored_rules_impact(
    cursor,
    organization_id: int,
    *,
    period_start=None,
    period_end=None,
    date_field: str = "folding_work_date",
) -> dict[str, Any]:
    """Counts from rinse_folding_performance (current stored data)."""
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    sql = """
        SELECT p.exception_code, p.warning_codes, p.status, p.scoring_status,
               p.included_in_scoring, p.duration_seconds, p.folding_start_at, p.folding_end_at
        FROM rinse_folding_performance p
        INNER JOIN rinse_bag_registry r
          ON r.organization_id = p.organization_id AND r.bag_id = p.bag_id
        WHERE p.organization_id = %s AND r.completion_status = %s
    """
    args: list[Any] = [org, COMPLETION_COMPLETED]
    if period_start and period_end:
        period_sql, period_args = sql_period_filter_sql_and_args(
            date_field, period_start, period_end
        )
        sql += period_sql
        args.extend(period_args)
    cursor.execute(sql, tuple(args))
    rows = list(cursor.fetchall() or [])
    return _impact_from_rows(rows)


def projected_rules_impact(dry_run_report: dict[str, Any]) -> dict[str, Any]:
    """Post-recompute exception code totals from dry-run (proposed counts)."""
    prop = dry_run_report.get("proposed_exception_code_counts") or {}
    warn = dry_run_report.get("proposed_warning_code_counts") or {}
    pc = dry_run_report.get("proposed_changes") or {}
    mf_primary = int(prop.get("MULTIPLE_FOLDING_SCANS", 0))
    mf_secondary = int(warn.get("MULTIPLE_FOLDING_SCANS", 0))
    return {
        "source": "dry_run_projection",
        "total_bags": dry_run_report.get("total_completed_bags_evaluated", 0),
        "would_change_total": pc.get("would_change_total", 0),
        "calculated_to_exception": pc.get("calculated_to_exception", 0),
        "exception_to_calculated": pc.get("exception_to_calculated", 0),
        "too_short_duration": prop.get("FOLDING_DURATION_TOO_SHORT", 0),
        "too_long_duration": prop.get("FOLDING_DURATION_TOO_LONG", 0),
        "multiple_folding_scans_warning_in_scoring": None,
        "multiple_folding_scans_exception": mf_primary,
        "multiple_folding_scans_secondary_warning": mf_secondary,
        "multiple_clean_scans_warning_in_scoring": None,
        "multiple_clean_scans_exception": prop.get("MULTIPLE_CLEAN_SCANS", 0),
        "multiple_clean_scans_secondary_warning": warn.get("MULTIPLE_CLEAN_SCANS", 0),
        "missing_clean": prop.get("MISSING_CLEAN", 0),
        "missing_folding": prop.get("MISSING_FOLDING", 0),
        "clean_before_folding": prop.get("CLEAN_BEFORE_FOLDING", 0),
        "exception_code_counts": prop,
        "note": (
            "Proposed counts are totals after recompute; "
            "warning vs exception split for multi-scan uses current rules."
        ),
    }


def merge_impact_payload(
    cursor,
    organization_id: int,
    rules: dict[str, Any],
    *,
    dry_run_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.rinse_folding_exception_rules import get_folding_rules_meta

    stored = stored_rules_impact(cursor, organization_id)
    meta = get_folding_rules_meta(cursor, organization_id)
    out = {
        "rules_status": rules_status_summary(rules),
        "stored_impact": {**stored, "label": "Current stored data"},
        "recompute_needed": meta.get("recompute_needed"),
        "rules_saved_at": meta.get("rules_saved_at"),
        "last_recompute_at": meta.get("last_recompute_at"),
    }
    if dry_run_report:
        out["projected_impact"] = {
            **projected_rules_impact(dry_run_report),
            "label": "Would change after recompute (dry-run)",
        }
    return out
