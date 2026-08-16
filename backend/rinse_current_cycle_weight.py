"""
Current-cycle PRE/POST weight resolver (WF weight stabilization).

Replaces:
  * lifetime ordinal first/second weight-entry projection
  * first-non-null portal value forever (POST fill-once freeze)

Rules
-----
cycle_anchor        = latest valid sent-to-vendor (via resolve_current_cycle)
entry_at            = first configured-rack move-bag after anchor
garments_reviewed_at= first garments-reviewed after entry_at

PRE event  = latest weight-entry with entry_at <= ts < garments_reviewed_at
POST event = earliest weight-entry with ts > garments_reviewed_at

When ``entry_at`` is missing but ``cycle_anchor`` exists, a narrow **display**
fallback may still select factual PRE evidence from:

  cycle_anchor_at <= weight_event < cycle_end

This does not synthesize entry, clear ENTRY_NOT_FOUND, select POST, or change
completion / review / garments-reviewed logic. Prefer ``weight_role=PRE``;
otherwise the earliest in-window weight-entry.

Role comes from event ordering relative to review.
Numeric pounds come from portal / presence observations (or audited manual
correction). POST may start provisional and later correct when a later eligible
observation differs from PRE.

Finalization (deterministic, no silent freeze)
----------------------------------------------
* MANUAL_CORRECTION — audited override wins and is never auto-overwritten
* CONFIRMED — post-event observation(s) settled on a value that differs from PRE
  with two consecutive agreeing observations (distinct scrape/run IDs), OR a
  single differing value that is also the latest eligible observation
* EQUAL_VALUES_CONFIRMED — two consecutive post-event observations (distinct
  scrape/run IDs) equal PRE (legitimate equal PRE/POST)
* PROVISIONAL — first post-event observation equals PRE (or only one post-event
  obs so far); may still correct
* WAITING_FOR_POST_VALUE — POST event exists, no post-event observation yet
* CONFLICTING_OBSERVATIONS — post-event observations disagree without two
  consecutive agreements

"Two consecutive observations" means:
  * timestamps strictly after the POST weight-entry event
  * different presence/scrape run IDs (duplicate rows from one run collapse)
  * same normalized pounds (tol 0.05)
  * ordered by observed_at

State transitions:
  missing → provisional → confirmed
  provisional → corrected confirmed (later value ≠ PRE with consecutive evidence)

A confirmed portal POST may be superseded only by a stronger portal rule:
two consecutive distinct-run observations agreeing on a new value that still
differs from PRE. Ordinary single later scrapes do not rewrite confirmed.
Manual corrections are never auto-rewritten.

Proposed reconciliation window (reported, not hard-required for correction):
  3 hours after the POST weight-entry (≈ three hourly presence scrapes).
  Evidence from 2026-07-29 org3: stale PRE-valued POSTs typically saw the true
  portal value within 1–4 hours; hourly scrapes dominate. Elapsed time alone
  never confirms a value — correction is evidence-driven.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_cycle_boundary import (
    _event_ts,
    _is_cycle_boundary_sent_to_vendor,
    _norm_purpose,
    _operator,
    resolve_current_cycle,
)
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

STATUS_CONFIRMED = "CONFIRMED"
STATUS_PROVISIONAL = "PROVISIONAL"
STATUS_WAITING_FOR_POST_VALUE = "WAITING_FOR_POST_VALUE"
STATUS_EQUAL_VALUES_CONFIRMED = "EQUAL_VALUES_CONFIRMED"
STATUS_CONFLICTING_OBSERVATIONS = "CONFLICTING_OBSERVATIONS"
STATUS_MANUAL_CORRECTION = "MANUAL_CORRECTION"
STATUS_MISSING = "MISSING"
STATUS_WAITING_FOR_PRE_VALUE = "WAITING_FOR_PRE_VALUE"
STATUS_WAITING_FOR_EVENT = "WAITING_FOR_EVENT"

# Reported reconciliation horizon (not a hard gate for applying a later value).
POST_RECONCILIATION_WINDOW = timedelta(hours=3)

_MANAGER_WEIGHT_SOURCES = frozenset(
    {
        "manager_correction",
        "correct_weight",
        "step1_edit",
        "rinse_step1_edit",
        "operator_manual_correction",
        "OPERATOR_MANUAL_CORRECTION",
    }
)


def _parse_weight(raw: Any) -> float | None:
    return normalize_scan_weight_lbs(raw)


def _coerce_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo is not None else raw
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00").split("+")[0])
        except ValueError:
            return None
    return None


def _weights_equal(a: float | None, b: float | None, *, tol: float = 0.05) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def _is_weight_entry(ev: Mapping[str, Any]) -> bool:
    if is_weight_entry_purpose(ev.get("purpose")):
        return True
    return _norm_purpose(ev.get("purpose")) == "weight-entry"


def _obs_ts(obs: Mapping[str, Any]) -> datetime | None:
    return _coerce_dt(obs.get("observed_at") or obs.get("weight_observed_at"))


def _obs_lbs(obs: Mapping[str, Any]) -> float | None:
    return _parse_weight(
        obs.get("weight_num", obs.get("weight_lbs", obs.get("wf_lbs_num")))
    )


def _obs_run_id(obs: Mapping[str, Any]) -> Any:
    return obs.get("presence_run_id") or obs.get("weight_presence_run_id") or obs.get("run_id")


@dataclass(frozen=True)
class CurrentCycleWeightResult:
    cycle_anchor: datetime | None
    entry_at: datetime | None
    garments_reviewed_at: datetime | None

    pre_weight_event_at: datetime | None
    pre_weight_event_employee: str | None
    pre_weight_event_id: Any = None
    pre_weight_lbs: float | None = None
    pre_weight_observation_at: datetime | None = None
    pre_weight_observation_run: Any = None

    post_weight_event_at: datetime | None = None
    post_weight_event_employee: str | None = None
    post_weight_event_id: Any = None
    post_weight_lbs: float | None = None
    post_weight_observation_at: datetime | None = None
    post_weight_observation_run: Any = None

    pre_resolution_status: str = STATUS_MISSING
    post_resolution_status: str = STATUS_MISSING
    resolution_reason: str | None = None

    # Compatibility aliases used by existing surfaces
    pre_weight_at: datetime | None = None
    post_weight_at: datetime | None = None
    pre_weight_employee: str | None = None
    post_weight_employee: str | None = None
    weight_entry_count: int = 0
    post_weight_event_exists: bool = False
    post_weight_value: float | None = None
    post_weight_valid_for_standard_weight_revenue: bool = False
    pre_weight_source: str | None = None
    post_weight_source: str | None = None
    pre_weight_attach_reason: str | None = None
    post_weight_attach_reason: str | None = None
    corrected_pre_weight_lbs: float | None = None
    corrected_post_weight_lbs: float | None = None

    completion_event_would_change: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)

        def _fmt(v: Any) -> Any:
            if isinstance(v, datetime):
                return v.isoformat(sep=" ")
            return v

        return {k: _fmt(v) for k, v in d.items()}

    def as_weight_info(self) -> dict[str, Any]:
        """Shape compatible with resolve_weight_entry_pair / load_bag_weight_map."""
        return {
            "pre_weight_lbs": self.pre_weight_lbs,
            "post_weight_lbs": self.post_weight_lbs,
            "pre_weight_event_id": self.pre_weight_event_id,
            "post_weight_event_id": self.post_weight_event_id,
            "pre_weight_at": self.pre_weight_event_at or self.pre_weight_at,
            "pre_weight_employee": self.pre_weight_event_employee or self.pre_weight_employee,
            "post_weight_at": self.post_weight_event_at or self.post_weight_at,
            "post_weight_employee": self.post_weight_event_employee or self.post_weight_employee,
            "weight_entry_count": self.weight_entry_count,
            "post_weight_event_exists": self.post_weight_event_exists,
            "post_weight_value": self.post_weight_value
            if self.post_weight_value is not None
            else self.post_weight_lbs,
            "post_weight_valid_for_standard_weight_revenue": bool(
                self.post_weight_lbs is not None and self.post_weight_lbs > 0
            ),
            "pre_weight_source": self.pre_weight_source,
            "pre_weight_observed_at": self.pre_weight_observation_at,
            "pre_weight_attach_batch_id": None,
            "pre_weight_attach_reason": self.pre_weight_attach_reason,
            "post_weight_source": self.post_weight_source,
            "post_weight_observed_at": self.post_weight_observation_at,
            "post_weight_attach_batch_id": None,
            "post_weight_attach_reason": self.post_weight_attach_reason,
            "pre_resolution_status": self.pre_resolution_status,
            "post_resolution_status": self.post_resolution_status,
            "resolution_reason": self.resolution_reason,
            "cycle_anchor": self.cycle_anchor,
            "entry_at": self.entry_at,
            "garments_reviewed_at": self.garments_reviewed_at,
            "corrected_pre_weight_lbs": self.corrected_pre_weight_lbs,
            "corrected_post_weight_lbs": self.corrected_post_weight_lbs,
        }


def select_current_cycle_weight_events(
    timeline: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    entry_racks: Iterable[str] | None = None,
    as_of_end: datetime | None = None,
) -> dict[str, Any]:
    """
    Select PRE/POST weight-entry *events* for the current cycle.

    Does not attach pounds — event identity only.
    """
    cycle = resolve_current_cycle(
        timeline,
        selected_date_et=selected_date_et,
        entry_racks=entry_racks,
        as_of_end=as_of_end,
    )
    anchor = cycle.cycle_anchor_at
    entry_at = cycle.entry_at
    review_at = cycle.garments_reviewed_at

    pre_event = None
    post_event = None
    cycle_weight_events: list[Mapping[str, Any]] = []

    if anchor is not None:
        # Bound to this cycle: after anchor, before next cycle-boundary STV.
        next_send = None
        rack_keys = {
            str(r).strip().lower()
            for r in (entry_racks if entry_racks is not None else DEFAULT_FACILITY_ENTRY_RACKS)
            if str(r).strip()
        }
        for ev in timeline:
            if not _is_cycle_boundary_sent_to_vendor(ev, rack_keys):
                continue
            ts = _event_ts(ev)
            if ts is None or ts <= anchor:
                continue
            if as_of_end is not None and ts > as_of_end:
                continue
            if next_send is None or ts < next_send:
                next_send = ts

        for ev in timeline:
            if not _is_weight_entry(ev):
                continue
            ts = _event_ts(ev)
            if ts is None or ts <= anchor:
                continue
            if as_of_end is not None and ts > as_of_end:
                continue
            if next_send is not None and ts >= next_send:
                continue
            cycle_weight_events.append(ev)

        cycle_weight_events.sort(
            key=lambda e: (_event_ts(e) or datetime.min, e.get("id") or 0)
        )

        if entry_at is not None and review_at is not None:
            pre_cands = []
            for ev in cycle_weight_events:
                ts = _event_ts(ev)
                if ts is None:
                    continue
                if entry_at <= ts < review_at:
                    pre_cands.append(ev)
            if pre_cands:
                pre_event = pre_cands[-1]  # latest pre-review

            for ev in cycle_weight_events:
                ts = _event_ts(ev)
                if ts is None:
                    continue
                if ts > review_at:
                    post_event = ev  # earliest post-review
                    break
        elif entry_at is not None and review_at is None:
            # No review yet — all entry-or-later cycle weights are pre-side candidates.
            pre_cands = []
            for ev in cycle_weight_events:
                ts = _event_ts(ev)
                if ts is None:
                    continue
                if ts >= entry_at:
                    pre_cands.append(ev)
            if pre_cands:
                pre_event = pre_cands[-1]
        elif entry_at is None and anchor is not None:
            # Factual PRE display fallback only. Entry stays unresolved;
            # POST is never selected on this path.
            pre_cands: list[Mapping[str, Any]] = []
            for ev in timeline:
                if not _is_weight_entry(ev):
                    continue
                ts = _event_ts(ev)
                if ts is None:
                    continue
                if as_of_end is not None and ts > as_of_end:
                    continue
                # Approved window: cycle_anchor_at <= ts < cycle_end
                if ts < anchor:
                    continue
                if next_send is not None and ts >= next_send:
                    continue
                pre_cands.append(ev)
            pre_cands.sort(
                key=lambda e: (_event_ts(e) or datetime.min, e.get("id") or 0)
            )
            if pre_cands:
                role_pre = [
                    ev
                    for ev in pre_cands
                    if str(ev.get("weight_role") or "").strip().upper() == "PRE"
                ]
                pre_event = role_pre[-1] if role_pre else pre_cands[0]
            # Explicit: do not assign post_event without entry_at.

    return {
        "cycle": cycle,
        "cycle_anchor": anchor,
        "entry_at": entry_at,
        "garments_reviewed_at": review_at,
        "pre_event": pre_event,
        "post_event": post_event,
        "cycle_weight_events": cycle_weight_events,
        "legacy_completion_event": cycle.completion_event,
    }


def _dedupe_observations_by_run(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Collapse duplicate rows from the same presence/scrape run.

    "Two consecutive observations" means two distinct scrape/run IDs after the
    POST event with the same normalized pounds — not two DB rows from one run.
    When run_id is missing, fall back to distinct observed_at timestamps.
    """
    best: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for obs in observations or []:
        if not isinstance(obs, Mapping):
            continue
        ts = _obs_ts(obs)
        lbs = _obs_lbs(obs)
        if ts is None or lbs is None:
            continue
        run_id = _obs_run_id(obs)
        key = ("run", int(run_id)) if run_id is not None else ("ts", ts.isoformat(sep=" "))
        row = {
            "observed_at": ts,
            "weight_num": lbs,
            "presence_run_id": run_id,
            "presence_run_row_id": obs.get("presence_run_row_id")
            or obs.get("weight_presence_run_row_id"),
            "raw": obs,
        }
        if key not in best:
            order.append(key)
            best[key] = row
        else:
            # Keep earliest row_id within the same run.
            prev = best[key]
            prev_rid = prev.get("presence_run_row_id") or 0
            new_rid = row.get("presence_run_row_id") or 0
            if new_rid and (not prev_rid or new_rid < prev_rid):
                best[key] = row
    out = [best[k] for k in order]
    out.sort(
        key=lambda o: (
            o["observed_at"],
            o.get("presence_run_row_id") or 0,
            o.get("presence_run_id") or 0,
        )
    )
    return out


