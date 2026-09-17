"""Schema ensure memoization + owner PK lookup."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.schema_ensure_cache import (
    reset_schema_ensure_cache,
    run_schema_ensure_once,
    schema_ensure_stats,
)


def setup_function():
    reset_schema_ensure_cache()


def test_run_schema_ensure_once_memoizes():
    calls = []

    def fn():
        calls.append(1)

    assert run_schema_ensure_once("k", fn) is True
    assert run_schema_ensure_once("k", fn) is False
    assert run_schema_ensure_once("k", fn) is False
    assert calls == [1]
    stats = schema_ensure_stats()
    assert stats["calls"]["k"] == 1
    assert stats["skips"]["k"] == 2


def test_ensure_rinse_bag_tables_skips_after_first():
    from backend.rinse_bag_registry import ensure_rinse_bag_tables

    executes: list[str] = []

    class Cur:
        def execute(self, sql, params=None):
            executes.append(str(sql).split()[0:4].__repr__() if False else str(sql)[:60])

        def fetchone(self):
            return {"len": 32, "c": 1}

    cur = Cur()
    ensure_rinse_bag_tables(cur)
    first_n = len(executes)
    assert first_n > 0
    ensure_rinse_bag_tables(cur)
    ensure_rinse_bag_tables(cur)
    # Second and third calls must not re-issue CREATE / information_schema probes.
    assert len(executes) == first_n
    stats = schema_ensure_stats()
    assert stats["calls"].get("rinse_bag_tables") == 1
    assert stats["skips"].get("rinse_bag_tables") == 2


def test_ensure_wf_service_cycles_memoized():
    from backend.rinse_wf_service_cycle import ensure_wf_service_cycles_table

    probes: list[str] = []

    def fake_exists(cursor, name):
        probes.append(name)
        return True

    import backend.rinse_wf_service_cycle as mod

    orig = mod.table_exists
    mod.table_exists = fake_exists
    try:
        cur = MagicMock()
        ensure_wf_service_cycles_table(cur)
        ensure_wf_service_cycles_table(cur)
        ensure_wf_service_cycles_table(cur)
        assert probes == ["rinse_wf_service_cycles"]
    finally:
        mod.table_exists = orig


def test_fetch_owner_uses_pk_equality():
    from backend import rinse_bag_operational_owner as own

    sqls: list[str] = []
    params_seen: list[tuple] = []

    class Cur:
        def execute(self, sql, params=None):
            sqls.append(sql)
            params_seen.append(params)

        def fetchone(self):
            return None

    # Pretend table exists without SHOW TABLES on every call after cache.
    from backend.schema_ensure_cache import mark_table_exists

    mark_table_exists("rinse_bag_operational_owner", True)
    own._fetch_owner_row(Cur(), "abc123")
    assert len(sqls) == 1
    assert "WHERE bag_id = %s" in sqls[0]
    assert "UPPER(TRIM" not in sqls[0]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("abc123", "ABC123"),
        ("ABC123", "ABC123"),
        ("  abc123", "ABC123"),
        ("abc123  ", "ABC123"),
        ("  AbC123  ", "ABC123"),
        ("BAG_12", "BAG_12"),
        ("bag-99", "BAG-99"),
    ],
)
def test_fetch_owner_normalizes_input_then_pk_equality(raw, expected):
    from backend import rinse_bag_operational_owner as own
    from backend.schema_ensure_cache import mark_table_exists, reset_schema_ensure_cache

    reset_schema_ensure_cache()
    mark_table_exists("rinse_bag_operational_owner", True)
    params_seen: list = []

    class Cur:
        def execute(self, sql, params=None):
            params_seen.append(params)

        def fetchone(self):
            return {
                "bag_id": expected,
                "owner_organization_id": 3,
                "owner_rinse_vendor": "veewash",
                "assigned_at": None,
                "assignment_source": "registry",
                "locked": 1,
            }

    row = own._fetch_owner_row(Cur(), raw)
    assert params_seen == [(expected,)]
    assert row is not None
    assert row["bag_id"] == expected


def test_resolve_canonical_owners_batch_pk_equality(monkeypatch):
    from backend import rinse_bag_operational_owner as own

    sqls: list[str] = []

    class Cur:
        def execute(self, sql, params=None):
            sqls.append(sql)

        def fetchall(self):
            return []

    monkeypatch.setattr(own, "table_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(own, "_collect_evidence_candidates", lambda *_a, **_k: {})
    own.resolve_canonical_owners(Cur(), ["ab12", "cd34"])
    assert any("WHERE bag_id IN" in s for s in sqls)
    assert not any("UPPER(TRIM" in s for s in sqls)
