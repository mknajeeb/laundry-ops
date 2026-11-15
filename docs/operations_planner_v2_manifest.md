# Operations Planner v2 manifest

Baseline: origin/main `86596a21` (frontend production presentation of the weekly schedule).
Production API at inspection: `50b126a3`, the parent of that commit.
Branch: `feature/operations-planner-v2` in worktree `/Users/kamisb./laundry_app-ops-planner-v2`.

## Reused

- `planned_weekly_schedule_entries` and `build_week_payload` for the grid, labor redaction, and Rinse visibility.
- Existing shift validation (`create_entry` / `update_entry` / `delete_entry`).
- Task rows already returned as `daily_responsibilities`. Shared groups stay one group.
- Finalized W-2 paystubs from `generate_paystub_html`. No estimated stub is rendered.
- Attendance hours from `list_time_records` (Eastern wall clocks). Overtime is shown only when a record already has `overtime_hours`.

## Added

- Recurrence patterns, one-week exceptions, draft/approved/published revisions.
- Every apply asks for scope. Approved or published weeks, and later one-time exceptions, are included only after an explicit choice. Included published weeks return to draft and keep the previous employee snapshot.
- Weeks before the current America/New_York schedule week are rejected.
- Feature flags default off: manager pilot, employee pilot, paystub access.
- Employee PIN routes under `/api/public/attendance/pin-planner/`. Identity is the hub token. Paystubs also require a five-minute step-up (PIN plus HR date of birth) and are `Cache-Control: no-store`.

## Migration

`backend/sql/operations_planner_v2.sql` creates new tables only. It does not alter schedule, attendance, or payroll tables.
The same statements run on first manager use of the planner. A PIN login does not create them.
Rollback of the app code leaves the new tables in place. They are unused when the flags are off. Do not drop them to roll back; they hold the only copy of patterns and publication snapshots.

## Shared files touched

- `backend/app.py` — route registration.
- `backend/employee_pin_hub.py` — three tiles, default hidden until the pilot and the employee toggle are on.
- `frontend/src/App.jsx`, `tenantNav.js`, `translations.js`, `api.js`, `buildPinLauncherTiles.js`.
- The existing weekly schedule page is unchanged.

## Not deployed

No push, production migration, or production data change.
