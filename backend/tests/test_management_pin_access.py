"""Management PIN access — hub managers or MPA module employees."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.management_pin_access import (
    allows_management_hang_dry_pin,
    allows_management_revenue_pin,
    is_hub_manager,
)


def test_hub_manager_allowed_without_mpa_lookup():
    me = {"user_id": 9, "roles": ["MANAGER"]}
    assert is_hub_manager(me) is True
    with patch("backend.management_pin_access.employee_allows_module") as mock_emp:
        assert allows_management_revenue_pin(MagicMock(), me, org_id=3) is True
        assert allows_management_hang_dry_pin(MagicMock(), me, org_id=3) is True
        mock_emp.assert_not_called()


def test_employee_requires_revenue_cost_mpa():
    me = {"user_id": 42, "roles": ["EMPLOYEE"]}
    cur = MagicMock()
    with patch(
        "backend.management_pin_access.employee_allows_module", return_value=True
    ) as mock_emp:
        assert allows_management_revenue_pin(cur, me, org_id=3) is True
        mock_emp.assert_called_once_with(cur, 3, 42, "revenue_cost")
    with patch(
        "backend.management_pin_access.employee_allows_module", return_value=False
    ):
        assert allows_management_revenue_pin(cur, me, org_id=3) is False


def test_employee_requires_hang_dry_mpa():
    me = {"user_id": 42, "roles": ["EMPLOYEE"]}
    cur = MagicMock()
    with patch(
        "backend.management_pin_access.employee_allows_module", return_value=True
    ) as mock_emp:
        assert allows_management_hang_dry_pin(cur, me, org_id=3) is True
        mock_emp.assert_called_once_with(cur, 3, 42, "hang_dry")
    with patch(
        "backend.management_pin_access.employee_allows_module", return_value=False
    ):
        assert allows_management_hang_dry_pin(cur, me, org_id=3) is False
