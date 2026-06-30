"""Business entity isolation — WashPro, WashMate, and VeeWash share a platform, not records."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

ENTITY_WASHPRO = "washpro"
ENTITY_WASHMATE = "washmate"
ENTITY_VEEWASH = "veewash"
ENTITY_RINSE_EXCLUSIVE = "rinse_exclusive"
ENTITY_SHARED = "shared"
ENTITY_NONE = "none"
ENTITY_COMBINED = "combined"

ENTITY_LABELS: dict[str, str] = {
    ENTITY_WASHPRO: "WashPro",
    ENTITY_WASHMATE: "WashMate",
    ENTITY_VEEWASH: "VeeWash",
    ENTITY_RINSE_EXCLUSIVE: "Rinse Exclusive",
    ENTITY_SHARED: "Shared",
    ENTITY_NONE: "None",
    ENTITY_COMBINED: "Combined (Admin)",
}

WORKER_ENTITIES = frozenset(
    {
        ENTITY_WASHPRO,
        ENTITY_WASHMATE,
        ENTITY_VEEWASH,
        ENTITY_RINSE_EXCLUSIVE,
        ENTITY_SHARED,
        ENTITY_NONE,
    }
)
SHIFT_ENTITIES = frozenset(
    {
        ENTITY_WASHPRO,
        ENTITY_WASHMATE,
        ENTITY_VEEWASH,
        ENTITY_RINSE_EXCLUSIVE,
    }
)

ORG_SLUG_DEFAULT_ENTITY: dict[str, str] = {
    "washpro": ENTITY_WASHPRO,
    "washmate": ENTITY_WASHMATE,
    "veewash": ENTITY_VEEWASH,
}

PRIVILEGED_ROLES = frozenset({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def normalize_org_slug(raw: Any) -> str:
    return str(raw or "washpro").strip().lower() or "washpro"


def default_entity_for_org(org_slug: Any) -> str:
    return ORG_SLUG_DEFAULT_ENTITY.get(normalize_org_slug(org_slug), ENTITY_WASHPRO)


def normalize_worker_entity(raw: Any, *, organization_slug: str | None = None) -> str | None:
    aff = str(raw or "").strip().lower()
    if aff == "both":
        return ENTITY_SHARED
    if aff in WORKER_ENTITIES:
        return aff
    return None


def normalize_shift_entity(raw: Any, *, organization_slug: str | None = None) -> str | None:
    aff = str(raw or "").strip().lower()
    if aff == "veewash":
        slug = normalize_org_slug(organization_slug)
        return ENTITY_VEEWASH if slug == "veewash" else ENTITY_WASHPRO
    if aff in SHIFT_ENTITIES:
        return aff
    if aff == ENTITY_RINSE_EXCLUSIVE:
        return ENTITY_RINSE_EXCLUSIVE
    return None


def entity_label(entity: str | None) -> str:
    key = str(entity or "").strip().lower()
    return ENTITY_LABELS.get(key, key or "—")


def entities_for_organization(org_slug: Any, *, is_privileged: bool = False) -> list[str]:
    """Entity tabs visible for a tenant login."""
    slug = normalize_org_slug(org_slug)
    if slug == "washmate":
        tabs = [ENTITY_WASHMATE]
    elif slug == "veewash":
        tabs = [ENTITY_VEEWASH]
    else:
        tabs = [ENTITY_WASHPRO, ENTITY_RINSE_EXCLUSIVE]
    if is_privileged:
        tabs = [*tabs, ENTITY_COMBINED]
    return tabs


def worker_matches_entity_tab(
    worker_entity: str | None,
    tab: str,
    *,
    organization_slug: str | None = None,
) -> bool:
    tab_key = str(tab or "").strip().lower()
    entity = normalize_worker_entity(worker_entity, organization_slug=organization_slug)
    if entity is None:
        entity = ENTITY_NONE
    if tab_key == ENTITY_COMBINED:
        return entity != ENTITY_NONE
    if entity == ENTITY_NONE:
        return False
    if entity == ENTITY_SHARED:
        allowed = set(entities_for_organization(organization_slug, is_privileged=False))
        allowed.discard(ENTITY_COMBINED)
        return tab_key in allowed
    return entity == tab_key


def shift_matches_entity_tab(
    shift_entity: str | None,
    tab: str,
    *,
    organization_slug: str | None = None,
) -> bool:
    tab_key = str(tab or "").strip().lower()
    entity = normalize_shift_entity(shift_entity, organization_slug=organization_slug)
    if tab_key == ENTITY_COMBINED:
        return entity is not None
    if not entity:
        return False
    return entity == tab_key


def worker_allows_shift_entity(
    worker_entity: str | None,
    shift_entity: str | None,
    *,
    organization_slug: str | None = None,
) -> bool:
    worker = normalize_worker_entity(worker_entity, organization_slug=organization_slug) or ENTITY_NONE
    shift = normalize_shift_entity(shift_entity, organization_slug=organization_slug)
    if worker == ENTITY_NONE or not shift:
        return False
    if worker == ENTITY_SHARED:
        return True
    return worker == shift


def assert_same_organization(record_org_id: Any, tenant_org_id: int) -> None:
    if int(record_org_id or 0) != int(tenant_org_id):
        raise ValueError("cross-organization access denied")


def is_privileged_user(user_roles: Sequence[str] | None) -> bool:
    roles = {str(r).upper() for r in (user_roles or [])}
    return bool(roles & PRIVILEGED_ROLES)


def ensure_business_entity_column(cursor) -> None:
    """Add payroll_worker_profiles.business_entity when missing (mirrors business_entity_v1.sql)."""
    from backend.ta_helpers import table_has_column

    if table_has_column(cursor, "payroll_worker_profiles", "business_entity"):
        return
    cursor.execute(
        """
        ALTER TABLE payroll_worker_profiles
        ADD COLUMN business_entity VARCHAR(32) NULL DEFAULT NULL AFTER can_work_both
        """
    )


def entity_scope_payload(
    organization_id: int,
    organization_slug: str | None,
    user_roles: Sequence[str] | None,
) -> dict[str, Any]:
    slug = normalize_org_slug(organization_slug)
    privileged = is_privileged_user(user_roles)
    tabs = entities_for_organization(slug, is_privileged=privileged)
    return {
        "organization_id": int(organization_id),
        "organization_slug": slug,
        "default_entity": default_entity_for_org(slug),
        "entity_tabs": tabs,
        "active_entity_hint": default_entity_for_org(slug),
        "combined_is_admin_view": privileged,
    }
