-- Evidence-first Presence Run Rows: typed portal observations + processing markers.
-- Apply via ensure_* helpers (idempotent ALTER) or run manually on deploy.

-- Typed evidence columns on immutable run rows
ALTER TABLE rinse_cleaner_ticket_presence_run_rows
  ADD COLUMN IF NOT EXISTS weight_num DECIMAL(10, 4) NULL,
  ADD COLUMN IF NOT EXISTS weight_raw VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS wf_lbs_num DECIMAL(10, 4) NULL,
  ADD COLUMN IF NOT EXISTS wf_lbs_raw VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS hd_count_num INT NULL,
  ADD COLUMN IF NOT EXISTS hd_count_raw VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS wf_items_num INT NULL,
  ADD COLUMN IF NOT EXISTS wf_items_raw VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS observed_at DATETIME(6) NULL,
  ADD COLUMN IF NOT EXISTS source_row_seq INT NOT NULL DEFAULT 1;

-- Processing markers on presence runs (idempotent stage machine)
ALTER TABLE rinse_cleaner_ticket_presence_runs
  ADD COLUMN IF NOT EXISTS evidence_processing_stage VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS evidence_failed_stage VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS evidence_processing_error TEXT NULL,
  ADD COLUMN IF NOT EXISTS evidence_processing_json JSON NULL;

-- Migration aid: upload_batch_rows weights that could not map onto a run row
CREATE TABLE IF NOT EXISTS rinse_weight_observation_migration_archive (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  weight_num DECIMAL(10, 4) NULL,
  observed_at DATETIME(6) NULL,
  upload_batch_id BIGINT NULL,
  matched_presence_run_id BIGINT NULL,
  matched_presence_run_row_id BIGINT NULL,
  status VARCHAR(32) NOT NULL,
  detail_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY idx_weight_mig_org_bag (organization_id, bag_id),
  KEY idx_weight_mig_status (organization_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
