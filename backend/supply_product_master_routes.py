"""Management Supply Product Master + mapping routes (Phase A)."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.rinse_scan_time import json_safe_rinse
from backend.supply_product_constants import (
    PRODUCT_FORMS,
    SEED_PLACEHOLDER_SUMMARY,
    SUPPLY_TYPES,
    SUPPLY_TYPE_LABELS,
)
from backend.supply_product_mapping import (
    mapping_rules_for_display,
)
from backend.supply_product_master import (
    add_product_price,
    create_supply_product,
    ensure_supply_product_tables,
    get_supply_product,
    list_product_prices,
    list_supply_products,
    seed_default_supply_products,
    update_supply_product,
)
from backend.supply_usage_settings import (
    get_supply_usage_mapping_rules,
    save_supply_usage_mapping_rules,
)


def register_supply_product_master_routes(
    app,
    *,
    require_user,
    require_admin_or_ops,
    user_org_id,
    parse_date_value,
) -> None:
    def _as_of_from_request() -> date:
        raw = (request.args.get("as_of") or request.args.get("date_et") or "").strip()
        if not raw:
            return business_today()
        try:
            parsed = parse_date_value(raw)
        except (TypeError, ValueError):
            raise ValueError("Invalid as_of / date_et; use YYYY-MM-DD")
        if not isinstance(parsed, date):
            raise ValueError("Invalid as_of / date_et; use YYYY-MM-DD")
        return parsed

    @app.route("/api/management/supply-products/meta", methods=["GET"])
    def management_supply_products_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            return jsonify(
                {
                    "supply_types": [
                        {"id": t, "label": SUPPLY_TYPE_LABELS.get(t, t)} for t in SUPPLY_TYPES
                    ],
                    "forms": list(PRODUCT_FORMS),
                    "placeholder_note": SEED_PLACEHOLDER_SUMMARY,
                    "inventory_items_decision": {
                        "choice": "NEW",
                        "reason": (
                            "inventory_items is warehouse stock/count/order; "
                            "Supply Product Master is laundry-process identity + "
                            "effective-dated dose/cost. Optional inventory_item_id link later."
                        ),
                    },
                    "historical_cost_strategy": (
                        "supply_product_prices rows are effective-dated (ET business dates). "
                        "A report for date D uses the price whose window covers D. "
                        "Later price changes do not rewrite earlier reports. "
                        "Phase B+ may also snapshot cost onto usage aggregates."
                    ),
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/supply-products", methods=["GET", "POST"])
    def management_supply_products():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            ensure_supply_product_tables(cursor)
            if request.method == "GET":
                try:
                    as_of = _as_of_from_request()
                except ValueError as ve:
                    return jsonify({"error": str(ve)}), 400
                seed_info = seed_default_supply_products(cursor, tenant_oid)
                conn.commit()
                active_only = str(request.args.get("active_only") or "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                products = list_supply_products(
                    cursor, tenant_oid, active_only=active_only, as_of=as_of
                )
                return jsonify(
                    json_safe_rinse(
                        {
                            "products": products,
                            "seeded": bool(seed_info.get("seeded")),
                            "placeholder_note": seed_info.get("placeholder_note"),
                            "as_of_date_et": str(as_of),
                        }
                    )
                )
            data = request.get_json(silent=True) or {}
            created = create_supply_product(cursor, tenant_oid, data)
            conn.commit()
            return jsonify(json_safe_rinse(created)), 201
        except ValueError as ve:
            conn.rollback()
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/supply-products/<int:product_id>", methods=["GET", "PUT"])
    def management_supply_product_detail(product_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            if request.method == "GET":
                try:
                    as_of = _as_of_from_request()
                except ValueError as ve:
                    return jsonify({"error": str(ve)}), 400
                row = get_supply_product(cursor, tenant_oid, product_id, as_of=as_of)
                if not row:
                    return jsonify({"error": "Product not found"}), 404
                row["price_history"] = list_product_prices(cursor, tenant_oid, product_id)
                return jsonify(json_safe_rinse(row))
            data = request.get_json(silent=True) or {}
            updated = update_supply_product(cursor, tenant_oid, product_id, data)
            if not updated:
                return jsonify({"error": "Product not found"}), 404
            conn.commit()
            return jsonify(json_safe_rinse(updated))
        except ValueError as ve:
            conn.rollback()
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/supply-products/<int:product_id>/prices",
        methods=["GET", "POST"],
    )
    def management_supply_product_prices(product_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            if not get_supply_product(cursor, tenant_oid, product_id):
                return jsonify({"error": "Product not found"}), 404
            if request.method == "GET":
                return jsonify(
                    json_safe_rinse(
                        {"prices": list_product_prices(cursor, tenant_oid, product_id)}
                    )
                )
            data = request.get_json(silent=True) or {}
            created = add_product_price(cursor, tenant_oid, product_id, data)
            conn.commit()
            return jsonify(json_safe_rinse(created)), 201
        except ValueError as ve:
            conn.rollback()
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/supply-mappings", methods=["GET", "PUT"])
    def management_supply_mappings():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            # Ensure seed so type → product resolution has targets.
            ensure_supply_product_tables(cursor)
            seed_default_supply_products(cursor, tenant_oid)
            conn.commit()
            if request.method == "GET":
                rules = get_supply_usage_mapping_rules(cursor, tenant_oid)
                return jsonify(json_safe_rinse({"mapping_rules": mapping_rules_for_display(rules)}))
            data = request.get_json(silent=True) or {}
            rules_payload = (
                data.get("mapping_rules") if isinstance(data.get("mapping_rules"), list) else data
            )
            if not isinstance(rules_payload, list):
                return jsonify({"error": "mapping_rules must be a list"}), 400
            out = save_supply_usage_mapping_rules(cursor, tenant_oid, rules_payload)
            conn.commit()
            return jsonify(json_safe_rinse({"mapping_rules": mapping_rules_for_display(out)}))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
