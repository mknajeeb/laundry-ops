"""Org-scoped washer/dryer rack capacity settings (system_settings JSON)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.rinse_machine_rack import discover_racks_from_scan_events, parse_rack_capacity_lb
from backend.ta_helpers import table_exists

KEY_MACHINE_RACK_CONFIG = "machine_rack_config"

DEFAULT_WASHER_CAPACITIES: dict[str, float] = {
    "W23-30-VW": 30.0,
    "W24-30-VW": 30.0,
    "W25-30-VW": 30.0,
    "W26-30-VW": 30.0,
    "W27-20-VW": 20.0,
    "W28-20-VW": 20.0,
    "W29-40-VW": 40.0,
    "W30-40-VW": 40.0,
    "W31-40-VW": 40.0,
    "W32-40-VW": 40.0,
    "W39-30-VW": 30.0,
    "W40-40-VW": 40.0,
    "W48-40-VW": 40.0,
    "W50-30-VW": 30.0,
    "W51-20-VW": 20.0,
    "W53-20-VW": 20.0,
    "W54-20-VW": 20.0,
    "W55-20-VW": 20.0,
    "W56-20-VW": 20.0,
    "W57-30-VW": 30.0,
    "W58-30-VW": 30.0,
    "W59-40-VW": 40.0,
    "W60-40-VW": 40.0,
    "W67-20-VW": 20.0,
    "W68-20-VW": 20.0,
    "W69-20-VW": 20.0,
}

DEFAULT_DRYER_CAPACITIES: dict[str, float] = {
    "D1-50-VW": 50.0,
    "D2-50-VW": 50.0,
    "D3-50-VW": 50.0,
    "D37-50-VW": 50.0,
    "D4-50-VW": 50.0,
    "D43-50-VW": 50.0,
    "D44-50-VW": 50.0,
    "D45-50-VW": 50.0,
    "D46-50-VW": 50.0,
    "D47-50-VW": 50.0,
    "D48-50-VW": 50.0,
    "D49-50-VW": 50.0,
    "D5-50-VW": 50.0,
    "D50-50-VW": 50.0,
    "D51-50-VW": 50.0,
    "D52-50-VW": 50.0,
    "D53-50-VW": 50.0,
    "D56-50-VW": 50.0,
    "D57-50-VW": 50.0,
    "D6-50-VW": 50.0,
    "D60-50-VW": 50.0,
    "D62-50-VW": 50.0,
    "D64-50-VW": 50.0,
    "D7-50-VW": 50.0,
    "D8-50-VW": 50.0,
}


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def _parse_positive_float(raw: Any, default: float) -> float:
    if raw is None:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if val <= 0:
        return default
    return val


def _normalize_capacity_map(
    raw: Any,
    defaults: Mapping[str, float],
) -> dict[str, float]:
    out = dict(defaults)
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        code = str(key or "").strip()
        if not code:
            continue
        out[code] = _parse_positive_float(val, out.get(code, defaults.get(code, 1.0)))
    return out


def get_machine_rack_config(cursor, organization_id: int) -> dict[str, dict[str, float]]:
    raw = _get_setting(cursor, int(organization_id), KEY_MACHINE_RACK_CONFIG)
    washers = dict(DEFAULT_WASHER_CAPACITIES)
    dryers = dict(DEFAULT_DRYER_CAPACITIES)
    if not raw:
        return {"washers": washers, "dryers": dryers}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"washers": washers, "dryers": dryers}
    if not isinstance(parsed, dict):
        return {"washers": washers, "dryers": dryers}
    washers = _normalize_capacity_map(parsed.get("washers"), DEFAULT_WASHER_CAPACITIES)
    dryers = _normalize_capacity_map(parsed.get("dryers"), DEFAULT_DRYER_CAPACITIES)
    return {"washers": washers, "dryers": dryers}


def save_machine_rack_config(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    current = get_machine_rack_config(cursor, organization_id)
    washers_in = data.get("washers")
    dryers_in = data.get("dryers")
    if isinstance(washers_in, dict):
        merged = dict(current["washers"])
        for key, val in washers_in.items():
            code = str(key or "").strip()
            if code:
                merged[code] = _parse_positive_float(val, merged.get(code, 1.0))
        current["washers"] = merged
    if isinstance(dryers_in, dict):
        merged = dict(current["dryers"])
        for key, val in dryers_in.items():
            code = str(key or "").strip()
            if code:
                merged[code] = _parse_positive_float(val, merged.get(code, 1.0))
        current["dryers"] = merged
    _set_setting(
        cursor,
        int(organization_id),
        KEY_MACHINE_RACK_CONFIG,
        json.dumps(current),
    )
    return current


def _fallback_capacity(code: str, kind: str) -> float:
    defaults = DEFAULT_WASHER_CAPACITIES if kind == "washers" else DEFAULT_DRYER_CAPACITIES
    parsed = parse_rack_capacity_lb(code)
    if parsed is not None:
        return parsed
    if code in defaults:
        return defaults[code]
    return 30.0 if kind == "washers" else 50.0


def merge_discovered_racks(
    current: Mapping[str, Mapping[str, float]],
    discovered: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """Add newly discovered rack codes without overwriting existing capacities."""
    merged = {
        "washers": dict(current.get("washers") or {}),
        "dryers": dict(current.get("dryers") or {}),
    }
    stats = {"new_washers": 0, "new_dryers": 0, "existing_washers": 0, "existing_dryers": 0}
    for kind in ("washers", "dryers"):
        discovered_map = discovered.get(kind) or {}
        if not isinstance(discovered_map, dict):
            continue
        for code, capacity in discovered_map.items():
            rack_code = str(code or "").strip()
            if not rack_code:
                continue
            if rack_code in merged[kind]:
                stats[f"existing_{kind}"] += 1
                continue
            cap = _parse_positive_float(
                capacity,
                _fallback_capacity(rack_code, kind),
            )
            merged[kind][rack_code] = cap
            stats[f"new_{kind}"] += 1
    return merged, stats


def load_scan_events_for_rack_discovery(cursor, organization_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT rack, last_location, last_scan, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    rows = cursor.fetchall() or []
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def discover_racks_from_scans(cursor, organization_id: int) -> dict[str, dict[str, float]]:
    events = load_scan_events_for_rack_discovery(cursor, organization_id)
    return discover_racks_from_scan_events(events)


def merge_discovered_racks_into_config(
    cursor,
    organization_id: int,
    *,
    commit: bool = True,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    current = get_machine_rack_config(cursor, organization_id)
    discovered = discover_racks_from_scans(cursor, organization_id)
    merged, stats = merge_discovered_racks(current, discovered)
    had_saved = _get_setting(cursor, int(organization_id), KEY_MACHINE_RACK_CONFIG) is not None
    should_save = (
        not had_saved
        or stats["new_washers"] > 0
        or stats["new_dryers"] > 0
    )
    if should_save:
        _set_setting(
            cursor,
            int(organization_id),
            KEY_MACHINE_RACK_CONFIG,
            json.dumps(merged),
        )
        if commit:
            conn = getattr(cursor, "connection", None)
            if conn is not None:
                conn.commit()
    return merged, {
        **stats,
        "saved": should_save,
        "discovered_washers": len(discovered.get("washers") or {}),
        "discovered_dryers": len(discovered.get("dryers") or {}),
        "total_washers": len(merged["washers"]),
        "total_dryers": len(merged["dryers"]),
    }
