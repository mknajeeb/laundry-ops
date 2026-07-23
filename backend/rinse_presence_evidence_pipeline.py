"""
Downstream evidence processing after a successful Presence scrape board apply.

Stages (resume-safe via evidence_processing_stage):

  board_applied → membership_applied → weights_attached → projections_refreshed

Rejected / anomalous runs are no-ops. Failures set evidence_failed_stage + error
without mutating immutable Presence Run Row evidence.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_cleaner_ticket_presence import (
    EVIDENCE_STAGE_BOARD_APPLIED,
    EVIDENCE_STAGE_MEMBERSHIP_APPLIED,
    EVIDENCE_STAGE_PROJECTIONS_REFRESHED,
    EVIDENCE_STAGE_REJECTED,
    EVIDENCE_STAGE_WEIGHTS_ATTACHED,
    set_presence_run_processing_stage,
)
from backend.ta_helpers import table_exists

_STAGE_ORDER = (
    EVIDENCE_STAGE_BOARD_APPLIED,
    EVIDENCE_STAGE_MEMBERSHIP_APPLIED,
    EVIDENCE_STAGE_WEIGHTS_ATTACHED,
    EVIDENCE_STAGE_PROJECTIONS_REFRESHED,
)

_TERMINAL_NOOP = frozenset({EVIDENCE_STAGE_REJECTED, "anomalous", "failed"})


def _stage_rank(stage: str | None) -> int:
    if not stage:
        return -1
    try:
        return _STAGE_ORDER.index(str(stage))
    except ValueError:
        # Unknown / intermediate stages (e.g. chronology_applied): treat as
        # at least board_applied so membership can still run when needed.
        if str(stage) in {
            "captured",
            "validated",
            "chronology_applied",
        }:
            return _STAGE_ORDER.index(EVIDENCE_STAGE_BOARD_APPLIED)
        return -1


def _et_date_from_run(run: Mapping[str, Any]) -> date:
    from backend.rinse_scan_time import system_datetime_to_et

    for key in ("finished_at", "created_at", "started_at"):
        raw = run.get(key)
        if isinstance(raw, datetime):
            et = system_datetime_to_et(raw)
            if et is not None:
                return et.date()
            return raw.date()
        if isinstance(raw, date) and not isinstance(raw, datetime):
            return raw
    from backend.rinse_scheduled_scrape import _today_et

    return _today_et()


def _load_presence_run(
    cursor, organization_id: int, run_id: int
) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return None
    cursor.execute(
        """
        SELECT id, organization_id, portal_status, status, finished_at, created_at,
               started_at, evidence_processing_stage, evidence_failed_stage,
               evidence_processing_error
        FROM rinse_cleaner_ticket_presence_runs
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(run_id), int(organization_id)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, Mapping) else None


def _run_bag_ids(cursor, organization_id: int, run_id: int) -> list[str]:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return []
    cursor.execute(
        """
        SELECT DISTINCT bag_id
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE organization_id = %s AND presence_run_id = %s
        ORDER BY bag_id ASC
        """,
        (int(organization_id), int(run_id)),
    )
    out: list[str] = []
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, Mapping) else row[0]
        )
        if bid:
            out.append(bid)
    return out


