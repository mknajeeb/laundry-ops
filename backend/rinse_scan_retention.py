"""Lifecycle-safe scan / upload-history retention (DISABLED by default).

Two hot tables grow without bound today:

* ``upload_batch_scan_events`` — raw import copies (~389k rows/day org-3).
  Canonical lifecycle evidence lives in ``rinse_bag_scan_events`` after merge.
* ``rinse_bag_scan_events`` — canonical scan chronology (~3.7k rows/day).
  Needed while a bag has ACTIVE/REVIEW / open OI / HD open production.

This module plans and (when explicitly unlocked) applies **bounded** cleanup.
It does **not** enable a cron, does **not** run in production by default, and
does **not** expand the WF clean-reset destructive scope.

Recommended defaults (overridable; not auto-enabled):

* upload heavy rows (via Option C batch path): **30 days**
* canonical ``rinse_bag_scan_events``: **90 days**

Minimum safe floors (code-enforced):

* upload heavy rows: **7 days** — raw is redundant after merge, but short
  re-import / audit debugging needs a buffer.
* canonical scans: **14 days** — only rows older than this AND not belonging
  to a protected bag may be considered; open lifecycle evidence is never
  eligible regardless of age.

Parent ``upload_batches`` headers are retained by default (Option C). Optional
header archival is planned separately and stays off.

Respects ``wf_reset_epoch_at``: never deletes scan evidence at/after the epoch
wall (post-reset operational evidence). Pre-epoch rows remain eligible for
retention once aged past the cutoff *and* not protected.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from backend.ta_helpers import table_exists, table_has_column

ET = ZoneInfo("America/New_York")

# Hard block — same pattern as wf_ops_clean_reset.APPLY_BLOCKED.
APPLY_BLOCKED = True
APPLY_UNLOCK_ENV = "RINSE_SCAN_RETENTION_APPLY_UNLOCK"
ENABLED_ENV = "RINSE_SCAN_RETENTION_ENABLED"

# Defaults / floors (days). Env may raise floors; may not lower below floors.
DEFAULT_UPLOAD_RETENTION_DAYS = 30
DEFAULT_CANONICAL_RETENTION_DAYS = 90
MIN_UPLOAD_RETENTION_DAYS = 7
MIN_CANONICAL_RETENTION_DAYS = 14

DEFAULT_BATCH_SIZE = 5000
DEFAULT_MAX_RUNTIME_SECONDS = 120
DEFAULT_MAX_BATCHES_PER_RUN = 40

SETTINGS_KEY = "rinse_scan_retention_v1"
CURSOR_KEY = "rinse_scan_retention_cursor_v1"


@dataclass(frozen=True)
class RetentionConfig:
    """Resolved retention policy for one org."""

    organization_id: int
    enabled: bool = False
    upload_retention_days: int = DEFAULT_UPLOAD_RETENTION_DAYS
    canonical_retention_days: int = DEFAULT_CANONICAL_RETENTION_DAYS
    batch_size: int = DEFAULT_BATCH_SIZE
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS
    max_batches_per_run: int = DEFAULT_MAX_BATCHES_PER_RUN
    purge_upload_batch_headers: bool = False  # Phase 2 — off
    notes: tuple[str, ...] = ()


@dataclass
class RetentionCursor:
    """Resume state for bounded runs (stored in system_settings)."""

    last_canonical_id: int = 0
    last_upload_batch_id: int = 0
    last_run_at_utc: str | None = None
    last_status: str | None = None


def _clamp_days(requested: int, floor: int, *, label: str) -> tuple[int, str | None]:
    try:
        n = int(requested)
    except (TypeError, ValueError):
        return floor, f"{label}: invalid → floor {floor}"
    if n < floor:
        return floor, f"{label}: {n} raised to floor {floor}"
    return n, None


def resolve_retention_config(
    cursor,
    organization_id: int,
    *,
    enabled_override: bool | None = None,
    upload_days: int | None = None,
    canonical_days: int | None = None,
) -> RetentionConfig:
    """Merge defaults, env, optional system_settings JSON, and call overrides."""
    org = int(organization_id)
    notes: list[str] = []

    enabled_env = os.getenv(ENABLED_ENV, "").strip().lower() in {"1", "true", "yes"}
    enabled = bool(enabled_env)
    upload = DEFAULT_UPLOAD_RETENTION_DAYS
    canonical = DEFAULT_CANONICAL_RETENTION_DAYS
    batch_size = DEFAULT_BATCH_SIZE
    max_runtime = DEFAULT_MAX_RUNTIME_SECONDS
    max_batches = DEFAULT_MAX_BATCHES_PER_RUN
    purge_headers = False

    if cursor is not None and table_exists(cursor, "system_settings"):
        try:
            cursor.execute(
                """
                SELECT svalue FROM system_settings
                WHERE organization_id = %s AND skey = %s
                LIMIT 1
                """,
                (org, SETTINGS_KEY),
            )
            row = cursor.fetchone()
            raw = None
            if isinstance(row, dict):
                raw = row.get("svalue")
            elif row:
                raw = row[0]
            if raw:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict):
                    if "enabled" in parsed:
                        enabled = bool(parsed.get("enabled"))
                    upload = int(parsed.get("upload_retention_days", upload))
                    canonical = int(parsed.get("canonical_retention_days", canonical))
                    batch_size = int(parsed.get("batch_size", batch_size))
                    max_runtime = int(parsed.get("max_runtime_seconds", max_runtime))
                    max_batches = int(parsed.get("max_batches_per_run", max_batches))
                    purge_headers = bool(parsed.get("purge_upload_batch_headers", False))
        except Exception as exc:
            notes.append(f"settings_unreadable: {exc}")

    if os.getenv("RINSE_SCAN_RETENTION_UPLOAD_DAYS"):
        upload = int(os.getenv("RINSE_SCAN_RETENTION_UPLOAD_DAYS") or upload)
    if os.getenv("RINSE_SCAN_RETENTION_CANONICAL_DAYS"):
        canonical = int(os.getenv("RINSE_SCAN_RETENTION_CANONICAL_DAYS") or canonical)

    if upload_days is not None:
        upload = int(upload_days)
    if canonical_days is not None:
        canonical = int(canonical_days)
    if enabled_override is not None:
        enabled = bool(enabled_override)

    upload, note_u = _clamp_days(upload, MIN_UPLOAD_RETENTION_DAYS, label="upload")
    canonical, note_c = _clamp_days(
        canonical, MIN_CANONICAL_RETENTION_DAYS, label="canonical"
    )
    if note_u:
        notes.append(note_u)
    if note_c:
        notes.append(note_c)

    return RetentionConfig(
        organization_id=org,
        enabled=enabled,
        upload_retention_days=upload,
        canonical_retention_days=canonical,
        batch_size=max(100, min(int(batch_size), 50_000)),
        max_runtime_seconds=max(10, int(max_runtime)),
        max_batches_per_run=max(1, int(max_batches)),
        purge_upload_batch_headers=purge_headers,
        notes=tuple(notes),
    )


def today_et() -> date:
    return datetime.now(ET).date()


def cutoff_datetime_et(days: int, *, today: date | None = None) -> datetime:
    """Naive ET wall cutoff: rows with event time **strictly before** this are aged."""
    d = (today or today_et()) - timedelta(days=int(days))
    return datetime.combine(d, datetime.min.time())


def load_protected_bag_ids(cursor, organization_id: int) -> set[str]:
    """Bags whose scan evidence must never be purged."""
    org = int(organization_id)
    bags: set[str] = set()

    if table_exists(cursor, "rinse_wf_service_cycles"):
        cursor.execute(
            """
            SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
            FROM rinse_wf_service_cycles
            WHERE organization_id = %s AND status IN ('ACTIVE', 'REVIEW')
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            bid = (r.get("bag_id") if isinstance(r, dict) else r[0]) or ""
            if bid:
                bags.add(str(bid).upper())

    if table_exists(cursor, "rinse_order_instances") and table_has_column(
        cursor, "rinse_order_instances", "completed_at"
    ):
        cursor.execute(
            """
            SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
            FROM rinse_order_instances
            WHERE organization_id = %s AND completed_at IS NULL
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            bid = (r.get("bag_id") if isinstance(r, dict) else r[0]) or ""
            if bid:
                bags.add(str(bid).upper())

    # HD open / recent production — shared chronology table; never strip HD bags.
    if table_exists(cursor, "hd_day_bag_production"):
        cursor.execute(
            """
            SELECT DISTINCT UPPER(TRIM(bag_id)) AS bag_id
            FROM hd_day_bag_production
            WHERE organization_id = %s
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            bid = (r.get("bag_id") if isinstance(r, dict) else r[0]) or ""
            if bid:
                bags.add(str(bid).upper())

    return bags


def _epoch_wall(cursor, organization_id: int) -> datetime | None:
    try:
        from backend.wf_ops_reset_epoch import epoch_scan_wall, get_wf_reset_epoch_at

        return epoch_scan_wall(get_wf_reset_epoch_at(cursor, int(organization_id)))
    except Exception:
        return None


def load_retention_cursor(cursor, organization_id: int) -> RetentionCursor:
    if not table_exists(cursor, "system_settings"):
        return RetentionCursor()
    try:
        cursor.execute(
            """
            SELECT svalue FROM system_settings
            WHERE organization_id = %s AND skey = %s
            LIMIT 1
            """,
            (int(organization_id), CURSOR_KEY),
        )
        row = cursor.fetchone()
        raw = row.get("svalue") if isinstance(row, dict) else (row[0] if row else None)
        if not raw:
            return RetentionCursor()
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return RetentionCursor()
        return RetentionCursor(
            last_canonical_id=int(parsed.get("last_canonical_id") or 0),
            last_upload_batch_id=int(parsed.get("last_upload_batch_id") or 0),
            last_run_at_utc=parsed.get("last_run_at_utc"),
            last_status=parsed.get("last_status"),
        )
    except Exception:
        return RetentionCursor()


def save_retention_cursor(cursor, organization_id: int, cur: RetentionCursor) -> None:
    if not table_exists(cursor, "system_settings"):
        return
    payload = json.dumps(asdict(cur))
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE svalue = VALUES(svalue)
        """,
        (int(organization_id), CURSOR_KEY, payload),
    )


def estimate_bytes(row_count: int, avg_bytes: float) -> int:
    return int(max(0, row_count) * max(0.0, avg_bytes))


def steady_state_projection(
    *,
    daily_rows: float,
    avg_bytes: float,
    retention_days: int,
) -> dict[str, Any]:
    rows = daily_rows * retention_days
    return {
        "retention_days": retention_days,
        "estimated_rows": int(round(rows)),
        "estimated_gb": round(rows * avg_bytes / (1024**3), 3),
    }


def explain_canonical_selection(
    cursor,
    organization_id: int,
    *,
    cutoff: datetime,
    after_id: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        EXPLAIN SELECT id, bag_id, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND id > %s
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed < %s
        ORDER BY id ASC
        LIMIT %s
        """,
        (int(organization_id), int(after_id), cutoff, int(batch_size)),
    )
    rows = cursor.fetchall() or []
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (tuple, list)):
            # Some drivers return EXPLAIN as tuples.
            out.append({"cols": list(r)})
        else:
            out.append({"raw": str(r)})
    return out


