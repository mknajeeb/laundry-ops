"""
Settled bulk-only POST projection + Employee Productivity gate.

Does NOT change rinse_current_cycle_weight event selection.
Applies only after the shared current-cycle map is built:

  settled_bulk_only → keep PRE, set POST = final portal WF lbs (usually 0)

Raw scan-event weights are never rewritten.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, MutableMapping, Sequence

from backend.rinse_bulk_workitems import (
    bag_bulk_review_cleared,
    load_bag_bulk_lines,
    load_bulk_resolutions,
)
from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

PORTAL_ZERO_EPS = 0.051
PROD_EXCLUSION_SETTLED_BULK_ONLY = "settled_bulk_only"

_MANUAL_POST_STATUSES = frozenset({"MANUAL_CORRECTION"})


def _parse_weight(raw: Any) -> float | None:
    return normalize_scan_weight_lbs(raw)


def _norm_bag(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def is_portal_wf_zero(lbs: float | None) -> bool:
    if lbs is None:
        return False
    return abs(float(lbs)) < PORTAL_ZERO_EPS


def final_portal_wf_lbs_from_observations(
    observations: Sequence[Mapping[str, Any]],
) -> float | None:
    """
    Latest canonical portal WF pounds.

    Prefer wf_lbs_num when present. Settled zero often arrives as
    wf_lbs_num IS NULL with weight_num = 0.
    """
    if not observations:
        return None
    latest = observations[-1]
    wf = _parse_weight(latest.get("wf_lbs_num"))
    if wf is not None:
        return wf
    return _parse_weight(latest.get("weight_num"))


def trailing_portal_zero_count(observations: Sequence[Mapping[str, Any]]) -> int:
    """Count newest consecutive portal-zero observations."""
    n = 0
    for obs in reversed(list(observations or [])):
        wf = _parse_weight(obs.get("wf_lbs_num"))
        if wf is None:
            wf = _parse_weight(obs.get("weight_num"))
        if is_portal_wf_zero(wf):
            n += 1
            continue
        break
    return n


def is_manual_correction_protected(weight_info: Mapping[str, Any] | None) -> bool:
    info = weight_info or {}
    status = str(info.get("post_resolution_status") or "").strip().upper()
    if status in _MANUAL_POST_STATUSES:
        return True
    if info.get("corrected_post_weight_lbs") is not None:
        return True
    if info.get("corrected_pre_weight_lbs") is not None:
        return True
    return False


def chargeable_bulk_qty(lines: Sequence[Mapping[str, Any]] | None) -> int:
    return sum(max(0, int(x.get("quantity") or 0)) for x in (lines or []))


def cycle_enough_for_settled_bulk_only(weight_info: Mapping[str, Any] | None) -> bool:
    """
    Temporary-zero protection: do not activate on a bare early portal zero.

    Require current-cycle POST evidence and/or garments-reviewed, or an already
    confirmed/equal POST resolution (without treating MANUAL as activation).
    """
    info = weight_info or {}
    if info.get("post_weight_event_exists"):
        return True
    if info.get("garments_reviewed_at"):
        return True
    status = str(info.get("post_resolution_status") or "").strip().upper()
    if status in {"CONFIRMED", "EQUAL_VALUES_CONFIRMED", "EQUAL_CONFIRMED"}:
        return True
    # Multiple trailing zeros after positive mid-cycle is additional stability.
    if int(info.get("bulk_only_trailing_zero_obs") or 0) >= 2 and info.get(
        "pre_weight_lbs"
    ) is not None:
        return True
    return False


def is_settled_bulk_only(
    *,
    final_portal_wf: float | None,
    lines: Sequence[Mapping[str, Any]] | None,
    resolution: Mapping[str, Any] | None,
    weight_info: Mapping[str, Any] | None,
) -> bool:
    """
    Full overlay eligibility.

    post_weight_valid_for_standard_weight_revenue is treated as the *final*
    pound-line signal via final_portal_wf == 0 (sticky early POST=PRE must not
    block the overlay when portal has settled at 0).
    """
    if not is_portal_wf_zero(final_portal_wf):
        return False
    # Mixed / positive final WF pounds
    if final_portal_wf is not None and float(final_portal_wf) > PORTAL_ZERO_EPS:
        return False
    qty = chargeable_bulk_qty(lines)
    if qty <= 0:
        return False
    if not bag_bulk_review_cleared(resolution, list(lines or [])):
        return False
    if is_manual_correction_protected(weight_info):
        return False
    if not cycle_enough_for_settled_bulk_only(weight_info):
        return False
    return True


def apply_settled_bulk_only_post_overlay(
    weight_info: Mapping[str, Any],
    *,
    final_portal_wf: float,
) -> dict[str, Any]:
    """
    Keep PRE; set canonical POST to final portal WF lbs.

    Does not mutate raw evidence fields that describe scan events; only the
    canonical display/persist POST values and revenue validity.
    """
    out = dict(weight_info)
    post = float(final_portal_wf)
    # Preserve raw/detected event lbs for Evidence Details when present.
    if out.get("detected_post_weight_lbs") is None and out.get("post_weight_lbs") is not None:
        out["detected_post_weight_lbs"] = out.get("post_weight_lbs")
    if out.get("raw_post_weight_lbs") is None:
        out["raw_post_weight_lbs"] = out.get("post_weight_lbs")
    out["pre_weight_lbs"] = out.get("pre_weight_lbs")  # unchanged
    out["post_weight_lbs"] = post
    out["post_weight_value"] = post
    out["post_weight_event_exists"] = True
    out["post_weight_valid_for_standard_weight_revenue"] = False
    out["authoritative_post_weight_lbs"] = post
    out["settled_bulk_only"] = True
    out["settled_bulk_only_post_source"] = "final_portal_wf_lbs"
    out["weight_entry_count"] = max(int(out.get("weight_entry_count") or 0), 2)
    # Annotate resolution without claiming MANUAL.
    if str(out.get("post_resolution_status") or "").upper() != "MANUAL_CORRECTION":
        out["post_resolution_status"] = out.get("post_resolution_status") or "CONFIRMED"
        out["resolution_reason"] = "SETTLED_BULK_ONLY_FINAL_PORTAL_POST"
    return out


def load_latest_portal_observations(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    limit_per_bag: int = 12,
) -> dict[str, list[dict[str, Any]]]:
    from backend.ta_helpers import table_exists

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if not ids or not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return out
    placeholders = ",".join(["%s"] * len(ids))
    # Fetch a window of recent rows, then keep last N per bag in chronological order.
    cursor.execute(
        f"""
        SELECT bag_id, observed_at, weight_num, wf_lbs_num, portal_status
        FROM rinse_cleaner_ticket_presence_run_rows
        WHERE organization_id = %s
          AND bag_id IN ({placeholders})
        ORDER BY observed_at DESC, id DESC
        """,
        (int(organization_id), *ids),
    )
    counts: dict[str, int] = {b: 0 for b in ids}
    tmp: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    for row in cursor.fetchall() or []:
        bid = _norm_bag(row.get("bag_id"))
        if bid not in tmp:
            continue
        if counts[bid] >= int(limit_per_bag):
            continue
        tmp[bid].append(dict(row))
        counts[bid] += 1
    for bid, rows in tmp.items():
        out[bid] = list(reversed(rows))
    return out


def apply_settled_bulk_only_to_weight_map(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    weight_map: MutableMapping[str, dict[str, Any]],
    *,
    selected_date_et: date,
) -> dict[str, dict[str, Any]]:
    """Mutate/return weight_map with settled bulk-only POST overlay applied."""
    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    if not ids:
        return dict(weight_map)

    lines_by = load_bag_bulk_lines(cursor, organization_id, selected_date_et, ids)
    res_by = load_bulk_resolutions(cursor, organization_id, selected_date_et, ids)
    obs_by = load_latest_portal_observations(cursor, organization_id, ids)

    for bid in ids:
        info = dict(weight_map.get(bid) or {})
        obs = obs_by.get(bid) or []
        trailing = trailing_portal_zero_count(obs)
        info["bulk_only_trailing_zero_obs"] = trailing
        final_wf = final_portal_wf_lbs_from_observations(obs)
        lines = lines_by.get(bid) or []
        resolution = res_by.get(bid)
        if not is_settled_bulk_only(
            final_portal_wf=final_wf,
            lines=lines,
            resolution=resolution,
            weight_info=info,
        ):
            info["settled_bulk_only"] = False
            weight_map[bid] = info
            continue
        assert final_wf is not None
        weight_map[bid] = apply_settled_bulk_only_post_overlay(info, final_portal_wf=final_wf)
    return dict(weight_map)


def row_is_settled_bulk_only_for_productivity(row: Mapping[str, Any] | None) -> bool:
    """Durable EP gate from projected day-bag / productivity row fields."""
    if not row:
        return False
    if bool(row.get("settled_bulk_only")):
        return True
    reason = str(row.get("productivity_exclusion_reason") or "").strip()
    if reason == PROD_EXCLUSION_SETTLED_BULK_ONLY:
        return True
    snap = row.get("bag_snapshot")
    if isinstance(snap, Mapping) and bool(snap.get("settled_bulk_only")):
        return True
    if isinstance(snap, str) and "settled_bulk_only" in snap:
        try:
            import json

            parsed = json.loads(snap)
            if isinstance(parsed, Mapping) and bool(parsed.get("settled_bulk_only")):
                return True
        except Exception:
            pass
    return False


def project_productivity_override_for_settled_bulk_only(
    base: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Force WF productivity pounds to 0 and keep an exclusion reason so a later
    eligibility flip cannot credit physical PRE.
    """
    out = dict(base)
    out["productivity_weight_lbs"] = 0.0
    out["productivity_credit_eligible"] = 0
    out["productivity_exclusion_reason"] = PROD_EXCLUSION_SETTLED_BULK_ONLY
    out["settled_bulk_only"] = True
    return out
