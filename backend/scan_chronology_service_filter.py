"""Scan Chronology Wash & Fold / Hang Dry filter.

A bag's service is the order classification stored on ``rinse_bag_registry.service_type``
(written from the portal order on upload). Read-only; scans and sessions are never changed.

``service_types`` semantics:
  None             -> no filter (both checked; current behavior, unclassified bags included)
  {"WF"} / {"HD"}  -> only bags classified as that service
  frozenset()      -> nothing selected; every tab is empty
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

SERVICE_TYPES = ("WF", "HD")

_WF_ALIASES = {"WF", "WASH & FOLD", "WASH_AND_FOLD", "WASHANDFOLD", "WASH AND FOLD"}
_HD_ALIASES = {"HD", "HANG DRY", "HANG_DRY", "HANGDRY"}
_NONE_VALUES = {"NONE", ""}


def normalize_service_type(raw: Any) -> str | None:
    val = str(raw or "").strip().upper()
    if val in _WF_ALIASES:
        return "WF"
    if val in _HD_ALIASES:
        return "HD"
    return None


def parse_service_types(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    parts = [p.strip().upper() for p in str(raw).split(",")]
    selected: set[str] = set()
    for part in parts:
        if part in _NONE_VALUES:
            continue
        svc = normalize_service_type(part)
        if svc is None:
            raise ValueError("service_types must be WF, HD, WF,HD or none")
        selected.add(svc)
    if selected == set(SERVICE_TYPES):
        return None
    return frozenset(selected)


def _bag_key(raw: Any) -> str:
    return str(raw or "").strip().upper()


def load_bag_service_types(
    cursor,
    organization_id: int,
    bag_ids: Iterable[Any],
) -> dict[str, str | None]:
    ids = sorted({_bag_key(b) for b in bag_ids if _bag_key(b)})
    out: dict[str, str | None] = {bid: None for bid in ids}
    for i in range(0, len(ids), 200):
        part = ids[i : i + 200]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, service_type
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (int(organization_id), *part),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, Mapping):
                bid, svc = row.get("bag_id"), row.get("service_type")
            else:
                bid, svc = row[0], row[1]
            if _bag_key(bid) in out:
                out[_bag_key(bid)] = normalize_service_type(svc)
    return out


def allowed_bag_ids(
    cursor,
    organization_id: int,
    bag_ids: Iterable[Any],
    service_types: Collection[str] | None,
) -> set[str] | None:
    """Normalized bag ids whose service is selected; None when nothing is filtered."""
    if service_types is None:
        return None
    if not service_types:
        return set()
    svc_by_bag = load_bag_service_types(cursor, organization_id, bag_ids)
    return {bid for bid, svc in svc_by_bag.items() if svc in service_types}


def restrict_bag_ids(
    cursor,
    organization_id: int,
    bag_ids: Sequence[Any],
    service_types: Collection[str] | None,
) -> list[Any]:
    allowed = allowed_bag_ids(cursor, organization_id, bag_ids, service_types)
    if allowed is None:
        return list(bag_ids)
    return [b for b in bag_ids if _bag_key(b) in allowed]


def keep_allowed_rows(
    rows: Sequence[Mapping[str, Any]],
    allowed: Collection[str] | None,
) -> list[Any]:
    if allowed is None:
        return list(rows)
    return [r for r in rows if _bag_key(r.get("bag_id")) in allowed]
