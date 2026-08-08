# Business Time Contract

**Status:** Permanent project invariant (not an inspection finding).

All business logic, investigations, checkpoints, validations, UI reasoning, and
STOP reports use **America/New_York (Eastern Time)**.

UTC is permitted **only** for storage, infrastructure internals, scheduler
internals, and low-level debugging. UTC must **never** be the basis for a
business decision without an explicit conversion to Eastern first.

## Layers

| Layer | Timezone |
|-------|----------|
| Storage | UTC |
| Infrastructure | UTC |
| Scheduler | UTC |
| Business Logic | America/New_York **ONLY** |
| UI | America/New_York **ONLY** |
| Reports | America/New_York **ONLY** |
| Logs | ET first; UTC optional in parentheses |

## In scope (ET only)

- Selected Day, Opening / Closing of Day
- Opening Carryover, Added During Day, Completed Before Opening
- Rush / Non-Rush, Membership, Current Cycle, Completion Canonical
- Stage-B, Snapshot timestamps, `last_sync_at` (display and day meaning)
- Refresh / evidence / chronology windows
- Replay, historical repair, productivity, supply usage, review rules
- STOP reports and validation reports

## Hard comparison rule

Business decisions must **never** compare:

1. A UTC datetime against an ET calendar date, or
2. A UTC datetime against a naive datetime of unknown zone.

Convert first to an **America/New_York timezone-aware** datetime (or use the
documented Rinse **naive ET wall** convention for `scanned_at_parsed` and
related portal fields), then compare.

## Infrastructure UTC (keep)

These remain UTC storage/ops clocks:

- scrape `started_at` / `finished_at`
- scheduler / ACA timestamps
- DB and lock timestamps

**Never** decide membership, carryover, completion, review, productivity, or
supply directly from them. Convert with project helpers first.

## Canonical helpers

| Area | Helper |
|------|--------|
| Business calendar | `backend/business_time.py` (`business_today`, `business_now`) |
| Scan wall vs system UTC | `backend/rinse_scan_time.py` |
| ET day bounds | `backend/rinse_folding_et.py` |
| UI display | `formatFriendlyEtWall` / `formatBusinessDateTime` / `formatEasternDateTime` |

Do **not** use `date.today()`, bare `datetime.now()`, or `datetime.utcnow().date()`
for business-facing day selection without going through ET conversion.

## Report timestamp format

```
2026-08-08 12:42:30 ET
(16:42:30 UTC)
```

Not UTC-first.
