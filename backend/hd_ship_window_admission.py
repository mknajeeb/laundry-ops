"""HD reset/fresh-start admission from current ship-window membership.

Normal Management discovery still uses live portal presence for NEW bags.
Reset / fresh-start re-admission must NOT treat active=1 presence alone as proof
that a bag belongs to the intended ship_to_vendor window — that board can retain
stale HD rows when ship-window scrapes are absence_capable=false and anomalous
runs do not soft-deactivate the board.

Provenance comes from rinse_cleaner_ticket_presence_runs (+ run_rows), not from
active presence alone.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from backend.management_rinse_hd import (
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    _norm_bag,
    admit_discovered_hd_bags,
    has_positive_hd_admission_evidence,
)
from backend.rinse_ship_window_tickets_urls import ship_to_vendor_window_et
from backend.ta_helpers import table_exists

_TRUSTED_RUN_STATUSES = frozenset({"success"})


def _parse_json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _as_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def hang_dry_ship_window_from_scrape_meta(
    scrape_meta: Mapping[str, Any] | None,
) -> tuple[date | None, date | None]:
    """Extract hang_dry ship_to_vendor start/end from presence-run scrape_meta."""
    meta = dict(scrape_meta or {})
    for src in meta.get("tickets_sources") or []:
        if not isinstance(src, Mapping):
            continue
        label = str(src.get("label") or "").strip().lower()
        service = str(src.get("service_types") or "").strip().lower()
        if label not in {"hang_dry", "hd"} and service not in {"hang_dry", "hd"}:
            continue
        start = _as_iso_date(src.get("ship_to_vendor_date_start"))
        end = _as_iso_date(src.get("ship_to_vendor_date_end"))
        if start and end:
            return start, end
        url = str(src.get("url") or "").strip()
        if url:
            parsed = parse_qs(urlparse(url).query)
            start = _as_iso_date((parsed.get("ship_to_vendor_date_start") or [None])[0])
            end = _as_iso_date((parsed.get("ship_to_vendor_date_end") or [None])[0])
            if start and end:
                return start, end
    return None, None


def _run_is_trustworthy(run: Mapping[str, Any]) -> bool:
    status = str(run.get("status") or "").strip().lower()
    if status not in _TRUSTED_RUN_STATUSES:
        return False
    meta = _parse_json_obj(run.get("scrape_meta_json"))
    guard = meta.get("completeness_guard") if isinstance(meta.get("completeness_guard"), dict) else {}
    if guard and guard.get("trustworthy") is False:
        return False
    if meta.get("absence_capable") is False and guard.get("allow_mark_missing") is False:
        # Ship-window discovery is still usable for positive membership when the
        # run itself succeeded and was applied (status=success).
        pass
    return True


def _load_hd_bag_ids_for_presence_run(cursor, organization_id: int, run_id: int) -> set[str]:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return set()
    cursor.execute(
        """
        SELECT bag_id, service_type, hd_count_num, hd_count_raw, raw_row_json
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE organization_id = %s AND presence_run_id = %s
        """,
        (int(organization_id), int(run_id)),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not has_positive_hd_admission_evidence(row):
            continue
        bid = _norm_bag(row.get("bag_id"))
        if bid:
            out.add(bid)
    return out


def resolve_hd_ship_window_membership(
    cursor,
    organization_id: int,
    *,
    ship_start: date,
    ship_end: date,
    require_trustworthy: bool = True,
    union_recent_captures: bool = False,
    recent_run_limit: int = 30,
) -> dict[str, Any]:
    """Resolve HD bag IDs belonging to an intended hang_dry ship_to_vendor window.

    Prefers the latest presence run whose hang_dry source window matches
    (ship_start, ship_end). When require_trustworthy=True, only status=success
    (non-anomalous) runs qualify — otherwise returns unresolved and admits nothing.

    When union_recent_captures=True (explicit repair only), bag_ids are the union of
    HD rows across recent matching-window captures so intermittent portal/CSV drops
    do not falsely exclude a still-valid ticket.
    """
    org = int(organization_id)
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return {
            "ok": False,
            "unresolved": True,
            "reason": "presence_runs_table_missing",
            "bag_ids": [],
            "run_id": None,
            "trustworthy": False,
            "ship_start": ship_start.isoformat(),
            "ship_end": ship_end.isoformat(),
        }

    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, source_batch_id, scrape_meta_json, rows_found
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s
        ORDER BY id DESC
        LIMIT 200
        """,
        (org,),
    )
    matching: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        meta = _parse_json_obj(row.get("scrape_meta_json"))
        start, end = hang_dry_ship_window_from_scrape_meta(meta)
        if start != ship_start or end != ship_end:
            continue
        entry = dict(row)
        entry["_meta"] = meta
        entry["_trustworthy"] = _run_is_trustworthy(row)
        matching.append(entry)

    if not matching:
        return {
            "ok": False,
            "unresolved": True,
            "reason": "no_presence_run_for_intended_ship_window",
            "bag_ids": [],
            "run_id": None,
            "trustworthy": False,
            "ship_start": ship_start.isoformat(),
            "ship_end": ship_end.isoformat(),
        }

    trusted = [r for r in matching if r.get("_trustworthy")]
    chosen = trusted[0] if trusted else matching[0]
    trustworthy = bool(chosen.get("_trustworthy"))

    if require_trustworthy and not trustworthy:
        return {
            "ok": False,
            "unresolved": True,
            "reason": "current_ship_window_scrape_not_trustworthy",
            "bag_ids": [],
            "run_id": int(chosen["id"]),
            "run_status": chosen.get("status"),
            "trustworthy": False,
            "ship_start": ship_start.isoformat(),
            "ship_end": ship_end.isoformat(),
            "captured_run_ids": [int(r["id"]) for r in matching[:5]],
        }

    if union_recent_captures and not require_trustworthy:
        bag_ids_set: set[str] = set()
        used_runs: list[int] = []
        for run in matching[: max(1, int(recent_run_limit))]:
            rid = int(run["id"])
            bag_ids_set |= _load_hd_bag_ids_for_presence_run(cursor, org, rid)
            used_runs.append(rid)
        bag_ids = sorted(bag_ids_set)
        return {
            "ok": True,
            "unresolved": False,
            "reason": None,
            "bag_ids": bag_ids,
            "run_id": int(chosen["id"]),
            "run_status": chosen.get("status"),
            "trustworthy": trustworthy,
            "union_recent_captures": True,
            "union_run_ids": used_runs,
            "source_batch_id": chosen.get("source_batch_id"),
            "ship_start": ship_start.isoformat(),
            "ship_end": ship_end.isoformat(),
            "bag_count": len(bag_ids),
        }

    bag_ids = sorted(_load_hd_bag_ids_for_presence_run(cursor, org, int(chosen["id"])))
    return {
        "ok": True,
        "unresolved": False,
        "reason": None,
        "bag_ids": bag_ids,
        "run_id": int(chosen["id"]),
        "run_status": chosen.get("status"),
        "trustworthy": trustworthy,
        "source_batch_id": chosen.get("source_batch_id"),
        "ship_start": ship_start.isoformat(),
        "ship_end": ship_end.isoformat(),
        "bag_count": len(bag_ids),
    }


