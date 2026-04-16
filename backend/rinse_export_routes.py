"""Admin-only Rinse cleaner-tickets bag export (runs Node Playwright scraper)."""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from backend.rinse_bag_export_runner import (
    diagnose,
    export_enabled,
    rinse_import_subprocess_extra_env,
    RINSE_SCRAPE_EXIT_CANCELLED,
    run_bag_export_csv,
    scraper_script,
)

# uploads/ lives next to backend/ at deploy root (wwwroot), not under backend/ — avoid cwd-relative paths.
_RINSE_EXPORT_ROOT = Path(__file__).resolve().parent.parent


def _json_rinse_export_disabled(*, bag_export: bool = False):
    """503 with diagnostics so operators can tell missing env vs bad value vs wrong host."""
    dg = diagnose()
    if bag_export:
        err = "Rinse bag export is disabled (RINSE_BAG_EXPORT_ENABLED not on for this worker)."
    else:
        err = "Rinse import is disabled (RINSE_BAG_EXPORT_ENABLED not on for this worker)."
    return (
        jsonify(
            {
                "error": err,
                "rinse_export_env_key_present": dg.get("rinse_export_env_key_present"),
                "rinse_export_env_value_len": dg.get("rinse_export_env_value_len"),
            }
        ),
        503,
    )


def _rinse_job_created_utc(row_created: datetime | str | None):
    """Parse job created_at / updated_at from API row (iso string from fetch) or raw datetime."""
    if row_created is None:
        return None
    if isinstance(row_created, datetime):
        dt = row_created
    else:
        raw = str(row_created).strip()
        t = raw.replace(" ", "T", 1)
        if "T" in t and "+" not in t[t.find("T") :] and "Z" not in t:
            t = t + "+00:00"
        t = t.replace("Z", "+00:00")
        dt = None
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            candidates = []
            for c in (raw, raw.replace("T", " ")):
                c = c.strip()
                if c and c not in candidates:
                    candidates.append(c)
            for c in candidates:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(c[:26], fmt)
                        break
                    except ValueError:
                        continue
                if dt is not None:
                    break
            if dt is None:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rinse_import_heartbeat_sec() -> int:
    """Seconds between DB heartbeats while scraping; 0 disables (stale logic uses scrape timeout)."""
    hb_raw = (os.getenv("RINSE_IMPORT_HEARTBEAT_SEC") or "60").strip()
    if hb_raw == "0":
        return 0
    return max(20, min(300, int(hb_raw or "60")))


