"""Employer / business entity on payroll worker profiles and schedule shifts."""

from __future__ import annotations

from typing import Any, Mapping

from backend.business_entity import (
    ENTITY_NONE,
    ENTITY_RINSE_EXCLUSIVE,
    ENTITY_SHARED,
    ENTITY_WASHMATE,
    ENTITY_WASHPRO,
    ENTITY_VEEWASH,
    WORKER_ENTITIES,
    default_entity_for_org,
    normalize_shift_entity,
    normalize_worker_entity,
    worker_allows_shift_entity,
)

# Legacy aliases — keep imports stable across codebase
EMPLOYER_AFFILIATION_RINSE = ENTITY_RINSE_EXCLUSIVE
EMPLOYER_AFFILIATION_VEEWASH = ENTITY_WASHPRO  # legacy key; not the VeeWash tenant entity
EMPLOYER_AFFILIATION_BOTH = ENTITY_SHARED
EMPLOYER_AFFILIATION_NONE = ENTITY_NONE
EMPLOYER_AFFILIATION_WASHPRO = ENTITY_WASHPRO
EMPLOYER_AFFILIATION_WASHMATE = ENTITY_WASHMATE
EMPLOYER_AFFILIATION_VEEWASH_ENTITY = ENTITY_VEEWASH

VALID_EMPLOYER_AFFILIATIONS = WORKER_ENTITIES
SHIFT_EMPLOYER_AFFILIATIONS = frozenset({ENTITY_WASHPRO, ENTITY_WASHMATE, ENTITY_VEEWASH, ENTITY_RINSE_EXCLUSIVE})


def _stream_flag(value: Any) -> bool:
    return value is not False and value != 0


def _worker_business_entity(worker: Mapping[str, Any] | None, organization_slug: str | None = None) -> str | None:
    if not worker:
        return None
    explicit = worker.get("business_entity") or worker.get("employer_affiliation")
    if explicit:
        return normalize_worker_entity(explicit, organization_slug=organization_slug)
    return None


def employer_affiliation_from_flags(
    worker: Mapping[str, Any] | None,
    *,
    organization_slug: str | None = None,
) -> str:
    """Derive worker entity from profile flags / explicit business_entity."""
    explicit = _worker_business_entity(worker, organization_slug=organization_slug)
    if explicit:
        return explicit
    if not worker:
        return default_entity_for_org(organization_slug)
    rinse = _stream_flag(worker.get("can_work_rinse"))
    drop_off = _stream_flag(worker.get("can_work_drop_off"))
    both = _stream_flag(worker.get("can_work_both"))
    if not rinse and not drop_off and not both:
        return ENTITY_NONE
    if rinse and drop_off and both:
        return ENTITY_SHARED
    if rinse and not drop_off and not both:
        return ENTITY_RINSE_EXCLUSIVE
    if drop_off and not rinse:
        return default_entity_for_org(organization_slug)
    if rinse and not drop_off:
        return ENTITY_RINSE_EXCLUSIVE
    return default_entity_for_org(organization_slug)


def flags_from_employer_affiliation(affiliation: str) -> dict[str, bool]:
    aff = normalize_worker_entity(affiliation) or default_entity_for_org(None)
    if aff == ENTITY_NONE:
        return {"can_work_rinse": False, "can_work_drop_off": False, "can_work_both": False}
    if aff == ENTITY_RINSE_EXCLUSIVE:
        return {"can_work_rinse": True, "can_work_drop_off": False, "can_work_both": False}
    if aff == ENTITY_SHARED:
        return {"can_work_rinse": True, "can_work_drop_off": True, "can_work_both": True}
    if aff in {ENTITY_WASHPRO, ENTITY_WASHMATE, ENTITY_VEEWASH}:
        return {"can_work_rinse": False, "can_work_drop_off": True, "can_work_both": False}
    return {"can_work_rinse": False, "can_work_drop_off": True, "can_work_both": False}


def normalize_employer_affiliation(raw: Any, *, organization_slug: str | None = None) -> str | None:
    return normalize_worker_entity(raw, organization_slug=organization_slug)


def normalize_shift_employer_affiliation(raw: Any, *, organization_slug: str | None = None) -> str | None:
    return normalize_shift_entity(raw, organization_slug=organization_slug)


def default_shift_employer_affiliation(
    worker: Mapping[str, Any] | None,
    *,
    organization_slug: str | None = None,
) -> str:
    aff = employer_affiliation_from_flags(worker, organization_slug=organization_slug)
    if aff == ENTITY_RINSE_EXCLUSIVE:
        return ENTITY_RINSE_EXCLUSIVE
    if aff == ENTITY_SHARED:
        return default_entity_for_org(organization_slug)
    if aff in SHIFT_EMPLOYER_AFFILIATIONS:
        return aff
    return default_entity_for_org(organization_slug)


