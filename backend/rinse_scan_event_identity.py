"""
Stable identity for rinse_bag_scan_events rows (idempotent merge / dedupe).

Dedupe key must include the true scan time (raw + parsed ET) so May 15 and May 17
never collapse. NULL/blank parsed time alone must not merge unrelated rows.

scan_index is stored on the row but is NOT part of dedupe identity — Rinse re-exports
re-number indices for the same logical scan.
"""

from __future__ import annotations

import hashlib
from typing import Any

from backend.rinse_scan_purpose import normalize_scan_purpose
from backend.rinse_scan_time import (
    format_scanned_at_et_for_dedupe,
    normalize_rack_value,
    normalize_time_scanned_raw,
)


def _norm_str(val: Any, *, max_len: int) -> str:
    return str(val or "").strip()[:max_len]


def _purpose_part(purpose: str | None) -> str:
    return _norm_str(normalize_scan_purpose(purpose), max_len=255)


def compute_scan_event_dedupe_key(
    *,
    organization_id: int | None = None,
    bag_id: str | None = None,
    scan_index: int | None = None,
    rack: str | None,
    user_name: str | None,
    purpose: str | None,
    time_scanned_raw: str | None,
    scanned_at_parsed: Any,
    last_location: str | None = None,
) -> str:
    """
    Hash of scan identity fields (unique per org+bag in DB).

    Includes both time_scanned_raw and scanned_at_parsed (ET), normalized purpose
    (Last Scan suffix stripped), rack, and user. Re-upload of the same logical scan
    yields the same key even when scan_index changes between portal exports.
    """
    del scan_index  # metadata only; excluded from identity
    raw_part = normalize_time_scanned_raw(time_scanned_raw)
    parsed_part = format_scanned_at_et_for_dedupe(scanned_at_parsed)
    rack_norm = _norm_str(normalize_rack_value(rack) or "", max_len=128)

    if not raw_part and not parsed_part:
        raise ValueError(
            "Scan event dedupe_key requires Time Scanned raw text or a parseable timestamp"
        )

    org_part = str(int(organization_id)) if organization_id is not None else ""
    bag_part = _norm_str(bag_id, max_len=64)
    payload = "\x1f".join(
        [
            org_part,
            bag_part,
            rack_norm,
            _norm_str(user_name, max_len=255),
            _purpose_part(purpose),
            _norm_str(last_location, max_len=8),
            raw_part,
            parsed_part,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def dedupe_key_from_row(row: dict[str, Any]) -> str:
    raw = row.get("time_scanned_raw")
    if raw is None and "Time Scanned" in row:
        raw = row.get("Time Scanned")
    return compute_scan_event_dedupe_key(
        organization_id=row.get("organization_id"),
        bag_id=row.get("bag_id"),
        rack=row.get("rack"),
        user_name=row.get("user_name"),
        purpose=row.get("purpose"),
        time_scanned_raw=raw,
        scanned_at_parsed=row.get("scanned_at_parsed"),
        last_location=row.get("last_location"),
    )
