"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _disable_live_baseline_unless_marked(request):
    """Live baseline is opt-in per test module via pytestmark enable_live_baseline."""
    marker = request.node.get_closest_marker("enable_live_baseline")
    if marker is not None:
        yield
        return
    with patch(
        "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline",
        return_value={"active": False},
    ):
        yield