def _observations_for_event(
    observations: Sequence[Mapping[str, Any]],
    *,
    event_ts: datetime,
    interval_end: datetime | None,
) -> list[dict[str, Any]]:
    """Portal observations eligible to populate a weight-entry event."""
    raw_out: list[dict[str, Any]] = []
    for obs in observations or []:
        if not isinstance(obs, Mapping):
            continue
        ts = _obs_ts(obs)
        lbs = _obs_lbs(obs)
        if ts is None or lbs is None:
            continue
        if ts < event_ts:
            continue
        if interval_end is not None and ts >= interval_end:
            continue
        raw_out.append(obs if isinstance(obs, dict) else dict(obs))
        # Normalize shape for dedupe.
        if "weight_num" not in raw_out[-1] and lbs is not None:
            raw_out[-1] = {
                **raw_out[-1],
                "weight_num": lbs,
                "observed_at": ts,
                "presence_run_id": _obs_run_id(obs),
            }
    return _dedupe_observations_by_run(raw_out)


def _resolve_lbs_from_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    event_ts: datetime | None,
    interval_end: datetime | None,
    peer_lbs: float | None,
    role: str,
    allow_pre_fallback_after_end: bool = False,
) -> dict[str, Any]:
    if event_ts is None:
        return {
            "lbs": None,
            "observation_at": None,
            "observation_run": None,
            "status": STATUS_WAITING_FOR_EVENT,
            "reason": f"no_{role.lower()}_weight_entry_in_current_cycle",
            "source": None,
            "attach_reason": None,
        }

    eligible = _observations_for_event(
        observations, event_ts=event_ts, interval_end=interval_end
    )
    fallback_used = False
    if (
        role == "PRE"
        and not eligible
        and allow_pre_fallback_after_end
        and interval_end is not None
    ):
        # Delayed portal: first numeric observation may arrive after POST scan.
        # Seed PRE from the earliest observation after the PRE event without
        # requiring it to fall before POST event_ts.
        eligible = _observations_for_event(
            observations, event_ts=event_ts, interval_end=None
        )
        fallback_used = bool(eligible)

    if not eligible:
        return {
            "lbs": None,
            "observation_at": None,
            "observation_run": None,
            "status": STATUS_WAITING_FOR_PRE_VALUE
            if role == "PRE"
            else STATUS_WAITING_FOR_POST_VALUE,
            "reason": f"no_portal_observation_after_{role.lower()}_event",
            "source": "portal_weight_num",
            "attach_reason": "waiting_for_presence_observation",
        }

    if role == "PRE":
        hit = eligible[0]
        return {
            "lbs": hit["weight_num"],
            "observation_at": hit["observed_at"],
            "observation_run": hit.get("presence_run_id"),
            "status": STATUS_CONFIRMED,
            "reason": (
                "pre_observation_attached_via_delayed_portal_fallback"
                if fallback_used
                else "pre_observation_attached"
            ),
            "source": "portal_weight_num",
            "attach_reason": (
                "current_cycle_pre_delayed_fallback"
                if fallback_used
                else "current_cycle_interval_observation"
            ),
        }

    # POST — reconcilable, not fill-once.
    first = eligible[0]
    # Look for a value that differs from PRE (correction candidate).
    changed = [o for o in eligible if not _weights_equal(o["weight_num"], peer_lbs)]
    if not changed:
        # All post-event observations still equal PRE (or PRE unknown).
        if len(eligible) >= 2 and _weights_equal(
            eligible[-1]["weight_num"], eligible[-2]["weight_num"]
        ):
            hit = eligible[-1]
            return {
                "lbs": hit["weight_num"],
                "observation_at": hit["observed_at"],
                "observation_run": hit.get("presence_run_id"),
                "status": STATUS_EQUAL_VALUES_CONFIRMED,
                "reason": "two_consecutive_post_observations_equal_pre",
                "source": "portal_weight_num",
                "attach_reason": "current_cycle_equal_values_confirmed",
            }
        return {
            "lbs": first["weight_num"],
            "observation_at": first["observed_at"],
            "observation_run": first.get("presence_run_id"),
            "status": STATUS_PROVISIONAL,
            "reason": "post_observation_still_equals_pre_or_single_obs",
            "source": "portal_weight_num",
            "attach_reason": "current_cycle_provisional_post",
        }

    # Prefer the latest run of two consecutive agreeing changed values.
    confirmed_hit = None
    for i in range(1, len(changed)):
        if _weights_equal(changed[i]["weight_num"], changed[i - 1]["weight_num"]):
            confirmed_hit = changed[i]
    if confirmed_hit is not None:
        return {
            "lbs": confirmed_hit["weight_num"],
            "observation_at": confirmed_hit["observed_at"],
            "observation_run": confirmed_hit.get("presence_run_id"),
            "status": STATUS_CONFIRMED,
            "reason": "later_post_observation_differs_from_pre_two_consecutive",
            "source": "portal_weight_num",
            "attach_reason": "current_cycle_post_corrected",
        }

    # Multiple distinct changed values without a consecutive agreeing pair.
    distinct_changed: list[float] = []
    for o in changed:
        lbs = float(o["weight_num"])
        if not any(_weights_equal(lbs, prev) for prev in distinct_changed):
            distinct_changed.append(lbs)
    if len(distinct_changed) >= 2:
        last_changed = changed[-1]
        return {
            "lbs": last_changed["weight_num"],
            "observation_at": last_changed["observed_at"],
            "observation_run": last_changed.get("presence_run_id"),
            "status": STATUS_CONFLICTING_OBSERVATIONS,
            "reason": "post_observations_conflict_without_consecutive_agreement",
            "source": "portal_weight_num",
            "attach_reason": "current_cycle_conflicting_post",
        }

    last_changed = changed[-1]
    latest_eligible = eligible[-1]
    if _weights_equal(latest_eligible["weight_num"], last_changed["weight_num"]):
        # Single differing value that is also the latest eligible observation.
        return {
            "lbs": last_changed["weight_num"],
            "observation_at": last_changed["observed_at"],
            "observation_run": last_changed.get("presence_run_id"),
            "status": STATUS_CONFIRMED,
            "reason": "later_post_observation_differs_from_pre",
            "source": "portal_weight_num",
            "attach_reason": "current_cycle_post_corrected",
        }

    return {
        "lbs": last_changed["weight_num"],
        "observation_at": last_changed["observed_at"],
        "observation_run": last_changed.get("presence_run_id"),
        "status": STATUS_PROVISIONAL,
        "reason": "post_change_seen_awaiting_confirmation",
        "source": "portal_weight_num",
        "attach_reason": "current_cycle_post_corrected",
    }


