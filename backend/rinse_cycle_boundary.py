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
  (with the two documented edge-case exceptions below).
* Garments-reviewed + weight **without** qualifying entry must not complete.
  Result: ``effective_status=pending``, ``pending_reason=ENTRY_NOT_FOUND``,
  ``completion_at=null``.
* Raw scan history stays append-only; duplicate post-review weights complete
  the bag once (earliest qualifying weight).

Edge-case exceptions (narrow)
-----------------------------
1. Same-minute POST: when garments-reviewed and weight-entry share the same
   clock minute (seconds missing/equal/reversed), allow completion only when
   sequence evidence proves weight-entry followed review. Prefer, in order:
   full timestamp with seconds; portal scan-index chronology (lower index =
   later within a scrape); event id when scan_index is unavailable; never
   purpose alone. Source: ``same_minute_post_after_review_sequence``.

2. Pre-STV entry fallback: when no post-anchor configured entry exists, accept
   the latest configured Dirty/Zipvan move-bag at most
   ``PRE_STV_ENTRY_MAX_MINUTES`` before the anchor, only when:
   * no intervening sent-to-vendor / return / prior-cycle completion sits
     between that move and the anchor, and
   * post-anchor garments-reviewed + post-review weight evidence supports the
     same operational cycle.
   Do not treat arbitrary historical Dirty scans as current-cycle entry.

Do not use lifetime first clean-rack, lifetime first weight-entry, old
garments-reviewed, old completion timestamps, or ordinal weight-entry alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_purpose import normalize_scan_purpose

COMPLETION_SOURCE_POST_REVIEW_WEIGHT = "post_garments_reviewed_weight_entry"
COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW = (
    "same_minute_post_after_review_sequence"
)
PENDING_REASON_ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"

# Max age of a pre-anchor configured entry move relative to sent-to-vendor.
# Production evidence (org3 Jul 27–30): one bag at 7 minutes; keep a tight
# ceiling and require same-cycle review+POST + no intervening boundary.
PRE_STV_ENTRY_MAX_MINUTES = 15
PRE_STV_ENTRY_MAX_TOLERANCE = timedelta(minutes=PRE_STV_ENTRY_MAX_MINUTES)


