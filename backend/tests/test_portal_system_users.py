"""Portal system users are not payroll W-2 workers."""

from __future__ import annotations

from backend.portal_system_users import is_portal_system_only_user


def test_rinse_only_is_portal_system_user():
    assert is_portal_system_only_user(["RINSE"])
    assert not is_portal_system_only_user(["RINSE", "OPS"])
    assert not is_portal_system_only_user(["ADMIN"])
    assert not is_portal_system_only_user([])
