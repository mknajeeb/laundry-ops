"""Checklist training assignments.

Operational task checklists stay on the task engine (Track 1 owns assignment
and verification). Training versions keep their own items so an SOP update
cannot overwrite a completed task checklist or a previous training version.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

STATUSES = (
    "assigned",
    "in_progress",
    "awaiting_verification",
    "completed",
    "failed",
)

TRANSITIONS = {
    "assigned": {"in_progress"},
    "in_progress": {"awaiting_verification", "failed"},
    "awaiting_verification": {"completed", "failed"},
    "failed": set(),
    "completed": set(),
}


def normalize_template(body: Mapping[str, Any]) -> dict[str, Any]:
    title = str(body.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required")
    items = []
    for index, raw in enumerate(body.get("items") or []):
        if isinstance(raw, str):
            label = raw.strip()
            required = True
            evidence = False
        elif isinstance(raw, Mapping):
            label = str(raw.get("label") or "").strip()
            required = bool(raw.get("required", True))
            evidence = bool(raw.get("needs_evidence") or raw.get("evidence"))
        else:
            continue
        if not label:
            continue
        items.append(
            {
                "label": label[:255],
                "required": required,
                "needs_evidence": evidence,
                "sort_order": index,
            }
        )
    if not items:
        raise ValueError("Add at least one checklist item")
    return {
        "title": title[:160],
        "role_key": str(body.get("role_key") or "GENERAL").strip().upper() or "GENERAL",
        "category": str(body.get("category") or "general").strip().lower()[:64],
        "instructions": (str(body.get("instructions")).strip()[:4000] if body.get("instructions") else None),
        "practical_required": bool(body.get("practical_required")),
        "items": items,
    }


def checklist_ready(items: Sequence[Mapping[str, Any]], progress: Mapping[Any, Any]) -> bool:
    required = [item for item in items if item.get("required", True)]
    if not required:
        return False
    for item in required:
        marker = progress.get(item.get("id"), progress.get(str(item.get("id"))))
        if isinstance(marker, Mapping):
            done = bool(marker.get("done"))
        else:
            done = bool(marker)
        if not done:
            return False
    return True


def next_status(
    current: str,
    requested: str,
    *,
    checklist_complete: bool,
    practical_required: bool,
    competency_result: str | None,
    actor_is_trainee: bool,
    actor_is_supervisor: bool,
    actor_is_subject: bool = False,
) -> str:
    current = str(current or "assigned")
    requested = str(requested or "").strip()
    if requested not in STATUSES:
        raise ValueError("Unknown training status")
    if requested not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot move training from {current} to {requested}")
    if requested == "awaiting_verification" and not checklist_complete:
        raise ValueError("Required checklist items are still open")
    if requested == "completed":
        if actor_is_subject or not actor_is_supervisor:
            raise ValueError("A trainee cannot verify their own training")
        if not checklist_complete:
            raise ValueError("Required checklist items are still open")
        if practical_required and str(competency_result or "").lower() != "pass":
            raise ValueError("Practical competency is required before completion")
    if requested == "in_progress" and not (actor_is_trainee or actor_is_supervisor):
        raise ValueError("Only the trainee or a supervisor can start training")
    if requested == "failed" and not actor_is_supervisor:
        raise ValueError("Only a supervisor can mark training as failed")
    return requested


def completion_ratio(assignments: Sequence[Mapping[str, Any]]) -> float | None:
    rows = [row for row in assignments or [] if not row.get("voided_at")]
    if not rows:
        return None
    done = sum(1 for row in rows if str(row.get("status")) == "completed")
    return round(done / len(rows), 4)
