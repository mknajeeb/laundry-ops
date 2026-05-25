"""Folding exception review actions and search (Phase 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_folding import SOURCE_MANUAL
from backend.rinse_folding_registry import (
    ensure_rinse_folding_tables,
    get_folding_performance_row,
    list_folding_performance_overrides,
    list_folding_performance_rows,
)
from backend.rinse_folding_scoring import (
    SCORING_APPROVED,
    SCORING_EXCLUDED,
    SCORING_EXCEPTION,
    scoring_fields_from_compute,
)
def exception_reason_plain_english(code: str | None) -> str:
    from backend.rinse_order_search_detail import FOLDING_CODE_LABELS

    c = str(code or "").strip()
    if not c:
        return ""
    return FOLDING_CODE_LABELS.get(c, c.replace("_", " ").lower())


def enrich_exception_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        code = r.get("exception_code")
        r["plain_english_reason"] = exception_reason_plain_english(code)
        r["included_in_scoring"] = bool(int(r.get("included_in_scoring") or 0))
        r["reviewed"] = r.get("reviewed_at") is not None
        scoring = str(r.get("scoring_status") or r.get("status") or "").upper()
        r["approved_for_scoring"] = scoring == SCORING_APPROVED
        out.append(r)
    return out


def search_folding_exceptions(
    cursor,
    organization_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Exception queue with full filters."""
    kwargs = dict(kwargs)
    kwargs.setdefault("exception_only", True)
    payload = list_folding_performance_rows(
        cursor,
        organization_id,
        limit=limit,
        offset=offset,
        include_total=True,
        **kwargs,
    )
    if isinstance(payload, dict):
        payload["rows"] = enrich_exception_rows(payload.get("rows") or [])
    return payload


