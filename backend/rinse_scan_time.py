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

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

RINSE_SCAN_SOURCE_TIMEZONE = "America/New_York"
SYSTEM_DB_TIMEZONE = "UTC"
_ET = ZoneInfo(RINSE_SCAN_SOURCE_TIMEZONE)
_UTC = ZoneInfo(SYSTEM_DB_TIMEZONE)

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


def serialize_rinse_scan_datetime_for_api(dt: datetime | None) -> str | None:
    """
    Rinse portal / scan-event wall times (scanned_at_parsed, folding from scans).

    Naive DB values are America/New_York local wall time — not UTC.
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise TypeError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        localized = dt.replace(tzinfo=_ET)
    else:
        localized = dt.astimezone(_ET)
    return localized.isoformat(timespec="seconds")


def serialize_rinse_datetime_for_api(dt: datetime | None) -> str | None:
    """Alias for scan wall-time serialization (backward compatible)."""
    return serialize_rinse_scan_datetime_for_api(dt)


def serialize_system_datetime_for_api(dt: datetime | None) -> str | None:
    """
    System/job DB timestamps (rinse_scrape_runs, upload_batches, audit).

    Naive values are stored as UTC (MySQL/server). Convert to Eastern for API ISO
    with offset, e.g. UTC 2026-05-24 23:37:00 -> 2026-05-24T19:37:00-04:00.
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise TypeError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=_UTC)
    else:
        utc_dt = dt.astimezone(_UTC)
    return utc_dt.astimezone(_ET).isoformat(timespec="seconds")


def system_datetime_to_et(dt: datetime | None) -> datetime | None:
    """Interpret naive system DB time as UTC; return aware America/New_York."""
    if dt is None or not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC).astimezone(_ET)
    return dt.astimezone(_ET)


def naive_system_utc(dt: datetime | None) -> datetime | None:
    """Normalize system/job DB datetimes to naive UTC for safe age arithmetic."""
    if dt is None or not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_UTC).replace(tzinfo=None)


def json_safe_rinse(obj: Any) -> Any:
    """Recursively serialize Rinse scan/bag payloads (scan wall-time datetimes)."""
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return serialize_rinse_scan_datetime_for_api(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: json_safe_rinse(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe_rinse(x) for x in obj]
    return obj


def json_safe_system(obj: Any) -> Any:
    """Recursively serialize job/system payloads (UTC naive datetimes → ET ISO)."""
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return serialize_system_datetime_for_api(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: json_safe_system(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe_system(x) for x in obj]
    return obj


def rinse_api_json_dumps(obj: Any) -> str:
    """Test helper: JSON text for Rinse responses without Flask GMT encoding."""
    return json.dumps(json_safe_rinse(obj), ensure_ascii=False)


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
