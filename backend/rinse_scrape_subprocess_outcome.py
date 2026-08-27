"""Classify portal/scrape bash subprocess failures for bounded diagnostics."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

FAILURE_CHROMIUM_CRASH = "chromium_crash"
FAILURE_PLAYWRIGHT_HANG = "playwright_hang"
FAILURE_PAGE_NAVIGATION_HANG = "page_navigation_hang"
FAILURE_PROCESS_EXIT = "process_exit"
FAILURE_HOST_TERMINATION = "host_container_termination"
FAILURE_STALL_NO_PROGRESS = "stall_no_progress"
FAILURE_PHASE_TIMEOUT = "phase_timeout"
FAILURE_PARENT_KILL = "parent_kill"

_SIGSEGV_PATTERNS = (
    re.compile(r"received signal\s+11", re.I),
    re.compile(r"\bsigsegv\b", re.I),
    re.compile(r"segmentation fault", re.I),
    re.compile(r"trace/breakpoint trap", re.I),
)
_PLAYWRIGHT_HANG_PATTERNS = (
    re.compile(r"playwright.*timeout", re.I),
    re.compile(r"waiting for (?:locator|selector|function)", re.I),
    re.compile(r"page\.wait_for", re.I),
    re.compile(r"browser\.close", re.I),
)
_NAV_HANG_PATTERNS = (
    re.compile(r"page\.goto", re.I),
    re.compile(r"navigation timeout", re.I),
    re.compile(r"waiting for navigation", re.I),
    re.compile(r"net::err_", re.I),
    re.compile(r"domcontentloaded", re.I),
)
_HOST_TERM_PATTERNS = (
    re.compile(r"\bkilled\b", re.I),
    re.compile(r"oom", re.I),
    re.compile(r"out of memory", re.I),
    re.compile(r"container.*terminated", re.I),
)


def _tail_text(lines: Sequence[str], *, limit: int = 40) -> str:
    return "\n".join(str(l).strip() for l in (lines or [])[-limit:] if str(l).strip())


def _match_any(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def classify_subprocess_failure(
    *,
    returncode: int,
    timed_out: bool = False,
    stalled: bool = False,
    killed_by_parent: bool = False,
    last_log_lines: Sequence[str] | None = None,
    elapsed_sec: float | None = None,
) -> dict[str, Any]:
    """Map subprocess wait status + log tail to a stable failure_class."""
    tail = _tail_text(last_log_lines or [])
    signal: int | None = None
    if returncode is not None and returncode < 0:
        signal = -int(returncode)

    if timed_out:
        return {
            "failure_class": FAILURE_PHASE_TIMEOUT,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if stalled or returncode == -2:
        if _match_any(_NAV_HANG_PATTERNS, tail):
            failure_class = FAILURE_PAGE_NAVIGATION_HANG
        elif _match_any(_PLAYWRIGHT_HANG_PATTERNS, tail):
            failure_class = FAILURE_PLAYWRIGHT_HANG
        else:
            failure_class = FAILURE_STALL_NO_PROGRESS
        return {
            "failure_class": failure_class,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if signal == 11 or _match_any(_SIGSEGV_PATTERNS, tail):
        return {
            "failure_class": FAILURE_CHROMIUM_CRASH,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if signal in (9, 15) and killed_by_parent:
        return {
            "failure_class": FAILURE_PARENT_KILL,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if signal in (9, 15) or _match_any(_HOST_TERM_PATTERNS, tail):
        return {
            "failure_class": FAILURE_HOST_TERMINATION,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if _match_any(_PLAYWRIGHT_HANG_PATTERNS, tail) and returncode != 0:
        return {
            "failure_class": FAILURE_PLAYWRIGHT_HANG,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    if _match_any(_NAV_HANG_PATTERNS, tail) and returncode != 0:
        return {
            "failure_class": FAILURE_PAGE_NAVIGATION_HANG,
            "returncode": returncode,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "log_tail": tail,
        }

    return {
        "failure_class": FAILURE_PROCESS_EXIT if returncode not in (0, None) else None,
        "returncode": returncode,
        "signal": signal,
        "elapsed_sec": elapsed_sec,
        "log_tail": tail,
    }


def merge_portal_subprocess_outcome(
    detail: Mapping[str, Any] | None,
    outcome: Mapping[str, Any] | None,
    *,
    stage: str = "portal_scrape",
) -> dict[str, Any]:
    merged = dict(detail or {})
    if outcome:
        merged["portal_subprocess_outcome"] = {**dict(outcome), "stage": stage}
    return merged
