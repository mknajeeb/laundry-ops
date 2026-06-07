# Auto Roster Builder (Phase 1)

Rule-based draft schedule generation for **Payroll → Scheduling**. Does not publish automatically.

## How to use

1. Open **Payroll → Scheduling** (admin / `ta.settings`).
2. Click **Generate draft roster**.
3. Configure date range, location, streams, shifts, and rules.
4. Click **Generate draft roster** — review assignments, gaps, and conflicts.
5. **Accept draft into planner** — edits appear on the board as draft entries.
6. Adjust manually, **Save draft**, then **Publish week** when ready.

## Generator rules (priority)

1. Worker availability (day + time window)
2. Role and work stream skill match
3. Avoid overtime (optional)
4. Location / geofence compatibility
5. Preferred shift (profile or day-level)
6. Balance hours — favor underused workers (optional)
7. Performance preview (bags/hr) when enabled
8. Lower hourly rate as tie-breaker

## API

`POST /api/ta/payroll/schedule/generate-roster`

Body fields: `start_date`, `end_date`, `geofence_id`, `work_stream_ids`, `shift_ids`, `use_coverage_targets`, `avoid_overtime`, `balance_hours`, `prefer_strong_performers`, `active_workers_only`, `include_incomplete_profiles`, `clear_existing_drafts_in_range`, `max_hours_per_worker`, `notes`.

Response: `proposed_entries`, `assignments` (with reasons), `gap_report`, `conflict_report`, `summary`.

## Future (not in Phase 1)

Natural-language AI assistant on top of the same draft/publish flow.
