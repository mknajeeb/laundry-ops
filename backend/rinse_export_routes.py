"""Admin-only Rinse cleaner-tickets bag export (runs Node Playwright scraper)."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from flask import jsonify, request, send_file

from backend.rinse_bag_export_runner import diagnose, export_enabled, run_bag_export_csv, scraper_script

# uploads/ lives next to backend/ at deploy root (wwwroot), not under backend/ — avoid cwd-relative paths.
_RINSE_EXPORT_ROOT = Path(__file__).resolve().parent.parent


def register_rinse_export_routes(app):
    @app.route("/admin/rinse/bag-export/config", methods=["GET"])
    def rinse_bag_export_config():
        from backend.app import get_db, require_admin

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin(cursor)
            if err is not None:
                return err, code
            d = diagnose()
            ready = bool(
                d["enabled"] and d["scraper_script_exists"] and d["node_found"]
            )
            msg = []
            if not d["enabled"]:
                msg.append("Set RINSE_BAG_EXPORT_ENABLED=1 on the API server.")
            if not d["scraper_script_exists"]:
                msg.append("Deploy the repo including scripts/rinse-cleanertickets/scrape.mjs.")
            if not d["node_found"]:
                msg.append("Install Node.js on the API host or set NODE_BIN.")
            return jsonify(
                {
                    "ready": ready,
                    **d,
                    "hint": " ".join(msg) if msg else "Ready to run export.",
                }
            )
        finally:
            cursor.close()
            conn.close()

    @app.route("/admin/rinse/bag-export", methods=["POST"])
    def rinse_bag_export_run():
        from backend.app import get_db, require_admin

        if not export_enabled():
            return jsonify(
                {
                    "error": "Rinse bag export is disabled. Set RINSE_BAG_EXPORT_ENABLED=1 on the server.",
                }
            ), 503

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin(cursor)
            if err is not None:
                return err, code
        finally:
            cursor.close()
            conn.close()

        d = diagnose()
        if not d["scraper_script_exists"]:
            return jsonify({"error": "Scraper script not deployed."}), 503
        if not d["node_found"]:
            return jsonify({"error": "Node.js not found on server (set NODE_BIN)."}), 503

        export_dir = _RINSE_EXPORT_ROOT / "uploads" / "rinse_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_name = f"rinse-bag-export-{stamp}.csv"
        out_path = export_dir / out_name

        try:
            code, stdout, stderr = run_bag_export_csv(out_path)
        except Exception as e:
            app.logger.exception("rinse bag export subprocess error")
            return jsonify({"error": str(e)}), 500

        if code != 0:
            app.logger.error("rinse bag export failed code=%s stderr=%s", code, stderr[:4000])
            return jsonify(
                {
                    "error": "Rinse scrape failed.",
                    "exit_code": code,
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        if not out_path.is_file() or out_path.stat().st_size < 1:
            return jsonify(
                {
                    "error": "Scrape finished but CSV was not written.",
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        nonempty_lines: list[str] = []
        try:
            with out_path.open("r", encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        nonempty_lines.append(s)
        except OSError:
            nonempty_lines = []
        if len(nonempty_lines) <= 1:
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            return jsonify(
                {
                    "error": (
                        "Rinse export returned no data rows (only the CSV header). "
                        "Usually: rinse-auth.json missing/expired or wrong RINSE_STORAGE_STATE path on the API, "
                        "RINSE_TICKETS_URL does not match your logged-in Cleaner Tickets filter, or Rinse changed "
                        "their HTML (update SELECTORS.bodyRows in scripts/rinse-cleanertickets/scrape.mjs). "
                        "Re-run save-session locally, re-upload rinse-auth.json, restart the API, and try again."
                    ),
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        safe = re.sub(r"[^A-Za-z0-9._-]", "_", out_name)
        return send_file(
            out_path.resolve(),
            mimetype="text/csv",
            as_attachment=True,
            download_name=safe,
        )

    @app.route("/admin/rinse/import-upload-batch", methods=["POST"])
    def rinse_import_upload_batch():
        """
        Run portal-layout Rinse scrape and insert rows into the current upload batch pipeline
        (same DB path as /upload_orders) — no CSV download/upload round trip.
        """
        from backend.app import (
            commit_draft_upload_batch_from_orders_df,
            get_db,
            parse_date_value,
            require_admin,
            user_org_id,
        )
        from backend.rinse_portal_csv import portal_csv_to_orders_df

        if not export_enabled():
            return jsonify(
                {
                    "error": "Rinse import is disabled. Set RINSE_BAG_EXPORT_ENABLED=1 on the server.",
                }
            ), 503

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin(cursor)
            if err is not None:
                return err, code
            tenant_oid = user_org_id(me)
        finally:
            cursor.close()
            conn.close()

        d = diagnose()
        if not d["scraper_script_exists"]:
            return jsonify({"error": "Scraper script not deployed."}), 503
        if not d["node_found"]:
            return jsonify({"error": "Node.js not found on server (set NODE_BIN)."}), 503

        data = request.get_json(silent=True) or {}
        batch_raw = data.get("batch_date")
        batch_date = parse_date_value(batch_raw) if batch_raw else date.today()

        fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="rinse-portal-")
        os.close(fd)
        path = Path(tmp_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        virtual_name = f"rinse-portal-import-{stamp}.csv"

        try:
            code, stdout, stderr = run_bag_export_csv(
                path, extra_env={"RINSE_CSV_LAYOUT": "portal"}
            )
        except Exception as e:
            app.logger.exception("rinse import scrape error")
            path.unlink(missing_ok=True)
            return jsonify({"error": str(e)}), 500

        if code != 0:
            app.logger.error("rinse import scrape failed code=%s stderr=%s", code, stderr[:4000])
            path.unlink(missing_ok=True)
            return jsonify(
                {
                    "error": "Rinse scrape failed.",
                    "exit_code": code,
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        if not path.is_file() or path.stat().st_size < 1:
            path.unlink(missing_ok=True)
            return jsonify(
                {
                    "error": "Scrape finished but CSV was not written.",
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        nonempty_lines: list[str] = []
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        nonempty_lines.append(s)
        except OSError:
            nonempty_lines = []
        if len(nonempty_lines) <= 1:
            path.unlink(missing_ok=True)
            return jsonify(
                {
                    "error": (
                        "Rinse import returned no data rows (header only). "
                        "Refresh rinse-auth.json, RINSE_STORAGE_STATE, and RINSE_TICKETS_URL; "
                        "ensure the scraper can expand rows and click Show bag details."
                    ),
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        orders_df = None
        try:
            orders_df = portal_csv_to_orders_df(str(path))
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            app.logger.exception("rinse portal csv parse")
            return jsonify({"error": str(e)}), 500
        finally:
            path.unlink(missing_ok=True)

        if orders_df is None or len(orders_df) == 0:
            return jsonify({"error": "No orders parsed from Rinse portal CSV."}), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin(cursor)
            if err is not None:
                return err, code
            tenant_oid = user_org_id(me)
            try:
                payload = commit_draft_upload_batch_from_orders_df(
                    conn,
                    cursor,
                    tenant_oid,
                    batch_date,
                    orders_df,
                    virtual_name,
                )
            except Exception as e:
                conn.rollback()
                app.logger.exception("rinse import commit")
                return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

        return jsonify({**payload, "summary_rows": len(orders_df), "source": "rinse_portal"})
