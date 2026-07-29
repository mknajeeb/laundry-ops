"""
Current-cycle boundary for Shift Monitor entry/completion.

Non-negotiable invariant
------------------------
A scan from a previous ``sent-to-vendor`` cycle can never determine the
current cycle's entry, completion, or status.

Architectural rules (not an ID-specific patch)
----------------------------------------------
* ``cycle_anchor`` = latest valid ``purpose='sent-to-vendor'`` on or before
  the selected ET day cutoff.
* Ignore every Rinse scan at or before that anchor when resolving the
  current cycle's entry and completion.
* Entry = first post-anchor ``purpose='move-bag'`` whose rack is in the
  configured entry racks (default: VeeWash Dirty, Rinse Zipvan).
* Garments-reviewed counts only when it occurs **after** that entry.
* Completion = earliest valid ``purpose='weight-entry'`` after that
  post-entry garments-reviewed. Clean rack is **not** required.
* Required ordering:
  ``cycle_anchor < entry_at < garments_reviewed_at < completion_weight_at``
* Garments-reviewed + weight **without** qualifying entry must not complete.
  Result: ``effective_status=pending``, ``pending_reason=ENTRY_NOT_FOUND``,
  ``completion_at=null``.
* Raw scan history stays append-only; duplicate post-review weights complete
  the bag once (earliest qualifying weight).

Do not use lifetime first clean-rack, lifetime first weight-entry, old
garments-reviewed, old completion timestamps, or ordinal weight-entry alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_purpose import normalize_scan_purpose

COMPLETION_SOURCE_POST_REVIEW_WEIGHT = "post_garments_reviewed_weight_entry"
PENDING_REASON_ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"


def _norm_purpose(raw: Any) -> str:
    """Normalize portal purposes; strip trailing 'Last Scan' suffixes."""
    p = normalize_scan_purpose(raw)
    for base in (
        "sent-to-vendor",
        "move-bag",
        "garments-reviewed",
        "weight-entry",
    ):
        if p == base or p.startswith(f"{base}-") or p.startswith(f"{base} "):
            return base
    # normalize_scan_purpose already hyphenates; handle "move-bag-last-scan"
    if p.startswith("move-bag"):
        return "move-bag"
    if p.startswith("weight-entry"):
        return "weight-entry"
    if p.startswith("sent-to-vendor"):
        return "sent-to-vendor"
    if p.startswith("garments-reviewed"):
        return "garments-reviewed"
    return p


def _event_ts(ev: Mapping[str, Any]) -> datetime | None:
    for key in ("scanned_at_parsed", "scanned_at", "timestamp"):
        raw = ev.get(key)
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00").split("+")[0])
            except ValueError:
                continue
    return None


def _operator(ev: Mapping[str, Any]) -> str | None:
    for key in ("user_name", "completed_by", "user"):
        val = ev.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _entry_rack_keys(entry_racks: Iterable[str] | None) -> set[str]:
    racks = list(entry_racks) if entry_racks is not None else list(DEFAULT_FACILITY_ENTRY_RACKS)
    return {str(r).strip().lower() for r in racks if str(r).strip()}


@dataclass(frozen=True)
class CycleBoundaryResult:
    cycle_anchor_at: datetime | None
    entry_at: datetime | None
    entry_rack: str | None
    entry_event: Mapping[str, Any] | None
    garments_reviewed_at: datetime | None
    garments_reviewed_event: Mapping[str, Any] | None
    completion_at: datetime | None
    completed_by: str | None
    completion_event: Mapping[str, Any] | None
    completion_source: str | None
    effective_status: str  # pending | completed
    pending_reason: str | None = None
    via_clean_rack_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        def _fmt(ts: datetime | None) -> str | None:
            return ts.isoformat(sep=" ") if ts is not None else None

        return {
            "cycle_anchor_at": _fmt(self.cycle_anchor_at),
            "entry_at": _fmt(self.entry_at),
            "entry_rack": self.entry_rack,
            "garments_reviewed_at": _fmt(self.garments_reviewed_at),
            "completion_at": _fmt(self.completion_at),
            "completed_by": self.completed_by,
            "completion_source": self.completion_source,
            "effective_status": self.effective_status,
            "pending_reason": self.pending_reason,
            "via_clean_rack_required": self.via_clean_rack_required,
        }


def resolve_cycle_anchor(
    timeline: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> datetime | None:
    """Latest valid sent-to-vendor on or before the selected ET day cutoff."""
    cutoff = naive_et_day_end_inclusive(selected_date_et)
    best: datetime | None = None
    for ev in timeline:
        if _norm_purpose(ev.get("purpose")) != "sent-to-vendor":
            continue
        ts = _event_ts(ev)
        if ts is None or ts > cutoff:
            continue
        if best is None or ts > best:
            best = ts
    return best


def resolve_current_cycle(
    timeline: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    entry_racks: Iterable[str] | None = None,
    as_of_end: datetime | None = None,
    cycle_anchor_override: datetime | None = None,
) -> CycleBoundaryResult:
    """
    Resolve current-cycle entry and completion for one bag on an ET day.

    Pre-anchor scans are ignored for entry and completion. Clean rack is never
    required for completion. Completion requires the full chain:

      sent-to-vendor → configured entry → garments-reviewed → weight-entry

    ``as_of_end`` (optional) limits which post-anchor events are visible — used
    by At Vendor live/as-of evaluation without changing the day-cutoff anchor.

    ``cycle_anchor_override`` evaluates a specific sent-to-vendor cycle (used by
    immutable same-day attribution across repeat trips). When omitted, the
    latest valid sent-to-vendor on/before the selected day cutoff is used.
    """
    anchor = cycle_anchor_override
    if anchor is None:
        anchor = resolve_cycle_anchor(timeline, selected_date_et=selected_date_et)
    empty = CycleBoundaryResult(
        cycle_anchor_at=anchor,
        entry_at=None,
        entry_rack=None,
        entry_event=None,
        garments_reviewed_at=None,
        garments_reviewed_event=None,
        completion_at=None,
        completed_by=None,
        completion_event=None,
        completion_source=None,
        effective_status="pending",
        pending_reason=None,
        via_clean_rack_required=False,
    )
    if anchor is None:
        return empty

    rack_keys = _entry_rack_keys(entry_racks)
    # Strictly after this cycle's anchor; stop before a later sent-to-vendor
    # so repeat-trip cycles do not bleed into each other.
    next_send: datetime | None = None
    for ev in timeline:
        if _norm_purpose(ev.get("purpose")) != "sent-to-vendor":
            continue
        ts = _event_ts(ev)
        if ts is None or ts <= anchor:
            continue
        if as_of_end is not None and ts > as_of_end:
            continue
        if next_send is None or ts < next_send:
            next_send = ts

    post = []
    for ev in timeline:
        ts = _event_ts(ev)
        if ts is None or ts <= anchor:
            continue
        if as_of_end is not None and ts > as_of_end:
            continue
        if next_send is not None and ts >= next_send:
            continue
        post.append((ts, ev))
    post.sort(key=lambda item: item[0])

    entry_at = None
    entry_rack = None
    entry_event = None
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "move-bag":
            continue
        rack = str(ev.get("rack") or "").strip()
        if rack.lower() not in rack_keys:
            continue
        entry_at = ts
        entry_rack = rack
        entry_event = ev
        break

    # Detect review+weight that would have completed without entry (CUR0 pattern).
    orphan_review_at: datetime | None = None
    orphan_weight_after_review = False
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        orphan_review_at = ts
        break
    if orphan_review_at is not None:
        for ts, ev in post:
            if ts <= orphan_review_at:
                continue
            if _norm_purpose(ev.get("purpose")) == "weight-entry":
                orphan_weight_after_review = True
                break

    if entry_at is None:
        pending_reason = None
        if orphan_review_at is not None and orphan_weight_after_review:
            pending_reason = PENDING_REASON_ENTRY_NOT_FOUND
        elif orphan_review_at is not None:
            pending_reason = PENDING_REASON_ENTRY_NOT_FOUND
        return CycleBoundaryResult(
            cycle_anchor_at=anchor,
            entry_at=None,
            entry_rack=None,
            entry_event=None,
            garments_reviewed_at=None,
            garments_reviewed_event=None,
            completion_at=None,
            completed_by=None,
            completion_event=None,
            completion_source=None,
            effective_status="pending",
            pending_reason=pending_reason,
            via_clean_rack_required=False,
        )

    review_at = None
    review_event = None
    for ts, ev in post:
        if ts <= entry_at:
            continue
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        review_at = ts
        review_event = ev
        break

    completion_at = None
    completion_event = None
    completed_by = None
    completion_source = None
    if review_at is not None:
        for ts, ev in post:
            if ts <= review_at:
                continue
            if _norm_purpose(ev.get("purpose")) != "weight-entry":
                continue
            completion_at = ts
            completion_event = ev
            completed_by = _operator(ev)
            completion_source = COMPLETION_SOURCE_POST_REVIEW_WEIGHT
            break

    return CycleBoundaryResult(
        cycle_anchor_at=anchor,
        entry_at=entry_at,
        entry_rack=entry_rack,
        entry_event=entry_event,
        garments_reviewed_at=review_at,
        garments_reviewed_event=review_event,
        completion_at=completion_at,
        completed_by=completed_by,
        completion_event=completion_event,
        completion_source=completion_source,
        effective_status="completed" if completion_at is not None else "pending",
        pending_reason=None,
        via_clean_rack_required=False,
    )
