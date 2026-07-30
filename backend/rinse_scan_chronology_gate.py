"""Gate Step-1 rebuild/persist when scan chronology is incomplete or stale.

Never commit provisional Completed→Pending downgrades from a partial import.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.ta_helpers import table_exists

STATUS_OK = "ok"
STATUS_REBUILD_DEFERRED = "rebuild_deferred"
STATUS_SCAN_IMPORT_IN_PROGRESS = "scan_import_in_progress"
STATUS_SCAN_CHRONOLOGY_STALE = "scan_chronology_stale"
STATUS_IMPORT_INCOMPLETE = "import_coverage_incomplete"

# Pending bags with zero scan association beyond this count are treated as
# materially incomplete coverage (portal ahead of chronology).
DEFAULT_PORTAL_AHEAD_DEFER_THRESHOLD = 1


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def scrape_import_in_progress(
    cursor,
    organization_id: int,
    *,
    exclude_scrape_run_id: int | None = None,
) -> bool:
    """True when an org scrape run (other than exclude) is still running."""
    if not table_exists(cursor, "rinse_scrape_runs"):
        return False
    org = int(organization_id)
    cursor.execute(
        """
        SELECT id, status
        FROM rinse_scrape_runs
        WHERE organization_id = %s
        ORDER BY id DESC
        LIMIT 6
        """,
        (org,),
    )
    exclude = int(exclude_scrape_run_id) if exclude_scrape_run_id is not None else None
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        rid = row.get("id")
        if exclude is not None and rid is not None and int(rid) == exclude:
            continue
        st = _norm_status(row.get("status"))
        if st in ("running", "in_progress", "started", "importing"):
            return True
    return False


def last_consistent_snapshot_counts(
    day_meta: Mapping[str, Any] | None,
    *,
    cursor=None,
    organization_id: int | None = None,
    shift_date_et: date | None = None,
) -> dict[str, Any]:
    """Completed / Pending / Review from the last persisted snapshot."""
    summary: Mapping[str, Any] = {}
    if day_meta and isinstance(day_meta.get("headline"), Mapping):
        summary = day_meta["headline"]
    elif day_meta and isinstance(day_meta.get("summary"), Mapping):
        summary = day_meta["summary"]

    completed = summary.get("completed")
    pending = summary.get("pending")
    review = None
    exc = summary.get("exceptions") if isinstance(summary.get("exceptions"), Mapping) else {}
    if isinstance(exc, Mapping):
        review = exc.get("review_required")

    # Prefer live day-bag projection when available (authoritative card source).
    if (
        cursor is not None
        and organization_id is not None
        and shift_date_et is not None
        and table_exists(cursor, "rinse_shift_monitor_day_bags")
    ):
        try:
            cursor.execute(
                """
                SELECT LOWER(COALESCE(effective_status, '')) AS st, COUNT(*) AS c
                FROM rinse_shift_monitor_day_bags
                WHERE organization_id = %s AND shift_date_et = %s
                GROUP BY LOWER(COALESCE(effective_status, ''))
                """,
                (int(organization_id), shift_date_et),
            )
            hist = {
                str(r.get("st") or "").strip().lower(): int(r.get("c") or 0)
                for r in (cursor.fetchall() or [])
                if isinstance(r, Mapping)
            }
            if hist:
                completed = hist.get("completed", 0)
                pending = hist.get("pending", 0)
                review = hist.get("review_required", 0)
        except Exception:
            pass

    return {
        "completed": int(completed or 0),
        "pending": int(pending or 0),
        "review_required": int(review or 0),
        "total": int(completed or 0) + int(pending or 0) + int(review or 0),
        "source": "last_consistent_snapshot",
    }


def evaluate_step1_rebuild_gate(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    day_meta: Mapping[str, Any] | None = None,
    pending_bag_ids: Sequence[str] | None = None,
    sample_bag_ids: Sequence[str] | None = None,
    require_freshness_ok: bool = True,
    exclude_scrape_run_id: int | None = None,
    force_incomplete: bool = False,
) -> dict[str, Any]:
    """
    Decide whether Stage B may persist a new Step-1 snapshot.

    Blocks persist when portal/scan pipeline is incomplete or stale so we never
    commit provisional Completed→Pending downgrades.
    """
    from backend.rinse_scan_freshness import freshness_from_day_and_presence

    org = int(organization_id)
    day = operations_date_et
    meta = dict(day_meta or {})
    if not meta:
        try:
            from backend.rinse_veewash_shift_day import get_day_record

            meta = get_day_record(cursor, org, day) or {}
        except Exception:
            meta = {}

    pending_ids = list(pending_bag_ids or [])
    sample_ids = list(sample_bag_ids or [])
    if not pending_ids and isinstance(meta.get("headline"), Mapping):
        bag_ids = ((meta.get("headline") or {}).get("segments") or {}).get("all", {}).get(
            "bag_ids"
        ) or {}
        if isinstance(bag_ids, Mapping):
            pending_ids = list(bag_ids.get("pending") or [])

    freshness = freshness_from_day_and_presence(
        cursor,
        org,
        day,
        day_meta=meta,
        sample_bag_ids=sample_ids or None,
        pending_bag_ids=pending_ids or None,
    )
    import_running = scrape_import_in_progress(
        cursor, org, exclude_scrape_run_id=exclude_scrape_run_id
    )
    portal_ahead = int(freshness.get("portal_ahead_bag_count") or 0)
    status = str(freshness.get("status") or STATUS_OK).strip().lower()

    defer_reason: str | None = None
    defer_status = STATUS_REBUILD_DEFERRED
    if force_incomplete:
        defer_reason = STATUS_IMPORT_INCOMPLETE
        defer_status = STATUS_IMPORT_INCOMPLETE
    elif import_running:
        defer_reason = STATUS_SCAN_IMPORT_IN_PROGRESS
        defer_status = STATUS_SCAN_IMPORT_IN_PROGRESS
    elif require_freshness_ok and status != STATUS_OK:
        defer_reason = status or STATUS_SCAN_CHRONOLOGY_STALE
        defer_status = (
            STATUS_SCAN_CHRONOLOGY_STALE
            if "stale" in (status or "") or status == "incomplete_scrape"
            else STATUS_REBUILD_DEFERRED
        )
    elif portal_ahead >= DEFAULT_PORTAL_AHEAD_DEFER_THRESHOLD:
        defer_reason = STATUS_SCAN_CHRONOLOGY_STALE
        defer_status = STATUS_SCAN_CHRONOLOGY_STALE

    allow = defer_reason is None
    snapshot = last_consistent_snapshot_counts(
        meta, cursor=cursor, organization_id=org, shift_date_et=day
    )
    return {
        "allow_persist": allow,
        "ok": allow,
        "deferred": not allow,
        "reason": defer_reason,
        "step1_refresh_status": "SUCCESS" if allow else "DEFERRED",
        "status": defer_status if not allow else STATUS_OK,
        "rebuild_deferred": not allow,
        "data_freshness": freshness,
        "scan_import_in_progress": import_running,
        "portal_ahead_bag_count": portal_ahead,
        "last_consistent_snapshot": snapshot,
        "message": (
            None
            if allow
            else (
                "Scan chronology updating — counts have not been replaced. "
                "Last consistent snapshot retained."
            )
        ),
    }


def should_preserve_persisted_completion(
    *,
    previous_status: Any,
    incoming_status: Any,
    chronology_complete: bool,
    manager_edit_version: int = 0,
) -> bool:
    """
    Precedence while chronology is incomplete:

    manager decision > previous confirmed persisted completion >
    new complete chronology evidence > temporary incomplete chronology
    """
    if int(manager_edit_version or 0) > 0:
        return True
    if chronology_complete:
        return False
    prev = _norm_status(previous_status)
    incoming = _norm_status(incoming_status)
    if prev in ("completed",) and incoming in (
        "pending",
        "review_required",
        "stale",
        "unfinished_at_close",
        "",
    ):
        return True
    return False


def evaluate_timeline_replace_decision(
    *,
    existing_max: datetime | None,
    existing_n: int,
    incoming_max: datetime | None,
    incoming_n: int,
    existing_completion_events: int = 0,
    incoming_completion_events: int = 0,
    event_id_overlap: int | None = None,
    import_complete: bool = True,
) -> dict[str, Any]:
    """
    Decide whether an incoming export may replace a persisted bag timeline.

    Newer timestamps alone are never enough. Materially thinner or incomplete
    exports must preserve the richer existing timeline.
    """
    reasons: list[str] = []
    if existing_n <= 0:
        return {"replace": True, "reasons": ["no_existing_timeline"], "preserve": False}
    if incoming_n <= 0:
        return {
            "replace": False,
            "preserve": True,
            "reasons": ["incoming_empty"],
            "incomplete": True,
        }
    if not import_complete:
        return {
            "replace": False,
            "preserve": True,
            "reasons": ["import_incomplete_marker"],
            "incomplete": True,
        }
    if existing_max is not None and incoming_max is not None and existing_max > incoming_max:
        return {
            "replace": False,
            "preserve": True,
            "reasons": ["incoming_max_older_than_existing"],
            "incomplete": True,
        }
    # Never wipe a richer timeline with a thinner export — even if newer.
    if incoming_n < existing_n:
        reasons.append("incoming_materially_thinner")
        return {
            "replace": False,
            "preserve": True,
            "reasons": reasons,
            "incomplete": True,
            "existing_n": existing_n,
            "incoming_n": incoming_n,
        }
    if (
        existing_completion_events > 0
        and incoming_completion_events < existing_completion_events
    ):
        reasons.append("incoming_missing_completion_stage_events")
        return {
            "replace": False,
            "preserve": True,
            "reasons": reasons,
            "incomplete": True,
        }
    if event_id_overlap is not None and existing_n > 0:
        overlap_ratio = float(event_id_overlap) / float(existing_n)
        if overlap_ratio < 0.5 and incoming_n <= existing_n:
            reasons.append("low_event_id_overlap")
            return {
                "replace": False,
                "preserve": True,
                "reasons": reasons,
                "incomplete": True,
                "overlap_ratio": overlap_ratio,
            }
    return {"replace": True, "preserve": False, "reasons": ["incoming_complete_or_richer"]}