def resolve_current_cycle_weights(
    timeline: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    observations: Sequence[Mapping[str, Any]] | None = None,
    entry_racks: Iterable[str] | None = None,
    as_of_end: datetime | None = None,
    manual_pre_lbs: float | None = None,
    manual_post_lbs: float | None = None,
    prefer_event_attached_lbs: bool = True,
) -> CurrentCycleWeightResult:
    """
    Canonical current-cycle PRE/POST resolver for all surfaces.

    Precedence for pounds:
      audited manual correction > confirmed/provisional portal > missing
    Event-attached lbs on the selected scan may seed when no observations list
    is provided (offline / fixture mode).
    """
    selected = select_current_cycle_weight_events(
        timeline,
        selected_date_et=selected_date_et,
        entry_racks=entry_racks,
        as_of_end=as_of_end,
    )
    cycle = selected["cycle"]
    pre_event = selected["pre_event"]
    post_event = selected["post_event"]
    pre_ts = _event_ts(pre_event) if pre_event else None
    post_ts = _event_ts(post_event) if post_event else None
    obs = list(observations or [])

    notes: list[str] = []
    # Interval ends: PRE ends at POST event (or +inf); POST open-ended within cycle.
    pre_resolved = _resolve_lbs_from_observations(
        obs,
        event_ts=pre_ts,
        interval_end=post_ts,
        peer_lbs=None,
        role="PRE",
        allow_pre_fallback_after_end=True,
    )
    # Seed from scan-attached lbs when observations absent / empty interval.
    if pre_resolved["lbs"] is None and prefer_event_attached_lbs and pre_event is not None:
        seeded = _parse_weight(pre_event.get("weight_lbs"))
        if seeded is not None:
            pre_resolved = {
                "lbs": seeded,
                "observation_at": _coerce_dt(pre_event.get("weight_observed_at")),
                "observation_run": pre_event.get("weight_presence_run_id"),
                "status": STATUS_CONFIRMED
                if pre_event.get("weight_source")
                else STATUS_PROVISIONAL,
                "reason": "seeded_from_selected_pre_event_weight_lbs",
                "source": pre_event.get("weight_source") or "scan_event_weight_lbs",
                "attach_reason": pre_event.get("weight_attach_reason")
                or "selected_event_seed",
            }
            notes.append("pre_seeded_from_event_weight_lbs")

    post_resolved = _resolve_lbs_from_observations(
        obs,
        event_ts=post_ts,
        interval_end=None,
        peer_lbs=pre_resolved.get("lbs"),
        role="POST",
    )
    if post_resolved["lbs"] is None and prefer_event_attached_lbs and post_event is not None:
        seeded = _parse_weight(post_event.get("weight_lbs"))
        if seeded is not None:
            # If seeded equals PRE, keep provisional unless manual.
            status = STATUS_PROVISIONAL
            reason = "seeded_from_selected_post_event_weight_lbs"
            if pre_resolved.get("lbs") is not None and _weights_equal(
                seeded, pre_resolved.get("lbs")
            ):
                status = STATUS_PROVISIONAL
                reason = "seeded_post_equals_pre_pending_reconciliation"
            elif pre_resolved.get("lbs") is not None and not _weights_equal(
                seeded, pre_resolved.get("lbs")
            ):
                status = STATUS_CONFIRMED
                reason = "seeded_post_differs_from_pre"
            post_resolved = {
                "lbs": seeded,
                "observation_at": _coerce_dt(post_event.get("weight_observed_at")),
                "observation_run": post_event.get("weight_presence_run_id"),
                "status": status,
                "reason": reason,
                "source": post_event.get("weight_source") or "scan_event_weight_lbs",
                "attach_reason": post_event.get("weight_attach_reason")
                or "selected_event_seed",
            }
            notes.append("post_seeded_from_event_weight_lbs")

    # Manual correction precedence.
    pre_status = pre_resolved["status"]
    post_status = post_resolved["status"]
    pre_lbs = pre_resolved["lbs"]
    post_lbs = post_resolved["lbs"]
    pre_source = pre_resolved.get("source")
    post_source = post_resolved.get("source")
    pre_attach = pre_resolved.get("attach_reason")
    post_attach = post_resolved.get("attach_reason")
    corrected_pre = None
    corrected_post = None
    reason_parts = [pre_resolved.get("reason"), post_resolved.get("reason")]

    if manual_pre_lbs is not None:
        corrected_pre = float(manual_pre_lbs)
        pre_lbs = corrected_pre
        pre_status = STATUS_MANUAL_CORRECTION
        pre_source = "manager_correction"
        pre_attach = "audited_manual_correction"
        reason_parts.append("manual_pre_override")
    if manual_post_lbs is not None:
        corrected_post = float(manual_post_lbs)
        post_lbs = corrected_post
        post_status = STATUS_MANUAL_CORRECTION
        post_source = "manager_correction"
        post_attach = "audited_manual_correction"
        reason_parts.append("manual_post_override")

    # Also honor manager sources already stamped on the selected events.
    if pre_event is not None:
        src = str(pre_event.get("weight_source") or "").strip()
        if src in _MANAGER_WEIGHT_SOURCES and _parse_weight(pre_event.get("weight_lbs")) is not None:
            corrected_pre = _parse_weight(pre_event.get("weight_lbs"))
            pre_lbs = corrected_pre
            pre_status = STATUS_MANUAL_CORRECTION
            pre_source = src
            pre_attach = "audited_manual_correction"
    if post_event is not None:
        src = str(post_event.get("weight_source") or "").strip()
        fname = str(post_event.get("source_filename") or "")
        if (
            src in _MANAGER_WEIGHT_SOURCES or "MANUAL_CORRECTION" in fname.upper()
        ) and _parse_weight(post_event.get("weight_lbs")) is not None:
            corrected_post = _parse_weight(post_event.get("weight_lbs"))
            post_lbs = corrected_post
            post_status = STATUS_MANUAL_CORRECTION
            post_source = src or "operator_manual_correction"
            post_attach = "audited_manual_correction"

    if pre_event is None:
        pre_status = STATUS_WAITING_FOR_EVENT if cycle.entry_at else STATUS_MISSING
    if post_event is None:
        if cycle.garments_reviewed_at is None:
            post_status = STATUS_WAITING_FOR_EVENT
        else:
            post_status = STATUS_WAITING_FOR_EVENT

    weight_entry_count = 0
    if pre_event is not None:
        weight_entry_count += 1
    if post_event is not None:
        weight_entry_count += 1

    # Protect completion event identity: flag if ordinal-era completion event
    # differs from selected POST (caller must not auto-apply status changes).
    legacy = selected.get("legacy_completion_event")
    completion_event_would_change = False
    if legacy is not None and post_event is not None:
        if (legacy.get("id") or None) != (post_event.get("id") or None):
            # Same timestamp still OK; only flag id divergence when both have ids.
            if legacy.get("id") is not None and post_event.get("id") is not None:
                completion_event_would_change = True
                notes.append("selected_post_event_differs_from_cycle_completion_event")

    reason = "; ".join(str(p) for p in reason_parts if p)

    return CurrentCycleWeightResult(
        cycle_anchor=selected["cycle_anchor"],
        entry_at=selected["entry_at"],
        garments_reviewed_at=selected["garments_reviewed_at"],
        pre_weight_event_at=pre_ts,
        pre_weight_event_employee=_operator(pre_event) if pre_event else None,
        pre_weight_event_id=(pre_event or {}).get("id") if pre_event else None,
        pre_weight_lbs=pre_lbs,
        pre_weight_observation_at=pre_resolved.get("observation_at"),
        pre_weight_observation_run=pre_resolved.get("observation_run"),
        post_weight_event_at=post_ts,
        post_weight_event_employee=_operator(post_event) if post_event else None,
        post_weight_event_id=(post_event or {}).get("id") if post_event else None,
        post_weight_lbs=post_lbs,
        post_weight_observation_at=post_resolved.get("observation_at"),
        post_weight_observation_run=post_resolved.get("observation_run"),
        pre_resolution_status=pre_status,
        post_resolution_status=post_status,
        resolution_reason=reason or None,
        pre_weight_at=pre_ts,
        post_weight_at=post_ts,
        pre_weight_employee=_operator(pre_event) if pre_event else None,
        post_weight_employee=_operator(post_event) if post_event else None,
        weight_entry_count=weight_entry_count,
        post_weight_event_exists=post_event is not None,
        post_weight_value=post_lbs,
        post_weight_valid_for_standard_weight_revenue=bool(
            post_lbs is not None and post_lbs > 0
        ),
        pre_weight_source=pre_source,
        post_weight_source=post_source,
        pre_weight_attach_reason=pre_attach,
        post_weight_attach_reason=post_attach,
        corrected_pre_weight_lbs=corrected_pre,
        corrected_post_weight_lbs=corrected_post,
        completion_event_would_change=completion_event_would_change,
        notes=tuple(notes),
    )


