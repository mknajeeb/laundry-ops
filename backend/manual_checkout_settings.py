"""Washpro-scoped manual checkout setting (checkout queue only — not lifecycle)."""

from __future__ import annotations

from typing import Any, Optional

from backend.ta_helpers import table_exists

KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED = "manual_checkout_accept_completed_without_later_rack"
WASHPRO_SLUG = "washpro"


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in {"0", "false", "off", "no", "disabled"}:
        return False
    if s in {"1", "true", "on", "yes", "enabled"}:
        return True
    return default


def _get_setting(cursor, organization_id: int, key: str) -> Optional[str]:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def organization_slug(cursor, organization_id: int) -> str:
    if not table_exists(cursor, "organizations"):
        return ""
    cursor.execute(
        "SELECT slug FROM organizations WHERE id = %s LIMIT 1",
        (int(organization_id),),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return ""
    return str(row.get("slug") or "").strip().lower()


def is_washpro_organization(cursor, organization_id: int) -> bool:
    return organization_slug(cursor, organization_id) == WASHPRO_SLUG


def get_manual_checkout_accept_completed_without_later_rack(
    cursor,
    organization_id: int,
) -> bool:
    """
    Tenant setting: allow completed/CLEAN bags into manual checkout unless rack moved after CLEAN.

    Explicit DB value wins. When unset: enabled for Washpro only, disabled for all other tenants.
    """
    explicit = _get_setting(cursor, organization_id, KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED)
    if explicit is not None:
        return _truthy(explicit, False)
    return is_washpro_organization(cursor, organization_id)


def set_manual_checkout_accept_completed_without_later_rack(
    cursor,
    organization_id: int,
    enabled: bool,
) -> None:
    _set_setting(
        cursor,
        int(organization_id),
        KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED,
        "1" if enabled else "0",
    )


def washpro_manual_checkout_override_active(
    cursor,
    organization_id: int,
    *,
    is_auto_scrape: bool = False,
) -> bool:
    """
    True when Washpro manual checkout override applies to upload row classification.

    Never active for auto scrape or when tenant setting is off.
    """
    if is_auto_scrape:
        return False
    return get_manual_checkout_accept_completed_without_later_rack(cursor, int(organization_id))
