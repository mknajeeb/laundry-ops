from __future__ import annotations

import os
import threading
from typing import Any, Optional

from dotenv import load_dotenv
from mysql.connector import pooling

load_dotenv()

# mysql.connector caps pool_size at 32 (CNX_POOL_MAXSIZE).
_MAX_POOL = getattr(pooling, "CNX_POOL_MAXSIZE", 32)

_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()

# Env can accidentally set 1 — two parallel tabs will exhaust the pool immediately.
_MIN_POOL = 8


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
    }
    ssl_ca = os.getenv("MYSQL_SSL_CA")
    if ssl_ca:
        kwargs["ssl_ca"] = ssl_ca
        kwargs["ssl_disabled"] = False
    elif os.getenv("MYSQL_SSL_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
        kwargs["ssl_disabled"] = False
    return kwargs


def _ensure_pool() -> pooling.MySQLConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            kwargs = _connection_kwargs()
            pool_size = int(os.getenv("MYSQL_POOL_SIZE", str(_MAX_POOL)))
            pool_size = max(_MIN_POOL, min(pool_size, _MAX_POOL))
            _pool = pooling.MySQLConnectionPool(
                pool_name="laundry_app_pool",
                pool_size=pool_size,
                pool_reset_session=True,
                **kwargs,
            )
        return _pool


def get_db():
    """
    Return a pooled MySQL connection. Caller must close() when done — close() returns the
    connection to the pool (no extra TLS handshake on reuse).

    Do not use a request-scoped wrapper that makes close() a no-op: many routes call
    get_db() + conn.close() in finally; those closes must return connections immediately
    or the pool exhausts under parallel requests (login + branding, etc.).
    """
    return _ensure_pool().get_connection()