def explain_upload_batch_selection(
    cursor,
    organization_id: int,
    *,
    cutoff_batch_date: date,
) -> list[dict[str, Any]]:
    from backend.upload_batch_cleanup import resolve_upload_batches_pk

    if not table_exists(cursor, "upload_batches"):
        return []
    pk = resolve_upload_batches_pk(cursor)
    cursor.execute(
        f"""
        EXPLAIN SELECT b.`{pk}` AS batch_id, b.batch_date
        FROM upload_batches b
        WHERE b.organization_id = %s
          AND b.batch_date IS NOT NULL
          AND b.batch_date <= %s
        ORDER BY b.batch_date ASC, b.`{pk}` ASC
        LIMIT 100
        """,
        (int(organization_id), cutoff_batch_date),
    )
    rows = cursor.fetchall() or []
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (tuple, list)):
            out.append({"cols": list(r)})
        else:
            out.append({"raw": str(r)})
    return out


def _select_canonical_candidate_ids(
    cursor,
    organization_id: int,
    *,
    cutoff: datetime,
    after_id: int,
    batch_size: int,
    protected: set[str],
    epoch_wall: datetime | None,
) -> list[int]:
    """Return up to batch_size deletable canonical scan ids (lifecycle-safe)."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    # Upper bound for deletable timestamps: aged past retention AND strictly
    # before epoch (post-epoch evidence is current ops and must stay).
    effective_cutoff = cutoff
    if epoch_wall is not None and epoch_wall < effective_cutoff:
        effective_cutoff = epoch_wall

    cursor.execute(
        """
        SELECT id, bag_id, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND id > %s
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed < %s
        ORDER BY id ASC
        LIMIT %s
        """,
        (int(organization_id), int(after_id), effective_cutoff, int(batch_size) * 3),
    )
    out: list[int] = []
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        bid = str(r.get("bag_id") or "").strip().upper()
        if bid in protected:
            continue
        ts = r.get("scanned_at_parsed")
        if isinstance(ts, datetime) and ts >= cutoff:
            continue
        if epoch_wall is not None and isinstance(ts, datetime) and ts >= epoch_wall:
            continue
        out.append(int(r["id"]))
        if len(out) >= batch_size:
            break
    return out


def _plan_upload_retention_fast(
    cursor,
    organization_id: int,
    *,
    cutoff_batch_date: date,
) -> dict[str, Any]:
    """Aggregate eligible upload heavy-row counts without per-batch COUNTs.

    Selection is batch-date scoped and uses ``idx_ubse_org_batch`` via
    ``upload_batch_id`` join — never a created_at full scan.
    """
    from backend.upload_batch_cleanup import resolve_upload_batches_pk

    org = int(organization_id)
    notes: list[str] = []
    out: dict[str, Any] = {
        "batches": 0,
        "upload_batch_scan_events": 0,
        "upload_batch_rows": 0,
        "sample_batches": [],
        "notes": notes,
    }
    if not table_exists(cursor, "upload_batches"):
        notes.append("upload_batches missing")
        return out

    pk = resolve_upload_batches_pk(cursor)
    has_state = table_has_column(cursor, "upload_batches", "state")
    has_purged = table_has_column(cursor, "upload_batches", "raw_rows_purged_at")
    state_clause = (
        "AND UPPER(COALESCE(b.state, '')) IN ('CONFIRMED', 'CLOSED')"
        if has_state
        else ""
    )
    purged_clause = "AND b.raw_rows_purged_at IS NULL" if has_purged else ""

    # Protect latest successful imported batch (same rule as Option C).
    latest_success = None
    try:
        from backend.rinse_upload_batch_retention import (
            get_latest_successful_imported_batch_id,
        )

        latest_success = get_latest_successful_imported_batch_id(cursor, org)
    except Exception as exc:
        notes.append(f"latest_success_unreadable: {exc}")

    latest_clause = ""
    args: list[Any] = [org, cutoff_batch_date]
    if latest_success is not None:
        latest_clause = f"AND b.`{pk}` <> %s"
        args.append(int(latest_success))

    cursor.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM upload_batches b
        WHERE b.organization_id = %s
          AND b.batch_date IS NOT NULL
          AND b.batch_date <= %s
          {state_clause}
          {purged_clause}
          {latest_clause}
        """,
        tuple(args),
    )
    row = cursor.fetchone() or {}
    out["batches"] = int((row.get("n") if isinstance(row, dict) else 0) or 0)

    if table_exists(cursor, "upload_batch_scan_events"):
        cursor.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM upload_batch_scan_events ubse
            INNER JOIN upload_batches b ON b.`{pk}` = ubse.upload_batch_id
            WHERE ubse.organization_id = %s
              AND b.organization_id = %s
              AND b.batch_date IS NOT NULL
              AND b.batch_date <= %s
              {state_clause}
              {purged_clause}
              {latest_clause}
            """,
            tuple([org, org, cutoff_batch_date] + ([int(latest_success)] if latest_success is not None else [])),
        )
        row = cursor.fetchone() or {}
        out["upload_batch_scan_events"] = int(
            (row.get("n") if isinstance(row, dict) else 0) or 0
        )

    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM upload_batch_rows ubr
            INNER JOIN upload_batches b ON b.`{pk}` = ubr.upload_batch_id
            WHERE b.organization_id = %s
              AND b.batch_date IS NOT NULL
              AND b.batch_date <= %s
              {state_clause}
              {purged_clause}
              {latest_clause}
            """,
            tuple([org, cutoff_batch_date] + ([int(latest_success)] if latest_success is not None else [])),
        )
        row = cursor.fetchone() or {}
        out["upload_batch_rows"] = int(
            (row.get("n") if isinstance(row, dict) else 0) or 0
        )

    cursor.execute(
        f"""
        SELECT b.`{pk}` AS batch_id, b.batch_date
        FROM upload_batches b
        WHERE b.organization_id = %s
          AND b.batch_date IS NOT NULL
          AND b.batch_date <= %s
          {state_clause}
          {purged_clause}
          {latest_clause}
        ORDER BY b.batch_date ASC, b.`{pk}` ASC
        LIMIT 10
        """,
        tuple(args),
    )
    out["sample_batches"] = [
        {
            "batch_id": r.get("batch_id") if isinstance(r, dict) else None,
            "batch_date": str(r.get("batch_date")) if isinstance(r, dict) else None,
            "eligible": True,
        }
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict)
    ]
    notes.append(
        "fast aggregate plan — apply still uses Option C per-batch deletes"
    )
    return out


