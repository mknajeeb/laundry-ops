-- Daily Operations Phase 1C — HD bag production fact + audits.
-- Runtime ensure also in backend/daily_operations_hd.ensure_hd_production_tables().

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS hd_day_bag_production (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  operations_date_et DATE NOT NULL,
  day_bag_id BIGINT NULL,
  bag_id VARCHAR(32) NOT NULL,
  washed_by_user_id INT NULL,
  washed_by_name_snapshot VARCHAR(255) NULL,
  washed_by_override_name VARCHAR(255) NULL,
  folded_by_user_id INT NULL,
  folded_by_name_snapshot VARCHAR(255) NULL,
  folded_by_override_name VARCHAR(255) NULL,
  total_items INT NULL,
  revenue DECIMAL(12,2) NULL,
  zero_items_reason_code VARCHAR(64) NULL,
  zero_items_reason_note VARCHAR(512) NULL,
  zero_revenue_reason_code VARCHAR(64) NULL,
  zero_revenue_reason_note VARCHAR(512) NULL,
  notes TEXT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'NOT_RECORDED',
  created_by_user_id INT NULL,
  updated_by_user_id INT NULL,
  version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_hd_day_bag_prod (organization_id, operations_date_et, bag_id),
  INDEX idx_hd_day_bag_prod_status (organization_id, operations_date_et, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hd_day_bag_production_audits (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  operations_date_et DATE NOT NULL,
  bag_id VARCHAR(32) NOT NULL,
  production_fact_id BIGINT NULL,
  action VARCHAR(64) NOT NULL,
  version_before INT NULL,
  version_after INT NULL,
  before_json JSON NULL,
  after_json JSON NULL,
  reason VARCHAR(512) NULL,
  actor_user_id INT NULL,
  actor_display_name VARCHAR(255) NULL,
  is_undo TINYINT(1) NOT NULL DEFAULT 0,
  undone_audit_id BIGINT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_hd_bag_prod_aud_bag (organization_id, operations_date_et, bag_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
