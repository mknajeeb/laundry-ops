import json
import math
import re
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from werkzeug.security import check_password_hash, generate_password_hash


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


def json_safe(obj):
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        # MySQL DATETIME is naive; API hosts (e.g. Azure) use UTC. Without tz, browsers
        # parse ISO strings as *local* wall time and times appear ~offset from Eastern US.
        dt = obj
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
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
# Schema rarely changes at runtime; INFORMATION_SCHEMA hits are slow on remote MySQL (e.g. Azure).
_column_cache: dict[tuple[str, str], bool] = {}
_table_cache: dict[str, bool] = {}


def table_has_column(cursor, table_name: str, col_name: str) -> bool:
    key = (table_name, col_name)
    with _schema_lock:
        if key in _column_cache:
            return _column_cache[key]
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table_name, col_name),
    )
    ok = cursor.fetchone() is not None
    with _schema_lock:
        _column_cache[key] = ok
    return ok


def table_exists(cursor, table_name: str) -> bool:
    with _schema_lock:
        if table_name in _table_cache:
            return _table_cache[table_name]
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        LIMIT 1
        """,
        (table_name,),
    )
    ok = cursor.fetchone() is not None
    with _schema_lock:
        _table_cache[table_name] = ok
    return ok


def invalidate_schema_cache() -> None:
    """
    Call after runtime DDL (CREATE / ALTER). Negative answers for table_has_column /
    table_exists are cached; without invalidation the next request can repeat migrations
    and raise "duplicate column" / "table already exists", surfacing as HTTP 500.
    """
    with _schema_lock:
        _column_cache.clear()
        _table_cache.clear()
