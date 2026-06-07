"""Admin routes for cleaner-ticket portal presence scrape (ready_for_vendor / at_vendor)."""

from __future__ import annotations

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    VALID_PORTAL_STATUSES,
    ensure_presence_tables,
)
from backend.rinse_presence_scrape import (
    ready_for_vendor_scrape_enabled,
    run_presence_scrape_for_org,
)
from backend.rinse_presence_sync_status import (
    build_presence_run_list_item,
    get_ready_for_vendor_sync_status,
    list_presence_runs_for_et_range,
)
from backend.rinse_scan_time import json_safe_rinse


def register_rinse_presence_routes(app, *, require_user, require_admin, user_org_id):
    @app.route("/api/rinse/cleaner-ticket-presence/scrape", methods=["POST"])
    def rinse_cleaner_ticket_presence_scrape():
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

            body = request.get_json(silent=True) or {}
            portal_status = str(body.get("portal_status") or PORTAL_STATUS_READY).strip()
            if portal_status not in VALID_PORTAL_STATUSES:
                return jsonify({"error": f"portal_status must be one of {sorted(VALID_PORTAL_STATUSES)}"}), 400

            if portal_status == PORTAL_STATUS_READY and not ready_for_vendor_scrape_enabled(
                cursor, tenant_oid
            ):
                return jsonify(
                    {
                        "error": "ready_for_vendor scrape is disabled for this tenant",
                        "hint": "Set tenant_feature_flags_json.enable_ready_for_vendor_scrape=true in system_settings",
                    }
                ), 403

            dry_run = body.get("dry_run", True)
            if isinstance(dry_run, str):
                dry_run = dry_run.strip().lower() not in ("0", "false", "no")
            else:
                dry_run = bool(dry_run)

            mark_missing = body.get("mark_missing", False)
            if isinstance(mark_missing, str):
                mark_missing = mark_missing.strip().lower() in ("1", "true", "yes")
            else:
                mark_missing = bool(mark_missing)

            result = run_presence_scrape_for_org(
                conn,
                tenant_oid,
                portal_status=portal_status,
                dry_run=dry_run,
                mark_missing=mark_missing,
                run_type="manual",
                organization_slug=me.get("organization_slug"),
                organization_name=me.get("organization_name"),
                rinse_vendor=(body.get("rinse_vendor") or "").strip() or None,
            )
            if result.status == "failed":
                return jsonify(
                    json_safe_rinse(
                        {
                            "error": result.error_message or "Scrape failed",
                            "status": result.status,
                            "scrape_debug": result.scrape_debug,
                            "source_url": result.source_url,
                            "rinse_vendor": result.rinse_vendor,
                        }
                    )
                ), 502

            payload = {
                **result.stats,
                "status": result.status,
                "rinse_vendor": result.rinse_vendor,
                "scrape_debug": result.scrape_debug,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "finished_at": result.finished_at.isoformat() if result.finished_at else None,
                "duration_seconds": result.duration_seconds,
            }
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse/cleaner-ticket-presence/runs", methods=["GET"])
    def rinse_cleaner_ticket_presence_runs():
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
            ensure_presence_tables(cursor)
            try:
                limit = min(50, max(1, int(request.args.get("limit", 20))))
            except (TypeError, ValueError):
                limit = 20
            portal_status = (request.args.get("portal_status") or "").strip() or None
            sql = """
                SELECT *
                FROM rinse_cleaner_ticket_presence_runs
                WHERE organization_id = %s
            """
            args: list = [tenant_oid]
            if portal_status:
                sql += " AND portal_status = %s"
                args.append(portal_status)
            sql += " ORDER BY id DESC LIMIT %s"
            args.append(limit)
            cursor.execute(sql, tuple(args))
            runs = [build_presence_run_list_item(r) for r in (cursor.fetchall() or [])]
            return jsonify(json_safe_rinse({"organization_id": tenant_oid, "runs": runs}))
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse/cleaner-ticket-presence/summary", methods=["GET"])
    def rinse_cleaner_ticket_presence_summary():
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
            ensure_presence_tables(cursor)
            cursor.execute(
                """
                SELECT portal_status, active, COUNT(*) AS cnt
                FROM rinse_cleaner_ticket_presence
                WHERE organization_id = %s
                GROUP BY portal_status, active
                """,
                (tenant_oid,),
            )
            rows = cursor.fetchall() or []
            rfv_status = get_ready_for_vendor_sync_status(cursor, tenant_oid)
            return jsonify(
                json_safe_rinse(
                    {
                        "organization_id": tenant_oid,
                        "counts": rows,
                        "ready_for_vendor_sync": rfv_status,
                    }
                )
            )
        finally:
            cursor.close()
            conn.close()
