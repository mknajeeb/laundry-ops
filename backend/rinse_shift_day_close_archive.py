"""Release B: fresh-day close-and-archive (no carryover).

Each ET day is independent. Membership comes only from that day's Rinse scrapes.
At automatic ET rollover or manual batch close:

* Completed rows remain completed.
* Pending + Review Required become ``stale`` (display: Unfinished at Close).
* The day is CLOSED and frozen — unresolved rows are never seeded into the next day.

If the same order appears in a later day's scrape, that day creates its own New Today
row and resolves status from the current cycle. Prior-day rows stay frozen forever.

Does not modify ``rinse_cycle_boundary`` / Release A completion logic.

Transaction / call chain (automatic rollover)
--------------------------------------------
``build_or_load_step1_for_date`` (selected_date_et == today_et, America/New_York)
  → ``ensure_prior_et_day_archived_on_rollover``
      → yesterday = today - 1 day  (only immediately preceding ET date)
      → refuse if target == today
      → ``finalize_day_close_archive(mode=automatic)``
          → ``SELECT … FOR UPDATE`` day row (org-scoped)
          → if already CLOSED → no-op return
          → load day bags → archive unresolved → rewrite closed headline
          → ``UPDATE … SET status=CLOSED WHERE status IN (OPEN,READY_TO_CLOSE,REOPENED)``
            (rowcount 0 ⇒ another request won; reload as already_closed)
          → audit CLOSE_ARCHIVE_AUTO
  → ``_commit(cursor)`` when archive ok
  → build today from today's scrapes only (no seed)

Manual close uses the same ``finalize_day_close_archive(mode=manual)`` and the same
lock / conditional UPDATE. Frontend expected counts are advisory only; live counts
are recomputed. Material mismatch → conflict (no close).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
)

logger = logging.getLogger(__name__)

OUTCOME_STALE = "stale"
STALE_DISPLAY_LABEL = "Unfinished at Close"
DAY_CLOSE_STATUS_STALE = "stale"
BAG_CLOSE_REASON_UNRESOLVED = "unresolved_at_close"
UNFINISHED_AT_CLOSE_KEY = "unfinished_at_close"
CLOSE_CONFLICT_ERROR = "close_confirmation_stale"

_UNRESOLVED_STATUSES = frozenset(
    {
        OUTCOME_PENDING,
        "pending",
        OUTCOME_REVIEW_REQUIRED,
        "review_required",
    }
)

_CLOSABLE_STATUSES = frozenset({"OPEN", "READY_TO_CLOSE", "REOPENED"})


def is_unresolved_effective_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    if not s:
        return False
    if s in _UNRESOLVED_STATUSES:
        return True
    if s == OUTCOME_STALE or s == "unfinished_at_close":
        return False
    if s == OUTCOME_COMPLETED or s.endswith("_completed"):
        return False
    if s in ("excluded", "exclude"):
        return False
    if "pending" in s or "review" in s:
        return True
    return False


def is_stale_effective_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s in (OUTCOME_STALE, "unfinished_at_close", "stale_for_day")


def close_archive_counts_from_bags(
    day_bags: list[Mapping[str, Any]] | None,
) -> dict[str, int]:
    """Completed vs unfinished from live day bags (recomputed at close time)."""
    completed = 0
    unfinished = 0
    unfinished_pending = 0
    unfinished_review = 0
    excluded = 0
    for bag in day_bags or []:
        eff = str(bag.get("effective_status") or "").strip().lower()
        snap = bag.get("bag_snapshot") if isinstance(bag.get("bag_snapshot"), dict) else {}
        pre = str((snap or {}).get("pre_close_status") or "").strip().lower()
        if eff in ("excluded", "exclude"):
            excluded += 1
            continue
        if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
            completed += 1
            continue
        if is_stale_effective_status(eff):
            unfinished += 1
            if pre in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in pre:
                unfinished_review += 1
            else:
                unfinished_pending += 1
            continue
        if is_unresolved_effective_status(eff):
            unfinished += 1
            if eff in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in eff:
                unfinished_review += 1
            else:
                unfinished_pending += 1
            continue
        unfinished += 1
        unfinished_pending += 1
    return {
        "completed": completed,
        "unfinished": unfinished,
        "unfinished_from_pending": unfinished_pending,
        "unfinished_from_review_required": unfinished_review,
        "approved_excluded": excluded,
        "total": completed + unfinished,
    }


def build_close_confirmation_summary(
    day_bags: list[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Payload for Manual Close Batch confirmation UI (advisory until confirm)."""
    counts = close_archive_counts_from_bags(day_bags)
    return {
        "completed": counts["completed"],
        "unfinished": counts["unfinished"],
        "unfinished_from_pending": counts["unfinished_from_pending"],
        "unfinished_from_review_required": counts["unfinished_from_review_required"],
        "approved_excluded": counts["approved_excluded"],
        "total": counts["total"],
        "prompt": "Close and archive this day?",
        "unfinished_label": STALE_DISPLAY_LABEL,
        "model": "fresh_day_close_archive",
        "carryover_used": False,
        "prior_day_seeding_used": False,
        "counts_are_advisory": True,
        "note": "Counts are recomputed at confirmation from the latest live day bags.",
    }