def continue_presence_run_downstream(
    cursor,
    organization_id: int,
    run_id: int,
    *,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """
    Resume/complete post-board evidence processing for one presence run.

    - Rejected / anomalous: no-op
    - Membership: rebuild append-only for the selected ET day
    - Weights: interval-attach Presence Run Row observations per bag in the run
    - Projections: stage marker only (PRE/POST projection is read-time)

    Idempotent from ``evidence_processing_stage``. On failure, sets
    ``evidence_failed_stage`` + error and leaves immutable evidence intact.
    """
    org = int(organization_id)
    rid = int(run_id)
    stats: dict[str, Any] = {
        "organization_id": org,
        "presence_run_id": rid,
        "noop": False,
        "stages_completed": [],
    }

    run = _load_presence_run(cursor, org, rid)
    if not run:
        stats["noop"] = True
        stats["reason"] = "run_not_found"
        return stats

    status = str(run.get("status") or "").strip().lower()
    stage = str(run.get("evidence_processing_stage") or "").strip() or None
    if stage == EVIDENCE_STAGE_REJECTED or status in _TERMINAL_NOOP:
        stats["noop"] = True
        stats["reason"] = "rejected_or_anomalous"
        stats["evidence_processing_stage"] = stage
        stats["status"] = status
        return stats

    day = selected_date_et or _et_date_from_run(run)
    stats["selected_date_et"] = day.isoformat()
    rank = _stage_rank(stage)

    # --- membership_applied ---
    if rank < _STAGE_ORDER.index(EVIDENCE_STAGE_MEMBERSHIP_APPLIED):
        try:
            from backend.rinse_veewash_day_membership import build_append_only_membership
            from backend.rinse_veewash_workload import (
                build_veewash_daily_workload_from_membership,
            )

            membership = build_append_only_membership(cursor, org, day)
            stats["membership"] = {
                "ok": bool(membership.get("ok", True)),
                "baseline_count": membership.get("baseline_count"),
                "added_later_count": membership.get("added_later_count"),
                "total_count": membership.get("total_count"),
                "error": membership.get("error"),
            }
            # Light rebuild using the membership pattern (read/classify path).
            try:
                build_veewash_daily_workload_from_membership(
                    cursor, org, selected_date_et=day
                )
            except Exception as exc:
                # Membership append-only build succeeded; workload projection is best-effort.
                stats["membership_workload_warning"] = str(exc)[:500]

            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=EVIDENCE_STAGE_MEMBERSHIP_APPLIED,
                failed_stage=None,
                error=None,
                extra={"membership": stats.get("membership")},
            )
            stats["stages_completed"].append(EVIDENCE_STAGE_MEMBERSHIP_APPLIED)
            stage = EVIDENCE_STAGE_MEMBERSHIP_APPLIED
            rank = _stage_rank(stage)
        except Exception as exc:
            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=stage or EVIDENCE_STAGE_BOARD_APPLIED,
                failed_stage=EVIDENCE_STAGE_MEMBERSHIP_APPLIED,
                error=str(exc),
            )
            stats["failed_stage"] = EVIDENCE_STAGE_MEMBERSHIP_APPLIED
            stats["error"] = str(exc)
            return stats

    # --- weights_attached ---
    if rank < _STAGE_ORDER.index(EVIDENCE_STAGE_WEIGHTS_ATTACHED):
        try:
            from backend.rinse_scan_weight_enrichment import (
                attach_observations_to_weight_events,
            )

            bag_ids = _run_bag_ids(cursor, org, rid)
            per_bag: list[dict[str, Any]] = []
            updated_total = 0
            for bid in bag_ids:
                attach = attach_observations_to_weight_events(
                    cursor, org, bid, dry_run=False
                )
                updated_total += int(attach.get("updated_count") or 0)
                per_bag.append(
                    {
                        "bag_id": bid,
                        "updated_count": attach.get("updated_count"),
                        "attached": len(attach.get("attached") or []),
                        "reason": attach.get("reason"),
                    }
                )
            stats["weights"] = {
                "bags": len(bag_ids),
                "updated_total": updated_total,
                "per_bag": per_bag,
            }
            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=EVIDENCE_STAGE_WEIGHTS_ATTACHED,
                failed_stage=None,
                error=None,
                extra={"weights_updated_total": updated_total, "bags": len(bag_ids)},
            )
            stats["stages_completed"].append(EVIDENCE_STAGE_WEIGHTS_ATTACHED)
            stage = EVIDENCE_STAGE_WEIGHTS_ATTACHED
            rank = _stage_rank(stage)
        except Exception as exc:
            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=stage or EVIDENCE_STAGE_MEMBERSHIP_APPLIED,
                failed_stage=EVIDENCE_STAGE_WEIGHTS_ATTACHED,
                error=str(exc),
            )
            stats["failed_stage"] = EVIDENCE_STAGE_WEIGHTS_ATTACHED
            stats["error"] = str(exc)
            return stats

    # --- projections_refreshed (read-time PRE/POST; stage marker only) ---
    if rank < _STAGE_ORDER.index(EVIDENCE_STAGE_PROJECTIONS_REFRESHED):
        try:
            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=EVIDENCE_STAGE_PROJECTIONS_REFRESHED,
                failed_stage=None,
                error=None,
                extra={"projections": "read_time_noop"},
            )
            stats["stages_completed"].append(EVIDENCE_STAGE_PROJECTIONS_REFRESHED)
            stage = EVIDENCE_STAGE_PROJECTIONS_REFRESHED
        except Exception as exc:
            set_presence_run_processing_stage(
                cursor,
                org,
                rid,
                stage=stage or EVIDENCE_STAGE_WEIGHTS_ATTACHED,
                failed_stage=EVIDENCE_STAGE_PROJECTIONS_REFRESHED,
                error=str(exc),
            )
            stats["failed_stage"] = EVIDENCE_STAGE_PROJECTIONS_REFRESHED
            stats["error"] = str(exc)
            return stats

    stats["evidence_processing_stage"] = stage
    stats["ok"] = True
    return stats
