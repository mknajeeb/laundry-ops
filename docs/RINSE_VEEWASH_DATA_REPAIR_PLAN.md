# VeeWash (org 3) production data repair plan

Repairs **existing** rows to match **current** Rinse/LaundryOps rules. Future uploads already use the same logic; this backfill closes the gap for batches **120 → latest**.

## Command

```bash
# Dry-run (required first — no writes)
python scripts/repair_veewash_rinse_data_current_rules.py --org 3 --from-batch 120 --to-batch latest --dry-run

# Full JSON for review
python scripts/repair_veewash_rinse_data_current_rules.py --org 3 --from-batch 120 --to-batch latest --dry-run --json

# Apply after approval
python scripts/repair_veewash_rinse_data_current_rules.py --org 3 --from-batch 120 --to-batch latest --apply
```

## Phases (idempotent)

| Phase | What it fixes |
|-------|----------------|
| A. Upload row reasons | `OK` → `UPDATED_EXISTING_BAG` for repeat active incomplete bags; wrong `ALREADY_COMPLETED` rejections |
| B. Staging | Insert/update `orders_staging` for accepted confirmed rows; flag duplicate active `ticket_id` (no blind delete) |
| C. Completion registry | Recompute from scan events: `CLEAN_RACK_SCANNED` / `NO_CLEAN_SCAN`; replace legacy reasons |
| D. Portal absence safety | List `MISSING_FROM_LATEST` bags and batches with partial scrape meta — **no auto-reversal** |
| E. Folding | Recompute `rinse_folding_performance` (exceptions, duration, multiple folding scans); skip manual overrides |
| F. Timezone | Read-only spot checks only — **no DB timestamp rewrite** |
| G. Scrape linkage | Verify `rinse_scrape_runs.imported_batch_id` for each batch |

## What is NOT changed automatically

- `MISSING_FROM_LATEST_PORTAL_UPLOAD` completion reversals (manual review)
- Duplicate active staging rows (flagged only)
- Washpro / other orgs
- Scan-event `scanned_at_parsed` values (already correct wall time)

## Related scripts

- `python -m backend.repair_upload_batch_ok_reasons` — upload `OK` → `UPDATED_EXISTING_BAG` only
- `python scripts/repair_latest_upload_batch.py` — single-batch repair (Washpro-oriented)

## ACA scraper source on `main`

As of this doc, `backend/rinse_scheduled_scrape.py`, `backend/rinse_scrape_runs.py`, `backend/jobs/run_scheduled_rinse_scrape.py`, and `Dockerfile.rinse-scheduler` are still **untracked** on `main`. The ACA job runs from ACR image `laundryops-rinse-scheduler:v4`; commit those files in a separate PR for repo/deploy parity.