def _json_dump(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).decode("utf-8", errors="replace")
    if isinstance(val, str):
        return val
    return json.dumps(val, default=str, separators=(",", ":"))


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _lock_day_row_for_update(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> dict[str, Any] | None:
    """Org-scoped row lock. Blocks concurrent archive of the same day."""
    from backend.rinse_veewash_shift_day import ensure_shift_monitor_day_tables, get_day_record

    ensure_shift_monitor_day_tables(cursor)
    try:
        cursor.execute(
            """
            SELECT id, organization_id, shift_date_et, status, opened_at, last_sync_at,
                   closed_at, closed_by_user_id, closed_by_display_name, close_reason,
                   close_override, reopen_count, review_required_count, created_at, updated_at,
                   headline_json, workload_meta_json
            FROM rinse_shift_monitor_days
            WHERE organization_id = %s AND shift_date_et = %s
            LIMIT 1
            FOR UPDATE
            """,
            (int(organization_id), shift_date_et),
        )
        row = cursor.fetchone()
    except Exception:
        return get_day_record(cursor, organization_id, shift_date_et)
    if row is None:
        return None
    if not isinstance(row, dict):
        # Test doubles may return non-mapping rows; fall back.
        return get_day_record(cursor, organization_id, shift_date_et)
    from backend.rinse_veewash_shift_day import _json_load as day_json_load

    out = dict(row)
    if "headline" in out and "headline_json" not in out:
        return out
    out["headline"] = day_json_load(out.pop("headline_json", None))
    out["workload_meta"] = day_json_load(out.pop("workload_meta_json", None))
    return out


def archive_unresolved_day_bags(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    day_bags: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mark pending/review day bags stale. Completed unchanged. Idempotent.

    Preserves pre_close_status, review reason codes, and close_reason in snapshot.
    """
    from backend.rinse_veewash_shift_day import load_day_bags

    bags = list(day_bags) if day_bags is not None else load_day_bags(
        cursor, organization_id, shift_date_et
    )
    unfinished_ids: list[str] = []
    completed_ids: list[str] = []
    from_pending: list[str] = []
    from_review: list[str] = []
    changed = 0
    for bag in bags:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        eff = str(bag.get("effective_status") or "").strip().lower()
        snap = dict(bag.get("bag_snapshot") or {})
        if not snap and bag.get("bag_snapshot_json"):
            snap = dict(_json_load(bag.get("bag_snapshot_json")) or {})

        if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
            completed_ids.append(bid)
            continue
        if eff in ("excluded", "exclude"):
            continue
        if is_stale_effective_status(eff):
            unfinished_ids.append(bid)
            pre = str(snap.get("pre_close_status") or "").strip().lower()
            if pre in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in pre:
                from_review.append(bid)
            else:
                from_pending.append(bid)
            continue
        if not is_unresolved_effective_status(eff):
            unfinished_ids.append(bid)
            from_pending.append(bid)
            continue

        prior_reasons = list(
            bag.get("review_reason_codes")
            or snap.get("review_reason_codes")
            or snap.get("pre_close_review_reason_codes")
            or []
        )
        was_review = eff in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in eff
        snap["pre_close_status"] = eff or OUTCOME_PENDING
        snap["day_close_status"] = DAY_CLOSE_STATUS_STALE
        snap["day_close_label"] = STALE_DISPLAY_LABEL
        snap["close_reason"] = BAG_CLOSE_REASON_UNRESOLVED
        snap["closed_on_date_et"] = shift_date_et.isoformat()
        if prior_reasons:
            snap["pre_close_review_reason_codes"] = prior_reasons
            # Keep a durable copy of review evidence on the snapshot.
            snap["review_reason_codes"] = list(prior_reasons)
        if was_review:
            snap["pre_close_was_review_required"] = True
        else:
            snap["pre_close_was_pending"] = True

        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET effective_status=%s,
                review_reason_codes_json=%s,
                bag_snapshot_json=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE organization_id=%s
              AND shift_date_et=%s
              AND bag_id=%s
              AND LOWER(COALESCE(effective_status, '')) NOT IN ('stale', 'completed')
            """,
            (
                OUTCOME_STALE,
                # Active queue no longer shows review; history lives in snapshot.
                _json_dump([]),
                _json_dump(snap),
                int(organization_id),
                shift_date_et,
                bid,
            ),
        )
        if getattr(cursor, "rowcount", 1) != 0:
            changed += 1
        unfinished_ids.append(bid)
        if was_review:
            from_review.append(bid)
        else:
            from_pending.append(bid)
        bag["effective_status"] = OUTCOME_STALE
        bag["review_reason_codes"] = []
        bag["bag_snapshot"] = snap

    return {
        "changed": changed,
        "completed_ids": sorted(set(completed_ids)),
        "unfinished_ids": sorted(set(unfinished_ids)),
        "unfinished_from_pending_ids": sorted(set(from_pending)),
        "unfinished_from_review_required_ids": sorted(set(from_review)),
        "completed": len(set(completed_ids)),
        "unfinished": len(set(unfinished_ids)),
        "unfinished_from_pending": len(set(from_pending)),
        "unfinished_from_review_required": len(set(from_review)),
    }


def apply_closed_day_headline(
    headline: Mapping[str, Any] | None,
    *,
    completed_ids: list[str],
    unfinished_ids: list[str],
    unfinished_from_pending_ids: list[str] | None = None,
    unfinished_from_review_required_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Rewrite headline for CLOSED days: Total = Completed + Unfinished at Close.

    Preserves New Today / membership / rush segment identity lists; only status
    buckets move pending+review → unfinished_at_close.
    """
    out = dict(headline or {})
    completed = sorted({normalize_bag_id(x) for x in completed_ids if normalize_bag_id(x)})
    unfinished = sorted({normalize_bag_id(x) for x in unfinished_ids if normalize_bag_id(x)})
    from_pending = sorted(
        {
            normalize_bag_id(x)
            for x in (unfinished_from_pending_ids or [])
            if normalize_bag_id(x)
        }
    )
    from_review = sorted(
        {
            normalize_bag_id(x)
            for x in (unfinished_from_review_required_ids or [])
            if normalize_bag_id(x)
        }
    )
    total = len(completed) + len(unfinished)

    # Preserve membership counters when present.
    new_today = out.get("new_today")
    carryover = out.get("carryover")

    out["completed"] = len(completed)
    out["pending"] = 0
    out["unfinished_at_close"] = len(unfinished)
    out["unfinished_from_pending"] = len(from_pending)
    out["unfinished_from_review_required"] = len(from_review)
    out["active_workload"] = total
    out["total_workload"] = total
    out["completed_count"] = len(completed)
    out["pending_count"] = 0
    out["unfinished_at_close_count"] = len(unfinished)
    out["review_required_count"] = 0
    if new_today is not None:
        out["new_today"] = new_today
    if carryover is not None:
        out["carryover"] = 0 if carryover else carryover
    exc = dict(out.get("exceptions") or {})
    exc["review_required"] = 0
    exc["unfinished_at_close"] = len(unfinished)
    exc["total"] = 0
    out["exceptions"] = exc
    out["close_archive"] = {
        "model": "fresh_day_close_archive",
        "unfinished_label": STALE_DISPLAY_LABEL,
        "carryover_used": False,
        "prior_day_seeding_used": False,
        "unfinished_from_pending": len(from_pending),
        "unfinished_from_review_required": len(from_review),
    }

    segments = dict(out.get("segments") or {})
    for seg_name, seg in list(segments.items()):
        if not isinstance(seg, dict):
            continue
        seg_out = dict(seg)
        bag_ids = dict(seg_out.get("bag_ids") or {})
        # Preserve membership identity lists (new_today / carryover / rush filters).
        prior_pending = list(bag_ids.get("pending") or [])
        prior_review = list(bag_ids.get("review_required") or [])
        prior_completed = list(bag_ids.get("completed") or [])
        if str(seg_name).lower() == "all":
            bag_ids["completed"] = completed
            bag_ids["unfinished_at_close"] = unfinished
            bag_ids["unfinished_from_pending"] = from_pending
            bag_ids["unfinished_from_review_required"] = from_review
            bag_ids["pending"] = []
            bag_ids["review_required"] = []
            seg_out["completed"] = len(completed)
            seg_out["pending"] = 0
            seg_out["unfinished_at_close"] = len(unfinished)
            seg_out["active_workload"] = total
            seg_out["total_workload"] = total
        else:
            seg_unfinished = sorted(
                {
                    normalize_bag_id(x)
                    for x in (
                        prior_pending
                        + prior_review
                        + list(bag_ids.get(UNFINISHED_AT_CLOSE_KEY) or [])
                    )
                    if normalize_bag_id(x)
                }
            )
            seg_completed = sorted(
                {normalize_bag_id(x) for x in prior_completed if normalize_bag_id(x)}
            )
            bag_ids["completed"] = seg_completed
            bag_ids["unfinished_at_close"] = seg_unfinished
            bag_ids["pending"] = []
            bag_ids["review_required"] = []
            seg_total = len(seg_completed) + len(seg_unfinished)
            seg_out["completed"] = len(seg_completed)
            seg_out["pending"] = 0
            seg_out["unfinished_at_close"] = len(seg_unfinished)
            seg_out["active_workload"] = seg_total
            seg_out["total_workload"] = seg_total
        if "new_today" in seg_out or "new_today" in bag_ids:
            # Leave new_today membership counts/lists untouched.
            pass
        seg_exc = dict(seg_out.get("exceptions") or {})
        seg_exc["review_required"] = 0
        seg_exc["unfinished_at_close"] = int(seg_out.get("unfinished_at_close") or 0)
        seg_exc["total"] = 0
        seg_out["exceptions"] = seg_exc
        seg_out["bag_ids"] = bag_ids
        segments[seg_name] = seg_out
    out["segments"] = segments
    return out


def persist_closed_day_headline(
    cursor,
    organization_id: int,
    shift_date_et: date,
    headline: Mapping[str, Any],
    *,
    review_required_count: int = 0,
) -> None:
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET headline_json=%s,
            review_required_count=%s,
            updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (
            _json_dump(headline),
            int(review_required_count),
            int(organization_id),
            shift_date_et,
        ),
    )


def finalize_day_close_archive(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    reason: str | None = None,
    mode: str = "manual",
    checklist: Mapping[str, Any] | None = None,
    expected_completed: int | None = None,
    expected_unfinished: int | None = None,
    allow_close_today: bool = True,
) -> dict[str, Any]:
    """Archive-close a day: stale unresolved rows, freeze CLOSED, no next-day seed.

    Concurrency: SELECT … FOR UPDATE + conditional status UPDATE.
    Idempotent: already CLOSED → no bag/headline mutation.
    Automatic mode refuses to close ``today_et`` (only yesterday is eligible).
    """
    from backend.rinse_veewash_shift_day import (
        STATUS_CLOSED,
        STATUS_NOT_STARTED,
        _write_audit,
        get_day_record,
        load_day_bags,
        summary_from_day_record,
    )
    from backend.rinse_veewash_workload import today_et

    org = int(organization_id)
    today = today_et()

    if mode == "automatic" and shift_date_et >= today:
        return {
            "ok": False,
            "error": "cannot_auto_close_today_or_future",
            "message": "Automatic rollover may only archive the immediately preceding ET day.",
            "today_et": today.isoformat(),
            "shift_date_et": shift_date_et.isoformat(),
        }
    if mode == "automatic" and shift_date_et != today - timedelta(days=1):
        return {
            "ok": False,
            "error": "auto_close_only_yesterday",
            "message": "Automatic rollover only targets yesterday (America/New_York).",
            "today_et": today.isoformat(),
            "shift_date_et": shift_date_et.isoformat(),
        }
    if not allow_close_today and shift_date_et >= today and mode == "manual":
        return {
            "ok": False,
            "error": "cannot_close_today",
            "message": "Closing today's live day is disabled by policy.",
            "day": None,
        }

    existing = _lock_day_row_for_update(cursor, org, shift_date_et)
    if not existing:
        return {"ok": False, "error": "day_not_found", "day": None}

    existing_org = existing.get("organization_id")
    if existing_org is not None and int(existing_org) != org:
        return {"ok": False, "error": "organization_mismatch", "day": None}

    if existing.get("status") == STATUS_NOT_STARTED:
        return {
            "ok": False,
            "error": "shift_not_started",
            "message": "Shift has not started — nothing to close.",
            "day": existing,
        }

    if existing.get("status") == STATUS_CLOSED:
        # Already CLOSED — do not modify bags or headline.
        return {
            "ok": True,
            "already_closed": True,
            "modified": False,
            "mode": mode,
            "day": existing,
            "confirmation": build_close_confirmation_summary(
                load_day_bags(cursor, org, shift_date_et)
            ),
            "archive": {
                "changed": 0,
                "completed": 0,
                "unfinished": 0,
                "completed_ids": [],
                "unfinished_ids": [],
            },
            "validation": {
                "ok": True,
                "model": "fresh_day_close_archive",
                "checklist": {"archived": True, "already_closed": True},
            },
        }

    day_bags = load_day_bags(cursor, org, shift_date_et)
    live_counts = close_archive_counts_from_bags(day_bags)
    confirmation = build_close_confirmation_summary(day_bags)

    conflict = None
    if expected_completed is not None or expected_unfinished is not None:
        mismatches: list[str] = []
        if expected_completed is not None and int(expected_completed) != int(
            live_counts["completed"]
        ):
            mismatches.append("completed")
        if expected_unfinished is not None and int(expected_unfinished) != int(
            live_counts["unfinished"]
        ):
            mismatches.append("unfinished")
        if mismatches:
            return {
                "ok": False,
                "error": CLOSE_CONFLICT_ERROR,
                "message": (
                    "Day counts changed since the close dialog opened. "
                    "Refresh and confirm again."
                ),
                "mismatches": mismatches,
                "expected": {
                    "completed": expected_completed,
                    "unfinished": expected_unfinished,
                },
                "live": live_counts,
                "confirmation": confirmation,
                "day": existing,
            }

    prev = existing.get("status")
    archived = archive_unresolved_day_bags(
        cursor, org, shift_date_et, day_bags=day_bags
    )
    base_headline = (
        existing.get("headline")
        if isinstance(existing.get("headline"), dict)
        else {}
    )
    if not base_headline:
        base_headline = summary_from_day_record(
            existing, cursor=cursor, organization_id=org
        ) or {}
    headline = apply_closed_day_headline(
        base_headline,
        completed_ids=archived["completed_ids"],
        unfinished_ids=archived["unfinished_ids"],
        unfinished_from_pending_ids=archived.get("unfinished_from_pending_ids"),
        unfinished_from_review_required_ids=archived.get(
            "unfinished_from_review_required_ids"
        ),
    )

    now = datetime.utcnow()
    close_reason = reason or (
        "Automatic ET day rollover archive"
        if mode == "automatic"
        else "Manual close and archive"
    )
    # Conditional update — only one concurrent closer wins.
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET status=%s, closed_at=%s, closed_by_user_id=%s, closed_by_display_name=%s,
            close_reason=%s, close_override=%s, review_required_count=%s,
            headline_json=%s, updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s
          AND shift_date_et=%s
          AND status IN ('OPEN', 'READY_TO_CLOSE', 'REOPENED')
        """,
        (
            STATUS_CLOSED,
            now,
            actor_user_id,
            actor_display_name or ("system:et_rollover" if mode == "automatic" else None),
            close_reason,
            0,
            0,
            _json_dump(headline),
            org,
            shift_date_et,
        ),
    )
    won = False
    try:
        won = int(getattr(cursor, "rowcount", 0) or 0) > 0
    except Exception:
        # Test doubles may use MagicMock rowcount.
        won = True
    if not won:
        # Another request closed first — treat as idempotent already_closed.
        day = get_day_record(cursor, org, shift_date_et)
        return {
            "ok": True,
            "already_closed": True,
            "modified": False,
            "lost_race": True,
            "mode": mode,
            "day": day,
            "confirmation": confirmation,
            "archive": archived,
            "final_counts": {
                "completed": archived["completed"],
                "unfinished": archived["unfinished"],
                "total": archived["completed"] + archived["unfinished"],
            },
            "validation": {
                "ok": True,
                "model": "fresh_day_close_archive",
                "checklist": {"archived": True, "lost_race": True},
            },
        }

    _write_audit(
        cursor,
        org,
        shift_date_et,
        action="CLOSE_ARCHIVE" if mode == "manual" else "CLOSE_ARCHIVE_AUTO",
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name
        or ("system:et_rollover" if mode == "automatic" else None),
        reason=close_reason,
        previous_status=prev,
        new_status=STATUS_CLOSED,
        checklist=checklist
        or {
            "model": "fresh_day_close_archive",
            "carryover_used": False,
            "prior_day_seeding_used": False,
            "mode": mode,
            "timezone": "America/New_York",
        },
        totals={
            "completed": archived["completed"],
            "unfinished": archived["unfinished"],
            "unfinished_from_pending": archived.get("unfinished_from_pending"),
            "unfinished_from_review_required": archived.get(
                "unfinished_from_review_required"
            ),
            "pending": 0,
            "review_required": 0,
            "active": archived["completed"] + archived["unfinished"],
        },
    )
    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(org, shift_date_et)
    except Exception:
        pass

    # Explicitly do NOT seed next-day membership / carryover.
    day = get_day_record(cursor, org, shift_date_et)
    final_counts = {
        "completed": archived["completed"],
        "unfinished": archived["unfinished"],
        "unfinished_from_pending": archived.get("unfinished_from_pending"),
        "unfinished_from_review_required": archived.get(
            "unfinished_from_review_required"
        ),
        "total": archived["completed"] + archived["unfinished"],
    }
    return {
        "ok": True,
        "already_closed": False,
        "modified": True,
        "mode": mode,
        "day": day,
        "confirmation": confirmation,
        "final_counts": final_counts,
        "archive": archived,
        "validation": {
            "ok": True,
            "model": "fresh_day_close_archive",
            "checklist": {
                "archived": True,
                "carryover_used": False,
                "prior_day_seeding_used": False,
                "timezone": "America/New_York",
            },
            "totals": {
                "completed": archived["completed"],
                "unfinished": archived["unfinished"],
                "pending": 0,
                "review_required": 0,
                "active": archived["completed"] + archived["unfinished"],
            },
        },
    }


def ensure_prior_et_day_archived_on_rollover(
    cursor,
    organization_id: int,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Idempotent: if yesterday is still open, archive-close it before building today.

    Only the immediately preceding ET date is eligible. Today is never closed here.
    Does not create today's membership — caller builds today from today's scrapes.
    """
    from backend.rinse_veewash_shift_day import (
        STATUS_CLOSED,
        STATUS_NOT_STARTED,
        get_day_record,
    )
    from backend.rinse_veewash_workload import today_et

    today = today or today_et()
    yesterday = today - timedelta(days=1)
    # Safety: never target today.
    if yesterday >= today:
        return None

    prior = get_day_record(cursor, int(organization_id), yesterday)
    if not prior:
        return None
    if int(prior.get("organization_id") or 0) not in (0, int(organization_id)):
        # organization_id is always in the query predicate; belt-and-suspenders.
        if int(prior.get("organization_id") or 0) != int(organization_id):
            return None
    status = str(prior.get("status") or "").strip().upper()
    if status in ("", STATUS_NOT_STARTED):
        return None
    if status == STATUS_CLOSED:
        # Already closed — no modification (finalize short-circuits).
        return finalize_day_close_archive(
            cursor,
            int(organization_id),
            yesterday,
            mode="automatic",
            reason="Automatic ET day rollover archive (idempotent)",
        )
    return finalize_day_close_archive(
        cursor,
        int(organization_id),
        yesterday,
        mode="automatic",
        reason="Automatic ET day rollover archive",
    )
