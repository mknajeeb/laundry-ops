"""Step-1 HD manager review bridge — isolated from WF / Employee Productivity.

Reuses ``daily_operations_hd`` production facts (total_items/revenue/washed_by/
folded_by) without changing Supply Usage, WF classify, or Phase 1D labor.

Step-1 vocabulary:
  REVIEW_REQUIRED  ↔ production NOT_RECORDED / PARTIALLY_RECORDED (or missing)
  COMPLETED        ↔ production COMPLETE

Aliases accepted at the Step-1 boundary:
  item_count → total_items
  total_revenue → revenue
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from backend.daily_operations_hd import (
    STATUS_COMPLETE,
    STATUS_NOT_RECORDED,
    STATUS_PARTIALLY_RECORDED,
    compute_hd_day_revenue_totals,
    ensure_hd_production_tables,
    get_hd_production_row,
    list_org_employee_options,
    save_hd_production,
    undo_hd_production,
)
from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists

MONEY_Q = Decimal("0.01")

STEP1_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STEP1_COMPLETED = "COMPLETED"

REASON_HD_COMPLETION_DETAILS_MISSING = "COMPLETION_DETAILS_MISSING"

# Authoritative production fields required before HD may be COMPLETED.
HD_COMPLETED_REQUIRED_FIELDS = (
    "item_count",
    "total_revenue",
    "washed_by_user_id",
    "folded_by_user_id",
)


def map_production_status_to_step1(status: str | None) -> str:
    s = str(status or STATUS_NOT_RECORDED).strip().upper()
    if s == STATUS_COMPLETE:
        return STEP1_COMPLETED
    return STEP1_REVIEW_REQUIRED


def _hd_record_claims_completed(record: Mapping[str, Any] | None) -> bool:
    if not isinstance(record, Mapping):
        return False
    status = str(
        record.get("status") or record.get("production_status") or ""
    ).strip().upper()
    review = str(record.get("review_status") or "").strip().upper()
    return status == STATUS_COMPLETE or review == STEP1_COMPLETED


def hd_completed_authoritative_field_violations(
    record: Mapping[str, Any] | None,
) -> list[str]:
    """
    Business rule: HD COMPLETED ⇒ all authoritative production fields present.

    Required: item_count, total_revenue, washed_by_user_id, folded_by_user_id.
    Blank/missing fails; intentional zeros are valid when the field is present.

    Returns missing field names when the record claims COMPLETE/COMPLETED.
    Non-complete records return [] (invariant does not apply).
    """
    if not _hd_record_claims_completed(record):
        return []
    assert isinstance(record, Mapping)
    missing: list[str] = []
    items = record.get("item_count", record.get("total_items"))
    revenue = record.get("total_revenue", record.get("revenue"))
    washed = record.get("washed_by_user_id")
    folded = record.get("folded_by_user_id")
    if items is None:
        missing.append("item_count")
    if revenue is None:
        missing.append("total_revenue")
    if washed in (None, ""):
        missing.append("washed_by_user_id")
    if folded in (None, ""):
        missing.append("folded_by_user_id")
    return missing


def assert_hd_completed_implies_authoritative_fields(
    record: Mapping[str, Any] | None,
) -> None:
    """Raise AssertionError if COMPLETED lacks any authoritative production field."""
    missing = hd_completed_authoritative_field_violations(record)
    assert not missing, (
        "HD COMPLETED requires item_count, total_revenue, washed_by_user_id, "
        f"and folded_by_user_id; missing={missing}"
    )


def is_authoritative_hd_complete(fact: Mapping[str, Any] | None) -> bool:
    """True only when production status is COMPLETE and all four fields exist."""
    if not isinstance(fact, Mapping):
        return False
    if str(fact.get("status") or "").strip().upper() != STATUS_COMPLETE:
        return False
    return not hd_completed_authoritative_field_violations(fact)


def quantize_hd_revenue(value: Any) -> Decimal | None:
    """Blank → None; otherwise Decimal with ROUND_HALF_UP to cents."""
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    except Exception:
        raise ValueError("invalid_total_revenue") from None
    if amount < 0:
        raise ValueError("negative_total_revenue")
    return amount


def parse_hd_item_count(value: Any) -> int | None:
    """Blank → None; otherwise non-negative whole number."""
    if value is None or str(value).strip() == "":
        return None
    try:
        # Reject true floats like 1.5; allow "0", "3", 3.
        raw = str(value).strip()
        if "." in raw and not raw.replace(".", "", 1).isdigit():
            raise ValueError("invalid_item_count")
        n = int(Decimal(raw))
        if Decimal(raw) != Decimal(n):
            raise ValueError("invalid_item_count")
    except ValueError as exc:
        msg = str(exc)
        if msg in ("invalid_item_count", "negative_item_count"):
            raise
        raise ValueError("invalid_item_count") from exc
    except Exception as exc:
        raise ValueError("invalid_item_count") from exc
    if n < 0:
        raise ValueError("negative_item_count")
    return n


def _alias_payload(body: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(body or {})
    if "item_count" in out and out.get("total_items") is None:
        out["total_items"] = out.get("item_count")
    if "total_revenue" in out and out.get("revenue") is None:
        out["revenue"] = out.get("total_revenue")
    return out


def _employee_is_active_org_member(cursor, organization_id: int, user_id: int) -> bool:
    if not table_exists(cursor, "users"):
        return False
    has_active = False
    try:
        from backend.ta_helpers import table_has_column

        has_active = table_has_column(cursor, "users", "active")
    except Exception:
        has_active = False
    sql = "SELECT id FROM users WHERE id = %s AND organization_id = %s"
    if has_active:
        sql += " AND COALESCE(active, 1) = 1"
    sql += " LIMIT 1"
    cursor.execute(sql, (int(user_id), int(organization_id)))
    return bool(cursor.fetchone())


def list_hd_review_employee_options(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Active org employees only — no External / free-text option for Step-1."""
    opts = list_org_employee_options(cursor, organization_id)
    return [o for o in opts if not o.get("is_external") and o.get("user_id")]