def _fail_stale_rinse_job_if_needed(job_id: str, tenant_oid: int, row: dict) -> dict:
    """
    Mark dead jobs failed so the UI stops polling forever.

    - queued: worker should start within ~minutes; if not, treat as lost.
    - running: the worker bumps updated_at on a heartbeat while Playwright runs. If the API
      restarts, heartbeats stop — treat as stale after min(heartbeat window, scrape timeout + grace).
      If heartbeats are disabled (RINSE_IMPORT_HEARTBEAT_SEC=0), use scrape timeout + grace only.
    """
    status = row.get("status")
    if status not in ("queued", "running"):
        return row
    now = datetime.now(timezone.utc)
    from backend.db import get_db as db_conn
    from backend.rinse_import_jobs import ensure_rinse_import_jobs_table, fetch_rinse_import_job, update_rinse_import_job

    stale = False
    msg = ""
    if status == "queued":
        created_utc = _rinse_job_created_utc(row.get("created_at"))
        if created_utc is not None:
            qmax = int(os.getenv("RINSE_IMPORT_QUEUED_STALE_SEC", "600"))
            if (now - created_utc).total_seconds() > qmax:
                stale = True
                msg = (
                    f"Job stayed queued longer than {qmax}s (worker never updated it). "
                    "The API may have restarted or the job thread did not start. Start a new import."
                )
    else:
        ref = _rinse_job_created_utc(row.get("updated_at")) or _rinse_job_created_utc(row.get("created_at"))
        if ref is None:
            pass
        else:
            age = (now - ref).total_seconds()
            if age < -120:
                stale = True
                msg = (
                    "Job timestamps are far ahead of server time (clock skew). "
                    "Marking failed so the UI can recover; fix DB/app clock alignment."
                )
            elif age < 0:
                age = 0.0
            hb_sec = _rinse_import_heartbeat_sec()
            scrape_t = int(os.getenv("RINSE_SCRAPE_TIMEOUT_SEC", "900"))
            grace = int(os.getenv("RINSE_IMPORT_RUNNING_GRACE_SEC", "300"))
            abs_silence_max = int(os.getenv("RINSE_IMPORT_JOB_STALE_SEC", str(scrape_t + grace)))
            if hb_sec > 0:
                mult = max(3, int(os.getenv("RINSE_IMPORT_HEARTBEAT_MISS_MULT") or "3"))
                cap_hb = int(os.getenv("RINSE_IMPORT_NO_HEARTBEAT_STALE_SEC", str(hb_sec * mult)))
                # Never wait longer than scrape timeout silence (older servers / HB misconfig).
                cap = min(cap_hb, abs_silence_max)
                if age > cap:
                    stale = True
                    msg = (
                        f"No DB update for ~{cap:.0f}s while status was running (heartbeats should refresh every "
                        f"~{hb_sec:.0f}s; worker likely died on API restart or DB updates failed). "
                        "Enable Always On, avoid deploys during import, then start a new import."
                    )
            else:
                cap = abs_silence_max
                if age > cap:
                    stale = True
                    msg = (
                        f"No completion within {cap}s after this job started running (heartbeat disabled; "
                        "scrape timeout + grace). Azure restarts kill the worker—stabilize the app or enable "
                        "heartbeats (default RINSE_IMPORT_HEARTBEAT_SEC=60)."
                    )
    if not stale:
        return row
    row2 = None
    conn = db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            ensure_rinse_import_jobs_table(cur)
            row_now = fetch_rinse_import_job(cur, job_id, tenant_oid)
            if not row_now or row_now.get("status") not in ("queued", "running"):
                return row_now or row
            update_rinse_import_job(
                cur,
                job_id,
                tenant_oid,
                status="failed",
                progress_note="Stale job (server restarted or hung)",
                error_summary=msg[:4000],
                http_status=500,
            )
            conn.commit()
            row2 = fetch_rinse_import_job(cur, job_id, tenant_oid)
        finally:
            cur.close()
    finally:
        conn.close()
    ref_log = _rinse_job_created_utc(row.get("updated_at" if status == "running" else "created_at"))
    age_s = (now - ref_log).total_seconds() if ref_log else -1
    current_app.logger.warning(
        "rinse import job %s marked stale (status=%s, ~%.0fs since ref)", job_id[:8], status, age_s
    )
    return row2 or row


def _parse_rinse_import_job_page_options(data: dict) -> dict[str, str]:
    """Optional JSON keys page_start / max_pages → RINSE_PAGE_START / RINSE_MAX_PAGES for one job only."""
    out: dict[str, str] = {}
    ps = data.get("page_start")
    if ps is not None and str(ps).strip() != "":
        try:
            out["RINSE_PAGE_START"] = str(max(1, min(500, int(ps))))
        except (TypeError, ValueError):
            pass
    mp = data.get("max_pages")
    if mp is not None and str(mp).strip() != "":
        try:
            out["RINSE_MAX_PAGES"] = str(max(1, min(500, int(mp))))
        except (TypeError, ValueError):
            pass
    return out


def _parse_rinse_import_job_options(data: dict) -> tuple[dict[str, str], int | None, int]:
    """
    Optional sequential mode: JSON sequential_chunk_pages (list pages per Node run, usually 1).
    When set, body max_pages is ignored for chunk sizing (each subprocess gets RINSE_MAX_PAGES=chunk).
    max_sequential_chunks caps how many subprocesses (default 500).
    """
    seq: int | None = None
    raw = data.get("sequential_chunk_pages")
    if raw is not None and str(raw).strip() != "":
        try:
            v = int(raw)
            if v >= 1:
                seq = min(50, max(1, v))
        except (TypeError, ValueError):
            pass
    max_seq = 500
    mc = data.get("max_sequential_chunks")
    if mc is not None and str(mc).strip() != "":
        try:
            max_seq = max(1, min(500, int(mc)))
        except (TypeError, ValueError):
            max_seq = 500
    env = _parse_rinse_import_job_page_options(data)
    if seq is not None:
        env.pop("RINSE_MAX_PAGES", None)
    return env, seq, max_seq


