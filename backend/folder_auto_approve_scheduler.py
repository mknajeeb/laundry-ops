"""Drain the Folder auto-approve queue from the API process.

Uses the same APScheduler plus MySQL named lock as the daily operational reset.
Only one Gunicorn worker runs a pass. Historical days are not approved; that
rule lives in the queue processor.
"""

from __future__ import annotations

import atexit
import os
import sys

_LOCK_NAME = "washpro_folder_auto_approve"


def _stderr_log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def mysql_named_lock_acquired(row) -> bool:
    """GET_LOCK returns 1 when this connection owns the lock."""
    if isinstance(row, dict) and row:
        value = next(iter(row.values()))
    elif isinstance(row, (list, tuple)) and row:
        value = row[0]
    else:
        return False
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


def start_folder_auto_approve_scheduler(app) -> None:
    if "pytest" in sys.modules:
        return
    raw = (os.getenv("FOLDER_AUTO_APPROVE_EMBEDDED_SCHEDULER") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        _stderr_log("[folder_auto_approve] embedded scheduler disabled")
        return
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        msg = "[folder_auto_approve] APScheduler not installed; embedded scheduler disabled"
        _stderr_log(msg)
        app.logger.warning(msg)
        return

    def _minutes() -> int:
        raw_minutes = (os.getenv("FOLDER_AUTO_APPROVE_SCHED_MINUTES") or "5").strip()
        try:
            value = int(raw_minutes, 10)
        except ValueError:
            value = 5
        return max(1, min(60, value))

    minutes = _minutes()

    def job() -> None:
        from backend.db import get_db
        from backend.rinse_performance_auto_approve import process_pending_auto_approve_queue

        conn = None
        lock_cur = None
        try:
            conn = get_db()
            lock_cur = conn.cursor()
            lock_cur.execute("SELECT GET_LOCK(%s, 5)", (_LOCK_NAME,))
            if not mysql_named_lock_acquired(lock_cur.fetchone()):
                _stderr_log("[folder_auto_approve] skipped (lock held by another worker)")
                return
            cur = conn.cursor(dictionary=True)
            try:
                out = process_pending_auto_approve_queue(cur)
                conn.commit()
            finally:
                cur.close()
            _stderr_log(
                "[folder_auto_approve] processed_days="
                f"{out.get('processed_days')} days={out.get('days')}"
            )
        except Exception:
            _stderr_log("[folder_auto_approve] job FAILED")
            app.logger.exception("folder auto-approve scheduler failed")
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn is not None and lock_cur is not None:
                rel = conn.cursor()
                try:
                    rel.execute("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
                    rel.fetchone()
                except Exception:
                    pass
                finally:
                    rel.close()
            if lock_cur is not None:
                try:
                    lock_cur.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(
        job,
        IntervalTrigger(minutes=minutes, timezone="America/New_York"),
        id="washpro_folder_auto_approve",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    atexit.register(lambda: sched.shutdown(wait=False))
    _stderr_log(f"[folder_auto_approve] embedded scheduler started every {minutes} min ET")
    app.logger.info("folder auto-approve scheduler started every %s min ET", minutes)
