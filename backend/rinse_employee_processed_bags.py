"""Employee processed production events — labor performed regardless of business completion."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import gaming_events_from_records, ts_valid
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    _attribution_reason,
    _event_user_name,
    _is_hd_completion_purpose,
    _resolve_anchor_ts,
    _scan_event_timestamp,
    resolve_completion_attribution,
)
from backend.rinse_folding_et import (
    naive_et_day_end_inclusive,
    naive_et_day_end_exclusive,
    naive_et_day_start,
    period_datetime_bounds_et,
)
from backend.rinse_post_processing_weight_chronology import (
    _load_scan_events_for_bags,
    build_post_processing_weight_chronology_payload,
)
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import (
    WF_POST_PROCESSING_WEIGHT_SIGNAL,
    parse_weight_lbs_from_scan_event,
)
from backend.ta_helpers import table_exists


def _processed_lbs_from_weight_event(ev: Mapping[str, Any], meta: Mapping[str, Any] | None) -> float | None:
    from_weight = parse_weight_lbs_from_scan_event(ev)
    if from_weight is not None and from_weight > 0:
        return round(float(from_weight), 4)
    if meta:
        for key in ("post_clean_weight", "weight_num", "registry_weight_num", "weight_lbs"):
            raw = meta.get(key)
            if raw is None:
                continue
            try:
                val = float(raw)
                if val > 0:
                    return round(val, 4)
            except (TypeError, ValueError):
                continue
    return None


def _format_processed_time_et(comp_ts: datetime | None) -> str | None:
    if comp_ts is None:
        return None
    from backend.rinse_at_vendor_module import _format_et_display

    return _format_et_display(comp_ts)


def _wf_processed_records(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    registry_meta_by_bag: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    payload = build_post_processing_weight_chronology_payload(
        cursor, organization_id, selected_date_et=selected_date_et
    )
    ppw_rows = payload.get("sessions") or []

    bag_ids = sorted({str(r.get("bag_id") or "").strip().upper() for r in ppw_rows if r.get("bag_id")})
    loaded = _load_scan_events_for_bags(cursor, organization_id, bag_ids)
    events_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in loaded:
        bid = str(ev.get("bag_id") or "").strip().upper()
        if bid:
            events_lookup[bid].append(ev)

    records: list[dict[str, Any]] = []
    for row in ppw_rows:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        comp_ts = row.get("timestamp_et")
        if not isinstance(comp_ts, datetime):
            continue
        employee = _event_user_name({"user_name": row.get("employee")})
        events = events_lookup.get(bid) or []
        timeline = gaming_events_from_records(events)
        weight_ev = None
        for ev in timeline:
            if _scan_event_timestamp(ev) == comp_ts and is_weight_entry_purpose(ev.get("purpose")):
                weight_ev = ev
                break
        meta = registry_meta_by_bag.get(bid) or {}
        lbs = _processed_lbs_from_weight_event(weight_ev or {}, meta)
        records.append(
            {
                "bag_id": bid,
                "service_type": "WF",
                "service_bucket": "WF",
                "employee_credited": employee,
                "processed_by_employee": employee,
                "processed_signal": WF_POST_PROCESSING_WEIGHT_SIGNAL,
                "processed_time": comp_ts.isoformat(),
                "processed_timestamp": comp_ts.isoformat(),
                "processed_time_et": _format_processed_time_et(comp_ts),
                "processed_lbs": lbs,
                "weight_missing": lbs is None,
                "customer_name": meta.get("name_clean") or meta.get("customer_name"),
                "attribution_reason": _attribution_reason("WF", WF_POST_PROCESSING_WEIGHT_SIGNAL),
                "is_business_completed": False,
            }
        )
    return records


def _hd_processed_records(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    registry_meta_by_bag: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """HD employee credits prefer persisted washed_by/washed_at and folded_by/folded_at.

    Wash and fold may fall on different business days; each credits on its own timestamp.
    Do not attribute either operation to the revenue-entry / Complete date.
    """
    org = int(organization_id)
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    meta_lookup = dict(registry_meta_by_bag)
    records: list[dict[str, Any]] = []
    covered: set[str] = set()

    # Prefer canonical production attribution via Management HD performance helper.
    try:
        from backend.management_hd_performance import build_hd_employee_performance

        perf = build_hd_employee_performance(cursor, org, selected_date_et)
        for emp in perf.get("employees") or []:
            name = str(emp.get("display_name") or "").strip() or "Unknown"
            for wash in emp.get("wash_bags") or []:
                bid = str(wash.get("bag_id") or "").strip().upper()
                ts = wash.get("washed_at")
                if not bid or not isinstance(ts, datetime):
                    continue
                covered.add(bid)
                records.append(
                    {
                        "bag_id": bid,
                        "service_type": "HD",
                        "service_bucket": "HD",
                        "employee_credited": name,
                        "processed_by_employee": name,
                        "processed_signal": "hd_wash",
                        "processed_time": ts.isoformat(),
                        "processed_timestamp": ts.isoformat(),
                        "processed_time_et": _format_processed_time_et(ts),
                        "processed_lbs": None,
                        "weight_missing": True,
                        "customer_name": (meta_lookup.get(bid) or {}).get("name_clean")
                        or (meta_lookup.get(bid) or {}).get("customer_name"),
                        "attribution_reason": "washed_by/washed_at",
                        "is_business_completed": False,
                        "hd_credit_type": "wash",
                    }
                )
            for fold in emp.get("fold_bags") or []:
                bid = str(fold.get("bag_id") or "").strip().upper()
                ts = fold.get("folded_at")
                if not bid or not isinstance(ts, datetime):
                    continue
                covered.add(bid)
                records.append(
                    {
                        "bag_id": bid,
                        "service_type": "HD",
                        "service_bucket": "HD",
                        "employee_credited": name,
                        "processed_by_employee": name,
                        "processed_signal": "hd_fold",
                        "processed_time": ts.isoformat(),
                        "processed_timestamp": ts.isoformat(),
                        "processed_time_et": _format_processed_time_et(ts),
                        "processed_lbs": None,
                        "weight_missing": True,
                        "customer_name": (meta_lookup.get(bid) or {}).get("name_clean")
                        or (meta_lookup.get(bid) or {}).get("customer_name"),
                        "attribution_reason": "folded_by/folded_at",
                        "is_business_completed": False,
                        "hd_credit_type": "fold",
                    }
                )
    except Exception:
        pass

    if not table_exists(cursor, "rinse_bag_scan_events"):
        return records

    start_dt, _ = period_datetime_bounds_et(selected_date_et, selected_date_et)
    end_exclusive = naive_et_day_end_exclusive(selected_date_et)

    cursor.execute(
        """
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
          AND (
            LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
          )
        """,
        (
            org,
            start_dt,
            end_exclusive,
            "%garments-reviewed%",
            "%complete-cleaning%",
            "%assembly-printed%",
        ),
    )
    candidate_ids = sorted(
        {str(r.get("bag_id") or "").strip().upper() for r in cursor.fetchall() or [] if r.get("bag_id")}
    )
    # Skip bags already credited from production wash/fold facts
    candidate_ids = [bid for bid in candidate_ids if bid not in covered]
    if candidate_ids:
        from backend.rinse_simple_shift_performance import _load_bag_metadata

        missing = [bid for bid in candidate_ids if bid not in meta_lookup]
        if missing:
            meta_lookup.update(_load_bag_metadata(cursor, org, missing))
    loaded = _load_scan_events_for_bags(cursor, org, candidate_ids)
    events_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in loaded:
        bid = str(ev.get("bag_id") or "").strip().upper()
        if bid:
            events_lookup[bid].append(ev)

    as_of_end = day_end
    seen: set[str] = set()
    for bid in candidate_ids:
        if bid in seen:
            continue
        events = events_lookup.get(bid) or []
        if not events:
            continue
        meta = meta_lookup.get(bid) or {}
        svc = str(meta.get("service_type") or meta.get("service_bucket") or "HD").upper()
        if svc != "HD":
            continue
        anchor = _resolve_anchor_ts(events, selected_date_et)
        if anchor is None:
            continue
        employee, comp_ts, signal = resolve_completion_attribution(
            service_type="HD",
            events=events,
            anchor_ts=anchor,
            as_of_end=as_of_end,
        )
        if comp_ts is None or not ts_valid(comp_ts):
            continue
        if comp_ts < day_start or comp_ts > day_end:
            continue
        seen.add(bid)
        from backend.rinse_employee_completed_bags import _completed_lbs

        lbs = _completed_lbs({}, meta)
        records.append(
            {
                "bag_id": bid,
                "service_type": "HD",
                "service_bucket": "HD",
                "employee_credited": employee,
                "processed_by_employee": employee,
                "processed_signal": signal,
                "processed_time": comp_ts.isoformat(),
                "processed_timestamp": comp_ts.isoformat(),
                "processed_time_et": _format_processed_time_et(comp_ts),
                "processed_lbs": lbs,
                "weight_missing": lbs is None,
                "customer_name": meta.get("name_clean") or meta.get("customer_name"),
                "attribution_reason": _attribution_reason("HD", signal),
                "is_business_completed": False,
            }
        )
    return records


def build_employee_processed_bag_records(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    registry_meta_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    completed_bag_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """All employee-attributed production events on the ET day."""
    from backend.rinse_simple_shift_performance import _load_bag_metadata

    org = int(organization_id)
    registry_meta = dict(registry_meta_by_bag or {})
    wf_records = _wf_processed_records(
        cursor,
        org,
        selected_date_et=selected_date_et,
        registry_meta_by_bag=registry_meta,
    )
    hd_records = _hd_processed_records(
        cursor,
        org,
        selected_date_et=selected_date_et,
        registry_meta_by_bag=registry_meta,
    )
    all_records = wf_records + hd_records

    missing_meta_ids = sorted(
        {
            str(r.get("bag_id") or "").strip().upper()
            for r in all_records
            if str(r.get("bag_id") or "").strip().upper() not in registry_meta
        }
    )
    if missing_meta_ids:
        loaded_meta = _load_bag_metadata(cursor, org, missing_meta_ids)
        registry_meta.update(loaded_meta)
        for record in all_records:
            bid = str(record.get("bag_id") or "").strip().upper()
            meta = registry_meta.get(bid) or {}
            if record.get("customer_name") is None:
                record["customer_name"] = meta.get("name_clean") or meta.get("customer_name")
            if record.get("processed_lbs") is None and record.get("service_type") == "HD":
                from backend.rinse_employee_completed_bags import _completed_lbs

                record["processed_lbs"] = _completed_lbs({}, meta)
                record["weight_missing"] = record["processed_lbs"] is None

    completed_set = {str(b).strip().upper() for b in (completed_bag_ids or []) if str(b).strip()}
    for record in all_records:
        bid = str(record.get("bag_id") or "").strip().upper()
        record["is_business_completed"] = bid in completed_set

    all_records.sort(key=lambda r: str(r.get("processed_time") or ""))
    return all_records


def group_processed_records_by_employee(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_employee: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, Mapping):
            continue
        employee = str(record.get("processed_by_employee") or record.get("employee_credited") or UNKNOWN_EMPLOYEE)
        by_employee[employee].append(dict(record))
    return dict(by_employee)
