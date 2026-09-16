"""Management Issues Phase 1 — internal quality / claims (not WF Review).

INTERNAL mgmt_issues != future Rinse-published issues.
Narrow canonical reads only; no CW / Review / DFP builders.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from backend.business_time import business_now, business_today, system_datetime_to_et
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start
from backend.ta_helpers import table_exists, table_has_column

ISSUES_TABLE = "mgmt_issues"
ATTR_TABLE = "mgmt_issue_attributions"
EVENTS_TABLE = "mgmt_issue_events"
TAXONOMY_TABLE = "mgmt_issue_taxonomy"

MATCHED = "MATCHED"
UNMATCHED = "UNMATCHED"

STATUSES = frozenset({"open", "investigating", "resolved", "excluded"})
SEVERITIES = frozenset({"low", "medium", "high", "critical"})

ROLE_FOLDER = "folder"
ROLE_COMPLETION = "completion"
ROLE_HD_WASH = "hd_wash"
ROLE_HD_FOLD = "hd_fold"
ROLE_SORTER = "sorter"
ROLE_WASHER = "wf_washer"
ROLE_DRYER = "wf_dryer"

RATE_READY_ROLES = frozenset({ROLE_FOLDER, ROLE_HD_WASH, ROLE_HD_FOLD})

CATEGORY_SEEDS = [
    ("MISSING", "Missing", 10),
    ("FOUND", "Found", 20),
    ("DAMAGE", "Damage", 30),
    ("RECLEAN", "Reclean", 40),
    ("REJECTED", "Rejected", 50),
    ("MIXED_CUSTOMER_ITEMS", "Mixed Items", 60),
    ("QUALITY", "Quality", 70),
    ("OTHER", "Other", 80),
]

SUBTYPE_SEEDS = [
    ("MISSING", "MISSING_FULL_BAG", "Missing full bag", 10),
    ("MISSING", "MISSING_ITEM", "Missing item", 20),
    ("FOUND", "WRONG_CUSTOMER_ITEM", "Wrong customer item", 10),
    ("FOUND", "FOUND_OTHER", "Found — other", 20),
    ("DAMAGE", "GARMENT_DAMAGE", "Garment damage", 10),
    ("DAMAGE", "COLOR_BLEED", "Color bleed", 20),
    ("DAMAGE", "STAIN", "Stain", 30),
    ("RECLEAN", "WET_CLOTHES", "Wet clothes", 10),
    ("RECLEAN", "DIRTY_NOT_CLEANED", "Dirty / not cleaned", 20),
    ("REJECTED", "REJECTED_GENERAL", "Rejected", 10),
    ("MIXED_CUSTOMER_ITEMS", "MIXED_ITEMS", "Mixed items", 10),
    ("QUALITY", "PACKAGING", "Packaging", 10),
    ("QUALITY", "QUALITY_OTHER", "Quality — other", 20),
    ("OTHER", "OTHER", "Other", 10),
]

_ENSURED: set[int] = set()
_TABLE_CACHE: dict[str, bool] = {}
_COLUMN_CACHE: dict[tuple[str, str], bool] = {}


def _cached_table_exists(cursor, name: str) -> bool:
    if name not in _TABLE_CACHE:
        _TABLE_CACHE[name] = bool(table_exists(cursor, name))
    return _TABLE_CACHE[name]


def _cached_column(cursor, table: str, col: str) -> bool:
    key = (table, col)
    if key not in _COLUMN_CACHE:
        _COLUMN_CACHE[key] = bool(table_has_column(cursor, table, col))
    return _COLUMN_CACHE[key]


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(v: Any) -> float | None:
    d = _dec(v)
    return float(d) if d is not None else None


def _bool01(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "rush", "y"):
        return 1
    if s in ("0", "false", "no", "non-rush", "non_rush", "n"):
        return 0
    return None


def _json_dump(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, default=str)


def _parse_et_dt(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    s = str(raw).strip().replace("Z", "")
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s[:19])
        if len(s) == 10:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, 12, 0, 0)
        return datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def _parse_et_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        et = system_datetime_to_et(raw) if raw.tzinfo is None else raw
        return et.date() if hasattr(et, "date") else raw.date()
    s = str(raw).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _et_from_system(dt: Any) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    et = system_datetime_to_et(dt)
    if isinstance(et, datetime):
        return et.replace(tzinfo=None)
    return None


def ensure_mgmt_issues_tables(cursor) -> None:
    """Idempotent DDL + org-agnostic structure ensure."""
    if not table_exists(cursor, TAXONOMY_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TAXONOMY_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              kind VARCHAR(16) NOT NULL,
              code VARCHAR(64) NOT NULL,
              parent_category_code VARCHAR(64) NULL,
              label VARCHAR(128) NOT NULL,
              active TINYINT(1) NOT NULL DEFAULT 1,
              sort_order INT NOT NULL DEFAULT 100,
              maps_from_external_type VARCHAR(64) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_mgmt_issue_tax_org_kind_code (organization_id, kind, code),
              KEY idx_mgmt_issue_tax_org_kind_active (organization_id, kind, active, sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, ISSUES_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ISSUES_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              matched_state VARCHAR(16) NOT NULL,
              bag_id VARCHAR(64) NULL,
              order_instance_id BIGINT NULL,
              manual_identifier VARCHAR(255) NULL,
              unmatched_reason VARCHAR(512) NULL,
              customer_name_snapshot VARCHAR(255) NULL,
              service_type_snapshot VARCHAR(16) NULL,
              rush_snapshot TINYINT(1) NULL,
              production_date_et DATE NULL,
              completed_at_et DATETIME NULL,
              issue_category VARCHAR(64) NOT NULL,
              issue_subtype VARCHAR(64) NOT NULL,
              reported_at_et DATETIME NOT NULL,
              description TEXT NULL,
              internal_notes TEXT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'open',
              severity VARCHAR(32) NULL,
              resolution_type VARCHAR(64) NULL,
              resolution_notes TEXT NULL,
              resolved_at_et DATETIME NULL,
              claim_amount DECIMAL(12,2) NULL,
              vendor_percentage DECIMAL(6,2) NULL,
              final_vendor_claim DECIMAL(12,2) NULL,
              external_issue_id VARCHAR(128) NULL,
              external_issue_url VARCHAR(512) NULL,
              external_type VARCHAR(64) NULL,
              source VARCHAR(32) NOT NULL DEFAULT 'manual',
              created_by_user_id INT NULL,
              created_by_name VARCHAR(255) NULL,
              updated_by_user_id INT NULL,
              updated_by_name VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              KEY idx_mgmt_issues_org_bag (organization_id, bag_id),
              KEY idx_mgmt_issues_org_oi (organization_id, order_instance_id),
              KEY idx_mgmt_issues_org_prod_cat (organization_id, production_date_et, issue_category),
              KEY idx_mgmt_issues_org_reported (organization_id, reported_at_et),
              KEY idx_mgmt_issues_org_status_prod (organization_id, status, production_date_et),
              UNIQUE KEY uq_mgmt_issues_org_external (organization_id, external_issue_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, ATTR_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ATTR_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              issue_id BIGINT NOT NULL,
              organization_id INT NOT NULL,
              employee_user_id INT NULL,
              employee_name_snapshot VARCHAR(255) NULL,
              role_key VARCHAR(32) NOT NULL,
              stage_key VARCHAR(32) NOT NULL,
              attribution_source VARCHAR(64) NOT NULL,
              confidence VARCHAR(16) NOT NULL DEFAULT 'none',
              is_primary TINYINT(1) NOT NULL DEFAULT 0,
              is_manager_override TINYINT(1) NOT NULL DEFAULT 0,
              is_confirmed TINYINT(1) NOT NULL DEFAULT 0,
              is_not_applicable TINYINT(1) NOT NULL DEFAULT 0,
              original_employee_user_id INT NULL,
              original_employee_name VARCHAR(255) NULL,
              original_role_key VARCHAR(32) NULL,
              original_stage_key VARCHAR(32) NULL,
              override_reason VARCHAR(512) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by_user_id INT NULL,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              updated_by_user_id INT NULL,
              KEY idx_mgmt_attr_issue (issue_id),
              KEY idx_mgmt_attr_org_emp_role (organization_id, employee_user_id, role_key),
              KEY idx_mgmt_attr_org_role (organization_id, role_key, is_primary)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, EVENTS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              issue_id BIGINT NOT NULL,
              organization_id INT NOT NULL,
              action VARCHAR(64) NOT NULL,
              before_json JSON NULL,
              after_json JSON NULL,
              reason VARCHAR(512) NULL,
              actor_user_id INT NULL,
              actor_display_name VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_mgmt_issue_ev_issue (issue_id, created_at),
              KEY idx_mgmt_issue_ev_org_created (organization_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def seed_mgmt_issue_taxonomy(cursor, organization_id: int) -> None:
    org = int(organization_id)
    if org in _ENSURED:
        return
    ensure_mgmt_issues_tables(cursor)
    for code, label, sort in CATEGORY_SEEDS:
        cursor.execute(
            f"""
            INSERT IGNORE INTO {TAXONOMY_TABLE}
              (organization_id, kind, code, parent_category_code, label, active, sort_order)
            VALUES (%s, 'category', %s, NULL, %s, 1, %s)
            """,
            (org, code, label, sort),
        )
    for parent, code, label, sort in SUBTYPE_SEEDS:
        cursor.execute(
            f"""
            INSERT IGNORE INTO {TAXONOMY_TABLE}
              (organization_id, kind, code, parent_category_code, label, active, sort_order)
            VALUES (%s, 'subtype', %s, %s, %s, 1, %s)
            """,
            (org, code, parent, label, sort),
        )
    _ENSURED.add(org)


def append_issue_event(
    cursor,
    *,
    issue_id: int,
    organization_id: int,
    action: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    reason: str | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    cursor.execute(
        f"""
        INSERT INTO {EVENTS_TABLE}
          (issue_id, organization_id, action, before_json, after_json, reason,
           actor_user_id, actor_display_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(issue_id),
            int(organization_id),
            str(action),
            _json_dump(before),
            _json_dump(after),
            (reason or None),
            actor_user_id,
            actor_display_name,
        ),
    )


