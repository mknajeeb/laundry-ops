"""Canonical post-scrape Step-1 refresh orchestration (Stage B).

Owner: rinse-scheduler container (``python -m backend.jobs.run_scheduled_rinse_scrape``).

Stage A (evidence import) must commit first. This module only rebuilds/persists the
OPEN/REOPENED Step-1 day snapshot via ``backfill_day_from_live`` — no duplicated
membership, completion, review, HD, or productivity logic.

A scrape cycle is operationally synchronized only when evidence import succeeds
AND Step-1 refresh status is SUCCESS (or SKIPPED for CLOSED days).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Mapping

from backend.ta_helpers import table_exists

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

EVIDENCE_SUCCESS = "SUCCESS"
EVIDENCE_FAILED = "FAILED"

_MAX_WATCHDOG_RETRIES = 5


def _utcnow() -> datetime:
    return datetime.utcnow()


def _max_attempts() -> int:
    try:
        return max(1, min(20, int(os.getenv("RINSE_STEP1_REFRESH_MAX_ATTEMPTS", str(_MAX_WATCHDOG_RETRIES)))))
    except (TypeError, ValueError):
        return _MAX_WATCHDOG_RETRIES


def ensure_step1_scrape_refresh_table(cursor) -> None:
    if table_exists(cursor, "rinse_step1_scrape_refresh"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_scrape_refresh (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          scrape_run_id BIGINT NULL,
          import_batch_id INT NULL,
          affected_operations_date_et DATE NOT NULL,
          evidence_import_status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
          evidence_import_finished_at DATETIME NULL,
          step1_refresh_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
          step1_refresh_started_at DATETIME NULL,
          step1_refresh_finished_at DATETIME NULL,
          step1_day_last_sync_at DATETIME NULL,
          step1_refresh_error TEXT NULL,
          attempt_count INT NOT NULL DEFAULT 0,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_step1_refresh_org_day (organization_id, affected_operations_date_et, id),
          INDEX idx_step1_refresh_status (organization_id, step1_refresh_status, updated_at),
          INDEX idx_step1_refresh_run (scrape_run_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def record_evidence_import_pending(
    cursor,
    *,
    organization_id: int,
    operations_date_et: date,
    scrape_run_id: int | None,
    import_batch_id: int | None,
    evidence_import_finished_at: datetime | None = None,
) -> int | None:
    """Stage A complete — queue Stage B. Returns refresh row id."""
    ensure_step1_scrape_refresh_table(cursor)
    finished = evidence_import_finished_at or _utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_step1_scrape_refresh (
          organization_id, scrape_run_id, import_batch_id,
          affected_operations_date_et,
          evidence_import_status, evidence_import_finished_at,
          step1_refresh_status, attempt_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
        """,
        (
            int(organization_id),
            int(scrape_run_id) if scrape_run_id is not None else None,
            int(import_batch_id) if import_batch_id is not None else None,
            operations_date_et,
            EVIDENCE_SUCCESS,
            finished,
            STATUS_PENDING,
        ),
    )
    return int(cursor.lastrowid) if cursor.lastrowid else None


def _update_refresh_row(
    cursor,
    refresh_id: int | None,
    *,
    status: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    last_sync_at: Any = None,
    error: str | None = None,
    bump_attempt: bool = False,
) -> None:
    if not refresh_id:
        return
    ensure_step1_scrape_refresh_table(cursor)
    sets = ["step1_refresh_status = %s"]
    params: list[Any] = [status]
    if started_at is not None:
        sets.append("step1_refresh_started_at = %s")
        params.append(started_at)
    if finished_at is not None:
        sets.append("step1_refresh_finished_at = %s")
        params.append(finished_at)
    if last_sync_at is not None:
        sets.append("step1_day_last_sync_at = %s")
        params.append(last_sync_at)
    if error is not None:
        sets.append("step1_refresh_error = %s")
        params.append(str(error)[:2000])
    if bump_attempt:
        sets.append("attempt_count = attempt_count + 1")
    params.append(int(refresh_id))
    cursor.execute(
        f"""
        UPDATE rinse_step1_scrape_refresh
        SET {", ".join(sets)}
        WHERE id = %s
        """,
        tuple(params),
    )


