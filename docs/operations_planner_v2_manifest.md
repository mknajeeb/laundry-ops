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

Version `operations_planner_v2.2` in `backend/sql/operations_planner_v2.sql`. The new table is `ops_planner_paystub_codes`.

Apply that file explicitly. Startup, opening the planner, and PIN login do not create or alter tables. If the tables are missing, manager and employee planner routes return `migration_required` and the PIN tiles stay off.

Order: this file only. It does not alter schedule, attendance, payroll, users, or task tables.
Compatibility: the existing weekly schedule keeps working when these tables are absent.
Rollback: leave the tables and keep `ops_planner_org_flags` at 0. Do not drop them to undo the app; they hold patterns, exceptions, and published snapshots. Dropping them does not restore attendance or payroll.

A recurrence edit closes only the pattern that covers the edited week. A later effective-dated pattern stays unless the manager chooses “Replace that later schedule.” Selected dates are the Mondays that start full Monday–Sunday weeks.

Recurring tasks call the existing `create_responsibility` path. A responsibility that already has task activity is not deleted or rewritten. Shared tasks stay one assignment group. If the existing task table is missing, the save stops and the planner does not create it.

Full screen sets `data-ops-planner-fullscreen` on the document. The app shell hides the tenant sidebar and restores it when full screen ends. Day-timeline handles resize the shift, a role segment, or a break. Arrow keys on a handle move that edge by 15 minutes. Releasing the handle opens the same scope confirmation as every other save. A failed apply rolls the transaction back before commit.

## Paystub security

PIN plus date of birth is not adequate for paystubs on a shared device. The step-up compares a single-use code hash with the employee on the hub token. A code for another employee, a used code, or an expired code fails. A date of birth by itself is rejected. The settings API still refuses to turn `paystub_access` on, and the step-up route returns `module_disabled` while that flag is off. Documents stay W-2 only, `Cache-Control: no-store`, and only what `generate_paystub_html` already renders.

## Shared files touched

- `backend/app.py` — route registration.
- `backend/employee_pin_hub.py` — three tiles, default hidden until the pilot and the employee toggle are on.
- `frontend/src/App.jsx`, `tenantNav.js`, `translations.js`, `api.js`, `buildPinLauncherTiles.js`.
- The existing weekly schedule page is unchanged.

## Not deployed

No push, production migration, or production data change.
