-- Daily Operations Phase 1A — day header (org 3, ET day from 2026-07-23).
-- Runtime ensure also exists in backend/daily_operations.ensure_daily_operations_tables().

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS daily_operations_days (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  operations_date_et DATE NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
  wf_rate_plan_id INT NULL,
  pricing_schedule_snapshot_json JSON NULL,
  mtd_pounds_before DECIMAL(12,2) NULL,
  today_wf_completed_pounds DECIMAL(12,2) NULL,
  tier1_pounds_today DECIMAL(12,2) NULL,
  tier2_pounds_today DECIMAL(12,2) NULL,
  tier1_revenue_today DECIMAL(12,2) NULL,
  tier2_revenue_today DECIMAL(12,2) NULL,
  wf_weight_revenue DECIMAL(12,2) NULL,
  mtd_pounds_after DECIMAL(12,2) NULL,
  missing_post_weight_count INT NOT NULL DEFAULT 0,
  outstanding_workitem_review_count INT NOT NULL DEFAULT 0,
  pricing_incomplete TINYINT(1) NOT NULL DEFAULT 0,
  diagnostics_json JSON NULL,
  closed_at DATETIME NULL,
  closed_by_user_id INT NULL,
  reopened_at DATETIME NULL,
  reopened_by_user_id INT NULL,
  version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_daily_ops_org_date (organization_id, operations_date_et),
  INDEX idx_daily_ops_org_status (organization_id, status, operations_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
