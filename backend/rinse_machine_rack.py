"""Washer/dryer rack detection from rinse_bag_scan_events fields."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

# Rack codes like W24-30-VW: first segment is machine id, middle may encode lb capacity.
# Auto-discovery does not infer capacity from codes; use org defaults or manual entry.
_RACK_CAPACITY_RE = re.compile(r"^[WD]\d+-(\d+)-", re.IGNORECASE)


def normalize_rack_code(text: str | None) -> str | None:
    s = str(text or "").strip()
    return s or None


def is_washer_rack_code(text: str | None) -> bool:
    """Washer rack codes start with W (e.g. W24-30-VW, W29-40-VW)."""
    s = normalize_rack_code(text)
    if not s:
        return False
    return s[0].upper() == "W"


def is_dryer_rack_code(text: str | None) -> bool:
    """Dryer rack codes start with D (e.g. D4-50-VW, D8-35-VW)."""
    s = normalize_rack_code(text)
    if not s:
        return False
    return s[0].upper() == "D"


def _strings_from_raw_json(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return [raw.strip()] if raw.strip() else []
        raw = parsed
    if not isinstance(raw, dict):
        return []
    out: list[str] = []
    for key in ("Rack", "rack", "Machine", "machine", "Location", "location", "Last Location"):
        val = raw.get(key)
        if val:
            out.append(str(val).strip())
    return out


def rack_candidate_strings(ev: Mapping[str, Any]) -> list[str]:
    """Collect rack/machine/location strings from a scan event row."""
    out: list[str] = []
    for key in ("rack", "last_location", "last_scan"):
        val = ev.get(key)
        if val:
            out.append(str(val).strip())
    out.extend(_strings_from_raw_json(ev.get("raw_json")))
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if not s or s in seen:
            continue
        seen.add(s)
        deduped.append(s)
    return deduped


def _extract_rack_preferring_rack_field(
    ev: Mapping[str, Any],
    *,
    is_rack_code,
) -> str | None:
    """Prefer the explicit rack column; fall back to other location fields."""
    rack_field = normalize_rack_code(ev.get("rack"))
    if rack_field and is_rack_code(rack_field):
        return rack_field
    for candidate in rack_candidate_strings(ev):
        if candidate == rack_field:
            continue
        if is_rack_code(candidate):
            return normalize_rack_code(candidate)
    return None


def extract_washer_rack(ev: Mapping[str, Any]) -> str | None:
    return _extract_rack_preferring_rack_field(ev, is_rack_code=is_washer_rack_code)


def extract_dryer_rack(ev: Mapping[str, Any]) -> str | None:
    return _extract_rack_preferring_rack_field(ev, is_rack_code=is_dryer_rack_code)


def _event_id_int(ev: Mapping[str, Any]) -> int | None:
    eid = ev.get("id")
    if eid is None:
        return None
    try:
        return int(eid)
    except (TypeError, ValueError):
        return None


def dedupe_scan_events_by_id(
    events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    """Drop duplicate DB/join rows that share the same scan event id."""
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        eid = _event_id_int(ev)
        if eid is not None:
            if eid in seen:
                continue
            seen.add(eid)
        out.append(dict(ev))
    return out


def dedupe_machine_load_rows(
    rows: list[dict[str, Any]],
    *,
    rack_field: str,
) -> list[dict[str, Any]]:
    """
    One chronology/utilization row per scan event and per logical machine load.

    Collapses duplicate ingest rows that share bag, employee, timestamp, and rack.
    """
    seen_ids: set[int] = set()
    seen_logical: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        eid = row.get("scan_event_id")
        if eid is not None:
            try:
                eid_int = int(eid)
            except (TypeError, ValueError):
                eid_int = None
            if eid_int is not None:
                if eid_int in seen_ids:
                    continue
                seen_ids.add(eid_int)
        logical = (
            str(row.get("bag_id") or "").strip(),
            str(row.get("employee") or "").strip(),
            row.get("timestamp_et"),
            str(row.get(rack_field) or "").strip(),
        )
        if logical in seen_logical:
            continue
        seen_logical.add(logical)
        out.append(row)
    return out


def parse_rack_capacity_lb(code: str | None) -> float | None:
    """Extract lb capacity from rack code middle segment (e.g. W24-30-VW -> 30)."""
    s = normalize_rack_code(code)
    if not s:
        return None
    match = _RACK_CAPACITY_RE.match(s)
    if not match:
        return None
    try:
        val = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def discover_racks_from_scan_events(
    events: list[Mapping[str, Any]],
) -> dict[str, dict[str, float | None]]:
    """Collect unique washer/dryer rack codes from scan rows (capacity not inferred)."""
    washers: dict[str, None] = {}
    dryers: dict[str, None] = {}
    for ev in events:
        for candidate in rack_candidate_strings(ev):
            code = normalize_rack_code(candidate)
            if not code:
                continue
            if is_washer_rack_code(code):
                washers.setdefault(code, None)
            elif is_dryer_rack_code(code):
                dryers.setdefault(code, None)
    return {"washers": washers, "dryers": dryers}