def list_employer_affiliation_rows(conn, organization_id: int) -> list[dict[str, Any]]:
    from backend.payroll_schedule import list_schedule_workers_for_grid

    org_slug = _organization_slug(conn, organization_id)
    rows: list[dict[str, Any]] = []
    for worker in list_schedule_workers_for_grid(conn, int(organization_id)):
        aff = employer_affiliation_from_flags(worker, organization_slug=org_slug)
        rows.append(
            {
                "user_id": int(worker.get("user_id") or 0),
                "worker_profile_id": worker.get("worker_profile_id") or worker.get("id"),
                "display_name": worker.get("display_name") or worker.get("worker_name") or "",
                "employer_affiliation": aff,
                "business_entity": aff,
                "can_work_rinse": bool(worker.get("can_work_rinse")),
                "can_work_drop_off": bool(worker.get("can_work_drop_off")),
                "can_work_both": bool(worker.get("can_work_both")),
            }
        )
    rows.sort(key=lambda row: (row.get("display_name") or "").casefold())
    return rows


def save_employer_affiliation(
    conn,
    organization_id: int,
    user_id: int,
    affiliation: str,
    *,
    cascade_shifts: bool = True,
) -> dict[str, Any]:
    from backend.payroll_schedule import get_worker_by_user_id, save_scheduling_profile

    org_slug = _organization_slug(conn, organization_id)
    aff = normalize_employer_affiliation(affiliation, organization_slug=org_slug)
    if not aff:
        raise ValueError(
            "employer_affiliation must be washpro, washmate, veewash, rinse_exclusive, shared, or none"
        )
    flags = flags_from_employer_affiliation(aff)
    save_scheduling_profile(
        conn,
        int(organization_id),
        int(user_id),
        {**flags, "business_entity": aff},
    )
    future_entries_cleared = 0
    # Keep shift tabs in sync when the worker moves to a concrete entity. Otherwise
    # stored veewash/washpro shift tags keep them parked on the home-entity tab.
    if cascade_shifts and aff in SHIFT_EMPLOYER_AFFILIATIONS:
        cursor = conn.cursor()
        try:
            from backend.planned_weekly_schedule import ensure_planned_weekly_schedule_table

            ensure_planned_weekly_schedule_table(cursor)
            cursor.execute(
                """
                UPDATE planned_weekly_schedule_entries
                SET employer_affiliation=%s
                WHERE organization_id=%s AND user_id=%s
                """,
                (aff, int(organization_id), int(user_id)),
            )
        finally:
            cursor.close()
    elif cascade_shifts and aff == ENTITY_NONE:
        # Mapping → None: drop current/future planned participation. Keep past weeks.
        from backend.business_time import business_today
        from backend.planned_weekly_schedule import clear_future_planned_schedule_entries_for_user

        cursor = conn.cursor()
        try:
            future_entries_cleared = clear_future_planned_schedule_entries_for_user(
                cursor,
                int(organization_id),
                int(user_id),
                as_of=business_today(),
            )
        finally:
            cursor.close()
    worker = get_worker_by_user_id(conn, int(organization_id), int(user_id))
    return {
        "user_id": int(user_id),
        "worker_profile_id": worker.get("id"),
        "display_name": worker.get("display_name") or worker.get("worker_name") or "",
        "employer_affiliation": aff,
        "business_entity": aff,
        "future_entries_cleared": int(future_entries_cleared),
        **flags,
    }


def bulk_shift_entity_allowed(
    worker: Mapping[str, Any] | None,
    target_entity: str,
    *,
    organization_slug: str | None = None,
) -> tuple[bool, str | None]:
    worker_entity = employer_affiliation_from_flags(worker, organization_slug=organization_slug)
    shift_entity = normalize_shift_entity(target_entity, organization_slug=organization_slug)
    if not shift_entity:
        return False, "invalid target entity"
    if worker_entity == ENTITY_NONE:
        return False, "worker affiliation is none"
    if worker_allows_shift_entity(worker_entity, shift_entity, organization_slug=organization_slug):
        return True, None
    return False, f"worker entity {worker_entity} cannot be assigned to {shift_entity}"


def _organization_slug(conn, organization_id: int) -> str:
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT slug FROM organizations WHERE id=%s LIMIT 1",
            (int(organization_id),),
        )
        row = cursor.fetchone()
        if isinstance(row, dict) and row.get("slug"):
            return str(row["slug"]).strip().lower()
    finally:
        cursor.close()
    return "washpro"
