"""
Folding performance persistence, recompute, overrides, and aggregates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Sequence

from backend.rinse_bag_completion import COMPLETION_COMPLETED, normalize_bag_id
from backend.rinse_bag_folding import (
    EXCEPTION_CLEAN_BEFORE_FOLDING,
    EXCEPTION_INVALID_TIMESTAMPS,
    EXCEPTION_MISSING_ASSIGNED_USER,
    EXCEPTION_MISSING_CLEAN,
    EXCEPTION_MISSING_FOLDING,
    FOLDING_WARNING_CODES,
    SOURCE_MANUAL,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    evaluate_folding_performance_for_bag,
    registry_is_completed,
)
from backend.rinse_bag_registry import (
    fetch_persistent_scan_events_for_bag,
    get_registry_row,
)
from backend.rinse_folding_settings import get_rinse_folding_benchmarks


def ensure_rinse_folding_performance_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_folding_performance (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'EXCEPTION',
            exception_code VARCHAR(64) NULL,
            folding_start_at DATETIME NULL,
            folding_end_at DATETIME NULL,
            duration_seconds INT NULL,
            folding_start_event_id INT NULL,
            folding_end_event_id INT NULL,
            folding_start_rack VARCHAR(128) NULL,
            folding_end_rack VARCHAR(128) NULL,
            assigned_user_name VARCHAR(255) NULL,
            assigned_user_name_source VARCHAR(32) NULL,
            employee_id INT NULL,
            weight_lbs DECIMAL(8,2) NULL,
            work_date DATE NULL,
            registry_completion_status VARCHAR(24) NULL,
            excluded_from_performance TINYINT(1) NOT NULL DEFAULT 0,
            admin_notes TEXT NULL,
            folding_scan_count INT NULL,
            clean_scan_count INT NULL,
            source_recompute_kind VARCHAR(32) NULL,
            computed_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_rfp_org_bag (organization_id, bag_id),
            KEY idx_rfp_org_work_date (organization_id, work_date),
            KEY idx_rfp_org_user_date (organization_id, assigned_user_name, work_date),
            KEY idx_rfp_org_status (organization_id, status, exception_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_rinse_folding_performance_overrides_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_folding_performance_overrides (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            performance_id INT NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            old_value TEXT NULL,
            new_value TEXT NULL,
            actor_user_id INT NULL,
            notes TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_rfpo_perf (performance_id),
            KEY idx_rfpo_org_bag (organization_id, bag_id),
            KEY idx_rfpo_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_rinse_folding_tables(cursor) -> None:
    ensure_rinse_folding_performance_table(cursor)
    ensure_rinse_folding_performance_overrides_table(cursor)


def get_folding_performance_row(
    cursor, organization_id: int, bag_id: str
) -> dict[str, Any] | None:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    ensure_rinse_folding_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM rinse_folding_performance
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bid),
    )
    return cursor.fetchone()


def _weight_from_registry(registry_row: dict | None) -> float | None:
    if not registry_row:
        return None
    w = registry_row.get("weight_num")
    if w is None:
        return None
    try:
        return float(w)
    except (TypeError, ValueError):
        return None


def _upsert_performance_row(
    cursor,
    organization_id: int,
    bag_id: str,
    fields: dict[str, Any],
    *,
    source_recompute_kind: str | None,
    preserve_excluded: bool = True,
) -> int:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    existing = get_folding_performance_row(cursor, org, bid)
    excluded = 0
    admin_notes = None
    if existing and preserve_excluded:
        excluded = int(existing.get("excluded_from_performance") or 0)
        admin_notes = existing.get("admin_notes")

    cursor.execute(
        """
        INSERT INTO rinse_folding_performance (
            organization_id, bag_id, status, exception_code,
            folding_start_at, folding_end_at, duration_seconds,
            folding_start_event_id, folding_end_event_id,
            folding_start_rack, folding_end_rack,
            assigned_user_name, assigned_user_name_source,
            weight_lbs, work_date, registry_completion_status,
            excluded_from_performance, admin_notes,
            folding_scan_count, clean_scan_count,
            source_recompute_kind, computed_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, NOW()
        )
        ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            exception_code = VALUES(exception_code),
            folding_start_at = VALUES(folding_start_at),
            folding_end_at = VALUES(folding_end_at),
            duration_seconds = VALUES(duration_seconds),
            folding_start_event_id = VALUES(folding_start_event_id),
            folding_end_event_id = VALUES(folding_end_event_id),
            folding_start_rack = VALUES(folding_start_rack),
            folding_end_rack = VALUES(folding_end_rack),
            assigned_user_name = VALUES(assigned_user_name),
            assigned_user_name_source = VALUES(assigned_user_name_source),
            weight_lbs = VALUES(weight_lbs),
            work_date = VALUES(work_date),
            registry_completion_status = VALUES(registry_completion_status),
            folding_scan_count = VALUES(folding_scan_count),
            clean_scan_count = VALUES(clean_scan_count),
            source_recompute_kind = VALUES(source_recompute_kind),
            computed_at = NOW(),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            fields["status"],
            fields.get("exception_code"),
            fields.get("folding_start_at"),
            fields.get("folding_end_at"),
            fields.get("duration_seconds"),
            fields.get("folding_start_event_id"),
            fields.get("folding_end_event_id"),
            fields.get("folding_start_rack"),
            fields.get("folding_end_rack"),
            fields.get("assigned_user_name"),
            fields.get("assigned_user_name_source"),
            fields.get("weight_lbs"),
            fields.get("work_date"),
            fields.get("registry_completion_status"),
            excluded,
            admin_notes,
            fields.get("folding_scan_count"),
            fields.get("clean_scan_count"),
            source_recompute_kind,
        ),
    )
    row = get_folding_performance_row(cursor, org, bid)
    return int(row["id"]) if row else int(cursor.lastrowid or 0)


