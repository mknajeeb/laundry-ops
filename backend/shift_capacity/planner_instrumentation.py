"""Production timing for Shift Capacity Planner simulate requests."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

logger = logging.getLogger("shift_capacity.planner")


class PlannerRequestTiming:
    """Collect phase timestamps (ms from request_received) for one simulate call."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._t0 = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.meta: dict[str, Any] = {}

    def mark(self, phase: str) -> None:
        self.phases[phase] = round((time.perf_counter() - self._t0) * 1000.0, 2)

    def set_meta(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if value is not None:
                self.meta[key] = value

    def finish(self) -> dict[str, Any]:
        self.mark("response_ready")
        total_ms = self.phases.get("response_ready", 0.0)
        out = {
            "request_id": self.request_id,
            "phases_ms": dict(self.phases),
            "total_ms": total_ms,
            **self.meta,
        }
        logger.info(
            "capacity_planner_simulate request_id=%s total_ms=%.2f bag_count=%s "
            "response_bytes=%s phases=%s",
            self.request_id,
            total_ms,
            self.meta.get("bag_count"),
            self.meta.get("response_bytes"),
            self.phases,
        )
        return out


def new_planner_request_id() -> str:
    return uuid4().hex[:12]


@contextmanager
def planner_phase(timing: PlannerRequestTiming | None, name: str):
    if timing is None:
        yield
        return
    timing.mark(f"{name}_start")
    try:
        yield
    finally:
        timing.mark(f"{name}_end")
