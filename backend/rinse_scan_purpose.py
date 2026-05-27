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