def apply_folding_performance_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    source_recompute_kind: str = "bag",
) -> dict[str, Any]:
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"bag_id": "", "skipped": True, "reason": "invalid_bag_id"}

    reg = get_registry_row(cursor, org, bid)
    if not reg:
        return {"bag_id": bid, "skipped": True, "reason": "no_registry_row"}
    if not registry_is_completed(reg):
        return {
            "bag_id": bid,
            "skipped": True,
            "reason": "not_completed",
            "completion_status": reg.get("completion_status"),
        }

    events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
    if not events:
        result = evaluate_folding_performance_for_bag([], registry_row=reg)
    else:
        result = evaluate_folding_performance_for_bag(events, registry_row=reg)

    row_fields = result.to_performance_row(
        registry_completion_status=COMPLETION_COMPLETED
    )
    row_fields["weight_lbs"] = _weight_from_registry(reg)

    perf_id = _upsert_performance_row(
        cursor,
        org,
        bid,
        row_fields,
        source_recompute_kind=source_recompute_kind,
    )
    return {
        "bag_id": bid,
        "skipped": False,
        "performance_id": perf_id,
        "status": row_fields["status"],
        "exception_code": row_fields.get("exception_code"),
        "duration_seconds": row_fields.get("duration_seconds"),
        "assigned_user_name": row_fields.get("assigned_user_name"),
        "assigned_user_name_source": row_fields.get("assigned_user_name_source"),
    }


def recompute_folding_performance_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    source_recompute_kind: str = "bag",
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    results: list[dict[str, Any]] = []
    skipped = 0
    processed = 0
    for raw in bag_ids:
        bid = normalize_bag_id(raw)
        if not bid:
            skipped += 1
            continue
        payload = apply_folding_performance_for_bag(
            cursor,
            organization_id,
            bid,
            source_recompute_kind=source_recompute_kind,
        )
        results.append(payload)
        if payload.get("skipped"):
            skipped += 1
        else:
            processed += 1
    payload = {
        "bags_requested": len(bag_ids),
        "bags_processed": processed,
        "bags_skipped": skipped,
        "bags": results,
    }
    payload["summary"] = summarize_recompute_results(results)
    return payload


