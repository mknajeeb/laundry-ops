"""
Frozen contract: Washpro daily portal upload → confirm → rush checkout.

These invariants exist because production broke repeatedly when only part of
this pipeline was deployed or when classification diverged from staging. Tests in
backend/tests/test_daily_upload_checkout_regression.py assert every item below.
Do not remove or bypass without updating that test module and running it in CI.
"""

from __future__ import annotations

# --- Confirm pipeline (must exist and run in order) ---
CONFIRM_MUST_IMPORT = "resolve_stale_portal_attention_rows_before_confirm"
CONFIRM_MUST_CALL = (
    "resolve_stale_portal_attention_rows_before_confirm",
    "reclassify_checkout_batch_upload_rows",
)

# --- Portal credential ownership (cross-org history must not block upload) ---
STAGING_OWNER_CONTEXT = "credential_sourced=True"
FINALIZE_MERGE_SCAN_ARGS = ("replace_existing=True", "credential_sourced=True")
SCRAPE_PERSISTENT_MERGE = "persistent_scan_merge"

# --- Rush checkout (completed bags still on today's portal) ---
RUSH_EXCLUDED_NOT_STAGED_KEY = "excluded_not_staged"


def assert_confirm_pipeline_wired(source: str) -> None:
    """Raise AssertionError if confirm_upload_batch_core lost its daily hooks."""
    for name in CONFIRM_MUST_CALL:
        if f"{name}(" not in source:
            raise AssertionError(f"confirm_upload_batch_core must call {name}")
    resolve_at = source.index(f"{CONFIRM_MUST_CALL[0]}(")
    reclass_at = source.index(f"{CONFIRM_MUST_CALL[1]}(")
    if resolve_at >= reclass_at:
        raise AssertionError(
            "resolve_stale_portal_attention_rows_before_confirm must run before reclassify_checkout_batch_upload_rows"
        )


def assert_portal_owner_gate_wired(source: str, *, label: str) -> None:
    if "credential_sourced=True" not in source:
        raise AssertionError(f"{label} must pass credential_sourced=True for portal writes")


def assert_finalize_scan_merge_wired(source: str) -> None:
    for token in FINALIZE_MERGE_SCAN_ARGS:
        if token not in source:
            raise AssertionError(f"finalize_rinse_after_batch_confirm merge must include {token}")


# --- Symbols finalize/confirm must be able to import (partial-deploy guard) ---
FINALIZE_REQUIRED_EXPORTS: tuple[tuple[str, str], ...] = (
    ("backend.manual_checkout_eligibility", "resolve_stale_portal_attention_rows_before_confirm"),
    ("backend.manual_checkout_eligibility", "reclassify_checkout_batch_upload_rows"),
    ("backend.rinse_portal_absence_completion", "reject_bags_missing_from_latest_portal"),
)


def assert_daily_upload_import_graph() -> None:
    """Import every symbol the confirm/finalize path needs — fails before deploy if split."""
    import importlib

    for module_name, symbol in FINALIZE_REQUIRED_EXPORTS:
        mod = importlib.import_module(module_name)
        if not hasattr(mod, symbol):
            raise AssertionError(f"{module_name} must export {symbol} (prod ImportError guard)")