def list_taxonomy(cursor, organization_id: int) -> dict[str, Any]:
    seed_mgmt_issue_taxonomy(cursor, organization_id)
    cursor.execute(
        f"""
        SELECT kind, code, parent_category_code, label, active, sort_order, maps_from_external_type
        FROM {TAXONOMY_TABLE}
        WHERE organization_id = %s AND active = 1
        ORDER BY kind ASC, sort_order ASC, label ASC
        """,
        (int(organization_id),),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    categories = [r for r in rows if r.get("kind") == "category"]
    subtypes = [r for r in rows if r.get("kind") == "subtype"]
    return {"categories": categories, "subtypes": subtypes}


def _validate_taxonomy(
    cursor, organization_id: int, category: str, subtype: str
) -> str | None:
    seed_mgmt_issue_taxonomy(cursor, organization_id)
    cat = str(category or "").strip().upper()
    sub = str(subtype or "").strip().upper()
    if not cat or not sub:
        return "taxonomy_required"
    cursor.execute(
        f"""
        SELECT 1 FROM {TAXONOMY_TABLE}
        WHERE organization_id = %s AND kind = 'category' AND code = %s AND active = 1
        LIMIT 1
        """,
        (int(organization_id), cat),
    )
    if not cursor.fetchone():
        return "invalid_category"
    cursor.execute(
        f"""
        SELECT 1 FROM {TAXONOMY_TABLE}
        WHERE organization_id = %s AND kind = 'subtype' AND code = %s
          AND parent_category_code = %s AND active = 1
        LIMIT 1
        """,
        (int(organization_id), sub, cat),
    )
    if not cursor.fetchone():
        return "invalid_subtype"
    return None


# ---------------------------------------------------------------------------
# Bag search (narrow)
# ---------------------------------------------------------------------------


def search_issue_bags(
    cursor,
    organization_id: int,
    q: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Targeted bag/OI search. Max 10. No CW/Review/DFP.

    Query budget counts lookup SELECTs only (schema ensure/introspection cached).
    """
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        ensure_rinse_order_instances_table,
    )

    # Schema warm-up outside budget when CountingCursor is used.
    base_q = int(getattr(cursor, "query_count", 0) or 0)
    ensure_rinse_order_instances_table(cursor)
    org = int(organization_id)
    query = (q or "").strip()
    if not query:
        return {
            "results": [],
            "query_count": max(0, int(getattr(cursor, "query_count", 0) or 0) - base_q),
            "lookup_query_count": 0,
        }

    from backend.order_display_id import (
        attach_order_display_id,
        format_order_display_id,
        parse_order_display_id,
    )

    display_parsed = parse_order_display_id(query)
    # Bare-bag search uses the bag token; display-id search extracts bag (+ oi/edd).
    bid_norm = normalize_bag_id(
        display_parsed["bag_id"] if display_parsed else query
    )
    lim = max(1, min(int(limit), 10))
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    def _push(rows: Sequence[Mapping[str, Any]]) -> None:
        for r in rows:
            if not isinstance(r, Mapping):
                continue
            bag = normalize_bag_id(r.get("bag_id"))
            oi = int(r.get("order_instance_id") or 0)
            if not bag or oi <= 0:
                continue
            key = (bag, oi)
            if key in seen:
                continue
            seen.add(key)
            completed = r.get("completed_at")
            completed_et = _et_from_system(completed) if isinstance(completed, datetime) else None
            prod = completed_et.date() if completed_et else None
            rush_raw = r.get("rush_status") or r.get("rush_flag")
            rush = _bool01(rush_raw)
            edd = r.get("estimated_delivery_date")
            row = {
                "bag_id": bag,
                "order_instance_id": oi,
                "customer_name": (r.get("customer_name") or r.get("name_clean") or "").strip()
                or None,
                "service_type": str(r.get("service_type") or "WF").upper(),
                "rush": bool(rush) if rush is not None else False,
                "production_date_et": prod.isoformat() if prod else None,
                "completed_at_et": completed_et.isoformat(sep=" ") if completed_et else None,
                "cycle_anchor_at": str(r.get("cycle_anchor_at") or "") or None,
                "estimated_delivery_date": edd.isoformat()
                if isinstance(edd, date)
                else (str(edd)[:10] if edd else None),
            }
            attach_order_display_id(row)
            # Display-id EDD search: keep only matching EDD when unambiguous filter applies.
            if (
                display_parsed
                and display_parsed.get("form") == "edd"
                and display_parsed.get("estimated_delivery_date") is not None
            ):
                row_edd = row.get("estimated_delivery_date")
                want = display_parsed["estimated_delivery_date"].isoformat()
                if row_edd and row_edd != want:
                    continue
                if not row_edd:
                    # No EDD on row — keep and rely on oi secondary detail; do not drop.
                    row["order_display_id"] = format_order_display_id(
                        bag, oi, estimated_delivery_date=None
                    )
            results.append(row)
            if len(results) >= lim:
                return

    has_registry = _cached_table_exists(cursor, "rinse_bag_registry")
    has_oi = _cached_table_exists(cursor, ORDER_INSTANCES_TABLE)
    if not has_oi:
        return {
            "results": [],
            "query_count": max(0, int(getattr(cursor, "query_count", 0) or 0) - base_q),
            "lookup_query_count": 0,
        }

    name_join = ""
    name_select = "NULL AS name_clean"
    if has_registry:
        name_join = """
            LEFT JOIN rinse_bag_registry reg
              ON reg.organization_id = oi.organization_id
             AND reg.bag_id = oi.bag_id
        """
        name_select = "reg.name_clean AS name_clean"

    rush_select = "NULL AS rush_status"
    edd_select = "NULL AS estimated_delivery_date"
    cycle_join = ""
    if _cached_table_exists(cursor, "rinse_wf_service_cycles"):
        cycle_join = """
            LEFT JOIN rinse_wf_service_cycles cyc
              ON cyc.id = oi.source_cycle_id
        """
        if _cached_column(cursor, "rinse_wf_service_cycles", "rush_status"):
            rush_select = "cyc.rush_status AS rush_status"
        if _cached_column(cursor, "rinse_wf_service_cycles", "estimated_delivery_date"):
            edd_select = "cyc.estimated_delivery_date AS estimated_delivery_date"

    # Mark lookup budget start after schema/introspection warm-up.
    lookup_base = int(getattr(cursor, "query_count", 0) or 0)

    base_select = f"""
        SELECT oi.order_instance_id, oi.bag_id, oi.service_type, oi.completed_at,
               oi.cycle_anchor_at, {name_select}, {rush_select}, {edd_select}
        FROM {ORDER_INSTANCES_TABLE} oi
        {name_join}
        {cycle_join}
        WHERE oi.organization_id = %s
    """

    # Display-id with explicit OI: resolve that OI (still verify bag when present).
    if (
        display_parsed
        and display_parsed.get("form") == "oi_fallback"
        and display_parsed.get("order_instance_id")
    ):
        cursor.execute(
            base_select
            + """
              AND oi.order_instance_id = %s
              AND (%s IS NULL OR oi.bag_id = %s)
            LIMIT %s
            """,
            (
                org,
                int(display_parsed["order_instance_id"]),
                bid_norm,
                bid_norm,
                lim,
            ),
        )
        _push(cursor.fetchall() or [])
    # Single pass: exact OR prefix OR numeric OI — prefer exact first in ORDER BY
    elif bid_norm and re.fullmatch(r"\d{1,18}", query):
        # numeric could be OI id or bag-like; keep both paths in one query when possible
        cursor.execute(
            base_select
            + """
              AND (oi.bag_id = %s OR oi.bag_id LIKE %s OR oi.order_instance_id = %s)
            ORDER BY
              CASE WHEN oi.bag_id = %s THEN 0
                   WHEN oi.order_instance_id = %s THEN 1
                   ELSE 2 END,
              oi.completed_at DESC, oi.order_instance_id DESC
            LIMIT %s
            """,
            (org, bid_norm, f"{bid_norm}%", int(query), bid_norm, int(query), lim),
        )
        _push(cursor.fetchall() or [])
    elif bid_norm:
        cursor.execute(
            base_select
            + """
              AND (oi.bag_id = %s OR oi.bag_id LIKE %s)
            ORDER BY
              CASE WHEN oi.bag_id = %s THEN 0 ELSE 1 END,
              oi.completed_at DESC, oi.order_instance_id DESC
            LIMIT %s
            """,
            (org, bid_norm, f"{bid_norm}%", bid_norm, lim),
        )
        _push(cursor.fetchall() or [])
    elif re.fullmatch(r"\d{1,18}", query):
        cursor.execute(
            base_select + " AND oi.order_instance_id = %s LIMIT %s",
            (org, int(query), lim),
        )
        _push(cursor.fetchall() or [])

    # Customer name only when query looks like a name (spaces) or non-bag token
    if len(results) < lim and has_registry and (
        (" " in query and len(query) >= 3)
        or (not bid_norm and len(query) >= 2)
    ):
        like = f"%{query}%"
        cursor.execute(
            f"""
            SELECT oi.order_instance_id, oi.bag_id, oi.service_type, oi.completed_at,
                   oi.cycle_anchor_at, reg.name_clean AS name_clean, {rush_select}, {edd_select}
            FROM rinse_bag_registry reg
            INNER JOIN {ORDER_INSTANCES_TABLE} oi
              ON oi.organization_id = reg.organization_id
             AND oi.bag_id = reg.bag_id
            {cycle_join}
            WHERE reg.organization_id = %s
              AND reg.name_clean LIKE %s
            ORDER BY oi.completed_at DESC, oi.order_instance_id DESC
            LIMIT %s
            """,
            (org, like, lim - len(results) + 5),
        )
        _push(cursor.fetchall() or [])

    lookup_q = max(0, int(getattr(cursor, "query_count", 0) or 0) - lookup_base)
    return {
        "results": results[:lim],
        "query_count": lookup_q,
        "lookup_query_count": lookup_q,
    }


# ---------------------------------------------------------------------------
# Order context (narrow)
# ---------------------------------------------------------------------------


def _load_oi(cursor, organization_id: int, order_instance_id: int) -> dict[str, Any] | None:
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        ensure_rinse_order_instances_table,
    )

    if not _cached_table_exists(cursor, ORDER_INSTANCES_TABLE):
        ensure_rinse_order_instances_table(cursor)
        _TABLE_CACHE[ORDER_INSTANCES_TABLE] = True
    has_reg = _cached_table_exists(cursor, "rinse_bag_registry")
    if has_reg:
        cursor.execute(
            f"""
            SELECT oi.*, reg.name_clean AS registry_name_clean
            FROM {ORDER_INSTANCES_TABLE} oi
            LEFT JOIN rinse_bag_registry reg
              ON reg.organization_id = oi.organization_id
             AND reg.bag_id = oi.bag_id
            WHERE oi.organization_id = %s AND oi.order_instance_id = %s
            LIMIT 1
            """,
            (int(organization_id), int(order_instance_id)),
        )
    else:
        cursor.execute(
            f"""
            SELECT * FROM {ORDER_INSTANCES_TABLE}
            WHERE organization_id = %s AND order_instance_id = %s
            LIMIT 1
            """,
            (int(organization_id), int(order_instance_id)),
        )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def _customer_for_bag(cursor, organization_id: int, bag_id: str) -> str | None:
    if not table_exists(cursor, "rinse_bag_registry"):
        return None
    cursor.execute(
        """
        SELECT name_clean FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), bag_id),
    )
    row = cursor.fetchone()
    if isinstance(row, dict) and row.get("name_clean"):
        return str(row["name_clean"]).strip() or None
    return None


