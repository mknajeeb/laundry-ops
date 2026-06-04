"""Partner roster share links — read-only, tokenized, privacy-safe."""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime
from typing import Any, Optional

from backend.ta_helpers import json_safe, table_exists, table_has_column
from backend.ta_helpers import hash_password, verify_password


def ensure_roster_share_tables(cursor) -> None:
    if table_exists(cursor, "payroll_roster_share_links"):
        return
    import pathlib

    sql_path = pathlib.Path(__file__).resolve().parent / "sql" / "payroll_roster_share_v1.sql"
    raw = sql_path.read_text(encoding="utf-8")
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    for stmt in raw.split(";"):
        s = stmt.strip()
        if s and not s.startswith("--"):
            c.execute(s)


def _cursor(conn):
    return conn.cursor(dictionary=True)


def _parse_json_ids(val: Any) -> Optional[list[int]]:
    if val is None:
        return None
    if isinstance(val, list):
        return [int(x) for x in val if x is not None]
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [int(x) for x in parsed if x is not None]
        except json.JSONDecodeError:
            return None
    return None


def _json_ids(ids: Optional[list]) -> Optional[str]:
    if not ids:
        return None
    return json.dumps([int(x) for x in ids])


def _link_public_url(token: str) -> str:
    return f"/roster/{token}"


def list_share_links(conn, organization_id: int) -> list[dict[str, Any]]:
    ensure_roster_share_tables(conn.cursor())
    c = _cursor(conn)
    c.execute(
        """
        SELECT l.*, g.name AS location_name
        FROM payroll_roster_share_links l
        LEFT JOIN geofences g ON g.id = l.geofence_id
        WHERE l.organization_id=%s AND l.revoked_at IS NULL
        ORDER BY l.created_at DESC
        """,
        (int(organization_id),),
    )
    out = []
    for row in c.fetchall():
        r = dict(row)
        r.pop("password_hash", None)
        r["public_path"] = _link_public_url(r["token"])
        r["include_shift_ids"] = _parse_json_ids(r.get("include_shift_ids"))
        r["include_work_stream_ids"] = _parse_json_ids(r.get("include_work_stream_ids"))
        r["include_role_ids"] = _parse_json_ids(r.get("include_role_ids"))
        out.append(json_safe(r))
    return out


