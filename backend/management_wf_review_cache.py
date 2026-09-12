"""Bounded in-process caches for Management WF Review read paths.

Derived caches only — canonical builders remain authoritative.
Org-scoped, date-scoped (membership), short TTL, cleared with Management
today cache invalidation. Single-flight locks prevent duplicate concurrent
builds for the same key (primary ∥ secondary race).
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import date
from typing import Any, Mapping, Sequence

from backend.business_time import business_today

# Align with Management WF secondary live TTL.
_MEMBERSHIP_TTL_LIVE_SEC = 45.0
_MEMBERSHIP_TTL_CLOSED_SEC = 600.0
_DFP_TTL_LIVE_SEC = 45.0

# (org, date_iso) -> (monotonic_ts, membership_dict)
_MEMBERSHIP_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_MEMBERSHIP_LOCKS: dict[tuple[int, str], threading.Lock] = {}
_MEMBERSHIP_LOCKS_GUARD = threading.Lock()

# org -> (monotonic_ts, {bag_id: ctx})
_DFP_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
_DFP_LOCKS: dict[int, threading.Lock] = {}
_DFP_LOCKS_GUARD = threading.Lock()

# Test / instrumentation counters (process-local).
_STATS = {
    "dfp_compute": 0,
    "dfp_cache_hit": 0,
    "membership_compute": 0,
    "membership_cache_hit": 0,
}


def review_cache_stats() -> dict[str, int]:
    return dict(_STATS)


def reset_review_cache_stats() -> None:
    for k in _STATS:
        _STATS[k] = 0


def _membership_ttl(day: date) -> float:
    return (
        _MEMBERSHIP_TTL_LIVE_SEC
        if day == business_today()
        else _MEMBERSHIP_TTL_CLOSED_SEC
    )


def _dfp_ttl() -> float:
    return _DFP_TTL_LIVE_SEC


def _membership_lock(key: tuple[int, str]) -> threading.Lock:
    with _MEMBERSHIP_LOCKS_GUARD:
        lock = _MEMBERSHIP_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _MEMBERSHIP_LOCKS[key] = lock
        return lock


def _dfp_lock(org: int) -> threading.Lock:
    with _DFP_LOCKS_GUARD:
        lock = _DFP_LOCKS.get(org)
        if lock is None:
            lock = threading.Lock()
            _DFP_LOCKS[org] = lock
        return lock


def clear_wf_review_derived_cache(
    organization_id: int | None = None,
    date_et: date | str | None = None,
    *,
    clear_dfp: bool = True,
) -> None:
    """Invalidate Review membership caches (and optionally DFP).

    Date-scoped clears always drop membership for that org/date.
    DFP is date-free (open OIs); clear it when ``clear_dfp`` is True (default
    for mutation invalidation). Pass ``clear_dfp=False`` when only refreshing
    day-scoped membership.
    """
    org = int(organization_id) if organization_id is not None else None
    day_key = (
        date_et.isoformat()
        if isinstance(date_et, date)
        else (str(date_et) if date_et else None)
    )
    if org is None and day_key is None:
        _MEMBERSHIP_CACHE.clear()
        if clear_dfp:
            _DFP_CACHE.clear()
        return
    for key in list(_MEMBERSHIP_CACHE):
        if org is not None and key[0] != org:
            continue
        if day_key is not None and key[1] != day_key:
            continue
        _MEMBERSHIP_CACHE.pop(key, None)
    if clear_dfp:
        if org is None:
            _DFP_CACHE.clear()
        else:
            _DFP_CACHE.pop(org, None)


def get_qualified_disappeared_from_portal(
    cursor,
    organization_id: int,
    open_oi_rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    portal_status: str = "at_vendor",
    bypass_cache: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return DFP qualification map; compute at most once per org under lock."""
    from backend.rinse_order_instances import list_open_wf_order_instances
    from backend.rinse_wf_disappeared_from_portal import (
        qualify_disappeared_from_portal_bags,
    )

    org = int(organization_id)
    now = time.monotonic()
    if not bypass_cache:
        cached = _DFP_CACHE.get(org)
        if cached and (now - cached[0]) < _dfp_ttl():
            _STATS["dfp_cache_hit"] += 1
            return copy.deepcopy(cached[1])

    lock = _dfp_lock(org)
    with lock:
        now = time.monotonic()
        if not bypass_cache:
            cached = _DFP_CACHE.get(org)
            if cached and (now - cached[0]) < _dfp_ttl():
                _STATS["dfp_cache_hit"] += 1
                return copy.deepcopy(cached[1])

        rows = open_oi_rows
        if rows is None:
            rows = list_open_wf_order_instances(cursor, org, service_type="WF")
        result = qualify_disappeared_from_portal_bags(
            cursor, org, rows, portal_status=portal_status
        )
        _STATS["dfp_compute"] += 1
        _DFP_CACHE[org] = (time.monotonic(), dict(result))
        return copy.deepcopy(result)


def get_canonical_wf_review_membership_cached(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    headline: Mapping[str, Any] | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Cached wrapper around ``compute_canonical_wf_review_membership``."""
    from backend.management_rinse_wf_review import compute_canonical_wf_review_membership

    org = int(organization_id)
    day = selected_date_et
    key = (org, day.isoformat())
    now = time.monotonic()
    ttl = _membership_ttl(day)

    if not bypass_cache:
        cached = _MEMBERSHIP_CACHE.get(key)
        if cached and (now - cached[0]) < ttl:
            _STATS["membership_cache_hit"] += 1
            return copy.deepcopy(cached[1])

    lock = _membership_lock(key)
    with lock:
        now = time.monotonic()
        if not bypass_cache:
            cached = _MEMBERSHIP_CACHE.get(key)
            if cached and (now - cached[0]) < ttl:
                _STATS["membership_cache_hit"] += 1
                return copy.deepcopy(cached[1])

        result = compute_canonical_wf_review_membership(
            cursor,
            org,
            day,
            headline=headline,
        )
        try:
            from backend.management_rinse_wf_review import (
                merge_cw_manual_overrides_into_review_membership,
            )

            result = merge_cw_manual_overrides_into_review_membership(
                cursor, org, result
            )
        except Exception:
            # Soft overlay must never break membership reads.
            pass
        _STATS["membership_compute"] += 1
        _MEMBERSHIP_CACHE[key] = (time.monotonic(), copy.deepcopy(result))
        return copy.deepcopy(result)
