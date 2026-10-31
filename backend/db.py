from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from dotenv import load_dotenv
from mysql.connector import errors as mysql_errors
from mysql.connector import pooling

load_dotenv()

logger = logging.getLogger(__name__)

# mysql.connector caps pool_size at 32 (CNX_POOL_MAXSIZE).
_MAX_POOL = getattr(pooling, "CNX_POOL_MAXSIZE", 32)

_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()
_pool_size_resolved: int = 0

# Floor kept high enough for parallel PIN/branding/dashboard tabs on one worker,
# but low enough that workers × pool_size leaves MySQL headroom (max_connections=171).
_MIN_POOL = 4
_DEFAULT_POOL = 8
_DEFAULT_CONNECT_TIMEOUT_SEC = 8
# Wait for a free pooled connection. Separate from the TCP/auth handshake timeout.
_DEFAULT_POOL_ACQUIRE_TIMEOUT_SEC = 5.0
_MAX_POOL_ACQUIRE_TIMEOUT_SEC = 30.0

# Client-facing text only. Server logs keep the pool diagnostics.
DATABASE_BUSY_MESSAGE = "Service temporarily busy. Please try again in a moment."


class DatabasePoolBusy(Exception):
    """Pool checkout exceeded MYSQL_POOL_ACQUIRE_TIMEOUT.

    ``str(self)`` is safe to show to a client. The MySQL ``PoolError`` is
    chained as ``__cause__`` for server logs and must not be copied into
    the HTTP body.
    """

    def __init__(self) -> None:
        super().__init__(DATABASE_BUSY_MESSAGE)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def resolve_pool_size(raw: str | None = None) -> int:
    """Clamp configured pool size into a safe range for App Service + shared MySQL."""
    if raw is None:
        raw = os.getenv("MYSQL_POOL_SIZE")
    try:
        size = int(str(raw).strip()) if raw not in (None, "") else _DEFAULT_POOL
    except (TypeError, ValueError):
        size = _DEFAULT_POOL
    return max(_MIN_POOL, min(size, _MAX_POOL))


def resolve_connect_timeout_sec() -> int:
    """Seconds for establishing a MySQL TCP/auth handshake (not query duration)."""
    return max(1, min(60, _env_int("MYSQL_CONNECT_TIMEOUT", _DEFAULT_CONNECT_TIMEOUT_SEC)))


def resolve_pool_acquire_timeout_sec() -> float:
    """Max seconds to wait for a free connection already in this process pool.

    mysql.connector pops the pool queue with ``block=False`` (no wait). This
    bound is applied by ``get_db()`` and is independent of
    ``MYSQL_CONNECT_TIMEOUT``, which only limits the TCP/auth handshake
    (including reconnect of a dead pooled socket).
    """
    raw = (os.getenv("MYSQL_POOL_ACQUIRE_TIMEOUT") or "").strip()
    if not raw:
        value = _DEFAULT_POOL_ACQUIRE_TIMEOUT_SEC
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = _DEFAULT_POOL_ACQUIRE_TIMEOUT_SEC
    if value < 0:
        return 0.0
    return min(value, _MAX_POOL_ACQUIRE_TIMEOUT_SEC)


def _connection_kwargs() -> dict[str, Any]:
    """Shared connect kwargs for the pool and for direct connects (scripts)."""
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "mkncentralussrv1.mysql.database.azure.com"
    user = os.getenv("MYSQL_USER") or os.getenv("DB_USER") or "kamsee"
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "laundryapp"
    port = int(os.getenv("MYSQL_PORT") or os.getenv("DB_PORT") or "3306")

    if not password:
        raise RuntimeError(
            "Set MYSQL_PASSWORD or DB_PASSWORD in a .env file in the project root."
        )

    kwargs: dict[str, Any] = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port,
        # Fail fast on connect storms instead of holding a gunicorn worker indefinitely.
        "connection_timeout": resolve_connect_timeout_sec(),
    }
    ssl_ca = os.getenv("MYSQL_SSL_CA")
    if ssl_ca:
        kwargs["ssl_ca"] = ssl_ca
        kwargs["ssl_disabled"] = False
    elif os.getenv("MYSQL_SSL_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
        kwargs["ssl_disabled"] = False
    return kwargs


def _ensure_pool() -> pooling.MySQLConnectionPool:
    global _pool, _pool_size_resolved
    with _pool_lock:
        if _pool is None:
            kwargs = _connection_kwargs()
            pool_size = resolve_pool_size()
            _pool_size_resolved = pool_size
            _pool = pooling.MySQLConnectionPool(
                pool_name="laundry_app_pool",
                pool_size=pool_size,
                pool_reset_session=True,
                **kwargs,
            )
            logger.info(
                "mysql_pool_initialized pool_size=%s connect_timeout=%s acquire_timeout=%s",
                pool_size,
                kwargs.get("connection_timeout"),
                resolve_pool_acquire_timeout_sec(),
            )
        return _pool


def pool_config_snapshot() -> dict[str, Any]:
    """Read-only snapshot for diagnostics (does not open a connection)."""
    return {
        "pool_initialized": _pool is not None,
        "pool_size": _pool_size_resolved or resolve_pool_size(),
        "connect_timeout_sec": resolve_connect_timeout_sec(),
        "pool_acquire_timeout_sec": resolve_pool_acquire_timeout_sec(),
        "pool_min": _MIN_POOL,
        "pool_max_cap": _MAX_POOL,
        "pool_default": _DEFAULT_POOL,
    }


def get_db():
    """
    Return a pooled MySQL connection. Caller must close() when done — close() returns the
    connection to the pool (no extra TLS handshake on reuse).

    Do not use a request-scoped wrapper that makes close() a no-op: many routes call
    get_db() + conn.close() in finally; those closes must return connections immediately
    or the pool exhausts under parallel requests (login + branding, etc.).

    When every pooled connection is checked out, wait up to
    ``MYSQL_POOL_ACQUIRE_TIMEOUT`` seconds (default 5), then raise
    ``DatabasePoolBusy``. That wait is not the handshake timeout
    (``MYSQL_CONNECT_TIMEOUT``). The client message is fixed; pool details
    stay in the server log.
    """
    timeout = resolve_pool_acquire_timeout_sec()
    deadline = time.monotonic() + timeout
    while True:
        try:
            return _ensure_pool().get_connection()
        except mysql_errors.PoolError as exc:
            if time.monotonic() >= deadline:
                logger.error(
                    "mysql_pool_exhausted pool_size=%s acquire_timeout_sec=%s connect_timeout_sec=%s error=%s detail=%s",
                    _pool_size_resolved or resolve_pool_size(),
                    timeout,
                    resolve_connect_timeout_sec(),
                    type(exc).__name__,
                    exc,
                )
                raise DatabasePoolBusy() from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
