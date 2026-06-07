# Scheduling / Payroll Planning — Date & Time UI QA

Modern pickers are shared across **Scheduling**, **Employee → Scheduling → Availability**, **Payroll Planning Settings (shifts)**, **Partner Roster Share**, and **Funding Forecast** (week labels follow calendar settings).

Business timezone: **America/New_York** (`frontend/src/utils/businessTime.js`). Calendar dates are `YYYY-MM-DD`; shift times are local `HH:MM` (12-hour display in UI).

## Before production testing

### Date / week

- [ ] **Today** on day view jumps to current business date (ET).
- [ ] **Next week** on week view advances work week using configured `week_starts_on` (not hard-coded Mon/Sun).
- [ ] **This week** returns to the week containing today.
- [ ] Week label shows readable range (e.g. `Mon, Jun 8 – Sun, Jun 14` based on settings).

### Shift add/edit drawer

- [ ] Select **Morning** → start/end auto-fill from shift defaults (e.g. 7:00 AM – 3:00 PM).
- [ ] Manual override still works (time picker + quick chips: 7 AM, 8 AM, …).
- [ ] Live hours: `7:00 AM – 3:00 PM = 8.0 scheduled hours`.
- [ ] With break minutes: gross vs payable line updates.
- [ ] Create **7 AM – 3 PM** shift; save draft; refresh — times unchanged.
- [ ] Create **3 PM – 11 PM** shift; validation allows end after start.

### Validation messages

- [ ] Missing start/end shows required errors; Save disabled.
- [ ] End before start shows error (unless overnight enabled later).
- [ ] Overlap same worker/day shows error.
- [ ] Outside availability / OT risk show warnings.

### Availability (worker profile)

- [ ] Edit **From/To** with compact time pickers (mobile-friendly).
- [ ] Preferred shift fills default times.

### Partner roster

- [ ] Presets: Today, Tomorrow, This week, Next week.
- [ ] Custom range with calendar pickers.

### Forecast

- [ ] Work week line on forecast card matches planner week (from API).

### Mobile

- [ ] Date/time open bottom sheet dialogs on narrow screens.
- [ ] Tap targets ≥ ~40px; no native cramped `type=date/time` on planning screens.

### Timezone

- [ ] After save + hard refresh, scheduled shift still shows **7:00 AM** (not shifted by UTC).
- [ ] Partner roster public page shows same local times.

## Components

| Component | Path |
|-----------|------|
| Business dates (ET) | `frontend/src/utils/businessTime.js` |
| Date picker | `frontend/src/components/datetime/PlanningDatePicker.jsx` |
| Week picker | `frontend/src/components/datetime/PlanningWeekPicker.jsx` |
| Time picker | `frontend/src/components/datetime/PlanningTimePicker.jsx` |
| Date range | `frontend/src/components/datetime/PlanningDateRangePicker.jsx` |
| Shift times + hours | `frontend/src/components/datetime/ShiftScheduleTimeFields.jsx` |
