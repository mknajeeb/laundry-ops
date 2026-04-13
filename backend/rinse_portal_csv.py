"""
Map Rinse portal CSV (from scripts/rinse-cleanertickets/scrape.mjs with RINSE_CSV_LAYOUT=portal)
into the same pandas shape produced by etl.transform_orders.transform_orders (final orders_df).
"""

from __future__ import annotations

import pandas as pd

from etl.transform_orders import transform_orders

PORTAL_REQUIRED = {"Date", "Customer", "Weight", "Notes", "Bag ID"}


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

    def cell(series: pd.Series, key: str):
        v = series.get(key)
        if pd.isna(v):
            return None
        s = str(v).strip()
        return s if s else None

    synth_rows = []
    for _, r in raw.iterrows():
        synth_rows.append(
            {
                "Column1": cell(r, "Date"),
                "Column2": cell(r, "Customer"),
                "Column3": cell(r, "Weight"),
                "Column4": cell(r, "Notes"),
                "Column5": cell(r, "Bag ID"),
            }
        )
    synth = pd.DataFrame(synth_rows)
    orders_df, _, _ = transform_orders(synth)
    return orders_df