def plan_scan_retention(
    cursor,
    organization_id: int,
    *,
    config: RetentionConfig | None = None,
    include_explain: bool = True,
    measured_upload_avg_bytes: float = 388.0,
    measured_canonical_avg_bytes: float = 200.0,
    measured_upload_daily_rows: float = 389_047.0,
    measured_canonical_daily_rows: float = 3_735.0,
) -> dict[str, Any]:
    """Dry-run inventory + selection plan. SELECT only."""
    cfg = config or resolve_retention_config(cursor, organization_id)
    org = cfg.organization_id
    today = today_et()
    upload_cutoff_date = today - timedelta(days=cfg.upload_retention_days)
    canonical_cutoff = cutoff_datetime_et(cfg.canonical_retention_days, today=today)
    protected = load_protected_bag_ids(cursor, org)
    epoch_wall = _epoch_wall(cursor, org)
    cursor_state = load_retention_cursor(cursor, org)

    # --- Upload heavy rows: aggregate plan (avoid per-batch COUNT on 6M+ rows) ---
    upload_fast = _plan_upload_retention_fast(
        cursor, org, cutoff_batch_date=upload_cutoff_date
    )
    upload_eligible_scans = int(upload_fast.get("upload_batch_scan_events") or 0)
    upload_eligible_rows = int(upload_fast.get("upload_batch_rows") or 0)
    upload_eligible_batches = int(upload_fast.get("batches") or 0)
    upload_plan = {
        "cutoff_batch_date": upload_cutoff_date.isoformat(),
        "batches_to_purge": upload_fast.get("sample_batches") or [],
        "skipped_batches": [],
        "tables_never_touched": [
            "orders_staging",
            "rinse_bag_registry",
            "rinse_bag_scan_events",
            "orders_final",
        ],
        "fast_plan": True,
        "notes": upload_fast.get("notes") or [],
    }

    # --- Canonical scan eligible count (approx via COUNT with protected exclusion) ---
    canonical_eligible = 0
    canonical_oldest = None
    canonical_newest = None
    canonical_total = 0
    if table_exists(cursor, "rinse_bag_scan_events"):
        cursor.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(scanned_at_parsed) AS mn,
                   MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND scanned_at_parsed IS NOT NULL
            """,
            (org,),
        )
        row = cursor.fetchone() or {}
        canonical_total = int((row.get("n") if isinstance(row, dict) else 0) or 0)
        canonical_oldest = row.get("mn") if isinstance(row, dict) else None
        canonical_newest = row.get("mx") if isinstance(row, dict) else None

        effective_cutoff = canonical_cutoff
        if epoch_wall is not None and epoch_wall < effective_cutoff:
            effective_cutoff = epoch_wall
        # Count aged rows; protected bags subtracted via NOT IN when small.
        if protected and len(protected) <= 5000:
            ph = ", ".join(["%s"] * len(protected))
            cursor.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM rinse_bag_scan_events
                WHERE organization_id = %s
                  AND scanned_at_parsed IS NOT NULL
                  AND scanned_at_parsed < %s
                  AND UPPER(TRIM(bag_id)) NOT IN ({ph})
                """,
                (org, effective_cutoff, *sorted(protected)),
            )
        else:
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM rinse_bag_scan_events
                WHERE organization_id = %s
                  AND scanned_at_parsed IS NOT NULL
                  AND scanned_at_parsed < %s
                """,
                (org, effective_cutoff),
            )
        crow = cursor.fetchone() or {}
        canonical_eligible = int((crow.get("n") if isinstance(crow, dict) else 0) or 0)

    sample_ids = _select_canonical_candidate_ids(
        cursor,
        org,
        cutoff=canonical_cutoff,
        after_id=cursor_state.last_canonical_id,
        batch_size=min(20, cfg.batch_size),
        protected=protected,
        epoch_wall=epoch_wall,
    )

    explain_canonical: list[dict[str, Any]] = []
    explain_upload: list[dict[str, Any]] = []
    if include_explain:
        try:
            explain_canonical = explain_canonical_selection(
                cursor,
                org,
                cutoff=canonical_cutoff
                if epoch_wall is None
                else min(canonical_cutoff, epoch_wall),
                after_id=cursor_state.last_canonical_id,
                batch_size=cfg.batch_size,
            )
        except Exception as exc:
            explain_canonical = [{"error": str(exc)}]
        try:
            explain_upload = explain_upload_batch_selection(
                cursor, org, cutoff_batch_date=upload_cutoff_date
            )
        except Exception as exc:
            explain_upload = [{"error": str(exc)}]

    index_recommendation = [
        {
            "table": "rinse_bag_scan_events",
            "proposed": "idx_rbse_org_time (organization_id, scanned_at_parsed, id)",
            "why": (
                "Retention selects by org + scanned_at_parsed + id resume; "
                "existing idx_rbse_org_bag_time requires bag_id first."
            ),
            "status": "propose only — do not add in production yet",
        },
        {
            "table": "upload_batch_scan_events",
            "proposed": "keep deleting via upload_batch_id (idx_ubse_org_batch)",
            "why": "No created_at index; batch-scoped Option C path avoids full scans.",
            "status": "preferred path",
        },
    ]

    return {
        "organization_id": org,
        "enabled": cfg.enabled,
        "apply_blocked": APPLY_BLOCKED,
        "config": asdict(cfg),
        "policy": {
            "upload_table": "upload_batch_scan_events (+ upload_batch_rows via Option C)",
            "canonical_table": "rinse_bag_scan_events",
            "upload_retention_days": cfg.upload_retention_days,
            "canonical_retention_days": cfg.canonical_retention_days,
            "min_upload_days": MIN_UPLOAD_RETENTION_DAYS,
            "min_canonical_days": MIN_CANONICAL_RETENTION_DAYS,
            "upload_cutoff_batch_date_et": upload_cutoff_date.isoformat(),
            "canonical_cutoff_et": canonical_cutoff.isoformat(sep=" "),
            "wf_reset_epoch_wall": epoch_wall.isoformat(sep=" ") if epoch_wall else None,
            "protected_bag_count": len(protected),
            "protected_bag_sample": sorted(protected)[:25],
            "purge_upload_batch_headers": cfg.purge_upload_batch_headers,
            "frequency_recommendation": "daily (Quiet overnight preferred; ~2 min max runtime)",
        },
        "current_state": {
            "canonical_total_rows": canonical_total,
            "canonical_oldest": str(canonical_oldest) if canonical_oldest else None,
            "canonical_newest": str(canonical_newest) if canonical_newest else None,
            "upload_eligible_batches": upload_eligible_batches,
            "upload_eligible_scan_events": upload_eligible_scans,
            "upload_eligible_batch_rows": upload_eligible_rows,
            "canonical_eligible_rows": canonical_eligible,
            "canonical_sample_ids": sample_ids,
        },
        "bytes": {
            "upload_eligible_est": estimate_bytes(
                upload_eligible_scans, measured_upload_avg_bytes
            ),
            "canonical_eligible_est": estimate_bytes(
                canonical_eligible, measured_canonical_avg_bytes
            ),
            "upload_avg_bytes_used": measured_upload_avg_bytes,
            "canonical_avg_bytes_used": measured_canonical_avg_bytes,
        },
        "steady_state": {
            "upload_daily_rows": measured_upload_daily_rows,
            "canonical_daily_rows": measured_canonical_daily_rows,
            "upload": {
                "d30": steady_state_projection(
                    daily_rows=measured_upload_daily_rows,
                    avg_bytes=measured_upload_avg_bytes,
                    retention_days=30,
                ),
                "d60": steady_state_projection(
                    daily_rows=measured_upload_daily_rows,
                    avg_bytes=measured_upload_avg_bytes,
                    retention_days=60,
                ),
                "d90": steady_state_projection(
                    daily_rows=measured_upload_daily_rows,
                    avg_bytes=measured_upload_avg_bytes,
                    retention_days=90,
                ),
            },
            "canonical": {
                "d30": steady_state_projection(
                    daily_rows=measured_canonical_daily_rows,
                    avg_bytes=measured_canonical_avg_bytes,
                    retention_days=30,
                ),
                "d60": steady_state_projection(
                    daily_rows=measured_canonical_daily_rows,
                    avg_bytes=measured_canonical_avg_bytes,
                    retention_days=60,
                ),
                "d90": steady_state_projection(
                    daily_rows=measured_canonical_daily_rows,
                    avg_bytes=measured_canonical_avg_bytes,
                    retention_days=90,
                ),
            },
        },
        "batching": {
            "batch_size": cfg.batch_size,
            "max_batches_per_run": cfg.max_batches_per_run,
            "max_runtime_seconds": cfg.max_runtime_seconds,
            "resume_cursor": asdict(cursor_state),
            "failure_behavior": (
                "Per-batch COMMIT; on error abort remaining batches, persist cursor "
                "at last successful id/batch, leave remaining work for next run."
            ),
            "idempotent": True,
        },
        "explain": {
            "canonical_selection": explain_canonical,
            "upload_batch_selection": explain_upload,
        },
        "index_recommendations": index_recommendation,
        "upload_option_c_plan": {
            "cutoff_batch_date": upload_plan.get("cutoff_batch_date"),
            "batches_to_purge_count": len(upload_plan.get("batches_to_purge") or []),
            "skipped_count": len(upload_plan.get("skipped_batches") or []),
            "tables_never_touched": upload_plan.get("tables_never_touched"),
            "parent_headers": (
                "retained (raw_rows_purged_at stamped); "
                "header DELETE is Phase 2 and disabled"
            ),
        },
        "hd_safety": {
            "hd_production_bags_protected": True,
            "note": (
                "All hd_day_bag_production bag_ids are in the protected set so "
                "canonical scan purge cannot strip HD chronology."
            ),
        },
        "warnings": list(cfg.notes),
    }


def apply_scan_retention(
    cursor,
    organization_id: int,
    *,
    config: RetentionConfig | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Execute bounded retention. Refuses unless unlocked + enabled + not APPLY_BLOCKED."""
    cfg = config or resolve_retention_config(cursor, organization_id)
    plan = plan_scan_retention(cursor, organization_id, config=cfg, include_explain=False)
    result: dict[str, Any] = {
        **plan,
        "applied": False,
        "dry_run": dry_run,
        "deleted_canonical": 0,
        "deleted_upload_scan_events": 0,
        "deleted_upload_batch_rows": 0,
        "batches_processed": 0,
        "stopped_reason": None,
    }

    if dry_run:
        result["stopped_reason"] = "dry_run"
        return result

    if APPLY_BLOCKED:
        result["stopped_reason"] = "APPLY_BLOCKED"
        return result
    if os.getenv(APPLY_UNLOCK_ENV, "").strip() != "1":
        result["stopped_reason"] = f"missing {APPLY_UNLOCK_ENV}=1"
        return result
    if not cfg.enabled:
        result["stopped_reason"] = "retention_disabled"
        return result

    org = cfg.organization_id
    protected = load_protected_bag_ids(cursor, org)
    epoch_wall = _epoch_wall(cursor, org)
    canonical_cutoff = cutoff_datetime_et(cfg.canonical_retention_days)
    cur_state = load_retention_cursor(cursor, org)
    started = time.monotonic()
    deleted_canonical = 0
    batches = 0

    # 1) Canonical scans — id-ordered bounded deletes
    while batches < cfg.max_batches_per_run:
        if time.monotonic() - started > cfg.max_runtime_seconds:
            result["stopped_reason"] = "max_runtime"
            break
        ids = _select_canonical_candidate_ids(
            cursor,
            org,
            cutoff=canonical_cutoff,
            after_id=cur_state.last_canonical_id,
            batch_size=cfg.batch_size,
            protected=protected,
            epoch_wall=epoch_wall,
        )
        if not ids:
            if result["stopped_reason"] is None:
                result["stopped_reason"] = "canonical_caught_up"
            break
        ph = ", ".join(["%s"] * len(ids))
        cursor.execute(
            f"DELETE FROM rinse_bag_scan_events WHERE organization_id = %s AND id IN ({ph})",
            (org, *ids),
        )
        deleted_canonical += int(cursor.rowcount or 0)
        cur_state.last_canonical_id = max(ids)
        batches += 1
        try:
            cursor.connection.commit()  # type: ignore[attr-defined]
        except Exception:
            pass

    # 2) Upload heavy rows — Option C, one batch header at a time (bounded)
    from backend.rinse_upload_batch_retention import (
        apply_heavy_row_purge,
        plan_heavy_row_purge,
    )

    upload_deleted_scans = 0
    upload_deleted_rows = 0
    upload_batches_done = 0
    if result["stopped_reason"] in (None, "canonical_caught_up"):
        full_upload = plan_heavy_row_purge(
            cursor, org, older_than_days=cfg.upload_retention_days
        )
        # Resume: skip batches with id <= cursor
        pending = [
            b
            for b in (full_upload.get("batches_to_purge") or [])
            if int(b["batch_id"]) > int(cur_state.last_upload_batch_id or 0)
        ]
        for batch in pending:
            if batches >= cfg.max_batches_per_run:
                result["stopped_reason"] = "max_batches"
                break
            if time.monotonic() - started > cfg.max_runtime_seconds:
                result["stopped_reason"] = "max_runtime"
                break
            mini_plan = {
                **full_upload,
                "batches_to_purge": [batch],
                "scrape_runs": {"retain": [], "trim_heavy_fields": []},
            }
            applied = apply_heavy_row_purge(
                cursor, org, mini_plan, trim_scrape_result_json=False
            )
            upload_deleted_scans += int(applied.get("upload_batch_scan_events_deleted") or 0)
            upload_deleted_rows += int(applied.get("upload_batch_rows_deleted") or 0)
            upload_batches_done += 1
            cur_state.last_upload_batch_id = int(batch["batch_id"])
            batches += 1
            try:
                cursor.connection.commit()  # type: ignore[attr-defined]
            except Exception:
                pass
        if result["stopped_reason"] is None and not pending:
            result["stopped_reason"] = "upload_caught_up"

    cur_state.last_run_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur_state.last_status = result["stopped_reason"] or "ok"
    save_retention_cursor(cursor, org, cur_state)

    result.update(
        {
            "applied": True,
            "deleted_canonical": deleted_canonical,
            "deleted_upload_scan_events": upload_deleted_scans,
            "deleted_upload_batch_rows": upload_deleted_rows,
            "batches_processed": batches,
            "upload_batches_processed": upload_batches_done,
            "resume_cursor": asdict(cur_state),
        }
    )
    return result


