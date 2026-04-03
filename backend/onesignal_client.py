"""
Server-side OneSignal REST API (push). Targets users by External User ID — same string as the
browser after OneSignal.login() (see frontend/src/onesignalUser.js).

Env (repo root .env or Azure App Settings):
  ONESIGNAL_APP_ID          — same app as VITE_ONESIGNAL_APP_ID (public)
  ONESIGNAL_REST_API_KEY    — REST API Key from OneSignal → Keys & IDs (secret; never expose to client)

Optional:
  ONESIGNAL_BROADCAST_SEGMENT — default "Subscribed Users"
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ONESIGNAL_NOTIFY_URL = "https://onesignal.com/api/v1/notifications"

# Must match frontend/src/onesignalUser.js
def external_user_id(organization_id: int, user_id: int) -> str:
    """Stable External User ID for OneSignal (matches browser OneSignal.login)."""
    return f"lo-{int(organization_id)}-{int(user_id)}"


def _app_id() -> str | None:
    return (os.getenv("ONESIGNAL_APP_ID") or os.getenv("VITE_ONESIGNAL_APP_ID") or "").strip() or None


def _rest_key() -> str | None:
    return (os.getenv("ONESIGNAL_REST_API_KEY") or "").strip() or None


def send_push_to_external_user_ids(
    external_ids: list[str],
    title: str,
    body: str,
    *,
    data: dict | None = None,
) -> tuple[bool, str | None]:
    """
    Send a web push to specific External User IDs (all devices where that user logged in).
    Returns (ok, error_message).
    """
    app_id = _app_id()
    key = _rest_key()
    if not app_id or not key:
        return False, "ONESIGNAL_APP_ID or ONESIGNAL_REST_API_KEY not configured"
    if not external_ids:
        return False, "no external_ids"

    payload: dict = {
        "app_id": app_id,
        "include_external_user_ids": external_ids[:2000],
        "headings": {"en": title},
        "contents": {"en": body},
    }
    if data:
        payload["data"] = data

    return _post_notification(payload)


def send_push_broadcast_subscribed(title: str, body: str, *, data: dict | None = None) -> tuple[bool, str | None]:
    """Send to all subscribed users (typical segment for web push)."""
    app_id = _app_id()
    key = _rest_key()
    if not app_id or not key:
        return False, "ONESIGNAL_APP_ID or ONESIGNAL_REST_API_KEY not configured"

    segment = (
        os.getenv("ONESIGNAL_BROADCAST_SEGMENT") or "Subscribed Users"
    ).strip() or "Subscribed Users"
    payload: dict = {
        "app_id": app_id,
        "included_segments": [segment],
        "headings": {"en": title},
        "contents": {"en": body},
    }
    if data:
        payload["data"] = data
    return _post_notification(payload)


def _post_notification(payload: dict) -> tuple[bool, str | None]:
    key = _rest_key()
    assert key
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ONESIGNAL_NOTIFY_URL,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Key {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
        if parsed.get("errors"):
            err = str(parsed.get("errors"))
            logger.warning("OneSignal API errors: %s", err)
            return False, err
        return True, None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        logger.warning("OneSignal HTTP %s: %s", e.code, detail)
        return False, detail or str(e)
    except Exception as ex:
        logger.exception("OneSignal request failed")
        return False, str(ex)


_geofence_lock = threading.Lock()
_geofence_last: dict[str, float] = {}


def notify_geofence_outside_cooldown(
    user_id: int,
    organization_id: int,
    distance_m: int,
    *,
    cooldown_sec: int = 900,
) -> None:
    """
    Example event-driven push: user clocked in but location ping is outside geofence.
    Throttled per user to avoid spamming on every poll (in-memory; use Redis if you scale workers).
    """
    key = f"{organization_id}:{user_id}"
    now = time.time()
    with _geofence_lock:
        last = _geofence_last.get(key, 0.0)
        if now - last < cooldown_sec:
            return
        _geofence_last[key] = now

    eid = external_user_id(organization_id, user_id)
    title = "Laundry Ops"
    body = f"You're outside your work geofence (~{int(distance_m)}m). Please return when you can."
    ok, err = send_push_to_external_user_ids(
        [eid],
        title,
        body,
        data={"type": "geofence_outside", "distance_m": int(distance_m)},
    )
    if not ok:
        logger.debug("Geofence push skipped or failed: %s", err)
