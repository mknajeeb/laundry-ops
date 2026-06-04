"""
America/New_York business calendar and display for Washpro / VeeWash Laundry Ops.

Use these helpers for portal date parsing, batch defaults, and user-facing timestamps.
Do not use date.today(), datetime.now(), or datetime.utcnow() for business-facing logic
without converting through eastern_today() / eastern_now().
"""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_folding_et import ET, eastern_now, eastern_today
from backend.rinse_scan_time import (
    RINSE_SCAN_SOURCE_TIMEZONE,
    serialize_rinse_scan_datetime_for_api,
    serialize_system_datetime_for_api,
    system_datetime_to_et,
)

__all__ = [
    "ET",
    "RINSE_SCAN_SOURCE_TIMEZONE",
    "business_now",
    "business_today",
    "format_business_datetime_display",
    "serialize_rinse_scan_datetime_for_api",
    "serialize_system_datetime_for_api",
    "system_datetime_to_et",
]

# Aliases for Laundry Ops business calendar (America/New_York).
business_today = eastern_today
business_now = eastern_now


def format_business_datetime_display(
    dt: datetime | None,
    *,
    source: str = "system",
) -> str | None:
    """
    User-facing Eastern label, e.g. 'Jun 4, 2:15 PM EDT'.

    source:
      - 'system': naive UTC DB timestamp (upload_batches, scrape runs, checkout log)
      - 'scan': naive Rinse portal wall time (scanned_at_parsed)
    """
    if dt is None:
        return None
    if source == "scan":
        iso = serialize_rinse_scan_datetime_for_api(dt)
    else:
        iso = serialize_system_datetime_for_api(dt)
    if not iso:
        return None
    aware = datetime.fromisoformat(iso)
    tz_label = aware.strftime("%Z")
    if tz_label in ("EDT", "EST"):
        suffix = tz_label
    else:
        suffix = "ET"
    hour12 = aware.hour % 12 or 12
    return f"{aware.strftime('%b')} {aware.day}, {hour12}:{aware.strftime('%M %p')} {suffix}"