def classify_post_repair(
    *,
    current_post: float | None,
    proposed_post: float | None,
    post_status: str,
    manual_locked: bool,
    completion_event_would_change: bool,
    event_chain_complete: bool = False,
    post_event_deterministic: bool = False,
    before_state_matches: bool = True,
) -> str:
    """
    Bucket for the prepared (not executed) repair plan.

    Safe automatic requires all of:
      - before-state still matches validation snapshot
      - current-cycle event chain complete (entry + garments-reviewed + POST event)
      - selected POST event deterministic
      - portal observation confirmed (CONFIRMED or EQUAL_VALUES_CONFIRMED)
      - no manual correction
      - no conflicting observation remains
    """
    if manual_locked or post_status == STATUS_MANUAL_CORRECTION:
        return "manual_protected"
    if completion_event_would_change:
        return "needs_manager_review"
    if post_status == STATUS_CONFLICTING_OBSERVATIONS:
        return "insufficient_evidence"
    if proposed_post is None:
        return "insufficient_evidence"
    if not before_state_matches:
        return "needs_manager_review"
    if current_post is not None and _weights_equal(current_post, proposed_post):
        return "already_correct"

    confirmed = post_status in (STATUS_CONFIRMED, STATUS_EQUAL_VALUES_CONFIRMED)
    if (
        confirmed
        and event_chain_complete
        and post_event_deterministic
        and not manual_locked
    ):
        return "safe_automatic_correction"
    if post_status == STATUS_PROVISIONAL:
        return "insufficient_evidence"
    return "insufficient_evidence"