def _norm_purpose(raw: Any) -> str:
    """Normalize portal purposes; strip trailing 'Last Scan' suffixes."""
    p = normalize_scan_purpose(raw)
    for base in (
        "sent-to-vendor",
        "move-bag",
        "garments-reviewed",
        "weight-entry",
        "received-from-vendor",
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
    if p.startswith("received-from-vendor"):
        return "received-from-vendor"
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


def _scan_index_num(ev: Mapping[str, Any]) -> int | None:
    raw = ev.get("scan_index")
    if raw is None or raw == "":
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _event_id_num(ev: Mapping[str, Any]) -> int | None:
    raw = ev.get("id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _same_minute(a: datetime, b: datetime) -> bool:
    return _minute_floor(a) == _minute_floor(b)


def _weight_follows_review(
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
    review_ev: Mapping[str, Any],
    review_ts: datetime,
) -> tuple[bool, str | None]:
    """
    Return (follows, completion_source_override).

    Strict timestamp wins. Same-minute pairs require positive sequence evidence
    that weight-entry followed garments-reviewed — never allow every same-minute
    pair.
    """
    if weight_ts > review_ts:
        return True, None
    if not _same_minute(weight_ts, review_ts):
        return False, None
    if weight_ts < review_ts:
        # Same minute but weight stamped earlier within the minute — only
        # sequence evidence can rehabilitate (portal often truncates seconds).
        pass

    w_idx = _scan_index_num(weight_ev)
    r_idx = _scan_index_num(review_ev)
    # Portal scan_index is reverse-chronological within a scrape (1 = newest).
    # Lower index => later real-world event.
    if w_idx is not None and r_idx is not None and w_idx != r_idx:
        if w_idx < r_idx:
            return True, COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
        return False, None

    w_id = _event_id_num(weight_ev)
    r_id = _event_id_num(review_ev)
    # When scan_index is unavailable, higher event id ≈ later ingestion.
    if w_id is not None and r_id is not None and w_id != r_id:
        if w_id > r_id:
            return True, COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
        return False, None

    # No trustworthy sequence evidence — do not complete on purpose alone.
    return False, None


def _is_return_boundary(purpose: str) -> bool:
    return purpose == "received-from-vendor"


def _has_intervening_prior_cycle_boundary(
    timeline: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
    before_ts: datetime,
) -> bool:
    """True when a return or completed prior cycle sits between entry and STV."""
    review_at: datetime | None = None
    for ev in timeline:
        ts = _event_ts(ev)
        if ts is None or ts <= after_ts or ts >= before_ts:
            continue
        purpose = _norm_purpose(ev.get("purpose"))
        if purpose == "sent-to-vendor" or _is_return_boundary(purpose):
            return True
        if purpose == "garments-reviewed":
            if review_at is None:
                review_at = ts
            continue
        if purpose == "weight-entry" and review_at is not None and ts > review_at:
            return True
    return False


def _post_anchor_has_review_and_post_weight(
    post: Sequence[tuple[datetime, Mapping[str, Any]]],
) -> bool:
    review_at: datetime | None = None
    review_ev: Mapping[str, Any] | None = None
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        review_at = ts
        review_ev = ev
        break
    if review_at is None or review_ev is None:
        return False
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "weight-entry":
            continue
        follows, _src = _weight_follows_review(ev, ts, review_ev, review_at)
        if follows:
            return True
    return False


def _resolve_pre_stv_entry_fallback(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor: datetime,
    rack_keys: set[str],
    post: Sequence[tuple[datetime, Mapping[str, Any]]],
) -> tuple[datetime | None, str | None, Mapping[str, Any] | None]:
    """
    Narrow pre-anchor configured-entry fallback.

    Requires same-cycle post-anchor review + POST evidence and forbids
    intervening prior-cycle boundaries. Max lookback: PRE_STV_ENTRY_MAX_MINUTES.
    """
    if not _post_anchor_has_review_and_post_weight(post):
        return None, None, None

    earliest = anchor - PRE_STV_ENTRY_MAX_TOLERANCE
    best_ts: datetime | None = None
    best_rack: str | None = None
    best_ev: Mapping[str, Any] | None = None
    for ev in timeline:
        if _norm_purpose(ev.get("purpose")) != "move-bag":
            continue
        ts = _event_ts(ev)
        # Strictly before anchor (at-anchor move is not "pre-STV").
        if ts is None or ts >= anchor or ts < earliest:
            continue
        rack = str(ev.get("rack") or "").strip()
        if rack.lower() not in rack_keys:
            continue
        if _has_intervening_prior_cycle_boundary(
            timeline, after_ts=ts, before_ts=anchor
        ):
            continue
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best_rack = rack
            best_ev = ev
    return best_ts, best_rack, best_ev


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
    post.sort(
        key=lambda item: (
            item[0],
            -(_scan_index_num(item[1]) or 0),
            _event_id_num(item[1]) or 0,
        )
    )

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

    if entry_at is None:
        fb_ts, fb_rack, fb_ev = _resolve_pre_stv_entry_fallback(
            timeline, anchor=anchor, rack_keys=rack_keys, post=post
        )
        if fb_ts is not None:
            entry_at = fb_ts
            entry_rack = fb_rack
            entry_event = fb_ev

    # Detect review+weight that would have completed without entry (CUR0 pattern).
    orphan_review_at: datetime | None = None
    orphan_review_ev: Mapping[str, Any] | None = None
    orphan_weight_after_review = False
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        orphan_review_at = ts
        orphan_review_ev = ev
        break
    if orphan_review_at is not None and orphan_review_ev is not None:
        for ts, ev in post:
            if _norm_purpose(ev.get("purpose")) != "weight-entry":
                continue
            follows, _src = _weight_follows_review(
                ev, ts, orphan_review_ev, orphan_review_at
            )
            if follows:
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
    if review_at is not None and review_event is not None:
        for ts, ev in post:
            if _norm_purpose(ev.get("purpose")) != "weight-entry":
                continue
            follows, src_override = _weight_follows_review(
                ev, ts, review_event, review_at
            )
            if not follows:
                continue
            completion_at = ts
            completion_event = ev
            completed_by = _operator(ev)
            completion_source = src_override or COMPLETION_SOURCE_POST_REVIEW_WEIGHT
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
