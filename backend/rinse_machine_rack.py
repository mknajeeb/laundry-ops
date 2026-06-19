"""Washer/dryer rack detection from rinse_bag_scan_events fields."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

# Rack codes like W24-30-VW or D4-50-VW encode capacity (lb) in the middle segment.
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


def extract_washer_rack(ev: Mapping[str, Any]) -> str | None:
    for candidate in rack_candidate_strings(ev):
        if is_washer_rack_code(candidate):
            return normalize_rack_code(candidate)
    return None


def extract_dryer_rack(ev: Mapping[str, Any]) -> str | None:
    for candidate in rack_candidate_strings(ev):
        if is_dryer_rack_code(candidate):
            return normalize_rack_code(candidate)
    return None


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


def _record_discovered_rack(dest: dict[str, float | None], code: str) -> None:
    capacity = parse_rack_capacity_lb(code)
    if code not in dest:
        dest[code] = capacity
    elif dest[code] is None and capacity is not None:
        dest[code] = capacity


def discover_racks_from_scan_events(
    events: list[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    """Collect unique washer/dryer rack codes and inferred capacities from scan rows."""
    washers: dict[str, float | None] = {}
    dryers: dict[str, float | None] = {}
    for ev in events:
        for candidate in rack_candidate_strings(ev):
            code = normalize_rack_code(candidate)
            if not code:
                continue
            if is_washer_rack_code(code):
                _record_discovered_rack(washers, code)
            elif is_dryer_rack_code(code):
                _record_discovered_rack(dryers, code)
    return {
        "washers": {k: v for k, v in washers.items() if v is not None and v > 0},
        "dryers": {k: v for k, v in dryers.items() if v is not None and v > 0},
    }