def _log_review_action(
    cursor,
    organization_id: int,
    perf_id: int,
    bag_id: str,
    field_name: str,
    old_val: Any,
    new_val: Any,
    *,
    actor_user_id: int | None,
    notes: str | None,
    action_type: str,
) -> int:
    from backend.rinse_folding_registry import _serialize_override_value

    note_text = f"[{action_type}]"
    if notes:
        note_text = f"{note_text} {notes}"
    cursor.execute(
        """
        INSERT INTO rinse_folding_performance_overrides (
            organization_id, performance_id, bag_id,
            field_name, old_value, new_value, actor_user_id, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            int(perf_id),
            bag_id,
            field_name,
            _serialize_override_value(old_val),
            _serialize_override_value(new_val),
            actor_user_id,
            note_text[:2000] if note_text else None,
        ),
    )
    return int(cursor.lastrowid or 0)


def mark_exception_reviewed(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    actor_user_id: int | None,
    note: str | None = None,
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    row = get_folding_performance_row(cursor, org, bid)
    if not row:
        raise ValueError("Performance row not found")
    perf_id = int(row["id"])
    now = datetime.utcnow()
    old_reviewed = row.get("reviewed_at")
    cursor.execute(
        """
        UPDATE rinse_folding_performance
        SET reviewed_at = %s, reviewed_by_user_id = %s,
            exception_review_note = COALESCE(%s, exception_review_note),
            updated_at = NOW()
        WHERE id = %s AND organization_id = %s
        """,
        (now, actor_user_id, (note or "").strip() or None, perf_id, org),
    )
    _log_review_action(
        cursor, org, perf_id, bid, "reviewed_at", old_reviewed, now,
        actor_user_id=actor_user_id, notes=note, action_type="MARK_REVIEWED",
    )
    return {"bag_id": bid, "performance_id": perf_id, "reviewed_at": now}


def approve_exception_for_scoring(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    actor_user_id: int | None,
    note: str | None = None,
) -> dict[str, Any]:
    """Approve former exception for gaming; keep exception_code for audit."""
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    row = get_folding_performance_row(cursor, org, bid)
    if not row:
        raise ValueError("Performance row not found")
    perf_id = int(row["id"])
    old_scoring = row.get("scoring_status")
    old_included = row.get("included_in_scoring")
    now = datetime.utcnow()
    cursor.execute(
        """
        UPDATE rinse_folding_performance
        SET scoring_status = %s,
            included_in_scoring = 1,
            excluded_from_performance = 0,
            reviewed_at = COALESCE(reviewed_at, %s),
            reviewed_by_user_id = COALESCE(reviewed_by_user_id, %s),
            exception_review_note = COALESCE(%s, exception_review_note),
            updated_at = NOW()
        WHERE id = %s AND organization_id = %s
        """,
        (
            SCORING_APPROVED,
            now,
            actor_user_id,
            (note or "").strip() or None,
            perf_id,
            org,
        ),
    )
    _log_review_action(
        cursor, org, perf_id, bid, "scoring_status", old_scoring, SCORING_APPROVED,
        actor_user_id=actor_user_id, notes=note, action_type="APPROVE_SCORING",
    )
    _log_review_action(
        cursor, org, perf_id, bid, "included_in_scoring", old_included, 1,
        actor_user_id=actor_user_id, notes=note, action_type="APPROVE_SCORING",
    )
    updated = get_folding_performance_row(cursor, org, bid)
    return {
        "bag_id": bid,
        "performance_id": perf_id,
        "row": updated,
        "scoring_status": SCORING_APPROVED,
        "included_in_scoring": True,
        "exception_code": (updated or {}).get("exception_code"),
    }


def exclude_exception_from_scoring(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    actor_user_id: int | None,
    note: str | None = None,
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    row = get_folding_performance_row(cursor, org, bid)
    if not row:
        raise ValueError("Performance row not found")
    perf_id = int(row["id"])
    old_ex = row.get("excluded_from_performance")
    old_scoring = row.get("scoring_status")
    cursor.execute(
        """
        UPDATE rinse_folding_performance
        SET excluded_from_performance = 1,
            scoring_status = %s,
            included_in_scoring = 0,
            exception_review_note = COALESCE(%s, exception_review_note),
            updated_at = NOW()
        WHERE id = %s AND organization_id = %s
        """,
        (
            SCORING_EXCLUDED,
            (note or "").strip() or None,
            perf_id,
            org,
        ),
    )
    _log_review_action(
        cursor, org, perf_id, bid, "excluded_from_performance", old_ex, 1,
        actor_user_id=actor_user_id, notes=note, action_type="EXCLUDE_SCORING",
    )
    _log_review_action(
        cursor, org, perf_id, bid, "scoring_status", old_scoring, SCORING_EXCLUDED,
        actor_user_id=actor_user_id, notes=note, action_type="EXCLUDE_SCORING",
    )
    return {"bag_id": bid, "performance_id": perf_id, "row": get_folding_performance_row(cursor, org, bid)}


def apply_review_override(
    cursor,
    organization_id: int,
    bag_id: str,
    payload: dict[str, Any],
    *,
    actor_user_id: int | None,
) -> dict[str, Any]:
    """Reassign user / override times / admin note via existing override helper."""
    from backend.rinse_folding_registry import apply_performance_override

    out = apply_performance_override(
        cursor, organization_id, bag_id, payload, actor_user_id=actor_user_id
    )
    row = out.get("row") or {}
    if row and str(row.get("status") or "").upper() == "CALCULATED":
        scoring = scoring_fields_from_compute(
            status=row.get("status"),
            exception_code=row.get("exception_code"),
            existing=row,
            preserve_review=True,
        )
        perf_id = int(row["id"])
        org = int(organization_id)
        bid = normalize_bag_id(bag_id)
        cursor.execute(
            """
            UPDATE rinse_folding_performance
            SET scoring_status = %s, included_in_scoring = %s, updated_at = NOW()
            WHERE id = %s AND organization_id = %s
            """,
            (
                scoring["scoring_status"],
                scoring["included_in_scoring"],
                perf_id,
                org,
            ),
        )
        out["row"] = get_folding_performance_row(cursor, org, bid)
    return out
