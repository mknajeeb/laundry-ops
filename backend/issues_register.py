"""Unified supervisor register over customer issues and employee reports.

The two stores stay separate. This module only reads them and returns one
row shape for the Issues screen and dashboard.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

EMPLOYEE_CATEGORIES = {
    "orphan": "Found Item",
    "redry": "Re-Dry Issue",
    "equipment": "Equipment Not Working",
}

RINSE_OPEN = {"open"}
RINSE_REVIEW = {"investigating"}
RINSE_RESOLVED = {"resolved", "excluded"}
EMPLOYEE_OPEN = {"new"}
EMPLOYEE_REVIEW = {"under_review"}
EMPLOYEE_RESOLVED = {"resolved", "returned", "stored"}


def status_group(source: str, status: str | None) -> str:
    code = str(status or "").strip().lower()
    if source == "rinse":
        if code in RINSE_REVIEW:
            return "review"
        if code in RINSE_RESOLVED:
            return "resolved"
        return "open"
    if code in EMPLOYEE_REVIEW:
        return "review"
    if code in EMPLOYEE_RESOLVED:
        return "resolved"
    return "open"


def _text(*values: Any) -> str:
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def _stamp(value: Any) -> str:
    return str(value or "").replace("T", " ")[:19]


def rinse_row(issue: Mapping[str, Any]) -> dict[str, Any]:
    category = str(issue.get("issue_category") or "OTHER")
    subtype = str(issue.get("issue_subtype") or "").strip()
    order_ref = issue.get("order_display_id") or issue.get("bag_id") or issue.get("manual_identifier")
    return {
        "source": "rinse",
        "source_id": int(issue["id"]),
        "key": f"rinse:{int(issue['id'])}",
        "category": category,
        "category_label": category.replace("_", " ").title() + (f" / {subtype}" if subtype else ""),
        "status": issue.get("status") or "open",
        "status_group": status_group("rinse", issue.get("status")),
        "employee_name": issue.get("primary_employee_name") or "",
        "reported_at": _stamp(issue.get("reported_at_et")),
        "business_date": str(issue.get("production_date_et") or "")[:10],
        "location": "",
        "order_reference": order_ref or "",
        "customer_name": issue.get("customer_name_snapshot") or "",
        "summary": _text(issue.get("description"), issue.get("customer_name_snapshot")),
        "photo_count": int(issue.get("photo_count") or 0),
    }


def employee_row(item: Mapping[str, Any]) -> dict[str, Any]:
    category = str(item.get("report_category") or "orphan")
    flags = item.get("redry_flags") or {}
    if category == "redry":
        reasons = [name for name, on in flags.items() if on]
        detail = ", ".join(reasons)
    else:
        detail = _text(item.get("location_label"), item.get("location_number"), item.get("location_detail"))
    photos = item.get("photos") or []
    return {
        "source": "employee",
        "source_id": int(item["id"]),
        "key": f"employee:{int(item['id'])}",
        "category": category,
        "category_label": EMPLOYEE_CATEGORIES.get(category, category),
        "status": item.get("status") or "new",
        "status_group": status_group("employee", item.get("status")),
        "employee_name": item.get("employee_name") or item.get("reporter_name") or "",
        "reported_at": _stamp(item.get("reported_at_display") or item.get("reported_at")),
        "business_date": str(item.get("business_date") or "")[:10],
        "location": item.get("location_label") or detail,
        "order_reference": item.get("order_reference") or "",
        "customer_name": "",
        "summary": _text(detail, item.get("notes")),
        "photo_count": len(photos) if isinstance(photos, Sequence) and not isinstance(photos, (str, bytes)) else 0,
        "redry_flags": flags if category == "redry" else {},
    }


def _matches(row: Mapping[str, Any], *, source: str, category: str, employee: str, q: str) -> bool:
    if source in {"rinse", "employee"} and row["source"] != source:
        return False
    if category and str(row["category"]).lower() != category.lower():
        return False
    if employee and employee.lower() not in str(row["employee_name"] or "").lower():
        return False
    if q:
        haystack = _text(
            row.get("source_id"),
            row.get("category_label"),
            row.get("employee_name"),
            row.get("location"),
            row.get("order_reference"),
            row.get("customer_name"),
            row.get("summary"),
            row.get("status"),
        ).lower()
        if q.lower() not in haystack:
            return False
    return True


def compose_register(
    rinse_issues: Sequence[Mapping[str, Any]],
    employee_items: Sequence[Mapping[str, Any]],
    *,
    source: str = "all",
    category: str = "",
    status_group_filter: str = "",
    employee: str = "",
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Merge already-loaded rows. Does not read or write either table."""
    rows = [rinse_row(issue) for issue in rinse_issues] + [employee_row(item) for item in employee_items]
    narrowed = [
        row for row in rows
        if _matches(row, source=source, category=category, employee=employee, q=q)
    ]
    narrowed.sort(key=lambda row: (row.get("reported_at") or "", row["key"]), reverse=True)
    summary = _summary(narrowed)
    group = str(status_group_filter or "").strip().lower()
    visible = [row for row in narrowed if not group or group == "all" or row["status_group"] == group]
    size = max(1, min(int(page_size or 50), 100))
    index = max(1, int(page or 1))
    start = (index - 1) * size
    return {
        "ok": True,
        "rows": visible[start:start + size],
        "total": len(visible),
        "page": index,
        "page_size": size,
        "summary": summary,
    }


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_source = {"rinse": 0, "employee": 0}
    by_category: dict[str, int] = {}
    groups = {"open": 0, "review": 0, "resolved": 0}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
        label = str(row["category_label"])
        by_category[label] = by_category.get(label, 0) + 1
        groups[row["status_group"]] = groups.get(row["status_group"], 0) + 1
    attention = [row for row in rows if row["status_group"] in {"open", "review"}][:8]
    return {
        "total": len(rows),
        "open": groups["open"],
        "review": groups["review"],
        "resolved": groups["resolved"],
        "by_source": by_source,
        "by_category": [{"label": label, "count": count} for label, count in sorted(by_category.items())],
        "recent": attention,
    }


