"""
Rinse scan timestamp parsing and storage convention.

All Rinse portal / scan-events CSV timestamps are America/New_York (Eastern) wall time.

Storage convention (current schema):
- scanned_at_parsed: naive DATETIME interpreted as America/New_York local wall time
- time_scanned_raw: exact string from Rinse UI / scraper (immutable after insert)
- source_timezone: always 'America/New_York' for new rows

Do not treat Rinse times as UTC. Do not apply server local timezone when parsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

RINSE_SCAN_SOURCE_TIMEZONE = "America/New_York"

_PARSE_FORMATS = (
    "%A, %B %d, %Y %I:%M %p",
    "%A, %B %d, %Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %I:%M %p",
)


def normalize_rack_value(rack: Any) -> str | None:
    """Normalize rack for storage/dedupe; empty / (None) -> None."""
    s = str(rack or "").strip()
    if not s:
        return None
    if s.lower() in ("none", "(none)", "null", "n/a", "na"):
        return None
    return s[:128]


def normalize_time_scanned_raw(text: Any) -> str:
    """Canonical raw time string for dedupe (trimmed, single-spaced)."""
    return " ".join(str(text or "").split())


def parse_rinse_scanned_at(text: str) -> datetime | None:
    """
    Parse Rinse 'Time Scanned' text to naive Eastern local wall datetime.

    Example: 'Sunday, May 17, 2026 3:17 PM' -> datetime(2026, 5, 17, 15, 17, 0)
    """
    s = normalize_time_scanned_raw(text)
    if not s:
        return None
    for fmt in _PARSE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(s, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return ts.to_pydatetime().replace(tzinfo=None)
    except Exception:
        pass
    return None


def parse_rinse_scanned_at_pandas(text: str) -> pd.Timestamp | pd.NaT:
    """Pandas Timestamp for upload CSV pipelines (naive ET wall)."""
    dt = parse_rinse_scanned_at(text)
    if dt is None:
        return pd.NaT
    return pd.Timestamp(dt)


def format_scanned_at_et_for_dedupe(val: Any) -> str:
    """Second-precision ET wall string for dedupe key (empty if unparseable)."""
    if val is None or str(val) in ("", "NaT", "None"):
        return ""
    if isinstance(val, datetime):
        if val == datetime.min:
            return ""
        return val.strftime("%Y-%m-%d %H:%M:%S")
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return ""
        return ts.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val).strip()[:32]
