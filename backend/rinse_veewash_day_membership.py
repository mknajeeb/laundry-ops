"""
Jul 23+ append-only daily workload membership from same-day presence scrapes.

Daily membership (CP2B) =
  Opening Carryover
    — active in first qualifying portal scrape of the selected ET day
    — present in prior-day membership / prior-day active evidence
    — not canonically completed before selected-day opening
  Opening New
    — active in first qualifying portal scrape
    — not prior-day carryover evidence
    — not already completed before opening
  Added During Day
    — first becomes active after the opening scrape
    — append-only; disappearing later does not remove membership

Append-only Retained is a status within membership (admitted, no longer on portal),
not an additive bucket.

Never removes bags mid-day once admitted. Never uses next-day portal state.
Opening Carryover does **not** require a same-day Dirty/Zipvan scan.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Mapping

from backend.rinse_folding_et import naive_et_day_start

STEP1_AUTHORITATIVE_START_ET = date(2026, 7, 23)
VEEWASH_ORG_ID = 3

INCLUSION_OPENING_CARRYOVER = "OPENING_CARRYOVER"
INCLUSION_OPENING_NEW = "OPENING_NEW"
INCLUSION_ADDED_LATER = "ADDED_LATER_IN_DAY"
# Legacy aliases — Opening New replaces first-scrape baseline terminology.
INCLUSION_BASELINE = INCLUSION_OPENING_NEW
INCLUSION_FIRST_SCRAPE_BASELINE = INCLUSION_OPENING_NEW
INCLUSION_ADDED_LATER_IN_DAY = INCLUSION_ADDED_LATER

_OPENING_INCLUSION_SOURCES = frozenset(
    {
        INCLUSION_OPENING_CARRYOVER,
        INCLUSION_OPENING_NEW,
        # Pre-CP2B persisted / in-flight rows.
        "FIRST_SCRAPE_BASELINE",
    }
)

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
    """Prior-day Opening Carryover ids = WF bags with effective_status carried_forward.

    Only operational unfinished **WF** bags closed as ``carried_forward`` feed
    next-day Opening Carryover. HD / review / completed / excluded / legacy stale
    rows do not. New Today admits still come from today's scrape separately.
    """
    from backend.ta_helpers import table_exists

    prior = selected_date_et - timedelta(days=1)
    org = int(organization_id)
    out: set[str] = set()
    if prior < STEP1_AUTHORITATIVE_START_ET:
        return set()
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return set()
    cursor.execute(
        """
        SELECT bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND LOWER(TRIM(COALESCE(effective_status, ''))) = 'carried_forward'
          AND UPPER(TRIM(COALESCE(service_type, 'WF'))) = 'WF'
        """,
        (org, prior),
    )
    for r in cursor.fetchall() or []:
        bid = str((r.get("bag_id") if isinstance(r, dict) else r[0]) or "").strip().upper()
        if bid:
            out.add(bid)
    return out


def _bags_with_same_day_scan_evidence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str],
) -> set[str]:
    """Bags with any persisted scan on the ET calendar day (legacy helper)."""
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


def _facility_entry_rack_keys(cursor, organization_id: int) -> list[str]:
    from backend.rinse_processing_settings import (
        DEFAULT_FACILITY_ENTRY_RACKS,
        get_processing_settings,
    )
    from backend.rinse_veewash_workload import _entry_rack_keys

    try:
        racks = (
            get_processing_settings(cursor, int(organization_id)).get("facility_entry_racks")
            or list(DEFAULT_FACILITY_ENTRY_RACKS)
        )
    except Exception:
        racks = list(DEFAULT_FACILITY_ENTRY_RACKS)
    return sorted(_entry_rack_keys(racks))


def _bags_with_same_day_entry_evidence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str],
) -> set[str]:
    """Bags with a same-day VeeWash Dirty / facility-entry rack scan (ET day).

    Weight-entry, Clean, bulk, move-bag, etc. do **not** requalify prior-day bags.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    rack_keys = _facility_entry_rack_keys(cursor, organization_id)
    if not ids or not rack_keys or not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    org = int(organization_id)
    found: set[str] = set()
    rack_ph = ",".join(["%s"] * len(rack_keys))
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
              AND rack IS NOT NULL AND TRIM(rack) != ''
              AND LOWER(TRIM(rack)) IN ({rack_ph})
            """,
            (org, *part, selected_date_et, selected_date_et, *rack_keys),
        )
        for r in cursor.fetchall() or []:
            bid = str((r.get("bag_id") if isinstance(r, dict) else r[0]) or "").strip().upper()
            if bid:
                found.add(bid)
    return found


def _bags_canonically_completed_before_opening(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str],
    *,
    service_type_by_bag: Mapping[str, str] | None = None,
) -> set[str]:
    """Bags canonically completed before selected-day ET opening (midnight).

    Uses the Shift Monitor completion contract via ``load_canonical_completions_v2``:
      WF → resolve_current_cycle
      HD → _evaluate_bag_as_of
    Manager ``correct_completion`` remains authoritative **within the cycle
    active as of prior-day end** (same durable window as completion rebuild).
    A prior-cycle manager correction must not exclude a newer cycle.
    Clean rack / processed-by-vendor alone do not complete.
    """
    from backend.rinse_cycle_boundary import (
        current_cycle_event_window,
        manager_completion_belongs_to_cycle,
        resolve_current_cycle,
    )
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_processing_settings import (
        DEFAULT_FACILITY_ENTRY_RACKS,
        get_processing_settings,
    )
    from backend.rinse_veewash_workload import load_canonical_completions_v2
    from backend.ta_helpers import table_exists

    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    if not ids or selected_date_et < STEP1_AUTHORITATIVE_START_ET:
        return set()
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()

    prior = selected_date_et - timedelta(days=1)
    day_start = naive_et_day_start(selected_date_et)
    svc_map = {
        str(k).strip().upper(): str(v or "WF").strip().upper()
        for k, v in (service_type_by_bag or {}).items()
        if str(k).strip()
    }
    try:
        racks = get_processing_settings(cursor, int(organization_id)).get(
            "facility_entry_racks"
        ) or list(DEFAULT_FACILITY_ENTRY_RACKS)
    except Exception:
        racks = list(DEFAULT_FACILITY_ENTRY_RACKS)

    completed: set[str] = set()
    # Same-day completions on the prior ET day (includes manager overrides).
    if prior >= STEP1_AUTHORITATIVE_START_ET:
        comps_prior = load_canonical_completions_v2(
            cursor,
            int(organization_id),
            ids,
            selected_date_et=prior,
            service_type_by_bag=svc_map,
            entry_racks=racks,
        )
        for bid, comp in (comps_prior or {}).items():
            ca = comp.get("completion_at") if isinstance(comp, Mapping) else None
            cd = comp.get("completion_date") if isinstance(comp, Mapping) else None
            if cd is not None and cd < selected_date_et:
                completed.add(str(bid).strip().upper())
            elif isinstance(ca, datetime) and ca < day_start:
                completed.add(str(bid).strip().upper())

    # As-of prior-day-end resolve catches completions earlier than the prior
    # calendar day that still leave the bag on the opening portal.
    remaining = [b for b in ids if b not in completed]
    if not remaining:
        return completed

    org = int(organization_id)
    by_bag: dict[str, list[dict[str, Any]]] = {b: [] for b in remaining}
    chunk = 200
    for i in range(0, len(remaining), chunk):
        part = remaining[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose, rack, scanned_at_parsed, user_name, weight_lbs, id, raw_json
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({ph})
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed < %s
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (org, *part, day_start),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid in by_bag:
                by_bag[bid].append(row)

    prior_end = naive_et_day_end_inclusive(prior)
    for bid, timeline in by_bag.items():
        if not timeline:
            continue
        svc = svc_map.get(bid) or "WF"
        if svc == "HD":
            from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, _evaluate_bag_as_of

            status, _signal, comp_ts, _anchor, _fields = _evaluate_bag_as_of(
                timeline,
                service_type="HD",
                as_of_end=prior_end,
            )
            if status == AV_STATUS_COMPLETED and isinstance(comp_ts, datetime):
                if comp_ts < day_start:
                    completed.add(bid)
            continue

        boundary = resolve_current_cycle(
            timeline,
            selected_date_et=prior if prior >= STEP1_AUTHORITATIVE_START_ET else selected_date_et,
            entry_racks=racks,
            as_of_end=prior_end,
        )
        if (
            getattr(boundary, "effective_status", None) == "completed"
            and isinstance(getattr(boundary, "completion_at", None), datetime)
            and boundary.completion_at < day_start
        ):
            completed.add(bid)

    # Manager correct_completion before opening wins even without scan evidence,
    # but only when the correction belongs to the cycle active as of prior-day
    # end (same window as load_canonical_completions_v2). Prior-cycle corrections
    # must not exclude a newer cycle that started before opening.
    if table_exists(cursor, "rinse_step1_corrections"):
        still = [b for b in ids if b not in completed]
        cycle_day = prior if prior >= STEP1_AUTHORITATIVE_START_ET else selected_date_et
        for i in range(0, len(still), chunk):
            part = still[i : i + chunk]
            if not part:
                continue
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT bag_id, new_values
                FROM rinse_step1_corrections
                WHERE organization_id = %s
                  AND bag_id IN ({ph})
                  AND action = 'correct_completion'
                ORDER BY created_at ASC, id ASC
                """,
                (org, *part),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                raw = row.get("new_values")
                if isinstance(raw, str):
                    import json

                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}
                if not isinstance(raw, dict):
                    continue
                ts_raw = raw.get("completion_at")
                if ts_raw in (None, ""):
                    continue
                if isinstance(ts_raw, datetime):
                    ts = ts_raw
                else:
                    try:
                        ts = datetime.fromisoformat(
                            str(ts_raw).replace("Z", "").replace(" ", "T", 1)
                        )
                    except ValueError:
                        continue
                if ts >= day_start:
                    continue
                timeline = by_bag.get(bid) or []
                if not timeline:
                    # Manager-only completion with no pre-opening scan timeline:
                    # no newer cycle is visible, so the correction still excludes.
                    completed.add(bid)
                    continue
                cycle_start, cycle_end = current_cycle_event_window(
                    timeline,
                    selected_date_et=cycle_day,
                    entry_racks=racks,
                    as_of_end=prior_end,
                )
                if manager_completion_belongs_to_cycle(
                    ts, cycle_start=cycle_start, cycle_end=cycle_end
                ):
                    completed.add(bid)

    return completed


