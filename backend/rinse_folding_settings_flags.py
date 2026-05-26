"""Feature flags for folding UI and review workflows."""

from __future__ import annotations

import os

from backend.ta_helpers import as_bool


def folding_approvals_enabled() -> bool:
    return as_bool(os.getenv("RINSE_FOLDING_APPROVALS_ENABLED"), default=False)
