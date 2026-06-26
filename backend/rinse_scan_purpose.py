"""Normalize Rinse scan Purpose values (matches rinse_scan_events_logic)."""

from __future__ import annotations

import re
from typing import Any


def normalize_scan_purpose(raw: str | None) -> str:
    s = (raw or "").strip()
    s = re.sub(r"\s+last\s+\w+$", "", s, flags=re.I)
    s = re.sub(r"\s+", "-", s.strip().lower())
    return s


def is_start_cleaning_purpose(raw: str | None) -> bool:
    return "start-cleaning" in normalize_scan_purpose(raw)


def is_weight_entry_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "weight-entry"


def is_split_load_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "split-load"


def is_add_photos_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "add-photos"


def is_create_workitem_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "create-workitem"


def is_create_issue_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "create-issue"


def is_hd_add_photos_interruption_purpose(raw: str | None) -> bool:
    """Issue/rework scan that invalidates a later second add-photos HD completion."""
    return normalize_scan_purpose(raw) in (
        "create-issue",
        "create-workitem",
        "create-workitem-bulk",
        "create-bulk-workitem",
    )


def is_create_bulk_workitem_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "create-bulk-workitem"


def is_create_workitem_issue_or_bulk_purpose(raw: str | None) -> bool:
    """create-issue, create-workitem, or create-bulk-workitem (sorting prep end pool)."""
    p = normalize_scan_purpose(raw)
    return p in ("create-workitem", "create-issue", "create-bulk-workitem")


def is_create_workitem_or_issue_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p in ("create-workitem", "create-issue")


def is_sorting_prep_end_marker_purpose(raw: str | None) -> bool:
    """Sorting/prep end markers for lifecycle (excludes start-cleaning)."""
    return (
        is_create_workitem_issue_or_bulk_purpose(raw)
        or is_split_load_purpose(raw)
        or is_add_photos_purpose(raw)
    )


def is_sent_to_vendor_purpose(raw: str | None) -> bool:
    return "sent-to-vendor" in normalize_scan_purpose(raw)


def is_received_from_vendor_purpose(raw: str | None) -> bool:
    return "received-from-vendor" in normalize_scan_purpose(raw)


def is_load_out_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "load-out" or "load-out" in p


def is_at_delivery_location_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "at-delivery-location" or "at-delivery-location" in p


def scan_purpose_indicates_sent_left(raw: str | None) -> bool:
    """Outbound/delivery scan evidence — bag left the facility workflow."""
    return is_load_out_purpose(raw) or is_at_delivery_location_purpose(raw)


def is_processed_by_vendor_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "processed-by-vendor" or "processed-by-vendor" in p


def is_complete_cleaning_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "complete-cleaning" or "complete-cleaning" in p


def is_assembly_printed_ct_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "assembly-printed-ct" or "assembly-printed-ct" in p


def is_load_in_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "load-in"


def is_move_bag_purpose(raw: str | None) -> bool:
    return "move-bag" in normalize_scan_purpose(raw)


def is_inbound_cycle_reset_purpose(raw: str | None) -> bool:
    """Inbound/at-vendor cycle markers that supersede an older CLEAN rack anchor."""
    p = normalize_scan_purpose(raw)
    if not p:
        return False
    return (
        p in ("load-in", "received-from-vendor", "bag-picked-up")
        or "sent-to-vendor" in p
    )


def is_rack_location_movement_purpose(raw: str | None) -> bool:
    """Real rack/location movement — not cleaning/production metadata scans."""
    p = normalize_scan_purpose(raw)
    if not p:
        return False
    if p in (
        "start-cleaning",
        "complete-cleaning",
        "processed-by-vendor",
        "weight-entry",
        "add-photos",
        "assembly-printed-ct",
        "cleaning",
        "bag-picked-up",
        "workitems-added",
    ):
        return False
    if is_start_cleaning_purpose(raw) or is_processed_by_vendor_purpose(raw):
        return False
    if is_complete_cleaning_purpose(raw) or is_assembly_printed_ct_purpose(raw):
        return False
    if is_weight_entry_purpose(raw) or is_add_photos_purpose(raw):
        return False
    return (
        is_load_in_purpose(raw)
        or is_move_bag_purpose(raw)
        or is_sent_to_vendor_purpose(raw)
        or is_received_from_vendor_purpose(raw)
    )


def is_quality_control_completed_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "quality-control-completed" or "quality-control-completed" in p


def is_drying_purpose(raw: str | None) -> bool:
    return normalize_scan_purpose(raw) == "drying"


