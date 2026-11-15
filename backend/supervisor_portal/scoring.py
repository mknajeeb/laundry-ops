"""Target-based score preview.

The formula is not authorized. ``active`` is always false and finalize refuses
to write a snapshot. Components are returned so a supervisor can see the
arithmetic that would be used after management approval.

Proposed discussion weights (not production settings): productivity 70,
quality 25, training 5.
"""

from __future__ import annotations

from typing import Any, Mapping

PROPOSED_WEIGHTS = {"productivity": 0.70, "quality": 0.25, "training": 0.05}
ACTIVATION_ERROR = "scoring_activation_requires_explicit_authorization"


def draft_policy() -> dict[str, Any]:
    return {
        "active": False,
        "weights": dict(PROPOSED_WEIGHTS),
        "above_target_policy": "uncapped",
        "quality_points_per_bag_for_full_penalty": 0.1,
        "auto_approval_threshold": None,
        "status": "draft",
        "note": "Discussion weights only. Not applied to historical or current scores.",
    }


def refuse_activation(body: Mapping[str, Any] | None) -> str | None:
    if not body:
        return None
    if body.get("active") in (True, 1, "1", "true", "yes"):
        return ACTIVATION_ERROR
    return None


def achievement_ratio(actual: float | None, target: float | None, *, cap: bool) -> float | None:
    if actual is None or target is None or float(target) <= 0:
        return None
    ratio = float(actual) / float(target)
    if cap:
        return min(ratio, 1.0)
    return ratio


def quality_component(points: float | None, volume: float | None, penalty_scale: float) -> dict[str, Any]:
    """Normalize issue points by work volume. Unassigned issues contribute nothing."""
    if points is None:
        return {"score": None, "status": "no_weight_version", "points": None, "per_unit": None}
    bags = float(volume or 0)
    if bags <= 0:
        return {
            "score": None,
            "status": "no_volume",
            "points": points,
            "per_unit": None,
        }
    per_unit = points / bags
    scale = float(penalty_scale) if penalty_scale else 0.1
    score = max(0.0, 1.0 - (per_unit / scale))
    return {
        "score": round(score, 4),
        "status": "ready",
        "points": points,
        "per_unit": round(per_unit, 4),
        "volume": bags,
    }


def preview_score(
    *,
    actual: float | None,
    target: float | None,
    measurable: bool,
    quality_points: float | None,
    volume: float | None,
    training_ratio: float | None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return components. ``overall`` stays null until a formula is authorized."""
    chosen = dict(policy or draft_policy())
    if chosen.get("active"):
        # Belt and suspenders: this process never honors an active flag.
        chosen["active"] = False
        chosen["activation_ignored"] = ACTIVATION_ERROR
    cap = str(chosen.get("above_target_policy") or "") == "cap"
    ratio = achievement_ratio(actual, target, cap=cap) if measurable else None
    quality = quality_component(
        quality_points,
        volume,
        float(chosen.get("quality_points_per_bag_for_full_penalty") or 0.1),
    )
    training_score = None if training_ratio is None else max(0.0, min(1.0, float(training_ratio)))
    incomplete = (not measurable) or ratio is None
    weights = chosen.get("weights") or PROPOSED_WEIGHTS
    return {
        "overall": None,
        "status": "incomplete" if incomplete else "inactive",
        "activated": False,
        "reason": (
            "Role has no reliable productivity measurement"
            if not measurable or ratio is None
            else "Scoring formula is not authorized"
        ),
        "components": {
            "productivity": {
                "weight": weights.get("productivity"),
                "actual": actual,
                "target": target,
                "achievement": None if ratio is None else round(ratio, 4),
                "above_target_policy": "cap" if cap else "uncapped",
                "applied": False,
            },
            "quality": {
                "weight": weights.get("quality"),
                "applied": False,
                **quality,
            },
            "training": {
                "weight": weights.get("training"),
                "completion_ratio": training_score,
                "applied": False,
                "included_in_overall": False,
            },
        },
        "policy": {
            "active": False,
            "weights": weights,
            "note": chosen.get("note"),
        },
    }
