# Scheduling + Partner Roster — QA Checklist

Internal dev note for validating the shift planner and partner roster share before payroll batch work.

## Employee profile (master setup)

Scheduling data is maintained on **Employee Profile → Scheduling tab** (`/employees/:user_id`), not in the shift planner.

Includes: hourly rate, max hours, OT threshold, preferred shift/role, weekly availability grid, role×stream skills matrix, location compatibility, completeness score, and readiness badge.

People list (`/employees`) shows scheduling readiness and filters (ready, missing setup, W-2/1099/Temp, Rinse/Drop Off, role skills, rate missing).

### Historical snapshot rule

- **New** schedule entries pull current profile rate/category and store snapshots on save.
- **Published** entries keep their snapshots when profile changes.
- **Draft** entries show a warning if profile rate/category changed since the draft was created.

### Profile + scheduling QA

1. Worker with no rate → warning in planner + Missing Rate badge on profile/People.
2. No availability → warning + Missing Availability badge.
3. No skills → warning + Missing Role/Stream badge.
4. Shift outside availability window → planner warning.
5. Wrong role/stream → planner warning.
6. Location outside assigned geofences → planner warning.
7. OT threshold exceeded → OT risk warning.
8. Update rate in profile → new entries use new rate; published entries unchanged.
9. Partner roster still hides rates, category, OT, performance.

## Worker profile as source of truth

Scheduling **never duplicates** employee data in the form. When a manager selects a worker:

1. Category, hourly rate, role skills, work streams, availability, preferred shift/role, max hours, and OT threshold are read from `payroll_worker_profiles` (+ skills/availability tables).
2. The form auto-fills shift, role, and stream from profile preferences when possible.
3. Warnings appear for availability conflicts, skill mismatches, missing rate, inactive worker, etc.
4. On save, snapshots are stored on the entry (`hourly_rate_snapshot`, `worker_category_snapshot`, `role_snapshot`, `work_stream_snapshot`, `shift_snapshot`) for historical accuracy.
5. **Open worker profile** links go to `/employees/:user_id` — fix missing data in People, not on the schedule form.

Partner roster still exposes only allowed fields (no rates, category, OT, or performance unless explicitly enabled on the share link).

## Worker identity mapping

| Module | Source | Key |
|--------|--------|-----|
| Clock / attendance | `users.id` | Canonical person |
| Payroll profiles | `payroll_profiles.user_id` → `users.id` | HR / W-4 |
| Scheduling | `payroll_worker_profiles.user_id` → `users.id` | Planner cards |
| Performance preview | `rinse_folding_user_map.user_id` → `users.id` | Optional enrichment only |

Scheduling does **not** create duplicate people. `payroll_worker_profiles` is auto-provisioned from active payroll users when the plan bundle loads.

## Payroll planning settings UI (admin)

**Payroll → Scheduling → gear icon (Settings)** — requires `ta.settings` / admin.

Tabs: Shifts, Work streams, Roles, Coverage targets, Payroll calendar (W-2 / 1099 / Temp), Scheduling rules, Forecast assumptions (placeholder), Machine capacity (placeholder).

APIs: `GET/POST /api/ta/payroll/schedule/settings`, `GET/POST /api/ta/payroll/schedule/coverage-targets`, `GET/PUT /api/ta/payroll/calendar-settings`, `GET/PUT /api/ta/payroll/planning-maintenance`.

## Parameterized settings (not hard-coded in logic)

Defaults are seeded per org in DB tables / settings:

| Setting | Source |
|---------|--------|
| Shift names (Morning, Afternoon, …) | `payroll_shifts` |
| Work streams (Rinse, Drop Off, Both) | `payroll_work_streams` |
| Roles (Operator, Folder) | `payroll_roles` |
| Work week start | `payroll_period_settings.week_starts_on` (0=Mon) |
| OT threshold | `payroll_schedule_org_settings.overtime_threshold_hours` (40) |
| Underused / heavy hours | `underused_hours_threshold` / `heavy_hours_threshold` |
| Payment day | `payment_day_of_week` (6=Sat) |
| Coverage targets | `payroll_schedule_coverage_targets` |

## Draft vs published

- Local edits and **Save draft** → `publish_status = draft`
- **Publish week** → drafts in range become `published`
- Partner roster default: `published_only = true` — drafts are **never** visible unless explicitly toggled off on the link

Public roster exposes only: date, shift, worker name, role, work stream, start/end time, status (+ optional phone/category if enabled on link).

Never exposed: hourly rates, estimated cost, OT risk, internal notes, documents.

## Real-time recalculation (before save)

These update instantly when adding/editing/removing shifts locally:

- Total people scheduled
- Morning / Afternoon counts
- Rinse / Drop Off counts
- Operator / Folder counts
- Total scheduled hours
- Estimated labor cost
- Overtime risk count
- Coverage gaps

OT preview in the add/edit drawer warns when a shift would push a worker over the configured weekly threshold.

## Manual test checklist

1. **Create Monday Morning Rinse Operator shift** — Payroll → Scheduling → Day view → + → pick worker, Morning, Rinse, Operator.
2. **Add Folder to same shift** — + again on Morning card or same shift/stream.
3. **OT warning** — Add shifts for a worker until weekly hours approach 40h; confirm drawer shows OT warning before save.
4. **Copy previous day** — Copy prev day on an empty day; confirm entries appear as draft.
5. **Save draft** — Save draft; refresh page; draft persists.
6. **Partner link hides draft** — Create share link (published only). Open `/roster/:token` — roster empty or shows prior published only.
7. **Publish week** — Publish week; confirm success toast and published count in header.
8. **Partner link shows roster** — Reload public link; published shifts visible.
9. **Revoke link** — Revoke in Share drawer; public URL shows friendly “revoked” message.
10. **PIN link** — Create link with PIN; verify PIN gate and wrong-PIN rejection.

### Additional checks

- Mark worker **absent** → status sick; use **Replace** → pick suggestion → original marked replaced, replacement added.
- Edit shift times → summary hours/cost update without save.
- Delete/remove shift → counts drop immediately.
- Expired link (set `expires_at` in past) → friendly expired message.
- Invalid token → friendly invalid message.

## Audit / change log

Backend `payroll_schedule_change_log` records: create, update, delete, mark_absent, replace_worker, publish — with actor, old/new JSON, timestamp, optional note. Populated on save-draft and publish.

## Automated tests

```bash
# Backend
pytest backend/tests/test_payroll_schedule.py backend/tests/test_payroll_roster_share.py backend/tests/test_payroll_funding_forecast.py -q

# Frontend planner math
npm test -- --testPathPattern=schedulePlanner
```

## Payroll funding forecast

API: `GET /api/ta/payroll/funding-forecast?date=YYYY-MM-DD`  
Settings: `GET/PUT /api/ta/payroll/calendar-settings`

- **Estimated/projected only** — not final payroll
- W-2 / 1099 / Temp breakdown, draft vs published split, daily/shift/stream/role/worker breakdown
- OT risk for W-2 (1099/Temp only if category `overtime_enabled`)
- Excludes cancelled/replaced/absent/no-show; sick tracked separately
- Scheduling screen shows live forecast card (updates with draft edits)
- Partner roster: no rates or costs

Run migration: `backend/sql/payroll_calendar_settings_v1.sql` (or auto-create on first API call)

## Not in scope yet

Payroll batch creation, approved hours, and accountant export — next phase after funding forecast is stable.
