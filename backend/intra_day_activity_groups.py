"""Canonical Intra-Day Activity Groups.

These payloads reuse the existing task codes. Applying them inserts or updates
the three groups. Nothing in this module runs on import, and it does not write
to a database until ``apply_intra_day_activity_groups`` is called.
"""

from __future__ import annotations

from typing import Any, Mapping

WASHER_GROUP_CODE = "washer_cleaning"
FLOOR_GROUP_CODE = "floor_sweeping"
DRYER_GROUP_CODE = "dryer_lint"

WASHER_ROLE = "agroup_washer_cleaning"
FLOOR_ROLE = "agroup_floor_sweeping"
DRYER_ROLE = "agroup_dryer_lint"
LEGACY_COMBINED_ROLE = "agroup_floor_washer"

# Existing catalog codes. Do not create replacements for these.
WASHER_RESIDUE_CODE = "custom_check_washer_residue"
WASHER_WIPE_CODE = "washer_cleaning"
FLOOR_SWEEP_CODE = "floor_cleaning"
DRYER_LINT_CODE = "lint_cleaning"

ROUTINE_STANDALONE_CODES = frozenset(
    {
        WASHER_RESIDUE_CODE,
        WASHER_WIPE_CODE,
        FLOOR_SWEEP_CODE,
        DRYER_LINT_CODE,
    }
)

COVERED_BY_GROUP = {
    WASHER_RESIDUE_CODE: WASHER_ROLE,
    WASHER_WIPE_CODE: WASHER_ROLE,
    FLOOR_SWEEP_CODE: FLOOR_ROLE,
    DRYER_LINT_CODE: DRYER_ROLE,
}


def intra_day_activity_group_payloads() -> list[dict[str, Any]]:
    return [
        {
            "code": WASHER_GROUP_CODE,
            "name": "Washer Cleaning",
            "name_es": "Limpieza de lavadoras",
            "category_code": "intra_day",
            "display_order": 10,
            "active": True,
            "verification_inherits": True,
            "require_checklist_before_completion": True,
            "instructions": (
                "Shared washer activity. Check residue, then wipe the machines. "
                "The assignment has one checklist. Each person keeps their own timer."
            ),
            "instructions_es": (
                "Actividad compartida de lavadoras. Revisa el residuo y luego limpia las máquinas. "
                "La asignación tiene una lista. Cada persona conserva su propio tiempo."
            ),
            "items": [
                {
                    "task_code": WASHER_RESIDUE_CODE,
                    "section_label": "Machines",
                    "section_label_es": "Máquinas",
                    "task_name_es": "Revisar residuo de las lavadoras",
                    "section_order": 10,
                    "display_order": 10,
                    "required": True,
                    "active": True,
                    "responsibility_mode": "team",
                    "responsibility_user_ids": [],
                    "instructions": (
                        "Look inside each washer for leftover soap, lint, or debris "
                        "before the next load."
                    ),
                    "instructions_es": (
                        "Mira dentro de cada lavadora y busca jabón, pelusa o residuos "
                        "antes de la siguiente carga."
                    ),
                },
                {
                    "task_code": WASHER_WIPE_CODE,
                    "section_label": "Machines",
                    "section_label_es": "Máquinas",
                    "task_name_es": "Limpiar las lavadoras",
                    "section_order": 10,
                    "display_order": 20,
                    "required": True,
                    "active": True,
                    "responsibility_mode": "team",
                    "responsibility_user_ids": [],
                    "instructions": "Wipe washer doors, gaskets, tops, and detergent compartments.",
                    "instructions_es": "Limpia las puertas, los empaques, las tapas y los compartimentos de detergente.",
                },
            ],
        },
        {
            "code": FLOOR_GROUP_CODE,
            "name": "Floor Sweeping",
            "name_es": "Barrido del piso",
            "category_code": "intra_day",
            "display_order": 20,
            "active": True,
            "verification_inherits": True,
            "require_checklist_before_completion": True,
            "instructions": (
                "Shared floor activity. Sweep the production floor once for the assignment. "
                "Each person keeps their own timer."
            ),
            "instructions_es": (
                "Actividad compartida del piso. Barre el piso de producción una vez para la asignación. "
                "Cada persona conserva su propio tiempo."
            ),
            "items": [
                {
                    "task_code": FLOOR_SWEEP_CODE,
                    "section_label": "Floor Cleaning",
                    "section_label_es": "Limpieza del piso",
                    "task_name_es": "Barrido del piso",
                    "section_order": 10,
                    "display_order": 10,
                    "required": True,
                    "active": True,
                    "responsibility_mode": "team",
                    "responsibility_user_ids": [],
                    "instructions": (
                        "Sweep the production floor, including corners and the area around the machines."
                    ),
                    "instructions_es": (
                        "Barre el piso de producción, incluidas las esquinas y el área alrededor de las máquinas."
                    ),
                },
            ],
        },
        {
            "code": DRYER_GROUP_CODE,
            "name": "Dryer Lint Cleaning",
            "name_es": "Limpieza de pelusa de secadoras",
            "category_code": "intra_day",
            "display_order": 30,
            "active": True,
            "verification_inherits": True,
            "require_checklist_before_completion": True,
            "instructions": (
                "Shared dryer activity. One checklist for the assignment, however many people "
                "are assigned. Each person keeps their own timer."
            ),
            "instructions_es": (
                "Actividad compartida de secadoras. Una lista para la asignación, sin importar cuántas "
                "personas estén asignadas. Cada persona conserva su propio tiempo."
            ),
            "items": [
                {
                    "task_code": DRYER_LINT_CODE,
                    "section_label": "Dryer Cleaning",
                    "section_label_es": "Limpieza de secadoras",
                    "task_name_es": "Limpiar pelusa y empaques",
                    "section_order": 10,
                    "display_order": 10,
                    "required": True,
                    "active": True,
                    "responsibility_mode": "team",
                    "responsibility_user_ids": [],
                    "instructions": (
                        "Clean lint from the dryer lint screens and wipe the door gaskets. "
                        "Do this once for the shared assignment."
                    ),
                    "instructions_es": (
                        "Quita la pelusa de los filtros y limpia los empaques de la puerta. "
                        "Hazlo una vez para la asignación compartida."
                    ),
                },
            ],
        },
    ]


