"""
Stable identity for rinse_bag_scan_events rows (idempotent merge / dedupe).

Dedupe key must include the true scan time (raw + parsed ET) so May 15 and May 17
never collapse. NULL/blank parsed time alone must not merge unrelated rows.
"""

from __future__ import annotations

import hashlib
from typing import Any

from backend.rinse_scan_time import (
    format_scanned_at_et_for_dedupe,
    normalize_rack_value,
    normalize_time_scanned_raw,
)


def _norm_str(val: Any, *, max_len: int) -> str:
    return str(val or "").strip()[:max_len]


def _scan_index_part(scan_index: int | None) -> str:
    if scan_index is None:
        return ""
    return str(int(scan_index))


def compute_scan_event_dedupe_key(
    *,
    organization_id: int | None = None,
    bag_id: str | None = None,
    scan_index: int | None,
    rack: str | None,
    user_name: str | None,
    purpose: str | None,
    time_scanned_raw: str | None,
    scanned_at_parsed: Any,
) -> str:
    """
    Hash of scan identity fields (unique per org+bag in DB).

    Includes both time_scanned_raw and scanned_at_parsed (ET) so distinct calendar
    times never share a key. Re-upload of the exact same logical scan yields the
    same key (metadata-only touch).
    """
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
            _scan_index_part(scan_index),
            rack_norm,
            _norm_str(user_name, max_len=255),
            _norm_str(purpose, max_len=255),
            raw_part,
            parsed_part,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def dedupe_key_from_row(row: dict[str, Any]) -> str:
    scan_index = row.get("scan_index")
    if scan_index is not None and scan_index != "":
        try:
            scan_index = int(float(str(scan_index).strip()))
        except (TypeError, ValueError):
            scan_index = None
    raw = row.get("time_scanned_raw")
    if raw is None and "Time Scanned" in row:
        raw = row.get("Time Scanned")
    return compute_scan_event_dedupe_key(
        organization_id=row.get("organization_id"),
        bag_id=row.get("bag_id"),
        scan_index=scan_index,
        rack=row.get("rack"),
        user_name=row.get("user_name"),
        purpose=row.get("purpose"),
        time_scanned_raw=raw,
        scanned_at_parsed=row.get("scanned_at_parsed"),
    )
