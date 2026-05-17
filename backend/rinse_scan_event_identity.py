"""
Stable identity for rinse_bag_scan_events rows (idempotent merge / dedupe).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any


def _norm_str(val: Any, *, max_len: int) -> str:
    return str(val or "").strip()[:max_len]


def _norm_scanned_at(val: Any) -> str:
    if val is None or str(val) in ("", "NaT", "None"):
        return ""
    if isinstance(val, datetime):
        if val == datetime.min:
            return ""
        return val.strftime("%Y-%m-%d %H:%M:%S")
    try:
        import pandas as pd

        p = pd.Timestamp(val)
        if pd.isna(p):
            return ""
        return p.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val).strip()[:32]


def compute_scan_event_dedupe_key(
    *,
    scan_index: int | None,
    rack: str | None,
    user_name: str | None,
    purpose: str | None,
    scanned_at_parsed: Any,
) -> str:
    """
    Hash of scan identity fields (per org+bag uniqueness in DB).

    Matches: scan_index, rack, user_name, purpose, scanned_at_parsed (second precision).
    """
    idx_part = "" if scan_index is None else str(int(scan_index))
    payload = "\x1f".join(
        [
            idx_part,
            _norm_str(rack, max_len=128),
            _norm_str(user_name, max_len=255),
            _norm_str(purpose, max_len=255),
            _norm_scanned_at(scanned_at_parsed),
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
    return compute_scan_event_dedupe_key(
        scan_index=scan_index,
        rack=row.get("rack"),
        user_name=row.get("user_name"),
        purpose=row.get("purpose"),
        scanned_at_parsed=row.get("scanned_at_parsed"),
    )