def classify_opening_scrape_membership(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Any]]:
    """
    Classify first-scrape admits into Opening Carryover / Opening New.

    Excludes only bags canonically completed before selected-day opening.
    Does **not** require same-day Dirty/Zipvan for Opening Carryover.
    Added-during-day rows (later scrapes) are left unchanged.
    """
    if not membership:
        return membership, [], {
            "opening_carryover_bag_ids": [],
            "opening_new_bag_ids": [],
            "excluded_completed_before_opening_bag_ids": [],
        }

    opening_ids = [
        bid
        for bid, row in membership.items()
        if str(row.get("inclusion_source") or "") in _OPENING_INCLUSION_SOURCES
        or str(row.get("inclusion_source") or "") == "FIRST_SCRAPE_BASELINE"
    ]
    # Also treat unmarked first-scrape rows (source scrape = baseline) as opening.
    if not opening_ids:
        opening_ids = [
            bid
            for bid, row in membership.items()
            if str(row.get("inclusion_source") or "") != INCLUSION_ADDED_LATER
        ]

    prior_ids = _load_prior_day_membership_ids(cursor, organization_id, selected_date_et)
    svc_map = {
        bid: str((membership[bid] or {}).get("service_type_portal") or "WF").upper()
        for bid in opening_ids
    }
    completed_before = _bags_canonically_completed_before_opening(
        cursor,
        organization_id,
        selected_date_et,
        opening_ids,
        service_type_by_bag=svc_map,
    )

    kept: dict[str, dict[str, Any]] = {}
    excluded: list[str] = []
    opening_carryover: list[str] = []
    opening_new: list[str] = []

    for bid, row in membership.items():
        src = str(row.get("inclusion_source") or "")
        is_opening = (
            src in _OPENING_INCLUSION_SOURCES
            or src == "FIRST_SCRAPE_BASELINE"
            or (src != INCLUSION_ADDED_LATER and bid in opening_ids)
        )
        if not is_opening:
            kept[bid] = dict(row)
            continue
        if bid in completed_before:
            excluded.append(bid)
            continue
        next_row = dict(row)
        if bid in prior_ids:
            next_row["inclusion_source"] = INCLUSION_OPENING_CARRYOVER
            next_row["membership_note"] = "opening_carryover_prior_day_active"
            next_row.pop("requalified_from_prior_day", None)
            opening_carryover.append(bid)
        else:
            next_row["inclusion_source"] = INCLUSION_OPENING_NEW
            next_row["membership_note"] = "opening_new_same_day"
            opening_new.append(bid)
        kept[bid] = next_row

    meta = {
        "opening_carryover_bag_ids": sorted(opening_carryover),
        "opening_new_bag_ids": sorted(opening_new),
        "excluded_completed_before_opening_bag_ids": sorted(excluded),
    }
    return kept, sorted(excluded), meta