def _rinse_import_run_single_scrape(
    app,
    merged_env: dict[str, str],
    scrape_progress,
    should_cancel,
):
    """
    One Node scrape with merged_env → parse portal CSV to orders_df.
    Returns dict with kind: cancelled | error | no_data | ok.
    """
    from backend.rinse_portal_csv import portal_csv_to_orders_df

    fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="rinse-portal-")
    os.close(fd)
    path = Path(tmp_path)
    try:
        code, stdout, stderr = run_bag_export_csv(
            path,
            extra_env=merged_env,
            progress_callback=scrape_progress,
            should_cancel=should_cancel,
        )
    except Exception as e:
        app.logger.exception("rinse import scrape error")
        path.unlink(missing_ok=True)
        return {"kind": "error", "body": {"error": str(e)}}

    stout = stdout or ""
    sterr = stderr or ""

    if code == RINSE_SCRAPE_EXIT_CANCELLED:
        path.unlink(missing_ok=True)
        return {"kind": "cancelled", "stdout": stout, "stderr": sterr}

    if should_cancel and should_cancel():
        path.unlink(missing_ok=True)
        return {"kind": "cancelled", "stdout": stout, "stderr": sterr}

    if code != 0:
        path.unlink(missing_ok=True)
        if int(code) == 2:
            return {"kind": "no_data", "exit_code": 2, "stdout": stout, "stderr": sterr}
        app.logger.error(
            "rinse import scrape failed code=%s stderr=%s",
            code,
            (sterr or "")[:4000],
        )
        body = {
            "error": "Rinse scrape failed.",
            "exit_code": code,
            "stdout_tail": stout[-8000:],
            "stderr_tail": sterr[-8000:],
        }
        return {
            "kind": "error",
            "body": body,
            "exit_code": code,
            "http_status": 500,
            "stdout": stout,
            "stderr": sterr,
        }

    if not path.is_file() or path.stat().st_size < 1:
        path.unlink(missing_ok=True)
        return {"kind": "no_data", "exit_code": int(code), "stdout": stout, "stderr": sterr}

    if scrape_progress:
        try:
            scrape_progress(
                stout + "\n→ Parsing portal CSV and building order rows…\n",
                sterr,
            )
        except Exception:
            pass

    if should_cancel and should_cancel():
        path.unlink(missing_ok=True)
        return {"kind": "cancelled", "stdout": stout, "stderr": sterr}

    nonempty_lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s:
                    nonempty_lines.append(s)
    except OSError:
        nonempty_lines = []

    if should_cancel and should_cancel():
        path.unlink(missing_ok=True)
        return {"kind": "cancelled", "stdout": stout, "stderr": sterr}

    if len(nonempty_lines) <= 1:
        path.unlink(missing_ok=True)
        return {"kind": "no_data", "exit_code": 0, "stdout": stout, "stderr": sterr}

    orders_df = None
    try:
        orders_df = portal_csv_to_orders_df(str(path))
    except ValueError as ve:
        return {
            "kind": "error",
            "body": {"error": str(ve)},
            "http_status": 400,
            "stdout": stout,
            "stderr": sterr,
        }
    except Exception as e:
        app.logger.exception("rinse portal csv parse")
        return {
            "kind": "error",
            "body": {"error": str(e)},
            "http_status": 500,
            "stdout": stout,
            "stderr": sterr,
        }
    finally:
        path.unlink(missing_ok=True)

    if should_cancel and should_cancel():
        return {"kind": "cancelled", "stdout": stout, "stderr": sterr}

    if orders_df is None or len(orders_df) == 0:
        return {"kind": "no_data", "exit_code": 0, "stdout": stout, "stderr": sterr}

    return {"kind": "ok", "orders_df": orders_df, "stdout": stout, "stderr": sterr}