def _persist_day_meta_diagnostics(
    cursor,
    organization_id: int,
    shift_date_et: date,
    diagnostics: Mapping[str, Any],
) -> None:
    from backend.rinse_veewash_shift_day import get_day_record

    day = get_day_record(cursor, organization_id, shift_date_et)
    if not day:
        return
    meta = dict(day.get("workload_meta") or {})
    meta["step1_refresh"] = dict(diagnostics)
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET workload_meta_json = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (json.dumps(meta, default=str), int(organization_id), shift_date_et),
    )


def _evidence_watermark(
    cursor,
    organization_id: int,
    *,
    import_batch_id: int | None,
) -> datetime | None:
    """Latest relevant imported evidence timestamp for freshness check."""
    stamps: list[datetime] = []
    if import_batch_id is not None and table_exists(cursor, "upload_batches"):
        # Prod schema uses uploaded_at / confirmed_at / updated_at (no created_at).
        try:
            cursor.execute(
                """
                SELECT confirmed_at, uploaded_at, updated_at
                FROM upload_batches
                WHERE organization_id = %s AND batch_id = %s
                LIMIT 1
                """,
                (int(organization_id), int(import_batch_id)),
            )
            row = cursor.fetchone() or {}
            if isinstance(row, dict):
                for key in ("confirmed_at", "updated_at", "uploaded_at"):
                    v = row.get(key)
                    if isinstance(v, datetime):
                        stamps.append(v)
        except Exception:
            pass
    if import_batch_id is not None and table_exists(cursor, "rinse_bag_scan_events"):
        try:
            # Prod column is source_upload_batch_id (not upload_batch_id).
            cursor.execute(
                """
                SELECT MAX(created_at) AS mx
                FROM rinse_bag_scan_events
                WHERE organization_id = %s AND source_upload_batch_id = %s
                """,
                (int(organization_id), int(import_batch_id)),
            )
            row = cursor.fetchone() or {}
            mx = row.get("mx") if isinstance(row, dict) else None
            if isinstance(mx, datetime):
                stamps.append(mx)
        except Exception:
            pass
    return max(stamps) if stamps else None


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace(" ", "T")[:26]).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def verify_step1_snapshot_freshness(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    import_batch_id: int | None,
    last_sync_at: Any,
) -> dict[str, Any]:
    """Require persisted last_sync_at >= imported evidence watermark."""
    evidence_at = _evidence_watermark(
        cursor, organization_id, import_batch_id=import_batch_id
    )
    sync_at = _parse_dt(last_sync_at)
    if evidence_at is None:
        return {
            "fresh": True,
            "reason": "no_evidence_watermark",
            "evidence_at": None,
            "last_sync_at": sync_at.isoformat(sep=" ") if sync_at else None,
        }
    if sync_at is None:
        return {
            "fresh": False,
            "reason": "missing_last_sync_at",
            "evidence_at": evidence_at.isoformat(sep=" "),
            "last_sync_at": None,
        }
    # Compare with one-second floor to avoid microsecond false negatives.
    evidence_floor = evidence_at.replace(microsecond=0)
    fresh = sync_at >= evidence_floor
    return {
        "fresh": fresh,
        "reason": "ok" if fresh else "stale_vs_evidence",
        "evidence_at": evidence_at.isoformat(sep=" "),
        "last_sync_at": sync_at.isoformat(sep=" "),
    }