def _weights_and_rush_for_oi(
    cursor, organization_id: int, oi: Mapping[str, Any]
) -> tuple[float | None, float | None, bool | None]:
    pre = post = None
    rush = None
    sid = oi.get("source_cycle_id")
    if sid and _cached_table_exists(cursor, "rinse_wf_service_cycles"):
        cols = ["pre_weight_lbs", "post_weight_lbs"]
        rush_col = _cached_column(cursor, "rinse_wf_service_cycles", "rush_status")
        if rush_col:
            cols.append("rush_status")
        cursor.execute(
            f"""
            SELECT {", ".join(cols)}
            FROM rinse_wf_service_cycles
            WHERE id = %s AND organization_id = %s
            LIMIT 1
            """,
            (int(sid), int(organization_id)),
        )
        row = cursor.fetchone()
        if isinstance(row, dict):
            pre = _money(row.get("pre_weight_lbs"))
            post = _money(row.get("post_weight_lbs"))
            if rush_col:
                b = _bool01(row.get("rush_status"))
                rush = bool(b) if b is not None else None
    return pre, post, rush


def _folder_candidate(
    cursor, organization_id: int, oi: Mapping[str, Any], production_date: date | None
) -> dict[str, Any] | None:
    """OI-window fold evidence + optional manager override. Targeted scans only."""
    from backend.management_wf_folder_fold_attribution import (
        extract_oi_window_folder_fold_evidence,
    )
    from backend.rinse_wf_current_workload import _next_oi_cycle_anchor

    bag_id = normalize_bag_id(oi.get("bag_id"))
    anchor = oi.get("cycle_anchor_at")
    if not bag_id or not isinstance(anchor, datetime):
        return None

    name = None
    source = "auto_oi_fold"
    confidence = "medium"
    evidence = None

    if production_date and _cached_table_exists(
        cursor, "rinse_wf_folder_attribution_overrides"
    ):
        cursor.execute(
            """
            SELECT effective_employee_name
            FROM rinse_wf_folder_attribution_overrides
            WHERE organization_id = %s AND bag_id = %s AND selected_date_et = %s
              AND override_status = 'active'
            LIMIT 1
            """,
            (int(organization_id), bag_id, production_date),
        )
        ov = cursor.fetchone()
        if isinstance(ov, dict) and (ov.get("effective_employee_name") or "").strip():
            name = str(ov["effective_employee_name"]).strip()
            source = "folder_manager_override"
            confidence = "high"

    if not name and _cached_table_exists(cursor, "rinse_bag_scan_events"):
        end = _next_oi_cycle_anchor(
            cursor, organization_id, bag_id, anchor, ensure_schema=False
        )
        params: list[Any] = [int(organization_id), bag_id, anchor]
        end_sql = ""
        if end is not None:
            end_sql = " AND scanned_at_parsed < %s"
            params.append(end)
        cursor.execute(
            f"""
            SELECT purpose, scanned_at_parsed, user_name
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id = %s
              AND scanned_at_parsed IS NOT NULL
              AND scanned_at_parsed >= %s
              {end_sql}
              AND (
                purpose LIKE %s OR purpose LIKE %s OR purpose LIKE %s
              )
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            tuple(
                params
                + ["%garments-reviewed%", "%weight-entry%", "%processed-by-vendor%"]
            ),
        )
        timeline = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
        evidence = extract_oi_window_folder_fold_evidence(
            timeline,
            cycle_anchor_at=anchor,
            lifecycle_end_exclusive=end,
        )
        if evidence:
            name = (evidence.get("fold_employee") or "").strip() or None
            if name:
                confidence = "high"
                source = "oi_window_fold_evidence"

    if not name:
        return None
    return {
        "role_key": ROLE_FOLDER,
        "stage_key": ROLE_FOLDER,
        "employee_user_id": None,
        "employee_name": name,
        "attribution_source": source,
        "confidence": confidence,
        "is_primary_candidate": True,
    }


def _hd_candidates(
    cursor, organization_id: int, bag_id: str, production_date: date | None
) -> list[dict[str, Any]]:
    if not _cached_table_exists(cursor, "hd_day_bag_production"):
        return []
    params: list[Any] = [int(organization_id), bag_id]
    sql = """
        SELECT washed_by_user_id, washed_by_name_snapshot, washed_by_override_name,
               folded_by_user_id, folded_by_name_snapshot, folded_by_override_name,
               operations_date_et
        FROM hd_day_bag_production
        WHERE organization_id = %s AND bag_id = %s
    """
    if production_date:
        sql += " AND operations_date_et = %s"
        params.append(production_date)
    sql += " ORDER BY operations_date_et DESC LIMIT 1"
    cursor.execute(sql, tuple(params))
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return []
    out: list[dict[str, Any]] = []
    wash_name = (
        str(row.get("washed_by_override_name") or row.get("washed_by_name_snapshot") or "").strip()
        or None
    )
    fold_name = (
        str(row.get("folded_by_override_name") or row.get("folded_by_name_snapshot") or "").strip()
        or None
    )
    if wash_name or row.get("washed_by_user_id"):
        out.append(
            {
                "role_key": ROLE_HD_WASH,
                "stage_key": ROLE_HD_WASH,
                "employee_user_id": row.get("washed_by_user_id"),
                "employee_name": wash_name,
                "attribution_source": "hd_day_bag_production",
                "confidence": "high",
                "is_primary_candidate": True,
            }
        )
    if fold_name or row.get("folded_by_user_id"):
        out.append(
            {
                "role_key": ROLE_HD_FOLD,
                "stage_key": ROLE_HD_FOLD,
                "employee_user_id": row.get("folded_by_user_id"),
                "employee_name": fold_name,
                "attribution_source": "hd_day_bag_production",
                "confidence": "high",
                "is_primary_candidate": not bool(out),
            }
        )
    return out


def build_order_context(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    order_instance_id: int,
) -> dict[str, Any]:
    bid = normalize_bag_id(bag_id)
    oi_id = int(order_instance_id)
    if not bid or oi_id <= 0:
        return {"error": "bag_id_and_order_instance_required", "status": 400}

    base_q = int(getattr(cursor, "query_count", 0) or 0)
    oi = _load_oi(cursor, organization_id, oi_id)
    if not oi:
        return {"error": "order_instance_not_found", "status": 404}
    oi_bag = normalize_bag_id(oi.get("bag_id"))
    if oi_bag != bid:
        return {"error": "bag_id_order_instance_mismatch", "status": 400}

    completed = oi.get("completed_at")
    completed_et = _et_from_system(completed) if isinstance(completed, datetime) else None
    production_date = completed_et.date() if completed_et else None
    customer = (oi.get("registry_name_clean") or "").strip() or None
    if not customer:
        customer = _customer_for_bag(cursor, organization_id, bid)
    pre, post, rush = _weights_and_rush_for_oi(cursor, organization_id, oi)
    service = str(oi.get("service_type") or "WF").upper()

    candidates: list[dict[str, Any]] = []
    if service == "WF":
        folder = _folder_candidate(cursor, organization_id, oi, production_date)
        if folder:
            candidates.append(folder)
    else:
        candidates.extend(_hd_candidates(cursor, organization_id, bid, production_date))

    completion_name = (oi.get("completed_by_employee_name") or "").strip() or None
    if completion_name:
        candidates.append(
            {
                "role_key": ROLE_COMPLETION,
                "stage_key": ROLE_COMPLETION,
                "employee_user_id": oi.get("completed_by_user_id"),
                "employee_name": completion_name,
                "attribution_source": "order_instance_completion",
                "confidence": "high",
                "is_primary_candidate": not any(c.get("is_primary_candidate") for c in candidates),
            }
        )

    folder_name = next(
        (c.get("employee_name") for c in candidates if c.get("role_key") == ROLE_FOLDER),
        None,
    )

    lookup_q = max(0, int(getattr(cursor, "query_count", 0) or 0) - base_q)
    out = {
        "organization_id": int(organization_id),
        "bag_id": bid,
        "order_instance_id": oi_id,
        "customer_name": customer,
        "service_type": service,
        "rush": rush,
        "pre_lbs": pre,
        "post_lbs": post,
        "completion_status": "completed" if completed else "open",
        "completed_at_et": completed_et.isoformat(sep=" ") if completed_et else None,
        "production_date_et": production_date.isoformat() if production_date else None,
        "completion_employee_name": completion_name,
        "folder_employee_name": folder_name,
        "attribution_candidates": candidates,
        "matched_state": MATCHED,
        "query_count": lookup_q,
        "lookup_query_count": lookup_q,
    }
    from backend.order_display_id import attach_order_display_id

    return attach_order_display_id(out)



# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _serialize_issue(row: Mapping[str, Any]) -> dict[str, Any]:
    def _d(v: Any) -> str | None:
        if isinstance(v, date) and not isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, datetime):
            return v.isoformat(sep=" ")
        return str(v) if v is not None else None

    out = {
        "id": int(row["id"]),
        "organization_id": int(row["organization_id"]),
        "matched_state": row.get("matched_state"),
        "bag_id": row.get("bag_id"),
        "order_instance_id": int(row["order_instance_id"])
        if row.get("order_instance_id")
        else None,
        "manual_identifier": row.get("manual_identifier"),
        "unmatched_reason": row.get("unmatched_reason"),
        "customer_name_snapshot": row.get("customer_name_snapshot"),
        "service_type_snapshot": row.get("service_type_snapshot"),
        "rush_snapshot": bool(row["rush_snapshot"])
        if row.get("rush_snapshot") is not None
        else None,
        "production_date_et": _d(row.get("production_date_et")),
        "completed_at_et": _d(row.get("completed_at_et")),
        "issue_category": row.get("issue_category"),
        "issue_subtype": row.get("issue_subtype"),
        "reported_at_et": _d(row.get("reported_at_et")),
        "description": row.get("description"),
        "internal_notes": row.get("internal_notes"),
        "status": row.get("status"),
        "severity": row.get("severity"),
        "resolution_type": row.get("resolution_type"),
        "resolution_notes": row.get("resolution_notes"),
        "resolved_at_et": _d(row.get("resolved_at_et")),
        "claim_amount": _money(row.get("claim_amount")),
        "vendor_percentage": _money(row.get("vendor_percentage")),
        "final_vendor_claim": _money(row.get("final_vendor_claim")),
        "external_issue_id": row.get("external_issue_id"),
        "external_issue_url": row.get("external_issue_url"),
        "external_type": row.get("external_type"),
        "source": row.get("source"),
        "created_by_user_id": row.get("created_by_user_id"),
        "created_by_name": row.get("created_by_name"),
        "updated_by_user_id": row.get("updated_by_user_id"),
        "updated_by_name": row.get("updated_by_name"),
        "created_at": _d(row.get("created_at")),
        "updated_at": _d(row.get("updated_at")),
    }
    from backend.order_display_id import attach_order_display_id

    return attach_order_display_id(out)


def _serialize_attr(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "issue_id": int(row["issue_id"]),
        "employee_user_id": row.get("employee_user_id"),
        "employee_name_snapshot": row.get("employee_name_snapshot"),
        "role_key": row.get("role_key"),
        "stage_key": row.get("stage_key"),
        "attribution_source": row.get("attribution_source"),
        "confidence": row.get("confidence"),
        "is_primary": bool(row.get("is_primary")),
        "is_manager_override": bool(row.get("is_manager_override")),
        "is_confirmed": bool(row.get("is_confirmed")),
        "is_not_applicable": bool(row.get("is_not_applicable")),
        "original_employee_name": row.get("original_employee_name"),
        "original_role_key": row.get("original_role_key"),
        "override_reason": row.get("override_reason"),
    }


def _insert_attributions(
    cursor,
    *,
    issue_id: int,
    organization_id: int,
    candidates: Sequence[Mapping[str, Any]],
    actor_user_id: int | None,
    confirmations: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    conf_by_role = {
        str(c.get("role_key")): c
        for c in (confirmations or [])
        if isinstance(c, Mapping) and c.get("role_key")
    }
    inserted: list[dict[str, Any]] = []
    primary_set = False
    for cand in candidates:
        role = str(cand.get("role_key") or "")
        if not role:
            continue
        conf = conf_by_role.get(role) or {}
        if conf.get("not_applicable"):
            name = None
            uid = None
            na = True
            confirmed = False
            override = True
            reason = str(conf.get("reason") or "not_applicable").strip() or "not_applicable"
            source = "manager"
            confidence = "none"
        elif conf.get("employee_name") or conf.get("employee_user_id"):
            name = (conf.get("employee_name") or cand.get("employee_name") or "").strip() or None
            uid = conf.get("employee_user_id") or cand.get("employee_user_id")
            na = False
            confirmed = bool(conf.get("confirm", True))
            override = bool(
                conf.get("employee_name")
                and conf.get("employee_name") != cand.get("employee_name")
            ) or bool(conf.get("role_key") and conf.get("change"))
            reason = (conf.get("reason") or None) if override else None
            if override and not reason:
                raise ValueError("override_reason_required")
            source = "manager" if override else str(cand.get("attribution_source") or "auto")
            confidence = "high" if confirmed else str(cand.get("confidence") or "medium")
        else:
            name = (cand.get("employee_name") or "").strip() or None
            uid = cand.get("employee_user_id")
            na = False
            confirmed = bool(conf.get("confirm"))
            override = False
            reason = None
            source = str(cand.get("attribution_source") or "auto")
            confidence = str(cand.get("confidence") or "medium")

        is_primary = bool(conf.get("is_primary"))
        if not primary_set and (
            is_primary or (cand.get("is_primary_candidate") and not na and name)
        ):
            is_primary = True
            primary_set = True
        else:
            if not conf.get("is_primary"):
                is_primary = False

        cursor.execute(
            f"""
            INSERT INTO {ATTR_TABLE}
              (issue_id, organization_id, employee_user_id, employee_name_snapshot,
               role_key, stage_key, attribution_source, confidence,
               is_primary, is_manager_override, is_confirmed, is_not_applicable,
               original_employee_user_id, original_employee_name, original_role_key,
               original_stage_key, override_reason, created_by_user_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(issue_id),
                int(organization_id),
                uid,
                name,
                role,
                str(cand.get("stage_key") or role),
                source,
                confidence,
                1 if is_primary else 0,
                1 if override else 0,
                1 if confirmed else 0,
                1 if na else 0,
                cand.get("employee_user_id"),
                cand.get("employee_name"),
                role,
                cand.get("stage_key") or role,
                reason,
                actor_user_id,
            ),
        )
        attr_id = int(cursor.lastrowid)
        inserted.append(
            {
                "id": attr_id,
                "role_key": role,
                "employee_name_snapshot": name,
                "is_primary": is_primary,
                "is_manager_override": override,
                "is_confirmed": confirmed,
            }
        )
    return inserted


