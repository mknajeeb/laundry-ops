"""Phase A — Supply Product Master + type mapping adapter tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from backend.supply_product_constants import (
    DEFAULT_TYPE_MAPPING_RULES,
    LEGACY_KEY_DOWNY,
    LEGACY_KEY_HYPO,
    LEGACY_KEY_OXICLEAN,
    LEGACY_KEY_TIDE,
    SEED_PRODUCTS,
    SUPPLY_TYPE_BOOSTER_OXI,
    SUPPLY_TYPE_DETERGENT,
    SUPPLY_TYPE_FABRIC_SOFTENER,
    SUPPLY_TYPE_HYPO_DETERGENT,
)
from backend.supply_product_mapping import (
    default_mapping_rules,
    legacy_supplies_from_types,
    normalize_mapping_rule,
    project_rules_with_active_products,
    resolve_supplies_for_rule,
    supply_types_from_legacy_supplies,
)
from backend.supply_product_master import (
    calculate_cost_metrics,
    resolve_price_as_of,
)
from backend.supply_usage import supplies_for_usage
from backend.supply_usage_settings import (
    DEFAULT_DOSAGES,
    DEFAULT_MAPPING_RULES,
    KEY_SUPPLY_USAGE_MAPPING_RULES,
    get_supply_usage_dosages,
    get_supply_usage_mapping_rules,
    save_supply_usage_mapping_rules,
)


class TestCostCalculations:
    def test_doses_and_cost_per_dose(self):
        m = calculate_cost_metrics(
            package_qty=100,
            average_dose=2.0,
            purchase_price_per_package=18.0,
        )
        assert m["doses_per_package"] == 50.0
        assert m["cost_per_dose"] == 0.36
        assert m["cost_per_standard_load"] == 0.36

    def test_zero_dose_returns_null_costs(self):
        m = calculate_cost_metrics(package_qty=100, average_dose=0, purchase_price_per_package=10)
        assert m["doses_per_package"] is None
        assert m["cost_per_dose"] is None


class TestEffectiveDating:
    def test_aug17_uses_aug17_price_after_later_change(self):
        rows = [
            {
                "id": 1,
                "purchase_price_per_package": 18.0,
                "effective_from": "2020-01-01",
                "effective_to": "2026-08-17",
            },
            {
                "id": 2,
                "purchase_price_per_package": 22.0,
                "effective_from": "2026-08-18",
                "effective_to": None,
            },
        ]
        aug17 = resolve_price_as_of(rows, date(2026, 8, 17))
        aug18 = resolve_price_as_of(rows, date(2026, 8, 18))
        assert aug17 is not None
        assert float(aug17["purchase_price_per_package"]) == 18.0
        assert aug18 is not None
        assert float(aug18["purchase_price_per_package"]) == 22.0

    def test_open_ended_prior_still_covers_day(self):
        rows = [
            {
                "id": 1,
                "purchase_price_per_package": 10.0,
                "effective_from": "2024-01-01",
                "effective_to": None,
            }
        ]
        hit = resolve_price_as_of(rows, date(2026, 8, 17))
        assert hit is not None
        assert float(hit["purchase_price_per_package"]) == 10.0


class TestMappingTypeResolution:
    def test_default_type_rules_match_legacy_brand_lists(self):
        rules = default_mapping_rules()
        assert len(rules) == len(DEFAULT_TYPE_MAPPING_RULES)
        by_instr = {r["instructions"]: r for r in rules}
        assert by_instr["None / default"]["supply_types"] == [SUPPLY_TYPE_DETERGENT]
        assert by_instr["None / default"]["supplies"] == [LEGACY_KEY_TIDE]
        assert by_instr["Fabric Softener"]["supply_types"] == [
            SUPPLY_TYPE_DETERGENT,
            SUPPLY_TYPE_FABRIC_SOFTENER,
        ]
        assert by_instr["Hypo + OxiClean"]["supplies"] == [LEGACY_KEY_HYPO, LEGACY_KEY_OXICLEAN]

    def test_legacy_supplies_convert_to_types(self):
        types = supply_types_from_legacy_supplies(
            [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY, LEGACY_KEY_OXICLEAN]
        )
        assert types == [
            SUPPLY_TYPE_DETERGENT,
            SUPPLY_TYPE_FABRIC_SOFTENER,
            SUPPLY_TYPE_BOOSTER_OXI,
        ]

    def test_active_product_overrides_legacy_key_projection(self):
        products_by_type = {
            SUPPLY_TYPE_DETERGENT: {
                "id": 9,
                "legacy_report_key": LEGACY_KEY_TIDE,
                "supply_type": SUPPLY_TYPE_DETERGENT,
            },
            SUPPLY_TYPE_HYPO_DETERGENT: {
                "id": 10,
                "legacy_report_key": LEGACY_KEY_HYPO,
                "supply_type": SUPPLY_TYPE_HYPO_DETERGENT,
            },
        }
        supplies = legacy_supplies_from_types(
            [SUPPLY_TYPE_DETERGENT, SUPPLY_TYPE_HYPO_DETERGENT],
            products_by_type=products_by_type,
        )
        assert supplies == [LEGACY_KEY_TIDE, LEGACY_KEY_HYPO]

    def test_normalize_accepts_brand_only_rules(self):
        norm = normalize_mapping_rule(
            {"instructions": "VIP", "supplies": ["Tide", "Downy"]}
        )
        assert norm is not None
        assert norm["supply_types"] == [SUPPLY_TYPE_DETERGENT, SUPPLY_TYPE_FABRIC_SOFTENER]
        assert norm["supplies"] == [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY]

    def test_project_rules_preserves_default_categories(self):
        products_by_type = {
            SUPPLY_TYPE_DETERGENT: {"id": 1, "legacy_report_key": LEGACY_KEY_TIDE},
            SUPPLY_TYPE_FABRIC_SOFTENER: {"id": 2, "legacy_report_key": LEGACY_KEY_DOWNY},
            SUPPLY_TYPE_BOOSTER_OXI: {"id": 3, "legacy_report_key": LEGACY_KEY_OXICLEAN},
            SUPPLY_TYPE_HYPO_DETERGENT: {"id": 4, "legacy_report_key": LEGACY_KEY_HYPO},
        }
        projected = project_rules_with_active_products(
            DEFAULT_TYPE_MAPPING_RULES,
            products_by_type=products_by_type,
        )
        assert resolve_supplies_for_rule(projected[-1], products_by_type=products_by_type) == [
            LEGACY_KEY_TIDE
        ]
        hypo_oxi = next(r for r in projected if r["instructions"] == "Hypo + OxiClean")
        assert hypo_oxi["supplies"] == [LEGACY_KEY_HYPO, LEGACY_KEY_OXICLEAN]


class TestBackwardCompatibleSupplyUsage:
    def test_default_mapping_rules_export_still_resolves_brands(self):
        assert len(DEFAULT_MAPPING_RULES) == len(DEFAULT_TYPE_MAPPING_RULES)
        out = supplies_for_usage(None, rules=DEFAULT_MAPPING_RULES)
        assert out["supplies_used"] == [LEGACY_KEY_TIDE]

    def test_default_rules_cover_all_preference_categories(self):
        cases = [
            ("USE HYPOALLERGENIC SOAP; USE FABRIC SOFTENER; USE OXICLEAN", [
                LEGACY_KEY_HYPO,
                LEGACY_KEY_DOWNY,
                LEGACY_KEY_OXICLEAN,
            ]),
            ("USE HYPOALLERGENIC SOAP; USE OXICLEAN", [LEGACY_KEY_HYPO, LEGACY_KEY_OXICLEAN]),
            ("USE HYPOALLERGENIC SOAP", [LEGACY_KEY_HYPO]),
            ("USE FABRIC SOFTENER; USE OXICLEAN", [
                LEGACY_KEY_TIDE,
                LEGACY_KEY_DOWNY,
                LEGACY_KEY_OXICLEAN,
            ]),
            ("USE FABRIC SOFTENER", [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY]),
            ("USE OXICLEAN", [LEGACY_KEY_TIDE, LEGACY_KEY_OXICLEAN]),
            ("", [LEGACY_KEY_TIDE]),
        ]
        for raw, expected in cases:
            out = supplies_for_usage(raw or None, rules=DEFAULT_MAPPING_RULES)
            assert out["supplies_used"] == expected, raw

    def test_get_dosages_defaults_without_master_table(self):
        class _Cur:
            def execute(self, *_a, **_k):
                return None

            def fetchone(self):
                return None

        with patch("backend.supply_usage_settings.table_exists", return_value=False):
            out = get_supply_usage_dosages(_Cur(), 1)
        assert out == DEFAULT_DOSAGES

    def test_get_mapping_rules_defaults_when_unset(self):
        class _Cur:
            def execute(self, *_a, **_k):
                return None

            def fetchone(self):
                return None

        with patch("backend.supply_usage_settings.table_exists", return_value=False):
            rules = get_supply_usage_mapping_rules(_Cur(), 3)
        assert rules[-1]["default"] is True
        assert rules[-1]["supplies"] == [LEGACY_KEY_TIDE]
        assert rules[-1]["supply_types"] == [SUPPLY_TYPE_DETERGENT]

    def test_mapping_rules_persist_type_first(self):
        stored: dict[str, str] = {}

        def fake_get(_c, _oid, key):
            return stored.get(key)

        def fake_set(_c, _oid, key, value):
            stored[key] = value

        with patch("backend.supply_usage_settings.table_exists", return_value=False), patch(
            "backend.supply_usage_settings._get_setting", side_effect=fake_get
        ), patch("backend.supply_usage_settings._set_setting", side_effect=fake_set):
            saved = save_supply_usage_mapping_rules(
                object(),
                3,
                [
                    {
                        "instructions": "VIP",
                        "supply_types": [SUPPLY_TYPE_DETERGENT, SUPPLY_TYPE_FABRIC_SOFTENER],
                    },
                    {
                        "instructions": "None / default",
                        "supply_types": [SUPPLY_TYPE_DETERGENT],
                        "default": True,
                    },
                ],
            )
            assert saved[0]["supplies"] == [LEGACY_KEY_TIDE, LEGACY_KEY_DOWNY]
            assert KEY_SUPPLY_USAGE_MAPPING_RULES in stored
            reloaded = get_supply_usage_mapping_rules(object(), 3)
            assert reloaded[0]["instructions"] == "VIP"
            assert reloaded[0]["supply_types"] == [
                SUPPLY_TYPE_DETERGENT,
                SUPPLY_TYPE_FABRIC_SOFTENER,
            ]


class TestSeedCatalog:
    def test_seed_covers_operational_set(self):
        keys = {s["legacy_report_key"] for s in SEED_PRODUCTS}
        assert keys == {
            LEGACY_KEY_TIDE,
            LEGACY_KEY_DOWNY,
            LEGACY_KEY_OXICLEAN,
            LEGACY_KEY_HYPO,
        }
        by_key = {s["legacy_report_key"]: s for s in SEED_PRODUCTS}
        assert by_key[LEGACY_KEY_TIDE]["average_dose"] == 2.0
        assert by_key[LEGACY_KEY_DOWNY]["average_dose"] == 1.0
        assert by_key[LEGACY_KEY_OXICLEAN]["average_dose"] == 1.0
        assert by_key[LEGACY_KEY_HYPO]["average_dose"] == 2.0
        assert by_key[LEGACY_KEY_TIDE]["product_name"] == "Tide Original"


class TestInMemoryProductCrud:
    """Lightweight fake store for master CRUD without MySQL."""

    def test_create_list_update_and_price_history(self):
        from backend import supply_product_master as spm

        products: dict[int, dict] = {}
        prices: dict[int, list[dict]] = {}
        seq = {"p": 0, "pr": 0}

        class FakeCursor:
            lastrowid = 0

            def execute(self, sql, params=None):
                sql_n = " ".join(sql.split()).lower()
                params = params or ()
                self._rows = []
                self._row = None
                if "create table" in sql_n:
                    return
                if "select count(*) as c from supply_products" in sql_n:
                    self._row = {"c": len(products)}
                    return
                if sql_n.startswith("insert into supply_products"):
                    seq["p"] += 1
                    pid = seq["p"]
                    self.lastrowid = pid
                    products[pid] = {
                        "id": pid,
                        "organization_id": params[0],
                        "product_code": params[1],
                        "supply_type": params[2],
                        "brand": params[3],
                        "product_name": params[4],
                        "vendor": params[5],
                        "form": params[6],
                        "package_qty": params[7],
                        "package_unit": params[8],
                        "average_dose": params[9],
                        "dose_unit": params[10],
                        "is_active": params[11],
                        "legacy_report_key": params[12],
                        "inventory_item_id": params[13],
                        "sort_order": params[14],
                        "notes": params[15],
                    }
                    return
                if sql_n.startswith("insert into supply_product_prices"):
                    seq["pr"] += 1
                    prid = seq["pr"]
                    self.lastrowid = prid
                    prices.setdefault(params[1], []).append(
                        {
                            "id": prid,
                            "organization_id": params[0],
                            "product_id": params[1],
                            "purchase_price_per_package": params[2],
                            "effective_from": params[3],
                            "effective_to": params[4],
                            "notes": params[5],
                        }
                    )
                    return
                if "update supply_product_prices set effective_to" in sql_n:
                    pid = params[2]
                    for row in prices.get(pid, []):
                        if row.get("effective_to") is None and row["effective_from"] < params[3]:
                            row["effective_to"] = params[0]
                    return
                if "update supply_products set" in sql_n:
                    pid = params[-1]
                    products[pid].update(
                        {
                            "product_code": params[0],
                            "supply_type": params[1],
                            "brand": params[2],
                            "product_name": params[3],
                            "vendor": params[4],
                            "form": params[5],
                            "package_qty": params[6],
                            "package_unit": params[7],
                            "average_dose": params[8],
                            "dose_unit": params[9],
                            "is_active": params[10],
                            "legacy_report_key": params[11],
                            "inventory_item_id": params[12],
                            "sort_order": params[13],
                            "notes": params[14],
                        }
                    )
                    return
                if "from supply_products where organization_id" in sql_n and "and id" in sql_n:
                    pid = params[1]
                    self._row = dict(products[pid]) if pid in products else None
                    return
                if "from supply_products where organization_id" in sql_n:
                    self._rows = [dict(p) for p in products.values() if p["organization_id"] == params[0]]
                    return
                if "from supply_product_prices" in sql_n:
                    if len(params) >= 2:
                        self._rows = list(prices.get(params[1], []))
                    else:
                        # list_all_product_prices_for_org(org) — all products
                        self._rows = [
                            dict(row)
                            for pid_rows in prices.values()
                            for row in pid_rows
                            if row.get("organization_id") == params[0]
                        ]
                    return

            def fetchone(self):
                return self._row

            def fetchall(self):
                return list(self._rows)

        cur = FakeCursor()
        with patch.object(spm, "table_exists", return_value=True), patch.object(
            spm, "business_today", return_value=date(2026, 8, 17)
        ):
            created = spm.create_supply_product(
                cur,
                3,
                {
                    "supply_type": SUPPLY_TYPE_DETERGENT,
                    "brand": "Tide",
                    "product_name": "Tide Original",
                    "form": "LIQUID",
                    "package_qty": 100,
                    "average_dose": 2.0,
                    "legacy_report_key": LEGACY_KEY_TIDE,
                    "purchase_price_per_package": 18.0,
                    "effective_from": date(2020, 1, 1),
                },
            )
            assert created["id"] == 1
            assert created["doses_per_package"] == 50.0
            assert created["cost_per_dose"] == 0.36

            spm.add_product_price(
                cur,
                3,
                1,
                {
                    "purchase_price_per_package": 22.0,
                    "effective_from": date(2026, 8, 18),
                    "notes": "price increase",
                },
            )
            as_aug17 = spm.get_supply_product(cur, 3, 1, as_of=date(2026, 8, 17))
            as_aug18 = spm.get_supply_product(cur, 3, 1, as_of=date(2026, 8, 18))
            assert as_aug17["purchase_price_per_package"] == 18.0
            assert as_aug18["purchase_price_per_package"] == 22.0

            updated = spm.update_supply_product(
                cur,
                3,
                1,
                {
                    "supply_type": SUPPLY_TYPE_DETERGENT,
                    "brand": "Tide",
                    "product_name": "Tide Original",
                    "form": "LIQUID",
                    "package_qty": 100,
                    "package_unit": "oz",
                    "average_dose": 2.5,
                    "dose_unit": "oz",
                    "is_active": True,
                    "legacy_report_key": LEGACY_KEY_TIDE,
                },
            )
            assert updated["average_dose"] == 2.5
            listed = spm.list_supply_products(cur, 3, as_of=date(2026, 8, 17))
            assert len(listed) == 1