def refresh_step1_after_scrape(
    conn,
    cursor,
    *,
    organization_id: int,
    log: Any = None,
    scrape_run_id: int | None = None,
    import_batch_id: int | None = None,
    operations_date_et: date | None = None,
    refresh_row_id: int | None = None,
    evidence_import_status: str = EVIDENCE_SUCCESS,
) -> dict[str, Any]:
    """Stage B: rebuild/persist current OPEN/REOPENED Step-1 day after evidence commit.

    Uses existing ``backfill_day_from_live`` only. Never rebuilds CLOSED days.
    """
    from backend.rinse_veewash_shift_day import (
        STATUS_CLOSED,
        backfill_day_from_live,
        get_day_record,
        today_et,
    )

    def _log(msg: str) -> None:
        if log is not None and hasattr(log, "write"):
            log.write(msg if msg.endswith("\n") else f"{msg}\n")

    org = int(organization_id)
    day = operations_date_et or today_et()
    started = _utcnow()
    base: dict[str, Any] = {
        "scrape_run_id": int(scrape_run_id) if scrape_run_id is not None else None,
        "scrape_batch_id": int(import_batch_id) if import_batch_id is not None else None,
        "import_batch_id": int(import_batch_id) if import_batch_id is not None else None,
        "organization_id": org,
        "affected_operations_date_et": day.isoformat(),
        "shift_date_et": day.isoformat(),
        "evidence_import_status": evidence_import_status,
        "step1_refresh_status": STATUS_RUNNING,
        "started_at": started.isoformat(sep=" "),
        "status": "running",  # legacy alias
        "ok": False,
        "refresh_row_id": refresh_row_id,
    }

    if refresh_row_id is None and evidence_import_status == EVIDENCE_SUCCESS:
        try:
            refresh_row_id = record_evidence_import_pending(
                cursor,
                organization_id=org,
                operations_date_et=day,
                scrape_run_id=scrape_run_id,
                import_batch_id=import_batch_id,
                evidence_import_finished_at=started,
            )
            base["refresh_row_id"] = refresh_row_id
            try:
                conn.commit()
            except Exception:
                pass
        except Exception as exc:
            _log(f"WARNING: could not record PENDING Step-1 refresh row: {exc}")

    _update_refresh_row(
        cursor,
        refresh_row_id,
        status=STATUS_RUNNING,
        started_at=started,
        bump_attempt=True,
    )
    try:
        conn.commit()
    except Exception:
        pass

    try:
        existing = get_day_record(cursor, org, day)
        if existing and str(existing.get("status") or "") == STATUS_CLOSED:
            finished = _utcnow()
            out = {
                **base,
                "skipped": True,
                "reason": "day_closed",
                "step1_refresh_status": STATUS_SKIPPED,
                "status": "skipped",
                "ok": True,
                "finished_at": finished.isoformat(sep=" "),
                "day_bags_rebuilt": 0,
            }
            _update_refresh_row(
                cursor,
                refresh_row_id,
                status=STATUS_SKIPPED,
                finished_at=finished,
                error=None,
            )
            try:
                _persist_day_meta_diagnostics(cursor, org, day, out)
                conn.commit()
            except Exception:
                pass
            _log(f"Step-1 day {day} CLOSED — skip post-scrape refresh\n")
            return out

        before_sync = (existing or {}).get("last_sync_at") if existing else None
        backfill = backfill_day_from_live(cursor, org, day, force=True)
        finished = _utcnow()
        ok = bool(backfill.get("ok"))
        day_after = backfill.get("day") or get_day_record(cursor, org, day) or {}
        last_sync = day_after.get("last_sync_at")
        bag_count = backfill.get("bag_count")
        if bag_count is None:
            try:
                from backend.rinse_veewash_shift_day import day_bag_count

                bag_count = day_bag_count(cursor, org, day)
            except Exception:
                bag_count = None

        freshness = verify_step1_snapshot_freshness(
            cursor,
            org,
            day,
            import_batch_id=import_batch_id,
            last_sync_at=last_sync,
        )
        if ok and not freshness.get("fresh"):
            ok = False
            err = f"freshness_check_failed:{freshness.get('reason')}"
        else:
            err = backfill.get("error")

        status = STATUS_SUCCESS if ok else STATUS_FAILED
        diag: dict[str, Any] = {
            **base,
            "finished_at": finished.isoformat(sep=" "),
            "step1_refresh_status": status,
            "status": "ok" if ok else "failed",  # legacy
            "ok": ok,
            "day_bags_rebuilt": bag_count,
            "day_status": day_after.get("status"),
            "last_sync_at": last_sync,
            "last_sync_at_before": before_sync,
            "step1_day_last_sync_at": last_sync,
            "summary_totals": backfill.get("summary_totals"),
            "freshness": freshness,
            "error": err,
        }
        _update_refresh_row(
            cursor,
            refresh_row_id,
            status=status,
            finished_at=finished,
            last_sync_at=_parse_dt(last_sync),
            error=str(err) if err else None,
        )
        try:
            _persist_day_meta_diagnostics(cursor, org, day, diag)
        except Exception as stamp_exc:
            _log(f"WARNING: Step-1 refresh diagnostics stamp failed: {stamp_exc}\n")
        try:
            conn.commit()
        except Exception:
            pass
        if ok:
            _log(
                f"Step-1 day snapshot refreshed for {day} "
                f"bags={bag_count} batch_id={import_batch_id} status={status}\n"
            )
        else:
            _log(
                f"ERROR: Step-1 post-scrape refresh FAILED for {day}: {err}\n"
            )
        return diag
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        finished = _utcnow()
        _log(f"ERROR: Step-1 post-scrape refresh FAILED: {exc}\n")
        diag = {
            **base,
            "finished_at": finished.isoformat(sep=" "),
            "step1_refresh_status": STATUS_FAILED,
            "status": "failed",
            "ok": False,
            "error": str(exc)[:500],
        }
        try:
            _update_refresh_row(
                cursor,
                refresh_row_id,
                status=STATUS_FAILED,
                finished_at=finished,
                error=str(exc)[:2000],
            )
            conn.commit()
        except Exception:
            pass
        return diag


