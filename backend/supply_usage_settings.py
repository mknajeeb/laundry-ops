"""Org-scoped supply usage dosage and mapping settings (system_settings JSON).

Phase A: Preference mapping stores SUPPLY TYPE (+ legacy supplies projection).
Dosages prefer Supply Product Master average_dose when seeded; system_settings
overrides remain for the standalone Supply Usage page until Phase E.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from backend.supply_product_constants import DEFAULT_TYPE_MAPPING_RULES
from backend.supply_product_mapping import (
    default_mapping_rules,
    mapping_rules_for_display as mapping_rules_for_display_v2,
    normalize_mapping_rule as normalize_mapping_rule_v2,
    project_rules_with_active_products,
)
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

# Backward-compatible export: same brand lists as before, plus supply_types.
DEFAULT_MAPPING_RULES: tuple[dict[str, Any], ...] = tuple(
    dict(r) for r in DEFAULT_TYPE_MAPPING_RULES
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


def _try_master_context(cursor, organization_id: int) -> dict[str, Any] | None:
    """Load product master when tables exist; never break legacy callers/tests."""
    try:
        if not table_exists(cursor, "supply_products"):
            return None
        from backend.supply_product_mapping import load_mapping_context

        return load_mapping_context(cursor, int(organization_id))
    except Exception:
        return None


def _normalize_mapping_rule(
    raw: Mapping[str, Any],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    return normalize_mapping_rule_v2(raw, products_by_type=products_by_type)


def mapping_rules_for_display(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return mapping_rules_for_display_v2(rules)


def get_supply_usage_dosages(cursor, organization_id: int) -> dict[str, float]:
    out = dict(DEFAULT_DOSAGES)
    ctx = _try_master_context(cursor, organization_id)
    if ctx:
        for key, dose in (ctx.get("dosages_from_master") or {}).items():
            if key in out:
                out[key] = float(dose)
    raw = _get_setting(cursor, int(organization_id), KEY_SUPPLY_USAGE_DOSAGES)
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
            out[key] = _parse_positive_float(parsed[key], out.get(key, DEFAULT_DOSAGES[key]))
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
    # Write-through to product master average_dose when products exist (Phase A adapter).
    try:
        if table_exists(cursor, "supply_products"):
            from backend.supply_product_master import list_supply_products, update_supply_product

            for product in list_supply_products(cursor, int(organization_id)):
                legacy = str(product.get("legacy_report_key") or "")
                if legacy in current and legacy in data:
                    update_supply_product(
                        cursor,
                        int(organization_id),
                        int(product["id"]),
                        {"average_dose": current[legacy]},
                    )
    except Exception:
        pass
    return current


def get_supply_usage_mapping_rules(cursor, organization_id: int) -> list[dict[str, Any]]:
    ctx = _try_master_context(cursor, organization_id)
    products_by_type = (ctx or {}).get("products_by_type") or {}

    raw = _get_setting(cursor, int(organization_id), KEY_SUPPLY_USAGE_MAPPING_RULES)
    if not raw:
        rules = default_mapping_rules(products_by_type=products_by_type or None)
    else:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            rules = default_mapping_rules(products_by_type=products_by_type or None)
            parsed = None
        if parsed is not None and not isinstance(parsed, list):
            rules = default_mapping_rules(products_by_type=products_by_type or None)
        elif parsed is not None:
            out: list[dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict):
                    norm = _normalize_mapping_rule(item, products_by_type=products_by_type or None)
                    if norm:
                        out.append(norm)
            rules = out or default_mapping_rules(products_by_type=products_by_type or None)
        else:
            rules = default_mapping_rules(products_by_type=products_by_type or None)

    if products_by_type:
        return project_rules_with_active_products(rules, products_by_type=products_by_type)
    return rules


def save_supply_usage_mapping_rules(
    cursor,
    organization_id: int,
    rules: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ctx = _try_master_context(cursor, organization_id)
    products_by_type = (ctx or {}).get("products_by_type") or {}
    out: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, Mapping):
            continue
        norm = _normalize_mapping_rule(item, products_by_type=products_by_type or None)
        if norm:
            # Persist type-first; keep supplies projection for legacy readers.
            persist = {
                "instructions": norm["instructions"],
                "supply_types": list(norm.get("supply_types") or []),
                "supplies": list(norm.get("supplies") or []),
            }
            for key in ("requires", "excludes", "default"):
                if key in norm:
                    persist[key] = norm[key]
            out.append(persist)
    if not out:
        out = default_mapping_rules(products_by_type=products_by_type or None)
    _set_setting(
        cursor,
        int(organization_id),
        KEY_SUPPLY_USAGE_MAPPING_RULES,
        json.dumps(out),
    )
    if products_by_type:
        return project_rules_with_active_products(out, products_by_type=products_by_type)
    return out
