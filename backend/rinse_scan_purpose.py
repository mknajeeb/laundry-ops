"""Normalize Rinse scan Purpose values (matches rinse_scan_events_logic)."""

from __future__ import annotations

import re


def normalize_scan_purpose(raw: str | None) -> str:
    s = (raw or "").strip()
    s = re.sub(r"\s+last\s+\w+$", "", s, flags=re.I)
    s = re.sub(r"\s+", "-", s.strip().lower())
    return s


def is_start_cleaning_purpose(raw: str | None) -> bool:
    return "start-cleaning" in normalize_scan_purpose(raw)


def is_weight_entry_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "weight-entry"


def is_split_load_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "split-load"


def is_add_photos_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "add-photos"


def is_create_workitem_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "create-workitem"


def is_create_issue_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "create-issue"


def is_create_workitem_or_issue_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p in ("create-workitem", "create-issue")


def is_drying_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "drying"


def is_cleaning_related_purpose(raw: str | None) -> bool:
    """
    Purpose labels indicating cleaning/prep activity (gaming stages only).

    Purpose-based — do not use rack names. Folding keeps its own rack logic.
    """
    p = normalize_scan_purpose(raw)
    if not p:
        return False
    if p in (
        "weight-entry",
        "drying",
        "split-load",
        "add-photos",
        "create-workitem",
        "create-issue",
    ):
        return False
    return "clean" in p
