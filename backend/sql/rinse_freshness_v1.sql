-- Rinse continuous freshness (supervisor + watermarks + publish versions + reconcile).
-- Additive only. Does not rewrite historical scan facts.

CREATE TABLE IF NOT EXISTS rinse_freshness_watermarks (
  organization_id INT NOT NULL PRIMARY KEY,
  source_inspected_through DATETIME(6) NULL,
  source_inspected_complete TINYINT(1) NOT NULL DEFAULT 0,
  raw_imported_through DATETIME(6) NULL,
  canonical_processed_through DATETIME(6) NULL,
  chronology_processed_through DATETIME(6) NULL,
  management_published_through DATETIME(6) NULL,
  last_rolling_reconciliation DATETIME(6) NULL,
  last_deep_reconciliation DATETIME(6) NULL,
  last_fast_cycle_id BIGINT NULL,
  last_fast_result VARCHAR(32) NULL,
  updated_at DATETIME(6) NOT NULL,
  INDEX idx_rfw_mgmt (management_published_through)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_freshness_cycles (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  lane VARCHAR(16) NOT NULL, -- fast | rolling | deep
  cycle_status VARCHAR(16) NOT NULL, -- SUCCESS | DEGRADED | FAILED | RUNNING
  started_at DATETIME(6) NOT NULL,
  finished_at DATETIME(6) NULL,
  duration_seconds INT NULL,
  lease_generation BIGINT NULL,
  child_pid INT NULL,
  stage VARCHAR(64) NULL,
  meaningful_progress_at DATETIME(6) NULL,
  heartbeat_at DATETIME(6) NULL,
  portal_seconds INT NULL,
  import_seconds INT NULL,
  projection_seconds INT NULL,
  publish_seconds INT NULL,
  portal_pages INT NULL,
  portal_rows INT NULL,
  bags_affected INT NULL,
  dates_affected_json JSON NULL,
  source_inspected_complete TINYINT(1) NULL,
  batch_id BIGINT NULL,
  scrape_run_id BIGINT NULL,
  error_message VARCHAR(512) NULL,
  result_json JSON NULL,
  created_at DATETIME(6) NOT NULL,
  INDEX idx_rfc_org_started (organization_id, started_at),
  INDEX idx_rfc_org_lane_started (organization_id, lane, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_management_snapshot_versions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  version BIGINT NOT NULL,
  publish_status VARCHAR(16) NOT NULL, -- building | published | superseded | failed
  cycle_id BIGINT NULL,
  lease_generation BIGINT NULL,
  headline_json JSON NULL,
  workload_meta_json JSON NULL,
  published_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_rms_org_day_ver (organization_id, shift_date_et, version),
  INDEX idx_rms_org_day_pub (organization_id, shift_date_et, publish_status, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_reconcile_runs (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  reconcile_kind VARCHAR(16) NOT NULL, -- rolling | deep
  started_at DATETIME(6) NOT NULL,
  finished_at DATETIME(6) NULL,
  status VARCHAR(16) NOT NULL, -- RUNNING | SUCCESS | FAILED
  source_inspected INT NOT NULL DEFAULT 0,
  already_identical INT NOT NULL DEFAULT 0,
  changed INT NOT NULL DEFAULT 0,
  missing_in_db INT NOT NULL DEFAULT 0,
  backfilled INT NOT NULL DEFAULT 0,
  unresolved INT NOT NULL DEFAULT 0,
  duplicates_prevented INT NOT NULL DEFAULT 0,
  window_start_et DATETIME(6) NULL,
  window_end_et DATETIME(6) NULL,
  result_json JSON NULL,
  error_message VARCHAR(512) NULL,
  INDEX idx_rrr_org_kind_started (organization_id, reconcile_kind, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Fast-lane / reconcile-lane leases (separate from scrape lifecycle GET_LOCK).
CREATE TABLE IF NOT EXISTS rinse_freshness_lane_lease (
  organization_id INT NOT NULL,
  lane VARCHAR(16) NOT NULL, -- fast | rolling | deep
  generation BIGINT NOT NULL DEFAULT 0,
  owner_cycle_id BIGINT NULL,
  owner_pid INT NULL,
  heartbeat_at DATETIME(6) NULL,
  meaningful_progress_at DATETIME(6) NULL,
  current_stage VARCHAR(64) NULL,
  fenced_at DATETIME(6) NULL,
  fence_reason VARCHAR(255) NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (organization_id, lane)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
