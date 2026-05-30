-- Portal status transition timestamps (additive; safe on existing rows).
-- Backfill: current status first-seen defaults to first_seen_at when present.

ALTER TABLE rinse_cleaner_ticket_presence
  ADD COLUMN previous_portal_status VARCHAR(32) NULL AFTER portal_status,
  ADD COLUMN portal_status_first_seen_at DATETIME(6) NULL AFTER last_seen_at,
  ADD COLUMN portal_status_changed_at DATETIME(6) NULL AFTER portal_status_first_seen_at;

UPDATE rinse_cleaner_ticket_presence
SET
  portal_status_first_seen_at = COALESCE(portal_status_first_seen_at, first_seen_at),
  portal_status_changed_at = COALESCE(portal_status_changed_at, first_seen_at)
WHERE portal_status_first_seen_at IS NULL OR portal_status_changed_at IS NULL;
