"""
Jul 23+ append-only daily workload membership from same-day presence scrapes.

Daily membership =
  first valid at_vendor scrape finished after ET midnight
  + bags first seen in later same-day scrapes
  − prior-day membership bags with no same-day scan evidence (no portal carry-in)

Never removes bags mid-day once admitted. Never uses next-day portal state.
Does not import unresolved prior-day bags as today's operational membership unless
they produce independent same-day scan evidence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from backend.rinse_folding_et import naive_et_day_start

STEP1_AUTHORITATIVE_START_ET = date(2026, 7, 23)
VEEWASH_ORG_ID = 3

INCLUSION_BASELINE = "FIRST_SCRAPE_BASELINE"
INCLUSION_ADDED_LATER = "ADDED_LATER_IN_DAY"
# Aliases matching the cutover contract names.
INCLUSION_FIRST_SCRAPE_BASELINE = INCLUSION_BASELINE
INCLUSION_ADDED_LATER_IN_DAY = INCLUSION_ADDED_LATER

# Baseline delayed if first valid scrape finishes after this local ET clock time.
_DELAYED_AFTER = time(0, 15)


def is_before_step1_cutover(
    selected_date_et: date, *, organization_id: int = VEEWASH_ORG_ID
) -> bool:
    if int(organization_id) != VEEWASH_ORG_ID:
        return False
    return selected_date_et < STEP1_AUTHORITATIVE_START_ET


def step1_unavailable_payload(selected_date_et: date) -> dict[str, Any]:
    return {
        "ok": False,
        "step1_history_unavailable": True,
        "selected_date_et": selected_date_et.isoformat(),
        "earliest_available_date_et": STEP1_AUTHORITATIVE_START_ET.isoformat(),
        "message": (
            "Step-1 daily workload tracking started July 23, 2026. "
            "Earlier operational snapshots were retired."
        ),
        "rows": [],
        "new_today": [],
        "carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": [],
        "review_required": [],
        "review_reasons_by_bag": {},
        "counts": {
            "total_workload": 0,
            "active_workload": 0,
            "new_today": 0,
            "carryover": 0,
            "completed": 0,
            "pending": 0,
            "review_required": 0,
        },
    }


def _read_run_meta(run: dict[str, Any]) -> dict[str, Any]:
    import json

    raw = run.get("scrape_meta_json")
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def is_valid_baseline_scrape(run: dict[str, Any]) -> tuple[bool, str | None]:
    """Reject empty/failed/partial presence scrapes for daily baseline membership."""
    if int(run.get("rows_found") or 0) <= 0:
        return False, "empty_rows_found"
    status = str(run.get("status") or "").strip().lower()
    if status in {"failed", "error", "disabled"}:
        return False, "failed_status"
    meta = _read_run_meta(run)
    stopped = str(meta.get("stopped_reason") or "").strip().lower()
    # Incomplete pagination / aborted table scrape — not a day baseline.
    if stopped in {"no_table_rows", "error", "exception", "timeout"}:
        return False, f"partial_stopped:{stopped}"
    if meta.get("reached_max_pages"):
        return False, "partial_max_pages"
    home = meta.get("vendor_home_summary") or {}
    try:
        home_n = int(home.get("orders_at_veewash") or 0)
    except (TypeError, ValueError):
        home_n = 0
    found = int(run.get("rows_found") or 0)
    # If vendor home reports a much larger board, treat as partial.
    if home_n >= 20 and found < max(10, int(home_n * 0.5)):
        return False, "partial_vs_vendor_home"
    return True, None


def select_first_valid_scrape_after_midnight(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """
    First valid successful at_vendor presence scrape finished in
    [D 00:00 ET, D+1 00:00). Never uses a scrape finished before midnight.

    Returns (run, baseline_delayed, skip_reason).
    """
    from backend.rinse_shift_monitor_baseline import (
        list_clean_at_vendor_presence_scrapes,
        _presence_run_finished_naive_et,
    )
    from backend.ta_helpers import table_exists

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_start(selected_date_et + timedelta(days=1))
    has_rows_table = table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows")

    candidates: list[dict[str, Any]] = []
    for row in list_clean_at_vendor_presence_scrapes(cursor, organization_id):
        finished = _presence_run_finished_naive_et(row)
        if finished is None:
            continue
        if not (day_start <= finished < day_end):
            continue
        ok, _why = is_valid_baseline_scrape(row)
        if not ok:
            continue
        if has_rows_table:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence_run_rows WHERE presence_run_id=%s",
                (int(row["id"]),),
            )
            snap_n = int((cursor.fetchone() or {}).get("c") or 0)
            if snap_n <= 0:
                continue
            row = {**row, "_run_row_count": snap_n}
        candidates.append(row)

    if not candidates:
        return None, False, "no_valid_scrape_after_midnight"

    candidates.sort(
        key=lambda r: (
            _presence_run_finished_naive_et(r) or datetime.max,
            int(r.get("id") or 0),
        )
    )
    baseline = candidates[0]
    finished = _presence_run_finished_naive_et(baseline)
    delayed = bool(finished and finished.time() > _DELAYED_AFTER)
    return baseline, delayed, None


def list_later_valid_scrapes_same_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    after_run_id: int,
    after_finished_et: datetime,
) -> list[dict[str, Any]]:
    from backend.rinse_shift_monitor_baseline import (
        list_clean_at_vendor_presence_scrapes,
        _presence_run_finished_naive_et,
    )
    from backend.ta_helpers import table_exists

    day_end = naive_et_day_start(selected_date_et + timedelta(days=1))
    has_rows_table = table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows")
    out: list[dict[str, Any]] = []
    for row in list_clean_at_vendor_presence_scrapes(cursor, organization_id):
        rid = int(row.get("id") or 0)
        if rid == int(after_run_id):
            continue
        finished = _presence_run_finished_naive_et(row)
        if finished is None:
            continue
        if finished <= after_finished_et or finished >= day_end:
            continue
        ok, _why = is_valid_baseline_scrape(row)
        if not ok:
            # Later scrapes used for appends may still be partial; allow non-baseline
            # appends only when rows_found > 0 (handled below). Partial baselines stay out.
            if int(row.get("rows_found") or 0) <= 0:
                continue
        if int(row.get("rows_found") or 0) <= 0:
            continue
        if has_rows_table:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence_run_rows WHERE presence_run_id=%s",
                (rid,),
            )
            if int((cursor.fetchone() or {}).get("c") or 0) <= 0:
                continue
        out.append(row)
    out.sort(
        key=lambda r: (
            _presence_run_finished_naive_et(r) or datetime.max,
            int(r.get("id") or 0),
        )
    )
    return out


def load_run_bag_rows(cursor, presence_run_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT bag_id, customer_name, estimated_delivery_date, rush_flag,
               service_type, portal_status, raw_row_json, source_batch_id
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE presence_run_id = %s
        """,
        (int(presence_run_id),),
    )
    out = []
    for r in cursor.fetchall() or []:
        d = dict(r)
        bid = str(d.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        d["bag_id"] = bid
        out.append(d)
    return out


def _load_prior_day_membership_ids(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> set[str]:
    """Prior ET-day membership ids from persisted day bags (preferred) or rebuild."""
    from backend.ta_helpers import table_exists

    prior = selected_date_et - timedelta(days=1)
    org = int(organization_id)
    out: set[str] = set()
    if table_exists(cursor, "rinse_shift_monitor_day_bags"):
        cursor.execute(
            """
            SELECT bag_id
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND shift_date_et = %s
            """,
            (org, prior),
        )
        for r in cursor.fetchall() or []:
            bid = str((r.get("bag_id") if isinstance(r, dict) else r[0]) or "").strip().upper()
            if bid:
                out.add(bid)
        if out:
            return out
    # Fallback: recompute prior-day scrape membership without re-applying the
    # carry-in filter recursively beyond one day (prior of cutover is empty).
    if prior < STEP1_AUTHORITATIVE_START_ET:
        return set()
    prior_mem = build_append_only_membership(
        cursor, organization_id, prior, apply_prior_day_filter=False
    )
    return set(membership_bag_ids(prior_mem))


def _bags_with_same_day_scan_evidence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str],
) -> set[str]:
    """Bags that have at least one persisted facility scan on the ET calendar day."""
    from backend.ta_helpers import table_exists

    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    org = int(organization_id)
    found: set[str] = set()
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT DISTINCT bag_id
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed < DATE_ADD(%s, INTERVAL 1 DAY)
            """,
            (org, *part, selected_date_et, selected_date_et),
        )
        for r in cursor.fetchall() or []:
            bid = str((r.get("bag_id") if isinstance(r, dict) else r[0]) or "").strip().upper()
            if bid:
                found.add(bid)
    return found


def exclude_prior_day_portal_carryins(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """
    After the cutover day, do not auto-admit prior-day membership bags that only
    remain on the portal overnight. They need independent same-day scan evidence.

    Prior-day bags that *do* have same-day scan evidence stay in membership, but
    are reclassified away from FIRST_SCRAPE_BASELINE so opening-scrape admits
    never imply prior-day carryover.
    """
    if selected_date_et <= STEP1_AUTHORITATIVE_START_ET:
        return membership, []
    if not membership:
        return membership, []
    prior_ids = _load_prior_day_membership_ids(cursor, organization_id, selected_date_et)
    if not prior_ids:
        return membership, []
    same_day = _bags_with_same_day_scan_evidence(
        cursor, organization_id, selected_date_et, list(membership.keys())
    )
    kept: dict[str, dict[str, Any]] = {}
    excluded: list[str] = []
    for bid, row in membership.items():
        if bid in prior_ids and bid not in same_day:
            excluded.append(bid)
            continue
        next_row = dict(row)
        if bid in prior_ids and bid in same_day:
            # Qualify on independent Jul N evidence — not as midnight carry-in.
            next_row["inclusion_source"] = INCLUSION_ADDED_LATER
            next_row["requalified_from_prior_day"] = True
            next_row["membership_note"] = "prior_day_requalified_by_same_day_scan"
        kept[bid] = next_row
    return kept, sorted(excluded)


def build_append_only_membership(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    apply_prior_day_filter: bool = True,
) -> dict[str, Any]:
    """
    Append-only daily membership for one ET date from same-day scrapes only.
    """
    from backend.rinse_shift_monitor_baseline import _presence_run_finished_naive_et

    baseline, delayed, skip = select_first_valid_scrape_after_midnight(
        cursor, organization_id, selected_date_et
    )
    if not baseline:
        return {
            "ok": False,
            "error": skip or "no_baseline",
            "selected_date_et": selected_date_et.isoformat(),
            "membership": {},
            "baseline_count": 0,
            "added_later_count": 0,
            "total_count": 0,
            "excluded_prior_day_carryin_count": 0,
            "excluded_prior_day_carryin_bag_ids": [],
            "fresh_start_no_prior_day_carryover": selected_date_et
            >= STEP1_AUTHORITATIVE_START_ET,
        }

    baseline_id = int(baseline["id"])
    baseline_finished = _presence_run_finished_naive_et(baseline)
    membership: dict[str, dict[str, Any]] = {}

    for row in load_run_bag_rows(cursor, baseline_id):
        bid = row["bag_id"]
        membership[bid] = {
            "bag_id": bid,
            "organization_id": int(organization_id),
            "selected_date_et": selected_date_et.isoformat(),
            "inclusion_source": INCLUSION_BASELINE,
            "source_scrape_id": baseline_id,
            "first_included_at": baseline_finished,
            "first_seen_portal_at": baseline_finished,
            "last_seen_during_day": baseline_finished,
            "rush_flag": row.get("rush_flag"),
            "service_type_portal": row.get("service_type"),
            "customer_name": row.get("customer_name"),
        }

    later = list_later_valid_scrapes_same_day(
        cursor,
        organization_id,
        selected_date_et,
        after_run_id=baseline_id,
        after_finished_et=baseline_finished or naive_et_day_start(selected_date_et),
    )
    added_later_ids: list[str] = []
    for run in later:
        rid = int(run["id"])
        finished = _presence_run_finished_naive_et(run)
        for row in load_run_bag_rows(cursor, rid):
            bid = row["bag_id"]
            if bid in membership:
                # Enrich last_seen only — never remove / never change inclusion_source
                membership[bid]["last_seen_during_day"] = finished
                continue
            membership[bid] = {
                "bag_id": bid,
                "organization_id": int(organization_id),
                "selected_date_et": selected_date_et.isoformat(),
                "inclusion_source": INCLUSION_ADDED_LATER,
                "source_scrape_id": rid,
                "first_included_at": finished,
                "first_seen_portal_at": finished,
                "last_seen_during_day": finished,
                "rush_flag": row.get("rush_flag"),
                "service_type_portal": row.get("service_type"),
                "customer_name": row.get("customer_name"),
            }
            added_later_ids.append(bid)

    excluded_carryin: list[str] = []
    if apply_prior_day_filter:
        membership, excluded_carryin = exclude_prior_day_portal_carryins(
            cursor, organization_id, selected_date_et, membership
        )
        if excluded_carryin:
            excluded_set = set(excluded_carryin)
            added_later_ids = [b for b in added_later_ids if b not in excluded_set]
        # Bags requalified from prior-day via same-day scan must count as added.
        for bid, row in membership.items():
            if row.get("requalified_from_prior_day") and bid not in added_later_ids:
                added_later_ids.append(bid)

    baseline_ids = sorted(
        b for b, m in membership.items() if m["inclusion_source"] == INCLUSION_BASELINE
    )
    # Rebuild added list from membership so requalified bags are included once.
    added_later_ids = sorted(
        {
            bid
            for bid, m in membership.items()
            if m.get("inclusion_source") == INCLUSION_ADDED_LATER
        }
    )
    added_later = [
        {
            "bag_id": bid,
            "source_scrape_id": membership[bid]["source_scrape_id"],
            "first_included_at": (
                membership[bid]["first_included_at"].isoformat(sep=" ")
                if isinstance(membership[bid].get("first_included_at"), datetime)
                else membership[bid].get("first_included_at")
            ),
            "requalified_from_prior_day": bool(
                membership[bid].get("requalified_from_prior_day")
            ),
        }
        for bid in added_later_ids
        if bid in membership
    ]
    post_cutover = selected_date_et > STEP1_AUTHORITATIVE_START_ET
    return {
        "ok": True,
        "selected_date_et": selected_date_et.isoformat(),
        "organization_id": int(organization_id),
        "baseline_presence_run_id": baseline_id,
        "baseline_finished_at_et": baseline_finished.isoformat(sep=" ")
        if isinstance(baseline_finished, datetime)
        else None,
        "baseline_delayed": delayed,
        "later_scrape_ids": [int(r["id"]) for r in later],
        "baseline_bag_ids": baseline_ids,
        "added_later_bag_ids": added_later_ids,
        "added_later": added_later,
        "membership": membership,
        "baseline_count": len(baseline_ids),
        "added_later_count": len(added_later_ids),
        "total_count": len(membership),
        "excluded_prior_day_carryin_count": len(excluded_carryin),
        "excluded_prior_day_carryin_bag_ids": excluded_carryin,
        # Post-cutover days never treat prior-day unresolved bags as carryover.
        # Opening scrape admits are same-day portal first-seens only (not carry-in).
        "fresh_start_no_prior_day_carryover": post_cutover or (
            selected_date_et == STEP1_AUTHORITATIVE_START_ET
        ),
        # Opening scrape admits after carry-in filter (not prior-day carryover).
        "opening_scrape_admit_count": len(baseline_ids),
        "added_during_day_count": len(added_later_ids),
        "prior_day_carryover_count": 0 if post_cutover else None,
    }


def membership_bag_ids(membership: dict[str, Any] | Any) -> list[str]:
    """Sorted bag ids from a build_append_only_membership result."""
    if not isinstance(membership, dict):
        return []
    raw = membership.get("membership")
    if isinstance(raw, dict):
        return sorted(str(k).strip().upper() for k in raw.keys() if str(k).strip())
    if isinstance(raw, list):
        return sorted(
            {
                str(m.get("bag_id") or "").strip().upper()
                for m in raw
                if str(m.get("bag_id") or "").strip()
            }
        )
    baseline = [str(b).strip().upper() for b in (membership.get("baseline_bag_ids") or [])]
    later = [str(b).strip().upper() for b in (membership.get("added_later_bag_ids") or [])]
    for a in membership.get("added_later") or []:
        if isinstance(a, dict) and a.get("bag_id"):
            later.append(str(a["bag_id"]).strip().upper())
    return sorted({b for b in baseline + later if b})


def list_valid_same_day_scrapes(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    """Valid same-day scrapes oldest-first (baseline + later). Convenience for tests."""
    baseline, _delayed, _skip = select_first_valid_scrape_after_midnight(
        cursor, organization_id, selected_date_et
    )
    if not baseline:
        return []
    from backend.rinse_shift_monitor_baseline import _presence_run_finished_naive_et

    finished = _presence_run_finished_naive_et(baseline)
    later = list_later_valid_scrapes_same_day(
        cursor,
        organization_id,
        selected_date_et,
        after_run_id=int(baseline["id"]),
        after_finished_et=finished or naive_et_day_start(selected_date_et),
    )
    return [baseline, *later]
