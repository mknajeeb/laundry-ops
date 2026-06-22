"""Employer affiliation on payroll worker profiles — Rinse Exclusive, VeeWash, or Both."""

from __future__ import annotations

from typing import Any, Mapping

EMPLOYER_AFFILIATION_RINSE = "rinse_exclusive"
EMPLOYER_AFFILIATION_VEEWASH = "veewash"
EMPLOYER_AFFILIATION_BOTH = "both"
VALID_EMPLOYER_AFFILIATIONS = frozenset(
    {EMPLOYER_AFFILIATION_RINSE, EMPLOYER_AFFILIATION_VEEWASH, EMPLOYER_AFFILIATION_BOTH}
)


def _stream_flag(value: Any) -> bool:
    return value is not False and value != 0


def employer_affiliation_from_flags(worker: Mapping[str, Any] | None) -> str:
    """Derive affiliation from payroll_worker_profiles stream flags."""
    if not worker:
        return EMPLOYER_AFFILIATION_VEEWASH
    rinse = _stream_flag(worker.get("can_work_rinse"))
    drop_off = _stream_flag(worker.get("can_work_drop_off"))
    both = _stream_flag(worker.get("can_work_both"))
    if rinse and drop_off and both:
        return EMPLOYER_AFFILIATION_BOTH
    if rinse and not drop_off and not both:
        return EMPLOYER_AFFILIATION_RINSE
    if not rinse and drop_off and not both:
        return EMPLOYER_AFFILIATION_VEEWASH
    if rinse and not drop_off:
        return EMPLOYER_AFFILIATION_RINSE
    if drop_off:
        return EMPLOYER_AFFILIATION_VEEWASH
    return EMPLOYER_AFFILIATION_VEEWASH


def flags_from_employer_affiliation(affiliation: str) -> dict[str, bool]:
    aff = str(affiliation or "").strip().lower()
    if aff == EMPLOYER_AFFILIATION_RINSE:
        return {
            "can_work_rinse": True,
            "can_work_drop_off": False,
            "can_work_both": False,
        }
    if aff == EMPLOYER_AFFILIATION_BOTH:
        return {
            "can_work_rinse": True,
            "can_work_drop_off": True,
            "can_work_both": True,
        }
    return {
        "can_work_rinse": False,
        "can_work_drop_off": True,
        "can_work_both": False,
    }


def normalize_employer_affiliation(raw: Any) -> str | None:
    aff = str(raw or "").strip().lower()
    if aff in VALID_EMPLOYER_AFFILIATIONS:
        return aff
    return None


def list_employer_affiliation_rows(conn, organization_id: int) -> list[dict[str, Any]]:
    from backend.payroll_schedule import list_schedule_workers_for_grid

    rows: list[dict[str, Any]] = []
    for worker in list_schedule_workers_for_grid(conn, int(organization_id)):
        aff = employer_affiliation_from_flags(worker)
        rows.append(
            {
                "user_id": int(worker.get("user_id") or 0),
                "worker_profile_id": worker.get("worker_profile_id") or worker.get("id"),
                "display_name": worker.get("display_name") or worker.get("worker_name") or "",
                "employer_affiliation": aff,
                "can_work_rinse": bool(worker.get("can_work_rinse")),
                "can_work_drop_off": bool(worker.get("can_work_drop_off")),
                "can_work_both": bool(worker.get("can_work_both")),
            }
        )
    rows.sort(key=lambda row: (row.get("display_name") or "").casefold())
    return rows


def save_employer_affiliation(
    conn,
    organization_id: int,
    user_id: int,
    affiliation: str,
) -> dict[str, Any]:
    from backend.payroll_schedule import get_worker_by_user_id, save_scheduling_profile

    aff = normalize_employer_affiliation(affiliation)
    if not aff:
        raise ValueError("employer_affiliation must be rinse_exclusive, veewash, or both")
    flags = flags_from_employer_affiliation(aff)
    save_scheduling_profile(conn, int(organization_id), int(user_id), flags)
    worker = get_worker_by_user_id(conn, int(organization_id), int(user_id))
    return {
        "user_id": int(user_id),
        "worker_profile_id": worker.get("id"),
        "display_name": worker.get("display_name") or worker.get("worker_name") or "",
        "employer_affiliation": aff,
        **flags,
    }
