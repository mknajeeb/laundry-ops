"""Request-scoped evidence pack for Management Rinse WF secondary.

Management-only. Not imported by scraper/ACA. Bulk-loads day-bag ids + weight map
once so weights + review phases reuse the same evidence within one request.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Iterator, Mapping

_SECONDARY_EVIDENCE: ContextVar[dict[str, Any] | None] = ContextVar(
    "mgmt_wf_secondary_evidence", default=None
)


def peek_secondary_evidence() -> dict[str, Any] | None:
    pack = _SECONDARY_EVIDENCE.get()
    return pack if isinstance(pack, dict) else None


def secondary_evidence_weight_map(
    organization_id: int, selected_date_et: date
) -> Mapping[str, Any] | None:
    pack = peek_secondary_evidence()
    if not pack:
        return None
    if int(pack.get("organization_id") or 0) != int(organization_id):
        return None
    if pack.get("selected_date_et") != selected_date_et:
        return None
    wm = pack.get("weight_map")
    return wm if isinstance(wm, dict) else None


def secondary_evidence_bag_rows(
    organization_id: int, selected_date_et: date
) -> list[Mapping[str, Any]] | None:
    pack = peek_secondary_evidence()
    if not pack:
        return None
    if int(pack.get("organization_id") or 0) != int(organization_id):
        return None
    if pack.get("selected_date_et") != selected_date_et:
        return None
    rows = pack.get("bag_rows")
    return list(rows) if isinstance(rows, list) else None


@contextmanager
def management_secondary_evidence_scope(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> Iterator[dict[str, Any]]:
    """Preload WF day-bag rows + authoritative weight map for secondary reuse."""
    from backend.ta_helpers import table_exists
    from backend.rinse_veewash_review import load_bag_weight_map

    org = int(organization_id)
    day = selected_date_et
    bag_rows: list[dict[str, Any]] = []
    weight_map: dict[str, Any] = {}
    if table_exists(cursor, "rinse_shift_monitor_day_bags"):
        cursor.execute(
            """
            SELECT bag_id, rush_status, post_weight_lbs, service_type
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND UPPER(COALESCE(service_type, '')) = 'WF'
            """,
            (org, day),
        )
        bag_rows = [dict(r) for r in (cursor.fetchall() or [])]
        bag_ids = [
            str(r.get("bag_id") or "").strip().upper()
            for r in bag_rows
            if r.get("bag_id")
        ]
        if bag_ids:
            weight_map = load_bag_weight_map(
                cursor, org, bag_ids, selected_date_et=day
            ) or {}

    pack: dict[str, Any] = {
        "organization_id": org,
        "selected_date_et": day,
        "bag_rows": bag_rows,
        "weight_map": weight_map,
        "bag_ids": [
            str(r.get("bag_id") or "").strip().upper()
            for r in bag_rows
            if r.get("bag_id")
        ],
    }
    token = _SECONDARY_EVIDENCE.set(pack)
    try:
        yield pack
    finally:
        _SECONDARY_EVIDENCE.reset(token)
