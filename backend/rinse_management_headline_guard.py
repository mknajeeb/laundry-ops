"""Helpers to keep Management published headlines structurally valid."""

from __future__ import annotations

from typing import Any, Mapping


def headline_has_wf_workload_segments(headline: Mapping[str, Any] | None) -> bool:
    """True when headline carries Management WF workload segments (not weights-only)."""
    hl = dict(headline or {})
    segs = dict(hl.get("segments") or {})
    wf = dict(segs.get("wf") or {})
    if not wf:
        # Legacy flat headline still counts if it has total_workload.
        try:
            total = hl.get("total_workload")
            if total is None:
                total = hl.get("active_workload")
            if total is None:
                return False
            int(total)
            return True
        except (TypeError, ValueError):
            return False
    try:
        total = wf.get("total_workload")
        if total is None:
            total = wf.get("active_workload")
        if total is None:
            return False
        int(total)
        return True
    except (TypeError, ValueError):
        return False


def merge_weights_into_headline(
    base: Mapping[str, Any] | None,
    weights: Mapping[str, Any] | None,
    *,
    repair_tag: str | None = None,
) -> dict[str, Any]:
    """Overlay weight totals onto an existing Management headline without wiping segments."""
    out = dict(base or {})
    if weights:
        out["weights"] = dict(weights)
    if repair_tag:
        out["repair"] = repair_tag
    return out