def format_retention_report(plan: dict[str, Any]) -> str:
    lines = [
        "=== Rinse scan retention (DISABLED by default) ===",
        f"org={plan.get('organization_id')} enabled={plan.get('enabled')} "
        f"apply_blocked={plan.get('apply_blocked')}",
    ]
    pol = plan.get("policy") or {}
    lines.append(
        f"upload_retention={pol.get('upload_retention_days')}d "
        f"(floor {pol.get('min_upload_days')}) "
        f"canonical_retention={pol.get('canonical_retention_days')}d "
        f"(floor {pol.get('min_canonical_days')})"
    )
    lines.append(
        f"protected_bags={pol.get('protected_bag_count')} "
        f"epoch_wall={pol.get('wf_reset_epoch_wall')}"
    )
    cur = plan.get("current_state") or {}
    lines.append(
        f"eligible upload_scan_events={cur.get('upload_eligible_scan_events')} "
        f"upload_batch_rows={cur.get('upload_eligible_batch_rows')} "
        f"canonical={cur.get('canonical_eligible_rows')}"
    )
    ss = (plan.get("steady_state") or {}).get("upload") or {}
    if ss:
        lines.append(
            "upload steady-state est: "
            + ", ".join(
                f"{k}={v.get('estimated_rows')}rows/{v.get('estimated_gb')}GB"
                for k, v in ss.items()
            )
        )
    lines.append(f"frequency: {pol.get('frequency_recommendation')}")
    lines.append(
        "parent upload_batches headers: retained "
        f"(purge_headers={pol.get('purge_upload_batch_headers')})"
    )
    return "\n".join(lines)
