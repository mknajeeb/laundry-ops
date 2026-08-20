"""Employee-facing Mobile Ops labels for attendance category × role.

Canonical stored values remain Operator / Folder / Sort and Rinse WF / etc.
This module only formats labels for employee surfaces (PIN hub, Change Role,
clock-in / break-resume). Manager reports and Folder Performance keep backend codes.
"""

from __future__ import annotations

from typing import Any, Optional


def employee_role_label(
    role_name: Any = None,
    *,
    role_code: Any = None,
) -> str:
    code = str(role_code or "").strip().upper()
    name = str(role_name or "").strip()
    key = name.lower()
    if code == "OPERATOR" or key in ("operator", "wash-dry", "wash dry", "wash_dry"):
        return "Wash-Dry"
    if code == "SORT" or key in ("sort", "sorting", "sorter"):
        return "Sort"
    if code == "FOLDER" or key in ("folder", "folding", "fold"):
        return "Fold"
    return name or code or ""


def employee_work_type_label(
    category_name: Any = None,
    *,
    category_code: Any = None,
) -> str:
    code = str(category_code or "").strip().upper()
    name = str(category_name or "").strip()
    key = name.lower()
    if code == "RINSE_WF" or "rinse wf" in key or "wash & fold" in key or "wash and fold" in key:
        return "Rinse Wash & Fold"
    if code == "RINSE_HD" or "rinse hd" in key or "hang dry" in key:
        return "Rinse Hang Dry"
    if code in ("DHS", "DROP_OFF") or "dhs" in key or "drop off" in key or "drop-off" in key:
        return "Non-Rinse"
    if not name and not code:
        return ""
    # Unknown active categories: still avoid raw codes when we have a name.
    return name or code.replace("_", " ").title()


def employee_assignment_label(
    *,
    role_name: Any = None,
    role_code: Any = None,
    category_name: Any = None,
    category_code: Any = None,
) -> str:
    role = employee_role_label(role_name, role_code=role_code)
    work = employee_work_type_label(category_name, category_code=category_code)
    if role and work:
        return f"{role} | {work}"
    return role or work or ""


def employee_assignment_label_from_segment(segment: Optional[dict]) -> str:
    seg = segment if isinstance(segment, dict) else {}
    return employee_assignment_label(
        role_name=seg.get("role_name_snapshot") or seg.get("role_name"),
        role_code=seg.get("role_code"),
        category_name=seg.get("category_name_snapshot") or seg.get("category_name"),
        category_code=seg.get("category_code"),
    )
