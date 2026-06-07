# Bag Volume Labor Forecast (Future)

Phase 1 stores configuration only. The **Scheduling** screen is unchanged.

## Where to configure

**Payroll → Scheduling → Settings (gear) → Bag volume forecast**

Stored in `system_settings` key `payroll_bag_volume_forecast_v1` (JSON).

Optional future SQL: `backend/sql/payroll_bag_volume_forecast_v1.sql` → `payroll_labor_speed_parameters`.

## Data model (`bag_volume_forecast`)

| Field | Purpose |
|-------|---------|
| `default_method` | `planning` \| `actual` \| `compare` |
| `global_defaults` | Default bag count, avg weight (lbs), target completion |
| `role_speed_parameters[]` | Role + stream + unit type + planning speed |
| `performance_link` | Use Rinse folding productivity, lookback days, fallback |
| `calculations_enabled` | Dev flag — still hidden from Scheduling when false |

### Unit types

- `bags_per_hour`
- `pounds_per_hour`
- `minutes_per_bag`
- `minutes_per_order`

## Forecast methods (Phase 2)

### A. Planning parameters

Uses `role_speed_parameters` from settings (management assumptions).

### B. Actual performance average

Uses worker `performance_preview` / Rinse folding productivity (same mapping as scheduling suggestions).

### C. Compare both

Side-by-side required workers, hours, cost, and delta (e.g. actual team needs one more folder).

## Roster link (Phase 2)

For a selected day/week:

- Required vs scheduled by role/stream
- Gaps, surplus, OT risk if filling gaps
- Suggested workers (same rules as **Find Replacement** — no location)
- Optional draft shift suggestions — manager saves draft before publish

## Out of scope

- Payroll batch / final pay
- Exposing rates on partner roster
- Changing current funding forecast card until explicitly wired

## Code

| Layer | File |
|-------|------|
| Backend schema | `backend/payroll_bag_volume_forecast.py` |
| Settings API | `backend/payroll_planning_settings.py` |
| Frontend settings UI | `frontend/src/components/PayrollPlanningSettings/BagVolumeForecastSettingsTab.jsx` |
| Client stub | `frontend/src/payroll/bagVolumeForecastSettings.js` |
