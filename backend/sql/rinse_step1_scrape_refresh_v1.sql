-- Persistent Stage-B Step-1 refresh status for scheduled scrape cycles.
-- Stage A (evidence import) commits first; Stage B records refresh outcome here.

CREATE TABLE IF NOT EXISTS rinse_step1_scrape_refresh (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  scrape_run_id BIGINT NULL,
  import_batch_id INT NULL,
  affected_operations_date_et DATE NOT NULL,
  evidence_import_status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
  evidence_import_finished_at DATETIME NULL,
  step1_refresh_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  step1_refresh_started_at DATETIME NULL,
  step1_refresh_finished_at DATETIME NULL,
  step1_day_last_sync_at DATETIME NULL,
  step1_refresh_error TEXT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_step1_refresh_org_day (organization_id, affected_operations_date_et, id),
  INDEX idx_step1_refresh_status (organization_id, step1_refresh_status, updated_at),
  INDEX idx_step1_refresh_run (scrape_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