def list_retryable_step1_refreshes(
    cursor,
    organization_id: int,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Successful evidence imports whose Stage B is not SUCCESS/SKIPPED."""
    ensure_step1_scrape_refresh_table(cursor)
    max_attempts = _max_attempts()
    cursor.execute(
        """
        SELECT id, organization_id, scrape_run_id, import_batch_id,
               affected_operations_date_et, evidence_import_status,
               step1_refresh_status, attempt_count, step1_refresh_error
        FROM rinse_step1_scrape_refresh
        WHERE organization_id = %s
          AND evidence_import_status = %s
          AND step1_refresh_status IN (%s, %s)
          AND attempt_count < %s
        ORDER BY id ASC
        LIMIT %s
        """,
        (
            int(organization_id),
            EVIDENCE_SUCCESS,
            STATUS_PENDING,
            STATUS_FAILED,
            max_attempts,
            int(limit),
        ),
    )
    rows = cursor.fetchall() or []
    return [r for r in rows if isinstance(r, dict)]


def retry_failed_step1_refreshes(
    conn,
    cursor,
    *,
    organization_id: int,
    log: Any = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Watchdog: idempotent Stage-B retry for prior successful imports."""
    pending = list_retryable_step1_refreshes(cursor, organization_id, limit=limit)
    results: list[dict[str, Any]] = []
    for row in pending:
        day = row.get("affected_operations_date_et")
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        if not isinstance(day, date):
            continue
        out = refresh_step1_after_scrape(
            conn,
            cursor,
            organization_id=organization_id,
            log=log,
            scrape_run_id=row.get("scrape_run_id"),
            import_batch_id=row.get("import_batch_id"),
            operations_date_et=day,
            refresh_row_id=int(row["id"]),
        )
        results.append(
            {
                "refresh_row_id": row.get("id"),
                "affected_operations_date_et": day.isoformat(),
                "step1_refresh_status": out.get("step1_refresh_status"),
                "ok": out.get("ok"),
                "error": out.get("error"),
            }
        )
    failed = [r for r in results if not r.get("ok")]
    return {
        "organization_id": int(organization_id),
        "retried": len(results),
        "failed": len(failed),
        "results": results,
        "alert": len(failed) > 0 and any(
            (r.get("attempt_count") or 0) >= _max_attempts() - 1 for r in pending
        ),
    }


def step1_refresh_succeeded(detail: Mapping[str, Any] | None) -> bool:
    """True when Stage B already succeeded or was intentionally skipped."""
    refresh = (detail or {}).get("step1_day_refresh")
    if not isinstance(refresh, dict):
        return False
    if refresh.get("skipped"):
        return True
    status = str(refresh.get("step1_refresh_status") or refresh.get("status") or "").upper()
    if status in (STATUS_SUCCESS, STATUS_SKIPPED, "OK"):
        return True
    return bool(refresh.get("ok"))
