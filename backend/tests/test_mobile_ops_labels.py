"""Tests for employee-facing Mobile Ops assignment labels."""

from backend.mobile_ops_labels import (
    employee_assignment_label,
    employee_assignment_label_from_segment,
    employee_role_label,
    employee_work_type_label,
)


def test_role_labels():
    assert employee_role_label("Operator", role_code="OPERATOR") == "Wash-Dry"
    assert employee_role_label("Sort", role_code="SORT") == "Sort"
    assert employee_role_label("Sorting", role_code="SORT") == "Sort"
    assert employee_role_label("Folder", role_code="FOLDER") == "Fold"


def test_work_type_labels():
    assert employee_work_type_label("Rinse WF", category_code="RINSE_WF") == "Rinse Wash & Fold"
    assert employee_work_type_label("Rinse HD", category_code="RINSE_HD") == "Rinse Hang Dry"
    assert employee_work_type_label("DHS", category_code="DHS") == "Non-Rinse"
    assert employee_work_type_label("Drop Off", category_code="DROP_OFF") == "Non-Rinse"


def test_assignment_pipe_format():
    assert (
        employee_assignment_label(
            role_name="Operator",
            role_code="OPERATOR",
            category_name="Rinse WF",
            category_code="RINSE_WF",
        )
        == "Wash-Dry | Rinse Wash & Fold"
    )
    assert (
        employee_assignment_label(
            role_name="Sort",
            role_code="SORT",
            category_name="Rinse HD",
            category_code="RINSE_HD",
        )
        == "Sort | Rinse Hang Dry"
    )
    assert (
        employee_assignment_label_from_segment(
            {
                "role_name_snapshot": "Folder",
                "role_code": "FOLDER",
                "category_name_snapshot": "Drop Off",
                "category_code": "DROP_OFF",
            }
        )
        == "Fold | Non-Rinse"
    )
