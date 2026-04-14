"""MySQL-backed async Rinse → upload-batch import jobs (survives multi-worker Gunicorn)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any


def ensure_rinse_import_jobs_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_import_jobs (
            id CHAR(36) NOT NULL PRIMARY KEY,
            organization_id INT NOT NULL,
            user_id INT NOT NULL,
            batch_date DATE NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'queued',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL,
            progress_note VARCHAR(512) NULL,
            result_json LONGTEXT NULL,
            error_summary VARCHAR(4000) NULL,
            http_status INT NULL,
            exit_code INT NULL,
            stdout_tail MEDIUMTEXT NULL,
            stderr_tail MEDIUMTEXT NULL,
            INDEX idx_rinse_job_org_created (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def insert_rinse_import_job(
    cursor,
    job_id: str,
    organization_id: int,
    user_id: int,
    batch_date: date,
) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_import_jobs
        (id, organization_id, user_id, batch_date, status, created_at, progress_note)
        VALUES (%s, %s, %s, %s, 'queued', %s, %s)
        """,
        (
            job_id,
            int(organization_id),
            int(user_id),
            batch_date,
            _utcnow(),
            "Queued",
        ),
    )


def update_rinse_import_job(
    cursor,
    job_id: str,
    organization_id: int,
    *,
    status: str | None = None,
    progress_note: str | None = None,
    result_json: dict[str, Any] | None = None,
    error_summary: str | None = None,
    http_status: int | None = None,
    exit_code: int | None = None,
    stdout_tail: str | None = None,
    stderr_tail: str | None = None,
) -> None:
    parts: list[str] = ["updated_at=%s"]
    vals: list[Any] = [_utcnow()]
    if status is not None:
        parts.append("status=%s")
        vals.append(status[:24])
    if progress_note is not None:
        parts.append("progress_note=%s")
        vals.append(progress_note[:512])
    if result_json is not None:
        parts.append("result_json=%s")
        vals.append(json.dumps(result_json, default=str))
    if error_summary is not None:
        parts.append("error_summary=%s")
        vals.append(error_summary[:4000])
    if http_status is not None:
        parts.append("http_status=%s")
        vals.append(int(http_status))
    if exit_code is not None:
        parts.append("exit_code=%s")
        vals.append(int(exit_code))
    if stdout_tail is not None:
        parts.append("stdout_tail=%s")
        vals.append(stdout_tail)
    if stderr_tail is not None:
        parts.append("stderr_tail=%s")
        vals.append(stderr_tail)

    vals.extend([job_id, int(organization_id)])
    cursor.execute(
        f"UPDATE rinse_import_jobs SET {', '.join(parts)} WHERE id=%s AND organization_id=%s",
        vals,
    )


def fetch_rinse_import_job(cursor, job_id: str, organization_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id, organization_id, user_id, batch_date, status, created_at, updated_at,
               progress_note, result_json, error_summary, http_status, exit_code,
               stdout_tail, stderr_tail
        FROM rinse_import_jobs
        WHERE id=%s AND organization_id=%s
        LIMIT 1
        """,
        (job_id, int(organization_id)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        d = row
    else:
        cols = [c[0] for c in cursor.description]
        d = dict(zip(cols, row))
    out = dict(d)
    rj = out.get("result_json")
    if isinstance(rj, str) and rj.strip():
        try:
            out["result"] = json.loads(rj)
        except json.JSONDecodeError:
            out["result"] = None
    else:
        out["result"] = None
    out.pop("result_json", None)
    for k in ("batch_date", "created_at", "updated_at"):
        v = out.get(k)
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out
