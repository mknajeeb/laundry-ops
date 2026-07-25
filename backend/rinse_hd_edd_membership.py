"""HD day membership gate: EDD + active presence + not prior-completed.

Authoritative HD business date is ``estimated_delivery_date`` for the selected
ET day. Scrape timing (``first_seen_at``, opening scrape, same-day add timing)
is evidence only — not the admit key.

Admit HD only when:
  estimated_delivery_date == selected_date_et
  AND active portal presence exists
  AND this HD instance has not already been COMPLETED on a prior day

Exclude future EDD, past EDD without an open reason, inactive presence, and
prior-completed instances. WF append-only scrape membership is unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_day_membership import INCLUSION_ADDED_LATER
from backend.ta_helpers import table_exists


def _as_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def load_active_hd_presence_edd_map(
    cursor,
    organization_id: int,
) -> dict[str, dict[str, Any]]:
    """Active At-Vendor HD presence rows keyed by bag_id with EDD metadata."""
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return {}
    cursor.execute(
        """
        SELECT bag_id, customer_name, estimated_delivery_date, rush_flag,
               service_type, first_seen_at, last_seen_at, active, portal_status
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id = %s
          AND UPPER(COALESCE(service_type, '')) = 'HD'
          AND active = 1
        """,
        (int(organization_id),),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("service_type") or "").strip().upper() != "HD":
            continue
        if int(row.get("active") or 0) != 1:
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        out[bid] = {
            "bag_id": bid,
            "customer_name": row.get("customer_name"),
            "estimated_delivery_date": _as_date(row.get("estimated_delivery_date")),
            "rush_flag": row.get("rush_flag"),
            "service_type_portal": "HD",
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
            "portal_status": row.get("portal_status"),
            "active": 1,
        }
    return out


def load_hd_presence_edd_lookup(
    cursor,
    organization_id: int,
    bag_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """HD presence rows (active or not) for EDD / active checks on candidates."""
    if not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return {}
    ids = sorted({normalize_bag_id(b) for b in (bag_ids or []) if normalize_bag_id(b)})
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, customer_name, estimated_delivery_date, rush_flag,
                   service_type, first_seen_at, last_seen_at, active, portal_status
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s
              AND UPPER(COALESCE(service_type, '')) = 'HD'
              AND bag_id IN ({ph})
            """,
            (int(organization_id), *ids),
        )
    else:
        cursor.execute(
            """
            SELECT bag_id, customer_name, estimated_delivery_date, rush_flag,
                   service_type, first_seen_at, last_seen_at, active, portal_status
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s
              AND UPPER(COALESCE(service_type, '')) = 'HD'
            """,
            (int(organization_id),),
        )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("service_type") or "").strip().upper() != "HD":
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        out[bid] = {
            "bag_id": bid,
            "customer_name": row.get("customer_name"),
            "estimated_delivery_date": _as_date(row.get("estimated_delivery_date")),
            "rush_flag": row.get("rush_flag"),
            "service_type_portal": "HD",
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
            "portal_status": row.get("portal_status"),
            "active": int(row.get("active") or 0),
        }
    return out


def _load_completed_hd_bag_ids(
    cursor,
    organization_id: int,
    *,
    before_date: date,
) -> set[str]:
    """HD bag ids already COMPLETED on a prior operations date.

    Blocks resurrecting finished HD instances onto a later EDD day. Same-day
    COMPLETE stays eligible for membership so Step-1 Completed can still list
    them after manager confirmation.
    """
    try:
        from backend.rinse_hd_step1_review import load_prior_completed_hd_bag_ids
    except Exception:
        return set()
    try:
        return set(load_prior_completed_hd_bag_ids(cursor, organization_id, before_date=before_date))
    except Exception:
        return set()


