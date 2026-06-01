"""
Map Rinse portal CSV (scripts/rinse-cleanertickets/scrape.mjs with RINSE_CSV_LAYOUT=portal)
into a DataFrame with the same columns as transform_orders()'s final output.

We do NOT pass portal rows through transform_orders(): that pipeline is built for messy
Excel grids and uses extract_name() / get_date() heuristics that skip cells with "/" (dates),
"LBS", etc., which drops most clean portal rows — leaving only a handful that accidentally pass.
"""

from __future__ import annotations

import re
from datetime import date

from typing import Any, Sequence

import pandas as pd

from etl.transform_orders import (
    classify_service,
    detect_rush_hint,
    extract_date_from_text,
    extract_weight,
)

PORTAL_REQUIRED = {"Date", "Customer", "Weight", "Notes", "Bag ID"}


def _ticket_id_from_bag(bag: str | None) -> str | None:
    """Strip portal Bag ID to canonical ticket_id (shared with scan-events bag_id)."""
    from backend.rinse_bag_completion import normalize_bag_id

    bid = normalize_bag_id(bag)
    return bid if bid else None


def _cell(row: pd.Series, key: str):
    v = row.get(key)
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def _parse_portal_date(val: str | None):
    """Portal Date column is often 'Tue 4/14' or 'Tue 04/14/2026'; may include 'TODAY' from Rinse."""
    if val is None:
        return None
    t = str(val).strip()
    if not t:
        return None

    if re.fullmatch(r"today", t, flags=re.I):
        return date.today()

    t_parse = re.sub(r"\btoday\b", " ", t, flags=re.I)
    t_parse = re.sub(r"\s+", " ", t_parse).strip()
    if not t_parse:
        return date.today()

    d = extract_date_from_text(t_parse) or extract_date_from_text(t)
    if d is not None:
        return d

    m = re.search(
        r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        t_parse,
        re.I,
    )
    if m:
        month, day = int(m.group(2)), int(m.group(3))
        yraw = m.group(4)
        if yraw:
            y = int(yraw) if len(yraw) > 2 else 2000 + int(yraw)
        else:
            y = date.today().year
        try:
            return date(y, month, day)
        except ValueError:
            pass

    ts = pd.to_datetime(t_parse, errors="coerce")
    if pd.notna(ts):
        return ts.date()
    ts = pd.to_datetime(t, errors="coerce")
    if pd.notna(ts):
        return ts.date()
    return None


def parse_rush_flag_from_portal_cells(cells: Sequence[Any]) -> str | None:
    """Return RUSH, NON-RUSH, or None when speed cannot be determined."""
    if detect_rush_hint(cells):
        return "RUSH"
    for c in cells:
        if c is None:
            continue
        u = str(c).upper()
        if "NON-RUSH" in u or "NON RUSH" in u:
            return "NON-RUSH"
    return None


def portal_csv_to_orders_df(csv_path: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = PORTAL_REQUIRED - set(raw.columns)
    if missing:
        raise ValueError(
            "CSV is not a Rinse portal export (missing columns: "
            + ", ".join(sorted(missing))
            + "). The import runs the scraper with RINSE_CSV_LAYOUT=portal."
        )

    out_rows: list[dict] = []
    for _, r in raw.iterrows():
        date_raw = _cell(r, "Date")
        cust = _cell(r, "Customer")
        weight = _cell(r, "Weight")
        notes = _cell(r, "Notes")
        bag = _cell(r, "Bag ID")
        wf_lbs_col = _cell(r, "# WF LBS")
        hd_raw = _cell(r, "# HD")
        if hd_raw is not None and str(hd_raw).strip().upper() == "NA":
            wf_cnt_col = None
        elif hd_raw is not None and str(hd_raw).strip() != "":
            wf_cnt_col = str(hd_raw).strip()
        else:
            wf_cnt_col = None
        svc_type = _cell(r, "Service Type")
        sub_svc = _cell(r, "Sub-Service")
        wf_items_col = _cell(r, "# WF ITEMS")
        ticket_id = _ticket_id_from_bag(bag)
        if not cust:
            continue
        d = _parse_portal_date(date_raw)
        if d is None:
            continue
        cells = [
            x
            for x in (
                date_raw,
                cust,
                svc_type,
                sub_svc,
                wf_lbs_col,
                wf_cnt_col,
                wf_items_col,
                weight,
                notes,
                bag,
            )
            if x
        ]
        # wf_items is a Hang Dry item count, not pounds — do not feed extract_weight (would confuse lbs).
        # # HD / WF item counts are not pounds — do not pass them to extract_weight.
        w = extract_weight([wf_lbs_col, weight, notes, bag])
        st = classify_service(
            [
                svc_type,
                sub_svc,
                wf_lbs_col,
                wf_cnt_col,
                wf_items_col,
                weight,
                notes,
                bag,
            ]
        )
        rush_parsed = parse_rush_flag_from_portal_cells(cells)
        rush = rush_parsed if rush_parsed else "NON-RUSH"
        out_rows.append(
            {
                "Date_Clean": d,
                "Name_Clean": cust.strip(),
                "Weight_Num": w,
                "ServiceType": st,
                "RushType": rush,
                "ticket_id": ticket_id,
            }
        )

    if not out_rows:
        raise ValueError(
            "No portal rows produced a parseable date and customer. "
            "Check the CSV Date and Customer columns and Rinse scrape output."
        )

    df = pd.DataFrame(out_rows)
    bluebottle_mask = df["Name_Clean"].astype(str).str.upper().str.contains("BLUEBOTTLE", na=False)
    df.loc[bluebottle_mask, "ServiceType"] = "HD"
    # Keep scrape order; do not sort by name only (same customer can have many bags — looks “deduped”).
    df = df.sort_values(["Date_Clean", "ticket_id"], na_position="last").reset_index(drop=True)
    df["ServiceType"] = pd.Categorical(df["ServiceType"], categories=["WF", "HD"])
    return df