def create_issue(
    cursor,
    organization_id: int,
    payload: Mapping[str, Any],
    *,
    actor_user_id: int | None,
    actor_name: str | None,
) -> dict[str, Any]:
    seed_mgmt_issue_taxonomy(cursor, organization_id)
    matched_state = str(payload.get("matched_state") or "").strip().upper()

    # Select-to-save hard rule for matched
    if matched_state == MATCHED or payload.get("order_instance_id") or payload.get("selected"):
        if not payload.get("selection_token") and not payload.get("order_instance_id"):
            return {"error": "selection_required", "status": 400}
        if payload.get("typed_bag_id") and not payload.get("order_instance_id"):
            return {"error": "selection_required", "status": 400}
        if not payload.get("order_instance_id") or not payload.get("bag_id"):
            return {"error": "selection_required", "status": 400}
        matched_state = MATCHED

    if matched_state not in (MATCHED, UNMATCHED):
        # Infer
        if payload.get("order_instance_id"):
            matched_state = MATCHED
        elif payload.get("unmatched"):
            matched_state = UNMATCHED
        else:
            return {"error": "selection_required", "status": 400}

    category = str(payload.get("issue_category") or "").strip().upper()
    subtype = str(payload.get("issue_subtype") or "").strip().upper()
    tax_err = _validate_taxonomy(cursor, organization_id, category, subtype)
    if tax_err:
        return {"error": tax_err, "status": 400}

    status = str(payload.get("status") or "open").strip().lower()
    if status not in STATUSES:
        return {"error": "invalid_status", "status": 400}

    severity = payload.get("severity")
    if severity:
        severity = str(severity).strip().lower()
        if severity not in SEVERITIES:
            return {"error": "invalid_severity", "status": 400}

    reported = _parse_et_dt(payload.get("reported_at_et")) or business_now().replace(tzinfo=None)

    claim = _dec(payload.get("claim_amount"))
    vendor_pct = _dec(payload.get("vendor_percentage"))
    final_claim = _dec(payload.get("final_vendor_claim"))
    if vendor_pct is not None and (vendor_pct < 0 or vendor_pct > 100):
        return {"error": "invalid_vendor_percentage", "status": 400}

    bag_id = None
    oi_id = None
    customer = None
    service = None
    rush = None
    production_date = None
    completed_et = None
    candidates: list[dict[str, Any]] = []
    manual_identifier = None
    unmatched_reason = None

    if matched_state == MATCHED:
        bag_id = normalize_bag_id(payload.get("bag_id"))
        oi_id = int(payload.get("order_instance_id") or 0)
        ctx = build_order_context(
            cursor, organization_id, bag_id=bag_id or "", order_instance_id=oi_id
        )
        if ctx.get("error"):
            return {"error": ctx["error"], "status": int(ctx.get("status") or 400)}
        bag_id = ctx["bag_id"]
        oi_id = ctx["order_instance_id"]
        customer = ctx.get("customer_name")
        service = ctx.get("service_type")
        rush = 1 if ctx.get("rush") else (0 if ctx.get("rush") is False else None)
        production_date = _parse_et_date(ctx.get("production_date_et"))
        completed_et = _parse_et_dt(ctx.get("completed_at_et"))
        candidates = list(ctx.get("attribution_candidates") or [])
    else:
        manual_identifier = str(payload.get("manual_identifier") or "").strip()
        unmatched_reason = str(payload.get("unmatched_reason") or "").strip()
        if not manual_identifier or not unmatched_reason:
            return {"error": "unmatched_fields_required", "status": 400}
        bag_id = normalize_bag_id(payload.get("bag_id")) or None

    try:
        attrs_preview = payload.get("attributions")
        # validate override reasons before insert
        if attrs_preview:
            for a in attrs_preview:
                if not isinstance(a, Mapping):
                    continue
                changed = a.get("change") or (
                    a.get("employee_name")
                    and any(
                        c.get("role_key") == a.get("role_key")
                        and c.get("employee_name") != a.get("employee_name")
                        for c in candidates
                    )
                )
                if (changed or a.get("not_applicable")) and not str(a.get("reason") or "").strip():
                    if a.get("confirm") and not a.get("change") and not a.get("not_applicable"):
                        continue
                    if a.get("change") or a.get("not_applicable"):
                        return {"error": "override_reason_required", "status": 400}
    except Exception:
        pass

    cursor.execute(
        f"""
        INSERT INTO {ISSUES_TABLE}
          (organization_id, matched_state, bag_id, order_instance_id,
           manual_identifier, unmatched_reason,
           customer_name_snapshot, service_type_snapshot, rush_snapshot,
           production_date_et, completed_at_et,
           issue_category, issue_subtype, reported_at_et,
           description, internal_notes, status, severity,
           resolution_type, resolution_notes, resolved_at_et,
           claim_amount, vendor_percentage, final_vendor_claim,
           external_issue_id, external_issue_url, external_type, source,
           created_by_user_id, created_by_name, updated_by_user_id, updated_by_name)
        VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """,
        (
            int(organization_id),
            matched_state,
            bag_id,
            oi_id,
            manual_identifier,
            unmatched_reason,
            customer,
            service,
            rush,
            production_date,
            completed_et,
            category,
            subtype,
            reported,
            (payload.get("description") or None),
            (payload.get("internal_notes") or None),
            status,
            severity,
            (payload.get("resolution_type") or None),
            (payload.get("resolution_notes") or None),
            _parse_et_dt(payload.get("resolved_at_et")),
            claim,
            vendor_pct,
            final_claim,
            (payload.get("external_issue_id") or None),
            (payload.get("external_issue_url") or None),
            (payload.get("external_type") or None),
            str(payload.get("source") or "manual"),
            actor_user_id,
            actor_name,
            actor_user_id,
            actor_name,
        ),
    )
    issue_id = int(cursor.lastrowid)

    try:
        inserted_attrs = _insert_attributions(
            cursor,
            issue_id=issue_id,
            organization_id=organization_id,
            candidates=candidates,
            actor_user_id=actor_user_id,
            confirmations=payload.get("attributions") or [],
        )
    except ValueError as exc:
        return {"error": str(exc), "status": 400}

    action = "created" if matched_state == MATCHED else "unmatched_created"
    append_issue_event(
        cursor,
        issue_id=issue_id,
        organization_id=organization_id,
        action=action,
        actor_user_id=actor_user_id,
        actor_display_name=actor_name,
        after={"id": issue_id, "matched_state": matched_state, "category": category},
    )
    if inserted_attrs:
        append_issue_event(
            cursor,
            issue_id=issue_id,
            organization_id=organization_id,
            action="attribution_inferred",
            actor_user_id=actor_user_id,
            actor_display_name=actor_name,
            after={"attributions": inserted_attrs},
        )
        if any(a.get("is_manager_override") for a in inserted_attrs):
            append_issue_event(
                cursor,
                issue_id=issue_id,
                organization_id=organization_id,
                action="attribution_overridden",
                actor_user_id=actor_user_id,
                actor_display_name=actor_name,
                after={"attributions": inserted_attrs},
            )
        elif any(a.get("is_confirmed") for a in inserted_attrs):
            append_issue_event(
                cursor,
                issue_id=issue_id,
                organization_id=organization_id,
                action="attribution_confirmed",
                actor_user_id=actor_user_id,
                actor_display_name=actor_name,
                after={"attributions": inserted_attrs},
            )

    return get_issue(cursor, organization_id, issue_id)


