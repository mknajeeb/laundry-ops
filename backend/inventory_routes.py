"""Inventory v2.5 API routes."""

from __future__ import annotations

from datetime import date, timedelta

from flask import jsonify, request

from backend.db import get_db
from backend.inventory_constants import ADJUSTMENT_REASONS, VARIANCE_REASONS, VARIANCE_THRESHOLD_KEY
from backend.inventory_module import (
    create_bag_sale,
    deactivate_item,
    duplicate_order,
    get_activity_report,
    get_bag_price,
    get_draft_stock_check,
    get_item,
    get_latest_stock_check,
    get_orders_summary,
    get_org_setting,
    get_variance_threshold,
    get_vendor_detail,
    get_weekly_order_report,
    list_bag_sales,
    list_categories,
    list_items,
    list_orders,
    list_reorder_suggestions,
    list_vendors,
    manual_adjustment,
    receive_order,
    save_bag_price,
    save_category,
    save_item,
    save_order,
    save_org_setting,
    save_stock_check_draft,
    save_vendor,
    StockCheckConflictError,
    submit_stock_check,
)
from backend.inventory_ops import build_dashboard, get_item_history, get_reports_bundle
from backend.rinse_scan_time import json_safe_rinse


def register_inventory_routes(
    app,
    *,
    require_user,
    require_admin,
    require_admin_or_ops,
    user_org_id,
    parse_date_value,
) -> None:
    def _roles(me) -> set[str]:
        return {str(r).upper() for r in (me.get("roles") or [])}

    def _is_admin(rs: set[str]) -> bool:
        return bool(rs & {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"})

    def _is_supervisor(rs: set[str]) -> bool:
        return _is_admin(rs) or "OPS" in rs

    def _floor_only(rs: set[str]) -> bool:
        return "FRONT_DESK" in rs and not _is_supervisor(rs)

    def _me(cursor):
        me, err_resp, err_code = require_user(cursor)
        return me, err_resp, err_code, user_org_id(me) if me else None

    def _supervisor(cursor):
        me, err_resp, err_code = require_admin_or_ops(cursor)
        return me, err_resp, err_code, user_org_id(me) if me else None

    def _admin(cursor):
        me, err_resp, err_code = require_admin(cursor)
        return me, err_resp, err_code, user_org_id(me) if me else None

    @app.route("/inventory/dashboard", methods=["GET"])
    def inventory_dashboard():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            rs = _roles(me)
            include_financials = _is_supervisor(rs)
            return jsonify(json_safe_rinse(build_dashboard(cursor, org_id, include_financials=include_financials)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/meta", methods=["GET"])
    def inventory_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            rs = _roles(me)
            return jsonify(json_safe_rinse({
                "role_tier": "admin" if _is_admin(rs) else ("supervisor" if _is_supervisor(rs) else "floor"),
                "variance_threshold": get_variance_threshold(cursor, org_id),
                "variance_reasons": VARIANCE_REASONS,
                "adjustment_reasons": ADJUSTMENT_REASONS,
            }))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/bootstrap", methods=["GET"])
    def inventory_bootstrap():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            rs = _roles(me)
            categories = list_categories(cursor, org_id, active_only=False)
            items = list_items(cursor, org_id, active_only=True)
            draft = get_draft_stock_check(cursor, org_id)
            latest = get_latest_stock_check(cursor, org_id)
            summary = get_orders_summary(cursor, org_id) if _is_supervisor(rs) else None
            dashboard = build_dashboard(cursor, org_id, include_financials=_is_supervisor(rs))
            return jsonify(json_safe_rinse({
                "categories": categories,
                "items": items,
                "draft_check": draft,
                "latest_check": latest,
                "orders_summary": summary,
                "dashboard": dashboard,
                "role_tier": "admin" if _is_admin(rs) else ("supervisor" if _is_supervisor(rs) else "floor"),
            }))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/categories", methods=["GET", "POST", "PUT"])
    def inventory_categories_api():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method == "GET":
                me, err_resp, err_code, org_id = _me(cursor)
            else:
                me, err_resp, err_code, org_id = _admin(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
                return jsonify(json_safe_rinse(list_categories(cursor, org_id, active_only=active_only)))
            data = request.get_json(silent=True) or {}
            out = save_category(cursor, org_id, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/vendors", methods=["GET", "POST", "PUT"])
    def inventory_vendors_api():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method == "GET":
                me, err_resp, err_code, org_id = _me(cursor)
            else:
                me, err_resp, err_code, org_id = _admin(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
                with_stats = request.args.get("with_stats", "").lower() in ("1", "true", "yes")
                if with_stats and _floor_only(_roles(me)):
                    return jsonify({"error": "Forbidden"}), 403
                return jsonify(json_safe_rinse(list_vendors(cursor, org_id, active_only=active_only, with_stats=with_stats)))
            data = request.get_json(silent=True) or {}
            out = save_vendor(cursor, org_id, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/vendors/<int:vendor_id>", methods=["GET"])
    def inventory_vendor_detail(vendor_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            detail = get_vendor_detail(cursor, org_id, vendor_id)
            if not detail:
                return jsonify({"error": "Vendor not found"}), 404
            return jsonify(json_safe_rinse(detail))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/items", methods=["GET", "POST", "PUT", "DELETE"])
    def inventory_items_v2_api():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method in ("POST", "PUT", "DELETE"):
                me, err_resp, err_code, org_id = _admin(cursor)
            else:
                me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code

            if request.method == "GET":
                active_only = request.args.get("active_only", "1").lower() in ("1", "true", "yes")
                weekly_only = request.args.get("weekly_check_only", "").lower() in ("1", "true", "yes")
                search = request.args.get("search") or request.args.get("q")
                return jsonify(json_safe_rinse(list_items(
                    cursor, org_id, active_only=active_only, weekly_check_only=weekly_only, search=search,
                )))

            if request.method == "DELETE":
                item_id = request.args.get("id")
                if not item_id:
                    return jsonify({"error": "id is required"}), 400
                out = deactivate_item(cursor, org_id, int(item_id))
                conn.commit()
                return jsonify(json_safe_rinse(out))

            data = request.get_json(silent=True) or {}
            out = save_item(cursor, org_id, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/items/<int:item_id>/history", methods=["GET"])
    def inventory_item_history(item_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            limit = int(request.args.get("limit") or 100)
            return jsonify(json_safe_rinse(get_item_history(cursor, org_id, item_id, limit=limit)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/stock-check/draft", methods=["GET", "POST"])
    def inventory_stock_check_draft():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            if request.method == "GET":
                draft = get_draft_stock_check(cursor, org_id)
                latest = get_latest_stock_check(cursor, org_id)
                return jsonify(json_safe_rinse({
                    "draft": draft,
                    "latest": latest,
                    "variance_threshold": get_variance_threshold(cursor, org_id),
                    "variance_reasons": VARIANCE_REASONS,
                }))
            data = request.get_json(silent=True) or {}
            out = save_stock_check_draft(cursor, org_id, data, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/stock-check/submit", methods=["POST"])
    def inventory_stock_check_submit():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            data = request.get_json(silent=True) or {}
            out = submit_stock_check(cursor, org_id, data, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except StockCheckConflictError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 409
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/reorder-suggestions", methods=["GET"])
    def inventory_reorder_suggestions():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            return jsonify(json_safe_rinse(list_reorder_suggestions(cursor, org_id)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/orders/summary", methods=["GET"])
    def inventory_orders_summary():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            return jsonify(json_safe_rinse(get_orders_summary(cursor, org_id)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/orders", methods=["GET", "POST", "PUT"])
    def inventory_orders_api():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method == "GET":
                me, err_resp, err_code, org_id = _supervisor(cursor)
            else:
                me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            if request.method == "GET":
                status = request.args.get("status") or None
                limit = int(request.args.get("limit") or 100)
                return jsonify(json_safe_rinse(list_orders(cursor, org_id, status=status, limit=limit)))
            data = request.get_json(silent=True) or {}
            out = save_order(cursor, org_id, data, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/orders/<int:order_id>/receive", methods=["POST"])
    def inventory_orders_receive(order_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            data = request.get_json(silent=True) or {}
            out = receive_order(cursor, org_id, order_id, data, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/orders/<int:order_id>/duplicate", methods=["POST"])
    def inventory_orders_duplicate(order_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            out = duplicate_order(cursor, org_id, order_id, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/adjustments", methods=["POST"])
    def inventory_adjustments_api():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = me.get("display_name") or me.get("username") or "Unknown"
            data = request.get_json(silent=True) or {}
            out = manual_adjustment(cursor, org_id, data, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/reports", methods=["GET"])
    def inventory_reports_bundle():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            report_type = request.args.get("type") or "all"
            return jsonify(json_safe_rinse(get_reports_bundle(cursor, org_id, report_type)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/reports/weekly-orders", methods=["GET"])
    def inventory_reports_weekly_orders():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            start_raw = request.args.get("start_date")
            end_raw = request.args.get("end_date")
            if start_raw and end_raw:
                start = parse_date_value(start_raw)
                end = parse_date_value(end_raw)
            else:
                today = date.today()
                week_start = today - timedelta(days=today.weekday())
                start = week_start - timedelta(days=7)
                end = week_start - timedelta(days=1)
            if not start or not end:
                return jsonify({"error": "Invalid date range"}), 400
            return jsonify(json_safe_rinse(get_weekly_order_report(cursor, org_id, start, end)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/settings/variance-threshold", methods=["GET", "PUT"])
    def inventory_variance_threshold():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method == "PUT":
                me, err_resp, err_code, org_id = _admin(cursor)
            else:
                me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                return jsonify(json_safe_rinse({"variance_threshold": get_variance_threshold(cursor, org_id)}))
            data = request.get_json(silent=True) or {}
            val = float(data.get("variance_threshold") or 5)
            save_org_setting(cursor, org_id, VARIANCE_THRESHOLD_KEY, str(val), me.get("display_name"))
            conn.commit()
            return jsonify(json_safe_rinse({"variance_threshold": val}))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/report", methods=["GET"])
    def inventory_report_v2():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            start_date = request.args.get("start_date") or None
            end_date = request.args.get("end_date") or None
            item_id_raw = request.args.get("item_id")
            item_id = int(item_id_raw) if item_id_raw else None
            limit = int(request.args.get("limit") or 250)
            return jsonify(json_safe_rinse(get_activity_report(
                cursor, org_id, start_date=start_date, end_date=end_date, item_id=item_id, limit=limit,
            )))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/bag_price", methods=["GET", "POST"])
    def inventory_bag_price_v2():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if request.method == "POST":
                me, err_resp, err_code, org_id = _admin(cursor)
            else:
                me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                return jsonify(json_safe_rinse(get_bag_price(cursor, org_id)))
            data = request.get_json(silent=True) or {}
            price = float(data.get("bag_default_price") or 0)
            updated_by = me.get("display_name") or me.get("username") or "manager"
            out = save_bag_price(cursor, org_id, price, updated_by)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/bag_sales", methods=["GET", "POST"])
    def inventory_bag_sales_v2():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _admin(cursor) if request.method == "POST" else _me(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                return jsonify(json_safe_rinse(list_bag_sales(cursor)))
            data = request.get_json(silent=True) or {}
            data["entered_by"] = me.get("display_name") or me.get("username") or "Unknown"
            out = create_bag_sale(cursor, org_id, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/low_stock", methods=["GET"])
    def inventory_low_stock_v2():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            return jsonify(json_safe_rinse(list_reorder_suggestions(cursor, org_id)))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/reorder", methods=["POST"])
    def inventory_reorder_compat():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _supervisor(cursor)
            if err_resp:
                return err_resp, err_code
            data = request.get_json(silent=True) or {}
            lines_in = data.get("lines") or []
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = data.get("ordered_by") or me.get("display_name") or "manager"
            lines = [
                {"item_id": ln["item_id"], "qty_ordered": ln.get("requested_qty"), "unit_cost": 0}
                for ln in lines_in if ln.get("item_id") and ln.get("requested_qty")
            ]
            out = save_order(cursor, org_id, {"status": "ORDERED", "notes": data.get("notes"), "lines": lines}, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse({"status": "ordered", "lines": len(lines), "order_id": out.get("id")}))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/inventory/counts/bulk", methods=["POST"])
    def inventory_counts_bulk_compat():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            data = request.get_json(silent=True) or {}
            rows = data.get("rows") or []
            user_id = int(me["user_id"]) if me.get("user_id") else None
            user_name = data.get("counted_by") or me.get("display_name") or me.get("username") or "Unknown"
            payload = {"notes": data.get("notes"), "lines": [{"item_id": r["item_id"], "counted_qty": r["counted_qty"]} for r in rows], "oneshot": True}
            out = submit_stock_check(cursor, org_id, payload, user_id, user_name)
            conn.commit()
            return jsonify(json_safe_rinse({"status": "saved", "rows_saved": out.get("lines_submitted", 0)}))
        except StockCheckConflictError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 409
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
