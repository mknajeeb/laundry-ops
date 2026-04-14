"""Admin-only Rinse cleaner-tickets bag export (runs Node Playwright scraper)."""

from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from flask import jsonify, request, send_file

from backend.rinse_bag_export_runner import (
    diagnose,
    export_enabled,
    rinse_import_subprocess_extra_env,
    run_bag_export_csv,
    scraper_script,
)

# uploads/ lives next to backend/ at deploy root (wwwroot), not under backend/ — avoid cwd-relative paths.
_RINSE_EXPORT_ROOT = Path(__file__).resolve().parent.parent


def _rinse_import_after_auth(
    app,
    batch_date: date,
    tenant_oid: int,
    virtual_name: str,
) -> dict:
    """
    Scrape → portal CSV → orders_df → commit draft upload batch.
    Caller must have already verified admin + feature flags (no request auth here).

    Returns dict with keys: ok (bool), status_code (int), body (dict for JSON),
    and on scrape failure optionally exit_code, stdout_tail, stderr_tail.
    """
    from backend.app import commit_draft_upload_batch_from_orders_df
    from backend.db import get_db
    from backend.rinse_portal_csv import portal_csv_to_orders_df

    fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="rinse-portal-")
    os.close(fd)
    path = Path(tmp_path)
    try:
        code, stdout, stderr = run_bag_export_csv(
            path, extra_env=rinse_import_subprocess_extra_env()
        )
    except Exception as e:
        app.logger.exception("rinse import scrape error")
        path.unlink(missing_ok=True)
        return {"ok": False, "status_code": 500, "body": {"error": str(e)}}

    if code != 0:
        app.logger.error(
            "rinse import scrape failed code=%s stderr=%s",
            code,
            (stderr or "")[:4000],
        )
        path.unlink(missing_ok=True)
        body = {
            "error": "Rinse scrape failed.",
            "exit_code": code,
            "stdout_tail": (stdout or "")[-8000:],
            "stderr_tail": (stderr or "")[-8000:],
        }
        return {
            "ok": False,
            "status_code": 500,
            "body": body,
            "exit_code": code,
            "stdout_tail": body["stdout_tail"],
            "stderr_tail": body["stderr_tail"],
        }

    if not path.is_file() or path.stat().st_size < 1:
        path.unlink(missing_ok=True)
        return {
            "ok": False,
            "status_code": 500,
            "body": {
                "error": "Scrape finished but CSV was not written.",
                "stdout_tail": (stdout or "")[-8000:],
                "stderr_tail": (stderr or "")[-8000:],
            },
        }

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
        return {
            "ok": False,
            "status_code": 500,
            "body": {
                "error": (
                    "Rinse import returned no data rows (header only). "
                    "Refresh rinse-auth.json, RINSE_STORAGE_STATE, and RINSE_TICKETS_URL; "
                    "ensure the scraper can expand rows and click Show bag details."
                ),
                "stdout_tail": (stdout or "")[-8000:],
                "stderr_tail": (stderr or "")[-8000:],
            },
        }

    orders_df = None
    try:
        orders_df = portal_csv_to_orders_df(str(path))
    except ValueError as ve:
        return {"ok": False, "status_code": 400, "body": {"error": str(ve)}}
    except Exception as e:
        app.logger.exception("rinse portal csv parse")
        return {"ok": False, "status_code": 500, "body": {"error": str(e)}}
    finally:
        path.unlink(missing_ok=True)

    if orders_df is None or len(orders_df) == 0:
        return {
            "ok": False,
            "status_code": 400,
            "body": {"error": "No orders parsed from Rinse portal CSV."},
        }

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
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
            return {"ok": False, "status_code": 500, "body": {"error": str(e)}}
    finally:
        cursor.close()
        conn.close()

    return {
        "ok": True,
        "status_code": 200,
        "body": {**payload, "summary_rows": len(orders_df), "source": "rinse_portal"},
    }


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
        Synchronous import (can exceed HTTP proxy timeouts). Prefer POST …/jobs + poll for production.
        """
        from backend.app import get_db, parse_date_value, require_admin, user_org_id

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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        virtual_name = f"rinse-portal-import-{stamp}.csv"

        res = _rinse_import_after_auth(app, batch_date, tenant_oid, virtual_name)
        return jsonify(res["body"]), res["status_code"]

    @app.route("/admin/rinse/import-upload-batch/jobs", methods=["POST"])
    def rinse_import_upload_batch_job_start():
        """
        Start import in a background thread; poll GET …/jobs/<id> until succeeded or failed.
        Avoids browser/proxy timeouts while Playwright runs (can be many minutes).
        """
        from backend.app import get_db, parse_date_value, require_admin, user_org_id
        from backend.db import get_db as db_conn
        from backend.rinse_import_jobs import (
            ensure_rinse_import_jobs_table,
            insert_rinse_import_job,
            update_rinse_import_job,
        )

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
            user_id = int(me["user_id"])
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

        job_id = str(uuid.uuid4())
        virtual_name = f"rinse-portal-import-{job_id}.csv"

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            ensure_rinse_import_jobs_table(cursor)
            insert_rinse_import_job(cursor, job_id, tenant_oid, user_id, batch_date)
            conn.commit()
        except Exception as e:
            conn.rollback()
            app.logger.exception("rinse import job insert")
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

        def worker():
            with app.app_context():
                try:
                    conn_run = db_conn()
                    try:
                        c2 = conn_run.cursor(dictionary=True)
                        try:
                            ensure_rinse_import_jobs_table(c2)
                            update_rinse_import_job(
                                c2,
                                job_id,
                                tenant_oid,
                                status="running",
                                progress_note="Scraping Rinse (Playwright)…",
                            )
                            conn_run.commit()
                        finally:
                            c2.close()
                    finally:
                        conn_run.close()

                    res = _rinse_import_after_auth(app, batch_date, tenant_oid, virtual_name)

                    conn_done = db_conn()
                    try:
                        c3 = conn_done.cursor(dictionary=True)
                        try:
                            if res.get("ok"):
                                update_rinse_import_job(
                                    c3,
                                    job_id,
                                    tenant_oid,
                                    status="succeeded",
                                    progress_note="Complete",
                                    result_json=res["body"],
                                    http_status=200,
                                )
                            else:
                                body = res.get("body") or {}
                                err_txt = str(body.get("error") or body)[:4000]
                                update_rinse_import_job(
                                    c3,
                                    job_id,
                                    tenant_oid,
                                    status="failed",
                                    progress_note="Failed",
                                    error_summary=err_txt,
                                    http_status=int(res.get("status_code") or 500),
                                    exit_code=res.get("exit_code"),
                                    stdout_tail=res.get("stdout_tail"),
                                    stderr_tail=res.get("stderr_tail"),
                                    result_json=body if isinstance(body, dict) else None,
                                )
                            conn_done.commit()
                        finally:
                            c3.close()
                    finally:
                        conn_done.close()
                except Exception as e:
                    app.logger.exception("rinse import job worker")
                    try:
                        conn_err = db_conn()
                        try:
                            c4 = conn_err.cursor(dictionary=True)
                            try:
                                ensure_rinse_import_jobs_table(c4)
                                update_rinse_import_job(
                                    c4,
                                    job_id,
                                    tenant_oid,
                                    status="failed",
                                    progress_note="Worker error",
                                    error_summary=str(e)[:4000],
                                    http_status=500,
                                )
                                conn_err.commit()
                            finally:
                                c4.close()
                        finally:
                            conn_err.close()
                    except Exception:
                        app.logger.exception("rinse import job worker cleanup")

        threading.Thread(target=worker, name=f"rinse-import-{job_id[:8]}", daemon=True).start()

        return (
            jsonify(
                {
                    "job_id": job_id,
                    "status": "queued",
                    "batch_date": batch_date.isoformat(),
                    "poll_url": f"/admin/rinse/import-upload-batch/jobs/{job_id}",
                }
            ),
            202,
        )

    @app.route("/admin/rinse/import-upload-batch/jobs/<job_id>", methods=["GET"])
    def rinse_import_upload_batch_job_status(job_id: str):
        from backend.app import get_db, require_admin, user_org_id
        from backend.rinse_import_jobs import ensure_rinse_import_jobs_table, fetch_rinse_import_job

        if not export_enabled():
            return jsonify({"error": "Rinse import is disabled."}), 503

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin(cursor)
            if err is not None:
                return err, code
            tenant_oid = user_org_id(me)
            ensure_rinse_import_jobs_table(cursor)
            row = fetch_rinse_import_job(cursor, job_id, tenant_oid)
        finally:
            cursor.close()
            conn.close()

        if not row:
            return jsonify({"error": "Job not found."}), 404

        out = {
            "job_id": row["id"],
            "status": row["status"],
            "batch_date": row.get("batch_date"),
            "progress_note": row.get("progress_note"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        if row.get("result"):
            out["result"] = row["result"]
        if row["status"] == "failed":
            out["error"] = row.get("error_summary")
            out["http_status"] = row.get("http_status")
            out["exit_code"] = row.get("exit_code")
            if row.get("stdout_tail"):
                out["stdout_tail"] = row["stdout_tail"]
            if row.get("stderr_tail"):
                out["stderr_tail"] = row["stderr_tail"]
        return jsonify(out)