def load_prior_completed_hd_bag_ids(
    cursor,
    organization_id: int,
    *,
    before_date: date,
) -> set[str]:
    """Bag ids with a COMPLETE HD review on any prior operations date."""
    ensure_hd_production_tables(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return set()
    cursor.execute(
        """
        SELECT DISTINCT bag_id
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND operations_date_et < %s
          AND status = %s
        """,
        (int(organization_id), before_date, STATUS_COMPLETE),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out.add(bid)
    return out


def load_hd_production_status_map(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    ensure_hd_production_tables(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return {}
    ids = sorted({normalize_bag_id(b) for b in (bag_ids or []) if normalize_bag_id(b)})
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT *
            FROM hd_day_bag_production
            WHERE organization_id = %s
              AND operations_date_et = %s
              AND bag_id IN ({ph})
            """,
            (int(organization_id), operations_date_et, *ids),
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM hd_day_bag_production
            WHERE organization_id = %s AND operations_date_et = %s
            """,
            (int(organization_id), operations_date_et),
        )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out[bid] = dict(row)
    return out


def public_hd_review_fact(fact: Mapping[str, Any] | None) -> dict[str, Any]:
    """Step-1 facing production fact (aliases + review status)."""
    if not fact:
        return {
            "review_status": STEP1_REVIEW_REQUIRED,
            "production_status": STATUS_NOT_RECORDED,
            "item_count": None,
            "total_items": None,
            "total_revenue": None,
            "revenue": None,
            "washed_by_user_id": None,
            "washed_by_name_snapshot": None,
            "folded_by_user_id": None,
            "folded_by_name_snapshot": None,
            "version": 0,
            "included_in_authoritative_totals": False,
        }
    raw_status = str(fact.get("status") or STATUS_NOT_RECORDED)
    rev = fact.get("revenue")
    items = fact.get("total_items")
    # Incomplete COMPLETE rows cannot surface as Step-1 COMPLETED.
    if (
        raw_status.upper() == STATUS_COMPLETE
        and hd_completed_authoritative_field_violations(
            {
                "status": STATUS_COMPLETE,
                "total_items": items,
                "revenue": rev,
                "washed_by_user_id": fact.get("washed_by_user_id"),
                "folded_by_user_id": fact.get("folded_by_user_id"),
            }
        )
    ):
        status = STATUS_PARTIALLY_RECORDED
    else:
        status = raw_status
    return {
        "review_status": map_production_status_to_step1(status),
        "production_status": status,
        "item_count": int(items) if items is not None else None,
        "total_items": int(items) if items is not None else None,
        "total_revenue": float(rev) if rev is not None else None,
        "revenue": float(rev) if rev is not None else None,
        "washed_by_user_id": fact.get("washed_by_user_id"),
        "washed_by_name_snapshot": fact.get("washed_by_name_snapshot"),
        "folded_by_user_id": fact.get("folded_by_user_id"),
        "folded_by_name_snapshot": fact.get("folded_by_name_snapshot"),
        "notes": fact.get("notes"),
        "version": int(fact.get("version") or 0),
        "included_in_authoritative_totals": status == STATUS_COMPLETE,
        "updated_at": fact.get("updated_at"),
    }


def validate_step1_hd_completion_fields(fields: Mapping[str, Any]) -> list[str]:
    """
    Completion gate for Step-1 HD review.

    Blank = incomplete. Zero is valid when the field is present.
    Washed By / Folded By require org employee user ids (no free-text).
    """
    errors: list[str] = []
    try:
        items = parse_hd_item_count(fields.get("item_count", fields.get("total_items")))
    except ValueError as exc:
        errors.append(str(exc) or "invalid_item_count")
        items = None
    try:
        rev = quantize_hd_revenue(fields.get("total_revenue", fields.get("revenue")))
    except ValueError as exc:
        errors.append(str(exc) or "invalid_total_revenue")
        rev = None

    washed = fields.get("washed_by_user_id")
    folded = fields.get("folded_by_user_id")
    if washed in (None, "", "external_unknown"):
        errors.append("washed_by_required")
    if folded in (None, "", "external_unknown"):
        errors.append("folded_by_required")
    if items is None:
        errors.append("item_count_required")
    if rev is None:
        errors.append("total_revenue_required")
    return errors


def save_step1_hd_review(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    """
    Save HD review fields via daily_operations_hd.save_hd_production.

    When ``require_complete`` is True (Mark Completed), all four fields must be set.
    Intentional zeros auto-attach MANAGER_OVERRIDE so existing Phase 1C validators
    accept them without changing shared zero-reason rules.
    """
    body = _alias_payload(payload)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}

    # Reject free-text / external for Step-1.
    if body.get("washed_by_external") or body.get("washed_by_override_name"):
        return {
            "ok": False,
            "error": "validation_failed",
            "errors": ["washed_by_free_text_not_allowed"],
        }
    if body.get("folded_by_external") or body.get("folded_by_override_name"):
        return {
            "ok": False,
            "error": "validation_failed",
            "errors": ["folded_by_free_text_not_allowed"],
        }

    try:
        items = parse_hd_item_count(body.get("total_items"))
        rev = quantize_hd_revenue(body.get("revenue"))
    except ValueError as exc:
        return {"ok": False, "error": "validation_failed", "errors": [str(exc)]}

    if require_complete:
        gate = validate_step1_hd_completion_fields(
            {
                "item_count": items,
                "total_revenue": rev,
                "washed_by_user_id": body.get("washed_by_user_id"),
                "folded_by_user_id": body.get("folded_by_user_id"),
            }
        )
        if gate:
            return {"ok": False, "error": "validation_failed", "errors": gate}

    existing = get_hd_production_row(cursor, organization_id, operations_date_et, bid)
    for role in ("washed", "folded"):
        raw = body.get(f"{role}_by_user_id")
        if raw in (None, ""):
            continue
        try:
            uid = int(raw)
        except Exception:
            return {
                "ok": False,
                "error": "validation_failed",
                "errors": [f"{role}_by_invalid_user_id"],
            }
        if not _employee_is_active_org_member(cursor, organization_id, uid):
            # Historical retain: same inactive id already on the record is OK.
            prev = None
            if existing:
                try:
                    prev = (
                        int(existing.get(f"{role}_by_user_id"))
                        if existing.get(f"{role}_by_user_id") is not None
                        else None
                    )
                except Exception:
                    prev = None
            if prev != uid:
                return {
                    "ok": False,
                    "error": "validation_failed",
                    "errors": [f"{role}_by_inactive_or_cross_org"],
                }

    save_body = {
        "version": body.get("version", 0),
        "reason": str(body.get("reason") or "").strip()
        or ("step1_hd_mark_completed" if require_complete else "step1_hd_review_save"),
        "notes": body.get("notes"),
        "washed_by_user_id": body.get("washed_by_user_id") or None,
        "folded_by_user_id": body.get("folded_by_user_id") or None,
        "washed_by_external": False,
        "folded_by_external": False,
        "total_items": items,
        "revenue": float(rev) if rev is not None else None,
        # Save Review keeps REVIEW_REQUIRED until Mark Completed confirms.
        "defer_complete": not require_complete,
        # Intentional zero: satisfy existing Phase 1C zero-reason validators.
        "zero_items_reason_code": (
            body.get("zero_items_reason_code")
            or ("MANAGER_OVERRIDE" if items == 0 else None)
        ),
        "zero_items_reason_note": body.get("zero_items_reason_note")
        or ("Intentional zero items" if items == 0 else None),
        "zero_revenue_reason_code": (
            body.get("zero_revenue_reason_code")
            or ("MANAGER_OVERRIDE" if rev == Decimal("0.00") else None)
        ),
        "zero_revenue_reason_note": body.get("zero_revenue_reason_note")
        or ("Intentional zero revenue" if rev == Decimal("0.00") else None),
    }

    out = save_hd_production(
        cursor,
        organization_id,
        operations_date_et,
        bid,
        save_body,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )
    if not out.get("ok"):
        return out

    fact = (out.get("production") or out.get("record") or {}).get("status")
    # Normalize public shape
    prod = out.get("production") or out.get("record") or get_hd_production_row(
        cursor, organization_id, operations_date_et, bid
    )
    public = public_hd_review_fact(prod if isinstance(prod, dict) else None)
    return {
        **out,
        "ok": True,
        "bag_id": bid,
        "review": public,
        "review_status": public["review_status"],
        "step1_outcome": (
            "completed" if public["review_status"] == STEP1_COMPLETED else "review_required"
        ),
    }


def undo_step1_hd_review(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    out = undo_hd_production(
        cursor,
        organization_id,
        operations_date_et,
        bag_id,
        reason=reason or "step1_hd_review_undo",
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )
    if not out.get("ok"):
        return out
    prod = out.get("production") or out.get("record") or get_hd_production_row(
        cursor, organization_id, operations_date_et, normalize_bag_id(bag_id)
    )
    public = public_hd_review_fact(prod if isinstance(prod, dict) else None)
    return {
        **out,
        "review": public,
        "review_status": public["review_status"],
        "step1_outcome": (
            "completed" if public["review_status"] == STEP1_COMPLETED else "review_required"
        ),
    }


def build_hd_dashboard_totals(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    hd_segment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    HD section totals for Step-1.

    Total Items / Total Revenue include only manager-COMPLETED reviews.
    """
    seg = hd_segment or {}
    bags = seg.get("bag_ids") or {}
    total_orders = int(
        seg.get("total_workload")
        or seg.get("active_workload")
        or (len(bags.get("new_today") or []) + len(bags.get("carryover") or []))
    )
    review_n = int((seg.get("exceptions") or {}).get("review_required") or seg.get("pending") or 0)
    # Prefer explicit completed count from segment after HD review policy.
    completed_n = int(seg.get("completed") or 0)
    if review_n == 0 and completed_n == 0 and total_orders:
        # Fall back to bag lists.
        review_n = len(bags.get("review_required") or [])
        completed_n = len(bags.get("completed") or [])

    rev = compute_hd_day_revenue_totals(cursor, organization_id, operations_date_et)
    hd_revenue = rev.get("complete_hd_revenue") or rev.get("total_hd_revenue") or 0.0
    return {
        "total_hd_orders": total_orders,
        "review_required": review_n,
        "completed": completed_n,
        "total_items": int(rev.get("complete_total_items") or 0),
        "total_revenue": hd_revenue,
        "hd_revenue": hd_revenue,
        # Authoritative source note for UI.
        "totals_source": "manager_completed_hd_reviews_only",
    }


def apply_hd_review_status_to_summary(
    summary: Mapping[str, Any],
    *,
    production_by_bag: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Force HD workload into REVIEW_REQUIRED until production COMPLETE.

    Does not mutate WF / wf_rush / wf_non_rush segments.
    """
    out = deepcopy(dict(summary or {}))
    segments = dict(out.get("segments") or {})
    hd_keys = ("hd", "hd_rush", "hd_non_rush")

    def _rewrite(seg: Mapping[str, Any]) -> dict[str, Any]:
        s = dict(seg or {})
        bags = dict(s.get("bag_ids") or {})
        universe: set[str] = set()
        for key in ("new_today", "carryover", "completed", "pending", "review_required"):
            for raw in bags.get(key) or []:
                bid = normalize_bag_id(raw)
                if bid:
                    universe.add(bid)
        completed: list[str] = []
        review: list[str] = []
        for bid in sorted(universe):
            fact = production_by_bag.get(bid) or {}
            if is_authoritative_hd_complete(fact):
                completed.append(bid)
            else:
                review.append(bid)
        bags["completed"] = completed
        bags["pending"] = []
        bags["review_required"] = review
        bags["disappeared_without_completion"] = list(review)
        # Keep new_today as membership; clear carryover (caller may already have).
        bags["carryover"] = []
        bags["new_today"] = sorted(universe)
        s["bag_ids"] = bags
        s["new_today"] = len(bags["new_today"])
        s["carryover"] = 0
        s["completed"] = len(completed)
        s["pending"] = 0
        s["active_workload"] = len(universe)
        s["total_workload"] = len(universe)
        s["exceptions"] = {
            **dict(s.get("exceptions") or {}),
            "review_required": len(review),
            "disappeared_without_completion": len(review),
            "total": len(review),
        }
        return s

    for key in hd_keys:
        if key in segments:
            segments[key] = _rewrite(segments[key])

    # Rebuild combined all/rush/non_rush HD portions carefully: only adjust HD bags
    # inside combined segments by moving HD bags between completed/review.
    hd_universe = set((segments.get("hd") or {}).get("bag_ids", {}).get("new_today") or [])
    hd_completed = set((segments.get("hd") or {}).get("bag_ids", {}).get("completed") or [])
    hd_review = set((segments.get("hd") or {}).get("bag_ids", {}).get("review_required") or [])

    for key in ("all", "rush", "non_rush"):
        if key not in segments:
            continue
        seg = dict(segments[key] or {})
        bags = dict(seg.get("bag_ids") or {})
        # Remove HD bags from completed/pending/review then re-add by policy.
        for bucket in ("completed", "pending", "review_required", "disappeared_without_completion"):
            bags[bucket] = [
                b
                for b in (bags.get(bucket) or [])
                if normalize_bag_id(b) not in hd_universe
            ]
        bags["completed"] = sorted(
            {normalize_bag_id(b) for b in (bags.get("completed") or []) if normalize_bag_id(b)}
            | hd_completed
        )
        bags["review_required"] = sorted(
            {normalize_bag_id(b) for b in (bags.get("review_required") or []) if normalize_bag_id(b)}
            | hd_review
        )
        bags["disappeared_without_completion"] = list(bags["review_required"])
        # Strip HD from pending — HD uses review until complete.
        bags["pending"] = [
            b for b in (bags.get("pending") or []) if normalize_bag_id(b) not in hd_universe
        ]
        seg["bag_ids"] = bags
        seg["completed"] = len(bags["completed"])
        seg["pending"] = len(bags["pending"])
        seg["exceptions"] = {
            **dict(seg.get("exceptions") or {}),
            "review_required": len(bags["review_required"]),
            "total": len(bags["review_required"]),
        }
        segments[key] = seg

    out["segments"] = segments
    out["hd_review_policy"] = {
        "every_hd_order_starts_review_required": True,
        "completed_requires_manager_fields": [
            "item_count",
            "total_revenue",
            "washed_by_user_id",
            "folded_by_user_id",
        ],
    }
    return out


def exclude_prior_completed_hd_from_summary(
    summary: Mapping[str, Any],
    prior_completed_ids: set[str],
) -> dict[str, Any]:
    """Remove prior-day COMPLETED HD order instances from today's HD membership."""
    if not prior_completed_ids:
        return dict(summary or {})
    out = deepcopy(dict(summary or {}))
    segments = dict(out.get("segments") or {})
    remove = set(prior_completed_ids)

    def _strip(seg: Mapping[str, Any]) -> dict[str, Any]:
        s = dict(seg or {})
        bags = dict(s.get("bag_ids") or {})
        for key, vals in list(bags.items()):
            bags[key] = [b for b in (vals or []) if normalize_bag_id(b) not in remove]
        s["bag_ids"] = bags
        for key in ("new_today", "carryover", "completed", "pending"):
            s[key] = len(bags.get(key) or [])
        review = bags.get("review_required") or []
        s["exceptions"] = {
            **dict(s.get("exceptions") or {}),
            "review_required": len(review),
            "disappeared_without_completion": len(review),
            "total": len(review),
        }
        active = len(bags.get("new_today") or []) + len(bags.get("carryover") or [])
        s["active_workload"] = active
        s["total_workload"] = active
        return s

    for key in ("hd", "hd_rush", "hd_non_rush", "all", "rush", "non_rush"):
        if key in segments:
            # For WF-only keys we still strip HD prior-completed from combined lists;
            # WF segment keys are not in this loop.
            segments[key] = _strip(segments[key])

    out["segments"] = segments
    out["hd_prior_completed_excluded"] = {
        "count": len(remove),
        "bag_ids": sorted(remove),
        "rule": "prior_hd_review_status_completed_excludes_later_day_membership",
    }
    return out
