"""Rinse admin routes: scheduled sync status, order archive search."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_order_search import get_order_archive_detail, search_rinse_orders
from backend.rinse_scrape_status import (
    get_scheduled_scrape_status,
    list_scrape_runs_for_et_range,
)
from backend.rinse_scan_time import json_safe_rinse, json_safe_system
from backend.ta_helpers import table_has_column


def register_rinse_admin_routes(
    app,
    *,
    require_user,
    require_admin,
    user_org_id,
    parse_date_value,
    orders_status_capabilities,
    where_not_sent_or_forced_sql,
    get_upload_batch_rows_pk,
):
    @app.route("/rinse/scheduled-scrape/status", methods=["GET"])
    def rinse_scheduled_scrape_status():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            payload = get_scheduled_scrape_status(cursor, tenant_oid)
            payload["timing_note"] = (
                "Data updates after scrape, CSV import, auto-confirm, finalize, and "
                "completion/folding recompute finish — not at job start time."
            )
            return jsonify(json_safe_system(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/scheduled-scrape/runs", methods=["GET"])
    def rinse_scheduled_scrape_runs():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)

            from backend.rinse_upload_batch_retention import resolve_upload_batch_date_range

            range_preset = request.args.get("range") or "today"
            from_d = parse_date_value(request.args.get("from_date") or "")
            to_d = parse_date_value(request.args.get("to_date") or "")
            try:
                fd, td = resolve_upload_batch_date_range(
                    range_preset=range_preset,
                    from_date=from_d if isinstance(from_d, date) else None,
                    to_date=to_d if isinstance(to_d, date) else None,
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

            runs = list_scrape_runs_for_et_range(
                cursor, tenant_oid, from_date=fd, to_date=td
            )
            return jsonify(
                json_safe_system(
                    {
                        "organization_id": tenant_oid,
                        "range": range_preset,
                        "from_date": fd.isoformat(),
                        "to_date": td.isoformat(),
                        "timezone": "America/New_York",
                        "runs": runs,
                    }
                )
            )
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/order-search", methods=["GET"])
    def rinse_order_search():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)

            def _opt_date(key: str) -> date | None:
                raw = request.args.get(key)
                if not raw:
                    return None
                d = parse_date_value(raw)
                return d if isinstance(d, date) else None

            in_checkout_raw = request.args.get("in_checkout")
            in_checkout = None
            if in_checkout_raw is not None and str(in_checkout_raw).strip() != "":
                in_checkout = str(in_checkout_raw).lower() in ("1", "true", "yes")

            batch_id = None
            if request.args.get("batch_id"):
                try:
                    batch_id = int(request.args.get("batch_id"))
                except (TypeError, ValueError):
                    return jsonify({"error": "Invalid batch_id"}), 400

            try:
                limit = min(200, max(1, int(request.args.get("limit", 50))))
            except (TypeError, ValueError):
                limit = 50
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0

            payload = search_rinse_orders(
                cursor,
                tenant_oid,
                bag_id=(request.args.get("bag_id") or request.args.get("ticket_id") or "").strip()
                or None,
                customer_name=(request.args.get("customer_name") or "").strip() or None,
                batch_id=batch_id,
                completion_status=(request.args.get("completion_status") or "").strip() or None,
                folding_status=(request.args.get("folding_status") or "").strip() or None,
                in_checkout=in_checkout,
                date_clean_from=_opt_date("date_clean_from")
                or _opt_date("processing_date_from"),
                date_clean_to=_opt_date("date_clean_to") or _opt_date("processing_date_to"),
                limit=limit,
                offset=offset,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/order-search/<bag_id>", methods=["GET"])
    def rinse_order_search_detail(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            cap = orders_status_capabilities(cursor)
            detail = get_order_archive_detail(
                cursor,
                tenant_oid,
                bid,
                active_where_sql=where_not_sent_or_forced_sql(cap),
                has_staging_org=table_has_column(cursor, "orders_staging", "organization_id"),
                has_ticket_id_col=cap.get("has_ticket_id", False),
                upload_batch_row_pk=get_upload_batch_rows_pk(cursor),
            )
            if not detail:
                return jsonify({"error": "Bag not found"}), 404
            return jsonify(json_safe_rinse(detail))
        finally:
            cursor.close()
            conn.close()
