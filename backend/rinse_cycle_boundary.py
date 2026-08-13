"""
Current-cycle boundary for Shift Monitor entry/completion.

Non-negotiable invariant
------------------------
A scan from a previous ``sent-to-vendor`` cycle can never determine the
current cycle's entry, completion, or status.

Architectural rules (not an ID-specific patch)
----------------------------------------------
* ``current_cycle_anchor`` = latest valid ``purpose='sent-to-vendor'`` on or
  before the selected ET day cutoff (existing cycle boundary).
* ``first_cycle_weight_entry`` = earliest ``weight-entry`` **strictly after**
  that anchor (never a prior-cycle / lifetime weight).
* Entry candidates = configured-rack ``sent-to-vendor`` or ``move-bag`` in the
  selected current cycle that occur **before** ``first_cycle_weight_entry``
  (including the anchor STV itself when it lands on a configured rack, plus
  pre-anchor configured moves not cut off by a prior completed cycle).
* ``selected_entry`` = latest qualifying candidate before that cutoff.
  STV and move-bag are equal entry purposes — not a fallback hierarchy.
  Default racks: VeeWash Dirty, Rinse Zipvan (org-configurable).
* Configured-rack scans **after** ``first_cycle_weight_entry`` are ignored
  for entry (afternoon / outbound Zipvan, late Dirty, etc.).
* If no current-cycle weight exists yet, select the latest qualifying
  configured entry in the open cycle; bag stays pending until review + POST.
* The first weight-entry is only an entry cutoff; it does not prove
  completion (PRE may be that cutoff).
* Garments-reviewed counts only when it occurs **after** the selected entry.
* Completion = earliest valid ``purpose='weight-entry'`` after that
  post-entry garments-reviewed. Clean rack is **not** required.
* Required completion ordering:
  ``entry_at < garments_reviewed_at < completion_weight_at``
  (same-minute POST sequence exception below).
* Garments-reviewed + weight **without** qualifying entry must not complete.
  Result: ``effective_status=pending``, ``pending_reason=ENTRY_NOT_FOUND``,
  ``completion_at=null``.
* Raw scan history stays append-only; duplicate post-review weights complete
  the bag once (earliest qualifying weight).

Edge-case exception (narrow)
----------------------------
Same-minute POST: when garments-reviewed and weight-entry share the same
clock minute (seconds missing/equal/reversed), allow completion only when
sequence evidence proves weight-entry followed review. Prefer, in order:
full timestamp with seconds; portal scan-index chronology (lower index =
later within a scrape); event id when scan_index is unavailable; never
purpose alone. Source: ``same_minute_post_after_review_sequence``.

Do not use lifetime first clean-rack, lifetime first weight-entry, old
garments-reviewed, old completion timestamps, or ordinal weight-entry alone.
Do not require move-bag after sent-to-vendor, or a separate move-bag when
sent-to-vendor already lands on a configured entry rack before first weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_purpose import normalize_scan_purpose

COMPLETION_SOURCE_POST_REVIEW_WEIGHT = "post_garments_reviewed_weight_entry"
COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW = (
    "same_minute_post_after_review_sequence"
)
PENDING_REASON_ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"

_ENTRY_PURPOSES = frozenset({"sent-to-vendor", "move-bag"})


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
    """Return naive America/New_York wall time for cycle comparisons.

    Rinse scan fields are stored as naive ET wall. Aware / ``Z`` / offset ISO
    values are converted to ET first — never strip the zone and treat UTC digits
    as Eastern wall (that silently shifts bags across the day boundary).
    """
    from datetime import timezone as _tz

    from backend.rinse_folding_et import ET
    from backend.rinse_scan_time import _has_numeric_offset, system_datetime_to_et

    for key in ("scanned_at_parsed", "scanned_at", "timestamp"):
        raw = ev.get(key)
        if isinstance(raw, datetime):
            if raw.tzinfo is not None:
                et = system_datetime_to_et(raw) or raw.astimezone(ET)
                return et.replace(tzinfo=None)
            return raw
        if isinstance(raw, str) and raw.strip():
            s = raw.strip()
            try:
                # Aware ISO (Z or numeric offset) → ET wall naive.
                if s.endswith(("Z", "z")) or _has_numeric_offset(s):
                    aware = datetime.fromisoformat(
                        s.replace("Z", "+00:00").replace("z", "+00:00")
                    )
                    if aware.tzinfo is None:
                        aware = aware.replace(tzinfo=_tz.utc)
                    et = system_datetime_to_et(aware) or aware.astimezone(ET)
                    return et.replace(tzinfo=None)
                # Naive ISO / space datetime → already ET wall.
                return datetime.fromisoformat(s.replace(" ", "T", 1).split(".", 1)[0])
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


def _sort_key(ts: datetime, ev: Mapping[str, Any]) -> tuple:
    """Stable chronology: time, then portal reverse-index, then event id."""
    return (
        ts,
        -(_scan_index_num(ev) or 0),
        _event_id_num(ev) or 0,
    )


def _event_precedes(
    left_ev: Mapping[str, Any],
    left_ts: datetime,
    right_ev: Mapping[str, Any],
    right_ts: datetime,
) -> bool:
    """True when left occurs before right (timestamp, then sequence evidence)."""
    if left_ts < right_ts:
        return True
    if left_ts > right_ts:
        return False
    l_idx = _scan_index_num(left_ev)
    r_idx = _scan_index_num(right_ev)
    # Portal scan_index is reverse-chronological (lower index = later).
    if l_idx is not None and r_idx is not None and l_idx != r_idx:
        return l_idx > r_idx
    l_id = _event_id_num(left_ev)
    r_id = _event_id_num(right_ev)
    if l_id is not None and r_id is not None and l_id != r_id:
        return l_id < r_id
    return False


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


def _latest_prior_completion_before(
    timed: Sequence[tuple[datetime, Mapping[str, Any]]],
    *,
    before_ts: datetime,
) -> datetime | None:
    """Latest post-review weight-entry strictly before ``before_ts`` (prior cycle end)."""
    review_at: datetime | None = None
    best: datetime | None = None
    for ts, ev in timed:
        if ts >= before_ts:
            break
        purpose = _norm_purpose(ev.get("purpose"))
        if purpose == "sent-to-vendor" or _is_return_boundary(purpose):
            review_at = None
            continue
        if purpose == "garments-reviewed":
            review_at = ts
            continue
        if purpose == "weight-entry" and review_at is not None and ts > review_at:
            best = ts
            review_at = None
    return best


@dataclass(frozen=True)
class _EntryCandidate:
    entry_at: datetime
    entry_rack: str
    entry_event: Mapping[str, Any]


@dataclass(frozen=True)
class _ChainFromEntry:
    review_at: datetime
    review_event: Mapping[str, Any]
    completion_at: datetime
    completion_event: Mapping[str, Any]
    completed_by: str | None
    completion_source: str


def _chain_from_entry(
    post: Sequence[tuple[datetime, Mapping[str, Any]]],
    *,
    entry_at: datetime,
) -> _ChainFromEntry | None:
    """Garments-reviewed after entry + qualifying POST weight after review."""
    review_at: datetime | None = None
    review_event: Mapping[str, Any] | None = None
    for ts, ev in post:
        if ts <= entry_at:
            continue
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        review_at = ts
        review_event = ev
        break
    if review_at is None or review_event is None:
        return None
    for ts, ev in post:
        if _norm_purpose(ev.get("purpose")) != "weight-entry":
            continue
        follows, src_override = _weight_follows_review(
            ev, ts, review_event, review_at
        )
        if not follows:
            continue
        return _ChainFromEntry(
            review_at=review_at,
            review_event=review_event,
            completion_at=ts,
            completion_event=ev,
            completed_by=_operator(ev),
            completion_source=src_override or COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
        )
    return None


def _first_weight_in_cycle(
    cycle: Sequence[tuple[datetime, Mapping[str, Any]]],
) -> tuple[datetime, Mapping[str, Any]] | None:
    for ts, ev in cycle:
        if _norm_purpose(ev.get("purpose")) == "weight-entry":
            return ts, ev
    return None


def _collect_entry_candidates(
    timed: Sequence[tuple[datetime, Mapping[str, Any]]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor: datetime,
    cycle_lower: datetime | None,
    next_send: datetime | None,
    first_weight: tuple[datetime, Mapping[str, Any]] | None,
    rack_keys: set[str],
) -> list[_EntryCandidate]:
    """
    Configured-rack sent-to-vendor / move-bag scans before the first
    weight-entry in the current cycle (equal purposes; latest wins).
    """
    out: list[_EntryCandidate] = []
    for ts, ev in timed:
        if cycle_lower is not None and ts <= cycle_lower:
            continue
        if next_send is not None and ts >= next_send:
            continue
        if first_weight is not None:
            w_ts, w_ev = first_weight
            # Must occur before the first weight-entry (cutoff may be PRE).
            if not _event_precedes(ev, ts, w_ev, w_ts):
                continue
        purpose = _norm_purpose(ev.get("purpose"))
        if purpose not in _ENTRY_PURPOSES:
            continue
        rack = str(ev.get("rack") or "").strip()
        if rack.lower() not in rack_keys:
            continue
        if ts < anchor and _has_intervening_prior_cycle_boundary(
            timeline, after_ts=ts, before_ts=anchor
        ):
            continue
        out.append(
            _EntryCandidate(
                entry_at=ts,
                entry_rack=rack,
                entry_event=ev,
            )
        )
    return out


def _select_latest_entry(
    candidates: Sequence[_EntryCandidate],
) -> _EntryCandidate | None:
    if not candidates:
        return None
    best = candidates[0]
    for cand in candidates[1:]:
        if _event_precedes(
            best.entry_event,
            best.entry_at,
            cand.entry_event,
            cand.entry_at,
        ):
            best = cand
        elif not _event_precedes(
            cand.entry_event,
            cand.entry_at,
            best.entry_event,
            best.entry_at,
        ):
            # Tie on chronology evidence — keep the later-listed candidate
            # only when timestamps match and neither precedes; prefer cand
            # when it sorts later by _sort_key.
            if _sort_key(cand.entry_at, cand.entry_event) > _sort_key(
                best.entry_at, best.entry_event
            ):
                best = cand
    return best


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


def current_cycle_event_window(
    timeline: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
    as_of_end: datetime | None = None,
    entry_racks: Iterable[str] | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Inclusive start / exclusive end for scans in the current resolved cycle.

    Start is ``resolve_current_cycle(...).cycle_anchor_at``. End is the next
    ``sent-to-vendor`` after that anchor (exclusive), matching the resolver's
    internal ``next_send`` bound. Open cycles have ``end=None``.

    Callers must not substitute selected-calendar-day bounds for this window —
    cycles may cross ET midnight.
    """
    cycle = resolve_current_cycle(
        timeline,
        selected_date_et=selected_date_et,
        as_of_end=as_of_end,
        entry_racks=entry_racks,
    )
    start = cycle.cycle_anchor_at
    if start is None:
        return None, None
    next_send: datetime | None = None
    for ev in timeline:
        if _norm_purpose(ev.get("purpose")) != "sent-to-vendor":
            continue
        ts = _event_ts(ev)
        if ts is None:
            continue
        if as_of_end is not None and ts > as_of_end:
            continue
        if ts > start and (next_send is None or ts < next_send):
            next_send = ts
    return start, next_send


