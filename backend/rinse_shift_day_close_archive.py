"""Operational carryforward day-close archive.

Each ET day is independent for New Today admits (today's scrapes). At automatic
ET rollover or manual batch close, every bag is classified:

* **completed** — stays completed; never carried.
* **review** — stays ``review_required`` (Missing From Portal, Specialty,
  Service Classification, any already-``review_required`` / reason-coded
  Management review exception); never carried. Hidden/provisional split
  evaluator signals do **not** promote pending → review at close.
* **operationally unfinished pending** — becomes ``carried_forward`` (not left
  as pending on the closed day).

Closed-day display: Completed / Review / Carried Forward (pending = 0).
Closed Workload = Completed + Review + Carried Forward.

Next day Opening Carryover comes only from prior-day ``carried_forward`` IDs
(see ``_load_prior_day_membership_ids``). ``OUTCOME_STALE`` remains only for
reading legacy Release-B closed days (Unfinished at Close).

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
  → build today from today's scrapes + opening carryover from prior carried_forward

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

OUTCOME_CARRIED_FORWARD = "carried_forward"
# Legacy Release B closed-day status (read-only compatibility).
OUTCOME_STALE = "stale"
STALE_DISPLAY_LABEL = "Unfinished at Close"
CARRIED_FORWARD_DISPLAY_LABEL = "Carried Forward"
DAY_CLOSE_STATUS_CARRIED = "carried_forward"
DAY_CLOSE_STATUS_REVIEW = "review_required"
DAY_CLOSE_STATUS_STALE = "stale"
BAG_CLOSE_REASON_CARRIED = "carried_forward_at_close"
BAG_CLOSE_REASON_REVIEW = "review_retained_at_close"
BAG_CLOSE_REASON_UNRESOLVED = "unresolved_at_close"  # legacy stale path
UNFINISHED_AT_CLOSE_KEY = "unfinished_at_close"
CLOSE_CONFLICT_ERROR = "close_confirmation_stale"
CLOSE_ARCHIVE_MODEL = "operational_carryforward_close"

_UNRESOLVED_STATUSES = frozenset(
    {
        OUTCOME_PENDING,
        "pending",
        OUTCOME_REVIEW_REQUIRED,
        "review_required",
    }
)

_CLOSABLE_STATUSES = frozenset({"OPEN", "READY_TO_CLOSE", "REOPENED"})

# Review-category reason codes that promote pending → review at close.
# Split-evaluator codes are intentionally excluded — hidden/provisional split
# must not block operational carryforward.
_REVIEW_EXCEPTION_REASON_CODES = frozenset(
    {
        "DISAPPEARED_WITHOUT_COMPLETION",
        "WF_BULK_WORKITEM_REVIEW",
        "WF_ZERO_OR_MISSING_POST_WEIGHT",
        "WF_ZERO_OR_MISSING_WEIGHT",
        "COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
        "SERVICE_CLASSIFICATION_MISMATCH",
        "MANAGER_SENT_FOR_REVIEW",
        "COMPLETION_DETAILS_MISSING",
        "MISSING_PRE_EVIDENCE",
        "SCAN_CHRONOLOGY_STALE",
        "HD_REVIEW_REQUIRED",
        "HD_COMPLETION_DETAILS_MISSING",
    }
)


def is_unresolved_effective_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    if not s:
        return False
    if s in _UNRESOLVED_STATUSES:
        return True
    if s == OUTCOME_CARRIED_FORWARD:
        return False
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


def is_carried_forward_effective_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s in (OUTCOME_CARRIED_FORWARD, "carried_forward")


def _norm_reason_codes(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return [raw] if raw.strip() else []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(c).strip() for c in raw if str(c or "").strip()]


def _reasons_are_review_exception(codes: list[str] | None) -> bool:
    for code in codes or []:
        c = str(code or "").strip().upper()
        if not c:
            continue
        # Split evaluator / provisional split signals never block carry.
        if "SPLIT" in c or c == "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER":
            continue
        if c in _REVIEW_EXCEPTION_REASON_CODES:
            return True
        if "REVIEW" in c or "DISAPPEARED" in c or "MISMATCH" in c:
            return True
    return False


def _collect_headline_review_exception_ids(
    headline: Mapping[str, Any] | None,
) -> set[str]:
    """Specialty / Missing queues from headline (if present).

    Split Order Review is intentionally excluded: the live/hidden split
    evaluator must not block operational pending → carried_forward at close.
    """
    out: set[str] = set()
    if not isinstance(headline, Mapping) or not headline:
        return out
    try:
        from backend.management_rinse_wf_review import (
            CATEGORY_MISSING_PORTAL,
            CATEGORY_SPECIALTY,
            split_review_categories,
        )

        split = split_review_categories(headline)
        for key in (CATEGORY_SPECIALTY, CATEGORY_MISSING_PORTAL):
            for bid in split.get(key) or []:
                nb = normalize_bag_id(bid)
                if nb:
                    out.add(nb)
    except Exception:
        logger.debug("split_review_categories unavailable during close", exc_info=True)
    return out


def _collect_split_review_required_ids(
    cursor,
    organization_id: int,
    shift_date_et: date,
    pending_ids: list[str],
) -> set[str]:
    """Deprecated for close promotion — always empty.

    Hidden / provisional split evaluation must not block carryforward. Day-close
    keeps already-``review_required`` rows and reason-coded Management
    exceptions; operational pending becomes ``carried_forward``.
    """
    return set()


def close_archive_counts_from_bags(
    day_bags: list[Mapping[str, Any]] | None,
) -> dict[str, int]:
    """Live close preview: completed / review / carried_forward (pending → carry)."""
    completed = 0
    review = 0
    carried = 0
    excluded = 0
    for bag in day_bags or []:
        eff = str(bag.get("effective_status") or "").strip().lower()
        snap = bag.get("bag_snapshot") if isinstance(bag.get("bag_snapshot"), dict) else {}
        pre = str((snap or {}).get("pre_close_status") or "").strip().lower()
        reasons = _norm_reason_codes(
            bag.get("review_reason_codes")
            or (snap or {}).get("review_reason_codes")
            or (snap or {}).get("pre_close_review_reason_codes")
        )
        if eff in ("excluded", "exclude"):
            excluded += 1
            continue
        if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
            completed += 1
            continue
        if is_carried_forward_effective_status(eff):
            carried += 1
            continue
        if eff in (OUTCOME_REVIEW_REQUIRED, "review_required") or (
            "review" in eff and not is_stale_effective_status(eff)
        ):
            review += 1
            continue
        if is_stale_effective_status(eff):
            # Legacy closed rows: classify by pre_close when present.
            if pre in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in pre:
                review += 1
            else:
                carried += 1
            continue
        if is_unresolved_effective_status(eff):
            if (
                eff in (OUTCOME_REVIEW_REQUIRED, "review_required")
                or "review" in eff
                or _reasons_are_review_exception(reasons)
            ):
                review += 1
            else:
                carried += 1
            continue
        carried += 1
    total = completed + review + carried
    return {
        "completed": completed,
        "review": review,
        "review_required": review,
        "carried_forward": carried,
        # Compatibility aliases for older close-dialog expected_unfinished.
        "unfinished": carried,
        "unfinished_from_pending": carried,
        "unfinished_from_review_required": 0,
        "approved_excluded": excluded,
        "total": total,
    }


def build_close_confirmation_summary(
    day_bags: list[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Payload for Manual Close Batch confirmation UI (advisory until confirm)."""
    counts = close_archive_counts_from_bags(day_bags)
    return {
        "completed": counts["completed"],
        "review": counts["review"],
        "review_required": counts["review"],
        "carried_forward": counts["carried_forward"],
        "unfinished": counts["unfinished"],
        "unfinished_from_pending": counts["unfinished_from_pending"],
        "unfinished_from_review_required": counts["unfinished_from_review_required"],
        "approved_excluded": counts["approved_excluded"],
        "total": counts["total"],
        "prompt": "Close day and carry unfinished operational bags forward?",
        "carried_forward_label": CARRIED_FORWARD_DISPLAY_LABEL,
        "unfinished_label": CARRIED_FORWARD_DISPLAY_LABEL,
        "model": CLOSE_ARCHIVE_MODEL,
        "carryover_used": True,
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


def _bag_service_type(bag: Mapping[str, Any], snap: Mapping[str, Any] | None = None) -> str:
    snap = snap or {}
    raw = (
        bag.get("service_type")
        or snap.get("service_type")
        or snap.get("portal_service_type")
        or "WF"
    )
    return str(raw or "WF").strip().upper() or "WF"


def archive_unresolved_day_bags(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    day_bags: list[Mapping[str, Any]] | None = None,
    headline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify day bags at close: completed / review / carried_forward.

    Idempotent. Completed and excluded unchanged. Already ``review_required``
    stays review (reason codes preserved). Pending review-exceptions become
    ``review_required``. Other **WF** pending become ``carried_forward``.
    **HD** unfinished pending becomes legacy ``stale`` (HD has no next-day
    Opening Carryover).
    """
    from backend.rinse_veewash_shift_day import load_day_bags

    bags = list(day_bags) if day_bags is not None else load_day_bags(
        cursor, organization_id, shift_date_et
    )
    completed_ids: list[str] = []
    review_ids: list[str] = []
    carried_ids: list[str] = []
    hd_stale_ids: list[str] = []
    changed = 0

    pending_candidates: list[str] = []
    for bag in bags:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        eff = str(bag.get("effective_status") or "").strip().lower()
        if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
            continue
        if eff in ("excluded", "exclude"):
            continue
        if is_carried_forward_effective_status(eff):
            continue
        if is_stale_effective_status(eff):
            continue
        if eff in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in eff:
            continue
        if is_unresolved_effective_status(eff) or eff in (OUTCOME_PENDING, "pending"):
            pending_candidates.append(bid)

    headline_review_ids = _collect_headline_review_exception_ids(headline)
    split_review_ids = _collect_split_review_required_ids(
        cursor, organization_id, shift_date_et, pending_candidates
    )

    def _mark_hd_stale(bag: dict[str, Any], bid: str, eff: str, snap: dict[str, Any]) -> None:
        nonlocal changed
        snap["pre_close_status"] = eff or OUTCOME_PENDING
        snap["day_close_status"] = DAY_CLOSE_STATUS_STALE
        snap["day_close_label"] = STALE_DISPLAY_LABEL
        snap["close_reason"] = BAG_CLOSE_REASON_UNRESOLVED
        snap["closed_on_date_et"] = shift_date_et.isoformat()
        snap["pre_close_was_pending"] = True
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET effective_status=%s,
                bag_snapshot_json=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE organization_id=%s
              AND shift_date_et=%s
              AND bag_id=%s
              AND LOWER(COALESCE(effective_status, '')) NOT IN
                  ('completed', 'stale', 'review_required', 'excluded', 'carried_forward')
            """,
            (
                OUTCOME_STALE,
                _json_dump(snap),
                int(organization_id),
                shift_date_et,
                bid,
            ),
        )
        if getattr(cursor, "rowcount", 1) != 0:
            changed += 1
        bag["effective_status"] = OUTCOME_STALE
        bag["bag_snapshot"] = snap
        hd_stale_ids.append(bid)

    for bag in bags:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid:
            continue
        eff = str(bag.get("effective_status") or "").strip().lower()
        snap = dict(bag.get("bag_snapshot") or {})
        if not snap and bag.get("bag_snapshot_json"):
            snap = dict(_json_load(bag.get("bag_snapshot_json")) or {})
        reasons = _norm_reason_codes(
            bag.get("review_reason_codes")
            or snap.get("review_reason_codes")
            or snap.get("pre_close_review_reason_codes")
        )
        is_hd = _bag_service_type(bag, snap) == "HD"

        if eff == OUTCOME_COMPLETED or eff.endswith("_completed"):
            completed_ids.append(bid)
            continue
        if eff in ("excluded", "exclude"):
            continue

        # Already carried / legacy stale on an open day (idempotent / reopen edge).
        if is_carried_forward_effective_status(eff):
            if not is_hd:
                carried_ids.append(bid)
            else:
                hd_stale_ids.append(bid)
            continue
        if is_stale_effective_status(eff):
            pre = str(snap.get("pre_close_status") or "").strip().lower()
            if pre in (OUTCOME_REVIEW_REQUIRED, "review_required") or "review" in pre:
                review_ids.append(bid)
            elif is_hd:
                hd_stale_ids.append(bid)
            else:
                # Legacy WF stale on closed days maps to carried-forward display.
                carried_ids.append(bid)
            continue

        # Already review — keep status and reason codes; do not carry / stale.
        if eff in (OUTCOME_REVIEW_REQUIRED, "review_required") or (
            "review" in eff and "pending" not in eff
        ):
            review_ids.append(bid)
            continue

        if not is_unresolved_effective_status(eff) and eff not in (
            OUTCOME_PENDING,
            "pending",
        ):
            if is_hd:
                _mark_hd_stale(bag, bid, eff, snap)
            else:
                snap["pre_close_status"] = eff or OUTCOME_PENDING
                snap["day_close_status"] = DAY_CLOSE_STATUS_CARRIED
                snap["day_close_label"] = CARRIED_FORWARD_DISPLAY_LABEL
                snap["close_reason"] = BAG_CLOSE_REASON_CARRIED
                snap["closed_on_date_et"] = shift_date_et.isoformat()
                snap["pre_close_was_pending"] = True
                cursor.execute(
                    """
                    UPDATE rinse_shift_monitor_day_bags
                    SET effective_status=%s,
                        bag_snapshot_json=%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE organization_id=%s
                      AND shift_date_et=%s
                      AND bag_id=%s
                      AND LOWER(COALESCE(effective_status, '')) NOT IN
                          ('completed', 'carried_forward', 'review_required', 'excluded')
                    """,
                    (
                        OUTCOME_CARRIED_FORWARD,
                        _json_dump(snap),
                        int(organization_id),
                        shift_date_et,
                        bid,
                    ),
                )
                if getattr(cursor, "rowcount", 1) != 0:
                    changed += 1
                bag["effective_status"] = OUTCOME_CARRIED_FORWARD
                bag["bag_snapshot"] = snap
                carried_ids.append(bid)
            continue

        is_review_exception = (
            bid in headline_review_ids
            or bid in split_review_ids
            or _reasons_are_review_exception(reasons)
        )

        if is_review_exception:
            snap["pre_close_status"] = eff or OUTCOME_PENDING
            snap["day_close_status"] = DAY_CLOSE_STATUS_REVIEW
            snap["day_close_label"] = "Review Required"
            snap["close_reason"] = BAG_CLOSE_REASON_REVIEW
            snap["closed_on_date_et"] = shift_date_et.isoformat()
            snap["pre_close_was_pending"] = True
            snap["pre_close_was_review_exception"] = True
            if reasons:
                snap["pre_close_review_reason_codes"] = list(reasons)
                snap["review_reason_codes"] = list(reasons)
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
                  AND LOWER(COALESCE(effective_status, '')) NOT IN
                      ('completed', 'carried_forward', 'excluded')
                """,
                (
                    OUTCOME_REVIEW_REQUIRED,
                    _json_dump(reasons),
                    _json_dump(snap),
                    int(organization_id),
                    shift_date_et,
                    bid,
                ),
            )
            if getattr(cursor, "rowcount", 1) != 0:
                changed += 1
            bag["effective_status"] = OUTCOME_REVIEW_REQUIRED
            bag["review_reason_codes"] = list(reasons)
            bag["bag_snapshot"] = snap
            review_ids.append(bid)
            continue

        if is_hd:
            _mark_hd_stale(bag, bid, eff, snap)
            continue

        # Operational unfinished WF pending → carried_forward.
        snap["pre_close_status"] = eff or OUTCOME_PENDING
        snap["day_close_status"] = DAY_CLOSE_STATUS_CARRIED
        snap["day_close_label"] = CARRIED_FORWARD_DISPLAY_LABEL
        snap["close_reason"] = BAG_CLOSE_REASON_CARRIED
        snap["closed_on_date_et"] = shift_date_et.isoformat()
        snap["pre_close_was_pending"] = True
        if reasons:
            snap["pre_close_review_reason_codes"] = list(reasons)

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
              AND LOWER(COALESCE(effective_status, '')) NOT IN
                  ('completed', 'carried_forward', 'review_required', 'excluded')
            """,
            (
                OUTCOME_CARRIED_FORWARD,
                _json_dump([]),
                _json_dump(snap),
                int(organization_id),
                shift_date_et,
                bid,
            ),
        )
        if getattr(cursor, "rowcount", 1) != 0:
            changed += 1
        bag["effective_status"] = OUTCOME_CARRIED_FORWARD
        bag["review_reason_codes"] = []
        bag["bag_snapshot"] = snap
        carried_ids.append(bid)

    completed_ids = sorted(set(completed_ids))
    review_ids = sorted(set(review_ids))
    carried_ids = sorted(set(carried_ids))
    hd_stale_ids = sorted(set(hd_stale_ids))
    return {
        "changed": changed,
        "completed_ids": completed_ids,
        "review_ids": review_ids,
        "carried_forward_ids": carried_ids,
        "hd_stale_ids": hd_stale_ids,
        # Legacy aliases (carried ≈ former unfinished-from-pending).
        "unfinished_ids": carried_ids,
        "unfinished_from_pending_ids": carried_ids,
        "unfinished_from_review_required_ids": [],
        "completed": len(completed_ids),
        "review": len(review_ids),
        "review_required": len(review_ids),
        "carried_forward": len(carried_ids),
        "unfinished": len(carried_ids),
        "unfinished_from_pending": len(carried_ids),
        "unfinished_from_review_required": 0,
    }