def exclude_prior_day_portal_carryins(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Backward-compat wrapper — CP2B opening classification (no Dirty requalify)."""
    kept, excluded, _meta = classify_opening_scrape_membership(
        cursor, organization_id, selected_date_et, membership
    )
    return kept, excluded


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
            "opening_carryover_count": 0,
            "opening_new_count": 0,
            "added_later_count": 0,
            "total_count": 0,
            "opening_carryover_bag_ids": [],
            "opening_new_bag_ids": [],
            "excluded_prior_day_carryin_count": 0,
            "excluded_prior_day_carryin_bag_ids": [],
            "excluded_completed_before_opening_count": 0,
            "excluded_completed_before_opening_bag_ids": [],
            "fresh_start_no_prior_day_carryover": False,
            "includes_opening_carryover": True,
            "membership_policy": "opening_carryover_v1",
            "membership_copy": (
                "Today's active workload includes opening carryover and bags added during the day."
            ),
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
            # Provisional — classify_opening_scrape_membership sets Carryover/New.
            "inclusion_source": INCLUSION_OPENING_NEW,
            "source_scrape_id": baseline_id,
            "first_included_at": baseline_finished,
            "first_seen_portal_at": baseline_finished,
            "last_seen_during_day": baseline_finished,
            "rush_flag": row.get("rush_flag"),
            "service_type_portal": row.get("service_type"),
            "customer_name": row.get("customer_name"),
            "estimated_delivery_date": row.get("estimated_delivery_date"),
        }

    later = list_later_valid_scrapes_same_day(
        cursor,
        organization_id,
        selected_date_et,
        after_run_id=baseline_id,
        after_finished_et=baseline_finished or naive_et_day_start(selected_date_et),
    )
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
                "estimated_delivery_date": row.get("estimated_delivery_date"),
            }

    opening_meta = {
        "opening_carryover_bag_ids": [],
        "opening_new_bag_ids": [],
        "excluded_completed_before_opening_bag_ids": [],
    }
    excluded_completed: list[str] = []
    if apply_prior_day_filter:
        membership, excluded_completed, opening_meta = classify_opening_scrape_membership(
            cursor, organization_id, selected_date_et, membership
        )
    else:
        # Unfiltered rebuild (e.g. prior-day live evidence): keep provisional sources.
        opening_meta["opening_new_bag_ids"] = sorted(
            b
            for b, m in membership.items()
            if m.get("inclusion_source") != INCLUSION_ADDED_LATER
        )

    opening_carryover_ids = list(opening_meta.get("opening_carryover_bag_ids") or [])
    opening_new_ids = list(opening_meta.get("opening_new_bag_ids") or [])
    # Opening admits = carryover ∪ new (baseline_bag_ids keeps this union for compat).
    baseline_ids = sorted(set(opening_carryover_ids) | set(opening_new_ids))
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
    def _portal_rush_bucket(rush_flag: Any) -> str:
        # Same Shift Monitor portal classifier as workload._rush_bucket.
        v = str(rush_flag or "").strip().lower()
        if not v:
            return "UNKNOWN"
        if "non" in v:
            return "NON_RUSH"
        if "rush" in v or v in ("1", "true", "yes", "y"):
            return "RUSH"
        return "NON_RUSH"

    carryover_rush = {"RUSH": [], "NON_RUSH": [], "UNKNOWN": []}
    for bid in opening_carryover_ids:
        bucket = _portal_rush_bucket((membership.get(bid) or {}).get("rush_flag"))
        carryover_rush.setdefault(bucket, []).append(bid)
    for k in carryover_rush:
        carryover_rush[k] = sorted(carryover_rush[k])

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
        "opening_carryover_bag_ids": sorted(opening_carryover_ids),
        "opening_new_bag_ids": sorted(opening_new_ids),
        "added_later_bag_ids": added_later_ids,
        "added_later": added_later,
        "membership": membership,
        "baseline_count": len(baseline_ids),
        "opening_carryover_count": len(opening_carryover_ids),
        "opening_new_count": len(opening_new_ids),
        "added_later_count": len(added_later_ids),
        "total_count": len(membership),
        # Legacy field: completed-before-opening exclusions (not Dirty-filter carry-ins).
        "excluded_prior_day_carryin_count": 0,
        "excluded_prior_day_carryin_bag_ids": [],
        "excluded_completed_before_opening_count": len(excluded_completed),
        "excluded_completed_before_opening_bag_ids": sorted(excluded_completed),
        "fresh_start_no_prior_day_carryover": False,
        "includes_opening_carryover": True,
        "membership_policy": "opening_carryover_v1",
        "membership_copy": (
            "Today's active workload includes opening carryover and bags added during the day."
        ),
        "opening_scrape_admit_count": len(baseline_ids),
        "added_during_day_count": len(added_later_ids),
        "prior_day_carryover_count": len(opening_carryover_ids),
        "opening_carryover_rush_bag_ids": carryover_rush.get("RUSH") or [],
        "opening_carryover_non_rush_bag_ids": carryover_rush.get("NON_RUSH") or [],
        "opening_carryover_unknown_rush_bag_ids": carryover_rush.get("UNKNOWN") or [],
        "opening_carryover_rush_count": len(carryover_rush.get("RUSH") or []),
        "opening_carryover_non_rush_count": len(carryover_rush.get("NON_RUSH") or []),
        "service_membership": _service_membership_breakdown(membership),
    }


def _service_membership_breakdown(
    membership: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """WF/HD counts for Opening Carryover / Opening New / Added During Day."""
    out = {
        "WF": {
            "opening_carryover": [],
            "opening_new": [],
            "added_during_day": [],
        },
        "HD": {
            "opening_carryover": [],
            "opening_new": [],
            "added_during_day": [],
        },
    }
    for bid, row in (membership or {}).items():
        svc = str((row or {}).get("service_type_portal") or "WF").strip().upper()
        if svc not in out:
            svc = "WF"
        src = str((row or {}).get("inclusion_source") or "")
        if src == INCLUSION_OPENING_CARRYOVER:
            out[svc]["opening_carryover"].append(bid)
        elif src == INCLUSION_ADDED_LATER:
            out[svc]["added_during_day"].append(bid)
        else:
            out[svc]["opening_new"].append(bid)
    for svc in out:
        for key in ("opening_carryover", "opening_new", "added_during_day"):
            out[svc][key] = sorted(out[svc][key])
        out[svc]["opening_carryover_count"] = len(out[svc]["opening_carryover"])
        out[svc]["opening_new_count"] = len(out[svc]["opening_new"])
        out[svc]["added_during_day_count"] = len(out[svc]["added_during_day"])
        out[svc]["total"] = (
            out[svc]["opening_carryover_count"]
            + out[svc]["opening_new_count"]
            + out[svc]["added_during_day_count"]
        )
    return out


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
