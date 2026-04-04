"""
Tenant notification routing + delivery helpers.

Audience model (industry pattern):
  final_recipients = (union of includes) minus (union of excludes)
  includes/excludes may reference users or groups (groups expand to user ids).

Delivery respects per-user channel prefs (push, email, sms, whatsapp) from user_notification_preferences.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_delivery(
    cursor,
    *,
    organization_id: int,
    event_key: str,
    user_id: int | None,
    channel: str,
    status: str,
    detail: str | None = None,
    payload: dict | None = None,
) -> None:
    """Persist audit row when notification_delivery_log exists."""
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "notification_delivery_log"):
        return
    try:
        cursor.execute(
            """
            INSERT INTO notification_delivery_log
              (organization_id, event_key, user_id, channel, status, detail, payload_json)
            VALUES (%s,%s,%s,%s,%s,%s, %s)
            """,
            (
                int(organization_id),
                str(event_key)[:64],
                int(user_id) if user_id is not None else None,
                channel[:16],
                status[:32],
                (detail or "")[:512] if detail else None,
                json.dumps(payload, default=str) if payload is not None else None,
            ),
        )
    except Exception as ex:
        logger.debug("notification_delivery_log insert skipped: %s", ex)


def _group_member_ids(cursor, organization_id: int, group_id: int) -> set[int]:
    cursor.execute(
        """
        SELECT m.user_id FROM notification_group_members m
        JOIN notification_groups g ON g.id = m.group_id
        WHERE g.id = %s AND g.organization_id = %s
        """,
        (int(group_id), int(organization_id)),
    )
    return {int(r["user_id"]) for r in (cursor.fetchall() or []) if r.get("user_id") is not None}


def _user_in_org(cursor, organization_id: int, user_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM users WHERE id = %s AND organization_id = %s LIMIT 1",
        (int(user_id), int(organization_id)),
    )
    return cursor.fetchone() is not None


def _all_user_ids_in_org(cursor, organization_id: int) -> set[int]:
    """Active Washpro users for this tenant (for 'all users' include rule)."""
    cursor.execute(
        """
        SELECT id FROM users
        WHERE organization_id = %s AND COALESCE(active, 1) = 1
        """,
        (int(organization_id),),
    )
    return {int(r["id"]) for r in (cursor.fetchall() or []) if r.get("id") is not None}


# Sentinel: include/exclude with target_type=user and target_id=-1 means entire tenant user set.
_ALL_USERS_SENTINEL = -1


def resolve_recipient_user_ids(cursor, organization_id: int, event_definition_id: int) -> set[int]:
    """
    Apply include/exclude rules for an event. Returns Washpro user ids in the tenant.
    """
    cursor.execute(
        """
        SELECT target_type, target_id, rule_kind
        FROM notification_event_audiences
        WHERE event_definition_id = %s AND organization_id = %s
        """,
        (int(event_definition_id), int(organization_id)),
    )
    rows = cursor.fetchall() or []
    include: set[int] = set()
    exclude: set[int] = set()

    for r in rows:
        tt = (r.get("target_type") or "").strip()
        tid = int(r["target_id"])
        rk = (r.get("rule_kind") or "").strip()
        bucket = include if rk == "include" else exclude
        if tt == "user":
            if tid == _ALL_USERS_SENTINEL:
                bucket |= _all_user_ids_in_org(cursor, organization_id)
            elif _user_in_org(cursor, organization_id, tid):
                bucket.add(tid)
        elif tt == "group":
            mids = _group_member_ids(cursor, organization_id, tid)
            bucket |= mids

    return include - exclude


def get_user_channel_prefs(cursor, user_id: int) -> dict[str, bool]:
    """Defaults favor opted-in outbound channels."""
    from backend.ta_helpers import table_has_column

    defaults = {
        "email_out": True,
        "push_out": True,
        "sms_out": True,
        "whatsapp_out": False,
    }
    has_sms = table_has_column(cursor, "user_notification_preferences", "sms_out")
    sel = "email_out, push_out, whatsapp_out"
    if has_sms:
        sel = "email_out, push_out, sms_out, whatsapp_out"
    cursor.execute(
        f"SELECT {sel} FROM user_notification_preferences WHERE user_id = %s LIMIT 1",
        (int(user_id),),
    )
    row = cursor.fetchone()
    if not row:
        return defaults
    out = {
        "email_out": bool(row.get("email_out", 1)),
        "push_out": bool(row.get("push_out", 1)),
        "whatsapp_out": bool(row.get("whatsapp_out", 0)),
    }
    if has_sms:
        out["sms_out"] = bool(row.get("sms_out", 1))
    else:
        out["sms_out"] = True
    return out


def dispatch_notification_event(
    cursor,
    *,
    organization_id: int,
    event_key: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    channels: list[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve audiences for event_key, then send via enabled channels.
    channels: subset of ['push','email','sms','whatsapp'] — default all that are implemented.
    """
    from backend.onesignal_client import external_user_id, send_push_to_external_user_ids

    cursor.execute(
        """
        SELECT id FROM notification_event_definitions
        WHERE organization_id = %s AND event_key = %s AND is_active = 1
        LIMIT 1
        """,
        (int(organization_id), str(event_key)[:64]),
    )
    ev = cursor.fetchone()
    if not ev:
        return {"ok": False, "error": "unknown_or_inactive_event", "sent": 0}

    eid = int(ev["id"])
    user_ids = resolve_recipient_user_ids(cursor, organization_id, eid)
    want = set(channels or ["push", "email", "sms", "whatsapp"])
    sent = {"push": 0, "email": 0, "sms": 0, "whatsapp": 0}
    errors: list[str] = []

    for uid in sorted(user_ids):
        prefs = get_user_channel_prefs(cursor, uid)
        payload = {**(data or {}), "event_key": event_key, "user_id": uid}

        if "push" in want and prefs.get("push_out", True):
            eid_str = external_user_id(organization_id, uid)
            ok, err = send_push_to_external_user_ids([eid_str], title, body, data=payload)
            if ok:
                sent["push"] += 1
                log_delivery(
                    cursor,
                    organization_id=organization_id,
                    event_key=event_key,
                    user_id=uid,
                    channel="push",
                    status="sent",
                    payload=payload,
                )
            else:
                errors.append(f"push:{uid}:{err}")
                log_delivery(
                    cursor,
                    organization_id=organization_id,
                    event_key=event_key,
                    user_id=uid,
                    channel="push",
                    status="failed",
                    detail=err,
                    payload=payload,
                )

        if "email" in want and prefs.get("email_out", True):
            # Provider integration (Resend/SendGrid/SMTP) hooks here.
            log_delivery(
                cursor,
                organization_id=organization_id,
                event_key=event_key,
                user_id=uid,
                channel="email",
                status="queued_stub",
                detail="configure email provider",
                payload=payload,
            )
            sent["email"] += 1

        if "sms" in want and prefs.get("sms_out", True):
            log_delivery(
                cursor,
                organization_id=organization_id,
                event_key=event_key,
                user_id=uid,
                channel="sms",
                status="queued_stub",
                detail="configure SMS provider",
                payload=payload,
            )
            sent["sms"] += 1

        if "whatsapp" in want and prefs.get("whatsapp_out", False):
            log_delivery(
                cursor,
                organization_id=organization_id,
                event_key=event_key,
                user_id=uid,
                channel="whatsapp",
                status="queued_stub",
                detail="configure WhatsApp provider",
                payload=payload,
            )
            sent["whatsapp"] += 1

    return {"ok": True, "recipients": len(user_ids), "sent": sent, "errors": errors[:20]}


# -----------------------------------------------------------------------------
# Event-level notifications (apply when wiring real triggers — e.g. task reminders,
# password reset nudge). Requires: notification_event_definitions row for `event_key`,
# audiences configured in UI, and `conn.commit()` after dispatch.
#
#     from backend.notification_service import dispatch_notification_event
#
#     dispatch_notification_event(
#         cursor,
#         organization_id=org_id,
#         event_key="task.reminder",
#         title="Reminder",
#         body="You have a pending task.",
#         data={"type": "task"},
#         channels=["push", "email"],  # optional subset
#     )
#     conn.commit()
# -----------------------------------------------------------------------------