def is_ghost_cleaning_purpose(raw: str | None) -> bool:
    """Exact normalized purpose ``cleaning`` only — ignored in lifecycle/timing."""
    return normalize_scan_purpose(raw) == "cleaning"


def purpose_contains_workitem(raw: str | None) -> bool:
    return "workitem" in normalize_scan_purpose(raw)


def is_ready_washer_purpose(raw: str | None) -> bool:
    return "ready-washer" in normalize_scan_purpose(raw)


def is_washer_settings_purpose(raw: str | None) -> bool:
    p = normalize_scan_purpose(raw)
    return p == "washer-settings" or "washer-settings" in p


def is_load_washer_end_purpose(raw: str | None) -> bool:
    return is_ready_washer_purpose(raw) or is_washer_settings_purpose(raw)


def is_lifecycle_sorting_progress_marker_purpose(raw: str | None) -> bool:
    """Sorting/progress markers for lifecycle (excludes ghost ``cleaning``)."""
    if is_ghost_cleaning_purpose(raw):
        return False
    if is_create_issue_purpose(raw):
        return True
    if purpose_contains_workitem(raw):
        return True
    if is_split_load_purpose(raw) or is_add_photos_purpose(raw):
        return True
    return False


def _purpose_or_rack_is_folding(raw: str | None, rack: Any = None) -> bool:
    if normalize_scan_purpose(raw) == "folding":
        return True
    return "folding" in str(rack or "").lower()


def is_wf_folding_pipeline_purpose(raw: str | None) -> bool:
    """Same-bag WF steps that are part of folding/completion flow, not block splits."""
    if is_add_photos_purpose(raw):
        return True
    if is_complete_cleaning_purpose(raw):
        return True
    if is_start_cleaning_purpose(raw) or is_ghost_cleaning_purpose(raw):
        return True
    return is_cleaning_related_purpose(raw)


def is_fold_block_split_purpose(raw: str | None, *, rack: Any = None) -> bool:
    """Scan that ends one folding block and starts another (excludes WF pipeline steps)."""
    if is_wf_folding_pipeline_purpose(raw):
        return False
    return is_fold_block_non_folding_purpose(raw, rack=rack)


def is_fold_block_non_folding_purpose(raw: str | None, *, rack: Any = None) -> bool:
    """Operational scan that is not folding-rack activity or a completion signal."""
    if is_sent_to_vendor_purpose(raw) or is_received_from_vendor_purpose(raw):
        return False
    if is_move_bag_purpose(raw):
        return False
    if is_load_out_purpose(raw) or is_at_delivery_location_purpose(raw):
        return False
    if is_processed_by_vendor_purpose(raw):
        return False
    if is_load_in_purpose(raw):
        return False
    if _purpose_or_rack_is_folding(raw, rack):
        return False
    if is_complete_cleaning_purpose(raw):
        return False
    if is_assembly_printed_ct_purpose(raw):
        return False
    if normalize_scan_purpose(raw) == "garments-reviewed":
        return False
    return (
        is_operator_upstream_processing_purpose(raw)
        or is_lifecycle_sorting_progress_marker_purpose(raw)
    )


def is_fold_inference_prior_work_purpose(raw: str | None, *, rack: Any = None) -> bool:
    """Alias — non-folding operational scan used for folding block boundaries."""
    return is_fold_block_non_folding_purpose(raw, rack=rack)


def is_operator_upstream_processing_purpose(raw: str | None) -> bool:
    """Weighing, sorting, washing, or drying — not folding/completion scans."""
    if is_complete_cleaning_purpose(raw):
        return False
    if is_processed_by_vendor_purpose(raw):
        return False
    if is_assembly_printed_ct_purpose(raw):
        return False
    p = normalize_scan_purpose(raw)
    if p == "garments-reviewed":
        return False
    if is_move_bag_purpose(raw):
        return False
    return (
        is_weight_entry_purpose(raw)
        or is_ghost_cleaning_purpose(raw)
        or is_lifecycle_sorting_progress_marker_purpose(raw)
        or is_start_cleaning_purpose(raw)
        or is_ready_washer_purpose(raw)
        or is_washer_settings_purpose(raw)
        or is_drying_purpose(raw)
    )


def is_cleaning_related_purpose(raw: str | None) -> bool:
    """
    Purpose labels indicating cleaning/prep activity (gaming stages only).

    Purpose-based — do not use rack names. Folding keeps its own rack logic.
    """
    p = normalize_scan_purpose(raw)
    if not p:
        return False
    if p in (
        "weight-entry",
        "drying",
        "split-load",
        "add-photos",
        "create-workitem",
        "create-issue",
        "create-bulk-workitem",
    ):
        return False
    return "clean" in p