def get_issue(
    cursor, organization_id: int, issue_id: int, *, include_events: bool = False
) -> dict[str, Any]:
    ensure_mgmt_issues_tables(cursor)
    cursor.execute(
        f"SELECT * FROM {ISSUES_TABLE} WHERE organization_id = %s AND id = %s LIMIT 1",
        (int(organization_id), int(issue_id)),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return {"error": "not_found", "status": 404}
    cursor.execute(
        f"""
        SELECT * FROM {ATTR_TABLE}
        WHERE organization_id = %s AND issue_id = %s
        ORDER BY is_primary DESC, id ASC
        """,
        (int(organization_id), int(issue_id)),
    )
    attrs = [_serialize_attr(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    issue = _serialize_issue(row)
    from backend.order_display_id import stamp_order_display_ids

    stamp_order_display_ids(cursor, [issue])
    out = {
        "issue": issue,
        "attributions": attrs,
        "query_count": getattr(cursor, "query_count", None),
    }
    if include_events:
        cursor.execute(
            f"""
            SELECT id, action, before_json, after_json, reason,
                   actor_user_id, actor_display_name, created_at
            FROM {EVENTS_TABLE}
            WHERE organization_id = %s AND issue_id = %s
            ORDER BY id ASC
            """,
            (int(organization_id), int(issue_id)),
        )
        events = []
        for r in cursor.fetchall() or []:
            if not isinstance(r, dict):
                continue
            bj = r.get("before_json")
            aj = r.get("after_json")
            if isinstance(bj, (bytes, bytearray)):
                bj = bj.decode("utf-8", errors="replace")
            if isinstance(aj, (bytes, bytearray)):
                aj = aj.decode("utf-8", errors="replace")
            events.append(
                {
                    "id": int(r["id"]),
                    "action": r.get("action"),
                    "before": json.loads(bj) if isinstance(bj, str) and bj else bj,
                    "after": json.loads(aj) if isinstance(aj, str) and aj else aj,
                    "reason": r.get("reason"),
                    "actor_user_id": r.get("actor_user_id"),
                    "actor_display_name": r.get("actor_display_name"),
                    "created_at": r["created_at"].isoformat(sep=" ")
                    if isinstance(r.get("created_at"), datetime)
                    else r.get("created_at"),
                }
            )
        out["events"] = events
    return out


def list_issues(
    cursor,
    organization_id: int,
    *,
    status: str | None = None,
    category: str | None = None,
    employee: str | None = None,
    service: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_basis: str = "production",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    ensure_mgmt_issues_tables(cursor)
    org = int(organization_id)
    where = ["i.organization_id = %s"]
    params: list[Any] = [org]

    if status:
        where.append("i.status = %s")
        params.append(status.strip().lower())
    if category:
        where.append("i.issue_category = %s")
        params.append(category.strip().upper())
    if service:
        where.append("i.service_type_snapshot = %s")
        params.append(service.strip().upper())
    date_col = (
        "i.reported_at_et" if date_basis == "reported" else "i.production_date_et"
    )
    if date_from:
        where.append(f"{date_col} >= %s")
        params.append(
            datetime.combine(date_from, datetime.min.time())
            if date_basis == "reported"
            else date_from
        )
    if date_to:
        if date_basis == "reported":
            where.append(f"{date_col} < %s")
            params.append(naive_et_day_end_exclusive(date_to))
        else:
            where.append(f"{date_col} <= %s")
            params.append(date_to)

    join = ""
    if employee:
        join = f"""
            INNER JOIN {ATTR_TABLE} a
              ON a.issue_id = i.id AND a.organization_id = i.organization_id
             AND a.is_primary = 1
             AND a.is_not_applicable = 0
        """
        where.append("a.employee_name_snapshot LIKE %s")
        params.append(f"%{employee.strip()}%")

    if q:
        qq = q.strip()
        if qq.isdigit():
            where.append("(i.id = %s OR i.bag_id LIKE %s OR i.customer_name_snapshot LIKE %s)")
            params.extend([int(qq), f"%{qq}%", f"%{qq}%"])
        else:
            where.append("(i.bag_id LIKE %s OR i.customer_name_snapshot LIKE %s)")
            like = f"%{qq}%"
            params.extend([like, like])

    where_sql = " AND ".join(where)
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))

    cursor.execute(
        f"SELECT COUNT(DISTINCT i.id) AS cnt FROM {ISSUES_TABLE} i {join} WHERE {where_sql}",
        tuple(params),
    )
    total_row = cursor.fetchone() or {}
    total = int(total_row.get("cnt") or 0) if isinstance(total_row, dict) else 0

    cursor.execute(
        f"""
        SELECT i.*,
               (
                 SELECT a.employee_name_snapshot
                 FROM {ATTR_TABLE} a
                 WHERE a.issue_id = i.id AND a.is_primary = 1 AND a.is_not_applicable = 0
                 ORDER BY a.id ASC LIMIT 1
               ) AS primary_employee_name
        FROM {ISSUES_TABLE} i
        {join}
        WHERE {where_sql}
        GROUP BY i.id
        ORDER BY i.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [lim, off]),
    )
    items = []
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        item = _serialize_issue(r)
        item["primary_employee_name"] = r.get("primary_employee_name")
        items.append(item)
    from backend.order_display_id import stamp_order_display_ids

    stamp_order_display_ids(cursor, items)
    return {
        "issues": items,
        "total": total,
        "limit": lim,
        "offset": off,
        "query_count": getattr(cursor, "query_count", None),
    }


def update_issue(
    cursor,
    organization_id: int,
    issue_id: int,
    payload: Mapping[str, Any],
    *,
    actor_user_id: int | None,
    actor_name: str | None,
) -> dict[str, Any]:
    current = get_issue(cursor, organization_id, issue_id)
    if current.get("error"):
        return current
    before = current["issue"]
    fields: dict[str, Any] = {}
    events: list[tuple[str, Any, Any, str | None]] = []

    if "issue_category" in payload or "issue_subtype" in payload:
        cat = str(payload.get("issue_category") or before["issue_category"]).upper()
        sub = str(payload.get("issue_subtype") or before["issue_subtype"]).upper()
        err = _validate_taxonomy(cursor, organization_id, cat, sub)
        if err:
            return {"error": err, "status": 400}
        if cat != before["issue_category"] or sub != before["issue_subtype"]:
            fields["issue_category"] = cat
            fields["issue_subtype"] = sub
            events.append(
                (
                    "type_changed",
                    {"category": before["issue_category"], "subtype": before["issue_subtype"]},
                    {"category": cat, "subtype": sub},
                    None,
                )
            )

    if "status" in payload:
        st = str(payload.get("status") or "").strip().lower()
        if st not in STATUSES:
            return {"error": "invalid_status", "status": 400}
        if st != before["status"]:
            fields["status"] = st
            action = "status_changed"
            if st == "excluded":
                action = "excluded"
            elif before["status"] == "excluded" and st != "excluded":
                action = "restored"
            events.append((action, {"status": before["status"]}, {"status": st}, None))

    for key in ("description", "internal_notes", "resolution_type", "resolution_notes", "severity"):
        if key in payload:
            fields[key] = payload.get(key)

    if "reported_at_et" in payload:
        fields["reported_at_et"] = _parse_et_dt(payload.get("reported_at_et")) or before[
            "reported_at_et"
        ]

    if any(k in payload for k in ("resolution_type", "resolution_notes", "resolved_at_et", "status")):
        if payload.get("status") == "resolved" or payload.get("resolution_type"):
            resolved = _parse_et_dt(payload.get("resolved_at_et")) or business_now().replace(
                tzinfo=None
            )
            fields["resolved_at_et"] = resolved
            if "status" not in fields and before["status"] != "resolved":
                fields["status"] = "resolved"
                events.append(
                    (
                        "status_changed",
                        {"status": before["status"]},
                        {"status": "resolved"},
                        None,
                    )
                )
            events.append(
                (
                    "resolution_entered",
                    {
                        "resolution_type": before.get("resolution_type"),
                        "resolved_at_et": before.get("resolved_at_et"),
                    },
                    {
                        "resolution_type": payload.get("resolution_type")
                        or fields.get("resolution_type"),
                        "resolved_at_et": resolved.isoformat(sep=" ")
                        if isinstance(resolved, datetime)
                        else resolved,
                    },
                    None,
                )
            )

    money_changed = False
    for key in ("claim_amount", "vendor_percentage", "final_vendor_claim"):
        if key in payload:
            val = _dec(payload.get(key))
            if key == "vendor_percentage" and val is not None and (val < 0 or val > 100):
                return {"error": "invalid_vendor_percentage", "status": 400}
            fields[key] = val
            money_changed = True
    if money_changed:
        events.append(
            (
                "financial_changed",
                {
                    "claim_amount": before.get("claim_amount"),
                    "vendor_percentage": before.get("vendor_percentage"),
                    "final_vendor_claim": before.get("final_vendor_claim"),
                },
                {
                    "claim_amount": _money(fields.get("claim_amount", before.get("claim_amount"))),
                    "vendor_percentage": _money(
                        fields.get("vendor_percentage", before.get("vendor_percentage"))
                    ),
                    "final_vendor_claim": _money(
                        fields.get("final_vendor_claim", before.get("final_vendor_claim"))
                    ),
                },
                None,
            )
        )

    if not fields:
        return current

    fields["updated_by_user_id"] = actor_user_id
    fields["updated_by_name"] = actor_name
    sets = ", ".join(f"{k} = %s" for k in fields)
    cursor.execute(
        f"UPDATE {ISSUES_TABLE} SET {sets} WHERE organization_id = %s AND id = %s",
        tuple(list(fields.values()) + [int(organization_id), int(issue_id)]),
    )
    for action, b, a, reason in events:
        append_issue_event(
            cursor,
            issue_id=issue_id,
            organization_id=organization_id,
            action=action,
            actor_user_id=actor_user_id,
            actor_display_name=actor_name,
            before=b,
            after=a,
            reason=reason,
        )
    return get_issue(cursor, organization_id, issue_id, include_events=False)


def link_issue_to_bag(
    cursor,
    organization_id: int,
    issue_id: int,
    *,
    bag_id: str,
    order_instance_id: int,
    actor_user_id: int | None,
    actor_name: str | None,
) -> dict[str, Any]:
    current = get_issue(cursor, organization_id, issue_id)
    if current.get("error"):
        return current
    issue = current["issue"]
    if issue.get("matched_state") == MATCHED and issue.get("order_instance_id"):
        return {"error": "already_matched", "status": 400}

    ctx = build_order_context(
        cursor,
        organization_id,
        bag_id=bag_id,
        order_instance_id=int(order_instance_id),
    )
    if ctx.get("error"):
        return {"error": ctx["error"], "status": int(ctx.get("status") or 400)}

    before = {
        "matched_state": issue.get("matched_state"),
        "bag_id": issue.get("bag_id"),
        "order_instance_id": issue.get("order_instance_id"),
    }
    rush = 1 if ctx.get("rush") else (0 if ctx.get("rush") is False else None)
    cursor.execute(
        f"""
        UPDATE {ISSUES_TABLE}
        SET matched_state = %s,
            bag_id = %s,
            order_instance_id = %s,
            customer_name_snapshot = %s,
            service_type_snapshot = %s,
            rush_snapshot = %s,
            production_date_et = %s,
            completed_at_et = %s,
            updated_by_user_id = %s,
            updated_by_name = %s
        WHERE organization_id = %s AND id = %s
        """,
        (
            MATCHED,
            ctx["bag_id"],
            ctx["order_instance_id"],
            ctx.get("customer_name"),
            ctx.get("service_type"),
            rush,
            _parse_et_date(ctx.get("production_date_et")),
            _parse_et_dt(ctx.get("completed_at_et")),
            actor_user_id,
            actor_name,
            int(organization_id),
            int(issue_id),
        ),
    )

    # Replace attributions with fresh inference
    cursor.execute(
        f"DELETE FROM {ATTR_TABLE} WHERE organization_id = %s AND issue_id = %s",
        (int(organization_id), int(issue_id)),
    )
    inserted = _insert_attributions(
        cursor,
        issue_id=int(issue_id),
        organization_id=organization_id,
        candidates=list(ctx.get("attribution_candidates") or []),
        actor_user_id=actor_user_id,
        confirmations=[],
    )
    after = {
        "matched_state": MATCHED,
        "bag_id": ctx["bag_id"],
        "order_instance_id": ctx["order_instance_id"],
    }
    append_issue_event(
        cursor,
        issue_id=issue_id,
        organization_id=organization_id,
        action="bag_linked",
        actor_user_id=actor_user_id,
        actor_display_name=actor_name,
        before=before,
        after=after,
    )
    if inserted:
        append_issue_event(
            cursor,
            issue_id=issue_id,
            organization_id=organization_id,
            action="attribution_inferred",
            actor_user_id=actor_user_id,
            actor_display_name=actor_name,
            after={"attributions": inserted},
        )
    return get_issue(cursor, organization_id, issue_id, include_events=True)


def override_attributions(
    cursor,
    organization_id: int,
    issue_id: int,
    attributions: Sequence[Mapping[str, Any]],
    *,
    actor_user_id: int | None,
    actor_name: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    current = get_issue(cursor, organization_id, issue_id)
    if current.get("error"):
        return current
    before = current.get("attributions") or []
    if not reason or not str(reason).strip():
        # per-row reasons also accepted
        if not any(str(a.get("reason") or "").strip() for a in attributions):
            return {"error": "override_reason_required", "status": 400}

    cursor.execute(
        f"DELETE FROM {ATTR_TABLE} WHERE organization_id = %s AND issue_id = %s",
        (int(organization_id), int(issue_id)),
    )
    # Treat provided rows as full replacement candidates
    candidates = []
    confirmations = []
    for a in attributions:
        if not isinstance(a, Mapping):
            continue
        role = str(a.get("role_key") or "").strip()
        if not role:
            continue
        candidates.append(
            {
                "role_key": role,
                "stage_key": a.get("stage_key") or role,
                "employee_user_id": a.get("original_employee_user_id") or a.get("employee_user_id"),
                "employee_name": a.get("original_employee_name") or a.get("employee_name"),
                "attribution_source": a.get("attribution_source") or "manager",
                "confidence": a.get("confidence") or "high",
                "is_primary_candidate": bool(a.get("is_primary")),
            }
        )
        confirmations.append(
            {
                "role_key": role,
                "employee_name": a.get("employee_name"),
                "employee_user_id": a.get("employee_user_id"),
                "confirm": True,
                "change": True,
                "is_primary": bool(a.get("is_primary")),
                "not_applicable": bool(a.get("is_not_applicable") or a.get("not_applicable")),
                "reason": a.get("reason") or reason,
            }
        )
    try:
        inserted = _insert_attributions(
            cursor,
            issue_id=int(issue_id),
            organization_id=organization_id,
            candidates=candidates,
            actor_user_id=actor_user_id,
            confirmations=confirmations,
        )
    except ValueError as exc:
        return {"error": str(exc), "status": 400}

    append_issue_event(
        cursor,
        issue_id=issue_id,
        organization_id=organization_id,
        action="attribution_overridden",
        actor_user_id=actor_user_id,
        actor_display_name=actor_name,
        reason=reason,
        before={"attributions": before},
        after={"attributions": inserted},
    )
    return get_issue(cursor, organization_id, issue_id, include_events=True)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _period_bounds(
    period: str,
    *,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> tuple[date, date, date, date]:
    """Return (start, end, prior_start, prior_end) inclusive ET dates."""
    today = business_today()
    p = (period or "30d").strip().lower()
    if p == "today":
        start = end = today
    elif p in ("7d", "7", "7days"):
        end = today
        start = today - timedelta(days=6)
    elif p in ("30d", "30", "30days"):
        end = today
        start = today - timedelta(days=29)
    elif p in ("this_month", "month"):
        start = today.replace(day=1)
        end = today
    elif p in ("last_month",):
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
    elif p == "custom":
        if not custom_from or not custom_to:
            end = today
            start = today - timedelta(days=29)
        else:
            start, end = custom_from, custom_to
    else:
        end = today
        start = today - timedelta(days=29)

    if start > end:
        start, end = end, start
    days = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=days - 1)
    return start, end, prior_start, prior_end


def _completed_oi_count(
    cursor, organization_id: int, start: date, end: date
) -> int:
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        ensure_rinse_order_instances_table,
    )

    if not table_exists(cursor, ORDER_INSTANCES_TABLE):
        return 0
    ensure_rinse_order_instances_table(cursor)
    # Approximate ET day via padded UTC window then filter in SQL on date span
    pad_start = naive_et_day_start(start) - timedelta(hours=6)
    pad_end = naive_et_day_end_exclusive(end) + timedelta(hours=6)
    cursor.execute(
        f"""
        SELECT completed_at FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND completed_at IS NOT NULL
          AND completed_at >= %s AND completed_at < %s
        """,
        (int(organization_id), pad_start, pad_end),
    )
    n = 0
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        et = _et_from_system(r.get("completed_at"))
        if et and start <= et.date() <= end:
            n += 1
    return n


def _folder_volume(cursor, organization_id: int, start: date, end: date) -> int:
    """Completed day-bags with folder credit in range (canonical day bag)."""
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return 0
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et >= %s AND shift_date_et <= %s
          AND (
            (canonical_completion_employee IS NOT NULL AND canonical_completion_employee <> '')
            OR (productivity_employee_name IS NOT NULL AND productivity_employee_name <> '')
          )
        """,
        (int(organization_id), start, end),
    )
    row = cursor.fetchone()
    return int(row.get("cnt") or 0) if isinstance(row, dict) else 0


def _hd_volume(
    cursor, organization_id: int, start: date, end: date, *, kind: str
) -> int:
    if not table_exists(cursor, "hd_day_bag_production"):
        return 0
    if kind == "wash":
        date_col = "washed_date_et"
        user_col = "washed_by_user_id"
        name_cols = "(washed_by_override_name IS NOT NULL AND washed_by_override_name <> '') OR (washed_by_name_snapshot IS NOT NULL AND washed_by_name_snapshot <> '')"
    else:
        date_col = "folded_date_et"
        user_col = "folded_by_user_id"
        name_cols = "(folded_by_override_name IS NOT NULL AND folded_by_override_name <> '') OR (folded_by_name_snapshot IS NOT NULL AND folded_by_name_snapshot <> '')"
    # Prefer dedicated date cols when present
    if not table_has_column(cursor, "hd_day_bag_production", date_col):
        date_col = "operations_date_et"
    cursor.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND {date_col} >= %s AND {date_col} <= %s
          AND ({user_col} IS NOT NULL OR {name_cols})
        """,
        (int(organization_id), start, end),
    )
    row = cursor.fetchone()
    return int(row.get("cnt") or 0) if isinstance(row, dict) else 0


def _rate(count: int, denom: int) -> float | None:
    if denom <= 0:
        return None
    return round((count / denom) * 100.0, 2)


def _pct_change(cur: float | None, prior: float | None) -> float | None:
    if cur is None or prior is None or prior == 0:
        if cur is not None and prior == 0 and cur > 0:
            return None
        return None
    return round(((cur - prior) / prior) * 100.0, 1)


def dashboard_by_issue(
    cursor,
    organization_id: int,
    *,
    period: str = "30d",
    date_basis: str = "production",
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> dict[str, Any]:
    ensure_mgmt_issues_tables(cursor)
    start, end, p_start, p_end = _period_bounds(
        period, custom_from=custom_from, custom_to=custom_to
    )
    org = int(organization_id)
    date_col = "reported_at_et" if date_basis == "reported" else "production_date_et"

    def _agg(a: date, b: date) -> dict[str, Any]:
        if date_basis == "reported":
            cursor.execute(
                f"""
                SELECT issue_category,
                       COUNT(*) AS cnt,
                       SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_cnt,
                       SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_cnt,
                       COALESCE(SUM(claim_amount), 0) AS claim_sum,
                       COALESCE(SUM(final_vendor_claim), 0) AS final_sum
                FROM {ISSUES_TABLE}
                WHERE organization_id = %s
                  AND {date_col} >= %s AND {date_col} < %s
                GROUP BY issue_category
                """,
                (org, naive_et_day_start(a), naive_et_day_end_exclusive(b)),
            )
        else:
            cursor.execute(
                f"""
                SELECT issue_category,
                       COUNT(*) AS cnt,
                       SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_cnt,
                       SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_cnt,
                       COALESCE(SUM(claim_amount), 0) AS claim_sum,
                       COALESCE(SUM(final_vendor_claim), 0) AS final_sum
                FROM {ISSUES_TABLE}
                WHERE organization_id = %s
                  AND {date_col} >= %s AND {date_col} <= %s
                GROUP BY issue_category
                """,
                (org, a, b),
            )
        rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
        total = sum(int(r.get("cnt") or 0) for r in rows)
        open_n = sum(int(r.get("open_cnt") or 0) for r in rows)
        resolved_n = sum(int(r.get("resolved_cnt") or 0) for r in rows)
        claim = sum(float(r.get("claim_sum") or 0) for r in rows)
        final = sum(float(r.get("final_sum") or 0) for r in rows)
        return {
            "rows": rows,
            "total": total,
            "open": open_n,
            "resolved": resolved_n,
            "claim_sum": round(claim, 2),
            "final_sum": round(final, 2),
        }

    cur = _agg(start, end)
    prior = _agg(p_start, p_end)
    denom = _completed_oi_count(cursor, org, start, end)
    prior_denom = _completed_oi_count(cursor, org, p_start, p_end)
    cur_rate = _rate(cur["total"], denom)
    prior_rate = _rate(prior["total"], prior_denom)

    prior_by_cat = {str(r.get("issue_category")): int(r.get("cnt") or 0) for r in prior["rows"]}
    categories = []
    for r in cur["rows"]:
        cat = str(r.get("issue_category") or "")
        cnt = int(r.get("cnt") or 0)
        pcnt = prior_by_cat.get(cat, 0)
        rate = _rate(cnt, denom)
        prate = _rate(pcnt, prior_denom)
        categories.append(
            {
                "issue_category": cat,
                "count": cnt,
                "rate_per_100": rate,
                "pct_of_issues": round((cnt / cur["total"]) * 100.0, 1) if cur["total"] else 0,
                "change_pct_vs_prior": _pct_change(float(cnt), float(pcnt))
                if pcnt or cnt
                else None,
                "rate_change_pct_vs_prior": _pct_change(rate, prate),
                "denominator": denom,
                "denominator_label": "completed_order_instances",
            }
        )
    categories.sort(key=lambda x: -x["count"])

    patterns = []
    if cur_rate is not None and prior_rate is not None and denom >= 20:
        if prior_rate > 0 and cur_rate >= prior_rate * 1.2:
            patterns.append(
                {
                    "code": "rate_up",
                    "label": f"Rate increased vs prior period ({cur_rate} vs {prior_rate} /100)",
                    "numerator": cur["total"],
                    "denominator": denom,
                }
            )
    for c in categories:
        if c["count"] >= 3 and (end - start).days + 1 <= 14:
            patterns.append(
                {
                    "code": "category_cluster",
                    "label": f"{c['count']} {c['issue_category']} issues in selected period",
                    "numerator": c["count"],
                    "denominator": denom,
                }
            )

    return {
        "mode": "by_issue",
        "period": period,
        "date_basis": date_basis,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "prior_range": {"start": p_start.isoformat(), "end": p_end.isoformat()},
        "kpis": {
            "total_issues": cur["total"],
            "issue_rate_per_100": cur_rate,
            "open": cur["open"],
            "resolved": cur["resolved"],
            "claim_amount": cur["claim_sum"],
            "final_vendor_claim": cur["final_sum"],
            "completed_ois": denom,
        },
        "categories": categories,
        "patterns": patterns[:8],
        "query_count": getattr(cursor, "query_count", None),
    }


def dashboard_by_employee(
    cursor,
    organization_id: int,
    *,
    period: str = "30d",
    date_basis: str = "production",
    role_key: str | None = None,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> dict[str, Any]:
    ensure_mgmt_issues_tables(cursor)
    start, end, p_start, p_end = _period_bounds(
        period, custom_from=custom_from, custom_to=custom_to
    )
    org = int(organization_id)
    date_col = "i.reported_at_et" if date_basis == "reported" else "i.production_date_et"

    if date_basis == "reported":
        date_clause = f"{date_col} >= %s AND {date_col} < %s"
        date_params: tuple[Any, ...] = (
            naive_et_day_start(start),
            naive_et_day_end_exclusive(end),
        )
        prior_params: tuple[Any, ...] = (
            naive_et_day_start(p_start),
            naive_et_day_end_exclusive(p_end),
        )
    else:
        date_clause = f"{date_col} >= %s AND {date_col} <= %s"
        date_params = (start, end)
        prior_params = (p_start, p_end)

    role_clause = ""
    role_params: list[Any] = []
    if role_key:
        role_clause = " AND a.role_key = %s"
        role_params = [role_key]

    cursor.execute(
        f"""
        SELECT a.employee_name_snapshot AS employee_name,
               a.employee_user_id,
               a.role_key,
               COUNT(*) AS issue_count,
               COALESCE(SUM(i.claim_amount), 0) AS claim_exposure,
               GROUP_CONCAT(i.issue_category) AS mix_raw
        FROM {ATTR_TABLE} a
        INNER JOIN {ISSUES_TABLE} i
          ON i.id = a.issue_id AND i.organization_id = a.organization_id
        WHERE a.organization_id = %s
          AND a.is_primary = 1
          AND a.is_not_applicable = 0
          AND a.employee_name_snapshot IS NOT NULL
          AND a.employee_name_snapshot <> ''
          AND {date_clause}
          {role_clause}
        GROUP BY a.employee_name_snapshot, a.employee_user_id, a.role_key
        ORDER BY issue_count DESC
        LIMIT 100
        """,
        tuple([org, *date_params, *role_params]),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]

    cursor.execute(
        f"""
        SELECT a.employee_name_snapshot AS employee_name, a.role_key, COUNT(*) AS issue_count
        FROM {ATTR_TABLE} a
        INNER JOIN {ISSUES_TABLE} i
          ON i.id = a.issue_id AND i.organization_id = a.organization_id
        WHERE a.organization_id = %s
          AND a.is_primary = 1
          AND a.is_not_applicable = 0
          AND a.employee_name_snapshot IS NOT NULL
          AND a.employee_name_snapshot <> ''
          AND {date_clause.replace(date_col, date_col)}
          {role_clause}
        GROUP BY a.employee_name_snapshot, a.role_key
        """,
        tuple([org, *prior_params, *role_params]),
    )
    prior_map = {
        (str(r.get("employee_name")), str(r.get("role_key"))): int(r.get("issue_count") or 0)
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict)
    }

    # Volume denominators (set-based, not per employee for folder/hd org totals;
    # per-employee volume when role-ready uses name match on day bags — single query)
    folder_vol_by_name: dict[str, int] = {}
    if table_exists(cursor, "rinse_shift_monitor_day_bags"):
        cursor.execute(
            """
            SELECT COALESCE(NULLIF(productivity_employee_name, ''),
                            NULLIF(canonical_completion_employee, '')) AS emp,
                   COUNT(*) AS cnt
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s
              AND shift_date_et >= %s AND shift_date_et <= %s
            GROUP BY emp
            """,
            (org, start, end),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict) and r.get("emp"):
                folder_vol_by_name[str(r["emp"]).strip().lower()] = int(r.get("cnt") or 0)

    hd_wash_by_name: dict[str, int] = {}
    hd_fold_by_name: dict[str, int] = {}
    if table_exists(cursor, "hd_day_bag_production"):
        wash_date = (
            "washed_date_et"
            if table_has_column(cursor, "hd_day_bag_production", "washed_date_et")
            else "operations_date_et"
        )
        fold_date = (
            "folded_date_et"
            if table_has_column(cursor, "hd_day_bag_production", "folded_date_et")
            else "operations_date_et"
        )
        cursor.execute(
            f"""
            SELECT COALESCE(NULLIF(washed_by_override_name, ''),
                            NULLIF(washed_by_name_snapshot, '')) AS emp,
                   COUNT(*) AS cnt
            FROM hd_day_bag_production
            WHERE organization_id = %s
              AND {wash_date} >= %s AND {wash_date} <= %s
            GROUP BY emp
            """,
            (org, start, end),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict) and r.get("emp"):
                hd_wash_by_name[str(r["emp"]).strip().lower()] = int(r.get("cnt") or 0)
        cursor.execute(
            f"""
            SELECT COALESCE(NULLIF(folded_by_override_name, ''),
                            NULLIF(folded_by_name_snapshot, '')) AS emp,
                   COUNT(*) AS cnt
            FROM hd_day_bag_production
            WHERE organization_id = %s
              AND {fold_date} >= %s AND {fold_date} <= %s
            GROUP BY emp
            """,
            (org, start, end),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict) and r.get("emp"):
                hd_fold_by_name[str(r["emp"]).strip().lower()] = int(r.get("cnt") or 0)

    team_counts: dict[str, list[int]] = {}
    employees = []
    for r in rows:
        name = str(r.get("employee_name") or "").strip()
        role = str(r.get("role_key") or "")
        cnt = int(r.get("issue_count") or 0)
        mix_raw = str(r.get("mix_raw") or "")
        mix: dict[str, int] = {}
        for part in mix_raw.split(","):
            p = part.strip()
            if p:
                mix[p] = mix.get(p, 0) + 1
        key = name.lower()
        volume = None
        rate = None
        rate_available = False
        if role == ROLE_FOLDER:
            volume = folder_vol_by_name.get(key, 0)
            rate = _rate(cnt, volume)
            rate_available = True
        elif role == ROLE_HD_WASH:
            volume = hd_wash_by_name.get(key, 0)
            rate = _rate(cnt, volume)
            rate_available = True
        elif role == ROLE_HD_FOLD:
            volume = hd_fold_by_name.get(key, 0)
            rate = _rate(cnt, volume)
            rate_available = True

        prior_cnt = prior_map.get((name, role), 0)
        team_counts.setdefault(role, []).append(cnt)
        employees.append(
            {
                "employee_name": name,
                "employee_user_id": r.get("employee_user_id"),
                "role_key": role,
                "volume": volume,
                "issues": cnt,
                "issue_rate_per_100": rate if rate_available else None,
                "rate_available": rate_available,
                "issue_mix": mix,
                "claim_exposure": round(float(r.get("claim_exposure") or 0), 2),
                "prior_issues": prior_cnt,
                "trend_pct": _pct_change(float(cnt), float(prior_cnt)),
            }
        )

    # Sort by rate when available else by issues
    employees.sort(
        key=lambda e: (
            -(e["issue_rate_per_100"] if e["issue_rate_per_100"] is not None else -1),
            -e["issues"],
        )
    )

    patterns = []
    for e in employees:
        if not e["rate_available"] or e["issue_rate_per_100"] is None:
            continue
        role = e["role_key"]
        peers = [
            x
            for x in employees
            if x["role_key"] == role
            and x["rate_available"]
            and x["issue_rate_per_100"] is not None
            and (x.get("volume") or 0) >= 20
        ]
        if len(peers) < 2 or (e.get("volume") or 0) < 20:
            continue
        team_avg = sum(p["issue_rate_per_100"] for p in peers) / len(peers)
        if team_avg > 0 and e["issue_rate_per_100"] >= 2 * team_avg:
            patterns.append(
                {
                    "code": "2x_team_rate",
                    "label": f"{e['employee_name']} is 2× team {role} issue rate",
                    "numerator": e["issues"],
                    "denominator": e["volume"],
                    "employee_name": e["employee_name"],
                }
            )

    return {
        "mode": "by_employee",
        "period": period,
        "date_basis": date_basis,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "employees": employees,
        "patterns": patterns[:8],
        "query_count": getattr(cursor, "query_count", None),
    }


def employee_drilldown(
    cursor,
    organization_id: int,
    *,
    employee_name: str,
    role_key: str | None = None,
    period: str = "30d",
    date_basis: str = "production",
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> dict[str, Any]:
    dash = dashboard_by_employee(
        cursor,
        organization_id,
        period=period,
        date_basis=date_basis,
        role_key=role_key,
        custom_from=custom_from,
        custom_to=custom_to,
    )
    name = (employee_name or "").strip().lower()
    matches = [
        e
        for e in dash.get("employees") or []
        if str(e.get("employee_name") or "").strip().lower() == name
        and (not role_key or e.get("role_key") == role_key)
    ]
    start = date.fromisoformat(dash["range"]["start"])
    end = date.fromisoformat(dash["range"]["end"])
    date_col = "i.reported_at_et" if date_basis == "reported" else "i.production_date_et"
    params: list[Any] = [int(organization_id), f"%{employee_name.strip()}%"]
    if date_basis == "reported":
        date_clause = f"{date_col} >= %s AND {date_col} < %s"
        params.extend([naive_et_day_start(start), naive_et_day_end_exclusive(end)])
    else:
        date_clause = f"{date_col} >= %s AND {date_col} <= %s"
        params.extend([start, end])
    role_sql = ""
    if role_key:
        role_sql = " AND a.role_key = %s"
        params.append(role_key)
    cursor.execute(
        f"""
        SELECT i.id, i.bag_id, i.issue_category, i.issue_subtype, i.status,
               i.production_date_et, i.reported_at_et, i.claim_amount,
               a.role_key, a.is_primary
        FROM {ISSUES_TABLE} i
        INNER JOIN {ATTR_TABLE} a
          ON a.issue_id = i.id AND a.organization_id = i.organization_id
        WHERE i.organization_id = %s
          AND a.employee_name_snapshot LIKE %s
          AND a.is_not_applicable = 0
          AND {date_clause}
          {role_sql}
        ORDER BY i.id DESC
        LIMIT 50
        """,
        tuple(params),
    )
    recent = []
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        recent.append(
            {
                "id": int(r["id"]),
                "bag_id": r.get("bag_id"),
                "order_instance_id": r.get("order_instance_id"),
                "issue_category": r.get("issue_category"),
                "issue_subtype": r.get("issue_subtype"),
                "status": r.get("status"),
                "production_date_et": r["production_date_et"].isoformat()
                if isinstance(r.get("production_date_et"), date)
                else r.get("production_date_et"),
                "reported_at_et": r["reported_at_et"].isoformat(sep=" ")
                if isinstance(r.get("reported_at_et"), datetime)
                else r.get("reported_at_et"),
                "claim_amount": _money(r.get("claim_amount")),
                "role_key": r.get("role_key"),
                "is_primary": bool(r.get("is_primary")),
            }
        )
    from backend.order_display_id import stamp_order_display_ids

    stamp_order_display_ids(cursor, recent)
    return {
        "employee": matches[0] if matches else {"employee_name": employee_name, "issues": 0},
        "recent_issues": recent,
        "query_count": getattr(cursor, "query_count", None),
    }