def _load_manual_corrections(
    cursor, organization_id: int, bag_ids: Sequence[str]
) -> dict[str, dict[str, float | None]]:
    from backend.ta_helpers import table_exists

    out: dict[str, dict[str, float | None]] = {b: {} for b in bag_ids}
    if not bag_ids or not table_exists(cursor, "rinse_step1_corrections"):
        return out
    placeholders = ",".join(["%s"] * len(bag_ids))
    cursor.execute(
        f"""
        SELECT bag_id, new_values, created_at, id
        FROM rinse_step1_corrections
        WHERE organization_id = %s
          AND bag_id IN ({placeholders})
          AND action = 'correct_weight'
        ORDER BY created_at ASC, id ASC
        """,
        (int(organization_id), *bag_ids),
    )
    for row in cursor.fetchall() or []:
        bid = str(row.get("bag_id") or "").strip().upper()
        if bid not in out:
            continue
        raw = row.get("new_values")
        if isinstance(raw, str):
            try:
                import json

                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            continue
        pre = _parse_weight(raw.get("corrected_pre_weight_lbs"))
        post = _parse_weight(raw.get("corrected_post_weight_lbs"))
        if post is None and raw.get("corrected_pre_weight_lbs") is None:
            post = _parse_weight(raw.get("post_weight_lbs", raw.get("weight_lbs")))
        if pre is not None:
            out[bid]["pre"] = pre
        if post is not None:
            out[bid]["post"] = post
    return out


