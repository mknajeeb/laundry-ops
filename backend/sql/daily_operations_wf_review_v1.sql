-- Daily Operations Phase 1B — WF bag revenue fact + review audits.
-- Runtime ensure also in backend/daily_operations_wf_review.ensure_wf_review_tables().

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS wf_day_bag_revenue (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  operations_date_et DATE NOT NULL,
  day_bag_id BIGINT NULL,
  bag_id VARCHAR(32) NOT NULL,
  authoritative_post_weight_lbs DECIMAL(10,4) NULL,
  post_weight_source VARCHAR(64) NULL,
  post_weight_scan_event_id BIGINT NULL,
  post_weight_presence_run_id BIGINT NULL,
  post_weight_presence_run_row_id BIGINT NULL,
  post_weight_corrected TINYINT(1) NOT NULL DEFAULT 0,
  original_post_weight_lbs DECIMAL(10,4) NULL,
  post_weight_correction_reason VARCHAR(512) NULL,
  estimated_weight_revenue DECIMAL(12,2) NULL,
  workitem_revenue DECIMAL(12,2) NOT NULL DEFAULT 0,
  estimated_total_revenue DECIMAL(12,2) NULL,
  review_status VARCHAR(32) NOT NULL DEFAULT 'REVIEW_REQUIRED',
  review_resolution VARCHAR(64) NULL,
  reviewed_by_user_id INT NULL,
  reviewed_at DATETIME NULL,
  notes TEXT NULL,
  version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wf_day_bag_rev (organization_id, operations_date_et, bag_id),
  INDEX idx_wf_day_bag_rev_status (organization_id, operations_date_et, review_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wf_day_bag_revenue_audits (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  operations_date_et DATE NOT NULL,
  bag_id VARCHAR(32) NOT NULL,
  wf_day_bag_revenue_id BIGINT NULL,
  action VARCHAR(64) NOT NULL,
  version_before INT NULL,
  version_after INT NULL,
  before_json JSON NULL,
  after_json JSON NULL,
  reason VARCHAR(512) NULL,
  actor_user_id INT NULL,
  actor_display_name VARCHAR(255) NULL,
  is_undo TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_wf_bag_rev_aud_bag (organization_id, operations_date_et, bag_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
