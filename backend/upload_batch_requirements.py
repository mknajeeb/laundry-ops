"""Upload batch confirm rules: portal/order rows + optional scan-events CSV."""

from __future__ import annotations

from backend.ops_ui_flags import get_ops_ui_flags
from backend.rinse_scan_events_upload import count_scan_events_for_batch


def upload_batch_require_both_csv(cursor, organization_id: int) -> bool:
    """When True, confirm requires non-empty order rows and at least one scan-event row."""
    flags = get_ops_ui_flags(cursor, organization_id)
    return flags.get("upload_batch_require_both_csv", True) is not False


def batch_active_order_row_count(cursor, upload_batch_id: int) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM upload_batch_rows
        WHERE upload_batch_id = %s
          AND row_status IN ('ACCEPTED', 'OVERRIDDEN', 'NEEDS_ATTENTION', 'REJECTED_DUPLICATE')
        """,
        (int(upload_batch_id),),
    )
    row = cursor.fetchone()
    if not row:
        return 0
    return int(row["c"] if isinstance(row, dict) else row[0])


def batch_upload_files_status(cursor, upload_batch_id: int, organization_id: int) -> dict:
    order_rows = batch_active_order_row_count(cursor, upload_batch_id)
    scan_events = count_scan_events_for_batch(cursor, upload_batch_id, organization_id)
    require_both = upload_batch_require_both_csv(cursor, organization_id)
    has_orders = order_rows > 0
    has_events = scan_events > 0
    ready = True
    missing: list[str] = []
    if require_both:
        if not has_orders:
            missing.append("portal_orders")
        if not has_events:
            missing.append("scan_events")
        ready = len(missing) == 0
    else:
        if not has_orders and not has_events:
            missing.append("portal_orders_or_scan_events")
        ready = has_orders or has_events
    return {
        "require_both_csv": require_both,
        "has_order_rows": has_orders,
        "order_row_count": order_rows,
        "has_scan_events": has_events,
        "scan_events_count": scan_events,
        "confirm_ready": ready,
        "missing": missing,
    }


def validate_batch_confirm_dual_csv(cursor, upload_batch_id: int, organization_id: int) -> dict | None:
    """
    Return error payload if confirm must be blocked, else None.
    """
    status = batch_upload_files_status(cursor, upload_batch_id, organization_id)
    if status["confirm_ready"]:
        return None
    missing = status["missing"]
    parts = []
    if "portal_orders" in missing:
        parts.append("portal order CSV (draft must have order rows)")
    if "scan_events" in missing:
        parts.append("Rinse scan-events CSV")
    if "portal_orders_or_scan_events" in missing:
        parts.append("portal order CSV or Rinse scan-events CSV (at least one)")
    if status["require_both_csv"]:
        msg = "Upload batch cannot be confirmed until both files are uploaded: " + " and ".join(parts) + "."
    else:
        msg = "Upload batch cannot be confirmed with no order rows and no scan-events: " + " and ".join(parts) + "."
    return {
        "error": msg,
        "missing": missing,
        "upload_files_status": status,
    }
