"""Org-scoped supply usage dosage and mapping settings (system_settings JSON)."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from backend.ta_helpers import table_exists

KEY_SUPPLY_USAGE_DOSAGES = "supply_usage_dosages"
KEY_SUPPLY_USAGE_MAPPING_RULES = "supply_usage_mapping_rules"

DEFAULT_DOSAGES: dict[str, float] = {
    "Tide": 2.0,
    "Downy": 1.0,
    "OxiClean": 1.0,
    "All Free & Clear": 2.0,
}

SUPPLY_DOSAGE_KEYS = tuple(DEFAULT_DOSAGES.keys())

_TOKEN_FAB = "USE FABRIC SOFTENER"
_TOKEN_OXIC = "USE OXICLEAN"
_TOKEN_HYPO = "USE HYPOALLERGENIC SOAP"

DEFAULT_MAPPING_RULES: tuple[dict[str, Any], ...] = (
    {
        "instructions": "Hypo + Fabric Softener + OxiClean",
        "supplies": ["All Free & Clear", "Downy", "OxiClean"],
        "requires": [_TOKEN_HYPO, _TOKEN_FAB, _TOKEN_OXIC],
    },
    {
        "instructions": "Hypo + OxiClean",
        "supplies": ["All Free & Clear", "OxiClean"],
        "requires": [_TOKEN_HYPO, _TOKEN_OXIC],
        "excludes": [_TOKEN_FAB],
    },
    {
        "instructions": "Hypoallergenic (variations)",
        "supplies": ["All Free & Clear"],
        "requires": [_TOKEN_HYPO],
        "excludes": [_TOKEN_OXIC],
    },
    {
        "instructions": "Fabric Softener + OxiClean",
        "supplies": ["Tide", "Downy", "OxiClean"],
        "requires": [_TOKEN_FAB, _TOKEN_OXIC],
        "excludes": [_TOKEN_HYPO],
    },
    {
        "instructions": "Fabric Softener",
        "supplies": ["Tide", "Downy"],
        "requires": [_TOKEN_FAB],
        "excludes": [_TOKEN_HYPO, _TOKEN_OXIC],
    },
    {
        "instructions": "OxiClean only",
        "supplies": ["Tide", "OxiClean"],
        "requires": [_TOKEN_OXIC],
        "excludes": [_TOKEN_HYPO, _TOKEN_FAB],
    },
    {
        "instructions": "None / default",
        "supplies": ["Tide"],
        "default": True,
    },
)


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


def _normalize_supplies(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace("+", ",").split(",")]
        items = [p for p in parts if p]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = []
    out: list[str] = []
    for item in items:
        if item in SUPPLY_DOSAGE_KEYS and item not in out:
            out.append(item)
    return out


def _default_rule_by_instructions() -> dict[str, dict[str, Any]]:
    return {str(r["instructions"]): dict(r) for r in DEFAULT_MAPPING_RULES}


def _normalize_mapping_rule(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    instructions = str(raw.get("instructions") or "").strip()
    supplies = _normalize_supplies(raw.get("supplies"))
    if not instructions and not raw.get("default"):
        return None
    out: dict[str, Any] = {"instructions": instructions, "supplies": supplies}
    default_lookup = _default_rule_by_instructions()
    merged = default_lookup.get(instructions)
    if merged:
        for key in ("requires", "excludes", "default"):
            if key in raw:
                out[key] = raw[key]
            elif key in merged and key not in out:
                out[key] = merged[key]
    else:
        for key in ("requires", "excludes", "default"):
            if key in raw:
                out[key] = raw[key]
    if not supplies and not out.get("default"):
        return None
    return out


def mapping_rules_for_display(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in rules:
        supplies = _normalize_supplies(rule.get("supplies"))
        item: dict[str, Any] = {
            "instructions": str(rule.get("instructions") or "").strip(),
            "supplies": supplies,
            "supplies_display": " + ".join(supplies),
        }
        if rule.get("default"):
            item["default"] = True
        out.append(item)
    return out


def get_supply_usage_dosages(cursor, organization_id: int) -> dict[str, float]:
    raw = _get_setting(cursor, int(organization_id), KEY_SUPPLY_USAGE_DOSAGES)
    out = dict(DEFAULT_DOSAGES)
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, dict):
        return out
    for key in DEFAULT_DOSAGES:
        if key in parsed:
            out[key] = _parse_positive_float(parsed[key], DEFAULT_DOSAGES[key])
    return out


def save_supply_usage_dosages(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, float]:
    current = get_supply_usage_dosages(cursor, organization_id)
    for key in DEFAULT_DOSAGES:
        if key in data:
            current[key] = _parse_positive_float(data[key], current[key])
    _set_setting(
        cursor,
        int(organization_id),
        KEY_SUPPLY_USAGE_DOSAGES,
        json.dumps(current),
    )
    return current


def get_supply_usage_mapping_rules(cursor, organization_id: int) -> list[dict[str, Any]]:
    raw = _get_setting(cursor, int(organization_id), KEY_SUPPLY_USAGE_MAPPING_RULES)
    if not raw:
        return [dict(r) for r in DEFAULT_MAPPING_RULES]
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [dict(r) for r in DEFAULT_MAPPING_RULES]
    if not isinstance(parsed, list):
        return [dict(r) for r in DEFAULT_MAPPING_RULES]
    out: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            norm = _normalize_mapping_rule(item)
            if norm:
                out.append(norm)
    return out or [dict(r) for r in DEFAULT_MAPPING_RULES]


def save_supply_usage_mapping_rules(
    cursor,
    organization_id: int,
    rules: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, Mapping):
            continue
        norm = _normalize_mapping_rule(item)
        if norm:
            out.append(norm)
    if not out:
        out = [dict(r) for r in DEFAULT_MAPPING_RULES]
    _set_setting(
        cursor,
        int(organization_id),
        KEY_SUPPLY_USAGE_MAPPING_RULES,
        json.dumps(out),
    )
    return out
