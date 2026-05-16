-- Phase 2: portal snapshot + audit columns on rinse_bag_registry.
ALTER TABLE rinse_bag_registry
  ADD COLUMN IF NOT EXISTS rush_type VARCHAR(20) NULL,
  ADD COLUMN IF NOT EXISTS last_seen_upload_batch_id INT NULL,
  ADD COLUMN IF NOT EXISTS last_seen_at DATETIME NULL;