def create_share_link(conn, organization_id: int, body: dict, *, created_by: Optional[int] = None) -> dict:
    ensure_roster_share_tables(conn.cursor())
    oid = int(organization_id)
    token = secrets.token_urlsafe(32)
    pin = (body.get("pin") or body.get("password") or "").strip()
    pw_hash = hash_password(pin) if pin else None
    ins = conn.cursor()
    ins.execute(
        """
        INSERT INTO payroll_roster_share_links (
          organization_id, geofence_id, token, title, date_start, date_end,
          include_shift_ids, include_work_stream_ids, include_role_ids,
          show_phone, show_worker_category, show_internal_notes, show_performance,
          published_only, mode, expires_at, password_hash, active, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            oid,
            body.get("geofence_id") or body.get("location_id"),
            token,
            str(body.get("title") or "Partner Roster")[:128],
            body["date_start"],
            body["date_end"],
            _json_ids(body.get("include_shift_ids")),
            _json_ids(body.get("include_work_stream_ids")),
            _json_ids(body.get("include_role_ids")),
            1 if body.get("show_phone") else 0,
            1 if body.get("show_worker_category") else 0,
            1 if body.get("show_internal_notes") else 0,
            1 if body.get("show_performance") else 0,
            1 if body.get("published_only", True) else 0,
            str(body.get("mode") or "live")[:16],
            body.get("expires_at"),
            pw_hash,
            1 if body.get("active", True) else 0,
            created_by,
        ),
    )
    lid = int(ins.lastrowid)
    return get_share_link(conn, organization_id, lid)


def get_share_link(conn, organization_id: int, link_id: int) -> dict:
    c = _cursor(conn)
    c.execute(
        """
        SELECT l.*, g.name AS location_name
        FROM payroll_roster_share_links l
        LEFT JOIN geofences g ON g.id = l.geofence_id
        WHERE l.id=%s AND l.organization_id=%s
        """,
        (int(link_id), int(organization_id)),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Share link not found")
    r = dict(row)
    r.pop("password_hash", None)
    r["public_path"] = _link_public_url(r["token"])
    r["requires_pin"] = bool(row.get("password_hash"))
    r["include_shift_ids"] = _parse_json_ids(r.get("include_shift_ids"))
    r["include_work_stream_ids"] = _parse_json_ids(r.get("include_work_stream_ids"))
    r["include_role_ids"] = _parse_json_ids(r.get("include_role_ids"))
    return json_safe(r)


def update_share_link(conn, organization_id: int, link_id: int, body: dict) -> dict:
    ensure_roster_share_tables(conn.cursor())
    fields = []
    params = []
    for fld in (
        "title",
        "date_start",
        "date_end",
        "geofence_id",
        "show_phone",
        "show_worker_category",
        "show_internal_notes",
        "show_performance",
        "published_only",
        "mode",
        "expires_at",
        "active",
    ):
        if fld in body:
            fields.append(f"{fld}=%s")
            val = body[fld]
            if fld.startswith("show_") or fld in ("published_only", "active"):
                val = 1 if val else 0
            params.append(val)
    if "include_shift_ids" in body:
        fields.append("include_shift_ids=%s")
        params.append(_json_ids(body.get("include_shift_ids")))
    if "include_work_stream_ids" in body:
        fields.append("include_work_stream_ids=%s")
        params.append(_json_ids(body.get("include_work_stream_ids")))
    if "include_role_ids" in body:
        fields.append("include_role_ids=%s")
        params.append(_json_ids(body.get("include_role_ids")))
    pin = body.get("pin") or body.get("password")
    if pin is not None:
        pin = str(pin).strip()
        fields.append("password_hash=%s")
        params.append(hash_password(pin) if pin else None)
    if body.get("revoke"):
        fields.append("revoked_at=NOW()")
        fields.append("active=0")
    if fields:
        params.extend([int(link_id), int(organization_id)])
        conn.cursor().execute(
            f"UPDATE payroll_roster_share_links SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            tuple(params),
        )
    return get_share_link(conn, organization_id, link_id)


def revoke_share_link(conn, organization_id: int, link_id: int) -> None:
    update_share_link(conn, organization_id, link_id, {"revoke": True})


def _fetch_link_by_token(conn, token: str) -> Optional[dict]:
    ensure_roster_share_tables(conn.cursor())
    c = _cursor(conn)
    c.execute("SELECT * FROM payroll_roster_share_links WHERE token=%s LIMIT 1", (token,))
    return c.fetchone()


def _log_access(cursor, link_id: int, *, ip: Optional[str], ua: Optional[str]) -> None:
    if not table_exists(cursor, "payroll_roster_share_access_log"):
        return
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    c.execute(
        """
        INSERT INTO payroll_roster_share_access_log (share_link_id, ip_address, user_agent)
        VALUES (%s,%s,%s)
        """,
        (int(link_id), (ip or "")[:64] or None, (ua or "")[:512] or None),
    )
    c.execute(
        "UPDATE payroll_roster_share_links SET last_accessed_at=NOW() WHERE id=%s",
        (int(link_id),),
    )


def verify_roster_pin(conn, token: str, pin: str) -> bool:
    row = _fetch_link_by_token(conn, token)
    if not row or not row.get("password_hash"):
        return False
    return verify_password(row["password_hash"], pin)


def get_public_roster(
    conn,
    token: str,
    *,
    pin: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    row = _fetch_link_by_token(conn, token)
    if not row:
        raise ValueError("This schedule link is invalid.")
    if row.get("revoked_at") or not row.get("active"):
        raise ValueError("This schedule link has been revoked.")
    if row.get("expires_at"):
        exp = row["expires_at"]
        if isinstance(exp, datetime) and exp < datetime.utcnow():
            raise ValueError("This schedule link has expired.")
    if row.get("password_hash"):
        if not pin or not verify_password(row["password_hash"], pin):
            return {
                "requires_pin": True,
                "title": row.get("title"),
                "message": "Enter the PIN provided by your contact.",
            }
    oid = int(row["organization_id"])
    c = _cursor(conn)
    c.execute("SELECT display_name, slug FROM organizations WHERE id=%s LIMIT 1", (oid,))
    org = c.fetchone() or {}
    location_name = None
    if row.get("geofence_id"):
        c.execute("SELECT name FROM geofences WHERE id=%s LIMIT 1", (int(row["geofence_id"]),))
        location_name = (c.fetchone() or {}).get("name")

    publish_filter = " AND e.publish_status='published'" if row.get("published_only") else ""
    shift_ids = _parse_json_ids(row.get("include_shift_ids"))
    stream_ids = _parse_json_ids(row.get("include_work_stream_ids"))
    role_ids = _parse_json_ids(row.get("include_role_ids"))

    q = """
        SELECT e.work_date, e.start_time, e.end_time, e.status,
               s.name AS shift_name, ws.name AS work_stream_name, r.name AS role_name,
               COALESCE(NULLIF(TRIM(CONCAT(pp.first_name,' ',pp.last_name)), ''), u.username) AS worker_name,
               pp.mobile AS worker_phone,
               p.worker_category
        FROM payroll_schedule_entries e
        JOIN payroll_worker_profiles p ON p.id=e.worker_profile_id
        JOIN users u ON u.id=p.user_id
        LEFT JOIN payroll_profiles pp ON pp.user_id=u.id
        JOIN payroll_shifts s ON s.id=e.shift_id
        LEFT JOIN payroll_work_streams ws ON ws.id=e.work_stream_id
        LEFT JOIN payroll_roles r ON r.id=e.role_id
        WHERE e.organization_id=%s
          AND e.work_date BETWEEN %s AND %s
          AND e.status NOT IN ('cancelled', 'replaced')
    """
    params: list[Any] = [oid, row["date_start"], row["date_end"]]
    q += publish_filter
    if shift_ids:
        q += f" AND e.shift_id IN ({','.join(['%s'] * len(shift_ids))})"
        params.extend(shift_ids)
    if stream_ids:
        q += f" AND e.work_stream_id IN ({','.join(['%s'] * len(stream_ids))})"
        params.extend(stream_ids)
    if role_ids:
        q += f" AND e.role_id IN ({','.join(['%s'] * len(role_ids))})"
        params.extend(role_ids)
    if row.get("geofence_id"):
        q += " AND (e.geofence_id=%s OR e.geofence_id IS NULL)"
        params.append(int(row["geofence_id"]))
    q += " ORDER BY e.work_date, s.sort_order, e.start_time"
    c.execute(q, tuple(params))
    rows = list(c.fetchall() or [])

    grouped: dict[str, dict[str, list]] = {}
    for r in rows:
        d = str(r["work_date"])[:10]
        shift = r.get("shift_name") or "Shift"
        grouped.setdefault(d, {})
        grouped[d].setdefault(shift, [])
        item = {
            "worker_name": r.get("worker_name"),
            "role": r.get("role_name"),
            "work_stream": r.get("work_stream_name"),
            "start_time": str(r.get("start_time") or "")[:5],
            "end_time": str(r.get("end_time") or "")[:5],
            "status": str(r.get("status") or "scheduled").replace("_", " ").title(),
        }
        if row.get("show_phone") and r.get("worker_phone"):
            item["phone"] = r.get("worker_phone")
        if row.get("show_worker_category"):
            item["worker_category"] = r.get("worker_category")
        grouped[d][shift].append(item)

    _log_access(conn.cursor(), int(row["id"]), ip=ip, ua=user_agent)

    return json_safe(
        {
            "requires_pin": False,
            "read_only": True,
            "title": row.get("title"),
            "organization_name": org.get("display_name"),
            "location_name": location_name,
            "date_start": str(row["date_start"])[:10],
            "date_end": str(row["date_end"])[:10],
            "mode": row.get("mode") or "live",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "grouped_by_date": grouped,
            "disclaimer": "Read-only roster. For scheduling reference only.",
        }
    )
