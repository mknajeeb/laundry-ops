"""Supply Product Master constants (Phase A)."""

from __future__ import annotations

from datetime import date
from typing import Any

SUPPLY_TYPE_DETERGENT = "DETERGENT"
SUPPLY_TYPE_FABRIC_SOFTENER = "FABRIC_SOFTENER"
SUPPLY_TYPE_BOOSTER_OXI = "BOOSTER_OXI"
SUPPLY_TYPE_HYPO_DETERGENT = "HYPOALLERGENIC_DETERGENT"

SUPPLY_TYPES: tuple[str, ...] = (
    SUPPLY_TYPE_DETERGENT,
    SUPPLY_TYPE_FABRIC_SOFTENER,
    SUPPLY_TYPE_BOOSTER_OXI,
    SUPPLY_TYPE_HYPO_DETERGENT,
)

SUPPLY_TYPE_LABELS: dict[str, str] = {
    SUPPLY_TYPE_DETERGENT: "Detergent",
    SUPPLY_TYPE_FABRIC_SOFTENER: "Fabric Softener",
    SUPPLY_TYPE_BOOSTER_OXI: "Booster · Oxi",
    SUPPLY_TYPE_HYPO_DETERGENT: "Hypoallergenic Detergent",
}

FORM_LIQUID = "LIQUID"
FORM_POWDER = "POWDER"
PRODUCT_FORMS: tuple[str, ...] = (FORM_LIQUID, FORM_POWDER)

# Legacy report keys consumed by Supply Usage / Management WF today.
LEGACY_KEY_TIDE = "Tide"
LEGACY_KEY_DOWNY = "Downy"
LEGACY_KEY_OXICLEAN = "OxiClean"
LEGACY_KEY_HYPO = "All Free & Clear"

LEGACY_REPORT_KEYS: tuple[str, ...] = (
    LEGACY_KEY_TIDE,
    LEGACY_KEY_DOWNY,
    LEGACY_KEY_OXICLEAN,
    LEGACY_KEY_HYPO,
)

LEGACY_KEY_TO_SUPPLY_TYPE: dict[str, str] = {
    LEGACY_KEY_TIDE: SUPPLY_TYPE_DETERGENT,
    LEGACY_KEY_DOWNY: SUPPLY_TYPE_FABRIC_SOFTENER,
    LEGACY_KEY_OXICLEAN: SUPPLY_TYPE_BOOSTER_OXI,
    LEGACY_KEY_HYPO: SUPPLY_TYPE_HYPO_DETERGENT,
}

# Prefer active product of this type for preference → product resolution.
SUPPLY_TYPE_TO_LEGACY_KEY: dict[str, str] = {
    SUPPLY_TYPE_DETERGENT: LEGACY_KEY_TIDE,
    SUPPLY_TYPE_FABRIC_SOFTENER: LEGACY_KEY_DOWNY,
    SUPPLY_TYPE_BOOSTER_OXI: LEGACY_KEY_OXICLEAN,
    SUPPLY_TYPE_HYPO_DETERGENT: LEGACY_KEY_HYPO,
}

_TOKEN_FAB = "USE FABRIC SOFTENER"
_TOKEN_OXIC = "USE OXICLEAN"
_TOKEN_HYPO = "USE HYPOALLERGENIC SOAP"

# Type-based preference mapping (Phase A). supplies[] retained as legacy projection.
DEFAULT_TYPE_MAPPING_RULES: tuple[dict[str, Any], ...] = (
    {
        "instructions": "Hypo + Fabric Softener + OxiClean",
        "supply_types": [
            SUPPLY_TYPE_HYPO_DETERGENT,
            SUPPLY_TYPE_FABRIC_SOFTENER,
            SUPPLY_TYPE_BOOSTER_OXI,
        ],
        "supplies": [LEGACY_KEY_HYPO, LEGACY_KEY_DOWNY, LEGACY_KEY_OXICLEAN],
        "requires": [_TOKEN_HYPO, _TOKEN_FAB, _TOKEN_OXIC],
    },
    {
        "instructions": "Hypo + OxiClean",
        "supply_types": [SUPPLY_TYPE_HYPO_DETERGENT, SUPPLY_TYPE_BOOSTER_OXI],
        "supplies": [LEGACY_KEY_HYPO, LEGACY_KEY_OXICLEAN],
        "requires": [_TOKEN_HYPO, _TOKEN_OXIC],
        "excludes": [_TOKEN_FAB],
    },
    {
        "instructions": "Hypoallergenic (variations)",
        "supply_types": [SUPPLY_TYPE_HYPO_DETERGENT],
        "supplies": [LEGACY_KEY_HYPO],
        "requires": [_TOKEN_HYPO],
        "excludes": [_TOKEN_OXIC],
    },
    {
        "instructions": "Fabric Softener + OxiClean",
        "supply_types": [
            SUPPLY_TYPE_DETERGENT,
            SUPPLY_TYPE_FABRIC_SOFTENER,
            SUPPLY_TYPE_BOOSTER_OXI,
        ],
        "supplies": [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY, LEGACY_KEY_OXICLEAN],
        "requires": [_TOKEN_FAB, _TOKEN_OXIC],
        "excludes": [_TOKEN_HYPO],
    },
    {
        "instructions": "Fabric Softener",
        "supply_types": [SUPPLY_TYPE_DETERGENT, SUPPLY_TYPE_FABRIC_SOFTENER],
        "supplies": [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY],
        "requires": [_TOKEN_FAB],
        "excludes": [_TOKEN_HYPO, _TOKEN_OXIC],
    },
    {
        "instructions": "OxiClean only",
        "supply_types": [SUPPLY_TYPE_DETERGENT, SUPPLY_TYPE_BOOSTER_OXI],
        "supplies": [LEGACY_KEY_TIDE, LEGACY_KEY_OXICLEAN],
        "requires": [_TOKEN_OXIC],
        "excludes": [_TOKEN_HYPO, _TOKEN_FAB],
    },
    {
        "instructions": "None / default",
        "supply_types": [SUPPLY_TYPE_DETERGENT],
        "supplies": [LEGACY_KEY_TIDE],
        "default": True,
    },
)