def routine_groups_active(catalog: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(
        bool((catalog.get(code) or {}).get("active", False))
        for code in (WASHER_ROLE, FLOOR_ROLE, DRYER_ROLE)
    )


def competing_new_assignment_error(
    role: str,
    catalog: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Block a new standalone routine assignment once its Activity Group is active.

    Existing rows stay editable. The check runs only for a new role choice.
    """
    code = str(role or "").strip()
    info = catalog.get(code) or {}
    if code == LEGACY_COMBINED_ROLE and routine_groups_active(catalog):
        name = str(info.get("name") or "Floor & Washer")
        return (
            f"{name} stays on the schedule for assignments already saved. "
            "New routine cleaning uses Washer Cleaning, Floor Sweeping, and Dryer Lint Cleaning."
        )
    group_code = COVERED_BY_GROUP.get(code)
    if not group_code:
        return None
    group = catalog.get(group_code) or {}
    if not group.get("active", False):
        return None
    task_name = str(info.get("name") or code)
    group_name = str(group.get("name") or group_code)
    return (
        f"{task_name} stays available for assignments already on the schedule. "
        f"New routine cleaning uses the {group_name} activity group."
    )


def apply_intra_day_activity_groups(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Insert or update the three groups. Reuses task codes. Does not delete history."""
    from backend.task_activity_groups import get_activity_group, upsert_activity_group

    saved: list[dict[str, Any]] = []
    for payload in intra_day_activity_group_payloads():
        existing = get_activity_group(
            cursor,
            int(organization_id),
            role_code=str(payload["code"]),
            include_inactive=True,
        )
        group_id = int(existing["id"]) if existing and existing.get("id") is not None else None
        saved.append(
            upsert_activity_group(
                cursor,
                int(organization_id),
                payload,
                group_id=group_id,
            )
        )
    return saved
