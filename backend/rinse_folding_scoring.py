"""Scoring inclusion helpers for folding performance (Phase 3)."""

from __future__ import annotations

from typing import Any

from backend.rinse_bag_folding import STATUS_CALCULATED, STATUS_EXCEPTION

SCORING_CALCULATED = "CALCULATED"
SCORING_EXCEPTION = "EXCEPTION"
SCORING_APPROVED = "APPROVED"
SCORING_EXCLUDED = "EXCLUDED"
SCORING_INCLUDED_OVERRIDE = "INCLUDED_OVERRIDE"

SCORING_OVERRIDE_INCLUDE = "INCLUDE"
SCORING_OVERRIDE_EXCLUDE = "EXCLUDE"


def sql_scoring_included_predicate(alias: str = "p") -> str:
    """SQL fragment: row counts in leaderboard/TV team scoring."""
    a = alias
    return (
        f"(COALESCE({a}.included_in_scoring, 0) = 1 OR ("
        f"{a}.status = 'CALCULATED' AND COALESCE({a}.excluded_from_performance, 0) = 0 "
        f"AND COALESCE({a}.scoring_status, {a}.status) IN ('CALCULATED', 'APPROVED', '{SCORING_INCLUDED_OVERRIDE}')))"
    )


def scoring_fields_from_override(existing: dict[str, Any]) -> dict[str, Any] | None:
    ov = str(existing.get("scoring_override") or "").strip().upper()
    if ov == SCORING_OVERRIDE_INCLUDE:
        return {
            "scoring_status": SCORING_INCLUDED_OVERRIDE,
            "included_in_scoring": 1,
        }
    if ov == SCORING_OVERRIDE_EXCLUDE:
        return {
            "scoring_status": SCORING_EXCLUDED,
            "included_in_scoring": 0,
        }
    return None


def scoring_fields_from_compute(
    *,
    status: str,
    exception_code: str | None,
    existing: dict[str, Any] | None,
    preserve_review: bool = True,
) -> dict[str, Any]:
    """
    Derive scoring_status / included_in_scoring after recompute.
    Preserves admin APPROVED, manual EXCLUDED, and record scoring_override when preserve_review=True.
    """
    ex = existing or {}
    if preserve_review:
        override_fields = scoring_fields_from_override(ex)
        if override_fields:
            return override_fields
        if int(ex.get("excluded_from_performance") or 0):
            return {
                "scoring_status": SCORING_EXCLUDED,
                "included_in_scoring": 0,
            }
        if str(ex.get("scoring_status") or "").upper() == SCORING_APPROVED:
            return {
                "scoring_status": SCORING_APPROVED,
                "included_in_scoring": 1,
            }
    st = str(status or "").upper()
    if st == STATUS_CALCULATED:
        return {
            "scoring_status": SCORING_CALCULATED,
            "included_in_scoring": 1,
        }
    return {
        "scoring_status": SCORING_EXCEPTION,
        "included_in_scoring": 0,
    }


def row_included_in_scoring(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if int(row.get("included_in_scoring") or 0):
        return True
    if int(row.get("excluded_from_performance") or 0):
        return False
    scoring = str(row.get("scoring_status") or row.get("status") or "").upper()
    if scoring in (SCORING_APPROVED, SCORING_INCLUDED_OVERRIDE):
        return True
    return str(row.get("status") or "").upper() == STATUS_CALCULATED and scoring in (
        SCORING_CALCULATED,
        "",
    )


def scoring_override_label(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    ov = str(row.get("scoring_override") or "").strip().upper()
    if ov == SCORING_OVERRIDE_INCLUDE:
        return "Included by admin override"
    if ov == SCORING_OVERRIDE_EXCLUDE:
        return "Excluded by admin override"
    return None
