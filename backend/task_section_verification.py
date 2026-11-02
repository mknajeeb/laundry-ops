"""Checklist section status derived from item verification records.

A section has no stored status. The labels come from the required items and
the existing item approval rows.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

SECTION_VERIFIED = "verified"
SECTION_NEEDS_CORRECTION = "needs_correction"
SECTION_PENDING = "pending_verification"
SECTION_IN_PROGRESS = "in_progress"

SECTION_LABELS = {
    SECTION_VERIFIED: "Verified",
    SECTION_NEEDS_CORRECTION: "Needs Correction",
    SECTION_PENDING: "Pending Verification",
    SECTION_IN_PROGRESS: "In Progress",
}

_VERIFIED = frozenset({"approved", "verified"})
_AWAITING = frozenset({"pending_approval", "completed"})
_REJECTED = frozenset({"rejected"})


def _required(item: Mapping[str, Any]) -> bool:
    return item.get("required") is not False


def _record_statuses(item: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for rec in item.get("records") or []:
        if isinstance(rec, Mapping):
            out.append(str(rec.get("status") or "").strip().lower())
    return out


def item_section_bucket(item: Mapping[str, Any]) -> str | None:
    """Required-item bucket. Optional items do not affect the section."""
    if not _required(item):
        return None
    status = str(item.get("status") or "").strip().lower()
    records = _record_statuses(item)
    if item.get("needs_correction") or status in _REJECTED or any(s in _REJECTED for s in records):
        return "rejected"
    if status in _VERIFIED or (records and all(s in _VERIFIED for s in records)):
        return "verified"
    awaiting = status in _AWAITING or bool(item.get("checked_off")) or any(s in _AWAITING for s in records)
    if awaiting:
        if item.get("verification_required") is False and status == "completed" and not any(
            s == "pending_approval" for s in records
        ):
            return "verified"
        return "awaiting"
    return "incomplete"


def pending_section_activity_ids(items: Sequence[Mapping[str, Any]]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for item in items:
        if not _required(item):
            continue
        candidates: list[Any] = []
        for rec in item.get("records") or []:
            if isinstance(rec, Mapping) and str(rec.get("status") or "") == "pending_approval":
                candidates.append(rec.get("activity_id"))
        if str(item.get("status") or "") == "pending_approval":
            candidates.append(item.get("child_activity_id") or item.get("id"))
        for raw in candidates:
            if raw is None:
                continue
            iid = int(raw)
            if iid not in seen:
                seen.add(iid)
                ids.append(iid)
    return ids


def section_rollups(items: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("section_label") or "").strip() or "Checklist"
        order = int(item.get("section_order") or 0)
        groups.setdefault((order, label), []).append(item)
    out: list[dict[str, Any]] = []
    for (order, label), rows in sorted(groups.items(), key=lambda pair: (pair[0][0], pair[0][1].lower())):
        buckets = [bucket for bucket in (item_section_bucket(item) for item in rows) if bucket]
        if not buckets:
            status = SECTION_VERIFIED
        elif "rejected" in buckets:
            status = SECTION_NEEDS_CORRECTION
        elif "incomplete" in buckets:
            status = SECTION_IN_PROGRESS
        elif "awaiting" in buckets:
            status = SECTION_PENDING
        else:
            status = SECTION_VERIFIED
        out.append(
            {
                "section_label": label,
                "section_order": order,
                "status": status,
                "status_label": SECTION_LABELS[status],
                "pending_activity_ids": pending_section_activity_ids(rows),
            }
        )
    return out
