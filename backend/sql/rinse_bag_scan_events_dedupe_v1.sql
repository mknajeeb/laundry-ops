-- Idempotent scan-events: one row per logical scan per bag.
-- Run once on production after deploy; runtime ensure_* also adds column/index when missing.

ALTER TABLE rinse_bag_scan_events
  ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(64) NULL AFTER bag_id;

-- Backfill dedupe_key in application or scripts/dedupe_rinse_bag_scan_events.py before enforcing NOT NULL.

-- After backfill + duplicate delete:
-- ALTER TABLE rinse_bag_scan_events MODIFY dedupe_key VARCHAR(64) NOT NULL;
-- CREATE UNIQUE INDEX uq_rbse_org_bag_dedupe ON rinse_bag_scan_events (organization_id, bag_id, dedupe_key);