def resolve_current_hd_ship_window_membership(
    cursor,
    organization_id: int,
    *,
    today_et: date | None = None,
    require_trustworthy: bool = True,
) -> dict[str, Any]:
    """Resolve membership for production ship window (ET yesterday → today)."""
    start, end = ship_to_vendor_window_et(today_et=today_et)
    return resolve_hd_ship_window_membership(
        cursor,
        organization_id,
        ship_start=start,
        ship_end=end,
        require_trustworthy=require_trustworthy,
    )


def active_hd_presence_bag_ids(cursor, organization_id: int) -> set[str]:
    """All active=1 HD presence bag IDs (stale-capable; not reset-admission authority)."""
    from backend.management_rinse_hd import _load_hd_discovery_bag_ids

    return set(_load_hd_discovery_bag_ids(cursor, organization_id))


def admit_hd_reset_from_ship_window(
    cursor,
    organization_id: int,
    admission_date_et: date,
    *,
    today_et: date | None = None,
    ship_start: date | None = None,
    ship_end: date | None = None,
    require_trustworthy: bool = True,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Reset/fresh-start re-admission using current ship-window membership only.

    Fails closed when the intended window has no trustworthy scrape evidence.
    Does not admit from active=1 presence alone.
    """
    if ship_start is None or ship_end is None:
        membership = resolve_current_hd_ship_window_membership(
            cursor,
            organization_id,
            today_et=today_et or admission_date_et,
            require_trustworthy=require_trustworthy,
        )
    else:
        membership = resolve_hd_ship_window_membership(
            cursor,
            organization_id,
            ship_start=ship_start,
            ship_end=ship_end,
            require_trustworthy=require_trustworthy,
        )

    stale_active = sorted(active_hd_presence_bag_ids(cursor, organization_id))
    if not membership.get("ok"):
        return {
            "ok": False,
            "admitted_new": 0,
            "already_admitted": 0,
            "bag_ids": [],
            "skipped_stale_active_ids": stale_active,
            "membership": membership,
            "error": membership.get("reason") or "ship_window_membership_unresolved",
        }

    bag_ids = list(membership.get("bag_ids") or [])
    admit_meta = admit_discovered_hd_bags(
        cursor,
        organization_id,
        admission_date_et,
        bag_ids,
        actor_user_id=actor_user_id,
    )
    eligible = set(bag_ids)
    skipped_stale = sorted(b for b in stale_active if b not in eligible)
    return {
        "ok": True,
        "admitted_new": int(admit_meta.get("admitted_new") or 0),
        "already_admitted": int(admit_meta.get("already_admitted") or 0),
        "skipped_quarantined": int(admit_meta.get("skipped_quarantined") or 0),
        "bag_ids": list(admit_meta.get("bag_ids") or bag_ids),
        "skipped_stale_active_ids": skipped_stale,
        "membership": membership,
        "error": None,
    }


def quarantine_hd_stale_reset_admissions(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    reason: str = "stale_ship_window_reset_admission",
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Reversibly quarantine HD production rows (PRE_ACTIVATION_EXCLUDED). Preserves audits/scans."""
    from backend.business_time import business_now
    from backend.hd_workflow_extensions import _quarantine_row
    from backend.management_rinse_hd import _load_production_by_bag, ensure_management_hd_columns

    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    ids = [_norm_bag(b) for b in bag_ids if _norm_bag(b)]
    if not ids:
        return {"ok": True, "quarantined": 0, "bag_ids": [], "already": [], "missing": []}

    production = _load_production_by_bag(cursor, org, ids)
    quarantined: list[str] = []
    already: list[str] = []
    missing: list[str] = []
    now = business_now()
    now_naive = now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now

    for bid in ids:
        row = production.get(bid)
        if not row:
            missing.append(bid)
            continue
        wf = str(row.get("workflow_status") or "").strip().upper()
        if wf == WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED:
            already.append(bid)
            continue
        _quarantine_row(cursor, int(row["id"]))
        quarantined.append(bid)
        if table_exists(cursor, "hd_day_bag_production_audits"):
            cursor.execute(
                """
                INSERT INTO hd_day_bag_production_audits (
                  organization_id, operations_date_et, bag_id, action,
                  version_before, version_after, after_json, reason,
                  actor_user_id, actor_display_name
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    org,
                    row.get("operations_date_et"),
                    bid,
                    "QUARANTINE",
                    int(row.get("version") or 0),
                    int(row.get("version") or 0) + 1,
                    json.dumps(
                        {
                            "workflow_status": WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
                            "prior_workflow_status": row.get("workflow_status"),
                            "quarantined_at": str(now_naive),
                        },
                        default=str,
                    ),
                    reason,
                    actor_user_id,
                    None,
                ),
            )

    return {
        "ok": True,
        "quarantined": len(quarantined),
        "bag_ids": quarantined,
        "already": already,
        "missing": missing,
        "reason": reason,
    }
