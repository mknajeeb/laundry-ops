import json
import math
import re
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

from werkzeug.security import check_password_hash, generate_password_hash


def once_per_cursor(name: str):
    """Skip a schema ensure after it has succeeded on this request cursor."""

    def deco(fn):
        flag = f"_vw_ensured_{name}"

        def wrapped(cursor, *args, **kwargs):
            if getattr(cursor, flag, False):
                return None
            result = fn(cursor, *args, **kwargs)
            try:
                setattr(cursor, flag, True)
            except Exception:
                pass
            return result

        wrapped.__name__ = getattr(fn, "__name__", "wrapped")
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped

    return deco


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def week_bounds_for_date(d: date):
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def cycle_ref_for_week_start(week_start: date) -> str:
    iso = week_start.isocalendar()
    return f"PC-{week_start.year}-W{iso[1]:02d}"


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# Naive datetimes from TA/payroll (clock_in_at, breaks, etc.) are America/New_York wall time
# (see eastern_now_naive in payroll_identity). Tag them correctly so browsers parse one instant.
_PAYROLL_NAIVE_TZ = ZoneInfo("America/New_York")


def json_safe(obj):
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        dt = obj
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_PAYROLL_NAIVE_TZ)
        return dt.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, bytearray):
        return bytes(obj).decode("utf-8", errors="replace")
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    return obj


def mask_tax_id_for_api_response(d: dict) -> None:
    """In-place: never expose full SSN/ITIN in JSON; keep last 4 as itin_ssn_last4."""
    raw = d.get("itin_ssn")
    if raw:
        digits = re.sub(r"\D", "", str(raw))
        d["itin_ssn_last4"] = digits[-4:] if len(digits) >= 4 else None
    else:
        d["itin_ssn_last4"] = None
    d["itin_ssn"] = None


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(hash_str: str, plain: str) -> bool:
    return check_password_hash(hash_str, plain)


_schema_lock = threading.Lock()
_scope_local = threading.local()
# Schema rarely changes at runtime; INFORMATION_SCHEMA hits are slow on remote MySQL (e.g. Azure).
# Columns are loaded once per table and database. A later check for another column does not query again.
# Cursors without a real database name (unit-test fakes) do not write this cache.
_column_cache: dict[tuple[str, str, str], bool] = {}
_table_cache: dict[tuple[str, str], bool] = {}
_table_columns: dict[tuple[str, str], set[str]] = {}


def _schema_scope(cursor) -> str | None:
    """Database name for a live connection. Missing names stay uncached."""
    conn = getattr(cursor, "connection", None) or getattr(cursor, "_connection", None)
    name = str(getattr(conn, "database", None) or "").strip() if conn is not None else ""
    scope = name or None
    _scope_local.scope = scope
    return scope


def _column_name(row) -> str:
    if isinstance(row, dict):
        raw = row.get("COLUMN_NAME") or row.get("column_name")
    elif row:
        raw = row[0]
    else:
        raw = None
    return str(raw or "")


def _load_table_columns(cursor, table_name: str) -> set[str]:
    """One INFORMATION_SCHEMA read for every column on this table."""
    scope = _schema_scope(cursor)
    cache_key = (scope, table_name) if scope else None
    if cache_key is not None:
        with _schema_lock:
            cached = _table_columns.get(cache_key)
            if cached is not None:
                return set(cached)
    if not table_exists(cursor, table_name):
        if cache_key is not None:
            with _schema_lock:
                _table_columns[cache_key] = set()
        return set()
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    found = {_column_name(row) for row in (cursor.fetchall() or [])}
    found.discard("")
    if cache_key is not None:
        with _schema_lock:
            _table_columns[cache_key] = set(found)
            _table_cache[cache_key] = True
            for column in found:
                _column_cache[(scope, table_name, column)] = True
    return found


def table_has_column(cursor, table_name: str, col_name: str) -> bool:
    scope = _schema_scope(cursor)
    key = (scope, table_name, col_name) if scope else None
    if key is not None:
        with _schema_lock:
            if key in _column_cache:
                return _column_cache[key]
    found = _load_table_columns(cursor, table_name)
    ok = col_name in found
    if key is not None:
        with _schema_lock:
            _column_cache[key] = ok
    return ok


def table_exists(cursor, table_name: str) -> bool:
    scope = _schema_scope(cursor)
    key = (scope, table_name) if scope else None
    if key is not None:
        with _schema_lock:
            if key in _table_cache:
                return _table_cache[key]
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        LIMIT 1
        """,
        (table_name,),
    )
    ok = cursor.fetchone() is not None
    if key is not None:
        with _schema_lock:
            _table_cache[key] = ok
    return ok


def remember_column(table_name: str, column_name: str) -> None:
    """Record a column this process just added so the next check does not repeat ALTER."""
    scope = getattr(_scope_local, "scope", None)
    if not scope:
        return
    with _schema_lock:
        _table_columns.setdefault((scope, table_name), set()).add(column_name)
        _column_cache[(scope, table_name, column_name)] = True
        _table_cache[(scope, table_name)] = True


def invalidate_table_schema(table_name: str) -> None:
    """Drop cached answers for one table after CREATE or ALTER on that table."""
    with _schema_lock:
        for key in [item for item in _table_cache if item[1] == table_name]:
            _table_cache.pop(key, None)
        for key in [item for item in _table_columns if item[1] == table_name]:
            _table_columns.pop(key, None)
        for key in [item for item in _column_cache if item[1] == table_name]:
            _column_cache.pop(key, None)


def invalidate_schema_cache() -> None:
    """
    Call after runtime DDL (CREATE / ALTER). Negative answers for table_has_column /
    table_exists are cached; without invalidation the next request can repeat migrations
    and raise "duplicate column" / "table already exists", surfacing as HTTP 500.
    """
    with _schema_lock:
        _column_cache.clear()
        _table_cache.clear()
        _table_columns.clear()
