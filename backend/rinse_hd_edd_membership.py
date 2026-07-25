"""HD day membership gate: Estimated Delivery Date on the selected ET day.

WF append-only scrape membership is shared. HD presentation must further require
``estimated_delivery_date == selected_date_et`` so future-dated portal rows
(e.g. Nicole Callender EDD Jul 28) never enter today's HD drawer, and same-day
EDD orders excluded only as prior-day portal carry-ins (e.g. Victoria Panettiere)
are re-admitted.
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
        }
    return out


def apply_hd_edd_day_membership_gate(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership_result: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Mutate append-only membership so HD bags require EDD == selected_date_et.

    - Drop HD members whose EDD is set and not equal to the selected ET day.
    - Re-admit active HD presence with EDD == selected day (even if prior-day
      carry-in exclusion removed them).
    - Leave WF members unchanged.
    """
    out = dict(membership_result or {})
    mem = dict(out.get("membership") or {})
    presence_hd = load_active_hd_presence_edd_map(cursor, organization_id)

    removed_future: list[str] = []
    removed_mismatched: list[str] = []
    kept: dict[str, dict[str, Any]] = {}

    for bid, row in mem.items():
        bid_n = normalize_bag_id(bid)
        if not bid_n:
            continue
        svc = str((row or {}).get("service_type_portal") or "").strip().upper()
        # Prefer live presence service when membership row lacks it.
        if not svc and bid_n in presence_hd:
            svc = "HD"
        if svc != "HD":
            kept[bid_n] = dict(row)
            continue
        edd = None
        if bid_n in presence_hd:
            edd = presence_hd[bid_n].get("estimated_delivery_date")
        if edd is None:
            # No EDD on presence — keep scrape membership (cannot prove mismatch).
            kept[bid_n] = dict(row)
            continue
        if edd == selected_date_et:
            next_row = dict(row)
            next_row["estimated_delivery_date"] = edd.isoformat()
            next_row["hd_membership_reason"] = "edd_matches_selected_date"
            kept[bid_n] = next_row
        else:
            if edd > selected_date_et:
                removed_future.append(bid_n)
            else:
                removed_mismatched.append(bid_n)

    added_edd: list[str] = []
    for bid, prow in presence_hd.items():
        if prow.get("estimated_delivery_date") != selected_date_et:
            continue
        if bid in kept:
            continue
        kept[bid] = {
            "bag_id": bid,
            "organization_id": int(organization_id),
            "selected_date_et": selected_date_et.isoformat(),
            "inclusion_source": INCLUSION_ADDED_LATER,
            "source_scrape_id": None,
            "first_included_at": prow.get("last_seen_at") or prow.get("first_seen_at"),
            "first_seen_portal_at": prow.get("first_seen_at"),
            "last_seen_during_day": prow.get("last_seen_at"),
            "rush_flag": prow.get("rush_flag"),
            "service_type_portal": "HD",
            "customer_name": prow.get("customer_name"),
            "estimated_delivery_date": selected_date_et.isoformat(),
            "hd_membership_reason": "edd_day_readmit_from_active_presence",
            "requalified_from_prior_day": True,
        }
        added_edd.append(bid)

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
        "removed_future_edd_bag_ids": sorted(removed_future),
        "removed_mismatched_edd_bag_ids": sorted(removed_mismatched),
        "added_edd_day_bag_ids": sorted(added_edd),
        "removed_future_edd_count": len(removed_future),
        "added_edd_day_count": len(added_edd),
    }
    # Refresh added_later detail list used by workload reconstruction.
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
