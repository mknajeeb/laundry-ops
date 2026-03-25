import json
import math
from datetime import date, datetime, timedelta
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
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    return obj


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(hash_str: str, plain: str) -> bool:
    return check_password_hash(hash_str, plain)
