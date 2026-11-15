"""Mutually exclusive classification of unique completed WF bags.

The reporting day is the caller's list. Production loads that list with the
existing ET ``shift_date_et`` filter. This module does not invent bags and
does not drop a bag because its session was excluded, the employee was
unmapped, or the fold was nonqualifying.

Invariant: total unique completed bags = sum of primary category counts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

CATEGORIES = (
    "approved",
    "pending",
    "excluded",
    "outside_session",
    "nonqualifying",
    "unmapped",
    "unresolved",
)

_STATUS_CATEGORY = {
    "EXCLUDED": "excluded",
    "APPROVED": "approved",
    "UNAPPROVED": "pending",
    "NEEDS_APPROVAL": "pending",
    "PENDING": "pending",
}


def bag_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _completion_sort_value(row: Mapping[str, Any]) -> str:
    raw = row.get("completion_at") or row.get("completion_time_et") or row.get("completion_time") or ""
    if isinstance(raw, datetime):
        return raw.isoformat(sep=" ")
    return str(raw or "")


def _unique_completed(completed: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per bag id. A same-day reopen keeps the latest completion."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for row in completed or []:
        if not isinstance(row, Mapping):
            continue
        key = bag_key(row.get("bag_id"))
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    unique: list[dict[str, Any]] = []
    for key in order:
        rows = grouped[key]
        chosen = max(rows, key=_completion_sort_value)
        item = dict(chosen)
        item["bag_id"] = key
        order_ids = []
        for candidate in rows:
            oid = candidate.get("order_instance_id") or candidate.get("order_id")
            if oid is not None and oid not in order_ids:
                order_ids.append(oid)
        item["order_ids"] = order_ids
        if len(rows) > 1:
            item["duplicate_completions"] = len(rows)
        unique.append(item)
    return unique


def _index(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        key = bag_key(row.get("bag_id"))
        if not key:
            continue
        out.setdefault(key, []).append(dict(row))
    return out


def _approval_label(status: str, source: str | None, rate_override: bool) -> str:
    if rate_override:
        return "manual_rate"
    src = str(source or "").upper()
    if src in {"AUTO", "AUTO_APPROVED"}:
        return "auto"
    if status == "APPROVED":
        return "supervisor"
    return "none"


def _session_category(memberships: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any], list[str]]:
    """Pick one session placement. Excluded wins, then approved, then unresolved."""
    ranked: list[tuple[int, dict[str, Any], str]] = []
    for row in memberships:
        status = str(row.get("publication_status") or "UNAPPROVED").upper()
        role_status = str(row.get("role_status") or "").lower()
        if status == "EXCLUDED":
            category = "excluded"
            rank = 0
        elif status == "APPROVED":
            category = "approved"
            rank = 1
        elif role_status == "unresolved":
            category = "unresolved"
            rank = 2
        else:
            category = _STATUS_CATEGORY.get(status, "pending")
            rank = 3
        ranked.append((rank, dict(row), category))
    ranked.sort(key=lambda item: item[0])
    _rank, primary, category = ranked[0]
    secondary: list[str] = []
    session_ids = []
    for _rank, row, other in ranked:
        sid = str(row.get("session_id") or "")
        if sid and sid not in session_ids:
            session_ids.append(sid)
        if other != category and other not in secondary:
            secondary.append(other)
    primary["session_ids"] = session_ids
    return category, primary, secondary


def classify_completed_bags(
    completed: Sequence[Mapping[str, Any]],
    *,
    session_membership: Sequence[Mapping[str, Any]] | None = None,
    outside: Sequence[Mapping[str, Any]] | None = None,
    unmapped: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify every unique completed bag into one primary category."""
    unique = _unique_completed(completed)
    by_session = _index(session_membership or [])
    by_outside = _index(outside or [])
    by_unmapped = _index(unmapped or [])
    counts = {name: 0 for name in CATEGORIES}
    bags: list[dict[str, Any]] = []

    for bag in unique:
        key = bag["bag_id"]
        secondary: list[str] = []
        if bag.get("duplicate_completions"):
            secondary.append("duplicate_scan")
        placement = None
        if key in by_session:
            category, placement, extra = _session_category(by_session[key])
            secondary.extend(flag for flag in extra if flag not in secondary)
            if key in by_outside and "outside_session" not in secondary:
                secondary.append("outside_session")
            if key in by_unmapped and "unmapped" not in secondary:
                secondary.append("unmapped")
        elif key in by_outside:
            category = "outside_session"
            placement = by_outside[key][0]
            if key in by_unmapped:
                secondary.append("unmapped")
        elif key in by_unmapped:
            category = "unmapped"
            placement = by_unmapped[key][0]
        else:
            category = "nonqualifying"
            placement = {}

        qualifying = bag.get("qualifying_fold")
        if qualifying is False and category != "nonqualifying" and "nonqualifying" not in secondary:
            secondary.append("nonqualifying")
        if placement and placement.get("qualifying_fold") is False and "nonqualifying" not in secondary:
            secondary.append("nonqualifying")

        source_row = placement or {}
        status = str(source_row.get("publication_status") or "").upper()
        counts[category] += 1
        pounds = bag.get("pounds")
        if pounds is None:
            pounds = source_row.get("pounds")
        if pounds is None:
            pounds = bag.get("pre_lbs") or bag.get("credited_weight_lbs") or source_row.get("pre_lbs")
        bags.append(
            {
                "bag_id": key,
                "order_id": bag.get("order_id") or bag.get("order_instance_id") or source_row.get("order_instance_id"),
                "order_ids": bag.get("order_ids") or [],
                "order_instance_id": bag.get("order_instance_id") or source_row.get("order_instance_id"),
                "completion_at": _completion_sort_value(bag) or _completion_sort_value(source_row),
                "pounds": pounds,
                "employee": source_row.get("employee") or bag.get("employee") or bag.get("credited_employee"),
                "session_id": source_row.get("session_id"),
                "session_ids": source_row.get("session_ids") or (
                    [str(source_row.get("session_id"))] if source_row.get("session_id") else []
                ),
                "primary_category": category,
                "secondary_flags": secondary,
                "classification_reason": _reason(category, secondary),
                "approval_source": _approval_label(
                    status,
                    source_row.get("approval_source"),
                    bool(source_row.get("is_rate_override")),
                ),
                "publication_status": status or None,
            }
        )

    total = len(unique)
    accounted = sum(counts.values())
    return {
        "total_completed": total,
        "total_accounted": accounted,
        "unaccounted": total - accounted,
        "categories": counts,
        "invariant_holds": total == accounted and (total - accounted) == 0,
        "bags": bags,
    }


def _reason(category: str, secondary: Sequence[str]) -> str:
    reasons = {
        "approved": "Completed inside a folding session that is approved.",
        "pending": "Completed inside a folding session that is not approved yet.",
        "excluded": "Completed inside a folding session that was excluded. The bag stays in the day total.",
        "outside_session": "Completed outside a valid folding session.",
        "nonqualifying": "Completed without a qualifying folding scan in the owning order.",
        "unmapped": "Qualifying fold with no provable folder employee.",
        "unresolved": "Session time or role is unresolved.",
    }
    text = reasons.get(category, category)
    if secondary:
        text = f"{text} Also flagged: {', '.join(secondary)}."
    return text


def filter_bags(report: Mapping[str, Any], category: str | None) -> list[dict[str, Any]]:
    bags = list(report.get("bags") or [])
    if not category or category == "all":
        return bags
    return [bag for bag in bags if bag.get("primary_category") == category]