def load_current_cycle_weight_map(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    selected_date_et: date,
    entry_racks: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    DB-backed current-cycle PRE/POST map for Shift Monitor / workload / EP.

    Loads full scan timelines + presence observations, then resolves each bag.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({str(b or "").strip().upper() for b in bag_ids if str(b or "").strip()})
    empty = {b: resolve_current_cycle_weights([], selected_date_et=selected_date_et).as_weight_info() for b in ids}
    if not ids:
        return {}

    timelines: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if table_exists(cursor, "rinse_bag_scan_events"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT id, bag_id, purpose, rack, user_name, scanned_at_parsed,
                   weight_lbs, weight_role, weight_source, weight_observed_at,
                   weight_attach_reason, weight_presence_run_id,
                   weight_presence_run_row_id, source_filename
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed IS NOT NULL
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid in timelines:
                timelines[bid].append(dict(row))

    observations: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        placeholders = ",".join(["%s"] * len(ids))
        # Include prior evening observations for overnight send cycles.
        day_start = datetime(selected_date_et.year, selected_date_et.month, selected_date_et.day)
        window_start = day_start - timedelta(hours=12)
        window_end = day_start + timedelta(days=1)
        cursor.execute(
            f"""
            SELECT id AS presence_run_row_id, presence_run_id, bag_id,
                   weight_num, wf_lbs_num, observed_at
            FROM rinse_cleaner_ticket_presence_run_rows
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND observed_at >= %s AND observed_at < %s
            ORDER BY observed_at ASC, id ASC
            """,
            (int(organization_id), *ids, window_start, window_end),
        )
        for row in cursor.fetchall() or []:
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid in observations:
                observations[bid].append(dict(row))

    manuals = _load_manual_corrections(cursor, organization_id, ids)
    out: dict[str, dict[str, Any]] = {}
    for bid in ids:
        manual = manuals.get(bid) or {}
        result = resolve_current_cycle_weights(
            timelines.get(bid) or [],
            selected_date_et=selected_date_et,
            observations=observations.get(bid) or [],
            entry_racks=entry_racks,
            manual_pre_lbs=manual.get("pre"),
            manual_post_lbs=manual.get("post"),
        )
        out[bid] = result.as_weight_info()
        out[bid]["_resolver"] = "current_cycle_weight"
        out[bid]["_raw_result"] = result.as_dict()
    return out
