"""Read-model split: Pending vs Presence Unconfirmed.

Pending
  Open WF work that the latest portal snapshot still shows.

Presence Unconfirmed
  Open order that is not in Review (including authoritative Missing) and is
  not in the latest portal snapshot. Stored deactivation from a
  non-authoritative scrape is the usual cause, but the read model does not
  require a DB write to classify: absence of current portal evidence is
  enough once Review has already claimed authoritative Missing.

This module does not write presence, order instances, or day bags.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from backend.rinse_bag_completion import normalize_bag_id

OUTCOME_PRESENCE_UNCONFIRMED = "presence_unconfirmed"


def split_pending_and_unconfirmed(
    open_ids: Iterable[str],
    *,
    review_ids: Iterable[str] = (),
    latest_seen: Iterable[str] = (),
    prior_board_ids: Iterable[str] = (),
    inactive_ids: Iterable[str] = (),
) -> tuple[set[str], set[str]]:
    """Partition open bags that are not already Review.

    ``prior_board_ids`` / ``inactive_ids`` remain in the signature for callers
    that still pass scar evidence; classification itself is:

    - in latest snapshot → Pending
    - otherwise → Presence Unconfirmed

    Review (including authoritative Missing) is excluded from both sets.
    """
    _ = (prior_board_ids, inactive_ids)
    review = {normalize_bag_id(b) for b in review_ids if normalize_bag_id(b)}
    seen = {normalize_bag_id(b) for b in latest_seen if normalize_bag_id(b)}
    pending: set[str] = set()
    unconfirmed: set[str] = set()
    for raw in open_ids:
        bid = normalize_bag_id(raw)
        if not bid or bid in review:
            continue
        if bid in seen:
            pending.add(bid)
        else:
            unconfirmed.add(bid)
    return pending, unconfirmed


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _run_bag_ids(cursor, presence_run_id: int) -> set[str]:
    cursor.execute(
        """
        SELECT bag_id
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE presence_run_id=%s
        """,
        (int(presence_run_id),),
    )
    rows = cursor.fetchall()
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out.add(bid)
    return out


def load_latest_portal_boards(
    cursor,
    organization_id: int,
    *,
    portal_status: str = "at_vendor",
) -> tuple[set[str], set[str], bool]:
    """Latest and preceding successful at-vendor snapshots.

    Returns (latest_seen, prior_board, latest_may_establish_absence).

    ``absence_capable=false`` never makes the latest board an absence
    authority. The overlap / generation guard is defense-in-depth only after
    that primary check — it never promotes a non-absence-capable scrape.
    """
    from backend.rinse_portal_scrape_meta import (
        portal_scrape_may_establish_absence,
        scrape_explicitly_prohibits_absence,
    )
    from backend.rinse_scrape_completeness import generation_identity_allows_absence

    try:
        cursor.execute(
            """
            SELECT id, scrape_meta_json
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id=%s AND portal_status=%s AND dry_run=0
              AND status='success'
            ORDER BY id DESC
            LIMIT 2
            """,
            (int(organization_id), portal_status),
        )
        rows = cursor.fetchall()
    except Exception:
        return set(), set(), False
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return set(), set(), False
    latest = rows[0]
    prior = rows[1] if len(rows) > 1 and isinstance(rows[1], dict) else None
    latest_id = int(latest.get("id") or 0)
    latest_seen = _run_bag_ids(cursor, latest_id) if latest_id else set()
    prior_seen: set[str] = set()
    if prior and int(prior.get("id") or 0):
        prior_seen = _run_bag_ids(cursor, int(prior["id"]))
    meta = _parse_meta(latest.get("scrape_meta_json"))
    # Primary authority: absence_capable / ship-window. Overlap never overrides.
    if scrape_explicitly_prohibits_absence(meta):
        may = False
    else:
        may = portal_scrape_may_establish_absence(meta)
        if may and prior_seen:
            allowed, _detail = generation_identity_allows_absence(
                prior_ids=prior_seen, seen_ids=latest_seen
            )
            if not allowed:
                may = False
    return latest_seen, prior_seen, may


def resolve_presence_unconfirmed_ids(
    cursor,
    organization_id: int,
    open_ids: Iterable[str],
    review_ids: Iterable[str],
    *,
    portal_status: str = "at_vendor",
) -> set[str]:
    """Open bags that are Presence Unconfirmed.

    Uses one latest-run header query and one run-rows query (batched set).
    On read failure returns empty so callers keep fail-closed behavior for
    Missing; Pending must not absorb unresolved bags when the snapshot loads.
    """
    try:
        latest_seen, prior_seen, _may_establish = load_latest_portal_boards(
            cursor, organization_id, portal_status=portal_status
        )
        # If we could not load any latest board, do not invent Pending for
        # bags that also carry a non-authoritative inactive scar.
        if not latest_seen and not prior_seen:
            from backend.rinse_wf_disappeared_from_portal import (
                _load_inactive_presence_for_bags,
            )

            inactive_map = _load_inactive_presence_for_bags(
                cursor,
                int(organization_id),
                [normalize_bag_id(b) for b in open_ids if normalize_bag_id(b)],
            )
            review = {normalize_bag_id(b) for b in review_ids if normalize_bag_id(b)}
            return {
                normalize_bag_id(b)
                for b in open_ids
                if normalize_bag_id(b)
                and normalize_bag_id(b) not in review
                and normalize_bag_id(b) in inactive_map
            }
        _pending, unconfirmed = split_pending_and_unconfirmed(
            open_ids,
            review_ids=review_ids,
            latest_seen=latest_seen,
        )
        return unconfirmed
    except Exception:
        return set()