def _rinse_import_after_auth(
    app,
    batch_date: date,
    tenant_oid: int,
    virtual_name: str,
    scrape_progress=None,
    should_cancel=None,
    extra_scrape_env: dict | None = None,
    sequential_chunk_pages: int | None = None,
    max_sequential_chunks: int = 500,
):
    """
    Scrape → portal CSV → orders_df → commit draft upload batch.
    Caller must have already verified admin + feature flags (no request auth here).

    scrape_progress: optional callable(stdout_tail: str, stderr_tail: str) for live job log (import jobs).
    should_cancel: optional callable() -> bool; checked between major steps and passed to the scraper.

    If sequential_chunk_pages is set, runs that many list pages per subprocess, one subprocess after
    another (same job), merges DataFrames, then one draft commit — avoids losing rows to per-chunk commits.

    Returns dict with keys: ok (bool), status_code (int), body (dict for JSON),
    cancelled (bool) when user stopped the job, and on scrape failure optionally exit_code, stdout_tail, stderr_tail.
    """
    from backend.app import commit_draft_upload_batch_from_orders_df
    from backend.db import get_db

    merged_base = rinse_import_subprocess_extra_env()
    if extra_scrape_env:
        for _k, _v in extra_scrape_env.items():
            if _v is not None and str(_v).strip() != "":
                merged_base[str(_k)] = str(_v).strip()

    if sequential_chunk_pages is None:
        one = _rinse_import_run_single_scrape(
            app,
            merged_base,
            scrape_progress,
            should_cancel,
        )
        return _rinse_import_finish_from_one_round(
            app,
            batch_date,
            tenant_oid,
            virtual_name,
            scrape_progress,
            should_cancel,
            one,
        )

    merged_base.pop("RINSE_MAX_PAGES", None)
    try:
        current = int(merged_base.get("RINSE_PAGE_START", "1"))
    except ValueError:
        current = 1
    current = max(1, min(500, current))

    import pandas as pd

    dfs: list = []
    chunks_run = 0
    last_stdout, last_stderr = "", ""
    while chunks_run < max_sequential_chunks:
        if should_cancel and should_cancel():
            return {
                "ok": False,
                "cancelled": True,
                "status_code": 200,
                "body": {"cancelled": True, "message": "Rinse import stopped between sequential chunks."},
                "stdout_tail": last_stdout[-8000:],
                "stderr_tail": last_stderr[-8000:],
            }

        merged = dict(merged_base)
        merged["RINSE_PAGE_START"] = str(current)
        merged["RINSE_MAX_PAGES"] = str(sequential_chunk_pages)

        if scrape_progress:
            try:
                scrape_progress(
                    last_stdout
                    + f"\n→ Sequential chunk {chunks_run + 1}/{max_sequential_chunks}: "
                    f"list pages starting at {current}, up to {sequential_chunk_pages} page(s) this run…\n",
                    last_stderr,
                )
            except Exception:
                pass

        one = _rinse_import_run_single_scrape(app, merged, scrape_progress, should_cancel)
        last_stdout = one.get("stdout") or last_stdout
        last_stderr = one.get("stderr") or last_stderr

        if one["kind"] == "cancelled":
            return {
                "ok": False,
                "cancelled": True,
                "status_code": 200,
                "body": {"cancelled": True, "message": "Rinse import stopped before or during scrape."},
                "stdout_tail": (last_stdout or "")[-8000:],
                "stderr_tail": (last_stderr or "")[-8000:],
            }
        if one["kind"] == "error":
            body = one.get("body") or {"error": "Rinse import failed."}
            hs = int(one.get("http_status") or 500)
            return {
                "ok": False,
                "status_code": hs,
                "body": body,
                "exit_code": one.get("exit_code"),
                "stdout_tail": (last_stdout or "")[-8000:],
                "stderr_tail": (last_stderr or "")[-8000:],
            }
        if one["kind"] == "no_data":
            if chunks_run == 0:
                return {
                    "ok": False,
                    "status_code": 500,
                    "body": {
                        "error": (
                            "Rinse import returned no data rows on the first sequential chunk. "
                            "Refresh rinse-auth.json, RINSE_STORAGE_STATE, and RINSE_TICKETS_URL; "
                            "ensure the scraper can expand rows and click Show bag details."
                        ),
                        "stdout_tail": (last_stdout or "")[-8000:],
                        "stderr_tail": (last_stderr or "")[-8000:],
                    },
                }
            break
        if one["kind"] == "ok":
            dfs.append(one["orders_df"])
            current += sequential_chunk_pages
            chunks_run += 1
            continue

    if not dfs:
        return {
            "ok": False,
            "status_code": 500,
            "body": {"error": "Sequential Rinse import produced no order rows."},
        }

    orders_df = pd.concat(dfs, ignore_index=True)

    if scrape_progress:
        try:
            scrape_progress(
                (last_stdout or "")
                + f"\n→ Merged {chunks_run} sequential chunk(s) → {len(orders_df)} row(s). Saving to upload draft batch…\n",
                last_stderr or "",
            )
        except Exception:
            pass

    if should_cancel and should_cancel():
        return {
            "ok": False,
            "cancelled": True,
            "status_code": 200,
            "body": {"cancelled": True, "message": "Rinse import stopped before saving the draft batch."},
            "stdout_tail": (last_stdout or "")[-8000:],
            "stderr_tail": (last_stderr or "")[-8000:],
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
        "body": {
            **payload,
            "summary_rows": len(orders_df),
            "source": "rinse_portal",
            "sequential_chunks": chunks_run,
            "sequential_chunk_pages": sequential_chunk_pages,
        },
    }


