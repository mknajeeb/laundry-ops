"""Tenant and business-entity scoping helpers for operational queries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.business_entity import (
    ENTITY_COMBINED,
    assert_same_organization,
    default_entity_for_org,
    entity_scope_payload,
    is_privileged_user,
    normalize_org_slug,
    normalize_shift_entity,
    normalize_worker_entity,
    worker_allows_shift_entity,
)


def require_organization_id(organization_id: Any) -> int:
    oid = int(organization_id or 0)
    if oid <= 0:
        raise ValueError("organization_id required")
    return oid


def scoped_organization_filter(organization_id: int, *, column: str = "organization_id") -> tuple[str, tuple[int, ...]]:
    """Return SQL fragment + params for mandatory org scoping."""
    oid = require_organization_id(organization_id)
    return f"{column} = %s", (oid,)


def assert_record_in_tenant(record: Mapping[str, Any] | None, organization_id: int) -> None:
    if not record:
        raise ValueError("record not found")
    assert_same_organization(record.get("organization_id"), organization_id)


def resolve_entity_scope(
    organization_id: int,
    organization_slug: str | None,
    user_roles: Sequence[str] | None,
) -> dict[str, Any]:
    return entity_scope_payload(
        require_organization_id(organization_id),
        organization_slug,
        user_roles,
    )


def normalize_active_entity_tab(
    tab: str | None,
    *,
    organization_slug: str | None,
    is_privileged: bool = False,
) -> str:
    from backend.business_entity import entities_for_organization

    tab_key = str(tab or "").strip().lower()
    allowed = set(entities_for_organization(organization_slug, is_privileged=is_privileged))
    if tab_key in allowed:
        return tab_key
    return default_entity_for_org(organization_slug)


def bulk_action_entity_guard(
    worker: Mapping[str, Any] | None,
    *,
    source_entity: str | None,
    target_entity: str | None,
    organization_slug: str | None = None,
) -> tuple[bool, str | None]:
    """Validate bulk mutations stay within entity boundaries."""
    from backend.payroll_employer_affiliation import bulk_shift_entity_allowed, employer_affiliation_from_flags

    worker_entity = employer_affiliation_from_flags(worker, organization_slug=organization_slug)
    src = normalize_shift_entity(source_entity, organization_slug=organization_slug)
    dst = normalize_shift_entity(target_entity, organization_slug=organization_slug)
    if worker_entity == "none":
        return False, "worker affiliation is none"
    if dst and not worker_allows_shift_entity(worker_entity, dst, organization_slug=organization_slug):
        return False, f"worker entity {worker_entity} cannot move to {dst}"
    if src and dst and src != dst:
        allowed, reason = bulk_shift_entity_allowed(worker, dst, organization_slug=organization_slug)
        if not allowed:
            return False, reason
    return True, None


def combined_view_is_admin_only(tab: str | None) -> bool:
    return str(tab or "").strip().lower() == ENTITY_COMBINED
