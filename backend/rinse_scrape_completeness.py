"""
Scrape completeness guard + two-consecutive-absence disappearance confirmation.

Motivation (Jul 21 incident): a single truncated scrape (16 rows / 1 page vs the
prior complete 107 rows / 5 pages) was still labelled ``success`` and used to flip
91 previously-active bags to ``active=0``. That produced 12 false
DISAPPEARED_WITHOUT_COMPLETION exceptions when only 1 was real.

Two independent protections live here so both the presence writer
(``apply_presence_scrape``) and the read-time Step-1 classifier can share one
definition of "trustworthy / complete run":

  1. WRITE-TIME GUARD — ``evaluate_scrape_completeness``: decide whether a freshly
     captured run is complete enough to be allowed to mark bags missing. An
     anomalous run must NOT deactivate prior bags; the snapshot is still kept.

  2. READ-TIME CONFIRMATION — ``build_disappearance_confirmation``: a bag becomes
     a confirmed disappearance only when it is absent from the two most recent
     *trustworthy* runs. A truncated/anomalous run never counts toward the
     absence streak.

Thresholds are configurable constants (env-overridable). No hard-coded page count
is required; anomalies are detected from row-count consistency versus the most
recent complete run and, when available, the portal-reported order count.

Read-only helpers here never write to the DB.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping, Sequence

# scrape.mjs "natural end" stop reasons (a page-exhausted stop, not a truncation).
# Kept in sync with rinse_portal_scrape_meta.NATURAL_STOP_REASONS.
_NATURAL_STOP_REASONS = frozenset(
    {
        "pagination_redirect",
        "no_table_rows",
        "duplicate_page_fingerprint",
        "no_extractable_rows",
        "duplicate_bag_set",
        "no_next_page_ui",
    }
)
_MAX_PAGES_STOP_REASON = "max_pages_reached"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


# --- Configurable thresholds ------------------------------------------------ #
# Below this prior-population size we do not apply the row-drop guard (small
# populations swing legitimately, e.g. overnight).
SCRAPE_GUARD_MIN_PRIOR_POPULATION = _env_int("SCRAPE_GUARD_MIN_PRIOR_POPULATION", 50)
# A run is anomalous when captured rows fall below this fraction of the prior
# complete run's rows (e.g. 0.60 → a >40% drop is suspicious).
SCRAPE_GUARD_MIN_ROW_FRACTION = _env_float("SCRAPE_GUARD_MIN_ROW_FRACTION", 0.60)
# Captured rows must reconcile with the portal-reported order count: below this
# fraction of the portal's own count is suspicious (captured far less than claimed).
SCRAPE_GUARD_PORTAL_RECONCILE_FRACTION = _env_float(
    "SCRAPE_GUARD_PORTAL_RECONCILE_FRACTION", 0.90
)
# Consecutive trustworthy absences required before a bag is a confirmed disappearance.
SCRAPE_DISAPPEARANCE_MIN_ABSENT_RUNS = _env_int("SCRAPE_DISAPPEARANCE_MIN_ABSENT_RUNS", 2)

# Run statuses that can never be trusted for marking bags missing.
_UNTRUSTWORTHY_STATUSES = frozenset({"failed", "skipped", "anomalous", "running"})

# Confirmation states.
STATE_PRESENT = "PRESENT"
STATE_PENDING_CONFIRMATION = "PENDING_DISAPPEARANCE_CONFIRMATION"
STATE_CONFIRMED = "DISAPPEARED_WITHOUT_COMPLETION"


def _norm_bag(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _portal_reported_orders(scrape_meta: Mapping[str, Any] | None) -> int | None:
    """Best-effort portal 'orders at vendor' count from stored scrape metadata."""
    if not scrape_meta:
        return None
    vhs = scrape_meta.get("vendor_home_summary")
    if isinstance(vhs, Mapping):
        for key in ("orders_at_veewash", "orders_at_vendor", "total_orders"):
            val = vhs.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    continue
    return None


# --------------------------------------------------------------------------- #
# 1. WRITE-TIME completeness guard                                            #
# --------------------------------------------------------------------------- #
def _levels_consistent(a: int | None, b: int | None) -> bool:
    """True when two run row counts agree within the row-fraction band (both > 0)."""
    if not a or not b:
        return False
    lo, hi = (a, b) if a <= b else (b, a)
    return lo >= SCRAPE_GUARD_MIN_ROW_FRACTION * hi


def evaluate_scrape_completeness(
    *,
    captured_rows: int,
    prior_complete_rows: int | None,
    previous_run_rows: int | None = None,
    portal_reported_orders: int | None = None,
    had_errors: bool = False,
    stopped_reason: str | None = None,
    reached_max_pages: bool = False,
    page_loaded: bool = True,
) -> dict[str, Any]:
    """
    Decide whether a freshly captured scrape run is trustworthy/complete.

    Trustworthy → the caller may run mark_missing (set absent bags active=0).
    Not trustworthy → the caller MUST retain prior active state, keep the snapshot,
    and record the reason.

    A sharp row-count drop versus the prior complete run is anomalous UNLESS it is
    corroborated by the immediately-preceding run at a consistent level: two
    consecutive scrapes that agree on a lower level establish a real level shift
    (avoids getting permanently stuck at a stale high baseline). This mirrors the
    downstream "two consecutive trustworthy absences" rule at the population level —
    a single dip can never erase bags; a corroborated level can.

    Pure function; no DB, no I/O.
    """
    captured = int(captured_rows or 0)
    reasons: list[str] = []

    if not page_loaded:
        reasons.append("portal_page_not_loaded")
    if had_errors:
        reasons.append("scrape_errors_present")
    if reached_max_pages or (stopped_reason and stopped_reason == _MAX_PAGES_STOP_REASON):
        reasons.append("reached_max_pages_truncation")
    if stopped_reason and stopped_reason not in _NATURAL_STOP_REASONS and stopped_reason != _MAX_PAGES_STOP_REASON:
        reasons.append(f"unexpected_stop_reason:{stopped_reason}")

    # Primary guard: sharp row-count drop versus the prior complete run, unless the
    # previous run already corroborated this lower level (real downward shift).
    prior = int(prior_complete_rows) if prior_complete_rows is not None else None
    if (
        prior is not None
        and prior >= SCRAPE_GUARD_MIN_PRIOR_POPULATION
        and captured < SCRAPE_GUARD_MIN_ROW_FRACTION * prior
        and not _levels_consistent(captured, previous_run_rows)
    ):
        reasons.append(
            f"row_count_drop:{captured}<{SCRAPE_GUARD_MIN_ROW_FRACTION:.2f}*{prior}"
        )

    # Secondary guard: captured far below what the portal itself reported.
    if (
        portal_reported_orders is not None
        and portal_reported_orders >= SCRAPE_GUARD_MIN_PRIOR_POPULATION
        and captured < SCRAPE_GUARD_PORTAL_RECONCILE_FRACTION * portal_reported_orders
    ):
        reasons.append(
            f"portal_reconcile:{captured}<{SCRAPE_GUARD_PORTAL_RECONCILE_FRACTION:.2f}"
            f"*{portal_reported_orders}"
        )

    trustworthy = not reasons
    return {
        "trustworthy": trustworthy,
        "allow_mark_missing": trustworthy,
        "reason": None if trustworthy else ";".join(reasons),
        "reasons": reasons,
        "captured_rows": captured,
        "prior_complete_rows": prior,
        "portal_reported_orders": portal_reported_orders,
        "thresholds": {
            "min_prior_population": SCRAPE_GUARD_MIN_PRIOR_POPULATION,
            "min_row_fraction": SCRAPE_GUARD_MIN_ROW_FRACTION,
            "portal_reconcile_fraction": SCRAPE_GUARD_PORTAL_RECONCILE_FRACTION,
        },
    }


def _extract_meta(run: Mapping[str, Any]) -> dict[str, Any]:
    meta = run.get("scrape_meta_json") or run.get("scrape_meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = None
    return meta if isinstance(meta, dict) else {}


def classify_runs_chronological(
    runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Annotate each run with ``trustworthy`` using a bootstrap, chronological
    row-consistency pass (oldest → newest).

    A run is trustworthy unless its captured row count collapses versus the most
    recent trustworthy run (or it is failed/anomalous/empty). This avoids a
    fragile fixed page count: "complete" is defined relative to recent complete
    runs. Input order is not required; a copy is sorted by started_at then id.
    """
    ordered = sorted(
        runs,
        key=lambda r: (
            r.get("started_at") or r.get("created_at") or 0,
            int(r.get("id") or 0),
        ),
    )
    last_complete_rows: int | None = None
    prev_rows: int | None = None
    out: list[dict[str, Any]] = []
    for r in ordered:
        rows = int(r.get("rows_found") or 0)
        status = str(r.get("status") or "").strip().lower()
        meta = _extract_meta(r)
        reason: str | None = None
        if status in _UNTRUSTWORTHY_STATUSES:
            trustworthy = False
            reason = f"run_status:{status or 'unknown'}"
        elif rows == 0:
            trustworthy = False
            reason = "zero_rows_captured"
        elif last_complete_rows is None:
            trustworthy = True  # bootstrap
        else:
            verdict = evaluate_scrape_completeness(
                captured_rows=rows,
                prior_complete_rows=last_complete_rows,
                previous_run_rows=prev_rows,
                portal_reported_orders=_portal_reported_orders(meta),
                reached_max_pages=bool(meta.get("reached_max_pages")),
                stopped_reason=str(meta.get("stopped_reason") or "") or None,
            )
            trustworthy = bool(verdict["trustworthy"])
            reason = verdict["reason"]
        annotated = dict(r)
        annotated["trustworthy"] = trustworthy
        annotated["trust_reason"] = reason
        if trustworthy:
            last_complete_rows = rows
        prev_rows = rows
        out.append(annotated)
    return out


