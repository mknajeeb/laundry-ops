"""
Process-level memoization for schema ensure / migration guards.

Scrape hot paths historically re-ran CREATE TABLE IF NOT EXISTS and
information_schema.COLUMNS checks per bag/cycle. Schema is stable for the
life of a process; run the real ensure once, then skip.

Tests may call reset_schema_ensure_cache() between cases.
"""

from __future__ import annotations

from typing import Callable

_ensured_keys: set[str] = set()
# Optional counters for before/after measurement in tests / diagnostics.
_call_counts: dict[str, int] = {}
_skip_counts: dict[str, int] = {}
_table_exists_cache: dict[str, bool] = {}


def reset_schema_ensure_cache() -> None:
    _ensured_keys.clear()
    _call_counts.clear()
    _skip_counts.clear()
    _table_exists_cache.clear()


def schema_ensure_stats() -> dict[str, dict[str, int]]:
    return {
        "calls": dict(_call_counts),
        "skips": dict(_skip_counts),
        "ensured": {k: 1 for k in sorted(_ensured_keys)},
        "table_exists_cached": {k: (1 if v else 0) for k, v in sorted(_table_exists_cache.items())},
    }


def cached_table_exists(cursor, table_name: str, *, probe) -> bool:
    """
    Memoize table-existence probes for the process lifetime.

    `probe` is typically backend.app.table_exists / ta_helpers.table_exists.
    Negative results are also cached so we do not re-hit SHOW TABLES / information_schema
    every bag; ensure_* paths still create missing tables on first ensure.
    """
    key = str(table_name)
    if key in _table_exists_cache:
        return bool(_table_exists_cache[key])
    exists = bool(probe(cursor, table_name))
    _table_exists_cache[key] = exists
    return exists


def mark_table_exists(table_name: str, exists: bool = True) -> None:
    _table_exists_cache[str(table_name)] = bool(exists)


def run_schema_ensure_once(key: str, fn: Callable[[], None]) -> bool:
    """
    Run fn() at most once per process for the given key.

    Returns True if fn ran, False if skipped (already ensured).
    """
    if key in _ensured_keys:
        _skip_counts[key] = int(_skip_counts.get(key) or 0) + 1
        return False
    _call_counts[key] = int(_call_counts.get(key) or 0) + 1
    fn()
    _ensured_keys.add(key)
    return True
