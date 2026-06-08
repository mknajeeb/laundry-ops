"""Per-tenant feature flags stored in system_settings (tenant_feature_flags_json)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.ta_helpers import table_exists

KEY_FEATURE_FLAGS_JSON = "tenant_feature_flags_json"

DEFAULT_FLAGS: dict[str, bool] = {
    "enable_manual_upload": True,
    "enable_checkout": True,
    "enable_lifecycle_dashboard": False,
    "enable_ready_for_vendor_scrape": False,
    "enable_shift_user_performance": False,
}


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"0", "false", "off", "no", "disabled"}:
        return False
    if s in {"1", "true", "on", "yes", "enabled"}:
        return True
    return default


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    v = row.get("svalue") if isinstance(row, dict) else row[0]
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def get_tenant_feature_flags(cursor, organization_id: int) -> dict[str, bool]:
    out = dict(DEFAULT_FLAGS)
    org = int(organization_id)
    if table_exists(cursor, "organizations"):
        cursor.execute(
            "SELECT slug FROM organizations WHERE id=%s LIMIT 1",
            (org,),
        )
        row = cursor.fetchone()
        slug = ""
        if isinstance(row, dict):
            slug = str(row.get("slug") or "").strip().lower()
        elif row:
            slug = str(row[0] or "").strip().lower()
        if "veewash" in slug:
            out["enable_ready_for_vendor_scrape"] = True
    raw = _get_setting(cursor, organization_id, KEY_FEATURE_FLAGS_JSON)
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, dict):
        return out
    for k, v in parsed.items():
        if k in out:
            out[k] = _truthy(v, out[k])
    return out


def put_tenant_feature_flags(cursor, organization_id: int, payload: Mapping[str, Any]) -> dict[str, bool]:
    current = get_tenant_feature_flags(cursor, organization_id)
    for k, v in payload.items():
        if k in current:
            current[k] = _truthy(v, current[k])
    _set_setting(cursor, organization_id, KEY_FEATURE_FLAGS_JSON, json.dumps(current))
    return current


def is_feature_enabled(cursor, organization_id: int, flag_key: str, *, default: bool | None = None) -> bool:
    flags = get_tenant_feature_flags(cursor, organization_id)
    if flag_key in flags:
        return flags[flag_key]
    if default is not None:
        return default
    return False
