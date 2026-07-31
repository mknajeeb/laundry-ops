-- Durable Stage-B evidence gate keyed by scan-import batch.
-- Incomplete / deferred timeline imports must block day-bag & headline persistence
-- until a later complete batch clears the org tip.

CREATE TABLE IF NOT EXISTS rinse_step1_evidence_gate (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  import_batch_id INT NOT NULL,
  scrape_run_id BIGINT NULL,
  portal_presence_run_id BIGINT NULL,
  evidence_generation_id VARCHAR(64) NULL,
  gate_status VARCHAR(64) NOT NULL,
  gate_reason VARCHAR(128) NULL,
  import_incomplete TINYINT(1) NOT NULL DEFAULT 0,
  timeline_replacement_deferred TINYINT(1) NOT NULL DEFAULT 0,
  coverage_incomplete TINYINT(1) NOT NULL DEFAULT 0,
  invalid_for_step1_rebuild TINYINT(1) NOT NULL DEFAULT 0,
  detail_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_step1_evidence_gate_batch (organization_id, import_batch_id),
  INDEX idx_step1_evidence_gate_org_status (organization_id, gate_status, import_batch_id),
  INDEX idx_step1_evidence_gate_scrape (scrape_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
