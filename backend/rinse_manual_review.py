"""Manual review resolution + send-back audit for Step-1 / Management.

Management-review state is orthogonal to operational completion.
Sending a bag back to Review Required must not wipe completion facts.
"""

from __future__ import annotations

from typing import Any, Mapping

from backend.business_time import business_now
from backend.rinse_bag_completion import normalize_bag_id

MANUAL_REVIEW_KEY = "manual_review"


def _now_et_iso() -> str:
    return business_now().replace(microsecond=0).isoformat()


def _as_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x or "").strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def get_manual_review(snap: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = (snap or {}).get(MANUAL_REVIEW_KEY)
    return dict(raw) if isinstance(raw, Mapping) else {}


def is_manually_reviewed_active(snap: Mapping[str, Any] | None) -> bool:
    mr = get_manual_review(snap)
    return bool(mr.get("active"))


def stamp_manual_review_resolved(
    snap: dict[str, Any],
    *,
    prior_reason_codes: list[str] | None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Mark bag as manually reviewed (cleared Review Required by a manager)."""
    out = dict(snap or {})
    mr = get_manual_review(out)
    history = list(mr.get("history") or [])
    reasons = _as_list(prior_reason_codes) or _as_list(mr.get("prior_reason_codes"))
    at_s = at or _now_et_iso()
    by = (actor_display_name or "").strip() or None
    event = {
        "event": "resolved",
        "at": at_s,
        "by": by,
        "actor_user_id": actor_user_id,
        "reason_codes": reasons,
    }
    history.append(event)
    out[MANUAL_REVIEW_KEY] = {
        **mr,
        "active": True,
        "resolved_at": at_s,
        "resolved_by": by,
        "resolved_by_user_id": actor_user_id,
        "prior_reason_codes": reasons,
        "sent_back_at": None,
        "sent_back_by": None,
        "sent_back_by_user_id": None,
        "history": history,
    }
    return out


def stamp_manual_review_sent_back(
    snap: dict[str, Any],
    *,
    reason_codes: list[str] | None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Deactivate manual-review membership; keep full audit history."""
    out = dict(snap or {})
    mr = get_manual_review(out)
    history = list(mr.get("history") or [])
    reasons = _as_list(reason_codes) or _as_list(mr.get("prior_reason_codes"))
    if not reasons:
        reasons = ["MANAGER_SENT_FOR_REVIEW"]
    at_s = at or _now_et_iso()
    by = (actor_display_name or "").strip() or None
    history.append(
        {
            "event": "sent_back",
            "at": at_s,
            "by": by,
            "actor_user_id": actor_user_id,
            "reason_codes": reasons,
            "prior_resolved_at": mr.get("resolved_at"),
            "prior_resolved_by": mr.get("resolved_by"),
        }
    )
    out[MANUAL_REVIEW_KEY] = {
        **mr,
        "active": False,
        "prior_reason_codes": reasons,
        "sent_back_at": at_s,
        "sent_back_by": by,
        "sent_back_by_user_id": actor_user_id,
        "history": history,
    }
    return out


def resolve_send_back_reasons(
    *,
    snap: Mapping[str, Any] | None,
    previous_reason_codes: list[str] | None,
    explicit_reason_code: str | None = None,
) -> list[str]:
    """Prefer original review reasons, then explicit, then manager-sent default."""
    mr = get_manual_review(snap)
    reasons = _as_list(previous_reason_codes)
    if not reasons:
        reasons = _as_list(mr.get("prior_reason_codes"))
    if not reasons and explicit_reason_code:
        reasons = [str(explicit_reason_code).strip().upper()]
    if not reasons:
        reasons = ["MANAGER_SENT_FOR_REVIEW"]
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for r in reasons:
        code = str(r).strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def public_manual_review_fields(snap: Mapping[str, Any] | None) -> dict[str, Any]:
    mr = get_manual_review(snap)
    if not mr:
        return {
            "manually_reviewed": False,
            "manual_review_reason_codes": [],
            "reviewed_by": None,
            "reviewed_at": None,
            "sent_back_by": None,
            "sent_back_at": None,
            "manual_review_history": [],
        }
    return {
        "manually_reviewed": bool(mr.get("active")),
        "manual_review_reason_codes": _as_list(mr.get("prior_reason_codes")),
        "reviewed_by": mr.get("resolved_by"),
        "reviewed_at": mr.get("resolved_at"),
        "sent_back_by": mr.get("sent_back_by"),
        "sent_back_at": mr.get("sent_back_at"),
        "manual_review_history": list(mr.get("history") or []),
    }


def bag_matches_search(
    bag: Mapping[str, Any],
    query: str,
) -> bool:
    """Filter helper: bag id, customer name, optional order/reference id."""
    q = str(query or "").strip().lower()
    if not q:
        return True
    bag_id = str(bag.get("bag_id") or "").lower()
    customer = str(bag.get("customer_name") or "").lower()
    order_id = str(
        bag.get("order_id")
        or bag.get("reference_id")
        or bag.get("rinse_order_id")
        or bag.get("portal_order_id")
        or ""
    ).lower()
    return q in bag_id or q in customer or (bool(order_id) and q in order_id)


def load_manually_reviewed_day_bags(
    cursor,
    organization_id: int,
    shift_date_et,
) -> list[dict[str, Any]]:
    """Day-bag rows currently marked manually reviewed (not in Review Required)."""
    from backend.rinse_veewash_shift_day import ensure_shift_monitor_day_tables, _hydrate_day_bag_row

    ensure_shift_monitor_day_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND LOWER(COALESCE(effective_status, '')) <> 'review_required'
          AND manager_edit_version > 0
        ORDER BY bag_id
        """,
        (int(organization_id), shift_date_et),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        hydrated = _hydrate_day_bag_row(row)
        snap = hydrated.get("bag_snapshot") or {}
        if is_manually_reviewed_active(snap):
            out.append(hydrated)
    return out


def filter_manually_reviewed_ids(
    rows: list[Mapping[str, Any]],
    *,
    service: str = "all",
    rush: str = "all",
) -> list[str]:
    from backend.rinse_veewash_shift_day import _matches_segment_filters, _service_norm

    svc = str(service or "all").lower()
    r = str(rush or "all").lower().replace("-", "_")
    svc_filter = None if svc in ("", "all") else _service_norm(svc)
    rush_filter = None
    if r in ("rush",):
        rush_filter = "RUSH"
    elif r in ("non_rush", "non-rush", "nonrush"):
        rush_filter = "NON_RUSH"

    ids: list[str] = []
    for row in rows:
        meta = {
            "service_type": row.get("service_type"),
            "rush_status": row.get("rush_status"),
        }
        if not _matches_segment_filters(meta, service=svc_filter, rush=rush_filter):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            ids.append(bid)
    return sorted(set(ids))