def load_issue_register(cursor, organization_id: int, **filters: Any) -> dict[str, Any]:
    """Read both stores for one organization and compose the register."""
    from backend.business_time import business_today
    from backend.lost_found import search_issue_reports
    from backend.management_issues import list_issues

    end = filters.get("date_to") or business_today()
    start = filters.get("date_from") or (end - timedelta(days=29))
    if isinstance(start, date) and isinstance(end, date) and start > end:
        start, end = end, start
    source = str(filters.get("source") or "all").strip().lower()
    category = str(filters.get("category") or "").strip()
    employee_category = category.lower() if category.lower() in EMPLOYEE_CATEGORIES else ""
    rinse_category = category.upper() if category and not employee_category else ""
    want_rinse = source in {"", "all", "rinse"} and not employee_category
    want_employee = source in {"", "all", "employee"} and not rinse_category

    rinse_issues: list[dict[str, Any]] = []
    if want_rinse:
        offset = 0
        while len(rinse_issues) < 500:
            batch = list_issues(
                cursor,
                int(organization_id),
                category=rinse_category or None,
                q=None,
                date_from=start,
                date_to=end,
                date_basis="reported",
                limit=100,
                offset=offset,
            )
            chunk = list(batch.get("issues") or [])
            rinse_issues.extend(chunk)
            total = int(batch.get("total") or 0)
            if not chunk or len(rinse_issues) >= total:
                break
            offset += len(chunk)

    employee_items: list[dict[str, Any]] = []
    if want_employee:
        page = 1
        while len(employee_items) < 500:
            batch = search_issue_reports(
                cursor,
                int(organization_id),
                date_from=start,
                date_to=end,
                category=employee_category or None,
                page=page,
                page_size=100,
            )
            chunk = list(batch.get("items") or [])
            employee_items.extend(chunk)
            total = int(batch.get("total") or 0)
            if not chunk or len(employee_items) >= total:
                break
            page += 1

    payload = compose_register(
        rinse_issues,
        employee_items,
        source=source if source in {"rinse", "employee"} else "all",
        category=category,
        status_group_filter=str(filters.get("status_group") or ""),
        employee=str(filters.get("employee") or ""),
        q=str(filters.get("q") or ""),
        page=int(filters.get("page") or 1),
        page_size=int(filters.get("page_size") or 50),
    )
    payload["date_from"] = start.isoformat()
    payload["date_to"] = end.isoformat()
    return payload
