"""Tenant-scoped configurable folding exception rules (system_settings)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.ta_helpers import table_exists

KEY_EXCEPTION_RULES_JSON = "rinse_folding_exception_rules_json"

DEFAULT_MIN_DURATION_MINUTES = 10
DEFAULT_MAX_DURATION_MINUTES = 240  # UI default; use 0 to disable max check


@dataclass(frozen=True)
class FoldingExceptionRules:
    min_duration_minutes: int
    max_duration_minutes: int
    rule_multiple_folding_scans: bool
    rule_missing_clean: bool
    rule_missing_folding: bool
    rule_clean_before_folding: bool
    multiple_clean_scans_as_exception: bool

    @property
    def min_duration_seconds(self) -> int:
        return max(0, int(self.min_duration_minutes)) * 60

    @property
    def max_duration_seconds(self) -> int | None:
        m = int(self.max_duration_minutes)
        if m <= 0:
            return None
        return m * 60


def default_exception_rules_dict() -> dict[str, Any]:
    return {
        "min_duration_minutes": DEFAULT_MIN_DURATION_MINUTES,
        "max_duration_minutes": DEFAULT_MAX_DURATION_MINUTES,
        "rule_multiple_folding_scans": True,
        "rule_missing_clean": True,
        "rule_missing_folding": True,
        "rule_clean_before_folding": True,
        "multiple_clean_scans_as_exception": False,
        "multiple_clean_scans_help": (
            "When off (default), multiple CLEAN scans after folding stay CALCULATED "
            "with warning MULTIPLE_CLEAN_SCANS. When on, they become EXCEPTION."
        ),
        "max_duration_help": "Set to 0 to disable maximum duration checks.",
    }


def _bool_val(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _int_val(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def parse_exception_rules_payload(data: dict[str, Any] | None) -> FoldingExceptionRules:
    base = default_exception_rules_dict()
    src = {**base, **(data or {})}
    return FoldingExceptionRules(
        min_duration_minutes=max(0, _int_val(src.get("min_duration_minutes"), DEFAULT_MIN_DURATION_MINUTES)),
        max_duration_minutes=_int_val(src.get("max_duration_minutes"), DEFAULT_MAX_DURATION_MINUTES),
        rule_multiple_folding_scans=_bool_val(src.get("rule_multiple_folding_scans"), True),
        rule_missing_clean=_bool_val(src.get("rule_missing_clean"), True),
        rule_missing_folding=_bool_val(src.get("rule_missing_folding"), True),
        rule_clean_before_folding=_bool_val(src.get("rule_clean_before_folding"), True),
        multiple_clean_scans_as_exception=_bool_val(
            src.get("multiple_clean_scans_as_exception"), False
        ),
    )


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


def get_folding_exception_rules(cursor, organization_id: int) -> dict[str, Any]:
    raw = _get_setting(cursor, int(organization_id), KEY_EXCEPTION_RULES_JSON)
    if not raw or not str(raw).strip():
        return default_exception_rules_dict()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return default_exception_rules_dict()
    except json.JSONDecodeError:
        return default_exception_rules_dict()
    out = default_exception_rules_dict()
    out.update({k: parsed[k] for k in out if k in parsed})
    for k, v in parsed.items():
        if k not in out and not k.endswith("_help"):
            out[k] = v
    return out


def get_folding_exception_rules_typed(
    cursor, organization_id: int
) -> FoldingExceptionRules:
    return parse_exception_rules_payload(get_folding_exception_rules(cursor, organization_id))


def put_folding_exception_rules(
    cursor, organization_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    current = get_folding_exception_rules(cursor, organization_id)
    merged = {**current, **(payload or {})}
    rules = parse_exception_rules_payload(merged)
    stored = default_exception_rules_dict()
    stored.update(
        {
            "min_duration_minutes": rules.min_duration_minutes,
            "max_duration_minutes": rules.max_duration_minutes,
            "rule_multiple_folding_scans": rules.rule_multiple_folding_scans,
            "rule_missing_clean": rules.rule_missing_clean,
            "rule_missing_folding": rules.rule_missing_folding,
            "rule_clean_before_folding": rules.rule_clean_before_folding,
            "multiple_clean_scans_as_exception": rules.multiple_clean_scans_as_exception,
        }
    )
    _set_setting(cursor, int(organization_id), KEY_EXCEPTION_RULES_JSON, json.dumps(stored))
    return get_folding_exception_rules(cursor, organization_id)
