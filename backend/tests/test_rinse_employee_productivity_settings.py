"""Tests for employee productivity maintenance settings."""

from __future__ import annotations

import os
from unittest.mock import patch

from backend.rinse_employee_productivity_settings import (
    ENV_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY,
    include_hd_in_employee_productivity,
    productivity_scope_label,
)


class TestEmployeeProductivitySettings:
    def test_defaults_to_wf_only(self):
        with patch(
            "backend.rinse_employee_productivity_settings._get_setting",
            return_value=None,
        ):
            assert include_hd_in_employee_productivity(object(), 3) is False

    def test_env_override_true(self):
        with patch.dict(os.environ, {ENV_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY: "true"}):
            assert include_hd_in_employee_productivity(object(), 3) is True

    def test_scope_labels(self):
        assert productivity_scope_label(False) == "WF Only"
        assert productivity_scope_label(True) == "WF + HD"