def _rinse_import_finish_from_one_round(
    app,
    batch_date: date,
    tenant_oid: int,
    virtual_name: str,
    scrape_progress,
    should_cancel,
    one: dict,
):
    """Shared tail: commit draft from a single _rinse_import_run_single_scrape result."""
    from backend.app import commit_draft_upload_batch_from_orders_df
    from backend.db import get_db

    if one["kind"] == "cancelled":
        return {
            "ok": False,
            "cancelled": True,
            "status_code": 200,
            "body": {"cancelled": True, "message": "Rinse import stopped before or during scrape."},
            "stdout_tail": (one.get("stdout") or "")[-8000:],
            "stderr_tail": (one.get("stderr") or "")[-8000:],
        }
    if one["kind"] == "error":
        body = one.get("body") or {"error": "Rinse import failed."}
        hs = int(one.get("http_status") or 500)
        return {
            "ok": False,
            "status_code": hs,
            "body": body if isinstance(body, dict) else {"error": str(body)},
            "exit_code": one.get("exit_code"),
            "stdout_tail": (one.get("stdout") or "")[-8000:],
            "stderr_tail": (one.get("stderr") or "")[-8000:],
        }
    if one["kind"] == "no_data":
        ec = int(one.get("exit_code") or 0)
        return {
            "ok": False,
            "status_code": 500,
            "body": {
                "error": (
                    "Rinse import returned no data rows (header only). "
                    "Refresh rinse-auth.json, RINSE_STORAGE_STATE, and RINSE_TICKETS_URL; "
                    "ensure the scraper can expand rows and click Show bag details."
                ),
                "exit_code": ec,
                "stdout_tail": (one.get("stdout") or "")[-8000:],
                "stderr_tail": (one.get("stderr") or "")[-8000:],
            },
        }

    orders_df = one["orders_df"]
    if scrape_progress:
        try:
            scrape_progress(
                (one.get("stdout") or "") + "\n→ Saving to upload draft batch…\n",
                one.get("stderr") or "",
            )
        except Exception:
            pass

    if should_cancel and should_cancel():
        return {
            "ok": False,
            "cancelled": True,
            "status_code": 200,
            "body": {"cancelled": True, "message": "Rinse import stopped before saving the draft batch."},
            "stdout_tail": (one.get("stdout") or "")[-8000:],
            "stderr_tail": (one.get("stderr") or "")[-8000:],
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
        from backend.app import get_db, require_admin_or_perm

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin_or_perm(conn, cursor, "upload.create")
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
            return _json_rinse_export_disabled(bag_export=True)

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
        from backend.app import get_db, parse_date_value, require_admin_or_perm, user_org_id

        if not export_enabled():
            return _json_rinse_export_disabled(bag_export=False)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin_or_perm(conn, cursor, "upload.create")
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

        page_opts, seq_pages, max_seq = _parse_rinse_import_job_options(data)
        res = _rinse_import_after_auth(
            app,
            batch_date,
            tenant_oid,
            virtual_name,
            extra_scrape_env=page_opts or None,
            sequential_chunk_pages=seq_pages,
            max_sequential_chunks=max_seq,
        )
        return jsonify(res["body"]), res["status_code"]

    @app.route("/admin/rinse/import-upload-batch/jobs", methods=["POST"])
    def rinse_import_upload_batch_job_start():
        """
        Start import in a background thread; poll GET …/jobs/<id> until succeeded or failed.
        Avoids browser/proxy timeouts while Playwright runs (can be many minutes).
        """
        from backend.app import get_db, parse_date_value, require_admin_or_perm, user_org_id
        from backend.db import get_db as db_conn
        from backend.rinse_import_jobs import (
            ensure_rinse_import_jobs_table,
            fetch_rinse_import_job,
            insert_rinse_import_job,
            update_rinse_import_job,
        )

        if not export_enabled():
            return _json_rinse_export_disabled(bag_export=False)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin_or_perm(conn, cursor, "upload.create")
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
        job_page_env, job_seq_pages, job_max_seq = _parse_rinse_import_job_options(data)

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
                hb_sec = _rinse_import_heartbeat_sec()
                hb_stop = threading.Event()

                def heartbeat_loop():
                    while not hb_stop.wait(hb_sec):
                        try:
                            conn_h = db_conn()
                            try:
                                ch = conn_h.cursor(dictionary=True)
                                try:
                                    ensure_rinse_import_jobs_table(ch)
                                    row_hb = fetch_rinse_import_job(ch, job_id, tenant_oid)
                                    hb_note = (
                                        "Stop requested — halting scrape…"
                                        if row_hb and row_hb.get("cancel_requested_at")
                                        else "Scraping Rinse (Playwright)…"
                                    )
                                    update_rinse_import_job(
                                        ch,
                                        job_id,
                                        tenant_oid,
                                        status="running",
                                        progress_note=hb_note,
                                    )
                                    conn_h.commit()
                                finally:
                                    ch.close()
                            finally:
                                conn_h.close()
                        except Exception:
                            app.logger.warning("rinse import heartbeat failed", exc_info=True)

                hb_thread: threading.Thread | None = None
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

                    if hb_sec > 0:
                        hb_thread = threading.Thread(
                            target=heartbeat_loop,
                            name=f"rinse-hb-{job_id[:8]}",
                            daemon=True,
                        )
                        hb_thread.start()

                    # Cancel must be DB-backed (other Gunicorn workers handle POST /cancel), but a full
                    # fetch on every scrape poll (~5/s) starves MySQL and slows Playwright badly — cache it.
                    # Default 0.55s: fast enough that Stop feels responsive; still << scrape poll frequency.
                    _cancel_poll_s = max(
                        0.35,
                        min(5.0, float(os.getenv("RINSE_IMPORT_CANCEL_POLL_SEC", "0.55"))),
                    )
                    _cancel_cache: dict[str, float | bool] = {"t": -1e9, "v": False}

                    def import_job_cancel_requested() -> bool:
                        now = time.monotonic()
                        if now - float(_cancel_cache["t"]) < _cancel_poll_s:
                            return bool(_cancel_cache["v"])
                        _cancel_cache["t"] = now
                        try:
                            conn_q = db_conn()
                            try:
                                cq = conn_q.cursor(dictionary=True)
                                try:
                                    ensure_rinse_import_jobs_table(cq)
                                    row_q = fetch_rinse_import_job(cq, job_id, tenant_oid)
                                    _cancel_cache["v"] = bool(row_q and row_q.get("cancel_requested_at"))
                                finally:
                                    cq.close()
                            finally:
                                conn_q.close()
                        except Exception:
                            pass
                        return bool(_cancel_cache["v"])

                    # Writing full stdout_tail to MySQL every ~1.25s is heavy; progress_note carries the
                    # latest line for the UI counter. Throttle tail blobs (RINSE_IMPORT_STDOUT_DB_SEC, 0=always).
                    try:
                        _stdout_db_sec = float(os.getenv("RINSE_IMPORT_STDOUT_DB_SEC", "8"))
                    except ValueError:
                        _stdout_db_sec = 8.0
                    _stdout_db_sec = max(0.0, min(120.0, _stdout_db_sec))
                    _last_stdout_db_at = [float("-inf")]

                    def push_scrape_progress(so_tail: str, se_tail: str) -> None:
                        try:
                            cancel_req = import_job_cancel_requested()
                            conn_p = db_conn()
                            try:
                                cp = conn_p.cursor(dictionary=True)
                                try:
                                    ensure_rinse_import_jobs_table(cp)
                                    if cancel_req:
                                        note = "Stop requested — halting scrape…"
                                    else:
                                        note = "Scraping Rinse (Playwright)…"
                                        for ln in (so_tail or "").splitlines():
                                            t = ln.strip()
                                            if t:
                                                note = t[:120]
                                    now = time.monotonic()
                                    write_tails = _stdout_db_sec <= 0 or (
                                        now - _last_stdout_db_at[0] >= _stdout_db_sec
                                    )
                                    if write_tails:
                                        _last_stdout_db_at[0] = now
                                    if write_tails:
                                        update_rinse_import_job(
                                            cp,
                                            job_id,
                                            tenant_oid,
                                            status="running",
                                            progress_note=note,
                                            stdout_tail=(so_tail or "")[-65000:],
                                            stderr_tail=(se_tail or "")[-8000:],
                                        )
                                    else:
                                        update_rinse_import_job(
                                            cp,
                                            job_id,
                                            tenant_oid,
                                            status="running",
                                            progress_note=note,
                                        )
                                    conn_p.commit()
                                finally:
                                    cp.close()
                            finally:
                                conn_p.close()
                        except Exception:
                            app.logger.warning("rinse import progress push failed", exc_info=True)

                    res = _rinse_import_after_auth(
                        app,
                        batch_date,
                        tenant_oid,
                        virtual_name,
                        scrape_progress=push_scrape_progress,
                        should_cancel=import_job_cancel_requested,
                        extra_scrape_env=job_page_env or None,
                        sequential_chunk_pages=job_seq_pages,
                        max_sequential_chunks=job_max_seq,
                    )

                    conn_done = db_conn()
                    try:
                        c3 = conn_done.cursor(dictionary=True)
                        try:
                            if res.get("cancelled"):
                                update_rinse_import_job(
                                    c3,
                                    job_id,
                                    tenant_oid,
                                    status="cancelled",
                                    progress_note="Stopped by user",
                                    http_status=499,
                                    stdout_tail=res.get("stdout_tail"),
                                    stderr_tail=res.get("stderr_tail"),
                                )
                            elif res.get("ok"):
                                update_rinse_import_job(
                                    c3,
                                    job_id,
                                    tenant_oid,
                                    status="succeeded",
                                    progress_note="Complete",
                                    result_json=res["body"],
                                    http_status=200,
                                )
                            elif not res.get("ok"):
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
                finally:
                    hb_stop.set()
                    if hb_thread is not None:
                        hb_thread.join(timeout=3.0)

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
        from backend.app import get_db, require_admin_or_perm, user_org_id
        from backend.rinse_import_jobs import ensure_rinse_import_jobs_table, fetch_rinse_import_job

        if not export_enabled():
            return _json_rinse_export_disabled(bag_export=False)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin_or_perm(conn, cursor, "upload.create")
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

        row = _fail_stale_rinse_job_if_needed(job_id, tenant_oid, row)

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
        # Live scrape log for UI monitor while running (stdout/stderr tails refreshed by worker).
        if row.get("stdout_tail"):
            out["stdout_tail"] = row["stdout_tail"]
        if row.get("stderr_tail"):
            out["stderr_tail"] = row["stderr_tail"]
        if row["status"] == "failed":
            out["error"] = row.get("error_summary")
            out["http_status"] = row.get("http_status")
            out["exit_code"] = row.get("exit_code")
        if row.get("cancel_requested_at"):
            out["cancel_requested"] = True
        if row["status"] == "cancelled":
            out["message"] = row.get("progress_note") or "Cancelled"
        return jsonify(out)

    @app.route("/admin/rinse/import-upload-batch/jobs/<job_id>/cancel", methods=["POST"])
    def rinse_import_upload_batch_job_cancel(job_id: str):
        from backend.app import get_db, require_admin_or_perm, user_org_id
        from backend.db import get_db as db_conn
        from backend.rinse_import_jobs import (
            ensure_rinse_import_jobs_table,
            fetch_rinse_import_job,
            update_rinse_import_job,
        )

        if not export_enabled():
            return _json_rinse_export_disabled(bag_export=False)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_admin_or_perm(conn, cursor, "upload.create")
            if err is not None:
                return err, code
            tenant_oid = user_org_id(me)
        finally:
            cursor.close()
            conn.close()

        conn2 = db_conn()
        try:
            c = conn2.cursor(dictionary=True)
            try:
                ensure_rinse_import_jobs_table(c)
                row = fetch_rinse_import_job(c, job_id, tenant_oid)
                if not row:
                    return jsonify({"error": "Job not found."}), 404
                st = row.get("status") or ""
                if st not in ("queued", "running"):
                    return (
                        jsonify(
                            {
                                "error": "Job is not running.",
                                "status": st,
                            }
                        ),
                        409,
                    )
                if row.get("cancel_requested_at"):
                    return jsonify({"ok": True, "status": st, "already": True})
                stamp = datetime.now(timezone.utc).replace(tzinfo=None)
                update_rinse_import_job(
                    c,
                    job_id,
                    tenant_oid,
                    cancel_requested_at=stamp,
                    progress_note="Stop requested — halting scrape…",
                )
                conn2.commit()
            finally:
                c.close()
        finally:
            conn2.close()

        return jsonify({"ok": True, "status": "running"})
