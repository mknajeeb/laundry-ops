"""Admin-only Rinse cleaner-tickets bag export (runs Node Playwright scraper)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, send_file

from backend.rinse_bag_export_runner import diagnose, export_enabled, run_bag_export_csv, scraper_script


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

        base = os.path.join("uploads", "rinse_exports")
        os.makedirs(base, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_name = f"rinse-bag-export-{stamp}.csv"
        out_path = os.path.join(base, out_name)

        code, stdout, stderr = run_bag_export_csv(Path(out_path))
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

        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 1:
            return jsonify(
                {
                    "error": "Scrape finished but CSV was not written.",
                    "stdout_tail": (stdout or "")[-8000:],
                    "stderr_tail": (stderr or "")[-8000:],
                }
            ), 500

        safe = re.sub(r"[^A-Za-z0-9._-]", "_", out_name)
        return send_file(
            out_path,
            mimetype="text/csv",
            as_attachment=True,
            download_name=safe,
        )
