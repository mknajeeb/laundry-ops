"""Dynamic Cleaner Tickets source URLs for scheduled Rinse scrape.

Production scheduled scrape uses two filters (WF + HD) with
ship_to_vendor_date_start/end = America/New_York yesterday → today.

Does not hard-code calendar dates. Callers rebuild on every run.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from backend.business_time import business_today

SERVICE_TYPE_WF = "wash_and_fold"
SERVICE_TYPE_HD = "hang_dry"

# Full Rinse filter param order (matches portal UI / proven live URLs).
_PORTAL_PARAM_ORDER: tuple[str, ...] = (
    "q",
    "estimated_delivery_date_start",
    "estimated_delivery_date_end",
    "status",
    "speed",
    "transactionality",
    "service_types",
    "extra_qc",
    "rfd",
    "corporate_account",
    "vip",
    "assembled",
    "bagged",
    "steps_in_cleaning_process",
    "has_post_clean_weight",
    "split_ticket",
    "pickup_date_start",
    "pickup_date_end",
    "ship_to_vendor_date_start",
    "ship_to_vendor_date_end",
    "receive_from_vendor_date_start",
    "receive_from_vendor_date_end",
)

PORTAL_TICKETS_ORIGIN = "https://www.rinse.com/cleanertickets/"


def ship_to_vendor_window_et(
    *,
    today_et: date | None = None,
) -> tuple[date, date]:
    """Return (yesterday_et, today_et) for ship_to_vendor_date filters."""
    end = today_et if today_et is not None else business_today()
    start = end - timedelta(days=1)
    return start, end


def build_ship_window_tickets_url(
    *,
    service_types: str,
    date_start: date,
    date_end: date,
    status: str = "any",
    page: int | None = None,
) -> str:
    """Build one Cleaner Tickets list URL for a service type + ship-date window."""
    st = str(service_types or "").strip()
    if not st:
        raise ValueError("service_types is required")
    ps = str(status or "any").strip() or "any"
    params: dict[str, str] = {k: "" for k in _PORTAL_PARAM_ORDER}
    params["status"] = ps
    params["service_types"] = st
    params["ship_to_vendor_date_start"] = date_start.isoformat()
    params["ship_to_vendor_date_end"] = date_end.isoformat()
    if page is not None:
        # page is not in the proven template; pagination overwrites via scraper urlForPage.
        pass
    query = urlencode([(k, params[k]) for k in _PORTAL_PARAM_ORDER])
    return f"{PORTAL_TICKETS_ORIGIN}?{query}"


def build_scheduled_wf_hd_source_urls(
    *,
    today_et: date | None = None,
) -> list[dict[str, Any]]:
    """
    Production scheduled sources: Wash & Fold then Hang Dry.

    Dates: ET yesterday → ET today (inclusive ship_to_vendor window).
    """
    start, end = ship_to_vendor_window_et(today_et=today_et)
    return [
        {
            "label": "wash_and_fold",
            "service_types": SERVICE_TYPE_WF,
            "ship_to_vendor_date_start": start.isoformat(),
            "ship_to_vendor_date_end": end.isoformat(),
            "url": build_ship_window_tickets_url(
                service_types=SERVICE_TYPE_WF,
                date_start=start,
                date_end=end,
            ),
        },
        {
            "label": "hang_dry",
            "service_types": SERVICE_TYPE_HD,
            "ship_to_vendor_date_start": start.isoformat(),
            "ship_to_vendor_date_end": end.isoformat(),
            "url": build_ship_window_tickets_url(
                service_types=SERVICE_TYPE_HD,
                date_start=start,
                date_end=end,
            ),
        },
    ]