def apply_closed_day_headline(
    headline: Mapping[str, Any] | None,
    *,
    completed_ids: list[str],
    review_ids: list[str] | None = None,
    carried_forward_ids: list[str] | None = None,
    # Legacy kwargs (ignored when review/carried provided).
    unfinished_ids: list[str] | None = None,
    unfinished_from_pending_ids: list[str] | None = None,
    unfinished_from_review_required_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Rewrite headline for CLOSED days: Total = Completed + Review + Carried Forward."""
    out = dict(headline or {})
    completed = sorted({normalize_bag_id(x) for x in completed_ids if normalize_bag_id(x)})
    if review_ids is not None or carried_forward_ids is not None:
        review = sorted(
            {normalize_bag_id(x) for x in (review_ids or []) if normalize_bag_id(x)}
        )
        carried = sorted(
            {
                normalize_bag_id(x)
                for x in (carried_forward_ids or [])
                if normalize_bag_id(x)
            }
        )
    else:
        # Legacy unfinished split → map pending→carried, review→review.
        review = sorted(
            {
                normalize_bag_id(x)
                for x in (unfinished_from_review_required_ids or [])
                if normalize_bag_id(x)
            }
        )
        carried = sorted(
            {
                normalize_bag_id(x)
                for x in (unfinished_from_pending_ids or unfinished_ids or [])
                if normalize_bag_id(x)
            }
        )
    total = len(completed) + len(review) + len(carried)

    new_today = out.get("new_today")
    carryover = out.get("carryover")

    out["completed"] = len(completed)
    out["pending"] = 0
    out["carried_forward"] = len(carried)
    out["review_required_count"] = len(review)
    out["unfinished_at_close"] = 0
    out["unfinished_from_pending"] = len(carried)
    out["unfinished_from_review_required"] = 0
    out["active_workload"] = total
    out["total_workload"] = total
    out["completed_count"] = len(completed)
    out["pending_count"] = 0
    out["carried_forward_count"] = len(carried)
    out["unfinished_at_close_count"] = 0
    if new_today is not None:
        out["new_today"] = new_today
    if carryover is not None:
        # Closed day no longer presents opening carryover as live pending.
        out["carryover"] = carryover
    exc = dict(out.get("exceptions") or {})
    exc["review_required"] = len(review)
    exc["carried_forward"] = len(carried)
    exc["unfinished_at_close"] = 0
    exc["total"] = len(review)
    out["exceptions"] = exc
    out["close_archive"] = {
        "model": CLOSE_ARCHIVE_MODEL,
        "carried_forward_label": CARRIED_FORWARD_DISPLAY_LABEL,
        "unfinished_label": CARRIED_FORWARD_DISPLAY_LABEL,
        "carryover_used": True,
        "prior_day_seeding_used": False,
        "carried_forward": len(carried),
        "review_required": len(review),
        "unfinished_from_pending": len(carried),
        "unfinished_from_review_required": 0,
    }

    segments = dict(out.get("segments") or {})
    for seg_name, seg in list(segments.items()):
        if not isinstance(seg, dict):
            continue
        seg_out = dict(seg)
        bag_ids = dict(seg_out.get("bag_ids") or {})
        prior_pending = list(bag_ids.get("pending") or [])
        prior_review = list(bag_ids.get("review_required") or [])
        prior_completed = list(bag_ids.get("completed") or [])
        prior_carried = list(bag_ids.get("carried_forward") or [])
        if str(seg_name).lower() == "all":
            bag_ids["completed"] = completed
            bag_ids["review_required"] = review
            bag_ids["carried_forward"] = carried
            bag_ids["pending"] = []
            bag_ids["unfinished_at_close"] = []
            bag_ids["unfinished_from_pending"] = carried
            bag_ids["unfinished_from_review_required"] = []
            seg_out["completed"] = len(completed)
            seg_out["pending"] = 0
            seg_out["carried_forward"] = len(carried)
            seg_out["unfinished_at_close"] = 0
            seg_out["active_workload"] = total
            seg_out["total_workload"] = total
            seg_exc = dict(seg_out.get("exceptions") or {})
            seg_exc["review_required"] = len(review)
            seg_exc["carried_forward"] = len(carried)
            seg_exc["unfinished_at_close"] = 0
            seg_exc["total"] = len(review)
            seg_out["exceptions"] = seg_exc
        else:
            completed_set = set(completed)
            review_set = set(review)
            carried_set = set(carried)
            # Prefer intersection with day-level closed sets when identity lists exist.
            pool = {
                normalize_bag_id(x)
                for x in (
                    prior_pending
                    + prior_review
                    + prior_carried
                    + list(bag_ids.get(UNFINISHED_AT_CLOSE_KEY) or [])
                    + prior_completed
                )
                if normalize_bag_id(x)
            }
            if pool:
                seg_completed = sorted(pool & completed_set)
                seg_review = sorted(pool & review_set)
                seg_carried = sorted(pool & carried_set)
            else:
                seg_completed = sorted(
                    {
                        normalize_bag_id(x)
                        for x in prior_completed
                        if normalize_bag_id(x) and normalize_bag_id(x) in completed_set
                    }
                )
                seg_review = sorted(
                    {
                        normalize_bag_id(x)
                        for x in prior_review
                        if normalize_bag_id(x) and normalize_bag_id(x) in review_set
                    }
                )
                seg_carried = sorted(
                    {
                        normalize_bag_id(x)
                        for x in prior_pending + prior_carried
                        if normalize_bag_id(x) and normalize_bag_id(x) in carried_set
                    }
                )
            bag_ids["completed"] = seg_completed
            bag_ids["review_required"] = seg_review
            bag_ids["carried_forward"] = seg_carried
            bag_ids["pending"] = []
            bag_ids["unfinished_at_close"] = []
            seg_total = len(seg_completed) + len(seg_review) + len(seg_carried)
            seg_out["completed"] = len(seg_completed)
            seg_out["pending"] = 0
            seg_out["carried_forward"] = len(seg_carried)
            seg_out["unfinished_at_close"] = 0
            seg_out["active_workload"] = seg_total
            seg_out["total_workload"] = seg_total
            seg_exc = dict(seg_out.get("exceptions") or {})
            seg_exc["review_required"] = len(seg_review)
            seg_exc["carried_forward"] = len(seg_carried)
            seg_exc["unfinished_at_close"] = 0
            seg_exc["total"] = len(seg_review)
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
    expected_carried_forward: int | None = None,
    expected_review: int | None = None,
    allow_close_today: bool = True,
) -> dict[str, Any]:
    """Archive-close a day: review stays, pending → carried_forward, freeze CLOSED.

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
                "review": 0,
                "carried_forward": 0,
                "unfinished": 0,
                "completed_ids": [],
                "review_ids": [],
                "carried_forward_ids": [],
                "unfinished_ids": [],
            },
            "validation": {
                "ok": True,
                "model": CLOSE_ARCHIVE_MODEL,
                "checklist": {"archived": True, "already_closed": True},
            },
        }

    day_bags = load_day_bags(cursor, org, shift_date_et)
    live_counts = close_archive_counts_from_bags(day_bags)
    confirmation = build_close_confirmation_summary(day_bags)

    expected_carry = (
        expected_carried_forward
        if expected_carried_forward is not None
        else expected_unfinished
    )
    if (
        expected_completed is not None
        or expected_carry is not None
        or expected_review is not None
    ):
        mismatches: list[str] = []
        if expected_completed is not None and int(expected_completed) != int(
            live_counts["completed"]
        ):
            mismatches.append("completed")
        if expected_carry is not None and int(expected_carry) != int(
            live_counts["carried_forward"]
        ):
            mismatches.append("unfinished")
            mismatches.append("carried_forward")
        if expected_review is not None and int(expected_review) != int(
            live_counts["review"]
        ):
            mismatches.append("review")
        if mismatches:
            return {
                "ok": False,
                "error": CLOSE_CONFLICT_ERROR,
                "message": (
                    "Day counts changed since the close dialog opened. "
                    "Refresh and confirm again."
                ),
                "mismatches": sorted(set(mismatches)),
                "expected": {
                    "completed": expected_completed,
                    "unfinished": expected_unfinished,
                    "carried_forward": expected_carry,
                    "review": expected_review,
                },
                "live": live_counts,
                "confirmation": confirmation,
                "day": existing,
            }

    prev = existing.get("status")
    base_headline = (
        existing.get("headline")
        if isinstance(existing.get("headline"), dict)
        else {}
    )
    if not base_headline:
        base_headline = summary_from_day_record(
            existing, cursor=cursor, organization_id=org
        ) or {}
    archived = archive_unresolved_day_bags(
        cursor,
        org,
        shift_date_et,
        day_bags=day_bags,
        headline=base_headline,
    )
    # Closed WF headline identity uses WF bags only (HD unfinished is stale / no carry).
    wf_member = {
        normalize_bag_id(b.get("bag_id"))
        for b in day_bags
        if normalize_bag_id(b.get("bag_id"))
        and str(
            b.get("service_type")
            or ((b.get("bag_snapshot") or {}).get("service_type"))
            or "WF"
        )
        .strip()
        .upper()
        != "HD"
    }
    headline = apply_closed_day_headline(
        base_headline,
        completed_ids=[
            x for x in archived["completed_ids"] if x in wf_member
        ],
        review_ids=[x for x in (archived.get("review_ids") or []) if x in wf_member],
        carried_forward_ids=archived.get("carried_forward_ids"),
    )
    # Preserve HD closed segment from archived HD stale + HD review when present.
    hd_review = [
        x for x in (archived.get("review_ids") or []) if x not in wf_member
    ]
    hd_stale = list(archived.get("hd_stale_ids") or [])
    if hd_review or hd_stale:
        segments = dict(headline.get("segments") or {})
        hd_seg = dict(segments.get("hd") or {})
        bag_ids = dict(hd_seg.get("bag_ids") or {})
        bag_ids["review_required"] = sorted(set(hd_review))
        bag_ids["unfinished_at_close"] = sorted(set(hd_stale))
        bag_ids["pending"] = []
        bag_ids["carried_forward"] = []
        hd_seg["bag_ids"] = bag_ids
        hd_seg["pending"] = 0
        hd_seg["carried_forward"] = 0
        hd_seg["unfinished_at_close"] = len(bag_ids["unfinished_at_close"])
        hd_exc = dict(hd_seg.get("exceptions") or {})
        hd_exc["review_required"] = len(bag_ids["review_required"])
        hd_exc["unfinished_at_close"] = len(bag_ids["unfinished_at_close"])
        hd_exc["total"] = len(bag_ids["review_required"])
        hd_seg["exceptions"] = hd_exc
        hd_total = (
            int(hd_seg.get("completed") or len(bag_ids.get("completed") or []))
            + len(bag_ids["review_required"])
            + len(bag_ids["unfinished_at_close"])
        )
        hd_seg["active_workload"] = hd_total
        hd_seg["total_workload"] = hd_total
        segments["hd"] = hd_seg
        headline["segments"] = segments

    now = datetime.utcnow()
    close_reason = reason or (
        "Automatic ET day rollover archive"
        if mode == "automatic"
        else "Manual close and archive"
    )
    review_count = int(archived.get("review") or 0)
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
            review_count,
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
                "review": archived.get("review"),
                "carried_forward": archived.get("carried_forward"),
                "unfinished": archived["unfinished"],
                "total": archived["completed"]
                + int(archived.get("review") or 0)
                + int(archived.get("carried_forward") or 0),
            },
            "validation": {
                "ok": True,
                "model": CLOSE_ARCHIVE_MODEL,
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
            "model": CLOSE_ARCHIVE_MODEL,
            "carryover_used": True,
            "prior_day_seeding_used": False,
            "mode": mode,
            "timezone": "America/New_York",
        },
        totals={
            "completed": archived["completed"],
            "review": archived.get("review"),
            "carried_forward": archived.get("carried_forward"),
            "unfinished": archived["unfinished"],
            "unfinished_from_pending": archived.get("unfinished_from_pending"),
            "unfinished_from_review_required": archived.get(
                "unfinished_from_review_required"
            ),
            "pending": 0,
            "review_required": archived.get("review"),
            "active": archived["completed"]
            + int(archived.get("review") or 0)
            + int(archived.get("carried_forward") or 0),
        },
    )
    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(org, shift_date_et)
    except Exception:
        pass

    day = get_day_record(cursor, org, shift_date_et)
    final_counts = {
        "completed": archived["completed"],
        "review": archived.get("review"),
        "carried_forward": archived.get("carried_forward"),
        "unfinished": archived["unfinished"],
        "unfinished_from_pending": archived.get("unfinished_from_pending"),
        "unfinished_from_review_required": archived.get(
            "unfinished_from_review_required"
        ),
        "total": archived["completed"]
        + int(archived.get("review") or 0)
        + int(archived.get("carried_forward") or 0),
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
            "model": CLOSE_ARCHIVE_MODEL,
            "checklist": {
                "archived": True,
                "carryover_used": True,
                "prior_day_seeding_used": False,
                "timezone": "America/New_York",
            },
            "totals": {
                "completed": archived["completed"],
                "review": archived.get("review"),
                "carried_forward": archived.get("carried_forward"),
                "unfinished": archived["unfinished"],
                "pending": 0,
                "review_required": archived.get("review"),
                "active": final_counts["total"],
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
    Does not create today's membership — caller builds today from today's scrapes
    plus opening carryover from prior ``carried_forward`` IDs.
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
