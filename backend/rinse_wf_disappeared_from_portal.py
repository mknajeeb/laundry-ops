"""WF open-OI bags that disappeared from Cleaner Tickets → Review.

Qualification (all required):
  - legitimately admitted WF (open OI)
  - previously observed on presence board
  - presence inactive after authoritative successful absence
  - no valid completion evidence resolving the lifecycle
  - disappearance established while the bag was still inside the
    authoritative source window (not mere ship-window roll-off)

Does not trigger from scrape failure, partial/non-authoritative traversal,
or aging out of the rolling ship_to_vendor query window alone.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from backend.business_time import system_datetime_to_et
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_portal_scrape_meta import (
    normalize_portal_scrape_meta,
    portal_scrape_meta_allows_absence_completion,
)
from backend.rinse_scrape_completeness import (
    STATE_CONFIRMED,
    build_disappearance_confirmation,
)
from backend.ta_helpers import table_exists

REASON_DISAPPEARED_FROM_PORTAL = "DISAPPEARED_FROM_PORTAL"
REASON_LABEL = "Disappeared From Portal"


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _et_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        et = system_datetime_to_et(value)
        return et.date() if et is not None else None
    if isinstance(value, str) and value.strip():
        s = value.strip()[:10]
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    return None


def _parse_iso_date(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def ship_window_bounds_from_meta(meta: Mapping[str, Any] | None) -> tuple[date, date] | None:
    """Extract WF ship_to_vendor window from scrape meta sources/URLs, if any."""
    if not meta:
        return None
    sources = meta.get("tickets_sources") or meta.get("source_summaries") or []
    if not isinstance(sources, list):
        sources = []
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        label = str(src.get("label") or src.get("service_types") or "").strip().lower()
        svc = str(src.get("service_types") or "").strip().lower()
        is_wf = (
            label in {"wash_and_fold", "wf", "rinse_wf"}
            or svc in {"wash_and_fold", "wf"}
            or "wash_and_fold" in label
        )
        start = _parse_iso_date(src.get("ship_to_vendor_date_start"))
        end = _parse_iso_date(src.get("ship_to_vendor_date_end"))
        if start and end and is_wf:
            return start, end
        url = str(src.get("url") or "")
        if "ship_to_vendor_date_start=" in url:
            qs = parse_qs(urlparse(url).query)
            start = _parse_iso_date((qs.get("ship_to_vendor_date_start") or [None])[0])
            end = _parse_iso_date((qs.get("ship_to_vendor_date_end") or [None])[0])
            svc_q = str((qs.get("service_types") or [""])[0] or "").lower()
            if start and end and (not svc_q or svc_q in {"wash_and_fold", "wf"} or is_wf):
                return start, end
    # Fall back: any source with ship window bounds.
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        start = _parse_iso_date(src.get("ship_to_vendor_date_start"))
        end = _parse_iso_date(src.get("ship_to_vendor_date_end"))
        if start and end:
            return start, end
        url = str(src.get("url") or "")
        if "ship_to_vendor_date_start=" in url:
            qs = parse_qs(urlparse(url).query)
            start = _parse_iso_date((qs.get("ship_to_vendor_date_start") or [None])[0])
            end = _parse_iso_date((qs.get("ship_to_vendor_date_end") or [None])[0])
            if start and end:
                return start, end
    return None


def stv_still_in_source_window(
    *,
    cycle_anchor_at: Any,
    scrape_meta: Mapping[str, Any] | None,
) -> bool:
    """True when absence may be trusted for this bag's STV.

    Full-snapshot absence-capable traversals always qualify.
    Ship-window scrapes qualify only when the bag's STV date still falls inside
    that run's ship_to_vendor window (prevents roll-off false positives).
    """
    meta = normalize_portal_scrape_meta(dict(scrape_meta) if scrape_meta else None)
    if portal_scrape_meta_allows_absence_completion(meta):
        return True
    stv = _et_date(cycle_anchor_at)
    if stv is None:
        return False
    bounds = ship_window_bounds_from_meta(meta or scrape_meta or {})
    if bounds is None:
        # Non-window source that is not absence-capable → fail closed.
        return False
    start, end = bounds
    return start <= stv <= end


def _load_inactive_presence_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if not bag_ids or not table_exists(cursor, "rinse_cleaner_ticket_presence"):
        return {}
    org = int(organization_id)
    out: dict[str, dict[str, Any]] = {}
    chunk = 200
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, active, first_seen_at, last_seen_at, portal_status,
                   source_batch_id, customer_name
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND active = 0
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid:
                continue
            # Previously observed: first_seen or last_seen must exist.
            if row.get("first_seen_at") is None and row.get("last_seen_at") is None:
                continue
            out[bid] = dict(row)
    return out


def _load_run_meta_map(
    cursor,
    organization_id: int,
    run_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    if not run_ids or not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return {}
    org = int(organization_id)
    out: dict[int, dict[str, Any]] = {}
    ids = sorted({int(r) for r in run_ids if r})
    chunk = 100
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT id, status, started_at, finished_at, rows_found, scrape_meta_json
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id = %s AND id IN ({ph})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            rid = int(row.get("id") or 0)
            if not rid:
                continue
            meta = _parse_meta(row.get("scrape_meta_json"))
            out[rid] = {
                "id": rid,
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "rows_found": row.get("rows_found"),
                "scrape_meta": meta,
            }
    return out


def _last_present_run_ids(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, int]:
    """Most recent presence_run_id containing each bag (full history)."""
    if not bag_ids or not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return {}
    org = int(organization_id)
    bags = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not bags:
        return {}
    out: dict[str, int] = {}
    chunk = 100
    for i in range(0, len(bags), chunk):
        part = bags[i : i + chunk]
        bag_ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, MAX(presence_run_id) AS last_run_id
            FROM rinse_cleaner_ticket_presence_run_rows
            WHERE organization_id = %s
              AND bag_id IN ({bag_ph})
            GROUP BY bag_id
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            rid = int(row.get("last_run_id") or 0)
            if bid and rid:
                out[bid] = rid
    return out


def _first_establishing_absence_run(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    last_present_run_id: int,
    portal_status: str = "at_vendor",
    look_ahead: int = 40,
) -> dict[str, Any] | None:
    """First successful post-present run that did not contain the bag.

    This is the disappearance event used for ship-window authority — not a later
    rolling-window scrape after the bag aged out of the query.
    """
    if not last_present_run_id or not table_exists(
        cursor, "rinse_cleaner_ticket_presence_runs"
    ):
        return None
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    cursor.execute(
        """
        SELECT id, status, rows_found, started_at, finished_at, scrape_meta_json
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s
          AND dry_run = 0
          AND portal_status = %s
          AND id > %s
        ORDER BY id ASC
        LIMIT %s
        """,
        (org, portal_status, int(last_present_run_id), int(look_ahead)),
    )
    candidates = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    if not candidates:
        return None

    run_ids = [int(r["id"]) for r in candidates if r.get("id")]
    present_map: dict[int, bool] = {rid: False for rid in run_ids}
    if run_ids and table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        ph = ",".join(["%s"] * len(run_ids))
        cursor.execute(
            f"""
            SELECT DISTINCT presence_run_id
            FROM rinse_cleaner_ticket_presence_run_rows
            WHERE organization_id = %s
              AND bag_id = %s
              AND presence_run_id IN ({ph})
            """,
            (org, bid, *run_ids),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict):
                rid = int(row.get("presence_run_id") or 0)
            else:
                rid = int(row[0] or 0)
            if rid:
                present_map[rid] = True

    for row in candidates:
        rid = int(row.get("id") or 0)
        status = str(row.get("status") or "").strip().lower()
        rows_found = int(row.get("rows_found") or 0)
        if status in {"failed", "skipped", "anomalous", "running", "rejected"}:
            continue
        if rows_found <= 0:
            continue
        meta = _parse_meta(row.get("scrape_meta_json"))
        guard = meta.get("completeness_guard") if isinstance(meta, dict) else None
        # Prefer explicit guard; otherwise accept successful non-empty captures.
        if isinstance(guard, Mapping) and guard.get("allow_mark_missing") is False:
            continue
        if present_map.get(rid):
            continue
        return {
            "id": rid,
            "status": row.get("status"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "rows_found": row.get("rows_found"),
            "scrape_meta": meta,
        }
    return None


def qualify_disappeared_from_portal_bags(
    cursor,
    organization_id: int,
    open_oi_rows: Sequence[Mapping[str, Any]],
    *,
    portal_status: str = "at_vendor",
) -> dict[str, dict[str, Any]]:
    """Return ``{bag_id: context}`` for open WF OIs that qualify.

    Context includes reason code, last_seen, last present/absent run ids.
    Does not mutate storage.
    """
    by_bag: dict[str, Mapping[str, Any]] = {}
    for row in open_oi_rows or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        if row.get("completed_at") is not None:
            continue
        # Prefer earliest open OI (STV-backed cycle) when duplicates exist.
        prev = by_bag.get(bid)
        if prev is None:
            by_bag[bid] = row
            continue
        a = row.get("cycle_anchor_at")
        b = prev.get("cycle_anchor_at")
        if isinstance(a, datetime) and isinstance(b, datetime) and a < b:
            by_bag[bid] = row
        elif int(row.get("order_instance_id") or 0) < int(
            prev.get("order_instance_id") or 0
        ):
            if not (isinstance(a, datetime) and isinstance(b, datetime)):
                by_bag[bid] = row

    if not by_bag:
        return {}

    bag_ids = sorted(by_bag.keys())
    inactive = _load_inactive_presence_for_bags(cursor, organization_id, bag_ids)
    if not inactive:
        return {}

    candidates = sorted(inactive.keys())
    confirmation = build_disappearance_confirmation(
        cursor,
        organization_id,
        candidates,
        portal_status=portal_status,
    )

    confirmed: dict[str, dict[str, Any]] = {}
    for bid in candidates:
        conf = confirmation.get(bid) or {}
        if conf.get("state") != STATE_CONFIRMED:
            continue
        confirmed[bid] = conf
    if not confirmed:
        return {}

    last_present = _last_present_run_ids(cursor, organization_id, sorted(confirmed.keys()))

    out: dict[str, dict[str, Any]] = {}
    for bid, conf in confirmed.items():
        oi = by_bag[bid]
        anchor = oi.get("cycle_anchor_at")
        lp = int(last_present.get(bid) or 0)
        if not lp:
            # Never observed in immutable run_rows → cannot prove prior portal presence.
            continue
        establish = _first_establishing_absence_run(
            cursor,
            organization_id,
            bag_id=bid,
            last_present_run_id=lp,
            portal_status=portal_status,
        )
        if not establish:
            continue
        scrape_meta = establish.get("scrape_meta") or {}
        if not stv_still_in_source_window(
            cycle_anchor_at=anchor, scrape_meta=scrape_meta
        ):
            continue
        pres = inactive.get(bid) or {}
        absent_ids = [int(x) for x in (conf.get("absent_run_ids") or []) if x]
        out[bid] = {
            "bag_id": bid,
            "reason_code": REASON_DISAPPEARED_FROM_PORTAL,
            "reason_label": REASON_LABEL,
            "order_instance_id": oi.get("order_instance_id"),
            "cycle_anchor_at": anchor,
            "customer_name": oi.get("customer_name") or pres.get("customer_name"),
            "last_seen_at": pres.get("last_seen_at"),
            "last_present_run_id": lp,
            "first_absent_run_id": int(establish["id"]),
            "absent_run_ids": absent_ids,
            "trustworthy_absent_runs": conf.get("trustworthy_absent_runs"),
            "lifecycle_status": "open",
            "presence_active": 0,
        }
    return out


def disappeared_from_portal_bag_ids(
    cursor,
    organization_id: int,
    open_oi_rows: Sequence[Mapping[str, Any]],
    *,
    portal_status: str = "at_vendor",
) -> set[str]:
    return set(
        qualify_disappeared_from_portal_bags(
            cursor,
            organization_id,
            open_oi_rows,
            portal_status=portal_status,
        ).keys()
    )


def apply_manager_exclude_to_open_wf_lifecycle(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> dict[str, Any]:
    """Close open WF lifecycle after manager Exclude — keep OI/scans/history rows.

    Sets owning cycle to RESOLVED_OTHER and stamps open OI ``completed_at`` with
    ``completion_source=manager_exclude`` so Current Workload drops the bag.
    Does not delete order instances, scans, or presence history.
    """
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        list_order_instances_for_bag,
    )
    from backend.rinse_wf_service_cycle import (
        STATUS_RESOLVED_OTHER,
        get_active_cycle_for_bag,
        upsert_service_cycle,
    )

    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    out: dict[str, Any] = {"bag_id": bid, "cycle_resolved": False, "ois_closed": 0}
    if not bid:
        return out

    now_utc = datetime.utcnow()
    cycle = get_active_cycle_for_bag(cursor, org, bid)
    if cycle and isinstance(cycle.get("cycle_anchor_at"), datetime):
        anchor = cycle["cycle_anchor_at"]
        upsert_service_cycle(
            cursor,
            org,
            bag_id=bid,
            cycle_anchor_at=anchor,
            admitted_at=cycle.get("admitted_at") or anchor,
            admitted_source=str(cycle.get("admitted_source") or "PORTAL_DISCOVERY"),
            status=STATUS_RESOLVED_OTHER,
            review_reason="MANAGER_EXCLUDED",
            rush_status=cycle.get("rush_status"),
            estimated_delivery_date=cycle.get("estimated_delivery_date"),
            pre_weight_lbs=cycle.get("pre_weight_lbs"),
            post_weight_lbs=cycle.get("post_weight_lbs"),
            disappeared_at=cycle.get("disappeared_at"),
        )
        cursor.execute(
            """
            UPDATE rinse_wf_service_cycles
            SET review_resolved_at = %s,
                review_resolved_by = %s,
                review_resolution_note = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = %s AND bag_id = %s AND cycle_anchor_at = %s
            """,
            (
                now_utc,
                resolved_by,
                resolution_note,
                org,
                bid,
                anchor,
            ),
        )
        out["cycle_resolved"] = True

    open_ois = [
        r
        for r in list_order_instances_for_bag(cursor, org, bid, service_type="WF")
        if r.get("completed_at") is None
    ]
    for oi in open_ois:
        oid = oi.get("order_instance_id")
        if oid is None:
            continue
        cursor.execute(
            f"""
            UPDATE {ORDER_INSTANCES_TABLE}
            SET completed_at = COALESCE(completed_at, %s),
                completion_source = COALESCE(completion_source, %s),
                completed_by_employee_name = COALESCE(completed_by_employee_name, %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE order_instance_id = %s
              AND completed_at IS NULL
            """,
            (now_utc, "manager_exclude", resolved_by, int(oid)),
        )
        out["ois_closed"] += 1
    return out
