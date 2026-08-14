"""Effective-dated employment category history and Try Out conversion.

Assignments live in user_employment_categories. Changing current category must
not delete historical Try Out periods. Dates are never invented on existing rows.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from backend.payroll_worker_categories import (
    classify_employment_category,
    convert_tryout_targets,
)


def _parse_ymd(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _row_kind(conn, employment_category_id: int) -> tuple[str, str, str]:
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT code, name FROM employment_categories WHERE id=%s LIMIT 1",
        (int(employment_category_id),),
    )
    row = c.fetchone() or {}
    code = str(row.get("code") or "")
    name = str(row.get("name") or "")
    return classify_employment_category(code, name), code, name


def validate_employment_assignments(
    conn,
    rows: list[dict],
    *,
    existing_rows: Optional[list[dict]] = None,
) -> None:
    """Validate new/edited assignments. Empty historical dates stay allowed."""
    existing_keys = set()
    for r in existing_rows or []:
        cid = r.get("employment_category_id")
        start = str(r.get("effective_from") or "")[:10]
        if cid:
            existing_keys.add((int(cid), start))

    for r in rows or []:
        if not r.get("employment_category_id"):
            continue
        cid = int(r["employment_category_id"])
        start = _parse_ymd(r.get("effective_from"))
        end = _parse_ymd(r.get("effective_to"))
        kind, _code, name = _row_kind(conn, cid)
        start_s = str(r.get("effective_from") or "").strip()[:10]
        is_new = (cid, start_s) not in existing_keys and not (
            existing_rows is None
        )
        # When existing_rows is None (create), treat populated dates as new.
        require_new = existing_rows is None or is_new or bool(start_s)

        if kind == "tryout":
            if start and end and end < start:
                raise ValueError("Try Out end date cannot be earlier than start date.")
            if require_new and (not start or not end):
                # Grandfather: existing tryout with both dates empty may remain.
                if start or end or is_new or existing_rows is None:
                    raise ValueError("Try Out requires a start date and an end date.")
        elif kind in ("w2", "contractor_1099", "temp"):
            if start and end and end < start:
                raise ValueError(f"{name or kind} end date cannot be earlier than start date.")
            if (is_new or existing_rows is None) and start_s and not start:
                raise ValueError(f"{name or kind} start date is invalid.")


def load_user_employment_assignments(conn, user_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT uec.id, uec.employment_category_id, uec.effective_from, uec.effective_to,
               ec.code, ec.name
        FROM user_employment_categories uec
        JOIN employment_categories ec ON ec.id = uec.employment_category_id
        WHERE uec.user_id=%s
        ORDER BY uec.effective_from DESC, uec.id DESC
        """,
        (int(user_id),),
    )
    rows = []
    for r in c.fetchall() or []:
        if isinstance(r, dict):
            item = dict(r)
        else:
            item = {
                "id": r[0],
                "employment_category_id": r[1],
                "effective_from": r[2],
                "effective_to": r[3],
                "code": r[4],
                "name": r[5],
            }
        item["worker_category"] = classify_employment_category(
            item.get("code"), item.get("name")
        )
        rows.append(item)
    return rows


def current_assignment(rows: list[dict], *, on: Optional[date] = None) -> Optional[dict]:
    from backend.business_time import business_today

    today = on or business_today()
    covering = []
    for r in rows:
        start = _parse_ymd(r.get("effective_from"))
        end = _parse_ymd(r.get("effective_to"))
        if start and start > today:
            continue
        if end and end < today:
            continue
        covering.append(r)
    if covering:
        covering.sort(
            key=lambda x: (_parse_ymd(x.get("effective_from")) or date.min, int(x.get("id") or 0)),
            reverse=True,
        )
        return covering[0]
    if not rows:
        return None
    ranked = sorted(
        rows,
        key=lambda x: (_parse_ymd(x.get("effective_from")) or date.min, int(x.get("id") or 0)),
        reverse=True,
    )
    return ranked[0]


def convert_tryout(
    conn,
    user_id: int,
    organization_id: int,
    *,
    new_category_id: int,
    start_date: str,
) -> list[dict]:
    """Close the current Try Out period and add a new category without duplicating the employee."""
    new_start = _parse_ymd(start_date)
    if not new_start:
        raise ValueError("A start date is required for the new category.")
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, code, name FROM employment_categories
        WHERE id=%s AND organization_id=%s LIMIT 1
        """,
        (int(new_category_id), int(organization_id)),
    )
    cat = c.fetchone()
    if not cat:
        raise ValueError("Invalid employment category")
    new_code, new_name = cat.get("code"), cat.get("name")
    new_kind = classify_employment_category(new_code, new_name)
    if new_kind not in convert_tryout_targets():
        raise ValueError("Try Out can be converted to Temp / One Time, W-2, or 1099.")

    rows = load_user_employment_assignments(conn, user_id)
    cur = current_assignment(rows)
    if not cur or cur.get("worker_category") != "tryout":
        raise ValueError("Current category is not Try Out.")

    tryout_start = _parse_ymd(cur.get("effective_from"))
    tryout_end = _parse_ymd(cur.get("effective_to"))
    if tryout_start and new_start < tryout_start:
        raise ValueError("New category start date cannot be before Try Out start date.")
    close_on = new_start - timedelta(days=1)
    if tryout_end is None or tryout_end >= new_start:
        if close_on < (tryout_start or close_on):
            raise ValueError("New category start date must be after Try Out start date.")
        c.execute(
            """
            UPDATE user_employment_categories
            SET effective_to=%s
            WHERE id=%s AND user_id=%s
            """,
            (close_on.isoformat(), int(cur["id"]), int(user_id)),
        )
    c.execute(
        """
        INSERT INTO user_employment_categories
          (user_id, employment_category_id, effective_from, effective_to)
        VALUES (%s,%s,%s,NULL)
        """,
        (int(user_id), int(new_category_id), new_start.isoformat()),
    )
    conn.commit()
    return load_user_employment_assignments(conn, user_id)
