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
import uuid

logger = logging.getLogger(__name__)

ONESIGNAL_NOTIFY_URL = "https://api.onesignal.com/notifications"
ONESIGNAL_NOTIFY_URL_V1 = "https://onesignal.com/api/v1/notifications"
# Stable namespace so the same report and recipient always map to the same OneSignal key.
_IDEMPOTENCY_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Must match frontend/src/onesignalUser.js
def external_user_id(organization_id: int, user_id: int) -> str:
    """Stable External User ID for OneSignal (matches browser OneSignal.login)."""
    return f"lo-{int(organization_id)}-{int(user_id)}"


def _app_id() -> str | None:
    return (os.getenv("ONESIGNAL_APP_ID") or os.getenv("VITE_ONESIGNAL_APP_ID") or "").strip() or None


def _rest_key() -> str | None:
    return (os.getenv("ONESIGNAL_REST_API_KEY") or "").strip() or None


def onesignal_idempotency_uuid(raw: str | None) -> str | None:
    """OneSignal accepts only a UUID. A business key becomes a stable UUID5."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, text[:64]))


def public_web_url(path: str | None) -> str | None:
    """Absolute app URL for a notification tap. Relative paths stay in notification data."""
    raw_path = str(path or "").strip()
    if not raw_path.startswith("/") or raw_path.startswith("//"):
        return None
    base = (os.getenv("PUBLIC_APP_URL") or os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if not base:
        raw = os.getenv("CORS_ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS") or ""
        for part in raw.split(","):
            candidate = part.strip().rstrip("/")
            if (
                candidate.startswith("https://")
                and "localhost" not in candidate
                and "127.0.0.1" not in candidate
            ):
                base = candidate
                break
    if not base:
        return None
    return base + raw_path


def _classify_push_result(parsed: dict | None) -> tuple[bool, str | None]:
    """Map a OneSignal create-notification body to sent-or-not.

    A non-empty id means at least one subscribed device was sent the message.
    invalid_aliases lists opted-out subscriptions and does not cancel that send.
    An empty id with those aliases means nothing was subscribed.
    """
    if not isinstance(parsed, dict):
        return False, "empty_response"
    errors = parsed.get("errors")
    if errors in ([], {}, ""):
        errors = None
    recipients = parsed.get("recipients")
    note_id = str(parsed.get("id") or "").strip()
    if recipients == 0:
        return False, "no_subscribed_devices"
    if note_id:
        return True, None
    if errors:
        text = str(errors)
        if "invalid_aliases" in text or "not subscribed" in text.lower():
            return False, "no_subscribed_devices"
        return False, text[:500]
    if isinstance(recipients, int) and recipients > 0:
        return True, None
    return False, "unconfirmed_delivery"


def send_push_to_external_user_ids(
    external_ids: list[str],
    title: str,
    body: str,
    *,
    data: dict | None = None,
    url: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[bool, str | None]:
    """
    Send a web push to specific External User IDs (every device currently linked to that user).
    Returns (ok, error_message). ok is false when OneSignal reports no subscribed device.
    """
    app_id = _app_id()
    key = _rest_key()
    if not app_id or not key:
        return False, "ONESIGNAL_APP_ID or ONESIGNAL_REST_API_KEY not configured"
    if not external_ids:
        return False, "no external_ids"

    ids = [str(item) for item in external_ids[:2000] if str(item or "").strip()]
    if not ids:
        return False, "no external_ids"
    payload: dict = {
        "app_id": app_id,
        "target_channel": "push",
        "include_aliases": {"external_id": ids},
        "headings": {"en": title},
        "contents": {"en": body},
    }
    if data:
        payload["data"] = {k: v for k, v in data.items() if k != "user_id"}
    if url:
        payload["url"] = url
    idem = onesignal_idempotency_uuid(idempotency_key)
    if idem:
        payload["idempotency_key"] = idem

    ok, err = _post_notification(payload, idempotency_key=idem)
    if ok:
        return ok, err
    # A rejected create (not an accepted notification with zero devices) can be retried
    # on the older endpoint. Do not send twice when the first call was accepted.
    if err and err.startswith(("http_400", "http_404", "http_422")) and "include_aliases" in err.lower():
        legacy: dict = {
            "app_id": app_id,
            "include_external_user_ids": ids,
            "headings": {"en": title},
            "contents": {"en": body},
        }
        if data:
            legacy["data"] = {k: v for k, v in data.items() if k != "user_id"}
        if url:
            legacy["url"] = url
        if idem:
            legacy["idempotency_key"] = idem
        return _post_notification(
            legacy,
            endpoint=ONESIGNAL_NOTIFY_URL_V1,
            idempotency_key=idem,
        )
    return ok, err


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


def _post_notification(
    payload: dict,
    *,
    endpoint: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[bool, str | None]:
    key = _rest_key()
    assert key
    raw = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Key {key}",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = onesignal_idempotency_uuid(idempotency_key) or ""
    target = endpoint or ONESIGNAL_NOTIFY_URL
    req = urllib.request.Request(target, data=raw, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
        ok, err = _classify_push_result(parsed if isinstance(parsed, dict) else None)
        if not ok:
            logger.warning("OneSignal push not delivered: %s", err)
        else:
            logger.info(
                "OneSignal push accepted id=%s recipients=%s",
                (parsed or {}).get("id"),
                (parsed or {}).get("recipients"),
            )
        return ok, err
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        if e.code in (401, 403) and headers["Authorization"].startswith("Key "):
            headers["Authorization"] = f"Basic {key}"
            retry = urllib.request.Request(target, data=raw, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(retry, timeout=30) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return _classify_push_result(parsed if isinstance(parsed, dict) else None)
            except urllib.error.HTTPError as retry_err:
                try:
                    detail = retry_err.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = str(retry_err)
                logger.warning("OneSignal HTTP %s: %s", retry_err.code, detail[:300])
                return False, f"http_{retry_err.code}:{(detail or str(retry_err))[:400]}"
            except Exception as ex:
                logger.warning("OneSignal request failed: %s", ex)
                return False, str(ex)[:500]
        logger.warning("OneSignal HTTP %s: %s", e.code, detail[:300])
        return False, f"http_{e.code}:{(detail or str(e))[:400]}"
    except Exception as ex:
        logger.warning("OneSignal request failed: %s", ex)
        return False, str(ex)[:500]


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