# --------------------------------------------------------------------------- #
# 2. READ-TIME disappearance confirmation                                     #
# --------------------------------------------------------------------------- #
def load_recent_presence_runs(
    cursor,
    organization_id: int,
    *,
    portal_status: str = "at_vendor",
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Most recent real (non-dry-run) presence runs for a portal_status, chronological."""
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return []
    cursor.execute(
        """
        SELECT id, portal_status, status, rows_found, pages_visited,
               started_at, finished_at, scrape_meta_json
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND dry_run = 0 AND portal_status = %s
        ORDER BY started_at DESC, id DESC
        LIMIT %s
        """,
        (int(organization_id), portal_status, int(limit)),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    return classify_runs_chronological(rows)


def load_run_presence_for_bags(
    cursor,
    organization_id: int,
    *,
    run_ids: Sequence[int],
    bag_ids: Iterable[str],
) -> dict[int, set[str]]:
    """{presence_run_id: {bag_id seen in that run's immutable snapshot}}."""
    from backend.ta_helpers import table_exists

    bags = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    ids = [int(r) for r in run_ids if r is not None]
    if not bags or not ids or not table_exists(
        cursor, "rinse_cleaner_ticket_presence_run_rows"
    ):
        return {}
    run_ph = ",".join(["%s"] * len(ids))
    bag_ph = ",".join(["%s"] * len(bags))
    cursor.execute(
        f"""
        SELECT presence_run_id, bag_id
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE organization_id = %s
          AND presence_run_id IN ({run_ph})
          AND bag_id IN ({bag_ph})
        """,
        (int(organization_id), *ids, *bags),
    )
    out: dict[int, set[str]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        rid = int(row.get("presence_run_id") or 0)
        bid = _norm_bag(row.get("bag_id"))
        if rid and bid:
            out.setdefault(rid, set()).add(bid)
    return out


def confirm_disappearances_from_runs(
    trust_runs: Sequence[Mapping[str, Any]],
    presence_by_run: Mapping[int, set[str]],
    candidate_bag_ids: Iterable[str],
    *,
    min_absent_runs: int = SCRAPE_DISAPPEARANCE_MIN_ABSENT_RUNS,
) -> dict[str, dict[str, Any]]:
    """
    Pure confirmation logic. ``trust_runs`` is chronological with a ``trustworthy``
    flag (from classify_runs_chronological). Only trustworthy runs count toward the
    absence streak; anomalous runs are skipped entirely.

    For each candidate: count the consecutive most-recent trustworthy runs in which
    it is ABSENT.
      absent_streak >= min_absent_runs → confirmed disappearance
      absent_streak == 1..min-1        → pending confirmation (stays operationally pending)
      absent_streak == 0               → present (still in the latest complete scrape)
    """
    # Most-recent trustworthy runs first.
    trusted = [r for r in sorted(
        trust_runs,
        key=lambda r: (r.get("started_at") or 0, int(r.get("id") or 0)),
        reverse=True,
    ) if r.get("trustworthy")]

    out: dict[str, dict[str, Any]] = {}
    for raw in candidate_bag_ids:
        bid = _norm_bag(raw)
        if not bid:
            continue
        absent_streak = 0
        counted_runs: list[int] = []
        for r in trusted:
            rid = int(r.get("id") or 0)
            seen = presence_by_run.get(rid, set())
            if bid in seen:
                break  # present in this (more recent) complete run → streak ends
            absent_streak += 1
            counted_runs.append(rid)
        if absent_streak >= min_absent_runs:
            state = STATE_CONFIRMED
        elif absent_streak >= 1:
            state = STATE_PENDING_CONFIRMATION
        else:
            state = STATE_PRESENT
        out[bid] = {
            "state": state,
            "trustworthy_absent_runs": absent_streak,
            "absent_run_ids": counted_runs,
            "trustworthy_runs_available": len(trusted),
        }
    return out


def latest_trustworthy_run_rows(
    cursor, organization_id: int, *, portal_status: str = "at_vendor"
) -> int | None:
    """rows_found of the most recent trustworthy (complete) run, or None."""
    runs = load_recent_presence_runs(cursor, organization_id, portal_status=portal_status)
    for r in sorted(
        runs,
        key=lambda r: (r.get("started_at") or 0, int(r.get("id") or 0)),
        reverse=True,
    ):
        if r.get("trustworthy"):
            return int(r.get("rows_found") or 0)
    return None


def build_disappearance_confirmation(
    cursor,
    organization_id: int,
    candidate_bag_ids: Iterable[str],
    *,
    portal_status: str = "at_vendor",
    min_absent_runs: int = SCRAPE_DISAPPEARANCE_MIN_ABSENT_RUNS,
    run_limit: int = 40,
) -> dict[str, dict[str, Any]]:
    """DB wrapper: classify recent runs, load per-run presence, confirm disappearances."""
    candidates = sorted({_norm_bag(b) for b in candidate_bag_ids if _norm_bag(b)})
    if not candidates:
        return {}
    runs = load_recent_presence_runs(
        cursor, organization_id, portal_status=portal_status, limit=run_limit
    )
    trusted_ids = [int(r["id"]) for r in runs if r.get("trustworthy") and r.get("id")]
    presence_by_run = load_run_presence_for_bags(
        cursor, organization_id, run_ids=trusted_ids, bag_ids=candidates
    )
    return confirm_disappearances_from_runs(
        runs, presence_by_run, candidates, min_absent_runs=min_absent_runs
    )
