"""Management Hub helpers for org-scoped WF ops maintenance (read + mutation gate).

Single source of truth: ``system_settings.wf_ops_maintenance`` via
``backend.wf_ops_reset_epoch``. No second table or cached authority.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify

from backend.wf_ops_reset_epoch import WF_OPS_MAINTENANCE_KEY, get_wf_ops_maintenance


def wf_ops_maintenance_status(cursor, organization_id: int) -> dict[str, Any]:
    org = int(organization_id)
    on = bool(get_wf_ops_maintenance(cursor, org))
    return {
        "organization_id": org,
        "settings_key": WF_OPS_MAINTENANCE_KEY,
        "maintenance_on": on,
    }


def refuse_wf_mutation_if_maintenance(cursor, organization_id: int):
    """Return (jsonify_body, http_status) when WF mutations must be blocked."""
    org = int(organization_id)
    if not get_wf_ops_maintenance(cursor, org):
        return None
    return (
        jsonify(
            {
                "ok": False,
                "error": "wf_ops_maintenance_active",
                "maintenance_on": True,
                "message": (
                    "Wash & Fold maintenance is in progress. "
                    "Wash & Fold operational mutations are temporarily disabled. "
                    "Hang Dry is unaffected."
                ),
            }
        ),
        503,
    )
