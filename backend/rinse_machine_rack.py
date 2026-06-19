"""Washer/dryer rack detection from rinse_bag_scan_events fields."""

from __future__ import annotations

import json
from typing import Any, Mapping


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
