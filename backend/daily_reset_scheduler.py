"""
Embedded midnight (US Eastern) run for daily operational reset.

Runs daily at America/New_York (default 00:05) when DAILY_OPERATIONAL_RESET_EMBEDDED_SCHEDULER is on (default).
Optional: DAILY_OPERATIONAL_RESET_SCHED_HOUR (0–23), DAILY_OPERATIONAL_RESET_SCHED_MINUTE (0–59).
Uses MySQL GET_LOCK so only one Gunicorn worker / process runs the pass when scaled out.
"""

from __future__ import annotations

import atexit
import os

_LOCK_NAME = "washpro_daily_operational_reset"


def start_daily_reset_scheduler(app) -> None:
    raw = (os.getenv("DAILY_OPERATIONAL_RESET_EMBEDDED_SCHEDULER") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return
    # Flask/Werkzeug reloader: parent process must not start the scheduler.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        app.logger.warning("APScheduler not installed; embedded daily reset scheduler disabled")
        return

    def job():
        from backend.checkout_history import run_daily_operational_reset_scheduled_pass
        from backend.db import get_db

        conn = None
        lock_cur = None
        try:
            conn = get_db()
            lock_cur = conn.cursor()
            lock_cur.execute("SELECT GET_LOCK(%s, 30)", (_LOCK_NAME,))
            row = lock_cur.fetchone()
            got = row is not None and int(row[0]) == 1
            if not got:
                app.logger.info("daily reset embedded job: skipped (lock not acquired)")
                return

            try:
                out = run_daily_operational_reset_scheduled_pass(conn)
                ran_n = sum(
                    1
                    for t in (out.get("tenants") or [])
                    if isinstance((t or {}).get("result"), dict) and (t.get("result") or {}).get("ran")
                )
                app.logger.info(
                    "daily reset embedded job: tenants=%s rollovers_completed=%s",
                    out.get("tenant_count"),
                    ran_n,
                )
            finally:
                rel = conn.cursor()
                try:
                    rel.execute("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
                finally:
                    rel.close()
        except Exception:
            app.logger.exception("daily reset embedded job failed")
        finally:
            if lock_cur:
                try:
                    lock_cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    tz = "America/New_York"

    def _int_env(name: str, default: int, lo: int, hi: int) -> int:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            v = int(raw, 10)
        except ValueError:
            return default
        return max(lo, min(hi, v))

    sched_h = _int_env("DAILY_OPERATIONAL_RESET_SCHED_HOUR", 0, 0, 23)
    sched_m = _int_env("DAILY_OPERATIONAL_RESET_SCHED_MINUTE", 5, 0, 59)

    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(
        job,
        CronTrigger(hour=sched_h, minute=sched_m, timezone=tz),
        id="washpro_daily_operational_reset",
        replace_existing=True,
    )
    sched.start()
    atexit.register(lambda: sched.shutdown(wait=False))
    app.logger.info(
        "daily reset embedded scheduler started (%02d:%02d %s)",
        sched_h,
        sched_m,
        tz,
    )
