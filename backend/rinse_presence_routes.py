"""Admin routes for cleaner-ticket portal presence scrape (ready_for_vendor / at_vendor)."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_bag_export_runner import export_enabled, run_bag_export_csv
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    VALID_PORTAL_STATUSES,
    apply_presence_scrape,
    build_presence_scrape_debug,
    build_tickets_url_for_portal_status,
    ensure_presence_tables,
    parse_presence_rows_from_portal_csv,
    read_portal_scrape_meta,
)
from backend.rinse_scan_time import json_safe_rinse
from backend.rinse_vendor_config import rinse_scrape_env_for_organization
from backend.tenant_feature_flags import is_feature_enabled


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

            if not is_feature_enabled(cursor, tenant_oid, "enable_ready_for_vendor_scrape"):
                return jsonify(
                    {
                        "error": "ready_for_vendor scrape is disabled for this tenant",
                        "hint": "Set tenant_feature_flags_json.enable_ready_for_vendor_scrape=true in system_settings",
                    }
                ), 403

            if not export_enabled():
                return jsonify({"error": "Rinse scrape is disabled (RINSE_BAG_EXPORT_ENABLED not set)"}), 503

            body = request.get_json(silent=True) or {}
            portal_status = str(body.get("portal_status") or PORTAL_STATUS_READY).strip()
            if portal_status not in VALID_PORTAL_STATUSES:
                return jsonify({"error": f"portal_status must be one of {sorted(VALID_PORTAL_STATUSES)}"}), 400

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

            rinse_vendor = (body.get("rinse_vendor") or "").strip() or None
            org_slug = me.get("organization_slug")
            org_name = me.get("organization_name")

            vendor, vendor_env = rinse_scrape_env_for_organization(
                tenant_oid,
                organization_slug=org_slug,
                organization_name=org_name,
                override_vendor=rinse_vendor,
            )
            base_url = vendor_env.get("RINSE_TICKETS_URL") or ""
            source_url = build_tickets_url_for_portal_status(base_url, portal_status)
            batch_id = str(body.get("source_batch_id") or "").strip() or uuid.uuid4().hex

            extra_env = dict(vendor_env)
            extra_env["RINSE_TICKETS_URL"] = source_url
            extra_env["RINSE_CSV_LAYOUT"] = "portal"
            extra_env["RINSE_ALLOW_EMPTY_EXPORT"] = "1"
            extra_env.setdefault("RINSE_MAX_PAGES", "25")
            extra_env.setdefault("RINSE_PAGE_SETTLE_MS", "2000")
            extra_env.setdefault("RINSE_TABLE_WAIT_MS", "800")

            with tempfile.TemporaryDirectory(prefix="rinse-presence-") as tmp:
                csv_path = Path(tmp) / f"presence-{portal_status}.csv"
                meta_path = Path(str(csv_path) + ".meta.json")
                extra_env["OUTPUT_PORTAL_SCRAPE_META"] = str(meta_path)
                code, stdout, stderr = run_bag_export_csv(csv_path, extra_env=extra_env)
                if code != 0:
                    return jsonify(
                        {
                            "error": "Scrape failed",
                            "exit_code": code,
                            "stdout_tail": (stdout or "")[-4000:],
                            "stderr_tail": (stderr or "")[-4000:],
                            "source_url": source_url,
                            "rinse_vendor": vendor,
                            "scrape_debug": build_presence_scrape_debug(
                                portal_status=portal_status,
                                source_url=source_url,
                                rows=[],
                                scrape_meta=read_portal_scrape_meta(str(meta_path)),
                                exit_code=code,
                            ),
                        }
                    ), 502

                try:
                    rows = parse_presence_rows_from_portal_csv(str(csv_path))
                except Exception as exc:
                    return jsonify(
                        {
                            "error": f"Failed to parse portal CSV: {exc}",
                            "source_url": source_url,
                            "rinse_vendor": vendor,
                        }
                    ), 422

                scrape_meta = read_portal_scrape_meta(str(meta_path))
                scrape_debug = build_presence_scrape_debug(
                    portal_status=portal_status,
                    source_url=source_url,
                    rows=rows,
                    scrape_meta=scrape_meta,
                    exit_code=code,
                )

                ensure_presence_tables(cursor)
                stats = apply_presence_scrape(
                    cursor,
                    tenant_oid,
                    portal_status=portal_status,
                    rows=rows,
                    source_batch_id=batch_id,
                    source_url=source_url,
                    dry_run=dry_run,
                    mark_missing=mark_missing,
                )
                if not dry_run:
                    conn.commit()
                else:
                    conn.rollback()

            stats["rinse_vendor"] = vendor
            stats["stdout_tail"] = (stdout or "")[-2000:]
            stats["scrape_debug"] = scrape_debug
            return jsonify(json_safe_rinse(stats))
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
            cursor.execute(
                """
                SELECT *
                FROM rinse_cleaner_ticket_presence_runs
                WHERE organization_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant_oid, limit),
            )
            runs = cursor.fetchall() or []
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
            return jsonify(json_safe_rinse({"organization_id": tenant_oid, "counts": rows}))
        finally:
            cursor.close()
            conn.close()