# Placeholder package / price values — replace with real vendor invoices when known.
# Dosages match current operational DEFAULT_DOSAGES (not all forced to 2.0 oz).
SEED_PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "product_code": "SP-TIDE-ORIG",
        "supply_type": SUPPLY_TYPE_DETERGENT,
        "brand": "Tide",
        "product_name": "Tide Original",
        "vendor": "PLACEHOLDER — set vendor",
        "form": FORM_LIQUID,
        "package_qty": 100.0,
        "package_unit": "oz",
        "purchase_price_per_package": 18.00,
        "average_dose": 2.0,
        "dose_unit": "oz",
        "legacy_report_key": LEGACY_KEY_TIDE,
        "sort_order": 10,
        "notes": "PLACEHOLDER package 100 oz @ $18.00 — replace with invoice facts",
        "price_effective_from": date(2020, 1, 1),
    },
    {
        "product_code": "SP-DOWNY",
        "supply_type": SUPPLY_TYPE_FABRIC_SOFTENER,
        "brand": "Downy",
        "product_name": "Downy",
        "vendor": "PLACEHOLDER — set vendor",
        "form": FORM_LIQUID,
        "package_qty": 51.0,
        "package_unit": "oz",
        "purchase_price_per_package": 12.00,
        "average_dose": 1.0,
        "dose_unit": "oz",
        "legacy_report_key": LEGACY_KEY_DOWNY,
        "sort_order": 20,
        "notes": "PLACEHOLDER package 51 oz @ $12.00 — replace with invoice facts",
        "price_effective_from": date(2020, 1, 1),
    },
    {
        "product_code": "SP-OXICLEAN",
        "supply_type": SUPPLY_TYPE_BOOSTER_OXI,
        "brand": "OxiClean",
        "product_name": "OxiClean",
        "vendor": "PLACEHOLDER — set vendor",
        "form": FORM_POWDER,
        "package_qty": 48.0,
        "package_unit": "oz",
        "purchase_price_per_package": 14.00,
        "average_dose": 1.0,
        "dose_unit": "oz",
        "legacy_report_key": LEGACY_KEY_OXICLEAN,
        "sort_order": 30,
        "notes": "PLACEHOLDER package 48 oz @ $14.00 — replace with invoice facts",
        "price_effective_from": date(2020, 1, 1),
    },
    {
        "product_code": "SP-ALL-FC",
        "supply_type": SUPPLY_TYPE_HYPO_DETERGENT,
        "brand": "All",
        "product_name": "All Free & Clear",
        "vendor": "PLACEHOLDER — set vendor",
        "form": FORM_LIQUID,
        "package_qty": 100.0,
        "package_unit": "oz",
        "purchase_price_per_package": 20.00,
        "average_dose": 2.0,
        "dose_unit": "oz",
        "legacy_report_key": LEGACY_KEY_HYPO,
        "sort_order": 40,
        "notes": "PLACEHOLDER package 100 oz @ $20.00 — replace with invoice facts",
        "price_effective_from": date(2020, 1, 1),
    },
)

SEED_PLACEHOLDER_SUMMARY = (
    "Package sizes and purchase prices are PLACEHOLDERS until owner enters invoice facts. "
    "Average doses match current operational dosages "
    "(Tide 2.0 oz, Downy 1.0 oz, OxiClean 1.0 oz, All Free & Clear 2.0 oz)."
)
