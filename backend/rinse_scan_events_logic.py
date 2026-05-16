"""
Apply business rules to Rinse portal scan-event rows (exported by scrape-scan-events.mjs).

Not wired to production bag export / scrape.mjs — use locally or from a future API route.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

SCAN_REQUIRED = {
    "page",
    "ticket_row_index",
    "scan_index",
    "rack",
    "time_scanned",
    "user",
    "purpose",
}


def _cell(row: pd.Series, key: str) -> str:
    v = row.get(key)
    if pd.isna(v):
        return ""
    return str(v).strip()


def _parse_scanned_at(text: str) -> pd.Timestamp | pd.NaT:
    s = (text or "").strip()
    if not s:
        return pd.NaT
    for fmt in (
        "%A, %B %d, %Y %I:%M %p",
        "%A, %B %d, %Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT


def load_scan_events_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = SCAN_REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")
    return df


def apply_scan_event_logic(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich scan rows: parsed timestamp, per-ticket ordering, derived flags.
    Extend this function for new rules — do not change production scrape.mjs.
    """
    out = df.copy()
    out["scanned_at_parsed"] = out["time_scanned"].map(_parse_scanned_at)
    out["purpose_norm"] = out["purpose"].map(lambda s: re.sub(r"\s+", "-", (s or "").strip().lower()))

    group_keys = ["page", "ticket_row_index"]
    if "bag_id" in out.columns:
        group_keys.append("bag_id")

    out = out.sort_values(group_keys + ["scanned_at_parsed", "scan_index"], na_position="last")

    out["is_cleaning_start"] = out["purpose_norm"].eq("start-cleaning")
    out["is_move_bag"] = out["purpose_norm"].eq("move-bag")
    out["is_weight_entry"] = out["purpose_norm"].eq("weight-entry")

    out["is_latest_scan_in_ticket"] = False
    for _, g in out.groupby(group_keys, sort=False):
        if g.empty:
            continue
        idx = g["scanned_at_parsed"].idxmax()
        if pd.isna(idx) or idx not in g.index:
            idx = g.index[-1]
        out.loc[idx, "is_latest_scan_in_ticket"] = True

    out["flag_last_location_csv"] = out.get("is_last_location", pd.Series([""] * len(out))).astype(str).str.upper().eq("Y")
    out["flag_last_scan_csv"] = out.get("is_last_scan", pd.Series([""] * len(out))).astype(str).str.upper().eq("Y")

    return out


def summarize_scan_events(df: pd.DataFrame) -> dict:
    """Quick stats after apply_scan_event_logic."""
    applied = apply_scan_event_logic(df) if "scanned_at_parsed" not in df.columns else df
    tickets = applied.groupby(["page", "ticket_row_index"], dropna=False).ngroups
    return {
        "event_rows": len(applied),
        "tickets": int(tickets),
        "with_cleaning_start": int(applied["is_cleaning_start"].sum()),
        "with_move_bag": int(applied["is_move_bag"].sum()),
        "latest_scan_rows": int(applied["is_latest_scan_in_ticket"].sum()),
    }
