"""Minimal portal CSV fixtures for scrape gate integration tests."""

from __future__ import annotations

from pathlib import Path

PORTAL_CSV_HEADER = (
    "Date,Estd. Delivery,Customer,# WF LBS,# HD,# WF ITEMS,Weight,Notes,"
    "Special Instructions,USE OXIC,Use Hypo,USE FAB,Low DRY,NO SCEN,Extra Scen,"
    "Service Type,Sub-Service,Bag ID\n"
)


def write_gate_passing_portal_csv(path: Path) -> None:
    path.write_text(
        PORTAL_CSV_HEADER
        + '"Mon 06/15/2026","Mon 06/15/2026","Customer 0","18.8","NA","","18.8 LBS","","'
        '"USE OXICLEAN","","","","","","","Wash & Fold","Full",'
        '"ABC1234567 (Wash & Fold) (Full)"\n'
    )
