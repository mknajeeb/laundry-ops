"""
Apply business rules to Rinse scan-events CSV (scrape-scan-events.mjs).

Two files from scrape (no redundant portal columns on events):
  *-tickets.csv — production portal layout (compare to scrape.mjs output)
  *-events.csv   — Bag ID (unique alphanumeric code) + scan table columns only

Portal import uses tickets file + portal_csv_to_orders_df (production path).
Event rules apply only to the events file.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.rinse_portal_csv import PORTAL_REQUIRED, portal_csv_to_orders_df

SCAN_EVENT_COLUMNS = [
    "Scan Index",
    "Rack",
    "Time Scanned",
    "User",
    "Purpose",
    "Last Location",
    "Last Scan",
]

EVENTS_REQUIRED = {"Bag ID"} | set(SCAN_EVENT_COLUMNS)


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
    """Load *-events.csv (Bag ID + scan columns only)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    missing = EVENTS_REQUIRED - set(df.columns)
    if missing:
        raise ValueError(
            "Not an events CSV (missing: "
            + ", ".join(sorted(missing))
            + "). Use *-events.csv from scrape-scan-events.mjs."
        )
    from backend.rinse_bag_completion import normalize_bag_id

    df["Bag ID"] = df["Bag ID"].map(normalize_bag_id)
    return df


def resolve_tickets_csv_path(events_path: str, tickets_path: str | None = None) -> str:
    if tickets_path and Path(tickets_path).is_file():
        return tickets_path
    p = Path(events_path)
    for candidate in (
        p.with_name(p.name.replace("-events.csv", "-tickets.csv")),
        p.with_name(p.stem.replace("-events", "-tickets") + ".csv"),
        p.with_name(p.stem + "-tickets.csv"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError(
        "Tickets CSV not found. Pass --tickets or run scrape-scan-events.mjs "
        "(expects *-tickets.csv next to *-events.csv)."
    )


def portal_orders_from_tickets_csv(tickets_path: str) -> pd.DataFrame:
    """Production portal → orders (same as upload batch import)."""
    raw = pd.read_csv(tickets_path, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = PORTAL_REQUIRED - set(raw.columns)
    if missing:
        raise ValueError(f"Tickets CSV missing portal columns: {sorted(missing)}")
    return portal_csv_to_orders_df(tickets_path)


def apply_scan_event_logic(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich events file only — extend for new scan rules."""
    out = df.copy()
    out["scanned_at_parsed"] = out["Time Scanned"].map(_parse_scanned_at)
    out["purpose_norm"] = out["Purpose"].map(
        lambda s: re.sub(r"\s+", "-", re.sub(r"\s+last\s+\w+$", "", (s or "").strip(), flags=re.I).lower())
    )

    scan_idx = pd.to_numeric(out.get("Scan Index", pd.Series([""] * len(out))), errors="coerce")
    out["_scan_index_num"] = scan_idx

    group_keys = ["Bag ID"]
    out = out.sort_values(
        group_keys + ["scanned_at_parsed", "_scan_index_num"],
        na_position="last",
    )

    out["is_cleaning_start"] = out["purpose_norm"].str.contains("start-cleaning", na=False)
    out["is_move_bag"] = out["purpose_norm"].eq("move-bag")
    out["is_weight_entry"] = out["purpose_norm"].eq("weight-entry")
    out["is_sent_to_vendor"] = out["purpose_norm"].str.contains("sent-to-vendor", na=False)

    out["is_latest_scan_in_ticket"] = False
    has_scan = out["_scan_index_num"].fillna(0) > 0
    for _, g in out.loc[has_scan].groupby(group_keys, sort=False):
        if g.empty:
            continue
        idx = g["scanned_at_parsed"].idxmax()
        if pd.isna(idx) or idx not in g.index:
            idx = g.index[-1]
        out.loc[idx, "is_latest_scan_in_ticket"] = True

    out["flag_last_location_csv"] = out.get("Last Location", pd.Series([""] * len(out))).astype(str).str.upper().eq("Y")
    out["flag_last_scan_csv"] = out.get("Last Scan", pd.Series([""] * len(out))).astype(str).str.upper().eq("Y")

    out = out.drop(columns=["_scan_index_num"], errors="ignore")
    return out


def summarize_scan_events(df: pd.DataFrame) -> dict:
    applied = apply_scan_event_logic(df) if "scanned_at_parsed" not in df.columns else df
    has_scan = applied.get("Scan Index", pd.Series([""] * len(applied))).astype(str).str.strip() != ""
    bags = applied.loc[has_scan, "Bag ID"].nunique() if has_scan.any() else 0
    return {
        "event_rows": len(applied),
        "bags_with_scans": int(bags),
        "with_cleaning_start": int(applied["is_cleaning_start"].sum()) if "is_cleaning_start" in applied.columns else 0,
        "with_move_bag": int(applied["is_move_bag"].sum()) if "is_move_bag" in applied.columns else 0,
        "latest_scan_rows": int(applied["is_latest_scan_in_ticket"].sum())
        if "is_latest_scan_in_ticket" in applied.columns
        else 0,
    }
