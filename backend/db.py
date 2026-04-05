from __future__ import annotations

import os
import threading
from typing import Any, Optional

from mysql.connector import pooling

# mysql.connector caps pool_size at 32 (CNX_POOL_MAXSIZE). Each HTTP request may hold one
# connection until teardown; parallel tabs/XHR can exhaust a small pool quickly.
_MAX_POOL = getattr(pooling, "CNX_POOL_MAXSIZE", 32)
from dotenv import load_dotenv

load_dotenv()

_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()


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
            pool_size = max(1, min(pool_size, _MAX_POOL))
            _pool = pooling.MySQLConnectionPool(
                pool_name="laundry_app_pool",
                pool_size=pool_size,
                pool_reset_session=True,
                **kwargs,
            )
        return _pool


class _RequestScopedConnection:
    """One pooled connection per HTTP request; close() is deferred to Flask teardown."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)

    def close(self) -> None:
        return None


def close_request_db_if_any() -> None:
    """Return the request-scoped connection to the pool (call from teardown_appcontext)."""
    try:
        from flask import g, has_request_context
    except ImportError:
        return
    if not has_request_context():
        return
    wrapped = getattr(g, "_laundry_db_conn", None)
    if wrapped is None:
        return
    g._laundry_db_conn = None
    inner = getattr(wrapped, "_inner", None)
    if inner is not None:
        try:
            inner.close()
        except Exception:
            pass


def get_db():
    """
    MySQL connection: pooled, reused across the process.

    Inside a Flask request, the same connection is returned for every get_db() call
    (auth, permission checks, route body) so we avoid multiple TLS handshakes to Azure
    per request. Teardown returns it to the pool.

    Outside a request (scripts), returns a pooled connection; caller must .close() to return it.
    """
    try:
        from flask import g, has_request_context

        if has_request_context():
            existing = getattr(g, "_laundry_db_conn", None)
            if existing is not None:
                return existing
            raw = _ensure_pool().get_connection()
            wrapped = _RequestScopedConnection(raw)
            g._laundry_db_conn = wrapped
            return wrapped
    except RuntimeError:
        pass

    return _ensure_pool().get_connection()