def summarize_recompute_results(bags: Sequence[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "processed": 0,
        "skipped_not_completed": 0,
        "calculated": 0,
        "exceptions": 0,
        "warnings": 0,
        "errors": 0,
    }
    for b in bags:
        if b.get("skipped"):
            reason = str(b.get("reason") or "")
            if reason == "not_completed":
                summary["skipped_not_completed"] += 1
            else:
                summary["errors"] += 1
            continue
        summary["processed"] += 1
        st = str(b.get("status") or "").upper()
        if st == STATUS_EXCEPTION:
            summary["exceptions"] += 1
        elif st == STATUS_CALCULATED:
            summary["calculated"] += 1
            code = str(b.get("exception_code") or "").upper()
            if code in FOLDING_WARNING_CODES:
                summary["warnings"] += 1
    return summary


def fetch_completed_bag_ids_for_date_range(
    cursor,
    organization_id: int,
    start_date: date,
    end_date: date,
    *,
    date_field: str = "date_clean",
) -> list[str]:
    org = int(organization_id)
    ensure_rinse_folding_tables(cursor)
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table

    ensure_rinse_bag_registry_table(cursor)
    col = "date_clean" if date_field != "completed_at" else "completed_at"
    cursor.execute(
        f"""
        SELECT bag_id FROM rinse_bag_registry
        WHERE organization_id = %s
          AND completion_status = %s
          AND {col} IS NOT NULL
          AND {col} >= %s
          AND {col} <= %s
        ORDER BY bag_id
        """,
        (org, COMPLETION_COMPLETED, start_date, end_date),
    )
    rows = cursor.fetchall() or []
    out: list[str] = []
    for r in rows:
        bid = r.get("bag_id") if isinstance(r, dict) else r[0]
        nb = normalize_bag_id(bid)
        if nb:
            out.append(nb)
    return out


def recompute_folding_performance_for_date_range(
    cursor,
    organization_id: int,
    start_date: date,
    end_date: date,
    *,
    date_field: str = "date_clean",
) -> dict[str, Any]:
    bag_ids = fetch_completed_bag_ids_for_date_range(
        cursor, organization_id, start_date, end_date, date_field=date_field
    )
    payload = recompute_folding_performance_for_bags(
        cursor,
        organization_id,
        bag_ids,
        source_recompute_kind="date_range",
    )
    payload["start_date"] = start_date.isoformat()
    payload["end_date"] = end_date.isoformat()
    payload["date_field"] = date_field
    return payload


def list_folding_performance_rows(
    cursor,
    organization_id: int,
    *,
    status: str | None = None,
    exception_only: bool = False,
    work_date: date | None = None,
    user_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    sql = """
        SELECT p.*,
               r.completion_status AS registry_completion_status_live,
               r.name_clean,
               r.weight_num AS registry_weight_num
        FROM rinse_folding_performance p
        INNER JOIN rinse_bag_registry r
          ON r.organization_id = p.organization_id AND r.bag_id = p.bag_id
        WHERE p.organization_id = %s
          AND r.completion_status = %s
    """
    args: list[Any] = [org, COMPLETION_COMPLETED]
    if exception_only:
        sql += " AND p.status = %s"
        args.append(STATUS_EXCEPTION)
    elif status:
        sql += " AND p.status = %s"
        args.append(status.upper())
    if work_date:
        sql += " AND p.work_date = %s"
        args.append(work_date)
    if user_name:
        sql += " AND p.assigned_user_name = %s"
        args.append(str(user_name).strip())
    sql += " ORDER BY p.work_date DESC, p.computed_at DESC LIMIT %s OFFSET %s"
    args.extend([int(limit), int(offset)])
    cursor.execute(sql, tuple(args))
    return list(cursor.fetchall() or [])


def _serialize_override_value(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


def apply_performance_override(
    cursor,
    organization_id: int,
    bag_id: str,
    payload: dict[str, Any],
    *,
    actor_user_id: int | None,
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        raise ValueError("Invalid bag id")

    row = get_folding_performance_row(cursor, org, bid)
    if not row:
        raise ValueError("Performance row not found; recompute folding for this bag first")

    perf_id = int(row["id"])
    changes: list[tuple[str, Any, Any]] = []

    def _track(field: str, new_val: Any) -> None:
        old_val = row.get(field)
        if old_val == new_val:
            return
        changes.append((field, old_val, new_val))

    if "excluded_from_performance" in payload:
        ex = 1 if payload.get("excluded_from_performance") else 0
        _track("excluded_from_performance", ex)

    if "admin_notes" in payload:
        notes = str(payload.get("admin_notes") or "").strip() or None
        _track("admin_notes", notes)

    if "assigned_user_name" in payload:
        name = str(payload.get("assigned_user_name") or "").strip() or None
        _track("assigned_user_name", name)
        if name:
            _track("assigned_user_name_source", SOURCE_MANUAL)

    for time_field in ("folding_start_at", "folding_end_at"):
        if time_field not in payload:
            continue
        raw = payload.get(time_field)
        if raw is None or raw == "":
            _track(time_field, None)
            continue
        if isinstance(raw, datetime):
            parsed = raw
        elif isinstance(raw, date):
            parsed = datetime.combine(raw, datetime.min.time())
        else:
            s = str(raw).strip()
            try:
                parsed = datetime.fromisoformat(s.replace("Z", "+00:00")[:26])
            except ValueError:
                import pandas as pd

                p = pd.to_datetime(s, errors="coerce")
                parsed = None if pd.isna(p) else p.to_pydatetime()
        _track(time_field, parsed)

    if not changes:
        return {"performance_id": perf_id, "bag_id": bid, "changes": []}

    new_row = dict(row)
    for field, _old, new_val in changes:
        new_row[field] = new_val

    start = new_row.get("folding_start_at")
    end = new_row.get("folding_end_at")
    if isinstance(start, datetime) and isinstance(end, datetime):
        dur = int((end - start).total_seconds())
        if dur > 0:
            new_row["duration_seconds"] = dur
            if new_row.get("status") == STATUS_EXCEPTION and new_row.get("assigned_user_name"):
                hard_codes = {
                    EXCEPTION_MISSING_FOLDING,
                    EXCEPTION_MISSING_CLEAN,
                    EXCEPTION_CLEAN_BEFORE_FOLDING,
                    EXCEPTION_INVALID_TIMESTAMPS,
                    EXCEPTION_MISSING_ASSIGNED_USER,
                }
                if new_row.get("exception_code") in hard_codes:
                    new_row["status"] = STATUS_CALCULATED
                    new_row["exception_code"] = None

    set_parts = []
    args: list[Any] = []
    for field, _old, new_val in changes:
        set_parts.append(f"{field} = %s")
        args.append(new_val)
    if new_row.get("duration_seconds") != row.get("duration_seconds"):
        set_parts.append("duration_seconds = %s")
        args.append(new_row.get("duration_seconds"))
    if new_row.get("status") != row.get("status"):
        set_parts.append("status = %s")
        args.append(new_row.get("status"))
    if new_row.get("exception_code") != row.get("exception_code"):
        set_parts.append("exception_code = %s")
        args.append(new_row.get("exception_code"))

    args.extend([perf_id, org])
    cursor.execute(
        f"""
        UPDATE rinse_folding_performance
        SET {", ".join(set_parts)}, updated_at = NOW()
        WHERE id = %s AND organization_id = %s
        """,
        tuple(args),
    )

    override_ids: list[int] = []
    notes = str(payload.get("notes") or "").strip() or None
    for field, old_val, new_val in changes:
        cursor.execute(
            """
            INSERT INTO rinse_folding_performance_overrides (
                organization_id, performance_id, bag_id,
                field_name, old_value, new_value, actor_user_id, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                org,
                perf_id,
                bid,
                field,
                _serialize_override_value(old_val),
                _serialize_override_value(new_val),
                actor_user_id,
                notes,
            ),
        )
        override_ids.append(int(cursor.lastrowid or 0))

    updated = get_folding_performance_row(cursor, org, bid)
    return {
        "performance_id": perf_id,
        "bag_id": bid,
        "override_ids": override_ids,
        "row": updated,
    }


def aggregate_user_folding_stats(
    cursor,
    organization_id: int,
    user_name: str,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    uname = str(user_name or "").strip()
    if not uname:
        return {"error": "user_name required"}

    cursor.execute(
        """
        SELECT
            p.bag_id,
            p.duration_seconds,
            p.weight_lbs,
            p.work_date,
            p.folding_start_at,
            p.folding_end_at
        FROM rinse_folding_performance p
        INNER JOIN rinse_bag_registry r
          ON r.organization_id = p.organization_id AND r.bag_id = p.bag_id
        WHERE p.organization_id = %s
          AND p.assigned_user_name = %s
          AND p.status = %s
          AND p.excluded_from_performance = 0
          AND r.completion_status = %s
          AND p.work_date >= %s
          AND p.work_date <= %s
        ORDER BY p.folding_start_at ASC
        """,
        (
            org,
            uname,
            STATUS_CALCULATED,
            COMPLETION_COMPLETED,
            period_start,
            period_end,
        ),
    )
    rows = list(cursor.fetchall() or [])
    total_seconds = 0
    total_lbs = 0.0
    bag_count = 0
    gaps: list[dict[str, Any]] = []
    prev_end: datetime | None = None

    prev_bag_id: str | None = None
    for r in rows:
        dur = int(r.get("duration_seconds") or 0)
        if dur <= 0:
            continue
        bag_count += 1
        total_seconds += dur
        w = r.get("weight_lbs")
        if w is not None:
            try:
                total_lbs += float(w)
            except (TypeError, ValueError):
                pass
        start = r.get("folding_start_at")
        end = r.get("folding_end_at")
        if isinstance(start, datetime) and isinstance(end, datetime) and prev_end:
            gap_sec = int((start - prev_end).total_seconds())
            if gap_sec > 0:
                gaps.append(
                    {
                        "gap_seconds": gap_sec,
                        "after_bag_id": prev_bag_id,
                        "before_bag_id": r.get("bag_id"),
                    }
                )
        if isinstance(end, datetime):
            prev_end = end
        prev_bag_id = r.get("bag_id")

    hours = total_seconds / 3600.0 if total_seconds > 0 else 0.0
    bags_per_hour = (bag_count / hours) if hours > 0 else None
    lbs_per_hour = (total_lbs / hours) if hours > 0 else None
    gap_total = sum(g["gap_seconds"] for g in gaps)

    benchmarks = get_rinse_folding_benchmarks(cursor, org)
    return {
        "user_name": uname,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "bag_count": bag_count,
        "total_folding_seconds": total_seconds,
        "total_lbs": round(total_lbs, 2),
        "bags_per_hour": round(bags_per_hour, 4) if bags_per_hour is not None else None,
        "lbs_per_hour": round(lbs_per_hour, 4) if lbs_per_hour is not None else None,
        "gap_seconds_total": gap_total,
        "gap_count": len(gaps),
        "gaps": gaps,
        "benchmarks": benchmarks,
        "vs_target": {
            "bags_per_hour_delta": (
                round(bags_per_hour - benchmarks["bags_per_hour_target"], 4)
                if bags_per_hour is not None
                else None
            ),
            "lbs_per_hour_delta": (
                round(lbs_per_hour - benchmarks["lbs_per_hour_target"], 4)
                if lbs_per_hour is not None
                else None
            ),
        },
    }


def list_folding_performance_overrides(
    cursor, organization_id: int, bag_id: str
) -> list[dict[str, Any]]:
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    ensure_rinse_folding_tables(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, performance_id, bag_id, field_name,
               old_value, new_value, actor_user_id, notes, created_at
        FROM rinse_folding_performance_overrides
        WHERE organization_id = %s AND bag_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (int(organization_id), bid),
    )
    return list(cursor.fetchall() or [])


def folding_period_bounds(
    period: Literal["today", "week"], anchor: date
) -> tuple[date, date]:
    if period == "week":
        week_start = anchor - timedelta(days=anchor.weekday())
        return week_start, week_start + timedelta(days=6)
    return anchor, anchor


def prior_week_bounds(period_start: date) -> tuple[date, date]:
    """Calendar week immediately before the week containing period_start."""
    week_start = period_start - timedelta(days=period_start.weekday())
    prev_end = week_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return prev_start, prev_end


def list_folding_users_in_period(
    cursor,
    organization_id: int,
    period_start: date,
    period_end: date,
) -> list[str]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    cursor.execute(
        """
        SELECT DISTINCT p.assigned_user_name
        FROM rinse_folding_performance p
        INNER JOIN rinse_bag_registry r
          ON r.organization_id = p.organization_id AND r.bag_id = p.bag_id
        WHERE p.organization_id = %s
          AND p.status = %s
          AND p.excluded_from_performance = 0
          AND r.completion_status = %s
          AND p.work_date >= %s
          AND p.work_date <= %s
          AND p.assigned_user_name IS NOT NULL
          AND TRIM(p.assigned_user_name) != ''
        ORDER BY p.assigned_user_name
        """,
        (
            org,
            STATUS_CALCULATED,
            COMPLETION_COMPLETED,
            period_start,
            period_end,
        ),
    )
    names: list[str] = []
    for r in cursor.fetchall() or []:
        n = str(r.get("assigned_user_name") if isinstance(r, dict) else r[0] or "").strip()
        if n:
            names.append(n)
    return names


def _target_status_for_rates(
    bags_per_hour: float | None,
    lbs_per_hour: float | None,
    benchmarks: dict[str, Any],
) -> str:
    if bags_per_hour is None and lbs_per_hour is None:
        return "n/a"
    bags_tgt = float(benchmarks.get("bags_per_hour_target") or 0)
    lbs_tgt = float(benchmarks.get("lbs_per_hour_target") or 0)
    bags_ok = bags_per_hour is not None and bags_per_hour >= bags_tgt
    lbs_ok = lbs_per_hour is not None and lbs_per_hour >= lbs_tgt
    if bags_ok and lbs_ok:
        return "above"
    if bags_per_hour is not None and lbs_per_hour is not None and not bags_ok and not lbs_ok:
        return "below"
    if bags_ok or lbs_ok:
        return "mixed"
    return "n/a"


def _rank_leaderboard_users(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(u: dict[str, Any]) -> tuple:
        lbs_h = u.get("lbs_per_hour")
        bags_h = u.get("bags_per_hour")
        return (
            -(lbs_h if lbs_h is not None else -1),
            -(bags_h if bags_h is not None else -1),
            -(float(u.get("total_lbs") or 0)),
            -(int(u.get("bag_count") or 0)),
            str(u.get("user_name") or "").lower(),
        )

    ranked = sorted(users, key=sort_key)
    for i, u in enumerate(ranked, start=1):
        u["rank"] = i
    return ranked


def _aggregate_team_from_users(users: list[dict[str, Any]]) -> dict[str, Any]:
    total_seconds = sum(int(u.get("total_folding_seconds") or 0) for u in users)
    total_lbs = sum(float(u.get("total_lbs") or 0) for u in users)
    bag_count = sum(int(u.get("bag_count") or 0) for u in users)
    hours = total_seconds / 3600.0 if total_seconds > 0 else 0.0
    bags_per_hour = (bag_count / hours) if hours > 0 else None
    lbs_per_hour = (total_lbs / hours) if hours > 0 else None
    return {
        "bag_count": bag_count,
        "total_lbs": round(total_lbs, 2),
        "total_folding_seconds": total_seconds,
        "bags_per_hour": round(bags_per_hour, 4) if bags_per_hour is not None else None,
        "lbs_per_hour": round(lbs_per_hour, 4) if lbs_per_hour is not None else None,
    }


def aggregate_folding_leaderboard(
    cursor,
    organization_id: int,
    *,
    period: Literal["today", "week"] = "today",
    anchor: date | None = None,
    include_prior_period_winner: bool = True,
) -> dict[str, Any]:
    org = int(organization_id)
    anchor_day = anchor or date.today()
    period_start, period_end = folding_period_bounds(period, anchor_day)
    benchmarks = get_rinse_folding_benchmarks(cursor, org)

    user_names = list_folding_users_in_period(cursor, org, period_start, period_end)
    users: list[dict[str, Any]] = []
    for uname in user_names:
        stats = aggregate_user_folding_stats(cursor, org, uname, period_start, period_end)
        bags_h = stats.get("bags_per_hour")
        lbs_h = stats.get("lbs_per_hour")
        users.append(
            {
                "user_name": uname,
                "bag_count": stats.get("bag_count", 0),
                "total_lbs": stats.get("total_lbs", 0),
                "total_folding_seconds": stats.get("total_folding_seconds", 0),
                "bags_per_hour": bags_h,
                "lbs_per_hour": lbs_h,
                "gap_seconds_total": stats.get("gap_seconds_total", 0),
                "target_status": _target_status_for_rates(bags_h, lbs_h, benchmarks),
                "vs_target": stats.get("vs_target"),
            }
        )

    users = _rank_leaderboard_users(users)
    team = _aggregate_team_from_users(users)

    prior_winner: dict[str, Any] = {
        "available": False,
        "period": "week",
        "period_start": None,
        "period_end": None,
        "user_name": None,
        "bag_count": 0,
        "bags_per_hour": None,
        "lbs_per_hour": None,
        "total_lbs": None,
        "message": "Not enough data yet",
    }
    if include_prior_period_winner:
        pw_start, pw_end = prior_week_bounds(period_start)
        prior_winner["period_start"] = pw_start.isoformat()
        prior_winner["period_end"] = pw_end.isoformat()
        prior_users = list_folding_users_in_period(cursor, org, pw_start, pw_end)
        prior_stats_list: list[dict[str, Any]] = []
        for uname in prior_users:
            ps = aggregate_user_folding_stats(cursor, org, uname, pw_start, pw_end)
            prior_stats_list.append(
                {
                    "user_name": uname,
                    "bag_count": ps.get("bag_count", 0),
                    "total_lbs": ps.get("total_lbs", 0),
                    "bags_per_hour": ps.get("bags_per_hour"),
                    "lbs_per_hour": ps.get("lbs_per_hour"),
                }
            )
        prior_ranked = _rank_leaderboard_users(prior_stats_list)
        if prior_ranked and int(prior_ranked[0].get("bag_count") or 0) > 0:
            top = prior_ranked[0]
            if top.get("lbs_per_hour") is not None:
                prior_winner = {
                    "available": True,
                    "period": "week",
                    "period_start": pw_start.isoformat(),
                    "period_end": pw_end.isoformat(),
                    "user_name": top.get("user_name"),
                    "bag_count": top.get("bag_count", 0),
                    "bags_per_hour": top.get("bags_per_hour"),
                    "lbs_per_hour": top.get("lbs_per_hour"),
                    "total_lbs": top.get("total_lbs"),
                    "message": None,
                }

    generated_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    return {
        "generated_at": generated_at,
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "anchor_date": anchor_day.isoformat(),
        "benchmarks": benchmarks,
        "team": team,
        "users": users,
        "prior_period_winner": prior_winner,
    }
