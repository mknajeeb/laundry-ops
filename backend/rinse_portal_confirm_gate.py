"""Gate ACA portal auto-confirm on credible supply signal in scrape CSV."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from backend.rinse_special_instructions import (
    _classify_part,
    _is_portal_vendor_catalog_part,
    _raw_has_vendor_catalog_pollution,
    _split_instruction_parts,
    extract_labeled_special_instructions,
)

FLAG_COLS = ("USE OXIC", "Use Hypo", "USE FAB")

GATE_FAILURE_REASON = "Portal scrape not confirmed: no credible supply flags/SI captured."
GATE_FAILURE_WARNING = GATE_FAILURE_REASON

_FORCE_MARKS = frozenset({"X", "YES", "Y", "TRUE", "1", "✓"})


def flag_marked(val: str | None) -> bool:
    return str(val or "").strip().upper() in _FORCE_MARKS


def si_catalog_polluted(text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if _is_portal_vendor_catalog_part(s):
        return True
    return _raw_has_vendor_catalog_pollution(s)


def si_has_credible_supply_token(text: str | None) -> bool:
    """True when SI is clean (not catalog noise) and contains mapped supply tokens."""
    s = str(text or "").strip()
    if not s or si_catalog_polluted(s):
        return False
    labeled = extract_labeled_special_instructions(s)
    probe = labeled if labeled else s
    if not probe or si_catalog_polluted(probe):
        return False
    for part in _split_instruction_parts(probe):
        if si_catalog_polluted(part):
            continue
        kind = _classify_part(part)
        if kind and kind != "UNKNOWN":
            return True
    return bool(re.search(r"\buse\s+(oxic(?:lean)?|fabric\s+softener|hypoallergenic)\b", probe, re.I))


def read_portal_csv_rows(portal_csv_path: Path | str) -> list[dict[str, str]]:
    with Path(portal_csv_path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def assess_portal_csv_row(row: dict[str, Any]) -> dict[str, bool]:
    si = str(row.get("Special Instructions") or "").strip()
    flags = {c: str(row.get(c) or "").strip() for c in FLAG_COLS}
    has_flags = any(flag_marked(flags[c]) for c in FLAG_COLS)
    polluted = si_catalog_polluted(si)
    clean_supply_si = si_has_credible_supply_token(si)
    credible_flags = has_flags and not polluted
    template_flags = has_flags and polluted
    return {
        "has_flags": has_flags,
        "catalog_polluted": polluted,
        "clean_supply_si": clean_supply_si,
        "credible_flags": credible_flags,
        "template_like_flags": template_flags,
    }


def build_portal_confirm_gate_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    rows_with_flags = 0
    rows_with_clean_si = 0
    rows_with_catalog_pollution = 0
    rows_with_template_like_flags = 0
    rows_with_credible_flags = 0

    for row in rows:
        assessed = assess_portal_csv_row(row)
        if assessed["has_flags"]:
            rows_with_flags += 1
        if assessed["clean_supply_si"]:
            rows_with_clean_si += 1
        if assessed["catalog_polluted"]:
            rows_with_catalog_pollution += 1
        if assessed["template_like_flags"]:
            rows_with_template_like_flags += 1
        if assessed["credible_flags"]:
            rows_with_credible_flags += 1

    return {
        "total_rows": total,
        "rows_with_flags": rows_with_flags,
        "rows_with_clean_si": rows_with_clean_si,
        "rows_with_catalog_pollution": rows_with_catalog_pollution,
        "rows_with_template_like_flags": rows_with_template_like_flags,
        "rows_with_credible_flags": rows_with_credible_flags,
    }


def evaluate_portal_confirm_gate(
    portal_csv_path: Path | str,
    *,
    force_confirm: bool = False,
) -> dict[str, Any]:
    """
    Decide whether ACA should create/confirm a portal batch from scrape CSV.

    Confirm when clean SI supply tokens exist, or flag columns are credible
    (not paired with catalog-polluted SI). Manual force bypasses the gate.
    """
    rows = read_portal_csv_rows(portal_csv_path)
    report = build_portal_confirm_gate_report(rows)

    if force_confirm:
        return {
            **report,
            "confirm_decision": "confirm",
            "reason": "manual_force_override",
            "should_create_batch": True,
            "should_auto_confirm": True,
            "force_override": True,
            "warning": "Portal confirm gate bypassed via manual force override.",
        }

    if report["rows_with_clean_si"] >= 1:
        return {
            **report,
            "confirm_decision": "confirm",
            "reason": "clean_si_supply_tokens",
            "should_create_batch": True,
            "should_auto_confirm": True,
            "force_override": False,
        }

    if report["rows_with_credible_flags"] >= 1:
        return {
            **report,
            "confirm_decision": "confirm",
            "reason": "credible_detail_pane_flags",
            "should_create_batch": True,
            "should_auto_confirm": True,
            "force_override": False,
        }

    return {
        **report,
        "confirm_decision": "inspect_only",
        "reason": GATE_FAILURE_REASON,
        "should_create_batch": False,
        "should_auto_confirm": False,
        "force_override": False,
        "warning": GATE_FAILURE_WARNING,
    }
