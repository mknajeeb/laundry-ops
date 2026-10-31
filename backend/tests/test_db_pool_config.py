"""P0 MySQL pool configuration — no live database required."""

from __future__ import annotations

import pytest
from mysql.connector import errors as mysql_errors

import backend.db as db


def test_resolve_pool_size_default():
    assert db.resolve_pool_size(None) == db._DEFAULT_POOL
    assert db.resolve_pool_size("") == db._DEFAULT_POOL


def test_resolve_pool_size_clamps(monkeypatch):
    monkeypatch.delenv("MYSQL_POOL_SIZE", raising=False)
    assert db.resolve_pool_size("1") == db._MIN_POOL
    assert db.resolve_pool_size("999") == db._MAX_POOL
    assert db.resolve_pool_size("12") == 12


def test_resolve_pool_size_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("MYSQL_POOL_SIZE", "nope")
    assert db.resolve_pool_size() == db._DEFAULT_POOL


def test_resolve_connect_timeout(monkeypatch):
    monkeypatch.delenv("MYSQL_CONNECT_TIMEOUT", raising=False)
    assert db.resolve_connect_timeout_sec() == db._DEFAULT_CONNECT_TIMEOUT_SEC
    monkeypatch.setenv("MYSQL_CONNECT_TIMEOUT", "3")
    assert db.resolve_connect_timeout_sec() == 3
    monkeypatch.setenv("MYSQL_CONNECT_TIMEOUT", "999")
    assert db.resolve_connect_timeout_sec() == 60


def test_connection_kwargs_include_timeout(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", "unit-test-password")
    monkeypatch.setenv("MYSQL_CONNECT_TIMEOUT", "7")
    kwargs = db._connection_kwargs()
    assert kwargs["connection_timeout"] == 7
    assert "password" in kwargs


def test_pool_config_snapshot_without_init(monkeypatch):
    monkeypatch.setenv("MYSQL_POOL_SIZE", "10")
    monkeypatch.setenv("MYSQL_CONNECT_TIMEOUT", "5")
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "2")
    # Reset module pool state for isolation.
    db._pool = None
    db._pool_size_resolved = 0
    snap = db.pool_config_snapshot()
    assert snap["pool_initialized"] is False
    assert snap["pool_size"] == 10
    assert snap["connect_timeout_sec"] == 5
    assert snap["pool_acquire_timeout_sec"] == 2


def test_resolve_pool_acquire_timeout_independent_of_connect(monkeypatch):
    monkeypatch.setenv("MYSQL_CONNECT_TIMEOUT", "8")
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "5")
    assert db.resolve_connect_timeout_sec() == 8
    assert db.resolve_pool_acquire_timeout_sec() == 5
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "0")
    assert db.resolve_pool_acquire_timeout_sec() == 0
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "999")
    assert db.resolve_pool_acquire_timeout_sec() == db._MAX_POOL_ACQUIRE_TIMEOUT_SEC
    monkeypatch.delenv("MYSQL_POOL_ACQUIRE_TIMEOUT", raising=False)
    assert db.resolve_pool_acquire_timeout_sec() == db._DEFAULT_POOL_ACQUIRE_TIMEOUT_SEC


def test_get_db_logs_and_raises_safe_pool_busy(monkeypatch, caplog):
    class _BoomPool:
        def get_connection(self):
            raise mysql_errors.PoolError("Failed getting connection; pool exhausted")

    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "0")
    monkeypatch.setattr(db, "_ensure_pool", lambda: _BoomPool())
    with caplog.at_level("ERROR", logger="backend.db"):
        with pytest.raises(db.DatabasePoolBusy) as raised:
            db.get_db()
    assert str(raised.value) == db.DATABASE_BUSY_MESSAGE
    assert isinstance(raised.value.__cause__, mysql_errors.PoolError)
    assert "mysql_pool_exhausted" in caplog.text
    assert "pool exhausted" in caplog.text
    assert "password" not in caplog.text.lower()


def test_get_db_waits_for_pooled_connection_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class _FlakyPool:
        def get_connection(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise mysql_errors.PoolError("Failed getting connection; pool exhausted")
            return "conn-ok"

    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "1")
    monkeypatch.setattr(db, "_ensure_pool", lambda: _FlakyPool())
    monkeypatch.setattr(db.time, "sleep", lambda _sec: None)
    assert db.get_db() == "conn-ok"
    assert calls["n"] == 2


def test_get_db_acquire_wait_is_bounded(monkeypatch):
    class _BoomPool:
        def get_connection(self):
            raise mysql_errors.PoolError("Failed getting connection; pool exhausted")

    clock = {"now": 1000.0}

    def _mono():
        return clock["now"]

    def _sleep(sec):
        clock["now"] += sec

    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT", "0.2")
    monkeypatch.setattr(db, "_ensure_pool", lambda: _BoomPool())
    monkeypatch.setattr(db.time, "monotonic", _mono)
    monkeypatch.setattr(db.time, "sleep", _sleep)
    with pytest.raises(db.DatabasePoolBusy) as raised:
        db.get_db()
    assert str(raised.value) == db.DATABASE_BUSY_MESSAGE
    assert clock["now"] >= 1000.2
    assert clock["now"] < 1000.2 + 0.05 + 0.001
