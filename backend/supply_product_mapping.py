"""Preference → Supply Type / Active Product mapping adapter (Phase A).

Preserves existing Supply Usage brand-string resolution while migrating rules
toward SUPPLY TYPE + ACTIVE PRODUCT. Phase B can switch report keys cleanly
by reading product ids from resolved mapping without changing membership.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.supply_product_constants import (
    DEFAULT_TYPE_MAPPING_RULES,
    LEGACY_KEY_TO_SUPPLY_TYPE,
    LEGACY_REPORT_KEYS,
    SUPPLY_TYPE_TO_LEGACY_KEY,
    SUPPLY_TYPES,
)
from backend.supply_product_master import (
    active_products_by_supply_type,
    dosages_from_products,
    ensure_supply_product_tables,
    list_supply_products,
    seed_default_supply_products,
)


def _normalize_supply_types(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.replace("+", ",").split(",")]
        items = [p for p in parts if p]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip().upper() for s in raw if str(s).strip()]
    else:
        items = []
    out: list[str] = []
    for item in items:
        if item in SUPPLY_TYPES and item not in out:
            out.append(item)
    return out


def _normalize_legacy_supplies(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace("+", ",").split(",")]
        items = [p for p in parts if p]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = []
    out: list[str] = []
    for item in items:
        if item in LEGACY_REPORT_KEYS and item not in out:
            out.append(item)
    return out


def supply_types_from_legacy_supplies(supplies: Sequence[str]) -> list[str]:
    out: list[str] = []
    for key in supplies:
        st = LEGACY_KEY_TO_SUPPLY_TYPE.get(key)
        if st and st not in out:
            out.append(st)
    return out


def legacy_supplies_from_types(
    supply_types: Sequence[str],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Resolve types → active product legacy_report_key (fallback catalog map)."""
    out: list[str] = []
    for st in supply_types:
        key = None
        if products_by_type and st in products_by_type:
            key = str(products_by_type[st].get("legacy_report_key") or "").strip() or None
        if not key:
            key = SUPPLY_TYPE_TO_LEGACY_KEY.get(st)
        if key and key not in out:
            out.append(key)
    return out


def normalize_mapping_rule(
    raw: Mapping[str, Any],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    instructions = str(raw.get("instructions") or "").strip()
    supply_types = _normalize_supply_types(raw.get("supply_types"))
    supplies = _normalize_legacy_supplies(raw.get("supplies"))
    if not supply_types and supplies:
        supply_types = supply_types_from_legacy_supplies(supplies)
    if not supplies and supply_types:
        supplies = legacy_supplies_from_types(supply_types, products_by_type=products_by_type)

    if not instructions and not raw.get("default"):
        return None

    defaults_by_instr = {str(r["instructions"]): dict(r) for r in DEFAULT_TYPE_MAPPING_RULES}
    merged = defaults_by_instr.get(instructions)

    out: dict[str, Any] = {
        "instructions": instructions,
        "supply_types": supply_types,
        "supplies": supplies,
    }
    for key in ("requires", "excludes", "default"):
        if key in raw:
            out[key] = raw[key]
        elif merged and key in merged and key not in out:
            out[key] = merged[key]

    if merged and not supply_types:
        out["supply_types"] = list(merged.get("supply_types") or [])
    if merged and not supplies:
        out["supplies"] = list(merged.get("supplies") or [])

    if not out["supply_types"] and not out["supplies"] and not out.get("default"):
        return None
    return out


def default_mapping_rules(
    *,
    products_by_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in DEFAULT_TYPE_MAPPING_RULES:
        norm = normalize_mapping_rule(rule, products_by_type=products_by_type)
        if norm:
            out.append(norm)
    return out


def mapping_rules_for_display(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in rules:
        supplies = _normalize_legacy_supplies(rule.get("supplies"))
        supply_types = _normalize_supply_types(rule.get("supply_types"))
        if not supply_types and supplies:
            supply_types = supply_types_from_legacy_supplies(supplies)
        item: dict[str, Any] = {
            "instructions": str(rule.get("instructions") or "").strip(),
            "supplies": supplies,
            "supply_types": supply_types,
            "supplies_display": " + ".join(supplies),
            "supply_types_display": " + ".join(supply_types),
        }
        if rule.get("default"):
            item["default"] = True
        if "requires" in rule:
            item["requires"] = list(rule.get("requires") or [])
        if "excludes" in rule:
            item["excludes"] = list(rule.get("excludes") or [])
        out.append(item)
    return out


def resolve_supplies_for_rule(
    rule: Mapping[str, Any],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Return legacy brand keys for a rule using type → active product when possible."""
    supply_types = _normalize_supply_types(rule.get("supply_types"))
    if not supply_types:
        supply_types = supply_types_from_legacy_supplies(
            _normalize_legacy_supplies(rule.get("supplies"))
        )
    if supply_types:
        return legacy_supplies_from_types(supply_types, products_by_type=products_by_type)
    return _normalize_legacy_supplies(rule.get("supplies"))


def resolve_products_for_rule(
    rule: Mapping[str, Any],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    supply_types = _normalize_supply_types(rule.get("supply_types"))
    if not supply_types:
        supply_types = supply_types_from_legacy_supplies(
            _normalize_legacy_supplies(rule.get("supplies"))
        )
    out: list[dict[str, Any]] = []
    for st in supply_types:
        product = products_by_type.get(st)
        if product:
            out.append(dict(product))
    return out


def ensure_org_supply_master(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Ensure tables + seed defaults; return product list."""
    ensure_supply_product_tables(cursor)
    seed_default_supply_products(cursor, organization_id)
    return list_supply_products(cursor, organization_id)


def load_mapping_context(cursor, organization_id: int) -> dict[str, Any]:
    products = ensure_org_supply_master(cursor, organization_id)
    by_type = active_products_by_supply_type(products)
    return {
        "products": products,
        "products_by_type": by_type,
        "dosages_from_master": dosages_from_products(products),
    }


def project_rules_with_active_products(
    rules: Sequence[Mapping[str, Any]],
    *,
    products_by_type: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rewrite supplies[] from supply_types using current active products."""
    out: list[dict[str, Any]] = []
    for rule in rules:
        norm = normalize_mapping_rule(rule, products_by_type=products_by_type)
        if not norm:
            continue
        norm["supplies"] = resolve_supplies_for_rule(norm, products_by_type=products_by_type)
        norm["resolved_products"] = [
            {
                "id": p.get("id"),
                "supply_type": p.get("supply_type"),
                "brand": p.get("brand"),
                "product_name": p.get("product_name"),
                "legacy_report_key": p.get("legacy_report_key"),
            }
            for p in resolve_products_for_rule(norm, products_by_type=products_by_type)
        ]
        out.append(norm)
    return out