def manager_completion_belongs_to_cycle(
    correction_at: datetime,
    *,
    cycle_start: datetime | None,
    cycle_end: datetime | None,
) -> bool:
    """True when a manager correction's completion_at is in [anchor, next_stv).

    ``cycle_end`` is exclusive (next sent-to-vendor). Open cycles pass
    ``cycle_end=None``. Without a cycle anchor the correction cannot be
    associated with the selected day's current cycle.

    Shared by completion rebuild and opening-membership exclusion so both use
    one durable cycle-window definition.
    """
    if cycle_start is None:
        return False
    if correction_at < cycle_start:
        return False
    if cycle_end is not None and correction_at >= cycle_end:
        return False
    return True


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

    Cycle membership is anchored by the latest sent-to-vendor.
    ``first_cycle_weight_entry`` is the earliest weight-entry strictly after
    that anchor. Entry is the latest configured-rack ``sent-to-vendor`` or
    ``move-bag`` before that cutoff. Completion requires:

      selected entry → garments-reviewed after entry → weight-entry after review

    ``as_of_end`` (optional) limits which events are visible — used by At Vendor
    live/as-of evaluation without changing the day-cutoff anchor.

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

    timed: list[tuple[datetime, Mapping[str, Any]]] = []
    for ev in timeline:
        ts = _event_ts(ev)
        if ts is None:
            continue
        if as_of_end is not None and ts > as_of_end:
            continue
        timed.append((ts, ev))
    timed.sort(key=lambda item: _sort_key(item[0], item[1]))

    prev_stv: datetime | None = None
    next_send: datetime | None = None
    for ts, ev in timed:
        if _norm_purpose(ev.get("purpose")) != "sent-to-vendor":
            continue
        if ts < anchor and (prev_stv is None or ts > prev_stv):
            prev_stv = ts
        if ts > anchor and (next_send is None or ts < next_send):
            next_send = ts

    # Lower bound for pre-anchor entry candidates: prior STV, else end of a
    # prior completed chain. First-weight cutoff is the earliest weight-entry
    # *strictly after* the current-cycle anchor — never a prior-cycle weight.
    cycle_lower = prev_stv
    if cycle_lower is None:
        cycle_lower = _latest_prior_completion_before(timed, before_ts=anchor)

    post_anchor_cycle = [
        (ts, ev)
        for ts, ev in timed
        if ts > anchor and (next_send is None or ts < next_send)
    ]
    first_weight = _first_weight_in_cycle(post_anchor_cycle)

    candidates = _collect_entry_candidates(
        timed,
        timeline,
        anchor=anchor,
        cycle_lower=cycle_lower,
        next_send=next_send,
        first_weight=first_weight,
        rack_keys=rack_keys,
    )
    selected = _select_latest_entry(candidates)

    # Events visible for review/completion after the selected entry.
    chain_window = [
        (ts, ev)
        for ts, ev in timed
        if (selected is None or ts > selected.entry_at)
        and (next_send is None or ts < next_send)
    ]

    # Detect review+weight that would have completed without entry (CUR0 pattern).
    orphan_review_at: datetime | None = None
    orphan_review_ev: Mapping[str, Any] | None = None
    orphan_weight_after_review = False
    post_anchor = [
        (ts, ev) for ts, ev in timed if ts > anchor and (next_send is None or ts < next_send)
    ]
    for ts, ev in post_anchor:
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        orphan_review_at = ts
        orphan_review_ev = ev
        break
    if orphan_review_at is not None and orphan_review_ev is not None:
        for ts, ev in post_anchor:
            if _norm_purpose(ev.get("purpose")) != "weight-entry":
                continue
            follows, _src = _weight_follows_review(
                ev, ts, orphan_review_ev, orphan_review_at
            )
            if follows:
                orphan_weight_after_review = True
                break

    if selected is None:
        pending_reason = None
        if orphan_review_at is not None:
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

    chain = _chain_from_entry(chain_window, entry_at=selected.entry_at)
    if chain is not None:
        return CycleBoundaryResult(
            cycle_anchor_at=anchor,
            entry_at=selected.entry_at,
            entry_rack=selected.entry_rack,
            entry_event=selected.entry_event,
            garments_reviewed_at=chain.review_at,
            garments_reviewed_event=chain.review_event,
            completion_at=chain.completion_at,
            completed_by=chain.completed_by,
            completion_event=chain.completion_event,
            completion_source=chain.completion_source,
            effective_status="completed",
            pending_reason=None,
            via_clean_rack_required=False,
        )

    # Entry present but no complete downstream chain yet.
    review_at = None
    review_event = None
    for ts, ev in chain_window:
        if ts <= selected.entry_at:
            continue
        if _norm_purpose(ev.get("purpose")) != "garments-reviewed":
            continue
        review_at = ts
        review_event = ev
        break

    return CycleBoundaryResult(
        cycle_anchor_at=anchor,
        entry_at=selected.entry_at,
        entry_rack=selected.entry_rack,
        entry_event=selected.entry_event,
        garments_reviewed_at=review_at,
        garments_reviewed_event=review_event,
        completion_at=None,
        completed_by=None,
        completion_event=None,
        completion_source=None,
        effective_status="pending",
        pending_reason=None,
        via_clean_rack_required=False,
    )