def _hd_row_from_presence(
    *,
    organization_id: int,
    selected_date_et: date,
    prow: Mapping[str, Any],
    existing: Mapping[str, Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    base = dict(existing or {})
    bid = normalize_bag_id(prow.get("bag_id")) or normalize_bag_id(base.get("bag_id"))
    return {
        **base,
        "bag_id": bid,
        "organization_id": int(organization_id),
        "selected_date_et": selected_date_et.isoformat(),
        "inclusion_source": base.get("inclusion_source") or INCLUSION_ADDED_LATER,
        "source_scrape_id": base.get("source_scrape_id"),
        "first_included_at": (
            base.get("first_included_at")
            or prow.get("last_seen_at")
            or prow.get("first_seen_at")
        ),
        "first_seen_portal_at": prow.get("first_seen_at") or base.get("first_seen_portal_at"),
        "last_seen_during_day": prow.get("last_seen_at") or base.get("last_seen_during_day"),
        "rush_flag": prow.get("rush_flag") if prow.get("rush_flag") is not None else base.get("rush_flag"),
        "service_type_portal": "HD",
        "customer_name": prow.get("customer_name") or base.get("customer_name"),
        "estimated_delivery_date": selected_date_et.isoformat(),
        "hd_membership_reason": reason,
        "requalified_from_prior_day": bool(
            base.get("requalified_from_prior_day") or reason.endswith("active_presence")
        ),
    }


def apply_hd_edd_day_membership_gate(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership_result: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Replace scrape-based HD admits with EDD + active + not-completed admits.

    WF members pass through unchanged. HD members are dropped unless they satisfy
    the operational admit rule; active same-day-EDD presence is re-admitted even
    when prior-day carry-in exclusion removed them from scrape membership.
    """
    out = dict(membership_result or {})
    mem = dict(out.get("membership") or {})
    active_hd = load_active_hd_presence_edd_map(cursor, organization_id)
    candidate_ids = sorted(set(mem.keys()) | set(active_hd.keys()))
    presence_lookup = load_hd_presence_edd_lookup(cursor, organization_id, candidate_ids)
    # Ensure active map wins when both exist.
    for bid, prow in active_hd.items():
        presence_lookup[bid] = prow
    completed_hd = _load_completed_hd_bag_ids(
        cursor, organization_id, before_date=selected_date_et
    )

    removed_future: list[str] = []
    removed_past: list[str] = []
    removed_inactive: list[str] = []
    removed_completed: list[str] = []
    removed_no_edd: list[str] = []
    kept: dict[str, dict[str, Any]] = {}

    # Pass WF (and non-HD) scrape members through untouched.
    for bid, row in mem.items():
        bid_n = normalize_bag_id(bid)
        if not bid_n:
            continue
        svc = str((row or {}).get("service_type_portal") or "").strip().upper()
        if not svc and bid_n in presence_lookup:
            svc = "HD"
        if svc != "HD":
            kept[bid_n] = dict(row)

    # HD admits only from active presence with matching EDD and not completed.
    for bid, prow in presence_lookup.items():
        edd = prow.get("estimated_delivery_date")
        active = int(prow.get("active") or 0) == 1
        existing = mem.get(bid)

        if edd is None:
            if existing and str((existing or {}).get("service_type_portal") or "").upper() == "HD":
                removed_no_edd.append(bid)
            continue
        if edd > selected_date_et:
            removed_future.append(bid)
            continue
        if edd < selected_date_et:
            removed_past.append(bid)
            continue
        # edd == selected_date_et
        if bid in completed_hd:
            removed_completed.append(bid)
            continue
        if not active:
            removed_inactive.append(bid)
            continue

        reason = (
            "edd_day_readmit_from_active_presence"
            if not existing
            else "edd_active_not_completed"
        )
        kept[bid] = _hd_row_from_presence(
            organization_id=organization_id,
            selected_date_et=selected_date_et,
            prow=prow,
            existing=existing if isinstance(existing, dict) else None,
            reason=reason,
        )

    added_edd = sorted(
        bid
        for bid, row in kept.items()
        if str(row.get("service_type_portal") or "").upper() == "HD"
        and bid not in mem
    )

    baseline_ids = sorted(
        b
        for b, m in kept.items()
        if str(m.get("inclusion_source") or "") == "FIRST_SCRAPE_BASELINE"
    )
    added_later_ids = sorted(
        b
        for b, m in kept.items()
        if str(m.get("inclusion_source") or "") != "FIRST_SCRAPE_BASELINE"
    )
    out["membership"] = kept
    out["baseline_bag_ids"] = baseline_ids
    out["added_later_bag_ids"] = added_later_ids
    out["baseline_count"] = len(baseline_ids)
    out["added_later_count"] = len(added_later_ids)
    out["total_count"] = len(kept)
    out["hd_edd_gate"] = {
        "selected_date_et": selected_date_et.isoformat(),
        "authoritative_field": "estimated_delivery_date",
        "admit_requires_active_presence": True,
        "admit_excludes_completed": True,
        "removed_future_edd_bag_ids": sorted(set(removed_future)),
        "removed_past_edd_bag_ids": sorted(set(removed_past)),
        "removed_inactive_bag_ids": sorted(set(removed_inactive)),
        "removed_completed_bag_ids": sorted(set(removed_completed)),
        "removed_missing_edd_bag_ids": sorted(set(removed_no_edd)),
        "added_edd_day_bag_ids": added_edd,
        "removed_future_edd_count": len(set(removed_future)),
        "removed_inactive_count": len(set(removed_inactive)),
        "removed_completed_count": len(set(removed_completed)),
        "added_edd_day_count": len(added_edd),
    }
    added_later = []
    for bid in added_later_ids:
        row = kept[bid]
        ts = row.get("first_included_at")
        added_later.append(
            {
                "bag_id": bid,
                "source_scrape_id": row.get("source_scrape_id"),
                "first_included_at": (
                    ts.isoformat(sep=" ") if isinstance(ts, datetime) else ts
                ),
                "requalified_from_prior_day": bool(row.get("requalified_from_prior_day")),
            }
        )
    out["added_later"] = added_later
    return out
